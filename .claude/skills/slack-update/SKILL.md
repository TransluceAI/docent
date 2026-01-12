---
name: slack-update
description: Generates a Slack-ready markdown file summarizing codebase changes for stakeholders (team members, customers, etc.)
---

# Slack Update Generator

When this skill is invoked, the user has provided context about changes they want to communicate. Your job is to write a `.md` file that can be copied directly into Slack.

## Output Location

Write the update to `personal/mengk/updates/` with a descriptive filename like `update-<topic>.md`. Create the directory if it doesn't exist.

## Formatting Rules

Slack has limited markdown support. Follow these rules:

- Use `*bold*` sparingly for emphasis (not `**bold**`)
- Use `_italics_` if needed
- Use simple (possibly nested) bullet lists with `*`
- Use `code` for technical terms, function names, etc.
- Do NOT use headers (`#`, `##`) or horizontal rules (`---`)
- Use blank lines to separate sections

## Tone

- Professional but casual - this is Slack, not a formal document
- Direct and clear - assume the reader is busy
- No fluff or filler phrases
- Explain technical details at the right level for the audience (infer from context)
- Prefer bullet points (including nested bullets) to explain things - they're easier to scan than prose.
