/* The Quant Campus — the Scouting Room (#/<L>/scout), round 9 (28 Oct 2026; the Bullpen pilot, bp-scout.js, is the
 * reference): the Players catalogue and the Lab's players chart in one page. Kit: scout.js (QK.board, QK.leaderCard,
 * QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare, QK.scoutBar) and quant.js (QK.within, QK.hotRow).
 *
 * One control bar drives every view: "Compare within" Broad (football: offence, defence, specialists; basketball: all
 * players) or Position (the metrics spec's peer groups: CFB QB ... P by position, MBB / WBB guards, wings and bigs by
 * the box-score role), the season, the minimum (the spec's floor: the payload's qualified / qualified_rate flags, or a
 * games slider), team, conference, class (college has no dates of birth, so the year in school stands in for the age
 * band) and search. Under the bar, "Top of the position": the leader on five of the view's metrics.
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips ("Position view" = the spec view's excellence, production
 *            and value sets; "Our models"; every payload group), any metric added, percentile cells against the peers
 *            (the group past the floor; lower-is-better flipped, style metrics grey), top 50 then "Show all", CSV;
 *   chart    any two metrics (the Position view's presets first), coloured by the view's value metric on the percentile
 *            scale, medians, the corners named, the search ringed and "Most like" it;
 *   leaders  small multiples on the view's key metrics: the top five and the bottom three over a dot strip.
 * Selecting a player anywhere opens the profile drawer (?p=<pid>); pin up to four to the compare tray (?cmp=), whose
 * "Full compare" is #/<L>/compare?p=<pid>,<pid> (CC.compareFull, below). The views' tab row ends with Compare (the full
 * compare page, on the room's position group in Position mode).
 * Address: ?view, within=pos&pos=<code> | grp=off|def|st (Broad football), min, team, conf, cls, q, cols, add, sort,
 * dir, all, p, cmp, x, y, c, season. Old routes (#/<L>/players, #/<L>/lab) redirect here (cc-core.js CC.redirect).
 * Data: <L>/<S>/lab_players.json (every listed player, every metric, column-oriented; one load shared by the views),
 * <L>/<S>/players.json only for the full compare page. Older payloads without the spec's rates get the exact ones from
 * their season totals (DERIVE). Older-browser rule: no optional chaining, no nullish coalescing. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

/* Broad groups (football by side of the ball: specialists never pooled with players), and their "view": the sets the
 * board, the chart and the profile lead with (a Position group takes its sets from the spec's view instead). */
var BROAD = {
  cfb: [['off', 'Offence', ['QB', 'RB', 'WR', 'TE'], 'offensive players'], ['def', 'Defence', ['DL', 'LB', 'DB'], 'defenders'], ['st', 'Specialists', ['K', 'P'], 'specialists']],
  bb: [['all', 'All players', null, 'players']],
  hk: [['sk', 'Skaters', ['F', 'D'], 'skaters'], ['g', 'Goalies', ['G'], 'goalies']]
};
var BROAD_VIEW = {
  off: { why: '', x: 'epa_play', y: 'value_pg', color: 'value', sets: [['excellence', 'Efficiency', ['epa_play', 'sr_db', 'sr_rush', 'sr_tgt', 'ypa', 'ypc', 'yptpa']], ['production', 'Production', ['pass_yds', 'rush_yds', 'rec_yds', 'pass_td', 'rush_td', 'rec_td', 'rec']], ['aggregate', 'Value', ['value_pg', 'value', 'epa']]] },
  def: { why: '', x: 'havoc_pg', y: 'value_pg', color: 'value', sets: [['excellence', 'Disruption', ['havoc_pg', 'tfl_pg', 'sacks_pg', 'hurries_pg', 'pd_pg', 'def_int_pg']], ['production', 'Production', ['tkl', 'tfl', 'sacks', 'pd', 'def_int']], ['aggregate', 'Value', ['value_pg', 'value']]] },
  st: { why: '', x: 'fg_pct', y: 'value_pg', color: 'value', sets: [['excellence', 'Kicking and punting', ['fg_pct', 'xp_pct', 'gross', 'in20_rate', 'tb_rate']], ['production', 'Production', ['fgm', 'fga', 'fg_long']], ['aggregate', 'Value', ['value_pg', 'value']]] },
  all: { why: '', x: 'ts', y: 'pts', color: 'r', sets: [['excellence', 'Efficiency', ['ts', 'ts_add', 'efg', 'ortg', 'pts100']], ['production', 'Scoring and more', ['pts', 'reb', 'ast', 'stl', 'blk', 'min']], ['aggregate', 'Value', ['r', 'value_pg', 'value']]] },
  /* college hockey (College Hockey News lines): skaters and goalies are never pooled */
  sk: { why: '', x: 'sh_pg', y: 'pts_pg', color: 'gar_pg', sets: [['excellence', 'Driving play', ['sh_pg', 'tsa_pg', 'p1_pg', 'pm_rel', 'sh_pct', 'p60']], ['production', 'Scoring', ['pts_pg', 'g_pg', 'a_pg', 'pts', 'g', 'a', 'toi_pg']], ['aggregate', 'Value', ['gar_pg', 'gar', 'war']]] },
  g: { why: '', x: 'sa60', y: 'sv_pct', color: 'gsaa', sets: [['excellence', 'Stopping shots', ['sv_pct', 'sv_above', 'gaa']], ['production', 'Workload', ['sa60', 'gp', 'min']], ['aggregate', 'Value', ['gsaa', 'gar', 'war']]] }
};
var CLASSES = [['', 'Any year'], ['FR', 'Freshmen'], ['SO', 'Sophomores'], ['JR', 'Juniors'], ['SR', 'Seniors']];
var LISTED_ROLE = { G: 'G', C: 'B', F: 'W' };
/* football's rate minimums for a payload without qualified_rate: [lab field, per game played] (players.RATE_MIN) */
var CFB_RATE_MIN = { QB: ['db', 12.5], RB: ['rush_car', 6.25], WR: ['tgt', 2.5], TE: ['tgt', 1.67], K: ['fga', 0.67] };
/* exact rates from season totals, for older payloads: [id, numerator, denominator ('gp' = games), fmt, group] */
var DERIVE = {
  cfb: [['ypc', 'rush_yds', 'rush_car', '2', 'Rushing'], ['ypr', 'rec_yds', 'rec', '2', 'Receiving'], ['ypt', 'rec_yds', 'tgt', '2', 'Receiving'], ['catch_rate', 'rec', 'tgt', 'pct', 'Receiving'],
    ['fg_pct', 'fgm', 'fga', 'pct', 'Kicking'], ['fga_pg', 'fga', 'gp', '2', 'Kicking'], ['tkl_pg', 'tkl', 'gp', '2', 'Defence'], ['tfl_pg', 'tfl', 'gp', '2', 'Defence'], ['sacks_pg', 'sacks', 'gp', '2', 'Defence'],
    ['pd_pg', 'pd', 'gp', '2', 'Defence'], ['def_int_pg', 'def_int', 'gp', '3', 'Defence']],
  mbb: [['ast_tov', 'ast', 'tov', '2', 'Rates']],
  wbb: [['ast_tov', 'ast', 'tov', '2', 'Rates']]
};
/* totals: a bottom three says nothing useful about playing time */
var TOTALS = /^(value|epa|pass_yds|pass_td|rush_yds|rush_td|rec|rec_yds|rec_td|tgt|rush_car|tkl|tfl|sacks|pd|def_int|fgm|fga|db|gp|min|fg_long)$/;
/* one metric per family on the quick reads */
var FAMILY = { value: 'value_pg', epa: 'epa_play', rec_yds: 'yptpa', pass_yds: 'ypa', rush_yds: 'ypc', tkl: 'tkl_pg', sacks: 'sacks_pg', tfl: 'tfl_pg', pd: 'pd_pg', def_int: 'def_int_pg', pts: 'pts100', ts: 'ts_add' };
function fam(id) { return FAMILY[id] || id; }

/* ── state ───────────────────────────────────────────────────────────────── */
var SC = { L: 'cfb', S: null, view: 'board', within: 'broad', bg: 'off', pg: 'QB', min: null, team: '', conf: '', cls: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', c: '' };
var D = null, DK = '', ROOT = null, TRAY = null, BOARD = null, PCT = {};

function fb() { return CC.fb(SC.L); }
function broadList() { return BROAD[fb() ? 'cfb' : CC.hk(SC.L) ? 'hk' : 'bb']; }
function posGroups() { return (CC.METRICS || []).filter(function (g) { return g.L === SC.L && g.e === 'player' && g.pc && g.pc.length; }).map(function (g) { return { code: g.pc[0], g: g }; }); }
function posGroup(code) { return posGroups().filter(function (x) { return x.code === code; })[0] || null; }
function code() { return SC.within === 'pos' ? 'p:' + SC.pg : 'b:' + SC.bg; }
function bdef(k) { return broadList().filter(function (b) { return b[0] === k; })[0] || broadList()[0]; }
function grpName(c) { c = c || code(); if (c.charAt(0) === 'p') { var x = posGroup(c.slice(2)); return x ? x.g.d : c.slice(2); } return bdef(c.slice(2))[1]; }
function grpNoun(c) { c = c || code(); if (c.charAt(0) === 'p') return grpName(c).toLowerCase(); return bdef(c.slice(2))[3]; }

/* lab_players.json -> { idx, rows: [{ id, name, team, pos, cls, gp, role, a }], meta: { key: payload metric }, metrics } */
function prep(raw) {
  if (!raw || raw.ok === false || !Array.isArray(raw.rows) || !raw.fields) return null;
  var F = raw.fields.slice(), idx = {};
  F.forEach(function (f, i) { if (idx[f] === undefined) idx[f] = i; });
  var der = (DERIVE[SC.L] || []).filter(function (x) { return idx[x[0]] === undefined && idx[x[1]] !== undefined && (x[2] === 'gp' || idx[x[2]] !== undefined); });
  der.forEach(function (x) { idx[x[0]] = F.length; F.push(x[0]); });
  var meta = {}, mets = [];
  (raw.metrics || []).forEach(function (m) { if (m && idx[m.key] !== undefined && !meta[m.key]) { meta[m.key] = m; mets.push(m); } });
  der.forEach(function (x) { var m = { key: x[0], label: x[0], group: x[4], fmt: x[3], lower: false, desc: 'Computed on this page from the season totals.' }; meta[x[0]] = m; mets.push(m); });
  var g = function (r, f) { return idx[f] === undefined ? null : r[idx[f]]; };
  var rows = [];
  raw.rows.forEach(function (r0) {
    var id = String(g(r0, 'id')), nm = String(g(r0, 'name') || '').trim();
    if (!nm || /^team$/i.test(nm) || id.charAt(0) === '-') return;     // ESPN's team box line is not a player
    var a = r0.slice();
    der.forEach(function (x) { var n = g(r0, x[1]), d = x[2] === 'gp' ? g(r0, 'gp') : g(r0, x[2]); a[idx[x[0]]] = isNum(n) && isNum(d) && d > 0 ? n / d : null; });
    var pos = String(g(r0, 'pos') || '');
    var role = g(r0, 'role');
    rows.push({ id: id, name: nm, team: String(g(r0, 'team') || ''), pos: pos, cls: g(r0, 'class') || '', gp: g(r0, 'gp') || 0,
      role: role || (fb() || CC.hk(SC.L) ? null : LISTED_ROLE[pos] || null), roleListed: !role && !fb() && !CC.hk(SC.L), a: a });
  });
  var gmax = Math.max.apply(null, rows.map(function (r) { return r.gp; }).concat([1]));
  var withVals = mets.filter(function (m) { return rows.some(function (r) { return isNum(r.a[idx[m.key]]); }); });
  /* the spec's per-play and per-target rates (they settle in dropbacks, carries, targets ..., not games) */
  var rate = {};
  (CC.METRICS || []).forEach(function (g0) { if (g0.L === SC.L && g0.e === 'player') (g0.m || []).forEach(function (m) { if (m.m50 && m.mu && m.mu !== 'games' && m.mu !== 'minutes') rate[m.id] = 1; }); });
  return { idx: idx, rows: rows, meta: meta, metrics: withVals, gmax: gmax, derived: der.map(function (x) { return x[0]; }), rate: rate, qr: idx.qualified_rate };
}
function val(r, id) {
  var i = D.idx[id]; if (i === undefined) return null;
  var v = r.a[i];
  if (!isNum(v)) return null;
  /* Broad football pools the positions on the games floor only: a per-play rate counts only for a player with the
     volume for it (qualified_rate), so a two-carry back never tops "rush success rate" */
  if (SC.within === 'broad' && D.rate[id] && D.qr !== undefined && r.a[D.qr] === false) return null;
  return v;
}
function has(id) { return D && D.idx[id] !== undefined && !!D.meta[id]; }

/* metric display: the level's spec entry (cc-metrics.js: name, explanation, direction, style), our-model tag, the
   payload's format; British spelling for older payload labels */
function mmeta(id) {
  var m = (D && D.meta[id]) || { key: id, label: id };
  var sm = CC.specMeta(SC.L, 'player', id), ours = CC.ours(id);
  var label = CC.uk(sm ? sm.d : (m.label || id));
  var tip = CC.uk((sm && sm.x) || m.desc || '');
  return { id: id, label: label, short: label, tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''), ours: ours,
    lower: sm ? !!sm.low : !!m.lower, style: !!(sm && sm.style), fmt: function (v) { return CC.fmtMetric(m.fmt ? m : { fmt: /pct|rate|share/.test(id) && Math.abs(v) <= 1 ? 'pct' : '2' }, v); }, group: CC.uk(m.group || 'Other') };
}

/* ── groups, the floor, peers ────────────────────────────────────────────── */
function inGroup(r, c) {
  c = c || code();
  if (c.charAt(0) === 'b') { var b = bdef(c.slice(2)); return !b[2] || b[2].indexOf(r.pos) >= 0; }
  var x = posGroup(c.slice(2));
  if (!x) return false;
  var v = x.g.pf === 'role' ? r.role : r[x.g.pf] !== undefined ? r[x.g.pf] : r.pos;
  return x.g.pc.indexOf(v) >= 0;
}
/* the spec's minimum: the payload's flag (qualified_rate in football's Position groups, qualified otherwise), else
   the volume rule from the totals (older payloads) */
function qualified(r, c) {
  c = c || code();
  var x = c.charAt(0) === 'p' ? posGroup(c.slice(2)) : null;
  var f = x && x.g.min ? x.g.min.f : 'qualified';
  if (D.idx[f] !== undefined && r.a[D.idx[f]] !== null && r.a[D.idx[f]] !== undefined) return r.a[D.idx[f]] === true;
  if (D.idx.qualified !== undefined && r.a[D.idx.qualified] !== null && r.a[D.idx.qualified] !== undefined) return r.a[D.idx.qualified] === true;
  if (fb()) {
    var rm = x ? CFB_RATE_MIN[r.pos] : null;
    if (rm && D.idx[rm[0]] !== undefined) return (val(r, rm[0]) || 0) >= rm[1] * r.gp && r.gp >= (r.pos === 'K' ? 0.6 * D.gmax : 1);
    return r.gp >= (/^(DL|LB|DB)$/.test(r.pos) ? Math.max(4, 0.6 * D.gmax) : 4);
  }
  return r.gp >= Math.max(5, Math.floor(0.4 * D.gmax)) && (D.idx.min === undefined || (val(r, 'min') || 0) >= 10);
}
function minOk(r, c) { return SC.min === null ? qualified(r, c) : r.gp >= SC.min; }
function peers(c) { c = c || code(); return D.rows.filter(function (r) { return inGroup(r, c) && minOk(r, c); }); }
function keep(r) {
  if (SC.team && r.team !== SC.team) return false;
  if (SC.conf) { var t = CC.team(SC.L, r.team); if (!t || String(t.conference) !== SC.conf) return false; }
  if (SC.cls && String(r.cls || '').toUpperCase().slice(0, 2) !== SC.cls) return false;
  return true;
}
function shown() { return peers().filter(keep); }
function matches(r) { var q = String(SC.q || '').trim().toLowerCase(); return !!q && (r.name + ' ' + CC.tname(SC.L, r.team) + ' ' + CC.tabbr(SC.L, r.team)).toLowerCase().indexOf(q) >= 0; }
function floorText(c) {
  c = c || code();
  if (SC.min !== null) return SC.min + '+ games';
  var x = c.charAt(0) === 'p' ? posGroup(c.slice(2)) : null;
  var f = x ? CC.groupFloor(x.g) : '';
  return 'qualified' + (f ? ' (' + f + ')' : ' (the position’s games floor)');
}
function pctOf(r, id, c) {
  c = c || code();
  var key = c + '|' + SC.min + '|' + id, srt = PCT[key];
  if (!srt) srt = PCT[key] = peers(c).map(function (x) { return val(x, id); }).filter(isNum).sort(function (a, b) { return a - b; });
  var v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  var p = QK.pctRank(srt, v);
  return mmeta(id).lower ? 100 - p : p;
}
function clearPct() { PCT = {}; }

/* the view: the spec group's Position view (ids this payload carries for 30%+ of the peers); Broad: BROAD_VIEW */
function view(c) {
  c = c || code();
  var P = peers(c);
  var okId = function (id) { return has(id) && P.length > 0 && P.filter(function (r) { return isNum(val(r, id)); }).length >= 0.3 * P.length; };
  if (c.charAt(0) === 'p') {
    var x = posGroup(c.slice(2)), sg = x && CC.spec && CC.spec.group ? CC.spec.group(x.g.id) : null;
    var v = sg && sg.view ? QK.within.view(sg, okId) : null;
    if (v && v.x) {
      if (v.color && (v.color === v.x || v.color === v.y)) v.color = v.sets[2].ids.filter(function (id) { return id !== v.x && id !== v.y; })[0] || null;
      return { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(function (s) { return s.ids.length; }).map(function (s) { return { key: s.key, label: s.label, ids: s.ids }; }) };
    }
    var hs = x ? x.g.m.filter(function (m) { return m.set === 'h' && okId(m.id); }).map(function (m) { return m.id; }) : [];
    return { why: '', x: hs[1] || hs[0], y: hs[0], color: null, sets: hs.length ? [{ key: 'headline', label: 'Headline', ids: hs }] : [] };
  }
  var b = BROAD_VIEW[c.slice(2)] || BROAD_VIEW.all;
  var sets = b.sets.map(function (s) { return { key: s[0], label: s[1], ids: s[2].filter(okId) }; }).filter(function (s) { return s.ids.length; });
  var pick = function (want, alt) { return okId(want) ? want : alt; };
  var flat = [].concat.apply([], sets.map(function (s) { return s.ids; }));
  var x0 = pick(b.x, flat[0]), y0 = pick(b.y, flat.filter(function (id) { return id !== x0; })[0]);
  return { why: '', x: x0, y: y0, color: okId(b.color) && b.color !== x0 && b.color !== y0 ? b.color : null, sets: sets };
}
function pickDistinct(out, ids, n) {
  var k = 0;
  ids.forEach(function (id) { if (k >= n || out.indexOf(id) >= 0 || out.some(function (x) { return fam(x) === fam(id); })) return; out.push(id); k++; });
}
function keyMetrics(v) {
  var out = [];
  if (v.sets.length === 3) { pickDistinct(out, v.sets[0].ids, 3); pickDistinct(out, v.sets[1].ids, 4); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(function (s) { pickDistinct(out, s.ids, 3); });
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders', 'prospects'].indexOf(q.view) >= 0 && (q.view !== 'prospects' || fb()) ? q.view : 'board';
  var codes = posGroups().map(function (x) { return x.code; });
  if (q.within === 'pos' && codes.indexOf(q.pos) >= 0) { SC.within = 'pos'; SC.pg = q.pos; }
  else { SC.within = 'broad'; SC.bg = broadList().some(function (b) { return b[0] === q.grp; }) ? q.grp : broadList()[0][0]; SC.pg = codes[0] || ''; }
  var mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team || ''; SC.conf = q.conf || ''; SC.cls = /^(FR|SO|JR|SR)$/.test(q.cls || '') ? q.cls : '';
  SC.q = q.q || ''; SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.c = q.c || '';
}
function hashNow() {
  var q = [];
  var add = function (k, v) { if (v !== '' && v !== null && v !== undefined) q.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); };
  if (SC.view !== 'board') add('view', SC.view);
  if (SC.within === 'pos') { add('within', 'pos'); add('pos', SC.pg); } else if (SC.bg !== broadList()[0][0]) add('grp', SC.bg);
  if (SC.min !== null) add('min', SC.min);
  ['team', 'conf', 'cls', 'q', 'cols'].forEach(function (k) { add(k, SC[k]); });
  if (SC.add.length) add('add', SC.add.join(','));
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { add('sort', SC.sort.key); add('dir', SC.sort.dir); }
  if (SC.all) add('all', '1');
  add('p', SC.p);
  if (SC.cmp.length) add('cmp', SC.cmp.join(','));
  if (SC.view === 'chart') { add('x', SC.x); add('y', SC.y); add('c', SC.c); }
  return CC.href(SC.L, 'scout', null, SC.S, q.join('&'));
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }

/* ── names, links ───────────────────────────────────────────────────────── */
function href(r) { return CC.playerHref(SC.L, r.id, SC.S); }
function teamOf(r) { var t = CC.team(SC.L, r.team) || {}; return { abbr: CC.tabbr(SC.L, r.team), colour: t.colour || '', alt: CC.talt(SC.L, r.team) || '', name: t.short || t.name || '' }; }
function clsName(c) { var x = CLASSES.filter(function (k) { return k[0] && String(c || '').toUpperCase().indexOf(k[0]) === 0; })[0]; return x ? x[1].replace(/men$/, 'man').replace(/s$/, '') : ''; }
function posTxt(r) { return fb() ? r.pos : CC.hk(SC.L) ? CC.posName(SC.L, r.pos) : (r.role ? CC.posName(SC.L, r.role) : CC.posName(SC.L, r.pos)); }
function subOf(r) { return [posTxt(r), CC.tabbr(SC.L, r.team), r.cls ? String(r.cls).toUpperCase() : '', r.gp + ' GP'].filter(Boolean).join(' · '); }
function findRow(id) { var s = String(id); for (var i = 0; i < D.rows.length; i++) if (D.rows[i].id === s) return D.rows[i]; return null; }
/* the group a row belongs to in the current mode */
function codeOf(r) {
  if (SC.within === 'pos') { var x = posGroups().filter(function (z) { return inGroup(r, 'p:' + z.code); })[0]; return x ? 'p:' + x.code : code(); }
  var b = broadList().filter(function (z) { return !z[2] || z[2].indexOf(r.pos) >= 0; })[0];
  return 'b:' + (b ? b[0] : broadList()[0][0]);
}

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, p) {
  SC.L = p.L; SC.S = p.S;
  ROOT = el;
  readQuery(p.query || {});
  el.innerHTML = U.head('Scouting Room', 'Every player and every metric, judged against the same position: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare.', U.kicker(SC.L, SC.S)) +
    '<div class="sc qk-room"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].concat(CC.fb(SC.L) ? [['prospects', 'Draft prospects']] : []).map(function (t) { return '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>'; }).join('') +
    '<a class="qk-tab sc-tab-cmp" id="sc-tab-compare" href="' + esc(CC.href(SC.L, 'compare', null, SC.S)) + '">Compare</a></div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  CC.onLeave(function () { if (QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return Promise.all([CC.load(CC.path(SC.L, SC.S, 'lab_players.json')), CC.season(SC.L, SC.S), CC.metrics(), CC.specP]).then(function (a) {
    if (!U.alive(el)) return;
    readQuery(p.query || {});          /* again: the position groups (CC.METRICS) load with the page */
    var key = SC.L + '/' + SC.S;
    if (DK !== key) { D = prep(a[0]); DK = key; clearPct(); }
    if (!D || !D.rows.length) {
      document.getElementById('sc-ctl').innerHTML = '';
      document.getElementById('sc-view').innerHTML = CC.ok(a[0]) ? QK.empty('No player numbers yet', 'They appear once games have been played this season. Pick last season in the season menu above.') : U.missing('The scouting file', a[0]);
      return;
    }
    if (SC.within === 'pos' && !posGroup(SC.pg)) SC.within = 'broad';
    controls(); tabs(); tray(); refresh();
    if (SC.p) { var r = findRow(SC.p); if (r) openProfile(r.id); }
  });
}

/* a click on a player link anywhere in the room opens the drawer (a modified click follows the link) */
function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  var a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || !D) return;
  var m = /#\/(?:cfb|mbb|wbb|mch|wch)\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  var host = document.getElementById('sc-ctl');
  if (!host) return;
  var PG = posGroups();
  var bl = broadList();
  var broadSeg = bl.length > 1 ? '<div class="qk-seg" id="sc-grp" role="group" aria-label="Group">' + bl.map(function (b) { return '<button type="button" data-value="' + b[0] + '" aria-pressed="' + (SC.bg === b[0]) + '">' + esc(b[1]) + '</button>'; }).join('') + '</div>' : '';
  var within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', groups: PG.map(function (x) { return [x.code, x.g.d]; }), note: SC.within === 'pos' ? '' : broadSeg });
  var inG = D.rows.filter(function (r) { return inGroup(r); });
  var teams = Array.from(new Set(inG.map(function (r) { return r.team; }).filter(Boolean))).sort(function (a, b) { return CC.tname(SC.L, a).localeCompare(CC.tname(SC.L, b)); });
  var confs = Array.from(new Set(teams.map(function (t) { var x = CC.team(SC.L, t); return x && x.conference ? String(x.conference) : ''; }).filter(Boolean))).sort(function (a, b) { return CC.cname(SC.L, a).localeCompare(CC.cname(SC.L, b)); });
  var opt = function (v, t, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>'; };
  var anyCls = D.rows.some(function (r) { return r.cls; });
  var mx = Math.max(10, D.gmax);
  var items = [
    { label: 'Min games', html: '<span class="sc-min"><input type="range" id="sc-min" min="0" max="' + mx + '" step="1" value="' + (SC.min === null ? 0 : SC.min) + '" aria-label="Minimum games"><b class="qk-sbar-v" id="sc-min-v">' + (SC.min === null ? 'Qualified' : SC.min) + '</b></span>', cls: 'sc-minf' },
    { label: 'Conference', html: '<select class="qk-select" id="sc-conf">' + opt('', 'All conferences', SC.conf) + confs.map(function (c) { return opt(c, CC.cname(SC.L, c), SC.conf); }).join('') + '</select>' },
    { label: 'Team', html: '<select class="qk-select" id="sc-team">' + opt('', 'All teams', SC.team) + teams.filter(function (t) { var x = CC.team(SC.L, t); return !SC.conf || (x && String(x.conference) === SC.conf); }).map(function (t) { return opt(t, CC.tname(SC.L, t), SC.team); }).join('') + '</select>' },
    anyCls ? { label: 'Year', html: '<select class="qk-select" id="sc-cls">' + CLASSES.map(function (c) { return opt(c[0], c[1], SC.cls); }).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or team…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  var v = view();
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">' + esc(grpName()) + ', ' + esc(floorText()) + ' · ' + peers().length + ' players in the peer group' +
    (D.rows.some(function (r) { return r.roleListed; }) && SC.within === 'pos' ? ' · roles from the listed position until the next data build' : '') + '. Drag the slider for any number of games; back to 0 is the spec’s floor.</p>' +
    QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, function (w) {
    if (w.within === 'pos' && SC.within !== 'pos') {
      /* Broad -> Position: football keeps the side of the ball (offence opens on quarterbacks, defence on the line) */
      var first = { off: 'QB', def: 'DL', st: 'K' }[SC.bg];
      if (first && posGroup(first)) w.pos = first;
    }
    SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos;
    regroup();
  }, { id: 'sc-wn' });
  var seg = document.getElementById('sc-grp');
  if (seg) QK.seg(seg, function (x) { SC.bg = x; regroup(); });
  var $ = function (id) { return document.getElementById(id); };
  $('sc-min').oninput = function (e) { $('sc-min-v').textContent = Number(e.target.value) ? e.target.value : 'Qualified'; };
  $('sc-min').onchange = function (e) { var n = Number(e.target.value); SC.min = n > 0 ? n : null; clearPct(); controls(); refresh(); };
  $('sc-conf').onchange = function (e) { SC.conf = e.target.value; SC.team = ''; controls(); refresh(); };
  $('sc-team').onchange = function (e) { SC.team = e.target.value; refresh(); };
  if ($('sc-cls')) $('sc-cls').onchange = function (e) { SC.cls = e.target.value; refresh(); };
  var t = null;
  $('sc-q').oninput = function (e) { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
/* a new group: the floor, the column set, the sort and the chart's axes go back to the group's own */
function regroup() {
  SC.min = null; SC.cols = ''; SC.x = ''; SC.y = ''; SC.c = ''; SC.sort = null; SC.add = [];
  clearPct(); controls(); refresh();
}

/* ── views ───────────────────────────────────────────────────────────────── */
function tabs() {
  var bar = ROOT.querySelector('.sc-tabs');
  QK.$$('[role="tab"]', bar).forEach(function (b, i, all) {
    b.addEventListener('click', function () { select(b.getAttribute('data-view')); });
    b.addEventListener('keydown', function (e) {
      var j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : null;
      if (j === null) return;
      e.preventDefault();
      var n = all[(j + all.length) % all.length]; n.focus(); select(n.getAttribute('data-view'));
    });
  });
  function select(v) {
    SC.view = v;
    QK.$$('[role="tab"]', bar).forEach(function (b) { var on = b.getAttribute('data-view') === v; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
    document.getElementById('sc-view').setAttribute('aria-labelledby', 'sc-tab-' + v);
    drawView();
  }
}
function refresh() { if (!ROOT || !ROOT.isConnected) return; cmpTab(); topStrip(); drawView(); }
/* the Compare tab opens the full compare page on the room's position group (Position mode), else the level's default */
function cmpTab() {
  var a = ROOT.querySelector('#sc-tab-compare'), x = SC.within === 'pos' ? posGroup(SC.pg) : null;
  if (a) a.setAttribute('href', CC.href(SC.L, 'compare', null, SC.S, x && x.g.id ? 'g=' + encodeURIComponent(x.g.id) : ''));
}
function drawView() {
  writeQuery();
  var host = document.getElementById('sc-view');
  if (!host) return;
  BOARD = null;
  if (SC.view === 'chart') return chartView(host);
  if (SC.view === 'leaders') return leadersView(host);
  if (SC.view === 'prospects') return prospectsView(host);
  return boardView(host);
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* "Top of the position": the leader on five of the view's metrics among the players on screen */
function topStrip() {
  var host = document.getElementById('sc-top');
  if (!host) return;
  var v = view(), rows = shown();
  var ids = [];
  if (v.sets.length === 3) { pickDistinct(ids, v.sets[0].ids, 2); pickDistinct(ids, v.sets[1].ids, 2); pickDistinct(ids, v.sets[2].ids, 1); }
  else v.sets.forEach(function (s) { pickDistinct(ids, s.ids, 2); });
  var items = ids.slice(0, 5).map(function (id) {
    var m = mmeta(id);
    if (m.style) return null;
    var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
    if (!list.length) return null;
    var r = list[0], nx = list[1];
    return { sport: 'college', kicker: m.label, name: r.name, value: m.fmt(val(r, id)), title: CC.tabbr(SC.L, r.team) + ' · ' + posTxt(r), next: nx ? { name: nx.name, value: m.fmt(val(nx, id)) } : null, expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  var noun = grpNoun();
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + (SC.within === 'pos' ? 'position' : 'group'), title: SC.within === 'pos' ? 'The best ' + noun + ', on what matters there' : 'The best ' + noun + ' right now',
    sub: 'The leader on five of the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}

/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  var v = view(), P = peers();
  var all = shown();
  var rows = String(SC.q || '').trim() ? all.filter(matches) : all;
  var sets = [{ key: 'view', label: SC.within === 'pos' ? 'Position view' : 'Headline', groups: v.sets.map(function (s) { return { label: s.label, ids: s.ids }; }) }];
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var oursIds = D.metrics.filter(function (m) { return CC.ours(m.key) && okAny(m.key); }).map(function (m) { return m.key; });
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  var gnames = [];
  D.metrics.forEach(function (m) { var gn = CC.uk(m.group || 'Other'); if (gnames.indexOf(gn) < 0 && okAny(m.key)) gnames.push(gn); });
  gnames.forEach(function (gn) { sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: D.metrics.filter(function (m) { return CC.uk(m.group || 'Other') === gn && okAny(m.key); }).map(function (m) { return m.key; }) }] }); });
  var setKey = QK.board.pick(sets, SC.cols, 'view');
  var ag = v.sets.filter(function (s) { return s.key === 'aggregate'; })[0];
  /* the summary beside the name and the default sort: value per game, else the box rating (round 10), else the view's colour */
  var defSort = (has('value_pg') ? 'value_pg' : has('r') ? 'r' : null) || v.color || (ag ? ag.ids[0] : null) || ((v.sets[0] || { ids: [] }).ids[0]);
  var sort = SC.sort && SC.sort.key && (SC.sort.key === 'name' || SC.sort.key === 'gp' || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: sort.key !== 'name' && sort.key !== 'gp' && mmeta(sort.key).lower ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  var ordered = CC.orderMetrics(SC.L, 'player', D.metrics.filter(function (m) { return okAny(m.key); }));
  var addable = ordered.map(function (g) { return '<optgroup label="' + esc(CC.uk(g.label)) + '">' + g.items.map(function (m) { return '<option value="' + esc(m.key) + '">' + esc(mmeta(m.key).label) + '</option>'; }).join('') + '</optgroup>'; }).join('');
  var noun = grpNoun();
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><h2 class="qk-card-title">The board</h2><div class="qk-card-sub">' +
    esc(grpName()) + ' · ' + esc(CC.seasonLabel(SC.L, SC.S)) + ' · the bar under each number is its percentile against the ' + P.length + ' ' + esc(noun) + ', ' + esc(floorText()) + ': the top 10% in red, the bottom 10% in blue. Tap a name for the profile; tick the box beside it to pin it to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>';
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', summary: defSort, sets: sets, set: setKey, added: SC.add.filter(has), sort: sort, all: SC.all, page: 50, noun: noun,
    nameLabel: 'Player', subLabel: 'Position · team · year · games',
    meta: mmeta, addable: addable,
    lead: [{ key: 'gp', label: 'GP', tip: 'Games played', fmt: function (row) { return String(row._r.gp); }, val: function (row) { return row._r.gp; } }],
    rows: rows.map(function (r) { return { id: r.id, name: r.name, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r }; }),
    val: function (row, id) { return val(row._r, id); },
    peers: P.map(function (r) { return { id: r.id, _r: r }; }),
    hl: function (row) { return SC.cmp.indexOf(row.id) >= 0; },
    pin: { has: function (id) { return !!TRAY && TRAY.has(id); }, toggle: function (row) { pin(row._r); }, label: 'Pin to the compare tray' },
    onPick: function (row) { openProfile(row.id); },
    onState: function (st) { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'campus-' + SC.L + '-' + SC.S + '-' + code().replace(/[^a-z0-9]+/gi, '-').toLowerCase() + '.csv',
    empty: String(SC.q || '').trim() ? 'No ' + noun + ' match “' + SC.q.trim() + '” with these filters.' : 'No ' + noun + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(noun.replace(/s$/, '')) + ' in the peer group, whatever the team, conference or year filters show; a ↓ marks a metric where lower is better (its bar is flipped) and style metrics (neither better nor worse) are never coloured. Every metric in the file is under “Columns” or “Add a metric”.' +
      (D.derived.length ? ' Some rates are computed here from the season totals (this season’s file predates them).' : '')
  });
  if (v.sets.some(function (s) { return s.ids.some(function (id) { return CC.ours(id); }); })) host.insertAdjacentHTML('beforeend', '<div class="cc-ours">' + QK.oursExplain((fb() ? 'Value (points above a replacement-level player) and EPA per play' : 'Value (points above a replacement-level player) and the box rating per 100') + ' come from our models; columns tagged ' + QK.ours({ short: true }) + ' are theirs.') + '</div>');
}

/* Chart: any two metrics, the view's presets first, coloured by the value metric's percentile */
function chartView(host) {
  var v = view(), P = peers(), rows = shown();
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var list = D.metrics.filter(function (m) { return okAny(m.key); });
  var vo = QK.within.viewOrder(v, list, function (m) { return m.key; });
  var groups = vo.sets.map(function (s) { return { label: s.label, items: s.items }; }).concat(CC.orderMetrics(SC.L, 'player', vo.rest));
  var x = has(SC.x) && okAny(SC.x) ? SC.x : v.x, y = has(SC.y) && okAny(SC.y) ? SC.y : v.y;
  var c = SC.c === 'team' ? '' : has(SC.c) && okAny(SC.c) ? SC.c : (v.color || '');
  if (!x || !y) { host.innerHTML = QK.empty('Nothing to chart', 'This group has too few metrics with values.'); return; }
  var presets = QK.within.viewPresets(v, function (id) { return mmeta(id).label; });
  var pi = -1; presets.forEach(function (pr, i) { if (pi < 0 && pr.x === x && pr.y === y) pi = i; });
  var sel = function (id, cur, team) {
    return '<select class="qk-select" id="' + id + '">' + (team ? '<option value="team"' + (!cur ? ' selected' : '') + '>Team colours</option>' : '') + groups.map(function (g) {
      return '<optgroup label="' + esc(CC.uk(g.label)) + '">' + g.items.map(function (m) { return '<option value="' + esc(m.key) + '"' + (m.key === cur ? ' selected' : '') + '>' + esc(mmeta(m.key).label) + '</option>'; }).join('') + '</optgroup>';
    }).join('') + '</select>';
  };
  var mx = mmeta(x), my = mmeta(y), mc = c ? mmeta(c) : null;
  host.innerHTML = '<section class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
    presets.length ? { label: 'Preset', html: '<select class="qk-select" id="sc-preset">' + presets.map(function (pr, i) { return '<option value="' + i + '"' + (i === pi ? ' selected' : '') + '>' + esc(pr.label) + '</option>'; }).join('') + '<option value="-1"' + (pi < 0 ? ' selected' : '') + '>Any two metrics</option></select>', cls: 'grow' } : null,
    { label: 'Across', html: sel('sc-x', x) }, { label: 'Up', html: sel('sc-y', y) }, { label: 'Colour', html: sel('sc-c', c, true) }]) +
    '<h3 class="cc-chart-t">' + esc(my.label) + CC.oursTag(y, true) + ' against ' + esc(mx.label) + CC.oursTag(x, true) + '</h3>' +
    U.chart('sc-sc', 520, my.label + ' against ' + mx.label) + '<p class="cc-note" id="sc-ckey"></p><div id="sc-sim"></div></div></section>';
  var pts = rows.filter(function (r) { return isNum(val(r, x)) && isNum(val(r, y)); });
  var hits = String(SC.q || '').trim().length > 1 ? pts.filter(matches) : [];
  var med = function (a) { var b = a.slice().sort(function (p, q) { return p - q; }), n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
  var noC = QK.cssVar('--ink-3') || '#939bab';
  var colour = function (r) { if (!c) return CC.tcol(SC.L, r.team); var p0 = pctOf(r, c); return isNum(p0) ? QK.pctHex(p0) : noC; };
  var both = !mx.style && !my.style;
  /* never past the sensible range: a metric that cannot go below zero starts at zero */
  var lo0 = function (k) { var m0 = Math.min.apply(null, pts.map(function (r) { return val(r, k); })); return m0 >= 0 ? 0 : undefined; };
  QKC.scatter(document.getElementById('sc-sc'), {
    points: pts.map(function (r) { var hit = hits.indexOf(r) >= 0; return { x: val(r, x), y: val(r, y), name: r.name + ' · ' + CC.tabbr(SC.L, r.team) + (c ? ' · ' + mc.label + ' ' + mc.fmt(val(r, c)) : ''), label: QK.surname(r.name), color: colour(r), size: hit ? 20 : (pts.length > 300 ? 7 : 10), href: href(r), id: r.id }; }),
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: mx.fmt, yFmt: my.fmt, xInverse: mx.lower, yInverse: my.lower, labelTop: 10, pad: '8%', xMin: pts.length ? lo0(x) : undefined, yMin: pts.length ? lo0(y) : undefined,
    refX: pts.length > 2 ? med(pts.map(function (r) { return val(r, x); })) : null, refY: pts.length > 2 ? med(pts.map(function (r) { return val(r, y); })) : null,
    quadrants: both ? ['', 'Better on both', 'Behind on both', ''] : undefined,
    onClick: function (pt) { openProfile(pt.id); }, label: my.label + ' against ' + mx.label });
  document.getElementById('sc-ckey').innerHTML = pts.length + ' ' + esc(grpNoun()) + ' on the chart; dashed lines are their medians' + (both ? ', better is up and to the right' : '') + '. ' +
    (c ? 'Colour: <b>' + esc(mc.label) + '</b>, each player’s percentile in the peer group (blue low, red high; grey: none).' : 'Colour: each player’s team.') + ' Tap a point for the profile.';
  var sim = document.getElementById('sc-sim');
  if (hits.length) {
    var t = hits[0], keys = keyMetrics(v);
    var near = QK.within.similar(P.indexOf(t) >= 0 ? P : P.concat([t]), t, keys, function (r, k) { return val(r, k); }, 5);
    sim.innerHTML = QK.within.simHtml('Most like ' + t.name + ' · ' + grpNoun(), near.map(function (o) { return { name: o.row.name, href: href(o.row), sub: subOf(o.row) }; }));
  } else sim.innerHTML = '<p class="cc-note">Search a name in the bar above to ring the player and list the five most like them.</p>';
  var $ = function (id) { return document.getElementById(id); };
  var go = function () { SC.x = $('sc-x').value; SC.y = $('sc-y').value; SC.c = $('sc-c').value === 'team' ? 'team' : $('sc-c').value; drawView(); };
  ['sc-x', 'sc-y', 'sc-c'].forEach(function (id) { $(id).onchange = go; });
  if ($('sc-preset')) $('sc-preset').onchange = function (e) { var pr = presets[Number(e.target.value)]; if (!pr) return; SC.x = pr.x; SC.y = pr.y; SC.c = pr.color || 'team'; drawView(); };
}

/* Leaders: small multiples on the view's key metrics, each with a dot strip of the group */
function leadersView(host) {
  var v = view(), rows = shown(), P = peers();
  var ids = keyMetrics(v);
  var noun = grpNoun();
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + grpName(), title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + esc(noun) + ' on screen on the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics. Bars are percentiles against the ' + P.length + ' in the peer group; the strip under each card is everyone on screen, with the median dashed' + (String(SC.q || '').trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map(function (id, i) {
      var m = mmeta(id);
      var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
      if (!list.length) return '';
      var item = function (r, rk) { var p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      var top = list.slice(0, 5).map(function (r, j) { return item(r, j + 1); });
      var bottom = !TOTALS.test(id) && !m.style && list.length > 10 ? list.slice(-3).map(function (r, j) { return item(r, list.length - 2 + j); }) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + noun, top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach(function (id, i) {
    var el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    var m = mmeta(id);
    var vals = rows.filter(function (r) { return isNum(val(r, id)); }).map(function (r) { return { v: val(r, id), name: r.name + ' · ' + CC.tabbr(SC.L, r.team), id: r.id, hl: matches(r) || r.id === SC.p }; });
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + noun.replace(/s$/, '') + ' on ' + m.label, onClick: function (d) { openProfile(d.id); } });
  });
}

/* Draft prospects (round 9, Phase 4; football): the draft-eligible players (juniors and seniors, three seasons out of
   high school) at each position, ranked by the position view's value metric among the qualified players of the
   position, with their percentile there and the position's leading excellence metric. Our numbers only: no recruiting,
   combine or draft data. The filters above (conference, team, minimum) still apply; the year filter does not. */
function prospectsView(host) {
  var elig = function (r) { return /^(JR|SR|GR|5)/i.test(String(r.cls || '')); };
  var cards = posGroups().filter(function (x) { return x.code !== 'K' && x.code !== 'P'; }).map(function (x, i) {
    var c = 'p:' + x.code, v = view(c), P = peers(c);
    var key = v.color || (v.sets.filter(function (st) { return st.key === 'aggregate'; })[0] || { ids: [] }).ids[0];
    var ex = (v.sets[0] || { ids: [] }).ids.filter(function (id) { return id !== key; })[0];
    if (!key) return '';
    var m = mmeta(key), me = ex ? mmeta(ex) : null;
    var list = P.filter(function (r) { return elig(r) && (!SC.team || r.team === SC.team) && (!SC.conf || String((CC.team(SC.L, r.team) || {}).conference) === SC.conf) && isNum(val(r, key)); })
      .sort(function (a, b) { return val(b, key) - val(a, key); }).slice(0, 6);
    if (!list.length) return '';
    return QK.leaderCard({ kicker: x.g.d, title: m.label, ours: m.ours, tip: m.tip, count: 'draft-eligible, of ' + P.length + ' qualified',
      top: list.map(function (r, j) { var p0 = pctOf(r, key, c); return { id: r.id, rank: j + 1, name: r.name, href: href(r), mark: teamOf(r), text: m.fmt(val(r, key)), w: p0, pctl: p0,
        sub: [CC.tabbr(SC.L, r.team), String(r.cls || '').toUpperCase(), me && isNum(val(r, ex)) ? me.label + ' ' + me.fmt(val(r, ex)) : ''].filter(Boolean).join(' · ') }; }) });
  }).join('');
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Draft prospects', title: 'The draft-eligible board', sub: 'Juniors and seniors at each position, ranked by our value per game among the qualified players of the position; the bar is their percentile there, and the line names the position’s first excellence number. Our numbers only: no recruiting, combine or draft data. Tap a name for the profile.' }) + '</div>' +
    (cards ? '<div class="qk-lc-grid">' + cards + '</div>' : QK.empty('No draft-eligible players pass these filters', 'Clear the team or conference filter.'));
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id) {
  var r = findRow(id);
  if (!r) return;
  SC.p = r.id; writeQuery();
  var c = inGroup(r) ? code() : codeOf(r);
  var v = view(c), P = peers(c);
  var row = function (id2) { var m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: m.style ? null : pctOf(r, id2, c), value: m.fmt(x), tip: m.tip, style: m.style }; };
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(row).filter(Boolean) }; });
  var t = teamOf(r);
  var statIds = [v.color, v.y, v.x].filter(function (x, i, a) { return x && a.indexOf(x) === i; });
  var stats = statIds.map(function (id2) { var m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: m.style ? null : pctOf(r, id2, c), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Games played', value: String(r.gp) });
  var keys = keyMetrics(v);
  var pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  var near = QK.within.similar(pool, r, keys, function (rr, k) { return val(rr, k); }, 5);
  var base = href(r), prog = CC.playerHref(SC.L, r.id) + '?view=progression';
  var inPeers = P.indexOf(r) >= 0;
  var html = QK.profile({
    kicker: posTxt(r) + ' · ' + (t.name || t.abbr),
    name: r.name, href: base,
    sub: [r.cls ? clsName(r.cls) : '', r.gp + ' games', CC.seasonLabel(SC.L, SC.S)].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: grpNoun(c) + ', ' + floorText(c) + (inPeers ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + QK.surname(r.name) + ' · ' + grpNoun(c), items: near.map(function (o) { return { name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) }; }) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: base }, { label: 'Progression', href: prog }, { label: near.length ? 'Compare with ' + QK.surname(near[0].row.name) : 'Compare', href: CC.compareHref(SC.L, SC.S, [r.id].concat(near.length ? [near[0].row.id] : [])) }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(grpNoun(c)) + ' in the peer group in ' + esc(CC.seasonLabel(SC.L, SC.S)) + '. “Most like” is the nearest five on the ' + (SC.within === 'pos' ? 'position view’s' : 'group’s') + ' metrics.'
  });
  var inner = QK.drawer.open({ html: html, label: r.name + ': profile', onClose: function () { SC.p = ''; writeQuery(); } });
  var pb = inner.querySelector('#sc-pf-pin');
  if (pb) pb.addEventListener('click', function () { pin(r); openProfile(r.id); });
  QK.$$('[data-pick]', inner).forEach(function (a) { a.addEventListener('click', function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'));
  }); });
}

/* ── the compare tray ───────────────────────────────────────────────────── */
function pin(r) {
  if (!TRAY) return;
  TRAY.toggle(r.id);
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(function (b) { var on = TRAY.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(function (id) { return findRow(id); }), label: 'Compare tray',
    item: function (id) { var r = findRow(id); return r ? { name: r.name, short: QK.surname(r.name), sub: posTxt(r) + ' · ' + CC.tabbr(SC.L, r.team), colour: teamOf(r).colour } : { name: id }; },
    onChange: function (ids) { SC.cmp = ids; writeQuery(); },
    href: function (ids) { return CC.compareHref(SC.L, SC.S, ids); }, hrefLabel: 'Full compare',
    body: trayBody
  });
}
function trayBody(ids) {
  var rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  var codes = rs.map(function (r) { return inGroup(r) ? code() : codeOf(r); });
  var v = view(codes[0]);
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(function (id) {
    var m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(function (r, i) { var x = val(r, id); return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) && !m.style ? pctOf(r, id, codes[i]) : null }; }) };
  }) }; });
  return QK.trayCompare({ entities: rs.map(function (r) { var t = teamOf(r); return { name: r.name, short: QK.surname(r.name), sub: posTxt(r) + ' · ' + t.abbr + ' · ' + r.gp + ' GP', colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own ' + (SC.within === 'pos' ? 'position' : 'group') + '’s peers past the floor (' + esc(CC.seasonLabel(SC.L, SC.S)) + '). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

/* ── the full compare page (#/<L>/compare; the Scouting Room's Compare tab and the tray's "Full compare"; was
 * lab?kind=compare). Round 13 (12 Nov 2026): position first.
 *   #/<L>/compare                 the level's main group (football: quarterbacks; otherwise the group with the most
 *                                 qualified players), its top two by value (hockey: goals above replacement)
 *   #/<L>/compare?g=<group id>    that spec group's top two (the position chips)
 *   #/<L>/compare?p=<pid>         the player and the one most like him in his own group (headline metrics)
 *   #/<L>/compare?p=<pid>,<pid>[,<pid>]  as picked
 * Two or three players side by side on the spec's headline set for their peer group (METRICS_SPEC.md: football by
 * position, basketball by role, hockey by position), percentiles against that group (the payload's group percentiles,
 * else worked out here against the group's qualified players, so a slim early-season or older file still ranks), the
 * better value bold; then where each sits in the group's distribution. Players from different groups fall back to the
 * catalogue's own numbers against all qualified players, with links to compare each with someone from his own group. */
var CMP_COL = ['wpA', 'wpB', 'c5'];
/* The type a player's best metric suggests (verdicts), by the spec's metric id. */
var CMP_TYPE = { value_pg: 'The most valuable', epa_play: 'The efficient one', sr_db: 'The steady passer', cmp_pct: 'The accurate passer', ypa: 'The big-play passer', td_rate: 'The touchdown maker', int_rate: 'The ball-protector',
  sr_rush: 'The steady runner', ypc: 'The big-play runner', rush_share: 'The workhorse', tgt_share: 'The go-to target', yptpa: 'The yardage machine', ypr: 'The deep threat', sr_tgt: 'The reliable target', havoc_pg: 'The disruptor', sacks_pg: 'The pass rusher',
  hurries_pg: 'The pass rusher', tkl_pg: 'The tackler', pd_pg: 'The ball hawk', tfl_pg: 'The backfield wrecker', def_int_pg: 'The ball hawk', fg_pct: 'The accurate kicker', r: 'The difference-maker', pts100: 'The scorer', ts_add: 'The efficient scorer',
  ast_pct: 'The playmaker', tov_pct: 'The careful one', fta100: 'The rim attacker', stl_pct: 'The pickpocket', trb_pct: 'The rebounder', orb_pct: 'The glass cleaner', blk_pct: 'The rim protector',
  gar_pg: 'The most valuable', pts_pg: 'The point producer', p1_pg: 'The play driver', sh_pg: 'The shooter', g_pg: 'The goal scorer', pm_rel: 'The two-way one', toi_pg: 'The workhorse', blk_pg: 'The shot blocker',
  sv_pct: 'The wall', gsaa: 'The wall', gaa: 'The stingy one', sa60: 'The busy one' };
/* the headline position of a level (else the group with the most qualified players) */
var CMP_MAIN = { cfb: 'cfb_qb' };
/* one of the group / the group in a sentence (the spec's display names are plural nouns, two are collective) */
var CMP_ONE = { 'Defensive line': 'defensive lineman', 'Defence': 'defenceman' };
var CMP_MANY = { 'Defensive line': 'defensive linemen', 'Defence': 'defencemen' };
function gOne(G) { return CMP_ONE[G.d] || String(G.d).toLowerCase().replace(/s$/, ''); }
function gMany(G) { return CMP_MANY[G.d] || String(G.d).toLowerCase(); }
function aOr(w) { return (/^[aeiou]/i.test(w) ? 'an ' : 'a ') + w; }
function lc1(s) { s = String(s || ''); return /^[A-Z][a-z]/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s; }
function listWords(a) { return a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1]; }
/* the Scouting Room's views as links, with Compare (the same row the room shows) */
function roomTabs(L, S, active) {
  var t = [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].concat(CC.fb(L) ? [['prospects', 'Draft prospects']] : []);
  return U.tabsHTML(t.map(function (x) { return { key: x[0], label: x[1], href: CC.scoutHref(L, S, x[0] === 'board' ? '' : 'view=' + x[0]) }; })
    .concat([{ key: 'compare', label: 'Compare', href: CC.href(L, 'compare', null, S) }]), active).replace('aria-label="Views"', 'aria-label="Scouting Room views"');
}
CC.compareFull = function (el, p) {
  var L = p.L, S = p.S, q = p.query || {};
  var ids = String(q.p || '').split(',').filter(Boolean).slice(0, 3);
  var head = function () { return U.head('Compare', 'Two or three players side by side on the metrics that best describe and predict their play, ranked against their own position group.', U.kicker(L, S)) + roomTabs(L, S, 'compare'); };
  el.innerHTML = head() + QK.skeleton('lines', 6);
  return Promise.all([CC.load(CC.path(L, S, 'players.json')), CC.season(L, S), CC.metrics(), CC.specP]).then(function (a) {
    if (!U.alive(el)) return;
    document.title = 'Compare players · ' + CC.LSHORT[L] + ' · The Quant Campus';
    var cat = a[0];
    if (!CC.ok(cat) || !Object.keys(cat.players || {}).length) { el.innerHTML = head() + U.missing('The player catalogue', cat); return; }
    var P = cat.players;
    Object.keys(P).forEach(function (k) { var nm = String((P[k] || {}).name || '').trim(); if (!nm || /^team$/i.test(nm) || Number(k) < 0) delete P[k]; });
    var meta = {}; (cat.metrics || []).forEach(function (m) { meta[m.key] = m; });
    var vals = function (id) { return (P[id] && P[id].values) || {}; };

    /* the level's peer groups, their members and their qualified players */
    var GS = (CC.METRICS || []).filter(function (g) { return g.L === L && g.e === 'player'; });
    var members = {}, gOf = {};
    GS.forEach(function (G) { members[G.id] = []; });
    Object.keys(P).forEach(function (k) { var G = CC.group(L, 'player', P[k]); if (G && members[G.id]) { members[G.id].push(k); gOf[k] = G; } });
    var qual = function (id, G) { var x = P[id], f = G && G.min ? G.min.f : 'qualified'; if (x[f] === true || x[f] === false) return x[f]; return x.qualified !== false; };
    var QC = {};
    var qualified = function (G) { if (!QC[G.id]) QC[G.id] = members[G.id].filter(function (k) { return qual(k, G); }); return QC[G.id]; };
    var headIds = function (G) { return G.m.filter(function (m) { return m.set === 'h' && !m.style; }).map(function (m) { return m.id; }); };
    /* value first (the site's own value model; hockey: goals above replacement), else the first headline metric most
       of the group has */
    var rankKey = function (G) {
      var ms = members[G.id], ks = (CC.hk(L) ? ['gar', 'gar_pg'] : ['value', 'value_pg']).concat(headIds(G));
      return ks.filter(function (k) { return ms.filter(function (id) { return isNum(vals(id)[k]); }).length >= 0.5 * ms.length; })[0] || null;
    };
    var RC = {};
    var ranked = function (G) {
      if (RC[G.id]) return RC[G.id];
      var k = rankKey(G), mm = k ? G.m.filter(function (m) { return m.id === k; })[0] : null, low = !!(mm && mm.low);
      var sc = function (id) { var v = k ? vals(id)[k] : null; return isNum(v) ? (low ? -v : v) : -1e12; };
      var by = function (x, y) { return sc(y) - sc(x); };
      var qs = qualified(G).slice().sort(by), inQ = {};
      qs.forEach(function (id) { inQ[id] = 1; });
      return (RC[G.id] = qs.concat(members[G.id].filter(function (id) { return !inQ[id]; }).sort(by)));
    };
    var mainGroup = function () {
      var m = GS.filter(function (G) { return G.id === CMP_MAIN[L]; })[0];
      if (m && members[m.id].length >= 2) return m;
      return GS.slice().sort(function (x, y) { return (qualified(y).length - qualified(x).length) || (members[y.id].length - members[x.id].length); })[0] || null;
    };
    /* the player most like id within his group (the headline metrics on standard scores), else the group's best */
    var similarOf = function (id, G) {
      var pool = qualified(G).indexOf(id) >= 0 ? qualified(G) : qualified(G).concat([id]);
      var rows = pool.map(function (k) { return { id: k, v: vals(k) }; });
      var tgt = rows.filter(function (r) { return r.id === id; })[0];
      var hit = QK.within.similar(rows, tgt, headIds(G), function (r, k) { return r.v[k]; }, 1)[0];
      return hit ? hit.row.id : (ranked(G).filter(function (k) { return k !== id; })[0] || null);
    };

    var gq = q.g ? GS.filter(function (G) { return G.id === q.g; })[0] || null : null;
    ids = ids.filter(function (id, i, all) { return P[id] && all.indexOf(id) === i; });
    if (!ids.length) { var G0 = gq || mainGroup(); ids = G0 ? ranked(G0).slice(0, 2) : []; }
    else if (ids.length === 1 && gOf[ids[0]]) { var s1 = similarOf(ids[0], gOf[ids[0]]); if (s1) ids.push(s1); }
    var E = ids.map(function (id) { return { id: id, p: P[id], G: gOf[id] || null }; });
    var AG = E.length ? E[0].G : (gq || mainGroup());
    var same = !!AG && E.every(function (e) { return e.G === AG; });

    /* percentiles: the payload's group percentile, else worked out here against the pool's qualified players */
    var LOC = {}, usedLocal = false;
    var pctl = function (e, key, pool, pcKey, low) {
      var pc = (e.p[pcKey] || {})[key];
      if (isNum(pc)) return pc;
      var ck = pcKey + '|' + key, srt = LOC[ck];
      if (!srt) srt = LOC[ck] = pool.map(function (id) { return vals(id)[key]; }).filter(isNum).sort(function (x, y) { return x - y; });
      var v = (e.p.values || {})[key];
      if (!isNum(v) || srt.length < 5) return null;
      usedLocal = true;
      var r = QK.pctRank(srt, v);
      return low ? 100 - r : r;
    };

    /* the position strip: one chip per spec group, the key metrics in words, the early-season line */
    var posTxt = function (x) { return CC.fb(L) ? (x.pos || '') : CC.hk(L) ? CC.posName(L, x.pos) : x.role ? CC.posName(L, x.role) : CC.posName(L, x.pos); };
    var chips = '<div class="qk-chips cc-cmp-chips" role="group" aria-label="Position">' + GS.map(function (G) {
      var n = qualified(G).length, tot = members[G.id].length, on = same && G === AG;
      return '<button type="button" class="qk-chip" data-g="' + esc(G.id) + '" aria-pressed="' + on + '"' + (tot < 2 ? ' disabled title="No ' + esc(gMany(G)) + ' in this season’s numbers yet"' : ' title="' + n + ' qualified ' + esc(gMany(G)) + '"') + '>' +
        esc(G.d) + ' <span class="n">' + n + '</span></button>';
    }).join('') + '</div>';
    var KG = same ? AG : null;
    var keyLine = KG ? '<p class="cc-cmp-key"><b>' + esc(KG.d) + ':</b> ' + esc(listWords(KG.m.filter(function (m) { return m.set === 'h'; }).slice(0, 8).map(function (m) { return lc1(CC.uk(m.d)); }))) +
      ' — the metrics that best describe and predict ' + esc(aOr(gOne(KG))) + '.</p>' : '';
    var prev = CC.seasons(L).filter(function (s) { return s < Number(S); })[0];
    var thin = '';
    if (KG && qualified(KG).length < 20) {
      var nq = qualified(KG).length;
      thin = '<p class="cc-cmp-thin">' + (CC.isCur(L, S) ? 'Early in the season: only ' + nq + ' qualified ' + esc(gMany(KG)) + ' so far; percentiles settle as games are played.' : 'Only ' + nq + ' qualified ' + esc(gMany(KG)) + ' this season, so the percentiles are rough.') +
        (prev ? ' <a class="qk-link" href="' + esc(CC.href(L, 'compare', null, prev, 'g=' + encodeURIComponent(KG.id))) + '">Last season (' + esc(CC.seasonLabel(L, prev)) + ') →</a>' : '') + '</p>';
    }
    var instead = '';
    if (E.length >= 2 && !same) {
      var seen = {};
      var links = E.filter(function (e) { if (!e.G || seen[e.G.id]) return false; seen[e.G.id] = 1; return true; }).map(function (e) {
        var s2 = similarOf(e.id, e.G);
        return s2 ? '<a class="qk-link" href="' + esc(CC.compareHref(L, S, [e.id, s2])) + '">Compare ' + esc(e.p.name) + ' with ' + esc(aOr(gOne(e.G))) + ' instead&nbsp;→</a>' : '';
      }).filter(Boolean);
      instead = '<p class="cc-cmp-instead"><b>Different positions</b> (' + esc(E.map(function (e) { return QK.surname(e.p.name || '') + ': ' + (e.G ? gOne(e.G) : posTxt(e.p)); }).join(', ')) + '), so each is ranked against all qualified players. ' + links.join(' <span aria-hidden="true">·</span> ') + '</p>';
    }

    /* the name boxes: the active group's qualified players first (best first), then every other qualified player */
    var labelOf = function (k) { var x = P[k]; return x.name + ' (' + CC.tabbr(L, x.team) + ', ' + posTxt(x) + ')'; };
    var first = AG ? ranked(AG).filter(function (k) { return qual(k, AG); }) : [], inF = {};
    first.forEach(function (k) { inF[k] = 1; });
    var rest = Object.keys(P).filter(function (k) { return !inF[k] && (P[k].qualified !== false || ids.indexOf(k) >= 0); }).map(function (k) { return [k, labelOf(k)]; }).sort(function (x, y) { return x[1].localeCompare(y[1]); });
    ids.forEach(function (k) { if (!inF[k] && !rest.some(function (o) { return o[0] === k; })) rest.push([k, labelOf(k)]); });
    var opts = first.map(function (k) { return [k, labelOf(k)]; }).concat(rest);
    var lab = function (id) { var o = opts.filter(function (x) { return x[0] === id; })[0]; return o ? o[1] : ''; };
    var picker = '<div class="cc-cmp-pick">' + [0, 1, 2].map(function (i) { return '<label class="cc-cmp-slot" style="--ec:var(--' + ['wp-a', 'wp-b', 'c-5'][i] + ')"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span><input class="qk-input" list="cmp-names" data-i="' + i + '" value="' + esc(ids[i] ? lab(ids[i]) : '') + '" placeholder="Type a name" autocomplete="off"></label>'; }).join('') +
      '<datalist id="cmp-names">' + opts.map(function (o) { return '<option value="' + esc(o[1]) + '"></option>'; }).join('') + '</datalist></div>';
    var topCard = function () {
      return U.card('Position and players', 'Pick a position for its two best by value, or type names' + (AG ? ': suggestions start with qualified ' + esc(gMany(AG)) : ''), chips + keyLine + thin + instead + picker, { cls: 'cc-cmp-top' });
    };
    var html = head() + topCard();
    if (E.length < 2) {
      el.innerHTML = html + QK.empty('Pick at least two players', 'Choose a position above, or type a name in each box.');
      wire();
      return;
    }

    var G = AG;
    var hs = same ? G.m.filter(function (m) { return m.set === 'h' && E.some(function (e) { return isNum((e.p.values || {})[m.id]); }); }) : [];
    var useSpec = same && hs.length >= 2;
    var samePos = E.every(function (e) { return e.p.pos === E[0].p.pos; });
    var peer = useSpec ? gMany(G) : samePos ? lc1(((cat.positions || {})[E[0].p.pos] || {}).label || E[0].p.pos) : 'all qualified players';
    var pcKey = useSpec ? G.pct : samePos ? 'pct_pos' : 'pct';
    var pool = useSpec ? qualified(G) : Object.keys(P).filter(function (k) { return P[k].qualified !== false && (!samePos || P[k].pos === E[0].p.pos); });
    var rowsOf = function (list) {
      return list.map(function (m) {
        var mt = meta[m.id || m.key] || { fmt: /pct|rate|share/.test(m.id || m.key) ? 'pct' : '2' }, key = m.id || m.key, low = !!(m.low || m.lower);
        return { key: key, style: !!m.style, label: CC.uk(m.d || m.label), tip: CC.uk(m.x || m.desc || '') + (CC.ours(key) ? ' Our model: ' + CC.ours(key).name + '.' : '') + (m.style ? ' Describes playing style, not how well.' : ''), better: low ? 'low' : 'high',
          values: E.map(function (e) { return (e.p.values || {})[key]; }), pctls: m.style ? E.map(function () { return null; }) : E.map(function (e) { return pctl(e, key, pool, pcKey, low); }), fmt: function (v) { return CC.fmtMetric(mt, v); } };
      });
    };
    var groups = useSpec ? [{ label: 'Headline: ' + gMany(G), rows: rowsOf(hs) }, { label: 'More', rows: rowsOf(G.m.filter(function (m) { return m.set === 's' && E.some(function (e) { return isNum((e.p.values || {})[m.id]); }); }).slice(0, 6)) }].filter(function (g) { return g.rows.length; })
      : [{ label: 'Season numbers', rows: rowsOf((cat.metrics || []).slice(0, 10)) }];
    /* two players draw the tale of the tape in their team colours (QK.tape via QK.compareView); three keep the table */
    var ents = E.map(function (e) { return { name: e.p.name, short: QK.surname(e.p.name || '') || e.p.name, href: CC.playerHref(L, e.id, S), colour: CC.traw(L, e.p.team), alt: CC.talt(L, e.p.team) || undefined, sub: [CC.tabbr(L, e.p.team), posTxt(e.p), isNum(e.p.gp) ? e.p.gp + ' GP' : ''].filter(Boolean).join(' · ') }; });
    /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
    var short = E.map(function (e) { return QK.surname(e.p.name || ''); });
    var verd = E.map(function (e, i) {
      var bd = 0, br = null;
      groups[0].rows.forEach(function (r) {
        var mine = r.pctls[i]; if (!isNum(mine) || r.style) return;
        var dd = mine - Math.max.apply(null, r.pctls.filter(function (_, j) { return j !== i; }).map(function (v) { return isNum(v) ? v : 0; }));
        if (dd > bd) { bd = dd; br = r; }
      });
      return br ? { title: CMP_TYPE[br.key] || 'The standout', who: short[i], text: 'best of the ' + E.length + ' on ' + lc1(br.label) + ' (' + br.fmt(br.values[i]) + ', ' + QK.ordinal(Math.round(br.pctls[i])) + ' percentile).' } : null;
    });
    var qq = short.length === 2 ? short[0] + ' or ' + short[1] + '?' : short.slice(0, -1).join(', ') + ' or ' + short[short.length - 1] + '?';
    var notes = [];
    if (usedLocal) notes.push('Percentiles worked out on this page against the ' + pool.length + ' qualified ' + esc(peer) + ' in this season’s numbers.');
    if (!useSpec) notes.push(same || samePos ? 'This season’s numbers do not carry the key rates for ' + esc(G ? gMany(G) : 'this group') + ', so the season’s box-score numbers are shown.' : 'Different positions: percentiles are against all qualified players, so position effects stay in. Pick one position above for its key metrics.');
    html += '<section class="qk-section" style="margin-top:var(--sp-8)">' + QK.sectionHead({ kicker: 'Side by side', title: esc(qq), html: true, sub: (E.length === 2 ? 'Bar length = percentile against ' : 'Value and percentile against ') + esc(peer) + ' (100 = best). ' + (E.length === 2 ? 'The better number in each row is solid.' : 'The best in each row is highlighted.') }) +
      U.card(E.length + ' players, one metric set', useSpec ? 'The key metrics for ' + esc(gMany(G)) + ' from our metrics spec: stable and predictive rates first' : 'The season’s box-score numbers',
      QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) + notes.map(function (n) { return '<p class="cc-note">' + n + '</p>'; }).join('')) + '</section>';
    var dm = useSpec ? hs.filter(function (m) { return !m.style; }).slice(0, 4).map(function (m) { return [m.id, CC.uk(m.d), !!m.low]; }) : (cat.metrics || []).slice(0, 4).map(function (m) { return [m.key, m.label, !!m.lower]; });
    html += '<section class="qk-section">' + U.card('Where they sit', 'Every qualified ' + esc(useSpec ? gOne(G) : peer === 'all qualified players' ? 'player' : peer) + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px">' +
      dm.map(function (o, i) { return '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + esc(o[0]) + '">' + esc(o[1]) + '</button>'; }).join('') + '</div>' + U.chart('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
    el.innerHTML = html;
    wire();
    var dd = function (key) {
      var o = dm.filter(function (x) { return x[0] === key; })[0] || [key, key, false];
      var vs = pool.map(function (k) { return vals(k)[key]; }).filter(isNum).sort(function (x, y) { return x - y; });
      if (vs.length < 10) { QK.$('#cmp-dist', el).innerHTML = QK.empty('Too few qualified peers yet', 'The distribution appears with ten or more' + (vs.length ? ' (' + vs.length + ' so far)' : '') + '.'); return; }
      var mt = meta[key] || { fmt: '2' };
      QKC.distribution('#cmp-dist', { values: vs, binCount: 22, lowerBetter: o[2], colorBy: 'flat', fmt: function (v) { return CC.fmtMetric(mt, v); }, xName: o[1] + ' · ' + vs.length + ' qualified peers', yName: 'Players',
        marks: E.map(function (e, i) { return { x: (e.p.values || {})[key], label: QK.surname(e.p.name || ''), color: CMP_COL[i] }; }).filter(function (x) { return isNum(x.x); }), label: 'Distribution of ' + o[1] });
    };
    if (dm.length) { dd(dm[0][0]); QK.seg(QK.$('#cmp-dist-m', el), dd); }
    function wire() {
      QK.$$('.cc-cmp-chips [data-g]', el).forEach(function (b) {
        b.addEventListener('click', function () { if (!b.disabled) CC.go(CC.href(L, 'compare', null, S, 'g=' + encodeURIComponent(b.getAttribute('data-g')))); });
      });
      QK.$$('.cc-cmp-pick input', el).forEach(function (inp) {
        inp.addEventListener('change', function () {
          var pick = [0, 1, 2].map(function (i) {
            var v = ((QK.$('.cc-cmp-pick input[data-i="' + i + '"]', el) || {}).value || '').trim();
            var hit = opts.filter(function (o) { return o[1] === v; })[0] || (v ? opts.filter(function (o) { return o[1].toLowerCase().indexOf(v.toLowerCase()) === 0; })[0] : null);
            return hit ? hit[0] : null;
          }).filter(Boolean);
          if (pick.length) CC.go(CC.compareHref(L, S, pick));
        });
      });
    }
  });
};

CC.route('scout', render);
CC.scout = { prep: prep };
})(window.CC);
