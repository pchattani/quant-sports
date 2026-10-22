/* The Quant Gridiron — Compare (#/compare/<a>/<b>[/<c>]), in the Lab, on Design System 2.0 (the Rink compare page is
 * the reference). Players: two or three side by side on the one metric set the player card uses (GI.playerSet), each a
 * value and a percentile bar against the peer group (QB, RB, WR/TE, DL and outside rushers, LB, DB, K, P), the better
 * value bold and, for two, the difference; players from different peer groups are each ranked against their own, and
 * the page says so. Below: where each one sits in the peer distribution of a chosen metric. With one player picked the
 * others are his most similar players. Teams (t:KC) and ?view=all keep the classic comparison: who wins each shared
 * metric by percentile, the biggest differences, a radar, a percentile butterfly and every metric with values.
 * Reads <S>/players.json and <S>/teams.json. Exports GI.picker. */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;
let MODE = 'player';
const TEAM_HEAD = ['rating', 'off_rating', 'def_rating', 'off_epa', 'def_epa', 'off_pass_epa', 'off_rush_epa', 'def_pass_epa', 'def_rush_epa', 'st_epa_g', 'go_rate_rec', 'fd_wp_lost'];

/* A typeahead. host: element; o {items: {id: {name, sub}}, value, label, placeholder, min, onPick(id)} */
GI.picker = function (host, o) {
  host.classList.add('gi-picker');
  host.innerHTML = '<input type="search" class="qk-input" autocomplete="off" spellcheck="false" aria-label="' + esc(o.placeholder || 'Search') + '" placeholder="' + esc(o.placeholder || 'Type a name…') + '"><div class="gi-pick-list" role="listbox"></div>';
  const input = host.querySelector('input'), list = host.querySelector('.gi-pick-list');
  if (o.value) input.value = o.label || '';
  const items = Object.keys(o.items).map(id => ({ id: id, n: o.items[id].name || id, s: o.items[id].sub || '', f: GI.fold((o.items[id].name || id) + ' ' + (o.items[id].sub || '')) })).sort((a, b) => a.n.localeCompare(b.n));
  const close = () => { list.style.display = 'none'; list.innerHTML = ''; };
  const show = () => {
    const q = GI.fold(input.value.trim());
    if (q.length < (o.min === undefined ? 2 : o.min)) { close(); return; }
    const words = q.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.f.indexOf(w) >= 0)).slice(0, 12);
    list.innerHTML = hits.length ? hits.map(h => '<button type="button" role="option" data-id="' + esc(h.id) + '"><span>' + esc(h.n) + '</span><span class="gi-pick-sub">' + esc(h.s) + '</span></button>').join('') : '<div class="gi-pick-none">No match.</div>';
    list.style.display = 'block';
  };
  input.addEventListener('input', show);
  input.addEventListener('focus', () => { input.select(); });
  input.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); if (ev.key === 'Enter') { const b = list.querySelector('button[data-id]'); if (b) { ev.preventDefault(); b.click(); } } });
  list.addEventListener('click', ev => { const b = ev.target.closest('button[data-id]'); if (!b) return; input.value = o.items[b.dataset.id].name; close(); if (o.onPick) o.onPick(b.dataset.id); });
  const outside = ev => { if (!host.contains(ev.target)) close(); };
  document.addEventListener('click', outside);
  GI.onLeave(() => document.removeEventListener('click', outside));
};

/* The build ranks rates, not the volume lines (attempts, yards, touchdowns, tackles: fmt "int"), so those rows had no
 * percentile here and never counted. They get one against the qualified players of the same group (100 = best, ties at
 * the midpoint), for every player of the group with a value: by volume, except a quarterback's interceptions, which are
 * placed per attempt with fewer as better. Once per catalogue, kept apart (cat._volPct {id: {key: pct}}) so the shared
 * payload other pages read is not changed. */
function volumePct(cat) {
  if (!cat || cat._volPct || !cat.players) return;
  const out = {};
  cat._volPct = out;
  const P = cat.players, ids = Object.keys(P);
  GI.GROUPS.forEach(g => {
    const mine = ids.filter(id => GI.groupOf(P[id].pos, P[id].group) === g);
    const pool = mine.filter(id => P[id].qualified === true);
    if (pool.length < 5) return;
    GI.metricsFor(cat, g).filter(m => m && m.fmt === 'int' && !mine.some(id => isNum((P[id].pct || {})[m.key]))).forEach(m => {
      const perAtt = g === 'QB' && m.key === 'ints';
      const sv = id => { const v = (P[id].values || {})[m.key]; if (!isNum(v)) return null; if (!perAtt) return Number(v); const a = (P[id].values || {}).att; return isNum(a) && a > 0 ? Number(v) / a : null; };
      const refv = pool.map(sv).filter(isNum).sort((a, b) => a - b);
      if (refv.length < 5) return;
      const n = refv.length;
      mine.forEach(id => {
        const v = sv(id);
        if (!isNum(v)) return;
        let lo = 0, hi = 0;
        refv.forEach(y => { if (y < v) lo++; if (y <= v) hi++; });
        const tie = Math.max(0, hi - lo - 1);
        out[id] = out[id] || {};
        out[id][m.key] = Math.max(0, Math.min(100, Math.round(100 * ((perAtt ? n - hi : lo) + 0.5 * tie) / (n - 1))));
      });
    });
  });
}
function teamId(s) { const m = /^t:?([A-Za-z]{2,3})$/.exec(String(s || '')); return m ? m[1].toUpperCase() : (/^[A-Z]{2,3}$/.test(String(s || '')) ? String(s) : null); }
function entity(id, cat, tc) {
  const t = teamId(id);
  if (t && tc && tc.teams[t]) { const x = tc.teams[t]; return { kind: 'team', id: t, name: GI.teamName(t), values: x.values || {}, pct: x.pct || {}, rank: x.rank || {}, team: t, rec: x.record || {} }; }
  const p = cat && cat.players[String(id)];
  if (!p) return null;
  return { kind: 'player', id: String(id), name: p.name || GI.playerName(id), values: p.values || {}, pct: Object.assign({}, (cat._volPct || {})[String(id)] || {}, p.pct || {}), rank: {}, team: p.team, pos: p.pos, group: GI.groupOf(p.pos, p.group), age: p.age, games: p.games, qualified: p.qualified };
}
function nearest(A, cat, tc) {
  let best = null, bd = 1e9;
  if (A.kind === 'team') {
    Object.keys(tc.teams).forEach(t => { if (t === A.id) return; const p = tc.teams[t].pct || {}; let d = 0, n = 0; TEAM_HEAD.forEach(x => { if (isNum(A.pct[x]) && isNum(p[x])) { d += (A.pct[x] - p[x]) * (A.pct[x] - p[x]); n++; } }); if (n >= 3 && d / n < bd) { bd = d / n; best = t; } });
    return best;
  }
  const heads = GI.headline(GI.metricsFor(cat, A.group), GI.PREFS[A.group] || [], 10);
  Object.keys(cat.players).forEach(id => {
    const p = cat.players[id];
    if (id === A.id || p.qualified === false || GI.groupOf(p.pos, p.group) !== A.group) return;
    let d = 0, n = 0;
    heads.forEach(m => { const x = A.pct[m.key], y = (p.pct || {})[m.key]; if (isNum(x) && isNum(y)) { d += (x - y) * (x - y); n++; } });
    if (n >= 3 && d / n < bd) { bd = d / n; best = id; }
  });
  return best;
}
function idCard(S, X, side) {
  const v = X.values;
  let facts;
  if (X.kind === 'player') facts = [['Team', X.team ? GI.teamChip(X.team, S) : '—'], ['Pos', esc(X.pos || '—')], ['Age', isNum(X.age) ? GI.num(X.age, 0) : '—'], ['Games', GI.int(X.games)]];
  else { const rc = X.rec || {}; facts = [['W-L', GI.record(rc.w, rc.l, rc.t)], ['Rating', GI.signed(v.rating, 1)], ['Off EPA', GI.signed(v.off_epa, 3)], ['Def EPA', GI.signed(v.def_epa, 3)]]; }
  const col = X.team ? GI.tc(X.team) : 'var(--accent)';
  return '<div class="qk-card gi-cmp-id" style="--tc:' + esc(col) + '"><div class="gi-toolbar">' + (X.kind === 'team' ? GI.mark(X.team, 'lg') : '<div class="qk-avatar" style="--tc:' + esc(col) + ';width:52px;height:52px;font-size:18px">' + esc(QK.fmt.initials(X.name)) + '</div>') +
    '<div><span class="qk-kicker" style="color:' + (side === 'a' ? 'var(--wp-a)' : 'var(--wp-b)') + '">' + (side === 'a' ? 'Blue' : 'Orange') + '</span><br><a class="gi-link" style="font-size:var(--fs-lg)" href="' + (X.kind === 'team' ? GI.teamHref(X.id, S) : GI.playerHref(X.id, S)) + '">' + esc(X.name) + '</a>' + (X.qualified === false ? ' <span class="gi-tag">small sample</span>' : '') + '</div></div>' +
    GI.kpis(facts.map(f => GI.kpi(f[0], f[1]))) + '</div>';
}

const ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-3)'];
const DSEL = { key: null };
/* The v2 player comparison: two or three players on the player card's metric set. */
function compareV2(el, S, ids0, cat) {
  const sq = GI.sq(S);
  let h = GI.pageHead('Lab · ' + S, 'Compare', 'Two or three players side by side on the metrics that best describe and predict their play, each ranked against his own peer group.') + GI.sectionNav('lab', 'compare') +
    GI.subnav([['#/compare' + sq, 'Players', 'p'], ['#/compare/t:KC/t:BUF' + sq, 'Teams (classic)', 't'], ['#/compare' + (ids0.length ? '/' + ids0.map(encodeURIComponent).join('/') : '') + '?view=all' + (sq ? '&' + sq.slice(1) : ''), 'Every metric (classic)', 'all']], 'p', 'Compare views');
  if (!cat) { el.innerHTML = h + GI.notBuilt('The ' + S + ' player catalogue', null); return; }
  const P = cat.players;
  let ids = ids0.filter(id => P[id]);
  if (ids.length === 1) {
    /* one picked: his most similar players (player file), else the nearest on the catalogue */
    return GI.loadPlayer(ids[0]).then(pf => {
      const sim = ((pf && pf.similar) || []).map(r => String(Array.isArray(r) ? r[0] : r.pid)).filter(id => P[id] && id !== ids[0]);
      const more = sim.length ? sim.slice(0, 1) : [nearest(entity(ids[0], cat, null), cat, null)].filter(Boolean);
      if (el.isConnected) drawV2(el, h, S, ids.concat(more), cat);
    });
  }
  if (!ids.length) {
    const qb = Object.keys(P).filter(id => GI.groupOf(P[id].pos, P[id].group) === 'QB' && P[id].qualified !== false && isNum((P[id].values || {}).epa_db)).sort((a, b) => P[b].values.epa_db - P[a].values.epa_db);
    ids = qb.slice(0, 2);
  }
  drawV2(el, h, S, ids, cat);
}
function drawV2(el, h, S, ids, cat) {
  const P = cat.players;
  const E = ids.slice(0, 3).map(id => ({ id: id, p: P[id], group: GI.groupOf(P[id].pos, P[id].group) }));
  const items = {};
  Object.keys(P).forEach(id => { const p = P[id]; items[id] = { name: p.name || GI.playerName(id), sub: [GI.posLabel(p.pos), p.team].filter(Boolean).join(' · ') }; });
  const pick = '<div class="gi-cmp-pick">' + [0, 1, 2].map(i => '<div class="gi-cmp-slot" style="--ec:' + ECOL[i] + '"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span><div id="cmp-p' + i + '"></div></div>').join('') + '</div>';
  if (E.length < 2) {
    el.innerHTML = h + GI.card('Pick players', 'Choose two or three players to compare', pick + QK.empty('Pick at least two players', 'Type a name in each box.'));
    wireV2(el, S, E, items);
    return;
  }
  const meta = GI.metaOf(GI.allMetrics(cat));
  const peers = E.map(e => GI.peerOf(e.p, e.group));
  const same = peers.every(x => x.id === peers[0].id);
  const g0 = E[0].group;
  const sameGroup = E.every(e => e.group === g0 || (/^(WR|TE)$/.test(e.group) && /^(WR|TE)$/.test(g0)));
  /* the metric set: the first player's group set, kept to the metrics every player has */
  const set = GI.playerSet(g0, GI.metricsFor(cat, g0), 12);
  const groups = set.map(g => ({ label: g[0], rows: g[1].filter(k => meta[k] && E.some(e => isNum((e.p.values || {})[k]))).map(k => {
    const m = meta[k], pctFmt = m.fmt === 'pct' || m.fmt === 'pct0';
    return { label: m.label + (m.lower ? ' ↓' : ''), tip: GI.copyText(m.desc || ''), better: m.lower ? 'low' : 'high', values: E.map(e => (e.p.values || {})[k]), pctls: E.map(e => GI.peerPct(e.p, e.group)[k]),
      fmt: v => GI.fmtVal(v, m.fmt), dfmt: pctFmt ? (v => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v * 100).toFixed(1) + ' pts') : null };
  }) })).filter(g => g.rows.length);
  const ents = E.map((e, i) => ({ name: e.p.name || GI.playerName(e.id), href: GI.playerHref(e.id, S), abbr: GI.surnameOf(e.p.name || ''), colour: null,
    sub: [GI.posLabel(e.p.pos), GI.teamAbbr(e.p.team), (e.p.games || 0) + ' G', GI.sampleLine(e.p, e.group, '').replace(/^\d+ G · /, '')].filter(Boolean).join(' · ') }));
  const peerTxt = same ? peers[0].name : 'each against his own peer group (' + peers.map((x, i) => GI.surnameOf(E[i].p.name || '') + ': ' + x.name.replace(/^NFL /, '')).join('; ') + ')';
  const small = E.filter(e => e.p.qualified === false).map(e => e.p.name);
  el.innerHTML = h + GI.card('Players', 'Ranked against ' + esc(peerTxt) + ' this season (' + S + ')', pick) +
    '<section class="qk-section" style="margin-top:var(--sp-4)">' + GI.card('Side by side', 'Value · percentile against the peer group (100 = best) · ' + (E.length === 2 ? 'difference, green when ' + esc(E[0].p.name) + ' is better' : 'the best of three in bold'),
      QK.compareView({ entities: ents, groups: groups }) +
      (small.length ? '<p class="qk-caption">' + esc(small.join(', ')) + (small.length > 1 ? ' are' : ' is') + ' short of the sample floor: read the percentiles as early, or missing.</p>' : '') +
      (!sameGroup ? '<p class="qk-caption">Different positions: the rows are ' + esc(GI.GROUP_ONE[g0] || 'player') + ' metrics, and each percentile is against the player’s own peer group.</p>' : '')) + '</section>' +
    '<section class="qk-section">' + GI.card('Where they sit', 'The qualified ' + esc(peers[0].name.replace(/^NFL /, '')) + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + GI.chartBox('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
  wireV2(el, S, E, items);
  const keys = [].concat.apply([], set.map(g => g[1])).filter(k => meta[k] && E.every(e => isNum((e.p.values || {})[k]))).slice(0, 4);
  const seg = el.querySelector('#cmp-dist-m');
  if (!keys.length) { GI.ch.none('cmp-dist', 'No metric all of them have.'); return; }
  if (!DSEL.key || keys.indexOf(DSEL.key) < 0) DSEL.key = keys[0];
  seg.innerHTML = keys.map(k => '<button type="button" aria-pressed="' + (k === DSEL.key) + '" data-value="' + esc(k) + '">' + esc(GI.shortLabel(meta[k].label)) + '</button>').join('');
  const pool = Object.keys(P).map(id => P[id]).filter(x => x && x.qualified !== false && GI.peerOf(x).id === peers[0].id);
  const dd = key => {
    DSEL.key = key;
    const m = meta[key] || {};
    const vs = pool.map(x => (x.values || {})[key]).filter(isNum).sort((a, b) => a - b);
    if (vs.length < 5) { GI.ch.none('cmp-dist', 'Too few qualified peers yet.'); return; }
    const n = document.getElementById('cmp-dist');
    if (!n) return;
    n.classList.remove('gi-chart-empty'); n.innerHTML = '';
    const cols = ['wpA', 'wpB', 'c3'];
    const c = QKC.distribution(n, { values: vs, binCount: 22, lowerBetter: !!m.lower, fmt: v => GI.fmtVal(v, m.fmt), colorBy: 'flat', xName: (m.label || key) + ' · ' + vs.length + ' qualified peers', yName: 'Players',
      marks: E.map((e, i) => ({ x: (e.p.values || {})[key], label: GI.surnameOf(e.p.name || ''), color: cols[i] })).filter(x => isNum(x.x)), label: 'Distribution of ' + (m.label || key) });
    if (c) GI.onLeave(() => { try { c.dispose(); } catch (e2) { /* gone */ } });
  };
  dd(DSEL.key);
  QK.seg(seg, dd);
}
function wireV2(el, S, E, items) {
  [0, 1, 2].forEach(i => {
    const host = document.getElementById('cmp-p' + i);
    if (!host) return;
    GI.picker(host, { items: items, value: E[i] ? E[i].id : null, label: E[i] ? (E[i].p.name || '') : '', placeholder: i === 2 ? 'Add a third player' : 'Type a name', min: 2,
      onPick: id => { const ids = E.map(e => e.id); ids[i] = id; location.hash = GI.compareHref(ids[0], ids[1], ids[2]) + GI.sq(S); } });
  });
}

GI.route('compare', function (el, params) {
  const S = Number(params.season);
  const a0 = params.a || '', b0 = params.b || '';
  const classic = ((params.query || {}).view) === 'all' || teamId(a0) || teamId(b0) || MODE === 'team' && !a0 && !b0 && ((params.query || {}).view) === 'teams';
  if (!classic) {
    return GI.load(GI.ypath('players.json', S)).then(raw => {
      if (!el.isConnected) return;
      MODE = 'player';
      compareV2(el, S, [params.a, params.b, params.c].filter(Boolean).map(String), GI.catOf(raw));
    });
  }
  return GI.loadAll([GI.ypath('players.json', S), GI.ypath('teams.json', S)]).then(res => {
    if (!el.isConnected) return;
    const cat = GI.catOf(res[0]);
    volumePct(cat);
    const tc = GI.TM.of(res[1]);
    if (a0 || b0) MODE = teamId(a0 || b0) && tc && tc.teams[teamId(a0 || b0)] ? 'team' : 'player';
    let A = a0 ? entity(a0, cat, tc) : null, B = b0 ? entity(b0, cat, tc) : null;
    if (A && A.kind !== MODE) A = null;
    if (B && B.kind !== MODE) B = null;
    if (A && !B) { const n = nearest(A, cat, tc); if (n) B = entity(MODE === 'team' ? 't:' + n : n, cat, tc); }
    const src = MODE === 'team' ? tc : cat;
    const metrics = !A || !B ? [] : MODE === 'team' ? (tc.metrics || []) : GI.metricsFor(cat, A.group).filter(m => GI.metricsFor(cat, B.group).some(x => x.key === m.key));
    const sq0 = GI.sq(S);
    let h = GI.pageHead('Lab · ' + S, 'Compare', 'Two players (every metric they share) or two teams, by percentile: the classic comparison.') + GI.sectionNav('lab', 'compare') +
      GI.subnav([['#/compare' + sq0, 'Players', 'p'], ['#/compare/t:KC/t:BUF' + sq0, 'Teams (classic)', 't'], ['#/compare' + (a0 && !teamId(a0) ? '/' + encodeURIComponent(a0) + (b0 ? '/' + encodeURIComponent(b0) : '') : '') + '?view=all' + (sq0 ? '&' + sq0.slice(1) : ''), 'Every metric (classic)', 'all']], MODE === 'team' ? 't' : 'all', 'Compare views') +
      GI.card('', '', '<div class="gi-toolbar">' + GI.seg('cmp-mode', [['player', 'Players'], ['team', 'Teams']], MODE, 'Compare') + '<div id="cmp-pa"></div><button type="button" class="qk-btn" id="cmp-swap" aria-label="Swap">⇄</button><div id="cmp-pb"></div></div>');
    if (!src) h += GI.notBuilt('The ' + (MODE === 'team' ? 'team' : 'player') + ' catalogue', MODE === 'team' ? res[1] : res[0]);
    else if (!A || !B) h += QK.empty('Pick ' + (A ? 'a second ' : 'two ') + (MODE === 'team' ? 'teams' : 'players'), (a0 && !A ? a0 + ' is not in the ' + S + ' catalogue. ' : '') + 'Type a name above.');
    else {
      const ms = metrics.filter(m => isNum(A.pct[m.key]) && isNum(B.pct[m.key]));
      let wa = 0, wb = 0;
      const gaps = ms.map(m => { const d = A.pct[m.key] - B.pct[m.key]; if (d > 0.5) wa++; else if (d < -0.5) wb++; return { m: m, d: d }; });
      const tot = Math.max(1, wa + wb);
      const gl = list => list.map(g => '<b>' + esc(g.m.label) + '</b> (' + Math.round(Math.abs(g.d)) + ')').join(', ') || 'nothing by much';
      h += '<div class="gi-cmp-ids">' + idCard(S, A, 'a') + idCard(S, B, 'b') + '</div>' +
        GI.card('', '', '<div class="gi-verdict"><div>' + esc(A.name) + ' is ahead on ' + gl(gaps.filter(g => g.d > 0).sort((x, y) => y.d - x.d).slice(0, 3)) + '.</div>' +
          '<div class="gi-verdict-mid"><div class="gi-verdict-score"><span class="a">' + wa + '</span><span>–</span><span class="b">' + wb + '</span></div>' + QK.probBar(wa / tot, null, wb / tot, { name: A.name }, { name: B.name }) + '<div class="qk-sub">metrics won by percentile, of ' + ms.length + '</div></div>' +
          '<div class="gi-verdict-side b">' + esc(B.name) + ' is ahead on ' + gl(gaps.filter(g => g.d < 0).sort((x, y) => x.d - y.d).slice(0, 3)) + '.</div></div>' +
          (A.kind === 'player' && A.group !== B.group ? '<p class="gi-cap">Different position groups: each percentile is against the player\'s own group.</p>' : '')) +
        GI.grid(GI.card('Profile', 'headline metrics as percentiles (100 = best)', GI.chartBox('cmp-radar', 420, 'Percentile radar'), { span: 5 }) +
          GI.card('Every shared metric', 'percentile, blue left and orange right', GI.chartBox('cmp-fly', Math.max(300, ms.length * 24 + 40), 'Percentile butterfly'), { span: 7 })) +
        GI.card('The numbers', '', '<div id="cmp-all"></div>', { flush: true });
    }
    el.innerHTML = h;
    const tag = x => (MODE === 'team' ? 't:' + x : x);
    const go = (a, b) => { location.hash = GI.compareHref(a ? tag(a) : '', b ? tag(b) : '') + (MODE === 'player' ? '?view=all' + (GI.sq(S) ? '&' + GI.sq(S).slice(1) : '') : GI.sq(S)); };
    const items = {};
    if (MODE === 'team' && tc) Object.keys(tc.teams).forEach(t => { items[t] = { name: GI.teamName(t), sub: t }; });
    else if (cat) Object.keys(cat.players).forEach(id => { const p = cat.players[id]; items[id] = { name: p.name || GI.playerName(id), sub: [p.pos, p.team].filter(Boolean).join(' · ') }; });
    const pa = document.getElementById('cmp-pa'), pb = document.getElementById('cmp-pb');
    if (pa) GI.picker(pa, { items: items, value: A ? A.id : null, label: A ? A.name : '', placeholder: MODE === 'team' ? 'First team' : 'First player', min: MODE === 'team' ? 1 : 2, onPick: id => go(id, B ? B.id : '') });
    if (pb) GI.picker(pb, { items: items, value: B ? B.id : null, label: B ? B.name : '', placeholder: MODE === 'team' ? 'Second team' : 'Second player', min: MODE === 'team' ? 1 : 2, onPick: id => go(A ? A.id : '', id) });
    const sw = document.getElementById('cmp-swap');
    if (sw) sw.addEventListener('click', () => { if (A || B) go(B ? B.id : '', A ? A.id : ''); });
    GI.wireSeg(el, 'cmp-mode', v => { MODE = v; location.hash = v === 'team' ? '#/compare/t:KC/t:BUF' + GI.sq(S) : '#/compare' + GI.sq(S); });
    if (!A || !B || !src) return;
    const heads = (A.kind === 'team' ? TEAM_HEAD.map(x => metrics.find(m => m.key === x)).filter(Boolean) : GI.headline(metrics, GI.PREFS[A.group] || [], 10)).filter(m => isNum(A.pct[m.key]) || isNum(B.pct[m.key])).slice(0, 10);
    GI.ch.radar('cmp-radar', [{ name: A.name, values: heads.map(m => A.pct[m.key]), colour: '#3987e5' }, { name: B.name, values: heads.map(m => B.pct[m.key]), colour: '#e8833a' }], { labels: heads.map(m => GI.shortLabel(m.label)) });
    const ms = metrics.filter(m => isNum(A.pct[m.key]) && isNum(B.pct[m.key]));
    GI.ch.mount('cmp-fly', T => {
      const cats = ms.map(m => m.label + (m.lower ? ' ↓' : ''));
      const ya = GI.ch.ax(T, { type: 'category', data: cats, split: false, inverse: true });
      ya.axisLabel.color = T.ink2; ya.axisLabel.width = 150; ya.axisLabel.overflow = 'truncate';
      return { grid: { left: 8, right: 16, top: 26, bottom: 30, containLabel: true }, legend: GI.ch.legend(T, { data: [A.name, B.name] }),
        xAxis: GI.ch.ax(T, { min: -100, max: 100, fmt: v => String(Math.abs(v)), name: 'Percentile', nameLocation: 'middle', nameGap: 26 }), yAxis: ya,
        tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const m = ms[ps[0].dataIndex]; return GI.ch.thead(esc(m.label)) + GI.ch.trow(QK.cssVar('--wp-a') || T.cat[0], A.name, GI.fmtVal(A.values[m.key], m.fmt) + ' · ' + Math.round(A.pct[m.key]) + 'th') + GI.ch.trow(T.cat[1], B.name, GI.fmtVal(B.values[m.key], m.fmt) + ' · ' + Math.round(B.pct[m.key]) + 'th'); } }),
        series: [{ type: 'bar', name: A.name, stack: 's', data: ms.map(m => -A.pct[m.key]), barMaxWidth: 12, itemStyle: { color: QK.cssVar('--wp-a') || T.cat[0], borderRadius: [3, 0, 0, 3] } },
          { type: 'bar', name: B.name, stack: 's', data: ms.map(m => B.pct[m.key]), barMaxWidth: 12, itemStyle: { color: QK.cssVar('--wp-b') || T.cat[1], borderRadius: [0, 3, 3, 0] } }] };
    }, 'Percentile butterfly');
    GI.set('cmp-all', GI.tableHTML([{ label: 'Group' }, { label: 'Metric' }, { label: A.name, align: 'right' }, { label: 'Pct', align: 'right' }, { label: B.name, align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Gap', align: 'right', title: 'Percentile points, blue minus orange' }],
      metrics.filter(m => isNum(A.values[m.key]) || isNum(B.values[m.key])).map(m => { const pa2 = A.pct[m.key], pb2 = B.pct[m.key], d = isNum(pa2) && isNum(pb2) ? pa2 - pb2 : null;
        return [m.group || '', { html: GI.glossLink(m.key, esc(m.label)) + (m.lower ? ' ↓' : ''), v: m.label }, { html: GI.fmtVal(A.values[m.key], m.fmt), v: A.values[m.key] }, { html: QK.pctlChip(pa2) || '—', v: pa2 }, { html: GI.fmtVal(B.values[m.key], m.fmt), v: B.values[m.key] }, { html: QK.pctlChip(pb2) || '—', v: pb2 }, { html: GI.deltaHTML(d, 0), v: d }]; }), { sticky: true, maxHeight: 600 }));
    GI.sortable(document.getElementById('cmp-all'));
  });
});

})(window.GI);
