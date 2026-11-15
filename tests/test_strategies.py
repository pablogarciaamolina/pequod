import pytest

from pequod.strategies import StrategyCatalog

TEXT = {  # no payload
    "plain_message", "introduce", "warm_opener",  # opening
    "direct_ask", "indirect_ask", "choice_question", "yes_no_check", "assumption_check", "open_invitation",  # asking
    "shared_interest", "give_first",
    "build_on_reply", "clarify", "confirm_back", "thank_and_close",  # after a reply
    "gentle_nudge", "rephrase", "smaller_ask", "channel_switch",  # after silence
    "explain_why", "easy_out",  # after hesitation or refusal
}
LINKS = {"info_link", "call_link", "form_link"}
ALL = TEXT | LINKS
NOT_SMS = {"warm_opener", "open_invitation", "give_first", "info_link", "form_link"}  # too long, or no room for them


@pytest.fixture
def catalog(cfg):
    return StrategyCatalog.from_config(cfg.strategies)


def test_catalog_loads_default_config(catalog):
    assert set(catalog.for_channel()) == ALL
    assert catalog.get("info_link").payload == {"url": "https://example.com/info"}
    assert {name for name, s in catalog.for_channel().items() if s.payload} == LINKS


def test_every_description_says_when_to_use_it(catalog):
    assert all(" Use " in s.description for s in catalog.for_channel().values())


def test_for_channel_filters(catalog):
    assert set(catalog.for_channel("sms")) == ALL - NOT_SMS
    assert set(catalog.for_channel("email")) == ALL


def test_get_unknown_raises(catalog):
    with pytest.raises(ValueError, match="Unknown strategy 'nope'"):
        catalog.get("nope")
