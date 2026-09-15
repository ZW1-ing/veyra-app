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

## 本地模式（不需要 Supabase）

chatbot-ui 原本依赖 Supabase 做认证与存储。不配 Supabase 也能用：

```powershell
cd backend  && .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000   # 先起后端
cd frontend && npm run dev                                                       # 再起前端
```

打开 <http://localhost:3000/local>，直接提问即可。这一页：

- 不需要登录，会话存在浏览器本地（localStorage）
- 左侧是多会话列表：新建、重命名、删除，会话可导出为 Markdown
- 模型可选「Veyra 智能体（带工具）」或「Veyra 蜂群（多智能体）」
- 回答结束后附上知识库来源清单

首页在检测不到 Supabase 配置时会直接引导进本地模式。

![本地模式](docs/local-mode.png)

本地模式自带三个页面（左侧窄导航切换）：

| 页面 | 内容 |
| --- | --- |
| `/local` | 会话：多会话、流式回答、来源引用、导出 Markdown |
| `/local/kb` | 知识库：上传 txt/markdown、查看分块与嵌入模型、删除、检索调试 |
| `/local/settings` | 设置：后端地址、API Key、新会话默认模式、测试连接 |

![知识库管理](docs/knowledge-base.png)

知识库页里的「检索调试」值得一试：输入一个问题就能看到会命中哪些片段、各自得分多少。
它是排查「为什么回答没引用到我的文档」最快的方式——先看检索有没有命中，
再看模型怎么用这些片段；两者分开调，比盯着回答猜有效得多。

其他页面（工作区、文件、助手等）仍然需要 Supabase，缺配置时会在真正用到的那一刻给出提示，
而不是整页白屏。

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
