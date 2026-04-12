---
name: aws-server-lifecycle
description: AWS EC2 服务器生命周期管理（Start/Stop/Extend）。收到服务器启停请求时使用此 skill。
---

# AWS 云服务器生命周期管理

## 资源信息

| 资源 | ID / 值 |
|------|---------|
| EC2 Instance | `i-0199980a38fbf6b76` (t4g.large) |
| Region | `us-west-2` |
| Elastic IP | `52.40.126.37` (eipalloc-0342f6a44b874db09) |
| Root EBS | `vol-0c8b8826313b82557` (20GB gp3, /dev/sda1) |
| Data EBS | `vol-0561c2994a538f0f4` (50GB gp3, /dev/sdf, DeleteOnTermination=false) |
| Security Group | `sg-04d56f8725ef493e1` (sfagentos-sg) |
| SSH Key | `sfagentos-key` (key-0ac640989fb995974) |
| Route 53 Zone | `Z03946001T5K5XYILF0S4` |
| S3 Bucket | `sfagentos-backups` |
| IAM Role | `sfagentos-ec2-role` |
| 域名 | sfagentos.com / *.sfagentos.com |
| SSH 用户 | ubuntu |
| SSH 凭证 | 1Password "Agent Ops" vault → "sfagentos EC2 SSH Key (us-west-2)" |

## Start 流程

收到启动请求时（来自其他 Agent 或 Human 的消息）：

1. **确认请求**：记录谁请求的、用途、预计使用时长
2. **启动实例**（通过 AWS MCP）：
   ```javascript
   // region: us-west-2
   const ec2 = new AWS.EC2({ region: 'us-west-2' });
   await ec2.startInstances({ InstanceIds: ['i-0199980a38fbf6b76'] }).promise();
   ```
3. **等待就绪**：确认实例状态变为 `running`（约 1-2 分钟）
4. **验证服务**：SSH 检查 Docker 容器是否自动启动（约 2-3 分钟）
5. **回复请求者**：告知服务器已就绪，提供到期时间

## Stop 流程

到期或收到释放请求时：

1. **检查使用者**：如果是自动到期，先确认是否有人仍在使用
2. **停止实例**（通过 AWS MCP）：
   ```javascript
   // region: us-west-2
   const ec2 = new AWS.EC2({ region: 'us-west-2' });
   await ec2.stopInstances({ InstanceIds: ['i-0199980a38fbf6b76'] }).promise();
   ```
3. **确认停止**：确认状态变为 `stopped`
4. **通知相关方**：告知服务器已停止

## Extend 流程

收到延长请求时：

1. **确认新的到期时间**
2. **回复确认**：告知延长成功和新的到期时间

## 状态检查

```javascript
// region: us-west-2
const ec2 = new AWS.EC2({ region: 'us-west-2' });
const result = await ec2.describeInstances({ InstanceIds: ['i-0199980a38fbf6b76'] }).promise();
return result.Reservations[0].Instances[0].State.Name;
```

## 费用说明

- **运行时**：~$58/月（EC2 $49 + EBS $5.6 + EIP $3.6 + Route53 $0.50）
- **停止时**：~$10/月（EBS $5.6 + EIP $3.6 + Route53 $0.50）
- Start/Stop 本身不收费

## 权限

- Start/Stop 已有实例：✅ 可以自行执行
- 创建/删除实例：🔴 需要 Human 批准
