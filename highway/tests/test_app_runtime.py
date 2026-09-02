from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from highway.app.agent_runtime import OagAgentRuntime  # noqa: E402


class HighwayAgentRuntimeTest(unittest.TestCase):
    def test_default_runtime_remains_the_writable_main_domain(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        try:
            self.assertEqual(["highway.passage_charging"], runtime.domain_ids)
            self.assertEqual(12, len(runtime.runtime.ontology.actions))
            self.assertEqual(0, len(runtime.ontology.actions))
            self.assertEqual(5, len(runtime.domain_catalog()))
            self.assertIn("settlement", runtime.ontology.objects)
            self.assertEqual(46, len(runtime.bootstrap(include_graph=False)["model"]["actions"]))
            self.assertEqual(
                "highway.facility_operations",
                runtime.match_domains("登记收费站", limit=1)[0]["id"],
            )
            self.assertEqual(["highway.passage_charging"], runtime.status()["domains"])
        finally:
            runtime.close()

    def test_environment_can_select_a_read_only_domain_composition(self) -> None:
        previous = os.environ.get("UOM_DOMAIN_IDS")
        os.environ["UOM_DOMAIN_IDS"] = (
            "highway.customer_accounts,highway.facility_operations"
        )
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        try:
            self.assertEqual(
                ["highway.customer_accounts", "highway.facility_operations"],
                runtime.domain_ids,
            )
            self.assertEqual(0, len(runtime.ontology.actions))
            self.assertIn("account", runtime.ontology.objects)
            self.assertIn("equipment", runtime.ontology.objects)
            self.assertEqual(
                runtime.domain_ids,
                runtime.status()["domains"],
            )
        finally:
            runtime.close()
            if previous is None:
                os.environ.pop("UOM_DOMAIN_IDS", None)
            else:
                os.environ["UOM_DOMAIN_IDS"] = previous

    @patch.dict(
        os.environ,
        {"OAG_MODEL": "", "OPENAI_MODEL": "", "LLM_MODEL": ""},
    )
    def test_chat_lazily_routes_single_and_composed_domains(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        try:
            facility_events = list(runtime.chat("登记收费站", "facility-session"))
            self.assertEqual(
                ["highway.facility_operations"],
                facility_events[0]["selected"],
            )
            self.assertIn(
                ("highway.facility_operations",),
                runtime.runtime_manager.loaded_domain_sets,
            )

            composed_events = list(
                runtime.chat("账户和清分有什么关系", "composed-session")
            )
            self.assertEqual(
                {
                    "highway.customer_accounts",
                    "highway.clearing_settlement",
                },
                set(composed_events[0]["selected"]),
            )
            self.assertIn(
                tuple(composed_events[0]["selected"]),
                runtime.runtime_manager.loaded_domain_sets,
            )
        finally:
            runtime.close()

    def test_manual_session_selection_and_public_catalog(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        try:
            context = runtime.select_domains(
                "manual-session",
                ["highway.customer_accounts"],
            )

            self.assertEqual("manual", context["mode"])
            self.assertEqual(["highway.customer_accounts"], context["selected"])
            self.assertEqual(
                {"id", "name", "version", "description"},
                set(context["domains"][0]),
            )
            self.assertNotIn("path", context["domains"][0])
            self.assertNotIn("terms", context["domains"][0])
            self.assertNotIn("action_terms", context["domains"][0])

            automatic = runtime.select_domains(
                "manual-session",
                automatic=True,
            )
            self.assertEqual("auto", automatic["mode"])
            self.assertEqual(["highway.customer_accounts"], automatic["selected"])
        finally:
            runtime.close()

    def test_action_preview_uses_owning_child_domain(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        child = ["highway.facility_operations"]
        try:
            preview = runtime.preview_action(
                action_id="register_toll_road",
                inputs={"name": "路由测试收费公路", "code": "ROUTING-TEST"},
                domain_ids=child,
            )

            self.assertTrue(preview["valid"])
            self.assertEqual(
                tuple(child),
                runtime._action_preview_domains[preview["preview_token"]],
            )
        finally:
            runtime.close()

    def test_workbench_aggregates_actions_and_infers_their_owner(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        try:
            available = runtime.list_actions("charge:etc_001")["actions"]
            by_id = {item["id"]: item for item in available}

            self.assertEqual(
                ["highway.passage_charging"],
                by_id["record_payment"]["domain_ids"],
            )
            self.assertEqual(
                ["highway.clearing_settlement"],
                by_id["record_split"]["domain_ids"],
            )
            preview = runtime.preview_action(
                action_id="register_toll_road",
                inputs={"name": "自动归属测试公路", "code": "OWNER-TEST"},
            )
            self.assertTrue(preview["valid"])
            self.assertEqual(
                ("highway.facility_operations",),
                runtime._action_preview_domains[preview["preview_token"]],
            )
        finally:
            runtime.close()

    def test_workbench_bootstrap_exposes_full_model_and_ownership(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        try:
            bootstrap = runtime.bootstrap(include_graph=False)

            self.assertEqual(36, len(bootstrap["model"]["object_types"]))
            self.assertEqual(
                ["highway.facility_operations"],
                bootstrap["domain_ownership"]["objects"]["toll_interval"],
            )
            self.assertEqual(
                ["highway.pricing_control"],
                bootstrap["domain_ownership"]["objects"]["rate_rule"],
            )
        finally:
            runtime.close()

    def test_imported_anchor_cannot_be_written_through_the_wrong_domain(self) -> None:
        runtime = OagAgentRuntime(ROOT, ROOT / "highway")
        operation = [{
            "action": "create_object",
            "record": {
                "id": "rate_rule:wrong-owner",
                "type": "rate_rule",
                "name": "错误归属费率",
                "properties": {
                    "code": "WRONG-OWNER",
                    "vehicle_type": "一类客车",
                    "fee_type": "distance",
                    "valid_from": "2026-09-01",
                },
            },
        }]
        try:
            with self.assertRaisesRegex(
                ValueError,
                "不属于领域 highway.passage_charging",
            ):
                runtime.preview_changes(
                    operation,
                    domain_ids=["highway.passage_charging"],
                )
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
