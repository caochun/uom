# OMS

OMS 是面向 OAG Agent 的高速联网收费对象关系工作台。它把路网、车辆与 ETC 设备、临时通行介质、通行交易、拆分清分、
客服资金、费率和运行控制放在同一张可追溯业务图中。

系统只有两个固定本体概念：

```text
Object   可独立识别和追溯的业务对象
Relation 两个 Object 之间有方向、可携带事实的业务关系
```

具体业务语义由 [`oms/model.yaml`](oms/model.yaml) 中的 `type`、`properties` 和关系类型表达。当前模型基于
[`docs/高速联网收费领域本体模型 V3.0.md`](docs/高速联网收费领域本体模型%20V3.0.md) 做了面向 LLM 的抽象，
没有把设备、名单和运行参数逐表展开。

## 运行

项目使用 SQLite 保存实例数据，OAG Agent 作为 Git 子模块提供 Agent 运行时。安装依赖后：

```bash
git submodule update --init --recursive
uv sync --project oag-agent
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m app.server
```

打开 <http://127.0.0.1:8765>。LLM 配置写在根目录 `.env` 中；没有 LLM 配置时，图数据、模型和表单仍可使用。

## 用户级 systemd 服务

部署目录为 `~/Develop/highway-oms` 时，可安装仓库中的用户服务：

```bash
install -Dm644 deploy/highway-oms.service ~/.config/systemd/user/highway-oms.service
systemctl --user daemon-reload
systemctl --user enable --now highway-oms.service
systemctl --user status highway-oms.service
journalctl --user -u highway-oms.service -f
```

服务监听 `0.0.0.0:5678`。要在用户未登录时随系统启动，还需确保 `loginctl show-user "$USER" -p Linger`
返回 `Linger=yes`。

## 目录

```text
app/                  OMS Web UI、HTTP API 和 OAG Agent 适配
oms/                  领域本体、业务模型、SQLite 存储和确定性函数
oag-agent/            OAG Agent Git 子模块
oag-domains/          OAG 领域参考子模块
docs/                 领域模型和规则资料
```

详细的对象分组、关系方向、Action 和校验规则见 [`oms/README.md`](oms/README.md)。

## 数据写入

业务表单和 Agent 都使用模型驱动 Action。Action 会先编译成 ChangeSet，经过校验并得到用户确认后，再在
SQLite 事务中同时写入对象、关系和操作审计。模型扩展使用相同的预览/提交机制。

```text
业务意图 -> Action 表单 -> preview -> 用户确认 -> apply -> oms/data/oms.db
```

## 校验

```bash
python3 oms/scripts/validate_model.py --root oms
python3 -m unittest discover -s oms/tests -v
node --check app/static/app.js
```
