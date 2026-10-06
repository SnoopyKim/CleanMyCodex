# Architecture and cleanup policy

## Responsibilities

- The skill connects user intent, chat/workspace identity, useful context and authorization. It produces human-readable summaries through the host model.
- The file program handles inventory, explicit target plans, fresh validation, archive verification, staged removal and restoration.
- The read-only native adapter exports persisted conversation items. The skill delegates permanent deletion to Codex's supported command only after complete scope/backup checks.
- GitHub distributes source code and documentation. Private operational data stays in a separate local store.

The plugin contains no background daemon, hooks, network API client or telemetry. Git remote checks and native Codex reads use existing installed tools. It needs no user-configured environment variables.

## File transaction

1. Hash selected regular files and record directory entries, permissions and modification times. Reject protected and overlapping paths.
2. Before apply, check fingerprints, Git tracking, open files and unsupported filesystem metadata.
3. Write a gzip tar archive and a private manifest. Read the entire archive back and verify all member types, names, sizes, permissions and file hashes.
4. Recheck the source, record a stage path in the manifest, then rename within the workspace filesystem.
5. Recheck the staged content/open-file state before removing it. Update the manifest after each target.
6. Restore only verified regular files/directories into a temporary extraction directory, verify hashes, then publish to a new destination.

An interrupted run is not replayed. Its manifest identifies any stage locations; restore the verified archive to a new directory and reconcile retained newer edits. Root locks coordinate CleanMyCodex processes only. They are not locks against unrelated writers. Private storage is outside both the cleanup root and every Git repository.

The local manifest is trusted, account-private transaction metadata, not an authenticated proof against a malicious account holder. The tar parser rejects traversal, links, duplicate/unknown members and missing content. No automatic archive pruning exists in v0.1.

## Git evidence

The audit reads local branches/HEAD, status, ignored files and stashes. With `--check-remote`, it queries live remote branch tips and checks commit ancestry using locally available Git objects. If remote history is not locally available, it reports unknown rather than fetching or assuming backup coverage. It never pushes.

The result includes a scope statement. A confirmed code-history check is not a backup of LFS blobs, submodule repositories, local tags, ignored environments, databases or deployment state. Those remain separate preservation decisions. The file engine refuses Git-tracked files regardless of the audit result.

## Native conversation boundaries

The export adapter uses initialize, thread/read, thread/list and thread/turns/list. It requests full items, follows every continuation cursor, rejects duplicate pages, and rechecks updatedAt. It checks both archived and visible thread metadata for known child chats. Thread listing uses the native state index and cannot certify data absent from that index.

The owning host must separately establish that a target is idle: a new standalone app-server can report `notLoaded` even while another host process is running it. The explicit current chat ID prevents self-selection. A native delete refusal is final; no database or raw-rollout fallback is allowed.

The compressed JSON is an export for reading and future summaries, not a native database restore. Referenced local or external attachments must be inspected separately before deletion. The native CLI may have a broader descendant-deletion scope; unknown descendants or incomplete exports block deletion. Skill instructions retain the user's explicit choice about timing.

## Deliberately deferred

Automatic retention, permanent cache purging without archives, metadata-complete macOS backups, full tree exports for spawned chats, Work Cloud, Windows, and a standalone graphical app. Add these from observed needs; do not infer permission to perform them from installation.

## Packaging references

The portable plugin manifest and compatibility manifest ship together. The repository root contains the marketplace, while only `plugins/cleanmycodex` is the plugin payload. Consult the current [official packaging documentation](https://developers.openai.com/plugins/build/plugins) and [client capabilities](https://learn.chatgpt.com/docs/plugins) when changing this contract. Installed plugin discovery and actual desktop UI invocation are different verification claims.
