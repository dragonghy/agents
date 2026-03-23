# Agent Hub Cloud — AWS 资源清单

> 日期: 2026-03-22
> 域名: sfagentos.com（已注册，有效期至 2027-03-23）
> 架构: Phase 1 单 EC2 + Docker Compose

## 需要创建的 AWS 资源

### 1. EC2 实例

| 项 | 值 |
|----|----|
| 实例类型 | t4g.large (2 vCPU, 8GB RAM, ARM Graviton) |
| AMI | Ubuntu 24.04 LTS ARM64 |
| 区域 | us-east-1 (或你偏好的区域) |
| Root Volume | 20 GB gp3 (DeleteOnTermination=true) |
| 密钥对 | 需要创建或使用现有 SSH key |
| 月成本 | ~$49 |

### 2. Data EBS Volume（独立于 EC2）

| 项 | 值 |
|----|----|
| 类型 | gp3 |
| 大小 | 50 GB（可在线扩容） |
| IOPS | 3000（gp3 基线） |
| 吞吐 | 125 MB/s |
| DeleteOnTermination | **false** ← 关键 |
| Mount 点 | /data |
| 月成本 | ~$4 |

### 3. Elastic IP

| 项 | 值 |
|----|----|
| 用途 | EC2 固定公网 IP |
| 成本 | 免费（绑定到运行中的 EC2） |

### 4. 安全组

```
Inbound:
  TCP 80    (HTTP)     ← 0.0.0.0/0
  TCP 443   (HTTPS)    ← 0.0.0.0/0
  TCP 22    (SSH)      ← 限制为你的 IP

Outbound:
  All traffic          ← 0.0.0.0/0
```

### 5. DNS（两种方案）

**方案 A：用 AWS Route 53**
- 创建 Hosted Zone: sfagentos.com
- 需要到 name.com 修改 NS 记录指向 Route 53
- 成本: $0.50/月
- 优点: Let's Encrypt 自动化（certbot dns-route53 插件）

**方案 B：直接用 name.com DNS**
- 在 name.com 添加 A 记录
- 成本: 免费
- 缺点: Let's Encrypt 通配符证书需要手动 DNS 验证，或用 certbot 的 name.com 插件

**推荐方案 A**（Route 53），SSL 自动化更省事。

### 6. S3 备份桶

| 项 | 值 |
|----|----|
| 桶名 | sfagentos-backups |
| 用途 | 每日数据库 + 实例数据备份 |
| 生命周期 | 30 天后自动删除 |
| 月成本 | < $1 |

### 7. IAM

| 资源 | 用途 |
|------|------|
| IAM User 或 Role | EC2 上的 certbot 需要 Route 53 权限（DNS-01 challenge） |
| IAM Policy | Route53 ChangeResourceRecordSets + S3 PutObject |

---

## 不需要的资源（Phase 1）

- ❌ RDS — 用 SQLite
- ❌ EFS — 用 EBS bind mount
- ❌ ALB — 用 Nginx
- ❌ ECS/EKS — 用 Docker Compose
- ❌ ACM — 用 Let's Encrypt

---

## DNS 记录（部署后配置）

```
sfagentos.com          A     → <Elastic IP>
*.sfagentos.com        A     → <Elastic IP>
```

---

## 月度成本汇总

| 资源 | 月费 |
|------|------|
| EC2 t4g.large | $49 |
| EBS data 50GB | $4 |
| EBS root 20GB | $1.60 |
| EBS snapshots | ~$2 |
| Route 53 | $0.50 |
| S3 备份 | < $1 |
| Elastic IP | 免费 |
| SSL | 免费 |
| **总计** | **~$58/月** |

域名: $12.99/年（已付）

---

## 部署顺序

```
1. 创建 EC2 + Data Volume + Elastic IP + 安全组
2. SSH 进去装 Docker
3. 格式化 data volume，mount 到 /data
4. Route 53 Hosted Zone + 改 name.com NS 记录
5. Let's Encrypt 通配符证书
6. 克隆代码 + 构建前端 + docker compose up
7. 验证 https://sfagentos.com
```
