"""Mosquitto Dynamic Security RPC. Device passwords never go into API logs."""
import json
import os
import threading
import uuid
import paho.mqtt.client as mqtt


class BrokerUnavailable(RuntimeError):
    pass


class BrokerAdmin:
    def __init__(self, host=None, port=None, username=None, password=None):
        self.host = host or os.getenv("MQTT_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("MQTT_PORT", "1884"))
        self.username = username or os.getenv("MQTT_ADMIN_USERNAME", "broker_admin")
        self.password = password or os.getenv("MQTT_ADMIN_PASSWORD")
        self.lock = threading.Lock()

    def request(self, command, **arguments):
        if not self.password:
            raise BrokerUnavailable("Broker administration is not configured")
        # A separate short-lived client keeps RPC waits off the telemetry thread.
        with self.lock:
            ready, done = threading.Event(), threading.Event()
            response = {}
            correlation = uuid.uuid4().hex
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="admin-" + correlation)
            client.username_pw_set(self.username, self.password)
            def on_connect(c, userdata, flags, reason, properties):
                if not reason.is_failure:
                    c.subscribe("$CONTROL/dynamic-security/v1/response", qos=1)
                else:
                    response["error"] = "Broker administrator authentication failed"
                    done.set()
            def on_subscribe(c, userdata, mid, reasons, properties):
                if any(reason.is_failure for reason in reasons):
                    response["error"] = "Broker administrator subscription refused"
                    done.set()
                else:
                    ready.set()
            def on_message(c, userdata, message):
                try:
                    for item in json.loads(message.payload).get("responses", []):
                        if item.get("correlationData") == correlation:
                            response.update(item)
                            done.set()
                except (ValueError, TypeError):
                    pass
            client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
            try:
                client.connect(self.host, self.port, 15)
                client.loop_start()
                if not ready.wait(3):
                    raise BrokerUnavailable("Broker administration connection timed out")
                payload = {"commands": [{"command": command, "correlationData": correlation, **arguments}]}
                client.publish("$CONTROL/dynamic-security/v1", json.dumps(payload), qos=1)
                if not done.wait(3):
                    raise BrokerUnavailable("Broker did not acknowledge administration request")
                if response.get("error"):
                    raise BrokerUnavailable(str(response["error"]))
                return response.get("data", {})
            except OSError as exc:
                raise BrokerUnavailable("Could not reach MQTT broker") from exc
            finally:
                client.disconnect()
                client.loop_stop()

    def provision(self, code, password):
        self.request("createClient", username=code, password=password,
                     roles=[{"rolename": "device", "priority": 1}])

    def set_enabled(self, code, enabled):
        self.request("enableClient" if enabled else "disableClient", username=code)

    def rotate_password(self, code, password):
        self.request("setClientPassword", username=code, password=password)
