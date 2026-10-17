/* The Quant Rink — calibration (#/calibration): does the modelling hold up?
 *
 * 1. Expected goals against MoneyPuck's xG on the same shots (log-loss, AUC, Brier, reliability, by
 *    season and by strength); MoneyPuck's values are a published benchmark, credited where shown.
 * 2. The game model against the closing lines (ESPN's DraftKings and other books, 2019–20 on; opening and closing blocks from 2022–23): win
 *    probability, puck line and total, with reliability.
 * 3. The game model against Elo and simple baselines on every game from 2009–10 (the first season a warm-up).
 * 4. Season odds (playoffs, division, Presidents' Trophy, Cup) scored at fixed checkpoints of past seasons.
 * 5. Stabilisation: the sample at which each catalogue metric is 70% signal.
 * Every sentence of "What it shows" is computed from the numbers, and a gap smaller than the noise is called
 * a tie.
 *
 * Data: data/calibration.json (models/backtest.py and the xG validation). Scorer blocks {n, logloss, brier,
 * auc, calibration: {bins: [[mid, mean_pred, mean_obs, n]], ece} | reliability: [{mean_p, freq, n}]}; splits by
 * season and strength. Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;
const LAB = { ours: 'Ours', model: 'Game model', game_model: 'Game model', xg: 'Our xG', ours_xg: 'Our xG', moneypuck: 'MoneyPuck xG', mp: 'MoneyPuck xG', market: 'Closing line', market_ml: 'Closing moneyline', close: 'Closing line', closing: 'Closing line',
  open: 'Opening line', elo: 'Elo', ratings: 'Team ratings only', model_ratings_only: 'Ratings only', baseline: 'Baseline', home: 'Home-ice only', base_rate: 'Base rate', coin: 'Coin flip', shot_distance: 'Distance-only xG', distance: 'Distance-only xG', blend_50: '50/50 model and market', ours_common: 'Ours (same shots)' };
const COL = { ours: '#5cc6f2', model: '#5cc6f2', game_model: '#5cc6f2', xg: '#5cc6f2', ours_xg: '#5cc6f2', ours_common: '#5cc6f2', moneypuck: '#f97316', mp: '#f97316', market: '#e6edf3', market_ml: '#e6edf3', close: '#e6edf3', closing: '#e6edf3', open: '#8b949e',
  elo: '#bc8cff', ratings: '#bc8cff', model_ratings_only: '#bc8cff', baseline: '#8b949e', home: '#6e7681', base_rate: '#6e7681', distance: '#6e7681', shot_distance: '#6e7681', blend_50: '#3fb950' };
const lab = m => LAB[m] || K().titleCase(m);
const isOurs = m => /^(ours|model|game_model|xg|ours_xg)$/.test(m);
const isScorer = v => v && typeof v === 'object' && !Array.isArray(v) && (K().isNum(v.logloss) || K().isNum(v.brier) || K().isNum(v.mae) || K().isNum(v.auc));

function get(d, paths) {
  for (let i = 0; i < paths.length; i++) {
    let x = d;
    const ps = paths[i].split('.');
    for (let j = 0; j < ps.length && x; j++) x = x[ps[j]];
    if (x !== undefined && x !== null) return x;
  }
  return null;
}
/* Scorer blocks of an object: {name: {n, logloss, brier, auc, bins}}. */
function scorers(obj) {
  const k = K(), out = {};
  if (!obj || typeof obj !== 'object') return out;
  Object.keys(obj).forEach(m => {
    const v = obj[m];
    if (isScorer(v)) out[m] = { n: k.first(v.n, obj.n_common, obj.n), logloss: k.first(v.logloss), brier: k.first(v.brier), auc: k.first(v.auc), mae: k.first(v.mae), rmse: k.first(v.rmse), ece: k.first((v.calibration || {}).ece, v.ece), se: k.first(v.se, v.logloss_se), bins: binsOf(v) };
  });
  return out;
}
function binsOf(v) { const c = v.calibration || v.reliability || v.bins; return K().binsOf(Array.isArray(c) ? c : (c && Array.isArray(c.bins) ? c.bins : [])); }
/* "a tie" when two scores are within the noise: max(0.1% of the score, two standard errors when the block gives one). */
function verdict(a, b, lowerBetter, se) {
  const k = K();
  if (!k.isNum(a) || !k.isNum(b)) return null;
  const d = a - b, tol = Math.max(Math.abs(b) * 0.001, k.isNum(se) ? 2 * se : 0, 1e-5);
  if (Math.abs(d) <= tol) return 'tie';
  return (lowerBetter ? d < 0 : d > 0) ? 'win' : 'lose';
}
function vchip(v) { return v ? '<span class="gf-verdict ' + v + '">' + (v === 'tie' ? 'tie' : v === 'win' ? 'ours better' : 'ours worse') + '</span>' : ''; }
const WORD = { tie: 'level (a tie)', win: 'better', lose: 'worse' };

function scoreTable(S, opts) {
  const k = K(), o = opts || {};
  const names = Object.keys(S);
  if (!names.length) return k.muted('Not scored yet.');
  const best = (key, hi) => { let b = null; names.forEach(m => { const v = S[m][key]; if (k.isNum(v) && (b === null || (hi ? v > b.v : v < b.v))) b = { m: m, v: v }; }); return b; };
  const bl = best('logloss'), bb = best('brier'), ba = best('auc', true), bm = best('mae');
  const has = key => names.some(m => k.isNum(S[m][key]));
  const ref = names.find(isOurs);
  const cell = (m, key, b, d) => { const v = S[m][key]; return { v: v, html: !k.isNum(v) ? '—' : (b && b.m === m && names.length > 1 ? '<strong class="gq-ok">' + k.num(v, d) + '</strong>' : k.num(v, d)) }; };
  return k.table([{ label: o.first || 'Forecaster' }, { label: o.nLabel || 'n', align: 'right' }].concat(has('logloss') ? [{ label: 'Log-loss', align: 'right', title: 'Lower is better' }] : []).concat(has('brier') ? [{ label: 'Brier', align: 'right', title: 'Lower is better' }] : [])
    .concat(has('auc') ? [{ label: 'AUC', align: 'right', title: 'Area under the ROC curve: higher ranks goals above non-goals better' }] : []).concat(has('mae') ? [{ label: 'MAE', align: 'right', title: o.maeTitle || 'Mean absolute error (lower is better)' }] : [])
    .concat(has('ece') ? [{ label: 'ECE', align: 'right', title: 'Expected calibration error: count-weighted |forecast − observed| over the bins' }] : []).concat(ref ? [{ label: 'Ours v this', sortable: false }] : []),
  names.map(m => [{ v: m, html: '<span class="gq-dotc" style="background:' + (COL[m] || '#8b949e') + '"></span><strong>' + k.esc(lab(m)) + '</strong>' }, { v: S[m].n, html: k.int(S[m].n) }]
    .concat(has('logloss') ? [cell(m, 'logloss', bl, 4)] : []).concat(has('brier') ? [cell(m, 'brier', bb, 4)] : []).concat(has('auc') ? [cell(m, 'auc', ba, 4)] : []).concat(has('mae') ? [cell(m, 'mae', bm, 2)] : []).concat(has('ece') ? [cell(m, 'ece', null, 4)] : [])
    .concat(ref ? [{ v: '', html: m === ref ? '<span class="muted-inline">reference</span>' : vchip(verdict(k.isNum(S[ref].logloss) ? S[ref].logloss : S[ref].mae, k.isNum(S[m].logloss) ? S[m].logloss : S[m].mae, true, S[ref].se)) }] : [])), { compact: true });
}
/* {S: {name: logloss | {logloss}}} -> lines by season. */
function bySeries(id, obj, opts) {
  const k = K(), node = k.$(id), o = opts || {};
  if (!node) return;
  if (!obj || typeof obj !== 'object' || Object.keys(obj).length < 2) { k.empty(node, 'Not published.'); return; }
  const xs = Object.keys(obj).sort();
  const names = [];
  const vOf = (x, m) => { const v = (obj[x] || {})[m]; return k.isNum(v) ? Number(v) : (v && k.isNum(v[o.key || 'logloss']) ? Number(v[o.key || 'logloss']) : null); };
  xs.forEach(x => Object.keys(obj[x] || {}).forEach(m => { if (m !== 'n' && k.isNum(vOf(x, m)) && names.indexOf(m) < 0) names.push(m); }));
  const lx = xs.map(x => (k.sid(x) ? k.sLabel(x) : (/^\d$/.test(x) ? (Number(x) > 3 ? 'OT' : 'P' + x) : x)));
  k.plot(node, names.map(m => ({ type: 'scatter', mode: 'lines+markers', name: lab(m), x: lx, y: xs.map(x => vOf(x, m)), line: { color: COL[m] || '#8b949e', width: 2, dash: /market|close|moneypuck|mp/.test(m) ? 'dot' : 'solid' }, connectgaps: false })),
    k.layout(Object.assign({ margin: { l: 56, r: 10, t: 30, b: 40 }, yaxis: { title: o.yt || 'Log-loss', tickformat: '.3f' }, xaxis: { type: 'category' } }, k.legendTop())));
}

/* ── sections ──────────────────────────────────────────────────────────── */

function xgSection(d, out, read) {
  const k = K();
  const X = get(d, ['xg', 'xg_model', 'models.xg', 'shots']);
  if (!X || typeof X !== 'object') { out.push(k.card('Expected goals against MoneyPuck', '', k.muted('The comparison of our xG with MoneyPuck\'s on the same shots has not been published yet.'))); return; }
  const ALL = scorers(X.all || X.metrics || X.pooled || X);
  const credit = (RK.MONEYPUCK_CREDIT || 'xG benchmark data from MoneyPuck.com');
  let h = '<div class="card"><div class="card-header">Expected goals against MoneyPuck <span class="card-sub">Every unblocked shot' + (X.seasons ? ' from ' + k.esc(k.sLabel(X.seasons[0])) + ' to ' + k.esc(k.sLabel(X.seasons[X.seasons.length - 1])) : '') +
    ', y = 1 when it was a goal. Our model is cross-fitted by season (no shot is scored by a model that saw its season); MoneyPuck\'s published xG is the benchmark, on the shots both cover. ' + k.esc(credit) + '.</span></div>';
  h += '<div class="gq-pad" id="cal-xg-t"></div><div class="grid-2"><div><div class="gq-sub-head">Reliability: forecast against goal rate</div><div id="cal-xg-rel" class="gf-chart"></div></div><div><div class="gq-sub-head">Log-loss by season</div><div id="cal-xg-yr" class="gf-chart"></div></div></div>';
  if (X.by_strength) h += '<div class="gq-sub-head">By strength</div><div class="gq-pad" id="cal-xg-str"></div>';
  h += note(X) + '</div>';
  out.push(h);
  const o = ALL.ours || ALL.xg || ALL.ours_xg || ALL[Object.keys(ALL).find(isOurs)], mp = ALL.moneypuck || ALL.mp;
  if (o && mp && k.isNum(o.logloss) && k.isNum(mp.logloss)) {
    const v = verdict(o.logloss, mp.logloss, true, o.se);
    read.push('<p><strong>Expected goals.</strong> On ' + k.int(Math.min(o.n || 0, mp.n || 0) || o.n) + ' shots our xG scores a log-loss of ' + k.num(o.logloss, 4) + ' against MoneyPuck\'s ' + k.num(mp.logloss, 4) + ': ' +
      (v === 'tie' ? 'a tie, within the noise.' : v === 'win' ? 'ours is sharper by ' + k.num(mp.logloss - o.logloss, 4) + '. MoneyPuck\'s model is fitted on more history, so treat this as provisional.' : 'MoneyPuck\'s is sharper by ' + k.num(o.logloss - mp.logloss, 4) + ' a shot.') +
      (k.isNum(o.auc) && k.isNum(mp.auc) ? ' On ranking (AUC) ours is ' + WORD[verdict(o.auc, mp.auc, false)] + ' (' + k.num(o.auc, 4) + ' against ' + k.num(mp.auc, 4) + ').' : '') + '</p>');
  }
  setTimeout(() => {
    k.set('cal-xg-t', scoreTable(ALL, { nLabel: 'Shots' }));
    const rel = Object.keys(ALL).filter(m => ALL[m].bins.length).map(m => ({ name: lab(m), colour: COL[m] || '#8b949e', bins: ALL[m].bins }));
    if (rel.length) k.reliability('cal-xg-rel', rel, { xt: 'Forecast xG', yt: 'Goal rate', minN: 30, max: Math.min(1, Math.max.apply(null, rel.map(s => Math.max.apply(null, k.binsOf(s.bins).map(b => b.x)))) * 1.1) });
    else k.empty('cal-xg-rel', 'No reliability bins.');
    bySeries('cal-xg-yr', X.by_season || X.per_season);
    if (X.by_strength) { const T = {}; Object.keys(X.by_strength).forEach(s => { const z = scorers(X.by_strength[s]); Object.keys(z).forEach(m => { T[s + '|' + m] = z[m]; }); });
      k.set('cal-xg-str', k.table([{ label: 'Strength' }, { label: 'Model' }, { label: 'Shots', align: 'right' }, { label: 'Log-loss', align: 'right' }, { label: 'AUC', align: 'right' }],
        Object.keys(T).map(x => { const p = x.split('|'); return [{ v: p[0], html: '<strong>' + k.esc(RK.fk.strengthLabel ? RK.fk.strengthLabel(p[0]) : p[0]) + '</strong>' }, { v: p[1], html: '<span class="gq-dotc" style="background:' + (COL[p[1]] || '#8b949e') + '"></span>' + k.esc(lab(p[1])) }, { v: T[x].n, html: k.int(T[x].n) }, { v: T[x].logloss, html: k.num(T[x].logloss, 4) }, { v: T[x].auc, html: k.num(T[x].auc, 4) }]; }), { compact: true })); }
  }, 0);
}
function note(x) { return x && x.note ? '<div class="pg-note gq-note">' + K().esc(K().cleanDesc(x.note)) + '</div>' : ''; }

/* The game model (models/backtest.py): metrics / metrics_vs_market {model, market_ml, elo, ...}, per_season, puck_line, totals, books. */
function gamesSection(d, out, read) {
  const k = K();
  const G = get(d, ['game_model', 'games', 'backtest']);
  if (!G || typeof G !== 'object' || !(G.metrics || G.pooled || G.vs_market || G.metrics_vs_market)) { out.push(k.card('The game model against the closing line', '', k.muted('The walk-forward backtest (every game priced with only what was known before it, against the closing lines from 2019–20 and against Elo from 2009–10) has not been published yet.'))); return; }
  const ALL = scorers(G.metrics || (G.pooled || {}).win || G.pooled || {}), VM = scorers(G.metrics_vs_market || G.vs_market || {});
  const PSD = G.per_season || G.by_season || {};
  const seasons = (Object.keys(PSD).length ? Object.keys(PSD) : (G.seasons || [])).map(String).filter(s => k.sid(s)).sort();
  const warm = s => !!((PSD[s] || {}).warm_up) || (G.warm_up || []).map(String).indexOf(String(s)) >= 0;
  const m = VM.model || VM.ours || ALL.model || ALL.ours, mk = VM.market_ml || VM.market || VM.close || ALL.market_ml;
  let h = '<div class="card"><div class="card-header">The game model against the closing line <span class="card-sub">Walk-forward' + (seasons.length ? ' ' + k.esc(k.sLabel(seasons[0])) + ' to ' + k.esc(k.sLabel(seasons[seasons.length - 1])) : '') +
    ': team strength refitted before every game day from earlier games only; y = 1 when the home team wins (overtime and shootouts included). The closing lines are ESPN\'s (DraftKings first, then other books) from 2019–20, de-vigged (the close where ESPN has one, 2022–23 on; else the last line it lists).</span><span class="gq-ctl"><select id="cal-scope"><option value="vm">games with a closing line</option><option value="all">every game</option>' + seasons.slice().reverse().map(s => '<option value="s' + s + '">' + k.esc(k.sLabel(s)) + (warm(s) ? ' (warm-up, code defaults)' : '') + '</option>').join('') + '</select></span></div>';
  h += k.tiles([k.tile('Games scored', k.int(G.games || G.n || (ALL.model || ALL.ours || {}).n), seasons.length ? seasons.length + ' seasons' : ''),
    m ? k.tile('Model log-loss', k.num(m.logloss, 4), 'Brier ' + k.num(m.brier, 4) + (mk ? ' · same games as the close' : '')) : '',
    mk ? k.tile('Closing line', k.num(mk.logloss, 4), 'de-vigged · Brier ' + k.num(mk.brier, 4)) : '',
    (VM.elo || ALL.elo) ? k.tile('Elo', k.num((VM.elo || ALL.elo).logloss, 4), 'same games') : '',
    k.tile('Coin flip', k.num(Math.LN2, 4), 'log-loss of 50/50'), k.isNum(G.home_rate) ? k.tile('Home win rate', k.pct(G.home_rate, 1), 'base rate ' + k.num(-(G.home_rate * Math.log(G.home_rate) + (1 - G.home_rate) * Math.log(1 - G.home_rate)), 4)) : '']);
  h += '<div class="gq-pad" id="cal-table"></div>';
  h += '<div class="grid-2"><div><div class="gq-sub-head">Reliability: who wins</div><div id="cal-rel" class="gf-chart"></div></div><div><div class="gq-sub-head">Log-loss by season</div><div id="cal-years" class="gf-chart"></div></div></div>';
  if (G.books && Object.keys(G.books).length) h += '<div class="gq-sub-head">Closing lines by book, each against the model on the same games</div><div id="cal-books"></div>';
  h += '<div class="grid-2"><div><div class="gq-sub-head">Puck line: P(home ' + (G.puck_line || G.spread || G.ats ? 'covers the closing line' : 'wins by two or more, the −1.5') + ')</div><div id="cal-pl"></div><div id="cal-pl-c" class="gf-chart"></div></div>' +
    '<div><div class="gq-sub-head">Totals: P(over the closing total)</div><div id="cal-tot"></div><div id="cal-tot-c" class="gf-chart"></div></div></div>' + note(G) + '</div>';
  out.push(h);
  if (m && mk && k.isNum(m.logloss) && k.isNum(mk.logloss)) {
    const v = verdict(m.logloss, mk.logloss, true, m.se);
    read.push('<p><strong>Against the closing line.</strong> On the ' + k.int(Math.min(m.n || 0, mk.n || 0) || m.n) + ' games with a closing line the game model scores ' + k.num(m.logloss, 4) + ' and the de-vigged close ' + k.num(mk.logloss, 4) + ': ' +
      (v === 'tie' ? 'a tie, within the noise. ' : v === 'win' ? 'the model is sharper by ' + k.num(mk.logloss - m.logloss, 4) + ', which would be remarkable against a closing line: treat it as provisional until it survives more seasons. ' : 'the closing line is sharper by ' + k.num(m.logloss - mk.logloss, 4) + ' a game, the expected order: the close knows confirmed starting goalies, injuries and money that the model reads late or not at all. ') +
      'Hockey games are close to coin flips (even good teams win about 60%), so every forecaster sits near ln 2 = 0.693 and differences live in the third decimal.</p>');
  }
  const e = ALL.elo, mm = ALL.model || ALL.ours;
  if (e && mm && k.isNum(e.logloss) && k.isNum(mm.logloss)) read.push('<p><strong>Against Elo.</strong> Over ' + k.int(mm.n) + ' games' + (seasons.length ? ' from ' + k.esc(k.sLabel(seasons[0])) : '') + ' the model scores ' + k.num(mm.logloss, 4) + ' and Elo ' + k.num(e.logloss, 4) + ': the model is ' + WORD[verdict(mm.logloss, e.logloss, true, mm.se)] + '.' +
    (ALL.home && k.isNum(ALL.home.logloss) ? ' Home ice alone scores ' + k.num(ALL.home.logloss, 4) + '.' : '') + '</p>');
  [[G.puck_line || G.spread || G.ats || G.puck_line_home, 'covers', 'Puck line'], [G.totals || G.total || G.totals_model, 'overs', 'Totals']].forEach(z => { if (z[0] && z[0].n) side(null, null, z[0], z[1], read, z[2], true); });
  setTimeout(() => {
    const drawT = v => {
      let src = v === 'all' ? ALL : (Object.keys(VM).length ? VM : ALL);
      if (v.charAt(0) === 's') src = scorers(PSD[v.slice(1)] || {});
      k.set('cal-table', scoreTable(src, { nLabel: 'Games' }));
    };
    drawT('vm');
    const sel = k.$('cal-scope');
    if (sel) sel.onchange = ev => drawT(ev.target.value);
    const SRC = Object.keys(VM).length ? VM : ALL;
    const rel = Object.keys(SRC).filter(x => SRC[x].bins.length).slice(0, 4).map(x => ({ name: lab(x), colour: COL[x] || '#8b949e', bins: SRC[x].bins }));
    if (rel.length) k.reliability('cal-rel', rel, { xt: 'Forecast P(home win)', yt: 'Home win rate', minN: 20, min: 0.2, max: 0.8 }); else k.empty('cal-rel', 'No reliability bins.');
    const PS = {};
    Object.keys(PSD).forEach(s => { const z = scorers(PSD[s]); PS[s] = {}; Object.keys(z).forEach(x => { PS[s][x] = z[x].logloss; }); });
    bySeries('cal-years', PS);
    const books = G.books || {};
    if (Object.keys(books).length) {
      k.set('cal-books', k.table([{ label: 'Book' }, { label: 'Games', align: 'right' }, { label: 'Book log-loss', align: 'right' }, { label: 'Model, same games', align: 'right' }, { label: 'Model v book', sortable: false }],
        Object.keys(books).map(b => { const x = books[b], bk = x.book || x, mo = x.model_same_games || x.model || {};
          return [{ v: b, html: '<strong>' + k.esc(b) + '</strong>' }, { v: bk.n, html: k.int(bk.n) }, { v: bk.logloss, html: k.num(bk.logloss, 4) }, { v: mo.logloss, html: k.num(mo.logloss, 4) }, { v: '', html: vchip(verdict(mo.logloss, bk.logloss, true)) }]; }), { compact: true }));
    }
    side('cal-pl', 'cal-pl-c', G.puck_line || G.spread || G.ats || G.puck_line_home, 'covers', [], 'Puck line');
    side('cal-tot', 'cal-tot-c', G.totals || G.total || G.totals_model, 'overs', [], 'Totals');
  }, 0);
}

/* A side market (puck line or totals): the probability scored against a coin, and the record of the side the model leans to. */
function side(id, cid, A, what, read, title, textOnly) {
  const k = K();
  if (!A || !A.n) { if (!textOnly) { k.set(id, k.muted('Not scored yet.')); const n = k.$(cid); if (n) n.style.display = 'none'; } return; }
  const coin = k.isNum(A.logloss_coin) ? A.logloss_coin : (k.isNum(A.logloss_base) ? A.logloss_base : Math.LN2);
  const v = verdict(A.logloss, coin, true);
  const pk = A.picks_p55 || A.picks || {};
  const se = k.isNum(pk.win_rate) && pk.n ? Math.sqrt(pk.win_rate * (1 - pk.win_rate) / pk.n) : null;
  const pv = k.isNum(pk.win_rate) ? verdict(pk.win_rate, 0.5, false, se) : null;
  if (!textOnly) {
    const h = '<div class="kpi-grid gq-tiles gq-tiles-3">' + [k.tile('Scored', k.int(A.n), 'pushes left out'), k.tile('Log-loss', k.num(A.logloss, 4), (k.isNum(A.logloss_base) ? 'base rate ' : 'coin ') + k.num(coin, 4) + ' · ' + (v === 'tie' ? 'a tie' : v === 'win' ? 'better' : 'worse')),
      k.isNum(pk.win_rate) ? k.tile('Model\'s side (P ≥ 55%)', k.pct(pk.win_rate, 1), k.int(pk.n) + ' games' + (se ? ' · ±' + k.num(200 * se, 1) + ' pp (2 SE)' : '')) : ''].join('') + '</div>';
    k.set(id, h);
    const bins = binsOf(A);
    if (bins.length) k.reliability(cid, [{ name: title, colour: '#5cc6f2', bins: bins }], { xt: 'Model probability', yt: 'Observed rate', minN: 20, min: 0.2, max: 0.8 });
    else { const n = k.$(cid); if (n) n.style.display = 'none'; }
    return;
  }
  read.push('<p><strong>' + title + '.</strong> Against the closing ' + (what === 'covers' ? 'puck line' : 'total') + ', the model\'s probability scores ' + k.num(A.logloss, 4) + ' against ' + k.num(coin, 4) + ' for ' + (k.isNum(A.logloss_base) ? 'the base rate' : 'a coin') + ' over ' + k.int(A.n) + ' games: ' +
    (v === 'tie' ? 'a tie, which is what a closing line should allow. ' : v === 'win' ? 'better. ' : 'worse: the model adds noise to the closing number here. ') +
    (k.isNum(pk.win_rate) ? 'Where it leans 55% or more, its side ' + (what === 'covers' ? 'covered' : 'won') + ' ' + k.pct(pk.win_rate, 1) + ' of ' + k.int(pk.n) + (se ? ' (±' + k.num(200 * se, 1) + ' points)' : '') + ': ' + (pv === 'tie' ? 'a tie with 50%.' : pv === 'win' ? 'above 50%; treat as provisional, and remember the prices are not even money.' : 'below 50%.') : '') + '</p>');
}

/* Season odds: {metrics: {playoffs, div, pres, cup: scorer + base_rate + by_checkpoint}, n_sims, checkpoints}. */
function seasonOdds(d, out, read) {
  const k = K();
  const X = get(d, ['season_sim', 'season_odds', 'season']);
  const M = X && (X.metrics || X);
  if (!M || typeof M !== 'object' || !Object.keys(M).some(x => isScorer(M[x]))) { out.push(k.card('Season odds', '', k.muted('Season-odds calibration (playoff, division, Presidents\' Trophy and Cup odds at fixed points of past seasons, against what happened) is not published yet.'))); return; }
  const NAME = { playoffs: 'Make the playoffs', div: 'Win the division', pres: 'Presidents\' Trophy', presidents: 'Presidents\' Trophy', conf: 'Reach the Final', cup: 'Win the Stanley Cup' };
  const cps = X.checkpoints || X.check_dates || X.check_games || [];
  const rows = {};
  Object.keys(M).forEach(x => { if (isScorer(M[x])) rows[x] = scorers({ x: M[x] }).x; });
  let h = '<div class="card"><div class="card-header">Season odds <span class="card-sub">' + (X.n_sims ? k.int(X.n_sims) + ' simulations' : 'Simulations') + ' run at fixed points of each completed season with ratings fitted strictly before, scored against what happened. Base-rate log-loss (always forecasting the league share) is the bar to beat.</span></div><div class="gq-pad">';
  const H = b => (k.isNum(b) && b > 0 && b < 1 ? -(b * Math.log(b) + (1 - b) * Math.log(1 - b)) : null);
  h += k.table([{ label: 'Market' }, { label: 'Team-checkpoints', align: 'right' }, { label: 'Log-loss', align: 'right' }, { label: 'Base rate', align: 'right', title: 'Log-loss of always forecasting the share that happened' }, { label: 'Brier', align: 'right' }, { label: 'v base rate', sortable: false }].concat(cps.map(w => ({ label: String(w), align: 'right' }))),
    Object.keys(rows).map(x => { const r = M[x], b = H(r.base_rate);
      return [{ v: x, html: '<strong>' + k.esc(NAME[x] || lab(x)) + '</strong>' }, { v: r.n, html: k.int(r.n) }, { v: r.logloss, html: k.num(r.logloss, 4) }, { v: b, html: k.num(b, 4) }, { v: r.brier, html: k.num(r.brier, 4) }, { v: '', html: b ? vchip(verdict(r.logloss, b, true)) : '' }]
        .concat(cps.map(w => { const z = (r.by_checkpoint || r.by_week || {})[String(w)] || {}; return { v: z.logloss, html: k.num(z.logloss, 4) }; })); }), { compact: true }) + '</div><div id="cal-so" class="gf-chart"></div>' + note(X) + '</div>';
  out.push(h);
  const pl = M.playoffs;
  if (pl && k.isNum(pl.logloss) && k.isNum(pl.base_rate)) read.push('<p><strong>Season odds.</strong> Playoff odds score ' + k.num(pl.logloss, 4) + ' against ' + k.num(H(pl.base_rate), 4) + ' for the base rate over ' + k.int(pl.n) + ' team-checkpoints (' + WORD[verdict(pl.logloss, H(pl.base_rate), true)] + '); the gain grows through the season as the standings fill in.</p>');
  setTimeout(() => {
    const ser = Object.keys(rows).filter(x => rows[x].bins.length).slice(0, 5).map((x, i) => ({ name: NAME[x] || x, colour: k.PALETTE[i], bins: rows[x].bins }));
    if (ser.length) k.reliability('cal-so', ser, { minN: 10 }); else { const n = k.$('cal-so'); if (n) n.style.display = 'none'; }
  }, 0);
}

/* Stabilisation: calibration.json "stabilisation" [{key, label, kind, stabilises_at, unit, k, r_at_n?}] or the catalogues' METRIC.stabilises_at. */
function stabilisation(d, cats, out) {
  const k = K();
  let rows = k.listOf(get(d, ['stabilisation', 'stabilization', 'stability']) || [], 'key');
  if (!rows.length) {
    cats.forEach(c => { const cat = c[1]; if (!cat) return; k.allMetrics(cat).forEach(m => { if (k.isNum(m.stabilises_at) && !rows.some(r => r.key === m.key && r.kind === c[0])) rows.push({ key: m.key, label: m.label, kind: c[0], stabilises_at: m.stabilises_at, unit: m.unit || (c[0] === 'Goalies' ? 'shots' : 'minutes'), group: m.group }); }); });
  }
  rows = rows.filter(r => k.isNum(r.stabilises_at || r.n70 || r.n_07));
  if (!rows.length) { out.push(k.card('Stabilisation', '', k.muted('Stabilisation points are not published yet.'))); return; }
  rows.forEach(r => { r.n = k.first(r.stabilises_at, r.n70, r.n_07); r.kk = k.first(r.k, r.n * 3 / 7); });
  rows.sort((a, b) => String(a.kind || '').localeCompare(String(b.kind || '')) || a.n - b.n);
  out.push('<div class="card"><div class="card-header">Stabilisation <span class="card-sub">The sample at which each metric is 70% signal: split-half reliability r(n) = n/(n + k) fitted across seasons, so n₀.₇ = 7k/3. Below it, a number is mostly noise; the catalogues shrink every value by (n·x + k·mean)/(n + k) before ranking.</span></div>' +
    '<div class="gq-pad">' + k.table([{ label: 'Metric' }, { label: 'Pool' }, { label: 'Stabilises at', align: 'right' }, { label: 'Measured in' }, { label: 'k', align: 'right', title: 'The shrinkage constant: 3/7 of the stabilisation point' }].concat(rows.some(r => k.isNum(r.n_seasons) || k.isNum(r.pairs)) ? [{ label: 'Sample', align: 'right', title: 'Player-seasons in the fit' }] : []),
      rows.map(r => [{ v: r.label || r.key, html: '<a href="#/glossary/' + encodeURIComponent(r.key) + '">' + k.esc(r.label || r.key) + '</a>' }, { v: r.kind || '', html: k.esc(r.kind || r.pool || '') }, { v: r.n, html: '<strong>' + k.int(r.n) + '</strong>' }, { v: r.unit || '', html: k.esc(r.unit || '') }, { v: r.kk, html: k.int(r.kk) }]
        .concat(rows.some(z => k.isNum(z.n_seasons) || k.isNum(z.pairs)) ? [{ v: k.first(r.n_seasons, r.pairs), html: k.int(k.first(r.n_seasons, r.pairs)) }] : [])), { compact: true, sticky: true }) + '</div>' +
    '<div class="pg-note gq-note">Rates built on goals (shooting %, save %, on-ice goal shares) take far longer to stabilise than rates built on shot attempts or expected goals; that is why the site leads with expected goals.</div></div>');
  setTimeout(() => k.sortable(k.$('cal-root')), 0);
}

function render(el) {
  const k = K();
  el.innerHTML = k.muted('Loading the backtest…');
  return k.ready().then(() => { const S = k.curSeason(); return Promise.all([RK.load('calibration.json'), k.loadY(S, 'skaters.json'), k.loadY(S, 'goalies.json')]); }).then(res => {
    if (!k.alive(el)) return;
    const d = res[0];
    const ok = d && d.ok !== false;
    const out = [], read = [];
    let h = '<div class="card"><div class="card-header">Calibration <span class="card-sub">Does the modelling hold up? Every number below is computed out of sample, and every comparison is with the best public alternative.' + (d && (d.generated_at || d.updated_at) ? ' Generated ' + k.esc(k.fmtDate(d.generated_at || d.updated_at, { year: true })) + '.' : '') + '</span></div>';
    if (!ok) h += '<div class="gq-read"><p>The backtest has not been published yet' + (d && d.reason ? ' (' + k.esc(k.cleanDesc(d.reason)) + ')' : '') + '. When it is, this page scores our expected goals against MoneyPuck\'s on the same shots, the game model against the closing lines from 2019–20 and against Elo from 2009–10, the puck line and totals, and season odds. Ties will be reported as ties.</p></div>';
    h += '</div>';
    if (ok) { xgSection(d, out, read); gamesSection(d, out, read); seasonOdds(d, out, read); }
    stabilisation(ok ? d : {}, [['Skaters', k.catOf(res[1])], ['Goalies', k.catOf(res[2])]], out);
    el.innerHTML = '<div id="cal-root">' + h + (ok ? '<div class="card"><div class="card-header">What it shows <span class="card-sub">Written from the numbers on this page; a gap smaller than the noise is called a tie.</span></div><div class="gq-read" id="cal-read"></div></div>' : '') + out.join('') +
      '<div class="card"><div class="card-header">How to read it</div><div class="gq-read"><p><strong>Log-loss</strong> is −mean(y ln p + (1 − y) ln(1 − p)), lower is better; a coin scores ln 2 = 0.6931; for shots, where goals are rare, the bar is the base-rate log-loss of always forecasting the league\'s goal share, far below a coin\'s. <strong>Brier</strong> is mean((p − y)²). <strong>AUC</strong> is the chance a random goal got a higher xG than a random non-goal. <strong>Reliability</strong> bins forecasts and plots the average forecast against how often the event happened; a calibrated model sits on the diagonal. A difference is called a <strong>tie</strong> when it is within two standard errors (or 0.1% of the score when no standard error is published). Beating a closing line is rare; being close to it is the realistic goal. See the <a href="#/methodology/backtest">methodology</a>.</p>' +
      '<p class="muted-inline">' + k.esc(RK.MONEYPUCK_CREDIT || 'xG benchmark data from MoneyPuck.com') + ' (non-commercial use, credited). Closing lines from ESPN\'s public odds feed.</p></div></div></div>';
    if (ok) k.set('cal-read', read.join('') || '<p>Not enough scored games for a reading yet.</p>');
  });
}

if (typeof RK.route === 'function') { try { RK.route('calibration', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
