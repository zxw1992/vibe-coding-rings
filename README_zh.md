# Vibe Coding Rings

[English](README.md)

一个本地看板，将你的 AI 编程助手使用情况以三个同心动态圆环的形式呈现——灵感来自苹果健身环。支持 **Claude Code**、**Codex CLI**、**Gemini CLI** 和 **OpenCode**。所有数据被动读取自本地文件，无需任何外部服务或 API Key。支持 macOS、Windows、Linux。

![Dashboard](docs/dashboard.png)

<p align="center">
  <img src="docs/menubar.png" width="320" alt="菜单栏"/>
  &nbsp;&nbsp;
  <img src="docs/detail.png" width="600" alt="每小时详情"/>
</p>

## 三个环

| 环 | 指标 | 颜色 |
|----|------|------|
| ⚡ 消耗 | 今日消耗 Token 数 | 红色 |
| ⏱ 专注 | 今日 AI 活跃会话分钟数 | 绿色 |
| ⚙️ 行动 | 今日工具调用次数 | 蓝色 |

## 功能特性

- 动态圆环看板，显示每日目标完成进度
- **多 Agent 支持** — 在「数据来源」区域切换启用哪些 AI 编程工具（Claude Code、Codex CLI、Gemini CLI、OpenCode）
- 7 日历史迷你圆环——点击任意一天可查看该日期三个指标的每小时详情
- 点击今日任意指标行可查看该指标的每小时细分数据
- macOS 菜单栏应用——无需打开浏览器即可瞥见数据
- 中英文双语界面，随时切换
- 零配置：直接读取本地数据，无 API Key，无遥测

## 环境要求

- Python 3.9+
- 至少安装并使用了一款受支持的 AI 编程工具：Claude Code（`~/.claude/`）、Codex CLI（`~/.codex/`）、Gemini CLI（`~/.gemini/`）或 OpenCode（`~/.opencode/`）
- macOS / Windows / Linux

## 安装

```bash
git clone https://github.com/zxw1992/vibe-coding-rings.git
cd vibe-coding-rings
pip install -r requirements.txt
```

## 使用方式

**Web 看板** — 自动在 `http://localhost:8765` 打开浏览器
```bash
python main.py
```

**系统托盘应用** — 在菜单栏/托盘显示实时数据，同时提供 Web UI（支持 macOS、Windows、Linux）
```bash
python menubar.py
```

**数据检查** — 将今日指标和 7 日历史输出到终端
```bash
python data_collector.py
```

## 配置目标

默认目标：**每日 1M Token / 120 分钟专注 / 50 次工具调用**。

在 Web UI 的「每日目标」面板中拖动滑块或直接输入数值即可修改，变更立即生效（保存至 `config.json`），菜单栏无需重启即实时更新。

## 项目结构

```
config.py              目标配置 + config.json 读写
agent_providers.py     AgentProvider 抽象基类 + 各 Agent 实现
data_collector.py      跨 Agent 聚合指标数据
main.py                FastAPI 服务器 + 自动打开浏览器
menubar.py             系统托盘应用（macOS 用 rumps，Windows/Linux 用 pystray）
static/
  index.html           单页应用（主看板 + 多个详情页）
  style.css            深色主题，苹果健身环配色
  rings.js             所有前端逻辑：圆环、图表、Agent 切换、目标、语言
```

## 数据来源

每个 Agent 读取各自的本地文件——均为只读，数据不会离开设备：

| Agent | 会话文件 | 专注时间来源 |
|-------|---------|------------|
| Claude Code | `~/.claude/projects/**/*.jsonl` | `~/.claude/history.jsonl` |
| Codex CLI | `~/.codex/**/*.jsonl` | `~/.codex/history.jsonl` |
| Gemini CLI | `~/.gemini/**/*.jsonl` | `~/.gemini/history.jsonl` |
| OpenCode | `~/.opencode/**/*.jsonl` | `~/.opencode/history.jsonl` |

所有已启用 Agent 的指标求和后展示。数据目录不存在的 Agent 在 UI 中显示为不可用。可在「数据来源」chip 栏随时开关任意 Agent。

**数据永远不会离开你的设备。**

## 依赖

```
fastapi>=0.100
uvicorn>=0.20
rumps>=0.4.0      # 仅 macOS，托盘模式自动使用
pystray>=0.19     # 仅 Windows/Linux，托盘模式自动使用
pillow>=9.0       # 仅 Windows/Linux（托盘图标渲染）
```

`menubar.py` 在运行时自动判断平台，macOS 使用原生 `rumps`，Windows/Linux 使用 `pystray`。

## 许可证

MIT
