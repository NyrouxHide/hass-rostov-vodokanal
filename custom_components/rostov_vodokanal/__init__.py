"""Independent integration; the existing 'vodokanal' domain is never touched."""

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .api import VodokanalClient
from .const import CONF_ACCOUNT, DOMAIN
from .coordinator import VodokanalCoordinator
from .entity import account_device_info
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]
type VodokanalConfigEntry = ConfigEntry[VodokanalCoordinator]

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {vol.Required(CONF_ACCOUNT): vol.All(str, vol.Match(r"^\d{6,20}$"))}
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    if DOMAIN in config:
        # Optional one-time bootstrap; the normal setup method is the UI flow.
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=config[DOMAIN],
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VodokanalConfigEntry) -> bool:
    client = VodokanalClient(entry.data[CONF_ACCOUNT])
    coordinator = VodokanalCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            **account_device_info(entry.data[CONF_ACCOUNT]),
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await client.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: VodokanalConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VodokanalConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.async_close()
        return True
    return False
