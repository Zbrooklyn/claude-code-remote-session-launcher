---
description: "First-time setup for the /window and /daemon families. Walks through 5 questions and writes ~/.claude/window-config.json."
argument-hint: ""
---

# /window-setup — Interactive Configuration

You are running first-time setup for the /window family of spawn commands. Walk the user through **exactly 5 questions** using the `AskUserQuestion` tool (one question at a time). After all 5 answers, write the config file to `~/.claude/window-config.json` and confirm success.

**Tone:** terse, mobile-friendly, no markdown formatting in the answers you display (this may be invoked from a mobile/Telegram channel). Each question is multiple-choice. Use AskUserQuestion's structured options.

---

## Before Question 1: detect trusted directories

Read `~/.claude.json` and extract entries from `projects.<path>.hasTrustDialogAccepted == true`. Surface up to 4 of these as auto-detected options for Question 1, prioritizing entries with forward slashes and recognizable workspace roots (anything under `Documents`, `Downloads`, or `Desktop`). De-duplicate by case-insensitive normalized path.

## Question 1 — Default workspace path

"Which directory should /window open by default when called with no arguments?"

Options:
- Each auto-detected trusted directory as its own option (use the exact trust-list string as both display and value)
- "Custom path" — if picked, prompt with a follow-up freeform AskUserQuestion asking for the absolute path, then verify it exists on disk before continuing. If it doesn't exist, re-ask.

## Question 2 — Default permission mode

"What permission mode should /window use by default?"

Options:
- "Standard — Claude asks before risky actions" (default; recommended)
- "YOLO — skip permission checks, autonomous"

## Question 3 — Default remote control behavior

"Should /window attach Anthropic remote-control by default?"

Options:
- "No — only attach when I use the -remote variant" (recommended; matches the family structure)
- "Yes — every spawn is reachable from claude.ai/code"

## Question 4 — Extra allow-list

"Want to maintain an extra allow-list for directories you haven't opened in Claude locally but have vetted?"

Options:
- "Skip — rely only on Claude's trust list" (recommended)
- "Yes — I'll add directories later by editing the config file"

## Question 5 — Confirm and write

Surface a plain-prose summary of the 4 answers and ask:

"Write this config to ~/.claude/window-config.json?"

Options:
- "Yes, write it"
- "Restart — let me re-answer"

If "Restart" — go back to Question 1.
If "Yes" — write the config file with this exact shape:

```json
{
  "default_workspace": "<from Q1>",
  "default_yolo": <true if Q2=YOLO else false>,
  "default_remote": <true if Q3=Yes else false>,
  "extra_allow_list": [],
  "_note": "Edit extra_allow_list to add directories not in Claude's trust list. Re-run /window-setup to regenerate."
}
```

After writing, confirm in plain prose: "Setup complete. /window will open <default> by default. Run /window to test."

---

## Notes for the model running this skill

- Use the `Write` tool to create the JSON file. Use `Read` first if file already exists (to back it up by renaming to `window-config.json.bak-<timestamp>` before overwriting).
- Don't deviate from the 5-question flow. Don't add extra steps.
- If the user opts to skip questions ("just use defaults"), accept that and write a config using all the recommended defaults plus their current working directory as default_workspace if it's in the trust list.
- This skill should complete in under 2 minutes. No long-form prose between questions.
