/* The Quant Bullpen — builder G's shared kit (BP.gk) and the hitters catalogue (#/<L>/hitters).
 *
 * BP.gk is defined here and read lazily at render time by every other page of builder G
 * (pitchers, player, teams, leaders, umpires, parks, prospects, history, awards, lab, compare,
 * calibration, docs: const K = () => BP.gk), so script order does not matter as long as this
 * file is loaded. It leans on the shell (core.js: BP.load, BP.tableHTML, BP.sortable, BP.plot,
 * BP.layout, BP.pctColor, BP.statTile ...) where those exist and falls back to local copies.
 *
 * Data (oddsmarkets/baseball/PAYLOADS.md): data/<L>/<S>/hitters.json and pitchers.json
 * (catalogues: {"metrics": [METRIC], "players": {pid: {"name","team","pos","age","pa"|"bf",
 * "qualified","values","pct","pct_role"}}}), data/players_index.json (names), data/index.json
 * (teams, levels, season). */
(function (BP) {
'use strict';

// ════════════════════════════════════════════════════════════════════════════
// The kit: BP.gk
// ════════════════════════════════════════════════════════════════════════════

const K = BP.gk = BP.gk || {};

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const escL = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const has = f => typeof BP[f] === 'function';
K.isNum = isNum;
K.esc = s => (has('esc') ? BP.esc(s) : escL(s));
K.alive = el => !!el && el.isConnected;
K.ok = d => !!d && d.ok !== false;
K.muted = t => '<div class="muted">' + t + '</div>';
K.notBuilt = (what, d) => K.muted(K.esc(what) + ' is not available yet' + (d && d.reason ? ' (' + K.esc(d.reason) + ')' : '') + '. The payloads are rebuilt every run.');
K.num = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
K.int = v => (isNum(v) ? Math.round(Number(v)).toLocaleString('en-GB') : '—');
K.signed = (v, d) => {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
};
K.pct = (p, d) => {
  if (!isNum(p)) return '—';
  const dd = d === undefined ? 1 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd)) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd)) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
};
K.ordinal = n => {
  if (!isNum(n)) return '—';
  const v = Math.round(n), t = v % 100;
  return v + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][v % 10] || 'th');
};
/* A baseball rate: .345 (no leading zero), as wOBA and batting average are written. */
K.rate3 = v => (isNum(v) ? Number(v).toFixed(3).replace(/^(-?)0\./, '$1.') : '—');
/* Catalogue values by METRIC fmt. PAYLOADS: probabilities 4 dp, rates 3 dp, "plus" scores integers (100 = average),
 * fractions (pct/prob) 0–1. Unknown formats fall back to sensible decimals. */
K.fmtV = (v, fmt) => {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt || '')) {
    case 'int': case 'count': return Math.round(x).toLocaleString('en-GB');
    case 'plus': return Math.round(x).toString();
    case '0': return x.toFixed(0);
    case '1': case 'mph': case 'in': case 'deg': case 'ft': return x.toFixed(1);
    case '2': return x.toFixed(2);
    case '3': case 'rate': case 'rate3': case 'avg': return K.rate3(x);
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'prob': return K.pct(x);
    case 'signed': case 'runs': case 'pm': case 'rv': return K.signed(x, 1);
    case 'signed2': return K.signed(x, 2);
    case 'war': return K.signed(x, 1);
    case 'rpm': return Math.round(x).toLocaleString('en-GB');
    case 'ip': { const w = Math.floor(x + 1e-9), f = Math.round((x - w) * 3); return w + '.' + Math.min(2, f); }
    default: return Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) < 1 && x !== 0 ? x.toFixed(3) : x.toFixed(2);
  }
};
K.fmt = (m, v) => K.fmtV(v, (m || {}).fmt);
K.median = a => { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
K.mean = a => { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; };
K.sd = a => { const s = a.filter(isNum).map(Number); if (s.length < 2) return null; const m = K.mean(s); return Math.sqrt(s.reduce((x, y) => x + (y - m) * (y - m), 0) / (s.length - 1)); };
K.corr = (xs, ys) => {
  const pairs = xs.map((x, i) => [x, ys[i]]).filter(p => isNum(p[0]) && isNum(p[1]));
  if (pairs.length < 3) return null;
  const mx = K.mean(pairs.map(p => p[0])), my = K.mean(pairs.map(p => p[1]));
  let a = 0, b = 0, c = 0;
  pairs.forEach(p => { a += (p[0] - mx) * (p[1] - my); b += (p[0] - mx) * (p[0] - mx); c += (p[1] - my) * (p[1] - my); });
  return b && c ? a / Math.sqrt(b * c) : null;
};
K.alpha = (hex, a) => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return BP.alpha ? BP.alpha(hex || 'var(--c-1)', a) : 'rgba(88,166,255,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};
K.C = Object.assign({ bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d', text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316', purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8' }, BP.C || {});
K.PALETTE = BP.PALETTE || ['#58a6ff', '#f97316', '#3fb950', '#bc8cff', '#f85149', '#d29922', '#39d0d8', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
K.CA = 'var(--c-1)'; K.CB = 'var(--c-2)';   // compare: side A chart slot 1, side B slot 2 (the kit's pair)
K.fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
K.titleCase = s => String(s || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

// ── pitch types (Statcast codes) ───────────────────────────────────────────

K.PITCH = {
  FF: ['4-Seam Fastball', '#d22d49'], SI: ['Sinker', '#fe9d00'], FC: ['Cutter', '#933f2c'], FA: ['Fastball', '#d22d49'],
  SL: ['Slider', '#eee716'], ST: ['Sweeper', '#ddb33a'], SV: ['Slurve', '#93afd4'], CU: ['Curveball', '#00d1ed'], KC: ['Knuckle Curve', '#6236cd'],
  CS: ['Slow Curve', '#0068ff'], CH: ['Changeup', '#1dbe3a'], FS: ['Splitter', '#3bacac'], FO: ['Forkball', '#55ccab'], SC: ['Screwball', '#60db33'],
  KN: ['Knuckleball', '#3c44cd'], EP: ['Eephus', '#888888'], PO: ['Pitchout', '#aaaaaa'], all: ['All pitches', '#e6edf3'], ALL: ['All pitches', '#e6edf3']
};
K.pitchName = t => (K.PITCH[t] ? K.PITCH[t][0] : has('pitchName') ? BP.pitchName(t) : (t ? String(t) : '—'));
K.pitchColour = t => (has('pitchColour') && t && !/^all$/i.test(t) ? BP.pitchColour(t) : K.PITCH[t] ? K.PITCH[t][1] : '#8b949e');
K.pitchChip = t => '<span class="gq-pt" style="--pt:' + K.pitchColour(t) + '" title="' + K.esc(K.pitchName(t)) + '">' + K.esc(t) + '</span>';
K.FAMILY = { FF: 'fastball', SI: 'fastball', FC: 'fastball', FA: 'fastball', SL: 'breaking', ST: 'breaking', SV: 'breaking', CU: 'breaking', KC: 'breaking', CS: 'breaking', CH: 'offspeed', FS: 'offspeed', FO: 'offspeed', SC: 'offspeed', KN: 'other', EP: 'other' };

// ── level, season, index ───────────────────────────────────────────────────

K.LEVELS = ['mlb', 'aaa', 'npb'];
K.LN = L => (L === 'aaa' ? 'Triple-A' : L === 'npb' ? 'NPB' : 'MLB');
/* The level: 'mlb', 'aaa' or 'npb' (the npb level reaches this kit only through the pages that support it: the lab and
 * compare, which read npb/<S>/lab.json). */
K.L = (params, state) => {
  const st = state || BP.state || {};
  const t = String((params && (params.level || params.L || params.league)) || st.level || st.league || 'mlb').toLowerCase();
  return t === 'aaa' ? 'aaa' : t === 'npb' ? 'npb' : 'mlb';
};
K.ready = () => (K.INDEX ? Promise.resolve(K.INDEX) : BP.load('index.json').then(d => { K.INDEX = d || {}; K.learnIndex(K.INDEX); return K.INDEX; }));
K.curSeason = L => {
  if (has('currentSeason')) { try { const c = BP.currentSeason(L || 'mlb'); if (isNum(c)) return Number(c); } catch (e) { /* local */ } }
  const x = K.INDEX || {};
  const lv = ((x.levels || {})[L || 'mlb']) || {};
  if (isNum(lv.season)) return Number(lv.season);
  if (isNum(x.season)) return Number(x.season);
  return new Date().getFullYear();
};
K.S = (params, state) => {
  const q = (params && params.query) || {};
  const raw = params && (params.season || q.s || q.season || q.y);
  if (isNum(raw)) return Number(raw);
  const st = state || BP.state || {};
  if (isNum(st.season)) return Number(st.season);
  return K.curSeason(K.L(params, state));
};
K.seasons = L => {
  const lv = (((K.INDEX || {}).levels || {})[L || 'mlb']) || {};
  const list = (lv.seasons || []).filter(isNum).map(Number);
  const cur = K.curSeason(L);
  if (list.indexOf(cur) < 0) list.push(cur);
  return list.sort((a, b) => b - a);
};
K.ypath = (L, S, file) => L + '/' + S + '/' + file;
K.loadY = (L, S, file) => BP.load(K.ypath(L, S, file));

// ── names, teams, links ────────────────────────────────────────────────────

K.NAMES = BP.NAMES || K.NAMES || {};   // pid -> {name, team, pos, bats, throws, levels}; shared with the shell
K.TEAMS = BP.TEAMS || K.TEAMS || {};   // tid -> {name, abbr, short, colour, league, division, venue}; shared with the shell
K.learn = (pid, info) => { if (!pid || !info) return; K.NAMES[pid] = Object.assign({}, K.NAMES[pid] || {}, info); };
K.learnTeam = (tid, info) => {
  if (!tid || !info || typeof info !== 'object') return;
  const clean = {};
  ['name', 'abbr', 'short', 'colour', 'color', 'league', 'division', 'venue', 'parent', 'city', 'level'].forEach(k => { if (info[k] !== undefined && info[k] !== null) clean[k] = info[k]; });
  if (clean.color && !clean.colour) clean.colour = clean.color;
  K.TEAMS[String(tid)] = Object.assign({}, K.TEAMS[String(tid)] || {}, clean);
};
K.learnIndex = d => {
  if (!d || typeof d !== 'object') return;
  const T = d.teams || {};
  Object.keys(T).forEach(t => K.learnTeam(t, T[t]));
  Object.keys(d.levels || {}).forEach(L => { const x = (d.levels[L] || {}).teams || {}; Object.keys(x).forEach(t => K.learnTeam(t, Object.assign({ level: L }, x[t]))); });
};
K.loadNames = () => BP.load('players_index.json').then(d => {
  const m = d && typeof d === 'object' && d.ok !== false ? (d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : d) : null;
  if (m) Object.keys(m).forEach(pid => {
    const r = m[pid];
    if (Array.isArray(r)) K.learn(pid, { name: r[0], team: r[1], pos: r[2], bats: r[3], throws: r[4], levels: r[5] });
    else if (r && typeof r === 'object' && r.name) K.learn(pid, r);
  });
  return d;
});
K.learnCat = cat => {
  const P = ((cat || {}).players) || {};
  Object.keys(P).forEach(id => { const p = P[id] || {}; if (p.name && !(K.NAMES[id] || {}).name) K.learn(id, { name: p.name, team: p.team, pos: p.pos }); });
  const T = (cat || {}).teams;
  if (T && !Array.isArray(T)) Object.keys(T).forEach(t => { if (T[t] && typeof T[t] === 'object') K.learnTeam(t, T[t]); });
};
K.name = pid => {
  const x = K.NAMES[pid];
  if (x && x.name) return x.name;
  if (has('playerName')) { try { const n = BP.playerName(pid); if (n && !/^(Player |#)/.test(n) && n !== '—') return n; } catch (e) { /* local */ } }
  return pid ? '#' + pid : '—';
};
K.surname = n => { const p = String(n || '').split(' '); return p.length > 1 ? p.slice(1).join(' ') : p[0]; };
K.team = tid => {
  const t = K.TEAMS[String(tid)];
  if (t) return t;
  if (has('teamInfo')) { try { const x = BP.teamInfo(tid); if (x && typeof x === 'object') return x; } catch (e) { /* local */ } }
  return {};
};
K.teamAbbr = tid => (has('teamAbbr') ? BP.teamAbbr(tid) : (K.team(tid).abbr || (tid ? String(tid) : '—')));
K.teamName = tid => (K.team(tid).name || K.teamAbbr(tid));
K.teamColour = tid => (has('teamColour') ? BP.teamColour(tid) : (K.team(tid).colour || K.team(tid).color || '#6e7681'));
K.umpName = id => (has('umpireName') ? BP.umpireName(id) : (id ? 'Umpire ' + id : '—'));
K.parkName = vid => (has('parkName') ? BP.parkName(vid) : (vid ? 'Venue ' + vid : '—'));
K.park = vid => (has('parkInfo') ? BP.parkInfo(vid) : {});
const enc = encodeURIComponent;
/* "?s=<S>" when S is not the level's current season (the shell's convention: ?s=). */
K.sq = (L, S) => (isNum(S) && Number(S) !== K.curSeason(L) ? '?s=' + S : '');
K.href = (L, sub, S) => '#/' + (L || 'mlb') + (sub ? '/' + String(sub).replace(/^\/+/, '') : '') + K.sq(L, S);
K.isPitcherPos = pos => /^(P|SP|RP|CL|LHP|RHP)$/i.test(String(pos || ''));
K.isTwoWay = pos => /^(TWP|Two-Way|TW|Y)$/i.test(String(pos || ''));
K.hitterHref = (L, pid, S) => K.href(L, 'hitter/' + enc(pid), S);
K.pitcherHref = (L, pid, S) => K.href(L, 'pitcher/' + enc(pid), S);
K.playerHref = (L, pid, S, role) => {
  const pos = role || ((K.NAMES[pid] || {}).pos);
  if (K.isTwoWay(pos)) return '#/player/' + enc(pid) + K.sq(L, S);
  return K.isPitcherPos(pos) || role === 'pitcher' ? K.pitcherHref(L, pid, S) : K.hitterHref(L, pid, S);
};
K.teamHref = (L, tid, S) => K.href(L, 'team/' + enc(tid), S);
K.umpHref = id => '#/umpire/' + enc(id);
K.parkHref = vid => '#/park/' + enc(vid);
K.compareHref = (a, b) => '#/compare' + (a ? '/' + enc(a) : '') + (b ? '/' + enc(b) : '');
K.playerLink = (L, pid, label, S, role) => (pid ? '<a class="ply-link" href="' + K.playerHref(L, pid, S, role) + '">' + K.esc(label || K.name(pid)) + '</a>' : '<span class="muted-inline">—</span>');
K.teamChip = (L, tid, S) => (tid ? '<a class="gq-team" href="' + K.teamHref(L, tid, S) + '" style="--tc:' + K.teamColour(tid) + '" title="' + K.esc(K.teamName(tid)) + '">' + K.esc(K.teamAbbr(tid)) + '</a>' : '<span class="muted-inline">—</span>');
K.teamLink = (L, tid, S) => (tid ? '<a href="' + K.teamHref(L, tid, S) + '">' + K.esc(K.teamName(tid)) + '</a>' : '—');
K.ageOf = dob => {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
K.fmtDate = (s, o) => {
  if (has('fmtDate')) { try { const r = BP.fmtDate(s, o); if (r && r !== '—') return r; } catch (e) { /* local */ } }
  if (!s) return '—';
  const d = new Date(String(s).length === 10 ? s + 'T12:00:00Z' : s);
  if (isNaN(d.getTime())) return String(s);
  const opt = o || {};
  return d.getDate() + ' ' + MONTHS[d.getMonth()] + (opt.year === false ? '' : ' ' + d.getFullYear());
};
K.short = s => K.fmtDate(s, { year: false, weekday: false });

// ── HTML furniture ─────────────────────────────────────────────────────────

K.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + K.esc(id) + '"' : '') + '>' +
  (title ? '<div class="card-header">' + K.esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl ? '<span class="gq-ctl">' + ctl + '</span>' : '') + '</div>' : '') + (body || '') + '</div>';
K.tile = (label, value, sub, cls) => '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + K.esc(label) + '</div><div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>';
K.tiles = list => '<div class="kpi-grid gq-tiles">' + list.join('') + '</div>';
K.toggle = (id, opts, cur) => '<span class="gq-toggle" id="' + K.esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + K.esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' class="on"' : '') + '>' + K.esc(o[1]) + '</button>').join('') + '</span>';
K.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fn(b.dataset.v);
  }));
};
K.select = (id, opts, cur, cls) => '<select id="' + K.esc(id) + '"' + (cls ? ' class="' + cls + '"' : '') + '>' + opts.map(o => '<option value="' + K.esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' selected' : '') + '>' + K.esc(o[1]) + '</option>').join('') + '</select>';
K.pctColor = p => {
  if (has('pctColor')) return BP.pctColor(p);
  if (!isNum(p)) return '#30363d';
  const t = Math.max(0, Math.min(100, p)) / 100, lo = [59, 130, 246], mid = [107, 114, 128], hi = [239, 68, 68];
  const a = t < 0.5 ? lo : mid, b = t < 0.5 ? mid : hi, u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return 'rgb(' + [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * u)).join(',') + ')';
};
K.ink = p => (has('pctInk') ? BP.pctInk(p) : '#fff');
K.pill = p => (isNum(p) ? '<span class="pct-pill" style="background:' + K.pctColor(p) + ';color:' + K.ink(p) + '">' + Math.round(p) + '</span>' : '<span class="pct-pill empty">—</span>');
/* Savant-style percentile slider: a track, a coloured disc carrying the percentile, the value on the right. */
K.slider = (label, p, valueText, title, href, none) => {
  const known = isNum(p), x = known ? Math.max(0, Math.min(100, p)) : 0;
  const lab = href ? '<a href="' + href + '" class="gq-sl-a">' + K.esc(label) + '</a>' : K.esc(label);
  return '<div class="gq-sl"' + (title ? ' title="' + K.esc(title) + '"' : '') + '><span class="gq-sl-label">' + lab + '</span><div class="gq-sl-track">' +
    (known ? '<div class="gq-sl-fill" style="width:' + x + '%;background:' + K.pctColor(p) + '"></div><span class="gq-sl-dot" style="left:' + x + '%;background:' + K.pctColor(p) + ';color:' + K.ink(p) + '">' + Math.round(p) + '</span>' : '<span class="gq-sl-none">' + K.esc(none || 'not enough data') + '</span>') +
    '</div><span class="gq-sl-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
};
/* Grouped sliders over a whole catalogue. opts {onlyKnown, note, cols, glossary: true}. */
K.sliders = (metrics, vals, pcts, opts) => {
  const o = opts || {};
  // The shell's Savant-style sliders keep one look across the site; this copy is the fallback.
  if (BP.charts && typeof BP.charts.percentileSliders === 'function') { try { return BP.charts.percentileSliders(metrics, vals, pcts, o); } catch (e) { console.warn('sliders', e); } }
  const groups = K.groups(metrics).map(g => ({ name: g.name, items: g.items.filter(m => !o.onlyKnown || isNum((vals || {})[m.key])) })).filter(g => g.items.length);
  if (!groups.length) return K.muted('No metrics in the catalogue yet.');
  return '<div class="gq-sl-cols">' + groups.map(g => '<div class="gq-sl-group"><div class="gq-sl-head">' + K.esc(g.name) + '</div>' +
    g.items.map(m => K.slider(m.label + (m.lower ? ' ↓' : ''), (pcts || {})[m.key], K.fmt(m, (vals || {})[m.key]),
      (m.desc || m.label) + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + K.int(m.stabilises_at) + ' ' + (m.unit || 'PA/BF') : '') + (m._pctNote ? ' · ' + m._pctNote : ''),
      o.glossary === false ? null : '#/glossary/' + enc(m.key), K.noPctText(m, (vals || {})[m.key]))).join('') + '</div>').join('') + '</div>' + (o.note ? '<div class="pg-note gq-note">' + o.note + '</div>' : '');
};

/* Tables: the shell's when present (same signature as Hardwood's HW.tableHTML), else this copy. */
K.table = (cols, rows, opts) => {
  if (has('tableHTML')) return BP.tableHTML(cols, rows, opts);
  const o = opts || {};
  let h = '<div class="table-wrap' + (o.compact ? ' compact' : '') + '"' + (o.id ? ' id="' + K.esc(o.id) + '"' : '') + '><table class="wc-table' + (o.sticky ? ' sticky-head' : '') + (o.cls ? ' ' + o.cls : '') + '"><thead><tr>';
  cols.forEach(c => {
    const cc = typeof c === 'string' ? { label: c } : c;
    h += '<th class="' + (cc.sortable === false ? '' : 'sortable-th') + (cc.cls ? ' ' + cc.cls : '') + '"' + (cc.align ? ' style="text-align:' + cc.align + '"' : '') + (cc.title ? ' title="' + K.esc(cc.title) + '"' : '') + '>' + K.esc(cc.label) + '</th>';
  });
  h += '</tr></thead><tbody>';
  (rows || []).forEach(r => {
    const row = Array.isArray(r) ? { cells: r } : r;
    h += '<tr' + (row._class ? ' class="' + row._class + '"' : '') + (row._href ? ' data-href="' + K.esc(row._href) + '"' : '') + '>';
    row.cells.forEach((c0, i) => {
      const c = (c0 !== null && typeof c0 === 'object') ? c0 : { v: c0 };
      const col = typeof cols[i] === 'object' ? cols[i] : {};
      const align = c.align || col.align;
      const sortV = c.v !== undefined && c.v !== null ? c.v : (c.html !== undefined ? String(c.html).replace(/<[^>]*>/g, '') : '');
      h += '<td data-v="' + K.esc(sortV) + '"' + (c.cls || col.cls ? ' class="' + [c.cls, col.cls].filter(Boolean).join(' ') + '"' : '') + (c.title ? ' title="' + K.esc(c.title) + '"' : '') +
        (align || c.style ? ' style="' + (align ? 'text-align:' + align + ';' : '') + (c.style || '') + '"' : '') + '>' + (c.html !== undefined ? c.html : K.esc(c.v === null || c.v === undefined ? '—' : c.v)) + '</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
};
K.sortable = el => {
  if (has('sortable')) return BP.sortable(el);
  const root = typeof el === 'string' ? document.getElementById(el) : el;
  if (!root) return;
  const tables = root.tagName === 'TABLE' ? [root] : Array.prototype.slice.call(root.querySelectorAll('table'));
  tables.forEach(table => {
    if (table.dataset.sortWired) return;
    table.dataset.sortWired = '1';
    const ths = Array.prototype.slice.call(table.querySelectorAll('thead th'));
    ths.forEach((th, idx) => {
      if (!th.classList.contains('sortable-th')) return;
      th.addEventListener('click', () => {
        const tbody = table.querySelector('tbody');
        const rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        const asc = th.dataset.sortDir !== 'asc';
        ths.forEach(x => { delete x.dataset.sortDir; });
        th.dataset.sortDir = asc ? 'asc' : 'desc';
        rows.sort((a, b) => {
          const av = a.children[idx] ? a.children[idx].dataset.v : '', bv = b.children[idx] ? b.children[idx].dataset.v : '';
          const an = parseFloat(av), bn = parseFloat(bv), aN = !isNaN(an) && isFinite(av), bN = !isNaN(bn) && isFinite(bv);
          const cmp = aN && bN ? an - bn : aN ? -1 : bN ? 1 : String(av).localeCompare(String(bv));
          return asc ? cmp : -cmp;
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
    table.querySelectorAll('tr[data-href]').forEach(tr => {
      tr.classList.add('row-link');
      tr.addEventListener('click', ev => { if (ev.target.closest('a')) return; location.hash = tr.dataset.href; });
    });
  });
};

// ── charts: Plotly through the shell ───────────────────────────────────────

const DARK = {
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: '#8b949e', family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', size: 11 },
  xaxis: { gridcolor: '#21262d', zerolinecolor: '#30363d', linecolor: '#30363d' },
  yaxis: { gridcolor: '#21262d', zerolinecolor: '#30363d', linecolor: '#30363d' },
  margin: { l: 60, r: 20, t: 30, b: 50 }, hovermode: 'closest',
  hoverlabel: { bgcolor: '#161b22', bordercolor: '#30363d', font: { color: '#e6edf3', size: 12 } }, showlegend: false
};
K.layout = extra => {
  if (has('layout')) return BP.layout(extra);
  const out = Object.assign(JSON.parse(JSON.stringify(DARK)), extra || {});
  Object.keys(extra || {}).forEach(k => { if (/^[xy]axis\d*$/.test(k) && extra[k] && typeof extra[k] === 'object') out[k] = Object.assign({}, DARK.xaxis, extra[k]); });
  if (extra && extra.font) out.font = Object.assign({}, DARK.font, extra.font);
  return out;
};
K.plot = (el, traces, lay, conf) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (has('plot')) return BP.plot(node, traces, lay, conf);
  if (typeof Plotly === 'undefined') { node.innerHTML = K.muted('The chart library did not load. The tables carry the same data.'); return null; }
  try {
    const p = Plotly.newPlot(node, traces, lay, Object.assign({ displayModeBar: false, responsive: true }, conf || {}));
    if (has('onLeave')) BP.onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    return p;
  } catch (err) { node.innerHTML = K.muted('The chart could not be drawn.'); return null; }
};
K.narrow = node => ((node && node.clientWidth) || window.innerWidth || 800) < 520;
K.legendTop = () => ({ showlegend: true, legend: { orientation: 'h', y: 1.12, x: 0, font: { color: K.C.text2, size: 10 } } });
/* Diverging colour scale for run values and xwOBA+: blue (pitcher-friendly) to red (hitter-friendly). */
K.DIVERGE = [[0, '#2166ac'], [0.25, '#67a9cf'], [0.5, '#2d333b'], [0.75, '#ef8a62'], [1, '#b2182b']];
K.SEQ = [[0, '#161b22'], [0.25, '#1f3b57'], [0.5, '#2f6f9f'], [0.75, '#e08a3c'], [1, '#f85149']];

/* Strike-zone shapes in catcher's view (feet): the rule-book zone from sz_bot to sz_top over the 17-inch plate
 * (±0.708 ft, plus a ball radius ±0.12 ft for the called zone), the 3×3 grid and the plate drawn below. */
K.PLATE_HALF = 17 / 24;
K.zoneShapes = (top, bot, opts) => {
  const o = opts || {};
  const T = isNum(top) ? top : 3.4, B = isNum(bot) ? bot : 1.6, h = K.PLATE_HALF;
  const line = { color: o.colour || '#e6edf3', width: 1.6 };
  const thin = { color: 'rgba(230,237,243,0.35)', width: 0.8, dash: 'dot' };
  const out = [{ type: 'rect', x0: -h, x1: h, y0: B, y1: T, line: line, fillcolor: 'rgba(0,0,0,0)' }];
  if (o.grid !== false) {
    [1, 2].forEach(i => {
      out.push({ type: 'line', x0: -h + (2 * h) * i / 3, x1: -h + (2 * h) * i / 3, y0: B, y1: T, line: thin });
      out.push({ type: 'line', x0: -h, x1: h, y0: B + (T - B) * i / 3, y1: B + (T - B) * i / 3, line: thin });
    });
  }
  if (o.plate !== false) {
    const y0 = isNum(o.plateY) ? o.plateY : 0.25;
    out.push({ type: 'path', path: 'M ' + (-h) + ' ' + y0 + ' L ' + h + ' ' + y0 + ' L ' + h + ' ' + (y0 - 0.1) + ' L 0 ' + (y0 - 0.22) + ' L ' + (-h) + ' ' + (y0 - 0.1) + ' Z', line: { color: '#8b949e', width: 1 }, fillcolor: 'rgba(230,237,243,0.12)' });
  }
  return out;
};

/* A grid in any of the shapes a payload may use -> {x: centres, y: centres, z: [[row by y][col by x]], n, xe, ye}.
 * Accepted: [[...]] rows top-to-bottom (default extent x −1.5..1.5, z 1..4 ft); {x|xe|x_edges, z|ze|z_edges|y, v|values|grid|z, n};
 * a list of cells [{x, z, v, n}] or [[x, z, v, n]]. */
K.gridOf = (g, opts) => {
  const o = opts || {};
  if (!g) return null;
  const centres = (e, n) => {
    if (!e || !e.length) return null;
    if (e.length === n + 1) return e.slice(0, n).map((v, i) => (v + e[i + 1]) / 2);
    return e.slice(0, n);
  };
  const lin = (a, b, n) => { const out = []; for (let i = 0; i < n; i++) out.push(a + (b - a) * (i + 0.5) / n); return out; };
  // A matrix (rows of equal length, top row first) unless it looks like a list of [x, z, v, n] cells.
  const matrix = Array.isArray(g) && g.length > 1 && g.every(r => Array.isArray(r) && r.length === g[0].length) && g[0].length > 1 && !(g[0].length <= 4 && g.length > 6);
  if (matrix) {
    const rows = g.slice().reverse(); // top-to-bottom in -> bottom-to-top
    const ny = rows.length, nx = rows[0].length;
    return { x: lin(o.x0 !== undefined ? o.x0 : -1.5, o.x1 !== undefined ? o.x1 : 1.5, nx), y: lin(o.z0 !== undefined ? o.z0 : 1, o.z1 !== undefined ? o.z1 : 4, ny), z: rows, n: null };
  }
  if (Array.isArray(g)) {
    // cells
    const cells = g.map(c => (Array.isArray(c) ? { x: c[0], z: c[1], v: c[2], n: c[3] } : { x: c.x !== undefined ? c.x : c.px, z: c.z !== undefined ? c.z : (c.y !== undefined ? c.y : c.pz), v: c.v !== undefined ? c.v : (c.value !== undefined ? c.value : c.xw), n: c.n }))
      .filter(c => isNum(c.x) && isNum(c.z));
    if (!cells.length) return null;
    const xs = Array.from(new Set(cells.map(c => +c.x))).sort((a, b) => a - b), ys = Array.from(new Set(cells.map(c => +c.z))).sort((a, b) => a - b);
    const z = ys.map(() => xs.map(() => null)), n = ys.map(() => xs.map(() => null));
    cells.forEach(c => { const i = ys.indexOf(+c.z), j = xs.indexOf(+c.x); z[i][j] = isNum(c.v) ? +c.v : null; n[i][j] = isNum(c.n) ? +c.n : null; });
    return { x: xs, y: ys, z: z, n: n };
  }
  if (typeof g === 'object') {
    const V = g.v || g.values || g.grid || g.z || g.value || g.mean;
    if (!Array.isArray(V) || !V.length || !Array.isArray(V[0])) return null;
    const xe = g.x || g.xe || g.x_edges || g.xbins || g.px;
    const ye = g.zb || g.ze || g.z_edges || g.zbins || g.y || g.pz || (Array.isArray(g.z) && !Array.isArray(g.z[0]) ? g.z : null);
    let rows = V, nrows = g.n || g.count || null;
    const ny = rows.length, nx = rows[0].length;
    if (g.order === 'top' || g.top_down) { rows = rows.slice().reverse(); if (nrows) nrows = nrows.slice().reverse(); }
    return { x: centres(xe, nx) || lin(-1.5, 1.5, nx), y: centres(ye, ny) || lin(1, 4, ny), z: rows, n: nrows };
  }
  return null;
};
/* Zone heatmap in catcher's view. grid: anything K.gridOf reads. opts {title, fmt, diverge (centre), zmin, zmax, top, bot, colorbar, label}. */
K.zoneHeat = (el, grid, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const G = K.gridOf(grid, o);
  if (!G) { node.innerHTML = K.muted('No location data for this selection.'); return; }
  const flat = [].concat.apply([], G.z).filter(isNum);
  if (!flat.length) { node.innerHTML = K.muted('No location data for this selection.'); return; }
  let zmin = isNum(o.zmin) ? o.zmin : Math.min.apply(null, flat), zmax = isNum(o.zmax) ? o.zmax : Math.max.apply(null, flat);
  if (isNum(o.diverge)) { const r = Math.max(Math.abs(zmax - o.diverge), Math.abs(o.diverge - zmin)) || 1; zmin = o.diverge - r; zmax = o.diverge + r; }
  const text = G.z.map((row, i) => row.map((v, j) => (isNum(v) ? K.fmtV(v, o.fmt) + (G.n && G.n[i] && isNum(G.n[i][j]) ? ' · n=' + G.n[i][j] : '') : 'no pitches')));
  const narrow = K.narrow(node);
  K.plot(node, [{
    type: 'heatmap', x: G.x, y: G.y, z: G.z, text: text, hovertemplate: 'x %{x:.2f} ft, height %{y:.2f} ft<br>' + K.esc(o.label || 'value') + ': %{text}<extra></extra>',
    colorscale: isNum(o.diverge) ? (o.reverse ? K.DIVERGE.map(c => [1 - c[0], c[1]]).reverse() : K.DIVERGE) : K.SEQ, zmin: zmin, zmax: zmax, zsmooth: o.smooth === false ? false : 'best',
    showscale: o.colorbar !== false && !narrow, colorbar: { thickness: 8, len: 0.8, tickfont: { size: 9, color: K.C.text2 } }, connectgaps: false
  }], K.layout({
    margin: { l: 30, r: narrow ? 8 : 10, t: o.title ? 26 : 8, b: 26 }, title: o.title ? { text: o.title, font: { size: 12, color: K.C.text } } : undefined,
    xaxis: { range: [-1.75, 1.75], zeroline: false, showgrid: false, title: '', tickvals: [-1, 0, 1], scaleanchor: 'y', scaleratio: 1 },
    yaxis: { range: [0.3, 4.4], zeroline: false, showgrid: false, title: '', tickvals: [1, 2, 3, 4] },
    shapes: K.zoneShapes(o.top, o.bot)
  }));
};

/* Spray chart. pts: [{x, y (feet from home, y to centre field), v (colour value), ev, la, ev_desc, date}] — K.sprayPoints
 * converts payload shapes. dims: {lf, lcf, cf, rcf, rf} wall distances (ft). opts {fmt, label, diverge, zmin, zmax}. */
K.HC = { x0: 125.42, y0: 198.27, s: 2.495 };
/* Result codes on the career files' spray rows (analytics/careers.py EV_CODE). */
K.EV_CODE = { 0: 'field_out', 1: 'single', 2: 'double', 3: 'triple', 4: 'home_run', 5: 'field_error' };
K.sprayPoints = (raw) => {
  if (!raw) return [];
  let pts = raw.points || raw.pts || raw.bip || raw;
  const cols = raw.cols || raw.columns || raw.fields || null;
  if (!Array.isArray(pts)) return [];
  return pts.map(p => {
    let o;
    if (Array.isArray(p)) {
      if (cols) { o = {}; cols.forEach((c, i) => { o[c] = p[i]; }); } else o = { hc_x: p[0], hc_y: p[1], xwoba_plus: p[2], launch_speed: p[3], launch_angle: p[4], event: p[5] };
      if (typeof o.event === 'number') o.event = K.EV_CODE[o.event] || 'field_out';
    } else o = p;
    let x = o.x, y = o.y;
    if (isNum(o.hc_x) && isNum(o.hc_y)) { x = K.HC.s * (o.hc_x - K.HC.x0); y = K.HC.s * (K.HC.y0 - o.hc_y); }
    else if (isNum(o.spray) && isNum(o.dist)) { const a = o.spray * Math.PI / 180; x = o.dist * Math.sin(a); y = o.dist * Math.cos(a); }
    const v = [o.v, o.xwoba_plus, o.xw, o.xwoba, o.value].find(isNum);
    return { x: x, y: y, v: isNum(v) ? Number(v) : null, ev: o.launch_speed !== undefined ? o.launch_speed : o.ev, la: o.launch_angle !== undefined ? o.launch_angle : o.la, ev_desc: o.event || o.events || o.ev_desc || o.res || '', date: o.date || o.game_date || '', pt: o.pitch_type || o.pt || '', bb: o.bb_type || o.bb || '' };
  }).filter(p => isNum(p.x) && isNum(p.y));
};
K.fieldShapes = dims => {
  const d = Object.assign({ lf: 330, lcf: 375, cf: 400, rcf: 375, rf: 330 }, dims || {});
  const ang = [-45, -22.5, 0, 22.5, 45], dist = [d.lf, d.lcf, d.cf, d.rcf, d.rf].map(Number);
  const pts = [];
  for (let a = -45; a <= 45.001; a += 1.5) {
    let i = 0; while (i < 3 && a > ang[i + 1]) i++;
    const t = (a - ang[i]) / (ang[i + 1] - ang[i]);
    // cosine interpolation keeps the wall round between the five measured points
    const u = (1 - Math.cos(Math.PI * Math.max(0, Math.min(1, t)))) / 2;
    const r = dist[i] + (dist[i + 1] - dist[i]) * u, rad = a * Math.PI / 180;
    pts.push([r * Math.sin(rad), r * Math.cos(rad)]);
  }
  const wall = 'M 0 0 L ' + pts.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L ') + ' Z';
  const b = 90 / Math.SQRT2;
  const diamond = 'M 0 0 L ' + b.toFixed(1) + ' ' + b.toFixed(1) + ' L 0 ' + (2 * b).toFixed(1) + ' L ' + (-b).toFixed(1) + ' ' + b.toFixed(1) + ' Z';
  const grass = 'M ' + (-b - 30).toFixed(1) + ' ' + (b + 30).toFixed(1) + ' Q 0 ' + (2 * b + 80).toFixed(1) + ' ' + (b + 30).toFixed(1) + ' ' + (b + 30).toFixed(1);
  return [
    { type: 'path', path: wall, line: { color: '#3d444d', width: 1.5 }, fillcolor: 'rgba(63,185,80,0.05)', layer: 'below' },
    { type: 'path', path: grass, line: { color: '#3d444d', width: 1 }, layer: 'below' },
    { type: 'path', path: diamond, line: { color: '#6e7681', width: 1 }, fillcolor: 'rgba(210,153,34,0.06)', layer: 'below' }
  ];
};
K.spray = (el, pts, dims, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  if (BP.charts && typeof BP.charts.sprayChart === 'function' && o.local !== true && (o.fmt === '3' || o.fieldOnly)) {
    // The shell's spray chart (hits filled, outs open, xwOBA+ 0 to 1.2); points in feet.
    try {
      BP.charts.sprayChart(node, (pts || []).map(p => ({ x: p.x, y: p.y, xwoba_plus: p.v, launch_speed: p.ev, launch_angle: p.la, event: p.ev_desc, pitch_type: p.pt })), { dims: dims || {}, height: o.height || (K.narrow(node) ? 320 : 400) });
      return;
    } catch (e) { console.warn('spray', e); }
  }
  if ((!pts || !pts.length) && !o.fieldOnly) { node.innerHTML = K.muted('No batted balls with hit coordinates for this selection.'); return; }
  pts = pts || [];
  const vs = pts.map(p => p.v).filter(isNum);
  const centre = isNum(o.diverge) ? o.diverge : (vs.length ? K.median(vs) : 0);
  let lo = isNum(o.zmin) ? o.zmin : null, hi = isNum(o.zmax) ? o.zmax : null;
  if (lo === null || hi === null) { const r = vs.length ? Math.max.apply(null, vs.map(v => Math.abs(v - centre))) : 1; lo = centre - r; hi = centre + r; }
  const narrow = K.narrow(node);
  const text = pts.map(p => [p.ev_desc ? K.titleCase(p.ev_desc) : 'Batted ball', p.date ? K.short(p.date) : '', isNum(p.ev) ? K.num(p.ev, 1) + ' mph' : '', isNum(p.la) ? K.num(p.la, 0) + '°' : '', p.pt ? K.pitchName(p.pt) : ''].filter(Boolean).join(' · ') +
    (isNum(p.v) ? '<br>' + K.esc(o.label || 'xwOBA+') + ' ' + K.fmtV(p.v, o.fmt) : ''));
  K.plot(node, [{
    type: 'scatter', mode: 'markers', x: pts.map(p => p.x), y: pts.map(p => p.y), text: text, hovertemplate: '%{text}<extra></extra>',
    marker: { size: narrow ? 5 : 7, opacity: 0.85, color: pts.map(p => (isNum(p.v) ? p.v : centre)), colorscale: K.DIVERGE, cmin: lo, cmax: hi,
      showscale: !narrow, colorbar: { title: { text: o.label || 'xwOBA+', side: 'right', font: { size: 10 } }, thickness: 8, len: 0.7, tickfont: { size: 9 } }, line: { color: '#0d1117', width: 0.5 } }
  }], K.layout({
    margin: { l: 10, r: narrow ? 10 : 20, t: 10, b: 10 }, shapes: K.fieldShapes(dims),
    xaxis: { range: [-330, 330], visible: false, scaleanchor: 'y', scaleratio: 1 }, yaxis: { range: [-20, 460], visible: false }
  }));
};

/* Movement plot (catcher's view, inches): induced vertical break against horizontal break, one dot per pitch (or per
 * pitch type), league reference clouds as faint ellipses, and the arm-angle line from the release point. */
K.movement = (el, groups, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  if (!groups || !groups.length) { node.innerHTML = K.muted('No pitch movement data.'); return; }
  const traces = [], shapes = [];
  (o.league || []).forEach(g => {
    if (!isNum(g.hb) || !isNum(g.ivb)) return;
    const sx = isNum(g.sd_hb) ? g.sd_hb : 3, sy = isNum(g.sd_ivb) ? g.sd_ivb : 3;
    shapes.push({ type: 'circle', x0: g.hb - 1.5 * sx, x1: g.hb + 1.5 * sx, y0: g.ivb - 1.5 * sy, y1: g.ivb + 1.5 * sy, line: { color: K.alpha(K.pitchColour(g.pt), 0.5), width: 1, dash: 'dot' }, fillcolor: K.alpha(K.pitchColour(g.pt), 0.05), layer: 'below' });
  });
  groups.forEach(g => {
    const pts = g.points || [];
    if (pts.length) traces.push({ type: 'scatter', mode: 'markers', name: K.pitchName(g.pt), x: pts.map(p => p[0]), y: pts.map(p => p[1]), hoverinfo: 'skip', showlegend: false,
      marker: { size: 4, color: K.alpha(K.pitchColour(g.pt), 0.35) } });
    if (isNum(g.hb) && isNum(g.ivb)) traces.push({ type: 'scatter', mode: 'markers+text', name: K.pitchName(g.pt) + (isNum(g.usage) ? ' (' + K.pct(g.usage, 0) + ')' : ''), x: [g.hb], y: [g.ivb], text: [g.pt], textposition: 'top center', textfont: { color: K.C.text, size: 10 },
      marker: { size: 12 + (isNum(g.usage) ? 18 * Math.sqrt(g.usage) : 6), color: K.pitchColour(g.pt), line: { color: '#0d1117', width: 1.5 } },
      hovertemplate: '<b>' + K.esc(K.pitchName(g.pt)) + '</b><br>HB %{x:.1f} in · IVB %{y:.1f} in' + (isNum(g.velo) ? '<br>' + K.num(g.velo, 1) + ' mph' : '') + (isNum(g.usage) ? ' · ' + K.pct(g.usage, 1) + ' usage' : '') + '<extra></extra>' });
  });
  if (isNum(o.armAngle)) {
    // Arm angle in degrees above horizontal, drawn from the origin towards the arm side.
    const a = o.armAngle * Math.PI / 180, side = isNum(o.armSide) ? o.armSide : (o.throws === 'L' ? 1 : -1), r = 22;
    shapes.push({ type: 'line', x0: 0, y0: 0, x1: side * r * Math.cos(a), y1: r * Math.sin(a), line: { color: '#e6edf3', width: 1.5, dash: 'dash' } });
  }
  const narrow = K.narrow(node);
  K.plot(node, traces, K.layout(Object.assign({
    margin: { l: 44, r: 10, t: 10, b: 40 }, shapes: shapes,
    xaxis: { title: o.xTitle || 'Horizontal break (in, catcher\'s view)', range: [-25, 25], zeroline: true, zerolinecolor: '#3d444d', dtick: 10 },
    yaxis: { title: 'Induced vertical break (in)', range: [-25, 25], zeroline: true, zerolinecolor: '#3d444d', dtick: 10, scaleanchor: narrow ? undefined : 'x' }
  }, groups.length > 1 && !narrow ? { showlegend: true, legend: { orientation: 'v', x: 1.02, y: 1, font: { size: 10, color: K.C.text2 } } } : {})));
};

/* Reliability diagram: series [{name, colour, bins: [{lo, hi, n, mean_p|p, freq|obs}]}]. */
K.reliability = (el, series, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const lo = isNum(o.min) ? o.min : 0, hi = isNum(o.max) ? o.max : 1;
  const tr = [{ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
  series.forEach(s => {
    const bins = K.binsOf(s.bins).filter(b => b.n >= (o.minN || 1));
    if (!bins.length) return;
    const maxN = Math.max.apply(null, bins.map(b => b.n || 1));
    tr.push({ type: 'scatter', mode: 'lines+markers', name: s.name, x: bins.map(b => b.x), y: bins.map(b => b.y), customdata: bins.map(b => b.n),
      marker: { size: bins.map(b => 5 + 13 * Math.sqrt((b.n || 1) / maxN)), color: s.colour }, line: { color: s.colour, width: 1.5 },
      hovertemplate: K.esc(s.name) + ': forecast %{x:' + (o.fmt || '.1%') + '}, observed %{y:' + (o.fmt || '.1%') + '} (n=%{customdata})<extra></extra>' });
  });
  if (tr.length < 2) { node.innerHTML = K.muted('No reliability bins.'); return; }
  K.plot(node, tr, K.layout({ showlegend: true, legend: { orientation: 'h', y: -0.24, font: { color: K.C.text2, size: 10 } }, margin: { l: 55, r: 15, t: 10, b: 84 },
    xaxis: { title: o.xt || 'Forecast', tickformat: o.fmt || '.0%', range: [lo, hi] }, yaxis: { title: o.yt || 'Observed', tickformat: o.fmt || '.0%', range: [lo, hi] } }));
};
K.binsOf = bins => (bins || []).map(b => (Array.isArray(b) ? { x: b[0], y: b[1], n: b[2] || 0 } : { x: [b.mean_p, b.p, b.pred, b.x, b.forecast].find(isNum), y: [b.freq, b.obs, b.y, b.observed, b.actual].find(isNum), n: b.n || b.count || 0, lo: b.lo, hi: b.hi }))
  .filter(b => isNum(b.x) && isNum(b.y));

// ── catalogue helpers ──────────────────────────────────────────────────────

/* {cols|fields|columns, rows} (the contract's compact frames) or an array of objects -> [{...}]. */
K.colRows = x => {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  const cols = x.cols || x.fields || x.columns, rows = x.rows || x.data;
  if (!Array.isArray(cols) || !Array.isArray(rows)) return [];
  return rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = Array.isArray(r) ? r[i] : undefined; }); return o; });
};

K.metaOf = metrics => { const m = {}; (metrics || []).forEach(x => { m[x.key] = x; }); return m; };
K.groups = metrics => {
  const out = [];
  (metrics || []).forEach(m => { let g = out.find(x => x.name === (m.group || 'Other')); if (!g) { g = { name: m.group || 'Other', items: [] }; out.push(g); } g.items.push(m); });
  return out;
};
/* First key of an object (or metric list) matching a candidate: exact strings first, then regexes. */
K.pick = (obj, cands) => {
  const keys = Array.isArray(obj) ? obj.map(m => (m && m.key !== undefined ? m.key : m)) : Object.keys(obj || {});
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (typeof c === 'string' && keys.indexOf(c) >= 0) return c; }
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (c instanceof RegExp) { const k = keys.find(x => c.test(x)); if (k) return k; } }
  return null;
};
K.val = (obj, cands) => { const k = K.pick(obj || {}, cands); return k ? obj[k] : null; };
/* Up to n metrics: the preferred candidates in order, then one per group, then the rest. */
K.headline = (metrics, prefs, n) => {
  const out = [];
  const usable = (metrics || []).slice();
  (prefs || []).forEach(p => {
    if (out.length >= n) return;
    const re = p instanceof RegExp ? p : new RegExp('^' + p + '$');
    const m = usable.find(x => re.test(x.key) && out.indexOf(x) < 0);
    if (m) out.push(m);
  });
  const seen = {}; out.forEach(m => { seen[m.group] = 1; });
  usable.forEach(m => { if (out.length < n && !seen[m.group] && out.indexOf(m) < 0) { out.push(m); seen[m.group] = 1; } });
  usable.forEach(m => { if (out.length < n && out.indexOf(m) < 0) out.push(m); });
  return out.slice(0, n);
};
K.shortLabel = s => String(s || '').replace(/percentage/i, '%').replace(/ over expected/i, ' v exp').replace(/^Expected /, 'x').slice(0, 24);
K.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + enc(key) + '" title="Glossary: ' + K.esc(key) + '">' + text + '</a>';
/* Catalogue payload -> {metrics, players, ...}; tolerates a wrapper {"ok", "hitters": {...}}. */
K.catOf = (d, key) => {
  if (!d || d.ok === false) return null;
  let out = null;
  if (d.players && d.metrics) out = d;
  else {
    const inner = d[key] || d.catalogue || d.data;
    if (inner && inner.players) out = Object.assign({}, d, inner);
    else if (d.players) out = d;
  }
  if (out && /hitter|pitcher/.test(String(key || ''))) K.countPct(out, /pitcher/.test(key) ? 'pitcher' : 'hitter');
  return out;
};
/* The build leaves the counting stats (fmt "int": G, PA, HR, W, SO...) without a percentile, so the top line of every
 * player's percentile panel and of compare used to read as a missing sample. They get one here, placed like the
 * build's (100 = best, ties at the midpoint) against the regulars (the payload's reference rule, e.g. PA >= 2.1 a team
 * game), for every player at or above the catalogue's sample floor: by volume when more is better (HR, SO for a
 * pitcher), per PA / BF when fewer is better (a hitter's SO, a pitcher's BB), so playing time is not read as a fault.
 * Metrics left without a percentile (a 0/1 flag, too few regulars) are marked m._noPct. Runs once per catalogue. */
K.countPct = (cat, kind) => {
  if (!cat || cat._countPct || !cat.players || !Array.isArray(cat.metrics)) return cat;
  cat._countPct = true;
  const P = cat.players, ids = Object.keys(P);
  const has = {};
  ids.forEach(id => { const pc = P[id].pct || {}; Object.keys(pc).forEach(x => { if (isNum(pc[x])) has[x] = 1; }); });
  const todo = cat.metrics.filter(m => m && m.key && !has[m.key] && m.fmt === 'int');
  if (!todo.length) return cat;
  const pit = kind === 'pitcher';
  const nOf = p => K.sampleOf(p, kind);
  const ref = cat.reference || {};
  const refMin = isNum(pit ? ref.min_bf : ref.min_pa) ? Number(pit ? ref.min_bf : ref.min_pa) : null;
  const fl = cat.floors || {};
  const floor = isNum(pit ? fl.bf : fl.pa) ? Number(pit ? fl.bf : fl.pa) : 50;
  let pool = ids.filter(id => (refMin !== null ? nOf(P[id]) >= refMin : P[id].qualified === true));
  if (pool.length < 10) pool = ids.filter(id => nOf(P[id]) >= floor);
  const roleOf = id => { const p = P[id]; if (pit) return K.roleOf(p); const r = String(p.pos || '').toUpperCase(); return r === 'LF' || r === 'RF' ? 'LF/RF' : r; };
  const place = (sorted, v, lower) => {
    const n = sorted.length;
    if (n < 2) return null;
    let lo = 0, hi = 0;
    sorted.forEach(y => { if (y < v) lo++; if (y <= v) hi++; });
    const below = lo, above = n - hi, tie = Math.max(0, hi - lo - 1);
    return Math.max(0, Math.min(100, Math.round(100 * ((lower ? above : below) + 0.5 * tie) / (n - 1))));
  };
  todo.forEach(m => {
    if (/flag/.test(m.key)) { m._noPct = true; return; }
    const lower = !!m.lower;
    const sv = id => { const v = (P[id].values || {})[m.key], n = nOf(P[id]); if (!isNum(v) || n < floor || n <= 0) return null; return lower ? Number(v) / n : Number(v); };
    const refv = pool.map(sv).filter(isNum).sort((a, b) => a - b);
    if (refv.length < 10) { m._noPct = true; return; }
    const byRole = {};
    pool.forEach(id => { const v = sv(id); if (isNum(v)) (byRole[roleOf(id)] = byRole[roleOf(id)] || []).push(v); });
    Object.keys(byRole).forEach(r => byRole[r].sort((a, b) => a - b));
    m._pctNote = lower ? 'percentile per ' + (pit ? 'batter faced' : 'plate appearance') + ' among the regulars, computed on the page' : 'percentile by volume among the regulars, computed on the page';
    ids.forEach(id => {
      const v = sv(id);
      if (!isNum(v)) return;
      const p = P[id];
      p.pct = p.pct || {};
      const x = place(refv, v, lower);
      if (isNum(x)) p.pct[m.key] = x;
      const rv = byRole[roleOf(id)] || [];
      if (rv.length >= 5) { p.pct_role = p.pct_role || {}; const y = place(rv, v, lower); if (isNum(y)) p.pct_role[m.key] = y; }
    });
  });
  return cat;
};
/* What a slider without a percentile says: no value at all, no percentile by design, or a sample under the floor. */
K.noPctText = (m, v) => (!isNum(v) ? 'no data' : m && m._noPct ? 'no percentile for this stat' : 'below the sample floor');
K.sampleOf = (p, kind) => (kind === 'pitcher' ? [p.bf, p.tbf, p.n, (p.values || {}).bf].find(isNum) : [p.pa, p.n, (p.values || {}).pa].find(isNum)) || 0;
K.roleOf = p => {
  const r = String(p.role || p.pos || '').toUpperCase();
  if (/^SP|START/.test(r)) return 'SP';
  if (/^RP|RELI|^CL/.test(r)) return 'RP';
  const v = p.values || {};
  if (isNum(v.gs) && isNum(v.g) && v.g > 0) return v.gs / v.g >= 0.5 ? 'SP' : 'RP';
  return r === 'P' ? 'P' : r;
};

// ── player picker (typeahead over players_index.json and the catalogues) ───

/* host: element; opts {value (pid), placeholder, onPick(pid), filter(pid, info)}. */
K.picker = (host, opts) => {
  const o = opts || {};
  host.classList.add('gq-picker');
  host.innerHTML = '<input type="search" class="gq-search" autocomplete="off" spellcheck="false" placeholder="' + K.esc(o.placeholder || 'Type a player…') + '"><div class="gq-pick-list"></div>';
  const input = host.querySelector('input'), list = host.querySelector('.gq-pick-list');
  if (o.value) input.value = o.label || K.name(o.value);
  let items = null;
  const build = () => {
    const N = Object.assign({}, K.NAMES, o.extra || {});
    items = Object.keys(N).filter(id => !o.filter || o.filter(id, N[id])).map(id => ({ id: id, n: N[id].name || id, s: [N[id].pos, N[id].team ? K.teamAbbr(N[id].team) : ''].filter(Boolean).join(' · '), f: K.fold(N[id].name || id) }));
    items.sort((a, b) => a.n.localeCompare(b.n));
  };
  const close = () => { list.innerHTML = ''; list.style.display = 'none'; };
  const show = () => {
    if (!items) build();
    const q = K.fold(input.value.trim());
    if (q.length < 2) { close(); return; }
    const words = q.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.f.indexOf(w) >= 0)).slice(0, 12);
    list.innerHTML = hits.length ? hits.map(h => '<button type="button" data-id="' + K.esc(h.id) + '"><span>' + K.esc(h.n) + '</span><span class="gq-pick-sub">' + K.esc(h.s) + '</span></button>').join('') : '<div class="gq-pick-none">No match.</div>';
    list.style.display = 'block';
  };
  input.addEventListener('input', show);
  input.addEventListener('focus', () => { input.select(); });
  input.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') close();
    if (ev.key === 'Enter') { const b = list.querySelector('button[data-id]'); if (b) { ev.preventDefault(); b.click(); } }
  });
  list.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-id]');
    if (!b) return;
    input.value = (o.extra && o.extra[b.dataset.id] && o.extra[b.dataset.id].name) || K.name(b.dataset.id);
    close();
    if (o.onPick) o.onPick(b.dataset.id);
  });
  const outside = ev => { if (!host.contains(ev.target)) close(); };
  document.addEventListener('click', outside);
  if (has('onLeave')) BP.onLeave(() => document.removeEventListener('click', outside));
  return { input: input, refresh: () => { items = null; } };
};

/* Register a page under a route name and its pattern(s); the shell's BP.route accepts either. */
K.route = (names, fn) => {
  if (typeof BP.route !== 'function') return;
  (Array.isArray(names) ? names : [names]).forEach(n => { try { BP.route(n, fn); } catch (e) { console.warn('route failed', n, e); } });
};
/* A page header in the house style. */
K.head = (title, sub, right, badge, colour) => '<div class="gq-head"' + (colour ? ' style="--tc:' + colour + '"' : '') + '>' + (badge ? '<div class="gq-badge">' + badge + '</div>' : '') +
  '<div class="gq-head-body"><h2>' + title + '</h2>' + (sub ? '<div class="gq-head-sub">' + sub + '</div>' : '') + '</div>' + (right ? '<div class="gq-head-links">' + right + '</div>' : '') + '</div>';

// ════════════════════════════════════════════════════════════════════════════
// Catalogue page shared by hitters and pitchers
// ════════════════════════════════════════════════════════════════════════════

const HIT_PREFS = ['xwoba_plus', 'xwoba_savant', 'woba', 'war', 'dv', 'decision_value', 'bat_speed_adj', 'barrel_pct', 'chase_pct', 'k_pct', 'bb_pct'];
const PIT_PREFS = ['pitching_plus', 'stuff_plus', 'location_plus', 'war', 'k_bb_pct', 'xwoba_plus', 'ra9', 'fip', 'csw_pct', 'whiff_pct'];
K.HIT_PREFS = HIT_PREFS; K.PIT_PREFS = PIT_PREFS;
const STATE = { hitter: { q: '', team: '', pos: '', role: '', floor: null, basis: 'all', extra: [], level: '', season: null, sort: null },
  pitcher: { q: '', team: '', pos: '', role: '', floor: null, basis: 'all', extra: [], level: '', season: null, sort: null } };

K.renderCatalogue = function (el, params, state, kind) {
  const L = K.L(params, state);
  const pit = kind === 'pitcher';
  const file = pit ? 'pitchers.json' : 'hitters.json';
  el.innerHTML = '<div class="card"><div class="card-header">' + K.LN(L) + ' ' + (pit ? 'pitchers' : 'hitters') + ' <span class="card-sub" id="cat-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls">' +
    '<label>Search<input id="cat-q" class="gq-search" type="search" placeholder="name or team…"></label>' +
    '<label>Team<select id="cat-team"><option value="">All teams</option></select></label>' +
    (pit ? '<label>Role<select id="cat-role"><option value="">Starters and relievers</option><option value="SP">Starters</option><option value="RP">Relievers</option></select></label>'
      : '<label>Position<select id="cat-pos"><option value="">All positions</option></select></label>') +
    '<label>Min ' + (pit ? 'batters faced' : 'PA') + ' <span id="cat-floor-v"></span><input id="cat-floor" type="range" min="0" max="700" step="5"></label>' +
    '<label>Percentiles<select id="cat-basis"><option value="all">against ' + K.LN(L) + '</option><option value="role">against ' + (pit ? 'role (SP / RP)' : 'position') + '</option></select></label>' +
    '<label>Add a metric<select id="cat-extra"><option value="">—</option></select></label>' +
    '<label>&nbsp;<button type="button" id="cat-clear" class="gq-btn">Clear added</button></label>' +
    '</div><div id="cat-chips" class="gq-chips"></div><div id="cat-table">' + K.muted('Loading…') + '</div><div class="pg-note gq-note" id="cat-note"></div></div>';
  return K.ready().then(() => {
    const S = K.S(params, state);
    return Promise.all([K.loadY(L, S, file), K.loadNames()]).then(res => ({ S: S, raw: res[0] }));
  }).then(o => {
    if (!K.alive(el)) return;
    const S = o.S, cat = K.catOf(o.raw, pit ? 'pitchers' : 'hitters');
    const $ = id => document.getElementById(id);
    if (!cat) { $('cat-table').innerHTML = K.notBuilt('The ' + K.LN(L) + ' ' + S + ' ' + (pit ? 'pitcher' : 'hitter') + ' catalogue', o.raw); $('cat-sub').textContent = ''; return; }
    K.learnCat(cat);
    const st = STATE[kind];
    if (st.level !== L || st.season !== S) { st.level = L; st.season = S; st.floor = null; st.team = ''; }
    const P = cat.players, metrics = cat.metrics || [], meta = K.metaOf(metrics);
    const ids = Object.keys(P);
    const maxN = Math.max.apply(null, ids.map(id => K.sampleOf(P[id], kind)).concat([50]));
    const floorDef = [cat.floor, cat.min_pa, cat.min_bf, cat.qualified_at].find(isNum);
    $('cat-floor').max = String(Math.ceil(maxN / 10) * 10);
    if (st.floor === null || st.floor > maxN) st.floor = isNum(floorDef) ? Math.min(floorDef, maxN) : Math.min(pit ? 100 : 150, Math.round(maxN * 0.25));
    $('cat-floor').value = st.floor; $('cat-floor-v').textContent = st.floor;
    const teams = {};
    ids.forEach(id => { const t = P[id].team; if (t) teams[t] = (teams[t] || 0) + 1; });
    $('cat-team').innerHTML = '<option value="">All teams</option>' + Object.keys(teams).sort((a, b) => K.teamAbbr(a).localeCompare(K.teamAbbr(b))).map(t => '<option value="' + K.esc(t) + '"' + (t === st.team ? ' selected' : '') + '>' + K.esc(K.teamAbbr(t) + ' · ' + K.teamName(t)) + '</option>').join('');
    if (!pit) {
      const pos = {};
      ids.forEach(id => { const x = P[id].pos; if (x) pos[x] = (pos[x] || 0) + 1; });
      const ORDER = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'OF', 'IF', 'DH', 'TWP'];
      $('cat-pos').innerHTML = '<option value="">All positions</option>' + Object.keys(pos).sort((a, b) => (ORDER.indexOf(a) < 0 ? 99 : ORDER.indexOf(a)) - (ORDER.indexOf(b) < 0 ? 99 : ORDER.indexOf(b))).map(x => '<option value="' + K.esc(x) + '"' + (x === st.pos ? ' selected' : '') + '>' + K.esc(x) + ' (' + pos[x] + ')</option>').join('');
    } else $('cat-role').value = st.role;
    $('cat-q').value = st.q; $('cat-basis').value = st.basis;
    $('cat-extra').innerHTML = '<option value="">—</option>' + K.groups(metrics).map(g => '<optgroup label="' + K.esc(g.name) + '">' + g.items.map(m => '<option value="' + K.esc(m.key) + '">' + K.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
    st.extra = st.extra.filter(k => meta[k]);
    const heads = K.headline(metrics, pit ? PIT_PREFS : HIT_PREFS, 7);
    const draw = () => drawCatalogue(L, S, kind, cat, heads);
    let t = null;
    $('cat-q').oninput = e => { st.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    $('cat-team').onchange = e => { st.team = e.target.value; draw(); };
    if (pit) $('cat-role').onchange = e => { st.role = e.target.value; draw(); };
    else $('cat-pos').onchange = e => { st.pos = e.target.value; draw(); };
    $('cat-basis').onchange = e => { st.basis = e.target.value; draw(); };
    $('cat-floor').oninput = e => { st.floor = Number(e.target.value); $('cat-floor-v').textContent = st.floor; };
    $('cat-floor').onchange = draw;
    $('cat-extra').onchange = e => { const k = e.target.value; if (k && st.extra.indexOf(k) < 0 && heads.every(m => m.key !== k)) st.extra.push(k); e.target.value = ''; draw(); };
    $('cat-clear').onclick = () => { st.extra = []; draw(); };
    $('cat-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (!b) return; st.extra = st.extra.filter(k => k !== b.dataset.rm); draw(); };
    draw();
    $('cat-note').innerHTML = K.LN(L) + ' ' + S + (cat.updated_at ? ', updated ' + K.esc(K.fmtDate(cat.updated_at, { year: false })) : '') + '. Pills are percentiles (100 = best; ↓ metrics are already flipped so that red is always good) against every qualified ' + K.LN(L) + ' ' + (pit ? 'pitcher' : 'hitter') + ', or with the second option against the same ' + (pit ? 'role (starters or relievers)' : 'position') + '. ' +
      'Players below the sample floor show raw values only. Every metric is shrunk towards the league by its stabilisation point before ranking (see the <a href="#/glossary">glossary</a>). Headline columns: ' + heads.map(m => K.glossLink(m.key, K.esc(m.label))).join(' · ') + '. All ' + metrics.length + ' metrics are on every player page, the <a href="' + K.href(L, 'leaders', S) + '">leaders</a> page and in the <a href="' + K.href(L, 'lab', S) + '">lab</a>.';
  });
};

function drawCatalogue(L, S, kind, cat, heads) {
  const st = STATE[kind], pit = kind === 'pitcher';
  const P = cat.players, meta = K.metaOf(cat.metrics);
  const q = K.fold(st.q.trim());
  const extras = st.extra.map(k => meta[k]).filter(Boolean);
  const cols = heads.concat(extras.filter(m => heads.indexOf(m) < 0));
  const ids = Object.keys(P).filter(id => {
    const p = P[id];
    if (K.sampleOf(p, kind) < st.floor) return false;
    if (st.team && String(p.team) !== st.team) return false;
    if (!pit && st.pos && p.pos !== st.pos) return false;
    if (pit && st.role && K.roleOf(p) !== st.role) return false;
    if (q && K.fold(String(p.name || K.name(id)) + ' ' + K.teamAbbr(p.team) + ' ' + K.teamName(p.team)).indexOf(q) < 0) return false;
    return true;
  });
  const sortKey = (heads[0] || {}).key, sortLower = !!(heads[0] || {}).lower;
  ids.sort((a, b) => {
    const va = (P[a].values || {})[sortKey], vb = (P[b].values || {})[sortKey];
    const d = (isNum(vb) ? vb : -1e9) - (isNum(va) ? va : -1e9);
    return (sortLower ? -d : d) || K.sampleOf(P[b], kind) - K.sampleOf(P[a], kind);
  });
  const src = p => (st.basis === 'role' ? (p.pct_role || p.pct_pos || {}) : (p.pct || {}));
  const rows = ids.map((id, i) => {
    const p = P[id];
    return { _href: pit ? K.pitcherHref(L, id, S) : K.hitterHref(L, id, S), cells: [
      { v: i + 1, cls: 'pos-cell' },
      { v: p.name || K.name(id), html: '<a class="ply-link" href="' + (pit ? K.pitcherHref(L, id, S) : K.hitterHref(L, id, S)) + '">' + K.esc(p.name || K.name(id)) + '</a>' + (p.qualified === false ? ' <span class="gq-tag" title="Below the sample floor: no percentiles">small sample</span>' : '') },
      { v: K.teamAbbr(p.team), html: K.teamChip(L, p.team, S) },
      { v: pit ? K.roleOf(p) : (p.pos || ''), html: K.esc(pit ? K.roleOf(p) : (p.pos || '—')) },
      { v: p.age, html: isNum(p.age) ? K.num(p.age, 0) : '—', align: 'right' },
      { v: K.sampleOf(p, kind), html: K.int(K.sampleOf(p, kind)), align: 'right' }
    ].concat(cols.map(m => {
      const v = (p.values || {})[m.key], pc = src(p)[m.key];
      return { v: isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gq-val">' + K.fmt(m, v) + '</span> ' + K.pill(pc), align: 'right' };
    })) };
  });
  const host = document.getElementById('cat-table');
  if (!host) return;
  host.innerHTML = rows.length ? K.table([{ label: '#', sortable: false }, { label: pit ? 'Pitcher' : 'Hitter' }, { label: 'Team' }, { label: pit ? 'Role' : 'Pos' }, { label: 'Age', align: 'right' }, { label: pit ? 'BF' : 'PA', align: 'right' }]
    .concat(cols.map(m => ({ label: K.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') }))), rows.slice(0, 600), { sticky: true, compact: true })
    : K.muted('No ' + (pit ? 'pitcher' : 'hitter') + ' matches these filters.');
  K.sortable(host);
  const chips = document.getElementById('cat-chips');
  if (chips) chips.innerHTML = extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + K.esc(m.key) + '" title="Remove">' + K.esc(m.label) + ' ×</button>').join(' ') : '';
  const sub = document.getElementById('cat-sub');
  if (sub) sub.textContent = ids.length + ' of ' + Object.keys(P).length + (pit ? ' pitchers' : ' hitters') + (ids.length > 600 ? ' (first 600 shown)' : '') + ' · sorted by ' + ((heads[0] || {}).label || 'sample') + '; click a header to sort, a row to open the player';
}

function renderHitters(el, params, state) { return K.renderCatalogue(el, params, state, 'hitter'); }
K.route(['hitters', '#/<L>/hitters'], renderHitters);
})(window.BP || (window.BP = {}));
