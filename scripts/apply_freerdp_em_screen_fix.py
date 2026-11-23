#!/usr/bin/env python3
"""Reviewable Emscripten-only SDL3 display fallback for FreeRDP 3.33.1.

The unmodified pinned upstream SDL3 client may get 0x0 from SDL_GetDisplayBounds
despite a nonzero browser screen and canvas. Normal desktop clients are unchanged.
Fail on unexpected upstream source, never silently patch another version.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

SOURCE_COMMIT = "65bcca1913a28cbdd7eb913599f692bd2b707991"
FILE = "client/SDL/SDL3/sdl_window.cpp"

INCLUDE = "#include <freerdp/utils/string.h>\n"
INCLUDE_PATCHED = INCLUDE + """
#if defined(__EMSCRIPTEN__)
#include <emscripten/html5.h>
#endif
"""

BEFORE = """\
	r.w = static_cast<int>(std::roundf(static_cast<float>(r.w) * mode->pixel_density));
	r.h = static_cast<int>(std::roundf(static_cast<float>(r.h) * mode->pixel_density));
	return makeMonitor(id, r, mode->pixel_density * SDL_GetDisplayContentScale(id), forceAsPrimary);
"""

AFTER = """\
	const float density = mode->pixel_density > 0.0f ? mode->pixel_density : 1.0f;
	r.w = static_cast<int>(std::roundf(static_cast<float>(r.w) * density));
	r.h = static_cast<int>(std::roundf(static_cast<float>(r.h) * density));
#if defined(__EMSCRIPTEN__)
	/* A WASM canvas can exist while SDL3 reports display bounds as 0x0.
	 * Use the actual browser screen as a bounded fallback, not a guessed
	 * resolution and never an override on native desktop platforms.
	 * GNOME RDP is still authenticated independently and TLS-pinned.
	 */
	if (r.w <= 0 || r.h <= 0)
	{
		int screenW = 0;
		int screenH = 0;
		if (emscripten_get_screen_size(&screenW, &screenH) == EMSCRIPTEN_RESULT_SUCCESS &&
		    screenW >= 320 && screenW <= 8192 && screenH >= 200 && screenH <= 4320)
		{
			SDL_LogWarn(SDL_LOG_CATEGORY_VIDEO, "Browser SDL3 display fallback: %dx%d",
			            screenW, screenH);
			r.x = 0;
			r.y = 0;
			r.w = screenW;
			r.h = screenH;
		}
	}
#endif
	const float displayScale = SDL_GetDisplayContentScale(id);
	return makeMonitor(id, r, density * (displayScale > 0.0f ? displayScale : 1.0f),
	                   forceAsPrimary);
"""


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_freerdp_em_screen_fix.py UPSTREAM_DIR")
    root = Path(sys.argv[1]).resolve()
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    if head != SOURCE_COMMIT:
        raise SystemExit("STOP: unexpected FreeRDP source commit")
    source = root / FILE
    original = source.read_text(encoding="utf-8")
    if original.count(INCLUDE) != 1 or original.count(BEFORE) != 1:
        raise SystemExit("STOP: upstream SDL3 source context does not match reviewed patch")
    updated = original.replace(INCLUDE, INCLUDE_PATCHED).replace(BEFORE, AFTER)
    source.write_text(updated, encoding="utf-8")
    print("FREERDP_SDL3_EMSCRIPTEN_SCREEN_FALLBACK=APPLIED")
    print("NATIVE_SDL_CLIENTS_CHANGED=False")
    print("PINNED_UPSTREAM_COMMIT_VERIFIED=True")


if __name__ == "__main__":
    main()
