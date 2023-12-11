# Python Threads and Objects - MQTT Publisher

The project provides an example of how to use Python threads and objects, and shows how these interact.  It does so by simulates multiple Internet of Things devices publishing simulataneously to a MQTT broker.   It was specifically written and tested with the Amazon AWS IoT core service, but since it is using the Paho MQTT client, it shoud should be easily adaptable to other MQTT Brokers like Microsoft Azure IoT Hub.

You could remove or replace the code in this script which is specific to MQTT, and replace with anything else you would like to do in a thread.


# Prerequisites

There are a few prerequisites you will need:

* Python3

* Paho MQTT Client for Python

   If you are not familiar with the Paho MQTT Client you can learn more about it [here](https://eclipse.dev/paho/)

   ```bash
   pip3 install paho-mqtt
   ```

* MQTT Broker Service and Device Credentials

   For this script to publish MQTT message, you will need an MQTT broker / server to publish to.   [AWS IoT Core](https://docs.aws.amazon.com/iot/latest/developerguide/iot-gs.html) is what I used, which means you'll need to setup an AWS account.  

   You will also need to tell your MQTT / IoT broker about the device which will be connecting and publishing, and get the device credentials.  AWS IoT makes this all really easy with this [interactive quick connect tutorial](https://docs.aws.amazon.com/iot/latest/developerguide/iot-quick-start.html)

   You do NOT need an actual device, like a Raspberry Pi, to run this script.  It can ball be done from your laptop.  What you do need need are the following files which are created during the AWS IoT tutorial.

   **root-CA.cert** : This is the CA Certificate needed to create a secure SSL / TLS connection to the broker
   **\<device\>.cert.pem** : This is the Certfiiate for your "device", which is needed to connect and authenticate the device to the broker
   **\<devicename\>.private.key** : This is the private key for the device certificate, which again is needed to connect and authenticate the device to the broker.

# Getting started

1. Download the python-threaded-mqtt.py script from this repository

2. Download the certificate and private key files to directory so the script can read them.  Again, the AWS IoT Quick Connect tutorial above is an easy way to start

3. Get the hostname of the MQTT broker.   In AWS IoT Core, this is the "device data endpoint" which you can find under under "Settings" in AWS IoT.

   For example:   <samp>a5ob6obuto8a7-ats.iot.us-west-2.amazonaws.com</samp>  
   
   You should be able to ping this hostname
   ```bash
   $ ping a5ob6obuto8a7-ats.iot.us-west-2.amazonaws.com
   PING a5ob6obuto8a7-ats.us-west-2.amazonaws.com (44.232.82.105): 56 data bytes
   64 bytes from 44.232.82.105: icmp_seq=0 ttl=240 time=80.492 ms
   64 bytes from 44.232.82.105: icmp_seq=1 ttl=240 time=82.598 ms
   64 bytes from 44.232.82.105: icmp_seq=2 ttl=240 time=87.628 ms
   ```

4. If using AWS IoT, check the security policy created during the AWS IoT Quick Connect tutorial.  The policy must:
   - Be associated with the thing / device you created 

   - Allow publishing to the MQTT topic string.  The default topic created by the tutorial is "sdk/test/python"

   ```json
      {
         "Effect": "Allow",
         "Action": "iot:Publish",
         "Resource": [
           "arn:aws:iot:us-west-2:027927523447:topic/sdk/test/java",
           "arn:aws:iot:us-west-2:027927523447:topic/sdk/test/python",
         ]
    }
   ```

   - Allows the Client ID to connect to the broker.   The default client ID created by the tutorial "basicPubSub".  To allow mutiple clients to connect you need to add an asterisk (wildcard) to the policy.  For example

   ```json
       {
         "Effect": "Allow",
         "Action": [
         "iot:Connect"
         ],
         "Resource": [
           "arn:aws:iot:us-west-2:027927523447:client/sdk-java",
           "arn:aws:iot:us-west-2:027927523447:client/basicPubSub*",
           "arn:aws:iot:us-west-2:027927523447:client/sdk-nodejs-*"
         ]
       }
   ```

# Running the script

After you have completed the Prerequisites and Getting Started sections above, run the script.

For example:

```bash
python3 ./aws-iot-publisher.py --cacert ./mydev-iot-1/root-CA.crt --devicecert ./mydev-iot-1/mydev-iot-1.cert.pem --devicekey ./mydev-iot-1/mydev-iot-1.private.asd --clientid basicPubSub --numclients 1
```

Start with just 1 client (<samp>--numclients 1</samp>).   As you use more clients, this script will append a number to the Client ID (<samp>--<samp>clientid) because the MQTT broker requires each client connection to have a unique Client ID.  That is the reason you must update the default security policy in Aws IoT Core as described above.


# Options

| Option | Description |
--- | ---
| -h, --help | show this help message and exit |
| -n NUMCLIENTS, --numclients NUMCLIENTS |  number of MQTT clients to start publishing (default is 1) |
| -b BROKERHOST, --brokerhost BROKERHOST |  hostname of MQTT broker (fully qualified domain name) |
| -p PORTNUMBER, --portnumber PORTNUMBER |  port number on broker to connect to (default is 8883)
| -r RUNTIME, --runtime RUNTIME | time to run script, in minutes (default is 1 minute) |
|  -d PUBLISHINTERVAL, --publishinterval PUBLISHINTERVAL | delay between publishing messages, in seconds (default is 10) |
|  -a CACERT, --cacert CACERT | file name of CA certificate for broker |
|  -i CLIENTID, --clientid CLIENTID | client ID for MQTT connection (used as prefix) |
|  -e DEVICECERT, --devicecert DEVICECERT | file name for certficiate of device / thing |
|  -k DEVICEKEY, --devicekey DEVICEKEY |file name for private key of device / thing |
|  -t TOPICSTRING, --topicstring TOPICSTRING | Topic string on broker namespace |
|  -x, --disconnect      | Disconnect / reconnect between every message published (use with caution) |
|  -l, --largemessage    | Use large messages for publishing (use with caution) |
|  -v, --verbosity       | increase verbosity / debug messages |

# Troubleshooting and FAQs

1. Cannot connect or publish messages

If the script fails to connect to the MQTT broker (AWS IOT), or fails to publish a messages, please re-check the security policy defintion I mention in the getting started section.

If you are using AWS IoT, you can also enable the CloudWatch Log service for your AWS IoT Core service, and it may help you find the problem.  Use this article describing how to [Monitor AWS IoT using CloudWatch logs](https://docs.aws.amazon.com/iot/latest/developerguide/cloud-watch-logs.html)

1. Clients are disconnecting

Check to see if you used the disconnect (<samp>--disconnect</samp>) flag.  This causes clients to disconnect and reconnect between each publish.   If you use a very short publish interval, some MQTT brokers will interpret this kind of disconnect / reconnect behavior as a rogue client, and block further connections from the device.

Some MQTT brokers may not allow the same device / thing to collect with multiple MQTT client IDs.  AWS IoT Core doesn't not specifically prohibit this, but you should be vigilant.

1. What message does the client publish?

This script simulates a temperature reading between 1 and 100, which is re-calcuate before each subsequent publish using some random numbers to bump the number up or down.   It also includes the client ID so you can determine which thread originated the message.

Here is an example of the message format:
   ```json
{ 
    "payload" :
    { 
        "clientID" : "basicPubSub1" ,  
        "humidity" : "59"
    } 
}
``````

# Issues

Report problems by [adding an issue on GitHub](https://github.com/henry-deangelis/psychic-samples/issues).

# License

This project is released under version 2.0 of the [Apache License](https://github.com/IBM-Cloud/ibm-cloud-cli-sdk/blob/master/LICENSE)

