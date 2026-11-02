/* The Quant Scrum — the Scouting Room (every player on the Board by position group, the leaders, a chart) and the player
 * page (the hero, per-80 rates with percentiles within the position, Scrum value, tests and points year by year, the
 * game log, the closest match side by side). Reads <S>/players.json (the Board, column-oriented) and
 * <S>/players/<id>.json (oddsmarkets/rugby/pages.py). Metric names, units and explanations come from the rugby spec
 * (docs/_design/metrics/rugby.json through QK.spec). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;
var PCT = { tkpct: 1, kpct: 1 };
var VIEWS = [['board', 'Board'], ['leaders', 'Leaders'], ['chart', 'Chart']];
var HEAD = {
  front_row: ['val80', 'tk', 'tkpct', 'car', 'm', 'rk', 'db', 'pc'], lock: ['val80', 'tk', 'tkpct', 'car', 'm', 'rk', 'db', 'pc'],
  back_row: ['val80', 'tk', 'car', 'm', 'db', 'tkpct', 'off', 'pc'], halves: ['val80', 'pts', 'pas', 'kfh', 'kpct', 'ta', 'm', 'tk'],
  centres: ['val80', 'm', 'cb', 'db', 'car', 'off', 'ta', 'tk'], back_three: ['val80', 'm', 'cb', 'db', 'tries', 'mpc', 'kfh', 'tk']
};
SC.vfmt = function (id, v) {
  if (!isNum(v)) return '—';
  if (PCT[id]) return Math.round(v * 100) + '%';
  if (id === 'val80') return SC.signed(v, 1);
  return Math.abs(v) >= 20 ? fmt.num(v, 0) : fmt.num(v, 1);
};

function unpackBoard(d) {
  var cols = d.cols || [], rows = [];
  (d.rows || []).forEach(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; rows.push(o); });
  return rows;
}

SC.route('scout', function (page, P) {
  var S = P.S, q = P.query || {};
  var view = ['board', 'leaders', 'chart'].indexOf(q.view) >= 0 ? q.view : 'board';
  var grp = SC.GROUP[q.grp] ? q.grp : 'back_row';
  page.innerHTML = U.head('Scouting Room', 'Every player against their position: per-80 rates over the last two years, shrunk toward the position so a cameo cannot top the list, and our Scrum value.', SC.SNAME[S]) +
    '<div class="sc qk-room" id="sr-root">' + QK.skeleton('lines', 8) + '</div>';
  var root = QK.$('#sr-root', page);
  return Promise.all([SC.load(S + '/players.json'), QK.spec && QK.spec.load ? QK.spec.load('rugby') : Promise.resolve(null)]).then(function (res) {
    var d = res[0], cat = res[1];
    if (!U.alive(root)) return;
    if (!SC.ok(d)) { root.innerHTML = U.missing('The Scouting Room', d); return; }
    var M = {};
    (d.metrics || []).forEach(function (m) { M[m.id] = m; });
    var label = function (id) { var m = cat && cat.metric ? cat.metric(id, 'player') : null; return (m && m.label) || (M[id] || {}).label || id; };
    var tip = function (id) { return cat && cat.tip ? cat.tip(id, 'player', (M[id] || {}).label || id) : (M[id] || {}).label; };
    var all = unpackBoard(d);
    var qual = q.all === '1' ? false : true;
    var teamF = q.team || '';
    var rows = all.filter(function (r) { return r.grp === grp && (!qual || r.q) && (!teamF || String(r.team) === teamF); });
    var teams = {};
    all.forEach(function (r) { if (r.team) teams[r.team] = 1; });
    var tOpts = '<option value="">Every side</option>' + Object.keys(teams).sort(function (a, b) { return SC.tname(S, a).localeCompare(SC.tname(S, b)); }).map(function (t) { return '<option value="' + esc(t) + '"' + (t === teamF ? ' selected' : '') + '>' + esc(SC.tname(S, t)) + '</option>'; }).join('');
    var bar = QK.scoutBar([
      { label: 'Position', html: '<select class="qk-select" id="sr-grp">' + Object.keys(SC.GROUP).map(function (g) { return '<option value="' + g + '"' + (g === grp ? ' selected' : '') + '>' + esc(SC.GROUP[g]) + '</option>'; }).join('') + '</select>' },
      { label: 'Side', html: '<select class="qk-select" id="sr-team">' + tOpts + '</select>' },
      { label: 'Players', html: '<select class="qk-select" id="sr-q"><option value="">Regulars (' + d.min_q + '+ min)</option><option value="1"' + (qual ? '' : ' selected') + '>Everyone</option></select>' }
    ]);
    var tabs = '<nav class="qk-tabs sc-tabs" aria-label="Views">' + VIEWS.map(function (v) {
      return '<a class="qk-tab" href="' + esc(SC.href(S, 'scout', null, 'view=' + v[0] + '&grp=' + grp + (teamF ? '&team=' + teamF : '') + (qual ? '' : '&all=1'))) + '"' + (v[0] === view ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + v[1] + '</a>';
    }).join('') + '</nav>';
    var heads = HEAD[grp] || HEAD.back_row;
    // top of the position: five headline metrics, one leader each
    var hot = heads.slice(0, 5).map(function (id) {
      var m = M[id] || {}, lower = m.dir === 'lower';
      var s = rows.filter(function (r) { return isNum(r[id]) && r.q; }).sort(function (a, b) { return lower ? a[id] - b[id] : b[id] - a[id]; });
      if (!s.length) return null;
      return { sport: 'rugby', kicker: label(id), name: s[0].n, value: SC.vfmt(id, s[0][id]), title: SC.tabbr(S, s[0].team) + ' · ' + SC.posName(s[0].pos), next: s[1] ? { name: s[1].n, value: SC.vfmt(id, s[1][id]) } : null, href: SC.playerHref(S, s[0].id) };
    }).filter(Boolean);
    root.innerHTML = bar + tabs + (hot.length ? QK.band(QK.sectionHead({ kicker: 'Top of the position', title: SC.GROUP[grp], sub: rows.length + ' players · per 80 minutes, last two years' }) + QK.hotRow(hot)) : '') + '<div id="sr-view"></div>';
    var vEl = QK.$('#sr-view', root);
    function go(extra) { SC.go(SC.href(S, 'scout', null, ['view=' + view, 'grp=' + (extra.grp || grp), (extra.team !== undefined ? extra.team : teamF) ? 'team=' + (extra.team !== undefined ? extra.team : teamF) : '', (extra.all !== undefined ? extra.all : !qual) ? 'all=1' : ''].filter(Boolean).join('&'))); }
    QK.$('#sr-grp', root).addEventListener('change', function (e) { go({ grp: e.target.value }); });
    QK.$('#sr-team', root).addEventListener('change', function (e) { go({ team: e.target.value }); });
    QK.$('#sr-q', root).addEventListener('change', function (e) { go({ all: e.target.value === '1' }); });
    if (!rows.length) { vEl.innerHTML = QK.empty('No players match', 'Try every side, or everyone rather than regulars.'); return; }
    var others = d.metrics.map(function (m) { return m.id; }).filter(function (id) { return heads.indexOf(id) < 0; });
    if (view === 'board' && QK.board) {
      QK.board(vEl, { id: 'sc-bd', summary: 'val80', sets: [{ key: 'pos', label: 'Position view', groups: [{ label: SC.GROUP[grp], ids: heads }, { label: 'More', ids: others }] }],
        meta: function (id) { var m = M[id] || {}; return { label: label(id), tip: tip(id), lower: m.dir === 'lower', fmt: function (v) { return SC.vfmt(id, v); }, ours: id === 'val80' ? { name: 'Scrum value', about: 'Our player value model' } : null, short: m.short }; },
        rows: rows.map(function (r) { return { id: r.id, name: r.n, sub: SC.tabbr(S, r.team) + ' · ' + SC.posName(r.pos) + (isNum(r.age) ? ' · ' + Math.floor(r.age) : '') + ' · ' + r.gp + ' tests', mark: SC.mark(S, r.team), href: SC.playerHref(S, r.id), vals: r }; }),
        val: function (r, id) { return r.vals[id]; }, sort: { key: 'val80', dir: -1 }, noun: 'players', peerNoun: SC.GROUP[grp].toLowerCase(), csv: 'scrum-' + grp + '.csv',
        note: 'Rates per 80 minutes over the last two years, shrunk toward the position average with 240 minutes of weight. Percentile bars rank each player among the regulars of the position group.' });
    } else if (view === 'leaders') {
      vEl.innerHTML = '<div class="sc-leaders">' + heads.concat(others).map(function (id, i) {
        var m = M[id] || {}, lower = m.dir === 'lower';
        var s = rows.filter(function (r) { return isNum(r[id]); }).sort(function (a, b) { return lower ? a[id] - b[id] : b[id] - a[id]; });
        if (!s.length) return '';
        var mx = Math.max.apply(null, s.map(function (r) { return Math.abs(r[id]); }).concat([1e-9]));
        return QK.leaderCard ? QK.leaderCard({ title: label(id), tip: tip(id), ours: id === 'val80', top: s.slice(0, 5).map(function (r) {
          return { id: r.id, name: r.n, sub: SC.tabbr(S, r.team), href: SC.playerHref(S, r.id), text: SC.vfmt(id, r[id]), w: lower ? 100 * (1 - Math.abs(r[id]) / mx) + 5 : 100 * Math.abs(r[id]) / mx, mark: SC.mark(S, r.team) };
        }), count: 'of ' + s.length }) : '';
      }).join('') + '</div>';
    } else {
      var xs = q.x && M[q.x] ? q.x : heads[1], ys = q.y && M[q.y] ? q.y : heads[2];
      var opt = function (sel) { return d.metrics.map(function (m) { return '<option value="' + m.id + '"' + (m.id === sel ? ' selected' : '') + '>' + esc(label(m.id)) + '</option>'; }).join(''); };
      vEl.innerHTML = QK.scoutBar([{ label: 'Across', html: '<select class="qk-select" id="sr-x">' + opt(xs) + '</select>' }, { label: 'Up', html: '<select class="qk-select" id="sr-y">' + opt(ys) + '</select>' }]) + U.card('', '', U.chart('sr-chart', 480, 'Players chart'));
      var pts = rows.filter(function (r) { return isNum(r[xs]) && isNum(r[ys]) && r.q; }).map(function (r) {
        return { x: PCT[xs] ? r[xs] * 100 : r[xs], y: PCT[ys] ? r[ys] * 100 : r[ys], name: r.n, label: QK.surname(r.n), color: SC.traw(S, r.team), href: SC.playerHref(S, r.id) };
      });
      if (window.QKC) QKC.scatter(QK.$('#sr-chart', vEl), { points: pts, xName: label(xs) + (PCT[xs] ? ' (%)' : ''), yName: label(ys) + (PCT[ys] ? ' (%)' : ''), labelTop: 14, refX: 'mean', refY: 'mean' });
      var upd = function () { SC.go(SC.href(S, 'scout', null, 'view=chart&grp=' + grp + '&x=' + QK.$('#sr-x', vEl).value + '&y=' + QK.$('#sr-y', vEl).value)); };
      QK.$('#sr-x', vEl).addEventListener('change', upd); QK.$('#sr-y', vEl).addEventListener('change', upd);
    }
  });
});

/* ── the player page ────────────────────────────────────────────────── */
var FAMILY = [['value', 'Value'], ['scoring', 'Scoring'], ['creating', 'Creating'], ['carrying', 'Carrying'], ['defence', 'Defence'], ['set piece', 'Set piece'], ['breakdown', 'Breakdown'], ['discipline', 'Discipline'], ['kicking', 'Kicking']];
var BOARD_META = null;

function seasonChart(el, Pp) {
  if (!el || !window.QKC || !Pp.caps_by_year || Pp.caps_by_year.length < 2) return;
  var cats = Pp.caps_by_year.map(function (x) { return String(x[0]); });
  QKC.bar(el, { cats: cats, series: [{ name: 'Tests', data: Pp.caps_by_year.map(function (x) { return x[1]; }), color: 'var(--c-1)' }], valName: 'Tests played', catName: 'Year', labels: true });
}

SC.route('player', function (page, P) {
  var S = P.S, pid = P.id;
  page.innerHTML = QK.skeleton('card', 2);
  return Promise.all([SC.load(S + '/players/' + pid + '.json'), BOARD_META ? Promise.resolve(BOARD_META) : SC.load(S + '/players.json')]).then(function (res) {
    var Pp = res[0], bd = res[1];
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
    if (bio.ht_cm) meta.push(['Height', bio.ht_cm + ' cm']);
    if (bio.wt_kg) meta.push(['Weight', bio.wt_kg + ' kg']);
    meta.push(['Tests', String(Pp.caps)]);
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
    html += QK.playerHeader({ name: Pp.name, number: num, pos: SC.posName(Pp.pos), kicker: SC.SNAME[S] + ' · ' + gname, team: { name: t.name, abbr: t.abbr, colour: t.colour, alt: t.alt, href: SC.teamHref(S, Pp.team) },
      meta: meta, strip: [{ label: 'Scrum value per 80', value: isNum(val) ? SC.signed(val, 1) : '—', pctl: C && C.q ? C.pc.val80 : null, signal: true },
        { label: 'Tests', value: String(Pp.caps), sub: Pp.starts + ' starts' }, { label: 'Points', value: String(Pp.pts), sub: Pp.tries + ' tries' },
        { label: 'Won', value: Pp.wdl ? Pp.wdl[0] + ' of ' + Pp.caps : '—', sub: Pp.wdl ? Pp.wdl.join('–') : '' }, { label: 'Span', value: SC.year(Pp.first) + '–' + SC.year(Pp.last).slice(2), sub: fmt.num(Pp.min) + ' minutes' }],
      short: short });
    // percentiles within the position
    if (C && C.v) {
      var groups = FAMILY.map(function (f) {
        var rows = Object.keys(M).filter(function (k) { return M[k].family === f[0] && isNum(C.v[k]); }).map(function (k) {
          return { label: M[k].label, pctl: isNum(C.pc[k]) ? C.pc[k] : null, value: SC.vfmt(k, C.v[k]), tip: M[k].label + (M[k].dir === 'lower' ? ' (lower is better; the percentile is turned so higher is better)' : ''), early: !C.q };
        }).filter(function (r) { return isNum(r.pctl); });
        return { label: f[1], rows: rows };
      }).filter(function (g) { return g.rows.length; });
      html += '<div class="qk-g75 sc-gap"><div>' + (groups.length ? QK.pctCard({ title: 'Per 80 minutes, against ' + gname.toLowerCase(), kicker: 'Last two years', peer: 'regular ' + gname.toLowerCase() + ' in tests',
        sample: C.n + ' tests · ' + fmt.num(C.min) + ' minutes since ' + SC.date(C.from), groups: groups }) : QK.empty('No percentiles yet', 'Percentiles need ' + ((bd && bd.min_q) || 160) + ' minutes in the last two years.')) +
        QK.explain('<b>How sure are we?</b> ' + fmt.num(C.min) + ' minutes is ' + (C.min < 400 ? 'a small sample: rates are pulled toward the position average (as if 240 more minutes at the average had been played), and a dashed box marks a percentile still settling.' : 'a solid sample for most rates; tries and turnovers still swing a lot from test to test.')) +
        '</div><div id="pl-tape"></div></div>';
    }
    html += '<div class="qk-g2 sc-gap">' + U.card('Tests, year by year', 'Appearances in our data (older tests are missing).', U.chart('pl-caps', 260, 'Tests per year')) +
      U.card('Most similar ' + (SC.GROUP1[Pp.grp] || 'player') + 's', 'Closest on the percentile profile over the last two years.', (Pp.similar || []).length ? '<ul class="sc-list">' + Pp.similar.map(function (s) {
        return '<li>' + U.playerEnt(S, s.id, s.n, s.team, SC.tabbr(S, s.team)) + '<span class="v" title="Average gap in percentile points">' + SC.f(s.d, 0) + ' pts apart</span></li>';
      }).join('') + '</ul>' : QK.empty('Not enough minutes to compare', '')) + '</div>';
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
            }) });
      });
    }
  });
});
})();
