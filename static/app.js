"use strict";
const $ = (id) => document.getElementById(id);
const state = { health: null, options: { players: [], teams: [] }, offset: 0, total: 0, view: "players", controllers: new Map(), dialogPlayer: null, signature: "", refreshing: false };
let pendingSelects = { position: "", nationality: "" };
let selectsApplied = false;
const roleNames = { GK: "Goalkeeper", CB: "Centre-back", LB: "Left-back", RB: "Right-back", DM: "Defensive midfielder", CM: "Central midfielder", AM: "Attacking midfielder", LW: "Left winger", RW: "Right winger", ST: "Striker", DEF: "Defender", MID: "Midfielder", FWD: "Forward", UNKNOWN: "Unknown position" };
const leagueNames = { PL: "Premier League", PD: "La Liga", BL1: "Bundesliga", SA: "Serie A", FL1: "Ligue 1" };
const formatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const number = (value) => value === null || value === undefined ? "—" : formatter.format(value);
const dateTime = (value) => value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Unknown";
function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function feedback(id, message = "", error = false) { const target = $(id); target.textContent = message; target.classList.toggle("hidden", !message); target.classList.toggle("error", error); }
function channel(name) { state.controllers.get(name)?.abort(); const controller = new AbortController(); state.controllers.set(name, controller); return controller; }
async function api(path, options = {}) {
  const controller = new AbortController();
  let timeout = false;
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = setTimeout(() => { timeout = true; controller.abort(); }, 150000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, credentials: "same-origin", headers: { Accept: "application/json", ...options.headers } });
    let payload;
    try { payload = await response.json(); } catch { throw new Error(`The server returned an unexpected (non-JSON) response (${response.status}). Confirm python app.py is running this version of the code.`); }
    if (!response.ok) throw new Error(payload.error?.message || payload.detail || payload.message || `Request failed (${response.status}).`);
    return payload;
  } catch (error) {
    if (timeout) throw new Error("This request took too long. Check Data & connection and retry.");
    throw error;
  } finally { clearTimeout(timer); options.signal?.removeEventListener("abort", abort); }
}
function showView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((node) => node.classList.toggle("hidden", node.id !== `view-${view}`));
  document.querySelectorAll(".tab").forEach((node) => { const active = node.dataset.view === view; node.classList.toggle("active", active); if (active) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
}
function themeLabel() { const dark = document.documentElement.dataset.theme === "dark"; $("theme-toggle").textContent = dark ? "Light theme" : "Dark theme"; $("theme-toggle").setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} theme`); }
function syncURL() {
  const params = new URLSearchParams();
  if (state.view !== "players") params.set("view", state.view);
  const q = $("query").value.trim(); if (q) params.set("q", q);
  if ($("search-mode").value !== "players") params.set("mode", $("search-mode").value);
  if ($("team-filter").value.trim()) params.set("team", $("team-filter").value.trim());
  if ($("position").value) params.set("position", $("position").value);
  if ($("nationality").value) params.set("nationality", $("nationality").value);
  if ($("max-age").value) params.set("max_age", $("max-age").value);
  const league = document.querySelector('input[name="league"]:checked')?.value; if (league) params.set("league", league);
  if ($("sort-by").value !== "name:asc") params.set("sort", $("sort-by").value);
  if (state.offset) params.set("offset", String(state.offset));
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}
function restoreFromURL() {
  const params = new URLSearchParams(location.search);
  const view = params.get("view");
  if (view && $(`view-${view}`)) showView(view);
  $("query").value = params.get("q") || "";
  const mode = params.get("mode") === "style" ? "style" : "players";
  $("search-mode").value = mode;
  $("style-chips").classList.toggle("hidden", mode !== "style");
  $("query").maxLength = mode === "style" ? 1000 : 200;
  if (mode === "style") $("query").placeholder = "Describe a role or playing style";
  $("team-filter").value = params.get("team") || "";
  if (params.get("max_age")) $("max-age").value = params.get("max_age");
  const league = params.get("league") || "";
  const radio = document.querySelector(`input[name="league"][value="${league}"]`); if (radio) radio.checked = true;
  if (params.get("sort")) $("sort-by").value = params.get("sort");
  const offset = parseInt(params.get("offset"), 10);
  state.offset = Number.isFinite(offset) && offset > 0 ? offset : 0;
  pendingSelects = { position: params.get("position") || "", nationality: params.get("nationality") || "" };
}
$("theme-toggle").addEventListener("click", () => { const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = next; try { localStorage.setItem("matchday-theme", next); } catch { /* Preference is optional in private browsing. */ } themeLabel(); });
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => { let saved = false; try { saved = ["dark", "light"].includes(localStorage.getItem("matchday-theme")); } catch { saved = false; } if (!saved) { document.documentElement.dataset.theme = event.matches ? "dark" : "light"; themeLabel(); } });
themeLabel();
document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => { showView(button.dataset.view); syncURL(); }));
$("notice-action").addEventListener("click", () => showView("data"));
function option(value, text) { const node = element("option", "", text); node.value = value; return node; }
function fillSelect(id, entries, first) { const node = $(id); const old = node.value; node.replaceChildren(option("", first), ...entries.map(([value, label]) => option(value, label))); if ([...node.options].some((item) => item.value === old)) node.value = old; }
function fillTwins() { const term = $("twin-search").value.trim().toLocaleLowerCase(); const entries = state.options.players.filter((player) => `${player.name} ${player.team_name || ""}`.toLocaleLowerCase().includes(term)); fillSelect("twin-player", entries.map((player) => [String(player.player_id), `${player.name} · ${player.team_name || "No club"}`]), entries.length ? "Choose a player" : "No matching players"); }
async function refreshOptions() {
  state.options = await api("/options");
  fillSelect("position", state.options.positions.map((code) => [code, roleNames[code] || code]), "All positions");
  fillSelect("nationality", state.options.nationalities.map((country) => [country, country]), "All countries");
  $("team-list").replaceChildren(...state.options.teams.map((team) => option(team.name, `${team.name} · ${leagueNames[team.league] || team.league}`)));
  fillTwins();
  if (!selectsApplied) {
    if (pendingSelects.position && [...$("position").options].some((item) => item.value === pendingSelects.position)) $("position").value = pendingSelects.position;
    if (pendingSelects.nationality && [...$("nationality").options].some((item) => item.value === pendingSelects.nationality)) $("nationality").value = pendingSelects.nationality;
    selectsApplied = true;
  }
}
function selectedTeam(text) { const key = text.trim().toLocaleLowerCase(); return state.options.teams.find((team) => team.name.toLocaleLowerCase() === key); }
function filters() {
  const params = new URLSearchParams();
  for (const [id, field] of [["position", "position"], ["nationality", "nationality"], ["max-age", "max_age"]]) if ($(id).value) params.set(field, $(id).value);
  const league = document.querySelector('input[name="league"]:checked').value;
  if (league) params.set("league", league);
  const teamText = $("team-filter").value.trim();
  const team = selectedTeam(teamText);
  if (team) params.set("team_id", team.team_id); else if (teamText) params.set("team", teamText);
  return params;
}
function metricList(metrics) { const list = element("dl", "metric-grid"); for (const [label, value] of metrics) { const group = element("div"); group.append(element("dt", "", label), element("dd", "", number(value))); list.append(group); } return list; }
function scoreMeter(player) {
  const container = element("div", "similarity");
  const line = element("div", "score-line");
  line.append(element("span", "", player.statistical_score === null || player.statistical_score === undefined ? "Profile similarity" : "Hybrid similarity"), element("span", "", `${number(player.similarity_percentage)}%`));
  const meter = element("meter"); meter.min = 0; meter.max = 100; meter.value = Math.max(0, Math.min(100, player.similarity_percentage)); meter.setAttribute("aria-label", `${number(player.similarity_percentage)} percent similarity`);
  container.append(line, meter); return container;
}
function playerCard(player) {
  const card = element("article", "player-card");
  const top = element("div", "card-top"); const identity = element("div");
  identity.append(element("h3", "player-name", player.name), element("p", "card-team", player.team_name || "No current club"));
  const rating = element("div", "rating", number(player.rating)); rating.append(element("small", "", player.synthetic ? "Demo / 10" : "Rating / 10")); rating.title = player.rating_source || "Rating unavailable";
  top.append(identity, rating);
  const meta = element("div", "card-meta"); meta.append(element("span", "position-tag", player.position), element("span", "", player.age === null ? "Age unknown" : `Age ${player.age}`), element("span", "", player.nationality || "Nationality unknown"));
  card.append(top, meta, element("p", "card-bio", player.tactical_summary));
  if (player.recommendation_reason) card.append(element("p", "recommendation", player.recommendation_reason));
  if (player.similarity_percentage !== undefined) card.append(scoreMeter(player));
  const metrics = player.per90?.xG !== null && player.per90?.xG !== undefined ? [["xG / 90", player.per90.xG], ["xA / 90", player.per90.xA], ["Prog. passes / 90", player.per90.progressive_passes]] : [["Goals", player.totals?.goals], ["Assists", player.totals?.assists], ["Minutes", player.minutes_played]];
  card.append(metricList(metrics));
  const bottom = element("div", "card-bottom"); const open = element("button", "text-button", "View profile ↗"); open.type = "button"; open.setAttribute("aria-label", `View ${player.name}'s profile`); open.addEventListener("click", () => showPlayer(player));
  bottom.append(element("span", "", `${leagueNames[player.league] || player.league || "Unassigned"} · ${player.synthetic ? "Synthetic" : player.season}`), open); card.append(bottom); return card;
}
function empty(target, title, message) { const node = element("div", "empty"); node.append(element("h3", "", title), element("p", "", message)); target.replaceChildren(node); }
async function loadPlayers() {
  if (!$("search-form").reportValidity()) return;
  const controller = channel("players");
  const q = $("query").value.trim(); const semantic = $("search-mode").value === "style" && q.length > 0;
  $("sort-by").disabled = semantic; $("ranking-note").textContent = semantic ? "Ranked by profile similarity" : "Unknown values sort last";
  $("results").setAttribute("aria-busy", "true"); feedback("search-feedback", "Loading players");
  const params = filters();
  if (q) params.set("q", q);
  if (semantic) params.set("top_k", "24"); else { const [sort, order] = $("sort-by").value.split(":"); params.set("sort_by", sort); params.set("order", order); params.set("limit", "12"); params.set("offset", state.offset); }
  try {
    const result = await api(`${semantic ? "/search" : "/players"}?${params}`, { signal: controller.signal });
    if (controller.signal.aborted) return;
    state.total = semantic ? result.items.length : result.total;
    $("results-title").textContent = semantic ? "Tactical matches" : q ? `Players matching “${q}”` : "Player collection";
    $("results-meta").textContent = semantic ? `${result.items.length} matches from ${result.eligible_count} indexed profiles` : `${number(result.total)} players found`;
    if (result.items.length) $("results").replaceChildren(...result.items.map(playerCard)); else empty($("results"), "No matching players", state.health?.synthetic ? "Try another name or filter. Connect live data for complete league squads." : "Try another filter or check league coverage in Data & connection.");
    $("pagination").classList.toggle("hidden", semantic || result.total <= 12);
    $("previous-page").disabled = state.offset === 0; $("next-page").disabled = state.offset + 12 >= state.total;
    $("page-label").textContent = `Page ${Math.floor(state.offset / 12) + 1} of ${Math.max(1, Math.ceil(state.total / 12))}`;
    feedback("search-feedback");
  } catch (error) { if (error.name !== "AbortError") { feedback("search-feedback", error.message, true); empty($("results"), "Search unavailable", "Check Data & connection, then retry."); } }
  finally { if (!controller.signal.aborted) $("results").setAttribute("aria-busy", "false"); }
}
let playerTimer;
function rerunPlayers() { clearTimeout(playerTimer); state.offset = 0; syncURL(); void loadPlayers(); }
function delayedSearch() { clearTimeout(playerTimer); playerTimer = setTimeout(rerunPlayers, 280); }
$("search-form").addEventListener("submit", (event) => { event.preventDefault(); rerunPlayers(); });
$("query").addEventListener("input", () => { if ($("search-mode").value === "players") delayedSearch(); });
$("team-filter").addEventListener("input", delayedSearch);
for (const id of ["position", "nationality", "max-age", "sort-by"]) $(id).addEventListener("change", rerunPlayers);
document.querySelectorAll('input[name="league"]').forEach((input) => input.addEventListener("change", rerunPlayers));
$("search-mode").addEventListener("change", () => { const semantic = $("search-mode").value === "style"; $("style-chips").classList.toggle("hidden", !semantic); $("query").maxLength = semantic ? 1000 : 200; $("query").placeholder = semantic ? "Describe a role or playing style" : "Search a player, e.g. Bukayo Saka"; $("query").value = ""; rerunPlayers(); });
document.querySelectorAll("[data-query]").forEach((button) => button.addEventListener("click", () => { $("query").value = button.dataset.query; rerunPlayers(); }));
$("reset-filters").addEventListener("click", () => { $("search-form").reset(); $("style-chips").classList.add("hidden"); $("query").placeholder = "Search a player, e.g. Bukayo Saka"; $("query").maxLength = 200; rerunPlayers(); });
$("previous-page").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 12); syncURL(); void loadPlayers(); });
$("next-page").addEventListener("click", () => { state.offset += 12; syncURL(); void loadPlayers(); });
function showPlayer(player) {
  state.dialogPlayer = player; const content = $("dialog-content"); const title = element("h2", "", player.name); title.id = "dialog-title";
  content.replaceChildren(title, element("p", "", `${player.team_name || "No club"} · ${roleNames[player.position] || player.position} · ${player.age === null ? "Age unknown" : `Age ${player.age}`}`), element("p", "", player.tactical_summary));
  if (player.similarity_percentage !== undefined) content.append(scoreMeter(player));
  content.append(metricList([["Rating / 10", player.rating], ["Appearances", player.matches_played], ["Minutes", player.minutes_played], ["Goals", player.totals?.goals], ["Assists", player.totals?.assists], ["Pass completion %", player.pass_accuracy], ["xG / 90", player.per90?.xG], ["xA / 90", player.per90?.xA], ["Progressive passes / 90", player.per90?.progressive_passes], ["Tackles won / 90", player.per90?.tackles_won], ["Progressive carries / 90", player.per90?.progressive_carries], ["Market value (€)", player.market_value]]));
  content.append(element("p", "footnote", `${player.synthetic ? "Synthetic historical example" : "Provider records"} · Season ${player.season}. Stats updated: ${dateTime(player.stats_updated_at)}. ${player.rating_source || "No rating supplied"}.`), element("p", "footnote", "A dash means unknown. Advanced metrics are shown only when supplied; they are never estimated from basic stats."));
  $("player-dialog").showModal();
}
$("close-dialog").addEventListener("click", () => $("player-dialog").close());
$("dialog-compare").addEventListener("click", () => { const player = state.dialogPlayer; if (!player) return; $("player-dialog").close(); $("twin-search").value = ""; fillTwins(); $("twin-player").value = String(player.player_id); showView("twins"); void loadTwins(); });
$("twin-search").addEventListener("input", fillTwins);
async function loadTwins() {
  const controller = channel("twins");
  const player = state.options.players.find((item) => String(item.player_id) === $("twin-player").value);
  $("twins").replaceChildren();
  if (!player) { feedback("twin-feedback", "Select a reference player."); return; }
  feedback("twin-feedback", `Finding matches for ${player.name}`);
  const params = new URLSearchParams({ player_id: player.player_id, top_k: "5", cross_role: String($("cross-role").checked), ranking: $("hybrid-ranking").checked ? "hybrid" : "semantic" });
  try {
    const result = await api(`/similar/${encodeURIComponent(player.name)}?${params}`, { signal: controller.signal });
    if (controller.signal.aborted) return;
    $("twins").replaceChildren(...result.items.map(playerCard));
    feedback("twin-feedback", `${result.items.length} matches for ${player.name}. ${result.ranking === "hybrid" ? "75% semantic similarity and 25% statistical similarity." : "Cosine similarity × 100; negative values display as zero."}`);
    if (!result.items.length) empty($("twins"), "No comparable profiles", "Refresh the index or allow comparison across roles.");
  } catch (error) { if (error.name !== "AbortError") feedback("twin-feedback", error.message, true); }
}
for (const id of ["twin-player", "cross-role", "hybrid-ranking"]) $(id).addEventListener("change", () => void loadTwins());
$("team-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const typed = $("audit-team").value.trim(); let team = selectedTeam(typed);
  if (!team) { const candidates = state.options.teams.filter((item) => item.name.toLocaleLowerCase().includes(typed.toLocaleLowerCase())); if (candidates.length === 1) team = candidates[0]; }
  if (!team) { feedback("team-feedback", "Choose a specific team from the suggestions.", true); return; }
  $("audit-team").value = team.name; const controller = channel("team"); feedback("team-feedback", `Assessing ${team.name}`); $("team-results").replaceChildren();
  const params = new URLSearchParams({ top_k: "5" }); if ($("audit-age").value) params.set("max_age", $("audit-age").value);
  try {
    const result = await api(`/teams/${team.team_id}/needs?${params}`, { signal: controller.signal });
    if (controller.signal.aborted) return;
    feedback("team-feedback", result.scope);
    const summary = element("div", "audit-summary"); summary.append(element("strong", "", team.name), element("span", "", `${result.squad_size} players`), element("span", "", result.season), element("span", "", result.complete_roster ? "Complete roster loaded" : "Partial or sample roster"));
    $("team-results").append(summary);
    if (!result.issues.length) { const note = element("div", "panel"); note.append(element("h3", "", result.skipped_checks.length ? "More data is needed for a full assessment" : "No gaps met the current thresholds"), element("p", "subtle", result.skipped_checks.length ? "The scout will not infer a weakness from missing players or missing statistics. Refresh live squads and stats to enable more checks." : "Review the squad manually alongside these planning indicators.")); $("team-results").append(note); }
    for (const issue of result.issues) {
      const section = element("section", "issue"); const head = element("div", "issue-head"); head.append(element("h3", "", issue.title), element("span", "tag", `${issue.priority} priority`));
      section.append(head, element("p", "", issue.evidence), element("p", "footnote", issue.method));
      const cards = element("div", "player-grid"); cards.append(...issue.recommendations.map(playerCard));
      if (!issue.recommendations.length) empty(cards, "No supported recommendations", "No player with sufficient evidence meets this need and your recruitment filters.");
      section.append(cards, element("p", "footnote", `Shortlist order: ${issue.ranking_basis}.`)); $("team-results").append(section);
    }
    if (result.skipped_checks.length) { const details = element("details"); details.append(element("summary", "", `${result.skipped_checks.length} checks skipped`)); const list = element("ul"); for (const reason of result.skipped_checks) list.append(element("li", "", reason)); details.append(list); $("team-results").append(details); }
  } catch (error) { if (error.name !== "AbortError") feedback("team-feedback", error.message, true); }
});
async function loadFixtures() { const data = await api("/fixtures"); $("fixture-source").textContent = data.synthetic ? "Synthetic fixture examples" : "Stored provider snapshots"; const cards = data.items.map((fixture) => { const card = element("article", "fixture"); card.append(element("p", "fixture-head", `${dateTime(fixture.kickoff)} · ${fixture.status}`)); for (const side of ["home", "away"]) { const row = element("div", "fixture-row"); row.append(element("span", "", fixture[side] || fixture[`${side}_name`]), element("strong", "", number(fixture[`${side}_score`]))); card.append(row); } return card; }); $("fixtures").replaceChildren(...cards); if (!cards.length) empty($("fixtures"), "No fixtures loaded", "They will appear after a successful provider sync."); }
function renderHealth(health) {
  state.health = health;
  const running = health.last_sync?.state === "running";
  const coverage = Array.isArray(health.coverage) ? health.coverage : [];
  $("source-badge").textContent = health.synthetic ? "Demo dataset" : "football-data.org";
  $("catalogue-count").textContent = `${number(health.players)} players · ${number(health.teams)} teams`;
  const seasons = [...new Set(coverage.map((league) => league.season))]; $("season-label").textContent = `${health.synthetic ? "Demo " : "Season "}${seasons.join(", ")}`;
  $("data-notice-text").textContent = health.synthetic ? "You're viewing a 60-player historical demo. Connect live data for current squads and stats across all five leagues." : running ? "Updating the catalogue. Imported players remain available while synchronization runs." : health.stats_stale ? "Some statistics are older than the refresh window. Review coverage and refresh your data." : coverage.some((league) => league.state !== "ready") ? "League coverage is incomplete. Check the data panel for quota, access or synchronization details." : "Current-season catalogue loaded. See Data & connection for coverage and refresh times.";
  $("notice-action").textContent = health.synthetic ? "Connect live data" : "View coverage";
  $("provider-name").textContent = $("source-badge").textContent;
  $("last-sync").textContent = health.last_sync ? `${health.last_sync.state} · ${dateTime(health.last_sync.finished_at || health.last_sync.started_at)}` : "Not synchronized";
  $("index-status").textContent = `${health.indexed} of ${health.players} profiles${health.search_ready ? " · ready" : " · preparing"}`;
  $("stats-date").textContent = dateTime(health.oldest_stats_at);
  $("data-description").textContent = health.data_message;
  $("sync-button").disabled = running || health.offline; $("sync-button").textContent = running ? "Syncing" : "Refresh data";
  $("connect-button").disabled = running;
  const report = health.last_sync?.report; const failures = (report?.resources || []).filter((item) => item.state === "failed");
  feedback("sync-feedback", running ? `Synchronization is ${report?.stage || "running"}. Full league imports can take several minutes.` : report?.error?.message || report?.index_error?.message || failures.map((item) => `${item.resource}: ${item.message || item.code}`).join(" "), Boolean(report?.error || failures.length || report?.index_error));
  $("coverage-table").replaceChildren(...coverage.map((league) => { const row = element("tr"); row.title = league.message; for (const value of [league.name, league.season, `${league.squads_loaded}/${league.expected_teams || "—"}`, number(league.players), number(league.players_with_stats), league.state]) row.append(element("td", "", value)); return row; }));
  if (health.synthetic && !keyPromptDismissed && !$("key-prompt-dialog").open) $("key-prompt-dialog").showModal();
}
async function refresh() {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    const health = await api("/health"); renderHealth(health);
    const signature = `${health.provider}:${health.players}:${health.indexed}:${health.last_sync?.run_id}:${health.last_sync?.state}`;
    if (signature !== state.signature) { await refreshOptions(); await loadPlayers(); await loadFixtures(); state.signature = signature; }
  } catch (error) { feedback("sync-feedback", error.message, true); $("data-notice-text").textContent = "Could not reach the local service. Check that python app.py is running."; }
  finally { state.refreshing = false; }
}
$("sync-button").addEventListener("click", async () => { $("sync-button").disabled = true; try { await api("/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_squads: true }) }); await refresh(); } catch (error) { feedback("sync-feedback", error.message, true); $("sync-button").disabled = false; } });
function connectFeedbackText(result) { return result.key_storage === "remembered_in_local_env_file" ? "Connected. The import is running. The key was saved to this project's local .env file so it reconnects automatically next time." : "Connected. The import is running. The API key is held only for this server session."; }
$("provider").addEventListener("change", () => { const demo = $("provider").value === "demo"; $("key-label").classList.toggle("hidden", demo); $("remember-key").closest("label").classList.toggle("hidden", demo); $("api-key").required = !demo; $("api-key").value = ""; });
$("connect-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("connect-button").disabled = true; feedback("connect-feedback", "Validating the connection and starting the import.");
  let secret = $("api-key").value.trim(); const remember = $("remember-key").checked; $("api-key").value = "";
  try {
    const result = await api("/data/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: $("provider").value, api_key: secret, remember }) });
    secret = ""; state.signature = ""; state.offset = 0; $("query").value = ""; $("team-filter").value = ""; $("twins").replaceChildren(); $("team-results").replaceChildren();
    feedback("connect-feedback", connectFeedbackText(result)); await refresh();
  } catch (error) { feedback("connect-feedback", error.message, true); $("connect-button").disabled = false; }
  finally { secret = ""; }
});

// On first load, if there's no live connection yet, ask for a football-data.org key
// right away instead of making the person find the Data & connection tab themselves.
let keyPromptDismissed = false;
try { keyPromptDismissed = sessionStorage.getItem("matchday-key-prompt-dismissed") === "1"; } catch { keyPromptDismissed = false; }
function dismissKeyPrompt() { keyPromptDismissed = true; try { sessionStorage.setItem("matchday-key-prompt-dismissed", "1"); } catch { /* Best-effort in private browsing. */ } $("key-prompt-dialog").close(); }
$("key-prompt-dismiss").addEventListener("click", dismissKeyPrompt);
$("key-prompt-skip").addEventListener("click", dismissKeyPrompt);
$("key-prompt-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("key-prompt-connect").disabled = true; feedback("key-prompt-feedback", "Validating the connection and starting the import.");
  let secret = $("key-prompt-key").value.trim(); const remember = $("key-prompt-remember").checked; $("key-prompt-key").value = "";
  try {
    const result = await api("/data/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: "football-data", api_key: secret, remember }) });
    secret = ""; state.signature = ""; dismissKeyPrompt(); await refresh();
  } catch (error) { feedback("key-prompt-feedback", error.message, true); $("key-prompt-connect").disabled = false; }
  finally { secret = ""; }
});
window.addEventListener("pagehide", () => { $("api-key").value = ""; $("key-prompt-key").value = ""; for (const controller of state.controllers.values()) controller.abort(); });
restoreFromURL();
void refresh();
setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
