"""An isolated provider simulator. Tests never call a real provider or HA Core."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import homeassistant  # noqa: F401  # Initialize HA's voluptuous compatibility first.
import pytest
from aiohttp import web
from bs4 import BeautifulSoup

from custom_components.rostov_vodokanal.api import VodokanalClient

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 8)
ACCOUNT = "123456789"
METER_ID = "123456_0"


class Portal:
    def __init__(self):
        self.records = [("1001", Decimal(2), date(2026, 11, 7))]
        self.writes = []
        self.fail_write = False
        self.fake_success = False
        self.payment_invalid = False
        self.base_url = ""

    def page(self):
        b = BeautifulSoup((FIXTURES / "counters.html").read_text(), "html.parser")
        rid, reading, day = self.records[-1]
        item = b.find("input", attrs={"name": f"counters[{METER_ID}][value]"})
        item["data-old-value"] = str(reading)
        if day == TODAY:
            item["disabled"] = "disabled"
        for note in b.select(".block-note"):
            if "от " in note.get_text():
                note.string = "от " + day.strftime("%d.%m.%y")
        remove = b.select_one(".remove-value")
        remove["data-value"] = rid
        for form in b.find_all("form"):
            form["action"] = str(form["action"]).replace(
                "https://lkfl.vodokanalrnd.ru", self.base_url
            )
        return str(b)

    async def lookup(self, request):
        if request.method == "POST":
            data = await request.post()
            assert data["ls"] == ACCOUNT
            assert data["page_code"] == "counters_noauth_check_ls"
            assert data["_token"] == "lookup-token"
            return web.Response(text=self.page(), content_type="text/html")
        return web.Response(
            text='<form><input name="ls"><input type="hidden" name="_token" value="lookup-token"></form>',
            content_type="text/html",
        )

    async def payment(self, request):
        assert request.query["ls"] == ACCOUNT
        if self.payment_invalid:
            return web.json_response({"checkLS": True})
        data = json.loads((FIXTURES / "payment.json").read_text())
        b = BeautifulSoup(data["filds"], "html.parser")
        b.find("input", attrs={"name": "pay_summ_404"})["value"] = "123,45"
        b.find("input", attrs={"name": "pay_peni_404"})["value"] = "6,78"
        data["filds"] = str(b)
        return web.json_response(data)

    async def submit(self, request):
        data = dict(await request.post())
        self.writes.append(("submit", data))
        assert set(data) == {
            "_token",
            f"counters[{METER_ID}][value]",
            f"counters[{METER_ID}][rowId]",
            f"counters[{METER_ID}][tarif]",
        }
        assert data["_token"] == "fixture-token"
        assert data[f"counters[{METER_ID}][rowId]"] == "123456"
        assert data[f"counters[{METER_ID}][tarif]"] == "0"
        if not self.fake_success:
            self.records.append(
                (
                    str(int(self.records[-1][0]) + 1),
                    Decimal(data[f"counters[{METER_ID}][value]"]),
                    TODAY,
                )
            )
        if self.fail_write:
            raise web.HTTPServiceUnavailable()
        return web.Response(text='<div class="alert-success">Принято</div>')

    async def cancel(self, request):
        data = dict(await request.post())
        self.writes.append(("cancel", data))
        assert data == {
            "_token": "fixture-token",
            "value": self.records[-1][0],
            "key": f"counters[{METER_ID}][value]",
        }
        self.records.pop()
        return web.Response(text='<div class="alert-success">Удалено</div>')


@pytest.fixture
async def portal(unused_tcp_port):
    instance = Portal()
    app = web.Application()
    app.router.add_route("*", "/counters", instance.lookup)
    app.router.add_get("/payment/checkLS", instance.payment)
    app.router.add_post(f"/counters/{ACCOUNT}", instance.submit)
    app.router.add_post(f"/counters/{ACCOUNT}/value/remove", instance.cancel)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    instance.base_url = f"http://127.0.0.1:{unused_tcp_port}"
    try:
        yield instance
    finally:
        await runner.cleanup()


@pytest.fixture
async def client(portal, monkeypatch):
    instance = VodokanalClient(ACCOUNT, base_url=portal.base_url)
    monkeypatch.setattr(instance, "_today", lambda: TODAY)
    try:
        yield instance
    finally:
        await instance.async_close()
