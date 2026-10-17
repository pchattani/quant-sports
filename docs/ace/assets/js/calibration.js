/* The Quant Ace — calibration (#/<T>/calibration): the walk-forward backtest.
 *
 * Every finished tour-level match of the covered years predicted with only the data before it,
 * by the match model (Elo and the serve/return chain blended), each of its two halves, a
 * ranking baseline, and the closing prices of Pinnacle, Bet365, the market average and the best
 * price. Shows coverage, a plain-words reading written from the numbers, the score table (all
 * matches, matches with a Pinnacle or average price, by year and by level), reliability
 * diagrams, set-score, straight-sets, tiebreak and total-games calibration, live probability
 * at set boundaries, tournament-odds calibration, the blend weights by year, and (WTA) the
 * validation of score-inferred hold and serve points won against the real WTA stats.
 *
 * Data: data/<T>/calibration.json (models/backtest.py page_copy; PAYLOADS.md "committed"). */
(function (TA) {
'use strict';

const K = () => TA.fk;
const LABELS = { model: 'Match model', elo: 'Elo', serve_return: 'Serve/return chain', rank: 'Ranking', pinnacle: 'Pinnacle closing', b365: 'Bet365 closing', avg: 'Average closing', max: 'Best price closing', bt: 'Bradley-Terry' };
const ORDER = ['model', 'elo', 'serve_return', 'rank', 'bt', 'pinnacle', 'b365', 'avg', 'max'];
const COL = { model: '#d9f24f', elo: '#bc8cff', serve_return: '#39d0d8', rank: '#8b949e', bt: '#79c0ff', pinnacle: '#f97316', b365: '#3fb950', avg: '#58a6ff', max: '#f85149' };
const BOOK = { pinnacle: 1, b365: 1, avg: 1, max: 1 };
const label = k => LABELS[k] || String(k).replace(/_/g, ' ');
const H = p => (p > 0 && p < 1 ? -(p * Math.log(p) + (1 - p) * Math.log(1 - p)) : null);

function scoreRows(src, models) {
  const k = K();
  const bestOf = key => { let b = null; models.forEach(m => { const v = (src[m] || {})[key]; if (k.isNum(v) && (b === null || v < b.v)) b = { m: m, v: v }; }); return b; };
  const bl = bestOf('logloss'), bb = bestOf('brier');
  return models.filter(m => src[m] && src[m].n).map(m => {
    const s = src[m], h0 = H(s.base_rate);
    return [{ v: ORDER.indexOf(m), html: '<span class="af-dot" style="background:' + (COL[m] || '#8b949e') + '"></span><strong>' + k.esc(label(m)) + '</strong>' + (BOOK[m] ? ' <span class="pg-tag">market</span>' : '') },
      { v: s.n, html: k.int(s.n) },
      { v: s.logloss, html: bl && bl.m === m ? '<strong class="pg-up">' + k.num(s.logloss, 4) + '</strong>' : k.num(s.logloss, 4) },
      { v: s.brier, html: bb && bb.m === m ? '<strong class="pg-up">' + k.num(s.brier, 4) + '</strong>' : k.num(s.brier, 4) },
      { v: h0 !== null && k.isNum(s.logloss) ? (h0 - s.logloss) / h0 : null, html: h0 !== null && k.isNum(s.logloss) ? k.signed(100 * (h0 - s.logloss) / h0, 1) + '%' : '—' }];
  });
}
const SCORE_COLS = [{ label: 'Forecaster' }, { label: 'Matches', align: 'right' }, { label: 'Log-loss', align: 'right', title: 'Lower is better' }, { label: 'Brier', align: 'right', title: 'Lower is better' },
  { label: 'Skill v coin', align: 'right', title: '1 − log-loss / ln 2: the improvement on calling every match 50-50' }];

/* Reliability: series [{name, colour, bins: [{lo, hi, n, mean_p, freq}]}] */
function reliability(elId, series, opts) {
  const k = K(), o = opts || {};
  const node = document.getElementById(elId);
  if (!node) return;
  const tr = [{ type: 'scatter', mode: 'lines', x: [0, o.max || 1], y: [0, o.max || 1], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
  series.forEach(s => {
    const bins = (s.bins || []).map(b => ({ x: b.mean_p, y: b.freq, n: b.n || 0, lo: b.lo, hi: b.hi })).filter(b => k.isNum(b.x) && k.isNum(b.y) && b.n >= (o.minN || 1));
    if (!bins.length) return;
    const maxN = Math.max.apply(null, bins.map(b => b.n));
    tr.push({ type: 'scatter', mode: 'lines+markers', name: s.name, x: bins.map(b => b.x), y: bins.map(b => b.y), customdata: bins.map(b => [b.n, k.pct(b.lo, 0), k.pct(b.hi, 0)]),
      marker: { size: bins.map(b => 5 + 13 * Math.sqrt(b.n / maxN)), color: s.colour }, line: { color: s.colour, width: 1.5 },
      hovertemplate: k.esc(s.name) + '<br>bin %{customdata[1]}–%{customdata[2]}: forecast %{x:.1%}, observed %{y:.1%} (n=%{customdata[0]})<extra></extra>' });
  });
  if (tr.length < 2) { node.innerHTML = k.muted('No reliability bins.'); return; }
  k.plot(node, tr, k.layout({ showlegend: true, legend: { orientation: 'h', y: -0.22, font: { color: k.C.text2, size: 10 } }, margin: { l: 55, r: 15, t: 10, b: 84 },
    xaxis: { title: 'Forecast probability (bin mean)', tickformat: '.0%', range: [0, o.max || 1] }, yaxis: { title: 'Observed frequency', tickformat: '.0%', range: [0, o.max || 1] } }));
}

function reading(d, T) {
  const k = K();
  const M = d.metrics || {}, V = d.vs_pinnacle || {}, out = [];
  const ll = (src, m) => (src[m] || {}).logloss;
  const pctOf = (a, b) => (k.isNum(a) && k.isNum(b) && b ? 100 * a / b : null);
  out.push('<p><strong>Coverage.</strong> ' + k.int(d.n_matches) + ' completed tour-level ' + k.TN(T) + ' matches from ' + (d.years || [])[0] + ' to ' + (d.years || []).slice(-1)[0] + ' were scored, each predicted with ratings fitted on matches strictly before it (the first ' + (d.warmup_years || 0) + ' years before that only warm the ratings up). ' +
    k.int(d.n_with_pinnacle) + ' of them (' + k.num(pctOf(d.n_with_pinnacle, d.n_matches), 0) + '%) have a Pinnacle closing price and ' + k.int(d.n_with_avg) + ' an average closing price. Retirements, walkovers and defaults are not scored.</p>');
  if (k.isNum(ll(M, 'model')) && k.isNum(ll(M, 'elo'))) {
    const dE = ll(M, 'elo') - ll(M, 'model'), dR = ll(M, 'rank') - ll(M, 'model');
    out.push('<p><strong>Model against the simple baselines.</strong> Over all scored matches the model\'s log-loss is ' + k.num(ll(M, 'model'), 4) + ', against ' + k.num(ll(M, 'elo'), 4) + ' for Elo alone' +
      (k.isNum(ll(M, 'serve_return')) ? ', ' + k.num(ll(M, 'serve_return'), 4) + ' for the serve/return chain alone' : '') + (k.isNum(ll(M, 'rank')) ? ' and ' + k.num(ll(M, 'rank'), 4) + ' for the ranking baseline' : '') + '. ' +
      (dE > 0 ? 'Blending the two halves beats Elo by ' + k.num(dE, 4) + ' nats a match: small, because surface Elo already carries most of what the scores say. ' : 'The blend does not beat Elo alone here. ') +
      (k.isNum(dR) ? (dR > 0 ? 'Against the ranking the gain is ' + k.num(dR, 4) + ' nats, which means the model gives the actual winner about ' + k.num(100 * (Math.exp(dR) - 1), 1) + '% more probability on average (geometric).' : 'The ranking baseline is not beaten, which is a red flag.') : '') + '</p>');
  }
  if (k.isNum(ll(V, 'model')) && k.isNum(ll(V, 'pinnacle'))) {
    const gap = ll(V, 'model') - ll(V, 'pinnacle');
    const share = k.isNum(ll(V, 'rank')) && ll(V, 'rank') > ll(V, 'pinnacle') ? (ll(V, 'rank') - ll(V, 'model')) / (ll(V, 'rank') - ll(V, 'pinnacle')) : null;
    out.push('<p><strong>Model against Pinnacle.</strong> On the ' + k.int((V.pinnacle || {}).n) + ' matches with a Pinnacle close, the model scores ' + k.num(ll(V, 'model'), 4) + ' and Pinnacle\'s de-vigged closing price ' + k.num(ll(V, 'pinnacle'), 4) +
      (k.isNum(ll(V, 'avg')) ? ' (the market average ' + k.num(ll(V, 'avg'), 4) + ', Bet365 ' + k.num(ll(V, 'b365'), 4) + ')' : '') + '. ' +
      (gap > 0 ? 'The closing market is sharper by ' + k.num(gap, 4) + ' nats a match. That is the expected order: the close knows about injuries, fatigue, form within the week and money the model never sees. ' +
        (share !== null ? 'Measured from the ranking baseline, the model closes ' + k.num(100 * share, 0) + '% of the distance to Pinnacle.' : '')
        : 'The model is at least as sharp as Pinnacle\'s close here, which would be extraordinary: treat it as a bug until proved otherwise.') + '</p>');
  }
  const bins = (((M.model || {}).reliability) || []).filter(b => b.n >= 100);
  if (bins.length) {
    const worst = bins.slice().sort((a, b) => Math.abs(b.freq - b.mean_p) - Math.abs(a.freq - a.mean_p))[0];
    const se = Math.sqrt(Math.max(1e-9, worst.mean_p * (1 - worst.mean_p)) / worst.n);
    out.push('<p><strong>Calibration.</strong> In the model\'s reliability bins (at least 100 matches), the largest gap is in the ' + k.pct(worst.lo, 0) + '–' + k.pct(worst.hi, 0) + ' bin: forecasts averaged ' + k.pct(worst.mean_p) + ' and that side won ' + k.pct(worst.freq) + ' of ' + k.int(worst.n) + ' matches, ' +
      (Math.abs(worst.freq - worst.mean_p) > 2 * se ? 'more than two standard errors (±' + k.num(200 * se, 1) + ' points) away, so a real if small miscalibration.' : 'within two standard errors (±' + k.num(200 * se, 1) + ' points), so consistent with noise.') + '</p>');
  }
  const D = d.distributions || {};
  const ss = D.straight_sets || {}, tb = D.tiebreak || {}, tg = (D.total_games || {}).mean || {};
  if (k.isNum(ss.mean_p) || k.isNum(tg['3'] && tg['3'].pred)) {
    const p3 = tg['3'] || {}, p5 = tg['5'] || {};
    out.push('<p><strong>Scorelines.</strong> ' +
      (k.isNum(ss.mean_p) ? 'The chain expected ' + k.pct(ss.mean_p) + ' of matches to finish in straight sets; ' + k.pct(ss.base_rate) + ' did. ' : '') +
      (k.isNum(tb.mean_p) ? 'It expected at least one tiebreak in ' + k.pct(tb.mean_p) + ' of matches against ' + k.pct(tb.base_rate) + ' observed. ' : '') +
      (k.isNum(p3.pred) ? 'Mean total games: ' + k.num(p3.pred, 1) + ' forecast against ' + k.num(p3.obs, 1) + ' played in best-of-3' + (k.isNum(p5.pred) ? ', ' + k.num(p5.pred, 1) + ' against ' + k.num(p5.obs, 1) + ' in best-of-5' : '') + '. ' : '') +
      (k.isNum(ss.mean_p) && ss.base_rate - ss.mean_p > 0.03 ? 'Too few straight sets and too many games point the same way: real matches are more lopsided than a chain with one fixed serve-point probability per player. Form within a match, momentum and the weaker player folding are not in the model, and the score distributions should be read with that in mind (the match-winner probability is much less affected).' : '') + '</p>');
  }
  const TT = d.tournaments || {};
  if (TT.pre && TT.pre.title) {
    const cr = TT.champion_model_rank || {};
    out.push('<p><strong>Tournament odds.</strong> ' + k.int(TT.n_events) + ' draws were simulated ' + k.int(TT.sims) + ' times each, before the first round and again at the quarter-finals. Title log-loss before the event is ' + k.num(TT.pre.title.logloss, 4) +
      (TT.qf && TT.qf.title ? ' and ' + k.num(TT.qf.title.logloss, 4) + ' at the quarter-finals' : '') + '. ' +
      (k.isNum(cr.median) ? 'The eventual champion was the model\'s favourite ' + k.pct(cr.share_favourite, 0) + ' of the time and in its top three ' + k.pct(cr.share_top3, 0) + '; the median champion was the model\'s No. ' + k.num(cr.median, 0) + '.' : '') + '</p>');
  }
  const V2 = d.validation;
  if (V2 && V2.hold && k.isNum(V2.hold.pearson)) {
    out.push('<p><strong>Inferred against real (WTA).</strong> For the ' + k.int(V2.n_players) + ' players with ' + V2.min_matches + '+ matches with WTA stats in the ' + Math.round((V2.window_days || 730) / 365) + ' years to ' + k.esc(V2.through) + ', the hold % inferred from scores alone correlates ' + k.num(V2.hold.pearson, 2) + ' with the real hold % (root-mean-square gap ' + k.num(100 * V2.hold.rmse, 1) + ' points, bias ' + k.signed(100 * V2.hold.bias, 1) + ')' +
      (V2.spw && k.isNum(V2.spw.pearson) ? ', and the implied serve points won correlates ' + k.num(V2.spw.pearson, 2) + ' with the real figure (gap ' + k.num(100 * V2.spw.rmse, 1) + ' points, bias ' + k.signed(100 * V2.spw.bias, 1) + ')' : '') +
      '. This is the check that lets the ATP pages, which have no point-level stats, lean on the inferred numbers.</p>');
  }
  return out.join('') || '<p>Not enough scored matches for a reading.</p>';
}

function render(el, params, state) {
  const k = K(), T = k.T(params, state);
  el.innerHTML = k.muted('Loading the backtest…');
  return k.ready().then(() => TA.load(T + '/calibration.json')).then(d => {
    if (!k.alive(el)) return;
    if (!d || d.ok === false || !d.metrics) { el.innerHTML = k.card('Calibration · ' + k.TN(T), '', k.notBuilt('The ' + k.TN(T) + ' backtest', d)); return; }
    const M = d.metrics, D = d.distributions || {}, TT = d.tournaments || {};
    const models = ORDER.filter(x => M[x]).concat(Object.keys(M).filter(x => ORDER.indexOf(x) < 0));
    const yrs = d.years || [];
    let h = '<div class="card"><div class="card-header">Calibration · ' + k.TN(T) + ' <span class="card-sub">Walk-forward backtest: every match predicted with ratings refitted from matches strictly before it and blend weights fitted on earlier years only, scored against what happened and against the closing market.</span></div>' +
      '<div class="kpi-grid af-tiles">' + [
        k.tile('Matches scored', k.int(d.n_matches), yrs.length ? yrs.length + ' years, ' + yrs[0] + '–' + yrs[yrs.length - 1] : ''),
        k.tile('With Pinnacle', k.int(d.n_with_pinnacle), k.isNum(d.n_matches) ? k.num(100 * d.n_with_pinnacle / d.n_matches, 0) + '% of matches' : ''),
        k.tile('Model log-loss', k.num((M.model || {}).logloss, 4), 'Elo ' + k.num((M.elo || {}).logloss, 4) + ' · rank ' + k.num((M.rank || {}).logloss, 4)),
        k.tile('Pinnacle log-loss', k.num(((d.vs_pinnacle || {}).pinnacle || {}).logloss, 4), 'model ' + k.num(((d.vs_pinnacle || {}).model || {}).logloss, 4) + ' on the same matches'),
        k.tile('Blend', d.blend_all_years && k.isNum(d.blend_all_years.w_elo) ? k.num(d.blend_all_years.w_elo, 2) + ' / ' + k.num(d.blend_all_years.w_sr, 2) : '—', 'Elo / serve-return weights on the log-odds'),
        k.tile('Refit', k.isNum(d.refit_days) ? 'every ' + d.refit_days + ' days' : '—', 'generated ' + k.esc(k.fmtDate(d.generated_at, { weekday: false })) + (k.isNum(d.runtime_s) ? ' · ' + k.num(d.runtime_s / 60, 0) + ' min run' : ''))
      ].join('') + '</div></div>';
    h += '<div class="card"><div class="card-header">What it shows <span class="card-sub">Written from the numbers below.</span></div><div class="cal-read">' + reading(d, T) + '</div></div>';
    h += '<div class="card"><div class="card-header">Scores <span class="card-sub">Log-loss −mean(y ln p + (1−y) ln(1−p)) with p clipped to [0.0001, 0.9999], and Brier mean((p−y)²); lower is better, green is best in the table. Bookmaker prices are de-vigged multiplicatively.</span>' +
      '<span class="pg-ctl">scope <select id="cal-scope"><option value="all">all scored matches</option><option value="pin">matches with a Pinnacle close</option><option value="avg">matches with an average close</option>' +
      Object.keys(d.per_level || {}).map(l => '<option value="l' + k.esc(l) + '">level: ' + k.esc(k.LEVEL_LABEL[l] || l) + '</option>').join('') +
      Object.keys(d.per_year || {}).sort().reverse().map(y => '<option value="y' + k.esc(y) + '">' + k.esc(y) + '</option>').join('') + '</select></span></div><div id="cal-table"></div>' +
      '<div class="pg-note">The ranking baseline is P = σ(b · (ln rank<sub>2</sub> − ln rank<sub>1</sub>)), unranked = 300, with b fitted on earlier years. The match model blends Elo and the serve/return chain on the log-odds scale with weights fitted on earlier years. Within each scope every forecaster is scored on the matches it has a price for, so the market rows can cover slightly fewer matches.</div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Reliability: match winner <span class="card-sub">Ten equal-width bins; marker size by matches.</span>' +
      k.toggle('cal-rel-set', [['core', 'Model, Elo, rank'], ['book', 'Model v books']], 'core') + '</div><div id="cal-rel" style="height:440px"></div></div>' +
      '<div class="card"><div class="card-header">Log-loss by year <span class="card-sub">All scored matches each year; the market rows on the matches they priced.</span></div><div id="cal-years" style="height:440px"></div></div></div>';
    h += '<div class="card"><div class="card-header">Reliability bins <span class="card-sub">The numbers behind the diagrams, with ±2 binomial standard errors at the bin\'s mean forecast.</span>' +
      '<span class="pg-ctl"><select id="cal-bin-model">' + models.map(x => '<option value="' + k.esc(x) + '">' + k.esc(label(x)) + '</option>').join('') + '</select></span></div><div id="cal-bins"></div></div>';
    h += '<div class="card"><div class="card-header">Set scores <span class="card-sub" id="cal-sets-sub"></span>' + k.toggle('cal-bo', [['3', 'Best of 3'], ['5', 'Best of 5']], '3') + '</div><div class="grid-2"><div id="cal-sets" style="height:320px"></div><div id="cal-sets-t"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Straight sets and tiebreaks <span class="card-sub">P(straight sets) and P(at least one tiebreak) from the chain, binned.</span></div><div id="cal-ss" style="height:400px"></div></div>' +
      '<div class="card"><div class="card-header">Total games <span class="card-sub">Over/under lines: forecast against observed share of overs, and the PIT histogram.</span></div><div id="cal-tg"></div><div id="cal-pit" style="height:220px"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Tournament odds <span class="card-sub" id="cal-tour-sub"></span>' + k.toggle('cal-tour-cp', [['pre', 'Before the draw'], ['qf', 'At the quarter-finals']], 'pre') + '</div><div id="cal-tour" style="height:420px"></div><div id="cal-tour-t"></div></div>' +
      '<div class="card"><div class="card-header">Live probability at set boundaries <span class="card-sub">The chain from each set score, scored against the result.</span></div><div id="cal-live" style="height:300px"></div><div id="cal-live-t"></div></div></div>';
    h += '<div class="card"><div class="card-header">Blend weights by year <span class="card-sub">Fitted on all earlier years and used for the next one: logit p = w<sub>Elo</sub> · logit p<sub>Elo</sub> + w<sub>SR</sub> · logit p<sub>SR</sub>. Also the ranking baseline\'s slope b.</span></div><div id="cal-blend" style="height:300px"></div></div>';
    if (d.validation || T === 'wta') h += '<div class="card"><div class="card-header">Inferred against real <span class="card-sub">Hold % and serve points won inferred from scores alone (the WTA stats switched off) against the WTA\'s real point-level numbers, per player.</span>' +
      k.toggle('cal-val', [['hold', 'Hold %'], ['spw', 'Serve points won %']], 'hold') + '</div><div class="grid-2"><div id="cal-val-chart" style="height:440px"></div><div id="cal-val-t"></div></div></div>';
    h += '<div class="card"><div class="card-header">Notes <span class="card-sub">From the backtest itself.</span></div><div class="pad doc-body"><ul>' + (d.notes || []).map(n => '<li>' + k.esc(n) + '</li>').join('') +
      '<li>Each match is oriented to a side picked by a hash of its id, so "player 1" is a coin toss and the base rate sits near 50%.</li><li>Details in the <a href="#/methodology/backtest">methodology</a>.</li></ul>' +
      '<p class="muted-inline">Backtest ' + k.esc(d.version || '') + ', generated ' + k.esc(d.generated_at || '') + '.</p></div></div>';
    el.innerHTML = h;

    // Scores.
    const drawTable = scope => {
      let src = M;
      if (scope === 'pin') src = d.vs_pinnacle || {};
      else if (scope === 'avg') src = d.vs_avg || {};
      else if (scope.charAt(0) === 'l') src = (d.per_level || {})[scope.slice(1)] || {};
      else if (scope.charAt(0) === 'y') src = (d.per_year || {})[scope.slice(1)] || {};
      document.getElementById('cal-table').innerHTML = k.table(SCORE_COLS, scoreRows(src, ORDER.filter(x => src[x]).concat(Object.keys(src).filter(x => ORDER.indexOf(x) < 0))), { compact: true });
      k.sortable('cal-table');
    };
    drawTable('all');
    document.getElementById('cal-scope').onchange = e => drawTable(e.target.value);

    const drawRel = set => reliability('cal-rel', (set === 'book' ? ['model', 'pinnacle', 'avg'] : ['model', 'elo', 'serve_return', 'rank']).filter(x => M[x]).map(x => ({ name: label(x), colour: COL[x], bins: M[x].reliability })));
    drawRel('core');
    k.wireToggle(el, 'cal-rel-set', drawRel);

    const PY = d.per_year || {}, ys = Object.keys(PY).sort();
    if (ys.length) k.plot('cal-years', ['model', 'elo', 'rank', 'pinnacle', 'avg'].filter(x => ys.some(y => (PY[y][x] || {}).n)).map(x => ({
      type: 'scatter', mode: 'lines+markers', name: label(x), x: ys, y: ys.map(y => (PY[y][x] || {}).logloss), line: { color: COL[x], width: x === 'model' ? 2.6 : 1.5, dash: BOOK[x] ? 'dot' : 'solid' }, marker: { size: 5 },
      hovertemplate: '%{x}: ' + label(x) + ' %{y:.4f}<extra></extra>' })), k.layout(Object.assign(k.legendTop(), { margin: { l: 55, r: 10, t: 34, b: 36 }, xaxis: { type: 'category' }, yaxis: { title: 'Log-loss' } })));
    else document.getElementById('cal-years').innerHTML = k.muted('No per-year scores.');

    const drawBins = () => {
      const v = document.getElementById('cal-bin-model').value;
      const bins = ((M[v] || {}).reliability || []);
      document.getElementById('cal-bins').innerHTML = bins.length ? k.table([{ label: 'Bin' }, { label: 'Forecasts', align: 'right' }, { label: 'Mean forecast', align: 'right' }, { label: 'Observed', align: 'right' }, { label: 'Gap', align: 'right' }, { label: '±2 se', align: 'right' }],
        bins.map(b => { const se = Math.sqrt(Math.max(1e-9, b.mean_p * (1 - b.mean_p)) / Math.max(1, b.n)), gap = b.freq - b.mean_p;
          return [k.pct(b.lo, 0) + '–' + k.pct(b.hi, 0), { v: b.n, html: k.int(b.n) }, { v: b.mean_p, html: k.pct(b.mean_p) }, { v: b.freq, html: k.pct(b.freq) },
            { v: gap, html: '<span class="' + (Math.abs(gap) > 2 * se ? 'pg-down' : '') + '">' + k.signed(100 * gap, 1) + ' pts</span>' }, { v: 2 * se, html: '±' + k.num(200 * se, 1) + ' pts' }]; }), { compact: true })
        : k.muted('No bins for this forecaster.');
    };
    document.getElementById('cal-bin-model').onchange = drawBins;
    drawBins();

    // Set scores.
    const drawSets = bo => {
      const S = ((D.set_scores || {})[bo]) || {};
      const keys = Object.keys(S).sort((a, b) => { const x = a.split('-').map(Number), y = b.split('-').map(Number); return (y[0] - y[1]) - (x[0] - x[1]); });
      const sub = document.getElementById('cal-sets-sub');
      if (!keys.length) { document.getElementById('cal-sets').innerHTML = k.muted('No best-of-' + bo + ' matches.'); document.getElementById('cal-sets-t').innerHTML = ''; sub.textContent = ''; return; }
      const n = (S[keys[0]] || {}).n;
      sub.innerHTML = 'Forecast against observed share of each set score, best of ' + bo + ', ' + k.int(n) + ' matches' + (k.isNum((D.set_score_logloss || {})[bo]) ? ' · multi-class log-loss ' + k.num(D.set_score_logloss[bo], 3) : '') + '. Player 1 is a coin toss, so mirror scores should match.';
      k.plot('cal-sets', [
        { type: 'bar', name: 'Forecast', x: keys, y: keys.map(s => S[s].pred), marker: { color: '#d9f24f' }, hovertemplate: '%{x}: forecast %{y:.1%}<extra></extra>' },
        { type: 'bar', name: 'Observed', x: keys, y: keys.map(s => S[s].obs), marker: { color: '#58a6ff' }, hovertemplate: '%{x}: observed %{y:.1%}<extra></extra>' }
      ], k.layout(Object.assign(k.legendTop(), { barmode: 'group', margin: { l: 44, r: 10, t: 30, b: 34 }, xaxis: { type: 'category' }, yaxis: { tickformat: '.0%' } })));
      document.getElementById('cal-sets-t').innerHTML = k.table([{ label: 'Sets' }, { label: 'Forecast', align: 'right' }, { label: 'Observed', align: 'right' }, { label: 'Gap', align: 'right' }],
        keys.map(s => [s, { v: S[s].pred, html: k.pct(S[s].pred, 1) }, { v: S[s].obs, html: k.pct(S[s].obs, 1) }, { v: S[s].obs - S[s].pred, html: k.signed(100 * (S[s].obs - S[s].pred), 1) + ' pts' }]), { compact: true });
    };
    drawSets('3');
    k.wireToggle(el, 'cal-bo', drawSets);

    reliability('cal-ss', [{ name: 'Straight sets', colour: '#d9f24f', bins: (D.straight_sets || {}).reliability }, { name: 'At least one tiebreak', colour: '#bc8cff', bins: (D.tiebreak || {}).reliability }], { minN: 20 });

    const TG = D.total_games || {}, OL = TG.over_lines || {};
    const olk = Object.keys(OL).sort((a, b) => { const x = a.split('_'), y = b.split('_'); return x[0] === y[0] ? Number(x[1]) - Number(y[1]) : x[0].localeCompare(y[0]); });
    document.getElementById('cal-tg').innerHTML = olk.length ? k.table([{ label: 'Line' }, { label: 'Matches', align: 'right' }, { label: 'P(over) forecast', align: 'right' }, { label: 'Over observed', align: 'right' }, { label: 'Gap', align: 'right' }, { label: 'Log-loss', align: 'right' }],
      olk.map(x => { const o = OL[x], p = x.split('_'); return [{ v: x, html: (p[0] === 'bo5' ? 'Best of 5 ' : 'Best of 3 ') + 'over ' + k.esc(p[1]) }, { v: o.n, html: k.int(o.n) }, { v: o.mean_p, html: k.pct(o.mean_p, 1) }, { v: o.base_rate, html: k.pct(o.base_rate, 1) },
        { v: o.base_rate - o.mean_p, html: '<span class="' + (Math.abs(o.base_rate - o.mean_p) > 0.03 ? 'pg-down' : '') + '">' + k.signed(100 * (o.base_rate - o.mean_p), 1) + ' pts</span>' }, { v: o.logloss, html: k.num(o.logloss, 4) }]; }), { compact: true }) +
      '<div class="pg-note">Mean total games: ' + Object.keys(TG.mean || {}).map(b => 'best of ' + b + ' ' + k.num(TG.mean[b].pred, 1) + ' forecast v ' + k.num(TG.mean[b].obs, 1) + ' played').join('; ') + (k.isNum(D.handicap_logloss) ? '. Game-handicap log-loss ' + k.num(D.handicap_logloss, 3) : '') + '.</div>' : k.muted('No total-games lines.');
    const PIT = TG.pit_hist || {};
    if (Object.keys(PIT).length) k.plot('cal-pit', Object.keys(PIT).map((b, i) => { const tot = PIT[b].reduce((s, x) => s + x, 0) || 1; return { type: 'bar', name: 'Best of ' + b, x: PIT[b].map((_, j) => (j + 0.5) / PIT[b].length), y: PIT[b].map(x => x / tot), marker: { color: i ? '#58a6ff' : '#d9f24f' }, opacity: 0.8, hovertemplate: 'PIT %{x:.2f}: %{y:.1%}<extra>Best of ' + b + '</extra>' }; }),
      k.layout(Object.assign(k.legendTop(), { barmode: 'group', margin: { l: 44, r: 10, t: 30, b: 36 }, xaxis: { title: 'PIT of total games (flat = calibrated; a slope means a biased mean)', range: [0, 1] }, yaxis: { tickformat: '.0%' },
        shapes: [{ type: 'line', x0: 0, x1: 1, y0: 0.1, y1: 0.1, line: { color: '#6e7681', dash: 'dot', width: 1 } }] })));

    // Tournaments.
    const drawTour = cp => {
      const X = TT[cp] || {};
      document.getElementById('cal-tour-sub').textContent = k.isNum(TT.n_events) ? k.int(TT.n_events) + ' events, ' + k.int(TT.sims) + ' simulations each' : '';
      reliability('cal-tour', [['title', 'Title', '#d9f24f'], ['final', 'Final', '#58a6ff'], ['sf', 'Semi-final', '#f97316']].filter(x => X[x[0]]).map(x => ({ name: x[1], colour: x[2], bins: X[x[0]].reliability })), { minN: 10 });
      document.getElementById('cal-tour-t').innerHTML = Object.keys(X).length ? k.table([{ label: 'Reach' }, { label: 'Player-events', align: 'right' }, { label: 'Log-loss', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Mean forecast', align: 'right' }, { label: 'Base rate', align: 'right' }],
        Object.keys(X).map(x => [x === 'sf' ? 'Semi-final' : x.charAt(0).toUpperCase() + x.slice(1), { v: X[x].n, html: k.int(X[x].n) }, { v: X[x].logloss, html: k.num(X[x].logloss, 4) }, { v: X[x].brier, html: k.num(X[x].brier, 4) }, { v: X[x].mean_p, html: k.pct(X[x].mean_p, 1) }, { v: X[x].base_rate, html: k.pct(X[x].base_rate, 1) }]), { compact: true }) : k.muted('No tournament checkpoints in this file.');
    };
    drawTour('pre');
    k.wireToggle(el, 'cal-tour-cp', drawTour);

    const LV = D.live_by_sets || {};
    reliability('cal-live', [{ name: 'All set boundaries', colour: '#39d0d8', bins: (LV.all || {}).reliability }], { minN: 20 });
    const BS = LV.by_state || {};
    document.getElementById('cal-live-t').innerHTML = Object.keys(BS).length ? k.table([{ label: 'State (p1 sets first)' }, { label: 'n', align: 'right' }, { label: 'Forecast', align: 'right' }, { label: 'Won', align: 'right' }, { label: 'Log-loss', align: 'right' }],
      Object.keys(BS).sort().map(s => [k.esc(s.replace('bo3', 'Best of 3,').replace('bo5', 'Best of 5,')), { v: BS[s].n, html: k.int(BS[s].n) }, { v: BS[s].mean_p, html: k.pct(BS[s].mean_p, 1) }, { v: BS[s].base_rate, html: k.pct(BS[s].base_rate, 1) }, { v: BS[s].logloss, html: k.num(BS[s].logloss, 3) }]), { compact: true }) : '';

    // Blend.
    const BY = d.blend_by_year || {}, by = Object.keys(BY).sort(), RS = d.rank_slope_by_year || {};
    if (by.length) k.plot('cal-blend', [
      { type: 'scatter', mode: 'lines+markers', name: 'w Elo', x: by, y: by.map(y => BY[y].w_elo), line: { color: '#bc8cff', width: 2 }, hovertemplate: '%{x}: w Elo %{y:.3f}<extra></extra>' },
      { type: 'scatter', mode: 'lines+markers', name: 'w serve/return', x: by, y: by.map(y => BY[y].w_sr), line: { color: '#39d0d8', width: 2 }, hovertemplate: '%{x}: w SR %{y:.3f}<extra></extra>' },
      { type: 'scatter', mode: 'lines', name: 'Rank slope b', x: by, y: by.map(y => RS[y]), line: { color: '#8b949e', width: 1.5, dash: 'dot' }, hovertemplate: '%{x}: b %{y:.3f}<extra></extra>' }
    ], k.layout(Object.assign(k.legendTop(), { margin: { l: 44, r: 10, t: 34, b: 36 }, xaxis: { type: 'category' }, yaxis: { title: 'Weight', rangemode: 'tozero' } })));
    else document.getElementById('cal-blend').innerHTML = k.muted('No blend history.');

    // Validation.
    if (document.getElementById('cal-val-chart')) {
      const V2 = d.validation;
      const drawVal = kind => {
        const node = document.getElementById('cal-val-chart'), tab = document.getElementById('cal-val-t');
        if (!V2 || V2.error || !(V2.players || []).length) { node.innerHTML = k.muted(V2 && V2.error ? 'The validation failed in this build: ' + k.esc(V2.error) : 'The validation is not in this backtest file yet.'); tab.innerHTML = ''; return; }
        const rows = V2.players.filter(r => k.isNum(r['inf_' + kind]) && k.isNum(r['real_' + kind]));
        const xs = rows.map(r => r['inf_' + kind]), ys = rows.map(r => r['real_' + kind]);
        const lo = Math.min.apply(null, xs.concat(ys)), hi = Math.max.apply(null, xs.concat(ys));
        const maxN = Math.max.apply(null, rows.map(r => r.n || 1));
        k.plot(node, [{ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: '#6e7681', dash: 'dash', width: 1 }, hoverinfo: 'skip', showlegend: false },
          { type: 'scatter', mode: 'markers', x: xs, y: ys, customdata: rows.map(r => r.pid), text: rows.map(r => k.esc(k.name(T, r.pid)) + ' · ' + r.n + ' matches'),
            marker: { size: rows.map(r => 5 + 10 * Math.sqrt((r.n || 1) / maxN)), color: '#d9f24f', opacity: 0.75, line: { color: '#0d1117', width: 0.6 } },
            hovertemplate: '%{text}<br>inferred %{x:.1%} · real %{y:.1%}<extra></extra>' }],
          k.layout({ margin: { l: 55, r: 15, t: 10, b: 50 }, xaxis: { title: 'Inferred from scores', tickformat: '.0%' }, yaxis: { title: 'Real (WTA stats)', tickformat: '.0%' } }));
        if (node.on) node.on('plotly_click', ev => { const p = ev.points && ev.points[0]; if (p && p.customdata) location.hash = k.playerHref(T, p.customdata); });
        const st = V2[kind] || {};
        tab.innerHTML = '<div class="af-kv">' + [['Players', k.int(st.n || V2.n_players)], ['Pearson', k.num(st.pearson, 3)], ['Spearman', k.num(st.spearman, 3)], ['RMSE', k.isNum(st.rmse) ? k.num(100 * st.rmse, 1) + ' pts' : '—'], ['Bias', k.isNum(st.bias) ? k.signed(100 * st.bias, 1) + ' pts' : '—']]
          .map(x => '<div class="af-kv-i"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join('') + '</div>' +
          k.table([{ label: 'Player' }, { label: 'Matches', align: 'right' }, { label: 'Inferred', align: 'right' }, { label: 'Real', align: 'right' }, { label: 'Gap', align: 'right' }],
            rows.slice().sort((a, b) => Math.abs(b['real_' + kind] - b['inf_' + kind]) - Math.abs(a['real_' + kind] - a['inf_' + kind])).slice(0, 40).map(r => ({ _href: k.playerHref(T, r.pid), cells: [{ v: k.name(T, r.pid), html: k.playerLink(T, r.pid) }, r.n,
              { v: r['inf_' + kind], html: k.pct(r['inf_' + kind], 1) }, { v: r['real_' + kind], html: k.pct(r['real_' + kind], 1) }, { v: r['real_' + kind] - r['inf_' + kind], html: k.signed(100 * (r['real_' + kind] - r['inf_' + kind]), 1) + ' pts' }] })), { compact: true }) +
          '<div class="pg-note">The 40 largest gaps, real minus inferred. Inferred = the mean over the player\'s matches with stats of the score-only model\'s hold against that opponent (and the serve-point probability that hold implies); real = pooled from the WTA stats. Window ' + k.int(V2.window_days) + ' days to ' + k.esc(V2.through) + ', ' + V2.min_matches + '+ matches. Click a dot for the player.</div>';
        k.sortable(tab);
      };
      drawVal('hold');
      k.wireToggle(el, 'cal-val', drawVal);
    }
  });
}

if (typeof TA.route === 'function') TA.route('calibration', render);
})(window.TA || (window.TA = {}));
