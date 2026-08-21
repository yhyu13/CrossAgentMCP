# CrossAgentMCP — 一个 A2A 池 MCP

这是对 [A2A.md](A2A.md) 愿景的最小实现：一个 **A2A 池 MCP**，在其中

1. 任意 agent 都可以**注册**进共享的池子，
2. 任意 agent 都可以**绑定**到一个多 agent 的**会话**，
3. agent 之间**互相观察彼此的活动**，在某位同伴完成后**提出批判**，自我改进，并在
   **无人工干预**的情况下持续工作，直到共享目标被会话中的每一位 agent 认可。

这是一个**面试 demo**：重点不在于 URL 短链/代码评审那篇产出文档，而在于围绕它搭建
的这套系统——一层忠实于 A2A v1.0 的协议层、一个协调控制面、一条「批判到收敛」的闭环，
以及一条从「三个 agent」走向「三个达成一致并停下来的 agent」的可测试、可度量的路径。

---

## 1. 它是做什么的

它把彼此独立的 agent 变成一个能自我协调的团队。包含三种进程：

```
        ┌────────────────── POOL (:9100, FastAPI HTTP JSON-RPC) ──────────────────┐
        │  registry / sessions / activity / critique / goal  （内存态控制面      │
        │  —— 不路由任何工作消息）                                              │
        └──────────────────────────────────────────────────────────────────────────┘
            ▲ pool JSON-RPC (PoolClient)            ▲ pool JSON-RPC（每个 agent 的桥）
            │                                       │
      ┌─────┴──────┐    对等 A2A (SendMessage/GetTask)  ┌─────┴──────┐
      │ orchestrator│◄──────────────────────────────────►│ agent-N    │ … :9101..9103
      └────────────┘      每个 agent 运行各自的          └────────────┘
          无头驱动              v1.0 A2A HTTP 服务器
```

- **Pool**（`crossagent/pool.py`）——控制面：agent **注册表**、带共享目标的多 agent
  **会话**、每个会话的只追加式**活动日志**、**批判线程**，以及每位 agent 的**满意度**。
- **Agents**——每个 agent 是一个目录（`agents/<role>/`），内含一个 v1.0 A2A HTTP
  服务器（对等数据面）、一份接线到 `a2a` stdio MCP 桥（`crossagent/a2a_bridge.py`）的
  `.mcp.json`，以及一份 `CLAUDE.md`（角色 + 每轮契约）。
- **Orchestrator**（`crossagent/orchestrator.py`）——唯一推进时间的组件。它注册
  agent、创建会话，然后按轮询无头运行每个 agent（`claude -p`），把对方尚未见过的
  活动/批判增量喂给它，直到每位成员都声明满意且没有残留的批判线程。

收敛规则是严格的：**每位成员满意，且没有任何未关闭的批判线程**。一次批判会自动撤销
被批判者的满意度，因此只有最后一条反对意见被它所指向的那位 agent 亲手解决，会话才能
结束。

## 2. 它解决什么问题

A2A（Google 的 Agent2Agent 协议）只定义了「两个 agent 之间如何交换任务」——
`SendMessage` / `GetTask` / 流式。它对「两个以上的 agent 如何协调」只字未提。而协调
恰恰是最难、最乱的那部分，也正是本仓库所解决的问题：

| 朴素多 agent 方案的痛点 | CrossAgentMCP 如何解决 |
|---|---|
| 没有注册表：agent 不知道还有谁存在 | 池注册表（`Register` / `ListAgents`） |
| 无法分组：agent 无法围绕一个目标组队 | 带共享 `goal` 和动态成员的可会话 |
| 没有共享记忆：每个 agent 只看到自己的记录 | 只追加式会话 `activityLog` + `activity_since(seq)` 增量 |
| 没有异议通道：一个 agent 无法拦下另一个的劣质产出 | `critique_post` 打开一个线程，**撤销**目标 agent 的满意度 |
| 没有收敛定义：什么才算「完成」 | `declare_satisfaction` + 状态机（`forming→working→revising→satisfied`） |
| 没有终止机制：循环可能无限闲聊、烧 token | 两道护栏：轮次上限 + 无进展检测 → `failed` |
| 没有身份：任何进程都能冒充另一个 agent | 每个 agent 独立 bearer token；伪造动作被 403 拒绝 |
| 不可测试：证明循环有效要烧真金白银的 LLM token | 可注入的 agent runner + 确定性 stub → `pytest` 零成本 |

让它保持清爽的关键设计决策：**控制面集中（池），数据面点对点（A2A）**。池只保存协调
状态；真正的产出和直接消息留在 agent 之间，所以池永远不会成为瓶颈或消息路由器。

## 3. 与其他方案的横向对比

| 方案 | 它是什么 | CrossAgentMCP 的优势 |
|---|---|---|
| **claude-a2a**（本仓库所扩展的参考实现） | 固定的 **2-agent** P2P demo：一个硬编码对等方 + 一个本地 agent | 泛化到 **N 个 agent**，补上注册表、会话、活动流、批判、共识与终止——正是 P2P 根本缺失的三件事 |
| **原生 A2A（Google）** | 仅传输：在两 agent 之间 send/get/stream 任务 | 在忠实 v1.0 线格式之上补上缺失的**协调层**，因此可与任何 A2A agent 组合 |
| **LangGraph / AutoGen / CrewAI** | 多 agent *框架*：agent 跑在框架自身的运行时与图里 | **协议原生、不绑定框架**。任何 agent——经 stdio MCP 桥接入的 Claude Code 会话，或任何会说 A2A over HTTP 的程序——都无需被重写进框架即可加入。agent 是独立 OS 进程；控制面就是一个普通的 HTTP JSON-RPC 服务 |
| **仅 MCP** | agent↔**工具**上下文，单 agent | 把 **MCP（工具）+ A2A（对等消息）+ 池（协调）**组合成一条 agent 循环：观察 → 批判 → 工作 → 汇报 → 声明 |
| **单 agent「全包」** | 一个模型、一个超长上下文、自我 review | 角色分离（writer/critic/lead）并**强制**交叉校验：批判是一等公民，会阻断收敛，而非一句礼貌的建议 |

对一个 demo 而言，决定性优势在于：**不花钱也能证明它成立**。确定性 stub agent 在
`pytest` 下完整回放了整个生命周期（注册 → 会话 → 产出 → 批判 → 满意度撤销 → 认证 403 →
对等 A2A 往返 → 解决 → 全体收敛），而 benchmark 工具则对真实运行报告 token/耗时/成本。

## 4. 这证明了什么（AI vibe coding 能力）

每一条结论都落在代码里。

1. **忠实阅读并实现一份真实的外部规范。** `crossagent/a2a.py` 对齐 A2A v1.0 proto 与
   `specification.md`——camelCase JSON、PascalCase JSON-RPC 方法、`SCREAMING_SNAKE_CASE`
   枚举、规范错误码（`-32001..-32004`）、终态任务状态。没有幻觉出的 API，线格式可对照
   规范逐条核验。
2. **歧义下的架构判断。** 计划中明确选择了*集中控制面 + P2P 数据面*、为可测试性而设的
   *可注入 agent runner*，以及在砍掉一个误触发的无进展检测器后保留*恰好两道*终止护栏——
   推理过程记录在 `1/plan.md` 与 `1/REVIEW.md`。
3. **零 LLM 成本的测试先行验证。** 4 个文件 24 个测试覆盖协议、池、桥与 orchestrator；
   `demo/review_demo_scripted.py` 用确定性 stub 回放完整生命周期；`benchmark.py` 记录每轮/
   每会话的墙钟时间、token（含缓存命中）与美元成本（`benchmark-results.json` 显示一场
   3-agent 共识对话：6 轮、$3.03）。
4. **真实集成调试。** `orchestrator.py` 把 Windows 的 `claude.cmd` shim 解析到原生
   `.exe`，杀掉整棵进程树（`taskkill /T`）以免 MCP 子进程变孤儿，而 `JOURNEY.md` 记录了
   通过把 `ANTHROPIC_MODEL` 重新指向带限定的模型 id 来诊断网关 503/403——这类问题只有
   真刀真枪跑无头 agent 时才会冒出来。
5. **正确性与安全严谨，而非「能跑就行」。** 每个 agent 独立 bearer 身份：
   `test_cannot_spoof_another_agents_satisfaction` 与脚本 demo 都展示了伪造的
   `declare_satisfaction` 被 HTTP 403 拒绝。只有批判所指向的 agent 才能解决它；
   `MarkFailed` 需要 orchestrator token；已失败的会话永远不得报告收敛。
6. **迭代式自审闭环。** `1/` 目录加上 `REVIEW.md`、`JOURNEY.md` 展示了完整弧线：计划 →
   实现 → 代码评审揪出真实缺陷（一个死掉的 `revising` FSM 状态、一处 SSE 回放竞态、
   `critique_resolve` 伪造线程）→ 修复 + 回归测试。系统施加在*自己的 agent* 身上的那条
   批判闭环，同样被施加在了系统*自己的代码*上。

## 协议

忠实于 **A2A v1.0**（PascalCase JSON-RPC 方法、camelCase JSON、`SCREAMING_SNAKE_CASE`
枚举）。见 `crossagent/a2a.py`。

## 安装

```bash
uv sync          # Python 3.11+ venv + 依赖
```

## 为 Kilo / Claude Code / Codex 安装 `a2a` MCP 桥

每个 agent 角色（writer / critic / lead）都暴露同一个 stdio MCP 桥
（`crossagent.a2a_bridge`），只是身份、本地端口和对等映射不同。三个工具都已注册
（路径钉在 `D:/GitRepo-AI/CrossAgentMCP`；若再迁移请同步调整）：

| 工具        | 配置文件                       | 服务器名 |
|-------------|--------------------------------|----------|
| Kilo        | `kilo.json`（`mcp` 字段）      | `a2a-writer`、`a2a-critic`、`a2a-lead` |
| Claude Code | `agents/<role>/.mcp.json`      | `a2a`（从该 agent 目录运行 Claude 时加载） |
| Codex       | `.codex/config.toml`           | `a2a-writer`、`a2a-critic`、`a2a-lead` |

桥的工具只有在池和 agent A2A 服务器都起来后才能工作。启停脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-servers.ps1
powershell -ExecutionPolicy Bypass -File scripts/stop-servers.ps1
```

（`start-servers.ps1 -WithDemoAuth` 会镜像 `demo/goal.json` 里的 token；默认运行时池
关闭认证。）

## 使用

### 快速上手（root vs `1/`）

本仓库有两套独立实现，都跑在同一组端口 `:9100–9103`，不要同时启动：

**root —— `crossagent/`（推荐，已接入 Kilo）**

```powershell
uv sync
powershell -ExecutionPolicy Bypass -File scripts/start-servers.ps1   # pool :9100 + writer/critic/lead :9101..9103
powershell -ExecutionPolicy Bypass -File scripts/stop-servers.ps1    # 停止
```

服务器起来后，Kilo 的 `a2a-writer` / `a2a-critic` / `a2a-lead` MCP 工具即可用；各角色
每轮契约见 `agents/<role>/CLAUDE.md`。

**子目录 `1/` —— `agentpool`（早期实现，无 bearer 身份、无头编排器非一等公民）**

```powershell
cd 1
uv sync
uv run pytest                                        # pool / session / consensus 测试
uv run python demo/run_session.py --num-agents 3     # 全自主闭环，无 LLM
uv run python demo/real_review.py --payload demo/real_review_payload.json
uv run python demo/compare_radiance.py               # 自动选端口，可与 root 并存
uv run python -m pool.server                         # 单跑 pool（:9100）
```

两套实现的差异（工具名 / 认证 / 收敛契约 / 编排器）见下方「与子目录 `1/` 的关系」。

```bash
make test        # 单元测试（协议 / 池 / orchestrator，使用假 agent）
make smoke       # 拉起池 + 2 个 A2A 服务器；脚本化往返（无真实 Claude）
make demo        # 完整无头 3-agent demo（writer / critic / lead）——需要 `claude`
```

编排器支持 `schedule: "serial"`（默认）与 `"parallel"`：并行模式每轮让所有 agent 在
同一 pre-round 快照上并发工作（bulk-synchronous），一轮计 `len(agents)` 次 run，与串行
模式的轮次预算可比。在 `goal.json` 加 `"schedule": "parallel"` 即可切换。

### Demo 目标

`demo/goal.json` 让三个 agent——**writer**、**critic**、**lead**——共同撰写
`demo/output/design.md`（一个 URL 短链设计），直到三者都声明满意。

### 代码评审 demo（torchimpulse）

另有两条驱动针对一个真实代码库（`F:\XD\git-repo\torchimpulse`）跑同一套池：

```bash
uv run python demo/review_demo_scripted.py   # 确定性 stub agent（无 claude，零成本）
uv run python demo/review_demo.py            # 完整自主 3-agent 评审——需要 `claude`
```

- `review_demo_scripted.py` 回放完整生命周期——注册 → 会话 → 产出 → 批判（满意度撤销）→
  伪造动作被认证 403 → 对等 A2A 发送/应答 → 解决 → 全体收敛——以真实评审结论作为内容。
- `review_demo.py` 无头运行 **writer / critic / lead**（`claude -p`）共同撰写
  `torchimpulse/A2A_REVIEW.md` 并收敛（5 轮，全员满意，0 条未关闭批判）。

### 文档树评审 + 单 agent 对照（radiance `3d/doc`）

同一棵 ~589 文件的文档树、同一模型（`deepseek/deepseek-v4-pro`），`demo/compare_radiance.py`
对照 **单 agent 融合一轮** 与 **3-agent 编排器**：

| 模式 | 轮次 | 墙钟 | 成本 | 收敛 |
|---|---|---|---|---|
| mono-agent | 1 | 556 s | $2.29 | 是（`MONO_REVIEW.md`） |
| 3-agent（本仓库 `crossagent/`） | 5 | 855 s | $4.56 | 是（三方 `true`） |

相对 mono：墙钟 ×1.54、input token ×3.03、成本 ×2.00。产出篇幅相当（18.5 KB vs 19.2 KB）。
原始数字在 `demo/output/radiance_comparison.json`。

```bash
uv run python demo/compare_radiance.py          # 需已运行 scripts/start-servers.ps1
uv run python demo/review_radiance.py           # 附着已运行栈评审；结束后导出完整活动/批判记录
```

### 单 agent vs 3-agent 效率 / 质量对照（payments ledger，盲评）

同一个问题、同一模型、同一运行栈，`demo/compare_efficiency.py` 对照**单 agent 融合一轮**
与 **3-agent 编排器**的效率比值；`demo/compare_quality.py` 再跑三种模式（single-monolithic /
single-iterative(N) / 3-agent），并由**独立盲评**按 5 项标准打分（满分 25）：

| 模式 | 轮次 | 墙钟 | 成本 | 盲评 /25 |
|---|---|---|---|---|
| single-monolithic | 1 | 38 s | $0.24 | 25 |
| single-iterative(6) | 6 | 650 s | $2.01 | 25 |
| 3-agent | 6 | 264 s | $2.13 | 10* |

`*` 10/25 是度量产物：目标写了「不要写文件」，池的推理只留在活动日志里，盲评只看到
lead 的状态行——池保存的是协调状态，不是工作产出。原始数字在
`demo/output/{efficiency,quality}_comparison.json`。

```bash
uv run python demo/compare_efficiency.py        # 需已运行 scripts/start-servers.ps1
uv run python demo/compare_quality.py           # 同上（含盲评）
```

### 与子目录 `1/` 的关系

`1/` 是**另一套**实现（从 `claude-a2a` 长出来的池：slash 方法名、SSE watch、无
bearer 身份、无头编排器不是一等公民）。同一棵 radiance 树的第一次真 `claude -p`
循环（`1/demo/compare_radiance.py`，自动选端口以免撞 :9100）跑满 9 轮仍停在
`reviewing`（lead 未声明满意），成本 $7.57。差距主要来自**循环契约**——根编排器每轮
强制 `declare_satisfaction`，`1/` 的 `satisfy()` 只能单向 `True`——不是评审质量
更差（`A2A_REVIEW_1.md` 同样有 `file:line` 的 Critical 发现）。详见
[JOURNEY.md](JOURNEY.md) 2026-08-21 节与 [1/README.md](1/README.md)。

## 注意事项

- 各 `.mcp.json` / `kilo.json` / `.codex/config.toml` 文件硬编码了仓库路径
  `D:/GitRepo-AI/CrossAgentMCP`；若迁移仓库请同步更新。
- 池与 agent 服务器都把状态保存在**内存**里；重启即重置。
- 无头 agent 运行的是 `claude -p`，此处它指向一个网关（`llm-proxy.tapsvc.com`）。请在
  `~/.claude/settings.json` 中钉住模型（例如 `ANTHROPIC_MODEL=deepseek/deepseek-v4-pro`）；
  Claude Code 的裸默认模型名会被该网关拒绝。
