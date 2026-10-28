/* The Quant Footballer — Lab (#/lab) and Compare (#/compare).
 *
 *   #/lab[/<all|club|intl|comp>/<F|M|D|G|O>][?w=season|last|365|ytd&x=&y=&size=&color=&min=&preset=&shrink=0&adj=0&q=
 *        &within=pos&pos=GK|CB|FB|DM-CM|AM-W|ST]
 *        the player lab: any two metrics against each other for one position group, one dot per player over every
 *        competition, club football, national-team football or one competition, this season, last season or a
 *        calendar window; presets, size and colour encodings, medians, labelled extremes, a highlight search and the
 *        group ranked on the view (data/lab/<window>/<scope>.json, UNIFIED_PAYLOADS 14). Our model metrics (GAR/90 and
 *        GAR from the player value model, value_fields.py) lead every picker as "Our models", then the metrics spec's
 *        headline set for the position, then the box score by group; names and explanations come from the spec
 *        (QK.spec, assets/qk/metrics/football.labels.json) and our metrics carry the cobalt "Our model" tag.
 *        "Compare within" (QK.within): Broad (the default) is the position letters, goalkeepers or outfield players by
 *        line; Position is the spec's formation-role peer groups (GK, CB, FB/WB, DM/CM, AM/W, ST, on the rows' `role`),
 *        and the scatter, ranks, percentiles, medians, metric order, minimum (the spec's floor: 450 minutes, goalkeepers
 *        900) and the "Most like" suggestions all follow the group. Position mode opens on the spec group's default
 *        view (QK.within.view, football.json `view`): what makes a player in the role good against their attacking or
 *        on-the-ball output, coloured by value added (GAR/90); the pickers and presets lead with the view's three sets,
 *        the ranked table adds the view's value column and "Most like" uses the view's metrics. Explicit x / y in the
 *        address still win; Broad is unchanged
 *   #/compare/players/<a>/<b>[?p3=<c>&view=classic&scope=]
 *        two or three players side by side (kit v4: two draw the tale of the tape, three the table): QK.compareView on the one metric set the player card
 *        uses (FB.PLAYER_SETS, players.js), percentiles against the shared position group, and where each one sits in
 *        that group's distribution; ?view=classic keeps the full pre-redesign comparison ("Every metric (classic)").
 *        A key is a person id, or the old <comp>:<id>
 *   #/compare/clubs/<a>/<b>     two clubs side by side: our chance if they met, the tale of the tape, style and every
 *        team metric; a key is a club id, or the old <comp>:<club-slug>
 *
 * Compare reads people/<pid>.json and clubs/<tid>.json (only ids in the indexes), the chosen competition's
 * players_live.json, shots.json, table/probs/strength/team_stats/analytics/fixtures (only files it writes) and
 * pool.json for the pooled model's chances. Older-browser rule: no optional chaining, no nullish coalescing. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, pct = FB.pct, signed = FB.signed;

function subnav(active) {
  return FB.subnav([['#/scout', 'Scouting Room', 'lab'], ['#/scout?view=chart', 'Chart', 'chart'], ['#/compare/players/_', 'Compare players', 'players'], ['#/clubs/h2h', 'Teams head to head', 'clubs']], active, 'Compare views');
}
function mean(a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : 0; }
function stats(a) { var n = a.length; if (!n) return { m: 0, s: 1 }; var m = mean(a); var v = a.reduce(function (x, y) { return x + (y - m) * (y - m); }, 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { var lo = 0, hi = sorted.length; while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } var up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }
function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }

// ══════════════════════════════════════════════════════════════════════ the lab

var POS = { F: 'Forwards', M: 'Midfielders', D: 'Defenders', G: 'Goalkeepers', O: 'All outfield players' };
var PRESETS = {
  F: [['npxg_xa_90', 'gar90', 'Value added against attacking output'], ['npxg_90', 'xa_90', 'Threat: scoring against creating'], ['shots_90', 'xg_per_shot', 'Shot volume against shot quality'], ['npxg_90', 'finishing', 'Chances against finishing'],
    ['xg_per_shot', 'placement', 'Chance quality against shot placement'], ['dribbles_90', 'dribble_pct', 'Dribbling: volume against success'], ['touches_90', 'loss_per_100', 'Involvement against ball security'],
    ['npxg_xa_90', 'def_actions_90', 'Output against work off the ball']],
  M: [['prog_actions_90', 'gar90', 'Value added against progression'], ['xa_90', 'key_passes_90', 'Creation: quality against volume'], ['prog_actions_90', 'opp_half_passes_90', 'Progression: carrying against passing'], ['passes_90', 'pass_pct', 'Passing volume against security'],
    ['padj_tkl_int_90', 'ball_wins_90', 'Ball winning'], ['npxg_xa_90', 'padj_tkl_int_90', 'Two-way midfielders'], ['shot_creation_90', 'xa_per_kp', 'Creation volume against chance quality']],
  D: [['padj_tkl_int_90', 'gar90', 'Value added against defending'], ['padj_tkl_int_90', 'duel_pct', 'Defending: activity against success'], ['aerials_90', 'aerial_pct', 'Aerial presence against dominance'], ['long_balls_90', 'long_ball_pct', 'Long distribution'],
    ['prog_actions_90', 'passes_90', 'Ball-playing defenders'], ['clearances_90', 'blocks_90', 'Defending the box'], ['crosses_90', 'xa_90', 'Attacking full-backs']],
  G: [['goals_prevented_90', 'gar90', 'Value added against shot stopping'], ['save_pct', 'goals_prevented_90', 'Shot stopping'], ['sweeper_90', 'high_claims_90', 'Command of the area'], ['passes_90', 'long_ball_pct', 'Distribution']],
  O: [['rating', 'gar90', 'Value added against match rating'], ['npxg_xa_90', 'padj_tkl_int_90', 'Attacking output against defending'], ['prog_actions_90', 'shot_creation_90', 'Progression against chance creation'], ['duels_90', 'duel_pct', 'Duels: volume against success']]
};
var EXTRA_ADJ = ['npxg_xa_90', 'ga_90', 'shot_creation_90'];
var WIN_ORDER = ['season', 'last', '365', 'ytd'];
var SHRINK_K = 450;
var LAB = null, MU = {}, IX = null;
var S = null;

/* Our model metrics on the lab rows (value_fields.py appends role, gar90 and gar), in the order they lead the
   pickers. Names and explanations come from the metrics spec when it has them (QK.spec); these are the fallbacks. */
var OURS = [
  { key: 'gar90', label: 'Value added (GAR/90)', fmt: '2', tip: 'Goals of expected goal difference a player adds per 90 minutes over a replacement-level player in the same role, from our player value model (box score plus match rating).' },
  { key: 'gar', label: 'Goals above replacement (GAR)', fmt: '1', tip: 'Goals of expected goal difference a player adds over a replacement-level player in the same role in these minutes: GAR/90 times minutes over 90.' }
];
var NO_SHRINK = { gar: 1 };
/* The spec's headline metrics for the lab's position letters (its groups are formation roles). */
var POS_GROUPS = { F: ['st', 'am_w'], M: ['dm_cm', 'am_w'], D: ['cb', 'fb'], G: ['gk'], O: ['cb', 'fb', 'dm_cm', 'am_w', 'st'] };
/* "Compare within: Position": the spec's formation-role peer groups (football.json groups; display, codes and minimum
   from the labels file when it has them): [address code, spec group, display, role codes, letter, minimum minutes]. */
var ROLES = [['GK', 'gk', 'Goalkeepers', ['GK'], 'G', 900], ['CB', 'cb', 'Centre-backs', ['CB'], 'D', 450], ['FB', 'fb', 'Full-backs and wing-backs', ['FB'], 'D', 450],
  ['DM-CM', 'dm_cm', 'Defensive and central midfielders', ['DM', 'CM'], 'M', 450], ['AM-W', 'am_w', 'Attacking midfielders and wingers', ['AM', 'W'], 'F', 450], ['ST', 'st', 'Strikers', ['ST'], 'F', 450]];
var ROLE_CODES = ROLES.map(function (g) { return g[0]; });
var LETTER_ROLE = { G: 'GK', D: 'CB', M: 'DM-CM', F: 'ST', O: 'CB' };
var ROLE_PRESETS = {
  GK: PRESETS.G,
  CB: PRESETS.D.filter(function (p) { return p[0] !== 'crosses_90'; }),
  FB: [['crosses_90', 'xa_90', 'Attacking full-backs: crossing against chance creation'], ['padj_tkl_int_90', 'gar90', 'Value added against defending'], ['prog_actions_90', 'opp_half_passes_90', 'Progression: carrying against passing'],
    ['npxg_xa_90', 'padj_tkl_int_90', 'Two-way full-backs: attacking output against defending'], ['padj_tkl_int_90', 'duel_pct', 'Defending: activity against success'], ['key_passes_90', 'crosses_90', 'Creation: key passes against crosses']],
  'DM-CM': PRESETS.M,
  'AM-W': [['npxg_xa_90', 'gar90', 'Value added against attacking output'], ['npxg_90', 'xa_90', 'Threat: scoring against creating'], ['dribbles_90', 'dribble_pct', 'Dribbling: volume against success'],
    ['shot_creation_90', 'xa_per_kp', 'Creation volume against chance quality'], ['xa_90', 'key_passes_90', 'Creation: quality against volume'], ['npxg_xa_90', 'def_actions_90', 'Output against work off the ball']],
  ST: PRESETS.F
};
function byPos() { return S && S.within === 'pos'; }
/* the current role group: { code, id, name, codes, letter, min } (the spec's display, codes and minimum when loaded) */
function roleGroup(code) {
  var r = ROLES.filter(function (g) { return g[0] === code; })[0] || ROLES[1];
  var sg = SPEC && SPEC.group ? SPEC.group(r[1]) : null;
  return { code: r[0], id: r[1], name: (sg && sg.display) || r[2], codes: (sg && sg.codes && sg.codes.length) ? sg.codes : r[3], letter: r[4],
    min: sg && sg.min && isNum(sg.min.value) ? sg.min.value : r[5] };
}
function groupNoun() { return byPos() ? roleGroup(S.role).name.toLowerCase() : POS[S.pos].toLowerCase(); }
function curPresets() { return byPos() ? ROLE_PRESETS[S.role] : PRESETS[S.pos]; }
var SPEC = null;
function specLoad() {
  if (SPEC || !QK.spec || !QK.spec.load) return Promise.resolve(SPEC);
  return QK.spec.load('football').then(function (c) { SPEC = c; return c; }, function () { return null; });
}
/* The spec's display name, with "/90" or "%" where the spec keeps the unit apart from the name. */
function specLabel(key, fallback) {
  var m = SPEC ? SPEC.metric(key, 'player') : null;
  if (!m || !m.label || m.label === key) return fallback;
  var l = m.label;
  if (/^per 90$/.test(m.unit || '') && !/90/.test(l)) l += ' /90';
  return l;
}
function specTip(key, fallback) { return SPEC ? SPEC.tip(key, 'player', fallback) : (fallback || ''); }
/* the spec's one-line explanation alone (the strip names the model itself) */
function specExplain(key, fallback) { var m = SPEC ? SPEC.metric(key, 'player') : null; return m && m.explain ? m.explain : (fallback || ''); }
function oursOf(key) {
  if (SPEC) { var o = SPEC.ours(key); if (o) return o; }
  return OURS.some(function (m) { return m.key === key; }) ? { name: 'Player value model', about: '' } : null;
}
function oursTag(key) { var o = oursOf(key); return o ? QK.ours({ model: o.name, about: o.about }) : ''; }
function headlineFor(pos) {
  var out = {}, n = 0;
  (byPos() ? [roleGroup(S.role).id] : (POS_GROUPS[pos] || [])).forEach(function (g) { (SPEC ? SPEC.headline(g) : []).forEach(function (k) { if (out[k] === undefined) out[k] = n++; }); });
  return out;
}
FB.labOurs = { oursOf: oursOf, tag: oursTag, label: specLabel, tip: specTip, explain: specExplain, load: specLoad, metrics: OURS };

/* One view of data/lab/ (one row per person) with the index's catalogue. */
function prep(ix, view) {
  var meta = {};
  var ours = OURS.filter(function (m) { return view.idx[m.key] !== undefined; }).map(function (m) {
    return { key: m.key, label: specLabel(m.key, m.label), group: 'Our models', fmt: m.fmt, scope: 'all', ours: true, desc: specTip(m.key, m.tip) };
  });
  var cat = ours.concat((ix.metrics || []).map(function (m) {
    var c = {}, k;
    for (k in m) if (Object.prototype.hasOwnProperty.call(m, k)) c[k] = m[k];
    c.label = specLabel(m.key, m.label);
    c.desc = specTip(m.key, m.desc || '');
    return c;
  }));
  cat.forEach(function (m) { meta[m.key] = m; });
  meta.minutes = { key: 'minutes', label: 'Minutes', fmt: 'int' };
  meta.age = { key: 'age', label: 'Age', fmt: 'int' };
  var adj = {};
  (ix.adjusted_keys || []).concat(EXTRA_ADJ).forEach(function (k) { adj[k] = 1; });
  var win = (ix.windows || []).filter(function (w) { return w.key === view.window; })[0] || null;
  return { idx: view.idx, meta: meta, metrics: cat, comps: ix.comps || {}, adj: adj, rows: view.rows, floor: view.floor, window: win, scope: view.scope, updated_at: ix.updated_at };
}
function loadView(win, scope) {
  return Promise.all([FB.labIndex(), specLoad()]).then(function (arr) {
    var ix = arr[0];
    if (!ix || !ix.scopes) return null;
    IX = ix;
    var have = ix.scopes[win] || {};
    if (!have[scope]) scope = have.all ? 'all' : Object.keys(have)[0];
    if (!scope) return null;
    return FB.labView(win, scope).then(function (v) { return v ? prep(ix, v) : null; });
  });
}
function single() { return !FB.LAB_SCOPES[S.scope]; }
function adjOn() { return S.adj && !single(); }
function rawV(r, key) {
  var i = LAB.idx[key];
  if (i === undefined) return null;
  var v = r[i];
  if (v === null || v === undefined) return null;
  if (adjOn() && LAB.adj[key]) v = v * (r[LAB.idx.factor] || 1);
  return v;
}
function val(r, key) {
  var v = rawV(r, key);
  if (v === null || !S.shrink || key === 'minutes' || key === 'age' || NO_SHRINK[key] || MU[key] === undefined) return v;
  var m = r[LAB.idx.minutes] || 0;
  return (m * v + SHRINK_K * MU[key]) / (m + SHRINK_K);
}
function label(key) {
  var m = LAB.meta[key] || {}, t = [];
  if (adjOn() && LAB.adj[key]) t.push('adj.');
  if (S.shrink && key !== 'minutes' && key !== 'age' && !NO_SHRINK[key]) t.push('shrunk');
  return (m.label || key) + (t.length ? ' (' + t.join(', ') + ')' : '');
}
function lower(key) { return !!(LAB.meta[key] || {}).lower; }
function fmtK(key, v) { return FB.fmtMetric(v, (LAB.meta[key] || {}).fmt || '2'); }
/* The default minimum: the view's floor (30% of what its regulars have played), at most 450 when it mixes competitions
   whose seasons are at different points (a European 2026/27 weeks old beside a Brazilian 2026 near its end). */
function defMin() {
  var f = LAB.floor || 90, m = Math.max(90, single() ? f : Math.min(f, 450));
  return byPos() ? Math.max(m, roleGroup(S.role).min) : m;
}
function inGroup(r) {
  var I = LAB.idx;
  if (byPos()) return I.role !== undefined && roleGroup(S.role).codes.indexOf(r[I.role]) >= 0;
  var p = r[I.position];
  return S.pos === 'O' ? !(p === 'G' || !p) : p === S.pos;
}
function pool() {
  var I = LAB.idx;
  return LAB.rows.filter(function (r) { return inGroup(r) && (r[I.minutes] || 0) >= S.min; });
}
function isGkView() { return byPos() ? S.role === 'GK' : S.pos === 'G'; }
/* The position's presets that this view can draw (an older payload without GAR drops the value presets). Position mode
   leads with the view's presets ([x, y, title, colour, true]: the default, excellence and attacking each against value,
   excellence against a second excellence metric); the role's own pairs follow, without repeats. */
function presets() {
  var own = curPresets().filter(function (pp) { return !LAB || (LAB.idx[pp[0]] !== undefined && LAB.idx[pp[1]] !== undefined); });
  var v = posView();
  if (!v) return own;
  var vp = QK.within.viewPresets(v, function (k) { return (LAB.meta[k] || {}).label || k; }).map(function (p) { return [p.x, p.y, p.label, p.color, true]; });
  return vp.concat(own.filter(function (pp) { return !vp.some(function (q) { return q[0] === pp[0] && q[1] === pp[1]; }); }));
}
function applyPreset() {
  if (S.preset < 0) return;
  var ps = presets();
  var p = ps[S.preset] || ps[0] || curPresets()[0];
  S.x = p[0]; S.y = p[1];
  // a view preset carries its colour; the "against value" ones fall back to the default colour rather than repeat an axis
  if (p[4]) { if (p[3]) S.color = p[3]; else if (S.color === p[0] || S.color === p[1]) S.color = S.defColor; }
}
/* the metrics this view's pickers offer (goalkeeping metrics only for goalkeepers, outfield ones only for the rest) */
function offered(m) { return isGkView() ? m.scope !== 'out' : m.scope !== 'gk'; }
/* The Position default view (QK.within.view on the spec group's `view`; spec ids are the lab's keys, and ids the lab does
   not carry yet, prog_dist_90 and on_npxgd_90, drop out). has(id): the pickers offer the metric and at least VIEW_SHARE
   of the group on screen has a value (the whole role when fewer than 3 clear the minimum), so a default never opens on
   an empty chart; the kit then falls back to the next metric of the same set. */
var VIEW_SHARE = 0.3;
function posView() {
  if (!byPos() || !LAB || !SPEC || !SPEC.group) return null;
  var g = SPEC.group(roleGroup(S.role).id);
  if (!g || !g.view) return null;
  var rows = pool();
  if (rows.length < 3) rows = LAB.rows.filter(inGroup);
  var memo = {};
  var has = function (id) {
    if (memo[id] !== undefined) return memo[id];
    var m = LAB.meta[id];
    if (!m || LAB.idx[id] === undefined || id === 'minutes' || id === 'age' || !offered(m)) return (memo[id] = false);
    if (!rows.length) return (memo[id] = true);
    var i = LAB.idx[id], n = 0;
    rows.forEach(function (r) { if (r[i] !== null && r[i] !== undefined) n++; });
    return (memo[id] = n / rows.length >= VIEW_SHARE);
  };
  return QK.within.view(g, has);
}
/* entering Position, another role, or ?within=pos without axes: the view's x, y and colour (preset 0) */
function applyView() {
  var v = posView();
  S.preset = 0;
  if (!v || !v.x || !v.y) { S.viewColor = null; applyPreset(); return; }
  S.x = v.x; S.y = v.y;
  if (v.color) S.color = v.color;
  S.viewColor = v.color || null;
}
/* the ranked table's value column in Position mode: the view's colour metric, else its first aggregate, never X or Y */
function valueKey(v) {
  if (!v) return '';
  return [v.color].concat(v.sets[2].ids).filter(function (k) { return k && LAB.idx[k] !== undefined && k !== S.x && k !== S.y; })[0] || '';
}
/* v (Position mode): the X, Y and Colour pickers lead with the view's three sets under the view's labels (our metrics
   marked "ours"), then the colour groupings, then the lab's grouping of the rest. */
function metricOpts(scope, v) {
  var groups = {}, order = [], head = headlineFor(S.pos), heads = [], lead = [];
  var ms = LAB.metrics;
  if (v && scope !== 'size') {
    var vo = QK.within.viewOrder(v, ms.filter(offered), function (m) { return m.key; });
    lead = vo.sets.map(function (st) { return { group: st.label, items: st.items.map(function (m) { return [m.key, m.label + (oursOf(m.key) ? ' · ours' : '')]; }) }; });
    var used = {};
    vo.sets.forEach(function (st) { st.items.forEach(function (m) { used[m.key] = 1; }); });
    ms = ms.filter(function (m) { return !used[m.key]; });
  }
  ms.forEach(function (m) {
    if (isGkView() ? m.scope === 'out' : m.scope === 'gk') return;
    if (!m.ours && head[m.key] !== undefined) { heads.push(m); return; }
    var g = m.ours ? 'Our models' : 'Box score · ' + m.group;
    if (!groups[g]) { groups[g] = []; order.push(g); }
    groups[g].push([m.key, m.label]);
  });
  if (heads.length) {
    groups['Box score · key numbers'] = heads.sort(function (a, b) { return head[a.key] - head[b.key]; }).map(function (m) { return [m.key, m.label]; });
    order.splice(groups['Our models'] ? 1 : 0, 0, 'Box score · key numbers');
  }
  var out = lead.slice();
  if (scope === 'size') out.push(['minutes', 'Minutes played'], ['', 'Same size']);
  if (scope === 'color') { if (lead.length) out.push({ group: 'Groups', items: [['comp', 'Main competition'], ['team', 'Club'], ['', 'One colour']] }); else out.push(['comp', 'Main competition'], ['team', 'Club'], ['', 'One colour']); }
  order.forEach(function (g) { out.push({ group: g, items: groups[g] }); });
  if (!scope) out.push({ group: 'Profile', items: [['age', 'Age'], ['minutes', 'Minutes']] });
  return out;
}
function winOpts() {
  var ws = (IX && IX.windows) || [];
  return WIN_ORDER.filter(function (k) { return ws.some(function (w) { return w.key === k; }) && (IX.scopes || {})[k]; }).map(function (k) {
    var w = ws.filter(function (x) { return x.key === k; })[0];
    return [k, k === 'season' ? 'This season' : w.label];
  });
}

/* State <-> hash: scope and position in the path (#/lab/<all|club|intl|slug>/<pos>, the old per-competition links
   included), the rest in the query. */
function stateFromRoute(p) {
  var q = p.query || {};
  var st = { win: WIN_ORDER.indexOf(q.w) >= 0 ? q.w : 'season', scope: p.comp || 'all', pos: POS[p.pos] ? p.pos : (POS[q.pos] ? q.pos : 'F'),
    min: isNum(q.min) ? Number(q.min) : null, adj: q.adj !== '0', shrink: q.shrink !== '0', preset: isNum(q.preset) ? Number(q.preset) : 0,
    x: q.x || '', y: q.y || '', size: q.size === 'none' ? '' : (q.size || 'minutes'), color: q.color === undefined ? null : (q.color === 'none' ? '' : q.color), q: q.q || '',
    colorSet: q.color !== undefined };
  if (st.x && st.y && q.preset === undefined) st.preset = -1;
  // Position mode opens on the role's view unless the address names both axes (a preset or colour in it still counts)
  st.openView = !(st.x && st.y);
  var w = QK.within.read(q, ROLE_CODES);
  st.within = w.within;
  st.role = ROLE_CODES.indexOf(q.pos) >= 0 ? q.pos : LETTER_ROLE[st.pos];
  return st;
}
/* the colour the address leaves out: the view's in Position mode (a reload re-applies it), else the default */
function defColorNow() { return byPos() && S.viewColor ? S.viewColor : S.defColor; }
/* The Lab mounted inside the Scouting Room (FB.lab.mount): no page head, the room owns the address (onState), and a
   dot opens the room's profile drawer (onPick). null when the Lab is its own page. */
var EMBED = null;
function writeHash() {
  if (EMBED) {
    if (EMBED.onState) EMBED.onState({ w: S.win, c: S.scope, pos: S.pos, within: S.within, role: S.role, x: S.preset < 0 ? S.x : '', y: S.preset < 0 ? S.y : '', preset: S.preset > 0 ? S.preset : '',
      color: S.color === defColorNow() ? '' : (S.color || 'none'), size: S.size === 'minutes' ? '' : (S.size || 'none'), min: S.min === defMin() ? '' : S.min, q: S.q || '' });
    return;
  }
  var q = { w: S.win === 'season' ? null : S.win, min: S.min === defMin() ? null : S.min, preset: S.preset >= 0 ? (S.preset ? S.preset : null) : null,
    x: S.preset < 0 ? S.x : null, y: S.preset < 0 ? S.y : null, size: S.size === 'minutes' ? null : (S.size || 'none'), color: S.color === defColorNow() ? null : (S.color || 'none'),
    shrink: S.shrink ? null : '0', adj: S.adj ? null : '0', q: S.q || null };
  var wq = QK.within.query({ within: S.within, pos: S.role });
  q.within = wq.within; q.pos = wq.pos;
  FB.setHashQuiet('#/lab/' + (S.scope || 'all') + '/' + S.pos + FB.qs(q));
}

FB.route('lab', function (el, p) {
  EMBED = null;
  S = stateFromRoute(p);
  el.innerHTML = FB.pageHead('Lab', 'Player lab', 'Chart any two player metrics for one position group: broad (goalkeepers, or outfield players by line) or a formation role (centre-backs, full-backs, strikers ...). Every player is one dot: matches in the season or window, across every competition, club football only, national-team football only, or one competition. Presets pick the pairs that separate styles of player; medians split the chart into quadrants. Position opens on what makes a player in that role good, their attacking or on-the-ball output, and their overall value.') +
    subnav('lab') + labBody();
  return show(el, true);
});
/* The Lab inside the Scouting Room's Chart view (scout-room.js): o = { comp (scope), pos (letter), query (w, x, y,
   color, size, min, preset, q, within, pos role), onState(state) (the room writes its address), onPick(pid) (a dot or a
   name opens the profile drawer) }. Renders into el; returns a Promise. */
FB.lab = { mount: function (el, o) {
  o = o || {};
  EMBED = { onState: o.onState || null, onPick: o.onPick || null };
  S = stateFromRoute({ comp: o.comp, pos: o.pos, query: o.query || {} });
  el.innerHTML = labBody();
  return show(el, true);
} };
function labBody() {
  return '<section class="qk-card fb-lb-ctl"><div class="qk-card-body" id="lb-ctl">' + FB.loading('lines', 3) + '</div></section>' +
    '<div id="lb-cover"></div>' +
    FB.card('<span id="lb-title">The chart</span>', '<span id="lb-sub"></span>', FB.chartBox('lb-chart', 640, 'Player lab scatter') + '<div id="lb-sim" class="fb-lb-sim"></div><p class="fb-cap" id="lb-note"></p>', { id: 'lb-chart-card' }) +
    '<div id="lb-ours" class="fb-mt"></div>' +
    QK.explain('<b>What’s that number?</b> Every dot is one player, and the top-right corner is better than the middle of the group on both axes. <b>Shrink small samples</b> pulls a player with few minutes towards the group’s middle, so a hot few hundred minutes does not top the chart; <b>league-adjust</b> multiplies attacking rates by the scoring factor of the leagues they came from.', { cls: 'fb-mt' }) +
    FB.card('Ranked on this view', 'The group ranked by the sum of standard scores on both axes (better direction); percentiles within the group (Broad or Position, as chosen above) shown, and in Position mode the role’s value column with its percentile. Top 60. A standard score is how many spreads above the group’s average a number sits: +1 is better than about five in six.', '<div id="lb-table"></div>', { flush: true, cls: 'fb-mt' });
}

function show(el, first) {
  return loadView(S.win, S.scope).then(function (lab) {
    if (!FB.alive(el)) return;
    if (!lab) { FB.set('lb-ctl', FB.empty('This view is not built yet', 'The lab payloads (data/lab/) are written by the next build.')); FB.set('lb-chart', ''); return; }
    LAB = lab;
    S.scope = lab.scope;
    if (!isNum(S.min) || !first) S.min = defMin();
    S.defColor = single() ? 'rating' : 'comp';
    if (S.color === null || (S.color && S.color !== 'comp' && S.color !== 'team' && LAB.idx[S.color] === undefined)) S.color = S.defColor;
    if (single() && S.color === 'comp') S.color = 'rating';
    if (S.size && S.size !== 'minutes' && LAB.idx[S.size] === undefined) S.size = 'minutes';
    if (first && byPos() && S.openView) {
      // ?within=pos&pos=.. without both axes: the role's view (preset 0, or the preset the address names), its colour
      // unless the address names one, and an axis the address names over the view's
      var c0 = S.color, qp = S.preset, qx = S.x, qy = S.y, keepC = S.colorSet;
      applyView();
      if (qp > 0) { S.preset = qp; applyPreset(); }
      if (keepC) S.color = c0;
      if (qx && LAB.idx[qx] !== undefined && qx !== S.y) { S.x = qx; S.preset = -1; }
      if (qy && LAB.idx[qy] !== undefined && qy !== S.x) { S.y = qy; S.preset = -1; }
    }
    if (!S.x || !S.y || LAB.idx[S.x] === undefined || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
    controls(el);
    draw(el);
  });
}

function controls(el) {
  var rg = byPos() ? roleGroup(S.role) : null, v = posView(), ps = presets();
  // the window, competitions or minimum can change the list: keep the selected preset only while it names the axes on screen
  if (S.preset >= 0 && (!ps[S.preset] || ps[S.preset][0] !== S.x || ps[S.preset][1] !== S.y)) {
    S.preset = -1;
    ps.forEach(function (pp, i) { if (S.preset < 0 && pp[0] === S.x && pp[1] === S.y) S.preset = i; });
  }
  var pOpt = function (pp, i) { return [String(i), pp[2]]; };
  var nv = ps.filter(function (pp) { return pp[4]; }).length;
  var presetOpts = nv ? [{ group: 'Position view · ' + groupNoun(), items: ps.slice(0, nv).map(pOpt) }, { group: 'More pairs', items: ps.slice(nv).map(function (pp, i) { return pOpt(pp, i + nv); }) }]
    : ps.map(pOpt);
  var html = QK.within.html({ within: S.within, pos: S.role }, { id: 'lb-wn', cls: 'fb-lb-within', groups: ROLES.map(function (g) { return [g[0], roleGroup(g[0]).name]; }),
    note: rg ? 'Opens on what makes a player in the role good, their attacking or on-the-ball output, and their overall value · formation role (the one started in most) · minimum ' + FB.int(rg.min) + ' minutes (the metrics spec)' : 'Goalkeepers, or outfield players by line' }) +
    QK.within.viewWhy(v) + FB.toolbar([
    FB.field('Season', FB.select('lb-win', winOpts(), S.win, 'Season or window')),
    FB.field('Competitions', FB.select('lb-comp', FB.labScopeOptions(IX, S.win), S.scope, 'Which competitions count', 'fb-pl-wide')),
    byPos() ? '' : FB.field('Position', FB.select('lb-pos', Object.keys(POS).map(function (k) { return [k, POS[k]]; }), S.pos, 'Position')),
    FB.field('Chart', FB.select('lb-preset', presetOpts.concat([['-1', 'Custom axes']]), String(S.preset), 'Preset')),
    FB.field('Min. minutes', '<span class="fb-lb-range"><input type="range" id="lb-min" min="90" max="2000" step="30" value="' + S.min + '" aria-label="Minimum minutes"><b class="fb-num" id="lb-min-v">' + S.min + '\'</b></span>')
  ]) + FB.toolbar([
    FB.field('X axis', FB.select('lb-x', metricOpts('', v), S.x, 'X axis')),
    '<button type="button" class="qk-btn fb-lb-swap" id="lb-swap" title="Swap the axes" aria-label="Swap the axes">⇄</button>',
    FB.field('Y axis', FB.select('lb-y', metricOpts('', v), S.y, 'Y axis')),
    FB.field('Size', FB.select('lb-size', metricOpts('size'), S.size, 'Marker size')),
    FB.field('Colour', FB.select('lb-color', metricOpts('color', v), S.color, 'Marker colour')),
    FB.field('Highlight', '<input class="qk-input" id="lb-q" type="search" placeholder="A player…" value="' + esc(S.q) + '" autocomplete="off">')
  ], 'fb-mt') + '<div class="fb-lb-checks">' +
    '<label class="fb-check"><input type="checkbox" id="lb-shrink"' + (S.shrink ? ' checked' : '') + '> Shrink small samples</label>' +
    '<label class="fb-check" id="lb-adj-wrap"' + (single() ? ' hidden' : '') + '><input type="checkbox" id="lb-adj"' + (S.adj ? ' checked' : '') + '> League-adjust attacking rates</label></div>';
  FB.set('lb-ctl', html);
  var $ = function (id) { return el.querySelector('#' + id); };
  $('lb-win').onchange = function (e) { S.win = e.target.value; show(el, false); };
  $('lb-comp').onchange = function (e) {
    S.scope = e.target.value;
    if (!single() && S.color === 'rating') S.color = 'comp';
    show(el, false);
  };
  if ($('lb-pos')) $('lb-pos').onchange = function (e) { S.pos = e.target.value; S.preset = 0; applyPreset(); controls(el); draw(el); };
  QK.within.wire(el, { within: S.within, pos: S.role }, function (w) {
    /* Broad -> Position: the last role if it is on this line, else the line's main role; the path letter follows the
       role, so going back to Broad lands on the role's line */
    if (w.within === 'pos' && S.within !== 'pos' && roleGroup(S.role).letter !== S.pos) w.pos = LETTER_ROLE[S.pos];
    var leaving = w.within !== 'pos' && S.within === 'pos';
    S.within = w.within; S.role = w.pos;
    if (S.within === 'pos') S.pos = roleGroup(S.role).letter;
    S.min = defMin();
    // Position (entered, or another role): the role's view; back to Broad: the line's first preset, and the view's colour
    // handed back to the default
    if (S.within === 'pos') applyView();
    else { S.preset = 0; applyPreset(); if (leaving && S.viewColor && S.color === S.viewColor) S.color = S.defColor; S.viewColor = null; }
    controls(el); draw(el);
  }, { id: 'lb-wn' });
  $('lb-preset').onchange = function (e) { S.preset = parseInt(e.target.value, 10); applyPreset(); controls(el); draw(el); };
  $('lb-x').onchange = function (e) { S.x = e.target.value; S.preset = -1; controls(el); draw(el); };
  $('lb-y').onchange = function (e) { S.y = e.target.value; S.preset = -1; controls(el); draw(el); };
  $('lb-size').onchange = function (e) { S.size = e.target.value; draw(el); };
  $('lb-color').onchange = function (e) { S.color = e.target.value; draw(el); };
  $('lb-min').oninput = function (e) { S.min = parseInt(e.target.value, 10); $('lb-min-v').textContent = S.min + '\''; };
  $('lb-min').onchange = function () { draw(el); };
  $('lb-shrink').onchange = function (e) { S.shrink = e.target.checked; draw(el); };
  $('lb-adj').onchange = function (e) { S.adj = e.target.checked; draw(el); };
  $('lb-swap').onclick = function () { var t = S.x; S.x = S.y; S.y = t; S.preset = -1; controls(el); draw(el); };
  var timer = null;
  $('lb-q').oninput = function (e) { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(function () { if (FB.alive(el)) draw(el); }, 250); };
}

/* The cobalt strip under the chart when an axis, the size or the colour is one of our model metrics: what it is,
   from the spec, and which value-model window this view reads (value_fields.py). */
function oursNote() {
  var keys = [S.y, S.x, S.size, S.color].filter(function (k, i, a) { return k && a.indexOf(k) === i && oursOf(k) && LAB.idx[k] !== undefined; });
  if (!keys.length) return '';
  var w = S.win, one = single();
  var src = w === 'season' ? (one ? 'this season’s line in ' + esc(FB.labScopeName(S.scope, IX)) : 'this season’s lines in ' + esc(FB.labScopeName(S.scope, IX).toLowerCase()) + ', added up (GAR/90 is total GAR over total minutes)')
    : w === 'last' ? 'last season’s lines' + (one ? ' in ' + esc(FB.labScopeName(S.scope, IX)) : ', added up')
    : 'the value model’s last 12 months (the nearest window it keeps)';
  return QK.oursExplain(keys.map(function (k) { return '<b>' + esc(label(k)) + '.</b> ' + esc(specExplain(k, (OURS.filter(function (m) { return m.key === k; })[0] || {}).tip)); }).join(' ') +
    ' In this view it reads ' + src + '. GAR is on one scale across competitions, so it is never league-adjusted. <a href="#/value">Value leaderboard →</a> · <a href="#/model/glossary/gar">Glossary →</a>',
    { title: 'Our model.' });
}

function draw(el) {
  if (!FB.alive(el)) return;
  var I = LAB.idx;
  var base0 = pool(), v = posView(), vk = valueKey(v);
  MU = {};
  [S.x, S.y, S.size, S.color, vk].forEach(function (k) {
    if (k && I[k] !== undefined && k !== 'minutes' && k !== 'age') {
      var a = base0.map(function (r) { return rawV(r, k); }).filter(function (v) { return v !== null; });
      if (a.length) MU[k] = FB.median(a);
    }
  });
  var rows = base0.filter(function (r) { return val(r, S.x) !== null && val(r, S.y) !== null; });
  var scopeName = FB.labScopeName(S.scope, IX);
  var W = LAB.window;
  FB.set('lb-title', esc(label(S.y)) + oursTag(S.y) + ' against ' + esc(label(S.x)) + oursTag(S.x));
  FB.set('lb-ours', oursNote());
  FB.set('lb-sub', FB.int(rows.length) + ' ' + esc(groupNoun()) + ' · ' + esc(single() ? scopeName : scopeName.toLowerCase()) + ' · ' + esc(FB.labWindowText(W)) + ' · ' + S.min + '+ minutes · one dot per player');
  if (W && W.start) {
    var present = {};
    rows.forEach(function (r) { present[r[I.comp]] = 1; });
    var late = Object.keys(LAB.comps).filter(function (k) { return present[k] && LAB.comps[k].first_detail && LAB.comps[k].first_detail > W.start; })
      .sort(function (a, b) { return LAB.comps[b].first_detail.localeCompare(LAB.comps[a].first_detail); });
    FB.set('lb-cover', late.length ? FB.note('<span>Match detail does not yet reach back to ' + esc(W.start) + ' for ' + late.slice(0, 6).map(function (k) { return '<b>' + esc(LAB.comps[k].name) + '</b> (from ' + esc(LAB.comps[k].first_detail) + ')'; }).join(', ') + (late.length > 6 ? ' and ' + (late.length - 6) + ' more' : '') +
      '. Players from those competitions are measured on less of the window than the rest; the hourly backfill is filling last season in, newest first. <a href="#/model/coverage">Data coverage →</a></span>') : '');
  } else FB.set('lb-cover', '');
  writeHash();
  var box = el.querySelector('#lb-chart');
  if (rows.length < 3) {
    if (box.__qkc) { try { box.__qkc.chart.dispose(); } catch (e) { /* gone */ } box.__qkc = null; }
    box.innerHTML = FB.empty('Too few players', 'Lower the minutes or widen the competitions' + (byPos() ? ', or compare within the broad group.' : '.'));
    FB.set('lb-table', ''); FB.set('lb-note', ''); FB.set('lb-sim', '');
    return;
  }
  var xs = rows.map(function (r) { return val(r, S.x); }), ys = rows.map(function (r) { return val(r, S.y); });
  var mx = FB.median(xs), my = FB.median(ys), sx = stats(xs), sy = stats(ys);
  var dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  var ranked = rows.map(function (r) { return { r: r, z: dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s }; }).sort(function (a, b) { return b.z - a.z; });
  var q = norm(S.q.trim());
  var hits = q ? rows.filter(function (r) { return norm(r[I.name]).indexOf(q) >= 0; }) : [];
  var labelled = {};
  ranked.slice(0, 12).forEach(function (o) { labelled[o.r[I.player_id]] = 1; });
  hits.forEach(function (r) { labelled[r[I.player_id]] = 1; });
  var sortedX = xs.slice().sort(function (a, b) { return a - b; }), sortedY = ys.slice().sort(function (a, b) { return a - b; });
  var pxOf = function (v) { var pp = pctRank(sortedX, v); return dirx > 0 ? pp : 100 - pp; };
  var pyOf = function (v) { var pp = pctRank(sortedY, v); return diry > 0 ? pp : 100 - pp; };

  var sizeVal = function (r) { return S.size === 'minutes' ? r[I.minutes] : val(r, S.size); };
  var sv = S.size ? rows.map(sizeVal).filter(isNum) : [];
  var slo = sv.length ? Math.min.apply(null, sv) : 0, shi = sv.length ? Math.max.apply(null, sv) : 1;
  var sizeOf = function (r) { if (!S.size) return 9; var x = sizeVal(r); return !isNum(x) ? 5 : 6 + 16 * (shi > slo ? (x - slo) / (shi - slo) : 0.5); };
  var groupKey = S.color === 'comp' ? function (r) { return r[I.comp]; } : S.color === 'team' ? function (r) { return r[I.team]; } : null;
  var continuous = !groupKey && !!S.color && I[S.color] !== undefined;
  var groups = [];
  if (groupKey) {
    var counts = {};
    rows.forEach(function (r) { var k = groupKey(r); counts[k] = (counts[k] || 0) + 1; });
    var top = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; }).slice(0, 7);
    top.forEach(function (k) { groups.push({ name: S.color === 'comp' ? ((LAB.comps[k] || {}).name || k) : k, rows: rows.filter(function (r) { return groupKey(r) === k; }) }); });
    var rest = rows.filter(function (r) { return top.indexOf(groupKey(r)) < 0; });
    if (rest.length) groups.push({ name: 'Others', rows: rest, other: true });
  } else groups.push({ name: continuous ? label(S.color) : 'Players', rows: rows });
  var cv = continuous ? rows.map(function (r) { return val(r, S.color); }).filter(isNum) : [];
  var clo = cv.length ? Math.min.apply(null, cv) : 0, chi = cv.length ? Math.max.apply(null, cv) : 1;
  // Position mode: a metric colour is drawn on the kit's percentile scale within the group on screen (better = higher)
  var cpct = continuous && byPos(), sortedC = cpct ? cv.slice().sort(function (a, b) { return a - b; }) : [];
  var cpOf = function (x) { if (!isNum(x)) return null; var pp = pctRank(sortedC, x); return lower(S.color) ? 100 - pp : pp; };
  var cOf = function (r) { return continuous ? (cpct ? cpOf(val(r, S.color)) : val(r, S.color)) : null; };
  var personQ = single() ? { c: S.scope } : S.scope === 'club' ? { scope: 'club' } : S.scope === 'intl' ? { scope: 'intl' } : null;
  var href = function (r) { return FB.href.player(r[I.player_id], personQ); };
  var compLabel = function (r) { return r[I.mix] || ((LAB.comps[r[I.comp]] || {}).name || r[I.comp]) + ' · ' + r[I.minutes] + '\''; };

  QKC.mount(box, function (T) {
    var series = groups.map(function (g, gi) {
      var c = g.other ? T.other : T.cat[gi % 8];
      return {
        type: 'scatter', name: g.name, large: false, itemStyle: continuous ? undefined : { color: c },
        symbolSize: function (v, prm) { return prm.data.sz; },
        data: g.rows.map(function (r) {
          return { value: [val(r, S.x), val(r, S.y), cOf(r)], name: r[I.name], href: href(r), r: r, sz: sizeOf(r),
            itemStyle: continuous ? { borderColor: T.s1, borderWidth: 0.6, opacity: 0.85 } : { color: QKC.hexA(c, 0.72), borderColor: T.s1, borderWidth: 0.6 },
            label: { show: !!labelled[r[I.player_id]], formatter: FB.surname(r[I.name]), position: 'top', color: T.ink1, fontSize: 10.5, fontWeight: 600, fontFamily: T.fontUI } };
        }),
        labelLayout: { hideOverlap: true },
        emphasis: { scale: 1.5, label: { show: true } },
        markLine: gi === 0 ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4], width: 1 }, label: { show: false }, data: [{ xAxis: mx }, { yAxis: my }] } : undefined
      };
    });
    if (hits.length) series.push({ type: 'scatter', name: 'Search', symbol: 'circle', z: 10, symbolSize: 20,
      itemStyle: { color: 'transparent', borderColor: T.brand, borderWidth: 2.5 },
      data: hits.map(function (r) { return { value: [val(r, S.x), val(r, S.y)], name: r[I.name], href: href(r), r: r }; }),
      label: { show: true, formatter: function (prm) { return prm.name; }, position: 'right', color: T.brand, fontWeight: 700, fontSize: 11 } });
    var xa = QKC.axis(T, { name: label(S.x), nameLocation: 'middle', nameGap: 30, scale: true, inverse: lower(S.x), fmt: function (v) { return fmtK(S.x, v); } });
    var ya = QKC.axis(T, { name: label(S.y), scale: true, inverse: lower(S.y), fmt: function (v) { return fmtK(S.y, v); } });
    ya.nameTextStyle.align = 'left';
    var opt = {
      grid: { left: 8, right: continuous ? 64 : 24, top: groupKey ? 64 : 34, bottom: 30, containLabel: true },
      xAxis: xa, yAxis: ya,
      legend: groupKey ? { top: 0, left: 0, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 11 }, data: groups.map(function (g) { return g.name; }) } : undefined,
      tooltip: QKC.tooltip(T, { formatter: function (prm) {
        var r = (prm.data || {}).r; if (!r) return '';
        var vx = val(r, S.x), vy = val(r, S.y);
        return '<div style="font-weight:700">' + esc(r[I.name]) + '</div><div style="color:' + T.ink3 + ';font-size:11px;max-width:260px;white-space:normal">' + esc(r[I.team] || '') + ' · ' + esc(compLabel(r)) + (r[I.age] ? ' · age ' + r[I.age] : '') + '</div>' +
          QKC.tipRow(prm.color, label(S.x), fmtK(S.x, vx) + ' · pct ' + Math.round(pxOf(vx))) + QKC.tipRow(prm.color, label(S.y), fmtK(S.y, vy) + ' · pct ' + Math.round(pyOf(vy))) +
          (cpct && isNum(val(r, S.color)) ? QKC.tipRow(prm.color, label(S.color), fmtK(S.color, val(r, S.color)) + ' · pct ' + Math.round(cOf(r))) : '') +
          (S.shrink ? '<div style="color:' + T.ink3 + ';font-size:11px">unshrunk ' + fmtK(S.x, rawV(r, S.x)) + ' · ' + fmtK(S.y, rawV(r, S.y)) + '</div>' : '');
      } }),
      series: series
    };
    if (cpct) opt.visualMap = { type: 'continuous', dimension: 2, seriesIndex: 0, min: 0, max: 100, right: 0, top: 'middle', itemWidth: 10, itemHeight: 140, calculable: false,
      text: ['better', 'worse'], textStyle: { color: T.ink3, fontSize: 10 }, inRange: { color: [0, 25, 50, 75, 100].map(function (x) { return QK.pctHex(x); }) } };
    else if (continuous) opt.visualMap = { type: 'continuous', dimension: 2, seriesIndex: 0, min: clo, max: chi, right: 0, top: 'middle', itemWidth: 10, itemHeight: 140, calculable: false,
      text: [lower(S.color) ? 'worse' : 'better', lower(S.color) ? 'better' : 'worse'], textStyle: { color: T.ink3, fontSize: 10 },
      inRange: { color: lower(S.color) ? [T.pos, T.mid, T.neg] : [T.neg, T.mid, T.pos] } };
    return opt;
  }, { label: 'Player lab: ' + label(S.y) + ' against ' + label(S.x),
    onClick: EMBED && EMBED.onPick ? function (prm) { var r = (prm.data || {}).r; if (r) EMBED.onPick(String(r[I.player_id])); } : undefined });

  FB.set('lb-note', 'One dot per player: minutes and rates over ' + esc(single() ? scopeName : scopeName.toLowerCase()) + ' in the view, however many competitions that spans. Dotted lines are the medians of this group (' + esc(groupNoun()) + '). ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    'Labelled: the twelve players furthest into that corner (sum of standard scores on both axes)' + (hits.length ? ', and your search (blue rings)' : '') + '. Click a dot to open the player.' +
    (cpct ? ' Colour: ' + esc(label(S.color)) + ' as a percentile within the ' + esc(groupNoun()) + ' on screen.' : '') +
    (adjOn() ? ' Attacking rates marked "adj." are multiplied by the scoring factor from the pooled model: the minutes-weighted blend of the player\'s competitions.' : '') +
    (S.shrink ? ' Rates marked "shrunk" are pulled towards the group median by ' + SHRINK_K + ' minutes of prior, so a player five matches in is not ranked on five matches alone; the tooltip shows the raw figures.' : '') +
    ' <a href="#/model/glossary/shrinkage">Glossary →</a>');

  FB.set('lb-sim', simStrip(base0, hits, personQ, v));
  // Position mode: the view's value column (vk) with its percentile within the group on screen; Broad keeps GAR/90
  var sortedV = vk ? rows.map(function (r) { return val(r, vk); }).filter(isNum).sort(function (a, b) { return a - b; }) : [];
  var pvOf = function (x) { if (!isNum(x)) return null; var pp = pctRank(sortedV, x); return lower(vk) ? 100 - pp : pp; };
  var trows = ranked.slice(0, 60).map(function (o, i) {
    var r = o.r, vx = val(r, S.x), vy = val(r, S.y), vv = vk ? val(r, vk) : null;
    return { i: i + 1, name: r[I.name], pid: r[I.player_id], comp: r[I.comp], team: r[I.team], tid: r[I.tid], mix: compLabel(r), age: r[I.age], min: r[I.minutes], vx: vx, px: pxOf(vx), vy: vy, py: pyOf(vy), z: o.z, href: href(r),
      role: I.role !== undefined ? (r[I.role] || '') : '',
      g90: I.gar90 !== undefined ? r[I.gar90] : null, vv: vv, pv: pvOf(vv) };
  });
  var garCol = !v && I.gar90 !== undefined && S.x !== 'gar90' && S.y !== 'gar90';
  var valCol = vk ? [{ key: 'vv', label: (LAB.meta[vk] || {}).label || vk, num: true, pctl: 'pv', ours: oursOf(vk) ? { name: oursOf(vk).name, about: oursOf(vk).about } : null,
    tip: 'Overall value, the position view’s value metric' + (specTip(vk, (LAB.meta[vk] || {}).desc || '') ? ': ' + specTip(vk, (LAB.meta[vk] || {}).desc || '') : ''),
    fmt: function (x) { return isNum(x) ? (vk === 'gar90' ? FB.signed(x, 2) : fmtK(vk, x)) : '—'; } }] : [];
  var oc = function (k) { var o = oursOf(k); return o ? { name: o.name, about: o.about } : null; };
  FB.table(el.querySelector('#lb-table'), [
    { key: 'i', label: '#', num: true },
    { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return '<a class="fb-link" href="' + esc(r.href) + '">' + esc(v) + '</a>'; } },
    { key: 'team', label: S.scope === 'intl' ? 'National team' : 'Club', fmt: function (v, r) { return r.tid && FB.clubRow(r.tid) ? FB.clubLink(r.tid, v || FB.clubName(r.tid)) : esc(v || ''); } },
    { key: 'mix', label: 'Competitions (minutes)', fmt: function (v) { return '<span class="qk-muted fb-lb-mix">' + esc(v) + '</span>'; } },
    { key: 'role', label: 'Role', tip: 'Formation role: the one started in most (DF, MF or FW: substitute appearances only)' },
    { key: 'age', label: 'Age', num: true },
    { key: 'min', label: 'Min', num: true },
    { key: 'vx', label: (LAB.meta[S.x] || {}).label || S.x, num: true, pctl: 'px', ours: oc(S.x), tip: specTip(S.x, (LAB.meta[S.x] || {}).desc || '') || undefined, fmt: function (v) { return fmtK(S.x, v); } },
    { key: 'vy', label: (LAB.meta[S.y] || {}).label || S.y, num: true, pctl: 'py', ours: oc(S.y), tip: specTip(S.y, (LAB.meta[S.y] || {}).desc || '') || undefined, fmt: function (v) { return fmtK(S.y, v); } }
  ].concat(garCol ? [{ key: 'g90', label: 'GAR/90', num: true, ours: oc('gar90'), tip: specTip('gar90', OURS[0].tip), fmt: function (v) { return isNum(v) ? FB.signed(v, 2) : '—'; } }] : []).concat(valCol).concat([
    { key: 'z', label: 'Combined', num: true, tip: 'Sum of standard scores on both axes, better direction', fmt: function (v) { return '<b>' + num(v, 2) + '</b>'; } }
  ]), trows, { maxHeight: 620, caption: 'Players ranked on this view' });
}

/* "Most like": the five players nearest the highlighted one within the group on screen (Broad or Position), on standard
   scores of the group's headline metrics (QK.within.similar), each a link to Compare. */
function simStrip(rows, hits, personQ, v) {
  var I = LAB.idx;
  if (!hits.length) return '<p class="fb-cap fb-lb-simhint">Highlight a player to list the five most like them among the ' + esc(groupNoun()) + ' on this chart.</p>';
  var t = hits[0];
  if (rows.indexOf(t) < 0) return '<p class="fb-cap fb-lb-simhint">' + esc(t[I.name]) + ' is under the minimum for this chart, so has no look-alikes here.</p>';
  var head = headlineFor(S.pos);
  // Position mode: the view's metrics (about 4 excellence, 4 attacking and 2 value ids the lab carries); Broad: the headline list
  var keys = v ? [] : Object.keys(head).filter(function (k) { return I[k] !== undefined; }).sort(function (a, b) { return head[a] - head[b]; });
  if (v) [4, 4, 2].forEach(function (n, i) { v.sets[i].ids.filter(function (k) { return I[k] !== undefined && keys.indexOf(k) < 0; }).slice(0, n).forEach(function (k) { keys.push(k); }); });
  var near = QK.within.similar(rows, t, keys, function (r, k) { return rawV(r, k); }, 5);
  var tid = String(t[I.player_id]);
  return QK.within.simHtml('Most like ' + t[I.name] + ' · ' + groupNoun(), near.map(function (o) {
    var r = o.row;
    return { name: r[I.name], href: '#/compare/players/' + tid + '/' + r[I.player_id] + (personQ && personQ.c ? '?scope=' + encodeURIComponent(personQ.c) : (personQ && personQ.scope ? '?scope=' + personQ.scope : '')),
      sub: [r[I.team] || '', I.role !== undefined ? r[I.role] : '', FB.int(r[I.minutes]) + ' min'].filter(Boolean).join(' · ') + ' · compare' };
  }));
}

// ══════════════════════════════════════════════════════════════════════ compare

var RADAR_OUT = [['npxg_90', 'npxG/90'], ['shots_90', 'Shots/90'], ['xa_90', 'xA/90'], ['key_passes_90', 'Key passes/90'], ['pass_pct', 'Pass %'], ['dribbles_90', 'Dribbles/90'],
  ['prog_carries_90', 'Prog. carries/90'], ['tackles_90', 'Tackles/90'], ['interceptions_90', 'Interceptions/90'], ['aerial_pct', 'Aerial %'], ['recoveries_90', 'Recoveries/90'], ['rating', 'Rating']];
var RADAR_GK = [['saves_90', 'Saves/90'], ['save_pct', 'Save %'], ['goals_prevented_90', 'Goals prevented/90'], ['conceded_90', 'Conceded/90'], ['sweeper_90', 'Sweeper/90'],
  ['high_claims_90', 'High claims/90'], ['pass_pct', 'Pass %'], ['long_ball_pct', 'Long-ball %'], ['rating', 'Rating']];
var HEAD_OUT = ['npxg_90', 'xa_90', 'shots_90', 'key_passes_90', 'dribbles_90', 'prog_carries_90', 'tackles_90', 'interceptions_90'];
var HEAD_GK = ['saves_90', 'goals_prevented_90', 'conceded_90', 'sweeper_90', 'high_claims_90', 'passes_90', 'long_balls_90', 'km_90'];
var STYLE_AXES = [['possession', 'Possession'], ['field_tilt', 'Field tilt'], ['ppda', 'Pressing (PPDA)'], ['shot_quality', 'Shot quality'], ['xg_for', 'xG for'], ['xg_against', 'xG against'], ['aerial_pct', 'Aerial %'], ['big_chances', 'Big chances']];
var STYLE_FALLBACK = { possession: 'poss', xg_for: 'xg', xg_against: 'xga', shot_quality: 'xg_per_shot', aerial_pct: 'aerial_pct', big_chances: 'big_chances' };
var SIDE = ['a', 'b', 'c'];

function splitKey(key) { var s = String(key || ''); var i = s.indexOf(':'); return i < 0 ? [null, s] : [s.slice(0, i), s.slice(i + 1)]; }
function sideDot(i) { return '<i class="fb-lb-dot ' + SIDE[i] + '" aria-hidden="true"></i>'; }

FB.route('compare', function (el, p) {
  var kind = p.kind === 'clubs' ? 'clubs' : 'players';
  var a = p.a || '', b = p.b || '';
  var q0 = p.query || {};
  var c3 = kind === 'players' ? (q0.p3 || '') : '';
  var classic = kind === 'players' && q0.view === 'classic';
  var noun = kind === 'players' ? 'player' : 'club';
  var keep = function (extra) { return FB.qs(FB.merge({ p3: c3 || null, view: classic ? 'classic' : null, scope: q0.scope || null }, extra || {})); };
  var viewTabs = kind === 'players' && a && b && a !== '_' ? FB.subnav([['#/compare/players/' + esc(a) + '/' + esc(b) + keep({ view: null }), 'Side by side', 'v2'],
    ['#/compare/players/' + esc(a) + '/' + esc(b) + keep({ view: 'classic', p3: null }), 'Every metric (classic)', 'classic'],
    ['#/compare/progression/' + [a, b, c3].filter(function (x) { return x && x !== '_'; }).map(function (x) { return esc(String(x).split(':').pop()); }).join('/') + (q0.scope === 'intl' ? '?scope=intl' : ''), 'Career progression', 'prog']], classic ? 'classic' : 'v2', 'Comparison view') : '';
  el.innerHTML = FB.pageHead(kind === 'players' ? 'Scouting Room' : 'Teams', kind === 'players' ? 'Compare players' : 'Compare clubs',
      kind === 'players' ? 'Two or three players from any competition, side by side on the metrics that best describe and predict their play, ranked against their own position group.' : 'Two clubs from any competition, side by side: our chance if they met, the tale of the tape, style, form, season chances and year by year.') +
    subnav(kind) +
    '<section class="qk-card fb-lb-pick"><div class="qk-card-body">' + FB.toolbar([
      picker('lb-pa', 'First ' + noun, 0), picker('lb-pb', 'Second ' + noun, 1), kind === 'players' && !classic ? picker('lb-pc', 'Third (optional)', 2) : '',
      (a && b ? '<a class="qk-btn" href="#/compare/' + kind + '/' + esc(b) + '/' + esc(a) + keep() + '" title="Swap the two">⇄ Swap</a>' : '')
    ]) + '<div id="lb-picked" class="fb-lb-picked"></div></div></section>' + viewTabs + '<div id="lb-body"></div>';
  var go = function (side, key) {
    var na = side === 0 ? key : a, nb = side === 1 ? key : b, nc = side === 2 ? key : c3;
    FB.go('#/compare/' + kind + '/' + (na || '_') + (nb ? '/' + nb : '') + (kind === 'players' ? keep({ p3: nc || null }) : ''));
  };
  wirePicker(el, 'lb-pa', kind, function (key) { go(0, key); });
  wirePicker(el, 'lb-pb', kind, function (key) { go(1, key); });
  if (kind === 'players' && !classic) wirePicker(el, 'lb-pc', kind, function (key) { go(2, key); });
  if (a === '_') a = '';
  if (!a || !b) {
    var ex = kind === 'players'
      ? [['839956', '823941', 'Haaland v Isak'], ['12994', '750', 'Messi v Ronaldo'], ['839956', '108579', 'Haaland v Kane'], ['826643', '839956', 'Mbappé v Haaland']]
      : [['42', '2817', 'Arsenal v Barcelona'], ['42', '44', 'Arsenal v Liverpool'], ['2829', '2672', 'Real Madrid v Bayern'], ['3202', '5981', 'Boca v Flamengo']];
    FB.set('lb-body', FB.card('Pick two ' + kind, '', '<p class="qk-sub">Type a name in each box, or try one of these:</p><div class="qk-chips">' +
      ex.map(function (x) { return '<a class="qk-chip" href="#/compare/' + kind + '/' + x[0] + '/' + x[1] + '">' + esc(x[2]) + '</a>'; }).join('') + '</div>'));
    if (a) FB.set('lb-picked', '<span class="qk-badge">' + esc(a) + '</span> v <span class="qk-badge">not picked</span>');
    return;
  }
  FB.set('lb-body', FB.loading('card', 4));
  return kind === 'players' ? comparePlayers(el, a, b, q0.scope, classic ? null : c3, classic) : compareClubs(el, a, b);
});

/* Teams › Head to head (clubs.js, #/clubs/h2h?a=&b=): the club compare inside the Teams page, two pickers over every
   club and national team, "If they met" (the pooled fit for clubs, the international fit for two national teams) and
   the tale of the tape. go(a, b) changes the address. */
FB.clubsH2H = function (host, a, b, go) {
  host.innerHTML = '<section class="qk-card fb-lb-pick"><div class="qk-card-body">' + FB.toolbar([picker('lb-pa', 'First club or team', 0), picker('lb-pb', 'Second club or team', 1),
    (a && b ? '<button type="button" class="qk-btn" id="lb-swap2" title="Swap the two">⇄ Swap</button>' : '')]) + '<div id="lb-picked" class="fb-lb-picked"></div></div></section><div id="lb-body"></div>';
  wirePicker(host, 'lb-pa', 'clubs', function (k) { go(k, b); });
  wirePicker(host, 'lb-pb', 'clubs', function (k) { go(a, k); });
  var sw = host.querySelector('#lb-swap2'); if (sw) sw.addEventListener('click', function () { go(b, a); });
  if (!a || !b) {
    var ex = [['42', '2817', 'Arsenal v Barcelona'], ['42', '44', 'Arsenal v Liverpool'], ['2829', '2672', 'Real Madrid v Bayern'], ['3202', '5981', 'Boca v Flamengo'], ['4698', '4819', 'Spain v Argentina']];
    FB.set('lb-body', FB.card('Pick two', '', '<p class="qk-sub">Type a name in each box, or try one of these:</p><div class="qk-chips">' +
      ex.map(function (x) { return '<a class="qk-chip" href="#/clubs/h2h?a=' + x[0] + '&amp;b=' + x[1] + '">' + esc(x[2]) + '</a>'; }).join('') + '</div>'));
    return null;
  }
  FB.set('lb-body', FB.loading('card', 4));
  return compareClubs(host, a, b);
};
function picker(id, placeholder, side) {
  return FB.field(placeholder, '<span class="fb-lb-picker">' + sideDot(side) + '<input class="qk-input" id="' + id + '" type="search" placeholder="Search…" autocomplete="off" spellcheck="false" aria-label="' + esc(placeholder) + '"><span class="fb-lb-res" id="' + id + '-r" hidden></span></span>');
}
function wirePicker(el, id, kind, onPick) {
  var input = el.querySelector('#' + id), box = el.querySelector('#' + id + '-r');
  if (!input) return;
  var timer = null;
  input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var q = norm(input.value.trim());
      if (q.length < 2) { box.hidden = true; return; }
      (kind === 'players' ? FB.peopleIndex() : FB.clubsIndex()).then(function (idx) {
        if (!FB.alive(el)) return;
        var hits = [];
        for (var i = 0; i < idx.list.length && hits.length < 60; i++) { var r = idx.list[i]; var n = norm(r.name); var k = n.indexOf(q); if (k >= 0) hits.push([k === 0 ? 0 : 1, r]); }
        hits.sort(function (x, y) { return x[0] - y[0] || (kind === 'players' ? (y[1].min || 0) - (x[1].min || 0) : ((y[1].comps || []).length - (x[1].comps || []).length)); });
        hits = hits.slice(0, 10).map(function (h) { return h[1]; });
        box.innerHTML = hits.length ? hits.map(function (r) {
          var sub = kind === 'players' ? [FB.POS_LABEL[r.pos] || '', r.club || '', r.min ? FB.int(r.min) + '\' this season' : ''].filter(Boolean).join(' · ') : (r.national ? 'National team' : (r.home ? FB.compName(r.home, true) : r.country || ''));
          return '<button type="button" data-key="' + esc(r.id) + '">' + (kind === 'clubs' ? FB.crest(r.id, r.name, 'sm') : '') + '<span><b>' + esc(r.name) + '</b><small>' + esc(sub) + '</small></span></button>';
        }).join('') : '<span class="fb-lb-none">No match.</span>';
        box.hidden = false;
        Array.prototype.forEach.call(box.querySelectorAll('button'), function (b) { b.addEventListener('click', function () { box.hidden = true; input.value = ''; onPick(b.getAttribute('data-key')); }); });
      });
    }, 140);
  });
  input.addEventListener('keydown', function (e) { if (e.key === 'Escape') { box.hidden = true; input.value = ''; } });
  document.addEventListener('click', function (e) { if (!e.target.closest || !e.target.closest('.fb-lb-picker')) box.hidden = true; });
}

/* ── players */

function liveComps(doc) {
  /* competitions of the person's current season with a players_live payload, most minutes first */
  var yr = (doc.years || [])[0];
  var era = yr ? yr.era : null;
  return (doc.seasons || []).filter(function (s) { return (!era || s.era === era) && s.source === 'live' && FB.hasFile(s.comp, 'players_live'); })
    .sort(function (x, y) { return (y.min || 0) - (x.min || 0); }).map(function (s) { return s.comp; });
}
/* A lab row (data/lab/season/<scope>.json) as the object buildPlayers reads: the rates, percentiles against the same
   position in the same view, and whether he is over the view's floor. */
function labRowObject(view, r, metrics, floor) {
  var I = view.idx, o = {};
  view.fields.forEach(function (f, i) { o[f] = r[i]; });
  o.is_gk = r[I.position] === 'G';
  o.qualified = (r[I.minutes] || 0) >= floor;
  o.pct = o.qualified ? FB.labPct(view, r, metrics.filter(function (m) { return m.pct; }), floor) : {};
  return o;
}
function comparePlayers(el, ka, kb, scopeQ, kc, classic) {
  var keys = [splitKey(ka), splitKey(kb)].concat(kc ? [splitKey(kc)] : []);
  return FB.peopleIndex().then(function (pi) {
    if (!FB.alive(el)) return;
    var bad = keys.filter(function (k) { return !pi.byId[k[1]]; });
    if (bad.length) {
      FB.set('lb-picked', keys.map(function (k, i) { return pi.byId[k[1]] ? '<span class="qk-badge">' + sideDot(i) + esc(pi.byId[k[1]].name) + '</span>' : '<span class="qk-badge">' + esc(k[1]) + ': not in the registry</span>'; }).join(' v '));
      FB.set('lb-body', FB.empty('Player not found', 'One of the ids is not in the player registry. Use the search boxes.'));
      return;
    }
    keys = keys.map(function (k) { return [k[0], String(pi.byId[k[1]].id)]; });       // a merged duplicate id -> the person
    // Scope: ?scope= (all, club, intl or a competition); an old <comp>:<id> key means that competition.
    var scope = scopeQ || keys[0][0] || keys[1][0] || 'all';
    return Promise.all(keys.map(function (k) { return FB.load('people/' + k[1] + '.json'); }).concat([FB.labIndex()])).then(function (docs) {
      if (!FB.alive(el)) return;
      var ix = docs[keys.length];
      var pooled = !!FB.LAB_SCOPES[scope];
      var P = docs.slice(0, keys.length).map(function (d, i) {
        d = d || { id: keys[i][1], name: pi.byId[keys[i][1]].name, seasons: [], years: [], apps: [] };
        var cands = liveComps(d);
        var comp = !pooled && FB.hasFile(scope, 'players_live') ? scope : (cands[0] || null);
        return { id: String(keys[i][1]), doc: d, comp: comp, cands: cands, scope: scope };
      });
      scopePicker(el, P, scope, ix);
      var view = pooled && ix ? FB.labView('season', scope) : Promise.resolve(null);
      return Promise.all([view].concat(P.map(function (x) { return x.comp ? FB.compFiles(x.comp, ['players_live', 'shots']) : Promise.resolve({}); }))).then(function (files) {
        if (!FB.alive(el)) return;
        var V = files[0];
        P.forEach(function (x, i) {
          var live = files[i + 1].players_live || {};
          var sh = (files[i + 1].shots || {}).players || {};
          x.shots = [];
          Object.keys(sh).forEach(function (n) { if (String(sh[n].player_id) === x.id) x.shots = sh[n].shots || []; });
          if (pooled) {
            var floor = V ? Math.max(90, Math.min(V.floor, 450)) : 450;
            var r = V ? V.rows.filter(function (row) { return String(row[V.idx.player_id]) === x.id; })[0] : null;
            x.pooled = FB.labScopeName(scope, ix);
            x.V = V;
            x.live = { minutes_floor: floor };
            x.metrics = (ix || {}).metrics || [];
            x.row = r ? labRowObject(V, r, x.metrics, floor) : null;
          } else {
            x.live = live;
            x.metrics = live.metrics || [];
            x.row = (live.players || []).filter(function (r) { return String(r.player_id) === x.id; })[0] || null;
          }
        });
        if (classic) { buildPlayers(el, P.slice(0, 2)); return; }
        /* the role groups (FB.MSET) when the role payload loads; the position letters otherwise */
        var hasRole = P.every(function (x) { return x.V ? x.V.idx.role !== undefined : (((x.live || {}).players || []).some(function (r) { return r.role !== undefined; })); });
        return FB.rolesFor(hasRole).then(function (R) { if (FB.alive(el) && !buildCompareRole(el, P, R, ix)) buildCompareV2(el, P); });
      });
    });
  });
}
/* The scope picker beside the two names: every competition, club football, national-team football, or one
   competition either player has played this season. */
function scopePicker(el, P, scope, ix) {
  var opts = [['all', 'All competitions'], ['club', 'Club competitions'], ['intl', 'National team']];
  var seen = {};
  P.forEach(function (x) { x.cands.forEach(function (c) { seen[c] = 1; }); });
  if (!FB.LAB_SCOPES[scope]) seen[scope] = 1;
  var comps = Object.keys(seen).sort(function (a, b) { return FB.compName(a).localeCompare(FB.compName(b)); });
  if (comps.length) opts.push({ group: 'One competition (its own percentiles)', items: comps.map(function (c) { return [c, FB.compName(c)]; }) });
  FB.set('lb-picked', P.map(function (x, i) { return '<span class="qk-badge">' + sideDot(i) + esc(x.doc.name) + '</span>'; }).join(' <span class="qk-muted">v</span> ') +
    ' <span class="fb-lb-scope">' + FB.field('Compare on', FB.select('lb-scope', opts, scope, 'Which competitions count', 'fb-pl-wide')) + '</span>');
  var sel = el.querySelector('#lb-scope');
  if (sel) sel.addEventListener('change', function () { FB.setQuery({ scope: sel.value === 'all' ? null : sel.value }, true); });
}

/* The v2 comparison on the metrics spec (FB.MSET): two or three players on their formation-role group's headline and
   secondary sets, each value with its percentile against the group (over max(the group's minimum, the view's floor)),
   in one competition's line or pooled over the scope with attacking rates league-adjusted (the spec's
   cross-competition rule); then where each one sits. Returns false when the role payload is missing (the caller
   falls back to the position letters). */
function buildCompareRole(el, P, R, ix) {
  if (!R || !R.ok) return false;
  var pooled = !!P[0].pooled;
  var adj = {};
  ((ix || {}).adjusted_keys || []).concat(FB.ADJ_EXTRA || []).forEach(function (k) { adj[k] = 1; });
  /* one ranker per view: the pooled lab view, or each player's competition line */
  var rankers = {};
  var rankerOf = function (x) {
    var key = pooled ? '_pool' : (x.comp || '_none');
    if (rankers[key]) return rankers[key];
    var rk;
    if (pooled && x.V) {
      var V = x.V, I = V.idx;
      rk = { floor: V.floor, rows: V.rows, id: function (r) { return String(r[I.player_id]); }, min: function (r) { return r[I.minutes]; },
        role: function (r) { return FB.rowRole(R, I.role === undefined ? null : r[I.role], r[I.player_id], null); },
        val: function (r, k) {
          /* the row's own GAR/90 (value_fields: the value over exactly this line's matches); no lines.json fallback, which
             would mix each competition's latest edition into another window or scope */
          if (k === 'gar90') return I.gar90 !== undefined && isNum(r[I.gar90]) ? r[I.gar90] : null;
          var v = I[k] === undefined ? null : r[I[k]];
          return isNum(v) && adj[k] ? v * (r[I.factor] || 1) : v;
        } };
    } else if (x.live && x.comp) {
      var comp = x.comp;
      rk = { floor: x.live.minutes_floor, rows: x.live.players || [], id: function (r) { return String(r.player_id); }, min: function (r) { return r.minutes; },
        role: function (r) { return FB.rowRole(R, r.role, r.player_id, comp); }, val: function (r, k) { return k === 'gar90' ? FB.rowGar(R, r.gar90, r.player_id, comp) : r[k]; } };
    } else return null;
    rk.PP = FB.peerPct({ rows: rk.rows, minutes: rk.min, role: rk.role, val: rk.val, floor: rk.floor });
    rankers[key] = rk;
    return rk;
  };
  var X = P.map(function (x) {
    var rk = rankerOf(x);
    var raw = rk ? rk.rows.filter(function (r) { return rk.id(r) === x.id; })[0] : null;
    var g = raw ? rk.PP.group(raw) : FB.peerGroup(FB.roleOf(R, x.id, pooled ? null : x.comp));
    x._role = raw ? rk.role(raw) : FB.roleOf(R, x.id, pooled ? null : x.comp);
    return { x: x, rk: rk, raw: raw, g: g, pct: raw ? rk.PP.pct(raw) : null, min: raw ? rk.min(raw) : null };
  });
  var groupsOf = X.map(function (y) { return y.g ? y.g.id : null; });
  var body = el.querySelector('#lb-body');
  var gk = groupsOf.filter(function (id) { return id === 'gk'; }).length;
  if (gk && gk < X.length) {
    body.innerHTML = FB.card('Side by side', '', FB.empty('A goalkeeper and an outfield player share no metric set', 'Compare goalkeepers with goalkeepers, or open the classic view for every metric.'));
    return true;
  }
  var G = X.filter(function (y) { return y.g; })[0];
  if (!G) return false;
  var g = G.g;
  var same = X.every(function (y) { return y.g && y.g.id === g.id; });
  var sameComp = pooled || P.every(function (x) { return x.comp && x.comp === P[0].comp; });
  var where = pooled ? P[0].pooled.toLowerCase() + ' this season' : sameComp && P[0].comp ? FB.compName(P[0].comp) + ' ' + (FB.currentSeason(FB.comp(P[0].comp)).season || '') : 'each player\'s main competition this season';
  var min = G.rk ? G.rk.PP.min(g) : g.min;
  var catMeta = {};
  P.forEach(function (x) { (x.metrics || []).forEach(function (m) { if (!catMeta[m.key]) catMeta[m.key] = m; }); });
  var rowOf = function (k) {
    var info = FB.metricInfo(k) || {}, m = catMeta[k] || {};
    var our = oursOf(k);
    return { key: k, label: (info.label || m.label || k) + (pooled && adj[k] ? ' (adj.)' : ''), tip: (info.tip || m.desc || '') + (pooled && adj[k] ? ' League-adjusted in this pooled view.' : '') + (our ? ' Our model: ' + our.name + '.' : ''), better: info.lower ? 'low' : 'high',
      values: X.map(function (y) { return y.raw && y.rk ? y.rk.val(y.raw, k) : null; }), pctls: X.map(function (y) { return y.pct ? y.pct[k] : null; }),
      fmt: function (v) { return FB.fmtSet(k, v, m.fmt); } };
  };
  var groups = [{ label: 'Headline', rows: FB.groupKeys(g, 'headline').map(rowOf) }, { label: 'More', rows: FB.groupKeys(g, 'more').map(rowOf) }];
  var ents = X.map(function (y) {
    var x = y.x, club = (x.doc.current_club || {}).name || (y.raw && y.rk && !pooled ? (y.raw.team || '') : '');
    var mins = isNum(y.min) ? FB.int(y.min) + ' min' : 'no minutes in the view';
    var role = x._role;
    var tid = (x.doc.current_club || {}).tid;
    /* v4: the club's kit and alternate colours when clubs_index.json has them (two players draw the tale of the tape) */
    return { name: x.doc.name, abbr: FB.surname(x.doc.name), short: FB.surname(x.doc.name), href: FB.href.player(x.id, x.comp && !pooled ? { c: x.comp } : null),
      colour: tid ? FB.clubColour(tid) : null, alt: tid ? FB.clubAlt(tid) : null, sub: [club, role || FB.POS_LABEL[x.doc.pos] || '', mins].filter(Boolean).join(' · ') };
  });
  var notes = [];
  if (!same) notes.push('Different roles: each percentile is against the player\'s own role group (' + X.map(function (y) { return y.x.doc.name + ': ' + (y.g ? y.g.short : 'no role'); }).join(', ') + '), on the ' + g.short + '\' set.');
  if (!sameComp) notes.push('Different competitions: each percentile is against peers in the player\'s own competition. Pick "All competitions" above to rank them in one pool.');
  X.forEach(function (y) {
    var mn = y.g && y.rk ? y.rk.PP.min(y.g) : null;
    if (!y.raw) notes.push(y.x.doc.name + ': no line in this view.');
    else if (!y.g) notes.push(y.x.doc.name + ': no formation role this season (substitute appearances only), so no peer group.');
    else if (isNum(mn) && (y.min || 0) < mn) notes.push(y.x.doc.name + ' is under the ' + FB.int(mn) + '-minute minimum for ' + y.g.short + ': no percentiles yet.');
    else if ((y.min || 0) < y.g.small) notes.push(y.x.doc.name + ' has under ' + FB.int(y.g.small) + ' minutes: a small sample, read the percentiles as early.');
  });
  if (pooled) notes.push('Pooled over ' + P[0].pooled.toLowerCase() + ': attacking rates are multiplied by each player\'s league scoring factor before ranking (the metrics spec); value added is already on one scale.');
  var withRow = X.filter(function (y) { return y.raw; });
  var distKeys = FB.groupKeys(g, 'headline').filter(function (k) { return G.rk && G.rk.PP.values(g, k).length >= 8; }).slice(0, 4);
  var showDist = same && sameComp && distKeys.length && G.rk;
  var names = P.map(function (x) { return FB.surname(x.doc.name); });
  body.innerHTML = QK.sectionHead({ kicker: P.length === 2 ? 'Tale of the tape' : 'Side by side', title: cmpQuestion(names), sub: (P.length === 2 ? 'Bar length = percentile ' + esc(FB.peerLine(g, where, min).replace(/^v /, 'against ')) + ' (100 = best). The better number in each row is solid.'
      : 'Value and percentile ' + esc(FB.peerLine(g, where, min).replace(/^v /, 'against ')) + ' (100 = best). The best in each row is highlighted.'), html: true }) +
    FB.card(P.length + ' players, one metric set', 'The headline set for the role from our metrics spec: stable and predictive rates first.',
    (withRow.length >= 2 ? '<div class="fb-cmp-wrap">' + QK.compareView({ entities: ents, groups: groups }) + '</div>' + QK.verdicts(cmpVerdicts(groups, names)) : FB.empty('Not enough to compare', 'At least two players need a line in this view.')) +
    (notes.length ? '<p class="fb-cap">' + notes.map(esc).join(' ') + '</p>' : '') +
    (withRow.length >= 2 && FB.groupKeys(g, 'all').indexOf('gar90') >= 0 ? QK.oursExplain('<b>' + esc(specLabel('gar90', OURS[0].label)) + '</b> is our player value model: ' + esc(specExplain('gar90', OURS[0].tip)).replace(/^./, function (c) { return c.toLowerCase(); }) + ' It is on one scale across leagues, so it is never league-adjusted. <a href="#/value">Value leaderboard →</a>', { cls: 'fb-mt' }) : ''), { cls: 'fb-lb-cv' }) +
    (showDist ? FB.card('Where they sit', '<span id="lb-dist-sub"></span>', '<div class="fb-lb-distseg">' + FB.seg('lb-dist-m', distKeys.map(function (k) { return [k, (FB.metricInfo(k) || {}).label || k]; }), distKeys[0], 'Metric') + '</div>' +
      FB.chartBox('lb-dist', 260, 'Peer distribution with the players marked'), { cls: 'fb-mt' }) : '') +
    '<p class="fb-cap">' + P.map(function (x) { return '<a href="' + esc(FB.href.player(x.id)) + '">' + esc(x.doc.name) + ' →</a>'; }).join(' · ') +
    ' · <a href="#/model/glossary">Glossary →</a></p>';
  if (!showDist) return true;
  FB.set('lb-dist-sub', esc(g.name.replace(/^./, function (c) { return c.toUpperCase(); })) + ' in ' + esc(where) + ' over ' + FB.int(min) + ' minutes (' + G.rk.PP.peers(g).length + '), each player marked.');
  var draw = function (key) {
    var info = FB.metricInfo(key) || {}, m = catMeta[key] || {};
    var vals = G.rk.PP.values(g, key);
    var box = el.querySelector('#lb-dist');
    if (!box) return;
    if (vals.length < 8) { box.style.height = 'auto'; box.innerHTML = FB.empty('Too few peers with this metric'); return; }
    QKC.distribution(box, { values: vals, binCount: 20, lowerBetter: !!info.lower, colorBy: 'flat', fmt: function (v) { return FB.fmtSet(key, v, m.fmt); },
      xName: (info.label || key) + ' · ' + vals.length + ' ' + g.short, yName: 'Players',
      marks: X.map(function (y, i) { return { x: y.raw && y.rk ? y.rk.val(y.raw, key) : null, label: FB.surname(y.x.doc.name), color: CMP_MARK[i] }; }).filter(function (mk) { return isNum(mk.x); }),
      label: 'Distribution of ' + (info.label || key) });
  };
  draw(distKeys[0]);
  FB.wireSeg(el, 'lb-dist-m', draw);
  return true;
}

/* The comparison on the position letters (the fallback without the role payload): two or three players on the
   player card's metric set, each value with its percentile against the position group (100 = best); two draw the
   tale of the tape (the better number solid), three the table (the best in bold); then where each one sits. */
var CMP_MARK = ['wpA', 'wpB', 'c5'];
/* v3: the compare title asks the question ("Saka, Rogers or Mbeumo?"). */
function cmpQuestion(names) { return names.length === 2 ? names[0] + ' or ' + names[1] + '?' : names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?'; }
/* One verdict per player: the metric where the player's percentile beats the others' by the most (QK.verdicts). */
function cmpVerdicts(groups, names) {
  var ARCH = FB.PLAYER_ARCH || {};
  return names.map(function (nm, i) {
    var best = null;
    groups.forEach(function (g) {
      g.rows.forEach(function (r) {
        var mine = (r.pctls || [])[i];
        if (!isNum(mine)) return;
        var others = Math.max.apply(null, r.pctls.filter(function (_, j) { return j !== i; }).map(function (v) { return isNum(v) ? v : 0; }));
        if (mine - others > 0 && (!best || mine - others > best.d)) best = { d: mine - others, r: r, p: mine };
      });
    });
    if (!best) return null;
    var lab = String(best.r.label || '').replace(/ \(adj\.\)$/, '');
    return { title: ARCH[best.r.key] || 'The standout', who: nm, text: 'best of the ' + names.length + ' on ' + lab.charAt(0).toLowerCase() + lab.slice(1) + ' (' + best.r.fmt(best.r.values[i]) + ', ' + FB.ordinal(best.p) + ' percentile).' };
  });
}
function letterOf(x) {
  var r = x.row || {};
  if (r.is_gk || (r.position === 'G')) return 'G';
  return (FB.PLAYER_SETS || {})[r.position] ? r.position : ((FB.PLAYER_SETS || {})[x.doc.pos] ? x.doc.pos : 'M');
}
function buildCompareV2(el, P) {
  var SETS = FB.PLAYER_SETS || {}, DIST = FB.PLAYER_DIST || {}, PEER = FB.PEER_NAME || {};
  var withRow = P.filter(function (x) { return x.row; });
  var L = letterOf(P[0]);
  var letters = P.map(letterOf);
  var gkMix = letters.some(function (l) { return l === 'G'; }) && letters.some(function (l) { return l !== 'G'; });
  var same = letters.every(function (l) { return l === L; });
  var metricsAll = P.reduce(function (best, x) { return (x.metrics || []).length > best.length ? x.metrics : best; }, []);
  var meta = {};
  metricsAll.forEach(function (m) { meta[m.key] = m; });
  var pooled = !!P[0].pooled;
  var sameComp = pooled || P.every(function (x) { return x.comp && x.comp === P[0].comp; });
  var where = pooled ? P[0].pooled.toLowerCase() + ' this season' : sameComp && P[0].comp ? FB.compName(P[0].comp) + ' ' + (FB.currentSeason(FB.comp(P[0].comp)).season || '') : 'each player\'s main competition this season';
  var floor = ((P[0].live || {}).minutes_floor) || 0;
  var peer = same ? PEER[L] + ' · ' + where : 'each against their own position · ' + where;
  var body = el.querySelector('#lb-body');
  if (gkMix) {
    body.innerHTML = FB.card('Side by side', '', FB.empty('A goalkeeper and an outfield player share no metric set', 'Compare goalkeepers with goalkeepers, or open the classic view for every metric.'));
    return;
  }
  var set = SETS[L] || [];
  var groups = set.map(function (g) {
    return { label: g[0], rows: g[1].filter(function (k) { return meta[k]; }).map(function (k) {
      var m = meta[k];
      return { key: k, label: m.label || k, tip: m.desc || '', better: m.lower ? 'low' : 'high', values: P.map(function (x) { return x.row ? x.row[k] : null; }),
        pctls: P.map(function (x) { return x.row && x.row.pct ? x.row.pct[k] : null; }), fmt: function (v) { return isNum(v) ? FB.fmtMetric(v, m.fmt) : '—'; } };
    }) };
  });
  var ents = P.map(function (x) {
    var r = x.row || {}, club = (x.doc.current_club || {}).name || r.team || '';
    var mins = isNum(r.minutes) ? FB.int(r.minutes) + ' min' : 'no minutes in the view';
    var tid = (x.doc.current_club || {}).tid;
    return { name: x.doc.name, abbr: FB.surname(x.doc.name), short: FB.surname(x.doc.name), href: FB.href.player(x.id, x.comp && !pooled ? { c: x.comp } : null),
      colour: tid ? FB.clubColour(tid) : null, alt: tid ? FB.clubAlt(tid) : null, sub: [club, FB.POS_LABEL[x.doc.pos] || '', mins].filter(Boolean).join(' · ') };
  });
  var short = P.filter(function (x) { return x.row && x.row.minutes < floor; }).map(function (x) { return x.doc.name; });
  var none = P.filter(function (x) { return !x.row; }).map(function (x) { return x.doc.name; });
  var early = P.filter(function (x) { return x.row && x.row.minutes >= floor && x.row.minutes < 900; }).map(function (x) { return x.doc.name; });
  var notes = [];
  if (!same) notes.push('Different positions: each percentile is against the player\'s own position group, so read across positions with care.');
  if (!sameComp) notes.push('Different competitions: each percentile is against peers in the player\'s own competition. Pick "All competitions" above to rank them in one pool.');
  if (short.length) notes.push(short.join(', ') + (short.length > 1 ? ' are' : ' is') + ' under the ' + FB.int(floor) + '-minute floor: no percentiles yet.');
  if (none.length) notes.push(none.join(', ') + ': no line in this view.');
  if (early.length) notes.push(early.join(', ') + (early.length > 1 ? ' have' : ' has') + ' under 900 minutes: a small sample, read the percentiles as early.');
  var distKeys = (DIST[L] || []).filter(function (k) { return meta[k]; });
  var names = P.map(function (x) { return FB.surname(x.doc.name); });
  body.innerHTML = QK.sectionHead({ kicker: P.length === 2 ? 'Tale of the tape' : 'Side by side', title: cmpQuestion(names), sub: (P.length === 2 ? 'Bar length = percentile against ' : 'Value and percentile against ') + esc(peer) + (floor ? ' (' + FB.int(floor) + '+ minutes)' : '') + ' (100 = best). ' +
      (P.length === 2 ? 'The better number in each row is solid.' : 'The best in each row is highlighted.'), html: true }) +
    FB.card(P.length + ' players, one metric set', 'The set for the position: stable and predictive rates first.',
    (withRow.length >= 2 ? '<div class="fb-cmp-wrap">' + QK.compareView({ entities: ents, groups: groups }) + '</div>' + QK.verdicts(cmpVerdicts(groups, names)) : FB.empty('Not enough to compare', 'At least two players need a line in this view.')) +
    (notes.length ? '<p class="fb-cap">' + notes.map(esc).join(' ') + '</p>' : ''), { cls: 'fb-lb-cv' }) +
    (same && sameComp && distKeys.length ? FB.card('Where they sit', '<span id="lb-dist-sub"></span>', '<div class="fb-lb-distseg">' + FB.seg('lb-dist-m', distKeys.map(function (k) { return [k, meta[k].label || k]; }), distKeys[0], 'Metric') + '</div>' +
      FB.chartBox('lb-dist', 260, 'Peer distribution with the players marked'), { cls: 'fb-mt' }) : '') +
    '<p class="fb-cap">' + P.map(function (x) { return '<a href="' + esc(FB.href.player(x.id)) + '">' + esc(x.doc.name) + ' →</a>'; }).join(' · ') +
    ' · <a href="' + esc(FB.legacyRedirect('#/lab/' + (pooled ? P[0].scope : (sameComp && P[0].comp) ? P[0].comp : 'all') + '/' + L)) + '">Chart in the Scouting Room →</a> · <a href="#/model/glossary">Glossary →</a></p>';
  if (!(same && sameComp && distKeys.length)) return;
  var peers;
  if (pooled && P[0].V) {
    var V = P[0].V, I = V.idx;
    peers = V.rows.filter(function (r) { return (L === 'G' ? r[I.position] === 'G' : r[I.position] === L) && (r[I.minutes] || 0) >= floor; })
      .map(function (r) { var o = {}; distKeys.forEach(function (k) { o[k] = I[k] === undefined ? null : r[I[k]]; }); return o; });
  } else {
    peers = (((P[0].live || {}).players) || []).filter(function (x) { return (L === 'G' ? x.is_gk : (!x.is_gk && x.position === L)) && (x.qualified || (x.minutes || 0) >= floor); });
  }
  FB.set('lb-dist-sub', esc((PEER[L] || 'players').replace(/^./, function (c) { return c.toUpperCase(); })) + ' in ' + esc(where) + ' over ' + FB.int(floor) + ' minutes (' + peers.length + '), each player marked.');
  var draw = function (key) {
    var m = meta[key] || {};
    var vals = peers.map(function (x) { return x[key]; }).filter(isNum).sort(function (a, b) { return a - b; });
    var box = el.querySelector('#lb-dist');
    if (!box) return;
    if (vals.length < 8) { box.style.height = 'auto'; box.innerHTML = FB.empty('Too few peers with this metric'); return; }
    QKC.distribution(box, { values: vals, binCount: 20, lowerBetter: !!m.lower, colorBy: 'flat', fmt: function (v) { return FB.fmtMetric(v, m.fmt); },
      xName: (m.label || key) + ' · ' + vals.length + ' ' + (PEER[L] || 'players'), yName: 'Players',
      marks: P.map(function (x, i) { return { x: x.row ? x.row[key] : null, label: FB.surname(x.doc.name), color: CMP_MARK[i] }; }).filter(function (mk) { return isNum(mk.x); }),
      label: 'Distribution of ' + (m.label || key) });
  };
  draw(distKeys[0]);
  FB.wireSeg(el, 'lb-dist-m', draw);
}

function buildPlayers(el, P) {
  var A = P[0], B = P[1];
  var short = function (x) { return x.doc.short_name || FB.surname(x.doc.name); };
  var gk = !!(A.row && B.row && A.row.is_gk && B.row.is_gk) || (A.doc.pos === 'G' && B.doc.pos === 'G');
  var mixed = !!(A.row && B.row) && !!A.row.is_gk !== !!B.row.is_gk;
  var scope = gk ? 'gk' : 'out';
  var metricsAll = A.metrics.length >= B.metrics.length ? A.metrics : B.metrics;
  var inScope = function (m) { return m.scope === 'all' || (mixed ? true : m.scope === scope); };
  var pa = (A.row || {}).pct || {}, pb = (B.row || {}).pct || {};
  var both = !!(A.row && B.row);

  var idCard = function (x, i) {
    var d = x.doc, r = x.row || {};
    var club = d.current_club || {};
    var yr = (d.years || [])[0] || {};
    var tiles = [
      FB.kpi('Season ' + esc(yr.era || ''), FB.int(yr.min || 0) + '\'', { sub: (yr.apps || 0) + ' apps · all competitions' }),
      FB.kpi('Goals · assists', (yr.g || 0) + ' · ' + (yr.a || 0), { sub: isNum(yr.xg) ? 'xG ' + num(yr.xg, 1) + ' · xA ' + num(yr.xa, 1) : '' }),
      FB.kpi('Rating', isNum(yr.rt) ? num(yr.rt, 2) : '—', { sub: 'minutes-weighted' }),
      FB.kpi(r.is_gk ? 'Save %' : 'npxG/90', r.is_gk ? FB.fmtMetric(r.save_pct, 'pct') : (isNum(r.npxg_90) ? num(r.npxg_90, 2) : '—'), { sub: x.pooled ? esc(x.pooled) : x.comp ? esc(FB.compName(x.comp, true)) : '' })
    ];
    var meta = [FB.POS_LABEL[d.pos] || '', d.age ? d.age + ' years' : '', d.nat || '', d.height ? d.height + ' cm' : '', isNum(d.mv) ? 'Value ' + FB.money(d.mv, d.mvc) : ''].filter(Boolean);
    return '<section class="qk-hero fb-lb-hero ' + SIDE[i] + '"><div class="qk-hero-in"><div class="qk-avatar">' + esc(FB.initials(d.name)) + '</div><div class="fb-lb-hero-t">' +
      '<div class="qk-kicker">' + sideDot(i) + (club.tid ? FB.clubLink(club.tid, club.name) : 'No current club') + '</div>' +
      '<h2><a href="' + esc(FB.href.player(x.id, x.comp ? { c: x.comp } : null)) + '">' + esc(d.name) + '</a></h2>' +
      '<div class="qk-hero-meta">' + meta.map(function (m) { return '<span>' + esc(m) + '</span>'; }).join('') + '</div>' +
      (x.row ? (r.qualified === false ? '<div class="fb-cap">Below the ' + (x.live.minutes_floor || 0) + '-minute floor in ' + esc(x.pooled ? x.pooled.toLowerCase() : FB.compName(x.comp)) + ': no percentiles yet.</div>' : '') : '<div class="fb-cap">' + (x.pooled ? 'No minutes in ' + esc(x.pooled.toLowerCase()) + ' this season.' : x.comp ? 'No line in ' + esc(FB.compName(x.comp)) + ' this season.' : 'No competition with player data this season.') + '</div>') +
      '</div></div>' + FB.kpis(tiles, 'fb-lb-kpis') + '</section>';
  };

  var pctMetrics = metricsAll.filter(function (m) { return m.pct && inScope(m); });
  var comparable = pctMetrics.map(function (m) { return { m: m, a: pa[m.key], b: pb[m.key] }; }).filter(function (x) { return isNum(x.a) && isNum(x.b); }).map(function (x) { x.gap = x.a - x.b; return x; });
  var verdict;
  if (!comparable.length) verdict = FB.empty('No shared percentiles', 'Both players need a line above the minutes floor in a competition with player data.');
  else {
    var wa = comparable.filter(function (x) { return x.gap > 0; }), wb = comparable.filter(function (x) { return x.gap < 0; });
    var n = comparable.length, lev = n - wa.length - wb.length;
    var say = function (list, who) { return list.length ? list.slice(0, 3).map(function (x) { return '<li><b class="fb-num">+' + Math.round(Math.abs(x.gap)) + '</b> ' + esc(x.m.label) + '</li>'; }).join('') : '<li class="qk-muted">Leads on nothing</li>'; };
    wa.sort(function (x, y) { return y.gap - x.gap; }); wb.sort(function (x, y) { return x.gap - y.gap; });
    verdict = '<div class="fb-lb-verdict"><div class="fb-lb-vside a"><div class="qk-kicker">' + sideDot(0) + esc(short(A)) + ' leads on</div><ul>' + say(wa) + '</ul></div>' +
      '<div class="fb-lb-vmid"><div class="fb-lb-score"><span class="a">' + wa.length + '</span><span class="qk-muted">–</span><span class="b">' + wb.length + '</span></div>' +
      '<div class="fb-lb-wins"><span class="a" style="flex:' + wa.length + '"></span><span class="t" style="flex:' + lev + '"></span><span class="b" style="flex:' + wb.length + '"></span></div>' +
      '<div class="fb-cap">metrics won of ' + n + (lev ? ' · ' + lev + ' level' : '') + (A.pooled ? ' · ' + esc(A.pooled.toLowerCase()) + ' this season, one line per player' : A.comp !== B.comp ? ' · different competitions: each percentile is against its own peers' : '') + '</div></div>' +
      '<div class="fb-lb-vside b"><div class="qk-kicker">' + sideDot(1) + esc(short(B)) + ' leads on</div><ul>' + say(wb) + '</ul></div></div>';
  }

  var heads = (gk ? HEAD_GK : HEAD_OUT).map(function (k) { return metricsAll.filter(function (m) { return m.key === k; })[0]; }).filter(Boolean);
  var h2h = both ? heads.map(function (m) {
    var va = A.row[m.key], vb = B.row[m.key];
    var mx = Math.max(isNum(va) ? va : 0, isNum(vb) ? vb : 0) || 1;
    var better = isNum(va) && isNum(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 0 : 1) : -1;
    return '<div class="fb-lb-h2h"><div class="fb-lb-h2h-l">' + esc(m.label) + (m.lower ? ' <span class="qk-muted">(lower is better)</span>' : '') + '</div>' +
      '<div class="fb-lb-h2h-r"><span class="fb-num' + (better === 0 ? ' win' : '') + '">' + (isNum(va) ? FB.fmtMetric(va, m.fmt) : '—') + '</span><span class="fb-lb-bar a"><i style="width:' + (isNum(va) ? 100 * va / mx : 0) + '%"></i></span>' +
      '<span class="fb-lb-bar b"><i style="width:' + (isNum(vb) ? 100 * vb / mx : 0) + '%"></i></span><span class="fb-num' + (better === 1 ? ' win' : '') + '">' + (isNum(vb) ? FB.fmtMetric(vb, m.fmt) : '—') + '</span></div></div>';
  }).join('') : '';

  el.querySelector('#lb-body').innerHTML =
    '<div class="fb-lb-pair">' + idCard(A, 0) + idCard(B, 1) + '</div>' +
    FB.card('Verdict', 'Who wins each of the ' + pctMetrics.length + ' percentile metrics of the ' + (gk ? 'goalkeeper' : 'outfield') + ' scope, and the biggest gaps each way.' + (mixed ? ' A goalkeeper and an outfield player share few metrics.' : ''), verdict, { cls: 'fb-mt' }) +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Profile', A.pooled ? 'Percentiles against every player of the same position in ' + esc(A.pooled.toLowerCase()) + ' this season (each over ' + A.live.minutes_floor + ' minutes), on the position\'s axes.' : 'Percentiles in each player\'s competition, on the position\'s axes.', both ? FB.chartBox('lb-radar', 380, 'Percentile radar') : FB.muted('Needs a line for both players.'), { span: 6 }) +
      FB.card('Head to head per 90', 'Eight headline rates; the brighter figure is the better one.', h2h || FB.muted('No per-90 rates for both.'), { span: 6 })
    ) + '</div>' +
    FB.card('Every metric', 'The whole catalogue for the ' + (gk ? 'goalkeeper' : 'outfield') + ' scope: value, percentile and the gap in percentile points.', '<div class="fb-toolbar">' + FB.seg('lb-mmode', [['group', 'By group'], ['gap', 'By size of gap']], 'group', 'Order') + '</div><div id="lb-metrics"></div>', { cls: 'fb-mt' }) +
    '<div class="fb-mt">' + FB.grid(
      /* two goalkeepers: their own goals and xG are zeros (the match logs carry no goals conceded or xGOT faced), so
         only the form chart */
      (gk ? '' : FB.card('Goals against xG, this season', 'Cumulative goals (solid) and xG (dashed) match by match, every competition.', FB.chartBox('lb-evo', 300, 'Cumulative goals and xG'), { span: 6 })) +
      FB.card('Form', 'Sofascore rating, five-match rolling average, every competition.', FB.chartBox('lb-rt', 300, 'Rolling rating'), { span: gk ? 12 : 6 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card(sideDot(0) + esc(A.doc.name) + ': shots', A.comp ? 'Every shot in ' + esc(FB.compName(A.comp)) + ' this season; size by xG.' : '', '<div id="lb-sh-a"></div>', { span: 6 }) +
      FB.card(sideDot(1) + esc(B.doc.name) + ': shots', B.comp ? 'Every shot in ' + esc(FB.compName(B.comp)) + ' this season; size by xG.' : '', '<div id="lb-sh-b"></div>', { span: 6 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Year by year', 'Goals and assists per season, every competition (the site\'s season model: a European\'s 2025/26, a Brazilian\'s 2026).', FB.chartBox('lb-years', 280, 'Goals and assists by season'), { span: 12 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card(sideDot(0) + esc(A.doc.name) + ': last five', '', '<div id="lb-l5-a"></div>', { span: 6, flush: true }) +
      FB.card(sideDot(1) + esc(B.doc.name) + ': last five', '', '<div id="lb-l5-b"></div>', { span: 6, flush: true })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card(sideDot(0) + esc(A.doc.name) + ': this season, every competition', '', '<div id="lb-ss-a"></div>', { span: 6, flush: true }) +
      FB.card(sideDot(1) + esc(B.doc.name) + ': this season, every competition', '', '<div id="lb-ss-b"></div>', { span: 6, flush: true })
    ) + '</div>' +
    '<p class="fb-cap">' + P.map(function (x) { return '<a href="' + esc(FB.href.player(x.id)) + '">' + esc(x.doc.name) + ' →</a>'; }).join(' · ') +
    ' · <a href="' + esc(FB.legacyRedirect('#/lab/' + (A.pooled ? A.scope : A.comp && A.comp === B.comp ? A.comp : 'all') + '/' + (gk ? 'G' : ({ D: 'D', M: 'M', F: 'F' }[A.doc.pos] || 'M')))) + '">Chart in the Scouting Room →</a> · <a href="#/model/glossary">Glossary →</a></p>';

  if (both) {
    var axes = gk ? RADAR_GK : RADAR_OUT;
    FB.charts.radar(el.querySelector('#lb-radar'), { axes: axes.map(function (a) { return { name: a[1], max: 100 }; }),
      series: P.map(function (x, i) { return { name: x.doc.name + ' (' + (x.pooled || FB.compName(x.comp, true)) + ')', values: axes.map(function (a) { return (x.row.pct || {})[a[0]]; }), color: QK.cssVar(i ? '--c-2' : '--c-1') }; }) });
  }
  // metric table
  var groupOrder = [];
  metricsAll.forEach(function (m) { if (groupOrder.indexOf(m.group) < 0) groupOrder.push(m.group); });
  var mrows = metricsAll.filter(inScope).map(function (m, i) {
    var va = (A.row || {})[m.key], vb = (B.row || {})[m.key];
    var qa = m.pct ? pa[m.key] : null, qb = m.pct ? pb[m.key] : null;
    var gap = isNum(qa) && isNum(qb) ? qa - qb : null;
    var better = isNum(va) && isNum(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    return { label: m.label, key: m.key, group: m.group, gi: groupOrder.indexOf(m.group) * 1000 + i, va: va, vb: vb, qa: qa, qb: qb, gap: gap, ag: isNum(gap) ? Math.abs(gap) : -1, better: better, fmt: m.fmt, lower: m.lower };
  });
  var cols = [
    { key: 'label', label: 'Metric', sticky: true, fmt: function (v, r) { return '<a class="fb-link" href="#/model/glossary/' + esc(r.key) + '">' + esc(v) + '</a>' + (r.lower ? ' <span class="qk-muted" title="lower is better">↓</span>' : ''); } },
    { key: 'group', label: 'Group', fmt: function (v) { return '<span class="qk-muted">' + esc(v) + '</span>'; } },
    { key: 'va', label: short(A), num: true, pctl: 'qa', fmt: function (v, r) { return (r.better === 'a' ? '<b class="fb-lb-win">' : '<span>') + FB.fmtMetric(v, r.fmt) + (r.better === 'a' ? '</b>' : '</span>'); } },
    { key: 'ag', label: 'Gap', num: true, tip: 'Difference in percentile points: blue when ' + short(A) + ' leads, orange when ' + short(B) + ' does', fmt: function (v, r) { return gapBar(r.gap); } },
    { key: 'vb', label: short(B), num: true, pctl: 'qb', fmt: function (v, r) { return (r.better === 'b' ? '<b class="fb-lb-win">' : '<span>') + FB.fmtMetric(v, r.fmt) + (r.better === 'b' ? '</b>' : '</span>'); } }
  ];
  var mt = FB.table(el.querySelector('#lb-metrics'), cols, mrows, { sort: { key: 'gi', dir: 'asc' }, maxHeight: 560, caption: 'Every metric' });
  FB.wireSeg(el, 'lb-mmode', function (v) { if (mt) mt.sort(v === 'gap' ? 'ag' : 'gi', v === 'gap' ? 'desc' : 'asc'); });

  // evolution from the match logs (every competition, the person's current season)
  var logs = P.map(function (x) {
    var f = x.doc.apps_fields || [];
    var era = ((x.doc.years || [])[0] || {}).era;
    var list = (x.doc.apps || []).map(function (a) { var o = {}; f.forEach(function (k, j) { o[k] = a[j]; }); return o; });
    var eraSeasons = {};
    (x.doc.seasons || []).forEach(function (s) { if (s.era === era) eraSeasons[s.comp + '|' + s.sid] = 1; });
    return list.filter(function (a) { return !era || eraSeasons[a.comp + '|' + a.sid]; });
  });
  var maxN = Math.max(logs[0].length, logs[1].length);
  if (maxN >= 2) {
    var xs = []; for (var i = 1; i <= maxN; i++) xs.push(i);
    var ser = [], rser = [];
    logs.forEach(function (rows, k) {
      var chron = rows.slice().reverse(), gs = 0, xg = 0;
      var c = QK.cssVar(k ? '--c-2' : '--c-1');
      var nm = short(P[k]);
      ser.push({ name: nm + ' goals', color: c, data: chron.map(function (r) { gs += r.g || 0; return gs; }) });
      ser.push({ name: nm + ' xG', color: c, dash: true, data: chron.map(function (r) { xg += r.xg || 0; return Math.round(xg * 100) / 100; }) });
      var rts = chron.map(function (r) { return isNum(r.rt) ? r.rt : null; });
      rser.push({ name: nm, color: c, data: rts.map(function (v, j) { var w = rts.slice(Math.max(0, j - 4), j + 1).filter(isNum); return w.length ? Math.round(mean(w) * 100) / 100 : null; }) });
    });
    if (!gk) QKC.line(el.querySelector('#lb-evo'), { x: xs, xLabel: function (v) { return 'Match ' + v; }, series: ser, yFmt: function (v) { return num(v, 1); }, yMin: 0, xName: 'Match', yName: 'Cumulative goals and xG', label: 'Cumulative goals and xG' });
    QKC.line(el.querySelector('#lb-rt'), { x: xs, xLabel: function (v) { return 'Match ' + v; }, series: rser, yFmt: function (v) { return num(v, 2); }, yScale: true, xName: 'Match', yName: 'Rating, 5-match average', label: 'Five-match rolling rating' });
  } else { FB.set('lb-evo', FB.muted('No match logs this season.')); FB.set('lb-rt', ''); }

  // shots
  P.forEach(function (x, k) {
    var box = el.querySelector('#lb-sh-' + SIDE[k]);
    if (!x.shots.length) { box.innerHTML = FB.muted(x.doc.pos === 'G' ? 'Goalkeepers rarely shoot.' : 'No shots recorded this season.'); return; }
    FB.charts.shotMap(box, x.shots.map(function (s) { return { x: s.x, y: s.y, xg: s.xg, outcome: s.type, type: s.type, body: s.body, situation: s.situation, time: s.time, match: s.match, name: x.doc.name, href: s.gid ? FB.href.match(x.comp, s.gid) : null }; }), { surface: 'half', label: x.doc.name + ' shot map' });
  });

  // years
  var eras = [];
  P.forEach(function (x) { (x.doc.years || []).forEach(function (y) { if (eras.indexOf(y.era) < 0) eras.push(y.era); }); });
  eras.sort(function (a, b) { return FB.eraKey(a) - FB.eraKey(b); });
  eras = eras.slice(-10);
  if (eras.length) {
    var yv = function (x, e, k) { var y = (x.doc.years || []).filter(function (r) { return r.era === e; })[0]; return y ? (y[k] || 0) : null; };
    QKC.bar(el.querySelector('#lb-years'), { legend: true, cats: eras, catName: 'Season', valName: 'Goals plus assists', fmt: function (v) { return num(v, 0); },
      series: [{ name: short(A) + ' G+A', color: QK.cssVar('--c-1'), data: eras.map(function (e) { var g = yv(A, e, 'g'); return g === null ? null : g + yv(A, e, 'a'); }) },
        { name: short(B) + ' G+A', color: QK.cssVar('--c-2'), data: eras.map(function (e) { var g = yv(B, e, 'g'); return g === null ? null : g + yv(B, e, 'a'); }) }], label: 'Goals plus assists by season' });
  } else FB.set('lb-years', FB.muted('No season history.'));

  // last five and this season
  P.forEach(function (x, k) {
    var rows = logs[k].slice(0, 5).map(function (a) { return { date: a.date, comp: a.comp, opp: a.opp, home: a.home, res: a.res, min: a.min, start: a.start, rt: a.rt, g: a.g, a: a.a, xg: a.xg, gid: a.gid }; });
    var box = el.querySelector('#lb-l5-' + SIDE[k]);
    if (!rows.length) box.innerHTML = FB.muted('No match log this season.');
    else FB.table(box, [
      { key: 'date', label: 'Date', fmt: function (v) { return esc(FB.fmtDate(v)); } },
      { key: 'opp', label: 'Opponent', fmt: function (v, r) { return (r.home ? 'v ' : '@ ') + esc(v) + ' <span class="qk-muted">' + esc(FB.compName(r.comp, true)) + '</span>'; } },
      { key: 'res', label: 'Result', fmt: function (v) { var c = String(v || '').charAt(0); return '<span class="fb-lb-res-' + esc(c) + '">' + esc(v || '') + '</span>'; } },
      { key: 'min', label: 'Min', num: true, fmt: function (v, r) { return v + (r.start ? '' : ' <span class="qk-muted" title="came on">s</span>'); } },
      { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return num(v, 1); } },
      { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true },
      { key: 'xg', label: 'xG', num: true, fmt: function (v) { return num(v, 2); } }
    ], rows, { caption: 'Last five matches' });
    var era = ((x.doc.years || [])[0] || {}).era;
    var srows = (x.doc.seasons || []).filter(function (s) { return s.era === era; }).sort(function (s1, s2) { return (FB.KIND_ORDER[s1.kind] || 0) - (FB.KIND_ORDER[s2.kind] || 0) || (s2.min || 0) - (s1.min || 0); });
    var sbox = el.querySelector('#lb-ss-' + SIDE[k]);
    if (!srows.length) { sbox.innerHTML = FB.muted('No appearances this season.'); return; }
    var yr = (x.doc.years || [])[0] || {};
    srows = srows.map(function (s) { return { comp: s.comp, kind: s.kind, team: s.team, tid: s.tid, apps: s.apps, min: s.min, g: s.g, a: s.a, xg: s.xg, rt: s.rt, s: s }; });
    srows.push({ comp: '', total: true, apps: yr.apps, min: yr.min, g: yr.g, a: yr.a, xg: yr.xg, rt: yr.rt, s: yr });
    FB.table(sbox, [
      { key: 'comp', label: 'Competition', sticky: true, sort: false, fmt: function (v, r) { return r.total ? '<b>All competitions</b>' : FB.compLink(v, { short: true }) + ' ' + FB.coverageChip(r.s); } },
      { key: 'team', label: 'For', sort: false, fmt: function (v, r) { return r.total ? '' : '<span class="qk-muted">' + esc(v || '') + '</span>'; } },
      { key: 'apps', label: 'Apps', num: true, sort: false }, { key: 'min', label: 'Min', num: true, sort: false },
      { key: 'g', label: 'G', num: true, sort: false }, { key: 'a', label: 'A', num: true, sort: false },
      { key: 'xg', label: 'xG', num: true, sort: false, fmt: function (v) { return num(v, 1); } },
      { key: 'rt', label: 'Rating', num: true, sort: false, fmt: function (v) { return num(v, 2); } }
    ], srows, { caption: 'This season by competition' });
  });
}
function gapBar(gap) {
  if (!isNum(gap)) return '<span class="fb-lb-gap"></span>';
  var w = Math.min(50, Math.abs(gap) / 2);
  return '<span class="fb-lb-gap" title="' + signed(gap, 0) + ' percentile points"><i class="' + (gap >= 0 ? 'a' : 'b') + '" style="width:' + w + '%"></i></span>';
}

/* ── clubs */

function poissonPmf(k, lam) { var p = Math.exp(-lam); for (var i = 1; i <= k; i++) p *= lam / i; return p; }
/* The pooled model's score matrix for home v away; homeAdv 0 for a neutral venue. */
function dcMatrix(home, away, model, homeAdv) {
  var lamH = Math.exp(home.attack + away.defence + (homeAdv || 0));
  var lamA = Math.exp(away.attack + home.defence);
  var k = (model.max_goals || 8) + 1, rho = model.rho || 0;
  var m = [], total = 0, i, j;
  for (i = 0; i < k; i++) {
    m.push([]);
    for (j = 0; j < k; j++) {
      var p = poissonPmf(i, lamH) * poissonPmf(j, lamA);
      if (i === 0 && j === 0) p *= 1 - lamH * lamA * rho; else if (i === 1 && j === 0) p *= 1 + lamA * rho; else if (i === 0 && j === 1) p *= 1 + lamH * rho; else if (i === 1 && j === 1) p *= 1 - rho;
      p = Math.max(p, 0); m[i].push(p); total += p;
    }
  }
  var h = 0, d = 0, a = 0, o25 = 0, btts = 0, best = [0, 0, -1];
  for (i = 0; i < k; i++) for (j = 0; j < k; j++) {
    var q = m[i][j] / total;
    if (i > j) h += q; else if (i === j) d += q; else a += q;
    if (i + j >= 3) o25 += q;
    if (i >= 1 && j >= 1) btts += q;
    if (q > best[2]) best = [i, j, q];
  }
  return { h: h, d: d, a: a, lamH: lamH, lamA: lamA, o25: o25, btts: btts, score: best[0] + '-' + best[1], pScore: best[2] };
}
/* Our chance if they met, at one venue: the win-chance bar (home on the left, as on every card) and the numbers. */
function chanceCard(title, home, away, model, neutral) {
  var r = dcMatrix(home, away, model, neutral ? 0 : model.home_adv);
  return '<div class="fb-lb-price"><div class="qk-kicker">' + esc(title) + '</div>' + FB.wpBar({ h: r.h, d: r.d, a: r.a }, home.team, away.team, { size: 'sm' }) +
    '<div class="fb-cap">Expected goals ' + num(r.lamH, 2) + '–' + num(r.lamA, 2) + ' · most likely ' + r.score + ' (' + pct(r.pScore) + ') · 3 or more goals ' + pct(r.o25) + ' · both score ' + pct(r.btts) + '</div></div>';
}
function xptsOf(xg, xga) {
  if (!isNum(xg) || !isNum(xga)) return null;
  var win = 0, draw = 0, total = 0;
  for (var i = 0; i <= 8; i++) for (var j = 0; j <= 8; j++) { var p = poissonPmf(i, xg) * poissonPmf(j, xga); total += p; if (i > j) win += p; else if (i === j) draw += p; }
  return total > 0 ? (3 * win + draw) / total : null;
}
function tableRowOf(t, team) {
  if (!t) return null;
  var row = (t.standings || t.overall || []).filter(function (r) { return r.team === team; })[0] || null;
  if (!row && t.conferences) Object.keys(t.conferences).forEach(function (g) { row = row || (t.conferences[g] || []).filter(function (r) { return r.team === team; })[0] || null; });
  return row;
}
var CLUB_FILES = ['teams', 'table', 'strength', 'probs', 'team_stats', 'analytics', 'fixtures', 'players_live'];

function resolveClub(key, ci) {
  var k = splitKey(key);
  if (!k[0]) return ci.byId[k[1]] ? { tid: String(k[1]), comp: null } : null;
  var slug = String(k[1]).toLowerCase();
  var hit = ci.list.filter(function (r) { return String(r.slug || '').toLowerCase() === slug && (r.comps || []).indexOf(k[0]) >= 0; })[0] ||
    ci.list.filter(function (r) { return String(r.slug || '').toLowerCase() === slug; })[0];
  return hit ? { tid: String(hit.id), comp: k[0] } : null;
}
function clubComp(doc, want) {
  var live = (doc.seasons || []).filter(function (s) { return s.source === 'live' && FB.comp(s.comp) && FB.comp(s.comp).ok; });
  if (want && live.some(function (s) { return s.comp === want; })) return want;
  var lg = live.filter(function (s) { return s.kind === 'league'; })[0];
  if (doc.home && live.some(function (s) { return s.comp === doc.home; })) return doc.home;
  if (lg) return lg.comp;
  live.sort(function (a, b) { return (b.played || 0) - (a.played || 0); });
  return live.length ? live[0].comp : (want && FB.comp(want) ? want : doc.home || null);
}

function compareClubs(el, ka, kb) {
  return Promise.all([FB.clubsIndex(), FB.load('pool.json'), FB.load('nations.json')]).then(function (arr) {
    if (!FB.alive(el)) return;
    var ci = arr[0], pool = arr[1] || {}, nat = arr[2] || {};
    var R = [resolveClub(ka, ci), resolveClub(kb, ci)];
    if (!R[0] || !R[1]) {
      FB.set('lb-picked', [ka, kb].map(function (k, i) { return '<span class="qk-badge">' + sideDot(i) + esc(R[i] ? ci.byId[R[i].tid].name : k + ': not found') + '</span>'; }).join(' v '));
      FB.set('lb-body', FB.empty('Club not found', 'Use the search boxes to pick two clubs.'));
      return;
    }
    if (splitKey(ka)[0] || splitKey(kb)[0]) FB.setHashQuiet('#/clubs/h2h?a=' + R[0].tid + '&b=' + R[1].tid);
    return Promise.all(R.map(function (r) { return FB.load('clubs/' + r.tid + '.json'); })).then(function (docs) {
      if (!FB.alive(el)) return;
      var K = R.map(function (r, i) {
        var doc = docs[i] || { id: r.tid, name: ci.byId[r.tid].name, seasons: [], years: [] };
        var comp = clubComp(doc, r.comp);
        return { tid: r.tid, doc: doc, comp: comp, team: (doc.names || {})[comp] || doc.name };
      });
      FB.set('lb-picked', K.map(function (k, i) { return '<span class="qk-badge">' + sideDot(i) + esc(k.doc.name) + (k.comp ? ' · ' + esc(FB.compName(k.comp, true)) : '') + '</span>'; }).join(' <span class="qk-muted">v</span> '));
      return Promise.all(K.map(function (k) { return k.comp ? FB.compFiles(k.comp, CLUB_FILES) : Promise.resolve({}); })).then(function (files) {
        if (!FB.alive(el)) return;
        K.forEach(function (k, i) {
          var d = files[i];
          var teams = (d.teams || {}).teams || {};
          var byId = Object.keys(teams).filter(function (n) { return String(teams[n].team_id) === k.tid; })[0];
          if (byId) k.team = byId;
          var team = k.team;
          k.d = d;
          k.row = tableRowOf(d.table, team);
          k.bands = (d.table || {}).bands || (d.probs || {}).bands || [];
          k.prob = ((d.probs || {}).teams || []).filter(function (x) { return x.team === team; })[0] || null;
          k.str = ((d.strength || {}).rows || []).filter(function (x) { return x.team === team; })[0] || null;
          k.ts = ((d.team_stats || {}).teams || {})[team] || null;
          k.tsMetrics = (d.team_stats || {}).metrics || [];
          k.an = ((d.analytics || {}).teams || {})[team] || null;
          k.anMetrics = (d.analytics || {}).team_metrics || [];
          k.perf = ((d.analytics || {}).performers || {}).teams || {};
          k.fx = (d.fixtures || {}).matches || [];
          k.players = ((d.players_live || {}).players || []).filter(function (p) { return p.team === team; });
          k.floor = (d.players_live || {}).minutes_floor || 0;
          k.pool = ((pool.clubs || []).filter(function (c) { return String(c.team_id) === k.tid; })[0]) || null;
          k.cobj = FB.comp(k.comp) || {};
        });
        /* two national teams: "If they met" from the international fit (nations.json), on the same Dixon-Coles maths */
        if (K[0].doc.national && K[1].doc.national && nat.model) {
          K.forEach(function (k) { k.pool = ((nat.teams || []).filter(function (t) { return t.team === k.doc.name; })[0]) || null; });
          pool = { model: nat.model, clubs: [] };
        }
        buildClubs(el, K, pool);
      });
    });
  });
}

function buildClubs(el, K, pool) {
  var A = K[0], B = K[1];
  var same = A.comp && A.comp === B.comp;
  var idCard = function (k, i) {
    var r = k.row, s = k.str || {}, season = (k.ts || {}).season || {};
    var meta = [];
    if (r) meta.push('<span>' + FB.ordinal(r.pos) + ' · <b>' + r.pts + '</b> pts · ' + r.w + '-' + r.d + '-' + r.l + '</span>');
    if (s.form_results) meta.push('<span>' + FB.formChips(s.form_results) + '</span>');
    if (k.pool && k.pool.rank) meta.push('<span>Pooled rank <b>#' + k.pool.rank + '</b></span>');
    var tiles = [
      FB.kpi('Strength', isNum(s.strength_ppg) ? num(s.strength_ppg, 2) : (k.pool ? num(k.pool.strength, 2) : '—'), { tip: 'Our team rating model: expected points per game against an average opponent at a neutral venue', sub: 'our model · exp. points a game' }),
      FB.kpi('Elo', isNum(s.elo) ? num(s.elo, 0) : '—', { tip: 'Our Elo rating; att and def are the attack and defence ratings of our team model (goals a match against an average side)', sub: isNum(s.attack) ? 'att ' + signed(s.attack, 2) + ' · def ' + signed(s.defence, 2) : '' }),
      FB.kpi('xG diff / match', isNum(season.xg_diff) ? signed(season.xg_diff, 2) : (isNum(season.xg) && isNum(season.xga) ? signed(season.xg - season.xga, 2) : '—'), { sub: isNum(s.luck) ? 'luck ' + signed(s.luck, 1) + ' pts' : '' }),
      FB.kpi('PPG', isNum(s.ppg) ? num(s.ppg, 2) : '—', { sub: s.played ? s.played + ' played' : '' })
    ];
    return '<section class="qk-hero fb-lb-hero ' + SIDE[i] + '"><div class="qk-hero-in">' + FB.crest(k.tid, k.doc.name, 'lg') + '<div class="fb-lb-hero-t">' +
      '<div class="qk-kicker">' + sideDot(i) + (k.comp ? FB.compLink(k.comp) : '') + '</div><h2><a href="' + esc(FB.href.club(k.tid, k.comp ? { c: k.comp } : null)) + '">' + esc(k.doc.name) + '</a></h2>' +
      '<div class="qk-hero-meta">' + meta.join('') + '</div></div></div>' + FB.kpis(tiles, 'fb-lb-kpis') + '</section>';
  };
  var hypo;
  if (A.pool && B.pool && pool.model) {
    hypo = '<div class="fb-lb-prices">' + chanceCard(A.doc.name + ' at home', A.pool, B.pool, pool.model, false) + chanceCard('Neutral venue', A.pool, B.pool, pool.model, true) + chanceCard(B.doc.name + ' at home', B.pool, A.pool, pool.model, false) + '</div>' +
      (A.pool.block && B.pool.block && A.pool.block !== B.pool.block ? FB.note('<span>The two clubs sit in different continental blocks (' + esc(A.pool.block) + ' and ' + esc(B.pool.block) + '). Few cup matches connect the blocks, so these chances carry wide error.</span>') : '');
  } else {
    hypo = FB.muted('No forecast: ' + ([A, B].filter(function (k) { return !k.pool; }).map(function (k) { return esc(k.doc.name) + ' is not in the pooled fit' + (k.doc.national ? ' (national teams are fitted separately: see <a href="#/clubs/nations">national teams</a>)' : ''); }).join('; ') || 'the pooled model is not available') + '.');
  }
  // style radar
  var styleRows = [A, B].map(function (k) {
    var p = {};
    STYLE_AXES.forEach(function (ax) {
      var key = ax[0];
      var prof = ((k.an || {}).profile || {})[key];
      var def = k.anMetrics.filter(function (m) { return m.key === key; })[0] || {};
      if (prof && isNum(prof.pct)) { p[key] = def.lower ? prof.pct : (key === 'ppda' || key === 'xg_against') ? 100 - prof.pct : prof.pct; return; }
      var fb = STYLE_FALLBACK[key];
      var s = ((k.ts || {}).season || {}).pct || {};
      if (fb && isNum(s[fb])) p[key] = s[fb];
    });
    return p;
  });
  var styleAxes = STYLE_AXES.filter(function (ax) { return styleRows.some(function (r) { return isNum(r[ax[0]]); }); });
  // metric table
  var defs = [];
  [A, B].forEach(function (k) { (k.anMetrics.length ? k.anMetrics : k.tsMetrics.map(function (m) { return { key: m.key, label: m.label, fmt: m.fmt, lower: m.lower, group: 'Season averages' }; })).forEach(function (m) { if (!defs.filter(function (x) { return x.key === m.key; }).length) defs.push(m); }); });
  var valueOf = function (k, key) { var a = ((k.an || {}).profile || {})[key]; if (a && isNum(a.v)) return a.v; var s = (k.ts || {}).season || {}; return isNum(s[key]) ? s[key] : null; };
  var pctOf = function (k, key) { var a = ((k.an || {}).profile || {})[key]; if (a && isNum(a.pct)) return a.pct; var s = ((k.ts || {}).season || {}).pct || {}; return isNum(s[key]) ? s[key] : null; };
  var rankOf = function (k, key) {
    var perf = (k.perf || {})[key];
    if (perf && (perf.ranking || []).length) { var ix = -1; perf.ranking.forEach(function (x, j) { if (x.team === k.team) ix = j; }); return ix >= 0 ? (ix + 1) + '/' + perf.ranking.length : null; }
    return null;
  };
  var mrows = defs.map(function (m, i) {
    var va = valueOf(A, m.key), vb = valueOf(B, m.key), qa = pctOf(A, m.key), qb = pctOf(B, m.key);
    var gap = isNum(qa) && isNum(qb) ? qa - qb : null;
    return { i: i, label: m.label, group: m.group || 'Season averages', lower: m.lower, fmt: m.fmt, va: va, vb: vb, qa: qa, qb: qb, ra: rankOf(A, m.key), rb: rankOf(B, m.key), gap: gap, ag: isNum(gap) ? Math.abs(gap) : -1,
      better: isNum(va) && isNum(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '' };
  });
  // tale of the tape (kit QK.matchupBar) on the headline team metrics
  var TAPE = ['xg_diff', 'xg_for', 'xg_against', 'sot_diff', 'field_tilt', 'big_chances', 'possession', 'ppda'];
  var tapeRows = TAPE.map(function (k) {
    var m = defs.filter(function (x) { return x.key === k; })[0];
    if (!m) return null;
    var va = valueOf(A, k), vb = valueOf(B, k);
    return isNum(va) && isNum(vb) ? { label: m.label, a: va, b: vb, better: m.lower || k === 'ppda' || k === 'xg_against' ? 'low' : 'high', fmt: function (v) { return FB.fmtMetric(v, m.fmt); } } : null;
  }).filter(Boolean);
  var tape = tapeRows.length >= 2 ? QK.matchupBar({ left: { name: A.doc.name, abbr: FB.surname(A.doc.name), logo: FB.crestUrl(A.tid) }, right: { name: B.doc.name, abbr: FB.surname(B.doc.name), logo: FB.crestUrl(B.tid) },
    rows: tapeRows, colors: [QK.cssVar('--wp-a'), QK.cssVar('--wp-b')] }) : '';
  // head to head
  var meetings = same ? A.fx.filter(function (m) { return (m.home === A.team && m.away === B.team) || (m.home === B.team && m.away === A.team); }).sort(function (x, y) { return String(x.date).localeCompare(String(y.date)); }) : [];
  var h2h = !same ? FB.muted('Different competitions this season (' + esc(FB.compName(A.comp)) + ' and ' + esc(FB.compName(B.comp)) + '): the chances above are our view of a meeting.')
    : meetings.length ? '<div class="fb-fxlist">' + meetings.map(function (m) { var f = FB.merge(m, { home_id: m.home === A.team ? A.tid : B.tid, away_id: m.home === A.team ? B.tid : A.tid }); return FB.fixtureRow(f, { slug: A.comp, date: true }); }).join('') + '</div>'
    : FB.muted('No meeting in ' + esc(FB.compName(A.comp)) + ' this season yet.');
  // season probabilities
  var bandsRows = [];
  var labels = [];
  var addL = function (key, lab) { if (!labels.filter(function (x) { return x.key === key; }).length) labels.push({ key: key, label: lab }); };
  [A, B].forEach(function (k) {
    var kd = k.cobj.kind;
    var isCup = kd === 'cup' || kd === 'playoff' || kd === 'conference';
    addL('title', isCup ? 'Winner' : 'Title');
    if (kd === 'conference') { addL('p_playoffs', 'Playoffs'); addL('shield', 'Supporters\' Shield'); }
    if (kd === 'playoff') addL('p_playoffs', 'Liguilla');
    if (kd === 'cup') addL('p_conference', 'Reaches the final');
    k.bands.forEach(function (b) { addL('band:' + b.key, b.label); });
    addL('exp_pts', 'Expected points'); addL('range', '5th–95th percentile of points');
  });
  var cell = function (k, key) {
    var r = k.row || {}, p = k.prob || {};
    var kd = k.cobj.kind;
    var isCup = kd === 'cup' || kd === 'playoff' || kd === 'conference';
    var bands = r.bands || p.bands || {};
    if (key === 'title') return pct(isCup ? (isNum(p.p_cup) ? p.p_cup : r.p_title) : (isNum(r.p_title) ? r.p_title : p.p_title), 1);
    if (key === 'shield') return pct(p.p_title, 1);
    if (key === 'p_playoffs' || key === 'p_conference') return isNum(p[key]) ? pct(p[key], 1) : '—';
    if (key.indexOf('band:') === 0) { var bk = key.slice(5); return isNum(bands[bk]) ? pct(bands[bk], 1) : '—'; }
    if (key === 'exp_pts') return isNum(r.exp_pts) ? num(r.exp_pts, 1) : isNum(p.exp_pts) ? num(p.exp_pts, 1) : '—';
    if (key === 'range') return isNum(r.p05) ? num(r.p05, 0) + '–' + num(r.p95, 0) : '—';
    return '—';
  };
  var unsim = [A, B].some(function (k) { return k.cobj.unsimulated; });
  bandsRows = labels.map(function (l) { return { label: l.label, a: cell(A, l.key), b: cell(B, l.key) }; }).filter(function (r) { return r.a !== '—' || r.b !== '—'; });
  // year by year
  var eras = [];
  [A, B].forEach(function (k) { (k.doc.years || []).forEach(function (y) { if (eras.indexOf(y.era) < 0) eras.push(y.era); }); });
  eras.sort(function (x, y) { return FB.eraKey(y) - FB.eraKey(x); });
  var yrRows = eras.slice(0, 10).map(function (e) {
    var ya = (A.doc.years || []).filter(function (y) { return y.era === e; })[0], yb = (B.doc.years || []).filter(function (y) { return y.era === e; })[0];
    var rec = function (y) { return y ? y.w + '-' + y.d + '-' + y.l : '—'; };
    var ppg = function (y) { return y && y.played ? (3 * y.w + y.d) / y.played : null; };
    return { era: e, ra: rec(ya), ga: ya ? ya.gf + '–' + ya.ga : '—', pa: ppg(ya), wa: ya && ya.won ? ya.won : [], rb: rec(yb), gb: yb ? yb.gf + '–' + yb.ga : '—', pb: ppg(yb), wb: yb && yb.won ? yb.won : [], parta: ya && ya.record === 'partial', partb: yb && yb.record === 'partial' };
  });

  el.querySelector('#lb-body').innerHTML =
    '<div class="fb-lb-pair">' + idCard(A, 0) + idCard(B, 1) + '</div>' +
    FB.card('If they met', 'Our chance at each venue, worked out in your browser from the pooled Dixon-Coles fit' + (pool.model ? ' (rho ' + num(pool.model.rho, 3) + ', home advantage ' + num(pool.model.home_adv, 3) + ')' : '') + '.', hypo, { cls: 'fb-mt' }) +
    (tape ? FB.card('Tale of the tape', 'Season averages in each club\'s own competition; the longer, solid side is the better one.', tape, { cls: 'fb-mt' }) : '') +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Style', 'Percentiles within each club\'s competition; pressing and xG against are flipped so outward is better.', styleAxes.length >= 3 ? FB.chartBox('lb-style', 380, 'Style radar') : FB.muted('No style percentiles for these clubs yet.'), { span: 6 }) +
      FB.card('Head to head this season', same ? esc(FB.compName(A.comp)) : '', h2h, { span: 6 })
    ) + '</div>' +
    FB.card('Every team metric', 'Season averages with each club\'s percentile and rank in its own competition. Bold marks the better raw figure; ↓ marks metrics where lower is better.', defs.length ? '<div id="lb-cm"></div>' : FB.muted('No team-stat sheets for these clubs yet.'), { cls: 'fb-mt', flush: !!defs.length }) +
    '<div class="fb-mt">' + FB.grid(
      FB.card(sideDot(0) + esc(A.doc.name) + ': points against expected points', 'Cumulative points (solid) and xPts from xG (dashed), round by round.', FB.chartBox('lb-luck-a', 240, 'Points against xPts'), { span: 6 }) +
      FB.card(sideDot(1) + esc(B.doc.name) + ': points against expected points', 'Cumulative points (solid) and xPts from xG (dashed), round by round.', FB.chartBox('lb-luck-b', 240, 'Points against xPts'), { span: 6 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Season chances', unsim ? 'National-team competitions are not simulated.' : 'Our chances from each competition\'s season simulation.' + (same ? '' : ' Different competitions: each column reads its own club\'s bands.'), bandsRows.length && !unsim ? '<div id="lb-bands"></div>' : FB.muted('No season simulation for these clubs.'), { span: 5, flush: !!(bandsRows.length && !unsim) }) +
      FB.card('Year by year', 'Every competition each season: won-drawn-lost, goals and points per game; trophies marked.', yrRows.length ? '<div id="lb-yrs"></div>' : FB.muted('No season history.'), { span: 7, flush: !!yrRows.length })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card(sideDot(0) + esc(A.doc.name) + ': top five by rating', A.comp ? esc(FB.compName(A.comp)) : '', '<div id="lb-sq-a"></div>', { span: 6, flush: true }) +
      FB.card(sideDot(1) + esc(B.doc.name) + ': top five by rating', B.comp ? esc(FB.compName(B.comp)) : '', '<div id="lb-sq-b"></div>', { span: 6, flush: true })
    ) + '</div>' +
    '<p class="fb-cap">' + K.map(function (k) { return '<a href="' + esc(FB.href.club(k.tid)) + '">' + esc(k.doc.name) + ' →</a>'; }).join(' · ') + ' · <a href="#/clubs">Clubs on one scale →</a> · <a href="#/model/glossary">Glossary →</a></p>';

  if (styleAxes.length >= 3) FB.charts.radar(el.querySelector('#lb-style'), { axes: styleAxes.map(function (a) { return { name: a[1], max: 100 }; }),
    series: [A, B].map(function (k, i) { return { name: k.doc.name, values: styleAxes.map(function (a) { return styleRows[i][a[0]]; }), color: QK.cssVar(i ? '--c-2' : '--c-1') }; }) });
  if (defs.length) FB.table(el.querySelector('#lb-cm'), [
    { key: 'label', label: 'Metric', sticky: true, fmt: function (v, r) { return esc(v) + (r.lower ? ' <span class="qk-muted">↓</span>' : ''); } },
    { key: 'group', label: 'Group', fmt: function (v) { return '<span class="qk-muted">' + esc(v) + '</span>'; } },
    { key: 'va', label: A.doc.name, num: true, pctl: 'qa', fmt: function (v, r) { return (r.better === 'a' ? '<b class="fb-lb-win">' : '<span>') + FB.fmtMetric(v, r.fmt) + (r.better === 'a' ? '</b>' : '</span>') + (r.ra ? ' <span class="qk-muted fb-lb-rk">' + r.ra + '</span>' : ''); } },
    { key: 'ag', label: 'Gap', num: true, fmt: function (v, r) { return gapBar(r.gap); } },
    { key: 'vb', label: B.doc.name, num: true, pctl: 'qb', fmt: function (v, r) { return (r.better === 'b' ? '<b class="fb-lb-win">' : '<span>') + FB.fmtMetric(v, r.fmt) + (r.better === 'b' ? '</b>' : '</span>') + (r.rb ? ' <span class="qk-muted fb-lb-rk">' + r.rb + '</span>' : ''); } }
  ], mrows, { sort: { key: 'i', dir: 'asc' }, maxHeight: 560, caption: 'Every team metric' });
  [A, B].forEach(function (k, i) {
    var box = el.querySelector('#lb-luck-' + SIDE[i]);
    var rs = (k.an || {}).rounds;
    var series = rs && rs.length ? rs.slice().sort(function (x, y) { return (Number(x.round) || 0) - (Number(y.round) || 0); }).map(function (r) { return { label: 'R' + r.round, pts: r.pts, xpts: r.xpts }; })
      : ((k.ts || {}).matches || []).slice().reverse().map(function (r, j) { return { label: isNum(r.round) ? 'R' + r.round : 'M' + (j + 1), pts: r.res === 'W' ? 3 : r.res === 'D' ? 1 : 0, xpts: xptsOf(r.xg, r.xga) }; });
    series = series.filter(function (r) { return isNum(r.xpts); });
    if (series.length < 2) { box.style.height = 'auto'; box.innerHTML = FB.muted('Not enough matches with xG.'); return; }
    var cp = 0, cx = 0;
    var c = QK.cssVar(i ? '--c-2' : '--c-1');
    QKC.line(box, { x: series.map(function (r) { return r.label; }), yMin: 0, yFmt: function (v) { return num(v, 0); },
      series: [{ name: 'Points', color: c, data: series.map(function (r) { cp += r.pts || 0; return cp; }) }, { name: 'xPts', color: c, dash: true, data: series.map(function (r) { cx += r.xpts || 0; return Math.round(cx * 10) / 10; }) }], xName: rs && rs.length ? 'Round' : 'Match', yName: 'Cumulative points', label: 'Points against xPts' });
  });
  if (bandsRows.length && !unsim) FB.table(el.querySelector('#lb-bands'), [
    { key: 'label', label: 'Outcome', sort: false },
    { key: 'a', label: A.doc.name, num: true, sort: false, fmt: function (v) { return v; } },
    { key: 'b', label: B.doc.name, num: true, sort: false, fmt: function (v) { return v; } }
  ], bandsRows, { caption: 'Season probabilities' });
  var won = function (list) { return list.length ? ' <span class="fb-lb-cup" title="' + esc(list.map(function (s) { return FB.compName(s); }).join(', ')) + '">🏆' + (list.length > 1 ? '×' + list.length : '') + '</span>' : ''; };
  if (yrRows.length) FB.table(el.querySelector('#lb-yrs'), [
    { key: 'era', label: 'Season', sticky: true, sort: false, fmt: function (v) { return '<b class="fb-num">' + esc(v) + '</b>'; } },
    { key: 'ra', label: FB.surname(A.doc.name) + ' W-D-L', num: true, sort: false, fmt: function (v, r) { return esc(v) + won(r.wa) + (r.parta ? ' <span class="fb-cov partial" data-tip="An archive table without W-D-L is in this season">Partial</span>' : ''); } },
    { key: 'pa', label: 'PPG', num: true, sort: false, fmt: function (v) { return num(v, 2); } },
    { key: 'rb', label: FB.surname(B.doc.name) + ' W-D-L', num: true, sort: false, fmt: function (v, r) { return esc(v) + won(r.wb) + (r.partb ? ' <span class="fb-cov partial" data-tip="An archive table without W-D-L is in this season">Partial</span>' : ''); } },
    { key: 'pb', label: 'PPG', num: true, sort: false, fmt: function (v) { return num(v, 2); } }
  ], yrRows, { caption: 'Year by year' });
  [A, B].forEach(function (k, i) {
    var box = el.querySelector('#lb-sq-' + SIDE[i]);
    var rows = k.players.filter(function (p) { return isNum(p.rating) && (p.qualified || p.minutes >= (k.floor || 0)); }).sort(function (x, y) { return y.rating - x.rating; }).slice(0, 5);
    if (!rows.length) { box.innerHTML = FB.muted('No qualified players yet.'); return; }
    FB.table(box, [
      { key: 'name', label: 'Player', sticky: true, sort: false, fmt: function (v, r) { return FB.posBadge(r.position) + ' ' + FB.playerLink(r.player_id, v, { q: { c: k.comp } }); } },
      { key: 'minutes', label: 'Min', num: true, sort: false },
      { key: 'rating', label: 'Rating', num: true, sort: false, fmt: function (v, r) { return '<b>' + num(v, 2) + '</b>'; }, pctl: 'prt' },
      { key: 'goals', label: 'G', num: true, sort: false }, { key: 'assists', label: 'A', num: true, sort: false },
      { key: 'xg', label: 'xG', num: true, sort: false, fmt: function (v) { return num(v, 1); } }
    ], rows.map(function (p) { return FB.merge(p, { prt: (p.pct || {}).rating }); }), { caption: 'Top five by rating' });
  });
}

FB.labTools = { dcMatrix: dcMatrix };
})(window.FB);
