# Host compatibility baseline

Use this reference only for installing, discovering, or invoking this Skill. It does not define Claude Code configuration compliance.

## Boundary

- Supported hosts: Claude Code and Codex.
- Review subject: Claude Code project configuration and Claude Agent SDK integration only.
- Anthropic/Claude documentation remains the sole normative basis for `OFFICIAL-*` findings about the review subject.
- OpenAI documentation supports Codex host-compatibility claims only; it must not justify a Claude configuration finding.

## Shared package contract

Keep one package with one `SKILL.md`. Use only the shared `name` and `description` frontmatter fields. Keep host-specific presentation metadata in `agents/openai.yaml` rather than duplicating the workflow.

| Host | Project install | User install | Explicit invocation |
|---|---|---|---|
| Claude Code | `<project>/.claude/skills/agent-config-reviewer/` | `~/.claude/skills/agent-config-reviewer/` | `/agent-config-reviewer ...` |
| Codex | `<project>/.agents/skills/agent-config-reviewer/` | `$HOME/.agents/skills/agent-config-reviewer/` | `$agent-config-reviewer ...` |

Codex can also install a GitHub-hosted Skill through `$skill-installer`. This repository's Skill is at repository path `.`, so installation must preserve the explicit destination name `agent-config-reviewer`.

## Sources

- Claude Code Skills: `https://code.claude.com/docs/en/slash-commands`
- OpenAI Build skills: `https://learn.chatgpt.com/docs/build-skills`

Both products change quickly. Recheck host-sensitive paths, metadata, and invocation behavior against current official documentation before asserting compatibility when the bundled baseline date is stale.
