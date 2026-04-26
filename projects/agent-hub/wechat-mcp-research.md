# WeChat MCP — 安全接入研究

> **Author**: dev-alex
> **Date**: 2026-04-26
> **Ticket**: #496 (Phase A)
> **Parent**: #493 — Personal MCP Umbrella
> **Status**: Phase A complete, **Phase B blocked on Human risk evaluation**

---

## 1. 目标 & 约束

### 目标
让未来的 Personal Assistant agent 能够：
- 读取最近 10 个会话列表
- 读取某个会话最近 N 条消息
- 给指定联系人发送一条消息

只对 personal agent 暴露（`mcp__wechat_personal__*`），工作 agent 调不到（per ticket #497 隔离层）。

### 硬约束（来自 Human + ticket）
1. **不能让 Human 主账号被封。** 这是首要红线，比"功能能不能跑"重要得多。
2. **优先本地客户端方案** — Human 已点名希望"在本地起一个 EP / APP 由 agent 操作"。
3. **任何方案要求 Human 用真账号重新扫码登录 = 必须先 escalate**。Phase B 不能默认 fire。
4. 范围内：私聊 + 群聊文字读 / 写。**范围外**：朋友圈、视频号、公众号、支付。

### 风险参考点（影响所有评估）
2025 年初社区报告（[wechaty issue #2773](https://github.com/wechaty/wechaty/issues/2773)）：
- 免费 wechaty 协议扫码"一扫必被警告 / 封号"
- 文本 + 图片相对安全；语音 / H5 / 电商 ≈ 100% 封号率
- Tencent 的反爬模型已经把 wechaty-style 流量当成已知 fingerprint

新账号或被识别为机器人的账号通常 24h–7d 内冻结。**Human 主账号是十年老号**，冻结不可接受。

---

## 2. 方案矩阵（一览）

| # | 方案 | 封号风险 | 实现难度 | 需 Human 介入 | 限制 | 推荐度 |
|---|------|---------|----------|---------------|------|--------|
| 1 | wechaty Web/Pad 协议（免费） | **高 (~100% within 7d)** | 低（社区代码现成）| 主账号扫码 | 文本/图片可用，语音/H5禁用 | ❌ |
| 2 | AppleScript / Accessibility UI 控制 | **极低**（行为 = 真人）| 中（GUI 脆弱）| 一次：开 Accessibility 权限 | 慢（每条 1–3s）；UI 改版会断 | ✅ 发送首选 |
| 3 | 本地客户端 SQLite DB 读取 | **极低**（read-only 不发包）| 中（要解密 + 提密钥）| 一次：codesign 重签 OR SIP off | 只读；DB schema 改版会断 | ✅ 读取首选 |
| 4 | PadLocal / iPad 协议（付费）| 中（"较低"≠"零"）| 低（成熟 SDK）| 主账号扫码 | 月付 ≈ ¥99–299；仍是云端中继 | ❌（仍要扫码）|
| 5 | Frida / LLDB hook 进程 | 中（异常网络行为可被检测）| 高（逆向 + 月度跟新）| 一次：SIP off | 完全控制；维护成本高 | ⚠️ 备选 |
| 6 | **组合**：方案 3 读 + 方案 2 发 | **极低**（两端都不碰协议）| 中 + 中 | 一次：codesign + Accessibility | 都得维护 | 🎯 **推荐** |

---

## 3. 各方案详解

### 方案 1: wechaty 免费协议
- **协议**: WebProtocol（已基本失效）/ Mac protocol（仍能跑但被 fingerprint）
- **GitHub**: [wechaty/wechaty](https://github.com/wechaty/wechaty)
- **2025 现状证据**:
  - Issue [#2773](https://github.com/wechaty/wechaty/issues/2773) — "20250110 不要再扫免费版的 wechaty，一扫必被微信安全封号警告"
  - Issue [#2518](https://github.com/wechaty/wechaty/issues/2518) — "可能被腾讯官方封号，用于生产项目要谨慎"
  - 社区共识：**主账号绝不可用**，副号 7 天内 99% 失效。
- **结论**: ❌ 不考虑，违背"不封 Human 主账号"红线。

### 方案 2: AppleScript / Accessibility UI 控制
- **原理**: 把 WeChat for Mac 当普通 macOS app，用 `System Events` / Accessibility API 找到聊天列表 → 输入框 → 按 Enter。流量上跟真人完全一样，腾讯几乎不可能区分。
- **现成参考**:
  - [biboyqg/wechat-mcp](https://github.com/biboyqg/wechat-mcp) — 已经是个 MCP server，用 Accessibility API + 截屏
  - [geminiwen/mcp-wechat-moments](https://github.com/geminiwen/mcp-wechat-moments) — AppleScript GUI 自动化（朋友圈，但模式可借鉴）
  - [MacScripter 讨论帖](https://www.macscripter.net/t/gui-scripting-of-wechat/72591) — 工作样例：搜联系人 → 选会话 → typetext → Enter，已确认可跑
- **配置成本（一次性）**:
  - 终端 / Claude Code 进程 加入 `System Settings → Privacy & Security → Accessibility`
  - 不需 SIP off，不需 codesign
- **限制**:
  - **慢**：每发一条 1–3 秒（要等 UI 响应）
  - **脆弱**：Tencent 改 UI 层级会让 AppleScript 失效（按月度更新历史，约每 1–2 月断一次）
  - 原生 `click` 不灵，需要 `keystroke return` 或外加 cliclick / mouse simulation
  - 必须 WeChat 在前台 OR 至少没被系统挂起（取决于实现）
- **封号风险**: **极低**。流量、心跳、设备指纹都跟普通 Mac 用户完全一样。仅有的风险是发送频率异常（1 秒发 100 条 = 暴露）→ 必须客户端 rate-limit。
- **结论**: ✅ 发送侧首选。

### 方案 3: 本地客户端 SQLite DB 读取
- **DB 路径**:
  ```
  ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid>/db_storage/message/message_*.db
  ```
- **加密**: SQLCipher 4，由 Tencent 自家 [WCDB](https://github.com/Tencent/wcdb) 封装。密钥存于 WeChat 进程内存 `DBEncryptInfo` 单例的 `m_dbEncryptKey`（NSData）字段。
- **现成解密工具**:
  - [Thearas/wechat-db-decrypt-macos](https://github.com/Thearas/wechat-db-decrypt-macos) — ARM64 + WeChat 4.1.2.241，**要求 `csrutil disable`（关 SIP）** ❌
  - [cocohahaha/wechat-decrypt-macos](https://github.com/cocohahaha/wechat-decrypt-macos) — 从进程内存提密钥，**不要求 SIP off，但要 `sudo codesign --force --deep --sign - /Applications/WeChat.app` 重签 WeChat** ✅ 推荐路径
  - [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) — WeChat 4.0+ SQLCipher 4 解密，附实时消息监控
- **流程**:
  1. WeChat 在登录状态运行
  2. `sudo codesign --force --deep --sign - /Applications/WeChat.app` → 一次性
  3. 用 lldb attach WeChat 进程，定位 `DBEncryptInfo` → dump 64-hex key
  4. 把 `message_*.db` 复制到工作目录（避免锁竞争）
  5. SQLCipher with key → 普通 SQLite query
- **能读什么**:
  - 完整聊天记录（文字、图片元数据、撤回标记、群聊、时间戳）
  - 联系人列表（另一个 db: `contact_*.db`）
  - 会话列表（`session_*.db`）
- **限制**:
  - **只读** — 物理上不发消息，必须配合方案 2
  - DB schema 在 WeChat 主版本升级时会变（4.0 → 4.1 已经变过一次）
  - 密钥提取在每次重启 WeChat 后需要重跑 lldb（密钥本身不变，但内存地址变）
- **封号风险**: **极低（≈零）**。整个过程不碰网络、不发包、不调用 WeChat API，纯本地文件读 + 内存读。Tencent 没有任何信号检测到。
- **结论**: ✅ 读取侧首选。

### 方案 4: PadLocal（付费 iPad 协议）
- **原理**: 第三方提供 Pad 协议网关（[pad-local.com](https://pad-local.com)），你的请求经他们的服务器转给 Tencent。
- **GitHub**: [wechaty/puppet-padlocal](https://github.com/wechaty/puppet-padlocal)
- **价格**: 免费 7 天 trial；长期 token 付费购买（社区零散数据约 ¥99–299/月，未在公开页面查到 2026 报价）
- **风险等级**: 中。比 Web 协议低（流量看起来像 iPad 客户端），但仍是云端中继，**Tencent 封过 PadLocal 提供商批量 IP 段**，账号会被一锅端。
- **需要 Human**: 主账号扫码登录到 PadLocal 网关 → **触发 ticket 红线**（"任何方案要求 Human 真账号扫码必须先 escalate"）。
- **额外问题**: 钱花在第三方上，且账号是否安全完全取决于供应商如何隐藏机器人特征。
- **结论**: ❌ 不推荐。即便愿意付费，"扫码 + 第三方中继"组合等于把 Human 主账号交给陌生方，比方案 6 风险高数量级。

### 方案 5: Frida / LLDB hook macOS WeChat 进程
- **原理**: 直接 hook WeChat 内部函数（如 `MMServiceCenter sendMessage:`），可读可写，性能 = 客户端原生。
- **代表项目**:
  - [WeChatFerry](https://github.com/lich0821/WeChatFerry) — **仅 Windows**（VS2019、vcpkg），最新 v39.5.2 / 2026-03 跟到 WeChat 3.9.x。**不适用 macOS**。
  - macOS hook 没有同等成熟项目；wechaty 官方 [2025-08 博客](https://wechaty.js.org/2025/08/12/ai-powered-reverse-engineering-concept/) 提到用 LLM + Frida 辅助逆向，仍属研究阶段。
- **配置成本**:
  - SIP off（重启进 Recovery，`csrutil disable`）→ 影响系统其他安全性
  - Frida 注入；需要月度跟随 WeChat 更新重新定位符号
- **封号风险**: 中。hook 本身不发异常包，但 Tencent 偶尔下推完整性检测（检查 mach-o load commands 是否被改）。
- **维护成本**: 高。Tencent 月度更新意味着每月可能要重新逆向。
- **结论**: ⚠️ 仅作 Plan B 备选；当前方案 6 失效（如方案 2 或 3 被 Tencent 完全堵死）时再考虑。

### 方案 6: 组合（DB 读 + AppleScript 发）— **推荐**
- **架构**:
  ```
  Personal Agent
       │
       ├── mcp__wechat_personal__list_sessions      → SQLite (decrypted, read-only)
       ├── mcp__wechat_personal__read_messages       → SQLite
       └── mcp__wechat_personal__send_message        → AppleScript (osascript)
                                                       └─ rate-limit 1/3s
  ```
- **封号风险叠加分析**:
  - 读：零网络流量 → 零风险
  - 发：行为 = 真人，但限频 ≤ 1/3s + 工作时段 + 仅白名单联系人 → 极低风险
  - 总评：**比 Human 自己用手机偶尔多手抖发条消息的风险还低**。
- **Human 一次性配置（≤ 30 分钟）**:
  1. `sudo codesign --force --deep --sign - /Applications/WeChat.app`
  2. System Settings → Privacy & Security → Accessibility → 加入终端进程
  3. 在 WeChat 上正常登录主账号（已是状态）
  4. 跑一次 `extract_key.sh` 从内存拿出 SQLCipher 密钥 → 存到 1Password Personal vault
- **维护负担**:
  - WeChat 升级 4.x → 5.x 时 DB schema 可能变（重写 query 层）
  - WeChat UI 升级时 AppleScript 选择器可能要调（`xpath`-style 失效）
  - 估计每 2–3 个月需要一次 patch
- **不能做什么**:
  - 收红包、转账（涉及支付，UI 路径里要密码）
  - 朋友圈（不在范围）
  - 视频号（不在范围）
  - 文件接收/发送（可做但 UI 自动化复杂，建议 v2）
  - 撤回消息（AppleScript 要长按右键，技术上能做但容易出错）

---

## 4. Phase B 推荐方案

### 推荐：组合方案 6
**`mcp-wechat-personal` MCP server** 实现以下接口：

| MCP Tool | 实现 | 风险 |
|----------|------|------|
| `list_recent_sessions(limit=10)` | SQLite query on `session_*.db` | 零 |
| `read_messages(session_id, limit=20)` | SQLite query on `message_*.db` | 零 |
| `send_message(contact_name, text)` | AppleScript: 搜索 → 选中 → typetext → Enter | 极低 |
| `search_contacts(query)` | SQLite query on `contact_*.db` | 零 |

附加约束（写在 MCP server 里）：
- 全局 send rate limit：每联系人 ≥ 30s 间隔 + 每分钟全局 ≤ 5 条
- send 接口必须传 `contact_name`，**不接受 `wxid`**（强制走 UI 搜索流程，避免直接 ID 调用看起来像机器人）
- 联系人白名单 enforced：`config/wechat-allowlist.txt` —— 默认空，Human 手动加
- 所有 send 调用记到 audit log（`projects/agent-hub/wechat-audit.log`）

### Phase B 实施前需要 Human 决定的两件事

> **这就是为什么不直接 fire Phase B。**

1. **接受"在 Human 主账号上搞自动化"的风险？**
   - 客观风险：极低（远低于 wechaty / PadLocal）
   - 主观风险：万一 Tencent 推新检测命中，最坏可能 24h 临时限制。十年老号被封概率 < 1% 但非零。
   - 替代选项：让 Human 创个小号专门给 agent 用，但小号没有现有联系人，意义大打折扣。

2. **接受 `sudo codesign --force --deep --sign - /Applications/WeChat.app`？**
   - 这会把 WeChat 重新签成 ad-hoc 签名，Apple Gatekeeper 后续不会再校验 Tencent 签名
   - WeChat 自己更新时会重新签回去，密钥提取脚本要再跑
   - 不影响 macOS 整体安全（不需要 SIP off）
   - 完全可逆：WeChat 自动更新一次就恢复 Tencent 签名

只要 Human 对这两点都点头，dev-alex 就可以 fire Phase B（估 1–2 个工作日）。

### Phase B 估时
- 解密脚本 + 密钥提取：4h
- SQLite read MCP tools (3 个 query)：4h
- AppleScript send MCP tool + rate limit + audit log：6h
- 白名单 enforcement + 测试：4h
- 文档 + 部署：2h
- **共 20h ≈ 2.5 个工作日**

---

## 5. 不可行 / 退路

如果 Human 拒绝方案 6 风险，退路按优先级：

### 退路 A：只读，不发
只实现方案 3 (DB 读)，不做发送。Personal agent 能"看"但不能"回"。Human 仍要手动回复。
- 价值：晨报里"未读消息摘要"、"今天有谁找你"，已经覆盖 70% 个人助理需求
- 风险：零（纯本地文件读）
- 工时：6h

### 退路 B：人工 forward
Human 把重要消息手动转发到 Telegram bot（`@agents_personal_bot`），personal agent 接管处理。
- 价值：覆盖 Human 主动选择的高优消息
- 风险：零
- 工时：< 2h（Telegram bot 已有，只加个标注）
- 缺点：需要 Human 主动转发，违背"自动化"初衷

### 退路 C: 暂搁置 WeChat MCP
按 #493 母 ticket，先把 #494 (Google) + #495 (iMessage) 做出来，Personal agent 先用这两个跑起来。WeChat 等到 (a) Human 风险评估通过 或 (b) 出现新的低风险接入方案 再做。

---

## 6. 推荐决策

**dev-alex 推荐**：

1. ✅ **进入 Phase B 实施方案 6**，前提是 admin 把"风险描述 + 一次性配置"摆给 Human，Human 明确点头。
2. ⚠️ 如果 Human 倾向保守，**先做退路 A（只读）**，发送侧留空。Personal agent 早一周能跑起来，覆盖大头价值。
3. ❌ 不上 wechaty 任何免费协议；**不上 PadLocal**（要扫码 + 第三方）。

**待 admin 决策的 Y/N**：
- [ ] 接受方案 6 风险，授权 Phase B（read + send）
- [ ] 暂只授权读取（退路 A），发送先不做
- [ ] 全部搁置（退路 C），先做 Google + iMessage

---

## 附录：关键链接

- [wechaty issue #2773 — 2025 封号现状](https://github.com/wechaty/wechaty/issues/2773)
- [wechaty issue #2518 — 早期生产警告](https://github.com/wechaty/wechaty/issues/2518)
- [biboyqg/wechat-mcp — Accessibility-based MCP](https://github.com/biboyqg/wechat-mcp)
- [cocohahaha/wechat-decrypt-macos — 推荐解密工具](https://github.com/cocohahaha/wechat-decrypt-macos)
- [Thearas/wechat-db-decrypt-macos — ARM64 4.x 解密（要 SIP off，不推荐）](https://github.com/Thearas/wechat-db-decrypt-macos)
- [ylytdeng/wechat-decrypt — SQLCipher 4 + 实时监控](https://github.com/ylytdeng/wechat-decrypt)
- [WeChatFerry — Windows hook（不适用 Mac）](https://github.com/lich0821/WeChatFerry)
- [puppet-padlocal — PadLocal 协议](https://github.com/wechaty/puppet-padlocal)
- [MacScripter — WeChat GUI scripting 工作样例](https://www.macscripter.net/t/gui-scripting-of-wechat/72591)
- [Reverse Engineering WeChat on macOS — 加密内幕](https://blog.imipy.com/post/reverse-engineering-wechat-on-macos--building-a-forensic-tool.html)
- [wechaty.js.org 2025-08 — LLM+Frida 逆向](https://wechaty.js.org/2025/08/12/ai-powered-reverse-engineering-concept/)
