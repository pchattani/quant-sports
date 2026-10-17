/* The Quant Gridiron — standings (#/standings, #/standings/<S>).
 *
 * Views: Divisions (W-L-T, points for and against, differential, our rating, strength of schedule
 * played and remaining, simulated playoff, division, bye and Super Bowl odds, magic and elimination
 * numbers), Conferences (the seeding race with the cut line), Ratings (our unit ratings and their
 * week-by-week history), Win totals (each team's simulated win distribution) and Draft order.
 *
 * Reads data/<S>/season.json. Shapes accepted: standings {division: [ROW]} or [ROW] (ROW carries
 * division); a team's simulation odds on the row, or under odds|sim.teams {team: {...}}; ratings
 * {team: {overall, pass_off, rush_off, pass_def, rush_def, st, qb, history: [[week, overall]]}};
 * draft [{team, exp_pick, p_first|p_1, p_top5}] or {team: {...}}. GI.seasonRows(season) is shared
 * with playoffs.js. */
(function (GI) {
'use strict';

const esc = GI.esc;
const isNum = GI.isNum;
let VIEW = 'div';
let RDIV = null;

function num(v) { return isNum(v) ? Number(v) : null; }
/* season.json -> [ROW] with odds merged and conference/division filled. */
function seasonRows(d) {
  if (!d) return [];
  const st = d.standings || d.table || {};
  let list = [];
  if (Array.isArray(st) && st.length && Array.isArray(st[0].teams)) st.forEach(grp => grp.teams.forEach(r => list.push(Object.assign({ division: grp.division, conference: grp.conference }, r))));
  else if (Array.isArray(st)) list = st.slice();
  else Object.keys(st).forEach(div => (Array.isArray(st[div]) ? st[div] : []).forEach(r => list.push(Object.assign({ division: div }, r))));
  const odds = d.odds || (d.sim && d.sim.teams) || {};
  return list.map((r0, k) => {
    const t = GI.canonTeam(r0.team || r0.abbr || r0.id);
    const r = Object.assign({}, odds[t] || {}, r0, { team: t });
    const info = GI.teamInfo(t);
    r.division = r.division || info.division || '';
    r.conference = r.conference || r.conf || info.conference || String(r.division).slice(0, 3);
    if (!isNum(r.diff) && isNum(r.pf) && isNum(r.pa)) r.diff = Number(r.pf) - Number(r.pa);
    if (!isNum(r.sos_rem) && isNum(r.sos_left)) r.sos_rem = r.sos_left;
    if (!isNum(r.seed) && isNum(r.seed_today)) r.seed = r.seed_today;
    if (!isNum(r.proj_w)) r.proj_w = isNum(r.mean_wins) ? r.mean_wins : distMean(r.win_dist);
    r._order = k;
    return r;
  });
}
GI.seasonRows = seasonRows;
function distMean(wd) {
  if (!wd) return null;
  const ks = Array.isArray(wd) ? wd.map((_, i) => i) : Object.keys(wd).map(Number);
  let e = 0, t = 0;
  ks.forEach(k => { const v = Number(Array.isArray(wd) ? wd[k] : wd[String(k)]) || 0; e += k * v; t += v; });
  return t ? e / t : null;
}
function flag(o, k) { return o && typeof o === 'object' && o[k] === true; }
function pctW(r) { const g = (num(r.w) || 0) + (num(r.l) || 0) + (num(r.t) || 0); return g ? ((num(r.w) || 0) + 0.5 * (num(r.t) || 0)) / g : 0; }
function clinchTag(r) {
  if (flag(r.eliminated, 'playoffs')) return '<span class="clinch out" title="Eliminated from playoff contention">e</span>';
  if (flag(r.clinched, 'top_seed')) return '<span class="clinch" title="Clinched the No. 1 seed and the bye">z</span>';
  if (flag(r.clinched, 'division')) return '<span class="clinch" title="Clinched the division">y</span>';
  if (flag(r.clinched, 'playoffs')) return '<span class="clinch" title="Clinched a playoff berth">x</span>';
  const c = typeof r.clinched === 'object' || typeof r.clinch === 'object' ? '' : String(r.clinched || r.clinch || r.status || '').toLowerCase();
  if (r.elim === true || c === 'e' || /elim/.test(c)) return '<span class="clinch out" title="Eliminated from playoff contention">e</span>';
  if (c === 'z' || /bye|seed1|top/.test(c)) return '<span class="clinch" title="Clinched a first-round bye">z</span>';
  if (c === 'y' || /div/.test(c)) return '<span class="clinch" title="Clinched the division">y</span>';
  if (c === 'x' || /playoff|clinch/.test(c)) return '<span class="clinch" title="Clinched a playoff berth">x</span>';
  return '';
}
function magicCell(r) {
  if (isNum(r.magic)) return { html: '<span title="Magic number to clinch a playoff place">M' + Math.round(r.magic) + '</span>', v: r.magic };
  if (isNum(r.elim)) return { html: '<span class="muted-inline" title="Elimination number">E' + Math.round(r.elim) + '</span>', v: 100 + Number(r.elim) };
  if (r.magic && typeof r.magic === 'object') {
    const m = r.magic;
    const bits = [];
    if (flag(r.eliminated, 'playoffs')) return { html: '<span class="muted-inline">out</span>', v: 999 };
    if (isNum(m.playoffs)) bits.push('<span title="Magic number to clinch a playoff place">P' + m.playoffs + '</span>');
    if (isNum(m.division) && !flag(r.eliminated, 'division')) bits.push('<span title="Magic number to win the division">D' + m.division + '</span>');
    return { html: bits.join(' ') || '—', v: m.playoffs };
  }
  return { html: '—', v: null };
}
function oddsCell(p, colour) {
  if (!isNum(p)) return { html: '<span class="muted-inline">—</span>', v: null };
  if (p >= 0.9995) return { html: '<span class="odds-done">✓</span>', v: 1 };
  if (p <= 0.0005) return { html: '<span class="muted-inline">0%</span>', v: 0 };
  return { html: GI.probCell(p, colour), v: p };
}

function divTable(rows, S) {
  const cols = [{ label: 'Team' }, { label: 'W-L-T', align: 'right' }, { label: 'PF', align: 'right' }, { label: 'PA', align: 'right' }, { label: 'Diff', align: 'right' },
    { label: 'Rating', align: 'right', title: 'Our team rating: points better than an average team on a neutral field' },
    { label: 'SOS', align: 'right', title: 'Strength of schedule played (average opponent rating)' }, { label: 'Rem SOS', align: 'right', title: 'Strength of the remaining schedule' },
    { label: 'Playoffs', title: 'Simulated probability of making the playoffs' }, { label: 'Div', align: 'right', title: 'Win the division' }, { label: 'Bye', align: 'right', title: 'The No. 1 seed and the bye' },
    { label: 'SB', align: 'right', title: 'Win the Super Bowl' }, { label: 'Magic', align: 'right', title: 'Magic numbers: P to clinch a playoff place, D to win the division (M / E when the build writes one number)' }];
  return GI.tableHTML(cols, rows.map(r => ({ _href: GI.teamHref(r.team, S), cells: [
    { html: GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
    { html: GI.record(r.w, r.l, r.t), v: pctW(r) }, { v: r.pf, align: 'right' }, { v: r.pa, align: 'right' },
    { html: isNum(r.diff) ? GI.signed(r.diff, 0) : '—', v: r.diff }, { html: isNum(r.rating) ? GI.signed(r.rating, 1) : '—', v: r.rating },
    { html: isNum(r.sos) ? GI.signed(r.sos, 1) : '—', v: r.sos }, { html: isNum(r.sos_rem) ? GI.signed(r.sos_rem, 1) : '—', v: r.sos_rem },
    oddsCell(r.p_playoffs, GI.teamColour(r.team)), { html: isNum(r.p_div) ? GI.pct(r.p_div, 0) : '—', v: r.p_div }, { html: isNum(r.p_bye) ? GI.pct(r.p_bye, 0) : '—', v: r.p_bye },
    { html: isNum(r.p_sb) ? GI.pct(r.p_sb, 1) : '—', v: r.p_sb }, magicCell(r)
  ] })), { cls: 'std-table', compact: true });
}
function divisionsView(rows, S) {
  const cols = GI.CONFERENCES.map(conf => '<div>' + GI.DIVISIONS.filter(d => d.indexOf(conf) === 0).map(div => {
    const list = rows.filter(r => r.division === div).sort((a, b) => (isNum(a.div_rank) && isNum(b.div_rank) ? a.div_rank - b.div_rank : pctW(b) - pctW(a) || a._order - b._order));
    if (!list.length) return '';
    return GI.card(div, '', divTable(list, S));
  }).join('') + '</div>');
  const other = rows.filter(r => GI.DIVISIONS.indexOf(r.division) < 0);
  return '<div class="std-grid">' + cols.join('') + '</div>' + (other.length ? GI.card('Other', '', divTable(other, S)) : '') +
    '<div class="chart-note">x clinched a playoff place · y the division · z the bye · e eliminated. Odds from our season simulation of the remaining schedule with the NFL tiebreakers.</div>';
}
function seedOrder(list) {
  return list.slice().sort((a, b) => {
    if (isNum(a.seed) && isNum(b.seed)) return a.seed - b.seed;
    if (isNum(a.seed)) return -1;
    if (isNum(b.seed)) return 1;
    return (num(b.p_playoffs) || 0) - (num(a.p_playoffs) || 0) || pctW(b) - pctW(a);
  });
}
function conferencesView(rows, S) {
  return '<div class="grid-2">' + GI.CONFERENCES.map(conf => {
    const list = seedOrder(rows.filter(r => r.conference === conf));
    const cols = [{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L-T', align: 'right' }, { label: 'Div', title: 'Division' }, { label: 'Playoffs' },
      { label: 'Bye', align: 'right' }, { label: 'Conf', align: 'right', title: 'Win the conference' }, { label: 'SB', align: 'right' }];
    const body = GI.tableHTML(cols, list.map((r, i) => ({ _class: (i === 6 ? 'wc-cut ' : '') + (i < 7 ? 'seed-in' : ''), _href: GI.teamHref(r.team, S), cells: [
      { html: '<span class="seed-n">' + (isNum(r.seed) ? r.seed : i + 1) + '</span>', v: i + 1 }, { html: GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
      { html: GI.record(r.w, r.l, r.t), v: pctW(r) }, String(r.division || '').replace(/^(AFC|NFC) /, ''), oddsCell(r.p_playoffs, GI.teamColour(r.team)),
      { html: GI.pct(r.p_bye, 0), v: r.p_bye }, { html: GI.pct(r.p_conf, 1), v: r.p_conf }, { html: GI.pct(r.p_sb, 1), v: r.p_sb }
    ] })), { cls: 'std-table', compact: true });
    return '<div>' + GI.card(conf, 'the seeding race · dashed line: the cut after the 7th seed', body) + '</div>';
  }).join('') + '</div>' + '<div class="chart-note">Order: the seeds as they stand when the payload carries them, else by simulated playoff probability. <a href="' + GI.playoffsHref(S) + '">The bracket and seed distributions →</a></div>';
}
/* {team: {overall, ...}} from ratings {team: {...}} or {team: {values: {rating, off_rating, ...}, history}}; defence EPA flipped so higher is better. */
function flatRatings(d) {
  const src = d.ratings || d.team_ratings || {};
  const hc = d.ratings_history_cols || ['week', 'net'];
  const ni = Math.max(1, hc.indexOf('net'));
  const out = {};
  Object.keys(src).forEach(t => {
    const x = src[t] || {};
    const v = x.values || x;
    const neg = k => (isNum(v[k]) ? -Number(v[k]) : null);
    out[GI.canonTeam(t)] = {
      overall: isNum(v.overall) ? v.overall : v.rating, off: v.off_rating, def: v.def_rating,
      pass_off: isNum(v.pass_off) ? v.pass_off : v.off_pass_epa, rush_off: isNum(v.rush_off) ? v.rush_off : v.off_rush_epa,
      pass_def: isNum(v.pass_def) ? v.pass_def : neg('def_pass_epa'), rush_def: isNum(v.rush_def) ? v.rush_def : neg('def_rush_epa'),
      st: isNum(v.st) ? v.st : v.st_epa_g, qb: v.qb,
      history: (x.history || []).map(r => (Array.isArray(r) ? [r[0], r[ni]] : [r.week, isNum(r.overall) ? r.overall : r.rating]))
    };
  });
  return out;
}
function ratingsView(d, rows, S) {
  const rat = flatRatings(d);
  const teams = Object.keys(rat).length ? Object.keys(rat) : rows.map(r => r.team);
  if (!teams.length) return GI.muted('Ratings arrive with the first build.');
  const keys = [['overall', 'Overall', 'Points better than average on a neutral field', 1], ['off', 'Offence', 'Offence rating, points', 1], ['def', 'Defence', 'Defence rating, points', 1], ['pass_off', 'Pass off.', 'EPA per dropback above average, opponent-adjusted', 3], ['rush_off', 'Rush off.', 'EPA per carry above average', 3],
    ['pass_def', 'Pass def.', 'EPA per dropback allowed, better than average = positive', 3], ['rush_def', 'Rush def.', 'EPA per carry allowed, better than average = positive', 3], ['st', 'Special teams', 'Special-teams EPA per game', 2], ['qb', 'QB', 'The starting quarterback component, EPA per play', 3]];
  const has = keys.filter(k => teams.some(t => isNum((rat[t] || {})[k[0]]) || (k[0] === 'overall' && isNum((rows.find(r => r.team === t) || {}).rating))));
  const ov = t => { const x = rat[t] || {}; return isNum(x.overall) ? x.overall : (rows.find(r => r.team === t) || {}).rating; };
  const sorted = teams.slice().sort((a, b) => (num(ov(b)) || 0) - (num(ov(a)) || 0));
  const spec = { cols: has.map(k => ({ label: k[1], title: k[2] })), corner: 'Team', center: 'col', fmt: (v, i) => GI.signed(v, has[i][3]),
    rows: sorted.map(t => ({ label: GI.teamLink(t, { short: true, season: S }), values: has.map(k => (k[0] === 'overall' ? ov(t) : (rat[t] || {})[k[0]])) })) };
  const anyHist = teams.some(t => ((rat[t] || {}).history || []).length > 1);
  if (!RDIV) RDIV = GI.DIVISIONS[0];
  return '<div class="grid-32"><div>' + GI.card('Team ratings', 'opponent-adjusted, with priors and time decay · blue below average, red above', GI.charts.heatTable(spec)) + '</div><div>' +
    (anyHist ? GI.card('Rating by week', 'overall rating', '<div class="toggle-row" id="rt-divs">' + GI.toggles(GI.DIVISIONS.map(x => ({ key: x, label: x })), RDIV, 'data-dv') + '</div><div id="rt-chart"></div>') : '') + '</div></div>';
}
function drawRatings(el, d) {
  const box = el.querySelector('#rt-chart');
  if (!box) return;
  const rat = flatRatings(d);
  const teams = Object.keys(rat).filter(t => GI.teamInfo(t).division === RDIV);
  GI.charts.lines(box, teams.map(t => {
    const h = (rat[t].history || []).map(r => ({ w: r[0], v: r[1] }));
    return { name: GI.teamAbbr(t), x: h.map(r => r.w), y: h.map(r => r.v), colour: GI.teamColour(t), mode: 'lines+markers', hover: esc(GI.teamAbbr(t)) + ' week %{x}: %{y:+.1f}<extra></extra>' };
  }), { height: 320, xTitle: 'Week', yTitle: 'Rating (pts)', xaxis: { dtick: 1 } });
}
function winsView(rows, S) {
  const list = rows.filter(r => r.win_dist).sort((a, b) => (num(b.proj_w) || 0) - (num(a.proj_w) || 0));
  if (!list.length) return GI.muted('Win distributions arrive with the season simulation.');
  let maxW = 0;
  list.forEach(r => { const wd = r.win_dist; (Array.isArray(wd) ? wd.map((_, i) => i) : Object.keys(wd).map(Number)).forEach(k => { if (k > maxW) maxW = k; }); });
  const ks = [];
  for (let k = 0; k <= maxW; k++) ks.push(k);
  const val = (wd, k) => (Array.isArray(wd) ? wd[k] : wd[String(k)]);
  const spec = { cols: ks.map(String).concat(['Mean']), corner: 'Wins', scale: 'seq', max: 0.35,
    fmt: (v, i) => (i === ks.length ? GI.num(v, 1) : (v >= 0.005 ? Math.round(v * 100) + '' : '·')),
    rows: list.map(r => ({ label: GI.teamLink(r.team, { abbr: true, season: S }) + ' <span class="muted-inline">' + GI.record(r.w, r.l, r.t) + '</span>', values: ks.map(k => val(r.win_dist, k)).concat([null]),
      titles: ks.map(k => GI.teamAbbr(r.team) + ' ' + k + ' wins: ' + GI.pct(val(r.win_dist, k), 1)) })) };
  // the mean column is text, not a colour
  let html = GI.charts.heatTable(spec);
  list.forEach(r => { html = html.replace('<td class="heat-cell heat-empty">·</td></tr>', '<td class="heat-cell"><b>' + GI.num(r.proj_w, 1) + '</b></td></tr>'); });
  return GI.card('Win totals', 'simulated final regular-season wins, % of simulations', html + '<div class="chart-note">Each row sums to 100%. Compare with the win-total markets on <a href="#/markets">Markets</a>.</div>');
}
function draftView(d, rows, S) {
  let list = d.draft || d.draft_order || [];
  if (!Array.isArray(list)) list = Object.keys(list).map(t => Object.assign({ team: t }, list[t]));
  if (!list.length) return GI.muted('Draft-order odds arrive with the season simulation.');
  list = list.map(x => Object.assign({}, x, { team: GI.canonTeam(x.team), exp_pick: isNum(x.exp_pick) ? x.exp_pick : x.mean_pick, p_first: isNum(x.p_first) ? x.p_first : x.p_first_pick }))
    .sort((a, b) => (num(a.exp_pick) || num(a.pick_today) || 99) - (num(b.exp_pick) || num(b.pick_today) || 99));
  const simmed = list.some(x => isNum(x.exp_pick));
  const rec = t => rows.find(r => r.team === t) || {};
  return GI.card('Draft order', (simmed ? 'simulated' : 'if the season ended today (by record and strength of schedule; the simulated order arrives with the season model)') + ', before trades; ' + (S + 1) + ' draft',
  GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L-T', align: 'right' },
    { label: 'Expected pick', align: 'right' }, { label: 'No. 1 pick' }, { label: 'Top 5', align: 'right' }, { label: 'Top 10', align: 'right' }],
  list.map((x, i) => ({ _href: GI.teamHref(x.team, S), cells: [isNum(x.pick_today) ? x.pick_today : i + 1, { html: GI.teamLink(x.team, { short: true, season: S }), v: x.team }, { html: GI.record(rec(x.team).w, rec(x.team).l, rec(x.team).t), v: pctW(rec(x.team)) },
    { html: GI.num(x.exp_pick, 1), v: x.exp_pick }, { html: GI.probCell(isNum(x.p_first) ? x.p_first : x.p_1, GI.teamColour(x.team)), v: isNum(x.p_first) ? x.p_first : x.p_1 },
    { html: GI.pct(x.p_top5, 0), v: x.p_top5 }, { html: GI.pct(x.p_top10, 0), v: x.p_top10 }] })), { compact: true }));
}

GI.route('standings', function (el, params) {
  const S = Number(params.season);
  const qv = (params.query || {}).view;
  if (['div', 'conf', 'ratings', 'wins', 'draft'].indexOf(qv) >= 0) VIEW = qv;
  return GI.loadYear('season.json', S).then(d => {
    if (!el.isConnected) return;
    const nav = '<a href="' + GI.playoffsHref(S) + '">Playoffs →</a>' + (S > GI.FIRST_SEASON ? '<a href="' + GI.standingsHref(S - 1) + '">← ' + (S - 1) + '</a>' : '') + (S < GI.currentSeason() ? '<a href="' + GI.standingsHref(S + 1) + '">' + (S + 1) + ' →</a>' : '');
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead(S + ' standings', '', nav) + GI.notBuilt('The ' + S + ' standings', d); return; }
    const rows = seasonRows(d);
    const sim = d.sim || {};
    const nsim = isNum(sim.sims) ? sim.sims : sim.n;
    const sub = [isNum(d.week) ? 'week ' + d.week : '', isNum(nsim) ? GI.int(nsim) + ' simulations' : (sim.reason ? 'no simulation: ' + sim.reason : ''), d.updated_at ? 'updated ' + GI.fmtStamp(d.updated_at) : ''].filter(Boolean).join(' · ');
    const views = [['div', 'Divisions'], ['conf', 'Conferences'], ['ratings', 'Ratings'], ['wins', 'Win totals'], ['draft', 'Draft order']];
    el.innerHTML = GI.pageHead(S + ' standings', esc(sub), nav) + '<div class="seg-tabs">' + views.map(v => '<a data-v="' + v[0] + '"' + (v[0] === VIEW ? ' class="active"' : '') + ' style="cursor:pointer">' + v[1] + '</a>').join('') + '</div><div id="std-body"></div>';
    const body = el.querySelector('#std-body');
    const draw = () => {
      el.querySelectorAll('.seg-tabs a').forEach(a => a.classList.toggle('active', a.dataset.v === VIEW));
      body.innerHTML = VIEW === 'conf' ? conferencesView(rows, S) : VIEW === 'ratings' ? ratingsView(d, rows, S) : VIEW === 'wins' ? winsView(rows, S) : VIEW === 'draft' ? draftView(d, rows, S) : divisionsView(rows, S);
      GI.sortable(body);
      if (VIEW === 'ratings') {
        drawRatings(body, d);
        GI.wireToggles(body.querySelector('#rt-divs'), 'data-dv', k => { RDIV = k; drawRatings(body, d); });
      }
    };
    el.querySelectorAll('.seg-tabs a').forEach(a => a.addEventListener('click', () => { VIEW = a.dataset.v; draw(); }));
    draw();
  });
});

})(window.GI);
