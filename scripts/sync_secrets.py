"""Create or update Secret Manager values from local .env. Does not print secrets."""

from __future__ import annotations

import shutil
import subprocess

from dotenv import dotenv_values

from cinetrace.env import REPO_ROOT


def _gcloud_bin() -> str:
    for name in ("gcloud.cmd", "gcloud"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("gcloud is not on PATH")

PROJECT = "cinetrace-ai"
KEYS = (
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD",
    "CLICKHOUSE_SECURE",
    "CLICKHOUSE_VERIFY",
    "CLICKHOUSE_DATABASE",
    "SUPERVISOR_RUN_TOKEN",
)


def _gcloud(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_gcloud_bin(), *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def upsert(name: str, value: str) -> None:
    exists = _gcloud("secrets", "describe", name, "--project", PROJECT)
    if exists.returncode != 0:
        created = _gcloud(
            "secrets",
            "create",
            name,
            "--project",
            PROJECT,
            "--replication-policy",
            "automatic",
            "--data-file",
            "-",
            input_text=value,
        )
        if created.returncode != 0:
            raise RuntimeError(created.stderr)
        print(f"created {name}")
        return
    added = _gcloud(
        "secrets",
        "versions",
        "add",
        name,
        "--project",
        PROJECT,
        "--data-file",
        "-",
        input_text=value,
    )
    if added.returncode != 0:
        raise RuntimeError(added.stderr)
    print(f"updated {name}")


def main() -> None:
    values = dotenv_values(REPO_ROOT / ".env")
    missing = [key for key in KEYS if not values.get(key)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")
    for key in KEYS:
        upsert(key, str(values[key]))


if __name__ == "__main__":
    main()
