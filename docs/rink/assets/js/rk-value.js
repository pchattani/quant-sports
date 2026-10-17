/* The Quant Rink — Value & Moves (#/value?tab=board|season|val|moves|trade).
 *
 * Board (new): the most valuable players this season (WAR), best by position, value against ice time, the
 * trade market (net value each club has gained from trades) and the best-graded deals. The other tabs render the
 * pre-redesign views: season value (value.js), the multi-season valuation (?tab=val), moves and trade grades
 * (moves.js), the trade simulator (trade.js, its state in &t=&m=).
 *
 * Reads <S>/value.json and <S>/deals.json. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const TABS = [['board', 'Board'], ['season', 'Season value'], ['val', 'Valuation (4 seasons)'], ['moves', 'Moves & trade grades'], ['trade', 'Trade simulator']];
const POS = [['C', 'Centres'], ['L', 'Left wings'], ['R', 'Right wings'], ['D', 'Defence'], ['G', 'Goalies']];

function board(node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  const cur = Number(S) === Number(RK.currentSeason());
  return Promise.all([RK.loadYear('value.json', S), cur ? RK.loadYear('deals.json', S) : Promise.resolve(null)]).then(res => {
    if (!U.alive(node)) return;
    const v = RK.ok(res[0]) ? res[0] : null, dl = RK.ok(res[1]) ? res[1] : null;
    if (!v) { node.innerHTML = U.card2('Player value', '', QK.empty('Not built yet', RK.reason(res[0]))); return; }
    const rows = U.rowsOf(v);
    const by = {}; rows.forEach(r => { by[r.id] = r; });
    const q = rows.filter(r => r.q);
    const sk = q.filter(r => r.kind !== 'G'), gk = q.filter(r => r.kind === 'G');
    const top = q.slice().sort((a, b) => (b.war || 0) - (a.war || 0)).slice(0, 15);
    const riser = q.filter(r => isNum(r.war) && isNum(r.prev_war)).sort((a, b) => (b.war - b.prev_war) - (a.war - a.prev_war))[0];
    const k = [
      QK.kpi({ label: 'Most valuable skater', value: sk[0] ? RK.surnameOf(sk[0].name) : '—', sub: sk[0] ? U.f(sk[0].war, 2) + ' WAR · ' + RK.teamAbbr(sk[0].team) + ' · ' + U.f(sk[0].gar, 1) + ' GAR' : '' }),
      QK.kpi({ label: 'Most valuable goalie', value: gk[0] ? RK.surnameOf(gk[0].name) : '—', sub: gk[0] ? U.f(gk[0].war, 2) + ' WAR · ' + RK.teamAbbr(gk[0].team) + ' · ' + U.signed(gk[0].gsax, 1) + ' GSAx' : '' }),
      QK.kpi({ label: 'Qualified players', value: QK.fmt.num(q.length), sub: (v.n_qualified ? (v.n_qualified.S || 0) + ' skaters, ' + (v.n_qualified.G || 0) + ' goalies' : '') }),
      QK.kpi({ label: 'Goals per win', value: v.currency && isNum(v.currency.goals_per_win) ? U.f(v.currency.goals_per_win, 2) : '—', sub: 'the exchange rate from GAR to WAR' })
    ];
    if (riser) k.push(QK.kpi({ label: 'Biggest riser', value: RK.surnameOf(riser.name), sub: U.signed(riser.war - riser.prev_war, 2) + ' WAR on last season · ' + RK.teamAbbr(riser.team) }));
    let h = '<div class="qk-kpis rk-kpis">' + k.join('') + '</div>' +
      '<div class="qk-grid"><div class="qk-span-7">' + U.card2('Most valuable this season', 'Wins above replacement (Rink value); qualified players', U.chart('vb-top', 440, 'Most valuable players'), { foot: '<span>' + esc(v.note || '') + '</span><a href="#/value?tab=season">Full leaderboard →</a>' }) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Value v ice time', 'GAR against minutes played: up and left is value in fewer minutes', U.chart('vb-sc', 440, 'Value against ice time')) + '</div></div>';
    h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Best by position</h2><div class="qk-sub">Top five qualified players at each position by WAR this season.</div></div></div><div class="qk-grid">' +
      POS.map(p => {
        const ids = ((v.best || {})[p[0]] || []).slice(0, 5);
        const list = ids.map(id => by[id]).filter(Boolean);
        return '<div class="qk-span-' + (p[0] === 'G' ? 4 : 4) + '">' + U.card2(p[1], '', list.length ? '<ul class="rk-list">' + list.map((r, i) => '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(r.id, r.name, r.team) + '<span class="v">' + U.f(r.war, 2) + '</span></li>').join('') + '</ul>' : QK.empty('Nobody qualifies yet'), { flush: true }) + '</div>';
      }).join('') + '</div></section>';
    if (dl) {
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>The trade market</h2><div class="qk-sub">Every NHL trade of the last twelve months, valued (multi-season WAR, picks from our pick-value curve) at the time and with what has happened since.</div></div><a class="qk-btn" href="#/value?tab=moves">All moves and grades →</a></div>' +
        '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Net value from trades, by club', 'Value received minus value sent, current view (WAR)', U.chart('vb-net', 620, 'Net trade value by club')) + '</div>' +
        '<div class="qk-span-6">' + U.card2('The best-graded deals', 'Largest value moved, graded for each side (A ≥ 65% of the value)', '<div id="vb-deals"></div>', { flush: true }) + '</div></div></section>';
    }
    node.innerHTML = h;
    QKC.bar('#vb-top', { cats: top.map(r => r.name), series: [{ name: 'WAR', data: top.map(r => r.war) }], horizontal: true, labels: true, fmt: x => U.f(x, 2), colors: top.map(r => RK.teamColourRaw(r.team)), hrefs: top.map(r => RK.playerHref(r.id)), labelWidth: 140 });
    const sc = q.filter(r => isNum(r.toi) && isNum(r.gar) && r.kind !== 'G');
    QKC.scatter('#vb-sc', { points: sc.map(r => ({ x: r.toi, y: r.gar, name: r.name + ' · ' + RK.teamAbbr(r.team), label: RK.surnameOf(r.name), color: RK.teamColourRaw(r.team), href: RK.playerHref(r.id), size: 8 })), xName: 'Minutes', yName: 'GAR', xFmt: x => x.toFixed(0), yFmt: x => x.toFixed(1), labelTop: 8, refY: 0 });
    if (dl) {
      const T0 = dl.teams || {};
      const tl = Object.keys(T0).map(t => ({ t: t, v: T0[t].net_now })).filter(x => isNum(x.v)).sort((a, b) => b.v - a.v);
      QKC.bar('#vb-net', { cats: tl.map(x => RK.teamName(x.t)), series: [{ name: 'Net WAR', data: tl.map(x => x.v) }], horizontal: true, diverging: true, labels: true, fmt: x => U.signed(x, 2), hrefs: tl.map(x => RK.teamHref(x.t)), labelWidth: 140 });
      const deals = (dl.deals || []);
      const best = (dl.best || []).map(id => deals.find(d => d.id === id)).filter(Boolean).slice(0, 6);
      node.querySelector('#vb-deals').innerHTML = best.length ? '<ul class="rk-list">' + best.map(d => {
        const sides = d.teams.map(t => { const s = (d.sides || {})[t] || {}; const g = s.grade_now || s.grade_at; return '<span class="rk-flex" style="gap:6px">' + (g ? '<span class="rk-grade" data-g="' + esc(g) + '">' + esc(g) + '</span>' : '') + U.teamEnt(t, { abbr: true }) + '</span>'; }).join('');
        const got = (d.assets || []).filter(a => a.k === 'player').slice(0, 3).map(a => esc(a.name) + ' → ' + esc(RK.teamAbbr(a.to))).join(' · ');
        return '<li style="flex-wrap:wrap"><div class="rk-flex" style="gap:14px">' + sides + '</div><span class="v">' + U.f(d.total_now, 1) + ' WAR</span><div class="s" style="flex-basis:100%">' + esc(RK.fmtDate(d.date)) + (got ? ' · ' + got : '') + '</div></li>';
      }).join('') + '</ul>' : QK.empty('No graded deals yet');
    }
  });
}

function page(el, params, state) {
  const S = params.season;
  const q = (params.query || {});
  const tab = TABS.map(t => t[0]).indexOf(q.tab) >= 0 ? q.tab : 'board';
  const tabs = TABS.map((t, i) => ({ key: t[0], label: t[1], href: '#/value' + (i ? '?tab=' + t[0] : '') + (U.sq(S) && (t[0] === 'board' || t[0] === 'season') ? (i ? '&' : '?') + U.sq(S) : '') }));
  const body = U.section(el, { section: 'value', title: 'Value & Moves', sub: 'What every player is worth on the ice (goals and wins above replacement), the multi-season valuation, every trade graded, and a simulator to try your own.', tabs: tabs, active: tab });
  if (tab === 'board') return board(body, S);
  if (tab === 'season' || tab === 'val') return U.legacy('value', body, params, state, { tab: tab });
  return U.legacy(tab, body, params, state);
}

RK.page('value', page);
})(window.RK);
