/* The Quant Scrum — Fixtures (upcoming tests with our chances, results with our pre-match call, the archive by year)
 * and the match page (the forecast against the result, the score by half, both team stat lines, both matchday 23s,
 * the key moments and the score race, the World Rugby points exchange). Reads <S>/fixtures.json, <S>/years/<Y>.json,
 * <S>/matches/<id>.json. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;

function compChips(list, active) {
  var seen = {}, keys = [];
  list.forEach(function (c) { if (c.comp && !seen[c.comp]) { seen[c.comp] = 1; keys.push(c.comp); } });
  if (keys.length < 2) return '';
  return '<div class="qk-chips sc-filters" id="fx-comp" role="group" aria-label="Competition"><button type="button" class="qk-chip" data-v=""' + (!active ? ' aria-pressed="true"' : ' aria-pressed="false"') + '>All</button>' +
    keys.map(function (k) { return '<button type="button" class="qk-chip" data-v="' + esc(k) + '" aria-pressed="' + (active === k) + '">' + esc(SC.compName(k)) + '</button>'; }).join('') + '</div>';
}

function byDay(S, list) {
  var out = '', day = null;
  list.forEach(function (c) {
    var d = SC.date(c.date);
    if (d !== day) { if (day !== null) out += '</div>'; day = d; out += '<div class="sc-day"><b>' + esc(d) + '</b></div><div class="qk-watch sc-watch">'; }
    var why = isNum(c.m) ? SC.margin(S, c) + (c.p && isNum(c.p[1]) && c.p[1] >= 0.03 ? ' · draw ' + SC.pct(c.p[1]) : '') + (isNum(c.t) ? ' · about ' + Math.round(c.t) + ' points' : '') : (c.venue || '');
    if (c.ref) why = (why ? why + ' · ' : '') + 'referee ' + c.ref;
    out += QK.gameCard(SC.game(S, c), { sport: false, homeFirst: true, why: why || false, market: false, form: false });
  });
  return out + (day !== null ? '</div>' : '');
}

function resultsTable(S, list, o) {
  o = o || {};
  var cols = [{ label: 'Date', align: 'left' }, { label: 'Competition', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Score' },
    { label: 'Away', align: 'left' }, { label: 'Our call', align: 'left' }, { label: 'Right?', align: 'left' }];
  var rows = list.map(function (c) {
    var p = c.p || [];
    var call = '—', right = '';
    if (isNum(p[0])) {
      var hf = p[0] >= p[2];
      call = SC.tabbr(S, hf ? c.home : c.away) + ' ' + SC.pct(hf ? p[0] : p[2]);
      if (isNum(c.hs)) {
        var won = c.hs === c.as ? null : (c.hs > c.as) === hf;
        right = won === null ? '<span class="qk-muted">Draw</span>' : won ? '<span class="sc-yes">Yes</span>' : '<span class="sc-no">Upset</span>';
      }
    }
    return [{ v: c.date, html: '<a href="' + esc(SC.matchHref(S, c.id)) + '">' + esc(SC.date(c.date)) + '</a>' }, { v: c.comp, html: esc(SC.compName(c.comp)) },
      { v: SC.tname(S, c.home), html: U.teamEnt(S, c.home) }, { v: (c.hs || 0) - (c.as || 0), html: '<a class="sc-score" href="' + esc(SC.matchHref(S, c.id)) + '">' + SC.scoreText(c.hs, c.as, c.ro) + '</a>' },
      { v: SC.tname(S, c.away), html: U.teamEnt(S, c.away) }, { v: isNum(p[0]) ? Math.max(p[0], p[2]) : -1, html: esc(call) }, { v: right, html: right || '—' }];
  });
  return U.table(cols, rows, { cls: 'sc-results', maxHeight: o.maxHeight || 720 });
}

SC.route('fixtures', function (page, P) {
  var S = P.S, tab = U.tab(P, ['upcoming', 'results', 'year'], 'upcoming');
  var comp = (P.query || {}).comp || '';
  page.innerHTML = U.head('Fixtures and results', 'Our chance for every test before it is played, and how each call turned out.', SC.SNAME[S]) +
    U.tabs([{ key: 'upcoming', label: 'Upcoming', href: SC.href(S, 'fixtures') }, { key: 'results', label: 'Results', href: SC.href(S, 'fixtures', null, 'tab=results') },
      { key: 'year', label: 'By year', href: SC.href(S, 'fixtures', null, 'tab=year') }], tab) + '<div id="fx-body">' + QK.skeleton('lines', 6) + '</div>';
  var body = QK.$('#fx-body', page);
  if (tab === 'year') {
    var years = (SC.info(S).years || []).slice().sort(function (a, b) { return b - a; });
    var y = Number((P.query || {}).y) || years[0];
    var sel = '<label class="sc-lab-sel">Year <select class="qk-select" id="fx-year">' + years.map(function (x) { return '<option value="' + x + '"' + (x === y ? ' selected' : '') + '>' + x + '</option>'; }).join('') + '</select></label>';
    return SC.load(S + '/years/' + y + '.json').then(function (d) {
      if (!U.alive(body)) return;
      if (!SC.ok(d)) { body.innerHTML = sel + U.missing('That year', d); return; }
      var list = (d.matches || []).filter(function (c) { return !comp || c.comp === comp; });
      body.innerHTML = '<div class="sc-toolbar">' + sel + '</div>' + compChips(d.matches || [], comp) + resultsTable(S, list.slice().reverse(), { maxHeight: 900 }) +
        U.note(list.length + ' tests in ' + y + '. "Our call" is the chance we gave the favourite before the start, from results up to that day only.');
      U.wire(body);
      QK.$('#fx-year', body).addEventListener('change', function (e) { SC.go(SC.href(S, 'fixtures', null, 'tab=year&y=' + e.target.value)); });
      wireComp(body, S, 'year&y=' + y);
    });
  }
  return SC.load(S + '/fixtures.json').then(function (d) {
    if (!U.alive(body)) return;
    if (!SC.ok(d)) { body.innerHTML = U.missing('Fixtures', d); return; }
    if (tab === 'results') {
      var rs = (d.results || []).filter(function (c) { return !comp || c.comp === comp; });
      var called = rs.filter(function (c) { return c.p && isNum(c.hs) && c.hs !== c.as; });
      var right = called.filter(function (c) { return (c.hs > c.as) === (c.p[0] >= c.p[2]); }).length;
      var exp = called.reduce(function (a, c) { return a + Math.max(c.p[0], c.p[2]); }, 0);
      body.innerHTML = compChips(d.results || [], comp) + (called.length ? QK.stats([{ label: 'Our favourite won', value: right + ' of ' + called.length, signal: true, sub: 'We expected about ' + Math.round(exp) + '.' },
        { label: 'Upsets', value: String(called.length - right), sub: 'A 70% favourite still loses 3 times in 10.' }]) : '') + resultsTable(S, rs);
      U.wire(body);
      wireComp(body, S, 'results');
      return;
    }
    var up = (d.live || []).concat(d.upcoming || []).filter(function (c) { return !comp || c.comp === comp; });
    body.innerHTML = compChips((d.upcoming || []), comp) + (up.length ? byDay(S, up.slice(0, 60)) : QK.empty('No tests scheduled', 'Fixtures appear here as soon as they are announced.')) +
      U.note('Each card shows our chance for each side before the start; the line under it is the margin and total we expect, and the draw chance where it is above 3%. Neutral venues have no home advantage.');
    wireComp(body, S, '');
  });
});

function wireComp(body, S, tab) {
  var ch = QK.$('#fx-comp', body);
  if (!ch) return;
  ch.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button[data-v]') : null;
    if (!b) return;
    var v = b.getAttribute('data-v');
    SC.go(SC.href(S, 'fixtures', null, [tab ? 'tab=' + tab : '', v ? 'comp=' + v : ''].filter(Boolean).join('&')));
  });
}

/* ── the match page ─────────────────────────────────────────────────── */
var STAT_ROWS = [
  ['Possession', 'poss', 'pct'], ['Territory', 'terr', 'pct'], ['Metres carried', 'metres'], ['Carries', 'carries'], ['Over the gain line', 'gainline'],
  ['Clean breaks', 'breaks'], ['Defenders beaten', 'beaten'], ['Offloads', 'offloads'], ['Passes', 'passes'], ['Tackles', 'tackles'],
  ['Missed tackles', 'missed', null, 'low'], ['Tackle success', 'tackle_pct', 'pct'], ['Rucks won', 'rucks_won'], ['Turnovers won', 'to_won'],
  ['Turnovers conceded', 'to_conc', null, 'low'], ['Knock-ons', 'knock_ons', null, 'low'], ['Scrums won', 'scrums_won'], ['Lineouts won', 'lineouts_won'],
  ['Lineout steals', 'lineout_steals'], ['Maul metres', 'maul_m'], ['Penalties conceded', 'pens', null, 'low'], ['Yellow cards', 'yc', null, 'low'],
  ['Red cards', 'rc', null, 'low'], ['Kicks from hand', 'kicks'], ['Kicking metres', 'kick_m'], ['Goal-kicking success', 'kick_pct', 'pct']
];
var LINE_COLS = [['min', 'Min'], ['pts', 'Pts'], ['tries', 'T'], ['ta', 'TA'], ['m', 'M'], ['car', 'Car'], ['cb', 'CB'], ['db', 'DB'], ['off', 'Off'],
  ['pas', 'Pas'], ['tk', 'Tk'], ['mt', 'MT'], ['lo', 'LO'], ['rk', 'Rk'], ['toc', 'TO'], ['pc', 'Pen'], ['kfh', 'Kicks'], ['yc', 'YC']];

function lineTable(S, rows, tid, stats) {
  /* a test our source has line-ups for but no player statistics: the team sheet and the minutes only, never a row of zeros */
  var lc = stats ? LINE_COLS : LINE_COLS.slice(0, 1);
  var cols = [{ label: '#', align: 'left' }, { label: 'Player', align: 'left', sticky: true }, { label: 'Pos', align: 'left' }].concat(lc.map(function (c) { return { label: c[1] }; }))
    .concat(stats ? [{ label: 'Value' }] : []);
  var trs = rows.map(function (r) {
    var s = r.s || {};
    return [{ v: r.j || 99, html: esc(r.j || '') }, { v: r.n, html: '<a href="' + esc(SC.playerHref(S, r.id)) + '">' + esc(r.n) + '</a>' + (r.c ? ' <span class="sc-capt" title="Captain">C</span>' : '') },
      { v: r.pos, html: '<span title="' + esc(SC.posName(r.pos)) + '">' + esc(r.pos || '') + '</span>' }].concat(lc.map(function (c) {
      var v = c[0] === 'min' ? r.min : s[c[0]];
      return { v: isNum(v) ? v : -1, html: isNum(v) ? (c[0] === 'min' && r.est ? '<span title="Estimated: no substitutions in the feed">~' + v + '</span>' : String(v)) : '<span class="qk-muted">0</span>' };
    })).concat(stats ? [{ v: isNum(r.gv) ? r.gv : -99, html: isNum(r.gv) ? '<span class="sc-ours ' + SC.cls(r.gv) + '">' + SC.signed(r.gv, 1) + '</span>' : '—' }] : []);
  });
  return U.table(cols, trs, { cls: 'sc-lines dense', maxHeight: 900 });
}

/* our home-win chance through the test (pages.win_chance_path) */
function winPath(el, S, M) {
  if (!el || !window.QKC || !M.wp || M.wp.length < 3) return;
  var c = M.match, cols = SC.lineColours(S, [c.home, c.away]);
  QKC.line(el, { x: M.wp.map(function (p) { return p[0]; }), xType: 'value', step: 'end', series: [{ name: SC.tabbr(S, c.home) + ' win chance', data: M.wp.map(function (p) { return Math.round(p[1] * 1000) / 10; }), color: cols[0], step: 'end' }],
    yName: SC.tname(S, c.home) + ' win chance (%)', xName: 'Minute', yMin: 0, yMax: 100, ref: { y: 50, label: 'Even' }, endLabels: false, yFmt: function (v) { return Math.round(v) + '%'; } });
}

/* who made the difference: the test's best and worst by game value (our value model on the player's own numbers) */
function difference(S, M) {
  if (!M.lines || !M.has_stats) return '';
  var all = [];
  ['h', 'a'].forEach(function (k) { (M.lines[k] || []).forEach(function (r) { if (isNum(r.gv)) all.push({ r: r, tid: k === 'h' ? M.match.home : M.match.away }); }); });
  if (all.length < 6) return '';
  all.sort(function (a, b) { return b.r.gv - a.r.gv; });
  var row = function (x) {
    var s = x.r.s || {}, bits = [];
    if (s.tries) bits.push(s.tries + (s.tries === 1 ? ' try' : ' tries'));
    if (s.m) bits.push(s.m + ' m');
    if (s.cb) bits.push(s.cb + ' breaks');
    if (s.tk) bits.push(s.tk + ' tackles');
    if (s.pc) bits.push(s.pc + (s.pc === 1 ? ' penalty' : ' penalties'));
    return '<li>' + QK.teamMark(SC.mark(S, x.tid), 'sm') + '<a href="' + esc(SC.playerHref(S, x.r.id)) + '">' + esc(x.r.n) + '</a><span class="s">' + esc(SC.posName(x.r.pos)) + (bits.length ? ' · ' + esc(bits.slice(0, 3).join(', ')) : '') + '</span><span class="v ' + SC.cls(x.r.gv) + '">' + SC.signed(x.r.gv, 1) + '</span></li>';
  };
  return '<div class="qk-g2 sc-gap">' + U.card('Who made the difference', 'The test’s top five by game value: our value model on each player’s own numbers, in points of margin above a replacement-level player of the position over the same minutes.', '<ul class="sc-list">' + all.slice(0, 5).map(row).join('') + '</ul>') +
    U.card('A test to forget', 'The bottom five on the same scale (penalties, turnovers and missed tackles cost points).', '<ul class="sc-list">' + all.slice(-5).reverse().map(row).join('') + '</ul>') + '</div>';
}

function scoreRace(el, S, M) {
  var ev = (M.events || []).filter(function (e) { return e[1] === 'try' || e[1] === 'con' || e[1] === 'pg' || e[1] === 'dg'; });
  if (!el || !window.QKC || ev.length < 2) return;
  var x = [0], h = [0], a = [0];
  ev.forEach(function (e) { if (isNum(e[0]) && isNum(e[5])) { x.push(e[0]); h.push(e[5]); a.push(e[6]); } });
  x.push(80); h.push(h[h.length - 1]); a.push(a[a.length - 1]);
  var cols = SC.lineColours(S, [M.match.home, M.match.away]);
  QKC.line(el, { x: x, xType: 'value', step: 'end', series: [{ name: SC.tname(S, M.match.home), data: h, color: cols[0], step: 'end' }, { name: SC.tname(S, M.match.away), data: a, color: cols[1], step: 'end' }],
    yName: 'Points', xName: 'Minute', endLabels: true, yFmt: function (v) { return String(Math.round(v)); } });
}

/* referee, venue, altitude, weather and crowd (Wikipedia, Open-Meteo); the forecast as issued for an upcoming test */
function conditions(S, M) {
  var c = M.match, items = [], V = M.venue || {}, W = M.weather || {};
  if (M.referee) items.push({ label: 'Referee', value: M.referee.name, sub: (M.referee.union ? M.referee.union + ' · ' : '') + '<a class="qk-link" href="' + esc(SC.href(S, 'model', null, 'tab=refs&ref=' + encodeURIComponent(M.referee.k))) + '">tendencies</a>', html: true });
  if (V.place || isNum(V.elev)) items.push({ label: 'Venue', value: isNum(V.elev) ? fmt.num(V.elev) + ' m' : '—', sub: (V.place ? esc(V.place) : '') + (V.alt ? ' · at altitude: the visitors come up from lower ground' : (isNum(V.elev) ? ' · above sea level' : '')), html: true });
  if (isNum(W.temp)) {
    var fc = W.kind === 'forecast';
    items.push({ label: fc ? 'Forecast at kick-off' : 'Weather at kick-off', value: Math.round(W.temp) + '°C', sub: [isNum(W.wind) ? 'wind ' + Math.round(W.wind) + ' km/h' + (isNum(W.gust) ? ' (gusts ' + Math.round(W.gust) + ')' : '') : '', isNum(W.rain) ? (W.rain >= 0.1 ? W.rain + ' mm of rain' : 'dry') : '', isNum(W.rh) ? W.rh + '% humidity' : ''].filter(Boolean).join(', ') + (fc ? ' (forecast as issued)' : '') });
  }
  if (isNum(M.attendance) && M.attendance > 0) items.push({ label: 'Crowd', value: fmt.num(M.attendance), sub: '' });
  var out = items.length ? QK.stats(items) : '';
  var notes = [];
  if (M.ro) notes.push('<b>' + esc(c.hs > c.as ? SC.tname(S, c.home) + ' won.' : c.hs < c.as ? SC.tname(S, c.away) + ' won.' : 'A draw.') + '</b> Before 1891 the four home unions counted goals and tries with no common points system, so this test carries the result only.');
  if (M.source && M.source.name === 'Sofascore') notes.push('Result' + (M.stats ? ' and team statistics' : '') + ' from Sofascore' + (M.source.page ? ' (' + esc(M.source.page) + ')' : '') + '; our main source has no record of this test, so there are no line-ups.');
  else if (M.source) notes.push('Result from Wikipedia (“' + esc(M.source.page) + '”, ' + esc(M.source.licence) + '); our main source has no record of this test, so there are no line-ups or statistics.');
  if (M.stat_src && !(M.source && M.source.name === 'Sofascore')) notes.push('Statistics for this test from ' + esc(M.stat_src) + ': our main source has the result and line-ups but no statistics.');
  if (W.temp !== undefined) notes.push('<a href="https://open-meteo.com/" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a> (CC BY 4.0)' + (W.kind === 'forecast' ? '' : ': the hours of the match from the ERA5 reanalysis. It is known only after the match, so it never enters our pre-match numbers.'));
  return out + (notes.length ? U.note(notes.join(' ')) : '');
}

var EV_WORD = { 'try': 'Try', con: 'Conversion', pg: 'Penalty goal', dg: 'Drop goal', yc: 'Yellow card', rc: 'Red card', on: 'On', off: 'Off' };

SC.route('match', function (page, P) {
  var S = P.S;
  page.innerHTML = QK.skeleton('card', 2);
  return SC.load(S + '/matches/' + P.id + '.json').then(function (M) {
    if (!SC.ok(M)) { page.innerHTML = U.head('Match', '', SC.SNAME[S]) + U.missing('This match page', M); return; }
    var c = M.match, g = SC.game(S, c), F = M.forecast || {};
    var factors = [];
    if (F.rating) factors.push({ label: 'Our rating', a: SC.signed(F.rating[1], 1), b: SC.signed(F.rating[0], 1), better: F.rating[0] >= F.rating[1] ? 'b' : 'a' });
    if (F.exp) factors.push({ label: 'Expected points', a: SC.f(F.exp[1], 0), b: SC.f(F.exp[0], 0), better: F.exp[0] >= F.exp[1] ? 'b' : 'a' });
    if (F.travel_km) factors.push({ label: 'Travel (km)', a: fmt.num(F.travel_km[1]), b: fmt.num(F.travel_km[0]), better: F.travel_km[0] <= F.travel_km[1] ? 'b' : 'a' });
    var days = function (d) { return d >= 99 ? '99+' : String(Math.round(d)); };
    if (F.rest && isNum(F.rest[0]) && isNum(F.rest[1])) factors.push({ label: 'Days since last test', a: days(F.rest[1]), b: days(F.rest[0]), better: '' });
    var kick = SC.compName(c.comp) + (c.venue ? ' · ' + c.venue : '') + (c.neutral ? ' · neutral' : '');
    var html = '<nav class="sc-crumb"><a href="' + esc(SC.href(S, 'fixtures')) + '">Fixtures</a> / ' + esc(SC.date(c.date)) + '</nav>';
    var extra = isNum(F.margin) ? 'We expected ' + esc(SC.tname(S, F.margin >= 0 ? c.home : c.away)) + ' by about ' + Math.max(1, Math.round(Math.abs(F.margin))) +
      (isNum(F.total) ? ' in a ' + Math.round(F.total) + '-point test' : '') + '.' : '';
    html += QK.previewCard(g, { kicker: kick, noun: 'test', homeFirst: true, factors: factors, factorsTitle: 'How they matched up before the start', noteExtra: extra });
    // the result against the forecast
    if (c.status === 'final' && F.p && !c.ro) {
      var hw = c.hs > c.as, dr = c.hs === c.as, pw = hw ? F.p[0] : dr ? F.p[1] : F.p[2];
      var mg = c.hs - c.as;
      var verdict = dr ? 'A draw, which we had at ' + SC.pct(F.p[1]) + '.' : (pw >= 0.5 ? 'As expected: ' : pw >= 0.4 ? 'A near coin flip: ' : 'An upset: ') + esc(SC.tname(S, hw ? c.home : c.away)) + ' won at ' + SC.pct(pw) + ' in our numbers.';
      html += QK.stats([{ label: 'Our pre-match chance for the winner', value: SC.pct(pw), signal: true, sub: verdict, html: true },
        { label: 'Margin', value: SC.signed(mg, 0), sub: 'We expected ' + SC.signed(F.margin, 1) + ' (home side first).' },
        { label: 'Total', value: String(c.hs + c.as), sub: isNum(F.total) ? 'We expected ' + Math.round(F.total) + '.' : '' },
        M.halves ? { label: 'Half-time' + (M.halves_est ? ' (from the scoring)' : ''), value: (M.halves[0][0] || 0) + '–' + (M.halves[1][0] || 0), sub: 'Second half ' + ((M.halves[0][1] || 0) - (M.halves[0][0] || 0)) + '–' + ((M.halves[1][1] || 0) - (M.halves[1][0] || 0)) } : null,
        M.wr ? { label: 'World Rugby points', value: SC.signed(M.wr.x, 2), sub: SC.tname(S, c.home) + ' took ' + SC.signed(M.wr.x, 2) + ' from ' + SC.tname(S, c.away) + ' (our replica; ' + SC.f(M.wr.before[0], 2) + ' v ' + SC.f(M.wr.before[1], 2) + ' before).' } : null]);
    } else if (M.wr === undefined && F.p) {
      html += '';
    }
    html += conditions(S, M);
    var moments = M.events && M.events.length ? U.card('Key moments', 'Tries, kicks, cards and changes as the feed records them.', '<ol class="sc-events">' + M.events.filter(function (e) { return e[1] !== 'on' && e[1] !== 'off'; }).map(function (e) {
      var tid = e[2] === 'h' ? c.home : c.away;
      return '<li class="ev-' + esc(e[1]) + '"><span class="mn num">' + (isNum(e[0]) ? e[0] + '’' : '') + '</span>' + QK.teamMark(SC.mark(S, tid), 'sm') + '<span class="w">' + esc(EV_WORD[e[1]] || e[1]) + '</span>' +
        (e[3] ? '<a href="' + esc(SC.playerHref(S, e[3])) + '">' + esc(e[4] || '') + '</a>' : '<span>' + esc(e[4] || '') + '</span>') + (isNum(e[5]) ? '<span class="sc num">' + e[5] + '–' + e[6] + '</span>' : '') + '</li>';
    }).join('') + '</ol>') : '';
    var flow = (M.events && M.events.length >= 2 ? U.card('The score, minute by minute', 'Each side’s points through the match, from the scoring events.', U.chart('mt-race', 280, 'Score by minute')) : '') +
      (M.wp ? U.card('Our win chance through the test', 'From our pre-match margin and spread and the score at each scoring event: the time left shrinks the spread. 50% is even.', U.chart('mt-wp', 240, 'Win chance by minute')) : '');
    if (!M.stats && (flow || moments)) html += '<div class="qk-g2 sc-gap"><div>' + flow + '</div><div>' + moments + '</div></div>';
    if (M.stats) {
      var hs = M.stats.home, as = M.stats.away;
      var rows = STAT_ROWS.filter(function (r) { return isNum(hs[r[1]]) && isNum(as[r[1]]); }).map(function (r) {
        var pc = r[2] === 'pct', f = pc ? function (v) { return Math.round(v * 100) + '%'; } : function (v) { return fmt.num(v); };
        return { label: r[0], a: hs[r[1]], b: as[r[1]], fmt: f, better: r[3] === 'low' ? 'low' : 'high' };
      });
      html += '<div class="qk-g2 sc-gap">' + U.card('Tale of the tape', 'The two team stat lines. The better number in each row is solid.',
        QK.matchupBar({ left: Object.assign(SC.side(S, c.home), { abbr: SC.tabbr(S, c.home) }), right: Object.assign(SC.side(S, c.away), { abbr: SC.tabbr(S, c.away) }), rows: rows })) +
        '<div>' + flow + moments + '</div></div>';
    }
    html += difference(S, M);
    if (M.lines) {
      if (!M.has_stats) html += U.note('Our source has the line-ups for this test but no player statistics, so the team sheets below show the minutes only.');
      ['h', 'a'].forEach(function (k) {
        var tid = k === 'h' ? c.home : c.away;
        if (!M.lines[k]) return;
        html += U.card(SC.tname(S, tid) + ': the matchday 23', 'Starters 1-15, then the replacements. Minutes come from the substitutions; "~" marks an estimate where the feed has none.' + (M.has_stats ? ' Value is the player’s game value (see above).' : ''), lineTable(S, M.lines[k], tid, !!M.has_stats), { flush: true });
      });
    } else if (c.status === 'final' && !M.source) {
      html += U.note('Our source has no line-ups or player statistics for this match.');
    }
    if (F.p && c.status !== 'final') {
      html += QK.explain('<b>How we got there.</b> Our rating gap with home advantage (' + (c.neutral ? 'none: a neutral venue' : 'about ' + SC.f(F.edge, 1) + ' points for the home side, travel and rest included') +
        '), then a normal spread of margins around it. <a class="qk-link" href="' + esc(SC.href(S, 'model')) + '">The method</a>.');
    }
    page.innerHTML = html;
    U.wire(page);
    scoreRace(QK.$('#mt-race', page), S, M);
    winPath(QK.$('#mt-wp', page), S, M);
    document.title = SC.tabbr(S, c.home) + ' v ' + SC.tabbr(S, c.away) + ' · ' + SC.SITE;
  });
});
})();
