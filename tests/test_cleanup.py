import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/cleanmycodex/skills/cleanmycodex/scripts"
sys.path.insert(0, str(SCRIPTS))
import cleanmycodex as c
import session_backup as s


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cleanmycodex-test-")
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.store = c.storage(self.base / "private")
        self.target = self.root / "scratch"
        self.target.mkdir()
        (self.target / "note.txt").write_text("temporary material\n" * 10000)
        (self.target / "empty").mkdir()
        self.keep = self.root / "keep.txt"
        self.keep.write_text("authored result")

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, names=None):
        return c.plan(self.root, names or ["scratch"], "Disposable test fixture", self.store)

    def apply(self, plan=None):
        return c.apply((plan or self.plan())["plan"], self.store)

    def test_round_trip_real_open_file_checks(self):
        original = c.content_ledger(c.snapshot(self.target))
        keep_hash = c.digest(self.keep)
        result = self.apply()
        self.assertFalse(self.target.exists())
        self.assertEqual(c.digest(self.keep), keep_hash)
        self.assertGreater(result["estimated_net_allocated_reduction"], 0)
        restored = self.base / "restored"
        c.restore(result["archive_id"], restored, self.store)
        self.assertEqual(c.content_ledger(c.snapshot(restored / "scratch")), original)

    def test_changed_content_refused(self):
        plan = self.plan()
        (self.target / "note.txt").write_text("new work")
        with self.assertRaisesRegex(c.Refused, "changed"):
            self.apply(plan)
        self.assertTrue(self.target.exists())

    def test_new_file_refused(self):
        plan = self.plan()
        (self.target / "added.txt").write_text("preserve")
        with self.assertRaises(c.Refused):
            self.apply(plan)

    def test_symlinks_refused(self):
        (self.target / "outside").symlink_to(self.keep)
        with self.assertRaisesRegex(c.Refused, "Links"):
            self.plan()
        self.assertTrue(self.keep.exists())

    def test_symlink_target_refused(self):
        (self.root / "alias").symlink_to(self.target)
        with self.assertRaisesRegex(c.Refused, "Symlink"):
            self.plan(["alias"])

    def test_hardlinks_refused(self):
        os.link(self.keep, self.target / "shared")
        with self.assertRaisesRegex(c.Refused, "Hard-linked"):
            self.plan()

    def test_credentials_refused(self):
        (self.target / ".env.local").write_text("synthetic test value")
        with self.assertRaisesRegex(c.Refused, "Protected"):
            self.plan()

    def test_repository_refused(self):
        (self.target / ".git").mkdir()
        with self.assertRaises(c.Refused):
            self.plan()

    def test_tracked_file_refused(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "scratch"], check=True)
        with self.assertRaisesRegex(c.Refused, "Git-tracked"):
            self.plan()

    def test_path_traversal_refused(self):
        for name in ["../keep.txt", "/tmp", ".", "scratch/../keep.txt", "scratch//empty"]:
            with self.subTest(name=name), self.assertRaises(c.Refused):
                self.plan([name])

    def test_overlap_refused(self):
        with self.assertRaisesRegex(c.Refused, "Overlapping"):
            self.plan(["scratch", "scratch/note.txt"])

    def test_private_store_must_be_outside_target_root(self):
        with self.assertRaises(c.Refused):
            c.plan(self.root, ["scratch"], "test", c.storage(self.root / "private"))

    def test_store_cannot_be_in_repository(self):
        (self.base / ".git").mkdir()
        with self.assertRaisesRegex(c.Refused, "outside every Git"):
            c.storage(self.base / "archive")

    def test_open_file_refused(self):
        with (self.target / "note.txt").open("rb"):
            with self.assertRaisesRegex(c.Refused, "open in a process"):
                self.apply()
        self.assertTrue(self.target.exists())

    def test_missing_lsof_refused(self):
        with mock.patch.object(c.shutil, "which", return_value=None):
            with self.assertRaisesRegex(c.Refused, "lsof"):
                self.apply()

    def test_xattrs_refused(self):
        path = self.target / "note.txt"
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/xattr", "-w", "com.cleanmycodex.test", "metadata", str(path)], check=True)
        else:
            os.setxattr(path, "user.cleanmycodex", b"metadata")
        with self.assertRaisesRegex(c.Refused, "Extended attributes"):
            self.apply()
        self.assertTrue(self.target.exists())

    def test_replay_refused(self):
        plan = self.plan()
        self.apply(plan)
        with self.assertRaisesRegex(c.Refused, "already started"):
            self.apply(plan)

    def test_tampered_archive_refused(self):
        result = self.apply()
        archive = self.store / "archives" / result["archive_id"] / "files.tar.gz"
        archive.write_bytes(b"corrupted")
        with self.assertRaisesRegex(c.Refused, "checksum"):
            c.restore(result["archive_id"], self.base / "restored", self.store)

    def test_restore_never_overwrites(self):
        result = self.apply()
        with self.assertRaisesRegex(c.Refused, "new path"):
            c.restore(result["archive_id"], self.root, self.store)
        self.assertEqual(self.keep.read_text(), "authored result")

    def test_archive_traversal_even_with_updated_checksum(self):
        result = self.apply()
        folder = self.store / "archives" / result["archive_id"]
        archive = folder / "files.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            item = tarfile.TarInfo("../escaped")
            item.size = 4
            tar.addfile(item, io.BytesIO(b"nope"))
        data = c.read_json(folder / "manifest.json")
        data["archive_sha256"] = c.digest(archive)
        c.write_json(folder / "manifest.json", data)
        with self.assertRaises(c.Refused):
            c.restore(result["archive_id"], self.base / "restored", self.store)
        self.assertFalse((self.base / "escaped").exists())

    def test_interrupted_removal_retains_verified_archive(self):
        plan = self.plan()
        with mock.patch.object(c.shutil, "rmtree", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                self.apply(plan)
        folder = self.store / "archives" / plan["id"]
        data = c.read_json(folder / "manifest.json")
        self.assertEqual(data["state"], "interrupted")
        self.assertEqual(data["stages"][0]["state"], "staged")
        c.restore(plan["id"], self.base / "restored", self.store)
        self.assertTrue((self.base / "restored/scratch/note.txt").exists())

    def test_scan_does_not_follow_symlink(self):
        (self.root / "link").symlink_to(self.base)
        result = c.inventory(self.root)
        self.assertEqual(next(r for r in result["items"] if r["path"] == "link")["symlinks"], 1)

    def test_private_permissions(self):
        plan = self.plan()
        self.assertEqual(Path(plan["plan"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.stat().st_mode & 0o777, 0o700)

    def test_source_changes_during_backup_are_retained(self):
        original = c.verify_archive
        def changed(*args):
            original(*args)
            (self.target / "note.txt").write_text("fresh edit")
        with mock.patch.object(c, "verify_archive", side_effect=changed):
            with self.assertRaisesRegex(c.Refused, "changed during backup"):
                self.apply()
        self.assertEqual((self.target / "note.txt").read_text(), "fresh edit")


class GitAuditTests(unittest.TestCase):
    def test_fresh_remote_and_local_changes(self):
        with tempfile.TemporaryDirectory(prefix="cleanmycodex-git-test-") as temp:
            base = Path(temp).resolve()
            repo, remote = base / "repo", base / "remote.git"
            def git(*args):
                return subprocess.run(["git", *map(str, args)], check=True, capture_output=True)
            git("init", "--bare", remote)
            git("init", "-b", "main", repo)
            git("-C", repo, "config", "user.name", "Test")
            git("-C", repo, "config", "user.email", "test@example.invalid")
            (repo / "source.txt").write_text("source")
            git("-C", repo, "add", ".")
            git("-C", repo, "commit", "-m", "Initial fixture")
            git("-C", repo, "remote", "add", "origin", remote)
            self.assertEqual(c.git_audit(repo, True)["status"], "partial")
            git("-C", repo, "push", "-u", "origin", "main")
            self.assertEqual(c.git_audit(repo)["status"], "unknown")
            self.assertEqual(c.git_audit(repo, True)["status"], "confirmed")
            (repo / "new.txt").write_text("not backed up")
            self.assertEqual(c.git_audit(repo, True)["status"], "partial")


THREAD = "11111111-1111-4111-8111-111111111111"
CURRENT = "22222222-2222-4222-8222-222222222222"


class FakeServer:
    def __init__(self):
        self.calls = []
        self.active, self.child, self.summary = False, False, False
    def call(self, method, params):
        self.calls.append(method)
        if method == "thread/read":
            return {"thread": {"id": THREAD, "status": {"type": "active" if self.active else "idle"},
                               "updatedAt": 123, "cwd": "/synthetic/workspace", "turns": []}}
        if method == "thread/list":
            return {"data": [{"parentThreadId": THREAD}] if self.child else [], "nextCursor": None}
        if method == "thread/turns/list":
            page = params["cursor"]
            return {"data": [{"id": "2" if page else "1", "itemsView": "summary" if self.summary else "full",
                              "status": "completed", "items": [{"text": "synthetic message"}]}],
                    "nextCursor": None if page else "next"}
        raise AssertionError(method)


class SessionTests(unittest.TestCase):
    def test_self_refused_without_read(self):
        fake = FakeServer()
        with self.assertRaises(c.Refused):
            s.collect(fake, THREAD, THREAD)
        self.assertEqual(fake.calls, [])

    def test_active_refused(self):
        fake = FakeServer()
        fake.active = True
        with self.assertRaises(c.Refused):
            s.collect(fake, THREAD, CURRENT)

    def test_children_refused(self):
        fake = FakeServer()
        fake.child = True
        with self.assertRaises(c.Refused):
            s.collect(fake, THREAD, CURRENT)

    def test_summary_only_export_refused(self):
        fake = FakeServer()
        fake.summary = True
        with self.assertRaises(c.Refused):
            s.collect(fake, THREAD, CURRENT)

    def test_paginated_backup_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="cleanmycodex-session-test-") as temp:
            base = Path(temp).resolve()
            summary = base / "summary.md"
            summary.write_text("# Synthetic continuity summary\nSaved decisions and next steps.\n")
            fake = FakeServer()
            result = s.backup(fake, THREAD, CURRENT, summary, c.storage(base / "private"))
            with gzip.open(Path(result["bundle"]) / "conversation.json.gz", "rt") as f:
                data = json.load(f)
            self.assertEqual([t["id"] for t in data["turns"]], ["1", "2"])
            self.assertFalse(result["native_deletion_performed"])
            self.assertNotIn("thread/delete", fake.calls)


if __name__ == "__main__":
    unittest.main()
