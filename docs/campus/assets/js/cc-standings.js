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
  var L = p.L, S = p.S, fb = CC.fb(L);
  var cur = CC.isCur(L, S);
  var list = fb ? [['conferences', 'Conferences'], ['cards', 'Team cards'], ['polls', 'Polls'], ['playoff', 'Playoff'], ['bowls', 'Bowls']] : [['conferences', 'Conferences'], ['cards', 'Team cards'], ['polls', 'Polls'], ['bracket', 'Bracket'], ['conftourneys', 'Conference tournaments']];
  if (cur) list.unshift(['race', 'The race']);
  var tab = U.tab(p, list.map(function (x) { return x[0]; }), list[0][0]);
  var sub = { race: 'How the race is shaping up: our chances over time, who moved and why, what is at stake next, the road left and the tiers.', cards: 'Every team’s strengths and weaknesses against the rest of the country, and the shape of the league.',
    conferences: 'Conference and overall records with our rating and the chance to win the conference.', polls: 'The voters next to the model.', playoff: 'The 12-team College Football Playoff: the bracket, everyone’s chance to reach each round, and how the committee may rank them.',
    bowls: 'Who reaches six wins, and the bowl games announced so far.', bracket: 'The NCAA tournament: the bracket by region, each team’s chance to reach each round, and our first-round upset chances.', conftourneys: 'Our chance to win each conference tournament (formats approximated where no bracket is published).' }[tab];
  el.innerHTML = U.head('Standings', sub, U.kicker(L, S)) + U.tabs(L, 'standings', list, S, tab) + chanceNote(L, S, tab) + '<div id="st-body">' + QK.skeleton('lines', 6) + '</div><div id="st-perf"></div>';
  var body = QK.$('#st-body', el);
  var none = Promise.resolve(null);
  return Promise.all([CC.season(L, S), (tab === 'playoff' || tab === 'bowls' || tab === 'bracket' || tab === 'conftourneys' || tab === 'race') ? CC.load(CC.path(L, S, fb ? 'cfp.json' : 'bracket.json')) : none,
    tab === 'race' ? CC.load(CC.lpath(L, 'race_log.json')) : none, tab === 'race' ? CC.load(CC.path(L, S, 'schedule.json')) : none,
    tab === 'cards' ? CC.load(CC.path(L, S, 'teams.json')) : none]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[0]) ? a[0] : null;
    if (!season) { body.innerHTML = U.missing('Standings', a[0]); return; }
    if (tab === 'race') CC.raceTab(body, L, S, season, { post: CC.ok(a[1]) ? a[1] : null, log: a[2], sched: CC.ok(a[3]) ? a[3] : null });
    else if (tab === 'cards') CC.cardsTab(body, L, S, season, a[4], p.query || {});
    else if (tab === 'conferences') conferences(body, L, S, season);
    else if (tab === 'polls') polls(body, L, S, season);
    else if (tab === 'playoff') playoff(body, L, S, season, a[1]);
    else if (tab === 'bowls') bowls(body, L, S, season, a[1]);
    else if (tab === 'bracket') bracket(body, L, S, season, a[1]);
    else conftourneys(body, L, S, season, a[1]);
    U.wire(body);
    if ((tab === 'race' || tab === 'conferences') && window.QKL && QKL.leaders) performers(QK.$('#st-perf', el), L, S);
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

/* Top and bottom performers (QKL.leaders) under the race and the conferences: all players on our value model (box
   rating first in basketball), each position on its spec headline set, and the teams on our ratings, from
   <L>/<S>/performers.json (oddsmarkets/college/performers.py, 20-40 KB: qualified players only). */
function performers(host, L, S) {
  if (!host) return;
  var fb = CC.fb(L);
  CC.load(CC.path(L, S, 'performers.json')).then(function (pf) {
    if (!U.alive(host)) return;
    QKL.leaders(host, { data: CC.ok(pf) ? pf : { views: [] }, title: fb ? 'Who leads FBS, and who is struggling' : 'Who leads Division I, and who is struggling',
      sub: 'The top five and the bottom five on each key number: every player on our ' + (fb ? 'value model' : 'box rating and value model') + ', then each position on the numbers that matter for it, and the teams. Qualified players only; each name opens the player page.',
      team: function (t) { var x = CC.team(L, t) || {}; return { abbr: CC.tabbr(L, t), name: x.name || CC.tname(L, t), colour: x.colour, href: CC.teamHref(L, t, S) }; },
      href: function (id) { return CC.playerHref(L, id, S); },
      note: fb ? 'Defensive numbers are per game from the box score; value for defenders and specialists counts box-score points, so it is a floor.' : 'In basketball the boards use the per-game box score (points, rebounds, assists, steals, blocks, turnovers) beside our box rating.',
      empty: 'The boards fill once players reach the qualifying minimums.' });
  });
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
    return '<div class="cc-conf" data-conf="' + esc(c) + '">' + U.card(CC.conf(L, c) ? (CC.conf(L, c).name || CC.cname(L, c)) : CC.cname(L, c), rows.length + ' teams' + (hasDiv ? ' · divisions' : '') + (cur ? ' · the bar is our chance to win the ' + (fb ? 'conference' : 'regular-season title') : '') + ' · ' + U.link(CC.href(L, 'standings', null, S, 'tab=cards&conf=' + encodeURIComponent(c)), 'Team cards'), U.lb('cf-' + k), { flush: true }) + '</div>';
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
  cards.push(U.card('Our power ranking', CC.fb(L) ? 'Points v an average FBS team' : 'Adjusted margin per 100 possessions', U.table([{ label: '#', align: 'right' }, 'Team', { label: 'Rating', align: 'right' }, { label: 'Prev', align: 'right' }, { label: 'Rec.', align: 'right' }], power.slice(0, 25).map(function (r) {
    return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.rating, html: CC.signed(r.rating, 1) }, isNum(r.prev_rank) ? r.prev_rank : '—', rec[String(r.team)] || '—']; }), { maxHeight: 640 })));
  node.innerHTML = '<div class="cc-polls">' + cards.join('') + '</div>';
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

function conftourneys(node, L, S, season, br) {
  if (!CC.ok(br)) { node.innerHTML = U.missing('Conference tournaments', br); return; }
  var ct = br.conf_tourneys || {};
  var cs = Object.keys(ct).sort(function (a, b) {
    var pw = POWER[L] || [], ia = pw.indexOf(CC.cname(L, a)), ib = pw.indexOf(CC.cname(L, b));
    if (ia < 0) ia = 99; if (ib < 0) ib = 99;
    return ia - ib || CC.cname(L, a).localeCompare(CC.cname(L, b));
  });
  if (!cs.length) { node.innerHTML = QK.empty('No conference tournaments yet', ''); return; }
  node.innerHTML = '<p class="cc-note">Formats vary by conference and are not in any free feed: until a bracket is published, each tournament is simulated as single elimination seeded by conference record, with byes to the bracket size (marked approximate).</p><div class="cc-auto">' + cs.map(function (c) {
    var x = ct[c], rows = (x.teams || []).slice().sort(function (a, b) { return (b.p_win || 0) - (a.p_win || 0); });
    var fin = (x.games || []).filter(function (g) { return /final/i.test(String(g.round || '')) && !/semi|quarter/i.test(String(g.round || '')) && CC.status(g) === 'final'; })[0];
    var champ = fin ? String(fin.hs > fin.as ? fin.home : fin.away) : null;
    return U.card(CC.cname(L, c), (x.approximate ? 'approximate format' : 'published bracket') + (champ ? ' · won by ' + esc(CC.tshort(L, champ)) : ''), U.table([{ label: 'Seed', align: 'right' }, 'Team', { label: 'Wins it', align: 'right' }, ''], rows.slice(0, 16).map(function (r) {
      return [isNum(r.seed) ? r.seed : '—', { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.p_win, html: CC.pct(r.p_win) }, { html: U.bar(r.p_win), v: r.p_win }];
    }), { sticky: false, maxHeight: 420 }));
  }).join('') + '</div>';
}

})(window.CC);
