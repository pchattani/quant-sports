/* The Quant Bullpen — shared helpers for the Design System 2.0 pages (BP.ui), on The Quant kit (QK, QKC).
 * The pattern every sport follows: docs/_design/MIGRATION_V2.md; the reference is the Rink (rk-ui.js).
 *
 *   head(o)                         QK.sectionHead with the level · season kicker
 *   card2(title, sub, body, opts)   a kit card (opts: right, foot, flush, id, cls)
 *   chart(id, h, label)             a sized chart container (role="img")
 *   team(tid, L) / tcol(tid) / pair(a, b)   kit team objects and two distinguishable chart colours
 *   records(season) / forms(games)  "W-L" and last-five form per club, for the v2 game cards
 *   fresh(card)                     false for a cached card still marked live or upcoming 12 hours after its start
 *   SETS / MDESC / setFor(kind, row) / pctGroups / sampleLine / floorOf   the comparison metric sets
 *   gloss()                          glossary.json as { hitter: {key: entry}, pitcher: {...} } (labels, formats)
 *   specReady / ours / oursTag / label / headIds / metricOpts / tagHeads / oursNote   our models first and tagged (round 5)
 *
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (BP) {
'use strict';

const U = BP.ui = {};
const esc = BP.esc, isNum = BP.isNum;

U.alive = el => !!el && el.isConnected;
U.f = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
U.pct = (p, d) => (isNum(p) ? QK.fmt.pct(Number(p), d) : '—');
U.signed = (v, d) => (isNum(v) ? (Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : '') + Math.abs(Number(v)).toFixed(d === undefined ? 1 : d) : '—');

U.kicker = (L, S, extra) => {
  const lv = BP.levelName(L) || 'MLB';
  return [lv, S || BP.state.season || BP.currentSeason(L)].concat(extra || []).filter(Boolean).join(' · ');
};
U.head = o => QK.sectionHead(Object.assign({ kicker: U.kicker(BP.state.level, BP.state.season) }, o));
U.card2 = (title, sub, body, opts) => {
  const o = opts || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
U.chart = (id, h, label) => '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>';
U.more = (href, label) => '<a href="' + href + '">' + esc(label) + ' →</a>';
U.seg = (id, label, opts, active) => '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label) + '">' + opts.map(o =>
  '<button type="button" aria-pressed="' + (String(o[0]) === String(active) ? 'true' : 'false') + '" data-value="' + esc(o[0]) + '">' + esc(o[1]) + '</button>').join('') + '</div>';

/* ── teams ─────────────────────────────────────────────────────────────── */
U.team = (tid, L, S) => { const x = BP.teamInfo(tid) || {}; return { name: x.short || x.name || BP.teamName(tid), full: x.name || '', short: x.short || '', abbr: BP.teamAbbr(tid), colour: x.colour, alt: x.alt || '', href: BP.teamHref(tid, L, S) }; };
/* v4: the raw kit colour and the alternate, for team blocks (QK.color.block / blockPair) */
U.raw = tid => (BP.teamInfo(tid) || {}).colour || '';
U.alt = tid => (BP.teamInfo(tid) || {}).alt || '';
U.tcol = tid => {
  const c = (BP.teamInfo(tid) || {}).colour;
  return c && QK.color.parse(c) ? QK.color.team(c) : QK.cssVar('--c-other');
};
U.pair = (a, b) => {
  const ca = U.tcol(a); let cb = U.tcol(b);
  const ok = (x, y) => (QK.color.distinct ? QK.color.distinct(x, y) : QK.color.contrast(x, y) >= 1.6);
  if (!ok(ca, cb)) { cb = QK.cssVar('--wp-b'); if (!ok(ca, cb)) cb = QK.cssVar('--wp-a'); }
  return [ca, cb];
};
U.teamEnt = (tid, L, S, sub) => (tid ? '<a class="bp-ent" href="' + esc(BP.teamHref(tid, L, S)) + '">' + BP.teamMark(tid, 'sm') + '<span class="nm">' + esc(BP.teamShort(tid)) + '</span>' + (sub ? '<span class="sb">' + esc(sub) + '</span>' : '') + '</a>' : '—');
U.playerEnt = (pid, L, sub, role) => {
  const x = BP.player(pid) || {};
  return '<a class="bp-ent" href="' + esc(BP.playerHref(pid, { level: L, role: role })) + '">' + (x.team ? BP.teamMark(x.team, 'sm') : '') + '<span class="nm">' + esc(BP.playerName(pid)) + '</span>' + (sub ? '<span class="sb">' + esc(sub) + '</span>' : '') + '</a>';
};

/* ── game cards ────────────────────────────────────────────────────────── */
U.records = season => {
  const rows = BP.standingsRows ? BP.standingsRows(season || {}) : {};
  const out = {};
  Object.keys(rows).forEach(t => { const r = rows[t]; if (isNum(r.w) && isNum(r.l)) out[t] = r.w + '-' + r.l; });
  return out;
};
/* Last five results per club from a list of game cards (oldest first), finals only. */
U.forms = games => {
  const by = {};
  (games || []).filter(g => g && BP.isFinal(g) && isNum(g.hs) && isNum(g.as) && g.hs !== g.as).sort((a, b) => String(a.start || a.date).localeCompare(String(b.start || b.date))).forEach(g => {
    (by[g.home] = by[g.home] || []).push(g.hs > g.as ? 'W' : 'L');
    (by[g.away] = by[g.away] || []).push(g.as > g.hs ? 'W' : 'L');
  });
  const out = {};
  Object.keys(by).forEach(t => { out[t] = by[t].slice(-5).join(''); });
  return out;
};
/* A cached card still marked live or upcoming 12 hours after its start is a stale snapshot: hide it. */
U.fresh = c => {
  if (c && BP.notNeeded && BP.notNeeded(c)) return false;
  if (!c || BP.isFinal(c)) return true;
  const t = Date.parse(c.start || c.date);
  return !isNum(t) || QK.now() - t < 12 * 3600 * 1000;
};
U.srcName = list => {
  const N = { kalshi: 'Kalshi', polymarket: 'Polymarket', draftkings_ml: 'DraftKings', draftkings: 'DraftKings', espn: 'ESPN BET' };
  return (list || []).map(x => { const k = typeof x === 'string' ? x : ((x && x.source) || ''); return N[k] || k; }).filter((x, i, a) => x && a.indexOf(x) === i).join(' / ');
};

/* ── the comparison metric sets (docs/METRICS_SPEC.md, docs/_design/metrics/baseball.json) ─────────────
   Peer groups: hitters by fielding position (catchers, first base, second base, third base, shortstop, centre field,
   corner outfield, designated hitter), pitchers by role (starters, relievers); percentiles are the payload's pct_role
   (the same position or role pool). Minimum samples: 200 PA for hitters, 300 BF for starters, 120 BF for relievers,
   prorated in season by team games / 162. A metric still short of the sample where it is half signal (m50) is drawn
   dashed. The player card, the compare page, the leaderboards and the distribution all read these. */
/* @@SETS-BEGIN@@ */
/* generated from docs/_design/metrics/baseball.json (2026-10-22) by the phase-2 front-end pass; [id, m50 (the sample where it is half signal), sample field] */
U.SETS = {
  "ALL": { spec: "hitters_all", name: "MLB hitters", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 315.0, "pa"], ["woba", 434.0, "pa"], ["barrel_pct", 63.0, "bip"], ["hard_pct", 60.0, "bip"], ["bat_speed", 56.0, "bat_swings"]]], ["Approach", [["k_pct", 70.0, "pa"], ["bb_pct", 133.0, "pa"], ["chase_pct", 75.0, "oz"]]], ["Glove, arm and legs", [["sprint_speed", null, null]]], ["Value", [["war_600", 393.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 328.0, "pa"], ["xwoba_savant", 186.0, "pa"], ["xslg", 259.0, "pa"], ["iso", 229.0, "pa"], ["ev", 51.0, "bip"], ["ev90", 40.0, "bip"], ["gb_pct", 93.0, "bip"], ["pull_air_pct", 147.0, "bip"], ["obp", 370.0, "pa"], ["slg", 392.0, "pa"], ["avg", 518.0, "pa"], ["babip", 470.0, "bip"], ["xwobacon_plus", 133.0, "bip"], ["re24_pa", 416.0, "pa"], ["sq_contact", 206.0, "bat_swings"], ["swing_length", 56.0, "bat_swings"]]], ["Approach", [["whiff_pct", 70.0, "swings"], ["z_swing_pct", 74.0, "iz"], ["swstr_pct", 126.0, "pitches"], ["dv100", 409.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"], ["sra", 501.0, "chances"], ["arm", null, null]]], ["Value", [["war", null, null]]]] },
  "C": { spec: "hitters_C", name: "catchers", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 386.0, "pa"], ["woba", 566.0, "pa"], ["barrel_pct", 82.0, "bip"], ["hard_pct", 78.0, "bip"]]], ["Approach", [["k_pct", 80.0, "pa"], ["bb_pct", 106.0, "pa"], ["chase_pct", 63.0, "oz"]]], ["Glove, arm and legs", [["framing_rate", 5095.0, "called"]]], ["Value", [["war_600", 490.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 399.0, "pa"], ["xwoba_savant", 217.0, "pa"], ["xslg", 350.0, "pa"], ["iso", 295.0, "pa"], ["ev", 62.0, "bip"], ["ev90", 46.0, "bip"], ["gb_pct", 107.0, "bip"], ["pull_air_pct", 116.0, "bip"], ["obp", 343.0, "pa"], ["slg", 594.0, "pa"], ["avg", 657.0, "pa"], ["babip", 699.0, "bip"], ["xwobacon_plus", 148.0, "bip"], ["re24_pa", 626.0, "pa"], ["sq_contact", 297.0, "bat_swings"], ["swing_length", 76.0, "bat_swings"], ["bat_speed", 60.0, "bat_swings"]]], ["Approach", [["whiff_pct", 71.0, "swings"], ["z_swing_pct", 74.0, "iz"], ["swstr_pct", 115.0, "pitches"], ["dv100", 398.0, "pitches"]]], ["Glove, arm and legs", [["framing_runs", 5123.0, "called"], ["framing_savant", null, null], ["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"], ["sprint_speed", null, null]]], ["Value", [["war", null, null]]]] },
  "1B": { spec: "hitters_1B", name: "first basemen", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 519.0, "pa"], ["woba", 473.0, "pa"], ["barrel_pct", 89.0, "bip"], ["hard_pct", 106.0, "bip"], ["bat_speed", 43.0, "bat_swings"]]], ["Approach", [["k_pct", 54.0, "pa"], ["bb_pct", 128.0, "pa"], ["chase_pct", 83.0, "oz"]]], ["Glove, arm and legs", [["sra", 501.0, "chances"]]], ["Value", [["war_600", 478.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 577.0, "pa"], ["xwoba_savant", 232.0, "pa"], ["xslg", 601.0, "pa"], ["iso", 480.0, "pa"], ["ev", 90.0, "bip"], ["ev90", 68.0, "bip"], ["gb_pct", 102.0, "bip"], ["pull_air_pct", 195.0, "bip"], ["obp", 279.0, "pa"], ["slg", 753.0, "pa"], ["avg", 406.0, "pa"], ["babip", 379.0, "bip"], ["xwobacon_plus", 233.0, "bip"], ["re24_pa", 495.0, "pa"], ["sq_contact", 107.0, "bat_swings"], ["swing_length", 47.0, "bat_swings"]]], ["Approach", [["whiff_pct", 79.0, "swings"], ["z_swing_pct", 82.0, "iz"], ["swstr_pct", 160.0, "pitches"], ["dv100", 407.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"], ["sprint_speed", null, null]]], ["Value", [["war", null, null]]]] },
  "2B": { spec: "hitters_2B", name: "second basemen", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 575.0, "pa"], ["woba", 667.0, "pa"], ["barrel_pct", 98.0, "bip"], ["hard_pct", 68.0, "bip"]]], ["Approach", [["k_pct", 62.0, "pa"], ["bb_pct", 160.0, "pa"], ["chase_pct", 66.0, "oz"]]], ["Glove, arm and legs", [["sra", 501.0, "chances"], ["sprint_speed", null, null]]], ["Value", [["war_600", 797.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 584.0, "pa"], ["xwoba_savant", 346.0, "pa"], ["xslg", 352.0, "pa"], ["iso", 280.0, "pa"], ["ev", 81.0, "bip"], ["ev90", 45.0, "bip"], ["gb_pct", 73.0, "bip"], ["pull_air_pct", 130.0, "bip"], ["obp", 456.0, "pa"], ["slg", 479.0, "pa"], ["avg", 389.0, "pa"], ["babip", 424.0, "bip"], ["xwobacon_plus", 181.0, "bip"], ["re24_pa", 644.0, "pa"], ["sq_contact", 265.0, "bat_swings"], ["swing_length", 83.0, "bat_swings"], ["bat_speed", 95.0, "bat_swings"]]], ["Approach", [["whiff_pct", 59.0, "swings"], ["z_swing_pct", 63.0, "iz"], ["swstr_pct", 108.0, "pitches"], ["dv100", 442.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"], ["arm", null, null]]], ["Value", [["war", null, null]]]] },
  "3B": { spec: "hitters_3B", name: "third basemen", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 360.0, "pa"], ["woba", 467.0, "pa"], ["barrel_pct", 64.0, "bip"], ["hard_pct", 63.0, "bip"]]], ["Approach", [["k_pct", 71.0, "pa"], ["bb_pct", 200.0, "pa"], ["chase_pct", 97.0, "oz"]]], ["Glove, arm and legs", [["sra", 501.0, "chances"], ["arm", null, null]]], ["Value", [["war_600", 359.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 354.0, "pa"], ["xwoba_savant", 244.0, "pa"], ["xslg", 294.0, "pa"], ["iso", 217.0, "pa"], ["ev", 64.0, "bip"], ["ev90", 50.0, "bip"], ["gb_pct", 79.0, "bip"], ["pull_air_pct", 102.0, "bip"], ["obp", 492.0, "pa"], ["slg", 377.0, "pa"], ["avg", 615.0, "pa"], ["babip", 444.0, "bip"], ["xwobacon_plus", 139.0, "bip"], ["re24_pa", 447.0, "pa"], ["sq_contact", 232.0, "bat_swings"], ["swing_length", 37.0, "bat_swings"], ["bat_speed", 51.0, "bat_swings"]]], ["Approach", [["whiff_pct", 67.0, "swings"], ["z_swing_pct", 85.0, "iz"], ["swstr_pct", 120.0, "pitches"], ["dv100", 461.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"], ["sprint_speed", null, null]]], ["Value", [["war", null, null]]]] },
  "SS": { spec: "hitters_SS", name: "shortstops", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 413.0, "pa"], ["woba", 460.0, "pa"], ["barrel_pct", 66.0, "bip"]]], ["Approach", [["k_pct", 66.0, "pa"], ["bb_pct", 149.0, "pa"], ["chase_pct", 82.0, "oz"]]], ["Glove, arm and legs", [["sra", 501.0, "chances"], ["arm", null, null], ["sprint_speed", null, null]]], ["Value", [["war_600", 396.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 433.0, "pa"], ["xwoba_savant", 167.0, "pa"], ["xslg", 310.0, "pa"], ["iso", 214.0, "pa"], ["ev", 46.0, "bip"], ["ev90", 64.0, "bip"], ["gb_pct", 109.0, "bip"], ["pull_air_pct", 201.0, "bip"], ["obp", 501.0, "pa"], ["slg", 344.0, "pa"], ["avg", 601.0, "pa"], ["babip", 575.0, "bip"], ["xwobacon_plus", 170.0, "bip"], ["re24_pa", 370.0, "pa"], ["sq_contact", 200.0, "bat_swings"], ["swing_length", 39.0, "bat_swings"], ["hard_pct", 52.0, "bip"], ["bat_speed", 71.0, "bat_swings"]]], ["Approach", [["whiff_pct", 73.0, "swings"], ["z_swing_pct", 64.0, "iz"], ["swstr_pct", 117.0, "pitches"], ["dv100", 417.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"]]], ["Value", [["war", null, null]]]] },
  "CF": { spec: "hitters_CF", name: "centre fielders", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 239.0, "pa"], ["woba", 366.0, "pa"], ["barrel_pct", 57.0, "bip"]]], ["Approach", [["k_pct", 77.0, "pa"], ["bb_pct", 143.0, "pa"], ["chase_pct", 57.0, "oz"]]], ["Glove, arm and legs", [["sra", 355.0, "chances"], ["sprint_speed", null, null], ["arm", null, null]]], ["Value", [["war_600", 392.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 257.0, "pa"], ["xwoba_savant", 148.0, "pa"], ["xslg", 193.0, "pa"], ["iso", 169.0, "pa"], ["ev", 48.0, "bip"], ["ev90", 35.0, "bip"], ["gb_pct", 100.0, "bip"], ["pull_air_pct", 156.0, "bip"], ["obp", 359.0, "pa"], ["slg", 298.0, "pa"], ["avg", 597.0, "pa"], ["babip", 541.0, "bip"], ["xwobacon_plus", 119.0, "bip"], ["re24_pa", 327.0, "pa"], ["sq_contact", 210.0, "bat_swings"], ["swing_length", 60.0, "bat_swings"], ["hard_pct", 58.0, "bip"], ["bat_speed", 61.0, "bat_swings"]]], ["Approach", [["whiff_pct", 75.0, "swings"], ["z_swing_pct", 76.0, "iz"], ["swstr_pct", 139.0, "pitches"], ["dv100", 390.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 355.0, "chances"], ["fielding_runs", 355.0, "chances"]]], ["Value", [["war", null, null]]]] },
  "LF/RF": { spec: "hitters_LFRF", name: "corner outfielders", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 345.0, "pa"], ["woba", 518.0, "pa"], ["barrel_pct", 67.0, "bip"], ["hard_pct", 67.0, "bip"]]], ["Approach", [["k_pct", 85.0, "pa"], ["bb_pct", 137.0, "pa"], ["chase_pct", 71.0, "oz"]]], ["Glove, arm and legs", [["sra", 355.0, "chances"], ["arm", null, null]]], ["Value", [["war_600", 460.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 366.0, "pa"], ["xwoba_savant", 233.0, "pa"], ["xslg", 308.0, "pa"], ["iso", 264.0, "pa"], ["ev", 55.0, "bip"], ["ev90", 41.0, "bip"], ["gb_pct", 99.0, "bip"], ["pull_air_pct", 186.0, "bip"], ["obp", 422.0, "pa"], ["slg", 487.0, "pa"], ["avg", 671.0, "pa"], ["babip", 525.0, "bip"], ["xwobacon_plus", 143.0, "bip"], ["re24_pa", 527.0, "pa"], ["sq_contact", 210.0, "bat_swings"], ["swing_length", 86.0, "bat_swings"], ["bat_speed", 66.0, "bat_swings"]]], ["Approach", [["whiff_pct", 76.0, "swings"], ["z_swing_pct", 66.0, "iz"], ["swstr_pct", 129.0, "pitches"], ["dv100", 380.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 355.0, "chances"], ["fielding_runs", 355.0, "chances"], ["sprint_speed", null, null]]], ["Value", [["war", null, null]]]] },
  "DH": { spec: "hitters_DH", name: "designated hitters", min: {"field": "pa", "value": 200, "unit": "PA"},
    head: [["Bat", [["xwoba_n", 322.0, "pa"], ["woba", 415.0, "pa"], ["barrel_pct", 66.0, "bip"], ["hard_pct", 62.0, "bip"], ["bat_speed", 44.0, "bat_swings"], ["iso", 259.0, "pa"]]], ["Approach", [["k_pct", 87.0, "pa"], ["bb_pct", 148.0, "pa"], ["chase_pct", 101.0, "oz"]]], ["Value", [["war_600", 365.0, "pa"]]]],
    more: [["Bat", [["xwoba_plus", 311.0, "pa"], ["xwoba_savant", 185.0, "pa"], ["xslg", 208.0, "pa"], ["ev", 50.0, "bip"], ["ev90", 36.0, "bip"], ["gb_pct", 113.0, "bip"], ["pull_air_pct", 139.0, "bip"], ["obp", 338.0, "pa"], ["slg", 394.0, "pa"], ["avg", 507.0, "pa"], ["babip", 389.0, "bip"], ["xwobacon_plus", 122.0, "bip"], ["re24_pa", 408.0, "pa"], ["sq_contact", 292.0, "bat_swings"], ["swing_length", 42.0, "bat_swings"]]], ["Approach", [["whiff_pct", 89.0, "swings"], ["z_swing_pct", 94.0, "iz"], ["swstr_pct", 168.0, "pitches"], ["dv100", 424.0, "pitches"]]], ["Glove, arm and legs", [["bsr", null, null], ["oaa", 501.0, "chances"], ["fielding_runs", 501.0, "chances"], ["sprint_speed", null, null]]], ["Value", [["war", null, null]]]] },
  "SP": { spec: "sp", name: "starting pitchers", min: {"field": "bf", "value": 300, "unit": "BF"},
    head: [["Results", [["xwoba_n", 633.0, "bf"], ["xfip", 424.0, "bf"]]], ["Stuff", [["stuff_plus", 860.0, "pitches"], ["pitching_plus", 1209.0, "pitches"], ["fb_velo", 4.0, "fb"]]], ["Missing bats", [["k_pct", 122.0, "bf"], ["csw_pct", 547.0, "pitches"], ["chase_pct", 422.0, "oz"]]], ["Control and contact", [["bb_pct", 321.0, "bf"], ["gb_pct", 89.0, "bip"]]]],
    more: [["Results", [["ra9", 1055.0, "bf"], ["fip", 387.0, "bf"], ["xwoba_plus", 643.0, "bf"], ["xwoba_savant", 321.0, "bf"], ["xra9", 708.0, "bf"], ["war_200", 1837.0, "bf"], ["war", null, null], ["war_x", null, null]]], ["Stuff", [["location_plus", 1199.0, "pitches"], ["fb_ivb", 217.0, "fb"], ["fb_vaa", 228.0, "fb"], ["extension", 129.0, "pitches"]]], ["Missing bats", [["k_bb_pct", 162.0, "bf"], ["whiff_pct", 182.0, "swings"], ["swstr_pct", 351.0, "pitches"]]], ["Control and contact", [["hard_pct", 375.0, "bip"], ["barrel_pct", 847.0, "bip"], ["ev", 260.0, "bip"], ["hr9", 1013.0, "bf"], ["whip", 588.0, "bf"], ["babip_against", 1633.0, "bip"], ["p_start", null, null], ["tto_penalty", 2665.0, "tto3"], ["fb_usage", 495.0, "pitches"], ["br_usage", 364.0, "pitches"], ["os_usage", 289.0, "pitches"]]]] },
  "RP": { spec: "rp", name: "relievers", min: {"field": "bf", "value": 120, "unit": "BF"},
    head: [["Results", [["xwoba_n", 598.0, "bf"]]], ["Stuff", [["pitching_plus", 659.0, "pitches"], ["stuff_plus", 387.0, "pitches"], ["fb_velo", 1.0, "fb"]]], ["Missing bats", [["k_bb_pct", 158.0, "bf"], ["csw_pct", 390.0, "pitches"], ["whiff_pct", 115.0, "swings"], ["chase_pct", 240.0, "oz"]]], ["Control and contact", [["bb_pct", 245.0, "bf"], ["gb_pct", 46.0, "bip"]]]],
    more: [["Results", [["xfip", 398.0, "bf"], ["fip", 364.0, "bf"], ["ra9", 1023.0, "bf"], ["gmli", null, null], ["wpa_li", 1375.0, "bf"], ["xwoba_plus", 573.0, "bf"], ["xra9", 668.0, "bf"], ["war", null, null], ["war_x", null, null]]], ["Stuff", [["location_plus", 575.0, "pitches"], ["fb_ivb", 60.0, "fb"], ["fb_vaa", 100.0, "fb"], ["extension", 42.0, "pitches"]]], ["Missing bats", [["k_pct", 86.0, "bf"], ["swstr_pct", 234.0, "pitches"]]], ["Control and contact", [["hard_pct", 338.0, "bip"], ["barrel_pct", 695.0, "bip"], ["hr9", 788.0, "bf"], ["whip", 487.0, "bf"], ["fb_usage", 182.0, "pitches"], ["br_usage", 150.0, "pitches"], ["os_usage", 101.0, "pitches"]]]] },
  "TEAM": { spec: "teams", name: "MLB clubs", min: {"field": "g", "value": 20, "unit": "games"},
    head: [["Strength", [["rating", null, null], ["baseruns_pct", null, null], ["off_rpg", null, null], ["pit_rpg", null, null], ["def_rpg", null, null]]], ["Batting", [["woba", null, null], ["bb_pct", null, null]]]],
    more: [["Strength", [["pythag", null, null], ["pct", null, null], ["rd", null, null], ["war", null, null]]], ["Batting", [["xwoba_savant", null, null], ["k_pct", null, null], ["barrel_pct", null, null], ["oaa", null, null], ["framing_runs", null, null]]], ["Pitching", [["xwoba_against", null, null], ["woba_against", null, null], ["p_k_bb", null, null], ["p_k_pct", null, null], ["csw_pct", null, null], ["stuff_plus", null, null], ["pitching_plus", null, null], ["p_barrel_pct", null, null]]]] }
};
/* metric labels and one-line explanations: hitters, pitchers */
U.MDESC = { hitter: {"xwoba_n": ["xwOBA+ (park-neutral)", "Expected wOBA from exit velocity, launch angle, hang time and sprint speed, plus walks and strikeouts, re-scored in a standard park."], "woba": ["wOBA", "Weighted on-base average: every way of reaching base, weighted by the runs it is worth."], "barrel_pct": ["Barrel%", "Share of balls in play hit at the speed and angle that most often become extra-base hits."], "hard_pct": ["Hard-hit%", "Share of balls in play hit at 95 mph or harder."], "bat_speed": ["Bat speed", "Average speed of the bat's sweet spot on competitive swings (tracked since 2023)."], "k_pct": ["K%", "Strikeouts per plate appearance."], "bb_pct": ["BB%", "Walks per plate appearance."], "chase_pct": ["Chase%", "How often the batter swings at pitches outside the strike zone."], "sprint_speed": ["Sprint speed", "Top running speed on the fastest runs."], "war_600": ["WAR/600", "Bullpen WAR per 600 plate appearances: batting, baserunning, fielding and position in one number."], "xwoba_plus": ["xwOBA+", "Expected wOBA from how the ball was hit, in the parks actually played in."], "xwoba_savant": ["xwOBA (Savant)", "Statcast's expected wOBA from exit velocity and launch angle."], "xslg": ["xSLG", "Statcast expected slugging from how the ball was hit."], "iso": ["ISO", "Isolated power: extra bases per at-bat."], "ev": ["Exit velocity", "Average speed of balls in play."], "ev90": ["EV90", "90th-percentile exit velocity: how hard the best contact is."], "gb_pct": ["GB%", "Ground balls per ball in play."], "pull_air_pct": ["Pull-air%", "Pulled line drives and fly balls per ball in play."], "obp": ["OBP", "On-base percentage."], "slg": ["SLG", "Slugging percentage."], "avg": ["AVG", "Batting average."], "babip": ["BABIP", "Batting average on balls in play (mostly noise year to year)."], "xwobacon_plus": ["xwOBAcon+", "xwOBA+ on balls in play only."], "re24_pa": ["RE24/PA", "Run expectancy added per plate appearance."], "sq_contact": ["Squared-up%", "Contact with 80 %+ of the attainable exit velocity."], "swing_length": ["Swing length", "How far the bat head travels on each swing."], "whiff_pct": ["Whiff%", "Share of swings that miss."], "z_swing_pct": ["Z-Swing%", "Swings at pitches in the zone."], "swstr_pct": ["SwStr%", "Swinging strikes per pitch seen."], "dv100": ["Decision value /100", "Runs gained per 100 pitches by swing and take choices alone."], "bsr": ["Baserunning runs", "Runs from steals and taking extra bases (a total)."], "oaa": ["OAA", "Outs above average over the season (a total)."], "fielding_runs": ["Fielding runs", "OAA in runs (a total)."], "sra": ["OAA per chance", "Outs above average per chance: how many more plays the fielder makes than an average fielder on the same balls."], "arm": ["Arm strength", "Average speed of the hardest throws from the field."], "war": ["WAR", "Bullpen WAR (a total)."], "framing_rate": ["Framing (strikes added)", "Extra called strikes per called pitch received, against an average catcher on the same pitches, umpire and batter."], "framing_runs": ["Framing runs", "Runs saved by framing over the season (a total: depends on playing time)."], "framing_savant": ["Framing runs (Savant)", "Savant's catcher framing runs, for reference."]},
  pitcher: {"xwoba_n": ["xwOBA+ against (park-neutral)", "Expected wOBA allowed from the contact, walks and strikeouts allowed, in a standard park."], "xfip": ["xFIP", "Fielding-independent pitching with home runs replaced by fly balls at the league rate (RA9 scale)."], "stuff_plus": ["Stuff+", "Quality of the pitches from velocity, movement, spin, release and extension alone."], "pitching_plus": ["Pitching+", "Stuff, location, count and sequencing together, per pitch."], "fb_velo": ["Fastball velocity", "Average speed of the primary fastball."], "k_pct": ["K%", "Strikeouts per batter faced."], "csw_pct": ["CSW%", "Called strikes plus whiffs per pitch."], "chase_pct": ["Chase%", "How often batters chase pitches outside the zone."], "bb_pct": ["BB%", "Walks per batter faced."], "gb_pct": ["GB%", "Ground balls per ball in play (style; fewer home runs)."], "ra9": ["RA9", "All runs allowed per nine innings (the result; noisy from year to year)."], "fip": ["FIP", "Runs per nine from strikeouts, walks, hit batters and home runs only (RA9 scale)."], "xwoba_plus": ["xwOBA+ against", "Expected wOBA allowed in the parks pitched in."], "xwoba_savant": ["xwOBA against (Savant)", "Statcast's expected wOBA allowed."], "xra9": ["xRA9", "Expected runs per nine from xwOBA+ against."], "war_200": ["WAR/200 IP", "Bullpen WAR (runs-allowed based) per 200 innings."], "war": ["WAR", "Bullpen WAR (a total)."], "war_x": ["WAR (xwOBA+)", "Bullpen WAR from expected runs (a total)."], "location_plus": ["Location+", "Value of the pitch location, given count and pitch type."], "fb_ivb": ["Fastball IVB", "Induced vertical break of the fastball (rise against gravity)."], "fb_vaa": ["Fastball VAA", "Vertical approach angle of the fastball at the plate."], "extension": ["Extension", "How far in front of the rubber the ball is released."], "k_bb_pct": ["K-BB%", "Strikeout rate minus walk rate: the single best quick guide to a pitcher."], "whiff_pct": ["Whiff%", "Share of swings against the pitcher that miss."], "swstr_pct": ["SwStr%", "Swinging strikes per pitch."], "hard_pct": ["Hard-hit% allowed", "Balls in play at 95 mph or harder."], "barrel_pct": ["Barrel% allowed", "Barrels per ball in play (unstable for pitchers)."], "ev": ["Exit velocity allowed", "Average speed of balls in play against the pitcher."], "hr9": ["HR/9", "Home runs allowed per nine innings."], "whip": ["WHIP", "Walks plus hits per inning."], "babip_against": ["BABIP against", "Average on balls in play against the pitcher (mostly defence and luck)."], "p_start": ["Pitches/start", "Average pitch count per start."], "tto_penalty": ["TTO penalty", "xwOBA the third time through the order minus the first."], "fb_usage": ["Fastball%", "Share of pitches that are fastballs."], "br_usage": ["Breaking%", "Share of pitches that are breaking balls."], "os_usage": ["Offspeed%", "Share of pitches that are changeups or splitters."], "gmli": ["gmLI", "Average leverage on entering (relievers; 1 = average)."], "wpa_li": ["WPA/LI", "Context-neutral wins added."]},
  team: {"rating": ["Team rating", "Expected run differential per game against an average team: offence + defence + pitching ratings."], "baseruns_pct": ["BaseRuns win%", "The record the team's hits, walks and outs deserved, with the order they came in (sequencing luck) removed."], "off_rpg": ["Offence", "Batting plus baserunning runs above average per game."], "pit_rpg": ["Pitching", "Runs saved per game by the pitchers, from the quality of contact, walks and strikeouts they allowed."], "def_rpg": ["Defence", "Fielding plus catcher framing runs per game."], "woba": ["Team wOBA", "The lineup's weighted on-base average."], "bb_pct": ["Team BB%", "The lineup's walks per plate appearance."], "pythag": ["Pythagorean win%", "Win% expected from runs scored and allowed."], "pct": ["Win%", "Actual winning percentage."], "rd": ["Run differential", "Runs scored minus runs allowed."], "war": ["Total WAR", "Bullpen WAR of all players."], "xwoba_savant": ["Team xwOBA", "Statcast expected wOBA of the lineup."], "k_pct": ["Team K%", "The lineup's strikeouts per plate appearance."], "barrel_pct": ["Team Barrel%", "The lineup's barrels per ball in play."], "oaa": ["Team OAA", "Team outs above average (our model)."], "framing_runs": ["Framing runs", "Catchers' framing runs."], "xwoba_against": ["xwOBA against", "Statcast expected wOBA allowed by the staff."], "woba_against": ["wOBA against", "wOBA allowed by the staff."], "p_k_bb": ["Staff K-BB%", "The staff's strikeout rate minus walk rate."], "p_k_pct": ["Staff K%", "The staff's strikeouts per batter faced."], "csw_pct": ["Staff CSW%", "The staff's called strikes plus whiffs per pitch."], "stuff_plus": ["Staff Stuff+", "Pitch-weighted Stuff+ of the staff."], "pitching_plus": ["Staff Pitching+", "Pitch-weighted Pitching+ of the staff."], "p_barrel_pct": ["Barrel% allowed", "Barrels allowed per ball in play."]} };
/* @@SETS-END@@ */

U.ROLE_OF_POS = { C: 'C', '1B': '1B', '2B': '2B', '3B': '3B', SS: 'SS', CF: 'CF', LF: 'LF/RF', RF: 'LF/RF', OF: 'LF/RF', 'LF/RF': 'LF/RF', DH: 'DH', TWP: 'DH' };
/* The set (peer group) for a catalogue row or a player file's current block: pitchers by role, hitters by position. */
U.setFor = (kind, row) => {
  if (kind === 'pitcher') return (row && row.role === 'RP') ? 'RP' : 'SP';
  const k = U.ROLE_OF_POS[String((row && row.pos) || '').toUpperCase()];
  return k || 'ALL';
};
/* The minimum sample, prorated by team games in season (spec: 200 PA x team_games / 162). */
U.floorOf = (setKey, teamGames) => {
  const s = U.SETS[setKey] || {};
  const m = s.min || {};
  if (!isNum(m.value)) return null;
  const tg = isNum(teamGames) && teamGames > 0 ? Math.min(162, teamGames) : 162;
  return { field: m.field, unit: m.unit, value: Math.max(1, Math.round(m.value * tg / 162)), full: m.value };
};
U.sampleOf = (row, field) => {
  if (!row || !field) return null;
  const n = row.n || {}, v = row.values || {};
  if (isNum(n[field])) return Number(n[field]);
  if (isNum(v[field])) return Number(v[field]);
  if (isNum(row[field])) return Number(row[field]);
  return null;
};
U.meets = (row, setKey, teamGames) => {
  const fl = U.floorOf(setKey, teamGames);
  if (!fl) return true;
  const n = U.sampleOf(row, fl.field);
  return isNum(n) && n >= fl.value;
};
U.peerName = setKey => (U.SETS[setKey] || {}).name || 'peers';
/* Fielding and framing are ranked only inside the position group, and only past their own floors (spec: fielding 150
   chances, framing 2,000 called pitches, prorated like the PA floor). */
U.FIELDING = { sra: 1, arm: 1, oaa: 1, fielding_runs: 1, oaa_savant: 1, framing_rate: 1, framing_runs: 1, framing_savant: 1 };
U.EXTRA_MIN = { sra: ['chances', 150], oaa: ['chances', 150], fielding_runs: ['chances', 150], framing_rate: ['called', 2000], framing_runs: ['called', 2000], framing_savant: ['called', 2000] };
U.metricOk = (row, id, setKey, teamGames) => {
  if (U.FIELDING[id] && (!setKey || setKey === 'ALL')) return false;
  const x = U.EXTRA_MIN[id];
  if (!x) return true;
  const n = U.sampleOf(row, x[0]);
  const tg = isNum(teamGames) && teamGames > 0 ? Math.min(162, teamGames) : 162;
  return isNum(n) && n >= Math.round(x[1] * tg / 162);
};
/* "691 PA · 452 balls in play · peers: designated hitters with 200+ PA" */
U.sampleLine = (row, kind, setKey, teamGames) => {
  const fl = U.floorOf(setKey, teamGames);
  const n = (row && row.n) || {};
  const bits = kind === 'pitcher'
    ? [isNum(n.bf) ? Math.round(n.bf) + ' BF' : '', isNum(n.ip) ? BP.fmtIP(n.ip) + ' IP' : '', isNum(n.pitches) ? QK.fmt.num(n.pitches) + ' pitches' : '']
    : [isNum(n.pa) ? n.pa + ' PA' : '', isNum(n.bip) ? n.bip + ' balls in play' : '', isNum(n.chances) ? n.chances + ' chances' : ''];
  return bits.filter(Boolean).join(' · ') + (fl ? ' · peers need ' + fl.value + '+ ' + fl.unit : '');
};
/* glossary.json -> { hitter: {key: entry}, pitcher: {key: entry} } (label, fmt, lower, desc) */
let GLOSS = null;
U.gloss = () => {
  if (GLOSS) return GLOSS;
  GLOSS = BP.load('glossary.json').then(g => {
    const out = { hitter: {}, pitcher: {}, team: {} };
    ((g && g.groups) || []).forEach(gr => (gr.entries || []).forEach(e => { const k = e.kind === 'pitcher' ? 'pitcher' : e.kind === 'team' ? 'team' : 'hitter'; if (!out[k][e.key]) out[k][e.key] = e; }));
    return out;
  });
  return GLOSS;
};
U.metaOf = (kind, id, gl) => {
  const g = ((gl || {})[kind] || {})[id] || {};
  const d = (U.MDESC[kind] || {})[id] || [];
  const o = U.ours ? U.ours(id) : null, tip = d[1] || g.desc || '';
  return { key: id, label: d[0] || g.label || id, tip: tip + (o ? (tip ? ' ' : '') + 'Our model: ' + o.name + '.' : ''), fmt: g.fmt, lower: !!g.lower, ours: o };
};
U.fmtBy = (meta, v) => (isNum(v) ? BP.fmtVal(v, (meta && meta.fmt) || '2') : '—');
/* A plain-English line under each metric on the percentile meters. */
U.SUB = {
  hitter: { xwoba_n: 'What the contact deserved, walks and strikeouts in, any park.', woba: 'Every way of reaching base, weighted by the runs it is worth.',
    barrel_pct: 'Balls hit at the speed and angle that become extra-base hits.', hard_pct: 'Balls in play at 95 mph or harder.', bat_speed: 'How fast the sweet spot moves on a real swing.',
    k_pct: 'Strikeouts per trip to the plate (lower is better).', bb_pct: 'Walks per trip to the plate.', chase_pct: 'Swings at pitches off the plate (lower is better).',
    sprint_speed: 'Top speed on the fastest runs.', war_600: 'Wins added per full season of trips to the plate.', sra: 'Extra outs made per chance against an average fielder.',
    arm: 'Speed of the hardest throws.', framing_rate: 'Extra strikes stolen per called pitch.', iso: 'Extra bases per at-bat: raw power.' },
  pitcher: { xwoba_n: 'What the contact allowed deserved, any park (lower is better).', xfip: 'Runs per nine from strikeouts, walks and fly balls (lower is better).',
    stuff_plus: 'The pitches alone: velocity, movement, spin. 100 is average.', pitching_plus: 'Stuff plus where the pitches go and the count.', fb_velo: 'Average fastball speed.',
    k_pct: 'Strikeouts per batter.', csw_pct: 'Called strikes and whiffs per pitch.', chase_pct: 'How often batters chase off the plate.', bb_pct: 'Walks per batter (lower is better).',
    gb_pct: 'Ground balls per ball in play: fewer home runs.', k_bb_pct: 'Strikeouts minus walks: the best quick guide to a pitcher.', whiff_pct: 'Swings that miss.' }
};
U.UNIT = { pa: 'PA', bf: 'batters faced', bip: 'balls in play', pitches: 'pitches', swings: 'swings', oz: 'pitches outside the zone', iz: 'pitches in the zone', fb: 'fastballs',
  bat_swings: 'tracked swings', chances: 'chances', called: 'called pitches', tto3: 'batters faced a third time', games: 'games' };
/* The type a player's best metric suggests (compare verdicts). */
U.ARCHETYPE = { hitter: { xwoba_n: 'The hitter', woba: 'The on-base machine', barrel_pct: 'The slugger', hard_pct: 'The hard hitter', bat_speed: 'The bat speed', k_pct: 'The contact hitter',
    bb_pct: 'The patient one', chase_pct: 'The disciplined eye', sprint_speed: 'The burner', war_600: 'The all-rounder', sra: 'The glove', arm: 'The cannon', framing_rate: 'The framer', iso: 'The power bat' },
  pitcher: { xwoba_n: 'The run preventer', xfip: 'The craftsman', stuff_plus: 'The nasty stuff', pitching_plus: 'The complete pitcher', fb_velo: 'The flamethrower', k_pct: 'The strikeout artist',
    csw_pct: 'The strike thrower', chase_pct: 'The deceiver', bb_pct: 'The control artist', gb_pct: 'The groundballer', k_bb_pct: 'The dominator', whiff_pct: 'The bat-misser' } };
/* Percentile-card groups for one player (a catalogue row or the player file's current hitting / pitching block):
   pct_role (his position or role pool) only; a metric without a value or a percentile is left out. prev: last
   season's percentiles in the same peer group (the hollow ring on the v3 rail), or null. */
U.pctGroups = (row, kind, setKey, gl, which, teamGames, prev) => {
  const set = U.SETS[setKey] || U.SETS[kind === 'pitcher' ? 'SP' : 'ALL'] || {};
  /* spec: pct_role for the position and role groups, pct for "All hitters" */
  const pr = (row && (setKey === 'ALL' ? row.pct : row.pct_role)) || {}, vals = (row && row.values) || {};
  return (set[which || 'head'] || []).map(g => ({
    label: g[0],
    rows: g[1].map(x => {
      const id = x[0], pc = pr[id];
      if (!isNum(pc) || !isNum(vals[id]) || !U.metricOk(row, id, setKey, teamGames)) return null;
      const m = U.metaOf(kind, id, gl);
      const n = x[1] && x[2] ? U.sampleOf(row, x[2]) : null;
      return { key: id, label: m.label, sub: (U.SUB[kind] || {})[id] || '', pctl: pc, prev: prev && isNum(prev[id]) ? prev[id] : null, value: U.fmtBy(m, vals[id]),
        tip: m.tip + (isNum(x[1]) && x[2] ? ' Settles at about ' + Math.round(x[1]) + ' ' + (U.UNIT[x[2]] || x[2]) + '.' : ''), early: isNum(n) && n < x[1] };
    }).filter(Boolean)
  })).filter(g => g.rows.length);
};
/* "How sure are we?" at the top of a Model page (kit v4: "We say it. Then we check it."): <L>/calibration.json read with QK.calib.find, rendered with
   QK.howSure into a section put first in el; nothing is shown when the level has no game backtest (Triple-A today).
   o.doing (round 6, the "How we're doing" tab): QK.doing instead, our recent record (index.json digest.record) over the same chart. */
U.howSureTop = (el, L, o) => {
  if (!el) return;
  const box = document.createElement('section');
  box.className = 'qk-section bp-sure';
  box.hidden = true;
  el.insertBefore(box, el.firstChild);
  BP.load(BP.lpath('calibration.json', L)).then(cj => {
    if (!BP.ok(cj) || !QK.calib.find(cj) || !box.isConnected) return;
    const ss = Object.keys((cj.games || {}).seasons || {}).sort();
    box.hidden = false;
    if (o && o.doing && QK.doing) {
      const idx = BP.index() || {}, dig = L === 'mlb' ? idx.digest : ((BP.levelInfo(L) || {}).digest);
      QK.doing(box, { record: (dig || {}).record || null, calibration: cj, league: BP.levelName(L), span: ss.length ? ss[0] + ' to ' + ss[ss.length - 1] : '', subject: 'the home team',
        sub: 'Our favourites’ record over the last week, then every pre-game forecast since ' + (ss[0] || 'the first season') + ', made walk-forward from what was known before the first pitch, grouped by our chance for the home team. When the two match, our numbers mean what they say.' });
      return;
    }
    box.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every pre-game forecast since ' + (ss[0] || 'the first season') + ', made walk-forward from what was known before the first pitch, grouped by our chance for the home team, against how often the home team won. When the two bars match, our numbers mean what they say.' }) + '<div></div>';
    QK.howSure(box.lastChild, { calibration: cj, league: BP.levelName(L), span: ss.length ? ss[0] + ' to ' + ss[ss.length - 1] : '', subject: 'the home team' });
  });
};
/* The flat metric list of a set: [[id, m50, field], ...] */
U.flat = (setKey, which) => {
  const out = [];
  ((U.SETS[setKey] || {})[which || 'head'] || []).forEach(g => g[1].forEach(x => out.push(x)));
  return out;
};

/* ── our models (round 5): the spec's `our_models` registry through the kit's QK.spec (assets/qk/metrics/baseball.labels.json)
   U.specReady() -> Promise of the catalogue (null when missing); U.ours(key) -> { name, about } | null; U.oursTag(key, short)
   the cobalt "Our model" tag; U.label(kind, key, fallback) the spec's display name (U.MDESC, per kind) else the payload's;
   U.headIds(kind) the spec's headline ids for hitters (every position group) or pitchers (starters, then relievers);
   U.metricOpts(metrics, sel, kind) a metric picker: "Our models", "Box score · headline", then the payload's groups;
   U.tagHeads(host, { colKey: metricKey }) the tag on a QK.table head (kept through re-sorts); U.oursNote(kind, keys) the
   cobalt explain strip naming the models behind the keys that are ours. */
U.SPEC = null;
U.specReady = () => (window.QK && QK.spec ? QK.spec.load('baseball').then(c => { if (c) U.SPEC = c; return c; }) : Promise.resolve(null));
U.specReady();
U.ours = key => (U.SPEC ? U.SPEC.ours(key) : null);
U.oursTag = (key, short) => { const o = U.ours(key); return o ? QK.ours({ short: !!short, model: o.name, about: o.about }) : ''; };
U.label = (kind, key, fallback) => {
  const d = (U.MDESC[kind === 'pitcher' ? 'pitcher' : kind === 'team' ? 'team' : 'hitter'] || {})[key];
  return d && d[0] ? d[0] : String(fallback || key).replace(/ \(ours\)$/, '');
};
U.headIds = (kind, setKey) => {
  let keys = kind === 'pitcher' ? ['SP', 'RP'] : kind === 'team' ? ['TEAM'] : ['ALL', 'C', '1B', '2B', '3B', 'SS', 'CF', 'LF/RF', 'DH'];
  if (setKey && keys.indexOf(setKey) >= 0) keys = [setKey].concat(keys.filter(x => x !== setKey));   // o.set: one group's headline first (the Lab's peer group)
  const out = [];
  keys.forEach(k => U.flat(k, 'head').forEach(x => { if (out.indexOf(x[0]) < 0) out.push(x[0]); }));
  return out;
};
U.metricOpts = (metrics, sel, kind, o) => {
  o = o || {};
  const heads = U.headIds(kind, o.set), pos = key => { const i = heads.indexOf(key); return i < 0 ? 999 : i; };
  const opt = m => '<option value="' + esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + esc(U.label(kind, m.key, m.label)) + (m.lower ? ' ↓' : '') + '</option>';
  const ms = (metrics || []).map((m, i) => ({ m: m, i: i }));
  const ours = ms.filter(x => U.ours(x.m.key)).sort((a, b) => (pos(a.m.key) - pos(b.m.key)) || (a.i - b.i));
  const head = ms.filter(x => !U.ours(x.m.key) && pos(x.m.key) < 999).sort((a, b) => pos(a.m.key) - pos(b.m.key));
  const rest = ms.filter(x => !U.ours(x.m.key) && pos(x.m.key) === 999);
  const grp = (label, list) => (list.length ? '<optgroup label="' + esc(label) + '">' + list.map(x => opt(x.m)).join('') + '</optgroup>' : '');
  let h = grp('Our models', ours) + grp('Box score · headline', head);
  const names = [];
  rest.forEach(x => { const g = x.m.group || 'Other'; if (names.indexOf(g) < 0) names.push(g); });
  names.forEach(g => { h += grp('Box score · ' + g, rest.filter(x => (x.m.group || 'Other') === g)); });
  return h;
};
U.tagHeads = (host, map) => {
  if (!host) return;
  const apply = () => Object.keys(map || {}).forEach(col => {
    const tag = U.oursTag(map[col], true);
    if (!tag) return;
    host.querySelectorAll('th[data-k="' + col + '"]').forEach(th => {
      if (th.querySelector('.qk-ours')) return;
      const b = th.querySelector('button') || th;
      b.insertAdjacentHTML('beforeend', tag);
    });
  });
  apply();
  if (host._oursObs) host._oursObs.disconnect();
  if (window.MutationObserver) { host._oursObs = new MutationObserver(apply); host._oursObs.observe(host, { childList: true, subtree: true }); }
};
U.oursNote = (kind, keys) => {
  const seen = {}, parts = [];
  (keys || []).forEach(k => {
    const o = U.ours(k);
    if (!o || seen[k]) return;
    seen[k] = 1;
    const d = (U.MDESC[kind === 'pitcher' ? 'pitcher' : kind === 'team' ? 'team' : 'hitter'] || {})[k];
    parts.push('<b>' + esc(U.label(kind, k, k)) + '</b> comes from our ' + esc(o.name.charAt(0).toLowerCase() + o.name.slice(1)) + ': ' + esc((d && d[1]) || o.about));
  });
  return parts.length ? QK.oursExplain(parts.join(' '), { title: 'Our model.' }) : '';
};

})(window.BP);
