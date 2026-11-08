"""Portal values, not guesses or locally remembered submission dates."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory

from .entity import VodokanalEntity
from .models import AccountData, Meter


@dataclass(frozen=True, kw_only=True)
class VodokanalSensorDescription(SensorEntityDescription):
    value_fn: Callable[[AccountData, Meter | None], Any]


ACCOUNT_SENSORS = (
    VodokanalSensorDescription(
        key="debt",
        translation_key="debt",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RUB",
        value_fn=lambda a, m: a.finance.debt,
    ),
    VodokanalSensorDescription(
        key="penalties",
        translation_key="penalties",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RUB",
        value_fn=lambda a, m: a.finance.penalties,
    ),
    VodokanalSensorDescription(
        key="total_due",
        translation_key="total_due",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RUB",
        value_fn=lambda a, m: a.finance.total,
    ),
    VodokanalSensorDescription(
        key="billing_period",
        translation_key="billing_period",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda a, m: a.finance.period,
    ),
    VodokanalSensorDescription(
        key="updated_at",
        translation_key="updated_at",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda a, m: a.updated_at,
    ),
)
METER_SENSORS = (
    VodokanalSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda a, m: m.reading,
    ),
    VodokanalSensorDescription(
        key="last_submission",
        translation_key="last_submission",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda a, m: m.reading_date,
    ),
    VodokanalSensorDescription(
        key="verification_date",
        translation_key="verification_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda a, m: m.verification_date,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        VodokanalSensor(coordinator, description) for description in ACCOUNT_SENSORS
    )
    known: set[str] = set()

    @callback
    def add_new_meters():
        for meter in coordinator.data.meters:
            if meter.id not in known:
                known.add(meter.id)
                async_add_entities(
                    VodokanalSensor(coordinator, d, meter) for d in METER_SENSORS
                )

    add_new_meters()
    entry.async_on_unload(coordinator.async_add_listener(add_new_meters))


class VodokanalSensor(VodokanalEntity, SensorEntity):
    entity_description: VodokanalSensorDescription

    def __init__(self, coordinator, description, meter=None):
        super().__init__(coordinator, description.key, meter)
        self.entity_description = description

    @property
    def native_value(self):
        if self.meter_id is not None and self.meter is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, self.meter)

    @property
    def extra_state_attributes(self):
        if self.meter_id is None or self.meter is None:
            return None
        meter = self.meter
        return {
            "meter_id": meter.id,
            "reading_id": meter.reading_id,
            "meter_number": meter.number,
            "service": meter.service,
            "tariff": meter.tariff,
        }
