---
name: commit
description: Inspect changes and create a focused Git commit
tools:
  - read_file
  - glob
  - grep
  - execute_command
mode: shared
---
Create a careful Git commit for the user's request: {{input}}

1. Inspect repository status and relevant diffs before staging anything.
2. Separate unrelated user changes and never discard or rewrite them.
3. Run the smallest relevant verification when practical.
4. Stage only files belonging to this request.
5. Write a concise commit message that explains the outcome.
6. Report the commit identifier, verification, and any files intentionally left unstaged.

