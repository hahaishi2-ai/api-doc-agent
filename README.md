# API 接口文档智能查询与测试助手

这是一个用于课程答辩和本地演示的轻量级 Web Agent。它面向 API 文档查询、接口参数解释、代码示例生成和接口测试场景，支持接入 LM Studio、Ollama 等本地模型 API；当本地模型未启动时，也可以通过规则兜底返回结构化结果。

## 项目地址

GitHub 仓库：

```text
https://github.com/hahaishi2-ai/api-doc-agent
```

本地演示地址：

```text
http://127.0.0.1:8765/
```

说明：本地演示地址需要先启动 `server.py`，只能在运行项目的电脑上访问。

## 功能概览

- 自然语言查询接口文档，例如“自习室座位接口需要哪些参数？”
- 根据问题自动匹配本地接口知识库中的相关接口
- 解释请求参数、请求体、响应字段、鉴权方式和错误码
- 生成 `curl`、Python、JavaScript 调用示例
- 提供接口测试台，可在白名单范围内发起 HTTP 请求
- 展示 Agent 工作流追踪，便于答辩时说明处理过程
- 支持 LM Studio / Ollama / OpenAI-compatible 本地模型服务

## 页面效果

运行项目后，浏览器会打开一个三栏工作台页面：

- 左侧：接口知识库和接口筛选
- 中间：智能问答、HTTP 测试台、代码示例
- 右侧：Agent 状态、工作流追踪、引用接口

## 技术栈

- 后端：Python 标准库 `http.server`
- 前端：HTML、CSS、JavaScript
- 知识库：本地 JSON 文件
- 模型接口：LM Studio / Ollama / OpenAI-compatible API
- 部署方式：本地运行，无需额外后端框架

## 目录结构

```text
api-doc-agent/
├── server.py              # 后端服务、Agent 工作流、本地模型调用、接口测试
├── config.json            # 本地模型和安全白名单配置
├── README.md              # 项目说明
├── data/
│   └── api_docs.json      # API 文档知识库
├── static/
│   ├── index.html         # 前端页面结构
│   ├── style.css          # UI 样式
│   └── app.js             # 前端交互和接口调用
├── docs/
│   └── workflow.png       # Agent 工作流图
└── screenshots/
    ├── agent-home.png     # 桌面端截图
    └── agent-mobile.png   # 移动端截图
```

## 快速开始

### 1. 准备环境

需要安装 Python 3.10 或更高版本。

检查 Python：

```bash
python3 --version
```

### 2. 启动服务

进入项目目录：

```bash
cd api-doc-agent
```

启动 Web 服务：

```bash
python3 server.py --host 127.0.0.1 --port 8765
```

### 3. 打开页面

浏览器访问：

```text
http://127.0.0.1:8765/
```

如果终端提示 `Address already in use`，说明端口已经被占用，可以换一个端口：

```bash
python3 server.py --host 127.0.0.1 --port 8766
```

然后访问：

```text
http://127.0.0.1:8766/
```

## 接入 LM Studio

项目默认已经按 LM Studio 的 OpenAI-compatible 接口方式配置。

打开 `config.json`：

```json
{
  "llm": {
    "provider": "openai_compat",
    "disable_llm": false,
    "timeout_seconds": 20,
    "openai_compat": {
      "base_url": "http://127.0.0.1:1234/v1",
      "model": "local-model",
      "api_key": "lm-studio"
    }
  }
}
```

LM Studio 操作步骤：

1. 打开 LM Studio。
2. 加载一个本地模型。
3. 进入 `Developer` 页面。
4. 点击 `Start Server`。
5. 确认服务地址是 `http://127.0.0.1:1234/v1`。
6. 将 LM Studio 中显示的模型 ID 填入 `config.json` 的 `llm.openai_compat.model`。
7. 重启本项目服务。

## 接入 Ollama

如果使用 Ollama，将 `config.json` 中的 `provider` 改为 `ollama`：

```json
{
  "llm": {
    "provider": "ollama",
    "ollama": {
      "base_url": "http://127.0.0.1:11434",
      "model": "qwen2.5:7b-instruct"
    }
  }
}
```

也可以通过环境变量临时覆盖：

```bash
AGENT_PROVIDER=ollama \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_MODEL=qwen2.5:7b-instruct \
python3 server.py --host 127.0.0.1 --port 8765
```

## 常用演示问题

可以在页面输入以下问题进行演示：

```text
失物招领智能匹配接口怎么测试？
```

```text
自习室座位接口需要哪些参数？
```

```text
帮我生成查询快递接口的 curl 示例
```

```text
反馈接口的请求体字段和错误码是什么？
```

```text
创建自习室预约接口最近有哪些版本变更？
```

## 后端接口说明

项目启动后，前端会调用以下本地接口：

| 接口 | 方法 | 作用 |
| --- | --- | --- |
| `/api/docs` | GET | 获取接口知识库 |
| `/api/health` | GET | 查看模型配置和服务状态 |
| `/api/search` | POST | 根据关键词检索接口 |
| `/api/chat` | POST | Agent 智能问答 |
| `/api/code` | POST | 生成接口调用代码 |
| `/api/test` | POST | 运行受限接口测试 |

## 工作流说明

Agent 的核心处理流程：

1. 输入解析：接收用户自然语言问题。
2. 意图识别：判断问题属于文档查询、参数解释、代码生成、接口测试还是版本变更。
3. 知识库召回：从 `data/api_docs.json` 中检索相关接口。
4. 提示词构造：将用户问题、意图和接口上下文组装为模型输入。
5. 模型生成：调用 LM Studio、Ollama 或其他 OpenAI-compatible 本地模型。
6. 规则兜底：如果模型不可用，则基于检索结果生成结构化回答。
7. 前端展示：显示回答内容、引用接口和工作流追踪。

## 安全边界

接口测试功能默认只允许访问以下本机地址：

- `localhost`
- `127.0.0.1`
- `::1`

如果确实需要测试其他内网地址，可以修改 `config.json`：

```json
{
  "security": {
    "allowed_test_hosts": ["localhost", "127.0.0.1", "::1"]
  }
}
```

不要随意开放公网地址，避免对外部服务发起未授权请求。

## 常见问题

### 页面打不开怎么办？

确认终端里已经启动服务：

```bash
python3 server.py --host 127.0.0.1 --port 8765
```

然后访问：

```text
http://127.0.0.1:8765/
```

### LM Studio 没启动还能演示吗？

可以。模型不可用时，系统会使用规则兜底，根据本地接口知识库返回结构化回答。

### 可以直接双击 `index.html` 吗？

不建议。正确方式是运行 `server.py`，然后通过浏览器访问本地服务地址。因为页面需要调用后端 API。

## 参考开源项目思路

本项目没有复制以下项目源码，只借鉴了它们的设计思路：

- `ollama/ollama`：本地模型服务和 `/api/chat` 调用方式
- `open-webui/open-webui`：本地模型 Web 对话界面思路
- `langchain-ai/langgraph`：按节点组织 Agent 工作流的思想

## 许可说明

本项目用于课程学习和答辩展示，可在保留说明的前提下继续修改和扩展。
