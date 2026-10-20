# Bili Research

Bili Research 是供 Agent 调用的 B 站连续阅读 Skill：按用户指定数量获取知识视频和评论，以模拟用户视角逐条写日记，再用累计经历完成调研或内容评价。

当前交付为 `skills/bili-research/`，不依赖 DeepSeek Harness。目标使用者是拥有本地命令、文件访问能力的 Agent；调用示例是“以刚入职的产品经理视角，看 10 个相关知识视频和评论，再评价我的应用内容与封面”。

## 安装

公开仓库：[CosimoDi/bili-research](https://github.com/CosimoDi/bili-research)。

在 Codex 中可直接说：

> 使用 skill-installer，从 CosimoDi/bili-research 安装 skills/bili-research。

也可以克隆后安装到本机 Skill 目录：

```bash
git clone --depth 1 https://github.com/CosimoDi/bili-research.git
cd bili-research
python3 scripts/package_skill.py --install-to ~/.codex/skills/bili-research
```

已存在不同内容的安装目录时，先备份旧目录再安装；安装器不会覆盖。其他 Agent 复制 `skills/bili-research/` 整个目录，并按平台要求注册 `SKILL.md`。在 Codex 中安装后，下一轮对话即可调用 `$bili-research`。账号配置和 Whisper 依赖准备见下文。

## 运行

核心工具使用 Python 3.9+ 标准库。Whisper 在独立 Python 3.11 环境运行，依赖在 `skills/bili-research/scripts/requirements.txt`。模型首次使用下载，不需要新增大模型 API Key。

```bash
python3 skills/bili-research/scripts/bili.py doctor
python3 skills/bili-research/scripts/setup.py
python3 skills/bili-research/scripts/bili.py configure
python3 skills/bili-research/scripts/bili.py doctor --online
```

`configure` 在用户本地终端隐藏输入凭据；不在聊天中粘贴 Cookie。其他 Agent 的准备与调用说明见 [SKILL.md](skills/bili-research/SKILL.md)、[准备运行](skills/bili-research/references/setup.md) 和 [调用协议](skills/bili-research/references/protocol.md)。

## 结构与职责

| 位置 | 职责 |
| --- | --- |
| `skills/bili-research/scripts/bili_core/api.py` | 只读 B 站 API：检索、全部分 P 元信息、字幕、评论样本 |
| `skills/bili-research/scripts/bili_core/media.py` | 字幕优先或 Whisper 优先；完整音频转写，显式按需抽帧 |
| `skills/bili-research/scripts/bili_core/engine.py` | SQLite 事务、交付回执、逐条日记、动态计数、恢复和导出 |
| `skills/bili-research/scripts/bili_core/report.py` | 本地 HTML 日记、原子更新与仅提供报告的本机预览 |
| `skills/bili-research/SKILL.md` | 研究视角、选片判断、日记质量、证据边界与后续任务 |
| `upstream/dsh-bili-whale/` | 上游浅克隆参考，忽略提交 |
| `tests/` | 离线协议与适配器验证 |
| `runtime/` | 本项目验证记录，忽略提交 |

每个任务可指定 1–1000 条视频；一个 BV 的全部分 P 都纳入阅读。只有视频文字、评论样本、此前日记全部交付确认且本条日记通过结构与引用校验，才增加已完成数量。跳过不计数，达到数量后停止准备下一条。

日记仅追加，心情状态承接上一条。旧日记在下一条视频前按顺序完整返回，长材料分页且不截断。程序校验交付与保存状态，无法证明模型已理解内容或实际保留了全部上下文。长期任务受宿主上下文容量约束，当前不自动压缩旧日记。

字幕轨覆盖不足会触发整段音频 Whisper 转写，保留时间轴与缺口提示。默认不看画面；评论默认热评与最新评论共 30 条、最多 3 个线程各 10 条回复，明确标注为样本。图表、动作、纯视觉信息可能缺失，模拟用户反应不代表真实用户。

## 日记网页

创建任务时生成空白日记网页；每完成一条视频和评论并保存日记，程序原子更新同一份 `journal.html`。页面展示累计感悟、心情变化、材料引用、证据范围和后续指令。调用 Agent 用宿主浏览器工具打开报告，后续刷新原标签；用户继续在原会话提出调研、比较或评价任务。

报告使用内置样式，无外部字体、脚本或图片。`report --task ID` 可为旧任务生成或修复网页。生成失败不会撤销已保存日记；打开失败也不会阻止下一条视频。浏览器不支持文件 URL 时，`serve-report --task ID` 启动仅绑定 `127.0.0.1` 的预览进程，只提供该任务报告，默认使用空闲端口。服务运行期间每次刷新读取最新页面，退出后 HTML 仍可离线阅读。

宿主需要可访问本机文件或预览服务的浏览器工具才能自动弹出页面；仅有聊天或远程隔离浏览器的平台需要其自身的文件预览／端口转发。CLI 返回页面位置，调用 Agent 负责通过宿主工具打开与刷新。

## 分发与验证

```bash
python3 -m unittest discover -s tests -v
python3 scripts/package_skill.py
python3 scripts/package_skill.py --install-to ~/.codex/skills/bili-research
```

打包产物 `dist/bili-research.zip` 包含完整 Skill、工具、调用文档与第三方许可，不含凭据、任务数据或依赖环境。安装器核对内容哈希，拒绝覆盖内容不同的已有 Skill。其他平台可复制同一文件夹并注册其入口。

已覆盖的离线验证包括 10 条双分 P 视频、长材料分页、完整旧日记回放、精确数量停止、重复去重、失败回滚、引用校验、心情连续性和账号缺项提示，以及日记网页追加、文本转义、生成失败恢复与预览服务访问范围。测试使用合成材料，不能替代真实 B 站验收。

真实验收步骤：用户本地配置账号 → `doctor --online` → 调用 Skill 看 1 条指定视频 → 验证字幕缺失时整段 Whisper → 再以用户指定主题与数量运行，检查日记、计数与后续评价。当前尚未验证账号接口、真实视频转写或真实研究输出质量。

定时主动运行由宿主自动化能力唤醒 Skill；本项目没有常驻守护进程。仅有聊天能力的平台需要另行部署工具服务。第三方复用范围与 MIT 许可见 [NOTICE.md](skills/bili-research/NOTICE.md)。

## 许可

项目使用 [MIT 许可](LICENSE)。上游署名、固定版本与复用范围见 [第三方许可说明](skills/bili-research/NOTICE.md)。
