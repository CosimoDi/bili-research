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

安装器使用 `uv` 创建 Python 3.11 环境并安装 yt-dlp、faster-whisper，以及本地二维码依赖 qrcode、pypng。没有 uv 时，使用 Python 3.10+ 的 `venv` 在 doctor 返回的 `runtime_home/venv` 建环境，再安装 `scripts/requirements.txt`。Whisper 模型首次转写时下载；默认 `small`，实际速度取决于机器。网络需要镜像时由用户显式设置 `HF_ENDPOINT`，不自动改镜像。

## 扫码登录（默认）

先创建当前会话的任务或复用本会话已明确的任务 ID。Agent 执行登录流程，用户只需用 B 站 App 扫码并在手机端确认。登录会将账号凭据保存在当前电脑，后续任务复用。

```bash
python3 <skill>/scripts/bili.py login --task <当前任务 ID>
```

成功返回 `qr_path` 后，立即用宿主图片能力展示这张本地 PNG。不要把二维码地址发送到第三方制码网站。随后调用：

```bash
python3 <skill>/scripts/bili.py login --poll --wait 60
```

`--poll` 可单独调用；`--wait` 为 0–60 秒，程序按至少 5 秒间隔轮询。单个二维码约 180 秒有效。根据返回值继续：

| 状态 | 下一步 |
| --- | --- |
| `waiting_scan` | 等用户扫码，再调用 `login --poll --wait 60` |
| `waiting_confirmation` | 提醒用户在手机端确认，再轮询 |
| `configured` | 绑定任务时查看 `online_verified` 和 `report`，确认日记已打开后开始观看；未绑定任务时先运行 `doctor --online`，再对当前任务执行 `open-diary` |
| `expired` | 告知二维码过期，用户准备好后重新运行 `login` |
| `cancelled` / `failed` | 当前登录流程已结束；根据失败原因处理 |

网络、风控或响应异常会停止本次登录，不自动生成新二维码。平台验证由用户处理，恢复条件明确后再重试。研究任务和此前凭据在失败时保留。取消当前扫码：

```bash
python3 <skill>/scripts/bili.py login --cancel
```

绑定任务后，`login --poll` 在扫码确认时自动验证账号、启动该任务的日记服务并请求浏览器打开。宿主有内嵌浏览器时使用 `login --poll --wait 60 --no-browser`，然后由宿主打开返回的 `report.url`；先确认页面可见，再继续观看。`login --task` 的任务绑定保留到后续轮询；显式传入不同任务 ID 会被拒绝。

程序通过 B 站登录接口接收 `Set-Cookie`，仅保存本 Skill 使用的凭据字段。标准输出只返回状态和二维码路径；登录完成、过期或失败后清除临时二维码与登录密钥。凭据采用原子写入，Unix 文件权限为 `0600`，目录为 `0700`。不读取用户浏览器配置、钥匙串或其他应用的 Cookie。

扫码协议依据：[B 站 Web 扫码接口资料](https://github.com/ylw1997/bilibili-API/blob/master/login/login_action/QR.md)。该接口可能变化；离线测试通过不能替代真实扫码验证。

## 手动配置（备用）

用户无法使用 B 站 App 扫码时，可选择本地隐藏输入：

```bash
python3 <skill>/scripts/bili.py configure
```

用户在已登录 B 站的浏览器开发者工具中展开 Application → Cookies → B 站域名，复制 `SESSDATA` 到终端；`bili_jct` 和 `buvid3` 可留空。不要把凭据发到聊天中，也不要依靠截图转写凭据。

无交互终端时，用户可将 JSON 凭据保存为本地文件，只提供路径：

```bash
python3 <skill>/scripts/bili.py configure --credentials-file /absolute/path/to/credentials.json
python3 <skill>/scripts/bili.py doctor --online
```

JSON 接受 `SESSDATA` 或 `sessdata`。`configure` 不自动删除原文件；返回 `configured` 仅表示保存成功。浏览器重新登录不会同步更新该文件。没有本地进程和文件访问能力的平台，需要另行部署工具服务，本包尚不提供远程 MCP 服务。

## 数据与宿主

`BILI_RESEARCH_HOME` 可指定独立运行目录；默认 macOS/Linux 为 `~/.local/share/bili-research`，Windows 为 `%LOCALAPPDATA%/bili-research`。凭据、模型缓存、任务库和日记均保存在该目录，便于迁移。

调用方需要执行命令、读写任务文件；抽帧补充还需要 ffmpeg 与宿主读图工具。macOS 可用 `brew install ffmpeg`，其他系统使用自己的包管理器。默认路径无需 ffmpeg 做画面抽取。

迁到其他 Agent 时复制整个 `bili-research/` 文件夹，把它注册到该平台的 Skill 目录，或将 `SKILL.md` 作为工具说明载入。命令路径按实际位置解析。插件没有 DSH SDK 依赖。
