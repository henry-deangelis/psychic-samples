#
# Copyright (C) 2019, 2023 Henry DeAngelis
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Eclipse Public License v1.0
# which accompanies this distribution, and is available at
# http://www.eclipse.org/legal/epl-v10.html
#
import os
import sys
import argparse
import time
import datetime
import threading
import logging
import paho.mqtt.client as mqtt
import ssl
from random import randint

cmdLineArgs = None
fileForCACert = None
fileForDeviceCert = None
fileForDevicePvtKey = None
mqttTopic = None

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s',)
theLogger = logging.getLogger(__name__)

largeMQTTPayload = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Define argument names and types passed in
def getArgs():
   parser = argparse.ArgumentParser(description='Run Multiple MQTT Clients in paralell with Threads.')
   parser.add_argument('-n', '--numclients', type=int, default='1',
          help="number of MQTT clients to start publishing (default is 1)")
   parser.add_argument('-b', '--brokerhost', type=str,
          help="hostname of MQTT broker (fully qualified domain name)")
   parser.add_argument('-p', '--portnumber', type=int, default="8883",
          help="port number on broker to connect to (default is 8883)")
   parser.add_argument('-r', '--runtime', type=int, default='1',
          help="time to run script, in minutes (default is 1 minute)")
   parser.add_argument('-d', '--publishinterval', type=int, default='10',
          help="delay between publishing messages, in seconds (default is 10)")
   parser.add_argument('-a', '--cacert', type=str, required=True,
          help="file name of CA certificate for broker")
   parser.add_argument('-i', '--clientid', type=str, required=True,
          help="client ID for MQTT connection (used as prefix)")
   parser.add_argument('-e', '--devicecert', type=str, required=True,
          help="file name for certficiate of device / thing")
   parser.add_argument('-k', '--devicekey', type=str, required=True,
          help="file name for private key of device / thing")
   parser.add_argument('-t', '--topicstring', default = "sdk/test/python",
          help="Topic string on broker namespace")
   parser.add_argument('-x', '--disconnect', action='store_true',
          help="Disconnect / reconnect between every message published (use with caution)")
   parser.add_argument('-l', '--largemessage', action='store_true',
          help="Use large messages for publishing (use with caution)")
   parser.add_argument('-v', '--verbosity', action="count", default=0,
          help="increase verbosity / debug messages")
   global cmdLineArgs
   cmdLineArgs = parser.parse_args()
   
# Validate argument values
# Returns:
#   -1 if there is a problem with any of the arguments
#    0 if all arguments are OK
def validateArgs():
 
   goodArguments = 0
   
   # Start by checking for existing of files for certs and keys
   global fileForCACert
   fileForCACert = cmdLineArgs.cacert
   global fileForDeviceCert
   fileForDeviceCert = cmdLineArgs.devicecert
   global fileForDevicePvtKey
   fileForDevicePvtKey = cmdLineArgs.devicekey
   if not os.path.exists(fileForCACert):
      theLogger.error("CA certificate file not found:  {}".format(fileForCACert))
      goodArguments = -1
   if not os.path.exists(fileForDeviceCert):
      theLogger.error("Device certficiate file not found:  {}".format(fileForDeviceCert))
      goodArguments = -1
   if not os.path.exists(fileForDevicePvtKey):
      theLogger.error("Deivce private key not found: {}".format(fileForDevicePvtKey))
      goodArguments = -1

   return goodArguments

   
def dateNow():
     return datetime.datetime.now().isoformat()

def printDebug(printString):
   theLogger.debug("{}".format(printString))

def onDisconnect(client, userdata, rc):
   theLogger.debug("Callback from disconnect: return code {}".format(rc))

def onConnect(client, userdata, flags, rc):
   theLogger.debug("Callback from connect:  return code {}".format(rc))

def onPublish(client, userdata, mid):
   theLogger.debug("Callback from publish for client ID {}, message ID {}".format(str(client),str(mid)))

# Class which does the work for a device
class DeviceWorker():

   # Initialize instance variables
   def __init__(self,workerID):
      global cmdLineArgs
      self._workerID = workerID
      self._endTime = None
      self._publishInterval = cmdLineArgs.publishinterval
      self._lastSensorValue = randint(0,100)
      self._newSensorValue = None
      self._msgToSend = None
      self._brokerHost = cmdLineArgs.brokerhost
      self._brokerResponse = None
      self._theTopic = cmdLineArgs.topicstring

      # Initialize mqtt client
      # 
      # set client ID for MQTT connection
      if cmdLineArgs.numclients > 1:
         # Append number to client ID to ensure it is unique
         self._clientID = "{}{}".format(cmdLineArgs.clientid, self._workerID)
      else: 
         # If just running 1 client, no need to append number
         self._clientID = cmdLineArgs.clientid
      printDebug("MQTT Client ID is {}".format(self._clientID))
      self._mqttCli = mqtt.Client(self._clientID)
      self._mqttCli.on_connect = onConnect
      self._mqttCli.on_disconnect = onDisconnect
      self._mqttCli.on_publish = onPublish
      self._mqttCli.tls_set(ca_certs=fileForCACert, certfile=fileForDeviceCert, keyfile=fileForDevicePvtKey, 
                            cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2, ciphers=None)

   def Start(self):
      global cmdLineArgs

      # Set ending time for this worker in seconds 
      self._endTime = time.time() + (cmdLineArgs.runtime  * 60)

      if cmdLineArgs.disconnect:
         theLogger.debug("Value of disconnect flag is {}".format(cmdLineArgs.disconnect))

      theLogger.info("Connecting to broker {} with client ID {}".format(self._brokerHost, self._clientID ))
      self._mqttCli.connect(self._brokerHost, cmdLineArgs.portnumber, keepalive=60)
      self._mqttCli.loop_start()
      # Need to delay after loop_start() or on_connect callback does not fire
      time.sleep(2)

      while time.time() < self._endTime:

         # Create and publish messages

         # If this is a real device / thing, here is where to inserts device-specific code 
         # which obtains the value of the sensor you are interested in.
         # The following simulates a sensor with values between 0 and 100,
         # which could represent relative temperature.
         # This code increments or decrements the sensor value by 5, without letting it drop below 0
         if (self._lastSensorValue - 5) < 0:
            self._newSensorValue = randint(20,40)
         elif (self._lastSensorValue + 5) > 100:
            self._newSensorValue = randint(60,80)
         else:
            self._newSensorValue = randint(self._lastSensorValue-5, self._lastSensorValue+5)
         

         # Create message in JSON format
         if cmdLineArgs.largemessage:
            self._msgToSend = "{{ \"payload\" : {{ \"clientID\" : \"{0}\" , \"temperature\" : \"{1}\" , \
              \"largeness\" : \"{2}\" }} }}".format(self._clientID, self._newSensorValue, largeMQTTPayload)
            theLogger.info("publishing payload {} to topic {}".format(self._msgToSend, self._theTopic) )
         else:
            self._msgToSend = "{{ \"payload\" : {{ \"clientID\" : \"{0}\" ,  \"temperature\" : \"{1}\" }} }}".format(
               self._clientID, self._newSensorValue, self._clientID)
            theLogger.info("publishing payload {} to topic {}".format(self._msgToSend, self._theTopic) )
         self._brokerResponse = self._mqttCli.publish(self._theTopic, self._msgToSend, qos=0)
         theLogger.debug("publish result is {}".format(self._brokerResponse))

         # Replace last sensor value with new value
         self._lastSensorValue = self._newSensorValue

         # Delay until next publish.  Disconnect/reconnect if requested
         if cmdLineArgs.disconnect:
            self._mqttCli.disconnect()
            self._mqttCli.loop_stop()
            time.sleep(self._publishinterval) # sleep for number of seconds on cmdLineArgs -f flag

            theLogger.info("Reconnecting explicitly to broker {} with client ID {}".format(self._brokerHost, self._clientID ))
            self._mqttCli.connect(self._brokerHost, cmdLineArgs.portnumber, keepalive=60)
            self._mqttCli.loop_start()
            # Need to delay after loop_start() or on_connect callback does not fire
            time.sleep(2) # sleep for number of seconds on cmdLineArgs -f flag

         else:
            time.sleep(self._publishInterval) # sleep for number of seconds on cmdLineArgs -f flag

      self._mqttCli.loop_stop()
      theLogger.info("Worker ID %s is ending".format(self._workerID))

class DeviceWorkerThread(threading.Thread):
   def __init__(self, workerID):
      threading.Thread.__init__(self)
      self._workerThreadID = workerID
      self._theWorker = DeviceWorker(self._workerThreadID)
   def run(self):
      printDebug("Start run of WorkerThread {}".format(self._workerThreadID))
      self._theWorker.Start()
      printDebug("End running WorkerThread {}".format(self._workerThreadID))

if __name__ == "__main__":
   
   printDebug("Starting main process thread")

   # Tried the following to help ensure log messages were not delayed, but not sure if really helped
   # sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0) # don't want to wait for stdout to be flushed
   
   # Setup up log message formats and level
   
   # Get command line arguments
   getArgs()
   theLogger.debug("Command line arguments are: {}".format(str(cmdLineArgs)))

   # Setup loglevel
   if cmdLineArgs.verbosity == 0:
      theLogger.setLevel(logging.INFO)
   elif cmdLineArgs.verbosity > 0:
      theLogger.setLevel(logging.DEBUG)

   rc = validateArgs()
   if rc != 0:
      theLogger.warning("Check argument values")
      exit(rc)
   
   clientThreads = []

   theLogger.info("Starting clients...")
   for n in range(cmdLineArgs.numclients):
     nextWorker = DeviceWorkerThread(n)
     clientThreads.append(nextWorker);
     nextWorker.start()
     time.sleep(3)

   for n in clientThreads:
      # wait for all threads to finish
      n.join()

   theLogger.info("Finished - all clients ended")
