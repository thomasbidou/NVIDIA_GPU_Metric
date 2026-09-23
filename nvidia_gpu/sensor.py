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
        translation_key="gpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_used_pct",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_used_gib",
        translation_key="memory_used",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_total_gib",
        translation_key="memory_total",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="power_draw_w",
        translation_key="power_draw",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="power_limit_w",
        translation_key="power_limit",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="power_usage_pct",
        translation_key="power_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature_c",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="fan_speed_pct",
        translation_key="fan_speed",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


# ---- System / CPU sensors (read from the "cpu" object) ----
SYSTEM_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="usage_pct",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature_c",
        translation_key="cpu_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ram_used_pct",
        translation_key="ram_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ram_used_gib",
        translation_key="ram_used",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ram_total_gib",
        translation_key="ram_total",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.TOTAL,
    ),
)


def _read(data: Optional[dict], source: tuple[str, ...], key: str):
    node: object = data
    for part in source:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    if not isinstance(node, dict):
        return None
    return node.get(key)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities) -> None:
    """Set up GPU + system sensor entities from a config entry."""
    coordinator: NvidiaGpuCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    entities: list[SensorEntity] = []

    # ---- GPU device ----
    gpu_name = coordinator.device_name or "NVIDIA GPU"
    gpu_device = DeviceInfo(
        identifiers={(DOMAIN, gpu_name)},
        name=gpu_name,
        manufacturer="NVIDIA",
        model=gpu_name,
    )
    entities.extend(
        StatSensor(coordinator, gpu_name, gpu_device, desc, source=())
        for desc in GPU_SENSORS
    )

    # ---- System (CPU/RAM) device ----
    cpu = data.get("cpu") or {}
    sys_name = cpu.get("name") or "CPU"
    sys_device = DeviceInfo(
        identifiers={(DOMAIN, sys_name)},
        name=sys_name,
        model=sys_name,
    )
    entities.extend(
        StatSensor(coordinator, sys_name, sys_device, desc, source=("cpu",))
        for desc in SYSTEM_SENSORS
    )

    async_add_entities(entities)


class StatSensor(CoordinatorEntity[NvidiaGpuCoordinator], SensorEntity):
    """A single metric, reading from an (optionally nested) snapshot path."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NvidiaGpuCoordinator,
        device_name: str,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
        source: tuple[str, ...],
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._source = source
        self._attr_unique_id = f"{device_name}_{description.key}"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return _read(self.coordinator.data, self._source, self.entity_description.key)
