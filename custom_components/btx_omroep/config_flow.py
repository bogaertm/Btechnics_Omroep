"""Config flow voor Btechnics Omroep."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_BASIS_URL, CONF_PIN, CONF_TTS, DEFAULT_PIN, DOMAIN
from .tuner import FrontierOmroep, TunerFout


class OmroepConfigFlow(ConfigFlow, domain=DOMAIN):
    """Tuner toevoegen op IP adres."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        fouten: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            tuner = FrontierOmroep(async_get_clientsession(self.hass), host, user_input[CONF_PIN])
            try:
                info = await tuner.info()
                await tuner.bronnen()
            except TunerFout:
                fouten["base"] = "niet_bereikbaar"
            else:
                return self.async_create_entry(
                    title=info.get("naam") or host, data={CONF_HOST: host, CONF_PIN: user_input[CONF_PIN]}
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                vol.Required(CONF_PIN, default=DEFAULT_PIN): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=fouten)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OmroepOptionsFlow()


class OmroepOptionsFlow(OptionsFlow):
    """PIN en basis URL aanpassen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        fouten: dict[str, str] = {}
        if user_input is not None:
            basis = (user_input.get(CONF_BASIS_URL) or "").strip().rstrip("/")
            if basis and not re.fullmatch(r"https?://[^/\s]+", basis):
                fouten[CONF_BASIS_URL] = "ongeldige_url"
            else:
                tuner = FrontierOmroep(
                    async_get_clientsession(self.hass), self.config_entry.data[CONF_HOST], user_input[CONF_PIN]
                )
                try:
                    await tuner.info()
                except TunerFout:
                    fouten["base"] = "niet_bereikbaar"
                else:
                    return self.async_create_entry(data={**user_input, CONF_BASIS_URL: basis})
        huidig = {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_PIN, default=huidig.get(CONF_PIN, DEFAULT_PIN)): str,
                vol.Optional(
                    CONF_BASIS_URL, description={"suggested_value": huidig.get(CONF_BASIS_URL, "")}
                ): str,
                vol.Optional(CONF_TTS, description={"suggested_value": huidig.get(CONF_TTS)}): EntitySelector(
                    EntitySelectorConfig(domain="tts")
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=fouten)
