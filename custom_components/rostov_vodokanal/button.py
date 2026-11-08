"""Read-only manual refresh button."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import VodokanalEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([VodokanalRefreshButton(entry.runtime_data)])


class VodokanalRefreshButton(VodokanalEntity, ButtonEntity):
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "refresh")

    async def async_press(self):
        await self.coordinator.async_request_refresh()
