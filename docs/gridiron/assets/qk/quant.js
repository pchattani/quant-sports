/* The Quant — shared UI kit, v4 "Broadcast" (dark only; every v1, v2 and v3 call still works). Framework-free; one
 * global, QK. Spec: docs/_design/STYLE_GUIDE.md; moving a page to v4: docs/_design/MIGRATION_V4.md.
 * Older-browser rule shared with the sites: no optional chaining, no nullish coalescing.
 *
 *   QK.SPORTS / QK.sport(key)          the sites shown in the switcher: names, URLs, accents, icons
 *   QK.ALL_SPORTS                      every site, including ones not launched yet (pending: true)
 *   QK.SECTIONS / QK.sections(key)     the information architecture every sport uses
 *   QK.shell(opts)                     top bar + sport switcher + section nav + search + footer
 *   QK.theme.get/set/toggle/onChange   kept for old callers; v3 is dark only (get() is always 'dark')
 *   QK.now()                           the page clock (?asof=<ISO> pins it for previews of an old snapshot)
 *   QK.table(el, spec)                 sortable sticky-header table, percentile chips, raw/year columns
 *   QK.tableHTML(cols, rows, o)        static table HTML; QK.sortable(el) wires header sorting + row links
 *   QK.tabs(root) QK.seg(root, cb) QK.chips(root, cb)
 *   QK.matchCard(g) QK.tick(g) QK.probBar() QK.mvm()   game rendering (v1)
 *   QK.teamMark(t) QK.color.*          team colours with contrast checks
 *   QK.spark(values, opts)             inline SVG sparkline (no chart library)
 *   QK.skeleton(kind, n) QK.empty(title, text)  QK.tooltips()  QK.search.open()
 *   QK.fmt.*                           numbers, percents, odds, local times
 * v2 builders (return HTML strings unless noted), restyled for Matchday:
 *   QK.sectionHead(o)  QK.ticker(games, o)  QK.gameCard(g, o)  QK.wpBar(pL, pD, pR, tL, tR, o)  QK.formDots(f)
 *   QK.chanceBar(r, o) QK.chances(rows, o)  QK.statTile(o)  QK.stats(list)  QK.playerHeader(o)  QK.pctCard(o)
 *   QK.leaderboard(el, spec) (renders)      QK.compareView(o)  QK.matchupBar(o)  QK.keys(items)  QK.tag(text, cls)
 *   QK.pctColor(p)  QK.pctInk(p)           the percentile scale (cold -> hot) as a colour and its text ink
 * v3 Matchday builders (HTML strings unless noted):
 *   QK.note(html) QK.aside(text) QK.mark(text)          the "i" explainer, the italic aside, the highlighter
 *   QK.greeting(o) QK.greet()                           the greeting hero; "Good morning / afternoon / evening"
 *   QK.featureCard(g, o)                                a marquee or live game for the hero, with a sticker
 *   QK.watchGrid(games, o) QK.whyLine(g) QK.watchScore(g)   "What to watch": game cards with one-line reasons
 *   QK.hotRow(items) QK.statOfDay(s, o)                 "Who's hot" (swipeable on phones); stat of the day
 *   QK.newHere(o)                                       "New here? Three things to know"
 *   QK.howSure(el, o) (renders) QK.calib.find(json)     "How sure are we?" from a site's calibration.json
 *   QK.pctRail(o) QK.pctKey(o)                          the Notebook slider rail with a last-season ring
 *   QK.shortVersion(o)                                  "The short version" (player pages)
 *   QK.scorebug(g, o)                                   the broadcast score bug for live games
 *   QK.previewCard(g, o)                                the game-page hero: away "at" home, our chance, factors
 *   QK.verdicts(items)                                  compare verdicts: "The volume shooter", one line each
 * v4 Broadcast (every builder above now draws the Broadcast look; new pieces):
 *   QK.splitHero(g, o)                                  the diagonal two-team hero with the black chance foot
 *   QK.explain(html, o)                                 the "What's that number?" strip (volt rule on the left)
 *   QK.band(html, o)                                    a full-bleed black section (the power list)
 *   QK.statStrip(list)                                  the black strip of big numbers under a hero
 *   QK.meter(p, o)                                      the LED segmented percentile meter (20 segments, ▼ last season)
 *   QK.outlineNum(n, o) QK.longName(name, max)          the outlined number; Barlow Condensed for long names
 *   QK.color.deep / block / blockPair / markOutline     block contrast (white type >= 4.5:1) and the team-colour rules
 *   QK.scorebug(g, { size: 'xl' })                      the scoreboard bug: both team blocks, the start or the clock
 *   QK.spec.load(sport) QK.ours(o) QK.oursExplain(html)  the spec's labels (<sport>.labels.json) and the "Our model" tag
 * Round 6 (the hub experience; the market quiet beside ours):
 *   QK.gameCard / previewCard / scorebug(xl) / ticker with market: 'quiet'   the market small and grey, source on hover
 *   QK.marketSource(src) QK.marketSides(g) QK.marketGap(g) QK.marketMark(g) QK.marketLine(g)   the quiet market's parts
 *   QK.storyCards(items, o)                             fan story cards: breakouts, surprises, records in reach
 *   QK.spotlight(o)                                     a player or team spotlight with deep stats and a season line
 *   QK.doing(el, o) (renders)                           "How we're doing" for the Model page: the record + QK.howSure */
(function (root) {
'use strict';

var QK = root.QK || {};
QK.version = '4.1.0';

/* ─────────────────────────────────────── helpers */
function esc(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function isNum(x) { return typeof x === 'number' && isFinite(x); }
function $(sel, ctx) { return (ctx || document).querySelector(sel); }
function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
function h(html) { var t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function store(key, val) {
  try {
    if (val === undefined) return root.localStorage.getItem(key);
    if (val === null) root.localStorage.removeItem(key); else root.localStorage.setItem(key, val);
  } catch (e) { /* private mode, blocked storage: the page still works */ }
  return null;
}
function cssVar(name, el) { return getComputedStyle(el || document.documentElement).getPropertyValue(name).trim(); }
QK.esc = esc; QK.isNum = isNum; QK.$ = $; QK.$$ = $$; QK.h = h; QK.cssVar = cssVar; QK.store = store;

/* ─────────────────────────────────────── the page clock */
/* QK.now() is Date.now(), unless the page URL carries ?asof=<ISO time>: then every "today", "live" and "ago" on the
 * page is read against that moment. It exists for previews and screenshots of an older local snapshot; the live
 * sites never pass it. */
var ASOF = (function () {
  try { var m = /[?&]asof=([^&#]+)/.exec((root.location && root.location.search) || ''); var t = m ? Date.parse(decodeURIComponent(m[1])) : NaN; return isFinite(t) ? t : null; } catch (e) { return null; }
})();
QK.now = function () { return ASOF !== null ? ASOF : Date.now(); };
QK.asof = function () { return ASOF; };

/* ─────────────────────────────────────── format */
var fmt = {
  num: function (x, d) { return isNum(x) ? x.toLocaleString('en-GB', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }) : '—'; },
  pct: function (p, d) {
    if (!isNum(p)) return '—';
    var v = p * 100;
    if (d === undefined) d = (v > 0 && v < 1) || (v > 99 && v < 100) ? 1 : 0;
    if (v > 0 && v < 0.1) return '<0.1%';
    return v.toFixed(d) + '%';
  },
  signed: function (x, d) { return isNum(x) ? (x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x).toFixed(d === undefined ? 1 : d) : '—'; },
  pp: function (x) { return isNum(x) ? (x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x * 100).toFixed(0) + ' pts' : '—'; },
  american: function (p) { if (!isNum(p) || p <= 0 || p >= 1) return '—'; return p >= 0.5 ? '−' + Math.round(100 * p / (1 - p)) : '+' + Math.round(100 * (1 - p) / p); },
  decimal: function (p) { return isNum(p) && p > 0 ? (1 / p).toFixed(2) : '—'; },
  /* one convention on every site (STYLE_GUIDE §8): en-GB, 24-hour, in the viewer's own time zone: "16:00",
   * "Mon 19 Oct"; never the browser locale's "04:00 PM" / "Mon, Oct 19" */
  date: function (iso, opts) { var d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d.toLocaleDateString('en-GB', opts || { weekday: 'short', day: 'numeric', month: 'short' }).replace(/,/g, '') : '—'; },
  time: function (iso) { var d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false }) : ''; },
  dayKey: function (iso) { var d = new Date(iso); return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); },
  relDay: function (iso) {
    var d = new Date(iso); if (isNaN(d)) return '';
    var t = new Date(QK.now()); t.setHours(0, 0, 0, 0);
    var x = new Date(d); x.setHours(0, 0, 0, 0);
    var n = Math.round((x - t) / 864e5);
    return n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n === -1 ? 'Yesterday' : fmt.date(iso);
  },
  ago: function (iso) {
    var s = (QK.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(s)) return '';
    if (s < 90) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  },
  initials: function (name) {
    var p = String(name || '?').replace(/[^A-Za-zÀ-ÿ0-9 ]/g, '').trim().split(/\s+/);
    return (p.length > 1 ? p[0][0] + p[p.length - 1][0] : String(p[0]).slice(0, 3)).toUpperCase();
  }
};
QK.fmt = fmt;

/* ─────────────────────────────────────── colour + contrast (WCAG 2.x relative luminance) */
var color = {
  parse: function (hex) {
    var m = String(hex || '').trim().replace('#', '');
    if (m.length === 3) m = m[0] + m[0] + m[1] + m[1] + m[2] + m[2];
    if (!/^[0-9a-f]{6}$/i.test(m)) return null;
    return [parseInt(m.slice(0, 2), 16), parseInt(m.slice(2, 4), 16), parseInt(m.slice(4, 6), 16)];
  },
  hex: function (rgb) { return '#' + rgb.map(function (v) { return ('0' + Math.max(0, Math.min(255, Math.round(v))).toString(16)).slice(-2); }).join(''); },
  lum: function (hex) {
    var c = color.parse(hex); if (!c) return 0;
    var a = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
  },
  contrast: function (a, b) { var x = color.lum(a), y = color.lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); },
  mix: function (a, b, t) { var x = color.parse(a), y = color.parse(b); if (!x || !y) return a; return color.hex([0, 1, 2].map(function (i) { return x[i] + (y[i] - x[i]) * t; })); },
  /* Nudge a team colour toward white (dark theme) or black (light theme) until it reaches
   * `min` contrast against the surface. Team identity survives; a navy on a near-black card
   * stops disappearing. 3:1 is the WCAG non-text minimum used for marks and bars. */
  ensure: function (hex, surface, min) {
    min = min || 3;
    if (!color.parse(hex)) return hex;
    if (color.contrast(hex, surface) >= min) return hex;
    /* step HSL lightness (hue and saturation kept, so a navy becomes a brighter blue, not grey) */
    var hsl = color.toHsl(hex), up = color.lum(surface) < 0.3;
    if (up && hsl[1] > 0.15) hsl[1] = Math.max(hsl[1], 0.55);
    for (var i = 1; i <= 40; i++) {
      var l = up ? hsl[2] + i * 0.02 : hsl[2] - i * 0.02;
      if (l < 0 || l > 1) break;
      var c = color.fromHsl([hsl[0], hsl[1], l]);
      if (color.contrast(c, surface) >= min) return c;
    }
    return up ? '#ffffff' : '#000000';
  },
  toHsl: function (hex) {
    var c = color.parse(hex).map(function (v) { return v / 255; });
    var mx = Math.max(c[0], c[1], c[2]), mn = Math.min(c[0], c[1], c[2]), l = (mx + mn) / 2, d = mx - mn, hh = 0, ss = 0;
    if (d) {
      ss = d / (1 - Math.abs(2 * l - 1));
      hh = mx === c[0] ? ((c[1] - c[2]) / d) % 6 : mx === c[1] ? (c[2] - c[0]) / d + 2 : (c[0] - c[1]) / d + 4;
      hh *= 60; if (hh < 0) hh += 360;
    }
    return [hh, ss, l];
  },
  fromHsl: function (x) {
    var hh = x[0], ss = x[1], l = x[2], k = (1 - Math.abs(2 * l - 1)) * ss, xx = k * (1 - Math.abs((hh / 60) % 2 - 1)), m = l - k / 2, r;
    r = hh < 60 ? [k, xx, 0] : hh < 120 ? [xx, k, 0] : hh < 180 ? [0, k, xx] : hh < 240 ? [0, xx, k] : hh < 300 ? [xx, 0, k] : [k, 0, xx];
    return color.hex(r.map(function (v) { return (v + m) * 255; }));
  },
  /* Can two team colours sit side by side (a win-probability bar, two lines)? v2: yes when they differ in lightness
   * (contrast >= 1.6) or clearly in hue (60 degrees or more) without being a red-green pair, the pair colour-blind
   * viewers confuse most. v1 used lightness only, which sent every red-v-blue game to the fallback colours. */
  distinct: function (a, b) {
    if (!color.parse(a) || !color.parse(b)) return true;
    if (color.contrast(a, b) >= 1.6) return true;
    var x = color.toHsl(a), y = color.toHsl(b);
    if (x[1] < 0.2 || y[1] < 0.2) return false;
    var d = Math.abs(x[0] - y[0]); d = Math.min(d, 360 - d);
    var red = function (h) { return h >= 330 || h <= 40; }, green = function (h) { return h >= 70 && h <= 170; };
    if ((red(x[0]) && green(y[0])) || (green(x[0]) && red(y[0]))) return false;
    return d >= 60;
  },
  /* Ink (black or white) that reads on a team-coloured fill: whichever has more contrast. */
  /* pure black for the dark ink: at the mid-tones where white and black tie, black clears 4.58:1 (near-black only 4.43) */
  ink: function (bg) { return color.contrast(bg, '#ffffff') >= color.contrast(bg, '#000000') ? '#ffffff' : '#000000'; },
  surface: function () { return cssVar('--s-1') || '#14171d'; },
  /* A team colour ready for a chart mark on the current theme. */
  team: function (hex) { return color.parse(hex) ? color.ensure(hex, color.surface(), 3) : cssVar('--c-other'); },

  /* ── v4 Broadcast: team colours as big blocks ──────────────────────────────────────────────────────────────
   * deep(hex, min): the colour darkened (same hue, 8% a step) until white type on it clears `min` (4.5:1, WCAG AA
   * for text). Every team block carrying white type goes through it. */
  deep: function (hex, min) {
    var c = color.parse(hex); if (!c) return hex;
    min = min || 4.6;   /* 4.5:1 with a margin, so a site's off-white type still clears AA */
    for (var n = 0; n < 32 && color.contrast(color.hex(c), '#ffffff') < min; n++) c = c.map(function (v) { return v * 0.92; });
    return color.hex(c);
  },
  /* pale(hex): a kit too light to carry white type without turning muddy (white, silver, cream, pale yellow). */
  pale: function (hex) { return !!color.parse(hex) && color.lum(hex) > 0.7; },
  /* block(hex) -> { bg, ink, edge }: a team colour as a block with white type.
   *   a normal kit: bg = deep(hex) (white >= 4.5:1);
   *   a pale kit (the pale-kit rule): bg = slate, edge = the kit colour (a 6 px rule along the block's foot);
   *   a kit that disappears into the near-black page (navy, black): bg = the kit, edge = the kit lifted to 3:1;
   *   no colour: the slate neutral. ink is always white. */
  block: function (hex) {
    var slate = cssVar('--slate') || '#3a4150';
    if (!color.parse(hex)) return { bg: slate, ink: '#ffffff', edge: null, none: true };
    if (color.pale(hex)) return { bg: slate, ink: '#ffffff', edge: hex, pale: true };
    var bg = color.deep(hex);
    var page = cssVar('--bg') || '#0a0c10';
    return { bg: bg, ink: '#ffffff', edge: color.contrast(bg, page) < 1.5 ? color.ensure(hex, page, 3) : null };
  },
  /* blockPair(a, b, o) -> [blockA, blockB] for two sides shown together (a hero, a bug, a tale of the tape). a and b
   * are teams { colour, alt } or hex strings. Rules (STYLE_GUIDE §3):
   *   1. each side takes its team colour as a block (block());
   *   2. two blocks that clash (QK.color.distinct, or the same kit: F1 team-mates, a derby in one colour) - the second
   *      side takes its alternate colour (team.alt), else the slate neutral with its kit as the edge;
   *   3. no colour at all (tennis players, football clubs without one): the side we favour (o.fav: 'a' | 'b') is
   *      cobalt, the other slate; with no favourite, left cobalt, right slate. */
  blockPair: function (a, b, o) {
    o = o || {};
    var ha = typeof a === 'string' ? a : (a && a.colour), hb = typeof b === 'string' ? b : (b && b.colour);
    var alt = b && typeof b === 'object' ? b.alt : null;
    var cob = { bg: cssVar('--signal-deep') || '#5a69b7', ink: '#ffffff', edge: null, ours: true };
    var A = color.block(ha), B = color.block(hb);
    if (A.none && B.none) return o.fav === 'b' ? [color.block(null), cob] : [cob, color.block(null)];
    /* one side without a colour: cobalt if it is the side we favour, else the slate neutral */
    if (A.none) A = o.fav === 'a' ? cob : A;
    if (B.none) B = o.fav === 'b' ? cob : B;
    /* two blocks are told apart by lightness (1.4:1) or by hue (50 degrees, not red v green); deepened kits lose
     * HSL saturation (a lilac becomes a dusky purple), so the grey floor here is 0.1, not distinct()'s 0.2 */
    var apart = function (p, q) {
      if (!color.parse(p) || !color.parse(q)) return true;
      if (color.contrast(p, q) >= 1.4) return true;
      var x = color.toHsl(p), y = color.toHsl(q);
      if (x[1] < 0.1 || y[1] < 0.1) return false;
      var dh = Math.abs(x[0] - y[0]); dh = Math.min(dh, 360 - dh);
      var red = function (h) { return h >= 330 || h <= 40; }, green = function (h) { return h >= 70 && h <= 170; };
      if ((red(x[0]) && green(y[0])) || (green(x[0]) && red(y[0]))) return false;
      return dh >= 50;
    };
    var clash = function (x, y) { return String(x.bg).toLowerCase() === String(y.bg).toLowerCase() || (x.edge && y.edge && String(x.edge).toLowerCase() === String(y.edge).toLowerCase()) || !apart(x.bg, y.bg); };
    if (clash(A, B)) {
      var B2 = color.parse(alt) ? color.block(alt) : null;
      if (B2 && !clash(A, B2)) B = B2;
      else B = { bg: A.bg === (cssVar('--slate') || '#3a4150') ? cob.bg : (cssVar('--slate') || '#3a4150'), ink: '#ffffff', edge: color.parse(hb) ? color.ensure(hb, cssVar('--bg') || '#0a0c10', 3) : null, clash: true };
    }
    return [A, B];
  },
  /* markOutline(hex): the inset outline a team square needs so it does not vanish into the card (contrast with the
   * card under 1.6), else null. */
  markOutline: function (hex) {
    if (!color.parse(hex)) return null;
    return color.contrast(hex, color.surface()) < 1.6 ? color.ensure(hex, color.surface(), 3) : null;
  }
};
QK.color = color;

/* ─────────────────────────────────────── icons */
var ICON = {
  logo: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M2 12 L6 7 L9 9.5 L14 3"/><circle cx="14" cy="3" r="0.6" fill="currentColor"/></svg>',
  search: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="9" cy="9" r="6"/><path d="M14 14l4 4"/></svg>',
  sun: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="10" cy="10" r="3.6"/><path d="M10 1.8v2M10 16.2v2M1.8 10h2M16.2 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M16.5 12.4A7 7 0 0 1 7.6 3.5a7 7 0 1 0 8.9 8.9z"/></svg>',
  home: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M3 9l7-6 7 6v8H3z"/><path d="M8 17v-5h4v5"/></svg>',
  football: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10" cy="10" r="8"/><path d="M10 6.2l3.2 2.3-1.2 3.8H8l-1.2-3.8z" fill="currentColor" stroke="none"/><path d="M10 2v4.2M13.2 8.5l4.3-1.4M12 12.3l2.6 3.6M8 12.3l-2.6 3.6M6.8 8.5L2.5 7.1"/></svg>',
  f1: '<svg viewBox="0 0 20 20" fill="currentColor"><path d="M3 2.5h1.5v15H3z"/><path d="M5 3h12v8H5z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5 3h3v2.7H5zM11 3h3v2.7h-3zM8 5.7h3v2.7H8zM14 5.7h3v2.7h-3zM5 8.3h3V11H5zM11 8.3h3V11h-3z"/></svg>',
  basketball: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10" cy="10" r="8"/><path d="M2 10h16M10 2v16M4.4 4.4c3 2.6 3 8.6 0 11.2M15.6 4.4c-3 2.6-3 8.6 0 11.2"/></svg>',
  tennis: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10" cy="10" r="8"/><path d="M3.2 5.6c3.6 1.6 3.6 7.2 0 8.8M16.8 5.6c-3.6 1.6-3.6 7.2 0 8.8"/></svg>',
  baseball: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10" cy="10" r="8"/><path d="M5.2 3.6c1.8 3.8 1.8 9 0 12.8M14.8 3.6c-1.8 3.8-1.8 9 0 12.8" stroke-dasharray="1.6 1.4"/></svg>',
  nfl: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3.5 16.5C2 11 5.5 4.5 16.5 3.5 18 9 14.5 15.5 3.5 16.5z"/><path d="M7 13l6-6M8.5 9.5l2 2M10 8l2 2"/></svg>',
  hockey: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><ellipse cx="10" cy="8" rx="7" ry="3"/><path d="M3 8v4c0 1.7 3.1 3 7 3s7-1.3 7-3V8"/></svg>',
  college: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2.5v15"/><path d="M4 3.5l12.5 3.8L4 11.2z"/><path d="M7 6.2l4.5 1.3"/></svg>',
  empty: '<svg viewBox="0 0 36 36" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="5" y="8" width="26" height="20" rx="3"/><path d="M5 14h26M11 20h8M11 24h5"/></svg>',
  arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 8h10M9 4l4 4-4 4"/></svg>'
};
QK.ICON = ICON;

/* ─────────────────────────────────────── sports registry + IA */
var PUB = 'https://pchattani.github.io/';
QK.HOME_URL = PUB + 'the-quant/';
/* pending: true marks a site that is built but not launched (no public Pages site yet). It stays out of the
 * switcher, footer and home page everywhere except on its own pages and in local preview (QK.visible). */
QK.ALL_SPORTS = [
  { key: 'football',   label: 'Football',   site: 'The Quant Footballer', repo: 'the-quant-footballer', folder: 'site',     leagues: 'Europe, the Americas, Asia, Africa · 69 competitions' },
  { key: 'nfl',        label: 'NFL',        site: 'The Quant Gridiron',   repo: 'the-quant-gridiron',   folder: 'gridiron', leagues: 'NFL' },
  { key: 'basketball', label: 'Basketball', site: 'The Quant Hardwood',   repo: 'the-quant-hardwood',   folder: 'hardwood', leagues: 'NBA · WNBA' },
  { key: 'baseball',   label: 'Baseball',   site: 'The Quant Bullpen',    repo: 'the-quant-bullpen',    folder: 'bullpen',  leagues: 'MLB · Triple-A' },
  { key: 'hockey',     label: 'Hockey',     site: 'The Quant Rink',       repo: 'the-quant-rink',       folder: 'rink',     leagues: 'NHL' },
  { key: 'f1',         label: 'F1',         site: 'The Quant Paddock',    repo: 'the-quant-paddock',    folder: 'paddock',  leagues: 'Formula 1 · 1950 to today' },
  { key: 'tennis',     label: 'Tennis',     site: 'The Quant Ace',        repo: 'the-quant-ace',        folder: 'ace',      leagues: 'ATP · WTA' },
  { key: 'college',    label: 'College',    site: 'The Quant Campus',     repo: 'the-quant-campus',     folder: 'campus',   leagues: 'CFB · Men’s and women’s college basketball' }
];
QK.ALL_SPORTS.forEach(function (s) { s.url = PUB + s.repo + '/'; s.data = s.url + 'data/'; s.accent = 'var(--a-' + s.key + ')'; });
QK.sport = function (key) { for (var i = 0; i < QK.ALL_SPORTS.length; i++) if (QK.ALL_SPORTS[i].key === key) return QK.ALL_SPORTS[i]; return null; };
/* Local preview: when a page is served from docs/ (http://127.0.0.1:<port>/home/...), link sibling folders. */
QK.localBase = function () {
  var l = root.location || {};
  return /^(localhost|127\.0\.0\.1)$/.test(l.hostname || '') || l.protocol === 'file:';
};
/* A pending site shows only on its own pages (<html data-sport="college">) and in local preview. */
QK.visible = function (s) {
  if (!s || !s.pending) return !!s;
  var own = root.document && document.documentElement ? document.documentElement.getAttribute('data-sport') : null;
  return own === s.key || QK.localBase();
};
QK.SPORTS = QK.ALL_SPORTS.filter(QK.visible);
QK.sportUrl = function (key) { var s = QK.sport(key); if (!s) return '#'; return QK.localBase() ? '../' + s.folder + '/' : s.url; };
QK.homeUrl = function () { return QK.localBase() ? '../home/' : QK.HOME_URL; };

/* Every sport uses these nine sections in this order (docs/REDESIGN.md). A site may relabel
 * one (F1 calls Fixtures "Races") or hide one it does not have, but never reorders them. */
QK.SECTIONS = [
  { key: 'overview',  label: 'Overview',      route: '#/' },
  { key: 'fixtures',  label: 'Fixtures',      route: '#/fixtures' },
  { key: 'standings', label: 'Standings',     route: '#/standings' },
  { key: 'teams',     label: 'Teams',         route: '#/teams' },
  { key: 'players',   label: 'Players',       route: '#/players' },
  { key: 'value',     label: 'Value & Moves', route: '#/value' },
  { key: 'fantasy',   label: 'Fantasy',       route: '#/fantasy' },
  { key: 'lab',       label: 'Lab',           route: '#/lab' },
  { key: 'model',     label: 'Model',         route: '#/model' }
];
var SECTION_LABELS = {
  f1: { fixtures: 'Races', teams: 'Constructors', players: 'Drivers' },
  tennis: { fixtures: 'Draws', standings: 'Rankings', teams: null },
  baseball: { fixtures: 'Games' }, basketball: { fixtures: 'Games' }, hockey: { fixtures: 'Games' }, nfl: { fixtures: 'Games' },
  college: { fixtures: 'Games' }
};
QK.sections = function (sportKey, overrides) {
  var lab = SECTION_LABELS[sportKey] || {};
  var o = overrides || {};
  return QK.SECTIONS.map(function (s) {
    var label = s.key in o ? o[s.key] : (s.key in lab ? lab[s.key] : s.label);
    return label === null ? null : { key: s.key, label: label, href: s.route };
  }).filter(Boolean);
};

/* ─────────────────────────────────────── theme: dark only (v3) */
/* v3 "Matchday" is dark only (user decision, 23 Oct 2026). The API stays so old callers keep working: get() is always
 * 'dark', set() and toggle() pin dark and repaint, onChange listeners run once on a set() call. boot() pins
 * data-theme="dark" on <html> (so a site's old light-mode CSS keyed on data-theme never applies) and forgets a
 * stored 'light' choice. */
var themeListeners = [];
QK.theme = {
  get: function () { return 'dark'; },
  set: function () {
    document.documentElement.setAttribute('data-theme', 'dark');
    QK.theme.paint();
    themeListeners.forEach(function (f) { try { f('dark'); } catch (e) { if (root.console) console.error(e); } });
  },
  paint: function () { $$('[data-qk-theme-toggle]').forEach(function (b) { b.hidden = true; }); },
  toggle: function () { QK.theme.set('dark'); },
  onChange: function (f) { themeListeners.push(f); },
  boot: function () {
    try { document.documentElement.setAttribute('data-theme', 'dark'); } catch (e) { /* no document */ }
    if (store('qk-theme') === 'light') store('qk-theme', null);
  }
};
QK.theme.boot();
QK.reducedMotion = function () { return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches); };

/* ─────────────────────────────────────── app shell */
/* QK.shell({ sport: 'nfl' | null, section: 'teams', sections: QK.sections('nfl'), live: {nfl: true},
 *            search: { load: fn -> Promise<[{t, s, href, sport}]> }, ctx: '<html for the right of the section nav>',
 *            mount: '#qk-shell', footer: '#qk-footer' })
 * Renders the unified bar; returns { setSection(key), setLive(map) }. */
QK.shell = function (o) {
  o = o || {};
  QK.ensureFonts();
  var sportKey = o.sport || null;
  var mount = typeof o.mount === 'string' ? $(o.mount) : (o.mount || $('#qk-shell'));
  if (!mount) { mount = document.createElement('div'); document.body.insertBefore(mount, document.body.firstChild); }
  /* demo: true renders the bar into a box (style guide) without touching the page's own accent, footer or keys */
  if (sportKey && !o.demo) document.documentElement.setAttribute('data-sport', sportKey);
  if (sportKey && o.demo) mount.style.setProperty('--accent', 'var(--a-' + sportKey + ')');
  document.body.classList.add('qk');
  QK.bleedFix();
  var sp = sportKey ? QK.sport(sportKey) : null;
  var brand = '<a class="qk-brand" href="' + esc(QK.homeUrl()) + '" aria-label="' + esc(sp ? sp.site + ': home of The Quant' : 'The Quant home') + '">' +
    '<span class="qk-brand-mark" aria-hidden="true"></span>' +
    '<span class="qk-brand-name">the quant' + (sp ? ' <b>' + esc(sp.site.replace('The Quant ', '').toLowerCase()) + '</b>' : '') + '</span></a>';
  var sports = '<nav class="qk-sports" aria-label="Sports">' +
    '<a class="qk-sport" style="--sa:var(--sun)" href="' + esc(QK.homeUrl()) + '"' + (sportKey ? '' : ' aria-current="page"') + '>' + ICON.home + 'Today</a>' +
    QK.SPORTS.map(function (s) {
      return '<a class="qk-sport" data-sport="' + s.key + '" style="--sa:' + s.accent + '" href="' + esc(QK.sportUrl(s.key)) + '"' +
        (s.key === sportKey ? ' aria-current="page"' : '') + '>' + ICON[s.key] + esc(s.label) + '<span class="qk-sport-live" hidden><span class="qk-sport-dot" aria-label="live now"></span></span></a>';
    }).join('') + '</nav>';
  var actions = '<div class="qk-bar-actions">' +
    (o.search ? '<button class="qk-searchbtn" type="button" data-qk-search aria-label="Search">' + ICON.search + '<span class="qk-sb-l">Find a player or team</span><span class="qk-sb-s">Search</span><kbd>/</kbd></button>' : '') + '</div>';
  var secs = o.sections || (sportKey ? QK.sections(sportKey) : null);
  /* links scroll in their own box; the context controls sit beside them (desktop) or on a second row (phones) */
  var secnav = secs ? '<nav class="qk-secnav' + (o.ctx ? ' has-ctx' : '') + '" aria-label="Sections"><div class="qk-secnav-in"><div class="qk-secnav-links">' +
    secs.map(function (s) { return '<a href="' + esc(s.href) + '" data-sec="' + esc(s.key) + '"' + (s.key === o.section ? ' aria-current="page"' : '') + '>' + esc(s.label) + '</a>'; }).join('') +
    '</div>' + (o.ctx ? '<div class="qk-secnav-ctx">' + o.ctx + '</div>' : '') + '</div></nav>' : '';
  mount.innerHTML = (o.demo ? '' : '<a class="qk-skip" href="#main">Skip to content</a>') + '<header class="qk-topbar"><div class="qk-topbar-in">' + brand +
    '<span class="qk-brand-sep" aria-hidden="true"></span>' + sports + actions + '</div></header>' + secnav;
  QK.theme.paint();
  if (o.search && !o.demo) QK.search.init(o.search);
  /* centre the current sport and section inside their own scrolling rows (never scrollIntoView, which can
   * also scroll the page sideways) */
  QK.centreIn($('.qk-sport[aria-current="page"]', mount), $('.qk-sports', mount));
  QK.centreIn($('.qk-secnav a[aria-current="page"]', mount), $('.qk-secnav-links', mount));
  if (o.footer !== false && !o.demo) QK.footer(o.footer);
  QK.tooltips();
  var api = {
    setSection: function (key) {
      $$('.qk-secnav a[data-sec]', mount).forEach(function (a) { if (a.getAttribute('data-sec') === key) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
      QK.centreIn($('.qk-secnav a[aria-current="page"]', mount), $('.qk-secnav-links', mount));
    },
    setLive: function (map) { $$('.qk-sport[data-sport]', mount).forEach(function (a) { var l = $('.qk-sport-live', a); if (l) l.hidden = !(map && map[a.getAttribute('data-sport')]); }); }
  };
  if (o.live) api.setLive(o.live);
  return api;
};
/* Full-bleed blocks (.qk-bleed: the player hero, the black band, the stat strip) run to the viewport's edges; 100vw
 * counts a classic scrollbar, so the kit keeps --qk-sbw (the scrollbar's width) on <html> to take it back out. */
var bleedOn = false, bleedW = -1;
QK.bleedFix = function () {
  function set() {
    try {
      var w = Math.max(0, Math.min(40, root.innerWidth - document.documentElement.clientWidth));
      if (w !== bleedW) { bleedW = w; document.documentElement.style.setProperty('--qk-sbw', w + 'px'); }
    } catch (e) { /* no layout */ }
  }
  set();
  if (!bleedOn && root.addEventListener) {
    bleedOn = true;
    root.addEventListener('resize', set); root.addEventListener('load', set);
    /* the scrollbar appears once the page's data fills it in: check again on the next frame after a size change */
    if (root.ResizeObserver) { try { new ResizeObserver(function () { root.requestAnimationFrame(set); }).observe(document.body); } catch (e) { /* old browser */ } }
  }
};
/* Scroll a horizontal row so `item` sits in its middle, without touching the page's own scroll. */
QK.centreIn = function (item, row) {
  if (!item || !row || row.scrollWidth <= row.clientWidth + 1) return;
  try {
    var r = row.getBoundingClientRect(), i = item.getBoundingClientRect();
    row.scrollLeft += (i.left + i.width / 2) - (r.left + r.width / 2);
  } catch (e) { /* detached */ }
};
QK.footer = function (sel) {
  var el = typeof sel === 'string' ? $(sel) : sel;
  if (!el) { el = document.createElement('footer'); document.body.appendChild(el); }
  el.className = 'qk-footer';
  el.innerHTML = '<div class="qk-footer-in"><div><div class="qk-footer-brand"><span class="qk-brand-mark" aria-hidden="true"></span>the quant</div><br>Free sports numbers, explained. Made for fans who like a stat.<br>' +
    'Our chances are model estimates, not betting advice.</div><nav aria-label="All sports">' +
    QK.SPORTS.map(function (s) { return '<a href="' + esc(QK.sportUrl(s.key)) + '">' + esc(s.site) + '</a>'; }).join('') + '</nav></div>';
};

/* ─────────────────────────────────────── search (command palette) */
QK.search = (function () {
  var cfg = null, rows = null, dlg = null, sel = 0, items = [];
  function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
  function build() {
    dlg = h('<div class="qk-search-dlg" role="dialog" aria-modal="true" aria-label="Search"><div class="qk-search-box">' +
      '<div class="qk-search-field">' + ICON.search + '<input type="search" placeholder="Search teams, players, competitions…" aria-label="Search" aria-controls="qk-sr" autocomplete="off" spellcheck="false"><kbd class="qk-badge">Esc</kbd></div>' +
      '<ul class="qk-search-results" id="qk-sr" role="listbox"></ul></div></div>');
    document.body.appendChild(dlg);
    var input = $('input', dlg);
    dlg.addEventListener('click', function (e) { if (e.target === dlg) close(); });
    input.addEventListener('input', function () { render(input.value); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, items.length - 1); mark(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); mark(); e.preventDefault(); }
      else if (e.key === 'Enter' && items[sel]) { root.location.href = items[sel].href; close(); }
      else if (e.key === 'Escape') close();
    });
  }
  function mark() { $$('#qk-sr a', dlg).forEach(function (a, i) { a.setAttribute('aria-selected', i === sel ? 'true' : 'false'); if (i === sel && a.scrollIntoView) a.scrollIntoView({ block: 'nearest' }); }); }
  function render(q) {
    var list = $('#qk-sr', dlg);
    var nq = norm(q).trim();
    if (!rows) { list.innerHTML = '<li class="qk-search-empty">Loading the index…</li>'; return; }
    if (!nq) { list.innerHTML = '<li class="qk-search-empty">Type a team, player or competition. ' + fmt.num(rows.length) + ' entries across every sport.</li>'; items = []; return; }
    /* rank: where the match starts (start of name, start of a word, inside a word), then the row's weight
     * (r.w, higher first: a star before a reserve, a club before its youth side), then the shorter name */
    var scored = [];
    for (var i = 0; i < rows.length && scored.length < 3000; i++) {
      var r = rows[i], n = r._n || (r._n = norm(r.t)), k = n.indexOf(nq);
      if (k >= 0) scored.push([k === 0 ? 0 : (n.charAt(k - 1) === ' ' ? 1 : 2), isNum(r.w) ? -r.w : 0, n.length, r]);
    }
    scored.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1] || a[2] - b[2]; });
    items = scored.slice(0, 30).map(function (x) { return x[3]; });
    sel = 0;
    if (!items.length) { list.innerHTML = '<li class="qk-search-empty">Nothing matches “' + esc(q) + '”.</li>'; return; }
    list.innerHTML = items.map(function (r, i) {
      var s = QK.sport(r.sport) || {};
      var n = esc(r.t), k = norm(r.t).indexOf(nq);
      if (k >= 0 && norm(r.t).length === r.t.length) n = esc(r.t.slice(0, k)) + '<mark>' + esc(r.t.slice(k, k + nq.length)) + '</mark>' + esc(r.t.slice(k + nq.length));
      return '<li role="option"><a href="' + esc(r.href) + '" aria-selected="' + (i === 0) + '"><span class="qk-iconbtn" style="width:30px;height:30px;color:' + (s.accent || 'var(--ink-2)') + '" aria-hidden="true">' + (ICON[r.sport] || ICON.search) + '</span>' +
        '<span class="qk-truncate"><span class="t">' + n + '</span><br><span class="s">' + esc(s.label || '') + (r.s ? ' · ' + esc(r.s) : '') + '</span></span></a></li>';
    }).join('');
  }
  function open() {
    if (!dlg) build();
    dlg.classList.add('open');
    var input = $('input', dlg);
    input.value = ''; render('');
    setTimeout(function () { input.focus(); }, 10);
    if (!rows && cfg && cfg.load) cfg.load().then(function (r) { rows = r || []; render(input.value); }, function () { rows = []; render(input.value); });
  }
  function close() { if (dlg) dlg.classList.remove('open'); var b = $('[data-qk-search]'); if (b) b.focus(); }
  return {
    init: function (c) {
      cfg = c;
      $$('[data-qk-search]').forEach(function (b) { b.addEventListener('click', open); });
      document.addEventListener('keydown', function (e) {
        var t = e.target && e.target.tagName;
        if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) && t !== 'INPUT' && t !== 'TEXTAREA' && t !== 'SELECT') { e.preventDefault(); open(); }
      });
    },
    open: open, close: close
  };
})();

/* ─────────────────────────────────────── tooltips: any [data-tip] (hover + keyboard focus) */
var tipEl = null, tipBound = false;
QK.tooltips = function () {
  if (tipBound) return; tipBound = true;
  tipEl = h('<div class="qk-tip" role="tooltip" id="qk-tip"></div>');
  document.body.appendChild(tipEl);
  function show(t) {
    var txt = t.getAttribute('data-tip'); if (!txt) return;
    tipEl.textContent = txt;
    var r = t.getBoundingClientRect();
    tipEl.style.left = '0px'; tipEl.style.top = '0px'; tipEl.classList.add('show');
    var w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
    var x = Math.max(8, Math.min(root.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
    var y = r.top - hh - 8; if (y < 8) y = r.bottom + 8;
    tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
    t.setAttribute('aria-describedby', 'qk-tip');
  }
  function hide() { tipEl.classList.remove('show'); }
  document.addEventListener('mouseover', function (e) { var t = e.target.closest && e.target.closest('[data-tip]'); if (t) show(t); });
  document.addEventListener('mouseout', function (e) { var t = e.target.closest && e.target.closest('[data-tip]'); if (t) hide(); });
  document.addEventListener('focusin', function (e) { var t = e.target.closest && e.target.closest('[data-tip]'); if (t) show(t); });
  document.addEventListener('focusout', hide);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });
  root.addEventListener('scroll', hide, { passive: true });
  glossWatch();
};

/* ─────────────────────────────────────── column abbreviations: a tooltip on every known header */
/* Table headers are short (GP, OTL, xGA, wOBA ...). Any header cell (th) whose text is a known abbreviation for
 * the page's sport and that carries no tooltip of its own gets one: hover, or tap / focus the sort button, to
 * read it. Runs on every table the page draws, kit-made or not (a MutationObserver started by QK.tooltips).
 * A site can add or override entries: QK.GLOSS.extend('hockey', { CF: 'Corsi for ...' }). */
var GL_ALL = {
  GP: 'Games played', W: 'Wins', L: 'Losses', T: 'Ties', 'W-L': 'Wins and losses', 'W–L': 'Wins and losses',
  L10: 'Record in the last 10 games', Strk: 'Current streak (W = winning, L = losing)', Opp: 'Opponent', Wk: 'Week',
  Rd: 'Round', 'O/U': 'Over/under: the total points line', Elo: 'Elo rating: higher is stronger; it moves with every result',
  Rk: 'Rank', Pts: 'Points', PTS: 'Points', Min: 'Minutes played', Apps: 'Appearances', Avg: 'Average', 'Δ': 'Change',
  Pctl: 'Percentile (100 = best)', Mkt: 'Market probability (de-vigged)', n: 'Number of cases', N: 'Number of cases',
  Proj: 'Projection', WAR: 'Wins above replacement', PPG: 'Points per game', Pos: 'Position', Tier: 'Tier: players of similar projected value'
};
var GL_SPORT = {
  football: { P: 'Played', D: 'Draws', GF: 'Goals for', GA: 'Goals against', GD: 'Goal difference', G: 'Goals', A: 'Assists',
    xG: 'Expected goals: the chance quality of the shots taken', xA: 'Expected assists: the expected goals of the shots a player set up',
    xGA: 'Expected goals against', xGD: 'Expected goal difference (xG for minus against)', npxG: 'Non-penalty expected goals',
    Att: 'Attack rating: above zero scores more than an average side would', Def: 'Defence rating: above zero concedes less than an average side would',
    PPG: 'Points per game', CS: 'Clean sheets', 'xG/90': 'Expected goals per 90 minutes', 'G/90': 'Goals per 90 minutes', Form: 'Recent results, oldest first' },
  hockey: { OTL: 'Overtime and shootout losses (one point each)', 'P%': 'Points percentage: points won out of points available',
    'Pts%': 'Points percentage: points won out of points available', GF: 'Goals for', GA: 'Goals against', Diff: 'Goal difference (for minus against)',
    G: 'Goals', A: 'Assists', P: 'Points (goals plus assists)', '+/-': 'Plus-minus: goals for minus against while on the ice at even strength',
    PIM: 'Penalty minutes', TOI: 'Time on ice', 'TOI/GP': 'Time on ice per game', SOG: 'Shots on goal', 'SV%': 'Save percentage',
    GAA: 'Goals against per 60 minutes', GSAx: 'Goals saved above expected (from shot quality)', xG: 'Expected goals: the chance quality of the shots taken',
    xGF: 'Expected goals for', xGA: 'Expected goals against', 'xGF%': 'Share of expected goals at 5-on-5', 'CF%': 'Share of shot attempts at 5-on-5 (Corsi)',
    PP: 'Power play', PK: 'Penalty kill', 'PP%': 'Power-play success rate', 'PK%': 'Penalty-kill success rate', 'FO%': 'Faceoffs won',
    ROW: 'Regulation and overtime wins', RW: 'Regulation wins', Cup: 'Chance of winning the Stanley Cup (season simulation)', GS: 'Games started' },
  basketball: { MIN: 'Minutes', PTS: 'Points', REB: 'Rebounds', AST: 'Assists', STL: 'Steals', BLK: 'Blocks', TOV: 'Turnovers',
    'FG%': 'Field-goal percentage', '3P%': 'Three-point percentage', '3PA': 'Three-point attempts', 'FT%': 'Free-throw percentage',
    'TS%': 'True shooting: points per shot, counting threes and free throws', 'eFG%': 'Effective field-goal percentage (a three counts 1.5)',
    'USG%': 'Usage: share of team plays a player finishes while on court', ORtg: 'Offensive rating: points scored per 100 possessions',
    DRtg: 'Defensive rating: points allowed per 100 possessions', Net: 'Net rating: points per 100 possessions better than the opponent',
    NRtg: 'Net rating: points per 100 possessions better than the opponent', BPM: 'Box plus-minus: points per 100 possessions above an average player',
    '+/-': 'Plus-minus: points for minus against while on court', GB: 'Games behind the leader', Diff: 'Point difference per game',
    PF: 'Points for', PA: 'Points against', GS: 'Games started', MPG: 'Minutes per game', RPG: 'Rebounds per game', APG: 'Assists per game', Pace: 'Possessions per 48 minutes',
    Reb: 'Rebounds', Ast: 'Assists', Stl: 'Steals', Blk: 'Blocks', TO: 'Turnovers', '3PM': 'Three-pointers made', Pct: 'Winning percentage',
    HPM: 'Hardwood Plus-Minus: box score and RAPM combined, points per 100 possessions above average',
    RAPM: 'Regularised adjusted plus-minus: points per 100 possessions above average, from who was on court',
    WPA: 'Win probability added', Home: 'Home record', Away: 'Away record' },
  baseball: { G: 'Games', GS: 'Games started', PA: 'Plate appearances', AB: 'At-bats', H: 'Hits', R: 'Runs', RBI: 'Runs batted in',
    '1B': 'Singles', '2B': 'Doubles', '3B': 'Triples', HR: 'Home runs', BB: 'Walks', SO: 'Strikeouts', K: 'Strikeouts', HBP: 'Hit by pitch',
    SB: 'Stolen bases', CS: 'Caught stealing', AVG: 'Batting average', OBP: 'On-base percentage', SLG: 'Slugging percentage',
    OPS: 'On-base plus slugging', ISO: 'Isolated power (slugging minus average)', BABIP: 'Batting average on balls in play',
    wOBA: 'Weighted on-base average: each way of reaching base weighted by its run value', xwOBA: 'Expected wOBA from the quality of contact',
    'wRC+': 'Runs created, park- and league-adjusted (100 = average)', 'K%': 'Strikeout rate', 'BB%': 'Walk rate', 'HR%': 'Home-run rate',
    GO: 'Ground-ball outs', AO: 'Fly-ball and line-drive outs', IP: 'Innings pitched', BF: 'Batters faced', SV: 'Saves', ERA: 'Earned runs per nine innings',
    RA9: 'Runs allowed per nine innings', FIP: 'Fielding-independent pitching: runs from strikeouts, walks and homers, on the ERA scale',
    xFIP: 'FIP with a league-average home-run rate on fly balls', WHIP: 'Walks plus hits per inning', OAA: 'Outs above average (fielding)',
    GB: 'Games behind the division leader', RS: 'Runs scored', RA: 'Runs allowed', Diff: 'Run difference (scored minus allowed)', 'v SP': 'Against the opposing starting pitcher', Pct: 'Winning percentage' },
  nfl: { G: 'Games', GS: 'Games started', PF: 'Points for', PA: 'Points against', Diff: 'Point difference (for minus against)',
    Att: 'Attempts', Cmp: 'Completions', Yds: 'Yards', TD: 'Touchdowns', INT: 'Interceptions', Int: 'Interceptions', Car: 'Carries', Rec: 'Receptions',
    Tgt: 'Targets', 'Y/A': 'Yards per attempt', YPA: 'Yards per attempt', EPA: 'Expected points added', 'EPA/play': 'Expected points added per play',
    CPOE: 'Completion percentage over expected', RYOE: 'Rushing yards over expected', FG: 'Field goal', Sk: 'Sacks', Sacks: 'Sacks', Fum: 'Fumbles',
    'Comp%': 'Completion percentage', Rate: 'Passer rating', QBR: 'Total quarterback rating', Punt: 'Punt', Down: 'Down and distance' },
  f1: { Pod: 'Podiums (top-three finishes)', DNF: 'Did not finish', Q3: 'Reached the final part of qualifying (top ten)', Pole: 'Pole position (fastest in qualifying)',
    Grid: 'Starting position', Laps: 'Laps completed', Win: 'Chance of winning', Pts: 'Championship points', FL: 'Fastest lap', Bias: 'Average error: projected minus actual points' },
  tennis: { Rk: 'Ranking', Elo: 'Elo rating: higher is stronger; it moves with every match', DF: 'Double faults', BP: 'Break points',
    'BP%': 'Break points converted', '1st%': 'First serves in', '1stW%': 'Points won on first serve', '2ndW%': 'Points won on second serve',
    'Hold%': 'Service games held', 'Brk%': 'Return games won (breaks)', SP: 'Service points won', RP: 'Return points won' },
  college: { PF: 'Points for', PA: 'Points against', Diff: 'Point difference (for minus against)', Conf: 'Conference record', SOS: 'Strength of schedule',
    'TS%': 'True shooting: points per shot, counting threes and free throws', ORtg: 'Points scored per 100 possessions', DRtg: 'Points allowed per 100 possessions',
    Net: 'Net rating: points per 100 possessions better than the opponent', EPA: 'Expected points added', Seed: 'Tournament seed',
    GP: 'Games played', C: 'Completions', ATT: 'Attempts', Att: 'Attempts', Cmp: 'Completions', YDS: 'Yards', Yds: 'Yards', AVG: 'Average', TD: 'Touchdowns',
    INT: 'Interceptions', QBR: 'Total quarterback rating', CAR: 'Carries', Car: 'Carries', REC: 'Receptions', Rec: 'Receptions', LONG: 'Longest',
    TOT: 'Total tackles', SOLO: 'Solo tackles', Tkl: 'Tackles', TFL: 'Tackles for loss', PD: 'Passes defended', SACKS: 'Sacks',
    FGM: 'Field goals made', FGA: 'Field goals attempted', XPM: 'Extra points made', XPA: 'Extra points attempted', PCT: 'Percentage',
    REB: 'Rebounds', OREB: 'Offensive rebounds', DREB: 'Defensive rebounds', AST: 'Assists', STL: 'Steals', BLK: 'Blocks', TO: 'Turnovers',
    MIN: 'Minutes', PTS: 'Points', FG: 'Field goals made-attempted', '3PT': 'Three-pointers made-attempted', FT: 'Free throws made-attempted',
    ATS: 'Against the spread: games where the model side covered the line', AP: 'AP poll rank', Ours: 'Our rank', Prev: 'Previous AP rank',
    In: 'Chance of making the playoff', Bye: 'Chance of a first-round bye', Line: 'The market line', Opp: 'Opponent', Q: 'Quarter' }
};
QK.GLOSS = {
  lookup: function (label, sport) {
    var sp = GL_SPORT[sport] || {};
    if (Object.prototype.hasOwnProperty.call(sp, label)) return sp[label];
    return Object.prototype.hasOwnProperty.call(GL_ALL, label) ? GL_ALL[label] : null;
  },
  extend: function (sport, map) { var t = sport ? (GL_SPORT[sport] = GL_SPORT[sport] || {}) : GL_ALL; Object.keys(map || {}).forEach(function (k) { t[k] = map[k]; }); }
};
/* Explain the headers under el (default the whole page). Idempotent: a header is looked at once. */
QK.explainHeaders = function (el) {
  var sport = document.documentElement.getAttribute('data-sport') || '';
  $$('th:not([data-qk-gl])', el || document).forEach(function (th) {
    th.setAttribute('data-qk-gl', '1');
    if (th.hasAttribute('data-tip') || th.hasAttribute('title') || th.querySelector('[data-tip],[title]')) return;
    var txt = (th.textContent || '').replace(/[\u2191\u2193\u2195\u25b2\u25bc\u25b4\u25be\u21c5]/g, '').trim();
    if (!txt || txt.length > 9) return;
    var def = QK.GLOSS.lookup(txt, sport);
    if ((txt === 'PF' || txt === 'TO') && (sport === 'basketball' || sport === 'college')) {
      var row = th.parentNode ? [].map.call(th.parentNode.children, function (c) { return (c.textContent || '').trim(); }).join(' ') : '';
      if (/\b(REB|Reb|AST|Ast|STL|Stl|BLK|Blk|FGM|3PT)\b/.test(row)) def = txt === 'PF' ? 'Personal fouls' : 'Turnovers';
    }
    if (!def) return;
    var tgt = th.querySelector('button') || th;
    tgt.setAttribute('data-tip', def);
    if (!tgt.getAttribute('aria-label')) tgt.setAttribute('aria-label', txt + ': ' + def);
  });
};
var glossObs = null;
function glossWatch() {
  if (glossObs || !root.MutationObserver || !document.body) return;
  var queued = false;
  QK.explainHeaders();
  glossObs = new MutationObserver(function (muts) {
    if (queued) return;
    for (var i = 0; i < muts.length; i++) {
      if (muts[i].addedNodes && muts[i].addedNodes.length) {
        queued = true;
        (root.requestAnimationFrame || setTimeout)(function () { queued = false; QK.explainHeaders(); });
        return;
      }
    }
  });
  glossObs.observe(document.body, { childList: true, subtree: true });
}

/* ─────────────────────────────────────── tabs, segmented controls, chips */
/* <div class="qk-tabs" role="tablist"><button class="qk-tab" role="tab" aria-controls="p1">…</button></div>
 * <div class="qk-tabpanel" role="tabpanel" id="p1">…</div>. Arrow keys move; cb(id) on change. */
QK.tabs = function (rootEl, cb) {
  var tabs = $$('[role="tab"]', rootEl);
  function select(t, focus) {
    tabs.forEach(function (x) {
      var on = x === t;
      x.setAttribute('aria-selected', on ? 'true' : 'false'); x.tabIndex = on ? 0 : -1;
      var p = document.getElementById(x.getAttribute('aria-controls')); if (p) p.hidden = !on;
    });
    if (focus) t.focus();
    if (cb) cb(t.getAttribute('aria-controls'), t);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { select(t); });
    t.addEventListener('keydown', function (e) {
      var j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : null;
      if (j === null) return; e.preventDefault(); select(tabs[(j + tabs.length) % tabs.length], true);
    });
  });
  var cur = tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0];
  if (cur) select(cur);
  return { select: function (id) { tabs.forEach(function (t) { if (t.getAttribute('aria-controls') === id) select(t); }); } };
};
/* Single-select button group (.qk-seg) — cb(value). */
QK.seg = function (rootEl, cb) {
  var bs = $$('button', rootEl);
  bs.forEach(function (b) {
    b.addEventListener('click', function () {
      bs.forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      if (cb) cb(b.getAttribute('data-value'), b);
    });
  });
};
/* Filter chips (.qk-chips). multi=false → single choice. cb(selectedValues[]). */
QK.chips = function (rootEl, cb, multi) {
  var bs = $$('.qk-chip', rootEl);
  bs.forEach(function (b) {
    b.addEventListener('click', function () {
      if (multi) b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      else bs.forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      if (cb) cb(bs.filter(function (x) { return x.getAttribute('aria-pressed') === 'true'; }).map(function (x) { return x.getAttribute('data-value'); }));
    });
  });
};

/* ─────────────────────────────────────── table */
/* QK.table(el, { columns: [{ key, label, num, fmt(v,row) -> html, sort: false, pctl: 'key_of_percentile', tip, cls, sticky }],
 *                rows, sort: { key, dir: 'desc' }, rank: true, dense: true, maxHeight: 480, rowClass(row), rowHref(row) })
 * Header buttons sort (Enter/Space); aria-sort tracks state; rank column re-numbers. A column with `ours` (a model name,
 * or { name, about }, or true) carries the cobalt "Ours" tag in its head (QK.ours). */
QK.table = function (el, spec) {
  if (typeof el === 'string') el = $(el);
  var cols = spec.columns, rows = (spec.rows || []).slice();
  var st = spec.sort || null;
  function cell(c, r) {
    var v = r[c.key];
    var html = typeof c.fmt === 'function' ? c.fmt(v, r) : (isNum(v) ? (isRaw(c, v) ? esc(String(v)) : fmt.num(v, c.d || 0)) : esc(v === undefined || v === null ? '—' : v));
    if (c.pctl && isNum(r[c.pctl])) html = '<span class="qk-row" style="justify-content:flex-end;gap:8px;flex-wrap:nowrap">' + html + QK.pctlChip(r[c.pctl]) + '</span>';
    return '<td class="' + (c.num ? 'num ' : '') + (c.sticky ? 'sticky-col ' : '') + (c.cls || '') + '">' + html + '</td>';
  }
  function render() {
    if (st) {
      var k = st.key, d = st.dir === 'asc' ? 1 : -1;
      rows.sort(function (a, b) {
        var x = a[k], y = b[k];
        if (x === y) return 0; if (x === null || x === undefined) return 1; if (y === null || y === undefined) return -1;
        return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * d;
      });
    }
    var head = '<tr>' + (spec.rank ? '<th class="num" scope="col">#</th>' : '') + cols.map(function (c) {
      var sortable = c.sort !== false;
      var aria = sortable ? ' aria-sort="' + (st && st.key === c.key ? (st.dir === 'asc' ? 'ascending' : 'descending') : 'none') + '"' : '';
      var lab = (c.tip ? '<span data-tip="' + esc(c.tip) + '">' + esc(c.label) + '</span>' : esc(c.label)) +
        (c.ours ? QK.ours({ short: true, model: typeof c.ours === 'string' ? c.ours : (c.ours.name || c.ours.model), about: c.ours.about }) : '');
      return '<th scope="col" class="' + (c.num ? 'num ' : '') + (c.sticky ? 'sticky-col' : '') + '"' + aria + ' data-k="' + esc(c.key) + '">' +
        (sortable ? '<button type="button">' + lab + '</button>' : lab) + '</th>';
    }).join('') + '</tr>';
    var body = rows.length ? rows.map(function (r, i) {
      var rc = spec.rowClass ? spec.rowClass(r) : '', rh = spec.rowHref ? spec.rowHref(r) : '';
      return '<tr' + (rc ? ' class="' + esc(rc) + '"' : '') + (rh ? ' data-href="' + esc(rh) + '"' : '') + '>' + (spec.rank ? '<td class="rank num">' + (i + 1) + '</td>' : '') + cols.map(function (c) { return cell(c, r); }).join('') + '</tr>';
    }).join('') : '<tr><td colspan="' + (cols.length + (spec.rank ? 1 : 0)) + '">' + QK.empty('No rows', 'Nothing matches the current filters.') + '</td></tr>';
    el.innerHTML = '<div class="qk-table-wrap"' + (spec.maxHeight ? ' style="--table-max:' + spec.maxHeight + 'px"' : '') + '><table class="qk-table' + (spec.dense ? ' dense' : '') + '">' +
      (spec.caption ? '<caption class="qk-sr">' + esc(spec.caption) + '</caption>' : '') + '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
    $$('th[aria-sort] button', el).forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.parentNode.getAttribute('data-k');
        var col = cols.filter(function (c) { return c.key === k; })[0] || {};
        st = st && st.key === k ? { key: k, dir: st.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: col.num ? 'desc' : 'asc' };
        render();
        var nb = $('th[data-k="' + k + '"] button', el); if (nb) nb.focus();
      });
    });
    $$('tr[data-href]', el).forEach(function (tr) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function (ev) { if (ev.target.closest('a, button, input, select')) return; root.location.href = tr.getAttribute('data-href'); });
    });
  }
  render();
  return { setRows: function (r) { rows = r.slice(); render(); }, sort: function (k, d) { st = { key: k, dir: d || 'desc' }; render(); } };
};
/* A column shows numbers as written (no thousands separator: 2026, not 2,026) when it says so (raw: true,
 * year: true, or fmt: 'raw' | 'year') or when it is a year-like column (key year / season / yr ...) holding a
 * whole number between 1000 and 2999. */
var YEARISH = /^(year|season|yr|draft_year|draft|from|to|since|born|first|last)$/i;
function isRaw(c, v) {
  if (c.raw || c.year || c.fmt === 'raw' || c.fmt === 'year') return true;
  return YEARISH.test(String(c.key || '')) && Math.round(v) === v && v >= 1000 && v <= 2999;
}
QK.fmt.raw = function (v) { return v === undefined || v === null || v === '' ? '—' : String(v); };

/* Static table HTML on the kit markup, for pages that build HTML strings (wire it with QK.sortable(el)).
 *   cols: [{ label, align: 'right', title (tooltip), sortable: false, cls }] or plain label strings
 *   rows: [{ cells, _class, _href, _attrs }] or arrays of cells; a cell is { v, html, cls, align, title, style }
 *         or a primitive (a string with tags counts as html). v is the sort value.
 *   opts: { cls, id, maxHeight, sticky (pin the first column), dense (default true), caption } */
QK.tableHTML = function (cols, rows, opts) {
  var o = opts || {};
  var hh = '<div class="qk-table-wrap"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + (o.maxHeight ? ' style="--table-max:' + o.maxHeight + 'px"' : '') + '><table class="qk-table' + (o.dense === false ? '' : ' dense') + (o.cls ? ' ' + o.cls : '') + '">' +
    (o.caption ? '<caption class="qk-sr">' + esc(o.caption) + '</caption>' : '') + '<thead><tr>';
  cols.forEach(function (c, i) {
    var cc = typeof c === 'string' ? { label: c } : c;
    var num = cc.align === 'right';
    var lab = cc.title ? '<span data-tip="' + esc(cc.title) + '">' + esc(cc.label) + '</span>' : esc(cc.label);
    hh += '<th scope="col" class="' + (num ? 'num ' : '') + (o.sticky && i === 0 ? 'sticky-col ' : '') + (cc.cls || '') + '"' + (cc.sortable === false ? '' : ' aria-sort="none"') + '>' +
      (cc.sortable === false ? lab : '<button type="button">' + lab + '</button>') + '</th>';
  });
  hh += '</tr></thead><tbody>';
  (rows || []).forEach(function (r) {
    var row = Array.isArray(r) ? { cells: r } : r;
    hh += '<tr' + (row._class ? ' class="' + row._class + '"' : '') + (row._href ? ' data-href="' + esc(row._href) + '"' : '') + (row._attrs || '') + '>';
    row.cells.forEach(function (c0, i) {
      var c = (c0 !== null && typeof c0 === 'object') ? c0 : (typeof c0 === 'string' && /<[a-z\/]/i.test(c0) ? { html: c0 } : { v: c0 });
      var col = typeof cols[i] === 'object' ? cols[i] : {};
      var align = c.align || col.align;
      var cls = [align === 'right' ? 'num' : '', o.sticky && i === 0 ? 'sticky-col' : '', c.cls, col.cls].filter(Boolean).join(' ');
      var sortV = c.v !== undefined && c.v !== null ? c.v : (c.html !== undefined ? String(c.html).replace(/<[^>]*>/g, '') : '');
      hh += '<td data-v="' + esc(sortV) + '"' + (cls ? ' class="' + cls + '"' : '') + (c.title ? ' title="' + esc(c.title) + '"' : '') + (c.style ? ' style="' + c.style + '"' : '') + '>' +
        (c.html !== undefined ? c.html : esc(c.v === null || c.v === undefined ? '—' : c.v)) + '</td>';
    });
    hh += '</tr>';
  });
  return hh + '</tbody></table></div>';
};
/* Sortable headers (aria-sort buttons) and data-href row links for every table.qk-table under el
 * (QK.tableHTML output, or any table with th[aria-sort] buttons and td[data-v] sort values). Idempotent. */
QK.sortable = function (el) {
  var rootEl = typeof el === 'string' ? (document.getElementById(el) || $(el)) : el;
  if (!rootEl) return;
  var tables = rootEl.tagName === 'TABLE' ? [rootEl] : $$('table.qk-table', rootEl);
  tables.forEach(function (table) {
    if (table.getAttribute('data-sort-wired')) return;
    table.setAttribute('data-sort-wired', '1');
    var ths = $$('thead th', table);
    ths.forEach(function (th, idx) {
      var b = $('button', th);
      if (!b || !th.hasAttribute('aria-sort')) return;
      b.addEventListener('click', function () {
        var tbody = $('tbody', table);
        var trs = $$('tr', tbody);
        var cur = th.getAttribute('aria-sort');
        var asc = cur === 'descending' ? true : cur === 'ascending' ? false : !th.classList.contains('num');
        ths.forEach(function (x) { if (x.hasAttribute('aria-sort')) x.setAttribute('aria-sort', 'none'); });
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        function sv(tr) { var td = tr.children[idx]; if (!td) return ''; var v = td.getAttribute('data-v'); return v === null ? td.textContent.trim() : v; }
        trs.sort(function (a, b2) {
          var av = sv(a), bv = sv(b2);
          var an = parseFloat(av), bn = parseFloat(bv), aN = av !== '' && !isNaN(an) && isFinite(av), bN = bv !== '' && !isNaN(bn) && isFinite(bv);
          var cmp = aN && bN ? an - bn : aN ? -1 : bN ? 1 : String(av).localeCompare(String(bv));
          return asc ? cmp : -cmp;
        });
        trs.forEach(function (r) { tbody.appendChild(r); });
      });
    });
    $$('tr[data-href]', table).forEach(function (tr) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function (ev) { if (ev.target.closest('a, button, input, select')) return; root.location.hash = tr.getAttribute('data-href'); });
    });
  });
};

/* Percentile 0-100 → banded chip; bands at 20/40/60/80. */
QK.pctlChip = function (p) {
  if (!isNum(p)) return '';
  var band = p >= 80 ? 5 : p >= 60 ? 4 : p >= 40 ? 3 : p >= 20 ? 2 : 1;
  var c = QK.pctColor(p);
  return '<span class="qk-pctl" data-band="' + band + '" style="background:' + c + ';color:' + QK.pctInk(p) + '" title="' + esc(QK.ordinal(Math.round(p))) + ' percentile">' + Math.round(p) + '</span>';
};
/* Savant-style percentile bars, drawn as the v3 rail: rows [{ label, pctl, value, sub, prev, tip, early, style }].
 * The knob carries the percentile on the cold -> hot scale; r.sub is a one-line plain-English explanation under the
 * label; r.prev (last season's percentile) draws a hollow ring on the track; a tick marks the median. r.tip explains
 * the metric; r.early marks a value below the sample where the metric settles (dashed knob, a dot after the label);
 * r.style marks a metric that describes how a player plays rather than how well (METRICS_SPEC "style": usage, pace),
 * drawn in neutral grey. */
/* v4: each row is an LED meter (QK.meter): 20 skewed segments lit to the percentile, each segment in the colour of
 * its own place on the scale, a ▼ above for last season (r.prev), the percentile in a box on the scale's colour,
 * then the value. */
QK.pctlBars = function (rows) {
  return '<div class="qk-pbars">' + rows.filter(function (r) { return r && isNum(r.pctl); }).map(function (r) {
    var p = Math.max(0, Math.min(100, r.pctl));
    var tip = r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : ' title="' + esc(r.label) + '"';
    var prev = isNum(r.prev) ? Math.max(0, Math.min(100, r.prev)) : null;
    var aria = r.label + ': ' + QK.ordinal(Math.round(p)) + ' percentile' + (prev !== null ? ', ' + QK.ordinal(Math.round(prev)) + ' last season' : '') + (r.early ? ', early sample' : '');
    var bg = r.style ? 'var(--s-4)' : QK.pctColor(p), ink = r.style ? 'var(--ink-1)' : QK.pctInk(p);
    return '<div class="qk-pbar' + (r.early ? ' early' : '') + (r.style ? ' style' : '') + '"><span class="qk-pbar-label"' + tip + '>' + esc(r.label) + (r.sub ? '<small>' + esc(r.sub) + '</small>' : '') + '</span>' +
      QK.meter(p, { prev: prev, style: !!r.style, label: aria }) +
      '<span class="qk-pbox num" style="background:' + bg + ';color:' + ink + '">' + Math.round(p) + '</span>' +
      '<span class="qk-pbar-val">' + esc(r.value === undefined || r.value === null ? '' : r.value) + '</span></div>';
  }).join('') + '</div>';
};
/* QK.meter(p, { prev, style: true (neutral grey: a style metric, neither better nor worse), label, n: 20 }) -> the LED
 * meter alone (a role="img" span). At least one segment is lit, so a 1st percentile still shows. */
QK.meter = function (p, o) {
  o = o || {};
  var n = o.n || 20, step = 100 / n;
  p = isNum(p) ? Math.max(0, Math.min(100, p)) : 0;
  var lit = Math.max(1, Math.round(p / step)), segs = '';
  for (var i = 0; i < n; i++) segs += '<i' + (i < lit ? ' style="background:' + (o.style ? 'var(--ink-3)' : QK.pctColor(i * step + step / 2)) + '"' : '') + '></i>';
  var prev = isNum(o.prev) ? Math.max(1, Math.min(99, o.prev)) : null;
  if (prev !== null) segs += '<span class="last" style="left:' + prev.toFixed(1) + '%" title="Last season: ' + esc(QK.ordinal(Math.round(o.prev))) + '"></span>';
  return '<span class="qk-segs" role="img" aria-label="' + esc(o.label || (QK.ordinal(Math.round(p)) + ' percentile')) + '">' + segs + '</span>';
};
/* The key under the meters: the scale, the ▼ when a row carries last season. o: { ring: true, ringLabel, extra } */
QK.pctKey = function (o) {
  o = o || {};
  return '<div class="qk-pkey"><span>Worse</span><span class="ramp" aria-hidden="true"><i style="background:var(--pc-0)"></i><i style="background:var(--pc-25)"></i><i style="background:var(--pc-50)"></i><i style="background:var(--pc-75)"></i><i style="background:var(--pc-100)"></i></span><span>Better</span>' +
    (o.ring ? '<span><i class="tri" aria-hidden="true"></i>' + esc(o.ringLabel || 'last season') + '</span>' : '') +
    '<span>Box = percentile, right = the number</span>' + (o.extra ? '<span>' + esc(o.extra) + '</span>' : '') + '</div>';
};

/* ─────────────────────────────────────── team marks */
/* t = { name, abbr, colour, logo } → crest image if given, else a contrast-checked monogram. */
QK.teamMark = function (t, size) {
  t = t || {};
  var cls = 'qk-team-mark' + (size ? ' ' + size : '');
  if (t.logo) return '<span class="' + cls + ' img"><img src="' + esc(t.logo) + '" alt="" loading="lazy" decoding="async" onerror="this.parentNode.classList.remove(\'img\');this.parentNode.textContent=\'' + esc(fmt.initials(t.abbr || t.name)).replace(/'/g, '') + '\'"></span>';
  var bg = color.parse(t.colour) ? t.colour : null;
  var ol = bg ? color.markOutline(bg) : null;   /* a navy square on the charcoal card gets an inset outline */
  var style = bg ? ' style="--tc:' + esc(bg) + ';--ti:' + color.ink(bg) + (ol ? ';--to:' + ol : '') + '"' : '';
  return '<span class="' + cls + '"' + style + ' aria-hidden="true">' + esc((t.abbr || fmt.initials(t.name)).slice(0, 4)) + '</span>';
};

/* ─────────────────────────────────────── win probability, model v market */
/* Probability bar, left to right in the order the teams are listed (away over home on cards):
 * QK.probBar(pLeft, pDraw|null, pRight, teamLeft, teamRight). Each side takes its team colour when
 * that clears 3:1 on the card, else the win-probability fallbacks (--wp-a blue, --wp-b orange). v2: QK.wpBar adds labels. */
QK.probBar = function (pL, pD, pR, tL, tR) {
  if (!isNum(pL) && !isNum(pR)) return '';
  if (!isNum(pR)) pR = 1 - pL - (isNum(pD) ? pD : 0);
  if (!isNum(pL)) pL = 1 - pR - (isNum(pD) ? pD : 0);
  var lc = QK.probColour(tL, tR, 'left', true), rc = QK.probColour(tR, tL, 'right', true);
  var nL = (tL && tL.name) || 'Left', nR = (tR && tR.name) || 'Right';
  return '<div class="qk-probbar" role="img" aria-label="Win probability: ' + esc(nL) + ' ' + fmt.pct(pL) + (isNum(pD) ? ', draw ' + fmt.pct(pD) : '') + ', ' + esc(nR) + ' ' + fmt.pct(pR) + '"' +
    ' style="' + (lc ? '--ph:' + lc + ';' : '') + (rc ? '--pa:' + rc : '') + '">' +
    '<span class="h" style="flex:' + pL + '"></span>' + (isNum(pD) ? '<span class="d" style="flex:' + pD + '"></span>' : '') + '<span class="a" style="flex:' + pR + '"></span></div>';
};
/* The colour QK.probBar gives one side, so text beside it can match. Two similar kits: the right
 * side falls back to the market orange so the split stays readable. raw=true returns null for a fallback. */
QK.probColour = function (t, other, side, raw) {
  var c = t && color.parse(t.colour) ? color.team(t.colour) : null;
  var o = other && color.parse(other.colour) ? color.team(other.colour) : null;
  if (side === 'right' && c && o && !color.distinct(c, o)) c = null;
  return c || (raw ? null : (side === 'left' ? 'var(--wp-a)' : 'var(--wp-b)'));
};
/* Our probability on a 0-100% track (solid signal dot) with the market as a quiet reference (hollow grey ring).
 * v2: ours first, no "gap" or "edge" wording; the label defaults to "Ours · market". */
QK.mvm = function (model, market, label) {
  if (!isNum(model) || !isNum(market)) return '';
  var a = Math.min(model, market) * 100, b = Math.max(model, market) * 100;
  return '<div class="qk-mvm" role="img" aria-label="' + esc(label || '') + ' our model ' + fmt.pct(model) + ', market ' + fmt.pct(market) + '">' +
    '<span>' + esc(label || 'Ours · market') + '</span><span class="qk-mvm-track"><span class="qk-mvm-link" style="left:' + a + '%;width:' + (b - a) + '%"></span>' +
    '<span class="qk-mvm-dot k" style="left:' + market * 100 + '%"></span><span class="qk-mvm-dot m" style="left:' + model * 100 + '%"></span></span>' +
    '<span class="qk-mvm-val"><b style="color:var(--c-model)">' + fmt.pct(model) + '</b> · ' + fmt.pct(market) + '</span></div>';
};

/* ─────────────────────────────────────── game card + ticker item */
/* Game shape (home.json and every site's adapters):
 * { sport, league, id, start, status: pre|live|final, home:{name,abbr,colour,logo}, away:{…}, hs, as,
 *   p_home, p_draw, p_away, market_home, note, clock, period, href, tba (day known, start time not) } */
QK.statusBadge = function (g) {
  if (g.status === 'live') return '<span class="qk-badge live">Live' + (g.period ? ' · ' + esc(QK.periodLabel(g)) : '') + '</span>';
  if (g.status === 'final') return '<span class="qk-badge final">Final' + (g.note === 'OT' ? '/OT' : '') + '</span>';
  /* tba: the day is known, the start time is not (tennis order of play, college TBA kick-offs) */
  if (g.tba) return '<span class="qk-badge" title="Start time to be announced">' + esc(fmt.relDay(g.start)) + ' · TBA</span>';
  return '<span class="qk-badge">' + esc(fmt.relDay(g.start)) + ' · ' + esc(fmt.time(g.start)) + '</span>';
};
QK.periodLabel = function (g) {
  var p = g.period;
  if (!p) return '';
  if (g.sport === 'baseball') return 'Inn ' + p;
  if (g.sport === 'hockey') return p > 3 ? 'OT' : 'P' + p;
  if (g.sport === 'nfl' || g.sport === 'basketball') return p > 4 ? 'OT' : 'Q' + p;
  return String(p);
};
QK.matchCard = function (g, opts) {
  opts = opts || {};
  var s = QK.sport(g.sport) || {};
  var fin = g.status === 'final', live = g.status === 'live';
  var hs = g.hs, as = g.as;
  var hw = (fin || live) && isNum(hs) && isNum(as) ? (hs > as ? 1 : hs < as ? -1 : 0) : 0;
  var pA = isNum(g.p_away) ? g.p_away : (isNum(g.p_home) ? 1 - g.p_home - (isNum(g.p_draw) ? g.p_draw : 0) : null);
  function row(t, sc, p, lost) {
    return '<div class="qk-match-row' + (fin && lost ? ' lost' : '') + '">' + QK.teamMark(t, 'sm') + '<span class="nm">' + esc(t.name) + '</span>' +
      '<span class="p" title="Our win probability">' + (isNum(p) && !fin ? fmt.pct(p) : '') + '</span>' +
      '<span class="sc">' + (fin || live ? (isNum(sc) ? sc : '–') : '') + '</span></div>';
  }
  var foot = '';
  if (!fin && isNum(g.p_home)) foot = QK.probBar(pA, g.p_draw, g.p_home, g.away, g.home);
  /* pre-game only: a live market has moved with the score, the pre-game model has not */
  var pre = g.status === 'pre';
  var mk = pre && isNum(g.market_home) && isNum(g.p_home) && opts.market !== false ? QK.mvm(g.p_home, g.market_home, 'Home · ours, mkt') : '';
  var xg = g.xg && isNum(g.xg[0]) ? '<span class="num">xG ' + g.xg[0].toFixed(1) + '–' + g.xg[1].toFixed(1) + '</span>' : '';
  var edge = '';   /* v2: no edge badges (STYLE_GUIDE copy rules); the market stays a quiet reference */
  var tag = g.href ? 'a' : 'div';
  return '<' + tag + (g.href ? ' href="' + esc(g.href) + '"' : '') + ' class="qk-match' + (live ? ' is-live' : '') + '" style="--sa:' + (s.accent || 'var(--accent)') + '">' +
    '<div class="qk-match-top"><span class="lg">' + (opts.sport !== false ? '<span class="qk-sportpill">' + esc(s.label || g.sport) + '</span> · ' : '') + esc(g.league || '') + (g.note && g.note !== 'OT' ? ' · ' + esc(g.note) : '') + '</span>' + QK.statusBadge(g) + '</div>' +
    '<div class="qk-match-teams">' + row(g.away, as, pA, hw > 0) + row(g.home, hs, g.p_home, hw < 0) + '</div>' +
    (foot || mk || xg || edge ? '<div class="qk-stack" style="--g:6px">' + foot + (mk ? '<div style="margin-top:6px">' + mk + '</div>' : '') + '</div>' : '') +
    (xg || edge ? '<div class="qk-match-foot">' + (xg || '<span></span>') + edge + '</div>' : '') +
    '</' + tag + '>';
};
/* 'Today 18:30' → '18:30'; another day → 'Sat 18:30' */
QK.whenShort = function (iso, tba) {
  var r = fmt.relDay(iso);
  if (r === 'Today') return tba ? 'Today' : fmt.time(iso);
  var d = new Date(iso);
  var day = isNaN(d) ? '' : d.toLocaleDateString('en-GB', { weekday: 'short' });
  return tba ? day : day + ' ' + fmt.time(iso);
};
/* Ticker item: abbreviations and scores in mono; before the game our chance for each side, the favourite in the
 * signal colour, and a 2 px bar of the first-listed side's chance along the bottom (away first; home first for
 * football, or o.homeFirst). o.league: show the league, not the sport. */
QK.tick = function (g, o) {
  o = o || {};
  var fin = g.status === 'final', live = g.status === 'live', pre = !fin && !live;
  var s = QK.sport(g.sport) || {};
  var pa = isNum(g.p_away) ? g.p_away : (isNum(g.p_home) && !isNum(g.p_draw) ? 1 - g.p_home : null);
  var fav = pre && isNum(pa) && isNum(g.p_home) ? (pa > g.p_home ? 'a' : 'h') : '';
  function r(t, sc, lost, side) { var sv = fin || live; return '<div class="qk-tick-row' + (fin && lost ? ' lost' : '') + (fav === side ? ' fav' : '') + '"><span class="qk-truncate">' + esc(t.abbr || t.name) + '</span><span class="s' + (sv ? '' : ' p') + '">' + (sv ? (isNum(sc) ? sc : '–') : (isNum(t._p) ? fmt.pct(t._p) : '')) + '</span></div>'; }
  var hw = isNum(g.hs) && isNum(g.as) ? (g.hs > g.as ? 1 : g.hs < g.as ? -1 : 0) : 0;
  var a = Object.assign({}, g.away, { _p: pa });
  var hm = Object.assign({}, g.home, { _p: g.p_home });
  var hfT = o.homeFirst !== undefined ? !!o.homeFirst : !!(PREVIEW_WORDS[g.sport] || {}).homeFirst;
  /* the bar is the first-listed side's chance */
  var bar = pre && isNum(pa) && (!hfT || isNum(g.p_home)) ? '<span class="qk-tick-bar" aria-hidden="true"><i style="width:' + Math.round((hfT ? g.p_home : pa) * 100) + '%"></i></span>' : '';
  var rowsT = hfT ? r(hm, g.hs, hw < 0, 'h') + r(a, g.as, hw > 0, 'a') : r(a, g.as, hw > 0, 'a') + r(hm, g.hs, hw < 0, 'h');
  /* market: 'quiet' (round 6): the market's chance for our favourite, one small grey line, the source on hover */
  var mq = o.market === 'quiet' && fav ? QK.marketSides(g) : null, mv = mq ? (fav === 'h' ? mq.home : mq.away) : null;
  var mqT = isNum(mv) ? '<div class="qk-tick-mq" title="' + esc(mktTip(g, o)) + '">Market ' + esc(QK.shortName(fav === 'h' ? g.home : g.away)) + ' ' + fmt.pct(mv) + '</div>' : '';
  return '<a class="qk-tick' + (live ? ' is-live' : '') + '" href="' + esc(g.href || '#') + '" style="--sa:' + (s.accent || '') + '"><div class="qk-tick-top">' + (o.pill === false ? '' : '<span class="qk-sportpill">' + esc(o.league ? (g.league || s.label || '') : (s.label || '')) + '</span>') + '<span class="st' + (live ? ' live' : '') + '">' +
    (live ? '● ' + esc(QK.periodLabel(g) || 'Live') : fin ? 'Final' + (g.note === 'OT' || g.note === 'SO' ? '/' + esc(g.note) : '') : esc(QK.whenShort(g.start, g.tba))) + '</span></div>' + rowsT + mqT + bar + '</a>';
};

/* ─────────────────────────────────────── sparkline (inline SVG, theme-aware via currentColor) */
/* QK.spark([..], { w: 120, h: 32, color: 'var(--c-1)', area: true, dot: true, base: 0, label }) */
QK.spark = function (vals, o) {
  o = o || {};
  var v = (vals || []).filter(isNum);
  if (v.length < 2) return '';
  var w = o.w || 120, hh = o.h || 32, pad = 3;
  var lo = Math.min.apply(null, v.concat(isNum(o.base) ? [o.base] : [])), hi = Math.max.apply(null, v.concat(isNum(o.base) ? [o.base] : []));
  if (hi === lo) { hi += 1; lo -= 1; }
  var X = function (i) { return pad + i * (w - 2 * pad) / (v.length - 1); };
  var Y = function (y) { return hh - pad - (y - lo) * (hh - 2 * pad) / (hi - lo); };
  var d = v.map(function (y, i) { return (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(y).toFixed(1); }).join('');
  var c = o.color || 'var(--c-1)';
  var gid = 'sg' + Math.random().toString(36).slice(2, 8);
  var last = v[v.length - 1];
  return '<svg class="qk-spark" viewBox="0 0 ' + w + ' ' + hh + '" preserveAspectRatio="none" role="img" aria-label="' + esc(o.label || ('Trend from ' + v[0] + ' to ' + last)) + '" style="color:' + c + '">' +
    (o.area !== false ? '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".28"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="' + d + 'L' + X(v.length - 1).toFixed(1) + ' ' + hh + 'L' + X(0).toFixed(1) + ' ' + hh + 'Z" fill="url(#' + gid + ')"/>' : '') +
    (isNum(o.base) ? '<line x1="0" x2="' + w + '" y1="' + Y(o.base) + '" y2="' + Y(o.base) + '" stroke="var(--axis)" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"/>' : '') +
    '<path d="' + d + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
    (o.dot !== false ? '<circle cx="' + X(v.length - 1) + '" cy="' + Y(last) + '" r="2.6" fill="currentColor"/>' : '') + '</svg>';
};

/* ─────────────────────────────────────── KPI tile */
/* QK.kpi({ label, value, sub, delta, deltaFmt, spark: [..] | '<svg…>', text: true, tip, accent, cls, html })
 * html: true takes value and sub as HTML (links, team marks); otherwise they are escaped text.
 * Values wrap rather than truncate; on phones they step down a size (quant.css). */
QK.kpi = function (k) {
  var dl = isNum(k.delta) ? '<span class="qk-delta ' + (k.delta > 0 ? 'up' : k.delta < 0 ? 'down' : 'flat') + '">' + esc(k.deltaFmt ? k.deltaFmt(k.delta) : fmt.signed(k.delta)) + '</span>' : '';
  var empty = k.value === undefined || k.value === null || k.value === '';
  var val = empty ? '—' : (k.html ? String(k.value) : esc(k.value));
  var sub = k.sub === undefined || k.sub === null || k.sub === '' ? '' : (k.html ? String(k.sub) : esc(k.sub));
  var spark = typeof k.spark === 'string' ? k.spark : (k.spark ? QK.spark(k.spark, { color: k.sparkColor || 'var(--accent)', w: 120, h: 34 }) : '');
  return '<div class="qk-kpi' + (k.cls ? ' ' + esc(k.cls) : '') + '"' + (k.accent ? ' style="--accent:' + esc(k.accent) + '"' : '') + '><div class="qk-kpi-label">' + (k.tip ? '<span data-tip="' + esc(k.tip) + '">' + esc(k.label) + '</span>' : esc(k.label)) + '</div>' +
    '<div class="qk-kpi-value' + (k.text ? ' is-text' : '') + '"' + (k.spark && typeof k.spark !== 'string' ? ' style="max-width:56%"' : '') + '>' + val + '</div>' +
    (dl || sub ? '<div class="qk-kpi-sub">' + dl + (sub ? '<span class="qk-truncate">' + sub + '</span>' : '') + '</div>' : '') +
    spark + '</div>';
};

/* ─────────────────────────────────────── skeleton + empty */
QK.skeleton = function (kind, n) {
  n = n || 3;
  var out = '';
  for (var i = 0; i < n; i++) {
    if (kind === 'card') out += '<div class="qk-match" aria-hidden="true"><div class="qk-skel line short"></div><div class="qk-row"><span class="qk-skel circle"></span><span class="qk-skel line" style="flex:1"></span></div><div class="qk-row"><span class="qk-skel circle"></span><span class="qk-skel line" style="flex:1"></span></div></div>';
    else if (kind === 'chart') out += '<div class="qk-skel block" aria-hidden="true"></div>';
    else out += '<div class="qk-skel line' + (i % 3 === 2 ? ' short' : '') + '" aria-hidden="true"></div>';
  }
  return '<div role="status" aria-label="Loading" class="' + (kind === 'card' ? 'qk-auto' : '') + '">' + out + '</div>';
};
QK.empty = function (title, text, icon) {
  return '<div class="qk-empty">' + (icon || ICON.empty) + '<b>' + esc(title || 'Nothing here yet') + '</b>' + (text ? '<span>' + esc(text) + '</span>' : '') + '</div>';
};

/* ─────────────────────────────────────── data */
/* fetchJSON(url, {timeout}) → Promise. Cross-origin reads from *.github.io work (Pages sends ACAO: *). */
QK.fetchJSON = function (url, o) {
  o = o || {};
  return new Promise(function (resolve, reject) {
    var done = false;
    var t = setTimeout(function () { if (!done) { done = true; reject(new Error('timeout ' + url)); } }, o.timeout || 12000);
    fetch(url, { cache: o.cache || 'default', credentials: 'omit' }).then(function (r) {
      if (!r.ok) throw new Error(r.status + ' ' + url);
      return r.json();
    }).then(function (j) { if (!done) { done = true; clearTimeout(t); resolve(j); } }, function (e) { if (!done) { done = true; clearTimeout(t); reject(e); } });
  });
};

/* ═══════════════════════════════════════ v2 "Signal" builders (Design System 2.0; STYLE_GUIDE.md) ═══ */

/* The v4 faces: Bebas Neue (scores, big numbers, short headlines), Barlow (UI, body, tabular figures) and Barlow
 * Condensed (labels, tags, long names). QK.shell() adds them once, so a page still linking the v3 faces gets them
 * without a code change; a page should link them itself (MIGRATION_V4.md step 1) to avoid a late font swap. */
var DISPLAY_FONT = 'https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700;800&family=Barlow:wght@400;500;600;700&family=Bebas+Neue&display=swap';
QK.FONTS_URL = DISPLAY_FONT;
QK.ensureFonts = function () {
  try {
    if (!document.head || document.querySelector('link[data-qk-display]')) return;
    var ls = $$('link[href*="fonts.googleapis.com"]');
    for (var i = 0; i < ls.length; i++) if (/family=Bebas\+Neue/.test(ls[i].getAttribute('href') || '') && /family=Barlow\+Condensed/.test(ls[i].getAttribute('href') || '')) return;
    var l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = DISPLAY_FONT; l.setAttribute('data-qk-display', '1');
    document.head.appendChild(l);
  } catch (e) { /* no head (tests): the system fallback face is used */ }
};
QK.ordinal = function (n) {
  if (!isNum(n)) return '';
  var s = ['th', 'st', 'nd', 'rd'], v = Math.abs(Math.round(n)) % 100;
  return Math.round(n) + (s[(v - 20) % 10] || s[v] || s[0]);
};

/* ─────────────────────────────────────── percentile scale (cold -> hot) */
/* QK.pctColor(p) is a CSS colour that follows the theme (a color-mix of the two --pc-* anchors around p), for HTML.
 * QK.pctHex(p) resolves it to a hex for the current theme (charts, contrast maths). QK.pctInk(p) is the text ink on
 * it: white at the deep ends, near-black in the middle (both clear 4.3:1 in either theme). */
var PC = [0, 25, 50, 75, 100];
QK.pctColor = function (p) {
  if (!isNum(p)) return 'var(--pc-50)';
  p = Math.max(0, Math.min(100, p));
  var i = Math.min(3, Math.floor(p / 25)), t = Math.round((p - PC[i]) * 4);
  if (t <= 0) return 'var(--pc-' + PC[i] + ')';
  if (t >= 100) return 'var(--pc-' + PC[i + 1] + ')';
  return 'color-mix(in srgb, var(--pc-' + PC[i + 1] + ') ' + t + '%, var(--pc-' + PC[i] + '))';
};
QK.pctHex = function (p) {
  if (!isNum(p)) return cssVar('--pc-50') || '#a9adb5';
  p = Math.max(0, Math.min(100, p));
  var i = Math.min(3, Math.floor(p / 25));
  return color.mix(cssVar('--pc-' + PC[i]) || '#a9adb5', cssVar('--pc-' + PC[i + 1]) || '#a9adb5', (p - PC[i]) / 25);
};
/* the ink with more contrast on the percentile colour itself (white at the deep ends, near-black in the middle) */
QK.pctInk = function (p) {
  if (!isNum(p)) return '#000000';
  var hx = null;
  try { hx = QK.pctHex(p); } catch (e) { hx = null; }
  return hx && color.parse(hx) ? color.ink(hx) : (p < 15 || p > 88 ? '#ffffff' : '#000000');
};

/* ─────────────────────────────────────── small pieces */
QK.tag = function (txt, cls) { return '<span class="qk-tag' + (cls ? ' ' + esc(cls) : '') + '">' + esc(txt) + '</span>'; };
/* Direct-label key for a chart that cannot label its own lines: [{ name, color, kind: 'line'|'dot'|'ring'|'band' }] */
QK.keys = function (items) {
  return '<div class="qk-keys">' + (items || []).map(function (it) {
    return '<span><i class="' + esc(it.kind || 'line') + '" style="--k:' + esc(it.color || 'var(--ink-3)') + '"></i>' + esc(it.name) + '</span>';
  }).join('') + '</div>';
};

/* ─────────────────────────────────────── section head */
/* QK.sectionHead({ kicker, title, sub, actions (HTML), id, size: 'lg', tag: 'h1'|'h2', html: true (title/sub as HTML) }) */
QK.sectionHead = function (o) {
  o = o || {};
  var tag = o.tag === 'h1' || o.tag === 'h3' ? o.tag : 'h2';
  return '<header class="qk-sh' + (o.size === 'lg' ? ' lg' : '') + (o.cls ? ' ' + esc(o.cls) : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-sh-main">' +
    (o.kicker ? '<div class="qk-sh-kicker">' + esc(o.kicker) + '</div>' : '') +
    '<' + tag + ' class="qk-sh-title">' + (o.html ? String(o.title || '') : esc(o.title)) + '</' + tag + '>' +
    (o.sub ? '<p class="qk-sh-sub">' + (o.html ? String(o.sub) : esc(o.sub)) + '</p>' : '') + '</div>' +
    (o.actions ? '<div class="qk-sh-actions">' + o.actions + '</div>' : '') + '</header>';
};

/* ─────────────────────────────────────── scoreboard ticker */
/* QK.ticker(games, { group: 'sport' (default) | 'league' | false, max, sort: false, pill: false (no sport/league pill
 * on each tick: single-sport sites, where the group label already says it) }) -> the inside of a
 * <div class="qk-ticker">. Live games first, then upcoming, then finals; one labelled block per sport (or league).
 * market: 'quiet' (round 6) adds one small grey line to an upcoming tick: the market's chance for our favourite. */
QK.ticker = function (games, o) {
  o = o || {};
  var order = { live: 0, pre: 1, final: 2 };
  var list = (games || []).filter(Boolean).slice();
  if (o.sort !== false) list.sort(function (a, b) { return ((order[a.status] || 1) - (order[b.status] || 1)) || (a.status === 'final' ? (a.start < b.start ? 1 : -1) : (a.start > b.start ? 1 : -1)); });
  if (o.max) list = list.slice(0, o.max);
  if (o.group === false) return list.map(function (g) { return QK.tick(g, o); }).join('');
  var keys = [], groups = {};
  list.forEach(function (g) {
    var k = o.group === 'league' ? String(g.league || '') : String(g.sport || '');
    if (!groups[k]) { groups[k] = []; keys.push(k); }
    groups[k].push(g);
  });
  return keys.map(function (k) {
    var g0 = groups[k][0], s = QK.sport(g0.sport) || {};
    var lab = o.group === 'league' ? k : (s.label || k);
    return '<span class="qk-tick-grp" style="--sa:' + (s.accent || 'var(--accent)') + '">' + (ICON[g0.sport] ? '<span class="ic" aria-hidden="true">' + ICON[g0.sport] + '</span>' : '') + '<b>' + esc(lab) + '</b></span>' +
      groups[k].map(function (g) { return QK.tick(g, { league: o.group === 'league' ? false : o.league, pill: o.pill, market: o.market }); }).join('');
  }).join('');
};

/* ─────────────────────────────────────── win-probability bar, form */
/* A team's short label for tight spots (bar keys, the score bug): its abbreviation, else its name when that is short,
 * else the name's initials ('Vasco da Gama' -> 'VG'). */
QK.shortName = function (t) {
  t = t || {};
  if (t.abbr) return String(t.abbr);
  var n = String(t.name || '');
  return n.length <= 10 ? n : fmt.initials(n);
};
/* QK.wpBar(pLeft, pDraw|null, pRight, teamLeft, teamRight, { market: left side's market probability (a quiet tick at
 * the market's split; two-way only), labels: true | false | 'key' (v3: the abbreviations at the ends and what the bar
 * means in the middle, for cards whose rows already carry the numbers), keyText: 'chance to win', size: 'lg',
 * label: 'Win chance', colors: [left, right] (a page that already picked the pair for its charts passes it, so bar
 * and charts agree) }) */
QK.wpBar = function (pL, pD, pR, tL, tR, o) {
  o = o || {};
  if (!isNum(pL) && !isNum(pR)) return '';
  if (!isNum(pR)) pR = 1 - pL - (isNum(pD) ? pD : 0);
  if (!isNum(pL)) pL = 1 - pR - (isNum(pD) ? pD : 0);
  var lc = o.colors && o.colors[0] ? o.colors[0] : QK.probColour(tL, tR, 'left'), rc = o.colors && o.colors[1] ? o.colors[1] : QK.probColour(tR, tL, 'right');
  var nL = (tL && (tL.abbr || tL.name)) || 'Left', nR = (tR && (tR.abbr || tR.name)) || 'Right';
  var mk = isNum(o.market) && !isNum(pD) ? '<i class="qk-wpbar-mk" style="left:' + (100 * Math.max(0, Math.min(1, o.market))).toFixed(1) + '%" title="Market reference: ' + esc(nL) + ' ' + fmt.pct(o.market) + '"></i>' : '';
  var aria = (o.label || 'Win chance') + ': ' + nL + ' ' + fmt.pct(pL) + (isNum(pD) ? ', draw ' + fmt.pct(pD) : '') + ', ' + nR + ' ' + fmt.pct(pR) + (mk ? '; market ' + nL + ' ' + fmt.pct(o.market) : '');
  var lab = '';
  if (o.labels === 'key') lab = '<div class="qk-wpbar-lab"><span>' + esc(QK.shortName(tL)) + '</span><span class="mid">' + esc(o.keyText || 'chance to win') + (isNum(pD) ? ' · draw <b>' + fmt.pct(pD) + '</b>' : '') + '</span><span>' + esc(QK.shortName(tR)) + '</span></div>';
  else if (o.labels !== false) lab = '<div class="qk-wpbar-lab"><span><b>' + fmt.pct(pL) + '</b> ' + esc(nL) + '</span>' + (isNum(pD) ? '<span>Draw <b>' + fmt.pct(pD) + '</b></span>' : '') + '<span>' + esc(nR) + ' <b>' + fmt.pct(pR) + '</b></span></div>';
  return '<div class="qk-wpbar' + (o.size === 'lg' ? ' lg' : '') + '" role="img" aria-label="' + esc(aria) + '">' +
    '<div class="qk-wpbar-track"><span style="flex:' + pL + ';background:' + lc + '"></span>' + (isNum(pD) ? '<span class="d" style="flex:' + pD + '"></span>' : '') +
    '<span style="flex:' + pR + ';background:' + rc + '"></span>' + mk + '</div>' + lab + '</div>';
};
/* Recent results, oldest first: 'WWLDW' or ['W', 'L', ...] (W win, L loss, D draw, O overtime loss). Last five. */
QK.formDots = function (f) {
  if (!f || !f.length) return '<span></span>';
  var a = Array.isArray(f) ? f : String(f).replace(/[^A-Za-z]/g, '').split('');
  a = a.slice(-5);
  return '<span class="qk-form" role="img" aria-label="Form, oldest first: ' + esc(a.join(' ')) + '">' + a.map(function (x) {
    var k = String(x).toUpperCase().charAt(0);
    return '<i class="' + (k === 'W' ? 'w' : k === 'L' ? 'l' : 'd') + '" aria-hidden="true">' + esc(k) + '</i>';
  }).join('') + '</span>';
};

/* ─────────────────────────────────────── game card (v2 API, v3 look) */
/* QK.gameCard(game, { sport: false (hide the sport pill), market: true (show the market reference; v3 default false:
 * the market never sits on overview cards; round 6: 'quiet' puts the market's chance for each side, small and grey,
 * under ours, the source (g.market_src) in the tooltip, and a neutral marker in the foot when ours and the market
 * differ by ten points or more: marketMark: 0.15 | false), marketLabel, marketTip, form: false, why: false | true | 'text' (the
 * italic one-line reason: default g.why; true also writes QK.whyLine(g) when g.why is missing), bug: false (live
 * games: no score bug), homeFirst: true | false (the home side first in the rows and the stripe; default on for
 * football) }). Game shape as QK.matchCard, plus home/away .record and .form, and optional:
 *   g.wp_home   the live chance for the home side (a live game's p_home is then read as the pre-game call)
 *   g.p_pre     the pre-game chance for the home side, when p_home already carries the live chance
 *   g.pre_only  live, but the only chance we have is the pre-game one (labelled so)
 *   g.why       a one-line reason it is worth watching (the builder's copy)
 * Before the game each row carries our chance (favourite in blue) and the bar shows the split; live, the score and
 * the live chance; final, the score with the pre-game call in the foot. */
QK.liveP = function (g) {
  if (!g) return null;
  if (g.status === 'live' && isNum(g.wp_home)) return g.wp_home;
  return isNum(g.p_home) ? g.p_home : null;
};
QK.preP = function (g) {
  if (!g) return null;
  if (g.status === 'live' && isNum(g.wp_home)) return isNum(g.p_home) ? g.p_home : null;
  if (isNum(g.p_pre)) return g.p_pre;
  return g.status === 'live' && !g.pre_only ? null : (isNum(g.p_home) ? g.p_home : null);
};

/* ─────────────────────────────────────── the quiet market (round 6) */
/* Our chance leads; the market sits beside it, small and grey, with its source in the tooltip. Before the start only
 * (a live market has moved with the score). Game fields read: market_home (the market's chance for the home side),
 * optional market_away / market_draw (three-way markets: market_away is then needed), market_src (a name, a list of
 * names, or [{ source }] as the payloads carry them). No betting words: "Market", "our chance", a neutral marker.
 *   QK.marketSource(src)        -> 'Kalshi, Polymarket, DraftKings' (payload source keys made readable)
 *   QK.marketSides(g)           -> { home, away, draw } before the start, else null
 *   QK.marketGap(g, { mark })   -> { side: 'home' | 'away', team, ours, mkt, d } on our favourite when ours and the market
 *                                  differ by mark or more (default 0.10, ten points), else null
 *   QK.marketMark(g, o)         -> the neutral marker ("We’re higher than the market on Boston"), or ''
 *   QK.marketLine(g, o)         -> the one-line quiet market for a hero or a bug ("Market BOS 58% · NYR 42%") with the
 *                                  marker; o.mark: false drops the marker, o.source names a source the game lacks */
var MKT_NAMES = { kalshi: 'Kalshi', polymarket: 'Polymarket', draftkings: 'DraftKings', fanduel: 'FanDuel', espn: 'ESPN (sportsbook line)',
  pinnacle: 'Pinnacle', betfair: 'Betfair', smarkets: 'Smarkets', bet365: 'bet365', caesars: 'Caesars', betmgm: 'BetMGM', odds: 'The Odds API' };
QK.marketSource = function (s) {
  if (!s) return '';
  var a = Array.isArray(s) ? s : [s], seen = {}, out = [];
  a.forEach(function (x) {
    var k = x && typeof x === 'object' ? (x.source || x.src || x.name) : x;
    k = String(k || '').trim();
    if (!k) return;
    var key = k.toLowerCase().replace(/[\s-]+/g, '_');
    var nm = MKT_NAMES[key] || MKT_NAMES[key.split('_')[0]] || k.charAt(0).toUpperCase() + k.slice(1);
    if (!seen[nm]) { seen[nm] = 1; out.push(nm); }
  });
  return out.join(', ');
};
QK.marketSides = function (g) {
  if (!g || g.status === 'live' || g.status === 'final' || !isNum(g.market_home)) return null;
  var three = isNum(g.p_draw) || isNum(g.market_draw);
  var a = isNum(g.market_away) ? g.market_away : (three ? null : 1 - g.market_home);
  return { home: g.market_home, away: a, draw: isNum(g.market_draw) ? g.market_draw : null };
};
function mktTip(g, o) {
  var src = QK.marketSource(g.market_src) || (o && o.source) || '';
  return 'The market’s chance' + (src ? ', from ' + src : '') + '. A reference beside ours; our chance is our own forecast.';
}
QK.marketGap = function (g, o) {
  o = o || {};
  var m = QK.marketSides(g);
  if (!m || !isNum(g.p_home)) return null;
  var pD = isNum(g.p_draw) ? g.p_draw : 0;
  var pA = isNum(g.p_away) ? g.p_away : 1 - g.p_home - pD;
  var home = g.p_home >= pA, ours = home ? g.p_home : pA, mkt = home ? m.home : m.away;
  if (!isNum(mkt)) return null;
  var lim = isNum(o.mark) ? o.mark : 0.10;
  var d = ours - mkt;
  return Math.abs(d) >= lim - 1e-9 ? { side: home ? 'home' : 'away', team: home ? (g.home || {}) : (g.away || {}), ours: ours, mkt: mkt, d: d } : null;
};
QK.marketMark = function (g, o) {
  o = o || {};
  if (o.mark === false) return '';
  var x = QK.marketGap(g, o);
  if (!x) return '';
  var nm = o.short ? QK.shortName(x.team) : (x.team.name || QK.shortName(x.team));
  return '<span class="qk-mq-d">' + (x.d > 0 ? 'We’re higher than the market on ' : 'The market is higher on ') + esc(nm) + '</span>';
};
QK.marketLine = function (g, o) {
  o = o || {};
  var m = QK.marketSides(g);
  if (!m) return '';
  var A = g.away || {}, H = g.home || {};
  var hf = o.homeFirst !== undefined ? !!o.homeFirst : !!(PREVIEW_WORDS[g.sport] || {}).homeFirst;
  var sideH = esc(QK.shortName(H)) + ' <b>' + fmt.pct(m.home) + '</b>', sideA = isNum(m.away) ? esc(QK.shortName(A)) + ' <b>' + fmt.pct(m.away) + '</b>' : '';
  var parts = (hf ? [sideH, isNum(m.draw) ? 'Draw <b>' + fmt.pct(m.draw) + '</b>' : '', sideA] : [sideA, isNum(m.draw) ? 'Draw <b>' + fmt.pct(m.draw) + '</b>' : '', sideH]).filter(Boolean);
  var tip = mktTip(g, o);
  return '<div class="qk-mq-line' + (o.cls ? ' ' + esc(o.cls) : '') + '"><span class="qk-mq" data-tip="' + esc(tip) + '" tabindex="0" aria-label="' + esc(tip) + '">Market ' + parts.join(' · ') + '</span>' + QK.marketMark(g, o) + '</div>';
};
QK.gameCard = function (g, o) {
  o = o || {};
  var s = QK.sport(g.sport) || {};
  var fin = g.status === 'final', live = g.status === 'live', pre = !fin && !live;
  var hs = g.hs, as = g.as;
  var hw = (fin || live) && isNum(hs) && isNum(as) ? (hs > as ? 1 : hs < as ? -1 : 0) : 0;
  var pH = live ? QK.liveP(g) : g.p_home;
  var pD = live && isNum(g.wp_home) ? null : g.p_draw;
  var pA = live && isNum(g.wp_home) ? 1 - g.wp_home : (isNum(g.p_away) ? g.p_away : (isNum(pH) ? 1 - pH - (isNum(pD) ? pD : 0) : null));
  var favA = isNum(pA) && isNum(pH) && pA > pH;
  var showP = !fin && isNum(pH);
  /* home first: o.homeFirst, else the sport's habit (football reads "Home v Away", PREVIEW_WORDS) */
  var hf = o.homeFirst !== undefined ? !!o.homeFirst : !!(PREVIEW_WORDS[g.sport] || {}).homeFirst;
  /* market: 'quiet' (round 6): the market's chance for each side, small and grey under ours, the source in the tooltip */
  var mq = o.market === 'quiet' ? QK.marketSides(g) : null, mqTip = mq ? mktTip(g, o) : '';
  function row(t, sc, p, lost, fav, mside) {
    t = t || {};
    var score = fin || live ? '<span class="qk-gc-v">' + (isNum(sc) ? esc(sc) : '–') + '</span>' : '<span></span>';
    var ch = showP ? '<span class="qk-gc-v pct' + (live && g.pre_only ? ' sm' : '') + '">' + (isNum(p) ? QK.pctSmall(p) : '') + '</span>' : '<span></span>';
    if (showP && mq && isNum(mq[mside])) ch = '<span class="qk-gc-pw">' + ch + '<span class="qk-gc-mq" data-tip="' + esc(mqTip) + '" tabindex="0" aria-label="' + esc('Market ' + (t.name || '') + ' ' + fmt.pct(mq[mside]) + '. ' + mqTip) + '">Market ' + fmt.pct(mq[mside]) + '</span></span>';
    return '<div class="qk-gc-row' + (fin && lost ? ' lost' : '') + (showP && fav && !g.pre_only ? ' fav' : '') + '">' + QK.teamMark(t, 'md') +
      '<span class="qk-gc-nm">' + esc(t.name) + (t.record ? '<small>' + esc(t.record) + '</small>' : '') + '</span>' + (o.form === false ? '<span></span>' : QK.formDots(t.form)) + score + ch + '</div>';
  }
  var showMk = pre && o.market === true && isNum(g.market_home);
  var keyText = live ? (g.pre_only ? 'our pre-game chance' : 'chance to win, right now') : 'chance to win';
  /* v4: the team-colour stripe across the top carries the split, so the bar under the rows is opt-in (o.bar: true) */
  var bar = showP && (o.bar === true || showMk) ? (hf ? QK.wpBar(pH, pD, pA, g.home, g.away, { labels: 'key', keyText: keyText, market: showMk && !isNum(pD) ? g.market_home : null, label: live ? 'Live win chance' : 'Our win chance' }) : QK.wpBar(pA, pD, pH, g.away, g.home, { labels: 'key', keyText: keyText, market: showMk && !isNum(pD) ? 1 - g.market_home : null, label: live ? 'Live win chance' : 'Our win chance' })) : '';
  var hA = (g.home && (g.home.abbr || g.home.name)) || 'Home', aA = (g.away && (g.away.abbr || g.away.name)) || 'Away';
  var left = '';
  var pp = QK.preP(g);
  if (fin && isNum(pp)) { var pfA = 1 - pp - (isNum(g.p_draw) ? g.p_draw : 0); left = '<span>Our pre-game call: <b>' + esc(pfA > pp ? aA : hA) + ' ' + fmt.pct(Math.max(pfA, pp)) + '</b></span>'; }
  var xg = g.xg && isNum(g.xg[0]) && isNum(g.xg[1]) ? '<span>xG <b>' + g.xg[0].toFixed(1) + '–' + g.xg[1].toFixed(1) + '</b></span>' : '';
  var mk = showMk ? '<span class="qk-mkt" data-tip="' + esc(o.marketTip || 'The market’s probability, shown as a reference next to ours') + '">' + esc(o.marketLabel || 'Market') + ' <b>' + esc(hA) + ' ' + fmt.pct(g.market_home) + '</b></span>' : '';
  var whyTxt = o.why === false ? '' : (typeof o.why === 'string' ? o.why : (g.why || (o.why === true ? QK.whyLine(g) : '')));
  var tag = g.href ? 'a' : 'div';
  var top = live && o.bug !== false && isNum(hs) && isNum(as) ? QK.scorebug(g, { compact: true }) : QK.statusBadge(g);
  /* the team-colour stripe across the top: away | (draw) | home, split by our chance (even before one exists or
   * once it is over); team colours after the contrast and clash checks, else cobalt v grey */
  var sA = isNum(pA) && !fin ? pA : 0.5, sH = isNum(pH) && !fin ? pH : 0.5, sD = !fin && isNum(pD) ? pD : 0;
  var stripeLab = showP ? (live ? 'Live win chance: ' : 'Our win chance: ') + aA + ' ' + fmt.pct(pA) + (sD > 0 ? ', draw ' + fmt.pct(sD) : '') + ', ' + hA + ' ' + fmt.pct(pH) : '';
  /* home first (football): the home side leads the rows, the stripe and its label */
  if (hf && stripeLab) stripeLab = (live ? 'Live win chance: ' : 'Our win chance: ') + hA + ' ' + fmt.pct(pH) + (sD > 0 ? ', draw ' + fmt.pct(sD) : '') + ', ' + aA + ' ' + fmt.pct(pA);
  var segA = '<i style="flex:' + sA.toFixed(3) + ';background:' + QK.probColour(g.away, g.home, hf ? 'right' : 'left') + '"></i>';
  var segH = '<i style="flex:' + sH.toFixed(3) + ';background:' + QK.probColour(g.home, g.away, hf ? 'left' : 'right') + '"></i>';
  var stripe = o.stripe === false ? '' : '<span class="qk-gc-stripe"' + (stripeLab && !bar ? ' role="img" aria-label="' + esc(stripeLab) + '"' : ' aria-hidden="true"') + '>' + (hf ? segH : segA) +
    (sD > 0 ? '<i class="d" style="flex:' + sD.toFixed(3) + '"></i>' : '') + (hf ? segA : segH) + '</span>';
  var rA = row(g.away, as, pA, hw > 0, favA, 'away'), rH = row(g.home, hs, pH, hw < 0, !favA, 'home');
  var mqMark = mq && showP ? QK.marketMark(g, { mark: o.marketMark, short: true }) : '';
  /* the foot: "Our chance · <why>" (live: "Chance to win now · ..."; final: "Final · ...") */
  var ftLab = live ? (g.pre_only ? 'Live · ' : 'Chance to win now · ') : fin ? 'Final · ' : 'Our chance · ';
  return '<' + tag + (g.href ? ' href="' + esc(g.href) + '"' : '') + ' class="qk-gc' + (live ? ' is-live' : fin ? ' is-final' : '') + '" style="--sa:' + (s.accent || 'var(--accent)') + '">' + stripe +
    '<div class="qk-gc-top"><span class="qk-gc-lg">' + (o.sport !== false ? '<span class="qk-sportpill">' + esc(s.label || g.sport) + '</span> · ' : '') + esc(g.league || '') + (g.note && g.note !== 'OT' && g.note !== 'SO' ? ' · ' + esc(g.note) : '') + '</span>' + top + '</div>' +
    '<div class="qk-gc-rows">' + (hf ? rH + rA : rA + rH) + '</div>' + bar +
    (left || xg || mk ? '<div class="qk-gc-foot">' + (left || '<span></span>') + (xg || '') + mk + '</div>' : '') +
    (mqMark ? '<div class="qk-gc-foot qk-gc-mqf">' + mqMark + '</div>' : '') +
    (whyTxt ? '<div class="qk-gc-ft"><b>' + esc(ftLab) + '</b>' + esc(whyTxt) + '</div>' : '') + '</' + tag + '>';
};
/* 0.35 -> '35<small>%</small>' (Bebas chances with a small per-cent sign); the text reads '35%'. */
QK.pctSmall = function (p, d) {
  var s = fmt.pct(p, d);
  return /%$/.test(s) ? esc(s.slice(0, -1)) + '<small>%</small>' : esc(s);
};

/* ─────────────────────────────────────── chance bars (538-style probability bars) */
/* QK.chanceBar({ label, p, market, color (team hex or CSS colour), href, sub, mark: team }, { max, teamColours })
 * QK.chances(rows, { max, sort: false, key: false, marketName: 'Market', limit, teamColours: false }) -> the list with a key.
 * Broadcast colours: a title race shows each bar in its team's colour (r.color, else r.mark.colour; contrast-lifted
 * by QK.color.team); rows without one, or teamColours: false, are ours in blue. The value stays ours. */
QK.chanceBar = function (r, o) {
  o = o || {};
  var max = isNum(o.max) && o.max > 0 ? o.max : 1;
  var w = Math.max(0, Math.min(100, 100 * (isNum(r.p) ? r.p : 0) / max));
  var rc = r.color || (r.mark && r.mark.colour);   /* a row's team colour, else its team mark's */
  /* v4: the bar is a block carrying the name in white, so the team colour goes through QK.color.block (white
   * >= 4.5:1; a pale kit becomes slate with its colour along the edge); no colour, or teamColours: false: cobalt */
  var bk = rc && o.teamColours && color.parse(rc) ? color.block(rc) : null;
  var c = bk ? bk.bg : (rc && o.teamColours && !color.parse(rc) ? rc : 'var(--signal-deep)');
  var edge = bk && bk.edge ? ';box-shadow:inset 0 -4px 0 ' + bk.edge : '';
  var mk = isNum(r.market) ? '<i class="qk-chance-mk" style="left:' + Math.min(100, 100 * r.market / max).toFixed(1) + '%"></i>' : '';
  var aria = r.label + ': our chance ' + fmt.pct(r.p) + (isNum(r.market) ? ', market ' + fmt.pct(r.market) : '');
  var tag = r.href ? 'a' : 'div';
  return '<' + tag + ' class="qk-chance' + (r.mark ? '' : ' nomark') + '"' + (r.href ? ' href="' + esc(r.href) + '"' : '') + '>' +
    '<span class="qk-chance-lab">' + (r.mark ? QK.teamMark(r.mark, 'md') : '') + '</span>' +
    '<span class="qk-chance-track" role="img" aria-label="' + esc(aria) + '"><span class="qk-chance-fill" style="width:' + w.toFixed(1) + '%;--cc:' + c + edge + '"></span>' +
    '<span class="qk-chance-nm">' + esc(r.label) + (r.sub ? '<small>' + esc(r.sub) + '</small>' : '') + '</span>' + mk + '</span>' +
    '<span class="qk-chance-v num">' + fmt.pct(r.p) + '</span></' + tag + '>';
};
QK.chances = function (rows, o) {
  o = o || {};
  var rs = (rows || []).filter(function (r) { return r && isNum(r.p); });
  if (o.sort !== false) rs.sort(function (a, b) { return b.p - a.p; });
  if (o.limit) rs = rs.slice(0, o.limit);
  var mx = o.max;
  if (!isNum(mx)) { var m = Math.max.apply(null, rs.map(function (r) { return Math.max(r.p || 0, isNum(r.market) ? r.market : 0); }).concat([0.01])); mx = m > 0.6 ? 1 : Math.min(1, Math.ceil(m * 10 + 0.4) / 10); }
  var anyM = rs.some(function (r) { return isNum(r.market); });
  return '<div class="qk-chances">' + rs.map(function (r) { return QK.chanceBar(r, { max: mx, teamColours: o.teamColours !== false }); }).join('') +
    (o.key === false ? '' : '<div class="qk-chances-key"><span><i class="bar"' + (o.teamColours !== false && rs.some(function (r) { return !!(r.color || (r.mark && r.mark.colour)); }) ? ' style="background:var(--slate)"' : '') + '></i>' + esc(o.oursName || 'Our chance') + '</span>' + (anyM ? '<span><i class="tick"></i>' + esc(o.marketName || 'Market (reference)') + '</span>' : '') + (mx < 1 ? '<span>Scale 0–' + fmt.pct(mx) + '</span>' : '') + '</div>') + '</div>';
};

/* ─────────────────────────────────────── stat tile */
/* QK.statTile({ label, value, unit, sub, delta, deltaFmt, pctl, trend: [..], trendLabel, trendColor, tip, href,
 * signal: true (ours: the number in the signal colour), text: true (a word, not a number), html: true, cls })
 * QK.stats([tile objects or HTML]) -> the responsive row (two a row on phones). */
QK.statTile = function (k) {
  var tag = k.href ? 'a' : 'div';
  var dl = isNum(k.delta) ? '<span class="qk-delta ' + (k.delta > 0 ? 'up' : k.delta < 0 ? 'down' : 'flat') + '">' + esc(k.deltaFmt ? k.deltaFmt(k.delta) : fmt.signed(k.delta)) + '</span>' : '';
  var empty = k.value === undefined || k.value === null || k.value === '';
  var v = empty ? '—' : (k.html ? String(k.value) : esc(k.value));
  var sub = k.sub === undefined || k.sub === null || k.sub === '' ? '' : (k.html ? String(k.sub) : esc(k.sub));
  var spark = k.trend && k.trend.length > 1 ? '<div class="qk-stat-trend">' + QK.spark(k.trend, { color: k.trendColor || 'var(--signal)', w: 160, h: 30, label: k.trendLabel }) + '</div>' : '';
  var lab = k.tip ? '<span data-tip="' + esc(k.tip) + '"' + (k.href ? '' : ' tabindex="0"') + '>' + esc(k.label) + '</span>' : '<span>' + esc(k.label) + '</span>';
  /* v4: the percentile sits under the number as a square chip, "97th pctl", on the scale's colour */
  var pc = isNum(k.pctl) ? '<div class="qk-stat-pc"><span class="qk-pctl" style="background:' + QK.pctColor(k.pctl) + ';color:' + QK.pctInk(k.pctl) + '" title="' + esc(QK.ordinal(Math.round(k.pctl))) + ' percentile among peers">' + esc(QK.ordinal(Math.round(k.pctl))) + ' pctl</span></div>' : '';
  var long = k.text && String(k.value || '').length > 14 ? ' qk-long' : '';
  return '<' + tag + ' class="qk-stat' + (k.cls ? ' ' + esc(k.cls) : '') + '"' + (k.href ? ' href="' + esc(k.href) + '"' : '') + '>' +
    '<div class="qk-stat-label">' + lab + '</div>' +
    '<div class="qk-stat-v' + (k.signal ? ' signal' : '') + (k.text ? ' text' : '') + long + '">' + v + (k.unit && !empty ? '<span class="u">' + esc(k.unit) + '</span>' : '') + '</div>' + pc +
    (dl || sub ? '<div class="qk-stat-sub">' + dl + (sub ? '<span>' + sub + '</span>' : '') + '</div>' : '') + spark + '</' + tag + '>';
};
QK.stats = function (list) {
  return '<div class="qk-stats">' + (list || []).filter(Boolean).map(function (x) { return typeof x === 'string' ? x : QK.statTile(x); }).join('') + '</div>';
};
/* QK.statStrip([tile objects or HTML], { bleed: true }) -> the black strip of big numbers that runs under a hero, edge
 * to edge (the player page's "points · goals · assists · pace · minutes"). */
QK.statStrip = function (list, o) {
  o = o || {};
  return '<div class="qk-strip' + (o.bleed === false ? '' : ' qk-bleed') + '"><div class="qk-strip-in">' + QK.stats(list) + '</div></div>';
};

/* ─────────────────────────────────────── player card header */
/* QK.playerHeader({ name, number, pos, team: { name, abbr, colour, href }, kicker, meta: [[label, value] | html | text],
 * stats: [{ label, value, sub }], tags: [html], short: 'plain-English summary' | { title, text, html } (v3: "The short
 * version" on the right; the stats then belong in a QK.stats row below), face: 'text for the tile' (default the
 * number, else initials), split (ignored in v3: the name is one display line) })
 * v3 look: a tilted tile in the team colour with a sun shadow, the kicker, the name, chips (position, team, age ...),
 * then "The short version" or the headline stats. */
/* v4 options: strip: [statTile objects] (the black strip of big numbers under the hero; o.stats render there too when
 * no strip is given), bleed: false (keep the hero inside the page width), alt: hex (the panel on the right; default
 * team.alt, else a darker shade of the team colour). The hero: the team colour as a full-bleed block (white type
 * >= 4.5:1 through QK.color.block; a pale kit becomes slate with a rule in its colour), the alternate colour on a
 * diagonal at the right behind a volt stripe, the jersey number huge and outlined (initials when there is none), the
 * name in Bebas on two lines (Barlow Condensed when it is long), chips. "The short version" follows as the explain
 * strip. Tennis and other no-team pages: the cobalt block (no colour given). */
QK.playerHeader = function (o) {
  o = o || {};
  var t = o.team || {};
  var hex = color.parse(t.colour) ? t.colour : (color.parse(o.colour) ? o.colour : null);
  var bk = hex ? color.block(hex) : { bg: cssVar('--signal-deep') || '#5a69b7', edge: null };
  var altHex = o.alt || t.alt;
  var alt = color.parse(altHex) && color.distinct(color.deep(altHex), bk.bg) ? color.deep(altHex) : color.mix(bk.bg, '#000000', 0.38);
  var nm = String(o.name || '');
  var num = o.face !== undefined && o.face !== null ? String(o.face) : (isNum(o.number) || /^\d+$/.test(String(o.number || '')) ? String(o.number) : fmt.initials(nm));
  var chips = [];
  if (isNum(o.number) || /^\d+$/.test(String(o.number || ''))) chips.push('<span>#' + esc(o.number) + '</span>');
  if (o.pos) chips.push('<span>' + esc(o.pos) + '</span>');
  if (t.name) chips.push('<span class="team">' + (t.href ? '<a href="' + esc(t.href) + '">' + esc(t.name) + '</a>' : esc(t.name)) + '</span>');
  (o.meta || []).filter(Boolean).forEach(function (m) {
    if (Array.isArray(m)) chips.push('<span>' + esc(m[0]) + ' <b>' + esc(m[1]) + '</b></span>');
    else chips.push('<span>' + (/<[a-z]/i.test(String(m)) ? m : esc(m)) + '</span>');
  });
  /* the name on two lines: given names, then the family name (a suffix stays with it: "Bobby / Witt Jr.") */
  var sur = QK.surname(nm).replace(/ /g, ' '), first = sur && nm.length > sur.length ? nm.slice(0, nm.length - sur.length).trim() : '';
  var nameH = first ? esc(first) + '<br>' + esc(sur) : esc(nm);
  var long = QK.longName(first.length > sur.length ? first : sur, 13) || (nm.length > 26 ? ' qk-long' : '');
  var strip = o.strip && o.strip.length ? o.strip : (o.stats || []).filter(Boolean).map(function (x) { return { label: x.label, value: x.value, sub: x.sub }; });
  return '<section class="qk-ph' + (o.bleed === false ? '' : ' qk-bleed') + '" style="--tb:' + esc(bk.bg) + ';--ta:' + esc(alt) + (bk.edge ? ';--te:' + esc(bk.edge) : '') + '">' +
    '<div class="qk-ph-bg" aria-hidden="true"></div><div class="qk-ph-in"><div class="qk-ph-main">' +
    (o.kicker ? '<div class="qk-ph-kicker">' + esc(o.kicker) + '</div>' : '') + '<h1 class="qk-ph-name' + long + '">' + nameH + '</h1>' +
    (chips.length ? '<div class="qk-ph-meta">' + chips.join('') + '</div>' : '') + ((o.tags || []).length ? '<div class="qk-ph-tags">' + o.tags.join('') + '</div>' : '') + '</div>' +
    '<div class="qk-ph-num qk-outline num' + (num.length > 2 ? ' txt' : '') + '" aria-hidden="true">' + esc(num) + '</div></div></section>' +
    (strip.length ? QK.statStrip(strip, { bleed: o.bleed !== false }) : '') +
    (o.short ? '<div class="qk-ph-short">' + QK.shortVersion(o.short) + '</div>' : '');
};
/* QK.longName(name, max) -> ' qk-long' when a name is too long for Bebas at display size (Barlow Condensed in
 * capitals instead), else ''. max: characters (default 16). */
QK.longName = function (name, max) { return String(name || '').length > (max || 16) ? ' qk-long' : ''; };
/* QK.outlineNum(n, { cls, size }) -> an outlined Bebas number (a jersey number, a rank). */
QK.outlineNum = function (n, o) { o = o || {}; return '<span class="qk-outline qk-display' + (o.cls ? ' ' + esc(o.cls) : '') + '"' + (o.size ? ' style="font-size:' + esc(o.size) + '"' : '') + ' aria-hidden="true">' + esc(n) + '</span>'; };

/* ─────────────────────────────────────── percentile card (Savant style, v3 rail) */
/* QK.pctCard({ title, kicker, peer: 'NHL forwards', sample: '7 GP · 117 min at 5v5', groups: [{ label, rows: [{ label,
 * pctl, value, sub, prev, tip, early }] }], note, foot, right (HTML in the head), id, cls, ringLabel: 'last season
 * (80 games)', key: false }). The peer group and sample are always shown; a row marked early (below the sample where
 * the metric settles) gets a dashed knob and a footnote; rows with prev get the hollow last-season ring.
 * QK.pctRail(o) is the same card (the v3 name). */
QK.pctCard = function (o) {
  o = o || {};
  var early = false, ring = false;
  var groups = (o.groups || []).map(function (g) {
    var rows = (g.rows || []).filter(function (r) { return r && isNum(r.pctl); });
    rows.forEach(function (r) { if (r.early) early = true; if (isNum(r.prev)) ring = true; });
    return rows.length ? '<div class="qk-pgrp">' + (g.label ? '<div class="qk-pgrp-h">' + esc(g.label) + '</div>' : '') + QK.pctlBars(rows) + '</div>' : '';
  }).join('');
  var head = '<div class="qk-card-head"><div style="min-width:0">' + (o.kicker ? '<div class="qk-kicker" style="margin-bottom:8px">' + esc(o.kicker) + '</div>' : '') + '<div class="qk-card-title">' + esc(o.title || 'Percentile rankings') + '</div>' +
    '<div class="qk-pcard-peer">' + (o.peer ? QK.tag('Peers: ' + o.peer, 'signal') : '') + (o.sample ? '<span>' + esc(o.sample) + '</span>' : '') + '</div></div>' + (o.right || '') + '</div>';
  var body = groups ? groups + (o.key === false ? '' : QK.pctKey({ ring: ring, ringLabel: o.ringLabel })) +
    (early ? '<div class="qk-pnote">A dashed box marks a metric still short of the sample where it settles down: read it as early.</div>' : '') +
    (o.note ? '<div class="qk-pnote">' + esc(o.note) + '</div>' : '')
    : QK.empty(o.emptyTitle || 'Not enough data yet', o.emptyText || 'Percentiles appear once the sample floors are met.');
  return '<section class="qk-card qk-pcard' + (o.cls ? ' ' + esc(o.cls) : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' + head +
    '<div class="qk-card-body">' + body + '</div>' + (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
QK.pctRail = function (o) { return QK.pctCard(o); };

/* ─────────────────────────────────────── leaderboard */
/* QK.leaderboard(el, spec): QK.table with column types —
 *   { type: 'entity', key, sub: 'key', mark: fn(row) -> team, href: fn(row) }   name, team mark, sub-line (pinned)
 *   { type: 'pctl', key, pctl: 'pct_key', fmt, d, style }                         value on a percentile heat cell (style: neutral)
 *   { type: 'bar', key, fmt, max }                                                value with an inline bar
 *   { type: 'spark', key }                                                        an array as a sparkline (not sortable)
 * plus spec.rowClass(row) and spec.rowHref(row) (both also work on QK.table). Returns the QK.table handle. */
QK.leaderboard = function (el, spec) {
  var rows = spec.rows || [];
  var cols = spec.columns.map(function (c) {
    var d = {}, k;
    for (k in c) if (Object.prototype.hasOwnProperty.call(c, k)) d[k] = c[k];
    var f0 = typeof c.fmt === 'function' ? c.fmt : null;
    var txt = function (v, r) { return f0 ? f0(v, r) : (isNum(v) ? fmt.num(v, c.d || 0) : esc(v === undefined || v === null ? '—' : v)); };
    if (c.type === 'entity') {
      d.sticky = c.sticky !== false;
      d.fmt = function (v, r) {
        var href = c.href ? c.href(r) : r.href;
        var inner = (c.mark ? QK.teamMark(c.mark(r) || {}, 'sm') : '') + '<span style="min-width:0"><span class="qk-entity-name">' + esc(v) + '</span>' + (c.sub && r[c.sub] ? ' <span class="qk-entity-meta">' + esc(r[c.sub]) + '</span>' : '') + '</span>';
        return href ? '<a class="qk-entity" href="' + esc(href) + '">' + inner + '</a>' : '<span class="qk-entity">' + inner + '</span>';
      };
    } else if (c.type === 'pctl') {
      d.num = true; d.pctl = null;
      d.fmt = function (v, r) {
        var p = r[c.pctl], t = txt(v, r);
        return isNum(p) ? '<span class="qk-pcell" style="background:' + (c.style ? 'var(--s-3)' : QK.pctColor(p)) + ';color:' + (c.style ? 'var(--ink-1)' : QK.pctInk(p)) + '" title="' + esc(QK.ordinal(p)) + ' percentile' + (c.style ? ' (style: neither better nor worse)' : '') + '">' + t + '</span>' : t;
      };
    } else if (c.type === 'bar') {
      d.num = true;
      var mx = isNum(c.max) ? c.max : Math.max.apply(null, rows.map(function (r) { return Math.abs(r[c.key]) || 0; }).concat([1e-9]));
      d.fmt = function (v, r) { return '<span class="qk-barcell">' + txt(v, r) + '<i aria-hidden="true"><b style="width:' + (isNum(v) ? Math.min(100, 100 * Math.abs(v) / mx) : 0).toFixed(1) + '%"></b></i></span>'; };
    } else if (c.type === 'spark') {
      d.sort = false;
      d.fmt = function (v) { return '<span class="qk-sparkcell">' + (QK.spark(v, { w: 80, h: 22, color: c.color || 'var(--signal)', area: false, label: c.label }) || '—') + '</span>'; };
    }
    return d;
  });
  var s2 = {}, kk;
  for (kk in spec) if (Object.prototype.hasOwnProperty.call(spec, kk)) s2[kk] = spec[kk];
  s2.columns = cols;
  return QK.table(el, s2);
};

/* ─────────────────────────────────────── comparison view */
/* QK.compareView({ entities: [{ name, sub, colour, href }] (2 or 3), groups: [{ label, rows: [{ label, values: [..],
 * pctls: [..] (100 = best in the peer group, already oriented), better: 'high' | 'low', fmt(v), dfmt(delta), tip }] }],
 * delta: true (two entities: A minus B, green when A is better), metricLabel }) -> HTML.
 * The better value in each row is bold; the header counts the rows each one wins. */
var CMP_FALLBACK = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];
/* v4: two entities draw the tale of the tape (QK.tape) unless o.layout === 'table' (the v3 grid, with the delta
 * column); three keep the grid, restyled. */
QK.compareView = function (o) {
  o = o || {};
  var E0 = (o.entities || []).slice(0, 3);
  if (E0.length === 2 && o.layout !== 'table') {
    return QK.tape({ left: E0[0], right: E0[1], wins: true, fav: o.fav, groups: (o.groups || []).map(function (g) {
      return { label: g.label, rows: (g.rows || []).filter(function (r) { return r && (r.values || []).some(isNum); }).map(function (r) {
        var f = r.fmt || function (v) { return isNum(v) ? fmt.num(v, r.d === undefined ? 2 : r.d) : '—'; };
        var vv = r.values || [], pp = r.pctls || [];
        return { label: r.label, tip: r.tip, a: vv[0], b: vv[1], pa: pp[0], pb: pp[1], ta: f(vv[0]), tb: f(vv[1]), better: r.better };
      }) };
    }), empty: QK.empty('Nothing to compare', 'These players share no metrics with values this season.') });
  }
  var E = E0, n = E.length, delta = o.delta !== false && n === 2;
  var wins = E.map(function () { return 0; }), total = 0;
  var cols = [];
  E.forEach(function (e, i) {
    var c = e.colour && color.parse(e.colour) ? color.team(e.colour) : null;
    for (var j = 0; j < cols.length; j++) if (c && cols[j].charAt(0) === '#' && !color.distinct(c, cols[j])) c = null;
    cols.push(c || CMP_FALLBACK[i]);
  });
  var body = (o.groups || []).map(function (g) {
    var rs = (g.rows || []).filter(function (r) { return r && (r.values || []).some(isNum); });
    if (!rs.length) return '';
    return (g.label ? '<div class="qk-cmp-grp">' + esc(g.label) + '</div>' : '') + rs.map(function (r) {
      var vals = r.values || [], pc = r.pctls || [], lower = r.better === 'low';
      var f = r.fmt || function (v) { return isNum(v) ? fmt.num(v, r.d === undefined ? 2 : r.d) : '—'; };
      var score = E.map(function (_, i) { return isNum(pc[i]) ? pc[i] : (isNum(vals[i]) ? (lower ? -vals[i] : vals[i]) : null); });
      var best = -1, bv = null, tie = false;
      score.forEach(function (sc, i) { if (!isNum(sc)) return; if (bv === null || sc > bv + 1e-12) { bv = sc; best = i; tie = false; } else if (Math.abs(sc - bv) <= 1e-12) tie = true; });
      if (best >= 0) { total++; if (!tie) wins[best]++; }
      var cells = E.map(function (e, i) {
        var p = pc[i];
        return '<div class="qk-cmp-cell' + (i === best && !tie ? ' best' : '') + '"><span class="v">' + f(vals[i]) + '</span>' +
          '<span class="qk-cmp-pb" aria-hidden="true">' + (isNum(p) ? '<i style="width:' + Math.max(3, Math.min(100, p)) + '%;background:' + QK.pctColor(p) + '"></i>' : '') + '</span>' +
          '<span class="p"' + (isNum(p) ? ' title="' + esc(QK.ordinal(p)) + ' percentile" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '"' : '') + '>' + (isNum(p) ? Math.round(p) : '') + '</span></div>';
      }).join('');
      var d = '';
      if (delta) {
        var dv = isNum(vals[0]) && isNum(vals[1]) ? vals[0] - vals[1] : null;
        var good = isNum(dv) ? (lower ? -dv : dv) : 0;
        var dtxt = !isNum(dv) ? '—' : r.dfmt ? r.dfmt(dv) : (dv > 0 ? '+' : dv < 0 ? '−' : '±') + String(f(Math.abs(dv))).replace(/^[+−-]/, '');
        d = '<div class="qk-cmp-d ' + (!isNum(dv) || Math.abs(dv) < 1e-12 ? 'flat' : good > 0 ? 'up' : 'down') + '">' + dtxt + '</div>';
      }
      return '<div class="qk-cmp-row"><div class="qk-cmp-lab"' + (r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : '') + '>' + esc(r.label) + '</div>' + cells + d + '</div>';
    }).join('');
  }).join('');
  var short = function (e) { return e.abbr || QK.surname(e.name); };
  var head = '<div class="qk-cmp-head"><div class="qk-cmp-dh" style="text-align:left">' + esc(o.metricLabel || 'Metric · value · percentile') + '</div>' + E.map(function (e, i) {
    var nm = '<b>' + esc(e.name) + '</b>';
    /* the head block carries white type: the team colour (or the fallback) as a block, its lifted colour as the rule */
    var eb = color.block(e.colour && color.parse(e.colour) ? e.colour : (i === 0 ? '#7d93ff' : i === 1 ? null : '#c39be8')).bg;
    return '<div class="qk-cmp-ent" style="--ec:' + cols[i] + ';--eb:' + eb + '">' + (e.href ? '<a class="qk-cmp-a" href="' + esc(e.href) + '">' + nm + '</a>' : nm) + '<small>' + esc(e.sub || '') + '</small>' +
      (total ? '<span class="wins">Better on ' + wins[i] + ' of ' + total + '</span>' : '') + '</div>';
  }).join('') + (delta ? '<div class="qk-cmp-dh" title="' + esc(E[0].name) + ' minus ' + esc(E[1].name) + '">Δ ' + esc(short(E[0])) + '</div>' : '') + '</div>';
  return '<div class="qk-cmp' + (delta ? '' : ' nodelta') + (n === 3 ? ' n3' : '') + '" style="--n:' + n + '">' + head + (body || QK.empty('Nothing to compare', 'These players share no metrics with values this season.')) + '</div>';
};

/* ─────────────────────────────────────── the tale of the tape (v4) */
/* QK.tape({ left: { name, short, sub, colour, alt, href }, right: {...}, fav: 'a' | 'b' (with no colours the side we
 * favour is cobalt, as on the hero), groups: [{ label, rows }] | rows: [{ label, a, b (numbers), ta, tb (their text;
 * default fmt), pa, pb (percentiles 0-100, already oriented: 100 = best), better:
 * 'high' | 'low', tip, fmt }], wins: true ("Better on 9 of 14" under each name), colors: [l, r] (bar colours),
 * key: false, empty }) -> the two blocks with a volt VS, then a row per metric: the value, a bar growing out to its
 * side (the percentile when given, else the value's share of the larger), the label in the middle. The better
 * number in each row is solid, the other dimmed. Blocks follow QK.color.blockPair; bars take the team colours
 * lifted to 3:1 on the card, distinct, else cobalt v grey. */
QK.tape = function (o) {
  o = o || {};
  var L = o.left || {}, R = o.right || {};
  var blocks = color.blockPair(L, R, { fav: o.fav });
  var sw = o.fav === 'b' && !color.parse(L.colour) && !color.parse(R.colour);   /* the tennis rule: the favourite is cobalt */
  var bl = o.colors && o.colors[0] ? o.colors[0] : (color.parse(L.colour) ? color.team(L.colour) : (sw ? 'var(--wp-b)' : 'var(--wp-a)'));
  var br = o.colors && o.colors[1] ? o.colors[1] : (color.parse(R.colour) ? color.team(R.colour) : (sw ? 'var(--wp-a)' : 'var(--wp-b)'));
  if (!(o.colors && o.colors[1]) && bl.charAt(0) === '#' && br.charAt(0) === '#' && !color.distinct(bl, br)) br = color.parse(R.alt) && color.distinct(bl, color.team(R.alt)) ? color.team(R.alt) : 'var(--wp-b)';
  if (bl === br) br = 'var(--wp-b)';
  var groups = o.groups || [{ label: '', rows: o.rows || [] }];
  var wins = [0, 0], total = 0;
  var body = groups.map(function (g) {
    var rs = (g.rows || []).filter(function (r) { return r && (isNum(r.a) || isNum(r.b)); });
    if (!rs.length) return '';
    return (g.label ? '<div class="qk-tape-grp">' + esc(g.label) + '</div>' : '') + rs.map(function (r) {
      var f = r.fmt || function (v) { return isNum(v) ? fmt.num(v, Math.abs(v) < 10 && v % 1 ? 2 : 0) : '—'; };
      var lower = r.better === 'low';
      var sa = isNum(r.pa) && isNum(r.pb) ? r.pa : (isNum(r.a) ? (lower ? -r.a : r.a) : null);
      var sb = isNum(r.pa) && isNum(r.pb) ? r.pb : (isNum(r.b) ? (lower ? -r.b : r.b) : null);
      var win = isNum(sa) && isNum(sb) && Math.abs(sa - sb) > 1e-12 ? (sa > sb ? 'a' : 'b') : '';
      if (isNum(sa) && isNum(sb)) { total++; if (win) wins[win === 'a' ? 0 : 1]++; }
      var wa, wb;
      if (isNum(r.pa) || isNum(r.pb)) { wa = isNum(r.pa) ? r.pa : 0; wb = isNum(r.pb) ? r.pb : 0; }
      else {
        var a = isNum(r.a) ? r.a : 0, b = isNum(r.b) ? r.b : 0, s;
        if (a >= 0 && b >= 0) s = a + b > 0 ? a / (a + b) : 0.5; else s = 0.5 + (a - b) / (2 * ((Math.abs(a) + Math.abs(b)) || 1));
        if (lower) s = 1 - s;
        s = Math.max(0.04, Math.min(0.96, s));
        var m = Math.max(s, 1 - s); wa = 100 * s / m; wb = 100 * (1 - s) / m;
      }
      wa = Math.max(3, Math.min(100, wa)); wb = Math.max(3, Math.min(100, wb));
      var ta = r.ta !== undefined ? r.ta : f(r.a), tb = r.tb !== undefined ? r.tb : f(r.b);
      var aria = r.label + ': ' + (L.short || L.name || 'left') + ' ' + ta + (isNum(r.pa) ? ' (' + QK.ordinal(Math.round(r.pa)) + ' percentile)' : '') + ', ' + (R.short || R.name || 'right') + ' ' + tb + (isNum(r.pb) ? ' (' + QK.ordinal(Math.round(r.pb)) + ' percentile)' : '');
      return '<div class="qk-tape-r" role="group" aria-label="' + esc(aria) + '"><span class="v num' + (win === 'b' ? ' lose' : '') + '">' + esc(ta) + '</span>' +
        '<span class="b lft" aria-hidden="true"><i class="' + (win === 'b' ? 'dim' : '') + '" style="width:' + wa.toFixed(1) + '%;background:' + bl + '"></i></span>' +
        '<span class="lb"' + (r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : '') + '>' + esc(r.label) + '</span>' +
        '<span class="b" aria-hidden="true"><i class="' + (win === 'a' ? 'dim' : '') + '" style="width:' + wb.toFixed(1) + '%;background:' + br + '"></i></span>' +
        '<span class="v rt num' + (win === 'a' ? ' lose' : '') + '">' + esc(tb) + '</span></div>';
    }).join('');
  }).join('');
  function side(e, i, cls) {
    var b = blocks[i], nm = e.short || QK.surname(e.name || '') || e.name || '';
    var inner = (e.sub ? '<small>' + esc(e.sub) + '</small>' : '') + '<b class="' + QK.longName(nm, 12).trim() + '"' + (e.name && e.name !== nm ? ' title="' + esc(e.name) + '"' : '') + '>' + esc(nm) + '</b>' +
      (o.wins !== false && total ? '<span class="wins">Better on ' + wins[i] + ' of ' + total + '</span>' : '');
    var st = ' style="--ec:' + esc(b.bg) + (b.edge ? ';--te:' + esc(b.edge) : '') + '"';
    return e.href ? '<a class="t' + cls + '" href="' + esc(e.href) + '"' + st + '>' + inner + '</a>' : '<div class="t' + cls + '"' + st + '>' + inner + '</div>';
  }
  var head = '<div class="qk-tape-head">' + side(L, 0, '') + '<div class="vs" aria-hidden="true">VS</div>' + side(R, 1, ' r') + '</div>';
  var key = o.key === false || !body ? '' : '<div class="qk-tape-key"><span>' + esc(L.short || QK.surname(L.name || '') || '') + '</span><span>' + esc(o.keyText || (groups.some(function (g) { return (g.rows || []).some(function (r) { return r && isNum(r.pa); }); }) ? 'Bar = percentile · the better number is solid' : 'The better side of each row is solid')) + '</span><span>' + esc(R.short || QK.surname(R.name || '') || '') + '</span></div>';
  return '<div class="qk-tape">' + head + '<div class="qk-tape-body">' + (body || o.empty || QK.empty('Nothing to compare')) + key + '</div></div>';
};

/* ─────────────────────────────────────── matchup bar (tale of the tape) */
/* QK.matchupBar({ left: team, right: team, rows: [{ label, a, b, fmt, better: 'high' | 'low', tip }], colors: [l, r] })
 * v4: drawn as the tale of the tape (QK.tape) with the teams' blocks; o.layout === 'bars' keeps the v2 split bars. */
QK.matchupBar = function (o) {
  o = o || {};
  if (o.layout !== 'bars') {
    var LL = o.left || {}, RR = o.right || {};
    return QK.tape({ left: { name: LL.name, short: LL.abbr || LL.name, sub: LL.record || LL.sub || '', colour: LL.colour, alt: LL.alt, href: LL.href },
      right: { name: RR.name, short: RR.abbr || RR.name, sub: RR.record || RR.sub || '', colour: RR.colour, alt: RR.alt, href: RR.href },
      colors: o.colors, fav: o.fav, wins: false, rows: (o.rows || []).filter(function (r) { return r && isNum(r.a) && isNum(r.b); }).map(function (r) {
        var f = r.fmt || function (v) { return fmt.num(v, 2); };
        return { label: r.label, a: r.a, b: r.b, ta: f(r.a), tb: f(r.b), better: r.better, tip: r.tip };
      }) });
  }
  var L = o.left || {}, R = o.right || {};
  var lc = o.colors && o.colors[0] ? o.colors[0] : QK.probColour(L, R, 'left'), rc = o.colors && o.colors[1] ? o.colors[1] : QK.probColour(R, L, 'right');
  var rows = (o.rows || []).filter(function (r) { return r && isNum(r.a) && isNum(r.b); }).map(function (r) {
    var f = r.fmt || function (v) { return fmt.num(v, 2); };
    var a = r.a, b = r.b, sa;
    if (a >= 0 && b >= 0) sa = a + b > 0 ? a / (a + b) : 0.5;
    else sa = 0.5 + (a - b) / (2 * ((Math.abs(a) + Math.abs(b)) || 1));
    sa = Math.max(0.04, Math.min(0.96, sa));
    var win = Math.abs(a - b) < 1e-12 ? '' : ((r.better === 'low') === (a < b) ? 'a' : 'b');
    return '<div class="qk-mu-row"><span class="qk-mu-v' + (win === 'a' ? ' win' : '') + '">' + f(a) + '</span><div class="qk-mu-mid"><span class="qk-mu-lab"' + (r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : '') + '>' + esc(r.label) + '</span>' +
      '<div class="qk-mu-bar" role="img" aria-label="' + esc(r.label + ': ' + (L.abbr || L.name || 'left') + ' ' + f(a) + ', ' + (R.abbr || R.name || 'right') + ' ' + f(b)) + '"><span class="' + (win === 'a' ? 'win' : '') + '" style="flex:' + sa.toFixed(3) + ';background:' + lc + '"></span><span class="' + (win === 'b' ? 'win' : '') + '" style="flex:' + (1 - sa).toFixed(3) + ';background:' + rc + '"></span></div></div>' +
      '<span class="qk-mu-v r' + (win === 'b' ? ' win' : '') + '">' + f(b) + '</span></div>';
  }).join('');
  return '<div class="qk-mu"><div class="qk-mu-head"><span>' + QK.teamMark(L, 'sm') + esc(L.abbr || L.name || '') + '</span><span>' + esc(R.abbr || R.name || '') + QK.teamMark(R, 'sm') + '</span></div>' + rows + '</div>';
};


/* ═══════════════════════════════════════ v3 "Matchday" builders (STYLE_GUIDE.md §5, MIGRATION_V3.md) ═══ */

/* ─────────────────────────────────────── notes, asides, the highlighter */
/* QK.note(html, { cls }) — the "i" explainer: one or two friendly sentences on what a number means. HTML in. */
QK.note = function (html, o) { o = o || {}; return '<div class="qk-note' + (o.cls ? ' ' + esc(o.cls) : '') + '"><span>' + String(html || '') + '</span></div>'; };
/* QK.aside(text) — the italic aside with a coral arrow: a one-line reason, a note beside a number. Text in. */
QK.aside = function (txt, o) { o = o || {}; return '<div class="qk-aside' + (o.cls ? ' ' + esc(o.cls) : '') + '">' + (o.html ? String(txt || '') : esc(txt)) + '</div>'; };
/* QK.mark(text) — the sun highlighter under a phrase (headlines, a key word). Text in. */
QK.mark = function (txt) { return '<span class="qk-mark">' + esc(txt) + '</span>'; };

/* ─────────────────────────────────────── greeting hero */
/* QK.greet(date) -> 'Good morning' | 'Good afternoon' | 'Good evening' by the viewer's local hour. */
QK.greet = function (d) {
  var h = (d || new Date(QK.now())).getHours();
  return h >= 5 && h < 12 ? 'Good morning' : h >= 12 && h < 18 ? 'Good afternoon' : 'Good evening';
};
/* QK.greeting({ date: 'Saturday 17 October · eight sports, one place' (kicker; default today's date), title: HTML
 * (default '<greet>! Here's what's <mark>worth watching</mark> today.'), lede, ctas: [{ label, href, ghost }],
 * side: HTML (a QK.featureCard, usually), id }) -> the hero section. */
QK.greeting = function (o) {
  o = o || {};
  var now = new Date(QK.now());
  var date = o.date !== undefined ? o.date : now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  var title = o.title || (esc(QK.greet(now)) + '! Here’s what’s ' + QK.mark('worth watching') + ' ' + (now.getHours() >= 15 || now.getHours() < 5 ? 'tonight' : 'today') + '.');
  var ctas = (o.ctas || []).map(function (c) { return '<a class="qk-btn ' + (c.ghost ? 'ghost' : 'primary') + '" href="' + esc(c.href || '#') + '">' + esc(c.label) + '</a>'; }).join('');
  /* v4: a broadcast lower third (the date tag, the line in Bebas, the lede, the buttons), the side (QK.featureCard:
   * the diagonal hero) full width under it */
  return '<section class="qk-greet' + (o.side ? '' : ' solo') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-greet-head"><div style="min-width:0">' +
    (date ? '<div class="qk-greet-date">' + esc(date) + '</div>' : '') + '<h1>' + title + '</h1>' +
    (o.lede ? '<p class="qk-lede">' + esc(o.lede) + '</p>' : '') + '</div>' + (ctas ? '<div class="qk-greet-cta">' + ctas + '</div>' : '') + '</div>' +
    (o.side ? '<div class="qk-greet-side">' + o.side + '</div>' : '') + '</section>';
};

/* ─────────────────────────────────────── the score bug (broadcast) */
/* QK.scorebug(g, { compact: true (no 'ours' label), size: 'lg', chance: false }) -> a black bug for a live game:
 * the period and clock, both teams with their score on a team-colour edge, and our live chance for the side ahead
 * in it. Returns the plain status badge for a game that is not live. */
/* o.homeFirst: the home side first (football reads "Home v Away"). */
QK.scorebug = function (g, o) {
  o = o || {};
  if (o.size === 'xl') return QK.scorebugXL(g, o);
  if (!g || g.status !== 'live') return QK.statusBadge(g || {});
  var per = QK.periodLabel(g);
  var clk = (per || 'Live') + (g.clock ? ' ' + g.clock : '');
  var A = g.away || {}, H = g.home || {};
  var ca = QK.probColour(A, H, 'left'), ch = QK.probColour(H, A, 'right');
  var p = QK.liveP(g), fav = null;
  if (isNum(p) && !g.pre_only && !isNum(g.p_draw)) fav = p >= 0.5 ? [H, p] : [A, 1 - p];
  var tmA = '<span class="tm" style="--tc:' + ca + '">' + esc(QK.shortName(A)) + ' <b>' + (isNum(g.as) ? esc(g.as) : '–') + '</b></span>';
  var tmH = '<span class="tm" style="--tc:' + ch + '">' + esc(QK.shortName(H)) + ' <b>' + (isNum(g.hs) ? esc(g.hs) : '–') + '</b></span>';
  return '<span class="qk-bug' + (o.size === 'lg' ? ' lg' : '') + '" role="img" aria-label="' + esc('Live, ' + clk + ': ' + (A.name || '') + ' ' + (isNum(g.as) ? g.as : '') + ', ' + (H.name || '') + ' ' + (isNum(g.hs) ? g.hs : '') + (fav ? '; our live chance ' + (fav[0].name || '') + ' ' + fmt.pct(fav[1]) : '')) + '">' +
    '<span class="clk">' + esc(clk) + '</span>' +
    (o.homeFirst ? tmH + tmA : tmA + tmH) +
    (fav && o.chance !== false && !o.compact ? '<span class="ch"><small>ours</small>' + esc(fav[0].abbr || fav[0].name || '') + ' ' + fmt.pct(fav[1]) + '</span>' : '') + '</span>';
};

/* QK.scorebugXL(g, { nick, homeFirst, bar: true, market: 'quiet' (round 6: before the start, the market's chances in a
 * small grey line under the bar, the source on hover, g.market_home / market_src) }) (= QK.scorebug(g, { size: 'xl' })) -> the scoreboard bug for any
 * game: both teams as blocks (QK.color.blockPair) with the abbreviation, the name and record, and our chance (live:
 * the score), the start time, the clock or "Final" in black between; then the bar in the two colours. */
QK.scorebugXL = function (g, o) {
  o = o || {};
  if (!g) return '';
  var live = g.status === 'live', fin = g.status === 'final';
  var A = g.away || {}, H = g.home || {};
  var hf = o.homeFirst !== undefined ? !!o.homeFirst : !!(PREVIEW_WORDS[g.sport] || {}).homeFirst;
  var nk = o.nick || function (t) { return t.name || t.abbr || ''; };
  var pH = live ? QK.liveP(g) : (fin ? QK.preP(g) : g.p_home);
  var pD = live && isNum(g.wp_home) ? null : g.p_draw;
  var pA = live && isNum(g.wp_home) ? 1 - g.wp_home : (isNum(g.p_away) && !live ? g.p_away : (isNum(pH) ? 1 - pH - (isNum(pD) ? pD : 0) : null));
  var Ls = hf ? H : A, Rs = hf ? A : H, pL = hf ? pH : pA, pR = hf ? pA : pH, sL = hf ? g.hs : g.as, sR = hf ? g.as : g.hs;
  var f = favOf(g), fav = f ? (f.t === Ls ? 'a' : 'b') : null;
  var bp = color.blockPair(Ls, Rs, { fav: fav });
  function tm(t, b, p, sc, cls) {
    var big = live || fin ? (isNum(sc) ? esc(sc) : '–') : (isNum(p) ? QK.pctSmall(p) : '');
    return '<div class="tm' + cls + '" style="--tb:' + esc(b.bg) + (b.edge ? ';--te:' + esc(b.edge) : '') + '"><span class="ab">' + esc(QK.shortName(t)) + '</span><span class="nm">' + esc(nk(t)) + (t.record ? '<br>' + esc(t.record) : '') + '</span><span class="p num">' + big + '</span></div>';
  }
  var md = live ? '<div class="md live">' + esc(QK.periodLabel(g) || 'Live') + '<b class="num">' + esc(g.clock || 'Live') + '</b></div>'
    : fin ? '<div class="md">Final<b class="num">' + (isNum(sL) && isNum(sR) ? esc(sL) + '–' + esc(sR) : '–') + '</b></div>'
    : '<div class="md">' + esc(fmt.relDay(g.start) === 'Today' ? 'Tonight' : fmt.relDay(g.start)) + '<b class="num">' + esc(g.tba ? 'TBA' : fmt.time(g.start)) + '</b>' + esc(g.league || '') + '</div>';
  var aria = (live ? 'Live' : fin ? 'Final' : 'Upcoming') + ': ' + (Ls.name || '') + ' ' + (live || fin ? (isNum(sL) ? sL : '') : fmt.pct(pL)) + ', ' + (Rs.name || '') + ' ' + (live || fin ? (isNum(sR) ? sR : '') : fmt.pct(pR));
  var bar = o.bar !== false && !fin && isNum(pL) && isNum(pR) ? QK.wpBar(pL, pD, pR, Ls, Rs, { labels: false, colors: [color.ensure(bp[0].bg, '#000000', 3), color.ensure(bp[1].bg, '#000000', 3)], label: live ? 'Live win chance' : 'Our win chance' }) : '';
  /* market: 'quiet' (round 6): before the start, the market's chances in one small grey line under the bar */
  var mq = o.market === 'quiet' && !live && !fin ? QK.marketLine(g, { homeFirst: hf, cls: 'qk-bugxl-mq', source: o.marketSource, mark: o.marketMark }) : '';
  return '<div class="qk-bugxl" role="group" aria-label="' + esc(aria) + '">' + tm(Ls, bp[0], pL, sL, '') + md + tm(Rs, bp[1], pR, sR, ' h') + '</div>' + bar + mq;
};

/* ─────────────────────────────────────── why it is worth watching */
/* QK.whyLine(g) -> one friendly line on a game, from our numbers only (no market): a coin flip, a clear favourite and
 * how often that still goes wrong, a live game the score has moved, a series note. A builder's g.why wins. */
function favOf(g) {
  var pH = g.status === 'live' ? QK.liveP(g) : g.p_home;
  if (!isNum(pH)) return null;
  var pD = g.status === 'live' && isNum(g.wp_home) ? 0 : (isNum(g.p_draw) ? g.p_draw : 0);
  var pA = g.status === 'live' && isNum(g.wp_home) ? 1 - g.wp_home : (isNum(g.p_away) ? g.p_away : 1 - pH - pD);
  return pA > pH ? { t: g.away || {}, p: pA, o: g.home || {}, op: pH, d: pD } : { t: g.home || {}, p: pH, o: g.away || {}, op: pA, d: pD };
}
/* Team names in the US leagues are nicknames ("the Ravens are"); football and college names stand alone ("Arsenal
 * are"); a player is singular ("J. Sinner is"). The builder (scripts/build_home.py why_line) follows the same rules. */
var THE_SPORTS = { nfl: 1, hockey: 1, baseball: 1, basketball: 1 };
function solo(g) { return g.sport === 'tennis' || g.sport === 'f1' || !!g.players; }
function isAre(g) { return solo(g) ? 'is' : 'are'; }
function nmOf(g, t) { var n = String(t.name || t.abbr || ''); return THE_SPORTS[g.sport] && !g.players ? 'the ' + n : n; }
function favPhrase(g, t, kind) { return cap(nmOf(g, t)) + (solo(g) ? ' is a ' + kind + ' favourite' : ' are ' + kind + ' favourites'); }
function art(n) { return /^8/.test(String(n)) || n === 11 || n === 18 ? 'an' : 'a'; }
function cap(x) { x = String(x || ''); return x.charAt(0).toUpperCase() + x.slice(1); }
QK.whyLine = function (g) {
  if (!g) return '';
  if (g.why) return g.why;
  var f = favOf(g);
  var note = String(g.note || '');
  if (g.status === 'final') {
    if (!isNum(g.hs) || !isNum(g.as)) return '';
    var pp = QK.preP(g);
    if (!isNum(pp)) return '';
    var pAw = 1 - pp - (isNum(g.p_draw) ? g.p_draw : 0), homeWon = g.hs > g.as, draw = g.hs === g.as;
    if (draw) return 'A draw. We had it at ' + fmt.pct(g.p_draw || 0) + ' before the start.';
    var w = homeWon ? g.home : g.away, wp = homeWon ? pp : pAw;
    if (wp < 0.4) return 'An upset: we gave ' + nmOf(g, w || {}) + ' ' + fmt.pct(wp) + ' before the start.';
    /* 40-50%: the winner was the slight underdog, so not "as expected" */
    if (wp < 0.5) return 'A near coin flip: we had ' + nmOf(g, w || {}) + ' at ' + fmt.pct(wp) + ' before the start.';
    return 'As expected: ' + nmOf(g, w || {}) + ' won at ' + fmt.pct(wp) + ' in our numbers.';
  }
  if (g.status === 'live') {
    var pre = QK.preP(g);
    var lp = QK.liveP(g);
    if (f && isNum(pre) && isNum(lp) && !g.pre_only && Math.abs(lp - pre) >= 0.08) {
      var preFavHome = pre >= 0.5;
      return 'Before the start we had ' + nmOf(g, preFavHome ? g.home || {} : g.away || {}) + ' at ' + fmt.pct(preFavHome ? pre : 1 - pre) + '. The score has moved it.';
    }
    if (/game 7|g7\b/i.test(note)) return 'Game 7, live. Winner goes through.';
    if (g.pre_only && f) return 'Live now. Before the start we had ' + nmOf(g, f.t) + ' at ' + fmt.pct(f.p) + (f.d > 0.02 ? ' and the draw at ' + fmt.pct(f.d) : '') + '.';
    return f && !g.pre_only ? 'Live, and ' + nmOf(g, f.t) + ' ' + isAre(g) + ' ' + fmt.pct(f.p) + ' to win from here.' : 'Live now.';
  }
  if (/game 7|g7\b/i.test(note)) return 'Game 7. The winner goes through.';
  if (!f) return note ? note + '.' : '';
  if (f.d >= 0.3) return 'A draw is live: ' + fmt.pct(f.d) + ' in our numbers.';
  var gap = f.p - f.op;
  if (gap < 0.08) return 'A coin flip: we can barely split them.';
  if (f.d >= 0.2 && f.p < 0.55) return cap(nmOf(g, f.t)) + ' shade it at ' + fmt.pct(f.p) + ', with the draw at ' + fmt.pct(f.d) + '.';
  if (f.p >= 0.66) {
    var u = Math.max(0.01, 1 - f.p - f.d), n = Math.round(1 / u), uu = Math.round(u * 100);
    if (f.d >= 0.05) return favPhrase(g, f.t, 'clear') + ', but they still lose about 1 time in ' + n + '.';
    return favPhrase(g, f.t, 'clear') + ', but ' + art(uu) + ' ' + uu + '% chance comes off about 1 time in ' + n + '.';
  }
  return favPhrase(g, f.t, 'slight') + ' at ' + fmt.pct(f.p) + '.';
};
/* QK.watchScore(g) — how much a game is worth watching: live first, close calls, playoff notes, soon. */
QK.watchScore = function (g) {
  if (!g || g.status === 'final' || g.event) return -1e9;
  var hrs = (new Date(g.start) - QK.now()) / 36e5;
  if (g.status !== 'live' && (hrs > 48 || hrs < -6)) return -1e9;
  var s = g.status === 'live' ? (g.pre_only ? 8 : 30) : 0;
  var note = String(g.note || '') + ' ' + String(g.league || '');
  if (/Final|Finals|CS\b|Series|SF\b|Super Bowl|Playoff|Game \d|G\d\b|Cup/i.test(note)) s += 20;
  var f = favOf(g);
  if (f) s += 14 * (1 - Math.min(1, Math.abs(f.p - f.op) * 2));
  return s - Math.max(0, hrs) * 0.4;
};
/* QK.watchGrid(games, { limit: 6, pick: true (rank by QK.watchScore; false keeps the order), card: { gameCard options },
 * diverse: true (at most two per sport while others wait) }) -> the "What to watch" grid of game cards, each with
 * its one-line reason (g.why, else QK.whyLine). */
QK.watchGrid = function (games, o) {
  o = o || {};
  var lim = o.limit || 6;
  var list = (games || []).filter(Boolean);
  if (o.pick !== false) {
    list = list.map(function (g) { return [QK.watchScore(g), g]; }).filter(function (x) { return x[0] > -1e8; }).sort(function (a, b) { return b[0] - a[0]; }).map(function (x) { return x[1]; });
    if (o.diverse !== false) {
      var per = {}, first = [], rest = [];
      list.forEach(function (g) { per[g.sport] = (per[g.sport] || 0) + 1; (per[g.sport] <= 2 ? first : rest).push(g); });
      list = first.concat(rest);
    }
  }
  list = list.slice(0, lim);
  if (!list.length) return QK.empty(o.emptyTitle || 'Nothing on right now', o.emptyText || 'The next games appear here as soon as they are scheduled.');
  var co = {}, k; for (k in (o.card || {})) if (Object.prototype.hasOwnProperty.call(o.card, k)) co[k] = o.card[k];
  if (co.why === undefined) co.why = true;
  return '<div class="qk-watch">' + list.map(function (g) { return QK.gameCard(g, co); }).join('') + '</div>';
};

/* ─────────────────────────────────────── feature card (a marquee or live game, for the greeting hero) */
/* QK.featureCard(g, { scribble: 'Finals, Game 1!', kicker }) -> a card with the league and status pills, both teams
 * (with the score once it starts), our chance for the favourite as a big blue number, what it means, and a note. */
/* v4: the feature is the diagonal split hero (QK.splitHero); o.scribble becomes its volt tag. o.compact: true
 * stacks it (a narrow column). */
QK.featureCard = function (g, o) {
  o = o || {};
  return QK.splitHero(g, { tag: o.scribble, kicker: o.kicker, noun: o.noun, compact: o.compact, nick: o.nick, sub: o.sub, note: o.note });
};

/* ─────────────────────────────────────── the diagonal split hero (v4) */
/* QK.splitHero(g, { kicker: 'WNBA Finals · Game 1' (the volt tag; default league · note), tag: 'Game 7!' (replaces the
 * volt tag; the league then leads the status chip), nick: fn(team) -> the name shown, sub: fn(team, 'home' |
 * 'away' | '') -> the line under it (default the city from team.full, then home / away), chip: 'text' (replaces the
 * status chip: "ATP · 8 meetings"), meters: true | false (two separate chance meters; default on for F1 and for any
 * two chances that do not add to 100%), homeFirst, noun ('game' |
 * 'match' | 'race'), note: HTML | false (the explain strip under the hero; default "What's that number?" live,
 * "How sure are we?" before), foot: false, link: false (no link even with g.href), compact: true, blocks: [a, b]
 * (QK.color.block results, to share colours with a page's charts) }) -> the two team colours cut on a diagonal
 * (QK.color.blockPair: white type >= 4.5:1, clashes and pale kits handled), giant scores once it starts (our chance
 * before), the clock and the occasion between, the abbreviations as watermarks; then the black foot: our chance for
 * the favourite in volt, what it means, and the bar in the two colours. No market here, ever. */
var NUM_W = ['nothing', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
QK.splitHero = function (g, o) {
  o = o || {};
  if (!g) return '';
  var live = g.status === 'live', fin = g.status === 'final';
  var A = g.away || {}, H = g.home || {};
  var dw = PREVIEW_WORDS[g.sport] || {};
  var hf = o.homeFirst !== undefined ? !!o.homeFirst : !!dw.homeFirst;
  var noun = o.noun || dw.noun || 'game';
  var nk = o.nick || function (t) { return t.name || t.abbr || ''; };
  var sp = QK.sport(g.sport) || {};
  var f = favOf(g);
  var pH = live ? QK.liveP(g) : g.p_home;
  var pD = live && isNum(g.wp_home) ? null : g.p_draw;
  var pA = live && isNum(g.wp_home) ? 1 - g.wp_home : (isNum(g.p_away) ? g.p_away : (isNum(pH) ? 1 - pH - (isNum(pD) ? pD : 0) : null));
  var Ls = hf ? H : A, Rs = hf ? A : H, pL = hf ? pH : pA, pR = hf ? pA : pH, sL = hf ? g.hs : g.as, sR = hf ? g.as : g.hs;
  var team = !solo(g) && g.sport !== 'f1';
  var bp = o.blocks || color.blockPair(Ls, Rs, { fav: f ? (f.t === Ls ? 'a' : 'b') : null });
  function subOf(t, role) {
    if (o.sub) return o.sub(t, role);
    /* the city: team.city, else the full name ("Winnipeg Jets", from team.full or team.name) less the name shown */
    var base = String(t.full || t.name || ''), shown = String(nk(t) || ''), at = shown && base !== shown ? base.lastIndexOf(shown) : -1;
    var city = t.city || (at > 0 && at + shown.length === base.length ? base.slice(0, at).trim() : '');
    return [city, t.record || '', team ? role : ''].filter(Boolean).join(' · ');
  }
  function side(t, b, p, sc, cls, role) {
    var nm = nk(t), big = live || fin ? (isNum(sc) ? esc(sc) : '–') : (isNum(p) ? QK.pctSmall(p) : '');
    var sub = subOf(t, role);
    return '<div class="qk-split-side ' + cls + '" style="--sb:' + esc(b.bg) + (b.edge ? ';--te:' + esc(b.edge) : '') + '"><div class="qk-split-tn">' + esc(nm) + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div>' +
      '<div class="qk-split-sc num">' + big + '</div><div class="qk-split-ab" aria-hidden="true">' + esc(QK.shortName(t)) + '</div></div>';
  }
  var lg = (g.league || sp.label || '') + (g.note && g.note !== 'OT' && g.note !== 'SO' ? ' · ' + g.note : '');
  var st = live ? (QK.periodLabel(g) || 'Live') + (g.clock ? ' ' + g.clock : '') : fin ? 'Final' + (g.note === 'OT' || g.note === 'SO' ? '/' + g.note : '') : (g.tba ? fmt.relDay(g.start) + ' · TBA' : fmt.relDay(g.start) + ' · ' + fmt.time(g.start));
  var mid = '<div class="qk-split-mid"><span class="qk-bchip' + (live ? ' live' : '') + '">' + esc(o.chip || ((o.tag ? (g.league || sp.label || '') + ' · ' : '') + (live ? 'Live · ' : '') + st)) + '</span>' +
    '<span class="qk-bchip volt">' + esc(o.tag || o.kicker || lg) + '</span></div>';
  /* the foot: our chance for the favourite, what it means, the bar */
  var foot = '';
  if (o.foot !== false) {
    var big = '', lab = '';
    if (f && !fin) {
      big = fmt.pct(f.p);
      var w = '<b>' + esc(nk(f.t)) + '</b> chance to win' + (live && !g.pre_only ? ' from here' : '');
      var second = '';
      if (live && isNum(g.hs) && isNum(g.as) && !g.pre_only) {
        var d = f.t === H ? g.hs - g.as : g.as - g.hs, ad = Math.abs(d), word = ad <= 10 ? NUM_W[ad] : String(ad);
        second = d > 0 ? 'up ' + word : d < 0 ? 'down ' + word : 'all square';
      } else if (live) second = 'our pre-' + noun + ' chance';
      else second = esc(nk(f.o)) + ' ' + fmt.pct(f.op) + (f.d > 0.02 ? ' · draw ' + fmt.pct(f.d) : '');
      lab = w + (second ? '<br>' + second : '');
    } else if (fin) {
      var pp = QK.preP(g);
      if (isNum(pp)) {
        var pa = 1 - pp - (isNum(g.p_draw) ? g.p_draw : 0), ft = pa > pp ? A : H;
        big = fmt.pct(Math.max(pa, pp));
        lab = 'Our pre-' + noun + ' call: <b>' + esc(nk(ft)) + '</b><br>' + esc(QK.whyLine(g));
      }
    }
    var hc = [color.ensure(bp[0].bg, '#000000', 3), color.ensure(bp[1].bg, '#000000', 3)];
    /* two chances that do not add to 100% (F1: each driver against the whole field) are two meters, never a split */
    var sep = o.meters !== undefined ? !!o.meters : (g.sport === 'f1' || (isNum(pL) && isNum(pR) && !isNum(pD) && Math.abs(pL + pR - 1) > 0.02));
    var meter = function (t, p, c) { return '<div class="m"><span class="n">' + esc(nk(t)) + '</span><span class="t"><i style="width:' + Math.max(1, Math.min(100, 100 * p)).toFixed(1) + '%;background:' + esc(c) + '"></i></span><span class="v num">' + fmt.pct(p) + '</span></div>'; };
    var bar = fin || !isNum(pL) || !isNum(pR) ? '' : sep
      ? '<div class="qk-split-meters" role="img" aria-label="' + esc((live ? 'Live win chance: ' : 'Our win chance: ') + nk(Ls) + ' ' + fmt.pct(pL) + ', ' + nk(Rs) + ' ' + fmt.pct(pR) + ' (each out of 100%)') + '">' + meter(Ls, pL, hc[0]) + meter(Rs, pR, hc[1]) + '<span class="k">Each out of 100% · the rest of the field takes the remainder</span></div>'
      : QK.wpBar(pL, pD, pR, Ls, Rs, { colors: hc, label: live ? 'Live win chance' : 'Our win chance' });
    if (big || bar) foot = '<div class="qk-split-foot">' + (big ? '<div class="big num">' + big + '</div><div class="lab">' + lab + '</div>' : '<div></div><div></div>') + '<div class="wpbox">' + bar + '</div></div>';
  }
  /* the note under it */
  var note = '';
  if (o.note !== false) {
    if (typeof o.note === 'string') note = o.note;
    else if (f && live && !g.pre_only) {
      var pre = QK.preP(g);
      note = '<b>What’s that number?</b> Our live chance updates with the score and the clock.' + (isNum(pre) ? ' Before the start it was ' + fmt.pct(f.t === H ? pre : 1 - pre) + ' for ' + esc(nmOf(g, f.t)) + (Math.abs(f.p - 0.5) < 0.1 ? ': a game this close still sits near a coin flip.' : '.') : '');
    } else if (f && !fin && !live) {
      var miss = Math.max(1, Math.round(10 * (1 - f.p)));
      note = '<b>How sure are we?</b> ' + fmt.pct(f.p) + ' means ' + (f.d > 0.02 ? 'a ' + noun + ' like this goes another way' : esc(nmOf(g, f.o)) + ' win' + (solo(g) ? 's' : '') + ' a ' + noun + ' like this') + ' about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.';
    }
  }
  var link = g.href && o.link !== false;
  var tag = link ? 'a' : 'div';
  var aria = (live ? 'Live: ' : fin ? 'Final: ' : '') + (Ls.name || '') + (live || fin ? ' ' + (isNum(sL) ? sL : '') : '') + ' v ' + (Rs.name || '') + (live || fin ? ' ' + (isNum(sR) ? sR : '') : '') + (f && !fin ? '; our chance ' + (f.t.name || '') + ' ' + fmt.pct(f.p) : '');
  return '<div class="qk-splitw"><' + tag + (link ? ' href="' + esc(g.href) + '"' : '') + ' class="qk-split' + (o.compact ? ' compact' : '') + (live ? ' is-live' : '') + '" aria-label="' + esc(aria) + '" style="--sa:' + (sp.accent || 'var(--accent)') + '">' +
    '<div class="qk-split-top">' + side(Ls, bp[0], pL, sL, 'l', hf ? 'home' : 'away') + side(Rs, bp[1], pR, sR, 'r', hf ? 'away' : 'home') + mid + '</div>' + foot + '</' + tag + '>' +
    (note ? QK.explain(note, { html: true }) : '') + '</div>';
};
/* QK.explain(html, { title, cls, html: true }) -> the explain strip: a volt rule on the left, one or two plain
 * sentences ("What's that number? ..."). With title, it leads in bold. HTML in. */
QK.explain = function (html, o) {
  o = o || {};
  return '<div class="qk-explain' + (o.cls ? ' ' + esc(o.cls) : '') + '">' + (o.title ? '<b>' + esc(o.title) + '</b> ' : '') + String(html || '') + '</div>';
};
/* QK.band(html, { id, cls }) -> a full-bleed black section (the power list's band) holding html. */
QK.band = function (html, o) {
  o = o || {};
  return '<section class="qk-blk qk-bleed' + (o.cls ? ' ' + esc(o.cls) : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-blk-in">' + String(html || '') + '</div></section>';
};

/* ─────────────────────────────────────── who's hot */
/* QK.hotRow([{ sport, title ('Most points'), name, value, unit, next: { name, value }, expl, href, colour }]) -> one
 * card per name: sport and what it leads, the name, the number, the next best, and what the number means.
 * Five across on desktop, three on tablets, a swipeable row on phones. */
/* QK.surname('Bobby Witt Jr.') -> 'Witt Jr.': the last word of a name, with a suffix (Jr., Sr., II-V) kept with the
 * word before it (joined by a no-break space). */
QK.surname = function (name) {
  var w = String(name || '').trim().split(/\s+/), k = w.length - 1;
  if (k > 0 && /^(jr|sr|ii|iii|iv|v)\.?$/i.test(w[k])) return w[k - 1] + '\u00a0' + w[k];
  return w[k] || '';
};
/* v4: the black power list: an outlined rank number in the corner (o.rank: false hides it), the sport and what it
 * leads in volt, the name in Bebas (Barlow Condensed when long), the big number, the unit, the explanation. */
QK.hotRow = function (items, o) {
  o = o || {};
  var it = (items || []).filter(Boolean);
  return '<div class="qk-hot' + (it.length === 4 ? ' n4' : it.length >= 6 ? ' n6' : '') + '">' + it.map(function (h, i) {
    var sp = QK.sport(h.sport) || {};
    var v = isNum(h.value) ? (h.value % 1 ? fmt.num(h.value, 1) : fmt.num(h.value)) : esc(h.value === undefined || h.value === null ? '—' : h.value);
    var nx = h.next && h.next.name ? ' · next best ' + esc(QK.surname(h.next.name)) + (h.next.value !== undefined && h.next.value !== null ? ' ' + esc(isNum(h.next.value) && h.next.value % 1 ? fmt.num(h.next.value, 1) : h.next.value) : '') : '';
    var tag = h.href ? 'a' : 'div';
    return '<' + tag + ' class="qk-hot-card"' + (h.href ? ' href="' + esc(h.href) + '"' : '') + ' style="--sa:' + (sp.accent || 'var(--accent)') + '">' +
      (o.rank === false ? '' : '<span class="qk-hot-rk qk-outline num" aria-hidden="true">' + (h.rank || i + 1) + '</span>') +
      '<div class="qk-hot-sport"><i aria-hidden="true"></i>' + esc(h.kicker || sp.label || h.sport || '') + '</div>' +
      '<div class="qk-hot-who' + QK.longName(h.name, 15) + '">' + esc(h.name) + '</div><div class="qk-hot-val num">' + v + '</div>' +
      '<div class="qk-hot-unit">' + esc(h.title || h.unit || '') + nx + '</div>' + (h.expl ? '<div class="qk-hot-expl">' + esc(h.expl) + '</div>' : '') + '</' + tag + '>';
  }).join('') + '</div>';
};

/* ─────────────────────────────────────── stat of the day */
/* QK.statOfDay({ value, kicker, title, text, note (HTML), href }, { nav: HTML }) -> the big-number card. */
QK.statOfDay = function (x, o) {
  o = o || {};
  x = x || {};
  return '<article class="qk-card qk-sotd"><div class="qk-sotd-v">' + esc(x.value) + '</div><div style="min-width:0"><div class="qk-kicker">' + esc(x.kicker || 'Stat of the day') + '</div>' +
    '<h3>' + (x.href ? '<a href="' + esc(x.href) + '">' + esc(x.title || '') + '</a>' : esc(x.title || '')) + '</h3>' + (x.text ? '<p>' + esc(x.text) + '</p>' : '') +
    (x.note ? QK.note(x.note) : '') + (o.nav || '') + '</div></article>';
};

/* ─────────────────────────────────────── fan modules (round 6: the hub experience) */
/* QK.storyCards([{ kicker: 'Breakout watch', name, sub, value, unit, text, html: true (text is HTML), href, colour (a
 * team hex: the card's edge), mark: { abbr, colour, logo }, sport, from: { label, value, pos }, to: { label, value,
 * pos } (a progression: two points on a 0-100 track, pos in 0-100; e.g. last season's percentile and this season's),
 * spark: [numbers] (season by season), sparkLabel, pace: { now, pace, target, max, label, fmt } (records in reach: how
 * far, the season pace, the mark to beat), link: { href, text } (a second link, "Progression"; on a card without its
 * own href) }], { cols: 3 | 4 }) -> a grid of story cards: the volt tag, the name, the big number, the picture, one
 * line. Phones: one a row. Every number comes from our data, and the text says what it means. */
QK.storyCards = function (items, o) {
  o = o || {};
  var it = (items || []).filter(Boolean);
  if (!it.length) return '';
  function num(v, f) { return f ? esc(f(v)) : (isNum(v) ? (v % 1 ? fmt.num(v, 1) : fmt.num(v)) : esc(v === undefined || v === null ? '' : v)); }
  function shown(e, pos) { return esc(e.value === undefined || e.value === null ? Math.round(pos) : e.value); }
  return '<div class="qk-stories" style="--n:' + Math.min(o.cols || 3, it.length) + '">' + it.map(function (x) {
    var sp = QK.sport(x.sport) || {};
    var hex = color.parse(x.colour) ? x.colour : (x.mark && color.parse(x.mark.colour) ? x.mark.colour : null);
    var edge = hex ? color.ensure(hex, cssVar('--s-1') || '#14171d', 3) : (sp.accent || 'var(--volt)');
    var tag = x.href ? 'a' : 'div';
    var prog = '';
    if (x.from && x.to && isNum(x.from.pos) && isNum(x.to.pos)) {
      var a = Math.max(0, Math.min(100, x.from.pos)), b = Math.max(0, Math.min(100, x.to.pos)), lo = Math.min(a, b), hi = Math.max(a, b);
      prog = '<div class="qk-story-prog" role="img" aria-label="' + esc((x.from.label || 'Before') + ' ' + (x.from.value === undefined ? Math.round(a) : x.from.value) + ', ' + (x.to.label || 'Now') + ' ' + (x.to.value === undefined ? Math.round(b) : x.to.value)) + '">' +
        '<div class="qk-story-track"><i class="span' + (b < a ? ' down' : '') + '" style="left:' + lo.toFixed(1) + '%;width:' + (hi - lo).toFixed(1) + '%"></i><i class="from" style="left:' + a.toFixed(1) + '%"></i><i class="to" style="left:' + b.toFixed(1) + '%"></i></div>' +
        '<div class="qk-story-pl"><span>' + esc(x.from.label || 'Before') + ' <b>' + shown(x.from, a) + '</b></span><span>' + esc(x.to.label || 'Now') + ' <b>' + shown(x.to, b) + '</b></span></div></div>';
    }
    var pace = '';
    if (x.pace && isNum(x.pace.now) && isNum(x.pace.target)) {
      var P = x.pace, mx = isNum(P.max) ? P.max : Math.max(P.target, isNum(P.pace) ? P.pace : 0) * 1.08, f = P.fmt;
      var w = function (v) { return Math.max(0, Math.min(100, 100 * v / mx)).toFixed(1); };
      pace = '<div class="qk-story-pace" role="img" aria-label="' + esc('Now ' + (f ? f(P.now) : P.now) + (isNum(P.pace) ? ', on pace for ' + (f ? f(P.pace) : Math.round(P.pace)) : '') + ', ' + (P.label || 'the mark') + ' ' + (f ? f(P.target) : P.target)) + '">' +
        '<div class="qk-story-track"><i class="pace" style="width:' + w(isNum(P.pace) ? P.pace : P.now) + '%"></i><i class="now" style="width:' + w(P.now) + '%"></i><i class="mark" style="left:' + w(P.target) + '%"></i></div>' +
        '<div class="qk-story-pl"><span>Now <b>' + num(P.now, f) + '</b>' + (isNum(P.pace) ? ' · pace <b>' + num(f ? P.pace : Math.round(P.pace), f) + '</b>' : '') + '</span><span>' + esc(P.label || 'The mark') + ' <b>' + num(P.target, f) + '</b></span></div></div>';
    }
    var spark = x.spark && x.spark.filter(isNum).length > 1 ? '<div class="qk-story-spark">' + QK.spark(x.spark, { w: 220, h: 40, color: 'var(--volt)', label: x.sparkLabel || '' }) + (x.sparkLabel ? '<small>' + esc(x.sparkLabel) + '</small>' : '') + '</div>' : '';
    var mark = x.mark ? QK.teamMark(x.mark, 'md') : '';
    var val = x.value === undefined || x.value === null || x.value === '' ? '' : '<div class="qk-story-v num">' + num(x.value) + (x.unit ? '<small>' + esc(x.unit) + '</small>' : '') + '</div>';
    var link = x.link && x.link.text ? (x.link.href && !x.href ? '<a class="qk-story-l" href="' + esc(x.link.href) + '">' + esc(x.link.text) + ' →</a>' : '<span class="qk-story-l">' + esc(x.link.text) + ' →</span>') : '';
    return '<' + tag + ' class="qk-story"' + (x.href ? ' href="' + esc(x.href) + '"' : '') + ' style="--se:' + esc(edge) + '">' +
      '<div class="qk-story-k">' + esc(x.kicker || '') + '</div>' +
      '<div class="qk-story-who">' + mark + '<div class="qk-story-id"><div class="qk-story-nm' + QK.longName(x.name, 18) + '">' + esc(x.name || '') + '</div>' + (x.sub ? '<div class="qk-story-sub">' + esc(x.sub) + '</div>' : '') + '</div></div>' +
      val + prog + pace + spark +
      (x.text ? '<p class="qk-story-t">' + (x.html ? String(x.text) : esc(x.text)) + '</p>' : '') + link + '</' + tag + '>';
  }).join('') + '</div>';
};
/* QK.spotlight({ kicker: 'Player spotlight', name, sub (team · position), number (outlined), team: { name, abbr,
 * colour }, href, headline (one plain sentence), text, stats: [{ label, value, pctl, prev, tip }] (LED meters when
 * every row has pctl, else big numbers), spark: { values, labels: [first, last], label } (a season-by-season line),
 * links: [{ href, text }] }) -> a full-width feature: the team-colour block with the name and the outlined number on
 * the left, the deep stats on the right. Tennis or no team: the cobalt block. */
QK.spotlight = function (o) {
  o = o || {};
  var t = o.team || {};
  var hex = color.parse(t.colour) ? t.colour : null;
  var bk = hex ? color.block(hex) : { bg: cssVar('--signal-deep') || '#5a69b7', edge: null };
  var st = (o.stats || []).filter(function (r) { return r && (r.value !== undefined || isNum(r.pctl)); });
  var meters = st.length && st.filter(function (r) { return isNum(r.pctl); }).length === st.length;
  var right = meters ? QK.pctlBars(st) : (st.length ? '<div class="qk-spot-nums">' + st.map(function (r) { return '<div><b class="num">' + esc(r.value) + '</b><span' + (r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : '') + '>' + esc(r.label) + '</span></div>'; }).join('') + '</div>' : '');
  var sv = o.spark && (o.spark.values || []).filter(isNum).length > 1 ? o.spark : null;
  var sp = sv ? '<div class="qk-spot-spark">' + QK.spark(sv.values, { w: 320, h: 56, color: 'var(--volt)', label: sv.label || '' }) +
    '<div class="qk-spot-sl"><span>' + esc((sv.labels || [])[0] || '') + '</span><span>' + esc(sv.label || '') + '</span><span>' + esc((sv.labels || []).slice(-1)[0] || '') + '</span></div></div>' : '';
  var links = (o.links || []).filter(function (l) { return l && l.href; }).map(function (l) { return '<a class="qk-more" href="' + esc(l.href) + '">' + esc(l.text) + '</a>'; }).join('');
  var nm = o.href ? '<a href="' + esc(o.href) + '">' + esc(o.name || '') + '</a>' : esc(o.name || '');
  var hasNum = o.number !== undefined && o.number !== null && o.number !== '';
  return '<article class="qk-spot" style="--tb:' + esc(bk.bg) + (bk.edge ? ';--te:' + esc(bk.edge) : '') + '">' +
    '<div class="qk-spot-l">' + (hasNum ? '<div class="qk-spot-num qk-outline num" aria-hidden="true">' + esc(o.number) + '</div>' : '') +
    '<div class="qk-spot-k">' + esc(o.kicker || 'Spotlight') + '</div><h3 class="qk-spot-nm' + QK.longName(o.name, 16) + '">' + nm + '</h3>' +
    (o.sub ? '<div class="qk-spot-sub">' + esc(o.sub) + '</div>' : '') + (o.headline ? '<p class="qk-spot-h">' + esc(o.headline) + '</p>' : '') + '</div>' +
    '<div class="qk-spot-r">' + right + sp + (o.text ? '<p class="qk-spot-t">' + esc(o.text) + '</p>' : '') + (links ? '<div class="qk-spot-links">' + links + '</div>' : '') + '</div></article>';
};
/* QK.doing(el, { record (a digest's record: { n, won, expected, expected_rate, upsets, draws, from, to, days }),
 * calibration | bins/brier/n (as QK.howSure), league, span, subject, unit, kicker, title, sub, note, caption }) ->
 * renders "How we're doing" into el: the section head, our recent record as black tiles, then QK.howSure. Its home is
 * a site's Model page (round 6: the record and the calibration live there, not on landing pages). */
QK.doing = function (el, o) {
  if (typeof el === 'string') el = $(el);
  if (!el) return null;
  o = o || {};
  var r = o.record, unit = o.unit || 'games', tiles = [];
  if (r && r.n) {
    var wk = !r.days || r.days === 7, diff = r.won - (r.expected || 0);
    tiles.push({ label: wk ? 'Our favourites this week' : 'Our favourites, last ' + r.days + ' days', value: r.won + ' of ' + r.n, signal: true,
      sub: 'Won, of the ' + unit + ' with a chance we published before the start' + (r.from ? ', since ' + fmt.date(String(r.from).length === 10 ? r.from + 'T12:00:00' : r.from) : '') + '.' });
    if (isNum(r.expected)) tiles.push({ label: 'We expected', value: fmt.num(r.expected, 0), sub: 'From our favourites’ average chance' + (isNum(r.expected_rate) ? ' of ' + fmt.pct(r.expected_rate) : '') + '. ' + (r.n < 20 ? 'A small sample: a couple of results move this a lot.' : Math.abs(diff) < 2 ? 'Right on our numbers.' : diff > 0 ? 'A good week for favourites.' : 'More upsets than we expected.') });
    if (isNum(r.upsets)) tiles.push({ label: 'Upsets', value: String(r.upsets), sub: 'Our underdog won' + (isNum(r.draws) && r.draws ? '; ' + r.draws + ' draw' + (r.draws === 1 ? '' : 's') : '') + '. A 60% call still misses 4 times in 10.' });
  }
  var hid = 'qk-doing-' + Math.random().toString(36).slice(2, 8);
  var noun = unit === 'games' ? 'game' : unit.replace(/s$/, '');
  el.innerHTML = QK.sectionHead({ kicker: o.kicker || 'How we’re doing', title: o.title || 'We say it. Then we check it.', sub: o.sub || ((tiles.length ? 'Our recent record, then every ' : 'Every ') + (o.league ? o.league + ' ' : '') + noun + ' we have forecast, grouped by the chance we gave ' + (o.subject || 'the home team') + '. When the two match, our numbers mean what they say.') }) +
    (tiles.length ? QK.stats(tiles) : '') + '<div id="' + hid + '"' + (tiles.length ? ' style="margin-top:18px"' : '') + '></div>' + (o.note ? QK.explain(o.note) : '');
  return QK.howSure(el.querySelector('#' + hid), { calibration: o.calibration, bins: o.bins, brier: o.brier, n: o.n, league: o.league, span: o.span, subject: o.subject, unit: unit, caption: o.caption });
};

/* ─────────────────────────────────────── New here? */
/* QK.newHere({ kicker: 'New here?', title: 'Three things to know', items: [HTML, ...] }) -> the cream card. The
 * default three items explain a chance, a percentile and the record; a site may pass its own (keep them three). */
QK.NEW_HERE = [
  'A <b>chance</b> is how often we think something happens. 70% still misses 3 times in 10.',
  'A <b>percentile</b> ranks a player against others in the same role: 90th means better than 90 in 100.',
  'Every forecast is checked against what happened. <a class="qk-link" href="#howsure">The record is here.</a>'
];
/* v4: the "What's that number?" strip: a volt rule on the left, the title in bold, three numbered points side by
 * side (stacked on phones). */
QK.newHere = function (o) {
  o = o || {};
  return '<article class="qk-explain qk-newhere"><b>' + esc(o.kicker || 'What’s that number?') + '</b> ' + esc(o.title || 'Three things to know.') +
    '<ol>' + (o.items || QK.NEW_HERE).map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ol></article>';
};

/* ─────────────────────────────────────── The short version */
/* QK.shortVersion('plain-English summary' | { title: 'The short version', text, html }) -> the cream summary box. */
QK.shortVersion = function (o) {
  if (typeof o === 'string') o = { text: o };
  o = o || {};
  return '<div class="qk-short"><h3>' + esc(o.title || 'The short version') + '</h3> <p>' + (o.html ? String(o.html) : esc(o.text || '')) + '</p></div>';
};

/* ─────────────────────────────────────── How sure are we? */
/* QK.calib.find(json) -> { n, brier, logloss, base_rate, bins: [{ lo, hi, n, mean_p, freq }] } from a site's
 * calibration.json, whatever its shape: game_model.metrics.model (Rink, Gridiron), metrics.model (Hardwood),
 * metrics.model_pre.win (Paddock), games.seasons.<year>.model (Bullpen: pooled across seasons), or a block that is
 * already { reliability | bins }. null when nothing usable is there. */
QK.calib = {
  block: function (b) {
    if (!b) return null;
    var bins = b.reliability || b.bins;
    if (!Array.isArray(bins) || !bins.length) return null;
    return { n: b.n, brier: b.brier, logloss: b.logloss, base_rate: b.base_rate, bins: bins.filter(function (x) { return x && isNum(x.mean_p) && isNum(x.freq) && isNum(x.n); }) };
  },
  pool: function (blocks) {
    var by = {}, n = 0, br = 0, ll = 0;
    blocks.forEach(function (b) {
      if (!b) return;
      n += b.n || 0; if (isNum(b.brier)) br += b.brier * (b.n || 0); if (isNum(b.logloss)) ll += b.logloss * (b.n || 0);
      (b.bins || []).forEach(function (x) {
        var k = String(x.lo);
        var t = by[k] || (by[k] = { lo: x.lo, hi: x.hi, n: 0, sp: 0, sf: 0 });
        t.n += x.n; t.sp += x.mean_p * x.n; t.sf += x.freq * x.n;
      });
    });
    var bins = Object.keys(by).map(function (k) { var t = by[k]; return { lo: t.lo, hi: t.hi, n: t.n, mean_p: t.n ? t.sp / t.n : 0, freq: t.n ? t.sf / t.n : 0 }; }).sort(function (a, b) { return a.lo - b.lo; });
    return bins.length ? { n: n, brier: n ? br / n : null, logloss: n ? ll / n : null, bins: bins } : null;
  },
  find: function (j) {
    if (!j) return null;
    var c = QK.calib;
    var tries = [j.game_model && j.game_model.metrics && j.game_model.metrics.model, j.metrics && j.metrics.model,
      j.metrics && j.metrics.model_pre && j.metrics.model_pre.win, j];
    for (var i = 0; i < tries.length; i++) { var b = c.block(tries[i]); if (b) return b; }
    var ss = j.games && j.games.seasons;
    if (ss) return c.pool(Object.keys(ss).map(function (k) { return c.block((ss[k] || {}).model); }));
    return null;
  }
};
/* QK.howSure(el, { bins | calibration (a calibration.json, read with QK.calib.find), brier, n, league: 'NHL',
 * span: '2009-10 to 2025-26', subject: 'the home team', unit: 'games', minN: 30, points: [{ k, b, text }] (override
 * the three cards), caption }) -> renders the module into el: the calibration chart (QKC.calibration, ours in blue,
 * the dashed diagonal "spot on", italic annotations on the busiest and the top bins) beside three plain-English
 * cards: the Brier score, our most common call and how it did, and what happens at the top end. */
QK.howSure = function (el, o) {
  if (typeof el === 'string') el = $(el);
  if (!el) return null;
  o = o || {};
  var c = o.calibration ? QK.calib.find(o.calibration) : null;
  var bins = (o.bins || (c && c.bins) || []).filter(function (b) { return b && isNum(b.n) && b.n > 0; });
  var brier = isNum(o.brier) ? o.brier : (c && c.brier);
  var n = isNum(o.n) ? o.n : (c && c.n) || bins.reduce(function (a, b) { return a + b.n; }, 0);
  var minN = o.minN || 30, subj = o.subject || 'the home team', unit = o.unit || 'games';
  if (!bins.length) { el.innerHTML = QK.empty('No forecast record yet', 'The record appears once enough forecasts have been checked.'); return null; }
  var shown = bins.filter(function (b) { return b.n >= minN; });
  var left = bins.filter(function (b) { return b.n < minN; }).reduce(function (a, b) { return a + b.n; }, 0);
  var big = shown.slice().sort(function (a, b) { return b.n - a.n; })[0];
  var top = shown[shown.length - 1];
  var d = top ? top.freq - top.mean_p : 0;
  /* v4: three black blocks with the big numbers (how many checked, how the most common call did, the Brier score),
   * each with a one-line explanation, over the calibration line chart (QKC.calibration: our forecast against how
   * often it happened, the dashed diagonal "spot on"; o.style 'bars' draws the v4 paired bars instead). o.points:
   * [{ k, b, text }] still overrides the three. */
  var tops = top && top !== big ? (Math.abs(d) <= 0.03 ? ' Our biggest favourites won about as often as we said.' : d > 0 ? ' Our biggest favourites won more often than we said.' : ' Our biggest favourites won less often than we said.') : '';
  var pts = o.points || [
    { k: fmt.num(n), b: unit + ' checked', text: (o.league ? o.league + (o.span ? ', ' + o.span : '') : 'Every forecast') + ', against what happened.' },
    big ? { k: fmt.pct(big.freq, 1), b: 'won when we said ' + Math.round(big.mean_p * 100) + '%', text: 'Our most common call: ' + fmt.num(big.n) + ' ' + unit + ' at ' + Math.round(big.lo * 100) + '–' + Math.round(big.hi * 100) + '%.' + tops } : null,
    isNum(brier) ? { k: brier.toFixed(3), b: 'Brier score (0.25 = coin flip)', text: '0 is perfect.' + (brier > 0.22 ? ' Close to random is normal here, so small gains count.' : ' Lower is better.') } : null
  ].filter(Boolean);
  var dots = o.style !== 'bars';
  var cap = o.caption || ((o.league ? o.league + (o.span ? ', ' + o.span : '') + '. ' : '') + (dots ? 'Bigger dot = more ' + unit + '. On the dashed line, our numbers mean what they say.' : 'When the two bars match, our numbers mean what they say.') + (left ? ' Buckets with fewer than ' + minN + ' ' + unit + ' left off (' + fmt.num(left) + ' ' + unit + ').' : ''));
  var cid = 'qk-hs-' + Math.random().toString(36).slice(2, 8);
  el.innerHTML = '<div class="qk-howsure"><div class="qk-bignums">' +
    pts.map(function (x) { return '<div><b class="num">' + esc(x.k) + '</b><span>' + esc(x.b) + '</span>' + (x.text ? '<small>' + esc(x.text) + '</small>' : '') + '</div>'; }).join('') + '</div>' +
    '<article class="qk-card"><div class="qk-card-body"><div id="' + cid + '" class="qk-chart" style="--h:' + (o.height || 360) + 'px" role="img" aria-label="' + esc('Calibration: our forecast chance against how often ' + subj + ' won') + '"></div>' +
    '<div class="qk-caption">' + esc(cap) + '</div></div></article></div>';
  if (root.QKC && QKC.calibration) QKC.calibration('#' + cid, { bins: shown, subject: subj, unit: unit, style: dots ? 'dots' : 'bars' });
  return { bins: shown, brier: brier, n: n };
};

/* ─────────────────────────────────────── game preview card (the game-page hero) */
/* QK.previewCard(g, { kicker: 'NHL · Ball Arena, Denver', nick: fn(team) -> short name, note: HTML (replaces the
 * default "How sure are we?" note), noteExtra: HTML (appended to it), factors: [{ label, a, b, better: 'a' | 'b' }]
 * (away value, home value; the better side in blue), factorsTitle, keyLeft, keyRight, market: 'quiet' (round 6: the
 * market's chances, small and grey under the hero, source on hover; or { p, src, quiet: true }) | { p, label } (the
 * older black reference line), marketMark: 0.1 | false (the neutral marker's threshold), vs: 'at' | 'v' (the word between the sides), noun: 'game' |
 * 'match' | 'race' ("a match like this"), homeFirst: true (home on the left, "Home v Away") }) -> a card. The
 * defaults follow g.sport: football is home first with "v" and "match", tennis "v" and "match", F1 "race",
 * everything else away "at" home and "game". The card: both sides with monogram, record and form, the
 * score once it starts (the score bug when live), our chance for the favourite as a big blue number with a
 * sentence, the team-colour bar, a plain-English note and the match-up factors. */
var PREVIEW_WORDS = { football: { vs: 'v', noun: 'match', homeFirst: true }, tennis: { vs: 'v', noun: 'match' }, f1: { vs: 'v', noun: 'race' } };
/* v4 options: layout: 'hero' (default: the diagonal split hero, QK.splitHero) | 'bug' (the scoreboard bug,
 * QK.scorebugXL, for a "tonight" slot on a player or team page). The note becomes the explain strip under the hero;
 * the market (game detail only) a quiet black line under the hero's foot; the factors a card of Bebas numbers with
 * the label between them, the better side in blue. o.colors: [left, right] chart colours (kept for the factors key). */
QK.previewCard = function (g, o) {
  o = o || {};
  if (!g) return '';
  var live = g.status === 'live', fin = g.status === 'final';
  var A = g.away || {}, H = g.home || {};
  var nk = o.nick || function (t) { return t.name || t.abbr || ''; };
  var dw = PREVIEW_WORDS[g.sport] || {};
  var noun = o.noun || dw.noun || 'game';
  var hf = o.homeFirst !== undefined ? !!o.homeFirst : !!dw.homeFirst;
  var f = favOf(g), note = '';
  if (f && !fin) {
    var miss = Math.max(1, Math.round(10 * (1 - f.p)));
    note = o.note !== undefined ? o.note : '<b>How sure are we?</b> ' + fmt.pct(f.p) + ' means ' + (f.d > 0.02 ? 'a ' + noun + ' like this goes another way' : (THE_SPORTS[g.sport] && !g.players ? 'the ' : '') + esc(nk(f.t)) + ' lose' + (solo(g) ? 's' : '') + ' a ' + noun + ' like this') + ' about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.' + (o.noteExtra ? ' ' + o.noteExtra : '');
  } else if (fin) {
    var pp = QK.preP(g);
    if (isNum(pp)) { var pa = 1 - pp - (isNum(g.p_draw) ? g.p_draw : 0); note = o.note !== undefined ? o.note : 'Our pre-' + noun + ' call: <b>' + esc(nk(pa > pp ? A : H)) + ' ' + fmt.pct(Math.max(pa, pp)) + '</b>. ' + esc(QK.whyLine(g)) + (o.noteExtra ? ' ' + o.noteExtra : ''); }
  }
  var top = o.layout === 'bug' ? QK.scorebugXL(g, { nick: nk, homeFirst: hf })
    : QK.splitHero(g, { kicker: o.kicker, nick: nk, homeFirst: hf, noun: noun, note: false, link: false, compact: o.compact });
  /* round 6: market: 'quiet' (from g.market_home / market_away / market_src) or { p, src, label, quiet: true } -> the
     market's chances in a small grey line under the hero, the source on hover, a neutral marker when ours and the
     market differ by ten points or more. The old { p, label } object still draws the black reference line. */
  var mk = '';
  if (o.market === 'quiet' || (o.market && o.market.quiet && isNum(o.market.p))) {
    var gq = o.market === 'quiet' ? g : Object.assign({}, g, { market_home: o.market.p, market_away: o.market.away, market_draw: o.market.draw, market_src: o.market.src || g.market_src });
    mk = QK.marketLine(gq, { homeFirst: hf, cls: 'qk-preview-mq', source: o.marketSource || (o.market && o.market.label), mark: o.marketMark });
  } else if (o.market && isNum(o.market.p)) mk = '<div class="qk-preview-mkt"><span class="qk-mkt">' + esc(o.market.label || 'Market') + ' <b>' + esc(QK.shortName(H)) + ' ' + fmt.pct(o.market.p) + '</b></span><span>a reference, not our forecast</span></div>';
  var fx = (o.factors || []).filter(function (r) { return r && r.a !== undefined && r.b !== undefined; });
  var L = hf ? 'b' : 'a', R = hf ? 'a' : 'b';
  var fxh = fx.length ? '<div class="qk-factors-card"><h4 class="qk-factors-h">' + esc(o.factorsTitle || 'How they match up so far') + '</h4><div class="qk-factors">' + fx.map(function (r) {
    return '<div class="l num' + (r.better === L ? ' better' : '') + '">' + esc(r[L]) + '</div><div class="c">' + esc(r.label) + '</div><div class="r num' + (r.better === R ? ' better' : '') + '">' + esc(r[R]) + '</div>';
  }).join('') + '</div><div class="qk-factors-key"><span>' + esc(o.keyLeft || nk(hf ? H : A)) + '</span><span>Better side in blue</span><span>' + esc(o.keyRight || nk(hf ? A : H)) + '</span></div></div>' : '';
  return '<article class="qk-preview' + (live ? ' is-live' : '') + (o.layout === 'bug' ? ' bug' : '') + '">' + top + mk + (note ? QK.explain(note) : '') + fxh + '</article>';
};

/* ─────────────────────────────────────── compare verdicts */
/* QK.verdicts([{ title: 'The volume shooter', who: 'MacKinnon', text: 'More 5-on-5 shots per hour than any regular.' }])
 * -> a row of small boxes under a compare table: one line on what each player does best. */
QK.verdicts = function (items) {
  var it = (items || []).filter(Boolean);
  if (!it.length) return '';
  return '<div class="qk-verdicts" style="--n:' + Math.min(3, it.length) + '">' + it.map(function (v) {
    return '<div><b>' + esc(v.title) + '</b>' + (v.who ? esc(v.who) + ': ' : '') + esc(v.text || '') + '</div>';
  }).join('') + '</div>';
};


/* ─────────────────────────────────────── our metrics: the spec's labels and the "Our model" tag */
/* QK.spec.load(sport?) -> Promise of the catalogue (null when the file is missing): assets/qk/metrics/<sport>.labels.json,
 * which design_kit.py writes from docs/_design/metrics/<sport>.json (display names, units, direction, headline sets,
 * explanations and `our_models`). The sport defaults to <html data-sport>. Once loaded, QK.spec.get(sport) returns it
 * synchronously. Catalogue:
 *   cat.metric(id, entity)  -> { id, label, unit, dir, set ('h'|'s'), order, style, explain, ours: model | null } | null
 *   cat.label(id, entity, fallback)   the spec's display name (fallback when the spec has none)
 *   cat.tip(id, entity, fallback)     the explanation, plus "Our model: <name>." when it is ours
 *   cat.ours(id)            -> { key, name, about } | null    (id is a spec metric id or a payload key)
 *   cat.headline(groupId)   -> [ids] in the spec's order;  cat.isHeadline(id, entity) -> order | 0
 *   cat.order(items, o)     -> [{ label: 'Our models', items }, { label: 'Box score', items }] (empty groups dropped):
 *        items are { key|id|value, ... }; within each, the spec's headline metrics first (by order), then the rest in
 *        the order given. o.entity picks the metric table (default 'player'); o.key(item) reads the id.
 * QK.optgroups(items, cat, o) -> '<optgroup>' HTML for a <select>: items [{ value, label, key? }], o.selected, o.entity.
 * QK.ours(o) -> the cobalt "Our model" tag; o.short ('Ours', for table heads), o.model (name, in the tooltip), o.text.
 * QK.oursExplain(html, o) -> the explain strip with the cobalt rule: what our number is, in a sentence. */
var SPEC_CACHE = {}, SPEC_P = {};
function SpecCat(j) {
  this.j = j || {};
  var o = this.j.ours || {};
  this.models = o.models || {};
  this.map = o.metrics || {};
}
SpecCat.prototype.table = function (entity) { var m = this.j.m || {}; return m[entity || 'player'] || m.player || {}; };
SpecCat.prototype.ours = function (id) {
  var k = Object.prototype.hasOwnProperty.call(this.map, id) ? this.map[id] : null;
  if (!k) return null;
  var md = this.models[k] || {};
  return { key: k, name: md.name || 'Our model', about: md.about || '' };
};
SpecCat.prototype.metric = function (id, entity) {
  var t = this.table(entity), r = Object.prototype.hasOwnProperty.call(t, id) ? t[id] : null;
  if (!r) {
    var m = this.j.m || {}, ks = Object.keys(m);
    for (var i = 0; i < ks.length && !r; i++) if (Object.prototype.hasOwnProperty.call(m[ks[i]], id)) r = m[ks[i]][id];
  }
  var ours = this.ours(id);
  if (!r) return ours ? { id: id, label: id, unit: '', dir: 'higher', set: 's', order: 99, style: false, explain: ours.about, ours: ours } : null;
  return { id: id, label: r[0], unit: r[1], dir: r[2], set: r[3], order: r[4], style: !!r[5], explain: r[6], ours: ours };
};
SpecCat.prototype.label = function (id, entity, fallback) { var m = this.metric(id, entity); return m && m.label !== id ? m.label : (fallback || id); };
SpecCat.prototype.tip = function (id, entity, fallback) {
  var m = this.metric(id, entity);
  var t = m && m.explain ? m.explain : (fallback || '');
  if (m && m.ours) t += (t ? ' ' : '') + 'Our model: ' + m.ours.name + '.';
  return t;
};
SpecCat.prototype.headline = function (groupId) {
  var g = (this.j.groups || []).filter(function (x) { return x.id === groupId; })[0];
  return g ? (g.headline || []).slice() : [];
};
SpecCat.prototype.isHeadline = function (id, entity) { var m = this.metric(id, entity); return m && m.set === 'h' ? (m.order || 99) : 0; };
SpecCat.prototype.order = function (items, o) {
  o = o || {};
  var self = this, ent = o.entity || 'player';
  var keyOf = o.key || function (it) { return it.key !== undefined ? it.key : (it.id !== undefined ? it.id : it.value); };
  var ours = [], box = [];
  (items || []).forEach(function (it, i) {
    var k = keyOf(it), h = self.isHeadline(k, ent);
    (self.ours(k) ? ours : box).push({ it: it, h: h, i: i });
  });
  var cmp = function (a, b) { return ((a.h || 1e3) - (b.h || 1e3)) || (a.i - b.i); };
  var out = [];
  if (ours.length) out.push({ label: o.oursLabel || 'Our models', items: ours.sort(cmp).map(function (x) { return x.it; }) });
  if (box.length) out.push({ label: o.boxLabel || 'Box score', items: box.sort(cmp).map(function (x) { return x.it; }) });
  return out;
};
QK.spec = {
  url: function (sport) { return (QK.spec.base || 'assets/qk/metrics/') + sport + '.labels.json'; },
  get: function (sport) { return SPEC_CACHE[sport || document.documentElement.getAttribute('data-sport') || ''] || null; },
  load: function (sport) {
    sport = sport || document.documentElement.getAttribute('data-sport') || '';
    if (SPEC_CACHE[sport]) return Promise.resolve(SPEC_CACHE[sport]);
    if (!SPEC_P[sport]) {
      SPEC_P[sport] = QK.fetchJSON(QK.spec.url(sport), { timeout: 15000 }).then(function (j) {
        SPEC_CACHE[sport] = new SpecCat(j);
        return SPEC_CACHE[sport];
      }, function () { SPEC_P[sport] = null; return null; });
    }
    return SPEC_P[sport];
  },
  /* a catalogue from an already-parsed labels object (tests, pages that inline it) */
  from: function (j) { return new SpecCat(j); }
};
QK.ours = function (o) {
  o = o || {};
  var txt = o.text || (o.short ? 'Ours' : 'Our model');
  var tip = o.model ? 'Our model: ' + o.model + (o.about ? '. ' + o.about : '') : 'From our own model, not a box-score count';
  return '<span class="qk-ours' + (o.short ? ' sm' : '') + '" data-tip="' + esc(tip) + '" aria-label="' + esc(tip) + '">' + esc(txt) + '</span>';
};
QK.oursExplain = function (html, o) {
  o = o || {};
  return QK.explain(html, { title: o.title === undefined ? 'Our model.' : o.title, cls: 'qk-explain-ours' + (o.cls ? ' ' + o.cls : '') });
};
QK.optgroups = function (items, cat, o) {
  o = o || {};
  var opt = function (it) {
    var v = it.value !== undefined ? it.value : (it.key !== undefined ? it.key : it.id);
    return '<option value="' + esc(v) + '"' + (String(v) === String(o.selected) ? ' selected' : '') + '>' + esc(it.label) + '</option>';
  };
  if (!cat) return (items || []).map(opt).join('');
  return cat.order(items, o).map(function (g) { return '<optgroup label="' + esc(g.label) + '">' + g.items.map(opt).join('') + '</optgroup>'; }).join('');
};

root.QK = QK;
})(window);
