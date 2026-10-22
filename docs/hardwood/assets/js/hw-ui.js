/* The Quant Hardwood — shared helpers for the redesigned pages (HW.ui), on The Quant kit (QK, QKC).
 *
 *   secHead(title, sub, tabs, active, kicker)    section heading + link tabs (?tab=<key>)
 *   section(el, opts) -> body element            the same, written into el
 *   tabs(L, sub, list, S, extra)                 tab specs for a section route
 *   legacy(name, el, params, state, query)       render a pre-redesign view (HW.view) inside a tab
 *   game(card, L, o) -> kit game object          GAME_CARD -> QK.gameCard / QK.tick shape (o.records: tid -> 'W-L')
 *   card(card, L, o)                             a v2 game card; fresh(g) drops stale live/upcoming snapshots
 *   head(o)                                      a v2 section head inside a page
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
U.secHead = (title, sub, tabs, active, kicker, actions) => QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', size: 'lg', tag: 'h1', html: true, actions: actions || '', cls: 'hw-head2' }) + U.tabsHTML(tabs, active);
/* A section head inside a page (Design System 2.0): kicker, title, sub (HTML allowed), actions. */
U.head = o => QK.sectionHead(Object.assign({ html: true }, o, { title: esc(o.title) }));
/* Tab specs: base route 'standings' (league-relative), list [[key, label, keepSeason?]], extra query string. */
U.tabs = (L, sub, list, S, extra) => list.map(x => {
  const q = [];
  if (x[0] !== list[0][0]) q.push('tab=' + x[0]);
  if (S && !U.isCur(L, S) && x[2] !== false) q.push('s=' + S);
  if (extra) q.push(extra);
  return { key: x[0], label: x[1], href: '#/' + L + (sub ? '/' + sub : '') + (q.length ? '?' + q.join('&') : '') };
});
U.section = (el, o) => {
  el.innerHTML = U.secHead(o.title, o.sub, o.tabs, o.active, o.kicker, o.actions) + '<div class="hw-sub"></div>';
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
/* Two teams' chart colours that can be told apart (kit rule QK.color.distinct: the second falls back to its alternate
   colour, then the win-probability orange, then blue). */
U.pair = (L, a, b) => {
  const ca = U.tcol(L, a); let cb = U.tcol(L, b);
  const ok = (x, y) => (QK.color.distinct ? QK.color.distinct(x, y) : QK.color.contrast(x, y) >= 1.6);
  if (!ok(ca, cb)) {
    const alt = HW.teamAlt(L, b);
    const alt2 = QK.color.parse(alt) ? QK.color.team(alt) : null;
    cb = alt2 && ok(ca, alt2) ? alt2 : QK.cssVar('--wp-b');
    if (!ok(ca, cb)) cb = QK.cssVar('--wp-a');
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
/* Team catalogue keys never shown: the rating's own uncertainty is not a skill, and the market belongs on game and Model pages. */
U.HIDE_TEAM = { model_se: 1, title_edge: 1, p_title_market: 1 };

/* ── games ─────────────────────────────────────────────────────────────── */
U.status = g => { const s = HW.gameState(g); return s === 'in' ? 'live' : s === 'post' ? 'final' : 'pre'; };
/* A stale snapshot guard: a game still marked live or upcoming 12 hours after its start is dropped from live lists. */
U.fresh = g => {
  const st = U.status(g);
  if (st === 'final') return true;
  const t = Date.parse(g.date);
  return !isFinite(t) || Date.now() - t < 12 * 36e5;
};
/* Season records by team from a season payload's standings ({ tid: 'W-L' }). */
U.records = season => {
  const out = {}, st = (season && season.standings) || {};
  Object.keys(st).forEach(c => (st[c] || []).forEach(r => { if (r && isNum(r.w) && isNum(r.l) && (r.w || r.l)) out[String(r.team)] = r.w + '-' + r.l; }));
  return out;
};
U.game = (g, L, o) => {
  o = o || {};
  const st = U.status(g);
  const m = g.model || {}, mk = g.market || null;
  const live = st === 'live';
  const p = live && isNum(g.wp_home) ? Number(g.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
  const tag = g.series && (g.series.summary || g.series.round) ? (g.series.summary || g.series.round) : (g.stype && g.stype !== 'reg' ? HW.stypeLabel(g.stype) : '');
  const home = U.team(L, g.home), away = U.team(L, g.away);
  const rec = o.records || {};
  if (rec[String(g.home)]) home.record = rec[String(g.home)];
  if (rec[String(g.away)]) away.record = rec[String(g.away)];
  return {
    sport: 'basketball', id: g.id, start: g.date, status: st,
    league: (o.league || HW.leagueName(L)) + (tag ? ' · ' + tag : ''),
    home: home, away: away, hs: isNum(g.hs) ? Number(g.hs) : null, as: isNum(g.as) ? Number(g.as) : null,
    p_home: p, market_home: mk && isNum(mk.p_home) ? Number(mk.p_home) : null, note: st === 'final' && Number(g.period) > 4 ? 'OT' : '',
    period: isNum(g.period) ? Number(g.period) : null, clock: g.clock, href: HW.gameHref(L, g.id, o.season)
  };
};
/* A v2 game card: our chance first, the market a quiet ring and tick (named in the tip). */
U.card = (g, L, o) => QK.gameCard(U.game(g, L, o), { sport: false, marketLabel: 'Market', marketTip: 'The prediction-market or sportsbook probability for the home side (no vig), shown as a reference next to ours' });

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
/* Market source keys in words (kalshi, draftkings_ml, 'Draft Kings' -> Kalshi, DraftKings), for the quiet reference. */
U.srcName = x => { const k = String(x || '').toLowerCase().replace(/[^a-z]/g, ''); return k.indexOf('kalshi') === 0 ? 'Kalshi' : k.indexOf('polymarket') === 0 ? 'Polymarket' : k.indexOf('draftkings') === 0 ? 'DraftKings' : k.indexOf('fanduel') === 0 ? 'FanDuel' : k.indexOf('espn') === 0 ? 'ESPN' : String(x || ''); };
U.srcLabel = list => { const out = []; (list || []).forEach(x => { const n = U.srcName(x); if (n && out.indexOf(n) < 0) out.push(n); }); return out.length ? out.join(' / ') : 'no vig'; };
U.btnLink = (href, text) => '<a class="qk-btn" href="' + esc(href) + '">' + esc(text) + ' →</a>';
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


/* ── Design System 2.0: role peers and the one metric set (HW.ui.MSET in hw-metrics.js, from the metrics spec) ─── */
const SIGNED = { hpm: 1, hpm_o: 1, hpm_d: 1, ts_add: 1, pox100: 1, rapm: 1, box_impact: 1, on_off: 1 };
U.mMeta = k => { const m = ((U.MSET || {}).meta || {})[k]; return m ? { label: m[0], better: m[1], fmt: m[2], style: !!m[3], desc: m[4] } : { label: k, better: 'high', fmt: '2', style: false, desc: '' }; };
U.fmtM = (k, v) => (!isNum(v) ? '—' : SIGNED[k] ? U.signed(v, U.mMeta(k).fmt === '1' ? 1 : 2) : HW.fmtVal(v, U.mMeta(k).fmt));
/* Roles (G guards, W wings, B bigs) by player id from value.json (players.json carries `role` once rebuilt). */
U.roles = (L, S) => HW.load(HW.path('value.json', L, S)).then(v => { const m = {}; U.rowsOf(U.ok(v) ? v : null).forEach(r => { if (r.role) m[String(r.id)] = r.role; }); return m; });
U.roleOf = (p, pid, roles) => (p && p.role) || (roles && roles[String(pid)]) || null;
U.peerName = (L, r) => HW.leagueName(L) + ' ' + ((U.ROLE_NAME || {})[r] || 'players');
/* Percentile within the role among qualified players (100 = best, lower-is-better flipped): the payload's pct_role
 * where it exists, else computed here from players.json values (mid-rank, ties shared). */
U.rolePctl = (cat, roles, pid, k) => {
  const P = (cat && cat.players) || {}, p = P[pid];
  if (!p) return null;
  if (p.pct_role && isNum(p.pct_role[k])) return p.pct_role[k];
  const r = U.roleOf(p, pid, roles), v = (p.values || {})[k];
  if (!r || !isNum(v)) return null;
  const C = cat.__rp || (cat.__rp = {}), ck = r + '|' + k;
  if (!C[ck]) C[ck] = Object.keys(P).filter(id => P[id].qualified && U.roleOf(P[id], id, roles) === r && isNum((P[id].values || {})[k])).map(id => P[id].values[k]).sort((a, b) => a - b);
  const arr = C[ck];
  if (arr.length < 5) return null;
  let lo = 0, eq = 0;
  arr.forEach(x => { if (x < v) lo++; else if (x === v) eq++; });
  const pc = 100 * (lo + 0.5 * eq) / arr.length;
  return Math.round(U.mMeta(k).better === 'low' ? 100 - pc : pc);
};
/* The qualified peers of a role, for distributions and leaderboards. */
U.rolePeers = (cat, roles, r) => { const P = (cat && cat.players) || {}; return Object.keys(P).filter(id => P[id].qualified && U.roleOf(P[id], id, roles) === r).map(id => Object.assign({ id: id }, P[id])); };
/* Percentile-card groups for one player: the role's headline metrics in their groups, then the secondary ones. */
U.pctGroups = (L, cat, roles, pid, opts) => {
  const o = opts || {};
  const P = (cat && cat.players) || {}, p = P[pid];
  const r = U.roleOf(p, pid, roles), set = r && U.MSET ? U.MSET.roles[r] : null;
  if (!p || !set) return [];
  const m50 = ((U.MSET.m50 || {})[L] || {})[r] || {};
  const row = k => { const pc = U.rolePctl(cat, roles, pid, k); const m = U.mMeta(k);
    return isNum(pc) ? { label: m.label, pctl: pc, value: U.fmtM(k, (p.values || {})[k]), tip: m.desc, early: isNum(m50[k]) && isNum(p.min) && p.min < m50[k] } : null; };
  const out = set.groups.map(g => ({ label: g[0], rows: g[1].map(row).filter(Boolean) }));
  if (o.more !== false) out.push({ label: 'More', rows: set.more.map(row).filter(Boolean) });
  return out.filter(g => g.rows.length);
};
U.sampleLine = (L, cat, p) => (p ? (p.gp || 0) + ' GP · ' + Number(Math.round(p.min || 0)).toLocaleString('en-GB') + ' min' + (isNum(cat && cat.min_floor) ? ' · peers need ' + Number(cat.min_floor).toLocaleString('en-GB') + ' min' : '') : '');


/* ── Who moves next (<L>/movement.json; docs/_design/MOVES_VIEWS.md, US sports) ──────────────────────────── */
/* Follows `published`: a block that did not pass its held-out test shows the league base rate, labelled as such,
 * or nothing (arrivals, targets). */
U.movement = L => HW.load(HW.lpath('movement.json', L)).then(m => {
  if (!U.ok(m) || !Array.isArray(m.players) || !Array.isArray(m.player_fields)) return null;
  const by = {};
  m.players.forEach(r => { const o = {}; m.player_fields.forEach((k, i) => { o[k] = r[i]; }); by[String(o.pid)] = o; });
  return { m: m, by: by, pub: m.published || {} };
});
U.pctMv = p => (!isNum(p) ? '—' : p > 0 && p < 0.005 ? '<1%' : U.pct(p));
const MV_SHORT = { trade: 'Traded or claimed', release: 'Waived', other: 'Offseason move' };
const MV_COL = ['var(--c-1)', 'var(--c-3)', 'var(--c-5)', 'var(--c-6)'];
/* The chance of moving as a 0-100% bar split by how (types order), with the percentage. */
U.mvBar = (mv, row) => {
  const m = mv.m, p = row && row.p_next;
  if (!isNum(p)) return '<span class="qk-muted">—</span>';
  const segs = (m.types || []).map((t, i) => { const v = row['p_' + t]; return isNum(v) && v > 0 ? '<i style="width:' + (100 * v).toFixed(1) + '%;background:' + MV_COL[i % 4] + '" title="' + esc((MV_SHORT[t] || t) + ' ' + U.pctMv(v)) + '"></i>' : ''; }).join('');
  return '<span class="hw-mv"><span class="hw-mvbar" role="img" aria-label="' + esc('Chance of moving ' + U.pctMv(p)) + '">' + segs + '</span><b>' + U.pctMv(p) + '</b></span>';
};
U.mvKeys = mv => QK.keys((mv.m.types || []).map((t, i) => ({ name: MV_SHORT[t] || t, color: MV_COL[i % 4], kind: 'dot' }))) + (mv.pub.type ? '' : ' ' + QK.tag('base shares'));
U.mvHorizon = mv => 'by ' + String((mv.m.horizons || {}).next || 'next season');
/* The league line shown where a per-player block is not published (base rate, labelled). */
U.mvBaseLine = (mv, block) => {
  const m = mv.m, br = (m.base_rates || {})[block], rr = (m.recent_rates || {})[block];
  if (!isNum(br)) return '';
  const what = block === 'deadline' ? 'are ' + (m.deadline_label || 'traded or claimed') + ' before ' + HW.fmtDate(String((m.horizons || {}).deadline || ''), { weekday: false }) : 'leave their team ' + U.mvHorizon(mv);
  return '<p class="hw-mvline">' + QK.tag('base rate') + ' About ' + U.pct(br) + ' of rostered players ' + esc(what) + (isNum(rr) ? ' (last three seasons: ' + U.pct(rr) + ')' : '') + '.' +
    ((m.reasons || {})[block] ? ' <span class="hw-quiet" data-tip="' + esc(m.reasons[block]) + '" tabindex="0">Why a base rate?</span>' : '') + '</p>';
};

/* ── Similar players: the spec's weighted method (same role, qualified, z within league, role and season,
 * weighted Euclidean, k = 5); the payload's similar_role is used where it exists. ─────────────────────────── */
U.similarRole = (L, cat, roles, pid, k) => {
  const P = (cat && cat.players) || {}, p = P[pid];
  const r = U.roleOf(p, pid, roles);
  const sim = r && U.MSET && U.MSET.similar && (U.MSET.similar[L] || {})[r];
  if (!p || !sim) return [];
  const peers = U.rolePeers(cat, roles, r);
  if (peers.length < 6) return [];
  const stats = {};
  sim.features.forEach(f => {
    const v = peers.map(x => (x.values || {})[f]).filter(isNum);
    const mu = v.reduce((a, b) => a + b, 0) / (v.length || 1);
    const sd = Math.sqrt(v.reduce((a, b) => a + (b - mu) * (b - mu), 0) / Math.max(1, v.length - 1)) || 1;
    stats[f] = [mu, sd];
  });
  const z = (x, f) => { const v = (x.values || {})[f]; return isNum(v) ? (v - stats[f][0]) / stats[f][1] : null; };
  const me = {}; sim.features.forEach(f => { me[f] = z(p, f); });
  return peers.filter(x => x.id !== String(pid)).map(x => {
    let d = 0, w = 0;
    sim.features.forEach(f => { const a = me[f], b = z(x, f), wt = Math.max(0.2, (sim.weights || {})[f] || 0.2); if (isNum(a) && isNum(b)) { d += wt * (a - b) * (a - b); w += wt; } });
    return { id: x.id, name: x.name, team: x.team, d: w ? Math.sqrt(d / w) : null };
  }).filter(x => isNum(x.d)).sort((a, b) => a.d - b.d).slice(0, k || 5);
};

})(window.HW);
