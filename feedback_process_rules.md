---
name: feedback-process-rules
description: MANDATORY process rules the user set at session start. Must be applied in every future session without exception. Violating any of these causes user to distrust the session entirely.
metadata:
  type: feedback
---

# Mandatory Process Rules — REWARD SCHEME Sessions

These rules were set by the owner (Soheb Khan) at session start and must be followed every time.

## Rule 1 — Approval Before Every Code Edit
**Rule:** Ask the user for approval BEFORE making any file edit. Show the exact before/after diff in plain text. Wait for explicit "approved" before calling Edit/Write.
**Why:** User distrusted changes made without consent. Quote: "i doubted you that you have made some changes are even authentic or not?"
**How to apply:** Present proposed changes as a numbered list with file:line and before/after code blocks. Only proceed when user replies "approved" or equivalent.

## Rule 2 — Session Signature on Every Edited Block
**Rule:** Every edited code block MUST have this comment immediately before the changed lines:
```
# SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
```
**Why:** Traceability — owner needs to audit which session made which change.
**How to apply:** Add the comment as the FIRST line of every edited block, before the actual code change.

## Rule 3 — Auto Git Commit + Push After Every Edit
**Rule:** After every single file edit (not batched), immediately run:
```bash
git config user.name  "Soheb Khan User 2"
git config user.email "Sohebkhan.sk11"
git add <file>
git commit -m "..."
git push
```
**Why:** Owner needs each change independently tracked and deployed to Render.
**How to apply:** Each commit message must describe the specific bug/fix. Never batch multiple file changes into one commit unless they are a single atomic fix.

## Rule 4 — Git Identity (Always Set Before Committing)
```
user.name  = "Soheb Khan User 2"
user.email = "Sohebkhan.sk11"
```
Set with `git config user.name/user.email` at each commit (not globally assumed).

## Rule 5 — Render Auto-Deploy
Render is connected to GitHub main branch. Every push triggers a new deploy automatically. No manual deployment action required.
