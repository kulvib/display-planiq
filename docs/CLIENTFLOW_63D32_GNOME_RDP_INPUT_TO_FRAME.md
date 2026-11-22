# ClientFlow 63D-32: physical GNOME input-to-frame pilot

Status: Draft replacement of the GTK marker; **Cairo-free CSS implementation not yet physically accepted**.
Physical 63D-32 guarded pilot stopped at GTK missing paint callback; full root RDP rollback and physical preflight passed.
Subsequent GTK-only normal-window diagnostics verified `V1R1M1` (visible / realized / mapped), one GDK monitor and live GLib loop, but not a successful custom draw callback. Physical read-only check confirmed `PYCAIRO_IMPORT=PASS`, `GI_CAIRO_CONVERTER=MISSING`, `PYTHON3_GI_CAIRO_PACKAGE_INSTALLED=False` on Viborg1. This strongly supports an optional PyGObject Cairo bridge failure, but original stderr was discarded so it is not proven as the sole cause.

## Proven prerequisites
- Viborg1 host viborg1-NUC14MNK-B2, client ID 3, active release 1.3.47 / seq-1248.
- 63D-30: Local RDP authentication, persistent firewall & watchdog, temporary RAM-only Keyring alias, verified full rollback.
- 63D-31: Real FreeRDP graphical surface on Xvfb (first X11 graphical change 513 ms). No proven remote click acceptance.
- 63D-32 physical preflight: Wayland socket PASS, GTK4 initialization PASS, GTK4 Wayland display PASS, no system changes.

## Isolation and evidence
- The 63D-32 script pins the previously tested 63D-31 module SHA256. 63D-31 itself pins 63D-29/30 sources and preflight.
- Read-only readiness verifies host, client identity, release, GNOME preflight and GTK4 Wayland connectivity.
- The exercise uses only the vetted 63D-30 guarded stage/start/stop and the 63D-31 bounded lock retry. No backend, Render, database or client release changes.
- A temporary fullscreen GTK4 Wayland window on the actual nonproduction kiosk desktop uses native `Gtk.Box` and `Gtk.CssProvider` red/green classes; its CSS toggles on GTK click callbacks. No `Gtk.DrawingArea.set_draw_func`, `gi.require_foreign('cairo')`, package installation, or external screenshot files are used.
- The GTK-only smoke opens a normal-size CSS window, verifies a mapped surface, its color style initialization, and a `Gtk.Widget.add_tick_callback` frame-clock tick. A frame-clock tick is not proof that an RDP client received a pixel: only the subsequent FreeRDP RGB sample can provide independent remote image evidence.
- A private Xvfb FreeRDP connects only to loopback 127.0.0.1:3389 with pinned TLS fingerprint; credentials sent over stdin, never argv, env or logs. Xvfb TCP listening is disabled.
- Before clicking, the FreeRDP X11 frame must contain a convincingly large matching red marker. The test then sends five left-clicks at the sampled marker location only.
- Each click requires both a monotonic timestamp from the actual GTK callback and the corresponding red/green CSS pixel transition independently observed inside the local X11 FreeRDP display buffer.
- The script reports input-to-GTK ACK and input-to-FreeRDP pixel median/max. Polling and compositor delays are included; NOT equal to production browser end-to-end latency.
- All workers are bounded: GTK window 80 seconds, Xvfb exercise 115 seconds, 63D-30 root RDP watchdog 6 minutes.
- In finally, all GUI processes are stopped; original 63D-30 stop clears RDP, secrets, TLS, Keyring alias and persistent firewall; original physical preflight must PASS.

## Deliberate limits
- The exercise temporarily overlays the actual kiosk desktop. Use only on nonproduction Viborg1.
- No screenshot files, no forwarded images, no production frontend or Livestream access.
- The test does not verify Display frontend relay, browser paint or the earlier approximately 15-second Livestream/HLS delay.
- Draft PR #404 remains unmerged. Physical test allowed only after CI and PostgreSQL smoke are both success for the exact pinned commit and sources.
