"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { query: "", offset: 0, total: 0, searchController: null, twinController: null, health: null, revision: "", players: [], dialogPlayer: null };
  const number = (value, digits = 2) => value == null ? "—" : Number(value).toFixed(digits);
  const roleNames = { GK: "Goalkeeper", CB: "Centre-back", LB: "Left-back", RB: "Right-back", DM: "Defensive midfield", CM: "Central midfield", AM: "Attacking midfield", LW: "Left winger", RW: "Right winger", ST: "Striker", DEF: "Defender", MID: "Midfielder", FWD: "Forward", UNKNOWN: "Unspecified" };
  const leagueNames = { PL: "Premier League", PD: "La Liga", BL1: "Bundesliga", FL1: "Ligue 1", SA: "Serie A", PPL: "Primeira Liga" };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { cache: "no-store", ...options });
    let body;
    try { body = await response.json(); }
    catch { throw new Error("The server returned an unreadable response. Check the local server and try again."); }
    if (!response.ok) {
      const error = new Error(body.error?.message || `Request failed (${response.status}).`);
      error.code = body.error?.code;
      throw error;
    }
    return body;
  }

  function filters() {
    const parameters = new URLSearchParams();
    for (const [id, name] of [["position", "position"], ["max-age", "max_age"], ["nationality", "nationality"], ["league", "league"]]) {
      if ($(id).value) parameters.set(name, $(id).value);
    }
    return parameters;
  }

  function feedback(id, message) {
    $(id).textContent = message;
    $(id).classList.toggle("hidden", !message);
  }

  function avatar(player) {
    const initials = player.name.split(/\s+/u).map((part) => Array.from(part)[0]).slice(0, 2).join("");
    const role = player.position === "GK" ? "goalkeeper" : ["CB", "LB", "RB", "DEF"].includes(player.position) ? "defender" : ["LW", "RW", "ST", "FWD"].includes(player.position) ? "forward" : "midfielder";
    return element("span", `avatar role-${role}`, initials);
  }

  function metric(label, value, className = "") {
    const node = element("div", className);
    node.append(element("strong", "", value), element("span", "", label));
    return node;
  }

  function showDetails(player) {
    state.dialogPlayer = player;
    const content = $("dialog-content");
    content.replaceChildren();
    const title = element("h2", "dossier-title", player.name);
    title.id = "dialog-title";
    content.append(title, element("p", "dossier-meta", `${roleNames[player.position] || player.position} · ${player.team_name || "Unattached"} · ${player.age == null ? "Age unknown" : `${player.age} years`}`));
    content.append(element("p", "dossier-bio", player.tactical_summary));
    const metrics = element("div", "dossier-stats");
    for (const [key, label] of [["goals", "Goals / 90"], ["assists", "Assists / 90"], ["xG", "xG / 90"], ["xA", "xA / 90"], ["progressive_passes", "Progressive passes / 90"], ["progressive_carries", "Progressive carries / 90"], ["tackles_won", "Tackles won / 90"]]) {
      metrics.append(metric(label, number(player.per90[key]), "dossier-stat"));
    }
    metrics.append(metric("Pass accuracy", player.pass_accuracy == null ? "—" : `${number(player.pass_accuracy, 1)}%`, "dossier-stat"));
    metrics.append(metric("Minutes played", player.minutes_played == null ? "—" : player.minutes_played.toLocaleString(), "dossier-stat"));
    content.append(metrics);
    const sourceText = player.synthetic ? "Synthetic demonstration. Performance figures and tactical descriptions are simulated; they are not verified player statistics." : "Provider profile. Unknown metrics remain unavailable; no synthetic values are added.";
    content.append(element("p", "dossier-provenance", `${sourceText} Season: ${player.season}. Nationality: ${player.nationality || "unknown"}. ${player.similarity_percentage == null ? "" : `Similarity: ${number(player.similarity_percentage, 1)}%.`}`));
    if (!$("player-dialog").open) $("player-dialog").showModal();
  }

  function card(player) {
    const article = element("article", "player-card");
    const top = element("div", "card-top");
    const identity = element("div", "card-identity");
    identity.append(element("h4", "", player.name), element("p", "", player.team_name || "Unattached"));
    const details = element("button", "card-arrow", "↗");
    details.type = "button";
    details.setAttribute("aria-label", `Open ${player.name}'s scout card`);
    details.addEventListener("click", () => showDetails(player));
    top.append(avatar(player), identity, details);
    const tags = element("div", "card-tags");
    tags.append(element("span", "position-tag", player.position), element("span", "country", `${player.nationality || "Unknown"} · ${player.age == null ? "Age unknown" : `${player.age} yrs`}`));
    if (player.synthetic) tags.append(element("span", "synthetic-mini", "Demo"));
    const metrics = element("div", "metric-row");
    metrics.append(metric("xG / 90", number(player.per90.xG)), metric("xA / 90", number(player.per90.xA)), metric("Prog. passes / 90", number(player.per90.progressive_passes, 1)));
    const bottom = element("div", "card-bottom");
    bottom.append(element("span", "match-score", player.similarity_percentage == null ? "PLAYER PROFILE" : `${number(player.similarity_percentage, 1)}% SIMILARITY`));
    const compare = element("button", "card-button", "Find twins ↗");
    compare.type = "button";
    compare.setAttribute("aria-label", `Find player twins for ${player.name}`);
    compare.addEventListener("click", () => chooseTwin(player));
    bottom.append(compare);
    article.append(top, tags, element("p", "card-bio", player.tactical_summary), metrics, bottom);
    return article;
  }

  async function loadResults(resetPage = true) {
    if (resetPage) state.offset = 0;
    state.query = $("query").value.trim();
    state.searchController?.abort();
    const controller = new AbortController();
    state.searchController = controller;
    feedback("search-feedback", "");
    $("results").setAttribute("aria-busy", "true");
    $("search-button").disabled = true;
    try {
      if (state.query && state.query.length < 3) throw new Error("Use at least three characters to describe a playing style.");
      const params = filters();
      const searching = Boolean(state.query);
      if (searching) { params.set("q", state.query); params.set("top_k", "12"); }
      else { params.set("limit", "12"); params.set("offset", String(state.offset)); }
      const result = await api(`${searching ? "/search" : "/players"}?${params}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      $("results").replaceChildren(...result.items.map(card));
      if (!result.items.length) $("results").append(element("div", "empty-state", "No players match these filters. Broaden your search or synchronize a player dataset."));
      $("results-title").textContent = searching ? "Your tactical matches" : "Player collection";
      state.total = searching ? result.items.length : result.total;
      $("results-meta").textContent = searching ? `${result.items.length} results · ${result.eligible_count} indexed candidates · ${number(result.elapsed_ms, 0)} ms` : `${result.total} players in scope · Open a card to explore the full profile`;
      if (result.unindexed_count) feedback("search-feedback", `${result.unindexed_count} matching profiles are awaiting indexing and are excluded from this ranking.`);
      $("pagination").classList.toggle("hidden", searching || state.total <= 12);
      $("previous-page").disabled = state.offset === 0;
      $("next-page").disabled = state.offset + 12 >= state.total;
      $("page-label").textContent = `${state.offset + 1}–${Math.min(state.offset + 12, state.total)} of ${state.total}`;
    } catch (error) {
      if (error.name !== "AbortError") {
        $("results").replaceChildren();
        $("results-title").textContent = "Search unavailable";
        $("results-meta").textContent = "Your filters have been kept";
        $("pagination").classList.add("hidden");
        feedback("search-feedback", error.message);
      }
    } finally {
      if (state.searchController === controller) {
        $("results").setAttribute("aria-busy", "false");
        $("search-button").disabled = false;
      }
    }
  }

  function chooseTwin(player) {
    $("twin-player").value = String(player.player_id);
    if (!$("twin-player").value) return;
    loadTwins();
    if (window.innerWidth < 790) $("twin-heading").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  async function loadTwins() {
    state.twinController?.abort();
    const controller = new AbortController();
    state.twinController = controller;
    $("twins").replaceChildren();
    const selected = state.players.find((p) => String(p.player_id) === $("twin-player").value);
    if (!selected) { $("twin-feedback").textContent = "Select a player to explore their closest stylistic matches."; return; }
    $("twin-feedback").textContent = `Finding matches for ${selected.name}`;
    $("twins").setAttribute("aria-busy", "true");
    const hybrid = $("hybrid-ranking").checked;
    $("score-explainer").textContent = hybrid ? "Hybrid scores combine 75% normalized semantic similarity and 25% statistical similarity. Players need at least four comparable metrics. This is not a quality rating." : "Bars show cosine similarity × 100, with negative values shown as 0%. Similarity is not a player quality rating.";
    try {
      const params = new URLSearchParams({ player_id: String(selected.player_id), top_k: "5", ranking: hybrid ? "hybrid" : "semantic", cross_role: String($("cross-role").checked) });
      const result = await api(`/similar/${encodeURIComponent(selected.name)}?${params}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      $("twin-feedback").textContent = result.items.length ? `${result.items.length} ${hybrid ? "hybrid" : "stylistic"} matches for ${selected.name}` : "No indexed players meet these comparison criteria.";
      if (result.insufficient_stats_count) $("twin-feedback").textContent += ` · ${result.insufficient_stats_count} excluded for missing statistics`;
      for (const player of result.items) {
        const item = element("div", "twin-item");
        const top = element("div", "twin-top");
        const name = element("button", "twin-name", player.name);
        name.type = "button";
        name.addEventListener("click", () => showDetails(player));
        top.append(name, element("span", "twin-number", `${number(player.similarity_percentage, 1)}%`));
        const meter = element("meter", "similarity-meter");
        meter.min = 0; meter.max = 100; meter.value = player.similarity_percentage;
        meter.setAttribute("aria-label", `${player.name}: ${number(player.similarity_percentage, 1)} percent similarity`);
        item.append(top, element("p", "twin-team", `${player.team_name || "Unattached"} · ${player.position}`), meter);
        $("twins").append(item);
      }
    } catch (error) {
      if (error.name !== "AbortError") $("twin-feedback").textContent = error.message;
    } finally {
      if (state.twinController === controller) $("twins").setAttribute("aria-busy", "false");
    }
  }

  function fillSelect(id, options, label) {
    const select = $(id);
    const value = select.value;
    select.replaceChildren(new Option(label, ""));
    for (const [key, name] of options) select.add(new Option(name, key));
    select.value = value;
    if (select.selectedIndex < 0) select.selectedIndex = 0;
  }

  async function loadOptions() {
    const options = await api("/options");
    state.players = options.players;
    fillSelect("twin-player", options.players.map((p) => [String(p.player_id), `${p.name} · ${p.team_name || p.position}`]), "Choose a player");
    fillSelect("position", options.positions.map((p) => [p, `${p} · ${roleNames[p] || p}`]), "All positions");
    fillSelect("nationality", options.nationalities.map((n) => [n, n]), "All nations");
    fillSelect("league", options.leagues.map((l) => [l, leagueNames[l] || l]), "All leagues");
  }

  async function loadFixtures() {
    const data = await api("/fixtures");
    $("fixtures").replaceChildren();
    $("fixture-source").textContent = data.synthetic ? "Synthetic match snapshots · May 2025" : "Latest available provider snapshots";
    for (const fixture of data.items.slice(0, 3)) {
      const item = element("article", "fixture");
      const meta = element("div", "fixture-meta");
      meta.append(element("span", "", new Date(fixture.kickoff).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })), element("span", "", fixture.status.replaceAll("_", " ")));
      const teams = element("div", "fixture-teams");
      teams.append(element("span", "", fixture.home || fixture.home_name), element("strong", "fixture-score", `${fixture.home_score ?? "—"} : ${fixture.away_score ?? "—"}`), element("span", "", fixture.away || fixture.away_name));
      item.append(meta, teams);
      $("fixtures").append(item);
    }
    if (!data.items.length) $("fixtures").append(element("p", "subtle", "No fixtures in the selected synchronization window."));
  }

  async function refreshHealth() {
    try {
      const health = await api("/health");
      const changed = `${health.players}:${health.indexed}:${health.last_sync?.run_id}:${health.last_sync?.state}`;
      $("player-count").textContent = health.players.toLocaleString();
      $("team-count").textContent = health.teams.toLocaleString();
      $("index-count").textContent = health.indexed.toLocaleString();
      $("season-label").textContent = `Scouting season ${health.season}`;
      $("source-badge").textContent = health.synthetic ? "Synthetic demo data" : "Provider data";
      $("source-badge").className = `badge ${health.synthetic ? "badge-demo" : "badge-api"}`;
      $("source-text").textContent = health.synthetic ? "Local demonstration" : "football-data.org";
      $("provenance-text").textContent = health.synthetic ? `Real player names. Simulated statistics and bios. Club snapshot: ${health.reference_date || "2025-06-01"}. This is a demonstration, not verified scouting evidence.` : "Provider coverage depends on your account. Free scores may be delayed. Advanced player metrics remain unavailable unless supplied by a supported source.";
      const running = health.last_sync?.state === "running";
      $("engine-state").textContent = health.search_ready ? "Ready to scout" : running ? "Preparing" : "Needs indexing";
      $("engine-detail").textContent = health.search_ready ? "Local CPU · Semantic search" : running ? `${health.last_sync.report.stage === "indexing" ? "Loading model and indexing profiles" : "Synchronizing player data"}` : "Use Sync data to prepare search";
      $("sync-button").disabled = running;
      $("sync-button").textContent = running ? "Sync in progress" : "↻ Sync data";
      $("last-sync").textContent = health.last_sync?.finished_at ? new Date(health.last_sync.finished_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : running ? "In progress" : "Not yet synchronized";
      const report = health.last_sync?.report;
      $("sync-feedback").textContent = report?.index_error?.message || report?.error?.message || (health.last_sync?.state === "partial" ? "Some provider resources were unavailable. See the sync report for coverage." : running ? "Your data stays local. The first model download can take a few minutes." : "");
      if (state.revision !== changed) {
        await loadOptions();
        await Promise.all([loadResults(false), loadFixtures()]);
        if ($("twin-player").value && health.search_ready) await loadTwins();
        state.revision = changed;
      }
      state.health = health;
    } catch (error) {
      $("engine-state").textContent = "Disconnected";
      $("engine-detail").textContent = "Check the local Python server";
      $("sync-feedback").textContent = error.message;
      $("sync-button").disabled = false;
    }
  }

  async function pollHealth() {
    if (!document.hidden) await refreshHealth();
    window.setTimeout(pollHealth, state.health?.last_sync?.state === "running" ? 3000 : 15000);
  }

  $("search-form").addEventListener("submit", (event) => { event.preventDefault(); loadResults(); });
  for (const chip of document.querySelectorAll(".chip")) {
    chip.setAttribute("aria-pressed", "false");
    chip.addEventListener("click", () => {
      $("query").value = chip.dataset.query;
      for (const other of document.querySelectorAll(".chip")) other.setAttribute("aria-pressed", String(other === chip));
      loadResults();
    });
  }
  $("query").addEventListener("input", () => {
    for (const chip of document.querySelectorAll(".chip")) chip.setAttribute("aria-pressed", String(chip.dataset.query === $("query").value));
  });
  for (const id of ["position", "max-age", "nationality", "league"]) $(id).addEventListener("change", () => {
    if ($("search-form").reportValidity()) loadResults();
  });
  $("clear-filters").addEventListener("click", () => {
    $("search-form").reset();
    for (const chip of document.querySelectorAll(".chip")) chip.setAttribute("aria-pressed", "false");
    loadResults();
  });
  $("previous-page").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 12); loadResults(false); });
  $("next-page").addEventListener("click", () => { state.offset += 12; loadResults(false); });
  for (const id of ["twin-player", "cross-role", "hybrid-ranking"]) $(id).addEventListener("change", loadTwins);
  $("close-dialog").addEventListener("click", () => $("player-dialog").close());
  $("player-dialog").addEventListener("click", (event) => {
    if (event.target === $("player-dialog")) {
      const box = $("player-dialog").getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) $("player-dialog").close();
    }
  });
  $("dialog-compare").addEventListener("click", () => {
    $("player-dialog").close();
    if (state.dialogPlayer) chooseTwin(state.dialogPlayer);
  });
  $("sync-button").addEventListener("click", async () => {
    $("sync-button").disabled = true;
    $("sync-feedback").textContent = "Starting synchronization";
    try {
      await api("/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      await refreshHealth();
    } catch (error) {
      $("sync-feedback").textContent = error.message;
      $("sync-button").disabled = false;
    }
  });
  pollHealth();
})();
