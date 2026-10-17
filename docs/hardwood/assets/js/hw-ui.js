/* The Quant Hardwood — shared helpers for the redesigned pages (HW.ui), on The Quant kit (QK, QKC).
 *
 *   secHead(title, sub, tabs, active, kicker)    section heading + link tabs (?tab=<key>)
 *   section(el, opts) -> body element            the same, written into el
 *   tabs(L, sub, list, S, extra)                 tab specs for a section route
 *   legacy(name, el, params, state, query)       render a pre-redesign view (HW.view) inside a tab
 *   game(card, L) -> kit game object             GAME_CARD -> QK.matchCard / QK.tick shape
 *   team(L, tid), tcol(L, tid), pair(L, a, b), teamEnt(L, tid, o), playerEnt(L, pid, name, team, sub)
 *   chart(id, h, label)                          a sized chart container
 *   card2(title, sub, body, opts)                a kit card
 *
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const U = HW.ui = {};
const esc = HW.esc, isNum = HW.isNum;

U.L = params => (params && params.league) || HW.state.league;
U.S = params => (params && params.season) || HW.state.season || HW.currentSeason(U.L(params));
U.isCur = (L, S) => Number(S) === Number(HW.currentSeason(L));

/* ── section heading and link tabs ─────────────────────────────────────── */
U.tabsHTML = (tabs, active) => {
  if (!tabs || !tabs.length) return '';
  return '<nav class="qk-tabs hw-tabs" aria-label="Views">' + tabs.map(t =>
    '<a class="qk-tab" href="' + esc(t.href) + '"' + (t.key === active ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + esc(t.label) + '</a>').join('') + '</nav>';
};
U.kicker = (L, S) => {
  const ph = U.isCur(L, S) ? HW.phase(L) : null;
  const P = { preseason: 'Preseason', regular: 'Regular season', playin: 'Play-in', playoffs: 'Playoffs', offseason: 'Offseason' };
  return HW.leagueName(L) + ' · ' + HW.seasonLabel(L, S) + (ph ? ' · ' + (P[ph] || HW.titleCase(ph)) : '');
};
U.secHead = (title, sub, tabs, active, kicker) => '<header class="hw-head"><div>' + (kicker ? '<div class="qk-kicker">' + esc(kicker) + '</div>' : '') +
  '<h1>' + esc(title) + '</h1>' + (sub ? '<div class="qk-sub">' + sub + '</div>' : '') + '</div></header>' + U.tabsHTML(tabs, active);
/* Tab specs: base route 'standings' (league-relative), list [[key, label, keepSeason?]], extra query string. */
U.tabs = (L, sub, list, S, extra) => list.map(x => {
  const q = [];
  if (x[0] !== list[0][0]) q.push('tab=' + x[0]);
  if (S && !U.isCur(L, S) && x[2] !== false) q.push('s=' + S);
  if (extra) q.push(extra);
  return { key: x[0], label: x[1], href: '#/' + L + (sub ? '/' + sub : '') + (q.length ? '?' + q.join('&') : '') };
});
U.section = (el, o) => {
  el.innerHTML = U.secHead(o.title, o.sub, o.tabs, o.active, o.kicker) + '<div class="hw-sub"></div>';
  return el.querySelector('.hw-sub');
};
U.tab = (params, keys, dflt) => {
  const t = ((params && params.query) || {}).tab;
  return keys.indexOf(t) >= 0 ? t : dflt;
};
/* Render a legacy view into node with the route params (query merged with `query`). */
U.legacy = (name, node, params, state, query) => {
  const fn = HW.view(name);
  if (!fn) { node.innerHTML = QK.empty('Not available', 'This view did not load.'); return null; }
  const p = Object.assign({}, params, { query: Object.assign({}, (params && params.query) || {}, query || {}) });
  node.classList.add('hw-legacy');
  try { return fn(node, p, state || HW.state); } catch (e) { console.error(e); node.innerHTML = '<div class="error-banner">This view could not be shown: ' + esc(e.message) + '</div>'; return null; }
};

/* ── teams and players ─────────────────────────────────────────────────── */
U.team = (L, tid) => ({ name: HW.teamName(L, tid), abbr: HW.teamAbbr(L, tid), colour: HW.teamColourRaw(L, tid), href: HW.teamHref(L, tid) });
U.tcol = (L, tid) => {
  const c = HW.teamColourRaw(L, tid);
  return QK.color.parse(c) ? HW.teamColour(L, tid) : QK.cssVar('--c-other');
};
/* Two teams' chart colours that can be told apart (kit rule: the second falls back to the market orange). */
U.pair = (L, a, b) => {
  const ca = U.tcol(L, a); let cb = U.tcol(L, b);
  if (QK.color.contrast(ca, cb) < 1.6) {
    const alt = HW.teamAlt(L, b);
    const alt2 = QK.color.parse(alt) ? QK.color.team(alt) : null;
    cb = alt2 && QK.color.contrast(ca, alt2) >= 1.6 ? alt2 : QK.cssVar('--c-2');
    if (QK.color.contrast(ca, cb) < 1.6) cb = QK.cssVar('--c-1');
  }
  return [ca, cb];
};
U.teamEnt = (L, tid, opts) => {
  const o = opts || {};
  if (!tid) return '<span class="qk-muted">—</span>';
  return '<a class="hw-ent" href="' + esc(HW.teamHref(L, tid, o.season)) + '">' + QK.teamMark(U.team(L, tid), 'sm') +
    '<span class="nm">' + esc(o.short ? HW.teamShort(L, tid) : o.abbr ? HW.teamAbbr(L, tid) : HW.teamName(L, tid)) + '</span>' + (o.sub ? '<span class="sb">' + esc(o.sub) + '</span>' : '') + '</a>';
};
U.playerEnt = (L, pid, name, team, sub, S) => {
  const nm = name || HW.playerName(L, pid);
  return '<a class="hw-ent" href="' + esc(HW.playerHref(L, pid, S)) + '">' + (team ? QK.teamMark(U.team(L, team), 'sm') : '') +
    '<span class="nm">' + esc(nm) + '</span>' + (sub ? '<span class="sb">' + esc(sub) + '</span>' : '') + '</a>';
};
U.pos = p => (p ? '<span class="hw-pos">' + esc(p) + '</span>' : '');
U.ROLE = { G: 'Guards', W: 'Wings', B: 'Bigs' };
U.ROLE1 = { G: 'Guard', W: 'Wing', B: 'Big' };

/* ── games ─────────────────────────────────────────────────────────────── */
U.status = g => { const s = HW.gameState(g); return s === 'in' ? 'live' : s === 'post' ? 'final' : 'pre'; };
U.game = (g, L, o) => {
  o = o || {};
  const st = U.status(g);
  const m = g.model || {}, mk = g.market || null;
  const live = st === 'live';
  const p = live && isNum(g.wp_home) ? Number(g.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
  const tag = g.series && (g.series.summary || g.series.round) ? (g.series.summary || g.series.round) : (g.stype && g.stype !== 'reg' ? HW.stypeLabel(g.stype) : '');
  return {
    sport: 'basketball', id: g.id, start: g.date, status: st,
    league: HW.leagueName(L) + (tag ? ' · ' + tag : ''),
    home: U.team(L, g.home), away: U.team(L, g.away), hs: isNum(g.hs) ? Number(g.hs) : null, as: isNum(g.as) ? Number(g.as) : null,
    p_home: p, market_home: mk && isNum(mk.p_home) ? Number(mk.p_home) : null, note: st === 'final' && Number(g.period) > 4 ? 'OT' : '',
    period: isNum(g.period) ? Number(g.period) : null, clock: g.clock, href: HW.gameHref(L, g.id, o.season)
  };
};
U.card = (g, L, o) => QK.matchCard(U.game(g, L, o), { sport: false });

/* ── charts, numbers, cards ────────────────────────────────────────────── */
U.chart = (id, h, label) => '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>';
U.f = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
U.pct = (p, d) => QK.fmt.pct(isNum(p) ? Number(p) : null, d);
U.signed = (v, d) => (isNum(v) ? (Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : '') + Math.abs(Number(v)).toFixed(d === undefined ? 1 : d) : '—');
U.cls = v => (isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : '');
U.sgnHTML = (v, d) => '<span class="' + U.cls(v) + '">' + U.signed(v, d) + '</span>';
U.rowsOf = d => {
  if (!d || !Array.isArray(d.rows) || !Array.isArray(d.cols)) return [];
  return d.rows.map(r => { const o = {}; d.cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
};
U.card2 = (title, sub, body, opts) => {
  const o = opts || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-card-head"><div><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
U.empty = (t, s) => QK.empty(t, s);
U.alive = el => !!el && el.isConnected;
U.ok = d => !!d && d.ok !== false;
U.grade = g => (g ? '<span class="hw-grade" data-g="' + esc(String(g).charAt(0).toUpperCase()) + '">' + esc(g) + '</span>' : '—');
U.link = (href, text) => '<a class="hw-link" href="' + esc(href) + '">' + esc(text) + ' →</a>';
/* Seasons of a league that have a players catalogue with games: the season on screen, else the latest one before it. */
U.catalogue = (L, S) => HW.load(HW.path('players.json', L, S)).then(cat => {
  if (U.ok(cat) && Object.keys(cat.players || {}).length) return { cat: cat, S: S, fallback: false };
  const prev = HW.seasons(L).filter(x => x < S)[0];
  if (!prev) return { cat: cat, S: S, fallback: false };
  return HW.load(HW.path('players.json', L, prev)).then(c2 => (U.ok(c2) && Object.keys(c2.players || {}).length ? { cat: c2, S: prev, fallback: true } : { cat: cat, S: S, fallback: false }));
});
/* Minutes floor for leaderboards: the catalogue's own qualification floor, scaled to games played so far.
 * Rates (per game, per 100, percentages) need a real sample: at least ~40% of the leader's games at 15+ minutes. */
U.floor = (cat) => {
  const P = (cat && cat.players) || {};
  const gps = Object.keys(P).map(k => P[k].gp || 0);
  const maxGp = gps.length ? Math.max.apply(null, gps) : 0;
  const minF = isNum(cat && cat.min_floor) ? Number(cat.min_floor) : 0;
  const gpF = Math.max(1, Math.round(maxGp * 0.4));
  return { min: Math.max(minF, gpF * 15), gp: gpF, maxGp: maxGp };
};

})(window.HW);
