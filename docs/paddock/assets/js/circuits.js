/* The Quant Paddock — circuits: the index (#/circuits) and the circuit page (#/circuit/<id>).
 *
 * Data: data/circuits.json (every circuit since 1950: profile from models/circuits.py,
 * history of winners and poles, records), data/<y>/season.json (which rounds ran at
 * the circuit), data/<y>/races/<r>.json (session keys and whether telemetry exists)
 * and data/<y>/telemetry/<key>.json (the fastest lap's x/y for the track map). */
(function (PD) {
'use strict';

const { esc, num, pct, isNum, card, muted, tableHTML, sortable, statTile, plot, layout, C } = PD;
const PG = () => PD.pg;

function profileTiles(p) {
  if (!p) return muted('No profile yet.');
  const s = p.samples || {};
  const scRace = isNum(p.sc_rate_per_lap) && isNum(p.laps) ? p.sc_rate_per_lap * p.laps : null;
  const vscRace = isNum(p.vsc_rate_per_lap) && isNum(p.laps) ? p.vsc_rate_per_lap * p.laps : null;
  return '<div class="kpi-grid six">' + [
    statTile('Laps', isNum(p.laps) ? p.laps : '—', isNum(p.length_km) ? num(p.length_km, 3) + ' km · ' + num(p.distance_km, 1) + ' km' + (p.sprint_laps ? ' · sprint ' + p.sprint_laps + ' laps' : '') : ''),
    statTile('Pit loss', isNum(p.pit_loss_s) ? num(p.pit_loss_s, 1) + 's' : '—', 'time lost to a stop against staying out' + (isNum(p.pit_lane_s) ? ' · lane ' + num(p.pit_lane_s, 1) + 's' : '') + (s.pit ? ' · ' + num(s.pit, 0) + ' samples' : '')),
    statTile('Safety car', isNum(p.p_sc_race) ? pct(p.p_sc_race, 0) : '—', (scRace !== null ? num(scRace, 2) + ' SC deployments per race' : '') + ' · hazard ' + num(1000 * (p.sc_rate_per_lap || 0), 2) + ' per 1,000 laps'),
    statTile('Virtual SC', isNum(p.p_vsc_race) ? pct(p.p_vsc_race, 0) : '—', (vscRace !== null ? num(vscRace, 2) + ' VSC per race' : '') + ' · hazard ' + num(1000 * (p.vsc_rate_per_lap || 0), 2) + ' per 1,000 laps'),
    statTile('Overtaking difficulty', isNum(p.overtake_difficulty) ? num(100 * p.overtake_difficulty, 0) + '/100' : '—', isNum(p.overtake_threshold_s) ? 'needs ' + num(p.overtake_threshold_s, 2) + ' s/lap pace edge for an even chance · ' + num(p.passes_per_car_lap, 3) + ' passes per car-lap' : ''),
    statTile('Typical stops', isNum(p.typical_stops) ? num(p.typical_stops, 1) : '—', 'wet chance ' + (isNum(p.p_wet) ? pct(p.p_wet, 0) : '—') + ' · DNFs/race ' + num((p.dnf_mech_per_race || 0) + (p.dnf_incident_per_race || 0), 2) + ' (' + num(p.dnf_mech_per_race, 2) + ' mech, ' + num(p.dnf_incident_per_race, 2) + ' incident)')
  ].join('') + '</div>';
}

// ── index ──────────────────────────────────────────────────────────────────

function renderCircuits(el, params, state) {
  const y = PG().yearOf(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">Circuits <span class="card-sub">Every circuit that has held a world championship race since 1950. Profiles come from the circuit model (pit loss, safety-car hazards, overtaking) shrunk to the global profile.</span>' +
    '<span class="pg-ctl">' + PG().toggle('ci-scope', [['cal', y + ' calendar'], ['all', 'All circuits']], 'cal') + '<input id="ci-q" class="pg-search" type="search" placeholder="Filter…"></span></div><div id="ci-table">' + muted('Loading…') + '</div></div>';
  return Promise.all([PD.load('circuits.json'), PD.load(y + '/season.json'), PD.load('elo.json')]).then(res => {
    if (!PG().alive(el)) return;
    const all = res[0], season = res[1];
    if (!all || all.ok === false) { document.getElementById('ci-table').innerHTML = PG().notBuilt('The circuit file', all); return; }
    const cal = {};
    (((season || {}).calendar) || []).forEach(c => { if (c.circuit && c.circuit.id) cal[c.circuit.id] = c; });
    const ids = Object.keys(all).filter(k => all[k] && typeof all[k] === 'object' && (all[k].name || all[k].profile));
    let scope = Object.keys(cal).length ? 'cal' : 'all';
    if (scope === 'all') { const t = document.getElementById('ci-scope'); if (t) t.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === 'all')); }
    const draw = () => {
      const q = (document.getElementById('ci-q').value || '').trim().toLowerCase();
      const list = ids.filter(k => (scope === 'all' || cal[k]) && (!q || ((all[k].name || '') + ' ' + (all[k].country || '') + ' ' + k).toLowerCase().indexOf(q) >= 0))
        .sort((a, b) => scope === 'cal' ? (cal[a].round - cal[b].round) : ((all[b].history || []).length - (all[a].history || []).length));
      const host = document.getElementById('ci-table');
      host.innerHTML = tableHTML([{ label: scope === 'cal' ? 'Rd' : '#', align: 'right' }, { label: 'Circuit' }, { label: 'Country' }, { label: 'Races', align: 'right', title: 'World championship races held' }, { label: 'Span' },
        { label: 'Last winner' }, { label: 'Laps', align: 'right' }, { label: 'Pit loss', align: 'right' }, { label: 'P(SC)', align: 'right' }, { label: 'Overtaking', align: 'right', title: 'Difficulty 0–100' }, { label: 'Stops', align: 'right' }, { label: 'Wet', align: 'right' }],
        list.map((k, i) => {
          const c = all[k], p = c.profile || {}, hist = (c.history || []).slice().sort((a, b) => b.year - a.year);
          const yrs = hist.map(h => h.year);
          return { _href: '#/circuit/' + k, cells: [scope === 'cal' ? cal[k].round : i + 1, { v: c.name || k, html: PD.circuitLink(k, c.name) }, c.country || '', hist.length,
            yrs.length ? Math.min.apply(null, yrs) + '–' + Math.max.apply(null, yrs) : '—', { v: hist[0] ? PD.driverName(hist[0].winner) : '', html: hist[0] ? PD.driverLink(hist[0].winner) + ' <span class="muted-inline">' + hist[0].year + '</span>' : '—' },
            { v: p.laps, html: isNum(p.laps) ? String(p.laps) : '—' }, { v: p.pit_loss_s, html: isNum(p.pit_loss_s) ? num(p.pit_loss_s, 1) + 's' : '—' },
            { v: p.p_sc_race, html: isNum(p.p_sc_race) ? pct(p.p_sc_race, 0) : '—' }, { v: p.overtake_difficulty, html: isNum(p.overtake_difficulty) ? num(100 * p.overtake_difficulty, 0) : '—' },
            { v: p.typical_stops, html: isNum(p.typical_stops) ? num(p.typical_stops, 1) : '—' }, { v: p.p_wet, html: isNum(p.p_wet) ? pct(p.p_wet, 0) : '—' }] };
        }), { sticky: true });
      sortable(host);
    };
    PG().wireToggle(el, 'ci-scope', v => { scope = v; draw(); });
    document.getElementById('ci-q').addEventListener('input', draw);
    draw();
  });
}

// ── circuit page ───────────────────────────────────────────────────────────

/* The latest session at this circuit with a telemetry file: walk seasons back from the
 * current one (OpenF1 starts in 2023), find done rounds here, prefer quali then race. */
function findTelemetry(id, years) {
  let i = 0;
  const next = () => {
    if (i >= years.length) return Promise.resolve(null);
    const y = years[i++];
    return PD.load(y + '/season.json').then(s => {
      const rounds = (((s || {}).calendar) || []).filter(c => c.circuit && c.circuit.id === id && c.status === 'done').map(c => c.round).sort((a, b) => b - a);
      if (!rounds.length) return next();
      return PD.load(y + '/races/' + rounds[0] + '.json').then(r => {
        const ses = (r || {}).sessions || {}, tf = (r || {}).telemetry || {};
        const order = ['quali', 'race', 'sprint_quali', 'sprint'].filter(k => ses[k] && tf[k] !== false);
        const tryK = j => {
          if (j >= order.length) return next();
          return PD.load(y + '/telemetry/' + ses[order[j]] + '.json').then(t => (t && t.fastest && Object.keys(t.fastest).length ? { year: y, round: rounds[0], kind: order[j], key: ses[order[j]], tel: t, name: r.name } : tryK(j + 1)));
        };
        return tryK(0);
      });
    });
  };
  return next();
}

/* Pick the trace to draw: the reference driver's fastest lap, else any with x/y. */
function mapTrace(tel) {
  const F = tel.fastest || {};
  const refDn = String(((tel.ref || {}).driver) || '');
  const order = [refDn].concat(Object.keys(F).sort((a, b) => (F[a].ms || 1e9) - (F[b].ms || 1e9)));
  for (let i = 0; i < order.length; i++) { const f = F[order[i]]; if (f && (f.x || []).length > 10) return { dn: order[i], f: f }; }
  return null;
}

/* Track map coloured by speed with the corner numbers. */
function drawTrackMap(elId, tel) {
  const pick = mapTrace(tel);
  if (!pick) { document.getElementById(elId).innerHTML = muted('The telemetry file has no position data.'); return null; }
  document.getElementById(elId).innerHTML = '';
  const f = pick.f, step = f.d || 10;
  const corners = ((tel.ref || {}).corners) || [];
  const ann = corners.map(c => { const k = Math.min(f.x.length - 1, Math.round(c.d / step)); return { x: f.x[k], y: f.y[k], text: String(c.n), showarrow: false, font: { size: 10, color: '#ffffff' }, bgcolor: 'rgba(13,17,23,0.75)', borderpad: 2 }; });
  plot(elId, [
    { type: 'scatter', mode: 'lines', x: f.x, y: f.y, line: { color: '#30363d', width: 9 }, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'markers', x: f.x, y: f.y, marker: { size: 4, color: f.speed, colorscale: 'Turbo', cmin: Math.min.apply(null, f.speed), cmax: Math.max.apply(null, f.speed), colorbar: { title: { text: 'km/h', side: 'right' }, thickness: 10, tickfont: { color: C.text2 } } },
      text: f.speed.map((v, i) => Math.round(i * step) + ' m · ' + v + ' km/h · gear ' + (f.gear || [])[i]), hovertemplate: '%{text}<extra></extra>' },
    { type: 'scatter', mode: 'markers', x: [f.x[0]], y: [f.y[0]], marker: { symbol: 'square', size: 10, color: '#ffffff' }, hovertemplate: 'start/finish<extra></extra>' }
  ], layout({ margin: { l: 10, r: 10, t: 10, b: 10 }, annotations: ann, xaxis: { visible: false, scaleanchor: 'y' }, yaxis: { visible: false } }));
  return pick;
}

function recordsHTML(rec) {
  if (!rec || typeof rec !== 'object' || !Object.keys(rec).length) return muted('No records yet.');
  const rows = [];
  const lr = rec.lap_record;
  if (lr && isNum(lr.ms)) rows.push(['Fastest race lap', '<strong>' + PD.fmtMs(lr.ms) + '</strong> ' + PD.driverLink(lr.driver) + (lr.team ? ' · ' + PD.teamLink(lr.team) : '') + ' <span class="muted-inline">' + esc(lr.year) + (lr.round ? ' R' + esc(lr.round) : '') + '</span>']);
  const list = (arr, k, link) => (arr || []).map(x => link(x) + ' <strong>' + x[k] + '</strong>').join(' · ');
  if ((rec.most_wins || []).length) rows.push(['Most wins', list(rec.most_wins, 'wins', x => PD.driverLink(x.driver))]);
  if ((rec.most_poles || []).length) rows.push(['Most poles', list(rec.most_poles, 'poles', x => PD.driverLink(x.driver))]);
  if ((rec.most_team_wins || []).length) rows.push(['Most wins by a team', list(rec.most_team_wins, 'wins', x => PD.teamLink(x.team))]);
  if (isNum(rec.won_from_pole)) rows.push(['Won from pole', pct(rec.won_from_pole, 0) + ' of races with a known pole']);
  if (isNum(rec.races)) rows.push(['Races held', rec.races + (rec.first_year ? ' (' + rec.first_year + '–' + rec.last_year + ')' : '')]);
  const known = ['lap_record', 'most_wins', 'most_poles', 'most_team_wins', 'won_from_pole', 'races', 'first_year', 'last_year'];
  Object.keys(rec).filter(k => known.indexOf(k) < 0 && rec[k] !== null && typeof rec[k] !== 'object').forEach(k => rows.push([PD.titleCase(k), esc(rec[k])]));
  return tableHTML([{ label: 'Record', sortable: false }, { label: 'Holder', sortable: false }], rows.map(r => [{ v: r[0], html: esc(r[0]) }, { v: '', html: r[1], style: 'white-space:normal' }]), { compact: true });
}

function renderCircuit(el, params, state) {
  const id = params.id;
  el.innerHTML = muted('Loading ' + esc(PD.circuitName(id)) + '…');
  return PD.loadAll(['circuits.json', 'elo.json']).then(both => {
    const all = both[0];
    if (!PG().alive(el)) return;
    const c = (all || {})[id];
    if (!c) { el.innerHTML = card(PD.circuitName(id), '', all ? muted('No circuit with id <code>' + esc(id) + '</code>. <a href="#/circuits">All circuits →</a>') : PG().notBuilt('The circuit file', all)); return; }
    const p = c.profile || null;
    const hist = (c.history || []).slice().sort((a, b) => b.year - a.year);
    const yrs = hist.map(x => x.year);
    let h = '<div class="pg-head" style="--team:' + C.teal + '"><div class="pg-num" style="font-size:1.1rem">' + esc(String(c.country || id).slice(0, 3).toUpperCase()) + '</div><div class="pg-body"><h2>' + esc(c.name || PD.circuitName(id)) + '</h2>' +
      '<div class="pg-sub">' + esc(c.country || '') + (hist.length ? '<span class="chip">' + hist.length + ' world championship race' + (hist.length === 1 ? '' : 's') + ', ' + Math.min.apply(null, yrs) + '–' + Math.max.apply(null, yrs) + '</span>' : '') + '</div></div>' +
      '<div class="pg-links"><a href="#/circuits">All circuits →</a></div></div>';
    h += profileTiles(p);
    h += '<div class="grid-2"><div class="card"><div class="card-header">Track map <span class="card-sub" id="ci-map-sub">fastest lap position data, coloured by speed</span></div><div id="ci-map" style="height:460px">' + muted('Looking for telemetry…') + '</div></div>' +
      '<div class="card"><div class="card-header">Model profile <span class="card-sub">What the race simulator uses at this circuit.</span></div><div id="ci-prof"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">History <span class="card-sub">Winners and pole sitters, newest first.</span></div><div id="ci-hist" style="max-height:520px;overflow-y:auto"></div></div>' +
      '<div class="card"><div class="card-header">Records <span class="card-sub">From the results since 1950.</span></div><div id="ci-rec"></div><div class="card-header" style="border-top:1px solid var(--border)">Most wins here</div><div id="ci-wins" style="height:260px"></div></div></div>';
    h += '<div class="card"><div class="card-header">Opening lap <span class="card-sub">Places gained or lost on lap 1 by grid slot and the lap-1 incident rate. The mean per slot is fitted on every circuit together; the whiskers (±1 sd) are scaled to this circuit, so the spread is what differs from track to track.</span></div><div id="ci-lap1" style="height:280px"></div></div>';
    el.innerHTML = h;

    // Profile table v global.
    if (p) {
      const g = p.global || null;
      const rows = [['Pit loss (s)', p.pit_loss_s, 'pit_loss_s', 2], ['SC hazard per lap', p.sc_rate_per_lap, 'sc_rate_per_lap', 5], ['VSC hazard per lap', p.vsc_rate_per_lap, 'vsc_rate_per_lap', 5],
        ['P(SC in the race)', p.p_sc_race, null, 3], ['P(VSC in the race)', p.p_vsc_race, null, 3], ['Pass probability', p.pass_prob, 'pass_prob', 4], ['Passes per car-lap', p.passes_per_car_lap, null, 4],
        ['Overtake threshold (s/lap)', p.overtake_threshold_s, null, 3], ['Typical stops', p.typical_stops, 'typical_stops', 2], ['Mechanical DNFs per race', p.dnf_mech_per_race, 'dnf_mech_per_race', 3],
        ['Incident DNFs per race', p.dnf_incident_per_race, 'dnf_incident_per_race', 3], ['Wet chance', p.p_wet, 'p_wet', 3]].filter(r => isNum(r[1]));
      const s = p.samples || {};
      const cols = [{ label: 'Parameter' }, { label: 'Here', align: 'right' }].concat(g ? [{ label: 'Global', align: 'right' }, { label: 'Ratio', align: 'right' }] : []);
      document.getElementById('ci-prof').innerHTML = tableHTML(cols, rows.map(r => {
        const gv = g && r[2] ? g[r[2]] : null;
        return [r[0], { v: r[1], html: num(r[1], r[3]), align: 'right' }].concat(g ? [{ v: gv, html: isNum(gv) ? num(gv, r[3]) : '—', align: 'right' }, { v: isNum(gv) && gv ? r[1] / gv : null, html: isNum(gv) && gv ? num(r[1] / gv, 2) + '×' : '—', align: 'right' }] : []);
      }), { compact: true }) +
        '<div class="pg-note">The circuit model shrinks each figure towards the all-circuit profile in proportion to how much history the circuit has. Samples behind the figures: ' +
        [['races', s.races], ['pit samples', s.pit], ['SC laps', s.sc_laps], ['pass opportunities', s.pass_opps], ['stops', s.stops], ['starts', s.starts]].filter(x => isNum(x[1])).map(x => num(x[1], 0) + ' ' + x[0]).join(', ') + '. <a href="#/methodology/circuits">Methodology</a> → circuit profiles.</div>';
      const mean = p.lap1_mean_by_grid || [], sd = p.lap1_sd_by_grid || [], inc = p.lap1_incident_by_grid || [];
      if (mean.length) {
        const g2 = mean.map((v, i) => i + 1);
        plot('ci-lap1', [
          { type: 'bar', name: 'Mean places gained', x: g2, y: mean, error_y: { type: 'data', array: sd.map(v => v * (p.lap1_sd_scale || 1)), visible: sd.length > 0, color: '#6e7681', thickness: 1 }, marker: { color: mean.map(v => (v >= 0 ? C.green : C.red)) }, hovertemplate: 'P%{x}: %{y:+.2f} places<extra></extra>' },
          { type: 'scatter', mode: 'lines+markers', name: 'Incident rate', x: g2, y: inc, yaxis: 'y2', line: { color: C.yellow, width: 1.5 }, hovertemplate: 'P%{x}: %{y:.1%} lap-1 incident<extra></extra>' }
        ], layout({ showlegend: true, legend: { orientation: 'h', y: 1.15, font: { color: C.text2 } }, margin: { l: 50, r: 50, t: 30, b: 40 }, xaxis: { title: 'Grid slot', dtick: 1 }, yaxis: { title: 'Places gained on lap 1' },
          yaxis2: { overlaying: 'y', side: 'right', tickformat: '.0%', title: 'Incident', gridcolor: 'rgba(0,0,0,0)', zerolinecolor: '#30363d', linecolor: '#30363d' } }));
        if (mean.every(v => !v)) document.getElementById('ci-lap1').insertAdjacentHTML('afterend', '<div class="pg-note">The profile carries a zero mean gain for every slot, so only the spread (whiskers, ±1 sd of places gained) and the incident rate vary by grid slot.</div>');
      } else document.getElementById('ci-lap1').innerHTML = muted('No opening-lap profile.');
    } else { document.getElementById('ci-prof').innerHTML = muted('No profile.'); document.getElementById('ci-lap1').innerHTML = ''; }

    // History and wins.
    document.getElementById('ci-hist').innerHTML = hist.length ? tableHTML([{ label: 'Year' }, { label: 'Winner' }, { label: 'Team' }, { label: 'Pole' }],
      hist.map(x => [x.year, { v: PD.driverName(x.winner), html: PD.driverLink(x.winner) }, { v: PD.teamName(x.team), html: x.team ? PD.teamLink(x.team) : '—' }, { v: x.pole ? PD.driverName(x.pole) : '', html: x.pole ? PD.driverLink(x.pole) + (x.pole === x.winner ? ' <span class="pg-tag good">won from pole</span>' : '') : '—' }]), { compact: true, sticky: true }) : muted('No races recorded.');
    sortable('ci-hist');
    document.getElementById('ci-rec').innerHTML = recordsHTML(c.records);
    const wins = {};
    hist.forEach(x => { if (x.winner) wins[x.winner] = (wins[x.winner] || 0) + 1; });
    const top = Object.keys(wins).sort((a, b) => wins[b] - wins[a]).slice(0, 8).reverse();
    if (top.length) plot('ci-wins', [{ type: 'bar', orientation: 'h', y: top.map(k => PD.driverName(k)), x: top.map(k => wins[k]), marker: { color: C.teal }, text: top.map(k => wins[k]), textposition: 'outside', cliponaxis: false, hovertemplate: '%{y}: %{x} wins<extra></extra>' }],
      layout({ margin: { l: 140, r: 30, t: 10, b: 30 }, xaxis: { dtick: 1 } }));
    else document.getElementById('ci-wins').innerHTML = '';

    // Track map from the latest telemetry session here.
    const cur = PD.currentSeason();
    const years = []; for (let yy = cur; yy >= 2023; yy--) years.push(yy);
    findTelemetry(id, years).then(t => {
      if (!PG().alive(el)) return;
      if (!t) { document.getElementById('ci-map').innerHTML = muted('No telemetry session at this circuit yet (OpenF1 car and position data start in 2023).'); return; }
      const pick = drawTrackMap('ci-map', t.tel);
      if (pick) document.getElementById('ci-map-sub').innerHTML = esc(t.year + ' ' + (t.name || '') + ' ' + ({ quali: 'qualifying', race: 'race', sprint: 'sprint', sprint_quali: 'sprint qualifying' }[t.kind] || t.kind)) + ': fastest lap of car #' + esc(pick.dn) +
        (pick.f.ms ? ' (' + PD.fmtMs(pick.f.ms) + ')' : '') + ', coloured by speed; numbers are the corners found on the reference lap. <a href="' + PD.raceHref(t.year, t.round, 'telemetry') + '">Telemetry lab →</a>';
    });
  });
}

PD.pg_drawTrackMap = drawTrackMap;
PD.route('circuits', renderCircuits);
PD.route('circuit', renderCircuit);
})(window.PD);
