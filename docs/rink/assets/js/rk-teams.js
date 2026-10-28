/* The Quant Rink — the Teams page (#/teams), round 9 (28 Oct 2026, after the Bullpen pilot bp-teams.js): every club
 * ranked, profiled and set against the rest. It replaces the old Clubs tab (tiles, the team-set table and the
 * offence-v-defence chart) and the legacy team catalogue; team pages (#/team/<abbr>) stay in rk-team.js.
 * Kit: scout.js (QK.powerBars, QK.heatGrid, QK.strengths), quant.js (QK.tape with gap: true), quant-charts.js
 * (QKC.scatter, QKC.line).
 *
 * Sections (a chip strip jumps between them; ?go=<section> scrolls to one):
 *   1. Power board (power): each club ranked by our rating, a bar split into where its goal difference comes from this
 *      season (5v5 attack, 5v5 defence, power play, penalty kill, goaltending: goals a game against an average club,
 *      from the per-60 counts and each club's minutes in each state), our rating as the volt tick, the record, points,
 *      projected points and quiet playoff and Cup chances; Division | Conference | All (?pw=).
 *   2. Team profile (grid): the heat grid of the 32 clubs on every team metric in season.json (the units, our model's
 *      goals for and against, finishing and saving above expected, results), phase chips, percentile cells, sortable,
 *      CSV (?grid=, gadd=, gsort=).
 *   3. Style map (map): any two team metrics with six presets, the corners named, medians dashed, lower-is-better axes
 *      flipped; the site's one offence-v-defence chart (?map=, mx=, my=).
 *   4. Strengths and weaknesses (sw): each club's three best and three worst process metrics, as percentile chips.
 *   5. Head to head (h2h): two clubs on the tale of the tape with the gap in percentile points (?a=, b=).
 *   6. Through the season (trend): the rolling 10-game 5v5 expected-goal share game by game (season.json ratings
 *      rolling) and our playoff chance day by day (race_log.json, this season) (?trend=, clubs=).
 *   7. Best lines (lines): the forward lines and defence pairs with the best 5v5 expected-goal share past a minutes
 *      floor (lab.json lines_forwards / lines_pairs, loaded when the section is reached) (?lt=).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);
const ST = { S: null, pw: 'division', grid: '', gadd: [], gsort: null, map: 0, mx: '', my: '', a: '', b: '', trend: 'xg', clubs: [], lt: '', go: '' };
let T = {}, IDS = [], RACE = null, SIM = {}, NSIM = 0, ROWS = {};
const K = () => RK.fk;

/* metrics: id -> [label, fmt, lower, tip, set] (set: the phase chip) */
const M = {
  rating: ['Our rating', 's2', false, 'Our team-strength model: goals a game better than an average club, all situations (last season’s prior fades as games come in).'],
  m_gf: ['Our goals for a game', 'f2', false, 'Goals a game our team-strength model expects the club to score against an average opponent.'],
  m_ga: ['Our goals against a game', 'f2', true, 'Goals a game our team-strength model expects the club to allow against an average opponent.'],
  fin: ['Finishing (our model)', 's3', false, 'Our model’s finishing term: how much more often the club’s chances go in than expected goals say, regressed.'],
  xgf_pct5: ['5v5 expected-goal share', 'pct', false, 'Share of the 5-on-5 expected goals the club gets: the number that best predicts the next games.'],
  cf_pct5: ['5v5 shot-attempt share', 'pct', false, 'Share of the 5-on-5 shot attempts (on goal, missed or blocked): puck possession.'],
  off5: ['5v5 attack (xGF/60)', 'f2', false, 'Expected goals created per 60 minutes at 5-on-5.'],
  def5: ['5v5 defence (xGA/60)', 'f2', true, 'Expected goals allowed per 60 minutes at 5-on-5 (lower is better).'],
  pp: ['Power play (xGF/60)', 'f2', false, 'Expected goals created per 60 minutes on the power play.'],
  pk: ['Penalty kill (xGA/60)', 'f2', true, 'Expected goals allowed per 60 minutes short-handed (lower is better).'],
  pp_pct: ['Power-play conversion', 'pct', false, 'Power-play goals per power-play opportunity.'],
  pk_pct: ['Penalty-kill success', 'pct', false, 'Share of the opponents’ power plays killed off.'],
  pp_toi_g: ['Power-play minutes a game', 'f1', false, 'Minutes a game on the power play: penalties drawn.'],
  pk_toi_g: ['Short-handed minutes a game', 'f1', true, 'Minutes a game short-handed: penalties taken (lower is better).'],
  goalie: ['Goaltending (GSAx/60)', 's3', false, 'Goals the club’s goalies saved above expected per 60 minutes.'],
  gsax: ['Goals saved above expected', 's1', false, 'Season total of goals the club’s goalies stopped beyond an average goalie on the same shots.'],
  finish: ['Goals above expected a game', 's2', false, 'Goals scored minus expected goals, per game: finishing (and luck).'],
  save: ['Goals saved a game', 's2', false, 'Expected goals against minus goals against, per game: goaltending (and luck).'],
  gf_g: ['Goals for a game', 'f2', false, 'Goals scored per game (shootout winners left out).'],
  ga_g: ['Goals against a game', 'f2', true, 'Goals allowed per game (lower is better).'],
  gd_g: ['Goal difference a game', 's2', false, 'Goals for minus goals against, per game.'],
  xgf_g: ['Expected goals for a game', 'f2', false, 'Expected goals created per game, all situations.'],
  xga_g: ['Expected goals against a game', 'f2', true, 'Expected goals allowed per game, all situations (lower is better).'],
  p_pct: ['Points %', 'pct', false, 'Standings points taken as a share of the points available.'],
  pts: ['Points', 'int', false, 'Two for a win, one for an overtime or shootout loss.'],
  p_playoffs: ['Our playoff chance', 'pct', false, 'Our chance of a playoff spot, from the season simulation.'],
  p_cup: ['Our Stanley Cup chance', 'pct', false, 'Our chance of winning the Cup, from the season simulation.']
};
const OURS = { rating: 1, m_gf: 1, m_ga: 1, fin: 1, p_playoffs: 1, p_cup: 1 };
const GRID_SETS = [
  ['overview', 'Overview', [['Ratings', ['rating', 'm_gf', 'm_ga']], ['Process', ['xgf_pct5', 'cf_pct5']], ['Results', ['p_pct', 'gd_g']], ['Chances', ['p_playoffs', 'p_cup']]]],
  ['ev', '5-on-5', [['Shares', ['xgf_pct5', 'cf_pct5']], ['Attack and defence', ['off5', 'def5']]]],
  ['st', 'Special teams', [['Power play', ['pp', 'pp_pct', 'pp_toi_g']], ['Penalty kill', ['pk', 'pk_pct', 'pk_toi_g']]]],
  ['gf', 'Goaltending and finishing', [['Goaltending', ['goalie', 'gsax', 'save']], ['Finishing', ['finish', 'fin']]]],
  ['res', 'Results', [['Goals', ['gf_g', 'ga_g', 'gd_g']], ['Expected goals', ['xgf_g', 'xga_g']], ['Standings', ['pts', 'p_pct']]]]
];
const SW_POOL = ['xgf_pct5', 'cf_pct5', 'off5', 'def5', 'pp', 'pk', 'pp_pct', 'pk_pct', 'goalie', 'finish', 'pp_toi_g', 'pk_toi_g', 'm_gf', 'm_ga'];
const H2H = [['Strength', ['rating', 'gd_g', 'xgf_pct5', 'cf_pct5']], ['5-on-5', ['off5', 'def5']], ['Special teams', ['pp', 'pk', 'pp_pct', 'pk_pct']], ['Goaltending and finishing', ['goalie', 'finish']], ['Results', ['p_pct', 'gf_g', 'ga_g']]];
const PRESETS = [
  ['Process against results', 'xgf_pct5', 'p_pct', { tl: 'Winning on luck?', tr: 'The real deal', bl: 'Struggling', br: 'Due a run' }],
  ['5v5 attack against defence', 'off5', 'def5', { tl: 'Lock it down', tr: 'Complete clubs', bl: 'Blunt and leaky', br: 'Run and gun' }],
  ['Power play against penalty kill', 'pp', 'pk', { tl: 'Kill first', tr: 'Special-teams aces', bl: 'Special-teams woes', br: 'Power play first' }],
  ['Shot volume against chance quality', 'cf_pct5', 'xgf_pct5', { tl: 'Quality over quantity', tr: 'Volume and quality', bl: 'Out-shot, out-chanced', br: 'Volume, little danger' }],
  ['Our rating against points', 'rating', 'p_pct', { tl: 'Winning on luck?', tr: 'The real deal', bl: 'Struggling', br: 'Due a run' }],
  ['Finishing against goaltending', 'finish', 'save', { tl: 'The goalie carries them', tr: 'Hot at both ends', bl: 'Cold at both ends', br: 'Finishers' }]
];
function fmtV(f, v) {
  if (!isNum(v)) return '—';
  if (f === 'pct') return U.pct(v, 1);
  if (f === 's1') return U.signed(v, 1);
  if (f === 's2') return U.signed(v, 2);
  if (f === 's3') return U.signed(v, 3);
  if (f === 'f1') return U.f(v, 1);
  if (f === 'int') return String(Math.round(v));
  return U.f(v, 2);
}
function meta(id) {
  const m = M[id] || [id, 'f2', false, ''];
  const ours = OURS[id] ? { name: 'Team-strength and season-simulation models' } : null;
  return { id: id, label: m[0], short: m[0], tip: m[3], lower: !!m[2], ours: ours, fmt: v => fmtV(m[1], v) };
}
function v(t, id) { const x = (T[t] || {})[id]; return isNum(x) ? x : null; }
function pc(t, id) {
  const xs = IDS.map(x => v(x, id)).filter(isNum).sort((a, b) => a - b), y = v(t, id);
  if (!isNum(y) || xs.length < 5) return null;
  const q = QK.pctRank(xs, y);
  return meta(id).lower ? 100 - q : q;
}
function rec(t) { const r = ROWS[t] || {}; return isNum(r.w) ? RK.record(r.w, r.l, r.otl) : '—'; }
function tinfo(t) { const i = RK.teamInfo(t) || {}; return { abbr: RK.teamAbbr(t), name: RK.teamName(t), short: RK.teamShort(t), colour: RK.teamColourRaw(t), alt: RK.teamAlt(t), conference: (ROWS[t] || {}).conference || i.conference || '', division: (ROWS[t] || {}).division || i.division || '' }; }
function thref(t) { return RK.teamHref(t, ST.S); }
function byRating(list) { return list.slice().sort((a, b) => (v(b, 'rating') || -9) - (v(a, 'rating') || -9)); }

/* season.json -> T[team] = flat metrics */
function build(d) {
  T = {}; ROWS = {};
  const rows = RK.seasonRows(d);
  rows.forEach(r => { ROWS[r.team] = r; });
  const R = d.ratings || {};
  SIM = (d.sim && d.sim.teams) || {}; NSIM = (d.sim && d.sim.n) || 0;
  Object.keys(R).forEach(t0 => {
    const t = RK.canonTeam(t0), u = (R[t0] || {}).units || {}, md = u.model || {}, r = ROWS[t] || {}, sm = SIM[t0] || SIM[t] || {};
    const o = { rating: isNum(u.rating) ? u.rating : r.rating, m_gf: md.gf_g, m_ga: md.ga_g, fin: md.fin, xgf_pct5: u.xgf_pct5, cf_pct5: u.cf_pct5, off5: u.off5, def5: u.def5, pp: u.pp, pk: u.pk,
      pp_pct: u.pp_pct, pk_pct: u.pk_pct, pp_toi_g: u.pp_toi_g, pk_toi_g: u.pk_toi_g, goalie: u.goalie, gsax: u.gsax, gf_g: u.gf_g, ga_g: u.ga_g, xgf_g: u.xgf_g, xga_g: u.xga_g,
      gd_g: isNum(u.gd_g) ? u.gd_g : (isNum(u.gf_g) && isNum(u.ga_g) ? u.gf_g - u.ga_g : null), p_pct: r.p_pct, pts: r.pts, gp: isNum(r.gp) ? r.gp : u.gp,
      p_playoffs: isNum(sm.p_playoffs) ? sm.p_playoffs : r.p_playoffs, p_cup: isNum(sm.p_cup) ? sm.p_cup : r.p_cup, mean_pts: sm.mean_pts, rolling: (R[t0] || {}).rolling || [] };
    o.finish = isNum(u.gf_g) && isNum(u.xgf_g) ? u.gf_g - u.xgf_g : null;
    o.save = isNum(u.ga_g) && isNum(u.xga_g) ? u.xga_g - u.ga_g : null;
    Object.keys(o).forEach(k => { if (o[k] === undefined) o[k] = null; });
    T[t] = o;
  });
  IDS = Object.keys(T).filter(t => isNum(v(t, 'rating')) || isNum(v(t, 'gp')));
  /* where the goal difference comes from: goals a game against an average club, per state, from the per-60 counts */
  const avg = id => { const xs = IDS.map(t => v(t, id)).filter(isNum); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; };
  const L = { off5: avg('off5'), def5: avg('def5'), pp: avg('pp'), pk: avg('pk') };
  IDS.forEach(t => {
    const o = T[t], ppm = isNum(o.pp_toi_g) ? o.pp_toi_g : 0, pkm = isNum(o.pk_toi_g) ? o.pk_toi_g : 0, evm = Math.max(30, 60 - ppm - pkm);
    o.parts = { ev_o: isNum(o.off5) && isNum(L.off5) ? (o.off5 - L.off5) * evm / 60 : null, ev_d: isNum(o.def5) && isNum(L.def5) ? (L.def5 - o.def5) * evm / 60 : null,
      pp: isNum(o.pp) && isNum(L.pp) ? (o.pp - L.pp) * ppm / 60 : null, pk: isNum(o.pk) && isNum(L.pk) ? (L.pk - o.pk) * pkm / 60 : null, g: isNum(o.goalie) ? o.goalie : null };
  });
}

/* ── address ─────────────────────────────────────────────────────────────── */
function readQ(q) {
  q = q || {};
  ST.pw = ['division', 'conference', 'all'].indexOf(q.pw) >= 0 ? q.pw : 'division';
  ST.grid = q.grid || ''; ST.gadd = q.gadd ? String(q.gadd).split(',').filter(Boolean) : [];
  ST.gsort = q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null;
  const mp = parseInt(q.map, 10); ST.map = isNaN(mp) ? 0 : mp; ST.mx = q.mx || ''; ST.my = q.my || '';
  if (ST.map < 0 && (!M[ST.mx] || !M[ST.my])) ST.map = 0;
  ST.a = q.a ? RK.canonTeam(q.a) : ''; ST.b = q.b ? RK.canonTeam(q.b) : ''; ST.trend = q.trend === 'po' ? 'po' : 'xg'; ST.clubs = q.clubs ? String(q.clubs).split(',').filter(Boolean).map(RK.canonTeam) : [];
  ST.lt = q.lt ? RK.canonTeam(q.lt) : ''; ST.go = q.go || (q.tab === 'stats' ? 'grid' : '');
}
function writeQ() {
  const q = {};
  if (ST.pw !== 'division') q.pw = ST.pw;
  if (ST.grid) q.grid = ST.grid;
  if (ST.gadd.length) q.gadd = ST.gadd.join(',');
  if (ST.gsort && ST.gsort.key && !(ST.gsort.key === 'rating' && ST.gsort.dir === 'desc')) { q.gsort = ST.gsort.key; q.gdir = ST.gsort.dir; }
  if (ST.map) q.map = ST.map;
  if (ST.map < 0) { q.mx = ST.mx; q.my = ST.my; }
  if (ST.a) q.a = ST.a;
  if (ST.b) q.b = ST.b;
  if (ST.trend !== 'xg') q.trend = ST.trend;
  if (ST.clubs.length) q.clubs = ST.clubs.join(',');
  if (ST.lt) q.lt = ST.lt;
  if (ST.S && ST.S !== RK.currentSeason()) q.s = ST.S;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  try { history.replaceState(null, '', '#/teams' + (qs ? '?' + qs : '')); } catch (e) { /* no history API */ }
}

/* ── render ──────────────────────────────────────────────────────────────── */
const SECS = [['tm-power', 'Power board', 'power'], ['tm-grid', 'Team profile', 'grid'], ['tm-map', 'Style map', 'map'], ['tm-sw', 'Strengths and weaknesses', 'sw'], ['tm-h2h', 'Head to head', 'h2h'], ['tm-trend', 'Through the season', 'trend'], ['tm-lines', 'Best lines', 'lines'], ['tm-inj', 'Who’s missing', 'injuries']];
function jump(id, smooth) {
  const t = document.getElementById(id);
  if (!t) return;
  const off = ['.qk-topbar', '.qk-secnav'].reduce((s, q) => s + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + 12;
  window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: smooth && !(QK.reducedMotion && QK.reducedMotion()) ? 'smooth' : 'auto' });
}
function render(el, params) {
  ST.S = Number(params.season) || RK.currentSeason();
  readQ(params.query || {});
  const body = U.section(el, { section: 'teams', title: 'Teams', sub: 'Every club ranked, profiled and set against the rest: our ratings, every team metric, how each club wins, strengths and weaknesses, head to head and the best lines.' });
  body.innerHTML = '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(s => '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[1]) + '</a>').join('') + '</div></nav>' +
    SECS.map(s => '<section class="qk-section tm-sec" id="' + s[0] + '">' + QK.skeleton('lines', 3) + '</section>').join('');
  body.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); jump(a.getAttribute('data-jump'), true); }));
  return Promise.all([RK.loadYear('season.json', ST.S), ST.S === RK.currentSeason() ? RK.load('race_log.json') : Promise.resolve(null)]).then(res => {
    if (!U.alive(el)) return;
    const d = res[0];
    if (!RK.ok(d) || !d.ratings) { body.innerHTML = QK.empty('Not built yet', 'The ' + RK.seasonLabel(ST.S) + ' season file is not available.'); return; }
    build(d);
    RACE = res[1] && res[1][String(ST.S)] ? res[1][String(ST.S)] : null;
    RK.setMeta('NHL ' + RK.seasonLabel(ST.S) + ' · ' + IDS.length + ' clubs · ' + Object.keys(M).length + ' team metrics');
    power(); grid(); styleMap(); strengths(); h2h(); trend(); lines();
    if (RK.injuryBoard) RK.injuryBoard(document.getElementById('tm-inj'), ST.S);
    const g = SECS.filter(s => s[2] === ST.go)[0];
    if (g) setTimeout(() => jump(g[0], false), 60);
  });
}
const early = () => IDS.every(t => (v(t, 'gp') || 0) < U.TEAM_MIN_GP);

/* 1. the power board */
function power() {
  const host = document.getElementById('tm-power');
  if (!host) return;
  const all = byRating(IDS);
  const rk = {}; all.forEach((t, i) => { rk[t] = i + 1; });
  const sim = NSIM > 0;
  const row = t => {
    const i = tinfo(t), o = T[t], r = ROWS[t] || {};
    return { rank: rk[t], name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + (r.streak ? ' · ' + r.streak : ''), value: o.rating, text: U.signed(o.rating, 2),
      parts: o.parts, cells: [{ label: 'Points', text: isNum(r.pts) ? String(r.pts) : '—' }, { label: 'Projected', text: isNum(o.mean_pts) ? String(Math.round(o.mean_pts)) : '—' },
        { label: 'Last 10', text: Array.isArray(r.l10) ? r.l10.join('-') : (r.l10 || '—') }],
      chances: sim ? [{ label: 'Playoffs', p: o.p_playoffs, text: o.p_playoffs === 1 ? 'In' : o.p_playoffs === 0 ? 'Out' : '' }].concat(o.p_playoffs === 0 ? [] : [{ label: 'Cup', p: o.p_cup }]) : [] };
  };
  let groups;
  if (ST.pw === 'all') groups = [{ label: '', rows: all.map(row) }];
  else {
    const keyOf = t => (ST.pw === 'conference' ? tinfo(t).conference : tinfo(t).division) || '';
    const names = Array.from(new Set(all.map(keyOf))).sort((a, b) => (RK.DIVISIONS.indexOf(a) - RK.DIVISIONS.indexOf(b)) || a.localeCompare(b));
    groups = names.map(n => ({ label: n ? n + (ST.pw === 'conference' ? ' Conference' : '') : 'Clubs', rows: all.filter(t => keyOf(t) === n).map(row) }));
  }
  const seg = '<div class="qk-seg" id="tm-pw" role="group" aria-label="Group the board">' + [['division', 'Division'], ['conference', 'Conference'], ['all', 'All ' + IDS.length]].map(x => '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (ST.pw === x[0]) + '">' + x[1] + '</button>').join('') + '</div>';
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: 'Every club, ranked by our rating', sub: 'Our rating is how many goals a game better than an average club we think each team is. The bar shows where this season’s goal difference comes from: 5-on-5 attack and defence, the power play, the penalty kill and goaltending, in goals a game against an average club. The volt tick is our rating.' + (sim ? ' Playoff and Cup chances come from ' + QK.fmt.num(NSIM) + ' simulated seasons.' : ''), actions: seg }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(null, { groups: groups, valueLabel: 'Our rating', unit: 'goals a game against an average club', key: true,
      parts: [{ key: 'ev_o', label: '5v5 attack', color: 'var(--c-2)' }, { key: 'ev_d', label: '5v5 defence', color: 'var(--c-3)' }, { key: 'pp', label: 'Power play', color: 'var(--c-5)' }, { key: 'pk', label: 'Penalty kill', color: 'var(--c-6)' }, { key: 'g', label: 'Goaltending', color: 'var(--c-7)' }] }) + '</div></div>' +
    QK.explain('A <b>rating of +0.50</b> means the club outscores an average opponent by half a goal a game: over 84 games that is about 20 points in the standings. The bar is this season’s process (expected goals, plus what the goalies saved); the rating also weighs last season and how chances turn into goals, so the two can differ' + (early() ? ', most of all in the first weeks' : '') + '. The full table is on <a class="qk-link" href="' + esc(RK.standingsHref(ST.S)) + '">Standings</a>.', { title: 'What’s that number?', html: true });
  const sg = document.getElementById('tm-pw');
  if (sg) QK.seg(sg, x => { ST.pw = x; writeQ(); power(); });
}

/* 2. the team profile grid */
function grid() {
  const host = document.getElementById('tm-grid');
  if (!host) return;
  const have = id => IDS.some(t => isNum(v(t, id)));
  const sets = GRID_SETS.map(s => ({ key: s[0], label: s[1], groups: s[2].map(g => ({ label: g[0], ids: g[1].filter(have) })).filter(g => g.ids.length) })).filter(s => s.groups.length);
  const ours = Object.keys(OURS).filter(have);
  if (ours.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: ours }] });
  const rows = byRating(IDS).map(t => { const i = tinfo(t); return { id: t, name: i.name, sub: rec(t) + ' · ' + i.division, mark: { abbr: i.abbr, colour: i.colour }, href: thref(t) }; });
  const addable = Object.keys(M).filter(have).map(id => '<option value="' + esc(id) + '">' + esc(M[id][0]) + '</option>').join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: IDS.length + ' clubs, every metric', sub: 'Each cell is the club’s value, coloured by its percentile among the ' + IDS.length + ' (blue worst, red best; a ↓ marks a metric where lower is better). Pick a phase, add any metric, sort by any column, tap a club for its page.' + (early() ? ' Early in the season ranks move a lot: a team metric needs 10 to 50 games to settle.' : '') }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(s => s.key === ST.grid) ? ST.grid : 'overview', setsLabel: 'Phase', added: ST.gadd.filter(have), sort: ST.gsort || { key: 'rating', dir: 'desc' },
    nameLabel: 'Club', subLabel: 'Record · division', noun: 'clubs', meta: meta, addable: addable,
    rows: rows, val: (r, id) => v(r.id, id),
    csv: 'rink-' + ST.S + '-teams.csv',
    onState: st => { ST.grid = st.set === 'overview' ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; writeQ(); }
  });
}

/* 3. the style map */
function styleMap() {
  const host = document.getElementById('tm-map');
  if (!host) return;
  const opts = Object.keys(M).filter(id => IDS.some(t => isNum(v(t, id)))).map(id => ({ value: id, label: M[id][0] }));
  const P = PRESETS.filter(p => IDS.filter(t => isNum(v(t, p[1])) && isNum(v(t, p[2]))).length >= 5);
  if (ST.map >= P.length) ST.map = 0;
  const cur = ST.map >= 0 ? P[ST.map] : null;
  const x = cur ? cur[1] : (ST.mx || 'off5'), y = cur ? cur[2] : (ST.my || 'def5');
  const sel = (id, val) => '<select class="qk-select" id="' + id + '">' + opts.map(o => '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>').join('') + '</select>';
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each club wins', sub: 'Any two team metrics against each other. The dashed lines are the league medians; better is always up and to the right (axes where less is better are flipped). Tap a club for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map((p, i) => '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p[0]) + '</option>').join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:520px;margin-top:16px" role="img" aria-label="Style map"></div><p class="rk-note" id="tm-map-n"></p></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-preset').onchange = e => { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } writeQ(); styleMap(); };
  $('tm-mx').onchange = e => { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; writeQ(); styleMap(); };
  $('tm-my').onchange = e => { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; writeQ(); styleMap(); };
  const mx = meta(x), my = meta(y);
  const pts = IDS.filter(t => isNum(v(t, x)) && isNum(v(t, y))).map(t => { const i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name + ' · ' + rec(t), label: i.abbr, color: i.colour || null, size: 15, href: thref(t) }; });
  const med = a => K().median(a);
  const corners = cur ? cur[3] : { tl: '', tr: 'Better on both', bl: 'Worse on both', br: '' };
  const pf = m => (M[m.id] && M[m.id][1] === 'pct' ? (q => Math.round(q * 100) + '%') : m.fmt);
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: med(pts.map(p => p.x)), refY: med(pts.map(p => p.y)), xInverse: mx.lower, yInverse: my.lower, pad: '9%',
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: pf(mx), yFmt: pf(my),
    quadrants: [corners.tl, corners.tr, corners.bl, corners.br], label: my.label + ' against ' + mx.label });
  $('tm-map-n').innerHTML = '<b>' + esc(mx.label) + '</b>: ' + esc(mx.tip) + ' <b>' + esc(my.label) + '</b>: ' + esc(my.tip);
}
/* 4. strengths and weaknesses */
function strengths() {
  const host = document.getElementById('tm-sw');
  if (!host) return;
  const pool = SW_POOL.filter(id => IDS.some(t => isNum(v(t, id))));
  const cards = byRating(IDS).map(t => {
    const i = tinfo(t);
    const xs = pool.map(id => ({ id: id, p: pc(t, id) })).filter(o => isNum(o.p));
    const chip = o => { const m = meta(o.id); return { label: m.label, pctl: o.p, text: m.fmt(v(t, o.id)), tip: m.tip }; };
    const best = xs.slice().sort((a, b) => b.p - a.p).slice(0, 3).map(chip), worst = xs.slice().sort((a, b) => a.p - b.p).slice(0, 3).map(chip);
    return QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + ' · rating ' + U.signed(v(t, 'rating'), 2), best: best, worst: worst });
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each club does best, and worst', sub: 'Each club’s three best and three worst of ' + pool.length + ' process metrics and ratings, as percentiles among the ' + IDS.length + ' clubs (100 = best). Ordered by our rating.' }) +
    '<div class="qk-sw-grid">' + cards + '</div>';
}

/* 5. head to head */
function h2h() {
  const host = document.getElementById('tm-h2h');
  if (!host) return;
  const list = byRating(IDS);
  if (!T[ST.a]) ST.a = list[0];
  if (!T[ST.b] || ST.b === ST.a) ST.b = list.filter(t => t !== ST.a)[0];
  const opt = cur => list.slice().sort((a, b) => tinfo(a).name.localeCompare(tinfo(b).name)).map(t => '<option value="' + esc(t) + '"' + (t === cur ? ' selected' : '') + '>' + esc(tinfo(t).name) + '</option>').join('');
  const A = tinfo(ST.a), B = tinfo(ST.b);
  const groups = H2H.map(g => ({ label: g[0], rows: g[1].map(id => {
    const m = meta(id);
    return { label: m.label, tip: m.tip, a: v(ST.a, id), b: v(ST.b, id), ta: m.fmt(v(ST.a, id)), tb: m.fmt(v(ST.b, id)), pa: pc(ST.a, id), pb: pc(ST.b, id), better: m.lower ? 'low' : 'high' };
  }) }));
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: A.short + ' or ' + B.short + '?', sub: 'Two clubs on the numbers that decide games. Bars are percentiles among the ' + list.length + ' clubs; the small line under each metric is the gap in percentile points and who leads it.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Club', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: rec(ST.a) + ' · ' + U.signed(v(ST.a, 'rating'), 2), colour: A.colour, alt: A.alt, href: thref(ST.a) },
      right: { name: B.name, short: B.abbr, sub: rec(ST.b) + ' · ' + U.signed(v(ST.b, 'rating'), 2), colour: B.colour, alt: B.alt, href: thref(ST.b) }, groups: groups, wins: true, gap: true }) + '</div></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-a').onchange = e => { ST.a = e.target.value; writeQ(); h2h(); };
  $('tm-b').onchange = e => { ST.b = e.target.value; writeQ(); h2h(); };
  $('tm-swap').onclick = () => { const t = ST.a; ST.a = ST.b; ST.b = t; writeQ(); h2h(); };
}

/* 6. through the season: the rolling 10-game 5v5 xG share game by game; our playoff chance day by day (this season) */
function trend() {
  const host = document.getElementById('tm-trend');
  if (!host) return;
  const list = byRating(IDS);
  const roll = t => (T[t].rolling || []).filter(r => Array.isArray(r) && isNum(r[2]));
  if (!list.some(t => roll(t).length)) { host.innerHTML = ''; return; }
  const ps = RACE && RACE.p_playoffs ? RACE.p_playoffs : null;
  if (ST.trend === 'po' && !ps) ST.trend = 'xg';
  let clubs = ST.clubs.filter(t => T[t]);
  if (!clubs.length) { const dv = tinfo(list[0]).division; clubs = list.filter(t => tinfo(t).division === dv); if (clubs.length < 2) clubs = list.slice(0, 5); }
  const chips = list.slice().sort((a, b) => tinfo(a).abbr.localeCompare(tinfo(b).abbr)).map(t => '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '">' + esc(tinfo(t).abbr) + '</button>').join('');
  const divs = RK.DIVISIONS.filter(d => list.some(t => tinfo(t).division === d));
  const seg = ps ? '<div class="qk-seg" id="tm-tr" role="group" aria-label="Measure"><button type="button" data-value="xg" aria-pressed="' + (ST.trend === 'xg') + '">5v5 chance share</button><button type="button" data-value="po" aria-pressed="' + (ST.trend === 'po') + '">Playoff chance</button></div>' : '';
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: ST.trend === 'po' ? 'The race, day by day' : 'Form, game by game', sub: ST.trend === 'po' ? 'Our playoff chance for each club on each day of the season, from the season simulation as it stood that day.' : 'Each club’s share of the 5-on-5 expected goals over its last 10 games, game by game. Above 50% the club is out-chancing its opponents.', actions: seg }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">Clubs</span><div class="qk-chips">' + chips + '</div>' +
    (divs.length ? '<div class="qk-chips tm-divs">' + divs.map(d => '<button type="button" class="qk-chip" data-div="' + esc(d) + '">' + esc(d) + '</button>').join('') + '<button type="button" class="qk-chip" data-div="*top">Top five</button></div>' : '') +
    '</div><div id="tm-tr-c" class="qk-chart" style="--h:460px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  const T0 = QKC.tokens();
  const used = [];
  const colOf = (t, i) => { let c = tinfo(t).colour; c = c && QK.color.parse(c) ? QK.color.team(c) : T0.cat[i % 8]; if (used.some(u => !QK.color.distinct(u, c))) { const al = tinfo(t).alt; const c2 = al && QK.color.parse(al) ? QK.color.team(al) : null; c = c2 && !used.some(u => !QK.color.distinct(u, c2)) ? c2 : T0.cat[i % 8]; } used.push(c); return c; };
  if (ST.trend === 'po') {
    const dates = Object.keys(ps).filter(d => /^\d{4}-/.test(d)).sort();
    QKC.line(document.getElementById('tm-tr-c'), { x: dates.map(d => QK.fmt.date(d + 'T12:00:00', { day: 'numeric', month: 'short' })), series: clubs.map((t, i) => ({ name: tinfo(t).abbr, color: colOf(t, i), data: dates.map(d => { const p = (ps[d] || {})[t]; return isNum(p) ? Math.round(p * 1000) / 10 : null; }) })),
      yName: 'Playoff chance (%)', xName: 'Date', yMin: 0, yMax: 100, yFmt: x => x + '%', endLabels: true, label: 'Our playoff chance by day' });
  } else {
    const series = clubs.map((t, i) => ({ name: tinfo(t).abbr, color: colOf(t, i), data: roll(t).map(r => [r[0], Math.round(r[2] * 1000) / 10]) }));
    const n = Math.max.apply(null, series.map(x => x.data.length).concat([1]));
    QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', x: Array.from({ length: n }, (_, j) => j + 1), series: series, yName: '5v5 xG share, last 10 games (%)', xName: 'Games played', xMin: 1, xMax: Math.max(2, n), yFmt: x => x + '%', ref: { y: 50, label: 'Even' }, endLabels: true, label: 'Rolling 5v5 expected-goal share' });
  }
  host.querySelectorAll('[data-club]').forEach(b => b.addEventListener('click', () => {
    const t = b.getAttribute('data-club'), cur = clubs.slice(), i = cur.indexOf(t);
    if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else if (cur.length < 8) cur.push(t);
    ST.clubs = cur; writeQ(); trend();
  }));
  host.querySelectorAll('[data-div]').forEach(b => b.addEventListener('click', () => {
    const d = b.getAttribute('data-div');
    ST.clubs = d === '*top' ? list.slice(0, 5) : list.filter(t => tinfo(t).division === d);
    writeQ(); trend();
  }));
  const sg = document.getElementById('tm-tr');
  if (sg) QK.seg(sg, x => { ST.trend = x; writeQ(); trend(); });
}

/* 7. the best lines: forward lines and defence pairs by 5v5 expected-goal share past a minutes floor (lab.json) */
function lines() {
  const host = document.getElementById('tm-lines');
  if (!host) return;
  host.innerHTML = QK.sectionHead({ kicker: 'Best lines', title: 'The units that tilt the ice', sub: 'Forward lines and defence pairs together at 5-on-5, by their share of the expected goals. A unit needs real minutes to count: the floor grows with the season.' }) + '<div id="tm-lines-b">' + QK.skeleton('lines', 4) + '</div>';
  const go = () => RK.loadYear('lab.json', ST.S).then(d => {
    const box = document.getElementById('tm-lines-b');
    if (!box || !U.alive(box)) return;
    const L = RK.ok(d) ? d : {};
    const unit = X => (X && Array.isArray(X.ids) ? X.ids.map((id, i) => { const o = { ids: String(id).split('-'), team: (X.team || [])[i], names: (X.names || [])[i] || [] }; Object.keys(X.data || {}).forEach(c => { o[c] = X.data[c][i]; }); return o; }) : []);
    const F = unit(L.lines_forwards), P = unit(L.lines_pairs);
    if (!F.length && !P.length) { box.innerHTML = QK.empty('No lines yet', 'Line combinations come from the shift charts (2010-11 on).'); return; }
    const gp = Math.max.apply(null, IDS.map(t => v(t, 'gp') || 0).concat([1]));
    const floorF = Math.max(20, Math.round(150 * Math.min(1, gp / 82))), floorP = Math.max(20, Math.round(200 * Math.min(1, gp / 82)));
    const teams = Array.from(new Set(F.concat(P).map(x => x.team).filter(Boolean))).sort((a, b) => RK.teamName(a).localeCompare(RK.teamName(b)));
    const tbl = (list, floor, noun) => {
      const rows = list.filter(x => isNum(x.toi) && x.toi >= floor && isNum(x.xgf_pct) && (!ST.lt || x.team === ST.lt)).sort((a, b) => b.xgf_pct - a.xgf_pct).slice(0, ST.lt ? 12 : 15);
      if (!rows.length) return QK.empty('No ' + noun + ' past the floor', 'The floor is ' + floor + ' minutes together at 5-on-5.');
      return '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>#</th><th>' + (noun === 'lines' ? 'Line' : 'Pair') + '</th><th>Club</th><th class="num">Minutes</th><th class="num" data-tip="Share of the 5v5 expected goals with the unit on the ice">xGF%</th><th class="num">xGF/60</th><th class="num">xGA/60</th><th class="num" data-tip="Share of the 5v5 shot attempts">CF%</th><th class="num">Goals</th></tr></thead><tbody>' +
        rows.map((x, i) => '<tr><td class="num">' + (i + 1) + '</td><td>' + x.ids.map((id, j) => RK.playerLink(id, { name: RK.surnameOf(x.names[j] || RK.playerName(id)) })).join(' · ') + '</td><td>' + U.teamEnt(x.team, { abbr: true, season: ST.S }) + '</td><td class="num">' + U.f(x.toi, 0) + '</td>' +
          '<td class="num"><b>' + U.pct(x.xgf_pct, 1) + '</b></td><td class="num">' + U.f(x.xgf60, 2) + '</td><td class="num">' + U.f(x.xga60, 2) + '</td><td class="num">' + U.pct(x.cf_pct, 1) + '</td><td class="num">' + (isNum(x.gf) ? x.gf + '–' + x.ga : '—') + '</td></tr>').join('') + '</tbody></table></div>';
    };
    box.innerHTML = '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Club', html: '<select class="qk-select" id="tm-lt"><option value="">Every club</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === ST.lt ? ' selected' : '') + '>' + esc(RK.teamName(t)) + '</option>').join('') + '</select>' }]) + '</div></div>' +
      '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-7">' + U.card2('Forward lines', floorF + '+ minutes together at 5-on-5', tbl(F, floorF, 'lines'), { flush: true }) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Defence pairs', floorP + '+ minutes together at 5-on-5', tbl(P, floorP, 'pairs'), { flush: true }) + '</div></div>' +
      QK.explain('<b>Why expected goals?</b> Over a few hundred minutes a unit’s goal count is mostly luck; its share of the chances settles faster and says more about the next games. Each club’s own lines are on its team page.', { html: true });
    const s = document.getElementById('tm-lt');
    if (s) s.onchange = e => { ST.lt = e.target.value; writeQ(); go(); };
    if (QK.tooltips) QK.tooltips();
  });
  if (ST.go === 'lines' || !window.IntersectionObserver) go();
  else { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '300px' }); io.observe(host); }
}

RK.page('teams', render);
})(window.RK);
