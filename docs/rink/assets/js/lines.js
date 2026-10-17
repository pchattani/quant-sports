/* The Quant Rink — lines (#/lines): every forward line and defence pair in the league with its 5-on-5
 * time together and on-ice expected-goals share, raw and shrunk.
 *
 * A line's raw xGF% over a few dozen minutes is mostly noise, so the headline share is shrunk towards
 * the team's 5-on-5 share by the time together (see the methodology): the table sorts by the shrunk
 * share, and the chart shows how far each line moved.
 *
 * Address: #/lines?kind=F|D&team=<abbr> (&s=<season>).
 * Data: data/<S>/lines.json ({"forwards", "pairs"} as lists or {cols, rows}; each row {players: [pid...],
 * team, toi, xgf_pct, xgf_pct_shrunk, gf, ga, ...}), falling back to teams.json "lines". Uses RK.fk
 * (and RK.fk.lineRows / lineTable from team.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const ST = { kind: 'F', team: '', min: 0, q: '', season: null };

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  if (/^(F|D)$/i.test(qy.kind || qy.k || '')) ST.kind = String(qy.kind || qy.k).toUpperCase();
  if (qy.team) ST.team = String(qy.team).toUpperCase();
  el.innerHTML = '<div class="card"><div class="card-header">Lines <span class="card-sub" id="ln-sub">Loading…</span><span class="gq-ctl">' + k.toggle('ln-kind', [['F', 'Forward lines'], ['D', 'Defence pairs']], ST.kind) + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Team<select id="ln-team"><option value="">All teams</option></select></label>' +
    '<label><span>Min TOI together <span id="ln-min-v"></span> min</span><input id="ln-min" type="range" min="0" max="600" step="5"></label>' +
    '<label>Player<input id="ln-q" class="gq-search" type="search" placeholder="any player on the unit…"></label></div>' +
    '<div id="ln-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="ln-note"></div></div>' +
    '<div class="card"><div class="card-header">Time together against results <span class="card-sub">Each unit\'s 5-on-5 minutes and its xGF%: hollow at the raw share, filled at the shrunk one, joined by a line. Short-lived units move furthest. Click a unit for its first player.</span></div><div id="ln-chart" class="gf-chart-lg"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'lines.json'), k.loadY(S, 'teams.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, $ = k.$, d = o.res[0];
    if (ST.season !== S) { ST.season = S; }
    const lr = k.lineRows;
    if (typeof lr !== 'function') { $('ln-table').innerHTML = k.muted('The page script for teams did not load.'); return; }
    let F = [], D = [];
    if (d && d.ok !== false) {
      // the lines model (B's lines.py, under "model") carries the shrunk shares; the build's own combos are the fallback
      const kinds = d.model && d.model.ok !== false && ((d.model.forwards || []).length || (d.model.pairs || []).length) ? d.model : (d.kinds || d);
      F = lr(kinds.forwards || kinds.lines || kinds.f || kinds.fwd);
      D = lr(kinds.pairs || kinds.defence || kinds.defense || kinds.d);
      if (!F.length && !D.length) { const all = lr(d.units || d.rows ? d : null); F = all.filter(r => /^f/i.test(r.kind) || r.ids.length === 3); D = all.filter(r => /^d|pair/i.test(r.kind) || r.ids.length === 2); }
    }
    if (!F.length && !D.length) {
      const tc = RK.fk.T ? RK.fk.T.teamsOf(o.res[1]) : null;
      if (tc) Object.keys(tc.teams).forEach(t => { const L = tc.teams[t].lines || {}; lr(L.forwards || L.f || L.lines).forEach(r => { r.team = r.team || t; F.push(r); }); lr(L.pairs || L.d || L.defence).forEach(r => { r.team = r.team || t; D.push(r); }); });
    }
    if (!F.length && !D.length) { $('ln-table').innerHTML = k.notBuilt('The ' + k.sLabel(S) + ' lines file', d); $('ln-sub').textContent = ''; k.empty('ln-chart', ''); return; }
    const teams = Array.from(new Set(F.concat(D).map(r => r.team).filter(Boolean))).sort();
    $('ln-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + k.esc(t + ' · ' + k.teamName(t)) + '</option>').join('');
    const maxT = Math.max.apply(null, F.concat(D).map(r => r.toi || 0).concat([60]));
    $('ln-min').max = String(Math.ceil(maxT / 10) * 10);
    if (ST.min > maxT) ST.min = 0;
    $('ln-min').value = ST.min; $('ln-min-v').textContent = ST.min; $('ln-q').value = ST.q;
    const ctx = { S: S, F: F, D: D, d: d || {} };
    const draw = () => drawLines(ctx);
    k.wireToggle(el, 'ln-kind', v => { ST.kind = v; draw(); });
    $('ln-team').onchange = e => { ST.team = e.target.value; draw(); };
    $('ln-min').oninput = e => { ST.min = Number(e.target.value); $('ln-min-v').textContent = ST.min; };
    $('ln-min').onchange = draw;
    let t = null;
    $('ln-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 200); };
    draw();
  });
}

function drawLines(ctx) {
  const k = K(), S = ctx.S;
  const q = k.fold(ST.q.trim());
  const src = ST.kind === 'D' ? ctx.D : ctx.F;
  const rows = src.filter(r => (!ST.team || r.team === ST.team) && (r.toi || 0) >= ST.min && (!q || r.ids.some((id, i) => k.fold((r.names && r.names[i]) || k.name(id)).indexOf(q) >= 0)));
  rows.sort((a, b) => (k.isNum(b.xgf) ? b.xgf : (k.isNum(b.raw) ? b.raw : -1)) - (k.isNum(a.xgf) ? a.xgf : (k.isNum(a.raw) ? a.raw : -1)) || (b.toi || 0) - (a.toi || 0));
  const host = k.$('ln-table');
  host.innerHTML = rows.length ? k.lineTable(rows.slice(0, 300), S, { label: ST.kind === 'D' ? 'Pair' : 'Line', team: !ST.team }) : k.muted('No unit matches these filters.');
  k.sortable(host);
  k.set('ln-sub', rows.length + ' of ' + src.length + ' ' + (ST.kind === 'D' ? 'pairs' : 'lines') + ' · ' + k.sLabel(S) + ' · ' + ST.min + '+ minutes together · sorted by shrunk xGF%' + (rows.length > 300 ? ' (first 300)' : ''));
  const M = ctx.d.model && ctx.d.model.ok !== false ? ctx.d.model : null;
  const m = M ? k.first(M.pseudo_xg) : null;
  const hasShrunk = src.some(r => k.isNum(r.xgf));
  k.set('ln-note', 'Units are the exact sets of ' + (ST.kind === 'D' ? 'two defencemen' : 'three forwards') + ' on the ice together at 5 on 5 (a side with three forwards and two defencemen), from the NHL\'s shift charts (2010–11 on); units under ' + k.int(k.first((M || {}).min_toi, ctx.d.min_toi, 20)) + ' minutes are left out. ' +
    (hasShrunk ? 'Shrunk xGF% = (xGF + m·p) / (xGF + xGA + m), with p the team\'s 5-on-5 xGF% and m the pseudo-expected-goals of the xGF% stabilisation constant' + (k.isNum(m) ? ' (m = ' + k.num(m, 1) + ' xG this season)' : '') + ': a unit stays near its team\'s share until its own sample of chances is comparable with m. ' : 'The shrunk share is not in this build yet, so the table sorts by the raw share. ') +
    'Raw shares over a few dozen minutes swing on a handful of chances, so read the shrunk column first.');
  chart(rows.slice(0, 250), S);
}

function chart(rows, S) {
  const k = K(), node = k.$('ln-chart');
  if (!node) return;
  const pts = rows.filter(r => k.isNum(r.toi) && (k.isNum(r.xgf) || k.isNum(r.raw)));
  if (pts.length < 2) { k.empty(node, 'Too few units for a chart.'); return; }
  const lbl = r => r.ids.map((id, i) => k.surname((r.names && r.names[i]) || k.name(id))).join('–');
  const segX = [], segY = [];
  pts.forEach(r => { if (k.isNum(r.raw) && k.isNum(r.xgf)) { segX.push(r.toi, r.toi, null); segY.push(r.raw, r.xgf, null); } });
  const tr = [{ type: 'scatter', mode: 'lines', x: segX, y: segY, line: { color: 'rgba(139,148,158,0.35)', width: 1 }, hoverinfo: 'skip', showlegend: false }];
  if (pts.some(r => k.isNum(r.raw))) tr.push({ type: 'scatter', mode: 'markers', name: 'Raw', x: pts.map(r => r.toi), y: pts.map(r => r.raw), marker: { size: 7, color: 'rgba(0,0,0,0)', line: { color: pts.map(r => k.teamColour(r.team)), width: 1.2 } }, text: pts.map(r => k.esc(lbl(r)) + ' (' + k.esc(r.team || '') + ')'), hovertemplate: '%{text}<br>%{x:.0f} min · raw xGF% %{y:.1%}<extra></extra>' });
  tr.push({ type: 'scatter', mode: 'markers', name: 'Shrunk', x: pts.map(r => r.toi), y: pts.map(r => (k.isNum(r.xgf) ? r.xgf : r.raw)), customdata: pts.map(r => k.playerHref(r.ids[0], S)), marker: { size: 9, color: pts.map(r => k.teamColour(r.team)), line: { color: '#0d1117', width: 1 } },
    text: pts.map(r => k.esc(lbl(r)) + ' (' + k.esc(r.team || '') + ')'), hovertemplate: '%{text}<br>%{x:.0f} min · shrunk xGF% %{y:.1%}<extra></extra>' });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 56, r: 12, t: 30, b: 46 }, xaxis: { title: 'Minutes together at 5 on 5', type: 'log' }, yaxis: { title: 'xGF%', tickformat: '.0%' },
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#6e7681', dash: 'dot', width: 1 } }] }, k.legendTop())));
  k.clickThrough(node);
}

if (typeof RK.route === 'function') { try { RK.route('lines', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
