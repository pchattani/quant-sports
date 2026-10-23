/* The Quant Gridiron — All-time (#/history): single-season and career boards since 1999, raw or
 * era-adjusted (100 = that season's average at the position, 10 = one SD), filtered by seasons and
 * searchable, with a chart of the board's top 15 and the league environment by season (Design System 2.0: stat tiles,
 * a leaderboard with team marks and inline bars).
 * Reads history.json ({season_leaders, career_leaders, *_cols, league, era_note, season_floor, coverage}). */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const MARK = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
const ST = { board: '', adj: true, from: 1999, to: 2100, q: '', env: 'epa_play' };
const ENV = { epa_play: ['EPA per play', '3'], pass_epa: ['EPA per dropback', '3'], rush_epa: ['EPA per carry', '3'], ppg: ['Points per team game', '1'], pass_rate: ['Pass rate', 'pct'], success: ['Success rate', 'pct'],
  go_rate: ['4th-down go rate', 'pct'], fg_pct: ['FG %', 'pct'], sack_rate: ['Sack rate', 'pct'], int_rate: ['INT rate', 'pct'], home_win: ['Home win rate', 'pct'], penalties_pg: ['Penalties per game', '1'], adot: ['aDOT', '1'] };

function boards(d) {
  const out = [];
  [['season_leaders', 'season_cols', 'season'], ['career_leaders', 'career_cols', 'career']].forEach(z => {
    const X = d[z[0]] || {}, cols = d[z[1]] || [];
    Object.keys(X).forEach(id => {
      const b = X[id] || {};
      const rows = GI.colRows({ cols: cols, rows: b.rows || [] }).map(o => (z[2] === 'career' ? { pid: o.pid, name: o.name, first: o.first, last: o.last, value: o.total, n: o.seasons } : { pid: o.pid, name: o.name, season: o.season, team: o.team, value: o.value, adj: o.plus }));
      out.push({ id: id, label: b.label || GI.titleCase(id), group: b.group || '', key: b.key || id, scope: z[2], fmt: b.fmt || '', lower: !!b.lower, rows: rows });
    });
  });
  return out.filter(b => b.rows.length);
}

GI.route('history', function (el) {
  return GI.load('history.json').then(d => {
    if (!el.isConnected) return;
    const head = GI.pageHead('Players · since 1999', 'All-time', 'The best single seasons and careers since 1999 from play-by-play, raw or against their own era.') + GI.sectionNav('players', 'history');
    if (!GI.ok(d)) { el.innerHTML = head + GI.notBuilt('The history boards', d); return; }
    const B = boards(d);
    if (!B.find(b => b.id === ST.board)) ST.board = B[0] ? B[0].id : '';
    const yrs = d.seasons || (d.league || []).map(r => r.season);
    const y0 = Math.min.apply(null, yrs), y1 = Math.max.apply(null, yrs);
    if (ST.to > y1) ST.to = y1;
    const opts = [{ group: 'Single seasons', items: B.filter(b => b.scope === 'season').map(b => [b.id, (b.group ? b.group + ' · ' : '') + b.label]) }, { group: 'Careers', items: B.filter(b => b.scope === 'career').map(b => [b.id, (b.group && b.group !== 'all' ? b.group.toUpperCase() + ' · ' : '') + b.label]) }];
    const years = []; for (let y = y1; y >= y0; y--) years.push([String(y), String(y)]);
    el.innerHTML = head + '<div id="hi-kpis"></div>' +
      GI.card('Board', '<span id="hi-sub"></span>', '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.field('Board', GI.select('hi-board', opts, ST.board, 'Board')) +
        GI.seg('hi-adj', [['1', 'Era-adjusted'], ['0', 'Raw']], ST.adj ? '1' : '0', 'Measure') + GI.field('From', GI.select('hi-from', years.slice().reverse(), String(ST.from), 'From')) + GI.field('To', GI.select('hi-to', years, String(ST.to), 'To')) +
        GI.field('Search', '<input id="hi-q" class="qk-input" type="search" placeholder="Player or team">') + '</div>' + GI.chartBox('hi-chart', 420, 'Top of the board') + '<div id="hi-table" style="margin-top:12px"></div><p class="gi-cap" id="hi-note"></p>') +
      GI.card('The league since ' + y0, 'League-wide rates by season: the environment the era adjustment works against', '<div class="gi-toolbar" style="margin-bottom:8px">' + GI.field('Rate', GI.select('hi-env', Object.keys(ENV).filter(k => (d.league || []).some(r => isNum(r[k]))).map(k => [k, ENV[k][0]]), ST.env, 'Rate')) + '</div>' + GI.chartBox('hi-envc', 300, 'League rate by season'));
    const $ = id => document.getElementById(id);
    $('hi-q').value = ST.q;
    const draw = () => {
      const b = B.find(x => x.id === ST.board);
      if (!b) return;
      const hasAdj = b.rows.some(r => isNum(r.adj));
      const useAdj = ST.adj && hasAdj;
      const q = GI.fold(ST.q.trim());
      const rows = b.rows.filter(r => (b.scope === 'career' ? (!isNum(r.last) || r.last >= ST.from) && (!isNum(r.first) || r.first <= ST.to) : r.season >= ST.from && r.season <= ST.to) &&
        (!q || GI.fold((r.name || '') + ' ' + (r.team || '')).indexOf(q) >= 0));
      const key = useAdj ? 'adj' : 'value';
      rows.sort((x, y) => { const dd = (isNum(y[key]) ? y[key] : -1e9) - (isNum(x[key]) ? x[key] : -1e9); return b.lower && !useAdj ? -dd : dd; });
      const fmtV = v => (b.scope === 'career' || Math.abs(v) >= 100 ? GI.int(v) : GI.fmtVal(v, b.fmt));
      const top = rows.slice(0, 15);
      const lab = r => (r.name || GI.playerName(r.pid)) + (b.scope === 'season' ? ' ' + r.season : '');
      if (top.length) GI.ch.bar('hi-chart', { cats: top.map(lab), series: [{ name: useAdj ? 'Era-adjusted' : b.label, data: top.map(r => r[key]) }], horizontal: true, labels: true, colors: top.map(r => GI.teamColour(r.team || GI.player(r.pid).team)), hrefs: top.map(r => GI.playerHref(r.pid)), fmt: v => (useAdj ? GI.int(v) : fmtV(v)), labelWidth: 190, min: useAdj ? 100 : undefined, valName: useAdj ? 'Era-adjusted (100 = average)' : b.label, catName: 'Player' });
      else GI.ch.none('hi-chart', 'Nobody on this board matches.');
      const L2 = rows.slice(0, 200).map(r => ({ pid: r.pid, name: r.name || GI.playerName(r.pid), team: r.team || GI.player(r.pid).team, sub: b.scope === 'career' ? (r.first || '') + '–' + (r.last || '') + ' · ' + (r.n || 0) + ' seasons' : r.season + ' · ' + GI.teamAbbr(r.team), value: r.value, adj: r.adj }));
      if (L2.length) QK.leaderboard($('hi-table'), { dense: true, rank: true, maxHeight: 600, rows: L2, rowHref: r => (r.pid ? GI.playerHref(r.pid) : ''),
        columns: [{ key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => MARK(r.team), href: r => (r.pid ? GI.playerHref(r.pid) : null), sort: false },
          useAdj ? { key: 'value', label: b.label + (b.lower ? ' ↓' : ''), num: true, fmt: v => fmtV(v), sort: false } : { key: 'value', label: b.label + (b.lower ? ' ↓' : ''), type: 'bar', fmt: v => '<b>' + fmtV(v) + '</b>', sort: false }]
          .concat(hasAdj ? [useAdj ? { key: 'adj', label: 'Era-adjusted', type: 'bar', fmt: v => '<b>' + GI.int(v) + '</b>', tip: '100 = that season\'s average at the position, 10 = one SD', sort: false } : { key: 'adj', label: 'Era-adjusted', num: true, fmt: v => GI.int(v), sort: false }] : []) });
      else GI.set('hi-table', GI.muted('Nobody on this board matches.'));
      const top1 = rows[0];
      GI.set('hi-kpis', top1 ? GI.kpis([GI.kpi(b.scope === 'career' ? 'Top career' : 'Top season', esc(top1.name || GI.playerName(top1.pid)), (b.scope === 'career' ? '' : top1.season + ' · ') + (useAdj ? GI.int(top1.adj) + ' era-adjusted' : fmtV(top1.value) + ' ' + esc(b.label)), { signal: true, text: true, href: top1.pid ? GI.playerHref(top1.pid) : null }),
        GI.kpi('On the board', GI.int(rows.length), ST.from + '–' + ST.to), GI.kpi('Measure', useAdj ? 'Era-adjusted' : 'Raw', useAdj ? '100 = that season\'s average, 10 = one SD' : 'as recorded', { text: true })]) : '');
      const fl = (d.season_floor || {})[b.group];
      GI.set('hi-sub', rows.length + ' on the ' + (b.scope === 'career' ? 'career' : 'single-season') + ' board · ' + ST.from + '–' + ST.to + (useAdj ? ' · era-adjusted' : ''));
      GI.set('hi-note', (useAdj ? esc(d.era_note || '') + ' ' : '') + (fl && b.scope === 'season' ? 'Sample floor: ' + fl.min + ' ' + esc(fl.metric) + '. ' : '') +
        'Coverage: play-by-play ' + esc((d.coverage || {}).pbp || '1999 on') + '; CPOE ' + esc((d.coverage || {}).cpoe || '') + '; NGS ' + esc((d.coverage || {}).ngs || '') + '; FTN ' + esc((d.coverage || {}).ftn || '') + '.');
    };
    const drawEnv = () => {
      const L = (d.league || []).slice().sort((a, b) => a.season - b.season);
      const e = ENV[ST.env] || ['', '3'];
      GI.ch.lines('hi-envc', [{ name: e[0], x: L.map(r => r.season), y: L.map(r => r[ST.env]), symbol: true, area: true }], { legend: false, yFmt: v => GI.fmtVal(v, e[1]), xFmt: String, xLabel: x => String(x), xName: 'Season', yName: e[0] });
    };
    $('hi-board').addEventListener('change', e => { ST.board = e.target.value; draw(); });
    $('hi-from').addEventListener('change', e => { ST.from = Number(e.target.value); draw(); });
    $('hi-to').addEventListener('change', e => { ST.to = Number(e.target.value); draw(); });
    let t = null;
    $('hi-q').addEventListener('input', e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); });
    $('hi-env').addEventListener('change', e => { ST.env = e.target.value; drawEnv(); });
    GI.wireSeg(el, 'hi-adj', v => { ST.adj = v === '1'; draw(); });
    draw();
    drawEnv();
  });
});

})(window.GI);
