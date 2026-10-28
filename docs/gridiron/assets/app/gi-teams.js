/* The Quant Gridiron — the Teams page (#/teams), round 9 (28 Oct 2026; the Bullpen's bp-teams.js is the reference):
 * every club ranked, profiled and set against the rest. It replaces the card wall of teams.js (the team pages,
 * #/team/<abbr>, stay in team.js). Kit: scout.js (QK.powerBars, QK.heatGrid, QK.strengths), quant.js (QK.tape with
 * gap: true), quant-charts.js (QKC.scatter, QKC.line).
 *
 * Sections (a chip strip jumps between them; ?sec= scrolls to one):
 *   1. Power board: each club ranked by our team rating (points a game against an average team on a neutral field),
 *      the bar split into offence, defence and special teams around zero (the team-strength model's parts; the rating
 *      is the volt tick), the record, point differential, our projected wins, the last five and our playoff and Super
 *      Bowl chances, quiet (current season, from 20,000 simulated seasons); Division | Conference | All (?pw=).
 *   2. Team profile: the heat grid of clubs by every team metric, phase groups as chips (Ratings, Offence, Defence,
 *      Special teams and fourth down, Tendencies, Defence style, Pace, Our models), percentile cells, sortable, CSV.
 *   3. Style map: presets (pass against rush EPA, offence against defence, success against EPA per play, pass rate over
 *      expected against EPA, pace against efficiency, pass rush against protection, our rating against the record) with
 *      the corners named, or any two metrics (?map=, mx=, my=). This is the site's one offence-v-defence scatter.
 *   4. Strengths and weaknesses: each club's three best and three worst process metrics as percentile chips.
 *   5. Head to head: two clubs on the tale of the tape with the gap in percentile points (?a=, b=); Compare's old team
 *      mode (#/compare/t:KC/t:BUF) lands here.
 *   6. Through the season: our rating week by week (team strength, from game EPA) or the point differential game by
 *      game, for the clubs picked (?trend=, clubs=).
 *   7. Injury impact (phase 4, current season): value on the sidelines by team and the biggest losses (<S>/injuries.json).
 *   8. Tendencies (phase 4): pass rate over expected by situation (neutral, third down, red zone, leading, trailing).
 * Reads <S>/teams.json and <S>/season.json. Older-browser rule: no optional chaining, no nullish coalescing. */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;

const ST = { S: null, pw: 'division', grid: '', gadd: [], gsort: null, map: 0, mx: '', my: '', a: '', b: '', trend: 'rating', clubs: [], sec: '' };
let T = null, META = {}, MS = [], SEA = {}, CUR = false;

const GRID_SETS = [
  ['overview', 'Overview', [['Ratings', ['rating', 'off_rating', 'def_rating', 'st_rating']], ['Record', ['win_pct', 'diff']], ['Chances', ['p_playoffs', 'p_sb', 'mean_wins']]]],
  ['offence', 'Offence', [['Efficiency', ['off_epa', 'off_pass_epa', 'off_rush_epa', 'off_success']], ['Protection', ['pressure_allowed']]]],
  ['defence', 'Defence', [['Efficiency allowed', ['def_epa', 'def_pass_epa', 'def_rush_epa', 'def_success']], ['Pass rush', ['pressure_rate_def']]]],
  ['special', 'Special teams and fourth down', [['Special teams', ['st_epa_g']], ['Fourth down', ['go_rate', 'go_rate_rec', 'fd_wp_lost']]]],
  ['tendencies', 'Tendencies', [['Pass rate over expected', ['proe', 'proe_neutral', 'proe_3rd', 'proe_rz', 'proe_lead', 'proe_trail']], ['Formation and design', ['shotgun', 'no_huddle', 'pa_rate', 'rpo_rate', 'motion_rate', 'screen_rate']]]],
  ['dstyle', 'Defence style', [['Style', ['blitz_rate', 'man_rate', 'box_avg']]]],
  ['pace', 'Pace', [['Pace', ['sec_per_play_neutral', 'sec_per_play', 'plays_pg']]]]
];
/* how a team plays, not how well: no percentile colour, never a strength or weakness */
const STYLE = /^(proe|proe_neutral|proe_3rd|proe_rz|proe_lead|proe_trail|shotgun|no_huddle|pa_rate|rpo_rate|motion_rate|screen_rate|blitz_rate|man_rate|box_avg|sec_per_play_neutral|sec_per_play|plays_pg|go_rate)$/;
const SW_POOL = ['off_epa', 'off_pass_epa', 'off_rush_epa', 'off_success', 'pressure_allowed', 'def_epa', 'def_pass_epa', 'def_rush_epa', 'def_success', 'pressure_rate_def', 'st_epa_g', 'go_rate_rec', 'fd_wp_lost'];
const H2H = [['Strength', ['rating', 'off_rating', 'def_rating', 'st_rating', 'diff']], ['Offence', ['off_epa', 'off_pass_epa', 'off_rush_epa', 'off_success', 'pressure_allowed']],
  ['Defence', ['def_epa', 'def_pass_epa', 'def_rush_epa', 'def_success', 'pressure_rate_def']], ['Special teams and fourth down', ['st_epa_g', 'go_rate_rec', 'fd_wp_lost']],
  ['How they play', ['proe_neutral', 'sec_per_play_neutral', 'pa_rate', 'motion_rate', 'blitz_rate', 'man_rate']]];
/* style-map presets: [label, x, y, corners { tl, tr, bl, br }]; better is up and to the right (flipped axes say so) */
const PRESETS = [
  ['Offence against defence (EPA per play)', 'off_epa', 'def_epa', { tl: 'Defence carries', tr: 'Contenders', bl: 'Rebuilding', br: 'Offence carries' }],
  ['Pass against rush (offence, EPA)', 'off_pass_epa', 'off_rush_epa', { tl: 'Win on the ground', tr: 'Balanced and good', bl: 'Stuck', br: 'Air it out' }],
  ['Success rate against EPA per play', 'off_success', 'off_epa', { tl: 'Boom or bust', tr: 'Efficient and explosive', bl: 'Stalled', br: 'Grinders' }],
  ['Pass rate over expected against EPA', 'proe_neutral', 'off_epa', { tl: 'Run-first, working', tr: 'Pass-first, working', bl: 'Run-first, stuck', br: 'Pass-first, stuck' }],
  ['Pace against efficiency', 'sec_per_play_neutral', 'off_epa', { tl: 'Slow and sure', tr: 'Fast and good', bl: 'Slow and stuck', br: 'Fast, going nowhere' }],
  ['Pass rush against protection', 'pressure_rate_def', 'pressure_allowed', { tl: 'Protect, no rush', tr: 'Win both lines', bl: 'Lose both lines', br: 'Rush, no protection' }],
  ['Our rating against the record', 'rating', 'win_pct', { tl: 'Winning on luck?', tr: 'The real deal', bl: 'Struggling', br: 'Due a run' }]
];
const EXTRA = {
  st_rating: { label: 'Special teams rating', short: 'Special teams', fmt: '1', desc: 'Special-teams points a game against an average team (our team-strength model).', group: 'Ratings', ours: 'rating' },
  win_pct: { label: 'Win %', fmt: 'pct', desc: 'Wins (ties half) over games played.', group: 'Record' },
  diff: { label: 'Point differential', fmt: 'signed1', desc: 'Points scored minus points allowed.', group: 'Record' },
  p_playoffs: { label: 'Playoff chance', fmt: 'prob', desc: 'Our chance from 20,000 simulated seasons.', group: 'Chances', ours: 'season_sim' },
  p_sb: { label: 'Super Bowl chance', fmt: 'prob', desc: 'Our chance from 20,000 simulated seasons.', group: 'Chances', ours: 'season_sim' },
  mean_wins: { label: 'Projected wins', fmt: '1', desc: 'Our average final win total over 20,000 simulated seasons.', group: 'Chances', ours: 'season_sim' }
};

function meta(id) {
  const x = EXTRA[id];
  const m = META[id] || (x ? { key: id, label: x.label, fmt: x.fmt, desc: x.desc, group: x.group } : { key: id, label: id });
  const label = GI.SP.specLabel(id, m.label || id, 'team');
  const ours = GI.SP.ours(x && x.ours ? x.ours : id);
  const tip = GI.cleanDesc(m.desc || '');
  return { id: id, label: label, short: (x && x.short) || label, tip: tip + (ours && tip.indexOf('Our model') < 0 ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''), lower: !!m.lower, style: STYLE.test(id), ours: ours,
    fmt: v => (m.fmt === 'prob' ? GI.pct(v, v < 0.1 ? 1 : 0) : GI.fmtVal(v, m.fmt)) };
}
function v(t, id) {
  const x = T[t] || {}, vals = x.values || {}, r = SEA[t] || {}, rec = x.record || {}, sim = x.sim || {};
  if (id === 'st_rating') { const u = (x.units || {}).model || {}; if (isNum(u.st)) return Number(u.st); return isNum(vals.rating) && isNum(vals.off_rating) && isNum(vals.def_rating) ? vals.rating - vals.off_rating - vals.def_rating : null; }
  if (id === 'win_pct') { const w = GI.first(r.w, rec.w), l = GI.first(r.l, rec.l), ti = GI.first(r.t, rec.t) || 0; return isNum(w) && isNum(l) && w + l + ti > 0 ? (w + 0.5 * ti) / (w + l + ti) : null; }
  if (id === 'diff') return GI.first(r.diff, rec.diff);
  if (id === 'p_playoffs' || id === 'p_sb' || id === 'mean_wins') return CUR ? GI.first(r[id], sim[id]) : null;
  return isNum(vals[id]) ? Number(vals[id]) : null;
}
/* percentile 100 = best: the payload's where it has one, else ranked among the clubs */
function pc(t, id) {
  const m = meta(id);
  if (m.style) return null;
  const p = ((T[t] || {}).pct || {})[id];
  if (isNum(p)) return p;
  const xs = ids().map(x => v(x, id)).filter(isNum).sort((a, b) => a - b), y = v(t, id);
  if (!isNum(y) || xs.length < 5) return null;
  const q = QK.pctRank(xs, y);
  return m.lower ? 100 - q : q;
}
function rec(t) { const r = SEA[t] || {}, x = (T[t] || {}).record || {}; return GI.record(GI.first(r.w, x.w), GI.first(r.l, x.l), GI.first(r.t, x.t)); }
function tinfo(t) { const x = T[t] || {}, i = GI.teamInfo(t); return { abbr: GI.teamAbbr(t), name: x.name || i.name || t, short: x.short || i.short || t, colour: x.colour || i.colour || '', alt: x.alt || i.alt || '', division: x.division || i.division || '', conference: x.conference || i.conference || '' }; }
function thref(t) { return GI.teamHref(t, ST.S); }
function ids() { return Object.keys(T || {}).filter(t => isNum(v(t, 'rating')) || isNum(v(t, 'off_epa'))); }
function byRating(list) { return list.slice().sort((a, b) => (GI.first(v(b, 'rating'), -99)) - (GI.first(v(a, 'rating'), -99))); }

/* ── address ─────────────────────────────────────────────────────────────── */
function readQ(q) {
  q = q || {};
  ST.pw = ['division', 'conference', 'all'].indexOf(q.pw) >= 0 ? q.pw : 'division';
  ST.grid = q.grid || ''; ST.gadd = q.gadd ? String(q.gadd).split(',').filter(Boolean) : [];
  ST.gsort = q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null;
  const mp = parseInt(q.map, 10); ST.map = isNaN(mp) ? 0 : mp; ST.mx = q.mx || ''; ST.my = q.my || '';
  ST.a = q.a ? GI.canonTeam(q.a) : ''; ST.b = q.b ? GI.canonTeam(q.b) : ''; ST.trend = q.trend === 'diff' ? 'diff' : 'rating';
  ST.clubs = q.clubs ? String(q.clubs).split(',').filter(Boolean).map(GI.canonTeam) : []; ST.sec = q.sec || '';
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
  if (ST.trend !== 'rating') q.trend = ST.trend;
  if (ST.clubs.length) q.clubs = ST.clubs.join(',');
  if (ST.S && ST.S !== GI.currentSeason()) q.s = ST.S;
  GI.setHashQuiet('#/teams' + GI.qs(q));
}

/* ── render ──────────────────────────────────────────────────────────────── */
const SECS = [['tm-power', 'Power board', 'power'], ['tm-grid', 'Team profile', 'grid'], ['tm-map', 'Style map', 'map'], ['tm-sw', 'Strengths and weaknesses', 'sw'], ['tm-h2h', 'Head to head', 'h2h'], ['tm-trend', 'Through the season', 'trend'],
  ['tm-inj', 'Injury impact', 'injuries'], ['tm-tend', 'Tendencies', 'tendencies']];
function jump(id) {
  const t = document.getElementById(id);
  if (!t) return;
  const off = ['.qk-topbar', '.qk-secnav'].reduce((s, q) => s + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + 12;
  window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth' });
}
GI.route('teams', function (el, params) {
  ST.S = Number(params.season) || GI.currentSeason();
  CUR = ST.S === GI.currentSeason();
  readQ(params.query || {});
  el.innerHTML = GI.pageHead('Teams · ' + ST.S, 'The 32 teams', 'Every club ranked by our rating, profiled on every team metric and set against the rest. Tap a club for its page: ratings over time, strengths and needs, the roster, the schedule and moves.') +
    GI.sectionNav('teams', 'teams') +
    '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(s => '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[1]) + '</a>').join('') + '</div></nav>' +
    SECS.map(s => '<section class="qk-section tm-sec" id="' + s[0] + '">' + QK.skeleton('lines', 3) + '</section>').join('');
  el.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); jump(a.getAttribute('data-jump')); }));
  return Promise.all([GI.loadYear('teams.json', ST.S), GI.loadYear('season.json', ST.S), GI.SP.specReady()]).then(res => {
    if (!el.isConnected) return;
    const cat = res[0], sea = res[1];
    if (!GI.ok(cat) || !cat.teams) { el.innerHTML = GI.pageHead('Teams · ' + ST.S, 'The 32 teams', '') + GI.sectionNav('teams', 'teams') + GI.notBuilt('The ' + ST.S + ' team file', cat); return; }
    T = {}; Object.keys(cat.teams).forEach(t => { T[GI.canonTeam(t)] = cat.teams[t]; });
    MS = (cat.metrics || []).slice(); META = {}; MS.forEach(m => { META[m.key] = m; });
    GI.cleanMetrics(MS);
    SEA = {};
    GI.seasonRows(GI.ok(sea) ? sea : null).forEach(r => { if (r && r.team) SEA[GI.canonTeam(r.team)] = r; });
    power(); grid(); styleMap(); strengths(); h2h(); trend(); injuries(); tendencies();
    const sec = SECS.find(s => s[2] === ST.sec);
    if (sec) setTimeout(() => jump(sec[0]), 60);
  });
});

/* 1. the power board */
function power() {
  const host = document.getElementById('tm-power');
  if (!host) return;
  const all = byRating(ids());
  const rk = {}; all.forEach((t, i) => { rk[t] = i + 1; });
  const row = t => {
    const i = tinfo(t), r = SEA[t] || {}, x = T[t] || {}, sim = x.sim || {}, recd = x.record || {};
    const last = (Array.isArray(r.last5) ? r.last5 : (recd.last5 || [])).join('');
    const pw = GI.first(r.mean_wins, sim.mean_wins), d = v(t, 'diff');
    const ch = CUR ? [{ label: 'Playoffs', p: GI.first(r.p_playoffs, sim.p_playoffs) }, { label: 'Super Bowl', p: GI.first(r.p_sb, sim.p_sb) }] : [];
    return { rank: rk[t], name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + (r.streak ? ' · ' + r.streak : '') + ' · ' + i.division, value: v(t, 'rating'), text: GI.signed(v(t, 'rating'), 1),
      parts: { off: v(t, 'off_rating'), def: v(t, 'def_rating'), st: v(t, 'st_rating') },
      cells: [{ label: 'Point diff', text: isNum(d) ? GI.signed(d, 0) : '—' }].concat(CUR && isNum(pw) ? [{ label: 'Projected wins', text: GI.num(pw, 1) }] : []),
      form: last || null, chances: ch };
  };
  let groups;
  if (ST.pw === 'all') groups = [{ label: '', rows: all.map(row) }];
  else {
    const keyOf = t => (ST.pw === 'conference' ? tinfo(t).conference : tinfo(t).division);
    const names = Array.from(new Set(all.map(keyOf))).filter(Boolean).sort();
    groups = names.map(n => ({ label: n, rows: all.filter(t => keyOf(t) === n).map(row) }));
  }
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: 'Every team, ranked by our rating', sub: 'Our team rating is the points a game we expect a team to beat an average one by on a neutral field. The bar splits it into offence, defence and special teams; the volt tick is the total.' +
    (CUR ? ' Playoff and Super Bowl chances come from 20,000 simulated seasons.' : ''), actions: GI.seg('tm-pw', [['division', 'Division'], ['conference', 'Conference'], ['all', 'All ' + all.length]], ST.pw, 'Group the board') }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(null, { groups: groups, valueLabel: 'Our rating', unit: 'points a game against an average team', formLabel: 'Last 5', formN: 5,
      parts: [{ key: 'off', label: 'Offence', color: 'var(--c-2)' }, { key: 'def', label: 'Defence', color: 'var(--c-3)' }, { key: 'st', label: 'Special teams', color: 'var(--c-5)' }] }) + '</div></div>' +
    QK.explain('A <b>rating of +7</b> means the team is about a touchdown a game better than an average team on a neutral field. It comes from every play’s expected points, adjusted for the opponents faced, with priors from last season that fade as the games come in. The full tables are on <a href="' + GI.standingsHref(ST.S) + '">Standings</a>.', { title: 'What’s that number?' });
  GI.wireSeg(host, 'tm-pw', x => { ST.pw = x; writeQ(); power(); });
}

/* 2. the team profile grid */
function grid() {
  const host = document.getElementById('tm-grid');
  if (!host) return;
  const haveId = id => ids().some(t => isNum(v(t, id)));
  const sets = GRID_SETS.map(s => ({ key: s[0], label: s[1], groups: s[2].map(g => ({ label: g[0], ids: g[1].filter(haveId) })).filter(g => g.ids.length) })).filter(s => s.groups.length);
  const ours = MS.filter(m => GI.SP.ours(m.key) && haveId(m.key)).map(m => m.key);
  if (ours.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: ours }] });
  const used = {}; sets.forEach(s => s.groups.forEach(g => g.ids.forEach(id => { used[id] = 1; })));
  const rest = MS.filter(m => !used[m.key] && haveId(m.key)).map(m => m.key);
  if (rest.length) sets.push({ key: 'more', label: 'More', groups: [{ label: 'More', ids: rest }] });
  const rows = byRating(ids()).map(t => { const i = tinfo(t); return { id: t, name: i.name, sub: rec(t) + ' · ' + i.division, mark: { abbr: i.abbr, colour: i.colour }, href: thref(t) }; });
  const addable = GI.metricGroups(MS.filter(m => haveId(m.key))).map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '">' + esc(meta(m.key).label) + '</option>').join('') + '</optgroup>').join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: ids().length + ' teams, every metric', sub: 'Each cell is the team’s value, coloured by its percentile among the ' + ids().length + ' (blue worst, red best; a ↓ marks a metric where lower is better; grey is style, neither better nor worse). Pick a phase, add any of the ' + MS.length + ' team metrics, sort by any column, tap a team for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(s => s.key === ST.grid) ? ST.grid : 'overview', setsLabel: 'Phase', added: ST.gadd.filter(haveId), sort: ST.gsort || { key: 'rating', dir: 'desc' },
    nameLabel: 'Team', subLabel: 'Record · division', noun: 'teams', meta: meta, addable: addable,
    rows: rows, val: (r, id) => v(r.id, id),
    csv: 'gridiron-' + ST.S + '-teams.csv',
    onState: st => { ST.grid = st.set === 'overview' ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; writeQ(); }
  });
}

/* 3. the style map */
function styleMap() {
  const host = document.getElementById('tm-map');
  if (!host) return;
  const haveId = id => ids().filter(t => isNum(v(t, id))).length >= 5;
  const opts = MS.filter(m => haveId(m.key)).map(m => ({ value: m.key, label: meta(m.key).label }))
    .concat(['st_rating', 'win_pct', 'diff'].filter(haveId).map(k => ({ value: k, label: meta(k).label })));
  const P = PRESETS.filter(p => haveId(p[1]) && haveId(p[2]));
  if (ST.map >= P.length) ST.map = 0;
  const cur = ST.map >= 0 ? P[ST.map] : null;
  const x = cur ? cur[1] : (ST.mx || 'off_epa'), y = cur ? cur[2] : (ST.my || 'def_epa');
  const sel = (id, val) => '<select class="qk-select" id="' + id + '">' + opts.map(o => '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>').join('') + '</select>';
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each team wins', sub: 'Any two team metrics against each other. The dashed lines are the league medians; better is always up and to the right (an axis where less is better is flipped, and says so). Tap a team for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map((p, i) => '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p[0]) + '</option>').join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:520px;margin-top:16px" role="img" aria-label="Style map"></div><p class="gi-cap" id="tm-map-n"></p></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-preset').onchange = e => { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } writeQ(); styleMap(); };
  $('tm-mx').onchange = e => { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; writeQ(); styleMap(); };
  $('tm-my').onchange = e => { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; writeQ(); styleMap(); };
  const mx = meta(x), my = meta(y);
  const pts = ids().filter(t => isNum(v(t, x)) && isNum(v(t, y))).map(t => { const i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name + ' · ' + rec(t), label: i.abbr, color: i.colour || null, size: 15, href: thref(t) }; });
  const corners = cur ? cur[3] : { tl: '', tr: 'Better on both', bl: 'Worse on both', br: '' };
  const styleAx = m => (m.style ? ' (style: neither better nor worse)' : m.lower ? ' (lower is better: flipped)' : '');
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: GI.median(pts.map(p => p.x)), refY: GI.median(pts.map(p => p.y)), xInverse: mx.lower, yInverse: my.lower, pad: '9%',
    xName: mx.label + styleAx(mx), yName: my.label + styleAx(my), xFmt: mx.fmt, yFmt: my.fmt,
    quadrants: [corners.tl, corners.tr, corners.bl, corners.br], label: my.label + ' against ' + mx.label });
  GI.set('tm-map-n', '<b>' + esc(mx.label) + '</b>: ' + esc(mx.tip) + ' <b>' + esc(my.label) + '</b>: ' + esc(my.tip));
}

/* 4. strengths and weaknesses */
function strengths() {
  const host = document.getElementById('tm-sw');
  if (!host) return;
  const pool = SW_POOL.filter(id => ids().filter(t => isNum(v(t, id))).length >= 5);
  const cards = byRating(ids()).map(t => {
    const i = tinfo(t);
    const xs = pool.map(id => ({ id: id, p: pc(t, id) })).filter(o => isNum(o.p));
    const chip = o => { const m = meta(o.id); return { label: m.label, pctl: o.p, text: m.fmt(v(t, o.id)), tip: m.tip }; };
    const best = xs.slice().sort((a, b) => b.p - a.p).slice(0, 3).map(chip), worst = xs.slice().sort((a, b) => a.p - b.p).slice(0, 3).map(chip);
    return QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + ' · rating ' + GI.signed(v(t, 'rating'), 1), best: best, worst: worst });
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each team does best, and worst', sub: 'Each team’s three best and three worst of ' + pool.length + ' process metrics (EPA and success by unit, pressure, special teams, fourth-down calls), as percentiles among the ' + ids().length + ' teams (100 = best). Ordered by our rating.' }) +
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
  const groups = H2H.map(g => ({ label: g[0], rows: g[1].filter(id => META[id] || EXTRA[id]).map(id => {
    const m = meta(id), a = v(ST.a, id), b = v(ST.b, id);
    return { label: m.label, tip: m.tip, a: a, b: b, ta: isNum(a) ? m.fmt(a) : '—', tb: isNum(b) ? m.fmt(b) : '—', pa: pc(ST.a, id), pb: pc(ST.b, id), better: m.style ? null : (m.lower ? 'low' : 'high') };
  }).filter(r => isNum(r.a) || isNum(r.b)) })).filter(g => g.rows.length);
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: QK.surname(A.short || A.name) + ' or ' + QK.surname(B.short || B.name) + '?', sub: 'Two teams on the numbers that decide games. Bars are percentiles among the ' + list.length + ' teams; the small line under each metric is the gap in percentile points and who leads it. How they play (pace, pass rate, blitzes) is style, with no winner.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: rec(ST.a) + ' · ' + GI.signed(v(ST.a, 'rating'), 1), colour: A.colour, alt: A.alt, href: thref(ST.a) },
      right: { name: B.name, short: B.abbr, sub: rec(ST.b) + ' · ' + GI.signed(v(ST.b, 'rating'), 1), colour: B.colour, alt: B.alt, href: thref(ST.b) }, groups: groups, wins: true, gap: true }) + '</div></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-a').onchange = e => { ST.a = e.target.value; writeQ(); h2h(); };
  $('tm-b').onchange = e => { ST.b = e.target.value; writeQ(); h2h(); };
  $('tm-swap').onclick = () => { const t = ST.a; ST.a = ST.b; ST.b = t; writeQ(); h2h(); };
}

/* 6. through the season: our rating week by week (teams.json history: team strength from game EPA) or the point
   differential game by game (the schedule's finals) */
function trend() {
  const host = document.getElementById('tm-trend');
  if (!host) return;
  const list = byRating(ids());
  const hist = t => { const x = T[t] || {}, hc = x.history_cols || ['week', 'net', 'off', 'def'], ni = hc.indexOf('net'), wi = hc.indexOf('week'); return (x.history || []).map(r => [r[wi < 0 ? 0 : wi], r[ni < 0 ? 1 : ni]]).filter(p => isNum(p[0]) && isNum(p[1])); };
  const games = t => ((T[t] || {}).schedule || []).filter(g => g && g.status === 'final' && isNum(g.hs) && isNum(g.as) && (g.gtype || 'REG') === 'REG').sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
  const hasR = list.some(t => hist(t).length > 1), hasD = list.some(t => games(t).length);
  if (!hasR && !hasD) { host.innerHTML = ''; return; }
  if (ST.trend === 'rating' && !hasR) ST.trend = 'diff';
  let clubs = ST.clubs.filter(t => T[t]);
  if (!clubs.length) { const dv = tinfo(list[0]).division; clubs = list.filter(t => tinfo(t).division === dv); }
  const chips = list.slice().sort((a, b) => tinfo(a).abbr.localeCompare(tinfo(b).abbr)).map(t => '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '">' + esc(tinfo(t).abbr) + '</button>').join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: ST.trend === 'rating' ? 'Our rating, week by week' : 'Point differential, game by game',
    sub: ST.trend === 'rating' ? 'Our team rating after each week (points a game against an average team), refitted from every game’s expected points.' : 'Points scored minus points allowed, added up over the regular season. A line that climbs is outscoring its opponents.',
    actions: hasR && hasD ? GI.seg('tm-tr', [['rating', 'Our rating'], ['diff', 'Point differential']], ST.trend, 'Measure') : '' }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">Teams</span><div class="qk-chips">' + chips + '</div>' +
    '<div class="qk-chips tm-divs">' + GI.DIVISIONS.map(d => '<button type="button" class="qk-chip" data-div="' + esc(d) + '">' + esc(d) + '</button>').join('') + '<button type="button" class="qk-chip" data-div="*top">Top five</button></div>' +
    '</div><div id="tm-tr-c" class="qk-chart" style="--h:440px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  const cs = GI.distinctColours(clubs);
  if (ST.trend === 'rating') {
    const series = clubs.map((t, i) => ({ name: tinfo(t).abbr, color: cs[i], data: hist(t) }));
    const n = Math.max.apply(null, series.map(s => (s.data.length ? s.data[s.data.length - 1][0] : 1)).concat([1]));
    QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', series: series, yName: 'Our rating (points a game v average)', xName: 'Week', xMin: 1, xMax: n, ref: { y: 0, label: 'Average' }, endLabels: true, yFmt: y => GI.signed(y, 0), label: 'Our rating by week' });
  } else {
    const series = clubs.map((t, i) => { let s = 0; return { name: tinfo(t).abbr, color: cs[i], data: games(t).map((g, j) => { s += (GI.canonTeam(g.home) === t ? g.hs - g.as : g.as - g.hs); return [j + 1, s]; }) }; });
    const n = Math.max.apply(null, series.map(x => x.data.length).concat([1]));
    QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', series: series, yName: 'Point differential (points)', xName: 'Games played', xMin: 0, xMax: n, ref: { y: 0, label: 'Even' }, endLabels: true, label: 'Point differential through the season' });
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
  GI.wireSeg(host, 'tm-tr', x => { ST.trend = x; writeQ(); trend(); });
}


/* 7. injury impact (round 9, phase 4; current season): each team's value on the sidelines from <S>/injuries.json (the ESPN
   injury lists the build snapshots hourly, valued with Gridiron Value per game and the game model's chance of missing) */
function injuries() {
  const host = document.getElementById('tm-inj');
  if (!host) return;
  if (!CUR) { host.innerHTML = ''; return; }
  GI.loadYear('injuries.json', ST.S).then(d => {
    if (!host.isConnected) return;
    if (!GI.ok(d) || !d.teams) { host.innerHTML = QK.sectionHead({ kicker: 'Injury impact', title: 'Who is missing the most', sub: '' }) + GI.notBuilt('The injury board', d); return; }
    const cols = d.cols || [], at = c => cols.indexOf(c);
    const teams = Object.keys(d.teams).map(t => Object.assign({ team: GI.canonTeam(t) }, d.teams[t])).sort((a, b) => b.out_pg - a.out_pg);
    const all = [];
    teams.forEach(t => (t.players || []).forEach(p => { if (isNum(p[at('gvar_pg')]) && p[at('gvar_pg')] > 0 && p[at('p_miss')] >= 0.85) all.push({ team: t.team, p: p }); }));
    all.sort((a, b) => b.p[at('gvar_pg')] - a.p[at('gvar_pg')]);
    const top = teams[0];
    host.innerHTML = QK.sectionHead({ kicker: 'Injury impact', title: 'Who is missing the most', sub: 'Each team’s value on the sidelines: the Gridiron Value a game of every player on its injury list, weighted by the chance he misses the next game (out, IR or suspended 1, doubtful 0.85, questionable 0.15, the game model’s weights). The lists as of ' + esc(GI.fmtStamp(d.as_of)) + '.' }) +
      GI.grid(GI.card('Value on the sidelines', 'Points a game of Gridiron Value missing, every team', GI.chartBox('tm-inj-c', Math.max(420, teams.length * 20 + 40), 'Value missing to injury by team'), { span: 6 }) +
        GI.card('The biggest losses', 'The most valuable players ruled out, doubtful or on a reserve list', GI.tableHTML([{ label: 'Player' }, { label: 'Team' }, { label: 'Status' }, { label: 'Injury' }, { label: 'Value a game', align: 'right', title: 'Gridiron Value per game this season' }, { label: 'Back', title: 'ESPN’s expected return date, where given' }],
          all.slice(0, 15).map(x => { const p = x.p; return [{ html: p[at('pid')] ? GI.playerLink(p[at('pid')], p[at('name')] || '') : esc(p[at('name')] || '—'), v: p[at('name')] }, { html: GI.teamChip(x.team, ST.S), v: x.team }, esc(p[at('status')] || ''), esc(p[at('injury')] || ''),
            { html: '<b>' + GI.signed(p[at('gvar_pg')], 2) + '</b>', v: p[at('gvar_pg')] }, esc(p[at('return')] ? GI.fmtDate(p[at('return')], { year: false }) : '—')]; }), { sticky: true, maxHeight: 520 }), { span: 6, flush: true })) +
      QK.explain((top ? 'The <b>' + esc(GI.teamName(top.team)) + '</b> are missing the most: ' + GI.num(top.out_pg, 1) + ' points a game of value, ' + top.n_out + ' players out or doubtful. ' : '') + 'About 40 points of value is one win over a season, so 2 points a game is worth roughly a win over 17 games. Offensive linemen are not valued individually, so a team missing linemen is missing more than this shows; the game model’s own starters-out term counts them.', { title: 'What’s that number?' });
    GI.sortable(host);
    GI.ch.bar('tm-inj-c', { cats: teams.map(t => GI.teamName(t.team)), series: [{ name: 'Value missing', data: teams.map(t => t.out_pg) }], horizontal: true, labels: true, colors: teams.map(t => GI.teamColour(t.team)), hrefs: teams.map(t => thref(t.team)), fmt: x => GI.num(x, 1), labelWidth: 150, valName: 'Value missing (points a game)', catName: 'Team' });
  });
}

/* 8. tendencies (round 9, phase 4): pass rate over expected by situation, from teams.json (nflverse xpass): how often a
   team passes compared with what an average team does in the same down, distance, field position, score and clock */
const PROE = [['proe_neutral', 'Neutral'], ['proe', 'All plays'], ['proe_3rd', 'Third down'], ['proe_rz', 'Red zone'], ['proe_lead', 'Leading'], ['proe_trail', 'Trailing']];
function tendencies() {
  const host = document.getElementById('tm-tend');
  if (!host) return;
  const ks = PROE.filter(k => ids().filter(t => isNum(v(t, k[0]))).length >= 5);
  if (!ks.length) { host.innerHTML = ''; return; }
  const list = ids().filter(t => isNum(v(t, ks[0][0]))).sort((a, b) => v(b, ks[0][0]) - v(a, ks[0][0]));
  const top = list[0], low = list[list.length - 1];
  host.innerHTML = QK.sectionHead({ kicker: 'Tendencies', title: 'Who throws more than they should?', sub: 'Pass rate over expected: how often a team drops back compared with an average team in the same down, distance, field position, score and time. It is style, not quality: the style map sets it against EPA.' }) +
    GI.kpis([top ? GI.kpi('Most pass-happy', esc(GI.teamAbbr(top)) + ' ' + GI.signed(100 * v(top, ks[0][0]), 1) + ' pts', 'pass rate over expected, ' + ks[0][1].toLowerCase() + ' situations', { href: thref(top) }) : '',
      low ? GI.kpi('Most run-first', esc(GI.teamAbbr(low)) + ' ' + GI.signed(100 * v(low, ks[0][0]), 1) + ' pts', 'pass rate over expected, ' + ks[0][1].toLowerCase() + ' situations', { href: thref(low) }) : '']) +
    GI.grid(GI.card('Pass rate over expected', ks[0][1] + ' situations (early downs, win chance 20-80%, outside the last two minutes of a half), every team', GI.chartBox('tm-proe', Math.max(420, list.length * 20 + 40), 'Pass rate over expected by team'), { span: 6 }) +
      GI.card('By situation', 'Percentage points over (+) or under (−) the expected pass rate · red passes more, blue runs more', GI.heatTable({ corner: 'Team', center: 0, max: 0.12, invert: true, cols: ks.map(k => ({ label: k[1] })),
        rows: list.map(t => ({ label: GI.teamLink(t, { abbr: true, season: ST.S }), values: ks.map(k => v(t, k[0])), fmts: ks.map(() => (x => GI.signed(100 * x, 1))) })) }), { span: 6, flush: true }));
  GI.ch.bar('tm-proe', { cats: list.map(t => GI.teamName(t)), series: [{ name: 'Pass rate over expected', data: list.map(t => 100 * v(t, ks[0][0])) }], horizontal: true, diverging: true, labels: true, fmt: x => GI.signed(x, 1), hrefs: list.map(t => thref(t)), labelWidth: 150, valName: 'Pass rate over expected (percentage points)', catName: 'Team' });
}

})(window.GI);
