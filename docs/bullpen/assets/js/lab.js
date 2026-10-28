/* The Quant Bullpen — the lab (#/<L>/lab): any two metrics for hitters or pitchers.
 *
 * The Footballer/Hardwood/Ace lab for baseball: scatter any two catalogue metrics for one season
 * window, with presets for the questions the models were built to answer (stuff against results,
 * bat speed against xwOBA+, decision value against chase rate, VAA against whiff rate, xwOBA+
 * against Savant's xwOBA, framing against pop time), colour by team, position or any metric,
 * medians as quadrants, the corners labelled, a search highlight and the group ranked below.
 * Rates can be shrunk towards the median by each metric's own stabilisation point:
 * shrunk = (n · x + k · median) / (n + k), with k = n₀.₇ · 3/7 (the sample at which split-half
 * reliability reaches 0.7 is n₀.₇ = k · 7/3 under r(n) = n / (n + k)).
 *
 * Address: ?kind=hitter|sp|rp|team&x=<key>&y=<key>&q=<highlight> (Broad), or ?within=pos&pos=C|1B|2B|3B|SS|CF|LF-RF|DH|SP|RP (Position);
 * the old ?kind=pitcher opens the starters.
 * "Compare within" (QK.within): Broad is hitters, starting pitchers or relief pitchers (and NPB's clubs): starters and
 * relievers are always separate groups, never pooled; Position is the metrics spec's position and role groups
 * (baseball.json: catchers ... designated hitters, starters, relievers, on the rows' pos / role). The scatter, ranks,
 * percentiles on screen, medians, metric order (the group's spec headline first), the default minimum (the spec floor
 * prorated by team games: 200 PA, starters 300 BF, relievers 120 BF, x team games / 162) and the "Most like" strip
 * (the five nearest to a highlighted player on the group's headline metrics) all follow the group.
 * NPB (since 15 October 2026): data/npb/<S>/lab.json in the same shape with a third kind, "team" (clubs), and
 * "n_label" (PA / BF / G); registered with BP.routeNpb.
 * Data: data/<L>/<S>/lab.json, column-oriented {"fields", "metrics", "rows", "kinds"}; a "kind" field
 * (hitter|pitcher) and a "season"/"window" field select rows; "windows": {label: {...}} is also read.
 * Falls back to the hitters and pitchers catalogues. Uses BP.gk.
 * Round 5: the axis pickers list our model metrics first ("Our models", then the spec's headline box-score metrics,
 * then the payload's groups), with the spec's names (BP.ui.label); our metrics carry the cobalt tag on the axes line
 * and in the ranked table's heads, and a cobalt strip says which model each comes from. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const PRESETS = [
  ['pitcher', ['stuff_plus'], ['rv100', 'ra9'], 'Stuff+ against run value per 100 pitches: does the physical pitch predict results?'],
  ['hitter', ['bat_speed_adj', /bat_speed_adj/, 'bat_speed', /bat_speed/], ['xwoba_plus', /xwoba_?plus/], 'Bat speed against xwOBA+: does swinging harder pay?'],
  ['hitter', ['chase_pct'], ['dv', 'decision_value'], 'Decision value against chase rate: is chasing the whole story?'],
  ['pitcher', ['fb_vaa', /vaa/], ['whiff_pct', /whiff/], 'Fastball VAA against whiff rate: flat fastballs and swings and misses'],
  ['hitter', ['xwoba_savant', /savant/], ['xwoba_plus', /xwoba_?plus/], 'xwOBA+ against Savant xwOBA: where spray, park and speed change the answer'],
  ['hitter', ['pop_time', /pop/, 'arm'], ['framing_runs', /framing/], 'Framing runs against pop time or arm (catchers)'],
  ['pitcher', ['stuff_plus', /stuff/], ['location_plus', /location/], 'Stuff+ against Location+: two ways to get outs'],
  ['hitter', ['woba', /^woba$/], ['xwoba_plus', /xwoba_?plus/], 'wOBA against xwOBA+: who has been lucky?'],
  ['pitcher', ['k_pct', /^k_?pct/], ['bb_pct', /^bb_?pct/], 'Strikeouts against walks'],
  ['hitter', ['barrel_pct', /barrel/], ['k_pct', /^k_?pct/], 'Power against contact']
];
const NO_SHRINK = /^(pa|bf|n|g|gs|age|season|ip|war.*|.*_runs|runs.*|decision_value|dv|dv_zone|dv_chase|rv|re24|wpa.*|bsr|wsb|oaa.*|rar|pos_runs|repl_runs)$|plus$|_plus|^proj_|^pre_/;
let LAB = null, LABK = '', LAB_PRESETS = [], N_LABEL = {}, LAB_META = {};
/* NPB: where the play-by-play metrics come from, and how the expected stats were fitted and checked (npb/<S>/lab.json). */
function npbNote(keys) {
  const k = K();
  if (LAB_META.level !== 'npb') return '';
  const pb = LAB_META.pbp || {}, cv = pb.coverage || {};
  let h = '<br><strong>NPB play-by-play</strong>: ' + (pb.available ? k.int(cv.games_with_pbp) + ' of ' + k.int(cv.games_final) + ' regular-season games this season' +
    (k.isNum(cv.games_with_pitch_counts) ? ' (' + k.int(cv.games_with_pitch_counts) + ' with pitch counts)' : '') : 'not available for this season (it starts in 2016); the stat pages\' metrics only') + '.';
  const ex = LAB_META.expected;
  if (ex && keys.some(x => /^x|woba_minus_x/.test(x))) {
    h += ' <strong>Expected stats</strong>: ' + (ex.out_of_sample ? 'fitted on earlier seasons only (out of sample)' : 'fitted on seasons that include this one or later (in sample until enough earlier seasons exist)') + '.';
    ['bat', 'pit'].forEach(kd => {
      const v = (ex.validation || {})[kd];
      if (!v) return;
      h += ' ' + (kd === 'bat' ? 'Hitters' : 'Pitchers') + ': next season\'s BABIP correlates ' + k.num(v.corr_next.xbabip, 2) + ' with xBABIP and ' + k.num(v.corr_next.babip, 2) + ' with BABIP itself (' + k.int(v.n) + ' player-seasons).';
    });
  }
  return h;
}
/* the sample's unit by kind (NPB's lab.json carries n_label; clubs count games) */
function nU(kind) { const kd = kind || S0.kind; return N_LABEL[kd] || (kd === 'pitcher' ? 'BF' : kd === 'team' ? 'G' : 'PA'); }
function nLong(kind) { const u = nU(kind); return u === 'BF' ? 'Batters faced' : u === 'G' ? 'Games' : 'Plate appearances'; }
/* The peer groups: code -> [kind, BP.ui.SETS key, name, test(pos)]. Starters and relievers are separate groups under
   both Broad and Position. */
const POSU = p => String(p || '').toUpperCase();
const ROLEP = p => (BP.ui.ROLE_OF_POS || {})[POSU(p)] || '';
const GROUPS = {
  H: ['hitter', 'ALL', 'Hitters', () => true],
  SP: ['pitcher', 'SP', 'Starting pitchers', p => POSU(p) === 'SP'],
  RP: ['pitcher', 'RP', 'Relief pitchers', p => POSU(p) === 'RP'],
  T: ['team', 'TEAM', 'Clubs', () => true],
  C: ['hitter', 'C', 'Catchers', p => ROLEP(p) === 'C'],
  '1B': ['hitter', '1B', 'First basemen', p => ROLEP(p) === '1B'],
  '2B': ['hitter', '2B', 'Second basemen', p => ROLEP(p) === '2B'],
  '3B': ['hitter', '3B', 'Third basemen', p => ROLEP(p) === '3B'],
  SS: ['hitter', 'SS', 'Shortstops', p => ROLEP(p) === 'SS'],
  CF: ['hitter', 'CF', 'Centre fielders', p => ROLEP(p) === 'CF'],
  'LF-RF': ['hitter', 'LF/RF', 'Corner outfielders', p => ROLEP(p) === 'LF/RF'],
  DH: ['hitter', 'DH', 'Designated hitters', p => ROLEP(p) === 'DH']
};
const BROAD = ['H', 'SP', 'RP', 'T'];
const POSN = ['C', '1B', '2B', '3B', 'SS', 'CF', 'LF-RF', 'DH', 'SP', 'RP'];
let TG = null;     // the season's team games (catalogues' team_games; NPB: the clubs' most games), for prorating floors
function code() { return S0.within === 'pos' ? S0.pg : S0.bg; }
function grp() { return GROUPS[code()] || GROUPS.H; }
function inGroup(r) { const g = grp(); return g[0] === 'team' || g[3](raw(r, 'pos')); }
/* the spec floor of the group, prorated by team games (BP.ui.floorOf: 200 PA, 300 BF starters, 120 BF relievers) */
function specFloor() { const g = grp(); if (g[0] === 'team') return 0; const f = BP.ui.floorOf ? BP.ui.floorOf(g[1], TG) : null; return f ? f.value : 0; }
function kindNoun() { return grp()[2].toLowerCase(); }
const S0 = { kind: 'hitter', within: 'broad', bg: 'H', pg: 'C', win: null, min: null, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '' };
const MU = {};
/* the hash: the group and, for custom axes, the axes (?kind= under Broad, ?within=pos&pos= under Position) */
function writeHash() {
  try {
    const h = location.hash || '#/lab', i = h.indexOf('?'), base = i < 0 ? h : h.slice(0, i);
    const keep = (i < 0 ? '' : h.slice(i + 1)).split('&').filter(kv => kv && ['kind', 'within', 'pos', 'x', 'y', 'q'].indexOf(kv.split('=')[0]) < 0);
    const add = [];
    if (S0.within === 'pos') add.push('within=pos', 'pos=' + encodeURIComponent(S0.pg));
    else if (S0.bg !== 'H') add.push('kind=' + ({ SP: 'sp', RP: 'rp', T: 'team' }[S0.bg] || 'hitter'));
    if (S0.preset < 0 && S0.x && S0.y) add.push('x=' + encodeURIComponent(S0.x), 'y=' + encodeURIComponent(S0.y));
    if (S0.q && S0.q.trim()) add.push('q=' + encodeURIComponent(S0.q.trim()));
    const q = keep.concat(add).join('&');
    history.replaceState(null, '', base + (q ? '?' + q : ''));
  } catch (e) { /* no history API */ }
}

/* The payload as {kinds: {hitter: {idx, meta, metrics, rows}, pitcher: ...}, windows: [...]}. */
function prep(raw, hc, pc) {
  const k = K();
  LAB_META = {};
  const kinds = {};
  const fromCols = (d, kindDefault) => {
    const idx = {};
    (d.fields || []).forEach((f, i) => { idx[f] = i; });
    const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
    al('id', ['pid', 'player', 'player_id']); al('win', ['season', 'window', 'year']); al('kind', ['role_kind', 'type']);
    const meta = k.metaOf(d.metrics || []);
    (d.rows || []).forEach(r => {
      const kd = idx.kind !== undefined ? String(r[idx.kind] || kindDefault || 'hitter') : (kindDefault || 'hitter');
      const kk = /pit/.test(kd) ? 'pitcher' : /catch/.test(kd) ? 'hitter' : kd;
      const g = kinds[kk] || (kinds[kk] = { idx: idx, meta: meta, rows: [] });
      g.rows.push(r);
    });
    Object.keys(kinds).forEach(kk => { const g = kinds[kk]; g.metrics = (d.metrics || []).filter(m => g.idx[m.key] !== undefined && (!m.kind || m.kind === kk || (m.kinds || []).indexOf(kk) >= 0) && g.rows.some(r => k.isNum(r[g.idx[m.key]]))); });
  };
  if (raw && raw.ok !== false && raw.metrics && !Array.isArray(raw.metrics) && raw.rows && !Array.isArray(raw.rows)) {
    // analytics/leaders.lab: {"fields": [pid, name, team, pos, n], "metrics": {kind: [METRIC]}, "rows": {kind: [[...fields, ...metric values]]}}
    Object.keys(raw.rows).forEach(kd => {
      const ms = raw.metrics[kd] || [];
      const fields = (raw.fields || ['pid', 'name', 'team', 'pos', 'n']).concat(ms.map(m => m.key));
      const idx = {};
      fields.forEach((f, i) => { idx[f] = i; });
      if (idx.id === undefined && idx.pid !== undefined) idx.id = idx.pid;
      const kk = /pit/.test(kd) ? 'pitcher' : /team|club/.test(kd) ? 'team' : 'hitter';
      kinds[kk] = { idx: idx, meta: k.metaOf(ms), rows: raw.rows[kd] || [], metrics: ms.filter(m => (raw.rows[kd] || []).some(r => k.isNum(r[idx[m.key]]))) };
    });
    LAB_PRESETS = (raw.presets || []).filter(p => p && p.kind && p.x && p.y);
    N_LABEL = raw.n_label || {};
    LAB_META = { pbp: raw.pbp || null, expected: raw.expected || null, level: raw.level || '' };
  } else if (raw && raw.ok !== false && raw.windows && typeof raw.windows === 'object') {
    Object.keys(raw.windows).forEach(w => {
      const d = raw.windows[w];
      if (!d || !d.fields) return;
      const f = d.fields.indexOf('window') < 0 && d.fields.indexOf('season') < 0 ? d.fields.concat(['window']) : d.fields;
      fromCols({ fields: f, metrics: d.metrics || raw.metrics, rows: (d.rows || []).map(r => (f.length > d.fields.length ? r.concat([w]) : r)) }, d.kind);
    });
  } else if (raw && raw.ok !== false && raw.fields) fromCols(raw);
  else {
    // Fallback: the season catalogues, one window.
    [[hc, 'hitter'], [pc, 'pitcher']].forEach(x => {
      const c = x[0];
      if (!c) return;
      const keys = (c.metrics || []).map(m => m.key);
      const fields = ['id', 'name', 'team', 'pos', 'n', 'win'].concat(keys);
      fromCols({ fields: fields, metrics: c.metrics, rows: Object.keys(c.players).map(pid => { const p = c.players[pid]; return [pid, p.name, p.team, x[1] === 'pitcher' ? k.roleOf(p) : p.pos, k.sampleOf(p, x[1]), 'season'].concat(keys.map(kk => (p.values || {})[kk])); }) }, x[1]);
    });
  }
  Object.keys(kinds).forEach(kk => {
    const g = kinds[kk];
    const al = (want, list) => { if (g.idx[want] === undefined) for (let i = 0; i < list.length; i++) if (g.idx[list[i]] !== undefined) { g.idx[want] = g.idx[list[i]]; break; } };
    al('n', kk === 'pitcher' ? ['bf', 'tbf', 'n', 'pa'] : ['pa', 'n']);
    al('pos', ['role', 'position']);
    const wins = g.idx.win !== undefined ? Array.from(new Set(g.rows.map(r => String(r[g.idx.win])))) : ['season'];
    g.wins = wins.sort((a, b) => (/^\d{4}$/.test(b) ? Number(b) : 0) - (/^\d{4}$/.test(a) ? Number(a) : 0) || a.localeCompare(b));
  });
  return kinds;
}
function G() { return LAB[S0.kind] || LAB[Object.keys(LAB)[0]]; }
function raw(r, key) { const g = G(), i = g.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function meta(key) { return G().meta[key] || (key === 'n' ? { key: 'n', label: nLong(), fmt: 'int' } : { key: key, label: key }); }
function shrinkable(key) { const m = meta(key); if (S0.kind === 'team') return false; return !NO_SHRINK.test(key) && ['int', 'plus', 'signed', 'rv', 'war'].indexOf(m.fmt) < 0 && key !== 'n'; }
function kOf(key) { const m = meta(key); return K().isNum(m.stabilises_at) ? m.stabilises_at * 3 / 7 : 200; }
function lower(key) { return !!meta(key).lower; }
function label(key) { return BP.ui.label(S0.kind, key, meta(key).label || key) + (S0.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return K().fmtV(v, meta(key).fmt); }
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S0.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!K().isNum(mu)) return v;
  const n = raw(r, 'n') || 0, kk = kOf(key);
  return (n * v + kk * mu) / (n + kk);
}
function resolve(pats) {
  const ms = G().metrics;
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (typeof p === 'string') { const m = ms.find(x => x.key === p); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(x.key)); if (m) return m.key; } }
  return '';
}
function presetList() {
  const out = [];
  const seen = {};
  const has = key => G().metrics.some(m => m.key === key);       // a metric with values this season (NPB: no xwOBA before two seasons of play-by-play)
  const add = p => { if (p.x && p.y && p.x !== p.y && !seen[p.x + '|' + p.y] && G().idx[p.x] !== undefined && G().idx[p.y] !== undefined && has(p.x) && has(p.y)) { seen[p.x + '|' + p.y] = 1; out.push(p); } };
  LAB_PRESETS.filter(p => p.kind === S0.kind).forEach(p => add({ x: p.x, y: p.y, title: p.label || (p.x + ' v ' + p.y) }));
  PRESETS.filter(p => p[0] === S0.kind).forEach(p => add({ x: resolve(p[1]), y: resolve(p[2]), title: p[3] }));
  return out;
}
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function metricOptions(sel, scope) {
  const k = K();
  let h = scope === 'color' ? '<option value="team">Team</option><option value="pos">' + (S0.kind === 'pitcher' ? 'Role' : S0.kind === 'team' ? 'League' : 'Position') + '</option><option value="">One colour</option>' : '';
  h += BP.ui.metricOpts(G().metrics, sel, S0.kind, { set: grp()[1] });
  if (!scope) h += '<optgroup label="Sample"><option value="n"' + (sel === 'n' ? ' selected' : '') + '>' + nLong() + '</option></optgroup>';
  return h;
}
function sync() {
  const k = K(), $ = id => document.getElementById(id), g = G(), P = presetList();
  $('lab-win').innerHTML = g.wins.map(w => '<option value="' + k.esc(w) + '"' + (w === S0.win ? ' selected' : '') + '>' + k.esc(w === 'season' ? 'This season' : w) + '</option>').join('');
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S0.preset ? ' selected' : '') + '>' + k.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S0.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S0.x); $('lab-y').innerHTML = metricOptions(S0.y);
  $('lab-x').value = S0.x; $('lab-y').value = S0.y;
  $('lab-color').innerHTML = metricOptions(S0.color, 'color'); $('lab-color').value = S0.color;
  $('lab-min').value = S0.min; $('lab-min-v').textContent = S0.min; $('lab-min-u').textContent = nU();
  $('lab-shrink').checked = S0.shrink; $('lab-q').value = S0.q;
}
function applyPreset() { const P = presetList(); if (S0.preset < 0 || !P.length) return; const p = P[S0.preset] || P[0]; S0.x = p.x; S0.y = p.y; }
function rowsNow() { const g = G(); return g.rows.filter(r => (g.idx.win === undefined || String(raw(r, 'win')) === String(S0.win)) && inGroup(r)); }
/* "Most like": the five nearest the highlighted player within the group on screen, on the group's spec headline metrics */
function simStrip(L, rows, hits, nm) {
  const k = K();
  if (S0.kind === 'team') return '';
  if (!hits.length) return '<p class="bp-note bp-lab-simhint">Highlight a player to list the five most like them among the ' + k.esc(kindNoun()) + ' on this chart.</p>';
  const t = hits[0];
  const keys = BP.ui.flat(grp()[1], 'head').map(x => x[0]).filter(key => G().idx[key] !== undefined);
  const near = QK.within.similar(rows, t, keys, (r, key) => raw(r, key), 5);
  const tid = String(raw(t, 'id'));
  return QK.within.simHtml('Most like ' + nm(t) + ' · ' + kindNoun(), near.map(o => ({ name: nm(o.row), href: BP.compareHref(tid, String(raw(o.row, 'id'))) + (S0.kind === 'pitcher' ? '?kind=pitcher' : ''),
    sub: [POSU(raw(o.row, 'pos')), k.teamAbbr(raw(o.row, 'team')), k.int(raw(o.row, 'n')) + ' ' + nU()].filter(Boolean).join(' · ') + ' · compare' })));
}

function draw(L, S) {
  const k = K();
  const U = BP.ui;
  writeHash();
  const base0 = rowsNow().filter(r => (raw(r, 'n') || 0) >= S0.min);
  Object.keys(MU).forEach(key => delete MU[key]);
  [S0.x, S0.y, S0.color].forEach(key => { if (key && G().idx[key] !== undefined && shrinkable(key)) MU[key] = k.median(base0.map(r => raw(r, key))); });
  const rows = base0.filter(r => val(r, S0.x) !== null && val(r, S0.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  set('lab-sub', rows.length + ' ' + kindNoun() + ' · ' + k.esc(S0.win === 'season' ? S : S0.win) + ' · ' + S0.min + '+ ' + nU());
  set('lab-ours', (BP.ui.ours(S0.x) || BP.ui.ours(S0.y) ? '<p class="bp-lab-axes">' + [['X', S0.x], ['Y', S0.y]].map(a => a[0] + ': <b>' + k.esc(BP.ui.label(S0.kind, a[1], meta(a[1]).label || a[1])) + '</b>' + BP.ui.oursTag(a[1])).join(' &nbsp;·&nbsp; ') + '</p>' : '') + BP.ui.oursNote(S0.kind, [S0.x, S0.y]));
  if (rows.length < 3) { set('lab-ours', ''); set('lab-sim', ''); set('lab-chart', QK.empty('Too few for this view', L === 'npb' ? 'Lower the floor, or pick metrics this season has (the play-by-play metrics start in 2016).' : 'Lower the floor, widen the window, or pick metrics these players have (bat tracking starts in 2023; framing is for catchers).')); set('lab-table', ''); set('lab-note', ''); return; }
  const xs = rows.map(r => val(r, S0.x)), ys = rows.map(r => val(r, S0.y));
  const mx = k.median(xs), my = k.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S0.x) ? -1 : 1, diry = lower(S0.y) ? -1 : 1;
  const score = r => dirx * (val(r, S0.x) - sx.m) / sx.s + diry * (val(r, S0.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const nm = r => raw(r, 'name') || (S0.kind === 'team' ? k.teamName(String(raw(r, 'id'))) : k.name(String(raw(r, 'id'))));
  const tm = r => raw(r, 'team');
  const q = k.fold(S0.q.trim());
  const hits = q ? rows.filter(r => k.fold(nm(r) + ' ' + k.teamAbbr(tm(r))).indexOf(q) >= 0) : [];
  set('lab-sim', simStrip(L, base0, hits, nm));
  const labelled = new Set(ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(r => raw(r, 'n') || 0), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => 6 + 11 * (hi > lo ? Math.sqrt(((raw(r, 'n') || 0) - lo) / (hi - lo)) : 0.5);
  const href = r => (S0.kind === 'team' ? k.teamHref(L, String(raw(r, 'id')), S) : S0.kind === 'pitcher' ? k.pitcherHref(L, String(raw(r, 'id')), S) : k.hitterHref(L, String(raw(r, 'id')), S));
  /* colour: club colour, position (categorical slots), or a metric on the percentile scale (cold -> hot) */
  const T = QKC.tokens();
  let colorOf = () => T.model, legend = [];
  if (S0.color === 'team') colorOf = r => (BP.teamInfo(tm(r)) || {}).colour || T.ink3;
  else if (S0.color === 'pos') {
    const cnt = {};
    rows.forEach(r => { const p = String(raw(r, 'pos') || '—'); cnt[p] = (cnt[p] || 0) + 1; });
    const top = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 8);
    colorOf = r => { const i = top.indexOf(String(raw(r, 'pos') || '—')); return i >= 0 ? T.cat[i] : T.ink3; };
    legend = top.map((p, i) => ({ name: p + ' (' + cnt[p] + ')', color: T.cat[i] }));
  } else if (S0.color) {
    const cv = rows.map(r => val(r, S0.color)).filter(k.isNum).sort((a, b) => a - b);
    const dc = lower(S0.color) ? -1 : 1;
    colorOf = r => { const v = val(r, S0.color); return k.isNum(v) ? QK.pctHex(pOf(cv, v, dc)) : T.ink3; };
  }
  const diag = (/xwoba/.test(S0.x) && /xwoba|^woba$/.test(S0.y)) || (/^woba$/.test(S0.x) && /xwoba/.test(S0.y));
  const fx = meta(S0.x).fmt === 'pct' ? (v => Math.round(v * 100) + '%') : (v => fmt(S0.x, v));
  const fy = meta(S0.y).fmt === 'pct' ? (v => Math.round(v * 100) + '%') : (v => fmt(S0.y, v));
  QKC.scatter('#lab-chart', { points: rows.map(r => ({ x: val(r, S0.x), y: val(r, S0.y), name: nm(r) + ' · ' + k.teamAbbr(tm(r)) + ' · ' + k.int(raw(r, 'n')) + ' ' + nU(),
    label: labelled.has(r) ? k.surname(nm(r)) : ' ', color: hits.indexOf(r) >= 0 ? T.ink1 : colorOf(r), size: hits.indexOf(r) >= 0 ? 14 : size(r), href: href(r) })),
    xName: label(S0.x) + (lower(S0.x) ? ' (better to the right)' : ''), yName: label(S0.y) + (lower(S0.y) ? ' (better up)' : ''), xFmt: fx, yFmt: fy, refX: mx, refY: my, labelAll: true,
    xInverse: lower(S0.x), yInverse: lower(S0.y), diagonal: diag ? { label: 'equal' } : undefined, legendItems: legend, label: label(S0.y) + ' against ' + label(S0.x) });
  const r = k.corr(xs, ys);
  const mX = meta(S0.x), mY = meta(S0.y);
  set('lab-note', 'Correlation on screen r = ' + k.num(r, 2) + ' (' + rows.length + ' ' + kindNoun() + '). The reference lines are the medians of this group' + (S0.kind === 'pitcher' ? ' (starters and relievers are never pooled)' : '') + '. ' + (lower(S0.x) || lower(S0.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    (diag ? 'The dashed diagonal is equality. ' : '') + (S0.color && S0.color !== 'team' && S0.color !== 'pos' ? 'Colour: ' + k.esc(label(S0.color)) + ' on the percentile scale (blue worst, red best). ' : '') +
    'Labelled: the eight furthest into the good corner, the four furthest from it' + (hits.length ? ', and your search (white)' : '') + '. Marker size is the sample.' +
    (S0.shrink ? ' Rates marked "shrunk" are pulled to the median of the players on screen by their own stabilisation point: (n·x + k·median)/(n + k) with k = 3/7 of the sample at which the metric reaches 0.7 split-half reliability (' + (shrinkable(S0.x) ? k.esc(mX.label || S0.x) + ' k = ' + k.int(kOf(S0.x)) : '') + (shrinkable(S0.x) && shrinkable(S0.y) ? ', ' : '') + (shrinkable(S0.y) ? k.esc(mY.label || S0.y) + ' k = ' + k.int(kOf(S0.y)) : '') + '). Model scores (the "+" scores), WAR and run totals are never shrunk here: the models regularise them already.' : '') +
    (mX.desc ? '<br><strong>' + k.esc(BP.ui.label(S0.kind, S0.x, mX.label)) + '</strong>: ' + k.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + k.esc(BP.ui.label(S0.kind, S0.y, mY.label)) + '</strong>: ' + k.esc(mY.desc) : '') + npbNote([S0.x, S0.y]));
  QK.leaderboard(document.getElementById('lab-table'), { dense: true, rank: true, maxHeight: 620, rowClass: o => (hits.indexOf(o._r) >= 0 ? 'is-me' : ''), rowHref: o => o.href, columns: [
    { key: 'name', label: S0.kind === 'pitcher' ? 'Pitcher' : S0.kind === 'team' ? 'Club' : 'Hitter', type: 'entity', sub: 'sub', mark: o => (S0.kind === 'team' ? U.team(o.id, L, S) : (o.team ? U.team(o.team, L, S) : null)), href: o => o.href },
    { key: 'n', label: nU(), num: true, fmt: v => k.int(v) },
    { key: 'vx', label: label(S0.x), type: 'pctl', pctl: 'px', fmt: v => fmt(S0.x, v) },
    { key: 'vy', label: label(S0.y), type: 'pctl', pctl: 'py', fmt: v => fmt(S0.y, v) },
    { key: 'z', label: 'Combined', type: 'bar', fmt: v => k.num(v, 2), tip: 'Sum of standard scores in the better direction' }],
    rows: ranked.slice(0, 300).map(o => { const rr = o.r, vx = val(rr, S0.x), vy = val(rr, S0.y);
      return { _r: rr, id: String(raw(rr, 'id')), name: nm(rr), team: tm(rr), sub: S0.kind === 'team' ? String(raw(rr, 'pos') || '') : [POSU(raw(rr, 'pos')), k.teamAbbr(tm(rr))].filter(Boolean).join(' · '), n: raw(rr, 'n'), vx: vx, px: pOf(sortedX, vx, dirx), vy: vy, py: pOf(sortedY, vy, diry), z: o.z, href: href(rr) }; }) });
  BP.ui.tagHeads(document.getElementById('lab-table'), { vx: S0.x, vy: S0.y });
}

function render(el, params, state) {
  const k = K();
  const U = BP.ui;
  const L = k.L(params, state);
  el.innerHTML = QK.sectionHead({ kicker: 'Lab · ' + k.LN(L), title: 'Any two metrics', sub: 'Plot one metric against another for a season or a window, colour by club, position or a third metric, and rank everyone on both, within a broad group (hitters, starters, relievers) or one position. Presets ask the questions our models were built to answer.' }) +
    '<section class="qk-card"><div class="qk-card-body"><div id="lab-wn-host" class="bp-lab-within"></div><div class="bp-ctl">' +
    '<label>Window<select id="lab-win"></select></label><label>Preset<select id="lab-preset" class="gq-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label><label>Y axis<select id="lab-y"></select></label><button type="button" id="lab-swap" class="qk-btn" title="Swap the axes">⇄ Swap</button>' +
    '<label>Colour<select id="lab-color"></select></label><label>Min <span id="lab-min-u"></span> <b id="lab-min-v"></b><input id="lab-min" type="range" min="0" max="700" step="5"></label>' +
    '<label class="bp-check"><input id="lab-shrink" type="checkbox"> shrink by stabilisation</label><label>Highlight<input id="lab-q" class="gq-search" type="search" placeholder="player or team…"></label>' +
    '</div></div></section>' +
    '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-12">' + U.card2('The chart', '<span id="lab-sub">Loading…</span>', '<div id="lab-ours"></div>' + U.chart('lab-chart', 560, 'Lab scatter') + '<div id="lab-sim" class="bp-lab-sim"></div><p class="bp-note" id="lab-note"></p>') + '</div>' +
    '<div class="qk-span-12">' + U.card2('Ranked', 'By the combined standard score on both axes (top 300); the cells are percentiles within the group on screen', '<div id="lab-table"></div>', { flush: true }) + '</div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    // NPB: one file (npb/<S>/lab.json: hitters, pitchers and clubs); MLB and Triple-A fall back to the catalogues
    const more = L === 'npb' ? [Promise.resolve(null), Promise.resolve(null), Promise.resolve(null)] : [k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json'), k.loadNames()];
    return Promise.all([k.loadY(L, S, 'lab.json')].concat(more).concat([U.specReady()])).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, $ = id => document.getElementById(id);
    const hc = k.catOf(res[1], 'hitters'), pc = k.catOf(res[2], 'pitchers');
    if (hc) k.learnCat(hc);
    if (pc) k.learnCat(pc);
    const key = L + '/' + S;
    if (LABK !== key) { LAB = prep(res[0], hc, pc); LABK = key; S0.win = null; S0.min = null; S0.x = ''; S0.y = ''; S0.preset = 0; }
    if (!Object.keys(LAB).length) { $('lab-chart').innerHTML = QK.empty('Not built yet', 'The ' + k.LN(L) + ' ' + S + ' lab file is not available.'); $('lab-sub').textContent = ''; return; }
    const qy = params.query || {};
    TG = (pc && pc.team_games) || (hc && hc.team_games) || null;
    if (!TG && LAB.team) TG = Math.max.apply(null, LAB.team.rows.map(r => Number(r[LAB.team.idx.n]) || 0).concat([0])) || null;
    const KQ = { hitter: 'H', pitcher: 'SP', sp: 'SP', rp: 'RP', team: 'T', clubs: 'T' };
    if (qy.kind && KQ[qy.kind]) { S0.bg = KQ[qy.kind]; S0.within = 'broad'; }
    const wq = QK.within.read(qy, POSN);
    if (qy.within) { S0.within = wq.within; if (wq.within === 'pos') S0.pg = wq.pos; }
    if (typeof qy.q === 'string') S0.q = qy.q;
    const avail = c => !!LAB[GROUPS[c][0]];
    if (!avail(code())) { S0.within = 'broad'; S0.bg = BROAD.filter(avail)[0] || 'H'; }
    S0.kind = grp()[0];
    const reset = () => {
      const g = G();
      if (S0.win === null || g.wins.indexOf(S0.win) < 0) S0.win = g.wins.indexOf(String(S)) >= 0 ? String(S) : g.wins[0];
      const maxN = Math.max.apply(null, rowsNow().map(r => raw(r, 'n') || 0).concat([50]));
      $('lab-min').max = String(Math.ceil(maxN / 10) * 10);
      if (S0.minFor !== code() + '|' + S0.win) S0.min = null;      // a new group or window: back to its floor
      if (S0.min === null || S0.min > maxN) S0.min = Math.min(Math.round(specFloor() / 5) * 5, Math.floor(maxN / 5) * 5);
      S0.minFor = code() + '|' + S0.win;
      if (!S0.x || g.idx[S0.x] === undefined || !S0.y || g.idx[S0.y] === undefined) { if (S0.preset < 0) S0.preset = 0; applyPreset(); }
      if (!S0.x || !S0.y) { const ms = g.metrics; S0.x = (ms[0] || {}).key || 'n'; S0.y = (ms[1] || {}).key || 'n'; S0.preset = -1; }
    };
    if (qy.x && G().idx[qy.x] !== undefined) { S0.x = qy.x; S0.preset = -1; }
    if (qy.y && G().idx[qy.y] !== undefined) { S0.y = qy.y; S0.preset = -1; }
    reset();
    sync();
    const redraw = () => draw(L, S);
    /* a new group: the axes stay when the kind does (starters to relievers), the minimum goes back to the group's floor */
    const regroup = () => {
      const kind = grp()[0];
      if (kind !== S0.kind) { S0.kind = kind; S0.x = ''; S0.y = ''; S0.preset = 0; if (S0.color !== 'team' && S0.color !== 'pos' && S0.color) S0.color = 'team'; }
      S0.min = null; reset(); sync(); within(); redraw();
    };
    const within = () => {
      const host = $('lab-wn-host');
      if (!host) return;
      const fl = specFloor();
      const broadSeg = U.seg('lab-kind', 'Group', BROAD.filter(avail).map(c => [c, c === 'H' ? 'Hitters' : c === 'SP' ? 'Starters' : c === 'RP' ? 'Relievers' : 'Clubs']), S0.bg);
      host.innerHTML = QK.within.html({ within: S0.within, pos: S0.pg }, { id: 'lab-wn', groups: POSN.filter(avail).map(c => [c, GROUPS[c][2]]),
        note: S0.within === 'pos' ? (fl ? 'minimum ' + k.int(fl) + ' ' + nU() + ' (the metrics spec, prorated to ' + (TG ? k.int(TG) + ' team games' : 'the season') + ')' : '') : broadSeg });
      QK.within.wire(host, { within: S0.within, pos: S0.pg }, w => {
        if (w.within === 'pos' && S0.within !== 'pos') { if (S0.bg === 'SP' || S0.bg === 'RP') w.pos = S0.bg; }
        if (w.within !== 'pos' && S0.within === 'pos') S0.bg = (S0.pg === 'SP' || S0.pg === 'RP') ? S0.pg : 'H';
        S0.within = w.within; if (w.within === 'pos') S0.pg = w.pos;
        regroup();
      }, { id: 'lab-wn' });
      const seg = $('lab-kind');
      if (seg) QK.seg(seg, v => { if (!GROUPS[v] || !avail(v)) return; S0.bg = v; regroup(); });
    };
    within();
    $('lab-win').onchange = e => { S0.win = e.target.value; S0.min = null; reset(); sync(); redraw(); };
    $('lab-preset').onchange = e => { S0.preset = parseInt(e.target.value, 10); applyPreset(); sync(); redraw(); };
    $('lab-x').onchange = e => { S0.x = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-y').onchange = e => { S0.y = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-swap').onclick = () => { const t = S0.x; S0.x = S0.y; S0.y = t; S0.preset = -1; sync(); redraw(); };
    $('lab-color').onchange = e => { S0.color = e.target.value; redraw(); };
    $('lab-min').oninput = e => { S0.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S0.min; };
    $('lab-min').onchange = redraw;
    $('lab-shrink').onchange = e => { S0.shrink = e.target.checked; redraw(); };
    let timer = null;
    $('lab-q').oninput = e => { S0.q = e.target.value; clearTimeout(timer); timer = setTimeout(redraw, 250); };
    redraw();
  });
}

if (typeof BP.route === 'function') { BP.route('lab', render); try { BP.route('#/<L>/lab', render); } catch (e) { /* bound */ } }
if (typeof BP.routeNpb === 'function') BP.routeNpb('lab', render);
})(window.BP || (window.BP = {}));
