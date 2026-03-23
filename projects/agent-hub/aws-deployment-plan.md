# Agent Hub Cloud — AWS 部署方案

> 日期: 2026-03-21 (v2)
> 作者: product-lisa
> Ticket: #412
> 状态: 待 Human 确认后执行

---

## 整体思路：两阶段演进

| | Phase 1（MVP） | Phase 2（增长） |
|--|--|--|
| **管理面** | EC2 上 Docker | 同左（或 ECS） |
| **客户实例** | 同一台 EC2 上 Docker | **ECS Fargate（按需启停，按秒计费）** |
| **存储** | 独立 EBS data volume + S3 备份 | EFS（共享）+ RDS |
| **路由** | 本地 Nginx | ALB + ACM |
| **适用规模** | 1-20 客户 | 20-500+ 客户 |
| **月成本** | ~$55 固定 | 按实际使用量 |

---

# Phase 1：单 EC2 部署（MVP）

## 1.1 架构

```
用户浏览器
    │
    ▼
┌──────────────────────────────────────────────┐
│  Route 53:  *.agenthub.cloud → Elastic IP    │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  EC2 Instance (Ubuntu 24.04)                 │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Nginx (:80/:443)                      │  │
│  │  Let's Encrypt wildcard SSL            │  │
│  └──────────┬─────────────────────────────┘  │
│             │                                │
│  ┌──────────▼─────────────────────────────┐  │
│  │  Management Plane (:3000)              │  │
│  └──────────┬─────────────────────────────┘  │
│             │ docker.sock                    │
│  ┌──────────▼─────────────────────────────┐  │
│  │  Instance Containers                   │  │
│  │  alice-daemon :10000                   │  │
│  │  bob-daemon   :10001                   │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  /dev/sda1 (root, 20GB) ← 系统盘，随EC2生死   │
│  /dev/sdf  (data, 50GB) ← 数据盘，独立存在    │
│             └── mount 到 /data               │
└──────────────────────────────────────────────┘
```

## 1.2 EC2 选型

**推荐：`t4g.large`（ARM Graviton）**

| 规格 | 值 |
|------|----|
| vCPU | 2 |
| 内存 | 8 GB |
| 价格 | ~$49/月（按需），~$31/月（1年预留） |

安全组：
```
Inbound:  TCP 80, 443 (0.0.0.0/0)  |  TCP 22 (你的IP)
Outbound: All
```

## 1.3 存储设计（关键）

### 双 EBS Volume

```
/dev/sda1  (root volume, 20GB, gp3)
  └── DeleteOnTermination = true（默认）
  └── 只装系统、Docker、代码

/dev/sdf   (data volume, 50GB, gp3)
  └── DeleteOnTermination = false  ← 关键！EC2 挂了数据不丢
  └── mount 到 /data
  └── 每日 EBS snapshot
```

**EC2 挂了怎么办**：
1. 新开一台 EC2
2. 把 data volume attach 上去
3. mount 到 /data
4. 部署代码 + docker compose up
5. 数据完整恢复

### 数据目录结构

所有数据 bind mount（不用 Docker named volume），确保可迁移：

```
/data/
├── management/
│   └── management.db              ← 管理面 SQLite
├── instances/
│   ├── alice/
│   │   ├── config/                ← docker-compose.yml, agents.yaml, .env
│   │   └── data/                  ← bind mount 到容器内
│   │       ├── daemon.db          ← 实例的 tickets/messages/profiles
│   │       └── workspace/         ← agent 工作空间
│   └── bob/
│       ├── config/
│       └── data/
└── backups/
    └── daily/
```

**为什么用 bind mount 而非 Docker volume**：
- 文件在宿主机可见，直接 `tar` 打包迁移
- 目录结构清晰，每个客户一个文件夹
- 备份脚本简单（直接 `rsync` 或 `tar`）

### 迁移一个客户

```bash
# 1. 停实例
docker compose -p aghub-alice down

# 2. 打包（config + data 全在一个目录里）
tar czf alice-backup.tar.gz /data/instances/alice/

# 3. 拷到新位置（另一台 EC2 / 本地 / S3）
scp alice-backup.tar.gz target:/data/instances/

# 4. 解压启动
tar xzf alice-backup.tar.gz
docker compose -p aghub-alice up -d

# 5. 更新管理面 DB 中的路由信息
# （一条 SQL update）
```

### 备份策略

```bash
# Cron: 每天凌晨 3 点
0 3 * * * /opt/agenthub/scripts/backup.sh

# backup.sh:
# 1. EBS snapshot（自动，AWS Backup 配置）
# 2. S3 增量同步
aws s3 sync /data/backups/ s3://agenthub-backups/ --delete
# 3. 本地保留 7 天，S3 保留 30 天
```

| 备份方式 | RPO | 成本 |
|---------|-----|------|
| EBS snapshot (每日) | 24h | ~$2/月 |
| S3 sync | 24h | < $1/月 |
| 手动 snapshot | 即时 | 免费 |

## 1.4 域名和 SSL

### DNS (Route 53)

```
agenthub.cloud         A     → Elastic IP
*.agenthub.cloud       A     → Elastic IP
```

成本：$0.50/月

### SSL: Let's Encrypt 通配符证书（免费）

```bash
sudo apt install certbot python3-certbot-dns-route53

sudo certbot certonly \
  --dns-route53 \
  -d "agenthub.cloud" \
  -d "*.agenthub.cloud" \
  --agree-tos \
  --email admin@agenthub.cloud \
  --non-interactive

# 自动续期：certbot 自带 systemd timer
# 证书路径：/etc/letsencrypt/live/agenthub.cloud/
```

## 1.5 部署流程

### Step 1: 创建 EC2 + Data Volume

```bash
# 创建 EC2（root volume 20GB）
aws ec2 run-instances \
  --image-id ami-0c7217cdde317cfec \
  --instance-type t4g.large \
  --key-name your-key \
  --security-group-ids sg-xxx \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]'

# 创建独立 data volume（不会随 EC2 删除）
aws ec2 create-volume \
  --size 50 \
  --volume-type gp3 \
  --availability-zone us-east-1a \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=agenthub-data}]'

# Attach data volume
aws ec2 attach-volume --volume-id vol-xxx --instance-id i-xxx --device /dev/sdf

# Elastic IP
aws ec2 allocate-address
aws ec2 associate-address --instance-id i-xxx --allocation-id eipalloc-xxx
```

### Step 2: 初始化

```bash
ssh ubuntu@<elastic-ip>

# 格式化并挂载 data volume
sudo mkfs.ext4 /dev/nvme1n1   # 或 /dev/xvdf，看具体设备名
sudo mkdir -p /data
sudo mount /dev/nvme1n1 /data
echo '/dev/nvme1n1 /data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo chown ubuntu:ubuntu /data

# 创建目录结构
mkdir -p /data/{management,instances,backups/daily}

# 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
# 重新登录让 group 生效
```

### Step 3: 部署代码

```bash
git clone <repo-url> /opt/agenthub
cd /opt/agenthub

# 创建 .env
cat > .env << 'EOF'
MGMT_DOMAIN=agenthub.cloud
MGMT_MOCK_MODE=false
MGMT_HOST_REPO_ROOT=/opt/agenthub
MGMT_HOST_INSTANCES_DIR=/data/instances
MGMT_DB_PATH=/data/management/management.db
JWT_SECRET=$(openssl rand -hex 32)
MGMT_ENCRYPT_KEY=$(openssl rand -hex 16)
MGMT_USAGE_SECRET=$(openssl rand -hex 16)
EOF

# 获取 SSL 证书
sudo apt install certbot python3-certbot-dns-route53
sudo certbot certonly --dns-route53 \
  -d "agenthub.cloud" -d "*.agenthub.cloud" \
  --agree-tos --email admin@agenthub.cloud --non-interactive

# 构建前端
cd services/management-plane/web && npm install && npm run build && cd -

# 启动
docker compose -f docker-compose.cloud.yml --env-file .env up --build -d

# 验证
curl -s https://agenthub.cloud/api/health
```

### Step 4: 配置 Route 53

```
agenthub.cloud       A    → <Elastic IP>
*.agenthub.cloud     A    → <Elastic IP>
```

## 1.6 Phase 1 成本

| 项目 | 月费 |
|------|------|
| EC2 t4g.large（按需） | $49 |
| EBS root 20GB gp3 | $1.60 |
| EBS data 50GB gp3 | $4 |
| EBS snapshots | ~$2 |
| Route 53 | $0.90 |
| S3 备份 | < $1 |
| SSL | 免费 |
| Elastic IP | 免费 |
| **总计** | **~$59/月** |

---

# Phase 2：ECS Fargate（按需计费）

当客户数 > 20 或需要弹性伸缩时迁移到此架构。

## 2.1 架构

```
用户浏览器
    │
    ▼
┌────────────────────────────────────────────────────┐
│  Route 53:  *.agenthub.cloud → ALB               │
└──────────────────┬─────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────┐
│  ALB (Application Load Balancer)                   │
│  ACM 通配符证书（免费，自动续期）                     │
│                                                    │
│  规则：                                             │
│  agenthub.cloud      → Target: Management (固定)   │
│  alice.agenthub.cloud → Target: alice Task (动态)   │
│  bob.agenthub.cloud   → Target: bob Task (动态)     │
└──────────┬─────────────┬──────────────┬────────────┘
           │             │              │
           ▼             ▼              ▼
    ┌────────────┐ ┌──────────┐  ┌──────────┐
    │ EC2 (固定)  │ │ Fargate  │  │ Fargate  │
    │ Management │ │ alice    │  │ bob      │
    │ Plane      │ │ daemon   │  │ daemon   │
    └─────┬──────┘ └────┬─────┘  └────┬─────┘
          │              │             │
          ▼              ▼             ▼
    ┌─────────────────────────────────────────┐
    │  共享存储                                │
    │  RDS PostgreSQL (管理面)                 │
    │  EFS (实例数据，各实例独立子目录)           │
    └─────────────────────────────────────────┘
```

## 2.2 核心区别：Fargate 按需启停

```
Customer 不在线：
  → ECS Service desired_count = 0
  → Fargate 不运行任何容器
  → 费用 = $0

Customer 登录/有任务：
  → Management Plane 调 ECS API: desired_count = 1
  → Fargate 30 秒内启动容器
  → 费用 = 按秒计费（~$0.04/小时 for 1vCPU/2GB）

Customer 长时间不活跃：
  → 自动缩到 0
  → 费用回到 $0
```

**每个客户实例的 Fargate 成本**：

| 使用时长 | 月成本 |
|---------|--------|
| 24/7 在线 | ~$29/月 |
| 每天 8 小时 | ~$10/月 |
| 每天 2 小时 | ~$2.5/月 |
| 偶尔使用 | < $1/月 |

对比固定 EC2：即使最小的 t4g.small 也要 $12/月，不管用不用。

## 2.3 存储方案

### Management DB: RDS PostgreSQL

- 从 SQLite 迁移到 PostgreSQL（支持并发、备份、高可用）
- `db.t4g.micro`：~$12/月
- 自动备份 + 多 AZ 可选

### 实例数据: EFS (Elastic File System)

```
EFS mount: /efs/
├── instances/
│   ├── alice/
│   │   ├── daemon.db       ← 实例 SQLite（EFS 支持单写者模式）
│   │   └── workspace/
│   └── bob/
```

**为什么 EFS**：
- Fargate 原生支持 EFS volume mount
- 实例停了数据还在（不像 Fargate 本地存储会消失）
- 多个 Fargate task 可以访问同一个 EFS（但每个实例只访问自己的子目录）
- 按使用量计费：$0.30/GB/月

**注意**：SQLite 在 EFS 上性能一般（网络延迟），但 daemon DB 操作频率低，可以接受。如果不行，可以改为每个实例用 RDS PostgreSQL schema。

### 迁移路径

从 Phase 1 → Phase 2：

```bash
# 1. 管理面 DB
#    SQLite → PostgreSQL：pgloader 一键迁移
pgloader /data/management/management.db postgresql://user:pass@rds-host/agenthub

# 2. 实例数据
#    EBS → EFS：rsync 同步
mount -t efs fs-xxx:/ /efs
rsync -av /data/instances/ /efs/instances/

# 3. 创建 ECS Task Definition（每个客户模板）
#    基于现有 docker-compose.yml 转换

# 4. ALB 规则
#    Management Plane 注册/删除实例时，调 ECS API + ALB API
```

## 2.4 Phase 2 成本估算

**固定成本**：

| 项目 | 月费 |
|------|------|
| EC2 Management Plane (t4g.small) | $12 |
| RDS PostgreSQL (db.t4g.micro) | $12 |
| ALB | $16 + $0.008/LCU-hr |
| Route 53 | $0.90 |
| ACM SSL | 免费 |
| **固定总计** | **~$41/月** |

**按客户变动成本**：

| 项目 | 单价 |
|------|------|
| Fargate (1vCPU/2GB, 按小时) | $0.04/hr |
| EFS (按 GB) | $0.30/GB/月 |

**示例**：20 个客户，平均每天活跃 4 小时：
- Fargate: 20 × 4hr × 30天 × $0.04 = $96/月
- EFS: 20 × 2GB × $0.30 = $12/月
- 固定: $41
- **总计: ~$149/月**

对比 Phase 1（20 个客户全在一台 EC2）：~$120/月（需要 t3.xlarge）
对比 20 × 独立 EC2：20 × $49 = $980/月

**Fargate 在客户不同时在线时显著省钱。**

---

## 从 Phase 1 到 Phase 2 的迁移 Checklist

- [ ] 管理面 DB: SQLite → RDS PostgreSQL
- [ ] 实例数据: EBS bind mount → EFS
- [ ] 路由: Nginx → ALB + ACM
- [ ] 实例管理: docker compose → ECS Task Definition
- [ ] Instance Manager 代码: 调 docker CLI → 调 ECS API
- [ ] 客户实例逐个迁移（可以灰度）

---

## Phase 1 部署前 Checklist

- [ ] 域名已购买并在 Route 53 中配置
- [ ] EC2 实例已创建（t4g.large）
- [ ] **独立 data EBS volume 已创建并 attach（DeleteOnTermination=false）**
- [ ] Data volume 已格式化、mount 到 /data、写入 fstab
- [ ] Elastic IP 已绑定
- [ ] 安全组已配置（80/443/22）
- [ ] Docker + Docker Compose 已安装
- [ ] 代码已克隆到 /opt/agenthub
- [ ] .env 文件已配置（JWT_SECRET 等随机生成）
- [ ] Let's Encrypt 通配符证书已获取
- [ ] 前端已构建 (npm run build)
- [ ] docker compose up 成功
- [ ] https://域名/api/health 返回 ok
- [ ] 注册 → 创建公司 → 实例可访问 流程验证
- [ ] EBS 每日 snapshot 已配置（AWS Backup）
- [ ] S3 备份 cron 已配置
- [ ] SSH 密钥登录已加固
