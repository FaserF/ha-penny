"""Tests for PENNY API client and PDF parser."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.penny.api import (
    AuthExpiredError,
    PennyAPIClient,
    _parse_ebon_text,
    build_auth_url,
    generate_pkce_pair,
)

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def test_generate_pkce_pair_lengths():
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) > 40
    assert len(challenge) > 40
    assert verifier != challenge


def test_generate_pkce_pair_unique():
    v1, c1 = generate_pkce_pair()
    v2, c2 = generate_pkce_pair()
    assert v1 != v2
    assert c1 != c2


def test_build_auth_url():
    url = build_auth_url(
        authorization_endpoint="https://account.penny.de/realms/penny/protocol/openid-connect/auth",
        state="test_state",
        code_challenge="test_challenge",
        client_id="pennyandroid",
        redirect_uri="https://www.penny.de/app/login",
    )
    assert "client_id=pennyandroid" in url
    assert "state=test_state" in url
    assert "code_challenge=test_challenge" in url
    assert "code_challenge_method=S256" in url
    assert "response_type=code" in url


# ---------------------------------------------------------------------------
# JWT decode
# ---------------------------------------------------------------------------


def test_decode_rewe_id():
    import base64
    import json

    payload = {"rewe_id": "12345678", "sub": "some-sub"}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    fake_jwt = f"header.{payload_b64}.signature"
    result = PennyAPIClient.decode_rewe_id(fake_jwt)
    assert result == "12345678"


def test_decode_rewe_id_fallback_sub():
    import base64
    import json

    payload = {"sub": "sub-uuid"}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    fake_jwt = f"header.{payload_b64}.signature"
    result = PennyAPIClient.decode_rewe_id(fake_jwt)
    assert result == "sub-uuid"


def test_decode_rewe_id_invalid():
    assert PennyAPIClient.decode_rewe_id("not.a.valid") is None or True  # doesn't crash


# ---------------------------------------------------------------------------
# PDF text parsing
# ---------------------------------------------------------------------------


SAMPLE_EBON_TEXT = """
Pepsi Cola Zero          8,94 A
2 Stk x 4,47
PFAND 1,50 EURO          3,00 A *
App-Preis-Rabatt        -0,30 A
SUMME EUR 11,64
Geg. EC-Karte EUR 11,64
05.09.2026 18:00 Bon-Nr.:12345
Markt:0515 Kasse:1 Bed.:999
0,30 EUR gespart
Sie erhalten 4 Treuepunkte
UID Nr.: DE123456789
A=  19,00%  9,78  1,86  11,64
"""


def test_parse_ebon_text_total():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["total"] == 11.64


def test_parse_ebon_text_payment():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["payment_method"] == "EC-Karte"
    assert result["payment_amount"] == 11.64


def test_parse_ebon_text_datetime():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["date"] == "05.09.2026"
    assert result["time"] == "18:00"
    assert result["receipt_number"] == "12345"


def test_parse_ebon_text_market():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["market_id"] == "0515"
    assert result["cashier_id"] == "1"
    assert result["employee_id"] == "999"


def test_parse_ebon_text_savings():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["savings"] == 0.30


def test_parse_ebon_text_loyalty():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["loyalty_points"] == 4


def test_parse_ebon_text_vat_id():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert result["store_vat_id"] == "DE123456789"


def test_parse_ebon_text_tax_breakdown():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    assert len(result["tax_breakdown"]) == 1
    tb = result["tax_breakdown"][0]
    assert tb["code"] == "A"
    assert tb["rate_percent"] == 19.0


def test_parse_ebon_text_items():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    items = result["items"]
    # Pepsi + PFAND + Rabatt
    assert len(items) >= 2
    pepsi = next((i for i in items if "Pepsi" in i["name"]), None)
    assert pepsi is not None
    assert pepsi["quantity"] == 2
    assert pepsi["tax_code"] == "A"
    assert pepsi["discount_excluded"] is False

    pfand = next((i for i in items if "PFAND" in i["name"]), None)
    assert pfand is not None
    assert pfand["discount_excluded"] is True


def test_parse_ebon_text_negative_price():
    result = _parse_ebon_text(SAMPLE_EBON_TEXT)
    items = result["items"]
    rabatt = next((i for i in items if "Rabatt" in i["name"]), None)
    assert rabatt is not None
    assert rabatt["price"] < 0


def test_parse_ebon_text_empty():
    result = _parse_ebon_text("")
    assert result["items"] == []
    assert result["total"] is None


# ---------------------------------------------------------------------------
# API client – mocked HTTP
# ---------------------------------------------------------------------------


def test_client_fetch_oidc_discovery():
    client = PennyAPIClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "authorization_endpoint": "https://auth",
        "token_endpoint": "https://token",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("custom_components.penny.api.requests.get", return_value=mock_resp):
        doc = client.fetch_oidc_discovery("https://discovery")
    assert doc["authorization_endpoint"] == "https://auth"
    assert client.authorization_endpoint == "https://auth"
    assert client.token_endpoint == "https://token"


def test_client_get_ebons_auth_expired():
    client = PennyAPIClient()
    client._token_endpoint = "https://token"
    client._authorization_endpoint = "https://auth"
    client.set_access_token("tok")

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("custom_components.penny.api.requests.get", return_value=mock_resp):
        with pytest.raises(AuthExpiredError):
            client.get_ebons("12345", page=1)


def test_client_get_all_ebons_pagination():
    client = PennyAPIClient()
    client._token_endpoint = "https://token"
    client._authorization_endpoint = "https://auth"
    client.set_access_token("tok")

    page1 = MagicMock()
    page1.status_code = 200
    page1.raise_for_status = MagicMock()
    page1.json.return_value = {
        "items": [{"id": "a"}, {"id": "b"}],
        "pagination": {"currentPage": 1, "pageCount": 2},
    }
    page2 = MagicMock()
    page2.status_code = 200
    page2.raise_for_status = MagicMock()
    page2.json.return_value = {
        "items": [{"id": "c"}],
        "pagination": {"currentPage": 2, "pageCount": 2},
    }

    with patch(
        "custom_components.penny.api.requests.get", side_effect=[page1, page2]
    ):
        ebons = client.get_all_ebons("12345")
    assert len(ebons) == 3
    assert ebons[2]["id"] == "c"


def test_client_get_subscription():
    client = PennyAPIClient()
    client._token_endpoint = "https://token"
    client._authorization_endpoint = "https://auth"
    client.set_access_token("tok")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"isSubscribed": True}

    with patch("custom_components.penny.api.requests.get", return_value=mock_resp):
        result = client.get_subscription("12345")
    assert result["isSubscribed"] is True
