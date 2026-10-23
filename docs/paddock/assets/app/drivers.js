/* The Quant Paddock — Drivers: the list (#/drivers[/<y>]) and a driver (#/driver/<id>).
 * Driver page on kit v3 "Matchday" (MIGRATION_V3.md, after rk-player.js): a crumb; the player header with "The short
 * version" (this season's peer percentiles in plain English, the weak spot, early days); five tiles with percentile
 * chips; the percentile rail on the F1 headline set (PD.v2.DRIVER_SET, peers = drivers at the starts floor) with a
 * plain line per metric and last season's ring (the career file's current.prev_pct_pos when the build carries it,
 * else last season's catalogue, loaded when the rail scrolls in); beside it "How sure are we?" (where each metric
 * settles), race by race and "Their type" (similar driver-seasons, the closest this season, the team-mate); a compare
 * with the two closest this season and verdicts; the next and the last race; then "More on the driver": how the title
 * picture moved (title_history, with the 90% band), the peer distribution, grid and finish, points against our
 * expectation, pace rank, every metric (field or team-mate), the team-mate head to head, the race log, telemetry style;
 * and the career. Reads <y>/drivers.json, teams.json, season.json, drivers/<id>.json, elo.json, <y-1>/drivers.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var MIN_RACES = 5;

function teamOf(season, drivers, id) {
  var d = ((drivers || {}).drivers || {})[id];
  if (d && d.team) return d.team;
  var t = (season || {}).teams || {};
  var hit = Object.keys(t).filter(function (k) { return (t[k].drivers || []).indexOf(id) >= 0; })[0];
  return hit || PD.driverTeam(id);
}
function mates(season, drivers, id) {
  var team = teamOf(season, drivers, id);
  if (!team) return [];
  var set = [];
  ((((season || {}).teams || {})[team] || {}).drivers || []).forEach(function (x) { if (x !== id && set.indexOf(x) < 0) set.push(x); });
  var D = (drivers || {}).drivers || {};
  Object.keys(D).forEach(function (k) { if (k !== id && D[k].team === team && set.indexOf(k) < 0) set.push(k); });
  return set.sort(function (a, b) { return ((D[b] || {}).races || 0) - ((D[a] || {}).races || 0); });
}

// ── list ──────────────────────────────────────────────────────────────────

function renderList(el, params) {
  var y = isNum(params.year) ? params.year : PD.currentSeason();
  el.innerHTML = PD.pageHead('Season ' + y, 'Every driver, ' + y, 'Everyone who started a race: results, our title chances, percentiles against the season’s regular drivers and Elo. Search any driver since 1950 with /.', PD.yearPager('drivers', y)) + '<div id="dl-body">' + PD.empty('Loading', '') + '</div>';
  return Promise.all([PD.seasonData(y), PD.load('elo.json')]).then(function (res) {
    if (!PD.alive(el)) return;
    var drivers = res[0][0], season = res[0][2], elo = res[1];
    var stand = {};
    (((season || {}).standings || {}).drivers || []).forEach(function (s) { stand[s.driver] = s; });
    var champ = (((season || {}).championship || {}).drivers) || {};
    var D = (PD.ok(drivers) && drivers.drivers) || null;
    var ids = D ? Object.keys(D) : Object.keys(stand);
    if (!ids.length) { PD.set('dl-body', PD.notBuilt('The ' + y + ' driver list', drivers)); return; }
    var metrics = D ? drivers.metrics || [] : [];
    var meta = {};
    metrics.forEach(function (m) { meta[m.key] = m; });
    var heads = D ? ['driver_effect', 'quali_driver_effect', 'race_h2h', 'points_per_race', 'race_pace'].map(function (k) { return meta[k]; }).filter(Boolean) : [];
    var dP = D ? PD.v2.peer(drivers, 'drivers', season) : null;
    var maxR = Math.max.apply(null, ids.map(function (id) { return D ? (D[id].races || 0) : ((stand[id] || {}).races || 0); }).concat([0]));
    var floor = Math.min(MIN_RACES, Math.max(1, Math.floor(maxR / 2)));
    var curElo = (elo || {}).current || {};
    var h = PD.note('<b>Percentiles</b> rank a driver against the other regular drivers this season (' + (dP ? dP.floor + '+ starts' : 'a starts floor') + '): 90th means better than 90 in 100. <b>Elo</b> is a rating from every head-to-head: 1500 is average.') + PD.grid(
      PD.card('Pace against points', D && meta.race_pace ? 'Race pace (field percentile) against points per race; drivers with ' + floor + '+ races.' : 'Points per race; drivers with ' + floor + '+ races.', PD.chartBox('dl-sc', 400, 'Pace against points'), { span: 8 }) +
      PD.card('The best ever, by Elo', 'Peak field rating since 1950, top 15.', PD.chartBox('dl-elo', 400, 'All-time peak Elo'), { span: 4, foot: '<a href="#dl-elo-t">The top 50 →</a>' }) +
      PD.card('Every driver', dP ? 'Heat cells: percentile against ' + esc(dP.label) + ' (' + dP.n + ' drivers); blank below the floor.' : '', '<div class="pd-toolbar"><input id="dl-q" class="qk-input" type="search" placeholder="Filter drivers or teams…" aria-label="Filter drivers"></div><div id="dl-t"></div>', { span: 12, flush: true }) +
      PD.card('All-time Elo leaders', 'Peak ratings against the field, the team-mate and in qualifying.', '<div id="dl-elo-t"></div>', { span: 12, flush: true }), '');
    PD.set('dl-body', h);
    var rows = ids.map(function (id) {
      var d = D ? D[id] : {}, s = stand[id] || {};
      var r = { id: id, name: (d && d.name) || PD.driverName(id), team: (d && d.team) || s.team, tname: PD.teamAbbr((d && d.team) || s.team), pos: s.pos || 99, races: d ? d.races : null, points: s.points, wins: s.wins || 0, podiums: s.podiums || 0, poles: s.poles || 0,
        title: (champ[id] || {}).p_title, elo: (curElo[id] || ((season || {}).elo || {})[id] || {}).elo };
      heads.forEach(function (m) { r[m.key] = ((d || {}).values || {})[m.key]; r['p_' + m.key] = dP && dP.pct[id] ? dP.pct[id][m.key] : null; });
      return r;
    });
    var cols = [
      { key: 'pos', label: 'Pos', num: true, fmt: function (v) { return v < 99 ? String(v) : '—'; } },
      { key: 'name', label: 'Driver', type: 'entity', sub: 'tname', mark: function (r) { return r.team ? { name: PD.teamName(r.team), abbr: PD.teamAbbr(r.team), colour: PD.teamColour(r.team) } : null; }, href: function (r) { return PD.driverHref(r.id); } },
      { key: 'races', label: 'Races', num: true },
      { key: 'points', label: 'Pts', num: true, fmt: function (v) { return PD.pts(v); } },
      { key: 'wins', label: 'Wins', num: true }, { key: 'podiums', label: 'Pod', num: true }, { key: 'poles', label: 'Poles', num: true }
    ];
    if (Object.keys(champ).length) cols.push({ key: 'title', label: 'Title', type: 'bar', max: 1, tip: 'Our title chance', fmt: function (v) { return isNum(v) ? PD.pct(v) : '—'; } });
    heads.forEach(function (m) { cols.push({ key: m.key, label: PD.v2.label(meta, m.key), type: 'pctl', pctl: 'p_' + m.key, tip: PD.v2.tip(meta, m.key) + (m.lower ? ' (lower is better)' : ''), fmt: function (v) { return PD.v2.fmt(meta, m.key, v); } }); });
    cols.push({ key: 'elo', label: 'Elo', num: true, fmt: function (v) { return PD.num(v, 0); } });
    var tbl = QK.leaderboard(document.getElementById('dl-t'), { columns: cols, rows: rows, sort: { key: 'pos', dir: 'asc' }, dense: true, maxHeight: 640, rowHref: function (r) { return PD.driverHref(r.id); } });
    document.getElementById('dl-q').addEventListener('input', function (e) {
      var q = e.target.value.trim().toLowerCase();
      tbl.setRows(rows.filter(function (r) { return !q || (r.name + ' ' + PD.teamName(r.team)).toLowerCase().indexOf(q) >= 0; }));
    });
    // scatter
    var pts = rows.filter(function (r) { return (r.races || (stand[r.id] || {}).races || 0) >= floor || (!D && isNum(r.points)); }).map(function (r) {
      var races = r.races || 1;
      var x = D && isNum(r.p_race_pace) ? r.p_race_pace : (isNum(r.elo) ? r.elo : null);
      return x === null || !isNum(r.points) ? null : { x: x, y: r.points / races, name: r.name, short: PD.driverCode(r.id), colour: PD.teamColour(r.team), href: PD.driverHref(r.id), label: true, sub: PD.teamName(r.team) + ' · ' + races + ' races' };
    }).filter(Boolean);
    PD.ch.scatter('dl-sc', pts, { xName: D && meta.race_pace ? 'Race pace, field percentile' : 'Elo', yName: 'Points per race', xFmt: function (v) { return PD.num(v, 0); }, yFmt: function (v) { return PD.num(v, 1); }, emptyText: 'No percentiles for this season (the catalogue starts in 2018).', label: 'Pace against points' });
    var at = ((elo || {}).all_time || []).slice();
    PD.ch.hbars('dl-elo', at.slice(0, 15).map(function (x) { return { label: x.name, value: x.peak_field, href: PD.driverHref(x.driver), colour: PD.col('coral'), sub: (x.years || []).join('–') + ' · ' + x.races + ' races' }; }),
      { fmt: function (v) { return PD.num(v, 0); }, min: 1500, name: 'Peak field Elo', emptyText: 'No Elo history.', label: 'All-time Elo' });
    if (at.length) PD.table('dl-elo-t', [
      { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.driver, { name: v, dot: false }); } },
      { key: 'span', label: 'Years', sort: false },
      { key: 'races', label: 'Races', num: true },
      { key: 'peak_field', label: 'Peak field', num: true, fmt: function (v) { return '<b>' + PD.num(v, 0) + '</b>'; } },
      { key: 'peak_teammate', label: 'Peak v team-mate', num: true, fmt: function (v) { return PD.num(v, 0); } },
      { key: 'peak_quali', label: 'Peak quali', num: true, fmt: function (v) { return PD.num(v, 0); } }
    ], at.slice(0, 50).map(function (x) { return Object.assign({ span: (x.years || []).join('–') }, x); }), { sort: { key: 'peak_field', dir: 'desc' }, rank: true, maxHeight: 520 });
  });
}

// ── driver page ───────────────────────────────────────────────────────────


function renderDriver(el, params, state) {
  var id = params.id;
  var y = state.year || PD.currentSeason();
  el.innerHTML = PD.empty('Loading ' + PD.driverName(id), '');
  return Promise.all([PD.seasonData(y), PD.load('drivers/' + id + '.json'), PD.load('elo.json')]).then(function (res) {
    if (!PD.alive(el)) return null;
    var cat = res[0], career = res[1], elo = res[2];
    var inSeason = PD.ok(cat[0]) && cat[0].drivers && cat[0].drivers[id];
    if (!inSeason && career && (career.seasons || []).length) {
      var lastY = career.seasons.slice().sort(function (a, b) { return b.year - a.year; })[0].year;
      if (lastY !== y && lastY >= 2018) return PD.seasonData(lastY).then(function (r2) { if (PD.alive(el)) draw(el, id, lastY, r2, career, elo, y); });
    }
    draw(el, id, y, cat, career, elo, null);
    return null;
  });
}

function draw(el, id, y, cat, career, elo, askedY) {
  var drivers = cat[0], season = cat[2];
  var D = (PD.ok(drivers) && drivers.drivers) || {};
  var d = D[id] || null;
  var metrics = (drivers || {}).metrics || [];
  var idx = PD.index() || {};
  var info = Object.assign({}, PD.NAMES.drivers[id] || {}, (idx.drivers || {})[id] || {});
  var name = (d && d.name) || (career && career.name) || PD.driverName(id);
  var sur = PD.driverSurname(id);
  var team = (d && d.team) || teamOf(season, drivers, id) || info.team;
  var curTeam = y === PD.currentSeason() || askedY ? ((idx.drivers || {})[id] || {}).team : null;
  var tcol = team ? PD.tc(team) : 'var(--accent)';
  var ms = mates(season, drivers, id), mate = ms[0] || null;
  var stand = (((season || {}).standings || {}).drivers || []).filter(function (s) { return s.driver === id; })[0] || {};
  var ch = (((season || {}).championship || {}).drivers || {})[id] || null;
  var age = PD.ageOf(career && career.dob);
  var tot = (career || {}).totals || {};
  var curT = curTeam || team;
  var dP = PD.ok(drivers) ? PD.v2.peer(drivers, 'drivers', season) : null;
  var pc = dP && dP.pct[id] ? dP.pct[id] : {};
  var meta = PD.v2.metaMap(drivers);
  var races = d && isNum(d.races) ? d.races : 0;
  var V = PD.v2;

  /* "The short version": what the numbers say, in plain English, from this season's peer percentiles */
  function shortVersion() {
    if (!d || !races) return null;
    var t = sur + ' has ' + PD.pts(stand.points || 0) + ' point' + (stand.points === 1 ? '' : 's') + ' from ' + races + ' start' + (races === 1 ? '' : 's') + (stand.pos ? ', ' + PD.ordinal(stand.pos) + ' in the championship' : '') + '.';
    if (!dP || !dP.qualified(id)) return t + ' Short of the starts floor for percentiles so far, so read the rest lightly.';
    var rows = [];
    V.DRIVER_SET.forEach(function (g) { g[1].forEach(function (k) { if (isNum(pc[k])) rows.push([k, pc[k], V.label(meta, k)]); }); });
    var top = rows.filter(function (r) { return r[1] >= 90; }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 2);
    var low = rows.slice().sort(function (a, b) { return a[1] - b[1]; })[0];
    if (top.length) t += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of this season’s regular drivers for ' + top.map(function (r) { return V.lc(r[2]); }).join(' and ') + '.';
    else if (rows.length) { var avg = rows.reduce(function (s, r) { return s + r[1]; }, 0) / rows.length; t += avg >= 60 ? ' Above the middle of the pack on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack on the numbers that matter.' : ' Below the middle of the pack on most of the numbers that matter so far.'; }
    if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) t += ' The weak spot: ' + V.lc(low[2]) + ', in the ' + PD.ordinal(Math.round(low[1])) + ' percentile.';
    if (races < 6) t += ' Early days, so read it lightly.';
    return t;
  }

  var crumb = '<nav class="pd-crumb" aria-label="Breadcrumb"><a href="#/drivers">F1</a><span aria-hidden="true">›</span>' + (curT ? '<a href="' + PD.teamHref(curT) + '">' + esc(PD.teamName(curT)) + '</a><span aria-hidden="true">›</span>' : '') + esc(name) + '</nav>';
  var h = crumb + QK.playerHeader({ name: name, number: info.number, pos: 'Driver', kicker: [y + (races ? ' · ' + races + ' start' + (races === 1 ? '' : 's') + ' in' : ''), info.nationality || (career || {}).nationality || '', age !== null ? (curTeam || (career && (career.seasons || []).some(function (z) { return z.year >= PD.currentSeason() - 1; })) ? 'age ' + age : 'born ' + String(career.dob).slice(0, 4)) : ''].filter(Boolean).join(' · '),
      team: curT ? { name: PD.teamName(curT), abbr: PD.teamAbbr(curT), colour: PD.teamColour(curT), href: PD.teamHref(curT) } : null,
      meta: [info.code ? ['Code', info.code] : null, isNum(tot.races) ? ['Starts', String(tot.races)] : null, isNum(tot.races) ? ['Wins', String(tot.wins || 0)] : null, tot.titles ? ['Titles', String(tot.titles)] : null],
      tags: dP && dP.qualified(id) ? [QK.tag('In the ' + y + ' peer group', 'signal')] : [], short: shortVersion() }) +
    (askedY ? PD.note(esc(name) + ' did not race in ' + askedY + '; showing ' + y + ', the latest season with a driver catalogue.') : '');
  if (d) {
    h += '<div class="pd-tiles">' + PD.kpis([
      ch && ch.eliminated ? PD.kpi('Title chance', 'Out', 'can no longer catch the leader', { text: true }) : ch ? PD.kpi('Title chance', PD.pct(ch.p_title, ch.p_title > 0.99 ? 2 : 1), 'expected ' + PD.num(ch.exp_points, 0) + ' pts (90%: ' + PD.num(ch.p05, 0) + '–' + PD.num(ch.p95, 0) + ')', { signal: true, tip: 'Our chance of the drivers’ title, from the season simulation' })
        : PD.kpi('Championship', stand.pos ? PD.ordinal(stand.pos) : '—', isNum(stand.points) ? PD.pts(stand.points) + ' points' : ''),
      PD.kpi('Race pace v team-mate', isNum((d.values || {}).driver_effect) ? PD.signed(d.values.driver_effect, 3) + '%' : '—', 'of a lap · lower is faster', { pctl: pc.driver_effect, tip: V.tip(meta, 'driver_effect') }),
      PD.kpi('Qualifying pace v team-mate', isNum((d.values || {}).quali_driver_effect) ? PD.signed(d.values.quali_driver_effect, 3) + '%' : '—', 'of a lap · lower is faster', { pctl: pc.quali_driver_effect, tip: V.tip(meta, 'quali_driver_effect') }),
      PD.kpi('Points per race', isNum((d.values || {}).points_per_race) ? PD.num(d.values.points_per_race, 2) : '—', (stand.wins || 0) + ' wins · ' + (stand.podiums || 0) + ' podiums · ' + (stand.poles || 0) + ' poles', { pctl: pc.points_per_race }),
      PD.kpi('Race head-to-head v team-mate', isNum((d.values || {}).race_h2h) ? PD.pct(d.values.race_h2h, 0) : '—', mate ? 'of races ahead of ' + esc(PD.driverSurname(mate)) : 'of races ahead of the team-mate', { pctl: pc.race_h2h })
    ]) + '</div>';
    h += '<div class="pd-links pd-mt">' + (mate ? '<a class="qk-btn" href="#/compare/drivers/' + encodeURIComponent(id) + '/' + encodeURIComponent(mate) + '">Compare with ' + esc(PD.driverSurname(mate)) + '</a>' : '') +
      '<a class="qk-btn" href="#/compare/drivers/' + encodeURIComponent(id) + '">Compare with anyone</a><a class="qk-btn" href="#/lab">Driver lab</a>' + (curT ? '<a class="qk-btn" href="' + PD.teamHref(curT) + '">' + esc(PD.teamName(curT)) + '</a>' : '') + '</div>';

    /* How sure are we: how far the starts so far are from where each headline metric settles (f1.json m50) */
    var settle = [['driver_effect', 'race pace against the team-mate'], ['quali_driver_effect', 'qualifying pace against the team-mate'], ['race_h2h', 'the race head-to-head'], ['lap1_gain', 'lap-1 gains']]
      .filter(function (x) { return isNum(V.M50[x[0]]); }).map(function (x) { var at = Math.ceil(V.M50[x[0]]); return x[1] + ' after about <b>' + at + ' start' + (at === 1 ? '' : 's') + '</b>' + (races >= at ? ' (reached)' : ''); });
    var small = races < 8;
    var nums = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven'];
    var sureCard = '<article class="qk-card cream"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">' +
      esc(races ? (small ? nums[races] + ' start' + (races === 1 ? ' is' : 's is') + ' a small sample' : races + ' starts: the picture is settling') : 'No starts yet this season') + '</h3>' +
      '<p style="margin:0;color:var(--ink-2);font-size:15px">Team-mate numbers settle fastest because the car is the same. The hollow rings on the rail show last season, where there was one: dots next to their ring are the steady part of the profile.</p>' +
      (settle.length ? QK.note('Half the season-to-season noise is gone for ' + settle.join(', ').replace(/, ([^,]*)$/, ', and $1') + '.') : '') + '</div></article>';

    var rbr = (d.log || []).length ? PD.card('Race by race', 'Points each round this season; the best weekend is labelled.', PD.chartBox('dv-rbr', 240, 'Points each round')) : '';
    var sim = (d.similar || []).slice(0, 3);
    var near = dP ? V.nearest(dP, id, V.DRIVER_SET, 2) : [];
    var typeCard = sim.length || near.length || mate ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div>' +
      (sim.length ? '<h4 class="pd-h4">Drives most like (since 1996)</h4><ul class="pd-list pd-type">' + sim.map(function (x) { return '<li><a href="' + PD.driverHref(x.driver) + '">' + esc(x.name || PD.driverName(x.driver)) + '</a><span class="s">' + esc([x.year, x.team ? PD.teamName(x.team) : ''].filter(Boolean).join(' · ')) + '</span></li>'; }).join('') + '</ul>' : '') +
      (near.length ? '<h4 class="pd-h4">Closest this season</h4><ul class="pd-list pd-type">' + near.map(function (x) { return '<li>' + PD.driverLink(x.id) + '<a class="v" href="#/compare/drivers/' + encodeURIComponent(id) + '/' + encodeURIComponent(x.id) + '">Compare</a></li>'; }).join('') + '</ul>' : '') +
      (mate ? '<h4 class="pd-h4">Team-mate</h4><ul class="pd-list pd-type"><li>' + PD.driverLink(mate) + '<a class="v" href="#/compare/drivers/' + encodeURIComponent(id) + '/' + encodeURIComponent(mate) + '">Compare</a></li></ul>' : '') +
      QK.aside('Closest matches on the headline metrics: pace against the team-mate and the field, head-to-heads, points and starts.') + '</div></article>' : '';
    var rail = dP ? V.pctCard(dP, id, V.DRIVER_SET, { id: 'dv-rail', foot: '<span>Metrics chosen for year-to-year stability and what they predict</span><a href="#/glossary">Glossary →</a>' }) : '';
    h += '<section class="qk-section pd-sec"><div class="qk-gside"><div>' + rail + '</div><div class="pd-stack">' + sureCard + rbr + typeCard + '</div></div></section>';
    if (near.length) h += '<section class="qk-section pd-sec" id="dv-cmp-sec"></section>';
    h += '<section class="qk-section pd-sec" id="dv-nl" hidden><div class="qk-g2" id="dv-nl-g"></div></section>';
    var hist = ((season || {}).title_history || []).filter(function (x) { return x && isNum(x.after_round) && x.drivers && x.drivers[id]; });
    h += '<section class="qk-section pd-sec">' + QK.sectionHead({ kicker: 'More on the driver', title: 'Peers, form and the long view', sub: 'Where ' + esc(sur) + ' sits among this season’s drivers, round by round, every metric and the career.' }) +
      PD.grid((hist.length >= 3 && ch ? PD.card('How the title picture moved', 'Our expected final points after each round, with the band where 90% of simulated seasons end.', '<div id="dv-move" class="qk-chart" style="--h:280px" role="img" aria-label="Expected final points after each round"></div>', { span: 12 }) : '') +
        PD.card('Among peers', dP ? 'Every driver in the ' + y + ' peer group (' + dP.floor + '+ starts); bars coloured by percentile, ' + esc(sur) + ' and the median marked.' : '', (dP ? V.distSeg('dv-dist-m', [['driver_effect', 'Race pace v team-mate'], ['quali_driver_effect', 'Qualifying v team-mate'], ['race_h2h', 'Race H2H'], ['points_per_race', 'Points / race'], ['race_pace', 'Race pace v field']]) : '') + PD.chartBox('dv-dist', 260, 'Peer distribution'), { span: 12 }) +
        PD.card('Grid and finish', 'Each round of ' + y + '; crosses are retirements.', PD.chartBox('dv-pos', 280, 'Grid and finish'), { span: 4 }) +
        PD.card('Points v expected', 'Cumulative points against our pre-race expectation.', PD.chartBox('dv-pts', 280, 'Points against expected'), { span: 4 }) +
        PD.card('Race pace rank', 'Our lap-time model’s pace rank each round (1 = fastest).', PD.chartBox('dv-pace', 280, 'Race pace rank by round'), { span: 4 }) +
        PD.card('Every metric', metrics.length + ' metrics. Field: against every driver who started this season (stand-ins included). Team-mate: only against drivers in the same car.', '<div id="dv-pct"></div>', { span: 12, right: PD.seg('dv-pk', [['field', 'Field'], ['teammate', 'Team-mate']], 'field', 'Percentiles') }) +
        PD.card('Team-mate head to head', '<span id="dv-h2h-s"></span>', '<div id="dv-h2h"></div>', { span: 12, flush: true }) +
        PD.card('Race log', 'Every round. Pace is the race-pace effect in seconds a lap against the field (negative is faster); deg is tyre degradation by compound.', '<div id="dv-log"></div>', { span: 12, flush: true }) +
        PD.card('Telemetry style', 'How the driver uses the car, from OpenF1 car data (2023 on), with the field percentile.', '<div id="dv-style"></div>', { span: 12 }), 'pd-mt') + '</section>';
  } else {
    h += PD.empty(PD.ok(drivers) ? name + ' has no race in ' + y : 'The ' + y + ' driver catalogue is not built yet', 'The career is below.');
  }
  h += '<section class="qk-section pd-sec">' + PD.secHead('Since 1950', 'Career', '<span id="dv-car-s"></span>') + '<div id="dv-career"></div></section>';
  el.innerHTML = h;
  if (d) {
    season_(d, id, y, metrics, D, mate, ms, tcol, team, dP);
    raceByRace(d, team);
    ringsLater(el, id, y, career, dP);
    compareBlock(dP, id, near, y);
    nextLast(id, d, y, team);
    movement(season, id, team);
  }
  careerBlock(id, career);
}

/* Race by race: points each round in the team colour, the best weekend labelled in an italic annotation. */
function raceByRace(d, team) {
  var log = (d.log || []).slice().sort(function (a, b) { return a.round - b.round; });
  var node = document.getElementById('dv-rbr');
  if (!node || !log.length || !window.QKC) return;
  var bi = -1, best = -1;
  log.forEach(function (r, i) { if ((r.points || 0) > best) { best = r.points || 0; bi = i; } });
  var col = PD.tc(team);
  QKC.mount(node, function (T) {
    var xa = QKC.axis(T, { type: 'category', data: log.map(function (r) { return 'R' + r.round; }), split: false, line: true });
    var ya = QKC.axis(T, { min: 0 });
    var gB = 22 + QKC.nameAxis(xa, 'Round', 'bottom'), gT = 26 + QKC.nameAxis(ya, 'Points', 'side');
    return { grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
      tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: function (ps) { var r = log[ps[0].dataIndex]; return '<b>' + esc(r.name || ('Round ' + r.round)) + '</b><br>' + (PD.finished(r.status) ? 'P' + r.pos : esc(r.status || 'DNF')) + (isNum(r.grid) && r.grid > 0 ? ' from P' + r.grid : '') + ' · ' + PD.pts(r.points || 0) + ' pts'; } }),
      series: [{ type: 'bar', name: 'Points', barMaxWidth: 26, data: log.map(function (r, i) {
        var o = { value: r.points || 0, itemStyle: { color: col, borderRadius: [6, 6, 0, 0] } };
        if (i === bi && best > 0) o.label = Object.assign(QKC.annot(T), { show: true, position: 'top', formatter: (PD.finished(r.status) ? 'P' + r.pos : '') + ' · ' + PD.shortRace(r.name) });
        return o; }) }] };
  }, { label: 'Points each round this season' });
}

/* Last season's percentiles in the same peer group: the hollow rings on the rail. The career file's
   current.prev_pct_pos when the build carries it; else last season's catalogue, loaded when the rail scrolls in. */
function ringsLater(el, id, y, career, dP) {
  var host = document.getElementById('dv-rail');
  if (!host || !dP || !dP.qualified(id)) return;
  var paint = function (prev, n) {
    var old = document.getElementById('dv-rail');
    if (!old || !prev) return;
    old.outerHTML = PD.v2.pctCard(dP, id, PD.v2.DRIVER_SET, { id: 'dv-rail', prev: prev, ringLabel: 'last season' + (isNum(n) ? ' (' + n + ' starts)' : ''), foot: '<span>Metrics chosen for year-to-year stability and what they predict</span><a href="#/glossary">Glossary →</a>' });
  };
  var cur = (career || {}).current || {};
  /* the starts come from prev_peer (f1/analytics/drivers.prev_peer_pct: {year, races, floor, qualified}) */
  if (cur.prev_pct_pos && typeof cur.prev_pct_pos === 'object') { var pp = cur.prev_pct_pos, pr = cur.prev_peer || {}; paint(pp.pct || pp, isNum(pr.races) ? pr.races : (pp.races || pp.n)); return; }
  var fired = false;
  var go = function () {
    if (fired) return; fired = true;
    PD.load((y - 1) + '/drivers.json').then(function (cat) {
      if (!PD.alive(el) || !cat || !cat.drivers || !cat.drivers[id]) return;
      var P = PD.v2.peer(cat, 'drivers', null);
      if (!P.qualified(id)) return;
      paint(P.pct[id], cat.drivers[id].races);
    });
  };
  if (window.IntersectionObserver) { var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); } else go();
}

/* Compare: the driver and the two closest this season on the headline set, the best in each row highlighted, verdicts. */
function compareBlock(dP, id, near, y) {
  var host = document.getElementById('dv-cmp-sec');
  if (!host || !dP || !near.length) return;
  var ids = [id].concat(near.map(function (x) { return x.id; }));
  var names = ids.map(PD.driverSurname);
  var ents = ids.map(function (k) { var r = dP.rows[k] || {}; return { name: r.name || PD.driverName(k), href: PD.driverHref(k), colour: PD.teamColour(r.team), sub: [PD.teamName(r.team), (r.races || 0) + ' starts'].join(' · ') }; });
  host.innerHTML = QK.sectionHead({ kicker: 'Compare', title: names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?',
    sub: 'The closest matches on this season’s headline metrics, side by side against ' + esc(dP.label) + ' in ' + y + '. The best in each row is highlighted; the small pills are percentiles.',
    actions: '<a class="qk-more" href="#/compare/drivers/' + encodeURIComponent(ids[0]) + '/' + encodeURIComponent(ids[1]) + '">Open in Compare</a>' }) +
    '<article class="qk-card"><div class="qk-card-body">' + PD.v2.compare(dP, ids, PD.v2.DRIVER_SET, ents) + QK.verdicts(PD.v2.verdicts(ids.map(function () { return dP; }), ids, PD.v2.DRIVER_SET, names)) + '</div></article>';
}

/* Next and last race: our chances for the driver at the next Grand Prix, and how the last one went. */
function nextLast(id, d, y, team) {
  var idx = PD.index() || {};
  var nx = idx.next && idx.next.year === y ? idx.next : null;
  var log = (d.log || []).slice().sort(function (a, b) { return a.round - b.round; });
  var last = log[log.length - 1];
  var sur = PD.driverSurname(id);
  (nx ? PD.load(nx.year + '/races/' + nx.round + '.json') : Promise.resolve(null)).then(function (race) {
    var wrap = document.getElementById('dv-nl'), g = document.getElementById('dv-nl-g');
    if (!wrap || !g) return;
    var f = race && race.forecast ? ((race.forecast.post_quali && race.forecast.post_quali.drivers && race.forecast.post_quali.drivers[id]) ? race.forecast.post_quali : race.forecast.pre_quali) : null;
    var me = f && f.drivers ? f.drivers[id] : null;
    var out = '';
    if (nx) {
      out += '<div><div class="qk-kicker" style="margin-bottom:10px">Next up</div><a class="qk-card qk-feature pd-nl" href="' + PD.raceHref(nx.year, nx.round) + '" style="--tc:' + esc(PD.tc(team)) + '"><div class="qk-feature-meta"><span class="qk-pill">Round ' + nx.round + ' · ' + esc((nx.circuit || {}).locality || '') + '</span><span class="qk-badge">' + esc(PD.fmtDate(((nx.sessions || {}).race) || nx.date, { year: false, time: true })) + '</span></div>' +
        '<div class="pd-feat-name">' + esc(nx.name) + '</div>' +
        (me ? '<div class="qk-feature-big"><div class="big">' + PD.pct(me.p_podium, 0) + '</div><div class="say">chance <b>' + esc(sur) + '</b> finishes on the podium. Win: <b>' + PD.pct(me.p_win, me.p_win < 0.1 ? 1 : 0) + '</b>, points: <b>' + PD.pct(me.p_points, 0) + '</b>.</div></div>' +
          QK.note('<b>How sure are we?</b> We expect P' + PD.num(me.exp_pos, 1) + ' on average; a retirement is ' + PD.pct(me.p_dnf, 0) + ' in our numbers.') : QK.note('Our forecast for the weekend is built once the race is near.')) + '</a></div>';
    }
    if (last) {
      var fin = PD.finished(last.status);
      out += '<div><div class="qk-kicker" style="margin-bottom:10px">Last time out</div><a class="qk-card qk-feature pd-nl" href="' + PD.raceHref(y, last.round) + '"><div class="qk-feature-meta"><span class="qk-pill">Round ' + last.round + '</span><span class="qk-badge final">Result</span></div>' +
        '<div class="pd-feat-name">' + esc(last.name || ('Round ' + last.round)) + '</div>' +
        '<div class="qk-feature-big"><div class="big pd-big-ink">' + (fin ? 'P' + last.pos : 'DNF') + '</div><div class="say">' + (isNum(last.grid) && last.grid > 0 ? 'from P' + last.grid + ' on the grid' : 'from the pit lane') + ', <b>' + PD.pts(last.points || 0) + ' point' + (last.points === 1 ? '' : 's') + '</b>.</div></div>' +
        QK.note((isNum(last.exp_points) ? 'We expected about <b>' + PD.num(last.exp_points, 1) + ' points</b> before the race. ' : '') + (isNum(last.pace_rank) ? 'Race pace ranked ' + PD.ordinal(last.pace_rank) + ' in our lap-time model.' : '')) + '</a></div>';
    }
    if (out) { g.innerHTML = out; wrap.hidden = false; }
  });
}

/* Movement: our expected final points after each recorded round, with the 5th-95th percentile band (title_history). */
function movement(season, id, team) {
  var node = document.getElementById('dv-move');
  if (!node) return;
  var H = (season.title_history || []).filter(function (x) { return x && isNum(x.after_round) && x.drivers && x.drivers[id]; }).sort(function (a, b) { return a.after_round - b.after_round; });
  var get = function (h, k) { var r = h.drivers[id]; return r && isNum(r[k]) ? r[k] : null; };
  QKC.forecast(node, { x: H.map(function (h) { return 'R' + h.after_round; }), xType: 'category', xName: 'After round', yName: 'Expected final points (5th–95th percentile band)', yMin: 0, yMax: 'auto',
    yFmt: function (v) { return PD.num(v, 0); }, today: 'R' + H[H.length - 1].after_round,
    series: [{ name: PD.driverName(id), label: PD.driverCode(id), color: PD.teamColour(team), data: H.map(function (h) { return get(h, 'exp_points'); }), band: { lo: H.map(function (h) { return get(h, 'p05'); }), hi: H.map(function (h) { return get(h, 'p95'); }) } }],
    label: 'Expected final points after each round' });
}

function season_(d, id, y, metrics, D, mate, ms, tcol, team, dP) {
  var log = (d.log || []).slice().sort(function (a, b) { return a.round - b.round; });
  if (log.length) {
    PD.ch.lines('dv-pos', [
      { name: 'Grid', data: log.map(function (r) { return [r.round, isNum(r.grid) && r.grid > 0 ? r.grid : null]; }), colour: PD.col('grey'), dash: true, symbols: true },
      { name: 'Finish', data: log.map(function (r) { return [r.round, PD.finished(r.status) ? r.pos : null]; }), colour: PD.teamColour(team), symbols: true, width: 2.5 }
    ], { inverse: true, yMin: 1, yScale: false, xName: 'Round', yName: 'Position', xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { var r = log.filter(function (z) { return z.round === +v; })[0]; return r ? 'R' + v + ' ' + PD.shortRace(r.name) + (PD.finished(r.status) ? '' : ' · ' + r.status) : v; }, yFmt: function (v) { return 'P' + Math.round(v); }, label: 'Grid and finish' });
    var cp = 0, ce = 0, any = false;
    var actual = [], exp = [];
    log.forEach(function (r) { cp += r.points || 0; actual.push([r.round, cp]); if (isNum(r.exp_points)) { any = true; ce += r.exp_points; exp.push([r.round, ce]); } });
    PD.ch.lines('dv-pts', [{ name: 'Points', data: actual, colour: PD.teamColour(team), width: 2.5, area: true }].concat(any ? [{ name: 'Expected', data: exp, colour: PD.col('grey'), dash: true }] : []),
      { xName: 'Round', yName: 'Points, cumulative', xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { return 'After round ' + v; }, yFmt: function (v) { return PD.num(v, 0); }, yScale: false, label: 'Points against expected' });
    PD.ch.lines('dv-pace', [{ name: 'Pace rank', data: log.map(function (r) { return [r.round, isNum(r.pace_rank) ? r.pace_rank : null]; }), colour: PD.teamColour(team), symbols: true, width: 2 }],
      { inverse: true, yMin: 1, yScale: false, xName: 'Round', yName: 'Race pace rank', xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { var r = log.filter(function (z) { return z.round === +v; })[0]; return r ? 'R' + v + ' ' + PD.shortRace(r.name) + (isNum(r.pace) ? ' · ' + PD.signed(r.pace, 3) + ' s/lap' : '') : v; }, yFmt: function (v) { return 'P' + Math.round(v); }, label: 'Race pace rank by round' });
  } else ['dv-pos', 'dv-pts', 'dv-pace'].forEach(function (k) { PD.ch.none(k, 'No races yet.'); });
  var drawPct = function (src) { PD.set('dv-pct', PD.pctPanel(metrics, d.values, src === 'teammate' ? d.pct_teammate : d.pct, { note: src === 'teammate' ? 'Team-mate percentile: 100 is the best figure among drivers sharing the car; with two drivers it sits near 0 or 100.' : 'Field percentile, 100 = best. ↓ marks metrics where lower is better; the bar already accounts for it.' })); };
  drawPct('field');
  PD.wireSeg(document, 'dv-pk', drawPct);
  var mrow = mate && D[mate];
  var pc = PD.pairColours(PD.teamColour(team), mrow ? PD.col('grey') : PD.col('coral'));
  if (dP && document.getElementById('dv-dist')) {
    var drawD = function (key) { PD.v2.distribution('#dv-dist', dP, key, [{ x: (d.values || {})[key], label: PD.driverSurname(id) }]); };
    drawD('driver_effect');
    PD.wireSeg(document, 'dv-dist-m', drawD);
  }
  if (mrow) {
    var hh = PD.h2h(d.log, mrow.log);
    var nA = PD.driverSurname(id), nB = PD.driverSurname(mate);
    PD.set('dv-h2h-s', 'Against ' + PD.driverLink(mate, { dot: false }) + ' in the ' + hh.both + ' rounds both started' + (ms.length > 1 ? ' (also: ' + ms.slice(1).map(function (x) { return PD.driverLink(x, { dot: false }); }).join(', ') + ')' : ''));
    PD.set('dv-h2h', '<div class="pd-pad pd-h2h-grid">' + PD.h2hBar('Qualifying', hh.quali[0], hh.quali[1], pc[0], pc[1], nA, nB) + PD.h2hBar('Race (ahead when classified, or finished when the other did not)', hh.race[0], hh.race[1], pc[0], pc[1], nA, nB) +
      PD.h2hBar('Points in shared rounds', hh.points[0], hh.points[1], pc[0], pc[1], nA, nB) + '</div><div id="dv-h2h-t"></div>');
    PD.table('dv-h2h-t', [
      { key: 'round', label: 'Rd', num: true },
      { key: 'name', label: 'Race', sticky: true, fmt: function (v, r) { return PD.raceLink(y, r.round, PD.shortRace(v)); } },
      { key: 'qa', label: 'Q ' + nA, num: true, fmt: function (v, r) { return isNum(v) ? (v < r.qb ? '<b>' + v + '</b>' : String(v)) : '—'; } },
      { key: 'qb', label: 'Q ' + nB, num: true, fmt: function (v, r) { return isNum(v) ? (v < r.qa ? '<b>' + v + '</b>' : String(v)) : '—'; } },
      { key: 'pa', label: nA, num: true, fmt: function (v, r) { return PD.posHTML(v, r.sa); } },
      { key: 'pb', label: nB, num: true, fmt: function (v, r) { return PD.posHTML(v, r.sb); } }
    ], hh.rows.map(function (p) { return { round: p[0].round, name: p[0].name || '', qa: p[0].quali_pos, qb: p[1].quali_pos, pa: p[0].pos, pb: p[1].pos, sa: p[0].status, sb: p[1].status }; }), { sort: { key: 'round', dir: 'desc' }, maxHeight: 360 });
  } else PD.set('dv-h2h', PD.muted('No team-mate in the catalogue this season.'));
  PD.table('dv-log', [
    { key: 'round', label: 'Rd', num: true },
    { key: 'name', label: 'Race', sticky: true, fmt: function (v, r) { return PD.raceLink(y, r.round, PD.shortRace(v || 'Round ' + r.round)); } },
    { key: 'quali_pos', label: 'Quali', num: true }, { key: 'grid', label: 'Grid', num: true },
    { key: 'fpos', label: 'Finish', num: true, fmt: function (v, r) { return PD.posHTML(r.pos, r.status); } },
    { key: 'pos_gained', label: 'Gained', num: true, fmt: function (v) { return PD.deltaHTML(v); } },
    { key: 'lap1_gain', label: 'Lap 1', num: true, fmt: function (v) { return PD.deltaHTML(v); } },
    { key: 'overtakes', label: 'Overtakes', num: true }, { key: 'pit_stops', label: 'Stops', num: true },
    { key: 'pace', label: 'Pace', num: true, fmt: function (v) { return isNum(v) ? PD.signed(v, 3) : '—'; } },
    { key: 'pace_rank', label: 'Pace rank', num: true },
    { key: 'degm', label: 'Deg', num: true, fmt: function (v, r) { var deg = r.deg; if (!deg || typeof deg !== 'object') return isNum(deg) ? PD.num(deg, 3) : '—'; return Object.keys(deg).filter(function (k) { return isNum(deg[k]); }).map(function (k) { return '<span title="' + esc(k) + '" style="color:' + PD.compoundColour(k) + '">●</span>' + PD.num(deg[k], 3); }).join(' ') || '—'; } },
    { key: 'points', label: 'Pts', num: true, fmt: function (v) { return v ? '<b>' + PD.pts(v) + '</b>' : '0'; } }
  ], log.map(function (r) { var deg = r.deg; var dm = deg && typeof deg === 'object' ? PD.mean(Object.keys(deg).map(function (k) { return deg[k]; })) : deg; return Object.assign({}, r, { fpos: PD.finished(r.status) ? r.pos : 99, degm: dm }); }), { sort: { key: 'round', dir: 'desc' } });
  var style = metrics.filter(function (m) { return /telemetry|style/i.test(m.group || ''); });
  PD.set('dv-style', style.length && style.some(function (m) { return isNum((d.values || {})[m.key]); }) ? PD.kpis(style.map(function (m) {
    var v = (d.values || {})[m.key], p = (d.pct || {})[m.key];
    return PD.kpi(m.label, PD.fmtVal(v, m.fmt) + ' ' + PD.pctl(p), esc(m.desc || ''), { tip: m.desc });
  })) : PD.muted('No telemetry-style metrics for ' + y + ' (OpenF1 car data starts in 2023).'));
}

function careerBlock(id, career) {
  var host = document.getElementById('dv-career');
  if (!host) return;
  if (!career || career.ok === false) { host.innerHTML = PD.notBuilt('The career file', career); return; }
  var seasons = (career.seasons || []).slice().sort(function (a, b) { return a.year - b.year; });
  var tot = career.totals || {};
  var sum = function (k) { return seasons.reduce(function (s, r) { return s + (r[k] || 0); }, 0); };
  PD.set('dv-car-s', seasons.length + ' season' + (seasons.length === 1 ? '' : 's') + (seasons.length ? ', ' + seasons[0].year + '–' + seasons[seasons.length - 1].year : '') + ' · results since 1950 from Jolpica');
  host.innerHTML = PD.kpis([
    PD.kpi('Starts', String(isNum(tot.races) ? tot.races : sum('races'))), PD.kpi('Wins', String(isNum(tot.wins) ? tot.wins : sum('wins'))), PD.kpi('Podiums', String(isNum(tot.podiums) ? tot.podiums : sum('podiums'))),
    PD.kpi('Poles', String(isNum(tot.poles) ? tot.poles : sum('poles'))), PD.kpi('Points', PD.pts(isNum(tot.points) ? tot.points : sum('points'))), PD.kpi('Titles', String(isNum(tot.titles) ? tot.titles : seasons.filter(function (s) { return s.pos === 1; }).length)),
    PD.kpi('Peak Elo', isNum(tot.peak_elo) ? PD.num(tot.peak_elo, 0) : '—', isNum(tot.peak_elo_teammate) ? 'v team-mate ' + PD.num(tot.peak_elo_teammate, 0) : '')
  ]) + PD.grid(
    PD.card('Season by season', 'Points (bars, team colours) and championship position (line).', PD.chartBox('dc-seasons', 300), { span: 7 }) +
    PD.card('Elo through the career', 'Field Elo after every race, and Elo against the team-mate.', PD.chartBox('dc-elo', 300), { span: 5 }) +
    PD.card('Seasons', '', '<div id="dc-t"></div>', { span: 7, flush: true }) +
    PD.card('Team-mates', 'Qualifying and race head to head with every team-mate.', '<div id="dc-m"></div>', { span: 5, flush: true }), 'pd-mt');
  if (seasons.length) PD.ch.columns('dc-seasons', { cats: seasons.map(function (s) { return String(s.year); }), xName: 'Season', y2Name: 'Position', y2Inverse: true, y2Max: Math.max.apply(null, seasons.map(function (s) { return s.pos || 0; }).concat([5])),
    series: [{ name: 'Points', data: seasons.map(function (s) { return s.points || 0; }), colours: seasons.map(function (s) { return PD.teamColour(s.team); }), fmt: function (v) { return PD.pts(v); } },
      { name: 'Championship position', type: 'line', axis: 1, data: seasons.map(function (s) { return s.pos || null; }), colour: PD.col('sun'), fmt: function (v) { return 'P' + v; } }],
    yName: 'Points', fmt: function (v) { return PD.num(v, 0); }, tipLabel: function (i) { var s = seasons[i]; return s.year + ' · ' + PD.teamName(s.team) + ' · ' + s.races + ' races, ' + s.wins + ' wins'; }, rotate: seasons.length > 14 ? 45 : 0, label: 'Season by season' });
  else PD.ch.none('dc-seasons', 'No seasons.');
  var e = career.elo || [];
  if (e.length) {
    var xs = e.map(function (r) { return r[0] + (r[1] - 1) / 25; });
    PD.ch.lines('dc-elo', [{ name: 'Field', data: e.map(function (r, i) { return [xs[i], r[2]]; }), colour: PD.col('sky') }, { name: 'v team-mate', data: e.map(function (r, i) { return [xs[i], r[3]]; }), colour: PD.col('coral') }],
      { xName: 'Season', yName: 'Elo rating', xFmt: function (v) { return String(Math.floor(v)); }, xLabel: function (v) { var y0 = Math.floor(v); return y0 + ' R' + (Math.round((v - y0) * 25) + 1); }, yFmt: function (v) { return PD.num(v, 0); }, label: 'Elo history' });
  } else PD.ch.none('dc-elo', 'No Elo history.');
  PD.table('dc-t', [
    { key: 'year', label: 'Year', num: true, fmt: function (v) { return '<a class="pd-link" href="#/standings/' + v + '">' + v + '</a>'; } },
    { key: 'team', label: 'Team', sticky: true, fmt: function (v) { return PD.teamLink(v); } },
    { key: 'races', label: 'Races', num: true }, { key: 'wins', label: 'Wins', num: true }, { key: 'podiums', label: 'Pod', num: true }, { key: 'poles', label: 'Poles', num: true },
    { key: 'points', label: 'Pts', num: true, fmt: function (v) { return PD.pts(v); } },
    { key: 'pos', label: 'Pos', num: true, fmt: function (v) { return v ? (v === 1 ? '<b class="pd-champ">1</b>' : String(v)) : '—'; } }
  ], seasons, { sort: { key: 'year', dir: 'desc' }, maxHeight: 420 });
  var tm = (career.teammates || []).slice();
  if (tm.length) PD.table('dc-m', [
    { key: 'year', label: 'Year', num: true, fmt: String },
    { key: 'teammate', label: 'Team-mate', sticky: true, fmt: function (v) { return PD.driverLink(v, { dot: false }); } },
    { key: 'q', label: 'Quali', num: true, fmt: function (v, r) { return '<b>' + r.qa + '</b>–' + r.qb; } },
    { key: 'r', label: 'Race', num: true, fmt: function (v, r) { return '<b>' + r.ra + '</b>–' + r.rb; } },
    { key: 'c', label: '', sort: false, fmt: function (v, r) { return '<a class="pd-link" href="#/compare/drivers/' + encodeURIComponent(id) + '/' + encodeURIComponent(r.teammate) + '">compare →</a>'; } }
  ], tm.map(function (r) { var q = r.h2h_quali || [0, 0], rc = r.h2h_race || [0, 0]; return { year: r.year, teammate: r.teammate, qa: q[0], qb: q[1], ra: rc[0], rb: rc[1], q: q[0] - q[1], r: rc[0] - rc[1] }; }), { sort: { key: 'year', dir: 'desc' }, maxHeight: 420 });
  else PD.set('dc-m', PD.muted('No team-mate record.'));
}

PD.route('drivers', renderList);
PD.route('driver', renderDriver);
})(window.PD);
