/* The Quant Hardwood — compare two players (#/<L>/compare/players/<a>/<b>) or two teams
 * (#/<L>/compare/teams/<a>/<b>); #/<L>/compare alone shows the pickers.
 *
 * Players: identity cards, a verdict strip (who wins more of the percentile metrics and
 * the biggest gaps each way), a radar, the full catalogue with gap bars and percentile
 * pills, shot charts side by side, career HPM overlaid, and the head to head when they
 * met. Teams: the same furniture over the team catalogue, plus rating paths, four
 * factors, shot profiles at both ends, lineups and the season series. */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const CA = '#58a6ff', CB = '#f97316';
const RADAR_P = ['hpm', /^hpm$/, 'hpm_o', /hpm_?o/, 'hpm_d', /hpm_?d/, 'ts', /^ts/, 'usg', /usg/, 'ast_pct', /ast/, 'trb_pct', /reb|trb/, 'stl_pct', /stl/, 'blk_pct', /blk/, 'pox100', 'pox', /pox|making/];
const RADAR_T = ['net', /^net/, 'ortg', /^o_?rtg|off/, 'drtg', /^d_?rtg|def/, 'pace', 'efg', /efg/, 'tov_pct', /tov/, 'orb_pct', /orb/, 'ftr', /ftr|ft_?rate/, /xpts|luck/, /clutch/];

function gapBar(gap) {
  const fx = FX();
  if (!fx.has(gap)) return '<span class="cmp-gap" title="no percentile on one side"></span>';
  const w = Math.min(50, Math.abs(gap) / 2);
  return '<span class="cmp-gap" title="' + fx.signed(gap, 0) + ' percentile points"><span class="' + (gap >= 0 ? 'a' : 'b') + '" style="width:' + w + '%"></span></span>';
}

function verdictAndTables(metrics, A, B, nameA, nameB, scopeNote) {
  const fx = FX(), has = fx.has;
  const comp = metrics.map(m => ({ m: m, a: (A.pct || {})[m.key], b: (B.pct || {})[m.key] })).filter(x => has(x.a) && has(x.b)).map(x => Object.assign(x, { gap: x.a - x.b }));
  let verdict;
  if (!comp.length) verdict = fx.muted('No metric has a percentile for both.');
  else {
    const wa = comp.filter(x => x.gap > 0).length, wb = comp.filter(x => x.gap < 0).length, lv = comp.length - wa - wb, n = comp.length;
    const topA = comp.filter(x => x.gap > 0).sort((x, y) => y.gap - x.gap).slice(0, 3);
    const topB = comp.filter(x => x.gap < 0).sort((x, y) => x.gap - y.gap).slice(0, 3);
    const say = (list, who) => (list.length ? '<strong>' + fx.esc(who) + '</strong>: ' + list.map(x => '+' + Math.round(Math.abs(x.gap)) + ' pct on ' + fx.esc(x.m.label)).join('; ') : '<strong>' + fx.esc(who) + '</strong>: leads on nothing');
    verdict = '<div class="cmp-verdict"><div class="cmp-verdict-side a">' + say(topA, nameA) + '</div>' +
      '<div class="cmp-verdict-mid"><div class="cmp-score"><span class="a">' + wa + '</span><span class="dash">–</span><span class="b">' + wb + '</span></div>' +
      '<div class="cmp-wins"><span class="a" style="width:' + (100 * wa / n) + '%"></span><span class="t" style="width:' + (100 * lv / n) + '%"></span><span class="b" style="width:' + (100 * wb / n) + '%"></span></div>' +
      '<div class="cmp-score-sub">metrics won of ' + n + (lv ? ' · ' + lv + ' level' : '') + (scopeNote ? ' · ' + scopeNote : '') + '</div></div>' +
      '<div class="cmp-verdict-side b">' + say(topB, nameB) + '</div></div>';
  }
  const row = (m, withGroup) => {
    const va = (A.values || {})[m.key], vb = (B.values || {})[m.key], qa = (A.pct || {})[m.key], qb = (B.pct || {})[m.key];
    const gap = has(qa) && has(qb) ? qa - qb : null;
    const better = has(va) && has(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    const cells = [{ v: m.label, html: fx.glossLink(m.key, fx.esc(m.label)) + (m.lower ? ' <span class="muted-inline">↓</span>' : '') }];
    if (withGroup) cells.push({ v: m.group, html: '<span class="muted-inline">' + fx.esc(m.group || '') + '</span>' });
    cells.push({ v: has(va) ? va : -1e9, html: (better === 'a' ? '<strong>' : '') + fx.fmt(m, va) + (better === 'a' ? '</strong>' : ''), align: 'right' });
    cells.push({ v: has(qa) ? qa : -1, html: fx.pill(qa), align: 'center' });
    cells.push({ v: gap === null ? -1 : Math.abs(gap), html: gapBar(gap), align: 'center' });
    cells.push({ v: has(qb) ? qb : -1, html: fx.pill(qb), align: 'center' });
    cells.push({ v: has(vb) ? vb : -1e9, html: (better === 'b' ? '<strong>' : '') + fx.fmt(m, vb) + (better === 'b' ? '</strong>' : ''), align: 'right' });
    return { cells: cells };
  };
  const cols = wg => [{ label: 'Metric' }].concat(wg ? [{ label: 'Group' }] : []).concat([{ label: nameA, align: 'right' }, { label: 'Pct', align: 'center' },
    { label: 'Gap', align: 'center', title: 'Percentile-point gap: blue when ' + nameA + ' leads, orange when ' + nameB + ' does' }, { label: 'Pct', align: 'center' }, { label: nameB, align: 'right' }]);
  const byGroup = fx.groups(metrics).map(g => '<div class="cmp-group-head">' + fx.esc(g.name) + '</div>' + HW.tableHTML(cols(false), g.items.map(m => row(m, false)), { compact: true })).join('');
  const flat = metrics.map(m => ({ m: m, g: has((A.pct || {})[m.key]) && has((B.pct || {})[m.key]) ? Math.abs(A.pct[m.key] - B.pct[m.key]) : -1 })).sort((x, y) => y.g - x.g);
  const byGap = HW.tableHTML(cols(true), flat.map(x => row(x.m, true)), { compact: true, sticky: true });
  return { verdict: verdict, byGroup: byGroup, byGap: byGap, n: comp.length };
}
function wireMetricTable(t) {
  const sel = document.getElementById('cmp-metric-mode');
  const draw = () => { document.getElementById('cmp-metrics').innerHTML = sel.value === 'gap' ? t.byGap : t.byGroup; HW.sortable('cmp-metrics'); };
  sel.onchange = draw;
  draw();
}
const METRIC_CARD = sub => '<div class="card"><div class="card-header">Every metric <span class="card-sub">' + sub + '</span><label class="pg-ctl">order <select id="cmp-metric-mode"><option value="group">by group</option><option value="gap">by size of gap</option></select></label></div><div id="cmp-metrics"></div></div>';

function pickerHTML(L, kind, a, b, opts) {
  const fx = FX();
  const sel = (id, cur) => '<select id="' + id + '" class="hf-pick"><option value="">— pick —</option>' + opts.map(o => '<option value="' + fx.esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + fx.esc(o[1]) + '</option>').join('') + '</select>';
  return '<div class="card"><div class="card-header">Compare ' + kind + ' <span class="card-sub">Pick two; the address updates so a comparison can be shared.</span>' +
    '<span class="pg-ctl">' + fx.toggle('cmp-kind', [['players', 'Players'], ['teams', 'Teams']], kind) + '</span></div>' +
    '<div class="controls"><span class="cmp-pill-a"></span>' + sel('cmp-a', a) + '<span class="muted-inline">v</span><span class="cmp-pill-b"></span>' + sel('cmp-b', b) +
    '<button type="button" id="cmp-swap" class="pg-search hf-btn">⇄ swap</button></div></div>';
}
function wirePicker(el, L, kind, a, b) {
  const fx = FX();
  const go = () => { const x = document.getElementById('cmp-a').value, y = document.getElementById('cmp-b').value; if (x && y && x !== y) location.hash = fx.href(L, 'compare/' + kind + '/' + encodeURIComponent(x) + '/' + encodeURIComponent(y)); };
  document.getElementById('cmp-a').onchange = go; document.getElementById('cmp-b').onchange = go;
  document.getElementById('cmp-swap').onclick = () => { if (a && b) location.hash = fx.href(L, 'compare/' + kind + '/' + encodeURIComponent(b) + '/' + encodeURIComponent(a)); };
  fx.wireToggle(el, 'cmp-kind', v => { if (v !== kind) location.hash = fx.href(L, 'compare/' + v); });
}
function idCard(i, badge, colour, nameHTML, subHTML, facts) {
  return '<div class="cmp-id ' + (i ? 'b' : 'a') + '"><div class="pg-num" style="--team:' + FX().esc(colour) + ';width:52px;height:52px;font-size:0.95rem">' + FX().esc(badge) + '</div><div class="cmp-id-body">' +
    '<div class="cmp-id-name">' + nameHTML + '</div><div class="cmp-id-sub">' + subHTML + '</div>' +
    '<div class="cmp-id-facts">' + facts.map(f => '<div class="cmp-fact"><span>' + f[0] + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div></div>';
}

// ── players ────────────────────────────────────────────────────────────────

/* The player's catalogue row: the season shown if he played in it, else his latest season with one. */
function playerSeason(L, pid, S, career) {
  const fx = FX();
  return HW.load(fx.path(L, S, 'players.json')).then(cat => {
    if (cat && cat.players && cat.players[pid]) return { season: S, cat: cat, p: cat.players[pid] };
    const yrs = ((career || {}).seasons || []).map(s => s.season).filter(v => v !== S).sort((x, y) => y - x);
    const tryY = i => (i >= yrs.length || i > 3 ? Promise.resolve({ season: null, cat: null, p: null }) : HW.load(fx.path(L, yrs[i], 'players.json')).then(c2 => (c2 && c2.players && c2.players[pid] ? { season: yrs[i], cat: c2, p: c2.players[pid] } : tryY(i + 1))));
    return tryY(0);
  });
}

function renderComparePlayers(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  const a = String(params.a || ''), b = String(params.b || '');
  el.innerHTML = '<div id="cmp-pick"></div><div id="cmp-body"></div>';
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    return HW.load(fx.path(L, S, 'players.json')).then(cat => {
      if (!fx.alive(el)) return null;
      fx.learnPlayers(L, cat);
      const P = ((cat || {}).players) || {};
      const ids = Object.keys(P).sort((x, y) => String(P[x].name).localeCompare(String(P[y].name)));
      [a, b].forEach(x => { if (x && ids.indexOf(x) < 0) ids.push(x); });
      document.getElementById('cmp-pick').innerHTML = pickerHTML(L, 'players', a, b, ids.map(k => [k, (P[k] ? P[k].name + ' (' + fx.teamAbbr(L, P[k].team) + ')' : fx.playerName(L, k))]));
      wirePicker(el, L, 'players', a, b);
      if (!a || !b) { document.getElementById('cmp-body').innerHTML = fx.card('', '', fx.muted('Pick two players. Players in the same position pool make the cleanest comparison: their percentiles are ranked against the same group.')); return null; }
      document.getElementById('cmp-body').innerHTML = fx.muted('Loading…');
      return Promise.all([HW.load(L + '/players/' + a + '.json'), HW.load(L + '/players/' + b + '.json')]).then(cs => Promise.all([playerSeason(L, a, S, cs[0]), playerSeason(L, b, S, cs[1])]).then(ss => {
        if (fx.alive(el)) buildPlayers(L, S, [a, b], ss, cs);
      }));
    });
  });
}

function buildPlayers(L, S, ids, ss, careers) {
  const fx = FX(), C = fx.C;
  const names = ids.map((id, i) => (ss[i].p && ss[i].p.name) || (careers[i] && careers[i].name) || fx.playerName(L, id));
  const short = names.map(fx.surname);
  const same = ss[0].season && ss[0].season === ss[1].season;
  const metrics = ((ss[0].cat || ss[1].cat || {}).metrics) || [];
  const samePool = ss[0].p && ss[1].p && ss[0].p.pool && ss[0].p.pool === ss[1].p.pool;
  const card = i => {
    const p = ss[i].p || {}, c = careers[i] || {}, v = p.values || {};
    const hk = fx.pick(v, ['hpm', 'hpm_t', /^hpm$/]), rk = fx.pick(v, ['rapm', /^rapm/]), wk = fx.pick(v, ['wpa', /^wpa$/]);
    const age = fx.isNum(p.age) ? Math.floor(p.age) : fx.ageOf(c.dob);
    return idCard(i, p.team ? fx.teamAbbr(L, p.team) : (p.pool || '—'), p.team ? fx.teamColour(L, p.team) : (i ? CB : CA), fx.playerLink(L, ids[i], names[i]),
      (p.team ? fx.teamLink(L, p.team) : '') + (p.pos ? ' · ' + fx.esc(p.pos) : '') + (age !== null ? ' · age ' + age : ''),
      [['Season', ss[i].season ? fx.esc(fx.seasonLabel(L, ss[i].season)) : '—'], ['GP', fx.has(p.gp) ? p.gp : '—'], ['MPG', p.gp ? fx.num(p.min / p.gp, 1) : '—'], ['HPM', fx.signed(hk ? v[hk] : null, 1)], ['RAPM', fx.signed(rk ? v[rk] : null, 1)], ['WPA', fx.signed(wk ? v[wk] : null, 2)],
        ['Seasons', (c.seasons || []).length || '—'], ['Awards', (c.career_awards || []).length]]);
  };
  const usePool = samePool && same;
  const A = Object.assign({}, ss[0].p || {}, { pct: usePool ? (ss[0].p || {}).pct_pool : (ss[0].p || {}).pct });
  const B = Object.assign({}, ss[1].p || {}, { pct: usePool ? (ss[1].p || {}).pct_pool : (ss[1].p || {}).pct });
  const t = verdictAndTables(metrics, A, B, short[0], short[1], same ? (usePool ? 'position-pool percentiles, ' : 'league percentiles, ') + fx.seasonLabel(L, ss[0].season) : 'different seasons (' + fx.seasonLabel(L, ss[0].season) + ' v ' + fx.seasonLabel(L, ss[1].season) + '): each percentile is against its own season');
  let h = '<div class="cmp-ids">' + card(0) + card(1) + '</div>';
  h += fx.card('Verdict', 'Who wins each catalogue metric on percentile' + (usePool ? ' within their shared position pool' : '') + ', and the three biggest gaps each way.', t.verdict);
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Ten headline metrics, percentiles.</span></div><div id="cmp-radar" style="height:420px"></div></div>' +
    '<div class="card"><div class="card-header">Head to head <span class="card-sub" id="cmp-h2h-sub">Games where both played, from the two game logs.</span></div><div id="cmp-h2h"></div></div></div>';
  h += METRIC_CARD('The whole player catalogue: value, percentile and the gap in percentile points. Bold marks the better raw figure.');
  h += '<div class="card"><div class="card-header">Shot charts <span class="card-sub">Points per shot against the league from each spot (red above, blue below), this season.</span>' + fx.toggle('cmp-shot-kind', [['hex', 'Hex'], ['zone', 'Zones']], 'hex') + '</div>' +
    '<div class="grid-2"><div><div id="cmp-shot-a" class="hf-court"></div><div id="cmp-zone-a"></div></div><div><div id="cmp-shot-b" class="hf-court"></div><div id="cmp-zone-b"></div></div></div></div>';
  h += '<div class="card"><div class="card-header">Careers <span class="card-sub">HPM by season (solid) with RAPM where play-by-play exists (diamonds).</span></div><div id="cmp-career" style="height:360px"></div><div id="cmp-career-t"></div></div>';
  document.getElementById('cmp-body').innerHTML = h;

  const pctA = A.pct || {}, axes = fx.headline(metrics, RADAR_P, 10, true).filter(m => fx.isNum(pctA[m.key]) || fx.isNum((B.pct || {})[m.key])).map(m => ({ key: m.key, label: fx.shortLabel(m.label) }));
  fx.radar('cmp-radar', axes, [{ name: names[0], pct: A.pct, colour: CA }, { name: names[1], pct: B.pct, colour: CB }]);
  wireMetricTable(t);

  // Head to head from the logs.
  const logs = careers.map((c, i) => ((c || {}).current || {}).log || []);
  const byGame = {}; logs[1].forEach(r => { byGame[r.game] = r; });
  const met = logs[0].filter(r => r.game && byGame[r.game]).map(r => [r, byGame[r.game]]);
  const sumK = (k, j) => met.reduce((s, pr) => s + (fx.isNum(pr[j][k]) ? pr[j][k] : 0), 0);
  document.getElementById('cmp-h2h').innerHTML = met.length ? '<div class="pg-h2h">' +
    ['pts', 'reb', 'ast', 'game_score'].map(k => { const va = sumK(k, 0) / met.length, vb = sumK(k, 1) / met.length; const n = va + vb || 1;
      return '<div class="pg-h2h-lab">' + ({ pts: 'Points', reb: 'Rebounds', ast: 'Assists', game_score: 'Game score' })[k] + ' a game</div><div class="pg-h2h-row"><span class="n">' + fx.esc(short[0]) + ' ' + fx.num(va, 1) + '</span><div class="pg-h2h-bar"><span style="width:' + (100 * va / n) + '%;background:' + CA + '"></span><span style="width:' + (100 * vb / n) + '%;background:' + CB + '"></span></div><span class="n r">' + fx.num(vb, 1) + ' ' + fx.esc(short[1]) + '</span></div>'; }).join('') + '</div>' +
    HW.tableHTML([{ label: 'Date' }, { label: short[0] + ' pts', align: 'right' }, { label: 'GmSc', align: 'right' }, { label: short[1] + ' pts', align: 'right' }, { label: 'GmSc', align: 'right' }],
      met.map(pr => ({ _href: fx.gameHref(L, pr[0].game), cells: [{ v: pr[0].date, html: fx.fmtDate(pr[0].date, { year: false }) }, pr[0].pts, { v: pr[0].game_score, html: fx.num(pr[0].game_score, 1) }, pr[1].pts, { v: pr[1].game_score, html: fx.num(pr[1].game_score, 1) }] })), { compact: true })
    : fx.muted('They did not meet in the games on file this season.');
  HW.sortable('cmp-h2h');

  // Shots.
  const shotsOf = i => { const c = careers[i] || {}; return (c.current && (!c.current.season || c.current.season === ss[i].season)) ? (c.current.shots || {}) : {}; };
  const drawShots = kind => [0, 1].forEach(i => {
    const sh = shotsOf(i), node = document.getElementById(i ? 'cmp-shot-b' : 'cmp-shot-a');
    document.getElementById(i ? 'cmp-zone-b' : 'cmp-zone-a').innerHTML = fx.zoneTable(sh.zones);
    if (kind === 'zone' || !fx.rowsOf(sh.grid).length) { if (sh.zones && Object.keys(sh.zones).length) fx.zoneMap(node, L, sh.zones, { title: names[i], small: true }); else node.innerHTML = fx.muted(fx.esc(names[i]) + ': no shot data.'); }
    else fx.cellChart(node, L, sh.grid, { title: names[i], colorbar: i === 1 });
  });
  drawShots('hex');
  fx.wireToggle(document.getElementById('cmp-body'), 'cmp-shot-kind', drawShots);

  // Careers.
  const tr = [];
  careers.forEach((c, i) => {
    const s = ((c || {}).seasons || []).slice().sort((x, y) => x.season - y.season).filter(r => fx.isNum(r.hpm));
    if (!s.length) return;
    tr.push({ type: 'scatter', mode: 'lines+markers', name: names[i] + ' HPM', x: s.map(r => r.season), y: s.map(r => r.hpm), line: { color: i ? CB : CA, width: 2.5 }, marker: { size: 6 }, hovertemplate: '%{x}: HPM %{y:+.1f}<extra>' + fx.esc(short[i]) + '</extra>' });
    const rp = s.filter(r => fx.isNum(r.rapm));
    if (rp.length) tr.push({ type: 'scatter', mode: 'markers', name: names[i] + ' RAPM', x: rp.map(r => r.season), y: rp.map(r => r.rapm), marker: { color: i ? CB : CA, size: 8, symbol: 'diamond-open' }, hovertemplate: '%{x}: RAPM %{y:+.1f}<extra>' + fx.esc(short[i]) + '</extra>' });
  });
  if (tr.length) fx.plot('cmp-career', tr, fx.layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 50, r: 15, t: 30, b: 40 }, xaxis: { title: 'Season', tickformat: 'd', dtick: 1 }, yaxis: { title: 'Per 100 possessions', zeroline: true, zerolinecolor: '#6e7681' } }));
  else document.getElementById('cmp-career').innerHTML = fx.muted('No career HPM for either player.');
  const tot = c => { const s = (c || {}).seasons || []; const g = s.reduce((x, r) => x + (r.gp || 0), 0); const w = k => (g ? s.reduce((x, r) => x + (fx.isNum(r[k]) ? r[k] * (r.gp || 0) : 0), 0) / g : null);
    return { seasons: s.length, gp: g, pts: w('pts'), reb: w('reb'), ast: w('ast'), hpm: w('hpm'), awards: ((c || {}).career_awards || []).length }; };
  const T2 = careers.map(tot);
  const lines = [['Seasons', 'seasons', 0], ['Games', 'gp', 0], ['Points a game', 'pts', 1], ['Rebounds a game', 'reb', 1], ['Assists a game', 'ast', 1], ['Career HPM (games-weighted)', 'hpm', 1], ['Awards', 'awards', 0]];
  document.getElementById('cmp-career-t').innerHTML = '<div class="cmp-h2h">' + lines.map(l => {
    const va = T2[0][l[1]], vb = T2[1][l[1]];
    const mx = Math.max(Math.abs(va || 0), Math.abs(vb || 0)) || 1;
    const better = fx.isNum(va) && fx.isNum(vb) && va !== vb ? (va > vb ? 'a' : 'b') : '';
    return '<div class="cmp-h2h-label">' + l[0] + '</div><div class="cmp-h2h-row"><div class="l"><span class="num">' + fx.num(va, l[2]) + '</span><div class="cmp-h2h-bar left"><div style="width:' + 100 * Math.abs(va || 0) / mx + '%"></div></div></div>' +
      '<div class="cmp-h2h-val' + (better ? ' win' : '') + '">' + (better ? fx.esc(better === 'a' ? short[0] : short[1]) : 'level') + '</div>' +
      '<div class="r"><span class="num">' + fx.num(vb, l[2]) + '</span><div class="cmp-h2h-bar right"><div style="width:' + 100 * Math.abs(vb || 0) / mx + '%"></div></div></div></div>';
  }).join('') + '</div>';
}

// ── teams ──────────────────────────────────────────────────────────────────

function renderCompareTeams(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  const a = String(params.a || ''), b = String(params.b || '');
  el.innerHTML = '<div id="cmp-pick"></div><div id="cmp-body"></div>';
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    return fx.season(L, S).then(res => {
      if (!fx.alive(el)) return;
      const teams = res[1], season = res[2];
      const T = ((teams || {}).teams) || {};
      const ids = Array.from(new Set(Object.keys(T).concat(Object.keys(((season || {}).ratings) || {})).concat(Object.keys(fx.indexL(L).teams || {})))).filter(k => !/^-/.test(k));
      [a, b].forEach(x => { if (x && ids.indexOf(x) < 0) ids.push(x); });
      document.getElementById('cmp-pick').innerHTML = pickerHTML(L, 'teams', a, b, ids.map(k => [k, fx.teamName(L, k)]).sort((p, q) => p[1].localeCompare(q[1])));
      wirePicker(el, L, 'teams', a, b);
      if (!a || !b) { document.getElementById('cmp-body').innerHTML = fx.card('', '', fx.muted('Pick two teams from the ' + fx.esc(fx.seasonLabel(L, S)) + ' season.')); return; }
      buildTeams(L, S, [a, b], T, teams, season, res[0]);
    });
  });
}

function buildTeams(L, S, ids, T, teams, season, cat) {
  const fx = FX(), C = fx.C;
  const names = ids.map(id => (T[id] || {}).name || fx.teamName(L, id));
  const abbr = ids.map(id => fx.teamAbbr(L, id));
  const metrics = (teams || {}).metrics || [];
  const R = ((season || {}).ratings) || {};
  const simAll = ((season || {}).sim || {}).teams || (season || {}).sim || {};
  const stand = {};
  Object.keys(((season || {}).standings) || {}).forEach(c => (season.standings[c] || []).forEach(r => { stand[r.team] = r; }));
  const card = i => {
    const id = ids[i], r = R[id] || {}, s = stand[id] || {}, sim = simAll[id] || {};
    return idCard(i, abbr[i], fx.teamColour(L, id), fx.teamLink(L, id, { name: names[i] }), fx.esc((fx.team(L, id) || {}).conference || ''),
      [['Record', fx.has(s.w) ? s.w + '-' + s.l : '—'], ['Net', fx.signed(r.net, 1)], ['ORtg', fx.num(r.off, 1)], ['DRtg', fx.num(r.def, 1)], ['Pace', fx.num(r.pace, 1)], ['Playoffs', fx.pct(sim.p_playoffs, 0)], ['Title', fx.pct(sim.p_title)]]);
  };
  const t = verdictAndTables(metrics, T[ids[0]] || {}, T[ids[1]] || {}, abbr[0], abbr[1], 'league percentiles, ' + fx.seasonLabel(L, S));
  let h = '<div class="cmp-ids">' + card(0) + card(1) + '</div>';
  h += fx.card('Verdict', 'Who wins each team metric on league percentile, and the three biggest gaps each way.', t.verdict);
  h += '<div class="card"><div class="card-header">Ratings <span class="card-sub">Net rating per 100 after each game, ±1 standard error shaded.</span></div><div id="cmp-paths" style="height:340px"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Headline team metrics, percentiles.</span></div><div id="cmp-radar" style="height:400px"></div></div>' +
    '<div class="card"><div class="card-header">Four factors <span class="card-sub">Both ends.</span></div><div id="cmp-ff"></div></div></div>';
  h += '<div class="card"><div class="card-header">Shot profiles <span class="card-sub">Their own shots (top) and what they allow (bottom); colour against the league, red better for the side shown.</span></div>' +
    '<div class="grid-2"><div id="cmp-sp-a" class="hf-court"></div><div id="cmp-sp-b" class="hf-court"></div><div id="cmp-sa-a" class="hf-court"></div><div id="cmp-sa-b" class="hf-court"></div></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Lineups <span class="card-sub">Each team\'s five most-used units.</span></div><div id="cmp-lu"></div></div>' +
    '<div class="card"><div class="card-header">Season series <span class="card-sub">Games between them this season.</span></div><div id="cmp-series"></div></div></div>';
  h += METRIC_CARD('The whole team catalogue: value, league percentile and the gap in percentile points.');
  document.getElementById('cmp-body').innerHTML = h;
  wireMetricTable(t);
  const axes = fx.headline(metrics, RADAR_T, 9, true).map(m => ({ key: m.key, label: fx.shortLabel(m.label) }));
  fx.radar('cmp-radar', axes, [{ name: names[0], pct: (T[ids[0]] || {}).pct, colour: CA }, { name: names[1], pct: (T[ids[1]] || {}).pct, colour: CB }]);
  const paths = ((season || {}).rating_paths) || {};
  const tr = [];
  ids.forEach((id, i) => { const p = paths[id] || []; if (p.length) tr.push.apply(tr, fx.band(p.map(x => ({ x: x.date, y: x.net, se: x.se, text: fx.fmtDate(x.date, { year: false }) })), i ? CB : CA, abbr[i], { hover: abbr[i] + ' %{text}: %{y:+.1f} ± %{customdata:.1f}<extra></extra>' })); });
  if (tr.length) fx.plot('cmp-paths', tr, fx.layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 45, r: 10, t: 30, b: 40 }, yaxis: { title: 'Net per 100', zeroline: true, zerolinecolor: '#6e7681' } }));
  else document.getElementById('cmp-paths').innerHTML = fx.muted('No rating paths yet.');
  const ff0 = metrics.filter(m => /four/i.test(m.group || ''));
  const ff = ff0.length ? ff0 : metrics.filter(m => /(^|_)(efg|tov|orb|drb|ftr|ft_rate)/.test(m.key));
  document.getElementById('cmp-ff').innerHTML = ff.length ? HW.tableHTML([{ label: 'Factor' }, { label: abbr[0], align: 'right' }, { label: 'Pct', align: 'center' }, { label: 'Pct', align: 'center' }, { label: abbr[1], align: 'right' }],
    ff.map(m => { const va = ((T[ids[0]] || {}).values || {})[m.key], vb = ((T[ids[1]] || {}).values || {})[m.key]; const better = fx.isNum(va) && fx.isNum(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 0 : 1) : -1;
      return [{ v: m.label, html: fx.glossLink(m.key, fx.esc(m.label)) }, { v: va, html: (better === 0 ? '<strong>' : '') + fx.fmt(m, va) + (better === 0 ? '</strong>' : '') }, { v: 0, html: fx.pill(((T[ids[0]] || {}).pct || {})[m.key]) }, { v: 0, html: fx.pill(((T[ids[1]] || {}).pct || {})[m.key]) }, { v: vb, html: (better === 1 ? '<strong>' : '') + fx.fmt(m, vb) + (better === 1 ? '</strong>' : '') }]; }), { compact: true })
    : fx.muted('No four-factor metrics.');
  const swap = z => { const o = {}; Object.keys(z || {}).forEach(k => { const x = z[k] || {}; o[k] = Object.assign({}, x, { pps: fx.isNum(x.league_pps) && fx.isNum(x.pps) ? 2 * x.league_pps - x.pps : x.pps }); }); return o; };
  ids.forEach((id, i) => { const sp = (T[id] || {}).shot_profile || {}; fx.zoneMap(i ? 'cmp-sp-b' : 'cmp-sp-a', L, sp['for'], { title: abbr[i] + ' shots', small: true }); fx.zoneMap(i ? 'cmp-sa-b' : 'cmp-sa-a', L, swap(sp.against), { title: abbr[i] + ' allowed', small: true }); });
  const P = ((cat || {}).players) || {};
  const nm = id => fx.surname((P[id] || {}).name || fx.playerName(L, id));
  document.getElementById('cmp-lu').innerHTML = ids.map((id, i) => { const lus = ((T[id] || {}).lineups || []).slice().sort((x, y) => (y.poss || 0) - (x.poss || 0)).slice(0, 5);
    return '<div class="cmp-group-head"><span class="cmp-pill-' + (i ? 'b' : 'a') + '"></span>' + fx.esc(names[i]) + '</div>' + (lus.length ? HW.tableHTML([{ label: 'Lineup' }, { label: 'Poss', align: 'right' }, { label: 'Net', align: 'right' }, { label: 'Shrunk', align: 'right' }],
      lus.map(u => [{ v: '', html: (u.players || []).map(x => fx.playerLink(L, x, nm(x))).join(' · ') }, { v: u.poss, html: fx.num(u.poss, 0) }, { v: u.net, html: fx.signed(u.net, 1) }, { v: u.shrunk_net, html: fx.signed(u.shrunk_net, 1) }]), { compact: true }) : fx.muted('No lineups.')); }).join('');
  const games = (((T[ids[0]] || {}).log) || []).filter(g => String(g.opp) === String(ids[1])).sort((x, y) => String(x.date).localeCompare(String(y.date)));
  const wA = games.filter(g => String(g.res).charAt(0) === 'W').length;
  document.getElementById('cmp-series').innerHTML = games.length ? '<div class="pg-h2h"><div class="pg-h2h-row"><span class="n">' + fx.esc(abbr[0]) + ' ' + wA + '</span><div class="pg-h2h-bar"><span style="width:' + 100 * wA / games.length + '%;background:' + CA + '"></span><span style="width:' + 100 * (games.length - wA) / games.length + '%;background:' + CB + '"></span></div><span class="n r">' + (games.length - wA) + ' ' + fx.esc(abbr[1]) + '</span></div></div>' +
    HW.tableHTML([{ label: 'Date' }, { label: 'Venue' }, { label: 'Score', align: 'right' }, { label: 'Winner' }],
      games.map(g => ({ _href: g.game ? fx.gameHref(L, g.game) : undefined, cells: [{ v: g.date, html: fx.fmtDate(g.date, { year: false }) }, g.home ? fx.esc(abbr[0]) + ' home' : fx.esc(abbr[1]) + ' home', (g.pts || 0) + '-' + (g.opp_pts || 0), { v: g.res, html: String(g.res).charAt(0) === 'W' ? '<span style="color:' + CA + '">' + fx.esc(abbr[0]) + '</span>' : '<span style="color:' + CB + '">' + fx.esc(abbr[1]) + '</span>' }] })), { compact: true })
    : fx.muted('They have not met this season.');
}

function renderCompare(el, params, state) {
  if (params.kind === 'teams') return renderCompareTeams(el, params, state);
  return renderComparePlayers(el, params, state);
}

HW.route('compare-players', renderComparePlayers);
HW.route('compare-teams', renderCompareTeams);
HW.route('compare', renderCompare);
})(window.HW);
