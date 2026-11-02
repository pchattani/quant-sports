/* The Quant — league module (QKL), kit v4 "Broadcast", dark only. Load after quant.js and quant-charts.js.
 *
 * Draws the season payload's `league` block (oddsmarkets/common/league.py, schema v1) on the US sport sites' standings
 * and team pages: how the race is shaping up, each team's strengths and weaknesses, the shape of the league.
 *
 *   QKL.race(el, o)          "How the race is shaping up": chances over time (538 style, from the race log), the
 *                            movers with their reasons, the race team by team (chance, week's move, magic /
 *                            elimination number, schedule left, the next game's swing) and the games that matter most
 *   QKL.shape(el, o)         "The shape of the league": offence v defence, record v the underlying numbers, the tiers
 *   QKL.toggle(key)          the + button for a compact standings row; QKL.wire(container, o) opens the team card
 *                            under the row (delegated, so a table re-sort keeps working)
 *   QKL.chip(o, key)         the team's first chip (for a compact "Profile" column)
 *   QKL.card(o, key, opts)   the team card: chips, percentile meters on the sport's team set, the race facts
 *   QKL.team(el, o, key)     the team page section: the card and the team's own chances over time
 *   QKL.performers(el, o)    a team page's top performers against the league
 *   QKL.leaders(el, o)       a league page's top and bottom performers: by key metric and by position, teams too
 *                            (QKL.board builds one metric's boards from rows in the page)
 *
 * o = { league: season.json.league, teams: { key: { abbr, name, colour, href } }, groups: [{ key, label, teams: [keys] }]
 *       (the race chart's switch: divisions or conferences), logUrl (the race log, data/.../race_log.json) or loadLog
 *       (a function returning a promise of it: the site's own cached loader), season
 *       (its key in the log), title (the section title), metric (the race chart's first metric; default the block's
 *       notes.metric), unitGames ('games'), meters (false: a team page with its own percentile card) }
 * Copy: neutral, no betting words; our chances only (the market sits on game pages and the Model page). Every chart
 * axis is titled. ES5 only (no ?. or ??). */
(function (root) {
'use strict';

var QK = root.QK, QKC = root.QKC;
if (!QK) return;
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt;
var QKL = {};
var LOGS = {};

/* ─────────────────────────────────────── styles (once) */
var CSS = [
  '.qkl-sec{margin-top:var(--sp-7,40px)}',
  '.qkl-ctl{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}',
  '.qkl-ctl .qk-seg{flex-wrap:wrap}',
  '.qkl-note{font:500 var(--fs-xs)/1.45 var(--font-ui);color:var(--ink-3);padding:0 20px 16px}',
  '.qkl-note b{color:var(--ink-2)}',
  '.qkl-mv{list-style:none;margin:0;padding:0 20px 16px}',
  '.qkl-mv li{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 10px;align-items:center;padding:10px 0;border-top:1px solid var(--line-1,#232833)}',
  '.qkl-mv li:first-child{border-top:0}',
  '.qkl-mv .nm{font:700 var(--fs-sm)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.03em;color:var(--ink-1);min-width:0}',
  '.qkl-mv .nm a{color:inherit;text-decoration:none}',
  '.qkl-mv .why{grid-column:2 / 4;font:500 var(--fs-xs)/1.4 var(--font-ui);color:var(--ink-3)}',
  '.qkl-mv .d{font:400 1.35rem/1 var(--font-display);white-space:nowrap}',
  '.qkl-mv .d small{font:600 var(--fs-2xs)/1 var(--font-cond);color:var(--ink-3);margin-left:4px;text-transform:uppercase}',
  '.qkl-mv-h{font:700 var(--fs-2xs)/1 var(--font-cond);text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);padding:14px 20px 4px}',
  '.qkl-up{color:var(--up)}.qkl-down{color:var(--down)}',
  '.qkl-gm{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:var(--sp-3,12px);padding:4px 20px 18px}',
  '.qkl-g{background:var(--s-2);padding:12px 14px;min-width:0;border-left:4px solid var(--signal)}',
  '.qkl-g .top{display:flex;justify-content:space-between;gap:8px;font:700 var(--fs-2xs)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3)}',
  '.qkl-g .mu{font:400 1.5rem/1.05 var(--font-display);color:var(--ink-1);margin:6px 0 8px;letter-spacing:.01em}',
  '.qkl-g .mu a{color:inherit;text-decoration:none}',
  '.qkl-sw{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:6px 8px;align-items:center;margin-top:6px;font:600 var(--fs-xs)/1.2 var(--font-cond);color:var(--ink-2)}',
  '.qkl-sw .ab{font-weight:700;color:var(--ink-1);text-transform:uppercase}',
  '.qkl-sw .tr{position:relative;height:10px;background:var(--s-3)}',
  '.qkl-sw .tr b{position:absolute;top:0;bottom:0;background:var(--signal)}',
  '.qkl-sw .tr i{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink-1)}',
  '.qkl-sw .v{white-space:nowrap;color:var(--ink-3)}',
  '.qkl-g .why{font:500 var(--fs-xs)/1.4 var(--font-ui);color:var(--ink-3);margin-top:8px}',
  '.qkl-chips{display:flex;flex-wrap:wrap;gap:6px}',
  '.qkl-c{display:inline-flex;align-items:center;height:22px;padding:0 8px;font:700 var(--fs-2xs)/1 var(--font-cond);text-transform:uppercase;letter-spacing:.05em;white-space:nowrap;background:var(--s-3);color:var(--ink-2);border-left:3px solid var(--ink-3)}',
  '.qkl-c.p{border-left-color:var(--up);color:var(--ink-1)}',
  '.qkl-c.m{border-left-color:var(--down);color:var(--ink-1)}',
  '.qkl-c.q{border-left-color:var(--volt);color:var(--ink-1)}',
  '.qkl-x{appearance:none;border:0;background:var(--s-3);color:var(--ink-1);width:22px;height:22px;margin-right:8px;font:700 15px/22px var(--font-cond);cursor:pointer;flex:none;padding:0;vertical-align:middle}',
  '.qkl-x:hover,.qkl-x:focus-visible{background:var(--signal);color:#fff}',
  '.qkl-x[aria-expanded="true"]{background:var(--volt);color:var(--volt-ink,#000)}',
  'tr.qkl-row>td{padding:0!important;background:var(--bg,#0a0c10);white-space:normal}',
  '.qkl-card{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:12px 28px;padding:16px 18px 18px;border-left:4px solid var(--tc,var(--signal));text-align:left;max-width:min(1180px,calc(100vw - 32px));position:sticky;left:0}',
  '.qkl-card h4{margin:0 0 8px;font:400 1.5rem/1 var(--font-display);text-transform:uppercase;color:var(--ink-1);letter-spacing:.01em}',
  '.qkl-card h4 a{color:inherit;text-decoration:none}',
  '.qkl-card .tier{margin-left:8px;vertical-align:middle}',
  '.qkl-card .qk-pbars{margin-top:10px}',
  '.qkl-facts{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 12px;font:500 var(--fs-sm)/1.35 var(--font-ui);color:var(--ink-2);margin:0}',
  '.qkl-facts dt{color:var(--ink-3);font:600 var(--fs-xs)/1.35 var(--font-cond);text-transform:uppercase;letter-spacing:.05em}',
  '.qkl-facts dd{margin:0;text-align:right;color:var(--ink-1);font-weight:600}',
  '.qkl-facts dd small{display:block;color:var(--ink-3);font-weight:500;font-size:var(--fs-2xs)}',
  '.qkl-pgh{font:700 var(--fs-2xs)/1 var(--font-cond);text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);margin:14px 0 2px}',
  '.qkl-tiers{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:var(--sp-3,12px);padding:4px 20px 18px}',
  '.qkl-tier{background:var(--s-2);padding:12px 14px;min-width:0}',
  '.qkl-tier h5{margin:0;font:400 1.35rem/1 var(--font-display);text-transform:uppercase;color:var(--ink-1)}',
  '.qkl-tier p{margin:4px 0 10px;font:500 var(--fs-2xs)/1.35 var(--font-ui);color:var(--ink-3)}',
  '.qkl-tier .ts{display:flex;flex-wrap:wrap;gap:6px}',
  '.qkl-tier .ts a{text-decoration:none}',
  '.qkl-tbl td.qkl-pct{white-space:nowrap}',
  '.qkl-tbl .mv{font-size:var(--fs-xs);margin-left:6px}',
  '.qkl-tp{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:var(--sp-3,12px);padding:4px 20px 18px}',
  '.qkl-tpg{background:var(--s-2);padding:12px 14px;min-width:0}',
  '.qkl-tpg h5{margin:0 0 6px;font:700 var(--fs-2xs)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3)}',
  '.qkl-pr{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;align-items:center;padding:9px 0;border-top:1px solid var(--line-1,#232833)}',
  '.qkl-pr:first-of-type{border-top:0}',
  '.qkl-pr .who{min-width:0;font:700 var(--fs-sm)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.02em;color:var(--ink-1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
  '.qkl-pr .who a{color:inherit;text-decoration:none}',
  '.qkl-pr .who small{font:600 var(--fs-2xs)/1 var(--font-cond);color:var(--ink-3);margin-left:6px}',
  '.qkl-pr .v{font:400 1.25rem/1 var(--font-display);color:var(--ink-1);text-align:right;white-space:nowrap}',
  '.qkl-pr .m{grid-column:1 / 3;display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center}',
  '.qkl-pr .rk{font:600 var(--fs-2xs)/1.2 var(--font-cond);color:var(--ink-3);text-transform:uppercase;white-space:nowrap}',
  '.qkl-top1{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:var(--sp-3,12px);padding:4px 20px 6px}',
  '.qkl-top1 .qkl-pr{background:var(--s-2);padding:12px 14px;border-top:0;border-left:4px solid var(--signal)}',
  '.qkl-pr .m{grid-template-columns:minmax(80px,1fr) auto auto}',
  '.qkl-pr .m .qk-segs{min-width:80px;width:100%}',
  '.qkl-top1 .qkl-pr .rk{white-space:normal;max-width:110px;line-height:1.15}',
  '.qkl-ld-ctl{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:0 0 var(--sp-4,16px)}',
  '.qkl-ld-ctl .qk-seg{flex-wrap:wrap;overflow:visible}',
  '.qkl-lt{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:2px;margin:0 0 var(--sp-4,16px)}',
  '.qkl-lt-b{all:unset;box-sizing:border-box;cursor:pointer;display:flex;flex-direction:column;gap:4px;min-width:0;padding:12px 14px 12px;background:var(--s-2);border-top:3px solid transparent}',
  '.qkl-lt-b:hover{background:var(--s-3)}',
  '.qkl-lt-b:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}',
  '.qkl-lt-b[aria-pressed="true"]{border-top-color:var(--volt);background:var(--s-3)}',
  '.qkl-lt-b .k{font:700 var(--fs-2xs)/1.25 var(--font-cond);text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3)}',
  '.qkl-lt-b[aria-pressed="true"] .k{color:var(--ink-1)}',
  '.qkl-lt-b .w{font:700 var(--fs-sm)/1.15 var(--font-cond);text-transform:uppercase;letter-spacing:.02em;color:var(--ink-1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:auto}',
  '.qkl-lt-b .v{font:400 1.6rem/1 var(--font-display);color:var(--ink-1);font-variant-numeric:tabular-nums}',
  '.qkl-lt-b .v small{font:600 var(--fs-2xs)/1 var(--font-cond);color:var(--ink-3);margin-left:6px;text-transform:uppercase;letter-spacing:.04em}',
  '.qkl-ld{list-style:none;margin:0;padding:4px 20px 14px}',
  '.qkl-ld li{display:grid;grid-template-columns:30px auto minmax(0,1fr) auto;gap:4px 10px;align-items:center;padding:10px 0;border-top:1px solid var(--line-1,#232833)}',
  '.qkl-ld li:first-child{border-top:0}',
  '.qkl-ld .rk{font:400 1.5rem/1 var(--font-display);color:var(--ink-3);text-align:right;font-variant-numeric:tabular-nums}',
  '.qkl-ld .who{min-width:0;font:700 var(--fs-sm)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.02em;color:var(--ink-1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
  '.qkl-ld .who a{color:inherit;text-decoration:none}',
  '.qkl-ld .who a:hover{color:var(--volt)}',
  '.qkl-ld .who small{font:600 var(--fs-2xs)/1 var(--font-cond);color:var(--ink-3);margin-left:6px}',
  '.qkl-ld .v{font:400 1.4rem/1 var(--font-display);color:var(--ink-1);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}',
  '.qkl-ld .m{grid-column:2 / 5;display:grid;grid-template-columns:minmax(80px,1fr) 40px;gap:8px;align-items:center}',
  '.qkl-ld .m .qk-segs{min-width:80px;width:100%;height:16px}',
  '.qkl-ld .m .qk-pbox{font-size:20px;padding:3px 0 1px;text-align:center}',
  '.qkl-ld-h{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}',
  '.qkl-ld-h .qk-tag{vertical-align:middle}',
  '.qkl-dn .qk-card-title{color:var(--ink-2)}',
  '@media (max-width:760px){.qkl-lt{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none}.qkl-lt::-webkit-scrollbar{display:none}.qkl-lt-b{flex:0 0 62%;scroll-snap-align:start}.qkl-ld{padding:4px 14px 12px}}',
  '@media (max-width:760px){.qkl-card{grid-template-columns:minmax(0,1fr);padding:14px 12px 16px;max-width:calc(100vw - 32px)}.qkl-mv{padding:0 14px 12px}.qkl-gm,.qkl-tiers{padding:4px 14px 14px}.qkl-note{padding:0 14px 14px}}'
].join('\n');
function css() {
  if (document.getElementById('qkl-css')) return;
  var s = document.createElement('style');
  s.id = 'qkl-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

/* ─────────────────────────────────────── helpers */
function tm(o, k) { return (o.teams || {})[k] || { abbr: k, name: k }; }
function ab(o, k) { var t = tm(o, k); return t.abbr || t.name || k; }
function nm(o, k) { var t = tm(o, k); return t.name || t.abbr || k; }
function href(o, k) { var t = tm(o, k); return t.href || ''; }
function link(o, k, txt) { var h = href(o, k); return h ? '<a href="' + esc(h) + '">' + esc(txt) + '</a>' : esc(txt); }
function mark(o, k) { var t = tm(o, k); return { abbr: t.abbr || k, name: t.name, colour: t.colour }; }
function pct(p) { return fmt.pct(p, isNum(p) && p > 0.995 && p < 1 ? 1 : 0); }
function pts(d) { return isNum(d) ? (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(d * 100).toFixed(Math.abs(d) < 0.1 ? 1 : 0) : '—'; }
function metricOf(L, key) { var m = (L.metrics || []).filter(function (x) { return x.key === key; })[0]; return m || { key: key, label: key }; }
function card(title, sub, body, o) {
  o = o || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + (o.html ? sub : esc(sub)) + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body"' + (o.flush ? ' style="padding:0"' : '') + '>' + body + '</div></section>';
}
function seg(id, items, on, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label) + '">' + items.map(function (x) {
    return '<button type="button" data-value="' + esc(x[0]) + '" aria-pressed="' + (x[0] === on) + '">' + esc(x[1]) + '</button>';
  }).join('') + '</div>';
}
function dayLabel(d) { return d ? fmt.date(d + 'T12:00:00Z', { day: 'numeric', month: 'short' }) : ''; }
function fmtVal(v, f) {
  if (!isNum(v)) return '—';
  if (f === 'pct1') return (v * 100).toFixed(1) + '%';
  if (f === 'pct0') return Math.round(v * 100) + '%';
  if (f && f.charAt(0) === '+') { var sd = Number(f.slice(1)) || 0; return fmt.signed(Math.abs(v) < 0.5 * Math.pow(10, -sd) ? 0 : v, sd); }
  if (f === '3') return v.toFixed(3).replace(/^0\./, '.').replace(/^-0\./, '−.');
  return isNum(Number(f)) ? v.toFixed(Number(f)) : String(v);
}
QKL.fmtVal = fmtVal;

/* the race log, fetched once per URL */
function loadLog(o) {
  if (o && o.loadLog) return Promise.resolve(o.loadLog()).then(function (d) { return d && d.ok !== false ? d : null; }, function () { return null; });
  var url = o && o.logUrl;
  if (!url) return Promise.resolve(null);
  if (!LOGS[url]) LOGS[url] = QK.fetchJSON(url).then(function (d) { return d; }, function () { return null; });
  return LOGS[url];
}
QKL.loadLog = loadLog;
/* {dates: [...], series: {team: [p...]}, rebuilt: {day: true}} for one metric of one season */
function logSeries(log, season, metric) {
  var s = log && log[String(season)];
  var m = s && s[metric];
  if (!m) return null;
  var dates = Object.keys(m).filter(function (d) { return /^\d{4}-\d\d-\d\d$/.test(d); }).sort();
  var teams = {};
  dates.forEach(function (d, i) { Object.keys(m[d] || {}).forEach(function (k) { (teams[k] = teams[k] || [])[i] = m[d][k]; }); });
  Object.keys(teams).forEach(function (k) { for (var i = 0; i < dates.length; i++) if (!isNum(teams[k][i])) teams[k][i] = null; });
  var reb = {};
  ((s._meta || {}).rebuilt || []).forEach(function (d) { reb[d] = true; });
  return { dates: dates, series: teams, rebuilt: reb };
}
QKL.logSeries = logSeries;

/* ─────────────────────────────────────── chips */
function chipHTML(c) {
  var tone = c[1] === '+' ? ' p' : c[1] === '-' ? ' m' : c[1] === '?' ? ' q' : '';
  return '<span class="qkl-c' + tone + '">' + esc(c[0]) + '</span>';
}
QKL.chips = function (o, key, max) {
  var t = ((o.league || {}).teams || {})[key] || {};
  var cs = (t.chips || []).slice(0, max || 8);
  return cs.length ? '<span class="qkl-chips">' + cs.map(chipHTML).join('') + '</span>' : '';
};
QKL.chip = function (o, key) { return QKL.chips(o, key, 1); };

/* ─────────────────────────────────────── the team card */
var TIER_TAG = { contend: 'volt', alive: 'volt', champion: 'volt', solid: 'signal' };
function tierTag(L, key) {
  var t = ((L.teams || {})[key] || {}).tier;
  if (!t) return '';
  var row = (L.tiers || []).filter(function (x) { return x.key === t; })[0];
  return row ? QK.tag(row.label, 'tier' + (TIER_TAG[t] ? ' ' + TIER_TAG[t] : '')) : '';
}
function raceFacts(o, key) {
  var L = o.league || {}, r = (L.race || {})[key] || {}, t = (L.teams || {})[key] || {}, notes = L.notes || {};
  var m0 = (L.metrics || [])[0] || {}, metric = notes.metric || m0.key, ml = metricOf(L, metric).label;
  var rows = [];
  var cur = (L.current || {})[metric];
  if (r.status === 'clinched') rows.push(['Status', 'Clinched a place']);
  else if (r.status === 'out') rows.push(['Status', 'Eliminated']);
  else if (r.all_sims === 'in') rows.push(['Status', 'In every simulation', 'not yet clinched']);
  else if (r.all_sims === 'out') rows.push(['Status', 'Out in every simulation', 'not yet eliminated']);
  if (isNum(r.magic)) rows.push(['Magic number', String(r.magic), (r.unit || 'wins') + ' from its own results or the chasers’ to clinch']);
  if (isNum(r.elim)) rows.push(['Elimination number', String(r.elim), (r.unit || 'wins') + ' for the cut line, or lost by this team, to end it']);
  if (r.sos) rows.push(['Schedule left', (isNum(r.sos[1]) ? QK.ordinal(r.sos[1]) + ' hardest' : '—'), r.sos[2] + ' games · opponents ' + fmt.signed(r.sos[0], 2) + (notes.sos_unit ? ' (' + notes.sos_unit.split(':')[0] + ')' : '')]);
  if (r.sos_played) rows.push(['Schedule so far', (isNum(r.sos_played[1]) ? QK.ordinal(r.sos_played[1]) + ' hardest' : '—'), r.sos_played[2] + ' games']);
  if (r.next && r.next.opp) {
    var nx = r.next, opp = ab(o, nx.opp);
    var sw = isNum(nx.w) && isNum(nx.l) ? ml + ': ' + pct(nx.w) + ' with a win, ' + pct(nx.l) + ' with a loss' : '';
    rows.push(['Next game', (nx.home ? 'v ' : '@ ') + opp + (isNum(nx.p) ? ' · ' + pct(nx.p) : ''), sw || (nx.date ? dayLabel(nx.date) : '')]);
  }
  var lk = t.luck;
  if (lk) {
    var u = notes.luck_unit || 'wins';
    rows.push(['Record v the numbers', (lk.d > 0 ? '+' : lk.d < 0 ? '−' : '±') + Math.abs(lk.d).toFixed(1) + ' ' + u, lk.a + ' ' + u + ' against ' + lk.x + ' expected' + (lk.close && lk.close[0] + lk.close[1] ? ' · close games ' + lk.close[0] + '-' + lk.close[1] : '')]);
  }
  return rows;
}
function meters(o, key, compact) {
  var L = o.league || {}, P = L.profile || {}, t = (L.teams || {})[key] || {};
  var pc = t.pct || {}, vals = t.vals || {};
  var groups = {}, order = [];
  (P.metrics || []).forEach(function (m) {
    if (!isNum(pc[m.id])) return;
    var g = m.group || '';
    if (!groups[g]) { groups[g] = []; order.push(g); }
    groups[g].push({ label: m.label, pctl: pc[m.id], value: fmtVal(vals[m.id], m.fmt) + (m.unit && !compact ? '' : ''), sub: m.unit || '', style: !!m.style, tip: m.label + (m.unit ? ' (' + m.unit + ')' : '') + (m.dir === 'lower' ? ': lower is better' : '') });
  });
  if (!order.length) return '<p class="qk-muted" style="margin:10px 0 0">' + (P.early ? 'Percentiles start after ' + (P.min_gp || 10) + ' ' + (o.unitGames || 'games') + ': before then the ranks are mostly noise.' : 'No team numbers in this build.') + '</p>';
  return order.map(function (g) { return (g ? '<div class="qkl-pgh">' + esc(g) + '</div>' : '') + QK.pctlBars(groups[g]); }).join('') +
    (P.early ? '<p class="qk-muted" style="margin:8px 0 0;font-size:var(--fs-2xs)">Early: under ' + (P.min_gp || 10) + ' ' + (o.unitGames || 'games') + ' each, so only our rating (which carries last season) is ranked.</p>' : '');
}
/* the plain-English read of the record against the numbers, for a card without meters (a team page that draws its
   own percentile card) */
/* a label mid-sentence: the first letter lower-cased, except a name (Elo) */
var KEEP_CASE = /^(Elo|Sofascore|Glicko|Gridiron|Rink|Hardwood|Bullpen|Campus|Paddock|Ace|Footballer)\b/;
function lc(x) { x = String(x || ''); return /^[A-Z][a-z]/.test(x) && !KEEP_CASE.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function luckLine(o, key) {
  var L = o.league || {}, t = (L.teams || {})[key] || {}, lk = t.luck, notes = L.notes || {}, u = notes.luck_unit || 'wins';
  var P = L.profile || {}, pc = t.pct || {}, best = null, worst = null;
  (P.metrics || []).forEach(function (m) {
    if (!isNum(pc[m.id]) || m.style || m.model || !m.chip) return;
    if (!best || pc[m.id] > pc[best.id]) best = m;
    if (!worst || pc[m.id] < pc[worst.id]) worst = m;
  });
  var out = [];
  if (best && worst && best !== worst) out.push('Best at <b>' + esc(lc(best.label)) + '</b> (' + QK.ordinal(pc[best.id]) + ' percentile); weakest at <b>' + esc(lc(worst.label)) + '</b> (' + QK.ordinal(pc[worst.id]) + ').');
  if (lk) out.push('Record: <b>' + lk.a + ' ' + esc(u) + '</b> against <b>' + lk.x + '</b> expected from its numbers (' + (lk.d >= 0 ? '+' : '−') + Math.abs(lk.d).toFixed(1) + ')' + (lk.close && lk.close[0] + lk.close[1] ? '; ' + lk.close[0] + '-' + lk.close[1] + ' in close games' : '') + '.');
  return out.length ? '<p style="margin:12px 0 0;font:500 var(--fs-sm)/1.5 var(--font-ui);color:var(--ink-2)">' + out.join(' ') + '</p>' : '';
}
QKL.card = function (o, key, opts) {
  css();
  opts = opts || {};
  var L = o.league || {}, t = tm(o, key), lt = (L.teams || {})[key] || {};
  var facts = raceFacts(o, key);
  var tc = t.colour && QK.color.parse(t.colour) ? QK.color.team(t.colour) : '';
  return '<div class="qkl-card"' + (tc ? ' style="--tc:' + esc(tc) + '"' : '') + '><div style="min-width:0">' +
    (opts.head === false ? '' : '<h4>' + link(o, key, nm(o, key)) + tierTag(L, key) + '</h4>') +
    (QKL.chips(o, key) || '<span class="qk-muted" style="font-size:var(--fs-xs)">No standout strength or weakness yet.</span>') +
    (opts.meters === false ? luckLine(o, key) : meters(o, key)) + '</div><div style="min-width:0"><div class="qkl-pgh" style="margin:4px 0 12px">The race</div>' +
    (facts.length ? '<dl class="qkl-facts">' + facts.map(function (f) { return '<dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + (f[2] ? '<small>' + esc(f[2]) + '</small>' : '') + '</dd>'; }).join('') + '</dl>' : '<p class="qk-muted">Nothing to show yet.</p>') +
    (opts.link !== false && href(o, key) ? '<p style="margin:14px 0 0"><a class="qk-btn" href="' + esc(href(o, key)) + '">' + esc(ab(o, key)) + ' team page</a></p>' : '') +
    (lt.gp !== undefined ? '' : '') + '</div></div>';
};

/* ─────────────────────────────────────── expandable rows */
QKL.toggle = function (key, label) {
  return '<button type="button" class="qkl-x" data-qkl="' + esc(key) + '" aria-expanded="false" aria-label="' + esc('Strengths, weaknesses and the race: ' + (label || key)) + '" title="Open the team card">+</button>';
};
QKL.wire = function (container, o) {
  css();
  if (!container || container._qkl) { if (container) container._qklO = o; return; }
  container._qkl = true;
  container._qklO = o;
  container.addEventListener('click', function (ev) {
    var b = ev.target.closest ? ev.target.closest('.qkl-x') : null;
    if (!b || !container.contains(b)) return;
    ev.preventDefault();
    ev.stopPropagation();
    var tr = b.closest('tr');
    if (!tr) return;
    var open = b.getAttribute('aria-expanded') === 'true';
    var nx = tr.nextElementSibling;
    if (open) {
      if (nx && nx.classList.contains('qkl-row')) nx.parentNode.removeChild(nx);
      b.setAttribute('aria-expanded', 'false');
      b.textContent = '+';
      return;
    }
    var n = tr.children.length;
    var row = document.createElement('tr');
    row.className = 'qkl-row';
    row.innerHTML = '<td colspan="' + n + '">' + QKL.card(container._qklO, b.getAttribute('data-qkl')) + '</td>';
    tr.parentNode.insertBefore(row, tr.nextSibling);
    b.setAttribute('aria-expanded', 'true');
    b.textContent = '−';
  });
};

/* ─────────────────────────────────────── the race */
function moversHTML(o) {
  var L = o.league || {}, mv = L.movers;
  if (!mv || !((mv.up || []).length || (mv.down || []).length)) {
    var h = L.history || {};
    return '<p class="qkl-note" style="padding-top:12px">' + (h.days > 1 ? 'No chance moved two points or more this week.' : 'Movers appear once a week of chances is on record' + (h.first ? ' (tracking since ' + esc(dayLabel(h.first)) + ')' : '') + '.') + '</p>';
  }
  var ml = lc(metricOf(L, mv.metric).label);
  function li(r) {
    var up = r.d > 0;
    return '<li>' + QK.teamMark(mark(o, r.team), 'sm') + '<span class="nm">' + link(o, r.team, nm(o, r.team)) + '</span><span class="d ' + (up ? 'qkl-up' : 'qkl-down') + '">' + pts(r.d) + '<small>' + pct(r.p) + '</small></span>' +
      '<span class="why">' + esc((r.why || []).join(' · ')) + '</span></li>';
  }
  return '<div class="qkl-mv-h">Up · ' + esc(ml) + ' chance, points since ' + esc(dayLabel(mv.since)) + '</div><ul class="qkl-mv">' + (mv.up || []).map(li).join('') + '</ul>' +
    '<div class="qkl-mv-h">Down</div><ul class="qkl-mv">' + (mv.down || []).map(li).join('') + '</ul>';
}
function gamesHTML(o) {
  var L = o.league || {}, gs = L.games || [];
  if (!gs.length) return '<p class="qkl-note" style="padding-top:12px">No games in the next seven days.</p>';
  var ml = lc(metricOf(L, (L.notes || {}).metric || ((L.metrics || [])[0] || {}).key).label);
  return '<div class="qkl-gm">' + gs.map(function (g) {
    var when = g.start ? fmt.date(g.start) + (String(g.start).length > 10 ? ' · ' + fmt.time(g.start) : '') : '';
    var sides = Object.keys(g.sides || {});
    var sw = sides.map(function (k) {
      var x = g.sides[k], lo = Math.min(x[0], x[1]), hi = Math.max(x[0], x[1]);
      var nowP = ((L.current || {})[(L.notes || {}).metric] || {})[k];
      return '<div class="qkl-sw"><span class="ab">' + esc(ab(o, k)) + '</span><span class="tr" role="img" aria-label="' + esc(ab(o, k) + ': ' + pct(x[0]) + ' with a win, ' + pct(x[1]) + ' with a loss') + '"><b style="left:' + (100 * lo).toFixed(1) + '%;width:' + Math.max(1, 100 * (hi - lo)).toFixed(1) + '%"></b>' +
        (isNum(nowP) ? '<i style="left:' + (100 * nowP).toFixed(1) + '%"></i>' : '') + '</span><span class="v">' + pct(x[1]) + '–' + pct(x[0]) + '</span></div>';
    }).join('');
    var c = (tm(o, g.home).colour && QK.color.parse(tm(o, g.home).colour)) ? QK.color.team(tm(o, g.home).colour) : 'var(--signal)';
    return '<div class="qkl-g" style="border-left-color:' + esc(c) + '"><div class="top"><span>' + esc(when) + '</span><span>' + (isNum(g.swing) ? 'Swing ' + Math.round(100 * g.swing) + ' pts' : 'High stakes') + '</span></div>' +
      '<div class="mu">' + link(o, g.away, ab(o, g.away)) + ' @ ' + link(o, g.home, ab(o, g.home)) + '</div>' + sw +
      (sides.length ? '' : '<div class="why">' + esc((g.why || []).join(' · ') || 'A big game for both sides’ ' + ml + ' chances') + '</div>') + '</div>';
  }).join('') + '</div><p class="qkl-note">Each bar runs from the team’s ' + esc(ml) + ' chance after a loss to its chance after a win in that game (the white tick: today). The swing adds both sides’ gaps, from our season simulation. Only a team’s next game carries a measured swing; later games are ranked by what rides on them.</p>';
}
function raceTable(o, keys, metric, log) {
  var L = o.league || {}, cur = (L.current || {})[metric] || {}, R = L.race || {};
  var ser = log ? logSeries(log, o.season, metric) : null;
  var wk = {};
  if (ser && ser.dates.length > 1) {
    var last = ser.dates[ser.dates.length - 1], target = new Date(new Date(last + 'T12:00:00Z').getTime() - 7 * 864e5).toISOString().slice(0, 10);
    var j = 0;
    ser.dates.forEach(function (d, i) { if (d <= target) j = i; });
    if (ser.dates[j] < last) keys.forEach(function (k) { var a = (ser.series[k] || [])[j], b = cur[k]; if (isNum(a) && isNum(b)) wk[k] = b - a; });
  }
  var rows = keys.slice().sort(function (a, b) { return (cur[b] || 0) - (cur[a] || 0); });
  var head = '<thead><tr><th scope="col">Team</th><th scope="col" class="num">' + esc(metricOf(L, metric).label) + '</th><th scope="col" class="num"><span data-tip="Change in points over about a week">7 days</span></th>' +
    '<th scope="col" class="num"><span data-tip="Magic number (clinch) or E and the elimination number, when within reach">Magic</span></th><th scope="col" class="num"><span data-tip="Rank of the schedule left by our ratings of the opponents: 1st is the hardest">Schedule left</span></th><th scope="col"><span data-tip="Its next game: our chance after a win, then after a loss">Next game</span></th></tr></thead>';
  var body = rows.map(function (k) {
    var r = R[k] || {}, nx = r.next || {};
    var mg = r.status === 'clinched' ? 'Clinched' : r.status === 'out' ? 'Out' : isNum(r.magic) ? String(r.magic) : isNum(r.elim) ? 'E' + r.elim : r.all_sims === 'in' ? 'In all sims' : r.all_sims === 'out' ? 'Out all sims' : '—';
    var w = wk[k];
    return '<tr><td><span class="qk-entity">' + QK.teamMark(mark(o, k), 'sm') + '<span class="qk-entity-name">' + link(o, k, ab(o, k)) + '</span></span></td><td class="num qkl-pct"><b>' + pct(cur[k]) + '</b></td>' +
      '<td class="num">' + (isNum(w) ? '<span class="' + (w > 0.005 ? 'qkl-up' : w < -0.005 ? 'qkl-down' : '') + '">' + pts(w) + '</span>' : '—') + '</td><td class="num">' + esc(mg) + '</td>' +
      '<td class="num">' + (r.sos && isNum(r.sos[1]) ? QK.ordinal(r.sos[1]) : '—') + '</td><td>' + (nx.opp ? esc((nx.home ? 'v ' : '@ ') + ab(o, nx.opp)) + (isNum(nx.w) && isNum(nx.l) ? ' <span class="qk-muted">' + pct(nx.w) + ' / ' + pct(nx.l) + '</span>' : '') : '—') + '</td></tr>';
  }).join('');
  return '<div class="qk-table-wrap"><table class="qk-table dense qkl-tbl">' + head + '<tbody>' + body + '</tbody></table></div>';
}
function dayTick(v) { var d = new Date(v); return isNaN(d) ? '' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }); }
function drawChart(sel, o, log, keys, metric) {
  var L = o.league || {}, h = L.history || {};
  var el = typeof sel === 'string' ? document.querySelector(sel) : sel;
  if (!el) return;
  var ser = log ? logSeries(log, o.season, metric) : null;
  if (!ser || ser.dates.length < 2) {
    el.innerHTML = QK.empty('Tracking since ' + (h.first ? dayLabel(h.first) : 'today'), 'The chart draws once two days of chances are on record; it fills in every day from here.');
    return;
  }
  var cur = (L.current || {})[metric] || {};
  var ks = keys.filter(function (k) { return ser.series[k]; }).sort(function (a, b) { return (cur[b] || 0) - (cur[a] || 0); });
  var lf = h.live_from;
  var ann = [];
  if (lf && ser.dates[0] < lf) ann.push({ x: lf + 'T12:00:00Z', label: 'Live from ' + dayLabel(lf) });
  QKC.forecast(el, {
    x: ser.dates.map(function (d) { return d + 'T12:00:00Z'; }), xType: 'time',
    series: ks.map(function (k) { return { name: ab(o, k), label: ab(o, k), data: ser.series[k], color: tm(o, k).colour }; }),
    annotations: ann, yName: 'Our ' + lc(metricOf(L, metric).label) + ' chance', xName: 'Date', xFmt: dayTick,
    label: 'Our ' + lc(metricOf(L, metric).label) + ' chance over time'
  });
}
QKL.race = function (el, o) {
  css();
  if (typeof el === 'string') el = document.querySelector(el);
  var L = o.league;
  if (!el || !L) return;
  var groups = (o.groups || []).filter(function (g) { return (g.teams || []).length; });
  if (!groups.length) groups = [{ key: 'all', label: 'League', teams: Object.keys(L.race || L.teams || {}) }];
  var ms = (L.metrics || []).filter(function (m) { return Object.keys((L.current || {})[m.key] || {}).length; });
  if (!ms.length) ms = L.metrics || [];
  var M = o.metric || (L.notes || {}).metric || (ms[0] || {}).key, G = o.group || groups[0].key;
  var h = L.history || {};
  var reb = (h.rebuilt || []).length, live = h.live_from;
  var note = live && reb ? 'Tracking live since <b>' + esc(dayLabel(live)) + '</b>. Before that, ' + reb + ' snapshots rebuilt from our season simulation run as of each date (' + esc(String(h.n || 2000)) + ' simulations each), using only the results known then.' :
    live ? 'Tracking since <b>' + esc(dayLabel(live)) + '</b>: one snapshot of our chances a day.' : 'Rebuilt from our season simulation as of each date, using only the results known then.';
  var id = 'qkl' + Math.floor(Math.random() * 1e6);
  el.innerHTML = '<section class="qk-section qkl-sec">' + QK.sectionHead({ kicker: 'The race', title: o.title || 'How the race is shaping up', html: true,
      sub: 'Our chances over the season, who moved this week and why, where each team stands against the cut, and the games that swing it.' }) +
    '<div class="qkl-ctl" style="margin:0 0 var(--sp-4,16px)">' + (ms.length > 1 ? seg(id + '-m', ms.map(function (m) { return [m.key, m.label]; }), M, 'Chance') : '') + (groups.length > 1 ? seg(id + '-g', groups.map(function (g) { return [g.key, g.label]; }), G, 'Group') : '') + '</div>' +
    '<div class="qk-grid">' +
      '<div class="qk-span-8">' + card('Chances over time', '', '<div class="qk-chart" id="' + id + '-c" style="height:380px"></div><p class="qkl-note">' + note + '</p>', { flush: false, html: true, id: id + '-cc' }) + '</div>' +
      '<div class="qk-span-4">' + card('Movers this week', 'The biggest moves in our chances, and why', moversHTML(o), { flush: true }) + '</div>' +
      '<div class="qk-span-12">' + card('The race, team by team', 'Our chance now, its move over the week, the magic number, the schedule left and what the next game is worth', '<div id="' + id + '-t"></div>' +
        '<p class="qkl-note" style="padding-top:10px"><b>Magic number</b>: ' + esc(((L.race || {})[Object.keys(L.race || {})[0]] || {}).unit || 'wins') + ' from the team’s own results plus the first team out’s dropped results that clinch a place (shown once within reach; E: the elimination number). <b>Schedule left</b>: 1st is the hardest, from our ratings of the opponents still to play. <b>Next game</b>: our chance after a win / after a loss.</p>', { flush: true }) + '</div>' +
      '<div class="qk-span-12">' + card('The games that matter most this week', 'Ranked by how far one result moves the race', gamesHTML(o), { flush: true }) + '</div>' +
    '</div></section>';
  function groupKeys() { var g = groups.filter(function (x) { return x.key === G; })[0] || groups[0]; return g.teams; }
  function draw() {
    loadLog(o).then(function (log) {
      if (!el.isConnected) return;
      drawChart('#' + id + '-c', o, log, groupKeys(), M);
      var t = document.getElementById(id + '-t');
      if (t) t.innerHTML = raceTable(o, groupKeys(), M, log);
      var cc = document.querySelector('#' + id + '-cc .qk-card-sub');
      if (cc) cc.textContent = 'Our ' + lc(metricOf(L, M).label) + ' chance, ' + ((groups.filter(function (x) { return x.key === G; })[0] || {}).label || '');
    });
  }
  var sm = document.getElementById(id + '-m'), sg = document.getElementById(id + '-g');
  if (sm) QK.seg(sm, function (v) { M = v; draw(); });
  if (sg) QK.seg(sg, function (v) { G = v; draw(); });
  draw();
};

/* ─────────────────────────────────────── the shape of the league */
QKL.shape = function (el, o) {
  css();
  if (typeof el === 'string') el = document.querySelector(el);
  var L = o.league;
  if (!el || !L) return;
  var id = 'qkls' + Math.floor(Math.random() * 1e6);
  var Q = L.quad, T = L.teams || {}, notes = L.notes || {};
  var keys = Object.keys(T);
  var qPts = Q ? keys.map(function (k) { var v = T[k].vals || {}; return isNum(v[Q.x]) && isNum(v[Q.y]) ? { x: v[Q.x], y: Q.flipY ? -v[Q.y] : v[Q.y], name: nm(o, k), label: ab(o, k), color: tm(o, k).colour, href: href(o, k), sub: ((T[k].chips || [])[0] || [])[0] } : null; }).filter(Boolean) : [];
  var P = L.profile || {};
  var lk = P.early ? [] : keys.filter(function (k) { return T[k].luck && isNum(T[k].luck.d); }).sort(function (a, b) { return T[b].luck.d - T[a].luck.d; });
  var u = notes.luck_unit || 'wins';
  var tiers = (L.tiers || []).map(function (x) {
    return '<div class="qkl-tier"><h5>' + esc(x.label) + '</h5><p>' + esc(x.sub || '') + ' · ' + x.teams.length + '</p><div class="ts">' + x.teams.map(function (k) {
      var p = (L.current || {})[(L.notes || {}).metric] || {};
      return '<a href="' + esc(href(o, k)) + '" title="' + esc(nm(o, k) + (isNum(p[k]) ? ': ' + pct(p[k]) : '')) + '">' + QK.teamMark(mark(o, k), 'sm') + '</a>';
    }).join('') + '</div></div>';
  }).join('');
  var subs = [];
  if (qPts.length) subs.push('offence against defence');
  if (lk.length) subs.push('each team’s record against the record its numbers deserved');
  if (tiers) subs.push('the tiers our chances put them in');
  var sub = subs.length ? subs.join(', ').replace(/, ([^,]*)$/, ' and $1') : '';
  el.innerHTML = '<section class="qk-section qkl-sec">' + QK.sectionHead({ kicker: 'The shape of the league', title: 'Who is good at what, and who is for real', sub: sub ? sub.charAt(0).toUpperCase() + sub.slice(1) + '.' : '' }) +
    '<div class="qk-grid">' +
    (qPts.length ? '<div class="qk-span-6">' + card('Offence v defence', Q.sub || 'Up and right is better (the defence axis is turned so fewer allowed is higher); dashed: the league average', '<div class="qk-chart" id="' + id + '-q" style="height:420px"></div>') + '</div>' : '') +
    (lk.length ? '<div class="qk-span-6">' + card('Record v the numbers', 'Actual ' + u + ' minus the ' + u + ' the numbers deserved (' + (notes.luck_basis || 'Pythagorean') + ')', '<div class="qk-chart" id="' + id + '-l" style="height:' + Math.max(320, 16 * lk.length + 70) + 'px"></div><p class="qkl-note">Above zero: winning more than the scoring says, often on close games; it rarely lasts. Below: the record trails the play.' + (notes.close ? ' Close games: ' + esc(notes.close) + '.' : '') + '</p>', { flush: false }) + '</div>' : '') +
    (P.early && !lk.length && keys.some(function (k) { return T[k].luck; }) ? '<div class="qk-span-6">' + card('Record v the numbers', '', QK.empty('Early days', 'The record against the numbers appears after ' + (P.min_gp || 10) + ' ' + (o.unitGames || 'games') + ': before then one close game moves it more than the play does.')) + '</div>' : '') +
    (tiers ? '<div class="qk-span-12">' + card('The tiers', 'From our chances today', '<div class="qkl-tiers">' + tiers + '</div>', { flush: true }) + '</div>' : '') +
    '</div></section>';
  if (qPts.length && QKC) {
    var fx = Q.xFmt === 'pct1' ? function (v) { return (100 * v).toFixed(0) + '%'; } : function (v) { return Number(v).toFixed(Math.abs(v) < 10 ? 1 : 0); };
    QKC.quadrant('#' + id + '-q', { points: qPts, xName: Q.xName, yName: Q.yName, refX: 'mean', refY: 'mean', corners: Q.corners, xFmt: fx,
      yFmt: function (v) { return Q.flipY ? fx(-v) : fx(v); }, label: 'Offence against defence' });
  }
  if (lk.length && QKC) {
    QKC.bar('#' + id + '-l', { cats: lk.map(function (k) { return ab(o, k); }), series: [{ name: 'Above expected', data: lk.map(function (k) { return T[k].luck.d; }) }], horizontal: true,
      colors: lk.map(function (k) { return T[k].luck.d >= 0 ? QKC.tokens().up : QKC.tokens().down; }), fmt: function (v) { return fmt.signed(v, 1); }, hrefs: lk.map(function (k) { return href(o, k); }),
      labelWidth: 46, valName: u.charAt(0).toUpperCase() + u.slice(1) + ' above expected', catName: 'Team', label: 'Record against the record the numbers deserved' });
  }
};

/* ─────────────────────────────────────── the team page */
QKL.team = function (el, o, key) {
  css();
  if (typeof el === 'string') el = document.querySelector(el);
  var L = o.league;
  if (!el || !L || !((L.teams || {})[key] || (L.race || {})[key])) return;
  var id = 'qklt' + Math.floor(Math.random() * 1e6);
  var ms = (L.metrics || []).filter(function (m) { return isNum(((L.current || {})[m.key] || {})[key]); });
  el.innerHTML = '<section class="qk-section qkl-sec">' + QK.sectionHead({ kicker: 'Strengths, weaknesses and the race', title: o.teamTitle || 'What they do well, and where the race stands', html: true,
      sub: 'Percentiles among the league’s teams on our team set, the plain-English read, and our chances over the season.' }) +
    '<div class="qk-grid"><div class="qk-span-12"><section class="qk-card">' + QKL.card(o, key, { head: false, link: false, meters: o.meters }) + '</section></div>' +
    (ms.length ? '<div class="qk-span-12">' + card('Chances over the season', ms.map(function (m) { return m.label; }).join(', ') + ': ours' + ((L.history || {}).live_from ? ', a snapshot a day since ' + dayLabel(L.history.live_from) + ((L.history.rebuilt || []).length ? '; before that rebuilt from our simulation as of each date' : '') : ''), '<div class="qk-chart" id="' + id + '-c" style="height:320px"></div>') + '</div>' : '') +
    '</div></section>';
  if (!ms.length) return;
  loadLog(o).then(function (log) {
    var c = document.getElementById(id + '-c');
    if (!c) return;
    var any = null;
    var series = ms.map(function (m, i) {
      var s = log ? logSeries(log, o.season, m.key) : null;
      if (s && s.dates.length > 1) any = s;
      return s && s.series[key] ? { name: m.label, label: m.label, data: s.series[key], ours: i === 0, dates: s.dates } : null;
    }).filter(Boolean);
    if (!any || !series.length) { c.innerHTML = QK.empty('Tracking since ' + dayLabel((L.history || {}).first), 'The chart draws once two days of chances are on record.'); return; }
    var h = L.history || {};
    QKC.forecast(c, { x: any.dates.map(function (d) { return d + 'T12:00:00Z'; }), xType: 'time', series: series.map(function (s) { return { name: s.name, label: s.label, data: s.data, ours: s.ours }; }),
      annotations: h.live_from && any.dates[0] < h.live_from ? [{ x: h.live_from + 'T12:00:00Z', label: 'Live from ' + dayLabel(h.live_from) }] : [],
      yName: 'Our chance', xName: 'Date', xFmt: dayTick, label: nm(o, key) + ': our chances over the season' });
  });
};

/* ─────────────────────────────────────── top performers (team pages) */
/* QKL.performers(el, { kicker, title, sub, metric: { label, unit, model: 'GAR' (the "Our model" tag; omit for a box
 *   score) }, overall: [ROW], groups: [{ label, rows: [ROW] }], note (HTML), empty })
 * ROW = { name, href, pos, value (formatted text), pct (0-100: league percentile among qualified players at the
 *   position), rank, n (qualified players at the position), peer ('forwards'), sub } -> the team's best players
 * overall (cards) and by position (LED meters with the percentile box and the rank among the league's qualified). */
function perfRow(r) {
  var p = isNum(r.pct) ? Math.max(0, Math.min(100, r.pct)) : null;
  var rk = isNum(r.rank) && isNum(r.n) ? QK.ordinal(r.rank) + ' of ' + r.n + (r.peer ? ' ' + r.peer : '') : (r.sub || '');
  return '<div class="qkl-pr"><span class="who">' + (r.href ? '<a href="' + esc(r.href) + '">' + esc(r.name) + '</a>' : esc(r.name)) + (r.pos ? '<small>' + esc(r.pos) + '</small>' : '') + '</span>' +
    '<span class="v num">' + esc(r.value === undefined || r.value === null ? '—' : r.value) + '</span>' +
    (p !== null ? '<span class="m">' + QK.meter(p, { label: r.name + ': ' + QK.ordinal(Math.round(p)) + ' percentile' + (rk ? ', ' + rk : '') }) +
      '<span class="qk-pbox num" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '">' + Math.round(p) + '</span><span class="rk">' + esc(rk) + '</span></span>' :
      (rk ? '<span class="m"><span class="rk">' + esc(rk) + '</span></span>' : '')) + '</div>';
}
QKL.performers = function (el, o) {
  css();
  if (typeof el === 'string') el = document.querySelector(el);
  if (!el) return;
  o = o || {};
  var m = o.metric || {};
  var tag = m.model && QK.ours ? ' ' + QK.ours({ model: m.model, short: false }) : '';
  var groups = (o.groups || []).filter(function (g) { return g && (g.rows || []).length; });
  var over = (o.overall || []).filter(Boolean);
  var body = !over.length && !groups.length ? QK.empty(o.emptyTitle || 'Not enough games yet', o.empty || 'Top performers appear once players reach the sample where the numbers settle.') :
    (over.length ? '<div class="qkl-top1">' + over.map(perfRow).join('') + '</div>' : '') +
    (groups.length ? '<div class="qkl-tp">' + groups.map(function (g) { return '<div class="qkl-tpg"><h5>' + esc(g.label) + '</h5>' + g.rows.map(perfRow).join('') + '</div>'; }).join('') + '</div>' : '') +
    '<p class="qkl-note">' + (o.note || ('The box is the league percentile among qualified players at the same position, by ' + esc(m.label || 'our headline metric') + (m.unit ? ' (' + esc(m.unit) + ')' : '') + '; the rank counts the same players.')) + '</p>';
  el.innerHTML = '<section class="qk-section qkl-sec">' + QK.sectionHead({ kicker: o.kicker || 'Top performers', title: o.title || 'Who carries them, and how they compare', sub: o.sub || '' }) +
    '<section class="qk-card"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(m.label || 'Top performers') + tag + '</div>' +
    '<div class="qk-card-sub">The team’s best overall, then the best at each position, against the whole league</div></div></div><div class="qk-card-body" style="padding:0">' + body + '</div></section></section>';
};

/* ─────────────────────────────────────── top and bottom performers (league pages) */
/* QKL.leaders(el, o): a league page's "Top and bottom performers". A position picker (the views: all players, each
 * position group, teams), the leader on every metric of the view as tiles (the metric picker), then the top N and the
 * bottom N on the chosen metric as two LED-meter boards, "Leaders" and "Struggling", each row linked to the player
 * (or team) page with its value, percentile and rank among the qualified.
 * o = { data: { views: [VIEW], n }, kicker, title, sub, view (first view's key), metric (first metric's key),
 *       team: fn(teamKey) -> { abbr, name, colour, logo, href } (the mark and the team link),
 *       href: fn(id, VIEW) -> the player page (a team view links through team()), note (HTML, after the footnote),
 *       empty (text), scope ('league' in "Bottom of the league on ..."; 'tour', 'grid') }
 * VIEW = { key, label, entity: 'player' | 'team', peer ('centre-backs', for "12th of 80 centre-backs"), min (the
 *          qualifying floor in words: '450 minutes'), note (HTML: this view's own footnote), metrics: [METRIC] }
 * METRIC = { key, label, unit, dir: 'higher' | 'lower', ours (our model's name: the "Our model" tag), fmt (a
 *          QKL.fmtVal code), tip, n (qualified), top: [ROW], bot: [ROW] }
 * ROW = [id, name, team, value, pct (0-100, 100 the best), rank]. oddsmarkets/common/performers.py writes this shape
 * (data/.../performers.json); QKL.board(rows, metric, n) builds a METRIC in the page from rows [{ id, name, team, v }].
 * Copy: the bottom board is "Struggling" / "Bottom of the league on ...", never mocking. */
QKL.board = function (rows, m, N) {
  N = N || 5;
  var lower = m.dir === 'lower';
  var rs = (rows || []).filter(function (r) { return r && isNum(r.v); }).slice().sort(function (a, b) {
    return (lower ? a.v - b.v : b.v - a.v) || String(a.name).localeCompare(String(b.name));
  });
  var n = rs.length, out = {}, k;
  for (k in m) if (Object.prototype.hasOwnProperty.call(m, k)) out[k] = m[k];
  var better = 0;
  var rows2 = rs.map(function (r, i) {
    if (i && rs[i - 1].v !== r.v) better = i;
    var rank = better + 1;
    return [r.id, r.name, r.team, r.v, n > 1 ? Math.round(100 * (n - rank) / (n - 1)) : 50, rank];
  });
  out.n = n;
  out.top = rows2.slice(0, Math.min(N, n));
  out.bot = n > N ? rows2.slice(Math.max(N, n - N)) : [];
  return out;
};
/* QKL.teamView(league, { key: 'teams', label: 'Teams', peer: 'teams', ours: 'Team rating model', oursIds: [ids], n })
 * -> a VIEW of the teams on the league block's team set (L.profile.metrics with L.teams[k].vals; style metrics left
 * out, our model metrics first: the profile's `model` flag, o.oursIds, or the spec catalogue once QK.spec has loaded
 * it), or null. Early in the season (profile.early) only our rating is ranked, as on the team cards. */
QKL.teamView = function (L, o) {
  o = o || {};
  var P = (L || {}).profile || {}, T = (L || {}).teams || {}, keys = Object.keys(T);
  if (!keys.length) return null;
  var ms = (P.metrics || []).filter(function (m) { return !m.style && (!P.early || m.model); });
  var cat = QK.spec && QK.spec.get ? QK.spec.get() : null, oid = o.oursIds || [];
  var isOurs = function (m) { return !!(m.model || oid.indexOf(m.id) >= 0 || (cat && cat.ours(m.id))); };
  ms = ms.filter(isOurs).concat(ms.filter(function (m) { return !isOurs(m); }));
  var metrics = ms.map(function (m) {
    var rows = keys.map(function (k) { return { id: k, name: (o.name ? o.name(k) : k), team: k, v: ((T[k] || {}).vals || {})[m.id] }; });
    return QKL.board(rows, { key: m.id, label: m.label, unit: m.unit || '', dir: m.dir === 'lower' ? 'lower' : 'higher', fmt: m.fmt, ours: isOurs(m) ? (o.ours || 'Our model') : '', tip: m.tip || '' }, o.n || 5);
  }).filter(function (m) { return m.n > 1; });
  return metrics.length ? { key: o.key || 'teams', label: o.label || 'Teams', entity: 'team', peer: o.peer || 'teams',
    min: P.early ? 'early in the season only our rating is ranked; the rest after ' + (P.min_gp || 10) + ' games' : '', metrics: metrics } : null;
};
/* the unit beside a number; none when the number already carries it (a share shown as 64.2% or .912) */
function ldUnit(m) { var u = String(m.unit || ''); return u === '%' || /^pct/.test(String(m.fmt || '')) || /^(%|percent|share)$/i.test(u) ? '' : u; }
function ldTeam(o, k) { var t = k && o.team ? o.team(k) : null; return t || (k ? { abbr: k, name: k } : null); }
function ldRow(o, V, M, r) {
  var team = V.entity === 'team', t = ldTeam(o, r[2] || (team ? r[0] : '')), p = isNum(r[4]) ? Math.max(0, Math.min(100, r[4])) : null;
  var h = team ? (t && t.href) : (o.href ? o.href(r[0], V) : '');
  var nmTxt = team && t ? (t.name || r[1]) : r[1];
  var rk = QK.ordinal(r[5]) + ' of ' + (M.n || '?') + (V.peer ? ' ' + V.peer : '');
  return '<li><span class="rk num">' + esc(r[5]) + '</span>' + (t ? QK.teamMark({ abbr: t.abbr, name: t.name, colour: t.colour, logo: t.logo }, 'sm') : '<span></span>') +
    '<span class="who">' + (h ? '<a href="' + esc(h) + '">' + esc(nmTxt) + '</a>' : esc(nmTxt)) + (!team && t && t.logo ? '<small>' + esc(t.abbr || t.name || '') + '</small>' : '') + '</span>' +
    '<span class="v num">' + esc(fmtVal(r[3], M.fmt)) + '</span>' +
    (p !== null ? '<span class="m">' + QK.meter(p, { label: nmTxt + ': ' + QK.ordinal(Math.round(p)) + ' percentile, ' + rk }) +
      '<span class="qk-pbox num" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '" title="' + esc(rk) + '">' + Math.round(p) + '</span></span>' : '') + '</li>';
}
QKL.leaders = function (el, o) {
  css();
  if (typeof el === 'string') el = document.querySelector(el);
  if (!el) return;
  o = o || {};
  var D = o.data || {};
  var views = (D.views || []).map(function (v) {
    var ms = (v.metrics || []).filter(function (m) { return m && (m.top || []).length; });
    return ms.length ? { v: v, ms: ms } : null;
  }).filter(Boolean);
  var head = QK.sectionHead({ kicker: o.kicker || 'Top and bottom performers', title: o.title || 'Who leads the league, and who is struggling',
    sub: o.sub || 'The leaders and the bottom of the league on each key number, league-wide and by position. Qualified players only; each name opens the player page.' });
  if (!views.length) {
    el.innerHTML = '<section class="qk-section qkl-sec">' + head + QK.empty('Not enough games yet', o.empty || 'The boards fill once players reach the sample where the numbers settle.') + '</section>';
    return;
  }
  var id = 'qkld' + Math.floor(Math.random() * 1e6);
  var VK = o.view && views.some(function (x) { return x.v.key === o.view; }) ? o.view : views[0].v.key, MK = o.metric || null;
  el.innerHTML = '<section class="qk-section qkl-sec">' + head +
    (views.length > 1 ? '<div class="qkl-ld-ctl">' + seg(id + '-v', views.map(function (x) { return [x.v.key, x.v.label]; }), VK, 'Position') + '</div>' : '') +
    '<div id="' + id + '-b"></div></section>';
  function draw() {
    var X = views.filter(function (x) { return x.v.key === VK; })[0] || views[0], V = X.v;
    var M = X.ms.filter(function (m) { return m.key === MK; })[0] || X.ms[0];
    MK = M.key;
    var tiles = '<div class="qkl-lt" role="group" aria-label="Metric">' + X.ms.map(function (m) {
      var l = m.top[0];
      return '<button type="button" class="qkl-lt-b" data-m="' + esc(m.key) + '" aria-pressed="' + (m.key === MK) + '"' + (m.tip ? ' title="' + esc(m.tip) + '"' : '') + '>' +
        '<span class="k">' + esc(m.label) + (m.ours && QK.ours ? QK.ours({ model: m.ours, short: true }) : '') + '</span>' +
        '<span class="w">' + esc(V.entity === 'team' ? ((ldTeam(o, l[2] || l[0]) || {}).name || l[1]) : l[1]) + '</span>' +
        '<span class="v">' + esc(fmtVal(l[3], m.fmt)) + (ldUnit(m) ? '<small>' + esc(ldUnit(m)) + '</small>' : '') + '</span></button>';
    }).join('') + '</div>';
    var who = V.peer || (V.entity === 'team' ? 'teams' : 'players');
    var lbl = esc(lc(M.label)) + (ldUnit(M) ? ' (' + esc(ldUnit(M)) + ')' : '');
    var tag = M.ours && QK.ours ? QK.ours({ model: M.ours }) : '';
    var lead = '<section class="qk-card"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title qkl-ld-h">Leaders' + tag + '</div><div class="qk-card-sub">The top ' + M.top.length + ' of ' + (M.n || M.top.length) + ' qualified ' + esc(who) + ' on ' + lbl + '</div></div></div>' +
      '<div class="qk-card-body" style="padding:0"><ol class="qkl-ld">' + M.top.map(function (r) { return ldRow(o, V, M, r); }).join('') + '</ol></div></section>';
    var bot = (M.bot || []).length ? '<section class="qk-card qkl-dn"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title qkl-ld-h">Struggling</div><div class="qk-card-sub">Bottom of the ' + esc(o.scope || 'league') + ' on ' + lbl + ' among the ' + (M.n || '') + ' qualified ' + esc(who) + '</div></div></div>' +
      '<div class="qk-card-body" style="padding:0"><ol class="qkl-ld">' + M.bot.map(function (r) { return ldRow(o, V, M, r); }).join('') + '</ol></div></section>' :
      '<section class="qk-card qkl-dn"><div class="qk-card-head"><div class="qk-card-title">Struggling</div></div><div class="qk-card-body">' + QK.empty('Too few qualified yet', 'The bottom of the board shows once more than ' + M.top.length + ' ' + who + ' qualify.') + '</div></section>';
    var foot = (V.min ? 'Qualified: ' + esc(V.min) + '. ' : '') + 'The box is the percentile among the qualified ' + esc(who) + ' (100 is the best) and the big number on the left the rank.' +
      (M.dir === 'lower' ? ' Lower is better on ' + esc(lc(M.label)) + ', so the leaders have the lowest numbers.' : '') + (M.tip ? ' <b>' + esc(M.label) + ':</b> ' + esc(M.tip) : '') + (V.note ? ' ' + V.note : '') + (o.note ? ' ' + o.note : '');
    var b = document.getElementById(id + '-b');
    if (!b) return;
    b.innerHTML = tiles + '<div class="qk-grid"><div class="qk-span-6">' + lead + '</div><div class="qk-span-6">' + bot + '</div></div><p class="qkl-note" style="padding:12px 0 0">' + foot + '</p>';
    Array.prototype.forEach.call(b.querySelectorAll('.qkl-lt-b'), function (x) {
      x.addEventListener('click', function () { MK = x.getAttribute('data-m'); draw(); var y = b.querySelector('.qkl-lt-b[data-m="' + MK + '"]'); if (y && y.focus) y.focus(); });
    });
  }
  var sv = document.getElementById(id + '-v');
  if (sv) QK.seg(sv, function (v) { VK = v; draw(); });
  draw();
};

root.QKL = QKL;
})(window);
