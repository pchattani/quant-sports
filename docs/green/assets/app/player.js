/* The Quant Green — the player page (#/player/<id>): the hero, percentiles against the regulars of the last two years
 * (last year's ring), the tale of the tape against the closest match with verdicts, the rating and form lines, where the
 * player sits among the peers, similar players, splits, course history, year by year and every event with our
 * pre-event chance. Reads players/<id>.json and scout/<stream>.json (pages.py, depth.py). */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;
var FAMILY = [['value', 'Rating and form'], ['scoring', 'Scoring'], ['holes', 'Hole by hole'], ['striking', 'Ball striking (PGA Tour statistics)'],
  ['categories', 'Strokes gained by category (our estimate)'], ['outcomes', 'Results']];
var HEAD = ['sg', 'form', 'sg_w', 'h4', 'h5', 'bird', 'bog', 'dist', 'gir', 'ppg', 't10'];
var PEER = ['sg', 'form', 'bird', 'dist', 'gir', 't10'];
var BOARD = {};

function boardMeta(stream) {
  if (BOARD[stream]) return Promise.resolve(BOARD[stream]);
  return GR.maybe('scout/' + stream + '.json').then(function (b) { if (b) BOARD[stream] = b; return b; });
}
function fin(e) { return e.st === 'finish' ? (e.tie ? 'T' : '') + e.pos : e.st === 'cut' ? 'MC' : String(e.st || '').toUpperCase(); }

function ratingChart(el, P) {
  var h = (P.history || []).filter(function (x) { return isNum(x[1]); });
  if (!el || h.length < 3) { if (el) el.innerHTML = QK.empty('Too few events', 'The rating line needs three events.'); return; }
  QKC.line(el, { x: h.map(function (x) { return x[0]; }), xType: 'time', series: [{ name: 'Our rating', data: h.map(function (x) { return [x[0], x[1]]; }), color: 'var(--c-1)' }],
    yName: 'Rating (strokes a round v an average tour player)', xName: 'Date (before each event)', ref: { y: 0, label: 'Average tour player' }, endLabels: false, yFmt: function (v) { return GR.signed(v, 1); } });
}
function formChart(el, P) {
  var f = (P.form || []).filter(function (x) { return isNum(x[1]); });
  if (!el || f.length < 3) { if (el) el.innerHTML = QK.empty('Too few events', 'The form chart needs three events with scores.'); return; }
  var good = QK.cssVar('--c-1') || '#7d93ff', bad = QK.cssVar('--neg') || '#ff6a4d';
  QKC.bar(el, { cats: f.map(function (x) { return GR.date(x[0]); }), series: [{ name: 'Strokes gained per round', data: f.map(function (x) { return x[1]; }) }],
    colors: f.map(function (x) { return x[1] >= (isNum(x[3]) ? x[3] : 0) ? good : bad; }), valName: 'Strokes gained per round', catName: 'Event (start date)', fmt: function (v) { return GR.signed(v, 2); } });
}
function peerChart(el, P, bd, key) {
  if (!el || !QKC.distribution || !bd || !P.cur) return;
  var cols = bd.cols || [], iq = cols.indexOf('q'), ik = cols.indexOf(key);
  if (ik < 0) { el.innerHTML = QK.empty('No values for this number', ''); return; }
  var pctm = GR.PCTM[key];
  var vs = (bd.rows || []).filter(function (r) { return r[iq] && isNum(r[ik]); }).map(function (r) { return pctm ? r[ik] * 100 : r[ik]; });
  var me = (P.cur.v || {})[key];
  var meta = (bd.metrics || []).filter(function (m) { return m.id === key; })[0] || { label: key };
  if (vs.length < 10 || !isNum(me)) { el.innerHTML = QK.empty('Not enough to compare on this number', meta.label + ' is not on file for this player.'); return; }
  QKC.distribution(el, { values: vs, binCount: 24, lowerBetter: meta.dir === 'lower', fmt: function (v) { return pctm ? fmt.num(v, 1) + '%' : GR.vfmt(key, v); },
    xName: meta.label + (pctm ? ' (%)' : '') + ' · ' + vs.length + ' regulars', yName: 'Players', marks: [{ x: pctm ? me * 100 : me, label: GR.surname(P.name) }], label: 'Where ' + P.name + ' sits' });
}

GR.page('player', function (el, params) {
  return GR.load('players/' + encodeURIComponent(params.id) + '.json').then(function (P) {
    var stream = P.stream || 'men';
    return boardMeta(stream).then(function (bd) { return [P, bd]; });
  }).then(function (res) {
    if (!el.isConnected) return;
    var P = res[0], bd = res[1];
    var stream = P.stream || 'men';
    var M = {};
    ((bd && bd.metrics) || []).forEach(function (m) { M[m.id] = m; });
    var C = P.cur || null;
    var sm = P.summary || {};
    var tour = (C && C.tour) || sm.tour || (stream === 'women' ? 'lpga' : 'pga');
    var bio = P.bio || {};
    var meta = [];
    if (isNum(bio.age)) meta.push(['Age', String(Math.floor(bio.age))]);
    if (P.cc) meta.push(['Country', P.cc]);
    if (bio.pro) meta.push(['Turned pro', String(bio.pro)]);
    if (isNum(bio.ht)) meta.push(['Height', Math.floor(bio.ht / 12) + '′' + Math.round(bio.ht % 12) + '″']);
    if (bio.born) meta.push(['Born', bio.born]);
    meta.push(['Rounds on file', fmt.num(P.rounds)]);
    var evs = P.events || [];
    var two = evs.filter(function (e) { return C && e.date >= C.from; });
    var wins2 = two.filter(function (e) { return e.st === 'finish' && e.pos === 1; }).length;
    var top10 = two.filter(function (e) { return e.st === 'finish' && e.pos <= 10; }).length;
    var short = '';
    if (C && C.q && C.pc) {
      var ks = HEAD.filter(function (k) { return isNum(C.pc[k]); }).sort(function (a, b) { return C.pc[b] - C.pc[a]; });
      var best = ks.slice(0, 2).map(function (k) { return ((M[k] || {}).label || k).toLowerCase(); });
      var worst = ks.length > 3 ? ((M[ks[ks.length - 1]] || {}).label || '').toLowerCase() : '';
      short = P.name + ' gains ' + GR.signed(C.v.sg, 2) + ' strokes a round on an average field over the last two years (' + QK.ordinal(Math.round(C.pc.sg || 50)) + ' percentile among the regulars), standing out on ' + best.join(' and ') + (worst ? ', and weakest on ' + worst : '') + '.';
    } else short = P.name + ' has ' + fmt.num(P.rounds) + ' rounds in our data' + (C ? ', ' + C.rounds + ' in the last two years: under the 30 rounds for percentiles.' : ', none in the last two years.');
    var html = '<nav class="gr-crumb"><a href="#/scout' + (stream === 'women' ? '?s=women' : '') + '">Scouting Room</a> / ' + esc(P.name) + '</nav>';
    var mk = GR.mark(P.name, tour);
    html += QK.playerHeader({ name: P.name, number: P.rank || '', pos: GR.tourName(tour), kicker: (stream === 'women' ? 'LPGA' : 'Men’s golf') + (P.rank ? ' · ranked ' + P.rank : ''),
      team: { name: GR.tourName(tour), abbr: GR.tourShort(tour), colour: mk.colour, href: '#/fixtures/' + tour }, meta: meta,
      strip: [{ label: 'Our rating', value: GR.rating(P.rt), pctl: C && C.q ? C.pc.rt : null, signal: true, sub: 'strokes a round' },
        { label: 'Rank', value: P.rank ? String(P.rank) : 'unranked', sub: P.ranked ? (stream === 'women' ? 'LPGA' : 'men') : 'needs 10 recent rounds' },
        { label: 'Wins', value: String(wins2), sub: 'last two years, ' + two.length + ' starts' },
        { label: 'Top 10s', value: String(top10), sub: two.length ? Math.round(100 * top10 / two.length) + '% of starts' : '' },
        { label: 'Form', value: C && isNum(C.v.form) ? GR.signed(C.v.form, 2) : GR.rating(P.rt), sub: 'last eight events', pctl: C && C.q ? C.pc.form : null }],
      short: short, follow: GR.followItem(P.pid, P.name, stream) });
    if (isNum(P.wt) && P.wt < GR.THIN) html += QK.note('Thin record: only ' + Math.round(P.wt) + ' recent rounds sit behind this rating, so it can swing a long way on a few results.');
    // percentiles
    var prev = P.prev || null;
    if (C && C.v) {
      var groups = FAMILY.map(function (f) {
        var rows = Object.keys(C.v).filter(function (k) { return M[k] && M[k].family === f[0] && isNum(C.pc[k]); }).map(function (k) {
          return { label: M[k].label, pctl: C.pc[k], value: GR.vfmt(k, C.v[k]), tip: M[k].tip + (M[k].dir === 'lower' ? ' (lower is better; the percentile is turned so higher is better)' : ''), early: !C.q,
            prev: prev && isNum((prev.pc || {})[k]) ? prev.pc[k] : undefined };
        });
        return { label: f[1], rows: rows };
      }).filter(function (g) { return g.rows.length; });
      html += '<div class="qk-g75 gr-gap"><div>' + (groups.length ? QK.pctCard({ title: 'Against the regulars', kicker: 'Last two years', peer: (stream === 'women' ? 'LPGA' : 'men’s') + ' regulars (30+ rounds), every tour on one scale', ringLabel: prev ? String(prev.y) : undefined,
        sample: C.rounds + ' rounds · ' + C.events + ' events since ' + GR.date(C.from), groups: groups }) : QK.empty('No percentiles yet', 'Percentiles need 12 rounds in the last two years.')) +
        QK.explain('<b>How sure are we?</b> ' + C.rounds + ' rounds is ' + (C.rounds < 60 ? 'a small sample: every rate is pulled toward the average (as if 12 average rounds, or 72 average holes, had been added), and a dashed knob marks a percentile still settling.' : 'a solid sample for strokes gained; win and top-10 rates still swing a lot from season to season.') +
          (tour !== 'pga' && stream === 'men' ? ' Ball-striking numbers come from PGA Tour season statistics only: ESPN carries none for the DP World Tour, LIV or the Korn Ferry Tour.' : '')) +
        '</div><div id="pl-tape"></div></div>';
    }
    html += '<div class="qk-g2 gr-gap">' + GR.card('Our rating over time', 'Before each event, against an average tour player of the trailing year.', GR.chart('pl-rt', 280, 'Rating over time')) +
      GR.card('Event by event', 'Strokes gained per round at each of the last 40 events: blue when it beat the rating they brought in, red when it fell short.', GR.chart('pl-form', 280, 'Strokes gained by event')) + '</div>';
    if (C && C.q && bd) html += '<div class="qk-g2 gr-gap">' + GR.card('Among the regulars', 'Every regular on one number, with ' + esc(GR.surname(P.name)) + ' marked.', '<div class="qk-seg" id="pl-pk" role="group" aria-label="Number" style="margin-bottom:10px">' +
      PEER.filter(function (k) { return isNum(C.v[k]); }).map(function (k, i) { return '<button type="button" data-value="' + k + '" aria-pressed="' + (i === 0) + '">' + esc(((M[k] || {}).short) || k) + '</button>'; }).join('') + '</div>' + GR.chart('pl-peer', 240, 'Peer distribution')) +
      GR.card('Most similar players', 'Closest on the percentile profile over the last two years (the average gap in percentile points).', (P.similar || []).length ? '<ul class="gr-list">' + P.similar.map(function (s) {
        return '<li><span>' + GR.playerLink(s.id, s.n) + ' <span class="gr-muted">' + esc(GR.tourShort(s.tour)) + '</span></span><span class="num">' + fmt.num(s.d, 0) + ' pts apart</span></li>'; }).join('') + '</ul>' : QK.empty('Not enough rounds to compare', '')) + '</div>';
    // splits and courses
    var sp = P.splits || [];
    var split = sp.length ? GR.table([{ label: 'Split', align: 'left' }, { label: 'Rounds' }, { label: 'SG/round', title: 'Shrunk toward zero with 12 rounds' }, { label: 'Raw' }],
      sp.map(function (x) { return [{ v: x.label, html: esc(x.label) }, { v: x.n, html: String(x.n) }, { v: x.sg, html: '<b>' + GR.signed(x.sg, 2) + '</b>' }, { v: x.raw, html: GR.signed(x.raw, 2) }]; })) : QK.empty('Too few rounds for splits', '');
    if (C && C.v) {
      var nine = [['Rounds 1 and 2', C.v.sg_e], ['The weekend', C.v.sg_w], ['Front nine', C.v.sg_f], ['Back nine', C.v.sg_b]].filter(function (x) { return isNum(x[1]); });
      if (nine.length) split += GR.note('Rounds and nines: ' + nine.map(function (x) { return x[0].toLowerCase() + ' ' + GR.signed(x[1], 2); }).join(', ') + ' (strokes gained, a nine against the field’s nine).');
    }
    var cs = P.courses || [];
    var course = cs.length ? GR.table([{ label: 'Course', align: 'left' }, { label: 'Rounds' }, { label: 'SG/round' }, { label: 'Fit', title: 'Strokes a round better than the rating they brought, shrunk with 32 rounds' }, { label: 'Last' }],
      cs.map(function (c) { return [{ v: c.name, html: GR.courseLink(c.id, c.name) }, { v: c.rounds, html: String(c.rounds) }, { v: c.sg, html: GR.signed(c.sg, 2) }, { v: c.fit, html: '<b>' + GR.signed(c.fit, 2) + '</b>' }, { v: c.last, html: esc(GR.date(c.last)) }]; })) : QK.empty('No course with eight rounds on file', 'Course history counts single-course events.');
    html += '<div class="qk-g2 gr-gap">' + GR.card('Splits', 'Strokes gained per round over the last two years, by tour, event, tee-time wave and course length.', split, { flush: true }) +
      GR.card('Course history', 'The courses this player plays best and worst against their own rating (eight rounds or more). Shown, not used: course history did not improve our forecasts out of sample.', course, { flush: true, html: true }) + '</div>';
    // year by year
    var smy = {};
    (P.sm || []).forEach(function (s) { smy[s.y] = s; });
    var yrs = {};
    (P.seasons || []).forEach(function (s) { var y = s.season; yrs[y] = yrs[y] || { y: y, starts: 0, wins: 0, top10: 0, cuts: 0, earn: 0, tours: [] }; var o = yrs[y]; o.starts += s.starts; o.wins += s.wins; o.top10 += s.top10; o.cuts += s.cuts; o.earn += s.earn || 0; o.tours.push(GR.tourShort(s.tour)); });
    var yl = Object.keys(yrs).map(Number).sort(function (a, b) { return b - a; });
    var cell = function (s, k) { var v = s && s.v ? s.v[k] : null; return { v: isNum(v) ? v : -99, html: isNum(v) ? GR.vfmt(k, v) + (s.q && s.pc && isNum(s.pc[k]) ? GR.pctChip(s.pc[k]) : '') : '' }; };
    html += GR.card('Year by year', 'Strokes gained and the hole numbers per calendar year; the chip is the percentile among that year’s regulars (25+ rounds).', GR.table([{ label: 'Year' }, { label: 'Tours', align: 'left' }, { label: 'Starts' }, { label: 'Wins' }, { label: 'Top 10' }, { label: 'Cuts' }, { label: 'Earnings' }, { label: 'Rounds' }, { label: 'SG/rd' }, { label: 'Birdie%' }, { label: 'Bogey%' }, { label: 'Dist' }, { label: 'GIR%' }, { label: 'Putts/GIR' }],
      yl.map(function (y) { var o = yrs[y], s = smy[y]; return [{ v: y, html: String(y) }, { v: o.tours.join(' '), html: esc(o.tours.join(', ')) }, { v: o.starts, html: String(o.starts) }, { v: o.wins, html: String(o.wins) }, { v: o.top10, html: String(o.top10) }, { v: o.cuts, html: String(o.cuts) },
        { v: o.earn, html: GR.money(o.earn, true) }, { v: s ? s.n : 0, html: s ? String(s.n) : '' }, cell(s, 'sg'), cell(s, 'bird'), cell(s, 'bog'), cell(s, 'dist'), cell(s, 'gir'), cell(s, 'ppg')]; }), { maxHeight: 520 }), { flush: true });
    // events
    html += GR.card('Every event', 'Our chance before the event beside the finish, and strokes gained per round there.', GR.table([{ label: 'Date', align: 'left' }, { label: 'Event', align: 'left' }, { label: 'Tour' }, { label: 'Finish' }, { label: 'To par' }, { label: 'SG/rd' }, { label: 'Our win chance' }, { label: 'Our top 10' }, { label: 'Rating in' }, { label: 'Earnings' }],
      evs.map(function (e) { return [{ v: e.date, html: esc(GR.date(e.date)) }, { v: e.name, html: GR.eventLink(e.id, e.name) + (e.major ? ' ' + QK.tag('Major') : '') }, { v: e.tour, html: esc(GR.tourShort(e.tour)) },
        { v: e.st === 'finish' ? e.pos : 999, html: esc(fin(e)) }, { v: isNum(e.tp) ? e.tp : 99, html: GR.toParHTML(e.tp) }, { v: isNum(e.sg) ? e.sg : -99, html: GR.signed(e.sg, 2) },
        { v: e.win || 0, html: GR.pct(e.win) }, { v: e.t10 || 0, html: GR.pct(e.t10) }, { v: isNum(e.rt) ? e.rt : -99, html: GR.rating(e.rt) }, { v: e.earn || 0, html: GR.money(e.earn, true) }]; }), { maxHeight: 640 }), { flush: true });
    el.innerHTML = html;
    QK.sortable(el);
    document.title = P.name + ' · The Quant Green';
    GR.safe(function () { ratingChart(el.querySelector('#pl-rt'), P); });
    GR.safe(function () { formChart(el.querySelector('#pl-form'), P); });
    var pk = PEER.filter(function (k) { return C && C.v && isNum(C.v[k]); })[0];
    GR.safe(function () { if (pk) peerChart(el.querySelector('#pl-peer'), P, bd, pk); });
    var seg = el.querySelector('#pl-pk');
    if (seg) QK.seg(seg, function (k) { GR.safe(function () { peerChart(el.querySelector('#pl-peer'), P, bd, k); }); });
    // the tale of the tape against the closest match
    var sim = (P.similar || [])[0];
    var tapeEl = el.querySelector('#pl-tape');
    if (sim && tapeEl && C && C.q) {
      GR.maybe('players/' + encodeURIComponent(sim.id) + '.json').then(function (O) {
        if (!tapeEl.isConnected || !O || !O.cur) return;
        var ids = HEAD.filter(function (k) { return isNum(C.v[k]) && isNum(O.cur.v[k]) && M[k]; });
        var ot = O.cur.tour || 'pga';
        tapeEl.innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: esc(GR.surname(P.name) + ' or ' + GR.surname(O.name) + '?'), html: true }) +
          QK.tape({ left: { name: P.name, short: GR.surname(P.name), sub: GR.tourShort(tour), colour: GR.TOUR_COL[tour], href: GR.playerHref(P.pid) },
            right: { name: O.name, short: GR.surname(O.name), sub: GR.tourShort(ot), colour: GR.TOUR_COL[ot] === GR.TOUR_COL[tour] ? '#8a8f9c' : GR.TOUR_COL[ot], href: GR.playerHref(O.pid) },
            rows: ids.map(function (k) { return { label: M[k].label, a: C.v[k], b: O.cur.v[k], ta: GR.vfmt(k, C.v[k]), tb: GR.vfmt(k, O.cur.v[k]), pa: C.pc[k], pb: O.cur.pc[k], better: M[k].dir === 'lower' ? 'low' : 'high' }; }) }) +
          (QK.verdicts ? QK.verdicts([[P, C, O.cur], [O, O.cur, C]].map(function (x) {
            var best = null, gap = 0;
            ids.forEach(function (k) { var a = x[1].pc[k], b = x[2].pc[k]; if (isNum(a) && isNum(b) && a - b > gap) { gap = a - b; best = k; } });
            return best ? { title: 'Better on ' + (M[best].short || best).toLowerCase(), who: GR.surname(x[0].name), text: 'better on ' + M[best].label.toLowerCase() + ' (' + GR.vfmt(best, x[1].v[best]) + ', ' + QK.ordinal(Math.round(x[1].pc[best])) + ' percentile).' } : null;
          }).filter(Boolean)) : '');
      });
    }
  });
});
})();
