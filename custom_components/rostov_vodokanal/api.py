"""Asynchronous portal client. Writes are explicit and are never retried."""

import asyncio
import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup

from .const import BASE_URL, TIMEZONE
from .exceptions import (
    CannotConnect,
    MutationUncertain,
    PortalChanged,
    ReadingRejected,
    StaleReading,
    VodokanalError,
)
from .models import AccountData, CounterPage, Meter
from .parser import decimal_value, lookup_form, parse_counters, parse_finance


class VodokanalClient:
    """One isolated cookie session and lock per account, independent of HA."""

    def __init__(self, account: str, *, base_url: str = BASE_URL) -> None:
        if not re.fullmatch(r"\d{6,20}", account):
            raise ValueError("Account must contain 6–20 digits")
        self.account = account
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    def _today(self):
        return datetime.now(ZoneInfo(TIMEZONE)).date()

    async def async_close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _url(self, path: str) -> str:
        url = urljoin(self.base_url + "/", path)
        if (
            urlsplit(url).netloc != urlsplit(self.base_url).netloc
            or urlsplit(url).scheme != urlsplit(self.base_url).scheme
        ):
            raise PortalChanged("Refusing an unexpected form destination")
        return url

    async def _request(
        self, method: str, path: str, *, mutation: bool = False, **kwargs
    ) -> str:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": "HomeAssistant-RostovVodokanal/0.1",
                    "Accept-Language": "ru",
                },
            )
        try:
            async with self._session.request(
                method, self._url(path), **kwargs
            ) as response:
                if response.status >= 400:
                    if mutation:
                        raise MutationUncertain(
                            "The portal returned an error after a write; refresh before deciding what to do"
                        )
                    raise CannotConnect(f"Portal HTTP status {response.status}")
                if urlsplit(str(response.url)).netloc != urlsplit(self.base_url).netloc:
                    raise PortalChanged("Unexpected portal redirect")
                return await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            if mutation:
                raise MutationUncertain(
                    "The write outcome is unknown; do not resend automatically"
                ) from err
            raise CannotConnect("Cannot connect to the portal") from err

    async def _counter_page(self) -> CounterPage:
        html = await self._request("GET", "/counters")
        data = await asyncio.to_thread(lookup_form, html)
        data.update({"ls": self.account, "page_code": "counters_noauth_check_ls"})
        html = await self._request("POST", "/counters", data=data)
        return await asyncio.to_thread(parse_counters, html, self._today())

    async def async_get_account(self) -> AccountData:
        async with self._lock:
            page = await self._counter_page()
            raw = await self._request(
                "GET",
                "/payment/checkLS",
                params={
                    "ls": self.account,
                    "accruals": 0,
                    "page_code": "payment_checkLS",
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            try:
                finance = await asyncio.to_thread(parse_finance, json.loads(raw))
            except (ValueError, TypeError) as err:
                raise PortalChanged("Invalid payment lookup response") from err
            return AccountData(
                self.account, page.meters, finance, datetime.now(ZoneInfo(TIMEZONE))
            )

    @staticmethod
    def _meter(page: CounterPage, meter_id: str | None) -> Meter:
        if meter_id is None and len(page.meters) == 1:
            return page.meters[0]
        for meter in page.meters:
            if meter.id == meter_id:
                return meter
        raise ReadingRejected("Select an existing meter_id")

    async def async_send_reading(
        self, value: Decimal | str | float, meter_id: str | None = None
    ) -> Meter:
        """Only a real new portal record confirms success, even for an equal value."""
        try:
            value = decimal_value(value)
        except ValueError as err:
            raise ReadingRejected("Reading must be a finite number") from err
        if value < 0:
            raise ReadingRejected("Reading cannot be negative")
        if value > Decimal(99999999) or value != value.quantize(Decimal("0.001")):
            raise ReadingRejected(
                "Reading must be at most 99999999 m³ with at most three decimal places"
            )
        async with self._lock:
            before = await self._counter_page()
            meter = self._meter(before, meter_id)
            if not meter.can_submit:
                raise ReadingRejected(
                    "Already submitted today or the portal has disabled submission"
                )
            if meter.reading is not None:
                if value < meter.reading:
                    raise ReadingRejected(
                        "New reading cannot be below the previous reading"
                    )
                if (
                    meter.max_consumption is not None
                    and value - meter.reading >= meter.max_consumption
                ):
                    raise ReadingRejected(
                        "Consumption exceeds the anonymous portal limit"
                    )
            # All fields come from the current form. Other meters are never submitted.
            data = {
                "_token": before.csrf,
                meter.input_name: format(value, "f"),
                f"counters[{meter.id}][rowId]": meter.row_id,
                f"counters[{meter.id}][tarif]": meter.tariff,
            }
            if (
                urlsplit(self._url(before.submit_url)).path.rstrip("/")
                != f"/counters/{self.account}"
            ):
                raise PortalChanged("Unexpected submission action")
            result = await self._request(
                "POST", before.submit_url, data=data, mutation=True
            )
            if BeautifulSoup(result, "html.parser").select_one(
                ".alert-danger, .alert-error"
            ):
                raise ReadingRejected(
                    "The portal rejected the reading; refresh to inspect its state"
                )
            try:
                after = self._meter(await self._counter_page(), meter.id)
            except VodokanalError as err:
                raise MutationUncertain(
                    "Reading was sent but confirmation could not be read"
                ) from err
            if (
                after.reading != value
                or after.reading_date != self._today()
                or not after.reading_id
                or after.reading_id == meter.reading_id
            ):
                raise MutationUncertain(
                    "The portal has not confirmed a new reading record; do not resend automatically"
                )
            return after

    async def async_cancel_reading(
        self, reading_id: str, meter_id: str | None = None
    ) -> Meter:
        """Require the expected record ID so a stale button cannot remove a newer record."""
        async with self._lock:
            before = await self._counter_page()
            meter = self._meter(before, meter_id)
            if not meter.reading_id or meter.reading_id != str(reading_id):
                raise StaleReading(
                    "The reading ID no longer matches; refresh before cancelling"
                )
            if not meter.can_cancel or not before.cancel_url or not before.cancel_csrf:
                raise ReadingRejected("The portal does not offer cancellation")
            if (
                urlsplit(self._url(before.cancel_url)).path.rstrip("/")
                != f"/counters/{self.account}/value/remove"
            ):
                raise PortalChanged("Unexpected cancellation action")
            result = await self._request(
                "POST",
                before.cancel_url,
                mutation=True,
                data={
                    "_token": before.cancel_csrf,
                    "value": meter.reading_id,
                    "key": meter.input_name,
                },
            )
            if BeautifulSoup(result, "html.parser").select_one(
                ".alert-danger, .alert-error"
            ):
                raise ReadingRejected("The portal rejected cancellation")
            try:
                after = self._meter(await self._counter_page(), meter.id)
            except VodokanalError as err:
                raise MutationUncertain(
                    "Cancellation was sent but confirmation could not be read"
                ) from err
            if after.reading_id == meter.reading_id:
                raise MutationUncertain(
                    "The portal has not confirmed cancellation; do not retry automatically"
                )
            return after
