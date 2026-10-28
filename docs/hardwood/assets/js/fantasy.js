/* The Quant Hardwood — fantasy (#/<L>/fantasy): projections per game, for the rest of the season and for the next
 * two fantasy weeks, in 9-category (with punts) or points formats (presets or your own weights); rankings with
 * tiers and value over replacement by position; schedule and streaming; buy-low / sell-high from shooting luck;
 * waiver targets; "our picks"; and the walk-forward check of the projections.
 *
 * Data: data/<L>/<S>/fantasy.json (analytics/fantasy.py). Rows: cols + pg (per game: pg_cols), ros (rest-of-season
 * totals: tot_cols), weeks (per fantasy week: week_cols), luck (luck_cols). 9-category z-scores and points are
 * computed here from those projections, so punts and weights change the ranks instantly. Our own projections
 * only: no fantasy platform's rankings, ownership or ADP (their terms do not allow reuse). */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const CATS = ['pts', 'reb', 'ast', 'stl', 'blk', 'tpm', 'fg', 'ft', 'tov'];
const LAB = { pts: 'PTS', reb: 'REB', ast: 'AST', stl: 'STL', blk: 'BLK', tpm: '3PM', fg: 'FG%', ft: 'FT%', tov: 'TO' };
const WKEYS = ['pts', 'tpm', 'fgm', 'fga', 'ftm', 'fta', 'reb', 'ast', 'stl', 'blk', 'tov', 'dd', 'td'];
const ROSTER = { G: 4, F: 4, C: 2 };              // starters per position in a 12-team league (replacement line)
const ST = { fmt: '9cat', hz: 'pg', punt: {}, pos: 'all', team: 'all', q: '', n: '50', w: null };

function obj(cols, arr) { const o = {}; (cols || []).forEach((c, i) => { o[c] = arr ? arr[i] : null; }); return o; }

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    const S = fx.current(L) || fx.S(params, state, L);
    const q = (params && params.query) || {};
    if (q.fmt) ST.fmt = q.fmt;
    if (q.hz) ST.hz = q.hz;
    if (q.punt) { ST.punt = {}; String(q.punt).split(',').forEach(c => { if (CATS.indexOf(c) >= 0) ST.punt[c] = true; }); }
    return HW.load(fx.path(L, S, 'fantasy.json')).then(d => {
      if (!fx.alive(el)) return;
      if (!fx.ok(d) || !d.rows) { el.innerHTML = fx.card('Fantasy', '', fx.notBuilt('Fantasy projections for ' + fx.seasonLabel(L, S), d)); return; }
      page(el, L, S, d);
    });
  });
}

function players(d) {
  return d.rows.map(r => {
    const x = obj(d.cols, r);
    x.pgo = obj(d.pg_cols, x.pg);
    x.roso = obj(d.tot_cols, x.ros);
    x.wk = (x.weeks || []).map(w => obj(d.week_cols, w));
    x.lk = x.luck ? obj(d.luck_cols, x.luck) : null;
    x.posG = String(x.pos || 'F').charAt(0).toUpperCase();
    return x;
  });
}

function statsOf(x) {
  if (ST.hz === 'pg') return x.pgo;
  if (ST.hz === 'ros') return x.roso;
  const k = ST.hz === 'w1' ? 1 : 0;
  return x.wk[k] || {};
}
function gamesOf(x) {
  if (ST.hz === 'pg') return 1;
  if (ST.hz === 'ros') return x.xgp;
  const w = x.wk[ST.hz === 'w1' ? 1 : 0];
  return w ? w.xgp : 0;
}

/* 9-category z-scores over the top POOL players (re-picked twice); percentages weighted by attempts. */
function nineCat(list, cats, pool) {
  const X = {};
  CATS.forEach(c => { X[c] = list.map(() => 0); });
  const st = list.map(statsOf);
  ['pts', 'reb', 'ast', 'stl', 'blk', 'tpm', 'tov'].forEach(c => { X[c] = st.map(s => Number(s[c] || 0)); });
  let idx = list.map((_, i) => i).sort((a, b) => (X.pts[b] + X.reb[b] + X.ast[b]) - (X.pts[a] + X.reb[a] + X.ast[a])).slice(0, pool);
  let z = {};
  for (let it = 0; it < 2; it++) {
    let fgm = 0, fga = 0, ftm = 0, fta = 0;
    idx.forEach(i => { fgm += Number(st[i].fgm || 0); fga += Number(st[i].fga || 0); ftm += Number(st[i].ftm || 0); fta += Number(st[i].fta || 0); });
    const fp = fga ? fgm / fga : 0.47, tp = fta ? ftm / fta : 0.78;
    X.fg = st.map(s => Number(s.fgm || 0) - fp * Number(s.fga || 0));
    X.ft = st.map(s => Number(s.ftm || 0) - tp * Number(s.fta || 0));
    z = {};
    CATS.forEach(c => {
      const v = idx.map(i => X[c][i]);
      const mu = v.reduce((a, b) => a + b, 0) / Math.max(1, v.length);
      const sd = Math.sqrt(v.reduce((a, b) => a + (b - mu) * (b - mu), 0) / Math.max(1, v.length)) || 1;
      z[c] = X[c].map(x => (x - mu) / sd * (c === 'tov' ? -1 : 1));
    });
    const tot = list.map((_, i) => cats.reduce((a, c) => a + z[c][i], 0));
    idx = list.map((_, i) => i).sort((a, b) => tot[b] - tot[a]).slice(0, pool);
  }
  return list.map((_, i) => { const o = {}; CATS.forEach(c => { o[c] = z[c][i]; }); o.total = cats.reduce((a, c) => a + z[c][i], 0); return o; });
}

function pointsOf(s, w) { let t = 0; Object.keys(w).forEach(k => { t += Number(w[k] || 0) * Number(s[k] || 0); }); return t; }

function tiers(vals) {
  const gaps = [];
  for (let i = 0; i + 1 < vals.length; i++) gaps.push(vals[i] - vals[i + 1]);
  const pos = gaps.filter(g => g > 0).sort((a, b) => a - b);
  const med = pos.length ? pos[Math.floor(pos.length / 2)] : 0;
  const out = [];
  let t = 1, size = 0;
  vals.forEach((v, i) => { out.push(t); size++; if (i < gaps.length && med > 0 && gaps[i] > 1.6 * med && size >= 3) { t++; size = 0; } });
  return out;
}

function page(el, L, S, d) {
  const fx = FX();
  const P = players(d);
  const byId = {}; P.forEach(x => { byId[x.id] = x; });
  if (!ST.w) ST.w = Object.assign({}, (d.presets.standard || {}).w || {});
  const weeks = d.weeks || [];
  const wl = i => (weeks[i] ? fx.fmtDate(weeks[i][0]) + '–' + fx.fmtDate(weeks[i][1]) : 'week ' + (i + 1));
  const target = d.season_over ? 'the ' + fx.seasonLabel(L, d.target) + ' season (way-too-early: last season\'s rates, today\'s rosters)' : fx.seasonLabel(L, d.season);
  let h = '<div class="card"><div class="card-header">Fantasy ' + fx.esc(fx.seasonLabel(L, d.target)) + ' <span class="card-sub">Projections for ' + fx.esc(target) + ' from our models: per-minute rates from the impact model (this season and last, recent games weighted, shrunk to the position), minutes from each team\'s depth chart with the injury report applied, usage redistributed while teammates are out, pace, the opponent\'s category defence, back-to-backs and rest, and availability. Our own numbers only: <strong>no fantasy platform rankings, ownership or ADP</strong> (their terms do not allow reuse). <a href="#/methodology">Methodology</a></span></div>';
  h += '<div class="lab-controls hf-controls fn-ctl">' +
    '<label>Format<select id="fn-fmt"><option value="9cat">9-category</option>' + Object.keys(d.presets || {}).map(k => '<option value="' + fx.esc(k) + '">' + fx.esc(d.presets[k].label) + '</option>').join('') + '<option value="custom">Points: my weights</option></select></label>' +
    '<label>Horizon<select id="fn-hz"><option value="pg">Per game</option>' + (d.season_over ? '<option value="ros">Next season</option>' : '<option value="ros">Rest of season</option>' +
      (weeks[0] ? '<option value="w0">Week ' + fx.esc(wl(0)) + '</option>' : '') + (weeks[1] ? '<option value="w1">Week ' + fx.esc(wl(1)) + '</option>' : '')) + '</select></label>' +
    '<label>Position<select id="fn-pos"><option value="all">All</option><option value="G">G</option><option value="F">F</option><option value="C">C</option></select></label>' +
    '<label>Search<input id="fn-q" type="search" placeholder="Player"></label>' +
    '<label>Show<select id="fn-n"><option value="50">Top 50</option><option value="150">Top 150</option><option value="0">All</option></select></label></div>' +
    '<div class="fn-punts" id="fn-punts"></div><div class="fn-weights" id="fn-w"></div></div>';
  /* round 9: the number, then the chart, then the table (Fantasy ▸ Rankings & tools rebuilt on the house order) */
  h += '<div class="hw-kpis" id="fn-kpis"></div>';
  h += '<div class="card"><div class="card-header">The top of the board <span class="card-sub">The top 20 in the format and horizon above; the bar is the player’s value, tiers alternate in colour</span></div><div id="fn-chart" class="qk-chart" style="--h:520px" role="img" aria-label="The top 20 by fantasy value"></div></div>';
  h += '<div class="card"><div class="card-header">Rankings and tiers <span class="card-sub" id="fn-sub"></span></div><div id="fn-table"></div><div class="pg-note" id="fn-note"></div></div>';
  h += '<div class="card"><div class="card-header">Our picks <span class="card-sub">Built from the default formats (9-category per game and standard points); each with the reason from the data.</span></div><div class="fn-picks" id="fn-picks"></div></div>';
  h += '<div class="card"><div class="card-header">Value over replacement by position <span class="card-sub">The replacement line is the ' + Object.keys(ROSTER).map(k => (12 * ROSTER[k]) + 'th ' + k).join(', ') + ' (12 teams starting ' + Object.keys(ROSTER).map(k => ROSTER[k] + ' ' + k).join(', ') + ', ESPN positions); value over it in the chosen format and horizon.</span></div><div class="grid-3" id="fn-vorp"></div></div>';
  if (!d.season_over) h += '<div class="card"><div class="card-header">Schedule and streaming <span class="card-sub">Games per fantasy week (Monday–Sunday, US dates), back-to-backs, light-slate games (days with ' + fx.num((d.constants || {}).light_day, 0) + ' or fewer games, when more fantasy teams have open slots) and the average opponent factor for points (pace × points allowed, 1.00 = league average).</span></div><div id="fn-sched"></div></div>';
  h += '<div class="card"><div class="card-header">Buy low, sell high <span class="card-sub">Shooting luck this season in points a game: points per shot against the shot model\'s expected points per shot plus the player\'s own shot-making over the two previous seasons (shrunk with ' + fx.num((d.constants || {}).shot_k, 0) + ' pseudo-shots), and free throws against the previous percentage. Negative: shooting below what the shots and history predict (buy low); positive: above (sell high).</span></div><div id="fn-luck"></div></div>';
  h += '<details class="hw-fold"><summary>How good are these projections? The walk-forward test</summary><div class="card"><div class="card-header">How good are these projections? <span class="card-sub">Walk-forward on completed seasons: at weekly checkpoints, projections from games before the checkpoint only, scored against what happened.</span></div><div id="fn-bt"></div></div></details>';
  el.innerHTML = h;
  const $ = id => document.getElementById(id);
  $('fn-fmt').value = ST.fmt; $('fn-hz').value = (d.season_over && ST.hz !== 'pg') ? 'ros' : ST.hz; ST.hz = $('fn-hz').value; $('fn-pos').value = ST.pos; $('fn-n').value = ST.n;
  const go = () => { syncUrl(L); controls(); table(); vorp(); };
  $('fn-fmt').onchange = e => { ST.fmt = e.target.value; if (d.presets[ST.fmt]) ST.w = Object.assign({}, d.presets[ST.fmt].w); go(); };
  $('fn-hz').onchange = e => { ST.hz = e.target.value; go(); };
  $('fn-pos').onchange = e => { ST.pos = e.target.value; table(); };
  $('fn-q').oninput = e => { ST.q = e.target.value; table(); };
  $('fn-n').onchange = e => { ST.n = e.target.value; table(); };

  function controls() {
    $('fn-punts').innerHTML = ST.fmt === '9cat' ? '<span class="muted-inline">Punt:</span> ' + CATS.map(c => '<label class="fn-chk"><input type="checkbox" data-c="' + c + '"' + (ST.punt[c] ? ' checked' : '') + '> ' + LAB[c] + '</label>').join(' ') : '';
    $('fn-punts').querySelectorAll('input').forEach(i => { i.onchange = e => { ST.punt[e.target.dataset.c] = e.target.checked; if (!e.target.checked) delete ST.punt[e.target.dataset.c]; syncUrl(L); table(); vorp(); }; });
    $('fn-w').innerHTML = ST.fmt !== '9cat' ? '<span class="muted-inline">Points per:</span> ' + WKEYS.map(k => '<label class="fn-wt">' + k.toUpperCase() + ' <input type="number" step="0.25" data-k="' + k + '" value="' + (ST.w[k] === undefined ? 0 : ST.w[k]) + '"></label>').join(' ') : '';
    $('fn-w').querySelectorAll('input').forEach(i => { i.onchange = e => { ST.w[e.target.dataset.k] = Number(e.target.value) || 0; ST.fmt = d.presets[ST.fmt] && JSON.stringify(ST.w) === JSON.stringify(d.presets[ST.fmt].w) ? ST.fmt : 'custom'; $('fn-fmt').value = ST.fmt; table(); vorp(); }; });
  }
  function valued() {
    const cats = CATS.filter(c => !ST.punt[c]);
    if (ST.fmt === '9cat') {
      const z = nineCat(P, cats, (d.constants || {}).pool_n || 156);
      return P.map((x, i) => ({ x: x, v: z[i].total, z: z[i] }));
    }
    return P.map(x => ({ x: x, v: pointsOf(statsOf(x), ST.w) }));
  }
  function table() {
    const all = valued().sort((a, b) => b.v - a.v);
    all.forEach((r, i) => { r.rank = i + 1; });
    const tv = tiers(all.slice(0, 250).map(r => r.v));
    all.forEach((r, i) => { r.tier = i < tv.length ? tv[i] : null; });
    const repl = replacement(all);
    const q = ST.q.toLowerCase();
    let list = all.filter(r => (ST.pos === 'all' || r.x.posG === ST.pos) && (!q || String(r.x.name).toLowerCase().indexOf(q) >= 0));
    const total = list.length;
    if (Number(ST.n) > 0) list = list.slice(0, Number(ST.n));
    const hzl = { pg: 'per game', ros: d.season_over ? 'next season' : 'rest of season', w0: 'week ' + wl(0), w1: 'week ' + wl(1) }[ST.hz];
    $('fn-sub').textContent = total + ' players · ' + (ST.fmt === '9cat' ? '9-category' + (Object.keys(ST.punt).length ? ', punting ' + Object.keys(ST.punt).map(c => LAB[c]).join(', ') : '') : (d.presets[ST.fmt] ? d.presets[ST.fmt].label : 'my points')) + ' · ' + hzl;
    const nine = ST.fmt === '9cat';
    const cols = [{ label: '#', align: 'right' }, { label: 'Tier', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'Min', align: 'right', title: 'Projected minutes a game (depth chart)' },
      { label: 'G', align: 'right', title: 'Expected games played in the horizon' }];
    const sc = nine ? CATS.map(c => ({ label: LAB[c], align: 'right', title: 'z-score' + (ST.punt[c] ? ' (punted)' : '') })) : [{ label: 'PTS', align: 'right' }, { label: 'REB', align: 'right' }, { label: 'AST', align: 'right' }, { label: 'STL', align: 'right' }, { label: 'BLK', align: 'right' }, { label: '3PM', align: 'right' }, { label: 'TO', align: 'right' }];
    const tail = [{ label: nine ? 'Total z' : 'Points', align: 'right' }, { label: 'VORP', align: 'right', title: 'Value over the replacement line at the position' }, { label: 'Start rank', align: 'right', title: 'Our 9-category rank at the season start (waiver proxy)' }];
    const nd = ST.hz === 'pg' ? 1 : 0;
    $('fn-table').innerHTML = list.length ? HW.tableHTML(cols.concat(sc, tail), list.map(r => {
      const x = r.x, s = statsOf(x);
      const cells = [r.rank, r.tier || '', { v: x.name, html: fx.playerLink(L, x.id, x.name) + (x.inj ? ' <span class="chip red" title="' + fx.esc(x.inj + (x.ret ? ', return ' + x.ret : '')) + '">' + fx.esc(String(x.inj).slice(0, 3)) + '</span>' : '') },
        { v: fx.teamAbbr(L, x.team), html: fx.teamLink(L, x.team, { abbr: true }) }, fx.esc(x.pos || ''), { v: x.age, html: fx.num(x.age, 0) }, { v: x.mpg, html: fx.num(x.mpg, 1) }, { v: gamesOf(x), html: fx.num(gamesOf(x), ST.hz === 'pg' ? 0 : 1) }];
      const stat = nine ? CATS.map(c => ({ v: r.z[c], html: '<span class="' + (ST.punt[c] ? 'muted-inline' : r.z[c] > 0.5 ? 'pg-up' : r.z[c] < -0.5 ? 'pg-down' : '') + '">' + fx.signed(r.z[c], 1) + '</span>' }))
        : ['pts', 'reb', 'ast', 'stl', 'blk', 'tpm', 'tov'].map(k => ({ v: s[k], html: fx.num(s[k], nd) }));
      const vr = repl[x.posG];
      return { _class: r.tier && r.tier % 2 === 0 ? 'fn-tier-alt' : '', cells: cells.concat(stat, [{ v: r.v, html: '<strong>' + fx.num(r.v, nine ? 2 : nd) + '</strong>' }, { v: fx.isNum(vr) ? r.v - vr : null, html: fx.isNum(vr) ? fx.signed(r.v - vr, nine ? 2 : nd) : '—' },
        { v: x.rank_pre, html: fx.num(x.rank_pre, 0) }]) };
    }), { compact: true, sticky: true }) : fx.muted('No players match.');
    HW.sortable('fn-table');
    const top = all.filter(r => ST.pos === 'all' || r.x.posG === ST.pos).slice(0, 20);
    const kp = document.getElementById('fn-kpis');
    if (kp && top[0]) kp.innerHTML = QK.stats([{ label: 'Number one', value: top[0].x.name, text: true, signal: true, href: fx.playerHref(L, top[0].x.id), sub: fx.teamAbbr(L, top[0].x.team) + ' · ' + (nine ? 'total z ' + fx.num(top[0].v, 2) : fx.num(top[0].v, nd) + ' points') + ' · ' + hzl },
      top[1] ? { label: 'Number two', value: top[1].x.name, text: true, sub: fx.teamAbbr(L, top[1].x.team) + ' · ' + (nine ? 'total z ' + fx.num(top[1].v, 2) : fx.num(top[1].v, nd) + ' points') } : null,
      { label: 'Tier one', value: String(all.filter(r => r.tier === 1).length), sub: 'players before the first big drop' }]);
    if (top.length) QKC.bar('#fn-chart', { cats: top.map(r => r.x.name), series: [{ name: nine ? 'Total z' : 'Points', data: top.map(r => Math.round(r.v * 100) / 100) }], horizontal: true, labels: true,
      colors: top.map(r => (r.tier || 1) % 2 ? QK.cssVar('--c-1') : QK.cssVar('--c-3')), fmt: v => fx.num(v, nine ? 2 : nd), labelWidth: 150, valName: nine ? 'Total z-score (9 categories)' : 'Fantasy points', catName: 'Player',
      hrefs: top.map(r => fx.playerHref(L, r.x.id)) });
    $('fn-note').innerHTML = 'Tiers start where the gap to the next player is more than 1.6 times the median gap (at least three players a tier). 9-category: per-game z-scores (or z-scores of totals for longer horizons) against the top ' + fx.num((d.constants || {}).pool_n, 0) + ' players, FG% and FT% weighted by attempts, turnovers counted negatively. Start rank: our rank before the season\'s first game; players outside the top ' + fx.num((d.constants || {}).waiver_line, 0) + ' then are the waiver proxy (we have no ownership data).';
  }
  function replacement(all) {
    const out = {};
    Object.keys(ROSTER).forEach(k => { const g = all.filter(r => r.x.posG === k); const r = g[Math.min(g.length - 1, 12 * ROSTER[k] - 1)]; out[k] = r ? r.v : null; });
    return out;
  }
  function vorp() {
    const all = valued().sort((a, b) => b.v - a.v);
    const repl = replacement(all);
    $('fn-vorp').innerHTML = Object.keys(ROSTER).map(k => '<div><div class="vl-best-h">' + k + ' · line ' + fx.num(repl[k], 2) + '</div>' + HW.tableHTML([{ label: 'Player' }, { label: 'VORP', align: 'right' }],
      all.filter(r => r.x.posG === k).slice(0, 8).map(r => [{ v: r.x.name, html: fx.playerLink(L, r.x.id, r.x.name) + ' <span class="muted-inline">' + fx.esc(fx.teamAbbr(L, r.x.team)) + '</span>' }, { v: r.v - repl[k], html: fx.signed(r.v - repl[k], 2) }]), { compact: true }) + '</div>').join('');
  }
  // picks
  const pk = d.picks || {};
  const PL = [['core', 'Core (9-category)'], ['points', 'Points (standard)'], ['breakouts', 'Breakouts'], ['buy_low', 'Buy low'], ['sell_high', 'Sell high'], ['adds', 'Waiver targets'],
    ['drops', 'Drop candidates'], ['streamers', 'Streamers'], ['punt_fg', 'Punt FG%'], ['punt_ft', 'Punt FT%'], ['punt_tov', 'Punt TO']];
  $('fn-picks').innerHTML = PL.filter(p => (pk[p[0]] || []).length).map(p => '<div class="fn-pick"><div class="vl-best-h">' + fx.esc(p[1]) + '</div><ol>' +
    pk[p[0]].slice(0, 6).map(r => { const x = byId[r[0]] || {}; return '<li>' + fx.playerLink(L, r[0], x.name) + ' <span class="muted-inline">' + fx.esc(fx.teamAbbr(L, x.team)) + '</span><div class="vl-why">' + fx.esc(r[1]) + '</div></li>'; }).join('') + '</ol></div>').join('') ||
    '<div class="pad">' + fx.muted('No picks yet.') + '</div>';
  if (!d.started && !d.season_over) $('fn-picks').insertAdjacentHTML('beforeend', '<div class="pad">' + fx.muted('Buy-low, sell-high, waiver and drop lists appear once the regular season has games.') + '</div>');
  // schedule
  if (!d.season_over) {
    const tw = d.teams || {};
    const tids = Object.keys(tw).sort((a, b) => ((tw[b].weeks[0] || [])[0] || 0) - ((tw[a].weeks[0] || [])[0] || 0) || ((tw[b].weeks[1] || [])[0] || 0) - ((tw[a].weeks[1] || [])[0] || 0));
    const wc = weeks.map((w, i) => ({ label: wl(i), align: 'center', title: 'games · back-to-backs · light-slate games · opponent factor' }));
    $('fn-sched').innerHTML = HW.tableHTML([{ label: 'Team' }].concat(wc, [{ label: 'Left', align: 'right' }]), tids.map(t => [{ v: fx.teamName(L, t), html: fx.teamLink(L, t, { abbr: true }) }].concat(
      weeks.map((w, i) => { const x = tw[t].weeks[i] || []; return { v: x[0], html: '<strong>' + fx.num(x[0], 0) + '</strong> <span class="muted-inline">' + (x[1] ? x[1] + ' b2b · ' : '') + (x[2] ? x[2] + ' light · ' : '') + fx.num(x[3], 2) + '</span>' }; }),
      [tw[t].left])), { compact: true });
    HW.sortable('fn-sched');
  }
  // luck
  const lk = P.filter(x => x.lk && fx.isNum(x.lk.luck)).sort((a, b) => a.lk.luck - b.lk.luck);
  $('fn-luck').innerHTML = lk.length ? HW.tableHTML([{ label: 'Player' }, { label: 'Team' }, { label: 'Luck pts/g', align: 'right' }, { label: 'Shot-making luck', align: 'right' }, { label: '3P luck', align: 'right' }, { label: 'FT luck', align: 'right' }, { label: '3P%', align: 'right' }, { label: 'Expected 3P%', align: 'right' }, { label: 'Call' }],
    lk.filter(x => Math.abs(x.lk.luck) >= 0.5).slice(0, 15).concat(lk.filter(x => Math.abs(x.lk.luck) >= 0.5).slice(-15).reverse()).filter((x, i, a) => a.indexOf(x) === i).map(x => [{ v: x.name, html: fx.playerLink(L, x.id, x.name) }, { v: fx.teamAbbr(L, x.team), html: fx.teamLink(L, x.team, { abbr: true }) },
      { v: x.lk.luck, html: '<strong>' + fx.signed(x.lk.luck, 1) + '</strong>' }, { v: x.lk.pps_luck, html: fx.signed(x.lk.pps_luck, 1) }, { v: x.lk.tp_luck, html: fx.signed(x.lk.tp_luck, 1) }, { v: x.lk.ft_luck, html: fx.signed(x.lk.ft_luck, 1) },
      { v: x.lk.fg3, html: fx.pct(x.lk.fg3) }, { v: x.lk.fg3_exp, html: fx.pct(x.lk.fg3_exp) }, x.lk.luck <= -((d.constants || {}).luck_line || 1) ? '<span class="chip ok">buy low</span>' : x.lk.luck >= ((d.constants || {}).luck_line || 1) ? '<span class="chip red">sell high</span>' : '']), { compact: true })
    : '<div class="pad">' + fx.muted(d.season_over ? 'The season is over.' : 'Shooting luck needs at least five games of this season.') + '</div>';
  HW.sortable('fn-luck');
  backtest(d.backtest);
  controls(); table(); vorp();

  function backtest(bt) {
    const box = $('fn-bt');
    const s = bt && bt.summary;
    if (!s) { box.innerHTML = '<div class="pad">' + fx.muted('The backtest has not been run for this league yet.') + '</div>'; return; }
    const rows = [];
    Object.keys(s).forEach(hz => {
      const m = s[hz];
      ['ours', 'season_to_date', 'last_season'].forEach(k => { if (m[k]) rows.push([{ next_week: 'Next 7 days (per game played)', next_week_total: 'Next 7 days (total, availability included)', ros: 'Rest of season (per game)' }[hz] || hz,
        { ours: '<strong>Ours</strong>', season_to_date: 'Season to date', last_season: 'Last season' }[k], { v: m[k].mae, html: fx.num(m[k].mae, 2) }, { v: m[k].spearman, html: fx.num(m[k].spearman, 3) }, m[k].n]); });
    });
    box.innerHTML = HW.tableHTML([{ label: 'Horizon' }, { label: 'Projection' }, { label: 'MAE (standard points)', align: 'right' }, { label: 'Rank correlation', align: 'right', title: 'Spearman, players with games in the window' }, { label: 'n', align: 'right' }], rows, { compact: true }) +
      '<div class="pg-note">Seasons ' + fx.esc((bt.seasons || []).join(', ')) + ', ' + fx.num(bt.checkpoints, 0) + ' weekly checkpoints. Baselines: the player\'s average so far this season (last season\'s when there are fewer than three games), and last season\'s average (this season\'s so far after no games last season). Lower MAE and higher rank correlation are better.</div>';
  }
}

function syncUrl(L) {
  try {
    const q = [];
    if (ST.fmt !== '9cat') q.push('fmt=' + ST.fmt);
    if (ST.hz !== 'pg') q.push('hz=' + ST.hz);
    const p = Object.keys(ST.punt);
    if (p.length) q.push('punt=' + p.join(','));
    history.replaceState(null, '', '#/' + L + '/fantasy?tab=tools' + (q.length ? '&' + q.join('&') : ''));
  } catch (e) { /* history unavailable */ }
}

HW.route('fantasy', render);
})(window.HW);
