"""Validate integration contracts against the installed HA 2026.11 APIs."""

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import Context
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.rostov_vodokanal import CONFIG_SCHEMA
from custom_components.rostov_vodokanal.config_flow import VodokanalConfigFlow
from custom_components.rostov_vodokanal.const import DOMAIN
from custom_components.rostov_vodokanal.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.rostov_vodokanal.exceptions import (
    CannotConnect,
    InvalidAccount,
    PortalChanged,
)
from custom_components.rostov_vodokanal.sensor import METER_SENSORS, VodokanalSensor
from custom_components.rostov_vodokanal.services import async_setup_services


def make_flow():
    flow = VodokanalConfigFlow()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow.async_create_entry = Mock(
        side_effect=lambda **kw: {"type": "create_entry", **kw}
    )
    flow.async_show_form = Mock(side_effect=lambda **kw: {"type": "form", **kw})
    return flow


async def test_ui_setup_validates_account_and_closes_session():
    client = SimpleNamespace(async_get_account=AsyncMock(), async_close=AsyncMock())
    flow = make_flow()
    with patch(
        "custom_components.rostov_vodokanal.config_flow.VodokanalClient",
        return_value=client,
    ):
        result = await flow.async_step_user({"account": "123456789"})
    assert result["type"] == "create_entry"
    assert result["data"] == {"account": "123456789"}
    flow.async_set_unique_id.assert_awaited_once_with("123456789")
    client.async_get_account.assert_awaited_once()
    client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    "error, expected",
    [
        (CannotConnect, "cannot_connect"),
        (InvalidAccount, "invalid_account"),
        (PortalChanged, "portal_changed"),
    ],
)
async def test_ui_setup_reports_provider_errors(error, expected):
    client = SimpleNamespace(
        async_get_account=AsyncMock(side_effect=error("test")), async_close=AsyncMock()
    )
    with patch(
        "custom_components.rostov_vodokanal.config_flow.VodokanalClient",
        return_value=client,
    ):
        result = await make_flow().async_step_user({"account": "123456789"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": expected}
    client.async_close.assert_awaited_once()


async def test_import_is_idempotent_and_does_not_access_portal():
    flow = make_flow()
    flow._abort_if_unique_id_configured.side_effect = AbortFlow("already_configured")
    with patch(
        "custom_components.rostov_vodokanal.config_flow.VodokanalClient"
    ) as client_class:
        with pytest.raises(AbortFlow):
            await flow.async_step_import({"account": "123456789"})
        client_class.assert_not_called()


async def test_invalid_account_has_a_useful_form_error():
    result = await make_flow().async_step_user({"account": "not-an-account"})
    assert result["errors"] == {"base": "invalid_account"}


def test_yaml_bootstrap_preserves_other_domains():
    cfg = {DOMAIN: {"account": "123456789"}, "vodokanal": {}, "automation": []}
    assert CONFIG_SCHEMA(cfg) == cfg


async def test_meter_identity_and_dates_come_from_provider(client):
    data = await client.async_get_account()
    coordinator = SimpleNamespace(client=client, data=data, last_update_success=True)
    meter = data.meters[0]
    sensor = VodokanalSensor(
        coordinator, next(d for d in METER_SENSORS if d.key == "last_submission"), meter
    )
    assert sensor.native_value == date(2026, 11, 7)
    assert sensor.device_info["via_device"] == (DOMAIN, "123456789")
    assert sensor.extra_state_attributes["reading_id"] == "1001"
    coordinator.data = replace(
        data,
        meters=(replace(meter, reading_id="1002", reading_date=date(2026, 11, 8)),),
    )
    assert sensor.native_value == date(2026, 11, 8)
    assert sensor.extra_state_attributes["reading_id"] == "1002"
    assert sensor.unique_id == "123456789_123456_0_last_submission"


async def test_diagnostics_redacts_identifiers_and_contains_no_tokens(client):
    data = await client.async_get_account()
    coordinator = SimpleNamespace(data=data, last_update_success=True)
    result = await async_get_config_entry_diagnostics(
        None, SimpleNamespace(runtime_data=coordinator, options={})
    )
    raw = json.dumps(result)
    for secret in [
        "123456789",
        "76543210",
        "123456_0",
        "1001",
        "Тестовый адрес",
        "fixture-token",
    ]:
        assert secret not in raw


class Services:
    def __init__(self):
        self.actions = {}
        self.events = []

    def has_service(self, domain, name):
        return (domain, name) in self.actions

    def async_register(self, domain, name, handler, **kwargs):
        self.actions[(domain, name)] = (handler, kwargs["schema"])


@pytest.fixture
def service_context(client, monkeypatch):
    registry = Services()
    hass = SimpleNamespace(services=registry, bus=SimpleNamespace(async_fire=Mock()))
    hass.bus.async_fire.side_effect = lambda event_type, event_data, context: (
        registry.events.append((event_type, event_data, context))
    )
    coordinator = SimpleNamespace(
        client=client, async_request_refresh=AsyncMock(), last_update_success=True
    )
    entry = SimpleNamespace(runtime_data=coordinator)
    monkeypatch.setattr(
        "custom_components.rostov_vodokanal.services.service.async_get_config_entry",
        lambda *a: entry,
    )
    monkeypatch.setattr(
        "custom_components.rostov_vodokanal.services.dr.async_get",
        lambda hass: SimpleNamespace(
            async_get_device=lambda **kw: SimpleNamespace(id="meter-device")
        ),
    )
    async_setup_services(hass)
    async_setup_services(hass)  # An additional account must not replace actions.
    assert len(registry.actions) == 3
    return registry, coordinator


async def call(context, name, **kwargs):
    registry, _ = context
    return_response = kwargs.pop("return_response", True)
    handler, schema = registry.actions[(DOMAIN, name)]
    data = schema({"config_entry_id": "test-entry", **kwargs})
    return await handler(
        SimpleNamespace(
            service=name, data=data, return_response=return_response, context=Context()
        )
    )


async def test_actions_send_and_cancel_have_useful_responses(service_context, portal):
    sent = await call(service_context, "send_reading", value=3)
    assert sent == {
        "success": True,
        "meter_id": "123456_0",
        "reading": "3",
        "date": "2026-11-08",
        "reading_id": "1002",
    }
    cancelled = await call(
        service_context, "cancel_reading", reading_id=sent["reading_id"]
    )
    assert cancelled["reading_id"] == "1001"
    assert len(portal.writes) == 2
    assert service_context[1].async_request_refresh.await_count == 2


async def test_action_without_response_returns_none(service_context):
    assert (
        await call(service_context, "send_reading", value=3, return_response=False)
        is None
    )


async def test_failed_action_raises_and_refreshes(service_context, portal):
    with pytest.raises(ServiceValidationError):
        await call(service_context, "cancel_reading", reading_id="9999")
    assert portal.writes == []
    service_context[1].async_request_refresh.assert_awaited_once()


async def test_uncertain_action_is_not_reported_as_success(service_context, portal):
    portal.fail_write = True
    with pytest.raises(HomeAssistantError):
        await call(service_context, "send_reading", value=3)
    assert len(portal.writes) == 1
    service_context[1].async_request_refresh.assert_awaited_once()
    events = service_context[0].events
    assert [e[0] for e in events] == ["rostov_vodokanal_send_reading_failed"]
    assert events[0][1]["outcome"] == "unknown"


async def test_send_completion_event_is_emitted_without_response(service_context):
    await call(service_context, "send_reading", value=3, return_response=False)
    events = service_context[0].events
    assert len(events) == 1
    event_type, data, context = events[0]
    assert event_type == "rostov_vodokanal_send_reading_completed"
    assert data["success"] is True
    assert data["reading"] == "3"
    assert data["reading_id"] == "1002"
    assert data["device_id"] == "meter-device"
    assert data["account"] == "123456789"
    assert data["config_entry_id"] == "test-entry"
    assert data["date"] == "2026-11-08"
    assert context is not None


async def test_cancel_event_identifies_cancelled_record_and_restored_reading(
    service_context,
):
    sent = await call(service_context, "send_reading", value=3)
    await call(service_context, "cancel_reading", reading_id=sent["reading_id"])
    event_type, data, _ = service_context[0].events[-1]
    assert event_type == "rostov_vodokanal_cancel_reading_completed"
    assert data["cancelled_reading_id"] == "1002"
    assert data["reading_id"] == "1001"
    assert data["reading"] == "2"


async def test_stale_cancel_has_only_failure_event(service_context):
    with pytest.raises(ServiceValidationError):
        await call(service_context, "cancel_reading", reading_id="9999")
    events = service_context[0].events
    assert len(events) == 1
    assert events[0][0] == "rostov_vodokanal_cancel_reading_failed"
    assert events[0][1]["error_code"] == "stale_reading"


async def test_post_write_poll_failure_does_not_hide_success(service_context):
    service_context[1].async_request_refresh.side_effect = RuntimeError(
        "Polling failed"
    )
    result = await call(service_context, "send_reading", value=3)
    assert result["success"]
    assert [e[0] for e in service_context[0].events] == [
        "rostov_vodokanal_send_reading_completed"
    ]
