"""PENNY sensor platform."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_EBONS,
    ATTR_LAST_RECEIPT_DATE,
    ATTR_LAST_RECEIPT_ITEMS,
    ATTR_LAST_RECEIPT_LOYALTY_POINTS,
    ATTR_LAST_RECEIPT_MARKET,
    ATTR_LAST_RECEIPT_PAYMENT,
    ATTR_LAST_RECEIPT_RECEIPT_NUMBER,
    ATTR_LAST_RECEIPT_SAVINGS,
    ATTR_LAST_RECEIPT_TAX_BREAKDOWN,
    ATTR_LAST_RECEIPT_TIME,
    ATTR_LAST_RECEIPT_TOTAL,
    ATTR_LEAFLET_URL,
    ATTR_NEXT_LEAFLET_URL,
    ATTRIBUTION,
    DOMAIN,
)
from .coordinator import PennyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up PENNY sensors from a config entry."""
    coordinator: PennyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug(
        "Setting up PENNY sensors for store_key=%s reweId=%s (authenticated=%s)",
        coordinator.store_key,
        coordinator.rewe_id,
        coordinator.is_authenticated,
    )

    sensors: list[SensorEntity] = [
        PennyLeafletSensor(coordinator),
        PennyNextLeafletSensor(coordinator),
        PennyStoreStatusSensor(coordinator),
    ]

    # Account-only sensors (eBons, Last Receipt, Savings, Loyalty Points, Receipt Filters)
    if coordinator.is_authenticated:
        sensors.extend(
            [
                PennyEbonsSensor(coordinator),
                PennyLastReceiptSensor(coordinator),
                PennySavingsSensor(coordinator),
                PennyLoyaltyPointsSensor(coordinator),
            ]
        )

        active_slugs: set[str] = set()
        for product_filter in coordinator.product_filters:
            clean = product_filter.strip()
            if clean:
                sensors.append(PennyProductFilterSensor(coordinator, clean))
                slug = re.sub(r"[^a-zA-Z0-9_]+", "_", clean.lower()).strip("_") or "item"
                active_slugs.add(f"penny_{coordinator.rewe_id}_filter_{slug}")

        # Purge stale filter entities
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if (
                ent.domain == "sensor"
                and ent.unique_id.startswith(f"penny_{coordinator.rewe_id}_filter_")
                and ent.unique_id not in active_slugs
            ):
                ent_reg.async_remove(ent.entity_id)
                _LOGGER.debug(
                    "PENNY: removed stale filter entity %s", ent.entity_id
                )

    async_add_entities(sensors, update_before_add=False)


# ---------------------------------------------------------------------------
# Device info helper
# ---------------------------------------------------------------------------


def _device_info(coordinator: PennyDataUpdateCoordinator) -> DeviceInfo:
    dev_id = coordinator.store_key or coordinator.rewe_id
    model_name = "Market & Leaflets" if not coordinator.is_authenticated else "Market & eBon Account"
    return DeviceInfo(
        identifiers={(DOMAIN, dev_id)},
        name=coordinator.config_entry.title,
        manufacturer="PENNY",
        model=model_name,
        configuration_url=coordinator.configuration_url,
    )


# ---------------------------------------------------------------------------
# Store & Leaflet Sensors
# ---------------------------------------------------------------------------


class PennyLeafletSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Current weekly leaflet / flyer (Blätterkatalog) sensor."""

    _attr_icon = "mdi:book-open-page-variant"
    _attr_has_entity_name = True
    _attr_name = "Weekly Leaflet"

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        key = coordinator.store_key or coordinator.rewe_id
        self._attr_unique_id = f"penny_{key}_leaflet"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        url = data.get("leaflet_url")
        return "Available" if url else "Not available"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        store = data.get("store") or {}
        return {
            ATTR_LEAFLET_URL: data.get("leaflet_url"),
            "selling_region": store.get("sellingRegion"),
            "market_name": store.get("marketName"),
            "address": store.get("streetWithHouseNumber"),
            "zip_code": store.get("zipCode"),
            "city": store.get("city"),
            "opening_hours": store.get("openingSentence"),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None


class PennyNextLeafletSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Next week's leaflet / flyer preview sensor."""

    _attr_icon = "mdi:calendar-arrow-right"
    _attr_has_entity_name = True
    _attr_name = "Next Week Leaflet"

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        key = coordinator.store_key or coordinator.rewe_id
        self._attr_unique_id = f"penny_{key}_next_leaflet"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        url = data.get("next_leaflet_url")
        return "Available" if url else "Not available"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        store = data.get("store") or {}
        return {
            ATTR_NEXT_LEAFLET_URL: data.get("next_leaflet_url"),
            "next_week_selling_region": store.get("nextWeekSellingRegion"),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None


class PennyStoreStatusSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Opening hours and status of the selected PENNY market."""

    _attr_icon = "mdi:store-clock"
    _attr_has_entity_name = True
    _attr_name = "Opening Hours"

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        key = coordinator.store_key or coordinator.rewe_id
        self._attr_unique_id = f"penny_{key}_store_status"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data or {}
        store = data.get("store") or {}
        return store.get("openingSentence") or ("Open" if store else "Unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        store = data.get("store") or {}
        return {
            "market_name": store.get("marketName"),
            "street": store.get("streetWithHouseNumber"),
            "zip_code": store.get("zipCode"),
            "city": store.get("city"),
            "state": store.get("state"),
            "self_checkout": store.get("selfCheckoutActive", False),
            "mobile_self_checkout": store.get("mobileSelfCheckoutActive", False),
            "image": store.get("image"),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


class PennyEbonsSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Number of stored eBons (digital receipts)."""

    _attr_icon = "mdi:receipt-text"
    _attr_native_unit_of_measurement = "eBons"
    _attr_has_entity_name = True
    _attr_name = "eBons"
    _unrecorded_attributes = frozenset({ATTR_EBONS})

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_ebons"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("ebons", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        ebons = data.get("ebons", [])
        # Return lightweight summary (id, timestamp, total, market, cancelled)
        summarized = [
            {
                "id": e.get("id"),
                "timestamp": e.get("timestamp"),
                "total": (e.get("totalPrice") or 0) / 100,
                "market": e.get("market"),
                "cancelled": e.get("cancelled", False),
            }
            for e in ebons
        ]
        return {
            ATTR_EBONS: summarized,
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success or self.coordinator.is_data_valid
        ) and self.coordinator.data is not None


class PennyLastReceiptSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Total amount of the latest PENNY receipt."""

    _attr_icon = "mdi:receipt"
    _attr_has_entity_name = True
    _attr_name = "Last Receipt"
    _attr_native_unit_of_measurement = "EUR"
    _unrecorded_attributes = frozenset({ATTR_LAST_RECEIPT_ITEMS})

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_last_receipt"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        receipt = self.coordinator.data.get("last_receipt", {})
        total = receipt.get("total")
        if total is None:
            total_cents = receipt.get("total_cents")
            if total_cents is not None:
                total = total_cents / 100
        return round(total, 2) if total is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {ATTR_ATTRIBUTION: ATTRIBUTION}
        receipt = self.coordinator.data.get("last_receipt", {})
        market = receipt.get("market") or {}
        return {
            ATTR_LAST_RECEIPT_DATE: receipt.get("date"),
            ATTR_LAST_RECEIPT_TIME: receipt.get("time"),
            ATTR_LAST_RECEIPT_TOTAL: receipt.get("total"),
            ATTR_LAST_RECEIPT_ITEMS: receipt.get("items", []),
            ATTR_LAST_RECEIPT_SAVINGS: receipt.get("savings"),
            ATTR_LAST_RECEIPT_LOYALTY_POINTS: receipt.get("loyalty_points"),
            ATTR_LAST_RECEIPT_MARKET: market if isinstance(market, dict) else {},
            ATTR_LAST_RECEIPT_PAYMENT: receipt.get("payment_method"),
            ATTR_LAST_RECEIPT_RECEIPT_NUMBER: receipt.get("receipt_number"),
            ATTR_LAST_RECEIPT_TAX_BREAKDOWN: receipt.get("tax_breakdown", []),
            "ebon_id": receipt.get("ebon_id"),
            "timestamp": receipt.get("timestamp"),
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success or self.coordinator.is_data_valid
        ) and self.coordinator.data is not None


class PennySavingsSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Savings on the latest PENNY receipt."""

    _attr_icon = "mdi:piggy-bank"
    _attr_has_entity_name = True
    _attr_name = "Last Receipt Savings"
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_savings"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        receipt = self.coordinator.data.get("last_receipt", {})
        savings = receipt.get("savings")
        return round(float(savings), 2) if savings is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_ATTRIBUTION: ATTRIBUTION}

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success or self.coordinator.is_data_valid
        ) and self.coordinator.data is not None


class PennyLoyaltyPointsSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Loyalty (Treue) points earned on the latest PENNY receipt."""

    _attr_icon = "mdi:star-circle"
    _attr_has_entity_name = True
    _attr_name = "Last Receipt Loyalty Points"
    _attr_native_unit_of_measurement = "points"

    def __init__(self, coordinator: PennyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_loyalty_points"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        receipt = self.coordinator.data.get("last_receipt", {})
        pts = receipt.get("loyalty_points")
        return int(pts) if pts is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_ATTRIBUTION: ATTRIBUTION}

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success or self.coordinator.is_data_valid
        ) and self.coordinator.data is not None


class PennyProductFilterSensor(
    CoordinatorEntity[PennyDataUpdateCoordinator], SensorEntity
):
    """Finds matching items in PENNY digital receipts."""

    _attr_icon = "mdi:tag-search"
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PennyDataUpdateCoordinator, product_filter: str
    ) -> None:
        super().__init__(coordinator)
        self._product_filter = product_filter
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", product_filter.lower()).strip("_") or "item"
        self._attr_unique_id = f"penny_{coordinator.rewe_id}_filter_{slug}"
        self._attr_name = f"Filter {product_filter}"
        self._attr_device_info = _device_info(coordinator)

    def _get_matches(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        results = self.coordinator.data.get("product_filter_results", {})
        return results.get(self._product_filter, [])

    @property
    def native_value(self) -> str | None:
        matches = self._get_matches()
        if matches:
            price = matches[0].get("price")
            return f"{price:.2f} €" if isinstance(price, float) else "Im Beleg"
        return "Nicht im Beleg"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        matches = self._get_matches()
        active = matches[0] if matches else {}
        return {
            "filter": self._product_filter,
            "in_receipt": len(matches) > 0,
            "match_count": len(matches),
            "best_price": active.get("price"),
            "product_name": active.get("name"),
            "tax_code": active.get("tax_code"),
            "quantity": active.get("quantity"),
            "matches": matches,
            ATTR_ATTRIBUTION: ATTRIBUTION,
        }

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success or self.coordinator.is_data_valid
        ) and self.coordinator.data is not None
