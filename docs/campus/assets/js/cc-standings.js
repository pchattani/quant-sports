/* The Quant Campus — Standings (#/<L>/standings?tab=...).
 *   Conferences: every conference as a leaderboard (conference and overall record, our rating and rank, our chance to win it).
 *   Polls: AP, Coaches and (cfb) CFP rankings beside our power ranking.
 *   Playoff (cfb): the 12-team CFP bracket (actual, or projected from the committee proxy), P(reach round) heat table,
 *     committee proxy, conference title games.   Bowls (cfb): bowl eligibility chances and announced bowl games.
 *   Bracket (basketball): the 68-team NCAA bracket drawn by region (actual or projected), P(reach round) heat table,
 *     first-round upset chances, bracketology, First Four, last in / first out.   Conference tournaments (basketball).
 * Reads <L>/<S>/season.json, <L>/<S>/cfp.json | bracket.json. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;
var POWER = { cfb: ['SEC', 'Big Ten', 'Big 12', 'ACC'], mbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'], wbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'] };

CC.route('standings', function (el, p) {
  if (CC.hk(p.L) && CC.hkStandings) return CC.hkStandings(el, p);     /* college hockey: cc-hockey.js */
  var L = p.L, S = p.S, fb = CC.fb(L);
  var cur = CC.isCur(L, S);
  var list = fb ? [['conferences', 'Conferences'], ['polls', 'Polls'], ['playoff', 'Playoff'], ['bowls', 'Bowls']] : [['conferences', 'Conferences'], ['polls', 'Polls'], ['bracket', 'Bracket'], ['conftourneys', 'Conference tournaments']];
  /* round 9: Team cards moved to the Teams page (strengths and weaknesses); an old link lands there */
  if ((p.query || {}).tab === 'cards') { window.location.replace(CC.href(L, 'teams', null, S, (p.query || {}).conf && p.query.conf !== 'top' ? 'scope=' + encodeURIComponent(p.query.conf) : '')); return null; }
  if (cur) list.unshift(['race', 'The race']);
  list.push(['history', 'History'], ['races', 'Races']);
  var tab = U.tab(p, list.map(function (x) { return x[0]; }), list[0][0]);
  var sub = { race: 'How the race is shaping up: our chances over time, who moved and why, what is at stake next, the road left and the tiers.', cards: 'Every team’s strengths and weaknesses against the rest of the country, and the shape of the league.',
    conferences: 'Conference and overall records with our rating and the chance to win the conference.', polls: 'The voters next to the model.', playoff: 'The 12-team College Football Playoff: the bracket, everyone’s chance to reach each round, and how the committee may rank them.',
    bowls: 'Who reaches six wins, and the bowl games announced so far.', bracket: 'The NCAA tournament: the bracket by region, each team’s chance to reach each round, and our first-round upset chances.', conftourneys: 'Our chance to win each conference tournament (formats approximated where no bracket is published).',
    history: 'Every champion since ' + (fb ? '2001' : '2002') + ', the programmes that won most, conference titles, and the best teams by our final ratings.',
    races: fb ? 'The race for the best player in college football, by our value model: the season’s leaders, the best freshmen, and the best on each side of the ball.' : 'The race for player of the year, by our value model: the season’s leaders, the best freshmen, and the best guard, forward and centre.' }[tab];
  el.innerHTML = U.head('Standings', sub, U.kicker(L, S)) + U.tabs(L, 'standings', list, S, tab) + chanceNote(L, S, tab) + '<div id="st-body">' + QK.skeleton('lines', 6) + '</div><div id="st-perf"></div>';
  var body = QK.$('#st-body', el);
  var none = Promise.resolve(null);
  return Promise.all([CC.season(L, S), (tab === 'playoff' || tab === 'bowls' || tab === 'bracket' || tab === 'conftourneys' || tab === 'race') ? CC.load(CC.path(L, S, fb ? 'cfp.json' : 'bracket.json')) : none,
    tab === 'race' ? CC.load(CC.lpath(L, 'race_log.json')) : none, tab === 'race' ? CC.load(CC.path(L, S, 'schedule.json')) : none,
    tab === 'history' ? CC.load(CC.lpath(L, 'history.json')) : tab === 'races' ? CC.load(CC.path(L, S, 'value.json')) : none]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[0]) ? a[0] : null;
    if (!season) { body.innerHTML = U.missing('Standings', a[0]); return; }
    if (tab === 'race') CC.raceTab(body, L, S, season, { post: CC.ok(a[1]) ? a[1] : null, log: a[2], sched: CC.ok(a[3]) ? a[3] : null });
    else if (tab === 'conferences') conferences(body, L, S, season);
    else if (tab === 'polls') polls(body, L, S, season);
    else if (tab === 'playoff') playoff(body, L, S, season, a[1]);
    else if (tab === 'bowls') bowls(body, L, S, season, a[1]);
    else if (tab === 'bracket') bracket(body, L, S, season, a[1]);
    else if (tab === 'history') history(body, L, S, a[4]);
    else if (tab === 'races') races(body, L, S, season, a[4]);
    else conftourneys(body, L, S, season, a[1]);
    U.wire(body);
    /* round 9: the player leader boards live in the Scouting Room's Leaders view; a link stays here */
    if (tab === 'race' || tab === 'conferences') QK.$('#st-perf', el).innerHTML = QK.explain('The top and bottom players on each key number, position by position, are in the <a class="qk-link" href="' + esc(CC.scoutHref(L, S, 'view=leaders')) + '">Scouting Room › Leaders</a>, and the teams on the <a class="qk-link" href="' + esc(CC.href(L, 'teams', null, S)) + '">Teams</a> page.', { title: 'Who leads, and who is struggling?' });
  });
});

/* "How to read the chances", only on the tabs that show chances from our simulated seasons (round 9: not on Polls or
   History), in the level's own words. */
function chanceNote(L, S, tab) {
  var on = { race: 1, playoff: 1, bowls: 1, bracket: 1, conftourneys: 1, conferences: CC.isCur(L, S) ? 1 : 0 };
  if (!on[tab]) return '';
  return QK.note('<b>How to read the chances:</b> each is the share of our simulated seasons in which it happens. ' +
    (CC.fb(L) ? 'A 30% playoff chance still comes off about 1 season in 3.' : 'A 30% chance of a place in the NCAA tournament still comes off about 1 season in 3.'));
}

function confOrder(L, season) {
  var cs = Object.keys(season.standings || {});
  var pw = POWER[L] || [];
  return cs.sort(function (a, b) {
    var na = CC.cname(L, a), nb = CC.cname(L, b), ia = pw.indexOf(na), ib = pw.indexOf(nb);
    if (ia < 0) ia = 99; if (ib < 0) ib = 99;
    return ia - ib || na.localeCompare(nb);
  });
}

function conferences(node, L, S, season) {
  var fb = CC.fb(L), sim = (season.sim && season.sim.teams) || {}, R = season.ratings || {};
  var cs = confOrder(L, season);
  var cur = CC.isCur(L, S);
  var chips = '<div class="qk-chips scroll cc-filters" id="cf-chips" role="group" aria-label="Conference">' + ['all'].concat(cs).map(function (c, i) {
    return '<button type="button" class="qk-chip" style="--ca:var(--signal)" data-value="' + esc(c) + '" aria-pressed="' + (i === 0) + '">' + esc(c === 'all' ? 'All' : CC.cname(L, c)) + '</button>'; }).join('') + '</div>';
  var cards = cs.map(function (c, k) {
    var rows = season.standings[c] || [];
    var hasDiv = rows.some(function (r) { return r.division; });
    return '<div class="cc-conf" data-conf="' + esc(c) + '">' + U.card(CC.conf(L, c) ? (CC.conf(L, c).name || CC.cname(L, c)) : CC.cname(L, c), rows.length + ' teams' + (hasDiv ? ' · divisions' : '') + (cur ? ' · the bar is our chance to win the ' + (fb ? 'conference' : 'regular-season title') : '') + ' · ' + U.link(CC.href(L, 'teams', null, S, 'scope=' + encodeURIComponent(c)), 'Team profiles'), U.lb('cf-' + k), { flush: true }) + '</div>';
  }).join('');
  node.innerHTML = chips + '<div class="cc-confs">' + cards + '</div>';
  cs.forEach(function (c, k) {
    var rows = (season.standings[c] || []).map(function (r) {
      var t = String(r.team), s0 = sim[t] || {}, rt = R[t] || {};
      return { team: t, name: CC.tshort(L, t), sub: isNum(r.rank) ? '#' + r.rank + ' AP' : '', conf_rank: r.conf_rank, conf: CC.record(r.conf_w, r.conf_l), cdiff: (r.conf_w || 0) - (r.conf_l || 0),
        overall: CC.record(r.w, r.l), odiff: (r.w || 0) - (r.l || 0), rating: rt.rating, rating_rank: r.rating_rank, streak: r.streak || '—',
        pc: fb ? s0.p_conf : (isNum(s0.p_conf_reg) ? s0.p_conf_reg : s0.p_conf_tourney) };
    });
    var cols = [
      { key: 'conf_rank', label: '#', num: true },
      { key: 'name', label: 'Team', type: 'entity', sub: 'sub', mark: function (r) { return U.mark(L, r.team); }, href: function (r) { return CC.teamHref(L, r.team, S); } },
      { key: 'cdiff', label: 'Conf', num: true, fmt: function (v, r) { return esc(r.conf); }, tip: 'Conference record' },
      { key: 'odiff', label: 'Overall', num: true, fmt: function (v, r) { return esc(r.overall); } },
      { key: 'rating', label: 'Rating', num: true, fmt: function (v) { return CC.signed(v, 1); }, tip: fb ? 'Our rating: points better than an average FBS team' : 'Our rating: adjusted margin per 100 possessions' },
      { key: 'rating_rank', label: 'Rk', num: true, tip: 'Our national rank' },
      { key: 'streak', label: 'Strk' }
    ];
    if (cur && rows.some(function (r) { return isNum(r.pc); })) cols.push({ key: 'pc', label: fb ? 'Conf title' : 'Reg. title', type: 'bar', max: 1, fmt: function (v) { return CC.pct(v); }, tip: 'Our chance to win the conference, from simulating the rest of the season' });
    QK.leaderboard(QK.$('#cf-' + k, node), { dense: true, columns: cols, rows: rows, rowHref: function (r) { return CC.teamHref(L, r.team, S); } });
  });
  QK.chips(QK.$('#cf-chips', node), function (v) {
    var c = v[0] || 'all';
    QK.$$('.cc-conf', node).forEach(function (x) { x.hidden = c !== 'all' && x.getAttribute('data-conf') !== c; });
  });
}

function polls(node, L, S, season) {
  var P = season.polls || {}, power = season.power || [];
  var mr = {}; power.forEach(function (r, i) { mr[String(r.team)] = r.rank || i + 1; });
  var rec = {};
  Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = CC.record(r.w, r.l); }); });
  function tbl(rows, kind) {
    if (!rows || !rows.length) return QK.empty('No ' + kind + ' ranking', kind === 'CFP' ? 'The committee publishes its first ranking in early November.' : 'Not published for this season yet.');
    return U.table([{ label: '#', align: 'right' }, 'Team', { label: 'Prev', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Ours', align: 'right', title: 'Our power rank' }, { label: 'Rec.', align: 'right' }], rows.slice(0, 25).map(function (r) {
      var t = String(r.team), mv = isNum(r.prev) ? r.prev - r.rank : null;
      return [r.rank, { html: U.teamEnt(L, t, { season: S }) + (mv ? ' <span class="cc-mv ' + (mv > 0 ? 'pos' : 'neg') + '">' + (mv > 0 ? '▲' : '▼') + Math.abs(mv) + '</span>' : (r.prev === null || r.prev === undefined ? ' <span class="qk-muted cc-mv">new</span>' : '')), v: CC.tname(L, t) },
        isNum(r.prev) ? r.prev : '—', isNum(r.points) ? r.points : '—', isNum(mr[t]) ? mr[t] : '—', rec[t] || '—'];
    }), { maxHeight: 640 });
  }
  var cards = [U.card('AP Top 25', 'Media poll', tbl(P.ap, 'AP')), U.card('Coaches Poll', '', tbl(P.coaches, 'Coaches'))];
  if (CC.fb(L)) cards.push(U.card('CFP rankings', 'Selection committee', tbl(P.cfp, 'CFP')));
  /* round 9: our power ranking is the Teams page's power board; the "Ours" column above keeps it beside the polls */
  node.innerHTML = '<div class="cc-polls">' + cards.join('') + '</div>' + QK.explain('Our own top 25 is the <a class="qk-link" href="' + esc(CC.href(L, 'teams', null, S)) + '">Teams page’s power board</a>: our rating split into offence and defence, with the move since last week. The “Ours” column above is that rank.', { title: 'Our power ranking.' });
}

/* ── History: champions, dynasties, conference titles, the best teams (<L>/history.json) ─────────────────── */
var POW_CONF = { cfb: ['SEC', 'Big Ten', 'Big 12', 'ACC'], mbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'], wbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'] };
function history(node, L, S, h) {
  if (!CC.ok(h) || !(h.champions || []).length) { node.innerHTML = U.missing('The history', h); return; }
  var fb = CC.fb(L), ch = (h.champions || []).slice().sort(function (a, b) { return b.season - a.season; });
  var titles = {};
  ch.forEach(function (c) { var t = String(c.team); (titles[t] = titles[t] || []).push(c.season); });
  var kings = Object.keys(titles).sort(function (a, b) { return titles[b].length - titles[a].length || Math.max.apply(null, titles[b]) - Math.max.apply(null, titles[a]); });
  var first = ch[ch.length - 1].season, last = ch[0].season;
  /* back to back: runs of consecutive titles */
  var runs = [];
  kings.forEach(function (t) {
    var ys = titles[t].slice().sort(function (a, b) { return a - b; }), st = ys[0], pv = ys[0];
    ys.slice(1).concat([null]).forEach(function (y) { if (y === pv + 1) { pv = y; return; } if (pv > st) runs.push({ t: t, a: st, b: pv }); st = pv = y; });
  });
  runs.sort(function (a, b) { return (b.b - b.a) - (a.b - a.a) || b.b - a.b; });
  var top = kings[0];
  var stats = U.stats([{ label: 'Most titles since ' + CC.seasonLabel(L, first), value: CC.tabbr(L, top) + ' ' + titles[top].length, signal: true, href: CC.teamHref(L, top, S), sub: CC.tname(L, top) + ': ' + titles[top].slice().sort().map(function (y) { return CC.seasonLabel(L, y); }).join(', ') },
    { label: 'Different champions', value: String(kings.length), sub: 'in ' + ch.length + ' seasons, ' + CC.seasonLabel(L, first) + ' to ' + CC.seasonLabel(L, last) },
    runs.length ? { label: 'Back to back', value: CC.tabbr(L, runs[0].t) + ' ' + (runs[0].b - runs[0].a + 1), href: CC.teamHref(L, runs[0].t, S), sub: CC.tname(L, runs[0].t) + ', ' + CC.seasonLabel(L, runs[0].a) + ' to ' + CC.seasonLabel(L, runs[0].b) } : null,
    { label: 'Latest champion', value: CC.tshort(L, ch[0].team), text: true, href: CC.teamHref(L, ch[0].team, S), sub: CC.seasonLabel(L, ch[0].season) + (ch[0].score && ch[0].runner_up ? ', ' + ch[0].score + ' over ' + CC.tshort(L, ch[0].runner_up) : '') }]);
  /* the dynasty strip: one team-colour block per title (the season on it), the programmes in order of titles */
  var strip = '<div class="cc-dyn" role="list">' + kings.map(function (t) {
    var tm = CC.team(L, t) || {}, b = QK.color.block(tm.colour && QK.color.parse(tm.colour) ? tm.colour : null);
    return '<div class="cc-dyn-r" role="listitem"><a class="cc-dyn-n" href="' + esc(CC.teamHref(L, t, S)) + '">' + QK.teamMark(U.mark(L, t), 'sm') + '<span>' + esc(CC.tshort(L, t)) + '</span></a><span class="cc-dyn-b">' +
      titles[t].slice().sort().map(function (y) { return '<i style="background:' + esc(b.bg) + (b.edge ? ';box-shadow:inset 0 -4px 0 ' + esc(b.edge) : '') + '" title="' + esc(CC.tname(L, t) + ', ' + CC.seasonLabel(L, y)) + '">' + esc('’' + String(y).slice(2)) + '</i>'; }).join('') + '</span><b class="num">' + titles[t].length + '</b></div>';
  }).join('') + '</div>';
  var tbl = U.table([{ label: 'Season', align: 'right' }, 'Champion', 'Runner-up', { label: 'Final', align: 'right' }], ch.map(function (c) {
    var gl = c.gid && CC.hasPage(L, { season: c.season, stype: fb ? 'cfp' : 'ncaa' }, c.season) ? '<a href="' + esc(CC.gameHref(L, c.gid, c.season)) + '">' + esc(c.score || 'Game') + '</a>' : esc(c.score || '—');
    return [{ v: c.season, html: esc(CC.seasonLabel(L, c.season)) }, { html: U.teamEnt(L, c.team, { season: c.season }), v: CC.tname(L, c.team) }, c.runner_up ? { html: U.teamEnt(L, c.runner_up, { season: c.season }), v: CC.tname(L, c.runner_up) } : '—', { html: gl, v: c.score }];
  }), { maxHeight: 560 });
  /* conference titles: the most per power conference */
  var cc = h.conference_champions || {}, byConf = {};
  Object.keys(cc).forEach(function (y) { Object.keys(cc[y] || {}).forEach(function (c) { var t = String(cc[y][c]); byConf[c] = byConf[c] || {}; byConf[c][t] = (byConf[c][t] || 0) + 1; }); });
  var confs = Object.keys(byConf).filter(function (c) { return (POW_CONF[L] || []).indexOf(CC.cname(L, c)) >= 0; });
  var confT = confs.length ? '<div class="cc-auto">' + confs.map(function (c) {
    var rows = Object.keys(byConf[c]).sort(function (a, b) { return byConf[c][b] - byConf[c][a]; }).slice(0, 5);
    return U.card(CC.cname(L, c), 'Most ' + (fb ? 'conference titles' : 'regular-season titles') + ' in our data', '<ul class="cc-list">' + rows.map(function (t) { return '<li>' + U.teamEnt(L, t, { season: S }) + '<span class="v">' + byConf[c][t] + '</span></li>'; }).join('') + '</ul>');
  }).join('') + '</div>' : '';
  var best = (h.best_teams || []).slice(0, 15);
  var bestT = best.length ? U.table(['#', { label: 'Season', align: 'right' }, 'Team', { label: 'Record', align: 'right' }, { label: 'Final rating', align: 'right' }], best.map(function (r, i) {
    return [i + 1, { v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, { html: U.teamEnt(L, r.team, { season: r.season }), v: r.name || CC.tname(L, r.team) }, r.record || '—', { v: r.rating, html: CC.signed(r.rating, 1) }];
  }), { sticky: false }) : '';
  node.innerHTML = stats + U.section('Dynasties', 'Every national champion since ' + CC.seasonLabel(L, first) + ': one block per title in the team’s colour, the season on the block.', U.card('', '', strip), '', 'Titles') +
    '<div class="qk-grid cc-grid"><div class="qk-span-7">' + U.card('Every champion', 'The ' + (fb ? 'BCS (2001-13) and College Football Playoff' : 'NCAA tournament') + ' finals as ESPN records them.', tbl) + '</div><div class="qk-span-5">' +
    (bestT ? U.card('The best teams', 'By our final rating (' + (fb ? 'points v an average FBS team' : 'points per 100 v an average D-I team') + '), every game counted.', bestT) : '') + '</div></div>' +
    (confT ? U.section('Conference titles', 'The power conferences’ most frequent champions.', confT, '', 'Conferences') : '') +
    ((h.notes || []).length ? U.note(esc((h.notes || []).join(' '))) : '');
}

/* ── Races: the player-of-the-year race by our value model (value.json leaders) ─────────────────────────────── */
function races(node, L, S, season, v) {
  if (!CC.ok(v) || !(v.leaders || []).length) { node.innerHTML = U.missing('The races', v); return; }
  var fb = CC.fb(L), rows = (v.leaders || []).filter(function (r) { return isNum(r.value); });
  var cur = (v.currency || {}).label || 'Value above replacement';
  var power = {}; (season.power || []).forEach(function (r, i) { power[String(r.team)] = r.rank || i + 1; });
  var nm = fb ? 'Heisman watch' : 'Player of the year';
  var bar = function (list) {
    var max = list.length ? Math.max.apply(null, list.map(function (r) { return r.value; })) : 1;
    return '<ol class="cc-race-l">' + list.map(function (r, i) {
      var tm = CC.team(L, r.team) || {};
      return '<li><span class="cc-race-rk num">' + (i + 1) + '</span>' + QK.teamMark(U.mark(L, r.team), 'sm') + '<span class="cc-race-nm"><a href="' + esc(CC.playerHref(L, r.id, S)) + '">' + esc(r.name) + '</a><small>' +
        esc([CC.posName(L, r.pos), CC.tshort(L, r.team), r['class'] || '', r.gp + ' games', power[String(r.team)] ? 'team No. ' + power[String(r.team)] + ' in our ratings' : ''].filter(Boolean).join(' · ')) + '</small>' +
        (r.why ? '<span class="cc-race-why">' + esc(r.why) + '</span>' : '') + '</span><span class="cc-race-bar" aria-hidden="true"><i style="width:' + Math.max(3, 100 * r.value / max).toFixed(1) + '%;background:' + esc(tm.colour && QK.color.parse(tm.colour) ? QK.color.team(tm.colour) : 'var(--signal)') + '"></i></span><b class="num">' + CC.f(r.value, 1) + '</b></li>';
    }).join('') + '</ol>';
  };
  var fr = rows.filter(function (r) { return /^FR/i.test(r['class'] || ''); }).slice(0, 5);
  var sides = fb ? [['Offence', ['QB', 'RB', 'WR', 'TE']], ['Defence', ['DL', 'LB', 'DB']]] : [['Guards', ['G']], ['Forwards', ['F']], ['Centres', ['C']]];
  var side = sides.map(function (sd) { var l = rows.filter(function (r) { return sd[1].indexOf(r.pos) >= 0; }).slice(0, 5); return l.length ? '<div class="qk-span-' + (fb ? 6 : 4) + '">' + U.card(sd[0], 'The top five by value', bar(l)) + '</div>' : ''; }).join('');
  node.innerHTML = U.section(nm + ': the value race', 'The ten most valuable players ' + (CC.isCur(L, S) ? 'this season' : 'of ' + CC.seasonLabel(L, S)) + ' in our value model (' + esc(String(cur).toLowerCase()) + '); the bar is each player’s value against the leader’s. ' +
    (fb ? 'A guide to who has done most, not a forecast of the voters: the Heisman goes mostly to quarterbacks and backs on winning teams, and our value compares best within a position.' : 'A guide to who has done most, not a forecast of the voters.'), U.card('', '', bar(rows.slice(0, 10))), '', 'Races') +
    '<div class="qk-grid cc-grid">' + side + '</div>' +
    (fr.length ? U.section('Freshman of the year', 'The five most valuable freshmen.', U.card('', '', bar(fr)), '', 'Races') : '') +
    QK.explain('Every player’s value, percentiles and position view are on the <a class="qk-link" href="' + esc(CC.scoutHref(L, S, 'cols=Value')) + '">Scouting Room board</a>.', { title: 'More players.' });
}

/* ── CFP bracket ─────────────────────────────────────────────────────── */
var QF_TOP = [1, 4, 2, 3], FR_PAIRS = [[8, 9], [5, 12], [7, 10], [6, 11]];
function slotTeam(L, S, tid, seed, extra, win, lose) {
  if (!tid) return '<div class="cc-bt empty"><span class="sd">' + (isNum(seed) ? seed : '') + '</span><span class="nm">' + esc(extra || 'TBD') + '</span></div>';
  var t = CC.team(L, tid) || { name: 'Team ' + tid };
  return '<a class="cc-bt' + (win ? ' win' : '') + (lose ? ' lose' : '') + '" href="' + esc(CC.teamHref(L, tid, S)) + '" style="--tc:' + esc(QK.color.parse(t.colour) ? QK.color.team(t.colour) : 'var(--c-other)') + '">' +
    '<span class="sd">' + (isNum(seed) ? seed : '') + '</span><span class="nm">' + esc(t.short || t.name) + '</span><span class="pr">' + (extra || '') + '</span></a>';
}
function cfpBracket(L, S, cfp) {
  var actual = cfp.actual && cfp.actual.bracket && cfp.actual.bracket.seeds && cfp.actual.bracket.seeds.length ? cfp.actual.bracket : null;
  var B = actual || cfp.projected_bracket;
  if (!B || !B.seeds || !B.seeds.length) return '';
  var seedOf = {}, bySeed = {};
  B.seeds.forEach(function (s) { seedOf[String(s.team)] = s.seed; bySeed[s.seed] = String(s.team); });
  var odds = cfp.odds || {};
  var games = B.games || [];
  function find(round, seeds) {
    return games.filter(function (g) {
      if (String(g.round).toLowerCase().indexOf(round) < 0) return false;
      var s1 = seedOf[String(g.home)], s2 = seedOf[String(g.away)];
      return seeds.indexOf(s1) >= 0 || seeds.indexOf(s2) >= 0;
    })[0] || null;
  }
  function pr(t, k) { var o = odds[String(t)]; return o && isNum(o[k]) ? CC.pct(o[k]) : ''; }
  function box(g, a, b, label, key) {
    var ta = g && g.home ? String(g.home) : a, tb = g && g.away ? String(g.away) : b;
    var w = g && g.winner ? String(g.winner) : null;
    var href = g && g.gid ? CC.gameHref(L, g.gid, S) : null;
    var meta = g && isNum(g.p_home) && !w ? CC.pct(g.p_home) + ' ' + CC.tabbr(L, g.home) : '';
    return '<div class="cc-bg">' + (label ? '<div class="cc-bg-l">' + esc(label) + (href ? ' · <a href="' + esc(href) + '">game</a>' : '') + (meta ? ' · ' + esc(meta) : '') + '</div>' : '') +
      slotTeam(L, S, ta, seedOf[ta], actual ? '' : pr(ta, key), w && w === ta, w && w !== ta) + slotTeam(L, S, tb, seedOf[tb], actual ? '' : (tb ? pr(tb, key) : 'winner'), w && w === tb, w && w !== tb) + '</div>';
  }
  var n = B.seeds.length;
  if (n <= 4) {
    var sf0 = find('semi', [1, 4]), sf1 = find('semi', [2, 3]), fin0 = find('champ', [1, 2, 3, 4]);
    return '<div class="cc-bracket cfp four"><div class="cc-bcol"><div class="cc-bh">Semifinals</div>' + box(sf0, bySeed[1], bySeed[4], '1 v 4', 'p_final') + box(sf1, bySeed[2], bySeed[3], '2 v 3', 'p_final') + '</div>' +
      '<div class="cc-bcol"><div class="cc-bh">Final</div>' + box(fin0, null, null, 'National Championship', 'p_title') + (fin0 && fin0.winner ? '<div class="cc-champ">' + QK.teamMark(CC.team(L, fin0.winner) || {}, 'lg') + '<div><div class="qk-kicker">Champion</div><b>' + esc(CC.tname(L, fin0.winner)) + '</b></div></div>' : '') + '</div></div>';
  }
  var colFR = '<div class="cc-bcol"><div class="cc-bh">First round</div>', colQF = '<div class="cc-bcol"><div class="cc-bh">Quarterfinals</div>', colSF = '<div class="cc-bcol"><div class="cc-bh">Semifinals</div>', colF = '<div class="cc-bcol"><div class="cc-bh">Final</div>';
  /* projected: later rounds show the likeliest team from each feeder group (by its chance to reach that round) */
  function likeliest(seeds, key) {
    var best = null, bp = -1;
    seeds.forEach(function (sd) { var t = bySeed[sd], o = t ? odds[t] : null, v = o && isNum(o[key]) ? o[key] : -1; if (t && v > bp) { bp = v; best = t; } });
    return best;
  }
  FR_PAIRS.forEach(function (pp, k) {
    var g = find('first', pp);
    colFR += box(g, bySeed[pp[0]], bySeed[pp[1]], pp[0] + ' v ' + pp[1] + (actual ? '' : ' · on campus'), 'p_qf');
    var q = find('quarter', [QF_TOP[k]].concat(pp));
    var winFR = g && g.winner ? String(g.winner) : (actual ? null : likeliest(pp, 'p_qf'));
    colQF += box(q && q.away ? q : null, bySeed[QF_TOP[k]], winFR, QF_TOP[k] + ' v ' + pp.join('/') + (actual ? ' winner' : ' (likeliest)'), 'p_sf');
  });
  var SIDES = [[[1, 8, 9], [4, 5, 12]], [[2, 7, 10], [3, 6, 11]]];
  var sf = [find('semi', [1, 8, 9, 4, 5, 12]), find('semi', [2, 7, 10, 3, 6, 11])];
  [0, 1].forEach(function (i) {
    var g = sf[i] && sf[i].away ? sf[i] : null;
    var a0 = sf[i] && sf[i].home ? String(sf[i].home) : (actual ? null : likeliest(SIDES[i][0], 'p_sf'));
    var b0 = sf[i] && sf[i].away ? String(sf[i].away) : (actual ? null : likeliest(SIDES[i][1], 'p_sf'));
    colSF += box(g, a0, b0, (i ? '2 / 3 side' : '1 / 4 side') + (actual ? '' : ' (likeliest)'), 'p_final');
  });
  var fn = find('champ', [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  var fa = fn && fn.home ? String(fn.home) : (actual ? null : likeliest(SIDES[0][0].concat(SIDES[0][1]), 'p_final'));
  var fbt = fn && fn.away ? String(fn.away) : (actual ? null : likeliest(SIDES[1][0].concat(SIDES[1][1]), 'p_final'));
  colF += box(fn && fn.away ? fn : null, fa, fbt, 'National Championship' + (actual ? '' : ' (likeliest)'), 'p_title');
  if (fn && fn.winner) colF += '<div class="cc-champ">' + QK.teamMark(CC.team(L, fn.winner) || {}, 'lg') + '<div><div class="qk-kicker">Champion</div><b>' + esc(CC.tname(L, fn.winner)) + '</b></div></div>';
  return '<div class="cc-bracket cfp">' + colFR + '</div>' + colQF + '</div>' + colSF + '</div>' + colF + '</div></div>';
}

function playoff(node, L, S, season, cfp) {
  if (!CC.ok(cfp)) { node.innerHTML = U.missing('The playoff picture', cfp); return; }
  var actual = cfp.actual && cfp.actual.bracket && cfp.actual.bracket.seeds && cfp.actual.bracket.seeds.length;
  var fmt0 = cfp.format || {};
  var html = '';
  var br = cfpBracket(L, S, cfp);
  html += U.card(actual ? 'The bracket' : 'Projected bracket', (actual ? 'Seeds and results as played.' : 'The most likely field and seeding from our committee proxy; percentages are each team’s chance to reach the next round.') +
    (fmt0.note ? ' ' + esc(fmt0.note) + '.' : (fmt0.rule ? ' Format: ' + esc(fmt0.rule) + (fmt0.verified === false ? ' (not yet confirmed for this season)' : '') + '.' : '')), br ? '<div class="cc-bscroll" tabindex="0" role="region" aria-label="Playoff bracket">' + br + '</div>' : QK.empty('No bracket yet', 'The field is projected once the season sim has run.'));
  var odds = cfp.odds || {};
  var ts = Object.keys(odds).filter(function (t) { return isNum(odds[t].p_in) && odds[t].p_in > 0.002; }).sort(function (a, b) { return odds[b].p_in - odds[a].p_in || (odds[b].p_title || 0) - (odds[a].p_title || 0); }).slice(0, 25);
  var heat = U.table(['Team', { label: 'In', align: 'right' }, { label: 'Bye', align: 'right' }, { label: 'QF', align: 'right' }, { label: 'SF', align: 'right' }, { label: 'Final', align: 'right' }, { label: 'Title', align: 'right' }, { label: 'Likeliest seed', align: 'right' }], ts.map(function (t) {
    var o = odds[t], sd = o.seed_dist || {}, best = Object.keys(sd).sort(function (a, b) { return sd[b] - sd[a]; })[0];
    return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, U.heat(o.p_in), U.heat(o.p_bye), U.heat(o.p_qf), U.heat(o.p_sf), U.heat(o.p_final), U.heat(o.p_title), best ? best + ' (' + CC.pct(sd[best]) + ')' : '—'];
  }), { maxHeight: 620 });
  var proxy = cfp.committee_proxy || [];
  var pf = cfp.proxy_fit || {};
  var px = proxy.length ? U.table([{ label: '#', align: 'right' }, 'Team', { label: 'Rec.', align: 'right' }, { label: 'Score', align: 'right' }, { label: 'Top 12', align: 'right' }, { label: 'Conf. champ', align: 'right' }, { label: 'SOS rk', align: 'right' }], proxy.map(function (r) {
    return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, r.record || '—', CC.f(r.score, 2), U.heat(r.p_top12), U.heat(r.conf_champ_p), isNum(r.sos_rank) ? r.sos_rank : '—'];
  }), { maxHeight: 620 }) : QK.empty('No committee proxy', '');
  var actualRk = cfp.actual && cfp.actual.rankings && cfp.actual.rankings.length ? U.table([{ label: '#', align: 'right' }, 'Team'], cfp.actual.rankings.slice(0, 25).map(function (r) { return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }]; }), { maxHeight: 620 }) : '';
  html += '<div class="qk-grid cc-grid"><div class="qk-span-7">' + U.card('Chance to reach each round', 'Our chances: the share of simulated seasons. Darker blue is likelier.', heat) + '</div><div class="qk-span-5">' +
    U.card('Committee proxy', 'How the committee may rank teams, fitted on its past rankings' + (pf.n_seasons ? ' (' + pf.n_seasons + ' seasons; out of sample Spearman ' + CC.f(pf.spearman, 2) + ', ' + (isNum(pf.top12_overlap) && pf.top12_overlap <= 1 ? CC.pct(pf.top12_overlap, 0) + ' of the top 12' : CC.f(pf.top12_overlap, 1) + ' of the top 12') + ' matched)' : '') + '. An estimate, not the committee.', px) +
    (actualRk ? U.card('Final CFP ranking', '', actualRk) : '') + '</div></div>';
  var ctg = cfp.conf_title_games || {};
  var cks = Object.keys(ctg).filter(function (c) { return (ctg[c] || []).length; });
  if (cks.length) {
    html += U.section('Conference championship games', 'Chance to play in, and to win, each conference title game.', '<div class="cc-auto">' + cks.map(function (c) {
      return U.card(CC.cname(L, c), '', U.table(['Team', { label: 'Plays in', align: 'right' }, { label: 'Wins', align: 'right' }], ctg[c].slice(0, 6).map(function (r) { return [{ html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, U.heat(r.p_appear), U.heat(r.p_win)]; }), { sticky: false }));
    }).join('') + '</div>');
  }
  node.innerHTML = html;
}

function bowls(node, L, S, season, cfp) {
  if (!CC.ok(cfp)) { node.innerHTML = U.missing('Bowl projections', cfp); return; }
  var el = (cfp.bowls && cfp.bowls.eligible) || {};
  var rec = {};
  Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = r; }); });
  var bubble = Object.keys(el).filter(function (t) { return isNum(el[t]) && el[t] > 0.05 && el[t] < 0.95; }).sort(function (a, b) { return el[b] - el[a]; });
  var locked = Object.keys(el).filter(function (t) { return el[t] >= 0.95; }).length;
  var out = Object.keys(el).filter(function (t) { return el[t] <= 0.05; }).length;
  var games = (cfp.bowls && cfp.bowls.games) || [];
  var html = U.stats([{ label: 'Bowl eligible', value: String(locked), unit: 'teams', signal: true, sub: 'our chance of six wins is 95% or more' }, { label: 'On the bubble', value: String(bubble.length), unit: 'teams', sub: '5% to 95% to reach six wins' }, { label: 'Out', value: String(out), unit: 'teams', sub: 'under 5% to reach six wins' }]);
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('The bubble', 'Chance to reach six wins (bowl eligibility; the 5-7 exception is ignored).', bubble.length ? U.table(['Team', { label: 'Rec.', align: 'right' }, { label: 'Six wins', align: 'right' }, ''], bubble.map(function (t) {
    var r = rec[t] || {};
    return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, CC.record(r.w, r.l), { v: el[t], html: CC.pct(el[t]) }, { html: U.bar(el[t]), v: el[t] }];
  }), { maxHeight: 640 }) : QK.empty('Nobody on the bubble', '')) + '</div><div class="qk-span-6">' +
    U.card('Bowl games', games.length ? games.length + ' announced' : '', games.length ? '<div class="cc-games one">' + games.map(function (c) { return CC.card(c, L); }).join('') + '</div>' : QK.empty('No bowl matchups yet', 'Bowl pairings are announced after the conference championship games.')) + '</div></div>';
  node.innerHTML = html;
}

/* ── NCAA bracket ────────────────────────────────────────────────────── */
var R64_ORDER = [[1, 16], [8, 9], [5, 12], [4, 13], [6, 11], [3, 14], [7, 10], [2, 15]];
var SLOT0 = {}; R64_ORDER.forEach(function (pp, i) { SLOT0[pp[0]] = i; SLOT0[pp[1]] = i; });
var RKEYS = ['R64', 'R32', 'S16', 'E8', 'F4', 'Final', 'Champion'];
var RNAMES = { 'Round of 64': 0, 'Round of 32': 1, 'Sweet 16': 2, 'Elite 8': 3, 'Final Four': 4, 'National Championship': 5 };
function regionData(L, S, br) {
  var actual = br.actual && br.actual.regions && Object.keys(br.actual.regions).length ? br.actual : null;
  var regs = actual ? actual.regions : ((br.projected && br.projected.regions) || {});
  var names = Object.keys(regs);
  var seedOf = {}, regOf = {};
  names.forEach(function (r) { (regs[r] || []).forEach(function (x) { seedOf[String(x.team)] = x.seed; regOf[String(x.team)] = r; }); });
  var games = actual ? (actual.games || []) : [];
  return { actual: actual, regs: regs, names: names, seedOf: seedOf, regOf: regOf, games: games, sites: (actual && actual.sites) || {} };
}
/* A region heading: women's regions named for their host city (2005-2022) read "Albany Regional"; numbered ones
 * (2023 on) add the city ("Regional 1 · Albany"); compass regions as they are. */
function regionTitle(D, rname) {
  var site = D.sites[rname];
  if (!site) return rname;
  return site === rname ? rname + ' Regional' : rname + ' · ' + site;
}
function regionHTML(L, S, br, D, rname) {
  var odds = br.odds || {};
  var teams = D.regs[rname] || [];
  var bySeed = {};
  teams.forEach(function (x) { (bySeed[x.seed] = bySeed[x.seed] || []).push(String(x.team)); });
  var games = D.games.filter(function (g) { return (g.region === rname || D.regOf[String(g.home)] === rname) && RNAMES[g.round] !== undefined && RNAMES[g.round] < 4; });
  function gameAt(rd, slot) {
    return games.filter(function (g) {
      if (RNAMES[g.round] !== rd) return false;
      var s = isNum(g.hseed) ? g.hseed : D.seedOf[String(g.home)];
      return isNum(s) && Math.floor(SLOT0[s] / Math.pow(2, rd)) === slot;
    })[0] || null;
  }
  function pR(t, rd) { var o = odds[String(t)]; return o && o.p_round && isNum(o.p_round[RKEYS[rd]]) ? o.p_round[RKEYS[rd]] : null; }
  /* projected: the likeliest team to reach round rd from the seeds feeding slot */
  function likely(rd, slot) {
    var cands = [];
    teams.forEach(function (x) { if (Math.floor(SLOT0[x.seed] / Math.pow(2, rd - 1)) === slot) cands.push(String(x.team)); });
    cands.sort(function (a, b) { return (pR(b, rd) || 0) - (pR(a, rd) || 0); });
    return cands[0] || null;
  }
  var cols = '';
  ['First round', 'Second round', 'Sweet 16', 'Elite 8'].forEach(function (lab, rd) {
    var n = 8 / Math.pow(2, rd);
    cols += '<div class="cc-bcol r' + rd + '"><div class="cc-bh">' + lab + '</div>';
    for (var k = 0; k < n; k++) {
      var g = gameAt(rd, k);
      if (g) {
        var w = CC.status(g) === 'final' ? String(g.hs > g.as ? g.home : g.away) : null;
        var sh = isNum(g.hseed) ? g.hseed : D.seedOf[String(g.home)], sa = isNum(g.aseed) ? g.aseed : D.seedOf[String(g.away)];
        var top = sh <= sa ? ['home', sh, 'hs'] : ['away', sa, 'as'], bot = sh <= sa ? ['away', sa, 'as'] : ['home', sh, 'hs'];
        var ex = function (sd) { var t = String(g[sd[0]]); return w ? String(g[sd[2]]) : (pR(t, rd + 1) !== null ? CC.pct(pR(t, rd + 1)) : ''); };
        cols += '<a class="cc-bg link" href="' + esc(CC.gameHref(L, g.id, S)) + '" aria-label="' + esc(CC.tname(L, g.home) + ' v ' + CC.tname(L, g.away)) + '">' +
          slotTeam(L, S, String(g[top[0]]), top[1], ex(top), w === String(g[top[0]]), w && w !== String(g[top[0]])).replace(/^<a /, '<span ').replace(/<\/a>$/, '</span>') +
          slotTeam(L, S, String(g[bot[0]]), bot[1], ex(bot), w === String(g[bot[0]]), w && w !== String(g[bot[0]])).replace(/^<a /, '<span ').replace(/<\/a>$/, '</span>') + '</a>';
      } else if (rd === 0) {
        var pp = R64_ORDER[k], a = bySeed[pp[0]] || [], b = bySeed[pp[1]] || [];
        var ta = a[0] || null, tb = b.length > 1 ? null : (b[0] || null);
        var bLab = b.length > 1 ? b.map(function (t) { return CC.tabbr(L, t); }).join('/') + ' (First Four)' : null;
        cols += '<div class="cc-bg">' + slotTeam(L, S, ta, pp[0], ta ? CC.pct(pR(ta, 1)) : '') + slotTeam(L, S, tb, pp[1], tb ? CC.pct(pR(tb, 1)) : bLab) + '</div>';
      } else {
        var t1 = D.actual ? null : likely(rd, 2 * k), t2 = D.actual ? null : likely(rd, 2 * k + 1);
        cols += '<div class="cc-bg' + (D.actual ? '' : ' proj') + '">' + slotTeam(L, S, t1, t1 ? D.seedOf[t1] : null, t1 ? CC.pct(pR(t1, rd + 1)) : '') + slotTeam(L, S, t2, t2 ? D.seedOf[t2] : null, t2 ? CC.pct(pR(t2, rd + 1)) : '') + '</div>';
      }
    }
    cols += '</div>';
  });
  return U.card(regionTitle(D, rname), D.actual ? 'Scores as played; tap a game for its page.' : 'Projected: first-round pairs from the projected seeds, later rounds show the likeliest team and its chance to advance.', '<div class="cc-bscroll" tabindex="0" role="region" aria-label="' + esc(rname) + ' region bracket"><div class="cc-bracket ncaa">' + cols + '</div></div>', { cls: 'cc-region' });
}
function finalFour(L, S, br, D) {
  var odds = br.odds || {};
  var ff = D.games.filter(function (g) { return g.round === 'Final Four'; }), fin = D.games.filter(function (g) { return g.round === 'National Championship'; })[0];
  var pairs = [];
  if (ff.length === 2) pairs = ff.map(function (g) { return [D.regOf[String(g.home)], D.regOf[String(g.away)]]; });
  else pairs = [[D.names[0], D.names[1]], [D.names[2], D.names[3]]];
  function best(rname, rk) {
    var c = (D.regs[rname] || []).map(function (x) { return String(x.team); });
    c.sort(function (a, b) { return ((odds[b] && odds[b].p_round && odds[b].p_round[rk]) || 0) - ((odds[a] && odds[a].p_round && odds[a].p_round[rk]) || 0); });
    return c[0] || null;
  }
  function gbox(g, a, b, lab, rk) {
    if (g) {
      var w = CC.status(g) === 'final' ? String(g.hs > g.as ? g.home : g.away) : null;
      return '<a class="cc-bg link" href="' + esc(CC.gameHref(L, g.id, S)) + '"><div class="cc-bg-l">' + esc(lab) + '</div>' + slotTeam(L, S, String(g.home), D.seedOf[String(g.home)], String(g.hs), w === String(g.home), w && w !== String(g.home)).replace(/^<a /, '<span ').replace(/<\/a>$/, '</span>') +
        slotTeam(L, S, String(g.away), D.seedOf[String(g.away)], String(g.as), w === String(g.away), w && w !== String(g.away)).replace(/^<a /, '<span ').replace(/<\/a>$/, '</span>') + '</a>';
    }
    var pr = function (t) { var o = odds[t]; return t && o && o.p_round && isNum(o.p_round[rk]) ? CC.pct(o.p_round[rk]) : ''; };
    return '<div class="cc-bg proj"><div class="cc-bg-l">' + esc(lab) + '</div>' + slotTeam(L, S, a, a ? D.seedOf[a] : null, pr(a)) + slotTeam(L, S, b, b ? D.seedOf[b] : null, pr(b)) + '</div>';
  }
  var semis = pairs.map(function (pp, i) { var g = ff.filter(function (x) { return D.regOf[String(x.home)] === pp[0] || D.regOf[String(x.away)] === pp[0]; })[0] || null; return gbox(g, best(pp[0], 'F4'), best(pp[1], 'F4'), (pp[0] || '?') + ' v ' + (pp[1] || '?'), 'Final'); }).join('');
  var champ = Object.keys(odds).sort(function (a, b) { return ((odds[b].p_round || {}).Champion || 0) - ((odds[a].p_round || {}).Champion || 0); });
  function bestSide(pp) {
    var a = best(pp[0], 'Final'), b = best(pp[1], 'Final');
    var pa = a && odds[a] && odds[a].p_round ? odds[a].p_round.Final || 0 : 0, pb = b && odds[b] && odds[b].p_round ? odds[b].p_round.Final || 0 : 0;
    return pa >= pb ? a : b;
  }
  var fbox = gbox(fin || null, D.actual ? null : bestSide(pairs[0]), D.actual ? null : bestSide(pairs[1]), 'National Championship', 'Champion');
  var w = fin && CC.status(fin) === 'final' ? String(fin.hs > fin.as ? fin.home : fin.away) : null;
  var crown = w ? '<div class="cc-champ">' + QK.teamMark(CC.team(L, w) || {}, 'lg') + '<div><div class="qk-kicker">Champion</div><b>' + esc(CC.tname(L, w)) + '</b></div></div>' :
    (champ[0] ? '<div class="cc-champ proj">' + QK.teamMark(CC.team(L, champ[0]) || {}, 'lg') + '<div><div class="qk-kicker">Title favourite</div><b>' + esc(CC.tname(L, champ[0])) + '</b> ' + CC.pct(odds[champ[0]].p_round.Champion) + '</div></div>' : '');
  return U.card('Final Four', '', '<div class="cc-ff"><div class="cc-bcol"><div class="cc-bh">Semifinals</div>' + semis + '</div><div class="cc-bcol"><div class="cc-bh">Final</div>' + fbox + crown + '</div></div>');
}

function bracket(node, L, S, season, br) {
  if (!CC.ok(br)) { node.innerHTML = U.missing('The bracket', br); return; }
  var D = regionData(L, S, br);
  var html = '';
  var fmt0 = br.format || {};
  if (D.names.length) {
    if (br.projected && br.projected.note) html += '<p class="cc-note">' + esc(br.projected.note) + '</p>';
    html += '<p class="cc-note">' + (D.actual ? 'The field of ' + (br.field || 68) + ' as seeded. ' : 'Projected field of ' + (br.field || 68) + ' from simulated seasons; ') + (fmt0.verified === false ? 'format assumed as last season. ' : '') +
      'Percentages are our chance for the team to reach the next round' + (D.actual ? ' (pre-tournament)' : '') + '. On a phone each region scrolls sideways inside its card.</p>';
    html += '<div class="cc-regions">' + D.names.map(function (r) { return regionHTML(L, S, br, D, r); }).join('') + '</div>' + finalFour(L, S, br, D);
  } else html += QK.empty('No bracket yet', 'The projected field appears once the season simulation has run.');
  // first four
  var ffl = (D.actual && D.actual.first_four) || [];
  var pff = (br.projected && br.projected.first_four) || [];
  if (ffl.length || pff.length) {
    html += U.card('First Four', '', ffl.length ? '<div class="cc-games">' + ffl.map(function (x) {
      if (Array.isArray(x)) x = { teams: x.slice(0, 2).map(String) };
      var g = D.games.filter(function (c) { return x.gid ? String(c.id) === String(x.gid) : (c.round === 'First Four' && (x.teams || []).indexOf(String(c.home)) >= 0 && (x.teams || []).indexOf(String(c.away)) >= 0); })[0];
      return g ? CC.card(g, L) : '<div class="qk-card cc-pad">' + (x.teams || []).map(function (t) { return U.teamEnt(L, t, { season: S }); }).join(' v ') + '</div>';
    }).join('') + '</div>' : '<ul class="cc-list">' + pff.map(function (pp) { return '<li>' + U.teamEnt(L, pp[0], { season: S }) + '<span class="s">v</span>' + U.teamEnt(L, pp[1], { season: S }) + '</li>'; }).join('') + '</ul>');
  }
  // heat table
  var odds = br.odds || {};
  var ts = Object.keys(odds).filter(function (t) { return odds[t].p_round; }).sort(function (a, b) { return (odds[b].p_round.Champion || 0) - (odds[a].p_round.Champion || 0) || (odds[b].p_round.S16 || 0) - (odds[a].p_round.S16 || 0); });
  var rounds = (br.rounds || RKEYS).filter(function (r) { return r !== 'R64' || !D.actual; });
  var heat = U.table(['Team', { label: 'Seed', align: 'right' }, 'Region'].concat(rounds.map(function (r) { return { label: r === 'Champion' ? 'Title' : r, align: 'right' }; })), ts.slice(0, 68).map(function (t) {
    var o = odds[t];
    return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, isNum(o.seed) ? o.seed : (D.seedOf[t] || '—'), esc(o.region || D.regOf[t] || '—')].concat(rounds.map(function (r) { return U.heat(o.p_round[r]); }));
  }), { maxHeight: 640 });
  var ups = (br.upsets || []).slice().sort(function (a, b) { return (b.p_upset || 0) - (a.p_upset || 0); });
  var upT = ups.length ? U.table(['Matchup', { label: 'Upset', align: 'right', title: 'Our chance the lower seed wins' }], ups.slice(0, 32).map(function (u) {
    return [{ html: '<span class="cc-ups">(' + u.seed_dog + ') ' + U.teamEnt(L, u.dog, { season: S, abbr: true }) + ' <span class="qk-muted">over</span> (' + u.seed_fav + ') ' + U.teamEnt(L, u.fav, { season: S, abbr: true }) + '</span>', v: u.seed_dog }, U.heat(u.p_upset)];
  }), { maxHeight: 560 }) : QK.empty('No first-round games yet', 'Upset chances appear once the first round is set.');
  html += '<div class="qk-grid cc-grid"><div class="qk-span-8">' + U.card('Chance to reach each round', (D.actual ? 'Our pre-tournament chances. ' : 'Our chances. ') + 'Darker blue is likelier.', heat) + '</div><div class="qk-span-4">' + U.card('First-round upset chances', 'Our chance the lower seed wins.', upT) + '</div></div>';
  // bracketology
  var bo = (br.bracketology || []).slice().sort(function (x, y) { return (isNum(x.seed_mean) ? x.seed_mean : 99) - (isNum(y.seed_mean) ? y.seed_mean : 99) || (y.p_ncaa || 0) - (x.p_ncaa || 0); });
  if (bo.length) {
    var sf = br.selection_fit || {};
    var li = (br.projected && br.projected.last_in) || [], fo = (br.projected && br.projected.first_out) || [];
    html += '<div class="qk-grid cc-grid"><div class="qk-span-8">' + U.card('Bracketology', 'Projected seeds and our selection chances' + (sf.n_seasons ? ' (selection model fitted on ' + sf.n_seasons + ' past fields; out of sample ' + CC.pct(sf.at_large_acc, 0) + ' of at-large picks right, seeds off by ' + CC.f(sf.seed_mae, 2) + ' on average)' : '') + '.',
      U.table(['Team', 'Conf.', { label: 'Rec.', align: 'right' }, { label: 'Seed', align: 'right' }, { label: 'Mode', align: 'right' }, { label: 'In field', align: 'right' }, { label: 'Auto', align: 'right' }, { label: 'At-large', align: 'right' }, { label: 'Rk', align: 'right' }], bo.map(function (r) {
        return [{ html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, esc(CC.cname(L, r.conf)), r.record || '—', { v: r.seed_mean, html: CC.f(r.seed_mean, 1) }, isNum(r.seed_mode) ? r.seed_mode : '—', U.heat(r.p_ncaa), U.heat(r.p_auto), U.heat(r.p_at_large), isNum(r.rating_rank) ? r.rating_rank : '—'];
      }), { maxHeight: 620 })) + '</div><div class="qk-span-4">' +
      U.card('The bubble', 'Last teams in and first out of the projected field.', '<div class="cc-mini-h">Last in</div><ul class="cc-list">' + li.map(function (t) { return '<li>' + U.teamEnt(L, t, { season: S }) + '</li>'; }).join('') + '</ul><div class="cc-mini-h">First out</div><ul class="cc-list">' + fo.map(function (t) { return '<li>' + U.teamEnt(L, t, { season: S }) + '</li>'; }).join('') + '</ul>') + '</div></div>';
  }
  node.innerHTML = html;
}

/* Conference tournaments (round 9, rebuilt from a wall of tables): the headline numbers, the favourite of every
   tournament as one chart, then each conference's chances folded (the power conferences open). */
function conftourneys(node, L, S, season, br) {
  if (!CC.ok(br)) { node.innerHTML = U.missing('Conference tournaments', br); return; }
  var ct = br.conf_tourneys || {};
  var pw = POWER[L] || [];
  var cs = Object.keys(ct).sort(function (a, b) {
    var ia = pw.indexOf(CC.cname(L, a)), ib = pw.indexOf(CC.cname(L, b));
    if (ia < 0) ia = 99; if (ib < 0) ib = 99;
    return ia - ib || CC.cname(L, a).localeCompare(CC.cname(L, b));
  });
  if (!cs.length) { node.innerHTML = QK.empty('No conference tournaments yet', ''); return; }
  var info = cs.map(function (c) {
    var x = ct[c], rows = (x.teams || []).slice().sort(function (a, b) { return (b.p_win || 0) - (a.p_win || 0); });
    var fin = (x.games || []).filter(function (g) { return /final/i.test(String(g.round || '')) && !/semi|quarter/i.test(String(g.round || '')) && CC.status(g) === 'final'; })[0];
    return { c: c, x: x, rows: rows, champ: fin ? String(fin.hs > fin.as ? fin.home : fin.away) : null };
  });
  var open = info.filter(function (i) { return !i.champ && i.rows.length; });
  var surest = open.slice().sort(function (a, b) { return (b.rows[0].p_win || 0) - (a.rows[0].p_win || 0); })[0];
  var widest = open.slice().sort(function (a, b) { return (a.rows[0].p_win || 0) - (b.rows[0].p_win || 0); })[0];
  var html = U.stats([{ label: 'Tournaments', value: String(cs.length), sub: info.filter(function (i) { return i.champ; }).length + ' decided' },
    surest ? { label: 'Surest favourite', value: CC.tabbr(L, surest.rows[0].team) + ' ' + CC.pct(surest.rows[0].p_win), signal: true, href: CC.teamHref(L, surest.rows[0].team, S), sub: CC.tname(L, surest.rows[0].team) + ' in the ' + CC.cname(L, surest.c) } : null,
    widest ? { label: 'Most open', value: CC.cname(L, widest.c), text: true, sub: 'the favourite, ' + CC.tshort(L, widest.rows[0].team) + ', wins it in only ' + CC.pct(widest.rows[0].p_win) + ' of our simulations' } : null]);
  var fav = info.filter(function (i) { return i.rows.length; });
  html += U.card('Every tournament’s favourite', 'Our chance the favourite wins its conference tournament (and with it the automatic bid); a decided tournament shows its champion at 100%.', U.chart('ct-fav', Math.max(320, fav.length * 22 + 50), 'Each conference tournament favourite'));
  html += QK.explain('Formats vary by conference and are not in any free feed: until a bracket is published, each tournament is simulated as single elimination seeded by conference record, with byes to the bracket size (marked approximate).');
  html += U.section('Conference by conference', 'Each tournament’s chances; the power conferences are open.', '<div class="cc-mvt">' + info.map(function (i) {
    var lead = i.champ ? 'won by ' + CC.tshort(L, i.champ) : i.rows[0] ? CC.tshort(L, i.rows[0].team) + ' ' + CC.pct(i.rows[0].p_win) : '';
    return '<details class="cc-mvt-t"' + (pw.indexOf(CC.cname(L, i.c)) >= 0 ? ' open' : '') + '><summary><span class="cc-mvt-c">' + esc(CC.cname(L, i.c)) + '</span><span class="cc-mvt-n">' + (i.x.approximate ? 'approximate format' : 'published bracket') + '</span><b class="cc-mvt-l">' + esc(lead) + '</b></summary><div class="cc-mvt-b">' +
      U.table([{ label: 'Seed', align: 'right' }, 'Team', { label: 'Wins it', align: 'right' }, ''], i.rows.slice(0, 16).map(function (r) {
        return [isNum(r.seed) ? r.seed : '—', { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.p_win, html: CC.pct(r.p_win) }, { html: U.bar(r.p_win), v: r.p_win }];
      }), { sticky: false }) + '</div></details>';
  }).join('') + '</div>', '', 'Automatic bids');
  node.innerHTML = html;
  if (fav.length) QKC.bar('#ct-fav', { cats: fav.map(function (i) { return CC.cname(L, i.c) + ' · ' + CC.tabbr(L, i.champ || i.rows[0].team); }), horizontal: true, labels: true, fmt: function (v) { return CC.pct(v); },
    series: [{ name: 'Wins the tournament', data: fav.map(function (i) { return i.champ ? 1 : (i.rows[0].p_win || 0); }) }], colors: fav.map(function (i) { return CC.tcol(L, i.champ || i.rows[0].team); }), labelWidth: 150, valName: 'Our chance the favourite wins it', catName: 'Conference · favourite', max: 1 });
}

/* shared with the overview's past-season recap (round 9) */
CC.cfpBracket = cfpBracket;
CC.ncaaFinalFour = function (L, S, br) { var D = regionData(L, S, br); return D.names.length ? finalFour(L, S, br, D) : ''; };

})(window.CC);
