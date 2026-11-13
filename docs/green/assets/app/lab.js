/* The Quant Green — the Lab (#/value?tab=lab|courses|records) and the course page (#/course/<id>).
 * Lab: what wins (each statistic against strokes gained), the strokes-gained category fit with its out-of-sample R2,
 * the age curve and peak age, tee-time waves, scoring by round, the tours side by side. Courses: every course with
 * editions on file, its difficulty, length and what it rewards. Records: lowest rounds against the field, biggest
 * winning margins, the biggest upsets, best seasons and the season-best progression. Reads lab.json,
 * courses.json, records.json and courses/<id>.json (depth.py). */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;
var STAT = { dist: 'Driving distance', acc: 'Driving accuracy', gir: 'Greens in regulation', ppg: 'Putts per green hit', sand: 'Sand saves',
  h3: 'Par 3 scoring', h4: 'Par 4 scoring', h5: 'Par 5 scoring', bird: 'Birdie rate', bog: 'Bogey rate', sd: 'Round-to-round spread' };

function labTab(el, L) {
  if (!L) { el.innerHTML = QK.empty('The Lab is not built yet', 'It appears after the next build.'); return; }
  var c = L.cats;
  var html = '';
  var ww = L.what_wins || {};
  var wk = Object.keys(ww).filter(function (k) { return isNum(ww[k]); }).sort(function (a, b) { return Math.abs(ww[b]) - Math.abs(ww[a]); });
  html += '<div class="qk-g2 gr-gap">' + GR.card('What wins', 'The correlation of each season number with the season’s strokes gained per round (PGA Tour and Korn Ferry regulars, 25+ rounds a season, ' + '2017 on). Lower-is-better numbers show as negative.', GR.chart('lb-ww', 360, 'What wins')) +
    GR.card('Strokes gained by category: our estimate', c ? 'A regression of each player-season’s strokes gained on its PGA Tour statistics, fitted on ' + c.train[0] + '–' + c.train[1] + ' (' + fmt.num(c.n_train) + ' player-seasons) and scored once on ' + c.test[0] + '–' + c.test[1] + ' (' + fmt.num(c.n_test) + ').' : '',
      c ? GR.chart('lb-cat', 300, 'Category coefficients') + QK.stats([{ label: 'Explained, fit years', value: GR.pct(c.r2_train) }, { label: 'Explained, held out', value: GR.pct(c.r2_test), signal: true, sub: 'the share of the spread in strokes gained the five statistics explain in seasons the fit never saw' }]) +
        GR.note('Strokes per round for one standard deviation better on each statistic. <b>Off the tee</b> = distance + accuracy, <b>approach</b> = greens in regulation, <b>around the green</b> = sand saves, <b>putting</b> = putts per green hit. Not ShotLink strokes gained (licensed, not used): greens in regulation also carries some of the tee shot, and the rest of a player’s game shows up as the unexplained part.') : QK.empty('Not fitted yet', 'The fit needs the PGA Tour season statistics from 2017.')) + '</div>';
  var sc = L.scatter || {};
  if ((sc.rows || []).length) html += GR.card('Strokes gained against a statistic, ' + sc.year, 'Each dot a regular (25+ rounds) with PGA Tour statistics that year.',
    '<div class="qk-seg" id="lb-sk" role="group" aria-label="Statistic" style="margin-bottom:10px">' + [['dist', 'Distance'], ['acc', 'Accuracy'], ['gir', 'GIR'], ['ppg', 'Putts/GIR'], ['sand', 'Sand']].map(function (x, i) { return '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (i === 0) + '">' + x[1] + '</button>'; }).join('') + '</div>' + GR.chart('lb-sc', 420, 'Strokes gained against a statistic'));
  var ag = L.age;
  html += '<div class="qk-g2 gr-gap">' + GR.card('The age curve', ag ? 'Strokes gained against the player’s own best age, from ' + fmt.num(ag.pairs) + ' back-to-back seasons of the same players (the delta method: each player against himself, so survivors do not flatter the old). Peak: about ' + ag.peak + '.' : '',
    ag ? GR.chart('lb-age', 320, 'Age curve') : QK.empty('Ages are still loading', 'The curve needs players’ dates of birth (ESPN bios), fetched once.')) +
    GR.card('Tee-time waves', L.waves ? 'Rounds 1 and 2 on the PGA Tour: the early half of the field’s strokes gained against the late half’s, per round. Across ' + fmt.num(L.waves.n) + ' rounds the average gap is ' + GR.signed(L.waves.mean, 2) + ' (early minus late), but its size averages ' + fmt.num(L.waves.abs, 2) + ' strokes and ' + L.waves.big + ' rounds split by a full stroke or more: the weather draw.' : '', L.waves ? GR.chart('lb-wv', 320, 'Wave gap by year') : QK.empty('No tee times on file', '')) + '</div>';
  var tours = L.tours || [];
  html += '<div class="qk-g2 gr-gap">' + GR.card('The tours side by side', 'The regulars of the last two years (30+ rounds), by the tour they played most: their average rating, the 90th percentile, and the round-to-round spread.',
    GR.table([{ label: 'Tour', align: 'left' }, { label: 'Players' }, { label: 'Average rating' }, { label: 'Top 10%' }, { label: 'Spread' }], tours.map(function (t) {
      return [{ v: t.name, html: esc(t.name) }, { v: t.n, html: String(t.n) }, { v: t.rt, html: '<b>' + GR.signed(t.rt, 2) + '</b>' }, { v: t.top, html: GR.signed(t.top, 2) }, { v: t.sd, html: fmt.num(t.sd, 2) }]; })) +
    GR.note('Every men’s tour sits on one scale (the PGA Tour’s average player is zero), tied together by the players who cross over. The LPGA is its own scale.'), { flush: false }) +
    GR.card('Scoring by round', 'The field’s average score against the field par (what an average tour player would shoot) by round, the last five years: the weekend field is the stronger, smaller one.', GR.chart('lb-rd', 300, 'Scoring by round')) + '</div>';
  el.innerHTML = html;
  QK.sortable(el);
  GR.safe(function () {
    if (!wk.length) return;
    QKC.bar(el.querySelector('#lb-ww'), { cats: wk.map(function (k) { return STAT[k] || k; }), series: [{ name: 'Correlation', data: wk.map(function (k) { return ww[k]; }) }], diverging: true, horizontal: true, labels: true,
      fmt: function (v) { return fmt.num(v, 2); }, valName: 'Correlation with season strokes gained', catName: 'Season number' });
  });
  GR.safe(function () {
    if (!c) return;
    var ks = ['dist', 'acc', 'gir', 'ppg', 'sand'];
    QKC.bar(el.querySelector('#lb-cat'), { cats: ks.map(function (k) { return STAT[k]; }), series: [{ name: 'Strokes per round per standard deviation', data: ks.map(function (k) { return c.coef[k]; }) }], diverging: true, horizontal: true, labels: true,
      fmt: function (v) { return GR.signed(v, 2); }, valName: 'Strokes a round per standard deviation', catName: 'Statistic' });
  });
  var drawSc = function (k) {
    var ix = { sg: 2, dist: 3, acc: 4, gir: 5, ppg: 6, sand: 7 }[k];
    var pc = { acc: 1, gir: 1, sand: 1 }[k];
    var pts = (sc.rows || []).filter(function (r) { return isNum(r[2]) && isNum(r[ix]); }).map(function (r) { return { x: pc ? r[ix] * 100 : r[ix], y: r[2], name: r[1], label: GR.surname(r[1]), href: GR.playerHref(r[0]) }; });
    QKC.scatter(el.querySelector('#lb-sc'), { points: pts, xName: STAT[k] + (pc ? ' (%)' : k === 'dist' ? ' (yards)' : ''), yName: 'Strokes gained per round', xInverse: k === 'ppg', labelTop: 10,
      yFmt: function (v) { return GR.signed(v, 1); }, label: 'Strokes gained against ' + STAT[k] });
  };
  GR.safe(function () { if ((sc.rows || []).length) drawSc('dist'); });
  var seg = el.querySelector('#lb-sk');
  if (seg) QK.seg(seg, function (k) { GR.safe(function () { drawSc(k); }); });
  GR.safe(function () {
    if (!ag) return;
    QKC.line(el.querySelector('#lb-age'), { x: ag.rows.map(function (r) { return r[0]; }), xType: 'value', series: [{ name: 'Against the best age', data: ag.rows.map(function (r) { return [r[0], r[1]]; }), color: 'var(--c-1)', symbols: true }],
      yName: 'Strokes a round against the peak', xName: 'Age', endLabels: false, ref: { x: ag.peak, label: 'Peak' }, yFmt: function (v) { return GR.signed(v, 1); } });
  });
  GR.safe(function () {
    if (!L.waves) return;
    var by = L.waves.by_year || [];
    QKC.line(el.querySelector('#lb-wv'), { x: by.map(function (r) { return r[0]; }), xType: 'value', series: [{ name: 'Average size of the gap', data: by.map(function (r) { return [r[0], r[2]]; }), color: 'var(--c-1)' },
      { name: 'Early minus late', data: by.map(function (r) { return [r[0], r[1]]; }), color: 'var(--c-3)' }], yName: 'Strokes a round', xName: 'Year', ref: { y: 0, label: 'No gap' }, yFmt: function (v) { return fmt.num(v, 2); }, xFmt: function (v) { return String(v); } });
  });
  GR.safe(function () {
    var rd = (L.by_round || []).filter(function (x) { return (x.rows || []).length; });
    if (!rd.length) return;
    var cats = rd[0].rows.map(function (r) { return 'Round ' + r[0]; });
    QKC.bar(el.querySelector('#lb-rd'), { cats: cats, series: rd.map(function (x, i) { return { name: x.stream === 'men' ? 'Men' : 'LPGA', data: x.rows.map(function (r) { return r[1]; }), color: i ? 'var(--c-3)' : 'var(--c-1)' }; }),
      labels: true, legend: true, fmt: function (v) { return GR.signed(v, 2); }, valName: 'Strokes against the field par', catName: 'Round' });
  });
}

function coursesTab(el, C) {
  var cs = ((C && C.courses) || []).slice().sort(function (a, b) { return b.events - a.events; });
  if (!cs.length) { el.innerHTML = QK.empty('No courses yet', ''); return; }
  var rw = function (c, k) { var v = (c.rw || {})[k]; return { v: isNum(v) ? (k === 'ppg' ? -v : v) : -9, html: isNum(v) ? GR.signed(k === 'ppg' ? -v : v, 2) : '' }; };
  el.innerHTML = GR.card('The hardest and the longest', 'Each dot a course with 200+ rounds on file: length across, how many strokes an average field takes against par up.', GR.chart('cs-sc', 420, 'Course length against difficulty')) +
    GR.card('Every course', 'Single-course events only (multi-course events cannot tie a round to its course). Difficulty: strokes an average tour field takes against par, a round. Rewards: the correlation of beating one’s own rating there with each PGA Tour statistic (2017 on; putting turned so positive means good putters gain).',
      GR.table([{ label: 'Course', align: 'left' }, { label: 'Tour' }, { label: 'Par' }, { label: 'Yards' }, { label: 'Editions' }, { label: 'Rounds' }, { label: 'Difficulty' }, { label: 'Distance' }, { label: 'Accuracy' }, { label: 'GIR' }, { label: 'Putting' }, { label: 'Last' }],
        cs.map(function (c) { return [{ v: c.name, html: GR.courseLink(c.id, c.name) }, { v: c.tour, html: esc(GR.tourShort(c.tour)) }, { v: c.par || 0, html: c.par ? String(c.par) : '' }, { v: c.yards || 0, html: c.yards ? fmt.num(c.yards) : '' },
          { v: c.events, html: String(c.events) }, { v: c.rounds, html: fmt.num(c.rounds) }, { v: c.diff, html: '<b>' + GR.signed(c.diff, 2) + '</b>' }, rw(c, 'dist'), rw(c, 'acc'), rw(c, 'gir'), rw(c, 'ppg'), { v: c.last, html: esc(String(c.last).slice(0, 4)) }]; }), { maxHeight: 820 }), { flush: true });
  QK.sortable(el);
  GR.safe(function () {
    var pts = cs.filter(function (c) { return isNum(c.yards) && c.yards > 5000 && isNum(c.diff); }).map(function (c) { return { x: c.yards, y: c.diff, name: c.name + ' · ' + GR.tourShort(c.tour), label: c.events >= 15 ? c.name.split(' (')[0] : '', href: '#/course/' + encodeURIComponent(c.id), color: GR.TOUR_COL[c.tour] }; });
    QKC.scatter(el.querySelector('#cs-sc'), { points: pts, xName: 'Length (yards)', yName: 'Difficulty (strokes against par for an average field)', labelTop: 12, yFmt: function (v) { return GR.signed(v, 1); }, xFmt: function (v) { return fmt.num(v); }, label: 'Course length against difficulty' });
  });
}

function recordsTab(el, R, s) {
  var d = (R || {})[s];
  if (!d) { el.innerHTML = QK.empty('No records yet', ''); return; }
  var t = function (cols, rows) { return GR.table(cols, rows, { maxHeight: 520 }); };
  el.innerHTML = '<div class="gr-controls">' + GR.seg('rc-s', [['men', 'Men'], ['women', 'Women']], s, 'Men or women') + '</div>' +
    GR.card('The best season every year', 'The highest strokes gained per round over a calendar year (40+ rounds); a filled dot set a new mark for our data (since ' + d.from + ').', GR.chart('rc-pr', 300, 'Season best by year')) +
    '<div class="qk-g2 gr-gap">' + GR.card('Lowest rounds against the field', 'Strokes better than an average field would have shot that day: the course and the conditions taken out.', t([{ label: 'Player', align: 'left' }, { label: 'Event', align: 'left' }, { label: 'Score' }, { label: 'Field' }, { label: 'SG' }],
      (d.low_rounds || []).map(function (r) { return [{ v: r.name, html: GR.playerLink(r.pid, r.name) }, { v: r.ev, html: GR.eventLink(r.event, r.y + ' ' + (r.ev || '')) + ' <span class="gr-muted">R' + r.round + '</span>' }, { v: r.strokes, html: String(r.strokes) }, { v: r.field, html: fmt.num(r.field, 1) }, { v: r.sg, html: '<b>' + GR.signed(r.sg, 1) + '</b>' }]; })), { flush: true }) +
    GR.card('Biggest winning margins', 'Strokes between the winner and second, from the round scores.', t([{ label: 'Winner', align: 'left' }, { label: 'Event', align: 'left' }, { label: 'Margin' }],
      (d.margins || []).map(function (r) { return [{ v: r.name, html: GR.playerLink(r.pid, r.name) }, { v: r.ev, html: GR.eventLink(r.event, r.y + ' ' + r.ev) }, { v: r.margin, html: '<b>' + r.margin + '</b>' }]; })), { flush: true }) + '</div>' +
    '<div class="qk-g2 gr-gap">' + GR.card('Biggest upsets', 'Winners we gave the smallest chance before the event.', t([{ label: 'Winner', align: 'left' }, { label: 'Event', align: 'left' }, { label: 'Our chance' }],
      (d.longshots || []).map(function (r) { return [{ v: r.name, html: GR.playerLink(r.pid, r.name) }, { v: r.ev, html: GR.eventLink(r.event, r.y + ' ' + (r.ev || '')) }, { v: r.p, html: '<b>' + GR.pct(r.p, 2) + '</b>' }]; })), { flush: true }) +
    GR.card('Best seasons', 'Strokes gained per round over a calendar year, 40+ rounds.', t([{ label: 'Player', align: 'left' }, { label: 'Year' }, { label: 'Rounds' }, { label: 'Wins' }, { label: 'SG/rd' }],
      (d.best_seasons || []).map(function (r) { return [{ v: r.name, html: GR.playerLink(r.pid, r.name) }, { v: r.y, html: String(r.y) }, { v: r.rounds, html: String(r.rounds) }, { v: r.wins || 0, html: String(r.wins || 0) }, { v: r.sg, html: '<b>' + GR.signed(r.sg, 2) + '</b>' }]; })), { flush: true }) + '</div>' +
    GR.card('Most wins in our data', 'Every final event on file since ' + d.from + '.', t([{ label: 'Player', align: 'left' }, { label: 'Wins' }], (d.most_wins || []).map(function (r) { return [{ v: r.name, html: GR.playerLink(r.pid, r.name) }, { v: r.wins, html: '<b>' + r.wins + '</b>' }]; })), { flush: true });
  QK.sortable(el);
  QK.seg(el.querySelector('#rc-s'), function (v) { location.hash = '#/value?tab=records&s=' + v; });
  GR.safe(function () {
    var p = d.season_best || [];
    QKC.line(el.querySelector('#rc-pr'), { x: p.map(function (r) { return r.y; }), xType: 'value', series: [{ name: 'Best season', data: p.map(function (r) { return [r.y, r.sg]; }), color: 'var(--c-1)', symbols: true }],
      yName: 'Strokes gained per round', xName: 'Year', endLabels: false, yFmt: function (v) { return GR.signed(v, 1); }, xFmt: function (v) { return String(v); } });
  });
}

GR.page('lab', function (el, params) {
  var q = params.query || {};
  var tab = ['lab', 'courses', 'records'].indexOf(q.tab) >= 0 ? q.tab : 'lab';
  var file = { lab: 'lab.json', courses: 'courses.json', records: 'records.json' }[tab];
  return GR.maybe(file).then(function (d) {
    if (!el.isConnected) return;
    el.innerHTML = GR.head('The Lab', 'What the numbers say about the game: what wins, how players age, the weather draw, the courses and the records.', 'Lab') +
      GR.tabs([['lab', 'What wins', '#/value'], ['courses', 'Courses', '#/value?tab=courses'], ['records', 'Records', '#/value?tab=records']], tab) + '<div id="lb-body"></div>';
    var body = el.querySelector('#lb-body');
    if (tab === 'courses') coursesTab(body, d);
    else if (tab === 'records') recordsTab(body, d, q.s === 'women' ? 'women' : 'men');
    else labTab(body, d);
  });
});

/* The course page, in the family's order: the hero (the tour colour, the course's initials, par, yardage and editions as
   chips) with the black strip of its numbers, the short version, then the charts (scoring by hole, what it rewards),
   then the tables (who plays it best, who has played it most, every edition, the holes). Difficulty is ranked against
   every course of the same stream with 200+ rounds on file (courses.json, the Lab's courses list). */
GR.page('course', function (el, params) {
  return Promise.all([GR.load('courses/' + encodeURIComponent(params.id) + '.json'), GR.maybe('courses.json')]).then(function (res) {
    if (!el.isConnected) return;
    var c = res[0], all = res[1];
    var rw = c.rw || {};
    var lab = { dist: 'Driving distance', acc: 'Driving accuracy', gir: 'Greens in regulation', ppg: 'Putting', sand: 'Sand saves' };
    var keys = Object.keys(rw).filter(function (k) { return isNum(rw[k]); });
    var stream = c.stream || (c.tour === 'lpga' ? 'women' : 'men');
    var hs = c.holes || [];
    var y0 = String(c.first || '').slice(0, 4), y1 = String(c.last || '').slice(0, 4);
    /* difficulty against the peers: same stream, 200+ rounds */
    var peers = ((all && all.courses) || []).filter(function (x) { return (x.stream || 'men') === stream && x.rounds >= 200 && isNum(x.diff); });
    var inPeers = peers.some(function (x) { return String(x.id) === String(c.id); });
    var rankD = inPeers ? 1 + peers.filter(function (x) { return x.diff > c.diff; }).length : null;
    var peerTxt = inPeers ? 'the ' + QK.ordinal(rankD) + ' hardest of ' + peers.length + (stream === 'women' ? ' LPGA' : ' men’s') + ' courses with 200+ rounds' : (c.rounds < 200 ? 'under the 200 rounds needed to rank it' : '');
    var hard = hs.length ? hs.slice().sort(function (a, b) { return b.avg - a.avg; })[0] : null;
    var easy = hs.length ? hs.slice().sort(function (a, b) { return a.avg - b.avg; })[0] : null;
    var lastEd = (c.editions || []).filter(function (e) { return e.status === 'final'; })[0];
    var strip = [
      { label: 'Difficulty', value: GR.signed(c.diff, 2), signal: true, sub: 'strokes over par a round for an average tour field' + (peerTxt ? ': ' + peerTxt : ''),
        tip: 'Our number: the field’s average score against par, adjusted for how strong the field was, so a course is not called easy because the best players went there' },
      { label: 'Scoring', value: GR.signed(c.to_par, 2), sub: 'what the fields that played it actually averaged against par, a round' },
      hard ? { label: 'Hardest hole: the ' + QK.ordinal(hard.h), value: GR.signed(hard.avg, 2), sub: 'par ' + hard.par + ' · ' + GR.pct(hard.bog, 0) + ' bogey or worse, ' + GR.pct(hard.bird, 0) + ' birdie or better' } : null,
      easy ? { label: 'Easiest hole: the ' + QK.ordinal(easy.h), value: GR.signed(easy.avg, 2), sub: 'par ' + easy.par + ' · ' + GR.pct(easy.bird, 0) + ' birdie or better' } : null,
      { label: 'Rounds on file', value: fmt.num(c.rounds), sub: 'from ' + c.events + (c.events === 1 ? ' edition' : ' editions') + (y0 ? ', ' + y0 + (y1 && y1 !== y0 ? '–' + y1 : '') : '') + ((c.editions || []).length > c.events ? ' (the others have no round scores tied to this course)' : '') }
    ].filter(Boolean);
    /* the short version: how hard, where the strokes go, what it rewards */
    var sv = esc(c.name) + ' plays ' + GR.signed(c.diff, 2) + ' strokes a round against par for an average tour field' + (inPeers ? ', the ' + QK.ordinal(rankD) + ' hardest of ' + peers.length + ' courses on file' : '') + '.';
    if (hard && easy) sv += ' The ' + QK.ordinal(hard.h) + ' is the hardest hole (' + GR.signed(hard.avg, 2) + ' against par), the ' + QK.ordinal(easy.h) + ' the easiest (' + GR.signed(easy.avg, 2) + ').';
    if (keys.length) {
      var rv = function (k) { return k === 'ppg' ? -rw[k] : rw[k]; };
      var ks = keys.slice().sort(function (a, b) { return rv(b) - rv(a); });
      var big = Math.max.apply(null, keys.map(function (k) { return Math.abs(rv(k)); }));
      sv += ' Of the PGA Tour statistics, it rewards ' + lab[ks[0]].toLowerCase() + ' most (' + GR.signed(rv(ks[0]), 2) + ') and ' + lab[ks[ks.length - 1]].toLowerCase() + ' least (' + GR.signed(rv(ks[ks.length - 1]), 2) + ')' +
        (big < 0.1 ? ', but every link is weak (under 0.10): no single skill decides it here.' : '.');
    }
    var sure = '<b>How sure are we?</b> ' + fmt.num(c.rounds) + ' rounds over ' + c.events + (c.events === 1 ? ' edition is a thin base: read the difficulty and the hole numbers lightly.' : ' editions: ' + (c.rounds >= 1000 ? 'a solid base for the difficulty and the hole averages.' : 'enough for the difficulty, but the hole averages still move with the weather of a single edition.')) +
      ' Course fit needs eight rounds here and is shrunk toward zero with 32 rounds, and it is history, not a forecast: adding it did not improve our forecasts on the sealed test seasons.';
    var nEd = Math.max(c.events || 0, (c.editions || []).length);
    var chips = [c.par ? ['Par', String(c.par)] : null, c.yards ? fmt.num(c.yards) + ' yards' : null, nEd + (nEd === 1 ? ' edition' : ' editions') + ' on file',
      lastEd ? 'Last: ' + (lastEd.page ? '<a href="#/event/' + encodeURIComponent(lastEd.id) + '">' + esc(lastEd.y + ' ' + lastEd.name) + '</a>' : esc(lastEd.y + ' ' + lastEd.name)) : null];
    var html = '<nav class="gr-crumb"><a href="#/value?tab=courses">Courses</a> / ' + esc(c.name) + '</nav>' +
      QK.playerHeader({ name: c.name, face: GR.code(c.name), kicker: GR.tourName(c.tour) + ' · Course',
        team: { name: GR.tourName(c.tour), abbr: GR.tourShort(c.tour), colour: GR.TOUR_COL[c.tour], href: '#/fixtures/' + c.tour }, meta: chips, strip: strip, short: { title: 'The short version', html: sv } });
    /* the charts: scoring by hole beside what the course rewards */
    var simLine = (c.similar || []).length ? GR.note('Courses most like it (length, difficulty and what they reward): ' + c.similar.map(function (x) { return GR.courseLink(x.id, x.name); }).join(', ') + '.') : '';
    var rewards = GR.card('What it rewards', 'The correlation of beating one’s own rating here with each PGA Tour season statistic (2017 on); putting turned so positive means good putters gain.',
      (keys.length ? GR.chart('co-rw', 260, 'What the course rewards') : QK.empty('Not enough striking data here', 'It needs PGA Tour rounds from 2017 on.')) + simLine, { html: true });
    html += GR.sec('Hole by hole', 'Where the strokes go', 'Average strokes against par on each hole over every edition on file, and the season statistics that pay off here.',
      hs.length ? '<div class="qk-g2">' + GR.card('Scoring by hole', 'Strokes against par per hole, every round on file. Above the line plays over par.', GR.chart('co-h', 260, 'Scoring by hole')) + rewards + '</div>' : rewards);
    /* the tables: who plays it best (kept) beside who has played it most and every edition */
    var best = GR.card('Who plays it best', 'Strokes a round better than their own rating here (eight rounds or more), shrunk toward zero with 32 rounds.',
      GR.table([{ label: 'Player', align: 'left' }, { label: 'Rounds' }, { label: 'Editions' }, { label: 'SG/rd here', title: 'Strokes gained a round against the field here' }, { label: 'Fit', title: 'Strokes a round better than the rating they brought, shrunk with 32 rounds' }], (c.best || []).map(function (p) {
        return [{ v: p.name, html: GR.playerLink(p.pid, p.name) }, { v: p.rounds, html: String(p.rounds) }, { v: p.events, html: String(p.events) }, { v: p.sg, html: GR.signed(p.sg, 2) }, { v: p.fit, html: '<b>' + GR.signed(p.fit, 2) + '</b>' }]; }), { maxHeight: 640 }), { flush: true });
    var most = GR.card('Played most here', 'Rounds on file at this course.', GR.table([{ label: 'Player', align: 'left' }, { label: 'Rounds' }, { label: 'SG/rd here' }, { label: 'Fit' }], (c.most || []).map(function (p) {
        return [{ v: p.name, html: GR.playerLink(p.pid, p.name) }, { v: p.rounds, html: String(p.rounds) }, { v: p.sg, html: GR.signed(p.sg, 2) }, { v: p.fit, html: GR.signed(p.fit, 2) }]; })), { flush: true });
    var eds = GR.card('Every edition', 'Each event on file at this course and its winner' + ((c.editions || []).length > c.events ? '; ' + c.events + ' of them have round scores tied to this course, and only those count in the numbers above.' : '.'), GR.table([{ label: 'Year' }, { label: 'Event', align: 'left' }, { label: 'Winner', align: 'left' }], (c.editions || []).map(function (e) {
        return [{ v: e.y, html: String(e.y) }, { v: e.name, html: e.page ? GR.eventLink(e.id, e.name) : esc(e.name) }, { v: e.winner ? e.winner.name : '', html: e.winner ? GR.playerLink(e.winner.pid, e.winner.name) : '<span class="gr-muted">' + (e.status === 'final' ? 'no winner on file' : 'to come') + '</span>' }]; }), { maxHeight: 420 }), { flush: true });
    html += GR.sec('Course history', 'Who plays it best', 'The players who beat their own rating here by most, the ones with the most rounds here, and every edition on file.',
      '<div class="qk-g2">' + best + '<div class="gr-stack">' + most + eds + '</div></div>' + QK.explain(sure));
    if (hs.length) html += '<section class="qk-section gr-sec">' + GR.card('The holes, every edition on file', 'Average strokes against par per hole, with the birdie and bogey rates.',
      GR.table([{ label: 'Hole' }, { label: 'Par' }, { label: 'Rounds' }, { label: 'v par' }, { label: 'Birdie or better' }, { label: 'Bogey or worse' }], hs.map(function (h) {
        return { _class: hard && h.h === hard.h ? 'hl' : '', cells: [{ v: h.h, html: String(h.h) }, { v: h.par, html: String(h.par) }, { v: h.n, html: fmt.num(h.n) }, { v: h.avg, html: '<b>' + GR.signed(h.avg, 3) + '</b>' }, { v: h.bird, html: GR.pct(h.bird, 1) }, { v: h.bog, html: GR.pct(h.bog, 1) }] }; })), { flush: true }) + '</section>';
    el.innerHTML = html;
    QK.sortable(el);
    document.title = c.name + ' · The Quant Green';
    GR.safe(function () {
      if (!keys.length) return;
      QKC.bar(el.querySelector('#co-rw'), { cats: keys.map(function (k) { return lab[k]; }), series: [{ name: 'Correlation', data: keys.map(function (k) { return k === 'ppg' ? -rw[k] : rw[k]; }) }], diverging: true, horizontal: true, labels: true,
        fmt: function (v) { return GR.signed(v, 2); }, valName: 'Correlation with beating one’s rating here', catName: 'Statistic' });
    });
    GR.safe(function () {
      if (!hs.length) return;
      QKC.bar(el.querySelector('#co-h'), { cats: hs.map(function (h) { return String(h.h); }), series: [{ name: 'Against par', data: hs.map(function (h) { return h.avg; }) }], diverging: true,
        fmt: function (v) { return GR.signed(v, 2); }, catName: 'Hole', valName: 'Strokes against par' });
    });
  });
});
})();
