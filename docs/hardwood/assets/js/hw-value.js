/* The Quant Hardwood — Value & Moves (#/<L>/value).
 *
 * Board tab (new): headline numbers; the most valuable players over four seasons with their 80% band; value
 * against age by position group; the best at each position; net trade value by team (deals of the last 12
 * months in today's view); the biggest deals with grades; the latest transactions.
 * Other tabs keep the pre-redesign views: Season value (WAR from HPM, any season), Moves & grades (?mt=, team=,
 * type=, basis=), Trade simulator (?t=&m=).
 * Data: <L>/<S>/valuation.json, deals.json, transactions.json for the current season. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;

function itemsTxt(L, items) {
  return (items || []).map(x => (x.k === 'pick' ? x.label : x.name)).join(', ') || 'nothing of value';
}

function board(node, L) {
  const S = HW.currentSeason(L);
  return Promise.all([HW.load(HW.path('valuation.json', L, S)), HW.load(HW.path('deals.json', L, S)), HW.load(HW.path('transactions.json', L, S))]).then(a => {
    if (!U.alive(node)) return;
    const val = U.ok(a[0]) ? a[0] : null, deals = U.ok(a[1]) ? a[1] : null, tx = U.ok(a[2]) ? a[2] : null;
    if (!val) { node.innerHTML = U.empty('Not built yet', 'The valuation for ' + HW.seasonLabel(L, S) + ' is not available.'); return; }
    const rows = U.rowsOf(val).filter(r => isNum(r.v));
    const top = rows.slice().sort((x, y) => y.v - x.v).slice(0, 15);
    const dl = deals ? (deals.deals || []) : [];
    const T = deals ? deals.teams || {} : {};
    const tIds = Object.keys(T).filter(t => isNum(T[t].net_now));
    const byNet = tIds.slice().sort((x, y) => T[y].net_now - T[x].net_now);
    const bigDeals = dl.filter(d => isNum(d.total_now) || isNum(d.total)).slice().sort((x, y) => (y.total_now || y.total || 0) - (x.total_now || x.total || 0)).slice(0, 8);
    const txr = tx ? U.rowsOf(tx) : [];
    const seen = {}, latest = txr.filter(x => { const k = x.date + x.text; if (seen[k]) return false; seen[k] = 1; return true; }).sort((x, y) => String(y.date).localeCompare(String(x.date))).slice(0, 14);
    const kp = [];
    if (top[0]) kp.push(({ label: 'Most valuable', value: top[0].name, text: true, signal: true, href: HW.playerHref(L, top[0].id), sub: U.f(top[0].v, 1) + ' WAR over four seasons · ' + HW.teamAbbr(L, top[0].team) }));
    const young = rows.filter(r => isNum(r.age) && r.age < 23).sort((x, y) => y.v - x.v)[0];
    if (young) kp.push(({ label: 'Best under 23', value: young.name, text: true, sub: U.f(young.v, 1) + ' WAR · age ' + Math.floor(young.age) }));
    if (byNet[0]) kp.push(({ label: 'Won the trade market', value: HW.teamAbbr(L, byNet[0]) + ' ' + U.signed(T[byNet[0]].net_now, 1), sub: 'net WAR from ' + T[byNet[0]].n + ' trades, today’s view' }));
    kp.push(({ label: 'Trades rated', value: String(dl.length), sub: latest.length ? txr.length + ' transactions in 12 months' : '' }));
    let h = '<div class="hw-kpis">' + QK.stats(kp) + '</div><div class="qk-grid hw-sec">' +
      U.card2('Most valuable players', 'Wins above replacement over four seasons (discounted 10% a season); the bar is the 80% band', U.chart('vb-top', 26 * top.length + 50, 'Most valuable players'), { cls: 'qk-span-7' }) +
      U.card2('Value against age', 'Four-season WAR (up) against age, every rostered player above half a win', U.chart('vb-age', 26 * top.length + 50, 'Value against age'), { cls: 'qk-span-5' }) + '</div>';
    h += '<section class="qk-section">' + U.head({ title: 'Best by position', sub: 'Guards, wings and bigs by four-season value; value over the position’s replacement level in brackets.', actions: U.btnLink(HW.href(L, 'value') + '?tab=war', 'Season value for any year') }) + '<div class="qk-grid">' +
      ['G', 'W', 'B'].map(k => U.card2(U.ROLE[k], '', '<ul class="hw-list">' + rows.filter(r => r.role === k).sort((x, y) => y.v - x.v).slice(0, 8).map((r, i) =>
        '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(L, r.id, r.name, r.team, isNum(r.age) ? 'age ' + Math.floor(r.age) : '') + '<span class="v">' + U.f(r.v, 1) + ' <span class="hw-quiet">(' + U.signed(r.vorp, 1) + ')</span></span></li>').join('') + '</ul>', { cls: 'qk-span-4', flush: true })).join('') + '</div></section>';
    if (tIds.length || bigDeals.length) {
      h += '<section class="qk-section">' + U.head({ title: 'Trades', sub: 'Every trade of the last 12 months rated on four-season value: at the time (no hindsight) and in today’s view (realised since plus what is left).', actions: U.btnLink(HW.href(L, 'value') + '?tab=moves', 'All trades and the feed') }) + '<div class="qk-grid">' +
        (tIds.length ? U.card2('Net trade value by team', 'WAR in minus WAR out, today’s view', U.chart('vb-net', 20 * tIds.length + 30, 'Net trade value'), { cls: 'qk-span-5' }) : '') +
        (bigDeals.length ? U.card2('Biggest deals', 'Grade = share of the value each side received (A 65%+, F under 35%)', '<div>' + bigDeals.map(d => '<div class="hw-deal"><div class="hw-quiet">' + esc(HW.fmtDate(d.date, { year: false })) + ' · ' + U.f(d.total_now || d.total, 1) + ' WAR moved</div>' +
          (d.sides || []).map(sd => '<div class="side">' + U.grade(sd.grade_now || sd.grade) + U.teamEnt(L, sd.team, { abbr: true }) + '<span class="items">gets ' + esc(itemsTxt(L, sd['in'])) + '</span></div>').join('') + '</div>').join('') + '</div>', { cls: tIds.length ? 'qk-span-7' : 'qk-span-12', flush: true }) : '') + '</div></section>';
    }
    if (latest.length) h += '<section class="qk-section">' + U.head({ title: 'Latest moves', sub: 'Signings, trades, waivers and injury-list moves from ESPN’s transaction feed.', actions: U.btnLink(HW.href(L, 'value') + '?tab=moves&mt=feed', 'The full feed') }) + '' +
      '<div class="qk-card">' + latest.map(x => '<div class="hw-tx"><span class="d">' + esc(HW.fmtDate(x.date, { year: 'auto', weekday: false })) + '</span><span>' + (x.team ? U.teamEnt(L, x.team, { abbr: true }) + ' ' : '') + esc(x.text) + '</span></div>').join('') + '</div></section>';
    node.innerHTML = h;
    QKC.mount('#vb-top', Tk => {
      const ya = QKC.axis(Tk, { type: 'category', data: top.map(r => r.name), split: false, inverse: true }); ya.axisLabel.color = Tk.ink2; ya.axisLabel.width = 140; ya.axisLabel.overflow = 'truncate';
      return { grid: { left: 8, right: 20, top: 10, bottom: 26, containLabel: true }, yAxis: ya, xAxis: QKC.axis(Tk, { name: 'WAR, four seasons', nameLocation: 'middle', nameGap: 24 }),
        tooltip: QKC.tooltip(Tk, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: QKC.hexA(Tk.ink1, 0.04) } }, formatter: ps => { const r = top[ps[0].dataIndex];
          return '<div style="font-weight:600;margin-bottom:4px">' + esc(r.name + ' · ' + HW.teamAbbr(L, r.team)) + '</div>' + QKC.tipRow(U.tcol(L, r.team), 'Value', U.f(r.v, 1)) + QKC.tipRow(Tk.other, '80% band', U.f(r.p10, 1) + ' to ' + U.f(r.p90, 1)) +
            QKC.tipRow(Tk.other, 'This season', U.f(r.w0, 1)) + QKC.tipRow(Tk.other, 'Age', U.f(r.age, 1)); } }),
        series: [{ type: 'custom', silent: true, data: top.map((r, i) => [r.p10, r.p90, i]), encode: { x: [0, 1], y: 2 },
          renderItem: (p, api) => { const a1 = api.coord([api.value(0), api.value(2)]), b1 = api.coord([api.value(1), api.value(2)]); return { type: 'rect', shape: { x: a1[0], y: a1[1] - 3, width: Math.max(2, b1[0] - a1[0]), height: 6, r: 3 }, style: { fill: QKC.hexA(U.tcol(L, top[p.dataIndex].team), 0.3) } }; } },
          { type: 'scatter', symbolSize: 11, z: 3, data: top.map((r, i) => ({ value: [r.v, i], href: HW.playerHref(L, r.id), itemStyle: { color: U.tcol(L, r.team), borderColor: Tk.s1, borderWidth: 2 } })) }] };
    }, { label: 'Most valuable players' });
    const pts = rows.filter(r => isNum(r.age) && r.v > 0.5);
    const RC = { G: 0, W: 2, B: 4 };
    QKC.mount('#vb-age', Tk => ({
      grid: { left: 8, right: 16, top: 48, bottom: 26, containLabel: true },
      legend: { top: 0, left: 0, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: Tk.ink2 } },
      xAxis: QKC.axis(Tk, { name: 'Age', nameLocation: 'middle', nameGap: 24, scale: true }), yAxis: QKC.axis(Tk, { name: 'WAR, four seasons', nameAlign: 'left' }),
      tooltip: QKC.tooltip(Tk, { formatter: p => '<div style="font-weight:600">' + esc(p.data.name) + '</div>' + QKC.tipRow(p.color, 'Value', U.f(p.value[1], 1)) + QKC.tipRow(p.color, 'Age', U.f(p.value[0], 1)) }),
      series: ['G', 'W', 'B'].map(k => ({ type: 'scatter', name: U.ROLE[k], symbolSize: 7, itemStyle: { color: Tk.cat[RC[k]], opacity: 0.8 },
        data: pts.filter(r => r.role === k).map(r => ({ value: [r.age, r.v], name: r.name + ' · ' + HW.teamAbbr(L, r.team), href: HW.playerHref(L, r.id) })) }))
    }), { label: 'Value against age' });
    if (tIds.length) QKC.bar('#vb-net', { cats: byNet.map(t => HW.teamAbbr(L, t)), series: [{ name: 'Net WAR', data: byNet.map(t => Math.round(T[t].net_now * 10) / 10) }], horizontal: true, labels: true, diverging: true, fmt: x => U.signed(x, 1), hrefs: byNet.map(t => HW.href(L, 'value') + '?tab=moves&team=' + t), labelWidth: 46, valName: 'Net WAR from trades' });
    HW.setMeta(val.updated_at ? 'Valuation ' + esc(HW.fmtStamp(val.updated_at)) : '');
  });
}

function render(el, params) {
  const L = U.L(params), S = U.S(params);
  const tab = U.tab(params, ['board', 'war', 'moves', 'trade'], 'board');
  const body = U.section(el, { title: 'Value & Moves', kicker: U.kicker(L, S), sub: 'What every player is worth in wins, who is winning the trade market, and a simulator for your own deal. On-field value only: no salaries.',
    tabs: U.tabs(L, 'value', [['board', 'Board', false], ['war', 'Season value'], ['moves', 'Moves & grades', false], ['trade', 'Trade simulator', false]], S), active: tab });
  if (tab === 'board') return board(body, L);
  return U.legacy({ war: 'value', moves: 'moves', trade: 'trade' }[tab], body, params);
}

HW.page('value', render);
})(window.HW);
