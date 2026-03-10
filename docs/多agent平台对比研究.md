# 多 Agent 平台对比研究

> 研究日期：2026-03-06
> 对比对象：Agent-Hub（本项目） vs Coze vs Taskade vs CrewAI vs Claude Code Agent Teams

---

## 1. 平台定位总览

| 维度 | **Agent-Hub（本项目）** | **CrewAI** | **Coze** | **Taskade** | **Claude Code Agent Teams** |
|---|---|---|---|---|---|
| **一句话定位** | 自治软件开发团队工作流 | 开源多 Agent 编排框架 | 低代码 AI Agent 构建平台 | AI 增强的项目管理/协作工具 | Claude Code 内置并行协作 |
| **目标用户** | 开发团队/个人开发者 | Python 开发者/AI 工程师 | 非技术/低技术用户 | 团队协作/项目管理人员 | Claude Code 用户 |
| **核心场景** | 自动化 SDLC 全流程 | 构建定制化多 Agent 应用 | 构建聊天机器人和工作流 | 任务管理 + AI 自动化 | 单次任务并行加速 |
| **技术门槛** | 高（tmux/MCP/Leantime） | 中（Python 编程） | 低（可视化拖拽） | 极低（SaaS 产品） | 低（自然语言指令） |
| **开源/商业** | 自用项目 | 开源（Apache 2.0） | 开源（Coze Studio） + 商业 | 商业 SaaS | Anthropic 内置功能 |

---

## 2. 架构对比

### Agent-Hub（本项目）
```
人类 → Leantime（任务管理） → auto_dispatch（轮询调度）
                                    ↓
                    ┌───────┬───────┬───────┐
                    │Admin  │Product│  Dev  │  QA  │
                    │(tmux) │(tmux) │(tmux) │(tmux)│
                    └───────┴───────┴───────┘
                    各自独立的 Claude Code 实例
                    通过 Leantime 工单异步协调
```
- **编排模式**：外部编排（auto_dispatch.sh 轮询 + Leantime 状态机）
- **Agent 生命周期**：持久化守护进程，`--resume` 跨会话
- **通信**：异步，通过工单（间接）
- **状态管理**：Leantime（外部持久化）

### CrewAI
```
开发者代码 → Crew（团队定义）→ Process（执行策略）
                                    ↓
                    ┌──────────┬──────────┐
                    │Agent A   │Agent B   │Agent C│
                    │role/goal │role/goal │role/goal│
                    │backstory │backstory │backstory│
                    └──────────┴──────────┘
                    共享 Process 上下文
                    通过 delegation 协调
```
- **编排模式**：代码定义（Python API / YAML 配置）
- **执行策略**：Sequential（串行）/ Hierarchical（层级）/ Parallel（并行）
- **通信**：结构化消息传递（message-passing protocols）
- **状态管理**：内存中（Flows 支持事件驱动持久化）

### Coze
```
用户 → 可视化 Workflow Builder → 多 Agent 节点图
                                    ↓
                    ┌──────────┬──────────┐
                    │邮件Bot   │日历Bot   │表格Bot│
                    │(prompt+  │(prompt+  │(prompt+│
                    │ plugins) │ plugins) │ plugins)│
                    └──────────┴──────────┘
                    通过 Jump Conditions 路由
                    关键词触发 Agent 切换
```
- **编排模式**：可视化节点图（拖拽）
- **Agent 切换**：Jump Conditions（关键词触发路由）
- **通信**：用户消息驱动的路由（不是 Agent 间直接通信）
- **状态管理**：平台托管

### Taskade
```
用户 → Workspace → Projects + Automations + AI Agents
                                    ↓
                    ┌──────────────────────┐
                    │AI Agent（训练后部署） │
                    │  ↕ 100+ 外部集成     │
                    │  ↕ If-Then 自动化    │
                    │  ↕ 持久记忆          │
                    └──────────────────────┘
                    单 Agent 为主，自动化为辅
```
- **编排模式**：If-Then 自动化规则
- **Agent 模式**：单 Agent + 自动化触发器（非真正多 Agent 协作）
- **通信**：通过自动化规则和 webhook
- **状态管理**：平台托管 + 持久记忆

### Claude Code Agent Teams
```
用户 → Team Lead（主会话）→ 共享任务列表
                                    ↓
                    ┌──────────┬──────────┐
                    │Teammate1 │Teammate2 │Teammate3│
                    │(独立CC)  │(独立CC)  │(独立CC) │
                    └──────────┴──────────┘
                    直接消息 + 广播
                    自主认领任务
```
- **编排模式**：自然语言驱动 + 共享任务列表
- **通信**：直接消息 + 广播（实时）
- **状态管理**：内存中（会话结束即消失）

---

## 3. 核心能力对比矩阵

| 能力 | Agent-Hub | CrewAI | Coze | Taskade | Agent Teams |
|---|:---:|:---:|:---:|:---:|:---:|
| **角色专业化** | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ | ★★☆☆☆ |
| **任务依赖管理** | ★★★★★ | ★★★★☆ | ★★☆☆☆ | ★★★☆☆ | ★★★☆☆ |
| **Agent 间通信** | ★★☆☆☆ | ★★★★☆ | ★★☆☆☆ | ★☆☆☆☆ | ★★★★★ |
| **持久化/跨会话** | ★★★★★ | ★★★☆☆ | ★★★★☆ | ★★★★★ | ★☆☆☆☆ |
| **质量关卡** | ★★★★★ | ★★☆☆☆ | ★☆☆☆☆ | ★☆☆☆☆ | ★☆☆☆☆ |
| **并行执行** | ★★☆☆☆ | ★★★★☆ | ★☆☆☆☆ | ★☆☆☆☆ | ★★★★★ |
| **上手难度（易→难）** | ★★★★★ | ★★★☆☆ | ★★☆☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| **外部集成** | ★★★☆☆ | ★★★★☆ | ★★★★★ | ★★★★★ | ★★☆☆☆ |
| **可视化界面** | ☆☆☆☆☆ | ★★★☆☆ | ★★★★★ | ★★★★★ | ★★☆☆☆ |
| **代码执行能力** | ★★★★★ | ★★★★☆ | ★★☆☆☆ | ★☆☆☆☆ | ★★★★★ |
| **SDLC 全流程** | ★★★★★ | ★★☆☆☆ | ☆☆☆☆☆ | ☆☆☆☆☆ | ★☆☆☆☆ |
| **可审计/可追溯** | ★★★★★ | ★★☆☆☆ | ★★★☆☆ | ★★★☆☆ | ★☆☆☆☆ |

---

## 4. 本质区别分析

### 4.1 Agent-Hub vs CrewAI：最接近的竞品

**相似点：**
- 都是角色驱动的多 Agent 系统
- 都有任务分配和依赖管理
- 都支持自定义 agent prompt/角色/工具

**关键区别：**

| | Agent-Hub | CrewAI |
|---|---|---|
| **Agent 实体** | 真实的 Claude Code 进程（有文件系统访问、终端、git） | Python 对象（LLM API 调用的封装） |
| **执行能力** | Agent 可以真的写代码、跑测试、操作系统 | Agent 主要做推理和调用工具 API |
| **持久性** | 守护进程，跨天运行 | 单次执行，run 完就结束 |
| **适用场景** | 软件开发全流程自动化 | 通用业务流程自动化（研究、内容、数据） |
| **编排方式** | 外部状态机（Leantime） | 代码/YAML 声明式 |

**结论：** CrewAI 是 Agent 编排的**通用框架**，Agent-Hub 是**专用于软件开发的实例**。如果用 CrewAI 的术语来描述 Agent-Hub：它是一个 Crew，有 4 个 Agent（Admin/Product/Dev/QA），用 Hierarchical Process，外挂了 Leantime 做持久化任务管理。

### 4.2 Agent-Hub vs Coze：完全不同的物种

| | Agent-Hub | Coze |
|---|---|---|
| **Agent 交互对象** | Agent 之间交互（无人值守） | Agent 与人类用户交互（聊天机器人） |
| **多 Agent 模式** | 并行自治 worker | 路由分发（用户消息 → 匹配 Agent） |
| **核心价值** | 自动化开发流程 | 构建面向终端用户的 AI 应用 |

**结论：** Coze 的"多 Agent"本质是**路由器模式**——根据用户输入的关键词把请求分发给不同的专业 Bot。它不是真正的 Agent 间协作，而是一个智能客服分发系统。和 Agent-Hub 几乎没有可比性。

### 4.3 Agent-Hub vs Taskade：不同维度

| | Agent-Hub | Taskade |
|---|---|---|
| **核心** | AI Agent 驱动的自动化工作流 | 人类驱动的项目管理 + AI 辅助 |
| **Agent 角色** | Agent 是主角，自主完成工作 | Agent 是助手，辅助人类完成工作 |
| **多 Agent** | 4 个专业 Agent 持续协作 | 本质是单 Agent + 自动化触发 |
| **可比维度** | 任务管理系统（Leantime ≈ Taskade 的项目管理） | AI 辅助功能 |

**结论：** Taskade 是一个**带 AI 增强的项目管理工具**，它的 AI Agent 更像是一个智能助手，而不是自治的 worker。Agent-Hub 的 Leantime 和 Taskade 的项目管理部分有相似性，但 Agent-Hub 的 Agent 是真正的自治执行者。

### 4.4 Agent-Hub vs Agent Teams：互补关系（详见 [借鉴-agent-teams.md](借鉴-agent-teams.md)）

Agent Teams 是**任务内并行引擎**，Agent-Hub 是**任务间工作流编排**。两者天然互补。

---

## 5. 分类总结

按照本质差异，这 5 个系统可以分为 3 类：

### 第一类：多 Agent 协作系统（真正的 Agent 间协作）

| 系统 | 协作模式 |
|---|---|
| **Agent-Hub** | 角色分工 + 异步工单协调 + 质量关卡 |
| **CrewAI** | 角色分工 + 编程式编排 + delegation |
| **Agent Teams** | 动态团队 + 直接消息 + 共享任务列表 |

### 第二类：智能路由/分发系统（不是真正的多 Agent 协作）

| 系统 | 模式 |
|---|---|
| **Coze** | 用户消息 → 关键词匹配 → 路由到专业 Bot |

### 第三类：AI 增强的传统工具

| 系统 | 模式 |
|---|---|
| **Taskade** | 项目管理工具 + AI 助手 + 自动化规则 |

---

## 6. Agent-Hub 可以从各平台借鉴的内容

### 从 CrewAI 借鉴

| 概念 | 说明 | 价值 |
|---|---|---|
| **YAML 声明式 Agent 定义** | CrewAI 支持 YAML 定义 role/goal/backstory/tools | Agent-Hub 的 `agents.yaml` 已部分实现，可进一步标准化 |
| **Hierarchical Process** | Manager Agent 自动分配任务给 Worker | 类似 Product Agent 的角色，但 CrewAI 的更自动化 |
| **Delegation 机制** | Agent 可以主动把子任务委托给其他 Agent | Agent-Hub 目前只能通过创建工单间接委托 |
| **Flows 事件驱动** | CrewAI Flows 支持事件触发、条件分支、状态管理 | 比 auto_dispatch.sh 的轮询更优雅 |
| **Structured Output** | 通过 Pydantic 模型强制 Agent 输出结构化数据 | 可用于标准化 QA 报告格式、Dev 交付物 |
| **Context Window 管理** | 自动检测并 summarize 超长上下文 | Agent-Hub 的长期运行 Agent 需要这个能力 |

### 从 Coze 借鉴

| 概念 | 说明 | 价值 |
|---|---|---|
| **可视化工作流编辑器** | 拖拽节点构建 Agent 协作流程 | 未来如果 Agent-Hub 要给其他人用，需要降低门槛 |
| **Plugin 生态** | 丰富的第三方插件（邮件、日历、表格等） | MCP server 生态可以借鉴这个思路 |
| **多渠道部署** | 同一个 Bot 可以部署到 Discord/WhatsApp/飞书 | 如果要把 Agent 暴露给团队成员交互 |

### 从 Taskade 借鉴

| 概念 | 说明 | 价值 |
|---|---|---|
| **持久记忆系统** | Agent 记住过去的交互、从结果中学习 | Agent-Hub 的 Agent 靠 `--resume` 保持上下文，但没有结构化的长期记忆 |
| **100+ 外部集成** | 连接 Slack/Gmail/Drive 等外部服务 | 可以让 Agent 在完成任务后自动通知（Slack）、归档（Drive） |
| **自动化触发器** | If-Then 规则自动执行动作 | 比 auto_dispatch.sh 更灵活的触发条件 |

### 从 Agent Teams 借鉴

详见 [借鉴-agent-teams.md](借鉴-agent-teams.md)

---

## 7. 综合结论

| 问题 | 回答 |
|---|---|
| Agent-Hub 最像谁？ | **CrewAI** — 都是角色驱动的多 Agent 协作系统，但 Agent-Hub 专注软件开发且 Agent 有真实系统能力 |
| 和 Coze 有关系吗？ | **几乎没有** — Coze 是面向终端用户的聊天机器人构建平台，"多 Agent"只是路由分发 |
| 和 Taskade 有关系吗？ | **部分重叠** — 任务管理层面有相似性（Leantime ≈ Taskade），但 Agent 自治程度完全不同 |
| Agent-Hub 的独特优势是什么？ | **Agent 有真实系统能力**（写代码、跑测试、操作 VM）+ **结构化质量关卡** + **持久化跨天工作流** |
| 最大的短板是什么？ | **Agent 间通信慢**（靠轮询工单）+ **无并行能力**（单任务串行）+ **配置复杂** |
| 最值得借鉴的？ | CrewAI 的 Flows 事件驱动 + Agent Teams 的直接消息 + Taskade 的持久记忆 |

---

## 参考来源

- [CrewAI 官方文档 - Agents](https://docs.crewai.com/en/concepts/agents)
- [CrewAI Framework 2025 完整评测](https://latenode.com/blog/ai-frameworks-technical-infrastructure/crewai-framework/crewai-framework-2025-complete-review-of-the-open-source-multi-agent-ai-platform)
- [Coze 多 Agent 模式使用指南](https://www.yeschat.ai/blog-Coze-How-to-use-Multiagent-mode-29442)
- [Coze Studio 开源](https://github.com/coze-dev/coze-studio)
- [Taskade AI Agents](https://www.taskade.com/ai/agents)
- [Taskade AI 评测 2025](https://www.humai.blog/taskade-ai-workspace-memory-agents-automation-review-2025/)
- [Claude Code Agent Teams 官方文档](https://code.claude.com/docs/en/agent-teams)
- [2026 AI Agent 框架对比](https://blog.softmaxdata.com/definitive-guide-to-agentic-frameworks-in-2026-langgraph-crewai-ag2-openai-and-more/)
