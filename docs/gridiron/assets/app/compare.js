/* The Quant Gridiron — Compare (#/compare/<a>/<b>[/<c>]), in the Scouting Room, on kit v4 "Broadcast" (the Rink compare page is
 * the reference). Players: two or three side by side on the metrics spec's headline set (spec.js), each a value and a
 * percentile bar against the group (QB, RB, WR, TE, outside pass rushers, interior linemen, LB, CB, S, K, P); two are
 * the tale of the tape in their team colours (the better number solid), three a table with the best under the volt
 * stroke; players from different peer groups are each ranked against their own, and
 * the page says so. Below: where each one sits in the peer distribution of a chosen metric. With one player picked the
 * others are his most similar players. The title asks the question ("Purdy, Prescott or Goff?") and a verdict under it
 * names what each player does best. Round 9: in the Scouting Room section; the classic tabs retired (teams: the Teams
 * page's head to head, where #/compare/t:KC/t:BUF now lands; quick reads of up to four: the room's compare tray).
 * Reads <S>/players.json and <S>/value.json. Exports GI.picker. */
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
const ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];
const DSEL = { key: null };
/* The type a player's best metric suggests (verdicts), by the spec's metric id. */
const ARCHETYPE = { composite: 'The all-round passer', epa_db: 'The efficient passer', cpoe: 'The accurate passer', sack_rate: 'The sack-dodger', int_rate: 'The ball-protector', pressure_rate: 'The quick processor',
  gvar_pg: 'The most valuable', ryoe: 'The elusive runner', rush_success: 'The steady runner', explosive: 'The home-run hitter', rush_epa: 'The efficient runner', stuff_rate: 'The tough runner', target_share: 'The go-to target',
  yptpa: 'The yardage machine', rec_epa_tgt: 'The efficient target', croe: 'The sure hands', yac_rec: 'The YAC threat', pressures_pg: 'The pass rusher', tfl_pg: 'The backfield wrecker', tackles_pg: 'The tackler',
  ff_pg: 'The strip specialist', pd_pg: 'The ball hawk', ints_pg: 'The ball hawk', splash_pg: 'The playmaker', fg_oe: 'The accurate kicker', fg_50_pct: 'The big leg', xp_pct: 'The steady kicker', fg_50: 'The big leg',
  epa_punt: 'The field flipper', net: 'The field flipper', gross: 'The big leg', inside20: 'The pin-it-deep punter', touchback_rate: 'The precise punter' };
/* The v2 player comparison: two or three players on the player card's metric set. */
function compareV2(el, S, ids0, cat) {
  const sq = GI.sq(S);
  /* round 9: the classic tabs retired: teams are on the Teams page's head to head, and quick side-by-side reads (up to
     four players, every view metric) are the Scouting Room's compare tray */
  let h = GI.pageHead('Scouting Room · ' + S, 'Compare', 'Two or three players side by side on the metrics that best describe and predict their play at their position, each ranked against their own group.') + GI.sectionNav('scout', 'compare') +
    GI.subnav([['#/compare' + sq, 'Players', 'p'], ['#/compare/progression' + (ids0.length ? '/' + ids0.map(encodeURIComponent).join('/') : ''), 'Career progression', 'prog'], [GI.ghref('teams', S, { sec: 'h2h' }), 'Teams: head to head', 't'], [GI.ghref('scout', S), 'The compare tray (Scouting Room)', 'tray']], 'p', 'Compare views');
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
  const P = cat.players, cx = cat._spv || cat._sp || GI.SP.ctx(cat, null);
  const E = ids.slice(0, 3).map(id => ({ id: id, p: P[id], g: GI.SP.groupOf(P[id], id, cx) }));
  const items = {};
  Object.keys(P).forEach(id => { const p = P[id]; items[id] = { name: p.name || GI.playerName(id), sub: [GI.posLabel(p.pos), p.team].filter(Boolean).join(' · ') }; });
  const pick = '<div class="gi-cmp-pick">' + [0, 1, 2].map(i => '<div class="gi-cmp-slot" style="--ec:' + ECOL[i] + '"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span><div id="cmp-p' + i + '"></div></div>').join('') + '</div>';
  const noGroup = E.filter(e => !e.g);
  if (E.length < 2 || noGroup.length) {
    el.innerHTML = h + GI.card('Pick players', 'Choose two or three players to compare', pick + (noGroup.length ? QK.empty('No comparison group', esc(noGroup.map(e => e.p.name).join(', ')) + ': percentiles are kept for QB, RB, WR, TE, the five defensive roles, K and P (not offensive linemen).') : QK.empty('Pick at least two players', 'Type a name in each box.')));
    wireV2(el, S, E, items);
    return;
  }
  const g0 = E[0].g;
  const same = E.every(e => e.g.id === g0.id);
  const hl = GI.SP.headline(g0), sty = GI.SP.style(g0);
  const groups = [{ label: 'The ' + g0.name.toLowerCase() + ' set', rows: hl.filter(m => E.some(e => isNum(GI.SP.value(e.p, e.id, m, cx)))).map(m => {
    const pctFmt = GI.SP.fmtOf(m, cx) === 'pct';
    return { key: m[0], m: m, label: m[1] + (m[3] ? ' ↓' : ''), tip: m[5], better: m[3] ? 'low' : 'high', values: E.map(e => GI.SP.value(e.p, e.id, m, cx)), pctls: E.map(e => GI.SP.pct(e.p, e.id, e.g, m, cx)),
      fmt: v => GI.SP.fmt(m, v, cx), dfmt: pctFmt ? (v => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v * 100).toFixed(1) + ' pts') : null };
  }) }];
  /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
  const short = E.map(e => GI.surnameOf(e.p.name || '') || e.p.name || e.id);
  const verd = E.map((e, i) => {
    let bestD = 0, bestRow = null;
    groups[0].rows.forEach(r => {
      const mine = r.pctls[i]; if (!isNum(mine)) return;
      const d = mine - Math.max.apply(null, r.pctls.filter((_, j) => j !== i).map(v => (isNum(v) ? v : 0)));
      if (d > bestD) { bestD = d; bestRow = r; }
    });
    return bestRow ? { title: ARCHETYPE[bestRow.key] || 'The standout', who: short[i], text: 'best of the ' + E.length + ' on ' + (/^[A-Z][a-z]/.test(bestRow.m[1]) ? bestRow.m[1].charAt(0).toLowerCase() + bestRow.m[1].slice(1) : bestRow.m[1]) + ' (' + bestRow.fmt(bestRow.values[i]) + ', ' + QK.ordinal(Math.round(bestRow.pctls[i])) + ' percentile).' } : null;
  });
  const q = short.length === 2 ? short[0] + ' or ' + short[1] + '?' : short.slice(0, -1).join(', ') + ' or ' + short[short.length - 1] + '?';
  /* v4: two players draw the tale of the tape in their team colours (QK.tape via QK.compareView); three keep the table */
  const ents = E.map(e => ({ name: e.p.name || GI.playerName(e.id), href: GI.playerHref(e.id, S), abbr: GI.surnameOf(e.p.name || ''), short: GI.surnameOf(e.p.name || '') || e.p.name,
    colour: GI.teamInfo(e.p.team).colour, alt: GI.teamInfo(e.p.team).alt,
    sub: [GI.posLabel(e.p.pos), GI.teamAbbr(e.p.team), GI.SP.sample(e.p, e.g)].filter(Boolean).join(' · ') }));
  const peerTxt = same ? g0.peer : 'each against their own group (' + E.map(e => GI.surnameOf(e.p.name || '') + ': ' + e.g.peer.replace(/^NFL /, '')).join('; ') + ')';
  const small = E.filter(e => e.p.qualified === false).map(e => e.p.name);
  const styleRows = sty.filter(m => E.some(e => isNum(GI.SP.value(e.p, e.id, m, cx))));
  const styleTbl = styleRows.length ? GI.card('Playing style', 'How they play, not how well: no better or worse', GI.tableHTML([{ label: 'Metric', sortable: false }].concat(E.map(e => ({ label: GI.surnameOf(e.p.name || ''), align: 'right', sortable: false }))),
    styleRows.map(m => [{ html: '<span data-tip="' + esc(m[5]) + '" tabindex="0">' + esc(m[1]) + '</span>' }].concat(E.map(e => ({ html: GI.SP.fmt(m, GI.SP.value(e.p, e.id, m, cx), cx) })))))) : '';
  el.innerHTML = h + GI.card('Players', 'Ranked against ' + esc(peerTxt) + ' this season (' + S + ')', pick) +
    '<section class="qk-section" style="margin-top:var(--sp-8)">' + QK.sectionHead({ kicker: 'Side by side', title: esc(q), html: true,
      sub: E.length === 2 ? 'Bar length = percentile against the group, qualified players (100 = best). The better number in each row is solid.' : 'Value and percentile against the group, qualified players (100 = best). The best in each row is highlighted.' }) +
      GI.card(E.length + ' players, one metric set', 'The headline set for the role from our metrics spec: stable and predictive rates first',
      QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) +
      (small.length ? '<p class="qk-caption">' + esc(small.join(', ')) + (small.length > 1 ? ' are' : ' is') + ' below the qualifying minimum: no percentiles.</p>' : '') +
      (!same ? '<p class="qk-caption">Different groups: the rows are the ' + esc(g0.name.toLowerCase()) + ' set, and each percentile is against the player’s own group.</p>' : '') +
      (GI.SP.NOTE[g0.id] ? '<p class="qk-caption">' + esc(GI.SP.NOTE[g0.id]) + '</p>' : '')) + '</section>' + styleTbl +
    '<section class="qk-section">' + GI.card('Among peers', 'The qualified ' + esc(g0.peer.replace(/^NFL /, '')) + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + GI.chartBox('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
  wireV2(el, S, E, items);
  const keys = hl.filter(m => E.every(e => isNum(GI.SP.value(e.p, e.id, m, cx)))).slice(0, 4);
  const seg = el.querySelector('#cmp-dist-m');
  if (!keys.length) { GI.ch.none('cmp-dist', 'No metric all of them have.'); return; }
  if (!DSEL.key || !keys.some(m => m[0] === DSEL.key)) DSEL.key = keys[0][0];
  seg.innerHTML = keys.map(m => '<button type="button" aria-pressed="' + (m[0] === DSEL.key) + '" data-value="' + esc(m[0]) + '">' + esc(GI.shortLabel(m[1])) + '</button>').join('');
  const pool = GI.SP.members(cx, g0.id).filter(id => P[id].qualified !== false);
  const dd = key => {
    DSEL.key = key;
    const m = hl.find(x => x[0] === key);
    const vs = pool.map(id => GI.SP.value(P[id], id, m, cx)).filter(isNum).sort((a, b) => a - b);
    if (vs.length < 5) { GI.ch.none('cmp-dist', 'Too few qualified peers yet.'); return; }
    const n = document.getElementById('cmp-dist');
    if (!n) return;
    n.classList.remove('gi-chart-empty'); n.innerHTML = '';
    const cols = ['wpA', 'wpB', 'c5'];
    const c = QKC.distribution(n, { values: vs, binCount: 22, lowerBetter: !!m[3], fmt: v => GI.SP.fmt(m, v, cx), colorBy: 'flat', xName: m[1] + ' · ' + vs.length + ' qualified ' + g0.peer.replace(/^NFL /, ''), yName: 'Players',
      marks: E.map((e, i) => ({ x: GI.SP.value(e.p, e.id, m, cx), label: GI.surnameOf(e.p.name || ''), color: cols[i] })).filter(x => isNum(x.x)), label: 'Distribution of ' + m[1] });
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
  return GI.loadAll([GI.ypath('players.json', S), GI.ypath('value.json', S)]).then(res0 => {
    if (!el.isConnected) return;
    MODE = 'player';
    const cat0 = GI.catOf(res0[0]);
    if (cat0) GI.SP.ctx(cat0, GI.ok(res0[1]) ? res0[1] : null);
    compareV2(el, S, [params.a, params.b, params.c].filter(Boolean).map(String), cat0);
  });
});

})(window.GI);
