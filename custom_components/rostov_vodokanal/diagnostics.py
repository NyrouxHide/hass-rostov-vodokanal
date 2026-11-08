"""Diagnostics without account numbers, addresses, meter IDs, or CSRF/cookies."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal

from homeassistant.components.diagnostics import async_redact_data

REDACT = {"account", "address", "number", "id", "row_id", "reading_id"}


def _json_value(value):
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "options": dict(entry.options),
        "last_update_success": coordinator.last_update_success,
        "data": async_redact_data(_json_value(asdict(coordinator.data)), REDACT)
        if coordinator.data
        else None,
    }
