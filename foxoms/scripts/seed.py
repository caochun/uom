#!/usr/bin/env python3
"""Build or replace a deterministic FoxOMS example graph."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "oag-agent"))

from foxoms.business import audit_foxoms_records  # noqa: E402
from uom.loader import load_domain  # noqa: E402
from uom.model import (  # noqa: E402
    load_action_plans,
    load_public_ontology,
    storage_contract_payload,
    workspace_model,
)
from uom.validation import ModelValidator  # noqa: E402

DOMAIN_ROOT = Path(__file__).resolve().parents[1]


def money(amount: float) -> dict[str, Any]:
    return {"amount": amount, "currency": "CNY"}


def obj(
    object_id: str,
    object_type: str,
    name: str,
    **properties: Any,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "type": object_type,
        "name": name,
        "properties": properties,
    }


def rel(
    relation_id: str,
    relation_type: str,
    source: str,
    target: str,
    **properties: Any,
) -> dict[str, Any]:
    relation: dict[str, Any] = {
        "id": relation_id,
        "type": relation_type,
        "from": source,
        "to": target,
    }
    if properties:
        relation["properties"] = properties
    return relation


def build_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects = [
        obj("party:qilu_digital", "party", "齐鲁数智服务有限公司（Mock）", is_managed=True),
        obj("party:haidai_cloud", "party", "海岱云创科技有限公司（Mock）", is_managed=True),
        obj("party:jinan_city", "party", "济南新城发展有限公司（Mock）", is_managed=False),
        obj("party:qingdao_industry", "party", "青岛智造产业有限公司（Mock）", is_managed=False),
        obj("party:taishan_partner", "party", "泰山系统集成有限公司（Mock）", is_managed=False),
        obj("party:bid_agency", "party", "山东正采招标代理有限公司（Mock）", is_managed=False),
        obj("party:competitor", "party", "鲁中信息技术有限公司（Mock）", is_managed=False),
        obj("party:weifang_customer", "party", "潍坊绿色能源有限公司（Mock）", is_managed=False),
        obj("opportunity:park_ops", "opportunity", "济南智慧园区运营服务商机"),
        obj("opportunity:factory_data", "opportunity", "青岛工业数据平台建设商机"),
        obj("opportunity:energy_advisory", "opportunity", "潍坊能源管理咨询商机"),
        obj("tender:park_ops", "tender", "济南智慧园区运营服务招标"),
        obj("tender:factory_data", "tender", "青岛工业数据平台建设招标"),
        obj("bid:park_joint", "bid", "智慧园区联合投标", bid_result="awarded"),
        obj("bid:park_competitor", "bid", "智慧园区竞争投标", bid_result="not_awarded"),
        obj("bid:factory_data", "bid", "工业数据平台项目投标", bid_result="awarded"),
        obj("framework:park_ops", "framework_agreement", "智慧园区运营服务框架协议"),
        obj("contract:factory_data", "contract", "工业数据平台建设项目合同"),
        obj("order:park_inspection", "order", "园区智能巡检服务订单"),
        obj("order:park_optimization", "order", "园区能耗优化服务订单"),
        obj("work_item:data_platform", "work_item", "工业数据平台建设项目"),
        obj("work_item:predictive_maintenance", "work_item", "设备预测性维护任务"),
        obj("personnel:wang_lei", "personnel", "王磊（项目经理，Mock）"),
        obj("personnel:delivery_team", "personnel", "智慧园区交付组（Mock）"),
        obj("personnel:data_team", "personnel", "工业数据实施组（Mock）"),
        obj("software:workflow", "software_resource", "流程编排平台许可（Mock）"),
        obj("software:digital_twin", "software_resource", "工业数字孪生平台许可（Mock）"),
        obj("hardware:edge_cluster", "hardware_resource", "边缘计算服务器组（Mock）"),
        obj("hardware:inspection_tablets", "hardware_resource", "巡检平板设备组（Mock）"),
        obj("ip:park_patent", "intellectual_asset", "园区设备协同控制专利（Mock）"),
        obj("ip:park_report", "intellectual_asset", "智慧园区能耗优化技术报告（Mock）"),
        obj("ip:data_copyright", "intellectual_asset", "工业数据治理平台软著（Mock）"),
        obj("ip:maintenance_paper", "intellectual_asset", "设备预测性维护方法论文（Mock）"),
        obj(
            "invoice:park:001",
            "invoice",
            "园区巡检服务首期发票",
            amount=money(120_000),
            issued_date="2026-04-08",
        ),
        obj(
            "invoice:park:002",
            "invoice",
            "园区巡检服务验收发票",
            amount=money(180_000),
            issued_date="2026-06-18",
        ),
        obj(
            "invoice:park:003",
            "invoice",
            "园区能耗优化服务发票",
            amount=money(200_000),
            issued_date="2026-07-05",
        ),
        obj(
            "invoice:factory:001",
            "invoice",
            "工业数据平台预付款发票",
            amount=money(300_000),
            issued_date="2026-05-12",
        ),
        obj(
            "invoice:factory:002",
            "invoice",
            "工业数据平台进度发票",
            amount=money(400_000),
            issued_date="2026-07-20",
        ),
        obj(
            "receipt:park:001",
            "receipt",
            "园区服务首笔回款",
            amount=money(100_000),
            received_date="2026-04-25",
        ),
        obj(
            "receipt:park:002",
            "receipt",
            "园区服务第二笔回款",
            amount=money(220_000),
            received_date="2026-06-30",
        ),
        obj(
            "receipt:park:003",
            "receipt",
            "园区服务第三笔回款",
            amount=money(180_000),
            received_date="2026-07-28",
        ),
        obj(
            "receipt:factory:001",
            "receipt",
            "工业数据平台首笔回款",
            amount=money(500_000),
            received_date="2026-06-10",
        ),
        obj(
            "receipt:factory:002",
            "receipt",
            "工业数据平台第二笔回款",
            amount=money(150_000),
            received_date="2026-08-05",
        ),
    ]

    relations = [
        rel("rel:opp_park:operator", "participates_in", "party:qilu_digital", "opportunity:park_ops", participation_role="operating_party"),
        rel("rel:opp_park:customer", "participates_in", "party:jinan_city", "opportunity:park_ops", participation_role="potential_customer"),
        rel("rel:opp_park:referrer", "participates_in", "party:taishan_partner", "opportunity:park_ops", participation_role="referrer"),
        rel("rel:opp_factory:operator", "participates_in", "party:haidai_cloud", "opportunity:factory_data", participation_role="operating_party"),
        rel("rel:opp_factory:customer", "participates_in", "party:qingdao_industry", "opportunity:factory_data", participation_role="potential_customer"),
        rel("rel:opp_energy:operator", "participates_in", "party:qilu_digital", "opportunity:energy_advisory", participation_role="operating_party"),
        rel("rel:opp_energy:customer", "participates_in", "party:weifang_customer", "opportunity:energy_advisory", participation_role="potential_customer"),
        rel("rel:tender_park:tenderer", "participates_in", "party:jinan_city", "tender:park_ops", participation_role="tenderer"),
        rel("rel:tender_park:agency", "participates_in", "party:bid_agency", "tender:park_ops", participation_role="tender_agent"),
        rel("rel:bid_park:lead", "participates_in", "party:qilu_digital", "bid:park_joint", participation_role="lead_bidder"),
        rel("rel:bid_park:member", "participates_in", "party:taishan_partner", "bid:park_joint", participation_role="consortium_member"),
        rel("rel:bid_park_competitor:bidder", "participates_in", "party:competitor", "bid:park_competitor", participation_role="lead_bidder"),
        rel("rel:framework_park:provider", "participates_in", "party:qilu_digital", "framework:park_ops", participation_role="service_provider"),
        rel("rel:framework_park:customer", "participates_in", "party:jinan_city", "framework:park_ops", participation_role="customer"),
        rel("rel:order_inspection:provider", "participates_in", "party:qilu_digital", "order:park_inspection", participation_role="service_provider"),
        rel("rel:order_inspection:customer", "participates_in", "party:jinan_city", "order:park_inspection", participation_role="customer"),
        rel("rel:order_optimization:provider", "participates_in", "party:qilu_digital", "order:park_optimization", participation_role="service_provider"),
        rel("rel:order_optimization:customer", "participates_in", "party:jinan_city", "order:park_optimization", participation_role="customer"),
        rel("rel:tender_factory:tenderer", "participates_in", "party:qingdao_industry", "tender:factory_data", participation_role="tenderer"),
        rel("rel:bid_factory:lead", "participates_in", "party:haidai_cloud", "bid:factory_data", participation_role="lead_bidder"),
        rel("rel:bid_factory:partner", "participates_in", "party:taishan_partner", "bid:factory_data", participation_role="technical_partner"),
        rel("rel:contract_factory:provider", "participates_in", "party:haidai_cloud", "contract:factory_data", participation_role="service_provider"),
        rel("rel:contract_factory:customer", "participates_in", "party:qingdao_industry", "contract:factory_data", participation_role="customer"),
        rel("rel:work_platform:provider", "participates_in", "party:haidai_cloud", "work_item:data_platform", participation_role="executing_party"),
        rel("rel:work_platform:customer", "participates_in", "party:qingdao_industry", "work_item:data_platform", participation_role="customer"),
        rel("rel:work_maintenance:provider", "participates_in", "party:haidai_cloud", "work_item:predictive_maintenance", participation_role="executing_party"),
        rel("rel:work_maintenance:customer", "participates_in", "party:qingdao_industry", "work_item:predictive_maintenance", participation_role="customer"),
        rel("rel:opp_park:tender", "contains", "opportunity:park_ops", "tender:park_ops"),
        rel("rel:tender_park:joint_bid", "contains", "tender:park_ops", "bid:park_joint"),
        rel("rel:tender_park:competitor_bid", "contains", "tender:park_ops", "bid:park_competitor"),
        rel("rel:opp_factory:tender", "contains", "opportunity:factory_data", "tender:factory_data"),
        rel("rel:tender_factory:bid", "contains", "tender:factory_data", "bid:factory_data"),
        rel("rel:framework_park:inspection_order", "contains", "framework:park_ops", "order:park_inspection"),
        rel("rel:framework_park:optimization_order", "contains", "framework:park_ops", "order:park_optimization"),
        rel("rel:contract_factory:data_platform", "contains", "contract:factory_data", "work_item:data_platform"),
        rel("rel:contract_factory:maintenance", "contains", "contract:factory_data", "work_item:predictive_maintenance"),
        rel("rel:order_inspection:invoice_001", "contains", "order:park_inspection", "invoice:park:001"),
        rel("rel:order_inspection:invoice_002", "contains", "order:park_inspection", "invoice:park:002"),
        rel("rel:order_optimization:invoice_003", "contains", "order:park_optimization", "invoice:park:003"),
        rel("rel:contract_factory:invoice_001", "contains", "contract:factory_data", "invoice:factory:001"),
        rel("rel:contract_factory:invoice_002", "contains", "contract:factory_data", "invoice:factory:002"),
        rel("rel:bid_park:framework", "derives", "bid:park_joint", "framework:park_ops"),
        rel("rel:bid_factory:contract", "derives", "bid:factory_data", "contract:factory_data"),
        rel("rel:wang:inspection", "allocated_to", "personnel:wang_lei", "order:park_inspection", quantity=45, unit="person_day", start_date="2026-03-15", end_date="2026-05-31"),
        rel("rel:delivery_team:inspection", "allocated_to", "personnel:delivery_team", "order:park_inspection", quantity=180, unit="person_day", start_date="2026-03-20", end_date="2026-06-15"),
        rel("rel:workflow:inspection", "allocated_to", "software:workflow", "order:park_inspection", quantity=6, unit="license_month", start_date="2026-03-15", end_date="2026-09-14"),
        rel("rel:edge:optimization", "allocated_to", "hardware:edge_cluster", "order:park_optimization", quantity=4, unit="device_month", start_date="2026-06-01", end_date="2026-09-30"),
        rel("rel:wang:data_platform", "allocated_to", "personnel:wang_lei", "work_item:data_platform", quantity=30, unit="person_day", start_date="2026-06-01", end_date="2026-07-31"),
        rel("rel:data_team:data_platform", "allocated_to", "personnel:data_team", "work_item:data_platform", quantity=240, unit="person_day", start_date="2026-05-20", end_date="2026-09-30"),
        rel("rel:digital_twin:data_platform", "allocated_to", "software:digital_twin", "work_item:data_platform", quantity=12, unit="license_month", start_date="2026-05-20", end_date="2027-05-19"),
        rel("rel:edge:data_platform", "allocated_to", "hardware:edge_cluster", "work_item:data_platform", quantity=6, unit="device_month", start_date="2026-05-20", end_date="2026-11-19"),
        rel("rel:workflow:maintenance", "allocated_to", "software:workflow", "work_item:predictive_maintenance", quantity=4, unit="license_month", start_date="2026-07-01", end_date="2026-10-31"),
        rel("rel:tablets:maintenance", "allocated_to", "hardware:inspection_tablets", "work_item:predictive_maintenance", quantity=10, unit="device_month", start_date="2026-07-01", end_date="2026-10-31"),
        rel("rel:inspection:park_patent", "involves_ip", "order:park_inspection", "ip:park_patent", ip_role="required"),
        rel("rel:optimization:park_report", "involves_ip", "order:park_optimization", "ip:park_report", ip_role="produced"),
        rel("rel:data_platform:copyright", "involves_ip", "work_item:data_platform", "ip:data_copyright", ip_role="required"),
        rel("rel:maintenance:paper", "involves_ip", "work_item:predictive_maintenance", "ip:maintenance_paper", ip_role="produced"),
        rel("rel:receipt_park_001:invoice_001", "settles", "receipt:park:001", "invoice:park:001", settled_amount=money(100_000)),
        rel("rel:receipt_park_002:invoice_001", "settles", "receipt:park:002", "invoice:park:001", settled_amount=money(20_000)),
        rel("rel:receipt_park_002:invoice_002", "settles", "receipt:park:002", "invoice:park:002", settled_amount=money(180_000)),
        rel("rel:receipt_park_002:invoice_003", "settles", "receipt:park:002", "invoice:park:003", settled_amount=money(20_000)),
        rel("rel:receipt_park_003:invoice_003", "settles", "receipt:park:003", "invoice:park:003", settled_amount=money(180_000)),
        rel("rel:receipt_factory_001:invoice_001", "settles", "receipt:factory:001", "invoice:factory:001", settled_amount=money(300_000)),
        rel("rel:receipt_factory_001:invoice_002", "settles", "receipt:factory:001", "invoice:factory:002", settled_amount=money(200_000)),
        rel("rel:receipt_factory_002:invoice_002", "settles", "receipt:factory:002", "invoice:factory:002", settled_amount=money(150_000)),
    ]
    return objects, relations


def validate_business_rules(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    audit = audit_foxoms_records(objects, relations)
    if not audit["valid"]:
        raise ValueError("\n".join(audit["errors"]))


def validate_graph(
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    public_model, _ = load_public_ontology(DOMAIN_ROOT)
    model = workspace_model(public_model, load_action_plans(DOMAIN_ROOT))
    result = ModelValidator(
        storage_contract_payload(),
        {"schema": "uom.data.objects.v1", "objects": objects},
        {"schema": "uom.data.relations.v1", "relations": relations},
        model,
    ).validate()
    if result.errors:
        raise ValueError("\n".join(result.errors))

    missing_object_types = set(public_model["objects"]) - {
        item["type"] for item in objects
    }
    missing_relation_types = set(public_model["relations"]) - {
        item["type"] for item in relations
    }
    if missing_object_types or missing_relation_types:
        raise ValueError(
            f"seed coverage missing object types={sorted(missing_object_types)}, "
            f"relation types={sorted(missing_relation_types)}"
        )
    validate_business_rules(objects, relations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-clear",
        action="store_true",
        help="replace all Object/Relation records and clear the action log",
    )
    args = parser.parse_args()
    objects, relations = build_graph()
    validate_graph(objects, relations)

    type_counts = Counter(item["type"] for item in objects)
    print(f"Validated {len(objects)} objects and {len(relations)} relations")
    print(
        "Object types: "
        + ", ".join(f"{key}={value}" for key, value in sorted(type_counts.items()))
    )
    if not args.confirm_clear:
        print("Dry run only; pass --confirm-clear to replace the database")
        return 0

    runtime = load_domain(DOMAIN_ROOT)
    try:
        graph = runtime.change_store
        graph.replace_graph(objects, relations)
        with sqlite3.connect(graph.database_path) as connection:
            connection.execute("DELETE FROM action_log")
            connection.commit()
    finally:
        runtime.repository.close()
    print(
        f"Seeded {len(objects)} objects and {len(relations)} relations into "
        f"{DOMAIN_ROOT / 'data' / 'graph.db'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
