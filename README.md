# AI Light

AI Light 是一个桌面红绿灯小组件，用来显示 AI 编程助手的当前状态。

它会显示 Claude Code、Codex 和 opencode 的会话状态，每个工具独立显示一个灯组：

- 红灯：等待用户处理、权限请求、通知或异常状态。
- 黄灯：AI 正在工作。
- 绿灯：任务已完成。
- 会话结束后，对应灯组会自动消失。

## 功能概览

- 悬浮透明窗口，始终置顶。
- 每个 AI 工具独立显示灯组，带工具标识（CC/CX/OC）。
- 支持 Claude Code hooks。
- 支持 Codex 本地会话文件监听。
- 支持 opencode 自动监听。
- Settings 中可调节窗口透明度。
- Settings 中可切换窗口置顶。
- 支持右键菜单打开 Settings、诊断信息、日志、项目路径等。
- 支持安装/卸载 Claude Code 集成。

## 平台支持

| 平台 | 支持方式 |
| --- | --- |
| Ubuntu/Linux | 原生 Python GTK3 GUI（`src-ubuntu/`），支持 Claude Code hooks、Codex 监听、opencode 监听 |

无需 Rust 工具链或 sudo，仅依赖 `python3-gi`（Ubuntu 自带）。

## 运行

```bash
./scripts/run-ubuntu-gui.sh
# 或
python3 src-ubuntu/ai_light.py
```

## 配置 Claude Code

右键 AI Light 小组件，打开：

```text
Settings -> Install Claude Integration
```

这会把 AI Light hooks 合并到 `~/.claude/settings.json`。

安装后重启 Claude Code 或 VSCode 中的 Claude Code 会话。可以在 Claude Code 中输入 `/hooks` 确认 AI Light hooks 已被加载。

## 配置 Codex

Codex 无需手动安装 hooks，AI Light 会自动监听 `~/.codex/sessions`。

## opencode

opencode 无需安装，AI Light 会自动监听 `~/.local/share/opencode/opencode.db`。

## 常用操作

- 左键红灯/绿灯：确认并关闭/重置。
- 右键 AI 图标：Settings / Diagnostics / Quit。
- 右键灯组：Open / Copy Path / Diagnostics / Settings / Remove。
- 拖拽窗口背景：移动窗口。

## Settings 配置

配置文件位于 `~/.ai_light/config.json`。

Settings 可设置：
- 窗口透明度（滑块，实时生效）
- 窗口置顶（开关，实时生效）
- HTTP 监听地址和端口（需重启生效）
- 安装/卸载 Claude Code 集成

## 项目结构

```
src-ubuntu/
  ai_light.py            # 入口
  config.py              # 配置和运行时路径
  model.py               # Status / Tool / LightState 数据模型
  aggregator.py          # 会话状态聚合
  http_server.py         # HTTP hook 接收服务
  project.py             # 项目标识（git root）
  codex_watcher.py       # Codex 文件监听
  opencode_watcher.py    # opencode DB 监听
  hook_installer.py      # Claude hooks 安装/移除
  ai_light_hook          # Python hook shim
  app_lock.py            # 单实例锁
  logging_util.py        # 日志
  window.py              # 悬浮红绿灯窗口
  settings_window.py     # 设置窗口
  ui.css                 # 样式
  actions.py             # 工具函数

scripts/
  install-ubuntu-hook.sh # Ubuntu hook-only 安装脚本
  run-ubuntu-gui.sh      # 启动脚本
```

## 文档

- [Ubuntu GUI 指南](docs/UBUNTU_GUI.md)
