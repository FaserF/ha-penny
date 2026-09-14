"""Data Update Coordinator for the PENNY integration.

Handles:
- Keycloak token lifecycle (refresh / re-auth detection)
- Paginated eBons fetch
- PDF download + parsing of the latest eBon
- Subscription status fetch
- Anti-ban: jitter, backoff, domain lock, restart-resistance via HA Storage
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import storage
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AuthExpiredError, PennyAPIClient, Store, parse_ebon_pdf
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_PRODUCT_FILTERS,
    CONF_REFRESH_TOKEN,
    CONF_REWE_ID,
    CONF_STORE_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ISSUE_ID_AUTH,
    ISSUE_ID_CONNECTION,
    MIN_UPDATE_INTERVAL,
    PENNY_CLIENT_ID,
    PENNY_OIDC_DISCOVERY,
)

_LOGGER = logging.getLogger(__name__)


class PennyDataUpdateCoordinator(DataUpdateCoordinator):
    """Manage fetching PENNY store data, offers/leaflets, and eBons."""

    config_entry: config_entries.ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
        config = {**entry.data, **entry.options}
        self.store_key: str = str(config.get(CONF_STORE_KEY, ""))
        self.rewe_id: str = str(config.get(CONF_REWE_ID, self.store_key or "penny_guest"))
        self._access_token: str = config.get(CONF_ACCESS_TOKEN, "")
        self._refresh_token: str = config.get(CONF_REFRESH_TOKEN, "")
        self._access_token_expires_at: float = float(
            config.get(CONF_ACCESS_TOKEN_EXPIRES_AT, 0.0)
        )
        self.product_filters: list[str] = config.get(CONF_PRODUCT_FILTERS, [])
        self.config_entry = entry

        # Anti-ban state
        self._backoff_until: datetime | None = None
        self._consecutive_failures: int = 0
        self._last_success: datetime | None = None
        self._issue_created: bool = False
        self._force_update: bool = False

        # HA persistent storage
        storage_key = f"{DOMAIN}_{self.store_key or self.rewe_id}"
        self.store: storage.Store = storage.Store(hass, 1, storage_key)

        interval_hours = max(
            MIN_UPDATE_INTERVAL,
            config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        interval_minutes = interval_hours * 60

        # Construct dynamic configuration URL for device visit link
        store_leaflet = config.get("flipping_book_url")
        if store_leaflet:
            self.configuration_url: str = store_leaflet
        elif self.store_key:
            self.configuration_url = "https://www.penny.de/angebote"
        else:
            self.configuration_url = "https://www.penny.de/"

        _LOGGER.debug(
            "Initializing PENNY coordinator for store_key=%s reweId=%s (interval: %d h)",
            self.store_key,
            self.rewe_id,
            interval_hours,
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"PENNY {entry.title}",
            update_interval=timedelta(minutes=interval_minutes),
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """Return True if user is authenticated with a PENNY account."""
        return (
            bool(self._access_token or self._refresh_token)
            and self.rewe_id != "penny_guest"
            and not self.rewe_id.startswith("penny_store_")
        )

    @property
    def is_data_valid(self) -> bool:
        """Return True when cached data exists and was refreshed today."""
        if not self.data:
            return False
        if self._last_success:
            return (dt_util.now() - self._last_success) < timedelta(hours=25)
        return False

    async def async_load_cache(self) -> None:
        """Load persisted coordinator data (restart-resistance)."""
        cache = await self.store.async_load()
        if not cache:
            _LOGGER.debug("No PENNY cache found for entry %s", self.config_entry.entry_id)
            return

        self.data = cache
        if "last_success" in cache:
            try:
                self._last_success = dt_util.parse_datetime(cache["last_success"])
            except (ValueError, TypeError):
                self._last_success = None
        _LOGGER.debug("Loaded PENNY cache for entry %s", self.config_entry.entry_id)

    # ------------------------------------------------------------------
    # Core update loop
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch new eBon data – called by DataUpdateCoordinator on schedule."""
        _LOGGER.debug(
            "Starting PENNY update for reweId=%s (force=%s)",
            self.rewe_id,
            self._force_update,
        )

        # Backoff guard
        if (
            not self._force_update
            and self._backoff_until
            and dt_util.now() < self._backoff_until
        ):
            _LOGGER.debug(
                "Skipping PENNY update for reweId=%s – backoff until %s",
                self.rewe_id,
                self._backoff_until,
            )
            raise UpdateFailed(
                f"PENNY update blocked by backoff until {self._backoff_until}"
            )

        # Skip if fetched very recently
        if not self._force_update and self._last_success is not None:
            time_since = dt_util.now() - self._last_success
            effective_interval = self.update_interval or timedelta(
                hours=DEFAULT_UPDATE_INTERVAL
            )
            if time_since < (effective_interval - timedelta(minutes=5)):
                _LOGGER.info(
                    "Skipping PENNY update for reweId=%s: last success %d min ago",
                    self.rewe_id,
                    int(time_since.total_seconds() / 60),
                )
                return self.data

        try:
            domain_data = self.hass.data.setdefault(DOMAIN, {})
            fetch_lock: asyncio.Lock = domain_data.setdefault(
                "fetch_lock", asyncio.Lock()
            )

            async with fetch_lock:
                is_first = self._last_success is None
                if not self._force_update and not is_first:
                    jitter = random.uniform(2.0, 15.0)
                    _LOGGER.debug(
                        "PENNY reweId=%s: jitter %.1f s", self.rewe_id, jitter
                    )
                    await asyncio.sleep(jitter)
                self._force_update = False

                async with asyncio.timeout(120):
                    data = await self.hass.async_add_executor_job(
                        self._fetch_sync
                    )

            self._last_success = dt_util.now()
            self._consecutive_failures = 0
            data["last_success"] = self._last_success.isoformat()
            await self.store.async_save(data)

            # Clear any active repair issues
            if self._issue_created:
                ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_CONNECTION)
                self._issue_created = False

            return data

        except Exception as err:
            self._consecutive_failures += 1
            _LOGGER.warning(
                "PENNY reweId=%s: fetch failed (#%d): %s",
                self.rewe_id,
                self._consecutive_failures,
                err,
            )

            if (
                self._last_success
                and (dt_util.now() - self._last_success) > timedelta(hours=24)
                and not self._issue_created
            ):
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    ISSUE_ID_CONNECTION,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="connection_error",
                    learn_more_url="https://github.com/FaserF/ha-penny/issues",
                )
                self._issue_created = True

            # Auth-expired: create repair issue and raise
            if isinstance(err, AuthExpiredError) or "401" in str(err):
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    ISSUE_ID_AUTH,
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="auth_expired",
                    learn_more_url="https://github.com/FaserF/ha-penny/issues",
                )

            err_str = str(err).lower()
            if "403" in err_str or "429" in err_str:
                backoff_hours = min(24, self._consecutive_failures * 2)
                self._backoff_until = dt_util.now() + timedelta(hours=backoff_hours)
                _LOGGER.error(
                    "PENNY reweId=%s: rate-limited. Backing off %d h.",
                    self.rewe_id,
                    backoff_hours,
                )
            else:
                backoff_min = min(240, self._consecutive_failures * 30)
                self._backoff_until = dt_util.now() + timedelta(minutes=backoff_min)

            if self.is_data_valid and self.data:
                _LOGGER.warning(
                    "PENNY reweId=%s: using cached data after fetch error: %s",
                    self.rewe_id,
                    err,
                )
                return self.data

            raise UpdateFailed(
                f"Error fetching PENNY eBons for reweId {self.rewe_id}: {err}"
            ) from err

    # ------------------------------------------------------------------
    # Synchronous fetch (runs in executor thread)
    # ------------------------------------------------------------------

    def _fetch_sync(self) -> dict[str, Any]:
        """Fetch store info, leaflet URLs, and (if logged in) eBons + subscription."""
        client = PennyAPIClient()
        store: Store | None = None
        store_info: dict[str, Any] = {}

        if self.store_key:
            try:
                store = client.get_market_by_id(self.store_key)
                if store:
                    store_info = store.raw_data
                    if store.flipping_book_url:
                        self.configuration_url = store.flipping_book_url
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("PENNY: Store metadata fetch failed for store %s: %s", self.store_key, exc)

        # Unauthenticated / guest mode check
        if not self._access_token and not self._refresh_token:
            _LOGGER.debug(
                "PENNY coordinator for %s running in guest mode (unauthenticated)",
                self.rewe_id,
            )
            return {
                "store": store_info,
                "leaflet_url": store.flipping_book_url if store else "",
                "next_leaflet_url": store.next_week_flipping_book_url if store else "",
                "ebons": [],
                "last_receipt": {},
                "subscription": {},
                "product_filter_results": {
                    pfilter: []
                    for pfilter in self.product_filters
                    if pfilter.strip()
                },
                "rewe_id": self.rewe_id,
                "store_key": self.store_key,
            }

        # Fetch OIDC discovery
        client.fetch_oidc_discovery(PENNY_OIDC_DISCOVERY)

        # Ensure access token is fresh
        access_token = self._get_valid_access_token(client)
        client.set_access_token(access_token)

        # Fetch eBons list
        try:
            ebons = client.get_all_ebons(self.rewe_id)
        except AuthExpiredError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "PENNY: failed to fetch eBons for reweId=%s: %s", self.rewe_id, exc
            )
            raise

        # Fetch subscription status
        try:
            subscription = client.get_subscription(self.rewe_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("PENNY: subscription fetch failed: %s", exc)
            subscription = {}

        # Parse latest non-cancelled eBon PDF
        last_receipt: dict[str, Any] = {}
        if ebons:
            active_ebons = [e for e in ebons if not e.get("cancelled", False)]
            if active_ebons:
                latest = active_ebons[0]
                ebon_id = latest.get("id", "")
                # Enrich last_receipt with eBon-list metadata
                last_receipt = {
                    "ebon_id": ebon_id,
                    "timestamp": latest.get("timestamp"),
                    "total_cents": latest.get("totalPrice"),
                    "total": (latest.get("totalPrice") or 0) / 100,
                    "market": latest.get("market"),
                    "cancelled": latest.get("cancelled", False),
                }
                if ebon_id:
                    try:
                        pdf_bytes = client.get_ebon_pdf(self.rewe_id, ebon_id)
                        parsed = parse_ebon_pdf(pdf_bytes)
                        last_receipt.update(parsed)
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.warning(
                            "PENNY: PDF parse failed for eBon %s: %s", ebon_id, exc
                        )

        # Build product-filter results from last receipt items
        product_filter_results: dict[str, list[dict[str, Any]]] = {}
        all_items: list[dict[str, Any]] = last_receipt.get("items") or []
        for pfilter in self.product_filters:
            clean = pfilter.strip().lower()
            if not clean:
                continue
            terms = clean.split()
            matches = [
                item
                for item in all_items
                if all(t in item.get("name", "").lower() for t in terms)
            ]
            product_filter_results[pfilter.strip()] = matches

        return {
            "store": store_info,
            "leaflet_url": store.flipping_book_url if store else "",
            "next_leaflet_url": store.next_week_flipping_book_url if store else "",
            "ebons": ebons,
            "last_receipt": last_receipt,
            "subscription": subscription,
            "product_filter_results": product_filter_results,
            "rewe_id": self.rewe_id,
            "store_key": self.store_key,
        }

    def _get_valid_access_token(self, client: PennyAPIClient) -> str:
        """Return a valid access token, refreshing if necessary."""
        now = time.time()
        # Refresh 60 s before expiry
        if self._access_token and self._access_token_expires_at > now + 60:
            return self._access_token

        if not self._refresh_token:
            raise AuthExpiredError(
                "No refresh token stored – user must re-authenticate via config flow"
            )

        _LOGGER.debug(
            "PENNY reweId=%s: access token expired, refreshing", self.rewe_id
        )
        try:
            tokens = client.refresh_tokens(self._refresh_token, PENNY_CLIENT_ID)
        except Exception as exc:
            raise AuthExpiredError(
                f"PENNY token refresh failed: {exc}"
            ) from exc

        new_access = tokens.get("access_token", "")
        new_refresh = tokens.get("refresh_token") or self._refresh_token
        expires_in = int(tokens.get("expires_in", 300))

        self._access_token = new_access
        self._refresh_token = new_refresh
        self._access_token_expires_at = time.time() + expires_in

        # Persist updated tokens to config entry safely on the event loop
        new_data = {
            **self.config_entry.data,
            CONF_ACCESS_TOKEN: new_access,
            CONF_REFRESH_TOKEN: new_refresh,
            CONF_ACCESS_TOKEN_EXPIRES_AT: self._access_token_expires_at,
        }
        import functools

        self.hass.loop.call_soon_threadsafe(
            functools.partial(
                self.hass.config_entries.async_update_entry,
                self.config_entry,
                data=new_data,
            )
        )
        _LOGGER.debug("PENNY reweId=%s: token refreshed successfully", self.rewe_id)
        return new_access
