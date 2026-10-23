---
name: humanware_helper
description: Character voice anchors, deterministic dialogue scoring and consistency checks for the Humanware console.
type: python
---

Deterministic, model-free character voice helper consumed by the xs2
`/api/humanware/*` routes. All input/output is file-only and the JSON
contract is stable (see the helper's module docstring and the contract
reference in the xs2 repo: `docs/humanware-helper-contract.md`).

Command summary:

- `generate-voice <workspace_root>` — parse `meta/character_profiles.md`
  (`## 角色名` entries), write a `meta/character_voice.md` template with one
  anchor per character.
- `analyze-voice <workspace_root>` — scan `references/**/*.{md,txt}` for
  `## 角色名` sections containing quoted dialogue, derive per-character
  sentence fingerprints and write `meta/character_voice.md`.
- `score-text <workspace_root> <character> <content>` — score one passage
  against the character's anchor (sentence length, question/exclamation
  ratios, tone words, banned words), returning the four-dimension score used
  by the HumanwareScoreCard.
- `score-chapter <workspace_root> <chapter_file>` — score every quoted
  dialogue in a chapter (relative to the workspace), attributing each line to
  the nearest preceding `## 角色名` section, and aggregate.
- `check-dialogue <workspace_root> <character> <dialogue>` — returns whether
  the line matches the anchor, with rule-level violations and a suggestion.

Exit/stream contract:

- Process-level failures exit non-zero (route maps to HTTP 500).
- Business failures (missing files, unknown character, empty references)
  **exit 0** and print `{"status":"error","message":...,"code":<int>}`; the
  route forwards `code` as the HTTP status.
- Success prints one JSON object to stdout, UTF-8.

Workspace paths are resolved inside `<workspace_root>`; `..` escapes are
rejected. No model is called and no external service is contacted.