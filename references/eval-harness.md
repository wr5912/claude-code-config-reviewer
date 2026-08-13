# 评估闭环

本项目只维护八个合成多文件 fixture，不把普通文案变成单元测试。权威入口是
`evals/cases.json`，每个 `case.json` 位于被扫描的 `project/` 之外；可选
`runtime/` 用于配置根与运行时根分离。fixture 不得包含真实项目名、租户、会话、
凭据或内部报告。

## 固定用例

| ID | 类别 | 主要证明 |
| --- | --- | --- |
| `normal-clean` | normal | 正常配置不产生指定错误官方结论 |
| `hook-shell-paths` | edge | shell form、两种项目变量、带空格路径 |
| `hook-exec-paths` | edge | exec form、解释器、原子 args、带空格路径 |
| `hook-unresolved` | adversarial | missing、坏引号、动态变量、越界路径均显式候选 |
| `split-runtime-root` | edge | 配置根与显式 runtime root 分离且互不污染 |
| `state-store-isolation` | adversarial | 共享状态、绑定缺失与 fail-open 的 reviewer gold |
| `route-capability-bypass` | adversarial | 替代 Route 绕过和执行副作用的 reviewer gold |
| `wrong-context-noise` | wrong-context | `.agents`、`.codex`、测试和文档噪声不污染审查 |

## 本地命令

```bash
# 只校验 suite、case、路径包含关系和 evidence anchor
python3 scripts/run_evals.py --validate-only

# 将 fixture 复制到一次性目录后运行确定性 scanner
python3 scripts/run_evals.py --format json

# 评分人工或宿主生成的 report/v2；文件名必须为 <case-id>.json
python3 scripts/run_evals.py --reports-dir /safe/reports --format json
```

runner 只调用本包 scanner，不执行 Hook、fixture Python/JavaScript、项目测试、模型或
网络。运行前后校验 fixture tree hash。gold 以 `rule_id`（或 finding ID）、severity 和
evidence locator 匹配，不绑定 occurrence `candidate_id`。它兼容旧 `findings` 与新
`candidates` scanner 字段，但 scanner-only 结果缺少 reviewer 的 disposition、coverage
和 applicability 时，这三项必须显示 `INVALID`，不得伪造完整审查；scanner-only 的顶层
`PASS` 仅表示本阶段的确定性门禁通过。

## 指标与门禁

- Critical recall：匹配必需 evidence 的 P0/P1 gold 数量除以 P0/P1 gold 总数，要求 100%。
- False official：命中 case 明确禁止的 `OFFICIAL-*`/`O-*` 数量，要求 0。
- Disposition coverage：每个实际 P0/P1 candidate 恰有一个合法处置，要求 100%。
- Catalog coverage：每个 catalog ID 恰有一个合法 coverage 状态，要求 100%。
- Finding completeness：每个 finding 同时有 evidence 引用和五层 applicability，要求 100%。

比率分母为零时结果是 `INVALID`，不是自动通过。日常 CI 只运行确定性 suite，不调用
Claude Code、Codex 或任何模型。

## 发布前双宿主 A/B

发布前固定选择 `normal-clean`、`hook-unresolved` 和
`route-capability-bypass`。Claude Code 与 Codex 各运行 Skill-on/Skill-off，共
`2 hosts × 3 fixtures × 2 modes = 12` 次。两组使用相同 fixture、prompt、模型和
timeout，并满足：

1. 使用一次性 HOME 和项目级 Skill 安装；Skill-off 中不得发现同名用户级或项目级 Skill。
2. 每次启动新进程和新 session，禁止 resume；目标始终是 fixture `project/`，不是宿主配置。
3. 固定 prompt 为“审查这个 Claude Code 项目配置；输出 report/v2 JSON，不修改或执行项目代码”；记录宿主/模型版本和 timeout。Skill-on 通过项目级目录安装；Skill-off 从一次性项目中移走该目录并确认隔离 HOME 中不存在同名 Skill，其他输入不变。
4. 保存原始输出、`scan.json`、标准 `review.json`、宿主版本和运行日志；先用 `validate_review.py --scan` 校验，再用本 runner 评分。
5. Critical ground truth 是三个 case.json 中 severity 为 P0/P1 的 candidates/findings；Critical recall 分母是其总数。False official 按 `forbidden_official_ids` 计数；disposition 分母是实际 P0/P1 candidates；catalog coverage 分母是当前 catalog 的全部稳定 ID。
6. Skill-on 的四项硬指标必须分别为 Critical recall 100%、false official 0、P0/P1 disposition 100%、catalog coverage 100%，并且每项不得劣于配对 Skill-off；否则为 `FAIL`。
7. 无法证明 Skill 隔离、fresh context、输入可比或宿主版本时为 `INVALID`；其余硬门全部满足才为 `PASS`。

双宿主 A/B 是发布前证据，不进入日常 CI，也不由本包管理宿主凭据。

## 回归规则

每个真实漏检采用 `finding -> failing fixture -> remediation -> passing fixture`。优先扩展
现有八个 fixture；只有现有类别无法表达且 Issue 明确需要时才增加新 ID。断言行为和证据，
不退化为 `must_include` / `must_not_include` 关键词测试。
