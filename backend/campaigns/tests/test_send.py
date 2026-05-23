"""Tests for the thin send interface in campaigns/send.py.

Covers both the stub path (taken when `outbound` is absent — the default on
this branch) and the real path (monkeypatched via a fake `outbound.api`
module so we can exercise both branches in a single test run).
"""

from __future__ import annotations

import logging
import sys
import types

from campaigns import send as send_module
from campaigns.send import (
    SendResult,
    _real_impl_factory,
    _select_impl,
    _stub_impl,
    force_send_impl,
    send_campaign_message,
)


class _FakeCustomer:
    pk = 1
    phone = "+14165550000"
    name = "Stubbed"


class _FakeMessage:
    def __init__(self, id):
        self.id = id


# ---------------------------------------------------------------------------
# Stub path
# ---------------------------------------------------------------------------


def test_stub_returns_ok_and_logs(caplog):
    with caplog.at_level(logging.INFO, logger="campaigns.send"):
        result = _stub_impl(_FakeCustomer(), "hi", "campaign:1:run:1")
    assert isinstance(result, SendResult)
    assert result.ok is True
    assert result.provider_message_id is None
    assert result.reason is None
    assert any("stub send" in r.message for r in caplog.records)


def test_select_impl_picks_stub_when_outbound_missing(monkeypatch):
    """When outbound.api is unimportable, _select_impl falls back to the stub.

    Setting sys.modules[...] = None is Python's standard sentinel that makes
    subsequent `import` calls raise ImportError. We use it here because
    outbound IS installed on disk in this branch (post-merge); the only way
    to simulate its absence is to actively block the import.
    """
    monkeypatch.setitem(sys.modules, "outbound", None)
    monkeypatch.setitem(sys.modules, "outbound.api", None)
    impl = _select_impl()
    assert impl is _stub_impl


# ---------------------------------------------------------------------------
# Real path (monkeypatched outbound)
# ---------------------------------------------------------------------------


def _install_fake_outbound(monkeypatch, recorded):
    """Inject a fake outbound.api module with a recording enqueue_message."""
    outbound_pkg = types.ModuleType("outbound")
    outbound_api = types.ModuleType("outbound.api")

    def enqueue_message(customer, template_key, context, channel, reference):
        recorded.append(
            {
                "customer": customer,
                "template_key": template_key,
                "context": context,
                "channel": channel,
                "reference": reference,
            }
        )
        return _FakeMessage(id=42)

    outbound_api.enqueue_message = enqueue_message
    outbound_pkg.api = outbound_api
    monkeypatch.setitem(sys.modules, "outbound", outbound_pkg)
    monkeypatch.setitem(sys.modules, "outbound.api", outbound_api)


def test_select_impl_picks_real_when_outbound_present(monkeypatch):
    recorded: list = []
    _install_fake_outbound(monkeypatch, recorded)
    impl = _select_impl()
    assert impl is not _stub_impl
    result = impl(_FakeCustomer(), "hi", "campaign:1:run:1")
    assert result.ok is True
    assert result.provider_message_id == "42"
    assert recorded[0]["template_key"] == "campaign"
    assert recorded[0]["context"] == {"body": "hi"}
    assert recorded[0]["channel"] == "sms"


def test_real_impl_delegates_payload():
    recorded: list = []

    def fake_enqueue(customer, template_key, context, channel, reference):
        recorded.append((customer, template_key, context, channel, reference))
        return _FakeMessage(id="abc123")

    real = _real_impl_factory(fake_enqueue)
    result = real(_FakeCustomer(), "Hi {customer.name}", "campaign:5:run:9")
    assert result.ok is True
    assert result.provider_message_id == "abc123"
    assert recorded == [
        (
            recorded[0][0],
            "campaign",
            {"body": "Hi {customer.name}"},
            "sms",
            "campaign:5:run:9",
        )
    ]


# ---------------------------------------------------------------------------
# Test fixture: force_send_impl
# ---------------------------------------------------------------------------


def test_force_send_impl_swaps_and_restores():
    original = send_module._get_impl()
    calls: list = []

    def custom(customer, body, reference):
        calls.append(reference)
        return SendResult(ok=True, provider_message_id="forced", reason=None)

    with force_send_impl(custom):
        assert send_module._get_impl() is custom
        result = send_campaign_message(_FakeCustomer(), "x", "ref-1")
        assert result.provider_message_id == "forced"

    assert send_module._get_impl() is original
    assert calls == ["ref-1"]


def test_both_paths_in_one_run(monkeypatch, caplog):
    """The runner test will need to flip impls mid-test — prove it works."""
    # Stub path
    with caplog.at_level(logging.INFO, logger="campaigns.send"):
        with force_send_impl(_stub_impl):
            r1 = send_campaign_message(_FakeCustomer(), "hi", "ref-stub")
    assert r1.provider_message_id is None
    assert any("stub send" in m.message for m in caplog.records)

    # Real path (fake outbound)
    recorded: list = []
    _install_fake_outbound(monkeypatch, recorded)
    real_impl = _select_impl()
    with force_send_impl(real_impl):
        r2 = send_campaign_message(_FakeCustomer(), "hi", "ref-real")
    assert r2.provider_message_id == "42"
    assert recorded[0]["reference"] == "ref-real"
