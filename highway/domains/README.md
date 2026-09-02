# Highway 业务域

Highway 按业务责任拆成五个平级、可独立加载的业务域：

| 领域 ID | 负责的语义 | 自有对象 |
| --- | --- | --- |
| `highway.passage_charging` | 车辆一次通行形成计费、支付及特殊处理 | `party`、`vehicle`、`toll_medium`、`passage`、`passage_event`、`charge`、`payment`、`inspection_result`、`charge_adjustment` |
| `highway.customer_accounts` | 客户账户、电子钱包、客服办理、资金交易和账单结算 | `account`、`wallet`、`account_entry`、`service_operation`、`fund_transaction`、`bill`、`bill_settlement` |
| `highway.clearing_settlement` | 通行费拆分、清分、发票依据、收款、上缴和实际划拨 | `split_result`、`clearing_result`、`invoice_basis`、`collection_summary`、`remittance`、`settlement`、`allocation` |
| `highway.facility_operations` | 道路设施组成和路网拓扑 | `toll_road`、`section`、`toll_interval`、`toll_station`、`toll_gantry`、`toll_lane`、`equipment` |
| `highway.pricing_control` | 费率发布、计费路径/明细和车辆、介质、设备控制 | `rate_version`、`rate_rule`、`interval_rate`、`pricing_path`、`charge_breakdown`、`control_record` |

各域共享 `../../data/graph.db`，同一个对象只保存一份。跨域对象通过
[`../contracts/highway_core.yaml`](../contracts/highway_core.yaml) 与 `domains/` 平级，作为编译期语义锚点导入，不是运行时业务域，也不等于导入它的领域拥有全部定义。

```text
facility_operations  road -> section -> interval/station/gantry/lane/equipment
passage_charging     vehicle/medium -> passage -> event -> charge <- payment
customer_accounts    account -> wallet/account_entry -> fund_transaction -> bill
clearing_settlement  charge -> split_result -> clearing_result/invoice_basis -> settlement -> allocation
                     passage -> collection_summary -> remittance
pricing_control      rate_version -> interval_rate -> charge_breakdown <- charge
```

## 运行时边界

- 每个领域单独加载时拥有自己的本体、Function、Action 和可写 Repository。
- Highway Web 工作台将五个域组合成只读模型，用于完整图查询、地图和模型浏览。
- Agent 根据用户意图按会话选择一个域或组合多个域；组合查询不暴露写操作。
- UI 汇总五个域的 Action，但预览和执行始终路由到 Action 所属的单一领域。
- 通用对象、关系和模型编辑要求明确选择所属领域；当前 MVP 不执行跨域事务。

## 确定性 Function

| 领域 | Function |
| --- | --- |
| `highway.passage_charging` | `get_business_overview`、`get_passage_trace`、`find_incomplete_passages`、`get_passage_economics` |
| `customer_accounts` | `get_account_ledger` |
| `clearing_settlement` | `get_settlement_trace` |
| `facility_operations` | `get_facility_overview` |
| `pricing_control` | `get_pricing_control_overview`、`get_passage_fare_basis` |

这些 Function 只读 Repository。写入由各域 Action 生成并校验 ChangeSet 后完成。

## 跨域契约

- 对象 ID 是共享图中的全局身份。
- 契约不声明 Repository；领域负责把导入语义绑定到数据源。
- 关系公共语义由契约定义，领域可以收窄端点和属性用途。
- UOM 在编译前导入契约；OAG 只接收编译后的单域或组合本体。
- 模型编辑器不会把导入定义展开写回领域 `model.yaml`。
