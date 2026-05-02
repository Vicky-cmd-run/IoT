from __future__ import annotations

import math

ZONE_GRAPH: dict[str, list[str]] = {
    "north": ["central", "west", "east"],
    "central": ["north", "west", "east", "south"],
    "east": ["north", "central", "south"],
    "west": ["north", "central", "south"],
    "south": ["central", "east", "west"],
}

ZONE_LABELS: dict[str, str] = {
    "north": "Vidhana Soudha Belt",
    "south": "Majestic Link",
    "east": "MG Road Axis",
    "west": "KR Circle Corridor",
    "central": "Cubbon Core",
}

LEVEL_COST: dict[str, float] = {"low": 1.0, "medium": 3.5, "high": 8.0}

ZONE_LAYOUT_COORDS: dict[str, tuple[float, float]] = {
    "north": (50.0, 18.0),
    "west": (20.0, 48.0),
    "central": (50.0, 52.0),
    "east": (82.0, 46.0),
    "south": (46.0, 80.0),
}

ZONE_GEO_COORDS: dict[str, tuple[float, float]] = {
    "north": (12.9789, 77.5917),
    "west": (12.9682, 77.5734),
    "central": (12.9755, 77.5920),
    "east": (12.9758, 77.6098),
    "south": (12.9765, 77.5713),
}


def heuristic_distance(source: str, destination: str) -> float:
    left = ZONE_LAYOUT_COORDS.get(source)
    right = ZONE_LAYOUT_COORDS.get(destination)
    if not left or not right:
        return 0.0
    return math.dist(left, right) / 100
