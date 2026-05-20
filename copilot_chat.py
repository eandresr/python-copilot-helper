#!/usr/bin/env python3
"""
copilot_chat.py - CLI for interacting with GitHub Copilot Chat API.

Supports model selection and loading Copilot instruction files from a local
path or a remote Git repository (same structure as .github/copilot-instructions.md,
.github/instructions/, and .github/prompts/).
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"  # GitHub Copilot client id (public)

TOKEN_FILE = Path.home() / ".copilot_helper"

# Model registry: api-id -> human description
AVAILABLE_MODELS: dict[str, str] = {
    "claude-sonnet-4-6": "Claude Sonnet 4.6 — fast & capable (default)",
    "claude-opus-4-6": "Claude Opus 4.6 — more powerful, slower",
    "claude-opus-4-7": "Claude Opus 4.7 — latest Opus generation",
    "claude-haiku-4-6": "Claude Haiku 4.6 — lightweight, very fast",
    "gpt-4o": "GPT-4o — OpenAI flagship model",
    "gpt-4o-mini": "GPT-4o Mini — faster, lighter GPT-4o",
    "o1": "o1 — advanced reasoning (slower)",
    "o3-mini": "o3 Mini — efficient reasoning model",
}
DEFAULT_MODEL = "claude-sonnet-4-6"

# Copilot instruction file patterns (relative to a repo/path root)
INSTRUCTION_GLOBS = [
    ".github/copilot-instructions.md",
    ".github/instructions/*.md",
    ".github/instructions/*.instructions.md",
    ".github/prompts/*.md",
    ".github/prompts/*.prompt.md",
]


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


def _load_token_file() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_token_file(data: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # chmod 600


def get_github_token() -> str:
    """Return a GitHub OAuth token from env, token file, or interactive login."""
    if token := os.environ.get("COPILOT_GH_TOKEN"):
        return token
    stored = _load_token_file()
    if token := stored.get("github_token"):
        return token
    return _github_device_login()


def _github_device_login() -> str:
    """Interactive GitHub device-flow OAuth to obtain a token."""
    resp = requests.post(
        GITHUB_DEVICE_CODE_URL,
        headers={"Accept": "application/json"},
        data={"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    device_code = data["device_code"]
    interval = data.get("interval", 5)
    print(f"\nOpen this URL in your browser:\n  {data['verification_uri']}")
    print(f"Enter code: {data['user_code']}\n")
    while True:
        time.sleep(interval)
        token_resp = requests.post(
            GITHUB_ACCESS_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
        token_data = token_resp.json()
        if "access_token" in token_data:
            token = token_data["access_token"]
            stored = _load_token_file()
            stored["github_token"] = token
            _save_token_file(stored)
            print("Authenticated successfully.\n")
            return token
        error = token_data.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        sys.exit(f"Authentication failed: {token_data}")


def get_copilot_session_token(github_token: str) -> str:
    """Exchange a GitHub token for a short-lived Copilot session token."""
    if session_token := os.environ.get("COPILOT_SESSION_TOKEN"):
        return session_token
    resp = requests.get(
        COPILOT_TOKEN_URL,
        headers={
            "Authorization": f"token {github_token}",
            "Accept": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Instruction loading
# ---------------------------------------------------------------------------


def _collect_instruction_files(root: Path) -> list[Path]:
    """Return all instruction files found under *root* matching known patterns."""
    files: list[Path] = []
    for pattern in INSTRUCTION_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    # deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def load_instructions(instructions_path: str) -> str:
    """
    Load Copilot instruction content from *instructions_path*.

    *instructions_path* can be:
    - A local filesystem path (absolute or relative).
    - A remote Git URL (anything containing "://" or ending with ".git").

    Returns a single string with all instruction content concatenated, or an
    empty string if no files are found.
    """
    is_git_url = "://" in instructions_path or instructions_path.endswith(".git")

    if is_git_url:
        tmp_dir = tempfile.mkdtemp(prefix="copilot_instr_")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", instructions_path, tmp_dir],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                print(
                    f"Warning: could not clone {instructions_path}:\n{result.stderr}",
                    file=sys.stderr,
                )
                return ""
            root = Path(tmp_dir)
            content = _read_instruction_files(root)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        root = Path(instructions_path).expanduser().resolve()
        if not root.exists():
            print(
                f"Warning: instructions path does not exist: {root}",
                file=sys.stderr,
            )
            return ""
        content = _read_instruction_files(root)

    if not content:
        print(
            f"Warning: no Copilot instruction files found under {instructions_path}",
            file=sys.stderr,
        )
    return content


def _read_instruction_files(root: Path) -> str:
    files = _collect_instruction_files(root)
    parts: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8").strip()
            if text:
                parts.append(f"<!-- Instructions from {f.relative_to(root)} -->\n{text}")
        except OSError as exc:
            print(f"Warning: could not read {f}: {exc}", file=sys.stderr)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Copilot API
# ---------------------------------------------------------------------------


def chat_completion(
    session_token: str,
    messages: list[dict],
    model: str,
) -> str:
    """Call the Copilot chat completions endpoint and return the reply text."""
    headers = {
        "Authorization": f"Bearer {session_token}",
        "Content-Type": "application/json",
        "Copilot-Integration-Id": "vscode-chat",
        "Editor-Version": "vscode/1.90.0",
        "Editor-Plugin-Version": "copilot-chat/0.17.0",
        "User-Agent": "GitHubCopilotChat/0.17.0",
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    resp = requests.post(COPILOT_CHAT_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    model_help_lines = ["Available models:"]
    for mid, desc in AVAILABLE_MODELS.items():
        model_help_lines.append(f"  {mid:<22} {desc}")
    model_help = "\n".join(model_help_lines)

    parser = argparse.ArgumentParser(
        prog="copilot_chat.py",
        description="Chat with GitHub Copilot from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=model_help,
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        metavar="MODEL",
        help=(
            f"Model to use for the conversation (default: {DEFAULT_MODEL}). "
            "See the available models list below."
        ),
    )
    parser.add_argument(
        "--instructions-path",
        "-i",
        metavar="PATH_OR_URL",
        help=(
            "Local path or Git repository URL that contains Copilot instruction files "
            "(e.g., .github/copilot-instructions.md, .github/instructions/*.md, "
            ".github/prompts/*.md). The content is injected as a system message."
        ),
    )
    parser.add_argument(
        "--message",
        "-M",
        metavar="TEXT",
        help="Send a single message and print the reply (non-interactive mode).",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Print the list of available models and exit.",
    )
    return parser


def interactive_loop(
    session_token: str,
    model: str,
    messages: list[dict],
) -> None:
    print(f'Copilot Chat [{model}] — type "exit" or press Ctrl-C to quit.\n')
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Goodbye.")
            break
        messages.append({"role": "user", "content": user_input})
        try:
            reply = chat_completion(session_token, messages, model)
        except requests.HTTPError as exc:
            print(f"API error: {exc}", file=sys.stderr)
            messages.pop()  # remove failed user message
            continue
        messages.append({"role": "assistant", "content": reply})
        print(f"\nCopilot: {reply}\n")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_models:
        print("Available models:\n")
        for mid, desc in AVAILABLE_MODELS.items():
            marker = " (default)" if mid == DEFAULT_MODEL else ""
            print(f"  {mid:<22} {desc}{marker}")
        return

    # Validate model
    if args.model not in AVAILABLE_MODELS:
        print(
            f"Warning: '{args.model}' is not in the known models list. "
            "Proceeding anyway — the API will reject it if invalid.",
            file=sys.stderr,
        )

    # Build initial messages
    messages: list[dict] = []

    if args.instructions_path:
        instructions = load_instructions(args.instructions_path)
        if instructions:
            messages.append({"role": "system", "content": instructions})

    # Authenticate
    github_token = get_github_token()
    session_token = get_copilot_session_token(github_token)

    if args.message:
        # Non-interactive single-shot mode
        messages.append({"role": "user", "content": args.message})
        try:
            reply = chat_completion(session_token, messages, args.model)
            print(reply)
        except requests.HTTPError as exc:
            sys.exit(f"API error: {exc}")
    else:
        # Interactive chat loop
        interactive_loop(session_token, args.model, messages)


if __name__ == "__main__":
    main()
