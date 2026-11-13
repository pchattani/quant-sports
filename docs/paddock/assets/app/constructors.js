/* The Quant Paddock — a constructor's page (#/team/<id>[/<y>]); the list is the Teams page (pd-teams.js, round 9).
 * Team page: the current line-up, car pace through the season (race and qualifying, ±1 se, the field
 * faint), points and retirements by round, the run-in (expected points per remaining round), the title
 * (our chance and where the simulations finish), the car/driver split, the pit crew, straight-line v cornering, the two drivers
 * head to head, the top performers (each driver against the grid: rank and percentile among the qualified drivers on
 * the driver metric set, our driver model first), strengths and needs, and every percentile. Driver swaps ("moves
 * that would add the most") live on the Value page only, not on the team page.
 * The percentile card uses the constructor metric set (PD.v2.TEAM_SET) against the teams at the rounds floor.
 * Reads <y>/teams.json, drivers.json, season.json, needs.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;

function magicOf(c) { if (!c) return null; var m = c.magic; if (m && typeof m === 'object') return isNum(m.magic_number) ? m.magic_number : null; return isNum(m) ? m : null; }
function series(season, kind, team) { return ((((season || {}).car_pace || {})[kind] || {})[team] || []).slice().sort(function (a, b) { return a.round - b.round; }); }
function seasonData(y) { return PD.loadAll([y + '/drivers.json', y + '/teams.json', y + '/season.json']); }
PD.seasonData = seasonData;

/* Grouped percentile bars for a catalogue. */
function pctPanel(metrics, vals, pcts, opts) {
  var o = opts || {};
  var groups = [];
  (metrics || []).forEach(function (m) {
    if (!isNum((pcts || {})[m.key])) return;
    var g = groups.filter(function (x) { return x.name === (m.group || 'Other'); })[0];
    if (!g) { g = { name: m.group || 'Other', items: [] }; groups.push(g); }
    g.items.push(m);
  });
  if (!groups.length) return PD.muted('No percentiles for this season.');
  return '<div class="pd-pct-cols">' + groups.map(function (g) {
    return '<div class="pd-pct-group"><h4>' + esc(g.name) + '</h4>' + window.QK.pctlBars(g.items.map(function (m) { return { label: m.label + (m.lower ? ' ↓' : ''), pctl: pcts[m.key], value: PD.fmtVal((vals || {})[m.key], m.fmt) }; })) + '</div>';
  }).join('') + '</div>' + (o.note ? '<p class="pd-cap">' + o.note + '</p>' : '');
}
PD.pctPanel = pctPanel;
function headline(metrics, prefs, n, pctAny) {
  var out = [];
  var usable = (metrics || []).filter(function (m) { return !pctAny || pctAny === true || isNum(pctAny[m.key]); });
  (prefs || []).forEach(function (p) {
    if (out.length >= n) return;
    var re = p instanceof RegExp ? p : new RegExp('^' + p + '$');
    var m = usable.filter(function (x) { return re.test(x.key) && out.indexOf(x) < 0; })[0];
    if (m) out.push(m);
  });
  usable.forEach(function (m) { if (out.length < n && out.indexOf(m) < 0) out.push(m); });
  return out.slice(0, n);
}
PD.headline = headline;
function h2h(logA, logB) {
  var by = {}, out = { quali: [0, 0], race: [0, 0], points: [0, 0], both: 0, rows: [] };
  (logB || []).forEach(function (r) { by[r.round] = r; });
  (logA || []).forEach(function (a) {
    var b = by[a.round];
    if (!b) return;
    out.both++;
    if (isNum(a.quali_pos) && isNum(b.quali_pos)) out.quali[a.quali_pos < b.quali_pos ? 0 : 1]++;
    var fa = PD.finished(a.status) && isNum(a.pos), fb = PD.finished(b.status) && isNum(b.pos);
    if (fa && fb) out.race[a.pos < b.pos ? 0 : 1]++; else if (fa) out.race[0]++; else if (fb) out.race[1]++;
    out.points[0] += a.points || 0; out.points[1] += b.points || 0;
    out.rows.push([a, b]);
  });
  return out;
}
PD.h2h = h2h;
function h2hBar(label, a, b, ca, cb, na, nb) {
  var n = (a || 0) + (b || 0), wa = n ? 100 * a / n : 50;
  return '<div class="pd-h2h"><div class="pd-h2h-l">' + esc(label) + '</div><div class="pd-h2h-row"><span>' + esc(na) + ' <b>' + PD.num(a, a % 1 ? 1 : 0) + '</b></span>' +
    '<span class="pd-h2h-bar"><i style="width:' + wa + '%;background:' + ca + '"></i><i style="width:' + (100 - wa) + '%;background:' + cb + '"></i></span><span><b>' + PD.num(b, b % 1 ? 1 : 0) + '</b> ' + esc(nb) + '</span></div></div>';
}
PD.h2hBar = h2hBar;
function pairColours(a, b) {
  var ca = window.QK.color.team(a), cb = window.QK.color.team(b);
  if (window.QK.color.contrast(ca, cb) < 1.6) cb = 'var(--c-2)';
  return [ca, cb];
}
PD.pairColours = pairColours;

// ── team page ─────────────────────────────────────────────────────────────

function renderTeam(el, params, state) {
  var id = params.id;
  var y = isNum(params.year) ? params.year : PD.currentSeason();
  el.innerHTML = PD.empty('Loading ' + PD.teamName(id), '');
  return Promise.all([seasonData(y), Promise.resolve(null), y === PD.currentSeason() ? PD.load(y + '/needs.json') : Promise.resolve(null)]).then(function (res) {
    if (!PD.alive(el)) return;
    var drivers = res[0][0], teams = res[0][1], season = res[0][2], needs = res[2];
    var T = (PD.ok(teams) && teams.teams) || {};
    var t = T[id] || null;
    var name = (t && t.name) || PD.teamName(id);
    var D = (drivers || {}).drivers || {};
    var lineup = ((((season || {}).teams || {})[id] || {}).drivers || []).slice();
    Object.keys(D).forEach(function (k) { if (D[k].team === id && lineup.indexOf(k) < 0) lineup.push(k); });
    var idx = PD.index() || {};
    if (y === PD.currentSeason()) {
      // the current line-up comes from the latest index (transfers and stand-ins land there first)
      var cur = Object.keys(idx.drivers || {}).filter(function (k) { return idx.drivers[k].team === id; });
      cur.forEach(function (k) { if (lineup.indexOf(k) < 0) lineup.unshift(k); });
    }
    lineup.sort(function (a, b) { return ((D[b] || {}).races || 0) - ((D[a] || {}).races || 0); });
    var s = (((season || {}).standings || {}).constructors || []).filter(function (x) { return x.team === id; })[0] || {};
    var ch = (((season || {}).championship || {}).constructors || {})[id] || null;
    var rp = series(season, 'race', id), qp = series(season, 'quali', id);
    var last = rp.length ? rp[rp.length - 1] : null, lastQ = qp.length ? qp[qp.length - 1] : null;
    var pit = (t && t.pit) || {};
    var dnfs = ((t && t.log) || []).reduce(function (a, r) { return a + (r.dnfs || 0); }, 0);
    var tcol = PD.tc(id);
    var tP = PD.ok(teams) ? PD.v2.peer(teams, 'teams', season) : null;
    var tpc = tP && tP.pct[id] ? tP.pct[id] : {};
    var nRounds = ((t && t.log) || []).length;
    var nSims = ((season || {}).championship || {}).n_sims;
    /* v4: the constructor colour as the full-bleed hero, the black strip of numbers under it (a tile with no value is
       left out, never dashed); the projected points carry the simulation's 90% range, the car pace its standard error */
    var f2 = function (x) { return PD.signed(x, 2) + '%'; };
    var strip = [
      s.pos ? PD.kpi('Constructors', PD.ordinal(s.pos), isNum(s.points) ? PD.pts(s.points) + ' points · ' + (s.wins || 0) + ' win' + (s.wins === 1 ? '' : 's') : '') : null,
      ch ? PD.kpi('Title chance', PD.titlePct(ch, 1), ch.clinched ? 'clinched' : ch.eliminated ? 'out of the running' : 'from ' + PD.int(nSims || 20000) + ' simulated seasons', { signal: true, tip: 'Our chance of the constructors’ title, from the season simulation' }) : null,
      ch && isNum(ch.exp_points) ? PD.kpi('Projected points', PD.num(ch.exp_points, 0), isNum(ch.p05) && isNum(ch.p95) ? '9 seasons in 10: ' + PD.num(ch.p05, 0) + '–' + PD.num(ch.p95, 0) : 'at the end of the season',
        { tip: 'Final points: the mean of our simulated seasons; the range runs from the 5th to the 95th percentile', range: isNum(ch.p05) && isNum(ch.p95) ? { lo: ch.p05, hi: ch.p95, mid: ch.exp_points, fmt: function (v) { return PD.num(v, 0); }, label: '9 seasons in 10' } : null }) : null,
      last ? PD.kpi('Race car pace', f2(-last.effect), '% of a lap v the field, + is faster · R' + last.round + ' ± ' + PD.num(last.se, 2) + ' (1 se)', { pctl: tpc.car_race_pace, tip: 'The car’s share of race pace with the drivers taken out, % of a lap against the field average; the band is plus or minus one standard error',
        range: isNum(last.se) && last.se > 0 ? { lo: -last.effect - last.se, hi: -last.effect + last.se, mid: -last.effect, fmt: f2, label: 'Plus or minus one standard error' } : null }) : null,
      !ch && lastQ ? PD.kpi('Quali car pace', f2(-lastQ.effect), 'R' + lastQ.round + ' ± ' + PD.num(lastQ.se, 2) + ' (1 se)') : null,
      isNum(pit.median_ms) ? PD.kpi('Median stop', PD.num(pit.median_ms / 1000, 2) + 's', isNum(pit.best_ms) ? 'best ' + PD.num(pit.best_ms / 1000, 2) + 's' + (isNum(pit.p_under_2500) ? ' · ' + PD.pct(pit.p_under_2500, 0) + ' under 2.5 s' : '') : '', { pctl: tpc.pit_under_2500 }) : null,
      t ? PD.kpi('Retirements', String(dnfs), nRounds + ' round' + (nRounds === 1 ? '' : 's') + (nRounds ? ' · ' + PD.pct(dnfs / (2 * nRounds), 0) + ' of starts' : ''), { pctl: tpc.dnf_rate }) : null
    ].filter(Boolean);
    var h = '<nav class="pd-crumb" aria-label="Breadcrumb"><a href="#/constructors">F1</a><span aria-hidden="true">›</span><a href="#/constructors">Constructors</a><span aria-hidden="true">›</span>' + esc(name) + '</nav>' + QK.playerHeader({ name: name, split: false, pos: 'Constructor', kicker: y + ' season' + (s.pos ? ' · P' + s.pos + ' in the constructors’ championship' : ''),
        team: { colour: PD.teamColourRaw(id), alt: PD.teamAlt(id) }, face: PD.teamAbbr(id), meta: lineup.map(function (d) { return PD.driverLink(d, { dot: false }); }), strip: strip, tags: tP && tP.qualified(id) ? [QK.tag('In the ' + y + ' peer group', 'signal')] : [],
        short: shortTeam(name, s, ch, tP, id, nRounds, last),
        /* round 12 (My Teams): follow the constructor from the hero */
        follow: PD.follow && PD.follow.ok('team', id) ? PD.follow.item('team', id) : null }) +
      '<div class="pd-links pd-mt">' + (lineup.length >= 2 ? '<a class="qk-btn" href="#/compare/drivers/' + encodeURIComponent(lineup[0]) + '/' + encodeURIComponent(lineup[1]) + (y !== PD.currentSeason() ? '?y=' + y : '') + '">Compare the drivers</a>' : '') +
      '<a class="qk-btn" href="#/constructors' + (y !== PD.currentSeason() ? '/' + y : '') + '?a=' + encodeURIComponent(id) + '&sec=h2h">Compare with another team</a><a class="qk-btn" href="#/value?tab=needs">Every team’s needs</a></div>';
    if (!t && !s.team && !lineup.length) { el.innerHTML = h + PD.empty(name + ' is not in the ' + y + ' data', PD.ok(teams) ? 'Pick another season.' : 'The team catalogue is not built yet.'); return; }
    /* 1. the LED meters with "How sure are we?" under them (7) beside the tale of the tape against the closest rival (5),
       as the driver and the Rink's player pages */
    var rivals = tP && tP.qualified(id) ? rivalsOf(tP, season, id) : [];
    if (tP) h += '<section class="qk-section pd-sec1"><div class="qk-g75"><div>' + PD.v2.pctCard(tP, id, PD.v2.TEAM_SET, { foot: '<span>Metrics chosen for year-to-year stability and what they predict</span><a href="#/glossary">Glossary →</a>' }) +
      QK.explain(settleTeam(tP, id, nRounds, last), { cls: 'pd-settle' }) +
      /* with the tape on the right, the peer distribution sits under the meters so the two columns end together */
      (rivals.length ? '<div class="pd-mt">' + PD.card('Where the team sits', 'Every constructor in the ' + y + ' peer group; bars coloured by percentile, ' + esc(name) + ' and the median marked.', PD.v2.distSeg('tm-dist-m', [['car_race_pace', 'Car pace'], ['points_per_race', 'Points / race'], ['dnf_rate', 'DNF rate'], ['pit_lane_v_field', 'Pit lane'], ['strategy_gain', 'Strategy']]) + PD.chartBox('tm-dist', 240, 'Peer distribution')) + '</div>' : '') +
      '</div><div class="pd-stack">' +
      (rivals.length ? '<div id="tm-tape-h"></div><div class="qk-chips pd-pick" id="tm-tape-pick" role="group" aria-label="Compare with"></div><div id="tm-tape"></div><div id="tm-verd"></div>'
        : PD.card('Where the team sits', 'Every constructor in the ' + y + ' peer group; bars coloured by percentile, ' + esc(name) + ' and the median marked.', PD.v2.distSeg('tm-dist-m', [['car_race_pace', 'Car pace'], ['points_per_race', 'Points / race'], ['dnf_rate', 'DNF rate'], ['pit_lane_v_field', 'Pit lane'], ['strategy_gain', 'Strategy']]) + PD.chartBox('tm-dist', 260, 'Peer distribution'))) +
      '</div></div></section>';
    /* 2. the next race (the two cars as the scoreboard bug) beside the last race (both cars' box and the race chart) */
    h += '<section class="qk-section" id="tm-nl" hidden><div class="qk-g2" id="tm-nl-g"></div></section>';
    /* 3. the season's chances: the title (or, once it is settled, the closest place still open) beside where this
       team finishes in the simulated seasons */
    h += titleBlock(season, id, name, y);
    h += '<section class="qk-section pd-sec">' + PD.secHead(y + ' season', 'Line-up', y === PD.currentSeason() ? 'Current drivers, from the latest build.' : 'Drivers who raced for the team in ' + y + '.') + '<div class="qk-auto" style="--min:220px" id="tm-lineup"></div></section>';
    h += '<section class="qk-section pd-sec">' + PD.secHead('Top performers', 'Against the grid', 'Each of the team\'s drivers ranked against every qualified driver this season, on our driver rating first, then the driver metric set.') + '<div id="tm-top"></div></section>';
    h += PD.grid(
      PD.card('Car pace by race', 'The car’s share of lap time, % of a lap faster than the field, ±1 se shaded; the other cars faint.', PD.chartBox('tm-pace', 360), { span: 12, right: PD.seg('tm-pk', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') }) +
      PD.card('Points and retirements by round', 'Points per round (bars) and retirements (markers).', PD.chartBox('tm-rel', 280), { span: 6 }) +
      PD.card('The run-in', 'Expected points per remaining round from the championship simulation (both drivers).', PD.chartBox('tm-runin', 280), { span: 6 }) +
      PD.card('Car or driver?', 'Our expected points: an average team, the car’s contribution and each driver’s.', PD.chartBox('tm-split', 300), { span: 6 }) +
      PD.card('Pit crew', 'Stationary time per stop; the 2.5 s line is the benchmark.', '<div id="tm-pitk"></div>' + PD.chartBox('tm-pit', 220), { span: 6 }) +
      PD.card('The drivers', 'Both cars on headline metrics, field percentiles, and head to head.', '<div id="tm-drv"></div>', { span: 6, flush: true }) +
      PD.card('Straight line v cornering', '<span id="tm-prof-s">Every team this season.</span>', PD.chartBox('tm-prof', 340), { span: 6 }), 'pd-mt');
    h += '<div id="tm-needs"></div>';
    h += PD.card('Every metric', 'The whole team catalogue against every team that entered this season (100 = best).', '<div id="tm-pct"></div>', { cls: 'pd-mt' });
    el.innerHTML = h;
    if (tP && document.getElementById('tm-dist')) {
      var drawTD = function (key) { PD.v2.distribution('#tm-dist', tP, key, [{ x: ((t || {}).values || {})[key], label: PD.teamAbbr(id) }]); };
      drawTD('car_race_pace');
      PD.wireSeg(document, 'tm-dist-m', drawTD);
    }

    // line-up cards
    var stD = {};
    ((((season || {}).standings || {}).drivers) || []).forEach(function (x) { stD[x.driver] = x; });
    PD.set('tm-lineup', lineup.map(function (d) {
      var info = (idx.drivers || {})[d] || PD.NAMES.drivers[d] || {}, x = stD[d] || {}, row = D[d] || {};
      return '<a class="qk-card is-link pd-dcard" href="' + PD.driverHref(d) + '" style="--tc:' + esc(tcol) + '"><span class="qk-avatar" style="--tc:' + esc(tcol) + '">' + esc(info.number || PD.driverCode(d)) + '</span><div><b>' + esc(PD.driverName(d)) + '</b>' +
        '<div class="qk-sub">' + esc(info.nationality || '') + (row.races ? ' · ' + row.races + ' races' : '') + '</div><div class="pd-dcard-s">' + (x.pos ? 'P' + x.pos + ' · ' : '') + PD.pts(x.points) + ' pts' + (x.wins ? ' · ' + x.wins + ' wins' : '') + '</div></div></a>';
    }).join('') || PD.muted('No drivers listed.'));

    // top performers against the grid
    topPerformers(drivers, season, lineup, id);

    // car pace
    var others = Object.keys((((season || {}).car_pace || {}).race) || {}).filter(function (k) { return k !== id; });
    var drawPace = function (kind) {
      var mine = series(season, kind, id);
      PD.ch.lines('tm-pace', others.map(function (o) { return { name: PD.teamName(o), faint: true, colour: PD.teamColour(o), data: series(season, kind, o).map(function (e) { return [e.round, -e.effect]; }) }; })
        .concat([{ name: name, colour: PD.teamColour(id), width: 3, symbols: true, data: mine.map(function (e) { return [e.round, -e.effect]; }), band: mine.map(function (e) { return [e.round, -e.effect - (e.se || 0), -e.effect + (e.se || 0)]; }) }]),
        { xName: 'Round', yName: 'Car pace (% of a lap)', legend: false, yFmt: function (v) { return PD.signed(v, 2); }, xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { return 'Round ' + v; }, faintTip: false, emptyText: 'No ' + kind + ' car-pace series yet.', label: 'Car pace by race' });
    };
    drawPace('race');
    PD.wireSeg(document, 'tm-pk', drawPace);

    // the tale of the tape against the closest rival, the next and the last race
    if (rivals.length) tapeTeam(tP, id, rivals, y, season);
    nextLastTeam(id, y, t, D, lineup, name);
    if (document.getElementById('tm-range')) PD.v2.rangeChart('tm-range', season, 'constructors', 11);

    // points and DNFs
    var lg = ((t && t.log) || []).slice().sort(function (a, b) { return a.round - b.round; });
    if (lg.length) PD.ch.columns('tm-rel', { cats: lg.map(function (r) { return 'R' + r.round; }), xName: 'Round', yName: 'Points', y2Name: 'DNFs', y2Max: 2,
      series: [{ name: 'Points', data: lg.map(function (r) { return r.points || 0; }), colour: PD.teamColour(id), fmt: function (v) { return PD.pts(v); } },
        { name: 'Retirements', type: 'scatter', axis: 1, symbol: 'triangle', size: 11, colour: PD.col('down'), data: lg.map(function (r) { return r.dnfs ? r.dnfs : null; }), fmt: function (v) { return String(v); } }], label: 'Points by round' });
    else PD.ch.none('tm-rel', 'No rounds logged yet.');

    // run-in
    var cd = (((season || {}).championship || {}).drivers) || {};
    var rounds = {};
    lineup.forEach(function (d) { var pr = (cd[d] || {}).per_round_exp_points || {}; Object.keys(pr).forEach(function (k) { rounds[k] = (rounds[k] || 0) + (pr[k] || 0); }); });
    var rk = Object.keys(rounds).sort(function (a, b) { return a - b; });
    var calBy = {};
    ((season || {}).calendar || []).forEach(function (c) { calBy[c.round] = c; });
    if (rk.length) PD.ch.columns('tm-runin', { cats: rk.map(function (k) { return PD.shortRace((calBy[k] || {}).name || 'R' + k); }), series: [{ name: 'Expected points', data: rk.map(function (k) { return rounds[k]; }), colour: PD.teamColour(id), labels: true, fmt: function (v) { return PD.num(v, 1); } }],
      fmt: function (v) { return PD.num(v, 0); }, yName: 'Expected points', rotate: rk.length > 8 ? 30 : 0, label: 'Expected points per remaining round' });
    else PD.ch.none('tm-runin', season && season.championship ? 'No per-round expectations in the simulation.' : 'No rounds left this season.');

    // split
    var split = (((season || {}).car_driver_split) || {})[id] || (t && t.split) || null;
    if (split && isNum(split.car)) {
      var dk = Object.keys(split.drivers || {});
      var steps = (isNum(split.baseline) ? [{ label: 'Average team', value: split.baseline }] : []).concat([{ label: 'Car', value: split.car }])
        .concat(dk.map(function (k) { return { label: PD.driverSurname(k), value: split.drivers[k] }; })).concat(isNum(split.model_points) ? [{ label: 'Model points', value: split.model_points, total: true }] : []);
      PD.ch.waterfall('tm-split', steps, { colour: PD.teamColour(id), yName: 'Expected points', label: 'Car and driver split' });
      document.getElementById('tm-split').insertAdjacentHTML('afterend', '<p class="pd-cap">Car share ' + (isNum(split.car_share) ? PD.pct(split.car_share, 0) : '—') + ' · actual points ' + PD.pts(split.points) + ' · from ' + esc(split.source || 'race') + ' effects.</p>');
    } else PD.ch.none('tm-split', 'No car/driver split yet.');

    // pit crew
    PD.set('tm-pitk', PD.kpis([PD.kpi('Median', isNum(pit.median_ms) ? PD.num(pit.median_ms / 1000, 2) + 's' : '—'), PD.kpi('Best', isNum(pit.best_ms) ? PD.num(pit.best_ms / 1000, 2) + 's' : '—'),
      PD.kpi('Under 2.5 s', isNum(pit.p_under_2500) ? PD.pct(pit.p_under_2500, 0) : '—'), PD.kpi('Stops', isNum(pit.stops) ? String(pit.stops) : (Array.isArray(pit.stops) ? String(pit.stops.length) : '—'))], 'pd-kpis-4'));
    var stops = Array.isArray(pit.stop_ms) ? pit.stop_ms : (Array.isArray(pit.stops) ? pit.stops : []);
    var sv = stops.filter(function (v) { return isNum(v) && v > 0 && v < 15000; }).map(function (v) { return v / 1000; });
    if (sv.length) PD.ch.hist('tm-pit', sv, { bin: 0.2, xName: 'Stationary time (s)', yName: 'Stops', colour: PD.teamColour(id), fmt: function (v) { return PD.num(v, 1); }, unit: ' s', name: 'Stops', label: 'Pit stop times' });
    else PD.ch.none('tm-pit', 'No stationary times recorded (OpenF1, 2023 on).');

    // drivers side by side
    var two = lineup.filter(function (d) { return D[d]; }).slice(0, 2);
    if (two.length) {
      var dm = (drivers && drivers.metrics) || [];
      var heads = headline(dm, ['race_pace', 'quali_pace', 'driver_effect', 'quali_driver_effect', 'avg_finish', 'overtakes_made', 'tyre_mgmt', 'points_v_expected', 'dnf_rate'], 9, true);
      var cols = [{ key: 'label', label: 'Metric', sticky: true, sort: false, fmt: function (v, r) { return '<a class="pd-link" href="#/glossary/' + encodeURIComponent(r.key) + '">' + esc(v) + '</a>'; } }];
      two.forEach(function (d, i) { cols.push({ key: 'v' + i, label: PD.driverSurname(d), num: true, sort: false, pctl: 'p' + i, fmt: function (v, r) { return PD.fmtVal(v, r.fmt); } }); });
      PD.table('tm-drv', cols, [{ key: 'races', label: 'Races', fmt: 'int', v0: (D[two[0]] || {}).races, v1: two[1] ? (D[two[1]] || {}).races : null }].concat(heads.map(function (m) {
        return { key: m.key, label: m.label, fmt: m.fmt, v0: ((D[two[0]] || {}).values || {})[m.key], p0: ((D[two[0]] || {}).pct || {})[m.key], v1: two[1] ? ((D[two[1]] || {}).values || {})[m.key] : null, p1: two[1] ? ((D[two[1]] || {}).pct || {})[m.key] : null };
      })));
      if (two.length === 2) {
        var hh = h2h(D[two[0]].log, D[two[1]].log);
        var pc = pairColours(PD.teamColour(id), PD.col('grey'));
        document.getElementById('tm-drv').insertAdjacentHTML('beforeend', '<div class="pd-pad">' + h2hBar('Qualifying', hh.quali[0], hh.quali[1], pc[0], pc[1], PD.driverSurname(two[0]), PD.driverSurname(two[1])) +
          h2hBar('Race', hh.race[0], hh.race[1], pc[0], pc[1], PD.driverSurname(two[0]), PD.driverSurname(two[1])) + '</div>');
      }
    } else PD.set('tm-drv', PD.muted('No drivers in the catalogue.'));

    // straight line v cornering
    var metrics = (teams && teams.metrics) || [];
    var findM = function (res2) { for (var i = 0; i < res2.length; i++) { var m = metrics.filter(function (x) { return res2[i].test(x.key); })[0]; if (m) return m; } return null; };
    var mx = findM([/^top_speed$/, /speed_trap/]), my = findM([/^corner_speed$/, /corner_speed/]);
    var pids = mx && my ? Object.keys(T).filter(function (k) { return isNum((T[k].values || {})[mx.key]) && isNum((T[k].values || {})[my.key]); }) : [];
    if (pids.length >= 3) {
      PD.set('tm-prof-s', esc(mx.label) + ' against ' + esc(my.label) + '; every team this season.');
      PD.ch.scatter('tm-prof', pids.map(function (k) { return { x: T[k].values[mx.key], y: T[k].values[my.key], name: PD.teamName(k), short: PD.teamAbbr(k), colour: PD.teamColour(k), href: PD.teamHref(k), size: k === id ? 18 : 11, hit: k === id, label: true }; }),
        { xName: mx.label, yName: String(my.label).replace(/^Minimum c/, 'C'), invX: !!mx.lower, invY: !!my.lower, xFmt: function (v) { return PD.num(v, 1); }, yFmt: function (v) { return PD.num(v, 1); }, label: 'Straight line against cornering' });
    } else PD.ch.none('tm-prof', 'Too few teams have both a top speed and a corner-speed figure this season (' + pids.length + '). Corner speed comes from processed OpenF1 telemetry (2023 on).');

    // needs
    needsBlock(needs, id);

    PD.set('tm-pct', t ? pctPanel(metrics, t.values, t.pct) : PD.muted('Not in the team catalogue.'));
  });
}

/* ── the constructor page's family pieces (12 Nov 2026 sweep, after rk-team.js and the driver page) ─────────── */
var NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five'];
var pct0 = function (v) { return PD.pct(v, 0); };
/* a win chance: a tenth of a percent below 10%, '0%' for a true zero (PD.pct prints '<0.1%' for the tiny ones) */
var pcw = function (v) { return isNum(v) && v > 0 && v < 0.1 ? PD.pct(v, 1) : PD.pct(v, 0); };
var shortNm = function (k) { return PD.teamName(k).replace(/ F1 Team$| Formula One Team$| Racing$/, ''); };

/* "The short version": points and place, our title chance and projected points (with the simulation's 90% range),
   then, once the team is in the peer group, what it does best among the constructors and its weak spot on the
   headline set (PD.v2.TEAM_SET). A team short of the floor is told to read the ranks lightly. */
function shortTeam(name, s, ch, tP, id, rounds, last) {
  if (!rounds && !isNum(s.points)) return null;
  var V = PD.v2;
  var t = name + (ch ? ' have ' : ' scored ') + PD.pts(s.points || 0) + ' point' + (s.points === 1 ? '' : 's') + ' from ' + rounds + ' round' + (rounds === 1 ? '' : 's') + (s.pos ? ', ' + PD.ordinal(s.pos) + ' in the constructors’ championship' : '') + '.';
  if (ch && isNum(ch.exp_points)) {
    var rng = isNum(ch.p05) && isNum(ch.p95) ? ' (9 seasons in 10: ' + PD.num(ch.p05, 0) + '–' + PD.num(ch.p95, 0) + ')' : '';
    t += ch.clinched ? ' The title is won; we project ' + PD.num(ch.exp_points, 0) + ' points by the end' + rng + '.'
      : ch.eliminated ? ' Out of the title race; we project ' + PD.num(ch.exp_points, 0) + ' points by the end' + rng + '.'
      : ' We give them ' + PD.titlePct(ch, 1) + ' for the title and project ' + PD.num(ch.exp_points, 0) + ' points' + rng + '.';
  }
  var pc = tP && tP.qualified(id) ? (tP.pct[id] || {}) : null;
  if (pc) {
    var rows = [];
    V.TEAM_SET.forEach(function (g) { g[1].forEach(function (k) { if (isNum(pc[k])) rows.push([k, pc[k], V.label(tP.meta, k)]); }); });
    var top = rows.slice().sort(function (a, b) { return b[1] - a[1]; })[0], low = rows.slice().sort(function (a, b) { return a[1] - b[1]; })[0];
    if (top && top[1] >= 70) t += ' Best at ' + V.lc(top[2]) + ' (' + PD.ordinal(Math.round(top[1])) + ' percentile of the ' + tP.n + ' constructors).';
    if (low && low[1] <= 30 && low[0] !== (top || [])[0]) t += ' The weak spot: ' + V.lc(low[2]) + ', in the ' + PD.ordinal(Math.round(low[1])) + ' percentile.';
    if (last && isNum(last.se)) t += ' The car is ' + PD.num(Math.abs(last.effect), 2) + '% of a lap ' + (last.effect <= 0 ? 'faster' : 'slower') + ' than the field (± ' + PD.num(last.se, 2) + ', one standard error).';
  } else if (tP) t += ' Short of the ' + tP.floor + '-round floor for percentiles so far, so read the ranks lightly.';
  return t;
}

/* "How sure are we?" under the meters: the sample, where each headline metric settles (f1.json m50 for constructors:
   the rounds at which half the season-to-season noise is gone), and the car pace's standard error. */
function settleTeam(tP, id, rounds, last) {
  var M = PD.v2.M50_TEAM || {};
  var sample = rounds ? (rounds < 6 ? NUMW[rounds] + ' round' + (rounds === 1 ? ' is' : 's is') + ' a small sample.' : rounds + ' rounds: the picture is settling.') : 'No rounds yet this season.';
  var parts = [['car_race_pace', 'car pace'], ['points_per_race', 'points per race'], ['pit_lane_v_field', 'pit-lane time'], ['strategy_gain', 'places gained through the stops'], ['dnf_rate', 'the DNF rate']]
    .filter(function (x) { return isNum(M[x[0]]); }).map(function (x) { var at = Math.max(1, Math.ceil(M[x[0]])); return x[1] + ' after about <b>' + at + ' round' + (at === 1 ? '' : 's') + '</b>' + (rounds >= at ? ' (reached)' : ''); });
  return '<b>How sure are we?</b> ' + esc(sample) + (parts.length ? ' Half the season-to-season noise is gone for ' + parts.join(', ').replace(/, ([^,]*)$/, ', and $1') + '.' : '') +
    (last && isNum(last.se) ? ' At round ' + last.round + ' the car is ' + PD.num(Math.abs(last.effect), 2) + '% of a lap ' + (last.effect <= 0 ? 'faster' : 'slower') + ' than the field ± ' + PD.num(last.se, 2) + ' (one standard error), from our pace model with the drivers taken out' +
      (Math.abs(last.effect) < last.se ? ': inside one standard error of the field average.' : '.') : '');
}

/* The rivals for the tale of the tape: the teams either side in the standings (the closer on points first), then the
   closest profiles on the headline set; all in the peer group, at most four. */
function rivalsOf(P, season, id) {
  var st = ((season || {}).standings || {}).constructors || [];
  var i = -1, me = null;
  st.forEach(function (r, k) { if (r.team === id) { i = k; me = r; } });
  var out = [];
  var add = function (k) { if (k && k !== id && P.qualified(k) && out.indexOf(k) < 0) out.push(k); };
  if (i >= 0) [st[i - 1], st[i + 1]].filter(Boolean).sort(function (a, b) { return Math.abs((a.points || 0) - (me.points || 0)) - Math.abs((b.points || 0) - (me.points || 0)); }).forEach(function (r) { add(r.team); });
  PD.v2.nearest(P, id, PD.v2.TEAM_SET, 3).forEach(function (x) { add(x.id); });
  return out.slice(0, 4);
}

/* The tale of the tape (QK.compareView with two constructors draws QK.tape): this team against a rival on the headline
   set plus the car group, percentiles against the season's peer group, chips to switch, verdicts under it. */
function tapeTeam(P, id, rivals, y, season) {
  var V = PD.v2;
  var sets = V.TEAM_SET.concat([V.MORE_TEAM[0]]);
  var st = {};
  ((((season || {}).standings || {}).constructors) || []).forEach(function (r) { st[r.team] = r; });
  var ent = function (k) { var r = st[k] || {}; return { name: PD.teamName(k), short: shortNm(k), href: PD.teamHref(k, y), colour: PD.teamColourRaw(k), alt: PD.teamAlt(k), sub: [r.pos ? 'P' + r.pos : '', isNum(r.points) ? PD.pts(r.points) + ' pts' : ''].filter(Boolean).join(' · ') }; };
  var draw = function (oid) {
    var ids = [id, oid], names = ids.map(shortNm);
    var next = Math.abs(((st[id] || {}).pos || 0) - ((st[oid] || {}).pos || 0)) === 1;
    PD.set('tm-tape-h', QK.sectionHead({ kicker: 'Tale of the tape', title: names[0] + ' or ' + names[1] + '?',
      sub: 'Bar length = percentile against ' + esc(P.label) + ' in ' + y + '. The better number in each row is solid.' + (next ? ' Next to each other in the standings.' : ' The closest profile on these numbers.'), html: true }));
    PD.set('tm-tape', V.compare(P, ids, sets, ids.map(ent)));
    PD.set('tm-verd', QK.verdicts(V.verdicts([P, P], ids, sets, names)));
    var lk = document.getElementById('tm-tape-open');
    if (lk) lk.setAttribute('href', '#/compare/teams/' + encodeURIComponent(id) + '/' + encodeURIComponent(oid));
  };
  var pick = document.getElementById('tm-tape-pick');
  if (pick) {
    pick.innerHTML = rivals.map(function (k, i) { return '<button type="button" class="qk-chip" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(shortNm(k)) + (st[k] && st[k].pos ? ' (P' + st[k].pos + ')' : '') + '</button>'; }).join('') +
      '<a class="qk-chip" id="tm-tape-open" href="#/compare/teams/' + encodeURIComponent(id) + '/' + encodeURIComponent(rivals[0]) + '">Open in Compare</a>';
    Array.prototype.forEach.call(pick.querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () {
        Array.prototype.forEach.call(pick.querySelectorAll('button'), function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        draw(b.getAttribute('data-value'));
      });
    });
  }
  draw(rivals[0]);
}

/* The season's chances (QK.chances, our chance only): the constructors' title while two or more teams can win it;
   once it is settled, the closest place still open nearest this team (the place two or more teams reach in between
   2% and 98% of the simulated seasons). Beside it, where every team's season ends on points (the simulation's 5th to
   95th percentile, PD.v2.rangeChart). Nothing for a finished season (no simulation). */
function titleBlock(season, id, name, y) {
  var CH = (season || {}).championship || {}, C = CH.constructors || {};
  var me = C[id], ids = Object.keys(C);
  if (!me || ids.length < 2) return '';
  var V = PD.v2, n = CH.n_sims || 20000, left = (CH.remaining || []).length;
  var sims = PD.int(n) + ' simulated seasons' + (left ? ' of the ' + left + ' round' + (left === 1 ? '' : 's') + ' left' : '');
  var cOf = function (k) { return C[k]; };
  var rows, title, sub, kick = 'Title race';
  var cont = ids.filter(function (k) { return isNum(C[k].p_title) && C[k].p_title >= 0.0005; }).sort(function (a, b) { return C[b].p_title - C[a].p_title; });
  if (cont.length >= 2) {
    rows = V.chanceRows(cont, function (k) { return C[k].p_title; }, false, null, cOf);
    title = 'Who wins the constructors’ title?'; sub = 'Our chance of the title, from ' + sims + '.';
  } else {
    var champ = ids.filter(function (k) { return C[k].clinched || (isNum(C[k].p_title) && C[k].p_title >= 0.9995); })[0];
    var at = isNum(me.exp_pos) ? me.exp_pos : 1, best = null;
    for (var k = 0; k < (me.pos_dist || []).length; k++) {
      var open = ids.filter(function (x) { var p = (C[x].pos_dist || [])[k]; return isNum(p) && p >= 0.02 && p <= 0.98; });
      if (open.length >= 2) { var d = Math.abs(k + 1 - at); if (!best || d < best.d) best = { k: k, d: d }; }
    }
    if (best) {
      var place = best.k + 1;
      var who = ids.filter(function (x) { var p = (C[x].pos_dist || [])[best.k]; return isNum(p) && p >= 0.005; }).sort(function (a, b) { return C[b].pos_dist[best.k] - C[a].pos_dist[best.k]; });
      rows = V.chanceRows(who, function (x) { return C[x].pos_dist[best.k]; }, false, null, null);
      kick = 'Still open'; title = 'The fight for P' + place; sub = (champ ? esc(PD.teamName(champ)) + ' have the title. ' : '') + 'The closest place still open: our chance of finishing P' + place + ', from ' + sims + '.';
    } else {
      rows = V.chanceRows(cont.length ? cont : [id], function (x) { return C[x].p_title; }, false, null, cOf);
      title = 'The order is settled'; sub = 'Every place ends the same way in at least 98 of 100 simulated seasons.';
    }
  }
  var dist = (me.pos_dist || []).map(function (p, i) { return [i + 1, p]; }).filter(function (x) { return isNum(x[1]) && x[1] >= 0.05; }).sort(function (a, b) { return b[1] - a[1]; });
  var mg = magicOf(me);
  var sure = '<b>How sure are we?</b> ' + esc(name) + ' finish ' + (dist.length ? dist.map(function (x) { return 'P' + x[0] + ' in ' + PD.pct(x[1], 0); }).join(', ') : 'outside the top places') + ' of our simulated seasons' +
    (isNum(me.p05) && isNum(me.p95) ? '; 9 in 10 end on ' + PD.num(me.p05, 0) + '–' + PD.num(me.p95, 0) + ' points' : '') + '.' +
    (!me.clinched && !me.eliminated && isNum(mg) && mg > 0 ? ' The magic number is ' + PD.num(mg, 0) + ': the points that clinch the title whatever the others do.' : '') +
    ' A 90% chance still slips one season in ten.';
  return '<section class="qk-section pd-sec"><div class="qk-g2"><div>' + QK.sectionHead({ kicker: kick, title: title, sub: sub, html: true }) +
    QK.chances(rows, { oursName: 'Our chance' }) + QK.explain(sure, { cls: 'pd-settle' }) + '</div>' +
    '<div>' + QK.sectionHead({ kicker: 'Season end', title: 'Where the points land', sub: 'Our expected final points (dot) and the range 9 seasons in 10 end in (bar), from ' + sims + '.', html: true }) +
    '<article class="qk-card"><div class="qk-card-body">' + PD.chartBox('tm-range', 330, 'Season-end points range') + '</div></article></div></div></section>';
}

/* The next race as the scoreboard bug (QK.previewCard layout 'bug': the team's two cars with our win chances, the start
   time between, side by side on podium, points, expected finish and retirement; "How sure" names the team's chance
   of the win, its expected points and how often both cars score), beside the last race: both cars' box, our chance of
   the win before it, and the positions lap by lap (the race file). The forecast's time is the card's "as of". */
function nextLastTeam(id, y, t, D, lineup, name) {
  var idx = PD.index() || {};
  var nx = idx.next && idx.next.year === y ? idx.next : null;
  var lg = ((t && t.log) || []).slice().sort(function (a, b) { return a.round - b.round; });
  var lastT = lg[lg.length - 1] || null;
  var lastRows = [];
  if (lastT) {
    var who = (lastT.drivers || []).length ? lastT.drivers : lineup;
    lastRows = who.map(function (k) { var r = (((D || {})[k] || {}).log || []).filter(function (x) { return x.round === lastT.round; })[0]; return r ? [k, r] : null; }).filter(Boolean)
      .sort(function (a, b) { var fa = PD.finished(a[1].status) && isNum(a[1].pos), fb = PD.finished(b[1].status) && isNum(b[1].pos); return (fb - fa) || ((a[1].pos || 99) - (b[1].pos || 99)); });
  }
  (nx ? PD.load(nx.year + '/races/' + nx.round + '.json') : Promise.resolve(null)).then(function (race) {
    var wrap = document.getElementById('tm-nl'), g = document.getElementById('tm-nl-g');
    if (!wrap || !g) return;
    var out = '';
    if (nx) {
      var fc = (race && race.forecast) || {};
      var f = fc.post_quali && fc.post_quali.drivers ? fc.post_quali : (fc.pre_quali && fc.pre_quali.drivers ? fc.pre_quali : null);
      var ds = f ? f.drivers : {};
      var cars = Object.keys(ds).filter(function (k) { return isNum(ds[k].p_win) && (((idx.drivers || {})[k] || {}).team || PD.driverTeam(k)) === id; }).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
      var rs = ((nx.sessions || {}).race) || nx.date;
      var nd = PD.parseDate(rs), soon = nd && nd.getTime() - QK.now() < 7 * 864e5;
      var fAt = f && (f.generated_at || fc.generated_at);
      out += '<div>' + QK.sectionHead({ kicker: soon ? 'What to watch this weekend' : 'Next up', title: PD.shortRace(nx.name) + ' Grand Prix', html: true,
        sub: 'Round ' + nx.round + ' · ' + esc(((nx.circuit || {}).name) || '') + ' · ' + esc(PD.fmtDate(rs, { year: false, time: true })) + ', your time' + (cars.length && fAt ? ' · our forecast ' + (f === fc.post_quali ? 'after' : 'before') + ' qualifying, as of ' + esc(PD.asOf(fAt)) : '') }) + '<div id="tm-next">';
      if (cars.length >= 2) {
        var a = cars[0], b = cars[1];
        var A = PD.v2.side(a, id), B = PD.v2.mates(PD.v2.side(a, id), PD.v2.side(b, id));
        A.record = A.sub; B.record = B.sub;
        var gg = { sport: 'f1', status: 'pre', start: rs, league: 'Round ' + nx.round, home: A, away: B, p_home: ds[a].p_win, p_away: ds[b].p_win };
        var fx = [['Podium', 'p_podium', false, pct0], ['Points finish', 'p_points', false, pct0], ['Expected finish', 'exp_pos', true, function (v) { return 'P' + PD.num(v, 1); }], ['Retirement', 'p_dnf', true, pct0]]
          .filter(function (x) { return isNum(ds[a][x[1]]) && isNum(ds[b][x[1]]); })
          .map(function (x) { var va = ds[b][x[1]], vb = ds[a][x[1]]; return { label: x[0], a: x[3](va), b: x[3](vb), better: Math.abs(va - vb) < 1e-9 ? null : ((va > vb) !== x[2] ? 'a' : 'b') }; });
        var pw = ds[a].p_win + ds[b].p_win, tm = (f.teams || {})[id] || {}, miss = Math.max(1, Math.round(10 * (1 - pw)));
        var note = '<b>How sure are we?</b> Our chance of a ' + esc(name) + ' win is ' + pcw(pw) + ' (' + esc(PD.driverSurname(a)) + ' ' + pcw(ds[a].p_win) + ', ' + esc(PD.driverSurname(b)) + ' ' + pcw(ds[b].p_win) + '): ' +
          (pw < 0.05 ? 'a win here would be one of the season’s big surprises.' : 'another team wins a race like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.') +
          (isNum(tm.exp_points) ? ' We expect ' + PD.num(tm.exp_points, 1) + ' points from the two cars' + (isNum(tm.p_double_points) ? ', and both score in ' + PD.pct(tm.p_double_points, 0) + ' of our simulated races' : '') + '.' : '');
        out += QK.previewCard(gg, { layout: 'bug', homeFirst: true, factors: fx, factorsTitle: 'The two cars this weekend', note: note });
      } else out += QK.explain('Our forecast for the weekend is built once the race is near.', { title: 'Not built yet.' });
      out += '</div></div>';
    }
    if (lastT && lastRows.length) {
      var posT = function (r) { return PD.finished(r[1].status) && isNum(r[1].pos) ? 'P' + r[1].pos : 'DNF'; };
      var gpPts = 0, ex = 0, allEx = true, spr = 0;
      lastRows.forEach(function (r) { var rp = isNum(r[1].race_points) ? r[1].race_points : (r[1].points || 0); gpPts += rp; spr += (r[1].points || 0) - rp; if (isNum(r[1].exp_points)) ex += r[1].exp_points; else allEx = false; });
      var where = PD.shortRace(lastRows[0][1].name || ('Round ' + lastT.round));
      var sub = lastRows.map(function (r) { return esc(PD.driverSurname(r[0])) + ' ' + posT(r) + (isNum(r[1].grid) && r[1].grid > 0 ? ' from P' + r[1].grid : r[1].grid === 0 ? ' from the pit lane' : ''); }).join(', ') +
        ' · ' + PD.pts(gpPts) + ' point' + (gpPts === 1 ? '' : 's') + ' in the Grand Prix' + (allEx ? ' against the ' + PD.num(ex, 1) + ' we expected' : '') + (spr > 0.05 ? ', plus ' + PD.pts(spr) + ' in the sprint' : '') + '.';
      out += '<div>' + QK.sectionHead({ kicker: y < PD.currentSeason() ? 'Last race of ' + y : 'Last race', title: lastRows.map(posT).join(' and ') + ' at the ' + where + ' GP', sub: sub, html: true }) +
        '<article class="qk-card"><div class="qk-card-body"><div id="tm-box"></div><div id="tm-last-x"></div><div id="tm-race"></div><p class="qk-caption"><a class="qk-link" href="' + PD.raceHref(y, lastT.round) + '">Race centre: laps, strategy and awards</a></p></div></article></div>';
    }
    if (!out) return;
    /* both blocks side by side; one alone (a past season: no next race) runs the full width */
    g.innerHTML = out; g.className = nx && out.indexOf('Last race') >= 0 ? 'qk-g2' : ''; wrap.hidden = false;
    if (lastT && lastRows.length && PD.raceBox) {
      var pr = PD.raceBox(lastRows[0][0], lastRows[0][1], y, id, lastRows[1] ? lastRows[1][0] : null, D, 'tm');
      if (pr && pr.then) pr.then(function (rc) {
        if (!PD.ok(rc)) return;
        var fc2 = rc.forecast || {}, f2 = fc2.post_quali && fc2.post_quali.drivers ? fc2.post_quali : (fc2.pre_quali && fc2.pre_quali.drivers ? fc2.pre_quali : null);
        var d2 = f2 ? f2.drivers : null;
        if (!d2) return;
        var have = lastRows.filter(function (r) { return d2[r[0]] && isNum(d2[r[0]].p_win); });
        if (!have.length) return;
        var pw2 = have.reduce(function (s0, r) { return s0 + d2[r[0]].p_win; }, 0);
        var won = lastRows.some(function (r) { return r[1].pos === 1 && PD.finished(r[1].status); });
        PD.set('tm-last-x', QK.explain('Before the race we gave ' + esc(name) + ' a ' + pcw(pw2) + ' chance of the win (' + have.map(function (r) { return esc(PD.driverSurname(r[0])) + ' ' + pcw(d2[r[0]].p_win); }).join(', ') + '), from our forecast ' + (f2 === fc2.post_quali ? 'after' : 'before') + ' qualifying, built only from data published before the race.' +
          (won ? (pw2 < 0.25 ? ' A win from there is a real surprise.' : ' The win came through.') : (pw2 >= 0.5 ? ' The favourites missed out this time.' : '')), { cls: 'pd-settle' }));
      });
    }
  });
}

/* grades on the kit's percentile scale (A hot, F cold), read when drawn */
var GRADE_P = { A: 100, B: 75, C: 50, D: 25, F: 0 };
function gradeC(g) { return isNum(GRADE_P[g]) ? QK.pctHex(GRADE_P[g]) : PD.col('grey'); }
function grade(g) { return g ? '<span class="pd-grade" style="--g:' + gradeC(g) + '">' + g + '</span>' : '—'; }
PD.grade = grade;
function swapsTable(id, list) {
  if (!list || !list.length) { PD.set(id, PD.muted('No swap adds points.')); return; }
  PD.table(id, [
    { key: 'in_name', label: 'In', sticky: true, fmt: function (v, r) { return PD.driverLink(r.in, { name: v }); } },
    { key: 'from', label: 'From', fmt: function (v) { return PD.teamLink(v); } },
    { key: 'out_name', label: 'Out', fmt: function (v, r) { return PD.driverLink(r.out, { name: v, dot: false }); } },
    { key: 'gain_pts', label: 'Team points', num: true, fmt: function (v) { return '<b class="' + (v >= 0 ? 'pd-up' : 'pd-down') + '">' + PD.signed(v, 1) + '</b>'; } },
    { key: 'gain_title', label: 'Title', num: true, fmt: function (v) { return PD.signed(100 * v, 1) + ' pts'; } },
    { key: 'other_change', label: 'Their team', num: true, fmt: function (v) { return PD.signed(v, 1); } },
    { key: 'sim', label: '', sort: false, fmt: function (v, r) { return '<a class="pd-link" href="#/value?tab=swap&x=' + encodeURIComponent(r.in) + '&w=' + encodeURIComponent(r.out) + '">Simulate →</a>'; } }
  ], list, { sort: { key: 'gain_pts', dir: 'desc' } });
}
PD.swapsTable = swapsTable;
function needsBlock(needs, id) {
  var host = document.getElementById('tm-needs');
  if (!host || !PD.ok(needs) || !(needs.teams || {})[id]) return;
  var x = needs.teams[id];
  var item = function (a) { return '<li>' + grade(a.grade) + '<div><b>' + esc(a.label) + '</b> <span class="qk-muted">' + PD.ordinal(a.pct) + ' percentile</span><div class="qk-sub">' + esc(a.stat || '') + '</div></div></li>'; };
  host.innerHTML = '<section class="qk-section pd-sec">' + PD.secHead('Team needs', 'Strengths and needs', esc(needs.label || '')) +
    PD.grid(PD.card('Areas against the field', 'Percentile among the teams this season; A from the 80th, B 60th, C 40th, D 20th.' + (x.balance ? ' The car ' + esc(x.balance) + '.' : ''), PD.chartBox('tm-areas', Math.max(240, (x.areas || []).length * 30 + 20)), { span: 6 }) +
      PD.card('Strengths', '', '<ul class="pd-glist">' + ((x.strengths || []).map(item).join('') || '<li>None stands out.</li>') + '</ul>', { span: 3 }) +
      PD.card('Weaknesses', '', '<ul class="pd-glist">' + ((x.weaknesses || []).map(item).join('') || '<li>None below the 40th percentile.</li>') + '</ul>', { span: 3 })) + '</section>';
  PD.ch.hbars('tm-areas', (x.areas || []).map(function (a) { return { label: a.label, value: a.pct, colour: gradeC(a.grade), sub: 'Grade ' + (a.grade || '—') + ' · ' + (a.stat || '') }; }), { fmt: function (v) { return PD.num(v, 0); }, min: 0, max: 100, name: 'Percentile', ref: 50, labelWidth: 150, label: 'Graded areas' });
}

/* Top performers: each driver who raced for the team, best first by our race driver rating, against the qualified
   drivers of the season (PD.v2.peer: the f1.json floor, pct_peer when the payload has it). Rank is among those
   drivers on the same metric; "Our model" tags mark the metrics from our own models. */
var TOP_KEYS = ['driver_effect', 'quali_driver_effect', 'race_pace', 'points_per_race', 'race_h2h', 'quali_h2h', 'lap1_gain', 'team_points_share', 'elo_teammate'];
function rankOf(P, id, k) {
  var lower = !!((P.meta || {})[k] || {}).lower, v = ((P.rows[id] || {}).values || {})[k];
  if (!isNum(v) || !P.qualified(id)) return null;
  var vals = P.ids.map(function (j) { return ((P.rows[j] || {}).values || {})[k]; }).filter(isNum);
  var better = vals.filter(function (x) { return lower ? x < v : x > v; }).length;
  return { rank: better + 1, of: vals.length };
}
function topPerformers(drivers, season, lineup, id) {
  var host = document.getElementById('tm-top');
  if (!host) return;
  if (!PD.ok(drivers)) { host.innerHTML = PD.muted('The driver catalogue is not built for this season.'); return; }
  var V = PD.v2, P = V.peer(drivers, 'drivers', season);
  var D = drivers.drivers || {};
  var list = lineup.filter(function (d) { return D[d]; });
  if (!list.length) { host.innerHTML = PD.muted('No driver of this team is in the catalogue.'); return; }
  var head = 'driver_effect';
  var score = function (d) { var pc = P.pct[d]; return pc && isNum(pc[head]) ? pc[head] : -1; };
  list.sort(function (a, b) { return score(b) - score(a) || ((D[b].races || 0) - (D[a].races || 0)); });
  var tcol = PD.tc(id);
  host.innerHTML = '<div class="pd-top">' + list.map(function (d, i) {
    var q = P.qualified(d), pc = P.pct[d] || {}, rk = rankOf(P, d, head);
    var top = q && isNum(pc[head]) ? '<div class="pd-top-h"><span class="pd-top-big">' + (rk ? PD.ordinal(rk.rank) : '—') + '</span><span class="pd-top-of">of ' + (rk ? rk.of : P.n) + ' qualified drivers on ' + esc(V.label(P.meta, head)) + ' ' + V.oursTag(head, true, 'driver') + '</span>' + QK.pctlChip(pc[head]) + '</div>' :
      '<p class="pd-cap">Short of the floor (' + esc(P.label) + '): ' + esc(P.sample(d)) + '. No grid rank yet.</p>';
    var bars = q ? TOP_KEYS.filter(function (k) { return isNum(pc[k]); }).map(function (k) {
      var r = rankOf(P, d, k), m50 = V.M50 || {};
      return { label: V.label(P.meta, k), sub: V.ours(k) ? 'Our model' : '', pctl: pc[k], value: V.fmt(P.meta, k, (D[d].values || {})[k]) + (r ? ' · ' + PD.ordinal(r.rank) + '/' + r.of : ''), tip: V.tip(P.meta, k), early: isNum(m50[k]) && P.size(d) < m50[k] };
    }) : [];
    return '<article class="qk-card pd-top-card" style="--tc:' + esc(tcol) + '"><div class="pd-top-k">' + (i === 0 && list.length > 1 && q ? 'Top performer' : 'Driver') + '</div>' +
      '<a class="pd-top-n" href="' + PD.driverHref(d) + '">' + esc(PD.driverName(d)) + '</a><div class="qk-sub">' + esc(P.sample(d)) + '</div>' + top +
      (bars.length ? QK.pctlBars(bars) : '') + '</article>';
  }).join('') + '</div><p class="pd-cap">Peers: ' + esc(P.label) + '. Percentile 100 is the best on the grid; the rank after each value is among the qualified drivers. Metrics marked "Our model" come from our driver model (the car taken out).</p>';
}

PD.route('team', renderTeam);
})(window.PD);
