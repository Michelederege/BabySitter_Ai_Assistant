"""Which mouse events are the side buttons.

BabySitter polls them. It does not install a hook, so other clicks are
left alone. The setting decides whether a side button starts talk.
"""

from __future__ import annotations


# Virtual-key codes. 0x05 is the first side button, 0x06 is the second.
SIDE_BUTTONS = (0x05, 0x06)
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C


def xbutton_action(wparam: int, mouse_data: int) -> str | None:
    """'down' or 'up' for a side button. None for every other mouse event."""
    which = (int(mouse_data) >> 16) & 0xFFFF
    if which not in {1, 2}:
        return None
    if int(wparam) == WM_XBUTTONDOWN:
        return "down"
    if int(wparam) == WM_XBUTTONUP:
        return "up"
    return None


def side_button_down(states: dict[int, bool]) -> bool:
    """True when either side button is currently held."""
    return any(bool(states.get(button)) for button in SIDE_BUTTONS)
