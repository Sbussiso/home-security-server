import logging
import json
import os
import sys
import time  # Keep time for potential backoff if needed, though SDK handles some

# ─── Correct AWS IoT SDK v2 Imports ──────────────────────────────────────────
try:
    from awscrt import io
    from awscrt.mqtt import QoS, Connection as MqttConnection     # QoS & Connection types
    from awsiot import mqtt_connection_builder                      # builder lives in awsiot
    from awscrt.exceptions import AwsCrtError                       # exception class
    SDK_V2_AVAILABLE = True
except ImportError as e:
    print(f"Error importing AWS IoT SDK v2/CRT components: {e}", file=sys.stderr)
    print("Please ensure 'awsiotsdk' (and 'awscrt') are installed correctly.", file=sys.stderr)
    io = None
    mqtt_connection_builder = None
    QoS = None
    MqttConnection = None
    AwsCrtError = Exception
    SDK_V2_AVAILABLE = False
# ────────────────────────────────────────────────────────────────────────────

class AWSIoTHandlerV2(logging.Handler):
    """
    A logging handler that publishes messages to an AWS IoT Core MQTT topic using SDK v2.
    Relies on the SDK's internal connection management and callbacks.
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.topic = os.getenv('AWS_IOT_LOG_TOPIC')

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
        self.client_id = os.getenv('AWS_IOT_CLIENT_ID', f'security-server-logger-v2-{os.getpid()}')

        self.mqtt_connection: MqttConnection | None = None
        self._is_connected = False
        self._connect_in_progress = False
        # CRT components - keep alive for the connection
        self.event_loop_group = None
        self.host_resolver = None
        self.client_bootstrap = None

        # Disable if SDK missing
        if not SDK_V2_AVAILABLE or io is None:
            print("Error: AWS IoT SDK V2 or CRT components not available. Handler disabled.", file=sys.stderr)
            self.endpoint = None
            return

        # Disable if config incomplete
        if not all([self.topic, self.endpoint, self.cert_path, self.key_path, self.ca_path]):
            print("Warning: AWS IoT logging environment variables not fully configured. Handler disabled.", file=sys.stderr)
            self.endpoint = None
            return

        # Initialize CRT components
        try:
            self.event_loop_group = io.EventLoopGroup(1)
            self.host_resolver    = io.DefaultHostResolver(self.event_loop_group)
            self.client_bootstrap = io.ClientBootstrap(self.event_loop_group, self.host_resolver)
        except Exception as init_e:
            print(f"Error initializing CRT components: {init_e}", file=sys.stderr)
            self.endpoint = None
            return

        # Attempt initial connection
        self._connect()

    def _on_connection_interrupted(self, connection, error, **kwargs):
        print(f"AWS IoT connection interrupted. Error: {error}", file=sys.stderr)
        self._is_connected = False

    def _on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        print(f"AWS IoT connection resumed. Return code: {return_code} Session present: {session_present}")
        self._is_connected = True

    def _connect(self):
        if not self.endpoint or self._connect_in_progress or self._is_connected or not self.client_bootstrap:
            return

        self._connect_in_progress = True
        print(f"Attempting to connect to AWS IoT endpoint: {self.endpoint} with client ID: {self.client_id}")
        try:
            self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
                endpoint=self.endpoint,
                cert_filepath=self.cert_path,
                pri_key_filepath=self.key_path,
                ca_filepath=self.ca_path,
                client_bootstrap=self.client_bootstrap,
                client_id=self.client_id,
                clean_session=False,
                keep_alive_secs=30,
                on_connection_interrupted=self._on_connection_interrupted,
                on_connection_resumed=self._on_connection_resumed
            )
            connect_future = self.mqtt_connection.connect()
            connect_future.result(timeout=10.0)
            print("AWS IoT Connection successful.")
            self._is_connected = True
        except (AwsCrtError, Exception) as e:
            print(f"Error connecting to AWS IoT: {e}", file=sys.stderr)
            self.mqtt_connection = None
            self._is_connected = False
        finally:
            self._connect_in_progress = False

    def format(self, record):
        # Ensure a formatter is available
        if self.formatter is None:
            self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        # Use the formatter's datefmt
        timestamp = self.formatter.formatTime(record, self.formatter.datefmt)
        entry = {
            'timestamp': timestamp,
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            entry['exception'] = self.formatter.formatException(record.exc_info)
        if record.stack_info:
            entry['stack_info'] = self.formatter.formatStack(record.stack_info)
        return json.dumps(entry)

    def emit(self, record):
        if not self.endpoint or not self._is_connected:
            return
        try:
            payload = self.format(record)
            if self.mqtt_connection:
                self.mqtt_connection.publish(
                    topic=self.topic,
                    payload=payload,
                    qos=QoS.AT_LEAST_ONCE
                )
            else:
                print("Error: MQTT connection missing despite connected state.", file=sys.stderr)
                self._is_connected = False
        except (AwsCrtError, Exception) as e:
            print(f"Error publishing log to AWS IoT: {e}", file=sys.stderr)
            self._is_connected = False

    def close(self):
        print("Closing AWS IoT Handler V2...")
        if self.mqtt_connection:
            print("Disconnecting AWS IoT MQTT connection...")
            dfut = self.mqtt_connection.disconnect()
            if dfut:
                try:
                    dfut.result(timeout=5.0)
                    print("AWS IoT MQTT connection disconnected.")
                except Exception as e:
                    print(f"Error during MQTT disconnect: {e}", file=sys.stderr)
            self._is_connected = False
            self.mqtt_connection = None
        super().close()
