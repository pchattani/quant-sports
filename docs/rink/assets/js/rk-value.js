/* The Quant Rink — Value & Moves (#/value?tab=board|season|val|moves|trade).
 *
 * Board (Design System 2.0): stat tiles, the most valuable players this season (WAR), best by position, value against
 * ice time, net value each club has gained from trades and the best-graded deals. Who moves next (?tab=next):
 * every player's chance of not being in his club's lineup next season (movement.json, MOVES_VIEWS.md), by club
 * or league-wide. The other tabs render the pre-redesign views: season value (value.js), the multi-season valuation
 * (?tab=val), moves and trade grades (moves.js), the trade simulator (trade.js, its state in &t=&m=).
 *
 * Kit v4 "Broadcast": Broadcast section heads, black stat blocks, team-colour bars and explain strips (QK.note) on WAR,
 * GAR and the trade grades.
 *
 * Reads <S>/value.json, <S>/deals.json and <S>/movement.json. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const TABS = [['board', 'Board'], ['next', 'Who moves next'], ['season', 'Season value'], ['val', 'Valuation (4 seasons)'], ['moves', 'Moves & trade grades'], ['trade', 'Trade simulator']];
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
    const top1 = (list, k) => list.filter(r => isNum(r[k])).sort((a, b) => b[k] - a[k])[0];
    const s0 = top1(sk, 'war'), g0 = top1(gk, 'war');
    const k = [
      s0 ? { label: 'Most valuable skater', value: RK.surnameOf(s0.name) + ' ' + U.f(s0.war, 2), unit: 'WAR', signal: true, href: RK.playerHref(s0.id), sub: RK.teamAbbr(s0.team) + ' · ' + U.f(s0.gar, 1) + ' goals above replacement', tip: 'Wins above replacement this season, our value model' } : null,
      g0 ? { label: 'Most valuable goalie', value: RK.surnameOf(g0.name) + ' ' + U.f(g0.war, 2), unit: 'WAR', href: RK.playerHref(g0.id), sub: RK.teamAbbr(g0.team) + ' · ' + U.signed(g0.gsax, 1) + ' goals saved above expected' } : null,
      riser ? { label: 'Biggest riser', value: RK.surnameOf(riser.name) + ' ' + U.signed(riser.war - riser.prev_war, 2), unit: 'WAR', href: RK.playerHref(riser.id), sub: 'on last season · ' + RK.teamAbbr(riser.team) } : null,
      { label: 'Qualified players', value: QK.fmt.num(q.length), sub: (v.n_qualified ? (v.n_qualified.S || 0) + ' skaters, ' + (v.n_qualified.G || 0) + ' goalies' : '') },
      { label: 'Goals per win', value: v.currency && isNum(v.currency.goals_per_win) ? U.f(v.currency.goals_per_win, 2) : '—', sub: 'the exchange rate from GAR to WAR', tip: 'How many goals above replacement buy one win this season' }
    ];
    let h = '<div class="rk-kpis">' + QK.stats(k) + '</div>' +
      QK.note('<b>What is WAR?</b> Wins above replacement: how many more wins a team gets from the player than from a replacement-level call-up. <b>GAR</b> is the same in goals' + (v.currency && isNum(v.currency.goals_per_win) ? ': this season about ' + U.f(v.currency.goals_per_win, 1) + ' goals buy one win' : '') + '.', { cls: 'rk-note-top' }) +
      QK.sectionHead({ kicker: 'This season', title: 'Who is worth the most', sub: 'Our value model on qualified players: everything a player adds at even strength, on special teams and in net, in one number.' }) +
      '<div class="qk-grid"><div class="qk-span-7">' + U.card2('Most valuable this season', 'Wins above replacement (Rink value); qualified players', U.chart('vb-top', 440, 'Most valuable players'), { foot: '<span>' + esc(v.note || '') + '</span><a href="#/value?tab=season">Full leaderboard →</a>' }) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Value v ice time', 'GAR against minutes played: up and left is value in fewer minutes', U.chart('vb-sc', 440, 'Value against ice time')) + '</div></div>';
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'By position', title: 'The best at each position', sub: 'Top five qualified players at each position by WAR this season.' }) + '<div class="qk-grid">' +
      POS.map(p => {
        const ids = ((v.best || {})[p[0]] || []).slice(0, 5);
        const list = ids.map(id => by[id]).filter(Boolean);
        return '<div class="qk-span-4">' + U.card2(p[1], 'WAR this season', list.length ? '<ul class="rk-list rk-lead">' + list.map((r, i) => '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(r.id, r.name, r.team) + '<span class="v">' + U.f(r.war, 2) + '</span></li>').join('') + '</ul>' : '<div class="rk-board-empty"><b>Fills in when the first ' + esc(p[1].toLowerCase()) + ' qualify</b><span>Value needs 200 minutes in all situations over a full season, prorated by games played.</span></div>', { flush: true }) + '</div>';
      }).join('') + '</div></section>';
    if (dl) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Trades', title: 'Who won the trades', sub: 'Every NHL trade of the last twelve months, valued (multi-season WAR, picks from our pick-value curve) at the time and with what has happened since.', actions: '<a class="qk-btn" href="#/value?tab=moves">All moves and grades →</a>' }) +
        QK.note('<b>How the grades work.</b> Each side gets a grade from its share of the value that changed hands: an A means it got at least 65% of it. Grades move as the players play, so a deal can look different a year on.') +
        '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Net value from trades, by club', 'Value received minus value sent, current view (WAR)', U.chart('vb-net', 620, 'Net trade value by club')) + '</div>' +
        '<div class="qk-span-6">' + U.card2('The best-graded deals', 'Largest value moved, graded for each side (A ≥ 65% of the value)', '<div id="vb-deals"></div>', { flush: true }) + '</div></div></section>';
    }
    node.innerHTML = h;
    QKC.bar('#vb-top', { cats: top.map(r => r.name), series: [{ name: 'WAR', data: top.map(r => r.war) }], horizontal: true, labels: true, fmt: x => U.f(x, 2), colors: top.map(r => RK.teamColourRaw(r.team)), hrefs: top.map(r => RK.playerHref(r.id)), labelWidth: 140, valName: 'Wins above replacement' });
    const sc = q.filter(r => isNum(r.toi) && isNum(r.gar) && r.kind !== 'G');
    QKC.scatter('#vb-sc', { points: sc.map(r => ({ x: r.toi, y: r.gar, name: r.name + ' · ' + RK.teamAbbr(r.team), label: RK.surnameOf(r.name), color: RK.teamColourRaw(r.team), href: RK.playerHref(r.id), size: 8 })), xName: 'Minutes', yName: 'GAR', xFmt: x => x.toFixed(0), yFmt: x => x.toFixed(1), labelTop: 8, refY: 0 });
    if (dl) {
      const T0 = dl.teams || {};
      const tl = Object.keys(T0).map(t => ({ t: t, v: T0[t].net_now })).filter(x => isNum(x.v)).sort((a, b) => b.v - a.v);
      QKC.bar('#vb-net', { cats: tl.map(x => RK.teamName(x.t)), series: [{ name: 'Net WAR', data: tl.map(x => x.v) }], horizontal: true, diverging: true, labels: true, fmt: x => U.signed(x, 2), hrefs: tl.map(x => RK.teamHref(x.t)), labelWidth: 140, valName: 'Net WAR from trades' });
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

/* Who moves next: the league list (or one club's) by our chance of not being in the lineup next season. */
function nextTab(node, S, team0) {
  node.innerHTML = QK.skeleton('lines', 8);
  return U.moves(S).then(M => {
    if (!U.alive(node)) return;
    if (!M || !M.pub.next) { node.innerHTML = U.card2('Who moves next', '', QK.empty('Not published', M && (M.d.reasons || {}).next ? M.d.reasons.next : 'The movement model is not published for this season.')); return; }
    const d = M.d, br = d.base_rates || {};
    const teams = Object.keys(M.teams).sort((a, b) => RK.teamName(a).localeCompare(RK.teamName(b)));
    const team = team0 && M.teams[RK.canonTeam(team0)] ? RK.canonTeam(team0) : '';
    const top = M.rows.filter(r => isNum(r.p_next)).sort((a, b) => b.p_next - a.p_next);
    const dep = teams.map(t => ({ t: t, v: M.teams[t].exp_departures })).filter(x => isNum(x.v)).sort((a, b) => b.v - a.v);
    node.innerHTML = '<div class="rk-kpis">' + QK.stats([
      { label: 'Players forecast', value: QK.fmt.num(top.length), sub: 'rostered NHL players this season' },
      isNum(br.next) ? { label: 'League base rate', value: U.pct(br.next), sub: 'of players were not in the same lineup the next season', tip: 'Over the seasons the model learned from' } : null,
      dep[0] ? { label: 'Most expected departures', value: RK.teamAbbr(dep[0].t) + ' ' + U.f(dep[0].v, 1), signal: true, href: RK.teamHref(dep[0].t), sub: 'players not in the lineup by ' + M.horizon } : null,
      dep.length ? { label: 'Fewest expected departures', value: RK.teamAbbr(dep[dep.length - 1].t) + ' ' + U.f(dep[dep.length - 1].v, 1), href: RK.teamHref(dep[dep.length - 1].t), sub: 'the most settled lineup' } : null
    ]) + '</div>' +
      QK.sectionHead({ kicker: 'By ' + M.horizon, title: U.MOVE_HEAD, html: true, sub: esc((d.notes || [])[2] || '') + ' <a href="#/model?tab=moves">How it works and how it tested →</a>',
        actions: '<select class="qk-select" id="mv-team" aria-label="Club"><option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === team ? ' selected' : '') + '>' + esc(RK.teamName(t)) + '</option>').join('') + '</select>' }) +
      U.deadlineLine(M) + '<div class="qk-card"><div class="rk-keys-row">' + U.moveKeys(M) + '</div><div id="mv-board"></div></div>' +
      (isNum(br.next) ? QK.note('<b>How to read a chance here.</b> About ' + U.pct(br.next) + ' of players are not in the same lineup a season later, so that is the middle. A player at 60% stays put about 4 times in 10. The chance counts trades, signings elsewhere, waivers and time in the minors.') : '');
    const draw = t => {
      const list = (t ? top.filter(r => r.team === t) : top.slice(0, 100)).map(r => Object.assign({ sub: [r.pos, isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · ') }, r));
      QK.leaderboard(node.querySelector('#mv-board'), { dense: true, rank: true, maxHeight: 720, rowHref: r => RK.playerHref(r.pid), columns: [
        { key: 'name', label: 'Player', type: 'entity', mark: r => U.team(r.team), href: r => RK.playerHref(r.pid), sub: 'sub' },
        { key: 'team', label: 'Club', fmt: v => esc(RK.teamAbbr(v)) },
        { key: 'value', label: 'Value', num: true, fmt: v => U.signed(v, 2), tip: 'Rink WAR, the last two completed seasons blended 3:2' },
        { key: 'yrs', label: 'Seasons', num: true, tip: 'Seasons in the league' },
        { key: 'p_next', label: 'Not in lineup next season', num: true, tip: U.moveTip(M), fmt: (v, r) => U.moveBar(r, M) + (r.why ? '<span class="rk-why">' + esc(r.why) + '</span>' : '') }
      ], rows: list });
    };
    draw(team);
    node.querySelector('#mv-team').addEventListener('change', e => draw(e.target.value));
  });
}

function page(el, params, state) {
  const S = params.season;
  const q = (params.query || {});
  const tab = TABS.map(t => t[0]).indexOf(q.tab) >= 0 ? q.tab : 'board';
  const tabs = TABS.map((t, i) => ({ key: t[0], label: t[1], href: '#/value' + (i ? '?tab=' + t[0] : '') + (U.sq(S) && (t[0] === 'board' || t[0] === 'season') ? (i ? '&' : '?') + U.sq(S) : '') }));
  const body = U.section(el, { section: 'value', title: 'Value & Moves', sub: 'What every player is worth on the ice, who is likely to move next, what a player is worth over the next four seasons, every trade graded, and a simulator to try your own.', tabs: tabs, active: tab });
  if (tab === 'board') return board(body, S);
  if (tab === 'next') return nextTab(body, S, q.team);
  if (tab === 'season' || tab === 'val') return U.legacy('value', body, params, state, { tab: tab });
  return U.legacy(tab, body, params, state);
}

RK.page('value', page);
})(window.RK);
