/* The Quant Campus — the race on Standings (#/<L>/standings?tab=race). The Team cards moved to the Teams page (round 9:
 * cc-teamspage.js, strengths and weaknesses and the style map).
 *
 *   Race (current season): how the playoff / tournament, title and conference races are shaping up.
 *     - the forecast lines (538 style) from <L>/race_log.json, one snapshot a day ("tracking since" its first day);
 *       until a second day exists, today's chances as bars;
 *     - the season so far: each contender's rating, week by week (season.json rating_paths);
 *     - who moved this week, with the reason we can attribute (their last result and our chance before it);
 *     - the CFP picture (in / bubble / chasing, with the projected seed) or the NCAA seeding race;
 *     - locks and lines: bowl eligibility clinched or ruled out (arithmetic), and what happened in every or none of
 *       our simulated seasons (never called "clinched" unless it is arithmetic);
 *     - what's at stake next: each side's chance if it wins and if it loses, from the same simulated seasons
 *       (season.json sim.stakes; football), or the games between undecided teams (basketball);
 *     - the road left: remaining schedule strength from our ratings (sim.teams[t].sos_rem);
 *     - tiers.
 * Reads <L>/<S>/season.json, schedule.json, cfp.json | bracket.json and <L>/race_log.json. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;
var POWER = { cfb: ['SEC', 'Big Ten', 'Big 12', 'ACC'], mbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'], wbb: ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East'] };
var DAY = 86400000;

function confOrder(L, season) {
  var pw = POWER[L] || [];
  return Object.keys(season.standings || {}).sort(function (a, b) {
    var na = CC.cname(L, a), nb = CC.cname(L, b), ia = pw.indexOf(na), ib = pw.indexOf(nb);
    if (ia < 0) ia = 99; if (ib < 0) ib = 99;
    return ia - ib || na.localeCompare(nb);
  });
}
function recs(season) {
  var out = {};
  Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { out[String(r.team)] = r; }); });
  return out;
}
function pp(v) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(Math.round(v * 100)) + ' pts' : '—'; }
function dayLabel(d) { return CC.date(d + 'T12:00:00Z'); }
function sims(season) { return (season.sim && season.sim.n_sims) || 0; }
function simTeams(season) { return (season.sim && season.sim.teams) || {}; }
function playoffKey(L) { return CC.fb(L) ? 'p_cfp' : 'p_ncaa'; }
function confKey(L) { return CC.fb(L) ? 'p_conf' : 'p_conf_reg'; }
function playoffName(L) { return CC.fb(L) ? 'CFP' : 'NCAA tournament'; }
function teamRow(L, S, t, sub, v) {
  return '<li>' + U.teamEnt(L, t, { season: S, sub: sub || '' }) + (v ? '<span class="v">' + v + '</span>' : '') + '</li>';
}
function segHTML(id, opts, active, label) {
  return '<div class="qk-seg cc-rc-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label) + '">' + opts.map(function (o) {
    return '<button type="button" data-value="' + esc(o[0]) + '" aria-pressed="' + (o[0] === active) + '">' + esc(o[1]) + '</button>'; }).join('') + '</div>';
}
/* the latest snapshot ~days before the newest one in a race_log metric, or null */
function logDays(m) { return Object.keys(m || {}).filter(function (d) { return d.length === 10; }).sort(); }

/* ── last result per team (schedule cards, finished, newest first) ───────── */
function lastGames(cards) {
  var out = {};
  (cards || []).filter(function (c) { return c.status === 'post' && c.stype !== 'pre' && c.stype !== 'exh' && isNum(c.hs) && isNum(c.as); })
    .sort(function (a, b) { return String(b.date).localeCompare(String(a.date)); })
    .forEach(function (c) { [['home', 'away'], ['away', 'home']].forEach(function (s) { var t = String(c[s[0]]); if (!out[t]) out[t] = { c: c, side: s[0], opp: String(c[s[1]]) }; }); });
  return out;
}
function resultLine(L, S, g, now) {
  if (!g) return 'No game yet';
  var c = g.c, home = g.side === 'home';
  var us = home ? c.hs : c.as, them = home ? c.as : c.hs, won = us > them;
  var ph = c.model && isNum(c.model.p_home) ? (home ? c.model.p_home : 1 - c.model.p_home) : null;
  var rk = home ? c.ar : c.hr;
  var old = now - new Date(c.date).getTime() > 9 * DAY;
  return (old ? 'Idle this week; last: ' : '') + (won ? 'Beat ' : 'Lost to ') + (isNum(rk) && rk <= 25 ? '#' + rk + ' ' : '') + esc(CC.tshort(L, g.opp)) + ' ' + us + '–' + them +
    (isNum(ph) ? ' · we gave them ' + CC.pct(ph) : '');
}

/* ── Race ─────────────────────────────────────────────────────────────── */
CC.raceTab = function (node, L, S, season, x) {
  var fb = CC.fb(L), sim = simTeams(season), n = sims(season), R = recs(season);
  var log = (x.log && x.log[String(S)]) || {};
  var cards = (x.sched && x.sched.games) || [];
  var now = QK.now ? QK.now() : Date.now();
  var pk = playoffKey(L), ck = confKey(L);
  var ts = Object.keys(sim);
  if (!ts.length) { node.innerHTML = QK.empty('The race starts once the season simulation has run', 'Our simulated seasons appear after the first build of the season.'); return; }
  var html = '';
  /* KPIs */
  var byP = ts.slice().sort(function (a, b) { return (sim[b][pk] || 0) - (sim[a][pk] || 0); });
  var byT = ts.slice().sort(function (a, b) { return (sim[b].p_title || 0) - (sim[a].p_title || 0); });
  var lock = ts.filter(function (t) { return (sim[t][pk] || 0) >= 0.99; }).length;
  var bub = ts.filter(function (t) { var p = sim[t][pk] || 0; return p >= 0.25 && p <= 0.75; }).length;
  var alive = ts.filter(function (t) { return (sim[t][pk] || 0) >= 0.01; }).length;
  var fav = byT[0];
  html += U.stats([
    { label: 'Title favourite', value: CC.tshort(L, fav), text: true, signal: true, sub: CC.pct(sim[fav].p_title) + ' of our simulated seasons' },
    { label: fb ? 'CFP: 99%+' : 'NCAA: 99%+', value: String(lock), unit: 'teams', sub: 'in the field in at least 99% of sims' },
    { label: 'On the bubble', value: String(bub), unit: 'teams', sub: '25% to 75% to make the ' + (fb ? 'CFP' : 'field') },
    { label: 'Still alive', value: String(alive), unit: 'teams', sub: 'at least a 1% ' + (fb ? 'CFP' : 'tournament') + ' chance' }]);

  /* forecast lines */
  var cs = confOrder(L, season);
  var metrics = [[pk, fb ? 'CFP' : 'NCAA field'], ['p_title', 'National title'], [ck, fb ? 'Conference title' : 'Conference (regular season)']];
  var confSel = '<label class="cc-rc-sel" id="rc-confwrap" hidden><span>Conference</span><select id="rc-conf">' + cs.map(function (c) { return '<option value="' + esc(c) + '">' + esc(CC.cname(L, c)) + '</option>'; }).join('') + '</select></label>';
  var days = logDays(log[pk]);
  html += U.section('How the race is shaping up', 'Our chances after each day’s simulations' + (days.length ? ' · tracking since ' + esc(dayLabel(days[0])) : '') + '. Each line is one team; the newest point is today.',
    '<div class="cc-rc-ctl">' + segHTML('rc-metric', metrics, pk, 'Which race') + confSel + '</div>' + '<div id="rc-lines"></div>', '', fb ? 'Playoff race' : 'Tournament race');

  /* the season so far: rating paths */
  var paths = season.rating_paths || {};
  var top = (season.power || []).slice(0, 8).map(function (r) { return String(r.team); }).filter(function (t) { return (paths[t] || []).length > 1; });
  if (top.length) html += U.section('The season so far', 'Our rating of today’s top eight, week by week: ' + (fb ? 'points better than an average FBS team on a neutral field.' : 'adjusted margin per 100 possessions.'), U.chart('rc-paths', 300, 'Ratings over the season'), '', 'Form');

  /* who moved */
  html += '<div id="rc-moved"></div>';
  /* picture */
  html += '<div id="rc-bubble"></div><div id="rc-picture"></div>';
  /* stakes */
  html += '<div id="rc-stakes"></div>';
  /* locks and lines, road left, tiers */
  html += '<div id="rc-sos"></div><div class="qk-grid cc-grid"><div class="qk-span-6" id="rc-locks"></div><div class="qk-span-6" id="rc-road"></div></div>';
  html += '<div id="rc-tiers"></div>';
  node.innerHTML = html;

  /* lines */
  var cur = { m: pk, c: cs[0] };
  function drawLines() {
    var box = QK.$('#rc-lines', node);
    var m = cur.m, lm = log[m] || {}, dd = logDays(lm);
    QK.$('#rc-confwrap', node).hidden = m !== ck;
    var pool = ts.filter(function (t) { return m !== ck || String((CC.team(L, t) || {}).conference) === String(cur.c); });
    var rank = pool.slice().sort(function (a, b) { return (sim[b][m] || 0) - (sim[a][m] || 0); }).filter(function (t) { return (sim[t][m] || 0) >= 0.005; }).slice(0, m === ck ? 6 : 8);
    if (!rank.length) { box.innerHTML = QK.empty('Nobody has a chance above half a percent', ''); return; }
    var note = '';
    if (dd.length < 2) {
      note = U.note(dd.length ? 'Tracking since ' + esc(dayLabel(dd[0])) + ': the lines start once a second day is logged. Today’s chances:' : 'The daily log starts with the next build. Today’s chances:');
      box.innerHTML = note + QK.chances(rank.map(function (t) { return { label: CC.tshort(L, t), p: sim[t][m], mark: U.mark(L, t), href: CC.teamHref(L, t, S) }; }), { oursName: 'Our chance, from ' + QK.fmt.num(n, 0) + ' simulated seasons' });
      return;
    }
    box.innerHTML = U.chart('rc-fc', 340, 'Chances over time');
    QKC.forecast(QK.$('#rc-fc', node), {
      x: dd.map(function (d) { return d + 'T12:00:00Z'; }), xType: 'time', xName: 'Date', yName: 'Chance',
      series: rank.map(function (t, i) { return { name: CC.tshort(L, t), label: CC.tabbr(L, t), color: CC.lineColours(L, rank)[i], data: dd.map(function (d) { var v = (lm[d] || {})[t]; return isNum(v) ? v : (m === ck ? null : 0); }) }; }),
      today: dd[dd.length - 1] + 'T12:00:00Z', label: 'Chances over time'
    });
  }
  QK.seg(QK.$('#rc-metric', node), function (v) { cur.m = v; drawLines(); });
  QK.$('#rc-conf', node).addEventListener('change', function (e) { cur.c = e.target.value; drawLines(); });
  drawLines();

  if (top.length) {
    var dates = {};
    top.forEach(function (t) { paths[t].forEach(function (p) { dates[p[0]] = 1; }); });
    var xs = Object.keys(dates).sort();
    QKC.line(QK.$('#rc-paths', node), {
      x: xs.map(function (d) { return CC.date(d + 'T12:00:00Z'); }), xName: 'Week of',
      yName: fb ? 'Rating (points v average FBS)' : 'Rating (per 100 possessions)', yScale: true,
      yFmt: function (v) { return CC.signed(v, 1); },
      series: top.map(function (t, i) { var m = {}; paths[t].forEach(function (p) { m[p[0]] = p[1]; }); return { name: CC.tshort(L, t), label: CC.tabbr(L, t), color: CC.lineColours(L, top)[i], symbols: true, data: xs.map(function (d) { return isNum(m[d]) ? m[d] : null; }) }; }),
      label: 'Ratings over the season'
    });
  }

  /* who moved this week */
  (function () {
    var last = lastGames(cards), rows = [], basis;
    var dd = logDays(log[pk]);
    if (dd.length >= 2) {
      var newest = dd[dd.length - 1], target = new Date(newest + 'T12:00:00Z').getTime() - 7 * DAY;
      var since = dd.slice(0, -1).sort(function (a, b) { return Math.abs(new Date(a + 'T12:00:00Z').getTime() - target) - Math.abs(new Date(b + 'T12:00:00Z').getTime() - target); })[0];
      var a = log[pk][since] || {};
      ts.forEach(function (t) { var p = sim[t][pk] || 0, b = isNum(a[t]) ? a[t] : 0; if (Math.abs(p - b) >= 0.02) rows.push({ t: t, d: p - b, v: CC.pct(b) + ' → ' + CC.pct(p) }); });
      basis = 'Change in our ' + playoffName(L) + ' chance since ' + esc(dayLabel(since)) + ', with the result behind it.';
      rows.forEach(function (r) { r.txt = pp(r.d); });
    } else {
      ts.forEach(function (t) {
        var p = paths[t] || [];
        if (p.length < 2 || !isNum(p[p.length - 1][1]) || !isNum(p[p.length - 2][1])) return;
        var d = p[p.length - 1][1] - p[p.length - 2][1];
        if (Math.abs(d) >= 1 && ((R[t] || {}).rating_rank <= 60 || (sim[t][pk] || 0) >= 0.02)) rows.push({ t: t, d: d, txt: CC.signed(d, 1), v: CC.signed(p[p.length - 2][1], 1) + ' → ' + CC.signed(p[p.length - 1][1], 1) });
      });
      basis = 'Our ' + playoffName(L) + ' chances are logged daily from ' + (dd.length ? esc(dayLabel(dd[0])) : 'the next build') + '; until a week is logged, this is the change in our rating since last week' + (fb ? ' (points v an average FBS team)' : '') + ', among teams in the national picture.';
    }
    if (!rows.length) { QK.$('#rc-moved', node).innerHTML = ''; return; }
    var up = rows.filter(function (r) { return r.d > 0; }).sort(function (a, b) { return b.d - a.d; }).slice(0, 5);
    var dn = rows.filter(function (r) { return r.d < 0; }).sort(function (a, b) { return a.d - b.d; }).slice(0, 5);
    function list(rs, cls) {
      return rs.length ? '<ul class="cc-list cc-rc-moves">' + rs.map(function (r) {
        return '<li>' + U.teamEnt(L, r.t, { season: S }) + '<span class="v cc-mv ' + cls + '">' + esc(r.txt) + '</span><span class="cc-rc-why">' + resultLine(L, S, last[r.t], now) + ' · ' + esc(r.v) + '</span></li>'; }).join('') + '</ul>' : QK.empty('Nobody', '');
    }
    QK.$('#rc-moved', node).innerHTML = U.section('Who moved this week', basis,
      '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Rising', '', list(up, 'pos')) + '</div><div class="qk-span-6">' + U.card('Falling', '', list(dn, 'neg')) + '</div></div>', '', 'Movers');
  })();

  /* round 9, Phase 4: the bubble watch: every team still in the balance for the field, its chance as a bar against the
     coin-flip line, the teams just in above it and just out below */
  (function () {
    var box = QK.$('#rc-bubble', node);
    var lo = fb ? 0.1 : 0.15, hi = fb ? 0.9 : 0.85;
    var bt = byP.filter(function (t) { var p = sim[t][pk] || 0; return p >= lo && p <= hi; }).slice(0, 24);
    if (!box || bt.length < 3) return;
    box.innerHTML = U.section('Bubble watch', 'Every team between ' + CC.pct(lo, 0) + ' and ' + CC.pct(hi, 0) + ' to make the ' + (fb ? '12-team playoff' : 'field of 68') + ', from our simulated seasons. Above the 50% line we have them in more often than out; the further from it, the safer.',
      U.card('', '', U.chart('rc-bub', Math.max(280, bt.length * 24 + 60), 'Bubble watch')), '', 'On the bubble');
    QKC.bar(QK.$('#rc-bub', node), { cats: bt.map(function (t) { var r = R[t] || {}; return CC.tshort(L, t) + ' ' + CC.record(r.w, r.l); }), horizontal: true, diverging: true, labels: true, min: -0.5, max: 0.5,
      fmt: function (v) { return CC.pct(v + 0.5, 0); }, series: [{ name: (fb ? 'Playoff' : 'NCAA') + ' chance, against 50%', data: bt.map(function (t) { return (sim[t][pk] || 0) - 0.5; }) }],
      hrefs: bt.map(function (t) { return CC.teamHref(L, t, S); }), labelWidth: 150, valName: 'Our chance to make the ' + (fb ? 'playoff' : 'field') + ' (the centre line is 50%)', catName: 'Team',
      valTicks: { values: [-0.5, -0.25, 0, 0.25, 0.5], labels: ['0%', '25%', '50%', '75%', '100%'] } });
  })();

  /* the CFP picture / the NCAA seeding race */
  (function () {
    var box = QK.$('#rc-picture', node), post = x.post;
    if (fb) {
      var seedOf = {};
      ((post && post.projected_bracket && post.projected_bracket.seeds) || []).forEach(function (s0) { seedOf[String(s0.team)] = s0; });
      var groups = [['In', 'At least 75% to make the field', function (p) { return p >= 0.75; }], ['On the bubble', '25% to 75%', function (p) { return p >= 0.25 && p < 0.75; }], ['Chasing', '5% to 25%', function (p) { return p >= 0.05 && p < 0.25; }]];
      var cols = groups.map(function (g) {
        var tt = byP.filter(function (t) { return g[2](sim[t].p_cfp || 0); });
        return '<div class="qk-span-4">' + U.card(g[0] + ' (' + tt.length + ')', g[1], tt.length ? '<ul class="cc-list">' + tt.map(function (t) {
          var r = R[t] || {}, sd = seedOf[t], sm = sim[t].seed_mean;
          var sub = CC.record(r.w, r.l) + (sd ? ' · projected ' + sd.seed + ' seed' + (sd.auto ? ' (auto bid)' : '') : (isNum(sm) ? ' · seed ' + CC.f(sm, 1) + ' on average when in' : ''));
          return teamRow(L, S, t, sub, CC.pct(sim[t].p_cfp));
        }).join('') + '</ul>' : QK.empty('Nobody yet', '')) + '</div>';
      }).join('');
      box.innerHTML = U.section('The CFP picture', 'Twelve places: five conference champions and seven at-large teams, seeded by the committee. Our chance of each team making it; the projected seed is our most likely field' + (post && post.format && post.format.verified === false ? ' (format assumed as last season)' : '') + '. ' + U.link(CC.href(L, 'standings', null, S, 'tab=playoff'), 'The bracket and every round'), '<div class="qk-grid cc-grid">' + cols + '</div>', '', 'Who’s in?');
    } else {
      var seeds = ts.filter(function (t) { return (sim[t].p_ncaa || 0) >= 0.3 && isNum(sim[t].seed_mean); }).sort(function (a, b) { return sim[a].seed_mean - sim[b].seed_mean; }).slice(0, 16);
      var bubble = byP.filter(function (t) { var p = sim[t].p_ncaa || 0; return p >= 0.3 && p <= 0.7; }).slice(0, 16);
      var sd1 = function (t) { var d = sim[t].seed_dist || {}; return d['1'] || 0; };
      var top4 = function (t) { var d = sim[t].seed_dist || {}; return (d['1'] || 0) + (d['2'] || 0) + (d['3'] || 0) + (d['4'] || 0); };
      var tbl = seeds.length ? U.table(['Team', { label: 'Avg seed', align: 'right', title: 'Our average seed when in the field' }, { label: '1 seed', align: 'right' }, { label: 'Top 4', align: 'right' }, { label: 'In field', align: 'right' }], seeds.map(function (t) {
        return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, { v: sim[t].seed_mean, html: CC.f(sim[t].seed_mean, 1) }, U.heat(sd1(t)), U.heat(top4(t)), U.heat(sim[t].p_ncaa)];
      }), { sticky: false }) : QK.empty('No seeding race yet', '');
      var bl = bubble.length ? '<ul class="cc-list">' + bubble.map(function (t) { return teamRow(L, S, t, CC.cname(L, (CC.team(L, t) || {}).conference), CC.pct(sim[t].p_ncaa)); }).join('') + '</ul>' : QK.empty('Nobody on the bubble', '');
      var pre = (CC.info(L).phase === 'preseason');
      box.innerHTML = U.section('The seeding race', (pre ? 'Preseason: these chances come from last season’s ratings, regressed, until games are played. ' : '') + 'The top seed lines and the bubble of the 68-team field, from our simulated seasons. ' + U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'The projected bracket'),
        '<div class="qk-grid cc-grid"><div class="qk-span-7">' + U.card('Top seed lines', 'Teams by their average projected seed', tbl) + '</div><div class="qk-span-5">' + U.card('The bubble', '30% to 70% to make the field', bl) + '</div></div>', '', 'NCAA picture');
    }
  })();

  /* what's at stake next */
  (function () {
    var box = QK.$('#rc-stakes', node);
    var st = ((season.sim && season.sim.stakes) || []).filter(function (g) { var t = new Date(g.date).getTime(); return !isNum(t) || (t > now - 4 * 3600000 && t < now + 10 * DAY); }).slice(0, 10);
    if (st.length) {
      var rows = st.map(function (g) {
        var side = function (s) { var c = g.cfp[s]; return '<span class="cc-rc-ifs"><b>' + CC.pct(c[0]) + '</b> win · ' + CC.pct(c[1]) + ' loss</span>'; };
        var also = (g.others || []).map(function (o) { return esc(CC.tabbr(L, o.team)) + ' ' + pp(o.d); }).join(', ');
        return [{ html: '<div class="cc-rc-game"><a href="' + esc(CC.gameHref(L, g.game, S)) + '">' + esc(CC.tshort(L, g.away)) + ' at ' + esc(CC.tshort(L, g.home)) + '</a><span class="s">' + esc(CC.date(g.date, true)) + (also ? ' · if ' + esc(CC.tabbr(L, g.home)) + ' win: ' + also : '') + '</span></div>', v: g.swing },
          { v: g.swing, html: '<b class="num">' + CC.f(g.swing, 2) + '</b>' },
          { v: g.p_home, html: CC.pct(g.p_home) + ' ' + esc(CC.tabbr(L, g.home)) },
          { html: U.teamEnt(L, g.home, { season: S, abbr: true }) + side('home'), v: g.cfp.home[0] - g.cfp.home[1] },
          { html: U.teamEnt(L, g.away, { season: S, abbr: true }) + side('away'), v: g.cfp.away[0] - g.cfp.away[1] }];
      });
      box.innerHTML = U.section('What’s at stake next', 'The games that move the CFP race most, from the same ' + QK.fmt.num(n, 0) + ' simulated seasons split by result. <b>Swing</b>: the CFP places we expect the result to move (each team’s expected change in its CFP chance, added up and halved; changes within the simulations’ noise left out). Each side: its CFP chance if it wins, and if it loses.',
        U.card('', '', U.table(['Game', { label: 'Swing', align: 'right', title: 'CFP places we expect the result to move' }, { label: 'Our chance', align: 'right' }, 'Home side: CFP chance', 'Away side: CFP chance'], rows, { sticky: false })), '', 'Big games');
      return;
    }
    /* basketball (or no stakes field): upcoming games between teams whose chances are undecided */
    var up = cards.filter(function (c) { var t = new Date(c.date).getTime(); return c.status === 'pre' && t > now - 3600000 && t < now + 8 * DAY; }).map(function (c) {
      var a = sim[String(c.home)] || {}, b = sim[String(c.away)] || {}, pa = a[pk] || 0, pb = b[pk] || 0;
      return { c: c, s: 4 * pa * (1 - pa) + 4 * pb * (1 - pb), pa: pa, pb: pb };
    }).filter(function (r) { return r.s > 0.4; }).sort(function (a, b) { return b.s - a.s; }).slice(0, 10);
    if (!up.length) { box.innerHTML = U.section('What’s at stake next', 'Games between teams whose ' + playoffName(L) + ' chances are still undecided appear here in the week before they are played.', QK.empty('None in the next week', ''), '', 'Big games'); return; }
    box.innerHTML = U.section('What’s at stake next', 'The coming week’s games between teams whose ' + playoffName(L) + ' chances are most undecided (the closer both are to 50%, the higher). A guide to where the race can move, not a measured swing.',
      U.card('', '', U.table(['Game', { label: 'Our chance', align: 'right' }, { label: 'Home ' + (fb ? 'CFP' : 'NCAA'), align: 'right' }, { label: 'Away ' + (fb ? 'CFP' : 'NCAA'), align: 'right' }], up.map(function (r) {
        var c = r.c, ph = c.model && c.model.p_home;
        return [{ html: '<div class="cc-rc-game"><a href="' + esc(CC.gameHref(L, c.id, S)) + '">' + esc(CC.tshort(L, c.away)) + ' at ' + esc(CC.tshort(L, c.home)) + '</a><span class="s">' + esc(CC.when(c)) + '</span></div>', v: r.s },
          { v: ph, html: isNum(ph) ? CC.pct(ph) + ' ' + esc(CC.tabbr(L, c.home)) : '—' }, U.heat(r.pa), U.heat(r.pb)];
      }), { sticky: false })), '', 'Big games');
  })();

  /* locks and lines */
  (function () {
    var box = QK.$('#rc-locks', node), out = '';
    var ns = n ? QK.fmt.num(n, 0) : 'our';
    if (fb) {
      var clinched = [], gone = [], need = [];
      ts.forEach(function (t) {
        var r = R[t] || {}, s0 = sim[t];
        if (!isNum(r.w)) return;
        var left = isNum(s0.n_rem) ? s0.n_rem + (s0.p_conf_game > 0 ? 1 : 0) : null;
        if (r.w >= 6) clinched.push(t);
        else if (isNum(left) && r.w + left < 6) gone.push(t);
        else if (isNum(left) && left > 0 && s0.p_bowl > 0.05 && s0.p_bowl < 0.95) need.push({ t: t, k: 6 - r.w, left: left });
      });
      need.sort(function (a, b) { return (b.k / b.left) - (a.k / a.left); });
      out += U.card('Bowl eligibility: the arithmetic', '<b>' + clinched.length + '</b> teams have six wins (eligible; the 5–7 exception aside) and <b>' + gone.length + '</b> can no longer reach six with the games they have left' + (gone.length ? ': ' + gone.map(function (t) { return esc(CC.tshort(L, t)); }).join(', ') : '') + '.',
        need.length ? '<ul class="cc-list">' + need.slice(0, 8).map(function (r) { return teamRow(L, S, r.t, 'needs ' + r.k + ' win' + (r.k === 1 ? '' : 's') + ' from ' + r.left + ' left', CC.pct(sim[r.t].p_bowl)); }).join('') + '</ul>' : '');
      var every = ts.filter(function (t) { return (sim[t].p_cfp || 0) >= 1; }), none = ts.filter(function (t) { return (sim[t].p_cfp || 0) <= 0 && (R[t] || {}).rank; });
      var confAlive = cs.map(function (c) { var tt = ts.filter(function (t) { return String((CC.team(L, t) || {}).conference) === String(c) && (sim[t].p_conf || 0) > 0; }); return { c: c, n: tt.length, lead: tt.sort(function (a, b) { return sim[b].p_conf - sim[a].p_conf; })[0] }; }).filter(function (r) { return r.n; });
      out += U.card('Locks and long shots', 'From ' + ns + ' simulated seasons. Nothing here is mathematically settled: “every” and “none” are our simulations, not the arithmetic.',
        '<ul class="cc-list">' + (every.length ? '<li><b>In the CFP in every simulation:</b>&nbsp;' + every.map(function (t) { return esc(CC.tshort(L, t)); }).join(', ') + '</li>' : '<li>No team makes the CFP in every simulation yet.</li>') +
        (none.length ? '<li><b>Ranked, but in no simulated CFP field:</b>&nbsp;' + none.map(function (t) { return esc(CC.tshort(L, t)); }).join(', ') + '</li>' : '') +
        confAlive.map(function (r) { return '<li><span>' + esc(CC.cname(L, r.c)) + ': <b>' + r.n + '</b> team' + (r.n === 1 ? '' : 's') + ' win the title in at least one simulation</span><span class="v">' + esc(CC.tabbr(L, r.lead)) + ' ' + CC.pct(sim[r.lead].p_conf) + '</span></li>'; }).join('') + '</ul>');
    } else {
      var locks = byP.filter(function (t) { return (sim[t].p_ncaa || 0) >= 0.99; });
      var crown = cs.map(function (c) { var tt = ts.filter(function (t) { return String((CC.team(L, t) || {}).conference) === String(c); }).sort(function (a, b) { return (sim[b].p_conf_reg || 0) - (sim[a].p_conf_reg || 0); }); return { c: c, lead: tt[0], n: tt.filter(function (t) { return (sim[t].p_conf_reg || 0) > 0; }).length }; }).filter(function (r) { return r.lead; });
      out += U.card('Locks and long shots', 'From ' + ns + ' simulated seasons; nothing here is mathematically settled.',
        '<ul class="cc-list">' + (locks.length ? '<li><b>In the field in 99%+ of simulations:</b>&nbsp;' + locks.map(function (t) { return esc(CC.tshort(L, t)); }).join(', ') + '</li>' : '<li>No team is in the field in 99% of simulations yet.</li>') +
        crown.slice(0, 12).map(function (r) { return '<li><span>' + esc(CC.cname(L, r.c)) + ': <b>' + r.n + '</b> can win the regular season</span><span class="v">' + esc(CC.tabbr(L, r.lead)) + ' ' + CC.pct(sim[r.lead].p_conf_reg) + '</span></li>'; }).join('') + '</ul>');
    }
    box.innerHTML = out;
  })();

  /* road left */
  (function () {
    var box = QK.$('#rc-road', node);
    var withRem = ts.filter(function (t) { return isNum(sim[t].sos_rem) && sim[t].n_rem > 0; });
    if (!withRem.length) { box.innerHTML = U.card('The road left', '', QK.empty('Remaining schedule strength appears with the next build', 'It needs the season simulation’s remaining games.')); return; }
    var order = withRem.slice().sort(function (a, b) { return sim[b].sos_rem - sim[a].sos_rem; }), rk = {};
    order.forEach(function (t, i) { rk[t] = i + 1; });
    var cont = byP.filter(function (t) { return (sim[t][pk] || 0) >= 0.03 && isNum(sim[t].sos_rem); }).slice(0, 16);
    /* round 9, Phase 4: remaining schedule strength as a chart, the contenders from toughest road to easiest */
    var sb = QK.$('#rc-sos', node), cs0 = cont.slice().sort(function (a, b) { return sim[b].sos_rem - sim[a].sos_rem; });
    if (sb && cs0.length >= 3) {
      sb.innerHTML = U.section('The road left', 'How hard the rest of the regular season is for each contender: the average rating of the opponents still to play, the toughest at the top. ' + (fb ? 'A point is a point better than an average FBS team.' : 'Points per 100 possessions against an average team.'),
        U.card('', '', U.chart('rc-sos-c', Math.max(260, cs0.length * 26 + 60), 'Remaining schedule strength of the contenders')), '', 'Schedule strength');
      QKC.bar(QK.$('#rc-sos-c', node), { cats: cs0.map(function (t) { return CC.tshort(L, t) + ' (' + sim[t].n_rem + ' left)'; }), horizontal: true, labels: true, fmt: function (v) { return CC.signed(v, 1); },
        series: [{ name: 'Average opponent rating', data: cs0.map(function (t) { return sim[t].sos_rem; }) }], colors: cs0.map(function (t) { return CC.tcol(L, t); }), hrefs: cs0.map(function (t) { return CC.teamHref(L, t, S); }), labelWidth: 150,
        valName: 'Average rating of the opponents left (' + (fb ? 'points' : 'per 100') + ')', catName: 'Contender' });
    }
    box.innerHTML = U.card('The road left', 'Contenders’ remaining regular-season schedules: the average rating of the opponents still to play (' + (fb ? 'points v an average FBS team' : 'per 100 possessions') + '), ranked 1 = toughest of ' + withRem.length + '.',
      U.table(['Team', { label: 'Left', align: 'right' }, { label: 'Opp. rating', align: 'right' }, { label: 'Rank', align: 'right', title: '1 = toughest remaining schedule' }, { label: 'Exp. wins left', align: 'right', title: 'Expected wins in the rest of the season, from our simulations' }], cont.map(function (t) {
        var r = R[t] || {}, s0 = sim[t];
        return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, s0.n_rem, { v: s0.sos_rem, html: CC.signed(s0.sos_rem, 1) }, rk[t], { v: s0.exp_w - (r.w || 0), html: isNum(s0.exp_w) && isNum(r.w) ? CC.f(s0.exp_w - r.w, 1) : '—' }];
      }), { sticky: false }));
  })();

  /* tiers */
  (function () {
    var tiers = fb ? [['Title contenders', 'At least a 5% national title chance', function (s0) { return (s0.p_title || 0) >= 0.05; }],
      ['Playoff contenders', '25%+ to make the CFP', function (s0) { return (s0.p_title || 0) < 0.05 && (s0.p_cfp || 0) >= 0.25; }],
      ['In the hunt', '5% to 25% to make the CFP', function (s0) { return (s0.p_cfp || 0) >= 0.05 && (s0.p_cfp || 0) < 0.25 && (s0.p_title || 0) < 0.05; }],
      ['Bowl bubble', '5% to 95% to reach six wins', function (s0) { return (s0.p_bowl || 0) > 0.05 && (s0.p_bowl || 0) < 0.95 && (s0.p_cfp || 0) < 0.05; }]]
      : [['Title contenders', 'At least a 3% title chance', function (s0) { return (s0.p_title || 0) >= 0.03; }],
      ['Tournament locks', '90%+ to make the field', function (s0) { return (s0.p_title || 0) < 0.03 && (s0.p_ncaa || 0) >= 0.9; }],
      ['The bubble', '25% to 90% to make the field', function (s0) { return (s0.p_ncaa || 0) >= 0.25 && (s0.p_ncaa || 0) < 0.9 && (s0.p_title || 0) < 0.03; }],
      ['Long shots', '5% to 25%', function (s0) { return (s0.p_ncaa || 0) >= 0.05 && (s0.p_ncaa || 0) < 0.25; }]];
    var html2 = '<div class="cc-auto">' + tiers.map(function (tr) {
      var tt = byP.filter(function (t) { return tr[2](sim[t]); });
      var shown = tt.slice(0, 18);
      return U.card(tr[0] + ' (' + tt.length + ')', tr[1], tt.length ? '<div class="cc-rc-tier">' + shown.map(function (t) { return U.teamEnt(L, t, { season: S, sub: CC.pct(sim[t][tr[0] === 'Title contenders' ? 'p_title' : (tr[0] === 'Bowl bubble' ? 'p_bowl' : pk)]) }); }).join('') + (tt.length > shown.length ? '<span class="qk-muted">and ' + (tt.length - shown.length) + ' more</span>' : '') + '</div>' : QK.empty('Nobody', ''));
    }).join('') + '</div>';
    QK.$('#rc-tiers', node).innerHTML = U.section('Tiers', 'Every team placed by our chances. A team sits in its highest tier only.', html2, '', 'Shape of the race');
  })();
};

})(window.CC);
