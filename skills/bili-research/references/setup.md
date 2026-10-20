# 准备运行

运行所需条件是本地 Python 3.9+、可访问 B 站的网络、用户授权使用的 B 站账号；Whisper 隔离环境使用 Python 3.10+。核心工具不连接大模型 API，理解与写作由调用它的 Agent 完成。

## 首次检查

把 `<skill>` 替换为此 Skill 的实际目录，Windows 可用 `python` 代替 `python3`。

```bash
python3 <skill>/scripts/bili.py doctor
```

缺少媒体依赖时安装隔离环境：

```bash
python3 <skill>/scripts/setup.py
```

安装器使用 `uv` 创建 Python 3.11 环境并安装 yt-dlp、faster-whisper。没有 uv 时，使用 Python 3.10+ 的 `venv` 在 doctor 返回的 `runtime_home/venv` 建环境，再安装 `scripts/requirements.txt`。Whisper 模型首次转写时下载；默认 `small`，实际速度取决于机器。网络需要镜像时由用户显式设置 `HF_ENDPOINT`，不自动改镜像。

## 用户账号

向用户说明：需要其授权账号的本地 Cookie 才能读取登录可见字幕和评论。让用户自行在 B 站浏览器开发者工具的 Cookies 面板找到 `SESSDATA`，可同时提供 `bili_jct`、`buvid3`。这些值由用户在本地终端隐藏输入：

```bash
python3 <skill>/scripts/bili.py configure
```

无交互终端的平台，请用户把 JSON 凭据保存为本地文件，仅向 Agent 提供文件路径：

```bash
python3 <skill>/scripts/bili.py configure --credentials-file /absolute/path/to/credentials.json
python3 <skill>/scripts/bili.py doctor --online
```

JSON 接受 `SESSDATA` 或 `sessdata`，另两个字段可为空。不要在对话、命令参数或报告里放凭据值。`configure` 不自动删除用户提供的原文件。没有本地进程和文件访问能力的平台，需要另行部署工具服务，本包尚不提供远程 MCP 服务。

## 数据与宿主

`BILI_RESEARCH_HOME` 可指定独立运行目录；默认 macOS/Linux 为 `~/.local/share/bili-research`，Windows 为 `%LOCALAPPDATA%/bili-research`。凭据、模型缓存、任务库和日记均保存在该目录，便于迁移。

调用方需要执行命令、读写任务文件；抽帧补充还需要 ffmpeg 与宿主读图工具。macOS 可用 `brew install ffmpeg`，其他系统使用自己的包管理器。默认路径无需 ffmpeg 做画面抽取。

迁到其他 Agent 时复制整个 `bili-research/` 文件夹，把它注册到该平台的 Skill 目录，或将 `SKILL.md` 作为工具说明载入。命令路径按实际位置解析。插件没有 DSH SDK 依赖。
