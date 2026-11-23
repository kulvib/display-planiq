#!/usr/bin/env python3
"""Reviewable Emscripten-only SDL3 display fallback for FreeRDP 3.33.1.

The pinned upstream SDL3 Web client can query a dummy 0x0 monitor despite a
nonzero browser screen. Patch only the actual Emscripten SdlWindow::query path;
native desktop clients are unchanged.
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
rdpMonitor SdlWindow::query(SDL_DisplayID id, bool forceAsPrimary)
{
	if (sdl::utils::isWaylandDriver() || sdl::utils::isX11Driver())
		return queryDisplay(id, forceAsPrimary);
"""

AFTER = """\
rdpMonitor SdlWindow::query(SDL_DisplayID id, bool forceAsPrimary)
{
#if defined(__EMSCRIPTEN__)
	/* The SDL3 Emscripten driver can report a dummy window/display of 0x0.
	 * Unlike the native Wayland/X11 queryDisplay path, SDL3 Web runs through
	 * createDummy() -> query(window), so patch the *actual* browser path.
	 * Use the browser's screen dimensions only when bounded and nonzero.
	 */
	int browserWidth = 0;
	int browserHeight = 0;
	emscripten_get_screen_size(&browserWidth, &browserHeight);
	if (browserWidth >= 320 && browserWidth <= 8192 &&
	    browserHeight >= 200 && browserHeight <= 4320)
	{
		const SDL_Rect browserBounds{ 0, 0, browserWidth, browserHeight };
		SDL_LogInfo(SDL_LOG_CATEGORY_VIDEO, "FreeRDP browser monitor: %dx%d",
		            browserWidth, browserHeight);
		return makeMonitor(id, browserBounds, 1.0f, forceAsPrimary);
	}
	SDL_LogError(SDL_LOG_CATEGORY_VIDEO, "Invalid browser monitor dimensions");
	return {};
#endif
	if (sdl::utils::isWaylandDriver() || sdl::utils::isX11Driver())
		return queryDisplay(id, forceAsPrimary);
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
