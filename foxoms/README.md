# FoxOMS Domain

FoxOMS 是一个逐步定义中的 UOM 领域。目前定义了业务主体、商机、招标事项和投标记录，
可以表达业务主体以特定角色参与业务，以及商机、招标事项和投标记录之间的包含结构。
中标投标可以形成框架协议或项目合同：框架协议包含后续订单，项目合同定义项目或任务。
人员、软件和硬件作为独立资源类型管理，并通过统一的投入关系配置到订单或项目/任务。
知识资产通过一条带角色的关系表达为订单或项目/任务所需的条件或产生的成果。
合同或订单可以包含多张发票，回款通过带金额的核销关系分配到发票；发票和回款主体
从合同或订单参与方推导，不重复保存。
三类资源的具体管理属性、业务操作、领域函数、应用和实例数据尚未定义。

领域语义后续统一写入 [`model.yaml`](model.yaml)。

## 运行

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m foxoms.app.server
```

默认打开 <http://127.0.0.1:8768>。未配置 LLM 时，对象、关系、模型和高级数据维护仍可使用。

## 校验

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python foxoms/scripts/validate_model.py --root foxoms
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s foxoms/tests -v
node --check foxoms/app/static/app.js
```

## Mock 数据

先校验数据，再显式确认替换本地数据库：

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python foxoms/scripts/seed.py
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python foxoms/scripts/seed.py --confirm-clear
```
