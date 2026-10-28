/* The Quant Hardwood — Standings ▸ History (round 9, 28 Oct 2026): champions as a visual, on the house order.
 *   1. headline numbers: the most titles, the longest wait among today's teams, the best record, the highest peak Elo;
 *   2. the dynasty strip: every title as a team-colour block, one row per club (most titles first), each block the season;
 *   3. the timeline: one block per season in the champion's colour, the runner-up under it;
 *   4. the longest waits (seasons since a title, or none since our data starts) and the best regular seasons;
 *   5. the champions table (season, champion, runner-up, MVP, best record), then the explain strip.
 * Data: <L>/history.json (seasons from 1997 for both leagues: ESPN box scores; there is no earlier free source we use).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;

function historyTab(node, L) {
  return HW.load(HW.lpath('history.json', L)).then(hist => {
    if (!U.alive(node)) return;
    if (!U.ok(hist)) { node.innerHTML = U.empty('No history', 'The champions list is not built yet.'); return; }
    const rows = (hist.seasons || []).filter(r => r.champion).slice().sort((a, b) => a.season - b.season);
    if (!rows.length) { node.innerHTML = U.empty('No champions yet', 'The champions list fills in as seasons finish.'); return; }
    const tn = id => (hist.team_names || {})[id] || HW.teamName(L, id);
    const ab = id => HW.teamAbbr(L, id) || String(tn(id)).slice(0, 3).toUpperCase();
    const col = id => HW.teamColourRaw(L, id) || QK.cssVar('--slate');
    const first = hist.first_season || rows[0].season, last = rows[rows.length - 1].season;
    const yl = s => HW.seasonLabel(L, s);
    const yshort = s => (L === 'nba' ? '’' + String(s).slice(2) : String(s));
    const titles = {};
    rows.forEach(r => { (titles[r.champion] || (titles[r.champion] = [])).push(r.season); });
    const clubs = Object.keys(titles).sort((a, b) => titles[b].length - titles[a].length || Math.max.apply(null, titles[b]) - Math.max.apply(null, titles[a]));
    /* waits: today's teams (index.json) by seasons since their last title, or since our data starts */
    const now = Object.keys((HW.NAMES[L] || {}).teams || {}).filter(t => (HW.NAMES[L].teams[t] || {}).abbr);
    const waits = now.map(t => { const ts = titles[t] || []; const lastT = ts.length ? Math.max.apply(null, ts) : null; return { t: t, last: lastT, n: lastT ? last - lastT : last - first + 1, never: !lastT }; })
      .sort((a, b) => b.n - a.n || (a.never === b.never ? 0 : a.never ? -1 : 1));
    const recs = (hist.seasons || []).filter(r => r.best_record && isNum(r.best_record[1])).map(r => ({ s: r.season, t: String(r.best_record[0]), w: r.best_record[1], l: r.best_record[2], pct: r.best_record[1] / Math.max(1, r.best_record[1] + r.best_record[2]), champ: String(r.champion || '') === String(r.best_record[0]) }))
      .sort((a, b) => b.pct - a.pct).slice(0, 10);
    const elo = (hist.elo_all_time || []).slice(0, 10);
    const top = clubs[0];
    const kp = [
      { label: 'Most titles since ' + yl(first), value: ab(top) + ' ' + titles[top].length, signal: true, href: HW.teamHref(L, top), sub: tn(top) + ': ' + titles[top].map(yshort).join(', ') },
      waits[0] ? (function () {
        const tied = waits.filter(w => w.n === waits[0].n && w.never === waits[0].never);
        return tied.length > 1 ? { label: 'Never won it here', value: tied.length + ' teams', sub: 'no title in ' + waits[0].n + ' seasons of our data: ' + tied.slice(0, 6).map(w => ab(w.t)).join(', ') + (tied.length > 6 ? '…' : '') }
          : { label: 'Longest wait', value: ab(waits[0].t) + ' ' + waits[0].n, href: HW.teamHref(L, waits[0].t), sub: waits[0].never ? 'seasons with no title since ' + yl(first) : 'seasons since ' + yl(waits[0].last) };
      })() : null,
      recs[0] ? { label: 'Best regular season', value: ab(recs[0].t) + ' ' + recs[0].w + '-' + recs[0].l, sub: yl(recs[0].s) + (recs[0].champ ? ', and the title' : ', no title') } : null,
      elo[0] ? { label: 'Highest peak rating', value: ab(elo[0].team) + ' ' + Math.round(elo[0].peak), sub: 'Elo, ' + yl(elo[0].season) } : null
    ];
    let h = '<div class="hw-kpis">' + QK.stats(kp) + '</div>';
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Dynasties', title: 'Every title, club by club', sub: 'One block per championship in the club’s colour, since ' + yl(first) + ' (our data starts there). ' + clubs.length + ' different champions in ' + rows.length + ' seasons.' }) +
      '<div class="qk-card"><div class="qk-card-body"><div class="hw-dyn">' + clubs.map(t => '<a class="hw-dyn-row" href="' + esc(HW.teamHref(L, t)) + '"><span class="nm">' + esc(tn(t)) + '</span><span class="n">' + titles[t].length + '</span><span class="bl">' +
        titles[t].map(s => { const b = QK.color.block(col(t)); return '<i style="background:' + esc(b.bg) + ';border-bottom-color:' + esc(b.edge || b.bg) + '" title="' + esc(yl(s)) + '">' + esc(yshort(s)) + '</i>'; }).join('') + '</span></a>').join('') + '</div></div></div></section>';
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Timeline', title: 'Season by season', sub: 'The champion of every season in its colour; the runner-up underneath. Runs of one colour are the dynasties.' }) +
      '<div class="qk-card"><div class="qk-card-body"><div class="hw-tl" role="img" aria-label="Champions by season">' + rows.map(r => { const b = QK.color.block(col(r.champion)); return '<a class="hw-tl-c" href="' + esc('#/' + L + (Number(r.season) !== Number(HW.currentSeason(L)) ? '?s=' + r.season : '')) + '" title="' + esc(yl(r.season) + ': ' + tn(r.champion) + (r.runner_up ? ' beat ' + tn(r.runner_up) : '')) + '">' +
        '<b style="background:' + esc(b.bg) + ';border-bottom-color:' + esc(b.edge || b.bg) + '">' + esc(ab(r.champion)) + '</b><span>' + esc(yshort(r.season)) + '</span><small>' + esc(r.runner_up ? ab(r.runner_up) : '') + '</small></a>'; }).join('') + '</div></div></div></section>';
    h += '<div class="qk-grid hw-sec">' + U.card2('The longest waits', 'Today’s teams by seasons since their last title (in our data from ' + yl(first) + ')', '<div id="hs-wait"></div>', { cls: 'qk-span-6', flush: true }) +
      U.card2('The best regular seasons', 'The league’s best record each season, top ten by win %, and whether it ended in the title', '<div id="hs-best"></div>', { cls: 'qk-span-6', flush: true }) + '</div>';
    h += '<section class="qk-section">' + U.card2('Champions', 'Season by season; tap a season for its recap', '<div id="hs-t"></div>', { flush: true }) + '</section>';
    h += QK.explain('Our history starts in ' + yl(first) + ', the first season with ESPN box scores; there is no earlier free source we use, so a club whose titles came before then shows none here. A season links to its recap: the bracket, the awards and how our numbers called it.', { title: 'Where this comes from.' });
    node.innerHTML = h;
    QK.leaderboard(document.getElementById('hs-wait'), { dense: true, rank: true, rows: waits.slice(0, 10).map(w => ({ team: w.t, nm: tn(w.t), n: w.n, lastS: w.last ? yl(w.last) : 'none since ' + yl(first) })), rowHref: r => HW.teamHref(L, r.team), columns: [
      { key: 'nm', label: 'Team', type: 'entity', mark: r => U.team(L, r.team), href: r => HW.teamHref(L, r.team) }, { key: 'lastS', label: 'Last title', sort: false }, { key: 'n', label: 'Seasons waiting', num: true }] });
    QK.leaderboard(document.getElementById('hs-best'), { dense: true, rank: true, rows: recs.map(r => ({ team: r.t, nm: tn(r.t), s: yl(r.s), rec: r.w + '-' + r.l, pct: r.pct, champ: r.champ })), columns: [
      { key: 'nm', label: 'Team', type: 'entity', mark: r => U.team(L, r.team), href: r => HW.teamHref(L, r.team) }, { key: 's', label: 'Season', sort: false }, { key: 'rec', label: 'W-L', num: true, sort: false },
      { key: 'pct', label: 'Win %', num: true, fmt: v => HW.fmtVal(v, '3') }, { key: 'champ', label: 'Title?', sort: false, fmt: v => (v ? QK.tag('Won it', 'signal') : '<span class="hw-quiet">no</span>') }] });
    QK.table(document.getElementById('hs-t'), { dense: true, maxHeight: 560, rows: rows.slice().reverse().map(r => Object.assign({}, r, { bw: r.best_record ? r.best_record[1] : null })), columns: [
      { key: 'season', label: 'Season', num: true, fmt: v => '<a class="hw-link" href="' + esc('#/' + L + (Number(v) !== Number(HW.currentSeason(L)) ? '?s=' + v : '')) + '">' + esc(yl(v)) + '</a>' },
      { key: 'champion', label: 'Champion', fmt: v => (v ? U.teamEnt(L, v, { name: tn(v) }) : '—') },
      { key: 'runner_up', label: 'Runner-up', fmt: v => (v ? esc(tn(v)) : '—') },
      { key: 'mvp', label: 'MVP', fmt: v => esc(v ? (HW.NAMES[L].players[String(v)] ? HW.playerName(L, v) : v) : '—') },
      { key: 'bw', label: 'Best record', num: true, fmt: (v, r) => (r.best_record ? esc(ab(r.best_record[0])) + ' ' + HW.record(r.best_record[1], r.best_record[2]) : '—') }] });
  });
}

HW.historyTab = historyTab;
})(window.HW);
