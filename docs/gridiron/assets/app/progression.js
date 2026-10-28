/* The Quant Gridiron — progression (round 6): the player page's "Progression" tab (#/player/<pid>?view=progression) and
 * Compare progression (#/compare/progression/<a>/<b>[/<c>/<d>]?m=<metric>&x=season|age|year&y=value|pct).
 *
 * The Gridiron adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"), laid out by
 * assets/app/qk-progview.js (QPV). Reads the career file's season rows (seasons[].dv / dp / pg: the deep set's values and
 * percentiles against that season's qualified players of the spec group, aligned to prog.keys[group]; defenders by
 * role: EDGE, DL, LB, CB, S; oddsmarkets/nfl/analytics/careers.py), data/progression_ref.json (each season's peers:
 * the median and the middle half) and the spec's labels (QK.spec). Seasons from 1999 (play-by-play); NGS, participation
 * and charting metrics where those seasons have them. */
(function (GI) {
'use strict';
if (!GI || !window.QPV) return;
const QK = window.QK, QPV = window.QPV, esc = GI.esc, isNum = GI.isNum;

const PEER = { qb: 'quarterbacks', rb: 'running backs', wr: 'wide receivers', te: 'tight ends', edge: 'edge rushers', idl: 'interior linemen',
  lb: 'linebackers', cb: 'cornerbacks', s: 'safeties', k: 'kickers', p: 'punters' };
const N_OF = { QB: ['att', 'attempts'], RB: ['carries', 'carries'], WR: ['targets', 'targets'], TE: ['targets', 'targets'], DEF: ['games', 'games'],
  K: ['fga', 'field-goal tries'], P: ['punts', 'punts'] };
let REF_P = null;
function refJson() { if (!REF_P) REF_P = GI.load('progression_ref.json'); return REF_P; }

/* the route: compare/progression first (before compare/:a/:b/:c) */
[['compare/progression/:a/:b/:c/:d', 'compare-progression'], ['compare/progression/:a/:b/:c', 'compare-progression'], ['compare/progression/:a/:b', 'compare-progression'],
  ['compare/progression/:a', 'compare-progression'], ['compare/progression', 'compare-progression']].reverse().forEach(r => {
  GI.ROUTES.unshift({ pattern: r[0], segs: r[0].split('/'), name: r[1], section: 'lab' });
});
const compareHref = QPV.hrefFor('#/compare/progression/');

function kindOf(c) {
  const rows = (c.seasons || []).filter(r => r.dv);
  return rows.length ? rows[rows.length - 1].group : (c.group || 'QB');
}
function toP(c) {
  const keys = (c.prog || {}).keys || {};
  const cur = GI.currentSeason(), ph = GI.phase();
  const inProgress = !/final|off/i.test(ph);
  const rows = (c.seasons || []).filter(r => isNum(r.season)).sort((a, b) => a.season - b.season);
  return { id: String(c.id), name: c.name, short: GI.surnameOf(c.name || '') || c.name, kind: kindOf(c),
    seasons: rows.map((r, i) => {
      const ks = keys[r.group] || [];
      const v = QPV.zip(ks, r.dv), pc = QPV.zip(ks, r.dp);
      const nk = N_OF[r.group] || ['games', 'games'];
      const n = nk[0] === 'games' ? r.games : first(r[nk[0]], v[nk[0]]);
      const t = r.team ? GI.canonTeam(r.team) : null;
      return { key: String(r.season), x: Number(r.season), label: String(r.season), age: isNum(r.age) ? r.age : null, cy: i + 1,
        team: t ? { abbr: GI.teamAbbr(t), name: GI.teamName(t), colour: GI.teamInfo(t).colour } : null,
        group: r.pg || null, n: isNum(n) ? n : null, nUnit: nk[1], small: !(r.dp && r.dp.length), values: v, pct: pc,
        partial: Number(r.season) === cur && inProgress };
    }) };
}
function first(a, b) { return isNum(a) ? a : b; }
function peerOf(P) { const s = P.seasons.slice().reverse().find(x => x.group) || {}; return PEER[s.group] || 'players'; }
function groupOf(P) { return (P.seasons.slice().reverse().find(x => x.group) || {}).group; }
function metricsFor(keys, cat, grp) {
  const head = cat && grp ? cat.headline(grp) : [];
  return QPV.metrics(keys, cat, { head: head });
}

function tab(el, params) {
  const pid = String(params.id || '');
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([GI.loadPlayer(pid), refJson(), QK.spec.load('nfl')]).then(res => {
    if (!el.isConnected) return;
    const c = GI.ok(res[0]) ? res[0] : null, ref = res[1], cat = res[2];
    if (!c) { el.innerHTML = QK.empty('No career file for this player', 'Player pages are built for everyone in a season catalogue since 1999.'); return; }
    document.title = c.name + ' · Progression · ' + GI.SITE;
    const P = toP(c), grp = groupOf(P), peer = peerOf(P);
    const ms = metricsFor(((c.prog || {}).keys || {})[P.kind] || [], cat, grp);
    const head = (cat && grp ? cat.headline(grp) : []).map(id => ms.find(m => m.id === id)).filter(Boolean);
    const R = QK.prog.ref(ref);
    const base = GI.playerHref(pid);
    const lastS = P.seasons[P.seasons.length - 1] || {};
    const sims = (c.similar || []).map(r => (Array.isArray(r) ? { id: String(r[0]), name: GI.surnameOf(r[1] || '') || r[1] } : { id: String(r.pid), name: r.name })).filter(s => s.id && s.id !== pid);
    QPV.tab(el, { P: P, metrics: ms, head: head, cat: cat, peer: peer, nUnit: (N_OF[P.kind] || [0, 'games'])[1],
      tabs: [['overview', 'Overview', base], ['progression', 'Progression', base + '?view=progression']],
      kicker: 'Progression · NFL' + (lastS.team ? ' · ' + lastS.team.name : ''), title: esc(c.name),
      sub: P.seasons.length + ' season' + (P.seasons.length === 1 ? '' : 's') + ' in the data, each against that season’s qualified ' + esc(peer) + '. Play-by-play numbers run from 1999; Next Gen Stats and participation from 2016, charting from 2022.',
      key: ms.find(m => m.id === 'gvar_pg') || null,
      ref: (S, id) => (S.group ? R(S.group, S.key, id) : null),
      compare: { sims: sims, href: compareHref } });
  });
}

function compare(el, params) {
  const q = params.query || {};
  let ids = [params.a, params.b, params.c, params.d].filter(Boolean).map(String);
  ids = ids.filter((x, i) => ids.indexOf(x) === i).slice(0, 4);
  el.innerHTML = QK.skeleton('chart', 1);
  let fill = Promise.resolve(ids);
  if (!ids.length) fill = Promise.resolve(['00-0033873', '00-0034857']);
  else if (ids.length === 1) fill = GI.loadPlayer(ids[0]).then(c => ids.concat(((c && c.similar) || []).slice(0, 1).map(r => String(Array.isArray(r) ? r[0] : r.pid))));
  return fill.then(list => Promise.all([Promise.all(list.map(id => GI.loadPlayer(id))), refJson(), QK.spec.load('nfl'), GI.ensureNames()]).then(res => {
    if (!el.isConnected) return;
    const cs = res[0].filter(c => GI.ok(c)), cat = res[2], idx = res[3] || {};
    const Ps = cs.map(toP);
    const keys = [];
    cs.forEach(c => { const P = Ps[cs.indexOf(c)]; (((c.prog || {}).keys || {})[P.kind] || []).forEach(k => { if (keys.indexOf(k) < 0) keys.push(k); }); });
    const grp = Ps.length ? groupOf(Ps[0]) : null;
    const ms = metricsFor(keys, cat, grp);
    const hd = cat && grp ? cat.headline(grp) : [];
    const R = QK.prog.ref(res[1]);
    const sugg = [];
    cs.forEach(c => (c.similar || []).forEach(r => {
      const id = String(Array.isArray(r) ? r[0] : r.pid), nm = Array.isArray(r) ? r[1] : r.name;
      if (Ps.length < 4 && !Ps.some(P => P.id === id) && !sugg.some(s => s.id === id)) sugg.push({ id: id, name: nm, sub: 'Plays most like ' + c.name, href: compareHref(Ps.map(P => P.id).concat([id]), '') });
    }));
    const names = Object.keys(idx).filter(k => Array.isArray(idx[k]) && (idx[k][4] || 0) >= 2006).map(k => [k, idx[k][0] + ' (' + (idx[k][2] || '') + (idx[k][1] ? ', ' + idx[k][1] : '') + ')'])
      .sort((a, b) => a[1].localeCompare(b[1]));
    document.title = 'Compare progression · ' + GI.SITE;
    QPV.compare(el, { players: Ps, metrics: ms, cat: cat, metric: q.m || (hd.find(id => ms.some(m => m.id === id)) || (ms[0] || {}).id), x: q.x, y: q.y,
      ref: (P, S, id) => (S.group ? R(S.group, S.key, id) : null), peerName: P => peerOf(P), suggest: sugg,
      cyNote: 'Career year counts NFL seasons in our data (from 1999).', kicker: 'Compare progression · NFL',
      actions: '<a class="qk-btn" href="' + esc(GI.compareHref(Ps[0] ? Ps[0].id : '', Ps[1] ? Ps[1].id : '')) + '">Compare this season</a>',
      href: compareHref, names: names });
  }));
}

GI.route('compare-progression', compare);
GI.progression = { tab: tab, compare: compare, toP: toP, compareHref: compareHref };
})(window.GI);
