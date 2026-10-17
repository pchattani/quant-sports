/* The Quant Footballer — the hub page and the club, player and match pages.
 *
 * Pages render into the shared #tab-page pane. Each declares the competition
 * payloads it needs (PAGE_NEEDS) and loads its own shard (a club's player logs,
 * a match's detail) through FH.loadShard. */
(function (FH) {
'use strict';

const { INDEX, C, PALETTE, ROUND_LABELS, esc, pct, num, signed, fmtNum, fmtMetric, fmtDate, fmtTime, fmtStamp, localDay,
        D, comp, kind, crest, teamLink, teamHref, playerLink, matchHref,
        tableHTML, setHTML, sortableIn, wireRowLinks, statTile, formChips, resultClass, riskClass,
        pctPill, pctRow, pctColor, probBar, statusChip, scoreText, plot, layout, renderShotMap, renderXgRace, renderMomentum,
        renderRadar, renderProbBars, loadShard, fixtureRow, teamHeadline, RADAR_OUT, RADAR_GK } = FH;

// ── the hub ────────────────────────────────────────────────────────────────

// The hub itself lives in hub.js (loaded last); this module keeps the club, player and match-adjacent pages.

// ── club page ──────────────────────────────────────────────────────────────

function findTeamBySlug(param) {
  const teams = (D().teams || {}).teams || {};
  for (const name of Object.keys(teams)) if ((teams[name].slug || FH.slugify(name)) === param) return name;
  for (const name of Object.keys(teams)) if (FH.slugify(name) === param) return name;
  const probs = (D().probs || {}).teams || [];
  const hit = probs.find(p => FH.slugify(p.team) === param);
  return hit ? hit.team : null;
}

function pageHeader(crestHtml, title, sub, chips) {
  return '<div class="page-header"><div class="ph-crest">' + crestHtml + '</div><div class="ph-body"><h2>' + title + '</h2>' +
    '<div class="ph-sub">' + sub + '</div>' + (chips ? '<div class="ph-chips">' + chips + '</div>' : '') + '</div></div>';
}

// ── club page: analytics cards (from analytics.json) ───────────────────────

const RADAR_TEAM = [
  { key: 'possession', label: 'Possession' }, { key: 'field_tilt', label: 'Field tilt' }, { key: 'ppda', label: 'Pressing' },
  { key: 'shot_quality', label: 'Shot quality' }, { key: 'xg_for', label: 'xG for' }, { key: 'xg_against', label: 'Defence' },
  { key: 'aerial_pct', label: 'Aerials' }, { key: 'big_chances', label: 'Big chances' }
];
const SQUAD_COLS = {
  G: [['saves_90', 'Saves/90'], ['save_pct', 'Save %'], ['goals_prevented_90', 'Prevented/90'], ['conceded_90', 'Conceded/90'], ['sweeper_90', 'Sweeper/90'], ['pass_pct', 'Pass %']],
  D: [['padj_tkl_int_90', 'PAdj Tkl+Int/90'], ['clearances_90', 'Clearances/90'], ['aerial_pct', 'Aerial %'], ['duel_pct', 'Duel %'], ['pass_pct', 'Pass %'], ['prog_carries_90', 'Prog. carries/90']],
  M: [['npxg_xa_90', 'npxG+xA/90'], ['key_passes_90', 'Key passes/90'], ['pass_pct', 'Pass %'], ['prog_carries_90', 'Prog. carries/90'], ['padj_tkl_int_90', 'PAdj Tkl+Int/90'], ['loss_per_100', 'Lost/100 touches']],
  F: [['npxg_90', 'npxG/90'], ['xa_90', 'xA/90'], ['shots_90', 'Shots/90'], ['xg_per_shot', 'xG/shot'], ['dribbles_90', 'Dribbles/90'], ['finishing', 'Finishing']]
};
const SQUAD_POS_LABELS = { G: 'Goalkeepers', D: 'Defenders', M: 'Midfielders', F: 'Forwards' };
const CLUB_EXTREMES = [
  ['rating', 'Rating', '2', false, 'all'], ['g_minus_xg', 'Goals − xG', '2', false, 'out'], ['npxg_xa_90', 'npxG + xA /90', '2', false, 'out'],
  ['padj_tkl_int_90', 'PAdj tackles + interceptions /90', '2', false, 'out'], ['loss_per_100', 'Possession lost per 100 touches', '1', true, 'out']
];
const SET_PIECE_TILES = [
  ['corners', 'Corners', 'per match', 'corners', '1'], ['big_chances', 'Big chances', 'per match', 'big_chances', '2'], ['big_chances_missed', 'Big chances missed', 'per match', null, '2'],
  ['fouls', 'Fouls', 'per match', 'fouls', '1'], ['cards', 'Cards', 'yellow + red per match', 'cards', '2'], ['km', 'Distance', 'km per match', 'km', '1'], ['sprints', 'Sprints', 'per match', 'sprints', 'int']
];

function isNumV(v) { return v !== null && v !== undefined && !isNaN(v); }
function posBadgeHtml(pos) { return pos ? '<span class="pos-badge pos-' + esc(pos) + '">' + esc(pos) + '</span>' : ''; }

/* The seven cards' shells; the content is filled by renderClubAnalytics once
   the page is in the DOM (Plotly needs the elements). */
function clubAnalyticsHTML(team) {
  return '<div class="grid-2">' +
    '<div class="card"><div class="card-header">Where they rank <span class="card-sub">Every team metric: value, percentile and rank in the competition.</span></div><div id="tp-rank"></div></div>' +
    '<div class="card"><div class="card-header">Style radar <span class="card-sub">Percentiles against the competition; the grey ring is the competition median. Pressing and Defence are turned so bigger is better.</span></div><div id="tp-radar" style="height:400px"></div>' +
    '<div class="card-header">Points and expected points by match <span class="card-sub">Bars = points; line = xPts from each match\'s xG; dotted = cumulative luck.</span></div><div id="tp-xpts" style="height:260px"></div></div>' +
    '</div>' +
    '<div class="card"><div class="card-header">Squad by position <span class="card-sub">Everyone with a minute; six headline rates per position, pills = percentile against positional peers. Click a header to sort.</span></div><div id="tp-squad-pos"></div></div>' +
    '<div class="card"><div class="card-header">Best XI of the club <span class="card-sub">The highest-rated keeper, four defenders, three midfielders and three forwards (180+ minutes where possible); colour = rating.</span></div>' +
    '<div class="tp-xi-wrap"><div id="tp-best-xi" class="an-pitch"></div><div id="tp-topbot"></div></div></div>' +
    '<div class="card"><div class="card-header">Set pieces and discipline <span class="card-sub">Per match, with the club\'s percentile in the competition.</span></div><div id="tp-setpieces"></div></div>';
}

function renderClubAnalytics(team) {
  const d = D();
  const an = d.analytics || null;
  const info = an && an.teams ? an.teams[team] : null;
  const profile = (info && info.profile) || {};
  const hasProfile = Object.keys(profile).length > 0;
  const tmetrics = (an && an.team_metrics) || [];
  const perfTeams = ((an || {}).performers || {}).teams || {};
  const live = d.players_live || {};
  const players = (live.players || []).filter(p => p.team === team);
  const catalogue = live.metrics || [];
  const fmtOf = key => { const m = catalogue.find(x => x.key === key); return m ? m.fmt : '2'; };
  const none = msg => '<div class="muted">' + esc(msg) + '</div>';
  const noAn = !an ? 'No analytics for this competition yet.' : !info ? 'No analytics for ' + team + ' yet.' : 'No season profile for ' + team + ' yet.';

  // Where they rank.
  if (hasProfile) {
    const keys = tmetrics.map(m => m.key).filter(k => profile[k]);
    Object.keys(profile).forEach(k => { if (keys.indexOf(k) < 0) keys.push(k); });
    const groups = [];
    keys.forEach(k => {
      const m = tmetrics.find(x => x.key === k) || { label: k, group: 'Other', fmt: '2' };
      let g = groups.find(x => x.name === (m.group || 'Other'));
      if (!g) { g = { name: m.group || 'Other', items: [] }; groups.push(g); }
      const ranking = (perfTeams[k] || {}).ranking || [];
      const idx = ranking.findIndex(r => r.team === team);
      g.items.push('<div class="rank-row" title="' + esc(m.desc || '') + '"><span class="rank-label">' + esc(m.label) + (m.lower ? ' <span class="muted-inline">↓</span>' : '') + '</span>' +
        '<span class="rank-val">' + fmtMetric(profile[k].v, m.fmt) + '</span><span>' + pctPill(profile[k].pct) + '</span>' +
        '<span class="rank-pos">' + (idx >= 0 ? '<strong>#' + (idx + 1) + '</strong> of ' + ranking.length : '') + '</span></div>');
    });
    setHTML('tp-rank', '<div class="rank-groups">' + groups.map(g => '<div class="rank-group-head">' + esc(g.name) + '</div>' + g.items.join('')).join('') + '</div>');
  } else setHTML('tp-rank', none(noAn));

  // Style radar: the club against the competition median.
  const isGood = key => (typeof FH.teamPctIsGoodness === 'function') ? FH.teamPctIsGoodness(key) : true;
  const axes = RADAR_TEAM.filter(ax => profile[ax.key] && isNumV(profile[ax.key].pct));
  if (axes.length >= 3) {
    const pctMap = {}, median = {};
    axes.forEach(ax => {
      const m = tmetrics.find(x => x.key === ax.key) || {};
      const raw = profile[ax.key].pct;
      // Lower-is-better axes read bigger = better: invert unless the payload already did.
      pctMap[ax.key] = (m.lower && !isGood(ax.key)) ? 100 - raw : raw;
      median[ax.key] = 50;
    });
    renderRadar('tp-radar', axes, [{ name: team, pct: pctMap }, { name: 'Competition median', pct: median }]);
  } else setHTML('tp-radar', none(hasProfile ? 'Not enough team metrics for a radar yet.' : noAn));

  // Points and expected points by match.
  const rds = ((info || {}).rounds || []).filter(r => isNumV(r.pts));
  if (rds.length) {
    const x = rds.map((r, i) => (r.round === null || r.round === undefined) ? i + 1 : r.round);
    let cum = 0;
    const luck = rds.map(r => { cum += (r.pts || 0) - (isNumV(r.xpts) ? r.xpts : 0); return cum; });
    plot('tp-xpts', [
      { type: 'bar', name: 'Points', x: x, y: rds.map(r => r.pts), marker: { color: rds.map(r => r.pts === 3 ? C.green : r.pts === 1 ? C.text3 : C.red), opacity: 0.8 },
        customdata: rds.map(r => (isNumV(r.xg) ? num(r.xg, 2) + '–' + num(r.xga, 2) : '')), hovertemplate: 'Round %{x}: %{y} pts · xG %{customdata}<extra></extra>' },
      { type: 'scatter', mode: 'lines+markers', name: 'xPts', x: x, y: rds.map(r => isNumV(r.xpts) ? r.xpts : null), line: { color: C.blue, width: 2 }, marker: { size: 6 }, hovertemplate: 'Round %{x}: %{y:.2f} xPts<extra></extra>' },
      { type: 'scatter', mode: 'lines', name: 'Cumulative luck', x: x, y: luck, yaxis: 'y2', line: { color: C.yellow, width: 1.5, dash: 'dot' }, hovertemplate: 'Round %{x}: %{y:+.1f} pts above xPts so far<extra></extra>' }
    ], layout({
      showlegend: true, legend: { orientation: 'h', y: 1.18, font: { color: C.text2 } }, margin: { l: 40, r: 40, t: 30, b: 35 },
      xaxis: { title: 'Round', dtick: 1 }, yaxis: { range: [0, 3.2], dtick: 1 },
      yaxis2: { overlaying: 'y', side: 'right', title: 'luck', gridcolor: 'rgba(0,0,0,0)', zerolinecolor: '#30363d', tickfont: { color: C.yellow } }
    }));
  } else setHTML('tp-xpts', none(an ? 'No expected points by match for ' + team + ' yet.' : noAn));

  // Squad by position.
  const withMin = players.filter(p => (p.minutes || 0) >= 1).sort((a, b) => (b.minutes || 0) - (a.minutes || 0));
  if (withMin.length) {
    const blocks = ['G', 'D', 'M', 'F'].map(pos => {
      const group = withMin.filter(p => (pos === 'G' ? p.is_gk : (!p.is_gk && (p.position === pos || (pos === 'M' && ['D', 'F'].indexOf(p.position) < 0)))));
      if (!group.length) return '';
      const cols = SQUAD_COLS[pos];
      const cell = (p, key, fmt) => { const pc = p.pct || {}; return { v: isNumV(p[key]) ? p[key] : -999, html: (isNumV(p[key]) ? fmtMetric(p[key], fmt) : '—') + ' ' + (pc[key] !== undefined ? pctPill(pc[key]) : ''), align: 'right' }; };
      return '<div class="squad-pos-head">' + SQUAD_POS_LABELS[pos] + ' · ' + group.length + '</div>' + tableHTML([
        { label: 'Player' }, { label: 'Pos', align: 'center' }, { label: 'Age', align: 'right' }, { label: 'Apps', align: 'right', title: 'Appearances (starts)' }, { label: 'Min', align: 'right' },
        { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }, { label: 'Rating', align: 'right' }
      ].concat(cols.map(c => ({ label: c[1], align: 'right', title: (catalogue.find(x => x.key === c[0]) || {}).desc || '' }))), group.map(p => ({ cells: [
        { v: p.name, html: playerLink(p.player_id, p.name) }, { v: p.position || '', html: posBadgeHtml(p.position), align: 'center' },
        { v: p.age || 0, html: p.age || '—', align: 'right' }, { v: p.matches || 0, html: (p.matches || 0) + ' <span class="muted-inline">(' + (p.starts || 0) + ')</span>', align: 'right' },
        { v: p.minutes || 0, align: 'right' }, { v: p.goals || 0, align: 'right' }, { v: p.assists || 0, align: 'right' },
        { v: p.xg || 0, html: num(p.xg, 2), align: 'right' }, { v: p.xa || 0, html: num(p.xa, 2), align: 'right' },
        { v: p.rating || 0, html: isNumV(p.rating) ? '<span style="color:' + (FH.ratingColor ? FH.ratingColor(p.rating) : 'inherit') + ';font-weight:600">' + num(p.rating, 2) + '</span>' : '—', align: 'right' }
      ].concat(cols.map(c => cell(p, c[0], fmtOf(c[0])))) })), { compact: true });
    }).join('');
    setHTML('tp-squad-pos', blocks || none('No squad data yet.'));
    document.querySelectorAll('#tp-squad-pos table').forEach(t => FH.makeSortable(t));
  } else setHTML('tp-squad-pos', none('No player data for ' + team + ' yet.'));

  // Best XI of the club, drawn with the Analytics tab's pitch (analytics.js loads after this module).
  if (typeof FH.drawXI !== 'function') setHTML('tp-best-xi', none('The formation drawing did not load.'));
  else if (!players.length) setHTML('tp-best-xi', none('No player data for ' + team + ' yet.'));
  else {
    const rated = players.filter(p => isNumV(p.rating) && (p.minutes || 0) > 0);
    let pool = rated.filter(p => p.minutes >= 180);
    if (pool.length < 11) pool = rated;
    const byRating = (a, b) => b.rating - a.rating;
    const gk = pool.filter(p => p.is_gk).sort(byRating).slice(0, 1);
    const out = pool.filter(p => !p.is_gk).sort(byRating);
    const want = { D: 4, M: 3, F: 3 };
    let chosen = [];
    ['D', 'M', 'F'].forEach(pos => { chosen = chosen.concat(out.filter(p => p.position === pos).slice(0, want[pos])); });
    out.forEach(p => { if (chosen.length < 10 && chosen.indexOf(p) < 0) chosen.push(p); });
    const counts = { D: 0, M: 0, F: 0 };
    chosen.forEach(p => { counts[counts[p.position] !== undefined ? p.position : 'M']++; });
    const formation = ['D', 'M', 'F'].map(k => counts[k]).filter(n => n > 0).join('-');
    const line = p => ({ id: p.player_id, name: p.name, team: p.team, pos: p.is_gk ? 'G' : (p.position || 'M'), rt: p.rating, g: p.goals, a: p.assists, xg: p.xg, xa: p.xa, min: p.minutes });
    const xi = gk.map(line).concat(chosen.sort((a, b) => ['D', 'M', 'F'].indexOf(a.position) - ['D', 'M', 'F'].indexOf(b.position)).map(line));
    if (xi.length) FH.drawXI('tp-best-xi', xi, formation);
    else setHTML('tp-best-xi', none('No rated players yet.'));
  }

  // Top and bottom at the club.
  const qualified = players.filter(p => p.qualified);
  if (qualified.length) {
    const blocks = CLUB_EXTREMES.map(([key, label, fmt, lower, scope]) => {
      const rows = qualified.filter(p => isNumV(p[key]) && (scope === 'all' || !p.is_gk)).sort((a, b) => lower ? a[key] - b[key] : b[key] - a[key]);
      if (rows.length < 2) return '';
      const row = p => '<div class="tb-row"><span class="tb-name">' + playerLink(p.player_id, p.name) + ' ' + posBadgeHtml(p.position) + '</span>' +
        '<span class="tb-val">' + fmtMetric(p[key], fmt) + '</span><span class="tb-pct">' + pctPill((p.pct || {})[key]) + '</span></div>';
      const best = rows.slice(0, 3), worst = rows.slice(-3).reverse().filter(p => best.indexOf(p) < 0);
      return '<div class="tb-block"><div class="tb-head">' + esc(label) + (lower ? ' <span class="muted-inline">(lower is better)</span>' : '') + '</div>' +
        '<div class="tb-sub">Best</div>' + best.map(row).join('') + (worst.length ? '<div class="tb-sub">Worst</div>' + worst.map(row).join('') : '') + '</div>';
    }).filter(Boolean);
    setHTML('tp-topbot', blocks.length ? '<div class="tb-grid">' + blocks.join('') + '</div>' : none('Not enough qualified players yet.'));
  } else setHTML('tp-topbot', none('No player at ' + team + ' has reached ' + (live.minutes_floor || 0) + ' minutes yet.'));

  // Set pieces and discipline.
  const season = (((d.team_stats || {}).teams || {})[team] || {}).season || {};
  const tiles = SET_PIECE_TILES.map(([key, label, sub, tsKey, fmt]) => {
    const m = tmetrics.find(x => x.key === key) || {};
    let v = null, p = null;
    if (profile[key] && isNumV(profile[key].v)) { v = profile[key].v; p = profile[key].pct; }
    else if (tsKey === 'cards' && (isNumV(season.yellow) || isNumV(season.red))) v = (season.yellow || 0) + (season.red || 0);
    else if (tsKey && isNumV(season[tsKey])) { v = season[tsKey]; p = (season.pct || {})[tsKey]; }
    if (!isNumV(v)) return '';
    return statTile(label, fmtMetric(v, m.fmt || fmt) + ' ' + (isNumV(p) ? pctPill(p) : ''), sub);
  }).filter(Boolean);
  setHTML('tp-setpieces', tiles.length ? '<div class="kpi-grid pad" style="margin-bottom:0">' + tiles.join('') + '</div>' : none(hasProfile ? 'No set-piece or discipline figures yet.' : noAn));
}

/* The club's season in the open competition: model tiles, the season profile,
   xG and form charts, the analytics cards, and the squad's lines with
   percentiles. Rendered into `el`; the unified club page calls it inside
   FH.withComp(slug, ...) with the competition's payloads loaded. */
function renderClubDossier(el, team) {
  const d = D();
  const k = kind();
  const c = comp() || {};
  const prob = ((d.probs || {}).teams || []).find(t => t.team === team) || {};
  const str = ((d.strength || {}).rows || []).find(r => r.team === team) || {};
  const ts = ((d.team_stats || {}).teams || {})[team] || { season: {}, matches: [] };
  const season = ts.season || {};
  const metrics = (d.team_stats || {}).metrics || [];
  const t = d.table || {};
  let row = (t.standings || t.overall || []).find(r => r.team === team);
  if (!row && t.conferences) Object.keys(t.conferences).forEach(g => { row = row || (t.conferences[g] || []).find(r => r.team === team); });
  const info = ((d.teams || {}).teams || {})[team] || {};

  const chips = [];
  if (row) chips.push('<span class="chip">' + (info.conference ? esc(info.conference) + ' · ' : '') + 'P' + row.pos + ' · ' + row.pts + ' pts · ' + row.w + '-' + row.d + '-' + row.l + '</span>');
  if (str.form_results) chips.push('<span class="chip form-chip-wrap">Form ' + formChips(str.form_results) + '</span>');
  let html = chips.length ? '<div class="ph-chips dossier-chips">' + chips.join('') + '</div>' : '';

  const tiles = teamHeadline(prob, k).map(([label, v]) => statTile(label, pct(v)));
  tiles.push(statTile('Strength', num(str.strength_ppg, 2), 'expected PPG v average opponent'));
  tiles.push(statTile('Elo', num(str.elo, 0), str.strength_rank ? 'strength rank ' + str.strength_rank : ''));
  tiles.push(statTile('xG for / against', (season.xg === undefined || season.xg === null ? '—' : num(season.xg, 2) + ' / ' + num(season.xga, 2)), 'per match' + (season.with_sheet ? ' · ' + season.with_sheet + ' with stat sheets' : '')));
  tiles.push(statTile('Luck', str.luck === undefined ? '—' : signed(str.luck, 1), 'points above xG expectation'));
  html += '<div class="kpi-grid">' + tiles.join('') + '</div>';

  // Season profile: percentile sliders against the competition.
  const sliders = metrics.filter(m => season[m.key] !== undefined && season[m.key] !== null && (season.pct || {})[m.key] !== undefined);
  html += '<div class="grid-2">';
  html += '<div class="card"><div class="card-header">Season profile <span class="card-sub">Percentile within the competition, from the team-stat sheets.</span></div><div class="pad">' +
    (sliders.length ? sliders.map(m => pctRow(m.label, (season.pct || {})[m.key], fmtMetric(season[m.key], m.fmt))).join('') : '<div class="muted">No team-stat sheets yet for this club.</div>') + '</div></div>';
  html += '<div class="card"><div class="card-header">xG by match <span class="card-sub">For (blue) and against (orange), oldest to newest.</span></div><div id="tp-xg" style="height:360px"></div>' +
    '<div class="card-header">Form <span class="card-sub">Points per match, five-match rolling.</span></div><div id="tp-form" style="height:220px"></div></div>';
  html += '</div>';

  // Analytics: rankings, style, expected points, the squad by position, the
  // best XI, extremes and set pieces (analytics.json; each card degrades alone).
  html += clubAnalyticsHTML(team);
  html += '<div class="card"><div class="card-header">Players in ' + esc(c.name) + ' <span class="card-sub">This season\'s lines in this competition; percentile pills against positional peers.</span></div><div id="tp-squad"></div></div>';
  el.innerHTML = html;
  try { renderClubAnalytics(team); } catch (err) { console.error('club analytics failed', err); }

  // Charts.
  const rows = (ts.matches || []).slice().reverse();
  const withXg = rows.filter(r => r.xg !== undefined && r.xg !== null);
  if (withXg.length) {
    plot('tp-xg', [
      { type: 'bar', name: 'xG for', x: withXg.map((r, i) => i + 1), y: withXg.map(r => r.xg), marker: { color: C.blue }, text: withXg.map(r => (r.ha === 'H' ? 'v ' : '@ ') + r.opp + ' ' + r.gf + '-' + r.ga), textposition: 'none', hovertemplate: '%{text}<br>xG for %{y:.2f}<extra></extra>' },
      { type: 'bar', name: 'xG against', x: withXg.map((r, i) => i + 1), y: withXg.map(r => (r.xga === null || r.xga === undefined) ? null : r.xga), marker: { color: C.orange }, text: withXg.map(r => (r.ha === 'H' ? 'v ' : '@ ') + r.opp), textposition: 'none', hovertemplate: '%{text}<br>xG against %{y:.2f}<extra></extra>' }
    ], layout({ barmode: 'group', showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 45, r: 15, t: 25, b: 35 }, xaxis: { title: 'Match' }, yaxis: { rangemode: 'tozero' } }));
  } else setHTML('tp-xg', '<div class="muted">No xG data yet.</div>');
  const ptsOf = r => r.res === 'W' ? 3 : r.res === 'D' ? 1 : 0;
  if (rows.length >= 2) {
    const roll = rows.map((r, i) => { const w = rows.slice(Math.max(0, i - 4), i + 1); return w.reduce((s, x) => s + ptsOf(x), 0) / w.length; });
    plot('tp-form', [{ type: 'scatter', mode: 'lines+markers', x: rows.map((r, i) => i + 1), y: roll, line: { color: C.green, width: 2 }, marker: { color: rows.map(r => r.res === 'W' ? C.green : r.res === 'D' ? C.text3 : C.red), size: 8 },
      text: rows.map(r => (r.ha === 'H' ? 'v ' : '@ ') + r.opp + ' ' + r.gf + '-' + r.ga), hovertemplate: '%{text}<br>rolling %{y:.2f} PPG<extra></extra>' }],
      layout({ margin: { l: 45, r: 15, t: 10, b: 35 }, yaxis: { range: [0, 3.1], title: 'PPG' }, xaxis: { title: 'Match' } }));
  } else setHTML('tp-form', '<div class="muted">Not enough matches.</div>');

  // Squad.
  const squad = ((d.players_live || {}).players || []).filter(p => p.team === team).sort((a, b) => b.minutes - a.minutes);
  setHTML('tp-squad', squad.length ? tableHTML([
    { label: 'Player' }, { label: 'Pos', align: 'center' }, { label: 'Age', align: 'right' }, { label: 'Apps', align: 'right' }, { label: 'Starts', align: 'right' },
    { label: 'Min', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' },
    { label: 'npxG/90', align: 'right' }, { label: 'xA/90', align: 'right' }, { label: 'Pass %', align: 'right' }, { label: 'Rating', align: 'right' }
  ], squad.map(p => {
    const pc = p.pct || {};
    const cell = (key, fmt) => ({ v: p[key] === undefined ? -1 : p[key], html: (p[key] === undefined ? '—' : fmtMetric(p[key], fmt)) + ' ' + (pc[key] !== undefined ? pctPill(pc[key]) : ''), align: 'right' });
    return { cells: [
      { v: p.name, html: playerLink(p.player_id, p.name) },
      { v: p.position || (p.is_gk ? 'G' : ''), html: (p.position || p.is_gk) ? '<span class="pos-badge pos-' + esc(p.position || 'G') + '">' + esc(p.position || 'G') + '</span>' : '', align: 'center' },
      { v: p.age || 0, html: p.age || '—', align: 'right' }, { v: p.matches, align: 'right' }, { v: p.starts || 0, align: 'right' }, { v: p.minutes, align: 'right' },
      { v: p.goals, align: 'right' }, { v: p.assists, align: 'right' }, { v: p.xg, html: num(p.xg, 2), align: 'right' }, { v: p.xa, html: num(p.xa, 2), align: 'right' },
      p.is_gk ? cell('save_pct', 'pct') : cell('npxg_90', '2'), p.is_gk ? cell('goals_prevented_90', '2') : cell('xa_90', '2'), cell('pass_pct', 'pct'), cell('rating', '2')
    ] };
  }), { sticky: true }) : '<div class="muted">No squad data yet.</div>');
  sortableIn('tp-squad');
}

/* The competition's club page, kept for clubs whose id is unknown (the router
   forwards every other club to the unified #/club/<tid> page). */
function renderTeamPage(param) {
  const d = D();
  const c = comp() || {};
  const team = findTeamBySlug(param) || decodeURIComponent(param);
  const pane = document.getElementById('tab-page');
  const t = d.table || {};
  pane.innerHTML = pageHeader(crest(team, null, 'xl'), esc(team), esc(c.name) + (t.season ? ' · ' + esc(t.season) : ''), '') +
    '<div id="tp-dossier"></div><div class="card"><div class="card-header">Matches <span class="card-sub">Results with xG; fixtures with the model\'s line.</span></div><div id="tp-matches"></div></div>';
  renderClubDossier(document.getElementById('tp-dossier'), team);
  const fx = ((d.fixtures || {}).matches || []).filter(f => f.home === team || f.away === team);
  // Match list: every competition the club plays in, when the cross-competition
  // list exists; the league's fixtures otherwise.
  const drawMatches = (list, withComp) => {
    setHTML('tp-matches', list.length ? tableHTML([
      { label: 'Date' }].concat(withComp ? [{ label: 'Competition' }] : []).concat([{ label: 'Round', align: 'right' }, { label: 'Opponent' }, { label: 'Venue', align: 'center' },
      { label: 'Result', align: 'center' }, { label: 'xG', align: 'center', sortable: false }, { label: 'Model', align: 'center', sortable: false }, { label: '', sortable: false }
    ]), list.map(f => {
      const home = f.home === team, opp = home ? f.away : f.home;
      const gf = home ? f.hs : f.as, ga = home ? f.as : f.hs;
      const done = f.status === 'finished';
      const res = done ? '<span class="' + resultClass(gf, ga) + '">' + gf + ' – ' + ga + '</span>' : statusChip(f);
      const xg = f.xg ? '<span class="xg-line">' + num(home ? f.xg[0] : f.xg[1], 2) + ' – ' + num(home ? f.xg[1] : f.xg[0], 2) + '</span>' : '';
      const model = !done && f.model ? probBar(f.model, { small: true }) : '';
      const compSlug = f.comp || c.slug;
      const href = f.detail ? matchHref(f.id, compSlug) : null;
      return { _href: href, cells: [
        { v: f.date || '', html: esc(fmtDate(f.date, true)) }].concat(withComp ? [{ v: f.cn || '', html: (compSlug === c.slug ? '<strong>' + esc(f.cn || '') + '</strong>' : '<a href="#/' + esc(compSlug) + '/fixtures">' + esc(f.cn || compSlug) + '</a>') }] : []).concat([
        { v: f.round === null || f.round === undefined ? '' : f.round, html: esc(FH.roundText(f, compSlug, true)), align: 'right' },
        { v: opp, html: compSlug === c.slug ? teamLink(opp) : esc(opp) }, { v: home ? 'H' : 'A', align: 'center' },
        { v: done ? gf - ga : -99, html: res, align: 'center' }, { v: '', html: xg, align: 'center' }, { v: '', html: model, align: 'center' },
        { v: '', html: href ? '<a href="' + esc(href) + '">Analysis →</a>' : '' }
      ]) };
    }), { sticky: true }) : '<div class="muted">No matches.</div>');
    wireRowLinks('tp-matches');
    sortableIn('tp-matches');
  };
  drawMatches(fx, false);
  loadShard('club_matches.json', null).then(cm => {
    if (FH.STATE.page !== 'team' || FH.STATE.param !== param) return;
    const all = ((cm || {}).clubs || {})[team];
    if (all && all.length > fx.length) drawMatches(all, true);
  });

}

// ── player page ────────────────────────────────────────────────────────────

const LOG_COLS_OUT = [
  ['min', 'Min', 'int'], ['rt', 'Rating', '2'], ['g', 'G', 'int'], ['a', 'A', 'int'], ['xg', 'xG', '2'], ['xa', 'xA', '2'], ['sh', 'Sh', 'int'], ['sot', 'SoT', 'int'],
  ['kp', 'KP', 'int'], ['pa', 'Pass', 'int'], ['pt', 'Att', 'int'], ['tch', 'Touch', 'int'], ['drw', 'Drb', 'int'], ['pc', 'PrgC', 'int'], ['dw', 'DuelW', 'int'],
  ['tk', 'Tkl', 'int'], ['int', 'Int', 'int'], ['rec', 'Rec', 'int'], ['aw', 'AerW', 'int'], ['fl', 'Fls', 'int'], ['km', 'Km', '1'], ['spr', 'Spr', 'int'], ['ts', 'Top', '1']
];
const LOG_COLS_GK = [
  ['min', 'Min', 'int'], ['rt', 'Rating', '2'], ['ga', 'Conc.', 'int'], ['sv', 'Saves', 'int'], ['svib', 'In box', 'int'], ['gp', 'Prevented', '2'], ['swp', 'Sweeper', 'int'],
  ['hc', 'Claims', 'int'], ['pun', 'Punch', 'int'], ['pa', 'Pass', 'int'], ['pt', 'Att', 'int'], ['lb', 'Long', 'int'], ['lbt', 'Att', 'int'], ['tch', 'Touch', 'int'], ['km', 'Km', '1']
];

/* A player's season in the open competition: percentile sliders, the radar,
   rating by match, the shot map, evolution and the full match log (from the
   club's shard). Rendered into `el`; the person page calls it inside
   FH.withComp(slug, ...) with players_live loaded. `opts.tiles` adds the
   competition's season tiles. Returns false when the player has no line. */
function renderPlayerDossier(el, pid, opts) {
  const o = opts || {};
  const d = D();
  const c = comp() || {};
  const slug = c.slug;
  const live = d.players_live || {};
  const players = live.players || [];
  const metrics = live.metrics || [];
  const p = players.find(x => String(x.player_id) === String(pid));
  if (!p) { el.innerHTML = '<div class="card"><div class="muted">No line for this player in ' + esc(c.name || 'this competition') + ' this season.</div></div>'; return false; }
  const posLabel = (live.positions || {})[p.position] || (p.is_gk ? 'Goalkeeper' : 'Outfield');
  const sub = [teamLink(p.team), esc(c.name)].join(' · ');
  const chips = [];
  chips.push('<span class="chip pos-' + esc(p.position || '') + '">' + esc(posLabel) + '</span>');
  if (p.age) chips.push('<span class="chip">' + p.age + ' years</span>');
  if (p.height) chips.push('<span class="chip">' + p.height + ' cm</span>');
  if (p.country) chips.push('<span class="chip">' + esc(p.country) + '</span>');
  if (p.shirt) chips.push('<span class="chip">#' + esc(p.shirt) + '</span>');
  if (p.pool) chips.push('<span class="chip">' + esc(p.pool.label) + ' pool · ' + p.pool.n + ' qualified</span>');
  else chips.push('<span class="chip warn">below ' + (live.minutes_floor || 0) + ' minutes: no percentiles yet</span>');
  let html = '<div class="ph-chips dossier-chips">' + chips.slice(-1).join('') + '</div>';

  const tiles = [
    statTile('Appearances', p.matches + ' <span class="kpi-dim">(' + (p.starts || 0) + ' starts)</span>', p.minutes + ' minutes'),
    p.is_gk ? statTile('Saves', p.saves, 'save % ' + fmtMetric(p.save_pct, 'pct')) : statTile('Goals', p.goals + (p.pens ? ' <span class="kpi-dim">(' + p.pens + ' pen)</span>' : ''), 'xG ' + num(p.xg, 2) + ' · npxG ' + num(p.npxg, 2)),
    p.is_gk ? statTile('Goals prevented', signed(p.goals_prevented, 2), 'v post-shot xG faced') : statTile('Assists', p.assists, 'xA ' + num(p.xa, 2)),
    p.is_gk ? statTile('Conceded', p.conceded, num(p.conceded_90, 2) + ' per 90') : statTile('Shots', p.shots, num(p.shots_90, 2) + ' per 90 · ' + fmtMetric(p.sot_pct, 'pct') + ' on target'),
    statTile('Rating', p.rating === undefined || p.rating === null ? '—' : num(p.rating, 2), p.pct && p.pct.rating !== undefined ? 'percentile ' + p.pct.rating : 'minutes-weighted'),
    statTile('Cards', (p.yellow || 0) + ' <span class="kpi-dim">Y</span> ' + (p.red || 0) + ' <span class="kpi-dim">R</span>', p.fouls !== undefined ? p.fouls + ' fouls · ' + (p.fouled || 0) + ' fouled' : '')
  ];
  if (o.tiles) html += '<div class="kpi-grid six">' + tiles.join('') + '</div>';

  // Percentile sliders by group.
  const scope = p.is_gk ? 'gk' : 'out';
  const groups = [];
  metrics.filter(m => m.pct && (m.scope === 'all' || m.scope === scope)).forEach(m => {
    let g = groups.find(x => x.name === m.group);
    if (!g) { g = { name: m.group, items: [] }; groups.push(g); }
    g.items.push(m);
  });
  html += '<div class="grid-2"><div class="card"><div class="card-header">Percentile rankings <span class="card-sub">Against ' + esc(posLabel.toLowerCase()) + 's in this competition with ' + (live.minutes_floor || 0) + '+ minutes. Red is better; for fouls, dispossessions and goals conceded, fewer is better.</span></div><div class="pad pct-groups">' +
    groups.map(g => '<div class="pct-group"><div class="pct-group-head">' + esc(g.name) + '</div>' + g.items.map(m => pctRow(m.label, (p.pct || {})[m.key], fmtMetric(p[m.key], m.fmt), m.lower ? 'lower is better' : '')).join('') + '</div>').join('') +
    '</div></div>';
  html += '<div class="card"><div class="card-header">Profile</div><div id="pp-radar" style="height:380px"></div>' +
    '<div class="card-header">Rating by match</div><div id="pp-rating" style="height:220px"></div>' +
    '<div class="card-header">Shot map <span class="card-sub">Every shot this season; size by xG.</span></div><div id="pp-shots" style="height:420px"></div></div></div>';
  html += '<div class="card"><div class="card-header">Evolution this season <span class="card-sub">Cumulative goals against cumulative xG by match, and the five-match rolling rating.</span></div>' +
    '<div class="grid-2"><div id="pp-evo" style="height:300px"></div><div id="pp-roll" style="height:300px"></div></div></div>';
  html += '<div class="card"><div class="card-header">Match log in ' + esc(c.name) + ' <span class="card-sub" id="pp-log-sub">Loading…</span></div><div id="pp-log"></div></div>';
  el.innerHTML = html;

  renderRadar('pp-radar', p.is_gk ? RADAR_GK : RADAR_OUT, [p]);

  const token = (renderPlayerDossier.token = (renderPlayerDossier.token || 0) + 1);
  loadShard('players/' + ((((D().teams || {}).teams || {})[p.team] || {}).slug || FH.slugify(p.team)) + '.json').then(shard => FH.withComp(slug, () => {
    if (token !== renderPlayerDossier.token || !document.getElementById('pp-log')) return;
    const entry = shard && shard.players ? shard.players[String(p.player_id)] : null;
    const rows = entry ? entry.matches : [];
    setHTML('pp-log-sub', rows.length ? rows.length + ' matches, newest first' : 'No match log available.');
    const cols = p.is_gk ? LOG_COLS_GK : LOG_COLS_OUT;
    setHTML('pp-log', rows.length ? tableHTML(
      [{ label: 'Date' }, { label: 'Opponent' }, { label: 'H/A', align: 'center' }, { label: 'Result', align: 'center' }, { label: 'Pos', align: 'center' }]
        .concat(cols.map(cdef => ({ label: cdef[1], align: 'right' }))).concat([{ label: '', sortable: false }]),
      rows.map(r => ({ _href: matchHref(r.gid), cells: [
        { v: r.date || '', html: esc(fmtDate(r.date, true)) }, { v: r.opp, html: teamLink(r.opp) }, { v: r.ha, align: 'center' },
        { v: r.gf - r.ga, html: '<span class="' + resultClass(r.gf, r.ga) + '">' + r.res + ' ' + r.gf + '–' + r.ga + '</span>', align: 'center' },
        { v: r.pos || '', html: (r.pos ? '<span class="pos-badge pos-' + esc(r.pos) + '">' + esc(r.pos) + '</span>' : '') + (r.start ? '' : ' <span class="sub-mark" title="substitute">S</span>'), align: 'center' }
      ].concat(cols.map(cdef => { const v = cdef[0] === 'ga' ? r.ga : r[cdef[0]]; return { v: v === undefined ? -1 : v, html: v === undefined || v === null ? '—' : fmtMetric(v, cdef[2]), align: 'right' }; }))
       .concat([{ v: '', html: '<a href="' + esc(matchHref(r.gid)) + '">→</a>' }]) })), { sticky: true }) : '<div class="muted">No matches recorded for this player.</div>');
    wireRowLinks('pp-log');
    sortableIn('pp-log');

    const chron = rows.slice().reverse();
    if (chron.length) {
      let g = 0, x = 0, ga = 0;
      const xs = chron.map((r, i) => i + 1);
      const goals = chron.map(r => (g += r.g || 0));
      const xgs = chron.map(r => (x += r.xg || 0));
      const gas = chron.map(r => (ga += (r.g || 0) + (r.a || 0)));
      plot('pp-evo', [
        { type: 'scatter', mode: 'lines+markers', name: 'Goals', x: xs, y: goals, line: { color: C.green, width: 2 } },
        { type: 'scatter', mode: 'lines', name: 'xG', x: xs, y: xgs, line: { color: C.blue, width: 2, dash: 'dot' } },
        { type: 'scatter', mode: 'lines+markers', name: 'G+A', x: xs, y: gas, line: { color: C.orange, width: 1.5 } }
      ], layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 40, r: 15, t: 30, b: 35 }, xaxis: { title: 'Match' }, yaxis: { rangemode: 'tozero' } }));
      const rts = chron.map(r => r.rt === undefined ? null : r.rt);
      const roll = rts.map((_, k) => { const w = rts.slice(Math.max(0, k - 4), k + 1).filter(v => v !== null); return w.length ? w.reduce((s, v) => s + v, 0) / w.length : null; });
      plot('pp-roll', [{ type: 'scatter', mode: 'lines+markers', name: 'Rolling rating', x: xs, y: roll, line: { color: C.purple, width: 2 }, hovertemplate: 'rolling rating %{y:.2f}<extra></extra>' }],
        layout({ margin: { l: 40, r: 15, t: 10, b: 35 }, xaxis: { title: 'Match' }, yaxis: { range: [5.5, 9], title: 'Rating, 5-match rolling' } }));
    } else { setHTML('pp-evo', '<div class="muted">No matches yet.</div>'); setHTML('pp-roll', ''); }
    const rated = chron.filter(r => r.rt !== undefined && r.rt !== null);
    if (rated.length) {
      plot('pp-rating', [{ type: 'bar', x: rated.map((r, i) => i + 1), y: rated.map(r => r.rt), marker: { color: rated.map(r => r.rt >= 7.5 ? C.green : r.rt >= 6.5 ? C.blue : C.orange) },
        text: rated.map(r => (r.ha === 'H' ? 'v ' : '@ ') + r.opp + ' · ' + r.min + "'"), textposition: 'none', hovertemplate: '%{text}<br>rating %{y:.2f}<extra></extra>' }],
        layout({ margin: { l: 40, r: 15, t: 10, b: 30 }, yaxis: { range: [4, 10] }, xaxis: { title: 'Match' }, bargap: 0.25 }));
    } else setHTML('pp-rating', '<div class="muted">No ratings.</div>');
    const shots = [];
    rows.forEach(r => (r.shots || []).forEach(s => shots.push(Object.assign({}, s, { match: (r.ha === 'H' ? 'v ' : '@ ') + r.opp + ' ' + r.gf + '-' + r.ga }))));
    if (shots.length) renderShotMap('pp-shots', shots); else setHTML('pp-shots', '<div class="muted">' + (p.is_gk ? 'Goalkeepers rarely shoot.' : 'No shots recorded.') + '</div>');
  }));
  return true;
}

// ── match page ─────────────────────────────────────────────────────────────

// Team-stat sheet rows shown on a match page, in order, with labels.
// ── wiring ─────────────────────────────────────────────────────────────────

Object.assign(FH.PAGES, { team: renderTeamPage });   // match: match.js; players: the person page (people.js)
FH.renderClubDossier = renderClubDossier;
FH.renderPlayerDossier = renderPlayerDossier;
FH.pageHeader = pageHeader;
Object.assign(FH.PAGE_NEEDS, {
  team: ['probs', 'strength', 'table', 'zones', 'team_stats', 'fixtures', 'players_live', 'analytics'],
  player: ['players_live'],
  match: ['fixtures']
});
})(window.FH);
