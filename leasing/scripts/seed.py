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
from leasing.business import audit_finance_records  # noqa: E402
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
        obj("lease_plan:001", "lease_plan", "智能产线融资租赁方案", reference_no="PLAN-2026-001", amount=money(10_000_000), occurred_on="2026-02-01", status="contracted", details={"term_months": 36, "business_mode": "direct_lease"}),
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
            "approval:plan:001",
            "approval",
            "项目方案审批申请",
            reference_no="APR-2026-001",
            category="lease_plan_approval",
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
        rel("rel:allocation1-rec1", "references", "allocation:001", "receivable:001", "allocated_target"),
        rel("rel:allocation2-rec2", "references", "allocation:002", "receivable:002", "allocated_target"),
        rel("rel:contract-settlement", "derives", "contract:001", "settlement:001", "settlement"),
        rel("rel:rec1-invoice", "derives", "receivable:001", "invoice:001", "invoice"),
        rel("rel:voucher-contract", "references", "voucher:001", "contract:001", "accounting_source"),
        rel("rel:voucher-debit", "contains", "voucher:001", "voucher_line:debit", "entry"),
        rel("rel:voucher-credit", "contains", "voucher:001", "voucher_line:credit", "entry"),
        rel("rel:approval-plan", "references", "approval:plan:001", "lease_plan:001", "reviewed_object"),
        rel("rel:approval-business", "associates", "approval:plan:001", "party:business", "submitted_by", status="completed", sequence=1, occurred_on="2026-02-08", details={"organization": "business_department"}),
        rel("rel:approval-risk", "associates", "approval:plan:001", "party:risk", "decided_by", status="approved", sequence=2, occurred_on="2026-02-09", reason="风险条件满足", details={"organization": "risk_department", "mode": "all"}),
        rel("rel:approval-lessor", "associates", "approval:plan:001", "party:lessor", "decided_by", status="approved", sequence=3, occurred_on="2026-02-10", reason="同意签约", details={"organization": "lessor_representative"}),
    ]
    _add_change_approval(objects, relations)
    _add_pending_plan_case(objects, relations)
    _add_rejected_plan_case(objects, relations)
    _add_yantai_active_case(objects, relations)
    _add_zibo_settled_case(objects, relations)
    objects.append(
        obj(
            "customer:inactive",
            "customer",
            "临沂旧城建设有限公司（已停用示例）",
            category="lessee",
            reference_no="CUST-099",
            status="inactive",
        )
    )
    return objects, relations


def approval_details(
    history: list[dict[str, Any]],
    decision: str,
    occurred_on: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {"decision": decision}
    if occurred_on:
        result["occurred_on"] = occurred_on
    if summary:
        result["summary"] = summary
    return {
        "process": [
            {"sequence": 1, "mode": "single", "role": "business_manager"},
            {"sequence": 2, "mode": "single", "role": "risk_department"},
            {"sequence": 3, "mode": "single", "role": "lessor_representative"},
        ],
        "history": history,
        "result": result,
    }


def _add_change_approval(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    objects.append(
        obj(
            "approval:change:001",
            "approval",
            "利率调整变更审批",
            reference_no="APR-CHG-2026-001",
            category="change_order_approval",
            occurred_on="2026-07-20",
            status="approved",
            details=approval_details(
                [
                    {"sequence": 1, "decision": "approved", "occurred_on": "2026-07-20", "opinion": "变更测算完整"},
                    {"sequence": 2, "decision": "approved", "occurred_on": "2026-07-21", "opinion": "风险可接受"},
                ],
                "approved",
                "2026-07-21",
                "同意利率调整并生成新租金计划版本",
            ),
        )
    )
    relations.extend([
        rel("rel:approval-change-object", "references", "approval:change:001", "change:001", "reviewed_object"),
        rel("rel:approval-change-submit", "associates", "approval:change:001", "party:business", "submitted_by", status="submitted", sequence=1, occurred_on="2026-07-20"),
        rel("rel:approval-change-risk", "associates", "approval:change:001", "party:risk", "decided_by", status="approved", sequence=2, occurred_on="2026-07-21", reason="风险可接受"),
    ])


def _add_pending_plan_case(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    objects.extend([
        obj("customer:qingdao", "customer", "青岛海湾医疗科技有限公司（示例）", category="lessee", reference_no="CUST-010", status="active"),
        obj("credit:qingdao", "credit", "青岛医疗设备授信", code="CR-2026-010", category="finance_lease", amount=money(6_000_000), valid_from="2026-05-01", valid_to="2027-04-30", status="active"),
        obj("credit_entry:qingdao:reserve", "credit_entry", "医疗设备方案额度预占", category="reserve", amount=money(4_000_000), occurred_on="2026-05-12", status="posted"),
        obj("lease_plan:qingdao", "lease_plan", "影像设备融资租赁方案（审批中）", reference_no="PLAN-2026-010", amount=money(4_000_000), occurred_on="2026-05-12", status="pending_approval", details={"term_months": 24, "business_mode": "direct_lease"}),
        obj(
            "approval:plan:qingdao",
            "approval",
            "影像设备方案审批",
            reference_no="APR-2026-010",
            category="lease_plan_approval",
            occurred_on="2026-05-13",
            status="pending",
            details=approval_details(
                [{"sequence": 1, "decision": "approved", "occurred_on": "2026-05-13", "opinion": "业务资料齐全"}],
                "pending",
            ),
        ),
    ])
    relations.extend([
        rel("rel:qingdao-credit-customer", "references", "credit:qingdao", "customer:qingdao", "granted_customer"),
        rel("rel:qingdao-credit-reserve", "contains", "credit:qingdao", "credit_entry:qingdao:reserve", "credit_entry"),
        rel("rel:qingdao-reserve-plan", "references", "credit_entry:qingdao:reserve", "lease_plan:qingdao", "source_plan"),
        rel("rel:qingdao-plan-customer", "references", "lease_plan:qingdao", "customer:qingdao", "applicant"),
        rel("rel:qingdao-plan-credit", "references", "lease_plan:qingdao", "credit:qingdao", "reserved_credit"),
        rel("rel:qingdao-approval-plan", "references", "approval:plan:qingdao", "lease_plan:qingdao", "reviewed_object"),
        rel("rel:qingdao-approval-submit", "associates", "approval:plan:qingdao", "party:business", "submitted_by", status="submitted", sequence=1, occurred_on="2026-05-13"),
        rel("rel:qingdao-approval-business", "associates", "approval:plan:qingdao", "party:business", "decided_by", status="approved", sequence=1, occurred_on="2026-05-13"),
    ])


def _add_rejected_plan_case(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    objects.extend([
        obj("customer:weifang", "customer", "潍坊陆港物流有限公司（示例）", category="lessee", reference_no="CUST-020", status="active"),
        obj("credit:weifang", "credit", "潍坊物流车辆授信", code="CR-2026-020", category="finance_lease", amount=money(8_000_000), valid_from="2026-03-01", valid_to="2027-02-28", status="active"),
        obj("credit_entry:weifang:reserve", "credit_entry", "物流车辆方案额度预占", category="reserve", amount=money(5_000_000), occurred_on="2026-03-05", status="posted"),
        obj("credit_entry:weifang:release", "credit_entry", "方案拒绝释放额度", category="release", amount=money(5_000_000), occurred_on="2026-03-09", status="posted", reason="方案审批未通过"),
        obj("lease_plan:weifang", "lease_plan", "新能源物流车融资租赁方案（已拒绝）", reference_no="PLAN-2026-020", amount=money(5_000_000), occurred_on="2026-03-05", status="rejected", details={"term_months": 36, "business_mode": "sale_and_leaseback"}),
        obj(
            "approval:plan:weifang",
            "approval",
            "物流车辆方案审批",
            reference_no="APR-2026-020",
            category="lease_plan_approval",
            occurred_on="2026-03-06",
            status="rejected",
            details=approval_details(
                [
                    {"sequence": 1, "decision": "approved", "occurred_on": "2026-03-06", "opinion": "业务条件基本满足"},
                    {"sequence": 2, "decision": "rejected", "occurred_on": "2026-03-09", "opinion": "现金流覆盖不足"},
                ],
                "rejected",
                "2026-03-09",
                "风险审查未通过",
            ),
        ),
    ])
    relations.extend([
        rel("rel:weifang-credit-customer", "references", "credit:weifang", "customer:weifang", "granted_customer"),
        rel("rel:weifang-credit-reserve", "contains", "credit:weifang", "credit_entry:weifang:reserve", "credit_entry"),
        rel("rel:weifang-credit-release", "contains", "credit:weifang", "credit_entry:weifang:release", "credit_entry"),
        rel("rel:weifang-reserve-plan", "references", "credit_entry:weifang:reserve", "lease_plan:weifang", "source_plan"),
        rel("rel:weifang-release-plan", "references", "credit_entry:weifang:release", "lease_plan:weifang", "source_plan"),
        rel("rel:weifang-plan-customer", "references", "lease_plan:weifang", "customer:weifang", "applicant"),
        rel("rel:weifang-plan-credit", "references", "lease_plan:weifang", "credit:weifang", "reserved_credit"),
        rel("rel:weifang-approval-plan", "references", "approval:plan:weifang", "lease_plan:weifang", "reviewed_object"),
        rel("rel:weifang-approval-submit", "associates", "approval:plan:weifang", "party:business", "submitted_by", status="submitted", sequence=1, occurred_on="2026-03-06"),
        rel("rel:weifang-approval-risk", "associates", "approval:plan:weifang", "party:risk", "decided_by", status="rejected", sequence=2, occurred_on="2026-03-09", reason="现金流覆盖不足"),
    ])


def _add_yantai_active_case(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    objects.extend([
        obj("customer:yantai", "customer", "烟台海工装备有限公司（示例）", category="lessee", reference_no="CUST-030", status="active"),
        obj("credit:yantai", "credit", "烟台海工装备授信", code="CR-2026-030", category="finance_lease", amount=money(9_000_000), valid_from="2026-01-01", valid_to="2027-12-31", status="active"),
        obj("credit_entry:yantai:reserve", "credit_entry", "海工装备方案额度预占", category="reserve", amount=money(7_200_000), occurred_on="2026-01-18", status="posted"),
        obj("credit_entry:yantai:convert", "credit_entry", "海工装备合同额度占用", category="convert_reserve_to_used", amount=money(7_200_000), occurred_on="2026-01-28", status="posted"),
        obj("lease_plan:yantai", "lease_plan", "海工检测设备融资租赁方案", reference_no="PLAN-2026-030", amount=money(7_200_000), occurred_on="2026-01-18", status="contracted", details={"term_months": 30, "business_mode": "sale_and_leaseback"}),
        obj(
            "approval:plan:yantai",
            "approval",
            "海工检测设备方案审批",
            reference_no="APR-2026-030",
            category="lease_plan_approval",
            occurred_on="2026-01-20",
            status="approved",
            details=approval_details(
                [
                    {"sequence": 1, "decision": "approved", "occurred_on": "2026-01-20", "opinion": "业务方案可行"},
                    {"sequence": 2, "decision": "approved", "occurred_on": "2026-01-22", "opinion": "风险缓释措施充分"},
                ],
                "approved",
                "2026-01-22",
                "同意签约",
            ),
        ),
        obj("contract:yantai", "contract", "海工检测设备融资租赁合同", reference_no="FL-2026-030", amount=money(7_200_000), occurred_on="2026-01-28", valid_from="2026-02-01", valid_to="2028-07-31", status="active"),
        obj("participation:yantai:lessee", "contract_participation", "烟台合同承租方参与事实", role="lessee", status="active", valid_from="2026-01-28"),
        obj("participation:yantai:lessor", "contract_participation", "烟台合同出租方参与事实", role="lessor", status="active", valid_from="2026-01-28"),
        obj("loan:yantai:001", "loan", "海工设备首笔放款", reference_no="LOAN-2026-030-01", amount=money(5_000_000), occurred_on="2026-02-01", status="paid"),
        obj("loan:yantai:002", "loan", "海工设备尾款投放", reference_no="LOAN-2026-030-02", amount=money(2_200_000), occurred_on="2026-02-10", status="paid"),
        obj("schedule:yantai:v1", "schedule_version", "烟台合同租金计划 V1", version="1", valid_from="2026-02-01", status="active", details={"term_count": 30, "annual_rate": 0.049}),
        obj("receivable:yantai:001", "receivable", "烟台合同第 1 期租金", sequence=1, category="rent", amount=money(400_000), due_on="2026-03-01", status="settled"),
        obj("receivable:yantai:002", "receivable", "烟台合同第 2 期租金", sequence=2, category="rent", amount=money(400_000), due_on="2026-04-01", status="settled"),
        obj("receivable:yantai:003", "receivable", "烟台合同第 3 期租金", sequence=3, category="rent", amount=money(400_000), due_on="2026-05-01", status="partial"),
        obj("penalty:yantai:003", "penalty", "烟台合同第 3 期罚息", amount=money(10_000), occurred_on="2026-05-15", rate=0.0005, status="partial"),
        obj("payment:yantai:001", "payment", "烟台租金到账 PAY-001", reference_no="PAY-2026-030-01", amount=money(550_000), occurred_on="2026-03-01", category="rent", status="allocated"),
        obj("payment:yantai:002", "payment", "烟台租金到账 PAY-002", reference_no="PAY-2026-030-02", amount=money(355_000), occurred_on="2026-05-20", category="rent_and_penalty", status="allocated"),
        obj("allocation:yantai:001", "allocation", "烟台 PAY-001 核销第 1 期", amount=money(400_000), occurred_on="2026-03-01", sequence=1, status="applied"),
        obj("allocation:yantai:002", "allocation", "烟台 PAY-001 核销第 2 期之一", amount=money(150_000), occurred_on="2026-03-01", sequence=2, status="applied"),
        obj("allocation:yantai:003", "allocation", "烟台 PAY-002 核销第 2 期之二", amount=money(250_000), occurred_on="2026-05-20", sequence=1, status="applied"),
        obj("allocation:yantai:004", "allocation", "烟台 PAY-002 核销第 3 期", amount=money(100_000), occurred_on="2026-05-20", sequence=2, status="applied"),
        obj("allocation:yantai:005", "allocation", "烟台 PAY-002 核销罚息", amount=money(5_000), occurred_on="2026-05-20", sequence=3, status="applied"),
        obj("subject:yantai", "subject_matter", "海工无损检测设备", category="equipment", code="SM-2026-030", amount=money(8_100_000), status="in_service", details={"location": "烟台开发区", "model": "NDT-6000"}),
        obj("guarantee:yantai", "guarantee", "烟台海工集团保证担保", category="corporate_guarantee", amount=money(7_200_000), sequence=1, status="active"),
        obj("invoice:yantai:001", "invoice", "烟台第 1 期租金发票", reference_no="INV-2026-030-01", amount=money(400_000), occurred_on="2026-03-02", status="issued", details={"tax_rate": 0.13}),
    ])
    relations.extend([
        rel("rel:yantai-credit-customer", "references", "credit:yantai", "customer:yantai", "granted_customer"),
        rel("rel:yantai-credit-reserve", "contains", "credit:yantai", "credit_entry:yantai:reserve", "credit_entry"),
        rel("rel:yantai-credit-convert", "contains", "credit:yantai", "credit_entry:yantai:convert", "credit_entry"),
        rel("rel:yantai-reserve-plan", "references", "credit_entry:yantai:reserve", "lease_plan:yantai", "source_plan"),
        rel("rel:yantai-convert-contract", "references", "credit_entry:yantai:convert", "contract:yantai", "source_contract"),
        rel("rel:yantai-plan-customer", "references", "lease_plan:yantai", "customer:yantai", "applicant"),
        rel("rel:yantai-plan-credit", "references", "lease_plan:yantai", "credit:yantai", "reserved_credit"),
        rel("rel:yantai-approval-plan", "references", "approval:plan:yantai", "lease_plan:yantai", "reviewed_object"),
        rel("rel:yantai-approval-submit", "associates", "approval:plan:yantai", "party:business", "submitted_by", status="submitted", sequence=1, occurred_on="2026-01-20"),
        rel("rel:yantai-approval-risk", "associates", "approval:plan:yantai", "party:risk", "decided_by", status="approved", sequence=2, occurred_on="2026-01-22"),
        rel("rel:yantai-plan-contract", "derives", "lease_plan:yantai", "contract:yantai", "signed_contract"),
        rel("rel:yantai-contract-lessee", "contains", "contract:yantai", "participation:yantai:lessee", "contract_party"),
        rel("rel:yantai-contract-lessor", "contains", "contract:yantai", "participation:yantai:lessor", "contract_party"),
        rel("rel:yantai-lessee-customer", "references", "participation:yantai:lessee", "customer:yantai", "participant"),
        rel("rel:yantai-lessor-party", "references", "participation:yantai:lessor", "party:lessor", "participant"),
        rel("rel:yantai-contract-loan1", "derives", "contract:yantai", "loan:yantai:001", "loan"),
        rel("rel:yantai-contract-loan2", "derives", "contract:yantai", "loan:yantai:002", "loan"),
        rel("rel:yantai-contract-schedule", "derives", "contract:yantai", "schedule:yantai:v1", "rent_schedule"),
        rel("rel:yantai-schedule-rec1", "derives", "schedule:yantai:v1", "receivable:yantai:001", "schedule_receivable"),
        rel("rel:yantai-schedule-rec2", "derives", "schedule:yantai:v1", "receivable:yantai:002", "schedule_receivable"),
        rel("rel:yantai-schedule-rec3", "derives", "schedule:yantai:v1", "receivable:yantai:003", "schedule_receivable"),
        rel("rel:yantai-rec3-penalty", "derives", "receivable:yantai:003", "penalty:yantai:003", "late_penalty"),
        rel("rel:yantai-payment1-customer", "associates", "payment:yantai:001", "customer:yantai", "payer", status="confirmed"),
        rel("rel:yantai-payment2-customer", "associates", "payment:yantai:002", "customer:yantai", "payer", status="confirmed"),
        rel("rel:yantai-payment1-contract", "associates", "payment:yantai:001", "contract:yantai", "intended_contract", status="confirmed"),
        rel("rel:yantai-payment2-contract", "associates", "payment:yantai:002", "contract:yantai", "intended_contract", status="confirmed"),
        rel("rel:yantai-payment1-allocation1", "derives", "payment:yantai:001", "allocation:yantai:001", "allocation"),
        rel("rel:yantai-payment1-allocation2", "derives", "payment:yantai:001", "allocation:yantai:002", "allocation"),
        rel("rel:yantai-payment2-allocation3", "derives", "payment:yantai:002", "allocation:yantai:003", "allocation"),
        rel("rel:yantai-payment2-allocation4", "derives", "payment:yantai:002", "allocation:yantai:004", "allocation"),
        rel("rel:yantai-payment2-allocation5", "derives", "payment:yantai:002", "allocation:yantai:005", "allocation"),
        rel("rel:yantai-allocation1-rec1", "references", "allocation:yantai:001", "receivable:yantai:001", "allocated_target"),
        rel("rel:yantai-allocation2-rec2", "references", "allocation:yantai:002", "receivable:yantai:002", "allocated_target"),
        rel("rel:yantai-allocation3-rec2", "references", "allocation:yantai:003", "receivable:yantai:002", "allocated_target"),
        rel("rel:yantai-allocation4-rec3", "references", "allocation:yantai:004", "receivable:yantai:003", "allocated_target"),
        rel("rel:yantai-allocation5-penalty", "references", "allocation:yantai:005", "penalty:yantai:003", "allocated_target"),
        rel("rel:yantai-contract-subject", "associates", "contract:yantai", "subject:yantai", "leased_subject", status="active"),
        rel("rel:yantai-contract-guarantee", "associates", "contract:yantai", "guarantee:yantai", "secured_by", status="active"),
        rel("rel:yantai-guarantee-guarantor", "associates", "guarantee:yantai", "customer:guarantor", "guarantor", status="active"),
        rel("rel:yantai-rec1-invoice", "derives", "receivable:yantai:001", "invoice:yantai:001", "invoice"),
    ])


def _add_zibo_settled_case(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    objects.extend([
        obj("customer:zibo", "customer", "淄博绿色材料有限公司（示例）", category="lessee", reference_no="CUST-040", status="active"),
        obj("credit:zibo", "credit", "淄博节能设备授信", code="CR-2025-040", category="finance_lease", amount=money(3_000_000), valid_from="2025-01-01", valid_to="2026-12-31", status="active"),
        obj("credit_entry:zibo:reserve", "credit_entry", "节能设备方案额度预占", category="reserve", amount=money(2_000_000), occurred_on="2025-01-08", status="posted"),
        obj("credit_entry:zibo:convert", "credit_entry", "节能设备合同额度占用", category="convert_reserve_to_used", amount=money(2_000_000), occurred_on="2025-01-20", status="posted"),
        obj("credit_entry:zibo:reverse", "credit_entry", "合同结清释放已用额度", category="reverse_occupy", amount=money(2_000_000), occurred_on="2026-01-31", status="posted", reason="合同到期结清"),
        obj("lease_plan:zibo", "lease_plan", "节能窑炉融资租赁方案", reference_no="PLAN-2025-040", amount=money(2_000_000), occurred_on="2025-01-08", status="contracted", details={"term_months": 12, "business_mode": "direct_lease"}),
        obj("approval:plan:zibo", "approval", "节能窑炉方案审批", reference_no="APR-2025-040", category="lease_plan_approval", occurred_on="2025-01-10", status="approved", details=approval_details([{"sequence": 1, "decision": "approved", "occurred_on": "2025-01-10", "opinion": "项目现金流稳定"}], "approved", "2025-01-10", "同意签约")),
        obj("contract:zibo", "contract", "节能窑炉融资租赁合同（已结清）", reference_no="FL-2025-040", amount=money(2_000_000), occurred_on="2025-01-20", valid_from="2025-02-01", valid_to="2026-01-31", status="settled"),
        obj("participation:zibo:lessee", "contract_participation", "淄博合同承租方参与事实", role="lessee", status="inactive", valid_from="2025-01-20", valid_to="2026-01-31"),
        obj("participation:zibo:lessor", "contract_participation", "淄博合同出租方参与事实", role="lessor", status="inactive", valid_from="2025-01-20", valid_to="2026-01-31"),
        obj("loan:zibo", "loan", "节能窑炉设备款投放", reference_no="LOAN-2025-040", amount=money(2_000_000), occurred_on="2025-02-01", status="paid"),
        obj("schedule:zibo:v1", "schedule_version", "淄博合同租金计划 V1", version="1", valid_from="2025-02-01", status="inactive", details={"term_count": 12, "annual_rate": 0.046}),
        obj("receivable:zibo:final", "receivable", "淄博合同尾期租金", sequence=12, category="rent", amount=money(180_000), due_on="2026-01-20", status="settled"),
        obj("payment:zibo:final", "payment", "淄博合同尾款到账", reference_no="PAY-2026-040", amount=money(180_000), occurred_on="2026-01-20", category="rent", status="allocated"),
        obj("allocation:zibo:final", "allocation", "淄博尾款核销", amount=money(180_000), occurred_on="2026-01-20", sequence=1, status="applied"),
        obj("settlement:zibo", "settlement", "淄博合同到期结清", reference_no="SET-2026-040", category="maturity", amount=money(2_000_000), occurred_on="2026-01-31", status="settled", details={"remaining_principal": 0, "unpaid_amount": 0}),
        obj("subject:zibo", "subject_matter", "节能窑炉成套设备", category="equipment", code="SM-2025-040", amount=money(2_300_000), status="lease_completed", details={"location": "淄博高新区", "ownership_disposition": "transferred_to_lessee"}),
        obj("voucher:zibo", "voucher", "淄博合同结清凭证", reference_no="V-2026-040", occurred_on="2026-01-31", period="2026-01", amount=money(180_000), status="posted"),
        obj("voucher_line:zibo:debit", "voucher_line", "银行存款借方（淄博）", sequence=1, category="debit", amount=money(180_000), status="posted", details={"account": "银行存款"}),
        obj("voucher_line:zibo:credit", "voucher_line", "长期应收款贷方（淄博）", sequence=2, category="credit", amount=money(180_000), status="posted", details={"account": "长期应收款"}),
    ])
    relations.extend([
        rel("rel:zibo-credit-customer", "references", "credit:zibo", "customer:zibo", "granted_customer"),
        rel("rel:zibo-credit-reserve", "contains", "credit:zibo", "credit_entry:zibo:reserve", "credit_entry"),
        rel("rel:zibo-credit-convert", "contains", "credit:zibo", "credit_entry:zibo:convert", "credit_entry"),
        rel("rel:zibo-credit-reverse", "contains", "credit:zibo", "credit_entry:zibo:reverse", "credit_entry"),
        rel("rel:zibo-reserve-plan", "references", "credit_entry:zibo:reserve", "lease_plan:zibo", "source_plan"),
        rel("rel:zibo-convert-contract", "references", "credit_entry:zibo:convert", "contract:zibo", "source_contract"),
        rel("rel:zibo-plan-customer", "references", "lease_plan:zibo", "customer:zibo", "applicant"),
        rel("rel:zibo-plan-credit", "references", "lease_plan:zibo", "credit:zibo", "reserved_credit"),
        rel("rel:zibo-approval-plan", "references", "approval:plan:zibo", "lease_plan:zibo", "reviewed_object"),
        rel("rel:zibo-approval-submit", "associates", "approval:plan:zibo", "party:business", "submitted_by", status="submitted", sequence=1, occurred_on="2025-01-10"),
        rel("rel:zibo-approval-risk", "associates", "approval:plan:zibo", "party:risk", "decided_by", status="approved", sequence=1, occurred_on="2025-01-10"),
        rel("rel:zibo-plan-contract", "derives", "lease_plan:zibo", "contract:zibo", "signed_contract"),
        rel("rel:zibo-contract-lessee", "contains", "contract:zibo", "participation:zibo:lessee", "contract_party"),
        rel("rel:zibo-contract-lessor", "contains", "contract:zibo", "participation:zibo:lessor", "contract_party"),
        rel("rel:zibo-lessee-customer", "references", "participation:zibo:lessee", "customer:zibo", "participant"),
        rel("rel:zibo-lessor-party", "references", "participation:zibo:lessor", "party:lessor", "participant"),
        rel("rel:zibo-contract-loan", "derives", "contract:zibo", "loan:zibo", "loan"),
        rel("rel:zibo-contract-schedule", "derives", "contract:zibo", "schedule:zibo:v1", "rent_schedule"),
        rel("rel:zibo-schedule-receivable", "derives", "schedule:zibo:v1", "receivable:zibo:final", "schedule_receivable"),
        rel("rel:zibo-payment-customer", "associates", "payment:zibo:final", "customer:zibo", "payer", status="confirmed"),
        rel("rel:zibo-payment-contract", "associates", "payment:zibo:final", "contract:zibo", "intended_contract", status="confirmed"),
        rel("rel:zibo-payment-allocation", "derives", "payment:zibo:final", "allocation:zibo:final", "allocation"),
        rel("rel:zibo-allocation-receivable", "references", "allocation:zibo:final", "receivable:zibo:final", "allocated_target"),
        rel("rel:zibo-contract-settlement", "derives", "contract:zibo", "settlement:zibo", "settlement"),
        rel("rel:zibo-reverse-settlement", "references", "credit_entry:zibo:reverse", "settlement:zibo", "source_settlement"),
        rel("rel:zibo-contract-subject", "associates", "contract:zibo", "subject:zibo", "leased_subject", status="completed"),
        rel("rel:zibo-voucher-contract", "references", "voucher:zibo", "contract:zibo", "accounting_source"),
        rel("rel:zibo-voucher-debit", "contains", "voucher:zibo", "voucher_line:zibo:debit", "entry"),
        rel("rel:zibo-voucher-credit", "contains", "voucher:zibo", "voucher_line:zibo:credit", "entry"),
    ])


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
    consistency = audit_finance_records(objects, relations)
    if not consistency["valid"]:
        raise ValueError("\n".join(consistency["errors"]))


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
