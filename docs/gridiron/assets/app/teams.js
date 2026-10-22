/* The Quant Gridiron — Teams (#/teams), on Design System 2.0: every club at a glance as cards (record, rating, our
 * playoff and Super Bowl chances, rating trend), the EPA map (offence v defence per play) and one sortable table with
 * views for ratings, tendencies, fourth downs and our chances. Exports GI.TM (teams.json readers) for the team
 * page and compare. Reads <S>/teams.json and <S>/season.json. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum, first = GI.first;
const TM = {};
TM.of = d => {
  if (!d || d.ok === false) return null;
  GI.cleanMetrics(d.metrics);
  let teams = d.teams || null;
  if (Array.isArray(teams)) { const o = {}; teams.forEach(t => { const a = t.team || t.abbr; if (a) o[a] = t; }); teams = o; }
  if (!teams) return null;
  return { teams: teams, metrics: d.metrics || [], raw: d };
};
TM.history = x => {
  const raw = (x || {}).history || [];
  const hc = (x || {}).history_cols || ['week', 'net', 'off', 'def'];
  return raw.map(a => { if (!Array.isArray(a)) return a; const o = {}; hc.forEach((c, i) => { o[c] = a[i]; }); return o; }).filter(z => isNum(z.week)).sort((a, b) => a.week - b.week);
};
GI.TM = TM;

const ST = { conf: '', view: 'units' };
const VIEWS = { units: ['Ratings', 'EPA units'], style: ['Tendencies', 'Defence style', 'Pace', 'Pressure'], fourth: ['Fourth down'] };

function tcard(t, x, r, S) {
  const v = (x || {}).values || {}, rec = (x || {}).record || {};
  const h = TM.history(x).map(z => z.net);
  const sim = (x || {}).sim || {};
  return '<a class="qk-card is-link gi-tcard" href="' + GI.teamHref(t, S) + '" style="--tc:' + esc(GI.tc(t)) + '">' +
    '<div class="gi-tcard-top">' + GI.mark(t) + '<div class="gi-tcard-n"><b>' + esc(GI.teamName(t)) + '</b><span class="qk-sub">' + esc(GI.teamInfo(t).division || '') + ' · ' + esc(GI.record(first(r.w, rec.w), first(r.l, rec.l), first(r.t, rec.t))) + '</span></div>' +
    '<span class="gi-tcard-r gi-disp" title="Our team rating, points a game">' + (isNum(v.rating) ? GI.signed(v.rating, 1) : '—') + '</span></div>' +
    (h.length > 1 ? QK.spark(h, { color: GI.tc(t), w: 220, h: 30, base: 0, label: 'Rating by week' }) : '') +
    '<div class="gi-tcard-stats"><div><span>Playoffs</span><b>' + GI.pct(first(r.p_playoffs, sim.p_playoffs), 0) + '</b></div><div><span>Division</span><b>' + GI.pct(first(r.p_div, sim.p_div), 0) + '</b></div>' +
    '<div><span>Super Bowl</span><b>' + GI.pct(first(r.p_sb, sim.p_sb), 1) + '</b></div><div><span>Proj. wins</span><b>' + GI.num(first(r.mean_wins, sim.mean_wins), 1) + '</b></div></div></a>';
}

GI.route('teams', function (el, params) {
  const S = Number(params.season);
  return GI.loadAll([GI.ypath('teams.json', S), GI.ypath('season.json', S)]).then(res => {
    if (!el.isConnected) return;
    const cat = TM.of(res[0]);
    const rowsL = GI.ok(res[1]) ? GI.seasonRows(res[1]) : [];
    const rows = {};
    rowsL.forEach(r => { rows[r.team] = r; });
    const head = GI.pageHead('Teams · ' + S, 'The 32 teams', 'Ratings in points per game against an average team on a neutral field; chances from 20,000 simulated seasons. Tap a team for its page: ratings over time, strengths and needs, the current roster, schedule and moves.');
    if (!cat) { el.innerHTML = head + GI.notBuilt('The ' + S + ' team pages', res[0]); return; }
    const T = cat.teams;
    const ids = Object.keys(T).filter(t => /^[A-Z]{2,3}$/.test(t)).sort((a, b) => ((T[b].values || {}).rating || -99) - ((T[a].values || {}).rating || -99));
    el.innerHTML = head +
      '<div class="gi-toolbar">' + GI.seg('tm-conf', [['', 'All'], ['AFC', 'AFC'], ['NFC', 'NFC']], ST.conf, 'Conference') + '</div>' +
      '<div class="qk-auto gi-tcards" id="tm-cards" style="--min:250px"></div>' +
      GI.grid(GI.card('Offence v defence per play', 'Opponent-adjusted EPA per play; up and right is better (less EPA allowed is up); dot size: our playoff chance', GI.chartBox('tm-map', 460, 'Offence EPA against defence EPA'), { span: 12 })) +
      GI.card('Every team, every metric', 'Click a header to sort · percentile chips against the 32 teams: 100 = best (↓ metrics flipped); tendencies are not good or bad, so they carry ranks',
        '<div class="gi-toolbar">' + GI.seg('tm-view', [['units', 'Ratings'], ['style', 'Tendencies'], ['fourth', '4th downs'], ['odds', 'Chances']], ST.view, 'View') + '</div><div id="tm-table"></div>');
    const draw = () => {
      const list = ids.filter(t => !ST.conf || GI.teamInfo(t).conference === ST.conf);
      GI.set('tm-cards', list.map(t => tcard(t, T[t], rows[t] || {}, S)).join(''));
      let cols, body;
      const base = t => { const r = rows[t] || {}, rec = T[t].record || {}; return [{ v: GI.teamName(t), html: GI.teamLink(t, { season: S }) }, { v: GI.first(r.pct, rec.pct), html: GI.record(first(r.w, rec.w), first(r.l, rec.l), first(r.t, rec.t)) }, { v: first(r.diff, rec.diff), html: GI.deltaHTML(first(r.diff, rec.diff), 0) }]; };
      const head0 = [{ label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Diff', align: 'right' }];
      if (ST.view === 'odds') {
        const O = [['mean_wins', 'Proj. wins', 1], ['p_playoffs', 'Playoffs'], ['p_div', 'Division'], ['p_bye', 'Bye'], ['p_conf', 'Conf.'], ['p_sb', 'Super Bowl'], ['sos_left', 'SOS left', 2]];
        cols = head0.concat(O.map(o => ({ label: o[1], align: 'right' })));
        body = list.map(t => { const r = Object.assign({}, T[t].sim || {}, rows[t] || {}); return { _href: GI.teamHref(t, S), cells: base(t).concat(O.map(o => ({ v: r[o[0]], html: o[2] ? (o[0] === 'sos_left' ? GI.signed(r[o[0]], 2) : GI.num(r[o[0]], 1)) : GI.pct(r[o[0]], 1) }))) }; });
      } else {
        const ms = cat.metrics.filter(m => VIEWS[ST.view].indexOf(m.group) >= 0 && list.some(t => isNum((T[t].values || {})[m.key])));
        cols = head0.concat(ms.map(m => ({ label: GI.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') })));
        body = list.map(t => ({ _href: GI.teamHref(t, S), cells: base(t).concat(ms.map(m => { const v = (T[t].values || {})[m.key], pc = (T[t].pct || {})[m.key], rk = (T[t].rank || {})[m.key];
          return { v: isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gi-num">' + GI.fmtVal(v, m.fmt) + '</span>' + (isNum(pc) ? ' ' + QK.pctlChip(pc) : isNum(rk) ? ' <span class="gi-tag">#' + rk + '</span>' : '') }; })) }));
      }
      GI.set('tm-table', GI.tableHTML(cols, body, { sticky: true }));
      GI.sortable(document.getElementById('tm-table'));
      const pts = list.map(t => ({ t: t, x: (T[t].values || {}).off_epa, y: (T[t].values || {}).def_epa, p: first((rows[t] || {}).p_playoffs, (T[t].sim || {}).p_playoffs) })).filter(p => isNum(p.x) && isNum(p.y));
      if (pts.length > 2) GI.ch.mount('tm-map', Tk => ({
        grid: { left: 8, right: 24, top: 18, bottom: 30, containLabel: true },
        xAxis: GI.ch.ax(Tk, { name: 'Offence EPA per play', nameLocation: 'middle', nameGap: 26, scale: true, fmt: v => GI.signed(v, 2) }),
        yAxis: GI.ch.ax(Tk, { name: 'Defence EPA allowed', scale: true, inverse: true, fmt: v => GI.signed(v, 2) }),
        tooltip: GI.ch.tip(Tk, { formatter: q => { const p = q.data.p; return GI.ch.thead(esc(GI.teamName(p.t))) + GI.ch.trow(q.color, 'Offence', GI.signed(p.x, 3)) + GI.ch.trow(q.color, 'Defence allows', GI.signed(p.y, 3)) + (isNum(p.p) ? GI.ch.trow(Tk.ink3, 'Playoffs', GI.pct(p.p, 0)) : ''); } }),
        series: [{ type: 'scatter', symbolSize: (v, q) => 9 + 22 * (isNum(q.data.p.p) ? q.data.p.p : 0.2),
          label: { show: true, formatter: q => q.data.p.t, position: 'top', color: Tk.ink2, fontSize: 10, fontWeight: 600 }, labelLayout: { hideOverlap: true },
          data: pts.map(p => ({ value: [p.x, p.y], p: p, href: GI.teamHref(p.t, S), itemStyle: { color: GI.ch.lift(GI.teamColour(p.t), Tk), borderColor: Tk.s1, borderWidth: 1.5 } })),
          markLine: { silent: true, symbol: 'none', lineStyle: { color: Tk.axis, type: [4, 4] }, label: { show: false }, data: [{ xAxis: GI.median(pts.map(p => p.x)) }, { yAxis: GI.median(pts.map(p => p.y)) }] } }]
      }), 'Offence against defence per play');
    };
    GI.wireSeg(el, 'tm-conf', v => { ST.conf = v; draw(); });
    GI.wireSeg(el, 'tm-view', v => { ST.view = v; draw(); });
    draw();
  });
});

})(window.GI);
