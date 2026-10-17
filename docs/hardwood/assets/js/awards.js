/* The Quant Hardwood — award races (#/<L>/awards): MVP, Rookie of the Year, Defensive
 * Player, Sixth Man (Sixth Player in the WNBA), Most Improved and Clutch Player.
 *
 * Each race: the model's probability (a conditional logit on pool-standardised features,
 * fitted on past winners and projected to season end by simulation; models/awards.py)
 * against Kalshi / Polymarket where they trade, the eligibility under the NBA's 65-game
 * rule, and the features behind every candidate.
 *
 * Data: data/<L>/<S>/awards.json {award: {model, market, features, eligible}},
 * data/<L>/<S>/players.json (names, teams). */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const ORDER = ['mvp', 'roy', 'dpoy', '6moy', 'sixth', 'mip', 'clutch'];
const FEAT = {
  hpm_value: ['HPM value', 'HPM × share of team minutes × games', '2'], hpm_t: ['HPM', 'Hardwood Plus-Minus per 100', 'pm'], ppg: ['PPG', 'points a game', '1'], mpg: ['MPG', 'minutes a game', '1'],
  team_win_pct: ['Team win %', 'projected team win share', 'pct'], hpm_d_value: ['Def HPM value', 'defensive HPM × minutes share × games', '2'], bpg: ['BPG', 'blocks a game', '1'], spg: ['SPG', 'steals a game', '1'],
  dpg: ['DRPG', 'defensive rebounds a game', '1'], team_def: ['Team defence', 'league ORtg minus team DRtg', 'pm'], d_hpm: ['Δ HPM', 'HPM change on last season', 'pm'], d_ppg: ['Δ PPG', 'points-a-game change', 'pm'],
  d_mpg: ['Δ MPG', 'minutes-a-game change', 'pm'], clutch_wpa: ['Clutch WPA', 'win probability added in the clutch', '2'], wpa: ['WPA', 'win probability added, season', '2'],
  games: ['GP', 'games played', 'int'], elig_games: ['Qualifying games', 'games at 20+ minutes (two 15-20 minute games count)', 'int']
};
const WHY = {
  mvp: 'HPM value (impact times playing time), scoring, team success and per-possession HPM.',
  roy: 'Rookies only (first season in the data): scoring, minutes, HPM value and team success.',
  dpoy: 'Defensive HPM value, blocks, steals, defensive rebounds and the team\'s defence.',
  '6moy': 'Players who start fewer than half their games: scoring, HPM value, minutes and team success.',
  sixth: 'Players who start fewer than half their games: scoring, HPM value, minutes and team success.',
  mip: 'Players who also played last season: the change in HPM, scoring and minutes, and scoring now.',
  clutch: 'Win probability added in the clutch (last five minutes, within five points), season WPA and team success.'
};

let CUR = null;

/* Market price for pid: by id, else by folded name. */
function marketP(mk, pid, name) {
  if (!mk || mk.available === false) return null;
  const probs = mk.probs || mk.prices || {};
  if (FX().isNum(probs[pid])) return probs[pid];
  const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z]/g, '');
  const n = fold(name);
  if (!n) return null;
  const k = Object.keys(probs).find(x => fold(x) === n);
  return k ? probs[k] : null;
}

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    el.innerHTML = fx.muted('Loading the award races…');
    return Promise.all([HW.load(fx.path(L, S, 'awards.json')), fx.season(L, S)]).then(res => {
      if (!fx.alive(el)) return;
      const aw = res[0], cat = res[1][0];
      const P = ((cat || {}).players) || {};
      if (!aw || aw.ok === false) { el.innerHTML = fx.card('Award races ' + fx.seasonLabel(L, S), '', fx.notBuilt('The award model', aw)); return; }
      const keys = ORDER.filter(k => aw[k] && typeof aw[k] === 'object').concat(Object.keys(aw).filter(k => ORDER.indexOf(k) < 0 && aw[k] && typeof aw[k] === 'object' && (aw[k].model || aw[k].features)));
      if (!keys.length) { el.innerHTML = fx.card('Award races', '', fx.muted('No award race is open yet.')); return; }
      if (!CUR || keys.indexOf(CUR) < 0) CUR = keys[0];
      if (params.rest && params.rest[0] && keys.indexOf(params.rest[0]) >= 0) CUR = params.rest[0];
      const fav = k => { const M = aw[k].model || {}; const ids = Object.keys(M).sort((a, b) => fx.pOf(M[b]) - fx.pOf(M[a])); return ids[0] ? [ids[0], fx.pOf(M[ids[0]])] : null; };
      const won = k => { const W = aw[k].winner; return W && (W.names || []).length ? 'Won: ' + W.names.join(' / ') : ''; };
      el.innerHTML = '<div class="card"><div class="card-header">Award races ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">The model\'s probability of winning each award, projected to the end of the season, against the prediction markets. Click a race.</span></div>' +
        '<div class="hf-races">' + keys.map(k => { const f = fav(k); const n = f ? ((P[f[0]] || {}).name || ((aw[k].features || {})[f[0]] || {}).name || fx.playerName(L, f[0])) : '—';
          return '<button type="button" class="hf-race' + (k === CUR ? ' on' : '') + '" data-k="' + fx.esc(k) + '"><span class="hf-race-k">' + fx.esc(fx.awardName(k, L)) + '</span><span class="hf-race-n">' + fx.esc(n) + '</span><span class="hf-race-p">' + (f ? fx.pct(f[1]) : '') + '</span>' + (won(k) ? '<span class="hf-race-k">' + fx.esc(won(k)) + '</span>' : '') + '</button>'; }).join('') + '</div></div>' +
        '<div id="aw-body"></div>';
      el.querySelectorAll('.hf-race').forEach(b => b.addEventListener('click', () => { CUR = b.dataset.k; el.querySelectorAll('.hf-race').forEach(x => x.classList.toggle('on', x === b)); drawRace(L, S, CUR, aw[CUR], P, aw); }));
      drawRace(L, S, CUR, aw[CUR], P, aw);
    });
  });
}

function drawRace(L, S, key, A, P, aw) {
  const fx = FX(), C = fx.C;
  const M = A.model || {}, F = A.features || {}, E = A.eligible || {}, mk = A.market || null;
  const name = pid => (P[pid] || {}).name || (F[pid] || {}).name || fx.playerName(L, pid);
  const team = pid => (P[pid] || {}).team || (F[pid] || {}).team;
  const ids = Array.from(new Set(Object.keys(M).concat(Object.keys(F)))).sort((a, b) => (fx.pOf(M[b]) || 0) - (fx.pOf(M[a]) || 0));
  const featKeys = Array.from(new Set([].concat.apply([], ids.slice(0, 40).map(id => Object.keys(F[id] || {}))))).filter(k => ['name', 'team'].indexOf(k) < 0 && ids.some(id => fx.isNum((F[id] || {})[k])));
  featKeys.sort((a, b) => (['games', 'elig_games'].indexOf(a) >= 0) - (['games', 'elig_games'].indexOf(b) >= 0));
  const rule = L === 'nba' && ['mvp', 'dpoy', 'mip', 'clutch'].indexOf(key) >= 0 && S >= 2024;
  const mkOn = mk && mk.available !== false && Object.keys(mk.probs || mk.prices || {}).length;
  const host = document.getElementById('aw-body');
  const model = A.fit || (aw.models || {})[key] || null;
  const T3 = A.p_top3 || {};
  const top3 = id => (fx.isNum(T3[id]) ? T3[id] : (M[id] || {}).p_top3);
  const W = A.winner || null, wonIds = new Set(((W || {}).ids || []).filter(Boolean));
  const winLine = W && (W.names || []).length ? '<div class="mk-line"><strong>Winner</strong>: ' + W.names.map((n, i) => {
    const id = (W.ids || [])[i];
    return (id ? fx.playerLink(L, id, n, team(id)) : fx.esc(n)) + (id && fx.isNum(fx.pOf(M[id])) ? ' (model ' + fx.pct(fx.pOf(M[id])) + ')' : id ? '' : ' (not in the model\'s pool)');
  }).join(' and ') + '. The model\'s race below is computed from the whole season, for comparison with the announced result.</div>' : '';
  let h = '<div class="card"><div class="card-header">' + fx.esc(((aw.labels || {})[key]) || fx.awardName(key, L)) + ' <span class="card-sub">' + fx.esc(WHY[key] || '') + '</span></div>' +
    winLine + '<div id="aw-chart" style="height:' + Math.max(260, 26 * Math.min(14, ids.length) + 70) + 'px"></div>' +
    '<div class="mk-line">' + (mkOn ? '<strong>Market</strong>: ' + (mk.sources || []).map(s => '<span class="mk-src">' + fx.esc(s) + '</span>').join('') + ' de-vigged mid prices' + (fx.isNum(mk.implied_total) ? ' (raw book total ' + fx.pct(mk.implied_total, 0) + ')' : '') + '.' : '<strong>Market</strong>: no two-sided market for this award at the moment.') +
    (rule ? ' <strong>65-game rule</strong>: from 2023-24 the NBA requires 65 qualifying games (20+ minutes; two games of 15-20 minutes also count) for this award; the model removes players who cannot reach it and simulates the rest.' : '') + '</div></div>';
  h += '<div class="card"><div class="card-header">Candidates <span class="card-sub">Everyone in the pool, by model probability. Features are the raw season figures the model standardises within the pool.</span></div><div id="aw-table"></div>' +
    (model && model.weights ? '<div class="pg-note"><strong>Fitted weights</strong> (on pool-standardised features' + (fx.isNum(model.n_seasons) ? ', from ' + model.n_seasons + ' past seasons' : '') + '): ' + (model.features || []).map((f, i) => fx.esc((FEAT[f] || [f])[0]) + ' ' + fx.num(model.weights[i], 2)).join(' · ') + '.</div>' : '') +
    '<div class="pg-note">P(win) = exp(θᵢ) / Σⱼ exp(θⱼ) over the pool, θᵢ = Σₖ wₖ zᵢₖ, projected to season end by simulating remaining games, availability, team wins and HPM drift. See the <a href="#/methodology/awards">methodology</a>.</div></div>';
  host.innerHTML = h;

  const top = ids.slice(0, 14).reverse();
  const tr = [{ type: 'bar', orientation: 'h', name: 'Model', y: top.map(name), x: top.map(id => fx.pOf(M[id])), marker: { color: top.map(id => fx.teamColour(L, team(id))) }, hovertemplate: '%{y}: model %{x:.1%}<extra></extra>' }];
  if (mkOn) tr.push({ type: 'scatter', mode: 'markers', name: 'Market', y: top.map(name), x: top.map(id => marketP(mk, id, name(id))), marker: { symbol: 'diamond', size: 11, color: '#ffffff', line: { color: '#0d1117', width: 1 } }, hovertemplate: '%{y}: market %{x:.1%}<extra></extra>' });
  fx.plot('aw-chart', tr, fx.layout({ showlegend: !!mkOn, legend: { orientation: 'h', y: 1.06, font: { color: C.text2 } }, margin: { l: 140, r: 20, t: 20, b: 35 }, xaxis: { tickformat: '.0%', rangemode: 'tozero' }, yaxis: { automargin: true } }));

  const cols = [{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Model', align: 'right' }]
    .concat(ids.some(id => fx.isNum(top3(id))) ? [{ label: 'Top 3', align: 'right', title: 'Probability of finishing in the top three' }] : [])
    .concat(mkOn ? [{ label: 'Market', align: 'right' }, { label: 'Edge', align: 'right', title: 'Model minus market, percentage points' }] : [])
    .concat([{ label: 'Eligible', title: rule ? '65-game rule: can still reach 65 qualifying games (probability of qualifying in the simulation)' : 'In the candidate pool' }])
    .concat(featKeys.map(k => ({ label: (FEAT[k] || [k])[0], align: 'right', title: (FEAT[k] || [k, k])[1] })));
  const rows = ids.map((id, i) => {
    const m = M[id], p = fx.pOf(m), q = mkOn ? marketP(mk, id, name(id)) : null;
    const el = E[id], f = F[id] || {};
    const elig = el === false || (m && m.can_qualify === false) ? '<span class="pg-tag bad">out</span>' : rule && m && fx.isNum(m.p_eligible) && m.p_eligible < 0.999 ? '<span class="pg-tag warn">' + fx.pct(m.p_eligible, 0) + '</span>' : '<span class="pg-tag good">yes</span>';
    const cells = [i + 1, { v: name(id), html: fx.playerLink(L, id, name(id), team(id)) + (wonIds.has(id) ? ' <span class="pg-tag good">winner</span>' : '') },{ v: fx.teamAbbr(L, team(id)), html: team(id) ? fx.teamLink(L, team(id), { abbr: true }) : '—' }, { v: p, html: '<strong>' + fx.pct(p) + '</strong>' }];
    if (ids.some(x => fx.isNum(top3(x)))) cells.push({ v: top3(id), html: fx.pct(top3(id), 0) });
    if (mkOn) cells.push({ v: q, html: fx.pct(q) }, { v: fx.isNum(p) && fx.isNum(q) ? p - q : null, html: fx.isNum(p) && fx.isNum(q) ? '<span class="' + (p > q ? 'pg-edge-pos' : 'pg-edge-neg') + '">' + fx.signed(100 * (p - q), 1) + '</span>' : '—' });
    cells.push({ v: el === false ? 0 : 1, html: elig });
    featKeys.forEach(k => cells.push({ v: f[k], html: fx.fmtV(f[k], (FEAT[k] || [])[2] || '2') }));
    return { _href: fx.playerHref(L, id), cells: cells };
  });
  document.getElementById('aw-table').innerHTML = rows.length ? HW.tableHTML(cols, rows.slice(0, 60), { compact: true, sticky: true }) : fx.muted('No candidates yet.');
  HW.sortable('aw-table');
}

HW.route('awards', render);
})(window.HW);
