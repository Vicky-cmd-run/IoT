from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from config import settings


def map_config() -> dict:
    return {
        "provider": settings.map_provider,
        "supports_tiles": settings.map_provider == "osm",
        "requires_api_key": settings.map_provider in {"mapbox", "tomtom", "google"},
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
