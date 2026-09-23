"""Data update coordinator for the NVIDIA GPU Stats integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_EXPECTED_KEYS = (
    "gpu_utilization_pct",
    "memory_used_pct",
    "memory_used_gib",
    "memory_total_gib",
    "power_draw_w",
    "power_limit_w",
    "power_usage_pct",
    "temperature_c",
    "fan_speed_pct",
)


class NvidiaGpuCoordinator(DataUpdateCoordinator[dict]):
    """Polls the nvidia-gpu-stats HTTP daemon once per interval."""

    def __init__(self, hass, entry_id, host: str, port: int, scan_interval: timedelta) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=scan_interval,
        )
        self._url = f"http://{host}:{port}/"
        self._timeout = aiohttp.ClientTimeout(total=10)
        # Stable, per-box identity (so multiple boxes / multiple GPUs never
        # collide on entity unique_id or device identifier).
        self.entry_id = entry_id
        self.host = host
        # Populated after the first successful refresh.
        self.device_name = "NVIDIA GPU"
        self.box = None  # hostname reported by the daemon

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                self._url, timeout=self._timeout, allow_redirects=False
            ) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"expected 200, got {resp.status}")
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise UpdateFailed(f"cannot reach nvidia-gpu-stats: {exc}") from exc
        except (ValueError, aiohttp.ContentTypeError) as exc:
            raise UpdateFailed(f"bad payload from nvidia-gpu-stats: {exc}") from exc

        for key in _EXPECTED_KEYS:
            if key not in data:
                _LOGGER.debug("missing field %s in payload", key)
        data.setdefault("name", "NVIDIA GPU")
        self.device_name = data["name"]
        self.box = data.get("box")
        return data
