/* The Quant Hardwood — calibration (#/<L>/calibration): the walk-forward backtest.
 *
 * Every finished game of the covered seasons predicted with only the data before it, by
 * the game model, the same ratings with home court only, Elo, the DraftKings closing
 * spread (ESPN pickcenter) and ESPN's own predictor where stored. Shows coverage, a
 * plain-words reading written from the numbers, the scores (log-loss, Brier, margin
 * RMSE; all games and the games with a market line), reliability diagrams, the season
 * simulation's calibration at fixed checkpoints, and live win probability against ESPN's.
 *
 * Data: data/<L>/calibration.json (models/backtest.py output + updated_at, ok; optional
 * winprob = winprob.calibration output and shots = shots.calibration_table by zone). */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const LABELS = { model: 'Game model', model_ratings_only: 'Ratings + home court only', elo: 'Elo', market: 'DraftKings spread', espn: 'ESPN predictor', model_on_market_games: 'Game model (market games)' };
const ORDER = ['model', 'model_ratings_only', 'elo', 'market', 'espn'];
const COL = { model: '#58a6ff', model_ratings_only: '#79c0ff', elo: '#bc8cff', market: '#f0883e', espn: '#3fb950' };
const label = k => LABELS[k] || HW.titleCase(k);

function scoreRows(src, models, best) {
  const fx = FX();
  const bestOf = key => { let b = null; models.forEach(m => { const v = (src[m] || {})[key]; if (fx.isNum(v) && (b === null || v < b.v)) b = { m: m, v: v }; }); return b; };
  const bl = bestOf('logloss'), bb = bestOf('brier');
  return models.filter(m => src[m] && src[m].n).map(m => {
    const s = src[m];
    const h0 = fx.isNum(s.base_rate) && s.base_rate > 0 && s.base_rate < 1 ? -(s.base_rate * Math.log(s.base_rate) + (1 - s.base_rate) * Math.log(1 - s.base_rate)) : null;
    return [{ v: label(m), html: '<strong>' + fx.esc(label(m)) + '</strong> <span class="gl-key">' + fx.esc(m) + '</span>' }, { v: s.n, html: Number(s.n).toLocaleString() },
      { v: s.logloss, html: best !== false && bl && bl.m === m ? '<strong style="color:#3fb950">' + fx.num(s.logloss, 4) + '</strong>' : fx.num(s.logloss, 4) },
      { v: s.brier, html: best !== false && bb && bb.m === m ? '<strong style="color:#3fb950">' + fx.num(s.brier, 4) + '</strong>' : fx.num(s.brier, 4) },
      { v: h0 !== null && fx.isNum(s.logloss) ? h0 - s.logloss : null, html: h0 !== null && fx.isNum(s.logloss) ? fx.signed(100 * (h0 - s.logloss) / h0, 1) + '%' : '—', title: 'Log-loss improvement on always forecasting the home win rate' },
      { v: s.base_rate, html: fx.pct(s.base_rate) }];
  });
}
const SCORE_COLS = [{ label: 'Model' }, { label: 'Games', align: 'right' }, { label: 'Log-loss', align: 'right', title: 'Lower is better' }, { label: 'Brier', align: 'right', title: 'Lower is better' }, { label: 'Skill v base rate', align: 'right', title: '1 - log-loss / log-loss of the constant home-win rate' }, { label: 'Home win rate', align: 'right' }];

/* Reliability: series [{name, colour, bins: [{mean_p|p_mean, freq|y_mean, n, lo, hi}]}] */
function reliability(elId, series) {
  const fx = FX();
  const tr = [{ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
  series.forEach(s => {
    const bins = (s.bins || []).map(b => ({ x: fx.has(b.mean_p) ? b.mean_p : b.p_mean, y: fx.has(b.freq) ? b.freq : b.y_mean, n: b.n || 0, lo: b.lo, hi: b.hi })).filter(b => fx.isNum(b.x) && fx.isNum(b.y) && b.n > 0);
    if (!bins.length) return;
    const maxN = Math.max.apply(null, bins.map(b => b.n));
    tr.push({ type: 'scatter', mode: 'lines+markers', name: s.name, x: bins.map(b => b.x), y: bins.map(b => b.y), customdata: bins.map(b => [b.n, fx.pct(b.lo, 0), fx.pct(b.hi, 0)]),
      marker: { size: bins.map(b => 6 + 14 * Math.sqrt(b.n / maxN)), color: s.colour }, line: { color: s.colour, width: 1.5 },
      hovertemplate: fx.esc(s.name) + '<br>bin %{customdata[1]}–%{customdata[2]}: forecast %{x:.1%}, observed %{y:.1%} (n=%{customdata[0]})<extra></extra>' });
  });
  if (tr.length < 2) { document.getElementById(elId).innerHTML = fx.muted('No reliability bins.'); return; }
  fx.plot(elId, tr, fx.layout({ showlegend: true, legend: { orientation: 'h', y: -0.2, font: { color: fx.C.text2 } }, margin: { l: 55, r: 15, t: 10, b: 80 },
    xaxis: { title: 'Forecast probability (bin mean)', tickformat: '.0%', range: [0, 1] }, yaxis: { title: 'Observed frequency', tickformat: '.0%', range: [0, 1] } }));
}

function reading(d, L) {
  const fx = FX();
  const M = d.metrics || {}, V = d.metrics_vs_market || {}, R = d.margin_rmse || {};
  const out = [];
  const ll = (src, m) => (src[m] || {}).logloss;
  if (fx.isNum(ll(M, 'model')) && fx.isNum(ll(M, 'elo'))) {
    const diff = ll(M, 'elo') - ll(M, 'model');
    out.push('<p><strong>Model against Elo</strong> over all ' + Number((M.model || {}).n || 0).toLocaleString() + ' games: log-loss ' + fx.num(ll(M, 'model'), 4) + ' against ' + fx.num(ll(M, 'elo'), 4) + '. ' +
      (diff > 0 ? 'The game model is better by ' + fx.num(diff, 4) + ' nats a game, so it gives the actual winner about ' + fx.num(100 * (Math.exp(diff) - 1), 1) + '% more probability on average (geometric).' : 'Elo is better by ' + fx.num(-diff, 4) + ' nats a game: the model does not yet beat the simple baseline.') + '</p>');
  }
  if (fx.isNum(ll(V, 'model')) && fx.isNum(ll(V, 'market'))) {
    const gap = ll(V, 'model') - ll(V, 'market');
    out.push('<p><strong>Model against the DraftKings spread</strong> on the ' + Number((V.market || {}).n || 0).toLocaleString() + ' games with a closing line: log-loss ' + fx.num(ll(V, 'model'), 4) + ' against ' + fx.num(ll(V, 'market'), 4) +
      (fx.isNum(ll(V, 'elo')) ? ' (Elo ' + fx.num(ll(V, 'elo'), 4) + ')' : '') + '. ' +
      (gap > 0 ? 'The market is sharper by ' + fx.num(gap, 4) + ' nats a game. That is the expected order: the closing spread has injury news, lineups and money the model does not see. ' + (fx.isNum(ll(V, 'elo')) && ll(V, 'elo') > ll(V, 'model') ? 'The model closes ' + fx.num(100 * (ll(V, 'elo') - ll(V, 'model')) / (ll(V, 'elo') - ll(V, 'market')), 0) + '% of the gap between Elo and the market.' : '')
        : 'The model is at least as sharp as the closing spread here, which is rare: treat it with suspicion until more games are scored.') + '</p>');
  }
  if (fx.isNum(R.model) || fx.isNum(R.market)) {
    out.push('<p><strong>Margin</strong>: root-mean-square error of the predicted point margin is ' + fx.num(R.model, 2) + ' points for the model' + (fx.isNum(R.elo) ? ', ' + fx.num(R.elo, 2) + ' for Elo' : '') +
      (fx.isNum(R.market) ? ' and ' + fx.num(R.market, 2) + ' for the closing spread' + (fx.isNum(R.model_on_market_games) ? ' (model ' + fx.num(R.model_on_market_games, 2) + ' on the same games)' : '') : '') + '. Most of it is irreducible: single-game margins scatter by around ' + (L === 'wnba' ? '11' : '12') + ' points around any forecast.</p>');
  }
  const bins = (((M.model || {}).reliability) || []).filter(b => b.n >= 30);
  if (bins.length) {
    const worst = bins.slice().sort((a, b) => Math.abs(b.freq - b.mean_p) - Math.abs(a.freq - a.mean_p))[0];
    const se = Math.sqrt(Math.max(1e-9, worst.mean_p * (1 - worst.mean_p)) / worst.n);
    out.push('<p><strong>Calibration</strong> (game model, bins with at least 30 games): the largest gap is in the ' + fx.pct(worst.lo, 0) + '–' + fx.pct(worst.hi, 0) + ' bin, where the forecasts averaged ' + fx.pct(worst.mean_p) + ' and the home side won ' + fx.pct(worst.freq) + ' of ' + worst.n + ' games: ' +
      (Math.abs(worst.freq - worst.mean_p) > 2 * se ? 'more than two standard errors (±' + fx.num(200 * se, 1) + ' points), so a real miscalibration.' : 'within two standard errors (±' + fx.num(200 * se, 1) + ' points), so consistent with noise.') + '</p>');
  }
  const ss = d.season_sim || {};
  if ((ss.title || {}).n) {
    const runs = (d.season_sim_runs || []).filter(r => fx.isNum(r.p_champion));
    out.push('<p><strong>Season simulation</strong>: scored at ' + runs.length + ' checkpoints (opening day and a quarter, half and three quarters of the regular season). Playoff-qualification log-loss ' + fx.num((ss.playoffs || {}).logloss, 4) + ', title ' + fx.num(ss.title.logloss, 4) +
      (runs.length ? '; the eventual champion was given ' + fx.pct(FX().mean(runs.map(r => r.p_champion))) + ' on average across checkpoints' : '') + '.</p>');
  }
  const wp = d.winprob || d.wp || d.wp_calibration;
  if (wp && wp.ours && wp.espn) {
    out.push('<p><strong>Live win probability</strong>: on ' + Number(wp.n_espn || wp.n || 0).toLocaleString() + ' play states with both numbers, our model\'s Brier is ' + fx.num((wp.ours_on_espn_rows || wp.ours).brier, 4) + ' against ESPN\'s ' + fx.num(wp.espn.brier, 4) +
      '; the two differ by ' + fx.num(100 * (wp.mean_abs_diff || 0), 1) + ' points on average.</p>');
  }
  return out.join('') || '<p>Not enough scored games for a reading.</p>';
}

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = fx.muted('Loading the backtest…');
  return fx.ready().then(() => HW.load(L + '/calibration.json')).then(d => {
    if (!fx.alive(el)) return;
    if (!d || d.ok === false || !d.metrics) { el.innerHTML = fx.card('Calibration · ' + L.toUpperCase(), '', fx.notBuilt('The ' + L.toUpperCase() + ' backtest', d)); return; }
    const M = d.metrics, V = d.metrics_vs_market || {}, R = d.margin_rmse || {};
    const models = ORDER.filter(k => M[k]).concat(Object.keys(M).filter(k => ORDER.indexOf(k) < 0));
    const seasons = d.seasons || [];
    const wp = d.winprob || d.wp || d.wp_calibration || null;
    const shots = d.shots || d.shot_calibration || null;
    let h = '<div class="card"><div class="card-header">Calibration · ' + fx.esc(L.toUpperCase()) + ' <span class="card-sub">Walk-forward backtest: every game predicted with ratings refitted from games strictly before it, coefficients fitted on earlier seasons only, scored against what happened.</span></div>' +
      '<div class="kpi-grid six" style="padding:12px 12px 0">' + [
        fx.tile('Games scored', fx.isNum(d.games) ? Number(d.games).toLocaleString() : '—', seasons.length ? seasons.length + ' seasons, ' + fx.seasonLabel(L, seasons[0]) + ' to ' + fx.seasonLabel(L, seasons[seasons.length - 1]) : ''),
        fx.tile('With a market line', fx.isNum((M.market || {}).n) ? Number(M.market.n).toLocaleString() : '—', fx.isNum((M.market || {}).n) && d.games ? fx.pct(M.market.n / d.games, 0) + ' of games (DraftKings via ESPN)' : 'no closing lines stored'),
        fx.tile('Model log-loss', fx.num((M.model || {}).logloss, 4), 'Elo ' + fx.num((M.elo || {}).logloss, 4)),
        fx.tile('Margin RMSE', fx.num(R.model, 2), 'points · market ' + fx.num(R.market, 2)),
        fx.tile('Refit', fx.isNum(d.refit_days) ? 'every ' + d.refit_days + ' days' : '—', 'ratings walk forward'),
        fx.tile('Updated', fx.esc(fx.fmtStamp(d.updated_at || d.generated_at) || '—'), fx.isNum(d.runtime_s) ? fx.num(d.runtime_s / 60, 0) + ' min run' : '')
      ].join('') + '</div>' +
      '<div class="mk-line"><strong>Seasons:</strong> ' + (seasons.map(s => fx.seasonLabel(L, s)).join(', ') || '—') + (fx.isNum((d.carryover || {}).b) ? ' · <strong>rating carry-over</strong> b = ' + fx.num(d.carryover.b, 2) + ' (net rating next season ≈ b × this season), residual sd ' + fx.num(d.carryover.se, 2) : '') + '</div></div>';
    h += '<div class="card"><div class="card-header">What it shows</div><div class="cal-read">' + reading(d, L) + '</div></div>';
    h += '<div class="card"><div class="card-header">Scores <span class="card-sub">Log-loss −mean(y ln p + (1−y) ln(1−p)), p clipped to [0.0001, 0.9999], and Brier mean((p−y)²); lower is better, green is best in the table. y = home win.</span>' +
      '<span class="pg-ctl">scope <select id="cal-scope"><option value="all">all games</option><option value="mkt">games with a market line</option>' + Object.keys(d.per_season || {}).sort().reverse().map(s => '<option value="s' + fx.esc(s) + '">' + fx.esc(fx.seasonLabel(L, Number(s))) + '</option>').join('') + '</select></span></div><div id="cal-table"></div>' +
      '<div class="pg-note"><strong>Margin RMSE</strong> (points): ' + Object.keys(R).filter(k => fx.isNum(R[k])).map(k => fx.esc(label(k)) + ' ' + fx.num(R[k], 2)).join(' · ') + '. The market\'s margin is minus the closing home spread.</div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Reliability: game winner <span class="card-sub">Forecasts in ten equal-width bins; marker size by number of games.</span></div><div id="cal-rel-game" style="height:430px"></div></div>' +
      '<div class="card"><div class="card-header">Reliability: season simulation <span class="card-sub">Playoffs, Finals and title forecasts at each checkpoint against what happened.</span></div><div id="cal-rel-sim" style="height:430px"></div></div></div>';
    h += '<div class="card"><div class="card-header">Reliability bins <span class="card-sub">The numbers behind the diagrams, with ±2 binomial standard errors at the bin\'s mean forecast.</span>' +
      '<span class="pg-ctl"><select id="cal-bin-model">' + models.map(k => '<option value="g:' + fx.esc(k) + '">' + fx.esc(label(k)) + '</option>').join('') + Object.keys(d.season_sim || {}).map(k => '<option value="s:' + fx.esc(k) + '">Season sim: ' + fx.esc(k) + '</option>').join('') + '</select></span></div><div id="cal-bins"></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Live win probability <span class="card-sub">Our in-game model against ESPN\'s per-play number, on the same play states.</span></div><div id="cal-wp" style="height:400px"></div><div id="cal-wp-t"></div></div>' +
      '<div class="card"><div class="card-header">Shot model <span class="card-sub">Made rate against the xPTS model\'s make probability by zone.</span></div><div id="cal-shots"></div></div></div>';
    h += '<div class="card"><div class="card-header">Fitted game-model coefficients <span class="card-sub">Fitted on the seasons before each one (so each season is scored out of sample).</span></div><div id="cal-params"></div></div>';
    h += '<div class="card"><div class="card-header">The baselines <span class="card-sub">What the game model has to beat.</span></div><div class="pad doc-body"><ul>' +
      '<li><strong>Ratings + home court only</strong>: the same walk-forward ratings, with rest, back-to-back, travel, time-zone and altitude terms switched off.</li>' +
      '<li><strong>Elo</strong>: game Elo from 1997 with a margin-of-victory multiplier, home court and regression between seasons; its pregame probability.</li>' +
      '<li><strong>DraftKings spread</strong>: the closing home spread from ESPN pickcenter turned into a probability, p = Φ(−spread / σ<sub>m</sub>), with σ<sub>m</sub> fitted on earlier seasons. Scored only on games with a line; the strongest public baseline.</li>' +
      '<li><strong>ESPN predictor</strong>: ESPN\'s pregame win probability where the store carries one.</li></ul>' +
      '<p>Details in the <a href="#/methodology/backtest">methodology</a> → backtest and calibration.</p></div></div>';
    el.innerHTML = h;

    const drawTable = scope => {
      let src = M, best = true;
      if (scope === 'mkt') src = V;
      else if (scope && scope.charAt(0) === 's') src = (d.per_season || {})[scope.slice(1)] || {};
      document.getElementById('cal-table').innerHTML = HW.tableHTML(SCORE_COLS, scoreRows(src, ORDER.filter(k => src[k]).concat(Object.keys(src).filter(k => ORDER.indexOf(k) < 0)), best), { compact: true });
      HW.sortable('cal-table');
    };
    drawTable('all');
    document.getElementById('cal-scope').onchange = e => drawTable(e.target.value);
    reliability('cal-rel-game', models.map(k => ({ name: label(k), colour: COL[k] || '#8b949e', bins: (M[k] || {}).reliability })));
    const SS = d.season_sim || {};
    reliability('cal-rel-sim', [['playoffs', 'Playoffs', '#58a6ff'], ['finals', 'Finals', '#f0883e'], ['title', 'Title', '#3fb950']].map(x => ({ name: x[1], colour: x[2], bins: (SS[x[0]] || {}).reliability })));
    const drawBins = () => {
      const v = document.getElementById('cal-bin-model').value;
      const bins = v.indexOf('g:') === 0 ? ((M[v.slice(2)] || {}).reliability || []) : ((SS[v.slice(2)] || {}).reliability || []);
      document.getElementById('cal-bins').innerHTML = bins.length ? HW.tableHTML([{ label: 'Bin' }, { label: 'Forecasts', align: 'right' }, { label: 'Mean forecast', align: 'right' }, { label: 'Observed', align: 'right' }, { label: 'Gap', align: 'right' }, { label: '±2 se', align: 'right' }],
        bins.map(b => { const se = Math.sqrt(Math.max(1e-9, b.mean_p * (1 - b.mean_p)) / b.n), gap = b.freq - b.mean_p;
          return [fx.pct(b.lo, 0) + '–' + fx.pct(b.hi, 0), b.n, { v: b.mean_p, html: fx.pct(b.mean_p) }, { v: b.freq, html: fx.pct(b.freq) }, { v: gap, html: '<span class="' + (Math.abs(gap) > 2 * se ? 'pg-edge-neg' : '') + '">' + fx.signed(100 * gap, 1) + ' pts</span>' }, { v: 2 * se, html: '±' + fx.num(200 * se, 1) + ' pts' }]; }), { compact: true })
        : fx.muted('No bins for this model.');
    };
    document.getElementById('cal-bin-model').onchange = drawBins;
    drawBins();
    // Win probability against ESPN.
    if (wp && (wp.ours || wp.espn)) {
      reliability('cal-wp', [{ name: 'Our model', colour: '#58a6ff', bins: (wp.ours || {}).table }, { name: 'ESPN', colour: '#3fb950', bins: (wp.espn || {}).table }]);
      document.getElementById('cal-wp-t').innerHTML = HW.tableHTML([{ label: '' }, { label: 'States', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Log-loss', align: 'right' }],
        [['Our model (all states)', wp.n, (wp.ours || {}).brier, (wp.ours || {}).logloss], ['Our model (states with ESPN)', wp.n_espn, (wp.ours_on_espn_rows || {}).brier, (wp.ours_on_espn_rows || {}).logloss], ['ESPN', wp.n_espn, (wp.espn || {}).brier, (wp.espn || {}).logloss]]
          .filter(r => fx.isNum(r[2])).map(r => [r[0], { v: r[1], html: fx.isNum(r[1]) ? Number(r[1]).toLocaleString() : '—' }, { v: r[2], html: fx.num(r[2], 4) }, { v: r[3], html: fx.num(r[3], 4) }]), { compact: true }) +
        (fx.isNum(wp.mean_abs_diff) ? '<div class="pg-note">Mean absolute difference between the two numbers: ' + fx.num(100 * wp.mean_abs_diff, 1) + ' percentage points.</div>' : '');
    } else document.getElementById('cal-wp').innerHTML = fx.muted('The win-probability comparison is not in this backtest file yet.');
    const zr = fx.rowsOf(shots.by_zone || shots).map(r => Object.assign({ zone: r.zone || r._key }, r));
    document.getElementById('cal-shots').innerHTML = zr.length ? HW.tableHTML([{ label: 'Zone' }, { label: 'Shots', align: 'right' }, { label: 'FG%', align: 'right' }, { label: 'Model', align: 'right' }, { label: 'Gap', align: 'right' }, { label: 'z', align: 'right', title: 'Gap over its binomial standard error' }, { label: 'Brier', align: 'right' }],
      zr.map(r => [{ v: r.zone, html: fx.esc(fx.ZONE_LABEL[r.zone] || r.zone) }, { v: r.n, html: fx.isNum(r.n) ? Number(r.n).toLocaleString() : '—' }, { v: r.fg, html: fx.fmtV(r.fg, 'pct') }, { v: r.p_mean, html: fx.fmtV(r.p_mean, 'pct') },
        { v: r.diff, html: fx.signed(100 * (r.diff || 0), 1) + ' pts' }, { v: r.z, html: '<span class="' + (Math.abs(r.z) > 2 ? 'pg-edge-neg' : '') + '">' + fx.num(r.z, 1) + '</span>' }, { v: r.brier, html: fx.num(r.brier, 4) }]), { compact: true })
      : fx.muted('The shot-model calibration is not in this backtest file yet; per-zone predicted against made rates are computed by models/shots.py calibration_table.');
    const PB = d.params_by_season || {};
    const pk = ['rating_scale', 'hca', 'b2b', 'rest', 'travel_1000km', 'tz', 'altitude', 'sigma', 'sigma_market', 'n'];
    const PL = { rating_scale: 'Rating scale', hca: 'Home court', b2b: 'Back-to-back', rest: 'Rest (per day)', travel_1000km: 'Travel (per 1,000 km)', tz: 'Time zones', altitude: 'Altitude', sigma: 'σ margin', sigma_market: 'σ market', n: 'Games fitted' };
    document.getElementById('cal-params').innerHTML = Object.keys(PB).length ? HW.tableHTML([{ label: 'Season' }].concat(pk.map(k => ({ label: PL[k], align: 'right' }))).concat([{ label: 'Fitted' }]),
      Object.keys(PB).sort().map(s => [fx.esc(fx.seasonLabel(L, Number(s)))].concat(pk.map(k => ({ v: PB[s][k], html: fx.isNum(PB[s][k]) ? (k === 'n' ? String(PB[s][k]) : fx.num(PB[s][k], 2)) : '—' }))).concat([PB[s].fitted ? 'yes' : 'defaults'])), { compact: true })
      : fx.muted('No fitted coefficients in the file.');
  });
}

HW.route('calibration', render);
})(window.HW);
