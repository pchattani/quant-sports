/* The Quant Gridiron — teams (#/teams): every club's unit ratings, tendencies, pace, fourth-down
 * aggressiveness and odds in one sortable table, with offence against defence on a chart.
 *
 * Data: data/<S>/teams.json (per team: unit ratings and history, tendencies, pace, 4th-down
 * aggressiveness, schedule v model, QB situation, roster value; a team catalogue {"metrics", "teams":
 * {abbr: {"values", "pct"}}} when written) and data/<S>/season.json (standings and simulation odds).
 * Also defines the readers the team page (team.js) and compare use: GI.fk.T. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;

// ── readers shared with team.js and compare.js ─────────────────────────────

const T = {};
/* teams.json -> {teams: {abbr: obj}, metrics: [METRIC]}; accepts {"teams": {...}} or a bare {abbr: {...}} dict or a list. */
T.teamsOf = d => {
  const k = K();
  if (!d || d.ok === false) return null;
  k.cleanMetrics(d.metrics);
  let teams = d.teams || d.data || null;
  if (Array.isArray(teams)) { const o = {}; teams.forEach(t => { const a = t.team || t.abbr || t.id; if (a) o[a] = t; }); teams = o; }
  if (!teams) { const o = {}; Object.keys(d).forEach(x => { if (/^[A-Z]{2,3}$/.test(x) && d[x] && typeof d[x] === 'object') o[x] = d[x]; }); teams = Object.keys(o).length ? o : null; }
  if (!teams) return null;
  Object.keys(teams).forEach(t => { const x = teams[t]; if (x && typeof x === 'object') k.learnTeam(t, x); });
  return { teams: teams, metrics: d.metrics || [], raw: d };
};
/* season.json standings -> {abbr: row}; rows may sit under standings {division: [rows]} | [rows] | {abbr: row}, with odds merged. */
T.seasonRows = d => {
  const k = K(), out = {};
  if (!d || d.ok === false) return out;
  const put = (t, r) => { if (!t || !r || typeof r !== 'object') return; out[t] = Object.assign({}, out[t] || {}, r); };
  const walk = x => {
    if (!x) return;
    if (Array.isArray(x)) x.forEach(r => { if (!r || typeof r !== 'object') return; if (Array.isArray(r.teams) || Array.isArray(r.rows)) walk(r.teams || r.rows); else put(r.team || r.abbr, r); });
    else if (typeof x === 'object') Object.keys(x).forEach(key => {
      const v = x[key];
      if (/^[A-Z]{2,3}$/.test(key) && v && typeof v === 'object' && !Array.isArray(v)) put(key, v);
      else if (Array.isArray(v) || (v && typeof v === 'object' && (v.teams || v.rows))) walk(v.teams || v.rows || v);
    });
  };
  walk(d.standings || d.table || d.divisions);
  const odds = d.odds || d.sim || d.simulation || d.playoff_odds;
  if (odds && typeof odds === 'object') {
    const src = odds.teams && typeof odds.teams === 'object' ? odds.teams : odds;
    if (Array.isArray(src)) src.forEach(r => put(r.team || r.abbr, { odds: r }));
    else Object.keys(src).forEach(t => { if (/^[A-Z]{2,3}$/.test(t)) put(t, { odds: src[t] }); });
  }
  const rt = d.ratings;
  if (rt && typeof rt === 'object') {
    const src = rt.teams && typeof rt.teams === 'object' ? rt.teams : rt;
    if (Array.isArray(src)) src.forEach(r => put(r.team || r.abbr, { ratings: r }));
    else Object.keys(src).forEach(t => { if (/^[A-Z]{2,3}$/.test(t)) put(t, { ratings: src[t] }); });
  }
  Object.keys(out).forEach(t => { if (out[t].name) k.learnTeam(t, out[t]); });
  return out;
};
const ODDS = [['p_playoffs', 'Playoffs', ['p_playoffs', 'p_playoff', 'playoffs', 'make_playoffs']], ['p_div', 'Division', ['p_div', 'p_division', 'division']], ['p_bye', 'First-round bye', ['p_bye', 'p_1seed', 'bye']],
  ['p_conf', 'Conference title', ['p_conf', 'p_conference', 'conf', 'p_cc']], ['p_sb', 'Super Bowl', ['p_sb', 'p_champ', 'p_title', 'sb']]];
T.ODDS = ODDS;
T.oddsOf = (...objs) => { const k = K(), o = {}; ODDS.forEach(x => { for (let i = 0; i < objs.length; i++) { const v = k.val(objs[i] || {}, x[2]); if (k.isNum(v)) { o[x[0]] = Number(v); break; } } }); return o; };
/* Unit ratings: {overall, off, def, pass_off, rush_off, pass_def, rush_def, st, qb} from any of a team's blocks. */
T.UNITS = [['overall', 'Rating', ['overall', 'rating', 'net', 'total'], 'Points per game better than an average team on a neutral field', '1', false],
  ['off', 'Offence', ['off_rating', 'off', 'offense', 'offence'], 'Offensive points per game over average', '1', false],
  ['def', 'Defence', ['def_rating', 'def', 'defense', 'defence'], 'Defensive points per game over average (positive = better)', '1', false],
  ['off_epa', 'Off EPA', ['off_epa'], 'Opponent-adjusted EPA per play, offence', 'epa', false], ['def_epa', 'Def EPA ↓', ['def_epa'], 'Opponent-adjusted EPA per play allowed (lower is better)', 'epa', true],
  ['pass_off', 'Pass off', ['off_pass_epa', 'pass_off'], 'EPA per dropback, adjusted', 'epa', false], ['rush_off', 'Rush off', ['off_rush_epa', 'rush_off'], 'EPA per designed run, adjusted', 'epa', false],
  ['pass_def', 'Pass def ↓', ['def_pass_epa', 'pass_def'], 'EPA per dropback allowed (lower is better)', 'epa', true], ['rush_def', 'Rush def ↓', ['def_rush_epa', 'rush_def'], 'EPA per designed run allowed (lower is better)', 'epa', true],
  ['st', 'Special teams', ['st_epa_g', 'st', 'special_teams'], 'Special-teams EPA per game', '2', false]];
T.unitsOf = (...objs) => { const k = K(), o = {}; T.UNITS.forEach(u => { for (let i = 0; i < objs.length; i++) { const v = k.val(objs[i] || {}, u[2]); if (k.isNum(v)) { o[u[0]] = Number(v); break; } } }); return o; };
T.ratingsOf = (tm, row) => { const t = tm || {}, r = row || {}; return T.unitsOf(t.values, (r.ratings || {}).values, r.ratings, (t.units || {}).model, r); };
T.recordOf = (tm, row) => {
  const k = K(), r = row || {}, t = tm || {}, v = t.values || {}, rec = t.record || {};
  const w = k.first(r.w, r.wins, rec.w, v.w), l = k.first(r.l, r.losses, rec.l, v.l), ti = k.first(r.t, r.ties, rec.t, v.t);
  const pf = k.first(r.pf, r.points_for, rec.pf, v.pf), pa = k.first(r.pa, r.points_against, rec.pa, v.pa);
  return { w: w, l: l, t: ti || 0, pf: pf, pa: pa, diff: k.first(r.diff, r.pd, r.point_diff, k.isNum(pf) && k.isNum(pa) ? pf - pa : null) };
};
T.recText = rc => (K().isNum(rc.w) ? rc.w + '–' + rc.l + (rc.t ? '–' + rc.t : '') : '—');
T.tendOf = tm => { const t = tm || {}; return Object.assign({}, t.values || {}, t.tendencies || t.tendency || {}, t.pace && typeof t.pace === 'object' ? t.pace : {}); };
/* Fourth downs from teams.json values: go rate, go rate when the model said go, WP lost (sum, 0-1). */
T.aggOf = tm => { const k = K(), t = tm || {}, v = t.values || {}, f = t.fourth || {}; return { go: k.first(v.go_rate, f.go_rate), goWhen: k.first(v.go_rate_rec, f.go_rate_rec), lost: k.first(v.fd_wp_lost, f.wp_lost), goe: k.first(v.goe, f.goe) }; };
GI.fk = GI.fk || {};
GI.fk.T = T;


// ── the list ───────────────────────────────────────────────────────────────

const ST = { conf: '', extra: [], view: 'units' };
const VIEWS = { units: ['Ratings', 'EPA units'], style: ['Tendencies', 'Defence style', 'Pace'], fourth: ['Fourth down'] };

function render(el, params, state) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">Teams <span class="card-sub" id="tm-sub">Loading…</span><span class="gq-ctl">' +
    k.toggle('tm-view', [['units', 'Ratings'], ['style', 'Tendencies'], ['fourth', '4th downs'], ['odds', 'Odds']], ST.view) + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Conference<select id="tm-conf"><option value="">Both</option><option value="AFC">AFC</option><option value="NFC">NFC</option></select></label>' +
    '<label>Add a metric<select id="tm-extra" class="gq-wide"><option value="">—</option></select></label><label>&nbsp;<button type="button" class="gq-btn" id="tm-clear">Clear added</button></label></div>' +
    '<div id="tm-chips" class="gq-chips"></div><div id="tm-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="tm-note"></div></div>' +
    '<div class="card"><div class="card-header">Offence against defence <span class="card-sub">Opponent-adjusted EPA per play; up and right is better (the defence axis is reversed: less EPA allowed is up). Marker size is playoff odds. Click a team for its page.</span></div><div id="tm-chart" class="gf-chart-lg"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'teams.json'), k.loadY(S, 'season.json')]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = T.teamsOf(o.res[0]), rows = T.seasonRows(o.res[1]), $ = k.$;
    if (!cat && !Object.keys(rows).length) { $('tm-table').innerHTML = k.notBuilt('The ' + S + ' team pages', o.res[0]); $('tm-sub').textContent = ''; k.set('tm-chart', ''); return; }
    const TM = (cat && cat.teams) || {};
    const metrics = (cat && cat.metrics) || [], meta = k.metaOf(metrics);
    const ids = Array.from(new Set(Object.keys(TM).concat(Object.keys(rows)))).filter(t => /^[A-Z]{2,3}$/.test(t));
    $('tm-conf').value = ST.conf;
    $('tm-extra').innerHTML = '<option value="">—</option>' + k.groups(metrics).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
    const draw = () => drawTable(S, ids, TM, rows, metrics, meta, cat);
    $('tm-conf').onchange = e => { ST.conf = e.target.value; draw(); };
    $('tm-extra').onchange = e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0) ST.extra.push(x); e.target.value = ''; draw(); };
    $('tm-clear').onclick = () => { ST.extra = []; draw(); };
    $('tm-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (b) { ST.extra = ST.extra.filter(x => x !== b.dataset.rm); draw(); } };
    k.wireToggle(el, 'tm-view', v => { ST.view = v; draw(); });
    draw();
    chart(S, ids, TM, rows);
    const src = cat && cat.raw ? cat.raw.ratings_source : null;
    k.set('tm-note', 'Ratings: ' + (src === 'team_strength' ? 'our team-strength model (Bayesian, time-decayed, with last season\'s regressed prior and the quarterback as its own component)' : 'opponent-adjusted EPA per play from a ridge regression of every play on offence and defence (the team-strength model takes over when it is fitted)') +
      ', in points per game against an average team on a neutral field; the EPA units are per play. PROE is the pass rate over expected given down, distance, field position, score, time and win probability. ' +
      'Pills are percentiles among the 32 teams (100 = best; ↓ metrics are flipped); tendencies are not good or bad, so they carry ranks (#1 = highest) instead. Playoff and Super Bowl odds come from the season simulation.' +
      (metrics.length ? ' The team catalogue has ' + metrics.length + ' metrics, all on each team page and in <a href="#/compare">compare</a>.' : ''));
  });
}

function vcell(t, m) {
  const k = K(), v = ((t || {}).values || {})[m.key], pc = ((t || {}).pct || {})[m.key], rk = ((t || {}).rank || {})[m.key];
  const tail = k.isNum(pc) ? ' ' + k.pill(pc) : (k.isNum(rk) ? ' <span class="gf-rank">#' + rk + '</span>' : '');
  return { v: k.isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gq-val">' + k.fmt(m, v) + '</span>' + tail, align: 'right' };
}

function drawTable(S, ids0, TM, rows, metrics, meta, cat) {
  const k = K();
  const ids = ids0.filter(t => !ST.conf || (k.team(t).conference || (rows[t] || {}).conference || String((k.team(t).division || '')).slice(0, 3)) === ST.conf);
  const extras = ST.extra.map(x => meta[x]).filter(Boolean);
  const list = ids.slice().sort((a, b) => { const x = T.ratingsOf(TM[a], rows[a]).overall, y = T.ratingsOf(TM[b], rows[b]).overall; return (k.isNum(y) ? y : -99) - (k.isNum(x) ? x : -99) || String(a).localeCompare(String(b)); });
  const base = t => { const rc = T.recordOf(TM[t], rows[t]); return [{ v: k.teamName(t), html: k.teamChip(t, S) + ' <a href="' + k.teamHref(t, S) + '">' + k.esc(k.teamName(t)) + '</a>' },
    { v: k.isNum(rc.w) ? rc.w - rc.l + 0.5 * (rc.t || 0) : null, html: T.recText(rc), align: 'right' }, { v: rc.diff, html: k.isNum(rc.diff) ? k.signed(rc.diff, 0) : '—', align: 'right' }]; };
  const head0 = [{ label: '#', sortable: false }, { label: 'Team' }, { label: 'W–L', align: 'right' }, { label: 'Pt diff', align: 'right' }];
  let cols, body;
  if (ST.view === 'odds') {
    cols = head0.concat([{ label: 'Proj. wins', align: 'right', title: 'Mean simulated wins' }]).concat(ODDS.map(x => ({ label: x[1], align: 'right' }))).concat([{ label: 'SOS left', align: 'right', title: 'Remaining strength of schedule: mean rating of the opponents still to play' }]);
    body = list.map((t, i) => { const r = rows[t] || {}, tm = TM[t] || {}, od = T.oddsOf(r, r.odds, tm.sim, tm.odds);
      const pw = k.first(r.mean_wins, (r.odds || {}).mean_wins, (tm.sim || {}).mean_wins);
      const sos = k.first(r.sos_left, r.sos_remaining, (r.odds || {}).sos_left);
      return { _href: k.teamHref(t, S), cells: [{ v: i + 1, cls: 'pos-cell' }].concat(base(t)).concat([{ v: pw, html: k.isNum(pw) ? k.num(pw, 1) : '—', align: 'right' }])
        .concat(ODDS.map(x => ({ v: od[x[0]], html: k.isNum(od[x[0]]) ? k.pct(od[x[0]], 1) : '—', align: 'right' }))).concat([{ v: sos, html: k.isNum(sos) ? k.signed(sos, 2) : '—', align: 'right' }]) }; });
  } else {
    let ms = metrics.filter(m => VIEWS[ST.view].indexOf(m.group) >= 0);
    if (!ms.length && ST.view === 'units') ms = T.UNITS.map(u => ({ key: u[2][0], label: u[1], fmt: u[4], lower: u[5], desc: u[3] }));
    ms = ms.filter(m => list.some(t => k.isNum(((TM[t] || {}).values || {})[m.key]))).concat(extras.filter(m => !ms.some(x => x.key === m.key)));
    cols = head0.concat(ms.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') })));
    body = list.map((t, i) => ({ _href: k.teamHref(t, S), cells: [{ v: i + 1, cls: 'pos-cell' }].concat(base(t)).concat(ms.map(m => vcell(TM[t], m))) }));
  }
  k.set('tm-table', list.length ? k.table(cols, body, { compact: true, sticky: true }) : k.muted('No teams yet.'));
  k.sortable(k.$('tm-table'));
  k.set('tm-chips', extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + k.esc(m.key) + '">' + k.esc(m.label) + ' ×</button>').join(' ') : '');
  k.set('tm-sub', list.length + ' teams, ' + S + ' · ' + { units: 'ratings and EPA units', style: 'tendencies and pace', fourth: 'fourth downs', odds: 'season simulation' }[ST.view] + ' · sorted by rating; click a header to sort');
}

function chart(S, ids, TM, rows) {
  const k = K(), node = k.$('tm-chart');
  if (!node) return;
  const pts = ids.map(t => { const R = T.ratingsOf(TM[t], rows[t]); const od = T.oddsOf(rows[t], (rows[t] || {}).odds, (TM[t] || {}).sim); return { t: t, x: R.off_epa, y: R.def_epa, p: od.p_playoffs }; }).filter(p => k.isNum(p.x) && k.isNum(p.y));
  if (pts.length < 3) { node.innerHTML = k.muted('EPA units are not available yet.'); node.style.height = 'auto'; return; }
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  k.plot(node, [{ type: 'scatter', mode: 'markers+text', x: xs, y: ys, text: pts.map(p => p.t), textposition: 'top center', textfont: { size: 10, color: k.C.text2 },
    customdata: pts.map(p => k.teamHref(p.t, S)), hovertext: pts.map(p => k.esc(k.teamName(p.t)) + '<br>offence ' + k.fmtV(p.x, 'epa') + ' EPA/play, defence allows ' + k.fmtV(p.y, 'epa') + (k.isNum(p.p) ? '<br>playoffs ' + k.pct(p.p, 0) : '')), hoverinfo: 'text',
    marker: { size: pts.map(p => 9 + (k.isNum(p.p) ? 20 * p.p : 4)), color: pts.map(p => k.teamColour(p.t)), line: { color: '#0d1117', width: 1 } } }],
  k.layout({ margin: { l: 56, r: 12, t: 10, b: 46 }, xaxis: { title: 'Offence: EPA per play (adjusted)', zeroline: false }, yaxis: { title: 'Defence: EPA per play allowed', zeroline: false, autorange: 'reversed' },
    shapes: [{ type: 'line', x0: k.median(xs), x1: k.median(xs), yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot' } }, { type: 'line', y0: k.median(ys), y1: k.median(ys), xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot' } }] }));
  k.clickThrough(node);
}

if (typeof GI.route === 'function') { try { GI.route('teams', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
