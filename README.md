# skillz — multi-skill catalog for Claude Code and Codex

A small, growing catalog of Claude Code / Codex skills, exposed as
individual plugins and a full-bundle plugin via the host's native
`/plugin install` flow. Skills are plain `SKILL.md` files; each
plugin entry adds a thin manifest plus a `skills/` directory of
symlinks back to the canonical `skills/<name>/`. A legacy
`install.sh` script remains available as a fallback for sandboxed
environments and older Codex versions.

## Table of contents

- [Catalog](#catalog)
- [Layout](#layout)
- [Install — Claude Code plugin (recommended)](#install--claude-code-plugin-recommended)
- [Install — Codex plugin (recommended)](#install--codex-plugin-recommended)
- [Install — script (legacy / fallback)](#install--script-legacy--fallback)
- [Migrating from `debedb/skillz`](#migrating-from-debedbskillz)
- [Catalog manifest](#catalog-manifest)
- [Contributing](#contributing)
  - [Which branch to target](#which-branch-to-target)
  - [Rules for a PR onto `next`](#rules-for-a-pr-onto-next)
  - [Merging `next` back into master](#merging-next-back-into-master)
- [Updating](#updating)
- [Releases](#releases)
- [Verify](#verify)
- [Collections](#collections)
  - [pr-loop](#pr-loop-collection)
- [Plugins](#plugins)
  - [codex-continuous-learning](#codex-continuous-learning-codex-only)
  - [tamarian](#tamarian-claude-only)
- [Validation](#validation)
  - [Rebasing a stale skill branch](#rebasing-a-stale-skill-branch)
- [Related code-review approaches](#related-code-review-approaches)
- [PR review workflow stack](#pr-review-workflow-stack)

## Catalog

| Name | Type | Hosts | Purpose |
|---|---|---|---|
| [oauth-mint-counting-passthrough-proxy](./skills/oauth-mint-counting-passthrough-proxy/SKILL.md) | skill | Claude, Codex | Count OAuth2 client-credentials token mints end to end by routing the config-driven token endpoint through a counting pass-through proxy started in the spec; proves gateway 401/200/refresh and N-calls-one-mint in one run. |
| [work-on-pr](./skills/work-on-pr/SKILL.md) | skill | Claude, Codex | Author-side PR iteration loop |
| [review-pr-loop](./skills/review-pr-loop/SKILL.md) | skill | Claude, Codex | Reviewer-side PR iteration loop |
| [codex-adversarial-pr-review](./skills/codex-adversarial-pr-review/SKILL.md) | skill | Claude, Codex | Post /codex:adversarial-review findings as a batched GitHub PR review (inline + out-of-diff rollup) |
| [continuous-learning](./skills/continuous-learning/SKILL.md) | skill | Codex | End-of-task retrospective: extract reusable, verified learnings as Codex skills |
| [cmux-search](./skills/cmux-search/SKILL.md) | skill | Claude, Codex | Search all open cmux workspaces/tabs/panes - live scrollback + agent transcripts |
| [macos-sparkle-update-quarantine-relaunch](./skills/macos-sparkle-update-quarantine-relaunch/SKILL.md) | skill | Claude, Codex | Sparkle updater error 4005 / 'Failed to create installation cache directory' persists after stripping quarantine; relaunch the un-quarantined bundle |
| [cmux-agent-tabs](./skills/cmux-agent-tabs/SKILL.md) | skill | Claude, Codex | Make AI agents show as watchable cmux tabs; Claude needs the `claude-teams` wrapper, Codex via `codex-teams`/hooks |
| [cmux-autoresume-after-reboot](./skills/cmux-autoresume-after-reboot/SKILL.md) | skill | Claude, Codex | Why cmux does not resume agent sessions after a macOS reboot despite `autoResumeAgentSessions` |
| [python-ast-static-analyzer-scoping](./skills/python-ast-static-analyzer-scoping/SKILL.md) | skill | Claude, Codex | Build a Python `ast` analyzer: import-alias resolution + load-time vs deferred scoping |
| [wordpress-com-publish](./skills/wordpress-com-publish/SKILL.md) | skill | Claude, Codex | Acquire a WordPress.com OAuth2 token (authorization-code flow) and publish/update posts |
| [git-worktree-convention](./skills/git-worktree-convention/SKILL.md) | skill | Claude, Codex | Repo on default branch, branch work in sibling `<repo>.worktrees/`; drift detection, ask-before-reorganizing, and recovery |
| [git-graft-worktree-onto-remote](./skills/git-graft-worktree-onto-remote/SKILL.md) | skill | Claude, Codex | Graft a local worktree's commits onto a remote branch without re-cloning |
| [multi-phase-feature-pr-worktrees](./skills/multi-phase-feature-pr-worktrees/SKILL.md) | skill | Claude, Codex | Run a multi-phase feature as stacked worktree PRs, each reviewed independently |
| [gist-to-repo-migration](./skills/gist-to-repo-migration/SKILL.md) | skill | Claude, Codex | Migrate a gist's full revision history into a real git repo |
| [neon-vercel-db-identify-and-migrate](./skills/neon-vercel-db-identify-and-migrate/SKILL.md) | skill | Claude, Codex | Identify which Neon project backs a Vercel app and migrate/split it; safe non-destructive cutover |
| [claudeception](./skills/claudeception/SKILL.md) | skill | Claude | Continuous-learning meta-skill: procedures become catalog skills via PR; specifics go to memory (local or shared vault) |
| [claude-code-codex-plugin-parity](./skills/claude-code-codex-plugin-parity/SKILL.md) | skill | Claude, Codex | Port a Claude Code plugin to the Codex CLI (or back); where the two systems match vs diverge |
| [claude-code-plugin-from-existing-repo](./skills/claude-code-plugin-from-existing-repo/SKILL.md) | skill | Claude, Codex | Convert a repo that ships CC commands/hooks (manual copy-in) into an installable plugin |
| [claude-code-plugin-python-bootstrap](./skills/claude-code-plugin-python-bootstrap/SKILL.md) | skill | Claude, Codex | Bootstrap Python deps from a CC plugin hook so `/plugin install` is one-click (PEP 668-safe) |
| [claude-code-plugin-update-flow](./skills/claude-code-plugin-update-flow/SKILL.md) | skill | Claude, Codex | Update a CC plugin via `/plugin marketplace update` + `/reload-plugins`, not the picker `/plugin update` |
| [claude-code-plugin-release-automation](./skills/claude-code-plugin-release-automation/SKILL.md) | skill | Claude, Codex | Tag + release notes automatically from the manifest version; CI fails a PR that forgot the bump |
| [claude-code-plugin-publish-anthropic-marketplace](./skills/claude-code-plugin-publish-anthropic-marketplace/SKILL.md) | skill | Claude, Codex | Publish a CC plugin to Anthropic's marketplace, plus the pre-submission validation pass |
| [claude-json-mcp-migration-slice](./skills/claude-json-mcp-migration-slice/SKILL.md) | skill | Claude, Codex | The exact `~/.claude.json` slice that carries MCP config for migration vs session bookkeeping |
| [playwright-mcp-upload-hidden-file-input](./skills/playwright-mcp-upload-hidden-file-input/SKILL.md) | skill | Claude, Codex | Upload to a hidden `<input type=file>` via Playwright MCP (unhide+tag, upload, verify via CDN URL) |
| [agent-team-orchestration](./skills/agent-team-orchestration/SKILL.md) | skill | Claude, Codex | Run a team of agents over a repo's open issues: architect plans the parallel set, per-issue squads (dev + adversarial reviewer + SDET + productivity engineer), each individually watchable |
| [istio-multicluster-endpointless-mesh-service](./skills/istio-multicluster-endpointless-mesh-service/SKILL.md) | skill | Claude, Codex | Istio multi-cluster endpoint-less away-Service: use a decoy selector (not an omitted one) so an EndpointSlice anchor exists for the mesh to merge remote endpoints into; for cross-region write-routing / home-away Service topologies |
| [pre-open-source-credential-audit](./skills/pre-open-source-credential-audit/SKILL.md) | skill | Claude, Codex | Audit a git repo for leaked secrets before making it public: scan tracked files AND full history, avoid the git grep -E word-boundary false-negative, catch tracked editor-backup files, decide rewrite+rotate vs. accept an inert identifier |
| [agent-session-credential-audit](./skills/agent-session-credential-audit/SKILL.md) | skill | Claude, Codex | Triage, rotate and scrub credentials that leaked into an agent session transcript: the surfaces a naive scan misses, the false-positive taxonomy, the key-id-vs-secret severity test, non-destructive liveness probes validated with a known-bad control, how to verify a rotation actually rotated (two credential surfaces, delete-vs-revoke, mint-without-retire), and a kill-list scrub that cannot erase a live secret |
| [prevent-committing-secrets](./skills/prevent-committing-secrets/SKILL.md) | skill | Claude, Codex | Block a credential at commit time with a gitleaks pre-commit hook, and cover new/cloned repos automatically via `init.templateDir`: the six paths that skip the hook, where gitleaks' default ruleset is blind, why a staged-diff scan is not a history scan, and GitHub push protection plus a required CI check as the halves that cannot be bypassed locally |
| [terraform-state-version-apply-forensics](./skills/terraform-state-version-apply-forensics/SKILL.md) | skill | Claude, Codex | Prove a terraform change really was applied to an env: census versioned S3 tfstate objects (serial + resource-type counts) + cross-check CloudTrail; separates a real apply from a reverted one, identifies which variant of a stacked change ran, and tells untracked orphans from failed destroys |
| [terraform-ecs-capacity-provider-staged-teardown](./skills/terraform-ecs-capacity-provider-staged-teardown/SKILL.md) | skill | Claude, Codex | Tear down an ECS-on-EC2 capacity-provider stack when one apply deadlocks on `ResourceInUseException`: destroy order is reverse-dependency, so compute tears down before the workload; split into two sequential untargeted applies, workload first |
| [gh-pr-merge-delete-branch-closes-dependent-pr](./skills/gh-pr-merge-delete-branch-closes-dependent-pr/SKILL.md) | skill | Claude, Codex | Stacked PRs: merging the upstream PR with branch deletion auto-CLOSES the dependent PR instead of retargeting it, and `gh pr reopen` then fails because the base ref is gone; recover by recreating the ref, or prevent by retargeting downstream PRs first |
| [`skillz` plugin](./plugins/skillz/) | plugin | Claude, Codex | Bundle: every skill except those of hooked plugins (`secrets-in-agent-sessions`, `tamarian`, `continuous-learning`) - install those plugins directly |
| [`pr-loop` plugin](./plugins/pr-loop/) | plugin | Claude, Codex | Paired author + reviewer PR-loop skills |
| [`work-on-pr` plugin](./plugins/work-on-pr/) | plugin | Claude, Codex | Single-skill plugin: work-on-pr |
| [`review-pr-loop` plugin](./plugins/review-pr-loop/) | plugin | Claude, Codex | Single-skill plugin: review-pr-loop |
| [`cmux-search` plugin](./plugins/cmux-search/) | plugin | Claude, Codex | Single-skill plugin: search all open cmux panes |
| [`cmux-agent-tabs` plugin](./plugins/cmux-agent-tabs/) | plugin | Claude, Codex | Single-skill plugin: cmux-agent-tabs |
| [`python-ast-static-analyzer-scoping` plugin](./plugins/python-ast-static-analyzer-scoping/) | plugin | Claude, Codex | Single-skill plugin: python-ast-static-analyzer-scoping |
| [`wordpress-com-publish` plugin](./plugins/wordpress-com-publish/) | plugin | Claude, Codex | Single-skill plugin: WordPress.com token + publish |
| [`git-worktree-convention` plugin](./plugins/git-worktree-convention/) | plugin | Claude, Codex | Single-skill plugin: git-worktree-convention |
| [`git-graft-worktree-onto-remote` plugin](./plugins/git-graft-worktree-onto-remote/) | plugin | Claude, Codex | Single-skill plugin: git-graft-worktree-onto-remote |
| [`multi-phase-feature-pr-worktrees` plugin](./plugins/multi-phase-feature-pr-worktrees/) | plugin | Claude, Codex | Single-skill plugin: multi-phase-feature-pr-worktrees |
| [`gist-to-repo-migration` plugin](./plugins/gist-to-repo-migration/) | plugin | Claude, Codex | Single-skill plugin: gist-to-repo-migration |
| [`neon-vercel-db-identify-and-migrate` plugin](./plugins/neon-vercel-db-identify-and-migrate/) | plugin | Claude, Codex | Single-skill plugin: neon-vercel-db-identify-and-migrate |
| [`claude-code-codex-plugin-parity` plugin](./plugins/claude-code-codex-plugin-parity/) | plugin | Claude, Codex | Single-skill plugin: claude-code-codex-plugin-parity |
| [`claude-code-plugin-from-existing-repo` plugin](./plugins/claude-code-plugin-from-existing-repo/) | plugin | Claude, Codex | Single-skill plugin: claude-code-plugin-from-existing-repo |
| [`claude-code-plugin-python-bootstrap` plugin](./plugins/claude-code-plugin-python-bootstrap/) | plugin | Claude, Codex | Single-skill plugin: claude-code-plugin-python-bootstrap |
| [`claude-code-plugin-update-flow` plugin](./plugins/claude-code-plugin-update-flow/) | plugin | Claude, Codex | Single-skill plugin: claude-code-plugin-update-flow |
| [`claude-code-plugin-release-automation` plugin](./plugins/claude-code-plugin-release-automation/) | plugin | Claude, Codex | Single-skill plugin: claude-code-plugin-release-automation |
| [`claude-json-mcp-migration-slice` plugin](./plugins/claude-json-mcp-migration-slice/) | plugin | Claude, Codex | Single-skill plugin: claude-json-mcp-migration-slice |
| [`continuous-learning` plugin](./plugins/continuous-learning/) | plugin | Codex | Single-skill plugin (no hooks) |
| [`playwright-mcp-upload-hidden-file-input` plugin](./plugins/playwright-mcp-upload-hidden-file-input/) | plugin | Claude, Codex | Single-skill plugin: playwright-mcp-upload-hidden-file-input |
| [`codex-continuous-learning` plugin](./plugins/codex-continuous-learning/) | plugin | Codex | continuous-learning skill plus UserPromptSubmit + Stop hooks |
| [`agent-team-orchestration` plugin](./plugins/agent-team-orchestration/) | plugin | Claude, Codex | Single-skill plugin: agent-team-orchestration |
| [`istio-multicluster-endpointless-mesh-service` plugin](./plugins/istio-multicluster-endpointless-mesh-service/) | plugin | Claude, Codex | Single-skill plugin: istio-multicluster-endpointless-mesh-service |
| [`pre-open-source-credential-audit` plugin](./plugins/pre-open-source-credential-audit/) | plugin | Claude, Codex | Single-skill plugin: pre-open-source-credential-audit |
| [`agent-session-credential-audit` plugin](./plugins/agent-session-credential-audit/) | plugin | Claude, Codex | Single-skill plugin: agent-session-credential-audit |
| [`prevent-committing-secrets` plugin](./plugins/prevent-committing-secrets/) | plugin | Claude, Codex | Single-skill plugin: prevent-committing-secrets |
| [`terraform-state-version-apply-forensics` plugin](./plugins/terraform-state-version-apply-forensics/) | plugin | Claude, Codex | Single-skill plugin: terraform-state-version-apply-forensics |
| [`terraform-ecs-capacity-provider-staged-teardown` plugin](./plugins/terraform-ecs-capacity-provider-staged-teardown/) | plugin | Claude, Codex | Single-skill plugin: terraform-ecs-capacity-provider-staged-teardown |
| [`gh-pr-merge-delete-branch-closes-dependent-pr` plugin](./plugins/gh-pr-merge-delete-branch-closes-dependent-pr/) | plugin | Claude, Codex | Single-skill plugin: gh-pr-merge-delete-branch-closes-dependent-pr |
| [`codex-adversarial-pr-review` plugin](./plugins/codex-adversarial-pr-review/) | plugin | Claude, Codex | Single-skill plugin: codex-adversarial-pr-review |
| [pr-loop](./collections/pr-loop.json) | collection (legacy) | Claude, Codex | `install.sh` selector. Prefer the `pr-loop` plugin entry. |
| [cmux-session-restore-forensics](./skills/cmux-session-restore-forensics/SKILL.md) | skill | Claude, Codex | Diagnose what cmux actually restored after a relaunch and recover panes it silently dropped: the Core Data epoch in `closedAt`, why `workspaceId` diffing is useless, and replaying a pane's stored `resumeBinding` via `cmux new-workspace` |
| [`cmux-session-restore-forensics` plugin](./plugins/cmux-session-restore-forensics/) | plugin | Claude, Codex | Single-skill plugin: cmux-session-restore-forensics |
| [spring-profile-config-overlay-dedupe](./skills/spring-profile-config-overlay-dedupe/SKILL.md) | skill | Claude, Codex | Strip an `application-<profile>.yml` to real overrides and prove the effective config is unchanged; when a duplicate should deliberately stay |
| [`spring-profile-config-overlay-dedupe` plugin](./plugins/spring-profile-config-overlay-dedupe/) | plugin | Claude, Codex | Single-skill plugin: spring-profile-config-overlay-dedupe |
| [spa-request-capture-and-block](./skills/spa-request-capture-and-block/SKILL.md) | skill | Claude, Codex | Capture the exact outbound request body a single-page app sends and block it before it leaves the browser: patch `window.fetch` **and** `XMLHttpRequest` together (the XHR half is the one usually missed, so a fetch-only wrapper lets the request through), read the parsed payload off `window`, disarm with a reload, and why a hash-route change does not remove the patch — for actions whose side effect costs credits or creates an irreversible record |
| [`spa-request-capture-and-block` plugin](./plugins/spa-request-capture-and-block/) | plugin | Claude, Codex | Single-skill plugin: spa-request-capture-and-block |
| [us-federal-open-data-claim-verification](./skills/us-federal-open-data-claim-verification/SKILL.md) | skill | Claude, Codex | Verify quantitative claims about US federal grants/awards/revenue against NIH RePORTER, USAspending and Treasury FiscalData |
| [`us-federal-open-data-claim-verification` plugin](./plugins/us-federal-open-data-claim-verification/) | plugin | Claude, Codex | Single-skill plugin: us-federal-open-data-claim-verification |
| [verbatim-social-post-retrieval](./skills/verbatim-social-post-retrieval/SKILL.md) | skill | Claude, Codex | Retrieve verbatim Truth Social / X posts, including deleted ones, for fact-checking |
| [`verbatim-social-post-retrieval` plugin](./plugins/verbatim-social-post-retrieval/) | plugin | Claude, Codex | Single-skill plugin: verbatim-social-post-retrieval |
| [chrome-localhost-mic-autoblock](./skills/chrome-localhost-mic-autoblock/SKILL.md) | skill | Claude, Codex | Chrome mic fails with `not-allowed` on localhost even though the OS granted Chrome mic access: Chrome auto-blocks the mic per-site and the OS Privacy toggle / restart never clears it; set the site to Allow at `chrome://settings/content/microphone` |
| [`chrome-localhost-mic-autoblock` plugin](./plugins/chrome-localhost-mic-autoblock/) | plugin | Claude, Codex | Single-skill plugin: chrome-localhost-mic-autoblock |
| [metrics-zero-provenance-audit](./skills/metrics-zero-provenance-audit/SKILL.md) | skill | Claude, Codex | A `0` in a multi-source metrics schema usually means the source never populates the field, not that you did not do it |
| [`metrics-zero-provenance-audit` plugin](./plugins/metrics-zero-provenance-audit/) | plugin | Claude, Codex | Single-skill plugin: metrics-zero-provenance-audit |
| [agent-host-skill-loading](./skills/agent-host-skill-loading/SKILL.md) | skill | Claude, Codex | Teach a third agent host (custom loop, Slack bot, service) to load this catalog: menu line in the prompt + `load_skill` tool, path precedence, gated reload |
| [litellm-custom-provider-dispatch-order](./skills/litellm-custom-provider-dispatch-order/SKILL.md) | skill | Claude, Codex | A LiteLLM `CustomLLM` that never runs: seven bare-model-name branches dispatch before the custom-provider one, so `myprovider/gpt-5.5` is silently billed to OpenAI |
| [secretsmanager-prove-no-consumer-before-destroy](./skills/secretsmanager-prove-no-consumer-before-destroy/SKILL.md) | skill | Claude, Codex | Prove nothing consumes a Secrets Manager secret before a terraform destroy: per-resource CloudTrail lookup + `GetSecretValue`-vs-metadata classification, minus your own terraform refresh — because a populated `LastAccessedDate` is **not** evidence of use (a secret with zero `GetSecretValue` still reports one) |
| [`secretsmanager-prove-no-consumer-before-destroy` plugin](./plugins/secretsmanager-prove-no-consumer-before-destroy/) | plugin | Claude, Codex | Single-skill plugin: secretsmanager-prove-no-consumer-before-destroy |
| [github-oidc-immutable-subject-claim](./skills/github-oidc-immutable-subject-claim/SKILL.md) | skill | Claude, Codex | A GitHub Actions job cannot assume an AWS role by OIDC (`Not authorized to perform sts:AssumeRoleWithWebIdentity`) while every sibling repo in the same org assumes the same role fine — GitHub now issues an immutable `sub` (`repo:ORG@ORG_ID/REPO@REPO_ID`) that a `repo:ORG/*` trust policy cannot match, **per repo**, depending on when it was created |
| [`github-oidc-immutable-subject-claim` plugin](./plugins/github-oidc-immutable-subject-claim/) | plugin | Claude, Codex | Single-skill plugin: github-oidc-immutable-subject-claim |
| [parallel-agent-session-collisions](./skills/parallel-agent-session-collisions/SKILL.md) | skill | Claude, Codex | Avoid duplicating, superseding, or clobbering work done by another agent session on the same repos: the three collision shapes, the pre-flight check for each, and how to reconcile |
| [claude-code-cross-session-messaging](./skills/claude-code-cross-session-messaging/SKILL.md) | skill | Claude, Codex | Message a Claude Code session that is already running via native `ListAgents` + `SendMessage`; idle-subscription instead of polling, and the no-TTY law that wedges headless/in-process transports |
| [cmux-cross-session-visibility](./skills/cmux-cross-session-visibility/SKILL.md) | skill | Claude, Codex | Make agent-to-agent traffic visible: structured `SendMessage` summary envelope + a cmux sidebar status pill per workspace, and what must clear a stale pill |
| [subagent-no-report-channel](./skills/subagent-no-report-channel/SKILL.md) | skill | Claude, Codex | Subagents idle with nothing delivered: recover the stranded result from the transcript or the job runtime's state dir, and use `tool_use` without `tool_result` as the real wedge oracle |
| [cmux-session-self-identity](./skills/cmux-session-self-identity/SKILL.md) | skill | Claude, Codex | Which workspace/tab am I in? `cmux identify` + `tree`, because the env vars conflate tab with workspace and go stale on resume |
| [agent-traffic-log](./skills/agent-traffic-log/SKILL.md) | skill | Claude, Codex | Append-only JSONL log of agent-to-agent traffic + a live pane; lock-free concurrent appends, and `xs status` derives who is blocked from the events |
| [terraform-noninteractive-prod-apply](./skills/terraform-noninteractive-prod-apply/SKILL.md) | skill | Claude, Codex | Non-interactive terraform **prod** apply when `apply.sh` has no `-auto-approve`: use `plan -out` + `apply <file>`, not `echo yes \|`, because a prompt-piped apply approves a plan terraform **recomputes** rather than the one you reviewed |
| [cmux-config-silent-drop-triage](./skills/cmux-config-silent-drop-triage/SKILL.md) | skill | Claude, Codex | A cmux.json entry passes `config doctor` but never appears: doctor is syntax-only, so bisect the backups and read the `[CmuxConfig]` diagnostics and enum values off the binary's `strings` |
| [alb-per-rule-traffic-attribution](./skills/alb-per-rule-traffic-attribution/SKILL.md) | skill | Claude, Codex | ALB publishes no per-listener-rule CloudWatch metric; access logs answer it, but `matched_rule_priority` is a position that renumbers when a rule is inserted - attribute by `request_url` + `user_agent` |
| [cmux-claude-codex-cross-runtime-messaging](./skills/cmux-claude-codex-cross-runtime-messaging/SKILL.md) | skill | Claude, Codex | Claude Code <-> Codex CLI agents as messaging peers in cmux: `cmux send` transport, self-named tabs, both sides in the traffic log, where the three transcripts live |
| [`alb-per-rule-traffic-attribution` plugin](./plugins/alb-per-rule-traffic-attribution/) | plugin | Claude, Codex | Single-skill plugin: alb-per-rule-traffic-attribution |
| [`cmux-claude-codex-cross-runtime-messaging` plugin](./plugins/cmux-claude-codex-cross-runtime-messaging/) | plugin | Claude, Codex | Single-skill plugin: cmux-claude-codex-cross-runtime-messaging |
| [tamarian](./skills/tamarian/SKILL.md) | skill | Claude | Tamarian mode: Claude speaks as the Children of Tama - metaphor and allusion carry the meaning, the technical substance stays literal; `/tamarian lite\|full\|ultra\|off`, phrasebook in `LEXICON.md` |
| [`tamarian` plugin](./plugins/tamarian/) | plugin | Claude | tamarian skill plus SessionStart + UserPromptSubmit hooks that persist the level across sessions |
| [chrome-not-secure-tls-interception](./skills/chrome-not-secure-tls-interception/SKILL.md) | skill | Claude, Codex | Chrome 'not secure' behind a TLS-inspecting proxy: CLI checks miss the PAC, and the forged zero-SCT cert is steady state, usually not the cause. |
| [cloudwatch-per-host-stat-single-host-vs-fleet](./skills/cloudwatch-per-host-stat-single-host-vs-fleet/SKILL.md) | skill | Claude, Codex | Max/Sum over a per-host gauge: is this number one host'\''s story or the fleet'\''s - answered from the metric alone, before any dashboard exists. |
| [client-rendered-dashboard-data-blob](./skills/client-rendered-dashboard-data-blob/SKILL.md) | skill | Claude, Codex | Decode a client-rendered dashboard'\''s embedded data blob instead of scraping the DOM or reaching for a headless browser. |
| [claude-ai-conversation-history-search](./skills/claude-ai-conversation-history-search/SKILL.md) | skill | Claude, Codex | Export and grep your own claude.ai conversation history: manifest exports, one-time URLs, the Cloudflare 403, and conversations.json search. |
| [git-worktree-add-relative-path-nests-inside-repo](./skills/git-worktree-add-relative-path-nests-inside-repo/SKILL.md) | skill | Claude, Codex | git worktree add with a relative path nests the worktree inside the repo - why, and how to relocate it with git worktree move. |
| [targetgroupbinding-unattached-tg-readiness-wedge](./skills/targetgroupbinding-unattached-tg-readiness-wedge/SKILL.md) | skill | Claude, Codex | A TargetGroupBinding on a target group no listener forwards to wedges every future rollout: the readiness gate that can never pass, and the PDB fallout. |
| [alb-controller-custom-sg-narrowing-inert](./skills/alb-controller-custom-sg-narrowing-inert/SKILL.md) | skill | Claude, Codex | A custom SG on an ALB ingress narrows nothing while the controller'\''s backend SG stays attached - SGs are additive; the real fix and its ordering traps. |
| [cloudwatch-metric-filter-dimensions-default-value-exclusive](./skills/cloudwatch-metric-filter-dimensions-default-value-exclusive/SKILL.md) | skill | Claude, Codex | Metric filter with dimensions AND default_value passes validate and plan, fails only at apply - and which of the two to drop. |
| [terraform-check-block-warn-only-ci-gate](./skills/terraform-check-block-warn-only-ci-gate/SKILL.md) | skill | Claude, Codex | Terraform check blocks only warn - plan exits 0 in CI; the tee+pipefail+grep pattern that turns a check into a real gate. |
| [mcp-language-server-orphan-fd-exhaustion](./skills/mcp-language-server-orphan-fd-exhaustion/SKILL.md) | skill | Claude, Codex | ENFILE file-table overflow from orphaned mcp-language-server processes: the sysctl+lsof diagnosis and the safe pkill recovery. |
| [rxjava-dofinally-terminal-then-finally-test-race](./skills/rxjava-dofinally-terminal-then-finally-test-race/SKILL.md) | skill | Claude, Codex | TestObserver.await returns before doFinally runs - the terminal-then-finally ordering that makes post-await gauge asserts racy, and the polling fix. |
| [personal-skills-shadow-bundle-audit](./skills/personal-skills-shadow-bundle-audit/SKILL.md) | skill | Claude, Codex | Audit ~/.claude/skills copies that shadow plugin-bundle skills: the three-directory model, the drift table, and the delete-vs-fork decision tree. |
| [session-transcript-mining](./skills/session-transcript-mining/SKILL.md) | skill | Claude, Codex | Mine all local Claude Code session transcripts for skills: inventory, condense 26-90x, fan out miners, tier the findings, ship serially. |
| [pr-amend-force-push-lost-to-racing-merge](./skills/pr-amend-force-push-lost-to-racing-merge/SKILL.md) | skill | Claude, Codex | An amend force-pushed after the reviewer'\''s squash-merge vanishes silently - detection, recovery, and the auto-merge disarm. |
| [archive-today-fetcher-hierarchy](./skills/archive-today-fetcher-hierarchy/SKILL.md) | skill | Claude, Codex | Reach archive.today when automation is refused, cite it reproducibly, and send a truthful user agent |
| [`archive-today-fetcher-hierarchy` plugin](./plugins/archive-today-fetcher-hierarchy/) | plugin | Claude, Codex | Single-skill plugin: archive-today-fetcher-hierarchy |
| [aws-http-server-on-lambda-web-adapter](./skills/aws-http-server-on-lambda-web-adapter/SKILL.md) | skill | Claude, Codex | Host an unmodified HTTP server (incl |
| [`aws-http-server-on-lambda-web-adapter` plugin](./plugins/aws-http-server-on-lambda-web-adapter/) | plugin | Claude, Codex | Single-skill plugin: aws-http-server-on-lambda-web-adapter |
| [confluence-rovo-mcp-readonly-rest-fallback](./skills/confluence-rovo-mcp-readonly-rest-fallback/SKILL.md) | skill | Claude, Codex | Create or update a Confluence Cloud page when the Atlassian Rovo connector is read-only - but check first that it still is, since the connector gets re-authorized and a writable site needs none of... |
| [`confluence-rovo-mcp-readonly-rest-fallback` plugin](./plugins/confluence-rovo-mcp-readonly-rest-fallback/) | plugin | Claude, Codex | Single-skill plugin: confluence-rovo-mcp-readonly-rest-fallback |
| [git-pr-merge-unblock](./skills/git-pr-merge-unblock/SKILL.md) | skill | Claude, Codex | Work out why a pull request will not merge and who can actually unblock it, on github.com or self-hosted GitHub Enterprise |
| [`git-pr-merge-unblock` plugin](./plugins/git-pr-merge-unblock/) | plugin | Claude, Codex | Single-skill plugin: git-pr-merge-unblock |
| [git-simulate-sequential-merges](./skills/git-simulate-sequential-merges/SKILL.md) | skill | Claude, Codex | Determine which merges in a queue of N branches actually conflict, and preview the fully-merged file content, using merge-tree --write-tree chained through commit-tree - no refs, worktrees, index... |
| [`git-simulate-sequential-merges` plugin](./plugins/git-simulate-sequential-merges/) | plugin | Claude, Codex | Single-skill plugin: git-simulate-sequential-merges |
| [github-actions-startup-failure-triage](./skills/github-actions-startup-failure-triage/SKILL.md) | skill | Claude, Codex | Tell a GitHub Actions outage apart from a workflow file you broke, and get the PR unstuck without bypassing branch protection |
| [`github-actions-startup-failure-triage` plugin](./plugins/github-actions-startup-failure-triage/) | plugin | Claude, Codex | Single-skill plugin: github-actions-startup-failure-triage |
| [agent-credential-leak-surfaces](./skills/agent-credential-leak-surfaces/SKILL.md) | skill | Claude, Codex | Find and clean the seven local surfaces where a coding agent accumulates copies of your secrets (git remote URLs, memory stores, file-history snapshots, tool config literals, |
| [`agent-credential-leak-surfaces` plugin](./plugins/agent-credential-leak-surfaces/) | plugin | Claude, Codex | Single-skill plugin: agent-credential-leak-surfaces |
| [`agent-host-skill-loading` plugin](./plugins/agent-host-skill-loading/) | plugin | Claude, Codex | Single-skill plugin: agent-host-skill-loading |
| [`agent-traffic-log` plugin](./plugins/agent-traffic-log/) | plugin | Claude, Codex | Single-skill plugin: agent-traffic-log |
| [`alb-controller-custom-sg-narrowing-inert` plugin](./plugins/alb-controller-custom-sg-narrowing-inert/) | plugin | Claude, Codex | Single-skill plugin: alb-controller-custom-sg-narrowing-inert |
| [`chrome-not-secure-tls-interception` plugin](./plugins/chrome-not-secure-tls-interception/) | plugin | Claude, Codex | Single-skill plugin: chrome-not-secure-tls-interception |
| [`claude-ai-conversation-history-search` plugin](./plugins/claude-ai-conversation-history-search/) | plugin | Claude, Codex | Single-skill plugin: claude-ai-conversation-history-search |
| [`claude-code-cross-session-messaging` plugin](./plugins/claude-code-cross-session-messaging/) | plugin | Claude, Codex | Single-skill plugin: claude-code-cross-session-messaging |
| [`claude-code-plugin-publish-anthropic-marketplace` plugin](./plugins/claude-code-plugin-publish-anthropic-marketplace/) | plugin | Claude, Codex | Single-skill plugin: claude-code-plugin-publish-anthropic-marketplace |
| [`claudeception` plugin](./plugins/claudeception/) | plugin | Claude, Codex | Single-skill plugin: claudeception |
| [`client-rendered-dashboard-data-blob` plugin](./plugins/client-rendered-dashboard-data-blob/) | plugin | Claude, Codex | Single-skill plugin: client-rendered-dashboard-data-blob |
| [`cloudwatch-metric-filter-dimensions-default-value-exclusive` plugin](./plugins/cloudwatch-metric-filter-dimensions-default-value-exclusive/) | plugin | Claude, Codex | Single-skill plugin: cloudwatch-metric-filter-dimensions-default-value-exclusive |
| [`cloudwatch-per-host-stat-single-host-vs-fleet` plugin](./plugins/cloudwatch-per-host-stat-single-host-vs-fleet/) | plugin | Claude, Codex | Single-skill plugin: cloudwatch-per-host-stat-single-host-vs-fleet |
| [`cmux-autoresume-after-reboot` plugin](./plugins/cmux-autoresume-after-reboot/) | plugin | Claude, Codex | Single-skill plugin: cmux-autoresume-after-reboot |
| [`cmux-config-silent-drop-triage` plugin](./plugins/cmux-config-silent-drop-triage/) | plugin | Claude, Codex | Single-skill plugin: cmux-config-silent-drop-triage |
| [`cmux-cross-session-visibility` plugin](./plugins/cmux-cross-session-visibility/) | plugin | Claude, Codex | Single-skill plugin: cmux-cross-session-visibility |
| [`cmux-session-self-identity` plugin](./plugins/cmux-session-self-identity/) | plugin | Claude, Codex | Single-skill plugin: cmux-session-self-identity |
| [`git-worktree-add-relative-path-nests-inside-repo` plugin](./plugins/git-worktree-add-relative-path-nests-inside-repo/) | plugin | Claude, Codex | Single-skill plugin: git-worktree-add-relative-path-nests-inside-repo |
| [launchd-env-sync-session-leak](./skills/launchd-env-sync-session-leak/SKILL.md) | skill | Claude, Codex | Diagnose and undo a login-environment -> launchd sync that was run from inside a multiplexer pane or an AI-agent session, so PROMPT_COMMAND, CMUX_*, CLAUDECODE/CLAUDE_CODE_*, |
| [`launchd-env-sync-session-leak` plugin](./plugins/launchd-env-sync-session-leak/) | plugin | Claude, Codex | Single-skill plugin: launchd-env-sync-session-leak |
| [`litellm-custom-provider-dispatch-order` plugin](./plugins/litellm-custom-provider-dispatch-order/) | plugin | Claude, Codex | Single-skill plugin: litellm-custom-provider-dispatch-order |
| [llm-vendor-waterfall](./skills/llm-vendor-waterfall/SKILL.md) | skill | Claude, Codex | Serve one LLM call from an ordered list of vendors so a rate limit, a dead key, or an out-of-credits account fails over instead of failing the request |
| [`llm-vendor-waterfall` plugin](./plugins/llm-vendor-waterfall/) | plugin | Claude, Codex | Single-skill plugin: llm-vendor-waterfall |
| [`macos-sparkle-update-quarantine-relaunch` plugin](./plugins/macos-sparkle-update-quarantine-relaunch/) | plugin | Claude, Codex | Single-skill plugin: macos-sparkle-update-quarantine-relaunch |
| [`mcp-language-server-orphan-fd-exhaustion` plugin](./plugins/mcp-language-server-orphan-fd-exhaustion/) | plugin | Claude, Codex | Single-skill plugin: mcp-language-server-orphan-fd-exhaustion |
| [openclaw-model-cascade-debugging](./skills/openclaw-model-cascade-debugging/SKILL.md) | skill | Claude, Codex | Diagnose OpenClaw model-cascade failures (gateway process up but every run FailoverErrors because all providers are down), build a free OpenRouter fallback basket to survive |
| [`openclaw-model-cascade-debugging` plugin](./plugins/openclaw-model-cascade-debugging/) | plugin | Claude, Codex | Single-skill plugin: openclaw-model-cascade-debugging |
| [`parallel-agent-session-collisions` plugin](./plugins/parallel-agent-session-collisions/) | plugin | Claude, Codex | Single-skill plugin: parallel-agent-session-collisions |
| [`personal-skills-shadow-bundle-audit` plugin](./plugins/personal-skills-shadow-bundle-audit/) | plugin | Claude, Codex | Single-skill plugin: personal-skills-shadow-bundle-audit |
| [`pr-amend-force-push-lost-to-racing-merge` plugin](./plugins/pr-amend-force-push-lost-to-racing-merge/) | plugin | Claude, Codex | Single-skill plugin: pr-amend-force-push-lost-to-racing-merge |
| [`rxjava-dofinally-terminal-then-finally-test-race` plugin](./plugins/rxjava-dofinally-terminal-then-finally-test-race/) | plugin | Claude, Codex | Single-skill plugin: rxjava-dofinally-terminal-then-finally-test-race |
| [secrets-in-agent-sessions](./skills/secrets-in-agent-sessions/SKILL.md) | skill | Claude, Codex | Handle credentials during a coding-agent session without writing them into the transcript, tool-output cache, permission allowlist or logs |
| [`secrets-in-agent-sessions` plugin](./plugins/secrets-in-agent-sessions/) | plugin | Claude, Codex | Single-skill plugin: secrets-in-agent-sessions |
| [`session-transcript-mining` plugin](./plugins/session-transcript-mining/) | plugin | Claude, Codex | Single-skill plugin: session-transcript-mining |
| [slack-app-token-rotation](./skills/slack-app-token-rotation/SKILL.md) | skill | Claude, Codex | Actually rotate a leaked Slack bot or app-level token: |
| [`slack-app-token-rotation` plugin](./plugins/slack-app-token-rotation/) | plugin | Claude, Codex | Single-skill plugin: slack-app-token-rotation |
| [slack-xoxc-session-client](./skills/slack-xoxc-session-client/SKILL.md) | skill | Claude, Codex | Drive the Slack web API as yourself via a live browser session (xoxc token + httpOnly d cookie) when you cannot install a Slack app; ships a runnable Python client that |
| [`slack-xoxc-session-client` plugin](./plugins/slack-xoxc-session-client/) | plugin | Claude, Codex | Single-skill plugin: slack-xoxc-session-client |
| [`subagent-no-report-channel` plugin](./plugins/subagent-no-report-channel/) | plugin | Claude, Codex | Single-skill plugin: subagent-no-report-channel |
| [`targetgroupbinding-unattached-tg-readiness-wedge` plugin](./plugins/targetgroupbinding-unattached-tg-readiness-wedge/) | plugin | Claude, Codex | Single-skill plugin: targetgroupbinding-unattached-tg-readiness-wedge |
| [`terraform-check-block-warn-only-ci-gate` plugin](./plugins/terraform-check-block-warn-only-ci-gate/) | plugin | Claude, Codex | Single-skill plugin: terraform-check-block-warn-only-ci-gate |
| [`terraform-noninteractive-prod-apply` plugin](./plugins/terraform-noninteractive-prod-apply/) | plugin | Claude, Codex | Single-skill plugin: terraform-noninteractive-prod-apply |
| [claude-transcript-permission-mining](./skills/claude-transcript-permission-mining/SKILL.md) | skill | Claude, Codex | Count permission outcomes (auto-mode refusals, operator rejections) from Claude Code transcripts without the traps that corrupt the number while leaving the output plausible: |
| [`claude-transcript-permission-mining` plugin](./plugins/claude-transcript-permission-mining/) | plugin | Claude, Codex | Single-skill plugin: claude-transcript-permission-mining |
| [codex-hook-wire-schema-from-binary](./skills/codex-hook-wire-schema-from-binary/SKILL.md) | skill | Claude, Codex | Read the Codex CLI hook contract out of the shipped native binary with strings rather than a live probe turn: |
| [`codex-hook-wire-schema-from-binary` plugin](./plugins/codex-hook-wire-schema-from-binary/) | plugin | Claude, Codex | Single-skill plugin: codex-hook-wire-schema-from-binary |
| [credential-redactor-audit](./skills/credential-redactor-audit/SKILL.md) | skill | Claude, Codex | Audit a credential-redaction layer you own: find the holes a normal test suite misses (fixtures that hide the bug, patterns that bypass the value guard, dropped overlap spans, non-idempotence, backwards allow-lists, fail-open imports), then scrub what already leaked |
| [`credential-redactor-audit` plugin](./plugins/credential-redactor-audit/) | plugin | Claude, Codex | Single-skill plugin: credential-redactor-audit |
| [git-default-branch-detection](./skills/git-default-branch-detection/SKILL.md) | skill | Claude, Codex | Detect a repo's real default branch; `init.defaultBranch` is a preference for repos that don't exist yet, not the answer |
| [`git-default-branch-detection` plugin](./plugins/git-default-branch-detection/) | plugin | Claude, Codex | Single-skill plugin: git-default-branch-detection |
| [macos-sandbox-exec-agent-command-confinement](./skills/macos-sandbox-exec-agent-command-confinement/SKILL.md) | skill | Claude, Codex | Confine agent-run commands to one tree with macOS sandbox-exec |
| [`macos-sandbox-exec-agent-command-confinement` plugin](./plugins/macos-sandbox-exec-agent-command-confinement/) | plugin | Claude, Codex | Single-skill plugin: macos-sandbox-exec-agent-command-confinement |
| [cmux-runbook-in-sibling-tab](./skills/cmux-runbook-in-sibling-tab/SKILL.md) | skill | Claude, Codex | Drive a runbook step by step in a sibling cmux terminal tab: receipts per step, irreversible steps staged for a human Enter; ships `cmux-step` + the YOLT rule |
| [`cmux-runbook-in-sibling-tab` plugin](./plugins/cmux-runbook-in-sibling-tab/) | plugin | Claude, Codex | Single-skill plugin: cmux-runbook-in-sibling-tab |
| [experimental-upstream-for-gated-integration-repo](./skills/experimental-upstream-for-gated-integration-repo/SKILL.md) | skill | Claude, Codex | Keep a high-velocity development loop alive when the repository you integrate into gains a merge gate you cannot satisfy and forking is disabled: experimental upstream, one reviewed fork-sync PR, pre-push guard, change-management issue framing |
| [`experimental-upstream-for-gated-integration-repo` plugin](./plugins/experimental-upstream-for-gated-integration-repo/) | plugin | Claude, Codex | Single-skill plugin: experimental-upstream-for-gated-integration-repo |
| [`oauth-mint-counting-passthrough-proxy` plugin](./plugins/oauth-mint-counting-passthrough-proxy/) | plugin | Claude, Codex | Single-skill plugin: oauth-mint-counting-passthrough-proxy |

Machine-readable index: [`catalog.json`](./catalog.json). The
installer and validation script both read from it, so new entries
land in the docs and tooling at the same time.

## Layout

```
catalog.json                       # machine-readable catalog index
collections/
  pr-loop.json                     # legacy install.sh selector (kept for backcompat)
skills/                            # canonical skill content
  work-on-pr/SKILL.md
  review-pr-loop/SKILL.md
  continuous-learning/SKILL.md
  cmux-search/SKILL.md
  gh-git-heredoc-body-file/SKILL.md
  claude-code-static-allow-bypasses-hook/SKILL.md
  python-ast-static-analyzer-scoping/SKILL.md
  wordpress-com-publish/SKILL.md
  git-add-u-rename-pitfall/SKILL.md
  git-branch-cleanup-script-races/SKILL.md
  git-worktree-convention/SKILL.md
  git-graft-worktree-onto-remote/SKILL.md
  multi-phase-feature-pr-worktrees/SKILL.md
  gist-to-repo-migration/SKILL.md
  vercel-token-deploy-branch-domains/SKILL.md
  s3-presigned-upload-fails-nonexistent-bucket/SKILL.md
  neon-vercel-db-identify-and-migrate/SKILL.md
  gh-api-f-vs-F-body-file/SKILL.md
  gh-api-jq-no-arg/SKILL.md
  gh-fork-issues-disabled/SKILL.md
  gh-pr-graphql-401-rest-fallback/SKILL.md
  gh-pr-merge-delete-branch-closes-dependent-pr/SKILL.md
  gh-workflow-run-matching/SKILL.md
  github-api-list-endpoint-staleness-fresh-pr/SKILL.md
  github-closing-keywords-default-branch-only/SKILL.md
  github-private-repo-readme-image-rendering/SKILL.md
  claude-code-claudemd-symlink-write-refused/SKILL.md
  claude-code-codex-plugin-parity/SKILL.md
  claude-code-piebald-lsp-binary-on-path/SKILL.md
  claude-code-plugin-from-existing-repo/SKILL.md
  claude-code-plugin-python-bootstrap/SKILL.md
  claude-code-plugin-update-flow/SKILL.md
  claude-code-plugin-release-automation/SKILL.md
  claude-json-mcp-migration-slice/SKILL.md
  macos-bash-3.2-compat/SKILL.md
  emacs-batch-package-verify-pitfalls/SKILL.md
  python-symtable-no-col-offset-pairing/SKILL.md
.claude-plugin/
  marketplace.json                 # Claude Code marketplace (lists all plugin entries)
.codex-plugin/
  marketplace.json                 # Codex marketplace (lists all plugin entries)
plugins/                           # per-plugin manifests + skill symlinks
  skillz/                          # full bundle (per-host skill dirs)
    .claude-plugin/plugin.json     # "skills": "./skills-claude/"
    .codex-plugin/plugin.json      # "skills": "./skills-codex/"
    skills-claude/                 # every claude-hosted skill (excludes continuous-learning, codex-only)
      work-on-pr -> ../../../skills/work-on-pr
      claudeception -> ../../../skills/claudeception
      ...                          # symlink per claude-hosted catalog skill
    skills-codex/                  # every codex-hosted skill (excludes claudeception, claude-only)
      work-on-pr -> ../../../skills/work-on-pr
      continuous-learning -> ../../../skills/continuous-learning
      ...                          # symlink per codex-hosted catalog skill
  pr-loop/                         # work-on-pr + review-pr-loop only
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/
      work-on-pr -> ../../../skills/work-on-pr
      review-pr-loop -> ../../../skills/review-pr-loop
  work-on-pr/                      # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/work-on-pr -> ../../../skills/work-on-pr
  review-pr-loop/                  # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/review-pr-loop -> ../../../skills/review-pr-loop
  cmux-search/                     # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/cmux-search -> ../../../skills/cmux-search
  gh-git-heredoc-body-file/        # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-git-heredoc-body-file -> ../../../skills/gh-git-heredoc-body-file
  claude-code-static-allow-bypasses-hook/   # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-static-allow-bypasses-hook -> ../../../skills/claude-code-static-allow-bypasses-hook
  python-ast-static-analyzer-scoping/       # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/python-ast-static-analyzer-scoping -> ../../../skills/python-ast-static-analyzer-scoping
  wordpress-com-publish/           # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/wordpress-com-publish -> ../../../skills/wordpress-com-publish
  git-add-u-rename-pitfall/        # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/git-add-u-rename-pitfall -> ../../../skills/git-add-u-rename-pitfall
  git-branch-cleanup-script-races/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/git-branch-cleanup-script-races -> ../../../skills/git-branch-cleanup-script-races
  git-graft-worktree-onto-remote/  # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/git-graft-worktree-onto-remote -> ../../../skills/git-graft-worktree-onto-remote
  multi-phase-feature-pr-worktrees/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/multi-phase-feature-pr-worktrees -> ../../../skills/multi-phase-feature-pr-worktrees
  gist-to-repo-migration/          # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gist-to-repo-migration -> ../../../skills/gist-to-repo-migration
  vercel-token-deploy-branch-domains/       # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/vercel-token-deploy-branch-domains -> ../../../skills/vercel-token-deploy-branch-domains
  s3-presigned-upload-fails-nonexistent-bucket/  # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/s3-presigned-upload-fails-nonexistent-bucket -> ../../../skills/s3-presigned-upload-fails-nonexistent-bucket
  neon-vercel-db-identify-and-migrate/      # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/neon-vercel-db-identify-and-migrate -> ../../../skills/neon-vercel-db-identify-and-migrate
  gh-api-f-vs-F-body-file/         # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-api-f-vs-F-body-file -> ../../../skills/gh-api-f-vs-F-body-file
  gh-api-jq-no-arg/                # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-api-jq-no-arg -> ../../../skills/gh-api-jq-no-arg
  gh-fork-issues-disabled/         # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-fork-issues-disabled -> ../../../skills/gh-fork-issues-disabled
  gh-pr-graphql-401-rest-fallback/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-pr-graphql-401-rest-fallback -> ../../../skills/gh-pr-graphql-401-rest-fallback
  gh-pr-merge-delete-branch-closes-dependent-pr/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-pr-merge-delete-branch-closes-dependent-pr -> ../../../skills/gh-pr-merge-delete-branch-closes-dependent-pr
  gh-workflow-run-matching/        # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/gh-workflow-run-matching -> ../../../skills/gh-workflow-run-matching
  github-api-list-endpoint-staleness-fresh-pr/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/github-api-list-endpoint-staleness-fresh-pr -> ../../../skills/github-api-list-endpoint-staleness-fresh-pr
  github-closing-keywords-default-branch-only/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/github-closing-keywords-default-branch-only -> ../../../skills/github-closing-keywords-default-branch-only
  github-private-repo-readme-image-rendering/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/github-private-repo-readme-image-rendering -> ../../../skills/github-private-repo-readme-image-rendering
  claude-code-claudemd-symlink-write-refused/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-claudemd-symlink-write-refused -> ../../../skills/claude-code-claudemd-symlink-write-refused
  claude-code-codex-plugin-parity/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-codex-plugin-parity -> ../../../skills/claude-code-codex-plugin-parity
  claude-code-piebald-lsp-binary-on-path/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-piebald-lsp-binary-on-path -> ../../../skills/claude-code-piebald-lsp-binary-on-path
  claude-code-plugin-from-existing-repo/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-plugin-from-existing-repo -> ../../../skills/claude-code-plugin-from-existing-repo
  claude-code-plugin-python-bootstrap/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-plugin-python-bootstrap -> ../../../skills/claude-code-plugin-python-bootstrap
  claude-code-plugin-update-flow/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-plugin-update-flow -> ../../../skills/claude-code-plugin-update-flow
  claude-code-plugin-release-automation/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-code-plugin-release-automation -> ../../../skills/claude-code-plugin-release-automation
  claude-json-mcp-migration-slice/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/claude-json-mcp-migration-slice -> ../../../skills/claude-json-mcp-migration-slice
  macos-bash-3.2-compat/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/macos-bash-3.2-compat -> ../../../skills/macos-bash-3.2-compat
  emacs-batch-package-verify-pitfalls/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/emacs-batch-package-verify-pitfalls -> ../../../skills/emacs-batch-package-verify-pitfalls
  python-symtable-no-col-offset-pairing/ # single-skill plugin
    .claude-plugin/plugin.json
    .codex-plugin/plugin.json
    skills/python-symtable-no-col-offset-pairing -> ../../../skills/python-symtable-no-col-offset-pairing
  continuous-learning/             # Codex-only single-skill plugin (no hooks)
    .codex-plugin/plugin.json
    skills/continuous-learning -> ../../../skills/continuous-learning
  codex-continuous-learning/       # Codex skill + hooks bundle
    .codex-plugin/plugin.json
    skills/continuous-learning -> ../../../skills/continuous-learning
    hooks/
      hooks.json
      continuous_learning_prompt.py
      continuous_learning_stop.py
install.sh                         # catalog-driven installer (legacy / fallback)
scripts/
  validate-catalog.sh              # CI/local catalog validation
README.md
```

Each `plugins/<name>/skills/<skill>` is a symlink back to the
canonical `skills/<skill>/`, so every plugin reads from a single
source of truth. The root `.claude-plugin/marketplace.json` and
`.codex-plugin/marketplace.json` enumerate every plugin entry so
hosts can offer them individually in `/plugin install`.

This repo replaced gist `5f606018eb36a75dc292016268f08e7c`. The full
gist revision history was imported as the first 13 commits on
`master` and the gist now redirects here.

## Install — Claude Code plugin (recommended)

The marketplace exposes every plugin entry individually, so you can
install exactly the subset you want. From inside Claude Code:

```text
/plugin marketplace add voitta-ai/skillz

# Bundle (every skill except those of hooked plugins - see Plugins below):
/plugin install skillz@skillz

# Author + reviewer PR-loop pair:
/plugin install pr-loop@skillz

# Single-skill plugins:
/plugin install work-on-pr@skillz
/plugin install review-pr-loop@skillz
```

Each plugin's `skills/` directory is a set of symlinks back to
`skills/<name>/`, so installing one plugin does not duplicate skill
content on disk.

If you previously installed via `install.sh --target claude`,
remove the old copies to avoid duplicates:

```bash
rm -rf ~/.claude/skills/work-on-pr ~/.claude/skills/review-pr-loop
```

## Install — Codex plugin (recommended)

Requires Codex CLI **0.117.0** or newer. Check with `codex --version`.

From any shell, add this repo as a Codex marketplace:

```bash
codex plugin marketplace add voitta-ai/skillz
```

Then open Codex's plugin browser and install whichever plugin entry
you want from the `skillz` marketplace — same set as Claude Code,
plus two Codex-only entries:

```text
/plugins
```

- `skillz` — full bundle (host-aware: the Claude manifest loads
  `skills-claude/`, the Codex manifest loads `skills-codex/`, so a
  claude-only skill like `claudeception` never lands in a Codex
  install; skills whose own plugin ships hooks are left out of both
  dirs - see [Plugins](#plugins))
- `pr-loop` — work-on-pr + review-pr-loop
- `work-on-pr` — single skill
- `review-pr-loop` — single skill
- `continuous-learning` — single skill, no hooks
- `codex-continuous-learning` — skill + UserPromptSubmit/Stop hooks

From a local checkout, point Codex at the repo root instead:

```bash
codex plugin marketplace add /absolute/path/to/skillz
```

If you add a local checkout, keep that checkout up to date yourself
with `git pull` in the clone.

Remove old direct-copy installs after switching:

```bash
rm -rf ~/.codex/skills/work-on-pr ~/.codex/skills/review-pr-loop
```

## Install — script (legacy / fallback)

`install.sh` predates the per-plugin marketplace entries above. Use
it when the plugin path is unavailable (older Codex, locked Claude
Code config, sandboxed environment) or when you want to drop skills
directly into `~/.claude/skills/` / `~/.codex/skills/` without going
through `/plugin`.

```bash
# Default: install the pr-loop collection (work-on-pr + review-pr-loop)
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh)

# Single skill
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --skill work-on-pr

# Named collection
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --collection pr-loop

# Everything in the catalog
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --all

# Force a target host
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --target codex
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --target claude
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --target both

# Dry-run shows what would happen without writing anything
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh) -- --all --dry-run
```

`--skill` and `--collection` are repeatable. `--target` accepts
`auto` (default), `codex`, `claude`, or `both`. Override the
destination directly with `SKILLS_DEST_ROOT`. `CODEX_HOME` and
`CLAUDE_SKILLS_DIR` are honored.

From a clone:

```bash
git clone https://github.com/voitta-ai/skillz.git /tmp/skillz
/tmp/skillz/install.sh --target both --collection pr-loop
```

Backward compatibility: invoking `install.sh` with no selection
flags installs the `pr-loop` collection, matching the prior default.

## Migrating from `debedb/skillz`

This repo previously lived at
[`debedb/skillz`](https://github.com/debedb/skillz). It has moved
to [`voitta-ai/skillz`](https://github.com/voitta-ai/skillz).
GitHub redirects the old URL indefinitely (until the
`debedb/skillz` name is reused), so existing installs continue to
work without changes. The notes below cover the few cases where a
manual switch is worth doing.

**Script install (`install.sh`).** Re-run the curl one-liner
against the new raw URL — it overwrites in place, same skill paths,
no orphan files:

```bash
bash <(curl -sL https://raw.githubusercontent.com/voitta-ai/skillz/master/install.sh)
```

The old `debedb` URL still resolves via the GitHub redirect, so
nothing breaks if you keep using it; the new URL is just the
canonical one going forward.

**Claude Code plugin.** The redirect also covers `/plugin
marketplace add` / `/plugin update`, so existing installs keep
updating from the renamed repo automatically. To switch the
marketplace entry to the new owner explicitly:

```text
/plugin uninstall skillz@skillz
/plugin marketplace remove skillz
/plugin marketplace add voitta-ai/skillz
/plugin install skillz@skillz
```

**Codex plugin.** Same pattern — the marketplace source URL
redirects, so existing installs keep working. To switch the
configured marketplace entry to the new owner explicitly:

```bash
codex plugin marketplace remove skillz
codex plugin marketplace add voitta-ai/skillz
```

Then reopen `/plugins`, select the `skillz` marketplace, and
reinstall or update the same plugin entry you were already using.

This section will be removed once the rename has aged enough that
nobody is hitting the old URL anymore — see #22.

## Catalog manifest

[`catalog.json`](./catalog.json) is the single source of truth for
what the repo ships. It lists:

- Every skill (`name`, `path`, supported `hosts`, one-line summary).
- Every collection (`name`, member skill names, optional path to a
  per-collection JSON file).
- Plugin bundles (`name`, paths to host manifests).
- A default for the no-arg install (currently `pr-loop`).

`install.sh` parses this file at runtime, so no installer edits are ever
required — but a skill is not a two-file change. It also needs its own plugin
directory and an entry in each host's marketplace, or it ships only inside the
bundle; see [Contributing](#contributing).

## Contributing

### What a new skill consists of

Six places, not one. A skill that exists only in `skills/` installs for nobody:

| Path | Why |
|---|---|
| `skills/<name>/SKILL.md` | the skill itself; YAML frontmatter with `name`, `description`, `version` |
| `plugins/<name>/.claude-plugin/plugin.json` | makes it installable standalone on Claude |
| `plugins/<name>/.codex-plugin/plugin.json` | same for Codex, same version string |
| `plugins/<name>/skills/<name>` | symlink to `../../../skills/<name>` |
| `catalog.json` | `skills[]` entry, `plugins[]` entry — `install.sh` and every gate read this |
| `.claude-plugin/marketplace.json`, `.codex-plugin/marketplace.json` | one entry per host that carries a manifest, or the plugin cannot be installed by name |

Plus a README catalog row (skill + plugin), and the bundle symlinks under
`plugins/skillz/skills-claude/` and `skills-codex/` unless the plugin ships
hooks. `scripts/validate-catalog.sh` checks every one of these and is the
authority; run it before pushing.

End a skill with a `## Related` section — that exact heading — listing sibling
skills as `` - `skill-name` — why you would go there instead ``. It is how a
reader navigates between overlapping skills, and it is the only place a link
checker can resolve names without an allowlist: backticks in ordinary prose are
mostly CLI flags and config keys, so only the **leading** backticked token of a
bullet counts as a reference.

### Which branch to target

**`master` for a single skill or fix that is ready now.** Every merge to master
tags a release, so master is what ships.

**`next` for a batch** — a fleet or teammate run landing several skills at once,
or work that should accumulate before it ships.

The reason there are two is one line of JSON. The bundle version in
`plugins/skillz/.claude-plugin/plugin.json` is a **monotonic counter shared by
every PR**, and CI requires it to advance. Two concurrent skill PRs therefore
cannot both be correct no matter how unrelated their subject matter: whoever
merges second is stale by construction and has to rebase. That gate is already
a lock — a pessimistic one, discovered at merge time as a conflict (issue #188).

`next` moves that collision from N PRs down to one merge-back.

### Rules for a PR onto `next`

- **Do not touch the bundle version.** CI enforces that
  `plugins/skillz/.{claude,codex}-plugin/plugin.json#version` equals *master's*
  — not "unchanged since next", so drift is self-correcting. A PR that bumps it
  fails.
- **Do bump everything else**: each touched skill's frontmatter `version`, and
  both host manifests of every plugin that ships it. Those are independent cache
  keys, never a shared counter, so they cannot collide and are never exempt.
- The bundle bump happens once, at merge-back.

### Merging `next` back into master

Branch off `next`, open a PR into `master`, and merge it as a **merge commit**
rather than a squash, so the individual skill commits survive:

```bash
git fetch origin
git switch -c merge-next-$(date +%F) origin/next
# resolve: bundle version -> master's + 1 minor, catalog conflicts in place
bash scripts/validate-catalog.sh
gh pr create --base master --title "Merge next into master: ..." 
```

One bundle bump for the whole batch, one release. Recent examples: #228, #205.

### Rules for every PR, either branch

- **Edit `catalog.json`, both marketplaces and the README table IN PLACE.**
  Never regenerate or re-sort them. A re-sorted `catalog.json` turns a
  three-line addition into a ~500-line diff that conflicts with every other open
  PR; an in-place append merges cleanly. When a rebase does conflict in those
  four files, resolve them with `python3 scripts/merge-skill-registry.py`
  (see [Rebasing a stale skill branch](#rebasing-a-stale-skill-branch)) rather
  than by hand.
- **Pick the bundle number at merge time, not when you write the branch.** It is
  a counter every open PR competes for, so a number chosen an hour ago is a
  claim on a value someone else has taken. Read it when you are about to land:

```bash
base=$(git show origin/master:plugins/skillz/.claude-plugin/plugin.json | jq -r .version)
next=$(echo "$base" | awk -F. '{printf "%d.%d.0", $1, $2+1}')
```

- **Re-check the bumps after every rebase.** The gate asserts the version
  advanced past the *new* base. If master took the same number while your PR sat
  open, your bump silently becomes a no-op: CI stays green and every installed
  copy stays frozen on the old content. Worse, when master took the *identical*
  change the rebase drops the hunk as already applied, so the bump disappears
  from your diff entirely and there is nothing to notice. Re-read the version
  out of the file after every rebase; do not trust that you set it once.
- Run the three gates locally — they are the same ones CI runs:

```bash
bash scripts/validate-catalog.sh
bash scripts/check-sensitive-terms.sh skills/<name>/
python3 scripts/check-plugin-version-bumps.py origin/master
```

  `hooks/pre-push` runs all three, plus the private name-wordlist half that
  cannot run in public CI. Install it once with
  `git config core.hooksPath hooks`.

## Updating

- **Claude Code plugin:** `/plugin update` (or `/plugin marketplace
  update skillz`) re-fetches `master` from this repo.
- **Codex plugin (GitHub marketplace source):** open `/plugins`,
  select `skillz`, run the update action.
- **Codex plugin (local checkout source):** `git pull` inside the
  checkout you added, then reopen `/plugins` if needed.
- **Script:** re-run the curl one-liner, or `git pull && ./install.sh`
  from a clone.

## Releases

Tagging and release notes are automatic; do not tag by hand.
`.github/workflows/release.yml` owns both halves:

- On a PR into `master`, the `version-bumped` job fails unless
  `plugins/skillz/.claude-plugin/plugin.json#version` advances past
  master's, **and** `plugins/skillz/.codex-plugin/plugin.json#version`
  matches it. Codex pins on its own manifest, so the two must move together.
  PRs touching only `.github/` or `scripts/` skip the gate — nothing
  shippable changed.
- On the push to `master`, the `tag-and-release` job creates tag
  `v<version>` and a GitHub release at master's squash commit, with
  `--generate-notes`.

The full-bundle plugin's version is the repo-level release anchor: one tag
and one release per shipping merge. The single-skill plugins keep their own
independent versions — those are each plugin's cache key in
`~/.claude/plugins/cache/`, so **bump the version of every plugin whose
skill you touched**, not just the bundle. Skip that and `claude plugin
update` tells users of that single-skill plugin "up to date" forever.

`scripts/check-plugin-version-bumps.py` enforces this, so you no longer have
to remember it. It maps the PR's changed paths back to the plugins that ship
them — via `catalog.json`, so editing `skills/foo/SKILL.md` implicates both
the `foo` plugin and the bundle — and fails the PR unless each implicated
plugin's version advanced. It also rejects a plugin whose Claude and Codex
manifests disagree, since the two runtimes pin independently and letting them
drift freezes one host silently.

Run it locally before pushing (it reads the working tree, so uncommitted
changes count):

```bash
python3 scripts/check-plugin-version-bumps.py origin/master
```

Release notes are the merged PR titles since the previous tag, which is why
there is no `CHANGELOG.md`. A lazy PR title is a lazy release note — write
the title as the line you want a reader to see.

## Verify

Plugin install (Claude Code):

```text
/plugin list
```

Plugin install (Codex):

```text
/plugins
```

Script install:

```bash
ls ~/.codex/skills/work-on-pr/SKILL.md   ~/.codex/skills/review-pr-loop/SKILL.md
ls ~/.claude/skills/work-on-pr/SKILL.md ~/.claude/skills/review-pr-loop/SKILL.md
```

Check only the host(s) you actually use.

## Collections (legacy)

Collections are an `install.sh`-only concept; Claude Code and Codex
do not have a native notion of "collection." New work should use
the equivalent **plugin** entries (e.g. install `pr-loop@skillz` via
`/plugin install`). Collections remain documented here for users
still on the script install path.

### pr-loop collection

Paired skills that drive the iterative back-and-forth of a GitHub
pull request review cycle. Install as one unit via:

```bash
./install.sh --collection pr-loop
```

The same pairing is also available as the `pr-loop` plugin entry —
`/plugin install pr-loop@skillz` is the preferred path on Claude
Code and on Codex CLI ≥ 0.117.

The two skills:

- **work-on-pr** ([SKILL.md](./skills/work-on-pr/SKILL.md)):
  author-side loop. Watches for new review comments, issue comments,
  and inline threads; waits when feedback has not landed; addresses
  each in a worktree; runs tests; commits; pushes; replies with the
  commit SHA. Also accepts an issue reference and creates the PR if
  one does not yet exist (ensuring `Closes #<issue>` is in the body).
- **review-pr-loop** ([SKILL.md](./skills/review-pr-loop/SKILL.md)):
  reviewer-side loop. Each round re-reads the linked issue(s) and
  all prior reviews, issue comments, and inline threads before
  reviewing only the new diff or the author's latest response.
  Leaves structured feedback (REQUEST_CHANGES, COMMENT, APPROVE)
  and continues until approved, merged, or closed.

**Which reviewer to pair with `work-on-pr`.** When the author and the
reviewer are two identities — a human reviewer, or a second operator —
`review-pr-loop` is the reviewer side. When one operator drives both
sides under a single GitHub login, prefer
[`codex-adversarial-pr-review`](./skills/codex-adversarial-pr-review/SKILL.md),
invoked from `work-on-pr` step 7: one deterministic script call per
round, no second watch loop to pace, and the findings post as ordinary
PR review comments that the author loop already knows how to read. Two
consequences of that path are worth knowing before you pick it: the
author identity cannot `APPROVE` its own PR, so the review exit is
*zero blocking findings*, not a review state; and a zero-finding result
is treated as suspicious rather than as a pass, because an empty result
looks exactly like a clean one on the wire (see #212).

Each skill owns the watch loop. Every pass should surface which watch
mode is active:

- `watch-mode=durable`: a real `ScheduleWakeup`-style continuation
  was scheduled and survives turn end.
- `watch-mode=in-process-only`: no durable wake-up exists, so the
  current invocation must stay alive with `sleep` + re-poll.

Invoking before comments exist is expected, and an idle poll is not
completion. In-process polling only works while the current
invocation stays alive; a terminal/final handoff ends it.
`watch stopped:*` is only valid when the invocation is actually
ending, not on an ordinary idle pass.

Usage:

```text
/work-on-pr <N>        # author side (also takes an issue ref, or a bare
                       #   problem statement — it opens the issue first)
/review-pr-loop <N>    # reviewer side, when the reviewer is a separate identity
```

#### Reducing permission prompts (Claude Code)

The author-side loop pushes commits, posts comments, and replies to
review threads several rounds per PR. Without the right
`permissions.allow` patterns in `~/.claude/settings.json`, Claude
Code prompts for each write every round and the loop stalls.

The recommended allow block lives in
[`skills/work-on-pr/SKILL.md`](skills/work-on-pr/SKILL.md), under
"Auto-approved operations (self-PR workflow)". Two pitfalls worth
calling out up front:

- **Never chain `cd <worktree> && git ...`.** Claude Code matches
  each allow entry against the full command string. The compound
  starts with `cd`, so a pattern like
  `Bash(git push origin feature/*)` does not fire even though the
  second segment would match on its own. The host's Bash-tool docs
  say this explicitly: *"never prepend `cd <current-directory>` to
  a `git` command — the compound triggers a permission prompt."*
  Use `git -C <worktree-path> <subcommand>` instead, and add the
  matching `Bash(git -C * <subcommand>:*)` entries from the SKILL's
  allow block. The same rule applies to chains like
  `git -C X commit ... && git -C X push ...` — issue them as
  separate Bash tool calls, not a single `&&` string.
- **`python3 -c "<inline>"` does not auto-allow.** Read-only
  introspection like
  `cat ~/.claude/settings.json | python3 -c "<parse>"` still
  prompts because Claude Code (and the YOLT hook, where installed)
  treats an inline `-c` script as opaque. Pull the snippet into a
  real `.py` file and invoke `python3 path/to/script.py` to make it
  analyzable, or accept the one-off prompt.

See `skills/work-on-pr/SKILL.md` → "Auto-approved operations" for
the full pattern list and the rationale behind every entry that is
intentionally NOT auto-approved (`git push origin master`,
`git push --force`, `gh repo delete`, etc.).

## Plugins

Rule: **a skill that ships inside a hooked plugin is not in the
`skillz` bundle.** Installing the bundle plus such a plugin (the
common case, since only the plugin carries the hooks) would expose
the same skill twice, namespaced by plugin - `/skillz:tamarian` next
to `/tamarian:tamarian` - and the bundle copy would be the lesser
half anyway: the hooks that make the skill persist or fire ship only
with its plugin. `validate-catalog.sh` enforces this by reading the
plugin manifests, so a plugin that grows hooks later trips the check
without any catalog edit. Currently: `secrets-in-agent-sessions`,
`tamarian`, `codex-continuous-learning`.

### codex-continuous-learning (Codex only)

A Codex-native counterpart of
[Claudeception](https://github.com/blader/Claudeception). Bundles the
[`continuous-learning`](./skills/continuous-learning/SKILL.md) skill
with two Codex hooks:

- **UserPromptSubmit** — injects a one-line reminder that any
  reusable, verified learning from this turn should be captured
  before exit.
- **Stop** — forces a brief end-of-task retrospective. The agent
  either invokes `continuous-learning` and acts on its output, or
  emits the literal line `No reusable learning.` and exits.

Design intent: capture only learnings that pass four retrospective
gates (real discovery cost, recurrence likelihood, verifiable
trigger, verified result). Most turns terminate with
`No reusable learning.` — that escape hatch is the point. See the
skill for the full policy and skill-shape requirements.

Layout:

```
plugins/codex-continuous-learning/
  .codex-plugin/plugin.json        # Codex plugin manifest
  skills/continuous-learning -> ../../../skills/continuous-learning
  hooks/
    hooks.json                     # UserPromptSubmit + Stop wiring
    continuous_learning_prompt.py  # UserPromptSubmit hook
    continuous_learning_stop.py    # Stop hook
```

The `skills/continuous-learning` directory inside the plugin is a
relative symlink to the canonical
[`skills/continuous-learning/`](./skills/continuous-learning/) at the
repo root, so the bundle stays a single source of truth.

Hook scripts are dependency-free Python (`python3` only, no
third-party imports, no filesystem writes, no network) and both fail
open via `on_error: ignore` in `hooks.json`. A hook crash never
breaks the user's session.

This bundle is **Codex-only** and not exposed via the Claude Code
plugin or the `pr-loop` collection. Claude Code users who want
similar end-of-task behavior should install Claudeception directly.
The `continuous-learning` skill ships only here, not in the `skillz`
bundle (see the rule above).

Install (when supported by the local Codex CLI):

```text
/plugins
# add this repo as a marketplace source, then install
# codex-continuous-learning
```

Or, from a clone, point Codex at `plugins/codex-continuous-learning/`
as a local plugin folder.

### tamarian (Claude only)

Darmok and Jalad at Tanagra. A persona mode, purely for entertainment:
Claude answers as the Children of Tama, meaning carried by metaphor and
allusion to shared stories - the canon ST:TNG phrases plus ones coined
from Earth myth, history and engineering lore ("Hopper, the moth in
the relay" is a bug, found). Inspired by
[caveman](https://github.com/juliusbrussee/caveman) for the mechanics
and by [Design Patterns are
Darmok](https://blog.debedb.com/2026/08/06/design-patterns-are-darmok/)
for the premise: a pattern name is a compressed story that only
decompresses against shared knowledge, and this mode makes the
compression audible.

The substance never leaves. Code, commands, paths, errors and numbers
stay literal at every level; security warnings, destructive-action
confirmations and step-by-step instructions always drop to plain
speech.

```text
> why is the build failing?

Shaka, when the walls fell - the build fails. Hopper, the moth in the
relay - `user` may be `undefined` at `auth.ts:42`. Temba, his arms
wide -

    if (!user) return null;
```

Levels: `lite` (one glossed metaphor, then plain speech), `full`
(default: every prose beat is metaphor, dash, literal statement), and
`ultra` (pure metaphor, a `The river Temarc` glossary at the end).

```text
/tamarian full      # persist the level; speaks Tamarian from that reply on
/tamarian           # status
/tamarian off       # plain speech; "stop tamarian" / "normal mode" also work
```

Layout:

```
plugins/tamarian/
  .claude-plugin/plugin.json   # manifest; SessionStart + UserPromptSubmit hooks inline
  skills/tamarian -> ../../../skills/tamarian
  hooks/
    tamarian-activate.sh       # SessionStart: emits the SKILL.md body when a level is set
    tamarian-reminder.sh       # UserPromptSubmit: one-line reminder against drift
```

The level lives in `$CLAUDE_CONFIG_DIR/.tamarian-mode` (default
`~/.claude/.tamarian-mode`); no file means off, so installing the
plugin changes nothing until `/tamarian` is invoked. The SessionStart
hook reads `skills/tamarian/SKILL.md` at runtime, so the skill stays
the single source of truth. Both hooks are plain bash with no
dependencies and print `OK` when the mode is off.

The skill ships only with this plugin, not in the `skillz` bundle (see
the rule above): the bundle manifest carries no hooks, so a bundle copy
would speak Tamarian for one session and then forget.

```text
/plugin marketplace update skillz
/plugin install tamarian@skillz
```

The phrasebook, with coinage templates and rules, is
[`skills/tamarian/LEXICON.md`](./skills/tamarian/LEXICON.md). Temba,
his arms wide - additions welcome by PR.

## Validation

```bash
./scripts/validate-catalog.sh
```

The script:

- Confirms every catalog-referenced skill path exists.
- Confirms every `SKILL.md` opens with YAML frontmatter containing
  `name:` and `description:`.
- Confirms every collection references only known skills.
- Confirms plugin-manifest paths declared in `catalog.json` exist.
- Fails if a skill of a hooked plugin (inline `hooks` in a manifest, or
  a `hooks/hooks.json`) is also listed in the `skillz` bundle.
- Runs `install.sh --dry-run` for the no-arg default,
  `--collection pr-loop`, `--skill work-on-pr`, and `--all`.

Run it before opening a PR that touches the catalog or installer.

### Rebasing a stale skill branch

Every skill-adding PR edits the same four registry files — `catalog.json`,
both `marketplace.json` files, and the README catalog table — so a branch that
has sat for a few weeks will conflict in all four. **Do not resolve those
conflicts as text.** The entry lists get reordered and re-summarised upstream,
and the bundle plugin's description is one line naming every skill, so "keep
both sides" yields a registry that is valid JSON, reads fine, and is wrong: it
resurrects skills master deliberately removed and pins a stale skill list into
the bundle description.

```bash
python3 scripts/merge-skill-registry.py         # first conflicted commit
python3 scripts/merge-skill-registry.py HEAD    # each later commit in the branch
```

It takes the base side of each registry wholesale and re-splices only the
entries your branch adds, keeping just the ones whose files exist in the
rebased tree — that last filter is what stops an upstream deletion from being
undone. Pass `HEAD` from the second conflicted commit onward, or resolving
commit 2 discards commit 1's entries. Then `git add` the registry files,
`git rebase --continue`, and re-run `validate-catalog.sh`, which is the real
check.

## Pre-publish sensitive-term gate

When a skill is authored on a client / day-job machine and promoted here, its
`SKILL.md` (and any shipped code) can leak content the public repo must never
carry — account IDs, keys/tokens, client names, internal domains, infra
topology. Run the gate before opening the PR:

```bash
./scripts/check-sensitive-terms.sh skills/<new-skill>/
```

It greps for **structural** leaks that are safe to enumerate publicly (AWS
account-id / access-key shapes, Slack `xox*`/`xapp-` and GitHub/OpenAI/Google
token shapes, `PRIVATE KEY` blocks, RFC-1918 IPs, `.internal`/`.corp` domains)
and exits non-zero on any hit.

Client/account **names** can't live in a denylist in this public repo, so the
script reads them from a private, out-of-repo wordlist — one term per line,
blank lines and `#` comments ignored, each term matched case-insensitively
(names get written `Foo`, `foo`, and `FOO`). It defaults to
`~/.config/skillz/sensitive-terms.txt`, so once that file exists the name
check runs with no flags:

```bash
mkdir -p ~/.config/skillz
cat >> ~/.config/skillz/sensitive-terms.txt <<'EOF'
# employer / client names, internal repo + service prefixes
EOF

./scripts/check-sensitive-terms.sh skills/<new-skill>/
```

Point `SKILLZ_SENSITIVE_TERMS_FILE` elsewhere to override the default. If it
is set to a path that doesn't exist the script exits `2` rather than quietly
downgrading to structural-only — a typo'd path should fail loudly, not look
clean.

Without a wordlist you get structural checks only, and the script says so.
That is the expected state for anyone outside the org: the names that matter
are exactly the ones this repo must not carry.

Clean exit = safe to promote. This is the automated form of the hard rule
"the public repo must never contain account IDs, client names, domains, or
infra topology" — make it a step in the claudeception / skill-promotion flow.

## Automated checks

Both gates run automatically, split across two places because one of them
cannot run in public CI.

**CI** (`.github/workflows/checks.yml`) — on every pull request and every push
to `master`:

```bash
bash scripts/validate-catalog.sh
bash scripts/check-sensitive-terms.sh skills/ docs/ plugins/ README.md catalog.json
```

Advisory: it reports pass/fail on the PR but nothing is a required check yet.
Neither script needs network — `install.sh` reads the local `catalog.json`
when run from a checkout, so the dry-run smoke test validates *that* PR's
catalog rather than master's.

**Pre-push hook** (`hooks/pre-push`) — enable it per clone with git's own
hooks path:

```bash
git config core.hooksPath hooks
```

One command, no installer, and the hook updates itself when you pull. Skip a
run deliberately with `git push --no-verify`.

The hook exists because the sensitive-term gate has two halves and CI can
only do one. The **structural** half (key/token/account-id shapes, private
IPs, internal-domain hostnames) runs fine in Actions. The **name** half reads
a wordlist that must stay out of this public repo — and an Actions secret
would not reach fork PRs, so the job would report green without having
checked anything. A check that silently no-ops is worse than no check. Names
are therefore enforced pre-push, on the machine where the wordlist already
lives.

It also runs `scripts/check-plugin-version-bumps.py` against `origin/master`,
for a different reason: that gate is not impossible in CI, it is just the one
contributors hit most. Learning about a missed bump from a red `version-bumped`
job costs a round trip, and the error names files you have already pushed.
Learning about it from the hook costs a second. If `origin/master` is not
present the hook **fails** rather than skipping — a version check that quietly
passes because it could not compare is the same silent-green failure mode the
name gate exists to avoid.

## Related code-review approaches

The pr-loop collection operates at the **workflow** layer — when to
review, how often, what to compare against across rounds. Several
other projects address the **content** layer (what to say in a
single review) and are complementary, not competing. They can be
stacked: `review-pr-loop` driving the cycle while internally invoking
a formatter and/or an adversarial subagent per round.

| Feature | [caveman-review](https://github.com/JuliusBrussee/caveman) | [ce-adversarial-reviewer](https://github.com/EveryInc/compound-engineering-plugin) | [claudskills adversarial-review](https://claudskills.com/skills/adversarial-review/) | [voitta-ai/skillz review-pr-loop](./skills/review-pr-loop/SKILL.md) |
|---|---|---|---|---|
| Type | Skill | Agent (subagent) | Skill | Skill (paired with [work-on-pr](./skills/work-on-pr/SKILL.md)) |
| Job | Compress review prose | Chaos-engineer failure scenarios | PASS/FAIL adversarial verdict | Drive multi-round PR review *loop* |
| Adversarial methodology | No (format only) | Yes (4 techniques) | Yes (claimed) | No — orchestration, not methodology |
| Verdict | None | Advisory findings | Binary PASS/FAIL | REQUEST_CHANGES / COMMENT / APPROVE |
| Confidence calibration | No | Anchored 100/75/50/25 | Anchoring-bias prevention | N/A |
| Scope discipline | Reviews only | Defers to 8 siblings | Standalone | Owns whole review *cycle* |
| Single-shot vs iterative | Single | Single | Single | Iterative — re-reads issue, prior threads, only-new-diff each round |
| Output | PR-paste comments | Structured JSON | Unknown | GitHub PR review (via `gh`) + commit replies |
| State across rounds | None | None | None | Yes — tracks addressed vs new, waits when quiet |
| Conditional trigger | Manual | Auto (size / risk) | Manual | Manual (`/review-pr-loop N`) |
| Exit conditions | N/A (one-shot) | N/A | N/A | Approve, merge, close, user stop |
| Polling discipline | N/A | N/A | N/A | Paced against prompt-cache TTL, `ScheduleWakeup`-aware |
| Host targets | Claude Code | Claude Code | Claude Code (+ Pro app) | Claude Code + Codex |
| Orchestration | Standalone | Part of `/ce-code-review` fleet | Standalone | Paired with `work-on-pr` (author side) |

See also: [claudskills](https://claudskills.com/) registry,
[Anthropic Claude Code skills docs](https://docs.claude.com/en/docs/claude-code/skills.md),
[vercel-labs/skills](https://github.com/vercel-labs/skills) (upstream
profile catalog used by `npx skills add`).

## PR review workflow stack

The skills here are the **workflow** layer. They compose with
subagents, Agent Teams, and the Agent SDK rather than competing with
them. [`docs/pr-review-workflow.md`](./docs/pr-review-workflow.md)
writes that down: which layer does which job, the rule that subagents
cannot spawn subagents (so `review-pr-loop` must run in the main
session when it delegates a specialist sweep), how to use PR Review
Toolkit agents as advisory-only subagents, when an Agent Team is worth
the overhead, the SDK boundary, and the same-identity reviewer caveat.
