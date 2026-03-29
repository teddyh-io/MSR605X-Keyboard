"""
MagSwipe — MSR605x menu bar card reader.

Reads magnetic stripe cards and types the data into the focused input field.
"""

import threading
import queue
import logging
import time
import sys
import os

import rumps

from .hid_transport import HIDTransport, HIDTransportError
from .msr_protocol import MSRProtocol, TrackData
from .keyboard_emitter import (
    check_accessibility,
    request_accessibility,
    type_string,
    type_enter,
)
from .config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

# Queue for passing swipe data from HID thread to main thread
swipe_queue: queue.Queue[TrackData] = queue.Queue()


class MagSwipeApp(rumps.App):
    def __init__(self):
        super().__init__(
            "MagSwipe",
            title="💳",
            quit_button=None,
        )
        self.config = Config.load()
        self.transport = HIDTransport()
        self.protocol = None
        self._reader_thread = None
        self._running = False
        self._connect_lock = threading.Lock()

        # Build menu
        self.status_item = rumps.MenuItem("Not Connected", callback=None)
        self.status_item.set_callback(None)

        self.swipe_status = rumps.MenuItem("Idle", callback=None)
        self.swipe_status.set_callback(None)

        self.reconnect_item = rumps.MenuItem("Reconnect", callback=self.on_reconnect)

        # Track toggles
        self.track1_item = rumps.MenuItem("Track 1", callback=self.on_toggle_track1)
        self.track1_item.state = self.config.track1_enabled

        self.track2_item = rumps.MenuItem("Track 2", callback=self.on_toggle_track2)
        self.track2_item.state = self.config.track2_enabled

        self.track3_item = rumps.MenuItem("Track 3", callback=self.on_toggle_track3)
        self.track3_item.state = self.config.track3_enabled

        # Separator submenu
        self.sep_tab = rumps.MenuItem("Tab", callback=lambda _: self._set_sep("tab"))
        self.sep_newline = rumps.MenuItem("Newline", callback=lambda _: self._set_sep("newline"))
        self.sep_pipe = rumps.MenuItem("Pipe", callback=lambda _: self._set_sep("pipe"))
        self.sep_none = rumps.MenuItem("None", callback=lambda _: self._set_sep("none"))
        self._update_sep_checks()

        sep_menu = rumps.MenuItem("Separator")
        sep_menu.update([self.sep_tab, self.sep_newline, self.sep_pipe, self.sep_none])

        # Options
        self.sentinels_item = rumps.MenuItem(
            "Include Sentinels (% ; ?)", callback=self.on_toggle_sentinels
        )
        self.sentinels_item.state = self.config.include_sentinels

        self.enter_item = rumps.MenuItem(
            "Press Enter After Swipe", callback=self.on_toggle_enter
        )
        self.enter_item.state = self.config.press_enter_after

        quit_item = rumps.MenuItem("Quit", callback=self.on_quit)

        self.menu = [
            self.status_item,
            self.swipe_status,
            None,  # separator
            self.reconnect_item,
            None,
            "Output Tracks:",
            self.track1_item,
            self.track2_item,
            self.track3_item,
            None,
            sep_menu,
            self.sentinels_item,
            self.enter_item,
            None,
            quit_item,
        ]

    # ── Lifecycle ──

    def start_reader(self):
        """Connect to device and start the background read loop."""
        if not self._connect_lock.acquire(blocking=False):
            return  # another connect is already in progress
        try:
            if self._running or self.transport.connected:
                return  # already connected

            self.transport.connect()
            self.protocol = MSRProtocol(self.transport)
            self.protocol.reset()

            if self.protocol.comm_test():
                self.status_item.title = "Connected — MSR605x"
                log.info("Device comm test passed")
            else:
                self.status_item.title = "Connected (comm test failed)"
                log.warning("Comm test did not get expected response")

            self._running = True
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True, name="msr-reader"
            )
            self._reader_thread.start()

        except HIDTransportError as e:
            self.status_item.title = f"Error: {e}"
            log.error("Connection failed: %s", e)
        finally:
            self._connect_lock.release()

    def _read_loop(self):
        """Background thread: continuously read cards."""
        while self._running:
            try:
                self._update_swipe_status("Waiting for swipe...")
                self.protocol.led_green()
                result = self.protocol.iso_read(timeout_ms=30000)

                if result.success:
                    log.info("Card read OK: T1=%d T2=%d T3=%d chars",
                             len(result.track1), len(result.track2), len(result.track3))
                    self.protocol.led_green()
                    swipe_queue.put(result)
                    self._update_swipe_status("Card read OK")
                elif result.track1 or result.track2 or result.track3:
                    # Partial read — still usable
                    log.warning("Partial read (status=%#x)", result.status)
                    swipe_queue.put(result)
                    self._update_swipe_status("Partial read")
                else:
                    # Timeout or no data — just loop
                    pass

                # Brief pause before re-entering read mode
                time.sleep(0.2)
                if self._running:
                    self.protocol.reset()
                    time.sleep(0.1)

            except HIDTransportError as e:
                log.error("Read error: %s", e)
                self._update_swipe_status(f"Error: {e}")
                self.status_item.title = "Disconnected"
                self._running = False
                # Attempt reconnection after a delay
                time.sleep(2)
                self._attempt_reconnect()

    def _attempt_reconnect(self):
        """Try to reconnect to the device."""
        self.transport.close()
        for attempt in range(5):
            try:
                time.sleep(2)
                self.transport.connect()
                self.protocol = MSRProtocol(self.transport)
                self.protocol.reset()
                self.status_item.title = "Connected — MSR605x"
                self._running = True
                self._reader_thread = threading.Thread(
                    target=self._read_loop, daemon=True, name="msr-reader"
                )
                self._reader_thread.start()
                return
            except HIDTransportError:
                log.info("Reconnect attempt %d failed", attempt + 1)
        self.status_item.title = "Disconnected — click Reconnect"

    def _update_swipe_status(self, text: str):
        """Update the swipe status menu item (thread-safe via rumps)."""
        self.swipe_status.title = text

    # ── Timer: process swipe queue on main thread ──

    @rumps.timer(0.1)
    def check_queue(self, _):
        """Drain the swipe queue and type data."""
        while not swipe_queue.empty():
            try:
                data = swipe_queue.get_nowait()
                output = self.config.format_tracks(
                    data.track1, data.track2, data.track3
                )
                if output:
                    type_string(output, self.config.inter_key_delay)
                    if self.config.press_enter_after:
                        type_enter()
            except queue.Empty:
                break

    # ── Device reconnect timer ──

    @rumps.timer(3)
    def check_device(self, _):
        """Periodically check if device is still connected."""
        if not self._running and not self.transport.connected:
            devices = self.transport.enumerate()
            if devices:
                log.info("Device detected, reconnecting...")
                self.start_reader()

    # ── Menu callbacks ──

    def on_reconnect(self, _):
        self._running = False
        self.transport.close()
        time.sleep(0.3)
        self.start_reader()

    def on_toggle_track1(self, sender):
        sender.state = not sender.state
        self.config.track1_enabled = sender.state
        self.config.save()

    def on_toggle_track2(self, sender):
        sender.state = not sender.state
        self.config.track2_enabled = sender.state
        self.config.save()

    def on_toggle_track3(self, sender):
        sender.state = not sender.state
        self.config.track3_enabled = sender.state
        self.config.save()

    def on_toggle_sentinels(self, sender):
        sender.state = not sender.state
        self.config.include_sentinels = sender.state
        self.config.save()

    def on_toggle_enter(self, sender):
        sender.state = not sender.state
        self.config.press_enter_after = sender.state
        self.config.save()

    def _set_sep(self, sep_name: str):
        self.config.separator = sep_name
        self.config.save()
        self._update_sep_checks()

    def _update_sep_checks(self):
        self.sep_tab.state = self.config.separator == "tab"
        self.sep_newline.state = self.config.separator == "newline"
        self.sep_pipe.state = self.config.separator == "pipe"
        self.sep_none.state = self.config.separator == "none"

    def on_quit(self, _):
        self._running = False
        self.transport.close()
        rumps.quit_application()


def main():
    # Check accessibility permissions
    if not check_accessibility():
        resp = rumps.alert(
            title="Accessibility Permission Required",
            message=(
                "MagSwipe needs Accessibility access to type card data "
                "into input fields.\n\n"
                "Click OK to open System Settings. Add this app (or Terminal/"
                "Python) to the Accessibility list, then restart MagSwipe."
            ),
            ok="Open Settings",
            cancel="Quit",
        )
        if resp == 1:  # OK
            request_accessibility()
        sys.exit(1)

    app = MagSwipeApp()
    # Start reader after a short delay to let rumps initialize
    threading.Timer(1.0, app.start_reader).start()
    app.run()


if __name__ == "__main__":
    main()
