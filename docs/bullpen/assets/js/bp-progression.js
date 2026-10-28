/* The Quant Bullpen — progression (round 6): the player page's "Progression" tab (#/player/<pid>?view=progression,
 * also #/<L>/hitter/<pid>?view=progression and pitcher) and Compare progression
 * (#/compare/progression/<a>/<b>[/<c>/<d>]?kind=hitter|pitcher&m=<metric>&x=season|age|year&y=value|pct).
 *
 * The Bullpen adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"; the Rink adapter
 * rk-progression.js is the reference). Reads the player file's MLB season rows (seasons[].pr = { dv, dp, pg }: the
 * deep set's values and percentiles against that season's position group or role, aligned to prog.keys[kind];
 * oddsmarkets/baseball/analytics/careers.py), the Retrosheet-era rows in `history` (before 2015: the box score and
 * wOBA / WAR, no percentiles), data/mlb/progression_ref.json (each season's qualified peers: the median and the middle
 * half) and the spec's labels (QK.spec). Statcast metrics (xwOBA+, barrels, bat speed, Stuff+ ...) run from 2015.
 * A two-way player switches between hitting and pitching. */
(function (BP) {
'use strict';

const U = BP.ui, esc = BP.esc, isNum = BP.isNum;
const PEER = { hitters_C: 'catchers', hitters_1B: 'first basemen', hitters_2B: 'second basemen', hitters_3B: 'third basemen', hitters_SS: 'shortstops',
  hitters_CF: 'centre fielders', hitters_LFRF: 'corner outfielders', hitters_DH: 'designated hitters', hitters_all: 'hitters', sp: 'starting pitchers', rp: 'relief pitchers' };
/* a pitcher's numbers point the other way from a hitter's for these (the spec's SP / RP groups; the labels file keeps
   one direction per id, the hitters') */
const PITCH_DIR = { xwoba_n: 'lower', k_pct: 'higher', bb_pct: 'lower', chase_pct: 'higher', gb_pct: 'higher', whiff_pct: 'higher', swstr_pct: 'higher',
  xwoba_plus: 'lower', xwoba_savant: 'lower', hard_pct: 'lower', barrel_pct: 'lower', ev: 'lower' };
/* box-score metrics for every season (the Retrosheet era too) */
const BOX = {
  hitter: [['pa', 'Plate appearances', 'PA', 'higher'], ['hr', 'Home runs', 'HR', 'higher'], ['sb', 'Stolen bases', 'SB', 'higher'], ['ops', 'OPS', 'rate', 'higher']],
  pitcher: [['ip', 'Innings', 'IP', 'higher'], ['bf', 'Batters faced', 'BF', 'higher'], ['so', 'Strikeouts', 'K', 'higher']]
};
const RATE3 = /^(woba|xwoba_n|xwoba_plus|xwoba_savant|xslg|iso|obp|slg|avg|babip|ops|xwobacon_plus|babip_against|tto_penalty)$/;
let REF_P = null;
function refJson() { if (!REF_P) REF_P = BP.load('mlb/progression_ref.json'); return REF_P; }

function fmtOf(id, unit) {
  if (RATE3.test(id)) return v => (isNum(v) ? (v < 0 ? '−' : '') + Math.abs(v).toFixed(3).replace(/^0/, '') : '—');
  if (/^(stuff_plus|pitching_plus|location_plus|p_start|pa|hr|sb|bf|so)$/.test(id)) return v => (isNum(v) ? String(Math.round(v)) : '—');
  if (id === 'ip') return v => (isNum(v) ? (BP.fmtIP ? BP.fmtIP(v) : v.toFixed(1)) : '—');
  if (/^(war|war_x|war_600|war_200|bsr|fielding_runs|framing_runs|oaa|re24_pa|dv100|wpa_li)$/.test(id)) return v => (isNum(v) ? (v < 0 ? '−' : '') + Math.abs(v).toFixed(id === 're24_pa' ? 3 : 1) : '—');
  if (unit === '%') return v => (isNum(v) ? (v * 100).toFixed(1) + '%' : '—');
  return v => QK.prog.fmt(unit, v);
}
function metrics(keys, kind, cat) {
  const out = [];
  (keys || []).forEach(id => {
    const m = cat ? cat.metric(id, 'player') : null;
    let dir = m ? (m.style ? 'neutral' : m.dir) : 'higher';
    if (kind === 'pitcher' && PITCH_DIR[id]) dir = PITCH_DIR[id];
    out.push({ id: id, label: m && m.label && m.label !== id ? m.label : id, unit: m && m.unit && m.unit !== 'rate' ? m.unit : '', dir: dir, ours: m && m.ours ? m.ours : null,
      tip: cat ? cat.tip(id, 'player', '') : '', head: !!(m && m.set === 'h'), fmt: fmtOf(id, m && m.unit) });
  });
  (BOX[kind] || []).forEach(b => { if (b[1] && !out.some(m => m.id === b[0])) out.push({ id: b[0], label: b[1], unit: b[2], dir: b[3], ours: null, tip: '', head: false, box: true, fmt: fmtOf(b[0], b[2]) }); });
  return out;
}
/* the sides a player has a real career on (100+ PA or batters faced in an MLB season): a pitcher's few at-bats from the
   pre-DH National League do not make a hitter */
function kindsOf(pf) {
  const ks = Object.keys((pf.prog || {}).keys || {});
  const real = ks.filter(k => (pf.seasons || []).some(s => s.level === 'mlb' && s.kind === k && ((k === 'pitcher' ? s.bf : s.pa) || 0) >= 100));
  return real.length ? real : ks;
}
function defaultKind(pf) {
  const ks = kindsOf(pf), pos = String(pf.pos || '').toUpperCase();
  if (ks.length === 1) return ks[0];
  return (pos === 'P' || pos === 'SP' || pos === 'RP') ? 'pitcher' : 'hitter';
}
function ageAt(dob, season) {
  const d = dob ? new Date(String(dob).slice(0, 10) + 'T00:00:00Z') : null;
  if (!d || isNaN(d)) return null;
  return (Date.UTC(Number(season), 6, 1) - d.getTime()) / (365.25 * 864e5);
}
/* the Retrosheet-era rows (history.batting / history.pitching) as season rows with box values */
function historyRows(pf, kind) {
  const h = pf.history || {}, cols = (h.cols || {})[kind === 'pitcher' ? 'pitching' : 'batting'] || [], rows = h[kind === 'pitcher' ? 'pitching' : 'batting'] || [];
  return rows.map(r => {
    const o = {}; cols.forEach((c, i) => { o[c] = r[i]; });
    const v = {};
    if (kind === 'hitter') {
      Object.assign(v, { pa: o.pa, hr: o.hr, woba: o.woba, war: o.war });
      if (isNum(o.ab) && o.ab > 0) {
        v.avg = o.h / o.ab;
        const tb = (o.h - o.b2 - o.b3 - o.hr) + 2 * o.b2 + 3 * o.b3 + 4 * o.hr;
        v.slg = tb / o.ab; v.iso = v.slg - v.avg;
      }
      if (isNum(o.pa) && o.pa > 0) { v.k_pct = o.k / o.pa; v.bb_pct = o.bb / o.pa; }
    } else {
      const ip = isNum(o.outs) ? Math.floor(o.outs / 3) + (o.outs % 3) / 10 : null;
      Object.assign(v, { ip: ip, bf: o.bf, so: o.k, ra9: o.ra9, war: o.war });
      if (isNum(o.bf) && o.bf > 0) { v.k_pct = o.k / o.bf; v.bb_pct = o.bb / o.bf; v.k_bb_pct = (o.k - o.bb) / o.bf; }
      if (isNum(o.outs) && o.outs > 0) v.hr9 = o.hr / (o.outs / 3) * 9;
    }
    return { season: o.season, hist: true, values: v };
  }).filter(r => isNum(r.season));
}
/* a player file -> the kit's player shape, for one side (hitter or pitcher) */
function toP(pf, kind, ref) {
  const keys = ((pf.prog || {}).keys || {})[kind] || [];
  const cur = Number(BP.currentSeason('mlb'));
  const ph = String(BP.phase ? BP.phase('mlb') : '');
  const inProgress = /regular|pre|spring/i.test(ph);
  const lens = (ref && ref.seasons) || {};
  const mlb = (pf.seasons || []).filter(s => s.level === 'mlb' && s.kind === kind).sort((a, b) => a.season - b.season);
  const first = mlb.length ? mlb[0].season : 9999;
  const old = historyRows(pf, kind).filter(r => r.season < first);
  const rows0 = old.concat(mlb), rows = [];
  /* a season with no MLB games between two that have them (injury, the minors): an empty column, tagged */
  rows0.forEach((r, i) => {
    const prev = rows0[i - 1];
    if (prev) for (let y = prev.season + 1; y < r.season; y++) rows.push({ season: y, gap: true, values: {} });
    rows.push(r);
  });
  const S = rows.map((r, i) => {
    if (r.gap) return { key: String(r.season), x: Number(r.season), label: String(r.season), age: ageAt(pf.dob, r.season), cy: i + 1, team: null, group: null, small: true, gap: true, values: {}, pct: {}, short: { kind: 'absent', tag: 'No MLB', text: 'No MLB games this season' } };
    const pr = r.pr || {};
    const v = r.hist ? Object.assign({}, r.values) : Object.assign({}, r), pc = {};
    if (!r.hist) { ['level', 'season', 'kind', 'team', 'pos', 'pr', 'dv'].forEach(k => { delete v[k]; }); }
    (pr.dv || []).forEach((x, j) => { if (isNum(x) && keys[j]) v[keys[j]] = x; });
    (pr.dp || []).forEach((x, j) => { if (isNum(x) && keys[j]) pc[keys[j]] = x; });
    const len = (lens[String(r.season)] || {}).len || (r.season === 2020 ? 60 : 162);
    const n = kind === 'pitcher' ? v.bf : v.pa;
    return { key: String(r.season), x: Number(r.season), label: String(r.season), age: ageAt(pf.dob, r.season), cy: i + 1,
      team: r.team ? { abbr: BP.teamAbbr(r.team), name: BP.teamName(r.team), colour: U.raw(r.team) } : null,
      group: pr.pg || null, n: n, nUnit: kind === 'pitcher' ? 'batters faced' : 'PA', g: r.g, len: len,
      small: !r.hist && !(pr.dp && pr.dp.length), hist: !!r.hist, values: v, pct: pc,
      partial: Number(r.season) === cur && inProgress };
  });
  /* short seasons: under 60% of a regular's share (games against the schedule for hitters, batters faced per team game
     for pitchers) after or before a full one; the data has no injured-list history, so the tag says what it shows */
  const rate = s => (kind === 'pitcher' ? (isNum(s.n) ? s.n / s.len : null) : (isNum(s.g) ? s.g / s.len : null));
  S.forEach((s, i) => {
    if (s.partial || s.hist || s.gap) return;
    const r0 = rate(s);
    if (!isNum(r0)) return;
    const full = x => x && !x.hist && !x.gap && isNum(rate(x)) && (kind === 'pitcher' ? rate(x) >= 3.0 : rate(x) >= 0.75);
    const nb = [S[i - 1], S[i + 1]].filter(full);
    if (!nb.length) return;
    const ref0 = Math.max.apply(null, nb.map(rate));
    if (r0 < 0.6 * ref0) s.short = { kind: 'short', tag: 'Short', text: kind === 'pitcher' ? 'Faced ' + s.n + ' batters (a full season’s pace is about ' + Math.round(ref0 * s.len) + ')' : 'Played ' + s.g + ' of ' + s.len + ' games' };
  });
  return { id: String(pf.id), name: pf.name, short: BP.playerSurname(pf.id) || QK.surname(pf.name), kind: kind, seasons: S };
}
function peerOf(P) {
  const last = (P.seasons || []).slice().reverse().find(s => s.group) || {};
  return PEER[last.group] || (P.kind === 'pitcher' ? 'pitchers' : 'hitters');
}
function compareHref(ids, q) { return '#/compare/progression/' + ids.map(encodeURIComponent).join('/') + (q ? '?' + q : ''); }

/* ── the player page tab ─────────────────────────────────────────────────── */
function tab(el, params, route) {
  const pid = String(params.id || '');
  const q = params.query || {};
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([BP.load('players/' + pid + '.json'), refJson(), QK.spec.load('baseball')]).then(res => {
    if (!U.alive(el)) return;
    const pf = BP.ok(res[0]) ? res[0] : null, ref = res[1], cat = res[2];
    if (!pf || !pf.name) { el.innerHTML = QK.empty('No career file for this player', 'Try the search.'); return; }
    document.title = pf.name + ' · Progression · ' + BP.SITE;
    const ks = kindsOf(pf);
    let kind = q.kind === 'pitcher' || q.kind === 'hitter' ? q.kind : (route === 'pitcher' || route === 'hitter' ? route : defaultKind(pf));
    if (ks.length && ks.indexOf(kind) < 0) kind = ks[0];
    const P = toP(pf, kind, ref);
    const ms = metrics(((pf.prog || {}).keys || {})[kind] || [], kind, cat);
    const deep = ms.filter(m => !m.box), peer = peerOf(P), sur = P.short;
    const grp = (P.seasons.slice().reverse().find(s => s.group) || {}).group;
    const headIds = cat && grp ? cat.headline(grp) : [];
    deep.forEach(m => { m.head = headIds.indexOf(m.id) >= 0; });
    const head = headIds.map(id => deep.find(m => m.id === id)).filter(Boolean);
    const role = route === 'player' ? null : route;
    const base = BP.playerHref(pid, { role: role || kind });
    const tabs = [['overview', 'Overview', base], ['progression', 'Progression', base + '?view=progression' + (ks.length > 1 ? '&kind=' + kind : '')], ['detail', 'Detail: every metric', base + '?view=detail']];
    const lastTeam = (P.seasons.slice().reverse().find(s => s.team) || {}).team;
    let h = '<nav class="qk-tabs bp-tabs2" aria-label="Player views">' + tabs.map(t => '<a class="qk-tab" href="' + esc(t[2]) + '" aria-selected="' + (t[0] === 'progression') + '"' + (t[0] === 'progression' ? ' aria-current="page"' : '') + '>' + esc(t[1]) + '</a>').join('') + '</nav>';
    h += QK.sectionHead({ kicker: 'Progression' + (lastTeam ? ' · ' + lastTeam.name : ''), title: pf.name, size: 'lg', tag: 'h1',
      sub: P.seasons.filter(s => !s.gap).length + ' season' + (P.seasons.filter(s => !s.gap).length === 1 ? '' : 's') + (kind === 'pitcher' ? ' pitching' : ' at the plate') + ', each MLB season against that season’s qualified ' + esc(peer) + ' (position or role). Statcast numbers run from 2015; older seasons carry the box score' + (kind === 'pitcher' ? ', RA9' : ', wOBA') + ' and WAR.',
      actions: ks.length > 1 ? '<div class="qk-seg" role="group" aria-label="Side">' + ['hitter', 'pitcher'].map(k => '<a class="qk-btn' + (k === kind ? ' primary' : '') + '" href="' + esc(base + '?view=progression&kind=' + k) + '">' + (k === 'hitter' ? 'Hitting' : 'Pitching') + '</a>').join('') + '</div>' : '' });
    if (!P.seasons.length) { el.innerHTML = h + QK.empty('No MLB seasons in the data', 'The progression covers MLB seasons; Triple-A and NPB stay on the Detail view.'); return; }
    const key = ms.find(m => m.id === 'war') || null;
    const played = { id: P.id, name: P.name, short: P.short, seasons: P.seasons.filter(s => !s.gap) };
    const arc = QK.careerArc({ player: played, metrics: head.length ? head : deep.slice(0, 10), all: deep, key: key, peerName: peer });
    h += arc.html + QK.explain(esc(arc.text), { title: 'The short version.' });
    const avail = ms.filter(m => P.seasons.some(s => isNum(s.values[m.id])));
    const m0 = (head.find(m => avail.indexOf(m) >= 0) || avail[0] || ms[0]);
    h += '<section class="qk-section">' + U.card2('Career progression', 'One number through the seasons against the middle half of ' + esc(peer) + ' that season, or the headline set as percentiles',
      '<div class="qkp-ctl"><label for="pg-m">Metric <select class="qk-select" id="pg-m">' + QK.optgroups(avail.map(m => ({ value: m.id, key: m.id, label: m.label })), cat, { selected: m0.id }) + '</select></label>' +
      '<div class="qk-seg" role="group" aria-label="Show" id="pg-y"><button type="button" data-value="value" aria-pressed="true">Value</button><button type="button" data-value="pct" aria-pressed="false">Percentile</button><button type="button" data-value="head" aria-pressed="false">Headline set</button></div>' +
      '<div class="qk-seg" role="group" aria-label="Along" id="pg-x"><button type="button" data-value="season" aria-pressed="true">By season</button><button type="button" data-value="age" aria-pressed="false">By age</button></div></div>' +
      '<div id="pg-chart" style="height:360px"></div><div id="pg-key"></div><p class="qkp-note" id="pg-note"></p>') + '</section>';
    const ds = { player: { id: P.id, name: P.name, seasons: P.seasons.filter(s => !s.hist && !(s.gap && P.seasons.indexOf(s) < P.seasons.findIndex(x => !x.hist))) } };
    h += '<section class="qk-section">' + U.card2('Every season, every number', 'Percentile against ' + esc(peer) + ' each MLB season (100 = best); the value, the sample and the peers in each cell’s tooltip. The headline numbers for the position first, then the deeper set.',
      QK.progressionGrid({ player: ds.player, metrics: deep, groups: [{ label: 'The headline set', ids: head.map(m => m.id) }, { label: 'Deeper', ids: deep.filter(m => !m.head).map(m => m.id) }], peerName: peer })) + '</section>';
    const sims = [];
    (pf.similar || []).forEach(x => { const id = String(x.pid || x[0]); if (id && id !== P.id && sims.indexOf(id) < 0 && sims.length < 3) sims.push(id); });
    const cq = 'kind=' + kind;
    h += '<section class="qk-section"><div class="qk-g75"><div>' + U.card2('Biggest jumps and drops', 'Season to season, in percentile points, both seasons above the sample floor', QK.progressionDeltas({ player: played, metrics: deep, limit: 4, peerName: peer })) + '</div>' +
      '<div>' + U.card2('Compare the careers', 'Line ' + esc(sur) + ' up with anyone by season, by age or by career year', '<p style="margin:0 0 12px;color:var(--ink-2)">The closest matches on the profile, or pick anyone on the compare page.</p><div class="qk-chips">' +
        (sims.length ? '<a class="qk-chip" href="' + esc(compareHref([P.id].concat(sims.slice(0, 2)), cq + '&x=age')) + '">' + esc([sur].concat(sims.slice(0, 2).map(id => BP.playerSurname(id))).join(', ')) + ' by age</a>' : '') +
        sims.map(id => '<a class="qk-chip" href="' + esc(compareHref([P.id, id], cq)) + '">v ' + esc(BP.playerSurname(id) || BP.playerName(id)) + '</a>').join('') +
        '<a class="qk-chip" href="' + esc(compareHref([P.id], cq)) + '">Pick a player</a></div>') + '</div></div></section>';
    el.innerHTML = h;
    const R = QK.prog.ref(ref);
    const RF = (S, id) => (S.group ? R(S.group, S.key, id) : null);
    const st = { m: m0.id, y: 'value', x: 'season' };
    const draw = () => {
      const M = ms.find(m => m.id === st.m) || ms[0];
      const mode = st.y === 'head' ? 'pct' : st.y;
      const list = st.y === 'head' ? head.slice(0, 4) : [M];
      QKC.progression('#pg-chart', { player: P, metrics: list, mode: mode, x: st.x, ref: RF, peerName: peer });
      const pl = mode === 'value' && P.seasons.some(s => isNum(s.pct[M.id]));
      el.querySelector('#pg-key').innerHTML = QK.progressionKey({ mode: mode, name: sur, peerName: peer, pctLine: pl, band: !M.box, nUnit: kind === 'pitcher' ? 'batters faced' : 'PA' });
      el.querySelector('#pg-note').innerHTML = st.y === 'head' ? 'The first four headline numbers as percentiles against ' + esc(peer) + ' each season; the shaded band is the middle half.' : (M.tip ? '<b>' + esc(M.label) + (M.ours ? ' (our model)' : '') + ':</b> ' + esc(M.tip) : '') + (M.box ? ' Box score: no peer band.' : '');
    };
    const sel = el.querySelector('#pg-m');
    sel.addEventListener('change', () => { st.m = sel.value; if (st.y === 'head') { st.y = 'value'; el.querySelectorAll('#pg-y button').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-value') === 'value'))); } draw(); });
    QK.seg(el.querySelector('#pg-y'), v => { st.y = v; draw(); });
    QK.seg(el.querySelector('#pg-x'), v => { st.x = v; draw(); });
    draw();
  });
}

/* ── compare progression ─────────────────────────────────────────────────── */
function compare(el, params) {
  const q = params.query || {};
  let ids = [params.b].concat(params.rest || []).filter(Boolean).map(String);
  if (ids.length === 1 && ids[0].indexOf(',') >= 0) ids = ids[0].split(',');
  ids = ids.filter((x, i) => /^\d+$/.test(x) && ids.indexOf(x) === i).slice(0, 4);
  el.innerHTML = QK.skeleton('chart', 1);
  let fill = Promise.resolve(ids);
  if (!ids.length) fill = Promise.resolve(['592450', '665742']);
  else if (ids.length === 1) fill = BP.load('players/' + ids[0] + '.json').then(pf => ids.concat(((pf && pf.similar) || []).slice(0, 1).map(x => String(x.pid || x[0]))));
  return fill.then(list => Promise.all([Promise.all(list.map(id => BP.load('players/' + id + '.json'))), refJson(), QK.spec.load('baseball'), BP.ensureNames ? BP.ensureNames() : null]).then(res => {
    if (!U.alive(el)) return;
    const pfs = res[0].filter(pf => pf && pf.name), ref = res[1], cat = res[2];
    const kind = q.kind === 'pitcher' || q.kind === 'hitter' ? q.kind : (pfs.length ? defaultKind(pfs[0]) : 'hitter');
    const R = QK.prog.ref(ref);
    const Ps = pfs.map(pf => toP(pf, kind, ref));
    const keys = [];
    pfs.forEach(pf => { (((pf.prog || {}).keys || {})[kind] || []).forEach(k => { if (keys.indexOf(k) < 0) keys.push(k); }); });
    const ms = metrics(keys, kind, cat);
    const grp = ((Ps[0] || { seasons: [] }).seasons.slice().reverse().find(s => s.group) || {}).group;
    const hd = cat && grp ? cat.headline(grp) : [];
    ms.forEach(m => { m.head = hd.indexOf(m.id) >= 0; });
    const names = Ps.map(P => P.short);
    const stNow = { metric: q.m || (hd.find(id => ms.some(m => m.id === id)) || (ms[0] || {}).id), x: q.x === 'age' || q.x === 'year' ? q.x : 'season', y: q.y === 'pct' ? 'pct' : 'value' };
    const qs = () => 'kind=' + kind + '&m=' + encodeURIComponent(stNow.metric) + '&x=' + stNow.x + '&y=' + stNow.y;
    const sugg = [];
    pfs.forEach(pf => (pf.similar || []).forEach(x => { const id = String(x.pid || x[0]); if (Ps.length < 4 && !Ps.some(P => P.id === id) && !sugg.some(s => s.id === id)) sugg.push({ id: id, name: x.name || BP.playerName(id), sub: 'Plays most like ' + pf.name + (x.season ? ' (' + x.season + ')' : ''), href: compareHref(Ps.map(P => P.id).concat([id]), qs()) }); }));
    const opts = Object.keys(BP.NAMES).map(id => [id, BP.NAMES[id]]).filter(x => x[1] && x[1].name && (!x[1].levels || x[1].levels.indexOf('mlb') >= 0)).sort((a, b) => a[1].name.localeCompare(b[1].name));
    const optLabel = x => x[1].name + (x[1].team ? ' (' + BP.teamAbbr(x[1].team) + ')' : '');
    el.innerHTML = U.head({ kicker: 'Compare progression · MLB', title: names.length > 1 ? names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?' : (names[0] || 'Compare progression'), size: 'lg', tag: 'h1',
      sub: 'Two to four careers on one chart: by season, by age or by career year, on any number of the ' + (kind === 'pitcher' ? 'pitcher' : 'hitter') + '’s deep set, as the value or as a percentile against that season’s peers. Hollow dots are seasons under the sample floor.',
      actions: '<div class="qk-seg" role="group" aria-label="Kind">' + ['hitter', 'pitcher'].map(k => '<a class="qk-btn' + (k === kind ? ' primary' : '') + '" href="' + esc(compareHref(Ps.map(P => P.id), 'kind=' + k)) + '">' + (k === 'hitter' ? 'Hitting' : 'Pitching') + '</a>').join('') + '</div><a class="qk-btn" href="#/compare">Compare (this season)</a>' }) +
      '<article class="qk-card"><div class="qk-card-body"><div id="cp-w"></div>' +
      '<form class="qkp-ctl" id="cp-add" style="margin:16px 0 0" autocomplete="off"><label for="cp-in">Add or swap a player <input class="qk-input" id="cp-in" list="cp-dl" placeholder="Type a name" style="min-width:0;width:min(260px,60vw)"></label><datalist id="cp-dl">' +
      opts.map(x => '<option value="' + esc(optLabel(x)) + '"></option>').join('') + '</datalist><button class="qk-btn" type="submit">Add</button>' +
      Ps.map(P => '<a class="qk-chip" href="' + esc(compareHref(Ps.filter(x => x !== P).map(x => x.id), 'kind=' + kind)) + '" aria-label="Remove ' + esc(P.name) + '">✕ ' + esc(P.short) + '</a>').join('') + '</form></div></article>';
    if (!Ps.length) el.querySelector('#cp-w').innerHTML = QK.empty('Pick a player', 'Type a name below.');
    else QK.compareProgression(el.querySelector('#cp-w'), { players: Ps, metrics: ms, cat: cat, metric: stNow.metric, x: stNow.x, y: stNow.y,
      ref: (P, S, id) => (S.group ? R(S.group, S.key, id) : null), peerName: P => peerOf(P), suggest: sugg.slice(0, 5),
      cyNote: 'Career year counts MLB seasons in our data (Retrosheet seasons before 2015 included).',
      onState: s => { stNow.metric = s.metric; stNow.x = s.x; stNow.y = s.y; try { history.replaceState(null, '', compareHref(Ps.map(P => P.id), qs())); } catch (e) { /* file:// */ } } });
    el.querySelector('#cp-add').addEventListener('submit', e => {
      e.preventDefault();
      const v = String(el.querySelector('#cp-in').value || '').trim().toLowerCase();
      if (!v) return;
      const hit = opts.find(x => optLabel(x).toLowerCase() === v) || opts.find(x => x[1].name.toLowerCase() === v) || opts.find(x => x[1].name.toLowerCase().indexOf(v) >= 0);
      if (!hit) return;
      const next = Ps.map(P => P.id).filter(id => id !== hit[0]);
      if (next.length >= 4) next.pop();
      location.hash = compareHref(next.concat([hit[0]]), qs());
    });
  }));
}

BP.progression = { tab: tab, compare: compare, toP: toP, metrics: metrics, compareHref: compareHref };
})(window.BP);
