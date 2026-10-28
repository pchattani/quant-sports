/* The Quant Footballer — a league's Race tab (#/competition/<slug>/race) and the team profiles the table reuses.
 *
 *   The race      our title, top-band and relegation chances over the season (history.json "daily", one point a
 *                 day; the hourly runs until two days exist), who moved this week and why (their results since,
 *                 with xG), what is settled by arithmetic (points still available against points needed: the
 *                 "magic numbers"), what rides on the next fixtures (probs.json "stakes": the simulated seasons
 *                 split by each fixture's result) and the run-in (our chances in each club's next five, and the
 *                 schedule strength left from our ratings)
 *   Team cards    each club's strengths and weak spots against the rest of the league: plain-English chips from
 *                 the percentiles of the clubs metric set (docs/METRICS_SPEC.md "Clubs", analytics.json
 *                 teams[].profile), set pieces (analytics.json "set_pieces"), and points against expected points
 *   The shape     attack v defence, points v expected points ("Who's for real?"), and the tiers our chances draw
 *
 * Plain leagues (kind "league") and Argentina (kind "liga"): the conference and playoff formats keep their own tabs.
 * Argentina's race is run on its Tabla Anual (table.json in the leagues' shape, from build_site_liga.py): the title is
 * the top of that table (table.json title_key / title_label / title_phrase / title_kpi / title_tier / safety_label
 * rename it; a league's table.json has none of them, so nothing changes there), the bands are the places that
 * guarantee a Libertadores or Sudamericana berth and the drop (either route), and two sections of its own follow:
 * the zone races for the playoff places and the promedio race. ES5. */
(function (FB) {
'use strict';
var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, pct = FB.pct, num = FB.num, signed = FB.signed;

function $(root, id) { return root.querySelector('#' + id); }
function pc(v) { return isNum(v) ? pct(v, v > 0 && v < 0.1 ? 1 : 0) : '—'; }
function msg(t) { return FB.muted(t); }
function nowMs() { var n = QK.now ? QK.now() : Date.now(); return typeof n === 'number' ? n : new Date(n).getTime(); }
function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
function sum(a) { return a.reduce(function (s, x) { return s + (isNum(x) ? x : 0); }, 0); }
function shortName(t) { var w = String(t).split(' '); return t.length > 13 && w.length > 1 ? w.slice(0, -1).map(function (x) { return x.charAt(0) + '.'; }).join(' ') + ' ' + w[w.length - 1] : t; }

/* Which competitions get the tab. */
function eligible(c) { return !!c && c.ok && (c.kind === 'league' || c.kind === 'liga') && c.scope !== 'international' && !FB.isLastEdition(c); }
/* A table.json override of the title's words (Argentina: the top of the Tabla Anual), else the league default. */
function tl(R, key, dflt) { return (R && R.t && R.t[key]) || dflt; }

// ── the model of the race from the payloads ────────────────────────────────

/* d: { meta, teams, fixtures, table, probs, history, strength, analytics }. */
function model(c, d) {
  var t = d.table || {}, rows = t.standings || [];
  var bands = t.bands || (d.probs || {}).bands || [];
  var ups = bands.filter(function (b) { return b.kind === 'up'; }), downs = bands.filter(function (b) { return b.kind === 'down'; });
  var P = {};
  ((d.probs || {}).teams || []).forEach(function (p) { P[p.team] = p; });
  var S = {};
  ((d.strength || {}).rows || []).forEach(function (r) { S[r.team] = r; });
  var an = d.analytics || {};
  var prof = {};
  Object.keys(an.teams || {}).forEach(function (k) { prof[k] = an.teams[k]; });
  var sp = ((an.set_pieces || {}).teams) || {};
  var fx = ((d.fixtures || {}).matches || []).filter(function (f) { return (f.stage || 'league') === 'league'; });
  var N = t.matches_per_team || null;
  var rel = function (team) { var p = P[team]; if (!p) return null; return downs.reduce(function (s, b) { return s + ((p.bands || {})[b.key] || 0); }, 0); };
  return { c: c, t: t, rows: rows, bands: bands, ups: ups, downs: downs, up1: ups[0] || null, P: P, S: S, prof: prof, sp: sp,
    fx: fx, N: N, split: !!t.split, rel: rel, hist: d.history || {}, m: d.meta || {}, an: an, stakes: (d.probs || {}).stakes || [] };
}

/* A metric's current chance for a club: 'title', an up band key, or 'rel'. */
function chanceOf(R, team, key) {
  var p = R.P[team];
  if (!p) return null;
  if (key === 'title') return R.t.title_key ? p[R.t.title_key] : p.p_title;
  if (key === 'rel') return R.rel(team);
  return (p.bands || {})[key];
}
function metricLabel(R, key) {
  if (key === 'title') return tl(R, 'title_label', 'Title');
  if (key === 'rel') return R.downs.length > 1 ? 'Drop zone' : (R.downs[0] || {}).label || 'Relegation';
  var b = R.bands.filter(function (x) { return x.key === key; })[0];
  return b ? b.label + (b.first === b.last ? '' : ' (top ' + b.last + ')') : key;
}
function metricShort(R, key) {
  if (key === 'title') return tl(R, 'title_short', 'Title');
  if (key === 'rel') return 'Drop';
  var b = R.bands.filter(function (x) { return x.key === key; })[0];
  return b ? (b.first === 1 ? 'Top ' + b.last : b.label) : key;
}

// ── chances over time ──────────────────────────────────────────────────────

/* The series for one metric: daily points when two or more days exist, else the hourly runs. Returns
   { pts: [{x, v: {team: p}}], daily, since } or null. History keys: 'title', 'band' (the first up band), 'relegation'. */
function histSeries(R, key) {
  var hk = key === 'title' ? 'title' : key === 'rel' ? 'relegation' : 'band';
  var daily = (R.hist.daily || []).filter(function (e) { return e && e[hk]; });
  if (daily.length >= 2) return { pts: daily.map(function (e) { return { x: e.d + 'T12:00:00Z', v: e[hk] }; }), daily: true, since: daily[0].d };
  var sk = ((R.t.hist_keys || {})[hk]) || hk;
  var snaps = (R.hist.snapshots || []).filter(function (s) { return s && s[sk]; });
  if (snaps.length >= 2) return { pts: snaps.map(function (s) { return { x: s.ts, v: s[sk] }; }), daily: false, since: snaps[0].ts };
  return null;
}
function raceChart(box, R, key) {
  var h = histSeries(R, key);
  if (!h) { box.style.height = 'auto'; box.innerHTML = msg('Our chances are logged once a day from today: the line appears with the second day.'); return null; }
  var last = h.pts[h.pts.length - 1].v;
  /* the clubs in play now, from the latest probs (the history keeps the top 16 of each run) */
  var now = {};
  R.rows.forEach(function (r) { var v = chanceOf(R, r.team, key); if (isNum(v)) now[r.team] = v; });
  var teams = Object.keys(now).length ? Object.keys(now) : Object.keys(last);
  teams = teams.filter(function (t) { return (now[t] || last[t] || 0) > 0.004 && (now[t] || last[t] || 0) < 0.999; })
    .sort(function (a, b) { return (now[b] || last[b] || 0) - (now[a] || last[a] || 0); }).slice(0, 6);
  if (!teams.length) { box.style.height = 'auto'; box.innerHTML = msg('Nothing is in doubt in this race: every club is at 0% or 100% in our simulations.'); return null; }
  var series = teams.map(function (t) { return { name: t, label: shortName(t), data: h.pts.map(function (p) { return isNum(p.v[t]) ? p.v[t] : 0; }) }; });
  var top = Math.max.apply(null, series.map(function (x) { return Math.max.apply(null, x.data.concat([0])); }).concat([0.01]));
  QKC.forecast(box, {
    x: h.pts.map(function (p) { return p.x; }), xType: 'time',
    xLabel: function (v) { return h.daily ? FB.fmtDate(new Date(v)) : FB.fmtStamp(new Date(v)); },
    xFmt: function (v) { var dd = new Date(v); return isNaN(dd.getTime()) ? '' : dd.getDate() + ' ' + FB.MONTHS[dd.getMonth()]; },
    yMax: top < 0.6 ? 'auto' : 1, xName: h.daily ? 'Date (one point a day)' : 'Model run (date)', yName: 'Our chance: ' + metricShort(R, key),
    label: 'Our ' + metricLabel(R, key) + ' chances over time', series: series
  });
  return h;
}

// ── who moved ──────────────────────────────────────────────────────────────

/* Results of a club since an ISO day (inclusive), oldest first: "W 2–1 v Chelsea (H) · xG 1.8–0.9". */
function resultsSince(R, team, since) {
  return R.fx.filter(function (f) { return f.status === 'finished' && (f.home === team || f.away === team) && String(f.date || '') >= since && isNum(f.hs); })
    .sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); }).map(function (f) {
      var home = f.home === team, gf = home ? f.hs : f.as, ga = home ? f.as : f.hs, opp = home ? f.away : f.home;
      var xg = f.xg && isNum(f.xg[0]) ? (home ? f.xg : [f.xg[1], f.xg[0]]) : null;
      var res = gf > ga ? 'W' : gf < ga ? 'L' : 'D';
      return { res: res, txt: (res === 'W' ? 'Beat ' : res === 'L' ? 'Lost to ' : 'Drew with ') + opp + ' ' + gf + '–' + ga + (home ? '' : ' away') + (xg ? ' (xG ' + num(xg[0], 1) + '–' + num(xg[1], 1) + ')' : ''), xg: xg, gf: gf, ga: ga };
    });
}
/* The movers of one metric since the daily entry nearest a week ago (at least a day old). */
function movers(R, key) {
  var hk = key === 'title' ? 'title' : key === 'rel' ? 'relegation' : 'band';
  var daily = (R.hist.daily || []).filter(function (e) { return e && e[hk]; });
  var today = new Date(nowMs()).toISOString().slice(0, 10);
  var old = daily.filter(function (e) { return e.d < today; });
  if (!old.length) return null;
  var target = new Date(nowMs() - 7 * 864e5).toISOString().slice(0, 10);
  var base = old.slice().sort(function (a, b) { return Math.abs(Date.parse(a.d) - Date.parse(target)) - Math.abs(Date.parse(b.d) - Date.parse(target)) || (a.d < b.d ? -1 : 1); })[0];
  var rows = R.rows.map(function (r) {
    var now = chanceOf(R, r.team, key), was = isNum(base[hk][r.team]) ? base[hk][r.team] : 0;
    return { team: r.team, now: now, was: was, d: isNum(now) ? now - was : null };
  }).filter(function (r) { return isNum(r.d) && Math.abs(r.d) >= 0.02; });
  rows.sort(function (a, b) { return Math.abs(b.d) - Math.abs(a.d); });
  return { since: base.d, rows: rows.slice(0, 6) };
}
/* Elo movers over the last week (strength.json elo_history): the fallback while the daily log is under a day old. */
function eloMovers(R, d) {
  var eh = ((d.strength || {}).elo_history) || {};
  var cut = new Date(nowMs() - 8 * 864e5).toISOString().slice(0, 10);
  var rows = Object.keys(eh).map(function (t) {
    var h = eh[t] || [];
    if (h.length < 2) return null;
    var before = h.filter(function (x) { return x.date < cut; }).slice(-1)[0];
    var last = h[h.length - 1];
    if (!before || before === last) return null;
    return { team: t, d: last.elo - before.elo, now: last.elo, since: before.date };
  }).filter(function (r) { return r && Math.abs(r.d) >= 3; });
  rows.sort(function (a, b) { return Math.abs(b.d) - Math.abs(a.d); });
  return rows.slice(0, 6);
}
function moversHTML(R, ctx, key, d) {
  var mv = movers(R, key);
  if (mv && mv.rows.length) {
    return '<ul class="fb-rc-movers">' + mv.rows.map(function (r) {
      var res = resultsSince(R, r.team, mv.since);
      var why = res.length ? res.map(function (x) { return '<span class="fb-rc-res ' + x.res + '">' + esc(x.txt) + '</span>'; }).join('') : '<span class="qk-muted">No match since; the clubs around them moved it.</span>';
      return '<li><div class="fb-rc-mv-h">' + ctx.club(r.team) + '<b class="fb-num ' + (r.d > 0 ? 'fb-up' : 'fb-down') + '">' + (r.d > 0 ? '▲ ' : '▼ ') + Math.abs(Math.round(r.d * 100)) + ' pp</b></div>' +
        '<div class="fb-rc-mv-s"><span class="fb-num">' + pc(r.was) + ' → ' + pc(r.now) + '</span>' + why + '</div></li>';
    }).join('') + '</ul><p class="fb-cap">' + esc(metricLabel(R, key)) + ' chance, percentage points since ' + esc(FB.fmtDate(mv.since)) + '. The reasons are each club\'s own results since then; a rival\'s result moves a chance too.</p>';
  }
  if (mv && !mv.rows.length) return msg('No ' + esc(metricLabel(R, key).toLowerCase()) + ' chance has moved 2 points or more since ' + esc(FB.fmtDate(mv.since)) + '.');
  var em = eloMovers(R, d);
  if (!em.length) return msg('The daily log of our chances starts today; movers appear from tomorrow.');
  return '<ul class="fb-rc-movers">' + em.map(function (r) {
    var res = resultsSince(R, r.team, r.since);
    return '<li><div class="fb-rc-mv-h">' + ctx.club(r.team) + '<b class="fb-num ' + (r.d > 0 ? 'fb-up' : 'fb-down') + '">' + (r.d > 0 ? '▲ ' : '▼ ') + Math.abs(Math.round(r.d)) + ' Elo</b></div>' +
      '<div class="fb-rc-mv-s">' + (res.length ? res.map(function (x) { return '<span class="fb-rc-res ' + x.res + '">' + esc(x.txt) + '</span>'; }).join('') : '') + '</div></li>';
  }).join('') + '</ul><p class="fb-cap">Our daily log of chances starts today, so until it covers a week these are the biggest moves in our Elo rating over the last week, with the results behind them.</p>';
}

// ── what is settled: the arithmetic ────────────────────────────────────────

/* For each club: played, points, the most it can reach. Assumes every club plays N league matches (no split). */
function arith(R) {
  if (!R.N || R.split) return null;
  var rows = R.rows.map(function (r) { var left = Math.max(0, R.N - (r.played || 0)); return { team: r.team, pts: r.pts || 0, left: left, max: (r.pts || 0) + 3 * left, pos: r.pos }; });
  if (!rows.length) return null;
  /* k-th largest of a list (1-based) */
  function kth(list, k) { var s = list.slice().sort(function (a, b) { return b - a; }); return k <= s.length ? s[k - 1] : -Infinity; }
  rows.forEach(function (x) {
    var others = rows.filter(function (y) { return y !== x; });
    var oMax = others.map(function (y) { return y.max; }), oPts = others.map(function (y) { return y.pts; });
    /* certain of a top-k place: at most k-1 others can still reach its points (a tie counts against it) */
    x.topK = function (k) {
      var need = kth(oMax, k) - x.pts + 1;                        // points that make it certain, whatever else happens
      var out = oPts.filter(function (p) { return p > x.max; }).length >= k;
      return { need: Math.max(0, need), sure: need <= 0, out: out };
    };
  });
  return rows;
}
function settledHTML(R, ctx) {
  var A = arith(R);
  var n = R.rows.length;
  var sims = R.m.n_sims ? FB.int(R.m.n_sims) : 'our';
  var out = [];
  if (!A) {
    out.push(FB.note(R.split ? 'This league splits into groups and halves the points partway through, so the points arithmetic is not shown; the chances above come from simulating the split.' : 'The schedule length is not known for this league, so the points arithmetic is not shown.'));
  }
  var items = [];
  if (A) {
    /* "Arsenal 85 of 93": the points that make a place certain whatever the rest do, against the points still
       available to the club; a need above what is left cannot be met on the club's own results yet */
    var needTxt = function (x, k) { var nd = x.topK(k).need; return esc(x.team) + ' <b class="fb-num">' + nd + '</b><span class="qk-muted"> of ' + (3 * x.left) + '</span>'; };
    var reach = function (x, k) { return x.topK(k).need <= 3 * x.left; };
    /* our projected line: the projected points of the club ranked k-th by projected points */
    var projAt = function (k) { var e = R.rows.map(function (r) { return (R.P[r.team] || {})[R.t.exp_key || 'exp_pts']; }).filter(isNum).sort(function (a, b) { return b - a; }); return k <= e.length ? e[k - 1] : null; };
    var leader = A.slice().sort(function (a, b) { return b.pts - a.pts; })[0];
    var alive = A.filter(function (x) { return x.max >= leader.pts; });
    var tk = leader.topK(1);
    var pj1 = projAt(1);
    var phrase = R.t.title_phrase;
    items.push([tl(R, 'title_label', 'Title'), tk.sure ? '<b>' + ctx.club(leader.team) + '</b> ' + (phrase ? 'will ' + esc(phrase) : 'are champions') + ': no one can reach their points.' :
      plural(alive.length, 'club') + ' can still mathematically ' + (phrase ? esc(phrase) : 'win it') + (alive.length < n ? ' (' + plural(n - alive.length, 'club') + ' cannot)' : ': all of them') + '. ' +
      ctx.club(leader.team) + ' lead on ' + leader.pts + '. ' + (reach(leader, 1) ? 'Points that would make it certain whatever the rest do: ' + needTxt(leader, 1) + ' still to play for (fewer if rivals drop points; level points go to goal difference).' :
        'The leader cannot make it certain on its own results yet: a rival could still pass that total.') +
      (isNum(pj1) ? ' Our projected ' + (phrase ? 'leader' : 'champion') + ' finishes on about <b class="fb-num">' + Math.round(pj1) + '</b> points.' : '')]);
    R.ups.slice(0, 2).forEach(function (b) {
      var sure = A.filter(function (x) { return x.topK(b.last).sure; }), out2 = A.filter(function (x) { return x.topK(b.last).out; });
      var inZone = A.filter(function (x) { return x.pos <= b.last && !x.topK(b.last).sure && reach(x, b.last); }).sort(function (a, c2) { return a.pos - c2.pos; });
      var pj = projAt(b.last);
      items.push([esc(b.label) + (b.first === 1 ? ' (top ' + b.last + ')' : ''),
        (sure.length ? plural(sure.length, 'club') + ' certain: ' + sure.map(function (x) { return esc(x.team); }).join(', ') + '. ' : 'No club is certain yet. ') +
        (out2.length ? plural(out2.length, 'club') + ' can no longer reach the top ' + b.last + '. ' : 'Every club can still reach the top ' + b.last + '. ') +
        (b.first === 1 && inZone.length ? 'Points that would make it certain for the clubs in the places now: ' + inZone.map(function (x) { return needTxt(x, b.last); }).join(' · ') + '.' : '') +
        (isNum(pj) ? ' Our projected ' + FB.ordinal(b.last) + ' place: about <b class="fb-num">' + Math.round(pj) + '</b> points.' : '')]);
    });
    if (R.downs.length) {
      var safeN = Math.min.apply(null, R.downs.map(function (b) { return b.first; })) - 1;
      var safe = A.filter(function (x) { return x.topK(safeN).sure; }), down = A.filter(function (x) { return x.topK(safeN).out; });
      var bottom = A.filter(function (x) { return !x.topK(safeN).sure && !x.topK(safeN).out; }).sort(function (a, b) { return b.pos - a.pos; }).slice(0, Math.min(6, n - safeN + 3));
      var canAlone = bottom.filter(function (x) { return reach(x, safeN); });
      var pjS = projAt(safeN);
      items.push([tl(R, 'safety_label', 'Safety'), (safe.length ? plural(safe.length, 'club') + ' mathematically safe. ' : 'No club is mathematically safe yet. ') +
        (down.length ? '<b>' + down.map(function (x) { return esc(x.team); }).join(', ') + '</b> cannot climb out. ' : '') +
        (canAlone.length ? 'Points that would make the clubs near the bottom safe whatever the rest do: ' + canAlone.map(function (x) { return needTxt(x, safeN); }).join(' · ') + '. ' :
          bottom.length ? 'No club near the bottom can make itself safe on its own results yet: the clubs around it still have too many points to play for. ' : '') +
        (isNum(pjS) ? 'Our projected safety line (the ' + FB.ordinal(safeN) + ' place): about <b class="fb-num">' + Math.round(pjS) + '</b> points.' : '')]);
    }
  }
  /* what the simulations say that the arithmetic cannot yet */
  var keys = ['title'].concat(R.ups.slice(0, 2).map(function (b) { return b.key; })).concat(R.downs.length ? ['rel'] : []);
  /* certainties grouped by what is certain ("Arsenal, Chelsea finish top 4"); a club certain of one up band is not
     listed again for a wider one (Argentina's Libertadores inside "Libertadores or Sudamericana") */
  var every = [], none = [], byPhrase = {}, order = [], upDone = {};
  keys.forEach(function (k) {
    R.rows.forEach(function (r) {
      var p = chanceOf(R, r.team, k);
      if (!isNum(p) || p < 0.9999) return;
      var bk = R.bands.filter(function (x) { return x.key === k; })[0];
      var ph = k === 'title' ? tl(R, 'title_phrase', 'win the title') : k === 'rel' ? 'go down' : bk && bk.phrase ? bk.phrase : 'finish ' + metricShort(R, k).toLowerCase();
      if (k !== 'title' && k !== 'rel') { if (upDone[r.team]) return; upDone[r.team] = 1; }
      if (!byPhrase[ph]) { byPhrase[ph] = []; order.push(ph); }
      byPhrase[ph].push(r.team);
    });
  });
  order.forEach(function (ph) { var t = byPhrase[ph]; every.push((t.length > 1 ? t.slice(0, -1).join(', ') + ' and ' + t[t.length - 1] : t[0]) + ' ' + ph); });
  if (R.downs.length) {
    var stayUp = R.rows.filter(function (r) { var p = R.rel(r.team); return isNum(p) && p <= 0.0001; }).length;
    if (stayUp) none.push(plural(stayUp, 'club') + ' never go down');
  }
  var aliveSim = R.rows.filter(function (r) { var p = chanceOf(R, r.team, 'title'); return isNum(p) && p > 0; }).length;
  none.push(plural(aliveSim, 'club') + ' ' + tl(R, 'title_phrase', 'win the title') + ' at least once');
  items.push(['In ' + sims + ' simulated seasons', (every.length ? 'In every one: ' + every.map(esc).join('; ') + '. ' : '') + none.map(esc).join('; ') + '.']);
  out.push('<dl class="fb-rc-settled">' + items.map(function (x) { return '<div><dt>' + x[0] + '</dt><dd>' + x[1] + '</dd></div>'; }).join('') + '</dl>');
  return out.join('');
}

// ── what's at stake next ───────────────────────────────────────────────────

function stakesHTML(R, ctx) {
  var done = {};
  R.fx.forEach(function (f) { if (f.status === 'finished' || f.status === 'postponed' || f.status === 'cancelled') done[String(f.id)] = 1; });
  var list = (R.stakes || []).filter(function (s) { return (s.m || []).length && !done[String(s.id)]; });
  if (!list.length) return null;
  list = list.slice().sort(function (a, b) { return (b.swing || 0) - (a.swing || 0); }).slice(0, 6);
  return '<div class="fb-rc-stakes">' + list.map(function (s) {
    var head = '<div class="fb-rc-st-h">' + ctx.club(s.home) + '<span class="qk-muted">v</span>' + ctx.club(s.away) + '</div>' +
      '<div class="fb-rc-st-w fb-cap">' + esc(s.date ? FB.fmtDate(s.date, { time: true }) : '') + ' · our chances ' + (s.p || []).map(function (x) { return pc(x); }).join(' / ') + ' (home / draw / away)</div>';
    var body = (s.m || []).slice(0, 3).map(function (m) {
      var rows = Object.keys(m.teams || {}).map(function (t) {
        var v = m.teams[t], cur = chanceOf(R, t, m.kind === 'down' ? 'rel' : m.key);
        if (m.kind === 'down' && R.downs.length > 1) cur = chanceOf(R, t, m.key);
        return '<tr><th scope="row">' + esc(shortName(t)) + '</th><td class="fb-num">' + pc(cur) + '</td><td class="fb-num">' + pc(v[0]) + '</td><td class="fb-num">' + (isNum(v[1]) ? pc(v[1]) : '—') + '</td><td class="fb-num">' + pc(v[2]) + '</td></tr>';
      }).join('');
      return '<div class="fb-rc-st-m"><div class="qk-kicker" data-tip="Half the total change in this race\'s chances between a home win and an away win, in percentage points" tabindex="0">' + esc(m.label) + ' · swing ' + num((m.swing || 0) * 100, 0) + ' pts</div>' +
        '<table class="fb-rc-st-t"><thead><tr><th></th><th>Now</th><th>' + esc(FB.clubCode(s.home, s.away)) + ' win</th><th>Draw</th><th>' + esc(FB.clubCode(s.away, s.home)) + ' win</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    }).join('');
    return '<article class="qk-card fb-rc-st">' + head + body + '</article>';
  }).join('') + '</div>';
}
/* Without the stakes field (a build before it): the next fixtures between clubs whose races are most open. */
function stakesGuide(R, ctx) {
  var up = R.fx.filter(function (f) { return f.status === 'live' || (f.status === 'scheduled' && !(Date.parse(f.date) < nowMs() - 3 * 3600e3)); }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
  if (!up.length) return msg('No league fixtures left.');
  var first = Date.parse(up[0].date), soon = up.filter(function (f) { return Date.parse(f.date) - first <= 7 * 864e5; });
  var open = function (t) { var s = 0; ['title', R.up1 ? R.up1.key : null, 'rel'].forEach(function (k) { if (!k) return; var p = chanceOf(R, t, k); if (isNum(p)) s += p * (1 - p); }); return s; };
  soon.forEach(function (f) { f._o = open(f.home) + open(f.away); });
  soon.sort(function (a, b) { return b._o - a._o; });
  return '<div class="fb-fxlist">' + soon.slice(0, 6).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); }).map(function (f) { return FB.fixtureRow(f, { slug: R.c.slug, date: true, round: true }); }).join('') + '</div>' +
    '<p class="fb-cap">A guide until the next simulation splits each result: the coming fixtures between the clubs whose races are most open now.</p>';
}

// ── the run-in ─────────────────────────────────────────────────────────────

function runIn(box, R, ctx) {
  var up = R.fx.filter(function (f) { return f.status === 'live' || (f.status === 'scheduled' && !(Date.parse(f.date) < nowMs() - 3 * 3600e3)); }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
  var sosRank = {};
  var withSos = R.rows.filter(function (r) { return R.S[r.team] && isNum(R.S[r.team].sos_remaining); }).map(function (r) { return r.team; });
  withSos.sort(function (a, b) { return R.S[b].sos_remaining - R.S[a].sos_remaining; }).forEach(function (t, i) { sosRank[t] = i + 1; });
  var rows = R.rows.map(function (r) {
    var next = up.filter(function (f) { return f.home === r.team || f.away === r.team; }).slice(0, 5);
    var xp = 0, n = 0;
    var chips = next.map(function (f) {
      var home = f.home === r.team, opp = home ? f.away : f.home, m = f.model || {};
      var w = home ? m.h : m.a, dr = m.d;
      if (isNum(w) && isNum(dr)) { xp += 3 * w + dr; n++; }
      var col = isNum(w) ? QK.pctColor(Math.round(w * 100)) : 'var(--s-3)', ink = isNum(w) ? QK.pctInk(Math.round(w * 100)) : 'var(--ink-2)';
      return '<span class="fb-rc-fx" style="background:' + col + ';color:' + ink + '" title="' + esc((home ? 'Home v ' : 'Away at ') + opp + (isNum(w) ? ': our chance of a win ' + pct(w) : '')) + '">' + esc(FB.clubCode(opp)) + '<small>' + (home ? 'H' : 'A') + (isNum(w) ? ' ' + Math.round(w * 100) : '') + '</small></span>';
    }).join('');
    return { team: r.team, pos: r.pos, chips: chips, xp: n ? xp : null, n: n, ppg: n ? xp / n : null, sos: R.S[r.team] ? R.S[r.team].sos_remaining : null, rank: sosRank[r.team] || null };
  });
  FB.table(box, [
    { key: 'pos', label: '#', num: true },
    { key: 'team', label: 'Club', sticky: true, fmt: function (v) { return ctx.club(v); } },
    { key: 'chips', label: 'Next five', sort: false, tip: 'Opponent, home or away, and our chance of a win in %: hot colours are likely wins, cold ones hard games', fmt: function (v) { return '<span class="fb-rc-fxs">' + (v || '—') + '</span>'; } },
    { key: 'ppg', label: 'xPts/game', num: true, tip: 'Our expected points per game over those fixtures (3 x win chance + draw chance)', fmt: function (v) { return num(v, 2); } },
    { key: 'rank', label: 'Run-in', num: true, tip: 'How hard the rest of the season is from our ratings: 1 is the hardest schedule left', fmt: function (v) { return isNum(v) ? FB.ordinal(v) + ' hardest' : '—'; } }
  ], rows, { sort: { key: 'pos', dir: 'asc' }, caption: 'The run-in' });
}

// ── team profiles ──────────────────────────────────────────────────────────

/* The clubs metric set's headline order (METRICS_SPEC "Clubs"), then set pieces. style: neither better nor worse. */
var CARD_KEYS = [
  ['xg_diff', 'xG difference', 2, false], ['xg_for', 'xG for', 2, false], ['xg_against', 'xG against', 2, false],
  ['sot_diff', 'Shots on target diff.', 1, false], ['field_tilt', 'Field tilt', 0, false], ['big_chances', 'Big chances', 1, false],
  ['possession', 'Possession', 0, true], ['ppda', 'PPDA (pressing)', 1, true]
];
var SP_KEYS = [['sp_xg', 'Set-piece xG for', 2], ['sp_xga', 'Set-piece xG against', 2], ['fb_xg', 'Fast-break xG for', 2]];
var EARLY = 8;   // matches: the clubs metric set's M50 for xG difference is about 9 matches

/* Chips for a club: [{t, kind: 'good' | 'bad' | 'style' | 'luck', why}], strongest first. */
function chipsFor(R, team) {
  var pr = (R.prof[team] || {}).profile || {}, played = (R.prof[team] || {}).played || 0, sp = R.sp[team], s = R.S[team] || {};
  var out = [];
  if (played < 3) return out;
  function P(k) { var x = pr[k]; return x && isNum(x.pct) ? x.pct : null; }
  function add(t, kind, score, why) { out.push({ t: t, kind: kind, score: score, why: why }); }
  var a = P('xg_for'), dfn = P('xg_against'), diff = P('xg_diff'), tilt = P('field_tilt'), ppda = P('ppda'), poss = P('possession'), bc = P('big_chances');
  if (isNum(diff) && diff >= 90) add('Dominant: best underlying numbers', 'good', diff + 5, 'xG difference in the top 10% of the league');
  if (isNum(a)) { if (a >= 85) add('Elite attack', 'good', a, 'xG for in the top 15%'); else if (a >= 70) add('Dangerous attack', 'good', a - 10, 'xG for in the top 30%'); else if (a <= 15) add('Blunt attack', 'bad', 100 - a, 'xG for in the bottom 15%'); }
  if (isNum(dfn)) { if (dfn >= 85) add('Elite defence', 'good', dfn, 'xG against in the best 15%'); else if (dfn >= 70) add('Hard to break down', 'good', dfn - 10, 'xG against in the best 30%'); else if (dfn <= 15) add('Leaky defence', 'bad', 100 - dfn, 'xG against in the worst 15%'); }
  if (isNum(tilt)) { if (tilt >= 80) add('Plays in the other half', 'good', tilt - 15, 'field tilt in the top 20%'); else if (tilt <= 20) add('Pinned back', 'bad', 85 - tilt, 'field tilt in the bottom 20%'); }
  if (isNum(bc) && bc >= 85) add('Makes big chances', 'good', bc - 15, 'big chances created in the top 15%');
  if (sp && sp.pct) {
    if (isNum(sp.pct.sp_xg) && sp.pct.sp_xg >= 80) add('Set-piece threat', 'good', sp.pct.sp_xg - 12, 'set-piece xG for in the top 20% (' + num(sp.sp_xg, 2) + ' a match)');
    if (isNum(sp.pct.sp_xga) && sp.pct.sp_xga <= 20) add('Vulnerable at set pieces', 'bad', 90 - sp.pct.sp_xga, 'set-piece xG against in the worst 20% (' + num(sp.sp_xga, 2) + ' a match)');
    else if (isNum(sp.pct.sp_xga) && sp.pct.sp_xga >= 85) add('Solid at set pieces', 'good', sp.pct.sp_xga - 20, 'set-piece xG against in the best 15%');
    if (isNum(sp.pct.fb_xg) && sp.pct.fb_xg >= 85) add('Lethal on the break', 'good', sp.pct.fb_xg - 18, 'fast-break xG in the top 15%');
  }
  if (isNum(ppda)) { if (ppda >= 80) add('Presses high', 'style', 40, 'PPDA in the lowest 20%: few passes allowed before a challenge'); else if (ppda <= 15) add('Sits off', 'style', 30, 'PPDA in the highest 15%'); }
  if (isNum(poss)) { if (poss >= 85) add('Keeps the ball', 'style', 35, 'possession in the top 15%'); else if (poss <= 15) add('Happy without the ball', 'style', 30, 'possession in the bottom 15%'); }
  /* luck: points against expected points from our xG (strength.json), per match so a season's length does not matter */
  if (isNum(s.luck) && isNum(s.played) && s.played >= 4) {
    var per = s.luck / s.played;
    if (per >= 0.3) add('Riding luck: ' + signed(s.luck, 1) + ' pts above xG', 'luck', 60 + per * 40, 'points ' + signed(s.luck, 1) + ' above expected points from our xG');
    else if (per <= -0.3) add('Unlucky: ' + signed(s.luck, 1) + ' pts below xG', 'luck', 60 - per * 40, 'points ' + signed(s.luck, 1) + ' below expected points from our xG');
  }
  /* form against the season: the last six matches' xG difference v the season's */
  var f = ((R.prof[team] || {}).form || []).slice(0, 6), sx = pr.xg_diff;
  if (f.length >= 4 && sx && isNum(sx.v) && played >= 8) {
    var fx = f.filter(function (m) { return isNum(m.xg) && isNum(m.xga); });
    if (fx.length >= 4) {
      var rec = sum(fx.map(function (m) { return m.xg - m.xga; })) / fx.length;
      if (rec - sx.v >= 0.5) add('Trending up', 'good', 45, 'last ' + fx.length + ' matches: xG difference ' + signed(rec, 2) + ' a match against ' + signed(sx.v, 2) + ' for the season');
      else if (rec - sx.v <= -0.5) add('Trending down', 'bad', 45, 'last ' + fx.length + ' matches: xG difference ' + signed(rec, 2) + ' a match against ' + signed(sx.v, 2) + ' for the season');
    }
  }
  out.sort(function (x, y) { return y.score - x.score; });
  return out;
}
function chipHTML(ch) { return '<span class="fb-rc-chip ' + ch.kind + '" data-tip="' + esc(ch.why) + '" tabindex="0">' + esc(ch.t) + '</span>'; }
/* At most n chips, at least one weak spot when there is one. */
function topChips(list, n) {
  var pick = list.slice(0, n);
  var bad = list.filter(function (c) { return c.kind === 'bad'; })[0];
  if (bad && pick.indexOf(bad) < 0 && pick.length) pick[pick.length - 1] = bad;
  return pick;
}
function shortVersion(R, team, chips) {
  var good = chips.filter(function (c) { return c.kind === 'good'; }), bad = chips.filter(function (c) { return c.kind === 'bad'; }), luck = chips.filter(function (c) { return c.kind === 'luck'; })[0];
  var s = [];
  if (good.length) s.push('Strength: ' + good[0].why + '.');
  if (bad.length) s.push('Weak spot: ' + bad[0].why + '.');
  else if (!good.length) s.push('Nothing stands out either way: close to the league average across the board.');
  if (luck) s.push(luck.kind === 'luck' && /below/.test(luck.why) ? 'The results have lagged the chances: ' + luck.why + '.' : 'The results have run ahead of the chances: ' + luck.why + '.');
  return s.join(' ');
}
function cardHTML(R, ctx, r) {
  var team = r.team, pr = (R.prof[team] || {}).profile || {}, played = (R.prof[team] || {}).played || 0, sp = R.sp[team];
  var chips = chipsFor(R, team);
  var bars = CARD_KEYS.filter(function (k) { return pr[k[0]] && isNum(pr[k[0]].pct); }).map(function (k) {
    var x = pr[k[0]];
    return { label: k[1], pctl: x.pct, value: num(x.v, k[2]) + (k[0] === 'field_tilt' || k[0] === 'possession' ? '%' : ''), style: k[3], early: played < EARLY };
  });
  if (sp && sp.pct) SP_KEYS.forEach(function (k) { if (isNum(sp.pct[k[0]])) bars.push({ label: k[1], pctl: sp.pct[k[0]], value: num(sp[k[0]], k[2]), early: played < EARLY }); });
  var p = R.P[team] || {};
  var head = '<summary class="fb-rc-card-h"><span class="fb-rc-pos fb-num">' + esc(r.pos) + '</span>' + FB.crest(ctx.tidOf(team), team, 'md') +
    '<span class="fb-rc-card-n"><b>' + esc(team) + '</b><span class="fb-cap fb-num">' + r.pts + ' pts · ' + r.played + ' played' + (isNum(p[R.t.exp_key || 'exp_pts']) ? ' · projected ' + num(p[R.t.exp_key || 'exp_pts'], 0) : '') + '</span></span>' +
    '<span class="fb-rc-chips">' + (chips.length ? topChips(chips, 3).map(chipHTML).join('') : '<span class="qk-muted fb-cap">' + (played < 3 ? 'Too few matches' : 'League average across the board') + '</span>') + '</span></summary>';
  var body = '<div class="fb-rc-card-b"><p class="fb-rc-short">' + esc(shortVersion(R, team, chips)) + '</p>' +
    (chips.length > 3 ? '<div class="fb-rc-chips all">' + chips.map(chipHTML).join('') + '</div>' : '') +
    (bars.length ? QK.pctlBars(bars) + '<p class="fb-cap">Percentiles against the rest of ' + esc(R.c.name) + ' this season, per match' + (played < EARLY ? '; ' + played + ' matches is an early sample (xG difference settles at about 9)' : '') + '. PPDA and possession describe the style (grey), not how good it is.</p>' : msg('No match sheets for this club yet.')) +
    (ctx.tidOf(team) ? '<a class="fb-rc-more" href="' + esc(FB.href.club(ctx.tidOf(team), { c: R.c.slug })) + '">Club page →</a>' : '') + '</div>';
  return '<details class="qk-card fb-rc-card" id="rc-card-' + esc(FB.enc(team)) + '">' + head + body + '</details>';
}

// ── the shape of the league ────────────────────────────────────────────────

function shapeCharts(el, R, ctx) {
  var teams = R.rows.map(function (r) { return r.team; }).filter(function (t) { var pr = (R.prof[t] || {}).profile || {}; return pr.xg_for && pr.xg_against && isNum(pr.xg_for.v) && isNum(pr.xg_against.v); });
  var qa = $(el, 'rc-quad-ad'), ql = $(el, 'rc-quad-luck');
  if (teams.length < 4) { [qa, ql].forEach(function (b) { if (b) { b.style.height = 'auto'; b.innerHTML = msg('Too few clubs with xG yet.'); } }); return; }
  var colour = function (t) { var id = ctx.tidOf(t); return id ? FB.clubColour(id) : null; };
  QKC.quadrant(qa, {
    points: teams.map(function (t) { var pr = R.prof[t].profile; return { x: pr.xg_for.v, y: pr.xg_against.v, name: t, label: FB.clubCode(t), color: colour(t), sub: 'xG difference ' + signed(pr.xg_for.v - pr.xg_against.v, 2) + ' a match' }; }),
    xName: 'xG for per match', yName: 'xG against per match (lower is better)', xFmt: function (v) { return num(v, 1); }, yFmt: function (v) { return num(v, 1); },
    corners: { tl: 'Struggling', tr: 'Open games', bl: 'Tight, blunt', br: 'Strong both ways' }, label: 'Attack against defence'
  });
  var lt = R.rows.filter(function (r) { var s = R.S[r.team]; return s && isNum(s.expected_points) && s.played > 0; });
  if (lt.length < 4) { ql.style.height = 'auto'; ql.innerHTML = msg('Too few clubs with expected points yet.'); return; }
  QKC.quadrant(ql, {
    points: lt.map(function (r) { var s = R.S[r.team]; return { x: s.expected_points / s.played, y: s.points / s.played, name: r.team, label: FB.clubCode(r.team), color: colour(r.team), sub: 'Points ' + s.points + ', expected ' + num(s.expected_points, 1) + ' (' + signed(s.points - s.expected_points, 1) + ')' }; }),
    xName: 'Expected points per match (from our xG)', yName: 'Points per match', xFmt: function (v) { return num(v, 1); }, yFmt: function (v) { return num(v, 1); },
    label: 'Points against expected points'
  });
}
function tiersHTML(R, ctx) {
  var up1 = R.up1, others = R.ups.slice(1);
  var tiers = [
    { key: 'title', name: tl(R, 'title_tier', 'Title contenders'), test: function (t) { return (chanceOf(R, t, 'title') || 0) >= 0.05; }, show: 'title' },
    { key: 'rel', name: 'Relegation scrap', test: function (t) { return R.downs.length && (R.rel(t) || 0) >= 0.1; }, show: 'rel' },
    { key: 'up1', name: up1 ? (up1.first === 1 ? 'Top-' + up1.last + ' race' : up1.label + ' race') : '', test: function (t) { return up1 && (chanceOf(R, t, up1.key) || 0) >= 0.1; }, show: up1 ? up1.key : null },
    { key: 'eu', name: 'Chasing ' + (others.length ? others.map(function (b) { return b.label; }).join(' / ') : 'Europe'), test: function (t) { return others.some(function (b) { return (chanceOf(R, t, b.key) || 0) >= 0.1; }); }, show: others.length ? others[0].key : null },
    { key: 'mid', name: 'Mid-table', test: function () { return true; }, show: null }
  ];
  var placed = {}, cols = tiers.map(function (x) { return { tier: x, teams: [] }; });
  R.rows.forEach(function (r) {
    for (var i = 0; i < tiers.length; i++) {
      if (!tiers[i].name) continue;
      if (tiers[i].test(r.team)) { cols[i].teams.push(r); placed[r.team] = 1; break; }
    }
  });
  var order = ['title', 'up1', 'eu', 'mid', 'rel'];
  return '<div class="fb-rc-tiers">' + order.map(function (k) {
    var col = cols.filter(function (x) { return x.tier.key === k; })[0];
    if (!col || !col.teams.length) return '';
    var key = col.tier.show;
    return '<div class="fb-rc-tier ' + k + '"><div class="qk-kicker">' + esc(col.tier.name) + ' <span class="fb-num">' + col.teams.length + '</span></div><ul>' + col.teams.map(function (r) {
      var p = key ? chanceOf(R, r.team, key) : null;
      return '<li>' + ctx.club(r.team) + (key ? '<b class="fb-num">' + pc(p) + '</b>' : '<span class="fb-num qk-muted">' + r.pts + ' pts</span>') + '</li>';
    }).join('') + '</ul></div>';
  }).join('') + '</div><p class="fb-cap">Tiers from our chances: ' + esc(tl(R, 'title_tier', 'title contenders').toLowerCase()) + ' at 5% or more; the ' + (up1 ? esc(up1.label) : 'top-band') + ' race and the chase for the other European places at 10% or more; the relegation scrap at 10% or more; the rest mid-table. The number is the chance that puts each club there.</p>';
}

// ── the tab ────────────────────────────────────────────────────────────────

function render(el, body, c, d, ctx) {
  var R = model(c, d);
  if (!R.rows.length) { body.innerHTML = FB.empty('No table yet', 'The race appears once the season has a table.'); return; }
  var m = R.m;
  var keys = [['title', tl(R, 'title_short', 'Title')]].concat(R.up1 ? [[R.up1.key, metricShort(R, R.up1.key)]] : []).concat(R.downs.length ? [['rel', 'Relegation']] : []);
  var fav = R.rows.map(function (r) { return { t: r.team, p: chanceOf(R, r.team, 'title') || 0 }; }).sort(function (a, b) { return b.p - a.p; })[0];
  var cut = R.up1 ? R.rows.map(function (r) { return { t: r.team, p: chanceOf(R, r.team, R.up1.key) || 0 }; }).sort(function (a, b) { return b.p - a.p; })[R.up1.last - 1] : null;
  var drop = R.downs.length ? R.rows.map(function (r) { return { t: r.team, p: R.rel(r.team) || 0, pos: r.pos || 0 }; }).sort(function (a, b) { return b.p - a.p || b.pos - a.pos; }) : [];
  var safeLine = drop.length ? drop[Math.min(drop.length - 1, R.t.down_places || R.downs.reduce(function (s, b) { return s + b.last - b.first + 1; }, 0))] : null;
  var left = R.t.total_games && isNum(R.t.games_played) ? R.t.total_games - R.t.games_played : null;
  var kp = [
    FB.kpi(tl(R, 'title_kpi', 'Title favourite'), fav && fav.p ? ctx.club(fav.t) : '—', { text: true, signal: true, sub: fav && fav.p ? 'our chance <b>' + pc(fav.p) + '</b>' : '' }),
    cut ? FB.kpi('On the ' + esc(metricShort(R, R.up1.key).toLowerCase()) + ' line', ctx.club(cut.t), { text: true, sub: 'the ' + FB.ordinal(R.up1.last) + ' likeliest, at <b>' + pc(cut.p) + '</b>' }) : '',
    safeLine ? FB.kpi('First club above the drop', ctx.club(safeLine.t), { text: true, sub: 'by our chances; down in <b>' + pc(safeLine.p) + '</b> of seasons' }) : '',
    FB.kpi('Matches left', isNum(left) ? '<span class="fb-num">' + left + '</span>' : '—', { sub: R.N ? R.N + ' a club in all' : '' })
  ].filter(Boolean);
  body.innerHTML = FB.kpis(kp) +
    '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'The race', title: 'How the race is shaping up', sub: 'Our chances day by day, who moved this week and why, and what the arithmetic has already settled.' }) +
      FB.grid(
        FB.card('Chances over time', 'Our chance of each outcome from the simulated seasons, one point a day. The six clubs most in play.', FB.seg('rc-key', keys, 'title', 'Race') + FB.chartBox('rc-hist', 320, 'Our chances over time'), { span: 7, foot: '<span id="rc-since"></span><a href="' + esc(FB.href.comp(c.slug, 'odds', { view: 'history' })) + '">Every model run →</a>' }) +
        FB.card('Who moved this week', 'The biggest changes in our chances, with the results behind them.', '<div id="rc-movers"></div>', { span: 5 })
      ) +
      '<div class="fb-mt">' + FB.card('What is settled', 'Points still available against points needed: the magic numbers. Certain means whatever every other result is.', settledHTML(R, ctx)) + '</div>' +
    '</section>' +
    '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'Next up', title: 'What\'s at stake next', sub: 'The coming fixtures that move the races most: our chances for the clubs involved after a home win, a draw and an away win, from the same simulated seasons split by that result.' }) +
      '<div id="rc-stakes"></div>' +
      '<div class="fb-mt">' + FB.card('The run-in', 'Each club\'s next five opponents coloured by our chance of a win, and how hard the rest of the season is from our ratings.', '<div id="rc-runin"></div>', { flush: true }) + '</div>' +
    '</section>' +
    '<section class="qk-section fb-co-sec" id="rc-cards-sec">' + QK.sectionHead({ kicker: 'Team cards', title: 'Strengths and weak spots', sub: 'Each club against the rest of the league on the measures that predict results best (xG difference, field tilt, shots on target), with set pieces, style and luck beside them. Open a card for the percentiles.' }) +
      '<div class="fb-rc-cards">' + R.rows.map(function (r) { return cardHTML(R, ctx, r); }).join('') + '</div>' +
    '</section>' +
    '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'Who\'s for real?', title: 'The shape of the league', sub: 'Attack against defence, points against the points our xG expected, and the tiers our chances draw.' }) +
      FB.grid(
        FB.card('Attack v defence', 'xG created and conceded per match. Dashed lines are the league averages.', FB.chartBox('rc-quad-ad', 380, 'Attack against defence'), { span: 6 }) +
        FB.card('Points v expected points', 'Above the average for points but not for expected points: winning on luck?', FB.chartBox('rc-quad-luck', 380, 'Points against expected points'), { span: 6 })
      ) +
      '<div class="fb-mt">' + FB.card('The tiers', 'Where each club\'s season is heading, from our chances.', tiersHTML(R, ctx)) + '</div>' +
    '</section>';
  var cur = 'title';
  function drawRace() {
    var h = raceChart($(el, 'rc-hist'), R, cur);
    $(el, 'rc-since').innerHTML = h ? (h.daily ? 'Tracking since ' + esc(FB.fmtDate(h.since)) + ' · one point a day' : 'Hourly model runs since ' + esc(FB.fmtStamp(h.since)) + '; the daily line starts as days are logged') : '';
    $(el, 'rc-movers').innerHTML = moversHTML(R, ctx, cur, d);
  }
  FB.wireSeg(el, 'rc-key', function (v) { cur = v || 'title'; drawRace(); });
  drawRace();
  var st = stakesHTML(R, ctx);
  $(el, 'rc-stakes').innerHTML = st || FB.card('The fixtures to watch', null, stakesGuide(R, ctx));
  runIn($(el, 'rc-runin'), R, ctx);
  shapeCharts(el, R, ctx);
  var q = (location.hash.split('?')[1] || '');
  var mm = /(?:^|&)club=([^&]+)/.exec(q);
  if (mm) { var card = document.getElementById('rc-card-' + mm[1]); if (card) { card.open = true; card.scrollIntoView({ block: 'start' }); } }
  if (c.kind === 'liga') ligaSections(el, body, c, R, ctx);
}

// ── Argentina: the zone races and the promedio race ─────────────────────────

/* After the Tabla Anual race: each zone's race for the eight playoff places (the points arithmetic over the zone
   phase, our chance of the top eight and of winning the zone, from zones.json) and the promedio race (the worst
   three-season averages, their projection and our chance of going down by each route, from relegation.json). */
function ligaSections(el, body, c, R, ctx) {
  var host = document.createElement('div');
  body.insertBefore(host, document.getElementById('rc-cards-sec'));
  FB.compFiles(c.slug, ['zones', 'relegation']).then(function (d) {
    if (!FB.alive(el)) return;
    var z = d.zones || {}, rel = d.relegation || {};
    var keys = Object.keys(z.zones || {});
    var cut = z.qualifiers_per_zone || 8;
    var torneo = z.tournament === 'apertura' ? 'Apertura' : 'Clausura';
    var html = '';
    if (keys.length) {
      html += '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'The ' + torneo, title: 'The zone races', sub: 'The top ' + cut + ' of each zone reach the ' + torneo + ' playoffs. Our chances of a place and of winning the zone, and what the arithmetic has settled.' }) +
        FB.grid(keys.map(function (k, i) {
          return FB.card('Zona ' + esc(k), zoneLine(z.zones[k], cut), '<div id="rc-zone-' + i + '"></div>', { span: 6, flush: true });
        }).join('')) + '</section>';
    }
    var rows = (rel.rows || []).slice().sort(function (a, b) { return a.promedio_now - b.promedio_now; });
    if (rows.length) {
      html += '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'Relegation', title: 'The promedio race', sub: 'The club with the worst three-season points per match goes down, beside the last club in the Tabla Anual (when they are the same club, the next-worst promedio goes too).' }) +
        FB.card('The bottom of the promedios', esc(((rel.prior || {}).note) || ''), '<div id="rc-prom"></div>', { flush: true }) + '</section>';
    }
    host.innerHTML = html;
    keys.forEach(function (k, i) {
      var zz = z.zones[k], A = arith({ rows: zz.standings || [], N: z.matches_per_team || 16 });
      var st = {};
      (A || []).forEach(function (x) { var t = x.topK(cut); st[x.team] = t.sure ? 'In' : t.out ? 'Out' : (t.need <= 3 * x.left ? t.need + ' of ' + (3 * x.left) : '—'); });
      FB.table($(el, 'rc-zone-' + i), [
        { key: 'pos', label: '#', num: true },
        { key: 'team', label: 'Club', sticky: true, fmt: function (v) { return ctx.club(v); } },
        { key: 'played', label: 'P', num: true }, { key: 'pts', label: 'Pts', num: true, fmt: function (v) { return '<b>' + v + '</b>'; } },
        { key: 'p_top8', label: 'Top ' + cut, num: true, fmt: function (v) { return pc(v); } },
        { key: 'p_zone_win', label: 'Zone', num: true, tip: 'Our chance of winning the zone', fmt: function (v) { return pc(v); } },
        { key: 'team', label: 'Settled', sort: false, tip: 'In: a top-' + cut + ' place is certain. Out: it can no longer be reached. Otherwise the points that would make it certain whatever the rest do, of the points still to play for', fmt: function (v) { return '<span class="fb-num">' + esc(st[v] || '—') + '</span>'; } }
      ], zz.standings || [], { caption: 'Zona ' + k, sort: { key: 'pos', dir: 'asc' } });
    });
    if (rows.length) {
      var worst = rows.slice(0, 8);
      FB.table($(el, 'rc-prom'), [
        { key: 'pos', label: '#', num: true },
        { key: 'team', label: 'Club', sticky: true, fmt: function (v) { return ctx.club(v); } },
        { key: 'promedio_now', label: 'Promedio', num: true, tip: 'Points per match over the promedio seasons, this season so far included', fmt: function (v) { return num(v, 3); } },
        { key: 'matches', label: 'Matches', num: true },
        { key: 'p50', label: 'Projected', num: true, tip: 'The median final promedio in our simulated seasons (5th to 95th percentile on hover)', fmt: function (v, x) { return '<span title="' + esc(num(x.p05, 3) + ' to ' + num(x.p95, 3)) + '">' + num(v, 3) + '</span>'; } },
        { key: 'p_promedio', label: 'Down via promedio', num: true, fmt: function (v) { return pc(v); } },
        { key: 'p_anual', label: 'Down via Tabla Anual', num: true, fmt: function (v) { return pc(v); } },
        { key: 'p_any', label: 'Down', num: true, fmt: function (v) { return '<b>' + pc(v) + '</b>'; } }
      ], worst, { caption: 'The promedio race', sort: { key: 'pos', dir: 'asc' } });
    }
  });
}
function zoneLine(zz, cut) {
  return (zz.games_played || 0) + ' of ' + (zz.total_games || 0) + ' zone matches played; the top ' + cut + ' go through.';
}

FB.race = { eligible: eligible, render: render, model: model, chipsFor: chipsFor, chipHTML: chipHTML, topChips: topChips };
})(window.FB);
