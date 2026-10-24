/* The Quant Paddock — Compare (#/compare/drivers/<a>/<b>, #/compare/teams/<a>/<b>), part of the Lab, on kit v4: the title
 * is the question ("Russell or Antonelli?"), two entries draw the tale of the tape in constructor colours (QK.tape,
 * team-mates: the second falls to slate with the colour as its rule), and one-line verdicts (QK.verdicts) say where
 * each leads the other by the most.
 * Drivers: identity cards, the side-by-side view (QK.compareView) on the F1 driver metric set (PD.v2.DRIVER_SET then
 * MORE_DRIVER) with percentiles against the season's drivers at the starts floor, where both sit in the peer
 * distribution, the races they shared, every metric (classic), Elo through their careers and the careers.
 * Teams: the same on the constructor set plus car pace, points, pit crews and reliability. With nobody picked, the
 * two points-per-race leaders (drivers) or the top two constructors; with one driver picked, his team-mate. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var CA = 'var(--wp-a)', CB = 'var(--wp-b)';

/* The page title as the question (kit v3). */
function ask(names) {
  var t = document.querySelector('.pd-page-compare .qk-sh-title');
  if (t && names[0] && names[1]) t.textContent = names[0] + ' or ' + names[1] + '?';
}
function metricTable(id, metrics, A, B, nA, nB) {
  PD.table(id, [
    { key: 'label', label: 'Metric', sticky: true, fmt: function (v, r) { return '<a class="pd-link" href="#/glossary/' + encodeURIComponent(r.key) + '">' + esc(v) + '</a>' + (r.lower ? ' <span class="qk-muted">↓</span>' : ''); } },
    { key: 'group', label: 'Group', fmt: function (v) { return '<span class="qk-muted">' + esc(v) + '</span>'; } },
    { key: 'va', label: nA, num: true, pctl: 'pa', fmt: function (v, r) { return (r.better === 'a' ? '<b>' : '') + PD.fmtVal(v, r.fmt) + (r.better === 'a' ? '</b>' : ''); } },
    { key: 'gapAbs', label: 'Gap', num: true, tip: 'Percentile-point gap: blue when ' + nA + ' leads, grey when ' + nB + ' does', fmt: function (v, r) { return gapBar(r.gap); } },
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
/* The v2 side-by-side card: the metric set (headline groups, then the secondary set) with each entry's peer percentile.
   cats: [catalogue per entry], Ps: [peer group per entry], ids, sets. */
function sideBySide(ids, rows, Ps, sets, ents) {
  var meta = Ps[0].meta;
  var groups = sets.map(function (g) {
    return { label: g[0], rows: g[1].filter(function (k) { return meta[k]; }).map(function (k) {
      var m = meta[k];
      return { label: PD.v2.label(meta, k), tip: PD.v2.tip(meta, k), better: m.lower ? 'low' : 'high', values: rows.map(function (r) { return ((r || {}).values || {})[k]; }),
        pctls: ids.map(function (id, i) { var pc = Ps[i] && Ps[i].pct[id]; return pc ? pc[k] : null; }), fmt: function (v) { return PD.v2.fmt(meta, k, v); },
        dfmt: m.fmt === 'prob' ? function (v) { return (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v * 100).toFixed(0) + ' pts'; } : null };
    }) };
  });
  return QK.compareView({ entities: ents, groups: groups });
}
function distCard(id, opts) {
  return PD.card('Where they sit', '<span id="' + id + '-s"></span>', PD.v2.distSeg(id + '-m', opts) + PD.chartBox(id, 260, 'Peer distribution with both marked'), { span: 12 });
}
function wireDist(id, P, rows, names, opts) {
  var cols = ['wpA', 'wpB'];
  var draw = function (key) { PD.v2.distribution('#' + id, P, key, rows.map(function (r, i) { return { x: ((r || {}).values || {})[key], label: names[i], color: cols[i] }; })); };
  PD.set(id + '-s', 'Every ' + (P.kind === 'teams' ? 'constructor' : 'driver') + ' in the peer group (' + esc(P.label) + '), with both marked; the median dashed.');
  draw(opts[0][0]);
  PD.wireSeg(document, id + '-m', draw);
}
function picker(kind, a, b, opts) {
  var sel = function (id, cur) { return '<select class="qk-select" id="' + id + '"><option value="">Pick…</option>' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select>'; };
  return '<div class="pd-toolbar pd-cmp-pick"><i class="pd-dot" style="--tc:var(--wp-a)"></i>' + sel('cmp-a', a) + '<span class="qk-muted">v</span><i class="pd-dot" style="--tc:var(--wp-b)"></i>' + sel('cmp-b', b) + '<button type="button" class="qk-btn" id="cmp-swap">⇄ Swap</button></div>';
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
  el.innerHTML = PD.pageHead('Lab · side by side', kind === 'teams' ? 'Compare constructors' : 'Compare drivers', kind === 'teams' ? 'Two constructors on the metrics that best describe and predict a team, ranked against the season’s constructors. The address updates so a comparison can be shared.' : 'Two drivers on the metrics that best describe and predict a driver, the car taken out where it can be, ranked against the season’s drivers. The address updates so a comparison can be shared.') + PD.labNav(kind) + '<div id="cmp-pick"></div><div id="cmp-body"></div>';
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
    var DD = ((dj || {}).drivers) || {};
    if (!a && !b) { var sd = Object.keys(DD).sort(function (p, q) { return (DD[q].values || {}).points_per_race - (DD[p].values || {}).points_per_race; }); a = sd[0]; b = sd[1]; }
    else if (a && !b && DD[a]) b = Object.keys(DD).filter(function (k) { return k !== a && DD[k].team === DD[a].team; }).sort(function (p, q) { return (DD[q].races || 0) - (DD[p].races || 0); })[0];
    if (!a || !b) { PD.set('cmp-body', PD.empty('Pick two drivers', 'Team-mates make the cleanest comparison: same car, same races.')); return null; }
    var sa = document.getElementById('cmp-a'), sb = document.getElementById('cmp-b'); if (sa) sa.value = a; if (sb) sb.value = b;
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
    var tr = PD.teamColourRaw(d.team || PD.driverTeam(id));
    var col = tr ? QK.color.team(tr) : (i ? CB : CA);
    var facts = [['Season', ss[i].year || '—'], ['Races', isNum(d.races) ? d.races : '—'], ['Points', isNum(st.points) ? PD.pts(st.points) : '—'], ['Starts', isNum(tot.races) ? tot.races : sum('races')],
      ['Wins', isNum(tot.wins) ? tot.wins : sum('wins')], ['Titles', isNum(tot.titles) ? tot.titles : seasons.filter(function (s) { return s.pos === 1; }).length], ['Elo now', isNum(e) ? PD.num(e, 0) : '—'], ['Peak Elo', isNum(tot.peak_elo) ? PD.num(tot.peak_elo, 0) : '—']];
    return '<div class="qk-card pd-cmp-id" style="--tc:' + col + '"><div class="pd-cmp-id-top"><span class="qk-avatar" style="--tc:' + col + '">' + esc(info.number || PD.driverCode(id)) + '</span><div><b>' + PD.driverLink(id, { name: names[i], dot: false }) + '</b><div class="qk-sub">' +
      (d.team ? PD.teamLink(d.team) : '') + (c.nationality ? ' · ' + esc(c.nationality) : '') + '</div></div></div><div class="pd-facts">' + facts.map(function (f) { return '<div><span>' + f[0] + '</span><b>' + f[1] + '</b></div>'; }).join('') + '</div></div>';
  };
  var Ps = [0, 1].map(function (i) { return ss[i].cat ? PD.v2.peer(ss[i].cat, 'drivers', ss[i].year === y ? season : null) : null; });
  var ents = [0, 1].map(function (i) { var d = ss[i].d || {}; return { name: names[i], href: PD.driverHref(ids[i]), abbr: short[i], short: short[i], colour: PD.teamColourRaw(d.team || PD.driverTeam(ids[i])), sub: [d.team ? PD.teamName(d.team) : '', ss[i].year ? ss[i].year : '', isNum(d.races) ? d.races + ' starts' : ''].filter(Boolean).join(' · ') }; });
  var peerTxt = Ps[0] && Ps[1] ? (same ? 'Ranked against ' + esc(Ps[0].label) + ' in ' + ss[0].year + ' (' + Ps[0].n + ' drivers)' : 'Different seasons: each ranked against their own season’s drivers (' + (ss[0].year || '—') + ' v ' + (ss[1].year || '—') + ')') : 'No driver catalogue for one of them (it starts in 2018)';
  var shortOf = [0, 1].filter(function (i) { return Ps[i] && !Ps[i].qualified(ids[i]); }).map(function (i) { return names[i]; });
  ask(short);
  var verd = Ps[0] && Ps[1] ? QK.verdicts(PD.v2.verdicts(Ps, ids, PD.v2.DRIVER_SET.concat(PD.v2.MORE_DRIVER), short)) : '';
  var dOpts = [['driver_effect', 'Race pace v team-mate'], ['quali_driver_effect', 'Qualifying'], ['race_h2h', 'Race H2H'], ['points_per_race', 'Points / race'], ['race_pace', 'Race pace']];
  PD.set('cmp-body', '<div class="pd-cmp-ids">' + card(0) + card(1) + '</div>' +
    PD.card('Side by side', peerTxt + '. Bar length = percentile (100 = best); the better number in each row is solid.', Ps[0] && Ps[1] ? sideBySide(ids, [ss[0].d, ss[1].d], Ps, PD.v2.DRIVER_SET.concat(PD.v2.MORE_DRIVER), ents) + verd +
      (shortOf.length ? '<p class="pd-cap">' + esc(shortOf.join(' and ')) + (shortOf.length > 1 ? ' are' : ' is') + ' short of the starts floor: no percentile.</p>' : '') : PD.muted('Nothing to compare yet.'), { cls: 'pd-mt' }) +
    PD.grid((same && Ps[0] ? distCard('cmp-dist', dOpts) : '') +
      PD.card('Races together', '<span id="cmp-sh-s">Head to head in every season both raced.</span>', '<div id="cmp-sh"></div>', { span: 12, flush: true }) +
      PD.card('Every metric (classic)', 'Value and the payload’s field percentile on both sides (every entrant, stand-ins included), ordered by the size of the gap. Bold marks the better raw figure.', '<div id="cmp-m"></div>', { span: 12, flush: true }) +
      PD.card('Elo through their careers', 'Field Elo after every race (solid) and against the team-mate (dashed).', PD.chartBox('cmp-elo', 340), { span: 12 }) +
      PD.card('Careers', 'Totals from every world championship start.', PD.chartBox('cmp-car', 300), { span: 12 }), 'pd-mt'));
  if (same && Ps[0] && document.getElementById('cmp-dist')) wireDist('cmp-dist', Ps[0], [ss[0].d, ss[1].d], short, dOpts);
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
    PD.set('cmp-sh', '<div class="pd-pad">' + PD.h2hBar('Qualifying, every shared round', qa, qb, PD.col('sky'), PD.col('coral'), short[0], short[1]) + PD.h2hBar('Race', ra, rb, PD.col('sky'), PD.col('coral'), short[0], short[1]) + '</div><div id="cmp-sh-t"></div>');
    if (rows.length) PD.table('cmp-sh-t', [{ key: 'year', label: 'Season', num: true, fmt: String }, { key: 'cars', label: 'Cars', fmt: function (v) { return v; } }, { key: 'n', label: 'Rounds', num: true }, { key: 'q', label: 'Quali', num: true }, { key: 'r', label: 'Race', num: true }, { key: 'p', label: 'Points', num: true }], rows, { sort: { key: 'year', dir: 'desc' } });
  });
  var series = [];
  careers.forEach(function (c, i) {
    var e = (c || {}).elo || [];
    if (!e.length) return;
    var col = i ? PD.col('coral') : PD.col('sky');
    series.push({ name: names[i], data: e.map(function (r) { return [r[0] + (r[1] - 1) / 25, r[2]]; }), colour: col });
    series.push({ name: names[i] + ' v team-mate', data: e.map(function (r) { return [r[0] + (r[1] - 1) / 25, r[3]]; }), colour: col, dash: true, width: 1.3 });
  });
  PD.ch.lines('cmp-elo', series, { xName: 'Season', yName: 'Elo rating', xFmt: function (v) { return String(Math.floor(v)); }, xLabel: function (v) { return String(Math.floor(v)); }, yFmt: function (v) { return PD.num(v, 0); }, emptyText: 'No Elo history for either driver.', label: 'Elo histories' });
  var tot2 = careers.map(function (c) { var s = (c || {}).seasons || [], t = (c || {}).totals || {}; var sum = function (k) { return s.reduce(function (a2, r) { return a2 + (r[k] || 0); }, 0); };
    return { Starts: isNum(t.races) ? t.races : sum('races'), Wins: isNum(t.wins) ? t.wins : sum('wins'), Podiums: isNum(t.podiums) ? t.podiums : sum('podiums'), Poles: isNum(t.poles) ? t.poles : sum('poles'), Titles: isNum(t.titles) ? t.titles : s.filter(function (r) { return r.pos === 1; }).length }; });
  var cats2 = ['Starts', 'Wins', 'Podiums', 'Poles', 'Titles'];
  PD.ch.columns('cmp-car', { cats: cats2, series: [{ name: names[0], data: cats2.map(function (k) { return tot2[0][k]; }), colour: PD.col('sky'), labels: true }, { name: names[1], data: cats2.map(function (k) { return tot2[1][k]; }), colour: PD.col('coral'), labels: true }], fmt: function (v) { return PD.num(v, 0); }, yName: 'Career total', label: 'Career totals' });
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
    var cs = (((season || {}).standings || {}).constructors || []).map(function (r) { return r.team; });
    if (!a && !b) { a = cs[0]; b = cs[1]; } else if (a && !b) b = cs.filter(function (k) { return k !== a; })[0];
    if (!a || !b) { PD.set('cmp-body', PD.empty('Pick two constructors', 'From the ' + y + ' season (change it in the bar above).')); return; }
    var sa = document.getElementById('cmp-a'), sb = document.getElementById('cmp-b'); if (sa) sa.value = a; if (sb) sb.value = b;
    var names = [a, b].map(function (id) { return (T[id] || {}).name || PD.teamName(id); });
    var metrics = (tms || {}).metrics || [];
    var stand = {};
    (((season || {}).standings || {}).constructors || []).forEach(function (s) { stand[s.team] = s; });
    var champ = (((season || {}).championship || {}).constructors) || {};
    var lineup = function (id) { return ((((season || {}).teams || {})[id] || {}).drivers) || Object.keys(((drv || {}).drivers) || {}).filter(function (k) { return drv.drivers[k].team === id; }); };
    var card = function (i) {
      var id = [a, b][i], t = T[id] || {}, s = stand[id] || {}, c = champ[id], pit = t.pit || {};
      var col = PD.teamColourRaw(id) ? QK.color.team(PD.teamColourRaw(id)) : (i ? CB : CA);
      var facts = [['Position', s.pos ? PD.ordinal(s.pos) : '—'], ['Points', PD.pts(s.points)], ['Wins', s.wins || 0], ['Title', c ? PD.pct(c.p_title) : '—'], ['Median stop', isNum(pit.median_ms) ? PD.num(pit.median_ms / 1000, 2) + 's' : '—'], ['DNFs', (t.log || []).reduce(function (x, r) { return x + (r.dnfs || 0); }, 0)]];
      return '<div class="qk-card pd-cmp-id" style="--tc:' + col + '"><div class="pd-cmp-id-top">' + PD.mark(id, 'lg') + '<div><b>' + PD.teamLink(id, { name: names[i], dot: false }) + '</b><div class="qk-sub">' + lineup(id).map(function (d) { return PD.driverLink(d, { dot: false }); }).join(' · ') + '</div></div></div>' +
        '<div class="pd-facts">' + facts.map(function (f) { return '<div><span>' + f[0] + '</span><b>' + f[1] + '</b></div>'; }).join('') + '</div></div>';
    };
    var tP = PD.ok(tms) ? PD.v2.peer(tms, 'teams', season) : null;
    ask(names);
    var tverd = tP ? QK.verdicts(PD.v2.verdicts([tP, tP], [a, b], PD.v2.TEAM_SET.concat(PD.v2.MORE_TEAM), names)) : '';
    var tOpts = [['car_race_pace', 'Car pace'], ['points_per_race', 'Points / race'], ['dnf_rate', 'DNF rate'], ['pit_lane_v_field', 'Pit lane'], ['strategy_gain', 'Strategy']];
    var tents = [a, b].map(function (id, i) { return { name: names[i], href: PD.teamHref(id), abbr: PD.teamAbbr(id), short: PD.teamAbbr(id), colour: PD.teamColourRaw(id), sub: lineup(id).map(PD.driverSurname).join(' · ') }; });
    PD.set('cmp-body', '<div class="pd-cmp-ids">' + card(0) + card(1) + '</div>' +
      PD.card('Side by side', (tP ? 'Ranked against ' + esc(tP.label) + ' in ' + y + ' (' + tP.n + ' constructors)' : 'No team catalogue for ' + y) + '. Bar length = percentile (100 = best); the better number in each row is solid.',
        tP ? sideBySide([a, b], [T[a], T[b]], [tP, tP], PD.v2.TEAM_SET.concat(PD.v2.MORE_TEAM), tents) + tverd : PD.muted('Nothing to compare yet.'), { cls: 'pd-mt' }) +
      PD.grid((tP ? distCard('cmt-dist', tOpts) : '') +
        PD.card('Car pace', 'The car effect by round, % of a lap faster than the field, ±1 se.', PD.chartBox('cmt-pace', 360), { span: 12, right: PD.seg('cmt-pk', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') }) +
        PD.card('Points', 'Cumulative constructors’ points by round.', PD.chartBox('cmt-pts', 360), { span: 6 }) +
        PD.card('Reliability', 'Retirements, cumulative by round.', PD.chartBox('cmt-rel', 360), { span: 6 }) +
        PD.card('Pit crews', 'Every stationary time.', PD.chartBox('cmt-pit', 280), { span: 12 }) +
        PD.card('Every metric (classic)', 'The whole team catalogue with the payload’s field percentile, ordered by the size of the percentile gap.', '<div id="cmt-m"></div>', { span: 12, flush: true }), 'pd-mt'));
    if (tP && document.getElementById('cmt-dist')) wireDist('cmt-dist', tP, [T[a], T[b]], [PD.teamAbbr(a), PD.teamAbbr(b)], tOpts);
    var cols = [PD.col('sky'), PD.col('coral')];
    var drawPace = function (kind) {
      PD.ch.lines('cmt-pace', [a, b].map(function (id, i) {
        var rows = ((((season || {}).car_pace || {})[kind] || {})[id] || []).slice().sort(function (p, q) { return p.round - q.round; });
        return { name: names[i], colour: cols[i], symbols: true, data: rows.map(function (e) { return [e.round, -e.effect]; }), band: rows.map(function (e) { return [e.round, -e.effect - (e.se || 0), -e.effect + (e.se || 0)]; }) };
      }), { xName: 'Round', yName: 'Car pace (% of a lap)', yFmt: function (v) { return PD.signed(v, 2); }, xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { return 'Round ' + v; }, emptyText: 'No car-pace series.', label: 'Car pace comparison' });
    };
    drawPace('race');
    PD.wireSeg(document, 'cmt-pk', drawPace);
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
