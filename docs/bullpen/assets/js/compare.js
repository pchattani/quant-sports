/* The Quant Bullpen — compare (#/compare/<a>/<b>): two hitters, two pitchers or two teams.
 *
 * Side by side on the season catalogue: who wins each metric (by percentile, so lower-is-better
 * metrics count the right way), the largest gaps each way, a radar of the headline metrics and
 * every metric group in full. Players are MLBAM ids; teams are written t<tid> (t147), or a bare
 * team id when no player has it. Pick either side with the search boxes.
 *
 * Data: data/<L>/<S>/hitters.json, pitchers.json and teams.json. NPB (since 15 October 2026): data/npb/<S>/lab.json,
 * whose hitters, pitchers and clubs become the three catalogues here, with percentiles computed in the browser among
 * the players at or above the file's floors (fromLab); registered with BP.routeNpb. Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
let MODE = 'hitter';
const RADAR = { hitter: K_ => K_.HIT_PREFS, pitcher: K_ => K_.PIT_PREFS, team: () => ['rating', 'off_rpg', 'def_rpg', 'pit_rpg', 'war', 'xwoba_plus', 'stuff_plus', 'pitching_plus', 'fielding_runs', 'framing_runs'] };

/* NPB: npb/<S>/lab.json -> {hc, pc, tc} catalogues ({players|teams: {id: {name, team, pos, values, pct, qualified}}, metrics}),
 * percentiles (100 = best, lower-is-better flipped) among the qualified, ties at the midpoint. */
function fromLab(raw) {
  const k = K();
  const out = {};
  if (!raw || raw.ok === false || !raw.rows || Array.isArray(raw.rows)) return out;
  const fl = raw.floors || {};
  Object.keys(raw.rows).forEach(kd => {
    const ms = (raw.metrics || {})[kd] || [];
    const fields = (raw.fields || ['pid', 'name', 'team', 'pos', 'n']).concat(ms.map(m => m.key));
    const idx = {};
    fields.forEach((f, i) => { idx[f] = i; });
    const floor = fl[kd] || 0;
    const P = {};
    (raw.rows[kd] || []).forEach(r => {
      const v = {};
      ms.forEach(m => { v[m.key] = r[idx[m.key]]; });
      const n = r[idx.n];
      P[String(r[idx.pid])] = { name: r[idx.name], team: r[idx.team], pos: r[idx.pos], role: kd === 'pitcher' ? r[idx.pos] : undefined, values: v, pct: {}, n: n,
        pa: kd === 'hitter' ? n : undefined, bf: kd === 'pitcher' ? n : undefined, qualified: (n || 0) >= floor };
    });
    ms.forEach(m => {
      const ids = Object.keys(P).filter(id => P[id].qualified && k.isNum(P[id].values[m.key]));
      if (ids.length < 3) return;
      const vals = ids.map(id => Number(P[id].values[m.key])).sort((a, b) => a - b);
      ids.forEach(id => {
        const x = Number(P[id].values[m.key]);
        let lo = 0, eq = 0;
        vals.forEach(y => { if (y < x) lo++; else if (y === x) eq++; });
        const pc = 100 * (lo + eq / 2) / vals.length;
        P[id].pct[m.key] = m.lower ? 100 - pc : pc;
      });
    });
    if (/team|club/.test(kd)) out.tc = { teams: P, metrics: ms };
    else if (/pit/.test(kd)) out.pc = { players: P, metrics: ms };
    else out.hc = { players: P, metrics: ms };
  });
  return out;
}

function kindOf(id, hc, pc, tc) {
  const s = String(id || '');
  if (/^t\d+$/i.test(s)) return 'team';
  if (hc && hc.players[s] && (!pc || !pc.players[s] || K().sampleOf(hc.players[s], 'hitter') >= K().sampleOf(pc.players[s], 'pitcher'))) return 'hitter';
  if (pc && pc.players[s]) return 'pitcher';
  if (tc && tc.teams[s]) return 'team';
  return null;
}
function entity(kind, id, hc, pc, tc) {
  const k = K();
  const s = String(id || '').replace(/^t/i, '');
  if (kind === 'team') { const t = (tc && tc.teams[s]) || null; return t ? { id: s, name: k.teamName(s), values: t.values || {}, pct: t.pct || {}, team: s, colour: k.teamColour(s) } : null; }
  const c = kind === 'pitcher' ? pc : hc;
  const p = c && c.players[s];
  return p ? { id: s, name: p.name || k.name(s), values: p.values || {}, pct: p.pct || {}, pctRole: p.pct_role || {}, team: p.team, pos: kind === 'pitcher' ? k.roleOf(p) : p.pos, age: p.age, n: k.sampleOf(p, kind), qualified: p.qualified } : null;
}

function render(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  const a0 = params.a || (params.rest || [])[0] || '', b0 = params.b || (params.rest || [])[1] || '';
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    if (L === 'npb') return k.loadY(L, S, 'lab.json').then(d => ({ S: S, res: [d, d, d, null], npb: fromLab(d) }));
    return Promise.all([k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json'), k.loadY(L, S, 'teams.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S;
    const nb = o.npb || null;
    const hc = nb ? (nb.hc || null) : k.catOf(o.res[0], 'hitters'), pc = nb ? (nb.pc || null) : k.catOf(o.res[1], 'pitchers');
    const tr = o.res[2], tc = nb ? (nb.tc || null) : (tr && tr.ok !== false && tr.teams ? tr : null);
    if (hc) k.learnCat(hc);
    if (pc) k.learnCat(pc);
    if (tc) Object.keys(tc.teams).forEach(t => k.learnTeam(t, tc.teams[t]));
    const ka = kindOf(a0, hc, pc, tc), kb = kindOf(b0, hc, pc, tc);
    MODE = ka || kb || MODE;
    const cat = MODE === 'team' ? tc : MODE === 'pitcher' ? pc : hc;
    let A = ka === MODE ? entity(MODE, a0, hc, pc, tc) : null, B = kb === MODE ? entity(MODE, b0, hc, pc, tc) : null;
    // A lone side: suggest the most similar on the headline metrics as the other.
    if (A && !B && cat) B = entity(MODE, nearest(MODE, A, cat), hc, pc, tc);
    const tag = x => (MODE === 'team' ? 't' + x : x);
    let h = '<div class="card"><div class="card-header">Compare <span class="card-sub">' + k.LN(L) + ' ' + S + '. Pick two of the same kind.</span><span class="gq-ctl">' + k.toggle('cmp-mode', [['hitter', 'Hitters'], ['pitcher', 'Pitchers'], ['team', 'Teams']], MODE) + '</span></div>' +
      '<div class="gq-cmp-pick"><div><span class="gq-dot a"></span><div id="cmp-pa"></div></div><button type="button" class="gq-btn" id="cmp-swap" title="Swap">⇄</button><div><span class="gq-dot b"></span><div id="cmp-pb"></div></div></div></div>';
    if (!cat) h += k.card('Compare', '', k.notBuilt('The ' + (MODE === 'team' ? 'team' : MODE) + ' catalogue', MODE === 'team' ? tr : MODE === 'pitcher' ? o.res[1] : o.res[0]));
    else if (!A || !B) h += k.card('', '', k.muted('Pick ' + (A ? 'a second ' : 'two ') + (MODE === 'team' ? 'teams' : MODE + 's') + ' above.'));
    else h += body(L, S, A, B, cat);
    el.innerHTML = h;
    const go = (a, b) => { location.hash = k.compareHref(a ? tag(a) : '', b ? tag(b) : ''); };
    const extra = {};
    if (MODE === 'team' && tc) Object.keys(tc.teams).forEach(t => { extra[t] = { name: k.teamName(t), team: t, pos: 'team' }; });
    const filt = MODE === 'team' ? (id => !!(tc && tc.teams[id])) : (id => !!(cat && cat.players[id]));
    const pick = (id, val, other, side) => k.picker(document.getElementById(id), { value: val ? val.id : null, label: val ? val.name : '', placeholder: MODE === 'team' ? 'Type a team…' : 'Type a ' + MODE + '…', extra: MODE === 'team' ? extra : null,
      filter: MODE === 'team' ? (pid => !!extra[pid]) : filt, onPick: pid => (side === 'a' ? go(pid, other ? other.id : '') : go(other ? other.id : '', pid)) });
    pick('cmp-pa', A, B, 'a'); pick('cmp-pb', B, A, 'b');
    const sw = document.getElementById('cmp-swap');
    if (sw) sw.onclick = () => { if (A || B) go(B ? B.id : '', A ? A.id : ''); };
    k.wireToggle(el, 'cmp-mode', v => { MODE = v; if (location.hash === '#/compare') render(el, { query: params.query }, state); else location.hash = '#/compare'; });
    if (A && B && cat) after(L, S, A, B, cat);
  });
}

function nearest(kind, A, cat) {
  const k = K();
  const heads = k.headline(cat.metrics, RADAR[kind](k), 10);
  const P = kind === 'team' ? cat.teams : cat.players;
  let best = null, bd = 1e9;
  Object.keys(P).forEach(id => {
    if (id === A.id) return;
    const p = P[id];
    if (kind !== 'team' && p.qualified === false) return;
    let d = 0, n = 0;
    heads.forEach(m => { const x = A.pct[m.key], y = (p.pct || {})[m.key]; if (k.isNum(x) && k.isNum(y)) { d += (x - y) * (x - y); n++; } });
    if (n >= 3 && d / n < bd) { bd = d / n; best = id; }
  });
  return best;
}

function idCard(L, S, X, side, kind) {
  const k = K();
  const facts = [];
  if (kind !== 'team' && L === 'npb') {
    const v = X.values;
    facts.push(['Club', X.team ? k.teamAbbr(X.team) : '—'], [kind === 'pitcher' ? 'Role' : 'Pos', X.pos || '—'], [kind === 'pitcher' ? 'BF' : 'PA', k.int(X.n)]);
    if (kind === 'hitter') facts.push(['wOBA', k.rate3(v.woba)], ['xwOBA', k.rate3(v.xwoba)], ['wRC+', k.fmtV(v.wrc_plus, 'plus')], ['WAR-lite', k.isNum(v.war) ? k.signed(v.war, 1) : '—']);
    else facts.push(['FIP', k.num(v.fip, 2)], ['ERA', k.num(v.era, 2)], ['K%', k.fmtV(v.k_pct, 'pct')], ['WAR-lite', k.isNum(v.war) ? k.signed(v.war, 1) : '—']);
  } else if (kind === 'team' && L === 'npb') {
    const v = X.values;
    const war = (k.isNum(v.war_bat) ? v.war_bat : 0) + (k.isNum(v.war_pit) ? v.war_pit : 0);
    facts.push(['W/(W+L)', k.rate3(v.pct)], ['Run diff', k.isNum(v.rd) ? k.signed(v.rd, 0) : '—'], ['Rating', k.isNum(v.rating) ? k.signed(v.rating, 3) : '—'], ['WAR-lite', k.signed(war, 1)]);
  } else if (kind !== 'team') {
    facts.push(['Team', X.team ? k.teamAbbr(X.team) : '—'], [kind === 'pitcher' ? 'Role' : 'Pos', X.pos || '—'], ['Age', k.isNum(X.age) ? k.num(X.age, 0) : '—'], [kind === 'pitcher' ? 'BF' : 'PA', k.int(X.n)]);
    const v = X.values;
    if (kind === 'hitter') facts.push(['xwOBA+', k.rate3(k.val(v, ['xwoba_plus']))], ['wOBA', k.rate3(k.val(v, ['woba']))], ['WAR', k.isNum(k.val(v, ['war'])) ? k.signed(k.val(v, ['war']), 1) : '—']);
    else facts.push(['Pitching+', k.fmtV(k.val(v, ['pitching_plus']), 'plus')], ['Stuff+', k.fmtV(k.val(v, ['stuff_plus']), 'plus')], ['WAR', k.isNum(k.val(v, ['war'])) ? k.signed(k.val(v, ['war']), 1) : '—']);
  } else {
    const v = X.values;
    facts.push(['W–L', k.isNum(v.w) ? v.w + '–' + v.l : '—'], ['Run diff', k.isNum(v.rd) ? k.signed(v.rd, 0) : '—'], ['Rating', k.isNum(v.rating) ? k.signed(v.rating, 2) : '—'], ['WAR', k.isNum(v.war) ? k.signed(v.war, 1) : '—']);
  }
  const href = kind === 'team' ? k.teamHref(L, X.id, S) : kind === 'pitcher' ? k.pitcherHref(L, X.id, S) : k.hitterHref(L, X.id, S);
  return '<div class="gq-cmp-id ' + side + '"><div class="gq-cmp-name"><a href="' + href + '">' + k.esc(X.name) + '</a>' + (X.qualified === false ? ' <span class="gq-tag">small sample</span>' : '') + '</div><div class="gq-cmp-facts">' +
    facts.map(f => '<div class="gq-fact"><span>' + k.esc(f[0]) + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div>';
}

function body(L, S, A, B, cat) {
  const k = K();
  const kind = MODE;
  const ms = (cat.metrics || []).filter(m => k.isNum(A.pct[m.key]) && k.isNum(B.pct[m.key]));
  let wa = 0, wb = 0;
  const gaps = ms.map(m => { const d = A.pct[m.key] - B.pct[m.key]; if (d > 0.5) wa++; else if (d < -0.5) wb++; return { m: m, d: d }; });
  const tot = Math.max(1, wa + wb);
  const ga = gaps.filter(g => g.d > 0).sort((x, y) => y.d - x.d).slice(0, 3), gb = gaps.filter(g => g.d < 0).sort((x, y) => x.d - y.d).slice(0, 3);
  const gl = list => list.map(g => '<strong>' + k.esc(g.m.label) + '</strong> (' + Math.round(Math.abs(g.d)) + ' pts)').join(', ') || 'nothing by much';
  let h = '<div class="gq-cmp-ids">' + idCard(L, S, A, 'a', kind) + idCard(L, S, B, 'b', kind) + '</div>';
  h += '<div class="card"><div class="gq-cmp-verdict"><div class="gq-cmp-side">' + k.esc(A.name) + ' is ahead on ' + gl(ga) + '.</div><div class="gq-cmp-mid"><div class="gq-cmp-score"><span class="a">' + wa + '</span><span class="dash">–</span><span class="b">' + wb + '</span></div>' +
    '<div class="gq-cmp-bar"><span class="a" style="width:' + (100 * wa / tot).toFixed(1) + '%"></span><span class="b" style="width:' + (100 * wb / tot).toFixed(1) + '%"></span></div><div class="gq-cmp-sub">metrics won by percentile, of ' + ms.length + '</div></div>' +
    '<div class="gq-cmp-side b">' + k.esc(B.name) + ' is ahead on ' + gl(gb) + '.</div></div></div>';
  h += '<div class="card"><div class="card-header">Profile <span class="card-sub">Headline metrics as ' + k.LN(L) + ' percentiles (100 = best).</span></div><div id="cmp-radar" style="height:420px"></div></div>';
  h += '<div class="card"><div class="card-header">Every metric <span class="card-sub">Value and percentile for each side; the bar shows the percentile gap (red: ' + k.esc(k.surname(A.name)) + ', blue: ' + k.esc(k.surname(B.name)) + ').</span></div><div id="cmp-all"></div></div>';
  return h;
}

function after(L, S, A, B, cat) {
  const k = K();
  const kind = MODE;
  const heads = k.headline(cat.metrics, RADAR[kind](k), 10).filter(m => k.isNum(A.pct[m.key]) || k.isNum(B.pct[m.key]));
  const node = document.getElementById('cmp-radar');
  if (node && heads.length >= 3) {
    const narrow = k.narrow(node);
    const wrap = s => (narrow && s.length > 12 ? s.replace(/^(.{6,14}?)\s+/, '$1<br>') : s);
    const th = heads.map(m => wrap(m.label));
    const tr = [[A, k.CA], [B, k.CB]].map(x => ({ type: 'scatterpolar', fill: 'toself', name: x[0].name, r: heads.map(m => (k.isNum(x[0].pct[m.key]) ? x[0].pct[m.key] : 0)).concat([k.isNum(x[0].pct[heads[0].key]) ? x[0].pct[heads[0].key] : 0]), theta: th.concat([th[0]]),
      line: { color: x[1], width: 2 }, fillcolor: k.alpha(x[1], 0.16), hovertemplate: '%{theta}: %{r:.0f}th percentile<extra>' + k.esc(x[0].name) + '</extra>' }));
    k.plot(node, tr, k.layout({ showlegend: true, legend: { orientation: 'h', y: -0.1, font: { color: k.C.text2 } },
      polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 100], gridcolor: '#21262d', tickfont: { size: 9 }, tickvals: [25, 50, 75, 100] }, angularaxis: { gridcolor: '#21262d', tickfont: { size: narrow ? 8 : 10 } } },
      margin: narrow ? { l: 46, r: 46, t: 24, b: 40 } : { l: 80, r: 80, t: 24, b: 40 } }));
  } else if (node) node.innerHTML = k.muted('Not enough shared percentiles for a profile.');
  const host = document.getElementById('cmp-all');
  if (!host) return;
  host.innerHTML = k.groups(cat.metrics).map(g => {
    const items = g.items.filter(m => k.isNum(A.values[m.key]) || k.isNum(B.values[m.key]));
    if (!items.length) return '';
    return '<div class="gq-sub-head">' + k.esc(g.name) + '</div>' + items.map(m => {
      const pa = A.pct[m.key], pb = B.pct[m.key];
      const d = k.isNum(pa) && k.isNum(pb) ? pa - pb : null;
      const w = k.isNum(d) ? Math.min(50, Math.abs(d) / 2) : 0;
      return '<div class="gq-cmp-row" title="' + k.esc(m.desc || '') + '"><span class="gq-cmp-v' + (k.isNum(d) && d > 0.5 ? ' win' : '') + '">' + k.fmt(m, A.values[m.key]) + ' ' + k.pill(pa) + '</span>' +
        '<span class="gq-cmp-lab">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '<span class="gq-gap">' + (k.isNum(d) ? '<i class="' + (d > 0 ? 'a' : 'b') + '" style="width:' + w.toFixed(1) + '%"></i>' : '') + '</span></span>' +
        '<span class="gq-cmp-v b' + (k.isNum(d) && d < -0.5 ? ' win' : '') + '">' + k.pill(pb) + ' ' + k.fmt(m, B.values[m.key]) + '</span></div>';
    }).join('');
  }).join('') || k.muted('No shared metrics.');
}

if (typeof BP.route === 'function') {
  [['compare', render], ['#/compare/<a>/<b>', render], ['#/compare/<a>', render]].forEach(r => { try { BP.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
if (typeof BP.routeNpb === 'function') BP.routeNpb('compare', render);
})(window.BP || (window.BP = {}));
