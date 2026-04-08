# Vibe Coding Rings

[English](README.md)

一个本地 macOS 看板，将你的 [Claude Code](https://claude.ai/code) 使用情况以三个同心动态圆环的形式呈现——灵感来自苹果健身环。所有数据被动读取自 `~/.claude/`，无需任何外部服务或 API Key。

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
- 7 日历史柱状图
- 点击任意指标行可查看每小时细分数据
- macOS 菜单栏应用——无需打开浏览器即可瞥见数据
- 中英文双语界面，随时切换
- 零配置：直接读取 `~/.claude/`，无 API Key，无遥测

## 环境要求

- macOS（菜单栏模式需要 macOS；纯 Web 看板在任意 Python 环境下可运行）
- Python 3.9+
- 已安装并使用 Claude Code（数据存放于 `~/.claude/`）

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

**macOS 菜单栏应用** — 在系统托盘显示实时数据，同时提供 Web UI
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
config.py          目标配置 + config.json 读写
data_collector.py  所有 ~/.claude/ 数据解析，不依赖服务器
main.py            FastAPI 服务器 + 自动打开浏览器
menubar.py         rumps 菜单栏应用，后台运行 FastAPI
static/
  index.html       单页应用（主看板 + 详情页）
  style.css        深色主题，苹果健身环配色
  rings.js         所有前端逻辑：圆环、图表、目标、语言切换
```

## 数据来源

两个来源，均为本地只读：

- **`~/.claude/projects/**/*.jsonl`** — 每个对话一个文件。每条 assistant 记录包含 Token 用量和工具调用信息，按本地日期的 UTC 时间范围过滤。
- **`~/.claude/history.jsonl`** — 每条用户消息包含 Session ID 和毫秒时间戳，用于计算专注时间：按 Session 分组，相邻消息间隔 >30 分钟则开启新专注块，每块结尾追加 5 分钟缓冲。

**数据永远不会离开你的设备。**

## 依赖

```
fastapi>=0.100
uvicorn>=0.20
rumps>=0.4.0    # 仅菜单栏模式需要（macOS）
```

`rumps` 依赖 `pyobjc`，仅限 macOS。如需跨平台托盘支持，可将 `menubar.py` 替换为 [`pystray`](https://github.com/moses-palmer/pystray)，FastAPI 后台线程模式保持不变。

## 许可证

MIT
