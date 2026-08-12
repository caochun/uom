# OMS 高速联网收费领域模型

`oms` 是面向 OAG Agent 的高速联网收费领域。它用两个稳定的本体概念保存业务图：

- `Object`：可独立识别和追溯的主体、设施、业务事实或计算结果。
- `Relation`：两个 Object 之间由业务行为建立或确认的有方向联系。

`model.yaml` 是业务语义层，不是元模型。它定义业务类型、可计算属性、关系端点约束和模型驱动的操作；
`ontology.yaml` 只定义 Object/Relation 的稳定记录契约和 OAG 工具。

## V3.4 抽象

V3.1 文档同时描述业务实体、设备、参数、名单和数据库属性。为便于 LLM 理解，OMS 保留业务主干，
只把生命周期和业务行为相同的概念收敛到 `category` 或 `details`。OBU、ETC 卡、CPC 卡，以及资金账户、
库存账户等角色不同的对象保持独立类型：

```text
主体与介质：party / user / vehicle / obu / etc_card / cpc_card / paper_ticket
路网设施：toll_road / section / toll_interval / toll_station / toll_plaza /
          toll_lane / toll_gantry / service_facility / business_device
通行清分：passage / toll_transaction / vehicle_id_record /
          vehicle_check_result / second_charge_result / split_record /
          split_basis / split_detail / clearing_result / invoice_basis_data
客服资金：customer_service_record / user_account / card_account / stock_account /
          account_transaction / account_entry / consumption_detail / bill / bill_settlement / stock_movement /
          business_day_summary / reconciliation_result
费率控制：fee_module / fee_rule / control_record / operating_parameter
```

五种关系保持稳定：

| 关系 | 含义 | 示例 |
| --- | --- | --- |
| `route_next` | 两个路网设施在某行驶方向上相邻 | 收费站的下一节点是门架 |
| `contains` | 整体包含依附的组成部分 | 公路包含路段，路段包含收费站 |
| `references` | 业务事实引用独立对象的信息 | 通行引用入口、门架、出口交易 |
| `associates` | 两个独立对象之间存在业务联系 | 车辆长期关联 OBU 和 ETC 卡 |
| `derives` | 来源事实产生计算或汇总结果 | 通行派生拆分，拆分派生清分 |

`derives` 统一使用“来源对象 -> 结果对象”的方向。相同生命周期的硬件、名单和运行参数不再为每个数据库表
建立类型，而是在 `business_device`、`control_record` 或 `operating_parameter` 中用 `category` 表达种类。
名单成员和运行配置不会混为同一对象。

V3.1 的 `RoadNode` 不再复制收费站和门架的身份，`NodeRelation` 也不建立中间业务对象。收费站和门架
本身就是路网节点，二者之间的 `route_next` 有向边表达拓扑；收费单元通过 `start_node`、`end_node`
引用边界节点。这样既能计算路径，又不会出现设施对象与路网节点对象需要同步的问题。

来源文档中的 `passId`、`vehicleId`、`obuId`、`laneId` 等字段用于识别对象联系，在本模型中转成关系，
不再作为记录属性。若一项联系可沿图唯一推导，也不建立捷径边。例如入口交易只指向入口车道，收费站由
`transaction -> toll_lane <- toll_station` 推导；交易所属车辆和介质由
`transaction <- passage -> vehicle / medium` 推导。交易仍保留计费车型、轴数、金额、交易结果和时间，
因为这些是当时发生的事实，不能用车辆或设施档案代替。

## 文件

```text
ontology.yaml         Object / Relation 本体契约、函数和 Agent 交互策略
model.yaml            业务类型、Property、关系和模型驱动 Action
data/oms.db           Object / Relation 实例的唯一 SQLite 数据源
functions/__init__.py OAG adapter 和领域函数注册入口
business.py           通行概览、通行追溯和不完整通行查询
actions.py            将 Action 编译为校验后的 ChangeSet
store.py              模型扩展和数据 ChangeSet 的预览、提交服务
scripts/              模型和实例数据校验
```

## 业务主链

```text
toll_road ->contains-> section ->contains-> toll_station ->contains-> toll_lane
passage ->associates-> vehicle
vehicle ->associates(bound_obu)-> obu
vehicle ->associates(bound_etc_card)-> etc_card
obu ->associates(paired_etc_card)-> etc_card
passage ->references(used_obu / used_cpc_card / used_paper_ticket)-> 通行介质
entry/exit transaction ->references-> toll_lane
gantry transaction ->references-> toll_gantry
entry_transaction ->references(issued_cpc_card)-> cpc_card
exit_transaction ->references(recovered_cpc_card)-> cpc_card
passage ->references-> entry/gantry/exit toll_transaction
toll_transaction ->references(vehicle_identification)-> vehicle_id_record
passage ->references-> vehicle_check_result ->derives-> second_charge_result
passage ->contains-> second_charge_result
passage ->derives-> split_record ->derives-> clearing_result
split_record ->contains-> split_basis / split_detail
split_detail ->references-> toll_interval
consumption_detail ->references-> passage
consumption_detail ->associates-> card_account
consumption_detail ->derives-> bill ->derives-> bill_settlement
account_transaction ->derives-> account_entry <-contains- user_account / card_account
station / gantry ->route_next-> station / gantry
toll_interval ->references(start_node / end_node)-> station / gantry
fee_rule ->references(applies_to)-> toll_interval
```

对象保留原始业务事实；后续计算、拆分、结算和对账通过新对象及关系追溯，不覆盖来源对象。
这里的“覆盖 V3.1”指核心业务语义和追溯路径可表达，不是把文档中的约 138 个实体或数据库字段一对一复制成类型。

空间设施可使用 `longitude`、`latitude` 和 `coordinate_system` 保存代表点，三者必须同时出现。山东 seed
中的收费站和服务设施坐标取自高德 POI，门架和收费单元代表点取自高德驾车路线，坐标系统一为
`GCJ-02`。收费公路、路段和收费单元本质上是线或区间；当前 MVP 保存的是代表点，完整线路几何应由
后续地图或 GIS 数据源提供，不能把代表点解释成对象的全部边界。

对象详情抽屉通过关系图即时生成空间视图。点状设施使用自身坐标；收费单元按
`start_node -> route_next -> end_node` 生成线路；路段和收费公路组合所包含收费单元的线路；通行记录按
交易时间和关联设施生成入口、门架、出口事件链。配置 `AMAP_API_KEY`、`AMAP_SECURITY_KEY` 和
`AMAP_WEB_SERVICE_KEY` 后，前端加载高德底图，后端用高德驾车规划细化线路。规划线路仅是派生展示，
不写入业务图，也不作为车辆 GPS 轨迹或权威路网边界。

## 模型驱动操作

`actions` 不是第三个本体概念，也不写入业务图。它描述用户意图如何生成 Object/Relation ChangeSet，
前端和 Agent 共用同一套定义。写入流程为：

```text
get_available_actions -> preview_action -> 用户确认 -> apply_action
```

模型扩展仍使用 `preview_changes` / `apply_changes`。所有写入先预览，预览结果失效后不能直接提交。

## 验证

需要 PyYAML 的 Python 环境：

```bash
python3 oms/scripts/validate_model.py --root oms
python3 -m unittest discover -s oms/tests -v
node --check app/static/app.js
```

山东 seed 覆盖 `model.yaml` 中全部对象类型和关系类型；如果新增类型却没有代表性实例，seed 校验会失败：

```bash
python3 oms/scripts/seed_shandong.py
python3 oms/scripts/seed_shandong.py --confirm-clear
```

`data/oms.db` 中已有实例不会被模型重建自动清空；未知 `type` 仍可作为开放词汇保留。新登记对象和关系应
优先使用 Action 或经过预览的 ChangeSet。
