# Log Parser for Nginx

This tool parses a Nginx log file, which loosely follows the
[Common Log Format](https://www.w3.org/Daemon/User/Config/Logging.html#common-logfile-format), with the addition of field for user agent.

It checks the structure and content of each field for expected values, and summarizes findings in json structure. As such, it showcases the use of Python and several important data structures.

For example, a typical nginx log entry is structured as follows. More detailed information on log file format and parsing can be found below.

`192.168.50.183 user-identifier frank [10/Oct/2020:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 3884 "Mozilla/5.0 (Linux i686) en-US" `

# Prerequisites

- Python 3.12
- Packages for `pathvalidate` and `statsd` installed with pip.

# Usage

Download and run the script. There are 2 required options: the input log file, and the output results summary.

For example:

`python3 nginxlogparser.py --in ngninx.log --out logsummary.json`

Command line arguments include:

| Argument                                       | Description                                                                                          |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| -i inputfile, --in inputputfile                | file name of log file to be parsed                                                                   |
| -o outputfile, --out outputfile                | file name of outputfile with parsing results                                                         |
| -c maxclientips, --max-client-ips numclientips | number of top (most common) client IPs to include in summary, between 0 and 10000 (default is 10)    |
| -p maxpaths, --max-paths numpaths              | number of top (most common) request paths to include in summary, between 0 and 10000 (default is 10) |
| -v, --verbose                                  | Send detailed debug output to stdout (overrides the env variable THELOGLEVEL described below)        |

Because this was written to be run as a container, it uses some environment varialbes, if set:

| Environment Variable | Value                              | Description                                                                                   |
| -------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------- |
| THELOGLEVEL          | DEBUG, INFO, WARN, ERROR, CRITICAL | Level of logging, based on Python logger levels. Sent to stdout                               |
| STATSD_SERVER        | hostname:port                      | host and port of statsd server, if available, where counts of parsed log entries will be sent |

# Output

The outputfile will have a json object summarizing the results of parsing the log, including:

- The total number of log lines processed
- The number of log lines validated successfully
- The number of log lines failing validation
- The top (most common) IP addresses in the log, along with the number of occurrences (as an integer). Output islimited by the --max-client-ips argument.
- The top (most common) resource paths, along with the average size of the content response in kilobytes (as a float rounded to 2 decimal plaes). Output is limited by the --max-paths argument.

```json
{
    "total_number_of_lines_processed": 4000,
    "total_number_of_lines_ok": 3894,
    "total_number_of_lines_failed": 106,
    "top_client_ips": {
        "192.168.50.183": 73,
        "72.20.11.162": 69,
        ...
    },
    "top_path_avg_response_size": {
        "/catalog/index.html": 70172.60,
        "/cart/checkout": 2304.80,
        ...
    }
}
```

# Log File Input Format and Parsing

The nginx log file is based on the [Common Log Format](https://www.w3.org/Daemon/User/Config/Logging.html#common-logfile-format). It also include a "user agent" string.

The log entry format is:

```log
<remote_addr> <user-identifier> <remote_user> [<date>] "<http_verb> <http_path> <http_version>" <http_response_code> <http_response_time_milliseconds> "<user_agent_string>"
```

Here is an example of an nginx log entry:

`192.168.50.183 - frank [10/Oct/2020:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 3884 "Mozilla/5.0 (Linux i686) en-US" `

- `192.168.50.183` is the IP address of the client (remote host) which made the request to the server.
- `user-identifier` is the [RFC 1413](https://datatracker.ietf.org/doc/html/rfc1413) identity of the client. Usually "-".
- `frank` is the userid of the person requesting the document. Usually "-" unless .htaccess has requested authentication.
- `[10/Oct/2020:13:55:36 -0700]` is the date, time, and time zone that the request was received, by default in strftime format %d/%b/%Y:%H:%M:%S %z.
- `"GET /apache_pb.gif HTTP/1.0"` is the request line from the client. The method GET, /apache_pb.gif the resource requested, and HTTP/1.0 the HTTP protocol.
- `200` is the HTTP status code returned to the client. 2xx is a successful response, 3xx a redirection, 4xx a client error, and 5xx a server error.
- `3884` is the size of the object returned to the client, measured in bytes.
- `"Mozilla/5.0 (Linux i686) en-US"` is a user agent string

## Parsing the User Agent

The format of the user agent string is perhaps the most confounding. It is defined in [IETF RFC 7231](https://datatracker.ietf.org/doc/html/rfc7231#section-5.5.3). In practice, many browsers and web kits do not conform precisely to this spec. And nginx itself appears to add a language specification to the user agent, such as 'en-US', which is not part of the spec.

Keeping this in mind, this tool attempts to accommodate a wide variety of user agent strings, including nested values (which makes for an interesting coding problem).

## Other Parsing Considerations

The general approach being taken here is to use [RFC 2616](https://tools.ietf.org/html/rfc2616) as a guide to whether values in a log entry are valid. The particulars of the nginx configuration, and whether any plugins are used, could change what is in the log entry.  
[NginX](https://nginx.org/en/docs/http/ngx_http_core_module.html#variables)
