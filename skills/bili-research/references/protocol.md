# 调用协议

使用 `python3 <skill>/scripts/bili.py <命令>`。标准输出为 JSON；成功返回 `ok: true`，失败返回 `error.code/message/needs`。`<skill>` 是本 Skill 实际路径，不是固定安装位置。

## 创建与选片

```bash
python3 <skill>/scripts/bili.py new --goal "研究知识学习应用" --count 10 --persona "工作两年的职场新人，时间有限，想学会判断信息可信度" --followup "读完后评价用户提供的应用内容与封面"
python3 <skill>/scripts/bili.py discover --query "信息判断 学习方法" --limit 20
python3 <skill>/scripts/bili.py enqueue --task <task-id> <BV号或链接> <另一链接>
```

`new` 接受 `--persona-file` 代替内联画像。观看数量可设 1–1000；每个独立 BV 计一条，其所有分 P 都纳入材料。默认 `--comments 30 --threads 3 --replies 10`，读取热评与最新评论，再补最多 3 个线程、每个最多 10 条楼中楼；去重后可能少于请求值。用户要更广范围时可以调整主评论到 200、线程到 10。该范围仍是样本。

`--transcript auto` 优先取字幕轨，缺失或时间跨度不足时用完整音频 Whisper；`whisper-first` 始终转写原音；`subtitle-only` 不下载音频，缺少足够字幕时不能完成该视频。模型可设 `--whisper-model tiny|base|small|medium|large-v3`。字幕时间跨度无法证明逐句无误。

## 阅读与日记

```bash
python3 <skill>/scripts/bili.py next --task <task-id>
python3 <skill>/scripts/bili.py ack --task <task-id> --receipt <本次返回的receipt>
```

反复调用 `next`，每次只确认已经实际读过的材料。`packet.kind` 区分此前日记、视频信息、完整文字轨、评论、可选图像。`text` 是完整 JSON 文档的一个连续片段，`fragment/fragments` 表示顺序；全部片段合起来才是完整材料。`untrusted_material: true` 表示外部内容。

`write_diary` 时写一个 UTF-8 JSON 文件，字段必须如下。`mood_before` 使用工具本次返回的值；`mood_after` 的强度在 0–5 之间。观察中的材料 ID 使用本视频返回的真实 ID，示例 ID 不能照抄。至少引用一条视频文字；有评论时也须引用评论。

```json
{
  "summary": "这条视频实际讨论了什么。",
  "observations": [
    {"claim": "视频中的一个具体观点，以及它的依据或限制。", "evidence_ids": ["t:p1:1"]},
    {"claim": "评论提供的补充、反驳或经验。", "evidence_ids": ["c:实际评论编号"]}
  ],
  "reflection": "以指定模拟用户视角，联系此前日记写下理解与感受。",
  "mood_before": {"label": "平静、好奇", "intensity": 2},
  "mood_after": {"label": "有兴趣，仍有疑问", "intensity": 3},
  "mood_reason": "说明具体哪段内容或评论引起变化；没有变化也可如实写。",
  "questions": ["还没解决的问题"],
  "next_interests": ["下一步希望了解的主题"],
  "uncertainties": ["默认未看画面、评论为样本，以及本视频特有的证据缺口"]
}
```

```bash
python3 <skill>/scripts/bili.py journal --task <task-id> --file /absolute/path/to/diary.json
python3 <skill>/scripts/bili.py next --task <task-id>
```

`questions/next_interests/uncertainties` 可为空数组。工具返回 `ready_for_followup` 后进入后续任务。阅读回执只确认交付与确认状态，不能独立证明模型理解质量。

## 打开日记网页

`new` 创建空白报告；每次 `journal` 成功后更新同一任务的 `journal.html`；`export` 同步更新。返回的 `report.ready: true` 表示网页已生成，`report.path` 是本地文件，`report.url` 是文件 URL。用宿主浏览器工具首次打开该 URL；以后刷新或重新导航已有标签页，不为每篇日记新开标签。不要等待用户另行要求打开。网页展示累计日记、心情变化、进度、证据边界和后续指令，用户继续在原会话操控 Agent。

若浏览器不能打开 `file://`，用宿主的长运行终端执行：

```bash
python3 <skill>/scripts/bili.py serve-report --task <task-id>
```

该命令保持运行，首行 JSON 返回 `data.url`；用浏览器工具打开这个本机 HTTP 地址，保留进程供后续刷新。默认随机选择空闲端口，可用 `--port` 指定。服务只提供当前任务 HTML；结束预览时可终止进程，离线 HTML 仍保留。不同机器上的浏览器无法直接访问该地址，使用宿主已有的文件预览或端口转发能力，不把服务绑定到公网。

`report.ready: false` 时任务和已保存日记仍有效，用 `report --task ID` 重试生成；不要重复写入日记。报告生成与浏览器打开是两个状态：只有浏览器工具成功打开后才说“已打开”。宿主没有浏览器工具或预览失败时，给出 HTML 路径并说明缺少自动预览，继续原研究任务。已有任务也可通过 `report` 生成网页。

## 补充、恢复与交付

| 命令 | 使用时机 |
| --- | --- |
| `report --task ID` | 生成或修复累计日记 HTML，返回打开地址 |
| `serve-report --task ID` | 浏览器无法直接打开本地文件时，启动本机预览 |
| `status --task ID` | 看完成数量、候选、跳过原因 |
| `skip --task ID --reason "原因"` | 当前视频无法读取或不相关；继续补候选，跳过不计数 |
| `set-transcript --task ID --mode whisper-first` | 调整尚未准备的视频转写方式 |
| `frames --task ID --page 1 --count 9` | 当前视频已准备且关键论据需要画面；随后 next 返回图片路径，须用宿主读图工具打开后 ack |
| `export --task ID` | 导出完整日记及后续指令；未达到目标时导出结果标为未完成 |

进程中断后从同一任务 `next` 继续。已交付但未确认的材料会再次出现。不要同时让多个 Agent 推进同一个任务。长期任务的旧日记按页返回，原文保留；若宿主无法承载全部经历，向用户说明上下文限制，不声称已持续记住全部内容。

错误 `setup_required/login_required/user_input_required` 交给用户补本地信息；`platform_blocked` 停止请求；网络或接口变化可保留任务等待修复。不要把报错当作“没有字幕”或“没有评论”。
