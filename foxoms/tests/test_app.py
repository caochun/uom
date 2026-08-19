from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ROOT = ROOT / "foxoms"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from foxoms.app.agent_runtime import OagAgentRuntime  # noqa: E402


class FoxOmsAppTest(unittest.TestCase):
    def test_runtime_bootstrap_exposes_foxoms_graph(self) -> None:
        runtime = OagAgentRuntime(ROOT, DOMAIN_ROOT)
        try:
            payload = runtime.bootstrap()
        finally:
            runtime.close()

        self.assertEqual("FoxOMS", payload["model"]["model"]["name"])
        self.assertEqual(43, payload["stats"]["object_count"])
        self.assertEqual(65, payload["stats"]["relation_count"])
        self.assertEqual(8, payload["stats"]["object_types"]["party"])
        self.assertEqual(20, len(payload["model"]["actions"]))
        self.assertEqual(
            2,
            sum(
                item["type"] == "party"
                and item.get("properties", {}).get("is_managed") is True
                for item in payload["objects"]
            ),
        )

    def test_static_shell_is_foxoms_specific(self) -> None:
        static_root = DOMAIN_ROOT / "app" / "static"
        content = "\n".join(
            (static_root / name).read_text(encoding="utf-8")
            for name in ("index.html", "app.js")
        )

        self.assertIn("FoxOMS", content)
        self.assertIn("企业运营", content)
        self.assertIn("经营工作台", content)
        self.assertIn("商务拓展", content)
        self.assertIn("开票回款", content)
        self.assertIn("资源资产", content)
        self.assertIn("全部数据", content)
        self.assertNotIn("融资租赁", content)


if __name__ == "__main__":
    unittest.main()
