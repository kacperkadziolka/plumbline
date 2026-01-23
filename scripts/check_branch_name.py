#!/usr/bin/env python3
"""Check that branch name follows conventional naming."""

import re
import subprocess
import sys

ALLOWED_PREFIXES = ("feat", "fix", "chore", "docs", "refactor", "test", "ci")
PATTERN = re.compile(rf"^({'|'.join(ALLOWED_PREFIXES)})/[a-z0-9._-]+$")


def get_branch_name() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> int:
    branch = get_branch_name()

    # Allow main branch and detached HEAD
    if branch in ("main", "master", "HEAD"):
        return 0

    if not PATTERN.match(branch):
        print(f'Branch name "{branch}" does not follow convention.')
        print(f"Use: {'/'.join(ALLOWED_PREFIXES)}/description")
        print("Example: feat/add-user-auth")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
