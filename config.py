"""
Configuration for MagSwipe — persisted to ~/.magswipe.json.
"""

import json
import os
import logging
from dataclasses import dataclass, field, asdict

log = logging.getLogger(__name__)

CONFIG_PATH = os.path.expanduser("~/.magswipe.json")

SEPARATOR_MAP = {
    "tab": "\t",
    "newline": "\n",
    "pipe": " | ",
    "none": "",
}


@dataclass
class Config:
    track1_enabled: bool = True
    track2_enabled: bool = True
    track3_enabled: bool = True
    separator: str = "tab"          # tab, newline, pipe, none
    include_sentinels: bool = True  # keep %, ;, ? markers
    press_enter_after: bool = False
    inter_key_delay_ms: float = 5.0  # milliseconds between keystrokes

    @property
    def sep(self) -> str:
        return SEPARATOR_MAP.get(self.separator, "\t")

    @property
    def inter_key_delay(self) -> float:
        return self.inter_key_delay_ms / 1000.0

    def save(self):
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(asdict(self), f, indent=2)
        except OSError as e:
            log.warning("Could not save config: %s", e)

    @classmethod
    def load(cls) -> "Config":
        if not os.path.exists(CONFIG_PATH):
            return cls()
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, json.JSONDecodeError, TypeError) as e:
            log.warning("Could not load config, using defaults: %s", e)
            return cls()

    def format_tracks(self, track1: str, track2: str, track3: str) -> str:
        """Format track data according to current settings."""
        parts = []
        for enabled, data in [
            (self.track1_enabled, track1),
            (self.track2_enabled, track2),
            (self.track3_enabled, track3),
        ]:
            if enabled and data:
                if not self.include_sentinels:
                    data = self._strip_sentinels(data)
                parts.append(data)
        return self.sep.join(parts)

    def _strip_sentinels(self, data: str) -> str:
        """Remove leading % or ; and trailing ? from track data."""
        if data and data[0] in ("%", ";"):
            data = data[1:]
        if data and data[-1] == "?":
            data = data[:-1]
        return data
