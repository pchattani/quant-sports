/* The Quant Footballer — past seasons of a competition.
 *
 *   #/<slug>/p-table?s=<sid>     the final table (official, or computed from results)
 *   #/<slug>/p-results?s=<sid>   every result of the season (store seasons only)
 *   #/<slug>/p-bracket?s=<sid>   the knockout ties
 *   #/<slug>/p-players?s=<sid>   player lines (store seasons with match detail)
 *   #/<slug>/p-leaders?s=<sid>   the season's leaders by category
 *
 * core.js loads the season (data/<slug>/s/<sid>/season.json, or the archive's
 * history/<slug>.json entry when that is all there is) and calls renderPastSeason.
 * Past seasons have no model: no probabilities, power, market or history tabs.
 * The current season's Overview also gets an "Every season" card from here. */
(function (FH) {
'use strict';

const { INDEX, esc, num, fmtDate, fmtMetric, tableHTML, setHTML, sortableIn, wireRowLinks, statTile, crest, clubHref, personHref,
        ROUND_LABELS, withComp, ensureComp, seasonsOf, loadSite, rowsOf } = FH;

const LEADER_LABELS = {
  goals: ['Goals', 'int'], assists: ['Assists', 'int'], goalsAssistsSum: ['Goals + assists', 'int'], rating: ['Rating', '2'],
  expectedGoals: ['Expected goals', '2'], expectedAssists: ['Expected assists', '2'], scoringFrequency: ['Minutes per goal', 'int', true],
  totalShots: ['Shots', 'int'], shotsOnTarget: ['Shots on target', 'int'], bigChancesCreated: ['Big chances created', 'int'], bigChancesMissed: ['Big chances missed', 'int'],
  keyPasses: ['Key passes', 'int'], accuratePasses: ['Accurate passes', 'int'], accurateLongBalls: ['Accurate long balls', 'int'], successfulDribbles: ['Dribbles', 'int'],
  tackles: ['Tackles', 'int'], interceptions: ['Interceptions', 'int'], clearances: ['Clearances', 'int'], possessionLost: ['Possession lost', 'int'],
  saves: ['Saves', 'int'], cleanSheet: ['Clean sheets', 'int'], goalsPrevented: ['Goals prevented', '2'], leastConceded: ['Fewest conceded', 'int'], mostConceded: ['Most conceded', 'int'],
  penaltyGoals: ['Penalty goals', 'int'], penaltyWon: ['Penalties won', 'int'], freeKickGoal: ['Free-kick goals', 'int'],
  yellowCards: ['Yellow cards', 'int'], redCards: ['Red cards', 'int'], topSpeed: ['Top speed (km/h)', '1'],
  kilometersCoveredPer90: ['Distance per 90 (km)', '1'], numberOfSprintsPer90: ['Sprints per 90', '1']
};
const LEADER_ORDER = ['goals', 'assists', 'goalsAssistsSum', 'rating', 'expectedGoals', 'expectedAssists', 'bigChancesCreated', 'keyPasses', 'successfulDribbles',
  'totalShots', 'shotsOnTarget', 'scoringFrequency', 'tackles', 'interceptions', 'clearances', 'saves', 'cleanSheet', 'goalsPrevented', 'accuratePasses',
  'accurateLongBalls', 'penaltyGoals', 'freeKickGoal', 'yellowCards', 'redCards'];

// Club ids by name: the competition's teams.json first, then the club index (both optional).
let CLUB_IDX = null;
function clubIndex() {
  if (CLUB_IDX) return Promise.resolve(CLUB_IDX);
  return loadSite('clubs_index.json').then(ci => {
    CLUB_IDX = {};
    rowsOf(ci).forEach(t => { if (!(t.name in CLUB_IDX)) CLUB_IDX[t.name] = t; });
    return CLUB_IDX;
  });
}

function tidOf(slug, team, row) {
  if (row && row.tid) return row.tid;
  const teams = (((FH.CACHE[slug] || {}).data || {}).teams || {}).teams || {};
  if (teams[team] && teams[team].team_id) return teams[team].team_id;
  const ci = CLUB_IDX || {};
  if (ci[team]) return ci[team].id;
  // Archive tables spell some clubs differently ("Liverpool FC", "Brighton & Hove Albion"): compare folded names.
  const k = foldName(team);
  const hit = Object.keys(teams).find(n => teams[n].team_id && foldName(n) === k);
  if (hit) return teams[hit].team_id;
  const hit2 = Object.keys(ci).find(n => foldName(n) === k);
  return hit2 ? ci[hit2].id : null;
}

function foldName(s) {
  return FH.normText(s).replace(/&/g, ' and ').replace(/\b(fc|afc|cf|sc|ac|cd|sv|fk|club)\b/g, ' ').replace(/[^a-z0-9]+/g, ' ').trim();
}

function clubCell(slug, team, row) {
  const tid = tidOf(slug, team, row);
  const src = tid ? 'assets/crests/' + tid + '.png' : null;
  if (!team) return '<span class="muted-inline">—</span>';
  return tid ? '<a class="team-link" href="' + esc(clubHref(tid, slug)) + '">' + crest(team, src) + esc(team) + '</a>' : crest(team, null) + esc(team);
}

function noteChip(note) {
  if (!note) return '';
  const n = String(note);
  const cls = /releg|descen/i.test(n) ? 'bad' : /champion|title|winner|promot|playoff|qualif|europa|conference|libertadores|sudamericana|copa/i.test(n) ? 'ok' : '';
  return '<span class="chip ' + cls + '">' + esc(n) + '</span>';
}

/* Which tabs a season's payload can fill. */
function pastTabs(doc) {
  const t = ['p-table'];
  if ((doc.fixtures || []).length) t.push('p-results');
  if ((doc.bracket || []).length) t.push('p-bracket');
  if ((doc.players || []).length) t.push('p-players');
  if (Object.keys(doc.leaders || {}).length) t.push('p-leaders');
  if (!(doc.standings || []).length && t.length > 1) t.shift();
  return t;
}

function seasonHeader(c, doc) {
  const m = doc.meta || {};
  // Say what this season actually has: an archive season can be a table, results, leaders or any mix.
  const holds = [];
  if ((doc.standings || []).length) holds.push(doc.standings_source === 'computed' ? 'a table computed from the results' : 'the official final table');
  if ((doc.fixtures || []).length) holds.push('the results');
  if (Object.keys(doc.leaders || {}).length) holds.push('the season\'s leaders');
  const src = doc.source === 'store' ? 'From the match store: every result' + (doc.detail_matches !== undefined ? ', player lines from ' + doc.detail_matches + ' matches with full detail' : '') :
    'From the archive: ' + (holds.length ? holds.join(', ').replace(/, ([^,]*)$/, ' and $1') : 'the season\'s name only') + ((doc.fixtures || []).length ? '' : '; no match list');
  const champ = (m.champion && m.champion.team) || doc.champion_team || null;
  const tiles = [];
  if (champ && c.kind !== 'cup') tiles.push(statTile('Champion', clubCell(c.slug, champ, m.champion), esc(doc.season || '')));
  else if (champ) tiles.push(statTile('Winner', clubCell(c.slug, champ, m.champion), esc(doc.season || '')));
  const st = doc.standings || [];
  if (st.length && !(doc.groups || []).length) {
    const top = st.slice().sort((a, b) => (a.pos || 99) - (b.pos || 99));
    if (!champ) tiles.push(statTile(c.kind === 'cup' ? 'Top of the league phase' : 'Top of the table', clubCell(c.slug, top[0].team, top[0]), top[0].pts !== undefined ? top[0].pts + ' pts' : ''));
    // A cup's table is its league or group phase: its second row is not the runner-up.
    if (top[1] && c.kind !== 'cup') tiles.push(statTile('Runner-up', clubCell(c.slug, top[1].team, top[1]), top[1].pts !== undefined ? top[1].pts + ' pts' : ''));
  }
  const fin = (doc.bracket || []).filter(t => t.round === 'final').slice(-1)[0];
  if (fin && champ && c.kind === 'cup') {
    const loser = fin.home === champ ? fin.away : fin.away === champ ? fin.home : null;
    if (loser) tiles.push(statTile('Runner-up', clubCell(c.slug, loser, { tid: fin.home === champ ? fin.away_id : fin.home_id }),
      'final ' + (fin.home === champ ? fin.hs + '–' + fin.as : fin.as + '–' + fin.hs) + (fin.hs === fin.as ? ', ' + esc(champ) + ' won on penalties' : ' to ' + esc(champ))));
  }
  const g = ((doc.leaders || {}).goals || [])[0];
  if (g) tiles.push(statTile('Top scorer', FH.playerLink(g.id, g.name, c.slug), (g.value || 0) + ' goals · ' + esc(g.team || '')));
  if ((doc.fixtures || []).length) tiles.push(statTile('Matches', (doc.fixtures || []).filter(f => f.status === 'finished').length, 'results in the store'));
  return '<div class="card season-head"><div class="card-header">' + esc(doc.name || (c.name + ' ' + (doc.season || ''))) +
    ' <span class="chip">' + (doc.source === 'store' ? 'store' : 'archive') + '</span><span class="card-sub">' + esc(src) + '.</span>' +
    '<a class="card-sub season-back" href="#/' + esc(c.slug) + '/">Current season →</a></div>' +
    (tiles.length ? '<div class="kpi-grid pad">' + tiles.join('') + '</div>' : '') + '</div>';
}

function standingsHTML(c, doc) {
  const st = (doc.standings || []).slice().sort((a, b) => (a.pos || 99) - (b.pos || 99));
  if (!st.length) return '<div class="muted">No final table for this season' + (c.kind === 'cup' ? ' (a knockout competition)' : '') + '.</div>';
  const full = st.some(r => r.w !== undefined && r.w !== null);
  const one = rows => tableHTML([{ label: '#', sortable: false }, { label: 'Club' }, { label: 'P', align: 'right' }]
    .concat(full ? [{ label: 'W', align: 'right' }, { label: 'D', align: 'right' }, { label: 'L', align: 'right' }, { label: 'GF', align: 'right' }, { label: 'GA', align: 'right' }, { label: 'GD', align: 'right' }] : [])
    .concat([{ label: 'Pts', align: 'right' }, { label: 'Outcome', sortable: false }]),
    rows.map(r => ({ cells: [{ v: r.pos, cls: 'pos-cell' }, { v: r.team, html: clubCell(c.slug, r.team, r) }, { v: r.played, align: 'right' }]
      .concat(full ? ['w', 'd', 'l', 'gf', 'ga'].map(k => ({ v: r[k], align: 'right' })).concat([{ v: r.gd, html: r.gd === undefined || r.gd === null ? '—' : (r.gd > 0 ? '+' : '') + r.gd, align: 'right' }]) : [])
      .concat([{ v: r.pts, html: '<strong>' + (r.pts === undefined || r.pts === null ? '—' : r.pts) + '</strong>', align: 'right' }, { v: r.note || '', html: noteChip(r.note) }]) })), { sticky: true });
  const groups = (doc.groups || []).length ? doc.groups : Array.from(new Set(st.map(r => r.group).filter(Boolean)));
  if (groups.length > 1) {
    return '<div class="zone-grid">' + groups.map(g => '<div class="group-card"><div class="group-card-header">' + esc(g) + '</div>' + one(st.filter(r => r.group === g)) + '</div>').join('') + '</div>';
  }
  return one(st);
}

function seasonListHTML(c, list, activeSid) {
  if (!list.length) return '<div class="muted">No other season on record.</div>';
  return '<div class="season-list">' + list.map(s => {
    const href = s.source === 'live' ? '#/' + c.slug + '/' : '#/' + c.slug + '/p-table?s=' + encodeURIComponent(s.sid);
    const who = s.champion && s.champion.team ? s.champion.team : '';
    return '<a class="season-pill' + (String(s.sid) === String(activeSid) ? ' active' : '') + '" href="' + esc(href) + '"><b>' + esc(s.season || s.name || s.sid) + '</b>' +
      '<span>' + (s.source === 'live' ? (s.status === 'last_edition' ? 'last edition' : 'current') : esc(who || s.source)) + '</span></a>';
  }).join('') + '</div>';
}

function renderPastSeason(arg) {
  const c = arg.comp, doc = arg.doc, tab = arg.tab;
  const pane = document.getElementById('tab-past');
  pane.innerHTML = '<div class="muted">Loading…</div>';
  Promise.all([ensureComp(c.slug, ['teams']), clubIndex(), seasonsOf(c)]).then(res => {
    if (FH.STATE.current !== c.slug || !FH.STATE.season) return;   // navigated away while loading
    const list = res[2] || [];
    withComp(c.slug, () => {
      let body = '';
      if (tab === 'p-table') body = '<div class="card"><div class="card-header">' + ((doc.groups || []).length > 1 ? 'Groups' : 'Final table') +
        ' <span class="card-sub">' + (doc.standings_source === 'computed' ? 'Computed from the results in the store (points, goal difference, goals scored).' : 'The official table as Sofascore published it.') + '</span></div>' + standingsHTML(c, doc) + '</div>';
      else if (tab === 'p-results') body = resultsHTML(c, doc);
      else if (tab === 'p-bracket') body = bracketHTML(c, doc);
      else if (tab === 'p-players') body = '<div class="card"><div class="card-header">Players <span class="card-sub" id="pp-sub"></span></div><div class="controls" id="pp-controls"></div><div id="pp-table"></div></div>';
      else body = leadersHTML(c, doc);
      pane.innerHTML = seasonHeader(c, doc) + body +
        '<div class="card"><div class="card-header">Every season <span class="card-sub">' + list.length + ' editions on record.</span></div><div class="pad">' + seasonListHTML(c, list, doc.sid) + '</div></div>';
      document.querySelectorAll('#tab-past table').forEach(t => FH.makeSortable(t));
      if (tab === 'p-results') wireResults(c, doc);
      if (tab === 'p-players') wirePlayers(c, doc);
      wireRowLinks('tab-past');
    });
  });
}

function resultsHTML(c, doc) {
  const fx = doc.fixtures || [];
  const teams = Array.from(new Set(fx.map(f => f.home).concat(fx.map(f => f.away)))).sort((a, b) => a.localeCompare(b));
  return '<div class="card"><div class="card-header">Results <span class="card-sub" id="pr-count"></span></div><div class="controls">' +
    '<select id="pr-team" class="team-select" style="max-width:240px"><option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('') + '</select>' +
    '<label><input type="checkbox" id="pr-detail"> with full match data only</label></div><div class="fx-list" id="pr-list"></div></div>';
}

function wireResults(c, doc) {
  const fx = (doc.fixtures || []).slice().sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
  const sel = document.getElementById('pr-team'), det = document.getElementById('pr-detail');
  const draw = () => withComp(c.slug, () => {
    const rows = fx.filter(f => (!sel.value || f.home === sel.value || f.away === sel.value) && (!det.checked || f.detail));
    setHTML('pr-count', rows.length + ' of ' + fx.length + ' matches');
    let html = '', lastDay = null;
    rows.forEach(f => {
      const day = FH.localDay(f.date) || 'TBD';
      if (day !== lastDay) { html += '<div class="fx-day">' + esc(fmtDate(f.date, true)) + '</div>'; lastDay = day; }
      html += pastFixtureRow(c, f);
    });
    setHTML('pr-list', html || '<div class="muted">No match for that filter.</div>');
    wireRowLinks('pr-list');
  });
  sel.onchange = draw; det.onchange = draw;
  draw();
}

function pastFixtureRow(c, f) {
  const href = f.detail ? FH.matchHref(f.id, c.slug) : null;
  const roundTxt = FH.roundText(f, c.slug, true);
  const done = f.status === 'finished';
  return '<div class="fx-row detail' + (href ? ' has-link' : '') + '"' + (href ? ' data-href="' + esc(href) + '"' : '') + '>' +
    '<div class="fx-when">' + FH.statusChip(f) + '<span class="fx-round">' + esc(roundTxt) + (f.group ? ' · ' + esc(f.group) : '') + '</span></div>' +
    '<div class="fx-home">' + clubCell(c.slug, f.home, { tid: f.home_id }).replace('<a class="team-link"', '<a class="team-link rev"') + '</div>' +
    '<div class="fx-score"><span class="score' + (done ? '' : ' vs') + '">' + esc(FH.scoreText(f)) + '</span></div>' +
    '<div class="fx-away">' + clubCell(c.slug, f.away, { tid: f.away_id }) + '</div>' +
    '<div class="fx-extra">' + (f.xg ? '<span class="xg-line">xG ' + num(f.xg[0], 2) + ' – ' + num(f.xg[1], 2) + '</span>' : '') +
    (href ? '<a class="fx-link" href="' + esc(href) + '">Analysis →</a>' : (done ? '<span class="muted-inline">result only</span>' : '')) + '</div></div>';
}

function bracketHTML(c, doc) {
  const order = ['prelim', 'q1', 'q2', 'q3', 'q4', 'po', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r64', 'r32', 'r16', 'qf', 'sf', '3rd', 'final'];
  // The payload lists matches; a two-legged tie is two of them. Pair legs by the two clubs and add up the aggregate.
  const ties = [];
  (doc.bracket || []).forEach(m => {
    const k = m.round + '|' + [m.home, m.away].sort().join('|');
    let t = ties.find(x => x.key === k);
    if (!t) { t = { key: k, round: m.round, a: m.home, aid: m.home_id, b: m.away, bid: m.away_id, ga: 0, gb: 0, legs: 0, winner: null }; ties.push(t); }
    const aHome = m.home === t.a;
    if (m.hs !== undefined && m.hs !== null) { t.ga += aHome ? m.hs : m.as; t.gb += aHome ? m.as : m.hs; t.legs++; }
    if (m.agg_winner || m.winner) t.winner = m.agg_winner || m.winner;
  });
  ties.forEach(t => { if (!t.winner && t.legs) t.winner = t.ga > t.gb ? t.a : t.gb > t.ga ? t.b : null; });
  const rounds = Array.from(new Set(ties.map(t => t.round))).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return '<div class="card"><div class="card-header">Knockout ties <span class="card-sub">Aggregate score over both legs where there were two; the winner in bold (penalties count when the payload records them).</span></div><div class="pad past-bracket">' + rounds.map(r =>
    '<div class="pb-round"><div class="pb-round-head">' + esc(ROUND_LABELS[r] || r) + '</div>' + ties.filter(t => t.round === r).map(t => {
      const side = (team, id, g) => '<div class="pb-side' + (t.winner && t.winner === team ? ' win' : '') + '">' + clubCell(c.slug, team, { tid: id }) + '<b>' + (t.legs ? g : '') + '</b></div>';
      return '<div class="pb-tie"' + (t.legs > 1 ? ' title="' + t.legs + ' legs"' : '') + '>' + side(t.a, t.aid, t.ga) + side(t.b, t.bid, t.gb) + '</div>';
    }).join('') + '</div>').join('') + '</div></div>';
}

function leadersHTML(c, doc) {
  const L = doc.leaders || {};
  const keys = LEADER_ORDER.filter(k => (L[k] || []).length).concat(Object.keys(L).filter(k => LEADER_ORDER.indexOf(k) < 0 && (L[k] || []).length));
  if (!keys.length) return '<div class="card"><div class="muted">No leaders recorded for this season.</div></div>';
  return '<div class="card"><div class="card-header">Season leaders <span class="card-sub">Sofascore\'s season leaderboards' + (doc.source === 'store' ? '' : ' from the archive') + '; names open the player\'s page.</span></div><div class="pad"><div class="mini-grid leaders-grid">' +
    keys.map(k => {
      const def = LEADER_LABELS[k] || [k, '2'];
      const rows = L[k].slice(0, 8);
      return '<div class="mini-card"><div class="mini-head">' + esc(def[0]) + (def[2] ? ' <span class="muted-inline">(lower is better)</span>' : '') + '</div>' + rows.map((p, i) =>
        '<div class="mini-row"><span class="mini-rank">' + (i + 1) + '</span><span class="mini-name">' + (p.id ? FH.playerLink(p.id, p.name, c.slug) : esc(p.name)) +
        '<span class="mini-sub">' + esc(p.team || '') + '</span></span><span class="mini-val">' + fmtMetric(p.value, Number.isInteger(p.value) ? 'int' : def[1]) + '</span></div>').join('') + '</div>';
    }).join('') + '</div></div></div>';
}

function wirePlayers(c, doc) {
  const all = doc.players || [], metrics = doc.metrics || [];
  setHTML('pp-sub', all.length + ' players' + (doc.detail_matches !== undefined ? ' · lines from ' + doc.detail_matches + ' matches with full detail' + (doc.detail_matches < 50 ? ' (a small sample: read rates with care)' : '') : ''));
  const opts = metrics.length ? metrics : [{ key: 'goals', label: 'Goals', fmt: 'int' }, { key: 'assists', label: 'Assists', fmt: 'int' }, { key: 'rating', label: 'Rating', fmt: '2' }];
  setHTML('pp-controls', '<select id="pp-metric" class="team-select" style="max-width:240px">' + opts.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + '</option>').join('') + '</select>' +
    '<select id="pp-pos" class="team-select" style="max-width:150px"><option value="">All positions</option><option value="G">Goalkeepers</option><option value="D">Defenders</option><option value="M">Midfielders</option><option value="F">Forwards</option></select>' +
    '<label>min. minutes <input type="number" id="pp-min" value="90" min="0" step="90" style="width:70px"></label>');
  const ms = document.getElementById('pp-metric'), ps = document.getElementById('pp-pos'), mm = document.getElementById('pp-min');
  ms.value = opts.some(m => m.key === 'goals') ? 'goals' : opts[0].key;
  const draw = () => withComp(c.slug, () => {
    const m = opts.find(x => x.key === ms.value) || opts[0], key = m.key, floor = parseInt(mm.value, 10) || 0;
    const rows = all.filter(p => (p.minutes || 0) >= floor && (!ps.value || (ps.value === 'G' ? p.is_gk : p.position === ps.value)) && p[key] !== undefined && p[key] !== null)
      .sort((a, b) => m.lower ? a[key] - b[key] : b[key] - a[key]).slice(0, 100);
    setHTML('pp-table', rows.length ? tableHTML([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Club' }, { label: 'Pos', align: 'center' }, { label: 'Min', align: 'right' },
      { label: m.label, align: 'right' }, { label: 'Pctl', align: 'center' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'Rating', align: 'right' }],
      rows.map((p, i) => ({ cells: [{ v: i + 1, cls: 'pos-cell' }, { v: p.name, html: FH.playerLink(p.player_id, p.name, c.slug) }, { v: p.team, html: clubCell(c.slug, p.team, null) },
        { v: p.position || '', html: p.position ? '<span class="pos-badge pos-' + esc(p.position) + '">' + esc(p.position) + '</span>' : '', align: 'center' }, { v: p.minutes || 0, align: 'right' },
        { v: p[key], html: '<strong>' + fmtMetric(p[key], m.fmt) + '</strong>', align: 'right' }, { v: ((p.pct || {})[key]) || -1, html: FH.pctPill((p.pct || {})[key]), align: 'center' },
        { v: p.goals || 0, align: 'right' }, { v: p.assists || 0, align: 'right' }, { v: p.rating || 0, html: p.rating ? num(p.rating, 2) : '—', align: 'right' }] })), { sticky: true }) : '<div class="muted">No player clears the filters.</div>');
    sortableIn('pp-table');
  });
  ms.onchange = draw; ps.onchange = draw; mm.oninput = draw;
  draw();
}

// ── "Every season" on the current season's Overview ───────────────────────

function renderSeasonCard() {
  const c = FH.comp();
  if (!c) return;
  setHTML('ov-seasons', '<span class="muted-inline">Loading…</span>');
  Promise.all([seasonsOf(c), clubIndex()]).then(res => {
    if (!FH.comp() || FH.comp().slug !== c.slug) return;
    setHTML('ov-seasons', seasonListHTML(c, res[0] || [], FH.currentSeason(c).sid));
  });
}

const baseOverview = FH.RENDERERS.overview;
FH.RENDERERS.overview = function () {
  if (baseOverview) baseOverview();
  try { renderSeasonCard(); } catch (err) { console.error('season card failed', err); }
};
FH.renderPastSeason = renderPastSeason;
FH.pastTabs = pastTabs;
FH.seasonListHTML = seasonListHTML;
})(window.FH);
