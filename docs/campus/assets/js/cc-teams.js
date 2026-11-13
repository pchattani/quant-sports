/* The Quant Campus — the team page (#/<L>/team/<tid>), Design System 2.0. The Teams page (#/<L>/teams) is
 * cc-teamspage.js (round 9: power board, team profile grid, style map, strengths, head to head, through the season).
 * Team page: a card header in the team colour (record, rating, rank, conference), stat tiles (our rating first, with
 * its standard error and national percentile; projected wins and the season chances), the rating through the season,
 * AP v our rank, a percentile card against every team in the country, the schedule with our win chance, the roster
 * with value, strengths and needs, who moves next (movement payload, when published), inferred transfers in and out,
 * top performers (overall and by position, against the level), and the final-wins and seed distributions.
 * Reads <L>/<S>/teams.json, <L>/<S>/teams/<tid>.json, <L>/<S>/season.json; basketball also <L>/<S>/trank.json
 * (Barttorvik's T-Rank, a credited reference beside our rating; absent when the source is switched off). */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

/* Metrics with one value across every team (preseason: luck, schedule strength, win %) carry no percentile. */
function flatKeys(cat) {
  var out = {}, T = (cat && cat.teams) || {};
  ((cat && cat.metrics) || []).forEach(function (m) {
    var seen = {}, n = 0;
    Object.keys(T).forEach(function (t) { var v = ((T[t] || {}).values || {})[m.key]; if (isNum(v) && !seen[v]) { seen[v] = 1; n++; } });
    if (n <= 1) out[m.key] = 1;
  });
  return out;
}

/* ── team page ───────────────────────────────────────────────────────── */
function chanceTiles(L, o) {
  if (!o) return [];
  var k = [];
  if (isNum(o.exp_w)) k.push({ label: 'Projected wins', value: CC.f(o.exp_w, 1), sub: CC.f(o.exp_l, 1) + ' losses · mean of our simulated seasons', tip: 'The average final record across the simulated seasons' });
  if (CC.fb(L)) {
    if (isNum(o.p_conf)) k.push({ label: 'Win the conference', value: CC.pct(o.p_conf), sub: isNum(o.p_conf_game) ? 'play in the title game ' + CC.pct(o.p_conf_game) : '' });
    if (isNum(o.p_cfp)) k.push({ label: 'Make the playoff', value: CC.pct(o.p_cfp), sub: isNum(o.p_bye) ? 'first-round bye ' + CC.pct(o.p_bye) : '' });
    else if (isNum(o.p_bowl)) k.push({ label: 'Bowl eligible', value: CC.pct(o.p_bowl) });
  } else {
    if (isNum(o.p_ncaa)) k.push({ label: 'Make the tournament', value: CC.pct(o.p_ncaa), sub: isNum(o.seed_mean) ? 'seed ' + CC.f(o.seed_mean, 1) + ' on average' : '' });
    if (isNum(o.p_conf_tourney)) k.push({ label: 'Win the conference tournament', value: CC.pct(o.p_conf_tourney) });
  }
  if (isNum(o.p_title)) k.push({ label: 'Win the title', value: CC.pct(o.p_title, o.p_title < 0.1 ? 1 : 0) });
  return k;
}

/* Who moves next (MOVES_VIEWS.md, college): the Outlook card from the team page's `movement`. The team page shows
   no potential signings (the user's call, 25 Oct 2026): the targets stay in movement.json for the movement views. */
var INFERRED = 'Inferred from box scores, not the official transfer portal';
function moveOutlook(L, S, d) {
  var mv = d && d.movement;
  if (!mv || !mv.expected_out) return '';
  var nx = mv.next_season ? CC.seasonLabel(L, mv.next_season) : 'next season';
  var sumv = function (o) { return Object.keys(o || {}).reduce(function (a, k) { return a + (isNum(o[k]) ? o[k] : 0); }, 0); };
  var poss = Object.keys(mv.expected_out).concat(Object.keys(mv.expected_in || {})).filter(function (x, i, arr) { return arr.indexOf(x) === i; });
  var needs = {}; ((d && d.needs) || []).forEach(function (u) { String(u.unit || '').split('/').forEach(function (x) { needs[x.trim().toUpperCase()] = 1; }); if (/^DL/i.test(u.unit || '')) needs.DL = 1; });
  var gap = null, gv = -1e9;
  poss.forEach(function (ps) { var g = (mv.expected_out[ps] || 0) - ((mv.expected_in || {})[ps] || 0); if (g > gv) { gv = g; gap = ps; } });
  var tiles = U.stats([
    { label: 'Expected departures', value: CC.f(mv.out_total, 1), signal: true, sub: 'players not back before ' + nx, tip: 'Our model of each player’s chance of leaving (a transfer, or no box-score line next season), summed over the roster' },
    { label: 'Expected transfers out', value: CC.f(sumv(mv.expected_transfers_out), 1), sub: 'inferred transfers to another team' },
    { label: 'Expected transfers in', value: CC.f(sumv(mv.expected_in), 1), sub: 'base rate: last offseason’s arrivals per team', tip: 'A base rate, not a team-level forecast' }
  ]);
  var rows = poss.map(function (ps) {
    return '<tr><td><b>' + esc(ps) + '</b>' + (ps === gap && gv > 0 ? ' ' + QK.tag('Biggest shortfall') : '') + (needs[ps] ? ' ' + QK.tag('need') : '') + '</td><td class="num">' + CC.f(mv.expected_out[ps], 1) +
      (mv.expected_transfers_out && isNum(mv.expected_transfers_out[ps]) ? ' <span class="qk-muted">(' + CC.f(mv.expected_transfers_out[ps], 1) + ' transfer)</span>' : '') + '</td><td class="num">' + CC.f((mv.expected_in || {})[ps], 1) + '</td>' +
      '<td class="num">' + (isNum((mv.p_add || {})[ps]) ? CC.pct(mv.p_add[ps]) + ' ' + U.bar(mv.p_add[ps]) : '—') + '</td></tr>';
  }).join('');
  var tbl = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Position</th><th class="num">Expected out</th><th class="num"><span data-tip="Base rate: last complete offseason’s inferred transfers in per team">Expected in</span></th><th class="num">Chance of adding</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  var byPos = U.card('By position', 'Expected departures and arrivals; ' + (gap && gv > 0 ? esc(gap) + ' has the biggest shortfall' : 'no position is short') + '.', tbl);
  return U.section('Outlook: before ' + esc(nx), 'Who moves next: our chance each player leaves, and the arrivals a team like this usually gets. ' + QK.tag(INFERRED),
    tiles + '<div class="qk-grid cc-grid"><div class="qk-span-12">' + byPos + '</div></div>', '', 'Movement');
}
/* Barttorvik's T-Rank for the team (basketball), beside our rating: its rank, efficiencies, barthag and wins above
   bubble, with our rank among the same teams. Empty when trank.json is missing (SOURCE_BARTTORVIK_ENABLED=0). */
var TRANK_CREDIT = 'Barttorvik (barttorvik.com, T-Rank)';
function trankCard(L, S, tid, tr, cat) {
  var row = tr && tr.teams ? tr.teams[String(tid)] : null;
  if (!row) return '';
  var T = (cat && cat.teams) || {}, ours = null;
  var our = (T[tid] || {}).values || {};
  if (isNum(our.rating)) ours = 1 + Object.keys(T).filter(function (t) { var v = ((T[t] || {}).values || {}).rating; return isNum(v) && v > our.rating; }).length;
  var tiles = U.stats([
    { label: 'T-Rank', value: '#' + row.rank, signal: true, sub: (isNum(ours) ? 'our rank #' + ours : '') },
    { label: 'Adj. offence', value: CC.f(row.adjoe, 1), sub: 'points per 100' },
    { label: 'Adj. defence', value: CC.f(row.adjde, 1), sub: 'allowed per 100 (lower is better)' },
    isNum(row.barthag) ? { label: 'Barthag', value: CC.f(row.barthag, 3), sub: 'chance to beat an average team' } : null,
    isNum(row.wab) ? { label: 'Wins above bubble', value: CC.signed(row.wab, 1), sub: 'v a bubble team\u2019s schedule' } : null
  ].filter(Boolean));
  return U.section('Another view: T-Rank', 'Bart Torvik\u2019s ratings for the same season, a reference beside ours (' + (CC.isCur(L, S) ? 'to date' : 'end of season') + '). They are not used by our model.',
    tiles + '<p class="cc-note">Source: <a href="https://barttorvik.com" target="_blank" rel="noopener">' + esc(TRANK_CREDIT) + '</a>. Shown with credit; removed if its owner asks.</p>', '', 'Reference');
}
/* ── sweep, 12 Nov 2026: the Rink's team-page pattern ─────────────────── */
/* "about 3 in 10" for a chance, in hundreds near the ends (1% is about 1 in 100, never "1 in 10") */
function freqWords(p) {
  if (p >= 0.995) return 'nearly all';
  if (p <= 0.005) return 'almost none';
  return p < 0.095 || p > 0.905 ? 'about ' + Math.round(p * 100) + ' in 100' : 'about ' + Math.round(p * 10) + ' in 10';
}
/* The team's finished games, oldest first, with its result in each (CC.resultOf: W, L, or a hockey tie T). */
function playedOf(L, sched, tid) {
  return (sched || []).filter(function (c) { return c && c.status === 'post' && c.stype !== 'exh' && c.stype !== 'pre'; })
    .map(function (c) { return { c: c, r: CC.resultOf(L, c, tid) }; }).filter(function (x) { return !!x.r; })
    .sort(function (a, b) { return String(a.c.date).localeCompare(String(b.c.date)); });
}
/* The hero's form chip: the last results as the kit's form squares on black (they keep their contrast on any team
   colour), oldest first, with the record over them; football's season is short, so its last five. */
function formChip(L, played) {
  var n = CC.fb(L) ? 5 : 10, f = played.slice(-n).map(function (x) { return x.r; });
  if (!f.length) return '';
  var c = function (x) { return f.filter(function (r) { return r === x; }).length; };
  return '<span class="cc-ph-form" tabindex="0" data-tip="The last ' + f.length + ' results, oldest first' + (c('T') ? ' (T: a tie)' : '') + '">Last ' + f.length + ' ' + QK.formDots(f, f.length) +
    '<b class="num">' + c('W') + '–' + c('L') + (c('T') ? '–' + c('T') : '') + '</b></span>';
}
/* 9 seasons in 10 from the simulation's own win distribution (w_dist[k] = the chance of k wins): the 5th and 95th
   percentiles, read off the payload's distribution (no interval is assumed). null without one. */
function winRange(dist) {
  if (!Array.isArray(dist) || dist.length < 2) return null;
  var cum = 0, lo = null, hi = null;
  for (var i = 0; i < dist.length; i++) { cum += isNum(dist[i]) ? dist[i] : 0; if (lo === null && cum >= 0.05) lo = i; if (hi === null && cum >= 0.95) { hi = i; break; } }
  return lo !== null && hi !== null ? { lo: lo, hi: hi, max: dist.length - 1 } : null;
}
/* Our season chances as the kit's bars (QK.chances), in the team colour: the level's milestones, ours only. */
function chanceRows(L, o, colour) {
  if (!o) return [];
  var pr = o.p_round || {};
  var rows = CC.fb(L) ? [['Make the playoff', o.p_cfp], ['First-round bye', o.p_bye], ['Reach the conference title game', o.p_conf_game], ['Win the conference', o.p_conf], ['Win the title', o.p_title], ['Bowl eligible', isNum(o.p_cfp) ? null : o.p_bowl]]
    : CC.hk(L) ? [['Make the NCAA tournament', o.p_ncaa], ['Win the conference tournament', o.p_conf_tourney], ['Win the regular-season conference title', o.p_conf_reg], ['Reach the Frozen Four', o.p_f4], ['Win the title', o.p_title]]
    : [['Make the NCAA tournament', o.p_ncaa], ['Win the conference tournament', o.p_conf_tourney], ['Win the regular-season conference title', o.p_conf_reg], ['Reach the Sweet 16', pr.s16], ['Reach the Final Four', pr.f4], ['Win the title', o.p_title]];
  return rows.filter(function (x, i) { return isNum(x[1]) && (i === 0 || x[1] > 0); }).map(function (x) { return { label: x[0], p: x[1], color: colour || undefined }; });
}
/* How the two teams of a game match up this season (season.json ratings), as the game page's hero. */
function matchup(L, c, season) {
  var R = (season && season.ratings) || {}, ra = R[String(c.away)] || {}, rh = R[String(c.home)] || {}, fb = CC.fb(L), hk = CC.hk(L), fx = [];
  var add = function (label, x, y, f, low) { if (isNum(x) && isNum(y)) fx.push({ label: label, a: f(x), b: f(y), better: Math.abs(x - y) < 1e-9 ? null : ((x > y) !== !!low ? 'a' : 'b') }); };
  add(hk ? 'Rating, goals v average' : fb ? 'Rating, points v average' : 'Rating, margin per 100', ra.rating, rh.rating, function (v) { return CC.signed(v, hk ? 2 : 1); });
  if (hk) { add('Attack, goals a game above average', ra.off, rh.off, function (v) { return CC.signed(v, 2); }); add('Defence, goals a game kept out', ra.def, rh.def, function (v) { return CC.signed(v, 2); }); }
  else { add(fb ? 'Offence, points a game' : 'Offence, points per 100', ra.off, rh.off, function (v) { return CC.f(v, 1); }); add(fb ? 'Defence, points prevented' : 'Defence, allowed per 100', ra.def, rh.def, function (v) { return CC.f(v, 1); }, !fb); }
  return fx;
}
/* What to watch next (the scoreboard bug and how the teams match up) beside the last game (the score as the title, our
   pre-game chance against the result, the box and our win chance through it from the game file), as the Rink's
   team page. No market here: it sits on the game page only. */
function nextAndLast(L, S, tid, sched, played, season) {
  var hk = CC.hk(L), nowT = QK.now();
  var nxt = (sched || []).filter(function (c) { return c && (c.status === 'in' || (c.status === 'pre' && Date.parse(c.date) > nowT - 4 * 3600e3)); })
    .sort(function (a, b) { return (a.status === 'in' ? -1 : 0) - (b.status === 'in' ? -1 : 0) || String(a.date).localeCompare(String(b.date)); })[0] || null;
  var last = played.length ? played[played.length - 1] : null;
  if (!nxt && !last) return { html: '', last: null };
  var h = '';
  if (nxt) {
    var G = CC.game(nxt, L);
    G.home.record = CC.rec(L, S, nxt.home); G.away.record = CC.rec(L, S, nxt.away);
    var live = nxt.status === 'in', rel = QK.fmt.relDay(CC.gameDate(nxt));
    h += '<div>' + QK.sectionHead({ kicker: live ? 'Live now' : (rel === 'Today' ? 'What to watch tonight' : 'Next up'), title: CC.tshort(L, nxt.away) + (nxt.neutral ? ' v ' : ' at ') + CC.tshort(L, nxt.home) }) +
      (hk ? CC.tieWords : String)(QK.previewCard(G, { layout: 'bug', nick: function (x) { return x.name; }, factors: matchup(L, nxt, season), factorsTitle: 'How they match up this season', vs: nxt.neutral ? 'v' : undefined })) + '</div>';
  }
  if (last) {
    var c = last.c, home = String(c.home) === String(tid), my = home ? c.hs : c.as, op = home ? c.as : c.hs, oid = home ? c.away : c.home;
    var me = CC.tabbr(L, tid), ab = CC.tabbr(L, oid);
    var ttl = (my >= op ? me + ' ' + my + ', ' + ab + ' ' + op : ab + ' ' + op + ', ' + me + ' ' + my) + (last.r === 'T' ? ' (tie)' : '');
    var m = c.model || {}, pw = null, po = null;
    if (isNum(m.p_home)) { var pa = isNum(m.p_away) ? m.p_away : 1 - m.p_home - (isNum(m.p_tie) && hk ? m.p_tie : 0); pw = home ? m.p_home : pa; po = home ? pa : m.p_home; }
    var pre = '';
    if (isNum(pw)) {
      var nm = CC.tshort(L, tid), fav = pw >= po;
      pre = 'We gave ' + nm + ' a ' + CC.pct(pw) + ' chance to win before the game' + (hk && isNum(m.p_tie) ? ' (a tie ' + CC.pct(m.p_tie) + ')' : '') + ': ' +
        (last.r === 'T' ? 'it ended level.' : Math.abs(pw - po) < 0.1 ? 'close to a coin flip, ' + (last.r === 'W' ? 'and they won.' : 'and they lost.') : fav === (last.r === 'W') ? 'the favourite won.' : (last.r === 'W' ? 'an upset win.' : 'an upset loss.'));
    }
    var hasPage = CC.hasPage(L, Object.assign({ season: S }, c), S);
    var where = c.neutral ? 'neutral site' : home ? 'at home' : 'away';
    var inner = '<div id="tp-box"></div>' + (pre ? QK.explain(esc(pre)) : '');
    h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: esc(ttl), html: true, sub: esc(CC.date(CC.gameDate(c)) + ' · ' + where + (CC.roundLabel(c) ? ' · ' + CC.roundLabel(c) : '')),
      actions: '<a class="qk-more" href="' + esc(CC.gameHref(L, c.id, S)) + '">' + (hasPage ? 'The game centre' : 'The recap') + '</a>' }) +
      '<article class="qk-card cc-card"><div class="qk-card-body">' + (nxt ? inner + '<div id="tp-race"></div>' : '<div class="qk-g2"><div>' + inner + '</div><div id="tp-race"></div></div>') + '</div></article></div>';
  }
  return { html: '<section class="qk-section cc-sec cc-nl">' + (nxt && last ? '<div class="qk-g2">' + h + '</div>' : h) + '</section>', last: last && CC.hasPage(L, Object.assign({ season: S }, last.c), S) ? last.c : null };
}
function fillLast(el, L, S, tid, c) {
  if (!c || !QK.$('#tp-box', el)) return;
  CC.load(CC.path(L, S, 'games/' + c.id + '.json')).then(function (gf) {
    if (!CC.ok(gf) || !U.alive(el)) return;
    if (!gf.season) gf.season = S;
    var box = QK.$('#tp-box', el), race = QK.$('#tp-race', el);
    if (box) box.innerHTML = CC.lastBox(L, gf, tid);
    if (race && CC.wpChart) {
      race.innerHTML = U.chart('tp-race-c', 240, 'Our win chance through the last game');
      if (!CC.wpChart('#tp-race-c', L, gf)) race.innerHTML = '';
    }
  });
}

CC.route('team', function (el, p) {
  var L = p.L, S = p.S, tid = p.id, fb = CC.fb(L);
  el.innerHTML = QK.skeleton('lines', 8);
  var bb = L === 'mbb' || L === 'wbb';
  return Promise.all([CC.load(CC.path(L, S, 'teams/' + tid + '.json')), CC.season(L, S), CC.load(CC.path(L, S, 'teams.json')), CC.metrics(),
    bb ? CC.load(CC.path(L, S, 'trank.json')) : Promise.resolve(null)]).then(function (a) {
    /* archive team pages carry no schedule (size budget): the team's games come from the season's schedule.json */
    var d0 = CC.ok(a[0]) ? a[0] : null;
    if (!d0 || d0.schedule) return a;
    return CC.load(CC.path(L, S, 'schedule.json')).then(function (sch) {
      if (CC.ok(sch)) d0.schedule = (sch.games || []).filter(function (c) { return String(c.home) === String(tid) || String(c.away) === String(tid); });
      return a;
    });
  }).then(function (a) {
    if (!U.alive(el)) return;
    var d = CC.ok(a[0]) ? a[0] : null, season = CC.ok(a[1]) ? a[1] : null, cat = CC.ok(a[2]) ? a[2] : null;
    if (d && d.team) { var m = {}; m[tid] = d.team; CC.addTeams(L, m); }
    var t = CC.team(L, tid);
    if (!d && !t) { el.innerHTML = U.head('Team', '', U.kicker(L, S)) + QK.empty('Team not found', 'No team ' + tid + ' in ' + CC.seasonLabel(L, S) + '.'); return; }
    var R = (d && d.rating) || (season && season.ratings && season.ratings[tid]) || {};
    var sim = (d && d.odds) || (season && season.sim && season.sim.teams && season.sim.teams[tid]) || null;
    var rec = d && d.record ? d.record : {};
    var conf = t ? CC.conf(L, t.conference) : null;
    var stx = (d && d.stats) || {}, cpt = cat && cat.teams && cat.teams[tid] ? cat.teams[tid].pct || {} : {};
    var pc = function (k) { return stx[k] && isNum(stx[k].pct) ? stx[k].pct : (isNum(cpt[k]) ? cpt[k] : null); };
    var peers = fb ? 'FBS teams' : 'Division I teams', hk = CC.hk(L), recS = function (r) { return hk ? CC.recW(r) : CC.record(r.w, r.l); };
    document.title = (t ? t.name : 'Team ' + tid) + ' · ' + CC.seasonLabel(L, S) + ' · The Quant Campus';
    /* The short version: the record, the rating and its rank, the schedule, and what the simulation says */
    var nm = t ? (t.short || t.name) : 'Team ' + tid;
    var shortTxt = (isNum(rec.w) ? nm + ' ' + (CC.isCur(L, S) ? 'are' : 'went') + ' ' + recS(rec) + (isNum(rec.conf_w) ? ' (' + recS({ w: rec.conf_w, l: rec.conf_l, t: rec.conf_t }) + ' in the conference)' : '') + '. ' : '') +
      (isNum(R.rating) ? 'We rate them ' + CC.f(Math.abs(R.rating), hk ? 2 : 1) + (fb ? ' points' : hk ? ' goals a game' : ' points per 100 possessions') + ' ' + (R.rating >= 0 ? 'better' : 'worse') + ' than an average ' + (fb ? 'FBS' : 'D-I') + ' team' + (isNum(R.rank) ? ', ' + QK.ordinal(R.rank) + ' in the country' : '') + (isNum(R.se) ? ', give or take ' + CC.f(R.se, hk ? 2 : 1) : '') + '. ' : '') +
      (sim && isNum(sim.p_title) && sim.p_title >= 0.005 ? 'Our simulations give them a ' + CC.pct(sim.p_title) + ' chance to win the title.' : (isNum(R.sos_rank) ? 'Their schedule ranks ' + QK.ordinal(R.sos_rank) + ' for strength.' : ''));
    var sched = (d && d.schedule) || [];
    var played = playedOf(L, sched, tid), fchip = formChip(L, played);
    var html = '<nav class="cc-crumb" aria-label="Breadcrumb"><a href="' + esc(CC.href(L, 'teams', null, S)) + '">' + esc(CC.LNAME[L]) + '</a><span aria-hidden="true">›</span>' + esc(conf ? (conf.short || conf.name) : 'Independent') + '<span aria-hidden="true">›</span>' + esc(t ? t.name : 'Team ' + tid) + '</nav>';
    html += QK.playerHeader({ name: t ? t.name : 'Team ' + tid, split: false, pos: conf ? (conf.name || conf.short) : 'Independent', kicker: CC.LNAME[L] + ' · ' + CC.seasonLabel(L, S), face: t && t.abbr ? t.abbr : null,
      team: t ? { name: '', abbr: t.abbr, colour: t.colour, alt: CC.talt(L, tid) || undefined } : null,
      meta: [['Record', recS(rec)], isNum(rec.conf_w) ? ['Conference', recS({ w: rec.conf_w, l: rec.conf_l, t: rec.conf_t }) + (hk && isNum(rec.conf_pts) ? ' · ' + rec.conf_pts + ' pts' : '')] : null, rec.streak ? ['Streak', rec.streak] : null, isNum(R.games) ? ['Games rated', String(R.games)] : null],
      tags: fchip ? [fchip] : [], short: null,
      /* round 12 (My Teams): follow the team from the hero; it then leads Home and this site's overview */
      follow: CC.followItem(L, tid) }) + '%STRIP_HTML%' + (shortTxt.trim() ? '<div class="qk-ph-short">' + QK.shortVersion(shortTxt.trim()) + '</div>' : '') + '%SURE_HTML%';
    if (!d) html += '<p class="cc-note">The full team page has not been built for this season; ratings come from the season file.</p>';
    var dm = ((cat && cat.metrics) || []).filter(function (m0) { return m0.key === 'def'; })[0];
    var defLow = dm ? !!dm.lower : !fb;
    var k = [{ label: 'Our rating', value: CC.signed(R.rating, hk ? 2 : 1), signal: true, pctl: pc('rating'), sub: (isNum(R.se) ? '± ' + CC.f(R.se, hk ? 2 : 1) + ' · ' : '') + (fb ? 'points v an average FBS team' : hk ? 'goals a game v an average D-I team' : 'per 100 v an average D-I team'),
      tip: (fb ? 'Expected margin against an average FBS team on a neutral field' : hk ? 'Expected goal difference a game against an average Division I team on neutral ice' : 'Adjusted efficiency margin per 100 possessions') + '; ± is one standard error; the chip is the national percentile' }];
    if (isNum(R.off)) k.push({ label: hk ? 'Attack' : 'Offence', value: hk ? CC.signed(R.off, 2) : CC.f(R.off, 1), pctl: pc('off'), sub: fb ? 'points a game added' : hk ? 'goals a game above average' : 'adjusted points per 100' });
    if (isNum(R.def)) k.push({ label: 'Defence', value: hk ? CC.signed(R.def, 2) : CC.f(R.def, 1), pctl: pc('def'), sub: hk ? 'goals a game kept out' : defLow ? 'points allowed per 100 (lower is better)' : 'points a game prevented' });
    var cur = CC.isCur(L, S), nSims = season && season.sim && isNum(season.sim.n_sims) ? season.sim.n_sims : null;
    if (cur) {
      var ct = chanceTiles(L, sim), wr = sim ? winRange(sim.w_dist) : null;
      /* projected wins carries the simulation's 9-in-10 range as the likely-range bar; the headline chance follows */
      ct.forEach(function (x) {
        if (x.label === 'Projected wins' && wr) { x.sub = '9 seasons in 10: ' + wr.lo + '–' + wr.hi + ' wins'; x.range = { lo: wr.lo, hi: wr.hi, mid: sim.exp_w, min: 0, max: wr.max, label: 'Projected wins, nine seasons in ten', fmt: function (v) { return CC.f(v, 0); } }; x.tip = 'The mean of our simulated seasons; the bar holds nine seasons in ten, from the simulation’s own win distribution'; }
      });
      var head = ct.filter(function (x) { return /playoff|tournament/i.test(x.label) && !/conference/i.test(x.label); })[0];
      k = k.concat(ct.filter(function (x) { return x.label === 'Projected wins'; })).concat(head ? [Object.assign({}, head, { signal: true, sub: head.sub || (nSims ? 'from ' + QK.fmt.num(nSims) + ' simulated seasons' : 'our chance') })] : []);
      if (k.length < 5) k = k.concat(ct.filter(function (x) { return x.label !== 'Projected wins' && x !== head; }).slice(0, 5 - k.length));
    }
    /* v4: the numbers are the black strip under the team-colour hero (QK.playerHeader strip), "The short version" after */
    html = html.replace('%STRIP_HTML%', QK.statStrip(k.slice(0, 5)));
    /* "How sure are we?": what the headline chance means, and the sample behind the rating (its standard error) */
    var hp = cur && sim ? (CC.fb(L) ? sim.p_cfp : sim.p_ncaa) : null, gpR = isNum(R.games) ? R.games : (isNum(rec.w) ? rec.w + rec.l + (rec.t || 0) : 0), sure = [];
    if (isNum(hp)) sure.push('<b>' + CC.pct(hp) + '</b> to make the ' + (CC.fb(L) ? 'playoff' : 'NCAA tournament') + ' means ' + esc(nm) + ' made it in ' + freqWords(hp) + ' of our ' + (nSims ? QK.fmt.num(nSims) + ' ' : '') + 'simulated seasons.');
    if (isNum(R.rating)) sure.push((gpR ? (cur ? gpR + ' game' + (gpR === 1 ? '' : 's') + ' in' : 'Over ' + gpR + ' game' + (gpR === 1 ? '' : 's')) + ', our' : 'Before the first game our') + ' rating is <b>' + CC.signed(R.rating, hk ? 2 : 1) + (isNum(R.se) ? ' ± ' + CC.f(R.se, hk ? 2 : 1) : '') + '</b> ' + (fb ? 'points' : hk ? 'goals a game' : 'points per 100 possessions') + ' against an average team' + (isNum(R.se) ? ' (one standard error)' : '') + '.' +
      (gpR && gpR < 8 ? ' ' + gpR + ' game' + (gpR === 1 ? ' is' : 's is') + ' a small sample, hence the wide ±.' : ''));
    html = html.replace('%SURE_HTML%', sure.length ? '<div style="margin-top:var(--sp-3)">' + QK.explain(sure.join(' '), { title: 'How sure are we?' }) + '</div>' : '');
    /* what to watch next beside the last game (the Rink's team page) */
    var NL = nextAndLast(L, S, tid, sched, played, season);
    html += NL.html;
    // percentile card (every team in the country) beside the rating path and rank history
    var groups = [];
    if (cat && cat.metrics) {
      var off = [], def = [], oth = [];
      var FL = flatKeys(cat);
      var TG = CC.group(L, 'team'), bk = {};
      cat.metrics.forEach(function (m0) { bk[m0.key] = m0; });
      if (TG) {
        var rowOf = function (m) {
          var m0 = bk[m.id], pp0 = pc(m.id);
          if (!m0 || FL[m.id] || !isNum(pp0)) return null;
          var v0 = (stx[m.id] && isNum(stx[m.id].v)) ? stx[m.id].v : ((cat.teams[tid] || {}).values || {})[m.id];
          return { label: CC.uk(m.d || m0.label), pctl: pp0, value: CC.fmtMetric(m0, v0), tip: (m.x || m0.desc || '') + (m.style ? ' Describes how the team plays, not how well: shown in grey.' : ''), style: !!m.style };
        };
        var hRows = TG.m.filter(function (m) { return m.set === 'h'; }).map(rowOf).filter(Boolean);
        var sRows = TG.m.filter(function (m) { return m.set === 's'; }).map(rowOf).filter(Boolean);
        if (hRows.length >= 3) groups = [{ label: 'Headline: ratings, then the process that predicts results', rows: hRows }, { label: 'More', rows: sRows }];
      }
      if (!groups.length) cat.metrics.forEach(function (m0) {
        if (FL[m0.key]) return;
        var v = (stx[m0.key] && isNum(stx[m0.key].v)) ? stx[m0.key].v : ((cat.teams[tid] || {}).values || {})[m0.key], pp = pc(m0.key);
        if (!isNum(pp)) return;
        var row = { label: CC.uk(m0.label), pctl: pp, value: CC.fmtMetric(m0, v), tip: m0.desc || '' };
        if (/off|ppg|^ypp$|third|pass_epa|rush_epa|explosive|efg|tpar|ftr|orb|ast|^tov_rate|tp_pct|ft_pct/.test(m0.key) && !/allowed|opp_|def/.test(m0.key)) off.push(row);
        else if (/def|allowed|papg|opp_|drb|blk|stl/.test(m0.key)) def.push(row); else oth.push(row);
      });
      if (!groups.length) groups = [{ label: 'Offence', rows: off }, { label: 'Defence', rows: def }, { label: 'Overall and schedule', rows: oth }];
    }
    var nTeams = cat && cat.teams ? Object.keys(cat.teams).length : null;
    var pcard = QK.pctCard({ title: 'Percentile rankings', peer: 'all ' + (nTeams ? nTeams + ' ' : '') + peers, sample: (isNum(R.games) && R.games > 0 ? R.games + ' games rated' : 'preseason ratings, no games yet') + ' · ' + CC.seasonLabel(L, S), groups: groups,
      note: 'Opponent-adjusted where the metric says so; lower-is-better metrics are flipped so 100 is always best.', emptyText: 'Percentiles appear after the first games.' });
    var path = (d && d.rating_path) || (season && season.rating_paths && season.rating_paths[tid]) || [];
    var rh = (d && d.rank_history) || [];
    var crow = cur ? chanceRows(L, sim, t ? t.colour : null) : [];
    var chCard = crow.length ? U.card('Season chances', 'Ours, from ' + (nSims ? QK.fmt.num(nSims) + ' ' : '') + 'simulated seasons' + (isNum(sim.n_rem) ? ' (' + sim.n_rem + ' regular-season game' + (sim.n_rem === 1 ? '' : 's') + ' left)' : '') + '.', QK.chances(crow, { sort: false, max: 1, key: false })) : '';
    html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + pcard + '</div><div class="qk-span-7"><div class="qk-stack">' + chCard +
      U.card('Rating through the season', 'Re-fitted after each week' + (isNum(R.se) ? '; today’s rating is ± ' + CC.f(R.se, 1) + ' (one standard error)' : '') + '.', path.length > 1 ? U.chart('tp-path', 240, 'Rating through the season') : QK.empty('Not enough games yet', 'The path starts after the first games.')) +
      U.card(hk ? 'USCHO rank v our rank' : 'AP rank v our rank', 'Week by week; 1 is the top.', rh.length > 1 ? U.chart('tp-rank', 220, 'AP and our rank by week') : QK.empty('No rank history', 'The polls and our ranking appear once the season starts.')) +
      /* the season distributions sit in this column too, beside the long percentile card (they were a row of their own) */
      (cur && sim && sim.w_dist && sim.w_dist.length ? U.card('Final win total', 'Our chance of each number of regular-season wins, from the simulated seasons.', U.chart('tp-wd', 220, 'Distribution of final wins')) : '') +
      (cur && sim && sim.seed_dist && Object.keys(sim.seed_dist).length ? U.card(fb ? 'Playoff seed' : 'Tournament seed', 'Our chance of each seed, from the simulated seasons.', U.chart('tp-sd', 220, 'Distribution of seeds')) : '') + '</div></div></div>';
    if (bb && CC.ok(a[4])) html += trankCard(L, S, tid, a[4], cat);
    // schedule
    if (hk) html += CC.hkCredit(true);
    if (sched.length) html += U.section('Schedule', 'Every game with our pre-game win chance for ' + esc(CC.tshort(L, tid)) + '.', U.card('', '', U.lb('tp-sched'), { flush: true, cls: 'cc-bare' }), '', 'Games');
    // roster + units
    var roster = (d && d.roster) || [];
    var units = (d && d.units) || [];
    var unitsH = units.length ? QK.pctCard({ title: 'Strengths and needs', peer: 'all ' + peers, sample: 'value by unit this season', groups: [{ label: 'Units, graded A to F', rows: units.map(function (u) { return { label: CC.unit(u.unit) + (u.grade ? ' · ' + u.grade : ''), pctl: isNum(u.pctl) ? u.pctl : null, value: isNum(u.value) ? CC.signed(u.value, 1) : '', tip: CC.unit(u.evidence || '') }; }) }],
      foot: swList(d) }) : U.card('Strengths and needs', '', QK.empty('Not graded yet', 'Units are graded once enough games are in.'));
    html += topPerformers(L, S, d, fb);
    html += U.section('Roster', 'Value: ' + (fb ? 'EPA above replacement' : hk ? 'goals above replacement (GAR)' : 'value above replacement') + ' this season.' + (!CC.isCur(L, S) && !fb && roster.length <= 12 && roster.length ? ' Archive seasons keep the top 12 by minutes.' : ''),
      '<div class="qk-grid cc-grid"><div class="qk-span-8">' + (roster.length ? U.card('', '', U.lb('tp-roster'), { flush: true, cls: 'cc-bare' }) : U.card('Roster', '', QK.empty('No roster yet', 'Rosters come from ESPN; the current one is refreshed weekly.'))) + '</div><div class="qk-span-4">' + unitsH + '</div></div>', '', 'Players');
    // who moves next (published payload only)
    if (CC.isCur(L, S)) html += moveOutlook(L, S, d);
    // moves that happened
    var mv = (d && d.moves) || { 'in': [], out: [] };
    function mvT(list, dir) {
      if (!list || !list.length) return QK.empty(dir === 'in' ? 'No transfers in found' : 'No transfers out found', 'None in our box scores since last season.');
      return U.table(['Player', 'Pos', dir === 'in' ? 'From' : 'To', { label: 'Value before', align: 'right' }, { label: 'After', align: 'right' }], list.map(function (m0) {
        return [{ html: '<a href="' + esc(CC.playerHref(L, m0.player, S)) + '">' + esc(m0.name || CC.pname(L, m0.player)) + '</a>', v: m0.name }, esc(m0.pos || '—'), { html: U.teamEnt(L, dir === 'in' ? m0.from : m0.to, { season: S }), v: CC.tname(L, dir === 'in' ? m0.from : m0.to) },
          { v: m0.value_before, html: CC.f(m0.value_before, 1) }, { v: m0.value_after, html: CC.f(m0.value_after, 1) }];
      }), { sticky: false });
    }
    html += U.section('Transfers', (hk ? 'The same College Hockey News player on a new team since last season. ' : 'The same ESPN athlete on a new team since last season. ') + QK.tag(hk ? 'Inferred from player lines, not the official transfer portal' : INFERRED),
      '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('In', '', mvT(mv['in'], 'in')) + '</div><div class="qk-span-6">' + U.card('Out', '', mvT(mv.out, 'out')) + '</div></div>', '', 'Moves');
    el.innerHTML = html;
    U.wire(el);
    fillLast(el, L, S, tid, NL.last);
    var col = t && QK.color.parse(t.colour) ? QK.color.team(t.colour) : null;
    if (path.length > 1) {
      var xs = path.map(function (x0) { return String(x0[0]).slice(0, 10); });
      QKC.forecast('#tp-path', { x: xs, xType: 'time', series: [{ name: 'Rating', label: CC.tabbr(L, tid), data: path.map(function (x0) { return x0[1]; }), color: col }],
        yFmt: function (v) { return CC.signed(v, 1); }, yName: fb ? 'Rating (points v average)' : 'Rating (per 100 v average)', xName: 'Date', label: 'Rating through the season' });
    }
    if (rh.length > 1) QKC.line('#tp-rank', { x: rh.map(function (r) { return String(r[0]) === 'pre' ? 'Pre' : (String(r[0]) === 'final' ? 'Final' : /^\d{4}-/.test(String(r[0])) ? CC.date(r[0] + 'T12:00:00Z') : 'Wk ' + r[0]); }), series: [{ name: hk ? 'USCHO' : 'AP', data: rh.map(function (r) { return isNum(r[1]) ? r[1] : null; }), color: QK.cssVar('--c-3'), symbols: true }, { name: 'Ours', data: rh.map(function (r) { return isNum(r[2]) ? r[2] : null; }), color: QK.cssVar('--signal'), symbols: true }],
      yInverse: true, yMin: 1, yInterval: (function () { var v = []; rh.forEach(function (r) { if (isNum(r[1])) v.push(r[1]); if (isNum(r[2])) v.push(r[2]); }); var span = v.length ? Math.max.apply(null, v) - 1 : 5; return Math.max(1, Math.ceil(span / 6)); })(),
      yFmt: function (v) { return '#' + Math.round(v); }, xName: 'Week', yName: 'Rank' });
    if (sched.length) {
      QK.leaderboard(QK.$('#tp-sched', el), { dense: true, maxHeight: 640, rowHref: function (r) { return CC.gameHref(L, r.id, S); }, columns: [
        { key: 'date', label: 'Date', fmt: function (v, r) { return esc(CC.date(CC.gameDate(r.c))) + (CC.tba(r.c) ? ' <span class="qk-muted">TBA</span>' : ''); } },
        { key: 'oppName', label: 'Opponent', type: 'entity', sub: 'tag', mark: function (r) { return U.mark(L, r.opp); }, href: function (r) { return CC.teamHref(L, r.opp, S); } },
        { key: 'pw', label: 'Our win chance', type: 'bar', max: 1, fmt: function (v) { return isNum(v) ? CC.pct(v) : '—'; } },
        { key: 'resv', label: 'Result', fmt: function (v, r) { return r.res; } }
      ], rows: sched.map(function (c) {
        var home = String(c.home) === String(tid), opp = home ? c.away : c.home, m0 = c.model || {};
        var pw = isNum(m0.p_home) ? (home ? m0.p_home : (isNum(m0.p_away) ? m0.p_away : 1 - m0.p_home)) : null;
        var res = '<span class="qk-muted">' + (c.status === 'pre' ? 'to play' : '—') + '</span>', resv = '';
        if (c.status === 'post' && isNum(c.hs)) { var my = home ? c.hs : c.as, op = home ? c.as : c.hs, wl = hk && (my === op || c.so) ? 'T' : my > op ? 'W' : 'L'; res = '<b class="' + (wl === 'W' ? 'pos' : wl === 'L' ? 'neg' : '') + '">' + wl + '</b> ' + my + '–' + op + (hk && c.ot ? ' <span class="qk-muted">OT' + (c.so ? '/SO' : '') + '</span>' : ''); resv = wl + my; }
        return { c: c, id: c.id, date: c.date, opp: opp, oppName: (c.neutral ? 'v ' : home ? 'v ' : '@ ') + CC.tshort(L, opp), tag: CC.roundLabel(c) || (c.conf_game ? 'conference' : ''), pw: pw, res: res, resv: resv };
      }) });
    }
    if (roster.length) {
      var rcols = fb ? [['pass_yds', 'Pass yds', 0], ['rush_yds', 'Rush yds', 0], ['rec_yds', 'Rec yds', 0], ['tkl', 'Tkl', 0]] : hk ? [['g', 'G', 0], ['a', 'A', 0], ['pts', 'PTS', 0], ['pm', '+/-', 0], ['toi', 'TOI', 1], ['sv_pct', 'SV%', 3]] : [['min', 'MIN', 1], ['pts', 'PTS', 1], ['reb', 'REB', 1], ['ast', 'AST', 1]];
      rcols = rcols.filter(function (c) { return roster.some(function (r) { return isNum(r[c[0]]); }); });
      var lv = {}; (((d && d.movement) || {}).roster || []).forEach(function (x) { lv[String(x[0])] = { p: x[1], pt: x[2] }; });
      var hasLv = Object.keys(lv).length > 0;
      var mx = Math.max.apply(null, roster.map(function (r) { return Math.abs(r.value || 0); }).concat([1e-9]));
      CC.oursHeads(QK.$('#tp-roster', el));
        QK.leaderboard(QK.$('#tp-roster', el), { dense: true, maxHeight: 640, sort: { key: 'value', dir: 'desc' }, rowHref: function (r) { return CC.playerHref(L, r.id, S); }, columns: [
        { key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: function (r) { return CC.playerHref(L, r.id, S); } },
        { key: 'gp', label: 'GP', num: true },
        { key: 'value', label: hk ? 'GAR' : 'Value', type: 'bar', max: mx, fmt: function (v) { return CC.f(v, fb || hk ? 1 : 2); }, tip: fb ? 'EPA above replacement this season' : hk ? 'Goals above replacement this season (our value model)' : 'Value above replacement this season' },
        { key: 'value_pg', label: 'Per game', num: true, fmt: function (v) { return CC.f(v, 2); } }
      ].concat(rcols.map(function (c) { return { key: c[0], label: c[1], num: true, fmt: function (v) { return isNum(v) ? CC.f(v, c[2]) : '—'; } }; }))
       .concat(hasLv ? [{ key: 'p_leave', label: 'Chance of leaving', type: 'bar', max: 1, fmt: function (v) { return isNum(v) ? CC.pct(v) : '—'; }, tip: 'Our chance the player is not with the team next season (an inferred transfer or no box-score line). ' + INFERRED }] : []),
        rows: roster.map(function (r) { return Object.assign({ sub: [hk ? CC.posName(L, r.pos) : r.pos, r['class'], hk && r.num ? '#' + r.num : ''].filter(Boolean).join(' · '), p_leave: lv[String(r.id)] ? lv[String(r.id)].p : null }, r); }) });
    }
    if (CC.isCur(L, S) && sim && sim.w_dist && QK.$('#tp-wd', el)) QKC.bar('#tp-wd', { cats: sim.w_dist.map(function (x, i) { return String(i); }), series: [{ name: 'Chance', color: 'model', data: sim.w_dist }], catName: 'Regular-season wins', valName: 'Chance', fmt: function (v) { return CC.pct(v); } });
    if (CC.isCur(L, S) && sim && sim.seed_dist && QK.$('#tp-sd', el)) { var ks = Object.keys(sim.seed_dist).sort(function (x, y) { return x - y; }); QKC.bar('#tp-sd', { cats: ks.map(function (k0) { return 'Seed ' + k0; }), series: [{ name: 'Chance', color: 'model', data: ks.map(function (k0) { return sim.seed_dist[k0]; }) }], catName: 'Seed', valName: 'Chance', fmt: function (v) { return CC.pct(v); } }); }
  });
});
/* Top performers (oddsmarkets/college/top_performers.py, the team page's `top_performers`): the team's best
   qualified players by our headline metric, and the best at each position, each against every qualified player at
   that position in FBS / Division I: the percentile (LED meter) and the rank. */
function topPerformers(L, S, d, fb) {
  var tp = d && d.top_performers;
  if (!tp || (!(tp.overall || []).length && !(tp.by_pos || []).length)) {
    return U.section('Top performers', 'The team’s best players against the rest of the country.', U.card('', '', QK.empty('Not yet', 'Top performers appear once players reach the position’s minimum games this season.')), '', 'Players');
  }
  var lab = function (k) { return ((tp.labels || {})[k]) || (k === tp.key ? tp.label : k); };
  var posName = function (ps) { return CC.posLabel ? CC.posLabel(L, ps) : ps; };
  var row = function (r, showPos) {
    var pc = isNum(r.pct) ? r.pct : null;
    return '<li class="cc-tp-row"><span class="cc-tp-who"><a href="' + esc(CC.playerHref(L, r.id, S)) + '">' + esc(r.name || CC.pname(L, r.id)) + '</a>' +
      '<small>' + esc((showPos ? r.pos + ' · ' : '') + (isNum(r.gp) ? r.gp + ' games' : '')) + '</small></span>' +
      '<span class="cc-tp-v num" data-tip="' + esc(lab(r.key)) + '">' + CC.f(r.v, fb ? 1 : 1) + '</span>' +
      (pc !== null ? QK.meter(pc, { label: esc(r.name || '') + ': ' + QK.ordinal(pc) + ' percentile among ' + r.pos + 's' }) + '<span class="qk-pbox num" style="background:' + QK.pctColor(pc) + ';color:' + QK.pctInk(pc) + '">' + pc + '</span>' : '<span></span><span></span>') +
      (isNum(r.rank) ? '<span class="cc-tp-rank">' + QK.ordinal(r.rank) + ' of ' + QK.fmt.num(r.n) + ' ' + esc(CC.hk(L) ? CC.posName(L, r.pos).toLowerCase() : r.pos) + 's</span>' : '<span class="cc-tp-rank"></span>') + '</li>';
  };
  var ours = tp.ours ? ' ' + QK.ours({ model: fb ? 'value per game: EPA above a replacement-level player' : CC.hk(L) ? 'goals above replacement (GAR)' : 'box rating and value above replacement' }) : '';
  var ov = (tp.overall || []).length ? U.card('Overall', 'The team’s best by ' + esc(lab(tp.key).toLowerCase()) + '; each against the qualified ' + esc(tp.pool) + ' players at the same position.' + ours,
    '<ol class="cc-tp">' + tp.overall.map(function (r) { return row(r, true); }).join('') + '</ol>') : '';
  var bp = (tp.by_pos || []).length ? U.card('By position', 'The best qualified player at each position, by the position’s headline metric (' + Object.keys(tp.labels || {}).map(lab).join(', ') + ').' + ours,
    '<ol class="cc-tp">' + tp.by_pos.map(function (r) { return '<li class="cc-tp-pos">' + esc(posName(r.pos)) + '</li>' + row(r, false); }).join('') + '</ol>') : '';
  return U.section('Top performers', 'The team’s best players overall and at each position, against every qualified player at that position in ' + esc(tp.pool) + ' (the spec’s minimum games). The meter is the percentile; the rank is among those players.',
    '<div class="qk-grid cc-grid">' + (ov ? '<div class="qk-span-6">' + ov + '</div>' : '') + (bp ? '<div class="qk-span-' + (ov ? 6 : 12) + '">' + bp + '</div>' : '') + '</div>', '', 'Players');
}
function swList(d) {
  if (!d || (!(d.strengths || []).length && !(d.needs || []).length)) return '';
  function li(u) { return '<li>' + CC.ui.grade(u.grade) + '<span><b>' + esc(CC.unit(u.unit)) + '</b> <span class="qk-muted">' + esc(CC.unit(u.evidence || '')) + '</span></span></li>'; }
  return '<div style="width:100%"><div class="cc-mini-h">Strengths</div><ul class="cc-list cc-sw">' + (d.strengths || []).map(li).join('') + '</ul><div class="cc-mini-h">Needs</div><ul class="cc-list cc-sw">' + (d.needs || []).map(li).join('') + '</ul></div>';
}

})(window.CC);
