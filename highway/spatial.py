"""Build read-only spatial projections from the OMS object-relation graph."""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


ROUTE_NODE_TYPES = {"toll_station", "toll_gantry"}
FACILITY_TYPES = {
    "toll_station",
    "toll_plaza",
    "toll_lane",
    "toll_gantry",
    "service_facility",
    "business_device",
}
NETWORK_TYPES = {"toll_road", "section", "toll_interval"}
STAGE_LABELS = {"entry": "入口", "gantry": "门架", "exit": "出口"}


class AmapRoutePlanner:
    """Resolve a business node sequence to a display polyline using AMap."""

    endpoint = "https://restapi.amap.com/v3/direction/driving"

    def __init__(self, api_key: str = "", timeout: float = 5.0):
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._cache: dict[tuple[tuple[float, float], ...], tuple[list[list[float]], str]] = {}
        self._lock = threading.RLock()

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
        with urlopen(f"{self.endpoint}?{urlencode(params)}", timeout=self.timeout) as response:
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


class SpatialViewService:
    """Project spatial objects and passages without adding GIS facts to the ontology."""

    def __init__(self, repository, route_planner: AmapRoutePlanner | None = None):
        self.repository = repository
        self.route_planner = route_planner or AmapRoutePlanner(
            os.environ.get("AMAP_WEB_SERVICE_KEY", "")
        )

    @staticmethod
    def map_config() -> dict[str, Any]:
        api_key = os.environ.get("AMAP_API_KEY", "").strip()
        security_key = os.environ.get("AMAP_SECURITY_KEY", "").strip()
        return {
            "provider": "amap",
            "enabled": bool(api_key),
            "api_key": api_key,
            "security_key": security_key,
            "coordinate_system": "GCJ-02",
        }

    def get_view(self, object_id: str) -> dict[str, Any]:
        objects = self.repository.query_objects("Object")
        relations = self.repository.query_relations("Relation")
        index = {item["id"]: item for item in objects}
        selected = index.get(object_id)
        if selected is None:
            raise KeyError(f"Object not found: {object_id}")

        if selected.get("type") == "passage":
            return self._passage_view(selected, index, relations)
        if selected.get("type") in NETWORK_TYPES:
            return self._network_view(selected, index, relations)
        point = self._point(selected)
        if point is None:
            return self._empty_view(selected)
        return self._result(selected, [point], [], [], "point")

    def _network_view(
        self,
        selected: dict[str, Any],
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        chains: list[list[str]] = []
        selected_type = selected.get("type")
        if selected_type == "toll_interval":
            chain = self._interval_chain(selected["id"], index, relations)
            if chain:
                chains.append(chain)
        elif selected_type == "section":
            intervals = self._children(selected["id"], "toll_interval", index, relations)
            chains.extend(
                chain for interval_id in intervals
                if (chain := self._interval_chain(interval_id, index, relations))
            )
            if not chains:
                chains.extend(self._route_chains(
                    self._children(selected["id"], None, index, relations), relations
                ))
        elif selected_type == "toll_road":
            for section_id in self._children(selected["id"], "section", index, relations):
                intervals = self._children(section_id, "toll_interval", index, relations)
                section_chains = [
                    chain for interval_id in intervals
                    if (chain := self._interval_chain(interval_id, index, relations))
                ]
                chains.extend(section_chains or self._route_chains(
                    self._children(section_id, None, index, relations), relations
                ))

        chains = [
            [node_id for node_id in chain if self._coordinates(index.get(node_id))]
            for chain in chains
        ]
        chains = [chain for chain in chains if chain]
        if not chains:
            point = self._point(selected)
            return self._result(selected, [point] if point else [], [], [], "point")

        point_ids = list(dict.fromkeys(node_id for chain in chains for node_id in chain))
        points = [self._point(index[node_id]) for node_id in point_ids]
        points = [point for point in points if point is not None]
        lines = self._lines(chains, index)
        return self._result(selected, points, lines, [], "route")

    def _passage_view(
        self,
        selected: dict[str, Any],
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        transaction_ids = [
            relation.get("to")
            for relation in relations
            if relation.get("from") == selected["id"]
            and index.get(relation.get("to"), {}).get("type") == "toll_transaction"
        ]
        transactions = [index[item_id] for item_id in transaction_ids if item_id in index]
        transactions.sort(key=lambda item: (
            str(item.get("properties", {}).get("occurred_at") or ""),
            {"entry": 0, "gantry": 1, "exit": 2}.get(
                item.get("properties", {}).get("stage"), 9
            ),
        ))

        events: list[dict[str, Any]] = []
        points: list[dict[str, Any]] = []
        route_ids: list[str] = []
        for transaction in transactions:
            facility = self._transaction_facility(transaction["id"], index, relations)
            if facility is None:
                continue
            point = self._point(facility)
            if point is None:
                continue
            properties = transaction.get("properties") or {}
            stage = str(properties.get("stage") or "event")
            event = {
                "id": transaction["id"],
                "name": transaction.get("name") or transaction["id"],
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, stage),
                "occurred_at": properties.get("occurred_at"),
                "facility_id": facility["id"],
                "facility_name": facility.get("name") or facility["id"],
                "facility_type": facility.get("type"),
                "amount": properties.get("paid_amount") or properties.get("receivable_amount"),
            }
            events.append(event)
            points.append({
                **point,
                "id": transaction["id"],
                "object_id": facility["id"],
                "name": event["facility_name"],
                "role": stage,
                "label": event["stage_label"],
                "occurred_at": event["occurred_at"],
            })
            route_ids.append(facility["id"])

        route_ids = self._deduplicate_ids(route_ids)
        lines = self._lines([route_ids], index) if len(route_ids) >= 2 else []
        return self._result(selected, points, lines, events, "passage")

    def _interval_chain(
        self,
        interval_id: str,
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> list[str]:
        endpoints: dict[str, str] = {}
        for relation in relations:
            if relation.get("from") != interval_id or relation.get("type") != "references":
                continue
            role = (relation.get("properties") or {}).get("role")
            if role in {"start_node", "end_node"}:
                endpoints[role] = relation.get("to")
        start, end = endpoints.get("start_node"), endpoints.get("end_node")
        if not start or not end:
            return []

        allowed: set[str] | None = None
        parent_sections = [
            relation.get("from") for relation in relations
            if relation.get("type") == "contains" and relation.get("to") == interval_id
            and index.get(relation.get("from"), {}).get("type") == "section"
        ]
        if parent_sections:
            allowed = {start, end}
            for section_id in parent_sections:
                allowed.update(
                    self._children(section_id, None, index, relations)
                )
            allowed = {
                node_id for node_id in allowed
                if index.get(node_id, {}).get("type") in ROUTE_NODE_TYPES
            }
        return self._find_route(start, end, relations, allowed) or [start, end]

    @staticmethod
    def _find_route(
        start: str,
        end: str,
        relations: list[dict[str, Any]],
        allowed: set[str] | None,
    ) -> list[str]:
        adjacency: dict[str, list[str]] = {}
        for relation in relations:
            if relation.get("type") != "route_next":
                continue
            source, target = relation.get("from"), relation.get("to")
            if allowed is not None and (source not in allowed or target not in allowed):
                continue
            adjacency.setdefault(source, []).append(target)
        queue = deque([[start]])
        visited = {start}
        while queue:
            path = queue.popleft()
            if path[-1] == end:
                return path
            for target in adjacency.get(path[-1], []):
                if target not in visited:
                    visited.add(target)
                    queue.append([*path, target])
        return []

    @staticmethod
    def _route_chains(
        child_ids: list[str], relations: list[dict[str, Any]]
    ) -> list[list[str]]:
        allowed = set(child_ids)
        edges = [
            (relation.get("from"), relation.get("to"))
            for relation in relations
            if relation.get("type") == "route_next"
            and relation.get("from") in allowed and relation.get("to") in allowed
        ]
        if not edges:
            return []
        targets = {target for _, target in edges}
        adjacency: dict[str, list[str]] = {}
        for source, target in edges:
            adjacency.setdefault(source, []).append(target)
        starts = [source for source in adjacency if source not in targets] or [edges[0][0]]
        chains: list[list[str]] = []
        for start in starts:
            stack = [(start, [start])]
            while stack:
                node, path = stack.pop()
                next_nodes = [item for item in adjacency.get(node, []) if item not in path]
                if not next_nodes:
                    if len(path) > 1:
                        chains.append(path)
                    continue
                stack.extend((target, [*path, target]) for target in next_nodes)
        return chains

    def _transaction_facility(
        self,
        transaction_id: str,
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        candidates = [
            index[relation["to"]]
            for relation in relations
            if relation.get("from") == transaction_id
            and relation.get("type") == "references"
            and relation.get("to") in index
            and index[relation["to"]].get("type") in FACILITY_TYPES
        ]
        candidates.sort(key=lambda item: (
            0 if item.get("type") in {"toll_lane", "toll_gantry"} else 1,
            item.get("id", ""),
        ))
        for candidate in candidates:
            if self._coordinates(candidate):
                return candidate
            ancestor = self._located_ancestor(candidate["id"], index, relations)
            if ancestor is not None:
                return ancestor
        return None

    def _located_ancestor(
        self,
        object_id: str,
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        queue = deque([object_id])
        visited = {object_id}
        while queue:
            child = queue.popleft()
            for relation in relations:
                if relation.get("type") != "contains" or relation.get("to") != child:
                    continue
                parent_id = relation.get("from")
                if parent_id in visited or parent_id not in index:
                    continue
                visited.add(parent_id)
                parent = index[parent_id]
                if self._coordinates(parent):
                    return parent
                queue.append(parent_id)
        return None

    def _lines(
        self,
        chains: list[list[str]],
        index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = []
        for number, chain in enumerate(chains, start=1):
            coordinates = [
                self._coordinates(index.get(node_id)) for node_id in chain
            ]
            coordinates = [point for point in coordinates if point is not None]
            if len(coordinates) < 2:
                continue
            geometry, source = self.route_planner.plan(coordinates)
            result.append({
                "id": f"route:{number}",
                "coordinates": geometry,
                "node_ids": chain,
                "source": source,
                "derived": True,
            })
        return result

    @staticmethod
    def _children(
        parent_id: str,
        object_type: str | None,
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> list[str]:
        result = []
        for relation in relations:
            if relation.get("type") != "contains" or relation.get("from") != parent_id:
                continue
            child_id = relation.get("to")
            child = index.get(child_id)
            if child and (object_type is None or child.get("type") == object_type):
                result.append(child_id)
        return result

    @classmethod
    def _point(cls, item: dict[str, Any] | None) -> dict[str, Any] | None:
        coordinates = cls._coordinates(item)
        if item is None or coordinates is None:
            return None
        return {
            "id": item["id"],
            "object_id": item["id"],
            "name": item.get("name") or item["id"],
            "type": item.get("type"),
            "longitude": coordinates[0],
            "latitude": coordinates[1],
            "role": "location",
        }

    @staticmethod
    def _coordinates(item: dict[str, Any] | None) -> list[float] | None:
        if not item:
            return None
        properties = item.get("properties") or {}
        longitude, latitude = properties.get("longitude"), properties.get("latitude")
        if isinstance(longitude, bool) or isinstance(latitude, bool):
            return None
        if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
            return None
        return [float(longitude), float(latitude)]

    @staticmethod
    def _deduplicate_ids(values: list[str]) -> list[str]:
        result = []
        for value in values:
            if not result or result[-1] != value:
                result.append(value)
        return result

    @staticmethod
    def _empty_view(selected: dict[str, Any]) -> dict[str, Any]:
        return {
            "available": False,
            "object_id": selected["id"],
            "object_type": selected.get("type"),
        }

    @staticmethod
    def _result(
        selected: dict[str, Any],
        points: list[dict[str, Any]],
        lines: list[dict[str, Any]],
        events: list[dict[str, Any]],
        mode: str,
    ) -> dict[str, Any]:
        if not points and not lines:
            return SpatialViewService._empty_view(selected)
        sources = {line["source"] for line in lines}
        return {
            "available": True,
            "object_id": selected["id"],
            "object_type": selected.get("type"),
            "mode": mode,
            "coordinate_system": "GCJ-02",
            "points": points,
            "lines": lines,
            "events": events,
            "derived": bool(lines),
            "route_source": (
                "amap_route_planning" if sources == {"amap_route_planning"}
                else "business_topology" if sources else "object_coordinates"
            ),
        }
