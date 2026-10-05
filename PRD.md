# MatchdayDB Product Requirements

## Purpose and ownership

MatchdayDB is Aagam Shah's open-source local football scouting workspace. It helps scouts, analysts, students and football enthusiasts discover players, compare profiles and explore squad-planning needs. The canonical product name is MatchdayDB and the creator identity is Aagam Shah (AagamS06).

## User outcomes

A user can find a named player or browse a club, narrow the catalogue to a major European league, sort useful attributes, inspect a dossier, describe a desired playing style, and request five player twins. A team scout identifies supported planning indicators and supplies relevant candidates with reasons.

## Required behaviour

| Capability | Acceptance |
| --- | --- |
| Minimalist UI | Neutral light/dark canvases, restrained yellow-green accent, no decorative hero or pitch graphic |
| Theme control | Manual toggle, system default, saved non-sensitive preference, no required external asset |
| Player search | Partial names and aliases, case/accent normalization, safe parameterized SQL |
| Team search | Partial team text or exact selection, composable with league and scalar filters |
| Sorting | Name, age, position, rating, team, goals, assists, minutes and freshness; unknowns last |
| League coverage | PL, PD, BL1, SA and FL1 enabled by default; complete available live pages rather than a 60-player cap |
| Current data | Provider current-season discovery; refresh action; season, source and coverage visible |
| Provider connection | football-data.org, with a synthetic-demo fallback; local key input, opt-in local persistence, isolated databases |
| Semantic search | Local 384-dimensional MiniLM embeddings with compatible-index checks |
| Twins | Searchable player selector, five nearest profiles, explicit similarity interpretation |
| Team scout | Evidence-backed depth, succession and performance indicators; outside-club shortlists; sparse checks skipped |
| Attribution | Footer links to Aagam Shah's profile and MatchdayDB repository |
| Offline example | Explicitly historical synthetic demo; never presented as current provider evidence |

## Evidence boundaries

The no-key demo remains a reproducible 60-player example. It cannot represent every real current player. Full current coverage requires a provider account with suitable season access and quota. No API key or subscription is bundled.

Live basic statistics include only fields actually supplied. Advanced xG, xA and progressive actions are not fabricated. A provider rating is not a semantic similarity score. Team findings are planning heuristics, not causal diagnoses, medical judgments or claims that a player can be signed.

## Operational requirements

Support Python 3.11+, CPU inference, SQLite, one local process and a frontend with no build step. Avoid import-time network activity. Enforce bounded HTTP timeouts, quota control, retry limits, atomic squad changes, schema migration and clear error reports. Preserve browsing during model preparation and incomplete imports.

## Excluded scope

Public multi-user hosting, authentication, payments, automatic account signup, purchasing a subscription, injury prediction, contracts, wages, transfer negotiations, guaranteed scouting relevance and redistributing licensed provider data are outside this release.

## Release acceptance

Automated tests cover old and new backend workflows. Browser verification covers both themes, search, sorting, comparison, team audit, responsive overflow and attribution. A real-account coverage test and cross-platform matrix remain necessary before declaring broad production deployment support.
