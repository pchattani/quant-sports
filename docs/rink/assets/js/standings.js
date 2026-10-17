/* The Quant Rink — standings (#/standings, #/standings/<S>).
 *
 * Views: Wild card (each conference: the top three of each division and the two wild cards, the cut
 * line, then the chasers), Divisions, League (all 32), Playoff odds (playoffs, division, Presidents'
 * Trophy, conference, Cup; expected points with a points distribution and the seed distribution),
 * Ratings (our team rating by component, with its history) and Lottery (the draft-lottery odds).
 * Every table carries GP, W, L, OTL, PTS, points %, RW, ROW, GF, GA, xGF%, our rating, the simulated
 * playoff, division and Cup odds and the magic number (or the elimination number).
 *
 * Reads data/<S>/season.json. Shapes accepted: standings [ROW] | {division: [ROW]} | [{division,
 * conference, teams: [ROW]}]; ROW {team, conference, division, gp, w, l, otl, pts, p_pct, rw, row, gf, ga,
 * xgf_pct, rating, clinch, l10, streak, seed}; odds|sim.teams {team: {p_playoffs, p_div, p_pres, p_conf,
 * p_cup, exp_pts, pts_dist ({pts: p} | [[pts, p]]), seed_dist {seed: p}, magic, elim}}; ratings {team:
 * {overall, ev_off, ev_def, pp, pk, goalie, history [[date, overall]]}}; lottery [{team, p_first, p_top2,
 * exp_pick, by_pick: [p1..p16]}] | {team: {...}}. RK.seasonRows / RK.seedConf are shared with playoffs.js. */
(function (RK) {
'use strict';

const esc = RK.esc;
const isNum = RK.isNum;
let VIEW = 'wc';
let ODDS_TEAM = null;
let RDIV = null;

function num(v) { return isNum(v) ? Number(v) : null; }
function pick(o, keys) { for (let i = 0; i < keys.length; i++) { const v = o[keys[i]]; if (v !== undefined && v !== null && v !== '') return v; } return null; }
/* season.json -> [ROW] with odds merged and conference/division filled. */
function seasonRows(d) {
  if (!d) return [];
  const st = d.standings || d.table || {};
  let list = [];
  if (Array.isArray(st) && st.length && st[0] && Array.isArray(st[0].teams)) st.forEach(grp => grp.teams.forEach(r => list.push(Object.assign({ division: grp.division, conference: grp.conference }, r))));
  else if (Array.isArray(st)) list = st.slice();
  else if (Array.isArray(st.rows)) list = st.rows.slice();
  else Object.keys(st).forEach(div => (Array.isArray(st[div]) ? st[div] : []).forEach(r => list.push(Object.assign({ division: div }, r))));
  const odds = d.odds || (d.sim && d.sim.teams) || {};
  return list.filter(Boolean).map(r0 => {
    const t = RK.canonTeam(r0.team || r0.abbr || r0.id);
    const r = Object.assign({}, odds[t] || {}, r0, { team: t });
    const sim = odds[t] || {};
    // the simulation's spellings (season.json sim.teams): mean_pts, points_dist, p_reach {r2, conf_final, final}, magic/tragic {playoffs}
    if (!isNum(r.exp_pts)) r.exp_pts = num(pick(r, ['mean_pts', 'exp_points']));
    if (!r.pts_dist && r.points_dist) r.pts_dist = r.points_dist;
    const reach = sim.p_reach || r.p_reach || {};
    if (!isNum(r.p_r2) && isNum(reach.r2)) r.p_r2 = reach.r2;
    if (!isNum(r.p_r3) && isNum(reach.conf_final)) r.p_r3 = reach.conf_final;
    if (!isNum(r.p_final) && isNum(reach.final)) r.p_final = reach.final;
    if (r.magic && typeof r.magic === 'object') r.magic = num(r.magic.playoffs);
    const tr = sim.tragic || r.tragic;
    if (!isNum(r.elim) && tr && typeof tr === 'object') r.elim = num(tr.playoffs);
    if (!r.clinch && sim.clinched && typeof sim.clinched === 'object') r.clinch = sim.clinched.presidents ? 'p' : sim.clinched.division ? 'y' : sim.clinched.playoffs ? 'x' : (sim.eliminated && sim.eliminated.playoffs ? 'e' : null);
    if (Array.isArray(r.l10)) r.l10 = r.l10.join('-');
    r.division = r.division || RK.teamDiv(t);
    r.conference = RK.confName(r.conference || RK.teamConf(t) || RK.DIV_CONF[r.division] || '');
    ['gp', 'w', 'l', 'otl', 'pts', 'rw', 'row', 'gf', 'ga'].forEach(k => { r[k] = num(pick(r, [k, k.toUpperCase()])); });
    if (r.pts === null && r.w !== null) r.pts = 2 * r.w + (r.otl || 0);
    if (r.gp === null && r.w !== null && r.l !== null) r.gp = r.w + r.l + (r.otl || 0);
    r.p_pct = num(pick(r, ['p_pct', 'pts_pct', 'point_pct', 'pct']));
    if (r.p_pct === null && r.gp) r.p_pct = r.pts / (2 * r.gp);
    if (r.p_pct !== null && r.p_pct > 1) r.p_pct = r.p_pct / 100;
    r.diff = r.gf !== null && r.ga !== null ? r.gf - r.ga : null;
    r.xgf_pct = num(pick(r, ['xgf_pct', 'xgf_share']));
    if (r.xgf_pct !== null && r.xgf_pct > 1) r.xgf_pct = r.xgf_pct / 100;
    r.rating = num(pick(r, ['rating', 'our_rating', 'power']));
    return r;
  });
}
/* NHL order: points, then fewer games played (points %), regulation wins, ROW, wins, goal differential. */
function cmp(a, b) {
  return (b.pts || 0) - (a.pts || 0) || (b.p_pct || 0) - (a.p_pct || 0) || (b.rw || 0) - (a.rw || 0) || (b.row || 0) - (a.row || 0) ||
    (b.w || 0) - (a.w || 0) || (b.diff || 0) - (a.diff || 0) || String(a.team).localeCompare(String(b.team));
}
/* The wild-card picture for a conference: {divs: [{name, rows (top 3)}], wc: [rows, seeded], out: [rows]}. Rows get .seed ('A1', 'WC2').
 * seedsNow (season.json bracket.seeds_now {conf: {leaders: [6 teams], wild_card: [2 teams]}}, the build's seeding with the NHL
 * tiebreakers) wins over the local ordering when given. */
function seedConf(rows, conf, seedsNow) {
  const inConf = rows.filter(r => r.conference === conf);
  const sn = seedsNow && seedsNow[conf];
  if (sn && Array.isArray(sn.leaders) && Array.isArray(sn.wild_card)) {
    const byT = {};
    inConf.forEach(r => { byT[r.team] = r; });
    const lead = sn.leaders.map(RK.canonTeam).filter(t => byT[t]);
    const wcT = sn.wild_card.map(RK.canonTeam).filter(t => byT[t]);
    const divsN = [];
    lead.forEach(t => { const dv = byT[t].division; if (divsN.indexOf(dv) < 0) divsN.push(dv); });
    divsN.sort((a, b) => RK.DIVISIONS.indexOf(a) - RK.DIVISIONS.indexOf(b));
    const res = { divs: [], wc: [], out: [] };
    divsN.forEach(dv => {
      const top = lead.filter(t => byT[t].division === dv).map(t => byT[t]);
      top.forEach((r, i) => { r.seed = dv.charAt(0) + (i + 1); });
      res.divs.push({ name: dv, rows: top });
    });
    res.wc = wcT.map((t, i) => { byT[t].seed = 'WC' + (i + 1); return byT[t]; });
    res.out = inConf.filter(r => lead.indexOf(r.team) < 0 && wcT.indexOf(r.team) < 0).sort(cmp);
    res.out.forEach(r => { r.seed = null; });
    if (res.divs.length >= 2 && res.wc.length) return res;
  }
  const divs = [];
  inConf.forEach(r => { if (divs.indexOf(r.division) < 0) divs.push(r.division); });
  divs.sort((a, b) => RK.DIVISIONS.indexOf(a) - RK.DIVISIONS.indexOf(b));
  const out = { divs: [], wc: [], out: [] };
  const rest = [];
  divs.forEach(dv => {
    const list = inConf.filter(r => r.division === dv).sort(cmp);
    list.slice(0, 3).forEach((r, i) => { r.seed = dv.charAt(0) + (i + 1); });
    out.divs.push({ name: dv, rows: list.slice(0, 3) });
    list.slice(3).forEach(r => rest.push(r));
  });
  rest.sort(cmp);
  rest.forEach((r, i) => { r.seed = i < 2 ? 'WC' + (i + 1) : null; });
  out.wc = rest.slice(0, 2);
  out.out = rest.slice(2);
  return out;
}
const CLINCH = { x: 'Clinched a playoff spot', y: 'Clinched the division', z: 'Clinched the conference', p: "Clinched the Presidents' Trophy", e: 'Eliminated' };
function clinchTag(r) {
  const c = String(r.clinch || r.clinched || '').toLowerCase();
  if (c && CLINCH[c]) return '<span class="clinch' + (c === 'e' ? ' out' : '') + '" title="' + esc(CLINCH[c]) + '">' + esc(c) + '</span>';
  if (isNum(r.p_playoffs) && r.p_playoffs >= 0.9999 && r.gp) return '<span class="clinch" title="Clinched in every simulation">x</span>';
  if (isNum(r.p_playoffs) && r.p_playoffs <= 0 && r.gp) return '<span class="clinch out" title="Out in every simulation">e</span>';
  return '';
}
function magicCell(r) {
  if (isNum(r.magic) && isNum(r.gp) && r.magic > 2 * Math.max(0, RK.regGames(RK.state.season) - r.gp)) return { html: '—', v: null, title: 'Not yet within reach' };
  if (isNum(r.magic)) return { html: Number(r.magic) <= 0 ? '<span class="odds-done">✓</span>' : String(r.magic), v: r.magic, title: 'Points (from any result of ours or a chaser\'s) to clinch a playoff spot' };
  if (isNum(r.elim)) return { html: '<span class="muted-inline">E' + r.elim + '</span>', v: 100 + Number(r.elim), title: 'Elimination number' };
  return { html: '—', v: null };
}
function oddsCell(p, colour) {
  if (!isNum(p)) return { html: '—', v: null };
  if (p >= 0.9995) return { html: '<span class="odds-done">✓</span>', v: 1 };
  return { html: RK.probCell(p, colour), v: p };
}
const COLS = [{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'GP', align: 'right' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' },
  { label: 'OTL', align: 'right', title: 'Overtime and shootout losses' }, { label: 'PTS', align: 'right' }, { label: 'P%', align: 'right', title: 'Points percentage' },
  { label: 'RW', align: 'right', title: 'Regulation wins (the first tiebreaker)' }, { label: 'ROW', align: 'right', title: 'Regulation and overtime wins' },
  { label: 'GF', align: 'right' }, { label: 'GA', align: 'right' }, { label: 'Diff', align: 'right' }, { label: 'xGF%', align: 'right', title: 'Share of expected goals, score and venue adjusted' },
  { label: 'Rating', align: 'right', title: 'Our team rating: goals per game above an average team on neutral ice' },
  { label: 'Playoffs', title: 'Simulated probability of making the playoffs' }, { label: 'Div', align: 'right', title: 'Win the division' }, { label: 'Cup', align: 'right', title: 'Win the Stanley Cup' },
  { label: 'Magic', align: 'right', title: 'Magic number to clinch a playoff spot (E: elimination number)' }];
function rowCells(r, i, S, seedLabel) {
  const col = RK.teamColour(r.team);
  return { _href: RK.teamHref(r.team, S), _class: [r._cut ? 'wc-cut' : '', r.seed ? 'seed-in' : ''].filter(Boolean).join(' '), cells: [
    { html: seedLabel === undefined ? String(i + 1) : (seedLabel ? '<span class="seed-n">' + esc(seedLabel) + '</span>' : '<span class="muted-inline" title="Outside a playoff spot today">—</span>'), v: i + 1 },
    { html: RK.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
    { v: r.gp }, { v: r.w }, { v: r.l }, { v: r.otl }, { html: '<b>' + (isNum(r.pts) ? r.pts : '—') + '</b>', v: r.pts },
    { html: isNum(r.p_pct) ? r.p_pct.toFixed(3).replace(/^0/, '') : '—', v: r.p_pct }, { v: r.rw }, { v: r.row }, { v: r.gf }, { v: r.ga },
    { html: isNum(r.diff) ? '<span class="' + (r.diff > 0 ? 'pos-up' : r.diff < 0 ? 'pos-down' : '') + '">' + RK.signed(r.diff, 0) + '</span>' : '—', v: r.diff },
    { html: RK.pct(r.xgf_pct, 1), v: r.xgf_pct }, { html: RK.signed(r.rating, 2), v: r.rating },
    oddsCell(r.p_playoffs, col), { html: RK.pct(r.p_div, 0), v: r.p_div }, { html: RK.pct(r.p_cup, 1), v: r.p_cup }, magicCell(r)] };
}
function table(list, S, opts) {
  const o = opts || {};
  const hasOdds = list.some(r => isNum(r.p_playoffs));
  const hasMagic = list.some(r => isNum(r.magic) || isNum(r.elim));
  const hasX = list.some(r => isNum(r.xgf_pct)), hasR = list.some(r => isNum(r.rating));
  const keep = (c, i) => !((i === 13 && !hasX) || (i === 14 && !hasR) || (i >= 15 && i <= 17 && !hasOdds) || (i === 18 && !hasMagic));
  return RK.tableHTML(COLS.filter(keep), list.map((r, i) => { const x = rowCells(r, i, S, o.seeds ? (r.seed || '') : undefined); x.cells = x.cells.filter(keep); return x; }), { compact: true, cls: 'std-table' });
}

function wcView(rows, S, sn) {
  return '<div class="std-grid">' + RK.CONFERENCES.slice().reverse().map(conf => {
    if (!rows.some(r => r.conference === conf)) return '';
    const p = seedConf(rows, conf, sn);
    const wc = p.wc.map(r => Object.assign({}, r));
    if (wc.length) wc[wc.length - 1]._cut = true;
    const head = (t) => '<div class="box-head">' + esc(t) + '</div>';
    let body = '';
    p.divs.forEach(d => { body += head(d.name) + table(d.rows.map(r => Object.assign({}, r, { _cut: false })), S, { seeds: true }); });
    body += head('Wild card') + table(wc.concat(p.out.map(r => Object.assign({}, r, { _cut: false }))), S, { seeds: true });
    return '<div>' + RK.card(conf + ' Conference', 'top three in each division, then two wild cards · dashed: the cut line', body) + '</div>';
  }).join('') + '</div>';
}
function divView(rows, S) {
  const divs = RK.DIVISIONS.filter(dv => rows.some(r => r.division === dv));
  rows.forEach(r => { if (divs.indexOf(r.division) < 0 && r.division) divs.push(r.division); });
  return '<div class="std-grid">' + divs.map(dv => '<div>' + RK.card(dv, esc(RK.DIV_CONF[dv] || '') + ' Conference', table(rows.filter(r => r.division === dv).sort(cmp).map(r => Object.assign({}, r, { seed: null })), S)) + '</div>').join('') + '</div>';
}
function leagueView(rows, S) {
  return RK.card('League', 'all 32 teams by points', table(rows.slice().sort(cmp).map(r => Object.assign({}, r, { seed: null })), S));
}
function distOf(d) {
  if (!d) return null;
  if (Array.isArray(d)) return d.map((p, k) => (Array.isArray(p) ? [Number(p[0]), Number(p[1])] : [k, Number(p)]));
  return Object.keys(d).map(k => [Number(k), Number(d[k])]);
}
function quant(dist, q) {
  const list = (distOf(dist) || []).filter(e => isNum(e[0]) && isNum(e[1])).sort((a, b) => a[0] - b[0]);
  const tot = list.reduce((a, e) => a + e[1], 0);
  if (!tot) return null;
  let c = 0;
  for (let i = 0; i < list.length; i++) { c += list[i][1] / tot; if (c >= q) return list[i][0]; }
  return list[list.length - 1][0];
}
function oddsView(rows, S) {
  const list = rows.slice().sort((a, b) => (b.p_playoffs || 0) - (a.p_playoffs || 0) || (b.exp_pts || 0) - (a.exp_pts || 0));
  if (!list.some(r => isNum(r.p_playoffs))) return RK.muted('The season simulation has not run for ' + esc(RK.seasonLabel(S)) + '.');
  const cols = [{ label: 'Team' }, { label: 'PTS', align: 'right' }, { label: 'Exp. pts', align: 'right', title: 'Simulated final points (mean)' },
    { label: '80% range', align: 'right', title: '10th to 90th percentile of final points' }, { label: 'Playoffs' }, { label: 'Div', align: 'right' },
    { label: "Pres.", align: 'right', title: "Presidents' Trophy" }, { label: 'Conf', align: 'right', title: 'Win the conference' }, { label: 'Cup', align: 'right' }];
  const tbl = RK.tableHTML(cols, list.map(r => ({ _attrs: ' data-team="' + esc(r.team) + '"', _class: r.team === ODDS_TEAM ? 'row-sel' : '', cells: [
    { html: RK.teamLink(r.team, { short: true, season: S }), v: r.team }, { v: r.pts }, { html: RK.num(r.exp_pts, 1), v: r.exp_pts },
    { html: r.pts_dist ? quant(r.pts_dist, 0.1) + '–' + quant(r.pts_dist, 0.9) : '—', v: r.pts_dist ? quant(r.pts_dist, 0.5) : null },
    oddsCell(r.p_playoffs, RK.teamColour(r.team)), { html: RK.pct(r.p_div, 0), v: r.p_div }, { html: RK.pct(r.p_pres, 1), v: r.p_pres },
    { html: RK.pct(r.p_conf, 1), v: r.p_conf }, { html: RK.pct(r.p_cup, 1), v: r.p_cup }] })), { compact: true, cls: 'std-table odds-table' });
  const seeds = [];
  list.forEach(r => Object.keys(r.seed_dist || {}).forEach(k => { if (seeds.indexOf(k) < 0) seeds.push(k); }));
  const order = k => { const m = /^([A-Z]+)(\d)$/.exec(k); return m ? (m[1] === 'WC' ? 10 : 0) + Number(m[2]) : 50; };
  seeds.sort((a, b) => order(a) - order(b));
  const seedTbl = seeds.length ? RK.charts.heatTable({ corner: 'Team', cols: seeds.concat(['Out']), scale: 'seq', max: 1, fmt: v => (v >= 0.005 ? Math.round(v * 100) + '' : '·'),
    rows: list.map(r => {
      const sd = r.seed_dist || {};
      const tot = seeds.reduce((a, k) => a + (isNum(sd[k]) ? sd[k] : 0), 0);
      return { label: RK.teamLink(r.team, { abbr: true, season: S }), values: seeds.map(k => (isNum(sd[k]) ? Number(sd[k]) : null)).concat([Object.keys(sd).length ? Math.max(0, 1 - tot) : null]) };
    }) }) : '';
  return '<div class="grid-32"><div>' + RK.card('Playoff odds', 'from the season simulation · click a team for its points distribution', tbl) + '</div><div>' +
    RK.card('Final points', '<span id="od-team"></span>', '<div id="od-dist"></div><div class="chart-note">Bars: the simulated distribution of final points; dotted: the mean. The playoff line moves with the conference: about 95 points in an 84-game season.</div>') + '</div></div>' +
    (seedTbl ? RK.card('Seed distribution', 'percent of simulations ending in each seed (A1 = first in the Atlantic; WC = wild card)', seedTbl) : '');
}
function drawOdds(el, rows) {
  const list = rows.filter(r => r.pts_dist);
  const box = el.querySelector('#od-dist');
  if (!box) return;
  if (!list.length) { box.innerHTML = RK.muted('No points distributions in this build.'); return; }
  if (!ODDS_TEAM || !list.some(r => r.team === ODDS_TEAM)) ODDS_TEAM = list.slice().sort((a, b) => (b.p_cup || 0) - (a.p_cup || 0))[0].team;
  const r = list.find(x => x.team === ODDS_TEAM);
  el.querySelector('#od-team').innerHTML = RK.teamLink(r.team) + ' · mean ' + RK.num(r.exp_pts, 1);
  const d = {};
  (distOf(r.pts_dist) || []).forEach(e => { d[e[0]] = e[1]; });
  RK.purge(box);
  RK.charts.distBars(box, d, { exp: r.exp_pts, colour: RK.teamColour(r.team), unit: 'points', height: 260, xTitle: 'Final points' });
  el.querySelectorAll('.odds-table tr[data-team]').forEach(tr => tr.classList.toggle('row-sel', tr.dataset.team === ODDS_TEAM));
}
const R_KEYS = [['overall', 'Overall'], ['ev_off', '5v5 offence'], ['ev_def', '5v5 defence'], ['pp', 'Power play'], ['pk', 'Penalty kill'], ['goalie', 'Goaltending']];
/* season.json ratings {team: {units: {rating, off5, def5, pp, pk, goalie, pct: {key: 0-100}, model}, history}} -> {team: {overall, ev_off, ..., pct, history}}. */
const U_KEYS = { off5: 'ev_off', def5: 'ev_def', pp: 'pp', pk: 'pk', goalie: 'goalie', rating: 'overall' };
function flatRatings(d) {
  const src = d.ratings || {};
  const out = {};
  Object.keys(src).forEach(t => {
    const x = src[t] || {};
    if (!x.units) { out[t] = x; return; }
    const u = x.units;
    const o = { history: x.history || x.rolling || [], pct: {}, raw: true };
    Object.keys(U_KEYS).forEach(k => { if (isNum(u[k])) o[U_KEYS[k]] = Number(u[k]); if (u.pct && isNum(u.pct[k])) o.pct[U_KEYS[k]] = Number(u.pct[k]); });
    if (!isNum(o.overall) && isNum(x.rating)) o.overall = Number(x.rating);
    out[t] = o;
  });
  return out;
}
function ratingsView(d, rows, S) {
  const rt = flatRatings(d);
  const teams = Object.keys(rt);
  if (!teams.length) return RK.muted('Team ratings are not in this build.');
  const keys = R_KEYS.filter(k => teams.some(t => isNum((rt[t] || {})[k[0]])));
  const list = teams.slice().sort((a, b) => ((rt[b] || {}).overall || 0) - ((rt[a] || {}).overall || 0));
  const hasPct = teams.some(t => Object.keys((rt[t] || {}).pct || {}).length);
  const heat = hasPct
    ? RK.tableHTML([{ label: 'Team' }].concat(keys.map(k => ({ label: k[1], align: 'right', title: k[0] === 'ev_def' ? 'Expected goals against per 60 at 5v5 (lower is better); colour: league percentile' : 'Colour: league percentile' }))),
      list.map(t => { const x = rt[t] || {}; return { _href: RK.teamHref(t, S), cells: [{ html: RK.teamLink(t, { short: true, season: S }), v: t }].concat(keys.map(k => {
        const v = num(x[k[0]]), p = (x.pct || {})[k[0]];
        return { html: v === null ? '—' : '<span class="rt-cell" style="background:' + (isNum(p) ? RK.pctColor(p) : 'transparent') + '" title="' + (isNum(p) ? Math.round(p) + 'th percentile' : '') + '">' + (k[0] === 'overall' ? RK.signed(v, 2) : RK.num(v, 2)) + '</span>', v: v };
      })) }; }), { compact: true, cls: 'std-table' })
    : RK.charts.heatTable({ corner: 'Team', cols: keys.map(k => ({ label: k[1] })), center: 0, fmt: v => RK.signed(v, 2),
      rows: list.map(t => ({ label: RK.teamLink(t, { short: true, season: S }), values: keys.map(k => num((rt[t] || {})[k[0]])) })) });
  const divs = RK.DIVISIONS.filter(dv => teams.some(t => RK.teamDiv(t) === dv));
  if (!RDIV || divs.indexOf(RDIV) < 0) RDIV = divs[0];
  return '<div><div>' + RK.card('Team ratings', hasPct ? 'overall: goals per game above average; units: 5v5 xGF/60 and xGA/60, special teams and goaltending · colour: league percentile (red good)' : 'goals per game above average, by component · red good, blue poor', heat) + '</div><div>' +
    RK.card('Rating history', 'overall rating through the season', '<div class="toggle-row">' + RK.toggles(divs.map(x => ({ key: x, label: x })), RDIV, 'data-rdiv') + '</div><div id="rt-hist"></div>') + '</div></div>';
}
function drawRatings(el, d) {
  const box = el.querySelector('#rt-hist');
  if (!box) return;
  const rt = flatRatings(d);
  const series = Object.keys(rt).filter(t => RK.teamDiv(t) === RDIV && Array.isArray((rt[t] || {}).history) && rt[t].history.length).map(t => ({
    name: RK.teamAbbr(t), x: rt[t].history.map(h => h[0]), y: rt[t].history.map(h => h[1]), colour: RK.teamColour(t), hover: esc(RK.teamAbbr(t)) + ' %{x}: %{y:+.2f}<extra></extra>' }));
  RK.purge(box);
  RK.charts.lines(box, series, { height: 340, yTitle: 'Rating', emptyText: 'No rating history yet.' });
}
function lotteryView(d, rows, S) {
  let L = d.lottery || d.draft || null;
  if (L && !Array.isArray(L) && Array.isArray(L.table)) {
    // by draft slot (1 = the worst team): today's occupant is read off the bottom of the league table
    const bottom = rows.slice().sort(RK.standingsCmp).reverse();
    L = L.table.map(x => Object.assign({}, x, { team: x.team || (bottom[(x.slot || 1) - 1] || {}).team, p_top2: isNum(x.p_top2) ? x.p_top2 : (isNum(x.p_first) && isNum(x.p_second) ? x.p_first + x.p_second : null),
      exp_pick: isNum(x.exp_pick) ? x.exp_pick : (Array.isArray(x.pick_dist) ? x.pick_dist.reduce((a, p, i) => a + (Number(p) || 0) * (i + 1), 0) : null), by_pick: x.by_pick || x.pick_dist, slot: x.slot }));
  } else if (L && !Array.isArray(L) && typeof L === 'object') L = Object.keys(L).map(t => Object.assign({ team: t }, L[t]));
  const list = (L || []).filter(Boolean).map(x => Object.assign({}, x, { team: RK.canonTeam(x.team) }));
  if (!list.length) return RK.muted('Draft-lottery odds are not in this build.');
  list.sort((a, b) => (num(a.exp_pick) || 99) - (num(b.exp_pick) || 99) || (b.p_first || 0) - (a.p_first || 0));
  const byPick = list.some(x => Array.isArray(x.by_pick));
  const n = byPick ? Math.min(16, Math.max.apply(null, list.map(x => (x.by_pick || []).length))) : 0;
  const bySlot = list.some(x => isNum(x.slot));
  const tbl = RK.tableHTML([{ label: bySlot ? 'Slot · team today' : 'Team' }, { label: 'Exp. pick', align: 'right' }, { label: 'No. 1', align: 'right', title: 'Probability of the first pick' },
    { label: 'Top 2', align: 'right' }, { label: 'Playoffs', align: 'right', title: 'A playoff team does not enter the lottery' }],
  list.map(x => { const r = rows.find(z => z.team === x.team) || {}; return { _href: x.team ? RK.teamHref(x.team, S) : null, cells: [{ html: (bySlot ? '<span class="seed-n">' + x.slot + '</span> ' : '') + (x.team ? RK.teamLink(x.team, { short: true, season: S }) : '—'), v: bySlot ? x.slot : x.team },
    { html: RK.num(x.exp_pick, 1), v: x.exp_pick }, { html: RK.pct(x.p_first, 1), v: x.p_first }, { html: RK.pct(x.p_top2, 1), v: x.p_top2 }, { html: RK.pct(r.p_playoffs, 0), v: r.p_playoffs }] }; }), { compact: true });
  const heat = byPick ? RK.charts.heatTable({ corner: 'Team', cols: Array.from({ length: n }, (_, i) => String(i + 1)), scale: 'seq', max: 1, fmt: v => (v >= 0.005 ? Math.round(v * 100) + '' : '·'),
    rows: list.map(x => ({ label: (bySlot ? x.slot + ' ' : '') + (x.team ? RK.teamLink(x.team, { abbr: true, season: S }) : ''), values: Array.from({ length: n }, (_, i) => num((x.by_pick || [])[i])) })) }) : '';
  return RK.card('Draft lottery', bySlot ? 'by lottery slot (1 = the fewest points among the 16 non-playoff teams; today\'s occupant shown) · two draws, a team moves up at most 10 places' : 'the 16 non-playoff teams: the simulation of the standings and the NHL draw (two draws; a team moves up at most 10 places)', tbl) +
    (heat ? RK.card('Pick distribution', 'percent of simulations landing each pick', heat) : '');
}

RK.seasonRows = seasonRows;
RK.seedConf = seedConf;
RK.standingsCmp = cmp;

RK.route('standings', function (el, params) {
  const S = params.season;
  const q = (params.query || {}).view;
  if (q && ['wc', 'div', 'league', 'odds', 'ratings', 'lottery'].indexOf(q) >= 0) VIEW = q;
  return RK.loadYear('season.json', S).then(d => {
    if (!el.isConnected) return;
    const S0 = RK.currentSeason();
    const nav = (S > RK.FIRST_SEASON ? '<a href="' + RK.standingsHref(S - 10001) + '">← ' + esc(RK.seasonLabel(S - 10001)) + '</a>' : '') +
      (S < S0 ? '<a href="' + RK.standingsHref(S + 10001) + '">' + esc(RK.seasonLabel(S + 10001)) + ' →</a>' : '') + '<a href="' + RK.playoffsHref(S) + '">Playoffs</a>';
    const head = RK.pageHead(RK.seasonLabel(S) + ' standings', 'points: 2 for a win, 1 for an overtime or shootout loss · ' + RK.regGames(S) + ' games', nav);
    if (!RK.ok(d)) { el.innerHTML = head + RK.notBuilt('The ' + RK.seasonLabel(S) + ' standings', d); return; }
    const rows = seasonRows(d);
    const views = [['wc', 'Wild card'], ['div', 'Divisions'], ['league', 'League'], ['odds', 'Playoff odds'], ['ratings', 'Ratings'], ['lottery', 'Lottery']];
    el.innerHTML = head + '<div class="seg-tabs std-tabs">' + views.map(v => '<a data-v="' + v[0] + '"' + (v[0] === VIEW ? ' class="active"' : '') + '>' + esc(v[1]) + '</a>').join('') + '</div><div id="std-body"></div>' +
      '<div class="chart-note">Clinch marks: x playoff spot, y division, z conference, p Presidents\' Trophy, e eliminated. Ties are broken by points %, regulation wins, regulation and overtime wins, then wins. Odds come from simulating the rest of the season with our game model.' + (d.updated_at ? ' Updated ' + esc(RK.fmtStamp(d.updated_at)) + '.' : '') + '</div>';
    const body = el.querySelector('#std-body');
    const show = v => {
      VIEW = v;
      el.querySelectorAll('.std-tabs a').forEach(a => a.classList.toggle('active', a.dataset.v === v));
      RK.purge(body);
      if (!rows.length && v !== 'ratings' && v !== 'lottery') { body.innerHTML = RK.muted('No standings rows in this build.'); return; }
      body.innerHTML = v === 'wc' ? wcView(rows, S, (d.bracket || {}).seeds_now) : v === 'div' ? divView(rows, S) : v === 'league' ? leagueView(rows, S) : v === 'odds' ? oddsView(rows, S) : v === 'ratings' ? ratingsView(d, rows, S) : lotteryView(d, rows, S);
      RK.sortable(body);
      if (v === 'odds') {
        drawOdds(body, rows);
        body.querySelectorAll('.odds-table tr[data-team]').forEach(tr => tr.addEventListener('click', ev => { if (ev.target.closest('a')) return; ODDS_TEAM = tr.dataset.team; drawOdds(body, rows); }));
      }
      if (v === 'ratings') { drawRatings(body, d); RK.wireToggles(body, 'data-rdiv', k => { RDIV = k; drawRatings(body, d); }); }
    };
    el.querySelectorAll('.std-tabs a').forEach(a => a.addEventListener('click', () => show(a.dataset.v)));
    show(VIEW);
  });
});

})(window.RK);
