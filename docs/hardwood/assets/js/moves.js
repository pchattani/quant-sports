/* The Quant Hardwood — moves (#/<L>/moves): every transaction of the last 12 months from ESPN's feed, trade
 * ratings (value at the time with no hindsight, realised since, and today's view), the league's winners and
 * losers, and the pick-value curve; plus HW.movesLedger, the team page's ledger.
 *
 * Data: data/<L>/<S>/transactions.json and deals.json for the current season (analytics/moves.py).
 * Values are four-season WAR (valuation v2), discounted 0.9 a season from the trade's season. A side's share
 * is value in / (value in + value out) on positive parts; grades A >= 0.65, B >= 0.55, C 0.45-0.55, D >= 0.35,
 * F below; "minor" when the deal moved little value. On-field value only: no salaries or contracts. */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const ST = { tab: 'ratings', basis: 'now', team: 'all', type: 'all', q: '' };

function grade(g) {
  if (!g) return '—';
  if (g === 'minor') return '<span class="chip" title="The deal moved little value">minor</span>';
  return '<span class="nd-grade nd-' + String(g).toLowerCase() + '">' + FX().esc(g) + '</span>';
}

function itemsHTML(L, items, basis) {
  const fx = FX();
  if (!items || !items.length) return '<span class="muted-inline">nothing of value</span>';
  return items.map(x => {
    if (x.k === 'pick') return '<span class="mv-pick">' + fx.esc(x.label) + '</span> <span class="muted-inline">' + fx.num(x.v, 1) + '</span>';
    const v = basis === 'now' ? x.now : x.v;
    const extra = basis === 'now' ? (fx.isNum(x.real) ? ' (' + fx.num(x.real, 1) + ' so far' + (x.still ? '' : ', gone') + ')' : '') : '';
    return fx.playerLink(L, x.id, x.name) + ' <span class="muted-inline">' + fx.num(v, 1) + extra + '</span>';
  }).join(', ');
}

function sideOf(dl, t) { return (dl.sides || []).filter(s => s.team === t)[0]; }

function dealCard(L, dl, basis, focus) {
  const fx = FX();
  const win = basis === 'now' ? dl.winner_now : dl.winner;
  let h = '<div class="mv-deal"><div class="mv-deal-h"><strong>' + fx.esc(fx.fmtDate(dl.date)) + '</strong> · ' +
    (dl.sides || []).map(s => fx.teamLink(L, s.team, { abbr: true })).join(' ⇄ ') +
    ' <span class="muted-inline">' + fx.num(basis === 'now' ? dl.total_now : dl.total, 1) + ' WAR moved' + (win ? ' · edge ' + fx.esc(fx.teamAbbr(L, win)) : '') + '</span></div>';
  h += '<div class="mv-sides">' + (dl.sides || []).map(s => {
    const g = basis === 'now' ? s.grade_now : s.grade;
    const sh = basis === 'now' ? s.share_now : s.share;
    const vin = basis === 'now' ? s.now_in : s.v_in, vout = basis === 'now' ? s.now_out : s.v_out;
    return '<div class="mv-side' + (focus && s.team === focus ? ' mv-focus' : '') + '"><div>' + grade(g) + ' ' + fx.teamLink(L, s.team) +
      ' <span class="muted-inline">' + (fx.isNum(sh) ? fx.num(100 * sh, 0) + '% of the value · ' : '') + 'net ' + fx.signed(vin - vout, 1) + '</span></div>' +
      '<div class="mv-io"><span class="muted-inline">In</span> ' + itemsHTML(L, s.in, basis) + '</div>' +
      '<div class="mv-io"><span class="muted-inline">Out</span> ' + itemsHTML(L, s.out, basis) + '</div></div>';
  }).join('') + '</div>';
  h += '<details class="tr-rot"><summary>ESPN\'s wording' + ((dl.zero || []).length ? ' · ' + fx.esc(dl.zero.join(', ')) + ' valued at zero' : '') + '</summary><div class="mv-text">' +
    (dl.rows || []).map(r => '<div><span class="muted-inline">' + fx.esc(fx.teamAbbr(L, r.team)) + ' ' + fx.esc(r.date) + '</span> ' + fx.esc(r.text) + '</div>').join('') + '</div></details></div>';
  return h;
}

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    const S = fx.current(L) || fx.S(params, state, L);
    const q = (params && params.query) || {};
    if (q.mt) ST.tab = q.mt;
    ['basis', 'team', 'type'].forEach(k => { if (q[k]) ST[k] = q[k]; });
    return HW.loadAll([fx.path(L, S, 'deals.json'), fx.path(L, S, 'transactions.json')]).then(r => {
      if (!fx.alive(el)) return;
      const dp = r[0], tx = r[1];
      if (!fx.ok(dp) && !fx.ok(tx)) { el.innerHTML = fx.card('Moves', '', fx.notBuilt('Transactions and trade ratings for ' + fx.seasonLabel(L, S), dp || tx)); return; }
      draw(el, L, S, dp, tx);
    });
  });
}

function draw(el, L, S, dp, tx) {
  const fx = FX();
  const deals = (fx.ok(dp) && dp.deals) || [];
  const rated = deals.filter(d => (d.sides || []).some(s => (s.in || []).length || (s.out || []).length));
  let h = '<div class="card"><div class="card-header">Moves ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">Trades, signings and releases from ESPN\'s transactions feed (' +
    fx.esc(fx.fmtDate((tx || {}).since)) + ' – ' + fx.esc(fx.fmtDate((tx || {}).until)) + '), parsed by the site; every trade rated on on-field value in WAR over four seasons (valuation v2). <strong>No salaries or cap</strong>: there is no free, legitimate salary source (Spotrac, HoopsHype and Basketball-Reference terms forbid reuse). <a href="#/methodology">Methodology</a></span></div>';
  h += '<div class="kpi-grid">' + [fx.tile('Transactions', fx.num(((tx || {}).rows || []).length, 0), 'last 12 months'), fx.tile('Trades rated', fx.num(rated.length, 0), 'grouped into deals'),
    fx.tile('Pick curve', fx.num(((dp || {}).pick_curve || {}).n_drafts, 0) + ' drafts', 'our WAR by draft slot'), fx.tile('Unmatched names', fx.num(((dp || {}).unmatched || []).length, 0), 'listed, never guessed')].join('') + '</div>';
  h += '<div class="pad">' + fx.toggle('mv-tab', [['ratings', 'Trade ratings'], ['feed', 'Feed'], ['picks', 'Pick values']], ST.tab) + ' ' +
    '<span id="mv-basis-w">' + fx.toggle('mv-basis', [['now', 'Today\'s view'], ['time', 'At the time']], ST.basis) + '</span></div></div><div id="mv-body"></div>';
  el.innerHTML = h;
  const redraw = () => { syncUrl(L); document.getElementById('mv-basis-w').style.display = ST.tab === 'ratings' ? '' : 'none'; body(L, S, dp, tx, rated); };
  fx.wireToggle(el, 'mv-tab', v => { ST.tab = v; redraw(); });
  fx.wireToggle(el, 'mv-basis', v => { ST.basis = v; redraw(); });
  redraw();
}

function body(L, S, dp, tx, rated) {
  const fx = FX();
  const box = document.getElementById('mv-body');
  if (ST.tab === 'feed') { feed(L, tx, box); return; }
  if (ST.tab === 'picks') { picks(L, dp, box); return; }
  const now = ST.basis === 'now';
  const teams = Object.keys((dp || {}).teams || {});
  const rows = teams.map(t => { const x = dp.teams[t]; return { t: t, x: x }; }).sort((a, b) => (now ? b.x.net_now - a.x.net_now : b.x.net_time - a.x.net_time));
  let h = '<div class="card"><div class="card-header">Winners and losers <span class="card-sub">Net value from each team\'s trades in the last 12 months: at the time (four-season value as of the trade date, no hindsight), realised since (our model\'s value of what the incoming and outgoing players have produced for their new teams, updated as games are played), and today\'s view (realised plus today\'s projection of what is left of the four seasons while the player is still there; picks at curve value).</span></div>' +
    HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'Deals', align: 'right' }, { label: 'In (time)', align: 'right' }, { label: 'Out (time)', align: 'right' }, { label: 'Net at the time', align: 'right' }, { label: 'Realised net', align: 'right' }, { label: 'Net today', align: 'right' }],
      rows.map((r, i) => [i + 1, { v: fx.teamName(L, r.t), html: fx.teamLink(L, r.t) }, r.x.n, { v: r.x.in_time, html: fx.num(r.x.in_time, 1) }, { v: r.x.out_time, html: fx.num(r.x.out_time, 1) },
        { v: r.x.net_time, html: signedCls(r.x.net_time) }, { v: r.x.net_real, html: signedCls(r.x.net_real) }, { v: r.x.net_now, html: '<strong>' + signedCls(r.x.net_now) + '</strong>' }]), { compact: true, sticky: true }) + '</div>';
  const lop = d => Math.max.apply(null, (d.sides || []).map(s => Math.abs((now ? s.now_in - s.now_out : s.v_in - s.v_out) || 0)).concat([0]));
  const top = rated.slice().sort((a, b) => lop(b) - lop(a)).slice(0, 6);
  h += fx.card('Most lopsided deals', (now ? 'Today\'s view' : 'At the time') + ': the biggest gap between what a side gave and got.', '<div class="pad">' + top.map(d => dealCard(L, d, ST.basis)).join('') + '</div>');
  const teamOpts = Array.from(new Set(rated.reduce((a, d) => a.concat(d.teams || []), []))).sort((a, b) => String(fx.teamName(L, a)).localeCompare(String(fx.teamName(L, b))));
  h += '<div class="card"><div class="card-header">Every trade <span class="card-sub" id="mv-n"></span></div><div class="lab-controls hf-controls"><label>Team<select id="mv-team"><option value="all">All teams</option>' +
    teamOpts.map(t => '<option value="' + fx.esc(t) + '"' + (ST.team === t ? ' selected' : '') + '>' + fx.esc(fx.teamName(L, t)) + '</option>').join('') + '</select></label></div><div class="pad" id="mv-all"></div></div>';
  box.innerHTML = h;
  HW.sortable(box);
  const all = () => {
    const list = rated.filter(d => ST.team === 'all' || (d.teams || []).indexOf(ST.team) >= 0);
    document.getElementById('mv-n').textContent = list.length + ' deals, newest first';
    document.getElementById('mv-all').innerHTML = list.map(d => dealCard(L, d, ST.basis, ST.team !== 'all' ? ST.team : null)).join('') || fx.muted('No trades.');
  };
  document.getElementById('mv-team').onchange = e => { ST.team = e.target.value; syncUrl(L); all(); };
  all();
}

function signedCls(v) { const fx = FX(); return '<span class="' + (v > 0.05 ? 'pg-up' : v < -0.05 ? 'pg-down' : '') + '">' + fx.signed(v, 1) + '</span>'; }

function feed(L, tx, box) {
  const fx = FX();
  if (!fx.ok(tx)) { box.innerHTML = fx.card('Feed', '', fx.notBuilt('The transactions feed', tx)); return; }
  const cols = tx.cols || [];
  const rows = (tx.rows || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  const types = tx.types || {};
  const teams = Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort((a, b) => String(fx.teamName(L, a)).localeCompare(String(fx.teamName(L, b))));
  box.innerHTML = '<div class="card"><div class="card-header">Feed <span class="card-sub" id="mv-fn"></span></div><div class="lab-controls hf-controls">' +
    '<label>Team<select id="mv-ft"><option value="all">All teams</option>' + teams.map(t => '<option value="' + fx.esc(t) + '"' + (ST.team === t ? ' selected' : '') + '>' + fx.esc(fx.teamName(L, t)) + '</option>').join('') + '</select></label>' +
    '<label>Type<select id="mv-fy"><option value="all">All types</option>' + Object.keys(types).map(k => '<option value="' + fx.esc(k) + '"' + (ST.type === k ? ' selected' : '') + '>' + fx.esc(types[k]) + '</option>').join('') + '</select></label>' +
    '<label>Search<input id="mv-fq" type="search" value="' + fx.esc(ST.q) + '" placeholder="Player or word"></label></div><div id="mv-ftab"></div>' +
    '<div class="pg-note">Source: ESPN\'s transactions feed, one row per team per day in ESPN\'s words. Linked players are matched to our player pages by name (accents, apostrophes and suffixes normalised; close spellings only when the team agrees). ' +
    ((tx.unmatched || []).length ? 'Names we could not match (mostly two-way and G League players with no games in our data): ' + fx.esc((tx.unmatched || []).slice(0, 40).join(', ')) + ((tx.unmatched || []).length > 40 ? '…' : '') + '.' : '') + '</div></div>';
  const draw = () => {
    const q = ST.q.toLowerCase();
    const list = rows.filter(r => (ST.team === 'all' || r.team === ST.team) && (ST.type === 'all' || (r.types || []).indexOf(ST.type) >= 0) && (!q || String(r.text).toLowerCase().indexOf(q) >= 0));
    document.getElementById('mv-fn').textContent = list.length + ' of ' + rows.length + ' rows';
    document.getElementById('mv-ftab').innerHTML = HW.tableHTML([{ label: 'Date' }, { label: 'Team' }, { label: 'Type' }, { label: 'Transaction' }],
      list.slice(0, 400).map(r => [{ v: r.date, html: fx.esc(r.date) }, { v: fx.teamAbbr(L, r.team), html: fx.teamLink(L, r.team, { abbr: true }) },
        { v: (r.types || []).join(','), html: (r.types || []).map(t => '<span class="chip' + (t === 'trade' ? ' info' : t === 'release' ? ' red' : t === 'sign' ? ' ok' : '') + '">' + fx.esc(types[t] || t) + '</span>').join(' ') },
        { v: r.text, html: '<span class="mv-txt">' + fx.esc(r.text) + '</span>' + ((r.players || []).length ? '<div class="vl-why">' + r.players.map(p => fx.playerLink(L, p)).join(' · ') + '</div>' : '') +
          (r.deal ? ' <a class="muted-inline" href="#/' + L + '/moves?tab=ratings">rated ›</a>' : '') }]), { compact: true });
  };
  document.getElementById('mv-ft').onchange = e => { ST.team = e.target.value; syncUrl(L); draw(); };
  document.getElementById('mv-fy').onchange = e => { ST.type = e.target.value; syncUrl(L); draw(); };
  document.getElementById('mv-fq').oninput = e => { ST.q = e.target.value; draw(); };
  draw();
}

function picks(L, dp, box) {
  const fx = FX();
  const pc = (dp || {}).pick_curve || {};
  if (!(pc.picks || []).length) { box.innerHTML = fx.card('Pick values', '', fx.muted('No pick-value curve: ESPN lists too few drafts for this league.')); return; }
  const rounds = pc.rounds || {};
  box.innerHTML = '<div class="card"><div class="card-header">Pick-value curve <span class="card-sub">Expected value of each draft slot in WAR over the first ' + fx.num(pc.seasons, 0) + ' seasons after the draft (each season floored at zero, discounted 0.9 a season), from our own player value for every pick of the ' + fx.num(pc.n_drafts, 0) + ' drafts ESPN lists from ' + fx.esc((pc.years || [])[0]) + ' to ' + fx.esc((pc.years || [])[1]) + ' (a pick who never played counts zero), made non-increasing and smoothed over five picks. A future pick of unknown slot counts at its round\'s mean (' +
    Object.keys(rounds).map(k => 'round ' + k + ': ' + fx.num(rounds[k], 2)).join(', ') + '), discounted 0.9 a season until it first plays. Pick swaps, draft and cash considerations count zero.</span></div><div id="mv-pc" style="height:360px"></div>' +
    HW.tableHTML([{ label: 'Pick', align: 'right' }, { label: 'Curve', align: 'right' }, { label: 'Raw mean', align: 'right' }, { label: 'Drafts', align: 'right' }],
      (pc.raw || []).filter(r => r[0] <= 10 || r[0] % 5 === 0).map(r => { const c = (pc.picks || []).filter(p => p[0] === r[0])[0]; return [r[0], { v: c ? c[1] : null, html: fx.num(c ? c[1] : null, 2) }, { v: r[1], html: fx.num(r[1], 2) }, r[2]]; }), { compact: true }) + '</div>';
  fx.plot('mv-pc', [{ type: 'scatter', mode: 'markers', name: 'Mean by pick', x: (pc.raw || []).map(r => r[0]), y: (pc.raw || []).map(r => r[1]), marker: { color: '#6e7681', size: 5 }, hovertemplate: 'Pick %{x}: %{y:.2f} WAR<extra></extra>' },
    { type: 'scatter', mode: 'lines', name: 'Curve', x: pc.picks.map(p => p[0]), y: pc.picks.map(p => p[1]), line: { color: '#f0883e', width: 3 }, hovertemplate: 'Pick %{x}: %{y:.2f} WAR<extra></extra>' }],
  fx.layout({ margin: { l: 50, r: 10, t: 20, b: 45 }, legend: { orientation: 'h', y: 1.1, font: { size: 10 } }, xaxis: { title: 'Overall pick' }, yaxis: { title: 'WAR, first four seasons (discounted)', rangemode: 'tozero' } }));
}

function syncUrl(L) {
  try {
    const q = [];
    q.push('tab=moves');
    if (ST.tab !== 'ratings') q.push('mt=' + ST.tab);
    if (ST.basis !== 'now') q.push('basis=' + ST.basis);
    if (ST.team !== 'all') q.push('team=' + encodeURIComponent(ST.team));
    if (ST.type !== 'all') q.push('type=' + encodeURIComponent(ST.type));
    history.replaceState(null, '', '#/' + L + '/value' + (q.length ? '?' + q.join('&') : ''));
  } catch (e) { /* history unavailable */ }
}

/* The team page's ledger: the team's transactions and its rated deals. */
HW.movesLedger = function (box, L, S, tid) {
  const fx = FX();
  HW.loadAll([fx.path(L, S, 'deals.json'), fx.path(L, S, 'transactions.json')]).then(r => {
    if (!box || !box.isConnected) return;
    const dp = r[0], tx = r[1];
    if (!fx.ok(dp) && !fx.ok(tx)) { box.innerHTML = '<div class="pad">' + fx.notBuilt('The ledger', dp || tx) + '</div>'; return; }
    const deals = ((dp || {}).deals || []).filter(d => (d.teams || []).indexOf(tid) >= 0 && (d.sides || []).some(s => s.team === tid && ((s.in || []).length || (s.out || []).length)));
    const t = ((dp || {}).teams || {})[tid];
    let h = '';
    if (t) h += '<div class="kpi-grid">' + [fx.tile('Trades', fx.num(t.n, 0), 'last 12 months'), fx.tile('Net at the time', fx.signed(t.net_time, 1), 'WAR, four seasons'),
      fx.tile('Realised net', fx.signed(t.net_real, 1), 'so far'), fx.tile('Net today', fx.signed(t.net_now, 1), 'realised + projection')].join('') + '</div>';
    h += deals.length ? '<div class="pad">' + deals.map(d => dealCard(L, d, 'now', tid)).join('') + '</div>' : '<div class="pad">' + fx.muted('No trades in the last 12 months.') + '</div>';
    const cols = (tx || {}).cols || [];
    const rows = ((tx || {}).rows || []).map(x => { const o = {}; cols.forEach((c, i) => { o[c] = x[i]; }); return o; }).filter(x => x.team === tid);
    h += '<details class="tr-rot mv-ledger"><summary>All ' + rows.length + ' transactions in the last 12 months</summary>' +
      HW.tableHTML([{ label: 'Date' }, { label: 'Transaction' }], rows.map(x => [{ v: x.date, html: fx.esc(x.date) }, { v: x.text, html: '<span class="mv-txt">' + fx.esc(x.text) + '</span>' }]), { compact: true }) + '</details>' +
      '<div class="pg-note">Grades in today\'s view: the share of the deal\'s value this team received (A at least 65%, F under 35%). <a href="' + fx.href(L, 'moves') + '">Every trade in the league →</a></div>';
    box.innerHTML = h;
  });
};

HW.route('moves', render);
})(window.HW);
