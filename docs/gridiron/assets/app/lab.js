/* The Quant Gridiron — the scatter lab (#/lab?g=QB|RB|WR|TE|K|P|DEF|TEAM&x=&y=), first view of the Lab, on Design System
 * 2.0 (stat tiles, a leaderboard with percentile heat cells, our highlight in the signal colour).
 * Any two catalogue metrics for a position group or the teams, with presets for the questions the models
 * were built for, colour by team, position, conference or any metric, medians, the corners labelled, a
 * search highlight and the group ranked below. Rates can be shrunk towards the median by their
 * stabilisation point: shrunk = (n·x + k·median)/(n + k), k = 3/7 of the sample at which split-half
 * reliability reaches 0.7. Reads <S>/lab.json (players.json and teams.json as the fallback) and <S>/value.json (Gridiron
 * Value per game and in total, joined by player id). Round 5: the pickers list our model metrics first ("Our models",
 * then the spec's headline box-score metrics, then the payload's groups), and our metrics carry the cobalt tag on the
 * axes line and in the ranked table's heads, with a cobalt strip naming the model. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const PRESETS = [
  /* our models lead each group: the QB composite, Gridiron Value per game, kicking over expected, the team ratings */
  ['QB', 'epa_db', 'composite', 'EPA per dropback against the QB composite'], ['RB', 'ryoe', 'gvar_pg', 'RYOE against value per game'], ['WR', 'target_share', 'gvar_pg', 'Volume against value per game'],
  ['TE', 'target_share', 'gvar_pg', 'Volume against value per game'], ['DEF', 'pressures_pg', 'gvar_pg', 'Sacks and hits per game against value per game'],
  ['TEAM', 'off_rating', 'def_rating', 'Our team ratings: offence against defence'],
  ['QB', 'cpoe', 'adot', 'CPOE against aDOT: accuracy against depth'], ['QB', 'epa_clean', 'epa_pressure', 'Clean pocket against under pressure'], ['QB', 'ttt', 'sack_rate', 'Time to throw against sack rate'],
  ['QB', 'epa_db', 'composite', 'EPA per dropback against the QB composite'], ['QB', 'pa_rate', 'epa_pa', 'Play-action rate against EPA on play action'],
  ['RB', 'ryoe', 'rush_success', 'RYOE against success rate'], ['RB', 'box8', 'ryoe', 'Eight-man boxes against RYOE'], ['RB', 'explosive', 'stuff_rate', 'Explosive runs against stuffed runs'],
  ['WR', 'separation', 'yacoe', 'Separation against YAC over expected'], ['WR', 'adot', 'croe', 'aDOT against catch rate over expected'], ['WR', 'target_share', 'rec_epa_tgt', 'Volume against efficiency'],
  ['TE', 'target_share', 'rec_epa_tgt', 'Volume against efficiency'], ['K', 'avg_dist', 'fg_oe', 'Attempt distance against FG over expected'], ['P', 'gross', 'epa_punt', 'Gross distance against EPA per punt'],
  ['DEF', 'pressures_pg', 'def_value', 'Sacks and hits per game against splash EPA'], ['TEAM', 'proe', 'off_epa', 'Does passing more pay? PROE against offensive EPA'], ['TEAM', 'off_epa', 'def_epa', 'Offence against defence (EPA per play)'],
  ['TEAM', 'go_rate', 'fd_wp_lost', 'Fourth-down go rate against win probability lost'], ['TEAM', 'sec_per_play_neutral', 'off_epa', 'Pace against efficiency'], ['TEAM', 'pa_rate', 'off_pass_epa', 'Play action against pass offence']
];
const NO_SHRINK = /^(n|g|games|age|season|composite|value|def_value|pts_oe|fg_oe|epa_total|rec_epa|scramble_epa|rush_epa_qb|.*_yds|.*_td|ints|sacks|qb_hits|tfl|tackles|pd|ff|att|carries|targets|rec|fga|fgm|fg_50|punts)$/;
let LAB = null, LABK = '';
const S0 = { kind: 'QB', min: null, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '', qual: true };
const MU = {};

/* Gridiron Value per game and in total (value.json, joined by player id) so the lab can plot our value model too. */
function withValue(G0, vr) {
  const ip = G0.cols.indexOf('pid');
  if (ip < 0 || !Object.keys(vr).length || G0.cols.indexOf('gvar_pg') >= 0) return G0;
  return { cols: G0.cols.concat(['gvar_pg', 'gvar']), rows: G0.rows.map(r => { const v = vr[String(r[ip])]; return r.concat([v && isNum(v.gvar_pg) ? v.gvar_pg : null, v && isNum(v.gvar) ? v.gvar : null]); }) };
}
const VMETRICS = () => [{ key: 'gvar_pg', label: GI.SP.specLabel('gvar_pg', 'Value per game'), group: 'Value', fmt: 'signed2', lower: false, desc: 'Points above a replacement-level player at the position, per game (Gridiron Value, value.json).' },
  { key: 'gvar', label: 'Value above replacement', group: 'Value', fmt: 'signed1', lower: false, desc: 'Points above a replacement-level player at the position over the season so far (Gridiron Value).' }];
function prep(raw, vraw) {
  const kinds = {};
  const vr = {};
  if (GI.ok(vraw) && vraw.rows) GI.colRows(vraw).forEach(r => { if (r && r.pid) vr[String(r.pid)] = r; });
  const mk = (g, cols, rows, metrics) => {
    const idx = {};
    cols.forEach((c, i) => { idx[c] = i; });
    const ms = metrics.filter(m => idx[m.key] !== undefined && rows.some(r => isNum(r[idx[m.key]])));
    const sk = g === 'TEAM' ? ['games', 'Games'] : (GI.SAMPLE[g] || []).find(s => idx[s[0]] !== undefined) || ['games', 'Games'];
    kinds[g] = { idx: idx, meta: GI.metaOf(metrics), metrics: ms, rows: rows, nKey: sk[0], nLabel: sk[1] };
  };
  if (GI.ok(raw) && raw.groups) {
    GI.cleanMetrics(raw.metrics); GI.cleanMetrics(raw.team_metrics);
    Object.keys(raw.groups).forEach(g => { const G0 = raw.groups[g] || {}; if (!Array.isArray(G0.cols) || !(G0.rows || []).length) return;
      const G = withValue(G0, vr), ms0 = GI.metricsFor(raw, g).length ? GI.metricsFor(raw, g) : (raw.metrics || []);
      mk(g, G.cols, G.rows, G.cols.length > G0.cols.length ? ms0.concat(VMETRICS()) : ms0); });
    if (raw.teams && Array.isArray(raw.teams.cols) && (raw.teams.rows || []).length) mk('TEAM', raw.teams.cols, raw.teams.rows, raw.team_metrics || []);
  }
  return kinds;
}
const G = () => LAB[S0.kind] || LAB[Object.keys(LAB)[0]];
function raw(r, key) { const i = G().idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
const idOf = r => String(S0.kind === 'TEAM' ? raw(r, 'team') : (raw(r, 'pid') || raw(r, 'id')));
const nOf = r => { const v = raw(r, G().nKey); return isNum(v) ? Number(v) : 0; };
const meta = key => G().meta[key] || { key: key, label: key === G().nKey ? G().nLabel : key };
const shrinkable = key => S0.kind !== 'TEAM' && !NO_SHRINK.test(key) && isNum(meta(key).stabilises_at) && ['int', '0'].indexOf(meta(key).fmt) < 0;
const kOf = key => (isNum(meta(key).stabilises_at) ? meta(key).stabilises_at * 3 / 7 : 200);
const lower = key => !!meta(key).lower;
const label = key => (meta(key).label || key) + (S0.shrink && shrinkable(key) ? ' (shrunk)' : '');
const fmt = (key, v) => GI.fmtVal(v, meta(key).fmt);
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S0.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!isNum(mu)) return v;
  const u = meta(key).unit, nv = u ? raw(r, u) : null, n = isNum(nv) ? Number(nv) : nOf(r), kk = kOf(key);
  return (n * v + kk * mu) / (n + kk);
}
function presetList() {
  const out = [], seen = {};
  PRESETS.filter(p => p[0] === S0.kind).forEach(p => { if (G().idx[p[1]] !== undefined && G().idx[p[2]] !== undefined && !seen[p[1] + p[2]]) { seen[p[1] + p[2]] = 1; out.push({ x: p[1], y: p[2], title: p[3] }); } });
  return out;
}
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; return { m: m, s: Math.sqrt(a.reduce((x, y) => x + (y - m) * (y - m), 0) / n) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }
function metricOpts(sel, colour) {
  return (colour ? '<option value="team">Team</option>' + (S0.kind !== 'TEAM' ? '<option value="pos">Position</option>' : '<option value="conf">Conference</option>') + '<option value="">One colour</option>' : '') +
    GI.SP.orderOpts(G().metrics.map(m => ({ key: m.key, label: m.label, lower: m.lower, group: m.group })), sel, GI.SP.headIds(S0.kind));
}

function draw(S) {
  const team = S0.kind === 'TEAM';
  const base0 = G().rows.filter(r => team || (nOf(r) >= S0.min && (!S0.qual || G().idx.qualified === undefined || raw(r, 'qualified') !== false)));
  Object.keys(MU).forEach(k => delete MU[k]);
  [S0.x, S0.y, S0.color].forEach(k => { if (k && G().idx[k] !== undefined && shrinkable(k)) MU[k] = GI.median(base0.map(r => raw(r, k))); });
  const rows = base0.filter(r => val(r, S0.x) !== null && val(r, S0.y) !== null);
  const noun = team ? 'teams' : (GI.GROUP_NAME[S0.kind] || 'players').toLowerCase();
  GI.set('lab-sub', rows.length + ' ' + noun + ' · ' + S + (team ? '' : ' · ' + S0.min + '+ ' + G().nLabel.toLowerCase() + (S0.qual ? ' · qualified' : '')));
  GI.set('lab-ours', GI.SP.ours(S0.x) || GI.SP.ours(S0.y) ? '<p class="gi-lab-axes">' + [['X', S0.x], ['Y', S0.y]].map(a => a[0] + ': <b>' + esc(meta(a[1]).label || a[1]) + '</b>' + GI.SP.oursTag(a[1])).join(' &nbsp;·&nbsp; ') + '</p>' + GI.SP.oursNote([[S0.x, meta(S0.x).label, team ? 'team' : 'player'], [S0.y, meta(S0.y).label, team ? 'team' : 'player']]) : '');
  if (rows.length < 3) { GI.ch.none('lab-chart', 'Too few for this view: lower the floor, untick qualified only, or pick metrics these players have (FTN charting starts in 2022, NGS in 2016).'); GI.set('lab-table', ''); GI.set('lab-note', ''); GI.set('lab-kpis', ''); return; }
  const xs = rows.map(r => val(r, S0.x)), ys = rows.map(r => val(r, S0.y));
  const mx = GI.median(xs), my = GI.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S0.x) ? -1 : 1, diry = lower(S0.y) ? -1 : 1;
  const ranked = rows.map(r => ({ r: r, z: dirx * (val(r, S0.x) - sx.m) / sx.s + diry * (val(r, S0.y) - sy.m) / sy.s })).sort((a, b) => b.z - a.z);
  const nm = r => (team ? GI.teamName(raw(r, 'team')) : (raw(r, 'name') || GI.playerName(idOf(r))));
  const short = r => (team ? raw(r, 'team') : GI.surnameOf(nm(r)));
  const tm = r => raw(r, 'team');
  const q = GI.fold(S0.q.trim());
  const hits = q ? rows.filter(r => GI.fold(nm(r) + ' ' + (tm(r) || '')).indexOf(q) >= 0) : [];
  const labelled = team ? rows : ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20));
  const sX = xs.slice().sort((a, b) => a - b), sY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(nOf), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => (team ? 14 : 6 + 13 * (hi > lo ? Math.sqrt((nOf(r) - lo) / (hi - lo)) : 0.5));
  const href = r => (team ? GI.teamHref(idOf(r), S) : GI.playerHref(idOf(r), S));
  const colourMetric = S0.color && ['team', 'pos', 'conf'].indexOf(S0.color) < 0 ? S0.color : null;
  const posCol = {};
  GI.ch.mount('lab-chart', T => {
    const cv = colourMetric ? rows.map(r => val(r, colourMetric)).filter(isNum) : [];
    const colourOf = r => {
      if (S0.color === 'team') return GI.ch.lift(GI.teamColour(tm(r)), T);
      if (S0.color === 'conf') return GI.teamInfo(tm(r)).conference === 'AFC' ? T.cat[1] : T.model;
      if (S0.color === 'pos') { const p = String(raw(r, 'pos') || '—'); if (!posCol[p]) posCol[p] = T.cat[Object.keys(posCol).length % 8]; return posCol[p]; }
      return T.model;
    };
    return {
      grid: { left: 8, right: colourMetric ? 70 : 20, top: 24, bottom: 34, containLabel: true },
      xAxis: GI.ch.ax(T, { name: label(S0.x), nameLocation: 'middle', nameGap: 28, scale: true, inverse: lower(S0.x), fmt: v => fmt(S0.x, v) }),
      yAxis: GI.ch.ax(T, { name: label(S0.y), scale: true, inverse: lower(S0.y), fmt: v => fmt(S0.y, v) }),
      visualMap: colourMetric && cv.length ? { type: 'continuous', dimension: 2, min: Math.min.apply(null, cv), max: Math.max.apply(null, cv), right: 0, top: 'middle', itemHeight: 140, itemWidth: 10, calculable: false,
        text: [lower(colourMetric) ? 'worse' : 'better', lower(colourMetric) ? 'better' : 'worse'], textStyle: { color: T.ink3, fontSize: 10 }, inRange: { color: lower(colourMetric) ? [T.pos, T.mid, T.neg] : [T.neg, T.mid, T.pos] } } : undefined,
      tooltip: GI.ch.tip(T, { formatter: p => { const r = p.data.r; return GI.ch.thead(esc(nm(r)) + (team ? '' : ' · ' + esc(tm(r) || ''))) +
        GI.ch.trow(p.color, label(S0.x), fmt(S0.x, val(r, S0.x)) + ' · ' + Math.round(pOf(sX, val(r, S0.x), dirx)) + 'th') + GI.ch.trow(p.color, label(S0.y), fmt(S0.y, val(r, S0.y)) + ' · ' + Math.round(pOf(sY, val(r, S0.y), diry)) + 'th') +
        (team ? '' : GI.ch.trow(T.ink3, G().nLabel, GI.int(nOf(r)))) + (colourMetric ? GI.ch.trow(T.ink3, label(colourMetric), fmt(colourMetric, val(r, colourMetric))) : ''); } }),
      series: [{ type: 'scatter', symbolSize: v => v[3],
        data: rows.map(r => ({ value: [val(r, S0.x), val(r, S0.y), colourMetric ? val(r, colourMetric) : 0, size(r)], r: r, href: href(r),
          itemStyle: colourMetric ? { borderColor: T.s1, borderWidth: 0.7, opacity: 0.9 } : { color: colourOf(r), borderColor: T.s1, borderWidth: 0.7, opacity: 0.88 },
          label: { show: labelled.indexOf(r) >= 0, formatter: short(r), position: 'top', color: hits.indexOf(r) >= 0 ? T.model : T.ink2, fontSize: 10, fontWeight: 600 } })),
        labelLayout: { hideOverlap: true }, emphasis: { scale: 1.4, label: { show: true } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4] }, label: { show: false }, data: [{ xAxis: mx }, { yAxis: my }] } }]
        .concat(hits.length ? [{ type: 'scatter', silent: true, symbol: 'circle', symbolSize: 22, z: 5, itemStyle: { color: 'transparent', borderColor: T.model, borderWidth: 2 }, data: hits.map(r => [val(r, S0.x), val(r, S0.y)]) }] : [])
    };
  }, 'Scatter of ' + label(S0.x) + ' against ' + label(S0.y));
  const rr = GI.corr(xs, ys), mX = meta(S0.x), mY = meta(S0.y);
  GI.set('lab-note', 'Correlation on screen r = ' + GI.num(rr, 2) + ' (' + rows.length + ' ' + noun + '). Dashed lines are medians; ' + (lower(S0.x) || lower(S0.y) ? 'axes where less is better are reversed, so ' : '') + 'better is up and to the right. ' +
    (team ? '' : 'Labelled: the eight furthest into the good corner, the four furthest from it' + (hits.length ? ', and your search' : '') + '. Dot size is the sample. ') + 'Tap a dot for the page.' +
    (S0.shrink && !team ? ' "Shrunk" rates are pulled towards the median by their stabilisation point' + (shrinkable(S0.x) ? ' (' + esc(mX.label) + ' k = ' + GI.int(kOf(S0.x)) + ')' : '') + (shrinkable(S0.y) ? ' (' + esc(mY.label) + ' k = ' + GI.int(kOf(S0.y)) + ')' : '') + '.' : '') +
    (mX.desc ? '<br><b>' + esc(mX.label) + '</b>: ' + esc(mX.desc) : '') + (mY.desc ? '<br><b>' + esc(mY.label) + '</b>: ' + esc(mY.desc) : ''));
  const best = ranked[0] ? ranked[0].r : null;
  GI.set('lab-kpis', GI.kpis([GI.kpi('Correlation', GI.num(rr, 2), 'r on screen, ' + rows.length + ' ' + noun, { tip: 'Pearson correlation of the two axes for the rows shown' }),
    best ? GI.kpi('Best on both', esc(team ? GI.teamAbbr(idOf(best)) : GI.surnameOf(nm(best))), 'the furthest into the good corner (combined standard score ' + GI.num(ranked[0].z, 2) + ')', { signal: true, href: href(best) }) : '',
    GI.kpi('Medians', fmt(S0.x, mx) + ' · ' + fmt(S0.y, my), esc(label(S0.x)) + ' · ' + esc(label(S0.y)), { text: true })]));
  const lrows = ranked.slice(0, 300).map(o => { const r = o.r, vx = val(r, S0.x), vy = val(r, S0.y);
    return { id: idOf(r), name: nm(r), team: tm(r) || (team ? idOf(r) : null), sub: team ? (GI.teamInfo(idOf(r)).division || '') : [raw(r, 'pos') ? GI.posLabel(raw(r, 'pos')) : '', GI.teamAbbr(tm(r))].filter(Boolean).join(' · '), n: nOf(r), vx: vx, px: pOf(sX, vx, dirx), vy: vy, py: pOf(sY, vy, diry), z: o.z }; });
  QK.leaderboard(document.getElementById('lab-table'), { dense: true, rank: true, maxHeight: 600, rows: lrows, rowHref: r => (team ? GI.teamHref(r.id, S) : GI.playerHref(r.id, S)),
    columns: [{ key: 'name', label: team ? 'Team' : 'Player', type: 'entity', sub: 'sub', mark: r => ({ name: GI.teamName(r.team), abbr: GI.teamAbbr(r.team), colour: GI.teamInfo(r.team).colour }), href: r => (team ? GI.teamHref(r.id, S) : GI.playerHref(r.id, S)) }]
      .concat(team ? [] : [{ key: 'n', label: G().nLabel, num: true }])
      .concat([{ key: 'px', label: label(S0.x), type: 'pctl', pctl: 'px', fmt: (v, r) => fmt(S0.x, r.vx), tip: 'Cell colour: percentile on screen (100 = best)' }, { key: 'py', label: label(S0.y), type: 'pctl', pctl: 'py', fmt: (v, r) => fmt(S0.y, r.vy), tip: 'Cell colour: percentile on screen (100 = best)' },
        { key: 'z', label: 'Combined', type: 'bar', fmt: v => '<b>' + GI.num(v, 2) + '</b>', tip: 'Sum of standard scores in the better direction' }]) });
  GI.SP.tagHeads(document.getElementById('lab-table'), { px: S0.x, py: S0.y });
  GI.setHashQuiet(GI.ghref('lab', S, { g: S0.kind, x: S0.x, y: S0.y }));
}

GI.route('lab', function (el, params) {
  const S = Number(params.season);
  return Promise.all([GI.load(GI.ypath('lab.json', S)), GI.load(GI.ypath('value.json', S)).catch(() => null), GI.SP.specReady()]).then(all => {
    const rawD = all[0];
    if (!el.isConnected) return;
    const head = GI.pageHead('Lab · ' + S, 'Scatter lab', 'Any two metrics for a position group or the teams. Presets ask the questions the models were built for.') + GI.sectionNav('lab', 'lab') + QK.note('<b>How to read it:</b> each dot is a player or a team, placed on any two metrics. Up and right is not always better: a metric marked ↓ is better when lower, and tendencies are neither good nor bad.');
    if (LABK !== String(S)) { LAB = prep(rawD, all[1]); LABK = String(S); S0.min = null; S0.x = ''; S0.y = ''; S0.preset = 0; }
    if (!Object.keys(LAB).length) { el.innerHTML = head + GI.notBuilt('The ' + S + ' lab file', rawD); return; }
    const qy = params.query || {};
    if (qy.g && LAB[String(qy.g).toUpperCase()]) S0.kind = String(qy.g).toUpperCase();
    if (!LAB[S0.kind]) S0.kind = Object.keys(LAB)[0];
    el.innerHTML = head + '<div id="lab-kpis"></div><div class="gi-toolbar">' + GI.seg('lab-kind', GI.GROUPS.concat(['TEAM']).map(g => [g, g === 'TEAM' ? 'Teams' : g, !LAB[g]]), S0.kind, 'Group') + '</div>' +
      GI.card('<span id="lab-title">Scatter</span>', '<span id="lab-sub"></span>', '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.field('Preset', '<select id="lab-preset" class="qk-select"></select>') +
        GI.field('X axis', '<select id="lab-x" class="qk-select"></select>') + GI.field('Y axis', '<select id="lab-y" class="qk-select"></select>') + '<button type="button" class="qk-btn" id="lab-swap" aria-label="Swap the axes">⇄ Swap</button>' +
        GI.field('Colour', '<select id="lab-color" class="qk-select"></select>') + '<label class="gi-field" id="lab-min-w"><span>Min <span id="lab-min-u"></span> <b id="lab-min-v"></b></span><input id="lab-min" type="range" min="0" max="700" step="1"></label>' +
        '<label class="gi-check" id="lab-qual-w"><input id="lab-qual" type="checkbox"> qualified only</label><label class="gi-check" id="lab-shrink-w"><input id="lab-shrink" type="checkbox"> shrink by stabilisation</label>' +
        GI.field('Highlight', '<input id="lab-q" class="qk-input" type="search" placeholder="Player or team">') + '</div>' + '<div id="lab-ours"></div>' + GI.chartBox('lab-chart', 520, 'Scatter') + '<p class="gi-cap" id="lab-note"></p>') +
      GI.card('Ranked', 'By the combined standard score on both axes (top 300); cells coloured by percentile on screen', '<div id="lab-table"></div>', { flush: true });
    const $ = id => document.getElementById(id);
    const applyPreset = () => { const P = presetList(); if (S0.preset < 0 || !P.length) return; const p = P[S0.preset] || P[0]; S0.x = p.x; S0.y = p.y; };
    const reset = () => {
      const g = G();
      const maxN = Math.max.apply(null, g.rows.map(nOf).concat([10]));
      $('lab-min').max = String(Math.ceil(maxN));
      if (S0.min === null || S0.min > maxN) S0.min = 0;
      if (!S0.x || g.idx[S0.x] === undefined || !S0.y || g.idx[S0.y] === undefined) { if (S0.preset < 0) S0.preset = 0; applyPreset(); }
      if (!S0.x || !S0.y || g.idx[S0.x] === undefined || g.idx[S0.y] === undefined) { S0.x = (g.metrics[0] || {}).key || g.nKey; S0.y = (g.metrics[1] || {}).key || g.nKey; S0.preset = -1; }
      if (S0.color && ['team', 'pos', 'conf'].indexOf(S0.color) < 0 && g.idx[S0.color] === undefined) S0.color = 'team';
      if (S0.color === 'pos' && S0.kind === 'TEAM') S0.color = 'team';
      if (S0.color === 'conf' && S0.kind !== 'TEAM') S0.color = 'team';
    };
    const sync = () => {
      const P = presetList();
      $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S0.preset ? ' selected' : '') + '>' + esc(p.title) + '</option>').join('') + '<option value="-1"' + (S0.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
      $('lab-x').innerHTML = metricOpts(S0.x); $('lab-y').innerHTML = metricOpts(S0.y); $('lab-x').value = S0.x; $('lab-y').value = S0.y;
      $('lab-color').innerHTML = metricOpts(S0.color, true); $('lab-color').value = S0.color;
      $('lab-min').value = S0.min; $('lab-min-v').textContent = S0.min; $('lab-min-u').textContent = G().nLabel.toLowerCase();
      $('lab-min-w').style.display = S0.kind === 'TEAM' ? 'none' : '';
      $('lab-qual-w').style.display = S0.kind === 'TEAM' || G().idx.qualified === undefined ? 'none' : '';
      $('lab-shrink-w').style.display = S0.kind === 'TEAM' ? 'none' : '';
      $('lab-shrink').checked = S0.shrink; $('lab-q').value = S0.q; $('lab-qual').checked = S0.qual;
      GI.set('lab-title', esc(S0.preset >= 0 && P[S0.preset] ? P[S0.preset].title : label(S0.x) + ' v ' + label(S0.y)));
    };
    if (qy.x && G().idx[qy.x] !== undefined) { S0.x = qy.x; S0.preset = -1; }
    if (qy.y && G().idx[qy.y] !== undefined) { S0.y = qy.y; S0.preset = -1; }
    reset();
    sync();
    const redraw = () => { sync(); draw(S); };
    GI.wireSeg(el, 'lab-kind', v => { if (!LAB[v]) return; S0.kind = v; S0.x = ''; S0.y = ''; S0.preset = 0; S0.min = null; reset(); redraw(); });
    $('lab-preset').addEventListener('change', e => { S0.preset = parseInt(e.target.value, 10); applyPreset(); redraw(); });
    $('lab-x').addEventListener('change', e => { S0.x = e.target.value; S0.preset = -1; redraw(); });
    $('lab-y').addEventListener('change', e => { S0.y = e.target.value; S0.preset = -1; redraw(); });
    $('lab-swap').addEventListener('click', () => { const t = S0.x; S0.x = S0.y; S0.y = t; S0.preset = -1; redraw(); });
    $('lab-color').addEventListener('change', e => { S0.color = e.target.value; redraw(); });
    $('lab-min').addEventListener('input', e => { S0.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S0.min; });
    $('lab-min').addEventListener('change', redraw);
    $('lab-shrink').addEventListener('change', e => { S0.shrink = e.target.checked; redraw(); });
    $('lab-qual').addEventListener('change', e => { S0.qual = e.target.checked; redraw(); });
    let timer = null;
    $('lab-q').addEventListener('input', e => { S0.q = e.target.value; clearTimeout(timer); timer = setTimeout(() => draw(S), 250); });
    draw(S);
  });
});

})(window.GI);
