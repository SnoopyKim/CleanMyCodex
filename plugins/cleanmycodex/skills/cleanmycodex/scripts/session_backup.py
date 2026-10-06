#!/usr/bin/env python3
"""Export persisted Codex conversation items. Never deletes or edits native history."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid

from cleanmycodex import Refused, digest, now, private_dir, storage, write_json


class AppServer:
    """Version-sensitive local, read-only JSON-RPC adapter (Codex CLI 0.160.0)."""

    def __init__(self):
        self.proc = subprocess.Popen(["codex", "app-server", "--listen", "stdio://"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue()
        self.counter = 0
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": "cleanmycodex", "version": "0.1.0"},
                                     "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def _read(self):
        for line in self.proc.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                continue
        self.messages.put(None)

    def send(self, payload):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params):
        if method not in {"initialize", "skills/list", "thread/read", "thread/list", "thread/turns/list"}:
            raise Refused("Read-only adapter refused this method.")
        self.counter += 1
        request_id = self.counter
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            try:
                response = self.messages.get(timeout=60)
            except queue.Empty as exc:
                raise Refused("Codex app-server did not reply within 60 seconds.") from exc
            if response is None:
                raise Refused("Codex app-server disconnected.")
            if response.get("id") == request_id:
                if "error" in response:
                    # Server errors may contain private paths or source text.
                    raise Refused(f"Codex rejected read-only method {method}; check CLI compatibility.")
                return response["result"]

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()


def pages(client, method, params):
    cursor, seen = None, set()
    while True:
        response = client.call(method, dict(params, cursor=cursor))
        yield from response["data"]
        cursor = response.get("nextCursor")
        if cursor is None:
            return
        if cursor in seen:
            raise Refused("Repeated pagination cursor; export is incomplete.")
        seen.add(cursor)


def collect(client, thread_id, current_thread):
    if thread_id == current_thread:
        raise Refused("Run conversation cleanup from a different chat after this chat finishes.")
    metadata = client.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
    if metadata["id"] != thread_id or metadata["status"]["type"] == "active":
        raise Refused("Target identity differs or target is active.")
    # Native deletion may also delete spawned descendants. v0.1 refuses that larger scope.
    all_threads = []
    for archived in (False, True):
        all_threads.extend(pages(client, "thread/list", {"archived": archived, "limit": 100,
            "sourceKinds": ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview",
                            "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"],
            "modelProviders": [], "useStateDbOnly": True}))
    if any(t.get("parentThreadId") == thread_id for t in all_threads):
        raise Refused("Spawned child chats require a separate backup of the entire deletion scope.")
    turns = list(pages(client, "thread/turns/list", {"threadId": thread_id, "limit": 20,
                                                  "itemsView": "full", "sortDirection": "asc"}))
    if any(t.get("itemsView", "full") != "full" or t["status"] == "inProgress" for t in turns):
        raise Refused("History is incomplete or still running.")
    if len({t["id"] for t in turns}) != len(turns):
        raise Refused("Duplicated history pages; retry when the chat is idle.")
    after = client.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
    if after["updatedAt"] != metadata["updatedAt"] or after["status"]["type"] == "active":
        raise Refused("Chat changed during export.")
    return {"schema": 1, "thread": metadata, "turns": turns,
            "scope": "All persisted ThreadItems exposed by the local app-server. "
                     "External attachments, cloud copies and native DB restoration are not included."}


def backup(client, thread_id, current_thread, summary_path, store):
    thread_id, current_thread = str(uuid.UUID(thread_id)), str(uuid.UUID(current_thread))
    summary = Path(summary_path).read_bytes()
    if not summary.strip():
        raise Refused("Write a meaningful continuity summary before exporting.")
    exported = collect(client, thread_id, current_thread)
    raw = json.dumps(exported, ensure_ascii=True).encode()
    bundle = private_dir(store / "conversations") / str(uuid.uuid4())
    bundle.mkdir(mode=0o700)
    output = bundle / "conversation.json.gz"
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(gzip.compress(raw, compresslevel=6))
        f.flush()
        os.fsync(f.fileno())
    with gzip.open(output, "rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != hashlib.sha256(raw).hexdigest():
            raise Refused("Conversation compression verification failed.")
    fd = os.open(bundle / "SUMMARY.md", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(summary)
    manifest = {"schema": 1, "thread_id": thread_id, "exported_at": now(),
                "updated_at": exported["thread"]["updatedAt"], "turn_count": len(exported["turns"]),
                "archive_sha256": digest(output), "summary_sha256": digest(bundle / "SUMMARY.md"),
                "compressed_bytes": output.stat().st_size, "uncompressed_bytes": len(raw),
                "native_deletion_performed": False,
                "scope": exported["scope"]}
    write_json(bundle / "manifest.json", manifest)
    return {"state": "exported", "bundle": str(bundle), **manifest}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("thread_id")
    p.add_argument("--current-thread", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--store")
    args = p.parse_args()
    client = None
    try:
        # Refuse active self before starting the app-server process.
        if str(uuid.UUID(args.thread_id)) == str(uuid.UUID(args.current_thread)):
            raise Refused("Run conversation cleanup from another chat after this chat finishes.")
        client = AppServer()
        result = backup(client, args.thread_id, args.current_thread, args.summary, storage(args.store))
        print(json.dumps(result, indent=2))
        return 0
    except (Refused, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"state": "refused", "reason": str(exc)}), file=sys.stderr)
        return 2
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
