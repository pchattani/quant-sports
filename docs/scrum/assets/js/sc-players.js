/* The Quant Scrum — the player page (the Scouting Room is sc-scout.js): the hero, per-80 rates with percentiles within
 * the position (last year's ring), the tale of the tape against the closest match with verdicts, the last test, game value
 * test by test, where the player sits among the position, value year by year, splits, tests and points year by year and
 * the game log. Reads <S>/players.json (the Board, column-oriented) and
 * <S>/players/<id>.json (oddsmarkets/rugby/pages.py). Metric names, units and explanations come from the rugby spec
 * (docs/_design/metrics/rugby.json through QK.spec). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;
var PCT = { tkpct: 1, kpct: 1, lopct: 1 };
var HEAD = {
  front_row: ['val80', 'tk', 'tkpct', 'car', 'lopct', 'rk', 'inv', 'pc'], lock: ['val80', 'tk', 'tkpct', 'car', 'm', 'rk', 'ml', 'pc'],
  back_row: ['val80', 'tk', 'car', 'm', 'db', 'tkpct', 'inv', 'pc'], halves: ['val80', 'pts', 'pas', 'kfh', 'kpct', 'gkp', 'ta', 'tk'],
  centres: ['val80', 'm', 'cb', 'db', 'car', 'off', 'ta', 'tk'], back_three: ['val80', 'm', 'cb', 'db', 'tries', 'mpc', 'kfh', 'tk']
};
SC.vfmt = function (id, v) {
  if (!isNum(v)) return '—';
  if (PCT[id]) return Math.round(v * 100) + '%';
  if (id === 'val80') return SC.signed(v, 1);
  return Math.abs(v) >= 20 ? fmt.num(v, 0) : fmt.num(v, 1);
};

/* ── the player page ────────────────────────────────────────────────── */
var FAMILY = [['value', 'Value'], ['scoring', 'Scoring'], ['creating', 'Creating'], ['carrying', 'Carrying'], ['defence', 'Defence'], ['set piece', 'Set piece'], ['breakdown', 'Breakdown and work'], ['discipline', 'Discipline and handling'], ['kicking', 'Kicking']];
var SPLIT_COLS = [['val80', 'Value'], ['m', 'Metres'], ['car', 'Carries'], ['cb', 'Breaks'], ['tk', 'Tackles'], ['tkpct', 'Tackle %'], ['pc', 'Pens'], ['pts', 'Points']];

function gameChart(el, S, Pp) {
  var g = (Pp.log || []).filter(function (x) { return isNum(x.gv); }).slice().reverse();
  if (!el || !window.QKC || g.length < 3) return false;
  var good = QK.cssVar('--c-1') || '#7d93ff', bad = QK.cssVar('--neg') || '#ff6a4d';
  QKC.bar(el, { cats: g.map(function (x) { return SC.date(x.date) + ' ' + (x.h ? 'v ' : '@ ') + SC.tabbr(S, x.opp); }),
    series: [{ name: 'Game value', data: g.map(function (x) { return x.gv; }), color: good }], colors: g.map(function (x) { return x.res === 'W' ? good : bad; }),
    valName: 'Game value (points of margin)', catName: 'Test (date and opponent)', fmt: function (v) { return SC.signed(v, 1); } });
  return true;
}
function valueChart(el, Pp) {
  var ss = (Pp.seasons || []).filter(function (s) { return s.q && s.v && isNum(s.v.val80); });
  if (!el || !window.QKC || ss.length < 2) return false;
  QKC.line(el, { x: ss.map(function (s) { return String(s.y); }), series: [{ name: 'Scrum value per 80', data: ss.map(function (s) { return s.v.val80; }), color: 'var(--c-1)' }],
    yName: 'Scrum value per 80 (points)', xName: 'Year', ref: { y: 0, label: 'Replacement level' }, endLabels: false, yFmt: function (v) { return SC.signed(v, 1); } });
  return true;
}
function peerChart(el, S, Pp, bd, key) {
  if (!el || !window.QKC || !QKC.distribution || !bd || !Pp.cur) return;
  var cols = bd.cols || [], ig = cols.indexOf('grp'), iq = cols.indexOf('q'), ik = cols.indexOf(key);
  if (ig < 0 || ik < 0) return;
  var vs = (bd.rows || []).filter(function (r) { return r[ig] === Pp.grp && r[iq] && isNum(r[ik]); }).map(function (r) { return PCT[key] ? r[ik] * 100 : r[ik]; });
  var me = Pp.cur.v ? Pp.cur.v[key] : null;
  if (vs.length < 10 || !isNum(me)) { el.innerHTML = QK.empty('Too few regulars to compare', ''); return; }
  var lab = ((BOARD_META && (BOARD_META.metrics || []).filter(function (m) { return m.id === key; })[0]) || {}).label || key;
  var low = ((BOARD_META && (BOARD_META.metrics || []).filter(function (m) { return m.id === key; })[0]) || {}).dir === 'lower';
  QKC.distribution(el, { values: vs, binCount: 22, lowerBetter: low, fmt: function (v) { return PCT[key] ? Math.round(v) + '%' : fmt.num(v, Math.abs(v) >= 20 ? 0 : 1); },
    xName: lab + (PCT[key] ? ' (%)' : '') + ' · ' + vs.length + ' regular ' + (SC.GROUP[Pp.grp] || '').toLowerCase(), yName: 'Players',
    marks: [{ x: PCT[key] ? me * 100 : me, label: QK.surname(Pp.name) }], label: 'Where ' + Pp.name + ' sits' });
}
var BOARD_META = null;

function seasonChart(el, Pp) {
  if (!el || !window.QKC || !Pp.caps_by_year || Pp.caps_by_year.length < 2) return;
  var cats = Pp.caps_by_year.map(function (x) { return String(x[0]); });
  QKC.bar(el, { cats: cats, series: [{ name: 'Tests', data: Pp.caps_by_year.map(function (x) { return x[1]; }), color: 'var(--c-1)' }], valName: 'Tests played', catName: 'Year', labels: true });
}

/* The next test and the last one. Next: the side's next test as the scoreboard bug (QK.previewCard layout 'bug'), only
   when the player played in one of the side's last three tests (a recent pick, said to be the side's fixture, not a
   named 23). Last: the player's last test titled with the score, home first, as the kit's game card with our pre-test
   call (the team file's results), the player's line and game value. */
function nextLast(S, Pp, T) {
  var L0 = (Pp.log || [])[0];
  var res = ((T || {}).results || []).filter(function (r) { return isNum(r.hs); });
  var cut = res.length ? String((res[Math.min(2, res.length - 1)] || {}).date || '').slice(0, 10) : '';
  var nx = T && L0 && cut && String(L0.date).slice(0, 10) >= cut ? (T.next || [])[0] : null;
  var out = '';
  if (nx) {
    var rel = QK.fmt.relDay ? QK.fmt.relDay(nx.date) : '';
    out += '<div>' + QK.sectionHead({ kicker: rel === 'Today' ? 'What to watch today' : 'Next up · ' + SC.tname(S, Pp.team), title: esc(SC.tname(S, nx.home) + ' v ' + SC.tname(S, nx.away)), sub: esc(SC.compName(nx.comp) + (nx.venue ? ' · ' + nx.venue : '')), html: true }) +
      QK.previewCard(SC.game(S, nx), { layout: 'bug', homeFirst: true, noun: 'test', note: SC.howSure(S, nx) }) +
      U.note('The side’s next test: ' + esc(QK.surname(Pp.name)) + ' played in ' + (String(L0.date).slice(0, 10) === String(res[0].date).slice(0, 10) ? 'the last one' : 'one of the last three') + '; the matchday 23 is named a few days before.' +
        (isNum(nx.m) ? ' We expect ' + esc(SC.margin(S, nx)) + (isNum(nx.t) ? ', about ' + Math.round(nx.t) + ' points in all' : '') + '.' : '') + ' <a href="' + esc(SC.matchHref(S, nx.id)) + '">The match page →</a>') + '</div>';
  }
  if (L0) {
    var c = res.filter(function (r) { return String(r.id) === String(L0.id); })[0];
    var ts = L0.sc || [];
    if (!c && isNum(ts[0])) c = { id: L0.id, date: L0.date, comp: L0.comp, status: 'final', home: L0.h ? Pp.team : L0.opp, away: L0.h ? L0.opp : Pp.team, hs: L0.h ? ts[0] : ts[1], as: L0.h ? ts[1] : ts[0] };
    var ls = L0.s || {}, bits = [];
    [['pts', 'points'], ['tries', 'tries'], ['m', 'metres'], ['car', 'carries'], ['cb', 'clean breaks'], ['tk', 'tackles'], ['mt', 'missed tackles'], ['pc', 'penalties']].forEach(function (k) { if (ls[k[0]]) bits.push(ls[k[0]] + ' ' + k[1]); });
    var ttl = c && isNum(c.hs) ? SC.tabbr(S, c.home) + ' ' + SC.scoreText(c.hs, c.as, c.ro) + ' ' + SC.tabbr(S, c.away) : SC.tabbr(S, Pp.team) + ' ' + (L0.h ? 'v ' : 'at ') + SC.tname(S, L0.opp);
    var pc = c && c.p ? (String(c.home) === String(Pp.team) ? c.p[0] : c.p[2]) : null;
    var line = '<p class="sc-last"><span class="sc-res ' + L0.res + '">' + L0.res + '</span> ' + esc(Pp.name) + ': ' + (L0.st ? 'started in the ' + L0.j + ' shirt' : 'off the bench') + ', ' + L0.min + ' minutes' +
      (bits.length ? '; ' + esc(bits.join(', ')) : '') + (isNum(L0.gv) ? '. Game value <b class="sc-ours ' + SC.cls(L0.gv) + '">' + SC.signed(L0.gv, 1) + '</b> points of margin above a replacement-level ' + esc(SC.GROUP1[Pp.grp] || 'player') + '.' : '.') + '</p>';
    /* alone (no next test), the card runs the page width with the game card and the player's line side by side */
    out += '<div>' + QK.sectionHead({ kicker: 'Last test', title: esc(ttl), sub: esc(SC.date(L0.date) + ' · ' + SC.compName(L0.comp)), html: true }) +
      U.card('', '', '<div class="sc-nl-gc">' + (c ? QK.gameCard(SC.game(S, c), { sport: false, homeFirst: true, why: false, market: false, form: false }) : '') + '</div><div>' + line +
        (isNum(pc) ? QK.explain('<b>Our pre-test call.</b> We gave ' + esc(SC.tname(S, Pp.team)) + ' ' + SC.pct(pc) + (L0.res === 'W' ? (pc >= 0.5 ? ': as expected.' : ': an upset win.') : L0.res === 'L' ? (pc >= 0.5 ? ': an upset defeat.' : ': as expected.') : ': a draw.')) : '') +
        '<p class="sc-note"><a href="' + esc(SC.matchHref(S, L0.id)) + '">The match page: the score race, the stat lines and both 23s →</a></p></div>', { cls: nx ? '' : 'sc-nl1' }) + '</div>';
  }
  return out ? '<div class="' + (nx && L0 ? 'qk-g2 ' : '') + 'sc-gap sc-nl">' + out + '</div>' : '';
}

SC.route('player', function (page, P) {
  var S = P.S, pid = P.id;
  page.innerHTML = QK.skeleton('card', 2);
  return Promise.all([SC.load(S + '/players/' + pid + '.json'), BOARD_META ? Promise.resolve(BOARD_META) : SC.load(S + '/players.json')]).then(function (res) {
    var Pp = res[0];
    /* the side's team file (its next test and the last one's pre-test call), a file the site already publishes */
    return (SC.ok(Pp) && Pp.team ? SC.load(S + '/teams/' + Pp.team + '.json') : Promise.resolve(null)).then(function (T) { return draw(res[0], res[1], SC.ok(T) ? T : null); });
  });
  function draw(Pp, bd, TM) {
    if (SC.ok(bd)) BOARD_META = bd;
    if (!SC.ok(Pp)) { page.innerHTML = U.head('Player', '', SC.SNAME[S]) + U.missing('This player page', Pp); return; }
    var M = {};
    ((bd && bd.metrics) || []).forEach(function (m) { M[m.id] = m; });
    var t = SC.team(S, Pp.team) || {};
    var C = Pp.cur || null;
    var jersey = (Pp.log || []).map(function (g) { return g.j; }).filter(isNum);
    var cnt = {};
    jersey.forEach(function (j) { cnt[j] = (cnt[j] || 0) + 1; });
    var num = Object.keys(cnt).sort(function (a, b) { return cnt[b] - cnt[a]; })[0];
    var bio = Pp.bio || {};
    var meta = [];
    if (isNum(Pp.age)) meta.push(['Age', String(Math.floor(Pp.age))]);
    var ph = Pp.phys || {};
    if (bio.ht_cm) meta.push(['Height', bio.ht_cm + ' cm' + (isNum(ph.ht_pct) ? ' (' + QK.ordinal(ph.ht_pct) + ' pct)' : '')]);
    if (bio.wt_kg) meta.push(['Weight', bio.wt_kg + ' kg' + (isNum(ph.wt_pct) ? ' (' + QK.ordinal(ph.wt_pct) + ' pct)' : '')]);
    if (bio.born) meta.push(['Born', bio.born]);
    meta.push(['Tests', String(Pp.caps)]);
    if (Pp.wcaps && isNum(Pp.wcaps.caps)) meta.push(['Career caps', String(Pp.wcaps.caps)]);
    if (Pp.capt) meta.push(['Captain', Pp.capt + ' times']);
    var val = C && C.v ? C.v.val80 : null;
    var gname = SC.GROUP[Pp.grp] || 'position';
    var short = '';
    if (C && C.q && C.pc) {
      var rel = HEAD[Pp.grp] || HEAD.back_row;   /* only the measures that matter for the position */
      var ks = Object.keys(C.pc).filter(function (k) { return k !== 'val80' && rel.indexOf(k) >= 0 && isNum(C.pc[k]); }).sort(function (a, b) { return C.pc[b] - C.pc[a]; });
      var best = ks.slice(0, 2).map(function (k) { return ((M[k] || {}).label || k).toLowerCase(); });
      var worst = ks.length ? ((M[ks[ks.length - 1]] || {}).label || '').toLowerCase() : '';
      short = Pp.name + ' stands out among ' + gname.toLowerCase() + ' on ' + best.join(' and ') + ', and is weakest on ' + worst + '. Scrum value ' + SC.signed(val, 1) + ' points per 80 above a replacement ' + (SC.GROUP1[Pp.grp] || 'player') + ' (' + QK.ordinal(Math.round(C.pc.val80 || 50)) + ' percentile).';
    } else short = Pp.name + ' has ' + Pp.caps + ' tests in our data' + (C ? ', ' + C.min + ' minutes in the last two years: under the ' + ((bd && bd.min_q) || 160) + ' minutes for percentiles.' : ', none in the last two years.');
    var html = '<nav class="sc-crumb"><a href="' + esc(SC.href(S, 'scout', null, 'grp=' + (Pp.grp || 'back_row'))) + '">Scouting Room</a> / ' + esc(Pp.name) + '</nav>';
    /* the black strip, as the Rink's player page: the value and the position's two key rates per 80, each with its
       percentile among the position's regulars, then the caps and the record. Career points and the span move to the
       chips; a player under the minutes for percentiles keeps the counting numbers instead. */
    var capsT = { label: Pp.wcaps && isNum(Pp.wcaps.caps) ? 'Career caps' : 'Tests', value: String(Pp.wcaps && isNum(Pp.wcaps.caps) ? Pp.wcaps.caps : Pp.caps), sub: Pp.wcaps && isNum(Pp.wcaps.caps) ? Pp.caps + ' in our data, ' + Pp.starts + ' starts' : Pp.starts + ' starts' };
    var wonT = { label: 'Won', value: Pp.wdl ? Pp.wdl[0] + ' of ' + Pp.caps : '—', sub: Pp.wdl ? Pp.wdl.join('–') + ' · ' + SC.pct(Pp.wdl[0] / Math.max(1, Pp.caps)) + ' of tests' : '' };
    var ptsT = { label: 'Points', value: String(Pp.pts), sub: Pp.tries + ' tries' }, spanT = { label: 'Span', value: SC.year(Pp.first) + '–' + SC.year(Pp.last).slice(2), sub: fmt.num(Pp.min) + ' minutes' };
    var strip;
    var peerTxt = C ? fmt.num(C.min) + ' min since ' + SC.date(C.from) + ' · v ' + gname.toLowerCase() : '';
    if (C && C.q && isNum(val)) {
      var keys = (HEAD[Pp.grp] || HEAD.back_row).filter(function (k) { return k !== 'val80' && isNum(C.v[k]) && isNum(C.pc[k]); }).slice(0, 2);
      strip = [{ label: 'Scrum value per 80', value: SC.signed(val, 1), unit: 'pts', pctl: C.pc.val80, signal: true, sub: peerTxt, tip: 'Our value model: points of margin per 80 minutes above a replacement-level player of the position; the percentile is among the position\'s regulars' }]
        .concat(keys.map(function (k) { var m = M[k] || {}; return { label: m.label || k, value: SC.vfmt(k, C.v[k]), pctl: C.pc[k], sub: 'v ' + gname.toLowerCase() + ', last two years', tip: (m.label || k) + (m.dir === 'lower' ? ': lower is better (the percentile is turned so higher is better)' : '') }; }))
        .concat([capsT, wonT]);
      meta.push(['Points', Pp.pts + ' (' + Pp.tries + ' tries)'], ['Span', SC.year(Pp.first) + '–' + SC.year(Pp.last)]);
    } else strip = (isNum(val) ? [{ label: 'Scrum value per 80', value: SC.signed(val, 1), unit: 'pts', signal: true, sub: C ? peerTxt + ': under the minutes for a percentile' : '' }] : []).concat([capsT, ptsT, wonT, spanT]).slice(0, 5);
    html += QK.playerHeader({ name: Pp.name, number: num, pos: SC.posName(Pp.pos), kicker: SC.SNAME[S] + ' · ' + gname, team: { name: t.name, abbr: t.abbr, colour: t.colour, alt: t.alt, href: SC.teamHref(S, Pp.team) },
      meta: meta, strip: strip, short: short });
    if (SC.cmpHref) {
      var simId = (Pp.similar || [])[0] ? String(Pp.similar[0].id) : null;
      html += '<div class="qk-chips sc-gap sc-jump"><a class="qk-chip" href="' + esc(SC.cmpHref(S, 'p', simId ? [String(Pp.id), simId] : [String(Pp.id)])) + '">Compare' + (simId ? ' with ' + esc(Pp.similar[0].n) : '') + ' →</a>' +
        '<a class="qk-chip" href="' + esc(SC.progHref(S, 'p', [String(Pp.id)])) + '">Career year by year →</a></div>';
    }
    if ((isNum(ph.ht_pct) || isNum(ph.wt_pct)) && Pp.phys_med) {
      html += U.note('Physical profile against ' + esc(gname.toLowerCase()) + ' capped in the last four years (' + Pp.phys_med.n + ' with a bio): ' +
        [isNum(ph.ht_pct) ? QK.ordinal(ph.ht_pct) + ' percentile for height (the middle ' + gname.toLowerCase().replace(/s$/, '') + ' is ' + Pp.phys_med.ht + ' cm)' : '', isNum(ph.wt_pct) ? QK.ordinal(ph.wt_pct) + ' for weight (' + Pp.phys_med.wt + ' kg)' : ''].filter(Boolean).join(', ') + '. Heights and weights are ESPN’s, as listed.');
    }
    // percentiles within the position (the hollow ring is the last full year with enough minutes)
    var prevS = (Pp.seasons || []).filter(function (s) { return s.q && s.pc && s.y < new Date(QK.now()).getUTCFullYear(); }).slice(-1)[0] || null;
    if (C && C.v) {
      var groups = FAMILY.map(function (f) {
        var rows = Object.keys(M).filter(function (k) { return M[k].family === f[0] && isNum(C.v[k]); }).map(function (k) {
          return { label: M[k].label, pctl: isNum(C.pc[k]) ? C.pc[k] : null, value: SC.vfmt(k, C.v[k]), tip: M[k].label + (M[k].dir === 'lower' ? ' (lower is better; the percentile is turned so higher is better)' : ''), early: !C.q,
            prev: prevS && isNum(prevS.pc[k]) ? prevS.pc[k] : undefined };
        }).filter(function (r) { return isNum(r.pctl); });
        return { label: f[1], rows: rows };
      }).filter(function (g) { return g.rows.length; });
      html += '<div class="qk-g75 sc-gap"><div>' + (groups.length ? QK.pctCard({ title: 'Per 80 minutes, against ' + gname.toLowerCase(), kicker: 'Last two years', peer: 'regular ' + gname.toLowerCase() + ' in tests', ringLabel: prevS ? String(prevS.y) : undefined,
        sample: C.n + ' tests · ' + fmt.num(C.min) + ' minutes since ' + SC.date(C.from), groups: groups }) : QK.empty('No percentiles yet', 'Percentiles need ' + ((bd && bd.min_q) || 160) + ' minutes in the last two years.')) +
        QK.explain('<b>How sure are we?</b> ' + fmt.num(C.min) + ' minutes is ' + (C.min < 400 ? 'a small sample: rates are pulled toward the position average (as if 240 more minutes at the average had been played), and a dashed box marks a percentile still settling.' : 'a solid sample for most rates; tries and turnovers still swing a lot from test to test.')) +
        '</div><div id="pl-tape"></div></div>';
    }
    // the next test and the last one (v4, as the Rink's player page: the scoreboard bug beside the last test, titled with its score)
    html += nextLast(S, Pp, TM);
    html += '<div class="qk-g2 sc-gap">' + U.card('Tests, year by year', 'Appearances in our data (older tests are missing).', U.chart('pl-caps', 260, 'Tests per year')) +
      U.card('Most similar ' + (SC.GROUP1[Pp.grp] || 'player') + 's', 'Closest on the percentile profile over the last two years.', (Pp.similar || []).length ? '<ul class="sc-list">' + Pp.similar.map(function (s) {
        return '<li>' + U.playerEnt(S, s.id, s.n, s.team, SC.tabbr(S, s.team)) + '<span class="v" title="Average gap in percentile points">' + SC.f(s.d, 0) + ' pts apart</span></li>';
      }).join('') + '</ul>' : QK.empty('Not enough minutes to compare', '')) + '</div>';
    html += '<div class="qk-g2 sc-gap">' + U.card('Test by test', 'Game value each test (our value model on the player’s own numbers, above a replacement-level player over the same minutes): blue when the side won, red when it lost.', U.chart('pl-gv', 280, 'Game value test by test')) +
      U.card('Among the position', 'Every regular ' + esc(gname.toLowerCase()) + ' on one metric (160+ minutes in the last two years), with ' + esc(QK.surname(Pp.name)) + ' marked.', '<div class="qk-seg" id="pl-pk" role="group" aria-label="Metric" style="margin-bottom:10px">' +
        (HEAD[Pp.grp] || HEAD.back_row).slice(0, 5).map(function (k, i) { return '<button type="button" data-value="' + k + '" aria-pressed="' + (i === 0) + '">' + esc(((M[k] || {}).short) || k) + '</button>'; }).join('') + '</div>' + U.chart('pl-peer', 240, 'Peer distribution')) + '</div>';
    html += '<div class="qk-g2 sc-gap">' + U.card('Value, year by year', 'Scrum value per 80 in each calendar year with 160+ minutes; 0 is a replacement-level ' + esc(SC.GROUP1[Pp.grp] || 'player') + '.', U.chart('pl-val', 260, 'Scrum value by year')) +
      ((Pp.splits || []).length ? U.card('Splits', 'Per 80 minutes over the last two years (shrunk toward the position like every rate here).', U.table([{ label: 'Split', align: 'left' }, { label: 'Tests' }, { label: 'Min' }].concat(SPLIT_COLS.map(function (c) { return { label: c[1] }; })),
        Pp.splits.map(function (x) { return [{ v: x.label, html: esc(x.label) }, { v: x.n, html: String(x.n) }, { v: x.min, html: fmt.num(x.min) }].concat(SPLIT_COLS.map(function (c) { return { v: isNum(x[c[0]]) ? x[c[0]] : -99, html: SC.vfmt(c[0], x[c[0]]) }; })); }), { cls: 'sc-table dense' }), { flush: true }) : U.card('Splits', '', QK.empty('Too few tests in two years', 'Splits need four tests with statistics.'))) + '</div>';
    // seasons
    var sc = [{ label: 'Year' }, { label: 'Side', align: 'left' }, { label: 'Tests' }, { label: 'Starts' }, { label: 'Min' }, { label: 'Pts' }, { label: 'Tries' }, { label: 'Value' }, { label: 'Metres' }, { label: 'Tackles' }, { label: 'Breaks' }];
    html += U.card('Year by year', 'Rates per 80 minutes; value is Scrum value per 80 above replacement (years with 160+ minutes get percentiles).', U.table(sc, (Pp.seasons || []).slice().reverse().map(function (s) {
      var v = s.v || {}, pc = s.pc || {};
      var cell = function (k) { return { v: isNum(v[k]) ? v[k] : -99, html: SC.vfmt(k, v[k]) + (s.q && isNum(pc[k]) ? ' <span class="qk-pctl" style="background:' + QK.pctColor(pc[k]) + ';color:' + QK.pctInk(pc[k]) + '">' + Math.round(pc[k]) + '</span>' : '') }; };
      return [{ v: s.y, html: String(s.y) }, { v: SC.tname(S, s.team), html: U.teamEnt(S, s.team, { abbr: true }) }, { v: s.n, html: String(s.n) }, { v: s.st, html: String(s.st) }, { v: s.min, html: fmt.num(s.min) },
        { v: s.pts, html: String(s.pts) }, { v: s.tries, html: String(s.tries) }, cell('val80'), cell('m'), cell('tk'), cell('cb')];
    }), { cls: 'sc-table' }), { flush: true });
    // the game log
    var lc = [{ label: 'Date', align: 'left' }, { label: 'Opponent', align: 'left' }, { label: 'Result' }, { label: '#' }, { label: 'Min' }, { label: 'Pts' }, { label: 'T' }, { label: 'M' }, { label: 'Car' }, { label: 'CB' }, { label: 'DB' }, { label: 'Tk' }, { label: 'MT' }, { label: 'Pen' }];
    html += U.card('Game log', 'The last 40 tests.', U.table(lc, (Pp.log || []).map(function (g) {
      var s = g.s || {};
      var c = function (k) { return { v: s[k] || 0, html: s[k] ? String(s[k]) : '<span class="qk-muted">0</span>' }; };
      return [{ v: g.date, html: '<a href="' + esc(SC.matchHref(S, g.id)) + '">' + esc(SC.date(g.date)) + '</a>' }, { v: SC.tname(S, g.opp), html: (g.h ? 'v ' : 'at ') + U.teamEnt(S, g.opp, { abbr: true }) },
        { v: g.res, html: '<span class="sc-res ' + g.res + '">' + g.res + '</span> ' + (isNum(g.sc[0]) ? g.sc[0] + '–' + g.sc[1] : '') }, { v: g.j || 0, html: String(g.j || '') + (g.st ? '' : ' <span class="qk-muted">bench</span>') },
        { v: g.min, html: String(g.min) }, c('pts'), c('tries'), c('m'), c('car'), c('cb'), c('db'), c('tk'), c('mt'), c('pc')];
    }), { cls: 'sc-table dense', maxHeight: 640 }), { flush: true });
    page.innerHTML = html;
    U.wire(page);
    seasonChart(QK.$('#pl-caps', page), Pp);
    if (!gameChart(QK.$('#pl-gv', page), S, Pp)) { var ge = QK.$('#pl-gv', page); if (ge) ge.innerHTML = QK.empty('No game values yet', 'They need tests with player statistics.'); }
    if (!valueChart(QK.$('#pl-val', page), Pp)) { var ve = QK.$('#pl-val', page); if (ve) ve.innerHTML = QK.empty('Fewer than two qualified years', 'A year needs 160 minutes.'); }
    var pk = (HEAD[Pp.grp] || HEAD.back_row)[0];
    peerChart(QK.$('#pl-peer', page), S, Pp, bd, pk);
    var seg = QK.$('#pl-pk', page);
    if (seg) QK.seg(seg, function (k) { peerChart(QK.$('#pl-peer', page), S, Pp, bd, k); });
    document.title = Pp.name + ' · ' + SC.SITE;
    // the tale of the tape against the closest match
    var sim = (Pp.similar || [])[0];
    var tapeEl = QK.$('#pl-tape', page);
    if (sim && tapeEl && C && C.q) {
      SC.load(S + '/players/' + sim.id + '.json').then(function (O) {
        if (!U.alive(tapeEl) || !SC.ok(O) || !O.cur) return;
        var ot = SC.team(S, O.team) || {};
        var ids = (HEAD[Pp.grp] || HEAD.back_row);
        tapeEl.innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: esc(QK.surname(Pp.name) + ' or ' + QK.surname(O.name) + '?'), html: true }) +
          QK.tape({ left: { name: Pp.name, short: QK.surname(Pp.name), sub: t.abbr, colour: t.colour, alt: t.alt, href: SC.playerHref(S, Pp.id) },
            right: { name: O.name, short: QK.surname(O.name), sub: ot.abbr, colour: ot.colour, alt: ot.alt, href: SC.playerHref(S, O.id) },
            rows: ids.filter(function (k) { return isNum(C.v[k]) && isNum(O.cur.v[k]); }).map(function (k) {
              return { label: (M[k] || {}).label || k, a: C.v[k], b: O.cur.v[k], ta: SC.vfmt(k, C.v[k]), tb: SC.vfmt(k, O.cur.v[k]), pa: C.pc[k], pb: O.cur.pc[k] };
            }) }) + (QK.verdicts ? QK.verdicts([[Pp, C, O.cur, O], [O, O.cur, C, Pp]].map(function (x) {
              var best = null, bd2 = 0;
              ids.forEach(function (k) { var a = x[1].pc[k], b = x[2].pc[k]; if (isNum(a) && isNum(b) && a - b > bd2) { bd2 = a - b; best = k; } });
              return best ? { title: 'Better on ' + (((M[best] || {}).short || best).toLowerCase()), who: QK.surname(x[0].name), text: 'better on ' + (((M[best] || {}).label || best).toLowerCase()) + ' (' + SC.vfmt(best, x[1].v[best]) + ', ' + QK.ordinal(Math.round(x[1].pc[best])) + ' percentile).' } : null;
            })) : '');
      });
    }
  }
});
})();
