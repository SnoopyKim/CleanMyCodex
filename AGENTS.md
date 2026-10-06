# Working on CleanMyCodex

Read README.md and docs/ARCHITECTURE.md before modifying cleanup behavior. Update docs/STATUS.md with evidence and remaining limits when behavior changes.

Only plugins/cleanmycodex ships in the plugin. Keep runtime scripts self-contained in its skill folder; use Python's standard library and avoid new credentials or external services without a concrete requirement.

Private conversations, archives, manifests, paths, runtime databases and test targets must stay outside this public repository. Use synthetic fixtures. Do not copy a user's workspace inventory into docs or issue reports. A GitHub push publishes everything tracked here.

Run `python3 -B -m unittest discover -s tests -v`, `python3 -B scripts/validate_package.py`, and `git diff --check` after relevant changes. Destructive behavior needs meaningful refusal and round-trip tests. Preserve native app-state protection; use supported host actions for chats/worktrees.

Do not run a real user-data cleanup as a routine build test. The user selects its scope and timing. Existing authorization should be carried forward, and a deferred test remains deferred.
