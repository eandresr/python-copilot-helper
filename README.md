# python-copilot-helper

Helper utilities for interacting with GitHub Copilot via scripts.

---

## `copilot_chat.py` — Ask Copilot from the command line

Send a question to the GitHub Copilot Chat API directly from your terminal,
with automatic token management so you only need to authorize once.

### Features

| Feature | Description |
|---------|-------------|
| **argparse** | Uses `-q`/`--question` key-value argument (or interactive prompt) |
| **Env-var token storage** | Copilot session token stored in `COPILOT_SESSION_TOKEN`; GitHub OAuth token in `COPILOT_GH_TOKEN` |
| **Automatic validation** | On every run the script checks whether the stored session token is still active |
| **Seamless refresh** | If the session token is expired the script uses the saved GitHub OAuth token to obtain a fresh one — no re-authorization needed |
| **One-time Device Flow** | Only runs the full GitHub Device Flow when no credentials are found at all |

---

### Requirements

- Python 3.10+
- [`requests`](https://pypi.org/project/requests/) library

```bash
pip install requests
```

---

### Usage

```bash
# Pass the question as a command-line argument
python copilot_chat.py -q "What is a Python decorator?"
python copilot_chat.py --question "Explain list comprehensions in Python"

# Or run without arguments and type the question when prompted
python copilot_chat.py
```

---

### Authentication flow

The script follows this sequence on every run:

```
1. COPILOT_SESSION_TOKEN env var set?
   ├─ YES → validate with a quick API call
   │         ├─ valid   → use it ✓
   │         └─ expired → go to step 2
   └─ NO  → go to step 2

2. COPILOT_GH_TOKEN env var set, or ~/.copilot_helper file present?
   ├─ YES → exchange GitHub OAuth token for a fresh session token ✓
   └─ NO  → go to step 3

3. Run full GitHub Device Flow (one-time browser authorization)
   → save GitHub OAuth token to COPILOT_GH_TOKEN env var
     and to ~/.copilot_helper (chmod 600)
   → obtain Copilot session token ✓
```

After the first successful run, step 3 is never needed again. The GitHub
OAuth token persists in `~/.copilot_helper` and will be used to silently
refresh the short-lived Copilot session token on future runs.

---

### Environment variables

| Variable | Description |
|----------|-------------|
| `COPILOT_SESSION_TOKEN` | Short-lived Copilot Chat session token. Set automatically by the script; you can also pre-set it if you already have one. |
| `COPILOT_GH_TOKEN` | Long-lived GitHub OAuth token obtained via Device Flow. Set automatically and persisted to `~/.copilot_helper`. |

To pre-load credentials in your shell session:

```bash
export COPILOT_GH_TOKEN="gho_xxxxxxxxxxxxxxxxxxxx"
```

---

### Credential file

`~/.copilot_helper` is a JSON file created with permissions `600`:

```json
{"gh_token": "gho_xxxxxxxxxxxxxxxxxxxx"}
```

Delete it to force a fresh Device Flow authorization.

---

### Example session (first run)

```
[*] No stored credentials found. Starting full authentication...
[*] Starting GitHub device authorization flow...

============================================================
=================== AUTHORIZATION REQUIRED =================
  1. Open your browser and go to: https://github.com/login/device
  2. Enter this exact code:        ABCD-1234
============================================================

Waiting for browser confirmation..........

[+] GitHub authorization successful!
[+] GitHub token saved to /home/user/.copilot_helper
[*] Exchanging credentials for a Copilot session token...
[+] Copilot session token obtained successfully.

[*] Sending question to Copilot: 'What is a Python decorator?'

============================================================
==================== COPILOT RESPONSE ======================
A decorator in Python is a function that takes another function
as an argument and extends or alters its behavior without
explicitly modifying it...
============================================================
```

### Example session (subsequent runs)

```
[*] Found COPILOT_SESSION_TOKEN. Validating...
[+] Session token is active. Proceeding.

[*] Sending question to Copilot: 'Explain list comprehensions'
...
```

---

### License

See [LICENSE](LICENSE).
