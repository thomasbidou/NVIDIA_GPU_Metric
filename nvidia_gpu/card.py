"""Ship the bundled Lovelace card into Home Assistant's ``www/`` and register it.

* Everything under ``www/`` in this package ships with the repo. At setup we
  mirror it into ``/homeassistant/www/`` so Lovelace can load the card.
* The registered URL carries a **content-based version query string**
  (``?v=<sha256-prefix>``) — the same technique HACS (``?hacstag=…``),
  Bambu Lab (``?v=0.6.54``) and Album Slideshow (``?v=1.11.0``) use. This
  forces browsers (and the Nabu Casa edge cache) to fetch the real file
  instead of serving a stale cached copy, and the value only changes when
  the file content actually changes (no cache thrash on every HA restart).
* Loading is driven by ``add_extra_js_url`` (primary, proven on this box via
  the lmstudio integration). A Lovelace **resource** entry is also created for
  UI discoverability — additive only, so it can never break the load path.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__package__)

#: Base URL (no query) for the card bundle.
CARD_BASE = "/local/nvidia-gpu-card.js"


# ---------------------------------------------------------------- helpers --
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


def _url_base(url: str) -> str:
    """Strip the query string so ``/x.js?v=1`` and ``/x.js`` compare equal."""
    return urlparse(url or "")._replace(query="").geturl()


def _versioned_url(base: str, content: bytes) -> str:
    """Append ``?v=<12-hex>`` derived from the file content."""
    return f"{base}?v={hashlib.sha256(content).hexdigest()[:12]}"


def _copy_sync(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


# ------------------------------------------------------------- ship -------
def _plan_copies(bundled: Path, root: Path) -> list[Path]:
    """Return the list of bundled files that need to be (re)written."""
    if not bundled.is_dir():
        return []
    written: list[Path] = []
    for src in sorted(p for p in bundled.rglob("*") if p.is_file()):
        dst = root / src.relative_to(bundled)
        if not _same_content(src, dst):
            written.append(dst)
    return written


async def async_ship_card(hass: HomeAssistant) -> list[Path]:
    bundled = _bundled_dir()
    root = _www_root(hass)
    loop = asyncio.get_running_loop()
    written = await loop.run_in_executor(None, _plan_copies, bundled, root)
    if not written:
        return []
    to_write = set(written)
    await loop.run_in_executor(
        None,
        lambda: [
            _copy_sync(src, root / src.relative_to(bundled))
            for src in sorted(p for p in bundled.rglob("*") if p.is_file())
            if (root / src.relative_to(bundled)) in to_write
        ],
    )
    _LOGGER.info("nvidia_gpu: shipped %d card file(s) to %s", len(written), root)
    return written


# ----------------------------------------------------------- register -----
def _versioned_url_for(hass: HomeAssistant) -> str:
    """Versioned URL computed from the shipped file's content on disk."""
    card_file = _www_root(hass) / "nvidia-gpu-card.js"
    if not card_file.exists():
        return CARD_BASE
    return _versioned_url(CARD_BASE, card_file.read_bytes())


async def async_register_card(hass: HomeAssistant) -> bool:
    ok = False
    vurl = await asyncio.get_running_loop().run_in_executor(
        None, _versioned_url_for, hass
    )
    _LOGGER.info("nvidia_gpu: registering card at %s", vurl)

    # --- primary: add_extra_js_url (proven on this HA build) ----------
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, vurl)
        ok = True
        _LOGGER.info("nvidia_gpu: add_extra_js_url → %s", vurl)
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "nvidia_gpu: add_extra_js_url unavailable; relying on resource",
            exc_info=True,
        )

    # --- secondary: lovelace resource (additive only, best-effort) ----
    lovelace_data = hass.data.get("lovelace")
    if lovelace_data is None:
        return ok
    resources = getattr(lovelace_data, "resources", None) or (
        lovelace_data.get("resources") if isinstance(lovelace_data, dict) else None
    )
    if resources is None or not hasattr(resources, "async_create_item"):
        return ok

    base = _url_base(CARD_BASE)
    try:
        if hasattr(resources, "async_load"):
            try:
                await resources.async_load()
            except Exception:  # noqa: BLE001
                pass
        items = list(resources.async_items()) if hasattr(resources, "async_items") else []
        already = any(
            _url_base(
                getattr(i, "url", None)
                or (i.get("url") if isinstance(i, dict) else "")
                or ""
            )
            == base
            for i in items
        )
        if not already:
            await resources.async_create_item({"url": vurl, "res_type": "module"})
            _LOGGER.info("nvidia_gpu: created Lovelace resource %s", vurl)
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
