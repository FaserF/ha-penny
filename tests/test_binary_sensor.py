"""Tests for PENNY binary sensor platform."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.penny.binary_sensor import PennyEbonSubscriptionSensor
from custom_components.penny.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_REWE_ID,
    DOMAIN,
)
from custom_components.penny.coordinator import PennyDataUpdateCoordinator

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def _make_coordinator(hass, subscription_data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REWE_ID: "12345678",
            CONF_ACCESS_TOKEN: "tok",
            CONF_REFRESH_TOKEN: "ref",
            CONF_ACCESS_TOKEN_EXPIRES_AT: 9999999999.0,
        },
        options={},
    )
    entry.add_to_hass(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)
    coordinator.data = {
        "ebons": [],
        "last_receipt": {},
        "subscription": subscription_data,
        "product_filter_results": {},
        "rewe_id": "12345678",
    }
    from homeassistant.util import dt as dt_util
    coordinator._last_success = dt_util.now()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def test_subscription_sensor_on(hass: HomeAssistant) -> None:
    coordinator = await _make_coordinator(hass, {"isSubscribed": True})
    sensor = PennyEbonSubscriptionSensor(coordinator)
    assert sensor.is_on is True


async def test_subscription_sensor_off(hass: HomeAssistant) -> None:
    coordinator = await _make_coordinator(hass, {"isSubscribed": False})
    sensor = PennyEbonSubscriptionSensor(coordinator)
    assert sensor.is_on is False


async def test_subscription_sensor_none_data(hass: HomeAssistant) -> None:
    coordinator = await _make_coordinator(hass, {})
    sensor = PennyEbonSubscriptionSensor(coordinator)
    assert sensor.is_on is None


async def test_subscription_sensor_no_coordinator_data(hass: HomeAssistant) -> None:
    coordinator = await _make_coordinator(hass, {})
    coordinator.data = None
    sensor = PennyEbonSubscriptionSensor(coordinator)
    assert sensor.is_on is None
    assert sensor.available is False
