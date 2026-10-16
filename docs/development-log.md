# AI Development Log

This document records meaningful observations from
AI-assisted development and resulting improvements
to the development system.

## Entries

### 2026-10-16: Planning-session decisions where AI output was changed or rejected

- **Top review.** The AI recommended "highest-rated review" (simple,
  deterministic). I rejected it as systematically favorable to brands and
  chose the review closest to the mean. My first tie rule ("closest without
  going over") was itself replaced during reconciliation by strict nearest
  distance, with the lower rating preferred only on exact ties.
- **Industry filter options.** The AI raised a question I hadn't considered
  (where the dropdown's options come from) and laid out options. I chose a
  dedicated `GET /api/industries/` endpoint.
- **Average-rating precision.** The AI proposed rounding the API value to
  one decimal place. I moved that formatting to the UI and kept two decimal
  places in the API contract.
- **Audit log.** The AI proposed an audit log on PATCH to mitigate the
  ~5-minute role-staleness window. I removed it as scope with no CHALLENGE
  requirement behind it, and accepted the bounded window explicitly instead.
- **HTML sanitization.** The plan initially adopted the AI's recommendation
  to sanitize at render and keep stored HTML identical to WordPress. I
  reversed this: sanitize once at import, the trust boundary.
- **Process.** Decision records had started to mention who suggested what.
  I moved that history here so `decisions.md` records only what was decided
  and why.
