"""Exercise real HTTP form parsing and state changes against a fake provider."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from custom_components.rostov_vodokanal.exceptions import (
    MutationUncertain,
    PortalChanged,
    ReadingRejected,
    StaleReading,
)


async def test_read_only_account_and_money(client, portal):
    data = await client.async_get_account()
    assert data.finance.debt == Decimal("123.45")
    assert data.finance.penalties == Decimal("6.78")
    assert data.finance.total == Decimal("130.23")
    assert data.meters[0].reading == 2
    assert data.meters[0].reading_date == date(2026, 11, 7)
    assert data.meters[0].verification_date == date(2030, 2, 3)
    assert data.meters[0].can_submit
    assert portal.writes == []


async def test_submit_and_same_day_lock(client, portal):
    result = await client.async_send_reading("3,125")
    assert result.reading == Decimal("3.125")
    assert result.reading_date == date(2026, 11, 8)
    assert result.reading_id == "1002"
    assert not result.can_submit
    with pytest.raises(ReadingRejected):
        await client.async_send_reading(4)
    assert len(portal.writes) == 1


async def test_equal_value_requires_a_new_record(client, portal):
    result = await client.async_send_reading(2)
    assert result.reading == 2
    assert result.reading_id == "1002"


async def test_cancel_only_expected_record_and_restore_previous(client, portal):
    new = await client.async_send_reading(3)
    result = await client.async_cancel_reading(new.reading_id)
    assert result.reading_id == "1001"
    assert result.reading == 2
    assert result.can_submit
    assert [kind for kind, _ in portal.writes] == ["submit", "cancel"]


async def test_stale_cancellation_never_writes(client, portal):
    with pytest.raises(StaleReading):
        await client.async_cancel_reading("9999")
    assert portal.writes == []


async def test_concurrent_submissions_cannot_double_send(client, portal):
    outcomes = await asyncio.gather(
        client.async_send_reading(3),
        client.async_send_reading(4),
        return_exceptions=True,
    )
    assert len(portal.writes) == 1
    assert sum(isinstance(r, ReadingRejected) for r in outcomes) == 1


@pytest.mark.parametrize(
    "value",
    [-1, 1, "NaN", "Infinity", float("nan"), True, "2.0001", "1e1000000", "2e-999999"],
)
async def test_invalid_reading_never_writes(client, portal, value):
    with pytest.raises(ReadingRejected):
        await client.async_send_reading(value)
    assert portal.writes == []


async def test_anonymous_consumption_limit_boundary(client, portal):
    with pytest.raises(ReadingRejected):
        await client.async_send_reading(102)
    assert portal.writes == []


async def test_unknown_meter_never_writes(client, portal):
    with pytest.raises(ReadingRejected):
        await client.async_send_reading(3, "999_0")
    assert portal.writes == []


async def test_server_error_after_acceptance_never_retries(client, portal):
    portal.fail_write = True
    with pytest.raises(MutationUncertain):
        await client.async_send_reading(3)
    assert len(portal.writes) == 1
    data = await client.async_get_account()
    assert data.meters[0].reading == 3


async def test_success_banner_is_not_proof_of_submission(client, portal):
    portal.fake_success = True
    with pytest.raises(MutationUncertain):
        await client.async_send_reading(2)
    assert len(portal.writes) == 1


async def test_missing_balance_is_not_zero(client, portal):
    portal.payment_invalid = True
    with pytest.raises(PortalChanged):
        await client.async_get_account()


async def test_external_form_action_is_rejected(client, portal, monkeypatch):
    original = portal.page
    monkeypatch.setattr(
        portal,
        "page",
        lambda: original().replace(
            f'action="{portal.base_url}/counters/123456789"',
            'action="https://example.invalid/counters/123456789"',
        ),
    )
    with pytest.raises(PortalChanged):
        await client.async_send_reading(3)
    assert portal.writes == []
