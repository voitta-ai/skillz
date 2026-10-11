#!/usr/bin/env node
//
// codex-adversarial-pr-review.mjs
//
// Deterministic bridge: run `/codex:adversarial-review` against a PR's diff and
// post its structured findings as a single batched GitHub PR review (inline
// comments + summary body).
//
// The Codex command itself is stdout-only and has no GitHub awareness; this
// wrapper calls the same companion runtime with --json, parses the findings,
// maps each to a commentable diff line, and posts via `gh`.
//
// Requires: node, git, gh (authenticated), and the OpenAI Codex CLI plugin
// installed (so the codex-companion runtime is present in the plugin cache).
//
// Usage:
//   node codex-adversarial-pr-review.mjs --pr <N> [options]
//
// Options:
//   --pr <N>              PR number (required).
//   --repo <owner/repo>   Base repo (default: derived from `gh repo view`).
//   --repo-dir <path>     Local checkout of the PR head (default: cwd).
//   --base <ref>          Base ref to diff against (default: PR baseRefName).
//   --min-confidence <f>  Inline only findings with confidence >= f (default 0.6).
//   --event <E>           Review event: COMMENT|REQUEST_CHANGES|APPROVE (default COMMENT).
//   --model <m>           Pass a model through to Codex.
//   --focus <text>        Extra adversarial focus text for the review.
//   --fetch               `git fetch origin <base>` before reviewing.
//   --dry-run             Print the review payload; do not post.
//   --json                Emit a machine-readable summary of what was posted.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const MARKER = "codex-adversarial-review";

function parseArgs(argv) {
  const opts = {
    pr: null,
    repo: null,
    repoDir: process.cwd(),
    base: null,
    minConfidence: 0.6,
    event: "COMMENT",
    model: null,
    focus: "",
    fetch: false,
    dryRun: false,
    json: false
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => argv[(i += 1)];
    switch (arg) {
      case "--pr": opts.pr = next(); break;
      case "--repo": opts.repo = next(); break;
      case "--repo-dir": opts.repoDir = path.resolve(next()); break;
      case "--base": opts.base = next(); break;
      case "--min-confidence": opts.minConfidence = Number(next()); break;
      case "--event": opts.event = next(); break;
      case "--model": opts.model = next(); break;
      case "--focus": opts.focus = next(); break;
      case "--fetch": opts.fetch = true; break;
      case "--dry-run": opts.dryRun = true; break;
      case "--json": opts.json = true; break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }
  if (!opts.pr) {
    throw new Error("--pr <N> is required.");
  }
  return opts;
}

function run(cmd, args, options = {}) {
  const stdout = execFileSync(cmd, args, {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    ...options
  });
  return stdout;
}

// Locate the codex companion script in the plugin cache, preferring the highest
// installed version. The plugin is vendored and version-stamped, so we never
// hard-code a path or fork it.
function findCompanion() {
  const roots = [
    path.join(os.homedir(), ".claude", "plugins", "cache", "openai-codex", "codex"),
    path.join(os.homedir(), ".claude", "plugins", "marketplaces", "openai-codex", "plugins", "codex")
  ];
  const candidates = [];
  for (const root of roots) {
    if (!fs.existsSync(root)) {
      continue;
    }
    const direct = path.join(root, "scripts", "codex-companion.mjs");
    if (fs.existsSync(direct)) {
      candidates.push(direct);
      continue;
    }
    for (const version of fs.readdirSync(root)) {
      const candidate = path.join(root, version, "scripts", "codex-companion.mjs");
      if (fs.existsSync(candidate)) {
        candidates.push(candidate);
      }
    }
  }
  if (candidates.length === 0) {
    throw new Error(
      "Could not find codex-companion.mjs. Install the OpenAI Codex CLI plugin first."
    );
  }
  // Highest version path sorts last lexically for the version-stamped layout.
  candidates.sort();
  const retval = candidates[candidates.length - 1];
  return retval;
}

function getPrMeta(repo, pr) {
  const args = ["pr", "view", String(pr), "--json", "baseRefName,headRefName,headRefOid"];
  if (repo) {
    args.push("--repo", repo);
  }
  const retval = JSON.parse(run("gh", args));
  return retval;
}

function getRepoSlug(explicit, repoDir) {
  if (explicit) {
    return explicit;
  }
  const retval = run("gh", ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], {
    cwd: repoDir
  }).trim();
  return retval;
}

function runReview(companion, repoDir, base, model, focus) {
  const args = [
    companion,
    "adversarial-review",
    "--json",
    "--cwd",
    repoDir,
    "--base",
    base,
    "--scope",
    "branch"
  ];
  if (model) {
    args.push("--model", model);
  }
  if (focus) {
    args.push(focus);
  }
  const raw = run(process.execPath, args, { cwd: repoDir });
  const payload = JSON.parse(raw);
  const result = payload.result || salvageResult(payload);
  if (!result) {
    const detail = payload.parseError || payload.codex?.stderr || "no structured result";
    throw new Error(`Codex review returned no findings: ${detail}`);
  }
  return result;
}

// The companion parses the model's output into `result`. That parse is flaky: the model
// intermittently emits its JSON object followed by trailing prose, and the companion then
// reports e.g. `parseError: "Unexpected non-whitespace character after JSON at position
// 183"`, leaves `result` empty, and a complete review is thrown away. Observed twice in a
// row on one PR and not at all on the next run of the same diff, so re-running is a coin
// flip rather than a fix.
//
// The companion does preserve the model's untouched output in `rawOutput`, so the findings
// are still there to be recovered: decode the FIRST complete JSON value and ignore whatever
// follows it. JSON.parse cannot do this (it rejects trailing content), so this walks
// candidate end positions from the first `{`. Returns null when nothing usable is found, so
// the caller still fails loudly rather than silently reviewing nothing.
function salvageResult(payload) {
  const raw = typeof payload.rawOutput === "string" ? payload.rawOutput : "";
  const start = raw.indexOf("{");
  if (start < 0) {
    return null;
  }
  for (let end = raw.length; end > start; end--) {
    if (raw[end - 1] !== "}") {
      continue;
    }
    let candidate;
    try {
      candidate = JSON.parse(raw.slice(start, end));
    } catch {
      continue;
    }
    if (candidate && Array.isArray(candidate.findings)) {
      process.stderr.write(
        `note: recovered ${candidate.findings.length} finding(s) from rawOutput after a companion parse error\n`
      );
      return candidate;
    }
  }
  return null;
}

// Build a map of file -> Set(new-file line numbers) that are commentable on the
// RIGHT side of the PR diff (added and context lines inside hunks).
function commentableLines(diffText) {
  const map = new Map();
  let file = null;
  let newLine = 0;
  let inHunk = false;
  const add = (line) => {
    if (!map.has(file)) {
      map.set(file, new Set());
    }
    map.get(file).add(line);
  };
  for (const text of diffText.split("\n")) {
    if (text.startsWith("diff --git")) {
      file = null;
      inHunk = false;
    } else if (text.startsWith("--- ")) {
      // left-side header, ignore
    } else if (text.startsWith("+++ ")) {
      const p = text.slice(4).trim();
      file = p === "/dev/null" ? null : p.replace(/^b\//, "");
      inHunk = false;
    } else if (text.startsWith("@@")) {
      const m = /@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
      newLine = m ? Number(m[1]) : 0;
      inHunk = Boolean(m);
    } else if (inHunk && file) {
      const c = text[0];
      if (c === "+") {
        add(newLine);
        newLine += 1;
      } else if (c === " ") {
        add(newLine);
        newLine += 1;
      } else if (c === "-" || c === "\\") {
        // deletion (left side) or "no newline at eof": no RIGHT advance
      }
    }
  }
  return map;
}

function findingHeading(f) {
  const retval = `**[${f.severity}] ${f.title}** _(confidence ${f.confidence.toFixed(2)})_`;
  return retval;
}

function inlineBody(f) {
  const lines = [
    findingHeading(f),
    "",
    f.body,
    "",
    `**Recommendation:** ${f.recommendation}`,
    "",
    `<sub>codex adversarial review</sub>`
  ];
  const retval = lines.join("\n");
  return retval;
}

function anchorComment(f, commentable) {
  const lines = commentable.get(f.file);
  if (!lines) {
    return null;
  }
  const endIn = lines.has(f.line_end);
  const startIn = lines.has(f.line_start);
  const comment = { path: f.file, side: "RIGHT", body: inlineBody(f) };
  if (endIn && startIn && f.line_start < f.line_end) {
    comment.start_line = f.line_start;
    comment.start_side = "RIGHT";
    comment.line = f.line_end;
    return comment;
  }
  if (endIn) {
    comment.line = f.line_end;
    return comment;
  }
  if (startIn) {
    comment.line = f.line_start;
    return comment;
  }
  return null;
}

function rollupLine(f) {
  const retval = `- \`${f.file}:${f.line_start}-${f.line_end}\` ${findingHeading(f)}\n  ${f.body} _(fix: ${f.recommendation})_`;
  return retval;
}

function buildReview(result, commentable, opts, headOid) {
  const inline = [];
  const outOfDiff = [];
  const lowConfidence = [];

  for (const f of result.findings) {
    if (f.confidence < opts.minConfidence) {
      lowConfidence.push(f);
      continue;
    }
    const comment = anchorComment(f, commentable);
    if (comment) {
      inline.push(comment);
    } else {
      outOfDiff.push(f);
    }
  }

  const body = [];
  body.push(`<!-- ${MARKER} sha=${headOid} -->`);
  body.push(`## Codex Adversarial Review — ${result.verdict}`);
  body.push("");
  body.push(result.summary);

  if (result.next_steps && result.next_steps.length > 0) {
    body.push("");
    body.push("### Next steps");
    for (const step of result.next_steps) {
      body.push(`- ${step}`);
    }
  }
  if (outOfDiff.length > 0) {
    body.push("");
    body.push("### Findings outside the diff");
    body.push("_(could not be attached inline; lines are not part of this PR's diff)_");
    for (const f of outOfDiff) {
      body.push(rollupLine(f));
    }
  }
  if (lowConfidence.length > 0) {
    body.push("");
    body.push(`<details><summary>Lower-confidence findings (below ${opts.minConfidence})</summary>`);
    body.push("");
    for (const f of lowConfidence) {
      body.push(rollupLine(f));
    }
    body.push("");
    body.push("</details>");
  }

  const review = {
    commit_id: headOid,
    event: opts.event,
    body: body.join("\n"),
    comments: inline
  };
  const retval = { review, counts: { inline: inline.length, outOfDiff: outOfDiff.length, lowConfidence: lowConfidence.length } };
  return retval;
}

function postReview(repo, pr, review) {
  const tmp = path.join(os.tmpdir(), `codex-pr-review-${pr}-${process.pid}.json`);
  fs.writeFileSync(tmp, JSON.stringify(review));
  try {
    run("gh", ["api", `repos/${repo}/pulls/${pr}/reviews`, "--method", "POST", "--input", tmp]);
  } finally {
    fs.rmSync(tmp, { force: true });
  }
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const repo = getRepoSlug(opts.repo, opts.repoDir);
  const meta = getPrMeta(opts.repo, opts.pr);
  const base = opts.base || `origin/${meta.baseRefName}`;
  const headOid = meta.headRefOid;

  if (opts.fetch) {
    run("git", ["fetch", "origin", meta.baseRefName], { cwd: opts.repoDir });
  }

  const companion = findCompanion();
  const result = runReview(companion, opts.repoDir, base, opts.model, opts.focus);
  const diffText = run("gh", ["pr", "diff", String(opts.pr), "--repo", repo]);
  const commentable = commentableLines(diffText);
  const { review, counts } = buildReview(result, commentable, opts, headOid);

  if (opts.dryRun) {
    process.stdout.write(JSON.stringify(review, null, 2) + "\n");
    return;
  }

  postReview(repo, opts.pr, review);

  if (opts.json) {
    process.stdout.write(JSON.stringify({ repo, pr: Number(opts.pr), verdict: result.verdict, ...counts }, null, 2) + "\n");
  } else {
    process.stdout.write(
      `Posted ${review.event} review on ${repo}#${opts.pr} (${result.verdict}): ` +
        `${counts.inline} inline, ${counts.outOfDiff} out-of-diff, ${counts.lowConfidence} low-confidence.\n`
    );
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
