---
name: codex-plan
description: Create a plan for addressing a user's request.
---

# Creating a plan from scratch

When asked to create a plan, follow these steps methodically.

**Critical**: The plan document must be **completely self-contained**. A fresh system with no prior context—only the plan document—must be able to understand the problem and implement the solution based solely on what you've written. This means capturing all relevant discoveries, file paths, code patterns, and reasoning in the document itself.

## 1. Understand the Request

Before doing anything else, make sure you understand what the user is asking for:
- Restate the goal in your own words to verify understanding
- Identify any ambiguities, missing context, or unstated assumptions
- If the request is unclear, list specific clarifying questions (do not guess)

## 2. Explore the Codebase

Do targeted exploration to understand the relevant parts of the codebase:
- Search for existing code related to the request (similar features, patterns, utilities)
- Identify the files and modules that will likely need modification
- Understand the existing architecture and conventions used in those areas
- Note any dependencies, APIs, or constraints that affect the implementation

**Do not propose changes to code you haven't read.** Understanding existing patterns prevents introducing inconsistencies.

**Record everything you discover.** Since the plan must be self-contained:
- Include exact file paths (e.g., `src/services/auth.py:45-67`)
- Quote relevant code snippets that show existing patterns to follow
- Document function signatures, class structures, or APIs that will be used
- Explain the "why" behind existing design choices if they affect the implementation

## 3. Consider Approaches

Think through potential solutions:
- For simple, well-defined tasks: identify the straightforward path
- For complex or open-ended tasks: outline 2-3 different approaches with trade-offs
- Consider what already exists that can be reused vs. what needs to be built
- Identify potential risks, edge cases, or complications

## 4. Avoid Over-Engineering

Keep solutions minimal and focused:
- Only include changes directly required by the request
- Don't add features, refactoring, or "improvements" beyond what was asked
- Don't design for hypothetical future requirements
- Prefer simple, direct solutions over clever abstractions
- Three similar lines of code is better than a premature abstraction

## 5. Break Down Into Steps

Create a clear, actionable task breakdown:
- Each step should be concrete and completable
- Order steps by dependency (what must happen before what)
- Group related changes together
- Identify which steps can be done in parallel vs. sequentially

**Include implementation details generously.** For each step:
- Specify exact file paths that need modification
- Include code snippets showing the expected changes (before/after or new code to add)
- Reference specific functions, classes, or methods by name
- Note any imports, dependencies, or configurations needed
- Describe the logic or algorithm in enough detail that someone could write the code directly from your description

## 6. Document Uncertainties

Be explicit about what you don't know:
- List questions that need answers before implementation
- Note assumptions you're making and why
- Identify areas where user input is needed to choose between options

## 7. Write the Plan Document

Create a markdown document in `personal/mengk/plans/` with this structure. Remember: a system with **no prior context** must be able to implement this plan using only this document.

**Err on the side of too much detail.** Include:
- Pseudocode or actual code snippets for non-trivial logic
- Data structures and their schemas
- API signatures and expected request/response formats
- Configuration values and environment variables
- Error handling strategies for likely failure modes

The goal is that implementation becomes straightforward transcription rather than creative problem-solving.

---

# Updating a plan based on feedback

When the user asks you to update an existing plan based on their feedback, follow this process.

## How Feedback Works

Users will often respond to questions or provide feedback **inline** directly in the plan markdown file. For example, if your plan included:

```markdown
## Questions
1. Should we use Redis or in-memory caching?
2. What's the expected cache TTL?
```

The user might edit the file to add their responses inline:

```markdown
## Questions
1. Should we use Redis or in-memory caching?
   - USER: ...
2. What's the expected cache TTL?
   - USER: ...
```

## Steps to Update the Plan

1. **Re-read the plan file** - Always start by reading the current state of the plan document. The user may have added answers, corrections, or new requirements anywhere in the file.

2. **Look for inline replies** - Scan for user responses, which may appear as comments or annotations added anywhere in the document.

3. **Incorporate the feedback** - Update the plan to reflect the user's input:
   - Move answered questions into the resolved context (don't just delete them—the answers are valuable context)
   - Revise the approach if the user's answers change the design
   - Update the steps to reflect any new requirements or constraints
   - Remove or revise any parts the user has rejected

4. **Maintain self-containment** - After updating, the plan must still be fully self-contained. A fresh system reading only the updated plan should understand everything, including:
   - What the original questions were
   - What the user decided
   - Why those decisions affect the approach

5. **Flag new uncertainties** - If the user's feedback raises new questions or reveals gaps, document those clearly.
