"""Transient traffic and route-weather integrations for Driver Assistance.

The service deliberately keeps route conditions out of persistence.  A missing
provider is a normal state: callers continue using the public OSRM route.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx


TRAFFIC_TIMEOUT_SECONDS = 8.0
WEATHER_TIMEOUT_SECONDS = 8.0


def _safe_mapbox_error(response: httpx.Response, token: str) -> dict[str, str | int]:
    """Return only bounded, non-secret provider diagnostics."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = {}
    code = str(payload.get("code") or "http_error")[:80] if isinstance(payload, dict) else "http_error"
    message = str(payload.get("message") or "Mapbox Directions request failed.")[:300] if isinstance(payload, dict) else "Mapbox Directions request failed."
    if token:
        message = message.replace(token, "[redacted]")
    message = re.sub(r"access_token=[^&\s]+", "access_token=[redacted]", message, flags=re.IGNORECASE)
    return {"http_status": response.status_code, "error_code": code, "error_message": message}


def traffic_provider_status() -> dict[str, Any]:
    token = (os.environ.get("MAPBOX_DIRECTIONS_TOKEN") or os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip()
    if token:
        return {"provider": "mapbox", "configured": True, "traffic_aware": True, "incidents": False, "mode": "traffic-aware", "health": "configured"}
    return {"provider": None, "configured": False, "traffic_aware": False, "incidents": False, "mode": "standard-routing", "health": "not_configured"}


def _classify_congestion(values: list[Any]) -> str | None:
    levels = {str(value).lower() for value in values if value not in (None, "")}
    levels.discard("unknown")
    if not levels:
        return None
    if levels & {"severe", "critical"}: return "Severe"
    if levels & {"heavy", "very heavy"}: return "Heavy"
    if levels & {"moderate", "medium"}: return "Moderate"
    if levels <= {"low"}: return "Light"
    return None


def parse_traffic_route(payload: dict[str, Any]) -> dict[str, Any] | None:
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict): return None
    route = routes[0]
    duration = route.get("duration")
    if not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or duration <= 0: return None
    baseline = route.get("duration_typical") or route.get("typical_duration")
    delay = max(0.0, float(duration) - float(baseline)) if isinstance(baseline, (int, float)) else None
    congestion_values = route.get("congestion") if isinstance(route.get("congestion"), list) else []
    if not congestion_values:
        for leg in route.get("legs") or []:
            annotation = leg.get("annotation") if isinstance(leg, dict) else None
            if isinstance(annotation, dict) and isinstance(annotation.get("congestion"), list): congestion_values.extend(annotation["congestion"])
    congestion = _classify_congestion(congestion_values)
    alternatives = [float(item.get("duration")) for item in routes[1:] if isinstance(item, dict) and isinstance(item.get("duration"), (int, float)) and float(item["duration"]) > 0]
    best_alternative = min(alternatives) if alternatives else None
    return {"duration_seconds": float(duration), "baseline_seconds": float(baseline) if isinstance(baseline, (int, float)) else None, "delay_seconds": delay, "traffic": congestion, "incidents": [], "distance_meters": route.get("distance") if isinstance(route.get("distance"), (int, float)) else None, "geometry": route.get("geometry"), "alternative_duration_seconds": best_alternative, "reroute_recommended": should_reroute_for_traffic(float(duration), best_alternative), "provider": "mapbox"}


def should_reroute_for_traffic(current_seconds: float, alternative_seconds: float | None, threshold_seconds: float = 300, threshold_ratio: float = 0.10) -> bool:
    """Require both a meaningful absolute and relative saving to avoid oscillation."""
    if alternative_seconds is None or current_seconds <= 0 or alternative_seconds <= 0: return False
    saving = current_seconds - alternative_seconds
    return saving >= threshold_seconds and saving / current_seconds >= threshold_ratio


async def fetch_traffic_route(origin: dict[str, float], destination: dict[str, float]) -> dict[str, Any] | None:
    status = traffic_provider_status()
    if not status["configured"]: return {"status": "unavailable", "reason": "not_configured", **status}
    token = (os.environ.get("MAPBOX_DIRECTIONS_TOKEN") or os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip()
    url = f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{origin['lng']},{origin['lat']};{destination['lng']},{destination['lat']}"
    depart_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    params = {"access_token": token, "alternatives": "true", "overview": "full", "geometries": "geojson", "annotations": "congestion,duration", "depart_at": depart_at}
    try:
        # Mapbox is a direct HTTPS provider.  Do not inherit the machine's
        # generic proxy variables: a stale proxy must not turn a reachable
        # provider into a false provider_unavailable result. TLS verification
        # remains enabled by httpx.
        async with httpx.AsyncClient(timeout=TRAFFIC_TIMEOUT_SECONDS, trust_env=False) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            parsed = parse_traffic_route(response.json())
            return {"status": "traffic-aware", **parsed} if parsed else {"status": "unavailable", "reason": "invalid_provider_response", **status}
    except httpx.HTTPStatusError as exc:
        details = _safe_mapbox_error(exc.response, token)
        if exc.response.status_code == 401: reason = "invalid_token"
        elif exc.response.status_code == 403: reason = "forbidden/account_or_token_restriction"
        elif exc.response.status_code == 404: reason = "invalid_profile"
        elif exc.response.status_code == 422: reason = "invalid_request"
        elif exc.response.status_code == 429: reason = "rate_limited"
        else: reason = "provider_unavailable"
        return {"status": "unavailable", "reason": reason, **details, **status, "health": reason}
    except (httpx.TimeoutException, TimeoutError):
        return {"status": "unavailable", "reason": "timeout", **status, "health": "timeout"}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, RuntimeError):
        return {"status": "unavailable", "reason": "provider_unavailable", **status, "health": "provider_unavailable"}


def sample_route_points(coordinates: list[Any], max_points: int = 8) -> list[dict[str, float]]:
    valid = []
    for point in coordinates:
        try:
            lng, lat = float(point[0]), float(point[1])
            if math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180: valid.append({"latitude": lat, "longitude": lng})
        except (TypeError, ValueError, IndexError):
            continue
    if len(valid) <= max_points: return valid
    indexes = [round(i * (len(valid) - 1) / (max_points - 1)) for i in range(max_points)]
    return [valid[index] for index in indexes]


def parse_route_weather(payload: dict[str, Any], points: list[dict[str, float]]) -> dict[str, Any]:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict): return {"status": "unavailable", "hazards": []}
    rain = hourly.get("precipitation", []) or []; showers = hourly.get("showers", []) or []; snow = hourly.get("snowfall", []) or []; wind = hourly.get("wind_speed_10m", []) or []; weather = hourly.get("weather_code", []) or []
    hazards = []
    if any(float(value or 0) >= 20 for value in rain + showers): hazards.append({"type": "heavy-rain", "severity": "high"})
    elif any(float(value or 0) >= 5 for value in rain + showers): hazards.append({"type": "rain", "severity": "significant"})
    if any(float(value or 0) > 0 for value in snow): hazards.append({"type": "snow", "severity": "significant"})
    if any(float(value or 0) >= 45 for value in wind): hazards.append({"type": "strong-wind", "severity": "significant"})
    if any(int(value or 0) in {45, 48} for value in weather): hazards.append({"type": "fog", "severity": "significant"})
    if any(int(value or 0) in {95, 96, 99} for value in weather): hazards.append({"type": "thunderstorm", "severity": "high"})
    return {"status": "available", "sample_count": len(points), "hazards": hazards, "checked_at": datetime.now(timezone.utc).isoformat()}


async def fetch_route_weather(points: list[dict[str, float]]) -> dict[str, Any]:
    if not points: return {"status": "unavailable", "hazards": []}
    params = {"latitude": ",".join(str(point["latitude"]) for point in points), "longitude": ",".join(str(point["longitude"]) for point in points), "hourly": "precipitation,showers,snowfall,wind_speed_10m,weather_code", "forecast_days": 2, "timezone": "auto"}
    try:
        async with httpx.AsyncClient(timeout=WEATHER_TIMEOUT_SECONDS) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            data = response.json()
            # Open-Meteo returns one object per coordinate for multi-point requests.
            payload = data[0] if isinstance(data, list) else data
            return parse_route_weather(payload, points)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, RuntimeError):
        return {"status": "unavailable", "hazards": []}
