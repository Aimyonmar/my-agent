# my-agent —— 从零手搓的 CLI Agent

> 不用 LangChain / LlamaIndex 等任何框架，只用 `httpx + rich + python-dotenv`，
> 手写 Agent 的全部核心机制：工具调用协议、SSE 流式解析、ReAct 循环、错误回喂。

## 它能做什么

- **多接入一键切换**：智谱 GLM / 本地 Ollama / 任意 OpenAI 兼容服务（DeepSeek 等），改一行 `.env` 即可
- **流式输出**：终端打字机效果，工具调用过程全透明可视化
- **基础三件套工具**：`calculate`（安全计算器）、`read_file` / `write_file` / `list_dir`（工作区内文件操作）、`run_shell`（命令执行）
- **工程化细节**：依赖完全隔离在 `.venv`、离线自检 `--check`、对话中断自动回滚

## 核心原理：Agent Loop

整个项目的心脏是 [agent.py](my_agent/agent.py) 里不到 100 行的循环（ReAct 思想的最小实现）：

```
┌────────────── REPL (repl.py) ──────────────┐
│  展示流式回答 / 工具调用面板，处理斜杠命令      │
└───────────────────┬────────────────────────┘
                    │ 一轮提问
┌────────────── Agent (agent.py) ────────────┐
│  核心循环：请求模型 → 解析 tool_calls →       │
│  执行工具 → 结果回填历史 → 再请求 …           │
└─────────┬─────────────────────┬────────────┘
          │                     │
┌─────────▼─────────┐  ┌────────▼──────────────┐
│ LLMClient (llm.py)│  │ ToolRegistry (tools/) │
│ httpx 流式调用     │  │ calculate / files×3   │
│ OpenAI 兼容协议    │  │ run_shell             │
└───────────────────┘  └───────────────────────┘
```

一轮「帮我看看当前目录有什么」的完整消息流：

```
system     你是 CLI 助手…（含工具使用规则）+ tools 声明
user       帮我看看当前目录有哪些文件
assistant  [tool_calls: list_dir(path=".")]
tool       [file] README.md (2.1KB) …        ← 工具结果回填
assistant  当前目录包含：README.md、requirements.txt …  ← 最终回答
```

关键设计：

| 机制 | 位置 | 说明 |
|---|---|---|
| 工具错误回喂 | `Agent._dispatch` | 工具失败不抛异常，错误文本喂回模型让它自行修正 |
| 历史回滚 | `Agent.rollback` | 中断/调用失败时回滚当轮，保证 messages 序列合法 |
| 流式聚合 | `llm.py::_absorb_chunk` | tool_calls 的 arguments 由多个 SSE chunk 分片拼成 |
| 防注入计算器 | `tools/calc.py` | AST 白名单求值，杜绝 `eval` 注入 |
| 工作区限界 | `tools/files.py` | 所有路径规范化校验，拒绝目录穿越 |

## 快速开始

```powershell
# 1. 创建隔离环境（本项目铁律：依赖绝不进全局）
python -m venv .venv
.venv\Scripts\activate

# 2. 安装依赖（仅 httpx / rich / python-dotenv 三个）
pip install -r requirements.txt

# 3. 配置密钥
copy .env.example .env    # 编辑 .env，填入你的 API Key

# 4. 开玩
python -m my_agent
```

试试这些问题：

```
帮我算一下 (123 * 456) / 7 等于多少
当前目录下都有什么文件？挑一个给我讲讲
把「你好，Agent」写进 hello.txt，然后读出来验证
这个项目现在一共多少行 Python 代码？
```

## 配置说明（.env）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `AGENT_PROVIDER` | 接入方式：`glm` / `ollama` / `openai` | `glm` |
| `GLM_API_KEY` | 智谱 API Key（[控制台](https://open.bigmodel.cn)获取） | 无 |
| `GLM_MODEL` | 模型名 | `glm-4-flash`（免费款，可换 `glm-4.6`） |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 本地 Ollama 地址与模型 | `http://localhost:11434/v1` / `qwen2.5:7b` |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | 任意 OpenAI 兼容服务 | 官方 / `gpt-4o-mini` |
| `AGENT_MAX_ITERATIONS` | 每轮最多「模型-工具」循环次数 | `15` |
| `AGENT_TEMPERATURE` | 采样温度（Agent 场景建议低温，抑制语言漂移） | `0.4` |

切换 DeepSeek 示例：`AGENT_PROVIDER=openai` + `OPENAI_BASE_URL=https://api.deepseek.com/v1` + `OPENAI_MODEL=deepseek-chat`。

## 内置工具

| 工具 | 参数 | 边界 |
|---|---|---|
| `calculate` | `expression` | AST 白名单求值，无 `eval`，指数上限防卡死 |
| `list_dir` | `path?` | 最多 200 项 |
| `read_file` | `path` | 仅文本文件，20K 字符截断 |
| `write_file` | `path, content` | 覆盖写入，50K 字符上限 |
| `run_shell` | `command, timeout?` | 30s 默认超时，8K 输出截断，危险命令黑名单 |

**安全边界（务必阅读）**：文件工具被硬限制在项目根目录内；`run_shell` 的黑名单只是防呆，
**不是沙箱**——它真实拥有你的用户权限，只在自己信任的环境运行本 Agent。

## 项目结构

```
my-agent/
├── .venv/                  # 隔离依赖（铁律：不碰全局）
├── .env.example            # 配置模板
├── requirements.txt        # 仅 3 个依赖
├── NOTES.md                # 学习与观察笔记（第一手认知记录）
├── tests/
│   ├── boundary.md         # Agent 边界测试题集（阶梯 / 安全 / 压力 / 模型对照）
│   └── fixtures/           # 测试固定物料（提示注入样本等）
└── my_agent/
    ├── __main__.py         # 入口：python -m my_agent [--check]
    ├── config.py           # 三种接入的配置加载
    ├── llm.py              # httpx 手写 OpenAI 兼容流式客户端
    ├── agent.py            # 核心循环（ReAct 最小实现）
    ├── repl.py             # CLI 交互与展示
    └── tools/
        ├── base.py         # Tool 抽象 + 注册表
        ├── calc.py         # 安全计算器（AST 白名单）
        ├── files.py        # 文件三件套（工作区限界）
        └── shell.py        # 命令执行（黑名单 + 超时）
```

## 开发与调试

```powershell
python -m my_agent --check    # 离线自检：配置 + 5 个工具行为，不耗 token
```

REPL 内命令：`/help` 帮助 · `/tools` 工具列表 · `/model` 当前配置 · `/history` 查看将发给模型的完整 messages · `/clear` 清空历史 · `/quit` 退出

## 常见问题

**Q：提示「需要 API Key」或「Illegal header value b'Bearer '」**
A：未配置密钥。复制 `.env.example` 为 `.env` 并填入对应服务的 Key；走本地 Ollama 则完全不需要 Key。

**Q：模型把工具调用写成了正文，或调用了不存在的参数**
A：小模型（如 llama3.2:3b）的已知局限。本 Agent 已内置「文本工具调用回收」：识别写成正文的 `{"name":...,"parameters":{...}}` 并还原成规范 tool_calls 重走流程，配合错误回喂让模型自行修正。判断标准是「调用工具」面板是否正常出现。仍频繁翻车就换更强的模型（`ollama pull qwen2.5:7b` 或 GLM）。

**Q：run_shell 里 date、ls 等命令报错**
A：Windows 下 shell 是 cmd，Linux 命令不可用；等价写法是 `echo %date%`、`dir`。

## Roadmap

- [ ] 网页抓取 / 联网搜索工具
- [ ] 长对话历史管理与自动摘要
- [ ] 高危命令人工审批模式（执行前需用户确认）
- [ ] 思考型模型 reasoning_content 展示
- [ ] Web UI（对话流 + 工具调用时间线）
