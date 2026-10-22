/* The Quant Ace — Design System 2.0 helpers (TA.v2): the comparison metric sets, peer groups and sample floors from
 * docs/METRICS_SPEC.md (machine copy docs/_design/metrics/tennis.json), defined once here and read by the player
 * page, the players leaderboard, compare and head to head; plus small layout helpers on the kit (QK, QKC).
 *
 *   SETS[group]                    headline metric ids per peer group (atp_all, wta_hard, ...), in the spec's order
 *   group(T, surface)              the group id: '<tour>_all' or '<tour>_<surface>'
 *   peer(T, surface, cat)          "ATP players, 18+ matches" / "WTA on clay, 8+ clay matches"
 *   inPool(p, surface, cat)        does a catalogue row meet the group's minimum
 *   value(p, key, surface)         the metric value for the group (surface rates from values_surface; Elo from values)
 *   pctl(p, key, surface, cat)     the percentile (payload pct / pct_surface; surface Elo ranked here among the pool)
 *   pctGroups(p, cat, T, surface)  QK.pctCard groups for one player (early = short of the spec's M50)
 *   similar(T, pid, cat, k)        the spec's similar players: weighted Euclidean on z-scores within the tour
 *   card(title, sub, body, o)  chart(id, h, label)
 *
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (TA) {
'use strict';

const V = TA.v2 = {};
const esc = TA.esc, isNum = TA.isNum;

/* Headline sets (METRICS_SPEC.md, Tennis: "set": "headline", in order). */
V.SETS = {
  atp_all: ['elo', 'games_won_pct', 'hold', 'brk', 'win_v_top50', 'elo_clay', 'elo_grass'],
  wta_all: ['elo', 'games_won_pct', 'hold', 'brk', 'dominance', 'ace_pct', 'win_v_top50', 'elo_clay', 'elo_grass'],
  atp_hard: ['elo_hard', 'games_won_pct', 'hold', 'brk', 'win_pct', 'win_v_top50'],
  atp_clay: ['elo_clay', 'elo', 'games_won_pct', 'hold', 'brk', 'win_pct'],
  atp_grass: ['elo_grass', 'elo', 'games_won_pct', 'hold', 'brk', 'win_pct'],
  wta_hard: ['elo_hard', 'games_won_pct', 'hold', 'brk', 'win_pct', 'dominance', 'ace_pct'],
  wta_clay: ['elo_clay', 'elo', 'games_won_pct', 'hold', 'brk', 'win_pct', 'dominance', 'ace_pct'],
  wta_grass: ['elo_grass', 'elo', 'games_won_pct', 'hold', 'brk', 'win_pct', 'ace_pct']
};
/* Where each metric stabilises (M50, matches; "stat" = matches with WTA statistics), per group, from the spec. */
V.M50 = {
  atp_all: { games_won_pct: 11.7, win_v_top50: 26.7 },
  wta_all: { games_won_pct: 13.3, win_v_top50: 28.5, dominance: 17.8, ace_pct: 3.1 },
  atp_hard: { games_won_pct: 11.9, win_pct: 19.1, win_v_top50: 26.1 },
  atp_clay: { games_won_pct: 13.9, win_pct: 21.4 },
  atp_grass: { games_won_pct: 88.7 },
  wta_hard: { games_won_pct: 17.6, win_pct: 23.7, dominance: 20.5, ace_pct: 3.5 },
  wta_clay: { games_won_pct: 26.2, win_pct: 50.3, dominance: 22.6, ace_pct: 3.4 },
  wta_grass: { ace_pct: 2.0 }
};
V.STAT_KEYS = { dominance: 1, ace_pct: 1 };
/* Display names and one-line explanations (the spec's "display" and "explanation"). */
V.META = {
  elo: ['Elo rating', 'Overall strength rating from every result, adjusted for the opponent’s rating.', 'rating'],
  elo_hard: ['Hard-court Elo', 'Strength rating from matches on hard courts only.', 'rating'],
  elo_clay: ['Clay Elo', 'Strength rating from matches on clay only.', 'rating'],
  elo_grass: ['Grass Elo', 'Strength rating from matches on grass only.', 'rating'],
  games_won_pct: ['Games won', 'Share of all games won in completed sets; steadier than win % because every game counts.', 'pct'],
  hold: ['Hold (inferred)', 'How often the player holds serve against an average tour returner, inferred from set scores.', 'pct'],
  brk: ['Break (inferred)', 'How often the player breaks an average tour server, inferred from set scores.', 'pct'],
  hold_plus_break: ['Serve + return', 'Hold % plus break %, inferred from scores: the best single predictor beyond Elo.', 'pct'],
  win_v_top50: ['Win % v top 50', 'Share of matches won against opponents ranked in the top 50.', 'pct'],
  win_pct: ['Win %', 'Share of tour-level matches won.', 'pct'],
  dominance: ['Dominance ratio', 'Return points won % divided by serve points lost %; above 1.0 wins more return points than it concedes on serve. WTA matches with statistics, 2016 on (not the Slams).', '2'],
  ace_pct: ['Ace rate', 'Aces per serve point. WTA matches with statistics, 2016 on (not the Slams).', 'pct']
};
V.label = (k, surface) => (k === 'win_pct' && surface ? 'Win % on ' + surface : ((V.META[k] || [])[0] || k));
V.SURF = ['hard', 'clay', 'grass'];
V.group = (T, surface) => (T === 'wta' ? 'wta' : 'atp') + '_' + (surface && V.SURF.indexOf(surface) >= 0 ? surface : 'all');
V.set = (T, surface) => V.SETS[V.group(T, surface)] || [];
V.floor = (cat, surface) => (surface ? (((cat || {}).surface_floor || {})[surface] || { hard: 10, clay: 8, grass: 5 }[surface]) : ((cat || {}).floor || 20));
V.peer = (T, surface, cat) => (T === 'wta' ? 'WTA' : 'ATP') + (surface ? ' on ' + surface + ', ' + V.floor(cat, surface) + '+ ' + surface + ' matches' : ' players, ' + V.floor(cat) + '+ matches');
V.inPool = (p, surface, cat) => {
  if (!p) return false;
  if (!surface) return p.qualified === true;
  const s = ((p.values_surface || {})[surface]) || null;
  return !!s && isNum(s.matches) && s.matches >= V.floor(cat, surface);
};
V.isElo = k => /^elo(_|$)/.test(k);
V.value = (p, k, surface) => {
  if (!p) return null;
  if (surface && !V.isElo(k)) return ((p.values_surface || {})[surface] || {})[k];
  return (p.values || {})[k];
};
/* Surface Elo (and Elo on a surface card) is ranked in the tour pool by the payload; the spec's interim rule ranks it
 * here among the players who meet the surface floor. Cached per catalogue and surface. */
const RANKS = typeof WeakMap === 'function' ? new WeakMap() : null;
function eloPct(cat, surface, k, v) {
  if (!isNum(v)) return null;
  let m = RANKS ? RANKS.get(cat) : null;
  if (!m) { m = {}; if (RANKS) RANKS.set(cat, m); }
  const key = surface + ':' + k;
  if (!m[key]) {
    const P = cat.players || {};
    m[key] = Object.keys(P).filter(id => V.inPool(P[id], surface, cat)).map(id => (P[id].values || {})[k]).filter(isNum).sort((a, b) => a - b);
  }
  const arr = m[key];
  if (arr.length < 5) return null;
  let lo = 0; while (lo < arr.length && arr[lo] < v) lo++;
  let hi = lo; while (hi < arr.length && arr[hi] === v) hi++;
  return 100 * (lo + (hi - lo) / 2) / arr.length;
}
V.pctl = (p, k, surface, cat) => {
  if (!p) return null;
  if (surface) return V.isElo(k) ? (V.inPool(p, surface, cat) ? eloPct(cat, surface, k, (p.values || {})[k]) : null) : (((p.pct_surface || {})[surface]) || {})[k];
  return (p.pct || {})[k];
};
V.fmt = (k, v, meta) => {
  if (!isNum(v)) return '—';
  const f = (V.META[k] || [])[2] || ((meta || {})[k] || {}).fmt;
  if (f === 'rating') return Math.round(v).toLocaleString('en-GB');
  if (f === 'pct') return (Math.abs(v) <= 1.5 ? v * 100 : v).toFixed(1) + '%';
  if (f === '2') return Number(v).toFixed(2);
  return TA.fmtVal ? TA.fmtVal(v, f) : Number(v).toFixed(2);
};
V.sample = (p, k, surface) => {
  if (V.STAT_KEYS[k]) return (p.values || {}).stats_matches;
  return surface ? ((p.values_surface || {})[surface] || {}).matches : p.matches;
};
/* QK.pctCard groups: strength, results, serve and return (inferred), serve statistics (WTA). */
const GROUPS = [['Strength', ['elo', 'elo_hard', 'elo_clay', 'elo_grass']], ['Results', ['games_won_pct', 'win_pct', 'win_v_top50']],
  ['Serve and return, inferred from scores', ['hold', 'brk']], ['Serve statistics (WTA)', ['dominance', 'ace_pct']]];
V.pctGroups = (p, cat, T, surface) => {
  const set = V.set(T, surface), m50 = V.M50[V.group(T, surface)] || {};
  return GROUPS.map(g => ({
    label: g[0],
    rows: set.filter(k => g[1].indexOf(k) >= 0).map(k => {
      const pc = V.pctl(p, k, surface, cat);
      if (!isNum(pc)) return null;
      const n = V.sample(p, k, surface);
      return { label: V.label(k, surface), pctl: pc, value: V.fmt(k, V.value(p, k, surface)), tip: (V.META[k] || [])[1] || '', early: isNum(m50[k]) && isNum(n) && n < m50[k] };
    }).filter(Boolean)
  }));
};
V.sampleLine = (p, T, surface, cat) => {
  if (!p) return '';
  const n = surface ? ((p.values_surface || {})[surface] || {}).matches : p.matches;
  const st = (p.values || {}).stats_matches;
  return (isNum(n) ? n + (surface ? ' ' + surface : '') + ' matches' : '') + (T === 'wta' && isNum(st) && st > 0 ? ' · ' + st + ' with WTA statistics' : '') + ' · peers need ' + V.floor(cat, surface);
};
/* Similar players (spec: tour view features, z-scored within tour and season among qualified players, weights = YoY r
 * floored at 0.2 and capped at 0.8, surface Elos as the difference from overall Elo). */
V.SIM = {
  atp: { elo: 0.8, hold: 0.8, brk: 0.8, elo_clay: 0.74, elo_grass: 0.68, games_won_pct: 0.72, tb_per_set: 0.57 },
  wta: { elo: 0.75, hold: 0.8, brk: 0.8, elo_clay: 0.64, elo_grass: 0.65, games_won_pct: 0.62, ace_pct: 0.8, first_in: 0.78 }
};
V.similar = (T, pid, cat, k) => {
  const P = (cat && cat.players) || {};
  const me = P[pid];
  if (!me || !me.qualified) return [];
  const W = V.SIM[T === 'wta' ? 'wta' : 'atp'];
  const feat = (p, f) => { const v = p.values || {}; if (f === 'elo_clay' || f === 'elo_grass') return isNum(v[f]) && isNum(v.elo) ? v[f] - v.elo : null; return v[f]; };
  const ids = Object.keys(P).filter(id => P[id] && P[id].qualified);
  const stats = {};
  Object.keys(W).forEach(f => {
    const xs = ids.map(id => feat(P[id], f)).filter(isNum);
    const m = xs.reduce((a, b) => a + b, 0) / (xs.length || 1);
    const sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) * (b - m), 0) / Math.max(1, xs.length - 1)) || 1;
    stats[f] = [m, sd];
  });
  const z = (p, f) => { const v = feat(p, f); return isNum(v) ? (v - stats[f][0]) / stats[f][1] : null; };
  return ids.filter(id => id !== pid).map(id => {
    let s = 0, w = 0;
    Object.keys(W).forEach(f => { const a = z(me, f), b = z(P[id], f); if (isNum(a) && isNum(b)) { s += W[f] * (a - b) * (a - b); w += W[f]; } });
    return { id: id, d: w ? Math.sqrt(s / w) : null };
  }).filter(x => isNum(x.d)).sort((a, b) => a.d - b.d).slice(0, k || 5);
};

/* ── layout ── */
V.card = (title, sub, body, o) => {
  o = o || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + (o.html ? title : esc(title)) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
V.chart = (id, h, label) => '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>';
V.kicker = (T, Y, extra) => [TA.tourName(T), Y || TA.state.year, extra].filter(Boolean).join(' · ');
V.seg = (id, opts, cur, label) => '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label || 'View') + '">' + opts.map(o => '<button type="button" aria-pressed="' + (String(o[0]) === String(cur)) + '" data-value="' + esc(o[0]) + '">' + esc(o[1]) + '</button>').join('') + '</div>';
/* A kit player object for chance rows and headers (no team: the country code rides as the monogram). */
V.ent = (T, pid) => ({ name: TA.playerShort(T, pid), abbr: TA.playerCountry(T, pid) || '', href: TA.playerHref(T, pid) });

})(window.TA);
