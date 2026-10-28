/* The Quant Campus — progression (round 6): the player page's "Progression" tab (#/<L>/player/<pid>?view=progression)
 * and Compare progression (#/<L>/compare/progression/<a>/<b>[/<c>/<d>]?m=<metric>&x=season|year&y=value|pct), for
 * CFB, men's and women's basketball.
 *
 * The Campus adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"), laid out by
 * assets/js/qk-progview.js (QPV). Reads the career file's season rows (seasons[].dv / dp / pg: the spec group's deep
 * set, CFB by position (value per game, EPA per play, success, completion, yards per attempt, target share, havoc ...),
 * hoops by role (rating per 100, points per 100, scoring added, assist, turnover, rebound, steal and block rates);
 * percentiles against that season's qualified players of the group; oddsmarkets/college/progression.py),
 * data/<L>/progression_ref.json (each season's peers: the median and the middle half) and the spec's labels.
 * College careers carry no dates of birth, so careers line up by season or by year in college. */
(function (CC) {
'use strict';
if (!CC || !window.QPV) return;
var QK = window.QK, QPV = window.QPV, esc = QK.esc, isNum = QK.isNum;
var REF_P = {};
function refJson(L) { if (!REF_P[L]) REF_P[L] = CC.load(CC.lpath(L, 'progression_ref.json')); return REF_P[L]; }
var PEER = { cfb_qb: 'quarterbacks', cfb_rb: 'running backs', cfb_wr: 'wide receivers', cfb_te: 'tight ends', cfb_dl: 'defensive linemen', cfb_lb: 'linebackers',
  cfb_db: 'defensive backs', cfb_k: 'kickers', cfb_p: 'punters', guards: 'guards', wings: 'wings', bigs: 'bigs' };
var ROLE = { guards: 'G', wings: 'W', bigs: 'B' };
var N_CFB = { QB: ['att', 'attempts'], RB: ['car', 'carries'], WR: ['tgt', 'targets'], TE: ['tgt', 'targets'] };
var LABELS = { db: 'Dropbacks', epa: 'EPA (total)', value: 'Value (total)', min: 'Minutes per game', pts: 'Points per game', fga_pg: 'Field-goal tries per game', fg_long: 'Longest field goal' };
function compareHref(L) { return QPV.hrefFor('#/' + L + '/compare/progression/'); }
function kindOfPg(L, pg) { if (!pg) return null; var s = String(pg).split('_'); return L === 'cfb' ? String(s[1] || '').toUpperCase() : ROLE[s[1]] || null; }
function peerOf(P) { var s = P.seasons.slice().reverse().filter(function (x) { return x.group; })[0] || {}; var g = String(s.group || ''); return PEER[g] || PEER[g.split('_')[1]] || 'players'; }
function groupOf(P) { return (P.seasons.slice().reverse().filter(function (x) { return x.group; })[0] || {}).group; }

function toP(L, d) {
  var keys = (d.prog || {}).keys || {}, fb = CC.fb(L), cur = CC.cur(L);
  var rows = (Array.isArray(d.seasons) ? d.seasons : []).filter(function (r) { return isNum(r.season); }).sort(function (a, b) { return a.season - b.season; });
  var last = rows.filter(function (r) { return r.pg; }).slice(-1)[0];
  var kind = last ? kindOfPg(L, last.pg) : null;
  return { id: String(d.id), name: d.name, short: QK.surname(d.name || '') || d.name, kind: kind,
    seasons: rows.map(function (r, i) {
      var k = kindOfPg(L, r.pg), ks = keys[k] || [];
      var t = r.team ? CC.team(L, r.team) : null;
      var nk = fb ? (N_CFB[k] || ['gp', 'games']) : ['gp', 'games'];
      return { key: String(r.season), x: Number(r.season), label: CC.seasonLabel(L, r.season), age: null, cy: i + 1,
        team: t ? { abbr: t.abbr || t.short, name: t.short || t.name, colour: t.colour } : null,
        group: r.pg || null, n: isNum(r[nk[0]]) ? r[nk[0]] : null, nUnit: nk[1], small: !(r.dp && r.dp.length), values: QPV.zip(ks, r.dv), pct: QPV.zip(ks, r.dp),
        partial: Number(r.season) === Number(cur) };
    }) };
}
function metricsFor(keys, cat, grp) { return QPV.metrics(keys, cat, { head: cat && grp ? cat.headline(grp) : [], labels: LABELS }); }

function tab(el, p) {
  var L = p.L, pid = String(p.id || '');
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([CC.load(CC.lpath(L, 'players/' + pid + '.json')), refJson(L), QK.spec.load('college')]).then(function (res) {
    if (!el.isConnected) return;
    var d = CC.ok(res[0]) ? res[0] : null, cat = res[2];
    if (!d) { el.innerHTML = QK.empty('No career file for this player', 'Careers are kept for players with a game in the last two seasons.'); return; }
    document.title = d.name + ' · Progression · The Quant Campus';
    var P = toP(L, d), grp = groupOf(P), peer = peerOf(P);
    var ms = metricsFor(((d.prog || {}).keys || {})[P.kind] || [], cat, grp);
    var head = (cat && grp ? cat.headline(grp) : []).map(function (k) { return ms.filter(function (m) { return m.id === k; })[0]; }).filter(Boolean);
    var R = QK.prog.ref(res[1]);
    var base = CC.playerHref(L, pid);
    var lastS = P.seasons[P.seasons.length - 1] || {};
    var sims = (d.similar || []).filter(function (s) { return s && s.id && String(s.id) !== pid; }).map(function (s) { return { id: String(s.id), name: QK.surname(s.name || '') || s.name }; });
    QPV.tab(el, { P: P, metrics: ms, head: head, cat: cat, peer: peer, nUnit: (lastS.nUnit || 'games'),
      tabs: [['overview', 'Overview', base], ['progression', 'Progression', base + '?view=progression']],
      kicker: 'Progression · ' + CC.LSHORT[L] + (lastS.team ? ' · ' + lastS.team.name : ''), title: esc(d.name),
      sub: P.seasons.length + ' season' + (P.seasons.length === 1 ? '' : 's') + ' in the data, each against that season’s qualified ' + esc(peer) + (CC.fb(L) ? ' (FBS teams, the position’s volume floor).' : ' (the catalogue’s games and minutes floor, by role).') + ' College careers line up by season or by year in college.',
      key: ms.filter(function (m) { return m.id === (CC.fb(L) ? 'value_pg' : 'r'); })[0] || null,
      ref: function (S, k) { return S.group ? R(S.group, S.key, k) : null; },
      compare: { sims: sims, href: compareHref(L) } });
  });
}

function idsFromHash() {
  var h = String(location.hash || '').replace(/^#\/?/, '').split('?')[0].split('/').filter(Boolean).map(decodeURIComponent);
  var i = h.indexOf('progression');
  return i >= 0 ? h.slice(i + 1) : [];
}
function compare(el, p) {
  var L = p.L, q = p.query || {};
  var ids = idsFromHash().filter(function (x, i, a) { return /^\d+$/.test(x) && a.indexOf(x) === i; }).slice(0, 4);
  el.innerHTML = QK.skeleton('chart', 1);
  var fill = Promise.resolve(ids);
  if (ids.length === 1) fill = CC.load(CC.lpath(L, 'players/' + ids[0] + '.json')).then(function (d) { return ids.concat(((d && d.similar) || []).slice(0, 1).map(function (s) { return String(s.id); })); });
  return fill.then(function (list) {
    return Promise.all([Promise.all(list.map(function (x) { return CC.load(CC.lpath(L, 'players/' + x + '.json')); })), refJson(L), QK.spec.load('college'), CC.load('search.json')]).then(function (res) {
      if (!el.isConnected) return;
      var ds = res[0].filter(function (d) { return CC.ok(d) && d.name; }), cat = res[2];
      var Ps = ds.map(function (d) { return toP(L, d); });
      var kind = Ps.length ? Ps[0].kind : null, keys = [];
      ds.forEach(function (d) { ((((d.prog || {}).keys || {})[kind]) || []).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
      var grp = Ps.length ? groupOf(Ps[0]) : null;
      var ms = metricsFor(keys, cat, grp), hd = cat && grp ? cat.headline(grp) : [];
      var R = QK.prog.ref(res[1]);
      var href = compareHref(L);
      var sugg = [];
      ds.forEach(function (d) { (d.similar || []).forEach(function (s) {
        var id = String(s.id);
        if (Ps.length < 4 && !Ps.some(function (P) { return P.id === id; }) && !sugg.some(function (x) { return x.id === id; })) sugg.push({ id: id, name: s.name, sub: 'Closest profile to ' + d.name + (s.season ? ' (' + CC.seasonLabel(L, s.season) + ')' : ''), href: href(Ps.map(function (P) { return P.id; }).concat([id]), '') });
      }); });
      var pre = '#/' + L + '/player/';
      var names = (Array.isArray(res[3]) ? res[3] : []).filter(function (r) { return String(r.href || '').indexOf(pre) === 0; }).map(function (r) { return [r.href.slice(pre.length).split('?')[0], r.t + (r.s ? ' (' + String(r.s).split(' · ').slice(1).join(', ') + ')' : '')]; })
        .sort(function (a, b) { return a[1].localeCompare(b[1]); });
      var first = hd.filter(function (k) { return ms.some(function (m) { return m.id === k; }); })[0];
      document.title = 'Compare progression · The Quant Campus';
      QPV.compare(el, { players: Ps, metrics: ms, cat: cat, metric: q.m || first || (ms[0] || {}).id, x: q.x || 'year', y: q.y,
        ref: function (P, S, k) { return S.group ? R(S.group, S.key, k) : null; }, peerName: peerOf, suggest: sugg,
        cyNote: 'Career year counts seasons in our data: year 1 is the first season with a game (careers are kept for players active in the last two seasons).',
        kicker: 'Compare progression · ' + CC.LSHORT[L], href: href, names: names,
        sub: 'Two to four college careers on one chart: by season or by year in college, on any number of the position’s deep set, as the value or as a percentile against that season’s peers. Hollow dots are seasons under the sample floor.' });
    });
  });
}

CC.route('compare', function (el, p) {
  if (p.id === 'progression') return compare(el, p);
  if (CC.compareFull) return CC.compareFull(el, p);       /* #/<L>/compare?p=<pid>,<pid>: the full compare page (cc-scout.js) */
  el.innerHTML = QK.empty('Pick players to compare', 'Open a player page and use “Compare progression”, or the Scouting Room’s compare tray.');
  return null;
});
CC.progression = { tab: tab, compare: compare, toP: toP, compareHref: compareHref };
})(window.CC);
