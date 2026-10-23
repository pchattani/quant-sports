/* The Quant Rink — Valuation (multi-season): the "Valuation (multi-season)" tab of #/value (#/value?tab=val), and the
 * tab bar shared by the value pages. value.js calls RK.valuation.render(el) for ?tab=val and RK.valuation.tabs(S, cur).
 *
 * Data: data/<S>/valuation.json for the current season (analytics/valuation.py current_payload): cols/rows per rostered
 * player (rate, se, mpg, avail, games, now, next, total, p10, p90, vorp, s1, s3, inj, basis), constants, fits
 * (reliability, minutes, survival, positional replacement and scarcity) and curves (aging, survival by age).
 * Values are on-field model value in WAR, never contracts or the cap. Uses RK.fk (skaters.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const POS = { C: 'Centres', L: 'Left wings', R: 'Right wings', D: 'Defence', G: 'Goalies' };
const POS_ONE = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G' };
const VT = { kind: 'S', pos: 'all', team: 'all', sort: 'total', n: '100', inj: '0' };

function rowsOf(v) {
  const cols = (v && v.cols) || [];
  return ((v && v.rows) || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}

function tabs(S, cur) {
  const k = K();
  const curS = k.curSeason();
  const list = [['season', 'Season value', '#/value' + (Number(S) !== curS ? '?s=' + S : '')], ['val', 'Valuation (multi-season)', '#/value?tab=val'],
    ['moves', 'Moves and trade grades', '#/moves'], ['fantasy', 'Fantasy', '#/fantasy'], ['trade', 'Trade simulator', '#/trade']];
  return '<div class="vv-tabs">' + list.map(t => '<a class="vv-tab' + (t[0] === cur ? ' on' : '') + '" href="' + t[2] + '">' + k.esc(t[1]) + '</a>').join('') + '</div>';
}

function render(el) {
  const k = K();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.curSeason();
    return Promise.all([k.loadY(S, 'valuation.json'), k.loadNames()]).then(res => {
      if (!k.alive(el)) return;
      const v = res[0];
      if (!k.ok(v) || !(v.rows || []).length) { el.innerHTML = tabs(S, 'val') + k.card('Valuation (multi-season)', '', '<div class="pad">' + k.notBuilt('The multi-season valuation', v) + '</div>'); return; }
      draw(el, S, v);
    });
  });
}

function band(r) {
  const k = K();
  return '<span class="vv-band" title="10th to 90th percentile of the four-season value">' + k.num(r.p10, 1) + ' to ' + k.num(r.p90, 1) + '</span>';
}

function injChip(r) {
  const k = K();
  if (!r.inj) return '';
  const st = r.inj[0], ret = r.inj[1], g = r.inj[2];
  return ' <span class="chip vv-inj" title="ESPN injury status' + (ret ? '; return date ' + k.esc(ret) : '') + (g ? '; ' + g + ' games missed in the projection' : '') + '">' + k.esc(st) + '</span>';
}

function draw(el, S, v) {
  const k = K();
  const rows = rowsOf(v);
  const C = v.constants || {}, F = v.fits || {}, P = ((F.positional || {}).positions) || {};
  const rel = F.reliability || {};
  const best = (kind, f) => rows.filter(r => (kind === 'G' ? r.pos === 'G' : r.pos !== 'G') && (!f || f(r))).sort((a, b) => b.total - a.total)[0];
  const tS = best('S'), tG = best('G'), tY = best('S', r => k.isNum(r.age) && r.age <= 23);
  const scarce = ['C', 'L', 'R', 'D'].filter(p => P[p] && k.isNum(P[p].scarcity)).sort((a, b) => P[b].scarcity - P[a].scarcity)[0];
  let h = tabs(S, 'val');
  h += '<div class="card"><div class="card-header">Valuation (multi-season) ' + k.esc(k.sLabel(S)) + ' <span class="card-sub">Each rostered player\'s projected on-field value in WAR over the rest of this season and the next ' + (C.horizon || 3) + ', discounted ' + k.num(C.discount, 1) + ' a season: the player\'s rest-of-season Rink value rate, aged a season at a time on the fitted ageing curve, times projected minutes, availability and the chance of still being an NHL regular. The band is the 10th to 90th percentile of ' + k.int(C.draws) + ' simulated careers (rate uncertainty, year-to-year drift, minutes and survival). VORP subtracts the replacement level at the player\'s own position. On-field value only: not contracts or the salary cap (no salary source). <a href="#/methodology/valuation">Method</a></span></div>';
  h += k.tiles([
    k.tile('Most valuable skater', tS ? k.playerLink(tS.id, tS.name) : '—', tS ? k.num(tS.total, 1) + ' WAR over four seasons · ' + k.esc(tS.team) : ''),
    k.tile('Most valuable goalie', tG ? k.playerLink(tG.id, tG.name) : '—', tG ? k.num(tG.total, 1) + ' WAR · ' + k.esc(tG.team) : ''),
    k.tile('Most valuable, 23 or under', tY ? k.playerLink(tY.id, tY.name) : '—', tY ? k.num(tY.total, 1) + ' WAR · age ' + k.num(tY.age, 0) : ''),
    k.tile('Scarcest position', scarce ? POS[scarce] : '—', scarce ? 'scarcity ' + k.num(P[scarce].scarcity, 2) + ' (1 = average skater)' : '')]) + '</div>';
  const teams = Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort();
  if (teams.indexOf(VT.team) < 0) VT.team = 'all';
  h += '<div class="card"><div class="card-header">Players <span class="card-sub" id="vv-sub"></span></div><div class="lab-controls vl-ctl">' +
    '<label>Players<select id="vv-kind"><option value="S">Skaters</option><option value="G">Goalies</option><option value="all">Everyone</option></select></label>' +
    '<label>Position<select id="vv-pos"><option value="all">All</option><option value="C">Centres</option><option value="L">Left wings</option><option value="R">Right wings</option><option value="D">Defence</option></select></label>' +
    '<label>Team<select id="vv-team"><option value="all">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamName(t)) + '</option>').join('') + '</select></label>' +
    '<label>Sort<select id="vv-sort"><option value="total">Four-season value</option><option value="vorp">Value over positional replacement</option><option value="now">This season</option><option value="next">Next season</option></select></label>' +
    '<label>Injured<select id="vv-inj"><option value="0">Everyone</option><option value="1">Injured only</option></select></label>' +
    '<label>Show<select id="vv-n"><option value="50">Top 50</option><option value="100">Top 100</option><option value="0">All</option></select></label></div><div id="vv-table"></div>' +
    '<div class="pg-note gq-note">Rate: rest-of-season GAR per 60 (± its standard error). TOI: projected minutes a game when playing (goalies: minutes per team game). Avail: expected share of team games played (games played this season and the last two, regressed to the league mean of regulars with ' + k.num(C.avail_pseudo, 0) + ' pseudo-games; goalies 100 %, their minutes are already a share). This season: WAR over the team\'s games left, after injuries (ESPN status and return date). Next: next season\'s expected WAR (survival included). 4 seasons: the discounted total, with its p10–p90 band. P(reg): the chance the player is still a regular next season and in three seasons.</div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Position scarcity <span class="card-sub">Replacement level at each position: the minute-weighted GAR per 60 of players outside the league\'s top N at that position by ice time (N = the position\'s share of 13 forwards, 7 defence and 2 goalies a team), pooled over ' + k.esc(((F.positional || {}).seasons || []).map(x => k.sLabel(x)).join(', ')) + '. Scarcity: the starters\' rate minus replacement, over the same gap for all skaters.</span></div>' +
    k.table([{ label: 'Pos' }, { label: 'Top N', align: 'right' }, { label: 'Starters', align: 'right', title: 'GAR per 60' }, { label: 'Repl.', align: 'right', title: 'GAR per 60' }, { label: 'Gap', align: 'right' }, { label: 'Scarcity', align: 'right' }],
      ['C', 'L', 'R', 'D', 'G'].filter(p => P[p]).map(p => [POS[p], P[p].n_top, { v: P[p].starter, html: k.num(P[p].starter, 3) }, { v: P[p].repl, html: k.signed(P[p].repl, 3) }, { v: P[p].gap, html: k.num(P[p].gap, 3) }, { v: P[p].scarcity, html: k.isNum(P[p].scarcity) ? '<strong>' + k.num(P[p].scarcity, 2) + '</strong>' : '—' }]), { compact: true }) + '</div>' +
    '<div class="card"><div class="card-header">Survival and ageing <span class="card-sub">The chance a regular of each age is still one next season (logistic fit on every pair of completed seasons, shown at a replacement-level rate and typical minutes), and the change in GAR per 60 a season of age brings (dotted, right axis).</span></div><div id="vv-surv" class="gf-chart" style="height:260px"></div></div></div>';
  h += '<div class="card"><div class="card-header">Fitted constants <span class="card-sub">Estimated from our own seasons ' + k.esc((F.completed || []).length ? k.sLabel(F.completed[0]) + ' to ' + k.sLabel(F.completed[F.completed.length - 1]) : '') + '.</span></div><div class="pad pg-note">' +
    ['S', 'G'].filter(x => rel[x]).map(x => {
      const sv = (F.survival || {})[x] || {};
      return '<div><strong>' + (x === 'S' ? 'Skaters' : 'Goalies') + '</strong>: noise σ² = ' + k.num(rel[x].sigma2, 4) + ' per 60 minutes, true spread τ² = ' + k.num(rel[x].tau2, 4) + ', year-to-year drift δ² = ' + k.num(rel[x].delta2, 4) + ' (' + k.int(rel[x].n_pairs) + ' season pairs); the rate is half signal at ' + k.int(rel[x].k_rel) + ' minutes. Minutes CV ' + k.num(((F.minutes || {})[x] || {}).cv, 3) + '; survival base rate ' + k.pct(sv.base, 1) + ' (log-loss ' + k.num(sv.logloss, 3) + ' against ' + k.num(sv.logloss_base, 3) + ' for the base rate).</div>';
    }).join('') + '</div></div>';
  el.innerHTML = h;
  const $ = id => document.getElementById(id);
  $('vv-kind').value = VT.kind; $('vv-pos').value = VT.pos; $('vv-team').value = VT.team; $('vv-sort').value = VT.sort; $('vv-n').value = VT.n; $('vv-inj').value = VT.inj;
  const redraw = () => drawTable(rows);
  ['kind', 'pos', 'team', 'sort', 'n', 'inj'].forEach(x => { $('vv-' + x).onchange = e => { VT[x] = e.target.value; redraw(); }; });
  redraw();
  survChart(v);
}

function drawTable(rows) {
  const k = K();
  const g = VT.kind === 'G';
  document.getElementById('vv-pos').disabled = g;
  let list = rows.filter(r => (VT.kind === 'all' || (g ? r.pos === 'G' : r.pos !== 'G')) && (g || VT.pos === 'all' || r.pos === VT.pos) &&
    (VT.team === 'all' || r.team === VT.team) && (VT.inj !== '1' || !!r.inj));
  list.sort((a, b) => (b[VT.sort] || 0) - (a[VT.sort] || 0));
  const total = list.length;
  if (Number(VT.n) > 0) list = list.slice(0, Number(VT.n));
  document.getElementById('vv-sub').textContent = total + ' players' + (VT.team === 'all' ? '' : ' · ' + k.teamName(VT.team));
  const head = [{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'Rate', align: 'right', title: 'Rest-of-season GAR per 60 ± standard error' },
    { label: 'TOI', align: 'right' }, { label: 'Avail', align: 'right' }, { label: 'This season', align: 'right', title: 'WAR over the games left' }, { label: 'Next', align: 'right', title: 'Next season, WAR' },
    { label: '4 seasons', align: 'right', title: 'Discounted WAR, rest of this season + three' }, { label: 'Band', align: 'right', title: 'p10 to p90' }, { label: 'VORP', align: 'right', title: 'Over replacement at the position' },
    { label: 'P(reg)', align: 'right', title: 'Still a regular next season / in three seasons' }];
  document.getElementById('vv-table').innerHTML = list.length ? k.table(head, list.map((r, i) => ({ _href: k.playerHref(r.id), cells: [i + 1,
    { v: r.name, html: k.playerLink(r.id, r.name) + injChip(r) }, { v: r.team, html: k.teamChip(r.team) }, POS_ONE[r.pos] || r.pos, { v: r.age, html: k.num(r.age, 0) },
    { v: r.rate, html: k.num(r.rate, 2) + ' <span class="muted-inline">±' + k.num(r.se, 2) + '</span>' }, { v: r.mpg, html: k.num(r.mpg, 1) }, { v: r.avail, html: k.pct(r.avail, 0) },
    { v: r.now, html: k.num(r.now, 2) }, { v: r.next, html: k.num(r.next, 2) }, { v: r.total, html: '<strong>' + k.num(r.total, 1) + '</strong>' }, { v: r.p10, html: band(r) },
    { v: r.vorp, html: k.num(r.vorp, 1) }, { v: r.s1, html: k.pct(r.s1, 0) + ' / ' + k.pct(r.s3, 0) }] })), { compact: true, sticky: true }) : k.muted('No players match these filters.');
  k.sortable('vv-table');
}

function survChart(v) {
  const k = K();
  const c = v.curves || {};
  const sv = c.survival || {}, ag = c.aging || {};
  const tr = [];
  [['S', 'Skaters', k.ACC], ['G', 'Goalies', '#f97316']].forEach(x => {
    if (sv[x[0]]) tr.push({ x: sv[x[0]].map(p => p[0]), y: sv[x[0]].map(p => p[1]), name: x[1] + ': P(regular next season)', type: 'scatter', mode: 'lines', line: { color: x[2], width: 2 } });
    if (ag[x[0]]) tr.push({ x: ag[x[0]].map(p => p[0]), y: ag[x[0]].map(p => p[1]), name: x[1] + ': ageing', yaxis: 'y2', type: 'scatter', mode: 'lines', line: { color: x[2], width: 1.5, dash: 'dot' } });
  });
  if (!tr.length) { k.empty('vv-surv', 'No fitted curves.'); return; }
  k.plot('vv-surv', tr, k.layout(Object.assign({ xaxis: { title: { text: 'Age' }, range: [19, 41] }, yaxis: { title: { text: 'P(regular next season)' }, range: [0, 1], tickformat: '.0%' },
    yaxis2: { title: { text: 'Δ GAR per 60 a season' }, overlaying: 'y', side: 'right', zeroline: true, showgrid: false }, margin: { l: 56, r: 56, t: 10, b: 44 } }, k.legendTop())));
}

/* The player's line on his page (player.js may call it; cheap: one cached file). */
function playerLine(pid) {
  const k = K();
  const S = k.curSeason();
  return k.loadY(S, 'valuation.json').then(v => {
    if (!k.ok(v)) return null;
    const r = rowsOf(v).find(x => String(x.id) === String(pid));
    return r || null;
  });
}

RK.valuation = { render: render, tabs: tabs, playerLine: playerLine, rowsOf: rowsOf };
})(window.RK);
