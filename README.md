# 小苏 - 公司内部 AI 助手

基于 RAG（检索增强生成）的公司内部 AI 助手。员工可以上传公司文档建立知识库，通过网页或 IM（飞书）向"小苏"提问，小苏基于知识库内容流式作答并给出参考来源；知识库中检索不到答案时，小苏会明确拒答而不编造。

## 功能特性

- 文档知识库：支持 PDF / Word / TXT / Markdown 上传，同名文件重复上传即增量替换
- RAG 问答：混合检索（向量 + BM25）→ RRF 融合 → Cross-Encoder 精排，流式输出 + 参考来源引用
- 多轮对话：上下文记忆，历史对话可管理
- 组织与权限：个人空间 / 组织空间，知识库按组织共享
- Web 管理后台：文档、知识库、对话记录管理（完善中）
- IM 接入：飞书机器人（开发中）
- 工具调用：模型自主决策调用内部工具（开发中）

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic v2（Python ≥ 3.12，uv 管理依赖） |
| 前端 | Vue 3 + Vite + Element Plus + Pinia（pnpm 管理依赖） |
| 检索 | ChromaDB 向量库 + rank-bm25 + Cross-Encoder 重排 |
| LLM | 任意 OpenAI 兼容 API（MiniMax / DeepSeek / SiliconFlow），本地可切 Ollama |
| 中间件 | MySQL 8.0（业务数据）+ Redis（语义缓存 / 限流） |
| 部署 | Docker Compose 一键启动 |

## 快速开始（Docker 一键启动）

```bash
# 1. 克隆项目
git clone https://github.com/2179948316-boop/xiaosu-ai-assistant.git
cd xiaosu-ai-assistant

# 2. 配置环境变量
cp .env.example .env                  # 修改 MYSQL_ROOT_PASSWORD
cp backend/.env.example backend/.env  # 填入 LLM API Key 等

# 3. 一键启动（MySQL + Redis + 后端 + 前端）
docker compose up -d --build

# 4. 访问
# 前端: http://localhost
# 后端 API 文档: http://localhost:8000/docs
```

## 本地开发

依赖 [uv](https://docs.astral.sh/uv/)（Python 包管理）与 [pnpm](https://pnpm.io/)（前端包管理）。

```bash
# 后端（端口 8000）
cd backend
uv venv .venv --python 3.12
uv sync
uv run uvicorn app.main:app --reload

# 前端（端口 5173）
cd frontend
pnpm install
pnpm dev
```

或使用统一脚本：

```bash
./scripts/start.sh        # Docker 模式启动全部服务
./scripts/start.sh dev    # 本地开发模式（uv + pnpm dev）
./scripts/test.sh         # 运行后端测试
```

## 项目结构

```
xiaosu-ai-assistant/
├── backend/            # FastAPI 后端（uv 管理）
│   ├── app/
│   │   ├── routers/    # API 路由（auth/knowledge/documents/chat/organizations）
│   │   ├── services/   # 业务服务（RAG 检索、LLM、缓存、重排）
│   │   ├── models/     # SQLAlchemy 模型
│   │   └── schemas/    # Pydantic 模型
│   └── tests/          # pytest 测试（含 Mock LLM 测试）
├── frontend/           # Vue 3 前端（pnpm 管理）
├── scripts/            # 启动 / 测试 / 部署脚本
├── docker-compose.yml
└── init.sql            # 数据库初始化
```

## 测试

```bash
./scripts/test.sh   # 等价于 cd backend && uv run pytest tests/ -v
```

## 文档

- AI 使用说明见 `AI_USAGE.md`（编写中）

## 许可

本项目仅用于学习与求职作品展示。
