/* The Quant Bullpen — calibration (#/calibration): does the modelling hold up?
 *
 * The walk-forward game backtest against ESPN's closing lines (models/backtest.py): every game
 * priced with projections refitted from games strictly before it, scored by log-loss, Brier and
 * reliability for the game model, a team-ratings model, a starter-and-record baseline and the
 * de-vigged closing moneyline; totals and run lines against the market's own prices; postseason
 * series. Then the model checks: xwOBA+ against Savant's xwOBA at predicting next-period wOBA,
 * stuff validity (does this season's stuff predict next season's strikeouts and runs?),
 * projections against a Marcel-style baseline, and framing and fielding against Savant's
 * leaderboards. "What it shows" is written from the numbers on the page.
 *
 * Data: data/<L>/calibration.json ({"generated_at", "games": {"seasons": {S: SUMM}, "pooled": SUMM,
 * "series"}, "checks": {"projections", "xwoba", "stuff"}, + "framing", "oaa", ...}); SUMM =
 * {"n_games", "model", "ratings", "starter_record", "vs_market": {...}, "totals", "totals_market",
 * "runline", "runline_market", "runs", "series"}. Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const LABELS = { model: 'Game model', ratings: 'Team ratings', starter_record: 'Starter and record', market: 'Closing line (ESPN)', blend_50: '50/50 model and market' };
const ORDER = ['model', 'ratings', 'starter_record', 'market', 'blend_50'];
const COL = { model: '#f97316', ratings: '#bc8cff', starter_record: '#8b949e', market: '#58a6ff', blend_50: '#3fb950' };
const lab = m => LABELS[m] || K().titleCase(m);
const H = p => (p > 0 && p < 1 ? -(p * Math.log(p) + (1 - p) * Math.log(1 - p)) : null);

function scoreTable(src, models) {
  const k = K();
  const best = key => { let b = null; models.forEach(m => { const v = (src[m] || {})[key]; if (k.isNum(v) && (b === null || v < b.v)) b = { m: m, v: v }; }); return b; };
  const bl = best('logloss'), bb = best('brier');
  return k.table([{ label: 'Forecaster' }, { label: 'Games', align: 'right' }, { label: 'Log-loss', align: 'right', title: 'Lower is better' }, { label: 'Brier', align: 'right', title: 'Lower is better' }, { label: 'Skill v coin', align: 'right', title: '1 − log-loss / ln 2' }, { label: 'Skill v base rate', align: 'right', title: '1 − log-loss / entropy of the home win rate' }],
    models.filter(m => src[m] && src[m].n).map(m => { const s = src[m], h0 = H(s.base_rate);
      return [{ v: ORDER.indexOf(m), html: '<span class="gq-dotc" style="background:' + (COL[m] || '#8b949e') + '"></span><strong>' + k.esc(lab(m)) + '</strong>' + (m === 'market' ? ' <span class="gq-tag">market</span>' : '') },
        { v: s.n, html: k.int(s.n) }, { v: s.logloss, html: bl && bl.m === m ? '<strong class="gq-ok">' + k.num(s.logloss, 4) + '</strong>' : k.num(s.logloss, 4) },
        { v: s.brier, html: bb && bb.m === m ? '<strong class="gq-ok">' + k.num(s.brier, 4) + '</strong>' : k.num(s.brier, 4) },
        { v: k.isNum(s.logloss) ? 1 - s.logloss / Math.LN2 : null, html: k.isNum(s.logloss) ? k.signed(100 * (1 - s.logloss / Math.LN2), 2) + '%' : '—' },
        { v: h0 !== null && k.isNum(s.logloss) ? 1 - s.logloss / h0 : null, html: h0 !== null && k.isNum(s.logloss) ? k.signed(100 * (1 - s.logloss / h0), 2) + '%' : '—' }]; }), { compact: true });
}

/* The reading: every sentence is computed from the payload. */
function reading(d) {
  const k = K(), out = [];
  const G = d.games || {}, P = G.pooled || {}, V = P.vs_market || {};
  const seasons = Object.keys(G.seasons || {}).sort();
  const ll = (o, m) => (o[m] || {}).logloss;
  if (P.n_games) {
    out.push('<p><strong>Coverage.</strong> ' + k.int(P.n_games) + ' games ' + (seasons.length > 1 ? 'from ' + seasons[0] + ' to ' + seasons[seasons.length - 1] : 'in ' + seasons[0]) + ' were priced walk-forward, each with projections refitted from games strictly before it. ' +
      k.int((V.market || {}).n) + ' of them (' + k.num(100 * ((V.market || {}).n || 0) / P.n_games, 0) + '%) have an ESPN closing moneyline to compare with.</p>');
  }
  if (k.isNum(ll(P, 'model')) && k.isNum(ll(P, 'ratings'))) {
    const dR = ll(P, 'ratings') - ll(P, 'model'), dS = ll(P, 'starter_record') - ll(P, 'model');
    out.push('<p><strong>Against the simple baselines.</strong> Over every scored game the game model\'s log-loss is ' + k.num(ll(P, 'model'), 4) + ', against ' + k.num(ll(P, 'ratings'), 4) + ' for team ratings from run differential and ' + k.num(ll(P, 'starter_record'), 4) + ' for the starter-and-record baseline. ' +
      (dS > 0 ? 'The model beats the starter-and-record baseline by ' + k.num(dS, 4) + ' nats a game' : 'The model does not beat the starter-and-record baseline, which is the gate it must pass') + (k.isNum(dR) ? (dR > 0 ? ' and the ratings by ' + k.num(dR, 4) + '.' : '; the ratings are as good or better (' + k.signed(-dR, 4) + ').') : '.') +
      ' Baseball games are close to coin flips (the coin scores ' + k.num(Math.LN2, 4) + '), so the gains are small in absolute terms; ' + k.num(100 * (1 - ll(P, 'model') / Math.LN2), 2) + '% better than a coin is the model\'s skill.</p>');
  }
  if (k.isNum(ll(V, 'model')) && k.isNum(ll(V, 'market'))) {
    const gap = ll(V, 'model') - ll(V, 'market');
    const share = k.isNum(ll(V, 'starter_record')) && ll(V, 'starter_record') > ll(V, 'market') ? (ll(V, 'starter_record') - ll(V, 'model')) / (ll(V, 'starter_record') - ll(V, 'market')) : null;
    out.push('<p><strong>Against the closing line.</strong> On the ' + k.int((V.market || {}).n) + ' games with a close, the model scores ' + k.num(ll(V, 'model'), 4) + ' and the de-vigged closing moneyline ' + k.num(ll(V, 'market'), 4) + '. ' +
      (gap > 0 ? 'The market is sharper by ' + k.num(gap, 4) + ' nats a game, the expected order: the close knows the lineups, the bullpen, injuries and money that the model reads late or not at all. ' + (share !== null ? 'Measured from the starter-and-record baseline, the model closes ' + k.num(100 * share, 0) + '% of the distance to the market. ' : '')
        : 'The model is at least as sharp as the close here, which would be extraordinary: treat it as a bug until it survives more seasons. ') +
      (k.isNum(ll(V, 'blend_50')) ? (ll(V, 'blend_50') < ll(V, 'market') ? 'A 50/50 blend of model and market scores ' + k.num(ll(V, 'blend_50'), 4) + ', better than the market alone, so the model carries some information the close does not.' : 'A 50/50 blend scores ' + k.num(ll(V, 'blend_50'), 4) + ', no better than the market alone, so the model adds nothing the close does not already price.') : '') + '</p>');
  }
  const bins = (((P.model || {}).reliability) || []).filter(b => b.n >= 100);
  if (bins.length) {
    const worst = bins.slice().sort((a, b) => Math.abs(b.freq - b.mean_p) - Math.abs(a.freq - a.mean_p))[0];
    const se = Math.sqrt(Math.max(1e-9, worst.mean_p * (1 - worst.mean_p)) / worst.n);
    out.push('<p><strong>Calibration.</strong> In the model\'s bins with at least 100 games the largest gap is at ' + k.pct(worst.lo, 0) + '–' + k.pct(worst.hi, 0) + ': forecasts averaged ' + k.pct(worst.mean_p) + ' and the home side won ' + k.pct(worst.freq) + ' of ' + k.int(worst.n) + ' games, ' +
      (Math.abs(worst.freq - worst.mean_p) > 2 * se ? 'more than two standard errors (±' + k.num(200 * se, 1) + ' points) away: a real miscalibration.' : 'within two standard errors (±' + k.num(200 * se, 1) + ' points): consistent with noise.') + '</p>');
  }
  const r = P.runs || {};
  if (k.isNum(r.model_mean_total)) {
    const T = P.totals || {}, TM = P.totals_market || {}, RL = P.runline || {}, RM = P.runline_market || {};
    out.push('<p><strong>Totals and run lines.</strong> The simulation expected ' + k.num(r.model_mean_total, 2) + ' runs a game; ' + k.num(r.actual_mean_total, 2) + ' were scored (' + (r.model_mean_total > r.actual_mean_total ? 'too many' : 'too few') + ' by ' + k.num(Math.abs(r.model_mean_total - r.actual_mean_total), 2) + '). ' +
      (k.isNum(T.logloss) && k.isNum(TM.logloss) ? 'On the over/under at the closing total the model scores ' + k.num(T.logloss, 4) + ' against the market\'s ' + k.num(TM.logloss, 4) + '. ' : '') +
      (k.isNum(RL.logloss) && k.isNum(RM.logloss) ? 'On the closing run line, ' + k.num(RL.logloss, 4) + ' against ' + k.num(RM.logloss, 4) + '.' : '') + '</p>');
  }
  const C = d.checks || {};
  const xw = C.xwoba || {};
  const wp = xw.within_pooled || xw.pooled, ap = xw.across_pooled;
  if (wp && wp.xwoba && wp.savant_xwoba) {
    out.push('<p><strong>xwOBA+ against Savant\'s xwOBA.</strong> Predicting a hitter\'s wOBA in the second half of a season from the first half (' + k.int(wp.n) + ' hitter-halves), our xwOBA+ correlates ' + k.num(wp.xwoba.r, 3) + ', Savant\'s xwOBA ' + k.num(wp.savant_xwoba.r, 3) + ' and first-half wOBA itself ' + k.num((wp.woba || {}).r, 3) + '. ' +
      (Math.abs(wp.xwoba.r - wp.savant_xwoba.r) < 0.02 ? 'The two are on par (a gap of ' + k.num(Math.abs(wp.xwoba.r - wp.savant_xwoba.r), 3) + ').' : 'The gap is ' + k.num(Math.abs(wp.xwoba.r - wp.savant_xwoba.r), 3) + ' in favour of ' + (wp.xwoba.r > wp.savant_xwoba.r ? 'xwOBA+.' : 'Savant\'s xwOBA.')) +
      (ap && ap.xwoba && ap.savant_xwoba ? ' Across the winter (second half to the next first half) the figures are ' + k.num(ap.xwoba.r, 3) + ' against ' + k.num(ap.savant_xwoba.r, 3) + '.' : '') + ' Differences of a hundredth or two are within the noise of a few hundred hitters.</p>');
  }
  const st = C.stuff || {};
  if (st.available) out.push('<p><strong>Stuff validity.</strong> For ' + k.int(st.n) + ' pitchers with 300+ batters faced in consecutive seasons, this season\'s ' + (st.score === 'stuff' ? 'Stuff+' : 'fastball velocity (Stuff+ was not available)') + ' correlates ' + k.num(st.stuff_vs_next_k, 3) + ' with next season\'s strikeout rate (this season\'s strikeout rate: ' + k.num(st.k_vs_next_k, 3) + ') and ' + k.num(st.stuff_vs_next_ra9, 3) + ' with next season\'s RA9 (strikeout rate: ' + k.num(st.k_vs_next_ra9, 3) + '). ' +
    (Math.abs(st.stuff_vs_next_k) > Math.abs(st.k_vs_next_k) ? 'Stuff alone predicts strikeouts better than past strikeouts do.' : 'Past strikeouts still predict strikeouts better than stuff alone, as expected: results carry location, sequencing and deception too.') +
    (k.isNum(st.stuff_vs_next_ra9) && k.isNum(st.k_vs_next_ra9) ? (Math.abs(Math.abs(st.stuff_vs_next_ra9) - Math.abs(st.k_vs_next_ra9)) < 0.02 ? ' For runs allowed the two are level.' : ' For runs allowed ' + (Math.abs(st.stuff_vs_next_ra9) > Math.abs(st.k_vs_next_ra9) ? 'stuff' : 'past strikeouts') + ' predict better.') : '') + '</p>');
  const pj = (C.projections || {}).pooled;
  if (pj && (pj.hitter || pj.pitcher)) {
    const g = (role, c) => ((pj[role] || {})[c] || {}).gain_pct;
    out.push('<p><strong>Projections.</strong> Against a Marcel-style baseline (5/4/3 season weights, 1,200 PA of league average, a simple age factor), next-season projections cut the weighted error of hitters\' wOBA by ' + k.num(g('hitter', 'wOBA'), 1) + '% and strikeout rate by ' + k.num(g('hitter', 'K'), 1) + '%' +
      (k.isNum(g('pitcher', 'K')) ? ', and pitchers\' strikeout rate by ' + k.num(g('pitcher', 'K'), 1) + '% and wOBA allowed by ' + k.num(g('pitcher', 'wOBA'), 1) + '%' : '') + ' (negative means worse than the baseline).</p>');
  }
  ['framing', 'oaa'].forEach(x => {
    const ps = bySeason(d[x] || C[x], x).filter(r => k.isNum(r.r));
    if (!ps.length) return;
    const lo = ps.reduce((a, b) => (b.r < a.r ? b : a)), hi = ps.reduce((a, b) => (b.r > a.r ? b : a));
    out.push('<p><strong>' + (x === 'oaa' ? 'Fielding runs against Savant\'s OAA' : 'Framing runs against Savant\'s framing runs') + '.</strong> ' + (ps.length === 1 ? 'Correlation ' + k.num(lo.r, 3) + ' in ' + lo.season : 'Season by season the correlation ranges from ' + k.num(lo.r, 3) + ' (' + lo.season + ') to ' + k.num(hi.r, 3) + ' (' + hi.season + ') over ' + ps.length + ' seasons') +
      (x === 'oaa' ? ', fielders with ' + (ps[0].floor || 50) + '+ chances' : ', catchers with ' + k.int(ps[0].floor || 1000) + '+ called pitches') + '.</p>');
  });
  ['framing', 'oaa'].forEach(x => { const v = d[x] || C[x]; if (v && k.isNum(v.r || v.pearson)) out.push('<p><strong>' + (x === 'oaa' ? 'Fielding runs against Savant\'s OAA' : 'Framing runs against Savant\'s framing') + '.</strong> Correlation ' + k.num(v.r || v.pearson, 3) + ' over ' + k.int(v.n) + (x === 'oaa' ? ' fielders with 50+ chances' : ' catchers with 1,000+ called pitches') + (k.isNum(v.slope) ? '; slope ' + k.num(v.slope, 2) : '') + '.</p>'); });
  return out.join('') || '<p>Not enough scored games for a reading yet.</p>';
}

function render(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  el.innerHTML = k.muted('Loading the backtest…');
  return k.ready().then(() => BP.load(L + '/calibration.json')).then(d => {
    if (!k.alive(el)) return;
    const G = (d && d.games) || {};
    if (!d || d.ok === false || (!G.pooled && !d.checks)) { el.innerHTML = k.card('Calibration · ' + k.LN(L), '', k.notBuilt('The ' + k.LN(L) + ' backtest', d)); return; }
    const P = G.pooled || {}, V = P.vs_market || {};
    const seasons = Object.keys(G.seasons || {}).sort();
    let h = '<div class="card"><div class="card-header">Calibration · ' + k.LN(L) + ' <span class="card-sub">Walk-forward backtest' + (seasons.length ? ' ' + seasons[0] + '–' + seasons[seasons.length - 1] : '') + ' against ESPN\'s closing lines, and the checks on xwOBA+, stuff, projections, framing and fielding.' + (d.generated_at ? ' Generated ' + k.esc(k.fmtDate(d.generated_at, { year: true })) + '.' : '') + '</span></div>' +
      k.tiles([k.tile('Games scored', k.int(P.n_games), seasons.length + ' season' + (seasons.length === 1 ? '' : 's')),
        k.tile('With a closing line', k.int((V.market || {}).n), P.n_games ? k.num(100 * ((V.market || {}).n || 0) / P.n_games, 0) + '% of games' : ''),
        k.tile('Model log-loss', k.num((P.model || {}).logloss, 4), 'ratings ' + k.num((P.ratings || {}).logloss, 4) + ' · starter ' + k.num((P.starter_record || {}).logloss, 4)),
        k.tile('Closing-line log-loss', k.num((V.market || {}).logloss, 4), 'model ' + k.num((V.model || {}).logloss, 4) + ' on the same games'),
        k.tile('Runs per game', k.num((P.runs || {}).model_mean_total, 2), 'forecast · ' + k.num((P.runs || {}).actual_mean_total, 2) + ' scored'),
        k.tile('Series', k.isNum((G.series || {}).n) ? k.int(G.series.n) : '—', k.isNum((G.series || {}).logloss) ? 'log-loss ' + k.num(G.series.logloss, 4) : 'postseason series at game 1')]) + '</div>';
    h += '<div class="card"><div class="card-header">What it shows <span class="card-sub">Written from the numbers below.</span></div><div class="gq-read">' + reading(d) + '</div></div>';
    h += '<div class="card"><div class="card-header">Scores <span class="card-sub">Log-loss −mean(y ln p + (1−y) ln(1−p)), p clipped to [0.0001, 0.9999]; Brier mean((p−y)²); lower is better, green is best. y = 1 when the home team wins.</span>' +
      '<span class="gq-ctl"><select id="cal-scope"><option value="all">all scored games</option><option value="mkt">games with a closing line</option>' + seasons.slice().reverse().map(s => '<option value="s' + s + '">' + s + '</option><option value="m' + s + '">' + s + ', with a closing line</option>').join('') + '</select></span></div><div id="cal-table"></div>' +
      '<div class="pg-note gq-note">Team ratings: run differential regressed to a prior of 50 games, 0.40 logit per run, plus 0.12 logit home field. Starter and record: a logistic regression on the log5 of regressed win percentages, the starters\' regressed RA9 difference and home field, refitted as games accumulate. The closing line is ESPN\'s DraftKings close (else the current line), de-vigged multiplicatively.</div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Reliability: who wins <span class="card-sub">Ten equal-width bins of P(home win); marker size by games.</span>' + k.toggle('cal-rel', [['all', 'All games'], ['mkt', 'v closing line']], 'mkt') + '</div><div id="cal-rel-c" style="height:420px"></div></div>' +
      '<div class="card"><div class="card-header">Log-loss by season</div><div id="cal-years" style="height:420px"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Totals <span class="card-sub">P(over the closing total), pushes excluded: the model\'s simulated distribution against the market\'s de-vigged over price.</span></div><div id="cal-tot" style="height:340px"></div><div id="cal-tot-t"></div></div>' +
      '<div class="card"><div class="card-header">Run line <span class="card-sub">P(home covers the closing run line).</span></div><div id="cal-rl" style="height:340px"></div><div id="cal-rl-t"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">xwOBA+ against Savant\'s xwOBA <span class="card-sub">Pearson r with the next period\'s wOBA (first half → second half, and second half → next first half), hitters with 200+ PA then 100+ PA.</span></div><div id="cal-xw" style="height:300px"></div><div id="cal-xw-t"></div></div>' +
      '<div class="card"><div class="card-header">Stuff validity <span class="card-sub">Does this season\'s Stuff+ predict next season? Pitchers with 300+ batters faced in both.</span></div><div id="cal-stuff"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Projection error <span class="card-sub">Weighted RMSE of next-season projections against a Marcel-style baseline; gain = 1 − ours/baseline.</span></div><div id="cal-proj"></div></div>' +
      '<div class="card"><div class="card-header">Framing and fielding against Savant <span class="card-sub">Our framing runs and fielding runs against Savant\'s published leaderboards.</span></div><div id="cal-ext"></div></div></div>';
    el.innerHTML = h;
    const pick = v => { if (v === 'all') return P; if (v === 'mkt') return V; const s = (G.seasons || {})[v.slice(1)] || {}; return v.charAt(0) === 'm' ? (s.vs_market || {}) : s; };
    const drawT = v => { const src = pick(v); document.getElementById('cal-table').innerHTML = scoreTable(src, ORDER.filter(m => src[m])); };
    drawT('all');
    document.getElementById('cal-scope').onchange = e => drawT(e.target.value);
    const rel = v => { const src = v === 'mkt' ? V : P; k.reliability('cal-rel-c', ORDER.filter(m => src[m] && (src[m].reliability || []).length && m !== 'blend_50').map(m => ({ name: lab(m), colour: COL[m], bins: src[m].reliability })), { xt: 'Forecast P(home win)', yt: 'Home win rate', minN: 20, min: 0.1, max: 0.9 }); };
    rel('mkt');
    k.wireToggle(el, 'cal-rel', rel);
    if (seasons.length) {
      k.plot('cal-years', ORDER.filter(m => m !== 'blend_50').map(m => ({ type: 'scatter', mode: 'lines+markers', name: lab(m), x: seasons, y: seasons.map(s => { const x = (G.seasons[s] || {}); return m === 'market' ? ((x.vs_market || {}).market || {}).logloss : (x[m] || {}).logloss; }), line: { color: COL[m], width: 2 }, connectgaps: false }))
        .concat([{ type: 'scatter', mode: 'lines', name: 'Coin', x: seasons, y: seasons.map(() => Math.LN2), line: { color: '#6e7681', dash: 'dot', width: 1 } }]), k.layout(Object.assign({ margin: { l: 56, r: 10, t: 30, b: 36 }, yaxis: { title: 'Log-loss', tickformat: '.3f' }, xaxis: { type: 'category' } }, k.legendTop())));
    } else document.getElementById('cal-years').innerHTML = k.muted('One season only.');
    lineCal('cal-tot', P.totals, P.totals_market);
    lineCal('cal-rl', P.runline, P.runline_market);
    xwoba((d.checks || {}).xwoba);
    stuff((d.checks || {}).stuff);
    proj((d.checks || {}).projections);
    ext(d);
  });
}

function lineCal(id, mod, mkt) {
  const k = K();
  const ser = [];
  if (mod && (mod.reliability || []).length) ser.push({ name: 'Model', colour: COL.model, bins: mod.reliability });
  if (mkt && (mkt.reliability || []).length) ser.push({ name: 'Market', colour: COL.market, bins: mkt.reliability });
  if (!ser.length) { const n = document.getElementById(id); n.innerHTML = k.muted('Not scored yet.'); n.style.height = 'auto'; return; }
  k.reliability(id, ser, { xt: 'Forecast', yt: 'Observed', minN: 20, min: 0.2, max: 0.8 });
  document.getElementById(id + '-t').innerHTML = scoreTable({ model: mod || {}, market: mkt || {} }, ['model', 'market']);
}
function xwoba(x) {
  const k = K();
  const node = document.getElementById('cal-xw'), tab = document.getElementById('cal-xw-t');
  if (!x || x.available === false || x.error || (!x.within && !x.within_pooled)) { node.innerHTML = k.muted(x && x.error ? 'The test failed in this build: ' + k.esc(x.error) : 'The predictive test is not published yet.'); node.style.height = 'auto'; return; }
  const rows = [];
  Object.keys(x.within || {}).sort().forEach(s => rows.push([s + ' H1 → H2', x.within[s]]));
  Object.keys(x.across || {}).sort().forEach(s => rows.push([s.replace('->', ' → '), x.across[s]]));
  if (x.within_pooled) rows.push(['Pooled, within seasons', x.within_pooled]);
  if (x.across_pooled) rows.push(['Pooled, across winters', x.across_pooled]);
  const ok = rows.filter(r => r[1] && r[1].n);
  const ser = [['xwoba', 'xwOBA+', '#f97316'], ['savant_xwoba', 'Savant xwOBA', '#58a6ff'], ['woba', 'wOBA', '#8b949e']];
  k.plot(node, ser.map(s => ({ type: 'bar', name: s[1], x: ok.map(r => r[0]), y: ok.map(r => (r[1][s[0]] || {}).r), marker: { color: s[2] }, hovertemplate: '%{x}: r = %{y:.3f}<extra>' + s[1] + '</extra>' })),
    k.layout(Object.assign({ barmode: 'group', margin: { l: 44, r: 10, t: 30, b: 70 }, yaxis: { title: 'r with next-period wOBA', rangemode: 'tozero' }, xaxis: { type: 'category', tickangle: -20 } }, k.legendTop())));
  tab.innerHTML = k.table([{ label: 'Test' }, { label: 'Hitters', align: 'right' }, { label: 'xwOBA+ r', align: 'right' }, { label: 'Savant r', align: 'right' }, { label: 'wOBA r', align: 'right' }, { label: 'xwOBA+ RMSE', align: 'right' }, { label: 'Savant RMSE', align: 'right' }, { label: 'r gap', align: 'right', title: 'xwOBA+ r minus Savant r' }],
    ok.map(r => { const v = r[1], a = (v.xwoba || {}).r, b = (v.savant_xwoba || {}).r;
      return [{ v: r[0], html: k.esc(r[0]) }, { v: v.n, html: k.int(v.n) }, { v: a, html: k.num(a, 3) }, { v: b, html: k.num(b, 3) }, { v: (v.woba || {}).r, html: k.num((v.woba || {}).r, 3) },
        { v: (v.xwoba || {}).rmse, html: k.num((v.xwoba || {}).rmse, 4) }, { v: (v.savant_xwoba || {}).rmse, html: k.num((v.savant_xwoba || {}).rmse, 4) },
        { v: k.isNum(a) && k.isNum(b) ? a - b : null, html: k.isNum(a) && k.isNum(b) ? k.signed(a - b, 3) : '—' }]; }), { compact: true });
}
function stuff(s) {
  const k = K(), host = document.getElementById('cal-stuff');
  if (!s || !s.available) { host.innerHTML = k.muted(s && s.error ? 'The check failed in this build: ' + k.esc(s.error) : 'Needs two consecutive seasons of pitch data' + (s && k.isNum(s.n) ? ' (' + s.n + ' pitchers so far)' : '') + '.'); return; }
  host.innerHTML = k.table([{ label: 'Predictor (season Y)' }, { label: 'Next season K%', align: 'right' }, { label: 'Next season RA9', align: 'right' }],
    [[{ v: 1, html: '<strong>' + (s.score === 'stuff' ? 'Stuff+' : 'Fastball velocity') + '</strong>' }, { v: s.stuff_vs_next_k, html: k.num(s.stuff_vs_next_k, 3) }, { v: s.stuff_vs_next_ra9, html: k.num(s.stuff_vs_next_ra9, 3) }],
      [{ v: 2, html: 'Strikeout rate' }, { v: s.k_vs_next_k, html: k.num(s.k_vs_next_k, 3) }, { v: s.k_vs_next_ra9, html: k.num(s.k_vs_next_ra9, 3) }]], { compact: true }) +
    '<div class="pg-note gq-note">' + k.int(s.n) + ' pitcher-seasons. Pearson correlations; for RA9 a negative number is good (more stuff, fewer runs).</div>';
}
function proj(p) {
  const k = K(), host = document.getElementById('cal-proj');
  if (!p || p.error || !p.pooled || !Object.keys(p.pooled).length) { host.innerHTML = k.muted(p && p.error ? 'The check failed in this build: ' + k.esc(p.error) : 'Needs a season to project into.'); return; }
  const rows = [];
  ['hitter', 'pitcher'].forEach(role => Object.keys(p.pooled[role] || {}).forEach(c => rows.push([role, c, p.pooled[role][c]])));
  host.innerHTML = k.table([{ label: 'Role' }, { label: 'Component' }, { label: 'Ours', align: 'right' }, { label: 'Marcel-style', align: 'right' }, { label: 'Gain', align: 'right' }],
    rows.map(r => [{ v: r[0], html: k.esc(k.titleCase(r[0])) }, { v: r[1], html: k.esc({ K: 'Strikeout rate', BB: 'Walk rate', HRBIP: 'HR per ball in play', HITS: 'Hits per ball in play', wOBA: 'wOBA' }[r[1]] || r[1]) },
      { v: r[2].ours, html: k.num(r[2].ours, 4) }, { v: r[2].marcel, html: k.num(r[2].marcel, 4) }, { v: r[2].gain_pct, html: '<span class="' + (r[2].gain_pct > 0 ? 'gq-ok' : 'gq-no') + '">' + k.signed(r[2].gain_pct, 1) + '%</span>' }]), { compact: true }) +
    '<div class="pg-note gq-note">RMSE weighted by the actual sample, players with 200+ PA or BF in the projected season. Seasons: ' + Object.keys(((p.seasons || {}).hitter) || {}).join(', ') + '.</div>';
}
/* checks.framing / checks.oaa as built: {season: {ok, n, r_runs, r_rate | r_oaa, min_called | min_chances}} ->
 * [{season, n, r (season runs v Savant's), r2 (rate or OAA), floor}], seasons ascending; [] for any other shape. */
function bySeason(v, x) {
  const k = K();
  if (!v || typeof v !== 'object' || k.isNum(v.r) || k.isNum(v.pearson)) return [];
  return Object.keys(v).filter(s => /^\d{4}$/.test(s) && v[s] && v[s].ok !== false && (k.isNum(v[s].r_runs) || k.isNum(x === 'oaa' ? v[s].r_oaa : v[s].r_rate))).sort()
    .map(s => ({ season: s, n: v[s].n, r: v[s].r_runs, r2: x === 'oaa' ? v[s].r_oaa : v[s].r_rate, floor: v[s].min_called || v[s].min_chances }));
}
function ext(d) {
  const k = K(), host = document.getElementById('cal-ext');
  const C = d.checks || {};
  const ps = [['framing', 'Framing runs v Savant', 'catchers', 'rate v rate'], ['oaa', 'Fielding runs v Savant OAA', 'fielders', 'OAA v OAA']]
    .map(x => [x, bySeason(d[x[0]] || C[x[0]], x[0])]).filter(x => x[1].length);
  if (ps.length) {
    host.innerHTML = k.table([{ label: 'Check' }, { label: 'Season' }, { label: 'n', align: 'right' }, { label: 'r (runs)', align: 'right' }, { label: 'r (other)', align: 'right' }],
      [].concat.apply([], ps.map(x => x[1].map(r => [{ v: x[0][1], html: '<strong>' + k.esc(x[0][1]) + '</strong>' }, { v: r.season, html: k.esc(r.season) }, { v: r.n, html: k.int(r.n) + ' ' + x[0][2] },
        { v: r.r, html: k.isNum(r.r) ? k.num(r.r, 3) : '—' }, { v: r.r2, html: k.isNum(r.r2) ? k.num(r.r2, 3) + ' <span class="muted-inline">' + x[0][3] + '</span>' : '—' }]))), { compact: true }) +
      '<div class="pg-note gq-note">Pearson correlations with Savant\'s leaderboards by season: framing for catchers with 1,000+ called pitches, fielding for fielders with 50+ chances. The current season is partial. Savant\'s framing leaderboard carries no run values before 2018 (zeros), so those seasons show the rate correlation only.</div>';
    return;
  }
  const items = [['framing', 'Framing runs v Savant framing', 'catchers'], ['oaa', 'Fielding runs v Savant OAA', 'fielders'], ['savant_framing', 'Framing v Savant', 'catchers'], ['catchprob', 'Catch probability v Savant OAA', 'fielders']];
  const rows = items.map(x => [x, d[x[0]] || C[x[0]]]).filter(x => x[1] && (k.isNum(x[1].r) || k.isNum(x[1].pearson) || k.isNum(x[1].spearman)));
  host.innerHTML = rows.length ? k.table([{ label: 'Check' }, { label: 'n', align: 'right' }, { label: 'Pearson r', align: 'right' }, { label: 'Spearman', align: 'right' }, { label: 'Slope', align: 'right' }, { label: 'RMSE', align: 'right' }],
    rows.map(x => { const v = x[1]; return [{ v: x[0][1], html: '<strong>' + k.esc(x[0][1]) + '</strong>' }, { v: v.n, html: k.int(v.n) + ' ' + x[0][2] }, { v: v.r || v.pearson, html: k.num(v.r || v.pearson, 3) }, { v: v.spearman, html: k.num(v.spearman, 3) }, { v: v.slope, html: k.num(v.slope, 2) }, { v: v.rmse, html: k.num(v.rmse, 2) }]; }), { compact: true })
    : k.muted('The comparisons with Savant\'s framing and OAA leaderboards are not in this build yet.');
}

if (typeof BP.route === 'function') { BP.route('calibration', render); try { BP.route('#/calibration', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
