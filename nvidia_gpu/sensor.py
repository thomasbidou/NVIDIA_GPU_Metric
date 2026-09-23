"""Sensor platform for the NVIDIA GPU Stats integration.

Two devices are created from one daemon snapshot:
  - the GPU  (fields at the top level of the JSON)
  - the system/CPU (fields under the "cpu" object: CPU %, CPU temp, RAM)

Each sensor uses the right `device_class` where one exists so Lovelace
`gauge` cards work natively. Percentages are expressed via
`unit_of_measurement=PERCENTAGE` (HA has no percentage device class).
"""
from __future__ import annotations

from typing import Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import NvidiaGpuCoordinator

PARALLEL_UPDATES = 1


# ---- GPU sensors (read from top level of the snapshot) ----
GPU_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="gpu_utilization_pct",
        name="Utilisation",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # ``role`` is a stable, language-neutral handle for the bundled
        # Lovelace card to identify the sensor (independent of display name).
    ),
    SensorEntityDescription(
        key="memory_used_pct",
        name="Mémoire (%)",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_used_gib",
        name="Mémoire (GiB)",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_total_gib",
        name="Mémoire totale",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="power_draw_w",
        name="Consommation",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="power_limit_w",
        name="Plafond",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="power_usage_pct",
        name="Puissance (%)",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature_c",
        name="Température",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="fan_speed_pct",
        name="Ventilateur",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


# ---- System / CPU sensors (read from the "cpu" object) ----
SYSTEM_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="usage_pct",
        name="Utilisation",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature_c",
        name="Température",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ram_used_pct",
        name="RAM (%)",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ram_used_gib",
        name="RAM (GiB)",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ram_total_gib",
        name="RAM totale",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.TOTAL,
    ),
)


def _read(data: Optional[dict], source: tuple, key: str):
    node: object = data
    for part in source:
        if part is None:
            return None
        if isinstance(node, (list, tuple)):
            if not isinstance(part, int) or part < 0 or part >= len(node):
                return None
            node = node[part]
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    if not isinstance(node, dict):
        return None
    return node.get(key)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities) -> None:
    """Set up GPU + system sensor entities from a config entry.

    Identity scheme (collision-safe for multiple GPUs and multiple boxes):
      - GPU sensors    -> unique_id  = "<gpu_uuid>_<key>",   device id (DOMAIN, uuid)
      - system sensors -> unique_id  = "<box>_sys_<key>",    device id (DOMAIN, box)
    Each GPU is its own device (keyed by its uuid), so N GPUs -> N devices.
    """
    coordinator: NvidiaGpuCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}
    box = coordinator.box

    def _display(model: str) -> str:
        # "<model> on <box>" when the box is known — keeps multiple boxes
        # distinguishable in the UI.
        return f"{model} on {box}" if box else model

    # ---- GPUs (one device per card) ----
    gpus = data.get("gpus")
    if not gpus:
        # v1 daemon / no "gpus" list: fall back to the top-level single GPU.
        if any(k in data for k in ("gpu_utilization_pct", "memory_used_pct")):
            gpus = [data]
    else:
        gpus = [g for g in gpus if isinstance(g, dict)]
    if not gpus:
        gpus = [data]

    entities: list[SensorEntity] = []
    for idx, gpu in enumerate(gpus):
        uuid = gpu.get("uuid") or f"gpu{idx}"
        model = gpu.get("name") or "NVIDIA GPU"
        # Disambiguate identical models on one box: "RTX 6000 Ada (1)", "(2)".
        display = _display(model) + (f" ({idx + 1})" if len(gpus) > 1 else "")
        device = DeviceInfo(
            identifiers={(DOMAIN, uuid)},
            name=display,
            manufacturer="NVIDIA",
            model=model,
        )
        # source=("gpus", idx) reads this card's fields from the snapshot.
        entities.extend(
            StatSensor(coordinator, device, desc,
                       source=("gpus", idx) if "gpus" in data else (),
                       unique_id=f"{uuid}_{desc.key}")
            for desc in GPU_SENSORS
        )

    # ---- System (CPU/RAM) device ----
    cpu = data.get("cpu") or {}
    sys_name = cpu.get("name") or "CPU"
    sys_id = box or coordinator.host
    sys_device = DeviceInfo(
        identifiers={(DOMAIN, f"{sys_id}-system")},
        name=_display(sys_name),
        model=sys_name,
    )
    entities.extend(
        StatSensor(coordinator, sys_device, desc, source=("cpu",),
                   unique_id=f"{sys_id}_sys_{desc.key}")
        for desc in SYSTEM_SENSORS
    )

    async_add_entities(entities)


class StatSensor(CoordinatorEntity[NvidiaGpuCoordinator], SensorEntity):
    """A single metric, reading from an (optionally nested) snapshot path."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NvidiaGpuCoordinator,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
        source: tuple[str, ...],
        unique_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        # Set the name as an ENTITY attribute (this HA build ignores the
        # description-level name and translation_key; _attr_name is the
        # proven pattern — cf. other custom integrations on this HA).
        self._attr_name = description.name
        self._source = source
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return _read(self.coordinator.data, self._source, self.entity_description.key)

    @property
    def extra_state_attributes(self):
        # Expose the stable metric key so the bundled Lovelace card can
        # identify each sensor by role (independent of the localized
        # display name). The card groups by device_id first (GPU vs system),
        # then matches on this key, so "temperature_c" means GPU temp on the
        # GPU device and CPU temp on the system device.
        return {"nvidia_gpu_key": self.entity_description.key}
