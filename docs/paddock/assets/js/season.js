/* The Quant Paddock — the season page (#/season/<y>).
 *
 *   standings (drivers, constructors) with the title simulation: P(title), expected
 *   points and the p05-p95 band, magic numbers, clinched / eliminated chips;
 *   finishing-position heatmap; points progression; car pace by race (heat table
 *   and lines); driver race and quali effects; the car-driver split; Elo; the
 *   calendar with winners, poles and the forecast favourite.
 *   A finished season shows its final standings without the simulation. */
(function (PD) {
'use strict';

const esc = PD.esc;

function magicOf(c) {
  if (!c) return null;
  const m = c.magic;
  if (m && typeof m === 'object') return PD.isNum(m.magic_number) ? m.magic_number : null;
  return PD.isNum(m) ? m : null;
}
function flag(c, k) {
  if (!c) return false;
  if (c[k] !== undefined) return !!c[k];
  return !!(c.magic && typeof c.magic === 'object' && c.magic[k]);
}
function q(c, lo) {
  if (!c) return null;
  if (PD.isNum(c[lo ? 'p05' : 'p95'])) return c[lo ? 'p05' : 'p95'];
  const pq = c.points_q || {};
  return pq[lo ? 'q5' : 'q95'];
}

function rangeCell(lo, mid, hi, max) {
  if (!PD.isNum(lo) || !PD.isNum(hi) || !max) return '—';
  const x = v => Math.max(0, Math.min(100, v / max * 100)).toFixed(1);
  return '<span class="range-cell"><span class="range-bar"><span style="left:' + x(lo) + '%;width:' + (x(hi) - x(lo)).toFixed(1) + '%"></span>' +
    (PD.isNum(mid) ? '<i style="left:' + x(mid) + '%"></i>' : '') + '</span><span class="muted-inline">' + PD.num(lo, 0) + '–' + PD.num(hi, 0) + '</span></span>';
}

function chipsFor(c, pos, finished) {
  if (finished && pos === 1) return PD.chip('champion', 'ok');
  if (flag(c, 'clinched')) return PD.chip('clinched', 'ok');
  if (flag(c, 'eliminated')) return PD.chip('eliminated', 'bad');
  return '';
}

function standingsTable(season, kind) {
  const isD = kind === 'drivers';
  const list = (season.standings || {})[kind] || [];
  if (!list.length) return PD.muted('No standings for this season.');
  const ch = season.championship ? (season.championship[kind] || {}) : null;
  const finished = !season.championship;
  const maxE = ch ? Math.max.apply(null, Object.keys(ch).map(k => q(ch[k], false) || 0)) : 0;
  const cols = [{ label: 'Pos', align: 'right' }, { label: isD ? 'Driver' : 'Team' }].concat(isD ? [{ label: 'Team' }] : [])
    .concat([{ label: 'Pts', align: 'right' }, { label: 'Wins', align: 'right' }]).concat(isD ? [{ label: 'Podiums', align: 'right' }, { label: 'Poles', align: 'right' }] : [])
    .concat(ch ? [{ label: 'P(title)', title: 'Share of simulated seasons won' }, { label: 'Exp. pts', align: 'right', title: 'Expected final points' },
      { label: 'p05–p95', title: 'The middle 90% of simulated final points; the tick is the expectation' }, { label: 'Magic', align: 'right', title: 'Points needed over every rival’s maximum to clinch' }] : [])
    .concat([{ label: '', sortable: false }]);
  const rows = list.map(r => {
    const id = isD ? r.driver : r.team;
    const c = ch ? ch[id] : null;
    const cells = [{ v: r.pos, align: 'right' },
      { v: isD ? PD.driverName(id) : PD.teamName(id), html: isD ? PD.driverLink(id, { team: r.team }) : PD.teamLink(id) }];
    if (isD) cells.push({ v: PD.teamName(r.team), html: '<span class="muted-inline">' + esc(PD.teamName(r.team)) + '</span>' });
    cells.push({ v: r.points, html: '<b>' + PD.num(r.points, r.points % 1 ? 1 : 0) + '</b>', align: 'right' });
    cells.push({ v: r.wins, align: 'right' });
    if (isD) { cells.push({ v: r.podiums, align: 'right' }); cells.push({ v: r.poles, align: 'right' }); }
    if (ch) {
      cells.push({ v: c ? c.p_title : null, html: c ? PD.probCell(c.p_title, PD.teamColour(isD ? r.team : id)) : '—' });
      cells.push({ v: c ? c.exp_points : null, html: c ? PD.num(c.exp_points, 0) : '—', align: 'right' });
      cells.push({ v: c ? c.exp_points : null, html: c ? rangeCell(q(c, true), c.exp_points, q(c, false), maxE) : '—' });
      const m = magicOf(c);
      cells.push({ v: m, html: m === null ? '—' : flag(c, 'eliminated') ? '<span class="muted-inline">—</span>' : PD.num(m, 0), align: 'right' });
    }
    cells.push({ v: '', html: chipsFor(c, r.pos, finished) });
    return { cells: cells };
  });
  return PD.tableHTML(cols, rows, { compact: true });
}

function roundLabels(season, n) {
  const done = (season.calendar || []).filter(c => c.status === 'done').sort((a, b) => a.round - b.round);
  const out = [];
  for (let i = 0; i < n; i++) out.push(done[i] ? 'R' + done[i].round + ' ' + shortName(done[i].name) : 'R' + (i + 1));
  return out;
}
function shortName(n) { return String(n || '').replace(/ Grand Prix.*$/, '').replace(/^Grand Prix (of )?/, ''); }

function progressionChart(el, season, kind) {
  const prog = ((season.progression || {})[kind]) || {};
  const order = ((season.standings || {})[kind] || []).map(r => (kind === 'drivers' ? r.driver : r.team)).filter(id => prog[id]);
  const top = order.slice(0, kind === 'drivers' ? 10 : 11);
  if (!top.length) { el.innerHTML = PD.muted('No progression yet.'); return; }
  const n = Math.max.apply(null, top.map(id => prog[id].length));
  const labels = roundLabels(season, n);
  const teamOf = {};
  ((season.standings || {}).drivers || []).forEach(r => { teamOf[r.driver] = r.team; });
  const st = kind === 'drivers' ? PD.charts.styleMap(top, teamOf) : null;
  PD.charts.lines(el, top.map(id => ({
    name: kind === 'drivers' ? PD.driverCode(id) : PD.teamName(id), x: labels.slice(0, prog[id].length), y: prog[id],
    colour: kind === 'drivers' ? st[id].colour : PD.teamColour(id), dash: kind === 'drivers' ? st[id].dash : 'solid',
    hover: esc(kind === 'drivers' ? PD.driverName(id) : PD.teamName(id)) + ' · %{y} pts after %{x}<extra></extra>'
  })), { height: 400, yTitle: 'Points', xaxis: { tickangle: -40, tickfont: { size: 9 } } });
}

function carPaceSection(season, kind) {
  const cp = ((season.car_pace || {})[kind]) || {};
  const teams = Object.keys(cp).filter(t => (cp[t] || []).length);
  if (!teams.length) return { html: PD.muted('Car pace needs lap data (2018 on).'), teams: [] };
  const rounds = [];
  teams.forEach(t => cp[t].forEach(e => { if (rounds.indexOf(e.round) < 0) rounds.push(e.round); }));
  rounds.sort((a, b) => a - b);
  const mean = t => { const v = cp[t].map(e => e.effect).filter(PD.isNum); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 99; };
  teams.sort((a, b) => mean(a) - mean(b));
  const cal = {};
  (season.calendar || []).forEach(c => { cal[c.round] = c; });
  const html = PD.charts.heatTable({
    corner: 'Team · mean',
    cols: rounds.map(r => ({ label: 'R' + r, title: cal[r] ? cal[r].name : 'Round ' + r })),
    rows: teams.map(t => {
      const by = {};
      cp[t].forEach(e => { by[e.round] = e; });
      return { label: PD.teamLink(t) + ' <span class="muted-inline">' + PD.signed(mean(t), 2) + '</span>', values: rounds.map(r => (by[r] ? by[r].effect : null)),
        titles: rounds.map(r => (by[r] ? PD.teamName(t) + ' · ' + (cal[r] ? cal[r].name : 'R' + r) + ': ' + PD.signed(by[r].effect, 3) + '% ± ' + PD.num(by[r].se, 3) : '')) };
    }),
    fmt: v => PD.signed(v, 2)
  });
  return { html: html, teams: teams, rounds: rounds, cp: cp };
}

function effectsChart(el, season, kind) {
  const eff = ((season.driver_effects || {})[kind]) || {};
  const ids = Object.keys(eff).filter(id => PD.isNum(eff[id].effect)).sort((a, b) => eff[a].effect - eff[b].effect);
  if (!ids.length) { el.innerHTML = PD.muted('Driver effects need lap data (2018 on).'); return; }
  const teamOf = {};
  ((season.standings || {}).drivers || []).forEach(r => { teamOf[r.driver] = r.team; });
  const rev = ids.slice().reverse();
  PD.plot(el, [{
    type: 'bar', orientation: 'h', y: rev.map(id => PD.driverCode(id)), x: rev.map(id => eff[id].effect),
    error_x: { type: 'data', array: rev.map(id => 1.96 * (eff[id].se || 0)), color: '#6e7681', thickness: 1, width: 3 },
    marker: { color: rev.map(id => PD.teamColour(teamOf[id] || (PD.NAMES.drivers[id] || {}).team)) },
    text: rev.map(id => PD.driverName(id) + ' · ' + (eff[id].races || 0) + ' races'), textposition: 'none',
    hovertemplate: '%{text}<br>%{x:+.3f}% of a lap<extra></extra>'
  }], PD.layout({
    height: Math.max(300, ids.length * 20 + 60),
    xaxis: { title: '% of a lap against the car (negative = faster)', zeroline: true, zerolinecolor: '#8b949e' },
    yaxis: { type: 'category', tickfont: { size: 10 }, fixedrange: true },
    margin: { l: 50, r: 15, t: 10, b: 45 }
  }));
}

function splitChart(el, season) {
  const sp = season.car_driver_split || {};
  const teams = Object.keys(sp).sort((a, b) => (sp[b].points || 0) - (sp[a].points || 0));
  if (!teams.length) { el.innerHTML = PD.muted('No car-driver split for this season.'); return; }
  const rev = teams.slice().reverse();
  const traces = [{
    type: 'bar', orientation: 'h', name: 'Car', y: rev.map(PD.teamName), x: rev.map(t => sp[t].car || 0),
    marker: { color: rev.map(t => PD.teamColour(t)) }, hovertemplate: '%{y} · car %{x:.0f} pts<extra></extra>'
  }];
  const maxDrivers = Math.max.apply(null, teams.map(t => Object.keys(sp[t].drivers || {}).length));
  for (let k = 0; k < maxDrivers; k++) {
    traces.push({
      type: 'bar', orientation: 'h', name: k === 0 ? 'Drivers' : 'Driver ' + (k + 1), y: rev.map(PD.teamName),
      x: rev.map(t => { const ds = Object.keys(sp[t].drivers || {}); return ds[k] ? sp[t].drivers[ds[k]] : 0; }),
      text: rev.map(t => { const ds = Object.keys(sp[t].drivers || {}); return ds[k] ? PD.driverCode(ds[k]) : ''; }),
      textposition: 'inside', insidetextanchor: 'middle', textfont: { size: 9, color: '#e6edf3' },
      marker: { color: rev.map(t => PD.charts.hexA(PD.teamColour(t), k === 0 ? 0.45 : 0.25)), line: { color: rev.map(t => PD.teamColour(t)), width: 1 } },
      hovertemplate: '%{y} · %{text}: %{x:.0f} pts above the car<extra></extra>'
    });
  }
  PD.plot(el, traces, PD.layout({
    barmode: 'relative', height: Math.max(280, teams.length * 30 + 60),
    xaxis: { title: 'Points', zeroline: true }, yaxis: { tickfont: { size: 10 }, fixedrange: true, automargin: true },
    margin: { l: 100, r: 15, t: 10, b: 45 }
  }));
}

function eloTable(season) {
  const elo = season.elo || {};
  const ids = Object.keys(elo).sort((a, b) => (elo[b].elo || 0) - (elo[a].elo || 0));
  if (!ids.length) return PD.muted('No Elo ratings for this season.');
  const teamOf = {};
  ((season.standings || {}).drivers || []).forEach(r => { teamOf[r.driver] = r.team; });
  return PD.tableHTML([{ label: '#', align: 'right' }, { label: 'Driver' }, { label: 'Elo', align: 'right', title: 'Against the whole field' },
    { label: 'Teammate', align: 'right', title: 'Elo from head-to-heads with the teammate only' }, { label: 'Quali', align: 'right', title: 'Elo from qualifying' }],
    ids.map((id, i) => ({ cells: [{ v: i + 1, align: 'right' }, { v: PD.driverName(id), html: PD.driverLink(id, { team: teamOf[id] }) },
      { v: elo[id].elo, html: '<b>' + PD.num(elo[id].elo, 0) + '</b>', align: 'right' }, { v: elo[id].elo_teammate, html: PD.num(elo[id].elo_teammate, 0), align: 'right' },
      { v: elo[id].elo_quali, html: PD.num(elo[id].elo_quali, 0), align: 'right' }] })), { compact: true });
}

function statusChip(c) {
  if (c.status === 'done') return PD.chip('done', '');
  if (c.status === 'next') return PD.chip('next', 'info');
  return PD.chip('upcoming', '');
}

/* The calendar as a table; shared with the races list. */
function calendarTable(season, opts) {
  const o = opts || {};
  const cal = season.calendar || [];
  if (!cal.length) return PD.muted('No calendar for this season.');
  const rows = cal.map(c => {
    const fav = (c.p_win_top || [])[0];
    const cells = [
      { v: c.round, align: 'right' },
      { v: c.date, html: esc(PD.fmtDate(c.date, { year: false })) },
      { v: c.name, html: '<a class="race-link" href="' + PD.raceHref(season.year, c.round) + '"><b>' + esc(c.name) + '</b></a>' + (c.sprint ? ' ' + PD.chip('sprint', 'info') : '') },
      { v: c.circuit ? c.circuit.name : '', html: c.circuit ? PD.circuitLink(c.circuit.id, c.circuit.name) + '<span class="drv-code">' + esc(c.circuit.country || '') + '</span>' : '—' },
      { v: c.status, html: statusChip(c) },
      { v: c.winner ? PD.driverName(c.winner) : '', html: c.winner ? PD.driverLink(c.winner) : '—' },
      { v: c.pole ? PD.driverName(c.pole) : '', html: c.pole ? PD.driverLink(c.pole) : '—' }
    ];
    if (o.fastest) cells.push({ v: c.fastest ? PD.driverName(c.fastest) : '', html: c.fastest ? PD.driverLink(c.fastest) : '—' });
    cells.push({ v: fav ? fav[1] : null, html: fav ? PD.driverLink(fav[0], { code: true }) + ' <span class="muted-inline">' + PD.pct(fav[1], 0) + '</span>' + (c.winner && c.winner === fav[0] ? ' ✓' : '') : '<span class="muted-inline">—</span>' });
    return { cells: cells, _class: c.status === 'next' ? 'cal-next' : '', _href: PD.raceHref(season.year, c.round) };
  });
  const cols = [{ label: 'Rd', align: 'right' }, { label: 'Date' }, { label: 'Grand Prix' }, { label: 'Circuit' }, { label: 'Status' }, { label: 'Winner' }, { label: 'Pole' }]
    .concat(o.fastest ? [{ label: 'Fastest lap' }] : []).concat([{ label: 'Forecast favourite', title: 'The model’s most likely winner before the race, with its probability' }]);
  return PD.tableHTML(cols, rows, { compact: true });
}

function pageHead(year, title, sub, seasons, route) {
  const ys = (seasons || []).slice().sort((a, b) => a - b);
  const i = ys.indexOf(year);
  const prev = i > 0 ? ys[i - 1] : null, next = i >= 0 && i < ys.length - 1 ? ys[i + 1] : null;
  return '<div class="page-head"><div><h2>' + esc(title) + '</h2><div class="ph-sub">' + sub + '</div></div><div class="ph-nav">' +
    (prev ? '<a href="#/' + route + '/' + prev + '">← ' + prev + '</a>' : '<span class="disabled">←</span>') +
    (route === 'season' ? '<a href="#/races/' + year + '">Races</a>' : '<a href="#/season/' + year + '">Season</a>') +
    (next ? '<a href="#/' + route + '/' + next + '">' + next + ' →</a>' : '<span class="disabled">→</span>') + '</div></div>';
}

function render(el, params) {
  const idx = PD.index() || {};
  const year = PD.isNum(params.year) ? Number(params.year) : PD.currentSeason();
  el.innerHTML = PD.muted('Loading ' + esc(year) + '…');
  return PD.load(year + '/season.json').then(season => {
    if (!el.isConnected) return;
    const seasons = idx.seasons || [year];
    if (!PD.ok(season)) {
      el.innerHTML = pageHead(year, year + ' season', '', seasons, 'season') +
        '<div class="stale-banner">The ' + esc(year) + ' season is not available: ' + esc(PD.reason(season)) + '.</div>';
      return;
    }
    const finished = !season.championship;
    const ch = season.championship;
    PD.setMeta(esc(year) + ' season · ' + season.rounds_done + '/' + season.rounds_total + ' rounds' + (ch && ch.n_sims ? ' · ' + Number(ch.n_sims).toLocaleString('en-US') + ' simulations' : ''));
    const sub = season.rounds_done + ' of ' + season.rounds_total + ' rounds run' + (finished ? ' · final standings' : ' · title odds from ' + (ch.n_sims ? Number(ch.n_sims).toLocaleString('en-US') + ' ' : '') + 'simulated seasons') +
      (season.updated_at ? ' · updated ' + esc(PD.fmtStamp(season.updated_at)) : '');
    const sd = (season.standings || {}).drivers || [], sc = (season.standings || {}).constructors || [];
    const leaderD = sd[0], leaderC = sc[0];
    const fav = ch ? Object.keys(ch.drivers || {}).sort((a, b) => ch.drivers[b].p_title - ch.drivers[a].p_title)[0] : null;
    const tiles = '<div class="kpi-grid">' +
      PD.statTile(finished ? 'Champion' : 'Leader', leaderD ? PD.driverLink(leaderD.driver, { team: leaderD.team }) : '—', leaderD ? PD.num(leaderD.points, 0) + ' pts' + (sd[1] ? ' · ' + PD.num(leaderD.points - sd[1].points, 0) + ' clear' : '') : '') +
      PD.statTile(finished ? 'Constructors’ champion' : 'Constructors’ leader', leaderC ? PD.teamLink(leaderC.team) : '—', leaderC ? PD.num(leaderC.points, 0) + ' pts' : '') +
      (fav ? PD.statTile('Title favourite', PD.driverLink(fav), PD.pct(ch.drivers[fav].p_title) + ' to win the title') :
        PD.statTile('Wins', leaderD ? String(leaderD.wins) : '—', 'for the champion')) +
      PD.statTile('Rounds', season.rounds_done + ' / ' + season.rounds_total, (season.calendar || []).filter(c => c.sprint).length + ' sprint weekends') +
      '</div>';

    el.innerHTML = pageHead(year, year + ' season', sub, seasons, 'season') + tiles +
      PD.card('Drivers’ championship', finished ? 'Final standings.' : 'P(title), expected final points and the middle 90% of simulated outcomes; magic = points needed to clinch.', '<div id="season-std-d"></div>') +
      PD.card('Constructors’ championship', '', '<div id="season-std-c"></div>') +
      (finished ? '' : '<div class="card"><div class="card-header">Finishing-position distribution <span class="card-sub">Share of simulated seasons ending in each place.</span></div>' +
        '<div class="toggle-row" id="season-pd-toggle"><button class="tbtn active" data-k="drivers">Drivers</button><button class="tbtn" data-k="constructors">Constructors</button></div><div id="season-posdist"></div></div>') +
      '<div class="card"><div class="card-header">Points progression</div>' +
        '<div class="toggle-row" id="season-prog-toggle"><button class="tbtn active" data-k="drivers">Drivers (top 10)</button><button class="tbtn" data-k="constructors">Constructors</button></div><div id="season-prog"></div></div>' +
      '<div class="card"><div class="card-header">Car pace by race <span class="card-sub">Each car’s pace as a % of a lap against the field, from the lap-time model; negative is faster.</span></div>' +
        '<div class="toggle-row" id="season-cp-toggle"><button class="tbtn active" data-k="race">Race</button><button class="tbtn" data-k="quali">Qualifying</button></div>' +
        '<div id="season-cp-table"></div><div id="season-cp-chart"></div></div>' +
      '<div class="grid-2">' +
        '<div class="card"><div class="card-header">Driver effects <span class="card-sub">Pace against the car, % of a lap with a 95% interval.</span></div>' +
          '<div class="toggle-row" id="season-eff-toggle"><button class="tbtn active" data-k="race">Race</button><button class="tbtn" data-k="quali">Qualifying</button></div><div id="season-eff"></div></div>' +
        PD.card('Elo', 'Driver ratings after the latest round.', '<div id="season-elo"></div>') +
      '</div>' +
      '<div class="card"><div class="card-header">Car and driver <span class="card-sub">Each team’s points split into what the car would score with an average driver and what its drivers added.</span></div><div id="season-split"></div></div>' +
      PD.card('Calendar', 'The favourite is the model’s pre-race pick; ✓ when it won.', '<div id="season-cal"></div>');

    const set = (id, html) => { const n = document.getElementById(id); if (n) n.innerHTML = html; };
    set('season-std-d', standingsTable(season, 'drivers'));
    set('season-std-c', standingsTable(season, 'constructors'));
    PD.sortable(document.getElementById('season-std-d'));
    PD.sortable(document.getElementById('season-std-c'));
    set('season-elo', eloTable(season));
    PD.sortable(document.getElementById('season-elo'));
    set('season-cal', calendarTable(season));
    PD.sortable(document.getElementById('season-cal'));

    const toggle = (id, fn) => {
      const box = document.getElementById(id);
      if (!box) return;
      box.querySelectorAll('.tbtn').forEach(b => b.addEventListener('click', () => {
        box.querySelectorAll('.tbtn').forEach(x => x.classList.toggle('active', x === b));
        fn(b.dataset.k);
      }));
    };

    const posdist = kind => {
      const c = (ch || {})[kind] || {};
      const order = ((season.standings || {})[kind] || []).map(r => (kind === 'drivers' ? r.driver : r.team)).filter(id => c[id]);
      Object.keys(c).forEach(id => { if (order.indexOf(id) < 0) order.push(id); });
      PD.charts.posHeatmap('season-posdist', order.map(id => ({ label: kind === 'drivers' ? PD.driverName(id) : PD.teamName(id), dist: c[id].pos_dist || [] })));
    };
    if (!finished) { posdist('drivers'); toggle('season-pd-toggle', posdist); }

    const prog = kind => progressionChart(document.getElementById('season-prog'), season, kind);
    prog('drivers'); toggle('season-prog-toggle', prog);

    const cp = kind => {
      const s = carPaceSection(season, kind);
      set('season-cp-table', s.html);
      const chart = document.getElementById('season-cp-chart');
      if (!s.teams.length) { chart.innerHTML = ''; if (!Object.keys(season.car_pace || {}).some(k => Object.keys(season.car_pace[k] || {}).length)) { const t = document.getElementById('season-cp-toggle'); if (t) t.style.display = 'none'; } return; }
      PD.charts.lines(chart, s.teams.map(t => ({
        name: PD.teamName(t), x: s.cp[t].map(e => 'R' + e.round), y: s.cp[t].map(e => e.effect), colour: PD.teamColour(t), mode: 'lines+markers',
        hover: esc(PD.teamName(t)) + ' · %{x}: %{y:+.2f}%<extra></extra>'
      })), { height: 360, yTitle: '% of a lap (negative = faster)', yaxis: { autorange: 'reversed', zeroline: true, zerolinecolor: '#8b949e' }, xaxis: { type: 'category', categoryorder: 'array', categoryarray: s.rounds.map(r => 'R' + r) } });
    };
    cp('race'); toggle('season-cp-toggle', cp);

    const eff = kind => effectsChart(document.getElementById('season-eff'), season, kind);
    if (!Object.keys(season.driver_effects || {}).some(k => Object.keys(season.driver_effects[k] || {}).length)) { const t = document.getElementById('season-eff-toggle'); if (t) t.style.display = 'none'; }
    eff('race'); toggle('season-eff-toggle', eff);
    splitChart(document.getElementById('season-split'), season);
  });
}

PD.route('season', render);
PD.season = { calendarTable: calendarTable, pageHead: pageHead, standingsTable: standingsTable, shortName: shortName };
})(window.PD);
