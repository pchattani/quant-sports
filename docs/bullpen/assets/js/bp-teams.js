/* The Quant Bullpen — the Teams page (#/<L>/teams), round 8 (28 Oct 2026; the pilot for the other seven sites): every
 * club ranked, profiled and set against the rest. It replaces the catalogue table of teams.js (whose team pages,
 * #/<L>/team/<tid>, stay there). Kit: scout.js (QK.powerBars, QK.heatGrid, QK.strengths), quant.js (QK.tape with
 * gap: true), quant-charts.js (QKC.scatter, QKC.line).
 *
 * Sections (a chip strip jumps between them):
 *   1. Power board: each club ranked by our team rating, a bar split into offence, pitching and defence around zero
 *      (the rating is the volt tick), the record, run differential, our expected record, the last ten, and our postseason
 *      and title chances, quiet (MLB, from the season simulation); Division | League | All (?pw=).
 *   2. Team profile: the heat grid of clubs by the 82 team metrics, phase groups as chips (Overview, Offence, Pitching,
 *      Contact quality, Defence and baserunning, Staff, Record and luck, Value, Our models), percentile cells, sortable,
 *      rows linked, any metric added, CSV (?grid=, gadd=, gsort=).
 *   3. Style map: any two team metrics, presets (offence against run prevention, power against contact, Stuff+ against
 *      Location+, range against framing, rotation against bullpen, our rating against the record), the medians and the
 *      four corners named (?map=, mx=, my=).
 *   4. Strengths and weaknesses: each club's three best and three worst metrics against the league, as percentile chips.
 *   5. Head to head: two clubs on the tale of the tape with the gap in percentile points (?a=, b=).
 *   6. Through the season: run differential game by game for the clubs picked (every level; derived from the game log
 *      in teams.json, no new data), and our postseason chance day by day (MLB, data/mlb/race_log.json) (?trend=, clubs=).
 * Percentiles are the payload's (teams.json "pct", 100 = best, lower-is-better flipped); a metric the payload has no
 * percentile for is ranked among the clubs on screen. The full standings stay on the Standings page.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const U = () => BP.ui;
const esc = s => BP.esc(s);
const isNum = v => typeof v === 'number' && isFinite(v);

const ST = { L: 'mlb', S: null, pw: 'division', grid: '', gadd: [], gsort: null, map: 0, mx: '', my: '', a: '', b: '', trend: 'rd', clubs: [] };
let T = null, META = {}, MS = [], SEA = {}, RACE = null;

/* the phase groups of the profile grid */
const GRID_SETS = [
  ['overview', 'Overview', [['Ratings', ['rating', 'off_rpg', 'pit_rpg', 'def_rpg']], ['Record', ['pct', 'pythag', 'baseruns_pct', 'rd', 'luck']], ['Value', ['war', 'p_postseason', 'p_ws']]]],
  ['offence', 'Offence', [['Batting', ['off_rpg', 'xwoba_plus', 'woba', 'obp', 'slg', 'iso', 'ops', 'avg', 'hr']], ['Approach', ['k_pct', 'bb_pct', 'chase_pct', 'whiff_pct', 'dv']], ['Value', ['rv100', 'wpa_bat', 'war_bat']]]],
  ['pitching', 'Pitching', [['Run prevention', ['pit_rpg', 'ra9', 'fip', 'whip', 'hr9', 'woba_against', 'xwoba_plus_against']], ['Missing bats', ['p_k_pct', 'p_bb_pct', 'p_k_bb', 'csw_pct', 'p_chase_pct', 'p_whiff_pct']], ['Stuff', ['stuff_plus', 'location_plus', 'pitching_plus', 'fb_velo']]]],
  ['contact', 'Contact quality', [['At the plate', ['xwoba_plus', 'xwoba_savant', 'barrel_pct', 'hard_pct', 'ev', 'pull_air_pct', 'bat_speed']], ['Allowed', ['xwoba_plus_against', 'xwoba_against', 'p_barrel_pct', 'p_hard_pct', 'p_ev', 'p_gb_pct']]]],
  ['defence', 'Defence and baserunning', [['Defence', ['def_rpg', 'oaa', 'oaa_savant', 'fielding_runs', 'framing_runs']], ['Baserunning', ['bsr']]]],
  ['staff', 'Staff', [['Rotation', ['sp_ra9', 'sp_ip_share', 'war_sp']], ['Bullpen', ['rp_ra9', 'war_rp']], ['Staff', ['p_rv100', 'wpa_pit', 'war_pit', 'age_pit']]]],
  ['record', 'Record and luck', [['Record', ['w', 'l', 'pct', 'home_pct', 'away_pct', 'one_run_pct']], ['Runs', ['rs', 'ra', 'rd', 'pythag', 'pythag_w', 'luck', 'baseruns_rs', 'baseruns_ra', 'baseruns_pct', 'baseruns_w']]]],
  ['value', 'Value and age', [['WAR', ['war', 'war_bat', 'war_pit', 'war_sp', 'war_rp']], ['Age', ['age_bat', 'age_pit']]]]
];
/* metrics a strength or weakness is read from: the process and the ratings, not counts, ages or chances */
const SW_POOL = ['off_rpg', 'pit_rpg', 'def_rpg', 'xwoba_plus', 'obp', 'iso', 'k_pct', 'bb_pct', 'barrel_pct', 'hard_pct', 'chase_pct', 'whiff_pct', 'bat_speed', 'dv', 'bsr',
  'fip', 'p_k_pct', 'p_bb_pct', 'hr9', 'xwoba_plus_against', 'stuff_plus', 'location_plus', 'csw_pct', 'p_chase_pct', 'p_barrel_pct', 'p_hard_pct', 'fb_velo', 'sp_ra9', 'rp_ra9', 'oaa', 'framing_runs'];
const H2H = [['Strength', ['rating', 'off_rpg', 'pit_rpg', 'def_rpg', 'baseruns_pct', 'rd']], ['Batting', ['xwoba_plus', 'obp', 'iso', 'k_pct', 'bb_pct', 'barrel_pct', 'chase_pct', 'bsr']],
  ['Pitching', ['fip', 'xwoba_plus_against', 'stuff_plus', 'location_plus', 'p_k_bb', 'csw_pct', 'p_barrel_pct', 'sp_ra9', 'rp_ra9']], ['Defence', ['oaa', 'framing_runs']]];
/* style map presets: [label, x, y, corners { tl, tr, bl, br }] (better is always up and to the right) */
const PRESETS = [
  ['Offence against run prevention', 'off_rpg', 'prev_rpg', { tl: 'Pitch and catch', tr: 'Complete clubs', bl: 'Rebuilding', br: 'Slug it out' }],
  ['Power against contact', 'barrel_pct', 'k_pct', { tl: 'Contact, little pop', tr: 'Power and contact', bl: 'Neither', br: 'All or nothing' }],
  ['Stuff+ against Location+', 'stuff_plus', 'location_plus', { tl: 'Command staffs', tr: 'Nasty and precise', bl: 'Hittable', br: 'Raw stuff' }],
  ['Range against framing', 'oaa', 'framing_runs', { tl: 'Framing carries it', tr: 'Glove and frame', bl: 'Leaky', br: 'Range carries it' }],
  ['Rotation against bullpen', 'sp_ra9', 'rp_ra9', { tl: 'Bullpen-led', tr: 'Deep staffs', bl: 'Thin staffs', br: 'Rotation-led' }],
  ['Our rating against the record', 'rating', 'pct', { tl: 'Winning on luck?', tr: 'The real deal', bl: 'Struggling', br: 'Due a run' }]
];
/* labels on this page: the batting metrics say so (a club's K% at the plate is not its staff's) */
const BAT_SAY = { k_pct: 'Lineup K%', bb_pct: 'Lineup BB%', barrel_pct: 'Lineup barrel%', hard_pct: 'Lineup hard-hit%', ev: 'Lineup exit velocity', chase_pct: 'Lineup chase%',
  whiff_pct: 'Lineup whiff%', hr: 'Home runs hit', pull_air_pct: 'Lineup pull-air%', bat_speed: 'Lineup bat speed', avg: 'Batting AVG', obp: 'OBP', slg: 'SLG', ops: 'OPS', iso: 'ISO',
  woba: 'Lineup wOBA', xwoba_plus: 'Lineup xwOBA+', xwoba_savant: 'Lineup xwOBA (Savant)', dv: 'Swing decisions' };
function meta(id) {
  if (id === 'prev_rpg') return { id: id, label: 'Run prevention (runs/game)', short: 'Prevention', tip: 'Pitching plus defence: runs saved per game against an average club (our team ratings).', lower: false, fmt: v => K().signed(v, 2), ours: U().ours('pit_rpg') };
  const m = META[id] || { label: id };
  const label = BAT_SAY[id] || U().label('team', id, m.label || id).replace(/ \(ours\)$/, '');
  const d = (U().MDESC.team || {})[id];
  const ours = U().ours(id);
  const tip = (d && d[1]) || m.desc || '';
  return { id: id, label: label, short: label, tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''), lower: !!m.lower, style: /^age_/.test(id), ours: ours,
    fmt: v => (m.fmt === 'prob' ? QK.fmt.pct(v) : K().fmtV(v, m.fmt)) };
}
function v(t, id) {
  const x = ((T[t] || {}).values || {});
  if (id === 'prev_rpg') return isNum(x.pit_rpg) && isNum(x.def_rpg) ? x.pit_rpg + x.def_rpg : null;
  return isNum(x[id]) ? x[id] : null;
}
/* the payload's percentile (100 = best), else ranked among the clubs */
function pc(t, id) {
  const p = ((T[t] || {}).pct || {})[id];
  if (isNum(p) && id !== 'prev_rpg') return p;
  const xs = Object.keys(T).map(x => v(x, id)).filter(isNum).sort((a, b) => a - b), y = v(t, id);
  if (!isNum(y) || xs.length < 5) return null;
  const q = QK.pctRank(xs, y);
  return meta(id).lower ? 100 - q : q;
}
function rec(t) { const r = SEA[t] || {}, x = (T[t] || {}).values || {}; const w = isNum(r.w) ? r.w : x.w, l = isNum(r.l) ? r.l : x.l; return isNum(w) && isNum(l) ? w + '–' + l : '—'; }
function tinfo(t) { const x = T[t] || {}, i = BP.teamInfo(t) || {}; return { abbr: x.abbr || K().teamAbbr(t), name: x.name || K().teamName(t), short: x.short || i.short || x.name, colour: x.colour || i.colour || '', alt: x.alt || i.alt || '', league: x.league || i.league || '', division: x.division || i.division || '' }; }
function thref(t) { return K().teamHref(ST.L, t, ST.S); }
function ids() { return Object.keys(T).filter(t => isNum(v(t, 'g')) || isNum(v(t, 'rating'))); }
function byRating(list) { return list.slice().sort((a, b) => (v(b, 'rating') || -9) - (v(a, 'rating') || -9)); }

/* ── address ─────────────────────────────────────────────────────────────── */
function readQ(q) {
  q = q || {};
  ST.pw = ['division', 'league', 'all'].indexOf(q.pw) >= 0 ? q.pw : 'division';
  ST.grid = q.grid || ''; ST.gadd = q.gadd ? String(q.gadd).split(',').filter(Boolean) : [];
  ST.gsort = q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null;
  const mp = parseInt(q.map, 10); ST.map = isNaN(mp) ? 0 : mp; ST.mx = q.mx || ''; ST.my = q.my || '';
  ST.a = q.a || ''; ST.b = q.b || ''; ST.trend = q.trend === 'ps' ? 'ps' : 'rd'; ST.clubs = q.clubs ? String(q.clubs).split(',').filter(Boolean) : [];
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
  if (ST.trend !== 'rd') q.trend = ST.trend;
  if (ST.clubs.length) q.clubs = ST.clubs.join(',');
  if (ST.S && ST.S !== K().curSeason(ST.L)) q.s = ST.S;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  try { history.replaceState(null, '', '#/' + ST.L + '/teams' + (qs ? '?' + qs : '')); } catch (e) { /* no history API */ }
}

/* ── render ──────────────────────────────────────────────────────────────── */
const SECS = [['tm-power', 'Power board'], ['tm-grid', 'Team profile'], ['tm-map', 'Style map'], ['tm-sw', 'Strengths and weaknesses'], ['tm-h2h', 'Head to head'], ['tm-trend', 'Through the season']];
function render(el, params, state) {
  const k = K();
  ST.L = k.L(params, state);
  readQ(params.query || {});
  el.innerHTML = '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(s => '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[1]) + '</a>').join('') + '</div></nav>' +
    SECS.map(s => '<section class="qk-section tm-sec" id="' + s[0] + '">' + QK.skeleton('lines', 3) + '</section>').join('');
  el.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const t = document.getElementById(a.getAttribute('data-jump'));
    if (!t) return;
    const off = ['.qk-topbar', '.qk-secnav'].reduce((s, q) => s + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + 12;
    window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth' });
  }));
  return k.ready().then(() => {
    ST.S = k.S(params, state);
    return Promise.all([k.loadY(ST.L, ST.S, 'teams.json'), k.loadY(ST.L, ST.S, 'season.json'), U().specReady(), ST.L === 'mlb' ? BP.load(ST.L + '/race_log.json') : Promise.resolve(null)]);
  }).then(res => {
    if (!k.alive(el)) return;
    const cat = res[0], sea = res[1];
    if (!cat || cat.ok === false || !cat.teams) { el.innerHTML = QK.empty('Not built yet', 'The ' + k.LN(ST.L) + ' ' + ST.S + ' team file is not available.'); return; }
    T = cat.teams; MS = (cat.metrics || []).map(m => (m && /\bodds\b/i.test(m.label || '') ? Object.assign({}, m, { label: m.label.replace(/\bodds\b/gi, 'chance') }) : m));
    META = {}; MS.forEach(m => { META[m.key] = m; });
    Object.keys(T).forEach(t => k.learnTeam(t, T[t]));
    SEA = {};
    const stn = (sea && sea.standings) || {};
    Object.keys(stn).forEach(d => (stn[d] || []).forEach(r => { if (r && r.tid) SEA[String(r.tid)] = Object.assign({ division: d }, r); }));
    ST.sim = !!(sea && sea.sim && sea.sim.available);
    RACE = res[3] && res[3][String(ST.S)] ? res[3][String(ST.S)] : null;
    BP.setMeta(k.LN(ST.L) + ' ' + ST.S + ' · ' + ids().length + ' clubs · ' + MS.length + ' team metrics');
    power(); grid(); styleMap(); strengths(); h2h(); trend();
  });
}

/* 1. the power board */
function power() {
  const host = document.getElementById('tm-power');
  if (!host) return;
  const k = K(), all = byRating(ids());
  const rk = {}; all.forEach((t, i) => { rk[t] = i + 1; });
  const form = t => ((T[t] || {}).log || []).filter(g => g[2] === 'R' && (g[7] === 'W' || g[7] === 'L')).slice(-10).map(g => g[7]).join('');
  const row = t => {
    const i = tinfo(t), r = SEA[t] || {}, x = (T[t] || {}).values || {};
    const rd = isNum(r.rd) ? r.rd : x.rd, ew = isNum(r.exp_w) ? r.exp_w : null, g = (isNum(r.w) ? r.w : x.w || 0) + (isNum(r.l) ? r.l : x.l || 0);
    return { rank: rk[t], name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + (r.streak ? ' · ' + r.streak : ''), value: v(t, 'rating'), text: k.signed(v(t, 'rating'), 2),
      parts: { off: v(t, 'off_rpg'), pit: v(t, 'pit_rpg'), def: v(t, 'def_rpg') },
      cells: [{ label: 'Run diff', text: isNum(rd) ? k.signed(rd, 0) : '—' }, { label: 'Expected', text: isNum(ew) && g ? Math.round(ew) + '–' + Math.round(g - ew) : '—' }],
      form: form(t), chances: ST.sim ? [{ label: 'Postseason', p: r.p_postseason, text: r.p_postseason === 1 ? 'In' : r.p_postseason === 0 ? 'Out' : '' }].concat(r.p_postseason === 0 ? [] : [{ label: 'Title', p: r.p_ws }]) : [] };
  };
  let groups;
  if (ST.pw === 'all') groups = [{ label: '', rows: all.map(row) }];
  else {
    const keyOf = t => { const i = tinfo(t); return ST.pw === 'league' ? (i.league || (SEA[t] || {}).league || '') : (i.division || (SEA[t] || {}).division || ''); };
    const names = Array.from(new Set(all.map(keyOf))).sort((a, b) => a.localeCompare(b));
    groups = names.map(n => ({ label: n || 'Clubs', rows: all.filter(t => keyOf(t) === n).map(row) }));
  }
  const lg = ST.L === 'aaa' ? 'Triple-A' : 'MLB';
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: 'Every club, ranked by our rating', sub: 'Our team rating is the run differential per game we expect against an average club. The bar splits it into offence (batting and baserunning), pitching and defence (fielding and framing); the volt tick is the total.' +
    (ST.sim ? ' Postseason and title chances come from 20,000 simulated seasons.' : ''), actions: U().seg('tm-pw', 'Group the board', [['division', 'Division'], ['league', 'League'], ['all', 'All ' + ids().length]], ST.pw) }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(null, { groups: groups, valueLabel: 'Our rating', unit: 'runs per game against an average club', formLabel: 'Last 10',
      parts: [{ key: 'off', label: 'Offence', color: 'var(--c-2)' }, { key: 'pit', label: 'Pitching', color: 'var(--c-3)' }, { key: 'def', label: 'Defence', color: 'var(--c-5)' }] }) + '</div></div>' +
    QK.explain('A <b>rating of +1.0</b> means the club scores about one run a game more than it allows against an average opponent: over a season that is roughly 16 extra wins. “Expected” is the record our ratings say the run production deserved. The full table is on <a href="' + BP.href('standings', ST.L, ST.S) + '">Standings</a>.', { title: 'What’s that number?' });
  const seg = document.getElementById('tm-pw');
  if (seg) QK.seg(seg, x => { ST.pw = x; writeQ(); power(); });
}

/* 2. the team profile grid */
function grid() {
  const host = document.getElementById('tm-grid');
  if (!host) return;
  const k = K(), have = id => MS.some(m => m.key === id) && ids().some(t => isNum(v(t, id)));
  const sets = GRID_SETS.map(s => ({ key: s[0], label: s[1], groups: s[2].map(g => ({ label: g[0], ids: g[1].filter(have) })).filter(g => g.ids.length) })).filter(s => s.groups.length);
  const ours = MS.filter(m => U().ours(m.key) && have(m.key)).map(m => m.key);
  if (ours.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: ours }] });
  const used = {}; sets.forEach(s => s.groups.forEach(g => g.ids.forEach(id => { used[id] = 1; })));
  const rest = MS.filter(m => !used[m.key] && have(m.key)).map(m => m.key);
  if (rest.length) sets.push({ key: 'more', label: 'More', groups: [{ label: 'More', ids: rest }] });
  const rows = byRating(ids()).map(t => { const i = tinfo(t); return { id: t, name: i.name, sub: rec(t) + ' · ' + (i.division || i.league || ''), mark: { abbr: i.abbr, colour: i.colour }, href: thref(t) }; });
  const groupsOpt = k.groups(MS).map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '">' + esc(meta(m.key).label) + '</option>').join('') + '</optgroup>').join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: ids().length + ' clubs, every metric', sub: 'Each cell is the club’s value, coloured by its percentile among the ' + ids().length + ' (blue worst, red best; a ↓ marks a metric where lower is better, grey is style). Pick a phase, add any of the ' + MS.length + ' metrics, sort by any column, tap a club for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(s => s.key === ST.grid) ? ST.grid : 'overview', setsLabel: 'Phase', added: ST.gadd.filter(have), sort: ST.gsort || { key: 'rating', dir: 'desc' },
    nameLabel: 'Club', subLabel: 'Record · division', noun: 'clubs', meta: meta, addable: groupsOpt,
    rows: rows, val: (r, id) => v(r.id, id),
    csv: 'bullpen-' + ST.L + '-' + ST.S + '-teams.csv',
    onState: st => { ST.grid = st.set === 'overview' ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; writeQ(); }
  });
}

/* 3. the style map */
function styleMap() {
  const host = document.getElementById('tm-map');
  if (!host) return;
  const opts = MS.filter(m => ids().some(t => isNum(v(t, m.key)))).map(m => ({ value: m.key, label: meta(m.key).label }));
  opts.unshift({ value: 'prev_rpg', label: meta('prev_rpg').label });
  const P = PRESETS.filter(p => ids().filter(t => isNum(v(t, p[1])) && isNum(v(t, p[2]))).length >= 5);
  if (ST.map >= P.length) ST.map = 0;
  const cur = ST.map >= 0 ? P[ST.map] : null;
  const x = cur ? cur[1] : (ST.mx || 'off_rpg'), y = cur ? cur[2] : (ST.my || 'prev_rpg');
  const sel = (id, val) => '<select class="qk-select" id="' + id + '">' + opts.map(o => '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>').join('') + '</select>';
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each club wins', sub: 'Any two team metrics against each other. The dashed lines are the league medians; better is always up and to the right (axes where less is better are flipped). Tap a club for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map((p, i) => '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p[0]) + '</option>').join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:520px;margin-top:16px" role="img" aria-label="Style map"></div><p class="bp-note" id="tm-map-n"></p></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-preset').onchange = e => { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } writeQ(); styleMap(); };
  $('tm-mx').onchange = e => { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; writeQ(); styleMap(); };
  $('tm-my').onchange = e => { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; writeQ(); styleMap(); };
  const mx = meta(x), my = meta(y);
  const pts = ids().filter(t => isNum(v(t, x)) && isNum(v(t, y))).map(t => { const i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name + ' · ' + rec(t), label: i.abbr, color: i.colour || null, size: 15, href: thref(t) }; });
  const med = a => K().median(a);
  const corners = cur ? cur[3] : { tl: '', tr: 'Better on both', bl: 'Worse on both', br: '' };
  const qd = [corners.tl, corners.tr, corners.bl, corners.br];
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: med(pts.map(p => p.x)), refY: med(pts.map(p => p.y)), xInverse: mx.lower, yInverse: my.lower,
    pad: '9%',
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: mx.fmt, yFmt: my.fmt,
    quadrants: qd, label: my.label + ' against ' + mx.label });
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
    const best = xs.slice().sort((a, b) => b.p - a.p).slice(0, 3).map(chip), worst = xs.slice().sort((a, b) => a.p - b.p).slice(0, 3).map(chip);
    return QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + ' · rating ' + K().signed(v(t, 'rating'), 2), best: best, worst: worst });
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each club does best, and worst', sub: 'Each club’s three best and three worst of ' + pool.length + ' process metrics and ratings, as percentiles among the ' + ids().length + ' clubs (100 = best). Ordered by our rating.' }) +
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
  }) }));
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: QK.surname(A.short || A.name) + ' or ' + QK.surname(B.short || B.name) + '?', sub: 'Two clubs on the metrics that decide games. Bars are percentiles among the ' + list.length + ' clubs; the small line under each metric is the gap in percentile points and who leads it.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Club', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: rec(ST.a) + ' · ' + K().signed(v(ST.a, 'rating'), 2), colour: A.colour, alt: A.alt, href: thref(ST.a) },
      right: { name: B.name, short: B.abbr, sub: rec(ST.b) + ' · ' + K().signed(v(ST.b, 'rating'), 2), colour: B.colour, alt: B.alt, href: thref(ST.b) }, groups: groups, wins: true, gap: true }) + '</div></div></div>';
  const $ = id => document.getElementById(id);
  $('tm-a').onchange = e => { ST.a = e.target.value; writeQ(); h2h(); };
  $('tm-b').onchange = e => { ST.b = e.target.value; writeQ(); h2h(); };
  $('tm-swap').onclick = () => { const t = ST.a; ST.a = ST.b; ST.b = t; writeQ(); h2h(); };
}

/* 6. through the season: run differential game by game (the game log), our postseason chance day by day (MLB race log) */
function trend() {
  const host = document.getElementById('tm-trend');
  if (!host) return;
  const list = byRating(ids());
  const logOf = t => ((T[t] || {}).log || []).filter(g => g[2] === 'R' && isNum(g[5]) && isNum(g[6]));
  if (!list.some(t => logOf(t).length)) { host.innerHTML = ''; return; }
  const ps = RACE && RACE.p_postseason ? RACE.p_postseason : null;
  if (ST.trend === 'ps' && !ps) ST.trend = 'rd';
  let clubs = ST.clubs.filter(t => T[t]);
  if (!clubs.length) {
    const top = list[0], dv = tinfo(top).division;
    clubs = list.filter(t => tinfo(t).division === dv);
    if (clubs.length < 2) clubs = list.slice(0, 5);
  }
  const chips = list.slice().sort((a, b) => tinfo(a).abbr.localeCompare(tinfo(b).abbr)).map(t => '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '">' + esc(tinfo(t).abbr) + '</button>').join('');
  const divs = Array.from(new Set(list.map(t => tinfo(t).division).filter(Boolean))).sort();
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: ST.trend === 'ps' ? 'The race, day by day' : 'Run differential, game by game', sub: ST.trend === 'ps' ? 'Our postseason chance for each club on each day of the season, from the season simulation as it stood that day.' : 'Runs scored minus runs allowed, added up over the regular season, from each club’s game log. A line that climbs is outscoring its opponents.',
    actions: ps ? U().seg('tm-tr', 'Measure', [['rd', 'Run differential'], ['ps', 'Postseason chance']], ST.trend) : '' }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">Clubs</span><div class="qk-chips">' + chips + '</div>' +
    (divs.length ? '<div class="qk-chips tm-divs">' + divs.map(d => '<button type="button" class="qk-chip" data-div="' + esc(d) + '">' + esc(d) + '</button>').join('') + '<button type="button" class="qk-chip" data-div="*top">Top five</button></div>' : '') +
    '</div><div id="tm-tr-c" class="qk-chart" style="--h:460px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  const T0 = QKC.tokens();
  const colOf = (t, i) => { const c = tinfo(t).colour; return c && QK.color.parse(c) ? QK.color.team(c) : T0.cat[i % 8]; };
  if (ST.trend === 'ps') {
    const dates = Object.keys(ps).sort();
    QKC.line(document.getElementById('tm-tr-c'), { x: dates.map(d => QK.fmt.date(d + 'T12:00:00', { day: 'numeric', month: 'short' })), series: clubs.map((t, i) => ({ name: tinfo(t).abbr, color: colOf(t, i), data: dates.map(d => { const p = (ps[d] || {})[t]; return isNum(p) ? Math.round(p * 1000) / 10 : null; }) })),
      yName: 'Postseason chance (%)', xName: 'Date', yMin: 0, yMax: 100, yFmt: x => x + '%', endLabels: true, label: 'Our postseason chance by day' });
  } else {
    const series = clubs.map((t, i) => { let s = 0; return { name: tinfo(t).abbr, color: colOf(t, i), data: logOf(t).map((g, j) => { s += g[5] - g[6]; return [j + 1, s]; }) }; });
    const n = Math.max.apply(null, series.map(x => x.data.length).concat([1]));
    QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', x: Array.from({ length: n }, (_, j) => j + 1), series: series, yName: 'Run differential (runs)', xName: 'Games played', xMin: 0, xMax: n, ref: { y: 0, label: 'Even' }, endLabels: true, label: 'Run differential through the season' });
  }
  host.querySelectorAll('[data-club]').forEach(b => b.addEventListener('click', () => {
    const t = b.getAttribute('data-club');
    const cur = clubs.slice();
    const i = cur.indexOf(t);
    if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else if (cur.length < 8) cur.push(t);
    ST.clubs = cur; writeQ(); trend();
  }));
  host.querySelectorAll('[data-div]').forEach(b => b.addEventListener('click', () => {
    const d = b.getAttribute('data-div');
    ST.clubs = d === '*top' ? list.slice(0, 5) : list.filter(t => tinfo(t).division === d);
    writeQ(); trend();
  }));
  const seg = document.getElementById('tm-tr');
  if (seg) QK.seg(seg, x => { ST.trend = x; writeQ(); trend(); });
}

if (typeof BP.route === 'function') { BP.route('teams', render); try { BP.route('#/<L>/teams', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
