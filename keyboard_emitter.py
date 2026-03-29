"""
Keyboard emitter using macOS Quartz CGEvent API.

Types strings into the currently focused input field by posting
synthetic keyboard events at the HID event tap level.

Requires Accessibility permissions (System Settings > Privacy & Security >
Accessibility).
"""

import time
import subprocess
import logging

from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    kCGHIDEventTap,
)
from ApplicationServices import AXIsProcessTrusted

log = logging.getLogger(__name__)

# Virtual keycode for Return/Enter
VK_RETURN = 0x24


def check_accessibility() -> bool:
    """Return True if this process has Accessibility permissions."""
    return AXIsProcessTrusted()


def request_accessibility():
    """Open System Settings to the Accessibility pane so the user can grant access."""
    subprocess.Popen([
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    ])


def type_string(text: str, inter_key_delay: float = 0.005):
    """Type a string into the currently focused input field.

    Each character is sent as a key-down + key-up pair using
    CGEventKeyboardSetUnicodeString to handle all ASCII and
    extended characters correctly.

    Args:
        text: The string to type.
        inter_key_delay: Seconds to wait between keystrokes (default 5ms).
    """
    for char in text:
        # Key down
        event_down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(event_down, len(char), char)
        CGEventPost(kCGHIDEventTap, event_down)

        # Key up
        event_up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(event_up, len(char), char)
        CGEventPost(kCGHIDEventTap, event_up)

        if inter_key_delay > 0:
            time.sleep(inter_key_delay)


def type_enter():
    """Press the Enter/Return key."""
    event_down = CGEventCreateKeyboardEvent(None, VK_RETURN, True)
    CGEventPost(kCGHIDEventTap, event_down)
    event_up = CGEventCreateKeyboardEvent(None, VK_RETURN, False)
    CGEventPost(kCGHIDEventTap, event_up)


def type_tab():
    """Press the Tab key."""
    VK_TAB = 0x30
    event_down = CGEventCreateKeyboardEvent(None, VK_TAB, True)
    CGEventPost(kCGHIDEventTap, event_down)
    event_up = CGEventCreateKeyboardEvent(None, VK_TAB, False)
    CGEventPost(kCGHIDEventTap, event_up)
