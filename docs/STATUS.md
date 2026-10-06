# Status and verification

Version: 0.1.0. Primary environment: macOS on Apple Silicon, Python 3.14.7, Git 2.56.0, Codex CLI 0.160.0.

## Verified

- 30 synthetic tests pass, including real filesystem compression/removal/restoration, unchanged preserved files, changed/new files, links, credentials, Git-tracked files, open files, xattrs, interrupted removal, tampered archives, traversal and replay refusal.
- Git backup classification is exercised against a disposable local bare remote before and after push, and after a new untracked file appears.
- Conversation export has synthetic pagination/compression tests and active/self/child/partial-history refusal tests. Live read-only native calls confirmed thread listing and a full-item turn page against the installed CLI protocol. No native deletion was performed.
- The dependency-free package validator passes. Skill frontmatter will also be checked through native discovery after installation. The optional upstream skill-creator validator needs PyYAML, which is not a product dependency.

## Pending release checks

- Public GitHub publication, installation from the remote marketplace, enabled-plugin/skill discovery, and invocation of the installed program.
- A real user-selected conversation cleanup from a separate chat is deferred. Its results must distinguish successful export, native deletion and measured disk reduction.
- Desktop UI invocation and GPT Work execution are not inferred from CLI discovery. No recurring automation has been created.

## Next useful work

1. Complete the separate, explicitly requested user-data test and record sanitized results only.
2. Validate native deletion and descendant scope on disposable conversations before adding a destructive native adapter.
3. Add metadata-complete macOS archives if real candidates are blocked by ACLs, resource forks or document xattrs.
4. Add opt-in periodic read-only audits after the manual workflow has been used.

Keep raw conversation data, absolute private paths, archive files and target IDs outside this public repository.
