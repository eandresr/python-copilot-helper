#!/usr/bin/env python3
"""
copilot_chat.py - Send questions to GitHub Copilot from the command line.
Requires Python 3.10+.

Authentication flow:
  1. Checks COPILOT_SESSION_TOKEN env var. If set, validates it with a quick
     API call. Uses it if valid.
  2. If the session token is missing or expired, checks COPILOT_GH_TOKEN env
     var (or the saved credential file at ~/.copilot_helper). Uses the stored
     GitHub OAuth token to request a fresh Copilot session token.
  3. If no GitHub OAuth token is available either, runs the GitHub Device Flow
     to obtain one, saves it to ~/.copilot_helper and to COPILOT_GH_TOKEN for
     the current process, then fetches a Copilot session token.

Usage:
    python copilot_chat.py -q "What is a Python decorator?"
    python copilot_chat.py --question "Explain list comprehensions"
    python copilot_chat.py            # prompts interactively
"""

import argparse
import json
import os
import sys
import time

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Official VS Code Copilot Client ID — verify against
# https://github.com/github/copilot.vim or official Copilot docs before use.
# Alternatively, override this via a COPILOT_CLIENT_ID environment variable.
CLIENT_ID = os.environ.get("COPILOT_CLIENT_ID", "Iv1.b507a08c87ecfe98")
DEVICE_CODE_URL = "https://github.com/login/device/code"
OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"

CREDENTIAL_FILE = os.path.expanduser("~/.copilot_helper")

# Headers that identify this client as the official VS Code Copilot extension,
# required for the Copilot Chat API to accept the request.
COPILOT_CLIENT_HEADERS = {
    "User-Agent": "GithubCopilot/1.155.0",
    "Editor-Version": "vscode/1.85.0",
    "Editor-Plugin-Version": "copilot-chat/0.12.0",
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# Credential persistence helpers
# ---------------------------------------------------------------------------


def _load_saved_github_token() -> str | None:
    """Return the GitHub OAuth token saved in CREDENTIAL_FILE, or None."""
    if not os.path.exists(CREDENTIAL_FILE):
        return None
    try:
        with open(CREDENTIAL_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("gh_token")
    except (json.JSONDecodeError, OSError):
        return None


def _save_github_token(gh_token: str) -> None:
    """Persist the GitHub OAuth token to CREDENTIAL_FILE (chmod 600)."""
    try:
        with open(CREDENTIAL_FILE, "w", encoding="utf-8") as fh:
            json.dump({"gh_token": gh_token}, fh)
        os.chmod(CREDENTIAL_FILE, 0o600)
        print(f"[+] GitHub token saved to {CREDENTIAL_FILE}")
    except OSError as exc:
        print(f"[!] Could not save credentials: {exc}")


# ---------------------------------------------------------------------------
# OAuth Device Flow
# ---------------------------------------------------------------------------


def _run_device_flow() -> str:
    """
    Execute the GitHub OAuth Device Flow.

    Returns the GitHub OAuth access token on success.
    Exits the process on unrecoverable errors.
    """
    print("[*] Starting GitHub device authorization flow...")

    response = requests.post(
        DEVICE_CODE_URL,
        headers={"Accept": "application/json"},
        data={"client_id": CLIENT_ID, "scope": "read:user"},
        timeout=15,
    )
    if response.status_code != 200:
        print(f"[-] Failed to contact GitHub: {response.text}")
        sys.exit(1)

    device_data = response.json()
    device_code = device_data.get("device_code")
    user_code = device_data.get("user_code")
    verification_uri = device_data.get("verification_uri")
    interval = device_data.get("interval", 5)

    print("\n" + "=" * 60)
    print(" AUTHORIZATION REQUIRED ".center(60, "="))
    print(f"  1. Open your browser and go to: {verification_uri}")
    print(f"  2. Enter this exact code:        {user_code}")
    print("=" * 60 + "\n")
    print("Waiting for browser confirmation...", end="", flush=True)

    while True:
        time.sleep(interval)
        print(".", end="", flush=True)

        poll_resp = requests.post(
            OAUTH_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        ).json()

        if "access_token" in poll_resp:
            print("\n\n[+] GitHub authorization successful!")
            return poll_resp["access_token"]

        error = poll_resp.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "expired_token":
            print("\n\n[-] The authorization window expired. Please re-run the script.")
            sys.exit(1)

        print(f"\n\n[-] Authentication error: {error}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Copilot session token helpers
# ---------------------------------------------------------------------------


def _fetch_copilot_session_token(gh_token: str) -> str:
    """
    Exchange a GitHub OAuth token for a short-lived Copilot session token.

    Returns the session token string.
    Exits the process on failure.
    """
    print("[*] Exchanging credentials for a Copilot session token...")

    headers = COPILOT_CLIENT_HEADERS.copy()
    headers["Authorization"] = f"token {gh_token}"

    resp = requests.get(COPILOT_TOKEN_URL, headers=headers, timeout=15)

    if resp.status_code == 200:
        token = resp.json().get("token")
        print("[+] Copilot session token obtained successfully.")
        return token

    print(f"[-] Failed to obtain Copilot session token ({resp.status_code}):")
    print(resp.text)
    sys.exit(1)


def _is_session_token_valid(session_token: str) -> bool:
    """
    Return True if *session_token* is accepted by the Copilot Chat API.

    Sends a minimal request; any 2xx response means the token is active.
    """
    headers = COPILOT_CLIENT_HEADERS.copy()
    headers["Authorization"] = f"Bearer {session_token}"
    headers["Content-Type"] = "application/json"

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }

    try:
        resp = requests.post(COPILOT_CHAT_URL, headers=headers, json=payload, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


# ---------------------------------------------------------------------------
# High-level token management
# ---------------------------------------------------------------------------


def get_valid_session_token() -> str:
    """
    Return a valid Copilot session token, going through each fallback in order:

    1. COPILOT_SESSION_TOKEN env var  → validate → use if valid
    2. COPILOT_GH_TOKEN env var or saved file → refresh session token
    3. Full GitHub Device Flow → save GitHub token → get session token
    """

    # --- Step 1: check existing session token ---
    session_token = os.environ.get("COPILOT_SESSION_TOKEN")
    if session_token:
        print("[*] Found COPILOT_SESSION_TOKEN. Validating...")
        if _is_session_token_valid(session_token):
            print("[+] Session token is active. Proceeding.")
            return session_token
        print("[!] Session token is expired or invalid. Refreshing...")

    # --- Step 2: refresh using stored GitHub OAuth token ---
    gh_token = os.environ.get("COPILOT_GH_TOKEN") or _load_saved_github_token()
    if gh_token:
        print("[*] Found GitHub OAuth token. Obtaining fresh session token...")
        session_token = _fetch_copilot_session_token(gh_token)
        os.environ["COPILOT_SESSION_TOKEN"] = session_token
        return session_token

    # --- Step 3: full Device Flow ---
    print("[*] No stored credentials found. Starting full authentication...")
    gh_token = _run_device_flow()
    os.environ["COPILOT_GH_TOKEN"] = gh_token
    _save_github_token(gh_token)

    session_token = _fetch_copilot_session_token(gh_token)
    os.environ["COPILOT_SESSION_TOKEN"] = session_token
    return session_token


# ---------------------------------------------------------------------------
# Copilot Chat
# ---------------------------------------------------------------------------


def ask_copilot(session_token: str, question: str) -> None:
    """Send *question* to the Copilot Chat API and print the response."""
    print(f"\n[*] Sending question to Copilot: '{question}'")

    headers = COPILOT_CLIENT_HEADERS.copy()
    headers["Authorization"] = f"Bearer {session_token}"
    headers["Content-Type"] = "application/json"

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": question}],
        "temperature": 0.2,
    }

    try:
        response = requests.post(COPILOT_CHAT_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            try:
                answer = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                print(f"[-] Unexpected response structure from Copilot API: {exc}")
                print(f"    Raw response: {response.text[:500]}")
                return
            print("\n" + "=" * 60)
            print(" COPILOT RESPONSE ".center(60, "="))
            print(answer)
            print("=" * 60)
        else:
            print(f"[-] Chat API error ({response.status_code}): {response.text}")
    except requests.RequestException as exc:
        print(f"[-] Network error while contacting Copilot: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask a question to GitHub Copilot from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-q",
        "--question",
        metavar="QUESTION",
        help="The question to send to Copilot. If omitted, you will be prompted.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.question:
        question = args.question.strip()
    else:
        try:
            question = input("Enter your question for Copilot: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[-] No input provided. Exiting.")
            sys.exit(1)

    if not question:
        print("[-] No question provided. Exiting.")
        sys.exit(1)

    valid_token = get_valid_session_token()
    ask_copilot(valid_token, question)


if __name__ == "__main__":
    main()
