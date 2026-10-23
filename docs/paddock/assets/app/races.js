/* The Quant Paddock — Races: the calendar (#/races[/<y>]), circuits (#/circuits) and a circuit (#/circuit/<id>).
 * Reads <y>/season.json, circuits.json, and for the track map the latest telemetry file at the circuit. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;

function racesNav(active, y) {
  return PD.subnav([['#/races' + (y && y !== PD.currentSeason() ? '/' + y : ''), 'Calendar', 'races'], ['#/circuits', 'Circuits', 'circuits']], active, 'Races views');
}

// ── calendar ──────────────────────────────────────────────────────────────

function renderRaces(el, params) {
  var y = isNum(params.year) ? params.year : PD.currentSeason();
  el.innerHTML = PD.pageHead('Races · ' + y, 'Every race, ' + y, '', PD.yearPager('races', y)) + racesNav('races', y) + '<div id="rc-body">' + PD.empty('Loading', '') + '</div>';
  return PD.load(y + '/season.json').then(function (season) {
    if (!PD.alive(el)) return;
    if (!PD.ok(season)) { PD.set('rc-body', PD.notBuilt('The ' + y + ' calendar', season)); return; }
    var cal = (season.calendar || []).slice().sort(function (a, b) { return a.round - b.round; });
    var done = cal.filter(function (c) { return c.status === 'done'; });
    var nxt = cal.filter(function (c) { return c.status === 'next'; })[0];
    var winners = {};
    done.forEach(function (c) { if (c.winner) winners[c.winner] = (winners[c.winner] || 0) + 1; });
    var favRounds = done.filter(function (c) { return (c.p_win_top || []).length; });
    var favWon = favRounds.filter(function (c) { return c.winner === c.p_win_top[0][0]; }).length;
    var poleWon = done.filter(function (c) { return c.pole && c.pole === c.winner; }).length;
    var head = el.querySelector('.pd-head .qk-sh-sub');
    if (head) head.innerHTML = season.rounds_done + ' of ' + season.rounds_total + ' rounds run' + (nxt ? ' · next: <a href="' + PD.raceHref(y, nxt.round) + '">' + esc(nxt.name) + '</a>, ' + esc(PD.fmtDate(nxt.date, { year: false })) : '');
    var h = PD.kpis([
      PD.kpi('Rounds', season.rounds_done + ' / ' + season.rounds_total, cal.filter(function (c) { return c.sprint; }).length + ' sprint weekends'),
      PD.kpi('Different winners', String(Object.keys(winners).length), done.length ? 'in ' + done.length + ' races' : ''),
      PD.kpi('Won from pole', done.length ? PD.pct(poleWon / done.length, 0) : '—', poleWon + ' of ' + done.length),
      PD.kpi('Our favourite won', favRounds.length ? favWon + '/' + favRounds.length : '—', favRounds.length ? 'our pre-race pick to win' : 'no stored forecasts', { signal: true })
    ]);
    h += '<div class="qk-auto pd-cal" style="--min:230px">' + cal.map(function (c) { return raceCard(y, c); }).join('') + '</div>';
    h += PD.grid(
      PD.card('Wins', 'Grand Prix wins this season by driver.', PD.chartBox('rc-wins', Math.max(160, Object.keys(winners).length * 28 + 30)), { span: 6 }) +
      PD.card('Every round', 'Winner, pole, fastest lap and our pre-race favourite with its win chance; ✓ when it won.', '<div id="rc-table"></div>', { span: 6, flush: true }), 'pd-mt');
    PD.set('rc-body', h);
    var wins = Object.keys(winners).sort(function (a, b) { return winners[b] - winners[a]; });
    var teamOf = {};
    done.forEach(function (c) { if (c.winner && c.winner_team) teamOf[c.winner] = c.winner_team; });
    PD.ch.hbars('rc-wins', wins.map(function (id) { return { label: PD.driverName(id), value: winners[id], colour: PD.teamColour(teamOf[id] || PD.driverTeam(id)), href: PD.driverHref(id) }; }),
      { fmt: function (v) { return String(v); }, name: 'Wins', emptyText: 'No race run yet.', label: 'Wins by driver' });
    PD.table('rc-table', [
      { key: 'round', label: 'Rd', num: true },
      { key: 'name', label: 'Grand Prix', sticky: true, fmt: function (v, r) { return '<a class="pd-link" href="' + PD.raceHref(y, r.round) + '">' + esc(PD.shortRace(v)) + '</a>' + (r.sprint ? ' <span class="qk-badge">S</span>' : ''); } },
      { key: 'winner', label: 'Winner', fmt: function (v, r) { return v ? PD.driverLink(v, { code: true, team: r.winner_team }) : '<span class="qk-muted">' + (r.status === 'next' ? 'next' : '—') + '</span>'; } },
      { key: 'pole', label: 'Pole', fmt: function (v) { return v ? PD.driverLink(v, { code: true }) : '—'; } },
      { key: 'fastest', label: 'FL', tip: 'Fastest lap', fmt: function (v) { return v ? PD.driverLink(v, { code: true }) : '—'; } },
      { key: 'favp', label: 'Our favourite', num: true, fmt: function (v, r) { var f = (r.p_win_top || [])[0]; return f ? PD.driverLink(f[0], { code: true }) + ' ' + PD.pct(f[1], 0) + (r.winner === f[0] ? ' ✓' : '') : '—'; } }
    ], cal.map(function (c) { return Object.assign({}, c, { favp: (c.p_win_top || [])[0] ? c.p_win_top[0][1] : null }); }), { sort: { key: 'round', dir: 'asc' }, maxHeight: 560 });
  });
}

function raceCard(y, c) {
  var team = c.winner_team || (c.winner ? PD.driverTeam(c.winner) : null);
  var fav = (c.p_win_top || [])[0];
  var status = c.status === 'done' ? '<span class="qk-badge final">Result</span>' : c.status === 'next' ? '<span class="qk-badge accent">Next</span>' : '<span class="qk-badge">' + esc(PD.fmtDate(c.date, { year: false, weekday: false })) + '</span>';
  var body;
  if (c.status === 'done' && c.winner) body = '<div class="pd-rc-win">' + PD.mark(team) + '<span><b>' + esc(PD.driverName(c.winner)) + '</b><span class="qk-sub">' + esc(PD.teamName(team)) + '</span></span></div>';
  else if (fav) body = '<div class="pd-rc-win"><span class="pd-rc-p">' + PD.pct(fav[1], 0) + '</span><span><b>' + esc(PD.driverName(fav[0])) + '</b><span class="qk-sub">our favourite</span></span></div>';
  else body = '<div class="pd-rc-win qk-muted">' + esc(c.status === 'done' ? 'Result pending' : 'Forecast after the previous race') + '</div>';
  return '<a class="qk-card is-link pd-rc' + (c.status === 'next' ? ' is-next' : '') + '" href="' + PD.raceHref(y, c.round) + '" style="--tc:' + esc(team ? PD.tc(team) : 'var(--line-2)') + '">' +
    '<div class="pd-rc-top"><span class="pd-rc-n">R' + c.round + '</span>' + status + '</div>' +
    '<div class="pd-rc-name">' + esc(PD.shortRace(c.name)) + (c.sprint ? ' <span class="qk-badge">Sprint</span>' : '') + '</div>' +
    '<div class="pd-rc-sub">' + esc((c.circuit || {}).locality || (c.circuit || {}).name || '') + ' · ' + esc(PD.fmtDate(c.date, { year: false })) + '</div>' + body + '</a>';
}

// ── circuits ──────────────────────────────────────────────────────────────

function renderCircuits(el, params, state) {
  var y = state.year || PD.currentSeason();
  el.innerHTML = PD.pageHead('Circuits', 'Every circuit since 1950', 'Profiles from the circuit model (pit loss, safety-car hazards, overtaking) shrunk to the global profile, with winners and records.') + racesNav('circuits') +
    PD.grid(PD.card('Circuit character', 'Overtaking difficulty against the chance of a safety car, ' + y + ' calendar; size = pit-stop time loss.', PD.chartBox('ci-char', 380), { span: 12 })) +
    PD.card('All circuits', '', '<div class="pd-toolbar">' + PD.seg('ci-scope', [['cal', y + ' calendar'], ['all', 'All circuits']], 'cal', 'Scope') + '<input id="ci-q" class="qk-input" type="search" placeholder="Filter circuits…" aria-label="Filter circuits"></div><div id="ci-table"></div>', { flush: true, cls: 'pd-mt' });
  return Promise.all([PD.load('circuits.json'), PD.load(y + '/season.json')]).then(function (res) {
    if (!PD.alive(el)) return;
    var all = res[0], season = res[1];
    if (!all || all.ok === false) { PD.set('ci-table', PD.notBuilt('The circuit file', all)); return; }
    var cal = {};
    ((season || {}).calendar || []).forEach(function (c) { if (c.circuit && c.circuit.id) cal[c.circuit.id] = c; });
    var ids = Object.keys(all).filter(function (k) { return all[k] && typeof all[k] === 'object' && (all[k].name || all[k].profile); });
    var scope = Object.keys(cal).length ? 'cal' : 'all';
    var calIds = ids.filter(function (k) { return cal[k] && all[k].profile; });
    PD.ch.scatter('ci-char', calIds.map(function (k) {
      var p = all[k].profile;
      return { x: 100 * (p.overtake_difficulty || 0), y: p.p_sc_race, name: all[k].name, short: (all[k].locality || all[k].name || k).split(/[ -]/)[0], href: '#/circuit/' + k, size: 8 + Math.max(0, (p.pit_loss_s || 20) - 14), colour: PD.col('down'), label: true,
        sub: 'Round ' + cal[k].round + ' · pit loss ' + PD.num(p.pit_loss_s, 1) + ' s' };
    }), { xName: 'Overtaking difficulty (0–100)', yName: 'P(safety car)', yFmt: function (v) { return Math.round(v * 100) + '%'; }, xFmt: function (v) { return PD.num(v, 0); }, label: 'Circuit character' });
    var draw = function () {
      var q = (document.getElementById('ci-q').value || '').trim().toLowerCase();
      var list = ids.filter(function (k) { return (scope === 'all' || cal[k]) && (!q || ((all[k].name || '') + ' ' + (all[k].country || '') + ' ' + (all[k].locality || '') + ' ' + k).toLowerCase().indexOf(q) >= 0); });
      PD.table('ci-table', [
        { key: 'rd', label: scope === 'cal' ? 'Rd' : 'Races', num: true },
        { key: 'name', label: 'Circuit', sticky: true, fmt: function (v, r) { return PD.circuitLink(r.id, v); } },
        { key: 'country', label: 'Country' },
        { key: 'span', label: 'Span', sort: false },
        { key: 'last', label: 'Last winner', fmt: function (v, r) { return v ? PD.driverLink(v, { code: true }) + ' <span class="qk-muted">' + r.lastY + '</span>' : '—'; } },
        { key: 'laps', label: 'Laps', num: true },
        { key: 'pit', label: 'Pit loss', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 1) + 's' : '—'; } },
        { key: 'sc', label: 'P(SC)', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v, 0) : '—'; } },
        { key: 'ot', label: 'Overtaking', num: true, tip: 'Difficulty 0–100', fmt: function (v) { return isNum(v) ? PD.num(v, 0) : '—'; } },
        { key: 'stops', label: 'Stops', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 1) : '—'; } },
        { key: 'wet', label: 'Wet', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v, 0) : '—'; } }
      ], list.map(function (k) {
        var c = all[k], p = c.profile || {}, hist = (c.history || []).slice().sort(function (a, b) { return b.year - a.year; });
        var yrs = hist.map(function (x) { return x.year; });
        return { id: k, rd: scope === 'cal' ? cal[k].round : hist.length, name: c.name || k, country: c.country || '', span: yrs.length ? Math.min.apply(null, yrs) + '–' + Math.max.apply(null, yrs) : '—',
          last: hist[0] ? hist[0].winner : null, lastY: hist[0] ? hist[0].year : '', laps: p.laps, pit: p.pit_loss_s, sc: p.p_sc_race, ot: isNum(p.overtake_difficulty) ? 100 * p.overtake_difficulty : null, stops: p.typical_stops, wet: p.p_wet };
      }), { sort: { key: 'rd', dir: scope === 'cal' ? 'asc' : 'desc' }, maxHeight: 640 });
    };
    if (scope === 'all') { var b = document.querySelector('#ci-scope button[data-value="all"]'); if (b) b.click(); }
    PD.wireSeg(el, 'ci-scope', function (v) { scope = v; draw(); });
    document.getElementById('ci-q').addEventListener('input', draw);
    draw();
  });
}

// ── circuit page ──────────────────────────────────────────────────────────

function findTelemetry(id, years) {
  var i = 0;
  function next() {
    if (i >= years.length) return Promise.resolve(null);
    var y = years[i++];
    return PD.load(y + '/season.json').then(function (s) {
      var rounds = ((s || {}).calendar || []).filter(function (c) { return c.circuit && c.circuit.id === id && c.status === 'done'; }).map(function (c) { return c.round; }).sort(function (a, b) { return b - a; });
      if (!rounds.length) return next();
      return PD.load(y + '/races/' + rounds[0] + '.json').then(function (r) {
        var ses = (r || {}).sessions || {}, tf = (r || {}).telemetry || {};
        var order = ['quali', 'race', 'sprint_quali', 'sprint'].filter(function (k) { return ses[k] && tf[k]; });
        function tryK(j) {
          if (j >= order.length) return next();
          return PD.load(y + '/telemetry/' + ses[order[j]] + '.json').then(function (t) { return t && t.fastest && Object.keys(t.fastest).length ? { year: y, round: rounds[0], kind: order[j], key: ses[order[j]], tel: t, name: r.name } : tryK(j + 1); });
        }
        return tryK(0);
      });
    });
  }
  return next();
}
function mapTrace(tel) {
  var F = tel.fastest || {};
  var refDn = String(((tel.ref || {}).driver) || '');
  var order = [refDn].concat(Object.keys(F).sort(function (a, b) { return (F[a].ms || 1e9) - (F[b].ms || 1e9); }));
  for (var i = 0; i < order.length; i++) { var f = F[order[i]]; if (f && (f.x || []).length > 10) return { dn: order[i], f: f }; }
  return null;
}
PD.mapTrace = mapTrace;

function renderCircuit(el, params) {
  var id = params.id;
  el.innerHTML = PD.empty('Loading ' + PD.circuitName(id), '');
  return PD.load('circuits.json').then(function (all) {
    if (!PD.alive(el)) return;
    var c = (all || {})[id];
    if (!c) { el.innerHTML = PD.pageHead('Circuit', PD.circuitName(id), '') + PD.empty('No circuit with id ' + id, 'See all circuits.') + '<p><a class="qk-btn" href="#/circuits">All circuits</a></p>'; return; }
    var p = c.profile || null;
    var hist = (c.history || []).slice().sort(function (a, b) { return b.year - a.year; });
    var yrs = hist.map(function (x) { return x.year; });
    var s = (p || {}).samples || {};
    var h = PD.pageHead('Circuit · ' + esc([c.locality, c.country].filter(Boolean).join(', ')), c.name || PD.circuitName(id),
      [hist.length ? '<b>' + hist.length + '</b> world championship races, ' + Math.min.apply(null, yrs) + '–' + Math.max.apply(null, yrs) : '', p && isNum(p.length_km) ? '<b>' + PD.num(p.length_km, 3) + '</b> km lap' : ''].filter(Boolean).join(' · '),
      '<a class="qk-btn" href="#/circuits">All circuits</a>');
    h += racesNav('circuits');
    if (p) {
      var scRace = isNum(p.sc_rate_per_lap) && isNum(p.laps) ? p.sc_rate_per_lap * p.laps : null;
      h += PD.kpis([
        PD.kpi('Laps', isNum(p.laps) ? String(p.laps) : '—', isNum(p.distance_km) ? PD.num(p.distance_km, 1) + ' km' + (p.sprint_laps ? ' · sprint ' + p.sprint_laps + ' laps' : '') : ''),
        PD.kpi('Pit loss', isNum(p.pit_loss_s) ? PD.num(p.pit_loss_s, 1) + 's' : '—', 'against staying out' + (isNum(p.pit_lane_s) ? ' · lane ' + PD.num(p.pit_lane_s, 1) + 's' : '')),
        PD.kpi('Safety car', isNum(p.p_sc_race) ? PD.pct(p.p_sc_race, 0) : '—', scRace !== null ? PD.num(scRace, 2) + ' per race' : ''),
        PD.kpi('Virtual SC', isNum(p.p_vsc_race) ? PD.pct(p.p_vsc_race, 0) : '—', ''),
        PD.kpi('Typical stops', isNum(p.typical_stops) ? PD.num(p.typical_stops, 1) : '—', 'wet chance ' + (isNum(p.p_wet) ? PD.pct(p.p_wet, 0) : '—')),
        PD.kpi('DNFs per race', PD.num((p.dnf_mech_per_race || 0) + (p.dnf_incident_per_race || 0), 2), PD.num(p.dnf_mech_per_race, 2) + ' mechanical, ' + PD.num(p.dnf_incident_per_race, 2) + ' incident')
      ]);
    }
    h += PD.grid(
      PD.card('Track map', '<span id="ci-map-s">Fastest lap from the latest session with telemetry, coloured by speed.</span>', PD.chartBox('ci-map', 440), { span: 7 }) +
      PD.card('Most wins here', 'Drivers with the most Grand Prix wins at this circuit.', PD.chartBox('ci-wins', 300) + '<div id="ci-rec"></div>', { span: 5 }) +
      PD.card('Opening lap', 'Mean places gained on lap 1 by grid slot (bars, ±1 sd) and the lap-1 incident rate (line).', PD.chartBox('ci-lap1', 280), { span: 7 }) +
      PD.card('Model profile', 'What the race simulator uses here, against the all-circuit profile.', '<div id="ci-prof"></div>', { span: 5, flush: true }) +
      PD.card('History', 'Winners and pole sitters, newest first.', '<div id="ci-hist"></div>', { span: 12, flush: true }), 'pd-mt');
    el.innerHTML = h;

    if (p) {
      var g = p.global || null;
      var rows = [['Pit loss (s)', p.pit_loss_s, 'pit_loss_s', 2], ['SC hazard per lap', p.sc_rate_per_lap, 'sc_rate_per_lap', 5], ['VSC hazard per lap', p.vsc_rate_per_lap, 'vsc_rate_per_lap', 5],
        ['P(SC in the race)', p.p_sc_race, null, 3], ['P(VSC in the race)', p.p_vsc_race, null, 3], ['Pass probability', p.pass_prob, 'pass_prob', 4], ['Passes per car-lap', p.passes_per_car_lap, null, 4],
        ['Overtake threshold (s/lap)', p.overtake_threshold_s, null, 3], ['Typical stops', p.typical_stops, 'typical_stops', 2], ['Mechanical DNFs per race', p.dnf_mech_per_race, 'dnf_mech_per_race', 3],
        ['Incident DNFs per race', p.dnf_incident_per_race, 'dnf_incident_per_race', 3], ['Wet chance', p.p_wet, 'p_wet', 3]].filter(function (r) { return isNum(r[1]); });
      PD.table('ci-prof', [{ key: 'k', label: 'Parameter', sort: false }, { key: 'v', label: 'Here', num: true, fmt: function (v, r) { return PD.num(v, r.d); } }]
        .concat(g ? [{ key: 'g', label: 'Global', num: true, fmt: function (v, r) { return isNum(v) ? PD.num(v, r.d) : '—'; } }, { key: 'ratio', label: 'Ratio', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 2) + '×' : '—'; } }] : []),
        rows.map(function (r) { var gv = g && r[2] ? g[r[2]] : null; return { k: r[0], v: r[1], d: r[3], g: gv, ratio: isNum(gv) && gv ? r[1] / gv : null }; }));
      document.getElementById('ci-prof').insertAdjacentHTML('beforeend', '<p class="pd-cap">Each figure is shrunk towards the all-circuit profile in proportion to the history behind it: ' +
        [['races', s.races], ['pit samples', s.pit], ['SC laps', s.sc_laps], ['pass opportunities', s.pass_opps], ['stops', s.stops], ['starts', s.starts]].filter(function (x) { return isNum(x[1]); }).map(function (x) { return PD.int(x[1]) + ' ' + x[0]; }).join(', ') + '. <a href="#/methodology/circuits">Method</a>.</p>');
      var mean = p.lap1_mean_by_grid || [], sd = p.lap1_sd_by_grid || [], inc = p.lap1_incident_by_grid || [];
      if (mean.length) PD.ch.columns('ci-lap1', { cats: mean.map(function (v, i) { return 'P' + (i + 1); }), xName: 'Grid slot', yName: 'Places gained', y2Name: 'Incident', y2Fmt: function (v) { return Math.round(v * 100) + '%'; },
        series: [{ name: 'Mean places gained', data: mean, colours: mean.map(function (v) { return v >= 0 ? PD.col('leaf') : PD.col('down'); }), fmt: function (v) { return PD.signed(v, 2); } },
          { name: '±1 sd', type: 'scatter', data: sd.map(function (v) { return v * (p.lap1_sd_scale || 1); }), colour: PD.col('grey'), symbol: 'diamond', size: 7, fmt: function (v) { return PD.num(v, 2) + ' places'; } },
          { name: 'Incident rate', type: 'line', axis: 1, data: inc, colour: PD.col('sun'), fmt: function (v) { return PD.pct(v); } }], label: 'Opening lap by grid slot' });
      else PD.ch.none('ci-lap1', 'No opening-lap profile.');
    } else { PD.set('ci-prof', PD.muted('No profile.')); PD.ch.none('ci-lap1', 'No profile.'); }

    PD.table('ci-hist', [
      { key: 'year', label: 'Year', num: true, fmt: String },
      { key: 'winner', label: 'Winner', sticky: true, fmt: function (v) { return PD.driverLink(v, { dot: false }); } },
      { key: 'team', label: 'Team', fmt: function (v) { return v ? PD.teamLink(v) : '—'; } },
      { key: 'pole', label: 'Pole', fmt: function (v, r) { return v ? PD.driverLink(v, { dot: false }) + (v === r.winner ? ' <span class="qk-badge">won from pole</span>' : '') : '—'; } }
    ], hist, { sort: { key: 'year', dir: 'desc' }, maxHeight: 520 });
    var wins = {};
    hist.forEach(function (x) { if (x.winner) wins[x.winner] = (wins[x.winner] || 0) + 1; });
    var top = Object.keys(wins).sort(function (a, b) { return wins[b] - wins[a]; }).slice(0, 8);
    PD.ch.hbars('ci-wins', top.map(function (k) { return { label: PD.driverName(k), value: wins[k], colour: PD.col('down'), href: PD.driverHref(k) }; }), { fmt: function (v) { return String(v); }, name: 'Wins', emptyText: 'No races recorded.' });
    var rec = c.records || {};
    var lr = rec.lap_record;
    PD.set('ci-rec', '<dl class="pd-dl">' + (lr && isNum(lr.ms) ? '<dt>Fastest race lap</dt><dd><b class="pd-num">' + PD.fmtMs(lr.ms) + '</b> ' + PD.driverLink(lr.driver) + ' <span class="qk-muted">' + esc(lr.year) + '</span></dd>' : '') +
      ((rec.most_poles || []).length ? '<dt>Most poles</dt><dd>' + rec.most_poles.slice(0, 3).map(function (x) { return PD.driverLink(x.driver, { dot: false }) + ' <b>' + x.poles + '</b>'; }).join(' · ') + '</dd>' : '') +
      ((rec.most_team_wins || []).length ? '<dt>Most team wins</dt><dd>' + rec.most_team_wins.slice(0, 3).map(function (x) { return PD.teamLink(x.team) + ' <b>' + x.wins + '</b>'; }).join(' · ') + '</dd>' : '') +
      (isNum(rec.won_from_pole) ? '<dt>Won from pole</dt><dd>' + PD.pct(rec.won_from_pole, 0) + ' of races with a known pole</dd>' : '') + '</dl>');

    var cur = PD.currentSeason(), years = [];
    for (var yy = cur; yy >= 2023; yy--) years.push(yy);
    findTelemetry(id, years).then(function (t) {
      if (!PD.alive(el)) return;
      if (!t) { PD.ch.none('ci-map', 'No telemetry session at this circuit yet (OpenF1 car and position data start in 2023).'); return; }
      var pick = mapTrace(t.tel);
      if (!pick) { PD.ch.none('ci-map', 'The telemetry file has no position data.'); return; }
      PD.ch.trackMap('ci-map', { x: pick.f.x, y: pick.f.y, v: pick.f.speed, vName: 'km/h', vUnit: 'km/h', gear: pick.f.gear, corners: (t.tel.ref || {}).corners, step: pick.f.d || 10 });
      PD.set('ci-map-s', esc(t.year + ' ' + (t.name || '') + ' ' + ({ quali: 'qualifying', race: 'race', sprint: 'sprint', sprint_quali: 'sprint qualifying' }[t.kind] || t.kind)) + ': fastest lap of car #' + esc(pick.dn) +
        (pick.f.ms ? ' (' + PD.fmtMs(pick.f.ms) + ')' : '') + ', coloured by speed. <a href="' + PD.raceHref(t.year, t.round, 'telemetry') + '">Telemetry lab →</a>');
    });
  });
}

PD.route('races', renderRaces);
PD.route('circuits', renderCircuits);
PD.route('circuit', renderCircuit);
})(window.PD);
