/* The Quant Gridiron — Transactions (#/transactions?tab=trades|table|feed|team&team=&type=), in Value & Moves.
 * The last twelve months of club transactions, parsed: every trade rated for each side (points above
 * replacement and wins, at the time and now), the best and worst deals, winners and losers by club as a
 * chart and a leaderboard, the feed, and each club's ledger (Design System 2.0: stat tiles, leaderboards with team marks). Reads <S>/transactions.json and <S>/ledgers/<abbr>.json. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const MARK = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
const TABS = [['trades', 'Trade ratings'], ['table', 'Winners & losers'], ['feed', 'Feed'], ['team', 'Team ledger']];
const TYPES = [['', 'All moves'], ['trade', 'Trades'], ['signing', 'Signings'], ['release', 'Releases'], ['claim', 'Waiver claims'], ['extension', 'Extensions']];
const GC = { A: '#2fb37b', B: '#7ee787', C: '#7d8590', D: '#e8833a', F: '#e05d5d' };
const ST = { tab: 'trades', team: '', type: '', q: '' };
let D = null, S = null;

function gradeChip(g) { return g ? '<span class="gi-tier" style="--tierc:' + (GC[g] || '#7d8590') + '">' + esc(g) + '</span>' : '<span class="qk-muted">—</span>'; }
function asset(a) {
  if (a.kind === 'pick') return '<li><span>' + (a.conditional ? 'conditional ' : '') + a.year + ' ' + (a.overall ? 'pick ' + a.overall : GI.ordinal(a.round) + ' round') + '</span><span class="gi-num qk-muted">' + GI.num(a.at, 1) + '</span></li>';
  if (a.kind === 'considerations') return '<li class="qk-muted">draft considerations</li>';
  return '<li><span><span class="gi-tag">' + esc(GI.posLabel(a.pos || '')) + '</span> ' + (a.pid ? GI.playerLink(a.pid, a.name) : esc(a.name || '')) + (a.valued && a.on_roster === false ? ' <span class="qk-badge">gone</span>' : '') + '</span>' +
    '<span class="gi-num qk-muted" title="' + (a.valued ? 'value at the time → now (realised ' + GI.num(a.real, 1) + ' in ' + (a.games || 0) + ' games)' : '') + '">' + esc(a.valued ? GI.num(a.at, 1) + ' → ' + GI.num(a.now, 1) : (a.why || 'not valued')) + '</span></li>';
}
function tradeCard(t) {
  const w = t.winner === 'even' ? 'even so far' : (t.winner ? GI.teamName(t.winner) + ' ahead' : '');
  return '<section class="qk-card"><div class="qk-card-head"><div class="gi-card-titles"><h3 class="qk-card-title">' + esc(GI.fmtDate(t.date)) + '</h3><div class="qk-card-sub">' + (t.teams || []).map(x => GI.teamChip(x)).join(' ') + (w ? ' · ' + esc(w) : '') + '</div></div></div><div class="qk-card-body">' +
    '<div class="gi-trade-cols">' + (t.sides || []).map(sd => '<div class="gi-trade-side" style="--tc:' + esc(GI.tc(sd.team)) + ';padding-top:8px"><div class="gi-toolbar">' + GI.teamLink(sd.team) + gradeChip(sd.grade_now) + '<span class="qk-sub">now · ' + esc(sd.grade_at || '—') + ' at the time</span></div>' +
      '<ul class="gi-moves">' + ((sd.gets || []).length ? sd.gets.map(asset).join('') : '<li class="qk-muted">nothing listed</li>') + '</ul>' +
      '<p class="gi-cap">Net ' + GI.signed(sd.wins_now, 2) + ' wins now · ' + GI.signed(sd.wins_at, 2) + ' at the time · received ' + GI.num(sd.in_now, 1) + ' pts</p></div>').join('') + '</div>' +
    ((t.notes || []).length ? '<details><summary class="qk-sub">Club notes</summary>' + t.notes.map(n => '<p class="gi-cap">' + esc(n) + '</p>').join('') + '</details>' : '') + '</div></section>';
}
function feedTable(list, withTeam) {
  if (!list.length) return GI.muted('Nothing in the window.');
  return GI.tableHTML([{ label: 'Date' }].concat(withTeam ? [{ label: 'Team' }] : []).concat([{ label: 'Type' }, { label: 'Move', sortable: false }, { label: 'Model value', sortable: false }]),
    list.map(f => [{ html: esc(GI.fmtDate(f[0], { weekday: false })), v: f[0] }].concat(withTeam ? [{ html: GI.teamChip(f[1]), v: f[1] }] : []).concat([{ html: GI.pill(GI.titleCase(f[2]), f[2] === 'trade' ? '#c95ac9' : /release|reserve/.test(f[2]) ? GI.BAD : f[2] === 'signing' ? GI.GOOD : 'var(--ink-3)'), v: f[2] },
      { html: '<span class="gi-play-desc">' + esc(f[3]) + '</span>' }, { html: (f[4] || []).filter(p => p[0] && isNum(p[3]) && p[3] > 0).map(p => GI.playerLink(p[0], p[1]) + ' <span class="gi-num qk-muted">' + GI.num(p[3], 0) + '</span>').join(', ') }])), { maxHeight: 640 });
}

GI.route('transactions', function (el, params) {
  S = GI.currentSeason();
  const qy = params.query || {};
  if (qy.tab && TABS.some(x => x[0] === qy.tab)) ST.tab = qy.tab;
  if (qy.team) { ST.team = String(qy.team).toUpperCase(); if (!qy.tab) ST.tab = 'team'; }
  if (qy.type !== undefined) ST.type = String(qy.type);
  return GI.load(GI.ypath('transactions.json', S)).then(d => {
    if (!el.isConnected) return;
    D = d;
    const head = GI.pageHead('Value & Moves', 'Transactions and trade ratings', GI.ok(d) ? 'The last twelve months · ' + esc((d.window || []).join(' to ')) : '') + GI.sectionNav('value', 'transactions');
    if (!GI.ok(d) || !d.trades) { el.innerHTML = head + GI.notBuilt('The transactions', d); return; }
    const TT = (d.table || []).slice().sort((a, b) => (b.wins_now || 0) - (a.wins_now || 0));
    const tiles = GI.kpis([GI.kpi('Trades', GI.int((d.trades || []).length), 'in the window, each rated for every side'),
      TT[0] ? GI.kpi('Biggest winner', esc(GI.teamAbbr(TT[0].team)) + ' ' + GI.signed(TT[0].wins_now, 1), 'net wins from its trades, valued now', { signal: true, href: '#/transactions?tab=team&team=' + TT[0].team }) : '',
      TT.length ? GI.kpi('Biggest loser', esc(GI.teamAbbr(TT[TT.length - 1].team)) + ' ' + GI.signed(TT[TT.length - 1].wins_now, 1), 'net wins from its trades, valued now', { href: '#/transactions?tab=team&team=' + TT[TT.length - 1].team }) : '',
      GI.kpi('Moves logged', GI.int(d.n_feed), 'signings, releases, claims and trades')]);
    el.innerHTML = head + tiles + GI.note('<p>' + esc((d.notes || {}).method || '') + ' ' + esc((d.notes || {}).source || '') + ' Defensive values are a floor (box-score credit only); offensive linemen are not valued.</p>') +
      '<div class="gi-toolbar">' + GI.seg('gx-tab', TABS, ST.tab, 'View') + '</div><div id="gx-body" class="gi-page"></div>';
    const draw = () => {
      try { history.replaceState(null, '', '#/transactions' + GI.qs({ tab: ST.tab, team: ST.team, type: ST.type })); } catch (e) { /* ok */ }
      const body = document.getElementById('gx-body');
      const teams = (D.table || []).map(r => r.team).sort();
      const teamSel = all => GI.field('Team', GI.select('gx-team', [['', all]].concat(teams.map(t => [t, GI.teamName(t)])), ST.team, 'Team'));
      if (ST.tab === 'trades') {
        const list = (D.trades || []).filter(t => !ST.team || (t.teams || []).indexOf(ST.team) >= 0);
        const bw = (arr, title) => GI.card(title, 'Net wins now', '<ol class="gi-ldl">' + (arr || []).slice(0, 8).map(b => '<li>' + GI.mark(b[1]) + '<span class="gi-link">' + esc(GI.teamAbbr(b[1])) + ' from ' + esc(b[2] || '?') + ' <span class="qk-muted">' + esc(GI.fmtDate(b[0], { weekday: false })) + '</span></span><b class="gi-num">' + GI.signed(b[3], 2) + '</b> ' + gradeChip(b[4]) + '</li>').join('') + '</ol>', { span: 6 });
        body.innerHTML = GI.grid(bw(D.best, 'Best deals') + bw(D.worst, 'Worst deals')) +
          '<div class="gi-toolbar">' + teamSel('All teams') + '<span class="qk-sub">' + list.length + ' trades · grades on the net in wins: A ≥ +1, B ≥ +0.3, C within 0.3 of even, D ≥ −1, F below</span></div>' + list.map(tradeCard).join('');
      } else if (ST.tab === 'table') {
        const T2 = (D.table || []).slice().sort((a, b) => (b.wins_now || 0) - (a.wins_now || 0));
        body.innerHTML = GI.card('Net wins from trades, now', 'every club\'s trades in the window, valued now', GI.chartBox('gx-chart', Math.max(420, T2.length * 20 + 30), 'Net wins from trades by club')) +
          GI.card('Winners and losers', 'Trades in the window, and the projected value of the players each club signed and released', '<div id="gx-table"></div>', { flush: true });
        QK.leaderboard(document.getElementById('gx-table'), { dense: true, rank: true, maxHeight: 700, rowHref: r => '#/transactions?tab=team&team=' + r.team, sort: { key: 'wins_now', dir: 'desc' },
          rows: T2.map(r => Object.assign({ name: GI.teamShort(r.team), sub: GI.teamInfo(r.team).division || '' }, r)),
          columns: [{ key: 'name', label: 'Club', type: 'entity', sub: 'sub', mark: r => MARK(r.team), href: r => '#/transactions?tab=team&team=' + r.team }, { key: 'trades', label: 'Trades', num: true },
            { key: 'wins_at', label: 'Net wins at the time', num: true, fmt: v => GI.deltaHTML(v, 2) }, { key: 'wins_now', label: 'Net wins now', num: true, fmt: v => '<b>' + GI.deltaHTML(v, 2) + '</b>' },
            { key: 'real', label: 'Realised in', type: 'bar', fmt: v => GI.num(v, 1), tip: 'Points above replacement the players it traded for have produced for it' },
            { key: 'signed', label: 'Signed (value)', num: true, fmt: (v, r) => GI.num(v, 0) + ' <span class="qk-muted">(' + r.n_signed + ')</span>' }, { key: 'lost', label: 'Released (value)', num: true, fmt: (v, r) => GI.num(v, 0) + ' <span class="qk-muted">(' + r.n_lost + ')</span>' }] });
        GI.ch.bar('gx-chart', { cats: T2.map(r => GI.teamName(r.team)), series: [{ name: 'Net wins now', data: T2.map(r => r.wins_now) }], horizontal: true, diverging: true, labels: true, fmt: x => GI.signed(x, 2), hrefs: T2.map(r => '#/transactions?tab=team&team=' + r.team), labelWidth: 150, valName: 'Net wins now', catName: 'Club' });
      } else if (ST.tab === 'feed') {
        const q = GI.fold(ST.q.trim());
        const list = (D.feed || []).filter(f => (!ST.team || f[1] === ST.team) && (!ST.type || f[2] === ST.type) && (!q || GI.fold(f[3]).indexOf(q) >= 0));
        body.innerHTML = GI.card('Feed', list.length + ' shown of ' + GI.int(D.n_feed) + ' moves · practice-squad and reserve moves are in the team ledgers', '<div class="gi-toolbar" style="margin-bottom:12px">' + teamSel('All teams') +
          GI.field('Type', GI.select('gx-type', TYPES, ST.type, 'Type')) + GI.field('Find', '<input id="gx-q" class="qk-input" type="search" placeholder="Name or text">') + '</div><div id="gx-feed">' + feedTable(list.slice(0, 300), true) + '</div>');
      } else {
        if (!ST.team) ST.team = ((D.table || [])[0] || {}).team || 'ARI';
        body.innerHTML = '<div class="gi-toolbar">' + teamSel('Choose') + '</div><div id="gx-ledger">' + QK.skeleton('lines', 4) + '</div>';
        GI.load(GI.ypath('ledgers/' + ST.team + '.json', S)).then(L => {
          const n = document.getElementById('gx-ledger');
          if (!n) return;
          if (!GI.ok(L)) { n.innerHTML = GI.notBuilt('The ledger', L); return; }
          const s = L.summary || {};
          n.innerHTML = GI.kpis([GI.kpi('Trades', GI.int(s.trades)), GI.kpi('Net wins now', GI.signed(s.wins_now, 2), 'at the time ' + GI.signed(s.wins_at, 2), { signal: true }), GI.kpi('Signed', GI.num(s.signed, 0), (s.n_signed || 0) + ' valued players'), GI.kpi('Released', GI.num(s.lost, 0), (s.n_lost || 0) + ' valued players')], 'gi-kpis-4') +
            ((L.trades || []).length ? L.trades.map(tradeCard).join('') : '') + GI.card('Every move', esc(GI.teamName(L.team)), feedTable((L.feed || []).map(f => [f[0], L.team, f[1], f[2], f[3]]), false), { flush: true });
          GI.sortable(n);
        });
      }
      GI.sortable(body);
      const ts = document.getElementById('gx-team');
      if (ts) ts.addEventListener('change', e => { ST.team = e.target.value; draw(); });
      const ty = document.getElementById('gx-type');
      if (ty) ty.addEventListener('change', e => { ST.type = e.target.value; draw(); });
      const qi = document.getElementById('gx-q');
      if (qi) {
        qi.value = ST.q;
        qi.addEventListener('input', e => { ST.q = e.target.value; const q = GI.fold(ST.q.trim()); GI.set('gx-feed', feedTable((D.feed || []).filter(f => (!ST.team || f[1] === ST.team) && (!ST.type || f[2] === ST.type) && (!q || GI.fold(f[3]).indexOf(q) >= 0)).slice(0, 300), true)); GI.sortable(document.getElementById('gx-feed')); });
      }
    };
    GI.wireSeg(el, 'gx-tab', v => { ST.tab = v; draw(); });
    draw();
  });
});

})(window.GI);
