/* The Quant Rink — the player page (#/player/<pid>), on the kit.
 *
 * Hero (club colour, number, position, age, size); KPI strip; Overview: percentiles against his position
 * (Savant-style bars), season by season (chart against the league and the table), this season's game log
 * chart, splits (by strength, home and away, last ten), the shot map, value (this season and the four-season
 * valuation), linemates and similar players; Detail (?view=detail): the full pre-redesign player page.
 *
 * Reads data/players/<pid>.json, data/glossary.json (labels), <S>/value.json and <S>/valuation.json (current). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
let LABELS = null;
function labels() {
  if (LABELS) return Promise.resolve(LABELS);
  return RK.load('glossary.json').then(g => {
    LABELS = { skater: {}, goalie: {} };
    ((g && g.groups) || []).forEach(gr => (gr.entries || []).forEach(e => { const k = e.kind === 'goalie' ? 'goalie' : 'skater'; if (!LABELS[k][e.key]) LABELS[k][e.key] = e; }));
    return LABELS;
  });
}

const SK_PCT = [
  ['Scoring', ['p60', 'g60', 'ixg60_all', 'sh_pct', 'gax']],
  ['Play driving (5v5)', ['xgf_pct', 'cf_pct', 'xgf_pct_rel', 'rapm_off', 'rapm_def']],
  ['Value', ['gar', 'gar_ev_off', 'gar_ev_def', 'gar_pp']],
  ['Physical and more', ['hits60', 'blocks60', 'take60', 'pen_diff60', 'fo_pct', 'edge_max_speed']]
];
const G_PCT = [
  ['Results', ['sv_pct', 'gsax', 'gsax60', 'qs_pct', 'gaa']],
  ['By danger', ['sv_pct_low', 'sv_pct_med', 'sv_pct_high', 'gsax_high']],
  ['By situation', ['sv_pct_5v5', 'sv_pct_sh', 'reb_rate']]
];
function fmtBy(meta, v) {
  if (!isNum(v)) return '—';
  const f = (meta || {}).fmt;
  if (f === 'pct') return U.pct(v, 1);
  if (f === 'toi_min') return RK.fmtTOI(v, { minutes: true });
  if (f === 'int') return String(Math.round(v));
  if (f === 'goals') return U.signed(v, 2);
  return RK.fmtVal ? RK.fmtVal(v, f || '2') : U.f(v, 2);
}
function age(dob) { const d = RK.parseDate(dob); if (!d) return null; return Math.floor((Date.now() - d.getTime()) / (365.25 * 864e5)); }

function render(el, params, state) {
  const pid = String(params.id);
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'overview';
  const S = RK.currentSeason();
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([RK.loadPlayer(pid), labels(), RK.loadYear('value.json', S), RK.loadYear('valuation.json', S)]).then(res => {
    if (!U.alive(el)) return;
    const p = res[0];
    if (!p || !p.name) { el.innerHTML = U.secHead('players', RK.playerName(pid), 'No career file for this player yet.', null, null, 'NHL · Player') + U.card2('Not found', '', QK.empty('No player ' + pid, 'Try the search.')); return; }
    const goalie = p.kind === 'goalie' || p.pos === 'G';
    const LB = res[1][goalie ? 'goalie' : 'skater'] || {};
    const c = p.current || null;
    const seasons = (p.seasons || []).slice().sort((a, b) => a.season - b.season);
    const last = seasons[seasons.length - 1] || {};
    const team = (c && last.season === c.season ? last.team : null) || last.team || RK.player(pid).team;
    const vrow = U.rowsOf(RK.ok(res[2]) ? res[2] : null).find(r => String(r.id) === pid) || null;
    const vv = U.rowsOf(RK.ok(res[3]) ? res[3] : null).find(r => String(r.id) === pid) || null;
    const curTeam = vv ? vv.team : team;
    const lv = last.values || {};
    document.title = p.name + ' · ' + RK.SITE;
    const a = age(p.dob);
    const ht = isNum(p.height) ? Math.floor(p.height / 12) + '′' + (p.height % 12) + '″' : '';
    const stat = (v, l) => '<div class="qk-hero-stat"><div class="v">' + v + '</div><div class="l">' + esc(l) + '</div></div>';
    const stats = goalie ? [stat(isNum(lv.gp) ? lv.gp : '—', 'GP'), stat(isNum(lv.sv_pct) ? RK.fmtVal(lv.sv_pct, '3') : '—', 'Save %'), stat(U.signed(lv.gsax, 1), 'GSAx'), stat(isNum(lv.w) ? lv.w + '-' + (lv.l || 0) + '-' + (lv.otl || 0) : '—', 'Record')]
      : [stat(isNum(lv.gp) ? lv.gp : '—', 'GP'), stat(isNum(lv.g) ? lv.g : '—', 'Goals'), stat(isNum(lv.a) ? lv.a : '—', 'Assists'), stat(isNum(lv.p) ? lv.p : '—', 'Points')];
    const tc = curTeam ? U.tcol(curTeam) : 'var(--accent)';
    const hero = '<section class="qk-hero" style="--tc:' + esc(tc) + '"><div class="qk-hero-in"><div class="qk-avatar">' + esc(isNum(p.number) ? '#' + p.number : QK.fmt.initials(p.name)) + '</div>' +
      '<div style="min-width:0"><div class="qk-kicker">' + esc([goalie ? 'Goalie' : ({ C: 'Centre', L: 'Left wing', R: 'Right wing', D: 'Defence' }[p.pos] || p.pos), last.season ? RK.seasonLabel(last.season) : ''].filter(Boolean).join(' · ')) + '</div><h1>' + esc(p.name) + '</h1>' +
      '<div class="qk-hero-meta">' + (curTeam ? '<span>' + U.teamEnt(curTeam) + '</span>' : '') + (a ? '<span>Age <b>' + a + '</b></span>' : '') + (ht ? '<span><b>' + ht + '</b>' + (isNum(p.weight) ? ' · ' + p.weight + ' lb' : '') + '</span>' : '') +
      (p.shoots ? '<span>' + (goalie ? 'Catches' : 'Shoots') + ' <b>' + esc(p.shoots) + '</b></span>' : '') + (vv && Array.isArray(vv.inj) && vv.inj[0] ? '<span class="rk-inj">' + esc(vv.inj[0]) + '</span>' : '') + '</div></div>' +
      '<div class="qk-hero-stats">' + stats.join('') + '</div></div></section>';
    const tabs = [{ key: 'overview', label: 'Overview', href: RK.playerHref(pid) }, { key: 'detail', label: 'Detail: every metric, shot maps, game log, on-ice, comparisons', href: RK.playerHref(pid) + '?view=detail' }];
    el.innerHTML = '<div class="qk-kicker" style="margin-bottom:10px"><a href="#/players">← Players</a></div>' + hero + '<div style="margin-top:var(--sp-4)"></div>' + U.tabsHTML(tabs, view) + '<div id="pp-body"></div>';
    const body = el.querySelector('#pp-body');
    if (view === 'detail') return U.legacy('player', body, params, state);

    // KPIs
    const k = [];
    if (vrow) k.push(QK.kpi({ label: 'Rink value this season', value: U.f(vrow.war, 2) + ' WAR', sub: U.f(vrow.gar, 1) + ' GAR · ' + (isNum(vrow.pct_pos) ? RK.ordinal(vrow.pct_pos) + ' pctl at his position' : ''), tip: 'Wins and goals above replacement, our model' }));
    if (vv) k.push(QK.kpi({ label: 'Four-season value', value: U.f(vv.total, 1) + ' WAR', sub: '10th–90th: ' + U.f(vv.p10, 1) + ' to ' + U.f(vv.p90, 1), tip: 'Discounted WAR over the rest of this season and the next three' }));
    if (c && c.projection && isNum(c.projection.proj_pts)) k.push(QK.kpi({ label: 'Projected points', value: U.f(c.projection.proj_pts, 0), sub: isNum(c.projection.proj_g) ? U.f(c.projection.proj_g, 0) + ' goals, full season' : '' }));
    if (c && c.onice && isNum(c.onice.xgf_pct)) k.push(QK.kpi({ label: '5v5 xGF%', value: U.pct(c.onice.xgf_pct, 1), sub: isNum(c.onice.xgf_pct_rel) ? U.signed(c.onice.xgf_pct_rel * 100, 1) + ' pts relative to team' : '', delta: null }));
    if (c && c.rapm && isNum(c.rapm.rapm_net)) k.push(QK.kpi({ label: 'RAPM net', value: U.signed(c.rapm.rapm_net, 2), sub: '± ' + U.f(c.rapm.rapm_net_se, 2) + ' xG/60', tip: 'Regularised adjusted plus-minus: on-ice expected-goal impact after teammates and opponents' }));
    if (!goalie && c && c.game_model && isNum(c.game_model.xgd60)) { const gm = c.game_model; k.push(QK.kpi({ label: 'Weight in the game model', value: U.signed(gm.xgd60, 3), sub: 'xG/60 to his team · ' + U.f(gm.share, 2) + ' of 5 skaters', tip: 'How much he moves his team’s game prices: his walk-forward RAPM (offence ' + U.signed(gm.o, 3) + ', defence ' + U.signed(gm.d, 3) + ' xG/60) times his share of the lineup’s expected 5v5 ice time (' + U.f(gm.toi5 / 60, 1) + ' min a game), as the game model reads the latest lineup' })); }
    if (goalie && c && c.goalie) { const g = c.goalie; k.push(QK.kpi({ label: 'Goals saved above expected', value: U.signed(g.gsax, 2), sub: U.signed(g.gsax60, 3) + ' per 60' }), QK.kpi({ label: 'High-danger save %', value: RK.fmtVal(g.sv_pct_high, '3'), sub: 'expected ' + RK.fmtVal(g.xfsv_pct, '3') + ' overall' })); }

    const groups = goalie ? G_PCT : SK_PCT;
    const pc = (c && c.pct) || {};
    const vals = goalie ? ((c && c.goalie) || {}) : Object.assign({}, lv, (c && c.onice) || {}, (c && c.rapm) || {}, (c && c.edge) || {});
    const pctHTML = groups.map(g => {
      const rows = g[1].filter(kk => isNum(pc[kk])).map(kk => ({ label: (LB[kk] || {}).label || kk, pctl: pc[kk], value: isNum(vals[kk]) ? fmtBy(LB[kk], vals[kk]) : '' }));
      return rows.length ? '<div class="qk-kicker" style="margin:12px 0 8px">' + esc(g[0]) + '</div>' + QK.pctlBars(rows) : '';
    }).join('');

    let h = (k.length ? '<div class="qk-kpis rk-kpis">' + k.join('') + '</div>' : '') +
      '<div class="qk-grid"><div class="qk-span-5">' + U.card2('Percentiles', c ? 'Against ' + (goalie ? 'goalies' : 'his position') + ' this season, 100 = best (needs the metric\'s sample floor)' : 'No current-season profile', pctHTML || QK.empty('Not enough data yet', 'Percentiles appear once he passes the sample floors.')) + '</div>' +
      '<div class="qk-span-7"><div class="rk-stack">' + U.card2('Season by season', goalie ? 'Save % and goals saved above expected' : 'Points and value by season; 100 = average for a qualified player at his position', U.chart('pp-seasons', 280, 'Season by season')) +
      ((c && (c.log || {}).rows || []).length ? U.card2('This season, game by game', goalie ? 'Goals saved above expected per game' : 'Game score per game (bars) and individual xG', U.chart('pp-log', 220, 'Game log')) : '') + '</div></div></div>';

    // season table
    h += '<section class="qk-section">' + U.card2('Career', seasons.length + ' season' + (seasons.length === 1 ? '' : 's') + ' in the data', '<div id="pp-career"></div>', { flush: true }) + '</section>';

    // splits, shots, value, linemates
    h += '<section class="qk-section"><div class="qk-grid">';
    if (c && c.shots && Array.isArray(c.shots.points) && c.shots.points.length) h += '<div class="qk-span-6">' + U.card2(goalie ? 'Shots faced' : 'Shot map', (goalie ? 'Unblocked shots faced' : 'His last ' + c.shots.points.length + ' unblocked attempts') + ', attacking right; filled = goal, size = xG', '<div id="pp-shots"></div>') + '</div>';
    h += '<div class="qk-span-6">' + U.card2('Splits', 'This season', '<div id="pp-splits"></div>', { flush: true }) + '</div>';
    h += '</div></section>';
    const side = [];
    if (c && (c.linemates || []).length) side.push('<div class="qk-span-4">' + U.card2('Linemates', 'Shared 5v5 minutes this season', '<ul class="rk-list">' + c.linemates.slice(0, 6).map(m => '<li>' + U.playerEnt(m[0], m[1]) + '<span class="v">' + U.f(m[2], 0) + ' min</span></li>').join('') + '</ul>', { flush: true }) + '</div>');
    if ((p.similar || []).length) side.push('<div class="qk-span-4">' + U.card2('Most similar', 'Nearest on this season\'s profile', '<ul class="rk-list">' + p.similar.slice(0, 6).map(m => '<li>' + U.playerEnt(m[0], m[1], m[2]) + '<a class="v rk-link" href="' + RK.compareHref(pid, m[0]) + '">Compare</a></li>').join('') + '</ul>', { flush: true }) + '</div>');
    if (vrow && (vrow.why || []).length) side.push('<div class="qk-span-4">' + U.card2('Where his value comes from', 'GAR by component this season', '<ul class="rk-list">' + vrow.why.map(w => '<li><span>' + esc(w[0]) + '</span><span class="v">' + esc(isNum(w[1]) ? (Math.abs(w[1]) < 1 && w[0].indexOf('%') >= 0 ? RK.fmtVal(w[1], '3') : U.signed(w[1], 2)) : '') + '</span></li>').join('') + '</ul>', { flush: true, foot: '<span></span><a href="#/value">Value leaderboard →</a>' }) + '</div>');
    if (side.length) h += '<section class="qk-section"><div class="qk-grid">' + side.join('') + '</div></section>';
    body.innerHTML = h;

    // season chart
    const sx = seasons.map(s => RK.seasonLabel(s.season, true));
    if (seasons.length) {
      if (goalie) {
        QKC.mount('#pp-seasons', T => ({
          grid: { left: 8, right: 8, top: 48, bottom: 30, containLabel: true },
          legend: { top: 0, left: 0, textStyle: { color: T.ink2 }, itemWidth: 12, itemHeight: 8 },
          xAxis: QKC.axis(T, { type: 'category', data: sx, split: false, line: true, name: 'Season', nameLocation: 'middle', nameGap: 26 }),
          yAxis: [QKC.axis(T, { fmt: v => v.toFixed(0), name: 'Goals saved above expected', nameAlign: 'left' }), QKC.axis(T, { fmt: v => v.toFixed(3), split: false, scale: true, name: 'Save %', nameAlign: 'right' })],
          tooltip: QKC.tooltip(T, { trigger: 'axis' }),
          series: [{ type: 'bar', name: 'GSAx', data: seasons.map(s => ({ value: (s.values || {}).gsax, itemStyle: { color: (s.values || {}).gsax >= 0 ? T.pos : T.neg, borderRadius: 3 } })), barMaxWidth: 26 },
            { type: 'line', name: 'Save %', yAxisIndex: 1, data: seasons.map(s => (s.values || {}).sv_pct), lineStyle: { color: T.market, width: 2 }, itemStyle: { color: T.market }, symbolSize: 6 }]
        }), { label: 'Goalie seasons' });
      } else {
        QKC.mount('#pp-seasons', T => ({
          grid: { left: 8, right: 8, top: 48, bottom: 30, containLabel: true },
          legend: { top: 0, left: 0, textStyle: { color: T.ink2 }, itemWidth: 12, itemHeight: 8 },
          xAxis: QKC.axis(T, { type: 'category', data: sx, split: false, line: true, name: 'Season', nameLocation: 'middle', nameGap: 26 }),
          yAxis: [QKC.axis(T, { fmt: v => v.toFixed(0), name: 'Points', nameAlign: 'left' }), QKC.axis(T, { split: false, scale: true, name: 'Index (100 = average)', nameAlign: 'right' })],
          tooltip: QKC.tooltip(T, { trigger: 'axis' }),
          series: [{ type: 'bar', name: 'Points', barMaxWidth: 26, data: seasons.map(s => ({ value: (s.values || {}).p, itemStyle: { color: QK.color.ensure(RK.teamColourRaw(s.team) || T.model, T.s1, 3), borderRadius: [3, 3, 0, 0] } })) },
            { type: 'line', name: 'Points/60 index', yAxisIndex: 1, data: seasons.map(s => (s.plus || {}).p60), lineStyle: { color: T.market, width: 2 }, itemStyle: { color: T.market }, symbolSize: 6, connectNulls: true },
            { type: 'line', name: 'xGF% index', yAxisIndex: 1, data: seasons.map(s => (s.plus || {}).xgf_pct), lineStyle: { color: T.cat[2], width: 2, type: 'dashed' }, itemStyle: { color: T.cat[2] }, symbolSize: 6, connectNulls: true,
              markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: 100 }] } }]
        }), { label: 'Points and indexes by season' });
      }
    }
    // game log chart
    const lg = c && c.log ? U.rowsOf(c.log) : [];
    if (lg.length && body.querySelector('#pp-log')) {
      const lx = lg.map(r => RK.fmtDate(r.date, { year: false, weekday: false }));
      QKC.mount('#pp-log', T => ({
        grid: { left: 8, right: 8, top: 28, bottom: 30, containLabel: true },
        xAxis: QKC.axis(T, { type: 'category', data: lx, split: false, line: true, name: 'Game date', nameLocation: 'middle', nameGap: 26 }),
        yAxis: QKC.axis(T, { fmt: v => v.toFixed(1), name: goalie ? 'Goals saved above expected' : 'Game score and ixG', nameAlign: 'left' }),
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => { const r = lg[ps[0].dataIndex]; return '<b>' + esc((r.home ? 'v ' : '@ ') + r.opp) + ' · ' + esc(r.result || '') + '</b>' + ps.map(q => QKC.tipRow(q.color, q.seriesName, U.f(q.value, 2))).join('') + (goalie ? QKC.tipRow(T.other, 'Saves', (r.sa - r.ga) + '/' + r.sa) : QKC.tipRow(T.other, 'G-A', r.g + '-' + r.a)); } }),
        series: goalie ? [{ type: 'bar', name: 'GSAx', data: lg.map(r => ({ value: r.gsax, itemStyle: { color: r.gsax >= 0 ? T.pos : T.neg, borderRadius: 3 } })), barMaxWidth: 18 }]
          : [{ type: 'bar', name: 'Game score', data: lg.map(r => ({ value: r.gs, itemStyle: { color: QKC.hexA(tc.charAt(0) === '#' ? tc : T.model, 0.85), borderRadius: 3 } })), barMaxWidth: 18 },
            { type: 'line', name: 'ixG', data: lg.map(r => r.ixg), lineStyle: { color: T.market, width: 2 }, itemStyle: { color: T.market }, symbolSize: 5 }]
      }), { label: 'Game log' });
    }
    // career table
    const cols = goalie
      ? [['gp', 'GP'], ['w', 'W'], ['sv_pct', 'SV%', v => RK.fmtVal(v, '3')], ['gaa', 'GAA', v => U.f(v, 2)], ['gsax', 'GSAx', v => U.signed(v, 1)], ['gsax60', 'GSAx/60', v => U.signed(v, 3)], ['qs_pct', 'QS%', v => U.pct(v)], ['war', 'WAR', v => U.f(v, 2)]]
      : [['gp', 'GP'], ['g', 'G'], ['a', 'A'], ['p', 'P'], ['p60', 'P/60', v => U.f(v, 2)], ['toi_gp', 'TOI/GP', v => RK.fmtTOI(v, { minutes: true })], ['ixg', 'ixG', v => U.f(v, 1)], ['sh_pct', 'Sh%', v => U.pct(v, 1)],
        ['xgf_pct', 'xGF%', v => U.pct(v, 1)], ['rapm_net', 'RAPM', v => U.signed(v, 2)], ['gar', 'GAR', v => U.f(v, 1)], ['war', 'WAR', v => U.f(v, 2)]];
    QK.table(body.querySelector('#pp-career'), { dense: true, sort: { key: 'season', dir: 'desc' }, columns: [
      { key: 'season', label: 'Season', sticky: true, fmt: (v, r) => '<b>' + esc(RK.seasonLabel(v)) + '</b>' }, { key: 'team', label: 'Club', fmt: (v, r) => (r.teams && r.teams.length > 1 ? r.teams.map(t => esc(RK.teamAbbr(t))).join(', ') : U.teamEnt(v, { abbr: true, season: r.season })) },
      { key: 'age', label: 'Age', num: true, fmt: v => U.f(v, 0) }]
      .concat(cols.map(cc => ({ key: cc[0], label: cc[1], num: true, fmt: cc[2] || (v => (isNum(v) ? String(v) : '—')) }))),
      rows: seasons.map(s => Object.assign({ season: s.season, team: s.team, teams: s.teams, age: s.age }, s.values || {})) });

    // shots
    const sn = body.querySelector('#pp-shots');
    if (sn) {
      const pcI = {}; (c.shots.point_cols || ['x', 'y', 'xg', 'goal']).forEach((kk, i) => { pcI[kk] = i; });
      sn.innerHTML = '<div id="pp-shots-c"></div>';
      QKC.shotMap('#pp-shots-c', { surface: 'rink', shots: c.shots.points.map(q => ({ x: q[pcI.x], y: q[pcI.y], v: q[pcI.xg], made: !!q[pcI.goal], name: (q[pcI.goal] ? 'Goal' : (goalie ? 'Save' : 'Attempt')) + ' · xG ' + U.f(q[pcI.xg], 2) })), madeLabel: goalie ? 'Goal against' : 'Goal', missLabel: goalie ? 'Saved / missed' : 'No goal', sizeScale: 30 });
    }
    // splits
    const sp = [];
    const bs = (c && c.onice && c.onice.by_strength) || {};
    Object.keys(bs).forEach(kk => { const b = bs[kk]; sp.push({ k: kk === 'pp' ? 'Power play' : kk === 'pk' ? 'Penalty kill' : kk, toi: b.toi, a: b.xgf_pct, b2: b.cf_pct, c2: b.gf_pct, d: b.xgf60, e: b.xga60 }); });
    const spEl = body.querySelector('#pp-splits');
    let sh = '';
    if (sp.length && !goalie) sh += '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>On ice</th><th class="num">TOI</th><th class="num">xGF%</th><th class="num">CF%</th><th class="num">GF%</th><th class="num">xGF/60</th><th class="num">xGA/60</th></tr></thead><tbody>' +
      sp.map(r => '<tr><td>' + esc(r.k) + '</td><td class="num">' + U.f(r.toi, 0) + '</td><td class="num">' + U.pct(r.a, 1) + '</td><td class="num">' + U.pct(r.b2, 1) + '</td><td class="num">' + U.pct(r.c2, 1) + '</td><td class="num">' + U.f(r.d, 2) + '</td><td class="num">' + U.f(r.e, 2) + '</td></tr>').join('') + '</tbody></table></div>';
    if (lg.length) {
      const part = (name, list) => {
        const n = list.length;
        if (!n) return '';
        if (goalie) { const sa = list.reduce((s2, r) => s2 + (r.sa || 0), 0), ga = list.reduce((s2, r) => s2 + (r.ga || 0), 0), gs = list.reduce((s2, r) => s2 + (r.gsax || 0), 0); return '<tr><td>' + esc(name) + '</td><td class="num">' + n + '</td><td class="num">' + (sa ? RK.fmtVal(1 - ga / sa, '3') : '—') + '</td><td class="num">' + U.signed(gs, 2) + '</td><td class="num">' + U.f(ga / n, 2) + '</td></tr>'; }
        const g = list.reduce((s2, r) => s2 + (r.g || 0), 0), a2 = list.reduce((s2, r) => s2 + (r.a || 0), 0), x = list.reduce((s2, r) => s2 + (r.ixg || 0), 0), t = list.reduce((s2, r) => s2 + (r.toi || 0), 0);
        return '<tr><td>' + esc(name) + '</td><td class="num">' + n + '</td><td class="num">' + g + '-' + a2 + '</td><td class="num">' + U.f((g + a2) / n, 2) + '</td><td class="num">' + U.f(x / n, 2) + '</td><td class="num">' + RK.fmtTOI(t / n, { minutes: true }) + '</td></tr>';
      };
      const rows = part('Home', lg.filter(r => r.home)) + part('Away', lg.filter(r => !r.home)) + part('Last 5', lg.slice(-5)) + part('Season', lg);
      sh += '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Games</th><th class="num">GP</th>' + (goalie ? '<th class="num">SV%</th><th class="num">GSAx</th><th class="num">GA/GP</th>' : '<th class="num">G-A</th><th class="num">P/GP</th><th class="num">ixG/GP</th><th class="num">TOI</th>') + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    }
    spEl.innerHTML = sh || QK.empty('No splits yet');
    RK.setMeta(p.updated_at ? 'Player file ' + esc(RK.fmtStamp(p.updated_at)) : '');
  });
}

RK.page('player', render);
})(window.RK);
