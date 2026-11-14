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


def early_protection_script(css: str) -> str:
    """Install narrow CMP-only CSS at document creation, without consenting.

    Used by both Chrome's initial navigation and the persistent Browser Guard
    DevTools subscription, including the kiosk timer's subsequent reloads.
    """
    import json

    return f"""(() => {{
  const css = {json.dumps(css)};
  const install = () => {{
    try {{
      if (!document.documentElement) return;
      let style = document.getElementById('clientflow-early-kiosk-protection');
      if (!style) {{
        style = document.createElement('style');
        style.id = 'clientflow-early-kiosk-protection';
        style.textContent = css;
        document.documentElement.appendChild(style);
      }}
    }} catch (_) {{}}
  }};
  install();
  try {{ new MutationObserver(install).observe(document, {{childList:true, subtree:true}}); }} catch (_) {{}}
  try {{ document.addEventListener('readystatechange', install, true); }} catch (_) {{}}
}})();"""
