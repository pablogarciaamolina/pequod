import pytest

from pequod.strategies import StrategyCatalog

ALL = {"plain_message", "kb_link", "booking_link", "intake_form"}


@pytest.fixture
def catalog(cfg):
    return StrategyCatalog.from_config(cfg.strategies)


def test_catalog_loads_default_config(catalog):
    assert set(catalog.for_channel()) == ALL
    assert catalog.get("kb_link").payload == {"url": "https://kb.example/erp-sync"}
    assert catalog.get("plain_message").payload is None


def test_for_channel_filters(catalog):
    assert set(catalog.for_channel("sms")) == {"plain_message", "booking_link"}
    assert set(catalog.for_channel("email")) == ALL


def test_get_unknown_raises(catalog):
    with pytest.raises(ValueError, match="Unknown strategy 'nope'"):
        catalog.get("nope")
