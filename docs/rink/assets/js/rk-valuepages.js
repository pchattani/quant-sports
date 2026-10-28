/* The Quant Rink — Value & Moves, the rebuilt legacy tabs (round 9, 28 Oct 2026): headline numbers, then a chart, then
 * the table, then the explain strip; the method lives on Model › How it works and the technical detail is folded.
 *   RK.valuationTab(node)        ?tab=val: the four-season valuation (valuation.json): who is worth the most over the
 *                                next four seasons with the likely range, the table with filters, scarcity and ageing
 *                                folded under "Technical detail".
 *   RK.movesTab(node, query)     ?tab=moves: the last twelve months of moves (transactions.json, deals.json): the
 *                                winners and losers chart and table, the best deals, the graded trades ten at a time,
 *                                every transaction folded (fifty at a time), the pick-value curve folded. The old page
 *                                ran to about 20,000 px at 1440.
 * Both use moves.js's deal card (RK.moves.dealCard) and the kit. Values are on-field model value (WAR), never contracts. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);
const POS = { C: 'Centres', L: 'Left wings', R: 'Right wings', D: 'Defence', G: 'Goalies' };
const POS1 = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G' };

/* ── the four-season valuation ─────────────────────────────────────────── */
const VT = { kind: 'S', pos: '', team: '', sort: 'total' };
RK.valuationTab = function (node) {
  node.innerHTML = QK.skeleton('lines', 8);
  const S = RK.currentSeason();
  return RK.loadYear('valuation.json', S).then(v => {
    if (!U.alive(node)) return;
    if (!RK.ok(v) || !(v.rows || []).length) { node.innerHTML = QK.empty('Not built yet', RK.reason(v)); return; }
    const rows = U.rowsOf(v), C = v.constants || {}, F = v.fits || {}, P = ((F.positional || {}).positions) || {};
    const best = (kind, f) => rows.filter(r => (kind === 'G' ? r.pos === 'G' : r.pos !== 'G') && (!f || f(r))).sort((a, b) => b.total - a.total)[0];
    const tS = best('S'), tG = best('G'), tY = best('S', r => isNum(r.age) && r.age <= 23);
    const scarce = ['C', 'L', 'R', 'D'].filter(p => P[p] && isNum(P[p].scarcity)).sort((a, b) => P[b].scarcity - P[a].scarcity)[0];
    const teams = Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort((a, b) => RK.teamName(a).localeCompare(RK.teamName(b)));
    const yrs = (C.horizon || 3) + 1;
    node.innerHTML = QK.stats([tS ? { label: 'Most valuable skater', value: RK.surnameOf(tS.name) + ' ' + U.f(tS.total, 1), unit: 'WAR', signal: true, href: RK.playerHref(tS.id), sub: RK.teamAbbr(tS.team) + ' · over ' + yrs + ' seasons, likely ' + U.f(tS.p10, 1) + ' to ' + U.f(tS.p90, 1) } : null,
        tG ? { label: 'Most valuable goalie', value: RK.surnameOf(tG.name) + ' ' + U.f(tG.total, 1), unit: 'WAR', href: RK.playerHref(tG.id), sub: RK.teamAbbr(tG.team) } : null,
        tY ? { label: '23 or under', value: RK.surnameOf(tY.name) + ' ' + U.f(tY.total, 1), unit: 'WAR', href: RK.playerHref(tY.id), sub: RK.teamAbbr(tY.team) + ' · age ' + Math.floor(tY.age) } : null,
        scarce ? { label: 'Scarcest position', value: POS[scarce], text: true, sub: 'starters there stand ' + U.f(P[scarce].scarcity, 2) + ' times as far above a replacement as the average skater' } : null].filter(Boolean)) +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'The long view', title: 'Who is worth the most over the next ' + yrs + ' seasons', sub: 'Our projected on-field value in wins above replacement, this season and the next ' + (C.horizon || 3) + ', discounted a little each year; the dot is our projection, the bar the likely range (10th to 90th percentile of ' + QK.fmt.num(C.draws || 400) + ' simulated careers).',
        actions: '<div class="qk-seg" id="vv-k" role="group" aria-label="Players"><button type="button" data-value="S" aria-pressed="' + (VT.kind === 'S') + '">Skaters</button><button type="button" data-value="G" aria-pressed="' + (VT.kind === 'G') + '">Goalies</button></div>' }) +
      U.card2('The top twenty', '<span id="vv-top-s"></span>', U.chart('vv-top', 640, 'Four-season value with its likely range')) + '</section>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Every player', title: 'The valuation table', sub: 'Filter by position or club and sort by any column. A tap opens the player.' }) +
      '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
        { label: 'Position', html: '<select class="qk-select" id="vv-pos"><option value="">All</option>' + ['C', 'L', 'R', 'D'].map(p => '<option value="' + p + '"' + (VT.pos === p ? ' selected' : '') + '>' + POS[p] + '</option>').join('') + '</select>' },
        { label: 'Club', html: '<select class="qk-select" id="vv-team"><option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (VT.team === t ? ' selected' : '') + '>' + esc(RK.teamName(t)) + '</option>').join('') + '</select>' }]) +
      '<div id="vv-table" style="margin-top:12px"></div></div></div>' +
      QK.explain('<b>What’s that number?</b> Four-season value adds up the wins a player should add over a replacement-level call-up: this season’s games left, then the next ' + (C.horizon || 3) + ' seasons, each projected from the player’s rate, ice time, age and the chance of still being a regular. <b>Over replacement</b> takes away what a replacement at the same position would give. On-field value only: no contracts or salary cap. How it works is on <a class="qk-link" href="#/model?tab=methodology">the Model page</a>.', { html: true }) + '</section>' +
      '<details class="rk-fold"><summary>Technical detail: position scarcity, ageing and survival, the fitted constants</summary><div class="rk-fold-b">' +
      '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Position scarcity', 'Replacement level and the starters’ edge, GAR per 60', '<div id="vv-scar"></div>', { flush: true }) + '</div>' +
      '<div class="qk-span-6">' + U.card2('Survival and ageing', 'The chance a regular of each age is still one next season', U.chart('vv-surv', 280, 'Survival by age')) + '</div></div>' +
      '<p class="rk-note">' + ['S', 'G'].filter(x => (F.reliability || {})[x]).map(x => { const rl = F.reliability[x], sv = (F.survival || {})[x] || {}; return '<b>' + (x === 'S' ? 'Skaters' : 'Goalies') + ':</b> the rate is half signal at ' + QK.fmt.num(rl.k_rel) + ' minutes (' + QK.fmt.num(rl.n_pairs) + ' season pairs); a regular stays one ' + U.pct(sv.base, 0) + ' of the time.'; }).join(' ') + '</p></div></details>';
    const drawTop = () => {
      const list = rows.filter(r => (VT.kind === 'G' ? r.pos === 'G' : r.pos !== 'G') && isNum(r.total)).sort((a, b) => b.total - a.total).slice(0, 20);
      node.querySelector('#vv-top-s').textContent = (VT.kind === 'G' ? 'Goalies' : 'Skaters') + ' · ' + RK.seasonLabel(S) + ' and the next ' + (C.horizon || 3);
      QKC.range('#vv-top', { rows: list.map(r => ({ label: r.name, lo: r.p10, hi: r.p90, mid: r.total, href: RK.playerHref(r.id), color: RK.teamColourRaw(r.team), sub: RK.teamAbbr(r.team) + ' · ' + (POS1[r.pos] || r.pos) + ' · age ' + Math.floor(r.age || 0) })),
        fmt: x => U.f(x, 1), loName: '10th', hiName: '90th percentile', midName: 'Our projection', valName: 'Wins above replacement, ' + yrs + ' seasons', labelWidth: 150 });
    };
    const drawTable = () => {
      const list = rows.filter(r => (VT.kind === 'G' ? r.pos === 'G' : r.pos !== 'G') && (!VT.pos || VT.kind === 'G' || r.pos === VT.pos) && (!VT.team || r.team === VT.team));
      QK.leaderboard(node.querySelector('#vv-table'), { dense: true, rank: true, maxHeight: 640, sort: { key: 'total', dir: 'desc' }, rowHref: r => RK.playerHref(r.id), columns: [
        { key: 'name', label: 'Player', type: 'entity', mark: r => U.team(r.team), href: r => RK.playerHref(r.id), sub: 'sub' },
        { key: 'age', label: 'Age', num: true, fmt: x => U.f(x, 0) },
        { key: 'now', label: 'This season', num: true, fmt: x => U.f(x, 2), tip: 'WAR over the club’s games left, after injuries' },
        { key: 'next', label: 'Next season', num: true, fmt: x => U.f(x, 2), tip: 'Expected WAR next season, survival included' },
        { key: 'total', label: yrs + ' seasons', type: 'bar', fmt: x => U.f(x, 1), tip: 'Discounted WAR over the rest of this season and the next ' + (C.horizon || 3) },
        { key: 'band', label: 'Likely range', sort: false, tip: '10th to 90th percentile of the simulated careers' },
        { key: 'vorp', label: 'Over replacement', num: true, fmt: x => U.f(x, 1), tip: 'Above a replacement at the same position' },
        { key: 's1', label: 'Still a regular', num: true, fmt: x => U.pct(x, 0), tip: 'Our chance the player is still an NHL regular next season' }],
        rows: list.map(r => Object.assign({}, r, { sub: [POS1[r.pos] || r.pos, Array.isArray(r.inj) && r.inj[0] ? r.inj[0] : ''].filter(Boolean).join(' · '), band: U.f(r.p10, 1) + ' to ' + U.f(r.p90, 1) })) });
    };
    drawTop(); drawTable();
    QK.seg(node.querySelector('#vv-k'), x => { VT.kind = x; drawTop(); drawTable(); });
    node.querySelector('#vv-pos').onchange = e => { VT.pos = e.target.value; drawTable(); };
    node.querySelector('#vv-team').onchange = e => { VT.team = e.target.value; drawTable(); };
    node.querySelector('#vv-scar').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Position</th><th class="num">Top N</th><th class="num">Starters</th><th class="num">Replacement</th><th class="num">Scarcity</th></tr></thead><tbody>' +
      ['C', 'L', 'R', 'D', 'G'].filter(p => P[p]).map(p => '<tr><td>' + POS[p] + '</td><td class="num">' + P[p].n_top + '</td><td class="num">' + U.f(P[p].starter, 3) + '</td><td class="num">' + U.signed(P[p].repl, 3) + '</td><td class="num"><b>' + (isNum(P[p].scarcity) ? U.f(P[p].scarcity, 2) : '—') + '</b></td></tr>').join('') + '</tbody></table></div>';
    const sv = ((v.curves || {}).survival) || {};
    const ser = [['S', 'Skaters'], ['G', 'Goalies']].filter(x => (sv[x[0]] || []).length).map((x, i) => ({ name: x[1], data: sv[x[0]].map(p => [p[0], Math.round(p[1] * 1000) / 10]), color: i ? QKC.tokens().cat[1] : 'model' }));
    if (ser.length) QKC.line('#vv-surv', { xType: 'value', series: ser.map(s => Object.assign({}, s, { color: s.color === 'model' ? QKC.tokens().model : s.color })), xName: 'Age', yName: 'Still a regular next season (%)', yMin: 0, yMax: 100, yFmt: x => x + '%', xMin: 19, xMax: 41, label: 'Survival by age' });
  });
};

/* ── moves and trade grades ─────────────────────────────────────────────── */
const MT = { team: '', minor: false, type: '', q: '', nd: 10, nt: 50 };
RK.movesTab = function (node, query) {
  node.innerHTML = QK.skeleton('lines', 8);
  const q = query || {};
  if (q.team) MT.team = RK.canonTeam(q.team);
  if (q.type) MT.type = q.type;
  if (q.minor === '1') MT.minor = true;
  const S = RK.currentSeason();
  return Promise.all([RK.loadYear('transactions.json', S), RK.loadYear('deals.json', S)]).then(res => {
    if (!U.alive(node)) return;
    const tx = res[0], dl = res[1];
    if (!RK.ok(tx) || !RK.ok(dl)) { node.innerHTML = QK.empty('Not built yet', RK.reason(RK.ok(tx) ? dl : tx)); return; }
    const deals = dl.deals || [], T = dl.teams || {}, N = dl.n || {};
    const tl = Object.keys(T).map(t => Object.assign({ team: t }, T[t])).filter(x => isNum(x.net_now)).sort((a, b) => b.net_now - a.net_now);
    const best = (dl.best || []).map(id => deals.find(d => d.id === id)).filter(Boolean);
    const txr = U.rowsOf(tx);
    const teams = Array.from(new Set(deals.reduce((a, d) => a.concat(d.teams), []).concat(txr.map(r => r.team)).filter(Boolean))).sort((a, b) => RK.teamName(a).localeCompare(RK.teamName(b)));
    const top = tl[0], bot = tl[tl.length - 1], W = dl.window || {};
    const types = tx.types || {};
    node.innerHTML = QK.stats([{ label: 'Trades graded', value: QK.fmt.num(N.graded), signal: true, sub: QK.fmt.num(N.deals) + ' deals and ' + QK.fmt.num(txr.length) + ' transactions since ' + RK.fmtDate(W.from, { weekday: false }) },
        top ? { label: 'Biggest winner', value: RK.teamAbbr(top.team) + ' ' + U.signed(top.net_now, 1), unit: 'WAR', href: RK.teamHref(top.team), sub: RK.teamName(top.team) + ': value received minus value sent, over ' + top.deals + ' deals' } : null,
        bot ? { label: 'Biggest loser', value: RK.teamAbbr(bot.team) + ' ' + U.signed(bot.net_now, 1), unit: 'WAR', href: RK.teamHref(bot.team), sub: RK.teamName(bot.team) + ', over ' + bot.deals + ' deals' } : null].filter(Boolean)) +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Twelve months of trades', title: 'Who won the trades', sub: 'Each club’s value received minus value sent, in wins above replacement as things stand now (what the players have done since, plus what they are still projected to do).' }) +
      '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Net value by club', 'Now, WAR', U.chart('mv-net', Math.max(420, 22 * tl.length + 60), 'Net trade value by club')) + '</div>' +
      '<div class="qk-span-6">' + U.card2('Winners and losers', 'At the time of each deal and now', '<div id="mv-league"></div>', { flush: true }) + '</div></div>' +
      QK.explain('<b>How the grades work.</b> Each side’s grade is its share of the value the deal moved: A at 65% or more, B at 55%, C between 45% and 55%, D at 35%, F below. “At the time” uses only what was known on the day; “now” adds what has happened since. Draft picks are valued on our pick curve (folded at the foot of the page). How it works: <a class="qk-link" href="#/model?tab=methodology">the Model page</a>.', { html: true }) + '</section>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'The best deals', title: 'The most lopsided', sub: 'The deals whose winner has gained the most so far.' }) + '<div class="qk-card"><div class="qk-card-body" id="mv-best"></div></div></section>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Every graded trade', title: 'Trade by trade', sub: 'Each side’s grade at the time and now, the assets, and the transaction text.' }) +
      '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
        { label: 'Club', html: '<select class="qk-select" id="mv-team"><option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === MT.team ? ' selected' : '') + '>' + esc(RK.teamName(t)) + '</option>').join('') + '</select>' },
        { label: 'Minor deals', html: '<select class="qk-select" id="mv-minor"><option value="0">Hide</option><option value="1"' + (MT.minor ? ' selected' : '') + '>Show</option></select>' }]) +
      '<p class="sc-floor" id="mv-deals-sub"></p><div id="mv-deals"></div></div></div></section>' +
      '<details class="rk-fold" id="mv-txf"><summary>Every transaction (' + QK.fmt.num(txr.length) + '): signings, recalls, waivers, trades</summary><div class="rk-fold-b">' + QK.scoutBar([
        { label: 'Type', html: '<select class="qk-select" id="mv-type"><option value="">All types</option>' + Object.keys(types).map(t => '<option value="' + esc(t) + '"' + (t === MT.type ? ' selected' : '') + '>' + esc(types[t]) + ' (' + (((tx.counts || {})[t]) || 0) + ')</option>').join('') + '</select>' },
        { label: 'Search', html: '<input class="qk-input" id="mv-q" type="search" placeholder="Player or text…" autocomplete="off">', cls: 'grow' }]) + '<div id="mv-tx" style="margin-top:12px"></div>' +
      '<p class="rk-note">Source: ' + esc(tx.source || 'ESPN') + '’s public transactions feed; ' + QK.fmt.num((tx.names || {}).matched) + ' of ' + QK.fmt.num((tx.names || {}).named) + ' names matched to NHL ids (never guessed).</p></div></details>' +
      '<details class="rk-fold"><summary>Technical detail: what a draft pick is worth (the pick-value curve)</summary><div class="rk-fold-b"><div class="qk-grid"><div class="qk-span-7">' + U.chart('mv-pc', 320, 'Pick-value curve') + '</div><div class="qk-span-5" id="mv-pc-t"></div></div></div></details>';
    if (MT.type) node.querySelector('#mv-txf').open = true;
    const dc = RK.moves && RK.moves.dealCard ? RK.moves.dealCard : null;
    QKC.bar('#mv-net', { cats: tl.map(x => RK.teamName(x.team)), series: [{ name: 'Net WAR', data: tl.map(x => x.net_now) }], horizontal: true, diverging: true, labels: true, fmt: x => U.signed(x, 1), hrefs: tl.map(x => RK.teamHref(x.team)), labelWidth: 150, valName: 'Net WAR from trades (now)' });
    QK.leaderboard(node.querySelector('#mv-league'), { dense: true, rank: true, maxHeight: Math.max(420, 22 * tl.length + 60), sort: { key: 'net_now', dir: 'desc' }, rowHref: r => RK.teamHref(r.team), columns: [
      { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team) }, { key: 'deals', label: 'Deals', num: true },
      { key: 'net_at', label: 'At the time', num: true, fmt: x => U.signed(x, 1) }, { key: 'net_now', label: 'Now', num: true, fmt: x => '<b>' + U.signed(x, 1) + '</b>' }, { key: 'wl', label: 'Won–lost', sort: false }],
      rows: tl.map(x => Object.assign({}, x, { name: RK.teamShort(x.team), wl: (x.won || 0) + '–' + (x.lost || 0) })) });
    node.querySelector('#mv-best').innerHTML = best.length && dc ? best.slice(0, 3).map(d => dc(d)).join('') : QK.empty('No graded deals yet');
    const drawDeals = () => {
      const list = deals.filter(d => (!MT.team || d.teams.indexOf(MT.team) >= 0) && (MT.minor || !d.minor));
      node.querySelector('#mv-deals-sub').textContent = list.length + ' deal' + (list.length === 1 ? '' : 's') + (MT.team ? ' involving ' + RK.teamName(MT.team) : '') + (MT.minor ? '' : ' (minor deals hidden)') + ', newest first';
      node.querySelector('#mv-deals').innerHTML = (list.length && dc ? list.slice(0, MT.nd).map(d => dc(d, MT.team || null)).join('') : QK.empty('No deals match')) +
        (list.length > MT.nd ? '<button type="button" class="qk-btn sm" id="mv-more-d">Show ' + Math.min(10, list.length - MT.nd) + ' more of ' + (list.length - MT.nd) + '</button>' : '');
      const b = node.querySelector('#mv-more-d');
      if (b) b.onclick = () => { MT.nd += 10; drawDeals(); };
    };
    const drawTx = () => {
      const needle = RK.fk.fold(MT.q.trim());
      const list = txr.filter(r => (!MT.team || r.team === MT.team) && (!MT.type || r.type === MT.type) && (!needle || RK.fk.fold(r.text).indexOf(needle) >= 0));
      node.querySelector('#mv-tx').innerHTML = (list.length ? '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Date</th><th>Club</th><th>Type</th><th>Transaction</th></tr></thead><tbody>' +
        list.slice(0, MT.nt).map(r => '<tr><td>' + esc(RK.fmtDate(r.date, { year: false })) + '</td><td>' + U.teamEnt(r.team, { abbr: true }) + '</td><td><span class="qk-badge' + (r.type === 'trade' ? ' accent' : '') + '">' + esc(types[r.type] || r.type) + '</span></td><td>' + esc(r.text) + '.</td></tr>').join('') + '</tbody></table></div>' : QK.empty('No transactions match')) +
        (list.length > MT.nt ? '<button type="button" class="qk-btn sm" id="mv-more-t" style="margin-top:10px">Show 50 more of ' + (list.length - MT.nt) + '</button>' : '');
      const b = node.querySelector('#mv-more-t');
      if (b) b.onclick = () => { MT.nt += 50; drawTx(); };
    };
    const sync = () => { try { history.replaceState(null, '', '#/value?tab=moves' + (MT.team ? '&team=' + encodeURIComponent(MT.team) : '') + (MT.type ? '&type=' + encodeURIComponent(MT.type) : '') + (MT.minor ? '&minor=1' : '')); } catch (e) { /* no history API */ } };
    node.querySelector('#mv-team').onchange = e => { MT.team = e.target.value; MT.nd = 10; MT.nt = 50; sync(); drawDeals(); drawTx(); };
    node.querySelector('#mv-minor').onchange = e => { MT.minor = e.target.value === '1'; MT.nd = 10; sync(); drawDeals(); };
    node.querySelector('#mv-type').onchange = e => { MT.type = e.target.value; MT.nt = 50; sync(); drawTx(); };
    let t0 = null;
    node.querySelector('#mv-q').oninput = e => { MT.q = e.target.value; clearTimeout(t0); t0 = setTimeout(drawTx, 200); };
    drawDeals(); drawTx();
    /* the pick curve */
    const pc = dl.pick_curve, raw = dl.pick_raw || [];
    if (pc && pc.ok && (pc.points || []).length) {
      QKC.mount('#mv-pc', T => {
        const xa = QKC.axis(T, { type: 'value', min: 1, max: Math.max.apply(null, pc.points.map(p => p[0])), split: false, line: true });
        const ya = QKC.axis(T, { fmt: x => x.toFixed(1) });
        const gB = 8 + QKC.nameAxis(xa, 'Overall pick', 'bottom'), gT = 14 + QKC.nameAxis(ya, 'Discounted WAR, first seasons', 'side');
        return { grid: { left: 8, right: 14, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya, tooltip: QKC.tooltip(T, { trigger: 'item' }),
          series: [{ type: 'scatter', name: 'Mean of the slot', symbolSize: 4, itemStyle: { color: T.ink3, opacity: 0.6 }, data: raw.map(r => [r[0], r[1]]) },
            { type: 'line', name: 'Fitted curve', showSymbol: false, lineStyle: { color: T.model, width: 3 }, data: pc.points.map(p => [p[0], p[1]]) }] };
      }, { label: 'Pick-value curve' });
      const ORD = ['', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th'], emp = pc.round_empirical || {};
      node.querySelector('#mv-pc-t').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Round</th><th class="num">Curve</th><th class="num">Observed</th><th class="num" data-tip="Share of picks with any positive WAR">Played</th></tr></thead><tbody>' +
        [1, 2, 3, 4, 5, 6, 7].map(r => { const e = emp[String(r)] || []; return '<tr><td>' + ORD[r] + '</td><td class="num">' + U.f((pc.round_avg || {})[String(r)], 2) + '</td><td class="num">' + U.f(e[0], 2) + '</td><td class="num">' + U.pct(e[2], 0) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
        '<p class="rk-note">v(p) = a (p + b)<sup>−c</sup> with a = ' + U.f(pc.a, 2) + ', b = ' + U.f(pc.b, 2) + ', c = ' + U.f(pc.c, 3) + ', from ' + QK.fmt.num(pc.n_picks) + ' picks of the ' + esc((pc.drafts || [])[0] || '') + ' to ' + esc((pc.drafts || []).slice(-1)[0] || '') + ' drafts.</p>';
    } else node.querySelector('#mv-pc').innerHTML = QK.empty('No pick curve');
  });
};
})(window.RK);
