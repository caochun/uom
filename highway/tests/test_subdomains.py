from __future__ import annotations

import sys
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.loader import load_domain  # noqa: E402
from uom.validation import validate_model  # noqa: E402


class HighwaySubdomainTest(unittest.TestCase):
    domains = (
        "passage_charging",
        "customer_accounts",
        "clearing_settlement",
        "facility_operations",
        "pricing_control",
    )

    def test_subdomains_load_against_the_shared_graph(self) -> None:
        for name in self.domains:
            with self.subTest(domain=name):
                domain_dir = ROOT / "highway" / "domains" / name
                runtime = load_domain(domain_dir)
                try:
                    self.assertTrue(runtime.ontology.name.startswith("Highway"))
                    self.assertGreater(len(runtime.ontology.objects), 0)
                    self.assertGreater(len(runtime.ontology.actions), 0)
                finally:
                    runtime.repository.close()

    def test_subdomains_validate_only_their_vocabulary(self) -> None:
        for name in self.domains:
            with self.subTest(domain=name):
                result = validate_model(ROOT / "highway" / "domains" / name)
                self.assertEqual([], result.errors)

    def _copy_runtime(self, domain: str):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name) / "highway"
        shutil.copytree(
            ROOT / "highway",
            root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        (root / "data").mkdir(exist_ok=True)
        shutil.copy2(ROOT / "highway" / "data" / "graph.db", root / "data" / "graph.db")
        runtime = load_domain(root / "domains" / domain)
        self.addCleanup(runtime.repository.close)
        self.addCleanup(temp_dir.cleanup)
        return runtime

    def test_customer_account_ledger_follows_entries_and_payment(self) -> None:
        runtime = self._copy_runtime("customer_accounts")
        before = runtime.bindings.call(
            "get_account_ledger", account_id="account:etc_a12345"
        )
        runtime.change_store.create_object({
            "id": "entry:test-account",
            "type": "account_entry",
            "name": "测试扣款",
            "properties": {
                "reference_no": "ENTRY-TEST",
                "entry_kind": "debit",
                "amount": {"amount": 120, "currency": "CNY"},
                "occurred_at": "2026-08-04T10:01:00+08:00",
                "result": "success",
                "balance_after": {"amount": 680, "currency": "CNY"},
            },
        })
        runtime.change_store.create_relation({
            "id": "contains:test-account-entry",
            "type": "contains",
            "from": "account:etc_a12345",
            "to": "entry:test-account",
        })
        runtime.change_store.create_relation({
            "id": "references:test-entry-payment",
            "type": "references",
            "from": "entry:test-account",
            "to": "payment:etc_001",
            "properties": {"role": "payment"},
        })

        result = runtime.bindings.call(
            "get_account_ledger", account_id="account:etc_a12345"
        )

        self.assertEqual(before["summary"]["entry_count"] + 1, result["summary"]["entry_count"])
        self.assertEqual(
            {
                "amount": before["summary"]["debits"]["amount"] + 120,
                "currency": "CNY",
            },
            result["summary"]["debits"],
        )
        self.assertEqual("payment:etc_001", result["linked_facts"]["payment"][0]["id"])
        self.assertEqual("charge:etc_001", result["linked_facts"]["charge"][0]["id"])

    def test_settlement_trace_returns_upstream_business_chain(self) -> None:
        runtime = self._copy_runtime("clearing_settlement")
        result = runtime.bindings.call(
            "get_settlement_trace", settlement_id="settlement:etc_001"
        )

        self.assertEqual(["split:etc_001"], [item["id"] for item in result["split_results"]])
        self.assertEqual(["charge:etc_001"], [item["id"] for item in result["charges"]])
        self.assertEqual(["passage:etc_001"], [item["id"] for item in result["passages"]])
        self.assertEqual(["payment:etc_001"], [item["id"] for item in result["payments"]])

    def test_facility_overview_returns_network_and_coordinates(self) -> None:
        runtime = self._copy_runtime("facility_operations")
        result = runtime.bindings.call(
            "get_facility_overview", facility_id="road:g20_sd"
        )

        self.assertEqual("road:g20_sd", result["root"]["id"])
        self.assertGreater(result["summary"]["coordinate_count"], 0)
        self.assertTrue(any(item["_object_type"] == "toll_station" for item in result["objects"]))
        self.assertTrue(any(item["_object_type"] == "contains" for item in result["relations"]))

    def test_pricing_domain_explains_passage_fare_basis(self) -> None:
        runtime = self._copy_runtime("pricing_control")
        result = runtime.bindings.call(
            "get_passage_fare_basis", passage_id="passage:etc_001"
        )

        self.assertEqual(["rate:sd_2026_08"], result["summary"][0]["rate_version_ids"])
        self.assertEqual(
            ["rate_rule:passenger_1"], result["summary"][0]["rate_rule_ids"]
        )


if __name__ == "__main__":
    unittest.main()
