#!/usr/bin/env python3
"""Mechanical checks that catch the class of bug behind the `@tool`-location doc drift and the
dead `pytest tests/ -v` gate: stale file references, and CLAUDE.md's eval baseline prose
silently drifting from evals/report/latest.json. Exit 0 = clean, exit 1 = at least one finding.

Deliberately does not run pytest/dart/run_eval itself (slow, needs a dev environment) — that
stays reviewer's job per rules/gates.md. This only checks facts a script can check without side
effects: does a referenced path exist, do two numbers that must agree actually agree.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
findings: list[str] = []

# Directories whose content is out of scope: another branch's worktree, and generated logs.
SKIP_DIRS = {".claude/worktrees", "artefacts/agent-memory.md", ".git"}


def scannable_files(patterns: list[str]) -> list[Path]:
    out = []
    for pattern in patterns:
        for p in ROOT.glob(pattern):
            rel = p.relative_to(ROOT).as_posix()
            if any(rel.startswith(skip) for skip in SKIP_DIRS):
                continue
            if p.is_file():
                out.append(p)
    return out


# Docs conventionally give paths relative to one of these subroots without the prefix
# (e.g. "api/routes.py" for calai_backend/api/routes.py, "lib/main.dart" for the frontend).
CANDIDATE_ROOTS = [ROOT, ROOT / "calai_backend", ROOT / "calai_frontend", ROOT / "evals"]


def check_dead_paths() -> None:
    """Every backtick-quoted path that looks like a repo file must exist under the repo root
    or one of the conventional subroots docs write paths relative to."""
    path_pattern = re.compile(r"`((?:[\w.-]+/)+[\w.-]+\.(?:py|md|dart|json|jsonl|sh|yaml|yml))`")
    # Deliberately excludes skills/*/SKILL.md: those are living implementation-plan docs that
    # intentionally reference "Retired" and "new, not yet built" files as part of their spec —
    # a real path there isn't a stale-doc bug the way it is in CLAUDE.md/rules/agents, which
    # state facts about the *current* codebase. This is where the @tool and pytest-tests/ bugs
    # actually lived, so that's the scope worth a hard fail on.
    files = scannable_files(["CLAUDE.md", "rules/*.md", ".claude/agents/*.md"])
    for f in files:
        text = f.read_text(errors="ignore")
        for m in path_pattern.finditer(text):
            candidate = m.group(1)
            # Skip obvious placeholders / globs / non-repo-relative examples.
            if "<" in candidate or "*" in candidate or candidate.startswith("http"):
                continue
            if not any((base / candidate).exists() for base in CANDIDATE_ROOTS):
                rel = f.relative_to(ROOT).as_posix()
                findings.append(f"{rel}: references `{candidate}` which does not exist "
                                 f"(checked repo root, calai_backend/, calai_frontend/, evals/)")


def check_known_dead_command() -> None:
    """The specific bug from D4: a bare `pytest tests/` with no root tests/ dir, cited as
    something to actually RUN. rules/gates.md deliberately describes this as the anti-pattern
    to avoid, so a mention there doesn't count as the bug recurring."""
    if (ROOT / "tests").exists():
        return  # a root tests/ now exists; this check no longer applies
    files = scannable_files(["CLAUDE.md", ".claude/agents/*.md", "skills/*/SKILL.md"])
    pattern = re.compile(r"`pytest tests/(?:\s+-v)?`")
    for f in files:
        text = f.read_text(errors="ignore")
        if pattern.search(text):
            rel = f.relative_to(ROOT).as_posix()
            findings.append(f"{rel}: cites `pytest tests/` as a command to run, but no root "
                             f"tests/ exists")


def check_eval_baseline_sync() -> None:
    """CLAUDE.md's prose eval numbers must match evals/report/latest.json."""
    report_path = ROOT / "evals" / "report" / "latest.json"
    claude_md = ROOT / "CLAUDE.md"
    if not report_path.exists() or not claude_md.exists():
        findings.append("eval baseline check skipped: evals/report/latest.json or CLAUDE.md missing")
        return
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as e:
        findings.append(f"evals/report/latest.json is not valid JSON: {e}")
        return

    # Only the top-level aggregate _pct fields are meant to be mirrored in CLAUDE.md's prose.
    # Nested per-dataset-category breakdowns (per_dataset_summary.*) are not — CLAUDE.md cites
    # the aggregate only, so including nested fields here would be checking against a promise
    # the doc never made.
    pct_fields = {
        k: v for k, v in report.items()
        if k.endswith("_pct") and isinstance(v, (int, float))
    }
    text = claude_md.read_text()
    for key, value in pct_fields.items():
        # Look for the number (to 1 decimal) anywhere in CLAUDE.md's prose.
        as_str = f"{value:.1f}"
        if as_str not in text and f"{value:.0f}%" not in text and f"{value:.1f}%" not in text:
            findings.append(
                f"CLAUDE.md may be stale: {key}={as_str} from evals/report/latest.json "
                f"not found verbatim in CLAUDE.md prose (re-check the Architecture docs & "
                f"eval baseline section)"
            )


def check_agent_tool_grants() -> None:
    """Flag an agent instructed to Write/Edit/use Skill without that tool granted.

    Heuristic, not exhaustive: greps for verbs that need a specific tool and checks the
    frontmatter `tools:` line. False negatives are expected (prose is prose); the point is to
    catch the D3 pattern (an agent told to do something its own frontmatter forbids), not to be
    a full static analyzer.
    """
    needs = {
        r"\buse the `Skill`\b|\bavailable via `Skill`\b": "Skill",
        r"\bwrite `artefacts/runs\b": "Write",
        r"\bupdate the status header\b": "Edit",
    }
    for f in scannable_files([".claude/agents/*.md"]):
        text = f.read_text(errors="ignore")
        m = re.search(r"^tools:\s*(.+)$", text, re.MULTILINE)
        granted = {t.strip() for t in m.group(1).split(",")} if m else set()
        for pattern, tool in needs.items():
            if re.search(pattern, text) and tool not in granted:
                rel = f.relative_to(ROOT).as_posix()
                findings.append(f"{rel}: mentions needing `{tool}` but tools: line lacks it")


def main() -> int:
    check_dead_paths()
    check_known_dead_command()
    check_eval_baseline_sync()
    check_agent_tool_grants()

    if not findings:
        print("verify_rules: clean — no dead references, no known-dead commands, "
              "eval baseline in sync, no tool-grant gaps found.")
        return 0

    print(f"verify_rules: {len(findings)} finding(s):\n")
    for f in findings:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
