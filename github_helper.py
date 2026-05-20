"""GitHub helper utilities for python-copilot-helper."""

import os
import sys


def resolve_github_token() -> str:
    """Return the GitHub token from environment variables.

    Reads GH_TOKEN and GITHUB_TOKEN from the environment. If only one is set,
    that value is returned. If both are set to the same value, that value is
    returned. If both are set to *different* values the script exits with an
    error to avoid ambiguity about which token should be used.

    Raises SystemExit if no token is found or if the two variables disagree.
    """
    gh_token = os.environ.get("GH_TOKEN")
    github_token = os.environ.get("GITHUB_TOKEN")

    if gh_token and github_token and gh_token != github_token:
        print(
            "Error: ambiguous GitHub token — both GH_TOKEN and GITHUB_TOKEN are set "
            "with different values. Please unset one of them.",
            file=sys.stderr,
        )
        sys.exit(1)

    token = gh_token or github_token

    if not token:
        print(
            "Error: a GitHub token is required. "
            "Set the GH_TOKEN or GITHUB_TOKEN environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    return token
