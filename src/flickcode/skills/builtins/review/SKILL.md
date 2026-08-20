---
name: review
description: Review the current project for correctness, risks, and missing tests
tools:
  - read_file
  - glob
  - grep
  - review_project_snapshot
mode: isolated
history: 2
---
Review the current project independently. The requested focus is: {{input}}

1. Use the project snapshot to orient yourself, then inspect the most relevant files and changes.
2. Prioritize concrete correctness bugs, security risks, regressions, and missing tests.
3. Cite file paths and precise locations whenever evidence permits.
4. Distinguish confirmed findings from questions or low-confidence risks.
5. End with a concise handoff ordered by severity; say explicitly when no actionable findings remain.

