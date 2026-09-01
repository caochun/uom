from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oag-agent"))
sys.path.insert(0, str(ROOT))

from uom.registry import DomainRegistry  # noqa: E402
from uom.routing import DomainRouter  # noqa: E402


class DomainRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = DomainRouter(
            DomainRegistry.discover(ROOT / "highway"),
            default_ids=["highway.passage_charging"],
        )

    def test_irrelevant_intent_keeps_default_domain(self) -> None:
        selection = self.router.resolve("session", "今天天气怎么样")

        self.assertEqual(("highway.passage_charging",), selection.domain_ids)
        self.assertEqual("keep_current", selection.reason)
        self.assertFalse(selection.changed)

    def test_action_intent_selects_one_owning_domain(self) -> None:
        selection = self.router.resolve("session", "登记收费站")

        self.assertEqual(
            ("highway.facility_operations",),
            selection.domain_ids,
        )

    def test_read_question_composes_matching_domains(self) -> None:
        selection = self.router.resolve("session", "账户和清分有什么关系")

        self.assertEqual(
            {
                "highway.customer_accounts",
                "highway.clearing_settlement",
            },
            set(selection.domain_ids),
        )
        self.assertNotIn("highway.passage_charging", selection.domain_ids)

    def test_manual_pin_overrides_intent_until_auto_is_restored(self) -> None:
        self.router.select(
            "session",
            ["highway.customer_accounts"],
            manual=True,
        )

        pinned = self.router.resolve("session", "登记收费站")
        self.assertEqual(("highway.customer_accounts",), pinned.domain_ids)
        self.assertEqual("manual", pinned.reason)

        self.router.use_auto("session")
        automatic = self.router.resolve("session", "登记收费站")
        self.assertEqual(
            ("highway.facility_operations",),
            automatic.domain_ids,
        )

    def test_locked_selection_cannot_switch(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "待确认"):
            self.router.select(
                "session",
                ["highway.customer_accounts"],
                locked=True,
            )

        selection = self.router.resolve("session", "登记收费站", locked=True)
        self.assertEqual(("highway.passage_charging",), selection.domain_ids)
        self.assertEqual("pending_confirmation", selection.reason)


if __name__ == "__main__":
    unittest.main()
