/* The Quant Bullpen — team history (#/history, Standings > History; round 9, 28 Oct 2026).
 *
 * Every World Series winner since 1903 as a strip of team-colour blocks, decade by decade (the dynasties read at a glance);
 * titles and pennants by club; the longest waits for a title; the best and worst team-seasons since 1901 and the best run
 * differentials; franchise records; every champion by year with the beaten finalist.
 * Data: data/mlb/team_history.json (oddsmarkets/baseball/analytics/team_history.py: the Lahman Baseball Database, CC BY-SA
 * 3.0, for 1901 to its last season, then our own finished seasons). Blocks carry the club's abbreviation of that season
 * (BRO, NYG, PHA) in the colour of the franchise today. The all-time player careers are the Scouting Room's
 * "All-time" view (#/mlb/scout?view=alltime). Older-browser rule: no optional chaining, no nullish coalescing. */
(function (BP) {
'use strict';

const esc = s => BP.esc(s);
const isNum = v => typeof v === 'number' && isFinite(v);
const L = 'mlb';

function blockOf(tid) {
  const hex = tid ? BP.teamColourRaw(tid) : '';
  return QK.color.block(hex);
}
function abbrOf(fid, tid) { return tid ? BP.teamAbbr(tid) : fid; }
function teamA(tid, name) { return tid ? '<a href="' + esc(BP.teamHref(tid, L)) + '">' + esc(name || BP.teamName(tid)) + '</a>' : esc(name || ''); }
function rec(w, l) { return w + '–' + l; }
function pct3(p) { return isNum(p) ? String(p.toFixed(3)).replace(/^0/, '') : '—'; }
function fmtV(r) {
  if (r.fmt === 'pct3') return pct3(r.value);
  if (r.fmt === 'num2') return r.value.toFixed(2);
  if (r.fmt === 'signed2') return (r.value >= 0 ? '+' : '−') + Math.abs(r.value).toFixed(2);
  return QK.fmt.num(r.value);
}

/* the dynasty strip: one row per decade, one block per season (the champion's colour and abbreviation; blank: no Series) */
function strip(d) {
  const by = {};
  (d.champions || []).forEach(c => { by[c.season] = c; });
  const first = 1900, last = d.last;
  let h = '<div class="bph-strip" role="img" aria-label="World Series winners by season, ' + (d.champions || []).length + ' champions">';
  for (let dec = first; dec <= last; dec += 10) {
    h += '<div class="bph-dec"><span class="bph-dl">' + dec + 's</span><div class="bph-yrs">';
    for (let y = dec; y < dec + 10; y++) {
      const c = by[y];
      if (y < 1903 || y > last) { h += '<span class="bph-y off" aria-hidden="true"></span>'; continue; }
      if (!c) { h += '<span class="bph-y none" title="' + y + ': no World Series"><small>' + String(y).slice(2) + '</small>—</span>'; continue; }
      const b = blockOf(c.tid);
      const tip = y + ': ' + c.name + ' (' + rec(c.w, c.l) + ')' + (c.opp ? ', beat the ' + c.opp.name : '');
      h += '<a class="bph-y" href="' + esc(BP.teamHref(c.tid, L)) + '" title="' + esc(tip) + '" style="background:' + b.bg + (b.edge ? ';box-shadow:inset 0 -4px 0 ' + b.edge : '') + '">' +
        '<small>' + String(y).slice(2) + '</small>' + esc(c.abbr || abbrOf(c.fid, c.tid)) + '</a>';
    }
    h += '</div></div>';
  }
  return h + '</div>';
}
/* titles and pennants by club: bars in the club's colour */
function titleBars(d) {
  const fr = d.franchises || {};
  const ids = Object.keys(fr).filter(f => fr[f].titles > 0 || fr[f].pennants > 0).sort((a, b) => fr[b].titles - fr[a].titles || fr[b].pennants - fr[a].pennants);
  const mx = Math.max.apply(null, ids.map(f => fr[f].pennants).concat([1]));
  return '<div class="bph-bars">' + ids.map(f => {
    const x = fr[f], b = blockOf(x.tid);
    return '<a class="bph-bar" href="' + esc(x.tid ? BP.teamHref(x.tid, L) : '#/history') + '">' + (x.tid ? QK.teamMark(BP.ui.team(x.tid, L), 'sm') : '') +
      '<span class="bph-nm">' + esc(x.tid ? BP.teamName(x.tid) : x.name) + '</span><span class="bph-tr" role="img" aria-label="' + esc(x.name + ': ' + x.titles + ' titles, ' + x.pennants + ' pennants') + '">' +
      '<i class="p" style="width:' + (100 * x.pennants / mx).toFixed(1) + '%"></i><i class="t" style="width:' + (100 * x.titles / mx).toFixed(1) + '%;background:' + b.bg + '"></i></span>' +
      '<b class="num">' + x.titles + '</b><span class="bph-pn num">' + x.pennants + '</span></a>';
  }).join('') + '</div>';
}

function render(el) {
  el.innerHTML = QK.sectionHead({ kicker: 'History · MLB', title: 'Every champion since 1903', sub: 'The World Series winners decade by decade, the clubs with the most titles, the longest waits, and the best and worst teams of the modern era (1901 on).' }) +
    '<div id="bph-body">' + QK.skeleton('card', 3) + '</div>';
  return BP.load('mlb/team_history.json').then(d => {
    const body = document.getElementById('bph-body');
    if (!body || !el.isConnected) return;
    if (!d || d.ok === false || !(d.champions || []).length) { body.innerHTML = QK.empty('Not built yet', 'The club history arrives with the next build.'); return; }
    const fr = d.franchises || {};
    const top = Object.keys(fr).sort((a, b) => fr[b].titles - fr[a].titles)[0];
    const lastC = d.champions[d.champions.length - 1];
    const repeat = (() => { let best = { n: 0 }; let run = null; d.champions.forEach(c => { if (run && run.fid === c.fid && c.season === run.end + 1) { run.n++; run.end = c.season; } else run = { fid: c.fid, tid: c.tid, name: c.name, n: 1, start: c.season, end: c.season }; if (run.n > best.n) best = Object.assign({}, run); }); return best; })();
    const dr = (d.droughts || [])[0];
    const tiles = [
      { label: 'Most titles', value: abbrOf(top, fr[top].tid) + ' ' + fr[top].titles, signal: true, sub: fr[top].name + ', ' + fr[top].pennants + ' pennants', href: fr[top].tid ? BP.teamHref(fr[top].tid, L) : null },
      { label: 'Latest champion', value: abbrOf(lastC.fid, lastC.tid) + ' ' + lastC.season, sub: lastC.name + ' (' + rec(lastC.w, lastC.l) + ')' + (lastC.opp ? ', beat the ' + lastC.opp.name : ''), href: lastC.tid ? BP.teamHref(lastC.tid, L) : null },
      repeat.n > 1 ? { label: 'Longest run of titles', value: abbrOf(repeat.fid, repeat.tid) + ' ' + repeat.n + ' in a row', sub: repeat.name + ', ' + repeat.start + '–' + repeat.end } : null,
      dr ? { label: 'Longest wait', value: abbrOf(dr.fid, dr.tid) + ' ' + dr.years + ' yrs', sub: dr.last_title ? dr.name + ': last won in ' + dr.last_title : dr.name + ': never won, since ' + dr.first, href: dr.tid ? BP.teamHref(dr.tid, L) : null } : null
    ].filter(Boolean);

    body.innerHTML = '<div class="bp-kpis">' + QK.stats(tiles) + '</div>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Dynasties', title: 'The champions, decade by decade', sub: 'Each block is a World Series winner in its own colour. Runs of one colour are the dynasties: the Yankees of the late 1930s, early 1950s and late 1990s, the Athletics of the early 1970s. No Series in 1904 or 1994.' }) +
      '<div class="qk-card"><div class="qk-card-body">' + strip(d) + '</div></div></section>' +
      '<section class="qk-section"><div class="qk-g75"><div>' + QK.sectionHead({ kicker: 'Titles', title: 'Who has won the most', sub: 'World Series titles (the block) and pennants (the grey bar behind it) by club, 1903 on; a club keeps its titles from earlier cities and names.' }) +
      '<div class="qk-card"><div class="qk-card-body"><div class="bph-key"><span><i class="t"></i>World Series titles</span><span><i class="p"></i>Pennants</span></div>' + titleBars(d) + '</div></div></div><div>' +
      QK.sectionHead({ kicker: 'The wait', title: 'Longest waits for a title', sub: 'Seasons since the last World Series win (since joining, for a club that has never won), the current 30 clubs.' }) +
      '<div class="qk-card"><div class="qk-card-body" id="bph-dr"></div></div></div></div></section>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'The best teams', title: 'The best team-seasons since 1901', sub: 'By winning percentage, seasons of 100 games or more; the run differential a game says how dominant they really were. A volt bar marks the champions.' }) +
      '<div class="qk-grid"><div class="qk-span-7">' + BP.ui.card2('Best records', 'winning percentage', '<div id="bph-best"></div>', { flush: true }) + '</div><div class="qk-span-5">' +
      BP.ui.card2('Most dominant', 'run differential a game', '<div id="bph-rd"></div>', { flush: true }) + '</div></div></section>' +
      '<section class="qk-section"><div class="qk-grid"><div class="qk-span-5">' + QK.sectionHead({ kicker: 'Records', title: 'Club records', sub: 'Single-season and all-time marks since 1901.' }) + '<div id="bph-rec"></div></div><div class="qk-span-7">' +
      QK.sectionHead({ kicker: 'The worst teams', title: 'The worst team-seasons', sub: 'By winning percentage, seasons of 100 games or more.' }) + BP.ui.card2('Worst records', '', '<div id="bph-worst"></div>', { flush: true }) + '</div></div></section>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Every Series', title: 'World Series winners by year', sub: 'The champion, its regular-season record and the club it beat.' }) +
      BP.ui.card2('Champions', d.champions.length + ' World Series', '<div id="bph-ch"></div>', { flush: true }) + '</section>' +
      '<p class="bp-note">' + esc((d.sources || {}).lahman || '') + ' ' + esc((d.sources || {}).ours || '') + '</p>';

    const mark = t => (t ? BP.ui.team(t, L) : null);
    const tsRows = list => list.map(r => ({ name: r.name, sub: r.season + ' · ' + r.lg + (r.champion ? ' · champions' : r.pennant ? ' · pennant' : ''), team: r.tid, href: r.tid ? BP.teamHref(r.tid, L) : null,
      rec: rec(r.w, r.l), pct: r.pct, rdg: r.rdg, season: r.season, champ: r.champion }));
    const cols = [{ key: 'name', label: 'Club', type: 'entity', sub: 'sub', mark: o => mark(o.team), href: o => o.href }, { key: 'rec', label: 'W–L', sort: false },
      { key: 'pct', label: 'Pct', num: true, fmt: v => pct3(v) }, { key: 'rdg', label: 'Run diff a game', type: 'bar', fmt: v => (isNum(v) ? (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(2) : '—') }];
    QK.leaderboard(document.getElementById('bph-best'), { dense: true, rank: true, rowClass: o => (o.champ ? 'bph-champ' : ''), columns: cols, rows: tsRows(d.best || []) });
    QK.leaderboard(document.getElementById('bph-rd'), { dense: true, rank: true, rowClass: o => (o.champ ? 'bph-champ' : ''), columns: [cols[0], cols[1], cols[3]], rows: tsRows(d.best_rd || []) });
    const rdNum = { key: 'rdg', label: 'Run diff a game', num: true, fmt: v => (isNum(v) ? (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(2) : '—') };
    QK.leaderboard(document.getElementById('bph-worst'), { dense: true, rank: true, columns: [cols[0], cols[1], cols[2], rdNum], rows: tsRows(d.worst || []) });
    document.getElementById('bph-dr').innerHTML = '<ol class="bph-dr">' + (d.droughts || []).slice(0, 10).map(x => {
      const b = blockOf(x.tid);
      return '<li><span class="bph-dry num" style="background:' + b.bg + '">' + x.years + '</span><span>' + teamA(x.tid, x.tid ? BP.teamName(x.tid) : x.name) + '<small>' + (x.last_title ? 'last title ' + x.last_title : 'never won · since ' + x.first) + '</small></span></li>';
    }).join('') + '</ol>';
    document.getElementById('bph-rec').innerHTML = '<div class="bph-recs">' + (d.records || []).map(r => '<div class="bph-rc"><span class="qk-kicker">' + esc(r.label) + '</span><b class="num">' + esc(fmtV(r)) + '</b><span>' + teamA(r.tid, r.name) +
      (r.season ? ' · ' + (r.key === 'drought' ? 'last title ' : '') + r.season : '') + ((r.also || []).length ? ' <small>(tied: ' + r.also.map(a => esc(a.name) + ' ' + a.season).join(', ') + ')</small>' : '') + '</span></div>').join('') + '</div>';
    QK.leaderboard(document.getElementById('bph-ch'), { dense: true, maxHeight: 640, sort: { key: 'season', dir: 'desc' }, columns: [
      { key: 'season', label: 'Season', num: true, fmt: v => String(v) }, { key: 'name', label: 'Champion', type: 'entity', sub: 'sub', mark: o => mark(o.tid), href: o => o.href },
      { key: 'opp', label: 'Beat', fmt: (v, o) => (o.oppTid ? teamA(o.oppTid, v) : esc(v || '—')) + (o.oppRec ? ' <span class="qk-muted">' + o.oppRec + '</span>' : '') }],
    rows: d.champions.map(c => ({ season: c.season, name: c.name, sub: rec(c.w, c.l), tid: c.tid, href: c.tid ? BP.teamHref(c.tid, L) : null, opp: c.opp ? c.opp.name : '', oppTid: c.opp ? c.opp.tid : null, oppRec: c.opp ? rec(c.opp.w, c.opp.l) : '' })) });
    BP.setMeta(d.first + '–' + d.last + ' · Lahman Baseball Database (CC BY-SA 3.0) to ' + d.lahman_last);
  });
}

BP.route('history', render);
})(window.BP);
