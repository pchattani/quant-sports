/* The Quant Rink — shared helpers for the redesigned pages (RK.ui), on The Quant kit (QK, QKC).
 *
 *   secHead(section, title, sub, tabs, active)   section heading + link tabs (?tab=<key>)
 *   section(el, opts) -> body element           the same, written into el
 *   legacy(name, el, params, state, query)      render a pre-redesign view (RK.view) inside a tab
 *   game(card) -> kit game object               GAME_CARD -> QK.matchCard / QK.tick shape
 *   team(abbr), tcol(abbr), teamEnt(abbr), playerEnt(pid, name, team)
 *   chart(el, h)                                a sized chart container
 *
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (RK) {
'use strict';

const U = RK.ui = {};
const esc = RK.esc, isNum = RK.isNum;

U.S = params => (params && params.season) || RK.state.season || RK.currentSeason();
U.cur = () => RK.currentSeason();
U.sq = S => (Number(S) !== Number(RK.currentSeason()) ? 's=' + S : '');

/* A section heading: kicker (league · season), title, sub-line, then link tabs. */
U.tabsHTML = (tabs, active) => {
  if (!tabs || !tabs.length) return '';
  return '<nav class="qk-tabs rk-tabs" aria-label="Views">' + tabs.map(t =>
    '<a class="qk-tab" href="' + esc(t.href) + '"' + (t.key === active ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + esc(t.label) + '</a>').join('') + '</nav>';
};
U.secHead = (section, title, sub, tabs, active, kicker) => {
  const S = RK.state.season || RK.currentSeason();
  const k = kicker !== undefined ? kicker : 'NHL · ' + RK.seasonLabel(S) + (Number(S) === Number(RK.currentSeason()) && RK.phaseLabel() ? ' · ' + RK.phaseLabel() : '');
  return '<header class="rk-head"><div>' + (k ? '<div class="qk-kicker">' + esc(k) + '</div>' : '') + '<h1>' + esc(title) + '</h1>' +
    (sub ? '<div class="qk-sub">' + sub + '</div>' : '') + '</div></header>' + U.tabsHTML(tabs, active);
};
/* Build tab specs for a section route: base '#/standings' (+ '/S' etc.), keys [[key, label]], extra query. */
U.tabs = (base, list, S, seasonInPath) => list.map(x => {
  const q = [];
  if (x[0] !== list[0][0]) q.push('tab=' + x[0]);
  if (!seasonInPath && S && Number(S) !== Number(RK.currentSeason()) && x[2] !== false) q.push('s=' + S);
  return { key: x[0], label: x[1], href: base + (q.length ? '?' + q.join('&') : '') };
});
U.section = (el, o) => {
  el.innerHTML = U.secHead(o.section, o.title, o.sub, o.tabs, o.active, o.kicker) + '<div class="rk-sub"></div>';
  return el.querySelector('.rk-sub');
};
/* Render a legacy view into `node` with the route params (query overridden by `query`). */
U.legacy = (name, node, params, state, query) => {
  const fn = RK.view(name);
  if (!fn) { node.innerHTML = QK.empty('Not available', 'This view did not load.'); return null; }
  const p = Object.assign({}, params, { query: Object.assign({}, (params && params.query) || {}, query || {}) });
  node.classList.add('rk-legacy');
  try { return fn(node, p, state); } catch (e) { console.error(e); node.innerHTML = '<div class="error-banner">This view could not be shown: ' + esc(e.message) + '</div>'; return null; }
};
U.tab = (params, keys, dflt) => {
  const t = ((params && params.query) || {}).tab;
  return keys.indexOf(t) >= 0 ? t : dflt;
};

/* ── teams and players ─────────────────────────────────────────────────── */
U.team = abbr => ({ name: RK.teamName(abbr), abbr: RK.teamAbbr(abbr), colour: RK.teamColourRaw(abbr), href: RK.teamHref(abbr) });
U.tcol = abbr => {
  const c = RK.teamColourRaw(abbr);
  return QK.color.parse(c) ? QK.color.team(c) : QK.cssVar('--c-other');
};
/* Two clubs' chart colours that can be told apart (kit rule QK.color.distinct: the second falls back to its alternate colour, then the win-probability orange). */
U.pair = (a, b) => {
  const ca = U.tcol(a); let cb = U.tcol(b);
  const ok = (x, y) => (QK.color.distinct ? QK.color.distinct(x, y) : QK.color.contrast(x, y) >= 1.6);
  if (!ok(ca, cb)) {
    const alt = RK.teamAlt(b);
    const alt2 = QK.color.parse(alt) ? QK.color.team(alt) : null;
    cb = alt2 && ok(ca, alt2) ? alt2 : QK.cssVar('--wp-b');
    if (!ok(ca, cb)) cb = QK.cssVar('--wp-a');
  }
  return [ca, cb];
};
U.teamEnt = (abbr, opts) => {
  const o = opts || {};
  if (!abbr) return '—';
  return '<a class="rk-ent" href="' + esc(RK.teamHref(abbr, o.season)) + '">' + QK.teamMark(U.team(abbr), 'sm') +
    '<span class="nm">' + esc(o.short ? RK.teamShort(abbr) : o.abbr ? RK.teamAbbr(abbr) : RK.teamName(abbr)) + '</span>' + (o.sub ? '<span class="sb">' + esc(o.sub) + '</span>' : '') + '</a>';
};
U.playerEnt = (pid, name, team, sub) => {
  const nm = name || RK.playerName(pid);
  return '<a class="rk-ent" href="' + esc(RK.playerHref(pid)) + '">' + (team ? QK.teamMark(U.team(team), 'sm') : '') +
    '<span class="nm">' + esc(nm) + '</span>' + (sub ? '<span class="sb">' + esc(sub) + '</span>' : '') + '</a>';
};
U.pos = p => (p ? '<span class="rk-pos">' + esc(p) + '</span>' : '');

/* ── games ─────────────────────────────────────────────────────────────── */
U.status = c => {
  const s = RK.gameState(c);
  return s === 'int' || s === 'live' ? 'live' : s === 'final' ? 'final' : 'pre';
};
U.game = (c, o) => {
  o = o || {};
  const st = U.status(c);
  const m = c.model || {}, mk = c.market || null;
  const pg = RK.parseGameId(c.game_id || c.id);
  const live = st === 'live';
  const p = live && isNum(c.wp_home) ? Number(c.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
  const note = c.so ? 'SO' : c.ot ? 'OT' : '';
  return {
    sport: 'hockey', id: c.game_id || c.id, start: c.start || c.date, status: st,
    league: pg && pg.playoff ? RK.roundName(pg.round) + (pg.game ? ' · Game ' + pg.game : '') : (o.league || 'NHL'),
    home: U.team(c.home), away: U.team(c.away), hs: isNum(c.hs) ? Number(c.hs) : null, as: isNum(c.as) ? Number(c.as) : null,
    p_home: p, market_home: mk && isNum(mk.p_home) ? Number(mk.p_home) : null, note: note,
    period: isNum(c.period) ? Number(c.period) : null, clock: c.clock, href: RK.gameHref(c.game_id || c.id),
    xg: c.xg && isNum(c.xg.away) && isNum(c.xg.home) && st !== 'pre' ? [Number(c.xg.away), Number(c.xg.home)] : null
  };
};
U.card = (c, o) => QK.matchCard(U.game(c, o), { sport: false });

/* ── charts and numbers ────────────────────────────────────────────────── */
U.chart = (id, h, label) => '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>';
U.f = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
U.pct = (p, d) => QK.fmt.pct(isNum(p) ? Number(p) : null, d);
U.signed = (v, d) => (isNum(v) ? (Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : '') + Math.abs(Number(v)).toFixed(d === undefined ? 1 : d) : '—');
U.cls = v => (isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : '');
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
U.load = (file, S) => RK.load((S || RK.state.season || RK.currentSeason()) + '/' + file);
U.alive = el => !!el && el.isConnected;
/* A league-wide ordinal: 3 -> "3rd". */
U.ord = n => RK.ordinal(n);
/* Days in the viewer's zone. */
U.dayKey = iso => RK.localDay(iso);

/* ── Design System 2.0 helpers (the pattern every sport follows; docs/_design/MIGRATION_V2.md) ─────────── */

/* The comparison metric set, defined once for the player card, the compare page and the percentile card:
   stable (year-to-year reliable) and predictive rates first, peer group = same position group (F / D / G) with the
   payload's sample floors (skaters.json / goalies.json "reference"). docs/METRICS_SPEC.md is the source of truth:
   change the set there first, then here. */
U.SK_SET = [
  ['Scoring', ['p60', 'p1_60', 'g60', 'ixg60_all', 'gax']],
  ['Play driving (5v5)', ['xgf_pct', 'xgf_pct_rel', 'cf_pct', 'xga60', 'rapm_off', 'rapm_def']],
  ['Value', ['gar', 'gar_ev_off', 'gar_ev_def', 'gar_pp']],
  ['Physical and more', ['hits60', 'blocks60', 'take60', 'pen_diff60', 'fo_pct', 'edge_max_speed']]
];
U.G_SET = [
  ['Results', ['gsax60', 'sv_pct', 'dfsv_pct', 'qs_pct', 'gaa']],
  ['By danger', ['sv_pct_low', 'sv_pct_med', 'sv_pct_high', 'gsax_high']],
  ['By situation', ['sv_pct_5v5', 'sv_pct_sh', 'reb_rate']]
];
U.GROUP_NAME = { F: 'NHL forwards', D: 'NHL defencemen', G: 'NHL goalies' };
/* Format a value by its catalogue metadata (glossary or payload "metrics" entry). */
U.fmtBy = (meta, v) => {
  if (!isNum(v)) return '—';
  const f = (meta || {}).fmt;
  if (f === 'pct') return U.pct(v, 1);
  if (f === 'toi_min') return RK.fmtTOI(v, { minutes: true });
  if (f === 'int') return String(Math.round(v));
  if (f === 'goals') return U.signed(v, 2);
  if (f === 'p60') return Number(v).toFixed(2);
  return RK.fmtVal ? RK.fmtVal(v, f || '2') : U.f(v, 2);
};
/* A metric catalogue as a map: payload.metrics -> { key: meta } */
U.metaMap = d => { const m = {}; ((d && d.metrics) || []).forEach(x => { if (x && x.key) m[x.key] = x; }); return m; };
/* The sample a metric's reliability is measured in, for one catalogue row (skaters.json / goalies.json player). */
U.sampleOf = (p, unit) => {
  const v = (p && p.values) || {};
  if (unit === 'minutes') return isNum(p.toi) ? p.toi : null;
  if (unit === '5v5 minutes') return isNum(v.toi5) ? v.toi5 : null;
  if (unit === 'shots') return isNum(v.sog) ? v.sog : null;
  if (unit === 'faceoffs') return isNum(v.fo_taken) ? v.fo_taken : null;
  if (unit === 'games') return isNum(p.gp) ? p.gp : null;
  if (unit === 'unblocked shots faced') return isNum(v.fa) ? v.fa : null;
  return null;
};
/* Percentile-card groups for one player from the catalogue: position-pool percentiles (pct_pos) when present.
   early = the sample is still short of where the metric stabilises (metrics[].stabilises_at). */
U.pctGroups = (p, meta, sets) => (sets || []).map(g => ({
  label: g[0],
  rows: g[1].map(k => {
    const m = meta[k] || {}, pc = ((p.pct_pos && isNum(p.pct_pos[k])) ? p.pct_pos : (p.pct || {}))[k];
    if (!isNum(pc) || m.unavailable) return null;
    const n = isNum(m.stabilises_at) ? U.sampleOf(p, m.unit) : null;
    return { label: m.label || k, pctl: pc, value: U.fmtBy(m, (p.values || {})[k]), tip: m.desc || '', early: isNum(n) && n < m.stabilises_at };
  }).filter(Boolean)
}));
U.sampleLine = (p, ref, goalie) => {
  if (!p) return '';
  const fl = (ref && ref.floors) || {};
  if (goalie) return p.gp + ' GP · ' + U.f(p.toi, 0) + ' min' + (isNum(fl.gp) ? ' · peers need ' + fl.gp + ' GP' : '');
  const v = p.values || {};
  return p.gp + ' GP · ' + U.f(p.toi, 0) + ' min · ' + U.f(v.toi5, 0) + ' at 5v5' + (isNum(fl.gp) ? ' · peers need ' + fl.gp + ' GP' : '');
};
/* A kit v2 game with records from the standings rows (team -> row). */
U.gameV2 = (c, o, rows) => {
  const g = U.game(c, o);
  const rec = t => { const r = rows && rows[t]; return r && isNum(r.w) ? r.w + '-' + r.l + '-' + (r.otl || 0) : ''; };
  g.home.record = rec(c.home); g.away.record = rec(c.away);
  return g;
};
U.gc = (c, o, rows) => QK.gameCard(U.gameV2(c, o, rows), { sport: false, marketLabel: 'Market', marketTip: 'The prediction-market or no-vig line probability for the home side, shown as a reference next to ours' });
U.head = o => QK.sectionHead(Object.assign({ kicker: 'NHL · ' + RK.seasonLabel(RK.state.season || RK.currentSeason()) }, o));

})(window.RK);
