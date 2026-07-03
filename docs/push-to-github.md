# Pushing to GitHub

How to commit and push changes from the server to the project repo.

**Repo:** [github.com/mdw223/evolution-api](https://github.com/mdw223/evolution-api)  
**Project root:** `/mnt/1tb/evolution-api`

Before your first push (or before making the repo public), read [github-prep.md](github-prep.md) — rotate secrets and confirm nothing sensitive is staged.

---

## SSH key (one-time on this server)

This server uses a **deploy key** (`~/.ssh/evolution_api_deploy`) instead of your personal GitHub SSH key. SSH is configured in `~/.ssh/config`:

```
Host github-evolution-api
  HostName github.com
  User git
  IdentityFile ~/.ssh/evolution_api_deploy
  IdentitiesOnly yes
```

Test authentication:

```bash
ssh -T git@github-evolution-api
# Expected: Hi mdw223/evolution-api! You've successfully authenticated...
```

If you see `Permission denied (publickey)`, the deploy key is missing or not added to the repo on GitHub (**Settings → Deploy keys**).

---

## Git remote (one-time per clone)

The remote must use the SSH host alias so Git picks up the deploy key:

```bash
cd /mnt/1tb/evolution-api

# First time only
git remote add origin git@github-evolution-api:mdw223/evolution-api.git

# If origin already points at git@github.com:... (will fail without your personal key)
git remote set-url origin git@github-evolution-api:mdw223/evolution-api.git

git remote -v
```

---

## Push workflow

```bash
cd /mnt/1tb/evolution-api

# 1. See what changed
git status
git diff

# 2. Optional: scan for secrets before staging (see github-prep.md)
git diff --cached | grep -iE 'password|api_key|apikey' | grep -v change_me | grep -v example || true

# 3. Stage and commit
git add <files>          # or git add docs/ scripts/ etc.
git commit -m "feat(nc-triangle): short description of why"

# 4. Push
git push -u origin main
```

**Commit message style** (match existing history):

- `feat(nc-triangle): ...` — new feature or script
- `fix(nc-triangle): ...` — bug fix
- `docs(nc-triangle): ...` — documentation only

---

## Never commit

These are gitignored and must stay on the server only:

| Path | Why |
|------|-----|
| `.env` | Passwords, API keys |
| `postgres-data/`, `redis-data/` | Database files |
| `logs/` | Runtime logs, pid files |
| `instances/` | WhatsApp session credentials |
| `forwarder/config.yaml` | May reference local paths (use `config.example.yaml` in git) |

Verify a file is ignored:

```bash
git check-ignore -v .env postgres-data logs/
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Permission denied (publickey)` on push | Use remote `git@github-evolution-api:mdw223/evolution-api.git`, not `git@github.com:...`. Run `ssh -T git@github-evolution-api`. |
| `rejected (fetch first)` | Remote has commits you don't have: `git pull --rebase origin main`, then push again. |
| Accidentally staged `.env` | `git restore --staged .env` before committing. |
| Pre-commit hook slow / fails | Hooks run via husky; fix lint errors or run the hook command it prints. |

---

## Related docs

- [github-prep.md](github-prep.md) — secrets, gitignore checklist, first-time clone
- [commands.md](commands.md) — run/stop the stack on the server
