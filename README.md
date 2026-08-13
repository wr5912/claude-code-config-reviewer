# Agent Config Reviewer（Agent 配置审查器）

一个可移植的 Claude Code 项目级 Skill，用于审查、验证和优化由项目指令、设置、权限、规则、Skills、子 Agent、hooks、MCP、命令、输出样式、worktrees 以及 Claude Agent SDK 启动代码共同构成的**实际生效配置系统**。

## 安装

项目级：

```text
<project-root>/.claude/skills/agent-config-reviewer/
```

用户级：

```text
~/.claude/skills/agent-config-reviewer/
```

本 Skill 特意使用 `agent-config-reviewer` 这一名称，而没有在 Skill 名称中加入 `claude`。这样既能遵循 Anthropic Agent Skills 的命名约束，也能继续承担 Claude Code 配置审查职责。

## 调用示例

```text
/agent-config-reviewer review
/agent-config-reviewer review current project configuration
/agent-config-reviewer optimize the configuration and validate with the existing safe eval harness
/agent-config-reviewer validate the last configuration change
```

本 Skill **不要求**仓库采用特定目录结构。它从当前项目或 workspace 出发，查找 Claude Code 文档中定义的位置；不会预设存在 `workspace/`、`/data`、某个特定测试目录、某个特定运行时封装，也不会预设使用任何指定的平台或产品。

## 安全模型

静态审查不会执行项目 hooks 或任意项目代码。现有 tests/evals 会被视为验证资产，而不是生产配置的修改目标。只有在识别出安全的非生产、mock 或 replay 验证环境，或由用户提供此类环境后，才允许进行运行时验证。

## 规范性发现与建议性发现

只有当前有效的 Anthropic/Claude 官方文档可以作为 `OFFICIAL-*` 类发现的依据。安全性、可移植性、架构和可维护性方面的建议会单独明确标注。有限范围修改、配对比较、已接受/已拒绝修复记忆，以及以验证为门槛的优化等社区方法，仅作为非规范性的优化技术使用。

## 包含内容

```text
agent-config-reviewer/
├── SKILL.md
├── README.md
├── references/
│   ├── official-compliance.md
│   ├── config-responsibility-matrix.md
│   ├── check-catalog.md
│   ├── review-methodology.md
│   ├── remediation-patterns.md
│   ├── eval-harness.md
│   ├── optimization-loop.md
│   └── non-normative-inspirations.md
├── scripts/
│   ├── scan_project.py
│   └── self_check.py
├── evals/
│   └── cases.json
└── templates/
    └── review-report.md
```

## 内置官方基线

内置的官方来源基线已于 **2026-08-13** 重新核查。Claude Code 的变化很快；在网络可用时，审查器应先根据当前官方文档刷新对版本敏感的结论，再作出合规判定。若无法刷新，则必须将对版本敏感的发现标记为 `UNVERIFIED`，而不能直接认定为违规。
