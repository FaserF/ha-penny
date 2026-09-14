"""Pure Python client for the PENNY eBon API (Keycloak OIDC + api.penny.de)."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
import urllib.parse
import uuid
from typing import Any

from curl_cffi import requests

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for OAuth2 PKCE/S256."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(
    authorization_endpoint: str,
    state: str,
    code_challenge: str,
    client_id: str,
    redirect_uri: str,
) -> str:
    """Construct the Keycloak authorization URL for the user to open."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return authorization_endpoint + "?" + urllib.parse.urlencode(params)


def decode_rewe_id(access_token: str) -> str | None:
    """Decode the JWT payload and return the reweId claim."""
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return None
        # Add padding
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        import json

        payload: dict[str, Any] = json.loads(payload_bytes)
        rewe_id = payload.get("rewe_id") or payload.get("sub")
        return str(rewe_id) if rewe_id else None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Failed to decode reweId from JWT: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Store Model
# ---------------------------------------------------------------------------


class Store:
    """Represents a PENNY store / market."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.raw_data = data
        self.store_key: str = str(data.get("wwIdent", ""))
        self.name: str = str(data.get("marketName", f"PENNY {self.store_key}"))
        self.street: str = str(data.get("streetWithHouseNumber", ""))
        self.zip_code: str = str(data.get("zipCode", ""))
        self.city: str = str(data.get("city", ""))
        self.state: str = str(data.get("state", ""))
        self.selling_region: str = str(data.get("sellingRegion", ""))
        self.next_week_selling_region: str = str(data.get("nextWeekSellingRegion", ""))
        self.flipping_book_url: str = str(data.get("flippingBookURL", ""))
        self.next_week_flipping_book_url: str = str(
            data.get("nextWeekFlippingBookURL", "")
        )
        self.opening_hours: str = str(data.get("openingSentence", ""))
        self.image: str = str(data.get("image", ""))
        self.latitude: float | None = None
        self.longitude: float | None = None
        try:
            if data.get("latitude"):
                self.latitude = float(data["latitude"])
            if data.get("longitude"):
                self.longitude = float(data["longitude"])
        except (ValueError, TypeError):
            pass

    @property
    def label(self) -> str:
        """Formatted label for dropdown selectors."""
        address_parts = [self.street, f"{self.zip_code} {self.city}".strip()]
        address_str = ", ".join(p for p in address_parts if p)
        return f"{self.name}, {address_str} (ID: {self.store_key})".strip()

    @property
    def title(self) -> str:
        """Friendly title for the config entry."""
        if self.city:
            return (
                f"PENNY {self.city}, {self.street}"
                if self.street
                else f"PENNY {self.city}"
            )
        return self.name or f"PENNY {self.store_key}"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PennyAPIClient:
    """API client for PENNY REST APIs (eBons, Markets & Offers)."""

    decode_rewe_id = staticmethod(decode_rewe_id)

    def __init__(self) -> None:
        """Initialize without tokens; set them via set_tokens()."""
        self._access_token: str | None = None
        self._authorization_endpoint: str | None = None
        self._token_endpoint: str | None = None

    # ------------------------------------------------------------------
    # Markets / Store catalog (public, no auth)
    # ------------------------------------------------------------------

    def fetch_all_markets(self) -> list[Store]:
        """Fetch the full catalogue of PENNY markets from .rest/market."""
        url = "https://www.penny.de/.rest/market"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.penny.de/angebote",
        }
        try:
            session = requests.Session(impersonate="chrome124")
            resp = session.get(url, headers=headers, timeout=25.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return [Store(item) for item in data]
            return []
        except Exception as exc:
            _LOGGER.error("PENNY markets fetch failed: %s", exc)
            raise RuntimeError(f"PENNY markets fetch failed: {exc}") from exc

    def search_markets(self, query: str) -> list[Store]:
        """Search stores by postal code, city, or market name."""
        all_stores = self.fetch_all_markets()
        clean_query = query.strip().casefold()
        if not clean_query:
            return all_stores

        terms = [t for t in clean_query.split() if t]
        matched: list[Store] = []
        for store in all_stores:
            raw_postal = store.zip_code or ""
            postal_collapsed = re.sub(r"[^a-z0-9]+", "", raw_postal.casefold())
            searchable_values = [
                store.store_key,
                store.name,
                store.street,
                store.zip_code,
                store.city,
                store.state,
                postal_collapsed,
            ]
            searchable = " ".join(v for v in searchable_values if v).casefold()
            if all(term in searchable for term in terms):
                matched.append(store)
        return matched

    def get_market_by_id(self, store_key: str) -> Store | None:
        """Find a single store by wwIdent/store_key."""
        all_stores = self.fetch_all_markets()
        for store in all_stores:
            if store.store_key == str(store_key):
                return store
        return None

    # ------------------------------------------------------------------
    # OIDC discovery (public, no auth)
    # ------------------------------------------------------------------

    def fetch_oidc_discovery(self, discovery_url: str) -> dict[str, Any]:
        """Fetch the Keycloak OIDC discovery document."""
        _LOGGER.debug("Fetching OIDC discovery from %s", discovery_url)
        try:
            resp = requests.get(discovery_url, timeout=15.0)
            resp.raise_for_status()
            doc: dict[str, Any] = resp.json()
            self._authorization_endpoint = doc["authorization_endpoint"]
            self._token_endpoint = doc["token_endpoint"]
            _LOGGER.debug(
                "OIDC discovery: auth=%s token=%s",
                self._authorization_endpoint,
                self._token_endpoint,
            )
            return doc
        except Exception as exc:
            raise RuntimeError(f"PENNY OIDC discovery failed: {exc}") from exc

    @property
    def authorization_endpoint(self) -> str:
        if not self._authorization_endpoint:
            raise RuntimeError(
                "OIDC discovery not yet fetched. Call fetch_oidc_discovery() first."
            )
        return self._authorization_endpoint

    @property
    def token_endpoint(self) -> str:
        if not self._token_endpoint:
            raise RuntimeError(
                "OIDC discovery not yet fetched. Call fetch_oidc_discovery() first."
            )
        return self._token_endpoint

    # ------------------------------------------------------------------
    # Token operations
    # ------------------------------------------------------------------

    def exchange_code_for_tokens(
        self,
        code: str,
        code_verifier: str,
        client_id: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange an authorization code for access + refresh tokens."""
        _LOGGER.debug("Exchanging authorization code for tokens")
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        try:
            resp = requests.post(
                self.token_endpoint,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
            resp.raise_for_status()
            tokens: dict[str, Any] = resp.json()
            self._access_token = tokens.get("access_token")
            _LOGGER.debug("Token exchange successful")
            return tokens
        except Exception as exc:
            raise RuntimeError(f"PENNY token exchange failed: {exc}") from exc

    def refresh_tokens(
        self,
        refresh_token: str,
        client_id: str,
    ) -> dict[str, Any]:
        """Obtain a fresh access token via the refresh token grant."""
        _LOGGER.debug("Refreshing PENNY access token")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        try:
            resp = requests.post(
                self.token_endpoint,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
            resp.raise_for_status()
            tokens: dict[str, Any] = resp.json()
            self._access_token = tokens.get("access_token")
            _LOGGER.debug("Token refresh successful")
            return tokens
        except Exception as exc:
            raise RuntimeError(f"PENNY token refresh failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Authenticated API requests
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "correlation-id": str(uuid.uuid4()),
            "Accept": "application/json",
            "Accept-Language": "de-DE,de;q=0.9",
            "User-Agent": "PENNY-App/Android",
        }

    def set_access_token(self, access_token: str) -> None:
        """Update the bearer token used for subsequent requests."""
        self._access_token = access_token

    def get_ebons(
        self, rewe_id: str, page: int = 1, objects_per_page: int = 20
    ) -> dict[str, Any]:
        """Fetch a page of eBons for the given customer."""
        _LOGGER.debug("Fetching eBons page %d for reweId %s", page, rewe_id)
        url = f"{_PENNY_API_BASE}/api/tenants/penny/customers/{rewe_id}/ebons"
        try:
            resp = requests.get(
                url,
                params={"objectsPerPage": objects_per_page, "page": page},
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code == 401:
                raise AuthExpiredError("PENNY access token expired (401)")
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
        except AuthExpiredError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"PENNY eBons fetch failed (page {page}): {exc}"
            ) from exc

    def get_all_ebons(self, rewe_id: str) -> list[dict[str, Any]]:
        """Fetch all eBons across all pages."""
        all_items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.get_ebons(rewe_id, page=page)
            items = data.get("items", [])
            if not items:
                break
            all_items.extend(items)
            pagination = data.get("pagination", {})
            current_page = pagination.get("currentPage", page)
            page_count = pagination.get("pageCount", 1)
            if current_page >= page_count:
                break
            page += 1
        _LOGGER.debug("Fetched %d eBons total for reweId %s", len(all_items), rewe_id)
        return all_items

    def get_ebon_pdf(self, rewe_id: str, ebon_id: str) -> bytes:
        """Download the PDF bytes for a specific eBon."""
        _LOGGER.debug("Fetching eBon PDF for id=%s", ebon_id)
        url = (
            f"{_PENNY_API_BASE}/api/tenants/penny/customers/"
            f"{rewe_id}/ebons/{ebon_id}/pdf"
        )
        try:
            resp = requests.get(
                url,
                headers={**self._headers(), "Accept": "application/pdf"},
                timeout=30.0,
            )
            if resp.status_code == 401:
                raise AuthExpiredError("PENNY access token expired (401)")
            resp.raise_for_status()
            return resp.content
        except AuthExpiredError:
            raise
        except Exception as exc:
            raise RuntimeError(f"PENNY eBon PDF download failed: {exc}") from exc

    def get_subscription(self, rewe_id: str) -> dict[str, Any]:
        """Return the eBon opt-in subscription status."""
        _LOGGER.debug("Fetching eBon subscription for reweId %s", rewe_id)
        url = f"{_PENNY_API_BASE}/api/tenants/penny/customers/{rewe_id}/subscriptions"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=15.0)
            if resp.status_code == 401:
                raise AuthExpiredError("PENNY access token expired (401)")
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
        except AuthExpiredError:
            raise
        except Exception as exc:
            raise RuntimeError(f"PENNY subscription fetch failed: {exc}") from exc


# Module-level constant (avoids circular refs from const.py)
_PENNY_API_BASE = "https://api.penny.de"


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------


def parse_ebon_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    """Extract structured data from a PENNY eBon PDF.

    Uses pypdf for pure-text extraction (no OCR needed).
    Returns a dict with items, total, savings, loyalty_points, etc.
    """
    try:
        import pypdf  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF parsing") from exc

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_ebon_text(text)


def _parse_ebon_text(text: str) -> dict[str, Any]:
    """Parse the plain-text content extracted from a PENNY eBon PDF."""
    lines = text.splitlines()

    items: list[dict[str, Any]] = []
    total: float | None = None
    payment_method: str | None = None
    payment_amount: float | None = None
    date: str | None = None
    receipt_time: str | None = None
    receipt_number: str | None = None
    market_id: str | None = None
    cashier_id: str | None = None
    employee_id: str | None = None
    savings: float | None = None
    loyalty_points: int | None = None
    store_vat_id: str | None = None
    tax_breakdown: list[dict[str, Any]] = []

    # Regex patterns (German decimal comma)
    _price_re = re.compile(
        r"^(.+?)\s{2,}(-?\d{1,3}(?:\.\d{3})*,\d{2})\s+([A-Z])(\s*\*)?$"
    )
    _qty_re = re.compile(r"^(\d+)\s+Stk\s+x\s+(\d{1,3}(?:\.\d{3})*,\d{2})")
    _total_re = re.compile(r"^SUMME\s+EUR\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})")
    _payment_re = re.compile(r"^Geg\.\s+(.+?)\s+EUR\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})")
    _datetime_re = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s+Bon-Nr\.:(\S+)")
    _market_re = re.compile(r"Markt:(\S+)\s+Kasse:(\S+)\s+Bed\.:(\S+)")
    _savings_re = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2})\s+EUR\s+gespart")
    _loyalty_re = re.compile(r"(?:Sie erhalten|Du erh[äa]ltst)\s+(\d+)\s+Treuepunkt")
    _vat_id_re = re.compile(r"UID\s+Nr\.:\s*(\S+)")
    _tax_breakdown_re = re.compile(
        r"^([A-Z])=\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})%\s+"
        r"(-?\d{1,3}(?:\.\d{3})*,\d{2})\s+"
        r"(-?\d{1,3}(?:\.\d{3})*,\d{2})\s+"
        r"(-?\d{1,3}(?:\.\d{3})*,\d{2})"
    )

    def _de_float(s: str) -> float:
        return float(s.replace(".", "").replace(",", "."))

    pending_item: dict[str, Any] | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Quantity line (must follow an item line)
        if pending_item is not None:
            m = _qty_re.match(line)
            if m:
                pending_item["quantity"] = int(m.group(1))
                pending_item["unit_price"] = _de_float(m.group(2))
                items.append(pending_item)
                pending_item = None
                continue
            else:
                items.append(pending_item)
                pending_item = None

        # Total
        m = _total_re.match(line)
        if m:
            total = _de_float(m.group(1))
            continue

        # Payment
        m = _payment_re.match(line)
        if m:
            payment_method = m.group(1).strip()
            payment_amount = _de_float(m.group(2))
            continue

        # Date / time / receipt number
        m = _datetime_re.search(line)
        if m:
            date = m.group(1)
            receipt_time = m.group(2)
            receipt_number = m.group(3)
            continue

        # Market / cashier / employee
        m = _market_re.search(line)
        if m:
            market_id = m.group(1)
            cashier_id = m.group(2)
            employee_id = m.group(3)
            continue

        # Savings
        m = _savings_re.search(line)
        if m:
            savings = _de_float(m.group(1))
            continue

        # Loyalty points
        m = _loyalty_re.search(line)
        if m:
            loyalty_points = int(m.group(1))
            continue

        # VAT ID
        m = _vat_id_re.search(line)
        if m:
            store_vat_id = m.group(1)
            continue

        # Tax breakdown
        m = _tax_breakdown_re.match(line)
        if m:
            tax_breakdown.append(
                {
                    "code": m.group(1),
                    "rate_percent": _de_float(m.group(2)),
                    "net": _de_float(m.group(3)),
                    "tax": _de_float(m.group(4)),
                    "gross": _de_float(m.group(5)),
                }
            )
            continue

        # Article line
        m = _price_re.match(line)
        if m:
            name = m.group(1).strip()
            price = _de_float(m.group(2))
            tax_code = m.group(3)
            discount_excluded = m.group(4) is not None and "*" in m.group(4)
            pending_item = {
                "name": name,
                "price": price,
                "tax_code": tax_code,
                "discount_excluded": discount_excluded,
                "quantity": 1,
                "unit_price": price,
            }

    if pending_item is not None:
        items.append(pending_item)

    return {
        "items": items,
        "total": total,
        "payment_method": payment_method,
        "payment_amount": payment_amount,
        "date": date,
        "time": receipt_time,
        "receipt_number": receipt_number,
        "market_id": market_id,
        "cashier_id": cashier_id,
        "employee_id": employee_id,
        "savings": savings,
        "loyalty_points": loyalty_points,
        "store_vat_id": store_vat_id,
        "tax_breakdown": tax_breakdown,
    }


class AuthExpiredError(Exception):
    """Raised when the PENNY access token has expired and needs refresh."""
