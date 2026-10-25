/* The Quant Rink — the team page (#/team/<abbr>).
 *
 * Record, rating and odds tiles; playoff paths (the odds of each stage, the points and seed
 * distributions, magic numbers); unit ratings over the season; special teams; shot maps for and against
 * against the league; line combinations and defence pairs; deployment (ice time by strength and zone
 * starts for every regular); the schedule against the model (the market stays on game pages and the Model page);
 * the roster's value.
 *
 * Data: data/<S>/teams.json, season.json, schedule.json, lines.json, skaters.json, goalies.json. Uses RK.fk
 * and RK.fk.T (teams.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const T = () => RK.fk.T;

function render(el, params, state) {
  const k = K();
  const abbr = String(params.id || (params.rest || [])[0] || '').toUpperCase();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'teams.json'), k.loadY(S, 'season.json'), k.loadY(S, 'schedule.json'), k.loadY(S, 'lines.json'), k.loadY(S, 'skaters.json'), k.loadY(S, 'goalies.json'), k.loadNames()])
      .then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, t = T();
    const cat = t.teamsOf(res[0]), rows = t.seasonRows(res[1]);
    const TM = (cat && cat.teams) || {};
    const tm = TM[abbr] || null, row = rows[abbr] || null;
    if (!tm && !row && !k.NHL[abbr]) { el.innerHTML = k.card('Team', '', k.muted('There is no team <code>' + k.esc(abbr) + '</code>. <a href="#/teams">All teams →</a>')); return; }
    const x = tm || {}, r = row || {};
    const info = k.team(abbr);
    const rc = t.recordOf(x, r), R = t.ratingsOf(x, r), od = t.oddsOf(r, r.odds, x.sim, x.odds);
    const colour = k.teamColour(abbr);
    const sub = [info.division ? '<span class="chip">' + k.esc(info.division) + '</span>' : '', info.conference ? '<span class="muted-inline">' + k.esc(info.conference) + '</span>' : '', k.isNum(rc.w) ? '<strong>' + t.recText(rc) + '</strong>' : '',
      k.isNum(r.div_rank) ? '<span>' + k.ordinal(r.div_rank) + ' in the division</span>' : '', k.isNum(r.conf_rank) ? '<span>' + k.ordinal(r.conf_rank) + ' in the conference</span>' : '',
      x.coach || r.coach ? '<span>Head coach ' + k.esc(x.coach || r.coach) + '</span>' : '', '<span class="chip">' + k.esc(k.sLabel(S)) + '</span>'].filter(Boolean).join(' ');
    const links = ['<a href="' + k.compareHref('t:' + abbr, '') + k.sq(S) + '">Compare →</a>', '<a href="' + (k.has('standingsHref') ? RK.standingsHref(S) : '#/standings') + '">Standings →</a>', '<a href="' + k.withQ('#/lines', S, { team: abbr }) + '">Lines →</a>', '<a href="' + k.withQ('#/teams', S) + '">All teams →</a>'].join('');
    let h = k.head(k.esc(k.teamName(abbr)), sub, links, k.esc(abbr), colour);
    if (!tm && !row) h += '<div class="card"><div class="pad muted-inline">' + k.notBuilt('The ' + k.sLabel(S) + ' page for ' + k.teamName(abbr), res[0]) + '</div></div>';
    const pp = k.first((x.sim || {}).exp_pts, (r.odds || {}).exp_pts, r.mean_pts, (r.odds || {}).mean_pts, (x.sim || {}).mean_pts, r.proj_pts);
    h += k.tiles([
      k.tile('Record', t.recText(rc), k.isNum(rc.pts) ? k.int(rc.pts) + ' points' + (k.isNum(rc.ppct) ? ', ' + k.fmtV(rc.ppct, '3').replace(/^0/, '') + ' P%' : '') : ''),
      k.tile('Goal differential', k.isNum(rc.diff) ? k.signed(rc.diff, 0) : '—', k.isNum(rc.gf) ? rc.gf + ' for, ' + rc.ga + ' against' : ''),
      k.tile('Rating', k.isNum(R.overall) ? k.signed(R.overall, 2) : '—', 'goal differential per game v average' + (k.isNum(T().unitPct(x, r).overall) ? ' ' + k.pill(T().unitPct(x, r).overall) : '')),
      k.tile('5v5 xGF%', k.isNum(k.first(rc.xgf_pct, (x.units || {}).xgf_pct5)) ? k.pct(k.first(rc.xgf_pct, (x.units || {}).xgf_pct5), 1) : '—', 'share of 5-on-5 expected goals'),
      k.tile('Playoffs', k.isNum(od.p_playoffs) ? k.pct(od.p_playoffs, 1) : '—', k.isNum(pp) ? k.num(pp, 1) + ' points projected' : 'season simulation'),
      k.tile('Stanley Cup', k.isNum(od.p_cup) ? k.pct(od.p_cup, 1) : '—', k.isNum(od.p_conf) ? 'reach the Final ' + k.pct(od.p_conf, 1) : '')
    ]);
    const curS = k.curSeason();
    h += '<div class="card"><div class="card-header">Strengths and needs <span class="card-sub">' + (Number(S) === Number(curS) ? 'Each position and unit graded against the league on projected value (rest-of-season GAR per 60 × projected ice time, in GAR over a full season); the three strongest and weakest.' : 'Built for the current season (' + k.esc(k.sLabel(curS)) + ') only.') + '</span></div><div id="tp-needs">' + (Number(S) === Number(curS) ? k.muted('Loading…') : '<div class="pad"><a href="' + k.teamHref(abbr) + '">' + k.esc(k.teamName(abbr)) + ' in ' + k.esc(k.sLabel(curS)) + ' →</a></div>') + '</div></div>';
    if (Number(S) === Number(curS) && RK.moves) h += '<div class="card"><div class="card-header">Ledger <span class="card-sub">The club\'s transactions of the last twelve months and every trade graded: value received at the time (our multi-season valuation as of the trade date), realised since and the current view, in WAR. On-field model value, not contracts or the cap.</span></div><div id="tp-ledger">' + k.muted('Loading…') + '</div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Playoff paths <span class="card-sub">Season simulation: the share of runs in which the team reaches each stage, its final points and where it is seeded.' + magicText(r, x) + '</span></div><div id="tp-odds"></div><div id="tp-pts" style="height:210px"></div><div id="tp-seed" style="height:210px"></div></div>' +
      '<div class="card"><div class="card-header">Special teams <span class="card-sub">Power play and penalty kill: results and the chances behind them, against the league.</span></div><div id="tp-st"></div></div></div>';
    h += '<div class="card"><div class="card-header">Form <span class="card-sub" id="tp-roll-sub">Rolling ten-game 5-on-5 xGF%, all-situations GF% and 5-on-5 CF%: process against results.</span></div><div id="tp-roll" class="gf-chart"></div></div>';
    h += '<div class="card"><div class="card-header">Unit ratings over the season <span class="card-sub">The team-strength model\'s rating and 5-on-5 units after every game day (time-decayed, with last season\'s regressed prior early on).</span><span class="gq-ctl" id="tp-hist-ctl"></span></div><div id="tp-hist" class="gf-chart"></div></div>';
    h += '<div class="card"><div class="card-header">Shot maps <span class="card-sub" id="tp-shot-sub">Unblocked shot rates per 60 against the league (red: more than average from there). For: the team attacking right; against: opponents attacking its net.</span><span class="gq-ctl"><select id="tp-shot-str"></select></span></div><div class="grid-2 gf-shots"><div id="tp-shot-f" class="gf-rink"></div><div id="tp-shot-a" class="gf-rink"></div></div><div class="pg-note gq-note" id="tp-shot-n"></div></div>';
    if (cat && cat.metrics && cat.metrics.length && x.pct) h += '<div class="card"><div class="card-header">Team profile <span class="card-sub">Percentiles among the 32 teams on the team catalogue (100 = best).</span></div><div class="gq-pad">' + k.sliders(cat.metrics.filter(m => k.isNum((x.pct || {})[m.key])), x.values || {}, x.pct || {}, {}) + '</div></div>';
    h += '<div class="card"><div class="card-header">Line combinations <span class="card-sub">Forward lines and defence pairs by 5-on-5 time together, with their expected-goals share (shrunk towards the team\'s by the time together).</span></div><div class="grid-2"><div id="tp-fl"></div><div id="tp-dp"></div></div></div>';
    h += '<div class="card"><div class="card-header">Deployment <span class="card-sub">Ice time per game by strength and offensive-zone start share for every regular.</span></div><div class="grid-2"><div id="tp-dep"></div><div id="tp-dep-c" style="height:420px"></div></div></div>';
    h += '<div class="card"><div class="card-header">Schedule against the model <span class="card-sub">Every game with our pre-game win probability; the chart is points minus the model\'s expected points.</span></div><div id="tp-sched-c" style="height:220px"></div><div id="tp-sched"></div></div>';
    h += '<div class="card"><div class="card-header">Roster value <span class="card-sub">Rink value this season (goals above replacement) for the team\'s skaters and goalies in the catalogues. Click a player for the player page.</span></div><div class="grid-2"><div id="tp-roster"></div><div id="tp-roster-c" style="height:380px"></div></div></div>';
    el.innerHTML = h;
    k.setMeta(k.esc(k.teamName(abbr)));
    if (Number(S) === Number(curS)) k.loadY(S, 'needs/' + abbr + '.json').then(nd => { if (k.alive(el)) drawNeeds(abbr, S, nd); });
    if (Number(S) === Number(curS) && RK.moves) RK.moves.ledger(document.getElementById('tp-ledger'), abbr);
    playoffPaths(x, r, od, colour);
    specialTeams(x, r);
    unitHistory(x, r, colour);
    shotMaps(x, colour, (cat && cat.raw) || {});
    lineCombos(abbr, x, res[3], S);
    deploymentT(abbr, x, res[4], S, colour);
    schedule(abbr, x, res[2], S, colour);
    rolling(x, colour);
    roster(abbr, res[4], res[5], S, colour);
  });
}

// ── strengths and needs (data/<S>/needs/<abbr>.json, analytics/value.py needs_payloads) ──────────────────

const POS_ONE = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G' };
function gradePill(g) { return g ? '<span class="nd-grade nd-' + String(g).toLowerCase() + '">' + K().esc(g) + '</span>' : '—'; }

function drawNeeds(abbr, S, nd) {
  const k = K();
  const box = document.getElementById('tp-needs');
  if (!box) return;
  if (!k.ok(nd) || !nd.grades) { box.innerHTML = '<div class="pad">' + k.notBuilt('Strengths and needs', nd) + '</div>'; return; }
  const full = nd.games_left !== undefined && nd.games_left !== null && nd.games_left === nd.games;
  let h = '<div class="grid-2 nd-top"><div>' + k.table([{ label: 'Area' }, { label: 'Grade', align: 'center' }, { label: 'GAR', align: 'right', title: 'Projected GAR over a full season' }, { label: 'Rank', align: 'right' }, { label: 'Pct', align: 'center' }],
    nd.grades.map(g => [{ v: g.label, html: k.esc(g.label) }, { v: g.pct, html: gradePill(g.grade) }, { v: g.value, html: k.num(g.value, 1) }, { v: g.rank, html: k.ordinal(g.rank) + ' of ' + g.n }, { v: g.pct, html: k.pill(g.pct) }]), { compact: true }) + '</div><div class="nd-list">' +
    '<div class="nd-h">Strengths</div>' + (nd.strengths || []).map(s => '<div class="nd-item">' + gradePill(s.grade) + ' <strong>' + k.esc(s.label) + (s.relative ? ' <span class="muted-inline">(relative: below the league median)</span>' : '') + '</strong> <span class="muted-inline">' + k.esc(s.evidence) + '</span></div>').join('') +
    '<div class="nd-h">Weaknesses</div>' + (nd.weaknesses || []).map(s => '<div class="nd-item">' + gradePill(s.grade) + ' <strong>' + k.esc(s.label) + (s.relative ? ' <span class="muted-inline">(relative: above the league median)</span>' : '') + '</strong> <span class="muted-inline">' + k.esc(s.evidence) + '</span></div>').join('') + '</div></div>';
  h += '<div class="pg-note gq-note">Grades are projected value by position and unit against the other clubs.</div>';
  box.innerHTML = h;
  k.sortable(box);
}

function magicText(r, x) {
  const k = K(), L = { division: 'the division', playoffs: 'a playoff place', presidents: 'the Presidents\' Trophy', wildcard: 'a wild card', div: 'the division' };
  const sim = Object.assign({}, r.odds || {}, x.sim || {});
  const parts = [];
  const m = r.magic !== undefined ? r.magic : sim.magic;
  const cl = r.clinched !== undefined ? r.clinched : sim.clinched, el = r.eliminated !== undefined ? r.eliminated : sim.eliminated, tr = sim.tragic;
  const done = o => (o && typeof o === 'object' ? o : {});
  if (k.isNum(m)) parts.push('Magic number ' + m + '.');
  else if (m && typeof m === 'object') { const xs = Object.keys(m).filter(z => k.isNum(m[z]) && !done(cl)[z] && !done(el)[z]).map(z => k.esc(L[z] || z) + ' ' + m[z]); if (xs.length) parts.push('Magic numbers (points): ' + xs.join(', ') + '.'); }
  if (tr && typeof tr === 'object') { const xs = Object.keys(tr).filter(z => k.isNum(tr[z]) && !done(cl)[z] && !done(el)[z] && z === 'playoffs').map(z => k.esc(L[z] || z) + ' ' + tr[z]); if (xs.length) parts.push('Elimination number: ' + xs.join(', ') + '.'); }
  const flags = (o, word) => { if (o === true) return word + '.'; if (o && typeof o === 'object') { const xs = Object.keys(o).filter(z => o[z] === true).map(z => L[z] || z); return xs.length ? word + ' ' + xs.join(', ') + '.' : ''; } return typeof o === 'string' && o ? word + ' ' + k.esc(o) + '.' : ''; };
  parts.push(flags(cl, 'Clinched'), flags(el, 'Eliminated from'));
  const t = parts.filter(Boolean).join(' ');
  return t ? ' ' + t : '';
}

function pillOf(x, key) { const k = K(), pc = ((x || {}).pct || {})[key]; return k.isNum(pc) ? ' ' + k.pill(pc) : ''; }
const distOf = d => (Array.isArray(d) ? (d.length && Array.isArray(d[0]) ? d.map(z => [z[0], z[1]]) : d.map((p, i) => [i, p])) : (d && typeof d === 'object' ? Object.keys(d).map(s => [s, d[s]]) : []));

function playoffPaths(x, r, od, colour) {
  const k = K(), t = T();
  const host = k.$('tp-odds');
  if (!host) return;
  const sim = Object.assign({}, r.odds || {}, x.sim || {});
  const list = t.ODDS.filter(o => k.isNum(od[o[0]]));
  const reach = sim.p_reach && typeof sim.p_reach === 'object' ? Object.keys(sim.p_reach).filter(z => k.isNum(sim.p_reach[z])) : [];
  const RN = { r1: 'First round', r2: 'Second round', r3: 'Conference final', r4: 'Stanley Cup Final', R1: 'First round', R2: 'Second round', R3: 'Conference final', R4: 'Stanley Cup Final', cf: 'Conference final', conf_final: 'Conference final', scf: 'Stanley Cup Final', final: 'Stanley Cup Final', cup: 'Win the Cup' };
  const bar = (lab, p) => '<div class="gq-odd"><span>' + k.esc(lab) + '</span><div class="gq-odd-bar"><i style="width:' + (100 * p).toFixed(1) + '%;background:' + colour + '"></i></div><strong>' + k.pct(p, 1) + '</strong></div>';
  host.innerHTML = list.length ? '<div class="gq-odds">' + list.map(o => bar(o[1], od[o[0]])).join('') +
    (reach.length ? '<div class="gq-sub-head">Reach each round</div>' + reach.map(z => bar(RN[z] || (RK.roundName ? RK.roundName(z) : z), sim.p_reach[z])).join('') : '') +
    (k.isNum(sim.p_wildcard) ? '<div class="pg-note gq-note">In by a wild card ' + k.pct(sim.p_wildcard, 1) + ', top three in the division ' + k.pct(sim.p_top3, 1) + '.</div>' : '') + '</div>'
    : k.muted('Simulation odds are not available yet.');
  const pd = sim.points_dist || sim.pts_dist || r.points_dist;
  const pv = distOf(pd).map(z => [Number(z[0]), z[1]]).filter(z => k.isNum(z[0]) && k.isNum(z[1]));
  const pNode = k.$('tp-pts');
  if (pv.length) {
    const band = k.isNum(sim.pts_p05) ? ' (90% range ' + sim.pts_p05 + '–' + sim.pts_p95 + ')' : '';
    k.plot(pNode, [{ type: 'bar', x: pv.map(z => z[0]), y: pv.map(z => z[1]), marker: { color: k.alpha(colour, 0.75) }, hovertemplate: '%{x} points: %{y:.1%}<extra></extra>' }],
      k.layout({ margin: { l: 44, r: 10, t: 24, b: 30 }, title: { text: 'Final points' + band, font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { tickformat: Math.max.apply(null, pv.map(z => z[1])) < 0.1 ? '.1%' : '.0%', title: 'Probability' }, xaxis: { title: 'Final points' } }));
  } else pNode.style.display = 'none';
  const sNode = k.$('tp-seed');
  const dr = sim.div_rank_dist;
  const sd = sim.seed_dist || sim.seeds || r.seed_dist;
  if (Array.isArray(dr) && dr.some(k.isNum)) {
    k.plot(sNode, [{ type: 'bar', x: dr.map((_, i) => k.ordinal(i + 1)), y: dr, marker: { color: colour }, hovertemplate: '%{x} in the division: %{y:.1%}<extra></extra>' }],
      k.layout({ margin: { l: 44, r: 10, t: 24, b: 30 }, title: { text: 'Finish in the division', font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { tickformat: '.0%', title: 'Probability' }, xaxis: { type: 'category', title: 'Division finish' } }));
  } else if (distOf(sd).length) {
    const sv = distOf(sd).filter(z => k.isNum(z[1]));
    k.plot(sNode, [{ type: 'bar', x: sv.map(z => (/^(0|out|none|miss)$/i.test(String(z[0])) ? 'Out' : String(z[0]).toUpperCase())), y: sv.map(z => z[1]), marker: { color: colour }, hovertemplate: '%{x}: %{y:.1%}<extra></extra>' }],
      k.layout({ margin: { l: 44, r: 10, t: 24, b: 30 }, title: { text: 'Playoff seed', font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { tickformat: '.0%', title: 'Probability' }, xaxis: { type: 'category', title: 'Playoff seed' } }));
  } else sNode.style.display = 'none';
}

function specialTeams(x, r) {
  const k = K(), host = k.$('tp-st');
  if (!host) return;
  const u = Object.assign({}, r, x.values || {}, x.units || {}, x.special_teams || {});
  const P = (x.units || {}).pct || {};
  const R = T().ratingsOf(x, r);
  const tile = (val, lab, fmt, sub, pk) => (k.isNum(val) ? k.tile(lab, k.fmtV(val, fmt), (k.isNum(P[pk]) ? k.pill(P[pk]) + ' ' : '') + k.esc(sub || '')) : '');
  const gp = k.first(u.gp, (x.record || {}).gp);
  const pp = [tile(k.first(u.pp_pct), 'Power play %', 'pct', 'goals per opportunity'), tile(R.pp, 'PP xGF / 60', '2', (x.units || {}).source === 'team_strength' ? 'modelled, above the league' : 'chances created per 60', 'pp'),
    tile(k.first(u.pp_gf), 'PP goals', 'int', k.isNum(gp) && gp ? k.num(u.pp_gf / gp, 2) + ' a game' : ''), tile(k.first(u.pp_toi_g), 'PP minutes / game', '1', 'time on the power play')].filter(Boolean);
  const pk = [tile(k.first(u.pk_pct), 'Penalty kill %', 'pct', 'kills per time short-handed'), tile(R.pk, 'PK xGA / 60', '2', 'chances allowed per 60 (lower is better)', 'pk'),
    tile(k.first(u.pk_ga), 'PK goals against', 'int', k.isNum(gp) && gp ? k.num(u.pk_ga / gp, 2) + ' a game' : ''), tile(k.first(u.pk_toi_g), 'PK minutes / game', '1', 'time short-handed (lower is better)')].filter(Boolean);
  let h = '';
  if (pp.length) h += '<div class="gq-sub-head">Power play</div>' + k.tiles(pp);
  if (pk.length) h += '<div class="gq-sub-head">Penalty kill</div>' + k.tiles(pk);
  host.innerHTML = h ? h + '<div class="pg-note gq-note">Special-teams goals swing on a handful of bounces; the expected-goals rates are the steadier read. Pills are percentiles among the 32 teams (100 = best).</div>' : k.muted('Special-teams figures are not available yet.');
}

function unitHistory(x, r, colour) {
  const k = K(), t = T(), node = k.$('tp-hist'), ctl = k.$('tp-hist-ctl');
  if (!node) return;
  const raw = x.history || x.ratings_history || (x.ratings || {}).history || r.history || (r.ratings || {}).history;
  const rows = t.historyOf(raw, x.history_cols || r.history_cols);
  if (rows.length < 2) { k.empty(node, 'Rating history starts after a few games.'); return; }
  const sets = { units: ['off', 'def', 'pp', 'pk', 'goalie'], overall: ['overall'], ev: ['off', 'def'], st: ['pp', 'pk'] };
  const avail = Object.keys(sets).filter(s => sets[s].some(u => rows.some(z => k.isNum(z[u]))));
  if (!avail.length) { k.empty(node, 'No unit history.'); return; }
  if (ctl) ctl.innerHTML = k.toggle('tp-hist-t', avail.map(s => [s, { units: 'All units', overall: 'Overall', ev: '5 on 5', st: 'Special teams' }[s]]), avail[0]);
  const COL = { overall: colour, off: colour, def: '#58a6ff', pp: '#f97316', pk: '#bc8cff', goalie: '#3fb950' };
  const draw = s => {
    const us = sets[s].filter(u => rows.some(z => k.isNum(z[u])));
    k.plot(node, us.map(u => ({ type: 'scatter', mode: 'lines', name: (t.UNITS.find(z => z[0] === u) || [u, u])[1], x: rows.map(z => z.x), y: rows.map(z => z[u]), line: { color: COL[u], width: 2, dash: u === 'def' || u === 'pk' ? 'dot' : 'solid' }, hovertemplate: '%{x}: %{y:+.2f}<extra>%{fullData.name}</extra>' })),
      k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 36 }, xaxis: { title: 'Date' }, yaxis: { title: 'Goals per game v average', zeroline: true, zerolinecolor: '#6e7681' } }, k.legendTop())));
  };
  draw(avail[0]);
  k.wireToggle(document, 'tp-hist-t', draw);
}

function shotMaps(x, colour, raw) {
  const k = K(), f = k.$('tp-shot-f'), a = k.$('tp-shot-a'), sel = k.$('tp-shot-str');
  if (!f) return;
  const SM = x.shot_map || x.shots || x.shot_maps || {};
  const spec = raw.grid || SM.grid || null;
  const F = SM.for || SM.f, A = SM.against || SM.a;
  if (!F && !A) { f.parentNode.innerHTML = k.muted('Team shot maps are not available yet (they need the season\'s play-by-play).'); return; }
  let cur = 'att';
  if (sel) { sel.innerHTML = '<option value="att">Unblocked attempts</option><option value="xg">Expected goals</option>'; sel.style.display = ''; }
  const one = (node, B, title) => {
    if (!B) { k.empty(node, 'No grid.'); return; }
    const rel = B[cur + '60_rel'], abs = B[cur + '60'];
    const G = spec ? K().flatGrid(spec, rel || abs || B[cur]) : null;
    if (G) { G.v = K().smooth(G.v); k.shotHeatmap(node, G, rel ? 'diff' : 'raw', { rel: !!rel, title: title, label: rel ? 'per 60 v lg' : 'per 60', fmt: cur === 'xg' ? '3' : '2' }); }
    else if (Array.isArray(B.zones) || (B.zones && typeof B.zones === 'object')) k.shotHeatmap(node, { zones: Object.keys(B.zones).map(z => ({ zone: K().titleCase(z), v: (B.zones[z] || {})[cur === 'xg' ? 'xg' : 'att'] })) }, 'raw', { title: title });
    else k.empty(node, 'No grid.');
  };
  const draw = () => {
    one(f, F, (cur === 'xg' ? 'Expected goals' : 'Attempts') + ' for per 60, v the league');
    one(a, A, (cur === 'xg' ? 'Expected goals' : 'Attempts') + ' against per 60, v the league');
  };
  draw();
  if (sel) sel.onchange = e => { cur = e.target.value; draw(); };
  k.set('tp-shot-n', '5 on 5, regular season' + (k.isNum(SM.toi5) ? ', ' + k.int(SM.toi5) + ' minutes' : '') + ': the team\'s rate per 60 from each 5 ft area of the offensive zone minus the league\'s, lightly smoothed. Red means more than the league from there: good on the left (chances created), bad on the right (chances allowed, drawn with the team\'s own net on the right). Coordinates before 2020–21 are hand-recorded and arena-adjusted.');
}

/* Lines and pairs: teams.json lines {forwards|f|lines: [...], pairs|d|defence: [...]} or lines.json filtered to the team. */
function lineRows(raw) {
  const k = K();
  return k.listOf(raw).map(r => {
    let ids = r.players || r.pids || r.ids || r.skaters || r.members || null;
    if (typeof ids === 'string') ids = ids.split(/[-_|, ]+/);
    if (!Array.isArray(ids)) ids = ['p1', 'p2', 'p3', 'f1', 'f2', 'f3', 'd1', 'd2'].map(c => r[c]).filter(v => v !== undefined && v !== null && v !== '');
    ids = ids.map(x => (x && typeof x === 'object' ? String(x.pid || x.id) : String(x)));
    const names = r.names || (Array.isArray(r.players) && r.players.length && typeof r.players[0] === 'object' ? r.players.map(x => x.name || null) : null);
    return { ids: ids, names: names, team: r.team, kind: r.kind || r.type || '', gp: k.first(r.gp, r.games), toi: k.first(r.toi, r.toi_5v5, r.minutes), xgf: k.first(r.xgf_pct_shrunk, r.xgf_pct_adj, r.shrunk, r.xgf_shrunk), raw: k.first(r.xgf_pct, r.xgf_pct_raw), gf: k.first(r.gf), ga: k.first(r.ga), cf: k.first(r.cf_pct), xgf60: k.first(r.xgf60), xga60: k.first(r.xga60) };
  }).filter(r => r.ids.length);
}
(RK.fk = RK.fk || {}).lineRows = lineRows;
function lineTable(rows, S, opts) {
  const k = K(), o = opts || {};
  const names = r => r.ids.map((id, i) => k.playerLink(id, r.names ? r.names[i] : null, S)).join(' – ');
  return k.table([{ label: o.label || 'Line' }].concat(o.team ? [{ label: 'Team' }] : []).concat([{ label: 'TOI', align: 'right', title: '5-on-5 minutes together' }, { label: 'xGF% (shrunk)', align: 'right', title: 'Expected goals share together, shrunk towards the team\'s share by the time together' }, { label: 'xGF% raw', align: 'right' }, { label: 'GF–GA', align: 'right' }]),
    rows.map(r => [{ v: r.ids.map(id => k.name(id)).join(' '), html: names(r) }].concat(o.team ? [{ v: r.team || '', html: k.teamChip(r.team, S) }] : [])
      .concat([{ v: r.toi, html: k.int(r.toi) }, { v: r.xgf, html: k.isNum(r.xgf) ? '<strong class="' + (r.xgf > 0.5 ? 'gq-ok' : r.xgf < 0.5 ? 'gq-no' : '') + '">' + k.pct(r.xgf, 1) + '</strong>' : '—' }, { v: r.raw, html: k.isNum(r.raw) ? k.pct(r.raw, 1) : '—' }, { v: k.isNum(r.gf) ? r.gf - r.ga : null, html: k.isNum(r.gf) ? r.gf + '–' + r.ga : '—' }])), { compact: true });
}
(RK.fk = RK.fk || {}).lineTable = lineTable;
function lineCombos(abbr, x, lj, S) {
  const k = K();
  const L = x.lines || x.combos || {};
  let F = [], D = [];
  if (lj && lj.ok !== false) {
    const M = lj.model && lj.model.ok !== false ? lj.model : null;   // the lines model carries the shrunk shares
    F = lineRows((M && M.forwards) || lj.forwards || lj.lines).filter(r => r.team === abbr);
    D = lineRows((M && M.pairs) || lj.pairs || lj.d).filter(r => r.team === abbr);
  }
  if (!F.length) F = lineRows(L.forwards || L.f || L.lines);
  if (!D.length) D = lineRows(L.pairs || L.d || L.defence);
  F.sort((a, b) => (b.toi || 0) - (a.toi || 0)); D.sort((a, b) => (b.toi || 0) - (a.toi || 0));
  k.set('tp-fl', '<div class="gq-sub-head">Forward lines</div>' + (F.length ? lineTable(F.slice(0, 10), S, { label: 'Line' }) : k.muted('No forward lines yet (shift data from 2010–11).')));
  k.set('tp-dp', '<div class="gq-sub-head">Defence pairs</div>' + (D.length ? lineTable(D.slice(0, 8), S, { label: 'Pair' }) : k.muted('No defence pairs yet.')));
  k.sortable(k.$('tp-fl')); k.sortable(k.$('tp-dp'));
}

function deploymentT(abbr, x, skRaw, S, colour) {
  const k = K(), host = k.$('tp-dep'), node = k.$('tp-dep-c');
  if (!host) return;
  let rows = k.listOf((x.deployment || {}).players || x.deployment, 'pid').map(r => Object.assign({}, r, { pid: String(r.pid || r.id || '') }));
  if (!rows.length) {
    const cat = k.catOf(skRaw);
    if (cat) rows = Object.keys(cat.players).filter(id => cat.players[id].team === abbr).map(id => Object.assign({ pid: id, name: cat.players[id].name, pos: cat.players[id].pos, gp: k.gpOf(cat.players[id]) }, cat.players[id].values || {}));
  }
  const ev = r => k.first(r.toi5_gp, r.toi_5v5_gp, r.toi_5v5, r.toi_ev_gp, r.toi_ev), pp = r => k.first(r.toi_pp_gp, r.toi_pp), pk = r => k.first(r.toi_sh_gp, r.toi_pk_gp, r.toi_pk), oz = r => k.first(r.ozs_pct, r.oz_start_pct, r.oz_pct);
  rows = rows.filter(r => r.pid && (k.isNum(ev(r)) || k.isNum(pp(r)) || k.isNum(pk(r))));
  if (!rows.length) { host.innerHTML = k.muted('Deployment is not available yet.'); node.style.display = 'none'; return; }
  const perGame = v => (k.isNum(v) && v > 40 ? null : v);
  rows.sort((a, b) => (k.sum([ev(b), pp(b), pk(b)]) - k.sum([ev(a), pp(a), pk(a)])));
  host.innerHTML = k.table([{ label: 'Player' }, { label: 'Pos' }, { label: '5v5', align: 'right', title: 'Minutes per game' }, { label: 'PP', align: 'right' }, { label: 'PK', align: 'right' }, { label: 'OZ start %', align: 'right' }],
    rows.slice(0, 24).map(r => ({ _href: k.playerHref(r.pid, S), cells: [{ v: r.name || k.name(r.pid), html: k.playerLink(r.pid, r.name, S) }, { v: r.pos || '', html: k.esc(k.posLabel(r.pos || (k.NAMES[r.pid] || {}).pos)) },
      { v: ev(r), html: k.isNum(perGame(ev(r))) ? k.mmss(ev(r)) : k.int(ev(r)) }, { v: pp(r), html: k.isNum(perGame(pp(r))) ? k.mmss(pp(r)) : k.int(pp(r)) }, { v: pk(r), html: k.isNum(perGame(pk(r))) ? k.mmss(pk(r)) : k.int(pk(r)) }, { v: oz(r), html: k.isNum(oz(r)) ? k.pct(oz(r) > 1.5 ? oz(r) / 100 : oz(r), 0) : '—' }] })), { compact: true, sticky: true });
  k.sortable(host);
  const top = rows.slice(0, 20);
  const yl = top.map(r => k.surname(r.name || k.name(r.pid)) + ' (' + k.posLabel(r.pos || (k.NAMES[r.pid] || {}).pos || '') + ')');
  k.plot(node, [['5 on 5', ev, colour], ['Power play', pp, '#f97316'], ['Penalty kill', pk, '#bc8cff']].map(z => ({ type: 'bar', orientation: 'h', name: z[0], y: yl, x: top.map(z[1]), marker: { color: z[2] }, customdata: top.map(r => k.playerHref(r.pid, S)), hovertemplate: '%{y}: %{x:.1f} min<extra>' + z[0] + '</extra>' })),
    k.layout(Object.assign({ barmode: 'stack', margin: { l: 120, r: 10, t: 34, b: 34 }, yaxis: { autorange: 'reversed', automargin: true, tickfont: { size: 10 } }, xaxis: { title: 'Minutes per game' } }, k.legendTop())));
  k.clickThrough(node);
}

function schedule(abbr, x, sch, S, colour) {
  const k = K(), host = k.$('tp-sched'), cnode = k.$('tp-sched-c');
  if (!host) return;
  let games = k.listOf(x.schedule || x.games);
  if (!games.length && sch && sch.ok !== false) games = k.listOf(sch.games || sch).filter(g => g.home === abbr || g.away === abbr);
  const cards = {};
  if (sch && sch.ok !== false) k.listOf(sch.games).forEach(c => { if (c.game_id) cards[c.game_id] = c; });
  if (!games.length) { host.innerHTML = k.muted('The schedule is not available yet.'); cnode.style.display = 'none'; return; }
  const rows = games.map(g => {
    const home = g.home !== undefined && typeof g.home === 'string' ? g.home === abbr : (g.is_home === true || g.side === 'home' || g.home === true);
    const opp = g.opp || g.opponent || (g.home === abbr ? g.away : g.home);
    const m = g.model || {};
    const pTeam = k.first(g.p_win, g.model_p, k.isNum(m.p_home) ? (home ? m.p_home : 1 - m.p_home) : null);
    const card = cards[g.game_id || g.id] || {};
    const pOT = k.first(m.p_ot, g.p_ot, (card.model || {}).p_ot);
    const gf = k.first(g.gf, home ? g.hs : g.as), ga = k.first(g.ga, home ? g.as : g.hs);
    const st = String(g.status || '').toLowerCase();
    const fin = k.isNum(gf) && k.isNum(ga) && (!st || /final|off|post|done|complete/.test(st));
    const ot = !!(g.ot || g.so || card.ot || card.so || g.result === 'OTL' || /ot|so/i.test(String(g.period_type || g.last_period || '')) || (k.isNum(card.period) && card.period > 3));
    return { gid: g.game_id || g.id, date: g.date || '', home: home, opp: opp, p: pTeam, pot: pOT, gf: gf, ga: ga, fin: fin, ot: ot, so: !!g.so };
  }).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const res = z => (!z.fin ? '' : (z.gf > z.ga ? 'W' : z.ot ? 'OTL' : 'L') + ' ' + z.gf + '–' + z.ga + (z.ot && z.gf > z.ga ? (z.so ? ' (SO)' : ' (OT)') : ''));
  host.innerHTML = k.table([{ label: 'Date' }, { label: 'Opponent' }, { label: 'Our chance', align: 'right', title: 'Our pre-game win probability (including overtime)' }, { label: 'Result' }],
    rows.map(z => [{ v: z.date, html: '<strong>' + k.esc(k.fmtDate(z.date, { year: false })) + '</strong>' }, { v: z.opp, html: (z.home ? 'v ' : '@ ') + k.teamChip(z.opp, S) },
      { v: z.p, html: k.isNum(z.p) ? k.pct(z.p, 0) : '—' },
      { v: res(z), html: z.gid ? '<a href="' + k.gameHref(z.gid) + '">' + k.esc(res(z) || 'Preview') + '</a>' : k.esc(res(z)) }]), { compact: true, sticky: true });
  k.sortable(host);
  const done = rows.filter(z => z.fin && k.isNum(z.p));
  if (done.length < 2) { cnode.style.display = 'none'; return; }
  // expected points: 2·P(win) + P(lose in OT) — with P(OT) when given, else the league's ~23% of games
  let cp = 0, ce = 0, assumed = 0;
  const xs = [], ys = [], ts = [];
  done.forEach(z => { if (!k.isNum(z.pot)) assumed++; const pot = k.isNum(z.pot) ? z.pot : 0.23; cp += z.gf > z.ga ? 2 : z.ot ? 1 : 0; ce += 2 * z.p + pot * 0.5; xs.push(z.date); ys.push(cp - ce); ts.push((z.home ? 'v ' : '@ ') + z.opp + ': ' + res(z) + ' · model ' + k.pct(z.p, 0)); });
  k.plot(cnode, [{ type: 'scatter', mode: 'lines+markers', x: xs, y: ys, text: ts, hovertemplate: '%{x}<br>%{text}<br>points over expected %{y:+.1f}<extra></extra>', line: { color: colour, width: 2, shape: 'hv' }, marker: { size: 4 }, fill: 'tozeroy', fillcolor: k.alpha(colour, 0.12) }],
    k.layout({ margin: { l: 50, r: 10, t: 10, b: 34 }, xaxis: { type: 'category', nticks: 12, title: 'Date' }, yaxis: { title: 'Points − expected', zeroline: true, zerolinecolor: '#6e7681' } }));
  if (assumed) host.insertAdjacentHTML('beforeend', '<div class="pg-note gq-note">Expected points = 2·P(win) + P(overtime)/2 (an overtime loss is a point); ' + assumed + ' game' + (assumed > 1 ? 's' : '') + ' without the model\'s overtime probability use the league\'s typical 23%.</div>');
}

function roster(abbr, skRaw, gkRaw, S, colour) {
  const k = K(), host = k.$('tp-roster'), cnode = k.$('tp-roster-c');
  if (!host) return;
  const mine = [];
  [k.catOf(skRaw), k.catOf(gkRaw)].forEach((cat, gi) => {
    if (!cat) return;
    k.learnCat(cat);
    Object.keys(cat.players).filter(id => cat.players[id].team === abbr).forEach(id => {
      const p = cat.players[id], v = p.values || {}, pc = p.pct || {};
      const key = k.pick(v, ['value', 'gar', 'war', /^(rink_)?value/, 'gsax']);
      mine.push({ id: id, p: p, g: gi ? 'G' : (p.group || k.groupOf(p.pos)), v: key ? v[key] : null, pc: key ? (gi ? pc[key] : (p.pct_pos || pc)[key]) : null });
    });
  });
  if (!mine.length) { host.innerHTML = k.muted('No players for this team in the catalogues yet.'); cnode.style.display = 'none'; return; }
  mine.sort((a, b) => (k.isNum(b.v) ? b.v : -1e9) - (k.isNum(a.v) ? a.v : -1e9));
  host.innerHTML = k.table([{ label: 'Player' }, { label: 'Pos' }, { label: 'GP', align: 'right' }, { label: 'Value', align: 'right', title: 'Rink value (goals above replacement); goalies: their value from goals saved above expected' }, { label: 'Pct', align: 'right', title: 'Percentile in the position pool' }],
    mine.slice(0, 32).map(z => ({ _href: k.playerHref(z.id, S), cells: [{ v: z.p.name || k.name(z.id), html: k.playerLink(z.id, z.p.name, S) }, { v: z.p.pos || z.g, html: k.esc(k.posLabel(z.p.pos || z.g)) }, { v: k.gpOf(z.p), html: k.int(k.gpOf(z.p)) },
      { v: z.v, html: k.isNum(z.v) ? k.signed(z.v, 1) : '—' }, { v: z.pc, html: k.pill(z.pc) }] })), { compact: true, sticky: true });
  k.sortable(host);
  const top = mine.filter(z => k.isNum(z.v)).slice(0, 14);
  if (!top.length) { cnode.style.display = 'none'; return; }
  k.plot(cnode, [{ type: 'bar', orientation: 'h', y: top.map(z => k.surname(z.p.name || k.name(z.id)) + ' (' + k.posLabel(z.p.pos || z.g) + ')'), x: top.map(z => z.v), customdata: top.map(z => k.playerHref(z.id, S)),
    marker: { color: top.map(z => (z.v >= 0 ? k.alpha(colour, 0.85) : 'rgba(248,81,73,0.8)')) }, hovertemplate: '%{y}: %{x:+.1f}<extra></extra>' }],
    k.layout({ margin: { l: 130, r: 16, t: 24, b: 34 }, title: { text: 'Top contributors (value)', font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { autorange: 'reversed', automargin: true }, xaxis: { zeroline: true, zerolinecolor: '#6e7681', title: 'Goals above replacement' } }));
  k.clickThrough(cnode);
}

/* Rolling form: teams.json "rolling" [[game_no, date, xgf_pct5, gf_pct, cf_pct5]] (ten-game windows). */
function rolling(x, colour) {
  const k = K(), node = k.$('tp-roll');
  if (!node) return;
  const R = Array.isArray(x.rolling) ? x.rolling.filter(z => Array.isArray(z)) : [];
  if (R.length < 3) { k.empty(node, 'Form starts after a few games.'); return; }
  const xs = R.map(z => z[1] || z[0]);
  const tr = [[2, '5v5 xGF%', colour, 'solid'], [3, 'GF%', '#e6edf3', 'dot'], [4, '5v5 CF%', '#8b949e', 'dash']].filter(c => R.some(z => k.isNum(z[c[0]])))
    .map(c => ({ type: 'scatter', mode: 'lines', name: c[1], x: xs, y: R.map(z => z[c[0]]), line: { color: c[2], width: c[3] === 'solid' ? 2.5 : 1.5, dash: c[3] }, hovertemplate: '%{x}: %{y:.1%}<extra>' + c[1] + '</extra>' }));
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 36 }, xaxis: { title: R.every(z => z[1]) ? 'Date' : 'Game' }, yaxis: { tickformat: '.0%', title: 'Share (10-game window)' },
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#6e7681', dash: 'dot', width: 1 } }] }, k.legendTop())));
}

if (typeof RK.route === 'function') { try { RK.route('team', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
