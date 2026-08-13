#!/usr/bin/env python3
"""Build or replace a deterministic financing lease example graph."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "oag-agent"))

from oag.ontology.loader import load_domain  # noqa: E402
from uom.validation import ModelValidator, load_yaml  # noqa: E402


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
CORE_ONTOLOGY = PROJECT_ROOT / "uom" / "ontology.yaml"


def money(amount: float) -> dict[str, Any]:
    return {"amount": amount, "currency": "CNY"}


def obj(object_id: str, object_type: str, name: str, **properties: Any) -> dict[str, Any]:
    return {"id": object_id, "type": object_type, "name": name, "properties": properties}


def rel(
    relation_id: str,
    relation_type: str,
    source: str,
    target: str,
    role: str = "",
    **properties: Any,
) -> dict[str, Any]:
    relation: dict[str, Any] = {
        "id": relation_id,
        "type": relation_type,
        "from": source,
        "to": target,
    }
    values = {**({"role": role} if role else {}), **properties}
    if values:
        relation["properties"] = values
    return relation


def build_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects = [
        obj("party:lessor", "party", "齐鲁融资租赁有限公司（示例）", category="lessor", code="QLFL", status="active"),
        obj("party:business", "party", "齐鲁融资租赁业务部（示例）", category="business_department", code="QLFL-BIZ", status="active"),
        obj("party:risk", "party", "齐鲁融资租赁风险部（示例）", category="risk_department", code="QLFL-RISK", status="active"),
        obj("customer:lessee", "customer", "济南智造有限公司（示例）", category="lessee", reference_no="CUST-001", status="active"),
        obj("customer:guarantor", "customer", "山东产业集团有限公司（示例）", category="guarantor", reference_no="CUST-002", status="active"),
        obj("credit:001", "credit", "综合授信 CR-2026-001", code="CR-2026-001", category="finance_lease", amount=money(12_000_000), valid_from="2026-01-01", valid_to="2027-12-31", status="active"),
        obj("credit_entry:reserve", "credit_entry", "项目方案额度预占", category="reserve", amount=money(10_000_000), occurred_on="2026-02-01", status="posted"),
        obj("credit_entry:convert", "credit_entry", "合同额度正式占用", category="convert_reserve_to_used", amount=money(10_000_000), occurred_on="2026-02-15", status="posted"),
        obj("lease_plan:001", "lease_plan", "智能产线融资租赁方案", reference_no="PLAN-2026-001", amount=money(10_000_000), occurred_on="2026-02-01", status="approved", details={"term_months": 36, "business_mode": "direct_lease"}),
        obj("contract:001", "contract", "智能产线融资租赁合同", reference_no="FL-2026-001", amount=money(10_000_000), occurred_on="2026-02-15", valid_from="2026-03-01", valid_to="2029-02-28", status="active"),
        obj("participation:lessee", "contract_participation", "承租方参与事实", role="lessee", status="active", valid_from="2026-02-15"),
        obj("participation:lessor", "contract_participation", "出租方参与事实", role="lessor", status="active", valid_from="2026-02-15"),
        obj("loan:001", "loan", "首笔设备款投放", reference_no="LOAN-2026-001", amount=money(10_000_000), occurred_on="2026-03-01", status="paid"),
        obj("schedule:v1", "schedule_version", "租金计划 V1", version="1", valid_from="2026-03-01", valid_to="2026-07-31", status="inactive", details={"term_count": 12, "annual_rate": 0.052}),
        obj("change:001", "change_order", "利率调整变更单", reference_no="CHG-2026-001", category="rate_adjustment", occurred_on="2026-07-20", status="effective", details={"annual_rate_before": 0.052, "annual_rate_after": 0.048}),
        obj("schedule:v2", "schedule_version", "租金计划 V2", version="2", valid_from="2026-08-01", status="active", details={"term_count": 10, "annual_rate": 0.048}),
        obj("receivable:001", "receivable", "第 1 期租金", sequence=1, category="rent", amount=money(900_000), due_on="2026-04-01", status="settled"),
        obj("receivable:002", "receivable", "第 2 期租金", sequence=2, category="rent", amount=money(900_000), due_on="2026-05-01", status="partial"),
        obj("penalty:002", "penalty", "第 2 期逾期罚息", amount=money(5_000), occurred_on="2026-05-15", rate=0.0005, status="open"),
        obj("payment:001", "payment", "租金到账 PAY-001", reference_no="PAY-2026-001", amount=money(1_000_000), occurred_on="2026-04-01", category="rent", status="allocated"),
        obj("payment:002", "payment", "待认领到账 PAY-002", reference_no="PAY-2026-002", amount=money(200_000), occurred_on="2026-05-03", category="unknown", status="unallocated"),
        obj("allocation:001", "allocation", "PAY-001 核销第 1 期", amount=money(900_000), occurred_on="2026-04-01", sequence=1, status="applied"),
        obj("allocation:002", "allocation", "PAY-001 核销第 2 期", amount=money(100_000), occurred_on="2026-04-01", sequence=2, status="applied"),
        obj("subject:line", "subject_matter", "智能生产线设备", category="equipment", code="SM-2026-001", amount=money(11_000_000), status="in_service", details={"location": "济南高新区", "model": "QL-INTELLIGENT-LINE"}),
        obj("guarantee:001", "guarantee", "集团保证担保", category="corporate_guarantee", amount=money(10_000_000), sequence=1, status="active"),
        obj("settlement:001", "settlement", "模拟部分提前结清", reference_no="SET-2026-001", category="partial_early", amount=money(1_500_000), occurred_on="2026-08-01", status="settled", details={"remaining_principal": 7_600_000}),
        obj("invoice:001", "invoice", "第 1 期租金发票", reference_no="INV-2026-001", amount=money(900_000), occurred_on="2026-04-02", status="issued", details={"tax_rate": 0.13}),
        obj("voucher:001", "voucher", "收款核销凭证", reference_no="V-2026-001", occurred_on="2026-04-01", period="2026-04", amount=money(1_000_000), status="posted"),
        obj("voucher_line:debit", "voucher_line", "银行存款借方", sequence=1, category="debit", amount=money(1_000_000), status="posted", details={"account": "银行存款"}),
        obj("voucher_line:credit", "voucher_line", "应收租赁款贷方", sequence=2, category="credit", amount=money(1_000_000), status="posted", details={"account": "应收融资租赁款"}),
        obj(
            "approval:contract",
            "approval",
            "合同审批申请",
            reference_no="APR-2026-001",
            category="contract_approval",
            occurred_on="2026-02-08",
            status="approved",
            details={
                "process": [
                    {"sequence": 1, "mode": "single", "role": "business_manager"},
                    {"sequence": 2, "mode": "all", "role": "risk_department"},
                    {"sequence": 3, "mode": "single", "role": "lessor_representative"},
                ],
                "history": [
                    {"sequence": 1, "decision": "approved", "occurred_on": "2026-02-08", "opinion": "业务方案完整"},
                    {"sequence": 2, "decision": "approved", "occurred_on": "2026-02-09", "opinion": "风险条件满足"},
                    {"sequence": 3, "decision": "approved", "occurred_on": "2026-02-10", "opinion": "同意签约"},
                ],
                "result": {"decision": "approved", "occurred_on": "2026-02-10", "summary": "同意签订融资租赁合同"},
            },
        ),
    ]
    relations = [
        rel("rel:credit-customer", "references", "credit:001", "customer:lessee", "granted_customer"),
        rel("rel:credit-entry", "contains", "credit:001", "credit_entry:reserve", "credit_entry"),
        rel("rel:entry-credit", "references", "credit_entry:reserve", "credit:001", "affected_credit"),
        rel("rel:entry-plan", "references", "credit_entry:reserve", "lease_plan:001", "source_plan"),
        rel("rel:credit-convert", "contains", "credit:001", "credit_entry:convert", "credit_entry"),
        rel("rel:convert-contract", "references", "credit_entry:convert", "contract:001", "source_contract"),
        rel("rel:plan-customer", "references", "lease_plan:001", "customer:lessee", "applicant"),
        rel("rel:plan-credit", "references", "lease_plan:001", "credit:001", "reserved_credit"),
        rel("rel:plan-contract", "derives", "lease_plan:001", "contract:001", "signed_contract"),
        rel("rel:contract-lessee-part", "contains", "contract:001", "participation:lessee", "contract_party"),
        rel("rel:contract-lessor-part", "contains", "contract:001", "participation:lessor", "contract_party"),
        rel("rel:lessee-part-customer", "references", "participation:lessee", "customer:lessee", "participant"),
        rel("rel:lessor-part-party", "references", "participation:lessor", "party:lessor", "participant"),
        rel("rel:contract-subject", "associates", "contract:001", "subject:line", "leased_subject", status="active"),
        rel("rel:contract-guarantee", "associates", "contract:001", "guarantee:001", "secured_by", status="active"),
        rel("rel:guarantee-guarantor", "associates", "guarantee:001", "customer:guarantor", "guarantor", status="active"),
        rel("rel:contract-loan", "derives", "contract:001", "loan:001", "loan"),
        rel("rel:contract-schedule-v1", "derives", "contract:001", "schedule:v1", "rent_schedule"),
        rel("rel:change-contract", "references", "change:001", "contract:001", "changed_contract"),
        rel("rel:change-schedule-v2", "derives", "change:001", "schedule:v2", "new_schedule"),
        rel("rel:schedule-v2-v1", "supersedes", "schedule:v2", "schedule:v1", reason="rate_adjustment", occurred_on="2026-08-01"),
        rel("rel:schedule-v1-rec1", "derives", "schedule:v1", "receivable:001", "schedule_receivable"),
        rel("rel:schedule-v1-rec2", "derives", "schedule:v1", "receivable:002", "schedule_receivable"),
        rel("rel:rec2-penalty", "derives", "receivable:002", "penalty:002", "late_penalty"),
        rel("rel:payment1-customer", "associates", "payment:001", "customer:lessee", "payer", status="confirmed"),
        rel("rel:payment2-customer", "associates", "payment:002", "customer:lessee", "payer", status="unclaimed"),
        rel("rel:payment1-allocation1", "derives", "payment:001", "allocation:001", "allocation", amount=money(900_000)),
        rel("rel:payment1-allocation2", "derives", "payment:001", "allocation:002", "allocation", amount=money(100_000)),
        rel("rel:allocation1-rec1", "references", "allocation:001", "receivable:001", "allocated_receivable"),
        rel("rel:allocation2-rec2", "references", "allocation:002", "receivable:002", "allocated_receivable"),
        rel("rel:contract-settlement", "derives", "contract:001", "settlement:001", "settlement"),
        rel("rel:rec1-invoice", "derives", "receivable:001", "invoice:001", "invoice"),
        rel("rel:voucher-contract", "references", "voucher:001", "contract:001", "accounting_source"),
        rel("rel:voucher-debit", "contains", "voucher:001", "voucher_line:debit", "entry"),
        rel("rel:voucher-credit", "contains", "voucher:001", "voucher_line:credit", "entry"),
        rel("rel:approval-contract", "references", "approval:contract", "contract:001", "reviewed_object"),
        rel("rel:approval-business", "associates", "approval:contract", "party:business", "submitted_by", status="completed", sequence=1, occurred_on="2026-02-08", details={"organization": "business_department"}),
        rel("rel:approval-risk", "associates", "approval:contract", "party:risk", "decided_by", status="approved", sequence=2, occurred_on="2026-02-09", reason="风险条件满足", details={"organization": "risk_department", "mode": "all"}),
        rel("rel:approval-lessor", "associates", "approval:contract", "party:lessor", "decided_by", status="approved", sequence=3, occurred_on="2026-02-10", reason="同意签约", details={"organization": "lessor_representative"}),
    ]
    return objects, relations


def validate_graph(objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> None:
    model = load_yaml(DOMAIN_ROOT / "model.yaml")
    result = ModelValidator(
        load_yaml(CORE_ONTOLOGY),
        {"schema": "uom.data.objects.v1", "objects": objects},
        {"schema": "uom.data.relations.v1", "relations": relations},
        model,
    ).validate()
    if result.errors:
        raise ValueError("\n".join(result.errors))
    missing_objects = set(model["object_types"]) - {item["type"] for item in objects}
    missing_relations = set(model["relation_types"]) - {item["type"] for item in relations}
    if missing_objects or missing_relations:
        raise ValueError(
            f"seed coverage missing object types={sorted(missing_objects)}, "
            f"relation types={sorted(missing_relations)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-clear", action="store_true")
    args = parser.parse_args()
    objects, relations = build_graph()
    validate_graph(objects, relations)
    print(f"Validated {len(objects)} objects and {len(relations)} relations")
    if not args.confirm_clear:
        print("Dry run only; pass --confirm-clear to replace the database")
        return 0
    _, repository, registry = load_domain(DOMAIN_ROOT)
    try:
        adapter = repository.adapter_for("Object")
        adapter.replace_graph(objects, relations)
        with sqlite3.connect(adapter.database_path) as connection:
            connection.execute("DELETE FROM action_log")
            connection.commit()
        consistency = registry.call("audit_finance_consistency")
        if not consistency["valid"]:
            raise ValueError("\n".join(consistency["errors"]))
    finally:
        repository.close()
    print(f"Seeded data into {DOMAIN_ROOT / 'data' / 'graph.db'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
