"""Optional MQTT transport. Receivers choose how to dispatch onto their thread."""
import logging
import math

logger = logging.getLogger(__name__)


class TimeSynchronizer:
    def __init__(self, topic, on_time):
        self.topic = topic
        self.on_time = on_time
        self.client = None

    def connect(self):
        if not isinstance(self.topic, str) or not self.topic:
            return
        import paho.mqtt.client as mqtt
        from paho.mqtt.subscribeoptions import SubscribeOptions
        client = mqtt.Client(protocol=mqtt.MQTTv5)
        client.on_message = self._on_message
        try:
            client.connect('127.0.0.1', 1883, 60)
            client.subscribe(self.topic, options=SubscribeOptions(noLocal=True))
            client.loop_start()
            self.client = client
        except OSError:
            logger.warning('No connection to MQTT server')

    def publish(self, time):
        if self.client is not None:
            self.client.publish(self.topic, payload=str(time))

    def _on_message(self, client, userdata, message):
        if message.topic != self.topic:
            return
        try:
            time = float(message.payload.decode())
            if math.isfinite(time):
                self.on_time(time)
        except (ValueError, UnicodeError):
            logger.warning('Ignoring invalid MQTT timestamp')

    def close(self):
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None
