/* The Quant Campus — college hockey (men's `mch`, women's `wch`; 30 Oct 2026). The hockey pages that differ from
 * basketball: Standings (Table · Chances · Bracket · NPI / PairWise · Polls · History · Races), the game centre's
 * box score (scoring, penalties, goalies, skaters, shots by period, College Hockey News's shot attempts and xG), the
 * Model page (How it works, How we're doing with the NPI / PairWise validation, Glossary, Terms) and the vocabulary
 * the shared pages read (CC.hk, CC.HKV). Payloads: oddsmarkets/college/hockey/build.py.
 * College Hockey News (collegehockeynews.com) is the source of every box score and player line: credited on every
 * hockey page (CC.hkCredit). Older-browser rule: no optional chaining, no nullish coalescing. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

CC.hk = function (L) { return L === 'mch' || L === 'wch'; };
/* hockey words for the shared pages */
CC.HKV = {
  rating: 'goals a game v an average D-I team', ratingShort: 'goals v average', unit: 'goals', peers: 'Division I teams',
  pos: { F: 'Forward', D: 'Defenceman', G: 'Goalie' }, posPl: { F: 'Forwards', D: 'Defence', G: 'Goalies' }
};
CC.hkCredit = function (short) {
  return '<p class="cc-note cc-hk-credit">' + (short ? 'Box scores and player numbers: <a href="https://www.collegehockeynews.com" target="_blank" rel="noopener">College Hockey News</a>.' :
    'Box scores, player and team statistics, rosters and College Hockey News’s own xG come from <a href="https://www.collegehockeynews.com" target="_blank" rel="noopener">College Hockey News</a> (collegehockeynews.com), credited with thanks; the weekly polls from <a href="https://www.uscho.com" target="_blank" rel="noopener">USCHO</a>; results and schedules also from ESPN. We publish derived numbers and our own models, never their pages.') + '</p>';
};
CC.recW = function (r) { return r ? (r.w || 0) + '–' + (r.l || 0) + '–' + (r.t || 0) : '—'; };

/* ── standings ───────────────────────────────────────────────────────── */
var TABS = [['table', 'Table'], ['chances', 'Chances'], ['bracket', 'Bracket'], ['selection', 'NPI'], ['polls', 'Polls'], ['history', 'History'], ['races', 'Races']];
CC.hkStandings = function (el, p) {
  var L = p.L, S = p.S, cur = CC.isCur(L, S);
  var list = TABS.map(function (x) { return x[0] === 'selection' ? ['selection', Number(S) >= 2026 ? 'NPI' : 'PairWise'] : x; });
  var tab = U.tab(p, list.map(function (x) { return x[0]; }), 'table');
  var sub = { table: 'Every conference: points, record, goals, our rating and, this season, our chance to win the regular-season title.',
    chances: 'Our chances from simulated seasons: the NCAA field, the Frozen Four, the national title and each conference’s titles.',
    bracket: Number(S) >= 2027 || cur ? 'The NCAA tournament: the projected field and every team’s chance to reach each round.' : 'The NCAA tournament as it was played, with our chances before it started.',
    selection: Number(S) >= 2026 ? 'The NPI decides the NCAA field. Ours is computed from the results and matches the published one.' : 'The PairWise decided the field to 2024-25: our replica from the results, against the published table.',
    polls: 'The USCHO poll next to our power ranking.', history: 'Every national champion in our data, the Frozen Fours, the programmes that won most and our calls against what happened.',
    races: 'The race for the best player, by our value model (goals above replacement).' }[tab];
  el.innerHTML = U.head('Standings', sub, U.kicker(L, S)) + U.tabs(L, 'standings', list, S, tab) + '<div id="st-body">' + QK.skeleton('lines', 6) + '</div>' + CC.hkCredit(true);
  var body = QK.$('#st-body', el);
  var none = Promise.resolve(null);
  return Promise.all([CC.season(L, S), (tab === 'bracket' || tab === 'chances' || tab === 'selection') ? CC.load(CC.path(L, S, 'bracket.json')) : none,
    tab === 'history' ? CC.load(CC.lpath(L, 'history.json')) : tab === 'races' ? CC.load(CC.path(L, S, 'value.json')) : none]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[0]) ? a[0] : null;
    if (!season) { body.innerHTML = U.missing('Standings', a[0]); return; }
    var br = CC.ok(a[1]) ? a[1] : null;
    if (tab === 'table') hkTable(body, L, S, season);
    else if (tab === 'chances') hkChances(body, L, S, season, br);
    else if (tab === 'bracket') hkBracket(body, L, S, season, br);
    else if (tab === 'selection') hkSelection(body, L, S, season, br);
    else if (tab === 'polls') hkPolls(body, L, S, season);
    else if (tab === 'history') hkHistory(body, L, S, a[2]);
    else hkRaces(body, L, S, season, a[2]);
    U.wire(body);
  });
};

function confOrder(L, season) {
  return Object.keys(season.standings || {}).sort(function (a, b) {
    if (a === 'ind') return 1; if (b === 'ind') return -1;
    return CC.cname(L, a).localeCompare(CC.cname(L, b));
  });
}
function hkTable(node, L, S, season) {
  var sim = (season.sim && season.sim.teams) || {}, R = season.ratings || {}, cur = CC.isCur(L, S);
  var cs = confOrder(L, season);
  var chips = '<div class="qk-chips scroll cc-filters" id="cf-chips" role="group" aria-label="Conference">' + ['all'].concat(cs).map(function (c, i) {
    return '<button type="button" class="qk-chip" style="--ca:var(--signal)" data-value="' + esc(c) + '" aria-pressed="' + (i === 0) + '">' + esc(c === 'all' ? 'All' : CC.cname(L, c)) + '</button>'; }).join('') + '</div>';
  var pts3 = Number(S) >= 2022;
  node.innerHTML = QK.note('<b>Conference points:</b> ' + (pts3 ? '3 for a regulation win, 2 for an overtime or shootout win, 1 for an overtime or shootout loss (a shootout decides the extra point; the NCAA record keeps it a tie).' : '2 for a win, 1 for a tie.') + ' Ranked by points a game. Overall records are W–L–T.') +
    chips + '<div class="cc-confs">' + cs.map(function (c, k) {
      var rows = season.standings[c] || [];
      return '<div class="cc-conf" data-conf="' + esc(c) + '">' + U.card(c === 'ind' ? 'Independents' : ((CC.conf(L, c) || {}).name || CC.cname(L, c)), rows.length + ' teams' + (cur && c !== 'ind' ? ' · the bar is our chance to win the regular-season title' : '') + ' · ' + U.link(CC.href(L, 'teams', null, S, 'scope=' + encodeURIComponent(c)), 'Team profiles'), U.lb('cf-' + k), { flush: true }) + '</div>';
    }).join('') + '</div>';
  cs.forEach(function (c, k) {
    var rows = (season.standings[c] || []).map(function (r) {
      var t = String(r.team), rt = R[t] || {}, s0 = sim[t] || {};
      return { team: t, name: CC.tshort(L, t), sub: isNum(r.rank) ? 'USCHO #' + r.rank : '', conf_rank: r.conf_rank, cpts: r.conf_pts, cgp: r.conf_gp,
        crec: CC.recW({ w: r.conf_w, l: r.conf_l, t: r.conf_t }), rec: CC.recW(r), gd: (r.gf || 0) - (r.ga || 0), goals: (r.gf || 0) + '–' + (r.ga || 0),
        rating: rt.rating, rating_rank: r.rating_rank, streak: r.streak || '—', pc: s0.p_conf_reg };
    });
    var cols = [{ key: 'conf_rank', label: '#', num: true },
      { key: 'name', label: 'Team', type: 'entity', sub: 'sub', mark: function (r) { return U.mark(L, r.team); }, href: function (r) { return CC.teamHref(L, r.team, S); } }];
    if (c !== 'ind') cols.push({ key: 'cpts', label: 'Pts', num: true, tip: 'Conference points' }, { key: 'cgp', label: 'GP', num: true, tip: 'Conference games' }, { key: 'crec', label: 'Conf', tip: 'Conference W–L–T' });
    cols.push({ key: 'rec', label: 'Overall', tip: 'Overall W–L–T (NCAA record: shootouts are ties)' }, { key: 'gd', label: 'GD', num: true, fmt: function (v, r) { return '<span title="' + esc(r.goals) + '">' + CC.signed(v, 0) + '</span>'; }, tip: 'Goal difference' },
      { key: 'rating', label: 'Rating', num: true, fmt: function (v) { return CC.signed(v, 2); }, tip: 'Our rating: goals a game better than an average Division I team on neutral ice' },
      { key: 'rating_rank', label: 'Rk', num: true, tip: 'Our national rank' }, { key: 'streak', label: 'Strk' });
    if (cur && c !== 'ind' && rows.some(function (r) { return isNum(r.pc); })) cols.push({ key: 'pc', label: 'Reg. title', type: 'bar', max: 1, fmt: function (v) { return CC.pct(v); }, tip: 'Our chance to win the conference regular season' });
    QK.leaderboard(QK.$('#cf-' + k, node), { dense: true, columns: cols, rows: rows, rowHref: function (r) { return CC.teamHref(L, r.team, S); } });
  });
  QK.chips(QK.$('#cf-chips', node), function (v) {
    var c = v[0] || 'all';
    QK.$$('.cc-conf', node).forEach(function (x) { x.hidden = c !== 'all' && x.getAttribute('data-conf') !== c; });
  });
}

function hkChances(node, L, S, season, br) {
  var sim = (season.sim && season.sim.teams) || {};
  var ts = Object.keys(sim).filter(function (t) { return (sim[t].p_ncaa || 0) > 0.004 || (sim[t].p_title || 0) > 0; });
  if (!ts.length) { node.innerHTML = QK.empty('No simulation for this season', (season.sim && season.sim.notes || []).join(' ') || 'Chances appear once the season simulation has run.'); return; }
  var fin = season.sim && season.sim.kind === 'final';
  ts.sort(function (a, b) { return (sim[b].p_title || 0) - (sim[a].p_title || 0) || (sim[b].p_ncaa || 0) - (sim[a].p_ncaa || 0); });
  var top = ts.slice(0, 8);
  var nS = season.sim && season.sim.n_sims ? QK.fmt.num(season.sim.n_sims) : 'thousands of';
  var html = QK.note('<b>How to read the chances:</b> each is the share of our ' + nS + ' simulated seasons in which it happens. A 30% chance of the NCAA field still comes off about one season in three.' + (fin ? ' This season is over: the field and results are real, and the tournament chances are ours from before it started.' : ''));
  html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + U.card(fin ? 'Title chances before the tournament' : 'Title chances', 'The national title, from simulated seasons.', QK.chances(top.map(function (t) { return { label: CC.tshort(L, t), p: sim[t].p_title || 0, href: CC.teamHref(L, t, S), color: CC.traw(L, t), mark: U.mark(L, t) }; }), { key: false })) + '</div>';
  var heat = U.table(['Team', { label: 'Field', align: 'right' }, { label: 'Auto bid', align: 'right' }, { label: L === 'mch' ? 'Regional final' : 'Quarterfinal', align: 'right' }, { label: 'Frozen Four', align: 'right' }, { label: 'Final', align: 'right' }, { label: 'Title', align: 'right' }, { label: 'Avg seed', align: 'right' }],
    ts.slice(0, 30).map(function (t) { var o = sim[t]; return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, U.heat(o.p_ncaa), U.heat(o.p_auto || (o.p_conf_tourney && o.p_ncaa ? o.p_conf_tourney : null)), U.heat(o.p_qf), U.heat(o.p_f4), U.heat(o.p_final), U.heat(o.p_title), isNum(o.seed_mean) ? CC.f(o.seed_mean, 1) : '—']; }), { maxHeight: 620 });
  html += '<div class="qk-span-7">' + U.card('Chance to reach each stage', 'Darker blue is likelier.', heat) + '</div></div>';
  // conference titles
  var cs = confOrder(L, season).filter(function (c) { return c !== 'ind'; });
  html += U.section('Conference titles', 'Our chance to win each conference’s regular season and its tournament (the tournament carries the automatic NCAA bid; formats approximated: every member, single elimination).', '<div class="cc-auto">' + cs.map(function (c) {
    var rows = (season.standings[c] || []).map(function (r) { return String(r.team); }).filter(function (t) { return sim[t]; }).sort(function (a, b) { return (sim[b].p_conf_tourney || 0) - (sim[a].p_conf_tourney || 0); }).slice(0, 6);
    return U.card(CC.cname(L, c), '', U.table(['Team', { label: 'Reg. season', align: 'right' }, { label: 'Tournament', align: 'right' }], rows.map(function (t) { return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, U.heat(sim[t].p_conf_reg), U.heat(sim[t].p_conf_tourney)]; }), { sticky: false }));
  }).join('') + '</div>', '', 'Conferences');
  if ((season.sim.notes || []).length) html += U.note(esc(season.sim.notes.join(' ')));
  node.innerHTML = html;
}

/* the NCAA bracket: men four regionals of four and the Frozen Four; women 6v11 / 7v10 / 8v9, quarterfinals, Frozen Four */
function slot(L, S, tid, seed, extra, win, lose) {
  if (!tid) return '<div class="cc-bt empty"><span class="sd">' + (isNum(seed) ? seed : '') + '</span><span class="nm">' + esc(extra || 'TBD') + '</span></div>';
  var t = CC.team(L, tid) || { name: 'Team ' + tid };
  return '<span class="cc-bt' + (win ? ' win' : '') + (lose ? ' lose' : '') + '" style="--tc:' + esc(QK.color.parse(t.colour) ? QK.color.team(t.colour) : 'var(--c-other)') + '"><span class="sd">' + (isNum(seed) ? seed : '') + '</span><span class="nm">' + esc(t.short || t.name) + '</span><span class="pr">' + (extra || '') + '</span></span>';
}
function gameBox(L, S, g, seedOf, label) {
  var fin = g && g.status === 'post' && isNum(g.hs) && isNum(g.as);
  var w = fin ? String(g.hs > g.as ? g.home : g.away) : null;
  var a = String(g.away), h = String(g.home);
  var ex = function (t, sc) { return fin ? String(sc) + (g.ot ? (t === w ? ' OT' : '') : '') : ''; };
  return '<a class="cc-bg link" href="' + esc(CC.gameHref(L, g.id, S)) + '">' + (label ? '<div class="cc-bg-l">' + esc(label) + '</div>' : '') +
    slot(L, S, a, seedOf[a], ex(a, g.as), w === a, w && w !== a) + slot(L, S, h, seedOf[h], ex(h, g.hs), w === h, w && w !== h) + '</a>';
}
function projBox(L, S, a, b, seedOf, pa, pb, label) {
  return '<div class="cc-bg proj">' + (label ? '<div class="cc-bg-l">' + esc(label) + '</div>' : '') + slot(L, S, a, seedOf[a], isNum(pa) ? CC.pct(pa) : '') + slot(L, S, b, seedOf[b], isNum(pb) ? CC.pct(pb) : '') + '</div>';
}
function hkBracket(node, L, S, season, br) {
  if (!br) { node.innerHTML = U.missing('The bracket', br); return; }
  var odds = br.odds || {}, act = br.actual, html = '', seedOf = {};
  var pr = function (t, k) { var o = odds[t]; return o && o.p_round && isNum(o.p_round[k]) ? o.p_round[k] : null; };
  var fmt = br.format || {};
  html += '<p class="cc-note">' + esc(fmt.rule || '') + (fmt.verified === false ? ' (format assumed: not yet confirmed for this season)' : '') + '.</p>';
  if (act && act.champion) html += '<div class="cc-champ big">' + QK.teamMark(U.mark(L, act.champion), 'lg') + '<div><div class="qk-kicker">National champions · ' + esc(CC.seasonLabel(L, S)) + '</div><b>' + esc(CC.tname(L, act.champion)) + '</b>' +
    (act.runner_up ? ' <span class="qk-muted">beat ' + esc(CC.tname(L, act.runner_up)) + ' in the final</span>' : '') + '</div></div>';
  if (L === 'mch') {
    var regs = act && act.regions && Object.keys(act.regions).length ? act.regions : (br.projected && br.projected.regions) || {};
    var names = Object.keys(regs);
    names.forEach(function (n) { (regs[n] || []).forEach(function (x) { seedOf[String(x.team)] = x.seed; }); });
    if (!names.length) html += QK.empty('No bracket yet', 'The projected field appears once the season simulation has run.');
    else {
      var games = (act && act.games) || [];
      var regOf = {}; names.forEach(function (n) { (regs[n] || []).forEach(function (x) { regOf[String(x.team)] = n; }); });
      html += '<div class="cc-regions hk">' + names.map(function (n) {
        var r = {}; (regs[n] || []).forEach(function (x) { r[x.seed] = String(x.team); });
        var gs = games.filter(function (g) { return regOf[String(g.home)] === n && regOf[String(g.away)] === n; });
        var semi = gs.filter(function (g) { return (g.round || '') === 'Regional semifinal'; }), fin = gs.filter(function (g) { return (g.round || '') === 'Regional final'; })[0];
        var col1 = '<div class="cc-bcol"><div class="cc-bh">Regional semifinals</div>', col2 = '<div class="cc-bcol"><div class="cc-bh">Regional final</div>';
        [[1, 4], [2, 3]].forEach(function (pp) {
          var g = semi.filter(function (x) { return [String(x.home), String(x.away)].indexOf(r[pp[0]]) >= 0; })[0];
          col1 += g ? gameBox(L, S, g, seedOf, pp[0] + ' v ' + pp[1]) : projBox(L, S, r[pp[0]], r[pp[1]], seedOf, pr(r[pp[0]], 'QF'), pr(r[pp[1]], 'QF'), pp[0] + ' v ' + pp[1]);
        });
        if (fin) col2 += gameBox(L, S, fin, seedOf, '');
        else {
          var cands = [r[1], r[4]].sort(function (a, b) { return (pr(b, 'F4') || 0) - (pr(a, 'F4') || 0); }), c2 = [r[2], r[3]].sort(function (a, b) { return (pr(b, 'F4') || 0) - (pr(a, 'F4') || 0); });
          col2 += projBox(L, S, cands[0], c2[0], seedOf, pr(cands[0], 'F4'), pr(c2[0], 'F4'), act ? '' : 'likeliest');
        }
        return U.card(n.indexOf('Region') === 0 ? n : n + ' Regional', act ? 'As played; tap a game for its page.' : 'Projected; the percentages are each team’s chance to reach the next round.', '<div class="cc-bscroll" tabindex="0" role="region" aria-label="' + esc(n) + ' regional"><div class="cc-bracket hk">' + col1 + '</div>' + col2 + '</div></div></div>', { cls: 'cc-region' });
      }).join('') + '</div>';
      html += ffCard(L, S, br, act, seedOf, names.length === 4 ? [[names[0], names[3]], [names[1], names[2]]] : null, regOf);
    }
  } else {
    var seeds = act && act.seeds ? act.seeds : (br.projected && br.projected.seeds) || [];
    seeds.forEach(function (x) { seedOf[String(x.team)] = x.seed; });
    if (!seeds.length) html += QK.empty('No bracket yet', 'The projected field appears once the season simulation has run.');
    else {
      var bySeed = {}; seeds.forEach(function (x) { bySeed[x.seed] = String(x.team); });
      var games2 = (act && act.games) || [];
      var find = function (rd, t) { return games2.filter(function (g) { return (g.round || '').indexOf(rd) === 0 && (String(g.home) === t || String(g.away) === t); })[0] || null; };
      var c1 = '<div class="cc-bcol"><div class="cc-bh">First round</div>', c2 = '<div class="cc-bcol"><div class="cc-bh">Quarterfinals</div>';
      var field = seeds.length;
      var qf = field >= 11 ? [[1, [8, 9]], [4, [5]], [2, [7, 10]], [3, [6, 11]]] : [[1, [8]], [4, [5]], [2, [7]], [3, [6]]];
      qf.forEach(function (q) {
        var top = bySeed[q[0]];
        if (q[1].length === 2) {
          var a = bySeed[q[1][0]], b = bySeed[q[1][1]], g1 = find('First', a) || find('First', b);
          c1 += g1 ? gameBox(L, S, g1, seedOf, q[1].join(' v ')) : projBox(L, S, a, b, seedOf, pr(a, 'QF'), pr(b, 'QF'), q[1].join(' v '));
        }
        var gq = find('Quarter', top);
        var opp = q[1].length === 1 ? bySeed[q[1][0]] : null;
        c2 += gq ? gameBox(L, S, gq, seedOf, '') : projBox(L, S, top, opp, seedOf, pr(top, 'F4'), opp ? pr(opp, 'F4') : null, q[0] + ' v ' + q[1].join('/'));
      });
      html += U.card('NCAA tournament', act ? 'As played; tap a game for its page.' : 'Projected field by our simulations; the percentages are each team’s chance to reach the next round.', '<div class="cc-bscroll" tabindex="0" role="region" aria-label="Bracket"><div class="cc-bracket hk">' + (field >= 11 ? c1 + '</div>' : '') + c2 + '</div></div></div>');
      html += ffCard(L, S, br, act, seedOf, null, null);
    }
  }
  // odds heat table and the bubble
  var ts = Object.keys(odds).filter(function (t) { return (pr(t, 'Field') || 0) > 0.003; }).sort(function (a, b) { return (pr(b, 'Champion') || 0) - (pr(a, 'Champion') || 0) || (pr(b, 'Field') || 0) - (pr(a, 'Field') || 0); }).slice(0, 24);
  if (ts.length) html += U.card(act ? 'Our chances before the tournament' : 'Chance to reach each round', act ? 'Ratings from games before the first NCAA game, played through the actual bracket.' : 'Share of simulated seasons.', U.table(['Team', { label: 'Field', align: 'right' }, { label: L === 'mch' ? 'Reg. final' : 'QF', align: 'right' }, { label: 'Frozen Four', align: 'right' }, { label: 'Final', align: 'right' }, { label: 'Title', align: 'right' }],
    ts.map(function (t) { return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, U.heat(pr(t, 'Field')), U.heat(pr(t, 'QF')), U.heat(pr(t, 'F4')), U.heat(pr(t, 'Final')), U.heat(pr(t, 'Champion'))]; }), { maxHeight: 560 }));
  var bub = (br.projected && br.projected.bubble) || [];
  if (bub.length) html += U.card('The bubble', 'Teams between 3% and 97% to make the field: the bar is our chance; the automatic bid share is the conference tournament.', U.table(['Team', { label: 'Field', align: 'right' }, '', { label: 'Via auto bid', align: 'right' }, { label: 'Avg ' + ((br.selection || {}).label || 'NPI') + ' rank', align: 'right' }],
    bub.map(function (b) { return [{ html: U.teamEnt(L, b.team, { season: S }), v: CC.tname(L, b.team) }, { v: b.p, html: CC.pct(b.p) }, { html: U.bar(b.p), v: b.p }, isNum(b.p_auto) ? CC.pct(b.p_auto) : '—', isNum(b.sel_rank) ? CC.f(b.sel_rank, 1) : '—']; }), { maxHeight: 520 }));
  if ((br.notes || []).length) html += U.note(esc(br.notes.join(' ')));
  node.innerHTML = html;
}
function ffCard(L, S, br, act, seedOf, pairs, regOf) {
  var odds = br.odds || {};
  var pr = function (t, k) { var o = odds[t]; return o && o.p_round && isNum(o.p_round[k]) ? o.p_round[k] : null; };
  var games = (act && act.games) || [];
  var ff = games.filter(function (g) { return (g.round || '') === 'Frozen Four'; }), fin = games.filter(function (g) { return (g.round || '') === 'Final'; })[0];
  var col1 = '<div class="cc-bcol"><div class="cc-bh">Frozen Four</div>', col2 = '<div class="cc-bcol"><div class="cc-bh">National championship</div>';
  if (ff.length) ff.forEach(function (g) { col1 += gameBox(L, S, g, seedOf, ''); });
  else {
    var ranked = Object.keys(odds).sort(function (a, b) { return (pr(b, 'F4') || 0) - (pr(a, 'F4') || 0); });
    var pick = [];
    if (pairs && regOf) pairs.forEach(function (pp) { var c = pp.map(function (n) { return ranked.filter(function (t) { return regOf[t] === n; })[0]; }); pick.push(c); });
    else pick = [[ranked[0], ranked[3]], [ranked[1], ranked[2]]];
    pick.forEach(function (c) { col1 += projBox(L, S, c[0], c[1], seedOf, pr(c[0], 'Final'), pr(c[1], 'Final'), 'likeliest'); });
  }
  if (fin) col2 += gameBox(L, S, fin, seedOf, '');
  else {
    var ch = Object.keys(odds).sort(function (a, b) { return (pr(b, 'Champion') || 0) - (pr(a, 'Champion') || 0); });
    col2 += ch[0] ? '<div class="cc-champ proj">' + QK.teamMark(U.mark(L, ch[0]), 'lg') + '<div><div class="qk-kicker">Title favourite</div><b>' + esc(CC.tname(L, ch[0])) + '</b> ' + CC.pct(pr(ch[0], 'Champion')) + '</div></div>' : '';
  }
  if (act && act.champion) col2 += '<div class="cc-champ">' + QK.teamMark(U.mark(L, act.champion), 'lg') + '<div><div class="qk-kicker">Champion</div><b>' + esc(CC.tname(L, act.champion)) + '</b></div></div>';
  return U.card('Frozen Four', '', '<div class="cc-ff">' + col1 + '</div>' + col2 + '</div></div>');
}

function hkSelection(node, L, S, season, br) {
  var sel = season.selection || (br && br.selection) || {};
  var rows = sel.rows || [];
  if (!rows.length) { node.innerHTML = QK.empty('No selection table yet', 'It appears after the first games between Division I teams.'); return; }
  var npi = sel.kind === 'npi', sim = (season.sim && season.sim.teams) || {};
  var field = (season.format && season.format.ncaa && season.format.ncaa.field) || 16;
  var cols = [{ key: 'rank', label: '#', num: true }, { key: 'name', label: 'Team', type: 'entity', mark: function (r) { return U.mark(L, r.team); }, href: function (r) { return CC.teamHref(L, r.team, S); } }];
  if (npi) cols.push({ key: 'npi', label: 'NPI', num: true, fmt: function (v) { return CC.f(v, 2); }, tip: 'Our NPI: 25% the team’s weighted winning share, 75% its opponents’ NPI, plus the quality-win bonus' }, { key: 'wwp', label: 'Wtd win %', num: true, fmt: function (v) { return isNum(v) ? CC.f(v, 3).replace(/^0/, '') : '—'; }, tip: 'Winning share with the home / road weights (overtime wins 0.6)' });
  else cols.push({ key: 'pcw', label: 'Comparisons won', num: true }, { key: 'rpi', label: 'RPI', num: true, fmt: function (v) { return isNum(v) ? CC.f(v, 4).replace(/^0/, '') : '—'; } });
  cols.push({ key: 'rec', label: 'W–L–T' });
  if (CC.isCur(L, S)) cols.push({ key: 'pf', label: 'NCAA field', type: 'bar', max: 1, fmt: function (v) { return isNum(v) ? CC.pct(v) : '—'; }, tip: 'Our chance to make the field, from simulated seasons' });
  var data = rows.map(function (r) { return { team: String(r.team), rank: r.rank, name: CC.tshort(L, r.team), npi: r.npi, wwp: r.wwp, pcw: r.pcw, rpi: r.rpi, rec: CC.recW(r), pf: (sim[String(r.team)] || {}).p_ncaa }; });
  node.innerHTML = QK.explain(npi ? '<b>The NPI</b> (NCAA Percentage Index) picks the at-large teams: the six conference tournament champions plus the ten best others by NPI make the men’s field of 16' + (L === 'wch' ? ' (women: five champions and six at-large, 11 teams)' : '') + '. A win is worth 25 points plus three quarters of the opponent’s NPI (plus a bonus over teams above 51), a loss three quarters of the opponent’s NPI; road wins and home losses count 1.2, home wins and road losses 0.8; overtime wins 0.6 of a win; “bad wins” and “good losses” are dropped. Ours is computed from the results.' :
    '<b>The PairWise</b> compared every team with every other on the RPI, the record against common opponents and head to head; the comparisons won ranked the field to 2024-25. Ours is rebuilt from the results.', { title: npi ? 'How the field is picked' : 'How the field was picked' }) +
    '<div id="sel-tbl"></div>' + (sel.through ? U.note('Games before ' + esc(CC.date(sel.through + 'T12:00:00Z')) + ' (the first NCAA game).') : '') + '<div id="sel-val"></div>';
  QK.leaderboard(QK.$('#sel-tbl', node), { dense: true, columns: cols, rows: data, maxHeight: 900, rowHref: function (r) { return CC.teamHref(L, r.team, S); }, rowClass: function (r) { return r.rank <= field ? 'hl' : ''; } });
  CC.load(CC.lpath(L, 'calibration.json')).then(function (cj) {
    var v = CC.ok(cj) ? cj.validation : null, host = QK.$('#sel-val', node);
    if (!v || !host || !U.alive(host)) return;
    host.innerHTML = selValidation(L, v);
  });
}
function selValidation(L, v) {
  var parts = [];
  if (v.npi) parts.push('<b>NPI:</b> against College Hockey News’s published NPI for ' + esc(v.npi.label || 'this season') + ', ' + v.npi.n + ' teams: mean absolute difference ' + CC.f(v.npi.mae, 3) + ', largest ' + CC.f(v.npi.max, 3) + ' (the table rounds to 0.01), ' + v.npi.rank_exact + ' of ' + v.npi.n + ' ranks identical.');
  if (v.pairwise && v.pairwise.seasons) {
    var s = v.pairwise;
    parts.push('<b>PairWise, ' + esc(CC.seasonLabel(L, s.first)) + ' to ' + esc(CC.seasonLabel(L, s.last)) + ':</b> against the published final tables, the 16-team top of the PairWise matched ' + CC.f(s.top16_overlap, 1) + ' of 16 on average; ' + CC.pct(s.rank_exact, 0) + ' of all ranks identical, ' + CC.pct(s.rank_within1, 0) + ' within one; RPI mean absolute difference ' + CC.f(s.rpi_mae, 4) + '.');
  }
  return parts.length ? QK.explain(parts.join('<br>'), { title: 'How close is our replica?' }) : '';
}

function hkPolls(node, L, S, season) {
  var P = season.polls || {}, rows = P.uscho || [];
  var mr = {}; (season.power || []).forEach(function (r) { mr[String(r.team)] = r.rank; });
  var rec = {}; Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = CC.recW(r); }); });
  var tbl = rows.length ? U.table([{ label: '#', align: 'right' }, 'Team', { label: 'Prev', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Ours', align: 'right' }, { label: 'W–L–T', align: 'right' }], rows.map(function (r) {
    var t = String(r.team), mv = isNum(r.prev) && r.prev ? r.prev - r.rank : null;
    return [r.rank, { html: U.teamEnt(L, t, { season: S }) + (mv ? ' <span class="cc-mv ' + (mv > 0 ? 'pos' : 'neg') + '">' + (mv > 0 ? '▲' : '▼') + Math.abs(mv) + '</span>' : ''), v: CC.tname(L, t) }, isNum(r.prev) && r.prev ? r.prev : '—', isNum(r.points) && r.points ? r.points : '—', isNum(mr[t]) ? mr[t] : '—', rec[t] || r.record || '—'];
  }), { maxHeight: 640 }) : QK.empty('No poll for this season', 'The USCHO poll appears once it is published (past seasons keep their final poll).');
  node.innerHTML = '<div class="cc-polls">' + U.card('USCHO poll', P.as_of ? 'As of ' + esc(CC.date(P.as_of + 'T12:00:00Z')) : '', tbl) + '</div>' + QK.explain('Our own ranking is the <a class="qk-link" href="' + esc(CC.href(L, 'teams', null, S)) + '">Teams page’s power board</a>; the “Ours” column is that rank.', { title: 'Our power ranking.' });
}

function hkHistory(node, L, S, h) {
  if (!CC.ok(h) || !(h.champions || []).length) { node.innerHTML = U.missing('The history', h); return; }
  if (h.teams) CC.addTeams(L, h.teams);
  var ch = (h.champions || []).slice().sort(function (a, b) { return b.season - a.season; });
  var titles = {};
  ch.forEach(function (c) { (titles[String(c.team)] = titles[String(c.team)] || []).push(c.season); });
  var kings = Object.keys(titles).sort(function (a, b) { return titles[b].length - titles[a].length || Math.max.apply(null, titles[b]) - Math.max.apply(null, titles[a]); });
  var first = ch[ch.length - 1].season, top = kings[0];
  var ffApp = {};
  Object.keys(h.frozen_fours || {}).forEach(function (s) { (h.frozen_fours[s] || []).forEach(function (t) { ffApp[t] = (ffApp[t] || 0) + 1; }); });
  var ffk = Object.keys(ffApp).sort(function (a, b) { return ffApp[b] - ffApp[a]; });
  var html = U.stats([{ label: 'Most titles since ' + CC.seasonLabel(L, first), value: CC.tabbr(L, top) + ' ' + titles[top].length, signal: true, href: CC.teamHref(L, top, S), sub: CC.tname(L, top) },
    { label: 'Different champions', value: String(kings.length), sub: 'in ' + ch.length + ' tournaments' },
    ffk[0] ? { label: 'Most Frozen Fours', value: CC.tabbr(L, ffk[0]) + ' ' + ffApp[ffk[0]], href: CC.teamHref(L, ffk[0], S), sub: CC.tname(L, ffk[0]) } : null,
    { label: 'Latest champion', value: CC.tshort(L, ch[0].team), text: true, href: CC.teamHref(L, ch[0].team, S), sub: CC.seasonLabel(L, ch[0].season) + (ch[0].score ? ', ' + ch[0].score + ' over ' + CC.tshort(L, ch[0].runner_up) : '') }].filter(Boolean));
  var strip = '<div class="cc-dyn" role="list">' + kings.map(function (t) {
    var tm = CC.team(L, t) || {}, b = QK.color.block(tm.colour && QK.color.parse(tm.colour) ? tm.colour : null);
    return '<div class="cc-dyn-r" role="listitem"><a class="cc-dyn-n" href="' + esc(CC.teamHref(L, t, S)) + '">' + QK.teamMark(U.mark(L, t), 'sm') + '<span>' + esc(CC.tshort(L, t)) + '</span></a><span class="cc-dyn-b">' +
      titles[t].slice().sort().map(function (y) { return '<i style="background:' + esc(b.bg) + (b.edge ? ';box-shadow:inset 0 -4px 0 ' + esc(b.edge) : '') + '" title="' + esc(CC.tname(L, t) + ', ' + CC.seasonLabel(L, y)) + '">' + esc('’' + String(y).slice(2)) + '</i>'; }).join('') + '</span><b class="num">' + titles[t].length + '</b></div>';
  }).join('') + '</div>';
  var tbl = U.table([{ label: 'Season', align: 'right' }, 'Champion', 'Runner-up', { label: 'Final', align: 'right' }, 'Frozen Four'], ch.map(function (c) {
    var ff = ((h.frozen_fours || {})[String(c.season)] || []).filter(function (t) { return t !== c.team && t !== c.runner_up; });
    return [{ v: c.season, html: esc(CC.seasonLabel(L, c.season)) }, { html: U.teamEnt(L, c.team, { season: c.season }), v: CC.tname(L, c.team) }, c.runner_up ? { html: U.teamEnt(L, c.runner_up, { season: c.season }), v: CC.tname(L, c.runner_up) } : '—', esc(c.score || '—'),
      esc(ff.map(function (t) { return CC.tabbr(L, t); }).join(', '))];
  }), { maxHeight: 560 });
  var calls = (h.calls || []).slice().sort(function (a, b) { return b.season - a.season; });
  var callT = calls.length ? U.table([{ label: 'Season', align: 'right' }, 'Our favourite', { label: 'Its chance', align: 'right' }, 'Champion', { label: 'Our chance', align: 'right' }, { label: 'Frozen Four expected', align: 'right' }], calls.map(function (c) {
    return [{ v: c.season, html: esc(CC.seasonLabel(L, c.season)) }, { html: U.teamEnt(L, c.favourite, { season: c.season, abbr: true }) + (c.hit ? ' ' + QK.tag('Right', 'signal') : ''), v: CC.tname(L, c.favourite) }, CC.pct(c.p_favourite), { html: U.teamEnt(L, c.champion, { season: c.season, abbr: true }), v: CC.tname(L, c.champion) }, CC.pct(c.p_champion), isNum(c.ff_expected) ? CC.f(c.ff_expected, 2) + ' of 4' : '—'];
  }), { maxHeight: 520 }) : '';
  var hits = calls.filter(function (c) { return c.hit; }).length;
  var best = (h.best_teams || []).slice(0, 12);
  var bestT = best.length ? U.table(['#', { label: 'Season', align: 'right' }, 'Team', { label: 'W–L–T', align: 'right' }, { label: 'Final rating', align: 'right' }], best.map(function (r, i) {
    return [i + 1, { v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, { html: U.teamEnt(L, r.team, { season: r.season }), v: r.name || CC.tname(L, r.team) }, r.record || '—', { v: r.rating, html: CC.signed(r.rating, 2) }];
  }), { sticky: false }) : '';
  html += U.section('Dynasties', 'Every national champion in our data: one block per title in the team’s colour.', U.card('', '', strip), '', 'Titles') +
    '<div class="qk-grid cc-grid"><div class="qk-span-7">' + U.card('Every champion', 'The NCAA tournament finals and Frozen Fours.', tbl) + '</div><div class="qk-span-5">' + (bestT ? U.card('The best teams', 'By our final rating (goals a game better than an average D-I team).', bestT) : '') + '</div></div>' +
    (callT ? U.section('Our calls', 'Before each tournament, from ratings fitted on games before its first game, through the actual bracket: our favourite won ' + hits + ' of ' + calls.length + '. “Frozen Four expected” adds up our chances for the four teams that got there (a perfect call is 4).', U.card('', '', callT), '', 'Calls') : '');
  node.innerHTML = html;
}

function hkRaces(node, L, S, season, v) {
  if (!CC.ok(v) || !(v.leaders || []).length) { node.innerHTML = U.missing('The races', v); return; }
  var rows = (v.leaders || []).filter(function (r) { return isNum(r.value); });
  var bar = function (list) {
    var max = list.length ? Math.max.apply(null, list.map(function (r) { return r.value; })) : 1;
    return '<ol class="cc-race-l">' + list.map(function (r, i) {
      var tm = CC.team(L, r.team) || {};
      return '<li><span class="cc-race-rk num">' + (i + 1) + '</span>' + QK.teamMark(U.mark(L, r.team), 'sm') + '<span class="cc-race-nm"><a href="' + esc(CC.playerHref(L, r.id, S)) + '">' + esc(r.name) + '</a><small>' +
        esc([CC.posName(L, r.pos), CC.tshort(L, r.team), r['class'] || '', r.gp + ' games'].filter(Boolean).join(' · ')) + '</small>' + (r.why ? '<span class="cc-race-why">' + esc(r.why) + '</span>' : '') + '</span><span class="cc-race-bar" aria-hidden="true"><i style="width:' + Math.max(3, 100 * r.value / max).toFixed(1) + '%;background:' + esc(tm.colour && QK.color.parse(tm.colour) ? QK.color.team(tm.colour) : 'var(--signal)') + '"></i></span><b class="num">' + CC.f(r.value, 1) + '</b></li>';
    }).join('') + '</ol>';
  };
  var fr = rows.filter(function (r) { return /^FR/i.test(r['class'] || ''); }).slice(0, 5);
  var side = [['Forwards', 'F'], ['Defence', 'D'], ['Goalies', 'G']].map(function (sd) { var l = rows.filter(function (r) { return r.pos === sd[1]; }).slice(0, 5); return l.length ? '<div class="qk-span-4">' + U.card(sd[0], 'The top five by value', bar(l)) + '</div>' : ''; }).join('');
  node.innerHTML = U.section(L === 'mch' ? 'Hobey Baker watch: the value race' : 'Patty Kazmaier watch: the value race', 'The ten most valuable players ' + (CC.isCur(L, S) ? 'this season' : 'of ' + CC.seasonLabel(L, S)) + ' in our value model (goals above replacement); a guide to who has done most, not a forecast of the voters.', U.card('', '', bar(rows.slice(0, 10))), '', 'Races') +
    '<div class="qk-grid cc-grid">' + side + '</div>' + (fr.length ? U.section('Rookie of the year', 'The five most valuable freshmen.', U.card('', '', bar(fr)), '', 'Races') : '');
}

/* ── game centre pieces ──────────────────────────────────────────────── */
function perName(p) { return p === 1 ? '1st' : p === 2 ? '2nd' : p === 3 ? '3rd' : p === 4 ? 'OT' : p > 4 ? (p - 3) + 'OT' : ''; }
function clock(t) { if (!isNum(t)) return ''; return Math.floor(t / 60) + ':' + ('0' + (t % 60)).slice(-2); }
CC.hkBox = function (L, g) {
  var bx = g.box || null, ts = g.team_stats || {}, out = '';
  var H = String(g.home), A = String(g.away);
  // shots and goals by period
  var th = ts[H] || {}, ta = ts[A] || {};
  if (th.sog_per || th.goals_per) {
    var np = Math.max((th.goals_per || []).length, (th.sog_per || []).length, 3);
    var lab = []; for (var i = 1; i <= np; i++) lab.push(i <= 3 ? String(i) : (i === 4 ? 'OT' : (i - 3) + 'OT'));
    var row = function (t, d, sc) {
      var gp = d.goals_per || [], sp = d.sog_per || [];
      return '<tr><td>' + QK.teamMark(U.mark(L, t), 'sm') + ' ' + esc(CC.tabbr(L, t)) + '</td>' + lab.map(function (x, k) { return '<td class="num">' + (isNum(gp[k]) ? '<b>' + gp[k] + '</b>' : '–') + (isNum(sp[k]) ? ' <span class="qk-muted">(' + sp[k] + ')</span>' : '') + '</td>'; }).join('') +
        '<td class="num"><b>' + (isNum(sc) ? sc : '–') + '</b>' + (isNum(d.sog) ? ' <span class="qk-muted">(' + d.sog + ')</span>' : '') + '</td></tr>';
    };
    out += U.card('Goals and shots by period', 'Goals, with shots on goal in brackets.', '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th></th>' + lab.map(function (x) { return '<th class="num">' + x + '</th>'; }).join('') + '<th class="num">T</th></tr></thead><tbody>' + row(A, ta, g.as) + row(H, th, g.hs) + '</tbody></table></div>');
  }
  if (!bx) return out;
  var tn = function (t) { return CC.tabbr(L, t); };
  // scoring summary
  var goals = (bx.goals || []).slice().sort(function (x, y) { return (x[0] - y[0]) || (x[1] - y[1]); });
  if (goals.length) {
    var lastP = null, items = '';
    goals.forEach(function (x) {
      if (x[0] !== lastP) { items += '<li class="cc-hk-per">' + esc(perName(x[0]) + (x[0] <= 3 ? ' period' : '')) + '</li>'; lastP = x[0]; }
      var sit = x[9] && x[9] !== 'EV' ? ' ' + QK.tag(x[9].replace(/\+/g, ' ')) : '';
      var who = x[3] ? '<a href="' + esc(CC.playerHref(L, x[3], g.season)) + '">' + esc(x[4]) + '</a>' : esc(x[4] || '');
      var ast = [[x[5], x[6]], [x[7], x[8]]].filter(function (a) { return a[1]; }).map(function (a) { return a[0] ? '<a href="' + esc(CC.playerHref(L, a[0], g.season)) + '">' + esc(a[1]) + '</a>' : esc(a[1]); });
      items += '<li><span class="t num">' + esc(clock(x[1])) + '</span>' + QK.teamMark(U.mark(L, x[2]), 'sm') + '<span class="tx"><b>' + who + '</b>' + (isNum(x[10]) ? ' (' + x[10] + ')' : '') + sit + '<small>' + (ast.length ? 'from ' + ast.join(', ') : 'unassisted') + '</small></span></li>';
    });
    out += U.card('Scoring', '', '<ol class="cc-hk-goals">' + items + '</ol>');
  }
  // penalties
  var pens = (bx.pens || []).slice().sort(function (x, y) { return (x[0] - y[0]) || (x[1] - y[1]); });
  if (pens.length) out += U.card('Penalties', pens.length + ' penalties', U.table(['Per', 'Time', 'Team', 'Player', { label: 'Min', align: 'right' }, 'Infraction'], pens.map(function (x) {
    return [esc(perName(x[0])), esc(clock(x[1])), esc(tn(x[2])), x[3] ? { html: '<a href="' + esc(CC.playerHref(L, x[3], g.season)) + '">' + esc(x[4]) + '</a>', v: x[4] } : esc(x[4] || ''), x[5], esc(x[6] || '')];
  }), { sticky: false, maxHeight: 360 }));
  // goalies
  var gk = (bx.goalies || []).filter(function (x) { return !x[6]; });
  if (gk.length) out += U.card('Goaltending', '', U.table(['Goalie', 'Team', { label: 'Saves', align: 'right' }, { label: 'GA', align: 'right' }, { label: 'SV%', align: 'right' }, { label: 'Min', align: 'right' }], gk.map(function (x) {
    var sa = (x[3] || 0) + (x[4] || 0);
    return [x[0] ? { html: '<a href="' + esc(CC.playerHref(L, x[0], g.season)) + '">' + esc(x[2]) + '</a>', v: x[2] } : esc(x[2]), esc(tn(x[1])), x[3], x[4], sa ? CC.f(x[3] / sa, 3).replace(/^0/, '') : '—', esc(clock(x[5]))];
  }), { sticky: false }));
  return out;
};
CC.hkSkaters = function (L, g) {
  var bx = g.box || null;
  if (!bx || !(bx.skaters || []).length) return '';
  var tabs = [String(g.away), String(g.home)];
  var hasToi = bx.skaters.some(function (r) { return isNum(r[7]); }), hasFo = bx.skaters.some(function (r) { return isNum(r[9]) && (r[9] + r[10]) > 0; });
  var html = '<div class="qk-tabs" role="tablist">' + tabs.map(function (t, i) { return '<button class="qk-tab" role="tab" aria-selected="' + (i === 0) + '" aria-controls="hkbox-' + t + '">' + esc(CC.tshort(L, t)) + '</button>'; }).join('') + '</div>';
  tabs.forEach(function (t, i) {
    var rows = bx.skaters.filter(function (r) { return String(r[1]) === t; });
    var cols = [{ label: 'Player' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'PTS', align: 'right' }, { label: '+/-', align: 'right' }, { label: 'SOG', align: 'right' }].concat(hasToi ? [{ label: 'TOI', align: 'right' }] : []).concat([{ label: 'PIM', align: 'right' }]).concat(hasFo ? [{ label: 'FO', align: 'right' }] : []);
    var body = rows.map(function (r) {
      var nm = r[0] ? { html: '<a href="' + esc(CC.playerHref(L, r[0], g.season)) + '">' + esc(r[2]) + '</a>', v: r[2] } : esc(r[2]);
      return [nm, isNum(r[3]) ? r[3] : '—', isNum(r[4]) ? r[4] : '—', (r[3] || 0) + (r[4] || 0), isNum(r[5]) ? { v: r[5], html: CC.signed(r[5], 0) } : '—', isNum(r[6]) ? r[6] : '—'].concat(hasToi ? [{ v: r[7], html: esc(clock(r[7])) }] : []).concat([isNum(r[8]) ? r[8] : '—']).concat(hasFo ? [isNum(r[9]) && (r[9] + r[10]) ? r[9] + '–' + r[10] : '—'] : []);
    });
    html += '<div class="qk-tabpanel" role="tabpanel" id="hkbox-' + t + '"' + (i ? ' hidden' : '') + '>' + U.table(cols, body) + '</div>';
  });
  return U.card('Box score', 'Player lines from College Hockey News.', html, { cls: 'cc-box' });
};
CC.hkTeamStats = function (L, g) {
  var ts = g.team_stats || {}, H = ts[String(g.home)] || {}, A = ts[String(g.away)] || {};
  var lab = [['sog', 'Shots on goal'], ['pp', 'Power play'], ['pim', 'Penalty minutes'], ['fo', 'Faceoffs won'], ['chn_xg', 'CHN xG (theirs)']];
  var v = function (d, k) {
    if (k === 'pp') return isNum(d.ppg) && isNum(d.ppo) ? d.ppg + ' of ' + d.ppo : null;
    if (k === 'fo') return isNum(d.fow) ? String(d.fow) : null;
    if (k === 'chn_xg') return isNum(d.chn_xg) ? CC.f(d.chn_xg, 1) : null;
    return isNum(d[k]) ? String(d[k]) : null;
  };
  var rows = lab.filter(function (x) { return v(A, x[0]) !== null || v(H, x[0]) !== null; }).map(function (x) {
    return [{ html: '<b>' + esc(v(A, x[0]) || '—') + '</b>', align: 'right' }, { html: esc(x[1]), cls: 'cc-mid' }, { html: '<b>' + esc(v(H, x[0]) || '—') + '</b>' }];
  });
  if (!rows.length) return '';
  return U.card('Team stats', 'College Hockey News’s expected goals are theirs (they publish no shot locations, so we have no xG model of our own).', U.table([{ label: CC.tabbr(L, g.away), align: 'right', sortable: false }, { label: '', sortable: false, cls: 'cc-mid' }, { label: CC.tabbr(L, g.home), sortable: false }], rows, { sticky: false, cls: 'cc-vs' }));
};
CC.hkAttempts = function (L, g) {
  var at = g.attempts;
  if (!at || !(at.rows || []).length) return '';
  var cols = at.cols, idx = {}; cols.forEach(function (c, i) { idx[c] = i; });
  var sk = at.rows.filter(function (r) { return r[0] === 's'; });
  var top = sk.slice().sort(function (a, b) { return (b[idx.all_tsa] || 0) - (a[idx.all_tsa] || 0); }).slice(0, 10);
  return U.card('Shot attempts', 'Every attempt a player took: on goal, missed or blocked, all strengths and at even strength (College Hockey News’s per-game metrics).', U.table(['Player', 'Team', { label: 'Attempts', align: 'right' }, { label: 'On goal', align: 'right' }, { label: 'Missed', align: 'right' }, { label: 'Blocked', align: 'right' }, { label: 'EV att.', align: 'right' }, { label: 'Blocks', align: 'right' }], top.map(function (r) {
    var og = (r[idx.all_sv] || 0) + (r[idx.all_g] || 0);
    return [r[1] ? { html: '<a href="' + esc(CC.playerHref(L, r[1], g.season)) + '">' + esc(r[3]) + '</a>', v: r[3] } : esc(r[3]), esc(CC.tabbr(L, r[2])), r[idx.all_tsa] || 0, og, r[idx.all_mi] || 0, r[idx.all_bl] || 0, r[idx.ev_tsa] || 0, r[idx.blk] || 0];
  }), { sticky: false, maxHeight: 420 }));
};
CC.hkFlow = function (L, g, node) {
  var fl = g.flow;
  if (!fl || fl.length < 3 || !node) return false;
  node.innerHTML = U.card('Score flow', 'The home lead through the game, goal by goal.', U.chart('hk-flow', 200, 'Home lead through the game'));
  QKC.line('#hk-flow', { xType: 'value', xName: 'Minutes played', yName: CC.tabbr(L, g.home) + ' lead (goals)', series: [{ name: 'Home lead', data: fl, area: true, color: CC.tcol(L, g.home) }], step: 'end', yFmt: function (v) { return CC.signed(v, 0); }, xFmt: function (v) { return Math.round(v) + '′'; }, ref: { y: 0 }, endLabels: false, xMin: 0, xMax: Math.max(60, fl[fl.length - 1][0]) });
  return true;
};

/* the Frozen Four card for a finished season's recap (cc-overview.js) */
CC.hkFrozenFour = function (L, S, br) {
  if (!br || !br.actual) return '';
  var seedOf = {};
  Object.keys(br.actual.regions || {}).forEach(function (n) { (br.actual.regions[n] || []).forEach(function (x) { seedOf[String(x.team)] = x.seed; }); });
  (br.actual.seeds || []).forEach(function (x) { seedOf[String(x.team)] = x.seed; });
  return ffCard(L, S, br, br.actual, seedOf, null, null);
};

/* ── Model page ──────────────────────────────────────────────────────── */
CC.hkModel = function (el, p, tab, body) {
  var L = p.L, S = p.S, Sx = CC.cur(L) || S;
  if (tab === 'calibration') return CC.load(CC.lpath(L, 'calibration.json')).then(function (d) { if (U.alive(el)) hkCalib(body, L, d); });
  return Promise.all([new Promise(function (resolve) { fetch('MODELS_HOCKEY.md', { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }).then(resolve, function () { resolve(null); }); }),
    CC.season(L, Sx), CC.load(CC.path(L, Sx, 'value.json')), CC.load(CC.lpath(L, 'calibration.json'))]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[1]) ? a[1] : null, val = CC.ok(a[2]) ? a[2] : null, cal = CC.ok(a[3]) ? a[3] : null;
    var lw = (L === 'mch' ? 'men’s' : 'women’s') + ' college hockey (every Division I team)';
    var n = season && season.sim && isNum(season.sim.n_sims) ? QK.fmt.num(season.sim.n_sims) : 'thousands of';
    var card = function (k, title, text, chart) { return '<article class="qk-card cc-mx"><div class="qk-card-body"><div class="qk-kicker">' + esc(k) + '</div><h3 class="cc-mx-t">' + esc(title) + '</h3><p>' + text + '</p>' + chart + '</div></article>'; };
    var sm = cal && cal.summary ? cal.summary : null;
    body.innerHTML = '<section class="qk-section cc-sec" style="margin-top:var(--sp-6)">' + QK.sectionHead({ kicker: 'How it works', title: 'Four models, in plain words',
      sub: 'We rate every team in ' + esc(lw) + ' on goals scored and goals kept out, turn two ratings into a chance of a win, a tie or a loss for every game, play the rest of the season ' + esc(n) + ' times for the conference, NCAA and title chances (the NPI picks the field, as it does for real), and value every player against a replacement at the same position.' }) +
      '<div class="cc-mx-grid">' +
      card('1 · Team ratings', 'How good is each team?', 'Each team gets an attack and a defence number from every result so far: goals scored and allowed in regulation, adjusted for the opponent and home ice, with recent games counting more and last season as the starting point. The rating is the goal difference a game we expect against an average Division I team on neutral ice.', U.chart('mx-r', 300, 'Our top ten ratings')) +
      card('2 · The game model', 'A win, a tie or a loss', 'The two ratings give each side’s expected goals; goals arrive at random around them (a Poisson model, with ties a little more common than chance, as real hockey has). Level after 60 minutes goes to five minutes of overtime (3-on-3 since 2021-22) and, if still level, a tie in the NCAA record. Playoff games go on until someone scores.', U.chart('mx-g', 300, 'Win, tie and loss chances by goal edge')) +
      card('3 · The season simulation', 'Playing the season ' + n + ' times', 'We play every remaining game, the conference tournaments (formats simplified), compute the NPI on each simulated season, pick the field (six conference champions and ten at-large for the men, five and six for the women), and play the NCAA tournament out. A title chance is the share of seasons a team wins it all.', '<div id="mx-s"></div>') +
      card('4 · Player value', 'Goals above replacement', 'From College Hockey News’s season lines: goals created (a fair split of the team’s goals among its scorers), a damped share of plus-minus, penalties and faceoffs, against a replacement-level forward or defenceman; goalies by goals saved above an average goalie. Six goals is about a win. No shot locations exist for college hockey, so this is production, not play-driving.', U.chart('mx-v', 300, 'The most valuable player at each position')) +
      '</div>' + (sm && sm.model && isNum(sm.model.acc) ? QK.explain('<b>How sure are we?</b> On the two sealed test seasons, every game predicted with only the games before it, our favourite won ' + CC.pct(sm.model.acc, 0) + ' of the games that were not tied, and our log-loss beat the naive base rates by ' + CC.f(-(sm.diff || 0), 3) + '. The calibration and the season-by-season record are on <a class="qk-link" href="' + esc(CC.href(L, 'model', null, null, 'tab=calibration')) + '">How we’re doing</a>.') : '') + '</section>' +
      '<details class="cc-tech qk-card"><summary>Technical detail: the models, the code and the tests</summary><div class="cc-prose">' + (a[0] ? CC.md(a[0]) : '<p class="qk-muted">The methodology document is published with the next build.</p>') + '</div></details>' + CC.hkCredit(false);
    var R = (season && season.ratings) || {}, top = ((season && season.power) || []).slice(0, 10);
    if (top.length) QKC.bar(QK.$('#mx-r', body), { cats: top.map(function (r) { return CC.tshort(L, r.team); }), horizontal: true, fmt: function (v) { return CC.signed(v, 2); },
      series: [{ name: 'Rating', data: top.map(function (r) { return r.rating; }), lo: top.map(function (r) { var x = R[String(r.team)] || {}; return isNum(x.se) ? r.rating - x.se : null; }), hi: top.map(function (r) { var x = R[String(r.team)] || {}; return isNum(x.se) ? r.rating + x.se : null; }) }],
      colors: top.map(function (r) { return CC.tcol(L, r.team); }), labelWidth: 96, valName: 'Rating (goals a game v average)', catName: 'Team' });
    var xs = [], pw = [], pt = [], pl = [];
    for (var d = -2; d <= 2.0001; d += 0.25) {
      var lh = 3 * Math.exp(d / 6), la = 3 * Math.exp(-d / 6), o = hkOutcome(lh, la);
      xs.push(Math.round(d * 100) / 100); pw.push([Math.round(d * 100) / 100, Math.round(1000 * o[0]) / 10]); pt.push([Math.round(d * 100) / 100, Math.round(1000 * o[1]) / 10]); pl.push([Math.round(d * 100) / 100, Math.round(1000 * o[2]) / 10]);
    }
    QKC.line(QK.$('#mx-g', body), { xType: 'value', series: [{ name: 'Win', data: pw, color: QK.cssVar('--signal') }, { name: 'Tie', data: pt, color: QK.cssVar('--c-3') }, { name: 'Loss', data: pl, color: QK.cssVar('--coral') || '#ff6b4a' }],
      xName: 'Expected goal difference', yName: 'Chance (%)', yMin: 0, yMax: 100, xMin: -2, xMax: 2, yFmt: function (v) { return v + '%'; }, xFmt: function (v) { return CC.signed(v, 1); }, label: 'Win, tie and loss chances by goal edge' });
    var sim = (season && season.sim && season.sim.teams) || {};
    var tt = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title) && sim[t].p_title > 0; }).sort(function (x, y) { return sim[y].p_title - sim[x].p_title; }).slice(0, 6);
    QK.$('#mx-s', body).innerHTML = tt.length ? QK.chances(tt.map(function (t) { return { label: CC.tshort(L, t), p: sim[t].p_title, href: CC.teamHref(L, t, Sx), color: CC.traw(L, t), mark: U.mark(L, t) }; }), { key: false }) : QK.empty('The simulation runs with the season', '');
    var bp = (val && val.by_position) || {}, best = ['F', 'D', 'G'].filter(function (k) { return (bp[k] || []).length; }).map(function (k) { return { k: k, r: bp[k][0] }; });
    if (best.length) QKC.bar(QK.$('#mx-v', body), { cats: best.map(function (b) { return b.k + ' · ' + QK.surname(b.r.name || ''); }), horizontal: true, labels: true, fmt: function (v) { return CC.f(v, 1); },
      series: [{ name: 'GAR', data: best.map(function (b) { return b.r.value; }) }], colors: best.map(function (b) { return CC.tcol(L, b.r.team); }), labelWidth: 120, valName: 'Goals above replacement', catName: 'Position' });
    else QK.$('#mx-v', body).innerHTML = QK.empty('Player values appear with the first games', '');
  });
};
/* the game model's shape at a typical goal rate (rho 0.12, 3-on-3 overtime 62% decided) for the explainer chart */
function hkOutcome(lh, la) {
  var f = function (l) { var o = [], p = Math.exp(-l); for (var k = 0; k <= 12; k++) { o.push(p); p = p * l / (k + 1); } return o; };
  var A = f(lh), B = f(la), w = 0, t = 0, l = 0;
  for (var i = 0; i <= 12; i++) for (var j = 0; j <= 12; j++) { var x = A[i] * B[j]; if (i > j) w += x; else if (i < j) l += x; else t += x; }
  t *= 1.12; var s = w + t + l; w /= s; t /= s; l /= s;
  var q = 0.62, sh = lh / (lh + la);
  return [w + t * q * sh, t * (1 - q), l + t * q * (1 - sh)];
}
function hkCalib(node, L, d) {
  if (!CC.ok(d)) { node.innerHTML = U.missing('The backtest', d); return; }
  var sm = d.summary || {}, m = sm.model || {}, dev = sm.dev || {};
  var tiles = U.stats([{ label: 'Log-loss, sealed seasons', value: CC.f(m.logloss, 3), signal: true, sub: 'base rates ' + CC.f((sm.base || {}).logloss, 3) + ' · ' + QK.fmt.num(m.n || 0) + ' games', tip: 'Lower is better: the average surprise of our win / tie / loss chances' },
    { label: 'Better than base rates by', value: CC.f(-(sm.diff || 0), 3), sub: isNum((sm.ci95 || [])[0]) ? '95% CI ' + CC.f(-sm.ci95[1], 3) + ' to ' + CC.f(-sm.ci95[0], 3) : '', tip: 'Paired difference in log-loss, model minus the naive base rates; the interval excludes zero when the model is clearly better' },
    { label: 'Favourite won', value: CC.pct(m.acc, 0), sub: 'of the sealed seasons’ games (a tie counts as a miss)' },
    { label: 'Development seasons', value: CC.f(dev.logloss, 3), sub: 'base ' + CC.f(dev.logloss_base, 3) + ' · ' + QK.fmt.num(dev.n || 0) + ' games, where the settings were chosen' }]);
  var per = (d.per_season || []).slice().sort(function (a, b) { return b.season - a.season; });
  var tbl = U.table([{ label: 'Season', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'Log-loss', align: 'right' }, { label: 'Base rates', align: 'right' }, { label: 'Gain', align: 'right' }, { label: '95% CI', align: 'right' }, { label: 'Ties: real v ours', align: 'right' }, ''], per.map(function (r) {
    return [{ v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, r.n, CC.f(r.model.logloss, 3), CC.f(r.base.logloss, 3), { v: -r.diff, html: CC.f(-r.diff, 3) }, (r.ci95 ? CC.f(-r.ci95[1], 3) + ' to ' + CC.f(-r.ci95[0], 3) : '—'), CC.pct(r.tie_rate, 1) + ' v ' + CC.pct(r.tie_pred, 1), r.sealed ? QK.tag('sealed test', 'signal') : ''];
  }), { maxHeight: 520 });
  var val = d.validation ? selValidation(L, d.validation) : '';
  node.innerHTML = tiles + '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Calibration', 'Our chance for the home team against how often it won, grouped (sealed seasons).', U.chart('hk-cal', 280, 'Calibration')) + '</div><div class="qk-span-6">' + U.card('Season by season', 'Every game between two Division I teams, each predicted from the games before its day.', tbl) + '</div></div>' + val +
    U.note(esc((d.notes || []).join(' '))) + (sm.promoted === false ? U.note('<b>On the promotion rule:</b> the sealed seasons’ interval does not clear zero, so the model is shown as it is, not as an improvement.') : '');
  var bins = d.calibration || [];
  if (bins.length) QKC.line('#hk-cal', { xType: 'value', series: [{ name: 'Observed', data: bins.map(function (b) { return [Math.round(b.p_mean * 1000) / 10, Math.round(b.y_mean * 1000) / 10]; }), color: QK.cssVar('--signal'), symbols: true }, { name: 'Perfect', data: [[0, 0], [100, 100]], color: QK.cssVar('--ink-3'), dashed: true }],
    xName: 'Our chance for the home team (%)', yName: 'Home team won (%)', xMin: 0, xMax: 100, yMin: 0, yMax: 100, yFmt: function (v) { return v + '%'; }, xFmt: function (v) { return v + '%'; }, label: 'Calibration' });
}

})(window.CC);
