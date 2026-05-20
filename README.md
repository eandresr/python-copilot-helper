# python-copilot-helper

Helper utilities for interacting with GitHub Copilot from the command line.

## Requirements

- Python 3.10+
- `requests` library (`pip install requests`)
- A GitHub account with Copilot access

## `copilot_chat.py`

Interactive (or single-shot) CLI chat with the GitHub Copilot API.

### Features

- **Model selection** — choose from Claude Sonnet / Opus and GPT models.
- **Copilot instructions** — load system instructions from a local path or remote Git
  repository that follows the `.github` Copilot customization structure.
- **Persistent auth** — tokens are cached in `~/.copilot_helper` (chmod 600) so you
  only authenticate once.

### Authentication

The script uses your GitHub account to obtain a Copilot session token. On first run it
will start a GitHub device-flow login. You can also supply credentials via environment
variables to skip the interactive flow:

| Variable | Description |
|---|---|
| `COPILOT_GH_TOKEN` | GitHub OAuth / personal-access token |
| `COPILOT_SESSION_TOKEN` | Pre-obtained Copilot session token (overrides GitHub token exchange) |

### Usage

```
python copilot_chat.py [OPTIONS]
```

| Option | Short | Description |
|---|---|---|
| `--model MODEL` | `-m` | Model to use (default: `claude-sonnet-4-6`) |
| `--instructions-path PATH_OR_URL` | `-i` | Path or Git URL with Copilot instruction files |
| `--message TEXT` | `-M` | Send a single message and exit (non-interactive) |
| `--list-models` | | Print available models and exit |

### Available models

| Model ID | Description |
|---|---|
| `claude-sonnet-4-6` | Claude Sonnet 4.6 — fast & capable **(default)** |
| `claude-opus-4-6` | Claude Opus 4.6 — more powerful, slower |
| `claude-opus-4-7` | Claude Opus 4.7 — latest Opus generation |
| `claude-haiku-4-6` | Claude Haiku 4.6 — lightweight, very fast |
| `gpt-4o` | GPT-4o — OpenAI flagship model |
| `gpt-4o-mini` | GPT-4o Mini — faster, lighter GPT-4o |
| `o1` | o1 — advanced reasoning (slower) |
| `o3-mini` | o3 Mini — efficient reasoning model |

Any model ID supported by the Copilot API can be passed even if it is not in the list
above — the script will warn you and forward it to the API as-is.

### Instruction files

With `--instructions-path` you can point the script at a local directory **or** a
remote Git repository that contains Copilot customization files. The following paths are
searched (relative to the root of the directory / repo):

```
.github/copilot-instructions.md
.github/instructions/*.md
.github/instructions/*.instructions.md
.github/prompts/*.md
.github/prompts/*.prompt.md
```

All found files are concatenated and injected as a **system message** before the
conversation starts, so Copilot will follow your custom instructions for every turn.

#### Examples

```bash
# Use a local checkout of another project's .github rules
python copilot_chat.py -i ~/projects/my-api

# Pull instructions directly from a remote Git repository
python copilot_chat.py -i https://github.com/myorg/my-repo.git

# Combine instructions with a specific model, single-shot
python copilot_chat.py \
  -i https://github.com/myorg/my-repo.git \
  -m claude-opus-4-7 \
  -M "Explain the authentication flow in this project"

# Interactive session with Claude Opus 4.6
python copilot_chat.py -m claude-opus-4-6

# List all available models
python copilot_chat.py --list-models
```
