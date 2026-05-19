# 标准 A2A 跨实例协作开发文档

**状态**: Draft  
**最后更新**: 2026-05-17  
**目标版本**: v1.2 -> v1.4

---

## 1. 背景

当前项目已经具备自定义 Agent-to-Agent 能力：

- 平台内 Agent 关系管理
- OpenCode Gateway 轮询与回传
- Agent 间消息与异步回复
- ChatSession / GatewayMessage 持久化

但这套能力仍是“平台内部协议 + 自定义 Gateway”，尚未达到需求中定义的“基于 Google A2A v0.3.0 的跨实例发现与通信”。

本功能目标是让不同服务器上的 Clawith / OpenCode 实例，能够像网络中的独立节点一样互相发现、能力声明、任务委派和结果回传。

---

## 2. 目标

### 2.1 产品目标

让用户和 Agent 可以调用其他部署点上的 Agent，而不要求全部 Agent 都在同一数据库或同一后端中。

### 2.2 技术目标

在保留现有 `opencode_gateway.py` 的同时，引入标准化 A2A Adapter 层。

### 2.3 非目标

- 首版不做全自动公网穿透
- 首版不做联邦身份完全互信
- 首版不做跨组织计费清结算

---

## 3. 功能范围

### 3.1 首版必须支持

1. 远端 Agent 能力声明
2. 远端实例注册
3. 基于技能 / 标签的远端发现
4. 任务委派
5. 异步状态查询
6. 回调与失败重试
7. 基础鉴权
8. 跨实例会话审计

### 3.2 后续增强

- mDNS / DNS-SD 自动发现
- gRPC 传输
- 多协议回退
- 跨租户信任策略
- 跨实例成本统计

---

## 4. 现有能力与缺口

### 4.1 已有

- `backend/app/api/opencode_gateway.py`
- `GatewayMessage`
- `ChatSession`
- `AgentAgentRelationship`
- 平台内异步消息回流

### 4.2 缺口

- 标准 Agent Card / Capability Manifest
- 远端实例注册表
- 协议版本协商
- 远端发现与路由评分
- 统一 callback / polling 抽象
- 跨实例认证与签名校验

---

## 5. 架构设计

## 5.1 分层

1. `A2A Registry`
2. `A2A Transport`
3. `A2A Router`
4. `A2A Task Runtime`
5. `A2A Audit Layer`

## 5.2 推荐目录

- `backend/app/models/a2a.py`
- `backend/app/api/a2a.py`
- `backend/app/services/a2a/registry.py`
- `backend/app/services/a2a/router.py`
- `backend/app/services/a2a/transports/*.py`
- `backend/app/services/a2a/tasks.py`

---

## 6. 数据模型建议

## 6.1 RemoteInstance

- `id`
- `tenant_id`
- `name`
- `base_url`
- `protocol_version`
- `status`
- `auth_type`
- `public_key`
- `last_seen`
- `metadata` JSON

## 6.2 RemoteAgentCard

- `id`
- `remote_instance_id`
- `remote_agent_id`
- `name`
- `description`
- `capabilities` JSON
- `skills` JSON
- `labels` JSON
- `availability_status`
- `last_synced_at`

## 6.3 A2ATask

- `id`
- `source_agent_id`
- `target_mode` (`local|remote`)
- `target_instance_id`
- `target_agent_ref`
- `request_payload` JSON
- `status`
- `callback_url`
- `external_task_id`
- `created_at`
- `finished_at`

## 6.4 A2AEventLog

- `id`
- `task_id`
- `event_type`
- `payload` JSON
- `created_at`

---

## 7. 协议设计

## 7.1 能力发现

平台从远端拉取标准能力描述：

- agent id
- display name
- skills
- supported task types
- auth requirements
- callback support

## 7.2 任务提交

统一抽象：

- `create_task`
- `get_task_status`
- `cancel_task`
- `submit_callback`

## 7.3 传输层

首版建议只落地 REST / JSON。

后续扩展：

- JSON-RPC
- gRPC

所有传输层都适配到同一内部接口，避免业务层感知协议差异。

## 7.4 鉴权

建议支持：

- API Key
- HMAC 签名
- 时间戳 + nonce 防重放

---

## 8. 路由与选型

## 8.1 路由输入

- 目标能力标签
- 任务类型
- 优先组织内 / 外
- 延迟偏好
- 成本偏好
- 可用性要求

## 8.2 路由评分

初版可用加权分：

- 技能匹配度
- 健康状态
- 最近成功率
- 预计延迟
- 调用成本
- 组织信任等级

## 8.3 降级策略

1. 远端首选失败
2. 备选远端
3. 本地 Agent fallback
4. 返回人工处理提示

---

## 9. 与现有 Gateway 的关系

不建议直接废弃 `opencode_gateway.py`。

建议路径：

- 把现有 Gateway 视为 `Custom Poll Transport`
- 在 A2A Adapter 层包装成统一接口
- 新的标准 A2A 实现与旧 Gateway 并存

这样可以保留现有 OpenCode 节点接入能力，逐步过渡到标准化跨实例协作。

---

## 10. API 建议

### 10.1 实例管理

- `GET /api/a2a/instances`
- `POST /api/a2a/instances`
- `PATCH /api/a2a/instances/{id}`
- `POST /api/a2a/instances/{id}/sync`

### 10.2 能力发现

- `GET /api/a2a/agents/search`
- `GET /api/a2a/agents/{card_id}`

### 10.3 任务

- `POST /api/a2a/tasks`
- `GET /api/a2a/tasks/{id}`
- `POST /api/a2a/tasks/{id}/cancel`
- `POST /api/a2a/callback/{token}`

---

## 11. 前端设计

## 11.1 管理端

在企业设置中新增：

- Remote Instances
- Agent Discovery
- A2A Audit

## 11.2 Agent 详情页

新增：

- 允许被远程发现
- 发布能力标签
- 允许跨实例调用
- 默认回调模式

## 11.3 协作体验

用户选择 Agent 时，应同时支持：

- 本地 Agent
- 远端 Agent
- 自动匹配最佳 Agent

---

## 12. 分阶段开发

### Phase 1

- RemoteInstance / RemoteAgentCard / A2ATask 模型
- REST transport
- 手工注册远端实例
- 基础任务委派

### Phase 2

- 路由评分
- callback / polling 双模式
- UI 搜索与远端调用
- A2A 审计页

### Phase 3

- JSON-RPC / gRPC adapter
- mDNS / DNS-SD
- 信任策略与组织互联

---

## 13. 验收标准

- 两个独立部署的实例可以互相注册
- 可以从实例 A 发现实例 B 的 Agent 能力
- 可以从实例 A 向实例 B 发起任务
- 支持异步状态查询和回调收敛
- 所有跨实例调用都有审计记录
- 远端不可用时有明确降级与错误提示

---

## 14. 风险

- 协议标准理解偏差导致后续兼容成本高
- 远端实例不稳定导致链路延迟放大
- 跨实例认证处理不严会带来安全风险
- 路由策略过早复杂化拖慢交付

建议先把“统一抽象层 + REST 传输 + 可观测性”做稳，再扩展标准协议覆盖面。
