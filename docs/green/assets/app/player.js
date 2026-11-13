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

/* ── next and last event (the Rink player page's "what to watch" and "last game" pair, for golf) ── */

/* this week's event the player is entered in: index.json's week (the player's own tour first), then each event file
   until the player turns up in its field. Resolves { e, p } or null. */
function findNext(P, stream, tour) {
  return GR.maybe('index.json').then(function (ix) {
    var wk = ((ix && ix.week) || []).filter(function (w) { return w.page && w.status !== 'final' && GR.STREAM_OF[w.tour] === stream; })
      .sort(function (a, b) { return (b.tour === tour ? 1 : 0) - (a.tour === tour ? 1 : 0); });
    var chain = Promise.resolve(null);
    wk.forEach(function (w) {
      chain = chain.then(function (hit) {
        if (hit) return hit;
        return GR.maybe('events/' + encodeURIComponent(w.id) + '.json').then(function (e) {
          var p = e && (e.players || []).filter(function (x) { return String(x.pid) === String(P.pid); })[0];
          return p ? { e: e, p: p } : null;
        });
      });
    });
    return chain;
  });
}
/* where the player is in a live event: "-3 after round 1", "-5 through 12 in round 2" */
function progress(p) {
  var r = p.r || [], th = p.thru || [], done = 0, at = '';
  for (var k = 0; k < r.length; k++) {
    if (isNum(r[k])) done = k + 1;
    else if (isNum(th[k]) && th[k] > 0 && th[k] < 18) at = 'through ' + th[k] + ' in round ' + (k + 1);
  }
  return at || (done ? 'after round ' + done : 'not started');
}
function nextHTML(e, p, P) {
  var live = e.status === 'live' && !!e.live;
  var pl = e.players || [];
  var rk = 1 + pl.filter(function (q) { return (q.win || 0) > (p.win || 0); }).length;
  var c = e.course || {};
  var sur = esc(GR.surname(P.name));
  var tiles = live ? [
    { label: 'Position', value: GR.position(p) || 'Not started', text: !GR.position(p), sub: (GR.toPar(p.tp) || 'level') + ' ' + progress(p) },
    { label: 'Live chance to win', value: GR.pct(p.lwin), signal: true, sub: 'from the score and the holes left' },
    { label: 'Live top 10', value: GR.pct(p.lt10), sub: isNum(p.lcut) ? 'make the cut ' + GR.pct(p.lcut) : '' },
    { label: 'Before the start', value: GR.pct(p.win), sub: 'to win, ' + GR.nthBest(rk) + ' of ' + pl.length + '; top 10 ' + GR.pct(p.t10) }
  ] : [
    { label: 'Our chance to win', value: GR.pct(p.win), signal: true, sub: GR.nthBest(rk) + ' in a field of ' + pl.length },
    { label: 'Top 10', value: GR.pct(p.t10), sub: isNum(p.t20) ? 'top 20 ' + GR.pct(p.t20) : '' },
    isNum(p.cut) && e.cut ? { label: 'Make the cut', value: GR.pct(p.cut), sub: 'top ' + e.cut.count + ' and ties after round ' + e.cut.round } : null,
    isNum(p.xr) ? { label: 'Expected finish', value: QK.ordinal(Math.round(p.xr)), text: true, sub: 'the average over ' + fmt.num(e.sims) + ' simulated tournaments' } : null
  ];
  var pp = live ? p.lwin : p.win;
  var sure = '<b>How sure are we?</b> ' + sur + '’s ' + GR.pct(pp) + (live ? ' now' : '') + ' comes off ' + GR.oneIn(pp) + '.' +
    (live ? ' Live chances start from the score and the holes left; before the start it was ' + GR.pct(p.win) + '.' : ' From ' + fmt.num(e.sims) + ' simulated tournaments, with a rating built only from rounds played before the event.') +
    (isNum(p.wt) && p.wt < GR.THIN ? ' Only ' + Math.round(p.wt) + ' recent rounds sit behind the rating, so read it lightly.' : '');
  return QK.sectionHead({ kicker: live ? 'Live now' : 'This week', title: esc(GR.shortEvent(e.name)), html: true,
      sub: esc((GR.shortEvent(e.name) !== e.name ? e.name + ' · ' : '') + GR.tourName(e.tour) + ' · ' + GR.dates(e.start, e.end) + (c.name ? ' · ' + c.name : '') + ' · ' + GR.asOf(live ? e.live.at : e.updated_at)) }) +
    QK.stats(tiles.filter(Boolean)) + QK.explain(sure) +
    '<p class="gr-meta" style="margin-top:10px"><a href="#/event/' + encodeURIComponent(e.id) + '">' + (live ? 'The live leaderboard and every player’s chances' : 'Every player’s chances') + ' →</a></p>';
}
/* the last event: the finish against what we expected, the rounds against the field par (the event file) */
function lastHTML(ev, E, P) {
  var sur = esc(GR.surname(P.name));
  var p = E ? (E.players || []).filter(function (x) { return String(x.pid) === String(P.pid); })[0] : null;
  var fp = {};
  ((E && E.round_avg) || []).forEach(function (r) { fp[r.round] = r.field_par; });
  var rows = [];
  /* a final event's round score where the feed gave only the score against par: par + to par (one course only) */
  var par = E && E.status === 'final' && E.course && isNum(E.course.par) && !((E.courses || []).length > 1) ? E.course.par : null;
  if (p) (p.r || []).forEach(function (s0, k) {
    var tp = (p.rtp || [])[k], s = isNum(s0) ? s0 : (isNum(par) && isNum(tp) ? par + tp : null);
    if (isNum(s)) rows.push({ k: k + 1, s: s, tp: tp, fp: fp[k + 1], sg: isNum(fp[k + 1]) ? fp[k + 1] - s : null });
  });
  var finTxt = ev.st === 'finish' && isNum(ev.pos) ? (ev.pos === 1 && !ev.tie ? 'Won' : ev.tie ? 'T' + ev.pos : QK.ordinal(ev.pos)) : ev.st === 'cut' ? 'Missed cut' : String(ev.st || '').toUpperCase();
  var xr = p && isNum(p.xr) ? p.xr : null;
  var line = '<b>' + sur + ':</b> ' + (isNum(ev.sg) ? GR.signed(ev.sg, 2) + ' strokes gained a round against the field' : 'no strokes gained on file') +
    (isNum(xr) ? '; we expected about ' + QK.ordinal(Math.round(xr)) + (ev.st === 'finish' && isNum(ev.pos) ? ' and the finish was ' + (ev.tie ? 'T' : '') + ev.pos + (isNum(p.beat) && Math.round(p.beat) !== 0 ? ', ' + Math.abs(Math.round(p.beat)) + ' places ' + (p.beat > 0 ? 'better' : 'worse') : '') : '') : '') +
    '. Our chances before the start: win ' + GR.pct(ev.win) + ', top 10 ' + GR.pct(ev.t10) + (isNum(ev.rt) ? ', with a rating of ' + GR.rating(ev.rt) + ' coming in' : '') + '.';
  var tbl = rows.length ? GR.table([{ label: 'Round' }, { label: 'Score' }, { label: 'To par' }, { label: 'Field par', title: 'What an average tour player would have shot that day: our strokes-gained baseline' }, { label: 'Strokes gained', title: 'Field par minus the score' }],
    rows.map(function (r) { return [{ v: r.k, html: 'R' + r.k }, { v: r.s, html: String(r.s) }, { v: r.tp, html: GR.toParHTML(r.tp) }, { v: r.fp, html: isNum(r.fp) ? fmt.num(r.fp, 2) : '' }, { v: r.sg, html: '<b>' + GR.signed(r.sg, 2) + '</b>' }]; })) : '';
  var html = QK.sectionHead({ kicker: 'Last event', title: esc(finTxt + (isNum(ev.tp) ? ' · ' + GR.toPar(ev.tp) : '')), html: true,
      sub: GR.eventLink(ev.id, ev.name) + ' · ' + esc(GR.date(ev.date)) + (E ? ' · ' + esc(GR.asOf(E.updated_at)) : '') }) +
    '<article class="qk-card"><div class="qk-card-body"><p class="gr-last-line">' + line + '</p>' +
    (rows.length > 1 ? GR.chart('pl-last', 190, 'Strokes gained by round') : '') + '</div>' + (tbl ? '<div class="qk-card-body flush" data-no-tools>' + tbl + '</div>' : '') + '</article>';
  return { html: html, rows: rows };
}
function lastChart(host, rows) {
  var tb = host && host.querySelector('#pl-last');
  rows = (rows || []).filter(function (r) { return isNum(r.sg); });
  if (!tb || rows.length < 2) return;
  QKC.bar(tb, { cats: rows.map(function (r) { return 'Round ' + r.k; }), series: [{ name: 'Strokes gained', data: rows.map(function (r) { return r.sg; }) }], diverging: true, labels: true,
    fmt: function (v) { return GR.signed(v, 2); }, catName: 'Round', valName: 'Strokes gained v the field', label: 'Strokes gained by round' });
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
    var careerW = evs.filter(function (e) { return e.st === 'finish' && e.pos === 1; }).length, careerT = evs.filter(function (e) { return e.st === 'finish' && e.pos <= 10; }).length;
    var short = '';
    if (C && C.q && C.pc) {
      var ks = HEAD.filter(function (k) { return isNum(C.pc[k]); }).sort(function (a, b) { return C.pc[b] - C.pc[a]; });
      var best = ks.slice(0, 2).map(function (k) { return ((M[k] || {}).label || k).toLowerCase(); });
      var worst = ks.length > 3 ? ((M[ks[ks.length - 1]] || {}).label || '').toLowerCase() : '';
      short = P.name + ' gains ' + GR.signed(C.v.sg, 2) + ' strokes a round on an average field over the last two years (' + QK.ordinal(Math.round(C.pc.sg || 50)) + ' percentile among the regulars), standing out on ' + best.join(' and ') + (worst ? ', and weakest on ' + worst : '') + '.';
    } else short = P.name + ' has ' + fmt.num(P.rounds) + ' rounds in our data' + (C ? ', ' + C.rounds + ' in the last two years: under the 30 rounds for percentiles.' : ', none in the last two years.');
    var html = '<nav class="gr-crumb"><a href="#/scout' + (stream === 'women' ? '?s=women' : '') + '">Scouting Room</a> / ' + esc(P.name) + '</nav>';
    var mk = GR.mark(P.name, tour);
    /* the rank is the outlined face (no '#' chip: it is not a shirt number); the tour is the team chip, once */
    html += QK.playerHeader({ name: P.name, face: P.rank ? String(P.rank) : undefined, kicker: (stream === 'women' ? 'LPGA' : 'Men’s golf') + (P.rank ? ' · ranked ' + P.rank : ''),
      team: { name: GR.tourName(tour), abbr: GR.tourShort(tour), colour: mk.colour, href: '#/fixtures/' + tour }, meta: meta,
      strip: [{ label: 'Our rating', value: GR.rating(P.rt), pctl: C && C.q ? C.pc.rt : null, signal: true, sub: 'strokes a round' },
        { label: 'Rank', value: P.rank ? String(P.rank) : 'unranked', sub: P.ranked ? (stream === 'women' ? 'LPGA' : 'men') : 'needs 10 recent rounds' },
        two.length ? { label: 'Wins', value: String(wins2), sub: 'last two years, ' + two.length + ' starts' } : { label: 'Career wins', value: String(careerW), sub: 'in ' + evs.length + ' starts on file' + (evs.length ? ', the last in ' + String(evs[0].date).slice(0, 4) : '') },
        two.length ? { label: 'Top 10s', value: String(top10), sub: Math.round(100 * top10 / two.length) + '% of starts, last two years' } : { label: 'Career top 10s', value: String(careerT), sub: evs.length ? Math.round(100 * careerT / evs.length) + '% of starts on file' : '' },
        C && isNum(C.v.form) ? { label: 'Form', value: GR.signed(C.v.form, 2), sub: 'strokes gained a round, last eight events', pctl: C.q ? C.pc.form : null }
          : (isNum(sm.sg12) ? { label: '12 months', value: GR.signed(sm.sg12, 2), sub: 'strokes gained a round over the last 12 months' } : null)].filter(Boolean),
      short: short, follow: GR.followItem(P.pid, P.name, stream) });
    if (isNum(P.wt) && P.wt < GR.THIN) html += QK.note('Thin record: only ' + Math.round(P.wt) + ' recent round' + (Math.round(P.wt) === 1 ? '' : 's') + ' sit' + (Math.round(P.wt) === 1 ? 's' : '') + ' behind this rating, so it can swing a long way on a few results.');
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
        '</div><div class="gr-stack"><div id="pl-tape"></div><div id="pl-next"></div><div id="pl-lastev"></div></div></div>';
    } else {
      html += '<div class="gr-pair gr-gap"><div id="pl-next"></div><div id="pl-lastev"></div></div>';
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
    /* the event log, as the Rink's game log: the best finish highlighted (the latest of equal bests) */
    var bestI = -1;
    evs.forEach(function (e, i) { if (e.st === 'finish' && isNum(e.pos) && (bestI < 0 || e.pos < evs[bestI].pos)) bestI = i; });
    var bestE = bestI >= 0 ? evs[bestI] : null;
    html += '<section class="qk-section gr-sec">' + QK.sectionHead({ kicker: 'Event log', title: 'Every event', html: true, sub: 'Our chance before each event beside the finish, and strokes gained per round there.' +
      (bestE ? ' The best finish, ' + (bestE.pos === 1 && !bestE.tie ? 'a win' : esc(fin(bestE))) + ' at the ' + esc(bestE.name) + ' (' + esc(GR.date(bestE.date)) + '), is highlighted.' : '') }) +
      GR.card('', '', GR.table([{ label: 'Date', align: 'left' }, { label: 'Event', align: 'left' }, { label: 'Tour' }, { label: 'Finish' }, { label: 'To par' }, { label: 'SG/rd' }, { label: 'Our win chance' }, { label: 'Our top 10' }, { label: 'Rating in' }, { label: 'Earnings' }],
      evs.map(function (e, i) { return { _class: i === bestI ? 'hl' : '', cells: [{ v: e.date, html: esc(GR.date(e.date)) }, { v: e.name, html: GR.eventLink(e.id, e.name) + (e.major ? ' ' + QK.tag('Major') : '') }, { v: e.tour, html: esc(GR.tourShort(e.tour)) },
        { v: e.st === 'finish' ? e.pos : 999, html: esc(fin(e)) }, { v: isNum(e.tp) ? e.tp : 99, html: GR.toParHTML(e.tp) }, { v: isNum(e.sg) ? e.sg : -99, html: GR.signed(e.sg, 2) },
        { v: e.win || 0, html: GR.pct(e.win) }, { v: e.t10 || 0, html: GR.pct(e.t10) }, { v: isNum(e.rt) ? e.rt : -99, html: GR.rating(e.rt) }, { v: e.earn || 0, html: GR.money(e.earn, true) }] }; }), { maxHeight: 640 }), { flush: true }) + '</section>';
    el.innerHTML = html;
    QK.sortable(el);
    document.title = P.name + ' · The Quant Green';
    GR.safe(function () { ratingChart(el.querySelector('#pl-rt'), P); });
    GR.safe(function () { formChart(el.querySelector('#pl-form'), P); });
    var pk = PEER.filter(function (k) { return C && C.v && isNum(C.v[k]); })[0];
    GR.safe(function () { if (pk) peerChart(el.querySelector('#pl-peer'), P, bd, pk); });
    var seg = el.querySelector('#pl-pk');
    if (seg) QK.seg(seg, function (k) { GR.safe(function () { peerChart(el.querySelector('#pl-peer'), P, bd, k); }); });
    // this week's event (if entered) and the last event, beside the rail
    var nx = el.querySelector('#pl-next');
    if (nx) findNext(P, stream, tour).then(function (hit) { if (hit && nx.isConnected) nx.innerHTML = nextHTML(hit.e, hit.p, P); }, function () { /* nothing this week */ });
    var lastEv = evs[0], lx = el.querySelector('#pl-lastev');
    if (lx && lastEv) {
      lx.innerHTML = lastHTML(lastEv, null, P).html;
      GR.maybe('events/' + encodeURIComponent(lastEv.id) + '.json').then(function (E) {
        if (!E || !lx.isConnected) return;
        var L = lastHTML(lastEv, E, P);
        lx.innerHTML = L.html;
        GR.safe(function () { lastChart(lx, L.rows); });
      });
    }
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
