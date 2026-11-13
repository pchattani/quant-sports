/* The Quant Scrum — Standings: the Nations Championship (both conferences, the finals weekend), the Six Nations (the
 * last table with bonus points; the next edition's title, Grand Slam, Triple Crown and wooden spoon chances), The
 * Rugby Championship, and the 2027 Rugby World Cup (pools, the round of 16 with the best thirds, title chances).
 * Views: Table | Chances | Bracket | History. Reads <S>/comps/<key>.json (oddsmarkets/rugby/build.py comp_payloads). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;
var ORDER = ['nc', 'six', 'trc', 'rwc', 'w6n', 'wxv', 'wrwc'];

function teamCell(S, name) {
  var id = SC.byName(S, name);
  return id ? { v: name, html: U.teamEnt(S, id) + SC.followStar(S, id) } : { v: name, html: esc(name) };
}

/* each side's results in this competition, oldest first (W/D/L), from the payload's results: the table's form column */
function formMap(results) {
  var m = {};
  (results || []).filter(function (r) { return r && isNum(r.hs) && isNum(r.as); }).slice().sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); }).forEach(function (r) {
    (m[r.home] = m[r.home] || []).push(r.hs > r.as ? 'W' : r.hs < r.as ? 'L' : 'D');
    (m[r.away] = m[r.away] || []).push(r.as > r.hs ? 'W' : r.as < r.hs ? 'L' : 'D');
  });
  return m;
}
function tableHTML(S, rows, o) {
  o = o || {};
  var form = o.form || {};
  var hasForm = (rows || []).some(function (r) { return (form[r.team] || []).length; });
  var cols = [{ label: '#' }, { label: 'Team', align: 'left', sticky: true }, { label: 'P' }, { label: 'W' }, { label: 'D' }, { label: 'L' },
    { label: 'PF' }, { label: 'PA' }, { label: 'PD' }, { label: 'TF' }, { label: 'TA' }, { label: 'TB' }, { label: 'LB' }].concat(o.gs ? [{ label: 'GS' }] : []).concat([{ label: 'Pts' }])
    .concat(hasForm ? [{ label: 'Form', align: 'left', sortable: false, title: 'The last five results in this competition, oldest first' }] : []);
  var trs = (rows || []).map(function (r) {
    var c = [{ v: r.pos, html: String(r.pos) }, teamCell(S, r.team), { v: r.p, html: String(r.p) }, { v: r.w, html: String(r.w) }, { v: r.d, html: String(r.d) },
      { v: r.l, html: String(r.l) }, { v: r.pf, html: String(r.pf) }, { v: r.pa, html: String(r.pa) }, { v: r.pd, html: '<span class="' + SC.cls(r.pd) + '">' + SC.signed(r.pd, 0) + '</span>' },
      { v: r.tf, html: String(r.tf) }, { v: r.ta, html: String(r.ta) }, { v: r.tb, html: String(r.tb) }, { v: r.lb, html: String(r.lb) }];
    if (o.gs) c.push({ v: r.gs, html: String(r.gs || 0) });
    c.push({ v: r.pts, html: '<b>' + r.pts + '</b>' });
    if (hasForm) { var f = (form[r.team] || []).slice(-5); c.push({ v: f.join(''), html: f.length ? QK.formDots(f, 5) : '<span class="qk-muted">—</span>' }); }
    return c;
  });
  return U.table(cols, trs, { cls: 'sc-table' });
}

function chancesTable(S, sim, cols) {
  var head = [{ label: 'Team', align: 'left', sticky: true }].concat(cols.map(function (c) { return { label: c[1] }; }));
  var trs = (sim.teams || []).map(function (r) {
    return [teamCell(S, r.team)].concat(cols.map(function (c) { var v = typeof c[0] === 'function' ? c[0](r) : r[c[0]]; return isNum(v) ? U.heat(v, v < 0.1 ? 1 : 0) : { v: -1, html: '—' }; }));
  });
  return U.table(head, trs, { cls: 'sc-chances' });
}

function posHeat(S, sim, n, key) {
  var head = [{ label: 'Team', align: 'left', sticky: true }];
  for (var i = 1; i <= n; i++) head.push({ label: QK.ordinal(i) });
  head.push({ label: 'Avg pts' });
  var trs = (sim.teams || []).map(function (r) {
    var arr = r[key || 'pos'] || [];
    return [teamCell(S, r.team)].concat(arr.map(function (p) { return U.heat(p, 0); })).concat([{ v: r.xpts || 0, html: isNum(r.xpts) ? SC.f(r.xpts, 1) : '—' }]);
  });
  return U.table(head, trs, { cls: 'sc-chances' });
}

function fixtures(S, list) {
  if (!list || !list.length) return '';
  var cols = [{ label: 'Date', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Away', align: 'left' }, { label: 'Home win' }, { label: 'Draw' }, { label: 'Away win' }, { label: 'Margin', align: 'left' }];
  return U.table(cols, list.map(function (f) {
    var p = f.p || [];
    var hid = SC.byName(S, f.home), aid = SC.byName(S, f.away);
    return [{ v: f.date, html: esc(SC.date(f.date)) }, teamCell(S, f.home), teamCell(S, f.away), U.heat(p[0], 0), U.heat(p[1], 0), U.heat(p[2], 0),
      { v: p[3], html: isNum(p[3]) ? esc((p[3] >= 0 ? SC.tabbr(S, hid) : SC.tabbr(S, aid)) + ' by ' + Math.max(1, Math.round(Math.abs(p[3])))) : '—' }];
  }), { cls: 'sc-fx' });
}

function chanceBars(S, rows, key, lab) {
  return QK.chances((rows || []).map(function (r) {
    var id = SC.byName(S, r.team);
    return { label: r.team, p: r[key], href: id ? SC.teamHref(S, id) : null, color: id ? SC.traw(S, id) : null, mark: id ? SC.mark(S, id) : null };
  }).filter(function (r) { return r.p > 0.0005; }), { key: false, limit: 10, oursName: lab });
}

function history(S, rows, kind) {
  if (!rows || !rows.length) return QK.empty('No past editions in our data', '');
  var cols = [{ label: 'Year' }, { label: 'Winner', align: 'left' }].concat(kind === 'rwc' ? [{ label: 'Runner-up', align: 'left' }, { label: 'Final' }] : [{ label: 'Won' }, { label: 'Pts' }, { label: '', align: 'left' }]);
  return U.table(cols, rows.slice().reverse().map(function (r) {
    var base = [{ v: r.season, html: String(r.season) }, teamCell(S, r.team)];
    if (kind === 'rwc') return base.concat([teamCell(S, r.runner_up), { v: r.score[0], html: '<a href="' + esc(SC.matchHref(S, r.id)) + '">' + r.score[0] + '–' + r.score[1] + '</a>' }]);
    return base.concat([{ v: r.w, html: r.w + ' of ' + r.p }, { v: r.pts, html: String(r.pts) }, { v: r.slam ? 1 : 0, html: r.slam ? '<span class="qk-bchip volt">Grand Slam</span>' : '' }]);
  }), { cls: 'sc-table', maxHeight: 640 }) + U.note('Champions as our table computes them from the results in our data (bonus points from ' + (kind === 'six' ? '2017, when the Six Nations adopted them' : 'the start') + '); an edition with missing matches is left out.');
}

/* one pairing: the label and date across the top, then side A | v | side B (each a name with a line under it) */
function pair(k, when, a, asub, b, bsub) {
  return '<li><div class="hd"><span class="k">' + esc(k) + '</span>' + (when ? '<span class="d">' + esc(when) + '</span>' : '') + '</div>' +
    '<div class="row"><div class="s"><b>' + esc(a) + '</b>' + (asub ? '<small>' + esc(asub) + '</small>' : '') + '</div><span class="v">v</span>' +
    '<div class="s r"><b>' + esc(b) + '</b>' + (bsub ? '<small>' + esc(bsub) + '</small>' : '') + '</div></div></li>';
}

function rwcBracket(S, d) {
  var sim = d.sim || {}, by = {};
  (sim.teams || []).forEach(function (r) { by[r.team] = r; });
  var seat = function (code) {
    var pool = code.charAt(1), place = code.charAt(0);
    var ts = (d.pools || {})[pool] || [];
    var best = ts.slice().sort(function (a, b) { return ((by[b] || {}).win_pool || 0) - ((by[a] || {}).win_pool || 0); });
    return { lab: (place === '1' ? 'Winner' : 'Runner-up') + ' Pool ' + pool, fav: place === '1' ? best[0] : best[1] };
  };
  var thirdLab = { A: 'C/E/F', B: 'D/E/F', C: 'A/E/F', D: 'B/E/F' };
  var r16 = Object.keys(d.r16 || {}).sort(function (a, b) { return a - b; }).map(function (k) {
    var pr = d.r16[k], a = seat(pr[0]), b = pr[1].indexOf('3:') === 0 ? { lab: 'Third, Pool ' + thirdLab[pr[1].charAt(2)], fav: null } : seat(pr[1]);
    return pair('R16 ' + k, '', a.lab, a.fav ? 'Most likely ' + a.fav : '', b.lab, b.fav ? 'Most likely ' + b.fav : '');
  }).join('');
  var qf = Object.keys(d.qf || {}).sort().map(function (k) { return pair('QF ' + k, '', 'Winner R16 ' + d.qf[k][0], '', 'Winner R16 ' + d.qf[k][1], ''); }).join('');
  var sf = Object.keys(d.sf || {}).sort().map(function (k) { return pair('SF ' + k, '', 'Winner QF ' + d.sf[k][0], '', 'Winner QF ' + d.sf[k][1], ''); }).join('');
  return '<div class="sc-bracket"><div><h3>Round of 16</h3><ol>' + r16 + '</ol></div><div><h3>Quarter-finals</h3><ol>' + qf + '</ol><h3>Semi-finals</h3><ol>' + sf +
    '</ol><h3>Final</h3><ol>' + pair('Final', '13 November 2027, Sydney', 'Winner SF 1', '', 'Winner SF 2', '') + '</ol></div></div>' +
    U.note('The pairings follow the official format: the top two in each pool and the four best third-placed teams (table points, then points difference, try difference, points, tries). Which pools the thirds come from decides their opponents, from World Rugby’s permutation table.');
}

var VIEW_LABEL = { table: 'Table', chances: 'Chances', bracket: 'Bracket', history: 'History', fixtures: 'Fixtures' };
var VIEWS = { nc: ['table', 'chances', 'bracket', 'fixtures'], six: ['chances', 'table', 'history'], trc: ['table', 'history'], rwc: ['chances', 'bracket', 'history'],
  w6n: ['table', 'history'], wxv: ['table'], wrwc: ['history'] };

SC.route('standings', function (page, P) {
  var S = P.S;
  var have = (SC.info(S).comps || []).filter(function (k) { return ORDER.indexOf(k) >= 0; }).sort(function (a, b) { return ORDER.indexOf(a) - ORDER.indexOf(b); });
  if (!have.length) { page.innerHTML = U.head('Standings', '', SC.SNAME[S]) + QK.empty('No competitions simulated for ' + SC.SNAME[S].toLowerCase() + ' yet', 'The tables appear here once the competitions are in our data.'); return; }
  var tab = U.tab(P, have, have[0]);
  var views = VIEWS[tab] || ['table'];
  var view = views.indexOf((P.query || {}).view) >= 0 ? P.query.view : views[0];
  page.innerHTML = U.head('Standings', 'Tables with bonus points, and our chances from 20,000 simulated tournaments, every remaining match played out with our model.', SC.SNAME[S]) +
    U.tabs(have.map(function (k) { return { key: k, label: SC.compName(k), href: SC.href(S, 'standings', null, 'tab=' + k) }; }), tab) +
    '<div class="qk-seg sc-views" role="group" aria-label="View">' + views.map(function (v) { return '<a class="sc-view" href="' + esc(SC.href(S, 'standings', null, 'tab=' + tab + '&view=' + v)) + '" aria-pressed="' + (v === view) + '">' + VIEW_LABEL[v] + '</a>'; }).join('') + '</div>' +
    '<div id="st-body">' + QK.skeleton('lines', 6) + '</div>';
  var body = QK.$('#st-body', page);
  return SC.load(S + '/comps/' + tab + '.json').then(function (d) {
    if (!U.alive(body)) return;
    if (!SC.ok(d)) { body.innerHTML = U.missing('This competition', d); return; }
    var html = '';
    if (tab === 'nc') {
      var sim = d.sim || { teams: [] };
      if (view === 'table') {
        html += '<div class="qk-g2">' + U.card('Northern conference', 'The Six Nations sides. Each plays the six southern sides once.', tableHTML(S, d.north, { form: formMap(d.results) }), { flush: true }) +
          U.card('Southern conference', 'The Rugby Championship sides with Fiji and Japan.', tableHTML(S, d.south, { form: formMap(d.results) }), { flush: true }) + '</div>' +
          U.note('Standard World Rugby points: 4 a win, 2 a draw, a try bonus for 4+ tries, a losing bonus for losing by 7 or fewer. Level on points: points difference, then tries scored.');
      } else if (view === 'chances') {
        html += '<div class="qk-g2">' + U.card('Who wins it?', 'Our chance to win the final at Twickenham on 29 November.', chanceBars(S, sim.teams, 'champion', 'Our title chance')) +
          U.card('Top of the conference', 'Our chance to finish first in each conference, which means a place in the final.', chanceBars(S, sim.teams, 'top_conf', 'Our chance')) + '</div>' +
          U.card('Every placing', 'Our chance of each final placing, 1st to 12th, after the finals weekend (each place meets its equal in the other conference).', posHeat(S, sim, 12, 'place'), { flush: true });
      } else if (view === 'bracket') {
        html += U.card('The finals weekend', 'Twickenham, 27-29 November: each place in one conference meets the same place in the other.', '<ol class="sc-finals">' + (d.finals || []).map(function (f, i) {
          var nRow = (sim.teams || []).filter(function (r) { return r.conf === 'North'; }).sort(function (a, b) { return (b.conf_pos[i] || 0) - (a.conf_pos[i] || 0); })[0];
          var sRow = (sim.teams || []).filter(function (r) { return r.conf === 'South'; }).sort(function (a, b) { return (b.conf_pos[i] || 0) - (a.conf_pos[i] || 0); })[0];
          return pair(f.label, SC.date(f.date, true), nRow ? nRow.team : 'North ' + (i + 1), nRow ? SC.pct(nRow.conf_pos[i]) + ' to finish ' + QK.ordinal(i + 1) + ' in the north' : '',
            sRow ? sRow.team : 'South ' + (i + 1), sRow ? SC.pct(sRow.conf_pos[i]) + ' to finish ' + QK.ordinal(i + 1) + ' in the south' : '');
        }).join('') + '</ol>' + U.note('The most likely side in each conference place from our simulations; the pairings are set once the six rounds are done.'));
      } else {
        html += U.card('Matches to play', 'Our chances for each remaining conference match.', fixtures(S, d.fixtures) || QK.empty('Every conference match is played', ''), { flush: true }) +
          (d.results && d.results.length ? U.card('Results', 'With our pre-match chance for the home side.', U.table([{ label: 'Date', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Score' }, { label: 'Away', align: 'left' }, { label: 'Our home chance' }],
            d.results.map(function (r) { return [{ v: r.date, html: esc(SC.date(r.date)) }, teamCell(S, r.home), { v: r.hs - r.as, html: '<a href="' + esc(SC.matchHref(S, r.id)) + '">' + r.hs + '–' + r.as + '</a>' }, teamCell(S, r.away), { v: r.p, html: SC.pct(r.p) }]; }), { cls: 'sc-table' }), { flush: true }) : '');
      }
    } else if (tab === 'six') {
      var nx = d.next || {};
      if (view === 'chances' && nx.sim) {
        html += '<div class="qk-g2">' + U.card('Who wins the ' + nx.season + ' Six Nations?', 'Our title chance from ' + fmt.num(nx.sim.n) + ' simulated championships (5 February to 13 March ' + nx.season + ').', chanceBars(S, nx.sim.teams, 'title', 'Our title chance')) +
          U.card('Grand Slam, Triple Crown, wooden spoon', 'A Grand Slam is five wins; the Triple Crown a Home Nation beating the other three; the spoon is last place.',
            chancesTable(S, nx.sim, [['title', 'Title'], ['slam', 'Grand Slam'], ['triple_crown', 'Triple Crown'], ['last', 'Spoon'], [function (r) { return r.xpts / 30; }, 'Avg pts']].slice(0, 4)), { flush: true }) + '</div>' +
          U.card('Every finishing place', 'Our chance of each place, with the average table points (bonus points and the 3-point Grand Slam bonus included).', posHeat(S, nx.sim, 6), { flush: true }) +
          U.card('The fixtures', 'Our chances for each match of the ' + nx.season + ' championship, with today’s ratings.', fixtures(S, nx.fixtures), { flush: true });
      } else if (view === 'history') {
        html += U.card('Champions', 'Each Six Nations in our data (Five Nations before 2000).', history(S, d.winners, 'six'), { flush: true });
      } else {
        html += U.card(d.season + ' Six Nations: final table', 'Bonus points as the championship awards them (since 2017), including 3 for a Grand Slam.', tableHTML(S, d.table, { gs: true, form: formMap(d.results) }), { flush: true }) +
          U.card('Results', '', U.table([{ label: 'Date', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Score' }, { label: 'Away', align: 'left' }, { label: 'Tries' }, { label: 'Our home chance' }],
            (d.results || []).map(function (r) { return [{ v: r.date, html: esc(SC.date(r.date)) }, teamCell(S, r.home), { v: r.hs - r.as, html: '<a href="' + esc(SC.matchHref(S, r.id)) + '">' + r.hs + '–' + r.as + '</a>' }, teamCell(S, r.away), { v: r.ht, html: isNum(r.ht) ? r.ht + '–' + r.at : '—' }, { v: r.p, html: SC.pct(r.p) }]; }), { cls: 'sc-table' }), { flush: true });
      }
    } else if (tab === 'trc') {
      if (view === 'history') html += U.card('Champions', 'Tri Nations (to 2011) and The Rugby Championship (since 2012), as our table computes them.', history(S, d.winners, 'trc'), { flush: true });
      else html += U.card(d.season + ' Rugby Championship: table', 'Bonus points throughout.', tableHTML(S, d.table, { form: formMap(d.results) }), { flush: true }) +
        (d.next && d.next.sim ? U.card('Chances', '', chancesTable(S, d.next.sim, [['title', 'Title'], ['last', 'Last']]), { flush: true }) : '');
    } else if (tab === 'rwc') {
      var rs = d.sim || { teams: [] };
      if (view === 'chances') {
        html += '<div class="qk-g2">' + U.card('Who lifts the 2027 World Cup?', 'Our title chance from simulated tournaments: every pool match, the best thirds and the knockouts played out (Australia at home; everyone else neutral).', chanceBars(S, rs.teams, 'champion', 'Our title chance')) +
          U.card('How far each side goes', 'Our chance to win the pool and to reach each round.', chancesTable(S, rs, [['win_pool', 'Win pool'], ['r16', 'Last 16'], ['qf', 'Quarters'], ['sf', 'Semis'], ['final', 'Final'], ['champion', 'Win']]), { flush: true }) + '</div>' +
          '<div class="sc-pools">' + Object.keys(d.pools || {}).map(function (p) {
            var teams = (rs.teams || []).filter(function (r) { return r.pool === p; }).sort(function (a, b) { return b.win_pool - a.win_pool; });
            return U.card('Pool ' + p, '', U.table([{ label: 'Team', align: 'left' }, { label: 'Win pool' }, { label: 'Last 16' }, { label: 'Win' }],
              teams.map(function (r) { return [teamCell(S, r.team), U.heat(r.win_pool, 0), U.heat(r.r16, 0), U.heat(r.champion, 1)]; }), { cls: 'sc-table' }), { flush: true });
          }).join('') + '</div>';
      } else if (view === 'bracket') html += U.card('The knockout bracket', 'Australia, 23 October to 13 November 2027.', rwcBracket(S, d));
      else html += U.card('World Cup winners', 'Every final in our data.', history(S, d.winners, 'rwc'), { flush: true });
    } else if (tab === 'w6n') {
      if (view === 'history') html += U.card('Champions', 'Each Women’s Six Nations in our data (Wikipedia’s season pages), as our table computes them.', history(S, d.winners, 'six'), { flush: true });
      else html += U.card(d.season + ' Women’s Six Nations: final table', 'Bonus points as the championship awards them (since 2017), including 3 for a Grand Slam. Results from Wikipedia (CC BY-SA 4.0).', tableHTML(S, d.table, { gs: true, form: formMap(d.results) }), { flush: true }) +
        U.card('Results', '', U.table([{ label: 'Date', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Score' }, { label: 'Away', align: 'left' }, { label: 'Our home chance' }],
          (d.results || []).map(function (r) { return [{ v: r.date, html: esc(SC.date(r.date)) }, teamCell(S, r.home), { v: r.hs - r.as, html: '<a href="' + esc(SC.matchHref(S, r.id)) + '">' + r.hs + '–' + r.as + '</a>' }, teamCell(S, r.away), { v: r.p, html: SC.pct(r.p) }]; }), { cls: 'sc-table' }), { flush: true });
    } else if (tab === 'wxv') {
      html += (d.tiers || []).map(function (t) {
        return U.card(d.season + ' ' + t.label, 'Each side plays three matches against the other group in its tier; a win is 4 points, with the standard bonus points. Results from Wikipedia (CC BY-SA 4.0).', tableHTML(S, t.table, { form: formMap(t.results) }), { flush: true });
      }).join('') + U.note('The tiers are labelled by the strength of their sides in our ratings today.');
    } else if (tab === 'wrwc') {
      html += U.card('Women’s World Cup winners', 'Every final in our data.', history(S, d.winners, 'rwc'), { flush: true });
    }
    body.innerHTML = html;
    U.wire(body);
    QK.follow && QK.follow.paint && QK.follow.paint();
  });
});
})();
