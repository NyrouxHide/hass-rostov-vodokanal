"""Set up by account number; this provider offers the required data without login."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api import VodokanalClient
from .const import CONF_ACCOUNT, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .exceptions import CannotConnect, InvalidAccount, VodokanalError

ACCOUNT_SCHEMA = vol.Schema(
    {vol.Required(CONF_ACCOUNT): vol.All(str, vol.Match(r"^\d{6,20}$"))}
)


class VodokanalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            account = str(user_input[CONF_ACCOUNT]).strip()
            try:
                ACCOUNT_SCHEMA({CONF_ACCOUNT: account})
            except vol.Invalid:
                return self.async_show_form(
                    step_id="user",
                    data_schema=ACCOUNT_SCHEMA,
                    errors={"base": "invalid_account"},
                )
            await self.async_set_unique_id(account)
            self._abort_if_unique_id_configured()
            client = VodokanalClient(account)
            try:
                await client.async_get_account()
            except InvalidAccount:
                errors["base"] = "invalid_account"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except VodokanalError:
                errors["base"] = "portal_changed"
            finally:
                await client.async_close()
            if not errors:
                return self.async_create_entry(
                    title=f"Ростовводоканал · {account}", data={CONF_ACCOUNT: account}
                )
        return self.async_show_form(
            step_id="user", data_schema=ACCOUNT_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input: dict[str, Any]):
        # Bootstrap creates the entry without a network call. Setup retries outages.
        account = str(user_input[CONF_ACCOUNT]).strip()
        ACCOUNT_SCHEMA({CONF_ACCOUNT: account})
        await self.async_set_unique_id(account)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Ростовводоканал · {account}", data={CONF_ACCOUNT: account}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return VodokanalOptionsFlow()


class VodokanalOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
                }
            ),
        )
