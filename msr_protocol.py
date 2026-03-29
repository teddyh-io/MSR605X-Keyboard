"""
MSR605x command protocol layer.

Implements the ESC-based command set over the HID transport.
All commands are prefixed with ESC (0x1B).
"""

import time
import logging
from dataclasses import dataclass

from .hid_transport import HIDTransport, HIDTransportError

log = logging.getLogger(__name__)

ESC = 0x1B

# Commands
CMD_RESET = bytes([ESC, 0x61])          # ESC a — reset device
CMD_READ_ISO = bytes([ESC, 0x72])       # ESC r — ISO read (blocks until swipe)
CMD_READ_RAW = bytes([ESC, 0x6D])       # ESC m — raw read
CMD_COMM_TEST = bytes([ESC, 0x65])      # ESC e — communication test
CMD_FIRMWARE = bytes([ESC, 0x76])       # ESC v — get firmware version
CMD_MODEL = bytes([ESC, 0x74])          # ESC t — get device model
CMD_LED_GREEN = bytes([ESC, 0x83])      # green LED on
CMD_LED_RED = bytes([ESC, 0x85])        # red LED on
CMD_LED_OFF = bytes([ESC, 0x81])        # all LEDs off

# Response markers
TRACK1_MARKER = bytes([ESC, 0x01])
TRACK2_MARKER = bytes([ESC, 0x02])
TRACK3_MARKER = bytes([ESC, 0x03])

# Status codes (byte after trailing ESC in read response)
STATUS_OK = 0x30        # '0'
STATUS_READ_ERR = 0x31  # '1' — read error on one or more tracks
STATUS_CMD_ERR = 0x41   # 'A' — command format error
STATUS_WRITE_ERR = 0x32 # '2' — write/verify error


@dataclass
class TrackData:
    track1: str  # empty string if not present/error
    track2: str
    track3: str
    status: int  # raw status byte
    success: bool


class MSRProtocolError(Exception):
    pass


class MSRProtocol:
    def __init__(self, transport: HIDTransport):
        self.transport = transport

    def reset(self):
        """Reset the device."""
        self.transport.send(CMD_RESET)
        time.sleep(0.1)
        # Drain any pending response
        try:
            self.transport.recv(timeout_ms=500)
        except HIDTransportError:
            pass

    def comm_test(self) -> bool:
        """Send communication test, return True if device responds correctly."""
        self.transport.send(CMD_COMM_TEST)
        resp = self.transport.recv(timeout_ms=2000)
        # Expected response: ESC y (0x1B 0x79)
        return len(resp) >= 2 and resp[0] == ESC and resp[1] == 0x79

    def get_firmware(self) -> str:
        """Query firmware version string."""
        self.transport.send(CMD_FIRMWARE)
        resp = self.transport.recv(timeout_ms=2000)
        if resp and len(resp) > 2 and resp[0] == ESC:
            return resp[2:].decode("ascii", errors="replace").strip("\x00")
        return ""

    def get_model(self) -> str:
        """Query device model string."""
        self.transport.send(CMD_MODEL)
        resp = self.transport.recv(timeout_ms=2000)
        if resp and len(resp) > 2 and resp[0] == ESC:
            return resp[2:].decode("ascii", errors="replace").strip("\x00")
        return ""

    def led_green(self):
        self.transport.send(CMD_LED_GREEN)

    def led_red(self):
        self.transport.send(CMD_LED_RED)

    def led_off(self):
        self.transport.send(CMD_LED_OFF)

    def iso_read(self, timeout_ms: int = 30000) -> TrackData:
        """Enter ISO read mode and wait for a card swipe.

        Blocks until a card is swiped or timeout expires.
        Returns TrackData with parsed track strings.
        """
        self.transport.send(CMD_READ_ISO)
        resp = self.transport.recv(timeout_ms=timeout_ms)

        if not resp:
            return TrackData("", "", "", 0, False)

        return self._parse_iso_response(resp)

    def _parse_iso_response(self, data: bytes) -> TrackData:
        """Parse an ISO read response into TrackData.

        Response format:
          ESC 0x73             — start of read response (ESC s)
          ESC 0x01 [track1]   — track 1 data
          ESC 0x02 [track2]   — track 2 data
          ESC 0x03 [track3]   — track 3 data
          ? 0x1C              — field separator
          ESC [status]        — status byte
        """
        track1 = ""
        track2 = ""
        track3 = ""
        status = STATUS_READ_ERR

        # Find track markers and extract data between them
        t1_start = self._find_marker(data, TRACK1_MARKER)
        t2_start = self._find_marker(data, TRACK2_MARKER)
        t3_start = self._find_marker(data, TRACK3_MARKER)

        if t1_start >= 0 and t2_start >= 0:
            track1 = data[t1_start + 2 : t2_start].decode(
                "ascii", errors="replace"
            )
        if t2_start >= 0 and t3_start >= 0:
            track2 = data[t2_start + 2 : t3_start].decode(
                "ascii", errors="replace"
            )
        if t3_start >= 0:
            # Track 3 goes until we hit the trailing ESC+status
            t3_end = self._find_trailing_status(data, t3_start + 2)
            track3 = data[t3_start + 2 : t3_end].decode(
                "ascii", errors="replace"
            )

        # Extract status byte — last two bytes should be ESC + status
        status = self._extract_status(data)

        return TrackData(
            track1=self._clean_track(track1),
            track2=self._clean_track(track2),
            track3=self._clean_track(track3),
            status=status,
            success=(status == STATUS_OK),
        )

    def _clean_track(self, text: str) -> str:
        """Remove control characters and nulls from track data."""
        # Strip ESC (0x1B), field separator (0x1C), and null bytes
        return "".join(
            c for c in text
            if c not in ("\x00", "\x1b", "\x1c") and (c.isprintable() or c == " ")
        )

    def _find_marker(self, data: bytes, marker: bytes) -> int:
        """Find a 2-byte marker in data, return index or -1."""
        try:
            return data.index(marker)
        except ValueError:
            return -1

    def _find_trailing_status(self, data: bytes, start: int) -> int:
        """Find the position where track 3 data ends (before trailing ESC+status)."""
        # Scan backward from end for ESC byte that isn't part of a track marker
        i = len(data) - 1
        while i >= start:
            if data[i - 1] == ESC and data[i] not in (0x01, 0x02, 0x03):
                return i - 1
            i -= 1
        return len(data)

    def _extract_status(self, data: bytes) -> int:
        """Extract the status byte from the end of the response."""
        # The response ends with ESC + status_byte
        if len(data) >= 2 and data[-2] == ESC:
            return data[-1]
        # Some responses may have trailing nulls
        stripped = data.rstrip(b"\x00")
        if len(stripped) >= 2 and stripped[-2] == ESC:
            return stripped[-1]
        return STATUS_READ_ERR
