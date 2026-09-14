"""Tests for PENNY config flow."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.penny.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


SAMPLE_STORE_DATA = {
    "wwIdent": "530027",
    "marketName": "Penny Hasporter Damm",
    "streetWithHouseNumber": "Hasporter Damm 110-114",
    "zipCode": "27749",
    "city": "Delmenhorst",
    "state": "Niedersachsen",
    "sellingRegion": "15A-08-26",
    "nextWeekSellingRegion": "",
    "flippingBookURL": "https://penny-publish.blaetterkatalog.de/frontend/getcatalog.do?catalogId=1378197",
    "nextWeekFlippingBookURL": "",
    "openingSentence": "Mo.-Sa.: 07:00 bis 22:00 Uhr",
    "image": "https://cdn.penny.de/dam/img.jpg",
}


async def test_config_flow_guest_mode(hass: HomeAssistant) -> None:
    """Test setting up PENNY store without account login (guest mode)."""
    from custom_components.penny.api import Store

    sample_store = Store(SAMPLE_STORE_DATA)

    with patch("custom_components.penny.config_flow.PennyAPIClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.search_markets.return_value = [sample_store]
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"search_query": "Delmenhorst", "login_to_account": False},
        )
        assert result2["type"] == "form"
        assert result2["step_id"] == "select_store"

        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input={"store_key": "530027"},
        )
        assert result3["type"] == "create_entry"
        assert "Delmenhorst" in result3["title"]
        assert result3["data"]["store_key"] == "530027"
        assert result3["data"]["rewe_id"] == "penny_store_530027"


async def test_config_flow_oauth_step_shows_form(hass: HomeAssistant) -> None:
    """Test that choosing login renders the OAuth step with auth_url placeholder."""
    from custom_components.penny.api import Store

    sample_store = Store(SAMPLE_STORE_DATA)

    mock_discovery = {
        "authorization_endpoint": "https://account.penny.de/realms/penny/protocol/openid-connect/auth",
        "token_endpoint": "https://account.penny.de/realms/penny/protocol/openid-connect/token",
    }
    with patch("custom_components.penny.config_flow.PennyAPIClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.search_markets.return_value = [sample_store]
        mock_client.fetch_oidc_discovery.return_value = mock_discovery
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"search_query": "Delmenhorst", "login_to_account": True},
        )
        assert result2["step_id"] == "select_store"

        result_oauth = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input={"store_key": "530027"},
        )

    assert result_oauth["type"] == "form"
    assert result_oauth["step_id"] == "oauth"
    placeholders = result_oauth.get("description_placeholders") or {}
    assert "auth_url" in placeholders
    auth_url = placeholders["auth_url"]
    assert "pennyandroid" in auth_url
    assert "code_challenge" in auth_url


async def test_config_flow_bare_code(hass: HomeAssistant) -> None:
    """Test that a bare code (no full URL) is accepted with store selection."""
    import base64
    import json

    from custom_components.penny.api import Store

    sample_store = Store(SAMPLE_STORE_DATA)

    payload = {"rewe_id": "11223344", "sub": "x"}
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    fake_access = f"hdr.{payload_b64}.sig"

    mock_discovery = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }

    with patch("custom_components.penny.config_flow.PennyAPIClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.search_markets.return_value = [sample_store]
        mock_client.fetch_oidc_discovery.return_value = mock_discovery
        mock_client.exchange_code_for_tokens.return_value = {
            "access_token": fake_access,
            "refresh_token": "r",
            "expires_in": 300,
        }
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"search_query": "Delmenhorst", "login_to_account": True},
        )
        result_oauth = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input={"store_key": "530027"},
        )
        assert result_oauth["step_id"] == "oauth"

        result3 = await hass.config_entries.flow.async_configure(
            result_oauth["flow_id"],
            user_input={"redirect_url_or_code": "BARE_CODE_NO_URL"},
        )
    assert result3["type"] == "create_entry"
    assert result3["data"]["rewe_id"] == "11223344"
    assert result3["data"]["store_key"] == "530027"


async def test_config_flow_invalid_code(hass: HomeAssistant) -> None:
    """Test that invalid input (URL with no code) shows an error."""
    from custom_components.penny.api import Store

    sample_store = Store(SAMPLE_STORE_DATA)

    mock_discovery = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }

    with patch("custom_components.penny.config_flow.PennyAPIClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.search_markets.return_value = [sample_store]
        mock_client.fetch_oidc_discovery.return_value = mock_discovery
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"search_query": "Delmenhorst", "login_to_account": True},
        )
        result_oauth = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input={"store_key": "530027"},
        )
        assert result_oauth["step_id"] == "oauth"

        result3 = await hass.config_entries.flow.async_configure(
            result_oauth["flow_id"],
            user_input={
                "redirect_url_or_code": "https://www.penny.de/app/login?error=access_denied"
            },
        )
    assert result3["type"] == "form"
    errors = result3.get("errors") or {}
    assert "invalid_code" in errors.get("base", "")


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test the options flow saves interval and filters."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "rewe_id": "12345678",
            "access_token": "tok",
            "refresh_token": "ref",
            "access_token_expires_at": 9999999999.0,
        },
        options={"update_interval": 24, "product_filters": []},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "update_interval": 12,
            "product_filters": ["Pepsi", "Butter"],
            "action": "save",
        },
    )
    assert result2["type"] == "create_entry"
    assert result2["data"]["update_interval"] == 12
    assert "Pepsi" in result2["data"]["product_filters"]
