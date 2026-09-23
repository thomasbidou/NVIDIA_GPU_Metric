"""Ship the bundled Lovelace card into Home Assistant's ``www/`` and register it.

Same pattern as the ``lmstudio`` integration on this box:

* Everything under ``www/`` in this package ships with the repo. At setup we
  mirror it into ``/homeassistant/www/`` so Lovelace can load the card via its
  standard URL (``/local/nvidia-gpu-card.js``).
* The copy is idempotent and content-aware: a file is written only when the
  bundled copy actually differs, so browser caches are not invalidated on
  every HA restart.
* The card URL is also registered via ``add_extra_js_url`` so the frontend
  injects a ``<script type="module">`` tag on every Lovelace render, independent
  of whether a Lovelace resource entry exists in storage. This is the durable
  path that keeps the card available even if a resource entry is ever dropped.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__package__)

#: The URL the browser loads to get the card bundle.
CARD_URL = "/local/nvidia-gpu-card.js"


def _bundled_dir() -> Path:
    return Path(__file__).resolve().parent / "www"


def _www_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www"))


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_content(a: Path, b: Path) -> bool:
    if not a.exists() or not b.exists():
        return False
    try:
        return _digest(a) == _digest(b)
    except OSError:
        return False


def _copy_sync(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _copy_many(
    sources: list[Path], root: Path, bundled: Path, written: list[Path]
) -> None:
    to_copy = set(written)
    for src in sources:
        dst = root / src.relative_to(bundled)
        if dst in to_copy:
            _copy_sync(src, dst)


def _plan_copies(bundled: Path, root: Path) -> tuple[list[Path], list[Path]]:
    """Synchronous scan: return (all sources, files that need a refresh).

    Runs in an executor to keep the event loop free of blocking I/O.
    """
    if not bundled.is_dir():
        return [], []
    sources = sorted(p for p in bundled.rglob("*") if p.is_file())
    written: list[Path] = []
    for src in sources:
        dst = root / src.relative_to(bundled)
        if not _same_content(src, dst):
            written.append(dst)
    return sources, written


async def async_ship_card(hass: HomeAssistant) -> list[Path]:
    """Ensure the bundled card is present under ``www/``."""
    bundled = _bundled_dir()
    root = _www_root(hass)
    loop = asyncio.get_running_loop()
    sources, written = await loop.run_in_executor(None, _plan_copies, bundled, root)
    if not written:
        return []
    await loop.run_in_executor(None, _copy_many, sources, root, bundled, written)
    _LOGGER.info("nvidia_gpu: shipped %d Lovelace card file(s) to %s", len(written), root)
    return written


async def async_register_card(hass: HomeAssistant) -> bool:
    """Register the card so the frontend always loads it."""
    ok = False

    # --- primary: add_extra_js_url -------------------------------------
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, CARD_URL)
        ok = True
        _LOGGER.info("nvidia_gpu: card registered via add_extra_js_url at %s", CARD_URL)
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "nvidia_gpu: add_extra_js_url unavailable; relying on resource only",
            exc_info=True,
        )

    # --- secondary: lovelace resource entry (idempotent) ---------------
    lovelace_data = hass.data.get("lovelace")
    if lovelace_data is None:
        return ok
    resources = getattr(lovelace_data, "resources", None) or (
        lovelace_data.get("resources") if isinstance(lovelace_data, dict) else None
    )
    if resources is None or not hasattr(resources, "async_create_item"):
        return ok
    try:
        if hasattr(resources, "async_load"):
            try:
                await resources.async_load()
            except Exception:  # noqa: BLE001
                pass
        items = list(resources.async_items()) if hasattr(resources, "async_items") else []
        already = any(
            (getattr(i, "url", None) or (i.get("url") if isinstance(i, dict) else ""))
            == CARD_URL
            for i in items
        )
        if not already:
            await resources.async_create_item({"url": CARD_URL, "res_type": "module"})
            _LOGGER.info("nvidia_gpu: Lovelace resource created for %s", CARD_URL)
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "nvidia_gpu: could not create Lovelace resource; card still loads "
            "via add_extra_js_url"
        )
    return True


async def async_setup_card(hass: HomeAssistant) -> bool:
    """Ship then register the bundled Lovelace card (best-effort)."""
    try:
        await async_ship_card(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("nvidia_gpu: failed to ship card to www/", exc_info=True)
    try:
        return await async_register_card(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("nvidia_gpu: failed to register card", exc_info=True)
        return False
