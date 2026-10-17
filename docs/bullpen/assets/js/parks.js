/* The Quant Bullpen — parks (#/parks) and one park (#/park/<vid>).
 *
 * Our own park factors (models/parks.py): contact factors by batter hand and outcome measured
 * against the park-neutral xwOBA+ expectation, runs by the home/road method, strikeout and walk
 * factors, all multi-year and regressed; the park's dimensions and walls; and what weather does
 * to carry and home runs. 100 = neutral.
 *
 * Data: data/<L>/<S>/parks.json ({"parks": {vid: {"name", "team", "dims", "elev_ft", "roof",
 * "factors": {...}, "weather": {...}}}, "effects": {"dimensions", "weather"}}). Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const OUT_LABEL = { '1B': 'Singles', '2B': 'Doubles', '3B': 'Triples', HR: 'Home runs', K: 'Strikeouts', BB: 'Walks', runs: 'Runs', woba_con: 'wOBA on contact', woba: 'wOBA', '1b': 'Singles', '2b': 'Doubles', '3b': 'Triples', hr: 'Home runs', k: 'Strikeouts', bb: 'Walks', so: 'Strikeouts', h: 'Hits', xbh: 'Extra-base hits',
  gb: 'Ground balls', fb: 'Fly balls', ld: 'Line drives', pu: 'Pop-ups', ground_ball: 'Ground balls', fly_ball: 'Fly balls', line_drive: 'Line drives', popup: 'Pop-ups', all: 'All', L: 'LHB', R: 'RHB', l: 'LHB', r: 'RHB', vl: 'LHB', vr: 'RHB' };
const ol = x => OUT_LABEL[x] || OUT_LABEL[String(x).toLowerCase()] || K().titleCase(x);
/* Factors are ratios (1.00 = neutral) or indices (100 = neutral): show them as indices. */
function idx(v) { return K().isNum(v) ? (Math.abs(v) < 5 ? 100 * v : Number(v)) : null; }
function pfCell(v) {
  const k = K(), x = idx(v);
  if (!k.isNum(x)) return { v: null, html: '—' };
  const d = Math.max(-1, Math.min(1, (x - 100) / 20));
  const bg = d > 0 ? 'rgba(239,68,68,' + (0.1 + 0.55 * d).toFixed(2) + ')' : 'rgba(59,130,246,' + (0.1 + 0.55 * -d).toFixed(2) + ')';
  return { v: x, html: '<span class="gq-pf" style="background:' + bg + '">' + Math.round(x) + '</span>', align: 'right' };
}
function parksOf(d) {
  if (!d || d.ok === false) return {};
  const P = d.parks || d.venues || d;
  if (Array.isArray(P)) { const o = {}; P.forEach(p => { if (p) o[String(p.vid || p.id || p.venue)] = p; }); return o; }
  const o = {};
  Object.keys(P || {}).forEach(v => { if (P[v] && typeof P[v] === 'object' && (P[v].name || P[v].factors || P[v].dims)) o[v] = P[v]; });
  return o;
}
function factorsOf(p) { return (p && (p.factors || p.pf || p.park_factors)) || {}; }
/* A flat headline value: factors.runs | factors.runs.all | factors.all.runs. */
function headlineF(p, key) {
  const k = K(), f = factorsOf(p);
  const want = String(key).toLowerCase();
  const hit = Object.keys(f).find(x => x.toLowerCase() === want);
  if (hit && k.isNum(f[hit])) return f[hit];
  if (hit && f[hit] && typeof f[hit] === 'object') { const v = k.val(f[hit], ['all', 'both']); if (k.isNum(v)) return v; }
  return null;
}

/* The whole factor table as a matrix: rows = outcomes (or batted-ball types), columns = batter hand. */
/* The factor table: rows = outcomes, columns = all batters, LHB, RHB (factors + by_hand). */
const OUT_ORDER = ['runs', 'woba_con', '1B', '2B', '3B', 'HR', 'K', 'BB'];
function parkFactorTable(p) {
  const k = K();
  const f = factorsOf(p), bh = (p && p.by_hand) || {};
  const outs = Array.from(new Set(Object.keys(f).concat([].concat.apply([], Object.keys(bh).map(h => Object.keys(bh[h] || {})))))).filter(o => k.isNum(f[o]) || Object.keys(bh).some(h => k.isNum((bh[h] || {})[o])));
  if (!outs.length) return k.muted('No factors for this park yet.');
  outs.sort((a, b) => (OUT_ORDER.indexOf(a) < 0 ? 99 : OUT_ORDER.indexOf(a)) - (OUT_ORDER.indexOf(b) < 0 ? 99 : OUT_ORDER.indexOf(b)));
  const hands = ['L', 'R'].filter(h => bh[h]);
  return k.table([{ label: 'Outcome' }, { label: 'All', align: 'right' }].concat(hands.map(h => ({ label: h === 'L' ? 'LHB' : 'RHB', align: 'right' }))),
    outs.map(o => [{ v: o, html: '<strong>' + k.esc(ol(o)) + '</strong>' }, pfCell(f[o])].concat(hands.map(h => pfCell((bh[h] || {})[o])))), { compact: true }) +
    '<div class="pg-note gq-note">100 = neutral; red helps hitters, blue helps pitchers. Contact factors (singles to home runs, wOBA on contact) compare actual outcomes with the park-neutral xwOBA+ expectation for the same batted balls, pooled over three seasons and regressed (1,000 pseudo-singles, 300 doubles, 60 triples, 250 home runs); runs use home against road scoring regressed with 160 games; strikeouts and walks 6,000 PA.' + (p && k.isNum(p.n_bip) ? ' ' + k.int(p.n_bip) + ' balls in play behind these.' : '') + '</div>';
}

(BP.gk = BP.gk || {}).parkFactorTable = parkFactorTable;

// ── list ───────────────────────────────────────────────────────────────────

function renderList(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">' + k.LN(L) + ' parks <span class="card-sub" id="pk-sub">Loading…</span></div><div id="pk-table"></div><div class="pg-note gq-note" id="pk-note"></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Home runs against runs <span class="card-sub">Each park\'s home-run factor against its run factor.</span></div><div id="pk-chart" style="height:400px"></div></div>' +
    '<div class="card"><div class="card-header">What the dimensions and weather do <span class="card-sub">Fitted across parks and games.</span></div><div id="pk-eff"></div></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return k.loadY(L, S, 'parks.json').then(d => ({ S: S, d: d }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, P = parksOf(o.d), ids = Object.keys(P), $ = id => document.getElementById(id);
    if (!ids.length) { $('pk-table').innerHTML = k.notBuilt('The ' + S + ' park factors', o.d); $('pk-sub').textContent = ''; $('pk-chart').innerHTML = ''; return; }
    const MAIN = [['runs', 'Runs'], ['HR', 'HR'], ['woba_con', 'wOBA con'], ['1B', '1B'], ['2B', '2B'], ['3B', '3B'], ['K', 'K'], ['BB', 'BB']];
    const cols = MAIN.filter(c => ids.some(v => k.isNum(headlineF(P[v], c[0]))));
    const hrHand = (p, h) => { const b = (p.by_hand || {})[h] || {}; return k.isNum(b.HR) ? b.HR : (k.isNum(b.hr) ? b.hr : null); };
    ids.sort((a, b) => (idx(headlineF(P[b], 'runs')) || 0) - (idx(headlineF(P[a], 'runs')) || 0));
    $('pk-table').innerHTML = k.table([{ label: 'Park' }, { label: 'Team' }].concat(cols.map(c => ({ label: c[1], align: 'right' }))).concat([{ label: 'HR LHB', align: 'right' }, { label: 'HR RHB', align: 'right' }, { label: 'R/G ' + S, align: 'right', title: 'Runs per game there this season (both teams)' }, { label: 'Elev.', align: 'right' }, { label: 'Roof' }, { label: 'LF · CF · RF', align: 'right' }]),
      ids.map(v => { const p = P[v], d = p.dims || {}; const tm = p.team || p.tid;
        return { _href: k.parkHref(v), cells: [{ v: p.name || k.parkName(v), html: '<a href="' + k.parkHref(v) + '">' + k.esc(p.name || k.parkName(v)) + '</a>' }, { v: tm ? k.teamAbbr(tm) : '', html: tm ? k.teamChip(L, tm, S) : '—' }]
          .concat(cols.map(c => pfCell(headlineF(p, c[0])))).concat([pfCell(hrHand(p, 'L')), pfCell(hrHand(p, 'R')), { v: (p.season || {}).runs_per_game, html: k.num((p.season || {}).runs_per_game, 2), align: 'right' }, { v: k.val(p, ['elev_ft', 'elevation']), html: k.isNum(k.val(p, ['elev_ft', 'elevation'])) ? k.int(k.val(p, ['elev_ft', 'elevation'])) + ' ft' : '—', align: 'right' },
            { v: p.roof || '', html: k.esc(p.roof || '—') }, { v: d.cf, html: k.isNum(d.lf) ? d.lf + ' · ' + d.cf + ' · ' + d.rf : '—', align: 'right' }]) }; }), { compact: true, sticky: true });
    k.sortable($('pk-table'));
    $('pk-sub').textContent = ids.length + ' parks · ' + ((o.d || {}).years ? 'seasons ' + o.d.years.join(', ') : S + ' (three seasons pooled)') + ' · sorted by run factor';
    $('pk-note').innerHTML = '100 = neutral; red helps hitters, blue helps pitchers. Contact factors (singles to home runs, wOBA on contact) compare actual outcomes with the park-neutral xwOBA+ expectation for the same batted balls, so they separate the park from the quality of contact hit there. Runs, strikeouts and walks use home against road rates. All are regressed towards neutral; see the <a href="#/methodology/parks">methodology</a>.';
    const pts = ids.map(v => ({ v: v, x: idx(headlineF(P[v], 'runs')), y: idx(headlineF(P[v], 'HR')) })).filter(p => k.isNum(p.x) && k.isNum(p.y));
    if (pts.length > 2) {
      k.plot('pk-chart', [{ type: 'scatter', mode: 'markers+text', x: pts.map(p => p.x), y: pts.map(p => p.y), text: pts.map(p => { const t = P[p.v].team || P[p.v].tid; return t ? k.teamAbbr(t) : String(P[p.v].name || '').split(' ')[0]; }),
        customdata: pts.map(p => p.v), textposition: 'top center', textfont: { size: 9, color: k.C.text2 }, hovertemplate: '%{customdata}: runs %{x:.0f}, HR %{y:.0f}<extra></extra>',
        marker: { size: 10, color: pts.map(p => (P[p.v].team ? k.teamColour(P[p.v].team) : '#58a6ff')), line: { color: '#0d1117', width: 1 } } }],
      k.layout({ margin: { l: 50, r: 10, t: 10, b: 44 }, xaxis: { title: 'Run factor', zeroline: false }, yaxis: { title: 'Home-run factor', zeroline: false },
        shapes: [{ type: 'line', x0: 100, x1: 100, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot' } }, { type: 'line', y0: 100, y1: 100, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot' } }] }));
      const node = $('pk-chart');
      if (node && node.on) node.on('plotly_click', ev => { const v = ev.points && ev.points[0] && ev.points[0].customdata; if (v) location.hash = k.parkHref(v); });
    } else $('pk-chart').innerHTML = k.muted('Not enough parks with both factors.');
    $('pk-eff').innerHTML = effects({ dimensions: (o.d || {}).dimension_effects || ((o.d || {}).effects || {}).dimensions, weather: (o.d || {}).weather_effects || ((o.d || {}).effects || {}).weather });
  });
}

/* Dimension and weather regressions: {dimensions: {hr: {fence_10ft, wall_10ft, elev_1000ft}, ...}, weather: {carry: {temp_10f, wind_mph}, hr: {...}}}. */
/* E's dimension effects {n, terms, HR: [b0, b_fence, b_wall, b_elev], woba_con: [...], 2B: [...]} and weather effects
 * {n, carry_ft: {per_10F, per_mph_out, se}, hr_prob: {...}}. */
function effects(e) {
  const k = K();
  let h = '';
  const d = e.dimensions;
  if (d && d.terms) {
    const outs = ['HR', 'woba_con', '2B'].filter(o => Array.isArray(d[o]));
    if (outs.length) h += '<div class="gq-sub-head">Dimensions (' + k.int(d.n) + ' parks)</div>' + k.table([{ label: 'Factor' }, { label: 'Per 10 ft of fence', align: 'right' }, { label: 'Per 10 ft of wall', align: 'right' }, { label: 'Per 1,000 ft up', align: 'right' }],
      outs.map(o => [{ v: o, html: '<strong>' + k.esc(ol(o)) + '</strong>' }].concat([1, 2, 3].map(j => ({ v: d[o][j], html: k.isNum(d[o][j]) ? k.signed(100 * d[o][j], 1) + ' pts' : '—' })))), { compact: true });
  }
  const w = e.weather;
  if (w && (w.carry_ft || w.hr_prob)) {
    h += '<div class="gq-sub-head">Weather (' + k.int(w.n) + ' hard-hit air balls)</div>' + k.table([{ label: 'Effect on' }, { label: 'Per 10 °F warmer', align: 'right' }, { label: 'Per mph blowing out', align: 'right' }],
      [['carry_ft', 'Carry (ft)', 1], ['hr_prob', 'Home-run probability', 100]].filter(x => w[x[0]]).map(x => [{ v: x[1], html: '<strong>' + x[1] + '</strong>' },
        { v: w[x[0]].per_10F, html: k.isNum(w[x[0]].per_10F) ? k.signed(x[2] * w[x[0]].per_10F, 2) + (x[2] === 100 ? ' pp' : ' ft') : '—' }, { v: w[x[0]].per_mph_out, html: k.isNum(w[x[0]].per_mph_out) ? k.signed(x[2] * w[x[0]].per_mph_out, 2) + (x[2] === 100 ? ' pp' : ' ft') : '—' }]), { compact: true });
  }
  return h ? h + '<div class="pg-note gq-note">Dimensions: least squares across parks of each factor (as an index, 100 = neutral) on mean fence distance (from 375 ft), wall height (from 8 ft) and elevation. Weather: residual carry and home-run probability of hard-hit air balls (launch angle 15–45°, 95+ mph) on temperature and wind blowing out, park means removed, domes and closed roofs excluded.</div>'
    : k.muted('The dimension and weather fits are not published yet.');
}

// ── one park ───────────────────────────────────────────────────────────────

function renderOne(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  const vid = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return k.loadY(L, S, 'parks.json').then(d => ({ S: S, d: d }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, P = parksOf(o.d), p = P[vid];
    const info = Object.assign({}, k.park(vid), p || {});
    if (!p && !info.name) { el.innerHTML = k.card('Park', '', k.notBuilt('The page for ' + k.parkName(vid), o.d) + '<div class="pg-note gq-note"><a href="#/parks">All parks →</a></div>'); return; }
    const tm = info.team || info.tid || Object.keys(k.TEAMS).find(t => String(k.TEAMS[t].venue) === vid && (!k.TEAMS[t].level || k.TEAMS[t].level === L));
    const d = info.dims || info.dimensions || {};
    const sub = [tm ? k.teamChip(L, tm, S) : '', info.city ? '<span>' + k.esc(info.city + (info.state ? ', ' + info.state : '')) + '</span>' : '', info.roof ? '<span class="chip">' + k.esc(info.roof) + '</span>' : '', info.turf ? '<span>' + k.esc(info.turf) + '</span>' : '',
      k.isNum(info.capacity) ? '<span>' + k.int(info.capacity) + ' seats</span>' : ''].filter(Boolean).join(' ');
    let h = k.head(k.esc(info.name || k.parkName(vid)), sub, '<a href="#/parks">All parks →</a>' + (tm ? '<a href="' + k.teamHref(L, tm, S) + '">' + k.esc(k.teamName(tm)) + ' →</a>' : ''), 'PARK', tm ? k.teamColour(tm) : null);
    const F = [['runs', 'Run factor'], ['hr', 'Home-run factor'], ['woba_con', 'wOBA on contact'], ['2b', 'Doubles'], ['3b', 'Triples'], ['k', 'Strikeouts']];
    const tiles = F.map(x => { const v = headlineF(info, x[0]); return k.isNum(v) ? k.tile(x[1], String(Math.round(idx(v))), idx(v) > 100.5 ? 'favours hitters' : idx(v) < 99.5 ? 'favours pitchers' : 'neutral') : ''; }).filter(Boolean);
    tiles.push(k.tile('Elevation', k.isNum(k.val(info, ['elev_ft', 'elevation'])) ? k.int(k.val(info, ['elev_ft', 'elevation'])) + ' <span class="kpi-dim">ft</span>' : '—', 'thinner air carries farther'));
    tiles.push(k.tile('Fences', k.isNum(d.lf) ? d.lf + ' · ' + (d.lcf || '—') + ' · ' + d.cf + ' · ' + (d.rcf || '—') + ' · ' + d.rf : '—', 'LF · LCF · CF · RCF · RF (ft)'));
    h += k.tiles(tiles);
    h += '<div class="grid-2"><div class="card"><div class="card-header">The field <span class="card-sub">Fence line from the five published distances (catcher\'s view from behind home plate)' + (info.walls ? ', wall heights where known' : '') + '.</span></div><div id="pk-field" class="gq-spray"></div>' + walls(info.walls) + '</div>' +
      '<div class="card"><div class="card-header">Factors by hand and outcome</div>' + parkFactorTable(info) + '</div></div>';
    h += '<div class="card"><div class="card-header">Weather here <span class="card-sub">How temperature and wind move carry and home runs in this park, and the conditions it usually plays in.</span></div><div id="pk-wx"></div></div>';
    el.innerHTML = h;
    k.spray('pk-field', [], d, { fieldOnly: true });
    weather(document.getElementById('pk-wx'), Object.assign({}, info.weather || {}, info.season || {}), { weather: (o.d || {}).weather_effects }, info);
    if (typeof BP.setMeta === 'function') { try { BP.setMeta(k.esc(info.name || '')); } catch (e) { /* optional */ } }
  });
}
function walls(w) {
  const k = K();
  if (!w || typeof w !== 'object') return '';
  const keys = Object.keys(w).filter(x => k.isNum(w[x]));
  return keys.length ? '<div class="pg-note gq-note">Wall heights: ' + keys.map(x => k.esc(x.toUpperCase()) + ' ' + w[x] + ' ft').join(' · ') + '</div>' : '';
}
function weather(host, wx, eff, info) {
  const k = K();
  if (!host) return;
  let h = '';
  const tiles = [];
  if (k.isNum(wx.runs_per_game)) tiles.push(k.tile('Runs per game here', k.num(wx.runs_per_game, 2), k.isNum(wx.games) ? k.int(wx.games) + ' regular-season games this season' : ''));
  if (info && k.isNum(info.azimuth)) tiles.push(k.tile('Orientation', k.int(info.azimuth) + '°', 'home plate to centre field, from north'));
  if (info && info.roof) tiles.push(k.tile('Roof', k.esc(info.roof), /dome|closed|retract/i.test(info.roof) ? 'weather effects are off when it is closed' : 'open air'));
  if (tiles.length) h += '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>';
  const w = eff && eff.weather;
  if (w && (w.carry_ft || w.hr_prob)) {
    const c = w.carry_ft || {}, r = w.hr_prob || {};
    h += '<div class="pg-note gq-note">League-wide, a hard-hit air ball carries ' + k.signed(c.per_10F, 1) + ' ft per 10 °F warmer and ' + k.signed(c.per_mph_out, 2) + ' ft per mph of wind blowing out; its home-run probability moves ' + k.signed(100 * (r.per_10F || 0), 2) + ' and ' + k.signed(100 * (r.per_mph_out || 0), 2) + ' percentage points. The game model prices weather separately: about 1.1% more home-run odds per °F above 70 and 1.8% per mph straight out (out to left or right 0.8), neutral under a closed roof.</div>';
  }
  host.innerHTML = h || k.muted('No weather effects published for this park yet.');
}

if (typeof BP.route === 'function') {
  [['parks', renderList], ['#/parks', renderList], ['park', renderOne], ['#/park/<vid>', renderOne]].forEach(r => { try { BP.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.BP || (window.BP = {}));
