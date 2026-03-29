# MSR605X-Keyboard

Turn your MSR605x magnetic stripe writer into a simple input device. Swipe a card and the track data gets typed directly into whatever input field is focused without needing to deal with the clumsy MSR605x interface. Helpful for when inputting a lot of cards into an excel spreadsheet or a GC reseller website.

## Features

- Reads magnetic stripe cards via USB HID
- Types track data into the focused input field like a keyboard
- Runs as a lightweight macOS menu bar app (💳)
- Configurable per-track output (Track 1, 2, 3)
- Configurable separator (Tab, Newline, Pipe, None)
- Optional sentinel stripping (%, ;, ?)
- Optional Enter keypress after swipe
- Auto-reconnects on device unplug/replug
- Settings persist across sessions

## Requirements

- macOS 10.13+
- Python 3.10+
- MSR605x (DEFTUN) connected via USB

## Installation

```bash
git clone https://github.com/teddyh-io/MSR605X-Keyboard.git
cd MSR605X-Keyboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
source .venv/bin/activate
python -m magswipe
```

Or use the launch script:

```bash
./run_magswipe.sh
```

On first launch, you'll be prompted to grant **Accessibility** permissions (System Settings > Privacy & Security > Accessibility). This is required for the app to simulate keyboard input.

## Menu Bar Options

| Option | Description |
|--------|-------------|
| Track 1 / 2 / 3 | Toggle which tracks are typed |
| Separator | Character between tracks (Tab, Newline, Pipe, None) |
| Include Sentinels | Keep or strip `%`, `;`, `?` markers |
| Press Enter After Swipe | Send a Return keypress after typing |
| Reconnect | Manually reconnect to the device |

## How It Works

1. Connects to the MSR605x over USB HID (VID `0x0801`, PID `0x0003`)
2. Sends ESC-based commands to enter ISO read mode
3. Blocks until a card is swiped, then parses track data
4. Uses macOS Quartz CGEvent API to simulate keyboard input into the focused field
5. Loops back to wait for the next swipe

## Project Structure

```
magswipe/
├── main.py              # Menu bar app, threading, UI
├── hid_transport.py     # USB HID 64-byte packet framing
├── msr_protocol.py      # MSR605 ESC command protocol
├── keyboard_emitter.py  # CGEvent keyboard simulation
├── config.py            # Persistent user preferences
```

## License

MIT

## Thanks To

Thanks to all these people who did the hard work of reverse-engineering this device.

- [rubicae/msr605x](https://github.com/rubicae/msr605x) — HID packet framing docs
- [wesley27/magworks](https://github.com/wesley27/magworks) — PyUSB CLI tool for MSR devices
- [egginabucket/openmsr](https://github.com/egginabucket/openmsr) — Cross-platform Go GUI
- [manwinder123/MSR605-Card-Reader-Writer-Eraser-with-GUI](https://github.com/manwinder123/MSR605-Card-Reader-Writer-Eraser-with-GUI) — Python GUI
- [eucalyp/MSR605](https://github.com/eucalyp/MSR605) — Python interface
- [Protryon/misiri_driver](https://github.com/Protryon/misiri_driver) — Multi-platform driver
- [InteliSecureLabs/MSR605](https://github.com/InteliSecureLabs/MSR605) — C/C++ library
- [bentbot/MSR605-GUI](https://github.com/bentbot/MSR605-GUI) — Python GUI
- [raphaelm/msrtool](https://github.com/raphaelm/msrtool) — Linux CLI tool
