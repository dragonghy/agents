# 从 Claude Code Agent Teams 可借鉴的概念

> 研究日期：2026-03-06
> 对比对象：Claude Code Agent Teams（实验性功能） vs 本项目（Agent-Hub）
> 结论：两者互补，不互相包含。Agent Teams 适合任务内并行，Agent-Hub 适合跨任务工作流编排。

---

## 高价值

### 1. 直接 Agent 间消息通信

**现有差距：** Agent 只通过 Leantime 工单通信，延迟高（依赖 `auto_dispatch.sh` 的 30 秒轮询）。

**借鉴内容：** Agent Teams 有 mailbox 系统，agent 之间可以实时发消息和广播。

**实现思路：**
- 基于文件或 tmux `send-keys` 实现轻量消息队列，用于紧急通知
- 保留 Leantime 作为事实来源，消息队列只做"推送通知"
- 场景：Dev 完成任务后直接通知 QA，不等轮询

### 2. 任务内并行（Agent Teams 作为执行引擎）

**现有差距：** Dev 拿到大任务时，在单个 Claude 实例中串行工作。

**借鉴内容：** Agent Teams 可以为单个任务生成多个 teammate 并行工作（前端/后端/测试各一个）。

**实现思路：**
- Agent-Hub 负责任务间编排（Dev→QA→Product）
- Dev 在处理大任务时，内部生成 Agent Team 做任务内并行
- 并行完成后综合结果，再按正常流程创建 QA 工单
- 这是最自然的组合方式：两个系统各管各的抽象层

---

## 中等价值

### 3. 竞争假设调试

**现有差距：** QA 报告 bug 时，单个 Dev agent 串行排查，容易锚定在第一个假设上。

**借鉴内容：** Agent Teams 的"竞争假设"模式——多个 teammate 分别调查不同假设，互相质疑，最终收敛到真正的根因。

**实现思路：**
- 当 Dev 收到复杂 bug 时，生成 3-5 个 teammate 各自调查一个假设
- Teammate 之间互相 challenge，存活下来的假设更可能是真正原因
- 比串行排查更快、更不容易遗漏

### 4. 计划审批关卡

**现有差距：** Dev 接到任务后立即开始实现，没有技术方案审批环节。

**借鉴内容：** Agent Teams 的 plan approval 机制——teammate 在 read-only plan mode 下工作，lead 审批后才能开始实现。

**实现思路：**
- Dev 接到任务后先进入计划模式，输出技术设计方案
- 方案通过 Leantime 提交给 Product 审批
- Product 批准后 Dev 才开始写代码
- 减少因理解偏差导致的无效实现

---

## 低-中等价值

### 5. Hooks 质量强制

**现有差距：** 质量执行依赖 agent prompt 和 `/review-qa` skill 的 prompt-level 合规。

**借鉴内容：** Agent Teams 的 `TaskCompleted` hook——任务标记完成时运行程序化检查。

**实现思路：**
- 在 `auto_dispatch.sh` 中加入任务完成检查逻辑
- 例如：QA 任务标记完成时，自动检查评论中是否包含 E2E 执行证据
- 不满足则自动驳回，不依赖 prompt 合规
- 从"靠 prompt 约束"升级到"靠系统约束"

### 6. 动态团队扩缩

**现有差距：** 固定 4 个 agent（Admin、Product、Dev、QA），不随工作量变化。

**借鉴内容：** Agent Teams 可按需生成任意数量的 teammate。

**实现思路：**
- 当多个同类任务同时解锁时，动态生成额外的同角色 agent
- 例如：3 个 Dev 任务同时解锁 → 生成 Dev-2、Dev-3
- 需要解决：tmux 窗口管理、会话 ID 追踪、Leantime 标签区分
- 目前优先级低，当前工作量不需要

---

## 推荐优先级

| 优先级 | 项目 | 理由 |
|--------|------|------|
| P0 | 直接消息通信 | 实现简单（tmux send-keys），立即减少延迟 |
| P1 | 任务内并行 | 需要先启用 Agent Teams 实验功能，但收益大 |
| P2 | 计划审批关卡 | 减少无效实现，可先在 prompt 层面实现 |
| P2 | 竞争假设调试 | 特定场景高价值，非通用需求 |
| P3 | Hooks 质量强制 | 当前 prompt 方案基本够用 |
| P3 | 动态团队扩缩 | 当前工作量不需要 |
