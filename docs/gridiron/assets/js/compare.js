/* The Quant Gridiron — compare (#/compare/<a>/<b>): two players or two teams.
 *
 * Side by side on the season catalogue: who wins each metric (by percentile, so lower-is-better
 * metrics count the right way), the largest gaps each way, a radar of the headline metrics and every
 * metric family in full. Players are gsis ids ("00-0036355"); teams are their abbreviation, written
 * t:KC (a bare KC also works). With one side picked, the other defaults to the most similar.
 *
 * Data: data/<S>/players.json and teams.json. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
let MODE = 'player';
const TEAM_HEAD = ['rating', 'off_rating', 'def_rating', 'off_epa', 'def_epa', 'off_pass_epa', 'off_rush_epa', 'def_pass_epa', 'def_rush_epa', 'st_epa_g', 'go_rate_rec', 'fd_wp_lost'];

function teamId(s) { const m = /^t:?([A-Za-z]{2,3})$/.exec(String(s || '')); return m ? m[1].toUpperCase() : (/^[A-Z]{2,3}$/.test(String(s || '')) ? String(s) : null); }
function entity(id, cat, tc) {
  const k = K();
  const t = teamId(id);
  if (t && tc && tc.teams[t]) { const x = tc.teams[t]; return { kind: 'team', id: t, name: k.teamName(t), values: x.values || {}, pct: x.pct || {}, rank: x.rank || {}, team: t, rec: x.record || null }; }
  const p = cat && cat.players[String(id)];
  if (!p) return null;
  return { kind: 'player', id: String(id), name: p.name || k.name(id), values: p.values || {}, pct: p.pct || {}, pctPos: p.pct_pos || {}, team: p.team, pos: p.pos, group: k.groupOf(p.pos, p.group), age: p.age, games: p.games, qualified: p.qualified };
}
function metricsFor(A, B, cat, tc) {
  const k = K();
  if (MODE === 'team') return (tc && tc.metrics) || [];
  const ga = k.metricsFor(cat, A.group), gb = B ? k.metricsFor(cat, B.group) : ga;
  return ga.filter(m => gb.some(x => x.key === m.key));
}

function render(el, params, state) {
  const k = K();
  const a0 = params.a || (params.rest || [])[0] || '', b0 = params.b || (params.rest || [])[1] || '';
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'players.json'), k.loadY(S, 'teams.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S;
    const cat = k.catOf(o.res[0]);
    const tc = GI.fk.T ? GI.fk.T.teamsOf(o.res[1]) : null;
    if (cat) k.learnCat(cat);
    if (a0 || b0) MODE = teamId(a0 || b0) && tc && tc.teams[teamId(a0 || b0)] ? 'team' : 'player';
    let A = a0 ? entity(a0, cat, tc) : null, B = b0 ? entity(b0, cat, tc) : null;
    if (A && A.kind !== MODE) A = null;
    if (B && B.kind !== MODE) B = null;
    if (A && !B) { const n = nearest(A, cat, tc); if (n) B = entity(n, cat, tc); }
    const src = MODE === 'team' ? tc : cat;
    let h = '<div class="card"><div class="card-header">Compare <span class="card-sub">' + S + '. Pick two players (any positions; the metrics they share are compared) or two teams.</span><span class="gq-ctl">' + k.toggle('cmp-mode', [['player', 'Players'], ['team', 'Teams']], MODE) + '</span></div>' +
      '<div class="gq-cmp-pick"><div><span class="gq-dot a"></span><div id="cmp-pa"></div></div><button type="button" class="gq-btn" id="cmp-swap" title="Swap">⇄</button><div><span class="gq-dot b"></span><div id="cmp-pb"></div></div></div></div>';
    if (!src) h += k.card('Compare', '', k.notBuilt('The ' + (MODE === 'team' ? 'team' : 'player') + ' catalogue', MODE === 'team' ? o.res[1] : o.res[0]));
    else if (!A || !B) h += k.card('', '', k.muted('Pick ' + (A ? 'a second ' : 'two ') + (MODE === 'team' ? 'teams' : 'players') + ' above.' + (a0 && !A ? ' (' + k.esc(a0) + ' is not in the ' + S + ' catalogue.)' : '')));
    else h += body(S, A, B, metricsFor(A, B, cat, tc));
    el.innerHTML = h;
    const tag = x => (MODE === 'team' ? 't:' + x : x);
    const go = (a, b) => { location.hash = k.compareHref(a ? tag(a) : '', b ? tag(b) : '') + k.sq(S); };
    const extra = {};
    if (MODE === 'team' && tc) Object.keys(tc.teams).forEach(t => { extra[t] = { name: k.teamName(t), team: t, pos: 'team' }; });
    else if (cat) Object.keys(cat.players).forEach(id => { const p = cat.players[id]; extra[id] = { name: p.name || k.name(id), team: p.team, pos: p.pos }; });
    const pick = (id, val, other, side) => k.picker(document.getElementById(id), { value: val ? val.id : null, label: val ? val.name : '', placeholder: MODE === 'team' ? 'Type a team…' : 'Type a player…', extra: extra, only: true, min: MODE === 'team' ? 1 : 2,
      onPick: pid => (side === 'a' ? go(pid, other ? other.id : '') : go(other ? other.id : '', pid)) });
    pick('cmp-pa', A, B, 'a'); pick('cmp-pb', B, A, 'b');
    const sw = document.getElementById('cmp-swap');
    if (sw) sw.onclick = () => { if (A || B) go(B ? B.id : '', A ? A.id : ''); };
    k.wireToggle(el, 'cmp-mode', v => { MODE = v; if (location.hash.replace(/\?.*$/, '') === '#/compare') render(el, { query: params.query }, state); else location.hash = '#/compare' + k.sq(S); });
    if (A && B && src) after(S, A, B, metricsFor(A, B, cat, tc));
  });
}

function nearest(A, cat, tc) {
  const k = K();
  if (A.kind === 'team') {
    let best = null, bd = 1e9;
    Object.keys(tc.teams).forEach(t => { if (t === A.id) return; const p = tc.teams[t].pct || {}; let d = 0, n = 0; TEAM_HEAD.forEach(x => { if (k.isNum(A.pct[x]) && k.isNum(p[x])) { d += (A.pct[x] - p[x]) * (A.pct[x] - p[x]); n++; } }); if (n >= 3 && d / n < bd) { bd = d / n; best = t; } });
    return best;
  }
  const heads = k.headline(k.metricsFor(cat, A.group), k.PREFS[A.group] || [], 10);
  let best = null, bd = 1e9;
  Object.keys(cat.players).forEach(id => {
    const p = cat.players[id];
    if (id === A.id || p.qualified === false || k.groupOf(p.pos, p.group) !== A.group) return;
    let d = 0, n = 0;
    heads.forEach(m => { const x = A.pct[m.key], y = (p.pct || {})[m.key]; if (k.isNum(x) && k.isNum(y)) { d += (x - y) * (x - y); n++; } });
    if (n >= 3 && d / n < bd) { bd = d / n; best = id; }
  });
  return best;
}

function idCard(S, X, side) {
  const k = K();
  const facts = [];
  if (X.kind === 'player') {
    const v = X.values;
    facts.push(['Team', X.team ? k.teamChip(X.team, S) : '—'], ['Pos', k.esc(X.pos || '—')], ['Age', k.isNum(X.age) ? k.num(X.age, 0) : '—'], ['Games', k.int(X.games)]);
    const extra = { QB: [['Composite', 'composite', '1'], ['EPA/db', 'epa_db', 'epa'], ['CPOE', 'cpoe', 'signed1']], RB: [['Value', 'value', 'signed1'], ['RYOE/carry', 'ryoe', 'signed2'], ['EPA/carry', 'rush_epa', 'epa']],
      WR: [['Value', 'value', 'signed1'], ['Tgt share', 'target_share', 'pct'], ['EPA/tgt', 'rec_epa_tgt', 'epa']], TE: [['Value', 'value', 'signed1'], ['Tgt share', 'target_share', 'pct'], ['EPA/tgt', 'rec_epa_tgt', 'epa']],
      K: [['FG OE', 'fg_oe', 'signed2'], ['FG%', 'fg_pct', 'pct']], P: [['Net', 'net', '1'], ['EPA/punt', 'epa_punt', 'epa']], DEF: [['Splash EPA', 'def_value', 'signed1'], ['Sacks', 'sacks', '1']] }[X.group] || [];
    extra.forEach(z => facts.push([z[0], k.fmtV(v[z[1]], z[2])]));
  } else {
    const v = X.values, rc = X.rec || {};
    facts.push(['W–L', k.isNum(rc.w) ? rc.w + '–' + rc.l + (rc.t ? '–' + rc.t : '') : '—'], ['Pt diff', k.isNum(rc.diff) ? k.signed(rc.diff, 0) : (k.isNum(rc.pf) ? k.signed(rc.pf - rc.pa, 0) : '—')], ['Rating', k.isNum(v.rating) ? k.signed(v.rating, 1) : '—'],
      ['Off EPA', k.fmtV(v.off_epa, 'epa')], ['Def EPA', k.fmtV(v.def_epa, 'epa')], ['PROE', k.isNum(v.proe) ? k.signed(v.proe * 100, 1) : '—']);
  }
  const href = X.kind === 'team' ? k.teamHref(X.id, S) : k.playerHref(X.id, S);
  return '<div class="gq-cmp-id ' + side + '"><div class="gq-cmp-name"><a href="' + href + '">' + k.esc(X.name) + '</a>' + (X.qualified === false ? ' <span class="gq-tag">small sample</span>' : '') + '</div><div class="gq-cmp-facts">' +
    facts.map(f => '<div class="gq-fact"><span>' + k.esc(f[0]) + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div>';
}

function body(S, A, B, metrics) {
  const k = K();
  const ms = metrics.filter(m => k.isNum(A.pct[m.key]) && k.isNum(B.pct[m.key]));
  let wa = 0, wb = 0;
  const gaps = ms.map(m => { const d = A.pct[m.key] - B.pct[m.key]; if (d > 0.5) wa++; else if (d < -0.5) wb++; return { m: m, d: d }; });
  const tot = Math.max(1, wa + wb);
  const ga = gaps.filter(g => g.d > 0).sort((x, y) => y.d - x.d).slice(0, 3), gb = gaps.filter(g => g.d < 0).sort((x, y) => x.d - y.d).slice(0, 3);
  const gl = list => list.map(g => '<strong>' + k.esc(g.m.label) + '</strong> (' + Math.round(Math.abs(g.d)) + ' pts)').join(', ') || 'nothing by much';
  let h = '<div class="gq-cmp-ids">' + idCard(S, A, 'a') + idCard(S, B, 'b') + '</div>';
  h += '<div class="card"><div class="gq-cmp-verdict"><div class="gq-cmp-side">' + k.esc(A.name) + ' is ahead on ' + gl(ga) + '.</div><div class="gq-cmp-mid"><div class="gq-cmp-score"><span class="a">' + wa + '</span><span class="dash">–</span><span class="b">' + wb + '</span></div>' +
    '<div class="gq-cmp-bar"><span class="a" style="width:' + (100 * wa / tot).toFixed(1) + '%"></span><span class="b" style="width:' + (100 * wb / tot).toFixed(1) + '%"></span></div><div class="gq-cmp-sub">metrics won by percentile, of ' + ms.length + (wa + wb < ms.length ? ' (' + (ms.length - wa - wb) + ' level)' : '') + '</div></div>' +
    '<div class="gq-cmp-side b">' + k.esc(B.name) + ' is ahead on ' + gl(gb) + '.</div></div>' +
    (A.kind === 'player' && A.group !== B.group ? '<div class="pg-note gq-note">Different position groups: each percentile is against the player\'s own group, so only the metrics both groups carry are compared.</div>' : '') + '</div>';
  h += '<div class="card"><div class="card-header">Profile <span class="card-sub">Headline metrics as percentiles (100 = best).</span></div><div id="cmp-radar" class="gf-radar"></div></div>';
  h += '<div class="card"><div class="card-header">Every metric <span class="card-sub">Value and percentile for each side; the bar shows the percentile gap (red: ' + k.esc(k.surname(A.name)) + ', blue: ' + k.esc(k.surname(B.name)) + ').</span></div><div id="cmp-all"></div></div>';
  return h;
}

function after(S, A, B, metrics) {
  const k = K();
  const heads = (A.kind === 'team' ? TEAM_HEAD.map(x => metrics.find(m => m.key === x)).filter(Boolean) : k.headline(metrics, k.PREFS[A.group] || [], 10)).filter(m => k.isNum(A.pct[m.key]) || k.isNum(B.pct[m.key])).slice(0, 10);
  const node = document.getElementById('cmp-radar');
  if (node && heads.length >= 3) {
    const narrow = k.narrow(node);
    const wrap = s => (narrow && s.length > 12 ? s.replace(/^(.{6,14}?)\s+/, '$1<br>') : s);
    const th = heads.map(m => wrap(m.label));
    const shell = k.chart('radar');
    if (shell) { try { shell(node, [{ name: A.name, values: heads.map(m => A.pct[m.key]), colour: k.CA }, { name: B.name, values: heads.map(m => B.pct[m.key]), colour: k.CB }], { labels: th, height: narrow ? 340 : 420 }); } catch (e) { console.warn('radar', e); } }
    else k.plot(node, [[A, k.CA], [B, k.CB]].map(x => ({ type: 'scatterpolar', fill: 'toself', name: x[0].name, r: heads.map(m => (k.isNum(x[0].pct[m.key]) ? x[0].pct[m.key] : 0)).concat([k.isNum(x[0].pct[heads[0].key]) ? x[0].pct[heads[0].key] : 0]), theta: th.concat([th[0]]),
      line: { color: x[1], width: 2 }, fillcolor: k.alpha(x[1], 0.16), hovertemplate: '%{theta}: %{r:.0f}th percentile<extra>' + k.esc(x[0].name) + '</extra>' })),
      k.layout({ showlegend: true, legend: { orientation: 'h', y: -0.1, font: { color: k.C.text2 } }, polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 100], gridcolor: '#21262d', tickfont: { size: 9 }, tickvals: [25, 50, 75, 100] }, angularaxis: { gridcolor: '#21262d', tickfont: { size: narrow ? 8 : 10 } } },
        margin: narrow ? { l: 46, r: 46, t: 24, b: 40 } : { l: 80, r: 80, t: 24, b: 40 } }));
  } else if (node) { node.innerHTML = k.muted('Not enough shared percentiles for a profile.'); node.style.height = 'auto'; }
  const host = document.getElementById('cmp-all');
  if (!host) return;
  host.innerHTML = k.groups(metrics).map(g => {
    const items = g.items.filter(m => k.isNum(A.values[m.key]) || k.isNum(B.values[m.key]));
    if (!items.length) return '';
    return '<div class="gq-sub-head">' + k.esc(g.name) + '</div>' + items.map(m => {
      const pa = A.pct[m.key], pb = B.pct[m.key];
      const d = k.isNum(pa) && k.isNum(pb) ? pa - pb : null;
      const w = k.isNum(d) ? Math.min(50, Math.abs(d) / 2) : 0;
      const ra = (A.rank || {})[m.key], rb = (B.rank || {})[m.key];
      const tagA = k.isNum(pa) ? k.pill(pa) : (k.isNum(ra) ? '<span class="gf-rank">#' + ra + '</span>' : k.pill(pa)), tagB = k.isNum(pb) ? k.pill(pb) : (k.isNum(rb) ? '<span class="gf-rank">#' + rb + '</span>' : k.pill(pb));
      return '<div class="gq-cmp-row" title="' + k.esc(m.desc || '') + '"><span class="gq-cmp-v' + (k.isNum(d) && d > 0.5 ? ' win' : '') + '">' + k.fmt(m, A.values[m.key]) + ' ' + tagA + '</span>' +
        '<span class="gq-cmp-lab">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '<span class="gq-gap">' + (k.isNum(d) ? '<i class="' + (d > 0 ? 'a' : 'b') + '" style="width:' + w.toFixed(1) + '%"></i>' : '') + '</span></span>' +
        '<span class="gq-cmp-v b' + (k.isNum(d) && d < -0.5 ? ' win' : '') + '">' + tagB + ' ' + k.fmt(m, B.values[m.key]) + '</span></div>';
    }).join('');
  }).join('') || k.muted('No shared metrics.');
}

if (typeof GI.route === 'function') { try { GI.route('compare', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
