<div align="center">
  <img src="Resources/Brand/AppIcon.png" width="104" alt="coindex icon" />
  <h1>coindex</h1>
  <p><strong>把 Codex 对话，变成下一步。</strong></p>
  <p>A native macOS task workspace for local and SSH Codex conversations.</p>
  <p>
    <a href="https://github.com/Junming-Liang/coindex/releases/latest"><img src="https://img.shields.io/github/v/release/Junming-Liang/coindex" alt="Latest release" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" /></a>
    <img src="https://img.shields.io/badge/macOS-14%2B-black.svg" alt="macOS 14 or later" />
    <img src="https://img.shields.io/badge/architecture-arm64%20%7C%20x86__64-blue.svg" alt="Apple Silicon and Intel" />
  </p>
  <p><a href="https://github.com/Junming-Liang/coindex/releases/tag/v1.9.0">下载 1.9.0</a> · <a href="#快速开始">快速开始</a> · <a href="docs/user-guide.md">使用指南</a> · <a href="https://github.com/Junming-Liang/coindex/issues">反馈问题</a></p>
</div>

coindex 是一个原生 macOS 待办应用。它读取你选择的本机和 SSH 机器上的 Codex 对话，整理整体目标、当前进度和下一步，让进行中的工作、等待的结果和需要你决定的事项都能被继续跟踪。每条待办可以查看原文依据，并跳回原来的 Codex 对话。

项目使用你自己的 Codex 登录和 SSH 配置。新安装只包含本机来源；添加远程机器后，才会读取对应机器上的会话。

> **1.9.0：** 支持 Apple Silicon / Intel 通用应用包。需要 macOS 14+、本机 Python 3.9+ 和已登录的兼容 Codex CLI。应用采用 ad hoc 签名，**尚未经过 Developer ID 签名与 Apple 公证**。

## 目录

- [功能](#功能)
- [安装](#安装)
- [快速开始](#快速开始)
- [配置 Codex](#配置-codex)
- [配置 SSH](#配置-ssh)
- [数据与隐私](#数据与隐私)
- [常见问题](#常见问题)
- [从源码构建](#从源码构建)
- [项目结构](#项目结构)
- [参与贡献](#参与贡献)
- [许可证与致谢](#许可证与致谢)

## 功能

| 能力 | 说明 |
| --- | --- |
| 多来源整理 | 本机 Codex + 用户添加的 SSH 机器；自动发现新增会话 |
| 目标与进度 | 区分进行中、继续推进、结果校对、等待结果、需要决定 |
| 原文依据 | 查看依据、来源对话、最后活动与建议下一步 |
| 手动控制 | 新建待办、固定标题、完成、忽略、稍后处理、结束对话跟踪 |
| 一键催办 | 用户主动点击后，把下一步发回原对话；回执不明时不自动重发 |
| 自动检测 | 增量读取、可暂停、下班暂停、检测间隔和时段 |
| 原生体验 | 浅色 / 深色主题、菜单栏、快捷键、按钮悬停反馈、可选桌面小猫 |

自动检测依据已有对话记录生成待办。外部 CI、训练或发布的真实结果，需要在原任务中进一步验收；coindex 不会因“已提交”就认定工作完成。详细规则见[使用指南](docs/user-guide.md)。

## 安装

### 系统要求

| 组件 | 要求 |
| --- | --- |
| Mac | macOS 14+；Apple Silicon 或 Intel |
| 本机 Python | Python 3.9+；后端只使用 Python 标准库 |
| 本机 Codex | 已登录；CLI 支持 `--ephemeral`、`--ignore-user-config`、`--ignore-rules`、`--output-schema` |
| 模型访问 | 账号可以访问设置中选择的模型与推理强度 |
| SSH 机器（可选） | Python 3.8+、可读的 Codex 会话目录、免交互 SSH 登录 |

### 下载应用

1. 打开 [Releases](https://github.com/Junming-Liang/coindex/releases/tag/v1.9.0)，下载 `coindex-1.9.0-macos-universal.zip`。
2. 解压，把 `coindex.app` 拖到 `/Applications` 或 `~/Applications`。
3. 安装 Python。已有 Python 3.9+ 可以直接使用；如果使用 [Homebrew](https://brew.sh/)，运行：

   ```sh
   brew install python
   python3 --version
   ```

4. 打开 coindex，按首次连接引导配置 Codex。

应用会查找 `/opt/homebrew/bin/python3`、`/usr/local/bin/python3` 和 `/usr/bin/python3`；Finder 启动的应用通常不会继承终端环境变量。其他 Python 位置的启动方法见[故障排查](docs/troubleshooting.md#找不到-python)。

此版本尚未公证，macOS 可能阻止首次打开。确认下载来自本项目 Release 后，先尝试打开应用，再到「系统设置 → 隐私与安全性」按系统提示选择「仍要打开」。详见 [Apple 的安全打开应用说明](https://support.apple.com/en-us/102445)。若系统提示恶意软件或应用损坏，请停止打开并核对文件。

### 校验下载

同时下载 `coindex-1.9.0-SHA256SUMS.txt`，在下载目录运行：

```sh
shasum -a 256 coindex-1.9.0-macos-universal.zip
```

结果应与校验文件中同名条目一致。校验值用于检查下载完整性，不代替 Developer ID 签名或 Apple 公证。

### 更新与卸载

更新前退出 coindex，用新应用替换旧应用，保留原数据目录。公开版使用 `org.coindex.desktop` 标识；从早期个人构建迁移后，需要重新检查「登录 Mac 时启动」。待办与宠物偏好仍使用相同数据目录。

卸载时退出并移除 `coindex.app`。个人数据不会随应用移除而删除；如需清除，请先备份下方的数据目录，再自行移除。

## 快速开始

1. 安装并登录 Codex，在 Codex 中创建至少一个会话。
2. 打开 coindex，首次启动自动进入「设置」。
3. 点击「保存并检查连接」，分别确认 CLI、登录与会话目录状态。
4. 选择「立即更新」。首次扫描逐批整理历史会话，可以随时中止。
5. 需要远程会话时，使用「添加 SSH 机器…」。

首次本机连接检查通过后，自动整理才会启用。检查本身不调用模型、不发送催办；实际分析使用你的 Codex 配额或对应计费方式。默认分析设置是 `gpt-6-luna` / `max`，可改为账号可用的模型与推理强度。

默认每 30 分钟检查变化，启用中国大陆法定工作日规则，按北京时间计算。其他地区可关闭「只在法定工作日检测」。更多规则见[使用指南](docs/user-guide.md#自动检测与下班)。

## 配置 Codex

### 安装与登录

已有 Codex / ChatGPT 桌面应用可在 coindex 中直接选择该应用。也可按 [OpenAI 官方 CLI 安装指南](https://learn.chatgpt.com/docs/codex/cli)安装独立 CLI。当前官方 macOS 安装入口为：

```sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
codex login
codex login status
```

登录通过 Codex 官方流程完成。**不要向 coindex、Issue 或聊天粘贴 `auth.json`、访问令牌或账号密码。**

### 应用内连接

| 设置 | 默认行为 | 何时填写 |
| --- | --- | --- |
| Codex 应用 | 使用系统 `codex://` 关联打开对话 | 自定义位置、多个桌面应用或应用改名 |
| 会话与登录目录 | `CODEX_HOME`，否则 `~/.codex` | 使用独立数据目录 |
| Codex CLI | 自动发现 PATH、常见位置与所选应用内的 CLI | 自动发现失败或需要特定版本 |
| 模型 / 推理强度 | `gpt-6-luna` / `max` | 账号权限不同或调整分析开销 |

手动 CLI 路径优先于应用内部的 CLI。读取、分析登录和本机桌面连接使用同一 Codex 数据目录。自定义目录也要以相同的 `CODEX_HOME` 登录：

```sh
CODEX_HOME="$HOME/.codex-work" codex login
```

随后在设置填写 `~/.codex-work`。连接结果分别显示 CLI、登录、会话读取、桌面连接。桌面连接用于催办；暂未就绪时，会话整理仍可使用。登录成功不代表所有模型都可用。

coindex 使用临时、只读、结构化的 `codex exec` 分析，隔离用户配置并禁用分析工具。参数见 [Codex CLI 参考](https://learn.chatgpt.com/docs/cli/reference)。旧 CLI 不支持所需选项时，请升级或选择更新的应用内置 CLI。

## 配置 SSH

SSH 用于读取远程会话，模型分析仍在 Mac 上通过本机 Codex 登录运行。远程采集不要求安装 coindex，也不安装常驻服务。

### 已有 SSH 别名

若已经可以运行 `ssh dev-server`，点击「添加 SSH 机器…」并选择该别名。应用发现 `~/.ssh/config` 及 `Include` 文件中的具体别名，实际连接由系统 OpenSSH 处理，可沿用跳板机等配置。

以下为**占位示例**，请替换为自己的主机与用户名：

```sshconfig
Host dev-server
    HostName server.example.com
    User developer
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

### 在应用中添加新机器

1. 点击「添加 SSH 机器… → 新机器」，填写连接名称、显示名称、地址与用户。
2. 按需填写端口、密钥路径、远程 Codex 数据目录或 Python 路径。
3. 点击「在终端连接」，从可信渠道核对主机指纹，完成首次连接和密钥登录。
4. 点击「测试 SSH 与会话读取」，成功后保存并启用，下一次更新开始采集。

新机器设置只保存在 coindex，不改写 `~/.ssh/config`。首次终端连接会按 OpenSSH 正常行为保存你确认过的主机指纹。尚未就绪的连接可先保存为停用来源。

### 远程环境准备

- 远程 Python 3.8+，已通过 Codex 创建会话，默认目录 `~/.codex/sessions`。
- Mac 可使用密钥或 ssh-agent 免交互登录；带口令的密钥需先在终端解锁。
- 自定义 `CODEX_HOME` 或 Python 虚拟环境可填写确切路径，避免非交互环境找不到它们。

验证已有别名：

```sh
ssh dev-server
# 在远程终端检查：
python3 --version
test -d ~/.codex/sessions && echo "sessions directory exists"
exit

# 回到 Mac 后检查免交互连接：
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes dev-server true
```

没有配置密钥时，可复制应用里的「SSH 配置引导」给自己的 Agent。只把**公钥**添加到远程 `authorized_keys`，私钥保留在本机。完整步骤见 [SSH 指南](docs/ssh-guide.md)。

后台固定使用 `BatchMode=yes` 与 `StrictHostKeyChecking=yes`，不自动接受指纹、不弹出密码输入框。停用或移除来源保留历史待办；重新添加相同连接名称可继续跟踪。

### 远程跳转与催办

读取、打开对话与催办是独立能力。打开远程对话需要 Codex 桌面认识该 SSH 机器；默认主机 ID 是 `remote-ssh-discovered:<连接名称>`，可在高级设置修改。

远程催办还需要远程已有的共享 Codex 服务，以及支持 `codex app-server proxy` 的 CLI。本机私有 IPC 与共享接口可能随 Codex 版本变化；读取成功不保证催办可用。coindex 不为催办启动新的独立会话引擎。

## 数据与隐私

```text
本机 Codex 会话 ─────┐
                    ├→ 只读采集与凭据遮蔽 → 本机 Codex CLI → 所选模型
启用的 SSH 会话 ─────┘                                    │
                                                        ↓
                                          本机 SQLite → 待办界面
用户主动点击催办 ─────────────────────────→ 原 Codex 对话
```

- **本机保存：** `~/Library/Application Support/CodexTodo/` 保存待办、对话摘录、连接设置、发送回执和宠物偏好。目录权限 `700`，数据库权限 `600`，应按敏感数据保护。
- **模型处理：** 对话摘录经你的 Codex 登录发送到所选模型。coindex 无自建托管分析服务，不额外收集遥测；Codex 的数据处理规则由账号与提供方政策决定。
- **遮蔽边界：** 采集会遮蔽常见 token、密码字段、私钥和 JWT，不能识别所有自由文本敏感信息。敏感来源应停用，或暂停分析。
- **其他请求：** 启用工作日规则时，从公开的 [holiday-cn](https://github.com/NateScarlet/holiday-cn) 下载节假日数据，不携带会话内容。
- **操作边界：** 采集不改写原记录。自动检测不自动催办、不代答、不批准权限；主动点击催办才向原对话追加消息。
- **发布边界：** 公共源码与应用不携带登录文件、私钥、SSH 配置、数据库、真实会话、日志、备份或导入的原版 Codex 宠物。

不要直接把数据目录、真实截图或原始诊断日志上传到公共 Issue。安全报告见 [SECURITY.md](SECURITY.md)。

## 常见问题

| 现象 | 先检查 |
| --- | --- |
| 找不到 Python | Python 3.9+ 和应用可发现的路径 |
| 找不到 CLI / 版本过旧 | 实际 CLI 路径与四个必需参数 |
| 已登录但看不到会话 | 数据目录、至少一个会话、启用与归档状态 |
| 连接成功但分析失败 | 模型、推理强度、账号配额与网络 |
| 终端 SSH 正常，后台失败 | 主机指纹、ssh-agent、免交互登录 |
| 远程目录不存在 | 远程用户、`CODEX_HOME`、读取权限 |
| 可以采集但无法催办 | 原 Codex 服务、桌面 IPC / 远程 proxy 与主机 ID |
| 结果待确认 | 先核对原对话，确认未送达后重试 |

完整步骤见[故障排查](docs/troubleshooting.md)。

## 从源码构建

需要 macOS 14+、Xcode 或 Command Line Tools、Python 3.9+。常规构建与后端测试不需要第三方 Python 库。

```sh
git clone https://github.com/Junming-Liang/coindex.git
cd coindex
xcode-select --install  # 已安装编译工具时跳过
python3 -m unittest discover -s tests -v
bash scripts/build.sh
open dist/coindex.app
```

默认构建当前 Mac 架构；通用构建使用：

```sh
COINDEX_ARCHS="arm64 x86_64" bash scripts/build.sh
```

输出 `dist/coindex.app`，采用 ad hoc 签名。演示模式使用虚构任务，不连接 SSH、不调用模型：

```sh
open -n dist/coindex.app --args --demo
```

开发变量：`CODEX_TODO_DATA_DIR`、`CODEX_TODO_PYTHON`、`CODEX_TODO_CODEX`。使用独立数据目录。无 Codex 的测试方式、Swift 动画验证与发布检查见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 项目结构

```text
Sources/             SwiftUI 界面、连接引导、设计系统与桌面宠物
backend/
  collector.py       只读解析与凭据遮蔽
  connections.py     本机发现、SSH 设置与连接检查
  analyzer.py        隔离的结构化模型分析
  store.py           SQLite、手动决定与待办身份
  service.py         stdin / stdout 服务与调度
  nudge.py           本机催办与持久回执
  remote_rpc.py      SSH 共享服务连接
scripts/             构建、演示、打包与发布检查
tests/              状态、采集、调度、连接与回执回归测试
docs/               使用、SSH 与故障排查指南
Resources/           品牌与默认小猫插画
```

界面通过进程 stdin / stdout 与后端通信，不开放 HTTP 监听端口。会话格式、桌面私有 IPC 与远程 proxy 依赖 Codex 实际版本，可能需要随上游更新适配。

## 参与贡献

欢迎提交可复现问题、文档改进与 Pull Request。请先读 [CONTRIBUTING.md](CONTRIBUTING.md)，用虚构会话与独立数据目录验证。连接问题提供版本与脱敏错误，不提供私钥、登录文件或真实会话。

- [问题与功能建议](https://github.com/Junming-Liang/coindex/issues/new/choose)
- [更新记录](CHANGELOG.md)
- [安全政策](SECURITY.md)
- [设计规范](DESIGN.md)

coindex 是独立社区项目，与 OpenAI 没有官方隶属关系。

## 许可证与致谢

原创代码与随项目发布的原创素材采用 [MIT License](LICENSE)。第三方参考与数据保留各自许可证：

- [OpenAI Codex 文档](https://learn.chatgpt.com/docs/codex/cli)：CLI 与官方使用说明。
- [awesome-design-md](https://github.com/VoltAgent/awesome-design-md)：设计参考，来源与 MIT 许可证见 [design/reference](design/reference/SOURCE.md)。
- [holiday-cn](https://github.com/NateScarlet/holiday-cn)：节假日数据，测试夹具保留[上游许可证](tests/fixtures/holiday-cn.LICENSE)。

从本机 Codex 导入的原版宠物仅用于个人构建，默认构建与公开 Release 不含这些素材。
