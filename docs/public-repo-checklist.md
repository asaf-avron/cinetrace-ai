# Public-repo checklist

CineTrace AI is **public**: `https://github.com/asaf-avron/cinetrace-ai`

Devpost: [Agentic Cinema](https://agentic-cinema.devpost.com/) (ClickHouse track). Deadline: **Sep 9, 2026 @ 2:00pm PDT**.

## Done

- [x] Apache-2.0 `LICENSE` on `main`
- [x] Repo visibility public (`gh repo edit ... --visibility public`)
- [x] Hosted judge URL: https://cinetrace-781071502822.us-central1.run.app

## Keep true

- `.env` stays gitignored. Never commit `CLICKHOUSE_PASSWORD` or `SUPERVISOR_RUN_TOKEN`.
- Devpost **Repository URL** must be the public GitHub URL above.
- Re-scan before any accidental secret commit:

  ```bash
  git check-ignore -v .env
  git grep -I -n -E 'CLICKHOUSE_PASSWORD=.+' -- ':!.env.example' || true
  git grep -I -n -E 'SUPERVISOR_RUN_TOKEN=.+' -- ':!.env.example' || true
  ```
