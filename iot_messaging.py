import os
import json
import sys
import time
import logging
from awscrt import io
from awscrt.mqtt import QoS, Connection as MqttConnection
from awsiot import mqtt_connection_builder
from awscrt.exceptions import AwsCrtError

# ─── Correct AWS IoT SDK v2 Imports ──────────────────────────────────────────
try:
    SDK_V2_AVAILABLE = True
except ImportError as e:
    logging.error(f"Error importing AWS IoT SDK v2/CRT components: {e}")
    logging.error("Please ensure 'awsiotsdk' (and 'awscrt') are installed correctly.")
    io = None
    mqtt_connection_builder = None
    QoS = None
    MqttConnection = None
    AwsCrtError = Exception
    SDK_V2_AVAILABLE = False
# ────────────────────────────────────────────────────────────────────────────

class IoTPublisher:
    def __init__(self):
        # Retrieve and clean the endpoint (strip whitespace, BOM, zero-width)
        raw_endpoint = os.getenv('AWS_IOT_ENDPOINT', '')
        if raw_endpoint:
            raw_endpoint = raw_endpoint.strip()
            raw_endpoint = raw_endpoint.replace('\ufeff', '')
            raw_endpoint = raw_endpoint.replace('\u200b', '')
        self.endpoint = raw_endpoint or None

        self.cert_path = os.getenv('AWS_IOT_CERT_PATH')
        self.key_path = os.getenv('AWS_IOT_KEY_PATH')
        self.ca_path = os.getenv('AWS_IOT_CA_PATH')
        self.client_id = os.getenv('AWS_IOT_CLIENT_ID', f'security-camera-{os.getpid()}')

        self.mqtt_connection: MqttConnection | None = None
        self._is_connected = False
        self._connect_in_progress = False
        # CRT components - keep alive for the connection
        self.event_loop_group = None
        self.host_resolver = None
        self.client_bootstrap = None

        # Disable if SDK missing
        if not SDK_V2_AVAILABLE or io is None:
            logging.error("Error: AWS IoT SDK V2 or CRT components not available. Publisher disabled.")
            self.endpoint = None
            return

        # Disable if config incomplete
        if not all([self.endpoint, self.cert_path, self.key_path, self.ca_path]):
            logging.error("Warning: AWS IoT environment variables not fully configured. Publisher disabled.")
            self.endpoint = None
            return

        # Initialize CRT components
        try:
            self.event_loop_group = io.EventLoopGroup(1)
            self.host_resolver = io.DefaultHostResolver(self.event_loop_group)
            self.client_bootstrap = io.ClientBootstrap(self.event_loop_group, self.host_resolver)
            logging.info("CRT components initialized successfully")
        except Exception as init_e:
            logging.error(f"Error initializing CRT components: {init_e}")
            self.endpoint = None
            return

        # Attempt initial connection
        self._connect()

    def _on_connection_interrupted(self, connection, error, **kwargs):
        logging.error(f"AWS IoT connection interrupted. Error: {error}")
        self._is_connected = False
        # Wait before attempting to reconnect
        time.sleep(2)
        # Only attempt reconnect if not already trying to connect
        if not self._connect_in_progress:
            self._connect()

    def _on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        logging.info(f"AWS IoT connection resumed. Return code: {return_code} Session present: {session_present}")
        self._is_connected = True
        # Resubscribe to topics after reconnection
        self._subscribe_to_topics()

    def _connect(self):
        if not self.endpoint or not self.client_bootstrap:
            logging.error("Missing required configuration for AWS IoT connection")
            return

        if self._connect_in_progress:
            logging.info("Connection already in progress, skipping retry")
            return

        if self._is_connected:
            logging.info("Already connected to AWS IoT")
            return

        self._connect_in_progress = True
        logging.info(f"Attempting to connect to AWS IoT endpoint: {self.endpoint} with client ID: {self.client_id}")
        
        try:
            # Configure MQTT connection with more resilient settings
            self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
                endpoint=self.endpoint,
                cert_filepath=self.cert_path,
                pri_key_filepath=self.key_path,
                ca_filepath=self.ca_path,
                client_bootstrap=self.client_bootstrap,
                client_id=self.client_id,
                clean_session=False,
                keep_alive_secs=30,
                ping_timeout_ms=3000,
                protocol_operation_timeout_ms=5000,
                on_connection_interrupted=self._on_connection_interrupted,
                on_connection_resumed=self._on_connection_resumed,
                on_message_received=self._on_message_received
            )
            
            # Single connection attempt
            connect_future = self.mqtt_connection.connect()
            connect_future.result(timeout=10.0)
            logging.info("AWS IoT Connection successful.")
            self._is_connected = True
            
            # Subscribe to topics after successful connection
            self._subscribe_to_topics()
            
        except (AwsCrtError, Exception) as e:
            logging.error(f"Error connecting to AWS IoT: {e}")
            self.mqtt_connection = None
            self._is_connected = False
        finally:
            self._connect_in_progress = False

    def _subscribe_to_topics(self):
        """Subscribe to all required topics"""
        if not self._is_connected or not self.mqtt_connection:
            return

        try:
            # Subscribe to camera status topics
            logging.info("Attempting to subscribe to camera/status/#...")
            sub_future, packet_id = self.mqtt_connection.subscribe(
                topic="camera/status/#",
                qos=QoS.AT_LEAST_ONCE,
                callback=self._on_subscribe_complete # Use the specific callback for this subscription
            )
            
            # Wait for the subscription ACK
            sub_future.result(timeout=5.0)
            logging.info(f"Successfully subscribed to camera/status/# (Packet ID: {packet_id})")

            # Example: Subscribe to another topic if needed
            # logging.info("Attempting to subscribe to another/topic...")
            # sub_future_other, packet_id_other = self.mqtt_connection.subscribe(
            #     topic="another/topic",
            #     qos=QoS.AT_LEAST_ONCE,
            #     callback=self._on_another_subscribe_complete # A different callback if needed
            # )
            # sub_future_other.result(timeout=5.0)
            # logging.info(f"Successfully subscribed to another/topic (Packet ID: {packet_id_other})")

        except (AwsCrtError, Exception) as e:
            logging.error(f"Error subscribing to topics: {e}", exc_info=True)
            # Optionally, set connection status to False or trigger reconnect on subscribe failure
            # self._is_connected = False 
            # self._connect()

    def _on_subscribe_complete(self, topic, qos, **kwargs):
        """Callback when subscription is complete for camera/status/#"""
        # Note: This callback might not be strictly necessary with .result() confirmation,
        # but can be useful for logging or specific actions upon ACK.
        logging.info(f"Received SUBACK for topic {topic} with QoS {qos}")

    def _on_message_received(self, topic, payload, **kwargs):
        """Callback when a message is received"""
        try:
            logging.debug(f"Raw message received on topic '{topic}'") # Log before parsing
            message = json.loads(payload)
            logging.info(f"Received message on {topic}: {json.dumps(message, indent=2)}") # Pretty print JSON
            # Add specific message handling logic here based on topic if needed
            # if topic.startswith("camera/status/"):
            #     handle_camera_status_message(message)
            # elif topic == "another/topic":
            #     handle_another_message(message)

        except json.JSONDecodeError as e:
             logging.error(f"Error decoding JSON payload on topic '{topic}': {e}. Payload: {payload}")
        except Exception as e:
            logging.error(f"Error processing received message on topic '{topic}': {e}", exc_info=True)

    def publish_event(self, event_type, data):
        """Publish an event to AWS IoT Core, using specific topics based on event type."""
        if not self.endpoint:
            logging.error("Cannot publish: AWS IoT endpoint not configured.")
            return False
            
        if not self._is_connected or not self.mqtt_connection:
            logging.error(f"Cannot publish '{event_type}': Not connected to AWS IoT Core. Attempting reconnect...")
            # Optionally trigger a reconnect attempt here if desired
            # self._connect()
            return False
            
        try:
            # Prepare the message payload
            payload = {
                # "type": event_type, # Type is now part of the topic
                "timestamp": time.time(),
                "data": data
            }
            
            # Determine the topic based on the event type
            if event_type == "motion_detected":
                topic = f"security/camera/{event_type}" # Reverted topic for motion detection
            else:
                # Assume other events are status updates
                topic = f"camera/status/{event_type}" # Keep this for status updates
                
            logging.info(f"Publishing '{event_type}' event to topic: {topic}")
            
            pub_future, packet_id = self.mqtt_connection.publish(
                topic=topic,
                payload=json.dumps(payload),
                qos=QoS.AT_LEAST_ONCE
            )
            
            # Optional: Wait for PUBACK for QoS 1 (can add latency)
            # pub_future.result(timeout=5.0) 
            # logging.info(f"PUBACK received for {event_type} on {topic} (Packet ID: {packet_id})")
            
            logging.debug(f"Published {event_type} event to {topic} (Packet ID: {packet_id}) with payload: {json.dumps(payload)}")
            return True
            
        except (AwsCrtError, Exception) as e:
            logging.error(f"Error publishing event '{event_type}' to {topic}: {e}", exc_info=True)
            # Consider marking as disconnected on publish failure
            # self._is_connected = False 
            return False
            
    def close(self):
        """Disconnect from AWS IoT Core"""
        logging.info("Closing AWS IoT Publisher...")
        if self.mqtt_connection:
            logging.info("Disconnecting AWS IoT MQTT connection...")
            dfut = self.mqtt_connection.disconnect()
            if dfut:
                try:
                    dfut.result(timeout=5.0)
                    logging.info("AWS IoT MQTT connection disconnected.")
                except Exception as e:
                    logging.error(f"Error during MQTT disconnect: {e}")
            self._is_connected = False
            self.mqtt_connection = None

# Create a singleton instance
iot_publisher = IoTPublisher() 