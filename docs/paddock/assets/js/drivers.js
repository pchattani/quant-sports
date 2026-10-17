/* The Quant Paddock — drivers: the index (#/drivers) and the driver page (#/driver/<id>).
 *
 * Also defines PD.pg, the small set of helpers the other page modules (teams,
 * circuits, lab, compare, markets, calibration, telemetry, docs) share: metric
 * grouping, percentile panels, the radar, toggles and a few formatters. They are
 * read at render time, so script order does not matter.
 *
 * Data: data/<y>/drivers.json (catalogue, percentiles, race log), data/<y>/season.json
 * (standings, championship, Elo, driver effects), data/drivers/<id>.json (career),
 * data/<y>/races/<r>.json (expected points, lazily, for the points chart). */
(function (PD) {
'use strict';

const { esc, num, pct, signed, fmtVal, isNum, card, muted, tableHTML, sortable, pctPill, pctRow, statTile, plot, layout, C, PALETTE } = PD;

// ── shared helpers (PD.pg) ─────────────────────────────────────────────────

const PG = PD.pg = PD.pg || {};

PG.alive = el => !!el && el.isConnected;
PG.has = v => v !== undefined && v !== null && !(typeof v === 'number' && isNaN(v));
PG.yearOf = (params, state) => (params && typeof params.year === 'number') ? params.year : (state && state.year) || PD.currentSeason();
PG.metaOf = metrics => { const m = {}; (metrics || []).forEach(x => { m[x.key] = x; }); return m; };
PG.groups = metrics => {
  const out = [];
  (metrics || []).forEach(m => { let g = out.find(x => x.name === m.group); if (!g) { g = { name: m.group || 'Other', items: [] }; out.push(g); } g.items.push(m); });
  return out;
};
PG.fmt = (m, v) => fmtVal(v, (m || {}).fmt);
PG.median = a => { const s = a.filter(isNum).slice().sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
PG.mean = a => { const s = a.filter(isNum); return s.length ? s.reduce((x, y) => x + Number(y), 0) / s.length : null; };
PG.ageOf = dob => {
  const d = PD.parseDate(dob);
  if (!d) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
};
/* Classified finish: Jolpica status "Finished" or "+n Lap(s)" / "Lapped". */
PG.finished = st => !st || st === 'Finished' || /^\+\d+ Laps?$/.test(st) || st === 'Lapped';
PG.posHTML = (pos, status) => {
  if (!PG.has(pos)) return '<span class="muted-inline">—</span>';
  if (status && !PG.finished(status)) return '<span class="pg-dnf" title="' + esc(status) + '">' + (/disq/i.test(status) ? 'DSQ' : 'DNF') + '</span>';
  return '<span class="pg-pos' + (pos <= 3 ? ' p' + pos : '') + '">P' + pos + '</span>';
};
PG.deltaHTML = (v, digits) => !isNum(v) ? '<span class="muted-inline">—</span>' : '<span class="' + (v > 0 ? 'pg-up' : v < 0 ? 'pg-down' : '') + '">' + signed(v, digits === undefined ? 0 : digits) + '</span>';
PG.toggle = (id, opts, cur) => '<span class="pg-toggle" id="' + esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + esc(o[0]) + '"' + (o[0] === cur ? ' class="on"' : '') + '>' + esc(o[1]) + '</button>').join('') + '</span>';
PG.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fn(b.dataset.v);
  }));
};
PG.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + encodeURIComponent(key) + '" title="Glossary: ' + esc(key) + '">' + text + '</a>';

/* Percentile bars over the whole catalogue, grouped, in two columns.
 * pctSrc: {key: 0-100}; vals: {key: v}. */
PG.pctPanel = (metrics, vals, pctSrc, opts) => {
  const o = opts || {};
  const groups = PG.groups(metrics);
  if (!groups.length) return muted('No metrics in the catalogue yet.');
  return '<div class="pg-pct-cols">' + groups.map(g => '<div class="pct-group"><div class="pct-group-head">' + esc(g.name) + '</div>' +
    g.items.map(m => pctRow(m.label + (m.lower ? ' ↓' : ''), (pctSrc || {})[m.key], PG.fmt(m, (vals || {})[m.key]), (m.desc || '') + (m.lower ? ' (lower is better; the percentile already accounts for it)' : ''))).join('') + '</div>').join('') + '</div>' +
    (o.note ? '<div class="pg-note">' + o.note + '</div>' : '');
};

/* Percentile radar for one or more rows: [{name, pct, colour}]. */
PG.radar = (el, axes, rows) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  axes = axes.filter(a => rows.some(r => r && r.pct && isNum(r.pct[a.key])));
  const usable = rows.filter(r => r && r.pct && axes.some(a => isNum(r.pct[a.key])));
  if (!usable.length || !axes.length) { node.innerHTML = muted('No percentiles to draw yet.'); return; }
  // On a phone the angular labels sit outside the plot area: wrap long ones and shrink the font.
  const narrow = (node.clientWidth || 600) < 520;
  const wrap = s => (narrow && s.length > 12 ? s.replace(/^(.{6,14}?)\s+/, '$1<br>') : s);
  axes = axes.map(a => Object.assign({}, a, { label: wrap(a.label) }));
  plot(node, usable.map((r, i) => ({
    type: 'scatterpolar', fill: 'toself', name: r.name,
    r: axes.map(a => (isNum(r.pct[a.key]) ? r.pct[a.key] : 0)).concat([isNum(r.pct[axes[0].key]) ? r.pct[axes[0].key] : 0]),
    theta: axes.map(a => a.label).concat([axes[0].label]),
    line: { color: r.colour || (i === 0 ? C.blue : C.orange), width: 2 }, fillcolor: PG.alpha(r.colour || (i === 0 ? C.blue : C.orange), 0.18),
    hovertemplate: '%{theta}: %{r:.0f}th percentile<extra>' + esc(r.name) + '</extra>'
  })), layout({
    showlegend: usable.length > 1, legend: { orientation: 'h', y: -0.1, font: { color: C.text2 } },
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 100], gridcolor: '#21262d', tickfont: { size: 9 }, tickvals: [25, 50, 75, 100] }, angularaxis: { gridcolor: '#21262d', tickfont: { size: narrow ? 8 : 10 } } },
    margin: narrow ? { l: 46, r: 46, t: 24, b: 40 } : { l: 60, r: 60, t: 20, b: 40 }
  }));
};
PG.alpha = (hex, a) => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(88,166,255,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};

/* Pick up to n headline metrics: preferred patterns first (matched against key),
 * then fill from groups not yet represented, then anything with percentiles. */
PG.headline = (metrics, prefs, n, pctAny) => {
  const out = [];
  const usable = (metrics || []).filter(m => !pctAny || isNum(pctAny[m.key]) || pctAny === true);
  (prefs || []).forEach(p => {
    if (out.length >= n) return;
    const re = p instanceof RegExp ? p : new RegExp('^' + p + '$');
    const m = usable.find(x => re.test(x.key) && out.indexOf(x) < 0);
    if (m) out.push(m);
  });
  const groupsSeen = new Set(out.map(m => m.group));
  usable.forEach(m => { if (out.length < n && !groupsSeen.has(m.group) && out.indexOf(m) < 0) { out.push(m); groupsSeen.add(m.group); } });
  usable.forEach(m => { if (out.length < n && out.indexOf(m) < 0) out.push(m); });
  return out.slice(0, n);
};
PG.shortLabel = s => String(s || '').replace(/ to teammate/i, ' v TM').replace(/ per race/i, '/race').slice(0, 26);

/* Load a season's driver catalogue, team catalogue and season payload. */
PG.season = y => PD.loadAll([y + '/drivers.json', y + '/teams.json', y + '/season.json']);
PG.teamOfDriver = (season, drivers, id) => {
  const d = ((drivers || {}).drivers || {})[id];
  if (d && d.team) return d.team;
  const t = (season || {}).teams || {};
  const hit = Object.keys(t).find(k => (t[k].drivers || []).indexOf(id) >= 0);
  return hit || (PD.NAMES.drivers[id] || {}).team || null;
};
/* Teammates of id in a season (everyone else in the same car, by drivers.json or season.teams). */
PG.teammates = (season, drivers, id) => {
  const team = PG.teamOfDriver(season, drivers, id);
  if (!team) return [];
  const set = new Set();
  (((season || {}).teams || {})[team] || {}).drivers && season.teams[team].drivers.forEach(x => { if (x !== id) set.add(x); });
  const D = (drivers || {}).drivers || {};
  Object.keys(D).forEach(k => { if (k !== id && D[k].team === team) set.add(k); });
  // The teammate with most races first.
  return Array.from(set).sort((a, b) => ((D[b] || {}).races || 0) - ((D[a] || {}).races || 0));
};
/* Head to head from two race logs: quali (lower quali_pos), race (both classified, lower pos), points. */
PG.h2h = (logA, logB) => {
  const byRound = {};
  (logB || []).forEach(r => { byRound[r.round] = r; });
  const out = { quali: [0, 0], race: [0, 0], points: [0, 0], both: 0, rows: [] };
  (logA || []).forEach(a => {
    const b = byRound[a.round];
    if (!b) return;
    out.both++;
    if (isNum(a.quali_pos) && isNum(b.quali_pos)) out.quali[a.quali_pos < b.quali_pos ? 0 : 1]++;
    const fa = PG.finished(a.status) && isNum(a.pos), fb = PG.finished(b.status) && isNum(b.pos);
    if (fa && fb) out.race[a.pos < b.pos ? 0 : 1]++;
    else if (fa && !fb) out.race[0]++;
    else if (fb && !fa) out.race[1]++;
    out.points[0] += a.points || 0; out.points[1] += b.points || 0;
    out.rows.push([a, b]);
  });
  return out;
};
PG.h2hBar = (label, a, b, ca, cb, nameA, nameB) => {
  const n = (a || 0) + (b || 0);
  const wa = n ? 100 * a / n : 50;
  return '<div class="pg-h2h-lab">' + esc(label) + '</div><div class="pg-h2h-row"><span class="n" title="' + esc(nameA) + '">' + esc(nameA) + ' ' + num(a, Number.isInteger(a) ? 0 : 1) + '</span>' +
    '<div class="pg-h2h-bar"><span style="width:' + wa + '%;background:' + ca + '"></span><span style="width:' + (100 - wa) + '%;background:' + cb + '"></span></div>' +
    '<span class="n r" title="' + esc(nameB) + '">' + num(b, Number.isInteger(b) ? 0 : 1) + ' ' + esc(nameB) + '</span></div>';
};
/* Distinguishable second colour when two drivers share a team colour. */
PG.pairColours = (ca, cb) => {
  if (!ca || !cb || ca.toLowerCase() !== cb.toLowerCase()) return [ca || C.blue, cb || C.orange];
  return [ca, '#e6edf3'];
};
PG.notBuilt = (what, d) => muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '. The payload is rebuilt after each session.');

// ── drivers index ──────────────────────────────────────────────────────────

const INDEX_PREFS = ['race_pace', 'quali_pace', 'quali_gap_tm_pct', 'overtakes_made', 'points_v_expected', /pace/, /overtak/];

function renderDrivers(el, params, state) {
  const y = PG.yearOf(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">Drivers ' + y + ' <span class="card-sub">Every driver who started a race this season. Pills are field percentiles (100 = best). Click a header to sort, a row to open the driver.</span>' +
    '<span class="pg-ctl"><input id="drv-q" class="pg-search" type="search" placeholder="Filter drivers…"></span></div><div id="drv-table">' + muted('Loading…') + '</div></div>' +
    '<div id="drv-elo"></div>';
  return Promise.all([PG.season(y), PD.load('elo.json')]).then(res => {
    if (!PG.alive(el)) return;
    const [drivers, teams, season] = res[0];
    const elo = res[1];
    if (!PD.ok(drivers) || !drivers.drivers) { document.getElementById('drv-table').innerHTML = PG.notBuilt('The ' + y + ' driver catalogue', drivers); return; }
    const meta = PG.metaOf(drivers.metrics);
    const D = drivers.drivers;
    const stand = {};
    (((season || {}).standings || {}).drivers || []).forEach(s => { stand[s.driver] = s; });
    const champ = (((season || {}).championship || {}).drivers) || {};
    const heads = PG.headline(drivers.metrics, INDEX_PREFS, 5, true);
    const ids = Object.keys(D).sort((a, b) => ((stand[a] || {}).pos || 99) - ((stand[b] || {}).pos || 99) || (D[b].races || 0) - (D[a].races || 0));
    const cols = [{ label: 'Pos', align: 'right' }, { label: 'Driver' }, { label: 'Team' }, { label: 'Races', align: 'right' }, { label: 'Pts', align: 'right' },
      { label: 'Wins', align: 'right' }, { label: 'Pod', align: 'right' }, { label: 'Poles', align: 'right' }]
      .concat(Object.keys(champ).length ? [{ label: 'Title', align: 'right', title: 'Championship probability from the season simulation' }] : [])
      .concat(heads.map(m => ({ label: PG.shortLabel(m.label), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') })))
      .concat([{ label: 'Elo', align: 'right', title: 'Field Elo (data/elo.json current)' }]);
    const curElo = ((elo || {}).current) || {};
    const rows = ids.map(id => {
      const d = D[id], s = stand[id] || {};
      const cells = [
        { v: s.pos || 99, html: s.pos ? String(s.pos) : '—', align: 'right' },
        { v: d.name || PD.driverName(id), html: PD.driverLink(id, { name: d.name, team: d.team }) },
        { v: PD.teamName(d.team), html: PD.teamLink(d.team, { bar: false }) },
        { v: d.races || 0 }, { v: PG.has(s.points) ? s.points : -1, html: PG.has(s.points) ? num(s.points, s.points % 1 ? 1 : 0) : '—' },
        { v: s.wins || 0 }, { v: s.podiums || 0 }, { v: s.poles || 0 }
      ];
      if (Object.keys(champ).length) cells.push({ v: (champ[id] || {}).p_title || 0, html: PG.has((champ[id] || {}).p_title) ? pct(champ[id].p_title) : '—', align: 'right' });
      heads.forEach(m => {
        const v = (d.values || {})[m.key], p = (d.pct || {})[m.key];
        cells.push({ v: isNum(p) ? p : -1, html: '<span class="muted-inline">' + PG.fmt(m, v) + '</span> ' + pctPill(p), align: 'right' });
      });
      const e = (curElo[id] || ((season || {}).elo || {})[id] || {}).elo;
      cells.push({ v: isNum(e) ? e : 0, html: isNum(e) ? num(e, 0) : '—', align: 'right' });
      return { _href: '#/driver/' + id, cells: cells, _q: (d.name || id) + ' ' + PD.teamName(d.team) };
    });
    const tbl = document.getElementById('drv-table');
    tbl.innerHTML = tableHTML(cols, rows, { sticky: true });
    sortable(tbl);
    const trs = Array.prototype.slice.call(tbl.querySelectorAll('tbody tr'));
    const qs = rows.map(r => r._q.toLowerCase());
    document.getElementById('drv-q').addEventListener('input', ev => {
      const q = ev.target.value.trim().toLowerCase();
      trs.forEach((tr, i) => { tr.style.display = !q || qs[i].indexOf(q) >= 0 ? '' : 'none'; });
    });
    if (heads.length) tbl.insertAdjacentHTML('afterend', '<div class="pg-note">Metric columns: ' + heads.map(m => PG.glossLink(m.key, esc(m.label))).join(' · ') + '. The full catalogue of ' + (drivers.metrics || []).length + ' metrics is on each driver page and in the <a href="#/lab">lab</a>.</div>');
    // All-time Elo leaders.
    const top = ((elo || {}).all_time || []).slice(0, 25);
    if (top.length) {
      document.getElementById('drv-elo').innerHTML = card('All-time Elo', 'Peak ratings since 1950 against the field, the teammate and in qualifying; top 25 of ' + ((elo.all_time || []).length) + '.',
        tableHTML([{ label: '#', align: 'right' }, { label: 'Driver' }, { label: 'Years' }, { label: 'Races', align: 'right' }, { label: 'Peak field', align: 'right' }, { label: 'Peak v teammate', align: 'right' }, { label: 'Peak quali', align: 'right' }],
          top.map((x, i) => ({ _href: '#/driver/' + x.driver, cells: [i + 1, { v: x.name, html: PD.driverLink(x.driver, { name: x.name }) }, (x.years || []).join('–'), { v: x.races, align: 'right' },
            { v: x.peak_field, html: num(x.peak_field, 0), align: 'right' }, { v: x.peak_teammate, html: num(x.peak_teammate, 0), align: 'right' }, { v: x.peak_quali, html: num(x.peak_quali, 0), align: 'right' }] })), { compact: true }));
      sortable('drv-elo');
    }
  });
}

// ── driver page ────────────────────────────────────────────────────────────

const RADAR_PREFS = ['race_pace', 'quali_pace', 'quali_gap_tm_pct', 'race_pace_tm_delta', 'overtakes_made', 'lap1_gain', 'tyre_mgmt', 'points_v_expected', /pace/, /overtak/, /gain/];
const STYLE_PREFS = ['brake_earliness', 'corner_speed_delta', 'full_throttle', 'braking_share', 'coasting', 'speed_trap_kph', /brak/, /corner/];

function renderDriver(el, params, state) {
  const id = params.id;
  let y = PG.yearOf(params, state);
  el.innerHTML = muted('Loading ' + esc(PD.driverName(id)) + '…');
  return Promise.all([PG.season(y), PD.load('drivers/' + id + '.json'), PD.load('elo.json')]).then(res => {
    if (!PG.alive(el)) return null;
    let [drivers, teams, season] = res[0];
    const career = res[1], elo = res[2];
    const inSeason = PD.ok(drivers) && drivers.drivers && drivers.drivers[id];
    // Not in the picked season: fall back to the driver's latest season on file.
    if (!inSeason && career && (career.seasons || []).length) {
      const last = career.seasons.slice().sort((a, b) => b.year - a.year)[0].year;
      if (last !== y && last >= 2018) {
        y = last;
        return PG.season(y).then(r2 => { if (!PG.alive(el)) return; drawDriver(el, id, y, r2[0], r2[1], r2[2], career, elo, true); });
      }
    }
    drawDriver(el, id, y, drivers, teams, season, career, elo, false);
    return null;
  });
}

function drawDriver(el, id, y, drivers, teams, season, career, elo, fellBack) {
  const D = (PD.ok(drivers) && drivers.drivers) || {};
  const d = D[id] || null;
  const metrics = (drivers || {}).metrics || [];
  const meta = PG.metaOf(metrics);
  const info = PD.NAMES.drivers[id] || {};
  const name = (d && d.name) || (career && career.name) || PD.driverName(id);
  const team = (d && d.team) || PG.teamOfDriver(season, drivers, id) || info.team;
  const colour = team ? PD.teamColour(team) : C.blue;
  const mates = PG.teammates(season, drivers, id);
  const mate = mates[0] || null;
  const stand = ((((season || {}).standings || {}).drivers) || []).find(s => s.driver === id) || {};
  const ch = ((((season || {}).championship) || {}).drivers || {})[id] || null;
  const age = PG.ageOf(career && career.dob);
  const nat = (career && career.nationality) || info.nationality;
  const number = info.number;

  let h = '<div class="pg-head" style="--team:' + esc(colour) + '"><div class="pg-num">' + (number ? esc(number) : esc(PD.driverCode(id))) + '</div><div class="pg-body"><h2>' + esc(name) + '</h2>' +
    '<div class="pg-sub">' + (team ? PD.teamLink(team) : '') + (nat ? '<span>' + esc(nat) + '</span>' : '') + (age !== null ? '<span>' + (d || ((career || {}).seasons || []).some(z => z.year >= PD.currentSeason() - 1) ? 'age ' + age : 'born ' + String(career.dob).slice(0, 4)) + '</span>' : '') +
    (info.code ? '<span class="chip">' + esc(info.code) + '</span>' : '') + (d ? '<span class="chip">' + y + ' season</span>' : '<span class="chip">no ' + y + ' race</span>') + (fellBack ? '<span class="chip warn">not on the ' + PD.state.year + ' grid: showing ' + y + '</span>' : '') + '</div></div>' +
    '<div class="pg-links">' + (mate ? '<a href="#/compare/drivers/' + esc(id) + '/' + esc(mate) + '">Compare with ' + esc(PD.driverSurname(mate)) + ' →</a>' : '') + '<a href="#/lab">Lab →</a>' + (team ? '<a href="#/team/' + esc(team) + '">Team →</a>' : '') + '</div></div>';

  if (!d) {
    h += card('This season', '', muted(PD.ok(drivers) ? esc(name) + ' has no race in ' + y + '.' : 'The ' + y + ' driver catalogue is not built yet.'));
    h += '<div id="drv-career"></div>';
    el.innerHTML = h;
    drawCareer(id, career, elo, mates);
    return;
  }

  // Tiles.
  const eloNow = (((elo || {}).current || {})[id]) || ((season || {}).elo || {})[id] || {};
  const eff = ((((season || {}).driver_effects) || {}).race || {})[id];
  const qeff = ((((season || {}).driver_effects) || {}).quali || {})[id];
  const tiles = [
    statTile('Championship', stand.pos ? PD.ordinal(stand.pos) : '—', PG.has(stand.points) ? num(stand.points, stand.points % 1 ? 1 : 0) + ' points' : ''),
    statTile('Wins · podiums · poles', (stand.wins || 0) + ' · ' + (stand.podiums || 0) + ' · ' + (stand.poles || 0), d.races + ' race' + (d.races === 1 ? '' : 's')),
    statTile('Title chance', ch ? pct(ch.p_title) : '—', ch ? 'expected ' + num(ch.exp_points, 0) + ' pts (' + num(ch.p05, 0) + '–' + num(ch.p95, 0) + ')' + (ch.clinched ? ' · clinched' : ch.eliminated ? ' · eliminated' : '') : (season && season.championship === null ? 'season finished' : '')),
    statTile('Race pace effect', eff ? signed(eff.effect, 3) + '%' : '—', eff ? '± ' + num(eff.se, 3) + ' · driver share of lap time, negative = faster' : ''),
    statTile('Quali effect', qeff ? signed(qeff.effect, 3) + '%' : '—', qeff ? '± ' + num(qeff.se, 3) : ''),
    statTile('Elo', isNum(eloNow.elo) ? num(eloNow.elo, 0) : '—', isNum(eloNow.elo_teammate) ? 'v teammate ' + num(eloNow.elo_teammate, 0) + ' · quali ' + num(eloNow.elo_quali, 0) : '')
  ];
  h += '<div class="kpi-grid six">' + tiles.join('') + '</div>';

  h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub">The whole catalogue, ' + metrics.length + ' metrics. Field: against every driver this season. Teammate: the same metric ranked only against drivers in the same car, so it shows who beats the machinery.</span>' +
    PG.toggle('drv-pct-src', [['field', 'Field'], ['teammate', 'Teammate']], 'field') + '</div><div id="drv-pct"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Eight headline metrics as field percentiles' + (mate ? ', against ' + esc(PD.driverName(mate)) : '') + '.</span></div><div id="drv-radar" style="height:400px"></div></div>';
  h += '<div class="card"><div class="card-header">Teammate head to head <span class="card-sub" id="drv-h2h-sub"></span></div><div id="drv-h2h"></div></div></div>';
  h += '<div class="card"><div class="card-header">Season evolution <span class="card-sub">Grid and finish by round; the lap-time model\'s pace rank; points against the model\'s pre-race expectation, cumulative.</span></div>' +
    '<div class="grid-3"><div id="drv-evo-pos" style="height:300px"></div><div id="drv-evo-pace" style="height:300px"></div><div id="drv-evo-pts" style="height:300px"></div></div></div>';
  h += '<div class="card"><div class="card-header">Race log <span class="card-sub">Every round this season. Pace is the race-pace effect from the lap-time model (seconds per lap against the field, negative = faster); deg is tyre degradation in s/lap.</span></div><div id="drv-log"></div></div>';
  h += '<div class="card"><div class="card-header">Telemetry style <span class="card-sub">How this driver uses the car, from OpenF1 car data (2023 on): braking earliness, minimum corner speed against the teammate, time on full throttle and coasting. Field percentile on each.</span></div><div id="drv-style"></div></div>';
  h += '<div id="drv-career"></div>';
  el.innerHTML = h;

  // Percentile panel and its toggle.
  const drawPct = src => {
    document.getElementById('drv-pct').innerHTML = PG.pctPanel(metrics, d.values, src === 'teammate' ? d.pct_teammate : d.pct,
      { note: src === 'teammate' ? 'Teammate percentiles: 100 means the best figure among drivers sharing this car this season; with two drivers it is close to 0 or 100.' : 'Field percentile, 100 = best. ↓ marks metrics where lower is better; the bar already accounts for it. Hover a row for its definition.' });
  };
  drawPct('field');
  PG.wireToggle(el, 'drv-pct-src', drawPct);

  // Radar.
  const axes = PG.headline(metrics, RADAR_PREFS, 8, d.pct).map(m => ({ key: m.key, label: PG.shortLabel(m.label) }));
  const mrow = mate && D[mate];
  const [ca, cb] = PG.pairColours(colour, mrow ? PD.teamColour(mrow.team) : C.orange);
  PG.radar('drv-radar', axes, [{ name: name, pct: d.pct, colour: ca }].concat(mrow ? [{ name: mrow.name || PD.driverName(mate), pct: mrow.pct, colour: cb }] : []));

  // Head to head.
  if (mrow) {
    const hh = PG.h2h(d.log, mrow.log);
    const nA = PD.driverSurname(id), nB = PD.driverSurname(mate);
    document.getElementById('drv-h2h-sub').innerHTML = 'against ' + PD.driverLink(mate) + ' in the ' + hh.both + ' rounds they both started' + (mates.length > 1 ? ' (also: ' + mates.slice(1).map(x => PD.driverLink(x)).join(', ') + ')' : '');
    document.getElementById('drv-h2h').innerHTML = '<div class="pg-h2h">' + PG.h2hBar('Qualifying', hh.quali[0], hh.quali[1], ca, cb, nA, nB) + PG.h2hBar('Race (classified ahead, or finished when the other did not)', hh.race[0], hh.race[1], ca, cb, nA, nB) +
      PG.h2hBar('Points in shared rounds', hh.points[0], hh.points[1], ca, cb, nA, nB) + '</div>' +
      tableHTML([{ label: 'Rd', align: 'right' }, { label: 'Race' }, { label: 'Q ' + nA, align: 'right' }, { label: 'Q ' + nB, align: 'right' }, { label: nA, align: 'right' }, { label: nB, align: 'right' }],
        hh.rows.map(p => ({ _href: PD.raceHref(y, p[0].round), cells: [p[0].round, p[0].name || '',
          { v: p[0].quali_pos, html: isNum(p[0].quali_pos) ? (p[0].quali_pos < p[1].quali_pos ? '<strong>' + p[0].quali_pos + '</strong>' : String(p[0].quali_pos)) : '—' },
          { v: p[1].quali_pos, html: isNum(p[1].quali_pos) ? (p[1].quali_pos < p[0].quali_pos ? '<strong>' + p[1].quali_pos + '</strong>' : String(p[1].quali_pos)) : '—' },
          { v: p[0].pos, html: PG.posHTML(p[0].pos, p[0].status) }, { v: p[1].pos, html: PG.posHTML(p[1].pos, p[1].status) }] })), { compact: true });
    sortable('drv-h2h');
  } else document.getElementById('drv-h2h').innerHTML = muted('No teammate in the catalogue this season.');

  // Evolution charts.
  const log = (d.log || []).slice().sort((a, b) => a.round - b.round);
  const xr = log.map(r => r.round);
  const hoverName = log.map(r => r.name || 'Round ' + r.round);
  if (log.length) {
    plot('drv-evo-pos', [
      { type: 'scatter', mode: 'lines+markers', name: 'Grid', x: xr, y: log.map(r => r.grid || null), text: hoverName, line: { color: C.text3, dash: 'dot', width: 1.5 }, marker: { size: 6 }, hovertemplate: '%{text}: grid %{y}<extra></extra>' },
      { type: 'scatter', mode: 'lines+markers', name: 'Finish', x: xr, y: log.map(r => (PG.finished(r.status) ? r.pos : null)), text: hoverName, line: { color: colour, width: 2 }, marker: { size: 7 }, hovertemplate: '%{text}: P%{y}<extra></extra>', connectgaps: false },
      { type: 'scatter', mode: 'markers', name: 'DNF', x: log.filter(r => !PG.finished(r.status)).map(r => r.round), y: log.filter(r => !PG.finished(r.status)).map(() => 22), text: log.filter(r => !PG.finished(r.status)).map(r => (r.name || '') + ': ' + r.status), marker: { symbol: 'x', color: C.red, size: 9 }, hovertemplate: '%{text}<extra></extra>' }
    ], layout({ showlegend: true, legend: { orientation: 'h', y: 1.15, font: { color: C.text2 } }, margin: { l: 40, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: 'Position', autorange: 'reversed', dtick: 5 } }));
    plot('drv-evo-pace', [
      { type: 'scatter', mode: 'lines+markers', name: 'Pace rank', x: xr, y: log.map(r => r.pace_rank || null), text: log.map(r => (r.name || '') + (isNum(r.pace) ? ' · pace ' + signed(r.pace, 3) + ' s/lap' : '')), line: { color: colour, width: 1.5 }, marker: { size: 9, color: log.map(r => (r.pace_rank && r.pace_rank <= 3 ? C.green : r.pace_rank && r.pace_rank <= 10 ? colour : C.text3)) }, hovertemplate: '%{text}: pace rank %{y}<extra></extra>' }
    ], layout({ margin: { l: 40, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: 'Race pace rank (1 = fastest)', autorange: 'reversed', dtick: 2 } }));
    drawPointsChart(y, id, log, colour);
  } else ['drv-evo-pos', 'drv-evo-pace', 'drv-evo-pts'].forEach(k => { document.getElementById(k).innerHTML = muted('No races yet.'); });

  // Race log table.
  document.getElementById('drv-log').innerHTML = log.length ? tableHTML([
    { label: 'Rd', align: 'right' }, { label: 'Race' }, { label: 'Quali', align: 'right' }, { label: 'Grid', align: 'right' }, { label: 'Finish', align: 'right' }, { label: 'Status' },
    { label: 'Gained', align: 'right', title: 'Grid minus finish' }, { label: 'Lap 1', align: 'right', title: 'Places gained on the opening lap' }, { label: 'Overtakes', align: 'right' },
    { label: 'Stops', align: 'right' }, { label: 'Pace', align: 'right', title: 'Race-pace effect, s/lap against the field' }, { label: 'Pace rank', align: 'right' }, { label: 'Deg', align: 'right', title: 's/lap per lap of tyre age' }, { label: 'Pts', align: 'right' }
  ], log.slice().reverse().map(r => ({ _href: PD.raceHref(y, r.round), cells: [
    r.round, { v: r.name || '', html: PD.raceLink(y, r.round, r.name || 'Round ' + r.round) }, { v: r.quali_pos, html: isNum(r.quali_pos) ? String(r.quali_pos) : '—' }, { v: r.grid, html: isNum(r.grid) ? String(r.grid) : '—' },
    { v: PG.finished(r.status) ? r.pos : 99, html: PG.posHTML(r.pos, r.status) }, { v: r.status || '', html: '<span class="muted-inline">' + esc(r.status || '') + '</span>' },
    { v: r.pos_gained, html: PG.deltaHTML(r.pos_gained) }, { v: r.lap1_gain, html: PG.deltaHTML(r.lap1_gain) }, { v: r.overtakes, html: isNum(r.overtakes) ? String(r.overtakes) : '—' },
    { v: r.pit_stops, html: isNum(r.pit_stops) ? String(r.pit_stops) : '—' }, { v: r.pace, html: isNum(r.pace) ? signed(r.pace, 3) : '—' }, { v: r.pace_rank, html: isNum(r.pace_rank) ? String(r.pace_rank) : '—' },
    degCell(r.deg), { v: r.points || 0, html: r.points ? '<strong>' + num(r.points, r.points % 1 ? 1 : 0) + '</strong>' : '0' }
  ] })), { compact: true }) : muted('No races yet.');
  sortable('drv-log');

  // Telemetry style.
  const styleMetrics = metrics.filter(m => /telemetry|style/i.test(m.group || ''));
  const styleList = styleMetrics.length ? styleMetrics : PG.headline(metrics, STYLE_PREFS, 6, d.values).filter(m => STYLE_PREFS.some(re => re.test(m.key)));
  document.getElementById('drv-style').innerHTML = styleList.length ? '<div class="pg-style">' + styleList.map(m => {
    const v = (d.values || {})[m.key], p = (d.pct || {})[m.key], pt = (d.pct_teammate || {})[m.key];
    return statTile(m.label, PG.fmt(m, v) + ' ' + pctPill(p), esc(m.desc || '') + (isNum(pt) ? ' · teammate pct ' + Math.round(pt) : ''));
  }).join('') + '</div>' + '<div class="pg-note">Telemetry metrics come from every timed lap with car data; laps shorter than 80% or longer than 125% of the reference lap are dropped. See <a href="#/methodology">methodology</a> → telemetry processing.</div>'
    : muted('No telemetry-style metrics in the catalogue for ' + y + ' (OpenF1 car data starts in 2023).');

  drawCareer(id, career, elo, mates);
}

/* Degradation per compound ({SOFT: s/lap/lap, ...}) as coloured figures; or a plain number. */
function degCell(deg) {
  if (isNum(deg)) return { v: deg, html: num(deg, 3) };
  if (!deg || typeof deg !== 'object' || !Object.keys(deg).length) return { v: null, html: '—' };
  const ks = Object.keys(deg).filter(k => isNum(deg[k]));
  const mean = ks.length ? ks.reduce((s, k) => s + deg[k], 0) / ks.length : null;
  return { v: mean, html: ks.map(k => '<span title="' + esc(k) + '" style="color:' + PD.compoundColour(k) + '">' + num(deg[k], 3) + '</span>').join(' ') };
}

/* Cumulative points against cumulative expected points: the log's exp_points, else each round's stored forecast. */
function drawPointsChart(y, id, log, colour) {
  const target = document.getElementById('drv-evo-pts');
  if (!target) return;
  target.innerHTML = muted('Loading the forecasts…');
  const fromLog = log.some(r => isNum(r.exp_points));
  (fromLog ? Promise.resolve(log.map(r => ({ forecast: { post_quali: { drivers: (function () { const o = {}; o[id] = { exp_points: r.exp_points }; return o; })() } } }))) : Promise.all(log.map(r => PD.load(y + '/races/' + r.round + '.json')))).then(races => {
    if (!target.isConnected) return;
    target.innerHTML = '';
    let cp = 0, ce = 0, anyExp = false;
    const pts = [], exp = [], expRace = [];
    log.forEach((r, i) => {
      cp += r.points || 0;
      const f = ((races[i] || {}).forecast) || {};
      const sim = f.post_quali || f.pre_quali;
      const e = sim && sim.drivers && sim.drivers[id] ? sim.drivers[id].exp_points : null;
      const sf = fromLog ? null : (races[i] || {}).sprint_forecast;
      const es = sf && sf.drivers && sf.drivers[id] ? sf.drivers[id].exp_points : 0;
      if (isNum(e)) { anyExp = true; ce += e + (es || 0); }
      pts.push(cp); exp.push(isNum(e) ? ce : null); expRace.push(isNum(e) ? e + (es || 0) : null);
    });
    const tr = [{ type: 'scatter', mode: 'lines+markers', name: 'Points', x: log.map(r => r.round), y: pts, text: log.map(r => r.name || ''), line: { color: colour, width: 2 }, hovertemplate: '%{text}: %{y} pts<extra></extra>' }];
    if (anyExp) tr.push({ type: 'scatter', mode: 'lines', name: 'Expected', x: log.map(r => r.round), y: exp, text: expRace.map(v => (isNum(v) ? num(v, 1) : '—')), line: { color: C.text2, width: 1.5, dash: 'dot' }, connectgaps: true, hovertemplate: 'expected %{y:.1f} (this round %{text})<extra></extra>' });
    plot(target, tr, layout({ showlegend: true, legend: { orientation: 'h', y: 1.15, font: { color: C.text2 } }, margin: { l: 45, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: 'Cumulative points', rangemode: 'tozero' } }));
    if (!anyExp) target.insertAdjacentHTML('beforeend', '<div class="pg-note">No stored forecast for these rounds, so only actual points are drawn.</div>');
  });
}

function drawCareer(id, career, elo, mates) {
  const host = document.getElementById('drv-career');
  if (!host) return;
  if (!career || career.ok === false) { host.innerHTML = card('Career', '', PG.notBuilt('The career file', career)); return; }
  const seasons = (career.seasons || []).slice().sort((a, b) => b.year - a.year);
  const tot = career.totals || {};
  const sum = k => seasons.reduce((s, r) => s + (r[k] || 0), 0);
  const titles = seasons.filter(s => s.pos === 1).length;
  let h = '<div class="card"><div class="card-header">Career <span class="card-sub">' + seasons.length + ' season' + (seasons.length === 1 ? '' : 's') + (seasons.length ? ', ' + seasons[seasons.length - 1].year + '–' + seasons[0].year : '') + ' · from Jolpica results since 1950</span></div>' +
    '<div class="kpi-grid six" style="padding:12px 12px 0">' + [
      statTile('Starts', PG.has(tot.races) ? tot.races : sum('races')), statTile('Wins', PG.has(tot.wins) ? tot.wins : sum('wins')), statTile('Podiums', PG.has(tot.podiums) ? tot.podiums : sum('podiums')),
      statTile('Poles', PG.has(tot.poles) ? tot.poles : sum('poles')), statTile('Points', num(PG.has(tot.points) ? tot.points : sum('points'), 0)), statTile('Titles', PG.has(tot.titles) ? tot.titles : titles)
    ].join('') + '</div>' +
    '<div class="pg-split"><div><div class="pct-group-head" style="padding:0 14px">Seasons</div>' + tableHTML([{ label: 'Year' }, { label: 'Team' }, { label: 'Races', align: 'right' }, { label: 'Wins', align: 'right' }, { label: 'Pod', align: 'right' }, { label: 'Poles', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Pos', align: 'right' }],
      seasons.map(s => ({ _href: '#/season/' + s.year, cells: [s.year, { v: PD.teamName(s.team), html: PD.teamLink(s.team) }, s.races, s.wins, s.podiums, s.poles, { v: s.points, html: num(s.points, s.points % 1 ? 1 : 0) }, { v: s.pos || 99, html: s.pos ? (s.pos === 1 ? '<strong style="color:#e3b341">1</strong>' : String(s.pos)) : '—' }] })), { compact: true }) + '</div>' +
    '<div><div id="drv-elo-chart" style="height:340px"></div></div></div>' +
    '<div class="pct-group-head" style="padding:6px 14px 0">Teammates</div><div id="drv-mates"></div></div>';
  host.innerHTML = h;
  sortable(host);
  // Elo line: field and teammate.
  const e = career.elo || [];
  if (e.length) {
    const x = e.map((r, i) => i), lab = e.map(r => r[0] + ' R' + r[1]);
    const ticks = [], tickText = [];
    e.forEach((r, i) => { if (i === 0 || r[0] !== e[i - 1][0]) { ticks.push(i); tickText.push(String(r[0])); } });
    const step = Math.max(1, Math.ceil(ticks.length / 12));
    plot('drv-elo-chart', [
      { type: 'scatter', mode: 'lines', name: 'Field Elo', x: x, y: e.map(r => r[2]), text: lab, line: { color: C.blue, width: 2 }, hovertemplate: '%{text}: %{y:.0f}<extra>field</extra>' },
      { type: 'scatter', mode: 'lines', name: 'Teammate Elo', x: x, y: e.map(r => r[3]), text: lab, line: { color: C.orange, width: 1.5 }, hovertemplate: '%{text}: %{y:.0f}<extra>teammate</extra>' }
    ], layout({ showlegend: true, legend: { orientation: 'h', y: 1.1, font: { color: C.text2 } }, margin: { l: 50, r: 15, t: 30, b: 40 },
      xaxis: { tickvals: ticks.filter((t, i) => i % step === 0), ticktext: tickText.filter((t, i) => i % step === 0), title: 'Race' }, yaxis: { title: 'Elo' } }));
  } else document.getElementById('drv-elo-chart').innerHTML = muted('No Elo history.');
  const tm = (career.teammates || []).slice().sort((a, b) => b.year - a.year);
  const tq = tm.reduce((s, r) => [s[0] + ((r.h2h_quali || [])[0] || 0), s[1] + ((r.h2h_quali || [])[1] || 0)], [0, 0]);
  const trc = tm.reduce((s, r) => [s[0] + ((r.h2h_race || [])[0] || 0), s[1] + ((r.h2h_race || [])[1] || 0)], [0, 0]);
  document.getElementById('drv-mates').innerHTML = tm.length ? tableHTML([{ label: 'Year' }, { label: 'Teammate' }, { label: 'Quali h2h', align: 'right' }, { label: 'Race h2h', align: 'right' }, { label: '', sortable: false }],
    tm.map(r => {
      const q = r.h2h_quali || [0, 0], rc = r.h2h_race || [0, 0];
      return { cells: [r.year, { v: PD.driverName(r.teammate), html: PD.driverLink(r.teammate) }, { v: q[0] - q[1], html: '<strong>' + q[0] + '</strong>–' + q[1] }, { v: rc[0] - rc[1], html: '<strong>' + rc[0] + '</strong>–' + rc[1] },
        { v: '', html: '<a href="#/compare/drivers/' + esc(id) + '/' + esc(r.teammate) + '">compare →</a>' }] };
    }).concat([{ _class: 'total-row', cells: [{ v: 9999, html: '<strong>All</strong>' }, { v: '', html: '' }, { v: 0, html: '<strong>' + tq[0] + '–' + tq[1] + '</strong>' }, { v: 0, html: '<strong>' + trc[0] + '–' + trc[1] + '</strong>' }, ''] }]), { compact: true }) : muted('No teammate record.');
  sortable('drv-mates');
}

PD.route('drivers', renderDrivers);
PD.route('driver', renderDriver);
})(window.PD);
