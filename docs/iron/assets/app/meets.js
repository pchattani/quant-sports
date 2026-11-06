/* The Quant Iron — meets: a year's meets (#/fixtures[/<year>]) and a meet (#/event/<id>): the flights with places,
 * attempts, our pre-meet expectation and podium chance, PRs, who beat our forecast, attempts at the meet against the
 * archive, and expected against actual. Reads schedule/<year>.json, events/<id>.json and lab.json. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;

IR.page('meets', function (el, params) {
  return IR.load('schedule/years.json').then(function (yrs) {
    var years = (yrs.years || []).slice().reverse();
    var y = params.year && years.indexOf(Number(params.year)) >= 0 ? Number(params.year) : years[0];
    return IR.load('schedule/' + y + '.json').then(function (s) {
      var q = (params.query || {}).q || '';
      var big = (params.query || {}).big === '1';
      var meets = s.meets || [];
      var feds = {};
      meets.forEach(function (m) { feds[m.fed] = (feds[m.fed] || 0) + 1; });
      var fedList = Object.keys(feds).sort(function (a, b) { return feds[b] - feds[a]; });
      var fed = (params.query || {}).fed || '';
      el.innerHTML = U.head('Meets', 'Every meet in the OpenPowerlifting archive for ' + y + ': ' + fmt.num(meets.length) + ' meets. Meets with a page carry the full results, attempts and our pre-meet expectations.', 'The Quant Iron') +
        '<div class="ir-controls">' + U.seg('mt-y', years.map(function (x) { return [x, String(x)]; }), y, 'Year') +
        '<label>Federation <select class="qk-select" id="mt-fed"><option value="">Every federation</option>' + fedList.slice(0, 80).map(function (f) { return '<option value="' + esc(f) + '"' + (f === fed ? ' selected' : '') + '>' + esc(f) + ' (' + feds[f] + ')</option>'; }).join('') + '</select></label>' +
        '<label><input type="checkbox" id="mt-big"' + (big ? ' checked' : '') + '> 40+ full-power lifters</label>' +
        '<input class="qk-input ir-search" id="mt-q" type="search" placeholder="Meet name, federation or country" value="' + esc(q) + '"></div><div id="mt-list"></div>';
      function draw() {
        var qq = String(QK.$('#mt-q', el).value || '').toLowerCase(), ff = QK.$('#mt-fed', el).value, bg = QK.$('#mt-big', el).checked;
        var rows = meets.filter(function (m) { return (!ff || m.fed === ff) && (!bg || m.n_sbd >= 40) && (!qq || (m.name + ' ' + m.fed + ' ' + m.country).toLowerCase().indexOf(qq) >= 0); });
        QK.$('#mt-list', el).innerHTML = U.card('', rows.length + ' meets' + (rows.length > 600 ? ' (the first 600 shown; narrow with a filter)' : ''), U.table(
          [{ label: 'Date', align: 'left' }, { label: 'Meet', align: 'left' }, { label: 'Federation', align: 'left' }, { label: 'Country', align: 'left' }, { label: 'Entries' }, { label: 'Full power' }],
          rows.slice(0, 600).map(function (m) {
            return [{ v: m.date, html: esc(IR.date(m.date)) }, { v: m.name, html: m.page ? IR.eventLink(m.id, m.name) : esc(m.name) }, { v: m.fed, html: esc(m.fed) }, { v: m.country, html: esc(m.country) },
              { v: m.n, html: fmt.num(m.n) }, { v: m.n_sbd, html: fmt.num(m.n_sbd) }];
          }), { cls: 'dense', maxHeight: 760 }), { flush: true });
        U.wire(el);
      }
      draw();
      QK.seg(QK.$('#mt-y', el), function (v) { location.hash = '#/fixtures/' + v; });
      var t = null;
      QK.$('#mt-q', el).addEventListener('input', function () { clearTimeout(t); t = setTimeout(draw, 200); });
      QK.$('#mt-fed', el).addEventListener('change', draw);
      QK.$('#mt-big', el).addEventListener('change', draw);
    });
  });
});

function flightKey(r) { return [r.sex, r.equip, r.div, r.class].join('|'); }
function flightName(r) { return (r.sex === 'F' ? 'Women' : r.sex === 'M' ? 'Men' : r.sex) + ' · ' + r.equip + ' · ' + (r.div || 'Open') + ' · ' + (r.class ? r.class + ' kg' : 'no class'); }
function placeNum(p) { var n = parseInt(p, 10); return isNaN(n) ? 999 : n; }

IR.page('event', function (el, params) {
  return Promise.all([IR.load('events/' + encodeURIComponent(params.id) + '.json'), IR.load('lab.json').catch(function () { return {}; })]).then(function (res) {
    var m = res[0], lab = res[1] || {};
    var b = m.board || [];
    document.title = m.name + ' · ' + IR.SITE;
    var sbd = b.filter(function (r) { return r.event === 'SBD'; });
    var withPre = sbd.filter(function (r) { return isNum(r.pre) && isNum(r.dots); });
    var prs = b.filter(function (r) { return r.pr; });
    var bombs = sbd.filter(function (r) { return r.place === 'DQ'; });
    var mae = withPre.length ? withPre.reduce(function (s, r) { return s + Math.abs(r.dots - r.pre); }, 0) / withPre.length : null;
    var flights = {};
    sbd.forEach(function (r) { var k = flightKey(r); (flights[k] = flights[k] || []).push(r); });
    var fkeys = Object.keys(flights).sort(function (a, c) { return flights[c].length - flights[a].length; });
    var called = 0, nf = 0;
    fkeys.forEach(function (k) {
      var f = flights[k];
      if (f.length < 4) return;
      var fav = f.filter(function (r) { return isNum(r.p_win); }).sort(function (a, c) { return c.p_win - a.p_win; })[0];
      if (!fav) return;
      nf += 1;
      if (fav.place === '1') called += 1;
    });
    var best = sbd.filter(function (r) { return isNum(r.dots); }).sort(function (a, c) { return c.dots - a.dots; })[0];
    var html = '<nav class="ir-crumb"><a href="#/fixtures/' + IR.year(m.date) + '">Meets ' + IR.year(m.date) + '</a> / ' + esc(m.name) + '</nav>';
    html += U.head(m.name, esc([IR.date(m.date), m.fed + (m.parent ? ' (' + m.parent + ')' : ''), [m.state, m.country].filter(Boolean).join(', ')].filter(Boolean).join(' · ')), 'Meet');
    html += QK.stats([
      { label: 'Entries', value: fmt.num(m.n), sub: fmt.num(m.n_sbd) + ' full power' },
      { label: 'Best lifter on DOTS', value: best ? best.name : '–', text: true, href: best && best.pg ? IR.playerHref(best.pid) : null, sub: best ? IR.kg(best.total) + ' · ' + IR.dots(best.dots) + ' DOTS' : '' },
      { label: 'Lifetime PRs', value: String(prs.length), signal: true, sub: 'totals above the lifter’s best before this meet' },
      { label: 'Bomb-outs', value: String(bombs.length), sub: sbd.length ? IR.pctv(100 * bombs.length / sbd.length, 1) + ' of full-power entries' : '' },
      { label: 'Attempts made', value: IR.pctv(m.made, 1), sub: lab.bombouts ? 'archive: about ' + IR.pctv(((lab.attempts || {}).by_stream || {}).men_raw ? lab.attempts.by_stream.men_raw.made : null, 0) + ' (men raw)' : fmt.num(m.tried) + ' attempts reported' },
      { label: 'Our miss', value: mae !== null ? IR.dots(mae) + ' DOTS' : '–', sub: withPre.length + ' lifters we had seen before' + (nf ? ' · our favourite won ' + called + ' of ' + nf + ' flights' : '') }
    ]);
    // who beat our forecast
    var val = withPre.map(function (r) { return { r: r, v: r.dots - r.pre }; }).sort(function (a, c) { return c.v - a.v; });
    var ups = val.filter(function (x) { return x.v > 0; }), downs = val.filter(function (x) { return x.v < 0; }).reverse();
    if (val.length >= 2) {
      var item = function (x) { return '<li>' + IR.playerLink(x.r.pid, x.r.name, x.r.pg) + ' <small>' + esc(x.r.class ? x.r.class + ' kg' : '') + ' · ' + IR.kg(x.r.total) + ' against ' + IR.kg(x.r.exp) + ' expected</small><span class="v ' + IR.cls(x.v) + '">' + IR.signed(x.v) + '</span></li>'; };
      html += '<div class="qk-g2 ir-gap">' + U.card('Beat our forecast', 'Meet value: DOTS above our pre-meet expectation.', (ups.length ? '<ul class="ir-list">' + ups.slice(0, 6).map(item).join('') + '</ul>' : QK.empty('Nobody beat our forecast', ''))) +
        U.card('Below our forecast', 'Bomb-outs are not here: they have no total.', downs.length ? '<ul class="ir-list">' + downs.slice(0, 6).map(item).join('') + '</ul>' : QK.empty('Nobody fell short of our forecast', '')) + '</div>';
    }
    // flights
    html += U.card('Flights', 'Each division and class with its places. Our <b>expected</b> total and <b>podium chance</b> (flights of four or more) were made before the meet from earlier meets only (newcomers have none); the squares are the nine attempts (struck through: missed). ★ PR: a lifetime best total.',
      '<div class="ir-controls"><label>Flight <select class="qk-select" id="ev-f"><option value="">Every flight (' + fkeys.length + ')</option>' + fkeys.map(function (k, i) { return '<option value="' + i + '">' + esc(flightName(flights[k][0])) + ' (' + flights[k].length + ')</option>'; }).join('') + '</select></label></div><div id="ev-board"></div>');
    var other = b.filter(function (r) { return r.event !== 'SBD'; });
    if (other.length) html += U.card('Single lifts and push-pull', other.length + ' entries in other events (bench only, deadlift only, push-pull): not rated.', U.table(
      [{ label: 'Lifter', align: 'left' }, { label: 'Event' }, { label: 'Division', align: 'left' }, { label: 'Class' }, { label: 'BW' }, { label: 'Bench' }, { label: 'Dead' }, { label: 'Total' }, { label: 'Place' }],
      other.slice(0, 300).map(function (r) { return [{ v: r.name, html: IR.playerLink(r.pid, r.name, r.pg) }, { v: r.event, html: esc(r.event) }, { v: r.div, html: esc(r.div) }, { v: r.class, html: esc(r.class) }, { v: r.bw, html: IR.kgn(r.bw) },
        { v: r.bench || 0, html: IR.kgn(r.bench) }, { v: r.dead || 0, html: IR.kgn(r.dead) }, { v: r.total || 0, html: IR.kgn(r.total) }, { v: placeNum(r.place), html: esc(r.place) }]; }), { cls: 'dense', maxHeight: 520 }), { flush: true });
    // attempts at the meet
    var made = [0, 0, 0, 0, 0, 0, 0, 0, 0], tried = [0, 0, 0, 0, 0, 0, 0, 0, 0];
    sbd.forEach(function (r) { (r.a || []).forEach(function (v, i) { if (isNum(v) && v !== 0) { tried[i] += 1; if (v > 0) made[i] += 1; } }); });
    var anyA = tried.some(function (x) { return x > 0; });
    html += '<div class="qk-g2 ir-gap">' + U.card('Expected against actual', 'Each dot is a full-power lifter we had seen before: our pre-meet expected DOTS across, what they lifted up. On the diagonal, a perfect forecast.', U.chart('ev-sc', 340, 'Expected against actual DOTS')) +
      U.card('Attempts at this meet', anyA ? 'Share made by lift and attempt, against the archive since 2012 (lighter bars).' : 'This federation did not report attempts for this meet.', anyA ? U.chart('ev-att', 340, 'Attempts made by lift and attempt') : QK.empty('No attempts reported', 'Only best lifts are in the archive for this meet.')) + '</div>';
    el.innerHTML = html;
    function board() {
      var i = QK.$('#ev-f', el).value;
      var ks = i === '' ? fkeys : [fkeys[Number(i)]];
      QK.$('#ev-board', el).innerHTML = ks.slice(0, i === '' ? 40 : 1).map(function (k) {
        var f = flights[k].slice().sort(function (a, c) { return placeNum(a.place) - placeNum(c.place) || (c.total || 0) - (a.total || 0); });
        return '<h3 class="ir-flight">' + esc(flightName(f[0])) + ' <small>' + f.length + (f.length === 1 ? ' lifter' : ' lifters') + '</small></h3>' + U.table(
          [{ label: 'Pl' }, { label: 'Lifter', align: 'left' }, { label: 'BW' }, { label: 'Attempts (squat · bench · deadlift)', align: 'left' }, { label: 'Total' }, { label: 'DOTS' }, { label: 'Expected' }, { label: 'v expected' }, { label: 'Podium chance' }],
          f.map(function (r) {
            return [{ v: placeNum(r.place), html: esc(r.place) }, { v: r.name, html: IR.playerLink(r.pid, r.name, r.pg) + (r.pr ? ' <span class="ir-pr" title="Lifetime PR">★ PR</span>' : '') + (r.new ? ' <span class="qk-muted">first meet</span>' : '') },
              { v: r.bw || 0, html: IR.kgn(r.bw) }, { v: r.total || 0, html: IR.attempts(r.a) }, { v: r.total || 0, html: r.place === 'DQ' ? '<span class="qk-muted">bombed</span>' : '<b>' + IR.kgn(r.total) + '</b>' },
              { v: r.dots || 0, html: IR.dots(r.dots) }, { v: r.exp || 0, html: IR.kgn(r.exp) }, { v: isNum(r.dots) && isNum(r.pre) ? r.dots - r.pre : -999, html: IR.delta(r.dots, r.pre) },
              { v: r.p_pod || 0, html: isNum(r.p_pod) && (r.fsize || 0) >= 4 ? IR.pct(r.p_pod) : '<span class="qk-muted" title="Flights of three or fewer: everyone with a total makes the podium">–</span>' }];
          }), { cls: 'dense' });
      }).join('') + (i === '' && fkeys.length > 40 ? U.note('The 40 largest flights are shown; pick one above for the rest.') : '');
      U.wire(QK.$('#ev-board', el));
    }
    board();
    QK.$('#ev-f', el).addEventListener('change', board);
    if (window.QKC && withPre.length >= 3) {
      var lo = Math.min.apply(null, withPre.map(function (r) { return Math.min(r.pre, r.dots); })), hi = Math.max.apply(null, withPre.map(function (r) { return Math.max(r.pre, r.dots); }));
      QKC.scatter(QK.$('#ev-sc', el), { points: withPre.map(function (r) { return { x: r.pre, y: r.dots, name: r.name + ' · ' + IR.kg(r.total), label: QK.surname(r.name), href: r.pg ? IR.playerHref(r.pid) : null, color: r.dots >= r.pre ? QK.cssVar('--up') : QK.cssVar('--down') }; }),
        xName: 'Our expected DOTS (before the meet)', yName: 'Actual DOTS', diagonal: { label: 'Perfect forecast' }, labelTop: 6, xMin: Math.floor(lo / 10) * 10, yMin: Math.floor(lo / 10) * 10, xMax: Math.ceil(hi / 10) * 10, yMax: Math.ceil(hi / 10) * 10,
        xFmt: function (v) { return fmt.num(v, 0); }, yFmt: function (v) { return fmt.num(v, 0); }, label: 'Expected against actual DOTS' });
    } else if (QK.$('#ev-sc', el)) QK.$('#ev-sc', el).innerHTML = QK.empty('Too few lifters we had seen before', '');
    if (window.QKC && anyA) {
      var arch = [];
      var L = (lab.attempts || {}).lifts || {};
      ['squat', 'bench', 'dead'].forEach(function (k) { ((L[k] || {}).attempts || []).forEach(function (x) { arch.push(x.made); }); });
      var cats = ['Squat 1', 'Squat 2', 'Squat 3', 'Bench 1', 'Bench 2', 'Bench 3', 'Dead 1', 'Dead 2', 'Dead 3'];
      QKC.bar(QK.$('#ev-att', el), { cats: cats, series: [{ name: 'This meet', data: made.map(function (x, i) { return tried[i] ? Math.round(1000 * x / tried[i]) / 10 : null; }), color: IR.col(1) },
        { name: 'Archive since 2012', data: arch.length === 9 ? arch : cats.map(function () { return null; }), color: IR.col('ink-4') }],
        valName: 'Attempts made (%)', catName: 'Lift and attempt', fmt: function (v) { return Math.round(v) + '%'; } });
    }
  });
});
})();
