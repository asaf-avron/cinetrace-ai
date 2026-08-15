# Public-repo flip checklist

CineTrace AI stays **private** until the board timing decision. Target flip: **~Sep 1, 2026**. Devpost deadline: **Sep 9, 2026 @ 2:00pm PDT**.

Do **not** change GitHub visibility in this document's lifetime until the board says go. Adding `LICENSE` is not the same as going public.

Repo: `https://github.com/asaf-avron/cinetrace-ai`  
Devpost: [Agentic Cinema](https://agentic-cinema.devpost.com/) (ClickHouse track)

## Already done

- [x] Apache-2.0 `LICENSE` at repo root (GitHub detects this on the default branch)
- [x] README **License** section
- [x] `pyproject.toml` declares `Apache-2.0`
- [x] First-pass secret history scan (2026-08-15): `.env` never committed; no filled `CLICKHOUSE_PASSWORD=` / `SUPERVISOR_RUN_TOKEN=` values in git history; `.gitignore` covers `.env`, `*.pem`, `*.key`, `secrets/`

## Do not flip yet

- [ ] Board / CEO timing decision (suggested window: Sep 1, at least several days before Sep 9)
- [ ] Default branch is `main` and includes `LICENSE` (required for GitHub About license badge)

## Pre-flight (day of flip)

1. Confirm visibility is still private:

   ```bash
   gh repo view asaf-avron/cinetrace-ai --json visibility,url,defaultBranchRef,licenseInfo
   ```

2. Re-scan git history for secrets (names and assignment patterns only; do not paste values into tickets or chat):

   ```bash
   git ls-files | grep -Ei '(\.env$|credentials|id_rsa|\.pem$|\.p12$|\.key$|token\.json|service.account)' || true
   git log --all --full-history -- .env
   git grep -I -n -E 'CLICKHOUSE_PASSWORD=.+' $(git rev-list --all) -- ':!.env.example' || true
   git grep -I -n -E 'SUPERVISOR_RUN_TOKEN=.+' $(git rev-list --all) -- ':!.env.example' || true
   ```

   Expected: no tracked secret files; empty `.env` history; no filled password/token assignments outside `.env.example` placeholders.

3. Confirm ignored local secrets are not staged:

   ```bash
   git status --ignored
   git check-ignore -v .env
   ```

4. Confirm hosted demo token is **not** in the repo. `SUPERVISOR_RUN_TOKEN` belongs in Secret Manager / local `.env` only.

5. Confirm `LICENSE` is on `origin/main` and GitHub can classify it:

   ```bash
   git ls-tree origin/main LICENSE README.md docs/public-repo-checklist.md
   ```

## Flip (board-approved only)

```bash
gh repo edit asaf-avron/cinetrace-ai --visibility public --accept-visibility-change-consequences
```

Then verify:

```bash
gh repo view asaf-avron/cinetrace-ai --json visibility,licenseInfo,url
```

Expected: `visibility=PUBLIC`, `licenseInfo.key=apache-2.0`, About on GitHub shows **Apache License 2.0**.

If `licenseInfo` is null after a few minutes, confirm `LICENSE` is the official Apache 2.0 text on the default branch (not a stub) and refresh the repo About page.

## Devpost repo URL

Until the flip, the Devpost **Repository URL** field is a placeholder. After the repo is public, paste:

```
https://github.com/asaf-avron/cinetrace-ai
```

Paste that URL on the Devpost submission (ClickHouse track). Do not submit a private-repo URL as the final entry.

## Post-flip

- [ ] GitHub About shows Apache-2.0
- [ ] Anonymous / logged-out browser can open the repo URL
- [ ] README license section and this checklist still say the flip already happened (update the "Do not flip yet" banner)
- [ ] Devpost form uses the public URL above
- [ ] Hosted judge URL still works: https://cinetrace-781071502822.us-central1.run.app
