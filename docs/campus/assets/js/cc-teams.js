/* The Quant Campus — Teams (#/<L>/teams) and the team page (#/<L>/team/<tid>), Design System 2.0.
 * Catalogue: every member team as a leaderboard (heat cells: the national percentile of each metric), conference
 * filter, search, and an offense-v-defense map.
 * Team page: a card header in the team colour (record, rating, rank, conference), stat tiles (our rating first, with
 * its standard error and national percentile; projected wins and the season chances), the rating through the season,
 * AP v our rank, a percentile card against every team in the country, the schedule with our win chance, the roster
 * with value, strengths and needs, who moves next (movement payload, when published), inferred transfers in and out,
 * top performers (overall and by position, against the level), and the final-wins and seed distributions.
 * Reads <L>/<S>/teams.json, <L>/<S>/teams/<tid>.json, <L>/<S>/season.json. */
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

CC.route('teams', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  el.innerHTML = U.head('Teams', '', U.kicker(L, S)) + QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'teams.json')), CC.season(L, S), CC.metrics()]).then(function (a) {
    if (!U.alive(el)) return;
    var cat = a[0];
    if (!CC.ok(cat)) { el.innerHTML = U.head('Teams', '', U.kicker(L, S)) + U.missing('The team catalogue', cat); return; }
    /* the spec's team headline set (METRICS_SPEC.md) where the catalogue lists it; else the catalogue's first eight */
    var G = CC.group(L, 'team'), byKey = {};
    (cat.metrics || []).forEach(function (m) { byKey[m.key] = m; });
    var hs = G ? G.m.filter(function (m) { return m.set === 'h' && byKey[m.id]; }).map(function (m) { return Object.assign({}, byKey[m.id], { label: m.d || byKey[m.id].label, desc: m.x || byKey[m.id].desc, style: !!m.style }); }) : [];
    var mets = hs.length >= 4 ? hs : (cat.metrics || []).slice(0, 8);
    var T = cat.teams || {};
    var ids = Object.keys(T);
    var confs = {};
    ids.forEach(function (t) { if (T[t].conference) confs[T[t].conference] = 1; });
    var conf = (p.query || {}).conf || '';
    var opts = '<option value="">All conferences</option>' + Object.keys(confs).sort(function (x, y) { return CC.cname(L, x).localeCompare(CC.cname(L, y)); }).map(function (c) { return '<option value="' + esc(c) + '"' + (c === conf ? ' selected' : '') + '>' + esc(CC.cname(L, c)) + '</option>'; }).join('');
    el.innerHTML = U.head('Teams', esc(ids.length + (fb ? ' FBS teams' : ' Division I teams')) + ': our ratings, efficiency and schedule strength. Each cell is coloured by its national percentile (blue low, red high; flipped where lower is better).', U.kicker(L, S)) +
      '<div class="cc-toolbar"><input class="qk-input" type="search" id="tm-q" placeholder="Find a team" aria-label="Find a team"><select class="qk-select" id="tm-conf" aria-label="Conference">' + opts + '</select></div>' +
      '<div class="qk-grid cc-grid"><div class="qk-span-8">' + U.card('Every team', '<span id="tm-n"></span>', U.lb('tm-table'), { flush: true }) + '</div><div class="qk-span-4" id="tm-map"></div></div>';
    var FL = flatKeys(cat);
    var ox = mets.filter(function (m) { return m.key === 'off'; })[0], dx = mets.filter(function (m) { return m.key === 'def'; })[0];
    function rows() {
      var q = (QK.$('#tm-q', el).value || '').toLowerCase(), c = QK.$('#tm-conf', el).value;
      return ids.filter(function (t) { return (!c || String(T[t].conference) === c) && (!q || String(T[t].name || '').toLowerCase().indexOf(q) >= 0); });
    }
    function paint() {
      var rs = rows().sort(function (x, y) { return (T[x].rating_rank || 999) - (T[y].rating_rank || 999); });
      QK.$('#tm-n', el).textContent = rs.length + ' teams · ranked by our rating';
      var data = rs.map(function (t) {
        var x = T[t], o = { team: t, name: x.name, rank: x.rating_rank, conf: CC.cname(L, x.conference), wl: (x.w || 0) - (x.l || 0), rec: CC.record(x.w, x.l) };
        mets.forEach(function (m) { o[m.key] = (x.values || {})[m.key]; o['p_' + m.key] = FL[m.key] ? null : (x.pct || {})[m.key]; });
        return o;
      });
      QK.leaderboard(QK.$('#tm-table', el), { dense: true, maxHeight: 720, rowHref: function (r) { return CC.teamHref(L, r.team, S); }, columns: [
        { key: 'rank', label: 'Rk', num: true, tip: 'Our national rank' },
        { key: 'name', label: 'Team', type: 'entity', sub: 'conf', mark: function (r) { return U.mark(L, r.team); }, href: function (r) { return CC.teamHref(L, r.team, S); } },
        { key: 'wl', label: 'W–L', num: true, fmt: function (v, r) { return esc(r.rec); } }
      ].concat(mets.map(function (m) { return { key: m.key, label: m.label, type: 'pctl', pctl: 'p_' + m.key, style: !!m.style, tip: (m.desc || m.label) + (m.lower ? ' (lower is better; the colour is flipped)' : '') + (m.style ? ' (style: shown in grey)' : ''), fmt: function (v) { return CC.fmtMetric(m, v); } }; })), rows: data });
      if (ox && dx) {
        QK.$('#tm-map', el).innerHTML = U.card('Offense v defense', 'Up and right is better on both sides of the ball.', U.chart('tm-sc', 420, 'Offense against defense, every team shown'));
        QKC.scatter('#tm-sc', { points: rs.map(function (t) { var v = T[t].values || {}; return { x: v.off, y: v.def, name: T[t].name, label: CC.tabbr(L, t), color: CC.tcol(L, t), href: CC.teamHref(L, t, S), size: 9 }; }).filter(function (q) { return isNum(q.x) && isNum(q.y); }),
          xName: ox.label, yName: dx.label, yInverse: !!dx.lower, labelTop: 8, xFmt: function (v) { return CC.f(v, 0); }, yFmt: function (v) { return CC.f(v, 0); } });
      }
    }
    QK.$('#tm-q', el).addEventListener('input', paint);
    QK.$('#tm-conf', el).addEventListener('change', paint);
    CC.oursHeads(QK.$('#tm-table', el));
    paint();
    QK.$('#tm-table', el).insertAdjacentHTML('afterend', '<div class="cc-ours">' + QK.oursExplain('Our rating is the margin we expect against an average team on a neutral field, split into offence and defence' + (fb ? ', with opponent-adjusted EPA and schedule strength from the same model' : ' (adjusted efficiency per 100 possessions)') + '; columns tagged ' + QK.ours({ short: true }) + ' are ours.') + '</div>');
  });
});

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
CC.route('team', function (el, p) {
  var L = p.L, S = p.S, tid = p.id, fb = CC.fb(L);
  el.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'teams/' + tid + '.json')), CC.season(L, S), CC.load(CC.path(L, S, 'teams.json')), CC.metrics()]).then(function (a) {
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
    var peers = fb ? 'FBS teams' : 'Division I teams';
    document.title = (t ? t.name : 'Team ' + tid) + ' · ' + CC.seasonLabel(L, S) + ' · The Quant Campus';
    /* The short version: the record, the rating and its rank, the schedule, and what the simulation says */
    var nm = t ? (t.short || t.name) : 'Team ' + tid;
    var shortTxt = (isNum(rec.w) ? nm + ' ' + (CC.isCur(L, S) ? 'are' : 'went') + ' ' + CC.record(rec.w, rec.l) + (isNum(rec.conf_w) ? ' (' + CC.record(rec.conf_w, rec.conf_l) + ' in the conference)' : '') + '. ' : '') +
      (isNum(R.rating) ? 'We rate them ' + CC.f(Math.abs(R.rating), 1) + (fb ? ' points' : ' points per 100 possessions') + ' ' + (R.rating >= 0 ? 'better' : 'worse') + ' than an average ' + (fb ? 'FBS' : 'D-I') + ' team' + (isNum(R.rank) ? ', ' + QK.ordinal(R.rank) + ' in the country' : '') + (isNum(R.se) ? ', give or take ' + CC.f(R.se, 1) : '') + '. ' : '') +
      (sim && isNum(sim.p_title) && sim.p_title >= 0.005 ? 'Our simulations give them a ' + CC.pct(sim.p_title) + ' chance to win the title.' : (isNum(R.sos_rank) ? 'Their schedule ranks ' + QK.ordinal(R.sos_rank) + ' for strength.' : ''));
    var html = '<nav class="cc-crumb" aria-label="Breadcrumb"><a href="' + esc(CC.href(L, 'teams', null, S)) + '">' + esc(CC.LNAME[L]) + '</a><span aria-hidden="true">›</span>' + esc(conf ? (conf.short || conf.name) : 'Independent') + '<span aria-hidden="true">›</span>' + esc(t ? t.name : 'Team ' + tid) + '</nav>';
    html += QK.playerHeader({ name: t ? t.name : 'Team ' + tid, split: false, pos: conf ? (conf.name || conf.short) : 'Independent', kicker: CC.LNAME[L] + ' · ' + CC.seasonLabel(L, S), face: t && t.abbr ? t.abbr : null,
      team: t ? { name: '', abbr: t.abbr, colour: t.colour, alt: CC.talt(L, tid) || undefined } : null,
      meta: [['Record', CC.record(rec.w, rec.l)], isNum(rec.conf_w) ? ['Conference', CC.record(rec.conf_w, rec.conf_l)] : null, rec.streak ? ['Streak', rec.streak] : null, isNum(R.games) ? ['Games rated', String(R.games)] : null],
      short: null }) + '%STRIP_HTML%' + (shortTxt.trim() ? '<div class="qk-ph-short">' + QK.shortVersion(shortTxt.trim()) + '</div>' : '');
    if (!d) html += '<p class="cc-note">The full team page has not been built for this season; ratings come from the season file.</p>';
    var dm = ((cat && cat.metrics) || []).filter(function (m0) { return m0.key === 'def'; })[0];
    var defLow = dm ? !!dm.lower : !fb;
    var k = [{ label: 'Our rating', value: CC.signed(R.rating, 1), signal: true, pctl: pc('rating'), sub: (isNum(R.se) ? '± ' + CC.f(R.se, 1) + ' · ' : '') + (fb ? 'points v an average FBS team' : 'per 100 v an average D-I team'),
      tip: (fb ? 'Expected margin against an average FBS team on a neutral field' : 'Adjusted efficiency margin per 100 possessions') + '; ± is one standard error; the chip is the national percentile' }];
    if (isNum(R.off)) k.push({ label: 'Offense', value: CC.f(R.off, 1), pctl: pc('off'), sub: fb ? 'points a game added' : 'adjusted points per 100' });
    if (isNum(R.def)) k.push({ label: 'Defense', value: CC.f(R.def, 1), pctl: pc('def'), sub: defLow ? 'points allowed per 100 (lower is better)' : 'points a game prevented' });
    if (CC.isCur(L, S)) k = k.concat(chanceTiles(L, sim));
    /* v4: the numbers are the black strip under the team-colour hero (QK.playerHeader strip), "The short version" after */
    html = html.replace('%STRIP_HTML%', QK.statStrip(k.slice(0, 6)));
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
          return { label: m.d || m0.label, pctl: pp0, value: CC.fmtMetric(m0, v0), tip: (m.x || m0.desc || '') + (m.style ? ' Describes how the team plays, not how well: shown in grey.' : ''), style: !!m.style };
        };
        var hRows = TG.m.filter(function (m) { return m.set === 'h'; }).map(rowOf).filter(Boolean);
        var sRows = TG.m.filter(function (m) { return m.set === 's'; }).map(rowOf).filter(Boolean);
        if (hRows.length >= 3) groups = [{ label: 'Headline: ratings, then the process that predicts results', rows: hRows }, { label: 'More', rows: sRows }];
      }
      if (!groups.length) cat.metrics.forEach(function (m0) {
        if (FL[m0.key]) return;
        var v = (stx[m0.key] && isNum(stx[m0.key].v)) ? stx[m0.key].v : ((cat.teams[tid] || {}).values || {})[m0.key], pp = pc(m0.key);
        if (!isNum(pp)) return;
        var row = { label: m0.label, pctl: pp, value: CC.fmtMetric(m0, v), tip: m0.desc || '' };
        if (/off|ppg|^ypp$|third|pass_epa|rush_epa|explosive|efg|tpar|ftr|orb|ast|^tov_rate|tp_pct|ft_pct/.test(m0.key) && !/allowed|opp_|def/.test(m0.key)) off.push(row);
        else if (/def|allowed|papg|opp_|drb|blk|stl/.test(m0.key)) def.push(row); else oth.push(row);
      });
      if (!groups.length) groups = [{ label: 'Offense', rows: off }, { label: 'Defense', rows: def }, { label: 'Overall and schedule', rows: oth }];
    }
    var nTeams = cat && cat.teams ? Object.keys(cat.teams).length : null;
    var pcard = QK.pctCard({ title: 'Percentile rankings', peer: 'all ' + (nTeams ? nTeams + ' ' : '') + peers, sample: (isNum(R.games) && R.games > 0 ? R.games + ' games rated' : 'preseason ratings, no games yet') + ' · ' + CC.seasonLabel(L, S), groups: groups,
      note: 'Opponent-adjusted where the metric says so; lower-is-better metrics are flipped so 100 is always best.', emptyText: 'Percentiles appear after the first games.' });
    var path = (d && d.rating_path) || (season && season.rating_paths && season.rating_paths[tid]) || [];
    var rh = (d && d.rank_history) || [];
    html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + pcard + '</div><div class="qk-span-7"><div class="qk-stack">' +
      U.card('Rating through the season', 'Re-fitted after each week' + (isNum(R.se) ? '; today’s rating is ± ' + CC.f(R.se, 1) + ' (one standard error)' : '') + '.', path.length > 1 ? U.chart('tp-path', 240, 'Rating through the season') : QK.empty('Not enough games yet', 'The path starts after the first games.')) +
      U.card('AP rank v our rank', 'Week by week; 1 is the top.', rh.length > 1 ? U.chart('tp-rank', 220, 'AP and our rank by week') : QK.empty('No rank history', 'The polls and our ranking appear once the season starts.')) + '</div></div></div>';
    // schedule
    var sched = (d && d.schedule) || [];
    if (sched.length) html += U.section('Schedule', 'Every game with our pre-game win chance for ' + esc(CC.tshort(L, tid)) + '.', U.card('', '', U.lb('tp-sched'), { flush: true, cls: 'cc-bare' }), '', 'Games');
    // roster + units
    var roster = (d && d.roster) || [];
    var units = (d && d.units) || [];
    var unitsH = units.length ? QK.pctCard({ title: 'Strengths and needs', peer: 'all ' + peers, sample: 'value by unit this season', groups: [{ label: 'Units, graded A to F', rows: units.map(function (u) { return { label: CC.unit(u.unit) + (u.grade ? ' · ' + u.grade : ''), pctl: isNum(u.pctl) ? u.pctl : null, value: isNum(u.value) ? CC.signed(u.value, 1) : '', tip: CC.unit(u.evidence || '') }; }) }],
      foot: swList(d) }) : U.card('Strengths and needs', '', QK.empty('Not graded yet', 'Units are graded once enough games are in.'));
    html += topPerformers(L, S, d, fb);
    html += U.section('Roster', 'Value: ' + (fb ? 'EPA above replacement' : 'value above replacement') + ' this season.' + (!CC.isCur(L, S) && !fb && roster.length <= 12 && roster.length ? ' Archive seasons keep the top 12 by minutes.' : ''),
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
    html += U.section('Transfers', 'The same ESPN athlete on a new team since last season. ' + QK.tag(INFERRED),
      '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('In', '', mvT(mv['in'], 'in')) + '</div><div class="qk-span-6">' + U.card('Out', '', mvT(mv.out, 'out')) + '</div></div>', '', 'Moves');
    // season distributions
    if (CC.isCur(L, S) && sim && (sim.w_dist || sim.seed_dist)) {
      html += '<div class="qk-grid cc-grid">' + (sim.w_dist && sim.w_dist.length ? '<div class="qk-span-6">' + U.card('Final win total', 'Our chance of each number of regular-season wins, from the simulated seasons.', U.chart('tp-wd', 220, 'Distribution of final wins')) + '</div>' : '') +
        (sim.seed_dist && Object.keys(sim.seed_dist).length ? '<div class="qk-span-6">' + U.card(fb ? 'Playoff seed' : 'Tournament seed', 'Our chance of each seed, from the simulated seasons.', U.chart('tp-sd', 220, 'Distribution of seeds')) + '</div>' : '') + '</div>';
    }
    el.innerHTML = html;
    U.wire(el);
    var col = t && QK.color.parse(t.colour) ? QK.color.team(t.colour) : null;
    if (path.length > 1) {
      var xs = path.map(function (x0) { return String(x0[0]).slice(0, 10); });
      QKC.forecast('#tp-path', { x: xs, xType: 'time', series: [{ name: 'Rating', label: CC.tabbr(L, tid), data: path.map(function (x0) { return x0[1]; }), color: col }],
        yFmt: function (v) { return CC.signed(v, 1); }, yName: fb ? 'Rating (points v average)' : 'Rating (per 100 v average)', xName: 'Date', label: 'Rating through the season' });
    }
    if (rh.length > 1) QKC.line('#tp-rank', { x: rh.map(function (r) { return String(r[0]) === 'pre' ? 'Pre' : (String(r[0]) === 'final' ? 'Final' : 'Wk ' + r[0]); }), series: [{ name: 'AP', data: rh.map(function (r) { return isNum(r[1]) ? r[1] : null; }), color: QK.cssVar('--c-3'), symbols: true }, { name: 'Ours', data: rh.map(function (r) { return isNum(r[2]) ? r[2] : null; }), color: QK.cssVar('--signal'), symbols: true }],
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
        var pw = isNum(m0.p_home) ? (home ? m0.p_home : 1 - m0.p_home) : null;
        var res = '<span class="qk-muted">' + (c.status === 'pre' ? 'to play' : '—') + '</span>', resv = '';
        if (c.status === 'post' && isNum(c.hs)) { var my = home ? c.hs : c.as, op = home ? c.as : c.hs; res = '<b class="' + (my > op ? 'pos' : 'neg') + '">' + (my > op ? 'W' : 'L') + '</b> ' + my + '–' + op; resv = (my > op ? 'W' : 'L') + my; }
        return { c: c, id: c.id, date: c.date, opp: opp, oppName: (c.neutral ? 'v ' : home ? 'v ' : '@ ') + CC.tshort(L, opp), tag: CC.roundLabel(c) || (c.conf_game ? 'conference' : ''), pw: pw, res: res, resv: resv };
      }) });
    }
    if (roster.length) {
      var rcols = fb ? [['pass_yds', 'Pass yds', 0], ['rush_yds', 'Rush yds', 0], ['rec_yds', 'Rec yds', 0], ['tkl', 'Tkl', 0]] : [['min', 'MIN', 1], ['pts', 'PTS', 1], ['reb', 'REB', 1], ['ast', 'AST', 1]];
      rcols = rcols.filter(function (c) { return roster.some(function (r) { return isNum(r[c[0]]); }); });
      var lv = {}; (((d && d.movement) || {}).roster || []).forEach(function (x) { lv[String(x[0])] = { p: x[1], pt: x[2] }; });
      var hasLv = Object.keys(lv).length > 0;
      var mx = Math.max.apply(null, roster.map(function (r) { return Math.abs(r.value || 0); }).concat([1e-9]));
      CC.oursHeads(QK.$('#tp-roster', el));
        QK.leaderboard(QK.$('#tp-roster', el), { dense: true, maxHeight: 640, sort: { key: 'value', dir: 'desc' }, rowHref: function (r) { return CC.playerHref(L, r.id, S); }, columns: [
        { key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: function (r) { return CC.playerHref(L, r.id, S); } },
        { key: 'gp', label: 'GP', num: true },
        { key: 'value', label: 'Value', type: 'bar', max: mx, fmt: function (v) { return CC.f(v, fb ? 1 : 2); }, tip: fb ? 'EPA above replacement this season' : 'Value above replacement this season' },
        { key: 'value_pg', label: 'Per game', num: true, fmt: function (v) { return CC.f(v, 2); } }
      ].concat(rcols.map(function (c) { return { key: c[0], label: c[1], num: true, fmt: function (v) { return isNum(v) ? CC.f(v, c[2]) : '—'; } }; }))
       .concat(hasLv ? [{ key: 'p_leave', label: 'Chance of leaving', type: 'bar', max: 1, fmt: function (v) { return isNum(v) ? CC.pct(v) : '—'; }, tip: 'Our chance the player is not with the team next season (an inferred transfer or no box-score line). ' + INFERRED }] : []),
        rows: roster.map(function (r) { return Object.assign({ sub: [r.pos, r['class']].filter(Boolean).join(' · '), p_leave: lv[String(r.id)] ? lv[String(r.id)].p : null }, r); }) });
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
      '<span class="cc-tp-rank">' + QK.ordinal(r.rank) + ' of ' + QK.fmt.num(r.n) + ' ' + esc(r.pos) + 's</span></li>';
  };
  var ours = tp.ours ? ' ' + QK.ours({ model: fb ? 'value per game: EPA above a replacement-level player' : 'box rating and value above replacement' }) : '';
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
