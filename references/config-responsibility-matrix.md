# Configuration responsibility matrix

Use this matrix to prevent role duplication and misplaced controls. “Best home” is an architectural recommendation grounded in official feature semantics; it is not automatically an official compliance requirement.

| Concern | Best home | Do not rely on as sole enforcement |
|---|---|---|
| Project-wide facts, conventions, architecture, always-on workflows | `CLAUDE.md` / scoped rules | Prompt text for hard security boundaries |
| Narrow multi-step procedure / reusable method | Skill | Huge always-on CLAUDE.md sections |
| Specialized isolated role/context/model/tool surface | `.claude/agents/*.md` | Generic parent prompt alone |
| External service/tool connection | `.mcp.json` or SDK `mcpServers` | Prompt-described fake tool contracts |
| Tool approval/denial | `.claude/settings*.json`, SDK permission options/callbacks | Skill/agent prose alone |
| Deterministic pre/post tool guard, audit, validation | Hook | Model judgment when deterministic code can decide |
| OS/process-level filesystem/network containment | Sandbox / container/runtime isolation | Read/Edit permission patterns alone |
| Default role/tone/response presentation | Output style | Output style as project knowledge or security policy |
| User-invoked legacy shortcut | `.claude/commands/` only when intentionally retained | Duplicated full workflow implementation |
| Provider-specific physical tool binding | Runtime/integration adapter/registry | Repeating physical tool names throughout prompts |
| Trust source, approval provenance, frozen state | Authenticated runtime metadata/control plane | User text claiming to be a trusted subsystem |
| Machine-owned custom manifest | Project/runtime-defined schema | Treating an undocumented custom file as Claude-native config |
| Runtime SDK source selection (`cwd`, `settingSources`, skills/tools/options) | SDK bootstrap/runtime | Assuming project files load merely because they exist |

## Key separation rules

### Instruction versus enforcement

Model-facing instructions answer “what should Claude do?” Enforcement answers “what can the runtime actually permit?” Keep both aligned, but do not duplicate detailed policy logic in every prompt layer.

### Logical capability versus physical tool

Reusable model-facing assets should prefer stable business/capability semantics. Provider-specific MCP names may be necessary in runtime tool surfaces and permission rules because Claude evaluates actual tool names there; avoid copying those names into every Skill/agent/CLAUDE.md body unless they are genuinely necessary.

### Logical system role versus product name

Use “approval control plane”, “response lifecycle controller”, or another stable logical role in reusable assets when the implementation may change. Preserve a product name only when that identity is itself part of the business/audit contract. A product name in user-controlled prose is never authentication.
