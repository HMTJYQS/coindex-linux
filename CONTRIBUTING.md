# Contributing to coindex

欢迎问题复现、文档与代码贡献。较大行为调整先在 Issue 说明场景和预期，持久状态与连接改动需解释兼容性。

## 开发与验证

需要 macOS 14+、Xcode / Command Line Tools、Python 3.9+。后端只使用标准库。测试使用虚构数据与模拟连接，无真实登录时可运行：

```sh
CODEX_TODO_CODEX=/usr/bin/true python3 -m unittest discover -s tests -v
bash scripts/build.sh
open -n dist/coindex.app --args --demo
```

Swift 动画测试：

```sh
mkdir -p build
swiftc Sources/PetAnimation.swift tests/pet-animation/main.swift -o build/pet-animation-tests
build/pet-animation-tests
```

可选图集打包工具需要 Pillow 与 NumPy，普通构建不需要。原版 Codex 图集仅用于本机个人导入，不进公开包。

## 约定

- 沿用 DESIGN.md 的组件、键盘与悬停反馈。
- 验证外部输入、SSH 参数、路径与模型结果。
- 保留任务身份、手动决定、固定标题和发送回执；未知回执不自动重发。
- 分析不执行原对话里的指令；连接检查不调用模型、不发催办。
- 使用独立临时数据与虚构会话验证行为。
- 行为改动提供有意义的回归，文案或样式不需要照抄实现的测试。

PR 说明具体问题、结果行为、验证和限制。界面截图只用演示数据。提交前测试、构建与 `git diff --check` 应通过。

## 发布

```sh
COINDEX_ARCHS="arm64 x86_64" bash scripts/build.sh
python3 scripts/check-public-release.py
python3 scripts/package-source.py
```

只发布默认公共构建，不上传含 `COINDEX_INCLUDE_LOCAL_PETS=1` 的个人构建。核对归档清单与 SHA-256，Git 提交使用隐藏邮箱，不发布个人路径、机器地址、日志或真实会话。安全问题按 SECURITY.md 私密报告。
