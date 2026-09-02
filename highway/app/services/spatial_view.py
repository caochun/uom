"""Build read-only map projections from the Highway cross-domain graph."""

from __future__ import annotations

from collections import deque
from typing import Any, Protocol


ROUTE_NODE_TYPES = {"toll_station", "toll_gantry", "toll_interval"}
FACILITY_TYPES = {
    "toll_station",
    "toll_lane",
    "toll_gantry",
    "toll_interval",
}
NETWORK_TYPES = {"toll_road", "section", "toll_interval"}
STAGE_LABELS = {"entry": "入口", "gantry": "门架", "exit": "出口"}


class RoutePlanner(Protocol):
    """Application port for turning business nodes into display geometry."""

    def plan(
        self,
        coordinates: list[list[float]],
    ) -> tuple[list[list[float]], str]: ...


class SpatialViewService:
    """Project spatial objects and passages without adding GIS facts to the ontology."""

    def __init__(self, repository, route_planner: RoutePlanner):
        self.repository = repository
        self.route_planner = route_planner

    def get_view(self, object_id: str) -> dict[str, Any]:
        objects = [
            self._raw_record(item, "object")
            for item in self.repository.query_all_objects()
        ]
        relations = [
            self._raw_record(item, "relation")
            for item in self.repository.query_all_relations()
        ]
        index = {item["id"]: item for item in objects}
        selected = index.get(object_id)
        if selected is None:
            raise KeyError(f"Object not found: {object_id}")

        if selected.get("type") == "passage":
            return self._passage_view(selected, index, relations)
        if selected.get("type") == "pricing_path":
            return self._pricing_path_view(selected, index, relations)
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
        event_ids = [
            relation.get("to")
            for relation in relations
            if relation.get("from") == selected["id"]
            and relation.get("type") == "contains"
            and index.get(relation.get("to"), {}).get("type") == "passage_event"
        ]
        events = [index[item_id] for item_id in event_ids if item_id in index]
        events.sort(key=lambda item: (
            str(item.get("properties", {}).get("occurred_at") or ""),
            {"entry": 0, "gantry": 1, "exit": 2}.get(
                item.get("properties", {}).get("stage"), 9
            ),
        ))

        timeline: list[dict[str, Any]] = []
        points: list[dict[str, Any]] = []
        route_ids: list[str] = []
        for event_record in events:
            facility = self._event_facility(event_record["id"], index, relations)
            if facility is None:
                continue
            point = self._point(facility)
            if point is None:
                continue
            properties = event_record.get("properties") or {}
            stage = str(properties.get("stage") or "event")
            timeline_item = {
                "id": event_record["id"],
                "name": event_record.get("name") or event_record["id"],
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, stage),
                "occurred_at": properties.get("occurred_at"),
                "facility_id": facility["id"],
                "facility_name": facility.get("name") or facility["id"],
                "facility_type": facility.get("type"),
                "amount": properties.get("paid_amount") or properties.get("receivable_amount"),
            }
            timeline.append(timeline_item)
            points.append({
                **point,
                "id": event_record["id"],
                "object_id": facility["id"],
                "name": timeline_item["facility_name"],
                "role": stage,
                "label": timeline_item["stage_label"],
                "occurred_at": timeline_item["occurred_at"],
            })
            route_ids.append(facility["id"])

        route_ids = self._deduplicate_ids(route_ids)
        lines = self._lines([route_ids], index) if len(route_ids) >= 2 else []
        return self._result(selected, points, lines, timeline, "passage")

    def _pricing_path_view(
        self,
        selected: dict[str, Any],
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        path_relations = [
            relation for relation in relations
            if relation.get("from") == selected["id"]
            and relation.get("type") == "references"
            and (relation.get("properties") or {}).get("role") == "path_node"
            and relation.get("to") in index
        ]
        path_relations.sort(key=lambda relation: (
            self._sequence(relation), str(relation.get("id") or "")
        ))

        points: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        node_ids: list[str] = []
        for position, relation in enumerate(path_relations, start=1):
            node = index[relation["to"]]
            point = self._point(node)
            if point is None:
                continue
            properties = relation.get("properties") or {}
            sequence = properties.get("sequence", position)
            mileage = properties.get("mileage")
            timeline.append({
                "id": relation.get("id"),
                "name": node.get("name") or node["id"],
                "stage": "path_node",
                "stage_label": f"第 {sequence} 节点",
                "sequence": sequence,
                "mileage": mileage,
                "facility_id": node["id"],
                "facility_name": node.get("name") or node["id"],
                "facility_type": node.get("type"),
            })
            points.append({
                **point,
                "role": "path_node",
                "label": str(sequence),
                "sequence": sequence,
                "mileage": mileage,
            })
            node_ids.append(node["id"])

        lines = self._lines([node_ids], index) if len(node_ids) >= 2 else []
        return self._result(selected, points, lines, timeline, "pricing_path")

    @staticmethod
    def _sequence(relation: dict[str, Any]) -> float:
        value = (relation.get("properties") or {}).get("sequence")
        if isinstance(value, bool):
            return float("inf")
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("inf")

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

    def _event_facility(
        self,
        event_id: str,
        index: dict[str, dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        candidates = [
            index[relation["to"]]
            for relation in relations
            if relation.get("from") == event_id
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
    def _raw_record(item: dict[str, Any], kind: str) -> dict[str, Any]:
        """Normalize an OAG semantic record for the spatial projection."""
        if "_object_type" not in item:
            return item
        base = {"id", "name"} if kind == "object" else {"id", "from", "to"}
        return {
            **{key: value for key, value in item.items() if key in base},
            "type": item["_object_type"],
            "properties": {
                key: value for key, value in item.items()
                if key not in base and key != "_object_type"
            },
        }

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
