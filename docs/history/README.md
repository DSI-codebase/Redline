# Shipped-release documents

Feature summaries and hand-run test plans for versions that have shipped. They
are **write-once records**, kept for provenance and not maintained: each was
added and never revisited, which is why they sat at the repository root long
after `docs/` existed.

They are deliberately in a **subdirectory**. `app/help.py` builds the in-app
help from `folder.glob("*.md")` — non-recursive — so `docs/*.md` is the user
manual and nothing in here reaches it. Putting these files directly in `docs/`
would publish test plans as help pages.

| | for |
|---|---|
| `BETA_TEST_CHECKLIST.md` | the original beta |
| `V1.0.3_TEST_PLAN.md` | v1.0.3 |
| `testPlan.md` | v1.1.0 (named before the versioned convention) |
| `V1.1.0_FEATURES.md` · `V1.2.0_FEATURES.md` · `V1.3.0_FEATURES.md` | what each release added |
| `V1.2.0_TEST_PLAN.md` | v1.2.0 |

The living documents stay at the root: `README.md`, `CHANGELOG.md`, `CI.md`,
`CLAUDE.md`, `CONTRIBUTING.md`.
