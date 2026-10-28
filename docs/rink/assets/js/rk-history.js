/* The Quant Rink — Standings › History (round 9, 28 Oct 2026): every Stanley Cup champion since 1917-18 as a picture,
 * not a 108-row table.
 *   1. the headline numbers: the last champion, the most Cups, the longest wait among clubs that have won, repeat
 *      champions;
 *   2. the dynasty strip: one block a season in the champion's colour, ten seasons a row, the dynasties (two or more in a
 *      row) named beside it;
 *   3. titles by franchise (renamed and relocated clubs folded into today's club) and the droughts: seasons since each
 *      current club's last Cup, with the clubs still waiting for a first;
 *   4. every champion as a table, folded (search and decade inside), team links for every season with a franchise id
 *      (the season's own team page from 2009-10, when the data starts; the club's page before);
 *   5. the league by era and the season leaders (history.js, RK.historyParts).
 * Reads data/history.json. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);
const WORD = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];

/* a champion's franchise abbreviation today (null for clubs outside today's 32: the first Ottawa Senators, the Maroons,
   Victoria and Seattle of the old western leagues) */
function abbrOf(r, H) {
  if (r.champion && /^[A-Z]{2,3}$/.test(String(r.champion))) return RK.canonTeam(r.champion);
  const f = H.franchiseOf(r);
  if (!f) return null;
  const hit = Object.keys(RK.NHL_TEAMS).filter(t => RK.HISTORIC.indexOf(t) < 0).find(t => RK.NHL_TEAMS[t][0] === f || RK.NHL_TEAMS[t][0].replace('é', 'e') === f.replace('é', 'e'));
  return hit || null;
}

RK.historyTab = function (node) {
  const H = RK.historyParts;
  node.innerHTML = QK.skeleton('lines', 8);
  if (!H) { node.innerHTML = QK.empty('Not available', 'The history module did not load.'); return null; }
  return RK.load('history.json').then(d => {
    if (!U.alive(node)) return;
    if (!RK.ok(d)) { node.innerHTML = QK.empty('Not built yet', RK.reason(d)); return; }
    const all = H.championsOf(d).slice().sort((a, b) => a.S - b.S);
    const rows = all.map(r => Object.assign({}, r, { y: H.startYear(r.S), ab: r.champion || r.champName ? abbrOf(r, H) : null, fr: H.franchiseOf(r) }));
    const won = rows.filter(r => r.fr);
    const cur = RK.currentSeason(), curY = Math.floor(cur / 10000);
    const last = won[won.length - 1];
    /* titles by franchise (Victoria's 1925 WCHL Cup is not an NHL club's) */
    const by = {};
    won.forEach(r => { if (!/Victoria Cougars/.test(r.fr)) by[r.fr] = (by[r.fr] || 0) + 1; });
    const tl = Object.keys(by).sort((a, b) => by[b] - by[a] || a.localeCompare(b));
    /* dynasties: the same franchise in consecutive played seasons */
    const runs = [];
    let run = null;
    rows.forEach(r => {
      if (!r.fr) return;               // a season with no Cup awarded does not break a run
      if (run && run.fr === r.fr && r.y - run.to <= 2 && !rows.some(x => x.y > run.to && x.y < r.y && x.fr)) { run.to = r.y; run.n++; }
      else { if (run && run.n >= 2) runs.push(run); run = { fr: r.fr, ab: r.ab, from: r.y, to: r.y, n: 1 }; }
    });
    if (run && run.n >= 2) runs.push(run);
    runs.sort((a, b) => b.n - a.n || a.from - b.from);
    /* droughts: today's clubs with a Cup, seasons since the last one */
    const lastWin = {};
    won.forEach(r => { if (r.ab) lastWin[r.ab] = r.y; });
    const live = Object.keys(RK.NHL_TEAMS).filter(t => RK.HISTORIC.indexOf(t) < 0);
    const dr = live.filter(t => isNum(lastWin[t])).map(t => ({ t: t, y: lastWin[t], n: curY - lastWin[t] - 1 })).sort((a, b) => b.n - a.n);
    const never = live.filter(t => !isNum(lastWin[t])).sort((a, b) => RK.teamName(a).localeCompare(RK.teamName(b)));
    const most = tl[0];
    const tag = r => (r.ab ? RK.teamAbbr(r.ab) : (r.fr ? r.fr.replace(/ \(.*\)$/, '').split(' ').map(w => w.charAt(0)).join('').slice(0, 3).toUpperCase() : ''));
    const lab = y => y + '–' + String(y + 1).slice(2);
    const href = r => (r.ab ? RK.teamHref(r.ab, r.S >= RK.FIRST_SEASON ? r.S : undefined) : '');
    node.innerHTML = QK.stats([last ? { label: 'Last champion', value: tag(last), signal: true, href: href(last), sub: (last.champName || RK.teamName(last.ab)) + ', ' + lab(last.y) } : null,
        most ? { label: 'Most Cups', value: String(by[most]), sub: most } : null,
        dr[0] ? { label: 'Longest wait', value: String(dr[0].n), unit: 'seasons', href: RK.teamHref(dr[0].t), sub: RK.teamName(dr[0].t) + ': last Cup ' + lab(dr[0].y) } : null,
        runs[0] ? { label: 'Longest run', value: String(runs[0].n), unit: 'in a row', sub: runs[0].fr + ', ' + lab(runs[0].from) + ' to ' + lab(runs[0].to) } : null]) +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Every champion', title: 'A century of the Cup', sub: 'One block a season since 1917–18, in the champion’s colours, ten seasons a row. Grey blocks are clubs no longer in the league; an empty block is a season with no Cup awarded (1918–19, the influenza pandemic; 2004–05, the lockout). Tap a block for the club.' }) +
      '<div class="qk-grid"><div class="qk-span-8"><div class="qk-card"><div class="qk-card-body"><div class="rk-dyn" role="img" aria-label="Stanley Cup champions by season">' + strip(rows, tag, lab, href) + '</div></div></div></div>' +
      '<div class="qk-span-4">' + U.card2('Dynasties', 'Two or more Cups in a row', '<ul class="rk-list rk-dyn-l">' + runs.slice(0, 12).map(x => '<li><span class="rk-dyn-n num">' + x.n + '</span><span>' + (x.ab ? U.teamEnt(x.ab, {}) : esc(x.fr)) + '<span class="s">' + lab(x.from) + ' to ' + lab(x.to) + (x.n >= 4 ? ': ' + WORD[x.n] + ' straight' : '') + '</span></span></li>').join('') + '</ul>', { flush: true }) + '</div></div></section>' +
      '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + U.card2('Titles by franchise', 'Renamed and relocated clubs folded into today’s club; the first Ottawa Senators (1917–34) are their own club', U.chart('hs-titles', Math.max(320, 22 * tl.length + 60), 'Stanley Cups by franchise')) + '</div>' +
      '<div class="qk-span-6">' + U.card2('The droughts', 'Seasons since each club’s last Cup (today’s clubs that have won one)', U.chart('hs-dr', Math.max(320, 22 * dr.length + 60), 'Seasons since the last Cup') +
        (never.length ? '<p class="rk-note" style="margin:10px 0 0"><b>Still waiting for a first Cup:</b> ' + never.map(t => '<a class="qk-link" href="' + esc(RK.teamHref(t)) + '">' + esc(RK.teamName(t)) + '</a>').join(', ') + '.</p>' : '')) + '</div></div></section>' +
      '<details class="rk-fold"><summary>Every champion and runner-up, season by season (' + all.length + ' seasons)</summary><div class="rk-fold-b"><div class="qk-scoutbar-lite">' + QK.scoutBar([{ label: 'Search', html: '<input class="qk-input" id="hs-q" type="search" placeholder="Club…" autocomplete="off">', cls: 'grow' }]) + '</div><div id="hs-t"></div></div></details>' +
      '<div class="qk-grid" style="margin-top:var(--sp-6)"><div class="qk-span-6"><div class="card"><div class="card-header">The league by era <span class="card-sub">The league’s eras and what changed, with the regular season’s length and league rates by season.</span><span class="gq-ctl" id="hi-env-ctl"></span></div><div id="hi-env" class="gf-chart-lg"></div><div class="pg-note gq-note" id="hi-env-n"></div></div></div>' +
      '<div class="qk-span-6"><div class="card"><div class="card-header">Season leaders <span class="card-sub" id="hi-ld-sub">The league leaders in each season on file.</span><span class="gq-ctl" id="hi-ld-ctl"></span></div><div id="hi-ld"></div></div></div></div>';
    node.querySelectorAll('.rk-dyn [data-href]').forEach(b => b.addEventListener('click', () => { location.hash = b.getAttribute('data-href'); }));
    QKC.bar('#hs-titles', { cats: tl, series: [{ name: 'Stanley Cups', data: tl.map(f => by[f]) }], horizontal: true, labels: true, fmt: v => String(v), labelWidth: 170, valName: 'Stanley Cups',
      colors: tl.map(f => { const r = won.filter(x => x.fr === f)[0]; return r && r.ab ? RK.teamColourRaw(r.ab) : '#5b6475'; }), hrefs: tl.map(f => { const r = won.filter(x => x.fr === f)[0]; return r && r.ab ? RK.teamHref(r.ab) : ''; }) });
    QKC.bar('#hs-dr', { cats: dr.map(x => RK.teamName(x.t)), series: [{ name: 'Seasons since the last Cup', data: dr.map(x => x.n) }], horizontal: true, labels: true, fmt: v => String(v), labelWidth: 170, valName: 'Seasons since the last Cup',
      colors: dr.map(x => RK.teamColourRaw(x.t)), hrefs: dr.map(x => RK.teamHref(x.t)) });
    const drawT = () => {
      const q = RK.fk.fold(((node.querySelector('#hs-q') || {}).value || '').trim());
      const list = rows.slice().reverse().filter(r => !q || RK.fk.fold([r.fr, r.champName, r.runnerName, r.runner, r.ab ? RK.teamName(r.ab) : ''].join(' ')).indexOf(q) >= 0);
      const ent = (ab, nm, S) => (ab ? '<a class="rk-ent" href="' + esc(RK.teamHref(ab, S >= RK.FIRST_SEASON ? S : undefined)) + '">' + QK.teamMark(U.team(ab), 'sm') + '<span class="nm">' + esc(nm || RK.teamName(ab)) + '</span></a>' : esc(nm || '—'));
      const rAb = r => (r.runner && /^[A-Z]{2,3}$/.test(String(r.runner)) ? RK.canonTeam(r.runner) : abbrOf({ champion: null, champName: r.runnerName || r.runner, S: r.S }, H));
      node.querySelector('#hs-t').innerHTML = '<div class="qk-table-wrap" style="--table-max:640px"><table class="qk-table dense"><thead><tr><th>Season</th><th>Champion</th><th>Runner-up</th></tr></thead><tbody>' +
        list.map(r => '<tr><td><b>' + esc(RK.seasonLabel(r.S)) + '</b></td><td>' + (r.fr ? ent(r.ab, r.champName || (r.ab ? RK.teamName(r.ab) : r.champion), r.S) : '<span class="qk-muted">' + esc(r.note || 'Not awarded') + '</span>') + '</td><td>' + (r.runner || r.runnerName ? ent(rAb(r), r.runnerName || (/^[A-Z]{2,3}$/.test(String(r.runner)) ? RK.teamName(r.runner) : r.runner), r.S) : '—') + '</td></tr>').join('') + '</tbody></table></div>';
    };
    drawT();
    node.querySelector('#hs-q').addEventListener('input', drawT);
    const eras = (RK.fk.listOf(d.eras) || []).map(e => [H.startYear(e.from) || e.from, H.startYear(e.to) || e.to, e.name, e.note || '']).filter(e => isNum(e[0]));
    H.envChart(H.envOf(d), eras.length ? eras : H.ERAS);
    H.seasonLeaders(H.leadersOf(d));
  });
};

function strip(rows, tag, lab, href) {
  const y0 = Math.floor(rows[0].y / 10) * 10, y1 = rows[rows.length - 1].y;
  const by = {}; rows.forEach(r => { by[r.y] = r; });
  let h = '';
  for (let dcd = y0; dcd <= y1; dcd += 10) {
    h += '<div class="rk-dyn-r"><span class="rk-dyn-d">' + dcd + 's</span>';
    for (let y = dcd; y < dcd + 10; y++) {
      const r = by[y];
      if (!r || y > y1) { h += '<span class="rk-dyn-b off" aria-hidden="true"></span>'; continue; }
      if (!r.fr) { h += '<span class="rk-dyn-b none" title="' + esc(lab(y) + ': ' + (r.note || 'not awarded')) + '"></span>'; continue; }
      const blk = QK.color.block(r.ab ? RK.teamColourRaw(r.ab) : null);
      const bg = r.ab ? blk.bg : '#3a4150';
      h += '<span class="rk-dyn-b" style="background:' + esc(bg) + (blk.edge && r.ab ? ';box-shadow:inset 0 -4px 0 ' + esc(blk.edge) : '') + '"' + (href(r) ? ' data-href="' + esc(href(r)) + '" role="link" tabindex="0"' : '') + ' title="' + esc(lab(y) + ': ' + (r.champName || r.fr)) + '"><b>' + esc(tag(r)) + '</b><small>' + String(y + 1).slice(2) + '</small></span>';
    }
    h += '</div>';
  }
  return h;
}
})(window.RK);
