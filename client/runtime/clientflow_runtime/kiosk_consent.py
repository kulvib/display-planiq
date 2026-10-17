"""Strict, shared CSS for *recognised* consent-management user interfaces.

The same stylesheet is registered by CDP before navigation and by the periodic
Browser Guard as a fallback.  Never match on generic user-facing text, broadly
named iframes, or container size: those patterns hide legitimate content.

This hides only the UI; it neither records nor implies cookie consent.  Sites
which require non-essential tracking to work need site-specific provisioning.
"""

# Each selector denotes a concrete consent-management UI, not general website
# content. Keep this list conservative and require a regression for additions.
CONSENT_SELECTORS = (
    # Cookie Information / Consent Studio.
    "#coiOverlay",
    "#coiConsentBanner",
    "#coi-banner-wrapper",
    "#coiPage-1",
    "#coiPage-2",
    ".coi-overlay",
    ".coi-banner__wrapper",
    "iframe[src*='policy.app.cookieinformation.com' i]",
    # Cookiebot.
    "#CybotCookiebotDialog",
    "#CybotCookiebotDialogBodyUnderlay",
    "#CookiebotWidget",
    "#CookiebotWidgetUnderlay",
    # Usercentrics.
    "#usercentrics-root",
    "[data-testid='uc-app-container']",
    "[data-testid='uc-overlay']",
    # OneTrust, Didomi, Quantcast.
    "#onetrust-banner-sdk",
    "#onetrust-consent-sdk",
    ".didomi-popup-container",
    ".didomi-consent-popup",
    ".qc-cmp2-container",
    # Cookie Script (vendor-specific).
    ".cookiescript_injected",
)

CONSENT_CSS = ",\n".join(CONSENT_SELECTORS) + " {\n" + (
    "  display: none !important;\n"
    "  visibility: hidden !important;\n"
    "  pointer-events: none !important;\n"
    "  opacity: 0 !important;\n"
) + "}\n"
