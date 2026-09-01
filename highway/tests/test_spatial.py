from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from highway.scripts.seed_shandong import build_graph  # noqa: E402
from highway.app.services.spatial_view import SpatialViewService  # noqa: E402
from highway.integrations.amap import AmapRoutePlanner  # noqa: E402


class MemoryRepository:
    def __init__(self, objects, relations):
        self.objects = objects
        self.relations = relations

    def query_all_objects(self):
        return self.objects

    def query_all_relations(self):
        return self.relations


class SpatialViewServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        objects, relations = build_graph()
        cls.service = SpatialViewService(MemoryRepository(objects, relations), route_planner=AmapRoutePlanner(""))

    def test_point_object_uses_its_location(self) -> None:
        view = self.service.get_view("station:zibo")
        self.assertTrue(view["available"])
        self.assertEqual("point", view["mode"])
        self.assertEqual("GCJ-02", view["coordinate_system"])

    def test_interval_uses_start_end_nodes_and_route_topology(self) -> None:
        view = self.service.get_view("interval:g20_jinan_zibo")
        self.assertEqual("route", view["mode"])
        self.assertEqual(["station:jinan_east", "gantry:g20_mid_1", "station:zibo"], view["lines"][0]["node_ids"])
        self.assertEqual("business_topology", view["route_source"])

    def test_road_combines_section_routes(self) -> None:
        view = self.service.get_view("road:g20_sd")
        self.assertEqual("route", view["mode"])
        self.assertEqual(2, len(view["lines"]))

    def test_passage_uses_observed_events_and_facilities(self) -> None:
        view = self.service.get_view("passage:etc_001")
        self.assertEqual("passage", view["mode"])
        self.assertEqual(["entry", "gantry", "exit"], [item["stage"] for item in view["events"]])
        self.assertEqual(["lane:jinan_entry", "gantry:g20_mid_1", "lane:qingdao_exit"], view["lines"][0]["node_ids"])

    def test_non_spatial_object_has_no_map_view(self) -> None:
        self.assertFalse(self.service.get_view("vehicle:lu_a12345")["available"])


if __name__ == "__main__":
    unittest.main()
