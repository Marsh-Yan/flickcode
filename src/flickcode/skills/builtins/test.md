---
name: test
description: Find and run the most relevant project tests
tools:
  - read_file
  - glob
  - grep
  - execute_command
mode: shared
---
Test the project with this focus: {{input}}

1. Inspect project metadata and nearby tests to identify the native test command.
2. Start with the narrowest relevant test target.
3. If it passes and risk warrants it, expand to the related suite.
4. Do not alter product code merely to hide a failure.
5. Report exact commands, pass/fail counts, and a concise diagnosis for failures.

