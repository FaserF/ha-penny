"""Diagnostics support for PENNY."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {
    "access_token",
    "refresh_token",
    "access_token_expires_at",
    "rewe_id",
    "token",
    "password",
    "api_key",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "coordinator": {
            "consecutive_failures": coordinator._consecutive_failures,
            "last_success": coordinator._last_success.isoformat()
            if coordinator._last_success
            else None,
            "backoff_until": coordinator._backoff_until.isoformat()
            if coordinator._backoff_until
            else None,
            "has_data": coordinator.data is not None,
            "ebons_count": len(coordinator.data.get("ebons", []))
            if coordinator.data
            else 0,
            "has_last_receipt": bool(
                coordinator.data and coordinator.data.get("last_receipt")
            ),
            "subscription": coordinator.data.get("subscription")
            if coordinator.data
            else None,
        },
    }
