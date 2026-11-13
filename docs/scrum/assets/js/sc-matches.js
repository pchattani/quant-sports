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

/* ── the match page (v4, as the Rink's game page) ──────────────────────
 * The hero (QK.previewCard) with the forecast panel beside it: our win, draw and loss, the expected margin with its
 * spread as a likely-range bar (8 tests in 10, from the model's own sd), the expected total and the projected score,
 * as of the build. Under it the tale of the tape (QK.tape: the ratings the forecast used, then each side's last two
 * years per test with percentiles before the start, or the test's own stat lines after it) beside the form card
 * (QK.formPair: each side's last five tests before this one, and the head to head) and, before the start, the key
 * players (the best by Scrum value in each side's last matchday). Reads the match file, both team files and teams.json
 * (the metric names); a finished test shows only results dated before it in its form. */
var Z80 = 1.2816;   /* the middle 80% of a normal spread */
var TAPE_IDS = ['pf', 'pa', 'tf', 'ta', 'metres', 'breaks', 'gainline', 'tackle_pct', 'to_won', 'ruck_pct', 'scrum_pct', 'lineout_pct', 'pens', 'kick_pct'];
function mWord(S, c, x) { return !isNum(x) ? '—' : Math.abs(x) < 0.5 ? 'level' : SC.tabbr(S, x > 0 ? c.home : c.away) + ' by ' + Math.round(Math.abs(x)); }
function tfmt(m, v) {
  if (!isNum(v)) return '—';
  if (m && m.unit === '%') return Math.round(v * 100) + '%';
  return Math.abs(v) >= 100 ? fmt.num(v, 0) : fmt.num(v, 1);
}

function forecastSide(S, M) {
  var c = M.match, F = M.forecast || {}, p = F.p || c.p || [];
  if (!isNum(p[0])) return '';
  var fin = c.status === 'final';
  var H = SC.tabbr(S, c.home), A = SC.tabbr(S, c.away);
  var mg = isNum(F.margin) ? F.margin : c.m, tot = isNum(F.total) ? F.total : c.t, sd = F.sd;
  var lo = isNum(mg) && isNum(sd) ? mg - Z80 * sd : null, hi = isNum(lo) ? mg + Z80 * sd : null;
  var tiles = [];
  if (isNum(mg)) {
    var w = isNum(lo) ? hi - lo : 0;
    tiles.push({ label: fin ? 'Margin we expected' : 'Expected margin', value: mWord(S, c, mg), text: true, signal: true,
      sub: isNum(lo) ? '8 tests in 10: ' + mWord(S, c, lo) + ' to ' + mWord(S, c, hi) : 'the home side first',
      range: isNum(lo) ? { lo: lo, hi: hi, mid: mg, min: Math.min(0, lo) - 0.12 * w, max: Math.max(0, hi) + 0.12 * w, label: H + ' minus ' + A + ', 8 tests in 10', fmt: function (v) { return SC.signed(v, 0); },
        caption: H + ' minus ' + A + ': ' + SC.signed(lo, 0) + ' to ' + SC.signed(hi, 0) } : null,
      tip: 'Our expected margin, and the middle 80% of the normal spread of margins our model draws around it (its spread: ' + (isNum(sd) ? SC.f(sd, 1) + ' points' : 'not in this build') + ')' });
  }
  if (isNum(tot)) tiles.push({ label: fin ? 'Total we expected' : 'Expected total', value: String(Math.round(tot)), unit: 'pts', sub: 'both sides together' });
  if (F.exp && isNum(F.exp[0])) tiles.push({ label: 'Projected score', value: H + ' ' + Math.round(F.exp[0]) + '–' + Math.round(F.exp[1]) + ' ' + A, text: true, sub: 'our expected points for each side' });
  if (isNum(p[1])) tiles.push({ label: 'Draw', value: SC.pct(p[1], p[1] < 0.1 ? 1 : 0), sub: 'a margin inside half a point' });
  var rows = [[SC.tname(S, c.home) + ' win', SC.pct(p[0])], ['Draw', SC.pct(p[1], p[1] < 0.1 ? 1 : 0)], [SC.tname(S, c.away) + ' win', SC.pct(p[2])]];
  if (isNum(mg)) rows.push(['Expected margin', mWord(S, c, mg) + (isNum(lo) ? ' (8 in 10: ' + mWord(S, c, lo) + ' to ' + mWord(S, c, hi) + ')' : '')]);
  if (isNum(tot)) rows.push(['Expected total', Math.round(tot) + ' points']);
  if (F.exp && isNum(F.exp[0])) rows.push(['Projected score', SC.tname(S, c.home) + ' ' + Math.round(F.exp[0]) + ' – ' + Math.round(F.exp[1]) + ' ' + SC.tname(S, c.away)]);
  if (fin && isNum(c.hs) && !c.ro) {
    var k = c.hs > c.as ? 0 : c.hs < c.as ? 2 : 1;
    rows.push(['What happened', (k === 1 ? 'A draw, ' + c.hs + '–' + c.as : SC.tname(S, k === 0 ? c.home : c.away) + ' won ' + Math.max(c.hs, c.as) + '–' + Math.min(c.hs, c.as)) + ' · we gave that ' + SC.pct(p[k], p[k] < 0.1 ? 1 : 0)]);
  }
  var asof = (SC.index || {}).updated_at;
  var tbl = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Question</th><th>' + (fin ? 'Our pre-match call' : 'Our forecast') + '</th></tr></thead><tbody>' +
    rows.map(function (r) { return '<tr><td>' + esc(r[0]) + '</td><td class="num" style="text-align:left;color:var(--ink-1);font-weight:600;white-space:normal">' + esc(r[1]) + '</td></tr>'; }).join('') + '</tbody></table></div>';
  return '<div class="sc-gside">' + QK.stats(tiles) + U.card(fin ? 'Our pre-match call' : 'Our forecast', fin ? 'What we said before the start, from results up to that day only, against what happened.' :
    'From our ratings model: win, draw and loss, the margin with its spread, the total and the score' + (asof ? '. As of ' + esc(fmt.date(asof) + ' ' + fmt.time(asof)) + '; it moves with every result until the start' : '') + '.', tbl, { flush: true }) + '</div>';
}

/* a test under way or over: a final or live status, or a kick-off already passed (the feed can lag) */
function started(c) {
  if (c.status === 'final' || c.status === 'live') return true;
  var t = Date.parse(String(c.date || ''));
  return isNum(t) && t <= QK.now();
}

/* the tale of the tape. Before the start: the ratings our forecast uses, then each side's last two years per test (the
   team files, as of the latest finished test; the bar is the percentile among test sides). Once it has started: "Going
   in", every row as it stood before the start (the match file's `pre` block: our rank, World Rugby points and the
   profile over the two years before that day; the ratings and the points we expected are the walk-forward forecast's),
   then the test's own stat lines as a separate "In this game" tape. A build without `pre` keeps only the forecast's
   own pre-match rows. */
function tapeHTML(S, M, TH, TA, MET) {
  var c = M.match, F = M.forecast || {}, fin = c.status === 'final', go = started(c), P = M.pre || null;
  var groups = [], pre = [];
  if (F.rating && isNum(F.rating[0])) pre.push({ label: 'Our rating (points v an average side)', a: F.rating[0], b: F.rating[1], ta: SC.signed(F.rating[0], 1), tb: SC.signed(F.rating[1], 1), tip: 'The rating each side carried into this test: points a test better than an average test side' });
  if (F.exp && isNum(F.exp[0])) pre.push({ label: 'Points we expected', a: F.exp[0], b: F.exp[1], ta: SC.f(F.exp[0], 0), tb: SC.f(F.exp[1], 0) });
  var wr = go ? (P && P.wr) : (TH && TA && isNum(TH.wr) && isNum(TA.wr) ? [TH.wr, TA.wr] : null);
  if (wr && isNum(wr[0]) && isNum(wr[1])) pre.push({ label: 'World Rugby points (our rebuild)', a: wr[0], b: wr[1], ta: SC.f(wr[0], 1), tb: SC.f(wr[1], 1), tip: go ? 'Each side’s points in our World Rugby rebuild before this test' : 'Each side’s points in our World Rugby rebuild today' });
  if (pre.length) groups.push({ label: 'Ratings', rows: pre });
  var prow = function (k, x, y) {
    var m = MET[k];
    return { label: m.label, a: x[0], b: y[0], ta: tfmt(m, x[0]), tb: tfmt(m, y[0]), pa: x[1], pb: y[1], better: m.dir === 'lower' ? 'low' : 'high', tip: m.label + (m.unit === '%' ? '' : ', per test') + '; the bar is the opponent-adjusted percentile among test sides' };
  };
  if (go && P && P.profile && P.profile.m) {
    var prs = TAPE_IDS.filter(function (k) { return MET[k] && P.profile.m[k]; }).map(function (k) { return prow(k, P.profile.m[k][0], P.profile.m[k][1]); });
    if (prs.length) groups.push({ label: 'Per test, the two years before (' + P.profile.n[0] + ' and ' + P.profile.n[1] + ' tests)', rows: prs });
  } else if (!go && TH && TA && TH.profile && TA.profile) {
    var rows = TAPE_IDS.filter(function (k) { return MET[k] && TH.profile.m[k] && TA.profile.m[k]; }).map(function (k) {
      var x = TH.profile.m[k], y = TA.profile.m[k];
      return prow(k, [x.v, x.pct], [y.v, y.pct]);
    });
    if (rows.length) groups.push({ label: 'Per test, last two years (' + TH.profile.n + ' and ' + TA.profile.n + ' tests)', rows: rows });
  }
  var rk = function (i, T) {
    if (go) return P && P.rank && isNum(P.rank[i]) ? QK.ordinal(P.rank[i]) + ' in our ratings' : SC.compName(c.comp);
    return T && isNum(T.rank) && T.rank ? QK.ordinal(T.rank) + ' in our ratings' : SC.compName(c.comp);
  };
  var side = function (tid, T, i) {
    var t = SC.team(S, tid) || {};
    return { name: t.name, short: t.abbr || t.name, sub: rk(i, T), colour: t.colour, alt: t.alt, href: SC.teamHref(S, tid) };
  };
  var fav = (F.p || [])[0] >= (F.p || [])[2] ? 'a' : 'b';
  var ctx = [];
  if (F.travel_km) ctx.push('distance from home to the venue ' + SC.tabbr(S, c.home) + ' ' + fmt.num(F.travel_km[0]) + ' km, ' + SC.tabbr(S, c.away) + ' ' + fmt.num(F.travel_km[1]) + ' km');
  var days = function (d) { return d >= 99 ? '99+' : String(Math.round(d)); };
  if (F.rest && isNum(F.rest[0]) && isNum(F.rest[1])) ctx.push('days since the last test ' + days(F.rest[0]) + ' and ' + days(F.rest[1]));
  var note = ctx.length ? U.note(esc(ctx.join('; ').replace(/^./, function (x) { return x.toUpperCase(); })) + '.') : '';
  var out = '';
  if (groups.length) {
    var when = esc(SC.date(c.date));
    out += U.card(go ? 'Going in' : 'Tale of the tape', go ? 'Before ' + when + ': the ratings each side carried in' + (groups.length > 1 ? ', then each side over the two years before, opponent-adjusted (the bar is the percentile among test sides)' : '') + '. Nothing from this test or after it.' :
      'The ratings our forecast uses, then each side over the last two years, opponent-adjusted: the bar is the percentile among test sides.',
      QK.tape({ left: side(c.home, TH, 0), right: side(c.away, TA, 1), groups: groups, fav: fav }) + note);
  }
  if (fin && M.stats) {
    var hs = M.stats.home, as = M.stats.away;
    var srows = STAT_ROWS.filter(function (r) { return isNum(hs[r[1]]) && isNum(as[r[1]]); }).map(function (r) {
      var f = r[2] === 'pct' ? function (v) { return Math.round(v * 100) + '%'; } : function (v) { return fmt.num(v); };
      return { label: r[0], a: hs[r[1]], b: as[r[1]], ta: f(hs[r[1]]), tb: f(as[r[1]]), better: r[3] === 'low' ? 'low' : 'high' };
    });
    if (srows.length) {
      var gs = function (tid) { var t = SC.team(S, tid) || {}; return { name: t.name, short: t.abbr || t.name, sub: tid === c.home ? String(c.hs) + ' points' : String(c.as) + ' points', colour: t.colour, alt: t.alt, href: SC.teamHref(S, tid) }; };
      out += U.card('In this game', 'The two stat lines from the test; the better side of each row is solid.',
        QK.tape({ left: gs(c.home), right: gs(c.away), groups: [{ label: 'The test itself', rows: srows }], fav: c.hs >= c.as ? 'a' : 'b' }));
    }
  }
  return out;
}

/* each side's last five tests before this one and the head to head. Once the test has started both come from the
   match file's `pre` block (every test dated before the start); a build without it falls back to the team files'
   results dated before the start, and to the all-time head to head only where this test is the latest meeting (it
   is taken out), never a record that runs past the start. */
function formHTML(S, M, TH, TA) {
  var c = M.match, before = String(c.date || ''), go = started(c), P = (go && M.pre) || null;
  var last5 = function (T, tid, i) {
    if (P && P.form) return String(P.form[i] || '').split('').filter(Boolean);
    return ((T || {}).results || []).filter(function (r) { return isNum(r.hs) && String(r.id) !== String(c.id) && String(r.date) < before; }).slice(0, 5).reverse().map(function (r) { return SC.result(S, r, tid); });
  };
  var side = function (tid, T, i) { var t = SC.team(S, tid) || {}; return { name: t.name, abbr: t.abbr, colour: t.colour, form: last5(T, tid, i) }; };
  var fp = QK.formPair({ left: side(c.home, TH, 0), right: side(c.away, TA, 1), n: 5, title: 'Last five tests before this one' });
  var H = SC.tname(S, c.home), A = SC.tname(S, c.away);
  var h = null;
  if (P) h = P.h2h || { p: 0 };
  else {
    var hh = ((TH || {}).h2h || []).filter(function (x) { return String(x.opp) === String(c.away); })[0];
    if (hh && hh.p) {
      h = { p: hh.p, w: hh.w, d: hh.d, l: hh.l, pf: hh.pf, pa: hh.pa, ro: hh.ro || 0, first: hh.first, last: hh.last };
      if (go) {
        if (c.status === 'final' && isNum(c.hs) && hh.last && String(hh.last.id) === String(c.id)) {
          h.p -= 1; if (c.hs > c.as) h.w -= 1; else if (c.hs < c.as) h.l -= 1; else h.d -= 1;
          if (!c.ro) { h.pf -= c.hs; h.pa -= c.as; } else h.ro -= 1;
          h.last = null;
        } else h = null;           /* the record runs past the start: left out until the next build */
      }
    }
  }
  var line = '';
  if (h) {
    if (h.p <= 0) line = 'The first meeting in our data.';
    else {
      line = (go ? 'Before this test: ' : '') + h.p + ' meeting' + (h.p === 1 ? '' : 's') + ' since ' + esc(SC.year(h.first)) + ', ' +
        h.w + ' ' + esc(H) + ' win' + (h.w === 1 ? '' : 's') + ', ' + h.d + ' draw' + (h.d === 1 ? '' : 's') + ', ' + h.l + ' ' + esc(A) + ' win' + (h.l === 1 ? '' : 's') +
        (h.p > (h.ro || 0) ? ' (points ' + h.pf + '–' + h.pa + (h.ro ? ', the ' + h.ro + ' tests before 1891 had no points' : '') + ')' : '') + '.';
      if (h.last) line += ' The last: ' + esc(SC.scoreText(h.last.us, h.last.them, h.last.ro)) + ' to ' + esc(SC.tabbr(S, c.home)) + ', ' + esc(SC.date(h.last.date)) + '.';
    }
  }
  if (!fp && !line) return '';
  return U.card('Form and head to head', go ? 'Results dated before ' + esc(SC.date(c.date)) + ' only.' : 'Results dated before the start only.', fp + (line ? QK.explain('<b>Head to head.</b> ' + line) : '') +
    '<p class="sc-note"><a href="' + esc(SC.teamHref(S, c.home)) + '">' + esc(H) + '’s every opponent →</a></p>');
}

/* the key players: the best by Scrum value per 80 among those who played the side's last test (the team file's squad
   with that date), else the most capped of them when our source has no player statistics for the side */
function keysHTML(S, T, tid) {
  if (!T) return '';
  var lastT = ((T.results || [])[0] || {}).date;
  if (!lastT) return '';
  var d = String(lastT).slice(0, 10);
  var xi = (T.squad || []).filter(function (r) { return String(r.last || '') === d; });
  if (!xi.length) return '';
  var vals = xi.filter(function (r) { return isNum(r.val); }).sort(function (a, b) { return b.val - a.val; }).slice(0, 3);
  var list = vals.length ? vals : xi.slice().sort(function (a, b) { return ((b.wcaps || b.caps) || 0) - ((a.wcaps || a.caps) || 0); }).slice(0, 3);
  return U.card(SC.tname(S, tid) + ': key players', vals.length ? 'The top three by Scrum value per 80 (points of margin above a replacement-level player of the position, last two years) among those who played the last test, ' + esc(SC.date(lastT)) + '.' :
    'Our source has no player statistics for ' + esc(SC.tname(S, tid)) + '’s recent tests, so no values: the three most capped of those who played the last test, ' + esc(SC.date(lastT)) + '.',
    '<ul class="sc-list">' + list.map(function (r) {
      return '<li>' + U.playerEnt(S, r.id, r.n, tid, SC.posName(r.pos)) + '<span class="v">' + (vals.length ? '<span class="sc-ours ' + SC.cls(r.val) + '">' + SC.signed(r.val, 1) + '</span>' : ((r.wcaps || r.caps) + ' caps')) + '</span></li>';
    }).join('') + '</ul>');
}

SC.route('match', function (page, P) {
  var S = P.S;
  page.innerHTML = QK.skeleton('card', 2);
  return SC.load(S + '/matches/' + P.id + '.json').then(function (M) {
    if (!SC.ok(M)) { page.innerHTML = U.head('Match', '', SC.SNAME[S]) + U.missing('This match page', M); return; }
    var c = M.match, g = SC.game(S, c), F = M.forecast || {};
    var fin = c.status === 'final';
    var kick = SC.compName(c.comp) + (c.venue ? ' · ' + c.venue : '') + (c.neutral ? ' · neutral' : '');
    var html = '<nav class="sc-crumb"><a href="' + esc(SC.href(S, 'fixtures')) + '">Fixtures</a> / ' + esc(SC.date(c.date)) + '</nav>';
    var extra = isNum(F.margin) ? 'We expected ' + esc(SC.tname(S, F.margin >= 0 ? c.home : c.away)) + ' by about ' + Math.max(1, Math.round(Math.abs(F.margin))) +
      (isNum(F.total) ? ' in a ' + Math.round(F.total) + '-point test' : '') + '.' : '';
    /* v4: the match-up moved to the tale of the tape under the hero (QK.tape); the forecast panel sits beside it */
    var side = forecastSide(S, M);
    /* "How sure are we?" in words that hold at the ends too: a 99% favourite fails to win about 1 test in 100, not 1 in 10 */
    var po = { kicker: kick, noun: 'test', homeFirst: true, noteExtra: extra };
    var hs0 = SC.howSure(S, Object.assign({}, c, { p: F.p || c.p }), extra);
    if (hs0) po.note = hs0;
    html += '<div class="sc-gtop' + (side ? '' : ' solo') + '"><div class="sc-gmain">' + QK.previewCard(g, po) + '</div>' + side + '</div>';
    // the result against the forecast
    if (fin && F.p && !c.ro) {
      var hw = c.hs > c.as, dr = c.hs === c.as, pw = hw ? F.p[0] : dr ? F.p[1] : F.p[2];
      var mg = c.hs - c.as;
      var verdict = dr ? 'A draw, which we had at ' + SC.pct(F.p[1]) + '.' : (pw >= 0.5 ? 'As expected: ' : pw >= 0.4 ? 'A near coin flip: ' : 'An upset: ') + esc(SC.tname(S, hw ? c.home : c.away)) + ' won at ' + SC.pct(pw) + ' in our numbers.';
      var inBand = isNum(F.sd) && isNum(F.margin) ? Math.abs(mg - F.margin) <= Z80 * F.sd : null;
      html += QK.stats([{ label: 'Our pre-match chance for the winner', value: SC.pct(pw), signal: true, sub: verdict, html: true },
        { label: 'Margin', value: SC.signed(mg, 0), sub: 'We expected ' + SC.signed(F.margin, 1) + ' (home side first)' + (inBand === null ? '.' : inBand ? ', inside our 8-in-10 range.' : ', outside our 8-in-10 range.') },
        { label: 'Total', value: String(c.hs + c.as), sub: isNum(F.total) ? 'We expected ' + Math.round(F.total) + '.' : '' },
        M.halves ? { label: 'Half-time' + (M.halves_est ? ' (from the scoring)' : ''), value: (M.halves[0][0] || 0) + '–' + (M.halves[1][0] || 0), sub: 'Second half ' + ((M.halves[0][1] || 0) - (M.halves[0][0] || 0)) + '–' + ((M.halves[1][1] || 0) - (M.halves[1][0] || 0)) } : null,
        M.wr ? { label: 'World Rugby points', value: SC.signed(M.wr.x, 2), sub: SC.tname(S, c.home) + ' took ' + SC.signed(M.wr.x, 2) + ' from ' + SC.tname(S, c.away) + ' (our replica; ' + SC.f(M.wr.before[0], 2) + ' v ' + SC.f(M.wr.before[1], 2) + ' before).' } : null]);
    }
    var moments = M.events && M.events.length ? U.card('Key moments', 'Tries, kicks, cards and changes as the feed records them.', '<ol class="sc-events">' + M.events.filter(function (e) { return e[1] !== 'on' && e[1] !== 'off'; }).map(function (e) {
      var tid = e[2] === 'h' ? c.home : c.away;
      return '<li class="ev-' + esc(e[1]) + '"><span class="mn num">' + (isNum(e[0]) ? e[0] + '’' : '') + '</span>' + QK.teamMark(SC.mark(S, tid), 'sm') + '<span class="w">' + esc(EV_WORD[e[1]] || e[1]) + '</span>' +
        (e[3] ? '<a href="' + esc(SC.playerHref(S, e[3])) + '">' + esc(e[4] || '') + '</a>' : '<span>' + esc(e[4] || '') + '</span>') + (isNum(e[5]) ? '<span class="sc num">' + e[5] + '–' + e[6] + '</span>' : '') + '</li>';
    }).join('') + '</ol>') : '';
    var flow = (M.events && M.events.length >= 2 ? U.card('The score, minute by minute', 'Each side’s points through the match, from the scoring events.', U.chart('mt-race', 280, 'Score by minute')) : '') +
      (M.wp ? U.card('Our win chance through the test', 'From our pre-match margin and spread and the score at each scoring event: the time left shrinks the spread. 50% is even.', U.chart('mt-wp', 240, 'Win chance by minute')) : '');
    /* the tape (left) beside the form card, then (before the start) the key players or (after it) the flow and moments */
    /* a finished test with team statistics has a long tape: the flow and the moments run beside it; without them the
       tape is short, so they get their own row */
    var tall = fin && !!M.stats;
    html += '<div class="qk-g2 sc-gap"><div id="mt-tape">' + QK.skeleton('lines', 6) + '</div><div><div id="mt-form"></div>' + (tall ? flow + moments : fin ? '' : '<div id="mt-keys"></div>') + '</div></div>';
    if (fin && !tall && (flow || moments)) html += '<div class="qk-g2 sc-gap"><div>' + flow + '</div><div>' + moments + '</div></div>';
    html += conditions(S, M);
    html += difference(S, M);
    if (M.lines) {
      if (!M.has_stats) html += U.note('Our source has the line-ups for this test but no player statistics, so the team sheets below show the minutes only.');
      ['h', 'a'].forEach(function (k) {
        var tid = k === 'h' ? c.home : c.away;
        if (!M.lines[k]) return;
        html += U.card(SC.tname(S, tid) + ': the matchday 23', 'Starters 1-15, then the replacements. Minutes come from the substitutions; "~" marks an estimate where the feed has none.' + (M.has_stats ? ' Value is the player’s game value (see above).' : ''), lineTable(S, M.lines[k], tid, !!M.has_stats), { flush: true });
      });
    } else if (fin && !M.source) {
      html += U.note('Our source has no line-ups or player statistics for this match.');
    }
    if (F.p && !fin) {
      /* the edge is signed: + for the home side in its own country, − when the side listed second is the one at home
         (a World Cup host listed away), 0 at a neutral venue or a "home" test abroad */
      var adv = !isNum(F.edge) || Math.abs(F.edge) < 0.05 ? (c.neutral ? 'none: a neutral venue' : 'none: neither side plays in its own country here') :
        'about ' + SC.f(Math.abs(F.edge), 1) + ' points for ' + esc(SC.tname(S, F.edge > 0 ? c.home : c.away)) + (F.edge > 0 ? ', at home' : ', at home in its own country though listed second');
      html += QK.explain('<b>How we got there.</b> Our rating gap with home advantage (' + adv +
        '), then a normal spread of margins around it' + (isNum(F.sd) ? ' (' + SC.f(F.sd, 1) + ' points here: 8 tests in 10 land within ' + Math.round(Z80 * F.sd) + ' points of our margin)' : '') + '. <a class="qk-link" href="' + esc(SC.href(S, 'model')) + '">The method</a>.');
    }
    page.innerHTML = html;
    U.wire(page);
    scoreRace(QK.$('#mt-race', page), S, M);
    winPath(QK.$('#mt-wp', page), S, M);
    document.title = SC.tabbr(S, c.home) + ' v ' + SC.tabbr(S, c.away) + ' · ' + SC.SITE;
    /* both team files and the metric names (files the site already publishes), then the tape, the form and the keys */
    return Promise.all([SC.load(S + '/teams/' + c.home + '.json'), SC.load(S + '/teams/' + c.away + '.json'), SC.load(S + '/teams.json')]).then(function (tt) {
      if (!U.alive(page)) return;
      var TH = SC.ok(tt[0]) ? tt[0] : null, TA = SC.ok(tt[1]) ? tt[1] : null, MET = {};
      ((SC.ok(tt[2]) && tt[2].metrics) || []).forEach(function (m) { MET[m.id] = m; });
      var tp = QK.$('#mt-tape', page), fm = QK.$('#mt-form', page), ky = QK.$('#mt-keys', page);
      if (tp) tp.innerHTML = tapeHTML(S, M, TH, TA, MET) || U.card('Tale of the tape', '', QK.empty('Nothing to compare yet', 'Neither side has a rating or team statistics in our data.'));
      if (fm) fm.innerHTML = formHTML(S, M, TH, TA);
      if (ky) ky.innerHTML = keysHTML(S, TH, c.home) + keysHTML(S, TA, c.away);
      U.wire(page);
    });
  });
});
})();
