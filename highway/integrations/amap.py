"""AMap integration for browser configuration and route planning."""

from __future__ import annotations

import json
import os
import threading
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


def web_map_config() -> dict[str, Any]:
    """Return the public AMap browser configuration."""
    api_key = os.environ.get("AMAP_API_KEY", "").strip()
    security_key = os.environ.get("AMAP_SECURITY_KEY", "").strip()
    return {
        "provider": "amap",
        "enabled": bool(api_key),
        "api_key": api_key,
        "security_key": security_key,
        "coordinate_system": "GCJ-02",
    }


class AmapRoutePlanner:
    """Resolve a business node sequence to a display polyline using AMap."""

    endpoint = "https://restapi.amap.com/v3/direction/driving"

    def __init__(self, api_key: str = "", timeout: float = 5.0):
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._cache: dict[
            tuple[tuple[float, float], ...],
            tuple[list[list[float]], str],
        ] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "AmapRoutePlanner":
        return cls(os.environ.get("AMAP_WEB_SERVICE_KEY", ""))

    def plan(self, coordinates: list[list[float]]) -> tuple[list[list[float]], str]:
        normalized = self._deduplicate(coordinates)
        if len(normalized) < 2:
            return normalized, "object_coordinates"
        key = tuple((point[0], point[1]) for point in normalized)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        result = (normalized, "business_topology")
        if self.api_key:
            try:
                planned: list[list[float]] = []
                for chunk in self._chunks(normalized, 18):
                    planned.extend(self._request(chunk))
                planned = self._deduplicate(planned)
                if len(planned) >= 2:
                    result = (planned, "amap_route_planning")
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
        with self._lock:
            self._cache[key] = result
        return result

    def _request(self, coordinates: list[list[float]]) -> list[list[float]]:
        params = {
            "key": self.api_key,
            "origin": self._format_point(coordinates[0]),
            "destination": self._format_point(coordinates[-1]),
            "strategy": "0",
            "extensions": "base",
            "output": "json",
        }
        if len(coordinates) > 2:
            params["waypoints"] = ";".join(
                self._format_point(point) for point in coordinates[1:-1]
            )
        with urlopen(
            f"{self.endpoint}?{urlencode(params)}",
            timeout=self.timeout,
        ) as response:
            payload = json.load(response)
        if str(payload.get("status")) != "1":
            raise ValueError(payload.get("info") or "AMap route planning failed")
        paths = payload.get("route", {}).get("paths") or []
        if not paths:
            raise ValueError("AMap did not return a route")
        result: list[list[float]] = []
        for step in paths[0].get("steps") or []:
            for value in str(step.get("polyline") or "").split(";"):
                if not value:
                    continue
                longitude, latitude = value.split(",", 1)
                result.append([float(longitude), float(latitude)])
        return result

    @staticmethod
    def _format_point(point: list[float]) -> str:
        return f"{point[0]:.6f},{point[1]:.6f}"

    @staticmethod
    def _deduplicate(coordinates: list[list[float]]) -> list[list[float]]:
        result: list[list[float]] = []
        for point in coordinates:
            normalized = [round(float(point[0]), 6), round(float(point[1]), 6)]
            if not result or normalized != result[-1]:
                result.append(normalized)
        return result

    @staticmethod
    def _chunks(values: list[list[float]], size: int):
        start = 0
        while start < len(values) - 1:
            chunk = values[start:start + size]
            yield chunk
            start += len(chunk) - 1
