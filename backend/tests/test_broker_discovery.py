from unittest.mock import Mock

import pytest

from app import broker_discovery as discovery


@pytest.fixture
def advertiser(monkeypatch):
    constructor = Mock(side_effect=lambda **kwargs: Mock())
    monkeypatch.setattr(discovery, "Zeroconf", constructor)
    instance = discovery.BrokerDiscovery(1884)
    yield instance, constructor
    instance.withdraw()


def test_dhcp_change_moves_hostname_to_new_interface(monkeypatch, advertiser):
    service, constructor = advertiser
    hosts = iter(["192.168.1.7", "192.168.1.7", "192.168.2.8", None])
    monkeypatch.setattr(discovery, "lan_address", lambda: next(hosts))
    service.refresh()
    first = service.zeroconf
    first_info = service.info
    assert first_info.server == "parkflow-iot.local."
    assert first_info.parsed_addresses() == ["192.168.1.7"]
    assert first_info.port == 1884
    service.refresh()
    assert constructor.call_count == 1
    service.refresh()
    first.unregister_service.assert_called_once_with(first_info)
    first.close.assert_called_once()
    assert service.info.server == first_info.server
    assert service.info.parsed_addresses() == ["192.168.2.8"]
    constructor.assert_called_with(interfaces=["192.168.2.8"], ip_version=discovery.IPVersion.V4Only)
    second = service.zeroconf
    service.refresh()
    second.close.assert_called_once()
    assert service.host is service.zeroconf is None


def test_failed_registration_closes_socket_and_can_retry(monkeypatch):
    first, second = Mock(), Mock()
    first.register_service.side_effect = OSError("Wi-Fi disconnected")
    monkeypatch.setattr(discovery, "Zeroconf", Mock(side_effect=[first, second]))
    monkeypatch.setattr(discovery, "lan_address", lambda: "192.168.1.6")
    service = discovery.BrokerDiscovery(1884)
    try:
        with pytest.raises(OSError):
            service.refresh()
        first.close.assert_called_once()
        assert service.host is service.zeroconf is None
        service.refresh()
        assert service.zeroconf is second
    finally:
        service.withdraw()


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("broker.example.com", False)])
def test_backend_advertises_only_local_broker_and_stops_on_shutdown(monkeypatch, host, expected):
    from fastapi.testclient import TestClient
    from app import main, mqtt_receiver

    receiver = Mock(host=host, port=1884)
    advertiser = Mock()
    constructor = Mock(return_value=advertiser)
    monkeypatch.setenv("MQTT_ENABLED", "1")
    monkeypatch.setattr(mqtt_receiver, "MqttReceiver", Mock(return_value=receiver))
    monkeypatch.setattr(discovery, "BrokerDiscovery", constructor)
    with TestClient(main.app):
        receiver.start.assert_called_once()
        assert constructor.called is expected
    receiver.stop.assert_called_once()
    if expected:
        advertiser.start.assert_called_once()
        advertiser.stop.assert_called_once()
