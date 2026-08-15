#!/usr/bin/env python3
"""Idempotent CIN host checkout, per-agent worktrees, and Paperclip cwd/GH_TOKEN.

CIN / CineTrace AI only. Never SYN/Maqom. Never companies[0].
Does not print secrets.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SYN_ID = "94bea508-f6a9-44db-b44c-ff6a6974b3e5"
API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100").rstrip("/")
REPO_URL = "https://github.com/asaf-avron/cinetrace-ai.git"
REPO_HTTPS = "https://github.com/asaf-avron/cinetrace-ai"
CLONE_DIR = Path(os.environ.get("CINETRACE_CLONE", "/opt/cinetrace-ai"))
TOKEN_FILE = Path(os.environ.get("CINETRACE_GITHUB_ENV", "/home/ubuntu/.cinetrace/github.env"))
PAPERCLIP_ENV = Path("/opt/milepo-oracle/.env")
PROJECT_NAME = "CineTrace AI"
HOST_HELPER = Path("/home/ubuntu/.cinetrace/git-credential.sh")
REPO_HELPER = Path(__file__).resolve().parent / "git-credential.sh"
UNIQUE_ROLES = {"ceo", "cto", "cfo", "cmo", "cpo"}


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def read_assignment(path: Path, key: str) -> str:
    if not path.is_file():
        die(f"missing {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip("\"'").strip()
    die(f"{key} not set in {path}")


def load_gh_token() -> str:
    token = read_assignment(TOKEN_FILE, "GH_TOKEN")
    if len(token) < 20:
        die("GH_TOKEN looks empty")
    return token


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True)


def run_ok(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    proc = run(cmd, cwd=cwd, env=env)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        die(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{err}")
    return proc.stdout


def api(key: str, method: str, path: str, body: dict | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        die(f"{method} {path} -> {exc.code}: {detail}")


def resolve_cin(key: str) -> str:
    rows = api(key, "GET", "/api/companies")
    if not isinstance(rows, list):
        die("unexpected /api/companies payload")
    cin = next((c for c in rows if isinstance(c, dict) and c.get("issuePrefix") == "CIN"), None)
    if not cin:
        die("CIN company not found")
    cid = str(cin["id"])
    if cid == SYN_ID:
        die("resolved CIN id matched SYN — refusing")
    return cid


def slug_for(agent: dict, used: set[str]) -> str:
    role = str(agent.get("role") or "").strip().lower()
    name = str(agent.get("name") or "").strip().lower()
    if role in UNIQUE_ROLES:
        base = role
    else:
        base = re.sub(r"[^a-z0-9]+", "-", name).strip("-") or role or "agent"
    if base in used:
        base = f"{base}-{str(agent.get('id') or 'x')[:8]}"
    used.add(base)
    return base


def github_identity(token: str) -> tuple[str, str]:
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cinetrace-cin-worktrees",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        user = json.loads(resp.read().decode())
    login = str(user.get("login") or "asaf-avron")
    email = str(user.get("email") or f"{login}@users.noreply.github.com")
    return login, email


def ensure_helper() -> Path:
    src = REPO_HELPER if REPO_HELPER.is_file() else HOST_HELPER
    if not src.is_file():
        die(f"missing credential helper {src}")
    HOST_HELPER.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != HOST_HELPER.resolve():
        HOST_HELPER.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(HOST_HELPER, 0o700)
    return HOST_HELPER


def ensure_clone(token: str) -> None:
    helper = ensure_helper()
    parent = CLONE_DIR.parent
    if not parent.is_dir():
        die(f"parent missing: {parent}")
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    env["GIT_TERMINAL_PROMPT"] = "0"
    if not (CLONE_DIR / ".git").exists() and not (CLONE_DIR / ".git").is_file():
        if CLONE_DIR.exists() and any(CLONE_DIR.iterdir()):
            die(f"{CLONE_DIR} exists and is not a git checkout")
        CLONE_DIR.mkdir(parents=True, exist_ok=True)
        log(f"cloning {REPO_HTTPS} -> {CLONE_DIR}")
        proc = run(
            [
                "git",
                "-c",
                f"credential.helper={helper}",
                "clone",
                REPO_URL,
                str(CLONE_DIR),
            ],
            env=env,
        )
        if proc.returncode != 0:
            die(f"git clone failed\n{(proc.stderr or proc.stdout or '').strip()}")
    else:
        log(f"checkout exists: {CLONE_DIR}")
        run_ok(["git", "remote", "set-url", "origin", REPO_URL], cwd=CLONE_DIR)

    login, email = github_identity(token)
    run_ok(["git", "config", "--local", "user.name", login], cwd=CLONE_DIR)
    run_ok(["git", "config", "--local", "user.email", email], cwd=CLONE_DIR)
    # Empty helper resets inherited helpers (host gh / insiteu-bot) for this repo.
    run_ok(["git", "config", "--local", "--replace-all", "credential.helper", ""], cwd=CLONE_DIR)
    run_ok(
        ["git", "config", "--local", "--replace-all", "credential.https://github.com.helper", ""],
        cwd=CLONE_DIR,
    )
    run_ok(
        ["git", "config", "--local", "--add", "credential.https://github.com.helper", str(helper)],
        cwd=CLONE_DIR,
    )
    run_ok(["git", "-c", f"credential.helper={helper}", "fetch", "origin"], cwd=CLONE_DIR, env=env)


def default_branch() -> str:
    ref = run_ok(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=CLONE_DIR).strip()
    if ref.startswith("origin/"):
        return ref.split("/", 1)[1]
    return "main"


def existing_worktrees() -> dict[str, str]:
    out = run_ok(["git", "worktree", "list", "--porcelain"], cwd=CLONE_DIR)
    paths: dict[str, str] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = line.split(" ", 1)[1]
        elif line.startswith("branch ") and current:
            paths[current] = line.split(" ", 1)[1]
    return paths


def ensure_worktree(slug: str, start_point: str) -> Path:
    dest = CLONE_DIR / "worktrees" / slug
    dest.parent.mkdir(parents=True, exist_ok=True)
    listed = existing_worktrees()
    if str(dest) in listed:
        log(f"worktree exists: {dest}")
        return dest
    if dest.exists():
        die(f"{dest} exists but is not a registered worktree")
    branch = f"{slug}-work"
    local = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=CLONE_DIR)
    remote = run(["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd=CLONE_DIR)
    if local.returncode == 0:
        run_ok(["git", "worktree", "add", str(dest), branch], cwd=CLONE_DIR)
    elif remote.returncode == 0:
        run_ok(["git", "worktree", "add", "-b", branch, str(dest), f"origin/{branch}"], cwd=CLONE_DIR)
    else:
        run_ok(["git", "worktree", "add", "-b", branch, str(dest), f"origin/{start_point}"], cwd=CLONE_DIR)
    log(f"created worktree {dest} on {branch}")
    return dest


def ensure_project(key: str, cin_id: str) -> str:
    rows = api(key, "GET", f"/api/companies/{cin_id}/projects")
    if not isinstance(rows, list):
        die("unexpected projects payload")
    for proj in rows:
        if isinstance(proj, dict) and proj.get("name") == PROJECT_NAME:
            pid = str(proj["id"])
            log(f"project exists: {PROJECT_NAME} {pid}")
            ensure_project_workspace(key, pid, proj)
            return pid
    created = api(
        key,
        "POST",
        f"/api/companies/{cin_id}/projects",
        {
            "name": PROJECT_NAME,
            "description": "Private CineTrace AI product repo (asaf-avron/cinetrace-ai).",
            "status": "in_progress",
        },
    )
    if not isinstance(created, dict) or not created.get("id"):
        die("project create returned no id")
    pid = str(created["id"])
    log(f"created project {pid}")
    ensure_project_workspace(key, pid, created)
    return pid


def workspace_cwd(proj: dict) -> str | None:
    pw = proj.get("primaryWorkspace")
    if isinstance(pw, dict) and pw.get("cwd"):
        return str(pw["cwd"])
    spaces = proj.get("workspaces")
    if isinstance(spaces, list):
        for ws in spaces:
            if isinstance(ws, dict) and ws.get("cwd"):
                return str(ws["cwd"])
    return None


def ensure_project_workspace(key: str, project_id: str, proj: dict) -> None:
    current = workspace_cwd(proj)
    if current == str(CLONE_DIR):
        log(f"project workspace cwd already {CLONE_DIR}")
        return
    spaces = api(key, "GET", f"/api/projects/{project_id}/workspaces")
    items = spaces if isinstance(spaces, list) else []
    for ws in items:
        if not isinstance(ws, dict):
            continue
        if ws.get("cwd") == str(CLONE_DIR) or ws.get("name") == "cinetrace-ai":
            if ws.get("cwd") != str(CLONE_DIR):
                api(
                    key,
                    "PATCH",
                    f"/api/projects/{project_id}/workspaces/{ws['id']}",
                    {"cwd": str(CLONE_DIR), "repoUrl": REPO_HTTPS},
                )
                log("patched project workspace cwd")
            else:
                log("project workspace already linked")
            return
    api(
        key,
        "POST",
        f"/api/projects/{project_id}/workspaces",
        {
            "name": "cinetrace-ai",
            "sourceType": "git_repo",
            "cwd": str(CLONE_DIR),
            "repoUrl": REPO_HTTPS,
            "visibility": "default",
        },
    )
    log(f"created project workspace cwd={CLONE_DIR}")


def env_plain(value: object) -> str:
    if isinstance(value, dict) and "value" in value:
        return str(value.get("value") or "").strip()
    return str(value or "").strip()


def merge_adapter(agent: dict, cwd: Path, token: str) -> dict:
    cfg = dict(agent.get("adapterConfig") or {})
    env = dict(cfg.get("env") or {})
    if not env.get("CURSOR_API_KEY"):
        die(f"agent {agent.get('name')} missing CURSOR_API_KEY; refusing to replace env")
    if env_plain(env.get("GH_TOKEN")) != token.strip():
        env["GH_TOKEN"] = token
    cfg["env"] = env
    cfg["cwd"] = str(cwd)
    return cfg


def patch_agent(key: str, agent: dict, cwd: Path, token: str) -> None:
    current = agent.get("adapterConfig") or {}
    current_env = current.get("env") or {}
    if current.get("cwd") == str(cwd) and env_plain(current_env.get("GH_TOKEN")) == token.strip():
        log(f"agent {agent.get('name')} already has cwd and GH_TOKEN")
        return
    cfg = merge_adapter(agent, cwd, token)
    api(key, "PATCH", f"/api/agents/{agent['id']}", {"adapterConfig": cfg})
    log(f"patched agent {agent.get('name')} cwd={cwd}")


def main() -> int:
    if os.geteuid() == 0:
        die("do not run as root")
    token = load_gh_token()
    os.chmod(TOKEN_FILE, 0o600)
    paperclip_key = read_assignment(PAPERCLIP_ENV, "PAPERCLIP_API_KEY")
    cin_id = resolve_cin(paperclip_key)
    log(f"CIN company {cin_id}")
    ensure_clone(token)
    start = default_branch()
    agents = api(paperclip_key, "GET", f"/api/companies/{cin_id}/agents")
    if not isinstance(agents, list):
        die("unexpected agents payload")
    used: set[str] = set()
    for agent in agents:
        if not isinstance(agent, dict) or not agent.get("id"):
            continue
        if str(agent.get("companyId") or cin_id) == SYN_ID:
            die("refusing SYN agent")
        slug = slug_for(agent, used)
        dest = ensure_worktree(slug, start)
        patch_agent(paperclip_key, agent, dest, token)
    ensure_project(paperclip_key, cin_id)
    log("CIN worktrees ensured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
