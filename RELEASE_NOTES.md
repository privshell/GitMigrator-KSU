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
| **Assistant (optional)** | Chat that explains job errors and suggests next steps. It never runs anything itself.
