"""Advertise the MQTT broker on the active LAN, including after a DHCP change."""
import ipaddress
import logging
import socket
import threading

from zeroconf import IPVersion, ServiceInfo, Zeroconf

HOSTNAME = "parkflow-iot.local."
SERVICE_TYPE = "_mqtt._tcp.local."
SERVICE_NAME = "ParkFlow MQTT." + SERVICE_TYPE
log = logging.getLogger(__name__)


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect selects the active route; it sends no network packet.
            probe.connect(("192.0.2.1", 9))
            host = probe.getsockname()[0]
        address = ipaddress.IPv4Address(host)
        if not (address.is_loopback or address.is_link_local or address.is_unspecified):
            return host
    except OSError:
        pass
    return None


class BrokerDiscovery:
    def __init__(self, port):
        self.port = port
        self.host = None
        self.zeroconf = None
        self.info = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name="mqtt-mdns", daemon=True)

    def start(self):
        self.thread.start()

    def withdraw(self):
        previous, info = self.zeroconf, self.info
        self.zeroconf = self.info = self.host = None
        if previous:
            try:
                if info:
                    previous.unregister_service(info)
            finally:
                previous.close()

    def refresh(self):
        host = lan_address()
        if host == self.host:
            return
        self.withdraw()
        if not host:
            return
        advertiser = Zeroconf(interfaces=[host], ip_version=IPVersion.V4Only)
        info = ServiceInfo(SERVICE_TYPE, SERVICE_NAME, port=self.port,
                           addresses=[socket.inet_aton(host)], server=HOSTNAME,
                           properties={"project": "parkflow"}, host_ttl=10, other_ttl=10)
        try:
            advertiser.register_service(info)
        except Exception:
            advertiser.close()
            raise
        self.zeroconf, self.info, self.host = advertiser, info, host
        log.info("MQTT discovery: %s -> %s:%s", HOSTNAME.rstrip("."), host, self.port)

    def run(self):
        try:
            while not self.stopped.is_set():
                try:
                    self.refresh()
                except Exception:
                    log.warning("MQTT mDNS unavailable; retrying in 5 seconds", exc_info=True)
                self.stopped.wait(5)
        finally:
            self.withdraw()

    def stop(self):
        self.stopped.set()
        self.thread.join(timeout=8)
