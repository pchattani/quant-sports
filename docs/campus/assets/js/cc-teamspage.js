/* The Quant Campus — the Teams page (#/<L>/teams), round 9 (28 Oct 2026; the Bullpen pilot, bp-teams.js, is the
 * reference): every FBS / Division I team ranked, profiled and set against the rest. It replaces the catalogue table
 * (cc-teams.js keeps the team pages, #/<L>/team/<tid>) and takes in Standings › Team cards (the strengths chips and the
 * offence-v-defence map) and Polls › "Our power ranking" (the power board). Kit: scout.js (QK.powerBars, QK.heatGrid,
 * QK.strengths), quant.js (QK.tape with gap: true), quant-charts.js (QKC.scatter, QKC.line).
 *
 * Sections (a chip strip jumps between them):
 *   1. Power board: our rating split into offence and defence around zero (the volt tick is the total), the record,
 *      the AP rank, the move in our ranking since last week, schedule strength, and our playoff (CFP / NCAA field) and
 *      title chances, quiet; Top 25 | By conference | All (?pw=).
 *   2. Team profile: the heat grid of teams by every team metric in teams.json, phase groups as chips (Overview = the
 *      spec's headline set, then the payload's groups and "Our models"), percentile cells against every team in the
 *      country, sortable, rows linked, any metric added, CSV (?grid=, gadd=, gsort=, gdir=); scoped by ?scope=.
 *   3. Style map: any two team metrics, sport presets with the corners named (football: offence against defence, pass
 *      against rush, success against explosiveness, our rating against the record; basketball: offence against
 *      defence, pace against efficiency, three-point rate against shooting, rebounding against turnovers), medians
 *      (?map=, mx=, my=). The one offence-v-defence team scatter on the site.
 *   4. Strengths and weaknesses: each team's three best and three worst process metrics as percentile chips, with the
 *      plain-English chips the Team cards had ("Elite offence", "Turnover-prone", "Plays fast", "Riding luck").
 *   5. Head to head: two teams on the tale of the tape with the gap in percentile points (?a=, b=).
 *   6. Through the season: our rating week by week (season.json rating_paths) and, this season, our playoff /
 *      tournament chance day by day (<L>/race_log.json) for the teams picked (?trend=, clubs=).
 * Scope (?scope=top|<conference id>): the top 25 by our rating, or one conference, for the grid and the cards.
 * Reads <L>/<S>/teams.json, season.json and <L>/race_log.json. Older-browser rule: no optional chaining, no nullish
 * coalescing. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;
var POWER = { cfb: ['SEC', 'Big Ten', 'Big 12', 'ACC'], mbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'], wbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'],
  mch: ['HEA', 'B1G', 'NCHC', 'ECAC', 'CCHA', 'AHA'], wch: ['WCHA', 'HEA', 'ECAC', 'NEWHA', 'AHA'] };
var PYTH = { cfb: 2.37, mbb: 11.5, wbb: 10.0, mch: 2.0, wch: 2.0 };

var ST = { L: 'cfb', S: null, pw: 'top', scope: 'top', grid: '', gadd: [], gsort: null, map: 0, mx: '', my: '', a: '', b: '', trend: 'rating', clubs: [] };
var T = null, META = {}, MS = [], SEA = null, R = {}, SIM = {}, REC = {}, RACE = null, AP = {};

/* style map presets: [label, x, y, corners [tl, tr, bl, br]] (better is always up and to the right; lower-is-better axes flip) */
var PRESETS = {
  cfb: [['Offence against defence', 'off', 'def', ['Defence first', 'Complete teams', 'Struggling', 'Outscore you']],
    ['Passing against rushing (offence, opponent-adjusted EPA)', 'off_pass_epa', 'off_rush_epa', ['Run first', 'Balanced and dangerous', 'Stuck', 'Air it out']],
    ['Success rate against explosiveness', 'sr_off', 'explosive', ['Big plays, little else', 'Efficient and explosive', 'Neither', 'Down-to-down grinders']],
    ['Pass defence against run defence', 'def_pass_epa', 'def_rush_epa', ['Stop the run', 'Lockdown', 'Leaky', 'Stop the pass']],
    ['Our rating against points scored', 'rating', 'ppg', ['Points over process', 'Elite both ways', 'Struggling', 'Better than the scoreboard']]],
  bb: [['Offence against defence', 'off', 'def', ['Defence first', 'Complete teams', 'Struggling', 'Outscore you']],
    ['Pace against efficiency', 'tempo', 'rating', ['Slow and good', 'Fast and good', 'Slow and struggling', 'Run and gun']],
    ['Three-point rate against shooting', 'tpar', 'efg', ['Efficient inside', 'Shoot and make', 'Struggling to score', 'Live by the three']],
    ['Offensive rebounding against ball security', 'orb_rate', 'tov_rate', ['Careful', 'Extra possessions', 'Wasteful', 'Crash the glass']],
    ['Our rating against win %', 'rating', 'wpct', ['Winning on luck?', 'The real deal', 'Struggling', 'Due a run']]],
  /* college hockey (better up and to the right; lower-is-better axes flip) */
  hk: [['Attack against defence', 'off', 'def', ['Defence first', 'Complete teams', 'Struggling', 'Outscore you']],
    ['Shot share against PDO (shooting % + save %)', 'shot_share', 'pdo', ['Riding the bounces', 'Dominant and finishing', 'Struggling', 'Outshooting, unrewarded']],
    ['Power play against penalty kill', 'pp_pct', 'pk_pct', ['Kill first', 'Special teams win games', 'Special teams cost games', 'Score on the power play']],
    ['Shots for against shots against', 'sf_pg', 'sa_pg', ['Tight defence', 'Control the play', 'Chasing the game', 'Run and gun']],
    ['Our rating against points %', 'rating', 'wpct', ['Winning on luck?', 'The real deal', 'Struggling', 'Due a run']]]
};
/* head to head */
var H2H = {
  cfb: [['Strength', ['rating', 'off', 'def', 'sos']], ['Offence', ['epa_off', 'sr_off', 'off_pass_epa', 'off_rush_epa', 'explosive', 'third_pct', 'ypp']], ['Defence', ['epa_def', 'sr_def', 'def_pass_epa', 'def_rush_epa', 'ypp_allowed']], ['Results', ['ppg', 'papg', 'to_margin']]],
  bb: [['Strength', ['rating', 'off', 'def', 'sos', 'tempo']], ['Offence', ['efg', 'tpar', 'tp_pct', 'ftr', 'ft_pct', 'tov_rate', 'orb_rate', 'ast_rate']], ['Defence', ['opp_efg', 'opp_tov_rate', 'drb_rate', 'blk_rate']]],
  hk: [['Strength', ['rating', 'off', 'def', 'sos']], ['Shots', ['shot_share', 'sf_pg', 'sa_pg', 'sh_pct', 'sv_pct', 'pdo']], ['Special teams', ['pp_pct', 'pk_pct', 'ppo_pg', 'tsh_pg', 'pim_pg']], ['Results', ['gf_pg', 'ga_pg', 'wpct']]]
};
/* metrics a strength or weakness is read from: the process and the ratings, not results or style */
var SW_POOL = {
  cfb: ['off', 'def', 'epa_off', 'epa_def', 'sr_off', 'sr_def', 'off_pass_epa', 'off_rush_epa', 'def_pass_epa', 'def_rush_epa', 'explosive', 'third_pct', 'ypp', 'ypp_allowed', 'to_margin'],
  bb: ['off', 'def', 'efg', 'opp_efg', 'tov_rate', 'opp_tov_rate', 'orb_rate', 'drb_rate', 'ft_pct', 'tp_pct', 'ftr', 'ast_rate', 'blk_rate'],
  hk: ['off', 'def', 'shot_share', 'sf_pg', 'sa_pg', 'sh_pct', 'sv_pct', 'pp_pct', 'pk_pct', 'pim_pg', 'ppo_pg']
};
/* the Team cards' plain-English chips: [metric, good at or above, text, bad at or below, text] */
var CHIP = {
  cfb: [['off', 90, 'Elite offence', 15, 'Struggling offence'], ['def', 90, 'Elite defence', 15, 'Leaky defence'], ['pass_epa', 85, 'Dangerous passing game', 12, 'Passing game stalls'],
    ['rush_epa', 85, 'Strong run game', 12, 'No run game'], ['explosive', 85, 'Big-play offence', 12, 'Few big plays'], ['sr_def', 88, 'Down-to-down defence', 12, 'Defence gives up steady gains'],
    ['to_margin', 85, 'Wins the turnover battle', 15, 'Turnover-prone'], ['third_pct', 88, 'Converts on third down', 12, 'Stalls on third down'], ['sos', 85, 'Battle-tested schedule', 12, 'Soft schedule so far']],
  bb: [['off', 90, 'Elite offence', 15, 'Struggling offence'], ['def', 90, 'Elite defence', 15, 'Leaky defence'], ['efg', 88, 'Efficient shooting', 12, 'Poor shot quality'],
    ['opp_efg', 88, 'Contests every shot', 12, 'Opponents shoot freely'], ['tov_rate', 88, 'Takes care of the ball', 12, 'Turnover-prone'], ['orb_rate', 88, 'Owns the offensive glass', 12, 'One shot and done'],
    ['opp_tov_rate', 88, 'Forces turnovers', null, null], ['ft_pct', 90, 'Reliable at the line', 10, 'Misses at the line'], ['sos', 85, 'Battle-tested schedule', 12, 'Soft schedule so far']],
  hk: [['off', 90, 'Elite attack', 15, 'Struggles to score'], ['def', 90, 'Elite defence', 15, 'Leaky defence'], ['shot_share', 88, 'Owns the puck', 12, 'Outshot most nights'],
    ['pp_pct', 88, 'Deadly power play', 12, 'Power play misfires'], ['pk_pct', 88, 'Shuts down power plays', 12, 'Penalty kill leaks'], ['sv_pct', 90, 'Hot in goal', 10, 'Goaltending trouble'],
    ['pim_pg', 88, 'Disciplined', 12, 'Penalty-prone'], ['sos', 85, 'Battle-tested schedule', 12, 'Soft schedule so far']]
};
var STYLE = { tempo: [80, 'Plays fast', 20, 'Slows it down'], tpar: [85, 'Lives behind the arc', 15, 'Works inside the arc'] };

function fb() { return CC.fb(ST.L); }
function hk() { return CC.hk(ST.L); }
function sp() { return fb() ? 'cfb' : hk() ? 'hk' : 'bb'; }
function meta(id) {
  var m = META[id] || { key: id, label: id };
  var sm = CC.specMeta(ST.L, 'team', id), ours = CC.ours(id);
  var label = CC.uk(sm && sm.d ? sm.d : (m.label || id));
  var tip = CC.uk((sm && sm.x) || m.desc || '');
  return { id: id, label: label, short: label, tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''), ours: ours, lower: !!m.lower, style: id === 'tempo' || id === 'tpar' || !!(sm && sm.style),
    fmt: function (v) { return CC.fmtMetric(m.fmt ? m : { fmt: '2' }, v); }, group: CC.uk(m.group || 'Other') };
}
function v(t, id) { var x = ((T[t] || {}).values || {})[id]; return isNum(x) ? x : null; }
/* the payload's national percentile (100 = best, lower-is-better flipped); else ranked among every team */
function pc(t, id) {
  var p = ((T[t] || {}).pct || {})[id];
  if (isNum(p)) return p;
  var xs = ids().map(function (x) { return v(x, id); }).filter(isNum).sort(function (a, b) { return a - b; }), y = v(t, id);
  if (!isNum(y) || xs.length < 5) return null;
  var q = QK.pctRank(xs, y);
  return meta(id).lower ? 100 - q : q;
}
function tinfo(t) { var x = CC.team(ST.L, t) || {}; return { abbr: CC.tabbr(ST.L, t), name: x.name || (T[t] || {}).name || CC.tname(ST.L, t), short: x.short || x.name || CC.tshort(ST.L, t), colour: CC.traw(ST.L, t) || '', alt: CC.talt(ST.L, t) || '', conf: String(x.conference || (T[t] || {}).conference || '') }; }
function rec(t) { var r = REC[t] || T[t] || {}; return hk() ? CC.recW(r) : CC.record(r.w, r.l); }
function rating(t) { var x = R[t] || {}; return isNum(x.rating) ? x.rating : v(t, 'rating'); }
function ids() { return Object.keys(T).filter(function (t) { return isNum(rating(t)); }); }
function byRating(list) { return list.slice().sort(function (a, b) { return (rating(b) || -99) - (rating(a) || -99); }); }
function thref(t) { return CC.teamHref(ST.L, t, ST.S); }
function confOrder(cs) {
  var pw = POWER[ST.L] || [];
  return cs.slice().sort(function (a, b) { var na = CC.cname(ST.L, a), nb = CC.cname(ST.L, b), ia = pw.indexOf(na), ib = pw.indexOf(nb); if (ia < 0) ia = 99; if (ib < 0) ib = 99; return ia - ib || na.localeCompare(nb); });
}
function scoped() {
  var all = byRating(ids());
  if (ST.scope === 'all') return all;
  if (ST.scope === 'top') return all.slice(0, 25);
  return all.filter(function (t) { return tinfo(t).conf === ST.scope; });
}
function scopeName() { return ST.scope === 'top' ? 'our top 25' : ST.scope === 'all' ? 'every team' : CC.cname(ST.L, ST.scope); }

/* ── address ─────────────────────────────────────────────────────────────── */
function readQ(q) {
  q = q || {};
  ST.pw = ['top', 'conf', 'all'].indexOf(q.pw) >= 0 ? q.pw : 'top';
  ST.scope = q.scope || q.conf || 'top';
  ST.grid = q.grid || ''; ST.gadd = q.gadd ? String(q.gadd).split(',').filter(Boolean) : [];
  ST.gsort = q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null;
  var mp = parseInt(q.map, 10); ST.map = isNaN(mp) ? 0 : mp; ST.mx = q.mx || ''; ST.my = q.my || '';
  ST.a = q.a || ''; ST.b = q.b || ''; ST.trend = q.trend === 'chance' ? 'chance' : 'rating'; ST.clubs = q.clubs ? String(q.clubs).split(',').filter(Boolean) : [];
}
function writeQ() {
  var q = [];
  var add = function (k, x) { if (x !== '' && x !== null && x !== undefined) q.push(encodeURIComponent(k) + '=' + encodeURIComponent(x)); };
  if (ST.pw !== 'top') add('pw', ST.pw);
  if (ST.scope !== 'top') add('scope', ST.scope);
  add('grid', ST.grid);
  if (ST.gadd.length) add('gadd', ST.gadd.join(','));
  if (ST.gsort && ST.gsort.key && !(ST.gsort.key === 'rating' && ST.gsort.dir === 'desc')) { add('gsort', ST.gsort.key); add('gdir', ST.gsort.dir); }
  if (ST.map) add('map', ST.map);
  if (ST.map < 0) { add('mx', ST.mx); add('my', ST.my); }
  add('a', ST.a); add('b', ST.b);
  if (ST.trend !== 'rating') add('trend', ST.trend);
  if (ST.clubs.length) add('clubs', ST.clubs.join(','));
  try { history.replaceState(null, '', CC.href(ST.L, 'teams', null, ST.S, q.join('&'))); } catch (e) { /* no history API */ }
}

/* ── render ──────────────────────────────────────────────────────────────── */
var SECS = [['tm-power', 'Power board'], ['tm-grid', 'Team profile'], ['tm-map', 'Style map'], ['tm-sw', 'Strengths and weaknesses'], ['tm-cont', 'Roster continuity'], ['tm-h2h', 'Head to head'], ['tm-trend', 'Through the season']];
CC.route('teams', function (el, p) {
  ST.L = p.L; ST.S = p.S;
  readQ(p.query || {});
  el.innerHTML = U.head('Teams', '', U.kicker(ST.L, ST.S)) + QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(ST.L, ST.S, 'teams.json')), CC.season(ST.L, ST.S), CC.metrics(), CC.specP, CC.isCur(ST.L, ST.S) ? CC.load(CC.lpath(ST.L, 'race_log.json')) : Promise.resolve(null)]).then(function (a) {
    if (!U.alive(el)) return;
    var cat = a[0];
    if (!CC.ok(cat) || !cat.teams) { el.innerHTML = U.head('Teams', '', U.kicker(ST.L, ST.S)) + U.missing('The team catalogue', cat); return; }
    T = cat.teams; MS = cat.metrics || []; META = {}; MS.forEach(function (m) { META[m.key] = m; });
    SEA = CC.ok(a[1]) ? a[1] : null;
    R = (SEA && SEA.ratings) || {}; SIM = (SEA && SEA.sim && SEA.sim.teams) || {};
    REC = {}; Object.keys((SEA && SEA.standings) || {}).forEach(function (c) { (SEA.standings[c] || []).forEach(function (r) { if (r) REC[String(r.team)] = r; }); });
    AP = {}; (((SEA && SEA.polls) || {}).ap || []).forEach(function (r) { AP[String(r.team)] = r.rank; });
    RACE = a[4] && CC.ok(a[4]) ? a[4][String(ST.S)] || null : null;
    if (ST.scope !== 'top' && ST.scope !== 'all' && !ids().some(function (t) { return tinfo(t).conf === ST.scope; })) ST.scope = 'top';
    var n = ids().length;
    el.innerHTML = U.head('Teams', esc(n + (fb() ? ' FBS teams' : ' Division I teams')) + ' ranked by our rating, profiled on every team metric and set against each other. Tap a team for its page.', U.kicker(ST.L, ST.S)) +
      '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(function (s) { return '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[1]) + '</a>'; }).join('') + '</div></nav>' +
      SECS.map(function (s) { return '<section class="qk-section tm-sec" id="' + s[0] + '"></section>'; }).join('');
    QK.$$('[data-jump]', el).forEach(function (x) { x.addEventListener('click', function (ev) {
      ev.preventDefault();
      var t = document.getElementById(x.getAttribute('data-jump'));
      if (!t) return;
      var off = ['.qk-topbar', '.qk-secnav'].reduce(function (s0, q) { return s0 + ((document.querySelector(q) || {}).offsetHeight || 0); }, 0) + 12;
      window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth' });
    }); });
    power(); grid(); styleMap(); strengths(); continuity(); h2h(); trend();
  });
});

/* the scope picker (the grid and the cards): our top 25, one conference, or every team */
function scopeSel(id) {
  var cs = confOrder(Array.from(new Set(ids().map(function (t) { return tinfo(t).conf; }).filter(Boolean))));
  return '<select class="qk-select" id="' + id + '" aria-label="Teams shown"><option value="top"' + (ST.scope === 'top' ? ' selected' : '') + '>Our top 25</option>' +
    cs.map(function (c) { return '<option value="' + esc(c) + '"' + (ST.scope === c ? ' selected' : '') + '>' + esc(CC.cname(ST.L, c)) + '</option>'; }).join('') +
    '<option value="all"' + (ST.scope === 'all' ? ' selected' : '') + '>Every team (' + ids().length + ')</option></select>';
}
function wireScope(id) { var s = document.getElementById(id); if (s) s.onchange = function (e) { ST.scope = e.target.value; writeQ(); grid(); strengths(); continuity(); }; }

/* 1. the power board */
function power() {
  var host = document.getElementById('tm-power');
  if (!host) return;
  var all = byRating(ids()), rk = {};
  all.forEach(function (t, i) { rk[t] = i + 1; });
  /* the split: football's rating is offence + defence (points added and prevented); basketball's is offence minus
     defence per 100, both around the same national average, so the parts are each side's distance from it */
  var avg = 0;
  if (!fb() && !hk()) { var os = all.map(function (t) { return (R[t] || {}).off; }).filter(isNum), ds = all.map(function (t) { return (R[t] || {}).def; }).filter(isNum); avg = (os.reduce(function (s, x) { return s + x; }, 0) / (os.length || 1) + ds.reduce(function (s, x) { return s + x; }, 0) / (ds.length || 1)) / 2; }
  var prevRk = {}; ((SEA && SEA.power) || []).forEach(function (r) { if (r && isNum(r.prev_rank)) prevRk[String(r.team)] = r.prev_rank; });
  var cur = CC.isCur(ST.L, ST.S);
  var row = function (t) {
    var i = tinfo(t), x = R[t] || {}, s0 = SIM[t] || {};
    var parts = fb() || hk() ? { off: x.off, def: x.def } : { off: isNum(x.off) ? x.off - avg : null, def: isNum(x.def) ? avg - x.def : null };
    var mv = isNum(prevRk[t]) ? prevRk[t] - rk[t] : null;
    var po = fb() ? s0.p_cfp : s0.p_ncaa;
    return { rank: rk[t], name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + ' · ' + CC.cname(ST.L, i.conf) + (AP[t] ? ' · AP No. ' + AP[t] : ''),
      value: rating(t), text: CC.signed(rating(t), hk() ? 2 : 1), parts: parts,
      cells: [{ label: 'Since last week', html: mv === null ? '<span class="qk-muted">—</span>' : mv === 0 ? '<span class="qk-muted">=</span>' : '<span class="cc-mv ' + (mv > 0 ? 'pos' : 'neg') + '">' + (mv > 0 ? '▲' : '▼') + Math.abs(mv) + '</span>' },
        { label: 'Schedule', text: isNum(x.sos_rank) ? QK.ordinal(x.sos_rank) + ' hardest' : '—' }],
      chances: cur ? [{ label: fb() ? 'Playoff' : 'NCAA field', p: po }, { label: 'Title', p: s0.p_title }].filter(function (c) { return isNum(c.p) && c.p > 0; }) : [] };
  };
  var groups;
  if (ST.pw === 'all') groups = [{ label: '', rows: all.map(row) }];
  else if (ST.pw === 'conf') {
    var cs = confOrder(Array.from(new Set(all.map(function (t) { return tinfo(t).conf; }))));
    groups = cs.map(function (c) { return { label: c ? CC.cname(ST.L, c) : 'Independents', rows: all.filter(function (t) { return tinfo(t).conf === c; }).map(row) }; });
  } else groups = [{ label: '', rows: all.slice(0, 25).map(row) }];
  var unit = fb() ? 'points v an average FBS team on a neutral field' : hk() ? 'goals a game v an average D-I team on neutral ice' : 'points per 100 possessions v an average D-I team';
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: 'Every team, ranked by our rating', sub: 'Our rating is the margin we expect against an average ' + (fb() ? 'FBS' : 'Division I') + ' team on ' + (hk() ? 'neutral ice (goals a game)' : 'a neutral field (' + (fb() ? 'points' : 'points per 100 possessions') + ')') + '. The bar splits it into ' + (hk() ? 'attack and defence' : 'offence and defence') + '; the volt tick is the total.' +
    (cur ? ' Playoff and title chances come from our simulated seasons.' : ''), actions: '<div class="qk-seg" id="tm-pw" role="group" aria-label="Group the board">' + [['top', 'Top 25'], ['conf', 'By conference'], ['all', 'All ' + all.length]].map(function (o) { return '<button type="button" data-value="' + o[0] + '" aria-pressed="' + (ST.pw === o[0]) + '">' + o[1] + '</button>'; }).join('') + '</div>' }) +
    '<div class="qk-card"><div class="qk-card-body' + (ST.pw === 'top' ? '' : ' tm-long') + '">' + QK.powerBars(null, { groups: groups, valueLabel: 'Our rating', unit: unit,
      parts: [{ key: 'off', label: hk() ? 'Attack' : 'Offence', color: 'var(--c-2)' }, { key: 'def', label: 'Defence', color: 'var(--c-3)' }] }) + '</div></div>' +
    QK.explain('A <b>rating of ' + (fb() ? '+14' : hk() ? '+1.0' : '+20') + '</b> means ' + (fb() ? 'two touchdowns better than an average FBS team on a neutral field' : hk() ? 'a goal a game better than an average Division I team on neutral ice: the best teams sit around +1.5' : 'twenty points per 100 possessions better than an average Division I team, about fourteen points a game') + '. This is our power ranking (it was on Standings › Polls); the AP and coaches’ polls stay on <a class="qk-link" href="' + esc(CC.href(ST.L, 'standings', null, ST.S, 'tab=polls')) + '">Standings › Polls</a>, beside it.', { title: 'What’s that number?' });
  var seg = document.getElementById('tm-pw');
  if (seg) QK.seg(seg, function (x) { ST.pw = x; writeQ(); power(); });
}

/* 2. the team profile grid */
function grid() {
  var host = document.getElementById('tm-grid');
  if (!host) return;
  var have = function (id) { return !!META[id] && ids().some(function (t) { return isNum(v(t, id)); }); };
  var G = CC.group(ST.L, 'team');
  var head = G ? G.m.filter(function (m) { return m.set === 'h' && have(m.id); }).map(function (m) { return m.id; }) : [];
  var sets = head.length ? [{ key: 'overview', label: 'Overview', groups: [{ label: 'Headline', ids: head }] }] : [];
  var gn = [];
  MS.forEach(function (m) { var g = CC.uk(m.group || 'Other'); if (gn.indexOf(g) < 0 && have(m.key)) gn.push(g); });
  gn.forEach(function (g) { sets.push({ key: g.toLowerCase().replace(/[^a-z]+/g, '-'), label: g, groups: [{ label: g, ids: MS.filter(function (m) { return CC.uk(m.group || 'Other') === g && have(m.key); }).map(function (m) { return m.key; }) }] }); });
  var ours = MS.filter(function (m) { return CC.ours(m.key) && have(m.key); }).map(function (m) { return m.key; });
  if (ours.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: ours }] });
  var rows = scoped().map(function (t) { var i = tinfo(t); return { id: t, name: i.name, sub: rec(t) + ' · ' + CC.cname(ST.L, i.conf), mark: { abbr: i.abbr, colour: i.colour }, href: thref(t) }; });
  var addable = MS.filter(function (m) { return have(m.key); }).map(function (m) { return '<option value="' + esc(m.key) + '">' + esc(meta(m.key).label) + '</option>'; }).join('');
  var all = ids();
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: rows.length + ' teams, every metric', sub: 'Each cell is the team’s value, coloured by its percentile among all ' + all.length + ' teams in the country (blue worst, red best; a ↓ marks a metric where lower is better, grey is style). Pick a phase, add any of the ' + MS.length + ' metrics, sort by any column, tap a team for its page.',
    actions: scopeSel('tm-scope') }) + '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  wireScope('tm-scope');
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(function (s) { return s.key === ST.grid; }) ? ST.grid : (sets[0] || {}).key, setsLabel: 'Phase', added: ST.gadd.filter(have), sort: ST.gsort || { key: 'rating', dir: 'desc' },
    nameLabel: 'Team', subLabel: 'Record · conference', noun: 'teams', meta: meta, addable: addable, maxHeight: 640,
    rows: rows, val: function (r, id) { return v(r.id, id); }, peers: all.map(function (t) { return { id: t }; }),
    csv: 'campus-' + ST.L + '-' + ST.S + '-teams.csv',
    onState: function (st) { ST.grid = sets[0] && st.set === sets[0].key ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; writeQ(); }
  });
}

/* 3. the style map */
function styleMap() {
  var host = document.getElementById('tm-map');
  if (!host) return;
  var opts = MS.filter(function (m) { return ids().some(function (t) { return isNum(v(t, m.key)); }); }).map(function (m) { return { value: m.key, label: meta(m.key).label }; });
  var P = PRESETS[sp()].filter(function (p0) { return ids().filter(function (t) { return isNum(v(t, p0[1])) && isNum(v(t, p0[2])); }).length >= 5; });
  if (ST.map >= P.length) ST.map = 0;
  var cur = ST.map >= 0 ? P[ST.map] : null;
  var x = cur ? cur[1] : (META[ST.mx] ? ST.mx : 'off'), y = cur ? cur[2] : (META[ST.my] ? ST.my : 'def');
  var sel = function (id, val) { return '<select class="qk-select" id="' + id + '">' + opts.map(function (o) { return '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>'; }).join('') + '</select>'; };
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each team wins', sub: 'Any two team metrics against each other, ' + esc(scopeName()) + ' labelled and every team in the country plotted. The dashed lines are the national medians; better is always up and to the right (axes where less is better are flipped).' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map(function (p0, i) { return '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p0[0]) + '</option>'; }).join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>', cls: 'grow' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:540px;margin-top:16px" role="img" aria-label="Style map"></div><p class="cc-note" id="tm-map-n"></p></div></div>';
  var $ = function (id) { return document.getElementById(id); };
  $('tm-preset').onchange = function (e) { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } writeQ(); styleMap(); };
  $('tm-mx').onchange = function (e) { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; writeQ(); styleMap(); };
  $('tm-my').onchange = function (e) { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; writeQ(); styleMap(); };
  var mx = meta(x), my = meta(y);
  var lab = {}; scoped().slice(0, 40).forEach(function (t) { lab[t] = 1; });
  var pts = ids().filter(function (t) { return isNum(v(t, x)) && isNum(v(t, y)); }).map(function (t) { var i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name + ' · ' + rec(t), label: lab[t] ? i.abbr : ' ', color: CC.tcol(ST.L, t), size: lab[t] ? 14 : 7, href: thref(t) }; });
  var med = function (a) { var b = a.slice().sort(function (p, q) { return p - q; }), n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
  var q = cur ? cur[3] : ['', 'Better on both', 'Worse on both', ''];
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: med(pts.map(function (p0) { return p0.x; })), refY: med(pts.map(function (p0) { return p0.y; })), xInverse: mx.lower, yInverse: my.lower, pad: '9%',
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: mx.fmt, yFmt: my.fmt, quadrants: q, label: my.label + ' against ' + mx.label });
  $('tm-map-n').innerHTML = '<b>' + esc(mx.label) + '</b>: ' + esc(mx.tip) + ' <b>' + esc(my.label) + '</b>: ' + esc(my.tip);
}

/* 4. strengths and weaknesses */
function luck(t) {
  var r = REC[t];
  if (r && hk()) r = { pf: r.gf, pa: r.ga, w: (r.w || 0) + 0.5 * (r.t || 0), l: (r.l || 0) + 0.5 * (r.t || 0) };
  if (!r || !isNum(r.pf) || !isNum(r.pa) || !(r.pf + r.pa > 0)) return null;
  var g = (r.w || 0) + (r.l || 0);
  if (!g) return null;
  var k = PYTH[ST.L] || 2.37, a = Math.pow(r.pf, k), b = Math.pow(r.pa, k);
  return { d: (r.w || 0) - g * a / (a + b), g: g };
}
function chips(t) {
  var out = [], p0 = function (k) { return pc(t, k); };
  CHIP[sp()].forEach(function (c) { var p = p0(c[0]); if (!isNum(p)) return; if (p >= c[1]) out.push(['good', c[2]]); else if (c[3] !== null && p <= c[3]) out.push(['bad', c[4]]); });
  Object.keys(STYLE).forEach(function (k) { var p = p0(k), s0 = STYLE[k]; if (!isNum(p)) return; if (p >= s0[0]) out.push(['style', s0[1]]); else if (p <= s0[2]) out.push(['style', s0[3]]); });
  var lk = luck(t);
  if (lk && lk.g >= 4) { if (lk.d >= 1) out.push(['luck', 'Riding luck: ' + CC.f(lk.d, 1) + ' wins above its points']); else if (lk.d <= -1) out.push(['luck', 'Unlucky: ' + CC.f(-lk.d, 1) + ' wins below its points']); }
  return out;
}
function strengths() {
  var host = document.getElementById('tm-sw');
  if (!host) return;
  var pool = SW_POOL[sp()].filter(function (id) { return META[id] && ids().some(function (t) { return isNum(v(t, id)); }); });
  var list = scoped();
  var cards = list.map(function (t) {
    var i = tinfo(t);
    var xs = pool.map(function (id) { return { id: id, p: pc(t, id) }; }).filter(function (o) { return isNum(o.p); });
    var chip = function (o) { var m = meta(o.id); return { label: m.label, pctl: o.p, text: m.fmt(v(t, o.id)), tip: m.tip }; };
    var best = xs.slice().sort(function (a, b) { return b.p - a.p; }).slice(0, 3).map(chip), worst = xs.slice().sort(function (a, b) { return a.p - b.p; }).slice(0, 3).map(chip);
    var ch = chips(t);
    return '<div class="tm-swc">' + QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: rec(t) + ' · rating ' + CC.signed(rating(t), 1), best: best, worst: worst }) +
      (ch.length ? '<div class="cc-rc-chips">' + ch.map(function (c) { return '<span class="cc-rc-chip ' + c[0] + '">' + esc(c[1]) + '</span>'; }).join('') + '</div>' : '') + '</div>';
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each team does best, and worst', sub: 'For ' + esc(scopeName()) + ': each team’s three best and three worst of ' + pool.length + ' process metrics, as percentiles among every team in the country (100 = best), and plain-English calls on the clear strengths (85th percentile and up), weak spots (15th and below), style and luck against its points. Ordered by our rating.',
    actions: scopeSel('tm-scope2') }) + '<div class="qk-sw-grid">' + cards + '</div>';
  wireScope('tm-scope2');
}

/* 4b. roster continuity (round 9, Phase 4): where each team's value comes from this season, from players who played
   for it last season (returning), players who played for another team last season (transfers in) and players with no
   box-score line last season (new: freshmen, players who did not play). Read from this season's and last season's
   lab_players.json (files the site already has), loaded when the section scrolls into view. Shares of the positive
   value (a player below replacement adds nothing to a share). */
var CONT = { key: '', rows: null };
function continuity() {
  var host = document.getElementById('tm-cont');
  if (!host) return;
  var prevS = CC.seasons(ST.L).filter(function (x) { return x < Number(ST.S); })[0];
  var head = QK.sectionHead({ kicker: 'Roster continuity', title: 'Who is doing it: returners, transfers, newcomers', sub: 'The share of each team’s value this season (' + esc(scopeName()) + ') from players who were on the team last season, from transfers in (another team last season) and from players with no game last season. Ordered by the returning share.', actions: scopeSel('tm-scope3') });
  if (!prevS) { host.innerHTML = head + QK.empty('No earlier season', 'Continuity needs last season’s file.'); wireScope('tm-scope3'); return; }
  var key = ST.L + '/' + ST.S;
  var draw = function () {
    var by = CONT.rows || {};
    var list = scoped().filter(function (t) { return by[t] && by[t].tot > 0; }).sort(function (a, b) { return by[b].ret / by[b].tot - by[a].ret / by[a].tot; });
    if (!list.length) { host.innerHTML = head + QK.empty('Not yet', 'Continuity reads once players have value this season.'); wireScope('tm-scope3'); return; }
    /* the headline tiles: teams that were in last season's file too (a programme new to the level has no returners to count) */
    var all = Object.keys(by).filter(function (t) { return by[t].tot > 0 && by[t].had && T[t]; });
    var share = function (t, k) { return by[t][k] / by[t].tot; };
    var most = all.slice().sort(function (a, b) { return share(b, 'ret') - share(a, 'ret'); })[0], least = all.slice().sort(function (a, b) { return share(a, 'ret') - share(b, 'ret'); })[0];
    var tr = all.slice().sort(function (a, b) { return share(b, 'tr') - share(a, 'tr'); })[0];
    host.innerHTML = head + U.stats([{ label: 'Most continuity', value: CC.tabbr(ST.L, most) + ' ' + CC.pct(share(most, 'ret'), 0), signal: true, href: thref(most), sub: CC.tname(ST.L, most) + ': value from last season’s players' },
      { label: 'Most rebuilt', value: CC.tabbr(ST.L, least) + ' ' + CC.pct(share(least, 'ret'), 0), href: thref(least), sub: CC.tname(ST.L, least) + ': returning share' },
      { label: 'Built on transfers', value: CC.tabbr(ST.L, tr) + ' ' + CC.pct(share(tr, 'tr'), 0), href: thref(tr), sub: CC.tname(ST.L, tr) + ': value from transfers in' }]) +
      '<div class="qk-card"><div class="qk-card-body">' + U.chart('tm-cont-c', Math.max(300, list.length * 24 + 70), 'Share of value by where the players came from') + '</div></div>' +
      QK.explain('Returning means a box-score line for the same team last season; a transfer, a line for another team (inferred from box scores, not the official portal); new, no line at all (mostly freshmen). Value is our value model, positive part only, so the three shares add to 100%. Archived seasons keep only their regular players, so in basketball “new” can include a few returning reserves.', { title: 'How it is counted.' });
    wireScope('tm-scope3');
    QKC.bar(document.getElementById('tm-cont-c'), { cats: list.map(function (t) { return tinfo(t).short; }), horizontal: true, stack: true, legend: true, max: 1, fmt: function (v) { return CC.pct(v, 0); }, hrefs: list.map(thref), labelWidth: 110,
      series: [{ name: 'Returning', color: QK.cssVar('--signal'), data: list.map(function (t) { return share(t, 'ret'); }) }, { name: 'Transfers in', color: QK.cssVar('--c-2'), data: list.map(function (t) { return share(t, 'tr'); }) }, { name: 'New', color: QK.cssVar('--c-3'), data: list.map(function (t) { return share(t, 'nw'); }) }],
      valName: 'Share of the team’s value this season', catName: 'Team', label: 'Roster continuity' });
  };
  if (CONT.key === key && CONT.rows) { draw(); return; }
  host.innerHTML = head + '<div id="tm-cont-w">' + QK.skeleton('lines', 3) + '</div>';
  wireScope('tm-scope3');
  var go = function () {
    Promise.all([CC.load(CC.path(ST.L, ST.S, 'lab_players.json')), CC.load(CC.path(ST.L, prevS, 'lab_players.json'))]).then(function (a) {
      if (!U.alive(host)) return;
      var rows = function (d) { if (!CC.ok(d) || !d.fields) return []; var ix = {}; d.fields.forEach(function (f, i) { ix[f] = i; }); var vk = ix.value !== undefined ? ix.value : ix.gar; return (d.rows || []).map(function (r) { return { id: String(r[ix.id]), team: String(r[ix.team]), v: r[vk] }; }).filter(function (r) { return r.id.charAt(0) !== '-'; }); };
      var prev = {}, had = {}; rows(a[1]).forEach(function (r) { prev[r.id] = r.team; had[r.team] = 1; });
      var by = {};
      rows(a[0]).forEach(function (r) {
        var v = isNum(r.v) && r.v > 0 ? r.v : 0, b = by[r.team] = by[r.team] || { ret: 0, tr: 0, nw: 0, tot: 0, had: !!had[r.team] };
        var k = prev[r.id] === undefined ? 'nw' : prev[r.id] === r.team ? 'ret' : 'tr';
        b[k] += v; b.tot += v;
      });
      CONT = { key: key, rows: by };
      draw();
    });
  };
  if (window.IntersectionObserver) { var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); go(); } }, { rootMargin: '400px' }); io.observe(host); } else go();
}

/* 5. head to head */
function h2h() {
  var host = document.getElementById('tm-h2h');
  if (!host) return;
  var list = byRating(ids());
  if (!T[ST.a]) ST.a = list[0];
  if (!T[ST.b] || ST.b === ST.a) ST.b = list.filter(function (t) { return t !== ST.a; })[0];
  var opt = function (cur) { return list.slice().sort(function (a, b) { return tinfo(a).name.localeCompare(tinfo(b).name); }).map(function (t) { return '<option value="' + esc(t) + '"' + (t === cur ? ' selected' : '') + '>' + esc(tinfo(t).name) + '</option>'; }).join(''); };
  var A = tinfo(ST.a), B = tinfo(ST.b);
  var groups = H2H[sp()].map(function (g) { return { label: g[0], rows: g[1].filter(function (id) { return META[id]; }).map(function (id) {
    var m = meta(id);
    return { label: m.label, tip: m.tip, a: v(ST.a, id), b: v(ST.b, id), ta: isNum(v(ST.a, id)) ? m.fmt(v(ST.a, id)) : '—', tb: isNum(v(ST.b, id)) ? m.fmt(v(ST.b, id)) : '—', pa: m.style ? null : pc(ST.a, id), pb: m.style ? null : pc(ST.b, id), better: m.style ? null : m.lower ? 'low' : 'high' };
  }) }; });
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: A.short + ' or ' + B.short + '?', sub: 'Two teams on the metrics that decide games. Bars are percentiles among all ' + list.length + ' teams; the small line under each metric is the gap in percentile points and who leads it.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: rec(ST.a) + ' · ' + CC.signed(rating(ST.a), 1), colour: A.colour, alt: A.alt, href: thref(ST.a) },
      right: { name: B.name, short: B.abbr, sub: rec(ST.b) + ' · ' + CC.signed(rating(ST.b), 1), colour: B.colour, alt: B.alt, href: thref(ST.b) }, groups: groups, wins: true, gap: true }) + '</div></div></div>';
  var $ = function (id) { return document.getElementById(id); };
  $('tm-a').onchange = function (e) { ST.a = e.target.value; writeQ(); h2h(); };
  $('tm-b').onchange = function (e) { ST.b = e.target.value; writeQ(); h2h(); };
  $('tm-swap').onclick = function () { var t = ST.a; ST.a = ST.b; ST.b = t; writeQ(); h2h(); };
}

/* 6. through the season: our rating week by week (rating_paths), our playoff / tournament chance by day (race log) */
function trend() {
  var host = document.getElementById('tm-trend');
  if (!host) return;
  var paths = (SEA && SEA.rating_paths) || {};
  var list = byRating(ids());
  if (!list.some(function (t) { return (paths[t] || []).length > 1; })) { host.innerHTML = ''; return; }
  var pk = fb() ? 'p_cfp' : 'p_ncaa';
  var log = RACE && RACE[pk] ? RACE[pk] : null, days = log ? Object.keys(log).filter(function (d) { return d.length === 10; }).sort() : [];
  if (ST.trend === 'chance' && days.length < 2) ST.trend = 'rating';
  var clubs = ST.clubs.filter(function (t) { return T[t]; });
  if (!clubs.length) clubs = list.slice(0, 6);
  var top = list.slice(0, 40).slice().sort(function (a, b) { return tinfo(a).abbr.localeCompare(tinfo(b).abbr); });
  clubs.forEach(function (t) { if (top.indexOf(t) < 0) top.push(t); });
  var chipsH = top.map(function (t) { return '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '">' + esc(tinfo(t).abbr) + '</button>'; }).join('');
  var cs = confOrder(Array.from(new Set(list.map(function (t) { return tinfo(t).conf; }).filter(Boolean)))).slice(0, (POWER[ST.L] || []).length || 6);
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: ST.trend === 'chance' ? 'The race, day by day' : 'Our rating, week by week',
    sub: ST.trend === 'chance' ? 'Our chance of ' + (fb() ? 'a playoff place' : 'a place in the NCAA tournament') + ' for each team on each day, from the season simulation as it stood that day.' : 'Our rating after each week’s games (' + (fb() ? 'points v an average FBS team' : hk() ? 'goals a game v an average D-I team' : 'points per 100 v an average D-I team') + '). A line that climbs is a team getting better, or being found out as better.',
    actions: days.length >= 2 ? '<div class="qk-seg" id="tm-tr" role="group" aria-label="Measure"><button type="button" data-value="rating" aria-pressed="' + (ST.trend === 'rating') + '">Our rating</button><button type="button" data-value="chance" aria-pressed="' + (ST.trend === 'chance') + '">' + (fb() ? 'Playoff chance' : 'NCAA chance') + '</button></div>' : '' }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">Teams (our top 40; up to eight)</span><div class="qk-chips">' + chipsH + '</div>' +
    '<div class="qk-chips tm-divs">' + cs.map(function (c) { return '<button type="button" class="qk-chip" data-conf="' + esc(c) + '">' + esc(CC.cname(ST.L, c)) + ' top six</button>'; }).join('') + '<button type="button" class="qk-chip" data-conf="*top">Our top six</button></div>' +
    '</div><div id="tm-tr-c" class="qk-chart" style="--h:460px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  var cols = CC.lineColours(ST.L, clubs);
  var colOf = function (t, i) { return cols[i]; };
  if (ST.trend === 'chance') {
    QKC.line(document.getElementById('tm-tr-c'), { x: days.map(function (d) { return QK.fmt.date(d + 'T12:00:00', { day: 'numeric', month: 'short' }); }), series: clubs.map(function (t, i) { return { name: tinfo(t).abbr, color: colOf(t, i), data: days.map(function (d) { var p = (log[d] || {})[t]; return isNum(p) ? Math.round(p * 1000) / 10 : 0; }) }; }),
      yName: (fb() ? 'Playoff' : 'NCAA tournament') + ' chance (%)', xName: 'Date', yMin: 0, yMax: 100, yFmt: function (x) { return x + '%'; }, endLabels: true, label: 'Our chance by day' });
  } else {
    var dates = {};
    clubs.forEach(function (t) { (paths[t] || []).forEach(function (p0) { dates[p0[0]] = 1; }); });
    var xs = Object.keys(dates).sort();
    QKC.line(document.getElementById('tm-tr-c'), { x: xs.map(function (d) { return CC.date(d + 'T12:00:00Z'); }), series: clubs.map(function (t, i) { var m = {}; (paths[t] || []).forEach(function (p0) { m[p0[0]] = p0[1]; }); return { name: tinfo(t).abbr, color: colOf(t, i), symbols: true, data: xs.map(function (d) { return isNum(m[d]) ? m[d] : null; }) }; }),
      yName: fb() ? 'Rating (points v average)' : hk() ? 'Rating (goals a game v average)' : 'Rating (per 100 v average)', xName: 'Week of', yScale: true, yFmt: function (x) { return CC.signed(x, hk() ? 1 : 0); }, endLabels: true, label: 'Our rating through the season' });
  }
  QK.$$('[data-club]', host).forEach(function (b) { b.addEventListener('click', function () {
    var t = b.getAttribute('data-club'), cur = clubs.slice(), i = cur.indexOf(t);
    if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else if (cur.length < 8) cur.push(t);
    ST.clubs = cur; writeQ(); trend();
  }); });
  QK.$$('[data-conf]', host).forEach(function (b) { b.addEventListener('click', function () {
    var c = b.getAttribute('data-conf');
    ST.clubs = (c === '*top' ? list : list.filter(function (t) { return tinfo(t).conf === c; })).slice(0, 6);
    writeQ(); trend();
  }); });
  var seg = document.getElementById('tm-tr');
  if (seg) QK.seg(seg, function (x) { ST.trend = x; writeQ(); trend(); });
}

})(window.CC);
