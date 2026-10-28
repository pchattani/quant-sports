/* The Quant Hardwood — the Teams page (#/<L>/teams), round 9 (28 Oct 2026; the Bullpen pilot bp-teams.js is the
 * reference): every team ranked, profiled and set against the rest. It replaces the tile list and the "Team stats"
 * catalogue table (?tab=stats opens the profile grid); team pages (#/<L>/team/<tid>) stay in hw-team.js. Kit: scout.js
 * (QK.powerBars, QK.heatGrid, QK.strengths), quant.js (QK.tape with gap: true), quant-charts.js (QKC.scatter, QKC.line).
 *
 * Sections (a chip strip jumps between them):
 *   1. Power board: each team ranked by our net rating (opponent-adjusted points per 100 possessions), the bar split
 *      into offence (points scored per 100 above the league) and defence (points kept off per 100 below it), the
 *      record, the raw net rating, projected wins, the last ten and our playoff and title chances, quiet; Conference |
 *      Division | All (?pw=).
 *   2. Team profile: the heat grid of teams by every team metric in teams.json (phase chips: Overview, Ratings, Record,
 *      Four factors, Shooting, Shot quality, Possessions, Clutch, Rotation, Context, Projections), percentile cells,
 *      sortable, rows linked, any metric added, CSV (?grid=, gadd=, gsort=).
 *   3. Style map: any two team metrics, presets with the corners named (offence against defence, pace against
 *      efficiency, three-point rate against rim rate, offensive rebounding against ball security, our rating against
 *      the record) (?map=, mx=, my=). The site's one offence-v-defence team scatter lives here.
 *   4. Strengths and weaknesses: each team's three best and three worst process metrics, as percentile chips.
 *   5. Head to head: two teams on the tale of the tape with the gap in percentile points (?a=, b=).
 *   6. Through the season: our net rating after every game (teams.json rating_path), the point differential added
 *      up game by game (the game log) and, for the current season, our playoff chance day by day (race_log.json)
 *      (?trend=net|pd|po, clubs=).
 *   7. Who's missing (round 9, Phase 4; current season): the injury and availability board. Each team's availability
 *      term for its next game (the informed game model: points of its own margin from who is expected to play, against
 *      what its rating already reflects; schedule.json model.av), and every player on ESPN's injury report with the
 *      points per 100 possessions the team loses without him ((projected rate − replacement) × minutes / 48) and his
 *      four-season value (valuation.json inj, rate, mpg, v).
 * Percentiles are the payload's (teams.json "pct", 100 = best, lower-is-better flipped), else ranked among the teams.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const U = () => HW.ui;
const esc = HW.esc, isNum = HW.isNum;

const ST = { L: 'nba', S: null, pw: 'conf', grid: '', gadd: [], gsort: null, map: 0, mx: '', my: '', a: '', b: '', trend: 'net', clubs: [] };
let T = null, META = {}, MS = [], SEA = null, RACE = null, LORTG = null;
const HIDE = { model_se: 1, title_edge: 1, p_title_market: 1, net_7d_change: 1 };

const OVERVIEW = [['Our ratings', ['model_net', 'model_off', 'model_def', 'pace']], ['Four factors, offence', ['efg', 'tov_pct', 'orb_pct', 'ftr']], ['Four factors, defence', ['opp_efg', 'opp_tov_pct', 'drb_pct', 'opp_ftr']], ['Record', ['win_pct', 'mov', 'pyth_wins', 'luck']]];
const SW_POOL = ['model_off', 'model_def', 'efg', 'tov_pct', 'orb_pct', 'ftr', 'opp_efg', 'opp_tov_pct', 'drb_pct', 'opp_ftr', 'fg3', 'fg2', 'ft', 'ast_rate', 'stl_pct', 'blk_pct',
  'xpps', 'pox100', 'opp_xpps', 'opp_pox100', 'tr_ppp', 'hc_ppp', 'ato_ppp', 'clutch_net', 'depth', 'best_lineup_net', 'home_net', 'away_net', 'b2b_net'];
const H2H = [['Strength', ['model_net', 'model_off', 'model_def', 'net', 'mov', 'elo']], ['Four factors', ['efg', 'tov_pct', 'orb_pct', 'ftr', 'opp_efg', 'opp_tov_pct', 'drb_pct', 'opp_ftr']],
  ['Shots', ['xpps', 'pox100', 'opp_xpps', 'fg3', 'tpar', 'rim_freq']], ['Style and depth', ['pace', 'tr_share', 'depth', 'clutch_net']]];
/* [label, x, y, corners { tl, tr, bl, br }]: better is up and to the right (lower-is-better axes are flipped) */
const PRESETS = [
  ['Offence against defence', 'model_off', 'model_def', { tl: 'Defence first', tr: 'Two-way teams', bl: 'Rebuilding', br: 'Score to win' }],
  ['Pace against efficiency', 'pace', 'model_off', { tl: 'Slow and sharp', tr: 'Fast and sharp', bl: 'Slow and stuck', br: 'Fast, little to show' }],
  ['Three-point rate against rim rate', 'tpar', 'rim_freq', { tl: 'Paint first', tr: 'Rim and three', bl: 'Mid-range heavy', br: 'Let it fly' }],
  ['Offensive rebounding against ball security', 'orb_pct', 'tov_pct', { tl: 'Careful, one shot', tr: 'Extra possessions', bl: 'Wasteful', br: 'Crash, then cough it up' }],
  ['Our rating against the record', 'model_net', 'win_pct', { tl: 'Winning on luck?', tr: 'The real deal', bl: 'Struggling', br: 'Due a run' }]
];

function label(id) {
  const m = META[id] || { label: id };
  const mm = U().MSET && U().MSET.meta[id];
  return (HW.ours ? HW.ours.label(id, mm ? mm[0] : m.label || id, 'team') : (mm ? mm[0] : m.label || id)).replace(/ \(ours\)$/, '');
}
function meta(id) {
  const m = META[id] || {};
  const mm = U().MSET && U().MSET.meta[id];
  const ours = HW.ours ? HW.ours.of(id) : null;
  const tip = (mm && mm[4]) || m.desc || '';
  return { id: id, label: label(id), short: label(id), tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''), lower: !!m.lower, style: !!(mm && mm[3]) || id === 'pace' || id === 'tpar' || id === 'rim_freq',
    ours: ours ? { name: ours.name, about: ours.about } : null, fmt: v => HW.fmtVal(v, m.fmt || (mm ? mm[2] : '1')) };
}
function v(t, id) { const x = ((T[t] || {}).values || {})[id]; return isNum(x) ? x : null; }
function pc(t, id) {
  const p = ((T[t] || {}).pct || {})[id];
  if (isNum(p)) return p;
  const xs = ids().map(x => v(x, id)).filter(isNum).sort((a, b) => a - b), y = v(t, id);
  if (!isNum(y) || xs.length < 5) return null;
  const q = QK.pctRank(xs, y);
  return meta(id).lower ? 100 - q : q;
}
function stRow(t) {
  const st = (SEA && SEA.standings) || {};
  let out = null;
  Object.keys(st).forEach(c => (st[c] || []).forEach(r => { if (String(r.team) === String(t)) out = Object.assign({ conf: c }, r); }));
  return out || {};
}
function rec(t) { const r = stRow(t); const w = isNum(r.w) ? r.w : v(t, 'w'), l = isNum(r.l) ? r.l : v(t, 'l'); return isNum(w) && isNum(l) ? w + '–' + l : '—'; }
function tinfo(t) { const x = T[t] || {}; return { abbr: x.abbr || HW.teamAbbr(ST.L, t), name: x.name || HW.teamName(ST.L, t), short: x.short || HW.teamShort(ST.L, t), colour: x.colour || HW.teamColourRaw(ST.L, t), alt: HW.teamAlt(ST.L, t), conf: x.conference || stRow(t).conf || '', division: x.division || stRow(t).division || '' }; }
function thref(t) { return HW.teamHref(ST.L, t, ST.S); }
function ids() { return Object.keys(T).filter(t => isNum(v(t, 'model_net')) || isNum(v(t, 'w'))); }
function rating(t) { const r = ((SEA && SEA.ratings) || {})[t] || {}; return isNum(r.net) ? r.net : v(t, 'model_net'); }
function byRating(list) { return list.slice().sort((a, b) => (isNum(rating(b)) ? rating(b) : -99) - (isNum(rating(a)) ? rating(a) : -99)); }
function sim() { return HW.simTeams ? HW.simTeams(SEA) : {}; }

function readQ(q) {
  q = q || {};
  ST.pw = ['conf', 'div', 'all'].indexOf(q.pw) >= 0 ? q.pw : (ST.L === 'wnba' ? 'all' : 'conf');
  ST.grid = q.grid || (q.tab === 'stats' ? 'Ratings' : ''); ST.gadd = q.gadd ? String(q.gadd).split(',').filter(Boolean) : [];
  ST.gsort = q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null;
  const mp = parseInt(q.map, 10); ST.map = isNaN(mp) ? 0 : mp; ST.mx = q.mx || ''; ST.my = q.my || '';
  ST.a = q.a || ''; ST.b = q.b || ''; ST.trend = ['net', 'pd', 'po'].indexOf(q.trend) >= 0 ? q.trend : 'net'; ST.clubs = q.clubs ? String(q.clubs).split(',').filter(Boolean) : [];
  ST.jump = q.tab === 'stats' ? 'tm-grid' : (q.a || q.b ? 'tm-h2h' : '');
}
function writeQ() {
  const q = {};
  if (ST.pw !== (ST.L === 'wnba' ? 'all' : 'conf')) q.pw = ST.pw;
  if (ST.grid) q.grid = ST.grid;
  if (ST.gadd.length) q.gadd = ST.gadd.join(',');
  if (ST.gsort && ST.gsort.key && !(ST.gsort.key === 'model_net' && ST.gsort.dir === 'desc')) { q.gsort = ST.gsort.key; q.gdir = ST.gsort.dir; }
  if (ST.map) q.map = ST.map;
  if (ST.map < 0) { q.mx = ST.mx; q.my = ST.my; }
  if (ST.a) q.a = ST.a;
  if (ST.b) q.b = ST.b;
  if (ST.trend !== 'net') q.trend = ST.trend;
  if (ST.clubs.length) q.clubs = ST.clubs.join(',');
  if (ST.S && Number(ST.S) !== Number(HW.currentSeason(ST.L))) q.s = ST.S;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  try { history.replaceState(null, '', '#/' + ST.L + '/teams' + (qs ? '?' + qs : '')); } catch (e) { /* no history API */ }
}

const SECS = [['tm-power', 'Power board'], ['tm-grid', 'Team profile'], ['tm-map', 'Style map'], ['tm-sw', 'Strengths and weaknesses'], ['tm-h2h', 'Head to head'], ['tm-trend', 'Through the season'], ['tm-inj', 'Who’s missing']];
let VAL = null, SCHED = null;
function render(el, params) {
  ST.L = U().L(params);
  ST.S = U().S(params);
  readQ(params.query || {});
  el.innerHTML = U().secHead('Teams', 'Every team ranked by our rating, profiled on every metric we keep, set against the rest and against each other. Open a team for its page.', null, null, U().kicker(ST.L, ST.S)) +
    '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(s => '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[1]) + '</a>').join('') + '</div></nav>' +
    SECS.map(s => '<section class="qk-section tm-sec" id="' + s[0] + '">' + QK.skeleton('lines', 3) + '</section>').join('');
  const jump = id => {
    const t = document.getElementById(id);
    if (!t) return;
    const off = ['.qk-topbar', '.qk-secnav'].reduce((s, q) => s + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + 56;
    window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: 'auto' });
  };
  el.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); jump(a.getAttribute('data-jump')); }));
  const cur = U().isCur(ST.L, ST.S);
  return Promise.all([HW.load(HW.path('teams.json', ST.L, ST.S)), HW.load(HW.path('season.json', ST.L, ST.S)), HW.load(HW.lpath('race_log.json', ST.L)), HW.ours ? HW.ours.load() : null,
    cur ? HW.load(HW.path('valuation.json', ST.L, ST.S)) : null, cur ? HW.load(HW.path('schedule.json', ST.L, ST.S)) : null]).then(res => {
    if (!U().alive(el)) return;
    const cat = res[0];
    if (!cat || cat.ok === false || !cat.teams || !Object.keys(cat.teams).length) {
      SECS.forEach(s => { const h = document.getElementById(s[0]); if (h) h.innerHTML = ''; });
      document.getElementById('tm-power').innerHTML = QK.empty('Not built yet', 'The ' + HW.leagueName(ST.L) + ' ' + HW.seasonLabel(ST.L, ST.S) + ' team file is not available.');
      return;
    }
    T = cat.teams; MS = (cat.metrics || []).filter(m => !HIDE[m.key]);
    META = {}; MS.forEach(m => { META[m.key] = m; });
    SEA = res[1] && res[1].ok !== false ? res[1] : null;
    LORTG = SEA && isNum(SEA.league_ortg) ? SEA.league_ortg : null;
    const rl = res[2] && res[2].ok !== false ? res[2] : null;
    RACE = rl && rl[String(ST.S)] ? rl[String(ST.S)] : null;
    VAL = res[4] && res[4].ok !== false ? res[4] : null; SCHED = res[5] && res[5].ok !== false ? res[5] : null;
    HW.setMeta(HW.leagueName(ST.L) + ' ' + HW.seasonLabel(ST.L, ST.S) + ' · ' + ids().length + ' teams · ' + MS.length + ' team metrics');
    [power, grid, styleMap, strengths, h2h, trend, injuries].forEach(f => { try { f(); } catch (e) { console.error(e); } });
    if (ST.jump) setTimeout(() => jump(ST.jump), 60);
  });
}

/* 1. the power board */
function power() {
  const host = document.getElementById('tm-power');
  if (!host) return;
  const all = byRating(ids()), sm = sim(), R = (SEA && SEA.ratings) || {};
  const rk = {}; all.forEach((t, i) => { rk[t] = i + 1; });
  const open = Object.keys(sm).some(t => isNum(sm[t].w_p05) && sm[t].w_p95 > sm[t].w_p05);
  const form = t => ((T[t] || {}).log || []).filter(g => g.res === 'W' || g.res === 'L').slice(-10).map(g => g.res).join('');
  const row = t => {
    const i = tinfo(t), r = R[t] || {}, s = sm[t] || {};
    const off = isNum(r.off) && isNum(LORTG) ? r.off - LORTG : null, def = isNum(r.def) && isNum(LORTG) ? LORTG - r.def : null;
    return { rank: rk[t], name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + (stRow(t).streak ? ' · ' + stRow(t).streak : ''), value: rating(t), text: U().signed(rating(t), 1),
      parts: { off: off, def: def },
      cells: [{ label: 'Raw net', text: isNum(v(t, 'net')) ? U().signed(v(t, 'net'), 1) : '—' }, { label: open ? 'Proj W' : 'Pyth W', text: open && isNum(s.exp_w) ? U().f(s.exp_w, 1) : (isNum(v(t, 'pyth_wins')) ? U().f(v(t, 'pyth_wins'), 1) : '—') }],
      form: form(t), chances: open ? [{ label: 'Playoffs', p: s.p_playoffs }, { label: 'Title', p: s.p_title }] : [] };
  };
  let groups;
  if (ST.pw === 'all') groups = [{ label: '', rows: all.map(row) }];
  else {
    const keyOf = t => (ST.pw === 'div' ? tinfo(t).division : tinfo(t).conf) || '';
    const names = Array.from(new Set(all.map(keyOf))).sort((a, b) => a.localeCompare(b));
    groups = names.map(n => ({ label: n || 'Teams', rows: all.filter(t => keyOf(t) === n).map(row) }));
  }
  const segs = ST.L === 'wnba' ? [['all', 'All ' + all.length], ['conf', 'Conference']] : [['conf', 'Conference'], ['div', 'Division'], ['all', 'All ' + all.length]];
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: 'Every team, ranked by our rating', sub: 'Our net rating is the points per 100 possessions a team is better than an average one, adjusted for opponents and home court. The bar splits it into offence (points scored per 100 above the league’s ' + (isNum(LORTG) ? U().f(LORTG, 1) : 'average') + ') and defence (points kept off per 100); the volt tick is the total.' + (open ? ' Playoff and title chances come from ' + Number((SEA.sim || {}).n_sims || 20000).toLocaleString('en-GB') + ' simulated seasons.' : ''),
    actions: '<div class="qk-seg" id="tm-pw" role="group" aria-label="Group the board">' + segs.map(s => '<button type="button" data-value="' + s[0] + '" aria-pressed="' + (s[0] === ST.pw) + '">' + esc(s[1]) + '</button>').join('') + '</div>' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(null, { groups: groups, valueLabel: 'Our rating', unit: 'points per 100 possessions against an average team', formLabel: 'Last 10',
      parts: [{ key: 'off', label: 'Offence', color: 'var(--c-2)' }, { key: 'def', label: 'Defence', color: 'var(--c-3)' }] }) + '</div></div>' +
    QK.explain('A <b>rating of +5</b> means the team outscores an average opponent by about five points every 100 trips down the floor: over a 100-possession game, about a five-point favourite on a neutral floor. “Raw net” is the same before the opponent and home-court adjustment. The full table is on <a class="qk-link" href="' + esc(HW.href(ST.L, 'standings', ST.S)) + '">Standings</a>.', { title: 'What’s that number?' });
  const seg = document.getElementById('tm-pw');
  if (seg) QK.seg(seg, x => { ST.pw = x; writeQ(); power(); });
}

/* 2. the team profile grid */
function grid() {
  const host = document.getElementById('tm-grid');
  if (!host) return;
  const have = id => !!META[id] && ids().some(t => isNum(v(t, id)));
  const sets = [{ key: 'overview', label: 'Overview', groups: OVERVIEW.map(g => ({ label: g[0], ids: g[1].filter(have) })).filter(g => g.ids.length) }];
  const gnames = [];
  MS.forEach(m => { if (gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(gn => { const ids2 = MS.filter(m => (m.group || 'Other') === gn && have(m.key)).map(m => m.key); if (ids2.length) sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: ids2 }] }); });
  const ours = MS.filter(m => HW.ours && HW.ours.of(m.key) && have(m.key)).map(m => m.key);
  if (ours.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: ours }] });
  const rows = byRating(ids()).map(t => { const i = tinfo(t); return { id: t, name: i.name, sub: rec(t) + (i.conf ? ' · ' + i.conf : ''), mark: { abbr: i.abbr, colour: i.colour }, href: thref(t) }; });
  const addable = gnames.map(gn => '<optgroup label="' + esc(gn) + '">' + MS.filter(m => (m.group || 'Other') === gn && have(m.key)).map(m => '<option value="' + esc(m.key) + '">' + esc(label(m.key)) + '</option>').join('') + '</optgroup>').join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: ids().length + ' teams, every metric', sub: 'Each cell is the team’s value, coloured by its percentile among the ' + ids().length + ' (blue worst, red best; a ↓ marks a metric where lower is better, grey is style). Pick a phase, add any of the ' + MS.length + ' metrics, sort any column, tap a team for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(s => s.key === ST.grid) ? ST.grid : 'overview', setsLabel: 'Phase', added: ST.gadd.filter(have), sort: ST.gsort || { key: 'model_net', dir: 'desc' },
    nameLabel: 'Team', subLabel: 'Record · conference', noun: 'teams', meta: meta, addable: addable,
    rows: rows, val: (r, id) => v(r.id, id),
    csv: 'hardwood-' + ST.L + '-' + ST.S + '-teams.csv',
    onState: st => { ST.grid = st.set === 'overview' ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; writeQ(); }
  });
}

/* 3. the style map */
function styleMap() {
  const host = document.getElementById('tm-map');
  if (!host) return;
  const opts = MS.filter(m => ids().some(t => isNum(v(t, m.key)))).map(m => ({ value: m.key, label: label(m.key) }));
  const P = PRESETS.filter(p => ids().filter(t => isNum(v(t, p[1])) && isNum(v(t, p[2]))).length >= 5);
  if (ST.map >= P.length) ST.map = 0;
  const cur = ST.map >= 0 ? P[ST.map] : null;
  const x = cur ? cur[1] : (ST.mx || 'model_off'), y = cur ? cur[2] : (ST.my || 'model_def');
  const sel = (id, val) => '<select class="qk-select" id="' + id + '">' + opts.map(o => '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>').join('') + '</select>';
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each team wins', sub: 'Any two team metrics against each other. The dashed lines are the league medians; better is always up and to the right (axes where less is better are flipped). Tap a team for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map((p, i) => '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p[0]) + '</option>').join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:520px;margin-top:16px" role="img" aria-label="Style map"></div><p class="hw-note" id="tm-map-n"></p></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-preset').onchange = e => { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } writeQ(); styleMap(); };
  $('tm-mx').onchange = e => { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; writeQ(); styleMap(); };
  $('tm-my').onchange = e => { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; writeQ(); styleMap(); };
  const mx = meta(x), my = meta(y);
  const pts = ids().filter(t => isNum(v(t, x)) && isNum(v(t, y))).map(t => { const i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name + ' · ' + rec(t), label: i.abbr, color: i.colour || null, size: 15, href: thref(t) }; });
  const med = a => { const s = a.slice().sort((p, q) => p - q), n = s.length; return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : 0; };
  const corners = cur ? cur[3] : { tl: '', tr: 'Better on both', bl: 'Worse on both', br: '' };
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: med(pts.map(p => p.x)), refY: med(pts.map(p => p.y)), xInverse: mx.lower, yInverse: my.lower, pad: '9%',
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: mx.fmt, yFmt: my.fmt,
    quadrants: [corners.tl, corners.tr, corners.bl, corners.br], label: my.label + ' against ' + mx.label });
  $('tm-map-n').innerHTML = '<b>' + esc(mx.label) + '</b>: ' + esc(mx.tip) + ' <b>' + esc(my.label) + '</b>: ' + esc(my.tip);
}

/* 4. strengths and weaknesses */
function strengths() {
  const host = document.getElementById('tm-sw');
  if (!host) return;
  const pool = SW_POOL.filter(id => META[id] && ids().some(t => isNum(v(t, id))));
  const cards = byRating(ids()).map(t => {
    const i = tinfo(t);
    const xs = pool.map(id => ({ id: id, p: pc(t, id) })).filter(o => isNum(o.p));
    const chip = o => { const m = meta(o.id); return { label: m.label, pctl: o.p, text: m.fmt(v(t, o.id)), tip: m.tip }; };
    return QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + ' · rating ' + U().signed(rating(t), 1), best: xs.slice().sort((a, b) => b.p - a.p).slice(0, 3).map(chip), worst: xs.slice().sort((a, b) => a.p - b.p).slice(0, 3).map(chip) });
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each team does best, and worst', sub: 'Each team’s three best and three worst of ' + pool.length + ' process metrics and ratings, as percentiles among the ' + ids().length + ' teams (100 = best). Ordered by our rating.' }) +
    '<div class="qk-sw-grid">' + cards + '</div>';
}

/* 5. head to head */
function h2h() {
  const host = document.getElementById('tm-h2h');
  if (!host) return;
  const list = byRating(ids());
  if (!T[ST.a]) ST.a = list[0];
  if (!T[ST.b] || ST.b === ST.a) ST.b = list.filter(t => t !== ST.a)[0];
  const opt = cur => list.slice().sort((a, b) => tinfo(a).name.localeCompare(tinfo(b).name)).map(t => '<option value="' + esc(t) + '"' + (t === cur ? ' selected' : '') + '>' + esc(tinfo(t).name) + '</option>').join('');
  const A = tinfo(ST.a), B = tinfo(ST.b);
  const groups = H2H.map(g => ({ label: g[0], rows: g[1].filter(id => META[id]).map(id => {
    const m = meta(id);
    return { label: m.label, tip: m.tip, a: v(ST.a, id), b: v(ST.b, id), ta: isNum(v(ST.a, id)) ? m.fmt(v(ST.a, id)) : '—', tb: isNum(v(ST.b, id)) ? m.fmt(v(ST.b, id)) : '—', pa: pc(ST.a, id), pb: pc(ST.b, id), better: m.lower ? 'low' : 'high' };
  }) })).filter(g => g.rows.length);
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: A.short + ' or ' + B.short + '?', sub: 'Two teams on the numbers that decide games. Bars are percentiles among the ' + list.length + ' teams; the small line under each metric is the gap in percentile points and who leads it.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: rec(ST.a) + ' · ' + U().signed(rating(ST.a), 1), colour: A.colour, alt: A.alt, href: thref(ST.a) },
      right: { name: B.name, short: B.abbr, sub: rec(ST.b) + ' · ' + U().signed(rating(ST.b), 1), colour: B.colour, alt: B.alt, href: thref(ST.b) }, groups: groups, wins: true, gap: true }) + '</div></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-a').onchange = e => { ST.a = e.target.value; writeQ(); h2h(); };
  $('tm-b').onchange = e => { ST.b = e.target.value; writeQ(); h2h(); };
  $('tm-swap').onclick = () => { const t = ST.a; ST.a = ST.b; ST.b = t; writeQ(); h2h(); };
}

/* 6. through the season */
function trend() {
  const host = document.getElementById('tm-trend');
  if (!host) return;
  const list = byRating(ids());
  const logOf = t => ((T[t] || {}).log || []).filter(g => isNum(g.pts) && isNum(g.opp_pts));
  const pathOf = t => ((T[t] || {}).rating_path || []).filter(p => isNum(p.net));
  if (!list.some(t => logOf(t).length || pathOf(t).length)) { host.innerHTML = ''; return; }
  const po = RACE && RACE.p_playoffs ? RACE.p_playoffs : null;
  if (ST.trend === 'po' && !po) ST.trend = 'net';
  let clubs = ST.clubs.filter(t => T[t]);
  if (!clubs.length) clubs = list.slice(0, 4).concat(list.slice(-1));
  const chips = list.slice().sort((a, b) => tinfo(a).abbr.localeCompare(tinfo(b).abbr)).map(t => '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '">' + esc(tinfo(t).abbr) + '</button>').join('');
  const groupsOf = ST.L === 'nba' ? Array.from(new Set(list.map(t => tinfo(t).division).filter(Boolean))).sort() : Array.from(new Set(list.map(t => tinfo(t).conf).filter(Boolean))).sort();
  const segs = [['net', 'Our rating'], ['pd', 'Point differential']].concat(po ? [['po', 'Playoff chance']] : []);
  const TTL = { net: 'Our rating, game by game', pd: 'Point differential, added up', po: 'The race, day by day' };
  const SUB = { net: 'Our net rating after each game: points per 100 possessions better than an average team, adjusted for opponents.', pd: 'Points scored minus points allowed, added up game by game from each team’s game log. A line that climbs is outscoring its opponents.', po: 'Our chance of a playoff place for each team on each day, from the season simulation as it stood that day.' };
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: TTL[ST.trend], sub: SUB[ST.trend],
    actions: '<div class="qk-seg" id="tm-tr" role="group" aria-label="Measure">' + segs.map(s => '<button type="button" data-value="' + s[0] + '" aria-pressed="' + (s[0] === ST.trend) + '">' + esc(s[1]) + '</button>').join('') + '</div>' }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">Teams</span><div class="qk-chips">' + chips + '</div>' +
    (groupsOf.length ? '<div class="qk-chips tm-divs">' + groupsOf.map(d => '<button type="button" class="qk-chip" data-div="' + esc(d) + '">' + esc(d) + '</button>').join('') + '<button type="button" class="qk-chip" data-div="*top">Top five</button></div>' : '') +
    '</div><div id="tm-tr-c" class="qk-chart" style="--h:460px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  const T0 = QKC.tokens();
  /* team colours kept apart (kit rule): a colour too close to one already drawn falls to the team's alternate, then a chart slot */
  const used = [];
  const colOf = (t, i) => {
    const c = tinfo(t).colour, a = tinfo(t).alt;
    const ok = x => x && QK.color.parse(x) && used.every(u => (QK.color.distinct ? QK.color.distinct(u, x) : QK.color.contrast(u, x) >= 1.6));
    let out = c && QK.color.parse(c) ? QK.color.team(c) : null;
    if (!ok(out)) out = a && QK.color.parse(a) ? QK.color.team(a) : null;
    if (!ok(out)) out = T0.cat[i % 8];
    used.push(out);
    return out;
  };
  const el = document.getElementById('tm-tr-c');
  if (ST.trend === 'po') {
    const dates = Object.keys(po).sort();
    QKC.line(el, { x: dates.map(d => QK.fmt.date(d + 'T12:00:00', { day: 'numeric', month: 'short' })), series: clubs.map((t, i) => ({ name: tinfo(t).abbr, color: colOf(t, i), data: dates.map(d => { const p = (po[d] || {})[t]; return isNum(p) ? Math.round(p * 1000) / 10 : null; }) })),
      yName: 'Playoff chance (%)', xName: 'Date', yMin: 0, yMax: 100, yFmt: x => x + '%', endLabels: true, label: 'Our playoff chance by day' });
  } else if (ST.trend === 'pd') {
    const series = clubs.map((t, i) => { let s = 0; return { name: tinfo(t).abbr, color: colOf(t, i), data: logOf(t).map((g, j) => { s += g.pts - g.opp_pts; return [j + 1, s]; }) }; });
    const n = Math.max.apply(null, series.map(x => x.data.length).concat([1]));
    QKC.line(el, { xType: 'value', x: Array.from({ length: n }, (_, j) => j + 1), series: series, yName: 'Point differential (points)', xName: 'Games played', xMin: 0, xMax: n, ref: { y: 0, label: 'Even' }, endLabels: true, label: 'Point differential through the season' });
  } else {
    const series = clubs.map((t, i) => ({ name: tinfo(t).abbr, color: colOf(t, i), data: pathOf(t).map((p, j) => [j + 1, Math.round(p.net * 10) / 10]) }));
    const n = Math.max.apply(null, series.map(x => x.data.length).concat([1]));
    QKC.line(el, { xType: 'value', x: Array.from({ length: n }, (_, j) => j + 1), series: series, yName: 'Net rating (points per 100 possessions)', xName: 'Games played', xMin: 0, xMax: n, ref: { y: 0, label: 'Average' }, endLabels: true, yFmt: x => U().signed(x, 0), label: 'Our net rating through the season' });
  }
  host.querySelectorAll('[data-club]').forEach(b => b.addEventListener('click', () => {
    const t = b.getAttribute('data-club'), cur = clubs.slice(), i = cur.indexOf(t);
    if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else if (cur.length < 8) cur.push(t);
    ST.clubs = cur; writeQ(); trend();
  }));
  host.querySelectorAll('[data-div]').forEach(b => b.addEventListener('click', () => {
    const d = b.getAttribute('data-div');
    ST.clubs = d === '*top' ? list.slice(0, 5) : list.filter(t => (ST.L === 'nba' ? tinfo(t).division : tinfo(t).conf) === d);
    writeQ(); trend();
  }));
  const seg = document.getElementById('tm-tr');
  if (seg) QK.seg(seg, x => { ST.trend = x; writeQ(); trend(); });
}

/* 7. who's missing: the availability term for each team's next game and the injury report with each player's cost */
function injuries() {
  const host = document.getElementById('tm-inj');
  if (!host) return;
  if (!VAL) { host.innerHTML = ''; const chip = document.querySelector('[data-jump="tm-inj"]'); if (chip) chip.remove(); return; }
  const rows = U().rowsOf(VAL);
  const repl = isNum((VAL.constants || {}).replacement) ? VAL.constants.replacement : -2;
  const gm = (VAL.constants || {}).game_minutes || (ST.L === 'wnba' ? 40 : 48);
  const out = rows.filter(r => r.inj && T[String(r.team)]).map(r => Object.assign({}, r, { cost: isNum(r.rate) && isNum(r.mpg) ? Math.max(0, (r.rate - repl) * r.mpg / gm) : null }));
  /* the next game's availability term per team (points of its own margin; schedule.json model.av = [home, away]) */
  const av = {};
  const nowT = QK.now();
  ((SCHED && SCHED.games) || []).filter(g => g.status === 'pre' && Date.parse(g.date) > nowT - 6 * 36e5).sort((a, b) => String(a.date).localeCompare(String(b.date))).forEach(g => {
    const a = (g.model || {}).av;
    if (!a) return;
    if (av[String(g.home)] === undefined) av[String(g.home)] = { v: a[0], g: g };
    if (av[String(g.away)] === undefined) av[String(g.away)] = { v: a[1], g: g };
  });
  const teams = ids().map(t => {
    const list = out.filter(r => String(r.team) === t).sort((a, b) => (b.cost || 0) - (a.cost || 0));
    const outN = list.filter(r => /^out/i.test(r.inj)).length;
    return { t: t, list: list, outN: outN, cost: list.filter(r => /^out/i.test(r.inj)).reduce((s0, r) => s0 + (r.cost || 0), 0), av: av[t] ? av[t].v : null, g: av[t] ? av[t].g : null };
  });
  const withAv = teams.filter(x => isNum(x.av)).sort((a, b) => a.av - b.av);
  const hit = teams.slice().sort((a, b) => b.cost - a.cost);
  const big = out.slice().sort((a, b) => (b.v || 0) - (a.v || 0))[0];
  host.innerHTML = QK.sectionHead({ kicker: 'Who’s missing', title: 'Injuries, and what they cost', sub: 'From ESPN’s injury report, as of the last build. The bar is each team’s availability term for its next game: the points of its own margin our game model expects from who will play, against what its rating already reflects. Below it, every listed player and what the team loses without him.' }) +
    '<div class="hw-kpis">' + QK.stats([
      { label: 'Players listed', value: String(out.length), sub: out.filter(r => /^out/i.test(r.inj)).length + ' out, the rest day to day or questionable' },
      hit[0] && hit[0].cost > 0 ? { label: 'Hit hardest', value: HW.teamAbbr(ST.L, hit[0].t) + ' −' + U().f(hit[0].cost, 1), signal: true, href: thref(hit[0].t), sub: 'points per 100 possessions out with ' + hit[0].outN + ' player' + (hit[0].outN === 1 ? '' : 's') } : null,
      big ? { label: 'Biggest name listed', value: big.name, text: true, href: HW.playerHref(ST.L, big.id), sub: HW.teamAbbr(ST.L, big.team) + ' · ' + big.inj + ' · ' + U().f(big.v, 1) + ' WAR over four seasons' } : null]) + '</div>' +
    (withAv.length ? '<div class="qk-card"><div class="qk-card-head"><div><div class="qk-card-title">Next game: the availability term</div><div class="qk-card-sub">Points of each team’s own margin from who is expected to play (below zero: weaker than its rating)</div></div></div><div class="qk-card-body"><div id="tm-av" class="qk-chart" style="--h:' + (20 * withAv.length + 80) + 'px" role="img" aria-label="Availability term by team"></div></div></div>' : '') +
    '<div class="qk-card" style="margin-top:var(--sp-4)"><div class="qk-card-head"><div><div class="qk-card-title">The injury report</div><div class="qk-card-sub">Every listed player, the most costly first</div></div></div><div class="qk-card-body flush"><div id="tm-injt"></div></div></div>' +
    QK.explain('<b>−3.0 per 100</b> means the team is about three points worse every 100 possessions without the player than with him at his usual minutes: over a game, roughly a three-point swing in the expected margin. Players listed Out count as not playing in our forecasts; day-to-day players keep the share of games their recent record implies.', { title: 'What’s that number?' });
  if (withAv.length) QKC.bar('#tm-av', { cats: withAv.map(x => HW.teamAbbr(ST.L, x.t)), series: [{ name: 'Availability', data: withAv.map(x => Math.round(x.av * 10) / 10) }], horizontal: true, labels: true, diverging: true, fmt: x => U().signed(x, 1), labelWidth: 46,
    valName: 'Points of margin from who plays (next game)', catName: 'Team', hrefs: withAv.map(x => x.g ? HW.gameHref(ST.L, x.g.id, ST.S) : thref(x.t)) });
  QK.leaderboard(document.getElementById('tm-injt'), { dense: true, maxHeight: 640, rows: out.sort((a, b) => (b.cost || 0) - (a.cost || 0)).map(r => ({ id: r.id, name: r.name, team: String(r.team), sub: [r.pos, isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · '), inj: r.inj, cost: r.cost, mpg: r.mpg, v: r.v })),
    rowHref: r => HW.playerHref(ST.L, r.id), columns: [
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => U().team(ST.L, r.team), href: r => HW.playerHref(ST.L, r.id) },
      { key: 'team', label: 'Team', fmt: v => esc(HW.teamAbbr(ST.L, v)) },
      { key: 'inj', label: 'Status', fmt: v => '<span class="hw-inj' + (/^out/i.test(v) ? '' : ' q') + '">' + esc(v) + '</span>' },
      { key: 'mpg', label: 'Min', num: true, fmt: v => U().f(v, 1), tip: 'Projected minutes a game when fit' },
      { key: 'cost', label: 'Cost per 100', num: true, fmt: v => (isNum(v) ? '−' + U().f(v, 1) : '—'), tip: 'Points per 100 possessions the team loses without the player: (projected rate − replacement) × minutes / 48' },
      { key: 'v', label: 'Value', num: true, fmt: v => U().f(v, 1), tip: 'Four-season wins above replacement' }] });
}

HW.page('teams', render);
HW.teamsPage = { render: render };
})(window.HW);
