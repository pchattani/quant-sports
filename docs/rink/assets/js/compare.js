/* The Quant Rink — compare (#/compare/<a>/<b>): two skaters, two goalies or two teams.
 *
 * Side by side on the season catalogue: who wins each metric (by percentile, so lower-is-better metrics
 * count the right way), the largest gaps each way, a radar of the headline metrics and every metric
 * family in full. Players are NHL playerIds; teams are their tri-code, written t:TOR (a bare TOR also
 * works). With one side picked, the other defaults to the most similar. Two skaters from the same pool
 * are compared on position-pool percentiles, a forward with a defenceman on league percentiles.
 *
 * Data: data/<S>/skaters.json, goalies.json and teams.json. Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;
let MODE = 'S';
const TEAM_HEAD = ['overall', 'off', 'def', 'pp', 'pk', 'goalie', 'xgf_pct5', 'cf_pct5', 'xgf_pct', 'cf_pct', 'gf_g', 'ga_g'];
const MODES = [['S', 'Skaters'], ['G', 'Goalies'], ['T', 'Teams']];

function teamId(s) { const m = /^t:?([A-Za-z]{2,3})$/.exec(String(s || '')); return m ? m[1].toUpperCase() : (/^[A-Z]{2,3}$/.test(String(s || '')) ? String(s) : null); }
function entity(id, sk, gk, tc) {
  const k = K();
  const t = teamId(id);
  if (t && tc && tc.teams[t]) { const x = tc.teams[t]; const R = RK.fk.T.ratingsOf(x, null); const U = x.units || {}; return { kind: 'T', id: t, name: k.teamName(t), values: Object.assign({}, U, R, x.values || {}), pct: Object.assign({}, U.pct || {}, RK.fk.T.unitPct(x, null), x.pct || {}), rank: x.rank || {}, team: t, rec: RK.fk.T.recordOf(x, x.record), R: R }; }
  const s = sk && sk.players[String(id)], g = gk && gk.players[String(id)];
  const p = s || g;
  if (!p) return null;
  return { kind: s ? 'S' : 'G', id: String(id), name: p.name || k.name(id), values: p.values || {}, pct: p.pct || {}, pctPos: p.pct_pos || {}, team: p.team, pos: p.pos, group: s ? (p.group || k.groupOf(p.pos)) : 'G', age: p.age, gp: k.gpOf(p), toi: p.toi, qualified: p.qualified };
}
/* The percentiles a side is shown on: position pool when both skaters share it, else the league. */
function pc(X, other) { return X.kind === 'S' && other && other.kind === 'S' && X.group === other.group ? (Object.keys(X.pctPos || {}).length ? X.pctPos : X.pct) : X.pct; }
function metricsFor(A, B, sk, gk, tc) {
  const k = K();
  if (MODE === 'T') { const ms = ((tc && tc.metrics) || []).slice(); if (!ms.length) return RK.fk.T.UNITS.map(u => ({ key: u[0], label: u[1], group: 'Unit ratings', fmt: u[4], lower: u[5], desc: u[3] })).concat([['xgf_pct5', '5v5 xGF%', 'pct', false], ['cf_pct5', '5v5 CF%', 'pct', false], ['xgf_g', 'xGF / game', '2', false], ['xga_g', 'xGA / game', '2', true], ['gf_g', 'Goals for / game', '2', false], ['ga_g', 'Goals against / game', '2', true], ['gsax', 'Goalie GSAx', '1', false]].map(z => ({ key: z[0], label: z[1], group: 'Results and shares', fmt: z[2], lower: z[3] }))); return ms; }
  if (MODE === 'G') return gk ? k.allMetrics(gk) : [];
  const ga = k.metricsFor(sk, A.group), gb = B ? k.metricsFor(sk, B.group) : ga;
  return ga.filter(m => gb.some(x => x.key === m.key));
}

function render(el, params, state) {
  const k = K();
  const a0 = params.a || (params.rest || [])[0] || '', b0 = params.b || (params.rest || [])[1] || '';
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'skaters.json'), k.loadY(S, 'goalies.json'), k.loadY(S, 'teams.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S;
    const sk = k.catOf(o.res[0]), gk = k.catOf(o.res[1]);
    const tc = RK.fk.T ? RK.fk.T.teamsOf(o.res[2]) : null;
    if (sk) k.learnCat(sk);
    if (gk) k.learnCat(gk);
    if (a0 || b0) { const e = entity(a0 || b0, sk, gk, tc); if (e) MODE = e.kind; }
    let A = a0 ? entity(a0, sk, gk, tc) : null, B = b0 ? entity(b0, sk, gk, tc) : null;
    if (A && A.kind !== MODE) A = null;
    if (B && B.kind !== MODE) B = null;
    if (A && !B) { const n = nearest(A, sk, gk, tc); if (n) B = entity(n, sk, gk, tc); }
    const src = MODE === 'T' ? tc : MODE === 'G' ? gk : sk;
    let h = '<div class="card"><div class="card-header">Compare <span class="card-sub">' + k.esc(k.sLabel(S)) + '. Pick two skaters (any positions; the metrics they share are compared), two goalies or two teams.</span><span class="gq-ctl">' + k.toggle('cmp-mode', MODES, MODE) + '</span></div>' +
      '<div class="gq-cmp-pick"><div><span class="gq-dot a"></span><div id="cmp-pa"></div></div><button type="button" class="gq-btn" id="cmp-swap" title="Swap">⇄</button><div><span class="gq-dot b"></span><div id="cmp-pb"></div></div></div></div>';
    if (!src) h += k.card('Compare', '', k.notBuilt('The ' + ({ S: 'skater', G: 'goalie', T: 'team' })[MODE] + ' catalogue', MODE === 'T' ? o.res[2] : MODE === 'G' ? o.res[1] : o.res[0]));
    else if (!A || !B) h += k.card('', '', k.muted('Pick ' + (A ? 'a second ' : 'two ') + ({ S: 'skaters', G: 'goalies', T: 'teams' })[MODE] + ' above.' + (a0 && !A ? ' (' + k.esc(a0) + ' is not in the ' + k.esc(k.sLabel(S)) + ' catalogue.)' : '')));
    else h += body(S, A, B, metricsFor(A, B, sk, gk, tc));
    el.innerHTML = h;
    const tag = x => (MODE === 'T' ? 't:' + x : x);
    const go = (a, b) => { location.hash = k.compareHref(a ? tag(a) : '', b ? tag(b) : '') + k.sq(S); };
    const extra = {};
    if (MODE === 'T' && tc) Object.keys(tc.teams).forEach(t => { extra[t] = { name: k.teamName(t), team: t, pos: 'team' }; });
    else if (MODE === 'G' && gk) Object.keys(gk.players).forEach(id => { const p = gk.players[id]; extra[id] = { name: p.name || k.name(id), team: p.team, pos: 'G' }; });
    else if (sk) Object.keys(sk.players).forEach(id => { const p = sk.players[id]; extra[id] = { name: p.name || k.name(id), team: p.team, pos: k.posLabel(p.pos) }; });
    const pick = (id, val, other, side) => k.picker(document.getElementById(id), { value: val ? val.id : null, label: val ? val.name : '', placeholder: MODE === 'T' ? 'Type a team…' : MODE === 'G' ? 'Type a goalie…' : 'Type a skater…', extra: extra, only: true, min: MODE === 'T' ? 1 : 2,
      onPick: pid => (side === 'a' ? go(pid, other ? other.id : '') : go(other ? other.id : '', pid)) });
    pick('cmp-pa', A, B, 'a'); pick('cmp-pb', B, A, 'b');
    const sw = document.getElementById('cmp-swap');
    if (sw) sw.onclick = () => { if (A || B) go(B ? B.id : '', A ? A.id : ''); };
    k.wireToggle(el, 'cmp-mode', v => { MODE = v; if (location.hash.replace(/\?.*$/, '') === '#/compare') render(el, { query: params.query }, state); else location.hash = '#/compare' + k.sq(S); });
    if (A && B && src) after(S, A, B, metricsFor(A, B, sk, gk, tc));
  });
}

function nearest(A, sk, gk, tc) {
  const k = K();
  if (A.kind === 'T') {
    let best = null, bd = 1e9;
    Object.keys(tc.teams).forEach(t => { if (t === A.id) return; const p = tc.teams[t].pct || {}; let d = 0, n = 0; TEAM_HEAD.forEach(x => { if (k.isNum(A.pct[x]) && k.isNum(p[x])) { d += (A.pct[x] - p[x]) * (A.pct[x] - p[x]); n++; } }); if (n >= 3 && d / n < bd) { bd = d / n; best = t; } });
    return best;
  }
  const cat = A.kind === 'G' ? gk : sk;
  const heads = k.headline(A.kind === 'G' ? k.allMetrics(cat) : k.metricsFor(cat, A.group), k.PREFS[A.kind === 'G' ? 'G' : A.group] || [], 10);
  const mine = A.kind === 'G' ? A.pct : (Object.keys(A.pctPos || {}).length ? A.pctPos : A.pct);
  let best = null, bd = 1e9;
  Object.keys(cat.players).forEach(id => {
    const p = cat.players[id];
    if (id === A.id || p.qualified === false || (A.kind === 'S' && (p.group || k.groupOf(p.pos)) !== A.group)) return;
    const theirs = A.kind === 'G' ? (p.pct || {}) : (p.pct_pos || p.pct || {});
    let d = 0, n = 0;
    heads.forEach(m => { const x = mine[m.key], y = theirs[m.key]; if (k.isNum(x) && k.isNum(y)) { d += (x - y) * (x - y); n++; } });
    if (n >= 3 && d / n < bd) { bd = d / n; best = id; }
  });
  return best;
}

function idCard(S, X, side) {
  const k = K();
  const facts = [];
  const v = X.values;
  if (X.kind === 'S') {
    facts.push(['Team', X.team ? k.teamChip(X.team, S) : '—'], ['Pos', k.esc(k.posLabel(X.pos) || '—')], ['Age', k.isNum(X.age) ? k.num(X.age, 0) : '—'], ['GP', k.int(X.gp)]);
    [['G', ['g', 'goals'], 'int'], ['P', ['pts', 'points'], 'int'], ['xGF%', ['xgf_pct'], 'pct'], ['Value', ['value', 'gar', 'war'], 'signed1']].forEach(z => { const key = k.pick(v, z[1]); if (key) facts.push([z[0], k.fmtV(v[key], z[2])]); });
  } else if (X.kind === 'G') {
    facts.push(['Team', X.team ? k.teamChip(X.team, S) : '—'], ['Age', k.isNum(X.age) ? k.num(X.age, 0) : '—'], ['GP', k.int(X.gp)]);
    [['Sv%', ['sv_pct', 'save_pct'], 'svpct'], ['GSAx', ['gsax'], 'signed1'], ['GSAx/60', ['gsax60'], 'signed'], ['Shots', ['shots_faced', 'sa'], 'int']].forEach(z => { const key = k.pick(v, z[1]); if (key) facts.push([z[0], k.fmtV(v[key], z[2])]); });
  } else {
    const rc = X.rec || {};
    facts.push(['W–L–OTL', RK.fk.T.recText(rc)], ['Pts', k.int(rc.pts)], ['GD', k.isNum(rc.diff) ? k.signed(rc.diff, 0) : '—'], ['Rating', k.isNum(X.R.overall) ? k.signed(X.R.overall, 2) : '—'], ['5v5 xGF/60', k.isNum(X.R.off) ? k.num(X.R.off, 2) : '—'], ['5v5 xGA/60', k.isNum(X.R.def) ? k.num(X.R.def, 2) : '—']);
  }
  const href = X.kind === 'T' ? k.teamHref(X.id, S) : k.playerHref(X.id, S);
  return '<div class="gq-cmp-id ' + side + '"><div class="gq-cmp-name"><a href="' + href + '">' + k.esc(X.name) + '</a>' + (X.qualified === false ? ' <span class="gq-tag">small sample</span>' : '') + '</div><div class="gq-cmp-facts">' +
    facts.map(f => '<div class="gq-fact"><span>' + k.esc(f[0]) + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div>';
}

function body(S, A, B, metrics) {
  const k = K();
  const pa = pc(A, B), pb = pc(B, A);
  const ms = metrics.filter(m => k.isNum(pa[m.key]) && k.isNum(pb[m.key]));
  let wa = 0, wb = 0;
  const gaps = ms.map(m => { const d = pa[m.key] - pb[m.key]; if (d > 0.5) wa++; else if (d < -0.5) wb++; return { m: m, d: d }; });
  const tot = Math.max(1, wa + wb);
  const ga = gaps.filter(g => g.d > 0).sort((x, y) => y.d - x.d).slice(0, 3), gb = gaps.filter(g => g.d < 0).sort((x, y) => x.d - y.d).slice(0, 3);
  const gl = list => list.map(g => '<strong>' + k.esc(g.m.label) + '</strong> (' + Math.round(Math.abs(g.d)) + ' pts)').join(', ') || 'nothing by much';
  let h = '<div class="gq-cmp-ids">' + idCard(S, A, 'a') + idCard(S, B, 'b') + '</div>';
  h += '<div class="card"><div class="gq-cmp-verdict"><div class="gq-cmp-side">' + k.esc(A.name) + ' is ahead on ' + gl(ga) + '.</div><div class="gq-cmp-mid"><div class="gq-cmp-score"><span class="a">' + wa + '</span><span class="dash">–</span><span class="b">' + wb + '</span></div>' +
    '<div class="gq-cmp-bar"><span class="a" style="width:' + (100 * wa / tot).toFixed(1) + '%"></span><span class="b" style="width:' + (100 * wb / tot).toFixed(1) + '%"></span></div><div class="gq-cmp-sub">metrics won by percentile, of ' + ms.length + (wa + wb < ms.length ? ' (' + (ms.length - wa - wb) + ' level)' : '') + '</div></div>' +
    '<div class="gq-cmp-side b">' + k.esc(B.name) + ' is ahead on ' + gl(gb) + '.</div></div>' +
    (A.kind === 'S' && A.group !== B.group ? '<div class="pg-note gq-note">A forward against a defenceman: percentiles are against the whole league here, not each player\'s position pool, and only the metrics both pools carry are compared.</div>' : '') +
    (!ms.length ? '<div class="pg-note gq-note">No shared percentiles: one side is below the sample floor, or the catalogue has none yet. Values are still listed below.</div>' : '') + '</div>';
  h += '<div class="card"><div class="card-header">Profile <span class="card-sub">Headline metrics as percentiles (100 = best).</span></div><div id="cmp-radar" class="gf-radar"></div></div>';
  h += '<div class="card"><div class="card-header">Every metric <span class="card-sub">Value and percentile for each side; the bar shows the percentile gap (red: ' + k.esc(A.kind === 'T' ? A.id : k.surname(A.name)) + ', blue: ' + k.esc(B.kind === 'T' ? B.id : k.surname(B.name)) + ').</span></div><div id="cmp-all"></div></div>';
  return h;
}

function after(S, A, B, metrics) {
  const k = K();
  const pa = pc(A, B), pb = pc(B, A);
  const heads = (A.kind === 'T' ? TEAM_HEAD.map(x => metrics.find(m => m.key === x)).filter(Boolean).concat(metrics) : k.headline(metrics, k.PREFS[A.kind === 'G' ? 'G' : A.group] || [], 10))
    .filter((m, i, arr) => arr.indexOf(m) === i && (k.isNum(pa[m.key]) || k.isNum(pb[m.key]))).slice(0, 10);
  const node = document.getElementById('cmp-radar');
  if (node && heads.length >= 3) {
    const narrow = k.narrow(node);
    const wrap = s => (narrow && s.length > 12 ? s.replace(/^(.{6,14}?)\s+/, '$1<br>') : s);
    const th = heads.map(m => wrap(m.label));
    const shell = k.chart('radar');
    const ser = [{ name: A.name, values: heads.map(m => (k.isNum(pa[m.key]) ? pa[m.key] : 0)), colour: k.CA }, { name: B.name, values: heads.map(m => (k.isNum(pb[m.key]) ? pb[m.key] : 0)), colour: k.CB }];
    let done = false;
    if (shell) { try { shell(node, ser, { labels: th, height: narrow ? 340 : 420 }); done = true; } catch (e) { console.warn('radar', e); } }
    if (!done) k.plot(node, ser.map(x => ({ type: 'scatterpolar', fill: 'toself', name: x.name, r: x.values.concat([x.values[0]]), theta: th.concat([th[0]]),
      line: { color: x.colour, width: 2 }, fillcolor: k.alpha(x.colour, 0.16), hovertemplate: '%{theta}: %{r:.0f}th percentile<extra>' + k.esc(x.name) + '</extra>' })),
      k.layout({ showlegend: true, legend: { orientation: 'h', y: -0.1, font: { color: k.C.text2 } }, polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 100], gridcolor: '#21262d', tickfont: { size: 9 }, tickvals: [25, 50, 75, 100] }, angularaxis: { gridcolor: '#21262d', tickfont: { size: narrow ? 8 : 10 } } },
        margin: narrow ? { l: 46, r: 46, t: 24, b: 40 } : { l: 80, r: 80, t: 24, b: 40 } }));
  } else if (node) k.empty(node, 'Not enough shared percentiles for a profile.');
  const host = document.getElementById('cmp-all');
  if (!host) return;
  host.innerHTML = k.groups(metrics).map(g => {
    const items = g.items.filter(m => k.isNum(A.values[m.key]) || k.isNum(B.values[m.key]));
    if (!items.length) return '';
    return '<div class="gq-sub-head">' + k.esc(g.name) + '</div>' + items.map(m => {
      const xa = pa[m.key], xb = pb[m.key];
      const d = k.isNum(xa) && k.isNum(xb) ? xa - xb : null;
      const w = k.isNum(d) ? Math.min(50, Math.abs(d) / 2) : 0;
      const ra = (A.rank || {})[m.key], rb = (B.rank || {})[m.key];
      const tagA = k.isNum(xa) ? k.pill(xa) : (k.isNum(ra) ? '<span class="gf-rank">#' + ra + '</span>' : k.pill(xa)), tagB = k.isNum(xb) ? k.pill(xb) : (k.isNum(rb) ? '<span class="gf-rank">#' + rb + '</span>' : k.pill(xb));
      const better = !k.isNum(d) && k.isNum(A.values[m.key]) && k.isNum(B.values[m.key]) ? (A.values[m.key] - B.values[m.key]) * (m.lower ? -1 : 1) : d;
      return '<div class="gq-cmp-row" title="' + k.esc(k.cleanDesc(m.desc || '')) + '"><span class="gq-cmp-v' + (k.isNum(better) && better > 0.5 * (k.isNum(d) ? 1 : 0) && better > 0 ? ' win' : '') + '">' + k.fmt(m, A.values[m.key]) + ' ' + tagA + '</span>' +
        '<span class="gq-cmp-lab">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '<span class="gq-gap">' + (k.isNum(d) ? '<i class="' + (d > 0 ? 'a' : 'b') + '" style="width:' + w.toFixed(1) + '%"></i>' : '') + '</span></span>' +
        '<span class="gq-cmp-v b' + (k.isNum(better) && better < 0 ? ' win' : '') + '">' + tagB + ' ' + k.fmt(m, B.values[m.key]) + '</span></div>';
    }).join('');
  }).join('') || k.muted('No shared metrics.');
}

if (typeof RK.route === 'function') { try { RK.route('compare', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
