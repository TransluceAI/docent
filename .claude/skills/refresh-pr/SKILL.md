---
name: refresh-pr
description: Closes current PR and opens a fresh one to clear AI code reviewer history.
---

# Refresh PR

When this skill is invoked, close the current PR and create a new one with a fresh description. This clears the review history for AI code reviewers.

## Workflow

1. **Get PR info**: Run `gh pr view --json number,baseRefName,url` to get:
   - The PR number (to close)
   - The base branch name
   - The PR URL (to reference when closing)

2. **Close the current PR**: Run `gh pr close <number>`

3. **Analyze changes**:
   - Run `git diff <base>...HEAD` to see all changes
   - Run `git log <base>...HEAD --oneline` to see commit history
   - Understand the full scope of what changed

4. **Create a new PR** using `gh pr create`:
   - Draft a fresh title summarizing the changes
   - Draft a fresh description focusing on the "why" behind changes

5. **Report**: Show the new PR URL to the user
