# Agent Config Reviewer（Agent 配置审查器）

一个可在 **Claude Code** 与 **Codex** 中安装和运行的可移植 Skill，专门用于审查、验证和优化 Claude Code 项目的**实际生效配置系统**，覆盖项目指令、设置、权限、规则、Skills、子 Agent、hooks、MCP、命令、输出样式、worktrees 以及 Claude Agent SDK 启动代码。

Codex 只是本 Skill 的运行宿主之一；审查对象仍然是 Claude Code 配置，不会把 `AGENTS.md`、`.agents/` 或 `.codex/` 当作 Claude 配置审查。

## 安装

复制完整 Skill 包，而不是只复制 `SKILL.md`。

### Claude Code

项目级：

```text
<project-root>/.claude/skills/agent-config-reviewer/
```

用户级：

```text
~/.claude/skills/agent-config-reviewer/
```

### Codex

项目级：

```text
<project-root>/.agents/skills/agent-config-reviewer/
```

用户级：

```text
$HOME/.agents/skills/agent-config-reviewer/
```

也可以在 Codex 中让 `$skill-installer` 从 GitHub 安装。本仓库的 Skill 位于仓库根目录，因此需明确仓库、源路径 `.` 和目标名称：

```text
使用 $skill-installer 从仓库 wr5912/claude-code-config-reviewer 的路径 . 安装，并将 Skill 命名为 agent-config-reviewer。
```

`$skill-installer` 使用 Codex 管理的用户级 Skill 目录。不要再向 `$HOME/.agents/skills` 手动复制同名 Skill，否则两个同名条目可能同时出现在选择器中。如果安装后未出现，请重启 Codex。

本 Skill 使用中立的 `agent-config-reviewer` 名称，以符合可移植 Agent Skills 命名约束，并在两个宿主中保持同一名称。

## 调用与目标路径

Claude Code 使用 `/` 调用：

```text
/agent-config-reviewer review
/agent-config-reviewer review /path/to/claude-project
/agent-config-reviewer review "/path/with spaces/.claude"
/agent-config-reviewer optimize /path/to/claude-project
/agent-config-reviewer validate /path/to/claude-project
```

Codex 使用 `$` 调用：

```text
$agent-config-reviewer review
$agent-config-reviewer review /path/to/claude-project
$agent-config-reviewer review "/path/with spaces/.claude"
$agent-config-reviewer optimize /path/to/claude-project
$agent-config-reviewer validate /path/to/claude-project
```

调用格式为 `[review|optimize|validate] [target] [--runtime-root <path>]`。未指定操作时默认为 `review`；未指定目标时才使用当前工作目录。

`target` 接受 Claude 项目根目录，或该项目直接包含的 `.claude` 目录。传入 `<project>/.claude` 时会规范化为 `<project>`，从而同时审查同级的 `CLAUDE.md`、`.mcp.json`、`.worktreeinclude` 和必要的 Agent SDK 启动代码。不存在、不可读、普通文件、用户级 `~/.claude` 或宿主配置目录 `.agents`/`.codex` 会明确失败，且不会静默回退当前目录。

当 Claude 配置仓与 Agent SDK 运行时仓分离时，可显式传入外部运行时根：

```text
$agent-config-reviewer review /path/to/config-project --runtime-root /path/to/runtime-project
```

`--runtime-root` 只用于 SDK 启动、依赖和运行时代码证据，不会改变 Claude 配置根或 `${CLAUDE_PROJECT_DIR}`。无效的显式运行时路径同样会失败且不回退。

## 可验证的审查结果

完整审查会为 catalog 中每个稳定检查项记录 `PASS / FINDING / NA / UNVERIFIED`，并对扫描器给出的每个 P0/P1 candidate 作出明确处置。权威结果是 `agent-config-reviewer-report/v2` JSON，Markdown 报告由校验器生成：

```bash
python3 scripts/validate_review.py review.json --scan scan.json --markdown review.md
```

Markdown 第一层提供全量覆盖索引，第二层详细展开 P0/P1。任何遗漏检查项、未处置 P0/P1 或缺少证据的关键结论都会使报告标记为 `INCOMPLETE`，不会被静默当作通过。

## 安全模型

静态审查不会执行项目 hooks 或任意项目代码。现有 tests/evals 会被视为验证资产，而不是生产配置的修改目标。只有在识别出安全的非生产、mock 或 replay 验证环境，或由用户提供此类环境后，才允许进行运行时验证。

## 验证 Skill 包

```bash
python3 -B scripts/self_check.py
python3 -B -m unittest discover -s tests -v
python3 -B scripts/run_evals.py
```

第一条命令校验包清单、文件哈希、双宿主元数据、catalog 与 fixture 契约；第二条命令运行精简的表驱动回归；第三条命令遍历 8 个合成多文件 fixture。它们都只使用 Python 标准库，不调用模型，也不会执行 fixture 中的 Hook 或项目代码。

真实 Claude Code/Codex Skill-on/Skill-off A/B 只作为发布前人工门禁，不进入日常测试。固定的 12 次运行矩阵、隔离方式、ground truth、指标公式与 `PASS / FAIL / INVALID` 判定见 `references/eval-harness.md`。该门禁不能读取真实工作区、凭据或生产环境。

## 规范性发现与宿主兼容

只有当前有效的 Anthropic/Claude 官方文档可以作为 Claude 配置 `OFFICIAL-*` 类发现的依据。OpenAI 官方文档只用于验证 Codex 的安装、发现与调用兼容性，不能用于判定 Claude 配置是否合规。安全性、可移植性、架构和可维护性建议会单独标注。

## 包含内容

```text
agent-config-reviewer/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
├── scripts/
│   ├── scan_project.py
│   ├── validate_review.py
│   ├── run_evals.py
│   └── self_check.py
├── evals/
├── templates/
├── tests/
├── LICENSE
├── PACKAGE-MANIFEST.json
├── README.md
└── README_en.md
```

## 内置官方基线

内置的 Claude 配置来源基线和双宿主安装契约已于 **2026-08-13** 重新核查。Claude Code 与 Codex 都会快速变化；网络可用时，应先根据各自当前官方文档刷新对版本敏感的结论。无法核实的 Claude 配置发现必须标记为 `UNVERIFIED`，不能直接认定为违规。
