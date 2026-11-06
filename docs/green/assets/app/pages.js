/* The Quant Green — the events list (a tour's season) and the terms. Overview: overview.js; event: event.js; rankings:
 * rankings.js; Scouting Room: scout.js; player: player.js; Lab and courses: lab.js; model: model.js. */
(function () {
'use strict';

var QK = window.QK, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc;

// ── events (a tour's season) ───────────────────────────────────────────────

GR.page('events', function (el, params) {
  return GR.load('index.json').then(function (ix) {
    var tour = params.tour && GR.TOURS[params.tour] ? params.tour : 'pga';
    var seasons = ((ix.seasons || {})[tour] || []).slice().sort(function (a, b) { return b - a; });
    var season = params.season ? +params.season : seasons[0];
    return GR.load('schedule/' + tour + '/' + season + '.json').then(function (sc) {
      if (!el.isConnected) return;
      var ctl = '<div class="gr-controls">' + GR.seg('gr-tour', Object.keys(GR.TOURS).map(function (t) { return [t, GR.tourShort(t)]; }), tour, 'Tour') +
        '<label for="gr-season">Season</label><select id="gr-season" class="qk-select">' + seasons.map(function (s) { return '<option value="' + s + '"' + (s === season ? ' selected' : '') + '>' + s + '</option>'; }).join('') + '</select></div>';
      var evs = (sc.events || []).filter(function (e) { return !e.team || true; });
      var done = evs.filter(function (e) { return e.status === 'final' && e.winner; });
      var favWon = done.filter(function (e) { return e.fav && e.winner && e.fav.pid === e.winner.pid; }).length;
      el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: GR.tourName(tour), title: season + ' season',
          sub: evs.length + ' events' + (done.length ? '; our favourite won ' + favWon + ' of the ' + done.length + ' played' : '') + '.' }) + ctl + '<div id="gr-ev"></div>';
      QK.seg(el.querySelector('#gr-tour'), function (v) { location.hash = '#/fixtures/' + v; });
      el.querySelector('#gr-season').addEventListener('change', function (e) { location.hash = '#/fixtures/' + tour + '/' + e.target.value; });
      QK.table(el.querySelector('#gr-ev'), {
        dense: true, rows: evs.map(function (e) { var x = Object.assign({}, e); x.when = e.start; x.winner_name = e.winner ? e.winner.name : null; x.fav_win = e.fav ? e.fav.win : null; return x; }),
        rowHref: function (r) { return r.page ? '#/event/' + encodeURIComponent(r.id) : ''; },
        rowClass: function (r) { return r.status === 'live' ? 'gr-win' : ''; },
        columns: [
          { key: 'when', label: 'Dates', fmt: function (v, r) { return esc(GR.dates(r.start, r.end)); } },
          { key: 'name', label: 'Event', fmt: function (v, r) { return (r.page ? GR.eventLink(r.id, v) : esc(v)) + (r.major ? ' ' + QK.tag('Major') : '') + (r.team ? ' <span class="gr-muted">(team event)</span>' : '') + (r.status === 'live' ? ' ' + QK.tag('Live', 'live') : ''); } },
          { key: 'course', label: 'Course', fmt: function (v, r) { return r.course_id ? GR.courseLink(r.course_id, v) : esc(v || ''); } },
          { key: 'purse', label: 'Purse', num: true, fmt: function (v) { return GR.money(v, true); } },
          { key: 'winner_name', label: 'Winner', fmt: function (v, r) { return r.winner ? GR.playerLink(r.winner.pid, r.winner.name) + ' ' + GR.toParHTML(r.winner.tp) : '<span class="gr-muted">' + (r.status === 'upcoming' ? 'to come' : 'not on file') + '</span>'; } },
          { key: 'fav_win', label: 'Our favourite', num: true, tip: 'Our pre-event favourite and the chance we gave them to win', fmt: function (v, r) { return r.fav ? GR.playerLink(r.fav.pid, r.fav.name) + ' <span class="num">' + GR.pct(r.fav.win) + '</span>' : ''; } }
        ]
      });
    });
  });
});

GR.page('disclaimer', function (el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = t ? t.innerHTML : '';
});
})();
