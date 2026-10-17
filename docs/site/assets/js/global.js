/* The Quant Footballer — the layer above the competitions.
 *
 *   #/clubs                 every club on the pooled scale, a hypothetical-match pricer
 *   #/leaders               global leaderboards, raw and league-adjusted
 *   #/compare/...           two players or two clubs side by side
 *   (#/player/<pid> and #/club/<tid>, one page per person and per club, live in people.js)
 *
 * All of it reads the site-wide payloads (pool.json, players_global.json,
 * nations.json, season_index.json) and never needs a competition to be open. The Dixon-Coles pricing of a hypothetical match is computed here
 * from the pooled parameters, so any two clubs across leagues can be priced. */
(function (FH) {
'use strict';

const { INDEX, C, PALETTE, esc, pct, num, signed, fmtMetric, fmtDate, fmtStamp, crest, playerLink, matchHref,
        tableHTML, setHTML, sortableIn, wireRowLinks, statTile, formChips, pctPill, pctRow, pctColor, probBar,
        plot, layout, renderRadar, renderProbBars, loadSite, RADAR_OUT, RADAR_GK } = FH;

// ── Dixon-Coles in the browser ─────────────────────────────────────────────

function poissonPmf(k, lam) {
  let p = Math.exp(-lam);
  for (let i = 1; i <= k; i++) p *= lam / i;
  return p;
}

/* The pooled model's score matrix for home v away; `homeAdv` 0 for a neutral venue. */
function dcMatrix(home, away, model, homeAdv) {
  const lamH = Math.exp(home.attack + away.defence + (homeAdv || 0));
  const lamA = Math.exp(away.attack + home.defence);
  const k = (model.max_goals || 8) + 1;
  const rho = model.rho || 0;
  const m = [];
  let total = 0;
  for (let i = 0; i < k; i++) {
    m.push([]);
    for (let j = 0; j < k; j++) {
      let p = poissonPmf(i, lamH) * poissonPmf(j, lamA);
      if (i === 0 && j === 0) p *= 1 - lamH * lamA * rho;
      else if (i === 1 && j === 0) p *= 1 + lamA * rho;
      else if (i === 0 && j === 1) p *= 1 + lamH * rho;
      else if (i === 1 && j === 1) p *= 1 - rho;
      p = Math.max(p, 0);
      m[i].push(p);
      total += p;
    }
  }
  let h = 0, d = 0, a = 0, o25 = 0, btts = 0, best = [0, 0, -1];
  for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) {
    const p = m[i][j] / total;
    if (i > j) h += p; else if (i === j) d += p; else a += p;
    if (i + j >= 3) o25 += p;
    if (i >= 1 && j >= 1) btts += p;
    if (p > best[2]) best = [i, j, p];
  }
  return { h, d, a, lamH, lamA, o25, btts, score: best[0] + '-' + best[1], pScore: best[2] };
}

function fairOdds(p) { return p > 0.005 ? (1 / p).toFixed(2) : '—'; }

function matchCard(home, away, model, neutral) {
  const r = dcMatrix(home, away, model, neutral ? 0 : model.home_adv);
  return '<div class="hypo">' + probBar({ h: r.h, d: r.d, a: r.a }) +
    '<div class="kpi-grid six">' +
    statTile(esc(home.team), pct(r.h), 'fair ' + fairOdds(r.h)) + statTile('Draw', pct(r.d), 'fair ' + fairOdds(r.d)) +
    statTile(esc(away.team), pct(r.a), 'fair ' + fairOdds(r.a)) +
    statTile('Expected goals', num(r.lamH, 2) + ' – ' + num(r.lamA, 2), 'most likely ' + r.score + ' (' + pct(r.pScore) + ')') +
    statTile('Over 2.5', pct(r.o25), 'under ' + pct(1 - r.o25)) + statTile('Both score', pct(r.btts), '') +
    '</div></div>';
}

// ── clubs across leagues ───────────────────────────────────────────────────

let POOL = null;

function clubLabel(c) { return c.team + ' (' + (c.comp_name || c.comp) + ')'; }

function renderClubs() {
  loadSite('pool.json').then(pool => {
    POOL = pool;
    if (!pool || !(pool.clubs || []).length) { setHTML('clubs-table', '<div class="muted">' + esc((pool || {}).note || 'No pooled model this run.') + '</div>'); return; }
    const leagues = pool.leagues || {};
    const lrows = Object.keys(leagues).map(s => ({ slug: s, ...leagues[s] })).sort((a, b) => a.rank - b.rank);
    setHTML('leagues-table', tableHTML([
      { label: '#', sortable: false }, { label: 'League' }, { label: 'Clubs', align: 'right' }, { label: 'Strength', align: 'right', title: 'Mean expected points per game of its clubs against the pool-average club, neutral venue' },
      { label: 'Attack', align: 'right' }, { label: 'Defence', align: 'right', title: 'Lower is better (fewer goals conceded)' },
      { label: 'Scoring factor', align: 'right', title: "Multiplier applied to a player's attacking rates from this league: how much harder it is to score here than against the pool average" },
      { label: 'Best club', sortable: false }, { label: 'Bridge', align: 'right', title: 'Cup matches connecting this league to the pool; fewer means a less certain scale' }
    ], lrows.map(L => ({ cells: [
      { v: L.rank, cls: 'pos-cell' }, { v: L.name, html: '<a href="#/' + esc(L.slug) + '/overview">' + esc(L.name) + '</a>' }, { v: L.n_clubs, align: 'right' },
      { v: L.strength, html: '<strong>' + num(L.strength, 3) + '</strong>', align: 'right' },
      { v: L.attack, html: signed(L.attack, 3), align: 'right' }, { v: L.defence, html: signed(L.defence, 3), align: 'right' },
      { v: L.factor_att, html: num(L.factor_att, 3), align: 'right' },
      { v: L.best, html: esc(L.best) + ' <span class="muted-inline">#' + L.best_rank + '</span>' },
      { v: L.connection, html: L.connection + (L.connection < 20 ? ' <span class="chip warn">weak</span>' : ''), align: 'right' }
    ] }))));
    sortableIn('leagues-table');
    const bridges = pool.bridges || {};
    const bkeys = Object.keys(bridges).sort((x, y) => bridges[y] - bridges[x]);
    setHTML('bridges-note', '<p><strong>Between continents</strong> the fit has only these matches to go on — ' +
      (bkeys.length ? bkeys.map(k => esc(k.replace('|', ' – ')) + ': ' + bridges[k]).join(' · ') : 'none') +
      '. Within a block (Europe through the UEFA cups, South America through CONMEBOL\'s, North America through CONCACAF\'s, Asia through the AFC\'s) the scale is well identified; a club\'s rank against clubs of another block is not, and the Club World Cup and Intercontinental Cup are the only bridges. Compare within a block with confidence; across blocks, read the numbers as the model\'s best guess with wide error.</p>');

    const sel = document.getElementById('clubs-league');
    sel.innerHTML = '<option value="">All competitions</option>' + INDEX.competitions.filter(c => pool.clubs.some(x => x.comp === c.slug))
      .map(c => '<option value="' + esc(c.slug) + '">' + esc(c.name) + '</option>').join('');
    const search = document.getElementById('clubs-search');
    function draw() {
      const q = search.value.trim().toLowerCase(), lg = sel.value;
      const rows = pool.clubs.filter(c => (!lg || c.comp === lg) && (!q || c.team.toLowerCase().indexOf(q) >= 0)).slice(0, lg || q ? 400 : 150);
      setHTML('clubs-table', tableHTML([
        { label: '#', sortable: false }, { label: 'Club' }, { label: 'Competition' }, { label: 'Block', sortable: true }, { label: 'Strength', align: 'right', title: 'Expected points per game against the pool-average club at a neutral venue' },
        { label: 'xG for', align: 'right', title: 'Expected goals against the pool-average defence' }, { label: 'xG against', align: 'right' },
        { label: 'Attack', align: 'right' }, { label: 'Defence', align: 'right' }, { label: 'Elo', align: 'right' }, { label: 'Pos', align: 'right' }, { label: 'Form', align: 'right' }, { label: 'Luck', align: 'right' }
      ], rows.map(c => ({ _href: c.in_league ? '#/' + c.comp + '/team/' + (c.slug || FH.slugify(c.team)) : null, cells: [
        { v: c.rank, cls: 'pos-cell' },
        { v: c.team, html: crest(c.team, c.crest) + esc(c.team) }, { v: c.comp_name, html: esc(c.comp_name) },
        { v: c.block || '', html: '<span class="chip">' + esc(c.block || '') + '</span>' },
        { v: c.strength, html: '<strong>' + num(c.strength, 3) + '</strong>', align: 'right' },
        { v: c.xg_for, html: num(c.xg_for, 2), align: 'right' }, { v: c.xg_against, html: num(c.xg_against, 2), align: 'right' },
        { v: c.attack, html: signed(c.attack, 2), align: 'right' }, { v: c.defence, html: signed(c.defence, 2), align: 'right' },
        { v: c.elo || 0, html: c.elo ? num(c.elo, 0) : '—', align: 'right' }, { v: c.table_rank || 0, html: c.table_rank || '—', align: 'right' },
        { v: c.ppg || 0, html: c.form_results ? formChips(c.form_results) : '—', align: 'right' },
        { v: c.luck === null || c.luck === undefined ? 0 : c.luck, html: c.luck === null || c.luck === undefined ? '—' : signed(c.luck, 1), align: 'right' }
      ] })), { sticky: true }));
      wireRowLinks('clubs-table');
      sortableIn('clubs-table');
    }
    sel.onchange = draw; search.oninput = draw;
    draw();
    setHTML('clubs-sub', pool.clubs.length + ' clubs on one scale · rho ' + num(pool.model.rho, 3) + ' · home advantage ' + num(pool.model.home_adv, 3));

    // The pricer.
    const opts = pool.clubs.map((c, i) => '<option value="' + i + '">' + esc(clubLabel(c)) + '</option>').join('');
    const a = document.getElementById('hypo-a'), b = document.getElementById('hypo-b'), venue = document.getElementById('hypo-venue');
    a.innerHTML = opts; b.innerHTML = opts; b.selectedIndex = Math.min(1, pool.clubs.length - 1);
    function price() {
      const home = pool.clubs[parseInt(a.value, 10)], away = pool.clubs[parseInt(b.value, 10)];
      if (!home || !away) return;
      setHTML('hypo-result', matchCard(home, away, pool.model, venue.value === 'neutral'));
    }
    a.onchange = price; b.onchange = price; venue.onchange = price;
    price();
    const top = pool.clubs.slice(0, 25).reverse();
    plot('clubs-chart', [{ type: 'bar', orientation: 'h', y: top.map(c => c.team + ' · ' + c.comp_name), x: top.map(c => c.strength), marker: { color: C.blue },
      text: top.map(c => num(c.strength, 2)), textposition: 'outside', cliponaxis: false, hovertemplate: '%{y}: %{x:.3f} PPG v average<extra></extra>' }],
      layout({ margin: { l: 240, r: 50, t: 10, b: 40 }, xaxis: { title: 'Expected points per game against the pool-average club', range: [1.5, 3] }, yaxis: { automargin: true } }));
  });
}

// ── national teams ─────────────────────────────────────────────────────────

function renderNations() {
  Promise.all([loadSite('nations.json'), loadSite('hub.json')]).then(([n, hub]) => {
    const teams = (n || {}).teams || [];
    if (!teams.length) { setHTML('nations-table', '<div class="muted">' + esc((n || {}).note || 'No international fit yet — the national-team stores fill on the next fetch.') + '</div>'); setHTML('nations-fixtures', ''); setHTML('nations-chart', ''); return; }
    setHTML('nations-sub', teams.length + ' teams · rho ' + num(n.model.rho, 3) + ' · home advantage ' + num(n.model.home_adv, 3));
    setHTML('nations-note', '<p>' + esc(n.note || '') + '</p>');
    const confs = Array.from(new Set(teams.map(t => t.confederation).filter(Boolean))).sort();
    const sel = document.getElementById('nations-conf'), search = document.getElementById('nations-search');
    sel.innerHTML = '<option value="">All confederations</option>' + confs.map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join('');
    function draw() {
      const q = search.value.trim().toLowerCase(), conf = sel.value;
      const rows = teams.filter(t => (!conf || t.confederation === conf) && (!q || t.team.toLowerCase().indexOf(q) >= 0)).slice(0, 150);
      setHTML('nations-table', tableHTML([
        { label: '#', sortable: false }, { label: 'Team' }, { label: 'Confederation' }, { label: 'Played', align: 'right', title: 'Matches in the stores' },
        { label: 'Strength', align: 'right', title: 'Expected points per game against the average national team, neutral venue' },
        { label: 'Attack', align: 'right' }, { label: 'Defence', align: 'right' }, { label: 'Elo', align: 'right' }
      ], rows.map(t => ({ cells: [
        { v: t.rank, cls: 'pos-cell' }, { v: t.team, html: esc(t.team) }, { v: t.confederation || '', html: esc(t.confederation || '—') },
        { v: t.played, align: 'right' }, { v: t.strength, html: '<strong>' + num(t.strength, 3) + '</strong>', align: 'right' },
        { v: t.attack, html: signed(t.attack, 2), align: 'right' }, { v: t.defence, html: signed(t.defence, 2), align: 'right' },
        { v: t.elo || 0, html: t.elo ? num(t.elo, 0) : '—', align: 'right' }
      ] })), { sticky: true }));
      sortableIn('nations-table');
    }
    sel.onchange = draw; search.oninput = draw;
    draw();
    const opts = teams.map((t, i) => '<option value="' + i + '">' + esc(t.team) + '</option>').join('');
    const a = document.getElementById('nhypo-a'), b = document.getElementById('nhypo-b'), venue = document.getElementById('nhypo-venue');
    a.innerHTML = opts; b.innerHTML = opts; b.selectedIndex = Math.min(1, teams.length - 1);
    function price() {
      const home = teams[parseInt(a.value, 10)], away = teams[parseInt(b.value, 10)];
      if (!home || !away) return;
      setHTML('nhypo-result', matchCard(home, away, n.model, venue.value === 'neutral'));
    }
    a.onchange = price; b.onchange = price; venue.onchange = price;
    price();
    const upcoming = ((hub || {}).upcoming || []).concat(Object.values((hub || {}).days || {}).flat()).filter(i => i.family === 'international' && i.status !== 'finished')
      .sort((x, y) => String(x.date).localeCompare(String(y.date)));
    const seen = new Set();
    const list = upcoming.filter(i => { const k = i.comp + ':' + i.id; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 30);
    setHTML('nations-fixtures', list.length ? list.map(i => FH.fixtureRow(i, { showDate: true }).replace('class="fx-row', 'title="' + esc(i.comp_name) + '" class="fx-row')).join('') : '<div class="muted">No international fixtures in the stores yet.</div>');
    const top = teams.slice(0, 25).reverse();
    plot('nations-chart', [{ type: 'bar', orientation: 'h', y: top.map(t => t.team), x: top.map(t => t.strength), marker: { color: C.green },
      text: top.map(t => num(t.strength, 2)), textposition: 'outside', cliponaxis: false, hovertemplate: '%{y}: %{x:.3f} PPG v average<extra></extra>' }],
      layout({ margin: { l: 160, r: 50, t: 10, b: 40 }, xaxis: { title: 'Expected points per game against the average national team' }, yaxis: { automargin: true } }));
  });
}

// ── global leaderboards ────────────────────────────────────────────────────

function metricOptionsGlobal(metrics, scope, adjustedKeys) {
  const groups = [];
  metrics.filter(m => scope === 'all' || m.scope === 'all' || m.scope === scope).forEach(m => {
    let g = groups.find(x => x.name === m.group);
    if (!g) { g = { name: m.group, items: [] }; groups.push(g); }
    g.items.push(m);
    if (adjustedKeys.indexOf(m.key) >= 0) g.items.push({ key: m.key + '_adj', label: m.label + ' (league-adjusted)', fmt: m.fmt, pct: true, lower: m.lower });
  });
  return groups.map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + '</option>').join('') + '</optgroup>').join('');
}

function renderLeaders() {
  loadSite('players_global.json').then(g => {
    const all = g.players || [];
    const metrics = g.metrics || [];
    const adjusted = g.adjusted_keys || [];
    if (!all.length) { setHTML('leaders-table', '<div class="muted">No players yet.</div>'); return; }
    // Each row is over its own competition's floor (a share of the minutes its season has offered), so a
    // Brazilian thirty rounds in and a European seven rounds in are each ranked on a like share of their seasons.
    setHTML('leaders-sub', all.length + ' qualified players across ' + Object.keys(g.leagues || {}).length + ' leagues and the cups, this season · ' +
      (g.floor_share ? 'each over ' + Math.round(g.floor_share * 100) + '% of the minutes his competition has played so far' : 'percentiles against the pool\'s position group over ' + g.minutes_floor + ' minutes'));
    setHTML('leaders-note', '<p>' + esc(g.note || '') + '</p>');
    const metricSel = document.getElementById('leaders-metric'), posSel = document.getElementById('leaders-pos'), compSel = document.getElementById('leaders-comp'), minMin = document.getElementById('leaders-min');
    const comps = Array.from(new Set(all.map(p => p.comp)));
    compSel.innerHTML = '<option value="">All competitions</option>' + INDEX.competitions.filter(c => comps.indexOf(c.slug) >= 0).map(c => '<option value="' + esc(c.slug) + '">' + esc(c.name) + '</option>').join('');
    minMin.value = g.minutes_floor || 270;
    function fill() {
      const scope = posSel.value === 'G' ? 'gk' : posSel.value ? 'out' : 'all';
      const keep = metricSel.value;
      metricSel.innerHTML = metricOptionsGlobal(metrics, scope, adjusted);
      metricSel.value = Array.from(metricSel.options).some(o => o.value === keep) ? keep : (scope === 'gk' ? 'saves_90' : 'npxg_90_adj');
    }
    fill();
    function draw() {
      const key = metricSel.value;
      const base = key.replace(/_adj$/, '');
      const metric = metrics.find(m => m.key === base) || { fmt: '2' };
      const floor = parseInt(minMin.value, 10) || 0, comp = compSel.value, pos = posSel.value;
      const rows = all.filter(p => p.minutes >= floor && (!comp || p.comp === comp) && (!pos || (pos === 'G' ? p.is_gk : p.position === pos)) && p[key] !== undefined && p[key] !== null)
        .sort((a, b) => metric.lower ? a[key] - b[key] : b[key] - a[key]).slice(0, 100);
      const pctKey = (p) => (p.pct_global || {})[key] !== undefined ? key : (p.pct_global || {})[base + '_90'] !== undefined ? base + '_90' : null;
      setHTML('leaders-table', rows.length ? tableHTML([
        { label: '#', sortable: false }, { label: 'Player' }, { label: 'Club' }, { label: 'Competition' }, { label: 'Pos', align: 'center' }, { label: 'Age', align: 'right' },
        { label: 'Min', align: 'right' }, { label: (metric.label || key) + (key.endsWith('_adj') ? ' (adj.)' : ''), align: 'right' },
        { label: 'Raw', align: 'right', title: 'Before the league adjustment' }, { label: 'Factor', align: 'right', title: "The league's scoring factor" },
        { label: 'Pctl', align: 'center', title: 'Percentile in the global position pool' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'Rating', align: 'right' }
      ], rows.map((p, i) => { const pk = pctKey(p); return { cells: [
        { v: i + 1, cls: 'pos-cell' }, { v: p.name, html: playerLink(p.player_id, p.name, p.comp) },
        { v: p.team, html: crest(p.team, p.crest) + esc(p.team) }, { v: p.comp_name, html: esc(p.comp_name) + (p.season ? ' <span class="muted-inline">' + esc(String(p.season).replace(/^.*?(\d{2}\/\d{2}|(19|20)\d{2})$/, '$1')) + '</span>' : '') },
        { v: p.position || '', html: p.position ? '<span class="pos-badge pos-' + esc(p.position) + '">' + esc(p.position) + '</span>' : '', align: 'center' },
        { v: p.age || 0, html: p.age || '—', align: 'right' }, { v: p.minutes, align: 'right' },
        { v: p[key], html: '<strong>' + fmtMetric(p[key], metric.fmt) + '</strong>', align: 'right' },
        { v: key.endsWith('_adj') ? p[base] : p[key], html: key.endsWith('_adj') ? fmtMetric(p[base], metric.fmt) : '—', align: 'right' },
        { v: p.adj_factor || 1, html: num(p.adj_factor || 1, 2), align: 'right' },
        { v: pk ? p.pct_global[pk] : -1, html: pctPill(pk ? p.pct_global[pk] : undefined), align: 'center' },
        { v: p.goals || 0, align: 'right' }, { v: p.assists || 0, align: 'right' }, { v: p.rating || 0, html: p.rating ? num(p.rating, 2) : '—', align: 'right' }
      ] }; }), { sticky: true }) : '<div class="muted">No player clears the filters.</div>');
      sortableIn('leaders-table');
    }
    metricSel.onchange = draw; posSel.onchange = () => { fill(); draw(); }; compSel.onchange = draw; minMin.onchange = draw; minMin.oninput = draw;
    draw();
  });
}

// ── compare ────────────────────────────────────────────────────────────────
//
// #/compare/players/<comp>:<id>/<comp>:<id> and #/compare/clubs/<comp>:<slug>/<comp>:<slug>.
// Players read each competition's players_live.json (the full catalogue and the
// competition percentiles), players_global.json (global percentiles, adjusted
// rates), the club shards (match logs, shots) and season_index.json. Clubs read
// each competition's teams, table, strength, probs, team_stats, analytics,
// fixtures and players_live, plus pool.json for the hypothetical match. Every
// section degrades to a muted line when its payload is missing.

let SEARCH_IDX = null;
const CMP_CACHE = {};        // path -> promise of a per-competition payload (or null)
let CMP_TOKEN = 0;           // bumps on every compare render; stale async work checks it

function cmpFetch(path) {
  if (!CMP_CACHE[path]) CMP_CACHE[path] = FH.fetchJSON('data/' + path, null).then(v => { if (v === null) delete CMP_CACHE[path]; return v; });
  return CMP_CACHE[path];
}

function pickerHTML(id, placeholder) {
  return '<div class="picker"><input id="' + id + '" type="search" placeholder="' + esc(placeholder) + '" autocomplete="off"><div id="' + id + '-results" class="search-results"></div></div>';
}

function wirePicker(id, kind, onPick) {
  const input = document.getElementById(id), box = document.getElementById(id + '-results');
  if (!input) return;
  const norm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = norm(input.value.trim());
      if (q.length < 2) { box.style.display = 'none'; return; }
      FH.fetchJSON('data/search.json', { teams: [], players: [] }).then(idx => {
        SEARCH_IDX = idx;
        const compName = slug => ((INDEX.competitions.find(c => c.slug === slug) || {}).short_name) || slug;
        const hits = kind === 'players'
          ? idx.players.filter(p => norm(p.n).indexOf(q) >= 0).slice(0, 10).map(p => ({ key: p.comp + ':' + p.id, label: p.n + (p.pos ? ' (' + p.pos + ')' : ''), sub: p.t + ' · ' + compName(p.comp) + ' · ' + (p.min || 0) + "'" }))
          : idx.teams.filter(t => norm(t.n).indexOf(q) >= 0).slice(0, 10).map(t => ({ key: t.comp + ':' + t.slug, label: t.n, sub: t.comp_name }));
        box.innerHTML = hits.map(h => '<a class="sr-item" href="#" data-key="' + esc(h.key) + '"><span>' + esc(h.label) + '</span><span class="sr-sub">' + esc(h.sub) + '</span></a>').join('') || '<div class="sr-empty">No match.</div>';
        box.style.display = 'block';
        box.querySelectorAll('a').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); box.style.display = 'none'; input.value = ''; onPick(a.dataset.key); }));
      });
    }, 120);
  });
  if (!wirePicker.docListener) {   // once per page load: a click outside any picker closes its suggestions
    document.addEventListener('click', ev => { if (!ev.target.closest('.picker')) document.querySelectorAll('.picker .search-results').forEach(b => { b.style.display = 'none'; }); });
    wirePicker.docListener = true;
  }
}

function renderCompare(param) {
  const parts = (param || '').split('/').filter(Boolean);
  const kind = parts[0] === 'clubs' ? 'clubs' : 'players';
  const a = parts[1] || '', b = parts[2] || '';
  const pane = document.getElementById('tab-compare');
  pane.innerHTML = '<div class="card"><div class="card-header">Compare <span class="card-sub">Two players or two clubs from any competition, side by side: identity, percentiles, form and the model\'s view.</span></div>' +
    '<div class="controls"><label><input type="radio" name="cmp-kind" value="players"' + (kind === 'players' ? ' checked' : '') + '> players</label>' +
    '<label><input type="radio" name="cmp-kind" value="clubs"' + (kind === 'clubs' ? ' checked' : '') + '> clubs</label>' +
    pickerHTML('cmp-pick-a', 'Search the first ' + (kind === 'players' ? 'player' : 'club') + '…') + pickerHTML('cmp-pick-b', 'Search the second…') +
    (a || b ? '<a class="btn-ghost" href="#/compare/' + kind + '/' + esc(b) + (a ? '/' + esc(a) : '') + '" title="Swap the two">⇄ swap</a>' : '') + '</div>' +
    '<div class="pad" id="cmp-picked"></div></div><div id="cmp-body"></div>';
  pane.querySelectorAll('input[name=cmp-kind]').forEach(r => r.addEventListener('change', () => { location.hash = '#/compare/' + r.value; }));
  wirePicker('cmp-pick-a', kind, key => { location.hash = '#/compare/' + kind + '/' + key + (b ? '/' + b : ''); });
  wirePicker('cmp-pick-b', kind, key => { location.hash = '#/compare/' + kind + '/' + (a || '') + '/' + key; });
  CMP_TOKEN++;
  if (!a && !b) {
    setHTML('cmp-picked', '<span class="muted-inline">Type a name in each box, or try an example.</span>');
    setHTML('cmp-body', '<div class="card"><div class="muted">Pick two ' + kind + ' above. Examples: <a href="#/compare/players/premier-league:839956/premier-league:823941">Haaland v Isak</a> · <a href="#/compare/players/mls:12994/saudi-pro-league:750">Messi v Ronaldo</a> · <a href="#/compare/players/premier-league:839956/bundesliga:108579">Haaland v Kane</a> · <a href="#/compare/clubs/premier-league:arsenal/la-liga:barcelona">Arsenal v Barcelona</a> · <a href="#/compare/clubs/premier-league:arsenal/premier-league:liverpool">Arsenal v Liverpool</a></div></div>');
    return;
  }
  if (kind === 'players') comparePlayers(a, b, CMP_TOKEN); else compareClubs(a, b, CMP_TOKEN);
}

function splitKey(key) { const i = key.indexOf(':'); return i < 0 ? [null, key] : [key.slice(0, i), key.slice(i + 1)]; }
function cmpAlive(token) { return token === CMP_TOKEN && FH.STATE.global === 'compare'; }
function compOf(slug) { return INDEX.competitions.find(c => c.slug === slug) || { slug: slug, name: slug, short_name: slug }; }
function mutedLine(text) { return '<div class="muted">' + text + '</div>'; }
function has(v) { return v !== undefined && v !== null && !(typeof v === 'number' && isNaN(v)); }
function divergingBar(gap) {
  // A percentile-point gap: blue to the left when the first side leads, orange to the right when the second does.
  if (!has(gap)) return '<span class="cmp-gap" title="no percentile on one side"></span>';
  const w = Math.min(50, Math.abs(gap) / 2);
  return '<span class="cmp-gap" title="' + signed(gap, 0) + ' percentile points"><span class="' + (gap >= 0 ? 'a' : 'b') + '" style="width:' + w + '%"></span></span>';
}
function posBadge(p) { return p ? '<span class="pos-badge pos-' + esc(p) + '">' + esc(p) + '</span>' : ''; }

/* Expected points from two xG totals as independent Poisson means, truncated at 8 goals. */
function xptsOf(xg, xga) {
  if (!has(xg) || !has(xga)) return null;
  let win = 0, draw = 0, total = 0;
  for (let i = 0; i <= 8; i++) for (let j = 0; j <= 8; j++) {
    const p = poissonPmf(i, xg) * poissonPmf(j, xga);
    total += p;
    if (i > j) win += p; else if (i === j) draw += p;
  }
  return total > 0 ? (3 * win + draw) / total : null;
}

// ── compare: players ───────────────────────────────────────────────────────

const HEADLINE_OUT = ['npxg_90', 'xa_90', 'shots_90', 'key_passes_90', 'dribbles_90', 'prog_carries_90', 'tackles_90', 'interceptions_90'];
const HEADLINE_GK = ['saves_90', 'goals_prevented_90', 'conceded_90', 'sweeper_90', 'high_claims_90', 'passes_90', 'long_balls_90', 'km_90'];

function comparePlayers(ka, kb, token) {
  loadSite('players_global.json').then(g => {
    if (!cmpAlive(token)) return;
    const all = (g || {}).players || [];
    const resolve = key => {
      if (!key) return null;
      const [comp, id] = splitKey(key);
      const grow = all.find(p => String(p.player_id) === String(id) && (!comp || p.comp === comp)) || all.find(p => String(p.player_id) === String(id)) || null;
      return { key: key, id: String(id), comp: comp || (grow ? grow.comp : null), global: grow };
    };
    const ra = resolve(ka), rb = resolve(kb);
    const unresolved = [ra, rb].filter(r => r && !r.comp);
    if (!ra || !rb || unresolved.length) {
      setHTML('cmp-picked', [ra, rb].map(r => r ? (r.comp ? '<span class="chip">' + esc(r.global ? r.global.name : 'player ' + r.id) + ' · ' + esc(compOf(r.comp).short_name || r.comp) + '</span>' : '<span class="chip warn">' + esc(r.id) + ': competition unknown</span>') : '<span class="chip warn">not picked</span>').join(' v '));
      setHTML('cmp-body', '<div class="card">' + mutedLine(unresolved.length ? 'A player picked without a competition prefix must be among the qualified players of the season; use the search boxes, which carry the competition.' : 'Pick both players.') + '</div>');
      return;
    }
    Promise.all([ra, rb].map(r => Promise.all([cmpFetch(r.comp + '/players_live.json'), cmpFetch(r.comp + '/teams.json')]))).then(res => {
      if (!cmpAlive(token)) return;
      const P = [ra, rb].map((r, i) => {
        const live = res[i][0] || {};
        const teams = ((res[i][1] || {}).teams) || {};
        const row = (live.players || []).find(p => String(p.player_id) === r.id) || null;
        const base = row || r.global;
        const tinfo = base ? (teams[base.team] || {}) : {};
        return { id: r.id, comp: compOf(r.comp), live: live, metrics: (live.metrics || []).length ? live.metrics : ((g || {}).metrics || []), row: base, fromLive: !!row, global: r.global, tinfo: tinfo,
                 teamSlug: tinfo.slug || (r.global || {}).team_slug || (base ? FH.slugify(base.team) : ''), crest: tinfo.crest || (r.global || {}).crest || null,
                 posLabel: base ? ((live.positions || (g || {}).positions || {})[base.position] || (base.is_gk ? 'Goalkeeper' : 'Outfield')) : '' };
      });
      setHTML('cmp-picked', P.map((p, i) => p.row ? '<span class="chip"><span class="cmp-pill-' + (i ? 'b' : 'a') + '"></span>' + esc(p.row.name) + ' · ' + esc(p.row.team) + ' · ' + esc(p.comp.short_name || p.comp.name) + '</span>' : '<span class="chip warn">' + esc(p.id) + ' not found in ' + esc(p.comp.name) + '</span>').join(' v '));
      if (!P[0].row || !P[1].row) { setHTML('cmp-body', '<div class="card">' + mutedLine('One of the players is not in that competition\'s player data this season.') + '</div>'); return; }
      buildPlayers(P, g || {}, token);
    });
  });
}

function buildPlayers(P, g, token) {
  const A = P[0], B = P[1];
  const name = p => p.row.name;
  const short = p => p.row.short_name || String(p.row.name).split(' ').slice(-1)[0];
  const gk = !!(A.row.is_gk && B.row.is_gk);
  const mixed = !!A.row.is_gk !== !!B.row.is_gk;
  const scope = gk ? 'gk' : 'out';
  const metricsAll = A.metrics.length >= B.metrics.length ? A.metrics : B.metrics;
  const inScope = m => m.scope === 'all' || (mixed ? true : m.scope === scope);
  const pctComp = p => p.fromLive ? (p.row.pct || {}) : (p.row.pct_comp || {});
  const pctGlobal = p => p.global && p.global.pct_global ? p.global.pct_global : null;
  const floorOf = p => p.live.minutes_floor || g.minutes_floor || 0;

  // (a) identity cards.
  const idCard = (p, side) => {
    const r = p.row;
    const facts = [['Minutes', r.minutes], ['Apps', r.matches + (r.starts !== undefined ? ' <span class="kpi-dim">(' + r.starts + ' st)</span>' : '')],
      ['Rating', has(r.rating) ? num(r.rating, 2) : '—'], ['Goals', has(r.goals) ? r.goals : '—'], ['Assists', has(r.assists) ? r.assists : '—'],
      [r.is_gk ? 'Save %' : 'npxG', r.is_gk ? fmtMetric(r.save_pct, 'pct') : num(r.npxg, 2)], [r.is_gk ? 'Prevented' : 'xA', r.is_gk ? signed(r.goals_prevented, 2) : num(r.xa, 2)]];
    const chips = [posBadge(r.position) + ' ' + esc(p.posLabel)];
    if (r.age) chips.push(r.age + ' years');
    if (r.country) chips.push(esc(r.country));
    if (r.height) chips.push(r.height + ' cm');
    if (r.shirt) chips.push('#' + esc(r.shirt));
    chips.push(r.qualified === false || (!r.pool && !p.global) ? '<span class="chip warn">below ' + floorOf(p) + ' minutes: no percentiles</span>' : '<span class="chip">' + esc(r.pool ? r.pool.label + ' pool · ' + r.pool.n + ' qualified' : 'qualified') + '</span>');
    return '<div class="cmp-id ' + side + '"><span class="ph-initials">' + esc(String(r.name).split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()) + '</span><div class="cmp-id-body">' +
      '<div class="cmp-id-name"><a href="#/' + esc(p.comp.slug) + '/player/' + esc(p.id) + '">' + esc(r.name) + '</a></div>' +
      '<div class="cmp-id-sub"><a class="team-link" href="#/' + esc(p.comp.slug) + '/team/' + esc(p.teamSlug) + '">' + crest(r.team, p.crest) + esc(r.team) + '</a> · <a href="#/' + esc(p.comp.slug) + '/overview">' + esc(p.comp.name) + '</a></div>' +
      '<div class="ph-chips">' + chips.map(c => c.indexOf('<span class="chip') === 0 ? c : '<span class="chip">' + c + '</span>').join('') + '</div>' +
      '<div class="cmp-id-facts">' + facts.map(f => '<div class="cmp-fact"><span>' + f[0] + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div></div>';
  };

  // (b) the verdict: wins on the position-relevant percentile metrics, biggest gaps each way.
  const pctMetrics = metricsAll.filter(m => m.pct && inScope(m));
  const pa = pctComp(A), pb = pctComp(B);
  const comparable = pctMetrics.map(m => ({ m: m, a: pa[m.key], b: pb[m.key] })).filter(x => has(x.a) && has(x.b)).map(x => Object.assign(x, { gap: x.a - x.b }));
  let verdict;
  if (!comparable.length) {
    const why = P.filter(p => !Object.keys(pctComp(p)).length).map(p => esc(name(p)) + ' has no percentiles in ' + esc(p.comp.name) + ' (below the ' + floorOf(p) + '-minute floor)');
    verdict = mutedLine(why.length ? why.join('; ') + '.' : 'No metric has a percentile for both players.');
  } else {
    const winsA = comparable.filter(x => x.gap > 0).length, winsB = comparable.filter(x => x.gap < 0).length, level = comparable.length - winsA - winsB;
    const topA = comparable.filter(x => x.gap > 0).sort((x, y) => y.gap - x.gap).slice(0, 3);
    const topB = comparable.filter(x => x.gap < 0).sort((x, y) => x.gap - y.gap).slice(0, 3);
    const say = (list, who) => list.length ? '<strong>' + esc(who) + '</strong>: ' + list.map(x => signed(Math.abs(x.gap), 0) + ' pct on ' + esc(x.m.label)).join('; ') : '<strong>' + esc(who) + '</strong>: leads on nothing';
    const n = comparable.length;
    verdict = '<div class="cmp-verdict"><div class="cmp-verdict-side a">' + say(topA, short(A)) + '</div>' +
      '<div class="cmp-verdict-mid"><div class="cmp-score"><span class="a">' + winsA + '</span><span class="dash">–</span><span class="b">' + winsB + '</span></div>' +
      '<div class="cmp-wins"><span class="a" style="width:' + (100 * winsA / n) + '%"></span><span class="t" style="width:' + (100 * level / n) + '%"></span><span class="b" style="width:' + (100 * winsB / n) + '%"></span></div>' +
      '<div class="cmp-score-sub">metrics won of ' + n + (level ? ' · ' + level + ' level' : '') + ' · percentiles in each player\'s competition' + (A.comp.slug !== B.comp.slug ? ' (different competitions: a percentile is against different peers)' : '') + '</div></div>' +
      '<div class="cmp-verdict-side b">' + say(topB, short(B)) + '</div></div>';
  }

  // (d) the full metric table, in two orders.
  const groups = [];
  metricsAll.filter(inScope).forEach(m => { let grp = groups.find(x => x.name === m.group); if (!grp) { grp = { name: m.group, items: [] }; groups.push(grp); } grp.items.push(m); });
  const metricRow = (m, withGroup) => {
    const va = A.row[m.key], vb = B.row[m.key];
    const qa = m.pct ? pa[m.key] : undefined, qb = m.pct ? pb[m.key] : undefined;
    const gap = has(qa) && has(qb) ? qa - qb : null;
    const better = has(va) && has(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    const cells = [{ v: m.label, html: FH.glossaryLink ? FH.glossaryLink(m.key, esc(m.label)) : esc(m.label) }];
    if (withGroup) cells.push({ v: m.group, html: '<span class="muted-inline">' + esc(m.group) + '</span>' });
    cells.push({ v: has(va) ? va : -1e9, html: (better === 'a' ? '<strong>' : '') + (has(va) ? fmtMetric(va, m.fmt) : '—') + (better === 'a' ? '</strong>' : ''), align: 'right' });
    cells.push({ v: has(qa) ? qa : -1, html: m.pct ? pctPill(qa) : '', align: 'center' });
    cells.push({ v: gap === null ? -1 : Math.abs(gap), html: m.pct ? divergingBar(gap) : '', align: 'center' });
    cells.push({ v: has(qb) ? qb : -1, html: m.pct ? pctPill(qb) : '', align: 'center' });
    cells.push({ v: has(vb) ? vb : -1e9, html: (better === 'b' ? '<strong>' : '') + (has(vb) ? fmtMetric(vb, m.fmt) : '—') + (better === 'b' ? '</strong>' : ''), align: 'right' });
    return { cells: cells };
  };
  const cols = withGroup => [{ label: 'Metric' }].concat(withGroup ? [{ label: 'Group' }] : []).concat([
    { label: short(A), align: 'right' }, { label: 'Pct', align: 'center', title: 'Percentile in the competition\'s position pool' },
    { label: 'Gap', align: 'center', title: 'Difference in percentile points; blue when ' + short(A) + ' leads, orange when ' + short(B) + ' does. Click to sort by size.' },
    { label: 'Pct', align: 'center' }, { label: short(B), align: 'right' }]);
  const byGroup = groups.map(grp => '<div class="cmp-group-head">' + esc(grp.name) + '</div>' + tableHTML(cols(false), grp.items.map(m => metricRow(m, false)), { compact: true })).join('');
  const flat = metricsAll.filter(inScope).map(m => ({ m: m, gap: (m.pct && has(pa[m.key]) && has(pb[m.key])) ? Math.abs(pa[m.key] - pb[m.key]) : -1 })).sort((x, y) => y.gap - x.gap);
  const byGap = tableHTML(cols(true), flat.map(x => metricRow(x.m, true)), { compact: true, sticky: true });

  // (e) headline per-90s as paired bars.
  const heads = (gk ? HEADLINE_GK : HEADLINE_OUT).map(k => metricsAll.find(m => m.key === k)).filter(Boolean);
  const h2h = heads.map(m => {
    const va = A.row[m.key], vb = B.row[m.key];
    const mx = Math.max(has(va) ? va : 0, has(vb) ? vb : 0) || 1;
    const better = has(va) && has(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    return '<div class="cmp-h2h-label">' + esc(m.label) + (m.lower ? ' <span class="muted-inline">(lower is better)</span>' : '') + '</div><div class="cmp-h2h-row">' +
      '<div class="l"><span class="num">' + (has(va) ? fmtMetric(va, m.fmt) : '—') + '</span><div class="cmp-h2h-bar left"><div style="width:' + (has(va) ? 100 * va / mx : 0) + '%"></div></div></div>' +
      '<div class="cmp-h2h-val' + (better ? ' win' : '') + '">' + (better ? (better === 'a' ? short(A) : short(B)) : 'level') + '</div>' +
      '<div class="r"><span class="num">' + (has(vb) ? fmtMetric(vb, m.fmt) : '—') + '</span><div class="cmp-h2h-bar right"><div style="width:' + (has(vb) ? 100 * vb / mx : 0) + '%"></div></div></div></div>';
  }).join('');

  const globalOk = !!(pctGlobal(A) && pctGlobal(B));
  let html = '<div class="cmp-ids">' + idCard(A, 'a') + idCard(B, 'b') + '</div>';
  html += '<div class="card"><div class="card-header">Verdict <span class="card-sub">Who wins each of the ' + pctMetrics.length + ' percentile metrics of the ' + (gk ? 'goalkeeper' : 'outfield') + ' scope, and the three biggest gaps each way.' + (mixed ? ' A goalkeeper and an outfield player share few metrics.' : '') + '</span></div>' + verdict + '</div>';
  html += '<div class="grid-2">';
  html += '<div class="card"><div class="card-header">Profile <span class="card-sub">Percentile radar on the position-appropriate axes.</span></div>' +
    '<div class="controls"><label><input type="radio" name="cmp-radar-src" value="comp" checked> competition percentiles</label>' +
    '<label' + (globalOk ? '' : ' title="Both players must be qualified in the global pool" style="opacity:.5"') + '><input type="radio" name="cmp-radar-src" value="global"' + (globalOk ? '' : ' disabled') + '> global percentiles</label></div>' +
    '<div id="cmp-radar" style="height:400px"></div></div>';
  html += '<div class="card"><div class="card-header">Head to head per 90 <span class="card-sub">Eight headline rates; the longer bar is the larger figure, green names the better one.</span></div><div class="cmp-h2h">' + (h2h || mutedLine('No per-90 rates.')) + '</div></div>';
  html += '</div>';
  html += '<div class="card"><div class="card-header">Every metric <span class="card-sub">The whole catalogue for the ' + (gk ? 'goalkeeper' : 'outfield') + ' scope: value, percentile pill and the gap in percentile points. Bold marks the better raw figure.</span>' +
    '<label class="card-sub" style="margin-left:auto">order <select id="cmp-metric-mode" class="team-select" style="max-width:190px;padding:3px 8px"><option value="group">by group</option><option value="gap">by size of gap</option></select></label></div><div id="cmp-metrics"></div></div>';
  html += '<div class="card"><div class="card-header">Evolution this season <span class="card-sub">Cumulative goals (solid) against cumulative xG (dotted) by match, and the five-match rolling rating.</span></div>' +
    '<div class="grid-2"><div id="cmp-evo" style="height:320px"></div><div id="cmp-rating" style="height:320px"></div></div></div>';
  html += '<div class="grid-2">';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-a"></span>' + esc(name(A)) + ': shot map <span class="card-sub">Every shot this season; size by xG.</span></div><div id="cmp-shots-a" style="height:420px"></div></div>';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-b"></span>' + esc(name(B)) + ': shot map <span class="card-sub">Every shot this season; size by xG.</span></div><div id="cmp-shots-b" style="height:420px"></div></div>';
  html += '</div><div class="grid-2">';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-a"></span>' + esc(name(A)) + ': last five <span class="card-sub" id="cmp-last-sub-a"></span></div><div id="cmp-last-a"></div></div>';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-b"></span>' + esc(name(B)) + ': last five <span class="card-sub" id="cmp-last-sub-b"></span></div><div id="cmp-last-b"></div></div>';
  html += '</div><div class="grid-2">';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-a"></span>' + esc(name(A)) + ': this season, every competition</div><div id="cmp-season-a"></div></div>';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-b"></span>' + esc(name(B)) + ': this season, every competition</div><div id="cmp-season-b"></div></div>';
  html += '</div>';
  html += '<div class="card"><div class="muted">' + P.map(p => '<a href="#/' + esc(p.comp.slug) + '/player/' + esc(p.id) + '">' + esc(name(p)) + ' →</a>').join(' &nbsp;·&nbsp; ') + ' &nbsp;·&nbsp; <a href="#/lab/' + esc(A.comp.slug === B.comp.slug ? A.comp.slug : 'all') + '/' + esc(A.row.position === 'G' ? 'G' : (A.row.position || 'M')) + '">Player lab →</a> &nbsp;·&nbsp; <a href="#/glossary">Glossary →</a></div></div>';
  setHTML('cmp-body', html);

  // (c) the radar, with its source toggle.
  const axes = gk ? RADAR_GK : RADAR_OUT;
  const drawRadar = src => renderRadar('cmp-radar', axes, P.map(p => ({ name: name(p) + (src === 'global' ? '' : ' (' + (p.comp.short_name || p.comp.slug) + ')'), pct: src === 'global' ? pctGlobal(p) : (Object.keys(pctComp(p)).length ? pctComp(p) : null) })));
  document.querySelectorAll('input[name=cmp-radar-src]').forEach(r => r.addEventListener('change', () => drawRadar(r.value)));
  drawRadar('comp');

  // (d) the metric table order toggle.
  const modeSel = document.getElementById('cmp-metric-mode');
  const drawMetrics = () => { setHTML('cmp-metrics', modeSel.value === 'gap' ? byGap : byGroup); document.querySelectorAll('#cmp-metrics table').forEach(t => FH.makeSortable(t)); };
  modeSel.onchange = drawMetrics;
  drawMetrics();

  // (f), (g), (h) from the club shards.
  Promise.all(P.map(p => cmpFetch(p.comp.slug + '/players/' + p.teamSlug + '.json'))).then(shards => {
    if (!cmpAlive(token)) return;
    const logs = shards.map((s, i) => (((s || {}).players || {})[P[i].id] || {}).matches || []);
    const traces = [], rtraces = [];
    logs.forEach((rows, i) => {
      const p = P[i];
      const chron = rows.slice().reverse();
      let gs = 0, xs = 0;
      const x = chron.map((r, k) => k + 1);
      const goals = chron.map(r => (gs += r.g || 0));
      const xg = chron.map(r => (xs += r.xg || 0));
      traces.push({ type: 'scatter', mode: 'lines+markers', name: name(p) + ' goals', x: x, y: goals, line: { color: PALETTE[i], width: 2 }, text: chron.map(r => (r.ha === 'H' ? 'v ' : '@ ') + r.opp), hovertemplate: name(p) + ': %{y} goals after %{x} (%{text})<extra></extra>' });
      traces.push({ type: 'scatter', mode: 'lines', name: name(p) + ' xG', x: x, y: xg, line: { color: PALETTE[i], width: 1.5, dash: 'dot' }, hovertemplate: name(p) + ': %{y:.2f} xG after %{x}<extra></extra>' });
      const rts = chron.map(r => (r.rt === undefined ? null : r.rt));
      const roll = rts.map((_, k) => { const w = rts.slice(Math.max(0, k - 4), k + 1).filter(v => v !== null); return w.length ? w.reduce((s, v) => s + v, 0) / w.length : null; });
      rtraces.push({ type: 'scatter', mode: 'lines+markers', name: name(p), x: x, y: roll, line: { color: PALETTE[i], width: 2 }, hovertemplate: name(p) + ': rolling rating %{y:.2f}<extra></extra>' });
    });
    if (logs.some(l => l.length)) {
      plot('cmp-evo', traces, layout({ showlegend: true, legend: { orientation: 'h', y: 1.14, font: { color: C.text2 } }, margin: { l: 45, r: 15, t: 30, b: 40 }, xaxis: { title: 'Match' }, yaxis: { title: 'Cumulative goals / xG', rangemode: 'tozero' } }));
      plot('cmp-rating', rtraces, layout({ showlegend: true, legend: { orientation: 'h', y: 1.14, font: { color: C.text2 } }, margin: { l: 45, r: 15, t: 30, b: 40 }, xaxis: { title: 'Match' }, yaxis: { title: 'Rating (5-match rolling)', range: [5.5, 9] } }));
    } else { setHTML('cmp-evo', mutedLine('No match logs for either player yet.')); setHTML('cmp-rating', ''); }
    // Shot maps.
    const shotsOf = rows => { const out = []; rows.forEach(r => (r.shots || []).forEach(s => out.push(Object.assign({}, s, { match: (r.ha === 'H' ? 'v ' : '@ ') + r.opp + ' ' + r.gf + '-' + r.ga })))); return out; };
    const sa = shotsOf(logs[0]), sb = shotsOf(logs[1]);
    if (sa.length) FH.renderShotMap('cmp-shots-a', sa); else setHTML('cmp-shots-a', mutedLine(A.row.is_gk ? 'Goalkeepers rarely shoot.' : logs[0].length ? 'No shots recorded.' : 'No match log for this player.'));
    if (sb.length) FH.renderShotMap('cmp-shots-b', sb); else setHTML('cmp-shots-b', mutedLine(B.row.is_gk ? 'Goalkeepers rarely shoot.' : logs[1].length ? 'No shots recorded.' : 'No match log for this player.'));
    // Last five.
    const lastTable = (p, rows) => rows.length ? tableHTML([
      { label: 'Date' }, { label: 'Opponent' }, { label: 'H/A', align: 'center' }, { label: 'Result', align: 'center' }, { label: 'Min', align: 'right' }, { label: 'Rating', align: 'right' },
      { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }
    ], rows.slice(0, 5).map(r => ({ _href: matchHref(r.gid, p.comp.slug), cells: [
      { v: r.date || '', html: esc(fmtDate(r.date)) }, { v: r.opp, html: esc(r.opp) }, { v: r.ha, align: 'center' },
      { v: r.gf - r.ga, html: '<span class="' + FH.resultClass(r.gf, r.ga) + '">' + r.res + ' ' + r.gf + '–' + r.ga + '</span>', align: 'center' },
      { v: r.min, html: r.min + (r.start ? '' : ' <span class="sub-mark" title="substitute">S</span>'), align: 'right' }, { v: has(r.rt) ? r.rt : 0, html: has(r.rt) ? num(r.rt, 2) : '—', align: 'right' },
      { v: r.g || 0, align: 'right' }, { v: r.a || 0, align: 'right' }, { v: r.xg || 0, html: num(r.xg, 2), align: 'right' }, { v: r.xa || 0, html: num(r.xa, 2), align: 'right' }
    ] })), { compact: true }) : mutedLine('No match log yet.');
    setHTML('cmp-last-a', lastTable(A, logs[0])); setHTML('cmp-last-b', lastTable(B, logs[1]));
    setHTML('cmp-last-sub-a', logs[0].length ? 'of ' + logs[0].length + ' in ' + esc(A.comp.short_name || A.comp.name) : ''); setHTML('cmp-last-sub-b', logs[1].length ? 'of ' + logs[1].length + ' in ' + esc(B.comp.short_name || B.comp.name) : '');
    wireRowLinks('cmp-last-a'); wireRowLinks('cmp-last-b');
  });

  // (i) across competitions this season.
  loadSite('season_index.json').then(idx => {
    if (!cmpAlive(token)) return;
    const seasonTable = (p, elId) => {
      const rows = (((idx || {}).players || {})[p.id] || {}).rows || [];
      if (!rows.length) { setHTML(elId, mutedLine('Only ' + esc(p.comp.name) + ' so far.')); return; }
      const order = { league: 0, cup: 1, domestic: 2, super: 3, international: 4 };
      rows.sort((x, y) => (order[x.fam] || 0) - (order[y.fam] || 0) || (y.min || 0) - (x.min || 0));
      const tot = rows.reduce((s, r) => { ['apps', 'min', 'g', 'a', 'xg', 'xa'].forEach(k => { s[k] = (s[k] || 0) + (r[k] || 0); }); s.rw += (r.rt || 0) * (r.min || 0); return s; }, { rw: 0 });
      setHTML(elId, tableHTML([{ label: 'Competition' }, { label: 'For' }, { label: 'Apps', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }, { label: 'Rating', align: 'right' }],
        rows.map(r => ({ cells: [
          { v: r.cn, html: (r.comp === p.comp.slug ? '<strong>' + esc(r.cn) + '</strong>' : '<a href="#/' + esc(r.comp) + '/player/' + esc(p.id) + '">' + esc(r.cn) + '</a>') + ' <span class="chip">' + esc((FH.FAMILY_LABELS || {})[r.fam] || (r.fam === 'league' ? 'League' : r.fam || '')) + '</span>' },
          { v: r.t, html: esc(r.t) }, { v: r.apps || 0, align: 'right' }, { v: r.min || 0, align: 'right' }, { v: r.g || 0, align: 'right' }, { v: r.a || 0, align: 'right' },
          { v: r.xg || 0, html: num(r.xg, 2), align: 'right' }, { v: r.xa || 0, html: num(r.xa, 2), align: 'right' }, { v: r.rt || 0, html: r.rt ? num(r.rt, 2) : '—', align: 'right' }
        ] })).concat([{ cells: [{ v: 'Total', html: '<strong>All competitions</strong>' }, { v: '' }, { v: tot.apps, html: '<strong>' + tot.apps + '</strong>', align: 'right' }, { v: tot.min, html: '<strong>' + tot.min + '</strong>', align: 'right' },
          { v: tot.g, html: '<strong>' + tot.g + '</strong>', align: 'right' }, { v: tot.a, html: '<strong>' + tot.a + '</strong>', align: 'right' }, { v: tot.xg, html: '<strong>' + num(tot.xg, 2) + '</strong>', align: 'right' }, { v: tot.xa, html: '<strong>' + num(tot.xa, 2) + '</strong>', align: 'right' },
          { v: tot.min ? tot.rw / tot.min : 0, html: tot.min && tot.rw ? '<strong>' + num(tot.rw / tot.min, 2) + '</strong>' : '—', align: 'right' }] }]), { compact: true }));
    };
    seasonTable(A, 'cmp-season-a'); seasonTable(B, 'cmp-season-b');
  });
}

// ── compare: clubs ─────────────────────────────────────────────────────────

const CLUB_FILES = ['teams', 'table', 'strength', 'probs', 'team_stats', 'analytics', 'fixtures', 'players_live'];
const STYLE_AXES = [['possession', 'Possession'], ['field_tilt', 'Field tilt'], ['ppda', 'Pressing (PPDA)'], ['shot_quality', 'Shot quality'], ['xg_for', 'xG for'], ['xg_against', 'xG against'], ['aerial_pct', 'Aerial %'], ['big_chances', 'Big chances']];
const STYLE_FALLBACK = { possession: 'poss', xg_for: 'xg', xg_against: 'xga', shot_quality: 'xg_per_shot', aerial_pct: 'aerial_pct', big_chances: 'big_chances' };

function tableRowOf(t, team) {
  if (!t) return null;
  let row = (t.standings || t.overall || []).find(r => r.team === team) || null;
  if (!row && t.conferences) Object.keys(t.conferences).forEach(gname => { row = row || (t.conferences[gname] || []).find(r => r.team === team) || null; });
  return row;
}

function compareClubs(ka, kb, token) {
  loadSite('pool.json').then(pool => {
    if (!cmpAlive(token)) return;
    const clubs = (pool || {}).clubs || [];
    const resolve = key => {
      if (!key) return null;
      const [comp, slug] = splitKey(key);
      const pc = clubs.find(c => (!comp || c.comp === comp) && ((c.slug || FH.slugify(c.team)) === slug)) || clubs.find(c => (c.slug || FH.slugify(c.team)) === slug) || null;
      return { key: key, slug: slug, comp: comp || (pc ? pc.comp : null), poolClub: pc };
    };
    const ra = resolve(ka), rb = resolve(kb);
    if (!ra || !rb || !ra.comp || !rb.comp) {
      setHTML('cmp-picked', [ra, rb].map(r => r ? '<span class="chip' + (r.comp ? '' : ' warn') + '">' + esc(r.poolClub ? r.poolClub.team : r.slug) + (r.comp ? ' · ' + esc(compOf(r.comp).short_name || r.comp) : ': competition unknown') + '</span>' : '<span class="chip warn">not picked</span>').join(' v '));
      setHTML('cmp-body', '<div class="card">' + mutedLine('Pick both clubs' + (clubs.length ? '' : ' (no pooled model this run, so a club needs its competition prefix)') + '.') + '</div>');
      return;
    }
    Promise.all([ra, rb].map(r => Promise.all(CLUB_FILES.map(f => cmpFetch(r.comp + '/' + f + '.json'))))).then(res => {
      if (!cmpAlive(token)) return;
      const K = [ra, rb].map((r, i) => {
        const d = {}; CLUB_FILES.forEach((f, j) => { d[f] = res[i][j]; });
        const teams = ((d.teams || {}).teams) || {};
        let team = Object.keys(teams).find(n => (teams[n].slug || FH.slugify(n)) === r.slug) || Object.keys(teams).find(n => FH.slugify(n) === r.slug) || null;
        if (!team && r.poolClub && r.poolClub.comp === r.comp) team = r.poolClub.team;
        if (!team) team = (((d.strength || {}).rows || []).find(x => FH.slugify(x.team) === r.slug) || {}).team || null;
        if (!team) return { comp: compOf(r.comp), slug: r.slug, team: null };
        const an = ((d.analytics || {}).teams || {})[team] || null;
        return { comp: compOf(r.comp), slug: r.slug, team: team, info: teams[team] || {}, d: d,
                 row: tableRowOf(d.table, team), bands: (d.table || {}).bands || ((d.probs || {}).bands) || [],
                 prob: ((d.probs || {}).teams || []).find(x => x.team === team) || null,
                 str: ((d.strength || {}).rows || []).find(x => x.team === team) || null,
                 ts: ((d.team_stats || {}).teams || {})[team] || null, tsMetrics: (d.team_stats || {}).metrics || [],
                 an: an, anMetrics: (d.analytics || {}).team_metrics || [], perf: ((d.analytics || {}).performers || {}).teams || {},
                 fx: (d.fixtures || {}).matches || [], players: (d.players_live || {}).players || [], floor: (d.players_live || {}).minutes_floor || 0,
                 poolClub: clubs.find(c => c.comp === r.comp && c.team === team) || r.poolClub || null,
                 unsimulated: !!((d.table || {}).unsimulated || (d.analytics || {}).unsimulated) };
      });
      setHTML('cmp-picked', K.map((k, i) => k.team ? '<span class="chip"><span class="cmp-pill-' + (i ? 'b' : 'a') + '"></span>' + esc(k.team) + ' · ' + esc(k.comp.short_name || k.comp.name) + '</span>' : '<span class="chip warn">' + esc(k.slug) + ' not found in ' + esc(k.comp.name) + '</span>').join(' v '));
      if (!K[0].team || !K[1].team) { setHTML('cmp-body', '<div class="card">' + mutedLine('One of the clubs is not in that competition\'s data.') + '</div>'); return; }
      buildClubs(K, pool, token);
    });
  });
}

function buildClubs(K, pool, token) {
  const A = K[0], B = K[1];
  const same = A.comp.slug === B.comp.slug;
  const crestOf = (k, size) => crest(k.team, k.info.crest || (k.poolClub || {}).crest || null, size);
  const teamLinkOf = k => '<a class="team-link" href="#/' + esc(k.comp.slug) + '/team/' + esc(k.info.slug || k.slug) + '">' + crestOf(k) + esc(k.team) + '</a>';

  // (a) identity cards.
  const idCard = (k, side) => {
    const r = k.row, s = k.str || {}, season = (k.ts || {}).season || {};
    const chips = [];
    if (r) chips.push('<span class="chip">' + (k.info.conference ? esc(k.info.conference) + ' · ' : '') + 'P' + r.pos + ' · ' + r.pts + ' pts · ' + r.w + '-' + r.d + '-' + r.l + '</span>');
    else if (k.prob && k.prob.conference) chips.push('<span class="chip">' + esc(k.prob.conference) + '</span>');
    if (s.form_results) chips.push('<span class="chip form-chip-wrap">Form ' + formChips(s.form_results) + '</span>');
    if (k.poolClub && k.poolClub.rank) chips.push('<span class="chip" title="Rank on the pooled scale">pool #' + k.poolClub.rank + ' of ' + (pool.clubs || []).length + '</span>');
    if (k.info.league && k.info.league !== k.comp.slug) chips.push('<a class="chip" href="#/' + esc(k.info.league) + '/team/' + esc(FH.slugify(k.team)) + '">in its league →</a>');
    const facts = [['Strength', has(s.strength_ppg) ? num(s.strength_ppg, 2) : '—'], ['Elo', has(s.elo) ? num(s.elo, 0) : '—'], ['Attack', has(s.attack) ? signed(s.attack, 2) : '—'], ['Defence', has(s.defence) ? signed(s.defence, 2) : '—'],
      ['Luck', has(s.luck) ? signed(s.luck, 1) : '—'], ['xG diff / m', has(season.xg_diff) ? signed(season.xg_diff, 2) : '—'], ['PPG', has(s.ppg) ? num(s.ppg, 2) : '—']];
    return '<div class="cmp-id ' + side + '"><div class="ph-crest">' + crestOf(k, 'xl') + '</div><div class="cmp-id-body">' +
      '<div class="cmp-id-name"><a href="#/' + esc(k.comp.slug) + '/team/' + esc(k.info.slug || k.slug) + '">' + esc(k.team) + '</a></div>' +
      '<div class="cmp-id-sub"><a href="#/' + esc(k.comp.slug) + '/overview">' + esc(k.comp.name) + '</a>' + (k.d.table && k.d.table.season ? ' · ' + esc(k.d.table.season) : '') + '</div>' +
      '<div class="ph-chips">' + chips.join('') + '</div>' +
      '<div class="cmp-id-facts">' + facts.map(f => '<div class="cmp-fact"><span>' + f[0] + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div></div>';
  };

  // (b) the hypothetical match.
  let hypo;
  if (A.poolClub && B.poolClub && pool.model) {
    hypo = '<div class="cmp-hypo-grid"><div><div class="mini-head">' + esc(A.team) + ' at home</div>' + matchCard(A.poolClub, B.poolClub, pool.model, false) + '</div>' +
      '<div><div class="mini-head">Neutral venue</div>' + matchCard(A.poolClub, B.poolClub, pool.model, true) + '</div>' +
      '<div><div class="mini-head">' + esc(B.team) + ' at home</div>' + matchCard(B.poolClub, A.poolClub, pool.model, false) + '</div></div>' +
      (A.poolClub.block && B.poolClub.block && A.poolClub.block !== B.poolClub.block ? note('The two clubs sit in different continental blocks (' + esc(A.poolClub.block) + ' and ' + esc(B.poolClub.block) + '). Only a handful of cup matches connect the blocks, so this price is the model\'s best guess with wide error.') : '');
  } else {
    const why = (pool || {}).note ? esc(pool.note) : [A, B].filter(k => !k.poolClub).map(k => esc(k.team) + ' is not in the pooled fit this run' + (k.comp.family === 'international' ? ' (national teams are fitted separately; see the National teams page)' : '')).join('; ') + '.';
    hypo = mutedLine('No price: ' + why);
  }

  // (c) the style radar and (d) the metric table.
  const metricDefs = (() => {
    const out = [];
    [A, B].forEach(k => (k.anMetrics.length ? k.anMetrics : k.tsMetrics.map(m => Object.assign({ group: 'Season averages', desc: '' }, m))).forEach(m => { if (!out.find(x => x.key === m.key)) out.push(m); }));
    return out;
  })();
  const valueOf = (k, key) => { const a = ((k.an || {}).profile || {})[key]; if (a && has(a.v)) return a.v; const s = (k.ts || {}).season || {}; return has(s[key]) ? s[key] : null; };
  const pctOf = (k, key) => { const a = ((k.an || {}).profile || {})[key]; if (a && has(a.pct)) return a.pct; const s = ((k.ts || {}).season || {}).pct || {}; return has(s[key]) ? s[key] : null; };
  const rankOf = (k, key) => {
    const perf = (k.perf || {})[key];
    if (perf && (perf.ranking || []).length) { const i = perf.ranking.findIndex(x => x.team === k.team); return i >= 0 ? [i + 1, perf.ranking.length] : null; }
    const teams = ((k.d.team_stats || {}).teams) || {};
    const def = metricDefs.find(m => m.key === key) || {};
    const vals = Object.keys(teams).map(n => ({ n: n, v: ((teams[n] || {}).season || {})[key] })).filter(x => has(x.v)).sort((x, y) => def.lower ? x.v - y.v : y.v - x.v);
    const i = vals.findIndex(x => x.n === k.team);
    return i >= 0 ? [i + 1, vals.length] : null;
  };
  const styleRows = [A, B].map(k => {
    const p = {};
    STYLE_AXES.forEach(ax => {
      const key = ax[0];
      const prof = ((k.an || {}).profile || {})[key];
      const def = k.anMetrics.find(m => m.key === key) || {};
      if (prof && has(prof.pct)) { p[key] = def.lower ? prof.pct : (key === 'ppda' || key === 'xg_against') ? 100 - prof.pct : prof.pct; return; }
      const fb = STYLE_FALLBACK[key];
      const s = ((k.ts || {}).season || {}).pct || {};
      if (fb && has(s[fb])) p[key] = s[fb];   // team_stats percentiles are already flipped for lower-is-better metrics
    });
    return { name: k.team + (same ? '' : ' (' + (k.comp.short_name || k.comp.slug) + ')'), pct: Object.keys(p).length ? p : null };
  });
  const styleAxes = STYLE_AXES.filter(ax => styleRows.some(r => r.pct && has(r.pct[ax[0]]))).map(ax => ({ key: ax[0], label: ax[1] }));
  const usingFallback = [A, B].every(k => !k.an);
  const groups = [];
  metricDefs.forEach(m => { let grp = groups.find(x => x.name === (m.group || 'Season averages')); if (!grp) { grp = { name: m.group || 'Season averages', items: [] }; groups.push(grp); } grp.items.push(m); });
  const metricTable = groups.map(grp => '<div class="cmp-group-head">' + esc(grp.name) + '</div>' + tableHTML([
    { label: 'Metric' }, { label: A.team, align: 'right' }, { label: 'Pct', align: 'center' }, { label: 'Rank', align: 'right', title: 'Rank in its competition' },
    { label: 'Gap', align: 'center', title: 'Difference in percentile points' }, { label: 'Rank', align: 'right' }, { label: 'Pct', align: 'center' }, { label: B.team, align: 'right' }
  ], grp.items.map(m => {
    const va = valueOf(A, m.key), vb = valueOf(B, m.key), qa = pctOf(A, m.key), qb = pctOf(B, m.key), rka = rankOf(A, m.key), rkb = rankOf(B, m.key);
    const gap = has(qa) && has(qb) ? qa - qb : null;
    const better = has(va) && has(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    return { cells: [
      { v: m.label, html: esc(m.label) + (m.desc ? ' <span class="muted-inline" title="' + esc(m.desc) + '">?</span>' : '') + (m.lower ? ' <span class="muted-inline">↓</span>' : '') },
      { v: has(va) ? va : -1e9, html: (better === 'a' ? '<strong>' : '') + (has(va) ? fmtMetric(va, m.fmt) : '—') + (better === 'a' ? '</strong>' : ''), align: 'right' },
      { v: has(qa) ? qa : -1, html: pctPill(qa), align: 'center' }, { v: rka ? rka[0] : 999, html: rka ? rka[0] + '<span class="muted-inline">/' + rka[1] + '</span>' : '—', align: 'right' },
      { v: gap === null ? -1 : Math.abs(gap), html: divergingBar(gap), align: 'center' },
      { v: rkb ? rkb[0] : 999, html: rkb ? rkb[0] + '<span class="muted-inline">/' + rkb[1] + '</span>' : '—', align: 'right' }, { v: has(qb) ? qb : -1, html: pctPill(qb), align: 'center' },
      { v: has(vb) ? vb : -1e9, html: (better === 'b' ? '<strong>' : '') + (has(vb) ? fmtMetric(vb, m.fmt) : '—') + (better === 'b' ? '</strong>' : ''), align: 'right' }
    ] };
  }), { compact: true })).join('');

  // (e) head to head this season.
  let h2h;
  if (!same) {
    h2h = mutedLine('The clubs are in different competitions this season (' + esc(A.comp.name) + ' and ' + esc(B.comp.name) + '); the hypothetical match above is the model\'s view of a meeting.');
  } else {
    const meetings = A.fx.filter(m => (m.home === A.team && m.away === B.team) || (m.home === B.team && m.away === A.team)).sort((x, y) => String(x.date).localeCompare(String(y.date)));
    h2h = meetings.length ? tableHTML([{ label: 'Date' }, { label: 'Round', align: 'right' }, { label: 'Home' }, { label: 'Score', align: 'center', sortable: false }, { label: 'Away' }, { label: 'xG', align: 'center', sortable: false }, { label: 'Model', sortable: false }, { label: '', sortable: false }],
      meetings.map(m => {
        const done = m.status === 'finished';
        const href = m.detail ? matchHref(m.id, A.comp.slug) : null;
        const model = !done && m.model ? probBar(m.model, { small: true }) + (m.model.fair ? '<div class="fx-model-line"><span>fair ' + m.model.fair.map(f => f === null ? '—' : num(f, 2)).join(' / ') + '</span><span>xG ' + num(m.model.lh, 2) + '–' + num(m.model.la, 2) + '</span><span>' + esc(m.model.score) + ' (' + pct(m.model.p_score, 0) + ')</span></div>' : '') : done ? '' : '<span class="muted-inline">no line</span>';
        return { _href: href, cells: [
          { v: m.date || '', html: esc(fmtDate(m.date, true)) }, { v: m.round === undefined || m.round === null ? '' : m.round, html: esc(FH.roundText(m, A.comp.slug, true)), align: 'right' },
          { v: m.home, html: (m.home === A.team ? crestOf(A) : crestOf(B)) + esc(m.home) }, { v: done ? m.hs + '-' + m.as : '', html: done || m.status === 'live' ? '<span class="score">' + esc(FH.scoreText(m)) + '</span>' : FH.statusChip(m), align: 'center' },
          { v: m.away, html: (m.away === A.team ? crestOf(A) : crestOf(B)) + esc(m.away) },
          { v: '', html: m.xg ? '<span class="xg-line">' + num(m.xg[0], 2) + ' – ' + num(m.xg[1], 2) + '</span>' : '', align: 'center' }, { v: '', html: model }, { v: '', html: href ? '<a href="' + esc(href) + '">Analysis →</a>' : '' }
        ] };
      }), { compact: true }) : mutedLine('No meeting between the two in ' + esc(A.comp.name) + ' this season yet.');
  }

  // (f) form and luck.
  const formRows = k => {
    const f = (k.an || {}).form;
    if (f && f.length) return f.slice(-6).map(r => ({ date: r.date, opp: r.opp, ha: r.ha, gf: r.gf, ga: r.ga, res: r.res, xg: r.xg, xga: r.xga, xpts: r.xpts, pts: r.pts, gid: r.gid }));
    return ((k.ts || {}).matches || []).slice(0, 6).reverse().map(r => ({ date: r.date, opp: r.opp, ha: r.ha, gf: r.gf, ga: r.ga, res: r.res, xg: r.xg, xga: r.xga, xpts: xptsOf(r.xg, r.xga), pts: r.res === 'W' ? 3 : r.res === 'D' ? 1 : 0, gid: r.gid }));
  };
  const formList = k => {
    const rows = formRows(k);
    if (!rows.length) return mutedLine('No matches yet.');
    return '<div class="cmp-form-list">' + rows.map(r => '<div class="cmp-form-row"><span class="muted-inline">' + esc(fmtDate(r.date)) + '</span><span>' + (r.ha === 'H' ? 'v ' : '@ ') + esc(r.opp) + '</span>' +
      '<span class="' + FH.resultClass(r.gf, r.ga) + '">' + esc(r.res || '') + ' ' + r.gf + '–' + r.ga + '</span><span class="xg">' + (has(r.xg) ? 'xG ' + num(r.xg, 2) + '–' + num(r.xga, 2) : '') + (has(r.xpts) ? ' · xPts ' + num(r.xpts, 2) : '') + '</span></div>').join('') + '</div>';
  };
  const roundSeries = k => {
    const rs = (k.an || {}).rounds;
    if (rs && rs.length) return rs.map(r => ({ label: 'R' + r.round, pts: r.pts, xpts: r.xpts }));
    return ((k.ts || {}).matches || []).slice().reverse().map((r, i) => ({ label: (r.round !== undefined && r.round !== null ? 'R' + r.round : 'M' + (i + 1)), pts: r.res === 'W' ? 3 : r.res === 'D' ? 1 : 0, xpts: xptsOf(r.xg, r.xga) }));
  };

  // (g) season position probabilities.
  let bandsHtml;
  if (A.unsimulated || B.unsimulated) bandsHtml = mutedLine('National-team competitions are not simulated, so there are no season probabilities for ' + [A, B].filter(k => k.unsimulated).map(k => esc(k.team)).join(' and ') + '.');
  else if (!A.row && !A.prob && !B.row && !B.prob) bandsHtml = mutedLine('No season simulation for either club yet.');
  else {
    const labels = [];
    const add = (key, label) => { if (!labels.find(x => x.key === key)) labels.push({ key: key, label: label }); };
    [A, B].forEach(k => {
      const isCup = k.comp.kind === 'cup' || k.comp.kind === 'playoff' || k.comp.kind === 'conference';
      add('title', isCup ? 'Winner' : 'Title');
      if (k.comp.kind === 'conference') { add('p_playoffs', 'Playoffs'); add('shield', "Supporters' Shield"); }
      if (k.comp.kind === 'playoff') add('p_playoffs', 'Liguilla');
      if (k.comp.kind === 'cup') add('p_conference', 'Reaches the final');
      k.bands.forEach(b => add('band:' + b.key, b.label));
      add('exp_pts', 'Expected points'); add('range', '5th–95th percentile of points');
    });
    const cell = (k, key) => {
      const r = k.row || {}, p = k.prob || {};
      const isCup = k.comp.kind === 'cup' || k.comp.kind === 'playoff' || k.comp.kind === 'conference';
      const bands = r.bands || p.bands || {};
      if (key === 'title') return pct(isCup ? (has(p.p_cup) ? p.p_cup : r.p_title) : (has(r.p_title) ? r.p_title : p.p_title));
      if (key === 'shield') return pct(p.p_title);
      if (key === 'p_playoffs' || key === 'p_conference') return has(p[key]) ? pct(p[key]) : '—';
      if (key.indexOf('band:') === 0) { const bk = key.slice(5); return has(bands[bk]) ? pct(bands[bk]) : '—'; }
      if (key === 'exp_pts') return has(r.exp_pts) ? num(r.exp_pts, 1) : has(p.exp_pts) ? num(p.exp_pts, 1) : '—';
      if (key === 'range') return has(r.p05) ? num(r.p05, 0) + ' – ' + num(r.p95, 0) : '—';
      return '—';
    };
    bandsHtml = tableHTML([{ label: 'Outcome', sortable: false }, { label: A.team, align: 'right', sortable: false }, { label: B.team, align: 'right', sortable: false }],
      labels.map(l => ({ cells: [{ v: l.label }, { v: '', html: cell(A, l.key), align: 'right' }, { v: '', html: cell(B, l.key), align: 'right' }] })), { compact: true }) +
      (same ? '' : '<div class="doc-meta">Different competitions: each column reads its own club\'s simulation and bands.</div>');
  }

  // (h) squads.
  const squad = k => {
    const rows = k.players.filter(p => p.team === k.team && has(p.rating) && (p.qualified || p.minutes >= (k.floor || 0))).sort((x, y) => y.rating - x.rating).slice(0, 5);
    if (!rows.length) return mutedLine('No qualified players yet' + (k.players.length ? ' (below the ' + k.floor + '-minute floor)' : '') + '.');
    return tableHTML([{ label: 'Player' }, { label: 'Pos', align: 'center' }, { label: 'Min', align: 'right' }, { label: 'Rating', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }],
      rows.map(p => ({ cells: [
        { v: p.name, html: playerLink(p.player_id, p.name, k.comp.slug) }, { v: p.position || '', html: posBadge(p.position), align: 'center' }, { v: p.minutes, align: 'right' },
        { v: p.rating, html: '<strong>' + num(p.rating, 2) + '</strong> ' + ((p.pct || {}).rating !== undefined ? pctPill(p.pct.rating) : ''), align: 'right' },
        { v: p.goals || 0, align: 'right' }, { v: p.assists || 0, align: 'right' }, { v: p.xg || 0, html: num(p.xg, 2), align: 'right' }, { v: p.xa || 0, html: num(p.xa, 2), align: 'right' }
      ] })), { compact: true });
  };

  let html = '<div class="cmp-ids">' + idCard(A, 'a') + idCard(B, 'b') + '</div>';
  html += '<div class="card"><div class="card-header">If they met <span class="card-sub">Priced in the browser from the pooled Dixon-Coles fit (rho ' + num((pool.model || {}).rho, 3) + ', home advantage ' + num((pool.model || {}).home_adv, 3) + '): fair odds carry no margin.</span></div><div class="pad">' + hypo + '</div></div>';
  html += '<div class="grid-2">';
  html += '<div class="card"><div class="card-header">Style <span class="card-sub">Percentiles within each club\'s competition; pressing and xG against are flipped so that outward is better.' + (usingFallback ? ' From the team-stat sheets (no analytics payload yet, so no field tilt or PPDA).' : '') + '</span></div><div id="cmp-style" style="height:400px"></div></div>';
  html += '<div class="card"><div class="card-header">Head to head this season <span class="card-sub">Results and the model line for the fixture to come.</span></div>' + h2h + '</div>';
  html += '</div>';
  html += '<div class="card"><div class="card-header">Every team metric <span class="card-sub">Season averages with each club\'s percentile and rank in its own competition. Bold marks the better raw figure; ↓ marks metrics where lower is better.</span></div>' + (metricDefs.length ? metricTable : mutedLine('No team-stat sheets for these clubs yet.')) + '</div>';
  html += '<div class="grid-2">';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-a"></span>' + esc(A.team) + ': last six</div>' + formList(A) + '<div class="card-header">Points against xPts by round</div><div id="cmp-luck-a" style="height:240px"></div></div>';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-b"></span>' + esc(B.team) + ': last six</div>' + formList(B) + '<div class="card-header">Points against xPts by round</div><div id="cmp-luck-b" style="height:240px"></div></div>';
  html += '</div>';
  html += '<div class="card cmp-bands"><div class="card-header">Season probabilities <span class="card-sub">From each competition\'s Monte Carlo simulation.</span></div>' + bandsHtml + '</div>';
  html += '<div class="grid-2">';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-a"></span>' + esc(A.team) + ': top five by rating</div>' + squad(A) + '</div>';
  html += '<div class="card"><div class="card-header"><span class="cmp-pill-b"></span>' + esc(B.team) + ': top five by rating</div>' + squad(B) + '</div>';
  html += '</div>';
  html += '<div class="card"><div class="muted">' + [A, B].map(k => teamLinkOf(k) + ' →').join(' &nbsp;·&nbsp; ') + ' &nbsp;·&nbsp; <a href="#/clubs">Clubs across leagues →</a> &nbsp;·&nbsp; <a href="#/glossary">Glossary →</a></div></div>';
  setHTML('cmp-body', html);
  document.querySelectorAll('#cmp-body table').forEach(t => FH.makeSortable(t));
  wireRowLinks('cmp-body');

  if (styleAxes.length >= 3) renderRadar('cmp-style', styleAxes, styleRows); else setHTML('cmp-style', mutedLine('No style percentiles for these clubs yet.'));
  const luckChart = (k, elId) => {
    const series = roundSeries(k).filter(r => has(r.xpts));
    if (series.length < 2) { setHTML(elId, mutedLine('Not enough matches with xG.')); return; }
    let cp = 0, cx = 0;
    const x = series.map(r => r.label), pts = series.map(r => (cp += r.pts || 0)), xp = series.map(r => (cx += r.xpts || 0));
    plot(elId, [
      { type: 'scatter', mode: 'lines+markers', name: 'Points', x: x, y: pts, line: { color: C.green, width: 2 }, hovertemplate: '%{x}: %{y} pts<extra></extra>' },
      { type: 'scatter', mode: 'lines', name: 'xPts', x: x, y: xp, line: { color: C.blue, width: 2, dash: 'dot' }, hovertemplate: '%{x}: %{y:.2f} xPts<extra></extra>' }
    ], layout({ showlegend: true, legend: { orientation: 'h', y: 1.18, font: { color: C.text2 } }, margin: { l: 40, r: 15, t: 25, b: 35 }, yaxis: { rangemode: 'tozero' } }));
  };
  luckChart(A, 'cmp-luck-a'); luckChart(B, 'cmp-luck-b');
  if (!cmpAlive(token)) return;
}

function note(html) { return '<div class="doc-note">' + html + '</div>'; }

Object.assign(FH.GLOBAL_PAGES, { clubs: renderClubs, nations: renderNations, leaders: renderLeaders, compare: renderCompare });
FH.dcMatrix = dcMatrix;
FH.matchCard = matchCard;
})(window.FH);
