/* The Quant Paddock — Constructors: the list (#/constructors[/<y>]) and a team (#/team/<id>).
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

// ── list ──────────────────────────────────────────────────────────────────

function renderList(el, params) {
  var y = isNum(params.year) ? params.year : PD.currentSeason();
  el.innerHTML = PD.pageHead('Constructors · ' + y, 'Every team, ' + y, 'Line-ups, points, our title chances, car pace and pit crews.', PD.yearPager('constructors', y)) + '<div id="cl-body">' + PD.empty('Loading', '') + '</div>';
  return seasonData(y).then(function (res) {
    if (!PD.alive(el)) return;
    var drivers = res[0], teams = res[1], season = res[2];
    var T = (PD.ok(teams) && teams.teams) || {};
    var stand = ((season || {}).standings || {}).constructors || [];
    var champ = (((season || {}).championship) || {}).constructors || {};
    var pos = {};
    stand.forEach(function (s) { pos[s.team] = s; });
    var ids = Object.keys(T).concat(stand.map(function (s) { return s.team; })).concat(Object.keys((season || {}).teams || {}))
      .filter(function (v, i, a) { return a.indexOf(v) === i; }).sort(function (a, b) { return ((pos[a] || {}).pos || 99) - ((pos[b] || {}).pos || 99); });
    if (!ids.length) { PD.set('cl-body', PD.notBuilt('The ' + y + ' team catalogue', teams)); return; }
    var lineup = function (id) {
      var s = (((season || {}).teams || {})[id] || {}).drivers;
      if (s && s.length) return s;
      var D = (drivers || {}).drivers || {};
      return Object.keys(D).filter(function (k) { return D[k].team === id; });
    };
    var cards = ids.map(function (id) {
      var t = T[id] || {}, s = pos[id] || {}, c = champ[id];
      var rp = series(season, 'race', id);
      var last = rp.length ? rp[rp.length - 1] : null;
      return '<a class="qk-card is-link pd-tcard" href="' + PD.teamHref(id) + '" style="--tc:' + esc(PD.tc(id)) + '"><div class="pd-tcard-top">' + PD.mark(id) + '<div class="pd-tcard-n"><b>' + esc(t.name || PD.teamName(id)) + '</b><span class="qk-sub">' +
        lineup(id).map(function (d) { return esc(PD.driverSurname(d)); }).join(' · ') + '</span></div>' + (s.pos ? '<span class="pd-tcard-pos">P' + s.pos + '</span>' : '') + '</div>' +
        '<div class="pd-tcard-stats"><div><span>Points</span><b>' + PD.pts(s.points) + '</b></div><div><span>Wins</span><b>' + (s.wins || 0) + '</b></div>' + (c ? '<div><span>Title</span><b>' + PD.pct(c.p_title, c.p_title > 0.99 ? 2 : 1) + '</b></div>' : '') +
        '<div><span>Car pace</span><b>' + (last ? PD.signed(-last.effect, 2) + '%' : '—') + '</b></div></div>' +
        (rp.length > 1 ? window.QK.spark(rp.map(function (e) { return -e.effect; }), { color: PD.tc(id), w: 220, h: 34, label: 'Car pace through the season' }) : '') + '</a>';
    }).join('');
    var metrics = (teams && teams.metrics) || [];
    var tmeta = PD.v2.metaMap(teams);
    var tP = PD.ok(teams) ? PD.v2.peer(teams, 'teams', season) : null;
    var heads = ['car_race_pace', 'points_per_race', 'dnf_rate', 'pit_lane_v_field', 'pit_under_2500', 'strategy_gain'].map(function (k) { return tmeta[k]; }).filter(function (m) { return m && Object.keys(T).some(function (k) { return isNum(((T[k] || {}).values || {})[m.key]); }); });
    PD.set('cl-body', '<div class="qk-auto pd-tcards" style="--min:250px">' + cards + '</div>' +
      PD.grid(PD.card('Car pace through the season', 'Each team’s race-pace car effect by round from the decomposition, % of a lap faster than the field.', PD.chartBox('cl-pace', 400), { span: 12, right: PD.seg('cl-pk', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') }) +
        PD.card('Team metrics', 'The headline constructor metrics; heat cells are percentiles against ' + (tP ? esc(tP.label) : 'the field') + '. Every metric is on each team page.', '<div id="cl-t"></div>', { span: 12, flush: true }), 'pd-mt'));
    var drawPace = function (kind) {
      PD.ch.lines('cl-pace', ids.map(function (id) { return { name: PD.teamName(id), short: PD.teamAbbr(id), colour: PD.teamColour(id), data: series(season, kind, id).map(function (e) { return [e.round, -e.effect]; }) }; }),
        { xName: 'Round', yName: 'Car pace (% of a lap)', endLabels: true, legend: false, yFmt: function (v) { return PD.signed(v, 2); }, xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { return 'Round ' + v; }, emptyText: 'No car-pace series for this season.', label: 'Car pace by team' });
    };
    drawPace('race');
    PD.wireSeg(document, 'cl-pk', drawPace);
    if (!Object.keys(T).length) { PD.set('cl-t', PD.muted('No team catalogue for this season.')); return; }
    QK.leaderboard(document.getElementById('cl-t'), { dense: true, sort: { key: 'pos', dir: 'asc' }, rowHref: function (r) { return PD.teamHref(r.id); }, columns: [
      { key: 'pos', label: 'Pos', num: true, fmt: function (v) { return v < 99 ? String(v) : '—'; } },
      { key: 'name', label: 'Team', type: 'entity', mark: function (r) { return { name: PD.teamName(r.id), abbr: PD.teamAbbr(r.id), colour: PD.teamColourRaw(r.id) }; }, href: function (r) { return PD.teamHref(r.id); } },
      { key: 'points', label: 'Pts', num: true, fmt: function (v) { return PD.pts(v); } }
    ].concat(heads.map(function (m) { return { key: m.key, label: PD.v2.label(tmeta, m.key), type: 'pctl', pctl: 'p_' + m.key, tip: PD.v2.tip(tmeta, m.key) + (m.lower ? ' (lower is better)' : ''), fmt: function (v) { return PD.v2.fmt(tmeta, m.key, v); } }; })),
    rows: ids.filter(function (id) { return T[id]; }).map(function (id) {
      var r = { id: id, name: PD.teamName(id), pos: (pos[id] || {}).pos || 99, points: (pos[id] || {}).points };
      heads.forEach(function (m) { r[m.key] = (T[id].values || {})[m.key]; r['p_' + m.key] = tP && tP.pct[id] ? tP.pct[id][m.key] : null; });
      return r;
    }) });
    PD.v2.oursHeads(document.getElementById('cl-t'), null, 'constructor');
  });
}

// ── team page ─────────────────────────────────────────────────────────────

function renderTeam(el, params, state) {
  var id = params.id;
  var y = state.year || PD.currentSeason();
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
    /* v4: the constructor colour as the full-bleed hero, the six numbers in the black strip under it */
    var strip = [
      PD.kpi('Constructors', s.pos ? PD.ordinal(s.pos) : '—', isNum(s.points) ? PD.pts(s.points) + ' points · ' + (s.wins || 0) + ' wins' : ''),
      PD.kpi('Title chance', ch ? PD.pct(ch.p_title, ch.p_title > 0.99 ? 2 : 1) : '—', ch ? 'expected ' + PD.num(ch.exp_points, 0) + ' pts (90%: ' + PD.num(ch.p05, 0) + '–' + PD.num(ch.p95, 0) + ')' + (ch.clinched ? ' · clinched' : ch.eliminated ? ' · eliminated' : '') : '', { signal: true, tip: 'Our chance of the constructors’ title' }),
      PD.kpi('Race car pace', last ? PD.signed(-last.effect, 2) + '%' : '—', last ? 'faster than the field · R' + last.round + ' ± ' + PD.num(last.se, 2) : '', { pctl: tpc.car_race_pace }),
      PD.kpi('Quali car pace', lastQ ? PD.signed(-lastQ.effect, 2) + '%' : '—', lastQ ? 'R' + lastQ.round + ' ± ' + PD.num(lastQ.se, 2) : ''),
      PD.kpi('Median stop', isNum(pit.median_ms) ? PD.num(pit.median_ms / 1000, 2) + 's' : '—', isNum(pit.best_ms) ? 'best ' + PD.num(pit.best_ms / 1000, 2) + 's' + (isNum(pit.p_under_2500) ? ' · ' + PD.pct(pit.p_under_2500, 0) + ' under 2.5 s' : '') : ''),
      PD.kpi('Retirements', t ? String(dnfs) : '—', t ? ((t.log || []).length) + ' rounds' : '')
    ];
    var h = '<nav class="pd-crumb" aria-label="Breadcrumb"><a href="#/constructors">F1</a><span aria-hidden="true">›</span><a href="#/constructors">Constructors</a><span aria-hidden="true">›</span>' + esc(name) + '</nav>' + QK.playerHeader({ name: name, split: false, pos: 'Constructor', kicker: y + ' season' + (s.pos ? ' · P' + s.pos + ' in the constructors’ championship' : ''),
        team: { colour: PD.teamColourRaw(id), alt: PD.teamAlt(id) }, face: PD.teamAbbr(id), meta: lineup.map(function (d) { return PD.driverLink(d, { dot: false }); }), strip: strip, tags: tP && tP.qualified(id) ? [QK.tag('In the ' + y + ' peer group', 'signal')] : [] }) +
      '<div class="pd-links pd-mt">' + (lineup.length >= 2 ? '<a class="qk-btn" href="#/compare/drivers/' + encodeURIComponent(lineup[0]) + '/' + encodeURIComponent(lineup[1]) + '">Compare the drivers</a>' : '') +
      '<a class="qk-btn" href="#/compare/teams/' + encodeURIComponent(id) + '">Compare with another team</a><a class="qk-btn" href="#/value?tab=needs">Every team’s needs</a></div>';
    if (!t && !s.team && !lineup.length) { el.innerHTML = h + PD.empty(name + ' is not in the ' + y + ' data', PD.ok(teams) ? 'Pick another season.' : 'The team catalogue is not built yet.'); return; }
    h += PD.grid('<div class="qk-span-5">' + (tP ? PD.v2.pctCard(tP, id, PD.v2.TEAM_SET, { foot: '<span>Metrics chosen for year-to-year stability and what they predict</span><a href="#/glossary">Glossary →</a>' }) : '') + '</div>' +
      PD.card('Where the team sits', tP ? 'Every constructor in the ' + y + ' peer group; bars coloured by percentile, ' + esc(name) + ' and the median marked.' : '', (tP ? PD.v2.distSeg('tm-dist-m', [['car_race_pace', 'Car pace'], ['points_per_race', 'Points / race'], ['dnf_rate', 'DNF rate'], ['pit_lane_v_field', 'Pit lane'], ['strategy_gain', 'Strategy']]) : '') + PD.chartBox('tm-dist', 260, 'Peer distribution'), { span: 7 }), 'pd-mt');
    h += '<section class="qk-section pd-sec">' + PD.secHead(y + ' season', 'Line-up', y === PD.currentSeason() ? 'Current drivers, from the latest build.' : 'Drivers who raced for the team in ' + y + '.') + '<div class="qk-auto" style="--min:220px" id="tm-lineup"></div></section>';
    h += '<section class="qk-section pd-sec">' + PD.secHead('Top performers', 'Against the grid', 'Each of the team\'s drivers ranked against every qualified driver this season, on our driver rating first, then the driver metric set.') + '<div id="tm-top"></div></section>';
    h += PD.grid(
      PD.card('Car pace by race', 'The car’s share of lap time, % of a lap faster than the field, ±1 se shaded; the other cars faint.', PD.chartBox('tm-pace', 360), { span: 8, right: PD.seg('tm-pk', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') }) +
      PD.card('Title', 'Our chance and where the simulated seasons finish.', '<div id="tm-title"></div>' + PD.chartBox('tm-pd', 180), { span: 4 }) +
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

    // title
    PD.set('tm-title', PD.kpis([
      PD.kpi('Our chance', ch ? PD.pct(ch.p_title, ch.p_title > 0.99 ? 2 : 1) : '—', ch ? PD.int((season.championship || {}).n_sims) + ' simulated seasons' : 'season over', { signal: true }),
      PD.kpi('Expected', ch ? PD.num(ch.exp_points, 0) : '—', ch ? 'final points' : ''),
      PD.kpi('Magic number', ch && isNum(magicOf(ch)) ? PD.num(magicOf(ch), 0) : '—', 'points to clinch')
    ], 'pd-kpis-3'));
    if (ch && (ch.pos_dist || []).length) PD.ch.columns('tm-pd', { cats: ch.pos_dist.map(function (p, i) { return 'P' + (i + 1); }), series: [{ name: 'Share of seasons', data: ch.pos_dist, colour: PD.teamColour(id), fmt: function (v) { return PD.pct(v); } }], fmt: function (v) { return Math.round(v * 100) + '%'; }, xName: 'Championship position', yName: 'Share of seasons', label: 'Final position distribution' });
    else PD.ch.none('tm-pd', season && season.championship === null ? 'The season is over.' : 'No simulation for this season.');

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
        { xName: mx.label, yName: my.label, invX: !!mx.lower, invY: !!my.lower, xFmt: function (v) { return PD.num(v, 1); }, yFmt: function (v) { return PD.num(v, 1); }, label: 'Straight line against cornering' });
    } else PD.ch.none('tm-prof', 'Too few teams have both a top speed and a corner-speed figure this season (' + pids.length + '). Corner speed comes from processed OpenF1 telemetry (2023 on).');

    // needs
    needsBlock(needs, id);

    PD.set('tm-pct', t ? pctPanel(metrics, t.values, t.pct) : PD.muted('Not in the team catalogue.'));
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

PD.route('constructors', renderList);
PD.route('team', renderTeam);
})(window.PD);
