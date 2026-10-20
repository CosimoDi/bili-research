# 第三方许可与改造来源

本包复用两个 MIT 项目的内容获取与媒体处理思路，并将相关算法改造成独立 Python 工具。原项目完整许可随包保留。

| 来源 | 固定提交 | 使用范围 |
| --- | --- | --- |
| [Alterssss/dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale) | `eecafbcc216ae7a8bd5acf9c542418936bd684eb` | WBI 签名排列、参数编码、字幕选择与视频截图处理参考；见 [许可](licenses/dsh-bili-whale.txt) |
| [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) | `9a3e0e67d82feedf755c763807c806c4d125a245` | 下载音频与 faster-whisper 完整转写流程改造；见 [许可](licenses/dsh-bili-scroll.txt) |
| bilibili-mcp，随上述 scroll 提交内置 | 同上 | 字幕接口与轨道选择参考；见 [许可](licenses/bilibili-mcp.txt) |

新增任务状态机、回执、日记协议与跨宿主命令行接口采用 MIT 许可，见 [LICENSE](LICENSE)。Python 依赖与 ffmpeg 通过用户环境单独安装，不随本包分发二进制；各依赖保留自身许可。
