import logging
import json
import os
import sys
import time # Keep time for potential backoff if needed, though SDK handles some

# Attempt to import V2 SDK components
try:
    from awsiot import mqtt_connection_builder # type: ignore
    from awsiot.mqtt import QoS, MqttConnection # type: ignore # Add MqttConnection for type hinting
    from awsiot.exceptions import AwsCrtError # type: ignore
    SDK_V2_AVAILABLE = True
except ImportError as e:
    print(f"Error importing AWS IoT SDK v2 components: {e}", file=sys.stderr)
    print("Please ensure 'awsiotsdk' is installed correctly.", file=sys.stderr)
    # Define placeholders if import fails to avoid downstream errors on class definition
    mqtt_connection_builder = None
    QoS = None
    MqttConnection = None
    AwsCrtError = Exception # Fallback to base Exception
    SDK_V2_AVAILABLE = False

class AWSIoTHandlerV2(logging.Handler):
    """
    A logging handler that publishes messages to an AWS IoT Core MQTT topic using SDK v2.
    Relies on the SDK's internal connection management and callbacks.
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.topic = os.getenv('AWS_IOT_LOG_TOPIC')
        self.endpoint = os.getenv('AWS_IOT_ENDPOINT')
        self.cert_path = os.getenv('AWS_IOT_CERT_PATH')
        self.key_path = os.getenv('AWS_IOT_KEY_PATH')
        self.ca_path = os.getenv('AWS_IOT_CA_PATH')
        self.client_id = os.getenv('AWS_IOT_CLIENT_ID', f'security-server-logger-v2-{os.getpid()}') # More unique default client_id
        self.mqtt_connection: MqttConnection | None = None
        self._is_connected = False
        self._connect_in_progress = False # Prevent recursive connection attempts in callbacks

        if not SDK_V2_AVAILABLE:
            print("Error: AWS IoT SDK V2 components not available. Handler disabled.", file=sys.stderr)
            self.endpoint = None # Mark as unusable
            return

        if not all([self.topic, self.endpoint, self.cert_path, self.key_path, self.ca_path]):
            print("Warning: AWS IoT logging environment variables not fully configured. Handler disabled.", file=sys.stderr)
            self.endpoint = None # Mark as unusable
            return

        # Attempt initial connection synchronously during init
        self._connect()

    # --- Connection Callbacks --- #
    def _on_connection_interrupted(self, connection, error, **kwargs):
        print(f"AWS IoT connection interrupted. Error: {error}", file=sys.stderr)
        self._is_connected = False
        # The SDK will automatically attempt to reconnect based on keep-alive settings

    def _on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        print(f"AWS IoT connection resumed. Return code: {return_code} Session present: {session_present}")
        self._is_connected = True

    # Optional: Callback for when the connection closes permanently (won't reconnect)
    def _on_connection_closed(self, **kwargs):
        print("AWS IoT connection closed.", file=sys.stderr)
        self._is_connected = False
        self.mqtt_connection = None # Clear connection object if it's truly closed

    def _connect(self):
        if not self.endpoint or self._connect_in_progress or self._is_connected:
            return # Don't attempt if not configured, already connecting, or connected

        self._connect_in_progress = True
        print(f"Attempting to connect to AWS IoT endpoint: {self.endpoint} with client ID: {self.client_id}")
        try:
            # Using mtls_from_path for certificate-based authentication
            self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
                endpoint=self.endpoint,
                cert_filepath=self.cert_path,
                pri_key_filepath=self.key_path,
                ca_filepath=self.ca_path,
                client_id=self.client_id,
                clean_session=False, # Keep session state if connection drops
                keep_alive_secs=30,
                on_connection_interrupted=self._on_connection_interrupted,
                on_connection_resumed=self._on_connection_resumed,
                # on_connection_closed=self._on_connection_closed # Optional: Only if needed
            )

            connect_future = self.mqtt_connection.connect()
            # Wait for the connection result (blocking during init is acceptable)
            connect_future.result(timeout=10.0) # Add a timeout
            print("AWS IoT Connection successful.")
            self._is_connected = True

        except (AwsCrtError, Exception) as e:
            print(f"Error connecting to AWS IoT: {e}", file=sys.stderr)
            self.mqtt_connection = None # Ensure connection is None on failure
            self._is_connected = False
            # Optional: Implement a simple backoff here if desired, but SDK handles retries
            # time.sleep(5)
        finally:
            self._connect_in_progress = False


    def format(self, record):
        # Use default formatter if none is set
        if self.formatter is None:
            self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        log_entry = {
            'timestamp': self.formatter.formatTime(record, self.datefmt),
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(), # Get formatted message
            # Add other fields if needed
            # 'pathname': record.pathname,
            # 'lineno': record.lineno,
        }
        # Include exception info if available
        if record.exc_info:
            log_entry['exception'] = self.formatter.formatException(record.exc_info)
        if record.stack_info:
             log_entry['stack_info'] = self.formatter.formatStack(record.stack_info)

        return json.dumps(log_entry)

    def emit(self, record):
        if not self.endpoint:
            return # Handler not configured

        # Check connection status - SDK handles reconnection attempts in background
        if not self._is_connected:
            # Optionally log locally that publish failed due to connection
            # print(f"Skipping log publish, AWS IoT connection not active for: {record.getMessage()}")
            # Optionally trigger a reconnect attempt if desired, but be careful of loops
            # if not self._connect_in_progress: self._connect()
            return

        try:
            msg = self.format(record)
            if self.mqtt_connection:
                publish_future, packet_id = self.mqtt_connection.publish(
                    topic=self.topic,
                    payload=msg,
                    qos=QoS.AT_LEAST_ONCE # Use QoS enum from v2 SDK
                )
                # Optional: Wait for publish ACK for critical logs, but can slow down logging
                # try:
                #    publish_future.result(timeout=2.0)
                #    # print(f"Log published with packet ID: {packet_id}")
                # except Exception as pub_e:
                #    print(f"Error waiting for publish ACK: {pub_e}", file=sys.stderr)

            else:
                # This shouldn't happen if _is_connected is true, but safeguard
                print("Error: Cannot publish log, MQTT connection is None despite connected state.", file=sys.stderr)
                self._is_connected = False # State inconsistency, mark as disconnected

        except (AwsCrtError, Exception) as e:
            print(f"Error publishing log to AWS IoT: {e}", file=sys.stderr)
            # Connection might be lost, SDK's on_interrupted callback should handle state
            self._is_connected = False # Assume connection is problematic until resume callback
            # Log error locally if possible
            # logging.warning(f"Failed to publish log to IoT: {record.getMessage()}", exc_info=True)


    def close(self):
        print("Closing AWS IoT Handler V2...")
        if self.mqtt_connection:
            print("Disconnecting AWS IoT MQTT connection...")
            disconnect_future = self.mqtt_connection.disconnect()
            if disconnect_future:
                try:
                    disconnect_future.result(timeout=5.0) # Wait for disconnect
                    print("AWS IoT MQTT connection disconnected.")
                except Exception as e:
                    print(f"Error during MQTT disconnect: {e}", file=sys.stderr)
            self.mqtt_connection = None
            self._is_connected = False
        super().close() # Call the parent class's close method 