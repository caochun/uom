#!/usr/bin/env python3
"""Replace OMS instance data with a deterministic Shandong highway scenario."""

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

from oag.ontology.loader import load_domain  # noqa: E402
from oms.scripts.validate_model import ModelValidator, load_yaml  # noqa: E402


OMS_ROOT = Path(__file__).resolve().parents[1]
COORDINATE_SYSTEM = "GCJ-02"


def money(amount: float) -> dict[str, Any]:
    return {"amount": amount, "currency": "CNY"}


def located(longitude: float, latitude: float, **properties: Any) -> dict[str, Any]:
    """Attach an Amap-compatible point to a spatial business object."""
    return {
        **properties,
        "longitude": longitude,
        "latitude": latitude,
        "coordinate_system": COORDINATE_SYSTEM,
    }


def obj(
    object_id: str,
    object_type: str,
    name: str,
    properties: dict[str, Any],
    *tags: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": object_id,
        "type": object_type,
        "name": name,
        "properties": properties,
    }
    if tags:
        record["tags"] = list(tags)
    return record


def rel(
    relation_id: str,
    relation_type: str,
    source: str,
    target: str,
    role: str,
    **properties: Any,
) -> dict[str, Any]:
    return {
        "id": relation_id,
        "type": relation_type,
        "from": source,
        "to": target,
        "properties": {"role": role, **properties},
    }


def route(
    relation_id: str,
    source: str,
    target: str,
    direction: str,
    mileage: float,
) -> dict[str, Any]:
    return {
        "id": relation_id,
        "type": "route_next",
        "from": source,
        "to": target,
        "properties": {
            "direction": direction,
            "mileage": mileage,
            "status": "active",
        },
    }


def build_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects = [
        obj("party:sd_expressway", "party", "山东高速股份有限公司（Mock）", {
            "category": "toll_road_operator", "code": "MOCK-SDGS", "status": "active",
        }, "shandong", "operator"),
        obj("party:sd_network_center", "party", "山东省高速公路联网结算中心（Mock）", {
            "category": "province_network_center", "code": "MOCK-SD-NET", "status": "active",
        }, "shandong", "network_center"),
        obj("party:sd_etc_issuer", "party", "山东高速 ETC 发行服务中心（Mock）", {
            "category": "issuer", "code": "MOCK-SD-ISSUER", "status": "active",
        }, "shandong", "issuer"),
        obj("user:qilu_logistics", "user", "齐鲁示例物流有限公司", {
            "reference_no": "MOCK-U-SD-001", "status": "active",
        }, "mock_customer"),
        obj("user:dao_cheng_coach", "user", "岛城示例客运有限公司", {
            "reference_no": "MOCK-U-SD-002", "status": "active",
        }, "mock_customer"),
        obj("vehicle:lu_a12345", "vehicle", "鲁A12345", {
            "plate_no": "鲁A12345", "vehicle_type": "一类客车", "status": "active",
        }, "etc_vehicle"),
        obj("vehicle:lu_b67890", "vehicle", "鲁B67890", {
            "plate_no": "鲁B67890", "vehicle_type": "二类客车", "status": "active",
        }, "mtc_vehicle"),
        obj("vehicle:lu_c24680", "vehicle", "鲁C24680", {
            "plate_no": "鲁C24680", "vehicle_type": "三类货车", "status": "active",
        }, "mtc_vehicle"),
        obj("obu:sd_001", "obu", "鲁A12345 OBU", {
            "category": "double_piece", "code": "MOCK-OBU-SD-001", "status": "active",
            "valid_from": "2026-01-01",
        }, "shandong_etc"),
        obj("etc_card:sd_001", "etc_card", "鲁A12345 ETC 记账卡", {
            "category": "postpaid", "code": "MOCK-ETC-SD-001", "status": "active",
            "valid_from": "2026-01-01",
        }, "shandong_etc"),
        obj("cpc_card:sd_001", "cpc_card", "山东 CPC 卡 001", {
            "code": "MOCK-CPC-SD-001", "status": "available", "valid_from": "2026-01-01",
        }, "shandong_cpc", "reused"),
        obj("cpc_card:sd_002", "cpc_card", "山东 CPC 卡 002", {
            "code": "MOCK-CPC-SD-002", "status": "available", "valid_from": "2026-01-01",
        }, "shandong_cpc", "in_stock"),
        obj("paper_ticket:sd_001", "paper_ticket", "山东应急纸券 001", {
            "code": "MOCK-TICKET-SD-001", "status": "available", "valid_from": "2026-01-01",
        }, "shandong_ticket", "emergency"),
        obj("user_account:qilu", "user_account", "齐鲁示例物流用户资金账户", {
            "reference_no": "MOCK-UA-SD-001", "balance": money(1000),
            "status": "active",
        }),
        obj("card_account:sd_etc_001", "card_account", "鲁A12345 ETC 卡资金账户", {
            "reference_no": "MOCK-CA-SD-001", "balance": money(832),
            "status": "active",
        }),
        obj("stock_account:sd_issuer", "stock_account", "山东 ETC 发行机构库存账户", {
            "category": "institution", "reference_no": "MOCK-SA-SD-001", "status": "active",
        }),
        obj("toll_road:g20_sd", "toll_road", "G20 青银高速山东示例走廊", located(
            118.664368, 36.776400, code="G20-SD-MOCK", status="operating",
            details={"point_role": "scenario_corridor_center"},
        ), "shandong", "g20"),
        obj("toll_road:g3_sd", "toll_road", "G3 京台高速山东示例走廊", located(
            116.938924, 36.445421, code="G3-SD-MOCK", status="operating",
            details={"point_role": "scenario_corridor_center"},
        ), "shandong", "g3"),
        obj("section:g20_jinan_zibo", "section", "G20 起步区至淄博段", located(
            117.531938, 36.863853, code="G20-SD-QB-ZB", mileage=102.1,
            status="operating", details={"point_role": "route_midpoint"},
        )),
        obj("section:g20_zibo_qingdao", "section", "G20 淄博至青岛段", located(
            119.249839, 36.712605, code="G20-SD-ZB-QD", mileage=215.4,
            status="operating", details={"point_role": "route_midpoint"},
        )),
        obj("section:g3_jinan_taian", "section", "G3 济南至泰安段", located(
            116.891220, 36.444653, code="G3-SD-JN-TA", mileage=52.4,
            status="operating", details={"point_role": "route_midpoint"},
        )),
        obj("interval:g20_jinan_zibo", "toll_interval", "G20 起步区至淄博收费单元", located(
            117.531938, 36.863853, code="MOCK-TI-G20-01", direction="青岛方向",
            mileage=102.1, status="active", details={"point_role": "route_midpoint"},
        )),
        obj("interval:g20_zibo_qingdao", "toll_interval", "G20 淄博至青岛收费单元", located(
            119.249839, 36.712605, code="MOCK-TI-G20-02", direction="青岛方向",
            mileage=215.4, status="active", details={"point_role": "route_midpoint"},
        )),
        obj("interval:g3_jinan_taian", "toll_interval", "G3 济南至泰安收费单元", located(
            116.891220, 36.444653, code="MOCK-TI-G3-01", direction="台北方向",
            mileage=52.4, status="active", details={"point_role": "route_midpoint"},
        )),
        obj("station:jinan_east", "toll_station", "起步区大桥收费站（G20 Mock）", located(
            117.007341, 36.843551, code="MOCK-SD-QB-BRIDGE", status="operating",
            details={"amap_poi_name": "起步区大桥收费站(G20青银高速入口)"},
        )),
        obj("station:zibo", "toll_station", "淄博收费站（G20 Mock）", located(
            118.080390, 36.859333, code="MOCK-SD-ZB", status="operating",
            details={"amap_poi_name": "淄博收费站(G20青银高速入口)"},
        )),
        obj("station:qingdao", "toll_station", "青岛收费站（G20 Mock）", located(
            120.282431, 36.388636, code="MOCK-SD-QD", status="operating",
            details={"amap_poi_name": "青岛收费站(G20青银高速东南向)"},
        )),
        obj("station:jinan_west", "toll_station", "济南西收费站（G3 Mock）", located(
            116.887596, 36.652593, code="MOCK-SD-JN-W", status="operating",
            details={"amap_poi_name": "济南西收费站(G3京台高速入口)"},
        )),
        obj("station:taian_north", "toll_station", "泰安北收费站（G3 Mock）", located(
            116.990500, 36.238249, code="MOCK-SD-TA-N", status="operating",
            details={"amap_poi_name": "泰安北收费站(G3京台高速入口)"},
        )),
        obj("plaza:jinan_west", "toll_plaza", "济南西收费广场（Mock）", located(
            116.887405, 36.652543, code="MOCK-PLAZA-JN-W", direction="双向",
            status="operating", details={"location_basis": "G3收费站入口与出口之间"},
        )),
        obj("lane:jinan_east_entry", "toll_lane", "起步区大桥入口 01 车道（Mock）", located(
            117.007392, 36.843519, code="MOCK-LANE-QB-EN-01", category="etc",
            direction="entry", status="operating", details={"offset_from_station_m": 6},
        )),
        obj("lane:zibo_entry", "toll_lane", "淄博入口 03 车道（Mock）", located(
            118.080444, 36.859301, code="MOCK-LANE-ZB-EN-03", category="mtc",
            direction="entry", status="operating", details={"offset_from_station_m": 6},
        )),
        obj("lane:qingdao_exit", "toll_lane", "青岛出口 02 车道（Mock）", located(
            120.282377, 36.388669, code="MOCK-LANE-QD-EX-02", category="mixed",
            direction="exit", status="operating", details={"offset_from_station_m": 6},
        )),
        obj("lane:jinan_west_entry", "toll_lane", "济南西入口 04 车道（Mock）", located(
            116.887650, 36.652564, code="MOCK-LANE-JN-W-EN-04", category="mtc",
            direction="entry", status="operating", details={"offset_from_station_m": 6},
        )),
        obj("lane:taian_north_exit", "toll_lane", "泰安北出口 05 车道（Mock）", located(
            116.990202, 36.238101, code="MOCK-LANE-TA-N-EX-05", category="mtc",
            direction="exit", status="operating", details={"offset_from_station_m": 6},
        )),
        obj("gantry:g20_jinan_zibo", "toll_gantry", "G20 起步区淄博中点门架（Mock）", located(
            117.531938, 36.863853, code="MOCK-GANTRY-G20-01", direction="青岛方向",
            status="operating", details={"location_basis": "Amap driving route midpoint"},
        )),
        obj("gantry:g20_zibo_qingdao", "toll_gantry", "G20 淄博青岛中点门架（Mock）", located(
            119.249839, 36.712605, code="MOCK-GANTRY-G20-02", direction="青岛方向",
            status="operating", details={"location_basis": "Amap driving route midpoint"},
        )),
        obj("gantry:g3_jinan_taian", "toll_gantry", "G3 济南泰安中点门架（Mock）", located(
            116.891220, 36.444653, code="MOCK-GANTRY-G3-01", direction="台北方向",
            status="operating", details={"location_basis": "Amap driving route midpoint"},
        )),
        obj("facility:g20_zhangqiu_service", "service_facility", "济南东服务区（G20 Mock）", located(
            117.368920, 36.808355, category="service_area", code="MOCK-SERVICE-G20-JNE",
            channel="roadside", status="operating",
            details={"amap_poi_name": "济南东服务区(青银高速青岛方向)"},
        )),
        obj("device:g20_gantry_rsu_01", "business_device", "G20 起步区淄博门架 RSU 01（Mock）", located(
            117.531951, 36.863861, category="rsu", code="MOCK-RSU-G20-01",
            status="active", details={"antenna_count": 2, "offset_from_gantry_m": 2},
        )),
        obj("passage:sd_etc_001", "passage", "山东 ETC 通行 001", {
            "reference_no": "MOCK-PASS-SD-ETC-001", "mode": "etc",
            "status": "completed",
        }, "shandong", "etc_passage"),
        obj("transaction:sd_etc_entry", "toll_transaction", "ETC 通行 001 入口交易", {
            "reference_no": "MOCK-TX-SD-ETC-E", "stage": "entry",
            "occurred_at": "2026-08-01T08:12:16+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "一类客车", "axle_count": 2, "result": "success",
            "operation_channel": "lane_terminal", "status": "recorded",
        }),
        obj("transaction:sd_etc_gantry", "toll_transaction", "ETC 通行 001 门架交易", {
            "reference_no": "MOCK-TX-SD-ETC-G", "stage": "gantry",
            "occurred_at": "2026-08-01T09:03:44+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "一类客车", "axle_count": 2, "result": "success",
            "receivable_amount": money(92), "discount_amount": money(4.6),
            "paid_amount": money(87.4), "status": "recorded",
        }),
        obj("transaction:sd_etc_exit", "toll_transaction", "ETC 通行 001 出口交易", {
            "reference_no": "MOCK-TX-SD-ETC-X", "stage": "exit",
            "occurred_at": "2026-08-01T10:21:08+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "一类客车", "axle_count": 2, "result": "success",
            "operation_channel": "lane_terminal", "receivable_amount": money(176.84),
            "discount_amount": money(8.84), "paid_amount": money(168),
            "payment_type": "etc_account", "fee_type": "normal", "multi_province": False,
            "status": "recorded",
        }),
        obj("passage:sd_cpc_001", "passage", "山东 CPC 通行 001", {
            "reference_no": "MOCK-PASS-SD-CPC-001", "mode": "mtc",
            "status": "completed",
        }, "shandong", "cpc_passage"),
        obj("transaction:sd_cpc_001_entry", "toll_transaction", "CPC 通行 001 入口交易", {
            "reference_no": "MOCK-TX-SD-CPC1-E", "stage": "entry",
            "occurred_at": "2026-08-02T07:35:20+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "一类客车", "axle_count": 2, "result": "success",
            "operation_channel": "lane_terminal", "status": "recorded",
        }),
        obj("transaction:sd_cpc_001_gantry", "toll_transaction", "CPC 通行 001 门架交易", {
            "reference_no": "MOCK-TX-SD-CPC1-G", "stage": "gantry",
            "occurred_at": "2026-08-02T08:10:00+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "一类客车", "axle_count": 2, "result": "success",
            "receivable_amount": money(24), "discount_amount": money(0),
            "paid_amount": money(24), "status": "recorded",
        }),
        obj("transaction:sd_cpc_001_exit", "toll_transaction", "CPC 通行 001 出口交易", {
            "reference_no": "MOCK-TX-SD-CPC1-X", "stage": "exit",
            "occurred_at": "2026-08-02T08:42:31+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "一类客车", "axle_count": 2, "result": "success",
            "operation_channel": "lane_terminal", "receivable_amount": money(45),
            "discount_amount": money(0), "paid_amount": money(45),
            "payment_type": "cash", "fee_type": "normal", "multi_province": False,
            "status": "recorded",
        }),
        obj("passage:sd_cpc_002", "passage", "山东 CPC 通行 002", {
            "reference_no": "MOCK-PASS-SD-CPC-002", "mode": "mtc",
            "status": "completed",
        }, "shandong", "cpc_passage", "medium_reuse"),
        obj("transaction:sd_cpc_002_entry", "toll_transaction", "CPC 通行 002 入口交易", {
            "reference_no": "MOCK-TX-SD-CPC2-E", "stage": "entry",
            "occurred_at": "2026-08-05T13:15:11+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "二类货车", "axle_count": 2, "result": "success",
            "operation_channel": "lane_terminal", "status": "recorded",
        }),
        obj("transaction:sd_cpc_002_exit", "toll_transaction", "CPC 通行 002 出口交易", {
            "reference_no": "MOCK-TX-SD-CPC2-X", "stage": "exit",
            "occurred_at": "2026-08-05T15:48:55+08:00", "transaction_type": "normal",
            "charged_vehicle_type": "二类货车", "axle_count": 2, "result": "success",
            "operation_channel": "lane_terminal", "receivable_amount": money(86),
            "discount_amount": money(0), "paid_amount": money(86),
            "payment_type": "mobile", "fee_type": "normal", "multi_province": False,
            "status": "recorded",
        }),
        obj("passage:sd_ticket_001", "passage", "山东纸券通行 001", {
            "reference_no": "MOCK-PASS-SD-TICKET-001", "mode": "mtc",
            "status": "completed",
        }, "shandong", "paper_ticket_passage"),
        obj("transaction:sd_ticket_001_entry", "toll_transaction", "纸券通行 001 入口交易", {
            "reference_no": "MOCK-TX-SD-TICKET1-E", "stage": "entry",
            "occurred_at": "2026-08-07T09:12:10+08:00", "transaction_type": "emergency",
            "charged_vehicle_type": "三类货车", "axle_count": 3, "result": "success",
            "operation_channel": "portable_terminal", "status": "recorded",
        }),
        obj("transaction:sd_ticket_001_exit", "toll_transaction", "纸券通行 001 出口交易", {
            "reference_no": "MOCK-TX-SD-TICKET1-X", "stage": "exit",
            "occurred_at": "2026-08-07T10:24:18+08:00", "transaction_type": "emergency",
            "charged_vehicle_type": "三类货车", "axle_count": 3, "result": "success",
            "operation_channel": "portable_terminal", "receivable_amount": money(66),
            "discount_amount": money(0), "paid_amount": money(66), "payment_type": "cash",
            "fee_type": "paper_ticket", "multi_province": False, "status": "recorded",
        }),
        obj("vehicle_id:sd_etc_entry", "vehicle_id_record", "ETC 通行 001 入口牌识", {
            "reference_no": "MOCK-VIS-SD-ETC-E", "occurred_at": "2026-08-01T08:12:15+08:00",
            "plate_no": "鲁A12345", "vehicle_type": "一类客车", "direction": "entry",
            "result": "matched",
        }),
        obj("vehicle_id:sd_etc_gantry", "vehicle_id_record", "ETC 通行 001 门架牌识", {
            "reference_no": "MOCK-VIS-SD-ETC-G", "occurred_at": "2026-08-01T09:03:43+08:00",
            "plate_no": "鲁A12345", "vehicle_type": "一类客车", "direction": "青岛方向",
            "result": "matched",
        }),
        obj("vehicle_id:sd_etc_exit", "vehicle_id_record", "ETC 通行 001 出口牌识", {
            "reference_no": "MOCK-VIS-SD-ETC-X", "occurred_at": "2026-08-01T10:21:07+08:00",
            "plate_no": "鲁A12345", "vehicle_type": "一类客车", "direction": "exit",
            "result": "matched",
        }),
        obj("check:sd_cpc_001", "vehicle_check_result", "CPC 通行 001 预约车辆查验", {
            "reference_no": "MOCK-CHECK-SD-CPC1", "occurred_on": "2026-08-02",
            "result": "approved", "details": {"category": "green_transport"},
        }),
        obj("second_charge:sd_cpc_001", "second_charge_result", "CPC 通行 001 二次计费", {
            "reference_no": "MOCK-SECOND-SD-CPC1", "original_amount": money(45),
            "amount": money(42), "occurred_on": "2026-08-03", "result": "success",
        }),
        obj("split:sd_etc_001", "split_record", "ETC 通行 001 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-ETC-001", "amount": money(168),
            "occurred_on": "2026-08-02", "status": "calculated",
        }),
        obj("split:sd_cpc_001", "split_record", "CPC 通行 001 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-CPC-001", "amount": money(42),
            "occurred_on": "2026-08-03", "status": "calculated",
        }),
        obj("split:sd_cpc_002", "split_record", "CPC 通行 002 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-CPC-002", "amount": money(86),
            "occurred_on": "2026-08-06", "status": "calculated",
        }),
        obj("split:sd_ticket_001", "split_record", "纸券通行 001 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-TICKET-001", "amount": money(66),
            "occurred_on": "2026-08-08", "status": "calculated",
        }),
        obj("split_basis:sd_etc_001", "split_basis", "ETC 通行 001 路径拆分依据", {
            "version": "2026.08", "details": {
                "basis": "observed_gantry_path",
                "transaction_sequence": ["MOCK-TX-SD-ETC-E", "MOCK-TX-SD-ETC-G", "MOCK-TX-SD-ETC-X"],
            },
        }),
        obj("split_detail:sd_etc_01", "split_detail", "ETC 通行 001 济南淄博明细", {
            "amount": money(58), "details": {"sequence": 1},
        }),
        obj("split_detail:sd_etc_02", "split_detail", "ETC 通行 001 淄博青岛明细", {
            "amount": money(110), "details": {"sequence": 2},
        }),
        obj("split_detail:sd_cpc_01", "split_detail", "CPC 通行 001 济南泰安明细", {
            "amount": money(42), "details": {"sequence": 1},
        }),
        obj("split_detail:sd_cpc_02", "split_detail", "CPC 通行 002 淄博青岛明细", {
            "amount": money(86), "details": {"sequence": 1},
        }),
        obj("split_detail:sd_ticket_01", "split_detail", "纸券通行 001 济南泰安明细", {
            "amount": money(66), "details": {"sequence": 1},
        }),
        obj("clearing:sd_etc_001", "clearing_result", "ETC 通行 001 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-ETC-001", "amount": money(168),
            "period": "2026-08", "occurred_on": "2026-08-03", "status": "confirmed",
        }),
        obj("clearing:sd_cpc_001", "clearing_result", "CPC 通行 001 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-CPC-001", "amount": money(42),
            "period": "2026-08", "occurred_on": "2026-08-04", "status": "confirmed",
        }),
        obj("clearing:sd_cpc_002", "clearing_result", "CPC 通行 002 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-CPC-002", "amount": money(86),
            "period": "2026-08", "occurred_on": "2026-08-07", "status": "confirmed",
        }),
        obj("clearing:sd_ticket_001", "clearing_result", "纸券通行 001 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-TICKET-001", "amount": money(66),
            "period": "2026-08", "occurred_on": "2026-08-09", "status": "confirmed",
        }),
        obj("invoice:sd_etc_001", "invoice_basis_data", "ETC 通行 001 发票基础数据", {
            "reference_no": "MOCK-INV-SD-ETC-001", "amount": money(168),
            "occurred_on": "2026-08-03", "status": "ready",
        }),
        obj("account_tx:sd_recharge_001", "account_transaction", "齐鲁示例物流充值", {
            "category": "recharge", "reference_no": "MOCK-AT-SD-001", "amount": money(1000),
            "occurred_on": "2026-07-30", "status": "completed",
        }),
        obj("account_entry:sd_recharge_001", "account_entry", "齐鲁示例物流充值记账", {
            "category": "recharge", "reference_no": "MOCK-ENTRY-SD-RECHARGE-001",
            "amount": money(1000), "occurred_on": "2026-07-30", "balance": money(1000),
            "status": "booked",
        }),
        obj("service_record:sd_etc_001_activation", "customer_service_record", "鲁A12345 ETC 卡激活业务", {
            "category": "etc_card_activation", "reference_no": "MOCK-CS-SD-001",
            "occurred_on": "2026-07-30", "result": "completed", "channel": "service_hall",
        }),
        obj("consumption:sd_etc_001", "consumption_detail", "ETC 通行 001 消费明细", {
            "reference_no": "MOCK-CONSUME-SD-001", "amount": money(168),
            "occurred_on": "2026-08-01", "status": "booked",
            "details": {"receivable": money(176.84), "discount": money(8.84)},
        }),
        obj("bill:sd_202608", "bill", "齐鲁示例物流 2026-08 ETC 账单", {
            "reference_no": "MOCK-BILL-SD-202608", "amount": money(168),
            "period": "2026-08", "status": "settled",
        }),
        obj("settlement:sd_202608", "bill_settlement", "齐鲁示例物流 2026-08 账单结算", {
            "reference_no": "MOCK-SETTLE-SD-202608", "amount": money(168),
            "occurred_on": "2026-08-08", "result": "success",
        }),
        obj("stock_movement:sd_cpc_002", "stock_movement", "CPC 卡 002 初始入库", {
            "category": "initial_stock", "reference_no": "MOCK-STOCK-SD-001", "quantity": 1,
            "occurred_on": "2026-07-01",
        }),
        obj("summary:sd_20260801", "business_day_summary", "山东 ETC 发行中心 2026-08-01 日结", {
            "reference_no": "MOCK-DAY-SD-20260801", "occurred_on": "2026-08-01",
            "result": "balanced", "details": {"recharge_total": money(1000), "passage_count": 1},
        }),
        obj("reconciliation:sd_202608", "reconciliation_result", "山东 ETC 2026-08 对账结果", {
            "reference_no": "MOCK-RECON-SD-202608", "occurred_on": "2026-08-09",
            "result": "matched",
        }),
        obj("fee_module:sd_2026", "fee_module", "山东省 2026 Mock 计费模块", {
            "version": "MOCK-SD-2026.08", "valid_from": "2026-08-01", "status": "published",
        }),
        obj("fee_rule:sd_base", "fee_rule", "山东高速基础费率规则（Mock）", {
            "category": "base_rate", "code": "MOCK-FEE-SD-BASE", "version": "2026.08",
            "valid_from": "2026-08-01", "details": {"vehicle_type": "一类客车", "rate": "0.40元/公里"},
        }),
        obj("fee_rule:sd_etc_discount", "fee_rule", "山东 ETC 优惠规则（Mock）", {
            "category": "discount", "code": "MOCK-FEE-SD-ETC", "version": "2026.08",
            "valid_from": "2026-08-01", "details": {"discount_rate": 0.95},
        }),
        obj("fee_rule:sd_provincial", "fee_rule", "山东省级计费规则（Mock）", {
            "category": "provincial_rate", "code": "MOCK-FEE-SD-PROV", "version": "2026.08",
            "valid_from": "2026-08-01", "details": {"source": "base_rate_and_interval"},
        }),
        obj("control:lu_c24680_watch", "control_record", "鲁C24680 重点关注记录（Mock）", {
            "category": "watch_list", "code": "MOCK-CTRL-SD-001", "status": "active",
            "valid_from": "2026-08-01", "reason": "Mock 稽核演示",
        }),
        obj("parameter:g20_gantry", "operating_parameter", "G20 山东段门架计费参数（Mock）", {
            "category": "gantry_billing", "code": "MOCK-PARAM-SD-G20", "status": "active",
            "version": "2026.08", "valid_from": "2026-08-01", "details": {"timeout_seconds": 3},
        }),
    ]

    relations = [
        rel("rel:user_qilu_vehicle_a", "associates", "user:qilu_logistics", "vehicle:lu_a12345", "owned_vehicle", status="active"),
        rel("rel:user_qilu_vehicle_c", "associates", "user:qilu_logistics", "vehicle:lu_c24680", "owned_vehicle", status="active"),
        rel("rel:user_coach_vehicle_b", "associates", "user:dao_cheng_coach", "vehicle:lu_b67890", "owned_vehicle", status="active"),
        rel("rel:vehicle_a_obu", "associates", "vehicle:lu_a12345", "obu:sd_001", "bound_obu", status="active"),
        rel("rel:vehicle_a_etc_card", "associates", "vehicle:lu_a12345", "etc_card:sd_001", "bound_etc_card", status="active"),
        rel("rel:obu_etc_card", "associates", "obu:sd_001", "etc_card:sd_001", "paired_etc_card", status="active"),
        rel("rel:user_account_qilu", "associates", "user_account:qilu", "user:qilu_logistics", "account_holder", status="active"),
        rel("rel:card_account_etc", "associates", "card_account:sd_etc_001", "etc_card:sd_001", "account_card", status="active"),
        rel("rel:stock_account_issuer", "associates", "stock_account:sd_issuer", "party:sd_etc_issuer", "stock_holder", status="active"),
        rel("rel:issuer_obu", "associates", "party:sd_etc_issuer", "obu:sd_001", "issued_obu", status="active"),
        rel("rel:issuer_etc_card", "associates", "party:sd_etc_issuer", "etc_card:sd_001", "issued_etc_card", status="active"),
        rel("rel:operator_g20", "associates", "party:sd_expressway", "toll_road:g20_sd", "road_operator", status="active"),
        rel("rel:operator_g3", "associates", "party:sd_expressway", "toll_road:g3_sd", "road_operator", status="active"),
        rel("rel:g20_section_1", "contains", "toll_road:g20_sd", "section:g20_jinan_zibo", "road_section"),
        rel("rel:g20_section_2", "contains", "toll_road:g20_sd", "section:g20_zibo_qingdao", "road_section"),
        rel("rel:g3_section_1", "contains", "toll_road:g3_sd", "section:g3_jinan_taian", "road_section"),
        rel("rel:g20_s1_interval", "contains", "section:g20_jinan_zibo", "interval:g20_jinan_zibo", "toll_interval"),
        rel("rel:g20_s2_interval", "contains", "section:g20_zibo_qingdao", "interval:g20_zibo_qingdao", "toll_interval"),
        rel("rel:g3_s1_interval", "contains", "section:g3_jinan_taian", "interval:g3_jinan_taian", "toll_interval"),
        rel("rel:g20_s1_station_jinan", "contains", "section:g20_jinan_zibo", "station:jinan_east", "toll_station"),
        rel("rel:g20_s1_station_zibo", "contains", "section:g20_jinan_zibo", "station:zibo", "toll_station"),
        rel("rel:g20_s2_station_qingdao", "contains", "section:g20_zibo_qingdao", "station:qingdao", "toll_station"),
        rel("rel:g3_s1_station_jinan", "contains", "section:g3_jinan_taian", "station:jinan_west", "toll_station"),
        rel("rel:g3_s1_station_taian", "contains", "section:g3_jinan_taian", "station:taian_north", "toll_station"),
        rel("rel:station_jinan_east_lane", "contains", "station:jinan_east", "lane:jinan_east_entry", "toll_lane"),
        rel("rel:station_zibo_lane", "contains", "station:zibo", "lane:zibo_entry", "toll_lane"),
        rel("rel:station_qingdao_lane", "contains", "station:qingdao", "lane:qingdao_exit", "toll_lane"),
        rel("rel:station_jinan_west_plaza", "contains", "station:jinan_west", "plaza:jinan_west", "toll_plaza"),
        rel("rel:plaza_jinan_west_lane", "contains", "plaza:jinan_west", "lane:jinan_west_entry", "toll_lane"),
        rel("rel:station_taian_north_lane", "contains", "station:taian_north", "lane:taian_north_exit", "toll_lane"),
        rel("rel:g20_s1_gantry", "contains", "section:g20_jinan_zibo", "gantry:g20_jinan_zibo", "toll_gantry"),
        rel("rel:g20_s2_gantry", "contains", "section:g20_zibo_qingdao", "gantry:g20_zibo_qingdao", "toll_gantry"),
        rel("rel:g3_s1_gantry", "contains", "section:g3_jinan_taian", "gantry:g3_jinan_taian", "toll_gantry"),
        rel("rel:g20_s1_service", "contains", "section:g20_jinan_zibo", "facility:g20_zhangqiu_service", "service_facility"),
        rel("rel:g20_gantry_rsu", "contains", "gantry:g20_jinan_zibo", "device:g20_gantry_rsu_01", "business_device"),
        route("rel:route_g20_jinan_gantry", "station:jinan_east", "gantry:g20_jinan_zibo", "青岛方向", 51.0),
        route("rel:route_g20_gantry_zibo", "gantry:g20_jinan_zibo", "station:zibo", "青岛方向", 51.1),
        route("rel:route_g20_zibo_gantry", "station:zibo", "gantry:g20_zibo_qingdao", "青岛方向", 107.7),
        route("rel:route_g20_gantry_qingdao", "gantry:g20_zibo_qingdao", "station:qingdao", "青岛方向", 107.7),
        route("rel:route_g3_jinan_gantry", "station:jinan_west", "gantry:g3_jinan_taian", "台北方向", 26.2),
        route("rel:route_g3_gantry_taian", "gantry:g3_jinan_taian", "station:taian_north", "台北方向", 26.2),
        rel("rel:interval_g20_s1_start", "references", "interval:g20_jinan_zibo", "station:jinan_east", "start_node"),
        rel("rel:interval_g20_s1_end", "references", "interval:g20_jinan_zibo", "station:zibo", "end_node"),
        rel("rel:interval_g20_s2_start", "references", "interval:g20_zibo_qingdao", "station:zibo", "start_node"),
        rel("rel:interval_g20_s2_end", "references", "interval:g20_zibo_qingdao", "station:qingdao", "end_node"),
        rel("rel:interval_g3_s1_start", "references", "interval:g3_jinan_taian", "station:jinan_west", "start_node"),
        rel("rel:interval_g3_s1_end", "references", "interval:g3_jinan_taian", "station:taian_north", "end_node"),
        rel("rel:pass_etc_vehicle", "associates", "passage:sd_etc_001", "vehicle:lu_a12345", "passage_vehicle", status="confirmed"),
        rel("rel:pass_etc_obu", "references", "passage:sd_etc_001", "obu:sd_001", "used_obu"),
        rel("rel:pass_etc_entry", "references", "passage:sd_etc_001", "transaction:sd_etc_entry", "entry_transaction"),
        rel("rel:pass_etc_gantry", "references", "passage:sd_etc_001", "transaction:sd_etc_gantry", "gantry_transaction"),
        rel("rel:pass_etc_exit", "references", "passage:sd_etc_001", "transaction:sd_etc_exit", "exit_transaction"),
        rel("rel:tx_etc_entry_lane", "references", "transaction:sd_etc_entry", "lane:jinan_east_entry", "toll_lane"),
        rel("rel:tx_etc_gantry", "references", "transaction:sd_etc_gantry", "gantry:g20_zibo_qingdao", "toll_gantry"),
        rel("rel:tx_etc_exit_lane", "references", "transaction:sd_etc_exit", "lane:qingdao_exit", "toll_lane"),
        rel("rel:tx_etc_entry_vehicle_id", "references", "transaction:sd_etc_entry", "vehicle_id:sd_etc_entry", "vehicle_identification"),
        rel("rel:tx_etc_gantry_vehicle_id", "references", "transaction:sd_etc_gantry", "vehicle_id:sd_etc_gantry", "vehicle_identification"),
        rel("rel:tx_etc_exit_vehicle_id", "references", "transaction:sd_etc_exit", "vehicle_id:sd_etc_exit", "vehicle_identification"),
        rel("rel:pass_cpc1_vehicle", "associates", "passage:sd_cpc_001", "vehicle:lu_b67890", "passage_vehicle", status="confirmed"),
        rel("rel:pass_cpc1_card", "references", "passage:sd_cpc_001", "cpc_card:sd_001", "used_cpc_card"),
        rel("rel:pass_cpc1_entry", "references", "passage:sd_cpc_001", "transaction:sd_cpc_001_entry", "entry_transaction"),
        rel("rel:pass_cpc1_gantry", "references", "passage:sd_cpc_001", "transaction:sd_cpc_001_gantry", "gantry_transaction"),
        rel("rel:pass_cpc1_exit", "references", "passage:sd_cpc_001", "transaction:sd_cpc_001_exit", "exit_transaction"),
        rel("rel:tx_cpc1_entry_lane", "references", "transaction:sd_cpc_001_entry", "lane:jinan_west_entry", "toll_lane"),
        rel("rel:tx_cpc1_entry_card", "references", "transaction:sd_cpc_001_entry", "cpc_card:sd_001", "issued_cpc_card"),
        rel("rel:tx_cpc1_gantry", "references", "transaction:sd_cpc_001_gantry", "gantry:g3_jinan_taian", "toll_gantry"),
        rel("rel:tx_cpc1_exit_lane", "references", "transaction:sd_cpc_001_exit", "lane:taian_north_exit", "toll_lane"),
        rel("rel:tx_cpc1_exit_card", "references", "transaction:sd_cpc_001_exit", "cpc_card:sd_001", "recovered_cpc_card"),
        rel("rel:pass_cpc1_check", "references", "passage:sd_cpc_001", "check:sd_cpc_001", "vehicle_check"),
        rel("rel:pass_cpc1_second_charge", "contains", "passage:sd_cpc_001", "second_charge:sd_cpc_001", "second_charge_result"),
        rel("rel:check_cpc1_second_charge", "derives", "check:sd_cpc_001", "second_charge:sd_cpc_001", "check_basis"),
        rel("rel:pass_cpc2_vehicle", "associates", "passage:sd_cpc_002", "vehicle:lu_c24680", "passage_vehicle", status="confirmed"),
        rel("rel:pass_cpc2_card", "references", "passage:sd_cpc_002", "cpc_card:sd_001", "used_cpc_card"),
        rel("rel:pass_cpc2_entry", "references", "passage:sd_cpc_002", "transaction:sd_cpc_002_entry", "entry_transaction"),
        rel("rel:pass_cpc2_exit", "references", "passage:sd_cpc_002", "transaction:sd_cpc_002_exit", "exit_transaction"),
        rel("rel:tx_cpc2_entry_lane", "references", "transaction:sd_cpc_002_entry", "lane:zibo_entry", "toll_lane"),
        rel("rel:tx_cpc2_entry_card", "references", "transaction:sd_cpc_002_entry", "cpc_card:sd_001", "issued_cpc_card"),
        rel("rel:tx_cpc2_exit_lane", "references", "transaction:sd_cpc_002_exit", "lane:qingdao_exit", "toll_lane"),
        rel("rel:tx_cpc2_exit_card", "references", "transaction:sd_cpc_002_exit", "cpc_card:sd_001", "recovered_cpc_card"),
        rel("rel:pass_ticket_vehicle", "associates", "passage:sd_ticket_001", "vehicle:lu_c24680", "passage_vehicle", status="confirmed"),
        rel("rel:pass_ticket_medium", "references", "passage:sd_ticket_001", "paper_ticket:sd_001", "used_paper_ticket"),
        rel("rel:pass_ticket_entry", "references", "passage:sd_ticket_001", "transaction:sd_ticket_001_entry", "entry_transaction"),
        rel("rel:pass_ticket_exit", "references", "passage:sd_ticket_001", "transaction:sd_ticket_001_exit", "exit_transaction"),
        rel("rel:tx_ticket_entry_lane", "references", "transaction:sd_ticket_001_entry", "lane:jinan_west_entry", "toll_lane"),
        rel("rel:tx_ticket_entry_medium", "references", "transaction:sd_ticket_001_entry", "paper_ticket:sd_001", "issued_paper_ticket"),
        rel("rel:tx_ticket_exit_lane", "references", "transaction:sd_ticket_001_exit", "lane:taian_north_exit", "toll_lane"),
        rel("rel:tx_ticket_exit_medium", "references", "transaction:sd_ticket_001_exit", "paper_ticket:sd_001", "presented_paper_ticket"),
        rel("rel:pass_etc_split", "derives", "passage:sd_etc_001", "split:sd_etc_001", "passage_split", amount=money(168)),
        rel("rel:pass_cpc1_split", "derives", "passage:sd_cpc_001", "split:sd_cpc_001", "passage_split", amount=money(42)),
        rel("rel:pass_cpc2_split", "derives", "passage:sd_cpc_002", "split:sd_cpc_002", "passage_split", amount=money(86)),
        rel("rel:pass_ticket_split", "derives", "passage:sd_ticket_001", "split:sd_ticket_001", "passage_split", amount=money(66)),
        rel("rel:split_etc_basis", "contains", "split:sd_etc_001", "split_basis:sd_etc_001", "split_basis"),
        rel("rel:split_etc_detail_1", "contains", "split:sd_etc_001", "split_detail:sd_etc_01", "split_detail"),
        rel("rel:split_etc_detail_2", "contains", "split:sd_etc_001", "split_detail:sd_etc_02", "split_detail"),
        rel("rel:split_cpc1_detail", "contains", "split:sd_cpc_001", "split_detail:sd_cpc_01", "split_detail"),
        rel("rel:split_cpc2_detail", "contains", "split:sd_cpc_002", "split_detail:sd_cpc_02", "split_detail"),
        rel("rel:split_ticket_detail", "contains", "split:sd_ticket_001", "split_detail:sd_ticket_01", "split_detail"),
        rel("rel:detail_etc_interval_1", "references", "split_detail:sd_etc_01", "interval:g20_jinan_zibo", "toll_interval", amount=money(58)),
        rel("rel:detail_etc_interval_2", "references", "split_detail:sd_etc_02", "interval:g20_zibo_qingdao", "toll_interval", amount=money(110)),
        rel("rel:detail_cpc1_interval", "references", "split_detail:sd_cpc_01", "interval:g3_jinan_taian", "toll_interval", amount=money(42)),
        rel("rel:detail_cpc2_interval", "references", "split_detail:sd_cpc_02", "interval:g20_zibo_qingdao", "toll_interval", amount=money(86)),
        rel("rel:detail_ticket_interval", "references", "split_detail:sd_ticket_01", "interval:g3_jinan_taian", "toll_interval", amount=money(66)),
        rel("rel:split_etc_clearing", "derives", "split:sd_etc_001", "clearing:sd_etc_001", "clearing_result", amount=money(168)),
        rel("rel:split_cpc1_clearing", "derives", "split:sd_cpc_001", "clearing:sd_cpc_001", "clearing_result", amount=money(42)),
        rel("rel:split_cpc2_clearing", "derives", "split:sd_cpc_002", "clearing:sd_cpc_002", "clearing_result", amount=money(86)),
        rel("rel:split_ticket_clearing", "derives", "split:sd_ticket_001", "clearing:sd_ticket_001", "clearing_result", amount=money(66)),
        rel("rel:split_etc_invoice", "derives", "split:sd_etc_001", "invoice:sd_etc_001", "invoice_basis", amount=money(168)),
        rel("rel:clearing_etc_center", "associates", "clearing:sd_etc_001", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:clearing_cpc1_center", "associates", "clearing:sd_cpc_001", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:clearing_cpc2_center", "associates", "clearing:sd_cpc_002", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:clearing_ticket_center", "associates", "clearing:sd_ticket_001", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:account_tx_user_account", "associates", "account_tx:sd_recharge_001", "user_account:qilu", "affected_account", status="confirmed"),
        rel("rel:account_tx_entry", "derives", "account_tx:sd_recharge_001", "account_entry:sd_recharge_001", "bookkeeping_entry"),
        rel("rel:account_entry_account", "contains", "user_account:qilu", "account_entry:sd_recharge_001", "account_entry"),
        rel("rel:service_record_card", "references", "service_record:sd_etc_001_activation", "etc_card:sd_001", "business_subject"),
        rel("rel:service_record_handler", "associates", "service_record:sd_etc_001_activation", "party:sd_etc_issuer", "handled_by", status="confirmed"),
        rel("rel:consume_passage", "references", "consumption:sd_etc_001", "passage:sd_etc_001", "passage", amount=money(168)),
        rel("rel:consume_card_account", "associates", "consumption:sd_etc_001", "card_account:sd_etc_001", "charged_account", status="confirmed"),
        rel("rel:consume_bill", "derives", "consumption:sd_etc_001", "bill:sd_202608", "bill_source", amount=money(168)),
        rel("rel:bill_user", "associates", "bill:sd_202608", "user:qilu_logistics", "billed_user", status="active"),
        rel("rel:bill_settlement", "derives", "bill:sd_202608", "settlement:sd_202608", "bill_settlement", amount=money(168)),
        rel("rel:settlement_reconciliation", "derives", "settlement:sd_202608", "reconciliation:sd_202608", "reconciliation_source"),
        rel("rel:stock_movement_account", "associates", "stock_movement:sd_cpc_002", "stock_account:sd_issuer", "affected_stock", status="confirmed"),
        rel("rel:stock_movement_item", "references", "stock_movement:sd_cpc_002", "cpc_card:sd_002", "stock_item"),
        rel("rel:account_tx_summary", "derives", "account_tx:sd_recharge_001", "summary:sd_20260801", "business_day_summary", amount=money(1000)),
        rel("rel:fee_module_base", "contains", "fee_module:sd_2026", "fee_rule:sd_base", "fee_rule"),
        rel("rel:fee_module_discount", "contains", "fee_module:sd_2026", "fee_rule:sd_etc_discount", "fee_rule"),
        rel("rel:fee_module_provincial", "contains", "fee_module:sd_2026", "fee_rule:sd_provincial", "fee_rule"),
        rel("rel:fee_base_interval", "references", "fee_rule:sd_base", "interval:g20_jinan_zibo", "applies_to"),
        rel("rel:fee_base_provincial", "derives", "fee_rule:sd_base", "fee_rule:sd_provincial", "rate_basis"),
        rel("rel:interval_provincial", "derives", "interval:g20_jinan_zibo", "fee_rule:sd_provincial", "interval_basis"),
        rel("rel:control_vehicle", "references", "control:lu_c24680_watch", "vehicle:lu_c24680", "controlled_object"),
        rel("rel:parameter_gantry", "references", "parameter:g20_gantry", "gantry:g20_zibo_qingdao", "configured_facility"),
    ]
    return objects, relations


def validate_graph(
    oms_root: Path,
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    business_model = load_yaml(oms_root / "model.yaml")
    result = ModelValidator(
        load_yaml(oms_root / "ontology.yaml"),
        {"schema": "oms.data.objects.v2", "objects": objects},
        {"schema": "oms.data.relations.v2", "relations": relations},
        business_model,
    ).validate()
    if result.errors:
        raise ValueError("\n".join(result.errors))
    object_types = {item["type"] for item in objects}
    missing_object_types = set(business_model.get("object_types", {})) - object_types
    relation_types = {item["type"] for item in relations}
    missing_relation_types = set(business_model.get("relation_types", {})) - relation_types
    if missing_object_types or missing_relation_types:
        messages = []
        if missing_object_types:
            messages.append("missing seed object types: " + ", ".join(sorted(missing_object_types)))
        if missing_relation_types:
            messages.append("missing seed relation types: " + ", ".join(sorted(missing_relation_types)))
        raise ValueError("\n".join(messages))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=OMS_ROOT)
    parser.add_argument(
        "--confirm-clear",
        action="store_true",
        help="replace all Object/Relation records and clear the action log",
    )
    args = parser.parse_args()
    oms_root = args.root.resolve()
    objects, relations = build_graph()
    validate_graph(oms_root, objects, relations)

    type_counts = Counter(item["type"] for item in objects)
    print(f"Validated {len(objects)} objects and {len(relations)} relations")
    print("Object types: " + ", ".join(f"{key}={value}" for key, value in sorted(type_counts.items())))
    if not args.confirm_clear:
        print("Dry run only; pass --confirm-clear to replace the database")
        return 0

    _, repository, _ = load_domain(oms_root)
    try:
        adapter = repository.adapter_for("Object")
        adapter.replace_graph(objects, relations)
        with sqlite3.connect(adapter.database_path) as connection:
            connection.execute("DELETE FROM action_log")
            connection.commit()
    finally:
        repository.close()
    print(f"Seeded {len(objects)} objects and {len(relations)} relations into {oms_root / 'data' / 'oms.db'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
