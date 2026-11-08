"""Account and meter devices with stable, independent identifiers."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN
from .coordinator import VodokanalCoordinator
from .models import Meter


def account_device_info(account: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, account)},
        name=f"Ростовводоканал · {account}",
        manufacturer="АО Ростовводоканал",
        model="Лицевой счёт",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=f"{BASE_URL}/counters/{account}",
    )


class VodokanalEntity(CoordinatorEntity[VodokanalCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: VodokanalCoordinator, key: str, meter: Meter | None = None
    ) -> None:
        super().__init__(coordinator)
        account = coordinator.client.account
        self.meter_id = meter.id if meter else None
        self._attr_unique_id = (
            f"{account}_{meter.id}_{key}" if meter else f"{account}_{key}"
        )
        self._attr_device_info = (
            DeviceInfo(
                identifiers={(DOMAIN, f"{account}:{meter.id}")},
                name=f"Счётчик воды {meter.number}",
                manufacturer="АО Ростовводоканал",
                model=meter.service,
                serial_number=meter.number,
                via_device=(DOMAIN, account),
                configuration_url=f"{BASE_URL}/counters/{account}",
            )
            if meter
            else account_device_info(account)
        )

    @property
    def meter(self) -> Meter | None:
        return next(
            (m for m in self.coordinator.data.meters if m.id == self.meter_id), None
        )

    @property
    def available(self) -> bool:
        return super().available and (self.meter_id is None or self.meter is not None)
