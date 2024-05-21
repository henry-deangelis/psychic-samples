##################################
# Copyright © 2024 Henry DeAngelis
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Apache License Version 2.0
# which accompanies this distribution, and is available at
# https://www.apache.org/licenses/LICENSE-2.0
#################################

import os
import sys
import argparse
import time
import datetime
from datetime import datetime
import pathvalidate
from pathvalidate import ValidationError
import logging
import shlex
import re
import json
import urllib
from urllib.parse import unquote
import statsd

# This is a log parser tool which parsers lines in the commong log format:
#   https://en.wikipedia.org/wiki/Common_Log_Format
# An example would be logs from the nginx load balancer

cmdLineArgs = None
inputFile = None
outputFile = None
maxClientIPs = None
maxPaths = None
logLevel = None
verboseLog = None

def getArgs():
    # Purpose:  Get and validate command line flags
    #   Sets values of flags in global variables
    # Returns:
    #   1 - If flag values are not valid
    #   0 - Otherwise
    rc = 0
    global cmdLineArgs
    global inputFile
    global outputFile
    global maxClientIPs
    global maxPaths
    global verboseLog

    cmdArgParser = argparse.ArgumentParser(description='Parse nginx logs')
    cmdArgParser.add_argument('-i', '--in', dest='infilearg', type=str, required=True,
          help="input log file (nginx log entries)")
    cmdArgParser.add_argument('-o', '--out', dest='outfilearg', type=str, required=True,
          help="output JSON file")
    cmdArgParser.add_argument('-c', '--max-client-ips', dest='maxipsarg', type=int, default='10',
          help="maximum number of results to output in the top_client_ips field. Defaults to 10")
    cmdArgParser.add_argument('-p', '--max-paths', dest='maxpathsarg', type=int, default='10',
          help="maximum number of results to output on the top_path_avg_seconds field. Defaults to 10")
    cmdArgParser.add_argument('-v','--verbose', action='count', default=0, dest='verbosearg',
          help="verbose debug output for stdout (overrides value of THELOGFILE env variable if set)")

    cmdLineArgs = cmdArgParser.parse_args()
    myLogger.debug(f"Command line arguments are: {cmdLineArgs}")
    
    # Check for verbose argument, which will overrise THELOGLEVEL env variable if set
    verboseLog = cmdLineArgs.verbosearg
    if verboseLog != 0:
        myLogger.warning("Changing log level to DEBUG since verbose argument was specified. Any value of THELOGLEVEL env variable is overridden.")
        myLogger.setLevel(logging.DEBUG)

    # Check input file argument
    inputFile = cmdLineArgs.infilearg
    if not os.path.exists(inputFile):
        myLogger.error(f"Cannot find input file: {inputFile}")
        rc = 1
    elif not os.access(inputFile, os.R_OK):
        myLogger.error(f"No read access to input file: {inputFile}")
        rc = 1
    else:
        myLogger.info(f"Input file to be parsed is: {inputFile}")

    # Check output file argument
    outputFile = cmdLineArgs.outfilearg
    if os.path.exists(outputFile):
        myLogger.warn(f"Output file already exists and will be overwritten: {outputFile}")
    try:
        fd = open(outputFile, 'w')
    except Exception as e:
        myLogger.error(f"Output file cannot be opened for writing: {outputFile}")
        rc = 1
    else:
        fd.close()
        os.remove(outputFile)
        myLogger.info(f"Output file to be used for parsing results is:  {outputFile}")
    
    # Check max-client-ips argument
    maxClientIPs = cmdLineArgs.maxipsarg
    if maxClientIPs < 0 or maxClientIPs > 10000:
        myLogger.error("Value of {} for max-client-ips is not between 0 and 10000".format(maxClientIPs))
        rc = 1
    else:
        myLogger.info("max-client-ips is set to {}".format(maxClientIPs))
    
    # Check max-paths argument
    maxPaths = cmdLineArgs.maxpathsarg
    if maxPaths < 0 or maxPaths > 10000:
        myLogger.error("Value of {} is not between 0 and 10000".format(maxPaths))
        rc = 1
    else:
        myLogger.info("max-paths is set to {}".format(maxPaths))

    return rc

def validateRemoteIPAddress(ipAddressToken):
    # Purpose:  Validate a string to be sure it has the format of
    #   an IP address.  For example:  "10.151.160.7"
    #   Insert the IP address into the provided dictionary if it
    #   does not already exist.  If it does, increment the count.
    # Arguments:
    #   ipAddressToken -    parsed token of log entry representing
    #       IP address string
    # Returns:
    #   False - IP address string is not valid
    #   True - valid IP address String
    parsedIP = ipAddressToken.split(".")
    myLogger.debug(f"Parsed IP Address string is {parsedIP}")
    if len(parsedIP) != 4:
        return False
    for ipAddr in parsedIP:
        if not ipAddr.isnumeric():
            return False
        elif int(ipAddr) < 0 or int(ipAddr) > 255:
            return False
    return True

def validateTimestamp(timeAndDateToken, timeZoneToken):
    # Purpose: Validate string for format of timestamp in
    #   common log format, for example:  [10/Oct/2000:13:55:36 -0700]
    # Arguments:
    #   timeStampField -    date/time portion of timestamp
    #   timeZoneField -     time zone portion of timestamp
    # Returns:
    #   True    - if string is a valid date/time
    #   False   - otherwise
    timeStampAndZone = timeAndDateToken + " " + timeZoneToken
    myLogger.debug(f"timeStampAndZone is {timeStampAndZone}")
    if timeStampAndZone[0] != '[' or timeStampAndZone[-1] != ']':
        myLogger.error(f"Timestamp not enclosed in square brackets: {timeStampAndZone}")
        return False
    else:
        timeToFormat = timeStampAndZone[1:-1]
        try:
            dateObject = datetime.strptime(timeToFormat, '%d/%b/%Y:%H:%M:%S %z')
        except ValueError:
            myLogger.error(f"Exception {str(ValueError)} while validating timestamp {timeToFormat}")
            return False
        return True
    
def validateHttpRequest(httpRequestField, validResourcePath):
    # Purpose:  Validate string for format of an HTTP request field in
    #   common log format, including the HTTP method (operation),
    #   resource path, and HTTP version.  For example:
    #   "GET /admin.php HTTP/1.1"
    #
    # If validation is successful, the resource path name is added
    # to the validResourcePath argument passed to this function
    #   
    # Arguments:
    #   httpRequestField (in) - parsed token of log entry containing the 
    #       method resource path, and http version
    #   validResourcePath (out) - List with 1 entry having the resource path
    # Returns
    #   True:   if valid Http request format
    #   False:  otherwise

    # Split up the request into HTTP method, resource path and HTTP version
    try:
        httpRequestTokens = shlex.split(httpRequestField)
    except Exception as e:
        myLogger.error("Exception parsing http request tokens: {}".format(e))
        return False
    except:
        myLogger.error("Unknown exception parsing http request tokens")
        return False
    myLogger.debug("http request tokens are {}".format(httpRequestTokens))

    # httpRequestField should have 3 parts
    if len(httpRequestTokens) != 3:
        return False
    
    # Check HTTP request method name
    # Note that HTTP method / operation names have evolved over time,
    # and different servers may support different methods
    myLogger.debug(f"Validating HTTP request method name.")
    httpMethods = [ 'OPTIONS', 'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'TRACE', 'CONNECT', 'PATCH']
    if httpRequestTokens[0] not in httpMethods:
        myLogger.error(f"HTTP request method name is not valid: {httpRequestTokens[0]}")
        return False
    
    # Check resource path name
    # 
    # For now, the resource path name is just urldecoded.
    # Other than this, the path name is accepted.
    # Earlier versions of this tool attempted to perform more validation on the
    # resource path name.  But determine valid characters / paths on all platforms 
    # for all possible paths is challenging, and likely not necssary.
    #
    decodedResourcePath = urllib.parse.unquote(httpRequestTokens[1])
    #try:
    #    pathvalidate.is_valid_filepath(urlDecodedPath)
    #    validResourcePath.append(urlDecodedPath)
    #except ValidationError as e:
    #    myLogger.error("Exception during resource path validation: {}".format(e))
    #    return False
    #except:
    #    myLogger.error("Unknown exception during resoruce path validation. ")
    #    return False
    validResourcePath.append(decodedResourcePath)
    
    
    # Check HTTP protocol
    # The HTTP should have the format of "HTTP/X.Y"
    # where the string "HTTP" is followed by a "/"
    # and then both major and minor version number
    #
    # Previously this script checked for version numbers via membership in a list
    # of known HTTP versions, but such a list is elusive.
    httpVersionParts = httpRequestTokens[2].split("/")
    myLogger.debug(f"httpVersionParts is {httpVersionParts}")
    
    if len(httpVersionParts) == 2 and  httpVersionParts[0] == "HTTP":
        versionNumber = httpVersionParts[1].split(".")
        if len(versionNumber) == 2 and versionNumber[0].isnumeric() and versionNumber[1].isnumeric():
            # Version number is good.
            # This is the last check, so return True
            return True
        else:
            myLogger.error(f"http protocol version is not numeric: {httpRequestTokens[2]}")
            return False
    else:
        myLogger.error(f"http protocol version format is not valid {httpRequestTokens[2]}")
        return False

def validateHttpResponseCode(httpResponseCode):
    # Purpose:  Validate string for proper http response code.
    #   Many clients and application servers support additional response codes
    #   but these are documents in the IETF RFC
    # Arguments:
    #   httpResponse (in) - parsed token of log entry representing the http response code
    # Returns:
    #   True -  http response code is valid
    #   False - otherwise

    # Just check that the response code is 3 digits long and begins with 2, 3, 4 or 5
    # An exhaustive list of http response codes is elusive, but could be attempted
    firstDigits = "2345"
    if (httpResponseCode.isnumeric()) and len(httpResponseCode) == 3 and httpResponseCode[0] in firstDigits:
        return True
    else:
        return False

def validateHttpResponseSize(httpResponseTime):
    # Purpose:  Validate string for format of response time in milliseconds
    # Arguments:
    #   httpResponseTime (in) - parsed token of log entry representing the
    #       response time of the http request in milliseconds
    #
    # NOTE: I believe this particular token in the Common Log Format is
    # actually the HTTP response *size* not response *time* based on what
    # this article:  https://en.wikipedia.org/wiki/Common_Log_Format
    # 
    if not httpResponseTime.isnumeric():
        return False
    #if resourcePath[0] in pathDict:
    #    pathDict[resourcePath[0]].append(httpResponseTime)
    #else:  
    #    # Error:  resource should already have been validated and placed
    #    # in the resourceDict by method validateHttpRequest
    #    myLogger.error("Error: Valid resource was not found in resource dictionary")
    #    return False
    #myLogger.debug("validatedResource is {}".format(resourcePath[0]))
    return True

def detailedValidateHttpUserAgent(httpUserAgent):
    # Purpose:  Validate string format of http user agent has proper
    #   order of product / versions and comments.
    # Arguments:
    #   httpUserAgent (in) - String representing the http user agent
    # Returns:
    #   True - if user agent is valid
    #   False - if user agent is not valid
    #   
    # Officially, the user agent is a string is composed of a series 
    # of Product/Version strings, each of which can optionally followed by 
    # a comment enclosed in parentheses.   Comments can be nested.
    # 
    # In practice, the user agent is a hot mess.   
    # - Clients can send almost anything as a user-agent.
    # - Products/Versions have no standard use of letters and numbers
    # - Many servers like nginx add the language/locale to the
    # user-agent, although it is not part of any specification.
    #
    # This method will validate a "Product/Version" or "Product" part of
    # a user agent to be sure it does not contain characters disallowed
    # in an http token:  (),/:;<=>?@[\]{}
    # See Sections 3.8 of of IETF RFC 2616 which states:
    #   "... Although any token character MAY appear in a product-version,
    #        this token should only be used for a version identifier"
    #   "/" will be allowed because it the separator between Product and Version
    #
    # For the comment part of the user agent, this method will only check that
    # it is enclosed in parentheses.  And comment may be nested.
    # The character limitations for a comment are even less stringent than
    # those for a product/version, essentially anything 
    # https://www.rfc-editor.org/rfc/rfc7230#section-3.2.6
    #  
    # Here is an example of a user agent string which shows some of the
    # complexities:
    # "Opera/9.80 (Windows NT 5.1; U; MRA 5.6 (build 03278); ru) Presto/2.6.30 Version/10.63"
 
    agentTokens = httpUserAgent.split()
    lastTokenType  = None # type of the last token (prodver or comment)
    commentStack = []  # stack to track comment start and end (and nested)
    # Disallow chars the RFC says are not allows in a Prod/Version
    # Disallowed chars do not include:
    #   "/"             because it is the separator between Product and Version
    #   "[" and "]"     because some user agent strings appears to contain a language
    #                   specified [en]
    notAllowedInProdVer = "(),:;<=>?@\{\}"

    for token in agentTokens:

        # Check for and handle different types of tokens in a user agent
        # 1 - Product/Version token.  These must precede an unnested comment token,
        #   and can follow another prod/ver token 
        # 2 - Comments are made up of multiple tokens, enclosed in parenthese.
        #   Comments must be preceded by a prod/ver token, unless comment is nested.
        #   Nested comment are allowed but consecutive comments are not.
        #   -- Start of comment token begins with '('
        #   -- Comment tokens, which haave few limitations 
        #   -- End of comment token, which ends with ')'
        #   -- End of *nested* comment token, which may end with either ");" or ')'     
        myLogger.debug(f"user agent: next token is {token} and last token type was: {lastTokenType}")


        if lastTokenType == None or ( lastTokenType == "prodver" and token[0] != "(" ) or ( lastTokenType == "comment" and len(commentStack) == 0):
            # Next token could be a prod/ver token:
            #  - prod/ver must be first token in user agent
            #  - prod/ver must follow an unnested comment token
            #  - The token following a prod/ver token could be another prod/ver token, but could also be a comment
            myLogger.debug(f"user agent: Checking for prod/ver token: {token}")
            for nextChar in token:
                if nextChar in notAllowedInProdVer:
                    myLogger.error(f"user agent: invalid character \'{nextChar}\' in prod/ver token: {token}")
                    return False
            lastTokenType = "prodver"
            continue
            
        tokenIter = iter(range(len(token)))
        for tokenIndex in tokenIter:
            #  Expect a comment token.  Look for start and end of comments
            if token[tokenIndex] == "(":
                # Start of comment
                commentStack.append(token[tokenIndex])
                lastTokenType = "comment"
                continue
            elif token[tokenIndex] == ")":
                # End of comment
                if len(commentStack) == 0:
                    # Found end of comment, but comment was not started
                    myLogger.error(f"user agent: found comment end without comment start in token {token}")
                    return False
                elif len(commentStack) > 0:
                    # End of comment 
                    commentStack.pop()
                    lastTokenType = "comment"
                    # If end of nested comment, the next char may be a ';' (if there is a next char)
                    if len(commentStack) > 1 and tokenIndex <= len(token-2) and token[tokenIndex+1] == ';':
                        next(tokenIter)
            continue
    
    if len(commentStack) != 0:
        myLogger.error(f"user agent: comment left unclosed: {httpUserAgent}")
        return False
    myLogger.debug(f"Finished parsing comment and length of comment stack is {len(commentStack)}")
    return True                    


def incrLineCounters(success, linesProcessed, linesOK, linesFailed, statsdClient):
    # Utility to increment counts of log lines processed
    # and to send metrcis to statsd service if a statsd client is available
    #
    # Note that List types are used for linesProcess, linesOK, and linesFailed
    # because they are mutuable.   Seemed better than global variables.
    # 
    # Arguments:
    #   success (in) - True or False, indicating if log line was validates
    #   linesProcessed (in, out) - List with single element containing count of all lines processed
    #   linesOK (in, out) - List with single element counting log lines validated successfully
    #   linesFailsed (in, out) - List with single element counting log lines failed validation 
    #   statsdClient (in) - client to statsd server for collecting metrics.
    linesProcessed[0] += 1
    if success:
        linesOK[0] += 1
    else: 
        linesFailed[0] += 1
    if statsdClient != None:
        statsdClient.incr("metric.1")
        if success:
            statsdClient.incr("metric.2")
        else:
            statsdClient.incr("metric.3")

    

if __name__ == "__main__":

    # Main thread

    # Set logging level from LOGLEVEL env variable if it is set
    logLevel = os.getenv("THELOGLEVEL")
    if logLevel is None:
        print("LOGLEVEL env variable is not set.  Defaulting to INFO.")
        logLevel = "INFO"
    elif logLevel not in [ 'DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL' ]:
        # If value of THELOGLEVEL is not a valid Python logging, level, set log level to INFO
        print(f"Value of {logLevel} in THELOGLEVEL env variable is not a valid Python log level. Defaulting to INFO.")
        logLevel = "INFO"
    logging.basicConfig(level=logLevel, encoding='utf-8', format='%(asctime)s [%(levelname)s] %(message)s')
    print(f"Log level has been set to {logLevel}.")
    myLogger = logging.getLogger(__name__)


    # Get and validate command line arguments
    myLogger.info("Log parser is starting.")
    myLogger.info("Get and validate command line arguments.")
    rc = getArgs()
    myLogger.debug("Finished validating command line arguments.")
    if rc != 0:
        myLogger.error("Error found with command line arguments.  Exiting.")
        sys.exit(rc)

    # Check for statsd server and instantiate a client if available
    statsdClient = None
    statsdEnv = None
    statsdHost = None
    statsdPort = None
    try: 
        statsdEnv = os.getenv("STATSD_SERVER")
    except Exception as e:
        myLogger.error("Could not get env variable STATSD_SERVER")
    if statsdEnv != None:
        sdparts = statsdEnv.split(":")
        if len(sdparts) == 2:
            statsdHost = str(sdparts[0])
            if sdparts[1].isnumeric():
                statsdPort = int(sdparts[1])
                myLogger.info("statsd host is: {} and statsd port is {}".format(statsdHost, statsdPort))
            else:
                 myLogger.error("Port number in STATSD_SERVER env var is not valid: {}",format(statsdEnv))
    if statsdHost != None and statsdPort != None:
        statsdClient = statsd.StatsClient(statsdHost, statsdPort)
    else:
        myLogger.info("No STATSD_SERVER env varaible found.  Continuing without statsd server.") 
      
    # Dictionaries for tracking client IP address and request paths in log entries
    clientIPDict = {}
    topIPDict = {}
    pathDict = {}
    topPathDict = {}

    # Counters for log lines
    linesProcessed = [0]
    linesOK = [0]
    linesFailed = [0]
    
    with open(inputFile, 'r') as f:

        # Loop through each line in input file and process next log line
        for nextLogLine in f:
            
            # shlex will split the log line and preserve values in quotes
            # note this splits the timestamp in two:  date/time and timezone
            # TBD: investigate other ways to split line, e.g. regex
            try:
                parsedLine = shlex.split(nextLogLine)
            except Exception as e:
                myLogger.error(f"Exception parsing log line: {str(e)}.  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue
            except:
                myLogger.error("Unknown exception parsing log line.  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue

            myLogger.debug(f"Parsed log line to be validated is \"{parsedLine}\"")

            # A proper log line should have 9 fields
            if len(parsedLine) != 9:
                myLogger.error("Parsed line has {len(parsedLine)} tokens instead of 9.  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue
            
            # Validate field index 0:  remote IP address
            validatedIPAddress = None
            if not validateRemoteIPAddress(parsedLine[0]):
                myLogger.error(f"IP address validation failed for: \"{parsedLine[0]}\".  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue
            else:
                validatedIPAddress = parsedLine[0]
                myLogger.debug(f"Type of parsedLogLine is {type(validatedIPAddress)}")

            # Validate field indexes 1 and 2:  client identity and userid
            # Haven't identified any requirements or limitations on the client
            # TBD: 

            # Validate field indexes 3 and 4:  date/time and timezone
            if not validateTimestamp(parsedLine[3], parsedLine[4]):
                myLogger.error(f"Timestamp validation failed for:  \"{parsedLine[3]} {parsedLine[4]}\".  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue

            # Validate field 5:  method, resource and protocol for HTTP request
            # The resource path is returned from validation so it can be tracked and counted
            validatedResourcePath = [] 
            if not validateHttpRequest(parsedLine[5], validatedResourcePath):
                myLogger.error(f"HTTP request validation failed for: \"{parsedLine[5]}\".  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue

            # Validate field 6: HTTP response code
            if not validateHttpResponseCode(parsedLine[6]):
                myLogger.error(f"HTTP response code validation failed for: \"{parsedLine[6]}\".  Continuing to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue

            # Validate field 7:  HTTP response size
            # Save response size for tracking
            validatedResponseSize = None
            if not validateHttpResponseSize(parsedLine[7]):
                myLogger.error(f"HTTP repsponse size validation failed for: \"{parsedLine[7]}\".  Continue to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue
            else:
                validatedResponseSize = parsedLine[7]

            # Validate field 8: User Agent
            if not detailedValidateHttpUserAgent(parsedLine[8]):
                myLogger.error(f"User agent validation failed for: \"{parsedLine[8]}\".  Continue to next line.")
                incrLineCounters(False, linesProcessed, linesOK, linesFailed, statsdClient)
                continue

            myLogger.debug("Log entry successfully validated.")

            # Log line successfully parsed and validated
            incrLineCounters(True, linesProcessed, linesOK, linesFailed, statsdClient)
            # Add or Update count of IP address
            if validatedIPAddress not in clientIPDict:
                clientIPDict.update( { validatedIPAddress : 1 } )
            else:
                clientIPDict[validatedIPAddress] +=1
            # Add or Update count of resource path and response time in dictionary
            # Each key in the pathDict is a unique key for the path
            # The value of the key is a list where:
            #   the first number is total of the instances of the path appeared in log line
            #   the second number is the total milliseconds for all instances
            thisPath = validatedResourcePath[0] # Because validatedResourcePath is a List
            if thisPath not in pathDict:
                pathDict.update({ thisPath : [ float(0), float(0)] })
            pathDict[thisPath][0] = pathDict[thisPath][0] + 1
            pathDict[thisPath][1] = pathDict[thisPath][1] + float(validatedResponseSize)

    # All lines in the log file have been parsed and validated.
    myLogger.info(f"Total lines processed = {linesProcessed}")
    myLogger.info(f"Total lines failed = {linesFailed}")
    myLogger.info(f"Total lines OK = {linesOK}")
    myLogger.debug(f"IP Address Dictionary is: {clientIPDict}")
    myLogger.debug(f"IP Resource Dictionary is: {pathDict}")

    # Find top (most freuqnet) occurences of IP addresses in log,
    # up to the number specified in the max-client-ips argument
    # Sort clientIPDict by value, which is the  number of occurences
    sortedClientIPDict = sorted(clientIPDict.items(), key=lambda i:i[1], reverse=True)
    if maxClientIPs < len(sortedClientIPDict):
        topIPDict = dict(sortedClientIPDict[:maxClientIPs])
    else: 
        topIPDict = dict(sortedClientIPDict)
    myLogger.debug(f"sorted top IP dict = {topIPDict}")

    # Calculate average response (size) for each resource
    # For each key in the pathDict, the value is a list where
    # the first element is the total of the instances of the resource path
    # and the second number is the size in bytes
    for path in pathDict:
        pathDict[path] = pathDict[path][1] / pathDict[path][0]
        pathDict[path] = pathDict[path] / 1024.0
    myLogger.debug("pathDict is {}".format(pathDict))
    # Sort resources by slowest response time (size)
    sortedPathDictList = sorted(pathDict.items(), key = lambda x:x[1], reverse=True)
    # Convert back to dictionary (for future json output) and select max paths
    if maxPaths <= len(sortedPathDictList):
        topPathDict = dict(sortedPathDictList[:maxPaths])
    else: 
        topPathDict = dict(sortedPathDictList)
    # Last thing is to format the response time in the topPathDict to 2 decimal places
    # Did not do this above, before averaging and sorts, to avoid losing precision
    for path in topPathDict:
        topPathDict[path] = round(topPathDict[path], 2)
    myLogger.debug(f"sorted top paths dict is {topPathDict}")

    # Format output
    finalDictionary = {}
    finalDictionary.update( { "total_number_of_lines_processed" : linesProcessed[0] } )
    finalDictionary.update( { "total_number_of_lines_ok" : linesOK[0] })
    finalDictionary.update( { "total_number_of_lines_failed" : linesFailed[0] })
    finalDictionary.update( { "top_client_ips" : topIPDict })
    finalDictionary.update( { "top_path_avg_response_size" : topPathDict })

    
    formattedjson = json.dumps( finalDictionary, indent=4)
    # Write to output file
    myLogger.info(f"JSON to be written to output file is:\n {formattedjson}")
    try:
        with open(outputFile, 'w') as f:
            json.dump( finalDictionary, f, indent=4)
    except Exception as e:
        myLogger.debug(f"Exception writing output file: {str(e)}")
    except:
        myLogger.debug("Unknown exception writing output file")        
    myLogger.info("The log parser is done")
    sys.exit(0)
        
