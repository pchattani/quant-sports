/* The Quant Iron — the overview: the greeting with the featured meet, My Teams (lifters), the last fortnight's digest,
 * the latest meets with the chances we gave before the lifting, the power board per stream, stories, who's hot by
 * class and "who's for real". Reads index.json (oddsmarkets/powerlifting/pages.py _index). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;

function featured(f) {
  if (!f) return '';
  var b = f.best || {};
  return QK.spotlight({
    kicker: 'The latest big meet · ' + f.fed, name: f.name, href: IR.eventHref(f.id), sub: IR.date(f.date) + ' · ' + f.country + ' · ' + f.n + ' full-power lifters',
    headline: b.name ? 'Best lifter on DOTS: ' + b.name + ', ' + IR.kg(b.total) + ' (' + IR.dots(b.dots) + ' DOTS).' : '',
    stats: [{ label: 'Full-power lifters', value: String(f.n) }, { label: 'Lifetime PRs', value: String(f.prs || 0) }, { label: 'Attempts made', value: IR.pctv(f.made) },
      { label: 'Our favourite', value: f.fav && f.fav.name ? QK.surname(f.fav.name) : '–', tip: f.fav ? 'The lifter we gave the best chance of winning a flight: ' + IR.pct(f.fav.p_win) + ' before the meet.' : '' }],
    links: [{ text: 'The full results', href: IR.eventHref(f.id) }]
  });
}

function digestTiles(d) {
  if (!d || !d.meets) return QK.empty('No results in the last fortnight', 'OpenPowerlifting adds meets weekly; new results appear here after the next update.');
  var t = [
    { label: 'Meets', value: fmt.num(d.meets), sub: IR.date(d.from) + ' to ' + IR.date(d.to) },
    { label: 'Full-power lifters', value: fmt.num(d.lifters), sub: fmt.num(d.entries) + ' entries' },
    { label: 'Lifetime PRs', value: fmt.num(d.prs), sub: 'totals above the lifter’s best before', signal: true },
    { label: 'Bomb-outs', value: fmt.num(d.bombs), sub: isNum(d.entries) && d.entries ? IR.pctv(100 * d.bombs / d.entries, 1) + ' of entries finished without a total' : '' },
    { label: 'Our miss', value: IR.dots(d.mae) + ' DOTS', sub: 'average gap between our expectation and the result, ' + fmt.num(d.n_fc) + ' lifters we had seen before' }
  ];
  if (d.over) t.push({ label: 'Beat us by most', value: d.over.name, text: true, href: IR.playerHref(d.over.pid), sub: IR.signed(d.over.v) + ' DOTS above our expectation at ' + d.over.mn });
  if (d.top) t.push({ label: 'Best DOTS', value: d.top.name, text: true, href: IR.playerHref(d.top.pid), sub: IR.dots(d.top.dots) + ' DOTS, ' + IR.kg(d.top.total) + ' (' + IR.STREAMS[d.top.stream] + ')' });
  return QK.stats(t);
}

function latestGrid(list) {
  if (!list || !list.length) return QK.empty('No meets yet', '');
  return '<div class="ir-meets">' + list.map(function (m) {
    var b = m.best || {}, f = m.fav || {};
    var won = f.place === '1';
    return '<a class="qk-card is-link ir-meetcard" href="' + IR.eventHref(m.id) + '"><div class="qk-card-body">' +
      '<div class="ir-mc-k">' + esc(m.fed) + ' · ' + esc(IR.date(m.date)) + ' · ' + esc(m.country) + '</div>' +
      '<div class="ir-mc-n">' + esc(m.name) + '</div>' +
      '<div class="ir-mc-row"><span>Best on DOTS</span><b>' + esc(b.name || '–') + '</b><em>' + IR.dots(b.dots) + '</em></div>' +
      (f.name ? '<div class="ir-mc-row"><span>Our favourite</span><b>' + esc(f.name) + '</b><em>' + IR.pct(f.p_win) + ' to win the flight · ' + (won ? 'won' : f.place === 'DQ' ? 'bombed out' : 'placed ' + esc(f.place || '–')) + '</em></div>' : '') +
      '<div class="ir-mc-foot">' + m.n + ' full-power lifters · ' + (m.prs || 0) + ' PRs · ' + IR.pctv(m.made) + ' of attempts made</div></div></a>';
  }).join('') + '</div>';
}

function powerBoard(key, rows) {
  if (!QK.powerBars || !rows || !rows.length) return '';
  var parts = [{ key: 's', label: 'Squat', color: IR.col(1) }, { key: 'b', label: 'Bench', color: IR.col(3) }, { key: 'd', label: 'Deadlift', color: IR.col(5) }];
  var mx = Math.max.apply(null, rows.map(function (r) { return r.rt || 0; })) * 1.02;
  return QK.powerBars(null, { groups: [{ label: '', rows: rows.map(function (r) {
    return { rank: r.rank, name: r.name, abbr: r.cc ? String(r.cc).slice(0, 3).toUpperCase() : '', href: IR.playerHref(r.pid), value: r.rt, text: IR.dots(r.rt),
      parts: r.parts || {}, form: r.form, follow: IR.followItem(r.pid, r.name, r.cc),
      cells: [{ label: 'Class', text: r.cls ? r.cls + ' kg' : '–' }, { label: 'Best DOTS (12 months)', text: IR.dots(r.best12) }, { label: '90 days', text: isNum(r.mv) ? (r.mv > 0 ? '▲' + r.mv : r.mv < 0 ? '▼' + Math.abs(r.mv) : '–') : 'new' }],
      sub: isNum(r.d90) && Math.abs(r.d90) >= 0.5 ? IR.signed(r.d90) + ' DOTS in 90 days' : '' };
  }) }], parts: parts, max: mx, valueLabel: 'Our rating', unit: 'DOTS expected at the next meet', formN: 5, formLabel: 'Last 5 v our forecast' });
}

function stories(list) {
  var items = (list || []).map(function (s) {
    if (s.kind === 'riser' || s.kind === 'faller') {
      return { sport: 'powerlifting', kicker: (s.kind === 'riser' ? 'Biggest riser · ' : 'Biggest faller · ') + IR.STREAMS[s.stream], name: s.name, sub: (s.cls ? s.cls + ' kg · ' : '') + 'No. ' + s.rank,
        value: IR.signed(s.d365), unit: 'DOTS in a year', href: IR.playerHref(s.pid),
        text: s.name + (s.kind === 'riser' ? ' is ' + Math.abs(s.d365).toFixed(1) + ' DOTS better than a year ago in our numbers, now ' : ' has dropped ' + Math.abs(s.d365).toFixed(1) + ' DOTS in a year, now ') + IR.dots(s.rt) + '.' };
    }
    if (s.kind === 'record') {
      var lift = { squat: 'squat', bench: 'bench', dead: 'deadlift', total: 'total' }[s.lift] || s.lift;
      return { sport: 'powerlifting', kicker: 'All-time record · ' + s.label, name: s.name, sub: s.cls + ' kg · ' + lift + ' · ' + IR.date(s.date), value: IR.kgn(s.kg), unit: 'kg',
        href: IR.playerHref(s.pid), text: 'The heaviest ' + lift + ' in the archive in the ' + s.cls + ' kg class' + (isNum(s.prev) ? ', up from ' + IR.kg(s.prev) : '') + '. Classes by bodyweight on the day, all federations.' };
    }
    return null;
  }).filter(Boolean);
  return items.length ? QK.storyCards(items, { cols: 3 }) : '';
}

function hot(key, list) {
  if (!list || !list.length) return '';
  return QK.hotRow(list.map(function (x) {
    return { sport: 'powerlifting', kicker: x.cls + ' kg', name: x.name, value: IR.dots(x.rt), title: 'DOTS expected', next: x.next ? { name: x.next.name, value: IR.dots(x.next.rt) } : null, href: IR.playerHref(x.pid) };
  }), { rank: false });
}

function quadrant(el, pts) {
  if (!el || !window.QKC || !pts || pts.length < 5) { if (el) el.innerHTML = QK.empty('Too few lifters', ''); return; }
  QKC.scatter(el, { points: pts.map(function (p) { return { x: p.rt, y: p.beat, name: p.name + ' · ' + p.n + ' meets', label: QK.surname(p.name), href: IR.playerHref(p.pid) }; }),
    xName: 'Our rating (DOTS)', yName: 'Meets above our expectation (%)', labelTop: 8, refY: 50,
    xFmt: function (v) { return fmt.num(v, 0); }, yFmt: function (v) { return Math.round(v) + '%'; }, quadrants: ['Beating our numbers', '', '', 'Below our numbers'], label: 'Rating against meets above expectation' });
}

/* "Your lifters in our rankings": each followed lifter with the two either side */
function followBoard(rk) {
  return function (cards) {
    var mine = {};
    (cards || []).forEach(function (c) { if (c && c.k) mine[c.k.split(':')[2]] = 1; });
    var groups = [];
    IR.STREAM_KEYS.forEach(function (k) {
      var rows = ((rk.streams || {})[k] || {}).rows || [];
      rows.forEach(function (r, i) {
        if (!mine[r.pid]) return;
        var lo = Math.max(0, i - 2), hi = Math.min(rows.length, i + 3);
        groups.push({ label: IR.STREAMS[k] + ' · ' + r.name, rows: rows.slice(lo, hi).map(function (x) {
          return { rank: x.rank, name: x.name, abbr: x.cc ? String(x.cc).slice(0, 3).toUpperCase() : '', href: x.pg ? IR.playerHref(x.pid) : null, value: x.rt, text: IR.dots(x.rt),
            follow: IR.followItem(x.pid, x.name, x.cc), sub: (x.cls ? x.cls + ' kg' : '') + (mine[x.pid] ? ' · you follow' : '') };
        }) });
      });
    });
    if (!groups.length) return '';
    return '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(null, { groups: groups.slice(0, 6), valueLabel: 'Our rating', unit: 'DOTS expected', key: false }) +
      '<p class="qk-caption">Each lifter you follow in our rankings, with the lifters either side. <a class="qk-link" href="#/standings">Every ranking →</a></p></div></div>';
  };
}

IR.page('overview', function (el) {
  return Promise.all([IR.load('index.json'), IR.load('rankings.json')]).then(function (res) {
    var d = res[0], rk = res[1];
    var c = d.counts || {};
    var html = QK.greeting({ date: 'Data to ' + IR.date(d.data_to) + ' · OpenPowerlifting archive',
      title: 'Powerlifting, ' + QK.mark('by the numbers') + '.',
      lede: fmt.num(c.scored || 0) + ' full-power performances since 1964: our rating of every active lifter in DOTS, the total we expect at the next meet, podium chances for every flight, attempt-by-attempt analytics and every lifter measured against their weight class.',
      ctas: [{ label: 'Rankings', href: '#/standings' }, { label: 'Scouting Room', href: '#/scout', ghost: true }, { label: 'The Lab', href: '#/lab', ghost: true }],
      side: featured(d.featured) });
    html += '<section class="qk-section ir-follow" id="ir-follow"></section>';
    html += U.sec('The last fortnight', 'The fortnight in the archive', 'Results added to OpenPowerlifting in the last 14 days of data: PRs, bomb-outs, how close our expectations came and who beat them by most.', digestTiles(d.digest));
    html += U.sec('Latest meets', 'Our call, then the lifting', 'OpenPowerlifting publishes results, not entry lists, so there are no upcoming meets to forecast. Instead: the latest meets with the chances we gave before the first attempt, built only from meets before them.', latestGrid(d.latest),
      '<a class="qk-more" href="#/fixtures">Every meet</a>');
    var pw = d.power || {};
    html += U.sec('Power board', 'Who is strongest right now?', 'Our rating is the DOTS we expect at the lifter’s next meet. The bar splits it by where the total comes from (squat, bench, deadlift at the best meet of the year); the squares are the last five meets against our expectation (filled: beat it). Movement is against our ranking 90 days ago.',
      '<div class="ir-pw-tabs">' + U.seg('pw-s', IR.STREAM_KEYS.filter(function (k) { return (pw[k] || []).length; }).map(function (k) { return [k, IR.STREAMS[k]]; }), 'men_raw', 'Stream') + '</div><div id="pw-board">' + powerBoard('men_raw', pw.men_raw) + '</div>',
      '<a class="qk-more" href="#/standings">Full rankings</a>');
    html += '<div id="ov-hot"></div>';
    html += U.sec('Stories', 'What the numbers say', 'Risers and fallers in our ratings over a year, and all-time records set in the last six months.', stories(d.stories) +
      '<div class="qk-g75 ir-gap"><div>' + U.card('Who’s for real?', 'Our rating across; up, the share of meets in the last two years above our pre-meet expectation (shrunk toward half). Top: lifting above what their record says. The top 80 men raw.', '<div class="ir-pw-tabs">' + U.seg('rq-s', [['men_raw', 'Men raw'], ['women_raw', 'Women raw']], 'men_raw', 'Stream') + '</div>' + U.chart('ov-quad', 380, 'Rating against meets above expectation')) +
      '</div><div>' + QK.newHere({ items: ['<b>DOTS</b> puts every bodyweight on one scale: a total of 600 kg at 83 kg is about 403 DOTS; 500 is world class for men, 450 for women.',
        'Our <b>rating</b> is the DOTS we expect at the next meet: the last meet, adjusted for stage of career, age and time away. On 2023 to 2025, sealed, it missed by ' + IR.dots(d.model && d.model.rmse) + ' DOTS a meet (the last meet alone: ' + IR.dots(d.model && d.model.rmse_last) + ').',
        'A <b>percentile</b> ranks a lifter against active lifters of the same sex, equipment and weight class. <a class="qk-link" href="#/model">How it all works</a>.'] }) + '</div></div>');
    html += U.note(fmt.num(c.meets || 0) + ' meets and ' + fmt.num(c.lifters || 0) + ' lifters in the archive. How our forecasts have done lives on the <a href="#/model?tab=doing">Model page</a>.');
    el.innerHTML = html;
    var fl = QK.$('#ir-follow', el);
    if (fl && QK.followSection) QK.followSection(fl, { site: 'iron', scope: 'lifter', full: true, feed: false, title: 'Your lifters', noun: 'lifter', kicker: 'My lifters',
      sub: 'The lifters you follow, first: their rating, their rank, their last meet against our expectation.',
      picker: { sport: 'powerlifting', load: IR.followRows }, board: followBoard(rk) });
    var segp = QK.$('#pw-s', el);
    if (segp) QK.seg(segp, function (k) { QK.$('#pw-board', el).innerHTML = powerBoard(k, pw[k]); });
    var hh = QK.$('#ov-hot', el), H = d.hot || {};
    if (hh && (H.men_raw || []).length) {
      hh.innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The best of every weight class', sub: 'The top of our rating in each IPF class (bodyweight on the day), raw. The next best beside.', actions: '<a class="qk-more" href="#/scout?view=leaders">Leaders on every metric</a>' }) +
        '<div class="ir-pw-tabs">' + U.seg('hot-s', [['men_raw', 'Men raw'], ['women_raw', 'Women raw']], 'men_raw', 'Stream') + '</div><div id="hot-row">' + hot('men_raw', H.men_raw) + '</div>');
      QK.seg(QK.$('#hot-s', el), function (k) { QK.$('#hot-row', el).innerHTML = hot(k, H[k]); });
    }
    var real = d.real || {};
    quadrant(QK.$('#ov-quad', el), real.men_raw);
    var rq = QK.$('#rq-s', el);
    if (rq) QK.seg(rq, function (k) { quadrant(QK.$('#ov-quad', el), real[k]); });
  });
});
})();
