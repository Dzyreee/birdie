"""Load and save venues/<venue_id>.json (venue info plus seat polygons)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from birdie.config import VENUES_DIR
from birdie.models import Seat, Venue, VenueConfig

_write_lock = threading.Lock()

ZONE_LABELS = {
    "quiet": "Quiet zone",
    "open": "Open study",
    "group": "Group study",
    "family": "Family section",
    "women": "Women's section",
    "terrace": "Terrace",
    "indoor": "Indoor",
}


def zone_label(zone: str) -> str:
    return ZONE_LABELS.get(zone, zone.replace("-", " ").replace("_", " ").title())


def venue_path(venue_id: str, venues_dir: Path = VENUES_DIR) -> Path:
    return Path(venues_dir) / f"{venue_id}.json"


def load_venue(venue_id: str, venues_dir: Path = VENUES_DIR) -> VenueConfig:
    with open(venue_path(venue_id, venues_dir), encoding="utf-8") as f:
        return VenueConfig.model_validate(json.load(f))


def load_all(venues_dir: Path = VENUES_DIR) -> dict[str, VenueConfig]:
    """All venues, keyed by venue_id. The live venue comes first, then by name."""
    configs = {}
    for path in sorted(Path(venues_dir).glob("*.json")):
        with open(path, encoding="utf-8") as f:
            cfg = VenueConfig.model_validate(json.load(f))
        configs[cfg.venue.venue_id] = cfg
    order = sorted(configs.values(), key=lambda c: (c.venue.source.value != "live", c.venue.name))
    return {c.venue.venue_id: c for c in order}


def save_venue(config: VenueConfig, venues_dir: Path = VENUES_DIR) -> Path:
    path = venue_path(config.venue.venue_id, venues_dir)
    data = config.model_dump(mode="json")
    tmp = path.with_suffix(".json.tmp")
    with _write_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(path)
    return path


def make_config(venue: Venue, seats: list[Seat]) -> VenueConfig:
    return VenueConfig(venue=venue, seats=seats)
