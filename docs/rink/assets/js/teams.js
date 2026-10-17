/* The Quant Rink — teams (#/teams): every club's unit ratings (5-on-5 offence and defence, power play,
 * penalty kill, goaltending), underlying numbers and season odds in one sortable table, with 5-on-5
 * offence against defence on a chart.
 *
 * Data: data/<S>/teams.json (per team: unit ratings with history, shot maps for and against, line
 * combinations, deployment, schedule v model; a team catalogue {"metrics", "teams": {abbr: {"values",
 * "pct"}}} when written) and data/<S>/season.json (standings, simulation odds, ratings by component).
 * Also defines the readers the team page (team.js), lines and compare use: RK.fk.T. Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;

// ── readers shared with team.js, lines.js and compare.js ───────────────────

const T = {};
const ABBR = /^[A-Z]{2,3}$/;
/* teams.json -> {teams: {abbr: obj}, metrics: [METRIC]}; accepts {"teams": {...}} or a bare {abbr: {...}} dict or a list. */
T.teamsOf = d => {
  const k = K();
  if (!d || d.ok === false) return null;
  k.cleanMetrics(d.metrics);
  let teams = d.teams || d.data || null;
  if (Array.isArray(teams)) { const o = {}; teams.forEach(t => { const a = t.team || t.abbr || t.id; if (a) o[a] = t; }); teams = o; }
  if (!teams) { const o = {}; Object.keys(d).forEach(x => { if (ABBR.test(x) && d[x] && typeof d[x] === 'object') o[x] = d[x]; }); teams = Object.keys(o).length ? o : null; }
  if (!teams) return null;
  Object.keys(teams).forEach(t => { const x = teams[t]; if (x && typeof x === 'object') k.learnTeam(t, x); });
  return { teams: teams, metrics: Array.isArray(d.metrics) ? d.metrics : [], raw: d };
};
/* season.json standings -> {abbr: row}; rows may sit under standings {division: [rows]} | [rows] | {abbr: row}, with odds and ratings merged. */
T.seasonRows = d => {
  const k = K(), out = {};
  if (!d || d.ok === false) return out;
  if (typeof RK.seasonRows === 'function') {
    // the shell's reader (standings.js): standings rows with the simulation merged in and its spellings normalised
    try {
      const rows = RK.seasonRows(d) || [];
      if (rows.length) {
        const sim = (d.sim && d.sim.teams) || d.odds || {}, rt = d.ratings || {};
        rows.forEach(r => { const t = r.team; if (!t) return; out[t] = Object.assign({}, r, { odds: sim[t] || null, ratings: rt[t] || null }); if (r.name) k.learnTeam(t, r); });
        return out;
      }
    } catch (e) { console.warn('RK.seasonRows', e); }
  }
  const put = (t, r) => { if (!t || !r || typeof r !== 'object') return; out[t] = Object.assign({}, out[t] || {}, r); };
  const walk = x => {
    if (!x) return;
    if (Array.isArray(x)) x.forEach(r => { if (!r || typeof r !== 'object') return; if (Array.isArray(r.teams) || Array.isArray(r.rows)) walk(r.teams || r.rows); else put(r.team || r.abbr, r); });
    else if (typeof x === 'object') Object.keys(x).forEach(key => {
      const v = x[key];
      if (ABBR.test(key) && v && typeof v === 'object' && !Array.isArray(v)) put(key, v);
      else if (Array.isArray(v) || (v && typeof v === 'object' && (v.teams || v.rows))) walk(v.teams || v.rows || v);
    });
  };
  const st = d.standings || d.table || d.divisions;
  if (st && st.cols && st.rows) k.colRows(st).forEach(r => put(r.team || r.abbr, r)); else walk(st);
  const odds = d.odds || d.sim || d.simulation || d.playoff_odds;
  if (odds && typeof odds === 'object') {
    const src = odds.teams && typeof odds.teams === 'object' ? odds.teams : odds;
    if (Array.isArray(src)) src.forEach(r => put(r.team || r.abbr, { odds: r }));
    else Object.keys(src).forEach(t => { if (ABBR.test(t)) put(t, { odds: src[t] }); });
  }
  const rt = d.ratings || d.team_ratings;
  if (rt && typeof rt === 'object') {
    const src = rt.teams && typeof rt.teams === 'object' ? rt.teams : rt;
    if (Array.isArray(src)) src.forEach(r => put(r.team || r.abbr, { ratings: r }));
    else Object.keys(src).forEach(t => { if (ABBR.test(t)) put(t, { ratings: src[t] }); });
  }
  Object.keys(out).forEach(t => { if (out[t].name) k.learnTeam(t, out[t]); });
  return out;
};
const ODDS = [['p_playoffs', 'Playoffs', ['p_playoffs', 'p_playoff', 'playoffs', 'make_playoffs']], ['p_div', 'Division', ['p_div', 'p_division', 'division']], ['p_pres', 'Presidents\' Trophy', ['p_pres', 'p_presidents', 'presidents']],
  ['p_conf', 'Conference title', ['p_conf', 'p_conference', 'p_final', 'conf']], ['p_cup', 'Stanley Cup', ['p_cup', 'p_champ', 'p_title', 'cup']]];
T.ODDS = ODDS;
T.oddsOf = function () { const k = K(), o = {}, objs = Array.prototype.slice.call(arguments); ODDS.forEach(x => { for (let i = 0; i < objs.length; i++) { const v = k.val(objs[i] || {}, x[2]); if (k.isNum(v)) { o[x[0]] = Number(v); break; } } }); return o; };
/* Unit ratings: [key, label, candidate keys, description, fmt, lower]. teams.json "units" carries off5 / def5 / pp / pk / goalie / rating
 * (team_strength's components when the model answers, else the season's own per-60 counts), with "pct" (100 = best) per unit. */
T.UNITS = [['overall', 'Rating', ['rating', 'overall', 'net', 'total'], 'Goal differential per game against an average opponent (team-strength model), or xG differential per game from the counts', 'signed', false],
  ['off', '5v5 offence', ['off5', 'ev_off', 'off_5v5', 'off'], 'Expected goals for per 60 at 5 on 5 (above the league when modelled)', '2', false],
  ['def', '5v5 defence', ['def5', 'ev_def', 'def_5v5', 'def'], 'Expected goals against per 60 at 5 on 5 (above the league when modelled); lower is better', '2', true],
  ['pp', 'Power play', ['pp', 'pp_off', 'pp_xgf60'], 'Expected goals for per 60 on the power play', '2', false],
  ['pk', 'Penalty kill', ['pk', 'pk_def', 'pk_xga60'], 'Expected goals against per 60 short-handed; lower is better', '2', true],
  ['goalie', 'Goaltending', ['goalie', 'goaltending', 'gsax60'], 'Goals saved above expected per 60 by the team\'s goalies', 'signed', false]];
T.UNIT_SRC = { overall: 'rating', off: 'off5', def: 'def5', pp: 'pp', pk: 'pk', goalie: 'goalie' };
T.unitsOf = function () { const k = K(), o = {}, objs = Array.prototype.slice.call(arguments); T.UNITS.forEach(u => { for (let i = 0; i < objs.length; i++) { const v = k.val(objs[i] || {}, u[2]); if (k.isNum(v)) { o[u[0]] = Number(v); break; } } }); return o; };
T.ratingsOf = (tm, row) => { const t = tm || {}, r = row || {}; return T.unitsOf(t.units, t.ratings, (r.ratings || {}).units, (r.ratings || {}).values, r.ratings, r); };
/* Percentiles of the units (100 = best) from teams.json units.pct. */
T.unitPct = (tm, row) => { const t = tm || {}, r = row || {}; const P = (t.units || {}).pct || ((r.ratings || {}).units || {}).pct || {}; const o = {}; Object.keys(T.UNIT_SRC).forEach(u => { if (K().isNum(P[T.UNIT_SRC[u]])) o[u] = P[T.UNIT_SRC[u]]; }); return o; };
T.recordOf = (tm, row) => {
  const k = K(), r = row || {}, t = tm || {}, v = t.values || {}, rec = t.record || {};
  const gp = k.first(r.gp, r.GP, rec.gp, v.gp);
  const w = k.first(r.w, r.W, r.wins, rec.w, v.w), l = k.first(r.l, r.L, r.losses, rec.l, v.l), otl = k.first(r.otl, r.OTL, r.ot, rec.otl, v.otl);
  const pts = k.first(r.pts, r.PTS, r.points, rec.pts, v.pts);
  const gf = k.first(r.gf, r.GF, rec.gf, v.gf), ga = k.first(r.ga, r.GA, rec.ga, v.ga);
  return { gp: gp, w: w, l: l, otl: otl || 0, pts: pts, rank: k.first(r.league_rank), streak: r.streak, l10: r.l10, clinch: r.clinch, ppct: k.first(r.p_pct, r.pts_pct, r['P%'], k.isNum(pts) && gp ? pts / (2 * gp) : null), rw: k.first(r.rw, r.RW), row: k.first(r.row, r.ROW), gf: gf, ga: ga, diff: k.isNum(gf) && k.isNum(ga) ? gf - ga : k.first(r.diff), xgf_pct: k.first(r.xgf_pct, r['xGF%'], v.xgf_pct) };
};
T.recText = rc => (K().isNum(rc.w) ? rc.w + '–' + rc.l + '–' + (rc.otl || 0) : '—');
/* A rating history in any shape -> [{x (date or game), ...units}]. */
T.historyOf = (raw, cols) => {
  const k = K();
  let rows = [];
  if (raw && !Array.isArray(raw) && typeof raw === 'object' && !(raw.cols || raw.fields) && Object.keys(raw).some(u => Array.isArray(raw[u]))) {
    const xk = ['date', 'dates', 'game', 'games', 'gp', 'x', 'week'].find(x => Array.isArray(raw[x]));
    const xs = xk ? raw[xk] : null;
    if (xs) rows = xs.map((x, i) => { const o = { x: x }; Object.keys(raw).forEach(u => { if (Array.isArray(raw[u]) && raw[u] !== xs) o[u] = raw[u][i]; }); return o; });
  } else if (Array.isArray(raw) && raw.length && Array.isArray(raw[0])) {
    const hc = cols || ['date', 'overall', 'off', 'def', 'pp', 'pk', 'goalie'];
    rows = raw.map(a => { const o = {}; hc.forEach((c, i) => { o[c] = a[i]; }); return o; });
  } else rows = k.listOf(raw);
  return rows.map(z => Object.assign({ x: z.x !== undefined ? z.x : (z.date || z.game || z.gp || z.week) }, T.unitsOf(z))).filter(z => z.x !== undefined && z.x !== null);
};
RK.fk = RK.fk || {};
RK.fk.T = T;

// ── the list ───────────────────────────────────────────────────────────────

const ST = { conf: '', extra: [], view: 'units' };

function render(el, params, state) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">Teams <span class="card-sub" id="tm-sub">Loading…</span><span class="gq-ctl">' +
    k.toggle('tm-view', [['units', 'Ratings'], ['under', 'Underlying'], ['odds', 'Odds']], ST.view) + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Conference<select id="tm-conf"><option value="">Both</option><option value="Eastern">Eastern</option><option value="Western">Western</option></select></label>' +
    '<label>Add a metric<select id="tm-extra" class="gq-wide"><option value="">—</option></select></label><label>&nbsp;<button type="button" class="gq-btn" id="tm-clear">Clear added</button></label></div>' +
    '<div id="tm-chips" class="gq-chips"></div><div id="tm-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="tm-note"></div></div>' +
    '<div class="card"><div class="card-header">5-on-5 offence against defence <span class="card-sub">Expected goals for and against per 60 at 5 on 5 (the defence axis is reversed); up and right is better; dotted lines are medians. Marker size is playoff odds. Click a team for its page.</span></div><div id="tm-chart" class="gf-chart-lg"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'teams.json'), k.loadY(S, 'season.json')]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = T.teamsOf(o.res[0]), rows = T.seasonRows(o.res[1]), $ = k.$;
    if (!cat && !Object.keys(rows).length) { $('tm-table').innerHTML = k.notBuilt('The ' + k.sLabel(S) + ' team pages', o.res[0]); $('tm-sub').textContent = ''; k.empty('tm-chart', ''); return; }
    const TM = (cat && cat.teams) || {};
    const metrics = (cat && cat.metrics) || [], meta = k.metaOf(metrics);
    const ids = Array.from(new Set(Object.keys(TM).concat(Object.keys(rows)))).filter(t => ABBR.test(t));
    $('tm-conf').value = ST.conf;
    $('tm-extra').innerHTML = '<option value="">—</option>' + k.groups(metrics).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
    $('tm-extra').parentNode.style.display = metrics.length ? '' : 'none';
    $('tm-clear').parentNode.style.display = metrics.length ? '' : 'none';
    const draw = () => drawTable(S, ids, TM, rows, metrics, meta);
    $('tm-conf').onchange = e => { ST.conf = e.target.value; draw(); };
    $('tm-extra').onchange = e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0) ST.extra.push(x); e.target.value = ''; draw(); };
    $('tm-clear').onclick = () => { ST.extra = []; draw(); };
    $('tm-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (b) { ST.extra = ST.extra.filter(x => x !== b.dataset.rm); draw(); } };
    k.wireToggle(el, 'tm-view', v => { ST.view = v; draw(); });
    draw();
    chart(S, ids, TM, rows);
    const src = cat && cat.raw ? cat.raw.ratings_source : null;
    k.set('tm-note', 'Ratings: ' + (src === 'team_strength' ? 'our team-strength model (time-decayed ridge regressions on every game, with last season\'s regressed prior): 5-on-5 expected goals created and allowed above the league per 60, the power play and penalty kill, and goaltending' : 'the season\'s own counts until the team-strength model is fitted: 5-on-5 expected goals for and against per 60, power-play xGF and penalty-kill xGA per 60, and the goalies\' GSAx per 60') +
      (cat && cat.raw && cat.raw.ratings_units ? ' (' + k.esc(cat.raw.ratings_units) + ')' : '') + '; ↓ marks units where lower is better. The rating is the goal (or expected-goal) differential per game. ' +
      'Pills are percentiles among the 32 teams (100 = best); #n is the rank. Playoff and Cup odds come from the season simulation (<a href="#/methodology/season">how</a>).' +
      (metrics.length ? ' The team catalogue has ' + metrics.length + ' metrics, all on each team page and in <a href="#/compare">compare</a>.' : ''));
  });
}

function vcell(t, m) {
  const k = K(), v = ((t || {}).values || {})[m.key], pc = ((t || {}).pct || {})[m.key], rk = ((t || {}).rank || {})[m.key];
  const tail = k.isNum(pc) ? ' ' + k.pill(pc) : (k.isNum(rk) ? ' <span class="gf-rank">#' + rk + '</span>' : '');
  return { v: k.isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gq-val">' + k.fmt(m, v) + '</span>' + tail, align: 'right' };
}
const UNDER = ['xgf_pct', 'cf_pct', 'ff_pct', 'gf_pct', 'xgf60', 'xga60', 'cf60', 'ca60', 'sh_pct', 'sv_pct', 'pdo', 'pp_pct', 'pk_pct', 'pp_xgf60', 'pk_xga60'];

function drawTable(S, ids0, TM, rows, metrics, meta) {
  const k = K();
  const ids = ids0.filter(t => !ST.conf || String(k.team(t).conference || (rows[t] || {}).conference || '').indexOf(ST.conf.slice(0, 4)) === 0);
  const extras = ST.extra.map(x => meta[x]).filter(Boolean);
  const list = ids.slice().sort((a, b) => { const x = T.ratingsOf(TM[a], rows[a]).overall, y = T.ratingsOf(TM[b], rows[b]).overall; return (k.isNum(y) ? y : -99) - (k.isNum(x) ? x : -99) || (T.recordOf(TM[b], rows[b]).pts || 0) - (T.recordOf(TM[a], rows[a]).pts || 0) || String(a).localeCompare(String(b)); });
  const base = t => { const rc = T.recordOf(TM[t], rows[t]); return [{ v: k.teamName(t), html: k.teamChip(t, S) + ' <a href="' + k.teamHref(t, S) + '">' + k.esc(k.teamName(t)) + '</a>' },
    { v: rc.pts, html: T.recText(rc), align: 'right', title: 'W–L–OTL' }, { v: rc.pts, html: k.int(rc.pts), align: 'right' }, { v: rc.diff, html: k.isNum(rc.diff) ? k.signed(rc.diff, 0) : '—', align: 'right' }]; };
  const head0 = [{ label: '#', sortable: false }, { label: 'Team' }, { label: 'W–L–OTL', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'GD', align: 'right', title: 'Goal differential' }];
  let cols, body;
  if (ST.view === 'odds') {
    cols = head0.concat([{ label: 'Proj. pts', align: 'right', title: 'Mean simulated points' }]).concat(ODDS.map(x => ({ label: x[1], align: 'right' })));
    body = list.map((t, i) => { const r = rows[t] || {}, tm = TM[t] || {}, od = T.oddsOf(r, r.odds, tm.sim, tm.odds);
      const pp = k.first((r.odds || {}).exp_pts, (tm.sim || {}).exp_pts, r.mean_pts, (r.odds || {}).mean_pts, (tm.sim || {}).mean_pts, r.proj_pts);
      return { _href: k.teamHref(t, S), cells: [{ v: i + 1, cls: 'pos-cell' }].concat(base(t)).concat([{ v: pp, html: k.isNum(pp) ? k.num(pp, 1) : '—', align: 'right' }])
        .concat(ODDS.map(x => ({ v: od[x[0]], html: k.isNum(od[x[0]]) ? k.pct(od[x[0]], 1) : '—', align: 'right' }))) }; });
  } else if (ST.view === 'units') {
    const us = T.UNITS.filter(u => list.some(t => k.isNum(T.ratingsOf(TM[t], rows[t])[u[0]])));
    cols = head0.concat(us.map(u => ({ label: u[1] + (u[5] ? ' ↓' : ''), align: 'right', title: u[3] }))).concat(extras.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: m.desc || '' })));
    const rk = {};
    us.forEach(u => { const vs = list.map(t => T.ratingsOf(TM[t], rows[t])[u[0]]).filter(k.isNum).sort((a, b) => (u[5] ? a - b : b - a)); rk[u[0]] = vs; });
    body = list.map((t, i) => { const R = T.ratingsOf(TM[t], rows[t]), P = T.unitPct(TM[t], rows[t]);
      return { _href: k.teamHref(t, S), cells: [{ v: i + 1, cls: 'pos-cell' }].concat(base(t)).concat(us.map(u => { const v = R[u[0]]; const r = k.isNum(v) ? rk[u[0]].indexOf(v) + 1 : null;
        return { v: k.isNum(v) ? (u[5] ? -v : v) : -1e9, html: k.isNum(v) ? '<span class="gq-val">' + k.fmtV(v, u[4]) + '</span> ' + (k.isNum(P[u[0]]) ? k.pill(P[u[0]]) : '<span class="gf-rank">#' + r + '</span>') : '—', align: 'right' }; })).concat(extras.map(m => vcell(TM[t], m))) }; });
  } else {
    let ms = metrics.filter(m => UNDER.indexOf(m.key) >= 0);
    if (!ms.length) ms = metrics.slice(0, 10);
    ms = ms.filter(m => list.some(t => k.isNum(((TM[t] || {}).values || {})[m.key]))).concat(extras.filter(m => !ms.some(x => x.key === m.key)));
    if (!ms.length) {
      const U = [['xgf_pct5', '5v5 xGF%', 'pct', false], ['cf_pct5', '5v5 CF%', 'pct', false], ['xgf_g', 'xGF / game', '2', false], ['xga_g', 'xGA / game', '2', true], ['gf_g', 'GF / game', '2', false], ['ga_g', 'GA / game', '2', true],
        ['gsax', 'Goalie GSAx', 'signed1', false], ['pp_gf', 'PP goals', 'int', false], ['pk_ga', 'PK goals against', 'int', true], ['pp_toi_g', 'PP min / game', '1', false], ['pk_toi_g', 'PK min / game', '1', true]];
      const uv = t => Object.assign({}, rows[t] || {}, ((TM[t] || {}).units) || {});
      const keys = U.filter(x => list.some(t => k.isNum(uv(t)[x[0]])));
      cols = head0.concat(keys.map(x => ({ label: x[1] + (x[3] ? ' ↓' : ''), align: 'right' })));
      const rkU = {};
      keys.forEach(x => { rkU[x[0]] = list.map(t => uv(t)[x[0]]).filter(k.isNum).sort((a, b) => (x[3] ? a - b : b - a)); });
      body = list.map((t, i) => ({ _href: k.teamHref(t, S), cells: [{ v: i + 1, cls: 'pos-cell' }].concat(base(t)).concat(keys.map(x => { const v = uv(t)[x[0]];
        return { v: k.isNum(v) ? (x[3] ? -v : v) : -1e9, html: k.isNum(v) ? k.fmtV(v, x[2]) + ' <span class="gf-rank">#' + (rkU[x[0]].indexOf(v) + 1) + '</span>' : '—', align: 'right' }; })) }));
    } else {
      cols = head0.concat(ms.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') })));
      body = list.map((t, i) => ({ _href: k.teamHref(t, S), cells: [{ v: i + 1, cls: 'pos-cell' }].concat(base(t)).concat(ms.map(m => vcell(TM[t], m))) }));
    }
  }
  k.set('tm-table', list.length ? k.table(cols, body, { compact: true, sticky: true }) : k.muted('No teams yet.'));
  k.sortable(k.$('tm-table'));
  k.set('tm-chips', extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + k.esc(m.key) + '">' + k.esc(m.label) + ' ×</button>').join(' ') : '');
  k.set('tm-sub', list.length + ' teams, ' + k.sLabel(S) + ' · ' + { units: 'unit ratings', under: 'underlying numbers', odds: 'season simulation' }[ST.view] + ' · sorted by rating; click a header to sort');
}

function chart(S, ids, TM, rows) {
  const k = K(), node = k.$('tm-chart');
  if (!node) return;
  const pts = ids.map(t => { const R = T.ratingsOf(TM[t], rows[t]); const od = T.oddsOf(rows[t], (rows[t] || {}).odds, (TM[t] || {}).sim); return { t: t, x: R.off, y: R.def, p: od.p_playoffs }; }).filter(p => k.isNum(p.x) && k.isNum(p.y));
  if (pts.length < 3) { k.empty(node, '5-on-5 unit ratings are not available yet.'); return; }
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  k.plot(node, [{ type: 'scatter', mode: 'markers+text', x: xs, y: ys, text: pts.map(p => p.t), textposition: 'top center', textfont: { size: 10, color: k.C.text2 },
    customdata: pts.map(p => k.teamHref(p.t, S)), hovertext: pts.map(p => k.esc(k.teamName(p.t)) + '<br>5v5 xGF/60 ' + k.num(p.x, 2) + ', xGA/60 ' + k.num(p.y, 2) + (k.isNum(p.p) ? '<br>playoffs ' + k.pct(p.p, 0) : '')), hoverinfo: 'text',
    marker: { size: pts.map(p => 9 + (k.isNum(p.p) ? 20 * p.p : 4)), color: pts.map(p => k.teamColour(p.t)), line: { color: '#0d1117', width: 1 } } }],
  k.layout({ margin: { l: 56, r: 12, t: 10, b: 46 }, xaxis: { title: '5v5 offence: xGF per 60', zeroline: false }, yaxis: { title: '5v5 defence: xGA per 60 (reversed: fewer is up)', zeroline: false, autorange: 'reversed' },
    shapes: [{ type: 'line', x0: k.median(xs), x1: k.median(xs), yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot' } }, { type: 'line', y0: k.median(ys), y1: k.median(ys), xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot' } }] }));
  k.clickThrough(node);
}

if (typeof RK.route === 'function') { try { RK.route('teams', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
