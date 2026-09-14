"""Tests for the PENNY coordinator."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
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

MOCK_EBONS = [
    {
        "id": "ebon-001",
        "timestamp": "2026-09-05T16:00:48Z",
        "totalPrice": 1164,
        "market": {"name": "PENNY", "street": "Musterstr. 1", "zipCode": "12345", "city": "Berlin"},
        "cancelled": False,
    }
]

MOCK_SUBSCRIPTION = {"isSubscribed": True}

MOCK_RECEIPT = {
    "items": [
        {"name": "Pepsi Cola Zero", "price": 8.94, "tax_code": "A", "discount_excluded": False, "quantity": 2, "unit_price": 4.47}
    ],
    "total": 11.64,
    "payment_method": "EC-Karte",
    "payment_amount": 11.64,
    "date": "05.09.2026",
    "time": "18:00",
    "receipt_number": "12345",
    "market_id": "0515",
    "cashier_id": "1",
    "employee_id": "999",
    "savings": 0.30,
    "loyalty_points": 4,
    "store_vat_id": "DE123",
    "tax_breakdown": [{"code": "A", "rate_percent": 19.0, "net": 9.78, "tax": 1.86, "gross": 11.64}],
}


def _make_entry(hass, access_expires_at: float = 9999999999.0):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REWE_ID: "12345678",
            CONF_ACCESS_TOKEN: "fake_access",
            CONF_REFRESH_TOKEN: "fake_refresh",
            CONF_ACCESS_TOKEN_EXPIRES_AT: access_expires_at,
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


async def test_coordinator_fetch_success(hass: HomeAssistant) -> None:
    """Test successful data fetch and storage caching."""
    entry = _make_entry(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)

    mock_client = MagicMock()
    mock_client.fetch_oidc_discovery.return_value = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }
    mock_client.get_all_ebons.return_value = MOCK_EBONS
    mock_client.get_subscription.return_value = MOCK_SUBSCRIPTION
    mock_client.get_ebon_pdf.return_value = b"%PDF fake"
    mock_client.cookies = {}

    with (
        patch("custom_components.penny.coordinator.PennyAPIClient", return_value=mock_client),
        patch("custom_components.penny.coordinator.parse_ebon_pdf", return_value=MOCK_RECEIPT),
        patch("homeassistant.helpers.storage.Store.async_save"),
        patch("asyncio.sleep"),
    ):
        data = await coordinator._async_update_data()

    assert len(data["ebons"]) == 1
    assert data["ebons"][0]["id"] == "ebon-001"
    assert data["subscription"]["isSubscribed"] is True
    assert data["last_receipt"]["total"] == 11.64
    assert data["last_receipt"]["savings"] == 0.30
    assert data["last_receipt"]["loyalty_points"] == 4


async def test_coordinator_backoff_on_failure(hass: HomeAssistant) -> None:
    """Test that consecutive failures trigger backoff."""
    entry = _make_entry(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)
    coordinator._consecutive_failures = 0

    mock_client = MagicMock()
    mock_client.fetch_oidc_discovery.return_value = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }
    mock_client.get_all_ebons.side_effect = RuntimeError("connection error")

    with (
        patch("custom_components.penny.coordinator.PennyAPIClient", return_value=mock_client),
        patch("homeassistant.helpers.storage.Store.async_save"),
        patch("asyncio.sleep"),
    ):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    assert coordinator._consecutive_failures == 1
    assert coordinator._backoff_until is not None


async def test_coordinator_uses_cache_on_failure(hass: HomeAssistant) -> None:
    """Test that cached data is returned when fetch fails and cache is valid."""
    entry = _make_entry(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)
    from homeassistant.util import dt as dt_util
    coordinator._last_success = dt_util.now()
    coordinator.data = {
        "ebons": MOCK_EBONS,
        "last_receipt": MOCK_RECEIPT,
        "subscription": MOCK_SUBSCRIPTION,
        "product_filter_results": {},
        "rewe_id": "12345678",
    }

    mock_client = MagicMock()
    mock_client.fetch_oidc_discovery.return_value = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }
    mock_client.get_all_ebons.side_effect = RuntimeError("transient error")

    with (
        patch("custom_components.penny.coordinator.PennyAPIClient", return_value=mock_client),
        patch("homeassistant.helpers.storage.Store.async_save"),
        patch("asyncio.sleep"),
    ):
        # Should return cached data, not raise
        result = await coordinator._async_update_data()

    assert result["ebons"] == MOCK_EBONS


async def test_coordinator_token_refresh(hass: HomeAssistant) -> None:
    """Test that expired access token triggers refresh."""
    # Set expires_at to past
    entry = _make_entry(hass, access_expires_at=0.0)
    coordinator = PennyDataUpdateCoordinator(hass, entry)

    mock_client = MagicMock()
    mock_client.fetch_oidc_discovery.return_value = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }
    mock_client.refresh_tokens.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 300,
    }
    mock_client.get_all_ebons.return_value = MOCK_EBONS
    mock_client.get_subscription.return_value = MOCK_SUBSCRIPTION
    mock_client.get_ebon_pdf.return_value = b"%PDF"

    with (
        patch("custom_components.penny.coordinator.PennyAPIClient", return_value=mock_client),
        patch("custom_components.penny.coordinator.parse_ebon_pdf", return_value=MOCK_RECEIPT),
        patch("homeassistant.helpers.storage.Store.async_save"),
        patch("asyncio.sleep"),
    ):
        data = await coordinator._async_update_data()

    mock_client.refresh_tokens.assert_called_once()
    assert coordinator._access_token == "new_access"
    assert data["ebons"][0]["id"] == "ebon-001"


async def test_coordinator_product_filter(hass: HomeAssistant) -> None:
    """Test product filter matching against receipt items."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REWE_ID: "12345678",
            CONF_ACCESS_TOKEN: "tok",
            CONF_REFRESH_TOKEN: "ref",
            CONF_ACCESS_TOKEN_EXPIRES_AT: 9999999999.0,
        },
        options={"product_filters": ["Pepsi"]},
    )
    entry.add_to_hass(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)

    mock_client = MagicMock()
    mock_client.fetch_oidc_discovery.return_value = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }
    mock_client.get_all_ebons.return_value = MOCK_EBONS
    mock_client.get_subscription.return_value = MOCK_SUBSCRIPTION
    mock_client.get_ebon_pdf.return_value = b"%PDF"

    with (
        patch("custom_components.penny.coordinator.PennyAPIClient", return_value=mock_client),
        patch("custom_components.penny.coordinator.parse_ebon_pdf", return_value=MOCK_RECEIPT),
        patch("homeassistant.helpers.storage.Store.async_save"),
        patch("asyncio.sleep"),
    ):
        data = await coordinator._async_update_data()

    assert "Pepsi" in data["product_filter_results"]
    matches = data["product_filter_results"]["Pepsi"]
    assert len(matches) == 1
    assert "Pepsi" in matches[0]["name"]


async def test_coordinator_guest_mode(hass: HomeAssistant) -> None:
    """Test coordinator update when running in unauthenticated guest mode."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_REWE_ID: "penny_guest",
            CONF_ACCESS_TOKEN: "",
            CONF_REFRESH_TOKEN: "",
            CONF_ACCESS_TOKEN_EXPIRES_AT: 0.0,
        },
        options={"product_filters": ["Cola"]},
    )
    entry.add_to_hass(hass)
    coordinator = PennyDataUpdateCoordinator(hass, entry)

    with (
        patch("homeassistant.helpers.storage.Store.async_save"),
        patch("asyncio.sleep"),
    ):
        data = await coordinator._async_update_data()

    assert data["ebons"] == []
    assert data["last_receipt"] == {}
    assert data["subscription"] == {}
    assert data["rewe_id"] == "penny_guest"
    assert "Cola" in data["product_filter_results"]
    assert data["product_filter_results"]["Cola"] == []
