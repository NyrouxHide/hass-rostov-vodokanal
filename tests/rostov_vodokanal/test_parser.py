"""Regressions for real portal markup, dates, tariffs, and Russian numbers."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from custom_components.rostov_vodokanal.exceptions import InvalidAccount, PortalChanged
from custom_components.rostov_vodokanal.parser import (
    decimal_value,
    parse_counters,
    parse_finance,
)

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 8)


def test_unrelated_disabled_button_does_not_block_submission():
    html = (
        FIXTURES / "counters.html"
    ).read_text() + "<button disabled>Other feature</button>"
    assert parse_counters(html, TODAY).meters[0].can_submit


def test_readonly_meter_and_same_day_both_block_submission():
    html = (FIXTURES / "counters.html").read_text()
    b = BeautifulSoup(html, "html.parser")
    b.select_one("input[data-old-value]")["readonly"] = ""
    assert not parse_counters(str(b), TODAY).meters[0].can_submit
    assert (
        not parse_counters(html.replace("07.11.26", "08.11.26"), TODAY)
        .meters[0]
        .can_submit
    )


def test_multiple_meters_have_independent_values_and_dates():
    html = (FIXTURES / "counters.html").read_text()
    b = BeautifulSoup(html, "html.parser")
    block = str(b.select_one("input[data-old-value]").find_parent(class_="overlay"))
    new = (
        block.replace("123456", "222222")
        .replace("76543210", "99999999")
        .replace("07.11.26", "08.11.26")
        .replace('data-old-value="2"', 'data-old-value="55"')
        .replace('data-value="1001"', 'data-value="2001"')
    )
    b.select_one("#sendCountersValues").append(BeautifulSoup(new, "html.parser"))
    page = parse_counters(str(b), TODAY)
    assert [(m.id, m.reading, m.can_submit) for m in page.meters] == [
        ("123456_0", Decimal(2), True),
        ("222222_0", Decimal(55), False),
    ]


def test_missing_csrf_fails_closed():
    b = BeautifulSoup((FIXTURES / "counters.html").read_text(), "html.parser")
    b.select_one('input[name="_token"]').decompose()
    with pytest.raises(PortalChanged):
        parse_counters(str(b), TODAY)


def test_duplicate_meter_ids_fail_closed():
    b = BeautifulSoup((FIXTURES / "counters.html").read_text(), "html.parser")
    b.select_one("#sendCountersValues").append(
        BeautifulSoup(
            str(b.select_one("input[data-old-value]").find_parent(class_="overlay")),
            "html.parser",
        )
    )
    with pytest.raises(PortalChanged):
        parse_counters(str(b), TODAY)


def test_unknown_account():
    with pytest.raises(InvalidAccount):
        parse_counters(
            '<form><input name="ls"></form><div class="alert-danger">Не найден</div>',
            TODAY,
        )


def test_financial_totals_not_service_rows_are_summed():
    data = json.loads((FIXTURES / "payment.json").read_text())
    b = BeautifulSoup(data["filds"], "html.parser")
    b.find("input", attrs={"name": "pay_summ_404"})["value"] = "1 234,56"
    b.find("input", attrs={"name": "pay_peni_404"})["value"] = "10,01"
    data["filds"] = str(b)
    assert parse_finance(data).total == Decimal("1244.57")


def test_non_object_finance_is_not_accepted():
    with pytest.raises(PortalChanged):
        parse_finance([])


def test_decimal_separator_and_non_breaking_space():
    assert decimal_value("1\u00a0234,567") == Decimal("1234.567")


def test_cancellation_is_unavailable_without_its_form():
    b = BeautifulSoup((FIXTURES / "counters.html").read_text(), "html.parser")
    b.select_one("#counter_value_remove").decompose()
    meter = parse_counters(str(b), TODAY).meters[0]
    assert meter.reading_id == "1001"
    assert not meter.can_cancel


def test_existing_record_without_date_fails_closed():
    html = (FIXTURES / "counters.html").read_text().replace("07.11.26", "unknown")
    with pytest.raises(PortalChanged):
        parse_counters(html, TODAY)


def test_financial_totals_for_different_providers_fail_closed():
    data = json.loads((FIXTURES / "payment.json").read_text())
    data["filds"] = data["filds"].replace('name="pay_peni_404"', 'name="pay_peni_999"')
    with pytest.raises(PortalChanged):
        parse_finance(data)
