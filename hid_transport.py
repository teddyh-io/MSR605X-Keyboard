"""
HID Transport layer for MSR605x.

The MSR605x communicates via 64-byte USB HID reports that wrap the legacy
ESC-based serial protocol. Each report has a 1-byte header followed by up
to 63 bytes of payload.

Header byte layout:
  bit 7  — first packet in a multi-packet sequence
  bit 6  — last packet in a multi-packet sequence
  bits 5-0 — payload byte count (0-63)
"""

import hid
import time
import logging

log = logging.getLogger(__name__)

VID = 0x0801
PID = 0x0003

FIRST_PACKET = 0x80
LAST_PACKET = 0x40
LENGTH_MASK = 0x3F
MAX_PAYLOAD = 63


class HIDTransportError(Exception):
    pass


class HIDTransport:
    def __init__(self):
        self.device = None

    def enumerate(self):
        """Return list of matching MSR605x HID device info dicts."""
        return hid.enumerate(VID, PID)

    def connect(self):
        """Open connection to the MSR605x. Raises HIDTransportError on failure."""
        devices = self.enumerate()
        if not devices:
            raise HIDTransportError(
                f"MSR605x not found (VID={VID:#06x}, PID={PID:#06x})"
            )
        self.device = hid.device()
        try:
            self.device.open(VID, PID)
        except OSError as e:
            self.device = None
            raise HIDTransportError(f"Failed to open MSR605x: {e}") from e
        self.device.set_nonblocking(0)
        log.info("Connected to MSR605x")

    @property
    def connected(self):
        return self.device is not None

    def close(self):
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
            log.info("Disconnected from MSR605x")

    def send(self, payload: bytes):
        """Send a payload wrapped in HID packet framing.

        For payloads ≤63 bytes (all standard MSR commands), this sends a
        single packet with both first and last flags set. Longer payloads
        are split across multiple packets.
        """
        if not self.device:
            raise HIDTransportError("Not connected")

        offset = 0
        total = len(payload)

        while offset < total:
            chunk_len = min(MAX_PAYLOAD, total - offset)
            header = chunk_len & LENGTH_MASK
            if offset == 0:
                header |= FIRST_PACKET
            if offset + chunk_len >= total:
                header |= LAST_PACKET

            # Build 64-byte report: header + chunk + zero-pad
            report = bytes([header]) + payload[offset : offset + chunk_len]
            report = report.ljust(64, b"\x00")

            # Prepend 0x00 report ID for macOS hidapi
            written = self.device.write(b"\x00" + report)
            if written < 0:
                raise HIDTransportError("HID write failed")

            offset += chunk_len

    def recv(self, timeout_ms: int = 10000) -> bytes:
        """Read a complete response, reassembling multi-packet sequences.

        Blocks up to timeout_ms for the first packet, then continues reading
        until the last-packet flag is seen.
        """
        if not self.device:
            raise HIDTransportError("Not connected")

        result = bytearray()
        first_seen = False

        while True:
            data = self.device.read(64, timeout_ms)
            if not data:
                if not first_seen:
                    return b""  # timeout, no data
                raise HIDTransportError("Timeout waiting for continuation packet")

            header = data[0]
            is_first = bool(header & FIRST_PACKET)
            is_last = bool(header & LAST_PACKET)
            length = header & LENGTH_MASK

            if is_first:
                result = bytearray()
                first_seen = True

            if first_seen:
                result.extend(data[1 : 1 + length])

            if is_last and first_seen:
                return bytes(result)

            # After first packet, use shorter timeout for continuations
            timeout_ms = 2000
