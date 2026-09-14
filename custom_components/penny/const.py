"""Constants for the PENNY integration."""

DOMAIN = "penny"
ATTRIBUTION = "Data provided by PENNY API"
PLATFORMS = ["sensor", "binary_sensor", "button"]

# Configuration keys
CONF_STORE_KEY = "store_key"
CONF_MARKET_NAME = "market_name"
CONF_REWE_ID = "rewe_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN_EXPIRES_AT = "access_token_expires_at"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_PRODUCT_FILTERS = "product_filters"
CONF_PKCE_VERIFIER = "pkce_verifier"
CONF_OAUTH_STATE = "oauth_state"

# Defaults
DEFAULT_UPDATE_INTERVAL = 24  # hours
MIN_UPDATE_INTERVAL = 1  # hours
MAX_UPDATE_INTERVAL = 24  # hours

# PENNY / Keycloak OIDC constants
PENNY_CLIENT_ID = "pennyandroid"
PENNY_REDIRECT_URI = "https://www.penny.de/app/login"
PENNY_OIDC_DISCOVERY = (
    "https://account.penny.de/realms/penny/.well-known/openid-configuration"
)
PENNY_API_BASE = "https://api.penny.de"
PENNY_EBONS_PAGE_SIZE = 20

# Sensor attributes
ATTR_DISCOUNTS = "discounts"
ATTR_DISCOUNT_TITLE = "product"
ATTR_DISCOUNT_PRICE = "price"
ATTR_BASE_PRICE = "base_price"
ATTR_PICTURE = "picture_link"
ATTR_VALID_DATE = "valid_until"
ATTR_VALID_FROM = "valid_from"
ATTR_CATEGORY = "category"
ATTR_LEAFLET_URL = "leaflet_url"
ATTR_NEXT_LEAFLET_URL = "next_week_leaflet_url"

ATTR_EBONS = "ebons"
ATTR_EBON_COUNT = "ebon_count"
ATTR_LAST_RECEIPT_ITEMS = "items"
ATTR_LAST_RECEIPT_DATE = "date"
ATTR_LAST_RECEIPT_TIME = "time"
ATTR_LAST_RECEIPT_TOTAL = "total"
ATTR_LAST_RECEIPT_SAVINGS = "savings"
ATTR_LAST_RECEIPT_LOYALTY_POINTS = "loyalty_points"
ATTR_LAST_RECEIPT_MARKET = "market"
ATTR_LAST_RECEIPT_PAYMENT = "payment_method"
ATTR_LAST_RECEIPT_RECEIPT_NUMBER = "receipt_number"
ATTR_LAST_RECEIPT_TAX_BREAKDOWN = "tax_breakdown"

# Issue IDs
ISSUE_ID_CONNECTION = "connection_error"
ISSUE_ID_AUTH = "auth_expired"
