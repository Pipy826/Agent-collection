# 长期记忆与自学习闭环开发文档

**状态**: Draft  
**最后更新**: 2026-05-17  
**目标版本**: v1.2 -> v1.5

---

## 1. 背景

当前项目已经具备一些与“记忆”和“自学习”相关的基础：

- Agent workspace / memory 文件结构
- ChatSession / ChatMessage 历史
- Trigger / Heartbeat 主动唤醒
- Plaza 发帖与评论
- 审批、审计、组织管理

但需求中的这三条仍未闭环：

1. 基于向量数据库的长期记忆
2. 跨会话用户偏好记忆与组织画像
3. 人工纠错、黄金题库、热点缺口分析

本功能要做的不是“再加一个 memory.md 文件”，而是形成“采集 -> 归档 -> 检索 -> 纠错 -> 再利用”的系统级学习回路。

---

## 2. 目标

### 2.1 产品目标

让 Agent 在多轮、多会话、多场景下持续变得更懂用户、更懂组织、更少犯重复错误。

### 2.2 技术目标

建立统一的 Memory Pipeline，打通：

- 对话历史
- 组织知识库
- 用户偏好
- 纠错反馈
- 相似问题召回

### 2.3 非目标

- 首版不做模型再训练
- 首版不做自动微调
- 首版不做完全无人审核的知识写回

---

## 3. 功能范围

### 3.1 首版必须支持

1. 长期记忆写入与向量检索
2. 用户偏好记忆
3. Agent 级跨会话记忆召回
4. 组织级共享知识召回
5. 回答点赞 / 点踩
6. 点踩后提交纠正答案
7. 黄金题库写入与相似召回
8. 热点缺口分析报表

### 3.2 后续增强

- 组织画像片段交换
- 记忆冲突解决策略
- 记忆衰减与归档
- 自动知识摘要与合并

---

## 4. 总体架构

## 4.1 三层记忆模型

### Layer 1: 会话短期记忆

来源：

- 当前 ChatSession 上下文
- 最近 N 轮消息

### Layer 2: Agent 长期记忆

来源：

- 历史对话提炼
- 用户偏好
- 工作经验总结
- 重要事实

### Layer 3: 组织共享记忆

来源：

- 企业知识库
- Plaza 总结
- 已审核黄金题库
- 管理员确认的团队知识

---

## 5. 数据模型建议

## 5.1 MemoryDocument

- `id`
- `tenant_id`
- `agent_id` nullable
- `user_id` nullable
- `scope` (`agent|user|tenant|golden`)
- `memory_type`
  - `fact`
  - `preference`
  - `summary`
  - `correction`
  - `profile_fragment`
- `title`
- `content`
- `source_type`
- `source_ref_id`
- `importance_score`
- `visibility`
- `is_verified`
- `created_at`

## 5.2 MemoryChunk

- `id`
- `memory_document_id`
- `chunk_index`
- `content`
- `embedding_model`
- `embedding_vector`
- `token_count`

## 5.3 AnswerFeedback

- `id`
- `message_id`
- `agent_id`
- `user_id`
- `feedback_type` (`upvote|downvote`)
- `comment`
- `corrected_answer`
- `created_at`

## 5.4 GoldenExample

- `id`
- `tenant_id`
- `agent_id` nullable
- `question`
- `normalized_question`
- `correct_answer`
- `source_feedback_id`
- `status` (`pending_review|approved|rejected|active`)
- `tags` JSON
- `created_at`

## 5.5 KnowledgeGapReport

- `id`
- `tenant_id`
- `question_cluster`
- `frequency`
- `affected_agents`
- `suggested_action`
- `status`
- `created_at`

---

## 6. 检索流程设计

## 6.1 回答前检索顺序

1. 当前会话上下文
2. 用户偏好记忆
3. Agent 长期记忆
4. 黄金题库相似问题
5. 企业知识库
6. 外部搜索 / 其他 Agent 求助

## 6.2 写入流程

触发来源：

- 对话结束后摘要
- 用户显式偏好表达
- 工具执行总结
- 用户点踩纠错
- 管理员确认知识

## 6.3 写入策略

不是所有消息都入库。仅在满足以下条件时写入：

- 可复用
- 相对稳定
- 对未来决策有帮助
- 不包含高风险敏感内容

---

## 7. 向量数据库方案

## 7.1 首版建议

优先选 PostgreSQL + pgvector，原因：

- 与当前主库体系贴合
- 便于租户隔离
- 运维复杂度低

## 7.2 替代方案

- Qdrant
- Milvus
- Weaviate

若后续记忆量暴涨，再拆为独立检索服务。

---

## 8. 反馈与黄金题库

## 8.1 前端交互

在 Agent 回答消息下新增：

- 点赞
- 点踩
- 点踩后弹窗：
  - 问题出在哪
  - 正确答案是什么
  - 是否写入团队知识

## 8.2 处理流程

1. 用户点踩
2. 创建 `AnswerFeedback`
3. 若填写纠正答案，则生成 `GoldenExample`
4. 管理员或规则自动审核
5. 审核通过后参与相似问题召回

## 8.3 召回策略

当新问题进入时：

- 先做问题归一化
- 查相似黄金题
- 若高于阈值，优先注入纠正答案

---

## 9. 热点缺口分析

## 9.1 目标

自动发现“团队常问，但系统回答差、知识库又缺”的问题。

## 9.2 数据来源

- 高频提问
- 点踩记录
- 无命中知识库记录
- 多次外部搜索记录

## 9.3 输出

面向管理员的 Gap Report：

- 高频问题簇
- 影响部门 / Agent
- 缺失知识类型
- 建议补充文档

---

## 10. 权限与隐私

## 10.1 用户偏好

默认仅当前 Agent 可见，除非用户授权升级为组织级画像片段。

## 10.2 组织共享记忆

仅管理员或具备授权的流程可发布到 tenant scope。

## 10.3 敏感信息

必须增加敏感信息检测，避免将：

- 密码
- token
- 身份证号
- 银行卡号
- 医疗隐私

写入长期记忆。

---

## 11. API 建议

### 11.1 记忆

- `GET /api/agents/{agent_id}/memory`
- `POST /api/agents/{agent_id}/memory/search`
- `POST /api/agents/{agent_id}/memory/rebuild`

### 11.2 反馈

- `POST /api/messages/{message_id}/feedback`
- `GET /api/agents/{agent_id}/feedback`

### 11.3 黄金题库

- `GET /api/enterprise/golden-examples`
- `POST /api/enterprise/golden-examples/{id}/review`

### 11.4 缺口分析

- `GET /api/enterprise/knowledge-gaps`

---

## 12. 前端设计

## 12.1 AgentDetail

新增或增强：

- Mind / Memory 页
- 记忆搜索
- 记忆来源标记
- 手动置顶 / 删除记忆

## 12.2 Chat 页面

新增：

- 点赞 / 点踩
- 错误反馈弹窗
- “此回答引用了历史纠错/知识”标记

## 12.3 EnterpriseSettings

新增：

- 黄金题库管理
- 知识缺口报表
- 共享画像授权策略

---

## 13. 分阶段开发

### Phase 1

- pgvector 接入
- MemoryDocument / MemoryChunk
- 基础写入与搜索
- Agent 级长期记忆召回

### Phase 2

- 用户偏好抽取
- 点赞 / 点踩
- 纠正答案入库
- 黄金题库审核

### Phase 3

- 知识缺口聚类
- 组织画像片段
- 自动摘要与记忆压缩

---

## 14. 验收标准

- Agent 可在跨会话中记住用户偏好
- 对话前可召回长期记忆与企业知识
- 用户可对回答进行点赞 / 点踩
- 点踩后可以提交纠正答案
- 相似问题能优先命中黄金题库
- 管理员可查看知识缺口报表

---

## 15. 风险

- 记忆写入过多导致噪音积累
- 错误记忆进入长期库后污染回答
- 租户隔离不严会引发数据泄露
- 检索链条过长导致响应变慢

建议首版先把“写入门槛、审核机制、可追溯来源”做好，再追求更强的自动学习能力。
