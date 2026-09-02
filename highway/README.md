# Highway 高速联网收费领域

Highway 以一次车辆通行为经营主链，并把账户、清分结算、设施运营和费率控制拆成独立业务域。所有领域使用 UOM 的 Object/Relation 图模型，共享一份 SQLite 图数据。

## 业务主链

```text
vehicle / toll_medium
          |
          v
       passage -> passage_event
          |
          v
        charge <- payment
```

五个平级业务域都位于 [`domains`](domains)。其中
[`passage_charging`](domains/passage_charging) 是 `highway.passage_charging` 通行收费域，拥有车辆、通行介质、通行事实、计费、支付以及特殊查验和计费调整对象。账户、设施和费率对象在该域中只是 Action 输入和关系端点所需的跨域锚点。

- `passage_charging`：车辆通行、计费和支付。
- `customer_accounts`：账户、电子钱包、账户记账、客服办理、资金交易和账单结算。
- `clearing_settlement`：拆分、清分、发票依据、收款汇总、通行费上缴和实际划拨。
- `facility_operations`：收费公路、路段、收费单元、收费站、门架、车道、设备及路网拓扑。
- `pricing_control`：费率版本、车型费率、计费路径、计费明细和业务控制记录。

完整组合模型共有 36 个对象类型、5 个关系类型和 9 个只读 Function；各域 Action 通过 ChangeSet 写入同一张图。对象所有权、跨域链路和运行时规则详见 [`domains/README.md`](domains/README.md)。

## 关键语义

OBU、ETC 卡、CPC 卡和纸券统一为 `toll_medium`，用 `medium_kind` 区分。车辆与 OBU/ETC 卡的长期绑定使用 `associates`；某次通行实际使用介质则使用 `passage -> references -> toll_medium`。CPC 卡的入口发放和出口回收由 `passage_event` 引用介质，不建立车辆长期绑定。

入口、门架和出口事实统一为 `passage_event`，用 `event_kind` 区分交易与识别，用 `stage` 区分通行阶段。`passId`、`vehicleId`、`obuId`、`laneId` 等外键语义优先表达为 Relation，而不是重复字符串属性。

OBU、ETC 卡、发行机构、持有人、用户账户、卡账户、扣款账户和电子钱包均保持为可独立追溯的对象；配套、持有、包含和资金流向通过带角色的 Relation 表达。计费路径引用路网节点的关系显式记录 `sequence` 和 `mileage`，聚合结果可以逐条追加多个来源事实。

费率版本、收费单元费率、计费路径和计费明细由 `pricing_control` 维护，计费结果引用实际依据。计费后的拆分、清分、发票依据、代收上缴和实际划拨由 `clearing_settlement` 维护，因此 `passage_charging` 的通行经济函数只计算应收、优惠、计费和支付，不冒充清分结算口径。

## 应用运行时

Highway Web 工作台使用五域只读组合模型展示完整业务图和空间视图。Agent 根据用户意图按需加载单域或多域。页面汇总各域 Action，但写入始终路由到 Action 所属领域；通用模型编辑必须选择一个明确领域。

```text
workbench -> 五域只读组合 -> 完整图查询/地图/模型浏览
agent     -> 按会话选域    -> 单域或多域推理
action    -> 唯一所属域    -> preview -> confirm -> ChangeSet
```

## 文件结构

```text
contracts/highway_core.yaml  跨域共享语义契约，不是运行时业务域
domains/                     五个平级、可独立加载的业务域
  passage_charging/          通行收费模型、Action、Function 及绑定
  customer_accounts/         客户账户域
  clearing_settlement/       清分结算域
  facility_operations/       设施运营域
  pricing_control/           费率控制域
data/graph.db                共享 SQLite Object/Relation 图
app/services/spatial_view.py 跨域设施坐标和通行路线投影
integrations/amap.py         高德地图配置和路线规划适配器
scripts/seed_shandong.py     覆盖五域完整模型的山东 seed
app/                         Web 工作台和 OAG Agent 接口
docs/                        V3.0/V3.1/V3.2 领域资料
```

## 验证与 seed

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --with pyyaml \
  python highway/scripts/seed_shandong.py
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --with pyyaml \
  python highway/scripts/seed_shandong.py --confirm-clear
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --with pyyaml \
  python -m unittest discover -s highway/tests -v
node --check highway/app/static/app.js
```

seed 脚本先组合五域模型，再校验全部对象、关系、端点和属性；只有显式传入 `--confirm-clear` 才替换数据库。

`highway/` 是应用边界，不是第六个领域。领域发现只加载 `domains/*/model.yaml`；`contracts/` 只在编译时被具体领域按需导入。
