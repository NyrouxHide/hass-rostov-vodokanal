"""Submission and cancellation availability as advertised by the portal."""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import callback

from .entity import VodokanalEntity

DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="can_submit", translation_key="can_submit", icon="mdi:upload"
    ),
    BinarySensorEntityDescription(
        key="can_cancel", translation_key="can_cancel", icon="mdi:undo"
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new_meters():
        for meter in coordinator.data.meters:
            if meter.id not in known:
                known.add(meter.id)
                async_add_entities(
                    VodokanalBinarySensor(coordinator, d, meter) for d in DESCRIPTIONS
                )

    add_new_meters()
    entry.async_on_unload(coordinator.async_add_listener(add_new_meters))


class VodokanalBinarySensor(VodokanalEntity, BinarySensorEntity):
    def __init__(self, coordinator, description, meter):
        super().__init__(coordinator, description.key, meter)
        self.entity_description = description

    @property
    def is_on(self):
        meter = self.meter
        if meter is None:
            return None
        if self.entity_description.key == "can_cancel":
            return meter.can_cancel
        return (
            meter.can_submit and meter.reading_date != self.coordinator.client._today()
        )
