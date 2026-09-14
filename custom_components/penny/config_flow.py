"""Config flow for PENNY integration.

Setup steps:
  1. async_step_user   – generates PKCE pair + state, shows auth URL to user
  2. async_step_oauth_code – user pastes the redirect URL (or just the code)
                             → exchange code for tokens → create entry

Options flow:
  - Update interval
  - Product filters
  - Re-authenticate (re-run OAuth flow)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import (
    PennyAPIClient,
    Store,
    build_auth_url,
    decode_rewe_id,
    generate_pkce_pair,
)
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
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    PENNY_CLIENT_ID,
    PENNY_OIDC_DISCOVERY,
    PENNY_REDIRECT_URI,
)

_LOGGER = logging.getLogger(__name__)


class PennyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PENNY Weekly Offers & eBons."""

    VERSION = 1

    def __init__(self) -> None:
        self._search_results: list[Store] = []
        self._selected_store: Store | None = None
        self._login_requested: bool = False
        self._selected_entry_data: dict[str, Any] = {}
        self._selected_title: str = ""
        self._pkce_verifier: str = ""
        self._pkce_challenge: str = ""
        self._oauth_state: str = ""
        self._auth_url: str = ""
        self._token_endpoint: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Store search (ZIP / city) and login choice."""
        errors: dict[str, str] = {}

        if user_input is not None:
            query = user_input.get("search_query", "").strip()
            self._login_requested = bool(user_input.get("login_to_account", False))

            try:
                client = PennyAPIClient()
                results = await self.hass.async_add_executor_job(
                    client.search_markets, query
                )
                if not results:
                    errors["base"] = "no_stores_found"
                else:
                    self._search_results = results
                    return await self.async_step_select_store()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("PENNY market search error: %s", exc)
                errors["base"] = "search_failed"

        schema = vol.Schema(
            {
                vol.Required("search_query"): str,
                vol.Optional("login_to_account", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_store(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Select market from search results."""
        errors: dict[str, str] = {}

        if user_input is not None:
            store_key = user_input[CONF_STORE_KEY]
            selected: Store | None = None
            for s in self._search_results:
                if s.store_key == str(store_key):
                    selected = s
                    break

            if selected:
                self._selected_store = selected
                title = selected.title
                entry_data = {
                    CONF_STORE_KEY: selected.store_key,
                    "market_name": selected.name,
                    "street": selected.street,
                    "zip_code": selected.zip_code,
                    "city": selected.city,
                    "state": selected.state,
                    "selling_region": selected.selling_region,
                    "next_week_selling_region": selected.next_week_selling_region,
                    "flipping_book_url": selected.flipping_book_url,
                    "next_week_flipping_book_url": selected.next_week_flipping_book_url,
                    "opening_sentence": selected.opening_hours,
                    "image": selected.image,
                }

                if not self._login_requested:
                    unique_id = f"penny_store_{selected.store_key}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    entry_data[CONF_REWE_ID] = unique_id
                    return self.async_create_entry(title=title, data=entry_data)

                # If login was requested, store selected data and proceed to OAuth step
                self._selected_entry_data = entry_data
                self._selected_title = title
                return await self.async_step_oauth()

            errors["base"] = "no_stores_found"

        options: dict[str, str] = {}
        for s in self._search_results:
            if s.store_key:
                options[s.store_key] = s.label

        if not options:
            return self.async_abort(reason="no_stores_found")

        schema = vol.Schema({vol.Required(CONF_STORE_KEY): vol.In(options)})
        return self.async_show_form(
            step_id="select_store",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Show authorization URL and accept redirect URL or code."""
        errors: dict[str, str] = {}

        # Generate PKCE pair + state on first render
        if not self._pkce_verifier:
            self._pkce_verifier, self._pkce_challenge = await self.hass.async_add_executor_job(
                generate_pkce_pair
            )
            self._oauth_state = uuid.uuid4().hex

            try:
                client = PennyAPIClient()
                discovery = await self.hass.async_add_executor_job(
                    client.fetch_oidc_discovery, PENNY_OIDC_DISCOVERY
                )
                self._token_endpoint = discovery["token_endpoint"]
                self._auth_url = build_auth_url(
                    authorization_endpoint=discovery["authorization_endpoint"],
                    state=self._oauth_state,
                    code_challenge=self._pkce_challenge,
                    client_id=PENNY_CLIENT_ID,
                    redirect_uri=PENNY_REDIRECT_URI,
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("PENNY OIDC discovery failed: %s", exc)
                errors["base"] = "oidc_discovery_failed"

        if user_input is not None and user_input.get("redirect_url_or_code"):
            raw = user_input.get("redirect_url_or_code", "").strip()

            code = _extract_code(raw)
            if not code:
                errors["base"] = "invalid_code"
            else:
                state_ok = True
                if raw.startswith("http"):
                    parsed_state = _extract_param(raw, "state")
                    if parsed_state and parsed_state != self._oauth_state:
                        _LOGGER.warning(
                            "PENNY OAuth state mismatch: expected %s, got %s",
                            self._oauth_state,
                            parsed_state,
                        )
                        errors["base"] = "state_mismatch"
                        state_ok = False

                if state_ok:
                    try:
                        client = PennyAPIClient()
                        await self.hass.async_add_executor_job(
                            client.fetch_oidc_discovery, PENNY_OIDC_DISCOVERY
                        )
                        tokens = await self.hass.async_add_executor_job(
                            client.exchange_code_for_tokens,
                            code,
                            self._pkce_verifier,
                            PENNY_CLIENT_ID,
                            PENNY_REDIRECT_URI,
                        )
                        access_token = tokens.get("access_token", "")
                        refresh_token = tokens.get("refresh_token", "")
                        expires_in = int(tokens.get("expires_in", 300))
                        expires_at = time.time() + expires_in

                        rewe_id = decode_rewe_id(access_token)
                        if not rewe_id:
                            errors["base"] = "cannot_decode_rewe_id"
                        else:
                            await self.async_set_unique_id(rewe_id)
                            self._abort_if_unique_id_configured()

                            entry_data = dict(self._selected_entry_data)
                            entry_data[CONF_REWE_ID] = rewe_id
                            entry_data[CONF_ACCESS_TOKEN] = access_token
                            entry_data[CONF_REFRESH_TOKEN] = refresh_token
                            entry_data[CONF_ACCESS_TOKEN_EXPIRES_AT] = expires_at

                            title = self._selected_title or f"PENNY ({rewe_id})"
                            return self.async_create_entry(
                                title=title,
                                data=entry_data,
                            )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error("PENNY token exchange failed: %s", exc)
                        errors["base"] = "token_exchange_failed"

        schema = vol.Schema(
            {
                vol.Required("redirect_url_or_code"): str,
            }
        )
        return self.async_show_form(
            step_id="oauth",
            data_schema=schema,
            errors=errors,
            description_placeholders={"auth_url": self._auth_url},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PennyOptionsFlowHandler:
        """Return the options flow handler."""
        return PennyOptionsFlowHandler(config_entry)


class PennyOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for PENNY eBons."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry
        # State for re-auth sub-flow
        self._pkce_verifier: str = ""
        self._pkce_challenge: str = ""
        self._oauth_state: str = ""
        self._auth_url: str = ""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Main options screen."""
        if user_input is not None:
            action = user_input.get("action", "save")
            if action == "reauth":
                return await self.async_step_reauth_start()

            raw_filters = user_input.get(CONF_PRODUCT_FILTERS, [])
            if isinstance(raw_filters, str):
                product_filters = [
                    f.strip()
                    for f in raw_filters.replace("\n", ",").split(",")
                    if f.strip()
                ]
            elif isinstance(raw_filters, list):
                product_filters = [str(f).strip() for f in raw_filters if str(f).strip()]
            else:
                product_filters = []

            new_options = dict(self._config_entry.options)
            new_options[CONF_UPDATE_INTERVAL] = int(user_input[CONF_UPDATE_INTERVAL])
            new_options[CONF_PRODUCT_FILTERS] = product_filters
            return self.async_create_entry(title="", data=new_options)

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        current_filters = self._config_entry.options.get(CONF_PRODUCT_FILTERS, [])

        action_choices = {
            "save": "Save settings",
            "reauth": "Re-authenticate PENNY account",
        }

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL,
                        max=MAX_UPDATE_INTERVAL,
                        step=1,
                        unit_of_measurement="hours",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_PRODUCT_FILTERS, default=current_filters
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=current_filters,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("action", default="save"): vol.In(action_choices),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_reauth_start(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the re-auth URL."""
        errors: dict[str, str] = {}
        if not self._pkce_verifier:
            self._pkce_verifier, self._pkce_challenge = (
                await self.hass.async_add_executor_job(generate_pkce_pair)
            )
            self._oauth_state = uuid.uuid4().hex
            try:
                client = PennyAPIClient()
                discovery = await self.hass.async_add_executor_job(
                    client.fetch_oidc_discovery, PENNY_OIDC_DISCOVERY
                )
                from .api import build_auth_url
                self._auth_url = build_auth_url(
                    authorization_endpoint=discovery["authorization_endpoint"],
                    state=self._oauth_state,
                    code_challenge=self._pkce_challenge,
                    client_id=PENNY_CLIENT_ID,
                    redirect_uri=PENNY_REDIRECT_URI,
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("PENNY re-auth OIDC discovery failed: %s", exc)
                errors["base"] = "oidc_discovery_failed"

        if user_input is not None and not errors:
            return await self.async_step_reauth_code()

        schema = vol.Schema({vol.Optional("_placeholder", default=""): str})
        return self.async_show_form(
            step_id="reauth_start",
            data_schema=schema,
            errors=errors,
            description_placeholders={"auth_url": self._auth_url},
        )

    async def async_step_reauth_code(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Accept the new authorization code during re-auth."""
        errors: dict[str, str] = {}
        if user_input is not None:
            raw = user_input.get("redirect_url_or_code", "").strip()
            code = _extract_code(raw)
            if not code:
                errors["base"] = "invalid_code"
            else:
                try:
                    client = PennyAPIClient()
                    await self.hass.async_add_executor_job(
                        client.fetch_oidc_discovery, PENNY_OIDC_DISCOVERY
                    )
                    tokens = await self.hass.async_add_executor_job(
                        client.exchange_code_for_tokens,
                        code,
                        self._pkce_verifier,
                        PENNY_CLIENT_ID,
                        PENNY_REDIRECT_URI,
                    )
                    new_data = {
                        **self._config_entry.data,
                        CONF_ACCESS_TOKEN: tokens.get("access_token", ""),
                        CONF_REFRESH_TOKEN: tokens.get(
                            "refresh_token",
                            self._config_entry.data.get(CONF_REFRESH_TOKEN, ""),
                        ),
                        CONF_ACCESS_TOKEN_EXPIRES_AT: time.time()
                        + int(tokens.get("expires_in", 300)),
                    }
                    self.hass.config_entries.async_update_entry(
                        self._config_entry, data=new_data
                    )
                    return self.async_create_entry(
                        title="", data=self._config_entry.options
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.error("PENNY re-auth token exchange failed: %s", exc)
                    errors["base"] = "token_exchange_failed"

        schema = vol.Schema({vol.Required("redirect_url_or_code"): str})
        return self.async_show_form(
            step_id="reauth_code",
            data_schema=schema,
            errors=errors,
            description_placeholders={"auth_url": self._auth_url},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_code(raw: str) -> str | None:
    """Extract the authorization code from a URL or return raw if it's a bare code."""
    if raw.startswith("http"):
        return _extract_param(raw, "code")
    # Assume bare code (no whitespace, no URL characters)
    if raw and " " not in raw and "?" not in raw:
        return raw
    return None


def _extract_param(url: str, param: str) -> str | None:
    """Extract a query parameter value from a URL string."""
    try:
        parsed = urlparse(url)
        values = parse_qs(parsed.query).get(param, [])
        return values[0] if values else None
    except Exception:  # noqa: BLE001
        return None
