"""Parse the public account forms actually used by lkfl.vodokanalrnd.ru."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup, Tag

from .exceptions import InvalidAccount, PortalChanged
from .models import CounterPage, Finance, Meter

METER_FIELD = re.compile(r"^counters\[(\d+_\d+)\]\[value\]$")
READING_DATE = re.compile(r"\bот\s+(\d{2}\.\d{2}\.\d{2,4})\b")
VERIFICATION_DATE = re.compile(
    r"Дата\s+сл\.\s*поверки:\s*(\d{2}\.\d{2}\.\d{2,4})", re.IGNORECASE
)


def decimal_value(value: Any) -> Decimal:
    """Accept Russian decimal separators, rejecting NaN/infinity and booleans."""
    if isinstance(value, bool) or value is None:
        raise ValueError("A finite numeric value is required")
    try:
        number = Decimal(
            str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
        )
    except InvalidOperation as err:
        raise ValueError("A finite numeric value is required") from err
    if not number.is_finite():
        raise ValueError("A finite numeric value is required")
    return number


def _date(value: str) -> date:
    try:
        return datetime.strptime(
            value, "%d.%m.%Y" if len(value) == 10 else "%d.%m.%y"
        ).date()
    except ValueError as err:
        raise PortalChanged("Invalid date format in the portal") from err


def csrf(form: Tag) -> str:
    token = form.select_one('input[name="_token"]')
    if token is None or not token.get("value"):
        raise PortalChanged("The portal did not provide a CSRF token")
    return str(token["value"])


def lookup_form(html: str) -> dict[str, str]:
    """Read the public lookup form; this POST does not submit meter readings."""
    soup = BeautifulSoup(html, "html.parser")
    for form in soup.find_all("form"):
        if form.select_one('input[name="ls"]') is not None:
            csrf(form)
            return {
                str(item["name"]): str(item.get("value", ""))
                for item in form.select('input[type="hidden"][name]')
            }
    raise PortalChanged("Account lookup form is missing")


def parse_counters(html: str, today: date) -> CounterPage:
    """Use each meter's own block; never match global dates or 'disabled'."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.select_one("form#sendCountersValues")
    if form is None:
        if (
            soup.select_one('.alert-danger, .invalid-feedback, input[name="ls"]')
            is not None
        ):
            raise InvalidAccount("Account lookup was rejected")
        raise PortalChanged("Meter reading form is missing")
    token = csrf(form)
    submit = form.select_one('input[type="submit"], button[type="submit"]')
    form_enabled = submit is None or not submit.has_attr("disabled")
    cancel_form = soup.select_one("form#counter_value_remove")
    cancel_csrf = csrf(cancel_form) if cancel_form else None
    meters: list[Meter] = []
    for item in form.select("input[name]"):
        match = METER_FIELD.fullmatch(str(item.get("name", "")))
        if match is None:
            continue
        key = match[1]
        block = item.find_parent(class_="overlay")
        values = item.find_parent(class_="counter-values")
        if block is None or values is None:
            raise PortalChanged("Meter block is missing")
        # A multi-tariff meter has a separate row for each input/date.
        row = next(
            (
                p
                for p in item.parents
                if p is not values and "Дата сл." in p.get_text(" ", strip=True)
            ),
            values,
        )
        text = row.get_text(" ", strip=True)
        row_id = form.find("input", attrs={"name": f"counters[{key}][rowId]"})
        tariff = form.find("input", attrs={"name": f"counters[{key}][tarif]"})
        number = re.search(
            r"Сч[её]тчик\s*№\s*([\w/-]+)", block.get_text(" ", strip=True)
        )
        if row_id is None or tariff is None or number is None:
            raise PortalChanged("Meter identifier is missing")
        if key != f"{row_id.get('value')}_{tariff.get('value')}":
            raise PortalChanged("Conflicting meter identifiers")
        submitted = READING_DATE.search(text)
        verification = VERIFICATION_DATE.search(text)
        reading_date = _date(submitted[1]) if submitted else None
        remove = row.find(
            "a", class_="remove-value", attrs={"data-counter-key": item["name"]}
        )
        if remove is not None and submitted is None:
            raise PortalChanged(
                "An existing reading has no recognizable submission date"
            )
        service = block.select_one(".type")
        try:
            reading = (
                decimal_value(item["data-old-value"])
                if item.get("data-old-value") not in [None, ""]
                else None
            )
            limit = (
                decimal_value(item["data-max-cons-value"])
                if item.get("data-max-cons-value")
                else None
            )
        except ValueError as err:
            raise PortalChanged("Meter reading has an invalid numeric format") from err
        meters.append(
            Meter(
                id=key,
                number=number[1],
                service=service.get_text(" ", strip=True) if service else "Вода",
                row_id=str(row_id.get("value")),
                tariff=str(tariff.get("value")),
                reading=reading,
                reading_date=reading_date,
                verification_date=_date(verification[1]) if verification else None,
                max_consumption=limit,
                can_submit=form_enabled
                and not item.has_attr("disabled")
                and not item.has_attr("readonly")
                and reading_date != today,
                reading_id=str(remove["data-value"])
                if remove and remove.get("data-value")
                else None,
                can_cancel=bool(
                    remove and remove.get("data-value") and cancel_form and cancel_csrf
                ),
            )
        )
    if not meters or len({meter.id for meter in meters}) != len(meters):
        raise PortalChanged("No meters or duplicate meter identifiers")
    return CounterPage(
        meters=tuple(meters),
        submit_url=str(form.get("action", "")),
        csrf=token,
        cancel_url=str(cancel_form.get("action", "")) if cancel_form else None,
        cancel_csrf=cancel_csrf,
    )


def parse_finance(data: dict[str, Any]) -> Finance:
    """The payment check endpoint is read-only; no payment is created."""
    if not isinstance(data, dict):
        raise PortalChanged("Payment response must be an object")
    if data.get("checkLS") not in (True, 1, "1"):
        raise InvalidAccount("Account was not found by the payment lookup")
    if not isinstance(data.get("filds"), str):
        raise PortalChanged("Payment totals are missing")
    soup = BeautifulSoup(data["filds"], "html.parser")
    debts = soup.find_all("input", attrs={"name": re.compile(r"^pay_summ_\d+$")})
    penalties = soup.find_all("input", attrs={"name": re.compile(r"^pay_peni_\d+$")})
    if not debts or len(debts) != len(penalties):
        raise PortalChanged("Payment totals are missing")
    if {item["name"].removeprefix("pay_summ_") for item in debts} != {
        item["name"].removeprefix("pay_peni_") for item in penalties
    }:
        raise PortalChanged("Payment totals refer to different providers")
    try:
        debt = sum((decimal_value(item.get("value")) for item in debts), Decimal(0))
        penalty = sum(
            (decimal_value(item.get("value")) for item in penalties), Decimal(0)
        )
    except ValueError as err:
        raise PortalChanged("Invalid payment total") from err
    return Finance(
        debt,
        penalty,
        str(data.get("month", "")),
        BeautifulSoup(str(data.get("address", "")), "html.parser").get_text(
            " ", strip=True
        ),
    )
