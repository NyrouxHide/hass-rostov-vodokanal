"""Shared, periodically refreshed portal data."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VodokanalClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .exceptions import VodokanalError
from .models import AccountData

_LOGGER = logging.getLogger(__name__)


class VodokanalCoordinator(DataUpdateCoordinator[AccountData]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: VodokanalClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> AccountData:
        try:
            return await self.client.async_get_account()
        except VodokanalError as err:
            raise UpdateFailed(str(err)) from err
