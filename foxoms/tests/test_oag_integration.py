from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "oag-agent"))

from foxoms.business import audit_foxoms_records  # noqa: E402
from oag.ontology.loader import load_domain  # noqa: E402
from uom.workspace import ChangeValidationError  # noqa: E402


class FoxOmsOagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.domain_root = Path(self.temp_dir.name) / "foxoms"
        shutil.copytree(
            ROOT / "foxoms",
            self.domain_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"),
        )
        self.ontology, self.repository, self.registry = load_domain(self.domain_root)

    def tearDown(self) -> None:
        self.repository.close()
        self.temp_dir.cleanup()

    def apply_action(
        self,
        action_id: str,
        inputs: dict,
        context_id: str = "",
    ) -> dict:
        preview = self.registry.call(
            "preview_action",
            action_id=action_id,
            inputs=inputs,
            context_id=context_id,
        )
        self.assertTrue(preview["valid"], preview["errors"])
        result = self.registry.call(
            "apply_action",
            preview_token=preview["preview_token"],
            reason="FoxOMS 领域集成测试",
        )
        self.assertTrue(result["applied"])
        return preview

    @staticmethod
    def created_object_id(preview: dict, object_type: str) -> str:
        return next(
            operation["record"]["id"]
            for operation in preview["operations"]
            if operation["action"] == "create_object"
            and operation["record"]["type"] == object_type
        )

    def register_party(self, name: str, is_managed: bool) -> str:
        preview = self.apply_action(
            "register_party", {"name": name, "is_managed": is_managed}
        )
        return self.created_object_id(preview, "party")

    def test_provider_uses_foxoms_action_service(self) -> None:
        self.assertEqual("FoxOMS", self.ontology.name)
        self.assertEqual(
            "FoxOmsActionService",
            type(self.registry.get_resolver("uom_actions")).__name__,
        )

    def test_framework_business_path_and_open_opportunity(self) -> None:
        provider_id = self.register_party("测试受管企业", True)
        customer_id = self.register_party("测试客户", False)
        agent_id = self.register_party("测试招标代理", False)

        open_opportunity = self.apply_action(
            "create_opportunity",
            {
                "name": "暂未推进的商机",
                "operating_party_id": provider_id,
                "potential_customer_id": customer_id,
            },
        )
        self.created_object_id(open_opportunity, "opportunity")

        opportunity = self.apply_action(
            "create_opportunity",
            {
                "name": "进入招投标的商机",
                "operating_party_id": provider_id,
                "potential_customer_id": customer_id,
            },
        )
        opportunity_id = self.created_object_id(opportunity, "opportunity")
        tender = self.apply_action(
            "register_tender",
            {
                "name": "测试招标事项",
                "tenderer_id": customer_id,
                "tender_agent_id": agent_id,
            },
            opportunity_id,
        )
        tender_id = self.created_object_id(tender, "tender")
        bid = self.apply_action(
            "register_bid",
            {"name": "测试投标", "lead_bidder_id": provider_id},
            tender_id,
        )
        bid_id = self.created_object_id(bid, "bid")

        with self.assertRaisesRegex(ChangeValidationError, "只有中标"):
            self.registry.call(
                "preview_action",
                action_id="sign_framework_agreement",
                context_id=bid_id,
                inputs={
                    "name": "不应创建的协议",
                    "service_provider_id": provider_id,
                    "customer_id": customer_id,
                },
            )

        self.apply_action(
            "record_bid_result", {"bid_result": "awarded"}, bid_id
        )
        agreement = self.apply_action(
            "sign_framework_agreement",
            {
                "name": "测试框架协议",
                "service_provider_id": provider_id,
                "customer_id": customer_id,
            },
            bid_id,
        )
        agreement_id = self.created_object_id(agreement, "framework_agreement")

        with self.assertRaisesRegex(ChangeValidationError, "已经形成"):
            self.registry.call(
                "preview_action",
                action_id="sign_project_contract",
                context_id=bid_id,
                inputs={
                    "name": "不应创建的合同",
                    "service_provider_id": provider_id,
                    "customer_id": customer_id,
                },
            )

        order = self.apply_action(
            "issue_order", {"name": "测试订单"}, agreement_id
        )
        order_id = self.created_object_id(order, "order")
        personnel = self.apply_action("register_personnel", {"name": "测试工程师"})
        personnel_id = self.created_object_id(personnel, "personnel")
        self.apply_action(
            "allocate_personnel",
            {
                "resource_id": personnel_id,
                "quantity": 10,
                "unit": "person_day",
                "start_date": "2026-08-01",
                "end_date": "2026-08-10",
            },
            order_id,
        )
        self.apply_action(
            "register_intellectual_asset",
            {"name": "测试技术报告", "ip_role": "produced"},
            order_id,
        )
        invoice = self.apply_action(
            "issue_invoice",
            {
                "name": "测试发票",
                "amount": {"amount": 100, "currency": "CNY"},
                "issued_date": "2026-08-11",
            },
            order_id,
        )
        invoice_id = self.created_object_id(invoice, "invoice")
        receipt = self.apply_action(
            "record_receipt",
            {
                "name": "测试回款",
                "amount": {"amount": 100, "currency": "CNY"},
                "received_date": "2026-08-15",
                "settled_amount": {"amount": 60, "currency": "CNY"},
            },
            invoice_id,
        )
        receipt_id = self.created_object_id(receipt, "receipt")
        self.apply_action(
            "settle_receipt",
            {
                "invoice_id": invoice_id,
                "settled_amount": {"amount": 40, "currency": "CNY"},
            },
            receipt_id,
        )

        audit = audit_foxoms_records(
            self.repository.query("Object"), self.repository.query("Relation")
        )
        self.assertTrue(audit["valid"], audit["errors"])
        self.assertEqual(
            100, audit["settled_by_receipt"][receipt_id]
        )
        self.assertEqual(
            100, audit["settled_by_invoice"][invoice_id]
        )
        self.assertGreaterEqual(
            len(self.registry.get_resolver("uom_workspace").bootstrap()["recent_actions"]),
            15,
        )

    def test_invalid_business_inputs_are_rejected(self) -> None:
        managed_id = self.register_party("受管企业", True)
        external_id = self.register_party("外部企业", False)
        with self.assertRaisesRegex(ChangeValidationError, "经营方必须是受管"):
            self.registry.call(
                "preview_action",
                action_id="create_opportunity",
                inputs={
                    "name": "无效商机",
                    "operating_party_id": external_id,
                    "potential_customer_id": managed_id,
                },
            )

        opportunity = self.apply_action(
            "create_opportunity",
            {
                "name": "约束测试商机",
                "operating_party_id": managed_id,
                "potential_customer_id": external_id,
            },
        )
        opportunity_id = self.created_object_id(opportunity, "opportunity")
        tender = self.apply_action(
            "register_tender",
            {"name": "约束测试招标", "tenderer_id": external_id},
            opportunity_id,
        )
        tender_id = self.created_object_id(tender, "tender")
        bid = self.apply_action(
            "register_bid",
            {"name": "约束测试投标", "lead_bidder_id": managed_id},
            tender_id,
        )
        bid_id = self.created_object_id(bid, "bid")

        with self.assertRaisesRegex(ChangeValidationError, "只能是 awarded"):
            self.registry.call(
                "preview_action",
                action_id="record_bid_result",
                context_id=bid_id,
                inputs={"bid_result": "unknown"},
            )
        self.apply_action(
            "record_bid_result", {"bid_result": "not_awarded"}, bid_id
        )
        available = self.registry.call("get_available_actions", context_id=bid_id)
        signing = {
            action["id"]: action
            for action in available["actions"]
            if action["id"].startswith("sign_")
        }
        self.assertFalse(signing["sign_framework_agreement"]["executable"])
        self.assertFalse(signing["sign_project_contract"]["executable"])

        work_target = {
            "id": "order:allocation-test",
            "type": "order",
            "name": "投入约束测试订单",
        }
        resource = {
            "id": "personnel:allocation-test",
            "type": "personnel",
            "name": "投入约束测试人员",
        }
        self.repository.insert_record("Object", work_target)
        self.repository.insert_record("Object", resource)
        with self.assertRaisesRegex(ChangeValidationError, "不能早于"):
            self.registry.call(
                "preview_action",
                action_id="allocate_personnel",
                context_id=work_target["id"],
                inputs={
                    "resource_id": resource["id"],
                    "quantity": 1,
                    "unit": "person_day",
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-01",
                },
            )

    def test_project_contract_path_and_repeatable_participants(self) -> None:
        provider_id = self.register_party("项目服务企业", True)
        customer_id = self.register_party("项目客户", False)
        partner_id = self.register_party("项目合作伙伴", False)
        opportunity = self.apply_action(
            "create_opportunity",
            {
                "name": "项目合同路径商机",
                "operating_party_id": provider_id,
                "potential_customer_id": customer_id,
            },
        )
        opportunity_id = self.created_object_id(opportunity, "opportunity")
        tender = self.apply_action(
            "register_tender",
            {"name": "项目合同路径招标", "tenderer_id": customer_id},
            opportunity_id,
        )
        tender_id = self.created_object_id(tender, "tender")
        bid = self.apply_action(
            "register_bid",
            {"name": "项目合同路径投标", "lead_bidder_id": provider_id},
            tender_id,
        )
        bid_id = self.created_object_id(bid, "bid")
        self.apply_action(
            "add_business_participant",
            {"party_id": partner_id, "participation_role": "technical_partner"},
            bid_id,
        )
        with self.assertRaisesRegex(ChangeValidationError, "相同角色"):
            self.registry.call(
                "preview_action",
                action_id="add_business_participant",
                context_id=bid_id,
                inputs={
                    "party_id": partner_id,
                    "participation_role": "technical_partner",
                },
            )
        self.apply_action(
            "record_bid_result", {"bid_result": "awarded"}, bid_id
        )
        contract = self.apply_action(
            "sign_project_contract",
            {
                "name": "项目合同路径合同",
                "service_provider_id": provider_id,
                "customer_id": customer_id,
            },
            bid_id,
        )
        contract_id = self.created_object_id(contract, "contract")
        work_item = self.apply_action(
            "define_work_item", {"name": "项目合同路径任务"}, contract_id
        )
        work_item_id = self.created_object_id(work_item, "work_item")
        software = self.apply_action(
            "register_software_resource", {"name": "项目测试软件许可"}
        )
        hardware = self.apply_action(
            "register_hardware_resource", {"name": "项目测试设备"}
        )
        self.apply_action(
            "allocate_software",
            {
                "resource_id": self.created_object_id(software, "software_resource"),
                "quantity": 2,
                "unit": "license_month",
            },
            work_item_id,
        )
        self.apply_action(
            "allocate_hardware",
            {
                "resource_id": self.created_object_id(hardware, "hardware_resource"),
                "quantity": 1,
                "unit": "device_month",
            },
            work_item_id,
        )
        audit = audit_foxoms_records(
            self.repository.query("Object"), self.repository.query("Relation")
        )
        self.assertTrue(audit["valid"], audit["errors"])


if __name__ == "__main__":
    unittest.main()
