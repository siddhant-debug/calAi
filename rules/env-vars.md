# Rule: making a `.env` value required

**When a change makes a previously-optional `.env` value required** (a new required API key,
no default/fallback path):

1. Use an explicit, **module-directory-anchored** `load_dotenv()` path — never the bare
   cwd-dependent default. This repo has more than one `.env` at different directory levels, and
   the default resolves to whichever one `find_dotenv()` hits first walking up from cwd, not
   necessarily the intended one.
2. Confirm the exact variable **NAME** the code reads matches what's actually in the target
   `.env`, via `dotenv_values(path).keys()` — **names only, never values, never the file's raw
   contents.** `os.getenv()` returning truthy elsewhere is not equivalent to this check: it can't
   tell "unset" apart from "set under a different name."

**Never read or display `.env` contents, under any circumstance — names only, via
`dotenv_values(path).keys()`, never a full read of the file.**

## Who checks what

- The engineer making the change performs both checks above before wiring the var into
  `config.py`.
- `reviewer` **independently re-runs the key-name check** as part of gating any change that adds
  a required credential — do this even if the engineer's report claims they already checked.
  This is exactly the kind of pre-existing/unchanged-line bug a diff-focused review otherwise
  skips (a `load_dotenv()` call that predates this unit of work but only becomes dangerous once
  this change removes its fallback).
- Split ownership: the *decision* that a new key is needed is usually `ai-engineer`'s (e.g.
  adding an LLM provider); the *edit* to `config.py` is `backend-engineer`'s. `ai-engineer`
  states the exact var name and requirement in their report; `backend-engineer` performs both
  checks above before wiring it in.

Referenced by: `CLAUDE.md`, `ai-engineer.md`, `backend-engineer.md`, `reviewer.md`.
