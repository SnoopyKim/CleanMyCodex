#!/usr/bin/env python3
"""Validate this repository's shipping contract without third-party packages."""
import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
plugin = root / "plugins/cleanmycodex"
portable = json.loads((plugin / "plugin.json").read_text())
compat = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text())
assert portable["name"] == compat["name"] == "cleanmycodex"
assert portable["version"] == compat["version"] == "0.1.0"
assert marketplace["plugins"][0]["source"]["path"] == "./plugins/cleanmycodex"
skill = plugin / "skills/cleanmycodex"
text = (skill / "SKILL.md").read_text()
assert text.startswith("---\nname: cleanmycodex\ndescription: ")
assert "$cleanmycodex" in (skill / "agents/openai.yaml").read_text()
for path in plugin.rglob("*.py"):
    ast.parse(path.read_text())
for path in plugin.rglob("*"):
    assert not path.is_symlink(), f"Shipping symlink: {path.name}"
    assert path.suffix not in {".gz", ".zip", ".jsonl", ".sqlite", ".pem", ".key"}, path.name
print("Package contract OK: one skill, two scripts, portable + compatibility manifests.")
