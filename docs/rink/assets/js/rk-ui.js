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
/* v2: the kit's section head (Archivo title, kicker square, signal rule), large, as the page's h1; `sub` is HTML. */
U.secHead = (section, title, sub, tabs, active, kicker, actions) => {
  const S = RK.state.season || RK.currentSeason();
  const k = kicker !== undefined ? kicker : 'NHL · ' + RK.seasonLabel(S) + (Number(S) === Number(RK.currentSeason()) && RK.phaseLabel() ? ' · ' + RK.phaseLabel() : '');
  return QK.sectionHead({ kicker: k, title: esc(title), sub: sub || '', html: true, size: 'lg', tag: 'h1', cls: 'rk-head', actions: actions || '' }) + U.tabsHTML(tabs, active);
};
/* Build tab specs for a section route: base '#/standings' (+ '/S' etc.), keys [[key, label]], extra query. */
U.tabs = (base, list, S, seasonInPath) => list.map(x => {
  const q = [];
  if (x[0] !== list[0][0]) q.push('tab=' + x[0]);
  if (!seasonInPath && S && Number(S) !== Number(RK.currentSeason()) && x[2] !== false) q.push('s=' + S);
  return { key: x[0], label: x[1], href: base + (q.length ? '?' + q.join('&') : '') };
});
U.section = (el, o) => {
  el.innerHTML = U.secHead(o.section, o.title, o.sub, o.tabs, o.active, o.kicker, o.actions) + '<div class="rk-sub"></div>';
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
    p_home: p, market_home: mk && isNum(mk.p_home) ? Number(mk.p_home) : null, market_src: mk && mk.sources ? RK.srcLabel(mk.sources) : null, note: note,
    /* v3: live, the kit reads the live chance and keeps our pre-game call for "before the start we had ..." */
    p_pre: live && isNum(m.p_home) ? Number(m.p_home) : null, pre_only: live && !isNum(c.wp_home) ? true : undefined,
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
/* The headline sets of docs/METRICS_SPEC.md "Hockey" (docs/_design/metrics/hockey.json, 5fdf8870), in the spec's order,
   one per peer group: forwards (pct_pos v forwards), defencemen (pct_pos v defencemen), goalies (pct v qualified
   goalies). Each id carries the sample where the spec measured it to settle (M50: split-half or year-to-year r reaches
   0.5) and its unit; a player short of it is drawn dashed ("early"). Style and luck metrics (hits, blocks, faceoff %,
   PDO, shooting %) are kept off the cards by the spec. */
U.SPEC = {
  gar_60: { label: 'Rink value per 60', unit: 'GAR/60', tip: 'Goals above a replacement-level player per 60 minutes, from our value model (even-strength impact, power play, penalty kill, finishing, penalties).' },
  p60: { label: 'Points per 60', unit: 'per 60', tip: 'Goals plus assists per 60 minutes, all situations.' },
  ixg60_all: { label: 'Individual xG per 60', unit: 'per 60', tip: 'Expected goals from the player’s own shots per 60 minutes, all situations: how much scoring chance the player creates.' },
  icf60: { label: 'Shot attempts per 60 (5v5)', unit: 'per 60', tip: 'The player’s own shot attempts (on goal, missed or blocked) per 60 minutes at 5-on-5: the steadiest individual stat in hockey.' },
  adj_xgf_pct: { label: 'On-ice xG share (5v5)', unit: '%', tip: 'Share of 5-on-5 expected goals the team gets with the player on the ice, adjusted for score and venue.' },
  xgf60_rel: { label: 'xG for per 60, relative to team (5v5)', unit: 'per 60', tip: 'How many more expected goals per 60 the team creates at 5-on-5 with the player on the ice than without.' },
  rapm_net: { label: 'Isolated impact (RAPM)', unit: 'xG per 60', tip: 'The player’s 5-on-5 expected-goal differential per 60 after accounting for team-mates, opponents, zone starts and score.' },
  rapm_def: { label: 'Isolated defence (RAPM)', unit: 'xGA per 60 prevented', tip: 'Expected goals against per 60 the player prevents at 5-on-5 after accounting for team-mates, opponents, zone starts and score.' },
  rapm_off: { label: 'Isolated offence (RAPM)', unit: 'xGF per 60', tip: 'Expected goals for per 60 the player adds at 5-on-5 after accounting for team-mates, opponents, zone starts and score.' },
  adj_xga60: { label: 'On-ice xG against per 60 (5v5)', unit: 'per 60', lower: true, tip: 'Expected goals the team allows per 60 at 5-on-5 with the player on the ice, adjusted for score and venue (lower is better).' },
  pen_diff60: { label: 'Penalty differential per 60', unit: 'per 60', tip: 'Penalties drawn minus penalties taken per 60 minutes; each one is a power play for or against.' },
  toi_gp: { label: 'Ice time per game', unit: 'min', tip: 'Minutes per game in all situations: how much the coach trusts the player.' },
  gsax100: { label: 'Goals saved above expected per 100 shots', unit: 'per 100 unblocked attempts', tip: 'Goals stopped beyond what an average goalie would on the same shots (by our expected-goals model), per 100 unblocked shots faced.' },
  gsax: { label: 'Goals saved above expected', unit: 'goals', tip: 'Season total of goals saved beyond an average goalie facing the same shots.' },
  sv_pct: { label: 'Save percentage', unit: '%', tip: 'Saves per shot on goal, all situations.' },
  sv_pct_high: { label: 'High-danger save %', unit: '%', tip: 'Save rate on high-danger chances (expected-goal value 0.20 or more). Pure noise season to season: never rank a goalie on it alone.' },
  sv_pct_med: { label: 'Medium-danger save %', unit: '%', tip: 'Save rate on medium-danger chances (expected-goal value 0.08 to 0.20).' },
  sv_pct_low: { label: 'Low-danger save %', unit: '%', tip: 'Save rate on low-danger chances (expected-goal value under 0.08).' },
  qs_pct: { label: 'Quality start %', unit: '%', tip: 'Share of starts with a save percentage above league average (or .885 on 20 shots or fewer).' }
};
/* v3 (Matchday): a plain-English line under each metric on the percentile rail (QK.pctlBars r.sub). */
U.SUB = {
  gar_60: 'Goals added over a replacement-level player, per hour.',
  p60: 'Goals + assists for every hour on the ice.',
  ixg60_all: 'How good the player’s own shots are, whether or not they go in.',
  icf60: 'Shot attempts per hour at 5-on-5: the steadiest stat there is.',
  adj_xgf_pct: 'With the player on the ice, the team’s share of the chances.',
  xgf60_rel: 'Chances the team creates with the player on, against without.',
  rapm_net: 'The player’s own effect on chances, after team-mates and opponents.',
  rapm_def: 'The player’s own effect on chances against (higher is better).',
  rapm_off: 'The player’s own effect on chances for.',
  adj_xga60: 'Chances against with the player on the ice (lower is better).',
  pen_diff60: 'Penalties drawn minus taken, per hour.',
  toi_gp: 'Minutes a game: how much the coach trusts the player.',
  gsax100: 'Goals stopped beyond an average goalie, per 100 shots.',
  gsax: 'Season total of goals stopped beyond an average goalie.',
  sv_pct: 'Saves per shot on goal.',
  sv_pct_high: 'Saves on the most dangerous chances. Very noisy.',
  sv_pct_med: 'Saves on medium-danger chances.',
  sv_pct_low: 'Saves on the easier chances.',
  qs_pct: 'Starts with an above-average save percentage.'
};
/* The type a player's best metric suggests (compare verdicts). */
U.ARCHETYPE = { gar_60: 'The all-rounder', p60: 'The point machine', ixg60_all: 'The chance-getter', icf60: 'The volume shooter', adj_xgf_pct: 'The play-driver',
  xgf60_rel: 'The play-driver', rapm_net: 'The difference-maker', rapm_def: 'The defender', rapm_off: 'The creator', adj_xga60: 'The defender', pen_diff60: 'The penalty-drawer',
  toi_gp: 'The workhorse', gsax100: 'The shot-stopper', gsax: 'The shot-stopper', sv_pct: 'The steady one', qs_pct: 'The reliable starter' };
/* [group label, [[id, settles at, sample unit], ...]] */
U.SETS = {
  F: [['Value and scoring', [['gar_60', 722, 'minutes'], ['p60', 277, 'minutes'], ['ixg60_all', 224, 'minutes'], ['icf60', 109, '5v5 minutes']]],
    ['Play driving (5v5)', [['adj_xgf_pct', 803, '5v5 minutes'], ['xgf60_rel', 489, '5v5 minutes'], ['rapm_net', 228, '5v5 minutes']]],
    ['Discipline and trust', [['pen_diff60', 1052, 'minutes'], ['toi_gp', 1, 'games']]]],
  D: [['Value', [['gar_60', 1186, 'minutes']]],
    ['Play driving (5v5)', [['adj_xgf_pct', 1338, '5v5 minutes'], ['rapm_def', 315, '5v5 minutes'], ['rapm_off', 359, '5v5 minutes'], ['adj_xga60', 1295, '5v5 minutes']]],
    ['Scoring', [['p60', 426, 'minutes'], ['ixg60_all', 194, 'minutes']]],
    ['Discipline and trust', [['toi_gp', 1, 'games'], ['pen_diff60', 1333, 'minutes']]]],
  G: [['Shot stopping', [['gsax100', 7022, 'unblocked shots faced'], ['gsax', null, ''], ['sv_pct', 4234, 'unblocked shots faced']]],
    ['By danger', [['sv_pct_high', null, ''], ['sv_pct_med', null, ''], ['sv_pct_low', null, '']]],
    ['Starts', [['qs_pct', 288, 'games']]]]
};
/* Back-compatible names: the old single skater set is now the forwards' set. */
U.SK_SET = U.SETS.F.map(g => [g[0], g[1].map(x => x[0])]);
U.SK_SET_D = U.SETS.D.map(g => [g[0], g[1].map(x => x[0])]);
U.G_SET = U.SETS.G.map(g => [g[0], g[1].map(x => x[0])]);
U.setFor = group => (group === 'G' ? U.G_SET : group === 'D' ? U.SK_SET_D : U.SK_SET);
/* The team headline set (spec "Teams"): 32 clubs, 10 games for a percentile; gd_g derived as gf_g - ga_g. */
U.TEAM_SET = [['rating', 'Team rating', 'goals a game', 'Our team-strength model: expected goal differential per game against an average team, all situations.'],
  ['xgf_pct5', 'Expected-goal share (5v5)', '%', 'Share of 5-on-5 expected goals the team gets.'],
  ['cf_pct5', 'Shot-attempt share (5v5)', '%', 'Share of 5-on-5 shot attempts the team gets: puck possession.'],
  ['off5', '5v5 offence', 'xGF per 60', 'Expected goals created per 60 minutes at 5-on-5.'],
  ['def5', '5v5 defence', 'xGA per 60', 'Expected goals allowed per 60 minutes at 5-on-5 (lower is better).', true],
  ['pp', 'Power play', 'xGF per 60', 'Expected goals created per 60 minutes on the power play.'],
  ['pk', 'Penalty kill', 'xGA per 60', 'Expected goals allowed per 60 minutes short-handed (lower is better).', true],
  ['goalie', 'Goaltending', 'GSAx per 60', 'Goals the team’s goalies saved above expected per 60 minutes.'],
  ['gd_g', 'Goal differential per game', 'goals', 'Goals for minus goals against per game (shootout winners excluded).'],
  ['pts_pct', 'Points %', '%', 'Standings points taken as a share of the points available.']];
U.TEAM_MIN_GP = 10;
/* Where each team metric reaches r 0.5 (spec M50, games): a club short of it is drawn dashed. */
U.TEAM_SETTLE = { xgf_pct5: 13, cf_pct5: 7, off5: 17, def5: 17, pp: 28, pk: 52, goalie: 108, gd_g: 28, pts_pct: 34 };
/* The 32 clubs on the team set: { rows: [{ team, gp, v: {id: value}, p: {id: percentile} }], by: {abbr: row} }.
   tj = teams.json, sj = season.json. Percentiles only from U.TEAM_MIN_GP games (the spec's minimum). */
U.teamSet = (tj, sj) => {
  const st = {}; (((sj || {}).standings || {}).rows || []).forEach(r => { st[r.team] = r; });
  const T = (tj && tj.teams) || {};
  const rows = Object.keys(T).map(t => {
    const u = T[t].units || {}, s = st[t] || {}, rec = T[t].record || {};
    const v = { rating: isNum(u.rating) ? u.rating : s.rating, xgf_pct5: u.xgf_pct5, cf_pct5: u.cf_pct5, off5: u.off5, def5: u.def5, pp: u.pp, pk: u.pk, goalie: u.goalie,
      gd_g: isNum(u.gd_g) ? u.gd_g : (isNum(u.gf_g) && isNum(u.ga_g) ? u.gf_g - u.ga_g : null), pts_pct: s.p_pct };
    return { team: t, gp: isNum(s.gp) ? s.gp : (rec.gp || u.gp || 0), v: v, p: {} };
  });
  rows.forEach(r => {
    if (r.gp < U.TEAM_MIN_GP) return;
    U.TEAM_SET.forEach(m => { r.p[m[0]] = U.rankPct(rows.filter(x => x.gp >= U.TEAM_MIN_GP).map(x => x.v[m[0]]), r.v[m[0]], !!m[4]); });
  });
  const by = {}; rows.forEach(r => { by[r.team] = r; });
  return { rows: rows, by: by };
};
U.teamFmt = (k, v) => {
  if (!isNum(v)) return '—';
  if (k === 'xgf_pct5' || k === 'cf_pct5' || k === 'pts_pct') return U.pct(v, 1);
  if (k === 'rating' || k === 'gd_g' || k === 'goalie') return U.signed(v, 2);
  return Number(v).toFixed(2);
};
U.GROUP_NAME = { F: 'NHL forwards', D: 'NHL defencemen', G: 'NHL goalies' };
U.PEER_SHORT = { F: 'forwards', D: 'defencemen', G: 'goalies' };
/* Percentiles of one value among a list (100 = best; lower = true flips). */
U.rankPct = (list, v, lower) => {
  const xs = list.filter(isNum);
  if (!isNum(v) || xs.length < 2) return null;
  let below = 0, eq = 0;
  xs.forEach(x => { if (x < v) below++; else if (x === v) eq++; });
  const p = 100 * (below + 0.5 * eq) / xs.length;
  return lower ? 100 - p : p;
};
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
  if (unit === 'unblocked shots faced') return U.faOf(p);
  return null;
};
/* Unblocked shots a goalie faced: the payload's fa when present, else from GSAx and GSAx/100 (fa = 100 x GSAx / GSAx100),
   else shots on goal (a lower bound). */
U.faOf = p => {
  const v = (p && p.values) || {};
  if (isNum(v.fa)) return v.fa;
  if (isNum(v.gsax) && isNum(v.gsax100) && Math.abs(v.gsax100) > 1e-6 && Math.abs(v.gsax) > 0.05) return Math.round(100 * v.gsax / v.gsax100);
  return isNum(v.sa) ? v.sa : null;
};
/* Percentile-card groups for one player from the catalogue: position-pool percentiles (pct_pos) when present.
   early = the sample is still short of where the metric stabilises (metrics[].stabilises_at). */
/* sets: a U.SETS entry (ids with their settling sample) or the older [label, [ids]] lists. pcts: the percentile map
   to read (the player file's current.pct_pos, else the catalogue row's pct_pos, else pct). prev: last season's
   percentiles in the same peer group (the hollow ring on the v3 rail), or null. */
U.pctGroups = (p, meta, sets, pcts, prev) => {
  const src = pcts || (p.pct_pos && Object.keys(p.pct_pos).length ? p.pct_pos : (p.pct || {}));
  return (sets || []).map(g => ({
    label: g[0],
    rows: g[1].map(x => {
      const k = Array.isArray(x) ? x[0] : x, unit = Array.isArray(x) ? x[2] : '';
      const m = meta[k] || {}, sp = U.SPEC[k] || {}, pc = src[k];
      if (!isNum(pc) || m.unavailable) return null;
      const at = Array.isArray(x) && isNum(x[1]) ? x[1] : (isNum(m.stabilises_at) ? m.stabilises_at : null);
      const n = isNum(at) ? U.sampleOf(p, unit || m.unit) : null;
      const pv = prev && isNum(prev[k]) ? prev[k] : null;
      const ours = RK.ours ? RK.ours.of(k) : null;
      return { label: sp.label || m.label || k, sub: (U.SUB[k] || '') + (ours ? (U.SUB[k] ? ' · ' : '') + 'our model' : ''), pctl: pc, prev: pv, value: U.fmtBy(m, (p.values || {})[k]), tip: (sp.tip || m.desc || '') + (ours ? ' Our model: ' + ours.name + '.' : '') + (isNum(at) && unit ? ' Settles at about ' + QK.fmt.num(at) + ' ' + unit + '.' : ''), early: isNum(n) && n < at };
    }).filter(Boolean)
  }));
};
U.sampleLine = (p, ref, goalie) => {
  if (!p) return '';
  const fl = (ref && ref.floors) || {};
  const v = p.values || {};
  if (goalie) return p.gp + ' GP · ' + U.f(p.toi, 0) + ' min' + (isNum(U.faOf(p)) ? ' · about ' + QK.fmt.num(U.faOf(p)) + ' unblocked shots faced' : '') + ' · peers: a quarter of the team’s minutes and ' + (isNum(fl.fa) ? fl.fa : 100) + ' shots';
  return p.gp + ' GP · ' + U.f(p.toi, 0) + ' min · ' + U.f(v.toi5, 0) + ' at 5v5 · peers: 250 5v5 min a full season, prorated' + (isNum(fl.gp) ? ', ' + fl.gp + '+ GP' : '');
};
/* The goalie card's honesty line (spec: show that one season is a small sample). */
U.goalieNote = p => {
  const fa = U.faOf(p);
  return 'One season is a small sample for a goalie: goals saved above expected per 100 shots settles at about 7,000 unblocked shots, roughly four seasons' + (isNum(fa) ? '; this goalie has faced about ' + QK.fmt.num(fa) + '.' : '.');
};

/* ── who moves next (movement.json; docs/_design/MOVES_VIEWS.md, US sports) ───────────────────────────────── */
/* Loads <S>/movement.json and indexes it: { d, rows (objects), byPid, teams, types, labels, pub }. null when missing. */
U.moves = S => RK.loadYear('movement.json', S).then(d => {
  if (!d || d.ok === false || !Array.isArray(d.players) || !Array.isArray(d.player_fields)) return null;
  const f = d.player_fields;
  const rows = d.players.map(r => { const o = {}; f.forEach((k, i) => { o[k] = r[i]; }); return o; });
  const byPid = {}; rows.forEach(r => { byPid[String(r.pid)] = r; });
  return { d: d, rows: rows, byPid: byPid, teams: d.teams || {}, types: d.types || [], labels: d.type_labels || {}, pub: d.published || {}, horizon: (d.horizons || {}).next || 'next season' };
});
const MV_COL = ['var(--c-1)', 'var(--c-4)', 'var(--c-other)', 'var(--c-6)'];
/* A 0-100% bar of p_next split by type (league base shares when the type model is not published), with the number. */
U.moveBar = (r, M) => {
  if (!r || !isNum(r.p_next)) return '<span class="qk-muted" data-tip="Not enough recent games for an estimate">—</span>';
  const segs = M.types.map((t, i) => { const v = r['p_' + t]; return isNum(v) && v > 0 ? '<span style="width:' + (100 * v).toFixed(1) + '%;background:' + MV_COL[i % MV_COL.length] + '"></span>' : ''; }).join('');
  return '<span class="rk-mv" role="img" aria-label="' + esc('Chance of not being in the lineup next season: ' + U.pct(r.p_next)) + '"><span class="rk-mv-t">' + segs + '</span><b>' + (r.p_next < 0.01 ? '<1%' : U.pct(r.p_next)) + '</b></span>';
};
U.moveKeys = M => QK.keys(M.types.map((t, i) => ({ name: M.labels[t] || t, color: MV_COL[i % MV_COL.length], kind: 'dot' }))) + (M.pub.type ? '' : ' ' + QK.tag('base shares') + '<span class="qk-muted rk-mv-note"> the split is the league’s shares, not the player’s</span>');
U.MOVE_HEAD = 'Chance of not being in the lineup next season';
U.moveTip = M => 'By ' + M.horizon + '. It includes a season in the minors. ' + (((M.d.notes || [])[0]) || '');
U.deadlineLine = M => {
  const d = M.d, br = (d.base_rates || {}).deadline;
  if (M.pub.deadline || !isNum(br)) return '';
  const dl = (d.horizons || {}).deadline;
  return '<p class="rk-note rk-mv-line">About <b>' + U.pct(br) + '</b> of players are ' + esc(d.deadline_label || 'traded or claimed') + ' before ' + (dl ? esc(RK.fmtDate(dl, { weekday: false })) + ((d.horizons || {}).deadline_estimated ? ' (estimated deadline)' : '') : 'the deadline') +
    ' ' + QK.tag('base rate') + ' <span class="rk-info" data-tip="' + esc((d.reasons || {}).deadline || '') + '" tabindex="0">ⓘ</span></p>';
};
/* A kit v2 game with records from the standings rows (team -> row). */
U.gameV2 = (c, o, rows) => {
  const g = U.game(c, o);
  const rec = t => { const r = rows && rows[t]; return r && isNum(r.w) ? r.w + '-' + r.l + '-' + (r.otl || 0) : ''; };
  g.home.record = rec(c.home); g.away.record = rec(c.away);
  return g;
};
/* Round 6: the market sits quietly under our chance (market: 'quiet', before the start only, the source on hover);
   `why` adds the italic one-line reason (QK.whyLine). */
U.gc = (c, o, rows, why) => QK.gameCard(U.gameV2(c, o, rows), { sport: false, market: 'quiet', why: why === undefined ? false : why });
U.head = o => QK.sectionHead(Object.assign({ kicker: 'NHL · ' + RK.seasonLabel(RK.state.season || RK.currentSeason()) }, o));

})(window.RK);
