"""Root-owned, allowlisted uinput helper for Remote Desktop only."""
from __future__ import annotations

import threading
from collections import deque
import uuid
from typing import Any

from evdev import AbsInfo, UInput, ecodes

from .server import serve_forever
from .socket_activation import activated_socket

_KEY_MAP = {
    "Enter": ecodes.KEY_ENTER,
    "Escape": ecodes.KEY_ESC,
    "Backspace": ecodes.KEY_BACKSPACE,
    "Tab": ecodes.KEY_TAB,
    " ": ecodes.KEY_SPACE,
    "ArrowUp": ecodes.KEY_UP,
    "ArrowDown": ecodes.KEY_DOWN,
    "ArrowLeft": ecodes.KEY_LEFT,
    "ArrowRight": ecodes.KEY_RIGHT,
    "Delete": ecodes.KEY_DELETE,
    "Home": ecodes.KEY_HOME,
    "End": ecodes.KEY_END,
    "PageUp": ecodes.KEY_PAGEUP,
    "PageDown": ecodes.KEY_PAGEDOWN,
    "Insert": ecodes.KEY_INSERT,
    "Control": ecodes.KEY_LEFTCTRL,
    "Alt": ecodes.KEY_LEFTALT,
    "Shift": ecodes.KEY_LEFTSHIFT,
    "Meta": ecodes.KEY_LEFTMETA,
}
for character in "abcdefghijklmnopqrstuvwxyz":
    _KEY_MAP[character] = getattr(ecodes, f"KEY_{character.upper()}")
for digit in "0123456789":
    _KEY_MAP[digit] = getattr(ecodes, f"KEY_{digit}")
for function_number in range(1, 13):
    _KEY_MAP[f"F{function_number}"] = getattr(ecodes, f"KEY_F{function_number}")

_SHIFTED = {
    "A": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_A),
    "B": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_B),
    "C": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_C),
    "D": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_D),
    "E": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_E),
    "F": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_F),
    "G": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_G),
    "H": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_H),
    "I": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_I),
    "J": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_J),
    "K": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_K),
    "L": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_L),
    "M": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_M),
    "N": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_N),
    "O": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_O),
    "P": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_P),
    "Q": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_Q),
    "R": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_R),
    "S": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_S),
    "T": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_T),
    "U": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_U),
    "V": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_V),
    "W": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_W),
    "X": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_X),
    "Y": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_Y),
    "Z": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_Z),
}


class InputDevice:
    def __init__(self) -> None:
        capabilities = {
            ecodes.EV_KEY: sorted(set(_KEY_MAP.values()) | {ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE}),
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(0, 0, 65535, 0, 0, 0)),
                (ecodes.ABS_Y, AbsInfo(0, 0, 65535, 0, 0, 0)),
            ],
            ecodes.EV_REL: [ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
        }
        self.device = UInput(capabilities, name="ClientFlow Remote Desktop", bustype=ecodes.BUS_VIRTUAL)
        self.lock = threading.Lock()
        self.pressed_by_session: dict[str, set[int]] = {}
        self.executed_ids: set[str] = set()
        self.recent_ids: deque[str] = deque()

    def sync(self) -> None:
        self.device.syn()

    def key(self, code: int, value: int) -> None:
        self.device.write(ecodes.EV_KEY, code, value)

    def transition(self, session_id: str, code: int, down: bool) -> None:
        """Track remote-held controls, never release another session's holds."""
        held = self.pressed_by_session.setdefault(session_id, set())
        previously_held = any(code in values for values in self.pressed_by_session.values())
        if down:
            if code not in held:
                held.add(code)
                if not previously_held:
                    self.key(code, 1)
                    self.sync()
        elif code in held:
            held.remove(code)
            if not any(code in values for values in self.pressed_by_session.values()):
                self.key(code, 0)
                self.sync()
        if not held:
            self.pressed_by_session.pop(session_id, None)

    def release_session(self, session_id: str) -> None:
        held = self.pressed_by_session.pop(session_id, set())
        for code in held:
            if not any(code in values for values in self.pressed_by_session.values()):
                self.key(code, 0)
        if held:
            self.sync()

    def remember(self, input_id: str) -> None:
        if not input_id:
            return
        if len(self.recent_ids) >= 2048:
            self.executed_ids.discard(self.recent_ids.popleft())
        self.recent_ids.append(input_id)
        self.executed_ids.add(input_id)

    def click(self, code: int) -> None:
        self.key(code, 1)
        self.sync()
        self.key(code, 0)
        self.sync()

    def type_character(self, character: str) -> None:
        if character in _SHIFTED:
            shift, code = _SHIFTED[character]
            self.key(shift, 1)
            self.key(code, 1)
            self.sync()
            self.key(code, 0)
            self.key(shift, 0)
            self.sync()
            return
        code = _KEY_MAP.get(character)
        if code is None:
            raise ValueError(f"Tegnet kan ikke indtastes sikkert: {character!r}")
        self.click(code)


_DEVICE: InputDevice | None = None
_DEVICE_LOCK = threading.Lock()


def _device() -> InputDevice:
    global _DEVICE
    with _DEVICE_LOCK:
        if _DEVICE is None:
            _DEVICE = InputDevice()
        return _DEVICE


def handle(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "")
    session_id = str(request.get("session_id") or "__legacy__")
    input_id = str(request.get("input_id") or "")
    if session_id != "__legacy__":
        try:
            if str(uuid.UUID(session_id)) != session_id:
                raise ValueError("Ugyldigt session-id")
        except ValueError as exc:
            raise ValueError("Ugyldigt session-id") from exc
    if input_id:
        try:
            if str(uuid.UUID(input_id)) != input_id:
                raise ValueError("Ugyldigt input-id")
        except ValueError as exc:
            raise ValueError("Ugyldigt input-id") from exc
    device = _device()
    with device.lock:
        if action == "release_session":
            if session_id == "__legacy__":
                raise ValueError("Frigivelse kræver session-id")
            device.release_session(session_id)
            return {"accepted": True, "action": action}
        if input_id and input_id in device.executed_ids:
            return {"accepted": True, "action": action, "duplicate": True}
        if action == "mouse":
            event = str(request.get("event") or "move")
            if event == "move":
                x = float(request.get("x", 0))
                y = float(request.get("y", 0))
                if not 0 <= x <= 1 or not 0 <= y <= 1:
                    raise ValueError("Muskoordinater skal være normaliserede")
                device.device.write(ecodes.EV_ABS, ecodes.ABS_X, round(x * 65535))
                device.device.write(ecodes.EV_ABS, ecodes.ABS_Y, round(y * 65535))
                device.sync()
            elif event in {"click", "down", "up"}:
                button = {1: ecodes.BTN_LEFT, 2: ecodes.BTN_MIDDLE, 3: ecodes.BTN_RIGHT}.get(int(request.get("button", 1)))
                if button is None:
                    raise ValueError("Museknappen er ugyldig")
                if event == "click":
                    device.click(button)
                else:
                    device.transition(session_id, button, event == "down")
            elif event == "scroll":
                delta = int(request.get("delta", 0))
                if not -20 <= delta <= 20:
                    raise ValueError("Scrollværdien er for stor")
                device.device.write(ecodes.EV_REL, ecodes.REL_WHEEL, delta)
                device.sync()
            else:
                raise ValueError("Ukendt musehandling")
        elif action == "key":
            key = str(request.get("key") or "")
            code = _KEY_MAP.get(key)
            if code is None:
                raise ValueError("Tasten er ikke tilladt")
            event = str(request.get("event") or "press")
            if event == "press":
                device.click(code)
            elif event in {"down", "up"}:
                device.transition(session_id, code, event == "down")
            else:
                raise ValueError("Ukendt tastehandling")
        else:
            raise ValueError("Inputbroker accepterer kun mouse og key")
        device.remember(input_id)
    return {"accepted": True, "action": action}


def main() -> int:
    serve_forever(activated_socket(), handle, name="clientflow.remote-desktop.input", connection_timeout=15)
    return 0
