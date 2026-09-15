# Veyra Agent API

![CI](https://github.com/xiaopeng-126/veyra-agent-api/actions/workflows/ci.yml/badge.svg)

把 Veyra 的 Agent 引擎用 Python 重写一遍：**LangGraph 编排 + FastAPI 接口 + MySQL 存储 + Docker 部署**。

桌面版的 Veyra（`D:\AI Agent\agent-workbench`）验证过产品形态，这个仓库解决的是另一类问题：
怎么把它做成一个能被别的系统调用的服务，以及每一层在工程上应该怎么落地。

## 现在能做什么

- **对话**：`POST /chat` 一次性返回，`POST /chat/stream` 走 SSE 逐字返回
- **Agent 工具调用**：模型自己决定何时调用工具（查时间、算数、检索知识库），循环有步数上限
- **多智能体协作**：Leader 规划分工 → 依赖感知调度并发执行 → 汇总成终稿（`mode: "swarm"`）
- **知识库 RAG**：文档分块入库 → 混合检索（TF-IDF 词法 + 向量）→ 回答带 `[S1]` 来源编号
- **会话与用量落库**：会话、消息、token 用量全部进 MySQL
- **离线可跑**：没有 API Key 时自动降级到 mock 模型，测试与演示都不依赖网络
- **数据库迁移**：Alembic 管理表结构，支持升级与回滚

已实测通过：`38 项 pytest`、本机 MySQL 9.7 端到端冒烟、Alembic 升级/降级往返（含在已有数据的表上加列）、
本机 Ollama（qwen2.5）真实问答并正确引用来源、5 成员 swarm 真实协作（规划 → 并发执行 → 汇总）。

## 快速开始

### 方式一：本地直接跑（用你电脑上的 MySQL 与 Ollama）

```powershell
cd "D:\AI Agent\veyra-agent-api"

# 1. 建虚拟环境与依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 建库（本地 MySQL）
mysql -u root -e "CREATE DATABASE IF NOT EXISTS veyra CHARACTER SET utf8mb4;"

# 3. 配好环境变量（不配也能跑，默认走 mock 模型 + 本机 MySQL）
copy .env.example .env

# 4. 启动
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000/docs> 可以直接在浏览器里调接口。

想接本机 Ollama 的真实模型，把 `.env` 改成：

```env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5
```

### 方式二：Docker 一键起（应用 + MySQL）

```powershell
docker compose up --build
```

宿主机端口用了 `3307`，避免和本地已装的 MySQL 抢 `3306`。

### 冒烟验证

```powershell
# 服务起来后另开一个终端
.\scripts\smoke_mysql.ps1
```

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查，含数据库探活 |
| POST | `/sessions` | 建会话 |
| GET | `/sessions` | 会话列表 |
| GET | `/sessions/{id}` | 会话详情（含消息） |
| DELETE | `/sessions/{id}` | 删除会话（级联删消息） |
| POST | `/kb/documents` | 文档入库（自动分块 + 向量化） |
| GET | `/kb/documents` | 文档列表 |
| DELETE | `/kb/documents/{id}` | 删除文档及其分块 |
| POST | `/kb/search` | 知识库检索，返回 `[S1]` 编号片段 |
| POST | `/chat` | 对话，一次性返回 |
| POST | `/chat/stream` | 对话，SSE 流式返回 |

对话请求可以指定编排方式，不传就沿用会话记住的模式：

```json
{ "message": "帮我制定两周学习计划", "mode": "swarm" }
```

`mode: "single"` 是带工具调用的单智能体；`mode: "swarm"` 是「规划 + 分工 + 汇总」的多智能体。

## 鉴权与限流

除 `/health` 外，所有接口都会校验 `X-API-Key` 请求头：

```powershell
# .env
API_KEYS=你的密钥1,你的密钥2    # 留空表示不校验，仅供本地开发
RATE_LIMIT_PER_MINUTE=120       # 每个 key 每分钟的额度，0 表示不限
```

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "X-API-Key: 你的密钥1" -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

- 没有配置 `API_KEYS` 时接口完全开放，日志里会打一条警告提醒你：这套配置只适合本地
- 超限返回 `429` 并带 `Retry-After`；限流按 key 计数，一个 key 被限不影响其它 key
- 每个 Key 会映射成一个独立租户：会话、知识库和用量都按租户过滤，数据库不保存原始 Key
- 可以按 Key 配置每日 token、费用和模型级 token 额度，超额返回 `429 + Retry-After`
- `/health` 刻意不挂鉴权，否则容器编排没法探活

限流默认是进程内滑动窗口；配 `REDIS_URL` 后自动切到 Redis 有序集合实现，
多实例共享同一份额度。Redis 启动时探测、运行期故障放行并告警。

每个请求会生成或透传 `X-Request-ID`，日志自动带上该 ID 和请求耗时。
模型调用完成后记录 prompt / completion token 与价格快照，用量页按模型和日期聚合。

Prometheus 指标通过 `/metrics` 暴露，包含 HTTP 请求、首 token 延迟、模型耗时、token、
成本、检索耗时与配额拒绝；该端点同样校验 `X-API-Key`。

## 知识库管理

入库是**幂等**的：内容哈希、分块大小、嵌入模型三者都相同，就直接复用已有记录，
返回 `"deduplicated": true`，不会再花一次向量化的钱。

```json
{ "name": "doc.md", "text": "……", "chunk_size": 80 }
```

判断条件里带上分块大小是刻意的：只看内容的话，你把分块从 500 改成 80 再入库，
会被当成重复而静默忽略——那才是真的坑。

删除文档会连同它的全部分块一起删掉（数据库外键 + ORM 级联双保险）：

```bash
curl -X DELETE http://127.0.0.1:8000/kb/documents/<id> -H "X-API-Key: ..."
```

## 架构

```
客户端
  │  HTTP / SSE
  ▼
FastAPI 路由  app/api/routes/
  │  只负责 HTTP：解析入参、拼事件流、返回响应
  ▼
业务编排  app/services/chat.py
  │  会话准备 → 历史拼装 → 知识注入 → 落库
  ├──────────────► 知识库  app/kb/
  │                 分块 → 向量化 → 混合检索 → [S1] 引用
  └──────────────► Agent  app/agent/
                    LangGraph 状态图：agent ⇄ tools，带上限
                      │
                      ▼
                    模型层  app/llm/
                      mock / OpenAI 兼容（DeepSeek、Ollama、任意服务）

存储：SQLAlchemy 2.x ORM → MySQL（会话、消息、文档、分块、用量）
```

### 目录结构

```
app/
  api/routes/     接口层：health / sessions / kb / chat
  services/       业务编排：chat.py
  agent/          LangGraph 图、工具注册表、提示词
  kb/             分块、向量化、检索、知识库编排
  llm/            模型抽象与两种实现（mock / OpenAI 兼容）
  db/             SQLAlchemy 模型与会话工厂
  core/           配置与日志
tests/            16 项测试，全部离线可跑
scripts/          冒烟脚本、检索阈值校准脚本
```

## 几个关键设计（面试也主要问这些）

### 1. 为什么用 LangGraph 状态图，而不是写个 while 循环

工具调用的本质是「思考 → 调工具 → 看结果 → 再思考」。用 `while` 也能写，
但状态藏在局部变量里，加需求就要改循环体：要人工确认怎么办？要并行分支怎么办？
要中途断点续跑怎么办？

这里把它拆成显式的节点和边：`START → agent → (有工具调用?) → tools → agent → … → END`。
每一步状态都是可检查、可序列化的，加节点和边即可扩展（checkpointer 参数已经预留）。
同时 `agent_max_steps` 是硬上限，模型反复要求调工具也不会把服务拖死，这条有测试守着。

### 2. 一套 OpenAI 兼容实现，支撑所有模型后端

DeepSeek、豆包方舟、本地 Ollama 的接口形状几乎一样，写四遍没有意义。
`app/llm/openai_compat.py` 一份实现 + 改 Base URL 就够，配置里换 `LLM_PROVIDER` 即可切换。
云端服务没配 Key 时自动降级成 mock，保证演示和 CI 不因为缺密钥而红。

### 3. 检索：混合打分 + 用实测校准的阈值

只用向量检索，遇到专有名词和短查询容易跑偏；只用关键词，同义改写就召不回。
所以两个都算，加权求和：

- **词法**：中文按「单字 + 二元组」切分（不需要外部分词词典），用 **IDF** 给词加权，
  再按「查询词的权重总和」归一化
- **向量**：余弦相似度，权重可配（默认 0.6 / 0.4）

两个容易踩的坑在这里被显式处理掉了：

1. **按候选最高分归一化是错的**。那样最弱的一次命中也会被放大成满分，
   结果是「问什么都能召回点什么」。这里分母用查询词权重总和，弱命中就是低分。
2. **两道门槛是「或」不是「与」**。词法覆盖率不达标，但向量相似度足够高时也要放行——
   否则「对话记录存在哪里」这种和原文用词完全不同的问法会被纯词法门槛挡掉，
   白瞎了语义嵌入。反过来两个都不过，才判定无关。

阈值不靠拍脑袋：`scripts/evaluate_retrieval.py --sweep` 会在带标注的数据集上跑 100+ 种阈值组合，
把「召回、MRR、误召回」三项一起打出来。当前默认值（`min_score=0.25 / min_coverage=0.25 /
min_vector=0.55`）就是这么选出来的。

### 4. 工具执行失败不能掀翻整轮对话

模型给错参数、工具内部抛异常，都属于「正常会发生」的情况。
`ToolRegistry.run()` 把异常统一兜成文本 observation 交回模型，让它自己纠错，
只有未知工具和参数不匹配会明确告诉模型可用工具列表。
数学工具用 `ast` 解析而不是 `eval`，避免表达式注入。

### 5. 流式接口里的数据库会话生命周期

SSE 是在接口函数返回**之后**才慢慢写出去的，那时 FastAPI 依赖注入的会话可能已经关闭。
所以流式路径只在准备阶段用请求会话读数据，等流结束后**另开一个短会话**写回答和用量
（`app/api/routes/chat.py` 的 `_persist`）。这是很多人写流式接口时会踩的坑。

### 6. MySQL 的 DATETIME 精度坑（真机踩到并修掉）

MySQL 的 `DATETIME` 默认精确到秒，同一秒内写入的「用户消息」和「回答」排序会错乱，
接口返回的顺序变成 `assistant → user`。解决办法是用 `DATETIME(6)`：

```python
Timestamp = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
```

这个 bug 是冒烟脚本打出来的，SQLite 上跑测试永远发现不了——越早接真数据库越好。

### 7. 多智能体：模型给的计划不能直接信

swarm 模式下 Leader 先输出 JSON 计划，然后按依赖关系并发执行，最后汇总。这里有三道防线：

1. **计划要校验**：id 唯一、依赖必须存在、不能成环、成员数有上限。
   解析失败就降级成单任务，绝不让坏计划把整轮对话带崩。
   解析分两阶段：先收全部任务再过滤依赖，这样「依赖写在后面」的正常计划不会被误删，
   环检测也才有意义。
2. **并发要限制**：用信号量控制同时在跑的成员数（本地模型并发太高反而更慢，还容易抢显存）。
   每个成员还有超时，避免一个卡住的成员拖死整场。
3. **失败要隔离**：某个成员失败时，依赖它的下游任务标记为「跳过」并说明原因，其余照常汇总；
   汇总提示词里会告诉 Leader 哪些部分没做出来，让它如实交代而不是硬编。

还有个小细节值得记：汇总提示词里「引用时用 [S1]」这句话，**只在真的检索到资料时才加**。
否则模型会凭空编出 `[S2]`、`[S5]` 这种看起来很像引用、实际不存在的编号——这个现象是真实跑
qwen2.5 时发现的，已经有测试守着。

### 8. 异步接口里的同步数据库调用

FastAPI 的 `async def` 路由跑在事件循环里，而 SQLAlchemy 同步驱动是阻塞的。
在 `async def` 里直接 `db.execute(...)`，会把整个事件循环卡住——单机自测完全看不出来，
并发一上来所有请求一起排队。

所以知识库的读写、对话的落库都通过 `run_in_threadpool` 执行（见 `app/kb/service.py`
和 `app/api/routes/chat.py`）。`tests/test_async.py` 用一个 0.3 秒的假慢查询加心跳协程来验证：
如果查询留在事件循环里，心跳计数会掉到个位数，测试会红。

### 9. 换嵌入模型不能静默变差

向量维度对不上时，余弦相似度会直接返回 0——不报错、不警告，检索质量悄悄下降，
日志里什么都看不到。所以在 `documents` 表上记录了入库时的 `embedding_model`、`embedding_dim`
和 `chunk_size`，检索时发现维度不一致就跳过这些分块并打日志：

```
WARNING | 有 3 个分块的向量维度与当前嵌入模型不一致（当前 1024 维），已跳过。
          换过嵌入模型的话，需要重新入库才能用上新模型。
```

**换嵌入模型 = 重建索引**，这是 RAG 系统的基本操作纪律。记录这三个字段还有一个好处：
出问题时能立刻看出「这批数据是多大的块、用哪个模型生成的」。

### 10. 超时与上下文预算

模型卡住是常态（本地模型尤其常见），所以单轮对话有整体超时（`AGENT_TIMEOUT_SECONDS`，默认 120 秒）。
超时不是直接把请求打回 500，而是保留已经生成的部分、附一句说明后正常结束——
用户至少知道自己看到的是半截答案，而不是一个错误页。

上下文裁剪也从「只留最近 20 条」改成了**按 token 预算**（`HISTORY_MAX_TOKENS`，默认 3000）。
按条数裁是不够的：三条长文档和三十条短消息的 token 量差着数量级，前者照样能把上下文撑爆。
裁剪时无论如何都保留最新一条，否则用户刚问的那句话会被丢掉。

## 数据库迁移

开发期 `AUTO_CREATE_TABLES=true` 会自动建表，方便起步；一旦有真实数据，就应该关掉它、只用迁移：

```powershell
# 1. 生成迁移（改完 app/db/models.py 之后）
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add xxx"

# 2. 应用迁移
.\.venv\Scripts\python.exe -m alembic upgrade head

# 3. 回滚一步 / 回到空库
.\.venv\Scripts\python.exe -m alembic downgrade -1
.\.venv\Scripts\python.exe -m alembic downgrade base

# 4. 检查模型和迁移是否一致（CI 里应该跑这一条）
.\.venv\Scripts\python.exe -m alembic check
```

### 已有的库怎么接上迁移

如果数据库是先靠 `create_all` 建出来的（没有 `alembic_version` 表），直接 `upgrade` 会从头建表然后失败。
正确做法是先给现有结构「盖章」，再往上叠新迁移：

```powershell
.\.venv\Scripts\python.exe -m alembic stamp 0420d61f29dd   # 标记到初始迁移版本
.\.venv\Scripts\python.exe -m alembic upgrade head         # 再应用后续迁移
```

两个 MySQL 特有的坑，已经在迁移文件里处理并写了注释：

- **downgrade 不要先 drop_index 再 drop_table**。MySQL 会为外键自动维护索引，
  显式删除时报 `Can't DROP 'xxx'; check that column/key exists`；
  而且 MySQL 的 DDL 不走事务，失败后表只删一半，状态很难收拾。删表本身会连带删掉索引。
- **`alembic.ini` 只能写 ASCII**。Alembic 按系统区域编码（简体中文 Windows 上是 GBK）读这个文件，
  中文注释会直接让命令崩溃。
- **给已有数据的表加 NOT NULL 列必须带 `server_default`**。自动生成的迁移不会加，
  空库上能过、有数据的库上直接失败。`56ebd234259d` 这个迁移就是手工补上默认值的例子。

顺带修掉的一处冗余：`messages.session_id` 上原本同时有单列索引和复合索引
`(session_id, created_at)`，而 MySQL 还会为外键自动建索引。复合索引已经覆盖按会话查询的场景，
单列索引只增加写入成本，所以去掉了。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

覆盖：健康检查、会话增删查、对话落库与用量、SSE 事件流、知识库入库与排序、
无关问题不硬凑引用、工具注册表容错、Agent 调用工具后作答、步数上限兜底、分块边界、
swarm 计划解析（坏 JSON / 环依赖 / 成员上限 / 乱序依赖）、依赖调度与并发上限、
成员失败的下游跳过、swarm 端到端与事件流、会话模式记忆、分块参数与嵌入元信息、
维度不一致时的剔除、鉴权与限流、慢查询不阻塞事件循环、重复入库幂等、删除级联清理、
超时保留半截输出、上下文 token 预算。

测试用临时 SQLite + mock 模型，所以离线、快速（77 项约 13 秒）、不产生任何 API 费用。
CI 里另外会起一个真实的 MySQL 来跑 `alembic upgrade` 和 `alembic check`。

## 检索质量评估

调检索最容易犯的错是「感觉好像准了」。用带标注的数据集把效果量化，改完前后各跑一次：

```powershell
# 基线：hash 嵌入（离线、无语义）
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py

# 真实语义嵌入（本地 Ollama 的 bge-m3，免费）
ollama pull bge-m3
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --embedding openai_compat --model bge-m3 --dim 1024

# 扫描阈值组合，找「召回不掉、误召回最低」的工作点
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --embedding openai_compat --model bge-m3 --dim 1024 --sweep
```

数据集是 8 篇文档（7 篇技术文档 + 1 篇完全无关的菜谱）配 12 个问题，
其中 4 个问题在知识库里**没有答案**，专门用来测「会不会硬凑引用」。

实测结果：

| 嵌入方式 | recall@3 | MRR | 误召回率 |
| --- | --- | --- | --- |
| hash（无语义，离线） | 87.5% | 0.750 | 50% |
| bge-m3（真实语义） | **100%** | **1.000** | **0%** |

结论有两条，比数字本身重要：

1. **嵌入质量比阈值重要得多**。hash 嵌入下我把 100+ 种阈值组合全扫了一遍，
   没有任何一组能同时做到高召回和零误召回——瓶颈是向量本身没有语义，
   继续调阈值只是在两个糟糕的选项里挑一个。
2. **语义嵌入会暴露打分逻辑里的隐藏假设**。换成 bge-m3 后召回一度没涨，
   查下来是「命中覆盖率」这个纯词法门槛先把语义命中的片段过滤掉了；
   改成「覆盖率或向量相似度二选一通过」之后，召回才从 87.5% 跳到 100%。

### 分块比阈值更值得先查

还有一个更典型的坑。接 bge-m3 之后，我拿一篇 146 字、讲了三个主题的文档试检索：
「一次任务里最多能派几个小助手」和「会话记录保存在什么地方」两个问题都召不回，
而无关的「红烧牛肉要炖多久」得分只低一点点，分界线极窄。

打印各分量后发现：这篇文档被切成了**一整块**，工具调用、蜂群并发、数据库三件事被平均进同一个向量，
所以相关片段聊胜于无，无关片段也没被拉开。把同一篇文档按 80 字入库拆成 3 块之后，
**同一套阈值**下三个相关问题全部命中，无关问题依然被拒绝。

所以调检索的建议顺序是：先看分块是否把主题混在一起 → 再看嵌入模型有没有语义 → 最后才动阈值。
入库接口支持按文档指定分块参数：

```json
{ "name": "veyra-agent.md", "text": "……", "chunk_size": 80, "chunk_overlap": 0 }
```

## 下一步可以做的

- [ ] 向量索引：MySQL 9 社区版只有 `VECTOR` 类型，`DISTANCE()` 和向量索引是 HeatWave 才有的功能，
      所以现在是全量算余弦；几万块以内够用，再往上要么换 pgvector / Milvus，要么用 hnswlib 自建索引
- [ ] swarm 成员也能调工具（现在是纯文本产出）、成员级重试
- [ ] 基于 Prometheus 数据做检索命中率和成本看板
