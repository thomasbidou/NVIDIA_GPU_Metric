"""Sensor platform for the NVIDIA GPU Stats integration.

One sensor per metric. Each uses the right `device_class` so Lovelace
`gauge` cards work natively — range auto-inferred from the class
(percent 0-100, temperature 0-100, power in W).
"""
from __future__ import annotations

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

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="gpu_utilization_pct",
        translation_key="gpu_utilization",
        device_class=SensorDeviceClass.PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_used_pct",
        translation_key="memory_used_pct",
        device_class=SensorDeviceClass.PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_used_gib",
        translation_key="memory_used_gib",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="memory_total_gib",
        translation_key="memory_total_gib",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="power_draw_w",
        translation_key="power_draw_w",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="power_limit_w",
        translation_key="power_limit_w",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="power_usage_pct",
        translation_key="power_usage_pct",
        device_class=SensorDeviceClass.PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature_c",
        translation_key="temperature_c",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="fan_speed_pct",
        translation_key="fan_speed_pct",
        device_class=SensorDeviceClass.PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities) -> None:
    """Set up the GPU sensor entities from a config entry."""
    coordinator: NvidiaGpuCoordinator = hass.data[DOMAIN][entry.entry_id]
    device_name = coordinator.device_name or "NVIDIA GPU"

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_name)},
        name=device_name,
        manufacturer="NVIDIA",
        model=device_name,
    )

    async_add_entities(
        NvidiaGpuSensor(coordinator, device_name, device_info, desc)
        for desc in SENSOR_TYPES
    )


class NvidiaGpuSensor(CoordinatorEntity[NvidiaGpuCoordinator], SensorEntity):
    """A single GPU metric."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NvidiaGpuCoordinator,
        device_name: str,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{device_name}_{description.key}"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return None
        return data.get(self.entity_description.key)
