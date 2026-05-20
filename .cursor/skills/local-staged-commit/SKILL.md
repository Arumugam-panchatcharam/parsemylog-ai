---
name: local-staged-commit
description: >-
  Creates a local git commit with a conventional subject line and a bullet-list
  body summarizing only staged changes (index), never unstaged files. Use when
  the user asks to commit staged changes only, make a local commit with a
  descriptive message, or commit what is already staged without pushing.
---

# Local commit (staged-only message)

## Goal

Run **`git commit`** in the current project so the message **summarizes only what is staged** (`git diff --cached`). Use a **subject line** plus an **additional body**: a blank line after the subject, then **`-` bullets** (one bullet per logical change or theme). Do **not** push. Do **not** describe unstaged or untracked work unless the user explicitly asked to include it.

## Preconditions

1. **Repository**: Use the workspace / project root that contains `.git` (or `git rev-parse --show-toplevel`).
2. **Staged changes**: If `git diff --cached --quiet` (nothing staged), **stop** and tell the user to stage files first (`git add …`). Do not run `git commit`.

## Steps

1. **Inspect staged diff only** (required source of truth for the message):

   ```bash
   git diff --cached --stat
   git diff --cached
   ```

   Optionally list staged paths:

   ```bash
   git diff --cached --name-only
   ```

2. **Write the message**:
   - **Subject**: one imperative line (roughly 50–72 characters when practical; longer is OK if needed). If the repo uses conventional commits, keep that style (`fix(scope): …`, `feat(scope): …`, `chore(scope): …`, etc.).
   - **Body**: after a blank line, add **several short bullets**. Each bullet should capture one cohesive change reflected in the **staged** diff (feature areas, behavior, notable config). Phrase bullets in sentence case; end with a period unless the line is a short label.
   - Do **not** paste raw diffs or stack traces into the message.
   - **Subject-only** is acceptable only when the staged change is a single trivial edit; default to **subject + bullets**.

3. **Commit locally** (subject and body):

   Prefer two `-m` arguments: first is the subject, second is the bullet block (include leading `- ` on each line, separated by newlines inside the quoted string).

   ```bash
   git commit -m "fix(scope): short subject" -m "- First concrete change drawn from staged diff.
   - Second concrete change.
   - Third concrete change."
   ```

   Alternatively use a single here-doc if the shell makes quoting easier:

   ```bash
   git commit -F - <<'EOF'
   fix(scope): short subject

   - First concrete change drawn from staged diff.
   - Second concrete change.
   EOF
   ```

4. **Do not**:
   - `git push`
   - `git add` or stage extra files unless the user explicitly asked to
   - Base the message on `git diff` (working tree) without `--cached`
   - Amend (`git commit --amend`) unless the user asked

## Examples

**Staged**: small fix in `nginx/default.conf` (single obvious tweak)  
**Message** (subject only is fine):

```text
fix(nginx): correct proxy_pass for api
```

**Staged**: analytics refactor in two Python files  
**Message**:

```text
refactor(analytics): ETL consolidated io paths

- consolidated_io: centralize layout resolution for device batches.
- polars_etl: narrow schema for health frames before Parquet write.
```

**Staged**: multi-area reliability and performance work  
**Message** (verbatim shape to target):

```text
fix(pattern-analyzer, cpe-overview): scan reliability and perf

- Stream Consolelog soft-reboot parsing to avoid GB read_text stalls during reboot extraction.
- Extend ISO timestamp parsing for minute-only forms (e.g. YYYY-MM-DDTHH:MM).
- Pattern Analyzer: expose rg_timeout_sec on 202 responses; align client poll budget with server timeouts and UI progress/overflow tweaks.
- Cross-CPE overview pattern scan: chunk batched ripgrep passes (CPE_OVERVIEW_PATTERN_BATCH_CHUNK) to cap Python attribution cost when many domains are enabled; remove debug instrumentation.
- Regex analyzer: configurable rg timeout/max-filesize defaults for large uploads.
```

## Verification

After committing, optionally confirm:

```bash
git show -1 --stat
```

Ensure the committed files match what was intended to be staged.
