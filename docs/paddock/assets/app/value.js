/* The Quant Paddock — Value & Moves (#/value[/<y>][?tab=drivers|swap|needs]).
 *   Driver value: the car/driver decomposition in % of a lap (positive = faster): pace above the
 *     team-mate (the driver alone, ±se) and above the field (driver and car now); cars by latest pace.
 *   Swap simulator (was #/swap): put driver X in car Y — both drivers' and both teams' seasons re-run
 *     through the championship simulation of the remaining rounds. Shareable: ?tab=swap&x=&w=.
 *   Team needs: every team's graded areas, and the driver moves that would add the most points.
 * Reads <y>/value.json (1994 on), <current>/swap.json, <current>/needs.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var pl = function (v, d) { return isNum(v) ? PD.signed(v, d === undefined ? 3 : d) + '%' : '—'; };

function render(el, params) {
  var y = isNum(params.year) ? params.year : PD.currentSeason();
  var q = params.query || {};
  var tab = ['drivers', 'swap', 'needs'].indexOf(q.tab) >= 0 ? q.tab : 'drivers';
  var cur = PD.currentSeason();
  var base = '#/value' + (y !== cur ? '/' + y : '');
  el.innerHTML = PD.pageHead('Value & Moves · ' + (tab === 'drivers' ? y : cur), 'Who’s fast, and what a seat swap would do', 'Who is quick once the car is taken out, who has the car, and what moving drivers between seats would do to the championship.', tab === 'drivers' ? PD.yearPager('value', y) : '') +
    PD.subnav([[base, 'Driver value', 'drivers'], ['#/value?tab=swap', 'Swap simulator', 'swap'], ['#/value?tab=needs', 'Team needs and moves', 'needs']], tab, 'Value views') +
    '<div class="pd-mt">' + PD.note(tab === 'swap' ? 'The swap runs the rest of the season again with two drivers in each other’s seats, using the same random draws, so the difference is the swap and not luck.' : tab === 'needs' ? 'Each team is graded against the others in every area: <b>A</b> from the 80th percentile, then B, C and D every 20 points.' : '<b>Pace above the team-mate</b> is the driver alone, the car taken out; <b>pace above the field</b> is driver and car together. Both are shares of a lap: 0.5% is about 0.45 seconds.') + '</div>' + '<div id="vl-body">' + PD.empty('Loading', '') + '</div>';
  if (tab === 'swap') return swap(el, q);
  if (tab === 'needs') return needs(el);
  return value(el, y);
}

// ── driver value ──────────────────────────────────────────────────────────

function value(el, y) {
  return (y >= 1994 ? PD.load(y + '/value.json') : Promise.resolve({ ok: false, reason: 'the decomposition starts in 1994' })).then(function (d) {
    if (!PD.alive(el)) return;
    if (!PD.ok(d) || !d.drivers) { PD.set('vl-body', PD.notBuilt('The ' + y + ' value table', d) + (y < 1994 ? PD.muted('The decomposition starts in 1994, when lap times begin.') : '')); return; }
    var D = PD.rowsOf(d.driver_cols, d.drivers), T = PD.rowsOf(d.team_cols, d.teams);
    var minR = d.min_races || 5;
    var full = D.filter(function (r) { return (r.races || 0) >= minR; });
    var best = full.slice().sort(function (a, b) { return b.pace_tm - a.pace_tm; })[0];
    var pkg = full.slice().sort(function (a, b) { return b.pace_field - a.pace_field; })[0];
    var car = T.slice().sort(function (a, b) { return b.car - a.car; })[0];
    var riser = full.filter(function (r) { return isNum(r.trend); }).sort(function (a, b) { return b.trend - a.trend; })[0];
    var h = PD.kpis([
      PD.kpi('Best driver', best ? PD.driverLink(best.id, { name: best.name, team: best.team }) : '—', best ? pl(best.pace_tm, 2) + ' above the team-mate' : '', { text: true }),
      PD.kpi('Fastest package', pkg ? PD.driverLink(pkg.id, { name: pkg.name, team: pkg.team }) : '—', pkg ? pl(pkg.pace_field, 2) + ' above the field' : '', { text: true }),
      PD.kpi('Fastest car', car ? PD.teamLink(car.id) : '—', car ? pl(car.car, 2) + ' at the latest round' : '', { text: true }),
      PD.kpi('Most improved', riser ? PD.driverLink(riser.id, { name: riser.name, team: riser.team }) : '—', riser ? PD.signed(riser.trend, 3) + ' v last season' : 'needs two seasons', { text: true })
    ]);
    h += PD.grid(
      PD.card('The driver and the package', 'Pace above the team-mate (the driver alone) against pace above the field (driver and car now); ' + minR + '+ races. Up and right is better.', PD.chartBox('vl-sc', 440), { span: 8 }) +
      PD.card('Cars', 'Latest race-pace state, % of a lap faster than the field, ±1 se.', PD.chartBox('vl-cars', 440), { span: 4 }) +
      PD.card('Drivers', esc((d.notes || {}).teammate || '') + ' Percentile among drivers with ' + minR + '+ races.', '<div id="vl-d"></div>', { span: 12, flush: true }) +
      PD.card('Constructors by car pace', 'The car part of the decomposition: a random walk from round to round, so upgrades show up as movement.', '<div id="vl-t"></div>', { span: 12, flush: true }), 'pd-mt');
    PD.set('vl-body', h);
    PD.ch.scatter('vl-sc', full.filter(function (r) { return isNum(r.pace_tm) && isNum(r.pace_field); }).map(function (r) {
      return { x: r.pace_tm, y: r.pace_field, name: r.name, short: PD.driverSurname(r.id), colour: PD.teamColour(r.team), href: PD.driverHref(r.id), label: true, size: 12, sub: PD.teamName(r.team) + ' · ' + r.races + ' races' };
    }), { xName: 'Pace above team-mate (% of a lap)', yName: 'Pace above the field', xFmt: function (v) { return PD.signed(v, 2); }, yFmt: function (v) { return PD.signed(v, 2); }, refX: 0, refY: 0, label: 'Driver against package' });
    PD.ch.hbars('vl-cars', T.slice().sort(function (a, b) { return b.car - a.car; }).map(function (r) { return { label: r.name || PD.teamName(r.id), value: r.car, lo: r.car - (r.car_se || 0), hi: r.car + (r.car_se || 0), colour: PD.teamColour(r.id), href: PD.teamHref(r.id), sub: 'Season mean ' + pl(r.car_mean, 2) + ' · last five rounds ' + PD.signed(r.trend, 3) }; }),
      { fmt: function (v) { return PD.signed(v, 2); }, name: 'Car pace', errName: '±1 se', xName: 'Car pace (% of a lap)', label: 'Car pace' });
    PD.table('vl-d', [
      { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { name: v, team: r.team }) + (r.races < minR ? ' <span class="qk-muted">(few races)</span>' : ''); } },
      { key: 'team', label: 'Team', fmt: function (v) { return PD.teamLink(v, { dot: false }); } },
      { key: 'races', label: 'Races', num: true },
      { key: 'pace_tm', label: 'Above team-mate', num: true, pctl: 'pct', tip: 'Race pace: minus the driver effect, % of a lap (± se)', fmt: function (v, r) { return '<b>' + pl(v) + '</b> <span class="qk-muted">±' + PD.num(r.pace_tm_se, 2) + '</span>'; } },
      { key: 'quali_tm', label: 'Quali v team-mate', num: true, fmt: function (v, r) { return pl(v) + ' <span class="qk-muted">±' + PD.num(r.quali_tm_se, 2) + '</span>'; } },
      { key: 'pace_field', label: 'Above the field', num: true, tip: 'The car’s latest race-pace state plus the driver', fmt: function (v) { return pl(v); } },
      { key: 'trend', label: 'Trend', num: true, tip: 'Pace above team-mate v last season', fmt: function (v) { return isNum(v) ? PD.deltaHTML(v, 3) : '—'; } },
      { key: 'points', label: 'Points', num: true, fmt: function (v) { return PD.pts(v); } },
      { key: 'exp_points', label: 'Exp. points', num: true, tip: 'Season total expected by the championship simulation', fmt: function (v) { return PD.num(v, 1); } },
      { key: 'elo_tm', label: 'Elo v TM', num: true, fmt: function (v) { return PD.num(v, 0); } }
    ], D, { sort: { key: 'pace_field', dir: 'desc' }, rank: true });
    PD.table('vl-t', [
      { key: 'rank', label: 'Rank', num: true },
      { key: 'name', label: 'Constructor', sticky: true, fmt: function (v, r) { return PD.teamLink(r.id, { name: v }); } },
      { key: 'car', label: 'Car, latest', num: true, fmt: function (v, r) { return '<b>' + pl(v) + '</b> <span class="qk-muted">±' + PD.num(r.car_se, 2) + '</span>'; } },
      { key: 'car_mean', label: 'Season mean', num: true, fmt: function (v) { return pl(v); } },
      { key: 'quali_car', label: 'Qualifying car', num: true, fmt: function (v) { return pl(v); } },
      { key: 'trend', label: 'Last 5 rounds', num: true, fmt: function (v) { return PD.deltaHTML(v, 3); } },
      { key: 'points', label: 'Points', num: true, fmt: function (v) { return PD.pts(v); } },
      { key: 'p_title', label: 'Title', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v) : '—'; } }
    ], T, { sort: { key: 'rank', dir: 'asc' } });
  });
}

// ── swap simulator ────────────────────────────────────────────────────────

function swap(el, q) {
  var Y = PD.currentSeason();
  return PD.loadAll([Y + '/swap.json', Y + '/value.json']).then(function (res) {
    if (!PD.alive(el)) return;
    var SW = res[0], VAL = res[1];
    if (!PD.ok(SW) || !SW.lineup) { PD.set('vl-body', PD.notBuilt('The ' + Y + ' swap table', SW) + PD.muted('It needs a season still to run: the swaps go through the championship simulation of the remaining rounds.')); return; }
    var L = SW.lineup;
    var nm = function (d) { return (SW.names || {})[d] || PD.driverName(d); };
    var drivers = Object.keys(L).sort(function (a, b) { return (L[a] + a).localeCompare(L[b] + b); });
    var teams = drivers.map(function (d) { return L[d]; }).filter(function (v, i, a) { return a.indexOf(v) === i; });
    var ST = { x: L[q.x] ? q.x : drivers[0], w: null };
    ST.w = L[q.w] && L[q.w] !== L[ST.x] ? q.w : null;
    PD.set('vl-body', PD.card('The swap', esc(SW.label || '') + ' ' + (SW.remaining || []).length + ' sessions left.',
      '<div class="pd-toolbar pd-swap"><label>Driver<select class="qk-select" id="sw-x"></select></label><span class="pd-swap-arrow" aria-hidden="true">→</span><label>Into the car of<select class="qk-select" id="sw-t"></select></label><label>Replacing<select class="qk-select" id="sw-w"></select></label>' +
      '<button type="button" class="qk-btn" id="sw-share">Copy link</button></div>') + '<div id="sw-out" class="pd-mt"></div>');
    var fill = function () {
      var sx = document.getElementById('sw-x'), st = document.getElementById('sw-t'), sw = document.getElementById('sw-w');
      sx.innerHTML = teams.map(function (t) { return '<optgroup label="' + esc(PD.teamName(t)) + '">' + drivers.filter(function (d) { return L[d] === t; }).map(function (d) { return '<option value="' + esc(d) + '"' + (d === ST.x ? ' selected' : '') + '>' + esc(nm(d)) + '</option>'; }).join('') + '</optgroup>'; }).join('');
      var others = teams.filter(function (t) { return t !== L[ST.x]; });
      if (!ST.w || L[ST.w] === L[ST.x]) ST.w = drivers.filter(function (d) { return L[d] === others[0]; })[0] || null;
      var ty = ST.w ? L[ST.w] : others[0];
      st.innerHTML = others.map(function (t) { return '<option value="' + esc(t) + '"' + (t === ty ? ' selected' : '') + '>' + esc(PD.teamName(t)) + '</option>'; }).join('');
      sw.innerHTML = drivers.filter(function (d) { return L[d] === ty; }).map(function (d) { return '<option value="' + esc(d) + '"' + (d === ST.w ? ' selected' : '') + '>' + esc(nm(d)) + '</option>'; }).join('');
    };
    var out = function () {
      PD.setHashQuiet('#/value' + PD.qs({ tab: 'swap', x: ST.x, w: ST.w }));
      var box = document.getElementById('sw-out');
      if (!box) return;
      if (!ST.x || !ST.w) { box.innerHTML = PD.muted('Pick a driver and a seat.'); return; }
      var a = ST.x < ST.w ? ST.x : ST.w, b = ST.x < ST.w ? ST.w : ST.x;
      var v = (SW.pairs || {})[a + '|' + b];
      if (!v) { box.innerHTML = PD.muted('This pair was not simulated.'); return; }
      var mine = ST.x === a;
      var dd = { x: mine ? v.slice(0, 3) : v.slice(3, 6), w: mine ? v.slice(3, 6) : v.slice(0, 3), tx: mine ? v.slice(6, 8) : v.slice(8, 10), ty: mine ? v.slice(8, 10) : v.slice(6, 8) };
      var P = SW.published || {}, pd = P.drivers || {}, pt = P.constructors || {};
      var tx = L[ST.x], ty = L[ST.w];
      var clip = function (z) { return Math.max(0, Math.min(1, z)); };
      var eff = SW.drv_effect || {};
      var vcar = {};
      if (PD.ok(VAL) && VAL.teams) PD.rowsOf(VAL.team_cols, VAL.teams).forEach(function (r) { vcar[r.id] = r; });
      var rows = [
        { label: nm(ST.x) + ' (to ' + PD.teamName(ty) + ')', now: (pd[ST.x] || [])[0], then: (pd[ST.x] || [])[0] + dd.x[0], kind: 'd', id: ST.x, team: ty, title: [(pd[ST.x] || [])[1], clip((pd[ST.x] || [])[1] + dd.x[1])], pos: [(pd[ST.x] || [])[2], (pd[ST.x] || [])[2] + dd.x[2]] },
        { label: nm(ST.w) + ' (to ' + PD.teamName(tx) + ')', now: (pd[ST.w] || [])[0], then: (pd[ST.w] || [])[0] + dd.w[0], kind: 'd', id: ST.w, team: tx, title: [(pd[ST.w] || [])[1], clip((pd[ST.w] || [])[1] + dd.w[1])], pos: [(pd[ST.w] || [])[2], (pd[ST.w] || [])[2] + dd.w[2]] },
        { label: PD.teamName(ty), now: (pt[ty] || [])[0], then: (pt[ty] || [])[0] + dd.ty[0], kind: 't', id: ty, title: [(pt[ty] || [])[1], clip((pt[ty] || [])[1] + dd.ty[1])] },
        { label: PD.teamName(tx), now: (pt[tx] || [])[0], then: (pt[tx] || [])[0] + dd.tx[0], kind: 't', id: tx, title: [(pt[tx] || [])[1], clip((pt[tx] || [])[1] + dd.tx[1])] }
      ];
      box.innerHTML = PD.grid(
        PD.card('Expected season points', 'Now (grey) against with the swap (colour).', PD.chartBox('sw-ch', 300), { span: 7 }) +
        PD.card('What moves', '', '<div id="sw-t2"></div>', { span: 5, flush: true })) +
        PD.note(esc(nm(ST.x)) + ': pace above team-mate ' + (isNum(eff[ST.x]) ? PD.signed(-eff[ST.x], 3) + '%' : '—') + '; ' + esc(nm(ST.w)) + ': ' + (isNum(eff[ST.w]) ? PD.signed(-eff[ST.w], 3) + '%' : '—') +
          '. Car pace, latest: ' + esc(PD.teamName(tx)) + ' ' + (vcar[tx] && isNum(vcar[tx].car) ? PD.signed(vcar[tx].car, 3) + '%' : '—') + ', ' + esc(PD.teamName(ty)) + ' ' + (vcar[ty] && isNum(vcar[ty].car) ? PD.signed(vcar[ty].car, 3) + '%' : '—') +
          ' (% of a lap, positive = faster). Each pair: ' + (SW.n || '') + ' championship simulations with the same random numbers as a baseline run; the change is added to the published championship. Points already scored stay with whoever scored them.');
      PD.ch.columns('sw-ch', { cats: rows.map(function (r) { return r.kind === 'd' ? PD.driverSurname(r.id) : PD.teamAbbr(r.id); }),
        series: [{ name: 'Now', data: rows.map(function (r) { return r.now; }), colour: PD.col('grey'), fmt: function (z) { return PD.num(z, 1); } },
          { name: 'With the swap', data: rows.map(function (r) { return r.then; }), colours: rows.map(function (r) { return PD.teamColour(r.kind === 'd' ? r.team : r.id); }), fmt: function (z) { return PD.num(z, 1); } }],
        fmt: function (z) { return PD.num(z, 0); }, yName: 'Expected points', tipLabel: function (i) { return rows[i].label; }, label: 'Swap result' });
      PD.table('sw-t2', [
        { key: 'label', label: '', sticky: true, sort: false, fmt: function (z, r) { return r.kind === 'd' ? PD.driverLink(r.id, { team: r.team }) : PD.teamLink(r.id); } },
        { key: 'chg', label: 'Points', num: true, sort: false, fmt: function (z, r) { return PD.num(r.now, 1) + ' → <b>' + PD.num(r.then, 1) + '</b> ' + PD.deltaHTML(r.then - r.now, 1); } },
        { key: 'ttl', label: 'Title', num: true, sort: false, fmt: function (z, r) { return PD.pct(r.title[0], 1) + ' → <b>' + PD.pct(r.title[1], 1) + '</b>'; } },
        { key: 'ps', label: 'Final pos', num: true, sort: false, fmt: function (z, r) { return r.pos ? PD.num(r.pos[0], 1) + ' → <b>' + PD.num(r.pos[1], 1) + '</b>' : ''; } }
      ], rows);
    };
    fill(); out();
    document.getElementById('sw-x').onchange = function (e) { ST.x = e.target.value; if (L[ST.w] === L[ST.x]) ST.w = null; fill(); out(); };
    document.getElementById('sw-t').onchange = function (e) { var t = e.target.value; ST.w = drivers.filter(function (d) { return L[d] === t; })[0] || null; fill(); out(); };
    document.getElementById('sw-w').onchange = function (e) { ST.w = e.target.value; out(); };
    document.getElementById('sw-share').onclick = function () {
      var link = location.href;
      try { navigator.clipboard.writeText(link); this.textContent = 'Copied'; } catch (e) { window.prompt('Link to this swap', link); }
    };
  });
}

// ── team needs ────────────────────────────────────────────────────────────

function needs(el) {
  var Y = PD.currentSeason();
  return PD.load(Y + '/needs.json').then(function (d) {
    if (!PD.alive(el)) return;
    if (!PD.ok(d) || !d.teams) { PD.set('vl-body', PD.notBuilt('The ' + Y + ' needs table', d)); return; }
    var ids = Object.keys(d.teams);
    var areas = [];
    ids.forEach(function (t) { (d.teams[t].areas || []).forEach(function (a) { if (!areas.some(function (x) { return x.key === a.key; })) areas.push({ key: a.key, label: a.label }); }); });
    var data = [];
    ids.forEach(function (t, yi) { (d.teams[t].areas || []).forEach(function (a) { data.push([areas.map(function (x) { return x.key; }).indexOf(a.key), yi, a.pct]); }); });
    var moves = [];
    ids.forEach(function (t) { (d.teams[t].best_swaps || []).forEach(function (s) { moves.push(Object.assign({ to: t }, s)); }); });
    PD.set('vl-body', PD.note(esc(d.label || '')) + PD.grid(
      PD.card('Every team, graded', 'Percentile against the other teams in each area (100 = best).', PD.chartBox('nd-heat', 420), { span: 12 }) +
      PD.card('The best moves', 'The driver swaps that would add the most expected constructors’ points to the receiving team, across the grid.', '<div id="nd-moves"></div>', { span: 12, flush: true }), 'pd-mt'));
    PD.ch.heat('nd-heat', { xs: areas.map(function (a) { return a.label.replace(/ \(.*\)$/, '').replace('Development through the season', 'Development'); }), ys: ids.map(function (t) { return d.teams[t].name || PD.teamName(t); }), xName: 'Area', yName: 'Constructor', data: data, hrefs: ids.map(PD.teamHref),
      fmt: function (v) { return PD.num(v, 0); }, diverging: true, mid: 50, label: 'Team needs heatmap' });
    PD.table('nd-moves', [
      { key: 'to', label: 'Team', sticky: true, fmt: function (v) { return PD.teamLink(v); } },
      { key: 'in_name', label: 'In', fmt: function (v, r) { return PD.driverLink(r.in, { name: v }); } },
      { key: 'from', label: 'From', fmt: function (v) { return PD.teamLink(v, { dot: false }); } },
      { key: 'out_name', label: 'Out', fmt: function (v, r) { return PD.driverLink(r.out, { name: v, dot: false }); } },
      { key: 'gain_pts', label: 'Team points', num: true, fmt: function (v) { return '<b class="' + (v >= 0 ? 'pd-up' : 'pd-down') + '">' + PD.signed(v, 1) + '</b>'; } },
      { key: 'gain_title', label: 'Title', num: true, fmt: function (v) { return PD.signed(100 * v, 1) + ' pts'; } },
      { key: 'other_change', label: 'Seller', num: true, fmt: function (v) { return PD.signed(v, 1); } },
      { key: 'sim', label: '', sort: false, fmt: function (v, r) { return '<a class="pd-link" href="#/value?tab=swap&x=' + encodeURIComponent(r.in) + '&w=' + encodeURIComponent(r.out) + '">Simulate →</a>'; } }
    ], moves, { sort: { key: 'gain_pts', dir: 'desc' }, maxHeight: 560 });
  });
}

PD.route('value', render);
})(window.PD);
