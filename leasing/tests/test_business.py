from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from leasing.business import (  # noqa: E402
    audit_finance_consistency,
    find_unallocated_payments,
    get_contract_trace,
)
from leasing.scripts.seed import build_graph  # noqa: E402


class MemoryRepository:
    def __init__(self, objects, relations):
        self.records = {"Object": objects, "Relation": relations}

    def query(self, object_type, filters=None):
        records = self.records[object_type]
        if not filters:
            return records
        return [
            item for item in records
            if all(item.get(key) == value for key, value in filters.items())
        ]

    def query_by_id(self, object_type, record_id):
        return next(
            (item for item in self.records[object_type] if item.get("id") == record_id),
            None,
        )


class LeasingBusinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.objects, self.relations = build_graph()
        self.repository = MemoryRepository(self.objects, self.relations)

    def test_seed_money_and_voucher_invariants_hold(self) -> None:
        result = audit_finance_consistency(self.repository)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(1_000_000, result["allocated_by_payment"]["payment:001"])
        self.assertEqual(900_000, result["allocated_by_target"]["receivable:001"])
        self.assertEqual(
            {"reserved": 0.0, "used": 10_000_000.0},
            result["credit_balances"]["credit:001"],
        )

    def test_seed_represents_distinct_credit_lifecycle_states(self) -> None:
        balances = audit_finance_consistency(self.repository)["credit_balances"]
        self.assertEqual(
            {"reserved": 4_000_000.0, "used": 0.0},
            balances["credit:qingdao"],
        )
        self.assertEqual(
            {"reserved": 0.0, "used": 0.0},
            balances["credit:weifang"],
        )
        self.assertEqual(
            {"reserved": 0.0, "used": 7_200_000.0},
            balances["credit:yantai"],
        )
        self.assertEqual(
            {"reserved": 0.0, "used": 0.0},
            balances["credit:zibo"],
        )

    def test_seed_represents_many_to_many_payment_allocation(self) -> None:
        result = audit_finance_consistency(self.repository)
        self.assertEqual(
            550_000,
            result["allocated_by_payment"]["payment:yantai:001"],
        )
        self.assertEqual(
            355_000,
            result["allocated_by_payment"]["payment:yantai:002"],
        )
        self.assertEqual(
            400_000,
            result["allocated_by_target"]["receivable:yantai:002"],
        )
        self.assertEqual(
            5_000,
            result["allocated_by_target"]["penalty:yantai:003"],
        )

    def test_seed_approval_targets_match_their_business_facts(self) -> None:
        reviewed = {
            relation["from"]: relation["to"]
            for relation in self.relations
            if relation["type"] == "references"
            and relation.get("properties", {}).get("role") == "reviewed_object"
        }
        self.assertEqual("lease_plan:001", reviewed["approval:plan:001"])
        self.assertEqual("change:001", reviewed["approval:change:001"])
        self.assertEqual(
            "lease_plan:qingdao",
            reviewed["approval:plan:qingdao"],
        )

    def test_unallocated_payment_is_found(self) -> None:
        self.assertEqual(
            ["payment:002"],
            [item["id"] for item in find_unallocated_payments(self.repository)],
        )

    def test_over_allocation_is_rejected(self) -> None:
        objects = copy.deepcopy(self.objects)
        allocation = next(item for item in objects if item["id"] == "allocation:002")
        allocation["properties"]["amount"]["amount"] = 200_000
        result = audit_finance_consistency(MemoryRepository(objects, self.relations))
        self.assertFalse(result["valid"])
        self.assertTrue(any("payment:001" in error for error in result["errors"]))

    def test_allocation_progress_status_must_match_amounts(self) -> None:
        objects = copy.deepcopy(self.objects)
        payment = next(item for item in objects if item["id"] == "payment:001")
        payment["properties"]["status"] = "partial"
        result = audit_finance_consistency(MemoryRepository(objects, self.relations))
        self.assertFalse(result["valid"])
        self.assertIn(
            "payment:001: 核销进度对应状态应为 allocated，当前为 partial",
            result["errors"],
        )

    def test_credit_entries_cannot_exceed_limit(self) -> None:
        objects = copy.deepcopy(self.objects)
        reservation = next(
            item for item in objects if item["id"] == "credit_entry:reserve"
        )
        reservation["properties"]["amount"]["amount"] = 13_000_000
        result = audit_finance_consistency(MemoryRepository(objects, self.relations))
        self.assertFalse(result["valid"])
        self.assertTrue(any("credit:001" in error for error in result["errors"]))

    def test_unbalanced_voucher_is_rejected(self) -> None:
        objects = copy.deepcopy(self.objects)
        credit = next(item for item in objects if item["id"] == "voucher_line:credit")
        credit["properties"]["amount"]["amount"] = 900_000
        result = audit_finance_consistency(MemoryRepository(objects, self.relations))
        self.assertFalse(result["valid"])
        self.assertIn("voucher:001: 借贷不平衡", result["errors"])

    def test_contract_trace_reaches_financing_and_collection_facts(self) -> None:
        trace = get_contract_trace(self.repository, "contract:001", depth=5)
        self.assertEqual("contract:001", trace["contract"]["id"])
        for object_type in ("loan", "schedule_version", "receivable", "allocation"):
            self.assertIn(object_type, trace["facts_by_type"])


if __name__ == "__main__":
    unittest.main()
