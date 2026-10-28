/* The Quant Hardwood — player value (#/<L>/value): wins above replacement (WAR) from HPM, the best
 * players at each position, and a filterable leaderboard.
 *
 * Data: data/<L>/<S>/value.json (analytics/value.py season_value: cols/rows, best, currency, roles).
 * WAR = (HPM + 2.0) x possessions / 100 / points per win; possessions = minutes x league pace / 48 (40
 * WNBA); points per win = the game model's margin sd x sqrt(2 pi). Before a season's first regular-season
 * game the page shows the latest season that has one. */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const ROLE = { G: 'Guards', W: 'Wings', B: 'Bigs' };
const ROLE_ONE = { G: 'Guard', W: 'Wing', B: 'Big' };
const ST = { pos: 'all', team: 'all', min: null, q: '1', n: '100' };

function rowsOf(v) {
  const cols = (v && v.cols) || [];
  return ((v && v.rows) || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}

function why(fx, r) {
  const parts = [];
  if (fx.isNum(r.o) && fx.isNum(r.d)) parts.push('O ' + fx.signed(r.o, 1) + ' · D ' + fx.signed(r.d, 1));
  (r.why || []).forEach(w => parts.push(fx.esc(w[0]) + ' ' + w[1]));
  return parts.join(' · ');
}

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    const q = (params && params.query) || {};
    if (ST.key !== L + S) { ST.key = L + S; ST.team = 'all'; ST.min = null; }
    ['pos', 'team', 'min', 'q', 'n'].forEach(k => { if (q[k] !== undefined && q[k] !== '') ST[k] = q[k]; });
    return HW.load(fx.path(L, S, 'value.json')).then(v => {
      if (!fx.alive(el)) return null;
      if (fx.ok(v) && (v.rows || []).length) { draw(el, L, S, v, null); return null; }
      return HW.load(fx.path(L, S - 1, 'value.json')).then(pv => {
        if (!fx.alive(el)) return;
        if (fx.ok(pv) && (pv.rows || []).length) draw(el, L, S - 1, pv, S);
        else el.innerHTML = fx.card('Player value ' + fx.seasonLabel(L, S), '', fx.notBuilt('Player value for ' + fx.seasonLabel(L, S), v));
      });
    });
  });
}

function draw(el, L, S, v, asked) {
  const fx = FX();
  const rows = rowsOf(v);
  const byId = {}; rows.forEach(r => { byId[r.id] = r; });
  const cur = v.currency || {};
  const roles = v.roles || ROLE;
  const tName = id => fx.teamName(L, id);
  let h = '';
  /* round 9: early in a season the current rates are shown, marked early (WAR is small and HPM noisy for a few weeks);
     "has not started" only when the season really has not (the builder writes this season's rows from the first game) */
  const maxGp = Math.max.apply(null, rows.map(r => r.gp || 0).concat([0]));
  if (!asked && maxGp > 0 && maxGp < 20) h += '<div class="qk-note" style="margin-bottom:14px"><span class="qk-tag">Early</span> ' + maxGp + ' game' + (maxGp === 1 ? '' : 's') + ' into ' + fx.esc(fx.seasonLabel(L, S)) + ': WAR counts the season so far, so the totals are small, and the rates (HPM) move a lot until about 20 games. Read the order, not the size.</div>';
  const notYet = asked && HW.phase(L) !== 'preseason' && Number(asked) === Number(HW.currentSeason(L));
  if (asked) h += '<div class="card"><div class="pad">' + fx.muted('The ' + fx.esc(fx.seasonLabel(L, asked)) + (notYet ? ' value file has no players yet (it fills with the next build after the first games)' : ' regular season has not started') + ', so this page shows ' + fx.esc(fx.seasonLabel(L, S)) + '. Each team\'s projected value for ' + fx.esc(fx.seasonLabel(L, asked)) + ' is on its team page ("Strengths and needs") and in the <a href="' + fx.href(L, 'trade') + '">trade simulator</a>.') + '</div></div>';
  h += '<div class="card"><div class="card-header">Player value ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">Wins above replacement (WAR): a player\'s impact per 100 possessions over the possessions played, measured from a replacement-level player. <a href="' + fx.esc(HW.href(L, 'model') + '?tab=methodology') + '">How it works →</a></span></div>';
  const top = rows.filter(r => r.q).sort((a, b) => b.war - a.war);
  const best = v.best || {};
  h += '<div class="kpi-grid">' + [fx.tile('Most WAR', top[0] ? fx.esc(top[0].name) : '—', top[0] ? fx.num(top[0].war, 1) + ' WAR · ' + fx.esc(fx.teamAbbr(L, top[0].team)) + ' · HPM ' + fx.signed(top[0].hpm, 1) : '')]
    .concat(['G', 'W', 'B'].map(k => { const r = byId[(best[k] || [])[0]]; return fx.tile('Best ' + (ROLE_ONE[k] || k).toLowerCase(), r ? fx.esc(r.name) : '—', r ? fx.num(r.war, 1) + ' WAR · ' + fx.esc(fx.teamAbbr(L, r.team)) : ''); })).join('') + '</div></div>';
  h += '<div id="vl-v2"></div>';
  h += '<div class="card"><div class="card-header">Best at each position <span class="card-sub">Qualified players (' + fx.num(v.n_qualified, 0) + '; ' + (fx.isNum(v.min_floor) ? fx.num(v.min_floor, 0) + '+ minutes' : 'the minutes floor') + '). ESPN lists only G, F and C, so forwards are split into wings and bigs by box profile (rebounds, blocks, rim attempts against threes and assists). "Why" gives the offence and defence split of HPM and the player\'s best box skills (league percentile).</span></div><div class="grid-3 vl-best">' +
    ['G', 'W', 'B'].map(k => '<div><div class="vl-best-h">' + fx.esc(roles[k] || ROLE[k]) + '</div>' + HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'WAR', align: 'right' }, { label: 'HPM', align: 'right' }, { label: 'Pct', align: 'center', title: 'WAR percentile among qualified players' }],
      (best[k] || []).map((id, i) => { const r = byId[id] || {}; return { _href: fx.playerHref(L, id, S), cells: [i + 1, { v: r.name, html: fx.playerLink(L, id, r.name) + ' <span class="muted-inline">' + fx.esc(fx.teamAbbr(L, r.team)) + '</span><div class="vl-why">' + why(fx, r) + '</div>' }, { v: r.war, html: '<strong>' + fx.num(r.war, 1) + '</strong>' }, { v: r.hpm, html: fx.signed(r.hpm, 1) }, { v: r.pct, html: fx.pill(r.pct) }] }; }), { compact: true }) + '</div>').join('') + '</div></div>';
  const teams = Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort((a, b) => String(tName(a)).localeCompare(String(tName(b))));
  const maxMin = Math.max.apply(null, rows.map(r => r.min || 0).concat([100]));
  if (teams.indexOf(ST.team) < 0) ST.team = 'all';
  if (ST.min === null || !fx.isNum(ST.min)) ST.min = fx.isNum(v.min_floor) ? Math.round(v.min_floor) : 0;
  h += '<div class="card"><div class="card-header">Leaderboard <span class="card-sub" id="vl-sub"></span></div>' +
    '<div class="lab-controls hf-controls vl-ctl">' +
    '<label>Position<select id="vl-pos"><option value="all">All</option><option value="G">Guards</option><option value="W">Wings</option><option value="B">Bigs</option></select></label>' +
    '<label>Team<select id="vl-team"><option value="all">All teams</option>' + teams.map(t => '<option value="' + fx.esc(t) + '">' + fx.esc(tName(t)) + '</option>').join('') + '</select></label>' +
    '<label>Min minutes <span id="vl-min-v"></span><input id="vl-min" type="range" min="0" max="' + Math.ceil(maxMin / 50) * 50 + '" step="50"></label>' +
    '<label>Sample<select id="vl-q"><option value="1">Qualified only</option><option value="0">Everyone over the minutes</option></select></label>' +
    '<label>Show<select id="vl-n"><option value="50">Top 50</option><option value="100">Top 100</option><option value="0">All</option></select></label>' +
    '</div><div id="vl-table"></div><div class="pg-note">WAR and PAR (points above replacement) count the whole season; PAR/G is per game played; HPM is the rate per 100 possessions (O offence, D defence). Pct places WAR among qualified players (Pos pct among the same position group). ΔHPM is the change from last season. Percentiles of players below the minutes floor are against the qualified players and do not move theirs.</div></div>';
  h += '<div class="card"><div class="card-header">Rate against volume <span class="card-sub">HPM per 100 possessions against minutes played, coloured by position group; bigger dots carry more WAR. Qualified players.</span></div><div id="vl-chart" style="height:420px"></div></div>';
  el.innerHTML = h;
  const $ = id => document.getElementById(id);
  $('vl-pos').value = ST.pos; $('vl-team').value = teams.indexOf(ST.team) >= 0 ? ST.team : 'all'; $('vl-q').value = String(ST.q); $('vl-n').value = String(ST.n);
  $('vl-min').value = ST.min; $('vl-min-v').textContent = ST.min;
  const redraw = () => { syncUrl(L, S, asked); drawTable(L, S, rows); };
  $('vl-pos').onchange = e => { ST.pos = e.target.value; redraw(); };
  $('vl-team').onchange = e => { ST.team = e.target.value; redraw(); };
  $('vl-q').onchange = e => { ST.q = e.target.value; redraw(); };
  $('vl-n').onchange = e => { ST.n = e.target.value; redraw(); };
  $('vl-min').oninput = e => { ST.min = Number(e.target.value); $('vl-min-v').textContent = ST.min; };
  $('vl-min').onchange = redraw;
  drawTable(L, S, rows);
  HW.sortable(el);
  valuation(L);
  const T0 = QKC.tokens(), col = { G: T0.cat[0], W: T0.cat[1], B: T0.cat[2] };
  const q = rows.filter(r => r.q && fx.isNum(r.hpm));
  QKC.scatter('#vl-chart', { points: q.filter(r => col[r.role]).map(r => ({ x: r.min, y: r.hpm, name: r.name + ' (' + fx.teamAbbr(L, r.team) + ') · WAR ' + fx.num(r.war, 1), color: col[r.role], size: 5 + Math.max(0, r.war) * 1.2, href: fx.playerHref(L, r.id) })),
    legendItems: ['G', 'W', 'B'].map(k => ({ name: roles[k] || ROLE[k], color: col[k] })), refY: 0, labelTop: 6,
    xName: 'Minutes', yName: 'Total impact (HPM per 100 possessions)', xFmt: v => fx.num(v, 0), yFmt: v => fx.signed(v, 1), label: 'Impact against minutes, by role' });
}

function drawTable(L, S, rows) {
  const fx = FX();
  let list = rows.filter(r => (ST.pos === 'all' || r.role === ST.pos) && (ST.team === 'all' || r.team === ST.team) && (r.min || 0) >= Number(ST.min || 0) && (String(ST.q) !== '1' || r.q));
  list.sort((a, b) => b.war - a.war);
  const total = list.length;
  if (Number(ST.n) > 0) list = list.slice(0, Number(ST.n));
  document.getElementById('vl-sub').textContent = total + ' players · ' + (ST.pos === 'all' ? 'all positions' : ROLE[ST.pos]) + (ST.team === 'all' ? '' : ' · ' + fx.teamName(L, ST.team)) + ' · ' + ST.min + '+ minutes';
  document.getElementById('vl-table').innerHTML = list.length ? HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos', title: 'ESPN position and position group' }, { label: 'Age', align: 'right' },
    { label: 'GP', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'WAR', align: 'right' }, { label: 'PAR/G', align: 'right', title: 'Points above replacement per game played' }, { label: 'HPM', align: 'right', title: 'Per 100 possessions' },
    { label: 'O', align: 'right' }, { label: 'D', align: 'right' }, { label: 'Pct', align: 'center' }, { label: 'Pos pct', align: 'center' }, { label: 'ΔHPM', align: 'right', title: 'Change from last season' }, { label: 'Last WAR', align: 'right' }],
    list.map((r, i) => ({ _href: fx.playerHref(L, r.id, S), cells: [i + 1, { v: r.name, html: fx.playerLink(L, r.id, r.name) }, { v: fx.teamAbbr(L, r.team), html: fx.teamLink(L, r.team) }, { v: r.role, html: fx.esc((r.pos || '') + ' · ' + (ROLE_ONE[r.role] || r.role)) },
      { v: r.age, html: fx.num(r.age, 0) }, r.gp, { v: r.min, html: fx.num(r.min, 0) }, { v: r.war, html: '<strong>' + fx.num(r.war, 1) + '</strong>' }, { v: r.par_g, html: fx.num(r.par_g, 1) }, { v: r.hpm, html: fx.signed(r.hpm, 1) },
      { v: r.o, html: fx.signed(r.o, 1) }, { v: r.d, html: fx.signed(r.d, 1) }, { v: r.pct, html: fx.pill(r.pct) }, { v: r.pct_role, html: fx.pill(r.pct_role) },
      { v: r.d_hpm, html: fx.isNum(r.d_hpm) ? '<span class="' + (r.d_hpm > 0 ? 'pg-up' : r.d_hpm < 0 ? 'pg-down' : '') + '">' + fx.signed(r.d_hpm, 1) + '</span>' : '—' }, { v: r.prev_war, html: fx.num(r.prev_war, 1) }] })), { compact: true, sticky: true })
    : fx.muted('No players match these filters.');
  HW.sortable('vl-table');
}

function syncUrl(L, S, asked) {
  try {
    const q = {};
    if (ST.pos !== 'all') q.pos = ST.pos;
    if (ST.team !== 'all') q.team = ST.team;
    q.min = String(ST.min);
    if (String(ST.q) !== '1') q.q = String(ST.q);
    if (String(ST.n) !== '100') q.n = String(ST.n);
    const s = asked || S;
    if (s !== FX().current(L)) q.s = String(s);
    const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
    history.replaceState(null, '', '#/' + L + '/value?tab=war' + (qs ? '&' + qs : ''));
  } catch (e) { /* history unavailable */ }
}

// ── valuation v2 (data/<L>/<current>/valuation.json, analytics/valuation.py) ────────────────
const V2 = { role: 'all', sort: 'v', n: '50' };
function valuation(L) {
  const fx = FX();
  const C = fx.current(L);
  const box = document.getElementById('vl-v2');
  if (!box || !C) return;
  HW.load(fx.path(L, C, 'valuation.json')).then(v => {
    if (!box.isConnected) return;
    if (!fx.ok(v) || !v.rows) { box.innerHTML = fx.card('Valuation over four seasons', '', '<div class="pad">' + fx.notBuilt('Valuation v2', v) + '</div>'); return; }
    const rows = rowsOf(v);
    const k = v.constants || {}, f = v.fit || {}, sp = f.spread || {}, pos = v.positions || {};
    const si = f.surv_info || {};
    let h = '<div class="card"><div class="card-header">Valuation over four seasons ' + fx.esc(fx.seasonLabel(L, C)) + ' <span class="card-sub">Every rostered player\'s projected value over ' + fx.esc((v.slots || []).join(', ')) +
      ', in WAR discounted ' + fx.num(k.discount, 2) + ' a season: today\'s rest-of-season rate (HPM), aged each season along the fitted ageing curve, times depth-chart minutes, availability (games played over two seasons, regressed) and the chance the player is still playing (fitted on our seasons by age, rate and minutes); future seasons floored at replacement. The band (10th to 90th percentile) is a Monte Carlo over the rate (one-season-ahead spread ' + fx.num(sp.s1, 2) + ' per 100, drift ' + fx.num(sp.tau, 2) + ' a season), minutes and survival. VORP measures from the replacement level of the player\'s own position. On-field value only: no salaries or contracts.</span></div>' +
      '<div class="lab-controls hf-controls vl-ctl"><label>Position<select id="v2-role"><option value="all">All</option><option value="G">Guards</option><option value="W">Wings</option><option value="B">Bigs</option></select></label>' +
      '<label>Sort<select id="v2-sort"><option value="v">Four-season value</option><option value="vorp">VORP at position</option><option value="w0">' + fx.esc((v.slots || [])[0] || 'Now') + '</option><option value="w1">' + fx.esc((v.slots || [])[1] || 'Next') + '</option><option value="p90">Upside (p90)</option></select></label>' +
      '<label>Show<select id="v2-n"><option value="50">Top 50</option><option value="150">Top 150</option><option value="0">All</option></select></label></div><div id="v2-table"></div>' +
      '<div class="pg-note">Ageing fitted on ' + fx.num((f.aging_info || {}).n_pairs, 0) + ' player-season pairs (500+ minutes in both); survival logistic log-loss ' + fx.num(si.logloss, 3) + ' against ' + fx.num(si.logloss_base, 3) + ' for the base rate (' + fx.num(si.n, 0) + ' player-seasons); league availability ' + fx.pct(f.avail, 0) + '. Ages from ESPN\'s athlete records.</div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Ageing curve <span class="card-sub">Change in HPM over the next season by age: fitted on our seasons (delta method) against the hand-set curve the impact model and roster prior use.</span></div><div id="v2-age" style="height:300px"></div></div>' +
      '<div class="card"><div class="card-header">Position scarcity <span class="card-sub">Replacement level by position: the mean rate of each position\'s next tier of playing time after the league\'s rotations. Scarcity = league replacement (' + fx.signed(k.replacement, 1) + ') minus the position\'s level.</span></div>' +
      HW.tableHTML([{ label: 'Position' }, { label: 'Replacement', align: 'right' }, { label: 'Scarcity', align: 'right' }, { label: 'Top-10 rate', align: 'right' }, { label: 'Rotation slots', align: 'right' }],
        ['G', 'W', 'B'].map(r => { const x = pos[r] || {}; return [ROLE[r], { v: x.repl, html: fx.signed(x.repl, 2) }, { v: x.scarcity, html: fx.signed(x.scarcity, 2) }, { v: x.top10, html: fx.signed(x.top10, 2) }, x.slots]; }), { compact: true }) + '</div></div>';
    box.innerHTML = h;
    const $ = id => document.getElementById(id);
    $('v2-role').value = V2.role; $('v2-sort').value = V2.sort; $('v2-n').value = V2.n;
    const sl = v.slots || [];
    const draw = () => {
      let list = rows.filter(r => V2.role === 'all' || r.role === V2.role).sort((a, b) => (b[V2.sort] || 0) - (a[V2.sort] || 0));
      if (Number(V2.n) > 0) list = list.slice(0, Number(V2.n));
      $('v2-table').innerHTML = HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'HPM', align: 'right', title: 'Rest-of-season rate per 100' },
        { label: 'Min', align: 'right' }, { label: 'Avail', align: 'right' }].concat(sl.map(s => ({ label: s, align: 'right', title: 'WAR in this season slot (mean path)' })), [{ label: 'Value', align: 'right', title: 'Four-season WAR, discounted' }, { label: 'Band', align: 'center', title: '10th to 90th percentile' },
        { label: 'Still playing', align: 'right', title: 'Chance of still playing in the last slot' }, { label: 'VORP', align: 'right', title: 'Value over the position\'s replacement level' }]),
        list.map((r, i) => ({ _href: fx.playerHref(L, r.id), cells: [i + 1, { v: r.name, html: fx.playerLink(L, r.id, r.name) + (r.inj ? ' <span class="chip red">' + fx.esc(String(r.inj).slice(0, 3)) + '</span>' : '') }, { v: fx.teamAbbr(L, r.team), html: fx.teamLink(L, r.team, { abbr: true }) },
          ROLE_ONE[r.role] || r.role, { v: r.age, html: fx.num(r.age, 0) }, { v: r.rate, html: fx.signed(r.rate, 1) }, { v: r.mpg, html: fx.num(r.mpg, 0) }, { v: r.avail, html: fx.pct(r.avail, 0) }]
          .concat(['w0', 'w1', 'w2', 'w3'].slice(0, sl.length).map(c => ({ v: r[c], html: fx.num(r[c], 1) })), [{ v: r.v, html: '<strong>' + fx.num(r.v, 1) + '</strong>' }, { v: r.p90 - r.p10, html: fx.num(r.p10, 0) + '–' + fx.num(r.p90, 0) },
            { v: r.surv, html: fx.pct(r.surv, 0) }, { v: r.vorp, html: fx.num(r.vorp, 1) }]) })), { compact: true, sticky: true });
      HW.sortable('v2-table');
    };
    $('v2-role').onchange = e => { V2.role = e.target.value; draw(); };
    $('v2-sort').onchange = e => { V2.sort = e.target.value; draw(); };
    $('v2-n').onchange = e => { V2.n = e.target.value; draw(); };
    draw();
    const ag = f.aging || [], hs = f.aging_handset || [];
    QKC.line('#v2-age', { xType: 'value', series: [{ name: 'Fitted', color: QKC.tokens().model, width: 3, data: ag.map(a => [a[0], a[1]]) }, { name: 'Hand-set (roster prior)', color: QKC.tokens().ink3, dash: true, symbols: true, data: hs.map(a => [a[0], a[1]]) }],
      xName: 'Age', yName: 'Change in HPM next season', xFmt: v => String(Math.round(v)), yFmt: v => fx.signed(v, 1), ref: { y: 0 }, legend: true, endLabels: false, label: 'Ageing curve' });
  });
}

HW.route('value', render);
})(window.HW);
