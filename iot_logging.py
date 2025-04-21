import logging
import json
import os
import threading
import time
import sys
from concurrent.futures import Future

# Attempt to import V2 SDK components
try:
    from awsiot import mqtt_connection_builder # type: ignore
    from awsiot.mqtt import QoS # type: ignore
    from awsiot.exceptions import AwsCrtError # type: ignore
except ImportError as e:
    print(f"Error importing AWS IoT SDK v2 components: {e}")
    print("Please ensure 'awsiot-device-sdk-python-v2' is installed correctly.")
    # Define placeholders if import fails to avoid downstream errors on class definition
    mqtt_connection_builder = None
    QoS = None
    AwsCrtError = Exception # Fallback to base Exception

class AWSIoTHandlerV2(logging.Handler):
    """A logging handler that publishes messages to an AWS IoT Core MQTT topic using SDK v2."""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.topic = os.getenv('AWS_IOT_LOG_TOPIC')
        self.endpoint = os.getenv('AWS_IOT_ENDPOINT')
        self.cert_path = os.getenv('AWS_IOT_CERT_PATH')
        self.key_path = os.getenv('AWS_IOT_KEY_PATH')
        self.ca_path = os.getenv('AWS_IOT_CA_PATH')
        self.client_id = os.getenv('AWS_IOT_CLIENT_ID', 'security-server-logger-v2')
        self.mqtt_connection = None
        self._connection_lock = threading.Lock()
        self._connect_attempted = False
        self._is_connected = False

        if not all([self.topic, self.endpoint, self.cert_path, self.key_path, self.ca_path]):
            print("Error: AWS IoT logging environment variables not fully configured.")
            # Indicate that handler is unusable
            self.endpoint = None
            return # Exit init early

        if mqtt_connection_builder is None:
            print("Error: AWS IoT SDK v2 not imported correctly. Handler disabled.")
            self.endpoint = None
            return # Exit init early

        # Connection callbacks
        self.connection_interrupted = Future()
        self.connection_resumed = Future()
        self.connection_closed = Future()

        # Start connection attempt in a separate thread to avoid blocking logger init
        self._connect_thread = threading.Thread(target=self._connect, daemon=True)
        self._connect_thread.start()

    # --- Connection Callbacks --- #
    def _on_connection_interrupted(self, connection, error, **kwargs):
        print(f"AWS IoT connection interrupted. error: {error}")
        self._is_connected = False
        self.connection_interrupted.set_result(error)

    def _on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        print(f"AWS IoT connection resumed. return_code: {return_code} session_present: {session_present}")
        self._is_connected = True
        self.connection_resumed.set_result(session_present)
        # Reset other futures for subsequent events
        self.connection_interrupted = Future()
        self.connection_closed = Future()

    def _on_connection_closed(self, **kwargs):
        print("AWS IoT connection closed.")
        self._is_connected = False
        self.connection_closed.set_result(True)

    def _connect(self):
        if not self.endpoint:
            print("Skipping AWS IoT connection, endpoint not configured.")
            return

        with self._connection_lock:
            if self.mqtt_connection is not None:
                return # Already connected or connection attempt in progress
            self._connect_attempted = True # Mark that we tried

            print(f"Connecting to AWS IoT v2 endpoint: {self.endpoint} with client ID: {self.client_id}")
            try:
                self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
                    endpoint=self.endpoint,
                    cert_filepath=self.cert_path,
                    pri_key_filepath=self.key_path,
                    ca_filepath=self.ca_path,
                    client_id=self.client_id,
                    keep_alive_secs=30,
                    on_connection_interrupted=self._on_connection_interrupted,
                    on_connection_resumed=self._on_connection_resumed,
                    on_connection_closed=self._on_connection_closed
                )

                connect_future = self.mqtt_connection.connect()
                # Wait for the connection result
                connect_future.result() # Raises exception on failure
                print("AWS IoT V2 Connection successful.")
                self._is_connected = True
                 # Reset futures for next events
                self.connection_resumed = Future()
                self.connection_closed = Future()

            except (AwsCrtError, Exception) as e:
                print(f"Error connecting to AWS IoT v2: {e}", file=sys.stderr)
                self.mqtt_connection = None # Ensure connection is None on failure
                self._is_connected = False
                # Optionally add retry logic here, but simple failure for now

    def _ensure_connection(self):
        """Checks connection status and initiates connect if needed."""
        if not self.endpoint:
             return False # Not configured
        
        with self._connection_lock:
            if self.mqtt_connection is None and not self._connect_attempted:
                # Initial connection hasn't even been tried yet
                print("Waiting for initial connection attempt...")
                self._connect_thread.join(timeout=5.0) # Wait for initial attempt
                if self.mqtt_connection is None:
                     print("Initial connection attempt failed or timed out.")
                     return False

            # If connection is None, it failed previously, don't retry automatically here
            if self.mqtt_connection is None:
                #print("AWS IoT connection not established (previous failure?).")
                return False
                
            # If we think we have a connection object, check its actual status
            if not self._is_connected:
                 # Check if a disconnect event occurred
                 if self.connection_closed.done():
                      print("Detected closed connection.")
                      self.mqtt_connection = None # Clear the connection object
                      self._connect_attempted = False # Allow reconnect attempt later maybe? Or handle reconnect differently
                      self.connection_closed = Future() # Reset future
                      return False
                 else:
                      # Still waiting for resume or initial connection?
                      #print("Connection not confirmed as active.")
                      return False # Not ready yet

        return True # Seems connected

    def format(self, record):
        log_entry = {
            'timestamp': self.formatter.formatTime(record, self.datefmt),
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(),
            'pathname': record.pathname,
            'lineno': record.lineno,
        }
        if record.exc_info:
            log_entry['exception'] = self.formatter.formatException(record.exc_info)
        return json.dumps(log_entry)

    def emit(self, record):
        if not self.endpoint:
            return # Handler not configured

        if not self._ensure_connection():
            # Optionally log locally that publish failed due to connection
            # print(f"Skipping log publish, AWS IoT connection not available for: {record.getMessage()}")
            return

        try:
            msg = self.format(record)
            if self.mqtt_connection:
                publish_future, _ = self.mqtt_connection.publish(
                    topic=self.topic,
                    payload=msg,
                    qos=QoS.AT_LEAST_ONCE # Use QoS enum from v2 SDK
                )
                # We might want to wait briefly or handle the future result
                # publish_future.result(timeout=2.0) # Example: Wait up to 2 seconds
            else:
                print("Error: Cannot publish log, MQTT v2 connection is None.")

        except AwsCrtError as e:
            print(f"AwsCrtError during publish: {e}. Connection might be lost.")
            self._is_connected = False # Assume connection is lost
            # Reset futures related to connection state if needed
            self.connection_interrupted = Future()
            self.connection_resumed = Future()
            self.connection_closed = Future()
            # Let reconnect happen on next emit attempt if logic allows
        except Exception as e:
            print(f"Error publishing log to AWS IoT v2: {e}", file=sys.stderr)
            # Log error locally
            logging.basicConfig().error(f"Failed to publish log to IoT v2: {record.getMessage()}", exc_info=True)
            # Assume connection is problematic
            self._is_connected = False
            # Potentially try to disconnect cleanly if object exists
            # if self.mqtt_connection:
            #    disconnect_future = self.mqtt_connection.disconnect()
            #    if disconnect_future:
            #        disconnect_future.result()
            # self.mqtt_connection = None 

    def close(self):
        print("Closing AWS IoT Handler V2...")
        if self.mqtt_connection:
            print("Disconnecting AWS IoT MQTT v2 connection...")
            disconnect_future = self.mqtt_connection.disconnect()
            if disconnect_future:
                try:
                    disconnect_future.result(timeout=5.0) # Wait for disconnect
                    print("AWS IoT MQTT v2 connection disconnected.")
                except Exception as e:
                    print(f"Error during MQTT v2 disconnect: {e}")
            self.mqtt_connection = None
            self._is_connected = False
        super().close() 