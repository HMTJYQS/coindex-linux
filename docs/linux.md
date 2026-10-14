# coindex Linux

这是 [Junming-Liang/coindex](https://github.com/Junming-Liang/coindex) 的 Linux 移植版。使用 Qt 桌面界面和上游 Python 后端，保留任务身份、手动操作、调度和催办去重规则。上游来源及许可见 [UPSTREAM.md](../UPSTREAM.md)。

## 系统要求

- Python 3.10+，`pip` 和 Python `venv` 模块。
- PySide6-Essentials 6.8.3（安装时自动获取），`tzdata`。
- Linux 图形桌面；Ubuntu 22.04 x86_64 为首版本机验收目标；Ubuntu 24.04 已配置 CI，实际结果待工作流运行确认。
- 实际整理会话时，需要已登录且支持上游所需参数的 Codex CLI；演示模式无需登录。
- SSH 来源按需启用，要求免交互登录及远程 Python；参见 [SSH 指南](ssh-guide.md)。

安装脚本使用用户级目录，不需要 `sudo`。缺少 `ensurepip` 的 Ubuntu Python 也可使用：脚本创建不含 pip 的 venv，然后用系统 pip 将 pip 安装到该隔离环境。系统 Python 必须已有可运行的 `python3 -m pip`。

Qt 的图形运行库由系统提供，Python wheel 不会安装这些系统包。即使使用 offscreen，导入 QtGui 也需要 EGL 和 GL。Ubuntu 22.04/24.04 首次运行前安装下列运行库；Ubuntu 24.04 的 GLib 包使用 `t64` 名称：

```sh
. /etc/os-release
COINDEX_GLIB_PACKAGE=libglib2.0-0
if [ "$VERSION_ID" = "24.04" ]; then
  COINDEX_GLIB_PACKAGE=libglib2.0-0t64
fi
sudo apt-get update
sudo apt-get install -y "$COINDEX_GLIB_PACKAGE" \
  libegl1 libgl1 libopengl0 libfontconfig1 libfreetype6 libdbus-1-3 \
  libx11-6 libx11-xcb1 libxrender1 libxkbcommon0 libxkbcommon-x11-0 \
  libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render0 libxcb-render-util0 libxcb-shape0 \
  libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 libxcb-util1
```

安装 coindex 完成后，用安装环境检查 Qt 是否可导入：

```sh
~/.local/share/coindex-linux/app/venv/bin/python -c "from PySide6 import QtCore, QtGui, QtWidgets; print('Qt runtime import OK:', QtCore.qVersion())"
```

自定义 XDG/安装目录时请替换解释器路径；自行通过 pip 安装时，使用安装该 wheel 的 Python 环境。其他发行版请参考 [Qt 官方 X11 依赖说明](https://doc.qt.io/qt-6/linux-requirements.html) 选择对应系统包。工作流在测试前强制导入 QtCore、QtGui 和 QtWidgets，缺库时直接失败，避免 Qt 测试因导入失败被跳过；Xvfb/xcb 检查仍需通过。

## 从 Release 安装

从 [Linux Releases](https://github.com/HMTJYQS/coindex-linux/releases/latest) 下载 wheel、`source.tar.gz` 和 `SHA256SUMS.txt`，放在同一目录。校验和确认文件未损坏：

```sh
sha256sum -c SHA256SUMS.txt
tar -xzf coindex-linux-*-source.tar.gz
cd coindex-linux
bash scripts/install-linux.sh ../coindex_linux-*.whl
```

安装完成后，从桌面应用菜单打开 **coindex Linux**，或运行：

```sh
~/.local/bin/coindex-linux
~/.local/bin/coindex-linux --demo
```

`--demo` 只加载虚构数据，禁用真实分析与催办。默认安装不会启用自启动。设置中的自启动开关可在之后按需开启。

默认安装位置：

| 内容 | 默认位置 |
| --- | --- |
| 任务数据库与会话摘录 | `$XDG_DATA_HOME/coindex`（默认 `~/.local/share/coindex`） |
| 小猫显示偏好 | `$XDG_CONFIG_HOME/coindex-linux/desktop.conf`（默认 `~/.config/coindex-linux/desktop.conf`） |
| 应用及隔离 Python 环境 | `$XDG_DATA_HOME/coindex-linux/app`（默认 `~/.local/share/coindex-linux/app`） |
| 启动命令 | `~/.local/bin/coindex-linux` |
| 桌面菜单入口 | `$XDG_DATA_HOME/applications/coindex-linux.desktop` |
| 菜单图标 | `$XDG_DATA_HOME/icons/hicolor/256x256/apps/coindex-linux.png` |

终端中无法直接找到 `coindex-linux` 时，可使用上面的完整路径，或将 `~/.local/bin` 加入自己的 PATH。桌面菜单启动不依赖终端 PATH。

安装器还支持明确指定 `--prefix`、`--bin-dir`、`--desktop-dir` 和 `--icon-dir`。升级和卸载时使用同一个 `--prefix`；该目录应只用于应用，不能指向自己的整个数据目录。

## 从源码构建与 pip 安装

```sh
git clone https://github.com/HMTJYQS/coindex-linux.git
cd coindex-linux
python3 -m pip install setuptools wheel
python3 scripts/build-linux.py
bash scripts/install-linux.sh dist/Linux/coindex_linux-*.whl
```

产物位于 `dist/Linux/`：wheel、公开源码 tar.gz、`SHA256SUMS.txt`。构建会执行公开文件和资源检查；wheel 内包含后端、图标、小猫资源及演示 JSON，启动时不需要源码目录。

也可以把 wheel 安装到自行管理的 Python 环境：

```sh
python3 -m pip install dist/Linux/coindex_linux-*.whl
coindex-linux --demo
```

自行通过 pip 安装时，pip 不会添加桌面菜单入口。

若需要离线安装，提前下载依赖，再提供 wheel 目录：

```sh
python3 -m pip download --dest wheelhouse dist/Linux/coindex_linux-*.whl pip
bash scripts/install-linux.sh dist/Linux/coindex_linux-*.whl --offline --find-links wheelhouse --pip-wheel wheelhouse/pip-*.whl
```

## 升级与卸载

升级前退出 coindex，使用相同安装命令指定新 wheel。安装器先准备和验证新环境，再替换已被 coindex manifest 标记的安装；失败会保留当前应用。桌面入口或启动脚本被用户修改时，安装器会拒绝覆盖。

卸载使用源码包中的脚本：

```sh
bash scripts/uninstall-linux.sh
# 自定义应用目录时：
bash scripts/uninstall-linux.sh --prefix /opt/example/coindex-linux
```

卸载只删除 manifest 标记的应用目录及内容仍一致的启动器、桌面入口、图标。任务、会话及偏好数据会保留；修改过的外部文件也会保留。不要把 `--prefix` 指向任务数据目录。

## 桌面差异

Linux 使用 Qt 主窗口、桌面菜单和可选系统托盘。桌面环境没有托盘时，关闭窗口会退出应用。窗口内小猫可显示 idle/running/waiting/review/failed 状态，并支持减少动画。X11（xcb）可选择可拖动的悬浮小猫，双击返回工作台、右键关闭；Wayland 只提供窗口内动画。

原对话通过 Linux 桌面 URL 处理器打开。如果本机 Codex 没有注册相应协议，可在应用中复制原对话链接，再由自己的 Codex 客户端打开。远程来源保留 SSH 与原会话信息。

## 验证边界

仓库提供 Python 后端回归、Qt 集成测试、安装 ownership/回滚测试，以及临时 HOME 安装后离开源码目录启动、升级、卸载的 CI 检查。测试使用虚构会话、隔离数据库和模拟 CLI；不会自动发送真实催办。

2026-10-14 本机 Ubuntu 22.04 x86_64 验收：186 项测试，185 项通过，1 项因可选上游宠物素材未导入而跳过。全新用户目录离线安装、离开源码目录启动演示、安装后的真实 Qt 子进程任务保存与重启恢复、升级及保留数据卸载均通过。本机 Codex 桌面 IPC 的只读初始化握手通过；没有发送真实催办。

本机 offscreen 渲染已通过；实体 X11 使用应用私有目录内经过校验的 Ubuntu 官方 `libxcb-cursor0` 库，通过默认启动入口完成演示启动和截图验收。该库采用隔离提取方式加载，未通过系统包管理器全局安装；标准安装仍应补齐上面的系统运行库。Ubuntu 22.04/24.04 工作流会分别验证 offscreen 与 Xvfb 的 xcb 启动，远程 CI 成功后再将对应结果作为验证证据。真实模型分析、真实 SSH 主机连通及真实催办送达，需要使用自己的账户与来源进行检查，不在自动测试的完成声明中。

图形库错误通常会提示缺少 X11/Wayland 系统组件。CI 用 `QT_QPA_PLATFORM=offscreen` 无界面平台测试；正常桌面运行不需要设置该变量。首次设置建议先保存并检查 Codex 连接，确认登录及会话目录可读后再启用自动整理。

## 维护者人工发布安装包

仓库的 **Publish Linux release** 工作流只通过 GitHub Actions 的 **Run workflow** 人工触发；选择 `main`，标签默认 `v1.9.0-linux.1`。标签 `vX.Y.Z-linux.N` 必须对应安装包版本 `X.Y.Z.postN`，并绑定触发时的精确源码提交。

工作流先在 Ubuntu 22.04 上运行隔离后端与 Qt 测试、公开包隐私检查和离开源码目录后的 Xvfb/xcb 演示启动，再创建草稿 Release，上传 wheel、source.tar.gz 和 `SHA256SUMS.txt`。下载资产与构建文件逐字节一致后才公开发布。仓库 `contents: write` 权限仅授予这个发布 job，安装、测试和构建步骤不读取个人账户凭据。

同名标签或 Release 已存在时会明确失败，保留已有资产；不会自动覆盖。上传或校验中断时可能留下草稿，维护者应先检查该草稿，不要反复触发同一个标签。普通 push 和 PR 不触发发布。
