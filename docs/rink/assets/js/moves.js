/* The Quant Rink — Moves (#/moves): the last twelve months of NHL transactions, every trade graded for each side, the
 * league's winners and losers, the best and worst deals and the pick-value curve; and the team page's "Ledger"
 * (RK.moves.ledger(el, abbr)).
 *
 * Data (current season): data/<S>/transactions.json (analytics/moves.py: cols [date, team, type, text, players, deal],
 * rows newest first, types, counts, unmatched) and data/<S>/deals.json (deals [{id, date, teams, minor, winner_at,
 * winner_now, total_at, total_now, sides {abbr: {at, real, now, sent_at, sent_now, share_at, share_now, grade_at,
 * grade_now, net_at, net_now}}, assets [{k: player|pick|fc|cash, from, to, pid, name, pos, at, real, now, gp, year,
 * round, overall, cond, note, gone}], text [[abbr, sentence]]}], teams {abbr: {deals, in_at, out_at, in_now, out_now,
 * net_at, net_now, won, lost}}, best, pick_curve {a, b, c, points, round_avg, round_empirical, r2_slots, r2_bins,
 * n_picks, drafts}, pick_raw [[overall, mean, n]]). Values are on-field model value (WAR), never contracts or the cap.
 * State in the hash: #/moves?team=<abbr>&type=<type>&minor=1. Uses RK.fk (skaters.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const POS_ONE = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G', F: 'F', LW: 'LW', RW: 'RW' };
const ORD = ['', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th'];
const MT = { team: 'all', type: 'all', minor: '0', n: 150 };

function gradePill(g) { return g ? '<span class="nd-grade nd-' + String(g).toLowerCase() + '">' + K().esc(g) + '</span>' : '<span class="muted-inline">—</span>'; }

function txRows(tx) {
  const cols = (tx && tx.cols) || [];
  return ((tx && tx.rows) || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}

function assetLabel(a) {
  const k = K();
  if (a.k === 'player') {
    const nm = a.pid ? k.playerLink(a.pid, a.name) : k.esc(a.name || '?');
    return (a.pos ? '<span class="muted-inline">' + k.esc(POS_ONE[a.pos] || a.pos) + '</span> ' : '') + nm + (a.rights ? ' <span class="muted-inline">(rights)</span>' : '') +
      (a.gone ? ' <span class="chip" title="No longer with this club: no projected value after leaving">gone</span>' : '') +
      (a.note ? ' <span class="mv-note" title="' + k.esc(a.note) + '">ⓘ</span>' : '');
  }
  if (a.k === 'pick') return (a.year ? a.year + ' ' : '') + (ORD[a.round] || (a.round + 'th')) + '-round pick' + (a.overall ? ' (No. ' + a.overall + ')' : '') +
    (a.cond ? ' <span class="muted-inline">conditional</span>' : '') + (a.yr_inferred ? ' <span class="muted-inline" title="No year in the text: the next draft">year assumed</span>' : '');
  if (a.k === 'fc') return 'Future considerations';
  if (a.k === 'cash') return 'Cash';
  return K().esc(a.k);
}

function dealCard(d, focus) {
  const k = K();
  const sides = d.teams.map(t => {
    const v = d.sides[t] || {};
    const got = d.assets.filter(a => a.to === t);
    const rows = got.map(a => '<tr><td class="mv-asset">' + assetLabel(a) + '</td><td class="mv-n" title="At the time">' + (a.k === 'player' || a.k === 'pick' ? k.num(a.at, 2) : '0') + '</td>' +
      '<td class="mv-n" title="Realised since">' + (a.k === 'player' ? k.num(a.real, 2) + (k.isNum(a.gp) && a.gp ? ' <span class="muted-inline">' + a.gp + ' GP</span>' : '') : '—') + '</td>' +
      '<td class="mv-n" title="Now">' + (a.k === 'player' || a.k === 'pick' ? '<strong>' + k.num(a.now, 2) + '</strong>' : '0') + '</td></tr>').join('');
    return '<div class="mv-side' + (focus && t === focus ? ' mv-focus' : '') + '"><div class="mv-side-h">' + k.teamChip(t) + ' <span class="muted-inline">receives</span> ' +
      '<span class="mv-gr" title="Grade at the time / now">' + gradePill(v.grade_at) + ' → ' + gradePill(v.grade_now) + '</span></div>' +
      '<div class="table-wrap compact"><table class="wc-table mv-tbl"><thead><tr><th>Asset</th><th class="mv-n">At time</th><th class="mv-n">Since</th><th class="mv-n">Now</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="4" class="muted-inline">nothing</td></tr>') + '</tbody></table></div>' +
      '<div class="mv-tot">' + k.num(v.at, 2) + ' WAR at the time (' + k.pct(v.share_at, 0) + ') · ' + k.num(v.now, 2) + ' now (' + k.pct(v.share_now, 0) + ') · net ' + k.signed(v.net_now, 2) + '</div></div>';
  }).join('');
  const win = d.minor ? '<span class="chip">minor</span>' : d.winner_now ? '<span class="chip ok">' + k.esc(k.teamNick(d.winner_now)) + ' won</span>' : '<span class="chip">even</span>';
  return '<div class="mv-deal" id="deal-' + k.esc(d.id) + '"><div class="mv-deal-h"><strong>' + k.esc(k.fmtDate(d.date)) + '</strong> · ' + d.teams.map(t => k.esc(k.teamName(t))).join(' – ') + ' ' + win +
    ' <span class="muted-inline">' + k.num(d.total_at, 2) + ' WAR moved at the time</span></div><div class="mv-sides mv-n' + d.teams.length + '">' + sides + '</div>' +
    '<details class="mv-src"><summary>Transaction text (ESPN)</summary>' + d.text.map(x => '<div><span class="muted-inline">' + k.esc(x[0]) + '</span> ' + k.esc(x[1]) + '.</div>').join('') + '</details></div>';
}

function render(el, params) {
  const k = K();
  el.innerHTML = k.muted('Loading…');
  const q = (params && params.query) || {};
  ['team', 'type', 'minor'].forEach(x => { if (q[x] !== undefined && q[x] !== '') MT[x] = q[x]; });
  return k.ready().then(() => {
    const S = k.curSeason();
    return Promise.all([k.loadY(S, 'transactions.json'), k.loadY(S, 'deals.json'), k.loadNames()]).then(res => {
      if (!k.alive(el)) return;
      const tx = res[0], dl = res[1];
      const tabs = RK.valuation ? RK.valuation.tabs(S, 'moves') : '';
      if (!k.ok(tx) || !k.ok(dl)) { el.innerHTML = tabs + k.card('Moves', '', '<div class="pad">' + k.notBuilt('Transactions and trade grades', k.ok(tx) ? dl : tx) + '</div>'); return; }
      draw(el, S, tx, dl, tabs);
    });
  });
}

function draw(el, S, tx, dl, tabs) {
  const k = K();
  const deals = dl.deals || [];
  const T = dl.teams || {};
  const tl = Object.keys(T).map(t => Object.assign({ team: t }, T[t])).sort((a, b) => (b.net_now || 0) - (a.net_now || 0));
  const best = (dl.best || []).map(id => deals.find(d => d.id === id)).filter(Boolean);
  const N = dl.n || {};
  let h = tabs + '<div class="card"><div class="card-header">Moves ' + k.esc(k.sLabel(S)) + ' <span class="card-sub">Every NHL transaction of the last twelve months (' + k.esc(k.fmtDate((dl.window || {}).from)) + ' to ' + k.esc(k.fmtDate((dl.window || {}).to)) + ', ESPN\'s public transactions feed), sorted into types, with every trade graded for each side: the value each club received at the time (our multi-season valuation as of the trade date, no hindsight; draft picks from our pick-value curve), what it has realised since (Rink value rate × ice time for the new club) and the current view (realised + what is still projected inside the original four-season window). Grades are a club\'s share of the value the deal moved: A ≥ 65 %, B ≥ 55 %, C 45–55 %, D ≥ 35 %, F below. On-field model value (WAR), not contracts or the salary cap: there is no free, legitimate salary source. <a href="#/methodology/moves">Method</a></span></div>';
  const top = tl[0], bot = tl[tl.length - 1];
  h += k.tiles([k.tile('Trades graded', k.int(N.graded), k.int(N.deals) + ' deals parsed · ' + k.int(N.picks) + ' picks · ' + k.int(N.players_matched) + ' of ' + k.int(N.players) + ' players matched'),
    k.tile('Biggest winner', top ? k.teamChip(top.team) : '—', top ? k.signed(top.net_now, 2) + ' WAR net (now) over ' + top.deals + ' deals' : ''),
    k.tile('Biggest loser', bot ? k.teamChip(bot.team) : '—', bot ? k.signed(bot.net_now, 2) + ' WAR net over ' + bot.deals + ' deals' : ''),
    k.tile('Transactions', k.int((tx.rows || []).length), Object.keys(tx.counts || {}).sort((a, b) => tx.counts[b] - tx.counts[a]).slice(0, 3).map(t => k.esc((tx.types || {})[t] || t) + ' ' + tx.counts[t]).join(' · '))]) + '</div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Winners and losers <span class="card-sub">Net value by club over the twelve months: WAR received minus WAR sent, at the time and now. Won / lost counts deals with a winner.</span></div><div id="mv-league"></div></div>' +
    '<div class="card"><div class="card-header">Net value by club <span class="card-sub">Now (bars) and at the time (dots), WAR.</span></div><div id="mv-net" class="gf-chart" style="height:560px"></div></div></div>';
  h += '<div class="card"><div class="card-header">Best deals <span class="card-sub">The deals whose winner gained the most (net WAR now).</span></div><div id="mv-best"></div></div>';
  const teams = Array.from(new Set(deals.reduce((a, d) => a.concat(d.teams), []).concat(txRows(tx).map(r => r.team)).filter(Boolean))).sort();
  h += '<div class="card"><div class="card-header">Graded trades <span class="card-sub" id="mv-deals-sub"></span></div><div class="lab-controls vl-ctl">' +
    '<label>Club<select id="mv-team"><option value="all">All clubs</option>' + teams.map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamName(t)) + '</option>').join('') + '</select></label>' +
    '<label>Minor deals<select id="mv-minor"><option value="0">Hide</option><option value="1">Show</option></select></label></div><div id="mv-deals"></div></div>';
  h += '<div class="card"><div class="card-header">All transactions <span class="card-sub" id="mv-tx-sub"></span></div><div class="lab-controls vl-ctl">' +
    '<label>Type<select id="mv-type"><option value="all">All types</option>' + Object.keys(tx.types || {}).map(t => '<option value="' + k.esc(t) + '">' + k.esc(tx.types[t]) + ' (' + ((tx.counts || {})[t] || 0) + ')</option>').join('') + '</select></label>' +
    '<label>Search<input id="mv-q" type="search" placeholder="player or text" autocomplete="off"></label></div><div id="mv-tx"></div>' +
    '<div class="pg-note gq-note">' + k.int((tx.names || {}).matched) + ' of ' + k.int((tx.names || {}).named) + ' names matched to NHL ids (' + k.int(tx.n_unmatched) + ' unmatched: mostly minor-league players with no NHL record; never guessed). Source: ' + k.esc(tx.source || 'ESPN') + '.</div></div>';
  const pc = dl.pick_curve;
  h += '<div class="card"><div class="card-header">Pick-value curve <span class="card-sub">What a draft slot is worth in our currency: every pick of the ' + k.esc(pc && pc.drafts ? pc.drafts[0] + '–' + pc.drafts[pc.drafts.length - 1] : '') + ' drafts, its WAR over its first ' + k.esc(pc ? pc.seasons : 7) + ' seasons discounted ' + k.esc(pc ? pc.discount : 0.9) + ' a season (floored at zero a season; picks who never played count zero), averaged by overall pick (dots) and fitted with a smooth decreasing curve v(p) = a (p + b)<sup>−c</sup>. A future pick of unknown slot is valued at its round\'s average, discounted by the seasons until its draft.</span></div>' +
    '<div class="grid-23"><div id="mv-pc" class="gf-chart" style="height:300px"></div><div id="mv-pc-t"></div></div></div>';
  el.innerHTML = h;
  const $ = id => document.getElementById(id);
  // league table
  $('mv-league').innerHTML = k.table([{ label: 'Club' }, { label: 'Deals', align: 'right' }, { label: 'In (time)', align: 'right' }, { label: 'Out (time)', align: 'right' }, { label: 'Net (time)', align: 'right' },
    { label: 'Net (now)', align: 'right' }, { label: 'W–L', align: 'right', title: 'Deals won and lost (now)' }],
  tl.map(x => ({ cells: [{ v: x.team, html: k.teamChip(x.team) }, x.deals, { v: x.in_at, html: k.num(x.in_at, 2) }, { v: x.out_at, html: k.num(x.out_at, 2) },
    { v: x.net_at, html: k.signed(x.net_at, 2) }, { v: x.net_now, html: '<strong class="' + (x.net_now > 0 ? 'pg-up' : x.net_now < 0 ? 'pg-down' : '') + '">' + k.signed(x.net_now, 2) + '</strong>' }, x.won + '–' + x.lost] })), { compact: true, sticky: true });
  k.sortable('mv-league');
  const tr = tl.slice().reverse();
  k.plot('mv-net', [{ type: 'bar', orientation: 'h', y: tr.map(x => x.team), x: tr.map(x => x.net_now), marker: { color: tr.map(x => (x.net_now >= 0 ? '#3fb950' : '#f85149')) }, name: 'Now', hovertemplate: '%{y}: %{x:.2f} WAR now<extra></extra>' },
    { type: 'scatter', mode: 'markers', y: tr.map(x => x.team), x: tr.map(x => x.net_at), marker: { color: '#e6edf3', size: 6 }, name: 'At the time', hovertemplate: '%{y}: %{x:.2f} WAR at the time<extra></extra>' }],
  k.layout({ margin: { l: 44, r: 12, t: 8, b: 40 }, xaxis: { title: { text: 'Net WAR' }, zeroline: true }, yaxis: { automargin: true, tickfont: { size: 10 } } }));
  $('mv-best').innerHTML = best.length ? best.slice(0, 5).map(d => dealCard(d)).join('') : k.muted('No graded deals yet.');
  $('mv-team').value = teams.indexOf(MT.team) >= 0 ? MT.team : 'all'; $('mv-minor').value = MT.minor; $('mv-type').value = (tx.types || {})[MT.type] ? MT.type : 'all';
  const rows = txRows(tx);
  function drawDeals() {
    const list = deals.filter(d => (MT.team === 'all' || d.teams.indexOf(MT.team) >= 0) && (MT.minor === '1' || !d.minor));
    $('mv-deals-sub').textContent = list.length + ' deals' + (MT.team === 'all' ? '' : ' involving ' + k.teamName(MT.team)) + (MT.minor === '1' ? '' : ' (minor deals hidden)');
    $('mv-deals').innerHTML = list.length ? list.slice(0, 60).map(d => dealCard(d, MT.team !== 'all' ? MT.team : null)).join('') + (list.length > 60 ? k.muted((list.length - 60) + ' more: pick a club.') : '') : k.muted('No deals match.');
  }
  function drawTx() {
    const needle = k.fold(($('mv-q').value || '').trim());
    const list = rows.filter(r => (MT.team === 'all' || r.team === MT.team) && (MT.type === 'all' || r.type === MT.type) && (!needle || k.fold(r.text).indexOf(needle) >= 0));
    $('mv-tx-sub').textContent = list.length + ' transactions' + (MT.team === 'all' ? '' : ' · ' + k.teamName(MT.team));
    $('mv-tx').innerHTML = list.length ? k.table([{ label: 'Date' }, { label: 'Club' }, { label: 'Type' }, { label: 'Transaction' }],
      list.slice(0, MT.n).map(r => [{ v: r.date, html: k.esc(k.fmtDate(r.date)) }, { v: r.team, html: k.teamChip(r.team) }, { v: r.type, html: '<span class="mv-type mv-t-' + k.esc(r.type) + '">' + k.esc((tx.types || {})[r.type] || r.type) + '</span>' },
        { v: r.text, html: '<span class="mv-text">' + k.esc(r.text) + '.</span>' + (r.deal ? ' <a href="#/moves?team=' + encodeURIComponent(r.team || '') + '" data-deal="' + k.esc(r.deal) + '" class="mv-dl">grade →</a>' : '') }]), { compact: true }) +
      (list.length > MT.n ? '<div class="pad"><button type="button" class="tbtn" id="mv-more">Show more</button></div>' : '') : k.muted('No transactions match.');
    const more = $('mv-more');
    if (more) more.onclick = () => { MT.n += 300; drawTx(); };
    $('mv-tx').querySelectorAll('a.mv-dl').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      MT.team = 'all'; MT.minor = '1'; $('mv-team').value = 'all'; $('mv-minor').value = '1'; drawDeals();
      const n = document.getElementById('deal-' + a.dataset.deal);
      if (n) { n.scrollIntoView({ block: 'center' }); n.classList.add('mv-flash'); }
    }));
  }
  function sync() {
    try {
      const qs = [];
      if (MT.team !== 'all') qs.push('team=' + encodeURIComponent(MT.team));
      if (MT.type !== 'all') qs.push('type=' + encodeURIComponent(MT.type));
      if (MT.minor === '1') qs.push('minor=1');
      history.replaceState(null, '', '#/value?tab=moves' + (qs.length ? '&' + qs.join('&') : ''));
    } catch (e) { /* history unavailable */ }
  }
  $('mv-team').onchange = e => { MT.team = e.target.value; MT.n = 150; sync(); drawDeals(); drawTx(); };
  $('mv-minor').onchange = e => { MT.minor = e.target.value; sync(); drawDeals(); };
  $('mv-type').onchange = e => { MT.type = e.target.value; MT.n = 150; sync(); drawTx(); };
  $('mv-q').oninput = () => { MT.n = 150; drawTx(); };
  drawDeals();
  drawTx();
  pickCurve(dl);
}

function pickCurve(dl) {
  const k = K();
  const pc = dl.pick_curve;
  if (!pc || !pc.ok) { k.empty('mv-pc', 'The pick-value curve is not available.'); return; }
  const raw = dl.pick_raw || [];
  k.plot('mv-pc', [{ type: 'scatter', mode: 'markers', x: raw.map(r => r[0]), y: raw.map(r => r[1]), marker: { size: 4, color: 'rgba(139,148,158,0.6)' }, name: 'Mean of the slot', hovertemplate: 'No. %{x}: %{y:.2f} WAR<extra></extra>' },
    { type: 'scatter', mode: 'lines', x: pc.points.map(p => p[0]), y: pc.points.map(p => p[1]), line: { color: k.ACC, width: 2.5 }, name: 'Fitted curve', hovertemplate: 'No. %{x}: %{y:.2f} WAR<extra></extra>' }],
  k.layout(Object.assign({ margin: { l: 52, r: 12, t: 10, b: 44 }, xaxis: { title: { text: 'Overall pick' } }, yaxis: { title: { text: 'Discounted WAR, first 7 seasons' }, rangemode: 'tozero' } }, k.legendTop())));
  const emp = pc.round_empirical || {};
  document.getElementById('mv-pc-t').innerHTML = k.table([{ label: 'Round' }, { label: 'Curve avg', align: 'right', title: 'Fitted curve averaged over the round (slots 32 a round)' }, { label: 'Observed', align: 'right' }, { label: 'Played', align: 'right', title: 'Share of picks with any positive WAR' }, { label: 'Picks', align: 'right' }],
    [1, 2, 3, 4, 5, 6, 7].map(r => { const e = emp[String(r)] || []; return [ORD[r], { v: (pc.round_avg || {})[String(r)], html: k.num((pc.round_avg || {})[String(r)], 2) }, { v: e[0], html: k.num(e[0], 2) }, { v: e[2], html: k.pct(e[2], 0) }, e[1]]; }), { compact: true }) +
    '<div class="pg-note gq-note">Fit: a = ' + k.num(pc.a, 2) + ', b = ' + k.num(pc.b, 2) + ', c = ' + k.num(pc.c, 3) + '; R² ' + k.num(pc.r2_slots, 2) + ' on the slot means, ' + k.num(pc.r2_bins, 2) + ' on 16-pick bins; ' + k.int(pc.n_picks) + ' picks.</div>';
}

/* The team page's Ledger: the club's graded deals and its transactions. */
function ledger(host, abbr) {
  const k = K();
  if (!host) return;
  const S = k.curSeason();
  Promise.all([k.loadY(S, 'deals.json'), k.loadY(S, 'transactions.json')]).then(res => {
    if (!host.isConnected) return;
    const dl = res[0], tx = res[1];
    if (!k.ok(dl) || !k.ok(tx)) { host.innerHTML = '<div class="pad">' + k.notBuilt('The ledger', k.ok(dl) ? tx : dl) + '</div>'; return; }
    const deals = (dl.deals || []).filter(d => d.teams.indexOf(abbr) >= 0);
    const T = (dl.teams || {})[abbr] || {};
    const rows = txRows(tx).filter(r => r.team === abbr);
    const graded = deals.filter(d => !d.minor);
    let h = k.tiles([k.tile('Trades (12 months)', k.int(deals.length), graded.length + ' graded · won ' + (T.won || 0) + ', lost ' + (T.lost || 0)),
      k.tile('Net value now', k.isNum(T.net_now) ? k.signed(T.net_now, 2) : '—', 'WAR received − sent (at the time ' + (k.isNum(T.net_at) ? k.signed(T.net_at, 2) : '—') + ')'),
      k.tile('Transactions', k.int(rows.length), Object.keys(tx.types || {}).map(t => [t, rows.filter(r => r.type === t).length]).filter(x => x[1]).sort((a, b) => b[1] - a[1]).slice(0, 3).map(x => k.esc((tx.types || {})[x[0]]) + ' ' + x[1]).join(' · '))]);
    h += graded.length ? '<div class="pad">' + graded.map(d => dealCard(d, abbr)).join('') + '</div>' : '<div class="pad">' + k.muted('No graded trades in the last twelve months.') + '</div>';
    const minor = deals.filter(d => d.minor);
    if (minor.length) h += '<details class="tr-rot"><summary>Minor deals (' + minor.length + ')</summary><div class="pad">' + minor.map(d => dealCard(d, abbr)).join('') + '</div></details>';
    h += '<details class="tr-rot"' + (rows.length <= 12 ? ' open' : '') + '><summary>All transactions (' + rows.length + ')</summary>' + k.table([{ label: 'Date' }, { label: 'Type' }, { label: 'Transaction' }],
      rows.map(r => [{ v: r.date, html: k.esc(k.fmtDate(r.date)) }, { v: r.type, html: '<span class="mv-type mv-t-' + k.esc(r.type) + '">' + k.esc((tx.types || {})[r.type] || r.type) + '</span>' }, { v: r.text, html: '<span class="mv-text">' + k.esc(r.text) + '.</span>' }]), { compact: true }) + '</details>';
    h += '<div class="pg-note gq-note">Values are on-field model value (WAR) from our multi-season valuation, not contracts or the cap. <a href="#/moves?team=' + encodeURIComponent(abbr) + '">All moves →</a></div>';
    host.innerHTML = h;
  });
}

RK.route('moves', render);
RK.moves = { dealCard: dealCard, ledger: ledger };
})(window.RK);
