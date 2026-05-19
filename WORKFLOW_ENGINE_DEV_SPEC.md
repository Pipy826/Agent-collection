# 任务编排引擎开发文档

**状态**: Draft  
**最后更新**: 2026-05-17  
**目标版本**: v1.1 -> v1.3

---

## 1. 背景

当前项目已经具备以下基础能力：

- Agent 创建、配置、权限、工具挂载
- Task / Schedule / Trigger / Activity Log 基础模型与接口
- WebSocket 实时对话
- Agent-to-Agent 消息与异步回传
- Workspace 文件系统与操作面板

但仍缺少“可视化任务编排引擎”这一层能力。现状更像“单 Agent 执行任务 + 触发器唤醒”，而不是“多步骤、多分支、可监控、可重试的工作流系统”。

本功能用于补齐以下能力：

- 顺序、并行、条件分支、循环、层级执行
- 可视化流程编排
- 执行状态实时跟踪
- 人工介入、失败救场、节点重试

---

## 2. 目标

### 2.1 产品目标

让用户可以像搭流程一样组织多个 Agent、工具、审批和人工步骤，用于完成复杂任务。

### 2.2 技术目标

在不推翻现有 `Task` / `ActivityLog` / `Trigger` / `ChatSession` 体系的前提下，新增一层 Workflow Runtime。

### 2.3 非目标

- 首版不做 BPMN 全量兼容
- 首版不做跨租户共享工作流市场
- 首版不做复杂低代码表达式编辑器

---

## 3. 功能范围

### 3.1 首版必须支持

1. 流程定义
2. 节点拖拽编排
3. 五类执行模式
   - 顺序
   - 并行
   - 条件分支
   - 循环
   - 子流程
4. 执行实例创建
5. 实时状态流转
6. 单节点重试
7. 人工确认节点
8. 失败 fallback 节点
9. 执行日志与产物记录

### 3.2 后续增强

- 流程模板
- 版本回滚
- 条件表达式可视化编辑
- 运行成本估算
- 流程级审批策略

---

## 4. 架构设计

## 4.1 新增核心概念

- `WorkflowDefinition`: 流程定义
- `WorkflowNode`: 流程节点
- `WorkflowEdge`: 节点连线
- `WorkflowRun`: 一次执行实例
- `WorkflowNodeRun`: 单个节点的运行实例
- `WorkflowArtifact`: 节点产出物

### 4.2 与现有模块的关系

- `Agent`: 执行主体之一
- `Task`: 可作为 WorkflowRun 的简化投影或兼容层
- `ActivityLog`: 记录流程级和节点级关键事件
- `Trigger`: 可作为流程启动器
- `ApprovalRequest`: 可承接人工确认节点
- `ChatSession`: Agent 节点对话上下文存放位置

### 4.3 推荐目录

- `backend/app/models/workflow.py`
- `backend/app/api/workflows.py`
- `backend/app/services/workflow_engine.py`
- `backend/app/services/workflow_executor.py`
- `frontend/src/pages/WorkflowBuilder.tsx`
- `frontend/src/components/workflow/*`

---

## 5. 数据模型建议

## 5.1 WorkflowDefinition

- `id`
- `tenant_id`
- `name`
- `description`
- `status` (`draft|active|archived`)
- `version`
- `created_by`
- `canvas_layout` JSON
- `input_schema` JSON
- `output_schema` JSON

## 5.2 WorkflowNode

- `id`
- `workflow_id`
- `node_key`
- `node_type`
  - `start`
  - `agent`
  - `tool`
  - `condition`
  - `loop`
  - `parallel`
  - `approval`
  - `human_input`
  - `end`
  - `subflow`
- `config` JSON
- `timeout_seconds`
- `retry_policy` JSON
- `fallback_node_key`

## 5.3 WorkflowEdge

- `id`
- `workflow_id`
- `source_node_key`
- `target_node_key`
- `edge_type` (`default|true|false|error|loop`)
- `condition_expr`

## 5.4 WorkflowRun

- `id`
- `workflow_id`
- `status` (`pending|running|waiting_human|completed|failed|cancelled`)
- `trigger_type`
- `started_by`
- `input_payload` JSON
- `context_snapshot` JSON
- `started_at`
- `finished_at`

## 5.5 WorkflowNodeRun

- `id`
- `workflow_run_id`
- `node_key`
- `status`
- `attempt`
- `executor_type`
- `executor_ref_id`
- `input_payload` JSON
- `output_payload` JSON
- `error_message`
- `started_at`
- `finished_at`

---

## 6. 执行模型

## 6.1 节点执行规则

- `agent` 节点：调用指定 Agent 执行任务
- `tool` 节点：调用平台 Tool / MCP Tool
- `condition` 节点：基于上下文表达式路由
- `parallel` 节点：同时启动多个下游节点
- `loop` 节点：直到条件满足或达到上限
- `approval` / `human_input` 节点：进入等待状态

## 6.2 上下文传递

每个 WorkflowRun 维护统一上下文对象：

- `workflow.input`
- `workflow.vars`
- `workflow.node_outputs`
- `workflow.artifacts`
- `workflow.audit_refs`

节点只读全局上下文，输出写入 `node_outputs[node_key]`。

## 6.3 失败策略

- 节点级重试
- fallback 路由
- 流程终止
- 人工接管

---

## 7. 后端接口建议

### 7.1 流程定义

- `GET /api/workflows`
- `POST /api/workflows`
- `GET /api/workflows/{id}`
- `PATCH /api/workflows/{id}`
- `DELETE /api/workflows/{id}`
- `POST /api/workflows/{id}/publish`

### 7.2 执行实例

- `POST /api/workflows/{id}/runs`
- `GET /api/workflow-runs/{run_id}`
- `POST /api/workflow-runs/{run_id}/cancel`
- `POST /api/workflow-runs/{run_id}/retry-node/{node_run_id}`
- `POST /api/workflow-runs/{run_id}/resume`

### 7.3 实时事件

复用 WebSocket 或新增频道：

- `workflow_run.started`
- `workflow_node.started`
- `workflow_node.waiting`
- `workflow_node.completed`
- `workflow_node.failed`
- `workflow_run.completed`

---

## 8. 前端设计

## 8.1 Builder 页面

包含三块：

1. 左侧节点面板
2. 中间画布
3. 右侧配置面板

推荐使用 React Flow。

## 8.2 Run Monitor 页面

显示：

- 当前执行到哪个节点
- 每个节点耗时
- 重试次数
- 错误信息
- 产出物链接
- 人工介入入口

## 8.3 AgentDetail 集成

可在 Agent 详情页新增：

- `Workflows`
- `Runs`
- `Templates`

---

## 9. 分阶段开发

### Phase 1

- 数据模型
- CRUD API
- 基础 Builder
- 顺序执行

### Phase 2

- 并行 / 条件分支 / 循环
- Run Monitor
- 节点重试
- Approval 节点

### Phase 3

- 子流程
- Trigger 启动流程
- 流程模板
- 成本统计

---

## 10. 验收标准

- 用户可以通过 UI 创建并保存流程
- 至少支持顺序、并行、条件分支三种模式
- 运行时可查看节点级状态变化
- 失败节点支持重试
- 人工审批节点可暂停并恢复流程
- 所有关键动作都有 ActivityLog / AuditLog 记录

---

## 11. 风险

- 条件表达式设计过重，影响首版交付
- 并行节点带来上下文竞争
- Agent 节点输出结构不稳定，影响下游节点消费
- 长流程可能产生大量 token 与日志数据

建议首版强制节点输出采用结构化 JSON envelope，降低链路耦合。
