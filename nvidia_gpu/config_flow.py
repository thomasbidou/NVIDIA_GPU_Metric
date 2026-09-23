"""Config flow for the NVIDIA GPU Stats integration."""
from __future__ import annotations

import aiohttp

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DEFAULT_PORT, DOMAIN

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="127.0.0.1"): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


async def _validate(host: str, port: int) -> dict | None:
    """Probe the daemon once. Returns payload if reachable, else None."""
    url = f"http://{host}:{port}/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except (aiohttp.ClientError, ValueError):
        return None


class NvidiaGpuFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for NVIDIA GPU Stats."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict = {}
        if user_input is not None:
            host: str = user_input[CONF_HOST]
            port: int = int(user_input.get(CONF_PORT, DEFAULT_PORT))

            data = await _validate(host, port)
            if data is None:
                errors["base"] = "cannot_reach"
            else:
                return self.async_create_entry(
                    title=data.get("name") or f"GPU {host}",
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=CONFIG_SCHEMA,
            errors=errors,
        )
