from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from config import settings
from network_topology import ZONE_GEO_COORDS, ZONE_LABELS

TRAFFIC_CACHE_TTL_SECONDS = 60
_traffic_cache: dict[str, dict] = {}


def map_config() -> dict:
    return {
        "provider": settings.map_provider,
        "supports_tiles": settings.map_provider == "osm",
        "requires_api_key": settings.map_provider in {"mapbox", "tomtom", "google"},
        "tomtom_enabled": settings.map_provider == "tomtom" and bool(settings.tomtom_api_key),
    }


def _traffic_cache_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _cached_traffic(lat: float, lon: float) -> dict | None:
    entry = _traffic_cache.get(_traffic_cache_key(lat, lon))
    if not entry:
        return None
    if (time.time() - entry["fetched_at"]) > TRAFFIC_CACHE_TTL_SECONDS:
        return None
    payload = dict(entry["payload"])
    payload["cache_status"] = "fresh"
    return payload


def _store_traffic_cache(lat: float, lon: float, payload: dict) -> None:
    _traffic_cache[_traffic_cache_key(lat, lon)] = {
        "fetched_at": time.time(),
        "payload": dict(payload),
    }


def _stale_traffic(lat: float, lon: float) -> dict | None:
    entry = _traffic_cache.get(_traffic_cache_key(lat, lon))
    if not entry:
        return None
    payload = dict(entry["payload"])
    payload["cache_status"] = "stale"
    return payload


def current_traffic(lat: float, lon: float) -> dict:
    if settings.map_provider != "tomtom":
        return {
            "status": "inactive",
            "provider": settings.map_provider,
            "message": "TomTom traffic is available when MAP_PROVIDER is set to tomtom.",
            "coordinates": {"lat": lat, "lon": lon},
        }

    if not settings.tomtom_api_key:
        return {
            "status": "not_configured",
            "provider": "tomtom",
            "message": "Set TOMTOM_API_KEY in .env to enable TomTom traffic flow.",
            "coordinates": {"lat": lat, "lon": lon},
        }

    cached = _cached_traffic(lat, lon)
    if cached:
        return cached

    query = urlencode(
        {
            "key": settings.tomtom_api_key,
            "point": f"{lat},{lon}",
        }
    )
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?{query}"

    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as error:
        stale = _stale_traffic(lat, lon)
        message = f"TomTom traffic lookup failed: {error}"
        if stale:
            stale["message"] = f"{message}. Using cached traffic."
            return stale
        return {
            "status": "error",
            "provider": "tomtom",
            "message": message,
            "fallback_recommended": True,
            "coordinates": {"lat": lat, "lon": lon},
        }
    except (URLError, TimeoutError) as error:
        stale = _stale_traffic(lat, lon)
        if stale:
            stale["message"] = f"TomTom traffic lookup failed: {error}. Using cached traffic."
            return stale
        return {
            "status": "error",
            "provider": "tomtom",
            "message": f"TomTom traffic lookup failed: {error}",
            "fallback_recommended": True,
            "coordinates": {"lat": lat, "lon": lon},
        }

    segment = payload.get("flowSegmentData", {})
    current_speed = segment.get("currentSpeed")
    free_flow_speed = segment.get("freeFlowSpeed")
    confidence = segment.get("confidence")
    current_travel_time = segment.get("currentTravelTime")
    free_flow_travel_time = segment.get("freeFlowTravelTime")

    congestion_ratio = None
    if current_speed and free_flow_speed:
        try:
            congestion_ratio = round(max(0.0, 1 - (current_speed / free_flow_speed)) * 100, 2)
        except ZeroDivisionError:
            congestion_ratio = None

    result = {
        "status": "ok",
        "provider": "tomtom",
        "coordinates": {"lat": lat, "lon": lon},
        "road_name": segment.get("frc") or "TomTom flow segment",
        "current_speed_kmph": current_speed,
        "free_flow_speed_kmph": free_flow_speed,
        "current_travel_time_seconds": current_travel_time,
        "free_flow_travel_time_seconds": free_flow_travel_time,
        "confidence": confidence,
        "road_closure": segment.get("roadClosure"),
        "congestion_ratio_pct": congestion_ratio,
        "cache_status": "live",
    }
    _store_traffic_cache(lat, lon, result)
    return result


def zone_traffic_overview() -> dict:
    zones: dict[str, dict] = {}
    active_provider = settings.map_provider
    successful = 0
    fallback_needed = False

    for zone_id, (lat, lon) in ZONE_GEO_COORDS.items():
        traffic = current_traffic(lat=lat, lon=lon)
        level = "low"
        ratio = traffic.get("congestion_ratio_pct")
        if isinstance(ratio, (int, float)):
            if ratio >= 45:
                level = "high"
            elif ratio >= 20:
                level = "medium"

        zone_payload = {
            "zone_id": zone_id,
            "label": ZONE_LABELS.get(zone_id, zone_id),
            "status": traffic.get("status"),
            "congestion_level": level,
            "current_speed_kmph": traffic.get("current_speed_kmph"),
            "free_flow_speed_kmph": traffic.get("free_flow_speed_kmph"),
            "congestion_ratio_pct": ratio,
            "road_closure": traffic.get("road_closure", False),
            "cache_status": traffic.get("cache_status"),
            "message": traffic.get("message"),
        }
        zones[zone_id] = zone_payload
        if traffic.get("status") == "ok":
            successful += 1
        else:
            fallback_needed = True

    status = "ok" if successful == len(ZONE_GEO_COORDS) else "partial" if successful else "error"
    return {
        "status": status,
        "provider": active_provider,
        "zones": zones,
        "successful_zones": successful,
        "fallback_recommended": fallback_needed,
    }


def current_weather(lat: float, lon: float) -> dict:
    if not settings.openweather_api_key:
        return {
            "status": "not_configured",
            "provider": "openweather",
            "message": "Set OPENWEATHER_API_KEY in .env to enable live weather.",
            "coordinates": {"lat": lat, "lon": lon},
        }

    query = urlencode(
        {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "appid": settings.openweather_api_key,
        }
    )
    url = f"https://api.openweathermap.org/data/2.5/weather?{query}"

    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as error:
        return {
            "status": "error",
            "provider": "openweather",
            "message": f"Weather lookup failed: {error}",
            "coordinates": {"lat": lat, "lon": lon},
        }

    weather_items = payload.get("weather", [])
    main = payload.get("main", {})
    wind = payload.get("wind", {})

    return {
        "status": "ok",
        "provider": "openweather",
        "location": payload.get("name", "Unknown"),
        "coordinates": payload.get("coord", {"lat": lat, "lon": lon}),
        "temperature_c": main.get("temp"),
        "humidity": main.get("humidity"),
        "condition": weather_items[0].get("main") if weather_items else None,
        "description": weather_items[0].get("description") if weather_items else None,
        "wind_speed": wind.get("speed"),
    }
