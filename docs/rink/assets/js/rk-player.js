/* The Quant Rink — the player page (#/player/<pid>), Design System 2.0 reference player page.
 *
 * Player card header (club colour band, number, position, age, size, headline stats); stat tiles with percentile
 * chips; Overview: the Savant-style percentile card against his position group (forwards / defencemen / goalies,
 * the payload's sample floors, the sample shown, early metrics dashed), where he sits in the peer distribution,
 * season by season, this season's game log, the career table, splits, the shot map, value, linemates and the most
 * similar players (with compare links); Detail (?view=detail): the full pre-redesign player page.
 *
 * Reads data/players/<pid>.json, data/glossary.json (labels), <S>/skaters.json or goalies.json (position-pool
 * percentiles, the metric catalogue and the peer distribution), <S>/value.json and <S>/valuation.json (current). */
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

function fmtBy(meta, v) { return U.fmtBy(meta, v); }
function age(dob) { const d = RK.parseDate(dob); if (!d) return null; return Math.floor((Date.now() - d.getTime()) / (365.25 * 864e5)); }

function render(el, params, state) {
  const pid = String(params.id);
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'overview';
  const S = RK.currentSeason();
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  const kindGuess = (RK.player(pid) || {}).pos === 'G' ? 'goalies.json' : 'skaters.json';
  /* The player file carries current.pct_pos and current.peer (accuracy audit, 725fadad): then the 2.7 MB catalogue
     loads only when the peer distribution scrolls into view. Older files without them load the catalogue first. */
  return Promise.all([RK.loadPlayer(pid), labels(), RK.loadYear('value.json', S), RK.loadYear('valuation.json', S), U.moves(S)]).then(res0 => {
    const pf = res0[0], cc = pf && pf.current;
    const fileP = !!(cc && cc.pct_pos && Object.keys(cc.pct_pos).length && cc.peer);
    return (fileP ? Promise.resolve(null) : RK.loadYear(pf && (pf.kind === 'goalie' || pf.pos === 'G') ? 'goalies.json' : kindGuess, S)).then(cat0 => res0.slice(0, 4).concat([cat0, fileP, res0[4]]));
  }).then(res => {
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
    const fileP = res[5];
    let catP = res[4] && res[4].players ? res[4].players[pid] : null;
    let cat = catP ? res[4] : null;
    if (fileP) {
      const pr = c.peer || {};
      catP = { name: p.name, team: last.team, group: pr.group || (goalie ? 'G' : null), gp: lv.gp, toi: lv.toi, qualified: !!pr.qualified, values: Object.assign({}, lv), pct_pos: c.pct_pos, pct: c.pct || {}, peerN: pr.n };
      cat = { reference: { floors: { gp: pr.min_gp } }, players: null, metrics: [] };
    }
    const meta = U.metaMap(cat);
    Object.keys(LB).forEach(k2 => { if (!meta[k2]) meta[k2] = LB[k2]; });
    const group = catP ? (goalie ? 'G' : catP.group) : (goalie ? 'G' : null);
    const posName = goalie ? 'Goalie' : ({ C: 'Centre', L: 'Left wing', R: 'Right wing', D: 'Defence' }[p.pos] || p.pos);
    const stats = goalie ? [{ label: 'GP', value: isNum(lv.gp) ? lv.gp : '—' }, { label: 'Save %', value: isNum(lv.sv_pct) ? RK.fmtVal(lv.sv_pct, '3') : '—' }, { label: 'GSAx', value: U.signed(lv.gsax, 1) }, { label: 'Record', value: isNum(lv.w) ? lv.w + '-' + (lv.l || 0) + '-' + (lv.otl || 0) : '—' }]
      : [{ label: 'GP', value: isNum(lv.gp) ? lv.gp : '—' }, { label: 'Goals', value: isNum(lv.g) ? lv.g : '—' }, { label: 'Assists', value: isNum(lv.a) ? lv.a : '—' }, { label: 'Points', value: isNum(lv.p) ? lv.p : '—' }];
    const tc = curTeam ? U.tcol(curTeam) : 'var(--signal)';
    const tagsH = [];
    if (catP && catP.qualified) tagsH.push(QK.tag('Qualified for percentiles', 'signal'));
    if (vv && Array.isArray(vv.inj) && vv.inj[0]) tagsH.push('<span class="qk-tag rk-inj">' + esc(vv.inj[0]) + '</span>');
    const hero = QK.playerHeader({ name: p.name, number: p.number, pos: posName, kicker: last.season ? RK.seasonLabel(last.season) : '',
      team: curTeam ? { name: RK.teamName(curTeam), abbr: RK.teamAbbr(curTeam), colour: RK.teamColourRaw(curTeam), href: RK.teamHref(curTeam) } : null,
      meta: [a ? ['Age', String(a)] : null, ht ? ['Height', ht + (isNum(p.weight) ? ' · ' + p.weight + ' lb' : '')] : null, p.shoots ? [goalie ? 'Catches' : 'Shoots', p.shoots] : null], stats: stats, tags: tagsH });
    const tabs = [{ key: 'overview', label: 'Overview', href: RK.playerHref(pid) }, { key: 'detail', label: 'Detail: every metric, shot maps, game log, on-ice, comparisons', href: RK.playerHref(pid) + '?view=detail' }];
    el.innerHTML = '<div class="qk-kicker" style="margin-bottom:10px"><a href="#/players">← Players</a></div>' + hero + '<div style="margin-top:var(--sp-4)"></div>' + U.tabsHTML(tabs, view) + '<div id="pp-body"></div>';
    const body = el.querySelector('#pp-body');
    if (view === 'detail') return U.legacy('player', body, params, state);

    // stat tiles: ours first, each with its percentile against the position group where there is one
    const pp = (catP && (catP.pct_pos || catP.pct)) || {};
    const k = [];
    if (vrow) k.push({ label: 'Rink value this season', value: U.f(vrow.war, 2), unit: 'WAR', sub: U.f(vrow.gar, 1) + ' goals above replacement', pctl: isNum(vrow.pct_pos) ? vrow.pct_pos : null, signal: true, tip: 'Wins and goals above replacement, our model' });
    if (vv) k.push({ label: 'Four-season value', value: U.f(vv.total, 1), unit: 'WAR', sub: 'likely range ' + U.f(vv.p10, 1) + ' to ' + U.f(vv.p90, 1), tip: 'Discounted WAR over the rest of this season and the next three; the range is the 10th to 90th percentile' });
    if (!goalie && catP) k.push({ label: 'Points per 60', value: U.f((catP.values || {}).p60, 2), pctl: pp.p60, sub: 'all situations', tip: (meta.p60 || {}).desc });
    if (c && c.onice && isNum(c.onice.xgf_pct)) k.push({ label: '5v5 expected-goals share', value: U.f(c.onice.xgf_pct * 100, 1), unit: '%', pctl: pp.xgf_pct, sub: isNum(c.onice.xgf_pct_rel) ? U.signed(c.onice.xgf_pct_rel * 100, 1) + ' pts relative to his team' : '', tip: 'Of the expected goals at 5v5 with him on the ice, the share that went his team’s way' });
    if (c && c.rapm && isNum(c.rapm.rapm_net)) k.push({ label: 'On-ice impact (RAPM)', value: U.signed(c.rapm.rapm_net, 2), pctl: pp.rapm_net, sub: '± ' + U.f(c.rapm.rapm_net_se, 2) + ' xG per 60 (one standard error)', tip: 'Regularised adjusted plus-minus: his on-ice expected-goal impact after teammates and opponents' });
    if (goalie && c && c.goalie) { const gg = c.goalie; k.push({ label: 'Goals saved above expected', value: U.signed(gg.gsax, 2), pctl: pp.gsax60, signal: true, sub: U.signed(gg.gsax60, 3) + ' per 60' }, { label: 'High-danger save %', value: RK.fmtVal(gg.sv_pct_high, '3'), pctl: pp.sv_pct_high, sub: 'expected ' + RK.fmtVal(gg.xfsv_pct, '3') + ' overall' }); }

    const SETS = U.SETS[group] || U.SETS.F;
    const peerOf = () => (catP ? (catP.pct_pos ? (U.GROUP_NAME[group] || 'his position') + (isNum(catP.peerN) ? ' (' + catP.peerN + ' qualified)' : '') : 'all NHL skaters') : '');
    const pcardHTML = () => QK.pctCard({ id: 'pp-pcard', title: 'Percentile rankings', peer: peerOf(), sample: catP ? U.sampleLine(catP, cat.reference, goalie) : '', groups: catP ? U.pctGroups(catP, meta, SETS) : [],
      note: goalie && catP ? U.goalieNote(catP) : '', emptyText: catP ? 'He is short of the sample floors for this season.' : 'No current-season profile yet.' });
    const pcard = pcardHTML();

    let h = (k.length ? '<div class="rk-kpis">' + QK.stats(k) + '</div>' : '') +
      '<div class="qk-grid"><div class="qk-span-5">' + pcard + '</div>' +
      '<div class="qk-span-7"><div class="rk-stack">' +
      (catP ? U.card2('Where he sits', 'Every qualified ' + (U.GROUP_NAME[group] || 'player').replace('NHL ', '') + ' this season; bars coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 240, 'Distribution of the peer group')) : '') +
      U.card2('Season by season', goalie ? 'Save % and goals saved above expected' : 'Points and value by season; 100 = average for a qualified player at his position', U.chart('pp-seasons', 280, 'Season by season')) +
      ((c && (c.log || {}).rows || []).length ? U.card2('This season, game by game', goalie ? 'Goals saved above expected per game' : 'Game score per game (bars) and individual xG (line)', U.chart('pp-log', 220, 'Game log')) : '') + '</div></div></div>';

    // season table
    h += '<section class="qk-section">' + U.card2('Career', seasons.length + ' season' + (seasons.length === 1 ? '' : 's') + ' in the data', '<div id="pp-career"></div>', { flush: true }) + '</section>';

    // splits, shots, value, linemates
    h += '<section class="qk-section"><div class="qk-grid">';
    if (c && c.shots && Array.isArray(c.shots.points) && c.shots.points.length) h += '<div class="qk-span-6">' + U.card2(goalie ? 'Shots faced' : 'Shot map', (goalie ? 'Unblocked shots faced' : 'His last ' + c.shots.points.length + ' unblocked attempts') + ', attacking right; filled = goal, size = xG', '<div id="pp-shots"></div>') + '</div>';
    h += '<div class="qk-span-6">' + U.card2('Splits', 'This season', '<div id="pp-splits"></div>', { flush: true }) + '</div>';
    h += '</div></section>';
    const side = [];
    if (c && (c.linemates || []).length) side.push('<div class="qk-span-4">' + U.card2('Linemates', 'Shared 5v5 minutes this season', '<ul class="rk-list">' + c.linemates.slice(0, 6).map(m => '<li>' + U.playerEnt(m[0], m[1]) + '<span class="v">' + U.f(m[2], 0) + ' min</span></li>').join('') + '</ul>', { flush: true }) + '</div>');
    if ((p.similar || []).length) side.push('<div class="qk-span-4">' + U.card2('Most similar', 'Nearest on this season\'s profile', '<ul class="rk-list">' + p.similar.slice(0, 6).map(m => '<li>' + U.playerEnt(m[0], m[1], m[2]) + '<a class="v rk-link" href="' + RK.compareHref(pid, m[0]) + '">Compare</a></li>').join('') + '</ul>', { flush: true, foot: '<span></span><a href="' + RK.compareHref(pid, (p.similar[0] || [])[0]) + (p.similar[1] ? '/' + encodeURIComponent(p.similar[1][0]) : '') + '">Compare the top three →</a>' }) + '</div>');
    if (vrow && (vrow.why || []).length) side.push('<div class="qk-span-4">' + U.card2('Where his value comes from', 'GAR by component this season', '<ul class="rk-list">' + vrow.why.map(w => '<li><span>' + esc(w[0]) + '</span><span class="v">' + esc(isNum(w[1]) ? (Math.abs(w[1]) < 1 && w[0].indexOf('%') >= 0 ? RK.fmtVal(w[1], '3') : U.signed(w[1], 2)) : '') + '</span></li>').join('') + '</ul>', { flush: true, foot: '<span></span><a href="#/value">Value leaderboard →</a>' }) + '</div>');
    // movement (MOVES_VIEWS.md §4): our chance he is not in the lineup next season, the type split, the deadline base rate
    const M = res[6], mvr = M ? M.byPid[pid] : null;
    if (mvr && isNum(mvr.p_next)) {
      const ctx = [isNum(mvr.age) ? 'age ' + Math.floor(mvr.age) : '', isNum(mvr.yrs) ? mvr.yrs + ' seasons in the league' : '', isNum(mvr.value) ? U.signed(mvr.value, 2) + ' ' + (M.d.unit || 'WAR') + ' last season' : ''].filter(Boolean).join(' · ');
      side.unshift('<div class="qk-span-4">' + U.card2('Movement', 'By ' + esc(M.horizon), QK.stats([{ label: U.MOVE_HEAD, value: mvr.p_next < 0.01 ? '<1' : String(Math.round(mvr.p_next * 100)), unit: '%', signal: true, sub: mvr.why || '', tip: U.moveTip(M) }]) +
        '<div style="margin-top:10px">' + U.moveBar(mvr, M) + '</div><div style="margin-top:8px">' + U.moveKeys(M) + '</div>' + (ctx ? '<p class="rk-note" style="margin:8px 0 0">' + esc(ctx) + '</p>' : '') + U.deadlineLine(M).replace('rk-mv-line', 'rk-mv-line" style="margin-top:8px'), { foot: '<span>How it works</span><a href="#/model?tab=moves">Who moves next →</a>' }) + '</div>');
    }
    if (side.length) h += '<section class="qk-section"><div class="qk-grid">' + side.join('') + '</div></section>';
    body.innerHTML = h;

    // where he sits: the peer distribution of one metric (the spec's set), with him and the median marked. With the
    // player file's percentiles the catalogue loads only when this card comes into view; it then fills the values.
    if (catP && body.querySelector('#pp-dist')) {
      const OPTS = { F: [['gar_60', 'Value / 60'], ['p60', 'Points / 60'], ['ixg60_all', 'ixG / 60'], ['adj_xgf_pct', 'xG share']], D: [['gar_60', 'Value / 60'], ['adj_xgf_pct', 'xG share'], ['rapm_def', 'RAPM defence'], ['p60', 'Points / 60']],
        G: [['gsax100', 'GSAx / 100'], ['sv_pct', 'Save %'], ['qs_pct', 'Quality starts']] };
      const opts = OPTS[group] || OPTS.F;
      const segEl = body.querySelector('#pp-dist-m');
      segEl.innerHTML = opts.map((o, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + o[0] + '">' + esc(o[1]) + '</button>').join('');
      const start = full => {
        const peers = Object.keys(full.players || {}).map(id => full.players[id]).filter(x => x && x.qualified && (goalie || x.group === group));
        const me = (full.players || {})[pid];
        if (fileP && me) {
          catP.values = Object.assign({}, catP.values, me.values || {}); catP.toi = me.toi; catP.gp = me.gp;
          Object.assign(meta, U.metaMap(full));
          const old = body.querySelector('#pp-pcard');
          if (old) old.outerHTML = pcardHTML();
        }
        const drawDist = key => {
          const mm = meta[key] || {}, sp = U.SPEC[key] || {};
          const vals = peers.map(x => (x.values || {})[key]).filter(isNum).sort((x, y) => x - y);
          const mine = (catP.values || {})[key];
          if (vals.length < 5) { body.querySelector('#pp-dist').innerHTML = QK.empty('Too few qualified peers yet', 'The distribution appears once five ' + (U.PEER_SHORT[group] || 'players') + ' reach the sample floor.'); return; }
          const med = vals[Math.floor(vals.length / 2)];
          const f = mm.fmt === 'pct' ? (v => U.f(v * 100, 1) + '%') : (v => U.f(v, 2));
          QKC.distribution('#pp-dist', { values: vals, binCount: 22, lowerBetter: !!(mm.lower || sp.lower), fmt: f, xName: (sp.label || mm.label || key) + ' · ' + vals.length + ' qualified peers', yName: 'Players',
            marks: (isNum(mine) ? [{ x: mine, label: RK.playerSurname(pid) }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + (sp.label || mm.label || key) });
        };
        drawDist(opts[0][0]);
        QK.seg(segEl, drawDist);
      };
      if (cat && cat.players) start(cat);
      else {
        const host = body.querySelector('#pp-dist');
        host.innerHTML = QK.skeleton('chart', 1);
        let fired = false;
        const go = () => { if (fired) return; fired = true; RK.loadYear(goalie ? 'goalies.json' : 'skaters.json', S).then(full => { if (U.alive(host) && full && full.players) start(full); else if (U.alive(host)) host.innerHTML = QK.empty('The peer catalogue did not load'); }); };
        if (window.IntersectionObserver) { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); } else go();
      }
    }

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
            { type: 'line', name: 'Save %', yAxisIndex: 1, data: seasons.map(s => (s.values || {}).sv_pct), lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] }, symbolSize: 6 }]
        }), { label: 'Goalie seasons' });
      } else {
        QKC.mount('#pp-seasons', T => ({
          grid: { left: 8, right: 8, top: 48, bottom: 30, containLabel: true },
          legend: { top: 0, left: 0, textStyle: { color: T.ink2 }, itemWidth: 12, itemHeight: 8 },
          xAxis: QKC.axis(T, { type: 'category', data: sx, split: false, line: true, name: 'Season', nameLocation: 'middle', nameGap: 26 }),
          yAxis: [QKC.axis(T, { fmt: v => v.toFixed(0), name: 'Points', nameAlign: 'left' }), QKC.axis(T, { split: false, scale: true, name: 'Index (100 = average)', nameAlign: 'right' })],
          tooltip: QKC.tooltip(T, { trigger: 'axis' }),
          series: [{ type: 'bar', name: 'Points', barMaxWidth: 26, data: seasons.map(s => ({ value: (s.values || {}).p, itemStyle: { color: QK.color.ensure(RK.teamColourRaw(s.team) || T.model, T.s1, 3), borderRadius: [3, 3, 0, 0] } })) },
            { type: 'line', name: 'Points/60 index', yAxisIndex: 1, data: seasons.map(s => (s.plus || {}).p60), lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] }, symbolSize: 6, connectNulls: true },
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
            { type: 'line', name: 'ixG', data: lg.map(r => r.ixg), lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] }, symbolSize: 5 }]
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
