"""Portal data, independent of Home Assistant."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Meter:
    """One meter/tariff. Record ID identifies a reading, not a meter."""

    id: str
    number: str
    service: str
    row_id: str
    tariff: str
    reading: Decimal | None
    reading_date: date | None
    verification_date: date | None
    max_consumption: Decimal | None
    can_submit: bool
    reading_id: str | None
    can_cancel: bool

    @property
    def input_name(self) -> str:
        return f"counters[{self.id}][value]"


@dataclass(frozen=True, slots=True)
class CounterPage:
    """Transient form state. CSRF tokens never become entity attributes."""

    meters: tuple[Meter, ...]
    submit_url: str
    csrf: str = field(repr=False)
    cancel_url: str | None = None
    cancel_csrf: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Finance:
    debt: Decimal
    penalties: Decimal
    period: str
    address: str = field(repr=False)

    @property
    def total(self) -> Decimal:
        return self.debt + self.penalties


@dataclass(frozen=True, slots=True)
class AccountData:
    account: str
    meters: tuple[Meter, ...]
    finance: Finance
    updated_at: datetime
