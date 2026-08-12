from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from highway.scripts.seed_shandong import build_graph  # noqa: E402
from highway.spatial import AmapRoutePlanner, SpatialViewService  # noqa: E402


class MemoryRepository:
    def __init__(self, objects, relations):
        self.records = {"Object": objects, "Relation": relations}

    def query(self, object_type):
        return self.records[object_type]


class SpatialViewServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        objects, relations = build_graph()
        cls.service = SpatialViewService(
            MemoryRepository(objects, relations),
            route_planner=AmapRoutePlanner(""),
        )

    def test_point_object_uses_its_own_location(self) -> None:
        view = self.service.get_view("station:zibo")

        self.assertTrue(view["available"])
        self.assertEqual("point", view["mode"])
        self.assertEqual("GCJ-02", view["coordinate_system"])
        self.assertEqual("station:zibo", view["points"][0]["object_id"])
        self.assertEqual([], view["lines"])

    def test_interval_uses_business_endpoints_and_route_nodes(self) -> None:
        view = self.service.get_view("interval:g20_jinan_zibo")

        self.assertEqual("route", view["mode"])
        self.assertEqual(
            ["station:jinan_east", "gantry:g20_jinan_zibo", "station:zibo"],
            view["lines"][0]["node_ids"],
        )
        self.assertEqual("business_topology", view["route_source"])
        self.assertTrue(view["derived"])

    def test_road_combines_its_contained_section_routes(self) -> None:
        view = self.service.get_view("toll_road:g20_sd")

        self.assertEqual("route", view["mode"])
        self.assertEqual(2, len(view["lines"]))
        self.assertEqual("station:jinan_east", view["lines"][0]["node_ids"][0])
        self.assertEqual("station:qingdao", view["lines"][1]["node_ids"][-1])

    def test_passage_uses_only_observed_transaction_facilities(self) -> None:
        view = self.service.get_view("passage:sd_etc_001")

        self.assertEqual("passage", view["mode"])
        self.assertEqual(["entry", "gantry", "exit"], [
            item["stage"] for item in view["events"]
        ])
        self.assertEqual(
            ["lane:jinan_east_entry", "gantry:g20_zibo_qingdao", "lane:qingdao_exit"],
            view["lines"][0]["node_ids"],
        )
        self.assertTrue(all(item["occurred_at"] for item in view["events"]))

    def test_non_spatial_object_has_no_map_view(self) -> None:
        self.assertFalse(self.service.get_view("vehicle:lu_a12345")["available"])

    def test_unknown_object_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            self.service.get_view("missing:object")


if __name__ == "__main__":
    unittest.main()
