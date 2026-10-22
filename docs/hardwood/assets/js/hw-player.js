/* The Quant Hardwood — the player page (#/<L>/player/<pid>).
 *
 * Overview tab: a header with the team colour and the season line; headline numbers (impact, value, minutes,
 * award odds); percentiles against his position pool or the league; season by season (impact chart and table);
 * the game log as a chart with splits (home/away, wins/losses, last ten); the shot chart on the half court; value
 * (projected WAR by season and the four-season band); similar players and awards.
 * Detail tab (?tab=detail): the pre-redesign player page in full (the whole catalogue, radar, on/off, clutch,
 * projection, lineups, game log table).
 * Data: <L>/players/<pid>.json (career), <L>/<S>/players.json (catalogue), value.json, valuation.json (current). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const PCT_KEYS = [['pts100', 'Scoring / 100'], ['ts', 'True shooting'], ['usg', 'Usage'], ['pox100', 'Shot-making'], ['ast_pct', 'Assist rate'], ['tov_pct', 'Ball security'],
  ['trb_pct', 'Rebounding'], ['stl_pct', 'Steal rate'], ['blk_pct', 'Block rate'], ['hpm_o', 'Offensive impact'], ['hpm_d', 'Defensive impact'], ['hpm', 'Total impact'], ['on_off', 'On/off'], ['wpa', 'Win prob. added']];

/* Hex cells on the half court: size = volume, colour = points per shot against the league from the same spot. */
function hexMap(node, cells) {
  node.classList.add('qk-chart', 'sq', 'qk-surface');
  const S = QKC.SURF.court;
  node.style.setProperty('--ar', (S.x[1] - S.x[0]) + ' / ' + (S.y[1] - S.y[0]));
  const ns = cells.map(c => c.n || 1).sort((x, y) => x - y);
  const capN = ns[Math.floor(ns.length * 0.9)] || 1;
  return QKC.mount(node, T => {
    node.style.backgroundImage = 'url("data:image/svg+xml,' + encodeURIComponent(QKC.surfaceSVG('court', T)) + '")';
    return {
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'value', min: S.x[0], max: S.x[1], show: false }, yAxis: { type: 'value', min: S.y[0], max: S.y[1], show: false },
      visualMap: { show: true, dimension: 2, min: -0.4, max: 0.4, inRange: { color: [T.neg, T.mid, T.pos] }, orient: 'horizontal', right: 8, top: 6, itemWidth: 10, itemHeight: 90, calculable: false,
        text: ['better', 'worse'], textStyle: { color: T.ink3, fontSize: 10 } },
      tooltip: QKC.tooltip(T, { formatter: p => { const c = cells[p.dataIndex]; return '<div style="font-weight:600">' + (c.n || 0) + ' shots</div>' + QKC.tipRow(p.color, 'FG%', HW.fmtVal(c.fg, 'pct')) + QKC.tipRow(p.color, 'Pts / shot', U.f(c.pps, 2)) + QKC.tipRow(p.color, 'v league', U.signed(c.d, 2)); } }),
      series: [{ type: 'scatter', symbol: 'path://M0,-1L0.866,-0.5L0.866,0.5L0,1L-0.866,0.5L-0.866,-0.5Z', data: cells.map(c => [c.x, c.y, isNum(c.d) ? c.d : 0]),
        symbolSize: (v, p) => { const px = (node.clientWidth || 400) / 50 * 3.1; return Math.max(3, px * (0.35 + 0.65 * Math.sqrt(Math.min(1, (cells[p.dataIndex].n || 1) / capN)))); }, itemStyle: { opacity: 0.92 } }]
    };
  }, { label: 'Shot chart' });
}

function splits(log) {
  const agg = list => {
    const n = list.length; if (!n) return null;
    const s = k => list.reduce((a, r) => a + (isNum(r[k]) ? Number(r[k]) : 0), 0);
    const tsa = s('fga') + 0.44 * s('fta');
    return { n: n, min: s('min') / n, pts: s('pts') / n, reb: s('reb') / n, ast: s('ast') / n, ts: tsa > 0 ? s('pts') / (2 * tsa) : null, pm: s('pm') / n, gs: s('game_score') / n };
  };
  const win = r => (isNum(r.pm) ? r.pm > 0 : null);
  return [['Season', log], ['Home', log.filter(r => r.home)], ['Away', log.filter(r => !r.home)], ['Team won', log.filter(r => win(r) === true)], ['Team lost', log.filter(r => win(r) === false)], ['Last 10', log.slice(-10)]]
    .map(x => Object.assign({ split: x[0] }, agg(x[1]) || {})).filter(x => x.n);
}

function render(el, params) {
  const L = U.L(params), pid = String(params.id || '');
  const tab = U.tab(params, ['overview', 'detail'], 'overview');
  let S = U.S(params);
  const curS = HW.currentSeason(L);
  el.innerHTML = QK.skeleton('lines', 6);
  return HW.load(L + '/players/' + pid + '.json').then(career => {
    if (!U.alive(el)) return null;
    const seasons = ((career && career.seasons) || []).map(x => x.season);
    // a season he did not play: show his latest one before it (the header says so)
    let asked = null;
    if (seasons.length && seasons.indexOf(S) < 0) { const prev = seasons.filter(x => x <= S).sort((a, b) => b - a)[0] || Math.max.apply(null, seasons); if (prev !== S) { asked = S; S = prev; } }
    const isCurS = U.isCur(L, S);
    return Promise.all([HW.load(HW.path('players.json', L, S)), HW.load(HW.path('value.json', L, S)), HW.load(HW.path('valuation.json', L, curS))]).then(a => {
      if (!U.alive(el)) return;
      draw(el, L, S, pid, career, U.ok(a[0]) ? a[0] : null, U.ok(a[1]) ? a[1] : null, U.ok(a[2]) ? a[2] : null, asked, tab, params, isCurS);
    });
  });
}

function draw(el, L, S, pid, career, cat, sv, val, asked, tab, params) {
  const P = (cat && cat.players) || {};
  const p = P[pid] || null;
  const cs = ((career && career.seasons) || []).slice().sort((a, b) => a.season - b.season);
  const srow = cs.find(x => x.season === S) || {};
  const cur = career && career.current && (!career.current.season || career.current.season === S) ? career.current : {};
  const vrow = U.rowsOf(val).find(x => String(x.id) === pid) || null;
  const swar = U.rowsOf(sv).find(x => String(x.id) === pid) || null;
  const name = (p && p.name) || (career && career.name) || (vrow && vrow.name) || HW.playerName(L, pid);
  const team = (vrow && vrow.team) || (p && p.team) || srow.team || null;
  const col = team ? U.tcol(L, team) : QK.cssVar('--c-1');
  const v = (p && p.values) || {};
  const pos = (p && p.pos) || (career && career.pos) || (vrow && vrow.pos) || '';
  const age = p && isNum(p.age) ? Math.floor(p.age) : vrow && isNum(vrow.age) ? Math.floor(vrow.age) : null;
  document.title = name + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
  const line = [['PPG', v.pts_g, '1'], ['RPG', v.reb_g, '1'], ['APG', v.ast_g, '1'], ['TS%', v.ts, 'pct'], ['MPG', v.mpg, '1']].filter(x => isNum(x[1]));
  const lineFallback = !line.length && srow.season ? [['PPG', srow.pts, '1'], ['RPG', srow.reb, '1'], ['APG', srow.ast, '1'], ['TS%', srow.ts, 'pct']].filter(x => isNum(x[1])) : [];
  const ini = QK.fmt.initials(name);
  let h = '<div class="qk-hero" style="--tc:' + esc(col) + '"><div class="hw-teamhead"><div class="qk-avatar" aria-hidden="true">' + esc(ini) + '</div><div><div class="qk-kicker">' + esc(HW.leagueName(L) + ' · ' + HW.seasonLabel(L, S)) + '</div><h1>' + esc(name) + '</h1>' +
    '<div class="qk-hero-meta">' + (team ? '<span>' + U.teamEnt(L, team, { season: S }) + '</span>' : '<span>Free agent</span>') + (pos ? '<span>' + esc(pos) + '</span>' : '') + (age !== null ? '<span>Age <b>' + age + '</b></span>' : '') +
    (vrow && vrow.inj ? '<span class="hw-inj">' + esc(vrow.inj) + '</span>' : '') + (asked ? '<span class="qk-badge">No ' + esc(HW.seasonLabel(L, asked)) + ' games yet: showing ' + esc(HW.seasonLabel(L, S)) + '</span>' : '') + '</div></div>' +
    '<div class="qk-hero-stats">' + line.concat(lineFallback).map(x => '<div class="qk-hero-stat"><div class="l">' + x[0] + '</div><div class="v">' + HW.fmtVal(x[1], x[2]) + '</div></div>').join('') + '</div></div></div>';
  const base = HW.playerHref(L, pid, S);
  h += U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'detail', label: 'Full catalogue, on/off and lineups', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab);
  if (tab === 'detail') { el.innerHTML = h + '<div class="hw-sub"></div>'; U.legacy('player', el.querySelector('.hw-sub'), params); return; }
  // headline numbers
  const k = [];
  const hpm = isNum(v.hpm) ? v.hpm : srow.hpm;
  if (isNum(hpm)) k.push(QK.kpi({ label: 'Impact (HPM)', value: U.signed(hpm, 1), sub: 'offence ' + U.signed(isNum(v.hpm_o) ? v.hpm_o : srow.o, 1) + ' · defence ' + U.signed(isNum(v.hpm_d) ? v.hpm_d : srow.d, 1), tip: 'Hardwood Plus-Minus: points per 100 possessions better than an average player' }));
  if (swar && isNum(swar.war)) k.push(QK.kpi({ label: 'Wins above replacement', value: U.f(swar.war, 1), sub: HW.seasonLabel(L, S) + (isNum(swar.pct) ? ' · ' + HW.ordinal(swar.pct) + ' percentile' : '') }));
  if (vrow) k.push(QK.kpi({ label: 'Projected WAR', value: U.f(vrow.w0, 1), sub: 'rest of ' + HW.seasonLabel(L, HW.currentSeason(L)) + ' · 4-yr value ' + U.f(vrow.v, 1), tip: 'Valuation over four seasons, discounted; see Value & Moves' }));
  if (p) k.push(QK.kpi({ label: 'Minutes', value: U.f(p.min, 0), sub: (p.gp || 0) + ' games' + (p.qualified === false ? ' · below the floor' : '') }));
  const aw = cur.awards || {};
  const best = Object.keys(aw).filter(x => isNum(aw[x]) || (aw[x] && isNum(aw[x].p))).sort((a, b) => (isNum(aw[b]) ? aw[b] : aw[b].p) - (isNum(aw[a]) ? aw[a] : aw[a].p))[0];
  if (best) k.push(QK.kpi({ label: 'Award odds', value: U.pct(isNum(aw[best]) ? aw[best] : aw[best].p), sub: best.toUpperCase() }));
  if (k.length) h += '<div class="qk-kpis hw-kpis">' + k.join('') + '</div>';
  const pct = p ? (p.pct_pool || p.pct || {}) : {};
  const pk = PCT_KEYS.filter(x => isNum(pct[x[0]]));
  const log = (cur.log || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const cells = cur.shots && cur.shots.grid ? U.rowsOf(cur.shots.grid).filter(c => isNum(c.x) && isNum(c.y) && c.y <= 41.5).map(c => Object.assign({}, c, { d: isNum(c.pps_diff) ? c.pps_diff : (isNum(c.pps) && isNum(c.lg_pps) ? c.pps - c.lg_pps : null) })) : [];
  h += '<div class="qk-grid hw-sec">';
  if (pk.length) h += U.card2('Percentiles', '<span id="pp-pbasis">Against ' + esc({ G: 'guards', F: 'forwards', C: 'centres' }[(p || {}).pool] || 'his position pool') + '</span>',
    '<div class="qk-seg" id="pp-seg" role="group" aria-label="Compare with" style="margin-bottom:12px"><button type="button" data-value="pool" aria-pressed="true">Position</button><button type="button" data-value="league" aria-pressed="false">League</button></div><div id="pp-pct"></div>',
    { cls: 'qk-span-5' });
  if (cs.length > 1) h += U.card2('Season by season', 'Impact per 100 possessions: total, offence and defence', U.chart('pp-career', 300, 'Impact by season'), { cls: pk.length ? 'qk-span-7' : 'qk-span-12' });
  h += '</div>';
  if (log.length) {
    h += '<div class="qk-grid hw-sec">' + U.card2('Game by game', 'Game score per game (Hollinger); green when his team was ahead with him (plus-minus)', U.chart('pp-log', 220, 'Game score per game'), { cls: 'qk-span-7' }) +
      U.card2('Splits', 'Per game', '<div id="pp-splits"></div>', { cls: 'qk-span-5', flush: true }) + '</div>';
  }
  if (cells.length || vrow) {
    h += '<div class="qk-grid hw-sec">';
    if (cells.length) h += U.card2('Shot chart', 'Size is volume; colour is points per shot against the league from the same spot', '<div id="pp-shots"></div>', { cls: vrow ? 'qk-span-6' : 'qk-span-12' });
    if (vrow) h += U.card2('Value', 'Projected WAR by season (mean path; ages and survival priced in). Four-season value ' + U.f(vrow.v, 1) + ' (80% band ' + U.f(vrow.p10, 1) + ' to ' + U.f(vrow.p90, 1) + ')',
      U.chart('pp-val', 240, 'Projected WAR by season'), { cls: cells.length ? 'qk-span-6' : 'qk-span-12', foot: U.link(HW.href(L, 'value'), 'Value & Moves') });
    h += '</div>';
  }
  h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Career</h2><div class="qk-sub">Box scores from 1997, play-by-play numbers (RAPM, WPA) from about 2017.</div></div></div><div class="qk-card"><div id="pp-ctab"></div></div></section>';
  const sim = (career && career.similar) || [], awards = (career && career.career_awards) || [];
  if (sim.length || awards.length) {
    h += '<div class="qk-grid hw-sec">' + (sim.length ? U.card2('Similar players', 'Nearest on the percentile profile', '<ul class="hw-list">' + sim.slice(0, 8).map(x => '<li>' + U.playerEnt(L, x.id, x.name, null, HW.seasonLabel(L, x.season), x.season) + '<span class="v">' + U.f(x.distance, 2) + '</span></li>').join('') + '</ul>', { cls: awards.length ? 'qk-span-7' : 'qk-span-12', flush: true }) : '') +
      (awards.length ? U.card2('Awards', '', '<div class="hw-pills">' + awards.slice().sort((a, b) => b[0] - a[0]).map(x => '<span class="qk-badge accent">' + esc(HW.seasonLabel(L, x[0]) + ' ' + x[1]) + '</span>').join('') + '</div>', { cls: sim.length ? 'qk-span-5' : 'qk-span-12' }) : '') + '</div>';
  }
  if (!p && !cs.length) h += U.empty('No numbers', 'This player has no games in the data yet.');
  el.innerHTML = h;

  if (pk.length) {
    const drawPct = basis => {
      const src = basis === 'league' ? (p.pct || {}) : (p.pct_pool || p.pct || {});
      const meta = {}; ((cat && cat.metrics) || []).forEach(m => { meta[m.key] = m; });
      document.getElementById('pp-pct').innerHTML = QK.pctlBars(pk.filter(x => isNum(src[x[0]])).map(x => ({ label: x[1], pctl: src[x[0]], value: HW.fmtVal(v[x[0]], (meta[x[0]] || {}).fmt) })));
      document.getElementById('pp-pbasis').textContent = basis === 'league' ? 'Against every qualified player' : 'Against ' + ({ G: 'guards', F: 'forwards', C: 'centres' }[p.pool] || 'his position pool');
    };
    drawPct('pool');
    QK.seg(document.getElementById('pp-seg'), drawPct);
  }
  if (document.getElementById('pp-career')) {
    QKC.line('#pp-career', { x: cs.map(x => HW.seasonLabel(L, x.season)), series: [
      { name: 'Total', data: cs.map(x => (isNum(x.hpm) ? Math.round(x.hpm * 10) / 10 : null)), color: col, width: 3 },
      { name: 'Offence', data: cs.map(x => (isNum(x.o) ? Math.round(x.o * 10) / 10 : null)), dash: true },
      { name: 'Defence', data: cs.map(x => (isNum(x.d) ? Math.round(x.d * 10) / 10 : null)), dash: true }], yFmt: v2 => U.signed(v2, 1), ref: { y: 0 }, xName: 'Season', yName: 'HPM per 100' });
  }
  if (log.length) {
    QKC.mount('#pp-log', T => ({
      grid: { left: 8, right: 12, top: 28, bottom: 30, containLabel: true },
      xAxis: QKC.axis(T, { type: 'category', data: log.map(r => HW.fmtDate(r.date, { year: false, weekday: false })), split: false, line: true, name: 'Game date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { name: 'Game score', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = log[ps[0].dataIndex];
        return '<div style="font-weight:600">' + esc(HW.fmtDate(r.date, { year: false }) + ' ' + (r.home ? 'v ' : '@ ') + HW.teamAbbr(L, r.opp)) + '</div>' + QKC.tipRow(ps[0].color, 'Game score', U.f(r.game_score, 1)) +
          QKC.tipRow(T.other, 'Line', (r.pts || 0) + ' pts · ' + (r.reb || 0) + ' reb · ' + (r.ast || 0) + ' ast') + QKC.tipRow(T.other, '+/-', U.signed(r.pm, 0)); } }),
      series: [{ type: 'bar', barMaxWidth: 14, data: log.map(r => ({ value: isNum(r.game_score) ? Math.round(r.game_score * 10) / 10 : 0, href: r.game ? HW.gameHref(L, r.game, S) : undefined,
        itemStyle: { color: r.pm > 0 ? T.up : r.pm < 0 ? T.down : T.other, borderRadius: [3, 3, 0, 0] } })) }]
    }), { label: 'Game score per game' });
    QK.table(document.getElementById('pp-splits'), { dense: true, rows: splits(log), columns: [{ key: 'split', label: 'Split', sort: false }, { key: 'n', label: 'G', num: true }, { key: 'min', label: 'Min', num: true, fmt: x => U.f(x, 1) },
      { key: 'pts', label: 'Pts', num: true, fmt: x => U.f(x, 1) }, { key: 'reb', label: 'Reb', num: true, fmt: x => U.f(x, 1) }, { key: 'ast', label: 'Ast', num: true, fmt: x => U.f(x, 1) }, { key: 'ts', label: 'TS%', num: true, fmt: x => HW.fmtVal(x, 'pct') }, { key: 'pm', label: '+/-', num: true, fmt: x => U.sgnHTML(x, 1) }] });
  }
  if (cells.length) hexMap(document.getElementById('pp-shots'), cells);
  if (vrow) {
    const slots = val && Array.isArray(val.slots) && val.slots.length === 4 ? val.slots.map(x => String(x).replace(/^rest of /, 'Rest of ')) : ['Rest of season', '+1', '+2', '+3'];
    QKC.bar('#pp-val', { cats: slots, series: [{ name: 'WAR', data: [vrow.w0, vrow.w1, vrow.w2, vrow.w3].map(x => (isNum(x) ? Math.round(x * 10) / 10 : 0)) }], labels: true, fmt: x => U.f(x, 1), colors: [col, col, col, col], valName: 'Projected WAR', catName: 'Season',
      max: v => (v.max > 0 ? Math.ceil(v.max * 12) / 10 : 0) });
  }
  const ct = document.getElementById('pp-ctab');
  if (cs.length) {
    QK.table(ct, { dense: true, sort: { key: 'season', dir: 'desc' }, rows: cs, columns: [
      { key: 'season', label: 'Season', num: true, fmt: x => '<a class="hw-link" href="' + esc(HW.playerHref(L, pid, x)) + '">' + esc(HW.seasonLabel(L, x)) + '</a>' },
      { key: 'team', label: 'Team', fmt: x => U.teamEnt(L, x, { abbr: true }) }, { key: 'gp', label: 'GP', num: true }, { key: 'min', label: 'Min', num: true, fmt: x => U.f(x, 0) },
      { key: 'pts', label: 'Pts', num: true, fmt: x => U.f(x, 1) }, { key: 'reb', label: 'Reb', num: true, fmt: x => U.f(x, 1) }, { key: 'ast', label: 'Ast', num: true, fmt: x => U.f(x, 1) },
      { key: 'ts', label: 'TS%', num: true, fmt: x => HW.fmtVal(x, 'pct') }, { key: 'hpm', label: 'HPM', num: true, fmt: x => '<b>' + U.signed(x, 1) + '</b>' },
      { key: 'rapm', label: 'RAPM', num: true, fmt: x => U.signed(x, 1) }, { key: 'wpa', label: 'WPA', num: true, fmt: x => U.signed(x, 2) }] });
  } else ct.innerHTML = U.empty('No career file', 'The career history is built with the season catalogues.');
  HW.setMeta('');
}

HW.page('player', render);
})(window.HW);
