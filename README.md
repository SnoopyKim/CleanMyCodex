# CleanMyCodex

**로컬 AI 작업의 용량을 확인하고, 필요한 기록을 보존하면서 정리하는 Codex 플러그인.**

CleanMyCodex combines one agent skill with a small, standard-library Python program. The host agent handles context and summaries; deterministic scripts inventory files, check Git coverage, verify archives and restore files. No API key, environment-variable setup, MCP server or separate LLM subscription is required by the plugin.

## Install

Requirements: macOS, Python 3.11+, Git, lsof, and a Codex CLI with plugin support. Native conversation export currently targets the Codex CLI 0.160.0 protocol. Existing host authentication is used; the plugin introduces no new credentials.

```sh
codex plugin marketplace add SnoopyKim/CleanMyCodex --ref main
codex plugin add cleanmycodex@cleanmycodex
```

Open a new Codex chat or reload skills if the running client does not discover the installed skill immediately. Then ask:

> `$cleanmycodex`로 이 작업 폴더의 용량과 정리 후보를 확인해줘. 프로젝트는 Git 원격 백업 상태도 확인해줘.

> `$cleanmycodex`로 선택한 임시 자료를 압축 보관하고 정리해줘. 원본과 압축본이 같은지 검증하고 복원 방법도 남겨줘.

This repository is a Git-backed plugin marketplace. A public GitHub repository does not imply a listing in OpenAI's global plugin directory.

## What v0.1 does

| Capability | Behavior |
|---|---|
| Inventory | Recursive byte and allocated-size estimates grouped by immediate child |
| Git check | Live remote branch ancestry plus local changes, ignored files and stashes |
| File cleanup | Explicit selection → immutable-content plan → verified archive → removal |
| Restore | Verified extraction into a new directory, without overwriting work |
| Conversation backup | Paginated export of persisted Codex ThreadItems plus a continuity summary |
| Conversation deletion | Skill-guided native Codex deletion after separate checks; no direct DB edits |

No cleanup runs on install. There is no default schedule or automatic archive expiry. Real conversation deletion is deliberately deferred to a user-selected test in another chat.

## Develop locally

```sh
git clone https://github.com/SnoopyKim/CleanMyCodex.git ~/Develop/CleanMyCodex
cd ~/Develop/CleanMyCodex
./cleanmycodex --help
python3 -B -m unittest discover -s tests -v
python3 -B scripts/validate_package.py
```

The development checkout and installed plugin cache are separate copies. After publishing an update, refresh the marketplace and reinstall/update using the commands supported by your Codex CLI. Do not patch the plugin cache as the source of truth.

## File workflow

```sh
./cleanmycodex scan /absolute/workspace
./cleanmycodex git-audit /absolute/repository --check-remote
./cleanmycodex plan /absolute/workspace --target work --reason 'Completed temporary work'
./cleanmycodex apply /absolute/path/to/plan.json
./cleanmycodex restore ARCHIVE_UUID --to /absolute/new-restore-directory
```

`scan` and `git-audit` are read-only with respect to workspace content. `plan` creates private metadata. `apply` changes only the selected workspace entries after creating a verified archive. Supply only selections the user has authorized. Names such as `node_modules` are candidates, not proof that everything inside is disposable.

Private plans, manifests and compressed files live in `~/Library/Application Support/CleanMyCodex` on macOS, outside the source repository. A `--store DIRECTORY` option is available before the subcommand. Files are account-private (0600; directories 0700), unencrypted, and local. Retaining an archive uses space; reported reduction subtracts archive and manifest allocation, and remains an estimate rather than a disk-free-space guarantee.

## Chat cleanup from another session

Finish the target chat, open another project chat, then ask CleanMyCodex to preserve key results and archive the target before native deletion. Give it an unambiguous chat identifier. The skill checks target/current identity and the owning host's runtime state. The local export helper does not delete anything.

The exported conversation is readable JSON in gzip format. It preserves persisted conversation items available through the native protocol, not a complete restorable Codex database. Attachments and generated workspace files may need separate preservation. The plugin does not promise to recreate the original resumable chat or erase server-side/cloud copies. Known spawned child chats cause the helper to refuse until their full deletion scope is handled separately.

## Limits

- Active files, native app state, credentials, Git-tracked files, symlinks and hard links are protected.
- ACLs and document extended attributes/resource forks require a different backup method and are refused. macOS's OS-managed `com.apple.provenance` marker is allowed but not preserved as part of the file archive contract. File bytes, relative paths, permission bits and modification times are verified/restored.
- Close writers first. Open-file checks cannot lock every unrelated application or defeat a concurrent hostile filesystem change. Use trusted local workspaces.
- Git `confirmed` applies to the declared scope of local branches and HEAD. Git LFS payloads, submodules, local tags, ignored files, databases and external services need separate checks.
- Native deletion is version-sensitive and has not been exercised on a real conversation in release validation. Native archive and context compaction are not proof of disk savings.
- Codex Desktop/CLI local use is the primary target. GPT Work requires actual local execution access; Work Cloud and Windows are not supported by this release.

[Architecture and cleanup policy](docs/ARCHITECTURE.md) · [Verification and next work](docs/STATUS.md) · [MIT license](LICENSE)
