<div align="center">
  <h1>PENNY (for Home Assistant) 🛒</h1>
  <p><strong>A secure, robust Home Assistant integration for PENNY Germany. Fetches purchase history, digital receipts (eBons) and loyalty points with automatic PDF item parsing.</strong></p>

  [![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz)
  [![Downloads (Current release)](https://img.shields.io/github/downloads/FaserF/ha-penny/latest/penny.zip?label=Downloads%20(Current%20release)&style=for-the-badge)](https://github.com/FaserF/ha-penny/releases)
  [![GitHub Release](https://img.shields.io/github/v/release/FaserF/ha-penny?style=for-the-badge)](https://github.com/FaserF/ha-penny/releases)
  [![License](https://img.shields.io/github/license/FaserF/ha-penny?style=for-the-badge)](LICENSE)
</div>

---

## 🧭 Quick Links

| | | | |
| :--- | :--- | :--- | :--- |
| [✨ Features](#-features) | [📦 Installation](#-installation) | [⚙️ Configuration](#️-configuration) | [🛠️ Options](#️-options-flow) |
| [🧑‍💻 Development](#-development) | [💖 Credits](#-credits--acknowledgements) | [📄 License](#-license) | |

---

### 🛒 Supermarket Family & Deals Hub

Check out our full collection of Home Assistant supermarket integrations and the multi-store aggregator:

| Repository | Description |
| :--- | :--- |
| 🏷️ [**Grocery Deals (ha-grocery-deals)**](https://github.com/FaserF/ha-grocery-deals) | **Smart multi-store price comparison hub** |
| 🔴 [**ha-rewe**](https://github.com/FaserF/ha-rewe) | REWE weekly offers, bonus points & discounts |
| 🟡 [**ha-edeka**](https://github.com/FaserF/ha-edeka) | EDEKA weekly offers, discounts & PAYBACK card |
| 🔵 [**ha-lidl**](https://github.com/FaserF/ha-lidl) | Lidl Plus weekly offers, coupons & digital receipts |
| ⚪ [**ha-aldi**](https://github.com/FaserF/ha-aldi) | ALDI Süd & ALDI Nord weekly flyers & brochures |
| 🔴 [**ha-norma**](https://github.com/FaserF/ha-norma) | Norma weekly store discounts & flyer offers |

---

## ✨ Features

- **🏪 Store & Leaflet Discovery (100% Pure REST API)**:
  - **Market Selector**: Search and select any of the 2,120 PENNY stores in Germany via the official `.rest/market` REST endpoint.
  - **Weekly Leaflet & Preview Links**: Exposes direct URLs to the current and upcoming weekly digital brochures (Blätterkatalog).
  - **Store Status & Opening Hours**: Live opening hours, address, and market features.
  - **Dynamic Device Visit URL**: Home Assistant "Visit Device" action links straight to your store's brochure.
  - **Guest / No-Login Mode**: Full store search and brochure links without needing a PENNY account.

- **🧾 Digital Receipts (eBons) Tracking (Official Keycloak OIDC & REST API)**:
  - **eBons Count**: Displays total number of stored digital receipts with detailed metadata (date, total amount, store, status).
  - **Last Receipt**: Total amount of the latest receipt in EUR.
  - **PDF Item Breakdown**: Automatically downloads and parses the latest receipt PDF without OCR, extracting:
    - Purchased item names, quantities, unit prices, and final prices.
    - Deposit (Pfand) recognition.
    - App-price discounts and total savings.
    - Tax breakdown (7% / 19% gross & net).
    - Store details, cashier ID, and receipt number.
  - **Last Receipt Savings**: Total EUR saved on the latest purchase.
  - **Loyalty Points (Treuepunkte)**: Tracks loyalty points earned on the latest receipt.
- **🔍 Custom Receipt Item Filters**:
  - Automatically match specific items in your latest purchase (e.g. `Pepsi`, `Butter`, `Pfand`) and extract their price.
- **📨 eBon Subscription Status**:
  - Binary sensor reflecting your digital receipt opt-in status (`isSubscribed`).
- **🛡️ Rate-Limiting & Anti-Ban Protections**:
  - Domain-wide concurrency lock.
  - Random jitter delay.
  - HA persistent storage cache (restart-resistant).
  - Exponential backoff on rate limits.
- **🎛️ Manual Force Update**:
  - Force Update button entity to trigger an on-demand API refresh.
- **🔍 Diagnostic Downloads**:
  - Full support for Home Assistant UI Diagnostics with tokens and customer IDs automatically redacted.

---

## ℹ️ Architecture & Limitations (Why No Weekly Offer Items?)

> [!NOTE]
> **No Web Scraping Policy & Official API Boundaries:**
> - **Digital Receipts & Account Data:** PENNY provides official, authenticated REST APIs (`api.penny.de`) for eBons, customer accounts, and loyalty points.
> - **Store Catalog:** PENNY provides an official public REST API (`.rest/market`) for all store metadata and brochure links.
> - **Weekly Offer Product Lists:** Unlike REWE (`ha-rewe`) and Lidl (`ha-lidl`), **PENNY does not operate a public REST API providing individual weekly offer product items**. In both the official PENNY mobile app and website, weekly flyers are rendered exclusively through an embedded third-party reader (Blätterkatalog). To maintain high reliability and adhere to a strict **API-only (no web scraping)** design, this integration does not parse third-party brochure markup into individual item sensors.
> - **Multi-Store Aggregators:** Because individual weekly offer items cannot be obtained via an official REST API, PENNY is **not included in `ha-grocery-deals`** weekly price comparisons. For PENNY weekly offers, use the direct digital brochure link provided by the `Weekly Leaflet` sensor.

---

## ❤️ Support This Project

> I maintain this integration in my **free time alongside my regular job**.
>
> **This project is and will always remain 100% free.**
>
> Donations are completely voluntary — but they help me stay motivated and dedicate more time to maintaining open-source tools!

<div align="center">

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor%20on-GitHub-%23EA4AAA?style=for-the-badge&logo=github-sponsors&logoColor=white)](https://github.com/sponsors/FaserF)&nbsp;&nbsp;
[![PayPal](https://img.shields.io/badge/Donate%20via-PayPal-%2300457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/FaserF)

</div>

---

## 📦 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Click on the three dots in the top right corner and select **Custom repositories**.
3. Add `FaserF/ha-penny` with category **Integration**.
4. Search for "PENNY".
5. Install and restart Home Assistant.

[![Open HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FaserF&repository=ha-penny&category=integration)

### Manual Installation

1. Download the latest release zip file (`penny.zip`).
2. Extract the `custom_components/penny` folder into your Home Assistant's `custom_components` directory.
3. Restart Home Assistant.

---

## ⚙️ Configuration

1. In Home Assistant, go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **PENNY**.
3. Open the displayed login URL in your browser and log in to your PENNY account.
4. Copy the URL from your browser's address bar after login and paste it into the setup step.

---

## 🛠️ Options Flow

- **Update Interval**: Adjust polling interval (1–24 hours).
- **Receipt Item Filters**: Add custom keywords to track specific products in your receipts.
- **Re-authenticate**: Refresh or re-link your PENNY account at any time.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
