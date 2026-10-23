/* The Quant Gridiron — Who moves next (docs/_design/MOVES_VIEWS.md, US-sports section), on Design System 2.0.
 * GI.MV renders the movement payload (<S>/movement.json, current season only) into four views and follows
 * `published` (never the table in the spec): the team page's Outlook card, its roster table "Chance of moving" and the
 * Targets block; the player page's Movement card; a "Chance of moving" column for the Players catalogue; and the Model
 * page's "Who moves next" (notes verbatim, the validation table, the decile chart). A block that is not published shows
 * its reason (or the league base rate with a "base rate" chip), never a placeholder number. The payload is 250 KB, so
 * every page loads it after its first paint. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const TYPE_COL = ['var(--c-1)', 'var(--c-3)', 'var(--c-5)', 'var(--c-4)'];
const MV = {};

function load() { const S = GI.currentSeason(); return GI.loadYear('movement.json', S).then(d => (d && d.ok !== false && Array.isArray(d.players) ? d : null)); }
function cols(d, key) { const o = {}; ((d && d[key]) || []).forEach((c, i) => { o[c] = i; }); return o; }
function rows(d) {
  if (!d) return [];
  const F = d.player_fields || [];
  return d.players.map(r => { const o = {}; F.forEach((c, i) => { o[c] = r[i]; }); return o; });
}
function byPid(d) { const o = {}; rows(d).forEach(r => { o[String(r.pid)] = r; }); return o; }
function pct(p) { return !isNum(p) ? '—' : p > 0 && p < 0.01 ? '<1%' : Math.round(p * 100) + '%'; }
function pct1(p) { return !isNum(p) ? '—' : (p * 100 < 10 ? (p * 100).toFixed(1) : Math.round(p * 100)) + '%'; }
function chip(text, tip) { return '<span class="qk-tag gi-mv-chip"' + (tip ? ' data-tip="' + esc(tip) + '" tabindex="0"' : '') + '>' + esc(text) + '</span>'; }
function deadlineText(d) {
  const h = (d && d.horizons) || {};
  return h.deadline ? GI.fmtDate(h.deadline, { year: false, weekday: false }) + (h.deadline_estimated ? ' (estimated)' : '') : 'the deadline';
}
function cap1(t) { t = String(t || ''); return t.charAt(0).toUpperCase() + t.slice(1); }
function nextText(d) { return ((d && d.horizons) || {}).next || 'next season'; }
function typeLabel(d, t) { return ((d && d.type_labels) || {})[t] || GI.titleCase(t); }
function shortType(t) { return { trade: 'In-season move', release: 'Released in season', other: 'Offseason departure' }[t] || GI.titleCase(t); }
/* A 0-100% bar for p_next (the chance of leaving) split into the types in the payload's order (they sum to p_next). */
function typeBar(r, d) {
  const T = (d && d.types) || [];
  const p = isNum(r.p_next) ? r.p_next : null;
  if (p === null) return '<span class="qk-muted">—</span>';
  const seg = T.map((t, i) => { const v = r['p_' + t]; return isNum(v) && v > 0 ? '<i style="width:' + (100 * v).toFixed(1) + '%;background:' + TYPE_COL[i % TYPE_COL.length] + '"></i>' : ''; }).join('');
  const aria = 'Chance of leaving ' + pct(p) + ': ' + T.map(t => shortType(t) + ' ' + pct(r['p_' + t])).join(', ');
  return '<span class="gi-mv-bar" role="img" aria-label="' + esc(aria) + '"><span class="gi-mv-track">' + seg + '</span><b>' + pct(p) + '</b></span>';
}
function legend(d) {
  const T = (d && d.types) || [];
  const pub = (d && d.published) || {};
  return QK.keys(T.map((t, i) => ({ name: shortType(t), color: TYPE_COL[i % TYPE_COL.length], kind: 'band' }))).replace('</div>', (pub.type ? '' : chip('base shares', (d.reasons || {}).type || 'The split is the league shares, not the player\'s')) + '</div>');
}
MV.load = load; MV.rows = rows; MV.byPid = byPid; MV.typeBar = typeBar; MV.legend = legend; MV.pct = pct;

/* ── team page: Outlook, the roster's chance of moving, targets ─────────────────────────────────────────────── */
MV.teamSection = function (d, abbr, needs) {
  if (!d) return '';
  const pub = d.published || {};
  const tm = (d.teams || {})[abbr] || {};
  const mine = rows(d).filter(r => r.team === abbr).sort((a, b) => (b.p_next || 0) - (a.p_next || 0));
  if (!mine.length && !tm.status) return '';
  const horizon = d.team_horizon === 'deadline' ? 'to the deadline, ' + deadlineText(d) : nextText(d);
  const weak = {};
  ((needs && needs.positions) || []).forEach(p => { if (/^[DF]$/.test(String(p.grade || ''))) weak[p.pos] = 1; });
  /* outlook: expected departures (sum of the published chances), arrivals (model or the league average) */
  const depByPos = {};
  mine.forEach(r => { if (isNum(r.p_next)) depByPos[r.pos] = (depByPos[r.pos] || 0) + r.p_next; });
  const outlook = Array.isArray(tm.outlook) && tm.outlook.length && pub.arrivals ? GI.colRows({ cols: (d.team_fields || {}).outlook || [], rows: tm.outlook }) : null;
  const posList = Object.keys(depByPos).filter(p => p !== 'LS').sort((a2, b2) => depByPos[b2] - depByPos[a2]);
  const statusTip = 'From our standings forecast: contending above ' + Math.round(((d.status_cuts || {}).contending || 0.6) * 100) + '% to make the playoffs, rebuilding below ' + Math.round(((d.status_cuts || {}).rebuilding || 0.4) * 100) + '%';
  const tl = [{ label: 'Expected departures', value: isNum(tm.exp_departures) ? GI.num(tm.exp_departures, 1) : '—', sub: 'by ' + nextText(d) + ' · the sum of each player\'s chance of leaving', signal: true, tip: 'The sum of the chance of leaving of everyone on the roster' }];
  if (outlook && isNum(tm.exp_arrivals)) tl.push({ label: 'Expected arrivals', value: GI.num(tm.exp_arrivals, 1), sub: 'from other teams\' rosters', tip: 'Players from other NFL rosters only: draft picks, undrafted free agents and players from outside the league are not counted.' });
  const tiles = QK.stats(tl);
  const grid = '<div class="qk-table-wrap"><table class="qk-table dense gi-mv-grid"><thead><tr><th>Position</th>' + (outlook ? '<th class="num"><span data-tip="Our chance the team adds at least one player there by ' + esc(nextText(d)) + '">Chance of adding</span></th><th class="num">Arrivals</th>' : '') + '<th class="num"><span data-tip="Sum of the chance of leaving of the players there">Expected departures</span></th></tr></thead><tbody>' +
    posList.map(p => {
      const o = outlook ? outlook.find(r => r.pos === p) : null;
      return '<tr><td><b>' + esc(GI.posLabel(p)) + '</b>' + (weak[p] ? ' ' + chip('need', 'A weak position on our strengths-and-needs grades (D or F)') : '') + '</td>' + (outlook ? '<td class="num">' + GI.probBar(o ? o.p_add : null) + '</td><td class="num">' + GI.num(o ? o.exp_arrivals : null, 1) + '</td>' : '') + '<td class="num">' + GI.num(depByPos[p] || 0, 1) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  const outlookCard = GI.card('Outlook: ' + esc(horizon), (tm.status ? 'Status: ' + chip(tm.status, statusTip) + ' · ' : '') + 'who is likely to leave, by position', tiles + grid, { span: 5 });
  /* roster: chance of leaving */
  const dlOn = !!pub.deadline;
  const tbl = mine.length ? GI.tableHTML([{ label: 'Player' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'Chance of leaving', align: 'right', title: 'Our chance the player is not with this team at ' + nextText(d) + '. ' + ((d.notes || [])[0] || '') },
    dlOn ? { label: cap1(d.deadline_label || 'traded') + ' by ' + deadlineText(d), align: 'right', title: 'Our chance the player is ' + (d.deadline_label || 'traded') + ' before the trade deadline (the weekly rosters cannot tell a trade from a waiver claim)' } : null].filter(Boolean),
    mine.map(r => ({ _href: GI.playerHref(r.pid), cells: [{ html: GI.playerLink(r.pid, r.name) + (r.why ? '<span class="gi-sub-line">' + esc(r.why) + '</span>' : ''), v: r.name }, { html: esc(GI.posLabel(r.pos)), v: r.pos }, { html: GI.num(r.age, 0), v: r.age },
      { html: typeBar(r, d), v: r.p_next }].concat(dlOn ? [{ html: pct1(r.p_dl), v: r.p_dl }] : []) })), { sticky: true, maxHeight: 520 }) : GI.muted('No players on this roster in the movement model.');
  const rosterCard = GI.card('Chance of leaving', 'Every player on the roster, by our chance of being gone by ' + esc(nextText(d)) + (dlOn ? '; and the chance of being ' + esc(d.deadline_label || 'traded') + ' before ' + esc(deadlineText(d)) : ''), legend(d) + tbl, { span: 7 });
  /* targets: only when the payload publishes them (the ranking must beat need x value and chance on the sealed seasons) */
  const tg = Array.isArray(tm.targets) && tm.targets.length && pub.targets ? GI.colRows({ cols: (d.team_fields || {}).targets || [], rows: tm.targets }) : [];
  const targets = tg.length ? GI.card('Who they could get', 'Ranked by chance of joining: the chance of a move × the chance of landing here; only players who would upgrade the weakest starter at the position',
    GI.tableHTML([{ label: '#', align: 'right', sortable: false }, { label: 'Player' }, { label: 'Pos' }, { label: 'Team' }, { label: 'Chance of joining', align: 'right' }, { label: 'Availability', align: 'right' }, { label: 'Fit', align: 'right' }, { label: 'Why', sortable: false }],
      tg.map((r, i) => [i + 1, { html: GI.playerLink(r.pid, r.name), v: r.name }, esc(GI.posLabel(r.pos)), { html: GI.teamChip(r.team), v: r.team }, { html: '<b class="gi-ours">' + pct1(r.p_join) + '</b>', v: r.p_join }, { html: GI.probBar(r.p_move), v: r.p_move }, { html: GI.signed(r.gain, 2) + ' ' + esc(d.unit || 'pts'), v: r.gain }, { html: '<span class="gi-play-desc">' + esc(r.why || '') + '</span>' }]))) : '';
  return '<section class="qk-section" id="tp-moves">' + GI.secHead({ kicker: 'Value & Moves', title: 'Who moves next', sub: 'Our chance each player leaves and the team\'s outlook by position. ' + esc((d.notes || [])[1] || '') }) +
    GI.grid(outlookCard + rosterCard) + targets + '</section>';
};

/* ── player page: the Movement card ────────────────────────────────────────────────────────────────────────── */
MV.playerCard = function (d, pid) {
  if (!d) return '';
  const r = byPid(d)[String(pid)];
  if (!r) return '';
  const pub = d.published || {};
  const T = d.types || [];
  const big = pub.next && isNum(r.p_next) ? '<div class="gi-mv-big"><span class="gi-disp">' + pct(r.p_next) + '</span><span>chance of leaving: not with ' + esc(GI.teamName(r.team)) + ' at ' + esc(nextText(d)) + '</span></div>' : '';
  const split = isNum(r.p_next) && r.p_next > 0 ? '<div class="gi-mv-split"><div class="qk-kicker">If the player leaves</div><span class="gi-mv-track wide">' + T.map((t, i) => { const v = r['p_' + t]; return isNum(v) && v > 0 ? '<i style="width:' + (100 * v / r.p_next).toFixed(1) + '%;background:' + TYPE_COL[i % TYPE_COL.length] + '" title="' + esc(typeLabel(d, t) + ': ' + Math.round(100 * v / r.p_next) + '%') + '"></i>' : ''; }).join('') + '</span>' + legend(d) + '</div>' : '';
  const dl = pub.deadline && isNum(r.p_dl) ? '<div class="gi-mv-dl"><b>' + pct1(r.p_dl) + '</b> chance of being ' + esc(d.deadline_label || 'traded') + ' before the deadline, ' + esc(deadlineText(d)) + '</div>' : '';
  const ctx = [isNum(r.age) ? 'age ' + GI.num(r.age, 0) : '', isNum(r.yrs) ? r.yrs + ' accrued season' + (r.yrs === 1 ? '' : 's') : '', isNum(r.value) ? GI.num(r.value, 1) + ' ' + (d.unit || 'points') + ' of value' : '', r.why || ''].filter(Boolean).join(' · ');
  return GI.card('Movement', 'Our chance the player leaves, from our own movement model · ' + esc((d.notes || [])[1] ? 'no contract data is used' : ''), big + (ctx ? '<p class="gi-cap">' + esc(ctx) + '</p>' : '') + split + dl, { cls: 'gi-mv-card' });
};

/* ── Model page: Who moves next ────────────────────────────────────────────────────────────────────────────── */
MV.modelSection = function (d) {
  if (!d) return '';
  const V = d.validation || {}, pub = d.published || {};
  const NAME = { next: 'Leaves by ' + nextText(d), deadline: cap1(d.deadline_label || 'traded') + ' before the deadline', type: 'How the player leaves (type split)', arrivals: 'Arrivals by position', targets: 'Targets' };
  const ci = a => (Array.isArray(a) ? GI.signed(a[0], 4) + ' [' + GI.signed(a[1], 4) + ', ' + GI.signed(a[2], 4) + ']' : '—');
  const tbl = GI.tableHTML([{ label: 'Block', sortable: false }, { label: 'Sealed seasons', sortable: false }, { label: 'n', align: 'right' }, { label: 'Rate', align: 'right' }, { label: 'Log-loss model v base', align: 'right' }, { label: 'Gain (95% CI)', align: 'right' }, { label: 'Calibration slope', align: 'right' }, { label: 'Published', sortable: false }],
    Object.keys(NAME).filter(k => V[k]).map(k => { const t = (V[k] || {}).test || {}; return [esc(NAME[k]), esc(((d.split || {}).test || []).join(', ')), { html: GI.int(t.n || t.team_seasons), v: t.n }, { html: isNum(t.rate) ? GI.pct(t.rate, 1) : '—', v: t.rate },
      { html: isNum(t.logloss) ? GI.num(t.logloss, 4) + ' v ' + GI.num(t.logloss_base, 4) : (t.model ? 'top-10 hit rate ' + GI.pct(t.model.hit_rate, 1) : '—') }, { html: t.ll_gain ? ci(t.ll_gain) : (t.model_minus_chance ? ci(t.model_minus_chance) : '—') }, { html: isNum(t.cal_slope) ? GI.num(t.cal_slope, 2) : '—', v: t.cal_slope },
      { html: pub[k] ? '<span class="gq-ok">yes</span>' : '<span class="gq-no" data-tip="' + esc((d.reasons || {})[k] || '') + '" tabindex="0">no</span>' }]; }));
  return '<div class="qk-card gi-ocard" id="cal-moves"><div class="gi-ohead">Who moves next <span class="qk-card-sub">The player-movement model on the sealed seasons; a block is published only when it beats the base rate and stays calibrated.</span></div>' +
    '<div class="gq-read">' + (d.notes || []).map(n => '<p>' + esc(n) + '</p>').join('') + '</div>' + tbl +
    ((V.next || {}).test && (V.next.test.deciles || []).length ? '<div class="gq-sub-head">Leaves by next season: predicted against observed, by decile</div>' + GI.chartBox('cal-mv-dec', 300, 'Movement model reliability by decile') : '') + '</div>';
};
MV.drawModel = function (d) {
  const t = d && d.validation && d.validation.next && d.validation.next.test;
  if (!t || !(t.deciles || []).length || !document.getElementById('cal-mv-dec')) return;
  GI.ch.reliability('cal-mv-dec', [{ name: 'Leaves by next season', colour: QK.cssVar('--signal'), bins: t.deciles.map(x => [x[0], x[1], x[2]]) }], { xName: 'Predicted chance', yName: 'Observed share' });
};

GI.MV = MV;
})(window.GI);
