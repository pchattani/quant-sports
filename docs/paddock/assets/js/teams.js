/* The Quant Paddock — teams: the index (#/teams) and the team page (#/team/<id>).
 *
 * Data: data/<y>/teams.json (catalogue, percentiles, pit crew, per-round log),
 * data/<y>/season.json (car pace by round with standard errors, car/driver split,
 * constructors' standings and championship simulation), data/<y>/drivers.json
 * (the team's drivers), data/markets.json (constructors' title prices), and the
 * race files for the pit-stop distribution when teams.json carries only a summary, and
 * data/<y>/needs.json (strengths and needs: graded areas and the best driver swaps; current season). */
(function (PD) {
'use strict';

const { esc, num, pct, signed, fmtMs, isNum, card, muted, tableHTML, sortable, pctPill, statTile, plot, layout, C } = PD;
const PG = () => PD.pg;

/* Car pace series for one team: [{round, effect, se}] sorted. */
function series(season, kind, team) { return ((((season || {}).car_pace || {})[kind] || {})[team] || []).slice().sort((a, b) => a.round - b.round); }

/* Line with a ±1 se band. */
function bandTraces(rows, colour, name, dash, showBand) {
  const x = rows.map(r => r.round), y = rows.map(r => r.effect);
  const out = [];
  if (showBand !== false && rows.some(r => isNum(r.se))) {
    out.push({ type: 'scatter', mode: 'lines', x: x, y: rows.map(r => r.effect + (r.se || 0)), line: { width: 0 }, hoverinfo: 'skip', showlegend: false });
    out.push({ type: 'scatter', mode: 'lines', x: x, y: rows.map(r => r.effect - (r.se || 0)), line: { width: 0 }, fill: 'tonexty', fillcolor: PG().alpha(colour, 0.18), hoverinfo: 'skip', showlegend: false });
  }
  out.push({ type: 'scatter', mode: 'lines+markers', name: name, x: x, y: y, customdata: rows.map(r => r.se), line: { color: colour, width: 2, dash: dash || 'solid' }, marker: { size: 5 },
    hovertemplate: name + ' R%{x}: %{y:+.3f}% ± %{customdata:.3f}<extra></extra>' });
  return out;
}
PD.pg_bandTraces = bandTraces;

function paceLayout(extra) {
  return layout(Object.assign({ showlegend: true, legend: { orientation: 'h', y: 1.14, font: { color: C.text2 } }, margin: { l: 55, r: 10, t: 30, b: 40 },
    xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: '% of lap v field (up = faster)', autorange: 'reversed', zeroline: true, zerolinecolor: '#6e7681' } }, extra || {}));
}

// ── teams index ────────────────────────────────────────────────────────────

function renderTeams(el, params, state) {
  const y = PG().yearOf(params, state);
  el.innerHTML = '<div id="tm-cards">' + muted('Loading…') + '</div><div class="card"><div class="card-header">Car pace ' + y + ' <span class="card-sub">Every team\'s race-pace car effect by round from the state-space decomposition, as % of a lap against the field; up is faster.</span>' +
    PG().toggle('tm-pace-kind', [['race', 'Race'], ['quali', 'Qualifying']], 'race') + '</div><div id="tm-pace" style="height:380px"></div></div><div id="tm-table"></div>';
  return PG().season(y).then(res => {
    if (!PG().alive(el)) return;
    const drivers = res[0], teams = res[1], season = res[2];
    const T = (PD.ok(teams) && teams.teams) || {};
    const standings = ((((season || {}).standings) || {}).constructors) || [];
    const champ = ((((season || {}).championship) || {}).constructors) || {};
    const pos = {}; standings.forEach(s => { pos[s.team] = s; });
    const ids = Array.from(new Set(Object.keys(T).concat(standings.map(s => s.team)).concat(Object.keys((season || {}).teams || {}))))
      .sort((a, b) => ((pos[a] || {}).pos || 99) - ((pos[b] || {}).pos || 99));
    if (!ids.length) { document.getElementById('tm-cards').innerHTML = card('Teams ' + y, '', PG().notBuilt('The ' + y + ' team catalogue', teams)); return; }
    const driversOf = id => {
      const fromSeason = (((season || {}).teams || {})[id] || {}).drivers;
      if (fromSeason && fromSeason.length) return fromSeason;
      const D = ((drivers || {}).drivers) || {};
      return Object.keys(D).filter(k => D[k].team === id);
    };
    document.getElementById('tm-cards').innerHTML = '<div class="pg-grid-cards">' + ids.map(id => {
      const t = T[id] || {}, s = pos[id] || {}, c = champ[id];
      const rp = series(season, 'race', id), last = rp.length ? rp[rp.length - 1] : null;
      return '<a class="pg-card" href="#/team/' + esc(id) + '" style="--team:' + esc(PD.teamColour(id)) + '"><div class="pg-card-name">' + (s.pos ? s.pos + '. ' : '') + esc(t.name || PD.teamName(id)) + '</div>' +
        '<div class="pg-card-sub">' + driversOf(id).map(d => esc(PD.driverName(d))).join(' · ') + '</div>' +
        '<div class="pg-card-stats"><span>Points<strong>' + (PG().has(s.points) ? num(s.points, s.points % 1 ? 1 : 0) : '—') + '</strong></span><span>Wins<strong>' + (s.wins || 0) + '</strong></span>' +
        (c ? '<span>Title<strong>' + pct(c.p_title) + '</strong></span>' : '') + '<span>Car pace<strong>' + (last ? signed(last.effect, 2) + '%' : '—') + '</strong></span>' +
        (t.pit && isNum(t.pit.median_ms) ? '<span>Median stop<strong>' + num(t.pit.median_ms / 1000, 2) + 's</strong></span>' : '') + '</div></a>';
    }).join('') + '</div>';
    const drawPace = kind => {
      const tr = [];
      ids.forEach(id => { const r = series(season, kind, id); if (r.length) tr.push.apply(tr, bandTraces(r, PD.teamColour(id), PD.teamName(id), null, false)); });
      if (tr.length) plot('tm-pace', tr, paceLayout({ legend: { orientation: 'h', y: -0.2, font: { color: C.text2 } }, margin: { l: 55, r: 10, t: 10, b: 80 } }));
      else document.getElementById('tm-pace').innerHTML = muted('No car-pace series yet.');
    };
    drawPace('race');
    PG().wireToggle(el, 'tm-pace-kind', drawPace);
    // Catalogue table.
    const metrics = (teams && teams.metrics) || [];
    const heads = PG().headline(metrics, ['car_race_pace', 'car_quali_pace', 'top_speed', 'corner_speed', 'pit_stop_ms', 'strategy_gain', 'dnf_rate', 'car_share'], 12, true).filter(m => Object.keys(T).some(k => isNum((T[k].values || {})[m.key]))).slice(0, 7);
    if (Object.keys(T).length) {
      document.getElementById('tm-table').innerHTML = card('Team metrics', 'Value and field percentile (100 = best) on headline metrics; the full catalogue is on each team page.',
        tableHTML([{ label: 'Pos', align: 'right' }, { label: 'Team' }, { label: 'Pts', align: 'right' }].concat(heads.map(m => ({ label: PG().shortLabel(m.label), align: 'right', title: m.desc || m.label }))),
          ids.filter(id => T[id]).map(id => ({ _href: '#/team/' + id, cells: [{ v: (pos[id] || {}).pos || 99, html: (pos[id] || {}).pos ? String(pos[id].pos) : '—' }, { v: PD.teamName(id), html: PD.teamLink(id) },
            { v: (pos[id] || {}).points || 0, html: num((pos[id] || {}).points, 0) }].concat(heads.map(m => ({ v: isNum((T[id].pct || {})[m.key]) ? T[id].pct[m.key] : -1, html: '<span class="muted-inline">' + PG().fmt(m, (T[id].values || {})[m.key]) + '</span> ' + pctPill((T[id].pct || {})[m.key]) }))) })), { compact: true }));
      sortable('tm-table');
    }
  });
}

// ── team page ──────────────────────────────────────────────────────────────

function renderTeam(el, params, state) {
  const id = params.id;
  const y = PG().yearOf(params, state);
  el.innerHTML = muted('Loading ' + esc(PD.teamName(id)) + '…');
  return Promise.all([PG().season(y), PD.load('markets.json')]).then(res => {
    if (!PG().alive(el)) return;
    const drivers = res[0][0], teams = res[0][1], season = res[0][2], markets = res[1];
    const T = (PD.ok(teams) && teams.teams) || {};
    const t = T[id] || null;
    const colour = PD.teamColour(id);
    const name = (t && t.name) || PD.teamName(id);
    const D = ((drivers || {}).drivers) || {};
    const drvIds = ((((season || {}).teams || {})[id] || {}).drivers || []).slice();
    Object.keys(D).forEach(k => { if (D[k].team === id && drvIds.indexOf(k) < 0) drvIds.push(k); });
    drvIds.sort((a, b) => ((D[b] || {}).races || 0) - ((D[a] || {}).races || 0));
    const s = ((((season || {}).standings) || {}).constructors || []).find(x => x.team === id) || {};
    const ch = ((((season || {}).championship) || {}).constructors || {})[id] || null;
    const split = (((season || {}).car_driver_split) || {})[id] || null;

    let h = '<div class="pg-head" style="--team:' + esc(colour) + '"><div class="pg-num" style="font-size:1.1rem">' + esc(String(name).slice(0, 3).toUpperCase()) + '</div><div class="pg-body"><h2>' + esc(name) + '</h2>' +
      '<div class="pg-sub">' + drvIds.map(d => PD.driverLink(d)).join(' · ') + '<span class="chip">' + y + ' season</span></div></div>' +
      '<div class="pg-links">' + (drvIds.length >= 2 ? '<a href="#/compare/drivers/' + esc(drvIds[0]) + '/' + esc(drvIds[1]) + '">Compare the drivers →</a>' : '') + '<a href="#/teams">All teams →</a></div></div>';
    if (!t && !s.team && !drvIds.length) { el.innerHTML = h + card('This season', '', muted(esc(name) + ' is not in the ' + y + ' data' + (PD.ok(teams) ? '' : ' (the team catalogue is not built yet)') + '.')); return; }
    const rp = series(season, 'race', id), qp = series(season, 'quali', id);
    const last = rp.length ? rp[rp.length - 1] : null, lastQ = qp.length ? qp[qp.length - 1] : null;
    const pit = (t && t.pit) || {};
    const dnfs = ((t && t.log) || []).reduce((a, r) => a + (r.dnfs || 0), 0);
    h += '<div class="kpi-grid six">' + [
      statTile('Constructors', s.pos ? PD.ordinal(s.pos) : '—', PG().has(s.points) ? num(s.points, s.points % 1 ? 1 : 0) + ' points · ' + (s.wins || 0) + ' wins' : ''),
      statTile('Title chance', ch ? pct(ch.p_title) : '—', ch ? 'expected ' + num(ch.exp_points, 0) + ' (' + num(ch.p05, 0) + '–' + num(ch.p95, 0) + ')' + (ch.clinched ? ' · clinched' : ch.eliminated ? ' · eliminated' : '') : ''),
      statTile('Race car pace', last ? signed(last.effect, 3) + '%' : '—', last ? 'after round ' + last.round + ' · ± ' + num(last.se, 3) : ''),
      statTile('Quali car pace', lastQ ? signed(lastQ.effect, 3) + '%' : '—', lastQ ? 'after round ' + lastQ.round + ' · ± ' + num(lastQ.se, 3) : ''),
      statTile('Median stop', isNum(pit.median_ms) ? num(pit.median_ms / 1000, 2) + 's' : '—', isNum(pit.best_ms) ? 'best ' + num(pit.best_ms / 1000, 2) + 's' + (isNum(pit.p_under_2500) ? ' · ' + pct(pit.p_under_2500, 0) + ' under 2.5 s' : '') : ''),
      statTile('DNFs', t ? String(dnfs) : '—', t ? ((t.log || []).length) + ' rounds' : '')
    ].join('') + '</div>';
    h += '<div class="card"><div class="card-header">Car pace by race <span class="card-sub">The car\'s share of lap time from the state-space decomposition, % of a lap against the field (up = faster), ±1 standard error shaded. The field\'s other cars are faint.</span></div>' +
      '<div class="grid-2"><div id="tm-race" style="height:340px"></div><div id="tm-quali" style="height:340px"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Straight line against cornering <span class="card-sub" id="tm-prof-sub"></span></div><div id="tm-prof" style="height:360px"></div></div>' +
      '<div class="card"><div class="card-header">Pit crew <span class="card-sub">Stationary time per stop (OpenF1 stop duration where available, else pit-lane time); the 2.5 s line is the crew benchmark.</span></div><div id="tm-pit-tiles"></div><div id="tm-pit" style="height:260px"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">The drivers <span class="card-sub">Both cars this season on headline metrics, field percentiles.</span></div><div id="tm-drv"></div></div>' +
      '<div class="card"><div class="card-header">Car or driver? <span class="card-sub">Model-expected points split between the car and each driver.</span></div><div id="tm-split" style="height:300px"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Reliability and points by round <span class="card-sub">Points per round (bars) and retirements (red markers).</span></div><div id="tm-rel" style="height:300px"></div></div>' +
      '<div class="card"><div class="card-header">Constructors\' title <span class="card-sub">Model probability against the de-vigged market, and the simulated finishing-position distribution.</span></div><div id="tm-title"></div><div id="tm-posdist" style="height:220px"></div></div></div>';
    h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub">The team catalogue against the rest of the field (100 = best), including strategy outcome and reliability.</span></div><div id="tm-pct"></div></div>';
    h += '<div class="card" id="tm-needs-card" style="display:none"><div class="card-header">Strengths and needs <span class="card-sub">Areas graded against the field, the three biggest strengths and weaknesses, and the driver swaps that would add the most points.</span></div><div id="tm-needs" class="pad"></div></div>';
    el.innerHTML = h;
    needs(id, y);

    // Car pace charts.
    const others = Object.keys((((season || {}).car_pace || {}).race) || {}).filter(k => k !== id);
    const faint = kind => others.map(o => { const r = series(season, kind, o); return { type: 'scatter', mode: 'lines', name: PD.teamName(o), x: r.map(z => z.round), y: r.map(z => z.effect), line: { color: PG().alpha(PD.teamColour(o), 0.28), width: 1 }, hovertemplate: PD.teamName(o) + ' R%{x}: %{y:+.3f}%<extra></extra>', showlegend: false }; });
    if (rp.length) plot('tm-race', faint('race').concat(bandTraces(rp, colour, 'Race')), paceLayout({ title: { text: 'Race', font: { size: 12, color: C.text2 }, x: 0.02 }, showlegend: false }));
    else document.getElementById('tm-race').innerHTML = muted('No race car-pace series yet.');
    if (qp.length) plot('tm-quali', faint('quali').concat(bandTraces(qp, colour, 'Quali')), paceLayout({ title: { text: 'Qualifying', font: { size: 12, color: C.text2 }, x: 0.02 }, showlegend: false }));
    else document.getElementById('tm-quali').innerHTML = muted('No qualifying car-pace series yet.');

    // Straight-line v cornering scatter across teams.
    const metrics = (teams && teams.metrics) || [];
    const findM = res2 => { for (let i = 0; i < res2.length; i++) { const m = metrics.find(x => res2[i].test(x.key) || res2[i].test(x.label || '')); if (m) return m; } return null; };
    const mx = findM([/^top_speed$/, /top_?speed/i, /speed_?trap_kph/i]), my = findM([/^corner_speed$/, /corner_speed/i, /min.*speed/i]);
    const profIds = mx && my ? Object.keys(T).filter(k => isNum((T[k].values || {})[mx.key]) && isNum((T[k].values || {})[my.key])) : [];
    if (profIds.length >= 3) {
      document.getElementById('tm-prof-sub').innerHTML = esc(mx.label) + ' against ' + esc(my.label) + '; every team this season.';
      const ids = Object.keys(T).filter(k => isNum((T[k].values || {})[mx.key]) && isNum((T[k].values || {})[my.key]));
      plot('tm-prof', [{ type: 'scatter', mode: 'markers+text', x: ids.map(k => T[k].values[mx.key]), y: ids.map(k => T[k].values[my.key]), text: ids.map(k => PD.teamName(k)), textposition: 'top center', textfont: { size: 10, color: ids.map(k => (k === id ? '#ffffff' : C.text2)) },
        marker: { size: ids.map(k => (k === id ? 16 : 10)), color: ids.map(k => PD.teamColour(k)), line: { color: ids.map(k => (k === id ? '#ffffff' : '#0d1117')), width: ids.map(k => (k === id ? 2 : 0.5)) } },
        hovertemplate: '%{text}<br>' + esc(mx.label) + ': %{x}<br>' + esc(my.label) + ': %{y}<extra></extra>' }],
        layout({ margin: { l: 60, r: 15, t: 10, b: 50 }, xaxis: { title: mx.label, autorange: mx.lower ? 'reversed' : true }, yaxis: { title: my.label, autorange: my.lower ? 'reversed' : true } }));
    } else {
      document.getElementById('tm-prof-sub').innerHTML = 'from the team catalogue';
      document.getElementById('tm-prof').innerHTML = muted('Too few teams have both a top speed and a minimum-corner-speed figure this season (' + profIds.length + '). Corner speed comes from processed OpenF1 telemetry, which covers only some sessions so far.');
    }

    // Pit crew.
    document.getElementById('tm-pit-tiles').innerHTML = '<div class="kpi-grid" style="padding:12px 12px 0;margin-bottom:6px">' + [
      statTile('Median', isNum(pit.median_ms) ? num(pit.median_ms / 1000, 2) + 's' : '—'), statTile('Best', isNum(pit.best_ms) ? num(pit.best_ms / 1000, 2) + 's' : '—'),
      statTile('Under 2.5 s', isNum(pit.p_under_2500) ? pct(pit.p_under_2500, 0) : '—'), statTile('Stops', Array.isArray(pit.stops) ? pit.stops.length : (isNum(pit.stops) ? pit.stops : '—'))].join('') + '</div>';
    const drawPitHist = stopsMs => {
      const v = stopsMs.filter(x => isNum(x) && x > 0 && x < 15000).map(x => x / 1000);
      if (!v.length) { document.getElementById('tm-pit').innerHTML = muted('No stop durations recorded.'); return; }
      document.getElementById('tm-pit').innerHTML = '';
      plot('tm-pit', [{ type: 'histogram', x: v, xbins: { start: Math.floor(Math.min.apply(null, v) * 5) / 5, end: Math.ceil(Math.max.apply(null, v) * 5) / 5 + 0.2, size: 0.2 }, marker: { color: colour, line: { color: '#0d1117', width: 1 } }, hovertemplate: '%{x} s: %{y} stops<extra></extra>' }],
        layout({ margin: { l: 45, r: 10, t: 10, b: 40 }, xaxis: { title: 'Stationary time (s)' }, yaxis: { title: 'Stops' }, shapes: [{ type: 'line', x0: 2.5, x1: 2.5, yref: 'paper', y0: 0, y1: 1, line: { color: C.yellow, dash: 'dot', width: 1.5 } }] }));
    };
    if (Array.isArray(pit.stop_ms) && pit.stop_ms.length) drawPitHist(pit.stop_ms);
    else if (Array.isArray(pit.stops) && pit.stops.length && isNum(pit.stops[0])) drawPitHist(pit.stops);
    else {
      // Collect from the race files: pits rows with stop_ms for this team's drivers.
      const rounds = ((t && t.log) || []).map(r => r.round);
      const doneRounds = rounds.length ? rounds : (((season || {}).calendar) || []).filter(c => c.status === 'done').map(c => c.round);
      document.getElementById('tm-pit').innerHTML = muted('Loading stops…');
      Promise.all(doneRounds.map(r => PD.load(y + '/races/' + r + '.json'))).then(races => {
        if (!PG().alive(el)) return;
        const out = [];
        races.forEach(rc => (((rc || {}).pits) || []).forEach(p => { if (drvIds.indexOf(p.driver) >= 0 && isNum(p.stop_ms)) out.push(p.stop_ms); }));
        drawPitHist(out);
      });
    }

    // Drivers side by side.
    if (drvIds.length) {
      const dm = (drivers && drivers.metrics) || [];
      const heads = PG().headline(dm, ['race_pace', 'quali_pace', 'driver_effect', 'quali_driver_effect', 'avg_finish', 'overtakes_made', 'tyre_mgmt', 'points_v_expected', 'dnf_rate', 'exp_points'], 10, true);
      document.getElementById('tm-drv').innerHTML = tableHTML([{ label: 'Metric' }].concat(drvIds.slice(0, 3).map(d => ({ label: PD.driverSurname(d), align: 'right' }))),
        [{ cells: [{ v: 'Races', html: 'Races' }].concat(drvIds.slice(0, 3).map(d => ({ v: (D[d] || {}).races || 0, align: 'right' }))) }]
          .concat(heads.map(m => ({ cells: [{ v: m.label, html: PG().glossLink(m.key, esc(m.label)) }].concat(drvIds.slice(0, 3).map(d => ({ v: ((D[d] || {}).values || {})[m.key], html: PG().fmt(m, ((D[d] || {}).values || {})[m.key]) + ' ' + pctPill(((D[d] || {}).pct || {})[m.key]), align: 'right' }))) }))), { compact: true });
      if (drvIds.length >= 2 && D[drvIds[0]] && D[drvIds[1]]) {
        const hh = PG().h2h(D[drvIds[0]].log, D[drvIds[1]].log);
        const [ca, cb] = PG().pairColours(colour, colour);
        document.getElementById('tm-drv').insertAdjacentHTML('beforeend', '<div class="pg-h2h">' + PG().h2hBar('Qualifying head to head', hh.quali[0], hh.quali[1], ca, cb, PD.driverSurname(drvIds[0]), PD.driverSurname(drvIds[1])) +
          PG().h2hBar('Race head to head', hh.race[0], hh.race[1], ca, cb, PD.driverSurname(drvIds[0]), PD.driverSurname(drvIds[1])) + '</div>');
      }
    } else document.getElementById('tm-drv').innerHTML = muted('No drivers listed.');

    // Car / driver split.
    if (split && isNum(split.car)) {
      const dk = Object.keys(split.drivers || {});
      const hasBase = isNum(split.baseline);
      const xs = (hasBase ? ['Average team'] : []).concat(['Car']).concat(dk.map(k => PD.driverSurname(k))).concat(isNum(split.model_points) ? ['Model points'] : []);
      const ys = (hasBase ? [split.baseline] : []).concat([split.car]).concat(dk.map(k => split.drivers[k])).concat(isNum(split.model_points) ? [split.model_points] : []);
      const ms = (hasBase ? ['absolute'] : []).concat(['relative']).concat(dk.map(() => 'relative')).concat(isNum(split.model_points) ? ['total'] : []);
      plot('tm-split', [{ type: 'waterfall', x: xs, y: ys, measure: ms, text: ys.map(v => (v > 0 && ms[ys.indexOf(v)] === 'relative' ? '+' : '') + num(v, 1)), textposition: 'outside', cliponaxis: false,
        increasing: { marker: { color: C.green } }, decreasing: { marker: { color: C.red } }, totals: { marker: { color: colour } }, connector: { line: { color: '#30363d' } }, hovertemplate: '%{x}: %{y:.1f}<extra></extra>' }],
        layout({ margin: { l: 50, r: 20, t: 20, b: 40 }, yaxis: { title: 'Expected points' } }));
      document.getElementById('tm-split').insertAdjacentHTML('afterend', '<div class="pg-note">Shapley split of model-expected points: what an average car and drivers would score, plus the car\'s and each driver\'s marginal contribution. Car share ' + (isNum(split.car_share) ? pct(split.car_share, 0) : '—') + ' · actual points ' + num(split.points, 0) + ' · from ' + esc(split.source || 'race') + ' effects.</div>');
    } else document.getElementById('tm-split').innerHTML = muted('No car/driver split yet.');

    // Reliability and points by round.
    const lg = ((t && t.log) || []).slice().sort((a, b) => a.round - b.round);
    if (lg.length) {
      plot('tm-rel', [
        { type: 'bar', name: 'Points', x: lg.map(r => r.round), y: lg.map(r => r.points || 0), marker: { color: colour }, hovertemplate: 'R%{x}: %{y} pts<extra></extra>' },
        { type: 'scatter', mode: 'markers', name: 'DNFs', x: lg.filter(r => r.dnfs).map(r => r.round), y: lg.filter(r => r.dnfs).map(r => r.dnfs), yaxis: 'y2', marker: { symbol: 'x', size: 11, color: C.red }, hovertemplate: 'R%{x}: %{y} retirement(s)<extra></extra>' }
      ], layout({ showlegend: true, legend: { orientation: 'h', y: 1.14, font: { color: C.text2 } }, margin: { l: 45, r: 45, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: 'Points' },
        yaxis2: { title: 'DNFs', overlaying: 'y', side: 'right', range: [0, 2.5], dtick: 1, gridcolor: 'rgba(0,0,0,0)', zerolinecolor: '#30363d', linecolor: '#30363d' } }));
    } else document.getElementById('tm-rel').innerHTML = muted('No rounds logged yet.');

    // Title.
    const mk = (markets || {}).constructors_title || {};
    const price = (mk.prices || {})[id], model = ch ? ch.p_title : (mk.model || {})[id], edge = (mk.edge || {})[id];
    document.getElementById('tm-title').innerHTML = '<div class="kpi-grid" style="padding:12px 12px 0">' + [
      statTile('Model', PG().has(model) ? pct(model) : '—', ch ? 'season simulation' + ((season.championship || {}).n_sims ? ', ' + Number(season.championship.n_sims).toLocaleString() + ' runs' : '') : ''),
      statTile('Market', PG().has(price) ? pct(price) : '—', mk.available ? (mk.sources || []).length + ' source(s), de-vigged' : 'no market'),
      statTile('Edge', PG().has(edge) ? '<span class="' + (edge > 0 ? 'pg-edge-pos' : 'pg-edge-neg') + '">' + signed(100 * edge, 0) + '%</span>' : '—', 'model / market − 1'),
      statTile('Magic number', ch && PG().has(ch.magic) ? num(ch.magic, 0) : '—', 'points to clinch')
    ].join('') + '</div>';
    if (ch && (ch.pos_dist || []).length) {
      plot('tm-posdist', [{ type: 'bar', x: ch.pos_dist.map((p, i) => i + 1), y: ch.pos_dist, marker: { color: colour }, hovertemplate: 'P%{x}: %{y:.1%}<extra></extra>' }],
        layout({ margin: { l: 45, r: 10, t: 10, b: 40 }, xaxis: { title: 'Final constructors\' position', dtick: 1 }, yaxis: { tickformat: '.0%' } }));
    } else document.getElementById('tm-posdist').innerHTML = muted(season && season.championship === null ? 'The season is over.' : 'No simulation for this season.');

    document.getElementById('tm-pct').innerHTML = t ? PG().pctPanel(metrics, t.values, t.pct) : muted('Not in the team catalogue.');
  });
}

/* Strengths and needs: data/<y>/needs.json (the current season). */
const GRADE_COLOUR = { A: '#3fb950', B: '#7ee787', C: '#d29922', D: '#f97316', F: '#f85149' };
function gradeChip(g) { return g ? '<span class="pv-grade" style="background:' + (GRADE_COLOUR[g] || '#30363d') + '">' + g + '</span>' : '—'; }
function needs(id, y) {
  PD.load(y + '/needs.json').then(d => {
    const box = document.getElementById('tm-needs'), cardEl = document.getElementById('tm-needs-card');
    if (!box || !PD.ok(d) || !(d.teams || {})[id]) return;
    const x = d.teams[id];
    cardEl.style.display = '';
    const fmtA = a => (isNum(a.value) ? (Math.abs(a.value) >= 100 ? num(a.value, 0) : num(a.value, 3)) : '—');
    const item = (a, cls) => '<div class="pv-item ' + cls + '">' + gradeChip(a.grade) + ' <strong>' + esc(a.label) + '</strong> <span class="muted-inline">' + PD.ordinal(a.pct) + ' percentile</span><div class="pv-ev">' + esc(a.stat || '') + '</div></div>';
    const swaps = list => list && list.length ? tableHTML([{ label: 'In', sortable: false }, { label: 'From', sortable: false }, { label: 'Out', sortable: false },
      { label: 'Team points', align: 'right', sortable: false }, { label: 'Title', align: 'right', sortable: false }, { label: 'Their team', align: 'right', sortable: false }, { label: '', sortable: false }],
      list.map(s => ({ cells: [{ v: s.in_name, html: PD.driverLink(s.in, s.in_name) }, { v: s.from, html: PD.teamLink(s.from) }, { v: s.out_name, html: PD.driverLink(s.out, s.out_name) },
        { v: s.gain_pts, html: '<strong>' + signed(s.gain_pts, 1) + '</strong>' }, { v: s.gain_title, html: signed(100 * s.gain_title, 1) + ' pp' },
        { v: s.other_change, html: signed(s.other_change, 1) }, { v: '', html: '<a href="#/swap?x=' + encodeURIComponent(s.in) + '&w=' + encodeURIComponent(s.out) + '">Simulate →</a>' }] })), { compact: true }) : muted('No swap adds points.');
    const imp = (x.improve || []).map(w => '<div class="pv-imp-h">To improve: <strong>' + esc(w.label) + '</strong></div>' + (w.swaps && w.swaps.length ? swaps(w.swaps) : muted(esc(w.note || '')))).join('');
    box.innerHTML = '<div class="pv-label">' + esc(d.label || '') + '</div>' +
      '<div class="grid-2"><div><div class="pv-sub">Top strengths</div>' + ((x.strengths || []).map(a => item(a, 'pv-good')).join('') || muted('None stands out.')) + '</div>' +
      '<div><div class="pv-sub">Top weaknesses</div>' + ((x.weaknesses || []).map(a => item(a, 'pv-bad')).join('') || muted('None below the 40th percentile.')) + '</div></div>' +
      (x.balance ? '<div class="pv-note2">Balance: the car ' + esc(x.balance) + '.</div>' : '') +
      '<div class="pv-sub">Areas against the field</div>' + tableHTML([{ label: 'Area', sortable: false }, { label: 'Value', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Grade', align: 'right' }, { label: 'Measured as', sortable: false }],
        (x.areas || []).map(a => ({ cells: [{ v: a.label, html: esc(a.label) }, { v: a.value, html: fmtA(a) }, { v: a.pct, html: PD.pctPill(a.pct) }, { v: a.grade || '', html: gradeChip(a.grade) }, { v: '', html: '<span class="muted-inline">' + esc(a.stat || '') + '</span>' }] })), { compact: true }) +
      (imp ? '<div class="pv-sub">Ways to improve</div>' + imp : '') +
      '<div class="pv-sub">The driver swaps that would add the most points</div>' + swaps(x.best_swaps) +
      '<div class="pg-note">Grades: A from the 80th percentile, B 60th, C 40th, D 20th, F below, among the teams this season. Swaps: each pair run through the championship simulation of the remaining rounds (' + (d.swaps_n || '') + ' runs, common random numbers), the change in expected constructors\' points. <a href="#/swap">Driver-swap simulator →</a></div>';
  });
}

PD.route('teams', renderTeams);
PD.route('team', renderTeam);
})(window.PD);
