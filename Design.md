# MatchdayDB Design System

## Direction

A modern, minimalist scouting workspace. Player and team search are immediately visible. The interface uses compact typography, clear spacing, thin borders and a small yellow-green football accent. Decorative pitch graphics, oversized marketing headings, gradients and tinted green page backgrounds are removed.

## Palette

| Token | Light | Dark | Purpose |
| --- | --- | --- | --- |
| Page | `#F7F7F8` | `#111113` | Neutral canvas |
| Surface | `#FFFFFF` | `#19191C` | Cards, panels and controls |
| Raised surface | `#F1F1F3` | `#232327` | Selected filters and secondary areas |
| Text | `#202024` | `#EDEDF0` | Main content |
| Muted text | `#63636D` | `#A1A1AB` | Labels and supporting text |
| Border | `#E0E0E5` | `#303036` | Quiet separation |
| Accent | `#D6E566` | `#D6E566` | Primary actions, brand mark and meters |
| Accent text | `#22250E` | `#22250E` | Text on accent controls |
| Link | `#566116` | `#D6E566` | Small action links |
| Error | `#B52D39` | `#FF949F` | Failure text |

CSS variables are authoritative. The first visit follows the system colour scheme. The toggle persists an explicit preference in localStorage. `theme.js` applies it before rendering; failure to access storage still leaves a working theme. Page surfaces remain neutral in both modes.

## Layout and typography

Use the system sans-serif stack. Main title: 26px desktop, 23px mobile. Section headings: 18px. Body: 14px. Supporting copy: 12–13px. Numeric metrics use tabular figures. No font downloads are required.

A compact header contains the brand, dataset badge, theme control and GitHub link. Four workspace views separate Players, Player twins, Team scout, and Data & connection. The footer credits Aagam Shah (AagamS06) and links to his profile, source repository and API reference.

The desktop content width is approximately 1328px, with three player-card columns. Intermediate screens use two columns. Mobile uses one column, stacked filters, wrapping league controls and horizontally scrollable coverage tables. Components have 4–8px corner radii; modal dialogs use 10px.

## Components and behaviour

| Component | Contract |
| --- | --- |
| Search mode | Literal player name or semantic playing style; clear input guidance |
| Team field | Searchable text with complete loaded-club suggestions |
| League filter | All five named leagues, native radio behaviour |
| Sort | Full catalogue ordering; disabled for semantic ranking |
| Player card | Name, current club, role, age, nationality, rating, evidence and profile action |
| Metrics | Advanced per-90 fields when available; otherwise supplied basic totals and minutes |
| Dossier | Native dialog, full metrics, source, season, update time and twin action |
| Twin picker | Search names/teams, select a player, receive five similarity bars |
| Team report | Evidence, priority, shortlist reasons and skipped-check disclosure |
| Connection | Local password input, provider choice, memory-only credential explanation |
| Coverage table | Season, squads, players, statistical coverage and state for every league |
| Theme toggle | Functional light/dark switch with accessible action label |

## States and accessibility

Separate loading, empty, partial, failure and ready states. A partial roster must not look like a complete team. Demo labels use text, not colour alone. Unknown numbers display a dash. Ratings are labelled separately from profile similarity.

Use visible focus, native controls, semantic landmarks, a skip link, live feedback, labelled meters and Escape-to-close dialogs. Respect reduced-motion preferences. Browser smoke checks do not replace a formal accessibility audit.
