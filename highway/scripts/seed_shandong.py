#!/usr/bin/env python3
"""Replace the highway graph with a small, deterministic Shandong scenario."""

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

from uom.composition import compose_domain_models  # noqa: E402
from uom.loader import load_domain  # noqa: E402
from uom.model import (  # noqa: E402
    public_ontology,
    storage_contract_payload,
    workspace_model,
)
from uom.registry import DomainRegistry  # noqa: E402
from uom.validation import ModelValidator  # noqa: E402


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
COORDINATE_SYSTEM = "GCJ-02"


def money(amount: float) -> dict[str, Any]:
    return {"amount": amount, "currency": "CNY"}


def obj(object_id: str, object_type: str, name: str, **properties: Any) -> dict[str, Any]:
    return {"id": object_id, "type": object_type, "name": name, "properties": properties}


def located(longitude: float, latitude: float, **properties: Any) -> dict[str, Any]:
    return {
        **properties,
        "longitude": longitude,
        "latitude": latitude,
        "coordinate_system": COORDINATE_SYSTEM,
    }


def rel(
    relation_id: str,
    relation_type: str,
    source: str,
    target: str,
    role: str | None = None,
    **properties: Any,
) -> dict[str, Any]:
    relation_properties = dict(properties)
    if role is not None:
        relation_properties["role"] = role
    return {
        "id": relation_id,
        "type": relation_type,
        "from": source,
        "to": target,
        "properties": relation_properties,
    }


def route(relation_id: str, source: str, target: str, direction: str, mileage: float) -> dict[str, Any]:
    return rel(
        relation_id, "route_next", source, target,
        direction=direction, mileage=mileage, relation_status="active",
    )


def build_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects = [
        obj("party:sd_operator", "party", "山东高速运营方", category="road_operator", code="SD-OP", status="active"),
        obj("party:sd_network", "party", "山东省联网结算中心", category="network_center", code="SD-NET", status="active"),
        obj("party:sd_issuer", "party", "山东 ETC 发行机构", category="medium_issuer", code="SD-ISSUER", status="active"),
        obj("party:external_operator", "party", "河北相邻路段运营方", category="road_operator", code="HB-OP", status="active"),
        obj("vehicle:lu_a12345", "vehicle", "鲁A12345", plate_no="鲁A12345", vehicle_type="一类客车", status="active"),
        obj("vehicle:lu_b67890", "vehicle", "鲁B67890", plate_no="鲁B67890", vehicle_type="二类货车", status="active"),
        obj("vehicle:lu_c24680", "vehicle", "鲁C24680", plate_no="鲁C24680", vehicle_type="三类货车", status="active"),
        obj("medium:obu_a12345", "toll_medium", "鲁A12345 OBU", medium_kind="obu", code="OBU-SD-001", status="active", valid_from="2026-01-01"),
        obj("medium:etc_a12345", "toll_medium", "鲁A12345 ETC 卡", medium_kind="etc_card", code="ETC-SD-001", status="active", valid_from="2026-01-01"),
        obj("medium:cpc_001", "toll_medium", "CPC 卡 001", medium_kind="cpc_card", code="CPC-SD-001", status="available", valid_from="2026-01-01"),
        obj("medium:paper_001", "toll_medium", "应急纸券 001", medium_kind="paper_ticket", code="PAPER-SD-001", status="available", valid_from="2026-01-01"),
        obj("account:etc_a12345", "account", "鲁A12345 ETC 扣款账户", account_kind="etc_debit", code="ACC-SD-001", balance=money(800), status="active"),
        obj("account:cashier", "account", "山东联网收费归集账户", account_kind="clearing", code="ACC-SD-CLEAR", status="active"),
        obj("road:g20_sd", "toll_road", "G20 青银高速山东段", **located(118.67, 36.78, code="G20-SD", status="operating")),
        obj("section:g20_jinan_zibo", "section", "G20 济南至淄博段", **located(117.53, 36.86, code="G20-S1", mileage=102.0, status="operating")),
        obj("section:g20_zibo_qingdao", "section", "G20 淄博至青岛段", **located(119.25, 36.71, code="G20-S2", mileage=215.0, status="operating")),
        obj("interval:g20_jinan_zibo", "toll_interval", "G20 济南淄博收费单元", **located(117.53, 36.86, code="G20-I1", direction="青岛方向", mileage=102.0, status="active")),
        obj("interval:g20_zibo_qingdao", "toll_interval", "G20 淄博青岛收费单元", **located(119.25, 36.71, code="G20-I2", direction="青岛方向", mileage=215.0, status="active")),
        obj("station:jinan_east", "toll_station", "起步区大桥收费站", **located(117.01, 36.84, code="ST-JNE", status="operating")),
        obj("station:zibo", "toll_station", "淄博收费站", **located(118.08, 36.86, code="ST-ZB", status="operating")),
        obj("station:qingdao", "toll_station", "青岛收费站", **located(120.28, 36.39, code="ST-QD", status="operating")),
        obj("gantry:g20_mid_1", "toll_gantry", "G20 济南淄博门架", **located(117.53, 36.86, code="GANTRY-G20-1", direction="青岛方向", status="operating")),
        obj("gantry:g20_mid_2", "toll_gantry", "G20 淄博青岛门架", **located(119.25, 36.71, code="GANTRY-G20-2", direction="青岛方向", status="operating")),
        obj("lane:jinan_entry", "toll_lane", "起步区大桥入口 ETC 车道", **located(117.01, 36.84, code="LANE-JNE-E", category="etc", direction="entry", status="operating")),
        obj("lane:zibo_entry", "toll_lane", "淄博入口混合车道", **located(118.08, 36.86, code="LANE-ZB-E", category="mixed", direction="entry", status="operating")),
        obj("lane:qingdao_exit", "toll_lane", "青岛出口混合车道", **located(120.28, 36.39, code="LANE-QD-X", category="mixed", direction="exit", status="operating")),
        obj("lane:taian_exit", "toll_lane", "泰安出口人工车道", **located(116.99, 36.24, code="LANE-TA-X", category="mtc", direction="exit", status="operating")),
        obj("equipment:rsu_001", "equipment", "G20 门架 RSU", category="rsu", code="EQ-RSU-001", status="active", details={"antenna_count": 2}),
        obj("equipment:lane_terminal_001", "equipment", "起步区大桥车道终端", category="lane_terminal", code="EQ-LANE-001", status="active"),
        obj("passage:etc_001", "passage", "鲁A12345 ETC 通行", reference_no="PASS-ETC-001", mode="etc", status="completed", source_system="ETC清分平台", source_type="passage_record", source_id="ETC-P-001"),
        obj("passage:cpc_001", "passage", "鲁B67890 CPC 通行一", reference_no="PASS-CPC-001", mode="mtc", status="completed", source_system="车道收费系统", source_type="passage_record", source_id="CPC-P-001"),
        obj("passage:cpc_002", "passage", "鲁C24680 CPC 通行二", reference_no="PASS-CPC-002", mode="mtc", status="completed", source_system="车道收费系统", source_type="passage_record", source_id="CPC-P-002"),
        obj("passage:paper_001", "passage", "鲁C24680 应急纸券通行", reference_no="PASS-PAPER-001", mode="mtc", status="in_progress", source_system="车道收费系统", source_type="passage_record", source_id="PAPER-P-001"),
        obj("event:etc_entry", "passage_event", "ETC 入口识别", reference_no="EV-ETC-E", event_kind="transaction", stage="entry", occurred_at="2026-08-01T08:12:00+08:00", result="success", charged_vehicle_type="一类客车", axle_count=2, source_system="车道收费系统", source_type="entry_transaction", source_id="ETC-E-001"),
        obj("event:etc_gantry", "passage_event", "ETC 门架识别", reference_no="EV-ETC-G", event_kind="identification", stage="gantry", occurred_at="2026-08-01T09:03:00+08:00", result="success", charged_vehicle_type="一类客车", axle_count=2, source_system="门架系统", source_type="gantry_identification", source_id="ETC-G-001"),
        obj("event:etc_exit", "passage_event", "ETC 出口交易", reference_no="EV-ETC-X", event_kind="transaction", stage="exit", occurred_at="2026-08-01T10:21:00+08:00", result="success", charged_vehicle_type="一类客车", axle_count=2, paid_amount=money(168), payment_type="etc_account", source_system="车道收费系统", source_type="exit_transaction", source_id="ETC-X-001"),
        obj("event:cpc1_entry", "passage_event", "CPC 一入口发卡", reference_no="EV-CPC1-E", event_kind="transaction", stage="entry", occurred_at="2026-08-02T07:35:00+08:00", result="success", charged_vehicle_type="二类货车", axle_count=2),
        obj("event:cpc1_exit", "passage_event", "CPC 一出口交易", reference_no="EV-CPC1-X", event_kind="transaction", stage="exit", occurred_at="2026-08-02T08:42:00+08:00", result="success", charged_vehicle_type="二类货车", axle_count=2, paid_amount=money(45), payment_type="cash"),
        obj("event:cpc2_entry", "passage_event", "CPC 二入口发卡", reference_no="EV-CPC2-E", event_kind="transaction", stage="entry", occurred_at="2026-08-05T13:15:00+08:00", result="success", charged_vehicle_type="三类货车", axle_count=3),
        obj("event:cpc2_exit", "passage_event", "CPC 二出口交易", reference_no="EV-CPC2-X", event_kind="transaction", stage="exit", occurred_at="2026-08-05T15:48:00+08:00", result="success", charged_vehicle_type="三类货车", axle_count=3, paid_amount=money(86), payment_type="cash"),
        obj("event:paper_entry", "passage_event", "应急纸券入口登记", reference_no="EV-PAPER-E", event_kind="transaction", stage="entry", occurred_at="2026-08-07T09:12:00+08:00", result="success", charged_vehicle_type="三类货车", axle_count=3),
        obj("charge:etc_001", "charge", "ETC 通行计费", reference_no="CHG-ETC-001", receivable_amount=money(176.84), discount_amount=money(8.84), paid_amount=money(168), version="SD-2026-08", occurred_at="2026-08-01T10:22:00+08:00", result="calculated", source_system="计费服务", source_type="charge_record", source_id="CHG-001"),
        obj("charge:cpc_001", "charge", "CPC 一通行计费", reference_no="CHG-CPC-001", receivable_amount=money(45), discount_amount=money(0), paid_amount=money(45), version="SD-2026-08", occurred_at="2026-08-02T08:43:00+08:00", result="calculated"),
        obj("charge:cpc_002", "charge", "CPC 二通行计费", reference_no="CHG-CPC-002", receivable_amount=money(86), discount_amount=money(0), paid_amount=money(86), version="SD-2026-08", occurred_at="2026-08-05T15:49:00+08:00", result="calculated"),
        obj("payment:etc_001", "payment", "ETC 账户扣款", reference_no="PAY-ETC-001", amount=money(168), payment_type="etc_account", occurred_at="2026-08-02T02:00:00+08:00", result="success", source_system="ETC清分平台", source_type="debit_record", source_id="PAY-001"),
        obj("payment:cpc_001", "payment", "CPC 一现金支付", reference_no="PAY-CPC-001", amount=money(45), payment_type="cash", occurred_at="2026-08-02T08:43:00+08:00", result="success"),
        obj("entry:etc_001", "account_entry", "ETC 通行扣款明细", reference_no="ENTRY-ETC-001", entry_kind="debit", amount=money(168), occurred_at="2026-08-02T02:00:01+08:00", result="success", balance_after=money(800), source_system="ETC清分平台", source_type="account_entry", source_id="ENTRY-001"),
        obj("split:etc_001", "split_result", "ETC 通行本地拆分", reference_no="SPLIT-ETC-001", amount=money(120), occurred_at="2026-08-03T02:00:00+08:00", version="SD-2026-08", split_basis="toll_interval_and_owner", local_amount=money(120), external_amount=money(0), status="completed", source_system="省联网中心", source_type="split_record", source_id="SPLIT-001"),
        obj("split:etc_external", "split_result", "ETC 通行外部拆分", reference_no="SPLIT-ETC-002", amount=money(48), occurred_at="2026-08-03T02:00:00+08:00", version="SD-2026-08", split_basis="toll_interval_and_owner", local_amount=money(0), external_amount=money(48), status="completed", source_system="省联网中心", source_type="split_record", source_id="SPLIT-002"),
        obj("split:cpc_001", "split_result", "CPC 一通行拆分", reference_no="SPLIT-CPC-001", amount=money(45), occurred_at="2026-08-03T02:00:00+08:00", version="SD-2026-08", split_basis="toll_interval_and_owner", local_amount=money(45), external_amount=money(0), status="completed"),
        obj("split:cpc_002", "split_result", "CPC 二通行拆分", reference_no="SPLIT-CPC-002", amount=money(86), occurred_at="2026-08-06T02:00:00+08:00", version="SD-2026-08", split_basis="toll_interval_and_owner", local_amount=money(86), external_amount=money(0), status="completed"),
        obj("settlement:etc_001", "settlement", "ETC 通行本地结算", reference_no="SET-ETC-001", amount=money(120), period="2026-08", occurred_at="2026-08-04T10:00:00+08:00", result="success", due_amount=money(120), allocated_amount=money(120), status="completed", source_system="省联网中心", source_type="settlement_record", source_id="SET-001"),
        obj("settlement:etc_external", "settlement", "ETC 通行外部结算", reference_no="SET-ETC-002", amount=money(48), period="2026-08", occurred_at="2026-08-04T10:00:00+08:00", result="success", due_amount=money(48), allocated_amount=money(48), status="completed", source_system="省联网中心", source_type="settlement_record", source_id="SET-002"),
        obj("settlement:cpc_001", "settlement", "CPC 一通行结算", reference_no="SET-CPC-001", amount=money(45), period="2026-08", occurred_at="2026-08-04T10:00:00+08:00", result="success", due_amount=money(45), allocated_amount=money(45), status="completed"),
        obj("rate:sd_2026_08", "rate_version", "山东 2026 年 8 月费率", version="SD-2026-08", valid_from="2026-08-01", status="published", source_system="省交通运输厅", source_type="rate_version", source_id="RATE-V-2026-08", details={"base_rate": "0.40 CNY/km", "etc_discount": 0.95}),
        obj("rate_rule:passenger_1", "rate_rule", "一类客车基础费率", code="SD-PASSENGER-1", vehicle_type="一类客车", unit_rate=0.4, fee_type="distance", discount_rule={"etc": 0.95}, valid_from="2026-08-01", status="active", source_system="省交通运输厅", source_type="rate_rule", source_id="RATE-R-001", details={"unit": "km"}),
        obj("control:vehicle_c24680", "control_record", "鲁C24680 稽核关注", category="watch_list", status="active", valid_from="2026-08-01", reason="演示异常通行追踪"),
    ]

    relations = [
        rel("rel:operator_road", "associates", "party:sd_operator", "road:g20_sd", "road_operator", relation_status="active"),
        rel("rel:operator_network", "associates", "party:sd_operator", "party:sd_network", "settlement_partner", relation_status="active"),
        rel("rel:vehicle_obu", "associates", "vehicle:lu_a12345", "medium:obu_a12345", "bound_obu", relation_status="active"),
        rel("rel:vehicle_etc", "associates", "vehicle:lu_a12345", "medium:etc_a12345", "bound_etc_card", relation_status="active"),
        rel("rel:account_vehicle", "associates", "account:etc_a12345", "vehicle:lu_a12345", "account_for_vehicle", relation_status="active"),
        rel("rel:road_section_1", "contains", "road:g20_sd", "section:g20_jinan_zibo", relation_status="active"),
        rel("rel:road_section_2", "contains", "road:g20_sd", "section:g20_zibo_qingdao", relation_status="active"),
        rel("rel:section_interval_1", "contains", "section:g20_jinan_zibo", "interval:g20_jinan_zibo", relation_status="active"),
        rel("rel:section_interval_2", "contains", "section:g20_zibo_qingdao", "interval:g20_zibo_qingdao", relation_status="active"),
        rel("rel:section_station_1", "contains", "section:g20_jinan_zibo", "station:jinan_east", relation_status="active"),
        rel("rel:section_station_2", "contains", "section:g20_jinan_zibo", "station:zibo", relation_status="active"),
        rel("rel:section_station_3", "contains", "section:g20_zibo_qingdao", "station:qingdao", relation_status="active"),
        rel("rel:section_gantry_1", "contains", "section:g20_jinan_zibo", "gantry:g20_mid_1", relation_status="active"),
        rel("rel:section_gantry_2", "contains", "section:g20_zibo_qingdao", "gantry:g20_mid_2", relation_status="active"),
        rel("rel:station_lane_1", "contains", "station:jinan_east", "lane:jinan_entry", relation_status="active"),
        rel("rel:station_lane_2", "contains", "station:zibo", "lane:zibo_entry", relation_status="active"),
        rel("rel:station_lane_3", "contains", "station:qingdao", "lane:qingdao_exit", relation_status="active"),
        rel("rel:gantry_equipment", "contains", "gantry:g20_mid_1", "equipment:rsu_001", relation_status="active"),
        rel("rel:lane_equipment", "contains", "lane:jinan_entry", "equipment:lane_terminal_001", relation_status="active"),
        route("rel:route_jinan_gantry", "station:jinan_east", "gantry:g20_mid_1", "青岛方向", 52),
        route("rel:route_gantry_zibo", "gantry:g20_mid_1", "station:zibo", "青岛方向", 50),
        route("rel:route_zibo_gantry", "station:zibo", "gantry:g20_mid_2", "青岛方向", 108),
        route("rel:route_gantry_qingdao", "gantry:g20_mid_2", "station:qingdao", "青岛方向", 107),
        rel("rel:interval_1_start", "references", "interval:g20_jinan_zibo", "station:jinan_east", "start_node", relation_status="confirmed"),
        rel("rel:interval_1_end", "references", "interval:g20_jinan_zibo", "station:zibo", "end_node", relation_status="confirmed"),
        rel("rel:interval_2_start", "references", "interval:g20_zibo_qingdao", "station:zibo", "start_node", relation_status="confirmed"),
        rel("rel:interval_2_end", "references", "interval:g20_zibo_qingdao", "station:qingdao", "end_node", relation_status="confirmed"),
        rel("rel:pass_etc_vehicle", "associates", "passage:etc_001", "vehicle:lu_a12345", "passage_vehicle", relation_status="confirmed"),
        rel("rel:pass_etc_medium", "references", "passage:etc_001", "medium:obu_a12345", "used_medium", relation_status="confirmed"),
        rel("rel:pass_cpc1_vehicle", "associates", "passage:cpc_001", "vehicle:lu_b67890", "passage_vehicle", relation_status="confirmed"),
        rel("rel:pass_cpc1_medium", "references", "passage:cpc_001", "medium:cpc_001", "used_medium", relation_status="confirmed"),
        rel("rel:pass_cpc2_vehicle", "associates", "passage:cpc_002", "vehicle:lu_c24680", "passage_vehicle", relation_status="confirmed"),
        rel("rel:pass_cpc2_medium", "references", "passage:cpc_002", "medium:cpc_001", "used_medium", relation_status="confirmed"),
        rel("rel:pass_paper_vehicle", "associates", "passage:paper_001", "vehicle:lu_c24680", "passage_vehicle", relation_status="confirmed"),
        rel("rel:pass_paper_medium", "references", "passage:paper_001", "medium:paper_001", "used_medium", relation_status="confirmed"),
    ]

    for passage_id, event_specs in {
        "passage:etc_001": [("event:etc_entry", "lane:jinan_entry"), ("event:etc_gantry", "gantry:g20_mid_1"), ("event:etc_exit", "lane:qingdao_exit")],
        "passage:cpc_001": [("event:cpc1_entry", "lane:zibo_entry"), ("event:cpc1_exit", "lane:qingdao_exit")],
        "passage:cpc_002": [("event:cpc2_entry", "lane:zibo_entry"), ("event:cpc2_exit", "lane:qingdao_exit")],
        "passage:paper_001": [("event:paper_entry", "lane:jinan_entry")],
    }.items():
        for event_id, location_id in event_specs:
            relations.append(rel(f"rel:{event_id.replace(':', '_')}_contains", "contains", passage_id, event_id, relation_status="active"))
            relations.append(rel(f"rel:{event_id.replace(':', '_')}_location", "references", event_id, location_id, "occurred_at", relation_status="confirmed"))

    relations.extend([
        rel("rel:cpc1_entry_issued", "references", "event:cpc1_entry", "medium:cpc_001", "issued_medium", relation_status="confirmed"),
        rel("rel:cpc1_exit_recovered", "references", "event:cpc1_exit", "medium:cpc_001", "recovered_medium", relation_status="confirmed"),
        rel("rel:cpc2_entry_issued", "references", "event:cpc2_entry", "medium:cpc_001", "issued_medium", relation_status="confirmed"),
        rel("rel:cpc2_exit_recovered", "references", "event:cpc2_exit", "medium:cpc_001", "recovered_medium", relation_status="confirmed"),
    ])

    for passage_id, charge_id in (("passage:etc_001", "charge:etc_001"), ("passage:cpc_001", "charge:cpc_001"), ("passage:cpc_002", "charge:cpc_002")):
        relations.append(rel(f"rel:{passage_id.replace(':', '_')}_charge", "derives", passage_id, charge_id, "charge", relation_status="confirmed"))
        relations.append(rel(f"rel:{charge_id.replace(':', '_')}_rate", "references", charge_id, "rate:sd_2026_08", "rate_version", relation_status="confirmed"))

    relations.append(rel("rel:etc_charge_split_external", "derives", "charge:etc_001", "split:etc_external", "split", relation_status="confirmed"))

    relations.extend([
        rel("rel:rate_version_rule", "references", "rate:sd_2026_08", "rate_rule:passenger_1", "rate_rule", relation_status="active"),
        rel("rel:etc_charge_rule", "references", "charge:etc_001", "rate_rule:passenger_1", "fare_basis", relation_status="confirmed"),
        rel("rel:etc_payment_charge", "references", "payment:etc_001", "charge:etc_001", "settles_charge", relation_status="confirmed"),
        rel("rel:etc_payment_account", "associates", "payment:etc_001", "account:etc_a12345", "debit_account", relation_status="confirmed"),
        rel("rel:account_entry", "contains", "account:etc_a12345", "entry:etc_001", relation_status="confirmed"),
        rel("rel:entry_payment", "references", "entry:etc_001", "payment:etc_001", "payment", relation_status="confirmed"),
        rel("rel:entry_passage", "references", "entry:etc_001", "passage:etc_001", "passage", relation_status="confirmed"),
        rel("rel:cpc_payment_charge", "references", "payment:cpc_001", "charge:cpc_001", "settles_charge", relation_status="confirmed"),
        rel("rel:etc_charge_split", "derives", "charge:etc_001", "split:etc_001", "split", relation_status="confirmed"),
        rel("rel:cpc1_charge_split", "derives", "charge:cpc_001", "split:cpc_001", "split", relation_status="confirmed"),
        rel("rel:cpc2_charge_split", "derives", "charge:cpc_002", "split:cpc_002", "split", relation_status="confirmed"),
        rel("rel:etc_split_interval", "references", "split:etc_001", "interval:g20_jinan_zibo", "toll_interval", relation_status="confirmed"),
        rel("rel:etc_external_split_interval", "references", "split:etc_external", "interval:g20_zibo_qingdao", "toll_interval", relation_status="confirmed"),
        rel("rel:cpc1_split_interval", "references", "split:cpc_001", "interval:g20_zibo_qingdao", "toll_interval", relation_status="confirmed"),
        rel("rel:cpc2_split_interval", "references", "split:cpc_002", "interval:g20_zibo_qingdao", "toll_interval", relation_status="confirmed"),
        rel("rel:etc_split_owner", "references", "split:etc_001", "party:sd_operator", "owner", relation_status="confirmed"),
        rel("rel:etc_external_split_owner", "references", "split:etc_external", "party:external_operator", "owner", relation_status="confirmed"),
        rel("rel:cpc1_split_owner", "references", "split:cpc_001", "party:sd_operator", "owner", relation_status="confirmed"),
        rel("rel:cpc2_split_owner", "references", "split:cpc_002", "party:sd_operator", "owner", relation_status="confirmed"),
        rel("rel:etc_settlement", "derives", "split:etc_001", "settlement:etc_001", "settlement", relation_status="confirmed"),
        rel("rel:etc_external_settlement", "derives", "split:etc_external", "settlement:etc_external", "settlement", relation_status="confirmed"),
        rel("rel:cpc1_settlement", "derives", "split:cpc_001", "settlement:cpc_001", "settlement", relation_status="confirmed"),
        rel("rel:etc_settlement_recipient", "references", "settlement:etc_001", "party:sd_operator", "recipient", relation_status="confirmed"),
        rel("rel:etc_external_settlement_recipient", "references", "settlement:etc_external", "party:external_operator", "recipient", relation_status="confirmed"),
        rel("rel:cpc1_settlement_recipient", "references", "settlement:cpc_001", "party:sd_operator", "recipient", relation_status="confirmed"),
        rel("rel:control_vehicle", "references", "control:vehicle_c24680", "vehicle:lu_c24680", "controlled_object", relation_status="active"),
    ])
    return objects, relations


def validate_graph(domain_root: Path, objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> None:
    registry = DomainRegistry.discover(domain_root)
    composed = compose_domain_models(
        [descriptor.path for descriptor in registry.list()],
        include_actions=False,
    )
    public_model, _ = public_ontology(composed)
    domain_model = workspace_model(
        public_model,
        {"schema": "uom.action_plans.v1", "actions": {}},
        composed.model_dump(by_alias=True),
    )
    result = ModelValidator(
        storage_contract_payload(),
        {"schema": "uom.data.objects.v1", "objects": objects},
        {"schema": "uom.data.relations.v1", "relations": relations},
        domain_model,
    ).validate()
    if result.errors:
        raise ValueError("\n".join(result.errors))
    missing_objects = set(public_model["objects"]) - {item["type"] for item in objects}
    missing_relations = set(public_model["relations"]) - {item["type"] for item in relations}
    if missing_objects or missing_relations:
        raise ValueError(f"missing seed types: objects={sorted(missing_objects)}, relations={sorted(missing_relations)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DOMAIN_ROOT)
    parser.add_argument("--confirm-clear", action="store_true", help="replace all graph records")
    args = parser.parse_args()
    domain_root = args.root.resolve()
    objects, relations = build_graph()
    validate_graph(domain_root, objects, relations)
    counts = Counter(item["type"] for item in objects)
    print(f"Validated {len(objects)} objects and {len(relations)} relations")
    print("Object types: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    if not args.confirm_clear:
        print("Dry run only; pass --confirm-clear to replace the database")
        return 0
    registry = DomainRegistry.discover(domain_root)
    passage_domain = registry.get(f"{domain_root.name}.passage_charging")
    runtime = load_domain(passage_domain.path)
    try:
        runtime.change_store.replace_graph(objects, relations)
        with sqlite3.connect(runtime.change_store.database_path) as connection:
            connection.execute("DELETE FROM action_log")
            connection.commit()
    finally:
        runtime.repository.close()
    print(
        f"Seeded {len(objects)} objects and {len(relations)} relations into "
        f"{runtime.change_store.database_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
