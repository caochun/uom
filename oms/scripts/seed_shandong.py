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


def money(amount: float) -> dict[str, Any]:
    return {"amount": amount, "currency": "CNY"}


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
        obj("user_account:qilu", "user_account", "齐鲁示例物流用户资金账户", {
            "reference_no": "MOCK-UA-SD-001", "status": "active",
            "details": {"balance": money(1000)},
        }),
        obj("card_account:sd_etc_001", "card_account", "鲁A12345 ETC 卡资金账户", {
            "reference_no": "MOCK-CA-SD-001", "status": "active",
            "details": {"balance": money(832)},
        }),
        obj("stock_account:sd_issuer", "stock_account", "山东 ETC 发行机构库存账户", {
            "category": "institution", "reference_no": "MOCK-SA-SD-001", "status": "active",
        }),
        obj("toll_road:g20_sd", "toll_road", "G20 青银高速山东段", {
            "code": "G20-SD-MOCK", "status": "operating",
        }, "shandong", "g20"),
        obj("toll_road:g3_sd", "toll_road", "G3 京台高速山东段", {
            "code": "G3-SD-MOCK", "status": "operating",
        }, "shandong", "g3"),
        obj("section:g20_jinan_zibo", "section", "G20 济南至淄博段", {
            "code": "G20-SD-JN-ZB", "mileage": 95.0, "status": "operating",
        }),
        obj("section:g20_zibo_qingdao", "section", "G20 淄博至青岛段", {
            "code": "G20-SD-ZB-QD", "mileage": 210.0, "status": "operating",
        }),
        obj("section:g3_jinan_taian", "section", "G3 济南至泰安段", {
            "code": "G3-SD-JN-TA", "mileage": 78.0, "status": "operating",
        }),
        obj("interval:g20_jinan_zibo", "toll_interval", "G20 济南至淄博收费单元", {
            "code": "MOCK-TI-G20-01", "direction": "青岛方向", "mileage": 95.0,
        }),
        obj("interval:g20_zibo_qingdao", "toll_interval", "G20 淄博至青岛收费单元", {
            "code": "MOCK-TI-G20-02", "direction": "青岛方向", "mileage": 210.0,
        }),
        obj("interval:g3_jinan_taian", "toll_interval", "G3 济南至泰安收费单元", {
            "code": "MOCK-TI-G3-01", "direction": "台北方向", "mileage": 78.0,
        }),
        obj("station:jinan_east", "toll_station", "济南东收费站（Mock）", {
            "code": "MOCK-SD-JN-E", "status": "operating",
        }),
        obj("station:zibo", "toll_station", "淄博收费站（Mock）", {
            "code": "MOCK-SD-ZB", "status": "operating",
        }),
        obj("station:qingdao", "toll_station", "青岛收费站（Mock）", {
            "code": "MOCK-SD-QD", "status": "operating",
        }),
        obj("station:jinan_west", "toll_station", "济南西收费站（Mock）", {
            "code": "MOCK-SD-JN-W", "status": "operating",
        }),
        obj("station:taian_north", "toll_station", "泰安北收费站（Mock）", {
            "code": "MOCK-SD-TA-N", "status": "operating",
        }),
        obj("gantry:g20_jinan_zibo", "toll_gantry", "G20 济南淄博门架（Mock）", {
            "code": "MOCK-GANTRY-G20-01", "direction": "青岛方向", "status": "operating",
        }),
        obj("gantry:g20_zibo_qingdao", "toll_gantry", "G20 淄博青岛门架（Mock）", {
            "code": "MOCK-GANTRY-G20-02", "direction": "青岛方向", "status": "operating",
        }),
        obj("gantry:g3_jinan_taian", "toll_gantry", "G3 济南泰安门架（Mock）", {
            "code": "MOCK-GANTRY-G3-01", "direction": "台北方向", "status": "operating",
        }),
        obj("passage:sd_etc_001", "passage", "山东 ETC 通行 001", {
            "reference_no": "MOCK-PASS-SD-ETC-001", "mode": "etc",
            "occurred_on": "2026-08-01", "status": "completed",
        }, "shandong", "etc_passage"),
        obj("transaction:sd_etc_entry", "toll_transaction", "ETC 通行 001 入口交易", {
            "reference_no": "MOCK-TX-SD-ETC-E", "stage": "entry",
            "occurred_on": "2026-08-01", "status": "recorded",
        }),
        obj("transaction:sd_etc_gantry", "toll_transaction", "ETC 通行 001 门架交易", {
            "reference_no": "MOCK-TX-SD-ETC-G", "stage": "gantry", "amount": money(92),
            "occurred_on": "2026-08-01", "status": "recorded",
        }),
        obj("transaction:sd_etc_exit", "toll_transaction", "ETC 通行 001 出口交易", {
            "reference_no": "MOCK-TX-SD-ETC-X", "stage": "exit", "amount": money(168),
            "occurred_on": "2026-08-01", "status": "recorded",
        }),
        obj("passage:sd_cpc_001", "passage", "山东 CPC 通行 001", {
            "reference_no": "MOCK-PASS-SD-CPC-001", "mode": "mtc",
            "occurred_on": "2026-08-02", "status": "completed",
        }, "shandong", "cpc_passage"),
        obj("transaction:sd_cpc_001_entry", "toll_transaction", "CPC 通行 001 入口交易", {
            "reference_no": "MOCK-TX-SD-CPC1-E", "stage": "entry",
            "occurred_on": "2026-08-02", "status": "recorded",
        }),
        obj("transaction:sd_cpc_001_gantry", "toll_transaction", "CPC 通行 001 门架交易", {
            "reference_no": "MOCK-TX-SD-CPC1-G", "stage": "gantry", "amount": money(24),
            "occurred_on": "2026-08-02", "status": "recorded",
        }),
        obj("transaction:sd_cpc_001_exit", "toll_transaction", "CPC 通行 001 出口交易", {
            "reference_no": "MOCK-TX-SD-CPC1-X", "stage": "exit", "amount": money(45),
            "occurred_on": "2026-08-02", "status": "recorded",
        }),
        obj("passage:sd_cpc_002", "passage", "山东 CPC 通行 002", {
            "reference_no": "MOCK-PASS-SD-CPC-002", "mode": "mtc",
            "occurred_on": "2026-08-05", "status": "completed",
        }, "shandong", "cpc_passage", "medium_reuse"),
        obj("transaction:sd_cpc_002_entry", "toll_transaction", "CPC 通行 002 入口交易", {
            "reference_no": "MOCK-TX-SD-CPC2-E", "stage": "entry",
            "occurred_on": "2026-08-05", "status": "recorded",
        }),
        obj("transaction:sd_cpc_002_exit", "toll_transaction", "CPC 通行 002 出口交易", {
            "reference_no": "MOCK-TX-SD-CPC2-X", "stage": "exit", "amount": money(86),
            "occurred_on": "2026-08-05", "status": "recorded",
        }),
        obj("split:sd_etc_001", "split_record", "ETC 通行 001 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-ETC-001", "amount": money(168),
            "occurred_on": "2026-08-02", "status": "calculated",
        }),
        obj("split:sd_cpc_001", "split_record", "CPC 通行 001 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-CPC-001", "amount": money(45),
            "occurred_on": "2026-08-03", "status": "calculated",
        }),
        obj("split:sd_cpc_002", "split_record", "CPC 通行 002 省内拆分", {
            "reference_no": "MOCK-SPLIT-SD-CPC-002", "amount": money(86),
            "occurred_on": "2026-08-06", "status": "calculated",
        }),
        obj("split_detail:sd_etc_01", "split_detail", "ETC 通行 001 济南淄博明细", {
            "amount": money(58), "details": {"sequence": 1},
        }),
        obj("split_detail:sd_etc_02", "split_detail", "ETC 通行 001 淄博青岛明细", {
            "amount": money(110), "details": {"sequence": 2},
        }),
        obj("split_detail:sd_cpc_01", "split_detail", "CPC 通行 001 济南泰安明细", {
            "amount": money(45), "details": {"sequence": 1},
        }),
        obj("split_detail:sd_cpc_02", "split_detail", "CPC 通行 002 淄博青岛明细", {
            "amount": money(86), "details": {"sequence": 1},
        }),
        obj("clearing:sd_etc_001", "clearing_result", "ETC 通行 001 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-ETC-001", "amount": money(168),
            "period": "2026-08", "occurred_on": "2026-08-03", "status": "confirmed",
        }),
        obj("clearing:sd_cpc_001", "clearing_result", "CPC 通行 001 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-CPC-001", "amount": money(45),
            "period": "2026-08", "occurred_on": "2026-08-04", "status": "confirmed",
        }),
        obj("clearing:sd_cpc_002", "clearing_result", "CPC 通行 002 清分结果", {
            "reference_no": "MOCK-CLEAR-SD-CPC-002", "amount": money(86),
            "period": "2026-08", "occurred_on": "2026-08-07", "status": "confirmed",
        }),
        obj("invoice:sd_etc_001", "invoice_basis_data", "ETC 通行 001 发票基础数据", {
            "reference_no": "MOCK-INV-SD-ETC-001", "amount": money(168),
            "occurred_on": "2026-08-03", "status": "ready",
        }),
        obj("account_tx:sd_recharge_001", "account_transaction", "齐鲁示例物流充值", {
            "category": "recharge", "reference_no": "MOCK-AT-SD-001", "amount": money(1000),
            "occurred_on": "2026-07-30", "status": "completed",
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
        rel("rel:g20_s1_gantry", "contains", "section:g20_jinan_zibo", "gantry:g20_jinan_zibo", "toll_gantry"),
        rel("rel:g20_s2_gantry", "contains", "section:g20_zibo_qingdao", "gantry:g20_zibo_qingdao", "toll_gantry"),
        rel("rel:g3_s1_gantry", "contains", "section:g3_jinan_taian", "gantry:g3_jinan_taian", "toll_gantry"),
        rel("rel:pass_etc_vehicle", "associates", "passage:sd_etc_001", "vehicle:lu_a12345", "passage_vehicle", status="confirmed"),
        rel("rel:pass_etc_obu", "references", "passage:sd_etc_001", "obu:sd_001", "used_obu"),
        rel("rel:pass_etc_entry", "references", "passage:sd_etc_001", "transaction:sd_etc_entry", "entry_transaction"),
        rel("rel:pass_etc_gantry", "references", "passage:sd_etc_001", "transaction:sd_etc_gantry", "gantry_transaction"),
        rel("rel:pass_etc_exit", "references", "passage:sd_etc_001", "transaction:sd_etc_exit", "exit_transaction"),
        rel("rel:tx_etc_entry_station", "references", "transaction:sd_etc_entry", "station:jinan_east", "toll_station"),
        rel("rel:tx_etc_gantry", "references", "transaction:sd_etc_gantry", "gantry:g20_zibo_qingdao", "toll_gantry"),
        rel("rel:tx_etc_exit_station", "references", "transaction:sd_etc_exit", "station:qingdao", "toll_station"),
        rel("rel:pass_cpc1_vehicle", "associates", "passage:sd_cpc_001", "vehicle:lu_b67890", "passage_vehicle", status="confirmed"),
        rel("rel:pass_cpc1_card", "references", "passage:sd_cpc_001", "cpc_card:sd_001", "used_cpc_card"),
        rel("rel:pass_cpc1_entry", "references", "passage:sd_cpc_001", "transaction:sd_cpc_001_entry", "entry_transaction"),
        rel("rel:pass_cpc1_gantry", "references", "passage:sd_cpc_001", "transaction:sd_cpc_001_gantry", "gantry_transaction"),
        rel("rel:pass_cpc1_exit", "references", "passage:sd_cpc_001", "transaction:sd_cpc_001_exit", "exit_transaction"),
        rel("rel:tx_cpc1_entry_station", "references", "transaction:sd_cpc_001_entry", "station:jinan_west", "toll_station"),
        rel("rel:tx_cpc1_entry_card", "references", "transaction:sd_cpc_001_entry", "cpc_card:sd_001", "issued_cpc_card"),
        rel("rel:tx_cpc1_gantry", "references", "transaction:sd_cpc_001_gantry", "gantry:g3_jinan_taian", "toll_gantry"),
        rel("rel:tx_cpc1_exit_station", "references", "transaction:sd_cpc_001_exit", "station:taian_north", "toll_station"),
        rel("rel:tx_cpc1_exit_card", "references", "transaction:sd_cpc_001_exit", "cpc_card:sd_001", "recovered_cpc_card"),
        rel("rel:pass_cpc2_vehicle", "associates", "passage:sd_cpc_002", "vehicle:lu_c24680", "passage_vehicle", status="confirmed"),
        rel("rel:pass_cpc2_card", "references", "passage:sd_cpc_002", "cpc_card:sd_001", "used_cpc_card"),
        rel("rel:pass_cpc2_entry", "references", "passage:sd_cpc_002", "transaction:sd_cpc_002_entry", "entry_transaction"),
        rel("rel:pass_cpc2_exit", "references", "passage:sd_cpc_002", "transaction:sd_cpc_002_exit", "exit_transaction"),
        rel("rel:tx_cpc2_entry_station", "references", "transaction:sd_cpc_002_entry", "station:zibo", "toll_station"),
        rel("rel:tx_cpc2_entry_card", "references", "transaction:sd_cpc_002_entry", "cpc_card:sd_001", "issued_cpc_card"),
        rel("rel:tx_cpc2_exit_station", "references", "transaction:sd_cpc_002_exit", "station:qingdao", "toll_station"),
        rel("rel:tx_cpc2_exit_card", "references", "transaction:sd_cpc_002_exit", "cpc_card:sd_001", "recovered_cpc_card"),
        rel("rel:pass_etc_split", "derives", "passage:sd_etc_001", "split:sd_etc_001", "passage_split", amount=money(168)),
        rel("rel:pass_cpc1_split", "derives", "passage:sd_cpc_001", "split:sd_cpc_001", "passage_split", amount=money(45)),
        rel("rel:pass_cpc2_split", "derives", "passage:sd_cpc_002", "split:sd_cpc_002", "passage_split", amount=money(86)),
        rel("rel:split_etc_detail_1", "contains", "split:sd_etc_001", "split_detail:sd_etc_01", "split_detail"),
        rel("rel:split_etc_detail_2", "contains", "split:sd_etc_001", "split_detail:sd_etc_02", "split_detail"),
        rel("rel:split_cpc1_detail", "contains", "split:sd_cpc_001", "split_detail:sd_cpc_01", "split_detail"),
        rel("rel:split_cpc2_detail", "contains", "split:sd_cpc_002", "split_detail:sd_cpc_02", "split_detail"),
        rel("rel:detail_etc_interval_1", "references", "split_detail:sd_etc_01", "interval:g20_jinan_zibo", "toll_interval", amount=money(58)),
        rel("rel:detail_etc_interval_2", "references", "split_detail:sd_etc_02", "interval:g20_zibo_qingdao", "toll_interval", amount=money(110)),
        rel("rel:detail_cpc1_interval", "references", "split_detail:sd_cpc_01", "interval:g3_jinan_taian", "toll_interval", amount=money(45)),
        rel("rel:detail_cpc2_interval", "references", "split_detail:sd_cpc_02", "interval:g20_zibo_qingdao", "toll_interval", amount=money(86)),
        rel("rel:split_etc_clearing", "derives", "split:sd_etc_001", "clearing:sd_etc_001", "clearing_result", amount=money(168)),
        rel("rel:split_cpc1_clearing", "derives", "split:sd_cpc_001", "clearing:sd_cpc_001", "clearing_result", amount=money(45)),
        rel("rel:split_cpc2_clearing", "derives", "split:sd_cpc_002", "clearing:sd_cpc_002", "clearing_result", amount=money(86)),
        rel("rel:split_etc_invoice", "derives", "split:sd_etc_001", "invoice:sd_etc_001", "invoice_basis", amount=money(168)),
        rel("rel:clearing_etc_center", "associates", "clearing:sd_etc_001", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:clearing_cpc1_center", "associates", "clearing:sd_cpc_001", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:clearing_cpc2_center", "associates", "clearing:sd_cpc_002", "party:sd_network_center", "clearing_operator", status="confirmed"),
        rel("rel:account_tx_user_account", "associates", "account_tx:sd_recharge_001", "user_account:qilu", "affected_account", status="confirmed"),
        rel("rel:consume_passage", "references", "consumption:sd_etc_001", "passage:sd_etc_001", "passage", amount=money(168)),
        rel("rel:consume_card", "references", "consumption:sd_etc_001", "etc_card:sd_001", "payment_card"),
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
        rel("rel:control_vehicle", "references", "control:lu_c24680_watch", "vehicle:lu_c24680", "controlled_object"),
        rel("rel:parameter_gantry", "references", "parameter:g20_gantry", "gantry:g20_zibo_qingdao", "configured_facility"),
    ]
    return objects, relations


def validate_graph(
    oms_root: Path,
    objects: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    result = ModelValidator(
        load_yaml(oms_root / "ontology.yaml"),
        {"schema": "oms.data.objects.v2", "objects": objects},
        {"schema": "oms.data.relations.v2", "relations": relations},
        load_yaml(oms_root / "model.yaml"),
    ).validate()
    if result.errors:
        raise ValueError("\n".join(result.errors))


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
