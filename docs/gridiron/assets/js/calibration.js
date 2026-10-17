/* The Quant Gridiron — calibration (#/calibration): does the modelling hold up?
 *
 * 1. The game model against the closing line, walk-forward 2006 on: log-loss, Brier and reliability of
 *    the win probability against the de-vigged closing moneyline (and simple baselines); the spread
 *    against the closing spread (mean absolute error of the margin, against-the-spread calibration and
 *    the record of the model's side); totals; and season odds (playoffs, division, Super Bowl).
 * 2. Our expected points and win probability against nflfastR's published values on the same plays.
 * 3. The fourth-down conversion model.
 * Every sentence of "What it shows" is computed from the numbers, and a difference smaller than the
 * noise is called a tie.
 *
 * Data: data/calibration.json, written from builder C's backtest (models/backtest.py) and builder B's
 * validation blocks. The readers accept the shapes those modules write: scorer blocks {n, logloss, brier,
 * calibration: {bins: [[mid, mean_pred, mean_obs, n]], ece}} (or reliability: [{mean_p, freq, n}]),
 * splits {all, pre_2020, from_2020, by_season: {S: {n, ours, wp, vegas_wp}}, by_quarter}. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const LAB = { model_ratings_only: 'Ratings only', elo: 'Elo (FiveThirtyEight method)', market_ml: 'Closing moneyline', market_spread: 'Closing spread', ours: 'Ours', model: 'Game model', game_model: 'Game model', ours_common: 'Ours (same plays)', market: 'Closing line', close: 'Closing line', closing: 'Closing line', closing_line: 'Closing line',
  open: 'Opening line', ratings: 'Team ratings only', elo: 'Elo baseline', baseline: 'Baseline', home: 'Home-field only', coin: 'Coin flip', blend_50: '50/50 model and market',
  nflfastr: 'nflfastR', nflfastr_wp: 'nflfastR wp', nflfastr_vegas_wp: 'nflfastR vegas_wp', wp: 'nflfastR wp', vegas_wp: 'nflfastR vegas_wp', espn: 'ESPN', espn_wp: 'ESPN' };
const COL = { model_ratings_only: '#bc8cff', market_ml: '#58a6ff', market_spread: '#79c0ff', ours: '#c8834a', model: '#c8834a', game_model: '#c8834a', ours_common: '#c8834a', market: '#58a6ff', close: '#58a6ff', closing: '#58a6ff', closing_line: '#58a6ff', open: '#79c0ff',
  ratings: '#bc8cff', elo: '#bc8cff', baseline: '#8b949e', home: '#6e7681', blend_50: '#3fb950', nflfastr: '#58a6ff', nflfastr_wp: '#58a6ff', wp: '#58a6ff', nflfastr_vegas_wp: '#39d0d8', vegas_wp: '#39d0d8', espn: '#8b949e', espn_wp: '#8b949e' };
const lab = m => LAB[m] || K().titleCase(m);
const isOurs = m => /^(ours|model|game_model)$/.test(m);
const isScorer = v => v && typeof v === 'object' && !Array.isArray(v) && (K().isNum(v.logloss) || K().isNum(v.brier) || K().isNum(v.mae));

function get(d, paths) {
  for (let i = 0; i < paths.length; i++) {
    let x = d;
    const ps = paths[i].split('.');
    for (let j = 0; j < ps.length && x; j++) x = x[ps[j]];
    if (x !== undefined && x !== null) return x;
  }
  return null;
}
/* Scorer blocks of an object: {name: {n, logloss, brier, bins}}. */
function scorers(obj) {
  const k = K(), out = {};
  if (!obj || typeof obj !== 'object') return out;
  Object.keys(obj).forEach(m => {
    const v = obj[m];
    if (isScorer(v)) out[m] = { n: k.first(v.n, obj.n_common, obj.n), logloss: k.first(v.logloss), brier: k.first(v.brier), mae: k.first(v.mae), rmse: k.first(v.rmse), ece: k.first((v.calibration || {}).ece, v.ece), bins: binsOf(v) };
  });
  return out;
}
function binsOf(v) {
  const c = v.calibration || v.reliability || v.bins;
  const list = Array.isArray(c) ? c : (c && Array.isArray(c.bins) ? c.bins : []);
  return list.map(b => (Array.isArray(b) ? (b.length >= 4 ? { x: b[1], y: b[2], n: b[3] } : { x: b[0], y: b[1], n: b[2] || 0 }) : { x: K().first(b.mean_p, b.p, b.pred, b.mean_pred, b.x), y: K().first(b.freq, b.obs, b.y, b.observed, b.mean_obs), n: b.n || b.count || 0 })).filter(b => K().isNum(b.x) && K().isNum(b.y));
}
/* "a tie" when two scores are within the noise: max(0.1% of the score, two standard errors when the block gives one). */
function verdict(a, b, lowerBetter, se) {
  const k = K();
  if (!k.isNum(a) || !k.isNum(b)) return null;
  const d = a - b, tol = Math.max(Math.abs(b) * 0.001, k.isNum(se) ? 2 * se : 0, 1e-5);
  if (Math.abs(d) <= tol) return 'tie';
  return (lowerBetter ? d < 0 : d > 0) ? 'win' : 'lose';
}
function vchip(v) { return v ? '<span class="gf-verdict ' + v + '">' + (v === 'tie' ? 'tie' : v === 'win' ? 'ours better' : 'ours worse') + '</span>' : ''; }

function scoreTable(S, opts) {
  const k = K(), o = opts || {};
  const names = Object.keys(S);
  if (!names.length) return k.muted('Not scored yet.');
  const best = key => { let b = null; names.forEach(m => { const v = S[m][key]; if (k.isNum(v) && (b === null || v < b.v)) b = { m: m, v: v }; }); return b; };
  const bl = best('logloss'), bb = best('brier'), bm = best('mae');
  const hasMae = names.some(m => k.isNum(S[m].mae)), hasLL = names.some(m => k.isNum(S[m].logloss)), hasEce = names.some(m => k.isNum(S[m].ece));
  const ref = names.find(isOurs);
  const cell = (m, key, b, d) => { const v = S[m][key]; return { v: v, html: !k.isNum(v) ? '—' : (b && b.m === m && names.length > 1 ? '<strong class="gq-ok">' + k.num(v, d) + '</strong>' : k.num(v, d)) }; };
  return k.table([{ label: o.first || 'Forecaster' }, { label: o.nLabel || 'n', align: 'right' }].concat(hasLL ? [{ label: 'Log-loss', align: 'right', title: 'Lower is better' }, { label: 'Brier', align: 'right', title: 'Lower is better' }] : [])
    .concat(hasMae ? [{ label: 'MAE', align: 'right', title: o.maeTitle || 'Mean absolute error (lower is better)' }, { label: 'RMSE', align: 'right' }] : []).concat(hasEce ? [{ label: 'ECE', align: 'right', title: 'Expected calibration error: count-weighted |forecast − observed| over the bins' }] : [])
    .concat(ref ? [{ label: 'Ours v this', sortable: false }] : []),
  names.map(m => [{ v: m, html: '<span class="gq-dotc" style="background:' + (COL[m] || '#8b949e') + '"></span><strong>' + k.esc(lab(m)) + '</strong>' }, { v: S[m].n, html: k.int(S[m].n) }]
    .concat(hasLL ? [cell(m, 'logloss', bl, 4), cell(m, 'brier', bb, 4)] : []).concat(hasMae ? [cell(m, 'mae', bm, 2), cell(m, 'rmse', null, 2)] : []).concat(hasEce ? [cell(m, 'ece', null, 4)] : [])
    .concat(ref ? [{ v: '', html: m === ref ? '' : vchip(verdict(k.isNum(S[ref].logloss) ? S[ref].logloss : S[ref].mae, k.isNum(S[m].logloss) ? S[m].logloss : S[m].mae, true)) }] : [])), { compact: true });
}

/* ── sections ──────────────────────────────────────────────────────────── */

/* The game-model block (models/backtest.py → calibration.json "game_model"): metrics and metrics_vs_market {model,
 * model_ratings_only, elo, market_ml, market_spread: {n, logloss, brier, base_rate, reliability}}, per_season, books,
 * margin_rmse, ats and totals ({n, logloss, brier, reliability, logloss_coin, picks_p55: {n, win_rate}, by_season}),
 * hfa_by_season. */
function gamesSection(d, out, read) {
  const k = K();
  const G = get(d, ['game_model', 'games', 'backtest']);
  if (!G || typeof G !== 'object' || !(G.metrics || G.pooled)) { out.push(k.card('The game model against the closing line', '', k.muted('The walk-forward backtest (every game from 2006 priced with only what was known before it, against the closing spread and moneyline) has not been published yet.'))); return; }
  const ALL = scorers(G.metrics || (G.pooled || {}).win || G.pooled), VM = scorers(G.metrics_vs_market || {});
  const seasons = (G.seasons || Object.keys(G.per_season || {})).map(String).filter(s => /^\d{4}$/.test(s)).sort();
  const m = VM.model || ALL.model, mk = VM.market_ml || ALL.market_ml;
  let h = '<div class="card"><div class="card-header">The game model against the closing line <span class="card-sub">Walk-forward' + (seasons.length ? ' ' + seasons[0] + '–' + seasons[seasons.length - 1] : '') +
    ': team strength refitted before every week from earlier games only, the game model\'s coefficients refitted on earlier rows; y = 1 when the home team wins' + (k.isNum(G.ties_excluded) ? ' (' + G.ties_excluded + ' ties left out)' : '') + '.</span><span class="gq-ctl"><select id="cal-scope"><option value="vm">games with a closing moneyline</option><option value="all">every game</option>' + seasons.slice().reverse().map(s => '<option value="s' + s + '">' + s + '</option>').join('') + '</select></span></div>';
  h += k.tiles([k.tile('Games scored', k.int(G.games || (ALL.model || {}).n), seasons.length ? seasons.length + ' seasons' : ''),
    m ? k.tile('Model log-loss', k.num(m.logloss, 4), 'Brier ' + k.num(m.brier, 4) + ' · same games as the close') : '',
    mk ? k.tile('Closing moneyline', k.num(mk.logloss, 4), 'de-vigged · Brier ' + k.num(mk.brier, 4)) : '',
    k.isNum((G.margin_rmse || {}).model_on_line_games) ? k.tile('Margin RMSE', k.num(G.margin_rmse.model_on_line_games, 2), 'closing spread ' + k.num(G.margin_rmse.market_line, 2) + ' points') : '',
    k.tile('Coin flip', k.num(Math.LN2, 4), 'log-loss of 50/50')]);
  h += '<div class="gq-pad" id="cal-table"></div>';
  h += '<div class="grid-2"><div><div class="gq-sub-head">Reliability: who wins</div><div id="cal-rel" class="gf-chart"></div></div><div><div class="gq-sub-head">Log-loss by season</div><div id="cal-years" class="gf-chart"></div></div></div>';
  const books = G.books || {};
  if (Object.keys(books).length) h += '<div class="gq-sub-head">ESPN closing lines by book (2017 on), each against the model on the same games</div><div id="cal-books"></div>';
  h += '<div class="grid-2"><div><div class="gq-sub-head">Against the spread: P(home covers the closing spread)</div><div id="cal-ats"></div><div id="cal-ats-c" class="gf-chart"></div></div>' +
    '<div><div class="gq-sub-head">Totals: P(over the closing total)</div><div id="cal-tot"></div><div id="cal-tot-c" class="gf-chart"></div></div></div>';
  if (G.hfa_by_season && Object.keys(G.hfa_by_season).length > 2) h += '<div class="gq-sub-head">Home-field advantage by season (points, fitted)</div><div id="cal-hfa" class="gf-chart"></div>';
  h += '</div>';
  out.push(h);
  if (m && mk && k.isNum(m.logloss) && k.isNum(mk.logloss)) {
    const v = verdict(m.logloss, mk.logloss, true);
    const elo = VM.elo, ro = VM.model_ratings_only;
    read.push('<p><strong>Against the closing moneyline.</strong> On the ' + k.int(Math.min(m.n || 0, mk.n || 0)) + ' games with a closing moneyline the game model scores ' + k.num(m.logloss, 4) + ' and the de-vigged close ' + k.num(mk.logloss, 4) + ': ' +
      (v === 'tie' ? 'a tie, within the noise. ' : v === 'win' ? 'the model is sharper by ' + k.num(mk.logloss - m.logloss, 4) + ', which would be remarkable against a closing line: treat it as provisional until it survives more seasons. ' : 'the closing line is sharper by ' + k.num(m.logloss - mk.logloss, 4) + ' a game, the expected order: the close knows injuries, weather and money that the model reads late or not at all. ') +
      (elo && k.isNum(elo.logloss) ? 'Against FiveThirtyEight-style Elo (' + k.num(elo.logloss, 4) + ') the model is ' + ({ tie: 'level (a tie)', win: 'better', lose: 'worse' })[verdict(m.logloss, elo.logloss, true)] + '; ' : '') +
      (ro && k.isNum(ro.logloss) ? 'against ratings alone (' + k.num(ro.logloss, 4) + ') ' + ({ tie: 'level (a tie)', win: 'better', lose: 'worse' })[verdict(m.logloss, ro.logloss, true)] + '.' : '') + '</p>');
  }
  [[G.ats, 'covers', 'Against the spread'], [G.totals, 'overs', 'Totals']].forEach(z => { if (z[0] && z[0].n) side(null, null, z[0], z[1], read, z[2], true); });
  const MR = G.margin_rmse || {};
  if (k.isNum(MR.model_on_line_games) && k.isNum(MR.market_line)) {
    const v = verdict(MR.model_on_line_games, MR.market_line, true);
    read.push('<p><strong>The margin.</strong> The model\'s expected margin misses the final margin by ' + k.num(MR.model_on_line_games, 2) + ' points (RMSE) against ' + k.num(MR.market_line, 2) + ' for the closing spread on the same games: ' + (v === 'tie' ? 'a tie.' : v === 'win' ? 'closer than the market.' : 'the market is closer by ' + k.num(MR.model_on_line_games - MR.market_line, 2) + ' points.') + ' NFL margins are noisy: even a perfect forecaster would miss by about 13 points.</p>');
  }
  setTimeout(() => {
    const drawT = v => {
      let src = v === 'all' ? ALL : VM;
      if (v.charAt(0) === 's') src = scorers((G.per_season || {})[v.slice(1)] || {});
      k.set('cal-table', scoreTable(src));
    };
    drawT('vm');
    const sel = k.$('cal-scope');
    if (sel) sel.onchange = e => drawT(e.target.value);
    const rel = ['model', 'market_ml', 'elo'].filter(x => ALL[x] && ALL[x].bins.length).map(x => ({ name: lab(x), colour: COL[x] || '#8b949e', bins: ALL[x].bins }));
    if (rel.length) k.reliability('cal-rel', rel, { xt: 'Forecast P(home win)', yt: 'Home win rate', minN: 20 }); else k.set('cal-rel', k.muted('No reliability bins.'));
    const node = k.$('cal-years'), PS = G.per_season || {};
    if (node && seasons.length > 1) {
      const names = Object.keys(ALL);
      k.plot(node, names.map(x => ({ type: 'scatter', mode: 'lines+markers', name: lab(x), x: seasons, y: seasons.map(s => ((PS[s] || {})[x] || {}).logloss), line: { color: COL[x] || '#8b949e', width: 2, dash: /market/.test(x) ? 'dot' : 'solid' }, connectgaps: false }))
        .concat([{ type: 'scatter', mode: 'lines', name: 'Coin', x: seasons, y: seasons.map(() => Math.LN2), line: { color: '#6e7681', dash: 'dot', width: 1 } }]), k.layout(Object.assign({ margin: { l: 56, r: 10, t: 30, b: 36 }, yaxis: { title: 'Log-loss', tickformat: '.3f' }, xaxis: { type: 'category' } }, k.legendTop())));
    } else if (node) { node.innerHTML = k.muted('One season only.'); node.style.height = 'auto'; }
    if (Object.keys(books).length) {
      k.set('cal-books', k.table([{ label: 'Book' }, { label: 'Games', align: 'right' }, { label: 'Book log-loss', align: 'right' }, { label: 'Model, same games', align: 'right' }, { label: 'Model v book', sortable: false }],
        Object.keys(books).map(b => { const x = books[b], bk = x.book || {}, mo = x.model_same_games || {};
          return [{ v: b, html: '<strong>' + k.esc(b) + '</strong>' }, { v: bk.n, html: k.int(bk.n) }, { v: bk.logloss, html: k.num(bk.logloss, 4) }, { v: mo.logloss, html: k.num(mo.logloss, 4) }, { v: '', html: vchip(verdict(mo.logloss, bk.logloss, true)) }]; }), { compact: true }));
    }
    side('cal-ats', 'cal-ats-c', G.ats, 'covers', [], 'Against the spread');
    side('cal-tot', 'cal-tot-c', G.totals, 'overs', [], 'Totals');
    if (G.hfa_by_season && k.$('cal-hfa')) { const xs = Object.keys(G.hfa_by_season).sort(); k.plot('cal-hfa', [{ type: 'scatter', mode: 'lines+markers', x: xs, y: xs.map(s => G.hfa_by_season[s]), line: { color: k.ACC, width: 2 }, hovertemplate: '%{x}: %{y:.2f} points<extra></extra>' }], k.layout({ margin: { l: 50, r: 10, t: 10, b: 36 }, yaxis: { title: 'Points', rangemode: 'tozero' }, xaxis: { type: 'category' } })); }
  }, 0);
}
function note(x) { return x && x.note ? '<div class="pg-note gq-note">' + K().esc(x.note) + '</div>' : ''; }

/* A side market (ATS or totals): the probability scored against a coin, and the record of the side the model leans to. */
function side(id, cid, A, what, read, title, textOnly) {
  const k = K();
  if (!textOnly && (!A || !A.n)) { k.set(id, k.muted('Not scored yet.')); const n = k.$(cid); if (n) n.style.display = 'none'; return; }
  const coin = k.isNum(A.logloss_coin) ? A.logloss_coin : Math.LN2;
  const v = verdict(A.logloss, coin, true);
  const pk = A.picks_p55 || {};
  const se = k.isNum(pk.win_rate) && pk.n ? Math.sqrt(pk.win_rate * (1 - pk.win_rate) / pk.n) : null;
  const pv = k.isNum(pk.win_rate) ? verdict(pk.win_rate, 0.5, false, se) : null;
  let h = k.tiles([k.tile('Scored', k.int(A.n), 'pushes left out'), k.tile('Log-loss', k.num(A.logloss, 4), 'coin ' + k.num(coin, 4) + ' · ' + (v === 'tie' ? 'a tie' : v === 'win' ? 'better than a coin' : 'worse than a coin')),
    k.isNum(pk.win_rate) ? k.tile('Model\'s side (P ≥ 55%)', k.pct(pk.win_rate, 1), k.int(pk.n) + ' games' + (se ? ' · ±' + k.num(200 * se, 1) + ' pp (2 SE)' : '') + ' · break-even at −110 is 52.4%') : '']);
  if (k.isNum(A.rmse_model_total)) h += '<div class="pg-note gq-note">Total points RMSE: model ' + k.num(A.rmse_model_total, 2) + ', closing total ' + k.num(A.rmse_market_total, 2) + ' (' + ({ tie: 'a tie', win: 'model closer', lose: 'market closer' })[verdict(A.rmse_model_total, A.rmse_market_total, true)] + ').</div>';
  if (!textOnly) {
  k.set(id, h.replace('kpi-grid gq-tiles', 'kpi-grid gq-tiles gq-tiles-3'));
  const bins = binsOf(A);
  if (bins.length) k.reliability(cid, [{ name: title, colour: '#c8834a', bins: bins }], { xt: 'Model probability', yt: 'Observed rate', minN: 20, min: 0.2, max: 0.8 });
  else { const n = k.$(cid); if (n) n.style.display = 'none'; }
  }
  read.push('<p><strong>' + title + '.</strong> Against the closing ' + (what === 'covers' ? 'spread' : 'total') + ', the model\'s probability scores ' + k.num(A.logloss, 4) + ' against a coin\'s ' + k.num(coin, 4) + ' over ' + k.int(A.n) + ' games: ' +
    (v === 'tie' ? 'a tie with a coin, which is what a closing line should allow. ' : v === 'win' ? 'better than a coin. ' : 'worse than a coin: the model adds noise to the closing number here. ') +
    (k.isNum(pk.win_rate) ? 'Where it leans 55% or more, its side ' + (what === 'covers' ? 'covered' : 'won') + ' ' + k.pct(pk.win_rate, 1) + ' of ' + k.int(pk.n) + (se ? ' (±' + k.num(200 * se, 1) + ' points)' : '') + ': ' + (pv === 'tie' ? 'a tie with 50%.' : pv === 'win' ? (pk.win_rate < 0.524 ? 'above 50% but below the 52.4% that −110 prices need.' : 'above the 52.4% break-even; treat as provisional.') : 'below 50%.') : '') + '</p>');
}

/* Season odds (calibration.json "season_sim": {metrics: {playoffs, div, bye, conf, sb: score + by_week}, n_sims, check_weeks}). */
function seasonOdds(d, out, read) {
  const k = K();
  const X = get(d, ['season_sim', 'season_odds']);
  const M = X && (X.metrics || X);
  if (!M || typeof M !== 'object' || !Object.keys(M).some(x => isScorer(M[x]))) { out.push(k.card('Season odds', '', k.muted('Season-odds calibration (playoff, division, bye, conference and Super Bowl odds at fixed weeks of past seasons, against what happened) is not published yet.'))); return; }
  const NAME = { playoffs: 'Make the playoffs', div: 'Win the division', bye: 'Earn the bye (1 seed)', conf: 'Reach the Super Bowl', sb: 'Win the Super Bowl' };
  const rows = {};
  Object.keys(M).forEach(x => { if (isScorer(M[x])) rows[x] = scorers({ x: M[x] }).x; });
  let h = '<div class="card"><div class="card-header">Season odds <span class="card-sub">' + (X.n_sims ? k.int(X.n_sims) + ' simulations' : 'Simulations') + ' run before weeks ' + (X.check_weeks || [1, 5, 10, 14]).join(', ') + ' of each completed season with ratings and coefficients fitted strictly before, scored against what happened. Base-rate log-loss (always forecasting the league share) is the bar to beat.</span></div><div class="gq-pad">';
  h += k.table([{ label: 'Market' }, { label: 'Team-checkpoints', align: 'right' }, { label: 'Log-loss', align: 'right' }, { label: 'Base rate', align: 'right', title: 'Log-loss of always forecasting the share that happened' }, { label: 'Brier', align: 'right' }, { label: 'v base rate', sortable: false }].concat((X.check_weeks || []).map(w => ({ label: 'Week ' + w, align: 'right' }))),
    Object.keys(rows).map(x => { const r = M[x], b = r.base_rate, H = k.isNum(b) && b > 0 && b < 1 ? -(b * Math.log(b) + (1 - b) * Math.log(1 - b)) : null;
      return [{ v: x, html: '<strong>' + k.esc(NAME[x] || lab(x)) + '</strong>' }, { v: r.n, html: k.int(r.n) }, { v: r.logloss, html: k.num(r.logloss, 4) }, { v: H, html: k.num(H, 4) }, { v: r.brier, html: k.num(r.brier, 4) }, { v: '', html: H ? vchip(verdict(r.logloss, H, true)) : '' }]
        .concat((X.check_weeks || []).map(w => ({ v: ((r.by_week || {})[String(w)] || {}).logloss, html: k.num(((r.by_week || {})[String(w)] || {}).logloss, 4) }))); }), { compact: true }) + '</div><div id="cal-so" class="gf-chart"></div></div>';
  out.push(h);
  const pl = M.playoffs;
  if (pl && k.isNum(pl.logloss) && k.isNum(pl.base_rate)) { const b = pl.base_rate, H = -(b * Math.log(b) + (1 - b) * Math.log(1 - b)); read.push('<p><strong>Season odds.</strong> Playoff odds score ' + k.num(pl.logloss, 4) + ' against ' + k.num(H, 4) + ' for the base rate over ' + k.int(pl.n) + ' team-checkpoints (' + ({ tie: 'a tie', win: 'better', lose: 'worse' })[verdict(pl.logloss, H, true)] + '); the gain grows as the season goes on and the standings fill in.</p>'); }
  setTimeout(() => {
    const ser = Object.keys(rows).filter(x => rows[x].bins.length).slice(0, 5).map((x, i) => ({ name: NAME[x] || x, colour: k.PALETTE[i], bins: rows[x].bins }));
    if (ser.length) k.reliability('cal-so', ser, { minN: 10 }); else { const n = k.$('cal-so'); if (n) n.style.display = 'none'; }
  }, 0);
}

/* EP / WP against nflfastR: {all, pre_2020, from_2020, by_season, by_quarter}. */
function playModels(d, out, read) {
  const k = K();
  const EP = get(d, ['ep', 'ep_wp.ep', 'models.ep', 'play_models.ep', 'validation.ep']);
  const WP = get(d, ['wp', 'ep_wp.wp', 'models.wp', 'play_models.wp', 'validation.wp']);
  if (!EP && !WP) { out.push(k.card('Expected points and win probability against nflfastR', '', k.muted('The comparison of our EP and WP models with nflfastR\'s published values is not in this build yet.'))); return; }
  let h = '<div class="card"><div class="card-header">Expected points and win probability against nflfastR <span class="card-sub">Our models (cross-fitted: no play is scored by a model that saw it) against nflfastR\'s published values on the same plays, 1999 on. nflfastR\'s models were fitted on 1999–2019, so its numbers on those seasons are in-sample and flatter it.</span></div>';
  const SPLITS = [['all', 'All seasons'], ['pre_2020', '1999–2019 (nflfastR in-sample)'], ['from_2020', '2020 on (out of sample for both)']];
  const one = (X, title, kind) => {
    if (!X) return '';
    let s = '<div class="gq-sub-head">' + title + '</div>';
    const rows = [];
    SPLITS.forEach(sp => { const b = X[sp[0]]; if (!b) return; const z = scorers(b); Object.keys(z).forEach(m => { if (m === 'ours_common') return; rows.push({ split: sp[1], m: m, v: z[m], n: k.first(b.n_common, b.n) }); }); });
    if (!rows.length) return s + k.muted('Not published.');
    const ours = {}; rows.forEach(r => { if (r.m === 'ours') ours[r.split] = r.v; });
    s += k.table([{ label: 'Seasons' }, { label: 'Model' }, { label: 'Plays', align: 'right' }, { label: kind === 'ep' ? 'Log-loss (next score)' : 'Log-loss', align: 'right' }].concat(kind === 'ep' ? [{ label: 'EP MSE', align: 'right' }] : [{ label: 'Brier', align: 'right' }]).concat([{ label: 'Ours v this', sortable: false }]),
      rows.map(r => [{ v: r.split, html: k.esc(r.split) }, { v: r.m, html: '<span class="gq-dotc" style="background:' + (COL[r.m] || '#8b949e') + '"></span>' + k.esc(lab(r.m)) + (r.m === 'nflfastr_vegas_wp' ? ' <span class="gq-tag" title="nflfastR\'s WP that also uses the pre-game spread, like ours">uses the spread</span>' : '') }, { v: r.n, html: k.int(r.n) },
        { v: r.v.logloss, html: k.num(r.v.logloss, 4) }, kind === 'ep' ? { v: epMse(X, r), html: k.num(epMse(X, r), 2) } : { v: r.v.brier, html: k.num(r.v.brier, 4) },
        { v: '', html: r.m === 'ours' || !ours[r.split] ? '' : vchip(verdict(ours[r.split].logloss, r.v.logloss, true)) }]), { compact: true });
    return s;
  };
  h += '<div class="gq-pad">' + one(EP, 'Expected points: the next scoring event', 'ep') + one(WP, 'Win probability', 'wp') + '</div>';
  h += '<div class="grid-2"><div><div class="gq-sub-head">Win probability reliability</div><div id="cal-wp-rel" class="gf-chart"></div></div><div><div class="gq-sub-head">Win-probability log-loss by season</div><div id="cal-wp-yr" class="gf-chart"></div></div></div>';
  h += '<div class="grid-2"><div><div class="gq-sub-head">EP calibration: predicted against the realised next score</div><div id="cal-ep-rel" class="gf-chart"></div></div><div><div class="gq-sub-head">Win-probability log-loss by quarter</div><div id="cal-wp-q" class="gf-chart"></div></div></div></div>';
  out.push(h);
  // reading
  const wa = (WP || {}).all || {}, ea = (EP || {}).all || {}, ef = (EP || {}).from_2020 || {}, wf = (WP || {}).from_2020 || {};
  const say = (name, a, b, bName) => { const v = verdict(a, b, true); return v === 'tie' ? 'a tie with ' + bName + ' (' + k.num(a, 4) + ' against ' + k.num(b, 4) + ')' : (v === 'win' ? 'better than ' : 'worse than ') + bName + ' (' + k.num(a, 4) + ' against ' + k.num(b, 4) + ')'; };
  const parts = [];
  if (k.isNum((ea.ours || {}).logloss) && k.isNum((ea.nflfastr || {}).logloss)) parts.push('Our expected-points model\'s next-score log-loss is ' + say('EP', ea.ours.logloss, ea.nflfastr.logloss, 'nflfastR\'s') + ' over all seasons' + (k.isNum((ef.ours || {}).logloss) && k.isNum((ef.nflfastr || {}).logloss) ? ', and ' + say('EP', ef.ours.logloss, ef.nflfastr.logloss, 'nflfastR\'s') + ' from 2020, where neither model saw the plays' : '') + '.');
  if (k.isNum((wa.ours || {}).logloss)) {
    let s = 'Our win probability scores ' + k.num(wa.ours.logloss, 4) + ' over ' + k.int(wa.n) + ' plays';
    if (k.isNum((wa.nflfastr_wp || {}).logloss)) s += ': ' + say('WP', (wa.ours_common || wa.ours).logloss, wa.nflfastr_wp.logloss, 'nflfastR\'s plain wp, which does not know the pre-game spread');
    if (k.isNum((wa.nflfastr_vegas_wp || {}).logloss)) s += ', and ' + say('WP', (wa.ours_common || wa.ours).logloss, wa.nflfastr_vegas_wp.logloss, 'nflfastR\'s vegas_wp, which does, the fair comparison');
    if (k.isNum((wf.ours || {}).logloss) && k.isNum((wf.nflfastr_vegas_wp || {}).logloss)) s += '. From 2020, out of sample for both, it is ' + say('WP', (wf.ours_common || wf.ours).logloss, wf.nflfastr_vegas_wp.logloss, 'vegas_wp');
    parts.push(s + '.');
  }
  if (parts.length) read.push('<p><strong>Expected points and win probability.</strong> ' + parts.join(' ') + ' Differences in the fourth decimal place are within the noise of a million plays\' correlated outcomes (plays in one game share its result), so only clear gaps count.</p>');
  setTimeout(() => {
    if (WP && WP.all) { const z = scorers(WP.all); const ser = Object.keys(z).filter(m => z[m].bins.length && m !== 'ours_common').map(m => ({ name: lab(m), colour: COL[m] || '#8b949e', bins: z[m].bins })); if (ser.length) k.reliability('cal-wp-rel', ser, { xt: 'Forecast WP', yt: 'Observed win rate', minN: 50 }); else k.set('cal-wp-rel', k.muted('No bins.')); } else k.set('cal-wp-rel', k.muted('Not published.'));
    bySeries('cal-wp-yr', (WP || {}).by_season, true);
    bySeries('cal-wp-q', (WP || {}).by_quarter, false);
    const eb = (((EP || {}).all || {}).ours || {}).ep_calibration;
    const enf = (((EP || {}).all || {}).nflfastr || {}).ep_calibration;
    if (eb && (eb.bins || []).length) {
      const pts = b => (b.bins || []).map(r => (Array.isArray(r) ? { x: r[1], y: r[2], n: r[3] } : r));
      const lo = -3, hi = 7;
      const tr = [{ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
      [[eb, 'Ours', '#c8834a'], [enf, 'nflfastR', '#58a6ff']].forEach(z => { if (z[0] && (z[0].bins || []).length) { const p = pts(z[0]); tr.push({ type: 'scatter', mode: 'lines+markers', name: z[1], x: p.map(r => r.x), y: p.map(r => r.y), line: { color: z[2], width: 1.5 }, marker: { size: 7 }, hovertemplate: z[1] + ': EP %{x:.2f}, realised %{y:.2f}<extra></extra>' }); } });
      k.plot('cal-ep-rel', tr, k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 40 }, xaxis: { title: 'Predicted EP', range: [lo, hi] }, yaxis: { title: 'Realised next-score value', range: [lo, hi] } }, k.legendTop())));
    } else k.set('cal-ep-rel', k.muted('Not published.'));
  }, 0);
}
function epMse(X, r) { const b = X[{ 'All seasons': 'all', '1999–2019 (nflfastR in-sample)': 'pre_2020', '2020 on (out of sample for both)': 'from_2020' }[r.split]] || {}; return ((b[r.m] || {}).ep_mse); }
/* {S: {n, ours, wp, vegas_wp}} -> lines. */
function bySeries(id, obj, isSeason) {
  const k = K(), node = k.$(id);
  if (!node) return;
  if (!obj || typeof obj !== 'object' || Object.keys(obj).length < 2) { node.innerHTML = k.muted('Not published.'); node.style.height = 'auto'; return; }
  const xs = Object.keys(obj).sort((a, b) => Number(a) - Number(b));
  const names = [];
  xs.forEach(x => Object.keys(obj[x] || {}).forEach(m => { if (m !== 'n' && k.isNum(obj[x][m]) && names.indexOf(m) < 0) names.push(m); }));
  k.plot(node, names.map(m => ({ type: 'scatter', mode: isSeason ? 'lines+markers' : 'lines+markers', name: lab(m), x: xs.map(x => (isSeason ? x : (Number(x) > 4 ? 'OT' : 'Q' + x))), y: xs.map(x => (obj[x] || {})[m]), line: { color: COL[m] || '#8b949e', width: 2, dash: m === 'wp' ? 'dot' : 'solid' } })),
    k.layout(Object.assign({ margin: { l: 56, r: 10, t: 30, b: 36 }, yaxis: { title: 'Log-loss', tickformat: '.3f' }, xaxis: { type: 'category' } }, k.legendTop())));
}

function fourthSection(d, out, read) {
  const k = K();
  const F = get(d, ['fourth_down', 'fourth', 'calibration_4th', 'models.fourth_down']);
  if (!F) return;
  const C = F.calibration_4th || F.conversion || F;
  const bins = binsOf(C);
  let h = '<div class="card"><div class="card-header">Fourth-down conversions <span class="card-sub">The conversion model behind every go-for-it valuation: predicted against actual conversion rates on fourth downs where teams went for it.</span></div>';
  h += k.tiles([k.tile('Attempts', k.int(k.first(C.n)), ''), k.tile('Log-loss', k.num(C.logloss, 4), k.isNum(C.logloss_base_rate) ? 'base rate ' + k.num(C.logloss_base_rate, 4) : ''), k.tile('ECE', k.num(C.ece, 4), 'calibration error')]);
  h += '<div class="grid-2"><div id="cal-4c" class="gf-chart"></div><div id="cal-4t"></div></div></div>';
  out.push(h);
  if (k.isNum(C.logloss) && k.isNum(C.logloss_base_rate)) read.push('<p><strong>Fourth-down conversions.</strong> On ' + k.int(C.n) + ' attempts the conversion model scores ' + k.num(C.logloss, 4) + ' against ' + k.num(C.logloss_base_rate, 4) + ' for the league\'s base rate (' + (verdict(C.logloss, C.logloss_base_rate, true) === 'win' ? 'better' : verdict(C.logloss, C.logloss_base_rate, true) === 'tie' ? 'a tie' : 'worse') + '), with a calibration error of ' + k.num(100 * (C.ece || 0), 1) + ' points.</p>');
  setTimeout(() => {
    if (bins.length) k.reliability('cal-4c', [{ name: 'Conversion model', colour: '#c8834a', bins: bins }], { xt: 'Predicted P(convert)', yt: 'Converted', minN: 20 }); else k.set('cal-4c', '');
    const T = C.by_togo || C.by_distance;
    if (T) k.set('cal-4t', k.table([{ label: 'Yards to go' }, { label: 'n', align: 'right' }, { label: 'Predicted', align: 'right' }, { label: 'Actual', align: 'right' }],
      Object.keys(T).map(x => [{ v: x, html: k.esc(x.replace(/^(\d+)-\1$/, '$1').replace('-99', '+')) }, { v: T[x].n, html: k.int(T[x].n) }, { v: T[x].pred, html: k.pct(T[x].pred, 1) }, { v: T[x].obs, html: k.pct(T[x].obs, 1) }]), { compact: true }));
  }, 0);
}

function render(el) {
  const k = K();
  el.innerHTML = k.muted('Loading the backtest…');
  return k.ready().then(() => GI.load('calibration.json')).then(d => {
    if (!k.alive(el)) return;
    const ok = d && d.ok !== false;
    const out = [], read = [];
    let h = '<div class="card"><div class="card-header">Calibration <span class="card-sub">Does the modelling hold up? Every number below is computed out of sample, and every comparison is with the best public alternative.' + (d && (d.generated_at || d.updated_at) ? ' Generated ' + k.esc(k.fmtDate(d.generated_at || d.updated_at, { year: true })) + '.' : '') + '</span></div>';
    if (!ok) h += '<div class="gq-read"><p>The backtest has not been published yet' + (d && d.reason ? ' (' + k.esc(String(d.reason).replace(/builder [A-Z]'s /gi, 'the ')) + ')' : '') + '. When it is, this page scores the game model against the closing spread and moneyline from 2006, against-the-spread calibration, totals and season odds, and compares our expected points and win probability with nflfastR\'s. Ties will be reported as ties.</p></div>';
    h += '<div class="card-sub-wrap"></div></div>';
    if (ok) {
      gamesSection(d, out, read);
      seasonOdds(d, out, read);
      playModels(d, out, read);
      fourthSection(d, out, read);
    }
    el.innerHTML = h + (ok ? '<div class="card"><div class="card-header">What it shows <span class="card-sub">Written from the numbers on this page; a gap smaller than the noise is called a tie.</span></div><div class="gq-read" id="cal-read"></div></div>' : '') + out.join('') +
      '<div class="card"><div class="card-header">How to read it</div><div class="gq-read"><p><strong>Log-loss</strong> is −mean(y ln p + (1 − y) ln(1 − p)), lower is better; a coin scores ln 2 = 0.6931. <strong>Brier</strong> is mean((p − y)²). <strong>Reliability</strong> bins forecasts and plots the average forecast against how often the event happened; a calibrated model sits on the diagonal. <strong>MAE</strong> is the mean absolute error in points. A difference is called a <strong>tie</strong> when it is within two standard errors (or 0.1% of the score when no standard error is published). Beating a closing line is rare; being close to it is the realistic goal. See the <a href="#/methodology/backtest">methodology</a>.</p></div></div>';
    if (ok) k.set('cal-read', read.join('') || '<p>Not enough scored games for a reading yet.</p>');
  });
}

if (typeof GI.route === 'function') { try { GI.route('calibration', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
