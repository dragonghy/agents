### Agent Hub 部署与架构演进方案 (Technical Design Doc)
**版本:** v1.1  
**状态:** 待评审 / 准备执行  
**核心理念:** 容器化抽象、资源超卖（Overcommit）、数据面与控制面解耦。

#### 1. 架构愿景：从“孤岛”到“平台”
我们的长远目标是构建一个能够服务数百个客户的 Agent 托管平台。该平台必须解决以下核心矛盾：
*   **重型环境**: 每个 Agent 容器包含 Chrome、Cron 等 Linux 进程，启动成本高。
*   **资源浪费**: 客户活跃度不一，静态分配内存（如每人 2GB）会导致极高的无效成本。
*   **平滑迁移**: 现在的单机方案必须能无缝过渡到未来的多机集群架构。

#### 2. 数据架构设计 (The "Solid" Foundation)
为了支持未来的灵活调度，我们将数据分为两个维度：
**2.1 控制平面数据 (Global Level)**
*   内容: 公司信息、客户 ID、Instance 配置清单（地址、Setup 参数）、资源配额。
*   存储: 中心化数据库 (RDS PostgreSQL)。
*   目的: 实现全局可见性。无论容器在哪台机器跑，管理后台都能通过 DB 找到它。
**2.2 数据平面数据 (Instance Level)**
*   内容: File System (用户文件)、Agent Memory (上下文状态)、本地日志。
*   存储:
    *   短期: 挂载 EC2 独立数据盘 (EBS) 的特定目录。
    *   长期: 迁移至 AWS EFS。
*   关键设计: 路径虚拟化。代码中访问 `/app/data`，底层由 K8s 决定挂载到哪里。

#### 3. 部署方案演进路径
**Phase 1: 单机 K3s 平台 (当前执行方案)**
在单台 `t4g.large` (或更大) EC2 上部署 K3s（轻量级 Kubernetes）。
*   **为什么用 K3s 而非 Docker Compose?**
    *   自动化超卖: 通过 K8s 的 Requests 和 Limits 自动管理内存。
    *   API 兼容: 现在写的部署脚本（YAML）未来在 EKS 上直接复用。
*   **资源管理**:
    *   Request: 256MB / Limit: 2GB。
    *   开启少量 Swap 作为 OOM 缓冲。
*   **网络**: 使用内置的 Traefik Ingress，实现 `customer-a.agent.com` 动态转发。

**Phase 2: 托管 EKS 平台 (规模化阶段)**
当单台 EC2 的 CPU/内存/网络达到瓶颈（通常在 20-50 个活跃客户时）迁移。
*   变更点: 将 K3s 升级为 AWS EKS。
*   计算: 购买多个 EC2 实例作为 Workload Nodes。
*   自动化: 引入 Cluster Autoscaler。当现有的 Node 塞不下新的 Pod 时，AWS 自动开新机器。
*   计费: 支付 EC2 实例费用 + EKS 管理费（$72/月）。通过超卖压榨每台 EC2 的价值。

#### 4. 关键技术细节与“避坑”指南
**4.1 内存优化与回收**
*   闲置挂起: 在管理后台增加逻辑，若 Instance 超过 2 小时无任务，直接删除 K8s Pod 释放内存，仅保留 DB 中的 Metadata。
*   快速恢复: Agent 代码需支持 Save/Load State。新容器启动时从 DB 加载 Memory，实现“热插拔”体验。
**4.2 存储隔离**
*   强制隔离: 严禁不同 Instance 共享同一个存储根目录。
*   PV/PVC 模式: 即使在单机 K3s 阶段，也使用 Kubernetes 的 Persistent Volume 声明，方便未来切换底层存储介质。
**4.3 成本预估 (Phase 1)**
| 组件 | 规格 | 预估月费 |
|---|---|---|
| EC2 | t4g.xlarge (4 vCPU, 16GB) | ~$65 (计算超卖可跑 ~30 客户) |
| EBS | 100GB (GP3) | ~$8 |
| RDS | db.t4g.micro (最简版) | ~$15 |
| **总计** | | **约 $88 / 月** |

#### 5. 下一步执行计划 (Action Items)
*   [代码层]：完成 Storage 抽象层，确保所有文件读写基于相对路径。
*   [数据库]：在 AWS 创建一个最便宜的 RDS PostgreSQL，迁移 Global Metadata。
*   [部署层]：在 EC2 上安装 K3s，并编写第一个 `deployment.yaml` 模板。
*   [验证]：测试在内存占满 80% 时，启动新 Pod 是否会导致旧 Pod 被正确调度或 Evict。