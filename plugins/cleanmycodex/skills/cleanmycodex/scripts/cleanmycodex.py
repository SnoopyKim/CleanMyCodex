#!/usr/bin/env python3
"""Local workspace inventory and verified, reversible cleanup. Python 3.11+."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone

VERSION = "0.1.0"
PROTECTED = {".git", ".codex", ".agents", ".ssh", ".gnupg", ".aws", ".kube",
             "auth.json", "credentials.json", "credentials", "Cookies", "Login Data"}
CACHES = {"node_modules", ".next", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


class Refused(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def run(args, cwd=None, timeout=45):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(f"Command unavailable or timed out: {args[0]}") from exc


def digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def contained(path, parent):
    return path == parent or parent in path.parents


def sensitive(path):
    for part in path.parts:
        if (part in PROTECTED or part == ".env" or part.startswith(".env.")
                or part.lower().endswith((".pem", ".key", ".p12", ".pfx"))):
            return True
    return False


def root_path(value):
    p = Path(value).expanduser().resolve(strict=True)
    home = Path.home().resolve()
    if not p.is_dir() or p == home or p == Path(p.anchor):
        raise Refused("Choose a specific workspace directory, not a disk or home root.")
    if sensitive(p) or contained(p, home / "Library"):
        raise Refused("Application state, credentials, and Library directories are protected.")
    return p


def relative_name(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or any(x in {"", ".", ".."} for x in value.split("/")):
        raise Refused("Targets must be explicit relative paths without dot or parent components.")
    return p.as_posix()


def target_path(root, name):
    name = relative_name(name)
    path = root / name
    if sensitive(Path(name)) or any(x.startswith(".cleanmycodex-") for x in Path(name).parts):
        raise Refused(f"Protected target: {name}")
    if path.resolve() != path or not contained(path, root):
        raise Refused(f"Symlink or escaped target: {name}")
    return path


def snapshot(path):
    """Stable content+metadata ledger. Links, special files and credentials are refused."""
    entries = []

    def walk(p, rel):
        s = p.lstat()
        if sensitive(Path(p.name)):
            raise Refused(f"Protected item within target: {p.name}")
        if stat.S_ISLNK(s.st_mode) or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
            raise Refused(f"Links and special files are not supported: {rel}")
        if stat.S_ISREG(s.st_mode) and s.st_nlink > 1:
            raise Refused(f"Hard-linked file requires separate review: {rel}")
        row = {"path": rel, "kind": "dir" if p.is_dir() else "file",
               "mode": stat.S_IMODE(s.st_mode), "mtime_ns": s.st_mtime_ns,
               "size": s.st_size if p.is_file() else 0,
               "allocated": s.st_blocks * 512}
        if row["kind"] == "file":
            row["sha256"] = digest(p)
        entries.append(row)
        if row["kind"] == "dir":
            for child in sorted(p.iterdir()):
                walk(child, child.name if rel == "." else f"{rel}/{child.name}")
    walk(path, ".")
    return entries


def content_ledger(entries):
    return [{k: v for k, v in r.items() if k != "allocated"} for r in entries]


def same_snapshot(path, entries):
    return content_ledger(snapshot(path)) == content_ledger(entries)


def no_tracked_files(path):
    base = path if path.is_dir() else path.parent
    found = run(["git", "-C", str(base), "rev-parse", "--show-toplevel"])
    if found.returncode:
        return
    repo = Path(os.fsdecode(found.stdout).strip()).resolve()
    result = run(["git", "-C", str(repo), "ls-files", "-z", "--", str(path)])
    if result.returncode or result.stdout:
        raise Refused("Target contains Git-tracked files. Preserve project sources separately.")


def idle(path):
    executable = shutil.which("lsof")
    if not executable:
        raise Refused("lsof is required for apply; open-file checks cannot be skipped.")
    args = [executable, "-nP", "-F", "p"]
    args += ["+D", str(path)] if path.is_dir() else ["--", str(path)]
    result = run(args, timeout=60)
    if result.stdout.strip():
        raise Refused("Target is open in a process. Close it before cleanup.")
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise Refused("Open-file inspection was incomplete; no cleanup performed.")


def private_dir(path):
    path = Path(path).expanduser().absolute()
    if path.resolve() != path:
        raise Refused("Private storage must not use symlinks.")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def default_store():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CleanMyCodex"
    return Path.home() / ".local/share/cleanmycodex"


def storage(value=None):
    path = Path(value).expanduser().absolute() if value else default_store()
    # Operational data must never accidentally be committed with the program.
    for p in (path, *path.parents):
        if (p / ".git").exists():
            raise Refused("Store plans and archives outside every Git repository.")
    return private_dir(path)


def write_json(path, data):
    fd, temp = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def inventory(root):
    def size(path):
        s = path.lstat()
        logical, allocated, files, links = 0, s.st_blocks * 512, 0, 0
        if stat.S_ISLNK(s.st_mode):
            return s.st_size, allocated, 0, 1
        if path.is_file():
            return s.st_size, allocated, 1, 0
        if path.is_dir():
            for child in path.iterdir():
                a, b, c, d = size(child)
                logical, allocated, files, links = logical+a, allocated+b, files+c, links+d
        return logical, allocated, files, links
    rows = []
    for p in root.iterdir():
        try:
            logical, allocated, files, links = size(p)
            rows.append({"path": p.name, "bytes": logical, "allocated_bytes": allocated,
                         "files": files, "symlinks": links,
                         "hint": "protected" if sensitive(p) else
                         "cache_candidate" if p.name in CACHES else "review"})
        except OSError:
            rows.append({"path": p.name, "hint": "unreadable"})
    return {"version": VERSION, "root": str(root), "items": sorted(
        rows, key=lambda r: r.get("allocated_bytes", 0), reverse=True),
        "note": "Allocated sizes are filesystem estimates; names alone do not authorize cleanup."}


def git_audit(path, check_remote=False, remote="origin"):
    def git(*args):
        return run(["git", "-C", str(path), *args])
    top = git("rev-parse", "--show-toplevel")
    if top.returncode:
        return {"status": "missing", "reason": "not_a_git_repository"}
    head = git("rev-parse", "HEAD")
    if head.returncode:
        return {"status": "missing", "reason": "no_commits"}
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    ignored = git("ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    stash = git("stash", "list", "--format=%H")
    heads = git("for-each-ref", "--format=%(objectname)", "refs/heads")
    if any(x.returncode for x in [status, ignored, stash, heads]):
        return {"status": "unknown", "reason": "local_inspection_failed"}
    result = {"status": "unknown", "remote_checked": False,
              "worktree_changes": bool(status.stdout),
              "ignored_files": len([x for x in ignored.stdout.split(b"\0") if x]),
              "stashes": len(stash.stdout.splitlines()),
              "scope": "Local branch tips and HEAD; ignored/untracked files are not Git backups. "
                       "LFS payloads, submodules, tags and external services are not verified."}
    if not check_remote:
        return result
    if remote not in os.fsdecode(git("remote").stdout).splitlines():
        result.update(status="missing", reason="remote_not_configured")
        return result
    live = git("ls-remote", "--heads", "--", remote)
    result.update(remote_checked=live.returncode == 0, checked_at=now())
    if live.returncode:
        result["reason"] = "remote_unreachable"
        return result
    tips = {line.split()[0].decode() for line in live.stdout.splitlines() if line.split()}
    local = {x.decode() for x in heads.stdout.splitlines()} | {head.stdout.decode().strip()}
    covered, unknown = [], []
    for commit in local:
        checks = [git("merge-base", "--is-ancestor", commit, tip).returncode for tip in tips]
        if commit in tips or 0 in checks:
            covered.append(commit)
        elif any(code > 1 for code in checks):
            unknown.append(commit)
    all_backed = len(covered) == len(local)
    result.update(local_tips=len(local), remote_covered_tips=len(covered),
                  tracked_history="confirmed" if all_backed else "unknown" if unknown else "partial",
                  status="confirmed" if all_backed and not status.stdout and not ignored.stdout
                         and not stash.stdout else "unknown" if unknown else "partial")
    return result


def plan(root, names, reason, store):
    root = root_path(root)
    if contained(store, root) or contained(root, store):
        raise Refused("Private storage and cleanup workspace must be separate.")
    selected = sorted(set(relative_name(n) for n in names))
    if not selected:
        raise Refused("Select at least one target.")
    for a in selected:
        if any(a.startswith(b + "/") for b in selected if a != b):
            raise Refused("Overlapping targets are not allowed.")
    items = []
    for name in selected:
        p = target_path(root, name)
        no_tracked_files(p)
        entries = snapshot(p)
        items.append({"path": name, "entries": entries})
    data = {"schema": 1, "id": str(uuid.uuid4()), "created_at": now(), "root": str(root),
            "operation": "archive_then_remove", "reason": reason, "items": items,
            "source_bytes": sum(r["size"] for i in items for r in i["entries"]),
            "source_allocated_bytes": sum(r["allocated"] for i in items for r in i["entries"]),
            "caveat": "Lossless file backup, not cloud backup or native chat restoration. "
                      "Extended attributes, ACLs and resource forks are not supported."}
    path = private_dir(store / "plans") / (data["id"] + ".json")
    write_json(path, data)
    return {"plan": str(path), **{k: v for k, v in data.items() if k != "items"},
            "targets": selected}


def archive_map(plan_data):
    expected = {}
    for item in plan_data["items"]:
        for entry in item["entries"]:
            name = item["path"] + ("/" + entry["path"] if entry["path"] != "." else "")
            relative_name(name)
            if name in expected:
                raise Refused("Duplicate archive entry.")
            expected[name] = entry
    return expected


def verify_archive(archive, data):
    expected, seen = archive_map(data), set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name.rstrip("/")
            if name not in expected or name in seen:
                raise Refused("Unexpected or repeated archive member.")
            row = expected[name]
            if not (member.isdir() if row["kind"] == "dir" else member.isfile()):
                raise Refused("Archive member type mismatch.")
            if member.mode != row["mode"]:
                raise Refused("Archive permissions mismatch.")
            if member.isfile():
                f = tar.extractfile(member)
                if member.size != row["size"] or hashlib.file_digest(f, "sha256").hexdigest() != row["sha256"]:
                    raise Refused("Archive content mismatch.")
            seen.add(name)
    if seen != set(expected):
        raise Refused("Archive is missing files.")


def xattr_names(path):
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        query = libc.listxattr
        query.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        query.restype = ctypes.c_ssize_t
        raw = os.fsencode(path)
        size = query(raw, None, 0, 1)  # XATTR_NOFOLLOW
        if size < 0:
            raise Refused("Extended attribute inspection failed.")
        if not size:
            return set()
        buffer = ctypes.create_string_buffer(size)
        actual = query(raw, buffer, size, 1)
        if actual < 0:
            raise Refused("Extended attributes changed during inspection.")
        return {os.fsdecode(n) for n in buffer.raw[:actual].split(b"\0") if n}
    elif hasattr(os, "listxattr"):
        return set(os.listxattr(path, follow_symlinks=False))
    else:
        raise Refused("Extended attribute inspection is unavailable on this platform.")


def check_xattrs(path):
    for p in [path, *path.rglob("*")] if path.is_dir() else [path]:
        # macOS attaches an OS-managed provenance marker to newly created files.
        # It is not a document resource and is deliberately not promised on restore.
        if xattr_names(p) - {"com.apple.provenance"}:
            raise Refused("Extended attributes require a metadata-preserving backup outside v0.1.")
        if sys.platform == "darwin":
            r = run(["/bin/ls", "-lde", str(p)])
            if r.returncode or len(r.stdout.splitlines()) > 1:
                raise Refused("ACL inspection failed or non-default ACL found.")


@contextlib.contextmanager
def root_lock(store, root):
    locks = private_dir(store / "locks")
    lock = locks / hashlib.sha256(str(root).encode()).hexdigest()
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise Refused("Workspace is locked. Review interrupted operation before removing its lock.") from exc
    try:
        yield
    finally:
        lock.rmdir()


def apply(plan_file, store):
    data = read_json(plan_file)
    if data.get("schema") != 1 or data.get("operation") != "archive_then_remove":
        raise Refused("Unsupported plan.")
    ident = str(uuid.UUID(data["id"]))
    if ident != data["id"]:
        raise Refused("Invalid plan identifier.")
    root = root_path(data["root"])
    if contained(store, root) or contained(root, store):
        raise Refused("Private storage and cleanup workspace must be separate.")
    archive_map(data)
    names = [i["path"] for i in data["items"]]
    if not names or len(names) != len(set(names)) or any(
            a.startswith(b + "/") for a in names for b in names if a != b):
        raise Refused("Empty, duplicate or overlapping targets.")
    bundles = private_dir(store / "archives")
    bundle = bundles / ident
    with root_lock(store, root):
        if bundle.exists():
            raise Refused("This plan already started. Inspect its manifest or restore; never replay apply.")
        for item in data["items"]:
            p = target_path(root, item["path"])
            no_tracked_files(p)
            if not same_snapshot(p, item["entries"]):
                raise Refused("Target changed since planning. Generate a new plan.")
            idle(p)
            check_xattrs(p)
        bundle.mkdir(mode=0o700)
        manifest = bundle / "manifest.json"
        data.update(state="backing_up", stages=[], started_at=now())
        write_json(manifest, data)
        archive = bundle / "files.tar.gz"
        try:
            fd = os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as output:
                with tarfile.open(fileobj=output, mode="w:gz", compresslevel=6) as tar:
                    for item in data["items"]:
                        tar.add(target_path(root, item["path"]), arcname=item["path"], recursive=True)
                output.flush()
                os.fsync(output.fileno())
            verify_archive(archive, data)
            data.update(state="verified", archive_sha256=digest(archive), archive_bytes=archive.stat().st_size)
            write_json(manifest, data)
            # Stage by atomic rename on the workspace filesystem. Any interrupted stage is recorded.
            for index, item in enumerate(data["items"]):
                p = target_path(root, item["path"])
                no_tracked_files(p)
                if not same_snapshot(p, item["entries"]):
                    raise Refused("Target changed during backup; original retained.")
                idle(p)
                check_xattrs(p)
                stage = root / f".cleanmycodex-stage-{ident}-{index}"
                if stage.exists() or stage.is_symlink():
                    raise Refused("Stage path already exists.")
                data["stages"].append({"source": item["path"], "stage": stage.name, "state": "pending"})
                write_json(manifest, data)
                p.rename(stage)
                data["stages"][-1]["state"] = "staged"
                write_json(manifest, data)
                if not same_snapshot(stage, item["entries"]):
                    raise Refused("Staged target changed; retained at the recorded stage path.")
                idle(stage)
                check_xattrs(stage)
                if stage.is_dir():
                    shutil.rmtree(stage)
                else:
                    stage.unlink()
                data["stages"][-1]["state"] = "removed"
                write_json(manifest, data)
            data.update(state="complete", completed_at=now())
            write_json(manifest, data)
        except Exception:
            data.update(state="interrupted", interrupted_at=now())
            write_json(manifest, data)
            raise
    stored = sum(p.stat().st_blocks * 512 for p in bundle.iterdir())
    return {"state": data["state"], "archive_id": ident, "manifest": str(manifest),
            "archive_bytes": data["archive_bytes"], "source_bytes": data["source_bytes"],
            "estimated_net_allocated_reduction": data["source_allocated_bytes"] - stored,
            "note": "Estimate excludes filesystem snapshots, shared blocks and plan files. "
                    "Restore into a new directory; native conversations are unchanged."}


def restore(ident, destination, store):
    ident = str(uuid.UUID(ident))
    bundle = store / "archives" / ident
    data = read_json(bundle / "manifest.json")
    archive = bundle / "files.tar.gz"
    if not data.get("archive_sha256") or digest(archive) != data["archive_sha256"]:
        raise Refused("Archive checksum is missing or differs from the manifest.")
    verify_archive(archive, data)
    dest = Path(destination).expanduser().absolute()
    if dest.resolve() != dest or dest.exists():
        raise Refused("Restore destination must be a new path without symlinks.")
    if sensitive(dest):
        raise Refused("Cannot restore into protected app state.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".cleanmycodex-restore-", dir=dest.parent))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            # Manual extraction: verified regular files/directories only, never tar.extractall.
            for member in tar:
                p = staging / relative_name(member.name.rstrip("/"))
                if member.isdir():
                    p.mkdir(parents=True, exist_ok=True)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with p.open("xb") as f, tar.extractfile(member) as source:
                        shutil.copyfileobj(source, f)
        expected = archive_map(data)
        for name, row in sorted(expected.items(), key=lambda item: item[0].count("/"), reverse=True):
            p = staging / name
            if row["kind"] == "file" and digest(p) != row["sha256"]:
                raise Refused("Restored content differs.")
            os.chmod(p, row["mode"])
            os.utime(p, ns=(row["mtime_ns"], row["mtime_ns"]))
        if dest.exists():
            raise Refused("Restore destination appeared during restore.")
        staging.rename(dest)
    except Exception:
        shutil.rmtree(staging)
        raise
    return {"state": "restored", "destination": str(dest), "archive_id": ident,
            "note": "Workspace files restored; this does not restore a native Codex chat."}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--store", help="Private data directory outside Git and cleanup roots")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan", help="Read-only, one-level workspace inventory")
    s.add_argument("root")
    s = sub.add_parser("git-audit", help="Audit Git history coverage; no push or fetch")
    s.add_argument("root")
    s.add_argument("--check-remote", action="store_true")
    s.add_argument("--remote", default="origin")
    s = sub.add_parser("plan", help="Hash explicit targets; write a private cleanup plan")
    s.add_argument("root")
    s.add_argument("--target", action="append", required=True)
    s.add_argument("--reason", required=True)
    s = sub.add_parser("apply", help="Verify, archive and remove a previously authorized selection")
    s.add_argument("plan")
    s = sub.add_parser("restore", help="Restore a verified archive into a new directory")
    s.add_argument("archive_id")
    s.add_argument("--to", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "scan":
            result = inventory(root_path(args.root))
        elif args.command == "git-audit":
            result = git_audit(Path(args.root).expanduser().resolve(), args.check_remote, args.remote)
        else:
            store = storage(args.store)
            if args.command == "plan":
                result = plan(args.root, args.target, args.reason, store)
            elif args.command == "apply":
                result = apply(args.plan, store)
            else:
                result = restore(args.archive_id, args.to, store)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        print(json.dumps({"state": "refused", "reason": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
