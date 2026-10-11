from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "frontend/public"

# Approved PlanIQ Display v5 bundle. Any asset replacement requires an explicit
# reviewed branding update, never a test bypass or an unreviewed image edit.
APPROVED_SHA256 = {
    "brand/planiq-display/planiq-display-logo.png": "f60fe57eb0b14531770a373ae0a46b7c3d6be83f4192806c95c575a70ddca2d1",
    "brand/planiq-display/planiq-display-logo-on-dark.png": "5d24741cbd7ea4309e975968bf123ca62fd06479065a51645b4e5fc6d4d96deb",
    "brand/planiq-display/planiq-display-logo-mono-dark.png": "8d62a57b0a44449e4e7669e3fbcaf665e8487aa7b30b53aef46b63b12e283315",
    "brand/planiq-display/planiq-display-mark.png": "02034fe26ba42a1037d920d318fede58ce810adedd3e1408e2404a23dcc741ce",
    "brand/planiq-display/planiq-display-mark-on-dark.png": "9b7886454e94cd91c8213deb13de3ddf5f241ea96e0debaf42af1bddd119648e",
    "favicon-16x16.png": "4b76d334855d558f9cab77221db0dc905fd2112a3879cb596ab24fc0293d64ff",
    "favicon-32x32.png": "163963dd6db68202b0f01d4c2a2973fb6c6b33ecf6a1b46fae560af763690217",
    "favicon.ico": "7b72b10239bf9eee4d0db958cf18f6e5d5eb7a9d9bbc0f099a8d3f1631b702ec",
    "apple-touch-icon.png": "f227f426988c137984dcf49e1126f5cba46ebb7fa2d1a88bc736981b12b39293",
    "icon-192.png": "c51e6b56574ebbe2df14ddd9e19f97eb1c30a4a4618bf722391878cb1a6b1101",
    "icon-512.png": "709c2702c665742fc6dfb7a9192915c7e5f4785ae99e7acf38e336f03f1834c8",
    "icon-maskable-192.png": "a1ba02f94beeb0fbc33f5f877ae50da9c9e1309a5e49d831f6973d103afc629e",
    "icon-maskable-512.png": "3c16ddc0a56b77fc69d53b3959d7fffe9ce96a3dfe6605d9380c4aa3df4eb31b",
    "brand/planiq-display/planiq-display-logo-primary.svg": "4fe7e1e9d4d83cc82cab38739bb774450bb5b0365cfc26304b7b9f57205ffb9f",
    "brand/planiq-display/planiq-display-logo-reversed.svg": "e3f8a1a9576d8b8515d040620d4fa09fa6fae10a32adc6ec5ce1cf174893c5f4",
    "brand/planiq-display/planiq-display-logo-white.svg": "94242f678502cb0d3d2d190ac958353632ac21fc01826478ab937815e7316940",
    "brand/planiq-display/planiq-display-logo-mono-navy.svg": "eb0c530912ce203d4a9a2ece579862cb503cdd48a6610e408c530e9bbe671564",
    "brand/planiq-display/planiq-display-mark-primary.svg": "1b5db5b1dca0a4df2742741647e62b444291c2bde9bac091b1eaaf42e58e24b1",
    "brand/planiq-display/planiq-display-mark-reversed.svg": "378a58677e2ac337f15837a9a76961cad74f1db24d1c066493479d9977651bb9",
    "brand/planiq-display/planiq-display-desktop-wallpaper-3840x2160.png": "c7d46f9a2ef78c1379d84fe8177908bac2bd0a20cb77ac423b04e30702a153b5"
}


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert payload[12:16] == b"IHDR"
    return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")


@pytest.mark.parametrize("name,expected", list(APPROVED_SHA256.items()))
def test_approved_v5_asset_integrity(name: str, expected: str) -> None:
    data = (PUBLIC / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected, name
    if name.endswith(".svg"):
        assert b"<svg" in data and b"<image" not in data and b"<foreignObject" not in data


def test_4k_wallpaper_is_not_stretched_full_hd() -> None:
    wallpaper = PUBLIC / "brand/planiq-display/planiq-display-desktop-wallpaper-3840x2160.png"
    assert _png_dimensions(wallpaper) == (3840, 2160)
    common = (ROOT / "client/bootstrap/clientflow_bootstrap_common.py").read_text(encoding="utf-8")
    policy = (ROOT / "client/runtime/clientflow_runtime/kiosk_session_policy.py").read_text(encoding="utf-8")
    for source in (common, policy):
        assert "planiq-display-desktop-wallpaper-3840x2160.png" in source
        assert "'scaled'" in source
        assert "'centered'" not in source[source.index("org.gnome.desktop.background"):]


def test_pwa_manifest_has_approved_any_and_maskable_icons() -> None:
    manifest = json.loads((PUBLIC / "site.webmanifest").read_text(encoding="utf-8"))
    assert {(x["src"],x["sizes"],x["purpose"]) for x in manifest["icons"]} == {
        ("/icon-192.png", "192x192", "any"),
        ("/icon-512.png", "512x512", "any"),
        ("/icon-maskable-192.png", "192x192", "maskable"),
        ("/icon-maskable-512.png", "512x512", "maskable"),
    }


def test_frontend_and_installer_use_approved_v5_paths() -> None:
    brand = (ROOT / "frontend/src/branding.js").read_text(encoding="utf-8")
    assert 'planiq-display-logo-primary.svg' in brand
    assert 'planiq-display-logo-reversed.svg' in brand
    assert 'planiq-display-logo-white.svg' in brand
    assert 'mailLogoPath: "/brand/planiq-display/planiq-display-logo.png"' in brand
    assert (ROOT / "frontend/src/Dashboard.jsx").read_text(encoding="utf-8").count("PRODUCT_BRAND.logo.nav") == 1
    start = (ROOT / "client/bootstrap/usb/01_START_CLIENTFLOW_USB.sh").read_text(encoding="utf-8")
    assert "planiq-display-desktop-wallpaper-3840x2160.png" in start
    assert "planiq-display-mark.png" in start
    assert "planiq-display-logo-on-dark.png" not in start


def test_copyright_footer_is_shared_outside_maintenance_and_routes() -> None:
    entry = (ROOT / "frontend/src/main.jsx").read_text(encoding="utf-8")
    footer = (ROOT / "frontend/src/components/PlanIQFooter.jsx").read_text(encoding="utf-8")
    assert entry.count("<PlanIQFooter />") == 1
    assert entry.index("<PlanIQFooter />") > entry.index("</MaintenanceGate>")
    assert 'component="footer"' in footer
    assert "new Date().getFullYear()" in footer
    assert "Alle rettigheder forbeholdes" in footer
    for screen in ("LoginPage", "ForgotPasswordPage", "ResetPasswordPage"):
        source=(ROOT / f"frontend/src/{screen}.jsx").read_text(encoding="utf-8")
        assert 'minHeight: "calc(100dvh - 40px)"' in source
    # Copyright belongs to the administrative UI, not to customer signage streams.
    assert "PlanIQFooter" not in (ROOT / "frontend/src/pages/adminpages/LivestreamOverview.jsx").read_text(encoding="utf-8")
