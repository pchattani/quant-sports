/* The Quant Hardwood — moves (#/<L>/moves): every transaction of the last 12 months from ESPN's feed, trade
 * ratings (value at the time with no hindsight, realised since, and today's view), the league's winners and
 * losers, and the pick-value curve; plus HW.movesLedger, the team page's ledger.
 *
 * Data: data/<L>/<S>/transactions.json, deals.json and picks.json for the current season (analytics/moves.py,
 * analytics/picks.py: the pick-value curve, its validation and every team's own future picks).
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

function slotTxt(sl) {
  if (!sl || !sl.length) return '';
  return sl[0] === sl[1] ? 'slot ' + sl[0] : 'likely slot ' + sl[0] + '–' + sl[1];
}

/* "2027 1st (via PHX): ≈ 3.4, likely slot 19–27"; a used pick names the player it became. */
function pickHTML(L, x, basis) {
  const fx = FX();
  const now = basis === 'now';
  const v = now ? x.now : x.v;
  const sl = now ? x.slot_now : x.slot;
  let h = '<span class="mv-pick">' + fx.esc(x.label) + (x.n ? ' ×' + x.n : '') + (x.via ? ' (via ' + fx.esc(fx.teamAbbr(L, x.via)) + ')' : '') + '</span>';
  h += ' <span class="muted-inline">≈ ' + fx.num(v, 1);
  if (now && x.pid) h += ' → ' + fx.playerLink(L, x.pid, x.pname) + (sl ? ' (No. ' + sl[0] + ')' : '') + (fx.isNum(x.real) ? ', ' + fx.num(x.real, 1) + ' so far' : '');
  else if (sl && !x.swap) h += ', ' + slotTxt(sl);
  if (fx.isNum(x.conv)) h += ', conveys ' + fx.num(100 * x.conv, 0) + '%';
  h += '</span>';
  if (x.note) h = '<span title="' + fx.esc(x.note) + '">' + h + '</span>';
  return h;
}

function itemsHTML(L, items, basis) {
  const fx = FX();
  if (!items || !items.length) return '<span class="muted-inline">nothing of value</span>';
  return items.map(x => {
    if (x.k === 'pick') return pickHTML(L, x, basis);
    const v = basis === 'now' ? x.now : x.v;
    const extra = basis === 'now' ? (fx.isNum(x.real) ? ' (' + fx.num(x.real, 1) + ' so far' + (x.still ? '' : ', gone') + ')' : '') : '';
    const rookie = fx.isNum(x.slot) ? ' <span class="chip" title="Drafted No. ' + x.slot + ': valued from the pick curve (' + fx.num(x.prior, 1) + ')' + (fx.isNum(x.wp) ? ', weight ' + fx.num(100 * x.wp, 0) + '% at the time' : '') + ' until he has played">No. ' + x.slot + '</span>' : '';
    return fx.playerLink(L, x.id, x.name) + rookie + ' <span class="muted-inline">' + fx.num(v, 1) + extra + '</span>';
  }).join(', ');
}

function sideOf(dl, t) { return (dl.sides || []).filter(s => s.team === t)[0]; }

function dealCard(L, dl, basis, focus) {
  const fx = FX();
  const win = basis === 'now' ? dl.winner_now : dl.winner;
  let h = '<div class="mv-deal"><div class="mv-deal-h"><strong>' + fx.esc(fx.fmtDate(dl.date)) + '</strong> · ' +
    (dl.sides || []).map(s => fx.teamLink(L, s.team, { abbr: true })).join(' ⇄ ') +
    ' <span class="muted-inline">' + fx.num(basis === 'now' ? dl.total_now : dl.total, 1) + ' WAR moved' + (win ? ' · better for ' + fx.esc(fx.teamAbbr(L, win)) : '') + '</span></div>';
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
    return HW.loadAll([fx.path(L, S, 'deals.json'), fx.path(L, S, 'transactions.json'), fx.path(L, S, 'picks.json')]).then(r => {
      if (!fx.alive(el)) return;
      const dp = r[0], tx = r[1];
      if (!fx.ok(dp) && !fx.ok(tx)) { el.innerHTML = fx.card('Moves', '', fx.notBuilt('Transactions and trade ratings for ' + fx.seasonLabel(L, S), dp || tx)); return; }
      ST.pk = fx.ok(r[2]) ? r[2] : null;
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
    fx.tile('Pick curve', fx.num(((dp || {}).pick_curve || {}).n_drafts, 0) + ' drafts', 'our WAR by draft slot, validated on held-out drafts'), fx.tile('Unmatched names', fx.num(((dp || {}).unmatched || []).length, 0), 'listed, never guessed')].join('') + '</div>';
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
  let h = '<div class="card"><div class="card-header">Winners and losers <span class="card-sub">Net value from each team\'s trades in the last 12 months: at the time (four-season value as of the trade date, no hindsight), realised since (our model\'s value of what the incoming and outgoing players have produced for their new teams, updated as games are played), and today\'s view (realised plus today\'s projection of what is left of the four seasons while the player is still there; a pick from today\'s projected finish of its original owner, or the player it became once used).</span></div>' +
    HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'Deals', align: 'right' }, { label: 'In (time)', align: 'right' }, { label: 'Out (time)', align: 'right' }, { label: 'Net at the time', align: 'right' }, { label: 'Realised net', align: 'right' }, { label: 'Net today', align: 'right' }],
      rows.map((r, i) => [i + 1, { v: fx.teamName(L, r.t), html: fx.teamLink(L, r.t) }, r.x.n, { v: r.x.in_time, html: fx.num(r.x.in_time, 1) }, { v: r.x.out_time, html: fx.num(r.x.out_time, 1) },
        { v: r.x.net_time, html: signedCls(r.x.net_time) }, { v: r.x.net_real, html: signedCls(r.x.net_real) }, { v: r.x.net_now, html: '<strong>' + signedCls(r.x.net_now) + '</strong>' }]), { compact: true, sticky: true }) + '</div>';
  const lop = d => Math.max.apply(null, (d.sides || []).map(s => Math.abs((now ? s.now_in - s.now_out : s.v_in - s.v_out) || 0)).concat([0]));
  const top = rated.slice().sort((a, b) => lop(b) - lop(a)).slice(0, 6);
  h += fx.card('Most lopsided deals', (now ? 'Today\'s view' : 'At the time') + ': the widest difference between what a side gave and got.', '<div class="pad">' + top.map(d => dealCard(L, d, ST.basis)).join('') + '</div>');
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
  const pk = ST.pk || {};
  const v = pc.v || (pc.picks || []).map(p => p[1]);
  if (!v.length) { box.innerHTML = fx.card('Pick values', '', fx.muted('No pick-value curve: too few drafts with four complete seasons for this league.')); return; }
  const rounds = pc.rounds || {};
  const per = pc.per_round || (L === 'wnba' ? 12 : 30);
  const xs = v.map((_x, i) => i + 1);
  const rows = xs.filter(o => o <= 14 || o % 5 === 0 || o === per + 1).map(o => {
    const raw = (pc.raw || []).filter(r => r[0] === o)[0];
    return [o, { v: v[o - 1], html: '<strong>' + fx.num(v[o - 1], 1) + '</strong>' }, { v: (pc.lo || [])[o - 1], html: fx.num((pc.lo || [])[o - 1], 1) + '–' + fx.num((pc.hi || [])[o - 1], 1) },
      { v: (pc.q50 || [])[o - 1], html: fx.num((pc.q10 || [])[o - 1], 1) + ' / ' + fx.num((pc.q50 || [])[o - 1], 1) + ' / ' + fx.num((pc.q90 || [])[o - 1], 1) },
      { v: raw ? raw[1] : null, html: raw ? fx.num(raw[1], 1) : '—' }, raw ? raw[2] : 0];
  });
  let h = '<div class="card"><div class="card-header">Pick-value curve <span class="card-sub">What a draft slot is worth, in the players\' unit: wins above replacement over the drafted player\'s first ' + fx.num(pc.seasons, 0) +
    ' seasons (the rookie-scale years; each season floored at zero, discounted 0.9 a season), from our own value for all ' + fx.num(pc.n_picks, 0) + ' picks of the ' + fx.num(pc.n_drafts, 0) + ' drafts from ' + fx.esc((pc.years || [])[0]) + ' to ' + fx.esc((pc.years || [])[1]) +
    ' (a pick who never played counts zero). Smoothed with a kernel that widens down the draft and made non-increasing; the band is the 10th–90th percentile over bootstrap resamples of whole drafts. Round averages: ' +
    Object.keys(rounds).map(k => 'round ' + k + ' ' + fx.num(rounds[k], 1)).join(', ') + '.</span></div><div id="mv-pc" style="height:360px"></div>' +
    HW.tableHTML([{ label: 'Pick', align: 'right' }, { label: 'Value', align: 'right', title: 'Expected four-season WAR' }, { label: '80% band', align: 'right', title: 'Uncertainty of the expected value (bootstrap over drafts)' },
      { label: 'One pick: 10th / 50th / 90th', align: 'right', title: 'What a single pick at this slot becomes' }, { label: 'Raw mean', align: 'right' }, { label: 'Drafts', align: 'right' }], rows, { compact: true }) + '</div>';
  h += validationHTML(L, pk.validation);
  h += teamPicksHTML(L, pk);
  h += '<div class="card"><div class="pad pg-note"><strong>How a traded pick is valued.</strong> The pick\'s original owner\'s slot distribution in that draft: this season from the season simulation (the lottery for the 14 non-playoff teams, then the playoff teams in reverse order; the second round in reverse order of record); later drafts from a regression of win % on win % k seasons earlier, fitted on our standings (' +
    fx.esc(((pk.persistence || {}).beta || []).slice(0, 4).map((b, i) => (i + 1) + ' yr ' + fx.num(b, 2)).join(', ')) + '; none beyond), all teams drawn together and ranked. Value = the curve over that distribution, discounted 0.9 a season to the pick\'s first season. ' +
    '"At the time" uses only the standings of the last season finished before the trade; today\'s view uses today\'s simulation. Top-N protected picks convey only outside the top N, else roll a year with the same protection and then convey unprotected (ESPN rarely states the terms: our assumption); "conditional" with no terms counts half; a swap is worth the expected gain of taking the better of the two picks. A pick already used is the player it became, valued from the slot until he has played about ' + fx.num((pk.constants || {}).rookie_info_min || 1500, 0) + ' minutes. ' +
    'No rookie-scale salaries: on-field value only, like the players.</div></div>';
  box.innerHTML = h;
  HW.sortable(box);
  QKC.line('#mv-pc', { xType: 'value', series: [{ name: 'Mean by pick', color: QKC.tokens().ink3, width: 0.01, symbols: true, data: (pc.raw || []).map(r => [r[0], r[1]]) },
    { name: 'Curve (80% band)', color: QKC.tokens().model, width: 3, data: xs.map(o => [o, v[o - 1]]), band: pc.lo && pc.hi ? { lo: pc.lo, hi: pc.hi, x: xs } : undefined }],
    xName: 'Overall pick', yName: 'WAR, first four seasons (discounted)', xFmt: x => String(Math.round(x)), yFmt: x => fx.num(x, 1), yMin: 0, legend: true, endLabels: false, label: 'Pick-value curve' });
}

function validationHTML(L, val) {
  const fx = FX();
  if (!val || !val.ok) return '';
  const nm = { kernel: 'Our curve (kernel)', old: 'Five-pick moving average', power: 'Power law', round: 'Round mean', flat: 'One average for every pick' };
  const dev = (val.dev_lodo || {}).mse || {}, wf = (val.dev_walk_forward || {}).mse || {};
  let h = '<div class="card"><div class="card-header">Validation <span class="card-sub">';
  if (val.test) {
    const t = val.test, m = t.metrics || {};
    const dk = t.mse_kernel_minus_round || {}, ci = dk.ci95 || [0, 0], top = (t.buckets || [])[0];
    h += 'Walk-forward on held-out drafts ' + fx.esc(t.drafts[0]) + '–' + fx.esc(t.drafts[1]) + ' (' + fx.num(t.n, 0) + ' picks): each draft predicted only from drafts at least ' + fx.num(t.train_lag, 0) + ' years older, so all their seasons had been played. The curve family was chosen on the development drafts ' + fx.esc((val.dev_lodo || {}).drafts[0]) + '–' + fx.esc((val.dev_lodo || {}).drafts[1]) + ', before the test. ' +
      'Single picks are very noisy: the curve cuts the squared error of one average for every pick by ' + fx.num(100 * ((m.kernel || {}).skill_v_flat || 0), 0) + '% and ranks picks better than a round mean (rank correlation ' + fx.num((m.kernel || {}).spearman, 2) + ' v ' + fx.num((m.round || {}).spearman, 2) + '); its squared error differs from the round mean\'s by ' + fx.signed(dk.diff, 2) + ' (95% interval ' + fx.signed(ci[0], 2) + ' to ' + fx.signed(ci[1], 2) + (ci[0] <= 0 && ci[1] >= 0 ? ': not a reliable difference' : '') + ').' + (top && top.realised < top.kernel ? ' Picks ' + top.slots[0] + '–' + top.slots[1] + ' of the test drafts produced less than the earlier drafts predicted (' + fx.num(top.realised, 1) + ' v ' + fx.num(top.kernel, 1) + ').' : '') + '</span></div>';
    h += HW.tableHTML([{ label: 'Method' }, { label: 'Dev MSE', align: 'right', title: 'Leave one development draft out' }, { label: 'Dev walk-forward', align: 'right' }, { label: 'Test MSE', align: 'right' }, { label: 'Test MAE', align: 'right' }, { label: 'Rank corr.', align: 'right' }, { label: 'Bias', align: 'right', title: 'Predicted minus realised' }],
      Object.keys(nm).filter(k => m[k]).map(k => [{ v: nm[k], html: k === 'kernel' ? '<strong>' + nm[k] + '</strong>' : nm[k] }, { v: dev[k], html: fx.num(dev[k], 2) }, { v: wf[k], html: fx.num(wf[k], 2) }, { v: m[k].mse, html: fx.num(m[k].mse, 2) }, { v: m[k].mae, html: fx.num(m[k].mae, 2) }, { v: m[k].spearman, html: fx.num(m[k].spearman, 2) }, { v: m[k].bias, html: fx.signed(m[k].bias, 2) }]), { compact: true });
    h += HW.tableHTML([{ label: 'Slots' }, { label: 'Picks', align: 'right' }, { label: 'Realised', align: 'right' }, { label: 'Our curve', align: 'right' }, { label: 'Round mean', align: 'right' }],
      (t.buckets || []).map(b => [b.slots[0] + '–' + b.slots[1], b.n, { v: b.realised, html: fx.num(b.realised, 2) }, { v: b.kernel, html: fx.num(b.kernel, 2) }, { v: b.round, html: fx.num(b.round, 2) }]), { compact: true });
  } else {
    h += 'Only ' + fx.esc((val.dev_lodo || {}).drafts ? (val.dev_lodo.drafts[1] - val.dev_lodo.drafts[0] + 1) : '') + ' drafts have four complete seasons, too few for a sealed test: leave-one-draft-out squared error only.</span></div>';
    h += HW.tableHTML([{ label: 'Method' }, { label: 'Leave-one-draft-out MSE', align: 'right' }], Object.keys(nm).filter(k => fx.isNum(dev[k])).map(k => [nm[k], { v: dev[k], html: fx.num(dev[k], 2) }]), { compact: true });
  }
  return h + '</div>';
}

function teamPicksHTML(L, pk) {
  const fx = FX();
  const teams = Object.keys((pk || {}).teams || {});
  if (!teams.length) return '';
  const years = pk.teams[teams[0]].years || [];
  const rows = teams.map(t => { const x = pk.teams[t]; return [{ v: fx.teamName(L, t), html: fx.teamLink(L, t) }].concat(years.slice(0, 4).map((y, i) => { const r = x.r1[i]; return { v: r[0], html: fx.num(r[0], 1) + ' <span class="muted-inline">' + r[1] + '–' + r[2] + '</span>' }; }))
    .concat([{ v: (x.r2[0] || [])[0], html: fx.num((x.r2[0] || [])[0], 1) }]); });
  return '<div class="card"><div class="card-header">Each team\'s own picks <span class="card-sub">Today\'s value of each team\'s own first-round pick (likely slot, 25th–75th percentile) in the next drafts, and its next second-round pick, discounted to this season. ESPN does not say who owns which pick today, so these are the original owners\' picks: the trade simulator values any of them.</span></div>' +
    HW.tableHTML([{ label: 'Team' }].concat(years.slice(0, 4).map(y => ({ label: y + ' 1st', align: 'right' }))).concat([{ label: years[0] + ' 2nd', align: 'right' }]), rows, { compact: true, sticky: true }) + '</div>';
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
