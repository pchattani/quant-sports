/* The Quant Ace — progression (round 6): the player page's "Progression" tab (#/<T>/player/<pid>?view=progression) and
 * Compare progression (#/<T>/compare/progression/<a>/<b>[/<c>/<d>]?m=<metric>&x=season|age|year&y=value|pct).
 *
 * The Ace adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"), laid out by
 * assets/js/qk-progview.js (QPV). Reads the career file's year rows (seasons[].dv / dp / pg: the tour's deep set, Elo
 * overall and by surface, hold and break, the serve and return ratings, results and, where the year has match
 * statistics, the point-level serve and return rates; percentiles against that year's qualified players of the tour;
 * oddsmarkets/tennis/analytics/players.py `progression`), data/<T>/progression_ref.json (each year's peers: the median
 * and the middle half) and the spec's labels (QK.spec). ATP from 2000, WTA from 2007. */
(function (TA) {
'use strict';
if (!TA || !window.QPV) return;
const QK = window.QK, QPV = window.QPV, esc = QK.esc, isNum = QK.isNum;
const REF_P = {};
function refJson(T) { if (!REF_P[T]) REF_P[T] = TA.load(T + '/progression_ref.json'); return REF_P[T]; }
const F = () => TA.fk;
function compareHref(T) { return QPV.hrefFor('#/' + T + '/compare/progression/'); }
function tourName(T) { return T === 'wta' ? 'WTA' : 'ATP'; }

function toP(T, c) {
  const keys = ((c.prog || {}).keys || {})[T] || [];
  const curY = Number((F().tourInfo ? F().tourInfo(T) : {}).year) || new Date().getFullYear();
  const rows = (c.seasons || []).filter(r => isNum(r.year)).sort((a, b) => a.year - b.year);
  return { id: String(c.id), name: c.name, short: F().surname(c.name || '') || c.name,
    seasons: rows.map((r, i) => {
      const v = QPV.zip(keys, r.dv), pc = QPV.zip(keys, r.dp);
      const n = (r.w || 0) + (r.l || 0);
      return { key: String(r.year), x: Number(r.year), label: String(r.year), age: QPV.ageAt(c.dob, r.year), cy: i + 1, team: null,
        group: r.pg || null, n: n, nUnit: 'matches', small: !(r.dp && r.dp.length), values: v, pct: pc,
        partial: Number(r.year) === curY };
    }) };
}
function metricsFor(T, keys, cat) { return QPV.metrics(keys, cat, { head: cat ? cat.headline(T + '_all') : [] }); }
function sims(c) {
  return (c.h2h || []).slice(0, 3).map(r => ({ id: String(r[0]), name: F().surname(F().name(c.tour, String(r[0]))) }));
}

function tab(el, params, state) {
  const k = F(), T = k.T(params, state);
  const pid = String(params.id || '');
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([TA.load(T + '/players/' + pid + '.json'), refJson(T), QK.spec.load('tennis'), k.loadNames(T)]).then(res => {
    if (!k.alive(el)) return;
    const c = k.ok(res[0]) ? res[0] : null, cat = res[2];
    if (!c) { el.innerHTML = QK.empty('No career file for this player', 'Try the players list.'); return; }
    document.title = c.name + ' · Progression · The Quant Ace';
    const P = toP(T, c), peer = tourName(T) + ' players';
    const ms = metricsFor(T, ((c.prog || {}).keys || {})[T] || [], cat);
    const head = (cat ? cat.headline(T + '_all') : []).map(id => ms.find(m => m.id === id)).filter(Boolean);
    const R = QK.prog.ref(res[1]);
    const base = k.playerHref(T, pid);
    QPV.tab(el, { P: P, metrics: ms, head: head, cat: cat, peer: peer, nUnit: 'matches',
      tabs: [['overview', 'Overview', base], ['progression', 'Progression', base + '?view=progression']],
      kicker: 'Progression · ' + tourName(T) + (c.country ? ' · ' + c.country : ''), title: esc(c.name),
      sub: P.seasons.length + ' year' + (P.seasons.length === 1 ? '' : 's') + ' at tour level in the data, each against that year’s qualified ' + esc(peer) + '. Elo, hold and break run every year; the point-level serve and return numbers only where the year has match statistics' + (T === 'wta' ? ' (WTA from 2016).' : ' (none on the ATP).'),
      key: ms.find(m => m.id === 'elo') || null,
      ref: (S, id) => (S.group ? R(S.group, S.key, id) : null),
      compare: { sims: sims(c), href: compareHref(T) } });
  });
}

function compare(el, params, state) {
  const k = F(), T = k.T(params, state), q = params.query || {};
  let ids = [params.b].concat(params.rest || []).filter(Boolean).map(String);
  ids = ids.filter((x, i) => ids.indexOf(x) === i).slice(0, 4);
  el.innerHTML = QK.skeleton('chart', 1);
  const def = T === 'wta' ? ['15339', '10885'] : ['296', '104925'];
  let fill = Promise.resolve(ids.length ? ids : null);
  return k.loadNames(T).then(() => fill).then(list0 => {
    let list = list0;
    if (!list) {
      const N = k.NAMES[T] || {};
      list = Object.keys(N).filter(id => isNum(N[id].rank)).sort((a, b) => N[a].rank - N[b].rank).slice(0, 2);
      if (list.length < 2) list = def;
    }
    if (list.length === 1) return TA.load(T + '/players/' + list[0] + '.json').then(c => list.concat(((c && c.h2h) || []).slice(0, 1).map(r => String(r[0]))));
    return list;
  }).then(list => Promise.all([Promise.all(list.map(id => TA.load(T + '/players/' + id + '.json'))), refJson(T), QK.spec.load('tennis')]).then(res => {
    if (!k.alive(el)) return;
    const cs = res[0].filter(c => k.ok(c)), cat = res[2];
    const Ps = cs.map(c => toP(T, c));
    const keys = [];
    cs.forEach(c => (((c.prog || {}).keys || {})[T] || []).forEach(x => { if (keys.indexOf(x) < 0) keys.push(x); }));
    const ms = metricsFor(T, keys, cat), hd = cat ? cat.headline(T + '_all') : [];
    const R = QK.prog.ref(res[1]);
    const href = compareHref(T);
    const sugg = [];
    cs.forEach(c => (c.h2h || []).slice(0, 4).forEach(r => {
      const id = String(r[0]);
      if (Ps.length < 4 && !Ps.some(P => P.id === id) && !sugg.some(s => s.id === id)) sugg.push({ id: id, name: k.name(T, id), sub: 'Played ' + c.name + ' ' + (r[1] + r[2]) + ' times', href: href(Ps.map(P => P.id).concat([id]), '') });
    }));
    const N = k.NAMES[T] || {};
    const names = Object.keys(N).filter(id => N[id] && N[id].name).map(id => [id, N[id].name + (N[id].country ? ' (' + N[id].country + ')' : '')]).sort((a, b) => a[1].localeCompare(b[1]));
    document.title = 'Compare progression · The Quant Ace';
    QPV.compare(el, { players: Ps, metrics: ms, cat: cat, metric: q.m || (hd.find(id => ms.some(m => m.id === id)) || (ms[0] || {}).id), x: q.x, y: q.y,
      ref: (P, S, id) => (S.group ? R(S.group, S.key, id) : null), peerName: () => tourName(T) + ' players', suggest: sugg,
      cyNote: 'Career year counts years with tour-level matches in our data (ATP from 2000, WTA from 2007).', kicker: 'Compare progression · ' + tourName(T),
      actions: '<a class="qk-btn" href="' + esc(k.compareHref(T, Ps[0] ? Ps[0].id : '', Ps[1] ? Ps[1].id : '')) + '">Compare this year</a>',
      href: href, names: names });
  }));
}

TA.progression = { tab: tab, compare: compare, toP: toP, compareHref: compareHref };
})(window.TA);
