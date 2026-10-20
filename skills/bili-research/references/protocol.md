# 调用协议

使用 `python3 <skill>/scripts/bili.py <命令>`。标准输出为 JSON；成功返回 `ok: true`，失败返回 `error.code/message/needs`。`<skill>` 是本 Skill 实际路径，不是固定安装位置。

## 创建与选片

先创建当前会话的任务或复用本会话已明确的任务 ID。账号缺失或确认失效时，按 [准备运行](setup.md) 使用 `login --task <task-id>` 绑定任务并生成二维码，使用 `login --poll --wait 60` 接收扫码结果。绑定任务的登录在确认后自动验证账号并启动日记预览。`configured` 只表示凭据已保存；`online_verified: true` 才表示账号验证成功。网络或风控错误停止本轮，不循环生成二维码。

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

`write_diary` 时写一个 UTF-8 JSON 文件，字段必须如下。`mood_before` 使用工具本次返回的值；`mood_after` 的强度在 0–5 之间。观察中的材料 ID 使用本视频返回的真实 ID，示例 ID 不能照抄。至少引用一条视频文字；有评论时也须引用评论。新增日记必须包含 `quotes`；旧日记仍可读取和展示，不为旧内容补写未经核对的引文。

```json
{
  "summary": "用一两句话交代视频讨论的主题。",
  "quotes": [
    {
      "text": "从本视频文字材料复制的短摘录，保留原字词和标点。",
      "evidence_ids": ["t:p1:1"],
      "commentary": "以模拟用户口吻，具体点评这句话为什么让我认同、犹豫或改变想法，并联系已知处境或此前经历。"
    },
    {
      "text": "从一条评论中复制的原文短摘录。",
      "evidence_ids": ["c:实际评论编号"],
      "commentary": "这条评论补充、反驳或限制了视频中的哪句话，我因此多想到了什么。"
    }
  ],
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

`quotes` 通常为 2–4 条，程序接受 1–6 条；每条原文最多 160 字，合计最多 480 字。无评论样本时不编造评论摘录。每条点评必须非空，重点写自己的具体理解、质疑与感受。

`text` 必须是所引材料中的连续原文；仅允许空格、换行差异。跨字幕段时按顺序列出同一分 P 的相邻材料 ID，摘录须实际覆盖所列片段。不同评论分成不同摘录；省略中间文字时分成两条，不在 `text` 中自行加省略号。材料 ID 无效、改写原文、混合来源、缺少视频摘录或已有评论却不摘录评论都会被拒绝。

来源类别、字幕或转写标签、分 P 和时间位置由程序从证据生成，模型不填写 `source` 字段。网页把原文与点评放在一起，逐条显示来源；校验只证明摘录匹配已获取文字，不证明转写正确或观点成立。

`questions/next_interests/uncertainties` 可为空数组。工具返回 `ready_for_followup` 后进入后续任务。阅读回执只确认交付与确认状态，不能独立证明模型理解质量。

## 打开日记网页

`new` 创建空白报告；每次 `journal` 成功后更新同一任务的 `journal.html`；`export` 同步更新。页面展示每条视频后的具体感触、心情变化原因、评论带来的补充、未解问题与证据边界。它展示模拟用户反应，不能当作真实用户反馈。

绑定任务的扫码登录在验证通过后自动启动该任务的实时预览，并请求默认浏览器打开。已有登录时使用：

```bash
python3 <skill>/scripts/bili.py open-diary --task <task-id>
```

在 Codex 等有内嵌浏览器的宿主中，登录轮询加 `--no-browser`，或运行 `open-diary --task <task-id> --no-browser`。程序返回本机 HTTP `url`；宿主通过浏览器工具打开或复用同一标签页，确认页面可见后再检索视频。无需尝试 `file://`。`browser_open_requested` 仅表示系统接受打开请求，不能独立证明页面已经可见；`report.ready` 仅表示报告生成成功。

HTTP 页面每 3 秒检查已保存的日记，内容变化时更新，保留页面滚动位置和已展开的证据说明。无需 Agent 每篇手动刷新，不为每篇日记新开标签。离线 HTML 仍可阅读；自动同步需要本机预览服务保持运行。程序按任务复用存活的服务；服务停止后，再次 `open-diary` 会重新启动。

预览只监听 `127.0.0.1`，仅提供该任务的日记页面，不暴露凭据或整个任务目录。宿主无法访问本机服务时，使用已有端口转发或提供离线 HTML 路径并说明预览受限，不把服务绑定到公网。预览失败时保留任务，先解决打开问题，再进入观看。

需要手动管理服务生命周期时，使用前台命令；终止进程即可停止服务：

```bash
python3 <skill>/scripts/bili.py serve-report --task <task-id>
```

`report.ready: false` 时用 `report --task ID` 重试生成，不要重复写入日记。用户继续在原会话中指挥任务。

## 补充、恢复与交付

| 命令 | 使用时机 |
| --- | --- |
| `report --task ID` | 生成或修复累计日记 HTML，返回打开地址 |
| `open-diary --task ID` | 启动或复用当前任务的实时日记预览并请求打开浏览器 |
| `serve-report --task ID` | 前台运行当前任务的本机预览服务 |
| `status --task ID` | 看完成数量、候选、跳过原因 |
| `skip --task ID --reason "原因"` | 当前视频无法读取或不相关；继续补候选，跳过不计数 |
| `set-transcript --task ID --mode whisper-first` | 调整尚未准备的视频转写方式 |
| `frames --task ID --page 1 --count 9` | 当前视频已准备且关键论据需要画面；随后 next 返回图片路径，须用宿主读图工具打开后 ack |
| `export --task ID` | 导出完整日记及后续指令；未达到目标时导出结果标为未完成 |

进程中断后从同一任务 `next` 继续。已交付但未确认的材料会再次出现。不要同时让多个 Agent 推进同一个任务。长期任务的旧日记按页返回，原文保留；若宿主无法承载全部经历，向用户说明上下文限制，不声称已持续记住全部内容。

错误 `setup_required/login_required/user_input_required` 交给用户补本地信息；`platform_blocked` 停止请求；网络或接口变化可保留任务等待修复。不要把报错当作“没有字幕”或“没有评论”。
