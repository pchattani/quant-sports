/* The Quant Campus — Teams (#/<L>/teams) and the team page (#/<L>/team/<tid>).
 * Catalogue: every member team with the payload's metrics and percentile chips, conference filter, search, and an
 * offense-v-defense map. Team page: rating with uncertainty, rating path, AP v model rank by week, schedule with
 * the model's win probability and the market, roster with value, strengths and needs (graded units), inferred
 * transfers in and out, model suggestions for the weakest units, and season odds.
 * Reads <L>/<S>/teams.json, <L>/<S>/teams/<tid>.json, <L>/<S>/season.json. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

CC.route('teams', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  el.innerHTML = U.head('Teams', '', U.kicker(L, S)) + QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'teams.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var cat = a[0];
    if (!CC.ok(cat)) { el.innerHTML = U.head('Teams', '', U.kicker(L, S)) + U.missing('The team catalogue', cat); return; }
    var mets = (cat.metrics || []).slice(0, 8);
    var T = cat.teams || {};
    var ids = Object.keys(T);
    var confs = {};
    ids.forEach(function (t) { if (T[t].conference) confs[T[t].conference] = 1; });
    var conf = (p.query || {}).conf || '';
    var opts = '<option value="">All conferences</option>' + Object.keys(confs).sort(function (x, y) { return CC.cname(L, x).localeCompare(CC.cname(L, y)); }).map(function (c) { return '<option value="' + esc(c) + '"' + (c === conf ? ' selected' : '') + '>' + esc(CC.cname(L, c)) + '</option>'; }).join('');
    el.innerHTML = U.head('Teams', ids.length + (fb ? ' FBS teams' : ' Division I teams') + ': ratings, efficiency and schedule strength, each with its national percentile.', U.kicker(L, S)) +
      '<div class="cc-toolbar"><input class="qk-input" type="search" id="tm-q" placeholder="Find a team" aria-label="Find a team"><select class="qk-select" id="tm-conf" aria-label="Conference">' + opts + '</select></div>' +
      '<div class="qk-grid cc-grid"><div class="qk-span-8" id="tm-table"></div><div class="qk-span-4" id="tm-map"></div></div>';
    var ox = mets.filter(function (m) { return m.key === 'off'; })[0], dx = mets.filter(function (m) { return m.key === 'def'; })[0];
    function rows() {
      var q = (QK.$('#tm-q', el).value || '').toLowerCase(), c = QK.$('#tm-conf', el).value;
      return ids.filter(function (t) { return (!c || String(T[t].conference) === c) && (!q || String(T[t].name || '').toLowerCase().indexOf(q) >= 0); });
    }
    function paint() {
      var rs = rows().sort(function (x, y) { return (T[x].rating_rank || 999) - (T[y].rating_rank || 999); });
      var cols = [{ label: 'Rk', align: 'right' }, 'Team', 'Conf.', { label: 'W–L', align: 'right' }].concat(mets.map(function (m) { return { label: m.label, align: 'right', title: m.desc || '' }; }));
      QK.$('#tm-table', el).innerHTML = U.card('Catalogue', rs.length + ' teams · chips show the national percentile (higher is better, whichever way the stat runs).', U.table(cols, rs.map(function (t) {
        var x = T[t];
        return { cells: [isNum(x.rating_rank) ? x.rating_rank : '—', { html: U.teamEnt(L, t, { season: S }), v: x.name }, esc(CC.cname(L, x.conference)), { v: (x.w || 0) - (x.l || 0), html: CC.record(x.w, x.l) }].concat(mets.map(function (m) {
          var v = (x.values || {})[m.key], pc = (x.pct || {})[m.key];
          return { v: isNum(v) ? v : null, html: '<span class="cc-num">' + CC.fmtMetric(m, v) + '</span>' + (isNum(pc) ? QK.pctlChip(pc) : '') };
        })), _href: CC.teamHref(L, t, S) };
      }), { maxHeight: 720 }));
      U.wire(QK.$('#tm-table', el));
      if (ox && dx) {
        QK.$('#tm-map', el).innerHTML = U.card('Offense v defense', 'Up and right is better on both sides of the ball.', U.chart('tm-sc', 420, 'Offense against defense, every team shown'));
        QKC.scatter('#tm-sc', { points: rs.map(function (t) { var v = T[t].values || {}; return { x: v.off, y: v.def, name: T[t].name, label: CC.tabbr(L, t), color: CC.tcol(L, t), href: CC.teamHref(L, t, S), size: 9 }; }).filter(function (q) { return isNum(q.x) && isNum(q.y); }),
          xName: ox.label, yName: dx.label, yInverse: !!dx.lower, labelTop: 8, xFmt: function (v) { return CC.f(v, 0); }, yFmt: function (v) { return CC.f(v, 0); } });
      }
    }
    QK.$('#tm-q', el).addEventListener('input', paint);
    QK.$('#tm-conf', el).addEventListener('change', paint);
    paint();
  });
});

/* ── team page ───────────────────────────────────────────────────────── */
function oddsKpis(L, o) {
  if (!o) return '';
  var k = [];
  if (isNum(o.exp_w)) k.push(QK.kpi({ label: 'Projected wins', value: CC.f(o.exp_w, 1), sub: CC.f(o.exp_l, 1) + ' losses · mean of simulated seasons' }));
  if (CC.fb(L)) {
    if (isNum(o.p_conf)) k.push(QK.kpi({ label: 'Win the conference', value: CC.pct(o.p_conf) }));
    if (isNum(o.p_cfp)) k.push(QK.kpi({ label: 'Make the playoff', value: CC.pct(o.p_cfp), sub: isNum(o.p_bye) ? 'bye ' + CC.pct(o.p_bye) : '' }));
    if (isNum(o.p_bowl)) k.push(QK.kpi({ label: 'Bowl eligible', value: CC.pct(o.p_bowl) }));
  } else {
    if (isNum(o.p_ncaa)) k.push(QK.kpi({ label: 'Make the tournament', value: CC.pct(o.p_ncaa), sub: isNum(o.seed_mean) ? 'seed ' + CC.f(o.seed_mean, 1) + ' on average' : '' }));
    if (isNum(o.p_conf_tourney)) k.push(QK.kpi({ label: 'Win the conference tournament', value: CC.pct(o.p_conf_tourney) }));
  }
  if (isNum(o.p_title)) k.push(QK.kpi({ label: 'Win the title', value: CC.pct(o.p_title) }));
  return k.join('');
}

CC.route('team', function (el, p) {
  var L = p.L, S = p.S, tid = p.id, fb = CC.fb(L);
  el.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'teams/' + tid + '.json')), CC.season(L, S), CC.load(CC.path(L, S, 'teams.json'))]).then(function (a) {
    /* archive team pages carry no schedule (size budget): the team's games come from the season's schedule.json */
    var d0 = CC.ok(a[0]) ? a[0] : null;
    if (!d0 || d0.schedule) return a;
    return CC.load(CC.path(L, S, 'schedule.json')).then(function (sch) {
      if (CC.ok(sch)) d0.schedule = (sch.games || []).filter(function (c) { return String(c.home) === String(tid) || String(c.away) === String(tid); });
      return a;
    });
  }).then(function (a) {
    if (!U.alive(el)) return;
    var d = CC.ok(a[0]) ? a[0] : null, season = CC.ok(a[1]) ? a[1] : null;
    if (d && d.team) { var m = {}; m[tid] = d.team; CC.addTeams(L, m); }
    var t = CC.team(L, tid);
    if (!d && !t) { el.innerHTML = U.head('Team', '', U.kicker(L, S)) + QK.empty('Team not found', 'No team ' + tid + ' in ' + CC.seasonLabel(L, S) + '.'); return; }
    var R = (d && d.rating) || (season && season.ratings && season.ratings[tid]) || {};
    var sim = (d && d.odds) || (season && season.sim && season.sim.teams && season.sim.teams[tid]) || null;
    var rec = d && d.record ? d.record : {};
    var tc = t && QK.color.parse(t.colour) ? t.colour : null;
    var conf = t ? CC.conf(L, t.conference) : null;
    var stats = [['Record', CC.record(rec.w, rec.l)], ['Rating', CC.signed(R.rating, 1)], ['Rank', isNum(R.rank) ? '#' + R.rank : '—'], ['SOS rank', isNum(R.sos_rank) ? '#' + R.sos_rank : '—']];
    var html = '<section class="qk-hero cc-hero"' + (tc ? ' style="--tc:' + esc(tc) + '"' : '') + '><div class="qk-hero-in">' + QK.teamMark(t || {}, 'lg') + '<div class="cc-hero-id"><div class="qk-kicker">' + esc(CC.LNAME[L] + ' · ' + CC.seasonLabel(L, S)) + '</div><h1>' + esc(t ? t.name : 'Team ' + tid) + '</h1>' +
      '<div class="qk-hero-meta"><span>' + esc(conf ? (conf.name || conf.short) : 'Independent') + '</span>' + (isNum(R.games) ? '<span><b>' + R.games + '</b> games rated</span>' : '') + '</div></div>' +
      '<div class="qk-hero-stats">' + stats.map(function (s) { return '<div class="qk-hero-stat"><div class="v">' + esc(s[1]) + '</div><div class="l">' + esc(s[0]) + '</div></div>'; }).join('') + '</div></div></section>';
    if (!d) html += '<p class="cc-note">The full team page has not been built for this season; ratings come from the season file.</p>';
    var kp = '';
    kp += QK.kpi({ label: 'Rating', value: CC.signed(R.rating, 1), sub: (isNum(R.se) ? '± ' + CC.f(R.se, 1) + ' · ' : '') + (fb ? 'pts v avg FBS' : 'per 100 v avg D-I'), tip: fb ? 'Expected margin against an average FBS team on a neutral field' : 'Adjusted efficiency margin per 100 possessions' });
    if (isNum(R.off)) kp += QK.kpi({ label: 'Offense', value: CC.f(R.off, 1), sub: fb ? 'points per game added' : 'adj. points per 100' });
    var dm = ((CC.ok(a[2]) && a[2].metrics) || []).filter(function (m) { return m.key === 'def'; })[0];
    var defLow = dm ? !!dm.lower : !fb;
    if (isNum(R.def)) kp += QK.kpi({ label: 'Defense', value: CC.f(R.def, 1), sub: defLow ? 'lower is better' : (fb ? 'points prevented per game' : 'higher is better') });
    if (CC.isCur(L, S)) kp += oddsKpis(L, sim);
    html += '<div class="qk-kpis cc-kpis">' + kp + '</div>';
    // charts: rating path + rank history
    var path = (d && d.rating_path) || (season && season.rating_paths && season.rating_paths[tid]) || [];
    var rh = (d && d.rank_history) || [];
    html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Rating through the season', 'Re-fitted after each week' + (fb ? '' : ' (basketball: weekly)') + '.', path.length > 1 ? U.chart('tp-path', 240, 'Rating through the season') : QK.empty('Not enough games yet', 'The path starts after the first games.')) + '</div>' +
      '<div class="qk-span-6">' + U.card('AP rank v our rank', 'Week by week; lower is better.', rh.length > 1 ? U.chart('tp-rank', 240, 'AP and model rank by week') : QK.empty('No rank history', '')) + '</div></div>';
    // schedule
    var sched = (d && d.schedule) || [];
    if (sched.length) {
      html += U.card('Schedule', 'Every game with our pregame win probability for ' + esc(CC.tshort(L, tid)) + ' and the market where known.', U.table(['Date', 'Opponent', { label: 'Win prob.', align: 'right' }, { label: 'Line', align: 'right' }, 'Result', ''], sched.map(function (c) {
        var home = String(c.home) === String(tid), opp = home ? c.away : c.home, m = c.model || {}, mk = c.market || {};
        var pw = isNum(m.p_home) ? (home ? m.p_home : 1 - m.p_home) : null;
        var line = isNum(mk.spread_home) ? (home ? mk.spread_home : -mk.spread_home) : null;
        var res = '—';
        if (c.status === 'post' && isNum(c.hs)) { var my = home ? c.hs : c.as, op = home ? c.as : c.hs; res = '<b class="' + (my > op ? 'pos' : 'neg') + '">' + (my > op ? 'W' : 'L') + '</b> ' + my + '–' + op; }
        var tag = CC.roundLabel(c);
        return { cells: [{ v: c.date, html: esc(CC.date(CC.gameDate(c))) + (CC.tba(c) ? ' <span class="qk-muted">TBA</span>' : '') }, { html: '<span class="qk-muted">' + (c.neutral ? 'v' : home ? 'v' : '@') + '</span> ' + U.teamEnt(L, opp, { season: S, sub: tag || (c.conf_game ? 'conf' : '') }), v: CC.tname(L, opp) },
          { v: pw, html: pw === null ? '—' : CC.pct(pw) + ' ' + U.bar(pw) }, { v: line, html: CC.spread(line) }, { html: res, v: res }, { html: '<a class="cc-link" href="' + esc(CC.gameHref(L, c.id, S)) + '">Game</a>', sortable: false }], _href: CC.gameHref(L, c.id, S) };
      }), { maxHeight: 640 }));
    }
    // roster + units
    var roster = (d && d.roster) || [];
    var units = (d && d.units) || [];
    var rcols = fb ? [['pass_yds', 'Pass yds'], ['rush_yds', 'Rush yds'], ['rec_yds', 'Rec yds'], ['tkl', 'Tkl']] : [['min', 'MIN'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST']];
    rcols = rcols.filter(function (c) { return roster.some(function (r) { return isNum(r[c[0]]); }); });
    var rosterT = roster.length ? U.table(['Player', 'Pos', 'Class', { label: 'GP', align: 'right' }, { label: 'Value', align: 'right' }, { label: 'Per game', align: 'right' }].concat(rcols.map(function (c) { return { label: c[1], align: 'right' }; })), roster.map(function (r) {
      return { cells: [{ html: '<a href="' + esc(CC.playerHref(L, r.id, S)) + '">' + esc(r.name || CC.pname(L, r.id)) + '</a>', v: r.name }, esc(r.pos || '—'), esc(r['class'] || '—'), isNum(r.gp) ? r.gp : '—', { v: r.value, html: CC.f(r.value, fb ? 1 : 2) }, { v: r.value_pg, html: CC.f(r.value_pg, 2) }]
        .concat(rcols.map(function (c) { return isNum(r[c[0]]) ? (fb ? Math.round(r[c[0]]) : CC.f(r[c[0]], 1)) : '—'; })), _href: CC.playerHref(L, r.id, S) };
    }), { maxHeight: 560 }) : QK.empty('No roster yet', 'Rosters come from ESPN; the current one is refreshed weekly.');
    var unitsH = units.length ? QK.pctlBars(units.map(function (u) { return { label: u.unit, pctl: isNum(u.pctl) ? u.pctl : 50, value: u.grade || '' }; })) : '';
    html += '<div class="qk-grid cc-grid"><div class="qk-span-8">' + U.card('Roster', 'Value: ' + (fb ? 'EPA above replacement' : 'value above replacement') + ' this season.' + (!CC.isCur(L, S) && !fb && roster.length <= 12 && roster.length ? ' Archive seasons keep the top 12 by minutes.' : ''), rosterT) + '</div><div class="qk-span-4">' +
      U.card('Strengths and needs', 'Each unit graded against every team in the country.', unitsH ? unitsH + swList(d) : QK.empty('Not graded yet', '')) + '</div></div>';
    // moves and suggestions
    var mv = (d && d.moves) || { 'in': [], out: [] };
    function mvT(list, dir) {
      if (!list || !list.length) return QK.empty(dir === 'in' ? 'No transfers in found' : 'No transfers out found', '');
      return U.table(['Player', 'Pos', dir === 'in' ? 'From' : 'To', { label: 'Value before', align: 'right' }, { label: 'After', align: 'right' }], list.map(function (m) {
        return [{ html: '<a href="' + esc(CC.playerHref(L, m.player, S)) + '">' + esc(m.name || CC.pname(L, m.player)) + '</a>', v: m.name }, esc(m.pos || '—'), { html: U.teamEnt(L, dir === 'in' ? m.from : m.to, { season: S }), v: CC.tname(L, dir === 'in' ? m.from : m.to) },
          { v: m.value_before, html: CC.f(m.value_before, 1) }, { v: m.value_after, html: CC.f(m.value_after, 1) }];
      }), { sticky: false });
    }
    html += U.section('Moves', 'Inferred from box scores and rosters (the same ESPN athlete on a new team since last season); not the official transfer portal.',
      '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('In', '', mvT(mv['in'], 'in')) + '</div><div class="qk-span-6">' + U.card('Out', '', mvT(mv.out, 'out')) + '</div></div>');
    var sg = (d && d.suggestions) || [];
    if (sg.length) {
      html += U.section('Ways to improve', esc((d && d.suggestions_note) || 'Model suggestions for the weakest units: players elsewhere whose on-field value would add most. Not considering eligibility, NIL, fit or availability.'),
        '<div class="cc-auto wide">' + sg.map(function (s) {
          return U.card('Need: ' + s.need, '', U.table(['Player', 'Team', { label: 'Value', align: 'right' }, { label: 'Gain', align: 'right' }], (s.candidates || []).map(function (c) {
            return [{ html: '<a href="' + esc(CC.playerHref(L, c.id, S)) + '">' + esc(c.name || CC.pname(L, c.id)) + '</a>', v: c.name }, { html: U.teamEnt(L, c.team, { season: S, abbr: true }), v: CC.tname(L, c.team) }, { v: c.value, html: CC.f(c.value, 1) }, { v: c.gain, html: CC.signed(c.gain, 1) }];
          }), { sticky: false }));
        }).join('') + '</div>');
    }
    // season odds distributions
    if (CC.isCur(L, S) && sim && (sim.w_dist || sim.seed_dist)) {
      html += '<div class="qk-grid cc-grid">' + (sim.w_dist && sim.w_dist.length ? '<div class="qk-span-6">' + U.card('Final win total', 'Share of simulated seasons ending on each number of regular-season wins.', U.chart('tp-wd', 220, 'Distribution of final wins')) + '</div>' : '') +
        (sim.seed_dist && Object.keys(sim.seed_dist).length ? '<div class="qk-span-6">' + U.card(fb ? 'Playoff seed' : 'Tournament seed', 'Share of simulated seasons in which the team gets each seed.', U.chart('tp-sd', 220, 'Distribution of seeds')) + '</div>' : '') + '</div>';
    }
    el.innerHTML = html;
    U.wire(el);
    var col = tc ? QK.color.team(tc) : null;
    if (path.length > 1) QKC.line('#tp-path', { xType: 'time', xName: 'Date', yName: fb ? 'Rating (pts)' : 'Pts per 100 poss.', series: [{ name: 'Rating', data: path.map(function (x) { return [new Date(x[0] + (String(x[0]).length === 10 ? 'T12:00:00Z' : '')).getTime(), x[1]]; }), color: col, area: true, symbols: path.length < 25 }],
      yFmt: function (v) { return CC.signed(v, 1); }, xFmt: function (v) { return new Date(v).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }); }, xLabel: function (v) { return CC.date(new Date(v).toISOString()); }, ref: { y: 0 }, endLabels: false });
    if (rh.length > 1) QKC.line('#tp-rank', { x: rh.map(function (r) { return String(r[0]) === 'pre' ? 'Pre' : (String(r[0]) === 'final' ? 'Final' : 'Wk ' + r[0]); }), series: [{ name: 'AP', data: rh.map(function (r) { return isNum(r[1]) ? r[1] : null; }), color: QK.cssVar('--c-2'), symbols: true }, { name: 'Model', data: rh.map(function (r) { return isNum(r[2]) ? r[2] : null; }), color: QK.cssVar('--c-1'), symbols: true }],
      yInverse: true, yMin: 1, yInterval: (function () { var v = []; rh.forEach(function (r) { if (isNum(r[1])) v.push(r[1]); if (isNum(r[2])) v.push(r[2]); }); var span = v.length ? Math.max.apply(null, v) - 1 : 5; return Math.max(1, Math.ceil(span / 6)); })(),
      yFmt: function (v) { return '#' + Math.round(v); }, legend: true, endLabels: false, xName: 'Week', yName: 'Rank' });
    if (CC.isCur(L, S) && sim && sim.w_dist && QK.$('#tp-wd', el)) QKC.bar('#tp-wd', { cats: sim.w_dist.map(function (x, i) { return String(i); }), series: [{ name: 'Share', data: sim.w_dist }], catName: 'Regular-season wins', valName: 'Share of seasons', fmt: function (v) { return CC.pct(v); }, colors: sim.w_dist.map(function () { return col || QK.cssVar('--c-1'); }) });
    if (CC.isCur(L, S) && sim && sim.seed_dist && QK.$('#tp-sd', el)) { var ks = Object.keys(sim.seed_dist).sort(function (x, y) { return x - y; }); QKC.bar('#tp-sd', { cats: ks.map(function (k) { return 'Seed ' + k; }), series: [{ name: 'Share', data: ks.map(function (k) { return sim.seed_dist[k]; }) }], catName: 'Seed', valName: 'Share of seasons', fmt: function (v) { return CC.pct(v); } }); }
  });
});
function swList(d) {
  if (!d) return '';
  function li(u, good) { return '<li>' + CC.ui.grade(u.grade) + '<span><b>' + esc(u.unit) + '</b> <span class="qk-muted">' + esc(u.evidence || '') + '</span></span></li>'; }
  return '<div class="cc-mini-h">Strengths</div><ul class="cc-list cc-sw">' + (d.strengths || []).map(function (u) { return li(u, true); }).join('') + '</ul><div class="cc-mini-h">Needs</div><ul class="cc-list cc-sw">' + (d.needs || []).map(function (u) { return li(u, false); }).join('') + '</ul>';
}

})(window.CC);
