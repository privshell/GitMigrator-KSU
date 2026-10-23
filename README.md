# Git Migrator

An AMOLED-black **KernelSU WebUI module** for moving GitHub projects between accounts, straight from your rooted phone.

Back up every repo as a full mirror, push them (all branches, tags and history) to a new account, upload any folder to a repo, and fix old-username links across many projects, all from one screen.

## Features

| Area | What it does |
|---|---|
| **File browser** | Browse internal storage with root access, pick a project folder. |
| **Folder → repo** | Upload a folder as a new commit on a branch, or push a folder's own `.git` with all branches and tags. Empty repos work. |
| **Link fixer** | Replaces `github.com/OLD/…`, `raw.githubusercontent.com/OLD/…`, `OLD.github.io`, `git@github.com:OLD/…`, shields.io badges, `ghcr.io` and `uses: OLD/…` with the new account. Shows a preview first; supports renamed repos. |
| **Backup** | Mirrors every repo of the source account (public and private), plus wikis. Re-running only updates. |
| **Migrate** | Pushes mirrors to the new account with all branches, tags and history. Creates missing repos and sets the default branch. A delay between repos reduces the chance of being flagged again. |
| **Tools** | `git fsck` health check, plus a `HISTORY.txt` and a `.bundle` file per project as a history reference. |
| **Assistant (optional)** | Chat that explains job errors and suggests next steps. It never runs anything itself. |

## Requirements

- Android with **KernelSU** (or a compatible root manager with WebUI support)
- **Termux** with Python and Git:

```sh
pkg install python git
```

## Install

1. Download `GitMigrator-KSU.zip`.
2. KernelSU Manager → **Modules** → install from storage.
3. Reboot, then tap the module to open its WebUI.
4. On the **Home** tab, run the **environment check**.

## Usage

1. **Repos tab → Accounts:** connect the destination account token. The source token is only needed for backing up straight from GitHub.
2. **Backup** (optional) mirrors the old account, or point *Backup folder* at mirrors you already have.
3. **Migrate:** select projects, keep the delay at 30 s or more, start.
4. **Files tab:** pick a project folder, then **Fix links** (preview first) or **Upload to repo**.

### Token scopes

Use a **classic** token with `repo` and `workflow`. Without `workflow`, pushes that contain `.github/workflows/*` are rejected.

## Where data lives

| Path | Content |
|---|---|
| `/data/adb/gitmigrator/config.json` | Tokens and settings (`chmod 600`, root only) |
| `/data/adb/gitmigrator/backup/` | Mirrors, wikis, exports (changeable in the app) |
| `/storage/emulated/0/GitHubBackup/exports/` | Copies of history exports |

Uninstalling the module keeps this folder on purpose. Remove it manually with `rm -rf /data/adb/gitmigrator`.

## Security notes

- Tokens are passed to git through environment config scoped to `github.com`. They never appear in URLs or in `.git/config`, and git output is scrubbed of them.
- Migrating **force-pushes** matching branches and tags to the destination repo. Existing content there is replaced.
- The assistant uses **your own Anthropic API key** (billed separately from any Claude app subscription). When you chat, the recent messages, the selected folder path and the last job log are sent to the API. Without a key it stays off and nothing is sent.

## Limitations

- Issues, pull requests, releases and GitHub Pages settings are **not** migrated, only git data (and wikis).
- Links to old issue numbers or release assets will not work until you recreate them in the new repo.
- Git does not track empty folders, and GitHub rejects single files above 100 MB.
- Modules whose `updateJson` points at the old account will not update until you ship a new version that points at the new URL.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "python3 not found" | `pkg install python git` in Termux, then reopen the WebUI. |
| Network check fails | Check the connection or VPN for root processes, then rerun the check. |
| Push rejected for workflow files | The token needs the `workflow` scope. |
| Operation seems stuck | Open the job bar and tap **Stop**. Re-running resumes from the mirrors. |

## License

MIT. See [LICENSE](LICENSE).
