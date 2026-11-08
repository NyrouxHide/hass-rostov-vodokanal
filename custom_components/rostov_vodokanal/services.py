"""Explicit portal actions and completion events for notification automations."""

import logging
from datetime import UTC, datetime

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service

from .const import DOMAIN
from .exceptions import MutationUncertain, ReadingRejected, StaleReading, VodokanalError

BASE_SCHEMA = {vol.Required("config_entry_id"): cv.string}
_LOGGER = logging.getLogger(__name__)
METER_SCHEMA = {
    **BASE_SCHEMA,
    vol.Optional("meter_id"): vol.All(str, vol.Match(r"^\d+_\d+$")),
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register once for all accounts, including when no entry is loaded yet."""
    if hass.services.has_service(DOMAIN, "send_reading"):
        return

    def fire(call: ServiceCall, suffix: str, data: dict) -> None:
        hass.bus.async_fire(
            f"{DOMAIN}_{call.service}_{suffix}",
            {"config_entry_id": call.data["config_entry_id"], **data},
            context=call.context,
        )

    def failed(call: ServiceCall, code: str, *, uncertain: bool = False) -> None:
        # No portal body, cookies, CSRF, or unvalidated input values in events.
        fire(
            call,
            "failed",
            {
                "meter_id": call.data.get("meter_id"),
                "error_code": code,
                "outcome": "unknown" if uncertain else "failed",
            },
        )

    async def handle(call: ServiceCall):
        coordinator = None
        response = None
        event_data = {}
        try:
            entry = service.async_get_config_entry(
                hass, DOMAIN, call.data["config_entry_id"]
            )
            coordinator = entry.runtime_data
            if call.service == "refresh":
                await coordinator.async_request_refresh()
                if not coordinator.last_update_success:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN, translation_key="refresh_failed"
                    )
                response = {"refreshed": True}
            else:
                if call.service == "send_reading":
                    result = await coordinator.client.async_send_reading(
                        call.data["value"], call.data.get("meter_id")
                    )
                else:
                    result = await coordinator.client.async_cancel_reading(
                        call.data["reading_id"], call.data.get("meter_id")
                    )
                    event_data["cancelled_reading_id"] = call.data["reading_id"]
                response = {
                    "success": True,
                    "meter_id": result.id,
                    "reading": str(result.reading)
                    if result.reading is not None
                    else None,
                    "date": result.reading_date.isoformat()
                    if result.reading_date
                    else None,
                    "reading_id": result.reading_id,
                }
                device = dr.async_get(hass).async_get_device(
                    identifiers={(DOMAIN, f"{coordinator.client.account}:{result.id}")}
                )
                event_data.update(
                    {
                        "account": coordinator.client.account,
                        "device_id": device.id if device else None,
                        "meter_number": result.number,
                        "service": result.service,
                        "tariff": result.tariff,
                    }
                )
        except StaleReading as err:
            failed(call, "stale_reading")
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="stale_reading"
            ) from err
        except ReadingRejected as err:
            failed(call, "rejected")
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="rejected",
                translation_placeholders={"reason": str(err)},
            ) from err
        except MutationUncertain as err:
            failed(call, "mutation_uncertain", uncertain=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="mutation_uncertain"
            ) from err
        except VodokanalError as err:
            failed(call, "portal_error")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="portal_error"
            ) from err
        except HomeAssistantError:
            failed(call, "unavailable")
            raise
        except Exception as err:
            failed(call, "unexpected_error")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="portal_error"
            ) from err
        else:
            # A confirmed write remains successful even if a later balance refresh fails.
            fire(
                call,
                "completed",
                {
                    **response,
                    **event_data,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return response if call.return_response else None
        finally:
            if coordinator is not None and call.service != "refresh":
                try:
                    await coordinator.async_request_refresh()
                except Exception as err:  # noqa: BLE001 - preserve the confirmed write outcome
                    # The action outcome was already determined above. Never make a
                    # successful write look unsent because a later poll failed.
                    _LOGGER.warning(
                        "Post-action refresh failed: %s", type(err).__name__
                    )

    for name, schema in (
        ("refresh", BASE_SCHEMA),
        (
            "send_reading",
            {**METER_SCHEMA, vol.Required("value"): vol.Any(str, int, float)},
        ),
        (
            "cancel_reading",
            {
                **METER_SCHEMA,
                vol.Required("reading_id"): vol.All(str, vol.Match(r"^\d+$")),
            },
        ),
    ):
        hass.services.async_register(
            DOMAIN,
            name,
            handle,
            schema=vol.Schema(schema),
            supports_response=SupportsResponse.OPTIONAL,
        )
