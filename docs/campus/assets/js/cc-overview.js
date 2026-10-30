/* The Quant Campus — Overview (#/<L>), the kit v4 "Broadcast" landing page (rk-overview.js is the reference).
 *   For the current season:
 *   1. the intro band: what the site covers and how to use it, with three quick links (Games, Standings, Players);
 *   2. "This week in <level>": the stage of the season, then the top lines from index.json levels.<L>.digest
 *      (oddsmarkets/college/site.py level_digest, on oddsmarkets/common/digest.py): the biggest movers in our playoff
 *      (CFB) or tournament (basketball) chance, the upset of the week, the team of the week;
 *      on a thin week the title favourite, the top-rated team and AP No. 1; the other games that matter;
 *   3. the game that matters most on the shared significance rule (digest.featured, oddsmarkets/common/featured.py:
 *      the level, AP ranks, the stage, the stakes in our simulation, the start time and hour; closeness only a small
 *      bonus) as the diagonal split hero, labelled "Live now", "Tonight" (only when it truly is tonight in the
 *      reader's time), "Today", "Tomorrow" or the weekday; with nothing big on, the title race leads instead;
 *   4. "N games. Our calls." (the big games first, in the same significance order; the market small and grey beside
 *      our chance, market 'quiet'); the black power list from the season leaders; round 6, the fan stories: "Biggest
 *      surprise" (the largest rating rises and the biggest fall since the first weekend, from season.json
 *      rating_paths) and "Best player nobody talks about" (QK.spotlight: the highest value-model player on a team
 *      outside the AP top 25 and our top 40, from value.json); "Who's for real?" (win % against our rating); "What's
 *      that number?"; the title race (ours only), power ratings with one standard error,
 *      AP poll v our ranking, the CFP picture (cfb) or bracketology / the bracket (basketball); the leaders.
 *   A past season keeps the "looking back" greeting, its champion tiles and the last postseason games.
 * Our record and the calibration chart are on the Model page's "How we're doing" tab (?tab=calibration).
 * Reads index.json, <L>/<S>/season.json, <L>/<S>/cfp.json | bracket.json, <L>/history.json,
 * <L>/<S>/schedule.json (past seasons), then <L>/<S>/value.json (lazy). */
(function (CC) {
'use strict';
var progHref = function (h) { return h + (h.indexOf('?') >= 0 ? '&' : '?') + 'view=progression'; };   /* the player's Progression tab (round 6) */
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

function dataTable(cols, rows, label) {
  return '<details class="cc-data"><summary>' + esc(label || 'Show the numbers as a table') + '</summary>' + U.table(cols, rows, { maxHeight: 360 }) + '</details>';
}

/* ── the landing top (the same shape on every sport overview) ──────────────────────────────────────────────── */
var WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
var LEVEL_WORDS = { cfb: 'college football', mbb: 'men’s college basketball', wbb: 'women’s college basketball', mch: 'men’s college hockey', wch: 'women’s college hockey' };
/* rating words by sport (college hockey's rating is goals a game) */
function rwords(L) { return CC.fb(L) ? 'points better than an average FBS team on a neutral field' : CC.hk(L) ? 'goals a game better than an average Division I team on neutral ice' : 'points per 100 possessions better than an average Division I team'; }
/* "Live now" | "Tonight" | "Today" | "Tomorrow" | the weekday | the date, in the reader's own time (QK.now()). */
function whenLabel(g) {
  if (!g) return '';
  if (g.status === 'live') return 'Live now';
  if (g.status === 'final') return 'Final';
  var d = new Date(g.start), now = new Date(QK.now());
  if (isNaN(d)) return '';
  var d0 = function (x) { var y = new Date(x.getTime()); y.setHours(0, 0, 0, 0); return y.getTime(); };
  var n = Math.round((d0(d) - d0(now)) / 864e5);
  if (n === 0) return g.tba ? 'Today' : d.getHours() >= 17 ? 'Tonight' : 'Today';
  if (n === 1) return 'Tomorrow';
  if (n > 1 && n < 7) return d.toLocaleDateString('en-GB', { weekday: 'long' });
  return QK.fmt.date(g.start);
}
/* a date-only payload day ("2026-12-12") in en-GB without a time-zone shift */
function day(d) { return QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d); }
function intro(o) {
  return '<section class="ql-intro" aria-label="About this site"><div class="ql-intro-l"><div class="qk-greet-date">' + esc(o.tag) + '</div>' +
    '<h1>' + esc(o.title) + '</h1><p>' + esc(o.lede) + '</p></div>' +
    '<nav class="ql-links" aria-label="Start here">' + o.links.map(function (l) { return '<a href="' + esc(l.href) + '"><b>' + esc(l.label) + '</b><span>' + esc(l.sub) + '</span></a>'; }).join('') + '</nav></section>';
}
function ptsOf(d) { return (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts'; }
function cardsById(info) {
  var by = {};
  (info.today || []).concat(info.next_games || []).forEach(function (c) { by[String(c.id)] = c; });
  return by;
}
/* playable at the reader's clock: live and started under 8 hours ago (an older "live" is a stale snapshot), or
   starting within `hrs` hours (an hour's grace after the start) */
function playable(c, hrs) {
  if (!c) return false;
  var st = CC.status(c);
  if (st === 'final' || QK.awaiting(CC.game(c, CC.state.L))) return false;
  var h = (Date.parse(c.date) - QK.now()) / 36e5;
  return st === 'live' ? h > -8 : h > -1 && h < hrs;
}
/* The game that matters most, on the shared significance rule (digest.featured): the first of "today" still
 * upcoming or live at the reader's clock, then "next" (the best of the rest of the week), else "week" (the biggest
 * occasion of the next seven days). Nothing big: the page leads with the title race. */
function pickFeatured(L, info, sim) {
  var F = (info.digest || {}).featured;
  if (!F) return null;
  var by = cardsById(info);
  var T = (F.today || []).filter(function (f) { return playable(by[String(f.id)], 24); });
  var N = (F.next || []).filter(function (f) { return playable(by[String(f.id)], 24 * 7); });
  var f = T[0] || N[0] || (F.week && playable(by[String(F.week.id)], 24 * 7) ? F.week : null);
  if (!f) return { c: null, rest: [], order: [] };
  var order = T.concat(N).map(function (x) { return by[String(x.id)]; });
  return { c: by[String(f.id)], why: reasonsWhy(L, f.why, by[String(f.id)], sim), week: !T.length && !N.length, rest: order.filter(function (c) { return String(c.id) !== String(f.id); }), order: order };
}
function reasonsWhy(L, r, c, sim) {
  var fb = CC.fb(L), po = fb ? 'p_cfp' : 'p_ncaa';
  var lead = (r || []).filter(Boolean).join(' and ');
  var a = sim[String(c.away)] || {}, h = sim[String(c.home)] || {}, A = CC.tabbr(L, c.away), H = CC.tabbr(L, c.home);
  var nums = [isNum(a[po]) && isNum(h[po]) && c.stype === 'reg' ? (fb ? 'our playoff chances ' : 'our chances of the NCAA field ') + A + ' ' + CC.pct(a[po]) + ', ' + H + ' ' + CC.pct(h[po]) : '',
    isNum(a.p_title) && isNum(h.p_title) && (a.p_title + h.p_title) >= 0.02 ? 'title chances ' + A + ' ' + CC.pct(a.p_title) + ', ' + H + ' ' + CC.pct(h.p_title) : ''].filter(Boolean).join('; ');
  if (!lead && !nums) return '';
  return lead ? lead.charAt(0).toUpperCase() + lead.slice(1) + (nums ? ': ' + nums : '') + '.' : nums.charAt(0).toUpperCase() + nums.slice(1) + '.';
}
/* Under the hero: why we picked it (round 6: no "How sure are we?" line on the overview). */
function heroNote(g, why) {
  return why ? '<b>Why this game?</b> ' + esc(why) : false;
}
var PHASE_LINE = { conf_champ: 'Conference championship week: the title games decide the automatic places in the playoff.', bowls: 'Bowl season, then the playoff rounds.',
  playoff: 'The College Football Playoff: twelve teams, one champion.', conf_tourneys: 'Conference tournament week: automatic bids on the line before Selection Sunday.',
  ncaa: 'The NCAA tournament: 68 teams, one champion.', offseason: 'The off-season. Our numbers pick up again with the next schedule.' };
function stageLine(L, st, ph) {
  if (CC.hk(L) && ph === 'ncaa') return 'The NCAA tournament: ' + (L === 'mch' ? 'sixteen teams in four regionals' : 'eleven teams') + ', then the Frozen Four.';
  if (CC.hk(L) && ph === 'conf_tourneys') return 'Conference tournament time: the six automatic bids are on the line before the field is picked.';
  if (PHASE_LINE[ph]) return PHASE_LINE[ph];
  if (!st) return '';
  var fb = CC.fb(L);
  if (ph === 'preseason') return 'Preseason. ' + (fb ? 'Kick-off is ' : CC.hk(L) ? 'Puck drop is ' : 'Tip-off is ') + day(st.first) + '; the regular season runs to ' + day(st.last) + (fb ? '.' : CC.hk(L) ? ', then the conference tournaments and the Frozen Four.' : ', then the conference tournaments and March Madness.');
  if (fb) return 'Week ' + (st.week || '?') + (st.weeks ? ' of ' + st.weeks : '') + ': ' + QK.fmt.num(st.played) + ' of ' + QK.fmt.num(st.total) + ' games played. The regular season ends ' + day(st.last) + ', then the conference title games and the 12-team playoff.';
  return 'Regular season: ' + QK.fmt.num(st.played) + ' of ' + QK.fmt.num(st.total) + ' games played. It runs to ' + day(st.last) + ', then the conference tournaments and the NCAA tournament.';
}
function weekTiles(L, S, info, dig, feat, sim) {
  var T = [], fb = CC.fb(L), mv = dig.movers;
  if (mv && (mv.up.length || mv.down.length)) {
    var up = mv.up[0], dn = mv.down[0], lead = up || dn, what = mv.metric === 'p_title' ? 'title' : fb ? 'playoff' : 'NCAA tournament';
    T.push({ label: 'Biggest mover', value: CC.tabbr(L, lead.key) + ' ' + ptsOf(lead.d), href: CC.teamHref(L, lead.key, S), signal: true,
      sub: CC.tname(L, lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + CC.pct(lead.p) + ' in our ' + what + ' chance since ' + day(mv.since) + '.' + (up && dn ? ' Biggest fall: ' + CC.tabbr(L, dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  }
  var u = dig.upset;
  if (u) {
    var score = u.side === 'home' ? u.hs + '–' + u.as : u.as + '–' + u.hs, rk = u.ranks || [];
    var nm = function (t, r) { return (isNum(r) && r <= 25 ? 'No. ' + r + ' ' : '') + CC.tshort(L, t); };
    T.push({ label: 'Upset of the week', value: CC.tabbr(L, u.winner) + ' ' + CC.pct(u.p), href: CC.gameHref(L, u.id, S),
      sub: nm(u.winner, rk[0]) + ' beat ' + nm(u.loser, rk[1]) + ' ' + score + ' on ' + QK.fmt.date(u.start) + '. We gave them ' + CC.pct(u.p) + ' before the start.' });
  }
  var h = dig.hot;
  if (h) T.push({ label: 'Team of the week', value: CC.tabbr(L, h.key) + ' ' + h.w + '–' + h.l, href: CC.teamHref(L, h.key, S),
    sub: CC.tname(L, h.key) + ': ' + h.w + ' win' + (h.w === 1 ? '' : 's') + ' in ' + h.gp + ' games, ' + (h.margin >= 0 ? '+' : '−') + Math.abs(Math.round(h.margin)) + ' points overall.' });
  /* a thin week (preseason, a one-game week): the title favourite, the top-rated team and AP No. 1 fill in */
  var t0 = (info.title_odds || [])[0];
  if (T.length < 4 && t0 && t0.p >= 0.9995) T.unshift({ label: 'National champions', value: CC.tabbr(L, t0.team), href: CC.teamHref(L, t0.team, S), signal: true, sub: CC.tname(L, t0.team) + ' won the national title.' });   /* round 11 */
  else if (T.length < 4 && t0 && !(mv && mv.metric === 'p_title')) T.unshift({ label: 'Title favourite', value: CC.tabbr(L, t0.team) + ' ' + CC.pct(t0.p), href: CC.teamHref(L, t0.team, S), signal: true,
    sub: (t0.p < 0.25 ? 'Nobody is better than 1 in 4. ' : '') + CC.tname(L, t0.team) + ' lead our board, from our simulated seasons.' });
  var m0 = (info.model_top || [])[0];
  if (T.length < 4 && m0) T.push({ label: 'Top-rated team', value: CC.tabbr(L, m0.team) + ' ' + CC.signed(m0.rating, 1), href: CC.teamHref(L, m0.team, S),
    sub: CC.tname(L, m0.team) + ': ' + CC.f(Math.abs(m0.rating), CC.hk(L) ? 2 : 1) + ' ' + rwords(L) + '.' });
  var a0 = (info.top25 || [])[0];
  if (T.length < 4 && a0) T.push({ label: CC.hk(L) ? 'USCHO No. 1' : 'AP No. 1', value: CC.tshort(L, a0.team), text: true, href: CC.teamHref(L, a0.team, S),
    sub: 'Top of the latest ' + (CC.hk(L) ? 'USCHO' : 'AP') + ' poll' + (a0.record && a0.record !== '0-0' ? ' at ' + a0.record : '') + (m0 && String(m0.team) !== String(a0.team) ? '; we rate ' + CC.tshort(L, m0.team) + ' higher.' : '.') });
  var rest = (feat && feat.rest || []).filter(Boolean).slice(0, 2);
  if (rest.length) T.push({ label: 'Also worth a look', value: rest.map(function (c) { return CC.tabbr(L, c.away) + '–' + CC.tabbr(L, c.home); }).join(' · '), href: CC.href(L, 'games'), text: rest.length > 1,
    sub: rest.map(function (c) { var g = CC.game(c, L), w = whenLabel(g); return w + (g.status === 'live' || g.tba ? '' : ' ' + QK.fmt.time(c.date)) + ': ' + g.away.name + ' at ' + g.home.name; }).join('. ') + '.' });
  return T;
}
/* The featured hero: the game that matters most (labelled for the reader's clock), or the title race. */
function featHero(L, S, feat, titleRows) {
  if (feat && feat.c) {
    var g = CC.game(feat.c, L), lab = whenLabel(g);
    g.home.record = CC.rec(L, S, feat.c.home); g.away.record = CC.rec(L, S, feat.c.away);
    return QK.featureCard(g, { scribble: lab + (feat.week ? ' · The big one this week' : ' · The one to watch'), note: heroNote(g, feat.why) });
  }
  /* round 9: nothing big on: no second title race here (the "Title race" section below has it) */
  return '';
}

function tiles(L, S, d, nSims) {
  var out = [], isCur = CC.isCur(L, S), info = CC.info(L), fb = CC.fb(L);
  var sim = d.sim, tit = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title); }).sort(function (a, b) { return sim[b].p_title - sim[a].p_title; });
  if (isCur && tit.length) {
    var fav = tit[0];
    if (sim[fav].p_title >= 0.9995) out.push({ label: 'National champions', value: CC.tabbr(L, fav), signal: true, href: CC.teamHref(L, fav), sub: CC.tname(L, fav) + ' won the national title.' });   /* round 11 */
    else out.push({ label: 'Title favourite', value: CC.tabbr(L, fav) + ' ' + CC.pct(sim[fav].p_title), signal: true, href: CC.teamHref(L, fav),
      sub: CC.tname(L, fav) + (nSims ? ' · from ' + QK.fmt.num(nSims) + ' simulated seasons' : ''), tip: 'Our chance of winning the national title: the share of simulated seasons the team wins it all' });
  } else if (d.champ) {
    out.push({ label: 'Champion', value: CC.tshort(L, d.champ), text: true, signal: true, href: CC.teamHref(L, d.champ, S), sub: CC.seasonLabel(L, S) });
  }
  var pw = d.power[0];
  if (pw) {
    var R = d.ratings[String(pw.team)] || {};
    out.push({ label: 'Top-rated team', value: CC.tabbr(L, pw.team) + ' ' + CC.signed(pw.rating, 1), href: CC.teamHref(L, pw.team, S),
      sub: (fb ? 'points better than an average FBS team' : CC.hk(L) ? 'goals a game better than average D-I' : 'points per 100 better than average D-I') + (isNum(R.se) ? ' · ± ' + CC.f(R.se, CC.hk(L) ? 2 : 1) : ''),
      tip: 'Our rating: ' + rwords(L) + (isNum(R.se) ? '; ± is one standard error' : '') });
  }
  var ap = d.ap[0];
  if (ap) out.push({ label: CC.hk(L) ? 'USCHO No. 1' : 'AP No. 1', value: CC.tshort(L, ap.team), text: true, href: CC.teamHref(L, ap.team, S),
    sub: (isNum(ap.first) && ap.first ? ap.first + ' first-place votes' : 'latest AP poll') + (d.rec[ap.team] ? ' · ' + d.rec[ap.team] : '') });
  if (isCur) {
    var live = (info.today || []).filter(function (g) { return g.status === 'in'; });
    var nx = (info.today || []).concat(info.next_games || []).filter(function (g) { return g.status === 'pre' && (CC.tba(g) || !(new Date(g.date).getTime() < Date.now() - 12 * 3600 * 1000)); }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); })[0];
    if (live.length) out.push({ label: 'Live now', value: String(live.length), unit: live.length > 1 ? 'games' : 'game', sub: live.slice(0, 3).map(function (g) { return CC.tabbr(L, g.away) + '–' + CC.tabbr(L, g.home); }).join(' · ') });
    else if (nx) out.push({ label: fb ? 'Next kick-off' : CC.hk(L) ? 'Next puck drop' : 'Next tip-off', value: CC.tba(nx) ? 'TBA' : QK.whenShort(nx.date), text: CC.tba(nx), href: CC.gameHref(L, nx.id, S),
      sub: CC.tabbr(L, nx.away) + ' @ ' + CC.tabbr(L, nx.home) + ' · ' + CC.date(CC.gameDate(nx)) });
    if (fb) {
      var po = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_cfp); }).sort(function (a, b) { return sim[b].p_cfp - sim[a].p_cfp; })[0];
      if (po && sim[po].p_cfp > 0) out.push({ label: 'Surest playoff team', value: CC.tabbr(L, po) + ' ' + CC.pct(sim[po].p_cfp), href: CC.teamHref(L, po), sub: 'our chance to make the 12-team playoff' });
    }
  }
  return U.stats(out);
}

/* The live, today's, upcoming and recent games of the level (a stale snapshot: a game still marked live or upcoming 12
   hours after its start is dropped, MIGRATION_V2.md). */
function gameLists(L, info) {
  var seen = {};
  /* a game the data still calls upcoming or live after it must have finished is waiting for its result (QK.awaiting):
     never in "What to watch", never featured */
  var fresh = function (g) { return g.status === 'post' || !QK.awaiting(CC.game(g, L)); };
  function take(list) { return (list || []).filter(function (g) { if (seen[g.id] || !fresh(g)) return false; seen[g.id] = 1; return true; }); }
  var live = take((info.today || []).filter(function (g) { return g.status === 'in'; }));
  var today = take(info.today);
  var next = take(info.next_games);
  var last = take(info.last_games);
  return { live: live, today: today, next: next, last: last };
}
/* Our picks: live first, then the games most worth watching (close calls, ranked or seeded teams, soonest). */
function pickScore(c, L) {
  var g = CC.game(c, L), s = QK.watchScore(g);
  if (s < -1e8) s = -50 - (new Date(c.date).getTime() - Date.now()) / 36e5 * 0.1;
  if (c.hr || c.ar || c.hseed || c.aseed) s += 6;
  if ((c.hr && c.ar) || (c.hseed && c.aseed)) s += 16;
  return s;
}
function watchBlock(L, S, G, feat) {
  var fb = CC.fb(L);
  var pool = G.live.concat(G.today, G.next).filter(function (c) { return c.status !== 'post'; });
  /* the big games first, in the shared significance order (digest.featured); an older payload: the old pick score */
  var order = feat && feat.order ? feat.order.filter(Boolean) : [];
  var inPool = {}; pool.forEach(function (c) { inPool[String(c.id)] = 1; });
  var picks = order.filter(function (c) { return c && inPool[String(c.id)]; }).slice(0, 6);
  if (!picks.length) picks = pool.slice().sort(function (x, y) { return pickScore(y, L) - pickScore(x, L); }).slice(0, 6);
  var when = watchWhen(picks.length ? picks : pool, fb);
  var seg = '<div class="qk-seg" id="ov-when" role="group" aria-label="Games"><button type="button" aria-pressed="true" data-value="picks">Big games</button><button type="button" aria-pressed="false" data-value="next"' + (pool.length ? '' : ' disabled') + '>Coming up</button><button type="button" aria-pressed="false" data-value="results"' + (G.last.length ? '' : ' disabled') + '>Latest results</button></div>';
  return { picks: picks, pool: pool, html: '<section class="qk-section cc-sec">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-gh">Our calls</span>', html: true,
    sub: 'Our chance for each side, with a line on why it’s worth your time. ' + (fb ? 'Ranked teams carry their AP rank.' : 'Ranked and seeded teams carry their number.'), actions: seg }) + '<div id="ov-games"></div></section>' };
}
/* "What to watch today | tonight | this week | next": from the games on show, never "today" for later games. */
function watchWhen(list, fb) {
  var ws = (list || []).map(function (c) { var g = CC.game(c, CC.state.L); return g.status === 'live' ? 'Live now' : whenLabel(g); });
  if (!ws.length) return fb ? 'this week' : 'next';
  if (ws.every(function (w) { return w === 'Live now' || w === 'Today' || w === 'Tonight'; })) return ws.indexOf('Tonight') >= 0 && ws.indexOf('Today') < 0 ? 'tonight' : 'today';
  var last = (list || []).map(function (c) { return Date.parse(c.date); }).filter(isFinite).sort(function (a, b) { return b - a; })[0];
  return isFinite(last) && last - QK.now() < 7 * 864e5 ? 'this week' : 'next';
}
/* Nothing upcoming in the index (a stale snapshot, or a quiet midweek): the next slate from the schedule, the games
   within a week of the next start, the big ones first (the old pick score). */
function nextSlate(L, sched) {
  var up = ((sched && sched.games) || []).filter(function (c) { return c.status === 'pre' && !QK.awaiting(CC.game(c, L)) && Date.parse(c.date) > QK.now() - 3600e3; })
    .sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
  if (!up.length) return [];
  var t0 = Date.parse(up[0].date);
  return up.filter(function (c) { return Date.parse(c.date) - t0 < 7 * 864e5; }).sort(function (x, y) { return pickScore(y, L) - pickScore(x, L); }).slice(0, 12)
    .sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
}
function drawWatch(el, L, W, G) {
  var NUM = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'];
  var draw = function (w) {
    var list = w === 'results' ? G.last.slice(0, 6) : w === 'next' ? W.pool.slice().sort(function (x, y) { return String(x.date).localeCompare(String(y.date)); }).slice(0, 9) : (W.picks.length ? W.picks : G.last.slice(0, 6));
    var n = list.length;
    QK.$('#ov-gh', el).textContent = w === 'results' || !W.picks.length ? 'The latest results' : w === 'next' ? 'Coming up' : NUM[n] + ' game' + (n === 1 ? '' : 's') + '. Our calls.';
    QK.$('#ov-games', el).innerHTML = n ? '<div class="qk-watch">' + list.map(function (c) { return CC.card(c, L, { why: true }); }).join('') + '</div>' : QK.empty('No games right now', 'The next games appear here as soon as they are scheduled.');
  };
  draw('picks');
  QK.seg(QK.$('#ov-when', el), draw);
}

function pastGames(L, S, sched) {
  var PRI = { cfp: 0, ncaa: 0, bowl: 1, nit: 2, wbit: 2 };
  var g = ((sched && sched.games) || []).filter(function (c) { return c.status === 'post' && PRI[c.stype] !== undefined; });
  g.sort(function (a, b) { return PRI[a.stype] - PRI[b.stype] || String(b.date).localeCompare(String(a.date)); });
  if (!g.length) return '';
  return U.section('How it ended', 'The last postseason games of ' + esc(CC.seasonLabel(L, S)) + ', with our pre-game chance in each card’s foot.', '<div class="qk-watch">' + g.slice(0, 9).map(function (c) { return CC.card(c, L, { why: true }); }).join('') + '</div>',
    '<a class="qk-btn" href="' + esc(CC.href(L, 'games', null, S)) + '">All games</a>', 'Scoreboard');
}

CC.route('overview', function (el, p) {
  var L = p.L, S = p.S, isCur = CC.isCur(L, S), fb = CC.fb(L);
  var info = CC.info(L);
  var title = CC.LNAME[L] + ', by the numbers.';
  var sub0 = fb ? 'Our win chance for every FBS game, ratings with their uncertainty, conference, playoff and title chances from simulated seasons, and the players behind it.'
    : CC.hk(L) ? 'Our win, tie and loss chances for every Division I game, ratings with their uncertainty, the NPI, NCAA and Frozen Four chances from simulated seasons, and the players behind it (College Hockey News box scores).'
    : 'Our win chance for every Division I game, ratings with their uncertainty, tournament and title chances from simulated seasons, and the players behind it.';
  var actions = '<a class="qk-btn" href="' + esc(CC.href(L, 'games', null, S)) + '">All games</a><a class="qk-btn" href="' + esc(CC.href(L, 'standings', null, S)) + '">Standings</a>';
  el.innerHTML = U.head(title, esc(sub0), U.kicker(L, S), actions) + QK.skeleton('lines', 5);
  return Promise.all([CC.season(L, S), CC.load(CC.path(L, S, fb ? 'cfp.json' : 'bracket.json')),
    CC.load(CC.lpath(L, 'history.json')), !isCur || !gameLists(L, info).today.concat(gameLists(L, info).next).some(function (c) { return c.status !== 'post'; }) ? CC.load(CC.path(L, S, 'schedule.json')) : Promise.resolve(null)]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[0]) ? a[0] : null, post = CC.ok(a[1]) ? a[1] : null, hist = CC.ok(a[2]) ? a[2] : null;
    if (!season) { el.innerHTML = U.head(title, '', U.kicker(L, S)) + U.missing('This season', a[0]); return; }
    var sim = (season.sim && season.sim.teams) || {}, ratings = season.ratings || {};
    var nSims = season.sim && isNum(season.sim.n_sims) ? season.sim.n_sims : null;
    var power = (season.power || []).filter(function (r) { return r && r.team !== undefined; });
    if (!power.length) power = Object.keys(ratings).filter(function (t) { return isNum(ratings[t].rating); }).sort(function (x, y) { return ratings[y].rating - ratings[x].rating; }).map(function (t, i) { return { rank: i + 1, team: t, rating: ratings[t].rating }; });
    var ap = ((season.polls || {}).ap || (season.polls || {}).uscho || []);
    var rec = {};
    Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = CC.hk(L) ? CC.recW(r) : CC.record(r.w, r.l); }); });
    var champ = null;
    ((hist && hist.champions) || []).forEach(function (c) { if (Number(c.season) === Number(S)) champ = String(c.team); });
    if (!champ && post && post.actual && post.actual.champion) champ = String(post.actual.champion);
    if (!champ && post && post.actual) {
      var fin = ((post.actual.games || (post.actual.bracket && post.actual.bracket.games)) || []).filter(function (g) { return /championship|^final$/i.test(String(g.round || '')) && (g.winner || CC.status(g) === 'final'); })[0];
      if (fin) champ = String(fin.winner || (fin.hs > fin.as ? fin.home : fin.away));
    }
    var d = { sim: sim, ratings: ratings, power: power, ap: ap, rec: rec, champ: champ };
    /* the builder's headline ("Week 8 · Ohio State lead the title chances at 18%") without its date part */
    var hl = isCur ? CC.copy(info.headline || '').replace(/^[^·]*·\s*/, '') : (champ ? CC.tname(L, champ) + ' won the title' : '');
    var G = isCur ? gameLists(L, info) : { live: [], today: [], next: [], last: [] };
    var feat = isCur ? pickFeatured(L, info, sim) : null;
    if (isCur && !G.live.concat(G.today, G.next).some(function (c) { return c.status !== 'post'; }) && CC.ok(a[3])) G.next = nextSlate(L, a[3]);
    var W = isCur ? watchBlock(L, S, G, feat) : null;
    // title chances: ours only (no market on the overview)
    var titleRows = (isCur ? (info.title_odds || []) : []).filter(function (r) { return isNum(r.p); }).slice(0, 12);
    if (!titleRows.length) titleRows = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title) && sim[t].p_title > 0; }).sort(function (x, y) { return sim[y].p_title - sim[x].p_title; }).slice(0, 12).map(function (t) { return { team: t, p: sim[t].p_title }; });
    var html;
    if (isCur) {
      var dig = info.digest || {};
      var lw = LEVEL_WORDS[L];
      html = intro({ tag: U.kicker(L, S),
        title: fb ? 'Every FBS game, team and player, by the numbers.' : 'Every Division I ' + (L === 'mbb' || L === 'mch' ? 'men’s' : 'women’s') + (CC.hk(L) ? ' hockey' : '') + ' game, team and player, by the numbers.',
        lede: fb ? 'Our chance for this week’s games, who’s for real, and the race for the 12-team playoff and the national title, in plain English.'
          : CC.hk(L) ? 'Our chance for this weekend’s series, who’s for real, the NPI and the road to the Frozen Four, in plain English.' : 'Our chance for tonight’s games, who’s for real, and the road to March, in plain English.',
        links: [{ label: 'Games', sub: 'Every game, our chance', href: CC.href(L, 'games', null, S) }, { label: 'Standings', sub: fb ? 'The playoff picture' : CC.hk(L) ? 'The NPI and the bracket' : 'Bracketology', href: CC.href(L, 'standings', null, S) },
          { label: 'Scouting Room', sub: 'Every player, every metric', href: CC.scoutHref(L, S) }] });
      var T = weekTiles(L, S, info, dig, feat, sim);
      var kick = 'This week in ' + lw;
      html += '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: kick, title: T.length >= 3 ? 'The week in ' + WORDS[T.length].toLowerCase() + ' lines' : 'The week so far', sub: stageLine(L, dig.stage, info.phase || season.phase) }) +
        (T.length ? QK.stats(T) : '') + '<div class="ql-feat">' + featHero(L, S, feat, titleRows) + '</div></section>';
    } else {
      /* a past season: the "looking back" greeting over the last result, and the champion tiles */
      /* the hero is the title game (the schedule's championship), else the season's last result */
      var fin = ((a[3] && a[3].games) || []).filter(function (c) { return c.status === 'post' && /championship/i.test(String(c.round || '')) && (c.stype === 'cfp' || c.stype === 'ncaa'); })
        .sort(function (x, y) { return String(y.date).localeCompare(String(x.date)); })[0];
      var featC = fin || (((a[3] && a[3].games) || []).filter(function (c) { return c.status === 'post'; }).sort(function (x, y) { return String(y.date).localeCompare(String(x.date)); })[0]) || null;
      var fg = featC ? CC.game(featC, L) : null;
      html = QK.greeting({ date: U.kicker(L, S), title: esc(CC.LNAME[L] + ' ' + CC.seasonLabel(L, S)) + ', ' + QK.mark('looking back') + '.', lede: (hl ? hl.replace(/\.?$/, '. ') : '') + sub0,
        ctas: [{ label: 'All games', href: CC.href(L, 'games', null, S) }, { label: 'Standings', href: CC.href(L, 'standings', null, S), ghost: true }],
        side: fg ? QK.featureCard(fg, { scribble: fin ? 'The title game' : 'The last game' }) : '' }) +
        '<div style="margin-top:var(--sp-10)">' + tiles(L, S, d, nSims) + '</div>';
    }
    html += isCur ? W.html : recap(L, S, season, post, hist, a[3]) + pastGames(L, S, a[3]);
    html += '<div id="ov-hot"></div>';
    /* round 6: the fan stories (filled after the page draws), then "Who's for real?" (rating against win %) and "What's
       that number?" */
    if (isCur) html += '<section class="qk-section" id="ov-surprise"></section><section class="qk-section" id="ov-spot"></section>';
    html += '<section class="qk-section cc-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Teams top-left are winning more than their rating suggests; bottom-right, the reverse. A soft schedule, luck, or something real?' }) +
      '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" style="--h:440px" role="img" aria-label="Win percentage against our rating, every team"></div><p class="qk-caption" id="ov-luck-cap"></p></div></div></section>';
    html += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0], fb ? 'A <b>rating</b> is points better than an average FBS team on a neutral field: +14 is two touchdowns better.' : CC.hk(L) ? 'A <b>rating</b> is goals a game better than an average Division I team on neutral ice: +1.0 is a goal a game better. A regular-season game level after overtime is a <b>tie</b>.' : 'A <b>rating</b> is points per 100 possessions better than an average Division I team.',
      CC.hk(L) ? 'A player’s <b>GAR</b> is the goals they add over a replacement-level player at the same position (forwards, defence, goalies). Compare it within a position.' : 'A player’s <b>value</b> is what they add over a replacement-level player at the same position. Compare it within a position.'] }) + (CC.hk(L) ? CC.hkCredit(false) : '') + '</section>';
    var top = power.slice(0, 25);
    var grid = '<div class="qk-grid cc-grid">';
    if (titleRows.length) grid += '<div class="qk-span-5">' + U.card('National title chances', 'Our chance of winning it all' + (nSims ? ', from ' + QK.fmt.num(nSims) + ' simulated seasons' : '') + ', in team colours.',
      '<div id="ov-title"></div>', { foot: '<span>Top ' + titleRows.length + '</span>' + U.link(CC.href(L, 'standings', null, S, fb ? 'tab=playoff' : 'tab=bracket'), fb ? 'The playoff picture' : 'The bracket') }) + '</div>';
    if (top.length) grid += '<div class="qk-span-7">' + U.card('Power ratings', (fb ? 'Points better than an average FBS team on a neutral field' : CC.hk(L) ? 'Goals a game better than an average D-I team on neutral ice' : 'Adjusted efficiency margin per 100 possessions') + '; whiskers ± one standard error.',
      U.chart('ov-power', Math.max(320, top.length * 22 + 30), 'Power ratings, top 25') +
      dataTable(['#', 'Team', { label: 'Rating', align: 'right' }, { label: '±', align: 'right' }, { label: 'Record', align: 'right' }], top.map(function (r) { var R = ratings[String(r.team)] || {}, dp = CC.hk(L) ? 2 : 1; return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.rating, html: CC.signed(r.rating, dp) }, CC.f(R.se, dp), rec[String(r.team)] || '—']; }))) + '</div>';
    grid += '</div><div class="qk-grid cc-grid">';
    if (ap.length) {
      var mrank = {}; power.forEach(function (r, i) { mrank[String(r.team)] = r.rank || i + 1; });
      var pts = ap.slice(0, 25).filter(function (r) { return isNum(mrank[String(r.team)]); });
      grid += '<div class="qk-span-6">' + U.card((CC.hk(L) ? 'USCHO' : 'AP') + ' poll v our ranking', 'Across: ' + (CC.hk(L) ? 'USCHO' : 'AP') + ' rank; down: our rank (1 at the top). Above the line, we rank the team higher than the voters do.', U.chart('ov-ap', 340, 'Poll rank against our rank') +
        dataTable(['AP', 'Team', { label: 'Prev', align: 'right' }, { label: 'Ours', align: 'right' }, { label: 'Record', align: 'right' }], ap.slice(0, 25).map(function (r) { return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, isNum(r.prev) ? r.prev : '—', isNum(mrank[String(r.team)]) ? mrank[String(r.team)] : '—', rec[String(r.team)] || '—']; }))) + '</div>';
      d.apPts = pts; d.mrank = mrank;
    }
    grid += isCur || !ap.length ? '<div class="qk-span-' + (ap.length ? 6 : 12) + '" id="ov-post"></div></div>' : '</div>';
    html += U.section(isCur ? (fb ? 'Who wins the national title?' : CC.hk(L) ? 'Who wins the Frozen Four?' : 'Who cuts down the nets?') : 'The season in numbers', isCur ? '<span id="ov-title-lede">Our chances from simulating the rest of the season, the ratings behind them and how they compare with the polls.</span>' : '', grid, '', isCur ? 'Title race' : 'Season');
    html += '<p class="qk-sub cc-ov-doing" style="margin-top:var(--sp-8)"><a class="qk-link" href="' + esc(CC.href(L, 'model', null, null, 'tab=calibration')) + '">How we’re doing →</a> Our recent record and how often our chances came true.</p>';
    el.innerHTML = html;
    U.wire(el);
    if (isCur) drawWatch(el, L, W, G);
    if (isCur) { surprises(L, S, season, power, ap, rec, QK.$('#ov-surprise', el)); unsung(L, S, season, power, ap, QK.$('#ov-spot', el)); }
    realOrNot(L, S, season, ap, QK.$('#ov-luck', el), QK.$('#ov-luck-cap', el));
    if (titleRows.length) {
      QK.$('#ov-title', el).innerHTML = QK.chances(titleRows.map(function (r) { return { label: CC.tshort(L, r.team), p: r.p, href: CC.teamHref(L, r.team, S), color: CC.traw(L, r.team), mark: U.mark(L, r.team) }; }), { key: false }) +
        (QK.decided(titleRows) ? QK.explain('<b>Decided.</b> ' + esc(CC.tname(L, QK.decided(titleRows).team)) + ' won the national title.') : QK.explain('<b>What’s that number?</b> Even the favourite misses most seasons: ' + CC.pct(titleRows[0].p, 0) + ' means about ' + Math.max(1, Math.round(10 * (1 - titleRows[0].p))) + ' seasons in 10 end without the title.'));
      var t0 = titleRows.slice().sort(function (x, y) { return y.p - x.p; })[0], lede = QK.$('#ov-title-lede', el);
      if (t0 && lede && QK.decided(titleRows)) lede.textContent = CC.tshort(L, t0.team) + ' won the national title.';
      else if (t0 && lede) lede.textContent = (t0.p < 0.25 ? 'Nobody’s better than 1 in 4. ' + CC.tshort(L, t0.team) + ' lead our board at ' + CC.pct(t0.p) + '.' : CC.tshort(L, t0.team) + ' lead at ' + CC.pct(t0.p) + '.') + (nSims ? ' From ' + QK.fmt.num(nSims) + ' simulated seasons.' : '');
    }
    if (top.length) QKC.bar('#ov-power', { cats: top.map(function (r) { return CC.tshort(L, r.team); }), horizontal: true, fmt: function (v) { return CC.signed(v, CC.hk(L) ? 2 : 1); },
      series: [{ name: 'Rating', data: top.map(function (r) { return r.rating; }), lo: top.map(function (r) { var R = ratings[String(r.team)] || {}; return isNum(R.se) ? r.rating - R.se : null; }), hi: top.map(function (r) { var R = ratings[String(r.team)] || {}; return isNum(R.se) ? r.rating + R.se : null; }) }],
      colors: top.map(function (r) { return CC.tcol(L, r.team); }), hrefs: top.map(function (r) { return CC.teamHref(L, r.team, S); }), labelWidth: 96, valName: fb ? 'Rating (points v average)' : CC.hk(L) ? 'Rating (goals a game v average)' : 'Margin per 100 possessions', catName: 'Team' });
    if (d.apPts && d.apPts.length) QKC.scatter('#ov-ap', { points: d.apPts.map(function (r) { return { x: r.rank, y: d.mrank[String(r.team)], name: CC.tname(L, r.team), label: CC.tabbr(L, r.team), color: CC.tcol(L, r.team), href: CC.teamHref(L, r.team, S) }; }),
      xName: CC.hk(L) ? 'USCHO rank' : 'AP rank', yName: 'Our rank', xInverse: false, yInverse: true, diagonal: { label: 'agree' }, labelTop: 10, xMin: 0, yMin: 1 });
    postSnapshot(L, S, post, sim, QK.$('#ov-post', el));
    if (!isCur) recapValue(L, S, QK.$('#ov-poy', el));
    leaders(L, S, season, QK.$('#ov-hot', el));
  });
});

/* Leaders (after the page has drawn): names come from value.json's leaderboard. */
/* Who's hot (round 9): the leader of each position on the position's predictive metric, not a counting stat, from
   <L>/<S>/performers.json (20-40 KB; oddsmarkets/college/performers.py: qualified players only, each position on the
   spec's headline set): football QB / RB / WR / DL / DB, basketball guards / forwards / centres, then our value
   leader. HOT_PICK names the metric per position; a position without it takes its first non-value metric. */
var HOT_PICK = { qb: 'epa_play', rb: 'epa_play', wr: 'yptpa', te: 'yptpa', dl: 'havoc_pg', lb: 'havoc_pg', db: 'pd_pg', guards: 'r', forwards: 'r', centers: 'r', all: 'value_pg' };
var HOT_ORDER = { cfb: ['qb', 'rb', 'wr', 'dl', 'db'], bb: ['guards', 'forwards', 'centers', 'all'], hk: ['hk_f', 'hk_d', 'hk_g', 'hk_all'] };
var HOT_POS = { qb: 'Quarterback', rb: 'Running back', wr: 'Wide receiver', te: 'Tight end', dl: 'Defensive line', lb: 'Linebacker', db: 'Defensive back', guards: 'Guard', forwards: 'Forward', centers: 'Centre', all: 'Every player',
  hk_f: 'Forward', hk_d: 'Defence', hk_g: 'Goalie', hk_all: 'Every skater' };
HOT_PICK.hk_f = 'gar_pg'; HOT_PICK.hk_d = 'gar_pg'; HOT_PICK.hk_g = 'gsaa'; HOT_PICK.hk_all = 'gar';
function leaders(L, S, season, hotNode) {
  if (!hotNode) return;
  CC.load(CC.path(L, S, 'performers.json')).then(function (pf) {
    if (!U.alive(hotNode) || !CC.ok(pf)) return;
    var views = {}; (pf.views || []).forEach(function (v) { views[v.key] = v; });
    var hot = (CC.fb(L) ? HOT_ORDER.cfb : CC.hk(L) ? HOT_ORDER.hk : HOT_ORDER.bb).map(function (k) {
      var v = views[k];
      if (!v) return null;
      var ms = v.metrics || [];
      var m = ms.filter(function (x) { return x.key === HOT_PICK[k] && (x.top || []).length; })[0] || ms.filter(function (x) { return x.key !== 'value_pg' && x.key !== 'value' && (x.top || []).length; })[0];
      if (!m) return null;
      var r0 = m.top[0], r1 = m.top[1];
      var dp = /\d/.test(m.fmt || '') ? Number(String(m.fmt).replace(/\D/g, '')) : 2;
      var fv = function (x) { return /^\+/.test(m.fmt || '') ? CC.signed(x, dp) : /pct|%/.test(m.unit || '') && x <= 1 ? CC.pct(x, 1) : CC.f(x, dp); };
      return { sport: 'college', kicker: HOT_POS[k] + ' · ' + CC.uk(m.label), title: CC.tabbr(L, r0[2]) + ' · ' + QK.ordinal(Math.round(r0[4])) + ' percentile of ' + v.n + ' ' + (v.peer || ''), name: r0[1], value: fv(r0[3]),
        href: CC.playerHref(L, r0[0], S), next: r1 ? { name: r1[1], value: fv(r1[3]) } : null, expl: CC.uk(String(m.tip || '').replace(/\s+\S*$/, '').slice(0, 110)) + (m.ours ? ' Ours.' : '') };
    }).filter(Boolean);
    /* v4: the black power list (QK.band + QK.hotRow) */
    if (hot.length) hotNode.innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The best at each position, on what predicts', sub: 'The leader at each position on the number that best predicts how a player there plays, among qualified players, and a line on what it means.', actions: '<a class="qk-more" href="' + esc(CC.scoutHref(L, S, 'view=leaders')) + '">Every position</a>' }) + QK.hotRow(hot));
  });
}

/* Round 6, "Biggest surprise": the largest rating rises since the first weekend and the biggest fall (season.json
   rating_paths: our rating after each week's games; the first point is after the first weekend, so it already has
   that weekend's results). Teams with four or more points on the path; ranks are among those teams on each date. */
function surprises(L, S, season, power, ap, rec, node) {
  if (!node) return;
  var fb = CC.fb(L), P = season.rating_paths || {};
  var ids = Object.keys(P).filter(function (t) { var tm = CC.team(L, t); return (P[t] || []).length >= 4 && (!tm || tm.member !== false); });
  if (ids.length < 20) { node.hidden = true; return; }
  var first = function (t) { return P[t][0][1]; }, last = function (t) { return P[t][P[t].length - 1][1]; };
  var rank0 = {}, rank1 = {};
  ids.slice().sort(function (a, b) { return first(b) - first(a); }).forEach(function (t, i) { rank0[t] = i + 1; });
  ids.slice().sort(function (a, b) { return last(b) - last(a); }).forEach(function (t, i) { rank1[t] = i + 1; });
  var byD = ids.slice().sort(function (a, b) { return (last(b) - first(b)) - (last(a) - first(a)); });
  var picks = [[byD[0], 'Biggest surprise'], [byD[1], 'Rising fast'], [byD[byD.length - 1], 'Biggest fall']].filter(function (x) { return x[0] && Math.abs(last(x[0]) - first(x[0])) >= (CC.hk(L) ? 0.3 : 3); });
  if (!picks.length) { node.hidden = true; return; }
  var N = ids.length, pos = function (r) { return 100 * (1 - (r - 1) / Math.max(1, N - 1)); };
  var d0 = P[picks[0][0]][0][0], unit = fb ? 'points' : CC.hk(L) ? 'goals a game' : 'points per 100';
  node.innerHTML = QK.sectionHead({ kicker: 'Biggest surprise', title: 'Who nobody saw coming', sub: 'The biggest moves in our rating since the first weekend (' + day(d0) + '), up and down. The line is the rating week by week; the track is the rank among ' + N + ' teams.',
    actions: '<a class="qk-more" href="' + esc(CC.href(L, 'teams', null, S)) + '">Every team</a>' }) +
    QK.storyCards(picks.map(function (x) {
      var t = x[0], dlt = last(t) - first(t), tm = CC.team(L, t) || {};
      return { kicker: x[1], name: tm.name || CC.tname(L, t), sub: [rec[t] || '', 'No. ' + rank1[t] + ' in our ratings'].filter(Boolean).join(' · '), href: CC.teamHref(L, t, S), sport: 'college',
        colour: CC.traw(L, t), mark: U.mark(L, t), value: CC.signed(dlt, CC.hk(L) ? 2 : 1), unit: unit + ' of rating',
        from: { label: day(P[t][0][0]), value: 'No. ' + rank0[t], pos: pos(rank0[t]) }, to: { label: 'Now', value: 'No. ' + rank1[t], pos: pos(rank1[t]) },
        spark: P[t].map(function (p) { return p[1]; }), sparkLabel: 'Our rating, week by week',
        text: 'Rated ' + CC.signed(first(t), CC.hk(L) ? 2 : 1) + ' after the first weekend, ' + CC.signed(last(t), CC.hk(L) ? 2 : 1) + ' now' + (rec[t] ? ', at ' + rec[t] : '') + '. ' + (fb ? 'A point of rating is a point better than an average FBS team on a neutral field.' : CC.hk(L) ? 'One point of rating is a goal a game better than an average team.' : 'A point of rating is a point per 100 possessions better than an average team.') };
    }), { cols: 3 });
}
/* Round 6, "Best player nobody talks about": the highest value-model player (value.json leaders) on a team outside the
   AP top 25 and our top 40, and not in the top three of any season leaderboard (the power list already shows those). */
function unsung(L, S, season, power, ap, node) {
  if (!node) return;
  CC.load(CC.path(L, S, 'value.json')).then(function (v) {
    if (!U.alive(node)) return;
    var rows = (CC.ok(v) && v.leaders) || [];
    var inAp = {}; (ap || []).slice(0, 25).forEach(function (r) { inAp[String(r.team)] = 1; });
    var pr = {}; (power || []).forEach(function (r, i) { pr[String(r.team)] = r.rank || i + 1; });
    var lead = {}, LD = season.leaders || {}; Object.keys(LD).forEach(function (k) { (LD[k] || []).slice(0, 3).forEach(function (x) { lead[String(x[0])] = 1; }); });
    var x = rows.filter(function (r) { return r && r.id && isNum(r.value) && !inAp[String(r.team)] && !lead[String(r.id)] && (pr[String(r.team)] || 999) > 40 && (r.gp || 0) >= 4; })[0];
    if (!x) { node.hidden = true; return; }
    var all = rows.filter(function (r) { return isNum(r.value); }), at = all.indexOf(x) + 1;
    var samePos = all.filter(function (r) { return r.pos === x.pos; }), posRank = samePos.indexOf(x) + 1;
    var tm = CC.team(L, x.team) || {}, cur = (v.currency || {}).label || 'Value above replacement';
    node.innerHTML = QK.spotlight({ kicker: 'Best player nobody talks about', name: x.name, sub: [CC.tshort(L, x.team), x.pos, x.class].filter(Boolean).join(' · '), team: { colour: tm.colour, abbr: tm.abbr },
      href: CC.playerHref(L, x.id, S), headline: 'No. ' + at + ' in our value model' + (posRank ? ' (No. ' + posRank + ' at ' + x.pos + ')' : '') + ', on a team outside the AP top 25 and No. ' + (pr[String(x.team)] || '—') + ' in our ratings.',
      stats: [{ label: cur, value: CC.f(x.value, 1) }, { label: 'Per game', value: CC.f(x.value_pg, 1) }, { label: 'Percentile, all players', value: isNum(x.pctl) ? QK.ordinal(Math.round(x.pctl)) : '—' }, { label: 'Games', value: String(x.gp || '—') }],
      text: x.why || '', links: [{ href: CC.playerHref(L, x.id, S), text: 'Player page' }, { href: progHref(CC.playerHref(L, x.id, S)), text: 'Progression' }, { href: CC.teamHref(L, x.team, S), text: CC.tshort(L, x.team) }] });
  });
}

/* Who's for real?: win % against our rating (QKC.quadrant), every team with a game this season; labels on the AP top
   25 and our top 25 (the rest unlabelled, so the chart stays readable with 130-360 teams). */
function realOrNot(L, S, season, ap, node, cap) {
  if (!node) return;
  var fb = CC.fb(L), R = season.ratings || {}, rows = [], seen = {};
  Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { var t = r && String(r.team); if (r && !seen[t] && isNum(r.w) && isNum(r.l) && r.w + r.l > 0 && R[t] && isNum(R[t].rating)) { seen[t] = 1; rows.push(r); } }); });
  if (rows.length < 8) { node.innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.'); if (cap) cap.textContent = ''; return; }
  var named = {};
  (ap || []).slice(0, 25).forEach(function (r) { named[String(r.team)] = 1; });
  Object.keys(R).filter(function (t) { return isNum(R[t].rating); }).sort(function (a, b) { return R[b].rating - R[a].rating; }).slice(0, 25).forEach(function (t) { named[t] = 1; });
  var hk = CC.hk(L), tt = function (r) { return hk ? (r.t || 0) : 0; };
  var pts = rows.map(function (r) { var t = String(r.team), lab = !!named[t]; return { x: R[t].rating, y: 100 * (r.w + 0.5 * tt(r)) / (r.w + r.l + tt(r)), label: lab ? CC.tabbr(L, t) : ' ', name: CC.tname(L, t), sub: (hk ? CC.recW(r) : CC.record(r.w, r.l)) + ' · rating ' + CC.signed(R[t].rating, hk ? 2 : 1), color: CC.traw(L, t), href: CC.teamHref(L, t, S), size: lab ? 13 : 8 }; });
  var gp = rows.map(function (r) { return r.w + r.l + tt(r); }), g0 = Math.min.apply(null, gp), g1 = Math.max.apply(null, gp);
  QKC.quadrant(node, { points: pts, xName: fb ? 'Our rating (points v an average FBS team)' : hk ? 'Our rating (goals a game v average)' : 'Our rating (points per 100 v average)', yName: hk ? 'Points % (a tie is half)' : 'Win %', refX: 0, refY: 50, yMin: 0, yMax: 100,
    xFmt: function (v) { return CC.signed(v, hk ? 1 : 0); }, yFmt: function (v) { return Math.round(v) + '%'; }, label: CC.LSHORT[L] + ' teams: our rating against win percentage' });
  if (cap) cap.textContent = CC.LSHORT[L] + ' ' + CC.seasonLabel(L, S) + ', ' + rows.length + ' teams, ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. Our rating: ' + (fb ? 'expected points margin against an average FBS team on a neutral field' : hk ? 'expected goals a game against an average Division I team on neutral ice' : 'adjusted points per 100 possessions against an average Division I team') + '. Dashed lines: an average rating and a .500 record. Labels: the AP top 25 and our top 25. Tap a team for its page.';
}

/* The CFP picture (cfb) or the bracket picture (basketball). */
/* ── round 9: a past season is a recap ─────────────────────────────────────────────────────────────────────────
   The champion and the final (the greeting's hero), then: our pre-playoff call against what happened (each team in the
   field: our title chance when the field was set, and how far it went), the bracket with the scores, the final
   standings (the field's seeds, conference champions flagged; our final top ten against the AP's), our first-weekend and
   final No. 1, and our player of the season by value (no official awards in our data, so labelled as ours). */
var CFP_ORDER = { 'First Round': 1, 'Quarterfinal': 2, 'Semifinal': 3, 'National Championship': 4 };
var CFP_NAME = ['', 'First round', 'Quarter-finals', 'Semi-finals', 'Runner-up', 'Champion'];
var NCAA_NAME = { R64: 'Round of 64', R32: 'Round of 32', S16: 'Sweet 16', E8: 'Elite 8', F4: 'Final Four', Final: 'Runner-up', Champion: 'Champion' };
var NCAA_RANK = { R64: 1, R32: 2, S16: 3, E8: 4, F4: 5, Final: 6, Champion: 7 };
function recap(L, S, season, post, hist, sched) {
  var fb = CC.fb(L), field = [], champ = null, html = '';
  var ch = ((hist && hist.champions) || []).filter(function (c) { return Number(c.season) === Number(S); })[0] || null;
  if (fb && post && post.actual && post.actual.bracket && (post.actual.bracket.seeds || []).length) {
    var B = post.actual.bracket, reach = {};
    (B.games || []).forEach(function (g) {
      var r = CFP_ORDER[g.round] || 0, w = g.winner ? String(g.winner) : null;
      [g.home, g.away].forEach(function (t) { if (!t) return; t = String(t); var lv = w === t ? (r === 4 ? 5 : r + 1) : (r === 4 ? 4 : r); if (!reach[t] || lv > reach[t]) reach[t] = lv; });
    });
    var odds = post.odds || {};
    field = B.seeds.map(function (x) { var t = String(x.team), o = odds[t] || {}; return { t: t, seed: x.seed, p: o.p_title, reach: reach[t] || 0, txt: CFP_NAME[reach[t] || 0] || 'Played' }; });
    champ = ch ? String(ch.team) : (field.filter(function (f) { return f.reach === 5; })[0] || {}).t;
  } else if (CC.hk(L) && post && post.actual && post.odds) {
    var HKN = { Field: L === 'mch' ? 'Regional semi-final' : 'First round', QF: L === 'mch' ? 'Regional final' : 'Quarter-final', F4: 'Frozen Four', Final: 'Runner-up', Champion: 'Champion' }, HKR = { Field: 1, QF: 2, F4: 3, Final: 4, Champion: 5 };
    var oh = post.odds;
    field = Object.keys(oh).filter(function (t) { return oh[t].reached; }).map(function (t) { var o = oh[t]; return { t: t, seed: o.seed, region: o.region, p: (o.p_round || {}).Champion, reach: HKR[o.reached] || 0, txt: HKN[o.reached] || '—' }; });
    champ = ch ? String(ch.team) : (post.actual.champion ? String(post.actual.champion) : null);
  } else if (!fb && post && post.actual && post.odds) {
    var od = post.odds;
    field = Object.keys(od).filter(function (t) { return isNum(od[t].seed) && od[t].p_round; }).map(function (t) { var o = od[t]; return { t: t, seed: o.seed, region: o.region, p: o.p_round.Champion, reach: NCAA_RANK[o.reached] || 0, txt: NCAA_NAME[o.reached] || '—' }; });
    champ = ch ? String(ch.team) : (post.actual.champion ? String(post.actual.champion) : null);
  }
  if (!field.length && !ch) return '';
  field.sort(function (a, b) { return (b.p || 0) - (a.p || 0); });
  var fav = field[0], cf = field.filter(function (f) { return f.t === champ; })[0];
  var cr = cf ? field.indexOf(cf) + 1 : null;
  /* our first-weekend No. 1 (the first point of the rating paths) and our final No. 1 */
  var P = season.rating_paths || {}, ids = Object.keys(P).filter(function (t) { return (P[t] || []).length; });
  var first = ids.slice().sort(function (a, b) { return P[b][0][1] - P[a][0][1]; })[0];
  var last = ((season.power || [])[0] || {}).team;
  var tiles = [];
  if (ch) tiles.push({ label: 'Champion', value: CC.tshort(L, ch.team), text: true, signal: true, href: CC.teamHref(L, ch.team, S), sub: (ch.score ? ch.score + ' over ' : 'over ') + CC.tname(L, ch.runner_up) });
  if (fav) tiles.push({ label: 'Our favourite when the field was set', value: CC.tabbr(L, fav.t) + ' ' + CC.pct(fav.p), href: CC.teamHref(L, fav.t, S), sub: CC.tname(L, fav.t) + ': ' + fav.txt.toLowerCase() + '.' });
  if (cf && cf !== fav) tiles.push({ label: 'The champion, by our call', value: CC.pct(cf.p), sub: 'our ' + QK.ordinal(cr) + ' favourite of the ' + field.length + ' in the field' });
  if (first) tiles.push({ label: 'Our No. 1 after the first weekend', value: CC.tabbr(L, first), text: true, href: CC.teamHref(L, first, S), sub: CC.tname(L, first) + (last ? '; our final No. 1: ' + CC.tname(L, last) : '') + '.' });
  html += U.section('How we called it', (fb ? 'The ' + field.length + '-team playoff' : 'The NCAA tournament') + ': our chance of winning it all for each team when the field was set, and how far each one went. The champion is marked in volt.',
    U.stats(tiles) + (field.length ? U.card('Our call against what happened', 'Bars: our title chance when the field was set' + (fb ? '' : ' (the top 16)') + '; the line under each name is how far it went.',
      QK.chances(field.slice(0, fb ? 12 : 16).map(function (f) { return { label: CC.tshort(L, f.t), p: f.p || 0, sub: (isNum(f.seed) ? (f.region ? f.region + ' ' : '') + f.seed + ' seed · ' : '') + (f.t === champ ? 'CHAMPION' : f.txt), href: CC.teamHref(L, f.t, S), color: CC.traw(L, f.t), mark: U.mark(L, f.t) }; }), { key: false, oursName: 'Our title chance' })) : ''), '', 'Looking back');
  /* the bracket with the scores */
  var br = fb && post ? CC.cfpBracket(L, S, post) : CC.hk(L) && post ? (CC.hkFrozenFour ? CC.hkFrozenFour(L, S, post) : '') : (!fb && post ? CC.ncaaFinalFour(L, S, post) : '');
  if (br) html += U.section(fb ? 'The bracket' : CC.hk(L) ? 'The Frozen Four' : 'The Final Four', fb ? 'Seeds and results as played; tap a team for its season.' : 'The last four and the final as played.', fb ? U.card('', '', '<div class="cc-bscroll" tabindex="0" role="region" aria-label="Playoff bracket">' + br + '</div>') : br,
    '<a class="qk-btn" href="' + esc(CC.href(L, 'standings', null, S, fb ? 'tab=playoff' : 'tab=bracket')) + '">' + (fb ? 'Every round' : 'The whole bracket') + '</a>', fb ? 'College Football Playoff' : CC.hk(L) ? 'NCAA tournament' : 'March Madness');
  /* the final standings: the field's seeds with conference champions flagged, our final top ten against the AP's */
  var cc = ((hist && hist.conference_champions) || {})[String(S)] || {}, champs = {};
  Object.keys(cc).forEach(function (c) { champs[String(cc[c])] = c; });
  var rec = {}; Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = r; }); });
  var seeds = field.slice().sort(function (a, b) { return (a.seed || 99) - (b.seed || 99) || (b.p || 0) - (a.p || 0); }).slice(0, fb ? 12 : 16);
  var ap = {}; (((season.polls || {}).ap) || ((season.polls || {}).uscho) || []).forEach(function (r) { ap[String(r.team)] = r.rank; });
  var seedT = seeds.length ? U.table([{ label: 'Seed', align: 'right' }, 'Team', { label: 'Record', align: 'right' }, 'Clinched', 'Finished'], seeds.map(function (f) {
    var r = rec[f.t] || {};
    return [isNum(f.seed) ? f.seed : '—', { html: U.teamEnt(L, f.t, { season: S }), v: CC.tname(L, f.t) }, CC.hk(L) ? CC.recW(r) : CC.record(r.w, r.l), champs[f.t] ? '<span class="qk-tag">' + esc(CC.cname(L, champs[f.t])) + ' champion</span>' : '<span class="qk-muted">At-large</span>', { html: f.t === champ ? '<b style="color:var(--volt)">Champion</b>' : esc(f.txt), v: f.reach }];
  }), { sticky: false }) : '';
  var top10 = (season.power || []).slice(0, 10);
  var finT = top10.length ? U.table([{ label: 'Ours', align: 'right' }, 'Team', { label: 'Record', align: 'right' }, { label: 'Final rating', align: 'right' }, { label: 'AP', align: 'right' }], top10.map(function (r, i) {
    var x = rec[String(r.team)] || {};
    return [r.rank || i + 1, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, CC.hk(L) ? CC.recW(x) : CC.record(x.w, x.l), { v: r.rating, html: CC.signed(r.rating, CC.hk(L) ? 2 : 1) }, ap[String(r.team)] || '—'];
  }), { sticky: false }) : '';
  if (seedT || finT) html += U.section('Final standings', 'The field' + (fb ? ' as seeded, conference champions flagged (the automatic bids)' : ', top seeds, conference regular-season champions flagged') + '; and our final top ten beside the last AP poll.',
    '<div class="qk-grid cc-grid">' + (seedT ? '<div class="qk-span-7">' + U.card(fb ? 'The playoff field' : 'The top seeds', '', seedT) + '</div>' : '') + (finT ? '<div class="qk-span-' + (seedT ? 5 : 12) + '">' + U.card('Our final top ten', '', finT) + '</div>' : '') + '</div><div id="ov-poy"></div>', '', 'Standings');
  return html;
}
/* our player of the season by the value model (the official awards are not in our data) */
function recapValue(L, S, node) {
  if (!node) return;
  CC.load(CC.path(L, S, 'value.json')).then(function (v) {
    if (!U.alive(node) || !CC.ok(v)) return;
    var x = (v.leaders || []).filter(function (r) { return isNum(r.value); })[0];
    if (!x) return;
    var tm = CC.team(L, x.team) || {};
    node.innerHTML = '<div style="margin-top:var(--sp-6)">' + QK.spotlight({ kicker: 'Our player of the season', name: x.name, sub: [CC.tshort(L, x.team), CC.posName(L, x.pos), x['class']].filter(Boolean).join(' · '), team: { colour: tm.colour, abbr: tm.abbr },
      href: CC.playerHref(L, x.id, S), headline: 'The most valuable player of ' + CC.seasonLabel(L, S) + ' in our value model: ours, not an official award.',
      stats: [{ label: (v.currency || {}).label || 'Value', value: CC.f(x.value, 1) }, { label: 'Per game', value: CC.f(x.value_pg, 1) }, { label: 'Games', value: String(x.gp || '—') }],
      text: x.why || '', links: [{ href: CC.playerHref(L, x.id, S), text: 'Player page' }, { href: CC.href(L, 'standings', null, S, 'tab=races'), text: 'The whole race' }] }) + '</div>';
  });
}

function postSnapshot(L, S, post, sim, node) {
  if (!node) return;
  var fb = CC.fb(L);
  if (CC.hk(L) && !(post && post.actual)) {
    var hs = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_ncaa) && sim[t].p_ncaa > 0; }).sort(function (a, b) { return sim[b].p_ncaa - sim[a].p_ncaa; }).slice(0, 16);
    node.innerHTML = hs.length ? U.card('The NCAA field', 'Our chance to make the ' + (L === 'mch' ? '16' : '11') + '-team field, with the average seed and the Frozen Four chance in the sub-line.', QK.chances(hs.map(function (t) {
      return { label: CC.tshort(L, t), p: sim[t].p_ncaa, sub: (isNum(sim[t].seed_mean) ? 'seed ' + CC.f(sim[t].seed_mean, 1) : '') + (isNum(sim[t].p_f4) ? ' · Frozen Four ' + CC.pct(sim[t].p_f4) : ''), color: (CC.team(L, t) || {}).colour, href: CC.teamHref(L, t, S), mark: U.mark(L, t) }; }), { max: 1, oursName: 'Our NCAA chance' }),
      { foot: '<span>Top 16</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'Projected bracket and the bubble') }) : U.card('The NCAA field', '', QK.empty('No projected field yet', 'It appears once the season simulation has run.'));
    return;
  }
  if (fb) {
    var odds = (post && post.odds) || {};
    /* v3: our chances in blue (no team colours on the bars) */
    var rows = Object.keys(odds).filter(function (t) { return isNum(odds[t].p_in); }).sort(function (a, b) { return odds[b].p_in - odds[a].p_in; }).slice(0, 12);
    if (!rows.length) rows = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_cfp); }).sort(function (a, b) { return sim[b].p_cfp - sim[a].p_cfp; }).slice(0, 12).map(function (t) { odds[t] = { p_in: sim[t].p_cfp, p_bye: sim[t].p_bye, p_title: sim[t].p_title }; return t; });
    if (!rows.length || !(odds[rows[0]].p_in > 0)) { node.innerHTML = U.card('Playoff picture', '', QK.empty('No playoff chances yet', 'They appear once the season simulation has run.')); return; }
    node.innerHTML = U.card('Playoff picture', 'Our chance to make the 12-team College Football Playoff; the sub-line has the bye and the title.', QK.chances(rows.map(function (t) {
      return { label: CC.tshort(L, t), p: odds[t].p_in, sub: (isNum(odds[t].p_bye) ? 'bye ' + CC.pct(odds[t].p_bye) : '') + (isNum(odds[t].p_title) ? ' · title ' + CC.pct(odds[t].p_title) : ''), color: (CC.team(L, t) || {}).colour, href: CC.teamHref(L, t, S), mark: U.mark(L, t) }; }), { max: 1, oursName: 'Our playoff chance' }),
      { foot: '<span>Top 12</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=playoff'), 'Projected bracket and committee proxy') });
    return;
  }
  var bo = (post && post.bracketology) || [];
  var od = (post && post.odds) || {};
  if (post && post.actual && post.actual.regions) {
    var champ = Object.keys(od).filter(function (t) { return isNum((od[t].p_round || {}).Champion); }).sort(function (a, b) { return od[b].p_round.Champion - od[a].p_round.Champion; }).slice(0, 10);
    node.innerHTML = U.card('Our chances when the field was set', 'Pre-tournament title chance, with the seed and the Final Four chance in the sub-line.', QK.chances(champ.map(function (t) {
      return { label: CC.tshort(L, t), p: od[t].p_round.Champion, sub: '(' + (od[t].seed || '—') + ') · Final Four ' + CC.pct(od[t].p_round.F4), color: (CC.team(L, t) || {}).colour, href: CC.teamHref(L, t, S), mark: U.mark(L, t) }; }), { oursName: 'Our title chance' }),
      { foot: '<span>Top 10</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'The full bracket') });
    return;
  }
  if (!bo.length) { node.innerHTML = U.card('Bracketology', '', QK.empty('No projected field yet', 'Bracketology appears once the season simulation has run.')); return; }
  node.innerHTML = U.card('Bracketology', 'Projected seed lines from simulated seasons and a selection model fitted on past fields.', '<div id="ov-bo"></div>', { flush: true, foot: '<span>Top 16 by projected seed</span>' + U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'Projected bracket') });
  QK.leaderboard(QK.$('#ov-bo', node), { dense: true, maxHeight: 460, rowHref: function (r) { return CC.teamHref(L, r.team, S); }, columns: [
    { key: 'name', label: 'Team', type: 'entity', mark: function (r) { return U.mark(L, r.team); }, sub: 'record' },
    { key: 'seed_mean', label: 'Seed', num: true, fmt: function (v) { return CC.f(v, 1); }, tip: 'Average projected seed across the simulated seasons' },
    { key: 'p_ncaa', label: 'In field', type: 'bar', max: 1, fmt: function (v) { return CC.pct(v); } },
    { key: 'p_auto', label: 'Auto bid', num: true, fmt: function (v) { return CC.pct(v); }, tip: 'Chance of the conference’s automatic bid' }
  ], rows: bo.slice(0, 16).map(function (r) { return Object.assign({ name: CC.tshort(L, r.team) }, r); }) });
}

})(window.CC);
