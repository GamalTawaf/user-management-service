# Shared agent contract

Portable operating files for **any** coding agent. Start at repo-root `AGENTS.md`, then this tree.

| Path | Role |
|------|------|
| `feature_list.json` | Shipped feature inventory + evidence |
| `progress.md` | Compact shipped log |
| `session-handoff.md` | System snapshot + walkthrough |
| `rules/` | Operating rules (same bodies Cursor auto-loads) |
| `skills/` | On-demand workflows (`session-start`, `open-pr`, …) |

**Cursor:** `.cursor/rules` and `.cursor/skills` are symlinks into `rules/` / `skills/` so Cursor keeps auto-discovering them. Edit files under `.agent/` only — do not duplicate content under `.cursor/`.
