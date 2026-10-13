from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gtk4_kiosk_gui_disallows_close_and_minimize_with_svg_logo_fallback():
    source = (ROOT / "client/libexec/local-gui").read_text(encoding="utf-8")
    compile(source, "client/libexec/local-gui", "exec")
    assert "titlebar = Gtk.HeaderBar()" in source
    assert "titlebar.set_show_title_buttons(False)" in source
    assert "self.set_titlebar(titlebar)" in source
    assert "self.set_deletable(False)" in source
    assert 'self.connect("close-request", self._keep_open_on_close)' in source
    assert 'BRAND_LOGO_PATH.with_name("planiq-display-logo-primary.svg")' in source
    assert "GdkPixbuf.Pixbuf.new_from_file(str(vector_logo))" in source
    assert "logo_path = BRAND_LOGO_PATH" in source
    assert "Gtk.Picture.new_for_filename(str(logo_path))" in source


def test_minimize_keyboard_shortcut_blocked_for_kiosk_account_only():
    source = (ROOT / "client/runtime/clientflow_runtime/kiosk_session_policy.py").read_text(encoding="utf-8")
    assert '("org.gnome.desktop.wm.keybindings", "minimize", "[]")' in source
    assert 'pwd.getpwnam(KIOSK_USER)' in source
    assert 'runuser' in source.lower() or 'RUNUSER' in source
