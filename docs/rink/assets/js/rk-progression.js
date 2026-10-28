/* The Quant Rink — progression (round 6): the player page's "Progression" tab (#/player/<pid>?view=progression) and
 * Compare progression (#/compare/progression/<a>/<b>[/<c>/<d>]?m=<metric>&x=season|age|year&y=value|pct).
 *
 * The reference adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"). Reads the player
 * files' seasons[].dv / dp / pg with prog.keys (oddsmarkets/nhl/analytics/careers.py on oddsmarkets/common/progression.py),
 * data/progression_ref.json (each season's qualified peers per position group: the median and the middle half) and the
 * spec's labels (QK.spec: names, units, direction, our models). Expected goals, RAPM and value come from 2010-11 on
 * (the 2009-10 catalogue is box score only); seasons without the deep set still show the box score (games, goals,
 * assists, points, ice time). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const GROUP_OF = { F: 'forwards', D: 'defence', G: 'goalies' };
const PEER = { forwards: 'forwards', defence: 'defencemen', goalies: 'goalies' };
/* box-score metrics from the career rows' values (every season, the older ones included) */
const BOX = {
  skater: [['gp', 'Games played', 'games', 'higher'], ['p', 'Points', 'points', 'higher'], ['g', 'Goals', 'goals', 'higher'], ['a', 'Assists', 'assists', 'higher'], ['sog', 'Shots on goal', 'shots', 'higher'], ['plus_minus', 'Plus-minus', '+/-', 'higher']],
  goalie: [['gp', 'Games played', 'games', 'higher'], ['w', 'Wins', 'wins', 'higher'], ['so', 'Shutouts', 'shutouts', 'higher']]
};
const FIRST_DEEP = '2010-11';
let REF_P = null;
function refJson() { if (!REF_P) REF_P = RK.load('progression_ref.json'); return REF_P; }

function kindOf(pf) { return pf && (pf.kind === 'goalie' || pf.pos === 'G') ? 'goalie' : 'skater'; }
function fmtOf(id, unit) {
  if (id === 'sv_pct' || id === 'sv_pct_high' || id === 'sv_pct_med' || id === 'sv_pct_low' || id === 'sv_pct_5v5' || id === 'sv_pct_sh' || id === 'dfsv_pct' || id === 'pdo') return v => (isNum(v) ? v.toFixed(3).replace(/^0/, '') : '—');
  if (id === 'toi_gp' || id === 'toi_pp_gp' || id === 'toi_sh_gp' || id === 'qoc_toi' || id === 'qot_toi') return v => (isNum(v) ? v.toFixed(1) : '—');
  if (/^(gp|g|a|p|w|so|sog|plus_minus)$/.test(id)) return v => (isNum(v) ? String(Math.round(v)) : '—');
  return v => QK.prog.fmt(unit, v);
}
/* the metric list (kit shape) for a kind: the player file's deep set (spec order: headline first), then the box score */
function metrics(keys, kind, cat) {
  const out = [];
  (keys || []).forEach(id => {
    const m = cat ? cat.metric(id, 'player') : null;
    const lab = m && m.label && m.label !== id ? m.label : ((U.SPEC[id] || {}).label || id);
    out.push({ id: id, label: lab, unit: (m && m.unit) || '', dir: m ? (m.style ? 'neutral' : m.dir) : 'higher', ours: m && m.ours ? m.ours : null, tip: cat ? cat.tip(id, 'player', '') : '', head: !!(m && m.set === 'h'), fmt: fmtOf(id, m && m.unit) });
  });
  (BOX[kind] || []).forEach(b => { if (!out.some(m => m.id === b[0])) out.push({ id: b[0], label: b[1], unit: b[2], dir: b[3], ours: null, tip: '', head: false, box: true, fmt: fmtOf(b[0], b[2]) }); });
  return out;
}
/* a player file -> the kit's player shape */
function toP(pf, ref) {
  const kind = kindOf(pf);
  const keys = ((pf.prog || {}).keys || {})[kind] || [];
  const cur = Number(RK.currentSeason());
  const rows = (pf.seasons || []).filter(s => (s.kind || kind) === kind || !s.kind).slice().sort((a, b) => a.season - b.season);
  const lens = (ref && ref.seasons) || {};
  const S = rows.map((r, i) => {
    const v = Object.assign({}, r.values || {}), pc = {};
    (r.dv || []).forEach((x, j) => { if (isNum(x) && keys[j]) v[keys[j]] = x; });
    (r.dp || []).forEach((x, j) => { if (isNum(x) && keys[j]) pc[keys[j]] = x; });
    const grp = r.pg || (kind === 'goalie' ? 'goalies' : GROUP_OF[r.pos === 'D' ? 'D' : 'F']);
    const len = (lens[String(r.season)] || {}).len;
    const teams = (r.teams && r.teams.length ? r.teams : [r.team]).filter(Boolean);
    return { key: String(r.season), x: Math.floor(r.season / 10000), label: RK.seasonLabel(r.season), age: r.age, cy: i + 1,
      team: r.team ? { abbr: RK.teamAbbr(r.team), name: RK.teamName(r.team), colour: RK.teamColourRaw(r.team) } : null,
      teams: teams.length > 1 ? teams.map(t => RK.teamAbbr(t)) : null, group: grp, n: v.gp, nMax: isNum(len) && Number(r.season) !== cur ? len : null, nUnit: 'games',
      small: !(r.dp && r.dp.length) || !r.qualified, values: v, pct: pc, _cur: Number(r.season) === cur, partial: Number(r.season) === cur && !!RK.phaseLabel && /regular|pre/i.test(String(RK.phaseLabel() || '')) };
  });
  /* short seasons: under 60% of the schedule after a fuller season (a regular, not a call-up); the data has no injury
     list for past seasons, so the tag says what it shows: the games played */
  S.forEach((s, i) => {
    if (s._cur || !isNum(s.n) || !isNum(s.nMax)) return;
    const full = x => x && isNum(x.n) && isNum(x.nMax) && x.n >= 0.75 * x.nMax;
    if (s.n < 0.6 * s.nMax && (full(S[i - 1]) || full(S[i + 1]))) s.short = { kind: 'short', tag: 'Short', text: 'Played ' + s.n + ' of ' + s.nMax + ' games' };
  });
  return { id: String(pf.id), name: pf.name, short: RK.playerSurname(pf.id) || QK.surname(pf.name), href: RK.playerHref(pf.id), kind: kind, seasons: S };
}
function refFn(ref) {
  const R = QK.prog.ref(ref);
  return (S, id) => R(S.group, S.key, id);
}
function peerOf(P) {
  const last = (P.seasons || []).slice().reverse().find(s => s.group) || {};
  return PEER[last.group] || 'peers';
}
function compareHref(ids, q) { return '#/compare/progression/' + ids.map(encodeURIComponent).join('/') + (q ? '?' + q : ''); }

/* ── the player page tab ─────────────────────────────────────────────────── */
function tab(body, pf) {
  body.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([refJson(), QK.spec.load('hockey')]).then(res => {
    if (!U.alive(body)) return;
    const ref = res[0], cat = res[1];
    const P = toP(pf, ref), kind = P.kind;
    const ms = metrics(((pf.prog || {}).keys || {})[kind] || [], kind, cat);
    const deep = ms.filter(m => !m.box), head = deep.filter(m => m.head);
    const peer = peerOf(P), sur = P.short;
    if (!P.seasons.length) { body.innerHTML = QK.empty('No seasons in the data', 'The progression appears once a season is in the data.'); return; }
    const key = ms.find(m => m.id === (kind === 'goalie' ? 'gsax' : 'war')) || null;
    const arc = QK.careerArc({ player: P, metrics: head.length ? head : deep.slice(0, 8), all: deep, key: key, peerName: peer });
    const sims = (pf.similar || []).slice(0, 3).map(x => String(x[0]));
    const cmpIds = [P.id].concat(sims.slice(0, 2));
    const first = P.seasons[0], deepFirst = P.seasons.find(s => s.pct && Object.keys(s.pct).length);
    let h = QK.sectionHead({ kicker: 'Progression', title: sur + ', season by season', sub: P.seasons.length + ' season' + (P.seasons.length === 1 ? '' : 's') + ' in the data, each against that season’s qualified ' + peer + '. Expected goals, RAPM and value run from ' + FIRST_DEEP + '; older seasons carry the box score.' }) +
      arc.html + QK.explain(esc(arc.text), { title: 'The short version.' });
    const opt = QK.optgroups(ms.filter(m => P.seasons.some(s => isNum(s.values[m.id]))).map(m => ({ value: m.id, key: m.id, label: m.label })), cat, { selected: (head[0] || ms[0]).id });
    h += '<section class="qk-section">' + U.card2('Career progression', 'One number through the seasons against the middle half of ' + esc(peer) + ' that season, or the headline set as percentiles',
      '<div class="qkp-ctl"><label for="pg-m">Metric <select class="qk-select" id="pg-m">' + opt + '</select></label>' +
      '<div class="qk-seg" role="group" aria-label="Show" id="pg-y"><button type="button" data-value="value" aria-pressed="true">Value</button><button type="button" data-value="pct" aria-pressed="false">Percentile</button><button type="button" data-value="head" aria-pressed="false">Headline set</button></div>' +
      '<div class="qk-seg" role="group" aria-label="Along" id="pg-x"><button type="button" data-value="season" aria-pressed="true">By season</button><button type="button" data-value="age" aria-pressed="false">By age</button></div></div>' +
      '<div id="pg-chart" style="height:360px"></div><div id="pg-key"></div><p class="qkp-note" id="pg-note"></p>') + '</section>';
    h += '<section class="qk-section">' + U.card2('Every season, every number', 'Percentile against ' + esc(peer) + ' each season (100 = best); the value, games and peers in each cell’s tooltip. The ' + (head.length || 9) + ' headline numbers first, then the deeper set.',
      QK.progressionGrid({ player: P, metrics: deep, groups: [{ label: 'The headline set', ids: head.map(m => m.id) }, { label: 'Deeper', ids: deep.filter(m => !m.head).map(m => m.id) }], peerName: peer })) + '</section>';
    h += '<section class="qk-section"><div class="qk-g75"><div>' + U.card2('Biggest jumps and drops', 'Season to season, in percentile points, both seasons above the sample floor', QK.progressionDeltas({ player: P, metrics: deep, limit: 4, peerName: peer })) + '</div>' +
      '<div>' + U.card2('Compare the careers', 'Line ' + esc(sur) + ' up with anyone by season, by age or by career year', '<p style="margin:0 0 12px;color:var(--ink-2)">The closest matches on this season’s profile, or pick anyone on the compare page.</p><div class="qk-chips">' +
        (sims.length ? '<a class="qk-chip" href="' + esc(compareHref(cmpIds, 'x=age')) + '">' + esc([sur].concat(sims.slice(0, 2).map(id => RK.playerSurname(id))).join(', ')) + ' by age</a>' : '') +
        sims.map(id => '<a class="qk-chip" href="' + esc(compareHref([P.id, id])) + '">v ' + esc(RK.playerSurname(id) || RK.playerName(id)) + '</a>').join('') +
        '<a class="qk-chip" href="' + esc(compareHref([P.id])) + '">Pick a player</a></div>') + '</div></div></section>';
    body.innerHTML = h;
    const st = { m: (head[0] || ms[0]).id, y: 'value', x: 'season' };
    const R = refFn(ref);
    const draw = () => {
      const M = ms.find(m => m.id === st.m) || ms[0];
      const mode = st.y === 'head' ? 'pct' : st.y;
      const list = st.y === 'head' ? head.slice(0, 4) : [M];
      QKC.progression('#pg-chart', { player: P, metrics: list, mode: mode, x: st.x, ref: R, peerName: peer, colour: null });
      const pl = mode === 'value' && P.seasons.some(s => isNum(s.pct[M.id]));
      body.querySelector('#pg-key').innerHTML = QK.progressionKey({ mode: mode, name: sur, peerName: peer, pctLine: pl, band: !M.box });
      body.querySelector('#pg-note').innerHTML = st.y === 'head' ? 'The first four headline numbers as percentiles against ' + esc(peer) + ' each season; the shaded band is the middle half.' : (M.tip ? '<b>' + esc(M.label) + (M.ours ? ' (our model)' : '') + ':</b> ' + esc(M.tip) : '') + (M.box ? ' Box score: no peer band.' : '');
    };
    const sel = body.querySelector('#pg-m');
    sel.addEventListener('change', () => { st.m = sel.value; if (st.y === 'head') { st.y = 'value'; body.querySelectorAll('#pg-y button').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-value') === 'value'))); } draw(); });
    QK.seg(body.querySelector('#pg-y'), v => { st.y = v; draw(); });
    QK.seg(body.querySelector('#pg-x'), v => { st.x = v; draw(); });
    draw();
  });
}

/* ── compare progression ─────────────────────────────────────────────────── */
function compare(el, params) {
  const q = params.query || {};
  let ids = [params.b].concat(params.rest || []).filter(Boolean).map(String);
  if (ids.length === 1 && ids[0].indexOf(',') >= 0) ids = ids[0].split(',');
  ids = ids.filter((x, i) => /^\d+$/.test(x) && ids.indexOf(x) === i).slice(0, 4);
  const sq = '';
  const body = U.section(el, { section: 'lab', title: 'Compare progression', sub: 'Two to four careers on one chart: by season, by age or by career year, on any number of the position’s deep set, as the value or as a percentile against that season’s peers.',
    tabs: [{ key: 'lab', label: 'Chart builder', href: '#/lab' + sq }, { key: 'compare', label: 'Compare', href: '#/compare' + sq }, { key: 'prog', label: 'Progression', href: '#/compare/progression' }], active: 'prog' });
  body.innerHTML = QK.skeleton('chart', 1);
  let fill = Promise.resolve(ids);
  if (!ids.length) {
    const L = ((RK.index() || {}).leaders || {}).s_p || [];
    fill = Promise.resolve(L.slice(0, 2).map(x => String(x[0])));
  } else if (ids.length === 1) fill = RK.loadPlayer(ids[0]).then(pf => ids.concat(((pf && pf.similar) || []).slice(0, 1).map(x => String(x[0]))));
  return fill.then(list => Promise.all([Promise.all(list.map(id => RK.loadPlayer(id))), refJson(), QK.spec.load('hockey')]).then(res => {
    if (!U.alive(el)) return;
    const pfs = res[0].filter(pf => pf && pf.name), ref = res[1], cat = res[2];
    const R = QK.prog.ref(ref);
    const Ps = pfs.map(pf => toP(pf, ref));
    const kinds = Ps.map(P => P.kind);
    const kind = kinds[0] || 'skater';
    const keys = [];
    pfs.forEach(pf => { (((pf.prog || {}).keys || {})[kind] || []).forEach(k => { if (keys.indexOf(k) < 0) keys.push(k); }); });
    const ms = metrics(keys, kind, cat);
    const names = Ps.map(P => P.short);
    const title = names.length > 1 ? names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?' : (names[0] || 'Pick players');
    const stNow = { metric: q.m || ((ms.find(m => m.head) || ms[0] || {}).id), x: q.x === 'age' || q.x === 'year' ? q.x : 'season', y: q.y === 'pct' ? 'pct' : 'value' };
    const sugg = [];
    pfs.forEach(pf => (pf.similar || []).forEach(x => { const id = String(x[0]); if (Ps.length < 4 && !Ps.some(P => P.id === id) && !sugg.some(s => s.id === id)) sugg.push({ id: id, name: x[1] || RK.playerName(id), sub: 'Plays most like ' + pf.name + ' this season', href: compareHref(Ps.map(P => P.id).concat([id]), qs()) }); }));
    function qs() { return 'm=' + encodeURIComponent(stNow.metric) + '&x=' + stNow.x + '&y=' + stNow.y; }
    /* the picker: any player in the index (name and last team) */
    const opts = Object.keys(RK.NAMES).map(id => [id, RK.NAMES[id]]).filter(x => x[1] && x[1].name).sort((a, b) => a[1].name.localeCompare(b[1].name));
    body.innerHTML = QK.sectionHead({ kicker: 'Compare progression', title: title, sub: (kinds.some(k => k !== kind) ? 'Skaters and goalies have different numbers: the chart shows the ' + kind + ' set. ' : '') + 'Hover a season for the team, the age and the sample; hollow dots are seasons under the sample floor.' }) +
      '<article class="qk-card"><div class="qk-card-body"><div id="cp-w"></div>' +
      '<form class="qkp-ctl" id="cp-add" style="margin:16px 0 0" autocomplete="off"><label for="cp-in">Add or swap a player <input class="qk-input" id="cp-in" list="cp-dl" placeholder="Type a name" style="min-width:0;width:min(260px,60vw)"></label><datalist id="cp-dl">' +
      opts.map(x => '<option value="' + esc(x[1].name + (x[1].team ? ' (' + RK.teamAbbr(x[1].team) + ')' : '')) + '"></option>').join('') + '</datalist>' +
      '<button class="qk-btn" type="submit">Add</button>' + Ps.map(P => '<a class="qk-chip" href="' + esc(compareHref(Ps.filter(x => x !== P).map(x => x.id), '')) + '" aria-label="Remove ' + esc(P.name) + '">✕ ' + esc(P.short) + '</a>').join('') + '</form></div></article>';
    if (!Ps.length) { body.querySelector('#cp-w').innerHTML = QK.empty('Pick a player', 'Type a name below.'); }
    else QK.compareProgression(body.querySelector('#cp-w'), { players: Ps, metrics: ms, cat: cat, metric: stNow.metric, x: stNow.x, y: stNow.y,
      ref: (P, S, id) => R(S.group, S.key, id), peerName: P => peerOf(P), suggest: sugg.slice(0, 5),
      cyNote: 'Career year counts seasons in our data, which starts in 2009-10: a veteran’s year 1 there is not the rookie season.',
      onState: s => { stNow.metric = s.metric; stNow.x = s.x; stNow.y = s.y; try { history.replaceState(null, '', compareHref(Ps.map(P => P.id), qs())); } catch (e) { /* file:// */ } } });
    const form = body.querySelector('#cp-add');
    form.addEventListener('submit', e => {
      e.preventDefault();
      const v = String(body.querySelector('#cp-in').value || '').trim().toLowerCase();
      if (!v) return;
      const hit = opts.find(x => (x[1].name + (x[1].team ? ' (' + RK.teamAbbr(x[1].team) + ')' : '')).toLowerCase() === v) || opts.find(x => x[1].name.toLowerCase() === v) || opts.find(x => x[1].name.toLowerCase().indexOf(v) >= 0);
      if (!hit) return;
      const next = Ps.map(P => P.id).filter(id => id !== hit[0]);
      if (next.length >= 4) next.pop();
      location.hash = compareHref(next.concat([hit[0]]), qs());
    });
  }));
}

RK.progression = { tab: tab, compare: compare, toP: toP, metrics: metrics, compareHref: compareHref };
})(window.RK);
