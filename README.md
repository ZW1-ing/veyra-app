# Veyra

一个 AI 应用的全栈实现：**前端用 chatbot-ui，后端用 Python**。

```
veyra/
├── frontend/   Next.js 聊天界面（基于开源项目 chatbot-ui 改造）
└── backend/    FastAPI + LangGraph + MySQL：模型接入、知识库检索、Agent 编排
```

## 这是什么

前端负责界面：会话列表、消息流式渲染、Markdown、模型切换。
后端负责能力：多模型接入（OpenAI 兼容 / 本地 Ollama）、知识库 RAG、工具调用、多智能体协作、
会话与用量落库。两边通过 HTTP + SSE 通信。

## 快速开始

### 1. 后端（先起，前端要连它）

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 建库（本地 MySQL）
mysql -u root -e "CREATE DATABASE IF NOT EXISTS veyra CHARACTER SET utf8mb4;"
copy .env.example .env

# 应用数据库迁移并启动
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000/docs> 可以直接调接口。

默认用离线 mock 模型，不需要任何密钥就能跑通。接本机 Ollama 的真实模型与中文嵌入：

```env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5
EMBEDDING_PROVIDER=openai_compat
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024
```

部署到服务器时记得配上 `API_KEYS`：留空等于不校验，任何人能连上端口就能用。

### 2. 前端

```powershell
cd frontend
npm install
copy .env.local.example .env.local   # 至少填 VEYRA_API_URL；用 Supabase 的功能需要另外配
npm run dev
```

打开 <http://localhost:3000>。

模型列表里的 **Veyra 智能体** / **Veyra 蜂群** 这两档就是走本仓库的 Python 后端：
前端把请求发给 `/api/chat/veyra`，该路由再转发给后端的 `/chat/stream`，
并把后端的 SSE 事件翻译成前端能直接显示的文本流（末尾附上 `[S1]` 来源）。

```
浏览器 → frontend/app/api/chat/veyra/route.ts → backend POST /chat/stream
                                                    ├─ 知识库混合检索（MySQL）
                                                    ├─ 单智能体工具循环 / 多智能体协作
                                                    └─ SSE 流式返回
```

两个细节值得留意：

- 该路由用 **Node runtime**，不是 edge —— 后端跑在本机 `127.0.0.1`，edge runtime 连不上宿主机。
- 前端会话会映射成后端会话 id（取首条消息 id 的 sha256 前 32 位）：后端会话 id 列是 32 位，
  而前端消息 id 是 36 位 uuid，直接传会被 MySQL 拒绝；用首条消息做种子是为了让同一个会话每轮都落到同一个后端会话，历史才能接上。

后端没启动时，接口会返回明确提示（告诉你去 `backend/` 里起服务），而不是一句「服务器错误」。

## 测试

```powershell
# 后端
cd backend
.\.venv\Scripts\python.exe -m pytest -q      # 45 项，离线可跑
.\.venv\Scripts\ruff.exe check app tests scripts
.\.venv\Scripts\python.exe -m alembic check   # 模型与迁移是否一致

# 前端
cd frontend
npm run type-check
npm run lint
```

CI（`.github/workflows/ci.yml`）会在每次推送时跑这些检查：后端会真起一个 MySQL 服务容器来验证迁移，
前端跑类型检查与 lint。

## 目录说明

| 路径 | 内容 |
| --- | --- |
| `backend/app/api/` | FastAPI 路由：health / sessions / kb / chat |
| `backend/app/agent/` | LangGraph 编排：单智能体工具循环、多智能体协作 |
| `backend/app/kb/` | 分块、向量化、混合检索 |
| `backend/app/llm/` | 模型抽象（mock / OpenAI 兼容） |
| `backend/migrations/` | Alembic 迁移 |
| `frontend/app/` | Next.js 页面与 API 路由 |
| `frontend/components/` | 聊天界面组件 |
| `frontend/lib/` | 前端工具与数据访问 |
