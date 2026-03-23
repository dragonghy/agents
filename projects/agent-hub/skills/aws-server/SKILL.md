---
name: aws-server
description: 请求启动/停止 Agent-Hub 云服务器（AWS EC2）。当你需要使用 sfagentos.com 上的容器资源时，用此 skill 了解如何请求。
---

# AWS 云服务器使用指南

## 概述

Agent-Hub 的云端部署运行在 AWS EC2 上（us-west-2, sfagentos.com）。为节省成本，服务器在不使用时会被停止（Stop），需要时由 Ops Agent 启动。

**你不能直接操作 AWS 资源。** 所有启停操作必须通过 Ops Agent 执行。

## 如何请求启动服务器

给 `ops` 发消息，说明：

1. **用途**：你需要服务器做什么
2. **时长**：预计使用多久（如 "1 小时"、"30 分钟"）

示例：
```
send_message(
  from_agent="dev-alex",
  to_agent="ops",
  body="请启动 Agent-Hub 云服务器，我需要部署新版本代码到 sfagentos.com，预计使用 1 小时。"
)
```

## 如何延长使用时间（Extend）

如果时间快到了但还没用完，给 `ops` 发消息请求延长：

```
send_message(
  from_agent="dev-alex",
  to_agent="ops",
  body="请延长服务器使用时间到 20:30（再延长 1 小时）。"
)
```

## 如何提前释放

用完了可以主动通知 ops 提前释放：

```
send_message(
  from_agent="dev-alex",
  to_agent="ops",
  body="我已经用完了，可以停止服务器了。"
)
```

## 服务器信息

| 项目 | 值 |
|------|-----|
| 域名 | sfagentos.com / *.sfagentos.com |
| 区域 | us-west-2 |
| 启动耗时 | ~3-5 分钟 |
| 停止耗时 | ~1 分钟 |

## 注意事项

- **不要自行操作 AWS CLI** — 所有基础设施操作由 ops 执行
- 服务器停止后数据不会丢失（EBS 卷持久保留）
- Elastic IP 绑定不变，停止/启动后 IP 和 DNS 不变
- 服务器启动后 Docker 容器会自动拉起，无需手动干预
