"""Tests for PENNY sensor platform."""


import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.penny.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_REWE_ID,
    DOMAIN,
)
from custom_components.penny.coordinator import PennyDataUpdateCoordinator

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MOCK_DATA = {
    "ebons": [
        {
            "id": "ebon-001",
            "timestamp": "2026-09-05T16:00:48Z",
            "totalPrice": 1164,
            "market": {"name": "PENNY", "street": "Musterstr. 1", "zipCode": "12345", "city": "Berlin"},
            "cancelled": False,
        },
        {
            "id": "ebon-002",
            "timestamp": "2026-09-01T12:00:00Z",
            "totalPrice": 550,
            "market": None,
            "cancelled": True,
        },
    ],
    "last_receipt": {
        "ebon_id": "ebon-001",
        "timestamp": "2026-09-05T16:00:48Z",
        "total": 11.64,
        "total_cents": 1164,
        "market": {"name": "PENNY", "street": "Musterstr. 1", "zipCode": "12345", "city": "Berlin"},
        "cancelled": False,
        "items": [
            {"name": "Pepsi Cola Zero", "price": 8.94, "tax_code": "A", "discount_excluded": False, "quantity": 2, "unit_price": 4.47}
        ],
        "savings": 0.30,
        "loyalty_points": 4,
        "date": "05.09.2026",
        "time": "18:00",
        "receipt_number": "12345",
        "payment_method": "EC-Karte",
        "payment_amount": 11.64,
        "tax_breakdown": [{"code": "A", "rate_percent": 19.0, "net": 9.78, "tax": 1.86, "gross": 11.64}],
    },
    "subscription": {"isSubscribed": True},
    "product_filter_results": {
        "Pepsi": [{"name": "Pepsi Cola Zero", "price": 8.94, "tax_code": "A", "quantity": 2, "unit_price": 4.47}]
    },
    "rewe_id": "12345678",
}


async def _setup_coordinator(hass, data=None, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REWE_ID: "12345678",
            CONF_ACCESS_TOKEN: "tok",
            CONF_REFRESH_TOKEN: "ref",
            CONF_ACCESS_TOKEN_EXPIRES_AT: 9999999999.0,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)
    coordinator.data = data or MOCK_DATA
    from homeassistant.util import dt as dt_util
    coordinator._last_success = dt_util.now()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return entry, coordinator


async def test_ebons_sensor_state(hass: HomeAssistant) -> None:
    """EbonsSensor.native_value = number of ebons."""
    from custom_components.penny.sensor import PennyEbonsSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennyEbonsSensor(coordinator)
    assert sensor.native_value == 2


async def test_ebons_sensor_attributes(hass: HomeAssistant) -> None:
    entry, coordinator = await _setup_coordinator(hass)
    from custom_components.penny.sensor import PennyEbonsSensor
    sensor = PennyEbonsSensor(coordinator)
    attrs = sensor.extra_state_attributes
    assert "ebons" in attrs
    assert len(attrs["ebons"]) == 2
    assert attrs["ebons"][0]["id"] == "ebon-001"


async def test_last_receipt_sensor_state(hass: HomeAssistant) -> None:
    """LastReceiptSensor.native_value = total in EUR."""
    from custom_components.penny.sensor import PennyLastReceiptSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennyLastReceiptSensor(coordinator)
    assert sensor.native_value == 11.64


async def test_last_receipt_sensor_attributes(hass: HomeAssistant) -> None:
    from custom_components.penny.sensor import PennyLastReceiptSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennyLastReceiptSensor(coordinator)
    attrs = sensor.extra_state_attributes
    assert attrs["date"] == "05.09.2026"
    assert attrs["savings"] == 0.30
    assert attrs["loyalty_points"] == 4
    assert attrs["payment_method"] == "EC-Karte"
    assert len(attrs["items"]) == 1


async def test_savings_sensor(hass: HomeAssistant) -> None:
    from custom_components.penny.sensor import PennySavingsSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennySavingsSensor(coordinator)
    assert sensor.native_value == 0.30


async def test_loyalty_points_sensor(hass: HomeAssistant) -> None:
    from custom_components.penny.sensor import PennyLoyaltyPointsSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennyLoyaltyPointsSensor(coordinator)
    assert sensor.native_value == 4


async def test_product_filter_sensor_match(hass: HomeAssistant) -> None:
    from custom_components.penny.sensor import PennyProductFilterSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennyProductFilterSensor(coordinator, "Pepsi")
    assert sensor.native_value == "8.94 €"
    attrs = sensor.extra_state_attributes
    assert attrs["in_receipt"] is True
    assert attrs["match_count"] == 1
    assert attrs["best_price"] == 8.94


async def test_product_filter_sensor_no_match(hass: HomeAssistant) -> None:
    from custom_components.penny.sensor import PennyProductFilterSensor
    entry, coordinator = await _setup_coordinator(hass)
    sensor = PennyProductFilterSensor(coordinator, "Butter")
    assert sensor.native_value == "Nicht im Beleg"
    attrs = sensor.extra_state_attributes
    assert attrs["in_receipt"] is False



async def test_sensor_unavailable_when_no_data(hass: HomeAssistant) -> None:
    from custom_components.penny.sensor import PennyLastReceiptSensor
    entry, coordinator = await _setup_coordinator(hass, data=None)
    coordinator.data = None
    sensor = PennyLastReceiptSensor(coordinator)
    assert sensor.native_value is None


async def test_leaflet_and_store_sensors(hass: HomeAssistant) -> None:
    """Test PennyLeafletSensor, PennyNextLeafletSensor, and PennyStoreStatusSensor."""
    from custom_components.penny.sensor import (
        PennyLeafletSensor,
        PennyNextLeafletSensor,
        PennyStoreStatusSensor,
    )

    data_with_store = {
        **MOCK_DATA,
        "store_key": "530027",
        "leaflet_url": "https://penny-publish.blaetterkatalog.de/frontend/getcatalog.do?catalogId=1378197",
        "next_leaflet_url": "https://penny-publish.blaetterkatalog.de/frontend/getcatalog.do?catalogId=1378198",
        "store": {
            "wwIdent": "530027",
            "marketName": "Penny Hasporter Damm",
            "streetWithHouseNumber": "Hasporter Damm 110-114",
            "zipCode": "27749",
            "city": "Delmenhorst",
            "state": "Niedersachsen",
            "sellingRegion": "15A-08-26",
            "nextWeekSellingRegion": "15A-08-26",
            "openingSentence": "Mo.-Sa.: 07:00 bis 22:00 Uhr",
            "selfCheckoutActive": True,
        },
    }

    entry, coordinator = await _setup_coordinator(hass, data=data_with_store)

    leaflet_sensor = PennyLeafletSensor(coordinator)
    assert leaflet_sensor.native_value == "Available"
    assert leaflet_sensor.extra_state_attributes["leaflet_url"] == data_with_store["leaflet_url"]
    assert leaflet_sensor.extra_state_attributes["market_name"] == "Penny Hasporter Damm"

    next_leaflet_sensor = PennyNextLeafletSensor(coordinator)
    assert next_leaflet_sensor.native_value == "Available"
    assert next_leaflet_sensor.extra_state_attributes["next_week_leaflet_url"] == data_with_store["next_leaflet_url"]

    status_sensor = PennyStoreStatusSensor(coordinator)
    assert status_sensor.native_value == "Mo.-Sa.: 07:00 bis 22:00 Uhr"
    assert status_sensor.extra_state_attributes["city"] == "Delmenhorst"
    assert status_sensor.extra_state_attributes["self_checkout"] is True
