# 故障排查

公开反馈只提供版本、脱敏错误与虚构复现。不上传数据库、凭据、真实会话或未经脱敏的截图。

## 找不到 Python

安装 Python 3.9+。Homebrew 的标准路径通常可自动发现。特殊安装可先退出应用，再直接运行可执行文件：

```sh
CODEX_TODO_PYTHON="/path/to/python3" /Applications/coindex.app/Contents/MacOS/coindex
```

替换占位路径。Finder / Dock 通常不继承终端环境，仅 `export` 不代表以后双击也有效。

## CLI 不存在或过旧

检查 `codex --version`、`codex exec --help` 与 `codex login status`。CLI 需支持 README 中四个必需选项。设置了错误路径时不会默默改用其他版本；重新选择或清空该字段再检查。

## 没有会话

数据目录应对应创建会话时的 `CODEX_HOME`，包含可读的 `sessions`；确认来源启用、至少一个会话、未归档或手动结束。历史回填可能需多轮，查看剩余数量和错误，不要清空数据库重新开始。

## 分析失败

登录检查不测试模型权限。检查模型名称、推理强度、配额与模型服务网络，再手动更新。失败不会自动降级或换模型。

## SSH 后台失败

先在终端核对指纹、解锁 ssh-agent，再运行 `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes dev-server true`。后台不接受密码、不自动确认指纹。指纹变化先核实，不能关闭校验掩盖问题。

远程 Python 需 3.8+；非交互 shell 不一定加载虚拟环境和 `CODEX_HOME`，可填写完整路径。确认 SSH 用户有读取权限，不要把会话目录设为公开可读。

## 催办失败或回执不明

本机打开 Codex，数据目录保持一致。远程需已有共享服务与支持 `app-server proxy` 的 CLI，主机 ID 需与桌面一致。接口随 Codex 版本变化，尤其本机私有 IPC，可能需要更新适配。

回执不明时先打开原对话查看消息；确认未送达后才重试，避免重复发起任务。

## 自动检测未运行

检查自动开关、首次连接、下班暂停、工作日限制、北京时间检测时段和年度节假日数据。应用退出或休眠时不更新。

## 数据与诊断

数据位于 `~/Library/Application Support/CodexTodo/`，迁移前退出并备份，不编辑运行中的 SQLite 文件。开发者可在独立目录只采集、不调用模型：

```sh
python3 backend/service.py --data-dir build/check-state sync --collect-only
```

该命令仍会读取真实会话并保存，目录与输出都应视为敏感信息。公开演示使用 `--demo`。
