/* The Quant Paddock — calibration (#/calibration): the walk-forward backtest.
 *
 * Every Grand Prix in the covered seasons predicted with only the data before it, by
 * the race simulator (before and after qualifying) and by simple baselines. Shows the
 * scores (log-loss and Brier for win, podium, points and DNF; winner log-loss), the
 * reliability diagrams, the probability each model gave the actual winner, and a
 * plain-words reading generated from the numbers.
 *
 * Data: data/calibration.json (models/backtest.py output plus updated_at, races,
 * seasons, skipped). */
(function (PD) {
'use strict';

const { esc, num, pct, isNum, card, muted, tableHTML, sortable, plot, layout, C, PALETTE } = PD;
const PG = () => PD.pg;

const LABELS = {
  model_pre: 'Race simulator, before qualifying', model_post: 'Race simulator, after qualifying', model_pre_results_only: 'Simulator, results-only pace (pre)',
  grid_order: 'Grid order (logistic on slot)', previous_results: 'Previous 5 results', elo: 'Field Elo (Plackett-Luce)', plackett_luce: 'Plackett-Luce on past orders'
};
const EVENTS = [['win', 'Win'], ['podium', 'Podium'], ['points', 'Points'], ['dnf', 'DNF']];
const label = k => LABELS[k] || PD.titleCase(k);

function bestBy(metrics, models, ev, key) {
  let best = null;
  models.forEach(m => { const v = (((metrics[m] || {})[ev]) || {})[key]; if (isNum(v) && (best === null || v < best.v)) best = { m: m, v: v }; });
  return best;
}

function scoreTable(metrics, models, perSeason) {
  const cols = [{ label: 'Model' }, { label: 'When' }].concat(EVENTS.map(e => ({ label: e[1] + ' LL', align: 'right', title: 'Binary log-loss, lower is better' })))
    .concat(EVENTS.map(e => ({ label: e[1] + ' Brier', align: 'right', title: 'Brier score, lower is better' }))).concat([{ label: 'Winner LL', align: 'right', title: 'Multiclass log-loss of the actual winner, -mean ln p(winner)' }, { label: 'N', align: 'right' }]);
  const groups = [['pre', models.pre], ['post', models.post]];
  const rows = [];
  groups.forEach(g => g[1].forEach(m => {
    const M = metrics[m] || {};
    const cells = [{ v: label(m), html: '<strong>' + esc(label(m)) + '</strong> <span class="gl-key">' + esc(m) + '</span>' }, { v: g[0], html: g[0] === 'pre' ? 'before quali' : 'after quali' }];
    ['logloss', 'brier'].forEach(k => EVENTS.forEach(e => {
      const v = (M[e[0]] || {})[k];
      const b = bestBy(metrics, g[1], e[0], k);
      cells.push({ v: v, html: isNum(v) ? (b && b.m === m ? '<strong style="color:' + C.green + '">' + num(v, 4) + '</strong>' : num(v, 4)) : '—', align: 'right' });
    }));
    const wm = (M.win_multiclass || {}).logloss;
    const bw = (() => { let b = null; g[1].forEach(x => { const v = ((metrics[x] || {}).win_multiclass || {}).logloss; if (isNum(v) && (b === null || v < b.v)) b = { m: x, v: v }; }); return b; })();
    cells.push({ v: wm, html: isNum(wm) ? (bw && bw.m === m ? '<strong style="color:' + C.green + '">' + num(wm, 3) + '</strong>' : num(wm, 3)) : '—', align: 'right' });
    cells.push({ v: (M.win || {}).n, align: 'right' });
    rows.push({ cells: cells });
  }));
  return tableHTML(cols, rows, { compact: true });
}

function reliability(elId, metrics, models, ev) {
  const tr = [{ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
  models.forEach((m, i) => {
    const bins = (((metrics[m] || {})[ev]) || {}).reliability || [];
    if (!bins.length) return;
    const maxN = Math.max.apply(null, bins.map(b => b.n));
    tr.push({ type: 'scatter', mode: 'lines+markers', name: label(m), x: bins.map(b => b.mean_p), y: bins.map(b => b.freq),
      customdata: bins.map(b => [b.n, b.lo, b.hi]), marker: { size: bins.map(b => 6 + 16 * Math.sqrt(b.n / maxN)), color: PALETTE[i % PALETTE.length] }, line: { color: PALETTE[i % PALETTE.length], width: 1.5 },
      hovertemplate: label(m) + '<br>bin %{customdata[1]}–%{customdata[2]}: forecast %{x:.1%}, observed %{y:.1%} (n=%{customdata[0]})<extra></extra>' });
  });
  plot(elId, tr, layout({ showlegend: true, legend: { orientation: 'h', y: -0.18, font: { color: C.text2 } }, margin: { l: 55, r: 15, t: 10, b: 80 },
    xaxis: { title: 'Forecast probability (bin mean)', tickformat: '.0%', range: [0, 1] }, yaxis: { title: 'Observed frequency', tickformat: '.0%', range: [0, 1] } }));
}

/* The reading, written from the numbers. */
function reading(d) {
  const M = d.metrics || {};
  const pre = d.pre_quali_models || [], post = d.post_quali_models || [];
  const ll = (m, e) => (((M[m] || {})[e]) || {}).logloss;
  const wmc = m => ((M[m] || {}).win_multiclass || {}).logloss;
  const out = [];
  const cmp = (model, pool, phase) => {
    const others = pool.filter(x => x !== model && x.indexOf('model_') !== 0 && isNum(wmc(x)));   // baselines only, not the simulator's own variants
    if (!isNum(wmc(model)) || !others.length) return;
    const best = others.sort((a, b) => wmc(a) - wmc(b))[0];
    const diff = wmc(best) - wmc(model);
    out.push('<p><strong>' + esc(phase) + ':</strong> the simulator gives the actual winner, on average, ' + (diff >= 0 ? 'more' : 'less') + ' probability than the best baseline (' + esc(label(best)) + '): winner log-loss ' + num(wmc(model), 3) + ' against ' + num(wmc(best), 3) +
      ' (lower is better; a gap of ' + num(Math.abs(diff), 3) + ' nats means the ' + (diff >= 0 ? 'simulator' : 'baseline') + ' assigns the winner about ' + num(100 * (Math.exp(Math.abs(diff)) - 1), 0) + '% more probability, geometrically averaged over races).</p>');
    const evs = EVENTS.map(e => e[0]).filter(e => isNum(ll(model, e)));
    const wins = evs.filter(e => others.every(o => !isNum(ll(o, e)) || ll(model, e) <= ll(o, e)));
    if (evs.length) out.push('<p>On the binary events it has the lowest log-loss for ' + (wins.length ? wins.map(e => EVENTS.find(x => x[0] === e)[1].toLowerCase()).join(', ') : 'none of them') + (wins.length < evs.length ? ' and trails a baseline on ' + evs.filter(e => wins.indexOf(e) < 0).map(e => EVENTS.find(x => x[0] === e)[1].toLowerCase()).join(', ') : '') + '.</p>');
  };
  if (pre.indexOf('model_pre') >= 0) cmp('model_pre', pre, 'Before qualifying');
  if (post.indexOf('model_post') >= 0) cmp('model_post', post, 'After qualifying');
  // Calibration of the main model's win bins.
  const main = M.model_post ? 'model_post' : 'model_pre';
  const bins = ((((M[main] || {}).win) || {}).reliability || []).filter(b => b.n >= 10);
  if (bins.length) {
    const worst = bins.slice().sort((a, b) => Math.abs(b.freq - b.mean_p) - Math.abs(a.freq - a.mean_p))[0];
    const over = bins.filter(b => b.mean_p > b.freq).reduce((s, b) => s + b.n, 0), under = bins.filter(b => b.mean_p < b.freq).reduce((s, b) => s + b.n, 0);
    out.push('<p><strong>Calibration</strong> (' + esc(label(main)) + ', win, bins with at least 10 forecasts): the largest gap is in the ' + pct(worst.lo, 0) + '–' + pct(worst.hi, 0) + ' bin, where the forecasts averaged ' + pct(worst.mean_p) + ' and the event happened ' + pct(worst.freq) + ' of the time (' + worst.n + ' forecasts). ' +
      (over > under ? 'More forecasts sit in bins where the model was too confident than too timid.' : under > over ? 'More forecasts sit in bins where the model was too timid than too confident.' : '') + ' Points on the dotted diagonal are perfectly calibrated; with a few dozen forecasts in a bin, a gap of ten points is within noise.</p>');
  }
  const dnfM = ll(main, 'dnf'), dnfB = (((M[main] || {}).dnf) || {}).base_rate;
  if (isNum(dnfM) && isNum(dnfB) && dnfB > 0 && dnfB < 1) {
    const h0 = -(dnfB * Math.log(dnfB) + (1 - dnfB) * Math.log(1 - dnfB));
    out.push('<p><strong>Retirements</strong> are close to unpredictable race by race: the DNF log-loss of ' + num(dnfM, 4) + ' compares with ' + num(h0, 4) + ' for forecasting the base rate (' + pct(dnfB) + ') for everyone.</p>');
  }
  return out.join('') || '<p>Not enough scored races for a reading.</p>';
}

function renderCalibration(el) {
  el.innerHTML = muted('Loading the backtest…');
  return PD.load('calibration.json').then(d => {
    if (!PG().alive(el)) return;
    if (!d || d.ok === false || !d.metrics) { el.innerHTML = card('Calibration', '', PG().notBuilt('The backtest', d)); return; }
    const M = d.metrics;
    const pre = (d.pre_quali_models || Object.keys(M).filter(k => k !== 'model_post' && k !== 'grid_order')).filter(k => M[k]);
    const post = (d.post_quali_models || ['model_post', 'grid_order']).filter(k => M[k]);
    const used = d.seasons_used || d.seasons || {};
    const skipped = d.skipped || {};
    const usedList = Array.isArray(used) ? used.map(y => [y, '']) : Object.keys(used).map(y => [y, used[y]]);
    let h = '<div class="card"><div class="card-header">Calibration <span class="card-sub">Walk-forward backtest: every Grand Prix predicted using only the data before it, scored against what happened.</span></div>' +
      '<div class="kpi-grid six" style="padding:12px 12px 0">' + [
        PD.statTile('Races scored', d.races || '—', usedList.length ? usedList.map(x => x[0]).join(', ') : ''),
        PD.statTile('Driver-races', ((M[pre[0]] || {}).win || {}).n || '—', 'one forecast per driver per event'),
        PD.statTile('Simulations', d.n_sims ? Number(d.n_sims).toLocaleString() : '—', 'per race and model variant'),
        PD.statTile('Win base rate', pct((((M[pre[0]] || {}).win) || {}).base_rate), 'one winner per race'),
        PD.statTile('Podium base rate', pct((((M[pre[0]] || {}).podium) || {}).base_rate)),
        PD.statTile('Updated', esc(PD.fmtStamp(d.updated_at || d.generated_at) || '—'), d.runtime_s ? num(d.runtime_s / 60, 0) + ' min run' : '')
      ].join('') + '</div>' +
      '<div class="mk-line"><strong>Seasons covered:</strong> ' + (usedList.map(x => x[0] + (x[1] ? ' <span class="muted-inline">(' + esc(x[1]) + ')</span>' : '')).join(', ') || '—') +
      ' · <strong>skipped:</strong> ' + (Object.keys(skipped).length ? Object.keys(skipped).map(y => y + ' <span class="muted-inline">(' + esc(skipped[y]) + ')</span>').join(', ') : 'none') +
      (d.unavailable && Object.keys(d.unavailable).length ? ' · <strong>unavailable:</strong> ' + Object.keys(d.unavailable).map(k => esc(k) + ' (' + esc(d.unavailable[k]) + ')').join(', ') : '') + '</div></div>';
    h += '<div class="card"><div class="card-header">What it shows</div><div class="cal-read">' + reading(d) + '</div></div>';
    h += '<div class="card"><div class="card-header">Scores <span class="card-sub">Binary log-loss −mean(y ln p + (1−y) ln(1−p)) with p clipped to [0.0001, 0.9999], and Brier mean((p−y)²); lower is better. Green marks the best in its group: before-qualifying models compete with each other, after-qualifying with each other.</span>' +
      '<span class="pg-ctl">season <select id="cal-season"><option value="">all</option>' + Object.keys(d.per_season || {}).sort().reverse().map(y => '<option value="' + esc(y) + '">' + esc(y) + '</option>').join('') + '</select></span></div><div id="cal-table"></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Reliability: win <span class="card-sub">Forecasts grouped into ten equal-width bins; marker size by the number of forecasts.</span></div><div id="cal-rel-win" style="height:420px"></div></div>' +
      '<div class="card"><div class="card-header">Reliability: podium</div><div id="cal-rel-pod" style="height:420px"></div></div></div>';
    h += '<div class="card"><div class="card-header">Reliability bins <span class="card-sub">The numbers behind the diagrams.</span>' +
      '<span class="pg-ctl"><select id="cal-bin-model">' + pre.concat(post).map(k => '<option value="' + esc(k) + '">' + esc(label(k)) + '</option>').join('') + '</select><select id="cal-bin-ev">' + EVENTS.map(e => '<option value="' + e[0] + '">' + e[1] + '</option>').join('') + '</select></span></div><div id="cal-bins"></div></div>';
    h += '<div class="card"><div class="card-header">The winner\'s probability, race by race <span class="card-sub">What each model gave the driver who won. Higher is better.</span></div><div id="cal-races" style="height:360px"></div></div>';
    h += '<div class="card"><div class="card-header">Baselines <span class="card-sub">What the simulator has to beat.</span></div><div class="pad doc-body"><ul>' +
      '<li><strong>Grid order</strong> (after qualifying): per event p = sigmoid(a + b × grid slot), fitted by maximum likelihood on the previous seasons, rescaled so the field\'s win / podium / points probabilities sum to 1 / 3 / 10.</li>' +
      '<li><strong>Previous results</strong>: each driver\'s frequency of the event in his last 5 starts, shrunk to the field base rate with 2 pseudo-starts, rescaled the same way.</li>' +
      '<li><strong>Field Elo</strong>: Elo before the race as Plackett-Luce log-strengths θ = Elo × ln 10 / 400; DNF at the previous seasons\' base rate.</li>' +
      '<li><strong>Plackett-Luce</strong>: strengths fitted to earlier finishing orders (this season weight 1, last season 0.35, two back 0.12), sampled for podium and points.</li></ul>' +
      '<p>Details in the <a href="#/methodology">methodology</a> → backtest.</p></div></div>';
    el.innerHTML = h;

    const drawTable = season => {
      const src = season ? ((d.per_season || {})[season] || {}) : M;
      document.getElementById('cal-table').innerHTML = scoreTable(src, { pre: pre.filter(k => src[k]), post: post.filter(k => src[k]) });
      sortable('cal-table');
    };
    drawTable('');
    document.getElementById('cal-season').onchange = e => drawTable(e.target.value);
    const relModels = ['model_pre', 'model_post', 'grid_order', 'previous_results'].filter(k => M[k]);
    reliability('cal-rel-win', M, relModels, 'win');
    reliability('cal-rel-pod', M, relModels, 'podium');
    const drawBins = () => {
      const m = document.getElementById('cal-bin-model').value, e = document.getElementById('cal-bin-ev').value;
      const bins = (((M[m] || {})[e]) || {}).reliability || [];
      document.getElementById('cal-bins').innerHTML = bins.length ? tableHTML([{ label: 'Bin' }, { label: 'Forecasts', align: 'right' }, { label: 'Mean forecast', align: 'right' }, { label: 'Observed', align: 'right' }, { label: 'Gap', align: 'right' }, { label: '±2 se', align: 'right', title: 'Two binomial standard errors at the mean forecast' }],
        bins.map(b => { const se = Math.sqrt(Math.max(1e-9, b.mean_p * (1 - b.mean_p)) / b.n); const gap = b.freq - b.mean_p; return [pct(b.lo, 0) + '–' + pct(b.hi, 0), b.n, { v: b.mean_p, html: pct(b.mean_p) }, { v: b.freq, html: pct(b.freq) },
          { v: gap, html: '<span class="' + (Math.abs(gap) > 2 * se ? 'pg-edge-neg' : '') + '">' + PD.signed(100 * gap, 1) + ' pts</span>' }, { v: 2 * se, html: '±' + num(200 * se, 1) + ' pts' }]; }), { compact: true }) : muted('No bins.');
    };
    document.getElementById('cal-bin-model').onchange = drawBins; document.getElementById('cal-bin-ev').onchange = drawBins;
    drawBins();
    const pr = d.per_race || [];
    if (pr.length) {
      const x = pr.map((r, i) => i), lab = pr.map(r => r.year + ' R' + r.round + ' ' + (r.name || '') + ': ' + PD.driverName(r.winner));
      const ticks = [], tt = [];
      pr.forEach((r, i) => { if (!i || r.year !== pr[i - 1].year) { ticks.push(i); tt.push(String(r.year)); } });
      plot('cal-races', ['model_pre', 'model_post', 'grid_order', 'elo'].filter(k => M[k]).map((k, i) => ({ type: 'scatter', mode: 'lines+markers', name: label(k), x: x, y: pr.map(r => (r.p_winner || {})[k]), text: lab,
        line: { color: PALETTE[i % PALETTE.length], width: k.indexOf('model') === 0 ? 2 : 1 }, marker: { size: 4 }, hovertemplate: '%{text}<br>' + esc(label(k)) + ': %{y:.1%}<extra></extra>' })),
        layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 50, r: 15, t: 30, b: 40 }, xaxis: { tickvals: ticks, ticktext: tt }, yaxis: { tickformat: '.0%', title: 'P(actual winner)' } }));
    } else document.getElementById('cal-races').innerHTML = muted('No per-race records.');
  });
}

PD.route('calibration', renderCalibration);
})(window.PD);
