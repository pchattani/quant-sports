/* The Quant Hardwood — progression (round 6): the player page's "Progression" tab (#/<L>/player/<pid>?tab=progression)
 * and Compare progression (#/<L>/compare/progression/<a>/<b>[/<c>/<d>]?m=<metric>&x=season|age|year&y=value|pct), for
 * the NBA (1997 on) and the WNBA (1997 on).
 *
 * The adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression", the Rink reference in
 * rk-progression.js). Reads the career files' seasons[].dv / dp / pg / age / miss with prog.keys.player
 * (scripts/build_hardwood.py `progression`: the spec's role sets for guards, wings and bigs, plus WAR from value.json
 * and the per-game box rates), <L>/progression_ref.json (each season's qualified peers per role), <L>/bio.json (debut
 * year: the career year) and the spec's labels (QK.spec). Injury-shortened seasons come from the catalogue's injury
 * absences (injury_dnp) and games missed. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const ROLE_PEER = { guards: 'guards', wings: 'wings', bigs: 'bigs' };
const EXTRA_LABEL = { war: ['WAR', 'wins'], rapm_o: ['RAPM offence', 'per 100'], rapm_d: ['RAPM defence', 'per 100'], wpa: ['Win probability added', 'wins'],
  pts_g: ['Points per game', 'points'], reb_g: ['Rebounds per game', 'rebounds'], ast_g: ['Assists per game', 'assists'], stl_g: ['Steals per game', 'steals'],
  blk_g: ['Blocks per game', 'blocks'], mpg: ['Minutes per game', 'min'], gmsc: ['Game score', 'per game'] };
const REF = {}, BIO = {};
function refJson(L) { if (!REF[L]) REF[L] = HW.load(L + '/progression_ref.json'); return REF[L]; }
function bioJson(L) { if (!BIO[L]) BIO[L] = HW.load(L + '/bio.json'); return BIO[L]; }
function groupPeer(g) { const m = /_(guards|wings|bigs)$/.exec(String(g || '')); return m ? ROLE_PEER[m[1]] : 'players'; }

function metrics(keys, cat) {
  return (keys || []).map(id => {
    const m = cat ? cat.metric(id, 'player') : null, mm = U.mMeta(id), ex = EXTRA_LABEL[id];
    const lab = m && m.label && m.label !== id ? m.label : (ex ? ex[0] : (mm.label && mm.label !== id ? mm.label : id));
    const ours = (m && m.ours) || (cat && cat.ours(id)) || null;
    return { id: id, label: lab, unit: (m && m.unit) || (ex ? ex[1] : ''), dir: m ? (m.style ? 'neutral' : m.dir) : (mm.style ? 'neutral' : mm.better === 'low' ? 'lower' : 'higher'),
      ours: ours, tip: cat ? cat.tip(id, 'player', mm.desc || '') : (mm.desc || ''), head: !!(m && m.set === 'h'), fmt: v => U.fmtM(id, v) };
  });
}
function toP(L, pf, ref, bio) {
  const keys = ((pf.prog || {}).keys || {}).player || [];
  const cur = Number(HW.currentSeason(L));
  const ph = String(HW.phase(L) || '');
  const lens = (ref && ref.seasons) || {};
  const debut = bio && bio[String(pf.id)] && isNum(bio[String(pf.id)].debut) ? bio[String(pf.id)].debut : null;
  const rows = (pf.seasons || []).slice().sort((a, b) => a.season - b.season);
  /* age at the season's midpoint (1 Feb for the NBA, 1 July for the WNBA) from the date of birth, for every season alike
     (the catalogues carry an age only in recent seasons, on another date: mixing them would put two seasons at one age) */
  const dob = pf.dob || (bio && bio[String(pf.id)] ? bio[String(pf.id)].dob : null);
  const dobT = dob ? Date.parse(String(dob).slice(0, 10) + 'T00:00:00Z') : NaN;
  const ageAt = season => (isNaN(dobT) ? null : Math.round(((Date.UTC(season, L === 'nba' ? 1 : 6, 1) - dobT) / (365.25 * 864e5)) * 10) / 10);
  const S = rows.map((r, i) => {
    const v = {}, pc = {};
    ['gp', 'min', 'pts', 'reb', 'ast', 'ts', 'hpm', 'rapm', 'box_impact', 'wpa'].forEach(k => { if (isNum(r[k])) v[k] = r[k]; });
    if (isNum(r.o)) v.hpm_o = r.o;
    if (isNum(r.d)) v.hpm_d = r.d;
    (r.dv || []).forEach((x, j) => { if (isNum(x) && keys[j]) v[keys[j]] = x; });
    (r.dp || []).forEach((x, j) => { if (isNum(x) && keys[j]) pc[keys[j]] = x; });
    const len = (lens[String(r.season)] || {}).len;
    const cy = isNum(debut) ? r.season - debut + (L === 'nba' ? 0 : 1) : null;
    const s = { key: String(r.season), x: r.season, label: HW.seasonLabel(L, r.season), age: isNum(ageAt(r.season)) ? ageAt(r.season) : r.age, cy: isNum(cy) && cy >= 1 ? cy : i + 1,
      team: r.team ? { abbr: HW.teamAbbr(L, r.team), name: HW.teamName(L, r.team), colour: HW.teamColourRaw(L, r.team) } : null,
      group: r.pg || null, n: r.gp, nMax: isNum(len) && r.season !== cur ? len : null, nUnit: 'games',
      small: !(r.dp && r.dp.length) || !r.qualified, values: v, pct: pc,
      partial: r.season === cur && /pre|regular|play/i.test(ph) && !/off/i.test(ph) };
    const miss = r.miss || [];
    if (!s.partial && isNum(miss[1]) && miss[1] >= 10) s.short = { kind: 'injury', tag: 'Injury', text: 'Out injured for ' + miss[1] + ' games' + (isNum(miss[0]) && miss[0] > miss[1] ? ' (' + miss[0] + ' missed in all)' : '') };
    return s;
  });
  S.forEach((s, i) => {
    if (s.short || s.partial || !isNum(s.n) || !isNum(s.nMax)) return;
    const full = x => x && isNum(x.n) && isNum(x.nMax) && x.n >= 0.75 * x.nMax;
    if (s.n < 0.6 * s.nMax && (full(S[i - 1]) || full(S[i + 1]))) s.short = { kind: 'short', tag: 'Short', text: 'Played ' + s.n + ' of ' + s.nMax + ' games' };
  });
  return { id: String(pf.id), name: pf.name, short: QK.surname(pf.name), href: HW.playerHref(L, pf.id), seasons: S, debut: debut };
}
function peerOf(L, P) {
  const last = (P.seasons || []).slice().reverse().find(s => s.group) || {};
  return HW.leagueName(L) + ' ' + groupPeer(last.group);
}
function compareHref(L, ids, q) { return '#/' + L + '/compare/progression/' + ids.map(encodeURIComponent).join('/') + (q ? '?' + q : ''); }

/* ── the player page tab ─────────────────────────────────────────────────── */
function tab(body, L, pf) {
  body.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  if (!pf || !pf.seasons) { body.innerHTML = QK.empty('No career file', 'The progression appears once the player has a season in the data.'); return null; }
  return Promise.all([refJson(L), QK.spec.load('basketball'), bioJson(L)]).then(res => {
    if (!U.alive(body)) return;
    const ref = res[0], cat = res[1], bio = res[2];
    const P = toP(L, pf, ref, bio);
    const ms = metrics(((pf.prog || {}).keys || {}).player || [], cat);
    const head = ms.filter(m => m.head);
    const peer = peerOf(L, P), sur = P.short;
    if (!P.seasons.length) { body.innerHTML = QK.empty('No seasons in the data'); return; }
    const key = ms.find(m => m.id === 'war') || null;
    const arc = QK.careerArc({ player: P, metrics: head.length ? head : ms.slice(0, 8), all: ms, key: key, peerName: peer });
    const simR = (pf.similar_role || []).filter((x, i, a) => a.findIndex(y => String(y.id) === String(x.id)) === i).slice(-3).map(x => String(x.id));
    const simA = (pf.similar || []).map(x => String(x.id)).filter((x, i, a) => a.indexOf(x) === i && x !== P.id);
    const sims = simR.concat(simA).filter((x, i, a) => a.indexOf(x) === i && x !== P.id).slice(0, 3);
    const noDeep = P.seasons.filter(s => !Object.keys(s.pct).length && !s.small).length;
    let h = QK.sectionHead({ kicker: 'Progression', title: sur + ', season by season', sub: P.seasons.length + ' season' + (P.seasons.length === 1 ? '' : 's') + ' in the data, each against that season’s qualified ' + peer + ' (role: guards, wings or bigs).' + (L === 'nba' ? ' Shot-location and play-by-play numbers run from 2002; the box score, HPM and WAR from 1997.' : '') + (noDeep ? '' : '') }) +
      arc.html + QK.explain(esc(arc.text), { title: 'The short version.' });
    const opt = QK.optgroups(ms.filter(m => P.seasons.some(s => isNum(s.values[m.id]))).map(m => ({ value: m.id, key: m.id, label: m.label })), cat, { selected: (head[0] || ms[0]).id });
    h += '<section class="qk-section">' + U.card2('Career progression', 'One number through the seasons against the middle half of ' + esc(peer) + ' that season, or the headline set as percentiles',
      '<div class="qkp-ctl"><label for="hpg-m">Metric <select class="qk-select" id="hpg-m">' + opt + '</select></label>' +
      '<div class="qk-seg" role="group" aria-label="Show" id="hpg-y"><button type="button" data-value="value" aria-pressed="true">Value</button><button type="button" data-value="pct" aria-pressed="false">Percentile</button><button type="button" data-value="head" aria-pressed="false">Headline set</button></div>' +
      '<div class="qk-seg" role="group" aria-label="Along" id="hpg-x"><button type="button" data-value="season" aria-pressed="true">By season</button><button type="button" data-value="age" aria-pressed="false">By age</button></div></div>' +
      '<div id="hpg-chart" style="height:360px"></div><div id="hpg-key"></div><p class="qkp-note" id="hpg-note"></p>') + '</section>';
    h += '<section class="qk-section">' + U.card2('Every season, every number', 'Percentile against ' + esc(peer) + ' each season (100 = best); the value, games and peers in each cell’s tooltip. The headline numbers first, then the deeper set, value and the box score.',
      QK.progressionGrid({ player: P, metrics: ms, groups: [{ label: 'The headline set', ids: head.map(m => m.id) }, { label: 'Deeper', ids: ms.filter(m => !m.head).map(m => m.id) }], peerName: peer })) + '</section>';
    h += '<section class="qk-section"><div class="qk-g75"><div>' + U.card2('Biggest jumps and drops', 'Season to season, in percentile points, both seasons above the minutes floor', QK.progressionDeltas({ player: P, metrics: ms, limit: 4, peerName: peer })) + '</div>' +
      '<div>' + U.card2('Compare the careers', 'Line ' + esc(sur) + ' up with anyone by season, by age or by career year', '<p style="margin:0 0 12px;color:var(--ink-2)">The closest matches by role, or pick anyone on the compare page.</p><div class="qk-chips">' +
        (sims.length ? '<a class="qk-chip" href="' + esc(compareHref(L, [P.id].concat(sims.slice(0, 2)), 'x=age')) + '">' + esc([sur].concat(sims.slice(0, 2).map(id => QK.surname(HW.playerName(L, id)))).join(', ')) + ' by age</a>' : '') +
        sims.map(id => '<a class="qk-chip" href="' + esc(compareHref(L, [P.id, id])) + '">v ' + esc(QK.surname(HW.playerName(L, id))) + '</a>').join('') +
        '<a class="qk-chip" href="' + esc(compareHref(L, [P.id])) + '">Pick a player</a></div>') + '</div></div></section>';
    body.innerHTML = h;
    const st = { m: (head[0] || ms[0]).id, y: 'value', x: 'season' };
    const R = QK.prog.ref(ref);
    const rf = (S, id) => R(S.group, S.key, id);
    const draw = () => {
      const M = ms.find(m => m.id === st.m) || ms[0];
      const mode = st.y === 'head' ? 'pct' : st.y;
      QKC.progression('#hpg-chart', { player: P, metrics: st.y === 'head' ? head.slice(0, 4) : [M], mode: mode, x: st.x, ref: rf, peerName: peer });
      const pl = mode === 'value' && P.seasons.some(s => isNum(s.pct[M.id]));
      body.querySelector('#hpg-key').innerHTML = QK.progressionKey({ mode: mode, name: sur, peerName: peer, pctLine: pl });
      body.querySelector('#hpg-note').innerHTML = st.y === 'head' ? 'The first four headline numbers as percentiles against ' + esc(peer) + ' each season; the shaded band is the middle half.' : (M.tip ? '<b>' + esc(M.label) + (M.ours ? ' (our model)' : '') + ':</b> ' + esc(M.tip) : '');
    };
    const sel = body.querySelector('#hpg-m');
    sel.addEventListener('change', () => { st.m = sel.value; if (st.y === 'head') { st.y = 'value'; body.querySelectorAll('#hpg-y button').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-value') === 'value'))); } draw(); });
    QK.seg(body.querySelector('#hpg-y'), v => { st.y = v; draw(); });
    QK.seg(body.querySelector('#hpg-x'), v => { st.x = v; draw(); });
    draw();
  });
}

/* ── compare progression ─────────────────────────────────────────────────── */
function compare(el, params) {
  const L = U.L(params), q = params.query || {};
  let ids = [params.a].concat(params.rest || []).filter(Boolean).map(String);
  if (ids.length === 1 && ids[0].indexOf(',') >= 0) ids = ids[0].split(',');
  ids = ids.filter((x, i) => /^\d+$/.test(x) && ids.indexOf(x) === i).slice(0, 4);
  const body = U.section(el, { title: 'Compare progression', kicker: HW.leagueName(L) + ' · careers', sub: 'Two to four careers on one chart: by season, by age or by career year, on any number of the role’s deep set, as the value or as a percentile against that season’s peers.',
    tabs: [{ key: 'compare', label: 'Players, side by side', href: '#/' + L + '/compare/players' + (ids.length ? '/' + ids.slice(0, 2).map(encodeURIComponent).join('/') : '') }, { key: 'prog', label: 'Progression', href: '#/' + L + '/compare/progression' }, { key: 'teams', label: 'Teams', href: '#/' + L + '/compare/teams' }], active: 'prog' });
  body.innerHTML = QK.skeleton('chart', 1);
  const search = HW.loadSearch ? HW.loadSearch(L) : Promise.resolve([]);
  let fill;
  if (!ids.length) fill = HW.load(HW.path('value.json', L, HW.currentSeason(L))).then(v => U.rowsOf(U.ok(v) ? v : null).filter(r => isNum(r.war)).sort((a, b) => b.war - a.war).slice(0, 2).map(r => String(r.id)));
  else if (ids.length === 1) fill = HW.load(L + '/players/' + ids[0] + '.json').then(pf => ids.concat(((pf && pf.similar_role) || []).slice(-1).map(x => String(x.id))));
  else fill = Promise.resolve(ids);
  return fill.then(list => Promise.all([Promise.all(list.map(id => HW.load(L + '/players/' + id + '.json'))), refJson(L), QK.spec.load('basketball'), bioJson(L), search]).then(res => {
    if (!U.alive(el)) return;
    const pfs = res[0].filter(pf => pf && pf.name), ref = res[1], cat = res[2], bio = res[3], items = (res[4] || []).filter(x => x.kind === 'Players');
    const R = QK.prog.ref(ref);
    const Ps = pfs.map(pf => toP(L, pf, ref, bio));
    const keys = [];
    pfs.forEach(pf => ((((pf.prog || {}).keys || {}).player) || []).forEach(k => { if (keys.indexOf(k) < 0) keys.push(k); }));
    const ms = metrics(keys, cat);
    const stNow = { metric: q.m || ((ms.find(m => m.head) || ms[0] || {}).id), x: q.x === 'age' || q.x === 'year' ? q.x : 'season', y: q.y === 'pct' ? 'pct' : 'value' };
    const qs = () => 'm=' + encodeURIComponent(stNow.metric) + '&x=' + stNow.x + '&y=' + stNow.y;
    const sugg = [];
    pfs.forEach(pf => (pf.similar_role || []).slice().reverse().forEach(x => { const id = String(x.id); if (Ps.length < 4 && !Ps.some(P => P.id === id) && !sugg.some(s => s.id === id)) sugg.push({ id: id, name: x.name || HW.playerName(L, id), sub: 'Closest by role to ' + pf.name + ' in ' + HW.seasonLabel(L, x.season), href: compareHref(L, Ps.map(P => P.id).concat([id]), qs()) }); }));
    const names = Ps.map(P => P.short);
    const title = names.length > 1 ? names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?' : (names[0] || 'Pick players');
    const opts = items.map(x => [String(x.id), x.label + (x.sub ? ' (' + x.sub + ')' : '')]);
    body.innerHTML = QK.sectionHead({ kicker: 'Compare progression', title: title, sub: 'Hover a season for the team, the age and the sample; hollow dots are seasons under the minutes floor.' }) +
      '<article class="qk-card"><div class="qk-card-body"><div id="hcp-w"></div>' +
      '<form class="qkp-ctl" id="hcp-add" style="margin:16px 0 0" autocomplete="off"><label for="hcp-in">Add a player <input class="qk-input" id="hcp-in" list="hcp-dl" placeholder="Type a name" style="min-width:0;width:min(260px,60vw)"></label><datalist id="hcp-dl">' +
      opts.map(x => '<option value="' + esc(x[1]) + '"></option>').join('') + '</datalist><button class="qk-btn" type="submit">Add</button>' +
      Ps.map(P => '<a class="qk-chip" href="' + esc(compareHref(L, Ps.filter(x => x !== P).map(x => x.id), '')) + '" aria-label="Remove ' + esc(P.name) + '">✕ ' + esc(P.short) + '</a>').join('') + '</form></div></article>';
    if (!Ps.length) body.querySelector('#hcp-w').innerHTML = QK.empty('Pick a player', 'Type a name below.');
    else QK.compareProgression(body.querySelector('#hcp-w'), { players: Ps, metrics: ms, cat: cat, metric: stNow.metric, x: stNow.x, y: stNow.y,
      ref: (P, S, id) => R(S.group, S.key, id), peerName: P => peerOf(L, P), suggest: sugg.slice(0, 5),
      cyNote: 'Career year counts from the player’s debut season.',
      onState: s => { stNow.metric = s.metric; stNow.x = s.x; stNow.y = s.y; try { history.replaceState(null, '', compareHref(L, Ps.map(P => P.id), qs())); } catch (e) { /* file:// */ } } });
    body.querySelector('#hcp-add').addEventListener('submit', e => {
      e.preventDefault();
      const v = String(body.querySelector('#hcp-in').value || '').trim().toLowerCase();
      if (!v) return;
      const hit = opts.find(x => x[1].toLowerCase() === v) || opts.find(x => x[1].toLowerCase().indexOf(v) >= 0);
      if (!hit) return;
      const next = Ps.map(P => P.id).filter(id => id !== hit[0]);
      if (next.length >= 4) next.pop();
      location.hash = compareHref(L, next.concat([hit[0]]), qs());
    });
  }));
}

HW.progression = { tab: tab, compare: compare, toP: toP, compareHref: compareHref };
HW.route('compare/progression', compare);
HW.route('compare/progression/:a', compare);
})(window.HW);
