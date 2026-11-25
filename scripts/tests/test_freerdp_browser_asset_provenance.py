"""Offline negative controls for the hash-locked browser binary. No network."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import diagnose_freerdp_wasm_browser as diag


class TestPinnedBrowserAssets(unittest.TestCase):
    def test_checked_in_corrected_artifact(self):
        diag.validate_pinned_assets(diag.ORIGINAL_ROOT)

    def fixture(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        js = b"known-good-js"
        wasm = b"\x00asmknown-good-wasm"
        fixed = {
            "sdl-freerdp.js": (hashlib.sha256(js).hexdigest(), len(js)),
            "sdl-freerdp.wasm": (hashlib.sha256(wasm).hexdigest(), len(wasm)),
        }
        (root / "sdl-freerdp.js").write_bytes(js)
        (root / "sdl-freerdp.wasm").write_bytes(wasm)
        info = {
            "freerdp_source_commit": diag.SOURCE_COMMIT,
            "freerdp_version": "3.33.1", "emsdk": "6.0.12",
            "files": {n: {"sha256": sha, "bytes": size}
                      for n, (sha, size) in fixed.items()},
        }
        (root / "provenance.json").write_text(json.dumps(info), encoding="utf-8")
        return tmp, root, fixed

    def test_reject_one_byte_mutation(self):
        tmp, root, fixed = self.fixture()
        with tmp, patch.dict(diag.APPROVED_ASSETS, fixed, clear=True):
            diag.validate_pinned_assets(root)
            (root / "sdl-freerdp.js").write_bytes(b"known-bad!-js")
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                diag.validate_pinned_assets(root)

    def test_reject_provenance_substitution(self):
        tmp, root, fixed = self.fixture()
        with tmp, patch.dict(diag.APPROVED_ASSETS, fixed, clear=True):
            p = root / "provenance.json"
            value = json.loads(p.read_text())
            value["emsdk"] = "unapproved"
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError, "provenance"):
                diag.validate_pinned_assets(root)

    def test_reject_symlink_and_missing_asset(self):
        tmp, root, fixed = self.fixture()
        with tmp, patch.dict(diag.APPROVED_ASSETS, fixed, clear=True):
            p = root / "sdl-freerdp.js"
            p.unlink()
            with self.assertRaisesRegex(RuntimeError, "different compiled"):
                diag.validate_pinned_assets(root)
            p.symlink_to(root / "sdl-freerdp.wasm")
            with self.assertRaisesRegex(RuntimeError, "different compiled"):
                diag.validate_pinned_assets(root)


if __name__ == "__main__":
    unittest.main()
