/* The Quant Gridiron — builder F's shared kit (GI.fk) and the player catalogue (#/players).
 *
 * GI.fk is defined here and read lazily at render time by every other page of builder F
 * (player, teams, fourth, coaches, leaders, history, lab, compare, calibration, docs:
 * const K = () => GI.fk), so script order does not matter as long as this file is loaded. It leans
 * on the shell (core.js: GI.load, GI.tableHTML, GI.sortable, GI.plot, GI.layout, GI.pctColor,
 * GI.teamColour ...) where those exist and falls back to local copies.
 *
 * Data (oddsmarkets/nfl/PAYLOADS.md): data/<S>/players.json (catalogue by position group:
 * {"metrics": [METRIC], "players": {pid: {"name","team","pos","group","age","games","qualified",
 * "values","pct","pct_pos"}}}; METRIC = {key,label,group,fmt,lower,scope,desc,stabilises_at}, where
 * "group" is the metric's family and "scope" the position group(s) it applies to), data/players_index.json
 * ({pid: [name, team, pos, first_season, last_season]}) and data/index.json (teams, season, week).
 *
 * Address: #/players?g=QB|RB|WR|TE|K|P|DEF (&s=<season>). */
(function (GI) {
'use strict';

// ════════════════════════════════════════════════════════════════════════════
// The kit: GI.fk
// ════════════════════════════════════════════════════════════════════════════

const K = GI.fk = GI.fk || {};

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const escL = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const has = f => typeof GI[f] === 'function';
const enc = encodeURIComponent;
K.isNum = isNum;
K.has = has;
K.esc = s => (has('esc') ? GI.esc(s) : escL(s));
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
/* Catalogue values by METRIC fmt. PAYLOADS: probabilities 4 dp, EPA 3 dp, fractions 0-1.
 * Formats: int|0|1|2|3|pct|prob|signed|signed1|signed2|signed3|epa|yds|sec|mph|ft|plus|wp|pp. */
K.fmtV = (v, fmt) => {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt || '')) {
    case 'int': case 'count': return Math.round(x).toLocaleString('en-GB');
    case 'plus': return Math.round(x).toString();
    case '0': return x.toFixed(0);
    case '1': case 'yds': case 'mph': case 'ft': case 'in': return x.toFixed(1);
    case '2': return x.toFixed(2);
    case '3': return x.toFixed(3);
    case 'sec': case 's': return x.toFixed(2) + 's';
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'pct0': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(0) + '%';
    case 'prob': case 'wp': return K.pct(x);
    case 'pp': return K.signed(x * 100, 1) + ' pp';
    case 'signed1': case 'pm': return K.signed(x, 1);
    case 'signed': case 'signed2': return K.signed(x, 2);
    case 'signed3': case 'epa': return K.signed(x, 3);
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
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316', purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8' }, GI.C || {});
K.ACC = (GI.C && (GI.C.gi || GI.C.accent || GI.C.turf)) || '#4cae6b';
K.PALETTE = GI.PALETTE || ['#4cae6b', '#58a6ff', '#f97316', '#bc8cff', '#f85149', '#39d0d8', '#d29922', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
K.CA = '#e8504f'; K.CB = '#58a6ff';   // compare: side A red, side B blue
K.fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
K.titleCase = s => String(s || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

// ── season, index ──────────────────────────────────────────────────────────

K.ready = () => (K.INDEX ? Promise.resolve(K.INDEX) : GI.load('index.json').then(d => { K.INDEX = d || {}; K.learnIndex(K.INDEX); return K.INDEX; }));
K.curSeason = () => {
  if (has('currentSeason')) { try { const c = GI.currentSeason(); if (isNum(c)) return Number(c); } catch (e) { /* local */ } }
  const x = K.INDEX || {};
  if (isNum(x.season)) return Number(x.season);
  const d = new Date();
  return d.getMonth() < 2 ? d.getFullYear() - 1 : d.getFullYear();
};
K.S = (params, state) => {
  const q = (params && params.query) || {};
  const raw = params && (params.season || q.s || q.season || q.y);
  if (isNum(raw)) return Number(raw);
  const st = state || GI.state || {};
  if (isNum(st.season)) return Number(st.season);
  return K.curSeason();
};
K.week = () => { const x = K.INDEX || {}; return isNum(x.week) ? Number(x.week) : null; };
K.loadY = (S, file) => GI.load(S + '/' + file);
K.sq = S => (isNum(S) && Number(S) !== K.curSeason() ? '?s=' + S : '');
K.withQ = (h, S, extra) => {
  const parts = [];
  if (isNum(S) && Number(S) !== K.curSeason()) parts.push('s=' + S);
  Object.keys(extra || {}).forEach(k => { if (extra[k] !== '' && extra[k] !== null && extra[k] !== undefined) parts.push(enc(k) + '=' + enc(extra[k])); });
  return h + (parts.length ? '?' + parts.join('&') : '');
};

// ── teams (nflverse abbreviations) ─────────────────────────────────────────

/* Fallback until index.json "teams" loads: [name, conference, division, colour]. Colours are plain hex, no marks. */
const NFL = {
  ARI: ['Arizona Cardinals', 'NFC', 'NFC West', '#97233f'], ATL: ['Atlanta Falcons', 'NFC', 'NFC South', '#a71930'], BAL: ['Baltimore Ravens', 'AFC', 'AFC North', '#241773'],
  BUF: ['Buffalo Bills', 'AFC', 'AFC East', '#00338d'], CAR: ['Carolina Panthers', 'NFC', 'NFC South', '#0085ca'], CHI: ['Chicago Bears', 'NFC', 'NFC North', '#0b162a'],
  CIN: ['Cincinnati Bengals', 'AFC', 'AFC North', '#fb4f14'], CLE: ['Cleveland Browns', 'AFC', 'AFC North', '#311d00'], DAL: ['Dallas Cowboys', 'NFC', 'NFC East', '#041e42'],
  DEN: ['Denver Broncos', 'AFC', 'AFC West', '#fb4f14'], DET: ['Detroit Lions', 'NFC', 'NFC North', '#0076b6'], GB: ['Green Bay Packers', 'NFC', 'NFC North', '#203731'],
  HOU: ['Houston Texans', 'AFC', 'AFC South', '#03202f'], IND: ['Indianapolis Colts', 'AFC', 'AFC South', '#002c5f'], JAX: ['Jacksonville Jaguars', 'AFC', 'AFC South', '#006778'],
  KC: ['Kansas City Chiefs', 'AFC', 'AFC West', '#e31837'], LA: ['Los Angeles Rams', 'NFC', 'NFC West', '#003594'], LAR: ['Los Angeles Rams', 'NFC', 'NFC West', '#003594'],
  LAC: ['Los Angeles Chargers', 'AFC', 'AFC West', '#0080c6'], LV: ['Las Vegas Raiders', 'AFC', 'AFC West', '#a5acaf'], MIA: ['Miami Dolphins', 'AFC', 'AFC East', '#008e97'],
  MIN: ['Minnesota Vikings', 'NFC', 'NFC North', '#4f2683'], NE: ['New England Patriots', 'AFC', 'AFC East', '#002244'], NO: ['New Orleans Saints', 'NFC', 'NFC South', '#d3bc8d'],
  NYG: ['New York Giants', 'NFC', 'NFC East', '#0b2265'], NYJ: ['New York Jets', 'AFC', 'AFC East', '#125740'], PHI: ['Philadelphia Eagles', 'NFC', 'NFC East', '#004c54'],
  PIT: ['Pittsburgh Steelers', 'AFC', 'AFC North', '#ffb612'], SEA: ['Seattle Seahawks', 'NFC', 'NFC West', '#69be28'], SF: ['San Francisco 49ers', 'NFC', 'NFC West', '#aa0000'],
  TB: ['Tampa Bay Buccaneers', 'NFC', 'NFC South', '#d50a0a'], TEN: ['Tennessee Titans', 'AFC', 'AFC South', '#4b92db'], WAS: ['Washington Commanders', 'NFC', 'NFC East', '#5a1414'],
  OAK: ['Oakland Raiders', 'AFC', 'AFC West', '#a5acaf'], SD: ['San Diego Chargers', 'AFC', 'AFC West', '#0080c6'], STL: ['St. Louis Rams', 'NFC', 'NFC West', '#003594']
};
K.NFL = NFL;
K.DIVISIONS = ['AFC East', 'AFC North', 'AFC South', 'AFC West', 'NFC East', 'NFC North', 'NFC South', 'NFC West'];
K.NAMES = GI.NAMES || K.NAMES || {};   // pid -> {name, team, pos, first, last}; shared with the shell
K.TEAMS = GI.TEAMS || K.TEAMS || {};   // abbr -> {name, colour, alt, division, conference}; shared with the shell
K.learn = (pid, info) => { if (!pid || !info) return; const o = {}; Object.keys(info).forEach(k => { if (info[k] !== undefined && info[k] !== null && info[k] !== '') o[k] = info[k]; }); K.NAMES[pid] = Object.assign({}, K.NAMES[pid] || {}, o); };
K.learnTeam = (t, info) => {
  if (!t || !info || typeof info !== 'object') return;
  const clean = {};
  ['name', 'abbr', 'short', 'colour', 'color', 'alt', 'division', 'conference', 'conf', 'stadium', 'city'].forEach(k => { if (info[k] !== undefined && info[k] !== null && info[k] !== '') clean[k] = info[k]; });
  if (clean.color && !clean.colour) clean.colour = clean.color;
  if (clean.conf && !clean.conference) clean.conference = clean.conf;
  K.TEAMS[String(t)] = Object.assign({}, K.TEAMS[String(t)] || {}, clean);
};
K.learnIndex = d => { if (d && d.teams && typeof d.teams === 'object' && !Array.isArray(d.teams)) Object.keys(d.teams).forEach(t => K.learnTeam(t, d.teams[t])); };
K.loadNames = () => GI.load('players_index.json').then(d => {
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
  if (has('playerName')) { try { const n = GI.playerName(pid); if (n && !/^(Player |#)/.test(n) && n !== '—') return n; } catch (e) { /* local */ } }
  return pid ? String(pid) : '—';
};
K.surname = n => { const p = String(n || '').split(' '); if (p.length < 2) return p[0]; const sfx = /^(Jr\.?|Sr\.?|II|III|IV|V)$/i.test(p[p.length - 1]); return sfx && p.length > 2 ? p[p.length - 2] : p.slice(1).join(' '); };
K.team = t => {
  const x = K.TEAMS[String(t)];
  const fb = NFL[String(t)] ? { name: NFL[t][0], conference: NFL[t][1], division: NFL[t][2], colour: NFL[t][3] } : {};
  if (x) return Object.assign({}, fb, x);
  if (has('teamInfo')) { try { const y = GI.teamInfo(t); if (y && typeof y === 'object' && Object.keys(y).length) return Object.assign({}, fb, y); } catch (e) { /* local */ } }
  return fb;
};
K.teamAbbr = t => (t ? String(t) : '—');
K.teamName = t => (K.team(t).name || K.teamAbbr(t));
K.teamNick = t => { const n = K.teamName(t); const p = n.split(' '); return p.length > 1 ? (/^(49ers)$/.test(p[p.length - 1]) ? '49ers' : p[p.length - 1]) : n; };
K.lift = hex => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return null;
  let c = [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)], k = 0;
  const lum = x => (0.2126 * x[0] + 0.7152 * x[1] + 0.0722 * x[2]) / 255;
  while (lum(c) < 0.32 && k < 12) { c = c.map(v => Math.round(v + (255 - v) * 0.14)); k++; }
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
};
K.teamColour = t => {
  if (has('teamColour')) { try { const c = GI.teamColour(t); if (c) return c; } catch (e) { /* local */ } }
  return K.lift(K.team(t).colour) || '#6e7681';
};
const PATH_SEASON = S => K.sq(S);
K.playerHref = (pid, S) => '#/player/' + enc(pid) + PATH_SEASON(S);
K.teamHref = (t, S) => '#/team/' + enc(t) + PATH_SEASON(S);
K.coachHref = (name, S) => '#/coach/' + enc(name) + PATH_SEASON(S);
K.gameHref = (gid, S) => (has('gameHref') ? GI.gameHref(gid, S) : '#/game/' + enc(gid));
K.compareHref = (a, b) => '#/compare' + (a ? '/' + enc(a) : '') + (b ? '/' + enc(b) : '');
K.playerLink = (pid, label, S) => (pid ? '<a class="ply-link" href="' + K.playerHref(pid, S) + '">' + K.esc(label || K.name(pid)) + '</a>' : '<span class="muted-inline">—</span>');
K.teamChip = (t, S) => (t ? '<a class="gq-team" href="' + K.teamHref(t, S) + '" style="--tc:' + K.teamColour(t) + '" title="' + K.esc(K.teamName(t)) + '">' + K.esc(K.teamAbbr(t)) + '</a>' : '<span class="muted-inline">—</span>');
K.teamLink = (t, S) => (t ? '<a href="' + K.teamHref(t, S) + '">' + K.esc(K.teamName(t)) + '</a>' : '—');
K.coachLink = (name, S) => (name ? '<a class="gf-coach" href="' + K.coachHref(name, S) + '">' + K.esc(name) + '</a>' : '—');
K.gameLink = (gid, label, S) => (gid ? '<a href="' + K.gameHref(gid, S) + '">' + K.esc(label || gid) + '</a>' : '—');
/* "2026_04_PIT_CLE" -> {season, week, away, home}. */
K.parseGid = gid => { const m = /^(\d{4})_(\d{2})_([A-Z]+)_([A-Z]+)$/.exec(String(gid || '')); return m ? { season: Number(m[1]), week: Number(m[2]), away: m[3], home: m[4] } : {}; };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
K.fmtDate = (s, o) => {
  if (has('fmtDate')) { try { const r = GI.fmtDate(s, o); if (r && r !== '—') return r; } catch (e) { /* local */ } }
  if (!s) return '—';
  const d = new Date(String(s).length === 10 ? s + 'T12:00:00Z' : s);
  if (isNaN(d.getTime())) return String(s);
  const opt = o || {};
  return d.getDate() + ' ' + MONTHS[d.getMonth()] + (opt.year === false ? '' : ' ' + d.getFullYear());
};
/* Seconds left in a quarter -> "12:34". */
K.clock = s => { if (!isNum(s)) return String(s || '—'); const v = Math.max(0, Math.round(Number(s))); return Math.floor(v / 60) + ':' + String(v % 60).padStart(2, '0'); };
/* Yard line from yardline_100 (distance to the opponent's end zone) and the offence: "own 25", "opp 35", "50". */
K.yardLine = (yl100, team, opp) => {
  if (!isNum(yl100)) return '—';
  const y = Number(yl100);
  if (y === 50) return '50';
  return y > 50 ? (team ? K.esc(team) + ' ' : 'own ') + Math.round(100 - y) : (opp ? K.esc(opp) + ' ' : 'opp ') + Math.round(y);
};
K.downDist = (down, dist, yl100) => (isNum(down) ? K.ordinal(down) + ' & ' + (isNum(yl100) && isNum(dist) && Number(dist) >= Number(yl100) ? 'Goal' : (isNum(dist) ? Math.round(dist) : '?')) : '—');

// ── position groups ────────────────────────────────────────────────────────

K.GROUPS = ['QB', 'RB', 'WR', 'TE', 'K', 'P', 'DEF'];
K.GROUP_NAME = { QB: 'Quarterbacks', RB: 'Running backs', WR: 'Wide receivers', TE: 'Tight ends', K: 'Kickers', P: 'Punters', DEF: 'Defence' };
K.GROUP_ONE = { QB: 'quarterback', RB: 'running back', WR: 'wide receiver', TE: 'tight end', K: 'kicker', P: 'punter', DEF: 'defender' };
K.groupOf = (pos, group) => {
  if (group && K.GROUPS.indexOf(String(group).toUpperCase()) >= 0) return String(group).toUpperCase();
  const p = String(pos || '').toUpperCase();
  if (p === 'QB') return 'QB';
  if (/^(RB|HB|FB)$/.test(p)) return 'RB';
  if (p === 'WR') return 'WR';
  if (p === 'TE') return 'TE';
  if (/^(K|PK)$/.test(p)) return 'K';
  if (p === 'P') return 'P';
  if (/^(OL|OT|OG|C|G|T|LS)$/.test(p)) return 'OL';
  return p ? 'DEF' : '';
};
/* The sample a catalogue row is counted on, by group: [key, label]. */
K.SAMPLE = {
  QB: [['dropbacks', 'Dropbacks'], ['plays', 'Plays'], ['att', 'Attempts'], ['pass_att', 'Attempts'], ['attempts', 'Attempts']],
  RB: [['carries', 'Carries'], ['rush_att', 'Carries'], ['att', 'Carries'], ['touches', 'Touches'], ['plays', 'Plays']],
  WR: [['targets', 'Targets'], ['routes', 'Routes'], ['tgt', 'Targets'], ['plays', 'Plays']],
  TE: [['targets', 'Targets'], ['routes', 'Routes'], ['tgt', 'Targets'], ['plays', 'Plays']],
  K: [['fga', 'FG attempts'], ['fg_att', 'FG attempts'], ['kicks', 'Kicks']],
  P: [['punts', 'Punts']],
  DEF: [['snaps', 'Snaps'], ['def_snaps', 'Snaps'], ['pass_rush_snaps', 'Rush snaps'], ['tackles', 'Tackles'], ['plays', 'Plays']]
};
K.sampleKey = (P, group) => {
  const cands = K.SAMPLE[group] || [];
  const ids = Object.keys(P || {});
  for (let i = 0; i < cands.length; i++) { const c = cands[i][0]; if (ids.some(id => isNum(((P[id] || {}).values || {})[c]) || isNum(((P[id] || {}).n || {})[c]) || isNum((P[id] || {})[c]))) return cands[i]; }
  return ['games', 'Games'];
};
K.sampleOf = (p, key) => { const v = isNum((p.n || {})[key]) ? p.n[key] : (p.values || {})[key]; return isNum(v) ? Number(v) : (isNum(p[key]) ? Number(p[key]) : (key === 'games' && isNum(p.g) ? Number(p.g) : 0)); };
/* Metrics that apply to a position group (scope: 'QB' | ['WR','TE'] | 'all'; missing scope applies to every group). */
K.scopeOk = (m, group) => {
  const s = m && (m.scope !== undefined ? m.scope : m.groups);
  if (!s || s === 'all' || s === '*') return true;
  const list = Array.isArray(s) ? s : String(s).split(/[,|/ ]+/);
  return list.some(x => String(x).toUpperCase() === group || (String(x).toUpperCase() === 'REC' && (group === 'WR' || group === 'TE' || group === 'RB')) || (String(x).toUpperCase() === 'SKILL' && /^(RB|WR|TE)$/.test(group)));
};
K.metricsFor = (cat, group) => {
  const M = (cat || {}).metrics;
  if (M && !Array.isArray(M) && typeof M === 'object') return (M[group] || []).slice();
  const G = (cat || {}).groups;
  if (G && Array.isArray(G[group])) { const meta = K.metaOf(M || []); return G[group].map(x => meta[x]).filter(Boolean); }
  const P = (cat || {}).players || {};
  const ids = Object.keys(P).filter(id => K.groupOf(P[id].pos, P[id].group) === group);
  return (M || []).filter(m => K.scopeOk(m, group) && ids.some(id => isNum(((P[id] || {}).values || {})[m.key])));
};
K.allMetrics = cat => { const M = (cat || {}).metrics; if (M && !Array.isArray(M) && typeof M === 'object') { const out = [], seen = {}; Object.keys(M).forEach(g => (M[g] || []).forEach(m => { if (!seen[m.key]) { seen[m.key] = 1; out.push(m); } })); return out; } return (M || []).slice(); };

// ── HTML furniture ─────────────────────────────────────────────────────────

K.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + K.esc(id) + '"' : '') + '>' +
  (title ? '<div class="card-header">' + K.esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl ? '<span class="gq-ctl">' + ctl + '</span>' : '') + '</div>' : '') + (body || '') + '</div>';
K.tile = (label, value, sub, cls) => '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + K.esc(label) + '</div><div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>';
K.tiles = list => '<div class="kpi-grid gq-tiles">' + list.filter(Boolean).join('') + '</div>';
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
  if (has('pctColor')) return GI.pctColor(p);
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
/* Grouped sliders over a catalogue. opts {onlyKnown, note, glossary: true}. The shell's sliders keep one look across the site. */
K.sliders = (metrics, vals, pcts, opts) => {
  const o = opts || {};
  if (GI.charts && typeof GI.charts.percentileSliders === 'function') {
    try {
      const fmtd = {};
      // The shell formats with its own fmtVal; hand it values it can format, and keep ours for unusual formats.
      const ms = (metrics || []).map(m => Object.assign({}, m));
      ms.forEach(m => { fmtd[m.key] = (vals || {})[m.key]; });
      return GI.charts.percentileSliders(ms, fmtd, pcts, o);
    } catch (e) { console.warn('sliders', e); }
  }
  const groups = K.groups(metrics).map(g => ({ name: g.name, items: g.items.filter(m => !o.onlyKnown || isNum((vals || {})[m.key])) })).filter(g => g.items.length);
  if (!groups.length) return K.muted('No metrics in the catalogue yet.');
  return '<div class="gq-sl-cols">' + groups.map(g => '<div class="gq-sl-group"><div class="gq-sl-head">' + K.esc(g.name) + '</div>' +
    g.items.map(m => K.slider(m.label + (m.lower ? ' ↓' : ''), (pcts || {})[m.key], K.fmt(m, (vals || {})[m.key]),
      (m.desc || m.label) + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + K.int(m.stabilises_at) + ' ' + (m.unit || 'plays') : ''),
      o.glossary === false ? null : '#/glossary/' + enc(m.key))).join('') + '</div>').join('') + '</div>' + (o.note ? '<div class="pg-note gq-note">' + o.note + '</div>' : '');
};

/* Tables: the shell's when present (same signature as Bullpen's BP.tableHTML), else this copy. */
K.table = (cols, rows, opts) => {
  if (has('tableHTML')) return GI.tableHTML(cols, rows, opts);
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
  if (has('sortable')) return GI.sortable(el);
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
  if (has('layout')) return GI.layout(extra);
  const out = Object.assign(JSON.parse(JSON.stringify(DARK)), extra || {});
  Object.keys(extra || {}).forEach(k => { if (/^[xy]axis\d*$/.test(k) && extra[k] && typeof extra[k] === 'object') out[k] = Object.assign({}, DARK.xaxis, extra[k]); });
  if (extra && extra.font) out.font = Object.assign({}, DARK.font, extra.font);
  return out;
};
K.plot = (el, traces, lay, conf) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (has('plot')) return GI.plot(node, traces, lay, conf);
  if (typeof Plotly === 'undefined') { node.innerHTML = K.muted('The chart library did not load. The tables carry the same data.'); return null; }
  try {
    const p = Plotly.newPlot(node, traces, lay, Object.assign({ displayModeBar: false, responsive: true }, conf || {}));
    if (has('onLeave')) GI.onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    return p;
  } catch (err) { node.innerHTML = K.muted('The chart could not be drawn.'); return null; }
};
K.chart = name => (GI.charts && typeof GI.charts[name] === 'function' ? GI.charts[name] : null);
K.narrow = node => ((node && node.clientWidth) || window.innerWidth || 800) < 520;
K.legendTop = () => ({ showlegend: true, legend: { orientation: 'h', y: 1.14, x: 0, font: { color: K.C.text2, size: 10 } } });
K.DIVERGE = [[0, '#2166ac'], [0.25, '#67a9cf'], [0.5, '#2d333b'], [0.75, '#ef8a62'], [1, '#b2182b']];
K.SEQ = [[0, '#161b22'], [0.25, '#1f3b57'], [0.5, '#2f6f9f'], [0.75, '#e08a3c'], [1, '#f85149']];
/* Click a Plotly point -> its customdata hash. */
K.clickThrough = id => { const n = typeof id === 'string' ? document.getElementById(id) : id; if (n && n.on) n.on('plotly_click', ev => { const h = ev.points && ev.points[0] && ev.points[0].customdata; if (h && typeof h === 'string' && h.charAt(0) === '#') location.hash = h; }); };

/* Reliability diagram: series [{name, colour, bins: [{lo, hi, n, mean_p|p, freq|obs}] | [[p, obs, n]]}]. */
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
  if (tr.length < 2) { node.innerHTML = K.muted('No reliability bins.'); node.style.height = 'auto'; return; }
  K.plot(node, tr, K.layout({ showlegend: true, legend: { orientation: 'h', y: -0.24, font: { color: K.C.text2, size: 10 } }, margin: { l: 55, r: 15, t: 10, b: 84 },
    xaxis: { title: o.xt || 'Forecast', tickformat: o.fmt || '.0%', range: [lo, hi] }, yaxis: { title: o.yt || 'Observed', tickformat: o.fmt || '.0%', range: [lo, hi] } }));
};
K.binsOf = bins => (bins || []).map(b => (Array.isArray(b) ? { x: b[0], y: b[1], n: b[2] || 0 } : { x: [b.mean_p, b.p, b.pred, b.x, b.forecast, b.mean_pred].find(isNum), y: [b.freq, b.obs, b.y, b.observed, b.actual, b.rate].find(isNum), n: b.n || b.count || 0, lo: b.lo, hi: b.hi }))
  .filter(b => isNum(b.x) && isNum(b.y));

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
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object');
  if ((x.cols || x.fields || x.columns) && (x.rows || x.data)) return K.colRows(x);
  if (typeof x === 'object') return Object.keys(x).filter(k => x[k] && typeof x[k] === 'object' && !Array.isArray(x[k])).map(k => Object.assign({ [idKey || 'id']: k }, x[k]));
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
K.shortLabel = s => String(s || '').replace(/percentage/i, '%').replace(/ over expected/i, ' OE').replace(/ per play/i, '/play').replace(/^Expected /, 'x').slice(0, 24);
K.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + enc(key) + '" title="Glossary: ' + K.esc(key) + '">' + text + '</a>';
/* Catalogue payload -> {metrics, players, ...}; tolerates a wrapper {"ok", "players": {...}} or {"catalogue": {...}}. */
/* Published descriptions never carry build-internal wording ("builder B's qb model ..."). */
K.cleanDesc = t => String(t || '').replace(/\(?builder [A-Z]'s ([a-z_ ]+?) model; /gi, '(').replace(/builder [A-Z]'s /gi, 'our ').replace(/\s+\(\)/g, '').replace(/player_value/g, 'player-value model').replace(/team_strength/g, 'team-strength model');
K.cleanMetrics = list => { (Array.isArray(list) ? list : []).forEach(m => { if (m && m.desc && !m._c) { m.desc = K.cleanDesc(m.desc); m._c = 1; } }); return list; };
K.catOf = d => {
  if (!d || d.ok === false) return null;
  K.cleanMetrics(d.metrics);
  if (d.players && d.metrics) return d;
  const inner = d.catalogue || d.data;
  if (inner && inner.players) return Object.assign({}, d, inner);
  return d.players ? Object.assign({ metrics: [] }, d) : null;
};
/* Headline metrics per group (exact keys first, then patterns). */
K.PREFS = {
  QB: ['composite', 'epa_db', 'epa_per_db', 'epa_per_play', /^epa_?(per_?)?(play|db|dropback)/, 'value', 'cpoe', /cpoe/, 'success', 'success_rate', 'adot', 'ttt', 'time_to_throw', 'sack_rate', 'twp_rate', /twp|turnover_worthy/],
  RB: ['value', 'ryoe', 'ryoe_per_att', /ryoe/, 'rush_epa', 'rush_success', 'success_rate', 'explosive', 'explosive_rate', 'target_share', 'rec_epa_tgt'],
  WR: ['value', 'target_share', 'rec_epa_tgt', 'adot', 'separation', 'yacoe', 'yac_oe', /yac_?oe|yacoe/, 'croe', /croe|catch_rate_oe/, 'drop_rate', 'wopr'],
  K: ['fg_oe', 'pts_oe', /fg_?oe|over_exp/, 'fg_pct', 'fg_50_pct', 'xp_pct', 'avg_dist', 'fga'],
  P: ['epa_punt', 'epa_per_punt', 'net', 'net_avg', 'gross', 'inside20', 'touchback_rate', 'punts'],
  DEF: ['def_value', 'splash_pg', 'sacks', 'pressures_pg', 'qb_hits', 'tfl', 'ints', 'pd', 'tackles']
};
K.PREFS.TE = K.PREFS.WR;

// ── player picker (typeahead over players_index.json and the catalogues) ───

/* host: element; opts {value, label, placeholder, onPick(id), filter(id, info), extra: {id: {name, pos, team}}}. */
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
  if (has('onLeave')) GI.onLeave(() => document.removeEventListener('click', outside));
  return { input: input, refresh: () => { items = null; } };
};

/* Register a page under a route name and its pattern(s); the shell's GI.route accepts either. */
K.route = (names, fn) => {
  if (typeof GI.route !== 'function') return;
  (Array.isArray(names) ? names : [names]).forEach(n => { try { GI.route(n, fn); } catch (e) { console.warn('route failed', n, e); } });
};
/* A page header in the house style. */
K.head = (title, sub, right, badge, colour) => '<div class="gq-head"' + (colour ? ' style="--tc:' + colour + '"' : '') + '>' + (badge ? '<div class="gq-badge">' + badge + '</div>' : '') +
  '<div class="gq-head-body"><h2>' + title + '</h2>' + (sub ? '<div class="gq-head-sub">' + sub + '</div>' : '') + '</div>' + (right ? '<div class="gq-head-links">' + right + '</div>' : '') + '</div>';
K.setMeta = html => { if (has('setMeta')) { try { GI.setMeta(html); } catch (e) { /* optional */ } } };
K.$ = id => document.getElementById(id);
K.set = (id, html) => { const e = document.getElementById(id); if (e) e.innerHTML = html; return e; };

// ════════════════════════════════════════════════════════════════════════════
// The catalogue page (#/players)
// ════════════════════════════════════════════════════════════════════════════

const ST = { group: 'QB', q: '', team: '', pos: '', floor: null, basis: 'pct', qual: true, extra: [], season: null, sortKey: null };

function renderPlayers(el, params, state) {
  const k = K;
  const qy = (params && params.query) || {};
  if (qy.g && k.GROUPS.indexOf(String(qy.g).toUpperCase()) >= 0) ST.group = String(qy.g).toUpperCase();
  el.innerHTML = '<div class="card"><div class="card-header">Players <span class="card-sub" id="cat-sub">Loading…</span><span class="gq-ctl">' +
    k.toggle('cat-group', k.GROUPS.map(g => [g, g]), ST.group) + '</span></div>' +
    '<div class="lab-controls gq-controls">' +
    '<label>Search<input id="cat-q" class="gq-search" type="search" placeholder="name or team…"></label>' +
    '<label>Team<select id="cat-team"><option value="">All teams</option></select></label>' +
    '<label>Position<select id="cat-pos"><option value="">All positions</option></select></label>' +
    '<label><span>Min <span id="cat-floor-u">plays</span> <span id="cat-floor-v"></span></span><input id="cat-floor" type="range" min="0" max="700" step="1"></label>' +
    '<label>Percentiles<select id="cat-basis"><option value="pct">against the group</option><option value="pct_pos">against the exact position</option></select></label>' +
    '<label>Add a metric<select id="cat-extra" class="gq-wide"><option value="">—</option></select></label>' +
    '<label class="inline"><input id="cat-qual" type="checkbox"> qualified only</label>' +
    '<label>&nbsp;<button type="button" id="cat-clear" class="gq-btn">Clear added</button></label>' +
    '</div><div id="cat-chips" class="gq-chips"></div><div id="cat-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="cat-note"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'players.json'), k.loadNames()]).then(res => ({ S: S, raw: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = k.catOf(o.raw), $ = k.$;
    if (!cat) { $('cat-table').innerHTML = k.notBuilt('The ' + S + ' player catalogue', o.raw); $('cat-sub').textContent = ''; return; }
    k.learnCat(cat);
    if (ST.season !== S) { ST.season = S; ST.floor = null; ST.team = ''; ST.pos = ''; }
    const P = cat.players;
    const byGroup = {};
    Object.keys(P).forEach(id => { const g = k.groupOf(P[id].pos, P[id].group); (byGroup[g] = byGroup[g] || []).push(id); });
    $('cat-group').querySelectorAll('button').forEach(b => { b.disabled = !(byGroup[b.dataset.v] || []).length; b.title = (byGroup[b.dataset.v] || []).length + ' ' + (k.GROUP_NAME[b.dataset.v] || b.dataset.v).toLowerCase(); });
    if (!(byGroup[ST.group] || []).length) ST.group = k.GROUPS.find(g => (byGroup[g] || []).length) || 'QB';
    $('cat-group').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === ST.group));
    const setup = () => {
      const g = ST.group, ids = byGroup[g] || [];
      const metrics = k.metricsFor(cat, g), meta = k.metaOf(metrics);
      const sk = k.sampleKey(pick(P, ids), g);
      const maxN = Math.max.apply(null, ids.map(id => k.sampleOf(P[id], sk[0])).concat([10]));
      const floorDef = [((cat.floors || {})[g]), cat.floor].find(isNum);
      $('cat-floor').max = String(Math.ceil(maxN));
      $('cat-floor').step = maxN > 200 ? '5' : '1';
      $('cat-floor-u').textContent = sk[1].toLowerCase();
      if (ST.floor === null || ST.floor > maxN) ST.floor = isNum(floorDef) ? Math.min(floorDef, maxN) : 0;
      $('cat-floor').value = ST.floor; $('cat-floor-v').textContent = ST.floor;
      const teams = {};
      ids.forEach(id => { const t = P[id].team; if (t) teams[t] = 1; });
      $('cat-team').innerHTML = '<option value="">All teams</option>' + Object.keys(teams).sort().map(t => '<option value="' + k.esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + k.esc(t + ' · ' + k.teamName(t)) + '</option>').join('');
      const pos = {};
      ids.forEach(id => { const x = P[id].pos; if (x) pos[x] = (pos[x] || 0) + 1; });
      $('cat-pos').innerHTML = '<option value="">All positions</option>' + Object.keys(pos).sort().map(x => '<option value="' + k.esc(x) + '"' + (x === ST.pos ? ' selected' : '') + '>' + k.esc(x) + ' (' + pos[x] + ')</option>').join('');
      $('cat-pos').parentNode.style.display = Object.keys(pos).length > 1 ? '' : 'none';
      $('cat-extra').innerHTML = '<option value="">—</option>' + k.groups(metrics).map(gr => '<optgroup label="' + k.esc(gr.name) + '">' + gr.items.map(m => '<option value="' + k.esc(m.key) + '">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      ST.extra = ST.extra.filter(x => meta[x]);
      const heads = k.headline(metrics, k.PREFS[g] || [], 7);
      if (ST.sortKey && !meta[ST.sortKey]) ST.sortKey = null;
      return { g: g, ids: ids, metrics: metrics, meta: meta, sk: sk, heads: heads };
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
    $('cat-floor').oninput = e => { ST.floor = Number(e.target.value); $('cat-floor-v').textContent = ST.floor; };
    $('cat-floor').onchange = draw;
    $('cat-extra').onchange = e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0 && ctx.heads.every(m => m.key !== x)) ST.extra.push(x); e.target.value = ''; draw(); };
    $('cat-clear').onclick = () => { ST.extra = []; draw(); };
    $('cat-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (!b) return; ST.extra = ST.extra.filter(x => x !== b.dataset.rm); draw(); };
    k.wireToggle(el, 'cat-group', v => { ST.group = v; ST.floor = null; ST.team = ''; ST.pos = ''; ST.extra = []; ST.sortKey = null; ctx = setup(); draw(); try { history.replaceState(null, '', k.withQ('#/players', S, { g: v })); } catch (e) { /* ok */ } });
    draw();
  });
}
function pick(P, ids) { const o = {}; ids.forEach(id => { o[id] = P[id]; }); return o; }

function drawCatalogue(S, cat, ctx) {
  const k = K;
  const P = cat.players, g = ctx.g;
  const q = k.fold(ST.q.trim());
  const extras = ST.extra.map(x => ctx.meta[x]).filter(Boolean);
  const cols = ctx.heads.concat(extras.filter(m => ctx.heads.indexOf(m) < 0));
  const sk = ctx.sk[0];
  const ids = ctx.ids.filter(id => {
    const p = P[id];
    if (k.sampleOf(p, sk) < ST.floor) return false;
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
    return (sortLower ? -d : d) || k.sampleOf(P[b], sk) - k.sampleOf(P[a], sk);
  });
  const src = p => (ST.basis === 'pct_pos' ? (p.pct_pos || p.pct || {}) : (p.pct || {}));
  const rows = ids.slice(0, 500).map((id, i) => {
    const p = P[id];
    return { _href: k.playerHref(id, S), cells: [
      { v: i + 1, cls: 'pos-cell' },
      { v: p.name || k.name(id), html: '<a class="ply-link" href="' + k.playerHref(id, S) + '">' + k.esc(p.name || k.name(id)) + '</a>' + (p.qualified === false ? ' <span class="gq-tag" title="Below the sample floor: percentiles are not published">small sample</span>' : '') },
      { v: p.team || '', html: k.teamChip(p.team, S) },
      { v: p.pos || '', html: k.esc(p.pos || '—') },
      { v: p.age, html: isNum(p.age) ? k.num(p.age, 0) : '—', align: 'right' },
      { v: k.first(p.games, p.g, (p.values || {}).games), html: k.int(k.first(p.games, p.g, (p.values || {}).games)), align: 'right' },
      { v: k.sampleOf(p, sk), html: k.int(k.sampleOf(p, sk)), align: 'right' }
    ].concat(cols.map(m => {
      const v = (p.values || {})[m.key], pc = src(p)[m.key];
      return { v: isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gq-val">' + k.fmt(m, v) + '</span> ' + k.pill(pc), align: 'right' };
    })) };
  });
  const host = k.$('cat-table');
  if (!host) return;
  const sameSample = sk === 'games';
  const head = [{ label: '#', sortable: false }, { label: k.GROUP_ONE[g] ? k.titleCase(k.GROUP_ONE[g]) : 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'G', align: 'right' }, { label: ctx.sk[1], align: 'right' }]
    .concat(cols.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + k.int(m.stabilises_at) : '') })));
  if (sameSample) { head.splice(6, 1); rows.forEach(r => r.cells.splice(6, 1)); }
  host.innerHTML = rows.length ? k.table(head, rows, { sticky: true, compact: true }) : k.muted('No ' + (k.GROUP_ONE[g] || 'player') + ' matches these filters.');
  k.sortable(host);
  const chips = k.$('cat-chips');
  if (chips) chips.innerHTML = extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + k.esc(m.key) + '" title="Remove">' + k.esc(m.label) + ' ×</button>').join(' ') : '';
  k.set('cat-sub', ids.length + ' of ' + ctx.ids.length + ' ' + (k.GROUP_NAME[g] || g).toLowerCase() + (ids.length > 500 ? ' (first 500 shown)' : '') + ' · ' + S + ' · sorted by ' + k.esc(sm.label || 'sample') + '; click a header to sort, a row for the player');
  const stab = cols.filter(m => isNum(m.stabilises_at));
  k.set('cat-note', S + (cat.updated_at ? ', updated ' + k.esc(k.fmtDate(cat.updated_at, { year: false })) : '') + '. Pills are percentiles (100 = best; ↓ metrics are flipped so red is always good) against every qualified ' + k.esc(k.GROUP_ONE[g] || 'player') +
    ', or against the same listed position with the second option. Players below the sample floor show raw values only, and every rate is shrunk towards the group mean by its stabilisation point before ranking' +
    (stab.length ? ' (' + stab.slice(0, 4).map(m => k.esc(m.label) + ' about ' + k.int(m.stabilises_at)).join(', ') + ')' : '') + '. ' +
    'Headline columns: ' + ctx.heads.map(m => k.glossLink(m.key, k.esc(m.label))).join(' · ') + '. All ' + ctx.metrics.length + ' ' + k.esc(g) + ' metrics are on every player page, the <a href="' + k.withQ('#/leaders', S, { g: g }) + '">leaders</a> page and in the <a href="' + k.withQ('#/lab', S, { g: g }) + '">lab</a>.' +
    (g === 'DEF' ? ' Defence is limited by the public data: no individual coverage charting exists in-season, so defenders are rated on pass rush, tackles, takeaways and the plays they are credited with; see the <a href="#/methodology/limitations">limitations</a>.' : ''));
}

K.route(['players', '#/players'], renderPlayers);
})(window.GI || (window.GI = {}));
