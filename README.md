# 盛途 Sales Agent - IT培训行业AI智能销售助手

> 基于大语言模型的智能销售对话系统，面向IT培训机构，完成从破冰到报备的全流程销售转化。

## 项目简介

这是一个 **AI智能销售Agent**，通过微信/企业微信与潜在学员对话，自动完成客户筛选、资质判定、异议处理、邀约试听等销售全流程。系统采用"关键节点模板直出 + 非关键节点LLM自主决策"的分层架构，兼顾合规性与对话自然度。

## 核心特性

- **七步邀约SOP**：破冰 → 资质筛查 → 校区匹配 → 费用展示 → 邀约试听 → 报备信息 → 完成
- **双层意图识别**：正则快速匹配 + LLM深度理解，支持20+种意图分类
- **信任门禁机制**：信任分（0-100）控制对话推进，防止过度销售
- **线索评分引擎**：S/A/B/C四级分级，差异化服务策略
- **动态异议处理**：5步法（共情→探因→举证→重构→行动），支持LLM个性化生成
- **合规红线保护**：自动过滤违禁词，防止承诺过度
- **向量记忆系统**：语义检索历史对话，提升上下文理解
- **A/B测试框架**：支持话术实验，数据驱动优化
- **人工协作机制**：高价值用户自动转人工，旁观提醒
- **对话挽回引擎**：智能挽回策略，异步任务调度
- **深度用户画像**：决策风格/经济压力/沟通风格多维分析
- **工具调用能力**：LLM可查询用户信息、检查资格、匹配校区

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Flask API Server                        │
├─────────────────────────────────────────────────────────────┤
│                    agent_core.py (核心调度)                   │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ 意图识别 │ 状态机   │ 信任引擎 │ 线索评分 │  合规检查       │
├──────────┼──────────┼──────────┼──────────┼─────────────────┤
│ LLM决策  │ 异议处理 │ 记忆管理 │ 用户画像 │  护栏系统       │
├──────────┼──────────┼──────────┼──────────┼─────────────────┤
│ 工具调用 │ 挽回引擎 │ A/B测试  │ 人工协作 │  数据分析       │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│              豆包LLM (doubao-1-5-lite-32k)                   │
└─────────────────────────────────────────────────────────────┘
```

## 模块说明

| 模块 | 功能 |
|------|------|
| `app.py` | Flask主服务，API路由、鉴权、限流 |
| `code/agent_core.py` | 核心调度，消息处理主流程，工具调用集成 |
| `code/state_machine.py` | 严格状态机 + 资格判定 + 信任门禁 |
| `code/intent_classifier.py` | 双层意图识别（正则 + LLM），含辱骂检测 |
| `code/trust_engine.py` | 信任计算引擎（每日衰减，门禁控制，防刷机制） |
| `code/lead_scorer.py` | 线索评分引擎（S/A/B/C四级） |
| `code/decision_engine.py` | 决策引擎（动态跳步、异议策略、对话终止） |
| `code/memory_manager.py` | 用户状态持久化（每用户独立JSON） |
| `code/memory_vector.py` | 向量记忆系统（语义检索，用户隔离，原子持久化） |
| `code/user_profiler.py` | 深度用户画像（决策/沟通/经济/情绪） |
| `code/objection_handler.py` | 动态异议处理（5步法 + 画像融合） |
| `code/recovery_engine.py` | 对话挽回引擎（持久化任务，重启恢复） |
| `code/experiment_manager.py` | A/B测试管理 |
| `code/auto_experiment.py` | 自动话术变体生成（含合规检查） |
| `code/human_collaboration.py` | 人工协作机制 |
| `code/compliance_checker.py` | 合规检查（红线词过滤，身份澄清豁免） |
| `code/guardrail.py` | 三层护栏系统（核心/知识/无关） |
| `code/model_router.py` | LLM路由与熔断 |
| `code/content_generator.py` | 内容生成（案例匹配、共情话术） |
| `code/conversation_analytics.py` | 对话分析与埋点 |
| `code/analytics_dashboard.py` | 数据分析仪表盘（转化漏斗） |
| `code/scheduler.py` | 任务调度器 |
| `code/tools.py` | 工具调用模块（用户查询/资格检查/校区匹配） |

## 关键机制

### 信任门禁

```
trust < 30  → 只能在 icebreak/qualify
trust < 50  → 可到 match_campus，不能 show_fee
trust >= 50 → 可以 show_fee/invite
trust >= 70 → 可以 report_info/completed
```

### 线索分级策略

| 等级 | 分数 | 异议处理 | 唤醒间隔 | 车费报销 |
|------|------|----------|----------|----------|
| S级 | ≥80 | LLM个性化 | 12小时 | 有 |
| A级 | ≥60 | LLM标准 | 24小时 | 无 |
| B级 | ≥40 | 模板 | 48小时 | 无 |
| C级 | <40 | 模板 | 72小时 | 无 |

### 合规红线

**绝对禁止**：包就业、100%就业、保就业、贷款、分期贷、助学贷、学历造假、轻松月入

**阶段禁止**：培训、学费、上课、招生、老师、机构、一定、保证

**豁免规则**：异议阶段可提"机构""培训"用于澄清；身份否定句式（"不是培训机构"）不受限

### 安全机制

- **辱骂检测**：识别脏话/辱骂，2次触发人工转接
- **信任防刷**：每日加分上限15分，单动作类型上限10分
- **对话硬上限**：20轮强制终止（报备阶段可延至25轮）
- **LLM熔断**：连续失败3次自动切换模板模式
- **模糊确认降级**："嗯""好的"等短回复不直接推进状态

## API接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查（含LLM/存储状态） |
| `/test/chat` | POST | 流式对话接口（SSE） |
| `/upload/image` | POST | 图片信息提取 |
| `/api/dashboard` | GET | 运营数据看板 |
| `/api/user/<id>/score` | GET | 用户线索分查询 |
| `/api/user/<id>/profile` | GET | 用户深度画像 |
| `/api/experiments` | GET | A/B实验状态 |
| `/api/analytics` | GET | 数据分析仪表盘 |
| `/api/analytics/funnel` | GET | 转化漏斗 |
| `/callback/wechat_work` | POST | 企业微信回调 |

## 快速开始

### 环境要求

- Python 3.10+
- 豆包API Key（或其他LLM服务）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

```bash
# 复制配置模板
cp server_backup/config/config.example.yaml server_backup/config/config.yaml
cp server_backup/.env.example server_backup/.env

# 编辑配置文件，填入实际的API Key和Token
```

### 启动

```bash
# 开发模式
python app.py

# 生产模式
gunicorn -c gunicorn_config.py app:app
```

服务默认运行在 `http://0.0.0.0:8080`

### 测试

```bash
curl -X POST http://localhost:8080/test/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-token" \
  -d '{"user_id": "test_001", "msg": "你好"}'
```

## 项目结构

```
shengtu-Sales-agent/
├── README.md                       # 项目说明
├── LICENSE                         # MIT许可证
├── requirements.txt                # 依赖清单
├── demo.py                         # 交互式演示脚本
├── .gitignore                      # Git忽略规则
└── server_backup/                  # 服务端代码
    ├── app.py                      # Flask主服务
    ├── gunicorn_config.py          # Gunicorn配置
    ├── .env.example                # 环境变量模板
    ├── ai-agent.service            # Systemd服务配置
    ├── config/
    │   ├── config.example.yaml     # 配置文件模板
    │   ├── knowledge_base.yaml     # 知识库/话术库
    │   ├── experiments.yaml        # A/B实验配置
    │   └── ...                     # 其他配置
    ├── code/
    │   ├── __init__.py
    │   ├── agent_core.py           # 核心调度
    │   ├── state_machine.py        # 状态机
    │   ├── intent_classifier.py    # 意图识别
    │   ├── trust_engine.py         # 信任引擎
    │   ├── lead_scorer.py          # 线索评分
    │   ├── decision_engine.py      # 决策引擎
    │   ├── memory_manager.py       # 记忆管理
    │   ├── memory_vector.py        # 向量记忆
    │   ├── user_profiler.py        # 用户画像
    │   ├── objection_handler.py    # 异议处理
    │   ├── recovery_engine.py      # 对话挽回
    │   ├── tools.py                # 工具调用
    │   ├── compliance_checker.py   # 合规检查
    │   ├── guardrail.py            # 护栏系统
    │   └── ...                     # 其他模块
    ├── data/
    │   └── users/                  # 用户数据
    └── file_repo/                  # 文件仓库
```

## 部署

### Systemd服务

```bash
sudo cp ai-agent.service /etc/systemd/system/
sudo systemctl enable ai-agent
sudo systemctl start ai-agent
```

### Docker（待支持）

```bash
docker build -t shengtu-agent .
docker run -p 8080:8080 shengtu-agent
```

## 监控

- 健康检查：`GET /health`
- LLM状态：熔断机制，连续失败3次自动切换模板模式
- 错误告警：企业微信/钉钉推送
- 数据看板：`GET /api/dashboard`

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 联系方式

- 项目维护：深圳龙二07网安天才
- 问题反馈：GitHub Issues
- 开发agent联系：3190569767@qq.com
