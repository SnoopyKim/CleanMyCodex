---
name: cleanmycodex
description: Audit Codex workspace storage, check remote Git backup coverage, archive and restore disposable local work, and prepare saved conversation cleanup. Use when the user wants to reclaim space from AI workspaces, generated artifacts, or saved chats.
---

# CleanMyCodex

Use the bundled Python scripts; resolve their paths relative to this SKILL.md. No API key, environment configuration, pip package, or external service is required. Python 3.11+, Git, and lsof are needed. Native conversation export additionally needs a compatible Codex CLI (verified protocol: 0.160.0).

## Review and file cleanup

1. Identify the exact chat, workspace, repository and any shared use. In the desktop app, prefer available list/read chat and project tools. A date folder is not a single disposable session. Report uncertain mappings explicitly.
2. Run `python3 -B scripts/cleanmycodex.py scan ROOT`. This lists immediate children with recursive sizes without reading file content or following links. Scan specific workspaces rather than the entire home directory. A cache name is only a candidate.
3. For projects, run `python3 -B scripts/cleanmycodex.py git-audit REPO --check-remote`. Explain its scoped result: live remote branch ancestry, local changes, ignored files and stashes. LFS data, submodules, local tags, credentials, databases and external services are separate. Never equate a configured remote with a backup. Do not push content without user authorization.
4. Preserve useful decisions/results/next steps in existing project documentation when appropriate. For temporary conversations, create a short continuity summary in private local storage. Use actual content and evidence; do not put private conversation data in the plugin's source repository.
5. Identify specific cleanup paths and their reasons. Carry forward the user's existing authorization. Ask only if scope or authorization is missing. A request for an audit authorizes read-only inspection; a request to clean selected data authorizes that selection. Do not ask for the same authorization twice.
6. Create a plan with `python3 -B scripts/cleanmycodex.py plan ROOT --target RELATIVE_PATH --reason REASON` (repeat `--target`). The plan is saved privately and records file hashes. Present the selection, source size, preservation and restore route. Compression savings are unknown until measured.
7. Run `python3 -B scripts/cleanmycodex.py apply PLAN_PATH` within the authorized scope. It checks for changes and open files, verifies a compressed backup, stages selected paths, and removes those staged copies. It refuses tracked source files, native app state, credentials, symlinks, hard links and unsupported metadata. Close writers before running; open-file checks are observations, not an OS-wide lock.
8. Report actual source/archive sizes, the manifest path, any skipped items, and remaining limitations. To restore, run `python3 -B scripts/cleanmycodex.py restore ARCHIVE_UUID --to NEW_DIRECTORY`. Never overwrite existing work.

Default private store: `~/Library/Application Support/CleanMyCodex` on macOS; `~/.local/share/cleanmycodex` elsewhere. The main script accepts `--store DIRECTORY` before its subcommand. Keep this directory outside every Git repository and cleanup root. Archives are local, unencrypted and readable by the local account; they are not cloud backups. No automatic retention purge is configured.

If an operation is interrupted, inspect its manifest and recorded stage paths. Do not replay the plan or delete its stage/lock blindly. The verified archive can be restored to a new directory. Preserve any staged newer edits until reconciled.

## Saved conversation cleanup

Perform this from a different chat after the target is idle. File cleanup and native conversation deletion are separate operations. Current-chat deletion is refused. If the user defers a test to another session, prepare only; do not execute it now.

1. Resolve target and current chat UUIDs through the host's actual context/tools. Confirm runtime status in the owning host, not only a standalone app-server: another app-server can report a running chat as `notLoaded`.
2. Read the target conversation, preserve a useful summary in private storage, and identify local outputs/attachments that must be separately archived. ChatGPT cloud chats and remote hosts are outside the bundled local adapter's scope.
3. Run `python3 -B scripts/session_backup.py TARGET_UUID --current-thread CURRENT_UUID --summary SUMMARY_PATH`. It exports all persisted ThreadItems exposed by the local Codex app-server across every page, compresses them, checks hashes and keeps a manifest. It refuses active/self targets, partial item views, changes during export and known spawned child chats. It performs no deletion. Do not use a truncated host chat summary as the only backup.
4. Inspect the saved export and manifest for the expected thread, first/last turns and completeness. Referenced images/files and raw internal events are not guaranteed to be embedded. Preserve needed referenced files separately. If a child-chat deletion scope or export completeness is uncertain, stop the deletion step and explain the concrete missing evidence.
5. If the user explicitly requested permanent deletion and the backup and full deletion scope are verified, recheck that the target remained idle and unchanged since the export. Check the current `codex delete --help`, then use the supported native `codex delete --force TARGET_UUID`. Never issue raw database, WAL, session JSONL or application-folder deletion. Native refusal means stop; do not work around active-session protection.
6. Verify the native result through supported chat lookup and report it accurately. If deletion cannot be verified, report that uncertainty. Native history deletion has not been exercised in v0.1 release validation. A readable compressed export does not recreate the same native resumable chat. Native archive only hides a chat and does not promise disk savings.

For desktop-managed worktrees, use the host's archive/restore worktree tools when applicable. Check ignored files first; a worktree archive need not preserve them. Do not apply the generic file cleaner to managed worktrees.

## Operating boundaries

Only the requested workspace selection is authorized. Keep app databases, authentication, settings, installed plugins and browser profiles protected. Preserve `.env` and original assets even when Git says clean. Do not compact or rewrite native transcripts directly. Context compaction does not establish disk savings.

The first release is designed for local macOS Codex workflows. GPT Work can use it only when that environment provides local execution and filesystem access. Do not promise Work Cloud local-disk access. Linux file operations have tests but are not the primary verified environment; Windows is unsupported.

For recurring requests, use the host's supported automation tools, starting with read-only audits unless the user has authorized a specific ongoing cleanup policy. Installing this plugin schedules nothing. An unchanged audit need not notify the user when their notification preference says to stay quiet.
