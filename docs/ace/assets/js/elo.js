/* The Quant Ace — Elo leaderboards (#/<T>/elo).
 *
 * Current Elo by surface (sortable, any surface as the ranking), the all-time peaks since 2000
 * (ATP) or 2007 (WTA) by surface, and Elo lines for any chosen players. ?p=pid,pid,... in the
 * address picks the players on the chart.
 *
 * Data: data/<T>/elo.json {"current": {pid: {all, hard, clay, grass, n, rank}}, "peaks": {all|surface:
 * [[pid, elo, date]]}, "history": {pid: [[date, all, surface_of_match]]}} (top 100 only); players
 * outside it and the surface lines come from data/<T>/players/<pid>.json "elo" [[date, all, hard,
 * clay, grass]]. Uses TA.fk from players.js. */
(function (TA) {
'use strict';

const K = () => TA.fk;
let ES = { sort: 'all', show: 50, peak: 'all', line: 'all', picks: null, win: 'all' };

function render(el, params, state) {
  const k = K(), T = k.T(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">' + k.TN(T) + ' Elo <span class="card-sub" id="el-sub">Loading…</span>' +
    '<span class="pg-ctl">rank by ' + k.toggle('el-sort', [['all', 'Overall'], ['hard', 'Hard'], ['clay', 'Clay'], ['grass', 'Grass']], ES.sort) + '</span></div>' +
    '<div class="af-elo-top" id="el-top"></div><div id="el-table">' + k.muted('Loading…') + '</div>' +
    '<div class="pg-note" id="el-note"></div></div>' +
    '<div class="card"><div class="card-header">Elo over time <span class="card-sub">Pick up to eight players; the line follows every match they played.</span>' +
    k.toggle('el-line', [['all', 'Overall'], ['hard', 'Hard'], ['clay', 'Clay'], ['grass', 'Grass']], ES.line) + '</div>' +
    '<div class="lab-controls af-controls"><label>Add a player<span id="el-pick"></span></label><label>Window<select id="el-win"><option value="all">Everything on file</option><option value="5">Last 5 years</option><option value="2">Last 2 years</option><option value="1">Last year</option></select></label>' +
    '<label>&nbsp;<button type="button" id="el-reset">Top 5 now</button></label></div><div id="el-chips" class="af-chips"></div><div id="el-chart" style="height:440px"></div><div class="pg-note" id="el-chart-note"></div></div>' +
    '<div class="card"><div class="card-header">All-time peaks <span class="card-sub" id="el-peak-sub"></span>' + k.toggle('el-peak', [['all', 'Overall'], ['hard', 'Hard'], ['clay', 'Clay'], ['grass', 'Grass']], ES.peak) + '</div><div id="el-peaks"></div></div>';
  return k.ready().then(() => Promise.all([TA.load(T + '/elo.json'), k.loadNames(T)])).then(res => {
    if (!k.alive(el)) return;
    const E = res[0];
    if (!k.ok(E) || !E.current) { document.getElementById('el-table').innerHTML = k.notBuilt('The ' + k.TN(T) + ' Elo file', E); document.getElementById('el-sub').textContent = ''; return; }
    const q = (params.query || {}).p;
    if (q) ES.picks = String(q).split(',').filter(Boolean).slice(0, 8);
    else if (!ES.picks || ES.picksT !== T) ES.picks = null;
    ES.picksT = T;
    drawTable(T, E);
    k.wireToggle(el, 'el-sort', v => { ES.sort = v; drawTable(T, E); });
    drawPeaks(T, E);
    k.wireToggle(el, 'el-peak', v => { ES.peak = v; drawPeaks(T, E); });
    // Lines.
    const cur = E.current;
    const top = Object.keys(cur).sort((a, b) => (cur[b].all || 0) - (cur[a].all || 0));
    if (!ES.picks) ES.picks = top.slice(0, 5);
    k.picker(document.getElementById('el-pick'), { T: T, placeholder: 'Type a name…', onPick: pid => { if (ES.picks.indexOf(pid) < 0) { ES.picks.push(pid); if (ES.picks.length > 8) ES.picks.shift(); } drawLines(T, E); } });
    document.getElementById('el-win').value = ES.win;
    document.getElementById('el-win').onchange = e => { ES.win = e.target.value; drawLines(T, E); };
    document.getElementById('el-reset').onclick = () => { ES.picks = top.slice(0, 5); drawLines(T, E); };
    k.wireToggle(el, 'el-line', v => { ES.line = v; drawLines(T, E); });
    document.getElementById('el-chips').addEventListener('click', ev => {
      const b = ev.target.closest('button[data-pid]');
      if (!b) return;
      ES.picks = ES.picks.filter(x => x !== b.dataset.pid);
      drawLines(T, E);
    });
    drawLines(T, E);
  });
}

function drawTable(T, E) {
  const k = K(), cur = E.current, s = ES.sort;
  const ids = Object.keys(cur).filter(id => k.isNum(cur[id][s]));
  ids.sort((a, b) => cur[b][s] - cur[a][s]);
  const shown = ids.slice(0, ES.show);
  const top = document.getElementById('el-top');
  // A podium strip: the top three on the chosen surface.
  top.innerHTML = ids.slice(0, 3).map((id, i) => '<a class="af-podium" href="' + k.playerHref(T, id) + '" style="--sc:' + k.surfColour(s) + '"><span class="af-pod-rk">' + (i + 1) + '</span><span class="af-pod-n">' + k.esc(k.name(T, id)) + '</span><span class="af-pod-v">' + k.num(cur[id][s], 0) + '</span></a>').join('');
  const best = {};
  ['all', 'hard', 'clay', 'grass'].forEach(x => { best[x] = Math.max.apply(null, ids.map(id => cur[id][x]).filter(k.isNum)); });
  const cell = (id, x) => {
    const v = cur[id][x];
    return { v: v, html: k.isNum(v) ? '<span class="af-elo-v' + (x === s ? ' on' : '') + '"' + (x !== 'all' ? ' style="color:' + k.surfColour(x) + '"' : '') + '>' + k.num(v, 0) + '</span>' : '—', align: 'right' };
  };
  const rows = shown.map((id, i) => {
    const c = cur[id];
    const spec = ['hard', 'clay', 'grass'].filter(x => k.isNum(c[x])).sort((a, b) => c[b] - c[a])[0];
    const gap = spec && k.isNum(c.all) ? c[spec] - c.all : null;
    return { _href: k.playerHref(T, id), cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: k.name(T, id), html: k.playerLink(T, id) }, { v: k.country(T, id), html: k.ctry(k.country(T, id)) },
      cell(id, 'all'), cell(id, 'hard'), cell(id, 'clay'), cell(id, 'grass'),
      { v: spec || '', html: spec ? k.surfChip(spec) + ' <span class="muted-inline">' + k.signed(gap, 0) + '</span>' : '—' },
      { v: c.n, html: k.int(c.n), align: 'right' }, { v: k.isNum(c.rank) ? c.rank : 9999, html: k.isNum(c.rank) ? String(c.rank) : '—', align: 'right' },
      { v: k.isNum((k.NAMES[T][id] || {}).rank) ? k.NAMES[T][id].rank : 9999, html: k.isNum((k.NAMES[T][id] || {}).rank) ? String(k.NAMES[T][id].rank) : '—', align: 'right' }
    ] };
  });
  const host = document.getElementById('el-table');
  host.innerHTML = k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Ctry' }, { label: 'Overall', align: 'right' }, { label: 'Hard', align: 'right' }, { label: 'Clay', align: 'right' }, { label: 'Grass', align: 'right' },
    { label: 'Best surface', title: 'The surface with the highest rating, and how far it sits above the overall one' }, { label: 'Matches', align: 'right', title: 'Matches rated (all levels, including qualifying and Challengers)' },
    { label: 'Elo rank', align: 'right', title: 'Rank by overall Elo' }, { label: 'ATP/WTA rank', align: 'right', title: 'Latest official ranking' }], rows, { compact: true, sticky: true }) +
    (ids.length > ES.show ? '<div class="pg-note"><button type="button" class="af-more" id="el-more">Show all ' + ids.length + '</button></div>' : '');
  k.sortable(host);
  const more = document.getElementById('el-more');
  if (more) more.onclick = () => { ES.show = 100000; drawTable(T, E); };
  document.getElementById('el-sub').textContent = ids.length + ' active players rated · ranked by ' + (s === 'all' ? 'overall' : s) + ' Elo; click a header to sort';
  document.getElementById('el-note').innerHTML = 'Every match from qualifying up moves the ratings; a player\'s surface Elo moves only on that surface. A match is priced on a blend of the two, ' +
    'w × surface + (1 − w) × overall, with w fitted (0.46 for the ATP; the WTA uses the code default 0.5 until its own fit is committed). 1500 is the long-run mean of everyone rated, so a top-100 player sits far above it. ' +
    'After 60 days out a rating decays towards 1500. Details in the <a href="#/methodology/elo">methodology</a>.';
}

function drawPeaks(T, E) {
  const k = K(), s = ES.peak, list = ((E.peaks || {})[s] || []).filter(r => Array.isArray(r));
  const host = document.getElementById('el-peaks');
  const sub = document.getElementById('el-peak-sub');
  sub.textContent = 'The highest ' + (s === 'all' ? 'overall' : s) + ' Elo each player reached, since ' + k.FIRST_YEAR[T] + ' (the first year of ' + k.TN(T) + ' results on file).';
  if (!list.length) { host.innerHTML = k.muted('No peak table in the Elo file.'); return; }
  const cur = E.current || {};
  host.innerHTML = k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Peak', align: 'right' }, { label: 'Date', align: 'right' }, { label: 'Now', align: 'right' }, { label: 'Off the peak', align: 'right' }],
    list.map((r, i) => {
      const now = (cur[r[0]] || {})[s];
      return { _href: k.playerHref(T, r[0]), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: k.name(T, r[0]), html: k.playerLink(T, r[0]) + ' ' + k.ctry(k.country(T, r[0])) },
        { v: r[1], html: '<strong>' + k.num(r[1], 0) + '</strong>' }, { v: r[2], html: k.esc(k.fmtDate(r[2], { weekday: false })) },
        { v: now, html: k.isNum(now) ? k.num(now, 0) : '<span class="muted-inline">inactive</span>' }, { v: k.isNum(now) ? now - r[1] : null, html: k.isNum(now) ? k.signed(now - r[1], 0) : '—' }] };
    }), { compact: true });
  k.sortable(host);
}

/* Lines: overall from elo.json history (or the career file), surfaces from the career file. */
function drawLines(T, E) {
  const k = K();
  const node = document.getElementById('el-chart');
  if (!node) return;
  const picks = ES.picks.slice();
  document.getElementById('el-chips').innerHTML = picks.map((pid, i) => '<span class="af-chip" style="--pc:' + k.PALETTE[i % k.PALETTE.length] + '"><a href="' + k.playerHref(T, pid) + '">' + k.esc(k.name(T, pid)) + '</a><button type="button" data-pid="' + k.esc(pid) + '" title="Remove">×</button></span>').join('');
  const hist = E.history || {};
  const surf = ES.line;
  const need = picks.filter(pid => surf !== 'all' || !(hist[pid] || []).length);
  node.innerHTML = k.muted('Loading…');
  Promise.all(need.map(pid => TA.load(T + '/players/' + pid + '.json'))).then(cs => {
    if (!node.isConnected) return;
    const careers = {};
    need.forEach((pid, i) => { careers[pid] = cs[i]; });
    const col = { all: 1, hard: 2, clay: 3, grass: 4 }[surf];
    const cut = ES.win === 'all' ? '' : (() => { const d = new Date(); d.setFullYear(d.getFullYear() - Number(ES.win)); return d.toISOString().slice(0, 10); })();
    const missing = [];
    const traces = [];
    picks.forEach((pid, i) => {
      let rows;
      const c = careers[pid];
      if (surf === 'all' && (hist[pid] || []).length) rows = hist[pid].map(r => [r[0], r[1], r[2]]);
      else if (c && k.ok(c) && (c.elo || []).length) rows = c.elo.map(r => [r[0], r[col], null]);
      else { missing.push(pid); return; }
      rows = rows.filter(r => k.isNum(r[1]) && String(r[0]) >= cut);
      if (!rows.length) { missing.push(pid); return; }
      traces.push({ type: 'scatter', mode: 'lines', name: k.name(T, pid), x: rows.map(r => r[0]), y: rows.map(r => r[1]), line: { color: k.PALETTE[i % k.PALETTE.length], width: 2, shape: 'hv' },
        text: rows.map(r => (r[2] ? r[2] : '')), hovertemplate: '%{x}: %{y:.0f}' + (surf === 'all' ? ' (%{text})' : '') + '<extra>' + k.esc(k.surname(k.name(T, pid))) + '</extra>' });
    });
    if (!traces.length) { node.innerHTML = k.muted('No Elo history for these players.'); return; }
    k.plot(node, traces, k.layout(Object.assign(k.legendTop(), { margin: { l: 50, r: 10, t: 36, b: 36 }, xaxis: { type: 'date' }, yaxis: { title: (surf === 'all' ? 'Overall' : k.SURF_LABEL[surf]) + ' Elo' } })));
    document.getElementById('el-chart-note').innerHTML = (surf === 'all' ? 'Overall Elo after each match; hover shows the surface the match was on. ' : k.SURF_LABEL[surf] + ' Elo from the career files (it moves only on ' + surf + ' matches, so it is flat between them). ') +
      (missing.length ? 'No history on file for ' + missing.map(p => k.esc(k.name(T, p))).join(', ') + '. ' : '') + 'Click a name above the chart to remove it.';
  });
}

if (typeof TA.route === 'function') TA.route('elo', render);
})(window.TA || (window.TA = {}));
