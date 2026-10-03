# MatchdayDB Design System

## Direction

A calm, dark football scouting workspace. Search is the primary action. Player twins, source provenance, and readiness stay visible beside the result collection. Product name: MatchdayDB.

## Palette

| Token | Value | Use |
| --- | --- | --- |
| Background | `#0C1110` | Page canvas |
| Surface | `#131A17` | Panels and cards |
| Raised surface | `#19221D` | Secondary emphasis |
| Border | `#28352C` | Separators |
| Primary text | `#F0F3ED` | Headings and key content |
| Muted text | `#97A69B` | Supporting labels |
| Accent | `#C4F36B` | Primary action, active controls, meters |
| Accent text | `#142109` | Text on green buttons |
| Synthetic/partial | `#EDC582` | Demo and partial status |
| Error | `#FFA59C` | Error emphasis |

CSS variables in `static/style.css` are authoritative. Dark mode is implemented; do not add a nonfunctional theme switch.

## Typography and layout

Use the local system sans-serif stack, with Inter only when already installed. Use a system monospace stack for dataset labels. No external font request is required. Use tabular numbers for metrics.

Hero type scales from 32 to 52px; section headings are approximately 23px. Cards prioritize name, team/role, tactical text, per-90 values, then actions. Preserve Unicode names and accents.

Content width is capped at 1440px. Panels use a 16px radius, cards 12px, controls 7–8px. Use restrained borders, an 8px spacing rhythm, and compact tags rather than heavy shadows.

Desktop contains a hero, four-part overview, main scouting column, comparison/status sidebar, fixture feed, and footer. Cards use three columns on wide screens and two on standard desktop. Tablet moves sidebar panels below results. Mobile uses one-column cards and a stacked search action. The decorative CSS pitch disappears on narrow screens.

## Components

| Component | Behaviour |
| --- | --- |
| Search | Labelled text, submit, role chips, explicit scalar filters, reset |
| Chip | Inserts a complete tactical query and exposes pressed state |
| Card | Role/source, bio, xG/xA/progressive passes per 90, dossier and twin buttons |
| Dossier | Native modal dialog, full metrics, provenance, Escape/close, comparison action |
| Twin picker | Complete player selector and five ranked matches |
| Score bar | Semantic meter with accessible numerical label and calculation explanation |
| Status | Source, last job, progress, error recovery, sync action |
| Fixture | Stored date/status/teams, nullable score, synthetic/provider context |

## State and accessibility rules

Show loading separately from empty results. Keep browsing available during model preparation. Errors should be actionable and must not present stale rankings as fresh. Synthetic labels use text as well as colour. Unknown metrics display an em dash.

Use native form controls, labels, explicit action buttons, a skip link, visible focus, and reduced-motion support. Verify keyboard flow and narrow-screen overflow. The initial visual design is not a claim of formal WCAG conformance; an accessibility audit remains release work.

## Asset boundaries

No frontend framework, build tool, remote script, stock player photography, or guessed crest asset is needed. CSS geometry and initials provide visual identity. Provider strings enter the DOM through safe text/value APIs.
