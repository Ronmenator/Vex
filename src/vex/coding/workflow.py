"""Coding workflow — plan, code, test, iterate orchestration.

This module is not a separate mode. It provides utilities that the agent
uses naturally when working on coding tasks. The system prompt encourages
the agent to use these patterns.
"""

from __future__ import annotations

CODING_SYSTEM_PROMPT_ADDON = """\

## Coding Workflow

When working on coding tasks, follow this pattern:

1. **Understand**: Use `file_read`, `glob`, and `grep` to explore the existing codebase before making changes.

2. **Plan**: Think about what needs to change. For multi-file changes, work through them systematically.

3. **Implement**: Use `file_write` to create new files and `file_edit` to modify existing files.
   - Always read a file before editing it
   - Use exact string matching for edits — include enough context for uniqueness

4. **Test**: Use `shell` to run the project's test suite after making changes.
   - If tests fail, read the failure output carefully
   - Read the failing test to understand what's expected
   - Fix the implementation and re-test
   - Iterate up to 3 times per failure before asking the user

5. **Verify**: After tests pass, do a final review of your changes.

Important:
- Create directories with file_write (parent dirs are created automatically)
- For new projects, start with the project structure, then implement files
- Write tests alongside implementation when appropriate
- If you're unsure about the project's test framework, check for pytest.ini, setup.cfg, or package.json
"""
