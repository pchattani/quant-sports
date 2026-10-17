/* The Quant Paddock — Overview (#/): the next race with a live countdown, who wins it (model against
 * the market), the title fight, the fastest cars and drivers right now, how the favourites have fared,
 * last race and the fantasy picks. Charts first, words second.
 * Reads index.json, <y>/season.json, <y>/races/<next>.json, markets.json, <y>/value.json, <y>/fantasy.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var SESSION_LABEL = { fp1: 'Practice 1', fp2: 'Practice 2', fp3: 'Practice 3', sprint_quali: 'Sprint qualifying', sprint_shootout: 'Sprint shootout', sprint: 'Sprint', quali: 'Qualifying', qualifying: 'Qualifying', race: 'Grand Prix' };
var SESSION_LEN_MIN = { fp1: 60, fp2: 60, fp3: 60, sprint_quali: 45, sprint_shootout: 45, sprint: 40, quali: 60, qualifying: 60, race: 120 };

function sessionsOf(next) {
  var s = (next && next.sessions) || {};
  return Object.keys(s).filter(function (k) { return s[k]; }).map(function (k) { return { key: k, label: SESSION_LABEL[k] || PD.titleCase(k), t: PD.parseDate(s[k]), iso: s[k] }; })
    .filter(function (x) { return x.t; }).sort(function (a, b) { return a.t - b.t; });
}
PD.sessionsOf = sessionsOf;
PD.SESSION_LEN_MIN = SESSION_LEN_MIN;
function tzName() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'; } catch (e) { return 'local'; } }

/* Countdown + schedule, ticking every second while the page is open. */
function weekendClock(list, cdId, schedId) {
  function tick() {
    var now = Date.now();
    var upcoming = list.filter(function (s) { return s.t.getTime() > now; })[0];
    var live = list.filter(function (s) { return s.t.getTime() <= now && now < s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000; })[0];
    var cd = document.getElementById(cdId);
    if (!cd) return;
    if (live) cd.innerHTML = '<div class="pd-cd-l">Now</div><div class="pd-cd-v"><span class="qk-badge live">Live</span> ' + esc(live.label) + '</div><div class="pd-cd-s">Started ' + esc(PD.fmtTime(live.iso)) + '</div>';
    else if (upcoming) cd.innerHTML = '<div class="pd-cd-l">' + esc(upcoming.label) + ' starts in</div><div class="pd-cd-v">' + esc(PD.countdown(upcoming.iso, now)) + '</div><div class="pd-cd-s">' + esc(PD.fmtDate(upcoming.iso, { year: false, time: true })) + ', your time</div>';
    else cd.innerHTML = '<div class="pd-cd-l">Weekend</div><div class="pd-cd-v">Sessions complete</div><div class="pd-cd-s">Results arrive with the next build.</div>';
    var sch = document.getElementById(schedId);
    if (sch) sch.innerHTML = list.map(function (s) {
      var past = s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000 < now;
      var on = (upcoming && s.key === upcoming.key) || (live && live.key === s.key);
      return '<li class="' + (past ? 'past' : '') + (on ? ' on' : '') + '"><span>' + esc(PD.fmtDate(s.iso, { year: false })) + '</span><b>' + esc(s.label) + '</b><span class="t">' + esc(PD.fmtTime(s.iso)) + '</span></li>';
    }).join('') || '<li>Session times not published yet.</li>';
  }
  tick();
  PD.interval(tick, 1000);
}
PD.weekendClock = weekendClock;

function titleRows(season, markets, kind) {
  var ch = PD.ok(season) && season.championship ? season.championship[kind] || {} : {};
  var mk = (markets || {})[kind === 'drivers' ? 'drivers_title' : 'constructors_title'] || {};
  var prices = mk.available ? (mk.prices || {}) : {};
  return Object.keys(ch).filter(function (id) { return (ch[id].p_title || 0) >= 0.0005 || (prices[id] || 0) >= 0.001; })
    .sort(function (a, b) { return (ch[b].p_title - ch[a].p_title) || ((prices[b] || 0) - (prices[a] || 0)); })
    .map(function (id) { return { id: id, model: ch[id].p_title, market: prices[id], c: ch[id] }; });
}

function render(el) {
  var idx = PD.index() || {};
  var y = idx.current_season || PD.currentSeason();
  var next = idx.next, last = idx.last;
  el.innerHTML = '<section class="pd-hero" id="ov-hero">' + PD.empty('Loading', '') + '</section>' +
    '<div class="qk-grid pd-ov">' +
      PD.card('<span id="ov-who-t">Who wins next?</span>', '<span id="ov-who-s">Model win probability against the de-vigged market.</span>', PD.chartBox('ov-who', 420), { span: 8, id: 'ov-who-card' }) +
      PD.card('Race forecast', '<span id="ov-fc-s"></span>', '<div id="ov-fc"></div>', { span: 4, flush: true }) +
      PD.card('The title fight', 'Points after each round, top six.', PD.chartBox('ov-prog', 340), { span: 8 }) +
      PD.card('Standings', '', '<div id="ov-std"></div>', { span: 4, flush: true, right: PD.seg('ov-std-k', [['drivers', 'Drivers'], ['constructors', 'Teams']], 'drivers', 'Standings') }) +
      PD.card('Championship odds', '<span id="ov-odds-s">Share of simulated seasons won; orange tick = market.</span>', PD.chartBox('ov-odds', 300), { span: 6, right: PD.seg('ov-odds-k', [['drivers', 'Drivers'], ['constructors', 'Teams']], 'drivers', 'Title') }) +
      PD.card('Fastest cars right now', 'Car race pace at the latest round, % of a lap against the field (right = faster), ±1 se.', PD.chartBox('ov-cars', 300), { span: 6 }) +
      PD.card('Best drivers this season', 'Race pace above the team-mate, % of a lap (the driver alone), ±1 se; 5+ races.', PD.chartBox('ov-drv', 300), { span: 6 }) +
      PD.card('How the favourite fared', 'The model’s pre-race favourite each round: its win probability, filled when it won.', PD.chartBox('ov-fav', 300), { span: 6 }) +
      PD.card('Last race', '', '<div id="ov-last"></div>', { span: 6 }) +
      PD.card('Fantasy: top projections', 'Expected points next weekend with our scoring table.', PD.chartBox('ov-fan', 300), { span: 6, foot: '<a href="#/fantasy">All picks, value and the schedule →</a>' }) +
    '</div>';
  var raceP = next ? PD.load(next.year + '/races/' + next.round + '.json') : Promise.resolve(null);
  return Promise.all([PD.load(y + '/season.json'), PD.load('markets.json'), raceP, PD.load(y + '/value.json'), PD.load(y + '/fantasy.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var season = arr[0], markets = arr[1], race = arr[2], value = arr[3], fan = arr[4];
    hero(idx, season, markets);
    whoWins(next, race, markets);
    progression(season);
    standings(season);
    odds(season, markets);
    cars(value);
    bestDrivers(value);
    favourites(season);
    lastRace(last, season);
    fantasy(fan);
  });
}

function hero(idx, season, markets) {
  var next = idx.next, y = idx.current_season;
  var st = PD.ok(season) ? (season.standings || {}).drivers || [] : [];
  var ct = PD.ok(season) ? (season.standings || {}).constructors || [] : [];
  var lead = st[0], second = st[1];
  var dr = titleRows(season, markets, 'drivers');
  var fav = dr[0];
  var left;
  if (next) {
    var circ = next.circuit || {};
    left = '<div class="pd-hero-main"><div class="qk-kicker">Next up · ' + esc(next.year) + ' round ' + esc(next.round) + ' of ' + esc((season || {}).rounds_total || '') + '</div>' +
      '<h1 class="pd-hero-title"><a href="' + PD.raceHref(next.year, next.round) + '">' + esc(next.name) + '</a></h1>' +
      '<div class="pd-hero-sub">' + PD.circuitLink(circ.id, circ.name) + (circ.locality ? ' · ' + esc(circ.locality) : '') + (circ.country ? ', ' + esc(circ.country) : '') + ' · ' + esc(PD.fmtDate(next.date, { year: false })) + '</div>' +
      '<div class="pd-hero-clock"><div class="pd-cd" id="ov-cd"></div><ul class="pd-sched" id="ov-sched" aria-label="Weekend schedule in ' + esc(tzName()) + ' time"></ul></div>' +
      '<div class="pd-hero-links"><a class="qk-btn primary" href="' + PD.raceHref(next.year, next.round) + '">Race centre</a><a class="qk-btn" href="#/races">Calendar</a></div></div>';
  } else {
    var meta = (idx.seasons_meta || {})[String(y)] || {};
    left = '<div class="pd-hero-main"><div class="qk-kicker">' + esc(y) + ' season complete</div><h1 class="pd-hero-title">' + (meta.champion ? esc(PD.driverName(meta.champion)) + ' is champion' : 'The season is over') + '</h1>' +
      '<div class="pd-hero-sub">' + (meta.constructors_champion ? 'Constructors: ' + PD.teamLink(meta.constructors_champion) : '') + '</div>' +
      '<div class="pd-hero-links"><a class="qk-btn primary" href="#/standings">Final standings</a></div></div>';
  }
  var prog = PD.ok(season) && lead ? ((season.progression || {}).drivers || {})[lead.driver] : null;
  var tiles = [
    PD.kpi('Championship leader', lead ? PD.driverLink(lead.driver, { team: lead.team }) : '—', lead ? PD.pts(lead.points) + ' pts' + (second ? ' · ' + PD.pts(lead.points - second.points) + ' clear of ' + esc(PD.driverCode(second.driver)) : '') : '', { text: true, spark: prog ? window.QK.spark(prog, { color: PD.tc(lead.team), w: 120, h: 30 }) : '' }),
    PD.kpi('Title favourite', fav ? esc(PD.pct(fav.model, fav.model > 0.99 ? 2 : 1)) : '—', fav ? esc(PD.driverName(fav.id)) + (isNum(fav.market) ? ' · market ' + PD.pct(fav.market) : '') : (season && !season.championship ? 'season decided' : '')),
    PD.kpi('Constructors', ct[0] ? PD.teamLink(ct[0].team) : '—', ct[0] ? PD.pts(ct[0].points) + ' pts' + (ct[1] ? ' · ' + PD.pts(ct[0].points - ct[1].points) + ' clear' : '') : '', { text: true }),
    PD.kpi('Rounds run', PD.ok(season) ? season.rounds_done + ' / ' + season.rounds_total : '—', PD.ok(season) ? (season.calendar || []).filter(function (c) { return c.sprint; }).length + ' sprint weekends' : '')
  ];
  PD.set('ov-hero', left + '<div class="pd-hero-side">' + PD.kpis(tiles, 'pd-kpis-2') + '</div>');
  if (next) weekendClock(sessionsOf(next), 'ov-cd', 'ov-sched');
}

function whoWins(next, race, markets) {
  if (!next) { PD.set('ov-who-t', 'The season is over'); PD.ch.none('ov-who', 'No race left this season.'); PD.set('ov-fc', PD.muted('No race left this season.')); return; }
  PD.set('ov-who-t', 'Who wins the ' + esc(next.name) + '?');
  var f = PD.ok(race) && race.forecast ? race.forecast : null;
  var post = f && f.post_quali && f.post_quali.drivers && Object.keys(f.post_quali.drivers).length ? f.post_quali : null;
  var sim = post || (f && f.pre_quali);
  if (!sim || !sim.drivers) { PD.ch.none('ov-who', 'The forecast for ' + next.name + ' is not built yet.'); PD.set('ov-fc', PD.muted('Not built yet.')); return; }
  var nr = (markets || {}).next_race || {};
  var mkt = nr.year === next.year && nr.round === next.round && nr.prices && Object.keys(nr.prices).length ? nr.prices : null;
  var ds = sim.drivers;
  var ids = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
  PD.set('ov-who-s', (post ? 'After qualifying' : 'Before qualifying') + (isNum(sim.p_sc) ? ' · P(safety car) ' + PD.pct(sim.p_sc, 0) : '') + (mkt ? ' · blue model, orange market' : ' · no market price yet'));
  PD.set('ov-fc-s', (sim.n ? Number(sim.n).toLocaleString('en-GB') + ' simulated races' : ''));
  if (mkt) {
    var top = ids.concat(Object.keys(mkt).filter(function (k) { return ids.indexOf(k) < 0; })).filter(function (id) { return (ds[id] || {}).p_win >= 0.01 || (mkt[id] || 0) >= 0.02; })
      .sort(function (a, b) { return Math.max((ds[b] || {}).p_win || 0, mkt[b] || 0) - Math.max((ds[a] || {}).p_win || 0, mkt[a] || 0); }).slice(0, 10);
    window.QKC.dumbbell(document.getElementById('ov-who'), { rows: top.map(function (id) { return { label: PD.driverName(id), a: (ds[id] || {}).p_win || 0, b: mkt[id] || 0, href: PD.driverHref(id), sub: PD.teamName(PD.driverTeam(id)) }; }),
      aName: 'Model', bName: 'Market', max: Math.min(1, Math.max.apply(null, top.map(function (id) { return Math.max((ds[id] || {}).p_win || 0, mkt[id] || 0); })) * 1.15 + 0.02), labelWidth: 130 });
  } else {
    PD.ch.hbars('ov-who', ids.slice(0, 10).map(function (id) { return { label: PD.driverName(id), value: ds[id].p_win, colour: PD.teamColour(PD.driverTeam(id)), href: PD.driverHref(id) }; }), { fmt: function (v) { return PD.pct(v); }, name: 'P(win)' });
  }
  var host = document.getElementById('ov-fc');
  if (host) PD.table(host, [
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { code: true }); } },
    { key: 'p_win', label: 'Win', num: true, fmt: function (v) { return PD.pct(v); } },
    { key: 'p_podium', label: 'Podium', num: true, fmt: function (v) { return PD.pct(v, 0); } }
  ].concat(mkt ? [{ key: 'mkt', label: 'Market', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v) : '—'; } }] : []),
  ids.slice(0, 10).map(function (id) { return { id: id, name: PD.driverName(id), p_win: ds[id].p_win, p_podium: ds[id].p_podium, mkt: mkt ? mkt[id] : null }; }), { sort: { key: 'p_win', dir: 'desc' } });
  if (host) host.insertAdjacentHTML('beforeend', '<div class="pd-cardlink"><a href="' + PD.raceHref(next.year, next.round) + '">Full forecast and position odds →</a></div>');
}

function progression(season) {
  if (!PD.ok(season)) return PD.ch.none('ov-prog', 'Standings not built yet.');
  var prog = (season.progression || {}).drivers || {};
  var order = ((season.standings || {}).drivers || []).map(function (r) { return r.driver; }).filter(function (id) { return prog[id]; }).slice(0, 6);
  var done = (season.calendar || []).filter(function (c) { return c.status === 'done'; }).sort(function (a, b) { return a.round - b.round; });
  var teams = {};
  ((season.standings || {}).drivers || []).forEach(function (r) { teams[r.driver] = r.team; });
  var st = PD.ch.styleMap(order, teams);
  var xs = done.map(function (c) { return 'R' + c.round; });
  PD.ch.lines('ov-prog', order.map(function (id) { return { name: PD.driverName(id), short: PD.driverCode(id), data: prog[id], colour: st[id].colour, dash: st[id].dash }; }),
    { xs: xs, endLabels: true, legend: false, yName: 'Points', yScale: false, xLabel: function (v) { var c = done[xs.indexOf(v)]; return c ? v + ' · ' + c.name : v; }, yFmt: function (v) { return PD.pts(v); }, label: 'Points progression' });
}

function standings(season) {
  var draw = function (kind) {
    var host = document.getElementById('ov-std');
    if (!host) return;
    if (!PD.ok(season)) { host.innerHTML = PD.muted('Standings not built yet.'); return; }
    var isD = kind === 'drivers';
    var list = ((season.standings || {})[kind] || []).slice(0, 10);
    var prog = ((season.progression || {})[kind]) || {};
    var leadPts = list.length ? list[0].points : 0;
    PD.table(host, [
      { key: 'pos', label: '#', num: true, sort: false },
      { key: 'name', label: isD ? 'Driver' : 'Constructor', sticky: true, sort: false, fmt: function (v, r) { return isD ? PD.driverLink(r.id, { team: r.team }) : PD.teamLink(r.id); } },
      { key: 'trend', label: 'Trend', sort: false, fmt: function (v, r) { return window.QK.spark(prog[r.id] || [], { color: PD.tc(r.team), w: 70, h: 20, dot: false, area: false }); } },
      { key: 'points', label: 'Pts', num: true, sort: false, fmt: function (v) { return '<b>' + PD.pts(v) + '</b>'; } },
      { key: 'gap', label: 'Gap', num: true, sort: false, fmt: function (v) { return v ? '−' + PD.pts(v) : '<span class="qk-muted">—</span>'; } }
    ], list.map(function (r) { var id = isD ? r.driver : r.team; return { pos: r.pos, id: id, team: r.team, name: id, points: r.points, gap: leadPts - r.points }; }));
    host.insertAdjacentHTML('beforeend', '<div class="pd-cardlink"><a href="#/standings">Full standings, magic numbers and odds →</a></div>');
  };
  draw('drivers');
  PD.wireSeg(document, 'ov-std-k', draw);
}

function odds(season, markets) {
  var draw = function (kind) {
    if (!PD.ok(season) || !season.championship) { PD.set('ov-odds-s', 'The championship is decided.'); return PD.ch.none('ov-odds', 'No simulation for a finished season.'); }
    var rows = titleRows(season, markets, kind).slice(0, 8);
    var decided = rows[0] && rows[0].model > 0.995;
    PD.set('ov-odds-s', decided ? esc(kind === 'drivers' ? PD.driverName(rows[0].id) : PD.teamName(rows[0].id)) + ' wins ' + PD.pct(rows[0].model, 2) + ' of simulated seasons; orange tick = market.' : 'Share of simulated seasons won; orange tick = market.');
    PD.ch.hbars('ov-odds', rows.map(function (r) {
      var isD = kind === 'drivers';
      return { label: isD ? PD.driverName(r.id) : PD.teamName(r.id), value: r.model, mark: r.market, colour: PD.teamColour(isD ? (r.c.team || PD.driverTeam(r.id)) : r.id), href: isD ? PD.driverHref(r.id) : PD.teamHref(r.id),
        sub: 'Expected ' + PD.num(r.c.exp_points, 0) + ' pts (' + PD.num(r.c.p05, 0) + '–' + PD.num(r.c.p95, 0) + ')' };
    }), { fmt: function (v) { return PD.pct(v, v > 0.99 ? 2 : 1); }, name: 'Model', markName: 'Market', min: 0, max: 1, label: 'Championship probability' });
  };
  draw('drivers');
  PD.wireSeg(document, 'ov-odds-k', draw);
}

function cars(value) {
  if (!PD.ok(value) || !value.teams) return PD.ch.none('ov-cars', 'Car pace is estimated once a race has lap data.');
  var T = PD.rowsOf(value.team_cols, value.teams).filter(function (r) { return isNum(r.car); }).sort(function (a, b) { return b.car - a.car; });
  PD.ch.hbars('ov-cars', T.map(function (r) { return { label: PD.teamName(r.id), value: r.car, lo: r.car - (r.car_se || 0), hi: r.car + (r.car_se || 0), colour: PD.teamColour(r.id), href: PD.teamHref(r.id),
    sub: 'Season mean ' + PD.signed(r.car_mean, 2) + '% · last five rounds ' + PD.signed(r.trend, 2) }; }), { fmt: function (v) { return PD.signed(v, 2) + '%'; }, name: 'Car pace', errName: '±1 se', label: 'Car pace by team' });
}

function bestDrivers(value) {
  if (!PD.ok(value) || !value.drivers) return PD.ch.none('ov-drv', 'Driver value needs lap data (1994 on).');
  var minR = value.min_races || 5;
  var D = PD.rowsOf(value.driver_cols, value.drivers).filter(function (r) { return isNum(r.pace_tm) && (r.races || 0) >= minR; }).sort(function (a, b) { return b.pace_tm - a.pace_tm; }).slice(0, 10);
  PD.ch.hbars('ov-drv', D.map(function (r) { return { label: r.name, value: r.pace_tm, lo: r.pace_tm - (r.pace_tm_se || 0), hi: r.pace_tm + (r.pace_tm_se || 0), colour: PD.teamColour(r.team), href: PD.driverHref(r.id), sub: PD.teamName(r.team) + ' · ' + r.races + ' races' }; }),
    { fmt: function (v) { return PD.signed(v, 2) + '%'; }, name: 'Above team-mate', errName: '±1 se', label: 'Pace above the team-mate' });
}

function favourites(season) {
  if (!PD.ok(season)) return PD.ch.none('ov-fav', 'No calendar.');
  var done = (season.calendar || []).filter(function (c) { return c.status === 'done' && (c.p_win_top || []).length; }).sort(function (a, b) { return a.round - b.round; });
  if (!done.length) return PD.ch.none('ov-fav', 'No forecasts stored for this season.');
  var won = done.filter(function (c) { return c.winner === c.p_win_top[0][0]; }).length;
  var mean = PD.mean(done.map(function (c) { return c.p_win_top[0][1]; }));
  PD.ch.columns('ov-fav', { cats: done.map(function (c) { return 'R' + c.round; }), label: 'Favourite win probability by round',
    series: [{ name: 'Favourite’s win probability', data: done.map(function (c) { return c.p_win_top[0][1]; }), colours: done.map(function (c) { return c.winner === c.p_win_top[0][0] ? PD.teamColour(c.winner_team || PD.driverTeam(c.winner)) : '#5a6270'; }), fmt: function (v) { return PD.pct(v); } }],
    fmt: function (v) { return Math.round(v * 100) + '%'; }, yMin: 0,
    tipLabel: function (i) { var c = done[i]; return 'R' + c.round + ' ' + c.name + ': ' + PD.driverName(c.p_win_top[0][0]) + (c.winner === c.p_win_top[0][0] ? ' won' : ' (winner ' + PD.driverName(c.winner) + ')'); } });
  var n = document.getElementById('ov-fav');
  if (n) n.insertAdjacentHTML('afterend', '<p class="pd-cap">The favourite won <b>' + won + ' of ' + done.length + '</b> races; its average win probability was ' + PD.pct(mean, 0) + ', so about ' + PD.num(mean * done.length, 1) + ' wins were expected.</p>');
}

function lastRace(last, season) {
  if (!last || !last.winner) { PD.set('ov-last', PD.muted('No race run yet this season.')); return; }
  var c = PD.ok(season) ? (season.calendar || []).filter(function (x) { return x.round === last.round; })[0] || {} : {};
  var fav = (c.p_win_top || [])[0];
  var team = last.winner_team || PD.driverTeam(last.winner);
  PD.set('ov-last', '<div class="pd-last" style="--tc:' + esc(PD.tc(team)) + '"><div class="qk-kicker">' + esc(last.name) + ' · ' + esc(PD.fmtDate(last.date, { year: false })) + '</div>' +
    '<div class="pd-last-win">' + PD.mark(team, 'lg') + '<div><div class="pd-last-name">' + PD.driverLink(last.winner, { dot: false }) + '</div><div class="qk-sub">' + esc(PD.teamName(team)) + ' · winner</div></div></div>' +
    PD.kpis([PD.kpi('Pole', c.pole ? PD.driverLink(c.pole, { code: true }) : '—', '', { text: true }), PD.kpi('Fastest lap', c.fastest ? PD.driverLink(c.fastest, { code: true }) : '—', '', { text: true }),
      PD.kpi('Model favourite', fav ? PD.driverLink(fav[0], { code: true }) : '—', fav ? PD.pct(fav[1]) + (fav[0] === last.winner ? ' · won' : '') : '', { text: true })], 'pd-kpis-3') +
    '<div class="pd-cardlink"><a href="' + PD.raceHref(last.year, last.round) + '">Race centre: laps, strategy, awards →</a></div></div>');
}

function fantasy(F) {
  if (!PD.ok(F) || !F.drivers || !F.projection_ok) return PD.ch.none('ov-fan', F && F.reason ? F.reason : 'No fantasy projection right now.');
  var D = PD.rowsOf(F.driver_cols, F.drivers).filter(function (r) { return isNum(r.next); }).sort(function (a, b) { return b.next - a.next; }).slice(0, 8);
  PD.ch.hbars('ov-fan', D.map(function (r) { return { label: r.name, value: r.next, lo: r.p10, hi: r.p90, colour: PD.teamColour(r.team), href: PD.driverHref(r.id), sub: 'Floor ' + PD.num(r.p10, 0) + ', ceiling ' + PD.num(r.p90, 0) + ' · value ' + PD.signed(r.value, 1) }; }),
    { fmt: function (v) { return PD.num(v, 1); }, name: 'Projected points', errName: '10th–90th pct', label: 'Fantasy projections' });
}

PD.route('overview', render);
})(window.PD);
