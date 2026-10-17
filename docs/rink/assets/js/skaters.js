/* The Quant Rink — builder F's shared kit (RK.fk) and the skater catalogue (#/skaters).
 *
 * RK.fk is defined here and read lazily at render time by every other page of builder F (goalies,
 * player, teams, team, lines, leaders, history, lab, compare, calibration, docs: const K = () => RK.fk),
 * so script order among those files does not matter as long as this file is loaded after core.js. It
 * leans on the shell (core.js: RK.load, RK.tableHTML, RK.sortable, RK.plot, RK.layout, RK.pctColor,
 * RK.teamColour ...) where those exist and falls back to local copies.
 *
 * Data (oddsmarkets/nhl/PAYLOADS.md): data/<S>/skaters.json, a catalogue {"metrics": [METRIC], "players":
 * {pid: {"name","team","pos","age","gp","toi","qualified","values","pct","pct_pos"}}} with METRIC =
 * {key,label,group,fmt,lower,scope,desc,stabilises_at}; "pct" ranks against every qualified skater (the
 * league) and "pct_pos" against the position pool (forwards or defencemen). data/players_index.json
 * ({pid: [name, team, pos, first_season, last_season]}) and data/index.json (teams, season).
 *
 * Seasons are NHL ids (20262027) and shown as 2026–27. Address: #/skaters?p=F|D|C|L|R (&s=<season>). */
(function (RK) {
'use strict';

// ════════════════════════════════════════════════════════════════════════════
// The kit: RK.fk
// ════════════════════════════════════════════════════════════════════════════

const K = RK.fk = RK.fk || {};

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const escL = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const has = f => typeof RK[f] === 'function';
const enc = encodeURIComponent;
K.isNum = isNum;
K.has = has;
K.esc = s => (has('esc') ? RK.esc(s) : escL(s));
K.alive = el => !!el && el.isConnected;
K.ok = d => !!d && d.ok !== false;
K.muted = t => '<div class="muted">' + t + '</div>';
K.notBuilt = (what, d) => K.muted(K.esc(what) + ' is not available yet' + (d && d.reason ? ' (' + K.esc(K.cleanDesc(d.reason)) + ')' : '') + '. The payloads are rebuilt every run.');
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
/* Minutes -> "18:32" (ice time per game). */
K.mmss = m => { if (!isNum(m)) return '—'; const s = Math.round(Number(m) * 60); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
/* Save percentage: 0.9154 -> ".915" (1.000 stays). */
K.svp = v => (isNum(v) ? (Number(v) >= 0.9995 ? '1.000' : Number(v).toFixed(3).replace(/^0/, '')) : '—');
/* Catalogue values by METRIC fmt, matching the shell's RK.fmtVal (toi is seconds, toi_min minutes, svpct ".915").
 * PAYLOADS: probabilities 4 dp, rates per 60 2 dp, fractions 0-1.
 * Formats: int|count|plus|0|1|2|3|pct|pct0|prob|pp|signed|signed1|signed2|signed3|pm|rate|per60|toi|toi_min|mmss|svpct|sv|speed|mph|kmh|ft|sec|min. */
K.fmtV = (v, fmt) => {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt || '')) {
    case 'int': case 'count': case 'plus': return Math.round(x).toLocaleString('en-GB');
    case '0': return x.toFixed(0);
    case '1': case 'speed': return x.toFixed(1);
    case 'mph': return x.toFixed(1) + ' mph';
    case 'kmh': return x.toFixed(1) + ' km/h';
    case 'ft': return x.toFixed(1) + ' ft';
    case '2': case 'per60': case 'rate': case 'p60': return x.toFixed(2);
    case '3': return x.toFixed(3);
    case 'sec': case 's': return x.toFixed(2) + 's';
    case 'min': return Math.round(x).toLocaleString('en-GB');
    // the catalogues' "toi" is minutes (analytics/__init__.fmt_value): per-game times as m:ss, season totals as whole minutes
    case 'toi': return x >= 100 ? Math.round(x).toLocaleString('en-GB') : K.mmss(x);
    case 'toi_sec': return K.mmss(x / 60);
    case 'goals': return Math.abs(x) >= 10 ? x.toFixed(1) : x.toFixed(2);
    case 'toi_min': case 'mmss': return K.mmss(x);
    case 'sv': case 'svp': case 'svpct': case 'save': return K.svp(x);
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'pct0': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(0) + '%';
    case 'prob': return K.pct(x);
    case 'pp': return K.signed(Math.abs(x) <= 1.5 ? x * 100 : x, 1) + ' pp';
    case 'signed1': case 'pm': return K.signed(x, 1);
    case 'signed': case 'signed2': return K.signed(x, 2);
    case 'signed3': return K.signed(x, 3);
    default: return Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) < 1 && x !== 0 ? x.toFixed(3) : x.toFixed(2);
  }
};
K.fmt = (m, v) => K.fmtV(v, (m || {}).fmt);
K.median = a => { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
K.mean = a => { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; };
K.sum = a => a.filter(isNum).map(Number).reduce((x, y) => x + y, 0);
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
  if (h.length !== 6) return 'rgba(88,166,255,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};
K.C = Object.assign({ bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d', text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316', purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8' }, RK.C || {});
K.ACC = (RK.C && (RK.C.rk || RK.C.accent || RK.C.ice)) || '#4fb3d9';
K.PALETTE = RK.PALETTE || ['#4fb3d9', '#f97316', '#3fb950', '#bc8cff', '#f85149', '#d29922', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341', '#39d0d8'];
K.CA = '#e8504f'; K.CB = '#58a6ff';   // compare: side A red, side B blue
K.fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
K.titleCase = s => String(s || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

// ── season, index ──────────────────────────────────────────────────────────

K.ready = () => (K.INDEX ? Promise.resolve(K.INDEX) : RK.load('index.json').then(d => { K.INDEX = d || {}; K.learnIndex(K.INDEX); return K.INDEX; }));
/* A season id: 20262027 (NHL) from 20262027, '2026-27', 2026 (start year) or 2027-only strings are left alone. */
K.sid = v => {
  if (v === null || v === undefined || v === '') return null;
  const s = String(v).trim();
  if (/^\d{8}$/.test(s)) return Number(s);
  let m = /^(\d{4})[-–/](\d{2}|\d{4})$/.exec(s);
  if (m) return Number(m[1]) * 10000 + Number(m[1]) + 1;
  m = /^(\d{4})$/.exec(s);
  if (m) return Number(m[1]) * 10000 + Number(m[1]) + 1;
  return isNum(s) ? Number(s) : null;
};
K.curSeason = () => {
  if (has('currentSeason')) { try { const c = K.sid(RK.currentSeason()); if (isNum(c)) return c; } catch (e) { /* local */ } }
  const x = K.INDEX || {};
  if (K.sid(x.season)) return K.sid(x.season);
  const d = new Date();
  const y = d.getMonth() < 8 ? d.getFullYear() - 1 : d.getFullYear();
  return y * 10000 + y + 1;
};
K.S = (params, state) => {
  const q = (params && params.query) || {};
  const raw = params && (params.season || q.s || q.season || q.y);
  if (K.sid(raw)) return K.sid(raw);
  const st = state || RK.state || {};
  if (K.sid(st.season)) return K.sid(st.season);
  return K.curSeason();
};
/* 20262027 -> "2026–27". */
K.sLabel = S => {
  if (has('seasonLabel')) { try { const r = RK.seasonLabel(S); if (r) return r; } catch (e) { /* local */ } }
  const s = String(K.sid(S) || S || '');
  return /^\d{8}$/.test(s) ? s.slice(0, 4) + '–' + s.slice(6, 8) : s;
};
K.prevS = S => { const s = K.sid(S); return s ? (Math.floor(s / 10000) - 1) * 10000 + Math.floor(s / 10000) : null; };
K.loadY = (S, file) => RK.load(S + '/' + file);
K.sq = S => (isNum(S) && Number(S) !== K.curSeason() ? '?s=' + S : '');
K.withQ = (h, S, extra) => {
  const parts = [];
  if (isNum(S) && Number(S) !== K.curSeason()) parts.push('s=' + S);
  Object.keys(extra || {}).forEach(k => { if (extra[k] !== '' && extra[k] !== null && extra[k] !== undefined) parts.push(enc(k) + '=' + enc(extra[k])); });
  return h + (parts.length ? '?' + parts.join('&') : '');
};

// ── teams (NHL tri-codes) ──────────────────────────────────────────────────

/* Fallback until index.json "teams" loads: [name, conference, division, colour]. Plain hex, no marks. */
const NHL = {
  ANA: ['Anaheim Ducks', 'Western', 'Pacific', '#f47a38'], BOS: ['Boston Bruins', 'Eastern', 'Atlantic', '#fcb514'], BUF: ['Buffalo Sabres', 'Eastern', 'Atlantic', '#003087'],
  CAR: ['Carolina Hurricanes', 'Eastern', 'Metropolitan', '#ce1126'], CBJ: ['Columbus Blue Jackets', 'Eastern', 'Metropolitan', '#002654'], CGY: ['Calgary Flames', 'Western', 'Pacific', '#c8102e'],
  CHI: ['Chicago Blackhawks', 'Western', 'Central', '#cf0a2c'], COL: ['Colorado Avalanche', 'Western', 'Central', '#6f263d'], DAL: ['Dallas Stars', 'Western', 'Central', '#006847'],
  DET: ['Detroit Red Wings', 'Eastern', 'Atlantic', '#ce1126'], EDM: ['Edmonton Oilers', 'Western', 'Pacific', '#ff4c00'], FLA: ['Florida Panthers', 'Eastern', 'Atlantic', '#c8102e'],
  LAK: ['Los Angeles Kings', 'Western', 'Pacific', '#a2aaad'], MIN: ['Minnesota Wild', 'Western', 'Central', '#154734'], MTL: ['Montréal Canadiens', 'Eastern', 'Atlantic', '#af1e2d'],
  NJD: ['New Jersey Devils', 'Eastern', 'Metropolitan', '#ce1126'], NSH: ['Nashville Predators', 'Western', 'Central', '#ffb81c'], NYI: ['New York Islanders', 'Eastern', 'Metropolitan', '#00539b'],
  NYR: ['New York Rangers', 'Eastern', 'Metropolitan', '#0038a8'], OTT: ['Ottawa Senators', 'Eastern', 'Atlantic', '#c52032'], PHI: ['Philadelphia Flyers', 'Eastern', 'Metropolitan', '#f74902'],
  PIT: ['Pittsburgh Penguins', 'Eastern', 'Metropolitan', '#fcb514'], SEA: ['Seattle Kraken', 'Western', 'Pacific', '#99d9d9'], SJS: ['San Jose Sharks', 'Western', 'Pacific', '#006d75'],
  STL: ['St. Louis Blues', 'Western', 'Central', '#002f87'], TBL: ['Tampa Bay Lightning', 'Eastern', 'Atlantic', '#002868'], TOR: ['Toronto Maple Leafs', 'Eastern', 'Atlantic', '#00205b'],
  UTA: ['Utah Mammoth', 'Western', 'Central', '#71afe5'], VAN: ['Vancouver Canucks', 'Western', 'Pacific', '#00205b'], VGK: ['Vegas Golden Knights', 'Western', 'Pacific', '#b4975a'],
  WPG: ['Winnipeg Jets', 'Western', 'Central', '#041e42'], WSH: ['Washington Capitals', 'Eastern', 'Metropolitan', '#c8102e'],
  ARI: ['Arizona Coyotes', 'Western', 'Central', '#8c2633'], PHX: ['Phoenix Coyotes', 'Western', 'Pacific', '#8c2633'], ATL: ['Atlanta Thrashers', 'Eastern', 'Southeast', '#5c88da']
};
K.NHL = NHL;
K.DIVISIONS = ['Atlantic', 'Metropolitan', 'Central', 'Pacific'];
K.NAMES = RK.NAMES || K.NAMES || {};   // pid -> {name, team, pos, first, last}; shared with the shell
K.TEAMS = RK.TEAMS || K.TEAMS || {};   // abbr -> {name, colour, alt, division, conference}; shared with the shell
K.learn = (pid, info) => { if (!pid || !info) return; const o = {}; Object.keys(info).forEach(k => { if (info[k] !== undefined && info[k] !== null && info[k] !== '') o[k] = info[k]; }); K.NAMES[pid] = Object.assign({}, K.NAMES[pid] || {}, o); };
K.learnTeam = (t, info) => {
  if (!t || !info || typeof info !== 'object') return;
  const clean = {};
  ['name', 'abbr', 'short', 'colour', 'color', 'alt', 'division', 'conference', 'conf', 'city', 'arena'].forEach(k => { if (info[k] !== undefined && info[k] !== null && info[k] !== '' && typeof info[k] !== 'object') clean[k] = info[k]; });
  if (clean.color && !clean.colour) clean.colour = clean.color;
  if (clean.conf && !clean.conference) clean.conference = clean.conf;
  if (clean.colour && !/^#/.test(clean.colour)) clean.colour = '#' + clean.colour;
  K.TEAMS[String(t)] = Object.assign({}, K.TEAMS[String(t)] || {}, clean);
};
K.learnIndex = d => { if (d && d.teams && typeof d.teams === 'object' && !Array.isArray(d.teams)) Object.keys(d.teams).forEach(t => K.learnTeam(t, d.teams[t])); };
K.loadNames = () => RK.load('players_index.json').then(d => {
  const m = d && typeof d === 'object' && d.ok !== false ? (d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : d) : null;
  if (m) Object.keys(m).forEach(pid => {
    const r = m[pid];
    if (Array.isArray(r)) { if (!(K.NAMES[pid] || {}).name) K.learn(pid, { name: r[0], team: r[1], pos: r[2], first: r[3], last: r[4] }); }
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
  if (has('playerName')) { try { const n = RK.playerName(pid); if (n && !/^(Player |#)/.test(n) && n !== '—') return n; } catch (e) { /* local */ } }
  return pid ? String(pid) : '—';
};
K.surname = n => { const p = String(n || '').split(' '); if (p.length < 2) return p[0]; const sfx = /^(Jr\.?|Sr\.?|II|III|IV)$/i.test(p[p.length - 1]); return sfx && p.length > 2 ? p[p.length - 2] : p.slice(1).join(' '); };
K.team = t => {
  const x = K.TEAMS[String(t)];
  const fb = NHL[String(t)] ? { name: NHL[t][0], conference: NHL[t][1], division: NHL[t][2], colour: NHL[t][3] } : {};
  if (x) return Object.assign({}, fb, x);
  if (has('teamInfo')) { try { const y = RK.teamInfo(t); if (y && typeof y === 'object' && Object.keys(y).length) return Object.assign({}, fb, y); } catch (e) { /* local */ } }
  return fb;
};
K.teamAbbr = t => (t ? String(t) : '—');
K.teamName = t => (K.team(t).name || K.teamAbbr(t));
K.teamNick = t => { const n = K.teamName(t); const p = n.split(' '); if (p.length < 2) return n; const two = /^(Maple Leafs|Red Wings|Blue Jackets|Golden Knights)$/.test(p.slice(-2).join(' ')); return two ? p.slice(-2).join(' ') : p[p.length - 1]; };
K.lift = hex => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return null;
  let c = [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)], k = 0;
  const lum = x => (0.2126 * x[0] + 0.7152 * x[1] + 0.0722 * x[2]) / 255;
  while (lum(c) < 0.32 && k < 12) { c = c.map(v => Math.round(v + (255 - v) * 0.14)); k++; }
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
};
K.teamColour = t => {
  if (has('teamColour')) { try { const c = RK.teamColour(t); if (c) return c; } catch (e) { /* local */ } }
  return K.lift(K.team(t).colour) || '#6e7681';
};
K.playerHref = (pid, S) => '#/player/' + enc(pid) + K.sq(S);
K.teamHref = (t, S) => '#/team/' + enc(t) + K.sq(S);
K.gameHref = gid => (has('gameHref') ? RK.gameHref(gid) : '#/game/' + enc(gid));
K.compareHref = (a, b) => '#/compare' + (a ? '/' + enc(a) : '') + (b ? '/' + enc(b) : '');
K.playerLink = (pid, label, S) => (pid ? '<a class="ply-link" href="' + K.playerHref(pid, S) + '">' + K.esc(label || K.name(pid)) + '</a>' : '<span class="muted-inline">—</span>');
K.teamChip = (t, S) => (t ? '<a class="gq-team" href="' + K.teamHref(t, S) + '" style="--tc:' + K.teamColour(t) + '" title="' + K.esc(K.teamName(t)) + '">' + K.esc(K.teamAbbr(t)) + '</a>' : '<span class="muted-inline">—</span>');
K.teamLink = (t, S) => (t ? '<a href="' + K.teamHref(t, S) + '">' + K.esc(K.teamName(t)) + '</a>' : '—');
K.gameLink = (gid, label) => (gid ? '<a href="' + K.gameHref(gid) + '">' + K.esc(label || gid) + '</a>' : '—');
/* NHL gameId 2026020009 -> {season: 20262027, type: '02', n: 9}. */
K.parseGid = gid => { const m = /^(\d{4})(\d{2})(\d{4})$/.exec(String(gid || '')); return m ? { season: Number(m[1]) * 10000 + Number(m[1]) + 1, type: m[2], n: Number(m[3]) } : {}; };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
K.fmtDate = (s, o) => {
  if (has('fmtDate')) { try { const r = RK.fmtDate(s, o); if (r && r !== '—') return r; } catch (e) { /* local */ } }
  if (!s) return '—';
  const d = new Date(String(s).length === 10 ? s + 'T12:00:00Z' : s);
  if (isNaN(d.getTime())) return String(s);
  const opt = o || {};
  return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + (opt.year === false ? '' : ' ' + d.getUTCFullYear());
};

// ── positions ──────────────────────────────────────────────────────────────

K.POSG = ['F', 'D'];
K.POSG_NAME = { F: 'Forwards', D: 'Defencemen', G: 'Goaltenders', C: 'Centres', L: 'Left wings', R: 'Right wings' };
K.POS_ONE = { F: 'forward', D: 'defenceman', G: 'goaltender', C: 'centre', L: 'left wing', R: 'right wing' };
/* 'F' | 'D' | 'G' from a position code (C, L, R, LW, RW, F, D, G). */
K.groupOf = pos => {
  const p = String(pos || '').toUpperCase();
  if (p === 'G') return 'G';
  if (p === 'D' || p === 'LD' || p === 'RD') return 'D';
  return p ? 'F' : '';
};
K.posLabel = pos => ({ C: 'C', L: 'LW', R: 'RW', LW: 'LW', RW: 'RW', D: 'D', G: 'G', F: 'F' })[String(pos || '').toUpperCase()] || String(pos || '—');
/* Ice time in minutes from a catalogue row: "toi" in minutes (or seconds when the catalogue is in seconds). */
K.toiScale = P => {
  const vs = Object.keys(P || {}).map(id => (P[id] || {}).toi).filter(isNum);
  return vs.length && Math.max.apply(null, vs) > 6000 ? 1 / 60 : 1;
};
K.toiOf = (p, scale) => (isNum((p || {}).toi) ? Number(p.toi) * (scale || 1) : (isNum(((p || {}).values || {}).toi) ? Number(p.values.toi) * (scale || 1) : 0));
K.gpOf = p => K.first((p || {}).gp, (p || {}).games, ((p || {}).values || {}).gp);
/* Metrics that apply to a position pool (scope 'F' | 'D' | 'skaters' | 'all' | ['F','D']; missing scope: every pool). */
K.scopeOk = (m, group) => {
  const s = m && (m.scope !== undefined ? m.scope : m.groups);
  if (!s || /^(all|\*|skaters?|league|both)$/i.test(String(s))) return true;
  const list = Array.isArray(s) ? s : String(s).split(/[,|/ ]+/);
  return list.some(x => { const u = String(x).toUpperCase(); return u === group || (u === 'FORWARDS' && group === 'F') || (u === 'DEFENCE' && group === 'D') || (u === 'DEFENSE' && group === 'D') || (u === 'GOALIES' && group === 'G'); });
};
K.metricsFor = (cat, group) => {
  const M = (cat || {}).metrics;
  if (M && !Array.isArray(M) && typeof M === 'object') return (M[group] || M.all || []).slice();
  if (!group) return (M || []).slice();
  const P = (cat || {}).players || {};
  const ids = Object.keys(P).filter(id => (P[id].group || K.groupOf(P[id].pos)) === group);
  return (M || []).filter(m => K.scopeOk(m, group) && ids.some(id => isNum(((P[id] || {}).values || {})[m.key])));
};
K.allMetrics = cat => { const M = (cat || {}).metrics; if (M && !Array.isArray(M) && typeof M === 'object') { const out = [], seen = {}; Object.keys(M).forEach(g => (M[g] || []).forEach(m => { if (!seen[m.key]) { seen[m.key] = 1; out.push(m); } })); return out; } return (M || []).slice(); };

// ── HTML furniture ─────────────────────────────────────────────────────────

K.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + K.esc(id) + '"' : '') + '>' +
  (title ? '<div class="card-header">' + K.esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl ? '<span class="gq-ctl">' + ctl + '</span>' : '') + '</div>' : '') + (body || '') + '</div>';
K.tile = (label, value, sub, cls) => '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + K.esc(label) + '</div><div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>';
K.tiles = list => { const l = list.filter(Boolean); return l.length ? '<div class="kpi-grid gq-tiles">' + l.join('') + '</div>' : ''; };
K.toggle = (id, opts, cur) => '<span class="gq-toggle" id="' + K.esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + K.esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' class="on"' : '') + (o[2] ? ' disabled' : '') + '>' + K.esc(o[1]) + '</button>').join('') + '</span>';
K.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    if (b.disabled) return;
    t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fn(b.dataset.v);
  }));
};
K.select = (id, opts, cur, cls) => '<select id="' + K.esc(id) + '"' + (cls ? ' class="' + cls + '"' : '') + '>' + opts.map(o => '<option value="' + K.esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' selected' : '') + '>' + K.esc(o[1]) + '</option>').join('') + '</select>';
K.pctColor = p => {
  if (has('pctColor')) return RK.pctColor(p);
  if (!isNum(p)) return '#30363d';
  const t = Math.max(0, Math.min(100, p)) / 100, lo = [50, 105, 220], mid = [128, 128, 128], hi = [214, 40, 40];
  const a = t < 0.5 ? lo : mid, b = t < 0.5 ? mid : hi, u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return 'rgb(' + [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * u)).join(',') + ')';
};
K.pill = p => (isNum(p) ? '<span class="pct-pill" style="background:' + K.pctColor(p) + '">' + Math.round(p) + '</span>' : '<span class="pct-pill empty">—</span>');
/* Savant-style percentile slider: a track, a coloured disc carrying the percentile, the value on the right. */
K.slider = (label, p, valueText, title, href) => {
  const known = isNum(p), x = known ? Math.max(0, Math.min(100, p)) : 0;
  const lab = href ? '<a href="' + href + '" class="gq-sl-a">' + K.esc(label) + '</a>' : K.esc(label);
  return '<div class="gq-sl"' + (title ? ' title="' + K.esc(title) + '"' : '') + '><span class="gq-sl-label">' + lab + '</span><div class="gq-sl-track">' +
    (known ? '<div class="gq-sl-fill" style="width:' + x + '%;background:' + K.pctColor(p) + '"></div><span class="gq-sl-dot" style="left:' + x + '%;background:' + K.pctColor(p) + '">' + Math.round(p) + '</span>' : '<span class="gq-sl-none">below the sample floor</span>') +
    '</div><span class="gq-sl-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
};
/* Grouped sliders over a catalogue. opts {onlyKnown, note, glossary: true, unit}. The shell's sliders keep one look across the site. */
K.sliders = (metrics, vals, pcts, opts) => {
  const o = opts || {};
  const sh = K.chart('percentileSliders');
  if (sh) {
    try {
      // the shell's RK.fmtVal reads "toi" as seconds; the catalogues write minutes, so hand it toi_min (per game) or whole minutes (totals)
      const ms = (metrics || []).map(m => Object.assign({}, m, m.fmt === 'toi' ? { fmt: isNum((vals || {})[m.key]) && Number(vals[m.key]) >= 100 ? 'int' : 'toi_min' } : {},
        m.fmt === 'goals' ? { fmt: isNum((vals || {})[m.key]) && Math.abs(vals[m.key]) >= 10 ? '1' : '2' } : {}, { desc: K.cleanDesc(m.desc || '') + (isNum(m.stabilises_at) && m.unit ? ' (' + m.unit + ')' : '') }));
      const out = sh(ms, vals || {}, pcts || {}, o);
      if (typeof out === 'string' && out) return out;
    } catch (e) { console.warn('sliders', e); }
  }
  const groups = K.groups(metrics).map(g => ({ name: g.name, items: g.items.filter(m => !o.onlyKnown || isNum((vals || {})[m.key])) })).filter(g => g.items.length);
  if (!groups.length) return K.muted('No metrics in the catalogue yet.');
  return '<div class="gq-sl-cols">' + groups.map(g => '<div class="gq-sl-group"><div class="gq-sl-head">' + K.esc(g.name) + '</div>' +
    g.items.map(m => K.slider(m.label + (m.lower ? ' ↓' : ''), (pcts || {})[m.key], K.fmt(m, (vals || {})[m.key]),
      K.cleanDesc(m.desc || m.label) + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + K.int(m.stabilises_at) + ' ' + (m.unit || 'minutes') : ''),
      o.glossary === false ? null : '#/glossary/' + enc(m.key))).join('') + '</div>').join('') + '</div>' + (o.note ? '<div class="pg-note gq-note">' + o.note + '</div>' : '');
};

/* Tables: the shell's when present (same signature as the Gridiron's GI.tableHTML), else this copy. */
K.table = (cols, rows, opts) => {
  if (has('tableHTML')) return RK.tableHTML(cols, rows, opts);
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
  if (has('sortable')) return RK.sortable(el);
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
  if (has('layout')) return RK.layout(extra);
  const out = Object.assign(JSON.parse(JSON.stringify(DARK)), extra || {});
  Object.keys(extra || {}).forEach(k => { if (/^[xy]axis\d*$/.test(k) && extra[k] && typeof extra[k] === 'object') out[k] = Object.assign({}, DARK.xaxis, extra[k]); });
  if (extra && extra.font) out.font = Object.assign({}, DARK.font, extra.font);
  return out;
};
K.plot = (el, traces, lay, conf) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (has('plot')) return RK.plot(node, traces, lay, conf);
  if (typeof Plotly === 'undefined') { node.innerHTML = K.muted('The chart library did not load. The tables carry the same data.'); return null; }
  try {
    const p = Plotly.newPlot(node, traces, lay, Object.assign({ displayModeBar: false, responsive: true }, conf || {}));
    if (has('onLeave')) RK.onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    return p;
  } catch (err) { node.innerHTML = K.muted('The chart could not be drawn.'); return null; }
};
K.chart = name => (RK.charts && typeof RK.charts[name] === 'function' ? RK.charts[name] : null);
K.narrow = node => ((node && node.clientWidth) || window.innerWidth || 800) < 520;
K.legendTop = () => ({ showlegend: true, legend: { orientation: 'h', y: 1.14, x: 0, font: { color: K.C.text2, size: 10 } } });
K.DIVERGE = [[0, '#2166ac'], [0.25, '#67a9cf'], [0.5, '#2d333b'], [0.75, '#ef8a62'], [1, '#b2182b']];
K.SEQ = [[0, '#161b22'], [0.25, '#1f3b57'], [0.5, '#2f6f9f'], [0.75, '#e08a3c'], [1, '#f85149']];
/* Click a Plotly point -> its customdata hash. */
K.clickThrough = id => { const n = typeof id === 'string' ? document.getElementById(id) : id; if (n && n.on) n.on('plotly_click', ev => { const h = ev.points && ev.points[0] && ev.points[0].customdata; if (h && typeof h === 'string' && h.charAt(0) === '#') location.hash = h; }); };
/* Hide a chart node (and its height) with a muted line instead. */
K.empty = (node, text) => { const n = typeof node === 'string' ? document.getElementById(node) : node; if (!n) return; n.innerHTML = K.muted(text); n.style.height = 'auto'; };

/* Reliability diagram: series [{name, colour, bins: [{lo, hi, n, mean_p|p, freq|obs}] | [[p, obs, n]] | [[mid, mean_p, mean_obs, n]]}]. */
K.reliability = (el, series, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const lo = isNum(o.min) ? o.min : 0, hi = isNum(o.max) ? o.max : 1;
  const tr = [{ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false }];
  series.forEach(s => {
    const bins = K.binsOf(s.bins).filter(b => b.n >= (o.minN || 1) || !b.n);
    if (!bins.length) return;
    const maxN = Math.max.apply(null, bins.map(b => b.n || 1));
    tr.push({ type: 'scatter', mode: 'lines+markers', name: s.name, x: bins.map(b => b.x), y: bins.map(b => b.y), customdata: bins.map(b => b.n),
      marker: { size: bins.map(b => 5 + 13 * Math.sqrt((b.n || 1) / maxN)), color: s.colour }, line: { color: s.colour, width: 1.5, dash: s.dash || 'solid' },
      hovertemplate: K.esc(s.name) + ': forecast %{x:' + (o.fmt || '.1%') + '}, observed %{y:' + (o.fmt || '.1%') + '} (n=%{customdata})<extra></extra>' });
  });
  if (tr.length < 2) { K.empty(node, 'No reliability bins.'); return; }
  K.plot(node, tr, K.layout({ showlegend: true, legend: { orientation: 'h', y: -0.24, font: { color: K.C.text2, size: 10 } }, margin: { l: 55, r: 15, t: 10, b: 84 },
    xaxis: { title: o.xt || 'Forecast', tickformat: o.fmt || '.0%', range: [lo, hi] }, yaxis: { title: o.yt || 'Observed', tickformat: o.fmt || '.0%', range: [lo, hi] } }));
};
K.binsOf = bins => {
  const list = Array.isArray(bins) ? bins : (bins && Array.isArray(bins.bins) ? bins.bins : K.colRows(bins));
  return list.map(b => (Array.isArray(b) ? (b.length >= 4 ? { x: b[1], y: b[2], n: b[3] } : { x: b[0], y: b[1], n: b[2] || 0 }) : { x: [b.mean_p, b.p, b.pred, b.x, b.forecast, b.mean_pred].find(isNum), y: [b.freq, b.obs, b.y, b.observed, b.actual, b.rate, b.mean_obs].find(isNum), n: b.n || b.count || 0 }))
    .filter(b => isNum(b.x) && isNum(b.y));
};

// ── the rink ───────────────────────────────────────────────────────────────

/* NHL coordinates: x −100…100 ft (goal lines at ±89, blue lines at ±25), y −42.5…42.5 ft; shots are normalised
 * so the shooting team attacks +x. Plotly shapes for the half rink (x 0…100) or the full rink. */
K.rinkShapes = full => {
  const line = (c, w) => ({ color: c, width: w || 1.2 });
  const S = [];
  const x0 = full ? -100 : 0;
  // boards with rounded corners (radius 28)
  const r = 28;
  const path = full
    ? 'M -72,-42.5 L 72,-42.5 Q 100,-42.5 100,-14.5 L 100,14.5 Q 100,42.5 72,42.5 L -72,42.5 Q -100,42.5 -100,14.5 L -100,-14.5 Q -100,-42.5 -72,-42.5 Z'
    : 'M 0,-42.5 L ' + (100 - r) + ',-42.5 Q 100,-42.5 100,' + (-42.5 + r) + ' L 100,' + (42.5 - r) + ' Q 100,42.5 ' + (100 - r) + ',42.5 L 0,42.5 Z';
  S.push({ type: 'path', path: path, line: line('#8b949e', 1.5), layer: 'below' });
  const sides = full ? [1, -1] : [1];
  S.push({ type: 'line', x0: 0, x1: 0, y0: -42.5, y1: 42.5, line: { color: 'rgba(248,81,73,0.55)', width: 2 }, layer: 'below' });
  sides.forEach(sg => {
    S.push({ type: 'line', x0: sg * 25, x1: sg * 25, y0: -42.5, y1: 42.5, line: { color: 'rgba(88,166,255,0.6)', width: 3 }, layer: 'below' });
    S.push({ type: 'line', x0: sg * 89, x1: sg * 89, y0: -37.2, y1: 37.2, line: { color: 'rgba(248,81,73,0.55)', width: 1.2 }, layer: 'below' });
    // crease (radius 6, opening toward centre ice) and the net
    S.push({ type: 'path', path: 'M ' + (sg * 89) + ',-4 L ' + (sg * 84.5) + ',-4 Q ' + (sg * 83) + ',0 ' + (sg * 84.5) + ',4 L ' + (sg * 89) + ',4 Z', fillcolor: 'rgba(88,166,255,0.18)', line: { color: 'rgba(248,81,73,0.55)', width: 1 }, layer: 'below' });
    S.push({ type: 'rect', x0: sg > 0 ? 89 : -92.3, x1: sg > 0 ? 92.3 : -89, y0: -3, y1: 3, line: { color: '#c9d1d9', width: 1 }, layer: 'below' });
    [22, -22].forEach(y => {
      S.push({ type: 'circle', x0: sg * 69 - 15, x1: sg * 69 + 15, y0: y - 15, y1: y + 15, line: { color: 'rgba(248,81,73,0.45)', width: 1 }, layer: 'below' });
      S.push({ type: 'circle', x0: sg * 69 - 1, x1: sg * 69 + 1, y0: y - 1, y1: y + 1, fillcolor: 'rgba(248,81,73,0.6)', line: { width: 0 }, layer: 'below' });
      S.push({ type: 'circle', x0: sg * 20 - 1, x1: sg * 20 + 1, y0: y - 1, y1: y + 1, fillcolor: 'rgba(248,81,73,0.6)', line: { width: 0 }, layer: 'below' });
    });
  });
  S.push({ type: 'circle', x0: -15, x1: 15, y0: -15, y1: 15, line: { color: 'rgba(88,166,255,0.45)', width: 1 }, layer: 'below' });
  if (!full) S.forEach(s => { if (s.x0 !== undefined && s.x0 < x0 && s.type !== 'circle') s.x0 = x0; });
  return S;
};
/* Axes for a rink plot. */
K.rinkAxes = full => ({
  xaxis: { range: full ? [-101, 101] : [-1, 101], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, constrain: 'domain' },
  yaxis: { range: [-43.5, 43.5], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1 }
});
/* Shot points from any shape: {cols, rows} | [{x, y, xg, goal, shot_type, ...}] | [[x, y, xg, goal, type]] (already normalised to attack +x). */
K.shotsOf = (raw, colsHint) => {
  let rows = [];
  if (Array.isArray(raw) && raw.length && Array.isArray(raw[0])) {
    const c = colsHint || ['x', 'y', 'xg', 'goal', 'shot_type'];
    rows = raw.map(r => { const o = {}; c.forEach((k, i) => { o[k] = r[i]; }); return o; });
  } else rows = K.listOf(raw);
  return rows.map(r => {
    const x = K.first(r.x, r.x_coord, r.xc), y = K.first(r.y, r.y_coord, r.yc);
    if (!isNum(x) || !isNum(y)) return null;
    const g = r.goal === true || r.goal === 1 || r.is_goal === 1 || r.is_goal === true || /^goal$/i.test(String(r.type || r.event || r.result || ''));
    return { x: x, y: y, xg: K.first(r.xg, r.xG, r.x_goal), goal: g, type: r.shot_type || r.type_shot || r.kind || '', strength: r.strength || '', period: r.period, game_id: r.game_id, date: r.date, opp: r.opp, sec: r.sec, raw: r };
  }).filter(Boolean);
};
/* Half-rink shot map: xG-sized dots, goals filled. opts {colour, title, height, legend}. */
K.shotMap = (el, shots, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const sh = K.chart('shotMap');
  if (sh && o.shell !== false) {
    // the shell's map: its own strength / period filters and a shots-goals-xG line below it
    const rows = shots.map(s => Object.assign({}, s.raw || s, { x: s.x, y: s.y, xg: s.xg, goal: s.goal, team: (s.raw || s).team || o.team || null, shot_type: (s.raw || s).shot_type || s.type || '', type: (s.raw || {}).type || (s.goal ? 'goal' : 'shot-on-goal') }));
    try { sh(node, rows, { filters: o.filters !== false, emptyText: o.empty || 'No shots on file.', colours: o.team && o.colour ? { [o.team]: o.colour } : undefined, height: o.height }); return; } catch (e) { console.warn('shotMap', e); }
  }
  if (!shots.length) { K.empty(node, o.empty || 'No shots on file.'); return; }
  const col = o.colour || K.ACC;
  const sz = s => 5 + 26 * Math.sqrt(Math.min(0.6, isNum(s.xg) ? s.xg : 0.05));
  const hov = s => (s.goal ? '<b>Goal</b>' : 'Shot') + (s.type ? ' · ' + K.esc(K.titleCase(s.type)) : '') + (isNum(s.xg) ? '<br>xG ' + K.num(s.xg, 2) : '') + (s.strength ? ' · ' + K.esc(s.strength) : '') + (s.opp ? '<br>v ' + K.esc(s.opp) : '') + (s.date ? ' · ' + K.esc(s.date) : '');
  const miss = shots.filter(s => !s.goal), goals = shots.filter(s => s.goal);
  const tr = [
    { type: 'scatter', mode: 'markers', name: 'Shots and misses', x: miss.map(s => s.x), y: miss.map(s => s.y), text: miss.map(hov), hovertemplate: '%{text}<extra></extra>', marker: { size: miss.map(sz), color: 'rgba(0,0,0,0)', line: { color: K.alpha(col, 0.75), width: 1.2 } } },
    { type: 'scatter', mode: 'markers', name: 'Goals', x: goals.map(s => s.x), y: goals.map(s => s.y), text: goals.map(hov), hovertemplate: '%{text}<extra></extra>', marker: { size: goals.map(sz), color: col, opacity: 0.95, line: { color: '#0d1117', width: 1 } } }
  ];
  K.plot(node, tr, K.layout(Object.assign({ margin: { l: 4, r: 4, t: o.title ? 26 : 6, b: 4 }, shapes: K.rinkShapes(false), title: o.title ? { text: o.title, font: { size: 11, color: K.C.text2 }, x: 0.02 } : undefined, showlegend: o.legend !== false, legend: { orientation: 'h', y: -0.02, font: { size: 10, color: K.C.text2 } } }, K.rinkAxes(false))));
};
/* A grid over the half rink from any shape: {x: [centres], y: [centres], z|v|rate|player: [[row y][col x]], league?: [[...]], diff?: [[...]]}
 * or cells [{x, y, v|rate|n, league}] -> {xs, ys, z, league, diff}. */
/* A grid in the payloads' compact form ({x0, dx, nx, y0, dy, ny} and a flat row-major layer) -> {x: [centres], y: [centres], v: [[y][x]]}. */
K.flatGrid = (spec, arr) => {
  if (!spec || !Array.isArray(arr) || !isNum(spec.nx) || !isNum(spec.ny) || arr.length < spec.nx * spec.ny) return null;
  const xs = [], ys = [], v = [];
  for (let i = 0; i < spec.nx; i++) xs.push(spec.x0 + spec.dx * (i + 0.5));
  for (let j = 0; j < spec.ny; j++) { ys.push(spec.y0 + spec.dy * (j + 0.5)); v.push(arr.slice(j * spec.nx, (j + 1) * spec.nx).map(x => (isNum(x) ? Number(x) : null))); }
  return { x: xs, y: ys, v: v };
};
/* A matrix smoothed with a 3x3 binomial kernel (counts on a 5 ft grid are spiky). */
K.smooth = v => {
  const W = [[1, 2, 1], [2, 4, 2], [1, 2, 1]];
  return v.map((row, j) => row.map((_, i) => { let s0 = 0, w0 = 0; for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) { const r = v[j + a]; if (!r || !isNum(r[i + b])) continue; s0 += W[a + 1][b + 1] * r[i + b]; w0 += W[a + 1][b + 1]; } return w0 ? s0 / w0 : null; }));
};
K.gridOf = g => {
  if (!g || typeof g !== 'object') return null;
  const isM = v => Array.isArray(v) && v.length && v.every(r => Array.isArray(r));
  const xs = g.x || g.xs || g.x_centres || g.x_centers || g.xbins, ys = g.y || g.ys || g.y_centres || g.y_centers || g.ybins;
  const z = [g.z, g.v, g.rate, g.player, g.team, g.for, g.values, g.n].find(isM);
  if (Array.isArray(xs) && Array.isArray(ys) && z) {
    const lg = [g.league, g.lg, g.base].find(isM) || null;
    let diff = [g.diff, g.delta, g.rel, g.vs_league].find(isM) || null;
    if (!diff && lg) diff = z.map((r, i) => r.map((v, j) => (isNum(v) && isNum((lg[i] || [])[j]) ? v - lg[i][j] : null)));
    return { xs: xs.map(Number), ys: ys.map(Number), z: z, league: lg, diff: diff, unit: g.unit || g.units || '', norm: g.norm || g.per || '' };
  }
  const cells = K.listOf(g.cells || g.hex || g.zones || g);
  if (!cells.length || !isNum(cells[0].x)) return null;
  const X = Array.from(new Set(cells.map(c => Number(c.x)))).sort((a, b) => a - b), Y = Array.from(new Set(cells.map(c => Number(c.y)))).sort((a, b) => a - b);
  const at = (arr, key) => Y.map(y => X.map(x => { const c = cells.find(q => Number(q.x) === x && Number(q.y) === y); return c ? K.first(c[key]) : null; }));
  const vk = ['rate', 'v', 'value', 'per60', 'n', 'shots'].find(k => cells.some(c => isNum(c[k])));
  const zz = at(cells, vk), lg = cells.some(c => isNum(c.league)) ? at(cells, 'league') : null;
  const df = cells.some(c => isNum(c.diff)) ? at(cells, 'diff') : (lg ? zz.map((r, i) => r.map((v, j) => (isNum(v) && isNum(lg[i][j]) ? v - lg[i][j] : null))) : null);
  return { xs: X, ys: Y, z: zz, league: lg, diff: df, unit: g.unit || '', norm: g.norm || '' };
};
/* Heatmap over the half rink. mode 'diff' (against the league, diverging) or 'raw' (sequential). opts {title, height, label}. */
K.shotHeatmap = (el, grid, mode, opts) => {
  const o = opts || {};
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const G = K.gridOf(grid);
  const sh = K.chart('shotHeatmap');
  if (sh && o.shell !== false && grid) {
    // the shell's heatmap: matrices {x, y, v, league}, hexes or zones; we hand it a normalised matrix when we can read one
    const native = Array.isArray(grid) || Array.isArray(grid.hex) || Array.isArray(grid.hexes) || Array.isArray(grid.zones);
    let g2 = grid, vs = mode === 'diff', rel = !!o.rel;
    if (!native && G) {
      if (mode === 'diff' && !G.league && G.diff) { g2 = { x: G.xs, y: G.ys, v: G.diff }; vs = false; rel = true; }
      else g2 = { x: G.xs, y: G.ys, v: G.z, league: G.league || undefined };
      if (mode === 'diff' && !G.league && !G.diff) { vs = false; rel = !!o.rel; }
    }
    try { sh(node, g2, { vsLeague: vs, rel: rel, invert: !!o.invert, label: o.label || '', title: o.title || '', fmt: o.fmt, scale: mode === 'raw' ? 'seq' : undefined, emptyText: o.empty || 'No shot-location data.' }); return; } catch (e) { console.warn('shotHeatmap', e); }
  }
  if (!G) { K.empty(node, o.empty || 'No shot grid on file.'); return; }
  const z = mode === 'diff' && G.diff ? G.diff : G.z;
  const flat = [].concat.apply([], z).filter(isNum);
  if (!flat.length) { K.empty(node, 'No shots in this view.'); return; }
  const div = mode === 'diff' && !!G.diff;
  const m = div ? Math.max.apply(null, flat.map(Math.abs)) || 1 : Math.max.apply(null, flat) || 1;
  const lab = o.label || (div ? 'Against the league' : 'Rate');
  K.plot(node, [{ type: 'heatmap', x: G.xs, y: G.ys, z: z, zmin: div ? -m : 0, zmax: m, zsmooth: 'best', colorscale: div ? K.DIVERGE : [[0, 'rgba(22,27,34,0)'], [0.25, '#1f3b57'], [0.6, '#2f6f9f'], [0.85, '#e08a3c'], [1, '#f85149']],
    showscale: !K.narrow(node), colorbar: { thickness: 8, len: 0.8, tickfont: { size: 9, color: K.C.text2 }, title: { text: lab, side: 'right', font: { size: 10 } } },
    hovertemplate: 'x %{x:.0f} ft, y %{y:.0f} ft<br>' + K.esc(lab) + ' %{z:.3f}<extra></extra>', opacity: 0.85 }],
  K.layout(Object.assign({ margin: { l: 4, r: 4, t: o.title ? 26 : 6, b: 4 }, shapes: K.rinkShapes(false), title: o.title ? { text: o.title, font: { size: 11, color: K.C.text2 }, x: 0.02 } : undefined }, K.rinkAxes(false))));
};

// ── catalogue helpers ──────────────────────────────────────────────────────

/* {cols|fields|columns, rows} (the contract's compact frames) or an array of objects -> [{...}]. */
K.colRows = x => {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  const cols = x.cols || x.fields || x.columns, rows = x.rows || x.data;
  if (!Array.isArray(cols) || !Array.isArray(rows)) return [];
  return rows.map(r => { if (!Array.isArray(r)) return r; const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
};
/* A list of objects, a {cols, rows} frame, or a {key: {...}} dict -> [{...}] (dict keys land in `idKey`). */
K.listOf = (x, idKey) => {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  if ((x.cols || x.fields || x.columns) && (x.rows || x.data)) return K.colRows(x);
  if (typeof x === 'object') return Object.keys(x).filter(k => x[k] && typeof x[k] === 'object' && !Array.isArray(x[k])).map(k => { const o = {}; o[idKey || 'id'] = k; return Object.assign(o, x[k]); });
  return [];
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
K.first = function () { for (let i = 0; i < arguments.length; i++) if (isNum(arguments[i])) return Number(arguments[i]); return null; };
/* Up to n metrics: the preferred candidates in order, then one per family, then the rest. */
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
K.shortLabel = s => String(s || '').replace(/percentage/i, '%').replace(/ per 60/i, '/60').replace(/ above expected/i, ' AX').replace(/ over expected/i, ' OE').replace(/^Expected /, 'x').replace(/^Individual /, 'i').slice(0, 24);
K.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + enc(key) + '" title="Glossary: ' + K.esc(key) + '">' + text + '</a>';
/* Published descriptions never carry build-internal wording ("builder B's xg model ..."). */
K.cleanDesc = t => String(t || '').replace(/\(?builder [A-Z]'s ([a-z_ ]+?) model; /gi, '(').replace(/\s*\(builder [A-Z]\)/gi, '').replace(/^Builder [A-Z]: /, '').replace(/([.;] )Builder [A-Z]: /g, '$1')
  .replace(/Builder [A-Z]'s /g, 'Our ').replace(/builder [A-Z]'s /g, 'our ').replace(/\bbuilder [A-Z]\b/gi, 'the build').replace(/\s+\(\)/g, '').replace(/team_strength/g, 'team-strength model');
K.cleanMetrics = list => { (Array.isArray(list) ? list : []).forEach(m => { if (m && m.desc && !m._c) { m.desc = K.cleanDesc(m.desc); m._c = 1; } }); return list; };
/* Catalogue payload -> {metrics, players, ...}; tolerates a wrapper {"ok", "players": {...}} or {"catalogue": {...}}. */
K.catOf = d => {
  if (!d || d.ok === false) return null;
  if (Array.isArray(d.metrics)) K.cleanMetrics(d.metrics);
  if (d.players && d.metrics) return d;
  const inner = d.catalogue || d.data;
  if (inner && inner.players) return Object.assign({}, d, inner);
  return d.players ? Object.assign({ metrics: [] }, d) : null;
};
/* Headline metrics (exact keys first, then patterns). */
K.PREFS = {
  F: ['gar', 'value', 'war', /^(rink_)?value/, 'p60', 'pts60', /^p(ts|oints)_?(per_?)?60/, 'ixg60', /^i?xg_?(per_?)?60|ixg/, 'g60', /^goals?_?(per_?)?60/, 'xgf_pct', /xgf_?pct|xgf%/, 'rapm_off', /rapm.*off|off.*rapm/, 'rapm_def', /rapm.*def|def.*rapm/, 'gax', /goals?_above|gax/],
  D: ['gar', 'value', 'war', /^(rink_)?value/, 'toi_gp', 'xgf_pct', /xgf_?pct/, 'rapm_def', /rapm.*def|def.*rapm/, 'rapm_off', /rapm.*off|off.*rapm/, 'xga60', /xga_?(per_?)?60/, 'p60', 'pts60', /^p(ts|oints)_?(per_?)?60/, /toi.*(gp|game|pg)/],
  G: ['gsax', /^gsax$/, 'gsax60', /gsax.*60/, 'sv_pct', /^sv_?pct$|save_pct/, 'gsax_high', /gsax.*high|hd_gsax/, 'dfsv_pct', 'qs_pct', /quality/, 'sa', 'shots_faced', /shots?_faced|^sa$/, 'gar']
};

// ── player picker (typeahead over players_index.json and the catalogues) ───

/* host: element; opts {value, label, placeholder, onPick(id), filter(id, info), extra: {id: {name, pos, team}}, only}. */
K.picker = (host, opts) => {
  const o = opts || {};
  host.classList.add('gq-picker');
  host.innerHTML = '<input type="search" class="gq-search" autocomplete="off" spellcheck="false" placeholder="' + K.esc(o.placeholder || 'Type a player…') + '"><div class="gq-pick-list"></div>';
  const input = host.querySelector('input'), list = host.querySelector('.gq-pick-list');
  if (o.value) input.value = o.label || K.name(o.value);
  let items = null;
  const build = () => {
    const N = o.only ? Object.assign({}, o.extra || {}) : Object.assign({}, K.NAMES, o.extra || {});
    items = Object.keys(N).filter(id => !o.filter || o.filter(id, N[id])).map(id => ({ id: id, n: N[id].name || id, s: [N[id].pos, N[id].team ? K.teamAbbr(N[id].team) : '', N[id].sub || ''].filter(Boolean).join(' · '), f: K.fold((N[id].name || id) + ' ' + (N[id].team || '')) }));
    items.sort((a, b) => a.n.localeCompare(b.n));
  };
  const close = () => { list.innerHTML = ''; list.style.display = 'none'; };
  const show = () => {
    if (!items) build();
    const q = K.fold(input.value.trim());
    if (q.length < (o.min === undefined ? 2 : o.min)) { close(); return; }
    const words = q.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.f.indexOf(w) >= 0)).slice(0, 12);
    list.innerHTML = hits.length ? hits.map(h => '<button type="button" data-id="' + K.esc(h.id) + '"><span>' + K.esc(h.n) + '</span><span class="gq-pick-sub">' + K.esc(h.s) + '</span></button>').join('') : '<div class="gq-pick-none">No match.</div>';
    list.style.display = 'block';
  };
  input.addEventListener('input', show);
  input.addEventListener('focus', () => { input.select(); if (o.min === 0) show(); });
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
  if (has('onLeave')) RK.onLeave(() => document.removeEventListener('click', outside));
  return { input: input, refresh: () => { items = null; } };
};

/* Register a page under a route name and its pattern(s); the shell's RK.route accepts either. */
K.route = (names, fn) => {
  if (typeof RK.route !== 'function') return;
  (Array.isArray(names) ? names : [names]).forEach(n => { try { RK.route(n, fn); } catch (e) { console.warn('route failed', n, e); } });
};
/* A page header in the house style. */
K.head = (title, sub, right, badge, colour) => '<div class="gq-head"' + (colour ? ' style="--tc:' + colour + '"' : '') + '>' + (badge ? '<div class="gq-badge">' + badge + '</div>' : '') +
  '<div class="gq-head-body"><h2>' + title + '</h2>' + (sub ? '<div class="gq-head-sub">' + sub + '</div>' : '') + '</div>' + (right ? '<div class="gq-head-links">' + right + '</div>' : '') + '</div>';
K.setMeta = html => { if (has('setMeta')) { try { RK.setMeta(html); } catch (e) { /* optional */ } } };
K.$ = id => document.getElementById(id);
K.set = (id, html) => { const e = document.getElementById(id); if (e) e.innerHTML = html; return e; };

// ════════════════════════════════════════════════════════════════════════════
// The skater catalogue (#/skaters)
// ════════════════════════════════════════════════════════════════════════════

const ST = { group: 'F', pos: '', q: '', team: '', floor: null, basis: 'pct_pos', qual: true, extra: [], season: null, sortKey: null, rate: 'all' };

function renderSkaters(el, params, state) {
  const k = K;
  const qy = (params && params.query) || {};
  const qp = String(qy.p || qy.g || '').toUpperCase();
  if (qp === 'F' || qp === 'D') { ST.group = qp; ST.pos = ''; }
  if (/^(C|L|R)$/.test(qp)) { ST.group = 'F'; ST.pos = qp; }
  el.innerHTML = '<div class="card"><div class="card-header">Skaters <span class="card-sub" id="cat-sub">Loading…</span><span class="gq-ctl">' +
    k.toggle('cat-group', [['F', 'Forwards'], ['D', 'Defence'], ['A', 'All']], ST.group) + '</span></div>' +
    '<div class="lab-controls gq-controls">' +
    '<label>Search<input id="cat-q" class="gq-search" type="search" placeholder="name or team…"></label>' +
    '<label>Team<select id="cat-team"><option value="">All teams</option></select></label>' +
    '<label>Position<select id="cat-pos"><option value="">All</option></select></label>' +
    '<label><span>Min TOI <span id="cat-floor-v"></span> min</span><input id="cat-floor" type="range" min="0" max="2000" step="10"></label>' +
    '<label>Percentiles<select id="cat-basis"><option value="pct_pos">against the position pool</option><option value="pct">against the league</option></select></label>' +
    '<label>Add any metric<select id="cat-extra" class="gq-wide"><option value="">—</option></select></label>' +
    '<label class="inline"><input id="cat-qual" type="checkbox"> qualified only</label>' +
    '<label>&nbsp;<button type="button" id="cat-clear" class="gq-btn">Clear added</button></label>' +
    '</div><div id="cat-chips" class="gq-chips"></div><div id="cat-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="cat-note"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'skaters.json'), k.loadNames()]).then(res => ({ S: S, raw: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = k.catOf(o.raw), $ = k.$;
    if (!cat) { $('cat-table').innerHTML = k.notBuilt('The ' + k.sLabel(S) + ' skater catalogue', o.raw); $('cat-sub').textContent = ''; return; }
    k.learnCat(cat);
    if (ST.season !== S) { ST.season = S; ST.floor = null; ST.team = ''; }
    const P = cat.players;
    const scale = k.toiScale(P);
    const byGroup = { F: [], D: [], A: [] };
    Object.keys(P).forEach(id => { const g = (P[id].group || k.groupOf(P[id].pos)); if (g === 'G') return; (byGroup[g] = byGroup[g] || []).push(id); byGroup.A.push(id); });
    $('cat-group').querySelectorAll('button').forEach(b => { b.disabled = !(byGroup[b.dataset.v] || []).length; b.title = (byGroup[b.dataset.v] || []).length + ' skaters'; });
    if (!(byGroup[ST.group] || []).length) ST.group = byGroup.F.length ? 'F' : 'A';
    $('cat-group').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === ST.group));
    const setup = () => {
      const g = ST.group, ids = byGroup[g] || [];
      const metrics = g === 'A' ? k.allMetrics(cat).filter(m => k.scopeOk(m, 'F') && k.scopeOk(m, 'D')) : k.metricsFor(cat, g);
      const meta = k.metaOf(k.allMetrics(cat));
      const maxN = Math.max.apply(null, ids.map(id => k.toiOf(P[id], scale)).concat([60]));
      const floorDef = [((cat.floors || {})[g]), cat.toi_floor, cat.floor].find(isNum);
      $('cat-floor').max = String(Math.ceil(maxN / 10) * 10);
      if (ST.floor === null || ST.floor > maxN) ST.floor = isNum(floorDef) ? Math.min(floorDef * (floorDef > 6000 ? 1 / 60 : 1), maxN) : 0;
      $('cat-floor').value = ST.floor; $('cat-floor-v').textContent = k.int(ST.floor);
      const teams = {};
      ids.forEach(id => { const t = P[id].team; if (t) teams[t] = 1; });
      $('cat-team').innerHTML = '<option value="">All teams</option>' + Object.keys(teams).sort().map(t => '<option value="' + k.esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + k.esc(t + ' · ' + k.teamName(t)) + '</option>').join('');
      const pos = {};
      ids.forEach(id => { const x = P[id].pos; if (x) pos[x] = (pos[x] || 0) + 1; });
      if (ST.pos && !pos[ST.pos]) ST.pos = '';
      $('cat-pos').innerHTML = '<option value="">All</option>' + Object.keys(pos).sort().map(x => '<option value="' + k.esc(x) + '"' + (x === ST.pos ? ' selected' : '') + '>' + k.esc(k.posLabel(x)) + ' (' + pos[x] + ')</option>').join('');
      $('cat-pos').parentNode.style.display = Object.keys(pos).length > 1 ? '' : 'none';
      $('cat-extra').innerHTML = '<option value="">—</option>' + k.groups(metrics).map(gr => '<optgroup label="' + k.esc(gr.name) + '">' + gr.items.map(m => '<option value="' + k.esc(m.key) + '">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      ST.extra = ST.extra.filter(x => meta[x]);
      const heads = k.headline(metrics, k.PREFS[g === 'D' ? 'D' : 'F'] || [], 7);
      if (ST.sortKey && !meta[ST.sortKey]) ST.sortKey = null;
      return { g: g, ids: ids, metrics: metrics, meta: meta, heads: heads, scale: scale };
    };
    let ctx = setup();
    const draw = () => drawCatalogue(S, cat, ctx);
    $('cat-q').value = ST.q; $('cat-basis').value = ST.basis; $('cat-qual').checked = ST.qual;
    let t = null;
    $('cat-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    $('cat-team').onchange = e => { ST.team = e.target.value; draw(); };
    $('cat-pos').onchange = e => { ST.pos = e.target.value; draw(); };
    $('cat-basis').onchange = e => { ST.basis = e.target.value; draw(); };
    $('cat-qual').onchange = e => { ST.qual = e.target.checked; draw(); };
    $('cat-floor').oninput = e => { ST.floor = Number(e.target.value); $('cat-floor-v').textContent = k.int(ST.floor); };
    $('cat-floor').onchange = draw;
    $('cat-extra').onchange = e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0 && ctx.heads.every(m => m.key !== x)) ST.extra.push(x); e.target.value = ''; draw(); };
    $('cat-clear').onclick = () => { ST.extra = []; draw(); };
    $('cat-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (!b) return; ST.extra = ST.extra.filter(x => x !== b.dataset.rm); draw(); };
    k.wireToggle(el, 'cat-group', v => { ST.group = v; ST.pos = ''; ST.floor = null; ST.team = ''; ST.sortKey = null; ctx = setup(); draw(); try { history.replaceState(null, '', k.withQ('#/skaters', S, { p: v === 'A' ? '' : v })); } catch (e) { /* ok */ } });
    draw();
  });
}

function drawCatalogue(S, cat, ctx) {
  const k = K;
  const P = cat.players, g = ctx.g;
  const q = k.fold(ST.q.trim());
  const extras = ST.extra.map(x => ctx.meta[x]).filter(Boolean);
  const cols = ctx.heads.concat(extras.filter(m => ctx.heads.indexOf(m) < 0));
  const ids = ctx.ids.filter(id => {
    const p = P[id];
    if (k.toiOf(p, ctx.scale) < ST.floor) return false;
    if (ST.qual && p.qualified === false) return false;
    if (ST.team && String(p.team) !== ST.team) return false;
    if (ST.pos && p.pos !== ST.pos) return false;
    if (q && k.fold(String(p.name || k.name(id)) + ' ' + (p.team || '') + ' ' + k.teamName(p.team)).indexOf(q) < 0) return false;
    return true;
  });
  const sm = ctx.meta[ST.sortKey] || ctx.heads[0] || {};
  const sortKey = sm.key, sortLower = !!sm.lower;
  ids.sort((a, b) => {
    const qa = P[a].qualified === false ? 1 : 0, qb = P[b].qualified === false ? 1 : 0;
    if (qa !== qb) return qa - qb;
    const va = (P[a].values || {})[sortKey], vb = (P[b].values || {})[sortKey];
    const d = (isNum(vb) ? vb : -1e9) - (isNum(va) ? va : -1e9);
    return (sortLower ? -d : d) || k.toiOf(P[b], ctx.scale) - k.toiOf(P[a], ctx.scale);
  });
  const src = p => (ST.basis === 'pct_pos' ? (p.pct_pos || p.pct || {}) : (p.pct || {}));
  const rows = ids.slice(0, 600).map((id, i) => {
    const p = P[id];
    const gp = k.gpOf(p), toi = k.toiOf(p, ctx.scale);
    return { _href: k.playerHref(id, S), cells: [
      { v: i + 1, cls: 'pos-cell' },
      { v: p.name || k.name(id), html: '<a class="ply-link" href="' + k.playerHref(id, S) + '">' + k.esc(p.name || k.name(id)) + '</a>' + (p.qualified === false ? ' <span class="gq-tag" title="Below the ice-time floor: percentiles are not published">small sample</span>' : '') },
      { v: p.team || '', html: k.teamChip(p.team, S) },
      { v: p.pos || '', html: k.esc(k.posLabel(p.pos)) },
      { v: p.age, html: isNum(p.age) ? k.num(p.age, 0) : '—', align: 'right' },
      { v: gp, html: k.int(gp), align: 'right' },
      { v: toi, html: k.int(toi), align: 'right', title: isNum(gp) && gp > 0 ? k.mmss(toi / gp) + ' a game' : '' }
    ].concat(cols.map(m => {
      const v = (p.values || {})[m.key], pc = src(p)[m.key];
      return { v: isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gq-val">' + k.fmt(m, v) + '</span> ' + k.pill(pc), align: 'right' };
    })) };
  });
  const host = k.$('cat-table');
  if (!host) return;
  const head = [{ label: '#', sortable: false }, { label: 'Skater' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'GP', align: 'right' }, { label: 'TOI', align: 'right', title: 'Total ice time, minutes (all strengths)' }]
    .concat(cols.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: k.cleanDesc(m.desc || m.label) + (m.lower ? ' (lower is better)' : '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + k.int(m.stabilises_at) + ' ' + (m.unit || 'minutes') : '') })));
  host.innerHTML = rows.length ? k.table(head, rows, { sticky: true, compact: true }) : k.muted('No skater matches these filters.');
  k.sortable(host);
  const chips = k.$('cat-chips');
  if (chips) chips.innerHTML = extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + k.esc(m.key) + '" title="Remove">' + k.esc(m.label) + ' ×</button>').join(' ') : '';
  const noun = { F: 'forwards', D: 'defencemen', A: 'skaters' }[g];
  k.set('cat-sub', ids.length + ' of ' + ctx.ids.length + ' ' + noun + (ids.length > 600 ? ' (first 600 shown)' : '') + ' · ' + k.sLabel(S) + ' · sorted by ' + k.esc(sm.label || 'ice time') + '; click a header to sort, a row for the player');
  const stab = cols.filter(m => isNum(m.stabilises_at));
  k.set('cat-note', k.sLabel(S) + (cat.updated_at ? ', updated ' + k.esc(k.fmtDate(cat.updated_at, { year: false })) : '') + '. Pills are percentiles (100 = best; ↓ metrics are flipped so red is always good) against every qualified ' +
    (ST.basis === 'pct_pos' ? 'skater in the same position pool (forwards or defencemen)' : 'skater in the league') + '. Skaters below the ice-time floor show raw values only; counting stats, RAPM and Rink value need ' +
    (isNum(((cat.reference || {}).floors || {}).gp) ? k.int(cat.reference.floors.gp) : 5) + ' games before they get a percentile (early in the season most cells are values only), and every rate is shrunk towards the pool mean by its stabilisation point before ranking' +
    (stab.length ? ' (' + stab.slice(0, 4).map(m => k.esc(m.label) + ' about ' + k.int(m.stabilises_at) + ' ' + k.esc(m.unit || 'minutes')).join(', ') + ')' : '') + '. ' +
    'Headline columns: ' + ctx.heads.map(m => k.glossLink(m.key, k.esc(m.label))).join(' · ') + '. All ' + ctx.metrics.length + ' metrics are on every player page, the <a href="' + k.withQ('#/leaders', S) + '">leaders</a> page and in the <a href="' + k.withQ('#/lab', S) + '">lab</a>. ' +
    'On-ice rates are per 60 minutes at 5-on-5 unless the label says otherwise; RAPM isolates a skater from his linemates, opponents, zone starts and score (see the <a href="#/methodology/rapm">methodology</a>).');
}

K.route(['skaters', '#/skaters'], renderSkaters);
})(window.RK || (window.RK = {}));
