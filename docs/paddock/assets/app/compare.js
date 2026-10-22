/* The Quant Paddock — Compare (#/compare/drivers/<a>/<b>, #/compare/teams/<a>/<b>), part of the Lab.
 * Drivers: identity cards, a verdict (who wins more catalogue percentiles and the biggest gaps), a
 * radar, the races they shared, every metric, Elo through their careers and the careers side by side.
 * Teams: the same over the team catalogue plus car pace, points, pit crews and reliability. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var CA = 'var(--c-1)', CB = 'var(--c-2)';

function verdict(metrics, A, B, nA, nB, note) {
  var cmp = metrics.map(function (m) { return { m: m, a: (A.pct || {})[m.key], b: (B.pct || {})[m.key] }; }).filter(function (x) { return isNum(x.a) && isNum(x.b); }).map(function (x) { x.gap = x.a - x.b; return x; });
  if (!cmp.length) return PD.muted('No metric has a percentile for both.');
  var wa = cmp.filter(function (x) { return x.gap > 0; }).length, wb = cmp.filter(function (x) { return x.gap < 0; }).length, lv = cmp.length - wa - wb, n = cmp.length;
  var topA = cmp.filter(function (x) { return x.gap > 0; }).sort(function (x, y) { return y.gap - x.gap; }).slice(0, 3);
  var topB = cmp.filter(function (x) { return x.gap < 0; }).sort(function (x, y) { return x.gap - y.gap; }).slice(0, 3);
  var say = function (list) { return list.length ? '<ul>' + list.map(function (x) { return '<li><b>+' + Math.round(Math.abs(x.gap)) + '</b> on ' + esc(x.m.label) + '</li>'; }).join('') + '</ul>' : '<p class="qk-muted">Leads on nothing.</p>'; };
  return '<div class="pd-verdict"><div class="pd-verdict-side a"><div class="qk-kicker">' + esc(nA) + ' leads on</div>' + say(topA) + '</div>' +
    '<div class="pd-verdict-mid"><div class="pd-verdict-score"><span class="a">' + wa + '</span><span>–</span><span class="b">' + wb + '</span></div><div class="pd-verdict-bar"><i class="a" style="width:' + (100 * wa / n) + '%"></i><i class="t" style="width:' + (100 * lv / n) + '%"></i><i class="b" style="width:' + (100 * wb / n) + '%"></i></div>' +
    '<div class="qk-sub">metrics won of ' + n + (lv ? ' · ' + lv + ' level' : '') + (note ? ' · ' + note : '') + '</div></div>' +
    '<div class="pd-verdict-side b"><div class="qk-kicker">' + esc(nB) + ' leads on</div>' + say(topB) + '</div></div>';
}
function metricTable(id, metrics, A, B, nA, nB) {
  PD.table(id, [
    { key: 'label', label: 'Metric', sticky: true, fmt: function (v, r) { return '<a class="pd-link" href="#/glossary/' + encodeURIComponent(r.key) + '">' + esc(v) + '</a>' + (r.lower ? ' <span class="qk-muted">↓</span>' : ''); } },
    { key: 'group', label: 'Group', fmt: function (v) { return '<span class="qk-muted">' + esc(v) + '</span>'; } },
    { key: 'va', label: nA, num: true, pctl: 'pa', fmt: function (v, r) { return (r.better === 'a' ? '<b>' : '') + PD.fmtVal(v, r.fmt) + (r.better === 'a' ? '</b>' : ''); } },
    { key: 'gapAbs', label: 'Gap', num: true, tip: 'Percentile-point gap: blue when ' + nA + ' leads, orange when ' + nB + ' does', fmt: function (v, r) { return gapBar(r.gap); } },
    { key: 'vb', label: nB, num: true, pctl: 'pb', fmt: function (v, r) { return (r.better === 'b' ? '<b>' : '') + PD.fmtVal(v, r.fmt) + (r.better === 'b' ? '</b>' : ''); } }
  ], metrics.map(function (m) {
    var va = (A.values || {})[m.key], vb = (B.values || {})[m.key], pa = (A.pct || {})[m.key], pb = (B.pct || {})[m.key];
    var gap = isNum(pa) && isNum(pb) ? pa - pb : null;
    return { key: m.key, label: m.label, group: m.group || '', lower: m.lower, fmt: m.fmt, va: va, vb: vb, pa: pa, pb: pb, gap: gap, gapAbs: gap === null ? -1 : Math.abs(gap), better: isNum(va) && isNum(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '' };
  }), { sort: { key: 'gapAbs', dir: 'desc' }, maxHeight: 640 });
}
function gapBar(g) {
  if (!isNum(g)) return '<span class="qk-muted">—</span>';
  var w = Math.min(50, Math.abs(g) / 2);
  return '<span class="pd-gap" title="' + PD.signed(g, 0) + ' percentile points"><i style="' + (g >= 0 ? 'right:50%;background:' + CA : 'left:50%;background:' + CB) + ';width:' + w + '%"></i></span>';
}
function picker(kind, a, b, opts) {
  var sel = function (id, cur) { return '<select class="qk-select" id="' + id + '"><option value="">Pick…</option>' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select>'; };
  return '<div class="pd-toolbar pd-cmp-pick"><i class="pd-dot" style="--tc:var(--c-1)"></i>' + sel('cmp-a', a) + '<span class="qk-muted">v</span><i class="pd-dot" style="--tc:var(--c-2)"></i>' + sel('cmp-b', b) + '<button type="button" class="qk-btn" id="cmp-swap">⇄ Swap</button></div>';
}
function wire(kind, a, b) {
  var go = function () { var x = document.getElementById('cmp-a').value, y = document.getElementById('cmp-b').value; if (x && y && x !== y) location.hash = '#/compare/' + kind + '/' + encodeURIComponent(x) + '/' + encodeURIComponent(y); else if (x && !y) location.hash = '#/compare/' + kind + '/' + encodeURIComponent(x); };
  document.getElementById('cmp-a').onchange = go; document.getElementById('cmp-b').onchange = go;
  document.getElementById('cmp-swap').onclick = function () { if (a && b) location.hash = '#/compare/' + kind + '/' + encodeURIComponent(b) + '/' + encodeURIComponent(a); };
}

function render(el, params, state) {
  var kind = params.kind === 'teams' ? 'teams' : 'drivers';
  var a = params.a || '', b = params.b || '';
  var y = state.year || PD.currentSeason();
  el.innerHTML = PD.pageHead('Side by side', kind === 'teams' ? 'Compare constructors' : 'Compare drivers', 'Pick two; the address updates so a comparison can be shared.') + PD.labNav(kind) + '<div id="cmp-pick"></div><div id="cmp-body"></div>';
  return kind === 'teams' ? teams(el, a, b, y) : drivers(el, a, b, y);
}

// ── drivers ───────────────────────────────────────────────────────────────

function driverSeason(id, y, career) {
  return PD.load(y + '/drivers.json').then(function (dj) {
    if (dj && dj.drivers && dj.drivers[id]) return { year: y, cat: dj, d: dj.drivers[id] };
    var yrs = ((career || {}).seasons || []).map(function (s) { return s.year; }).filter(function (v) { return v !== y && v >= 2018; }).sort(function (p, q) { return q - p; });
    var tryY = function (i) { return i >= yrs.length || i > 3 ? Promise.resolve({ year: null, cat: null, d: null }) : PD.load(yrs[i] + '/drivers.json').then(function (d2) { return d2 && d2.drivers && d2.drivers[id] ? { year: yrs[i], cat: d2, d: d2.drivers[id] } : tryY(i + 1); }); };
    return tryY(0);
  });
}

function drivers(el, a, b, y) {
  return Promise.all([PD.load(y + '/drivers.json'), PD.load('elo.json')]).then(function (r0) {
    if (!PD.alive(el)) return null;
    var dj = r0[0], elo = r0[1];
    var ids = Object.keys(((dj || {}).drivers) || {}).concat(((elo || {}).all_time || []).map(function (x) { return x.driver; })).concat(Object.keys(PD.NAMES.drivers)).concat([a, b].filter(Boolean));
    ids = ids.filter(function (v, i, arr) { return arr.indexOf(v) === i; });
    PD.set('cmp-pick', picker('drivers', a, b, ids.map(function (k) { return [k, PD.driverName(k) + (((dj || {}).drivers || {})[k] ? ' (' + PD.teamName(dj.drivers[k].team) + ')' : '')]; }).sort(function (p, q) { return p[1].localeCompare(q[1]); })));
    wire('drivers', a, b);
    if (!a || !b) { PD.set('cmp-body', PD.empty('Pick two drivers', 'Team-mates make the cleanest comparison: same car, same races.')); return null; }
    PD.set('cmp-body', PD.empty('Loading', ''));
    return Promise.all([PD.load('drivers/' + a + '.json'), PD.load('drivers/' + b + '.json'), PD.load(y + '/season.json')]).then(function (r1) {
      var careers = [r1[0], r1[1]], season = r1[2];
      return Promise.all([driverSeason(a, y, careers[0]), driverSeason(b, y, careers[1])]).then(function (ss) { if (PD.alive(el)) buildDrivers([a, b], ss, careers, elo, season, y); });
    });
  });
}

function buildDrivers(ids, ss, careers, elo, season, y) {
  var names = ids.map(function (id, i) { return (ss[i].d && ss[i].d.name) || (careers[i] && careers[i].name) || PD.driverName(id); });
  var short = ids.map(PD.driverSurname);
  var same = ss[0].year && ss[0].year === ss[1].year;
  var metrics = ((ss[0].cat || ss[1].cat || {}).metrics) || [];
  var stand = {};
  (((season || {}).standings || {}).drivers || []).forEach(function (s) { stand[s.driver] = s; });
  var card = function (i) {
    var id = ids[i], d = ss[i].d || {}, c = careers[i] || {}, info = PD.NAMES.drivers[id] || {};
    var tot = c.totals || {}, seasons = c.seasons || [];
    var sum = function (k) { return seasons.reduce(function (s, r) { return s + (r[k] || 0); }, 0); };
    var st = ss[i].year === y ? (stand[id] || {}) : {};
    var e = (((elo || {}).current || {})[id] || {}).elo;
    var col = i ? CB : CA;
    var facts = [['Season', ss[i].year || '—'], ['Races', isNum(d.races) ? d.races : '—'], ['Points', isNum(st.points) ? PD.pts(st.points) : '—'], ['Starts', isNum(tot.races) ? tot.races : sum('races')],
      ['Wins', isNum(tot.wins) ? tot.wins : sum('wins')], ['Titles', isNum(tot.titles) ? tot.titles : seasons.filter(function (s) { return s.pos === 1; }).length], ['Elo now', isNum(e) ? PD.num(e, 0) : '—'], ['Peak Elo', isNum(tot.peak_elo) ? PD.num(tot.peak_elo, 0) : '—']];
    return '<div class="qk-card pd-cmp-id" style="--tc:' + col + '"><div class="pd-cmp-id-top"><span class="qk-avatar" style="--tc:' + col + '">' + esc(info.number || PD.driverCode(id)) + '</span><div><b>' + PD.driverLink(id, { name: names[i], dot: false }) + '</b><div class="qk-sub">' +
      (d.team ? PD.teamLink(d.team) : '') + (c.nationality ? ' · ' + esc(c.nationality) : '') + '</div></div></div><div class="pd-facts">' + facts.map(function (f) { return '<div><span>' + f[0] + '</span><b>' + f[1] + '</b></div>'; }).join('') + '</div></div>';
  };
  PD.set('cmp-body', '<div class="pd-cmp-ids">' + card(0) + card(1) + '</div>' +
    PD.card('Verdict', 'Who wins each catalogue metric on field percentile, and the biggest gaps each way.', verdict(metrics, ss[0].d || {}, ss[1].d || {}, short[0], short[1], same ? 'field percentiles, ' + ss[0].year : 'different seasons (' + (ss[0].year || '—') + ' v ' + (ss[1].year || '—') + ')'), { cls: 'pd-mt' }) +
    PD.grid(PD.card('Profile', 'Eight headline percentiles.', PD.chartBox('cmp-radar', 380), { span: 5 }) +
      PD.card('Races together', '<span id="cmp-sh-s">Head to head in every season both raced.</span>', '<div id="cmp-sh"></div>', { span: 7, flush: true }) +
      PD.card('Every metric', 'Value and field percentile on both sides, ordered by the size of the gap. Bold marks the better raw figure.', '<div id="cmp-m"></div>', { span: 12, flush: true }) +
      PD.card('Elo through their careers', 'Field Elo after every race (solid) and against the team-mate (dashed).', PD.chartBox('cmp-elo', 340), { span: 12 }) +
      PD.card('Careers', 'Totals from every world championship start.', PD.chartBox('cmp-car', 300), { span: 12 }), 'pd-mt'));
  var axes = PD.headline(metrics, ['race_pace', 'quali_pace', 'driver_effect', 'quali_driver_effect', 'overtakes_made', 'lap1_gain', 'tyre_mgmt', 'points_v_expected'], 8, true).map(function (m) { return { key: m.key, label: m.label.replace(/ \(.*\)$/, '').slice(0, 22) }; });
  PD.ch.radar('cmp-radar', axes, [{ name: names[0] + (same ? '' : ' ' + ss[0].year), pct: (ss[0].d || {}).pct, colour: '#3987e5' }, { name: names[1] + (same ? '' : ' ' + ss[1].year), pct: (ss[1].d || {}).pct, colour: '#e8833a' }]);
  if (metrics.length) metricTable('cmp-m', metrics, ss[0].d || {}, ss[1].d || {}, short[0], short[1]); else PD.set('cmp-m', PD.muted('No catalogue for these seasons (it starts in 2018).'));
  var yearsOf = function (c) { return ((c || {}).seasons || []).map(function (s) { return s.year; }); };
  var shared = yearsOf(careers[0]).filter(function (v) { return yearsOf(careers[1]).indexOf(v) >= 0; });
  if (!shared.length && same) shared = [ss[0].year];
  shared.sort(function (p, q) { return q - p; });
  Promise.all(shared.map(function (yy) { return yy >= 2018 ? PD.load(yy + '/drivers.json') : Promise.resolve(null); })).then(function (cats) {
    if (!document.getElementById('cmp-sh')) return;
    var rows = [], tot = { q: [0, 0], r: [0, 0] };
    cats.forEach(function (cat, i) {
      var D = (cat || {}).drivers || {}, da = D[ids[0]], db = D[ids[1]];
      var ca = ((careers[0] || {}).seasons || []).filter(function (s) { return s.year === shared[i]; })[0] || {}, cb = ((careers[1] || {}).seasons || []).filter(function (s) { return s.year === shared[i]; })[0] || {};
      if (da && db) {
        var hh = PD.h2h(da.log, db.log);
        tot.q[0] += hh.quali[0]; tot.q[1] += hh.quali[1]; tot.r[0] += hh.race[0]; tot.r[1] += hh.race[1];
        rows.push({ year: shared[i], cars: da.team === db.team ? PD.teamLink(da.team) + ' <span class="qk-badge">team-mates</span>' : PD.teamLink(da.team) + ' v ' + PD.teamLink(db.team), n: hh.both, q: hh.quali[0] + '–' + hh.quali[1], r: hh.race[0] + '–' + hh.race[1], p: PD.pts(hh.points[0]) + '–' + PD.pts(hh.points[1]) });
      } else if (ca.year && cb.year) rows.push({ year: shared[i], cars: PD.teamLink(ca.team) + ' v ' + PD.teamLink(cb.team), n: Math.min(ca.races || 0, cb.races || 0), q: '—', r: '—', p: PD.pts(ca.points) + '–' + PD.pts(cb.points) });
    });
    // career team-mate record when they were team-mates before the catalogue
    var tm = ((careers[0] || {}).teammates || []).filter(function (t) { return t.teammate === ids[1]; });
    if (!rows.length && !tm.length) { PD.set('cmp-sh', PD.muted('They never raced in the same season.')); return; }
    var qa = tot.q[0], qb = tot.q[1], ra = tot.r[0], rb = tot.r[1];
    if (!qa && !qb && tm.length) tm.forEach(function (t) { qa += (t.h2h_quali || [])[0] || 0; qb += (t.h2h_quali || [])[1] || 0; ra += (t.h2h_race || [])[0] || 0; rb += (t.h2h_race || [])[1] || 0; });
    PD.set('cmp-sh', '<div class="pd-pad">' + PD.h2hBar('Qualifying, every shared round', qa, qb, '#3987e5', '#e8833a', short[0], short[1]) + PD.h2hBar('Race', ra, rb, '#3987e5', '#e8833a', short[0], short[1]) + '</div><div id="cmp-sh-t"></div>');
    if (rows.length) PD.table('cmp-sh-t', [{ key: 'year', label: 'Season', num: true, fmt: String }, { key: 'cars', label: 'Cars', fmt: function (v) { return v; } }, { key: 'n', label: 'Rounds', num: true }, { key: 'q', label: 'Quali', num: true }, { key: 'r', label: 'Race', num: true }, { key: 'p', label: 'Points', num: true }], rows, { sort: { key: 'year', dir: 'desc' } });
  });
  var series = [];
  careers.forEach(function (c, i) {
    var e = (c || {}).elo || [];
    if (!e.length) return;
    var col = i ? '#e8833a' : '#3987e5';
    series.push({ name: names[i], data: e.map(function (r) { return [r[0] + (r[1] - 1) / 25, r[2]]; }), colour: col });
    series.push({ name: names[i] + ' v team-mate', data: e.map(function (r) { return [r[0] + (r[1] - 1) / 25, r[3]]; }), colour: col, dash: true, width: 1.3 });
  });
  PD.ch.lines('cmp-elo', series, { xName: 'Season', yName: 'Elo rating', xFmt: function (v) { return String(Math.floor(v)); }, xLabel: function (v) { return String(Math.floor(v)); }, yFmt: function (v) { return PD.num(v, 0); }, emptyText: 'No Elo history for either driver.', label: 'Elo histories' });
  var tot2 = careers.map(function (c) { var s = (c || {}).seasons || [], t = (c || {}).totals || {}; var sum = function (k) { return s.reduce(function (a2, r) { return a2 + (r[k] || 0); }, 0); };
    return { Starts: isNum(t.races) ? t.races : sum('races'), Wins: isNum(t.wins) ? t.wins : sum('wins'), Podiums: isNum(t.podiums) ? t.podiums : sum('podiums'), Poles: isNum(t.poles) ? t.poles : sum('poles'), Titles: isNum(t.titles) ? t.titles : s.filter(function (r) { return r.pos === 1; }).length }; });
  var cats2 = ['Starts', 'Wins', 'Podiums', 'Poles', 'Titles'];
  PD.ch.columns('cmp-car', { cats: cats2, series: [{ name: names[0], data: cats2.map(function (k) { return tot2[0][k]; }), colour: '#3987e5', labels: true }, { name: names[1], data: cats2.map(function (k) { return tot2[1][k]; }), colour: '#e8833a', labels: true }], fmt: function (v) { return PD.num(v, 0); }, yName: 'Career total', label: 'Career totals' });
}

// ── teams ─────────────────────────────────────────────────────────────────

function teams(el, a, b, y) {
  return PD.seasonData(y).then(function (res) {
    if (!PD.alive(el)) return;
    var drv = res[0], tms = res[1], season = res[2];
    var T = ((tms || {}).teams) || {};
    var ids = Object.keys(T).concat(Object.keys((season || {}).teams || {})).concat([a, b].filter(Boolean)).filter(function (v, i, arr) { return arr.indexOf(v) === i; });
    PD.set('cmp-pick', picker('teams', a, b, ids.map(function (k) { return [k, PD.teamName(k)]; }).sort(function (p, q) { return p[1].localeCompare(q[1]); })));
    wire('teams', a, b);
    if (!a || !b) { PD.set('cmp-body', PD.empty('Pick two constructors', 'From the ' + y + ' season (change it in the bar above).')); return; }
    var names = [a, b].map(function (id) { return (T[id] || {}).name || PD.teamName(id); });
    var metrics = (tms || {}).metrics || [];
    var stand = {};
    (((season || {}).standings || {}).constructors || []).forEach(function (s) { stand[s.team] = s; });
    var champ = (((season || {}).championship || {}).constructors) || {};
    var lineup = function (id) { return ((((season || {}).teams || {})[id] || {}).drivers) || Object.keys(((drv || {}).drivers) || {}).filter(function (k) { return drv.drivers[k].team === id; }); };
    var card = function (i) {
      var id = [a, b][i], t = T[id] || {}, s = stand[id] || {}, c = champ[id], pit = t.pit || {};
      var col = i ? CB : CA;
      var facts = [['Position', s.pos ? PD.ordinal(s.pos) : '—'], ['Points', PD.pts(s.points)], ['Wins', s.wins || 0], ['Title', c ? PD.pct(c.p_title) : '—'], ['Median stop', isNum(pit.median_ms) ? PD.num(pit.median_ms / 1000, 2) + 's' : '—'], ['DNFs', (t.log || []).reduce(function (x, r) { return x + (r.dnfs || 0); }, 0)]];
      return '<div class="qk-card pd-cmp-id" style="--tc:' + col + '"><div class="pd-cmp-id-top">' + PD.mark(id, 'lg') + '<div><b>' + PD.teamLink(id, { name: names[i], dot: false }) + '</b><div class="qk-sub">' + lineup(id).map(function (d) { return PD.driverLink(d, { dot: false }); }).join(' · ') + '</div></div></div>' +
        '<div class="pd-facts">' + facts.map(function (f) { return '<div><span>' + f[0] + '</span><b>' + f[1] + '</b></div>'; }).join('') + '</div></div>';
    };
    PD.set('cmp-body', '<div class="pd-cmp-ids">' + card(0) + card(1) + '</div>' +
      PD.card('Verdict', 'Who wins each team metric on field percentile.', verdict(metrics, T[a] || {}, T[b] || {}, names[0], names[1], 'field percentiles, ' + y), { cls: 'pd-mt' }) +
      PD.grid(PD.card('Car pace', 'The car effect by round, % of a lap faster than the field, ±1 se.', PD.chartBox('cmt-pace', 360), { span: 12, right: PD.seg('cmt-pk', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') }) +
        PD.card('Profile', 'Headline team metrics, field percentiles.', PD.chartBox('cmt-radar', 360), { span: 6 }) +
        PD.card('Points', 'Cumulative constructors’ points by round.', PD.chartBox('cmt-pts', 360), { span: 6 }) +
        PD.card('Pit crews', 'Every stationary time.', PD.chartBox('cmt-pit', 280), { span: 6 }) +
        PD.card('Reliability', 'Retirements, cumulative by round.', PD.chartBox('cmt-rel', 280), { span: 6 }) +
        PD.card('Every metric', 'Ordered by the size of the percentile gap.', '<div id="cmt-m"></div>', { span: 12, flush: true }), 'pd-mt'));
    var cols = ['#3987e5', '#e8833a'];
    var drawPace = function (kind) {
      PD.ch.lines('cmt-pace', [a, b].map(function (id, i) {
        var rows = ((((season || {}).car_pace || {})[kind] || {})[id] || []).slice().sort(function (p, q) { return p.round - q.round; });
        return { name: names[i], colour: cols[i], symbols: true, data: rows.map(function (e) { return [e.round, -e.effect]; }), band: rows.map(function (e) { return [e.round, -e.effect - (e.se || 0), -e.effect + (e.se || 0)]; }) };
      }), { xName: 'Round', yName: 'Car pace (% of a lap)', yFmt: function (v) { return PD.signed(v, 2); }, xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { return 'Round ' + v; }, emptyText: 'No car-pace series.', label: 'Car pace comparison' });
    };
    drawPace('race');
    PD.wireSeg(document, 'cmt-pk', drawPace);
    var axes = PD.headline(metrics, ['car_race_pace', 'car_quali_pace', 'top_speed', 'corner_speed', 'tyre_mgmt', 'pit_stop_ms', 'strategy_gain', 'dnf_rate'], 8, true).map(function (m) { return { key: m.key, label: m.label.replace(/ \(.*\)$/, '').slice(0, 22) }; });
    PD.ch.radar('cmt-radar', axes, [{ name: names[0], pct: (T[a] || {}).pct, colour: cols[0] }, { name: names[1], pct: (T[b] || {}).pct, colour: cols[1] }]);
    var prog = (((season || {}).progression || {}).constructors) || {};
    PD.ch.lines('cmt-pts', [a, b].map(function (id, i) { return { name: names[i], colour: cols[i], data: (prog[id] || []).map(function (v, k) { return [k + 1, v]; }) }; }), { xName: 'Round', yName: 'Points', yFmt: function (v) { return PD.pts(v); }, xFmt: function (v) { return 'R' + v; }, yScale: false, emptyText: 'No points progression.', label: 'Points comparison' });
    var stops = [a, b].map(function (id) { var p = (T[id] || {}).pit || {}; return (Array.isArray(p.stop_ms) ? p.stop_ms : []).filter(function (v) { return isNum(v) && v > 0 && v < 15000; }).map(function (v) { return v / 1000; }); });
    if (stops[0].length || stops[1].length) PD.ch.hist('cmt-pit', [{ name: names[0], values: stops[0], colour: cols[0] }, { name: names[1], values: stops[1], colour: cols[1] }], { bin: 0.2, xName: 'Stationary time (s)', yName: 'Stops', fmt: function (v) { return PD.num(v, 1); }, unit: ' s', label: 'Pit stop comparison' });
    else PD.ch.none('cmt-pit', 'No stationary times recorded.');
    PD.ch.lines('cmt-rel', [a, b].map(function (id, i) { var c = 0; return { name: names[i], colour: cols[i], step: 'end', data: ((T[id] || {}).log || []).slice().sort(function (p, q) { return p.round - q.round; }).map(function (r) { c += r.dnfs || 0; return [r.round, c]; }) }; }),
      { xName: 'Round', yName: 'Retirements, cumulative', step: 'end', yScale: false, yFmt: function (v) { return PD.num(v, 0); }, xFmt: function (v) { return 'R' + v; }, emptyText: 'No per-round log.', label: 'Reliability comparison' });
    if (metrics.length) metricTable('cmt-m', metrics, T[a] || {}, T[b] || {}, names[0], names[1]); else PD.set('cmt-m', PD.muted('No team catalogue for this season.'));
  });
}

PD.route('compare', render);
})(window.PD);
