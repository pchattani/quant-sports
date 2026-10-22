/* The Quant — shared UI kit (v2 "Signal"; every v1 call still works). Framework-free; one global, QK.
 * Spec: docs/_design/STYLE_GUIDE.md; moving a page to v2: docs/_design/MIGRATION_V2.md.
 * Older-browser rule shared with the sites: no optional chaining, no nullish coalescing.
 *
 *   QK.SPORTS / QK.sport(key)          the sites shown in the switcher: names, URLs, accents, icons
 *   QK.ALL_SPORTS                      every site, including ones not launched yet (pending: true)
 *   QK.SECTIONS / QK.sections(key)     the information architecture every sport uses
 *   QK.shell(opts)                     top bar + sport switcher + section nav + search + footer
 *   QK.theme.get/set/toggle/onChange   dark | light, remembered per viewer
 *   QK.table(el, spec)                 sortable sticky-header table, percentile chips, raw/year columns
 *   QK.tableHTML(cols, rows, o)        static table HTML; QK.sortable(el) wires header sorting + row links
 *   QK.tabs(root) QK.seg(root, cb) QK.chips(root, cb)
 *   QK.matchCard(g) QK.tick(g) QK.probBar() QK.mvm()   game rendering
 *   QK.teamMark(t) QK.color.*          team colours with contrast checks
 *   QK.spark(values, opts)             inline SVG sparkline (no chart library)
 *   QK.skeleton(kind, n) QK.empty(title, text)  QK.tooltips()  QK.search.open()
 *   QK.fmt.*                           numbers, percents, odds, local times
 * v2 builders (return HTML strings unless noted):
 *   QK.sectionHead(o)  QK.ticker(games, o)  QK.gameCard(g, o)  QK.wpBar(pL, pD, pR, tL, tR, o)  QK.formDots(f)
 *   QK.chanceBar(r, o) QK.chances(rows, o)  QK.statTile(o)  QK.stats(list)  QK.playerHeader(o)  QK.pctCard(o)
 *   QK.leaderboard(el, spec) (renders)      QK.compareView(o)  QK.matchupBar(o)  QK.keys(items)  QK.tag(text, cls)
 *   QK.pctColor(p)  QK.pctInk(p)           the percentile scale (cold -> hot) as a colour and its text ink */
(function (root) {
'use strict';

var QK = root.QK || {};
QK.version = '2.0.0';

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
  date: function (iso, opts) { var d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d.toLocaleDateString(undefined, opts || { weekday: 'short', day: 'numeric', month: 'short' }) : '—'; },
  time: function (iso) { var d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : ''; },
  dayKey: function (iso) { var d = new Date(iso); return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); },
  relDay: function (iso) {
    var d = new Date(iso); if (isNaN(d)) return '';
    var t = new Date(); t.setHours(0, 0, 0, 0);
    var x = new Date(d); x.setHours(0, 0, 0, 0);
    var n = Math.round((x - t) / 864e5);
    return n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n === -1 ? 'Yesterday' : fmt.date(iso);
  },
  ago: function (iso) {
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
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
  ink: function (bg) { return color.contrast(bg, '#ffffff') >= color.contrast(bg, '#0b0d10') ? '#ffffff' : '#0b0d10'; },
  surface: function () { return cssVar('--s-1') || '#11151b'; },
  /* A team colour ready for a chart mark on the current theme. */
  team: function (hex) { return color.parse(hex) ? color.ensure(hex, color.surface(), 3) : cssVar('--c-other'); }
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

/* ─────────────────────────────────────── theme */
var themeListeners = [];
QK.theme = {
  get: function () {
    var a = document.documentElement.getAttribute('data-theme');
    if (a === 'light' || a === 'dark') return a;
    return root.matchMedia && root.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  },
  /* set() pins the viewer's choice; until then the page follows the OS setting. */
  set: function (t) {
    document.documentElement.setAttribute('data-theme', t);
    store('qk-theme', t);
    QK.theme.paint();
    themeListeners.forEach(function (f) { try { f(t); } catch (e) { if (root.console) console.error(e); } });
  },
  paint: function () {
    var t = QK.theme.get();
    $$('[data-qk-theme-toggle]').forEach(function (b) {
      b.innerHTML = t === 'dark' ? ICON.sun : ICON.moon;
      b.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
      b.setAttribute('title', b.getAttribute('aria-label'));
    });
  },
  toggle: function () { QK.theme.set(QK.theme.get() === 'dark' ? 'light' : 'dark'); },
  onChange: function (f) { themeListeners.push(f); },
  /* Call as early as possible (inline in <head>) to avoid a flash of the wrong theme. */
  boot: function () {
    var q = /[?&]theme=(light|dark)/.exec((root.location && root.location.search) || '');
    var t = q ? q[1] : store('qk-theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  }
};
QK.theme.boot();
if (root.matchMedia) {
  var mq = root.matchMedia('(prefers-color-scheme: light)');
  var onMq = function () { if (!store('qk-theme')) { QK.theme.paint(); themeListeners.forEach(function (f) { f(QK.theme.get()); }); } };
  if (mq.addEventListener) mq.addEventListener('change', onMq); else if (mq.addListener) mq.addListener(onMq);
}
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
  var sp = sportKey ? QK.sport(sportKey) : null;
  var brand = '<a class="qk-brand" href="' + esc(QK.homeUrl()) + '" aria-label="The Quant home">' +
    '<span class="qk-brand-mark" aria-hidden="true">' + ICON.logo + '</span>' +
    '<span class="qk-brand-name">The Quant' + (sp ? ' <b>' + esc(sp.site.replace('The Quant ', '')) + '</b>' : '') + '</span></a>';
  var sports = '<nav class="qk-sports" aria-label="Sports">' +
    '<a class="qk-sport" style="--sa:var(--brand)" href="' + esc(QK.homeUrl()) + '"' + (sportKey ? '' : ' aria-current="page"') + '>' + ICON.home + 'Home</a>' +
    QK.SPORTS.map(function (s) {
      return '<a class="qk-sport" data-sport="' + s.key + '" style="--sa:' + s.accent + '" href="' + esc(QK.sportUrl(s.key)) + '"' +
        (s.key === sportKey ? ' aria-current="page"' : '') + '>' + ICON[s.key] + esc(s.label) + '<span class="qk-sport-live" hidden><span class="qk-sport-dot" aria-label="live now"></span></span></a>';
    }).join('') + '</nav>';
  var actions = '<div class="qk-bar-actions">' +
    (o.search ? '<button class="qk-searchbtn" type="button" data-qk-search aria-label="Search">' + ICON.search + '<span>Search teams, players…</span><kbd>/</kbd></button>' : '') +
    '<button class="qk-iconbtn" type="button" data-qk-theme-toggle></button></div>';
  var secs = o.sections || (sportKey ? QK.sections(sportKey) : null);
  /* links scroll in their own box; the context controls sit beside them (desktop) or on a second row (phones) */
  var secnav = secs ? '<nav class="qk-secnav' + (o.ctx ? ' has-ctx' : '') + '" aria-label="Sections"><div class="qk-secnav-in"><div class="qk-secnav-links">' +
    secs.map(function (s) { return '<a href="' + esc(s.href) + '" data-sec="' + esc(s.key) + '"' + (s.key === o.section ? ' aria-current="page"' : '') + '>' + esc(s.label) + '</a>'; }).join('') +
    '</div>' + (o.ctx ? '<div class="qk-secnav-ctx">' + o.ctx + '</div>' : '') + '</div></nav>' : '';
  mount.innerHTML = (o.demo ? '' : '<a class="qk-skip" href="#main">Skip to content</a>') + '<header class="qk-topbar"><div class="qk-topbar-in">' + brand +
    '<span class="qk-brand-sep" aria-hidden="true"></span>' + sports + actions + '</div></header>' + secnav;
  $$('[data-qk-theme-toggle]', mount).forEach(function (b) { b.addEventListener('click', QK.theme.toggle); });
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
  el.innerHTML = '<div class="qk-footer-in"><div><b style="color:var(--ink-1)">The Quant</b> · sports models, probabilities and data. ' +
    'Probabilities are model estimates, not betting advice.</div><nav aria-label="All sports">' +
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
 * Header buttons sort (Enter/Space); aria-sort tracks state; rank column re-numbers. */
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
      var lab = c.tip ? '<span data-tip="' + esc(c.tip) + '">' + esc(c.label) + '</span>' : esc(c.label);
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
/* Savant-style percentile bars: rows [{label, pctl, value}] */
/* v2: the knob and fill take the percentile scale (cold -> hot); r.tip explains the metric, r.early marks a value
 * below the sample where the metric stabilises (dashed knob, a dot after the label). */
QK.pctlBars = function (rows) {
  return '<div class="qk-pbars">' + rows.filter(function (r) { return r && isNum(r.pctl); }).map(function (r) {
    var p = Math.max(0, Math.min(100, r.pctl)), c = QK.pctColor(p);
    var tip = r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : ' title="' + esc(r.label) + '"';
    return '<div class="qk-pbar' + (r.early ? ' early' : '') + '"><span class="qk-pbar-label"' + tip + '>' + esc(r.label) + '</span>' +
      '<span class="qk-pbar-track" role="img" aria-label="' + esc(r.label) + ': ' + esc(QK.ordinal(Math.round(p))) + ' percentile' + (r.early ? ', early sample' : '') + '"><span class="qk-pbar-fill" style="width:' + p + '%;background:' + c + '"></span>' +
      '<span class="qk-pbar-knob" style="left:' + p + '%;background:' + c + ';color:' + QK.pctInk(p) + '">' + Math.round(p) + '</span></span>' +
      '<span class="qk-pbar-val">' + esc(r.value === undefined ? '' : r.value) + '</span></div>';
  }).join('') + '</div>';
};

/* ─────────────────────────────────────── team marks */
/* t = { name, abbr, colour, logo } → crest image if given, else a contrast-checked monogram. */
QK.teamMark = function (t, size) {
  t = t || {};
  var cls = 'qk-team-mark' + (size ? ' ' + size : '');
  if (t.logo) return '<span class="' + cls + ' img"><img src="' + esc(t.logo) + '" alt="" loading="lazy" decoding="async" onerror="this.parentNode.classList.remove(\'img\');this.parentNode.textContent=\'' + esc(fmt.initials(t.abbr || t.name)).replace(/'/g, '') + '\'"></span>';
  var bg = color.parse(t.colour) ? t.colour : null;
  var style = bg ? ' style="--tc:' + esc(bg) + ';--ti:' + color.ink(bg) + '"' : '';
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
  return '<span class="qk-badge">' + esc(fmt.relDay(g.start)) + ' ' + esc(fmt.time(g.start)) + '</span>';
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
  var day = isNaN(d) ? '' : d.toLocaleDateString(undefined, { weekday: 'short' });
  return tba ? day : day + ' ' + fmt.time(iso);
};
/* Ticker item: abbreviations and scores in mono; before the game our chance for each side, the favourite in the
 * signal colour, and a 2 px bar of the away side's chance along the bottom. o.league: show the league, not the sport. */
QK.tick = function (g, o) {
  o = o || {};
  var fin = g.status === 'final', live = g.status === 'live', pre = !fin && !live;
  var s = QK.sport(g.sport) || {};
  var pa = isNum(g.p_away) ? g.p_away : (isNum(g.p_home) && !isNum(g.p_draw) ? 1 - g.p_home : null);
  var fav = pre && isNum(pa) && isNum(g.p_home) ? (pa > g.p_home ? 'a' : 'h') : '';
  function r(t, sc, lost, side) { return '<div class="qk-tick-row' + (fin && lost ? ' lost' : '') + (fav === side ? ' fav' : '') + '"><span class="qk-truncate">' + esc(t.abbr || t.name) + '</span><span class="s">' + (fin || live ? (isNum(sc) ? sc : '–') : (isNum(t._p) ? fmt.pct(t._p) : '')) + '</span></div>'; }
  var hw = isNum(g.hs) && isNum(g.as) ? (g.hs > g.as ? 1 : g.hs < g.as ? -1 : 0) : 0;
  var a = Object.assign({}, g.away, { _p: pa });
  var hm = Object.assign({}, g.home, { _p: g.p_home });
  var bar = pre && isNum(pa) ? '<span class="qk-tick-bar" aria-hidden="true"><i style="width:' + Math.round(pa * 100) + '%"></i></span>' : '';
  return '<a class="qk-tick' + (live ? ' is-live' : '') + '" href="' + esc(g.href || '#') + '" style="--sa:' + (s.accent || '') + '"><div class="qk-tick-top"><span class="qk-sportpill">' + esc(o.league ? (g.league || s.label || '') : (s.label || '')) + '</span><span class="st' + (live ? ' live' : '') + '">' +
    (live ? '● ' + esc(QK.periodLabel(g) || 'Live') : fin ? 'Final' + (g.note === 'OT' || g.note === 'SO' ? '/' + esc(g.note) : '') : esc(QK.whenShort(g.start, g.tba))) + '</span></div>' + r(a, g.as, hw > 0, 'a') + r(hm, g.hs, hw < 0, 'h') + bar + '</a>';
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

/* The display face (Archivo, with its width axis) for headlines and big numbers. QK.shell() adds it once, so a page
 * that only links Inter and JetBrains Mono still gets it; a page may link it itself (MIGRATION_V2.md step 1). */
var DISPLAY_FONT = 'https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..900&display=swap';
QK.ensureFonts = function () {
  try {
    if (!document.head || document.querySelector('link[data-qk-display]')) return;
    var ls = $$('link[href*="fonts.googleapis.com"]');
    for (var i = 0; i < ls.length; i++) if (/family=Archivo/.test(ls[i].getAttribute('href') || '')) return;
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
  if (!isNum(p)) return cssVar('--pc-50') || '#8b929f';
  p = Math.max(0, Math.min(100, p));
  var i = Math.min(3, Math.floor(p / 25));
  return color.mix(cssVar('--pc-' + PC[i]) || '#8b929f', cssVar('--pc-' + PC[i + 1]) || '#8b929f', (p - PC[i]) / 25);
};
QK.pctInk = function (p) { return isNum(p) && (p < 15 || p > 88) ? '#ffffff' : '#0b0d10'; };

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
/* QK.ticker(games, { group: 'sport' (default) | 'league' | false, max, sort: false }) -> the inside of a
 * <div class="qk-ticker">. Live games first, then upcoming, then finals; one labelled block per sport (or league). */
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
      groups[k].map(function (g) { return QK.tick(g, { league: o.group === 'league' ? false : o.league }); }).join('');
  }).join('');
};

/* ─────────────────────────────────────── win-probability bar, form */
/* QK.wpBar(pLeft, pDraw|null, pRight, teamLeft, teamRight, { market: left side's market probability (a quiet tick at
 * the market's split; two-way only), labels: true, size: 'lg', label: 'Win chance', colors: [left, right] (a page that
 * already picked the pair for its charts passes it, so bar and charts agree) }) */
QK.wpBar = function (pL, pD, pR, tL, tR, o) {
  o = o || {};
  if (!isNum(pL) && !isNum(pR)) return '';
  if (!isNum(pR)) pR = 1 - pL - (isNum(pD) ? pD : 0);
  if (!isNum(pL)) pL = 1 - pR - (isNum(pD) ? pD : 0);
  var lc = o.colors && o.colors[0] ? o.colors[0] : QK.probColour(tL, tR, 'left'), rc = o.colors && o.colors[1] ? o.colors[1] : QK.probColour(tR, tL, 'right');
  var nL = (tL && (tL.abbr || tL.name)) || 'Left', nR = (tR && (tR.abbr || tR.name)) || 'Right';
  var mk = isNum(o.market) && !isNum(pD) ? '<i class="qk-wpbar-mk" style="left:' + (100 * Math.max(0, Math.min(1, o.market))).toFixed(1) + '%" title="Market reference: ' + esc(nL) + ' ' + fmt.pct(o.market) + '"></i>' : '';
  var aria = (o.label || 'Win chance') + ': ' + nL + ' ' + fmt.pct(pL) + (isNum(pD) ? ', draw ' + fmt.pct(pD) : '') + ', ' + nR + ' ' + fmt.pct(pR) + (mk ? '; market ' + nL + ' ' + fmt.pct(o.market) : '');
  return '<div class="qk-wpbar' + (o.size === 'lg' ? ' lg' : '') + '" role="img" aria-label="' + esc(aria) + '">' +
    '<div class="qk-wpbar-track"><span style="flex:' + pL + ';background:' + lc + '"></span>' + (isNum(pD) ? '<span class="d" style="flex:' + pD + '"></span>' : '') +
    '<span style="flex:' + pR + ';background:' + rc + '"></span>' + mk + '</div>' +
    (o.labels === false ? '' : '<div class="qk-wpbar-lab"><span><b>' + fmt.pct(pL) + '</b> ' + esc(nL) + '</span>' + (isNum(pD) ? '<span>Draw <b>' + fmt.pct(pD) + '</b></span>' : '') + '<span>' + esc(nR) + ' <b>' + fmt.pct(pR) + '</b></span></div>') + '</div>';
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

/* ─────────────────────────────────────── game card (v2) */
/* QK.gameCard(game, { sport: false (hide the sport pill), market: false (hide the market reference), marketLabel,
 * form: false }). Game shape as QK.matchCard, plus home/away .record and .form. Before the game each row carries our
 * chance (favourite in the signal colour) and the bar shows the split; live, the score and the live chance; final,
 * the score with the pre-game chance in the foot. The market is a quiet reference: a hollow ring and a tick. */
QK.gameCard = function (g, o) {
  o = o || {};
  var s = QK.sport(g.sport) || {};
  var fin = g.status === 'final', live = g.status === 'live', pre = !fin && !live;
  var hs = g.hs, as = g.as;
  var hw = (fin || live) && isNum(hs) && isNum(as) ? (hs > as ? 1 : hs < as ? -1 : 0) : 0;
  var pA = isNum(g.p_away) ? g.p_away : (isNum(g.p_home) ? 1 - g.p_home - (isNum(g.p_draw) ? g.p_draw : 0) : null);
  var favA = isNum(pA) && isNum(g.p_home) && pA > g.p_home;
  function row(t, sc, p, lost, fav) {
    t = t || {};
    var v = fin || live ? '<span class="qk-gc-v">' + (isNum(sc) ? esc(sc) : '–') + '</span>' : '<span class="qk-gc-v pct">' + (isNum(p) ? fmt.pct(p) : '') + '</span>';
    return '<div class="qk-gc-row' + (fin && lost ? ' lost' : '') + (pre && fav ? ' fav' : '') + '">' + QK.teamMark(t, 'sm') +
      '<span class="qk-gc-nm">' + esc(t.name) + (t.record ? '<small>' + esc(t.record) + '</small>' : '') + '</span>' + (o.form === false ? '<span></span>' : QK.formDots(t.form)) + v + '</div>';
  }
  var showMk = pre && o.market !== false && isNum(g.market_home);
  var bar = !fin && isNum(g.p_home) ? QK.wpBar(pA, g.p_draw, g.p_home, g.away, g.home, { market: showMk && !isNum(g.p_draw) ? 1 - g.market_home : null, label: live ? 'Live win chance' : 'Our win chance' }) : '';
  var hA = (g.home && (g.home.abbr || g.home.name)) || 'Home', aA = (g.away && (g.away.abbr || g.away.name)) || 'Away';
  var left = '';
  if (pre && isNum(g.p_home)) left = '<span class="ours">Our chance' + (isNum(g.p_draw) ? ' · draw <b>' + fmt.pct(g.p_draw) + '</b>' : '') + '</span>';
  else if (live && isNum(g.p_home)) left = '<span class="ours">Live chance</span>';
  else if (fin && isNum(g.p_home)) left = '<span>Pre-game: <b>' + esc(favA ? aA : hA) + ' ' + fmt.pct(favA ? pA : g.p_home) + '</b></span>';
  var xg = g.xg && isNum(g.xg[0]) && isNum(g.xg[1]) ? '<span>xG <b>' + g.xg[0].toFixed(1) + '–' + g.xg[1].toFixed(1) + '</b></span>' : '';
  var mk = showMk ? '<span class="qk-mkt" data-tip="' + esc(o.marketTip || 'The market’s probability, shown as a reference next to ours') + '">' + esc(o.marketLabel || 'Market') + ' <b>' + esc(hA) + ' ' + fmt.pct(g.market_home) + '</b></span>' : '';
  var tag = g.href ? 'a' : 'div';
  return '<' + tag + (g.href ? ' href="' + esc(g.href) + '"' : '') + ' class="qk-gc' + (live ? ' is-live' : fin ? ' is-final' : '') + '" style="--sa:' + (s.accent || 'var(--accent)') + '">' +
    '<div class="qk-gc-top"><span class="qk-gc-lg">' + (o.sport !== false ? '<span class="qk-sportpill">' + esc(s.label || g.sport) + '</span> · ' : '') + esc(g.league || '') + (g.note && g.note !== 'OT' && g.note !== 'SO' ? ' · ' + esc(g.note) : '') + '</span>' + QK.statusBadge(g) + '</div>' +
    '<div class="qk-gc-rows">' + row(g.away, as, pA, hw > 0, favA) + row(g.home, hs, g.p_home, hw < 0, !favA) + '</div>' + bar +
    (left || xg || mk ? '<div class="qk-gc-foot">' + (left || '<span></span>') + (xg || '') + mk + '</div>' : '') + '</' + tag + '>';
};

/* ─────────────────────────────────────── chance bars (538-style probability bars) */
/* QK.chanceBar({ label, p, market, color (team hex or CSS colour; default the signal), href, sub, mark: team }, { max })
 * QK.chances(rows, { max, sort: false, key: false, marketName: 'Market', limit }) -> the list with a key. */
QK.chanceBar = function (r, o) {
  o = o || {};
  var max = isNum(o.max) && o.max > 0 ? o.max : 1;
  var w = Math.max(0, Math.min(100, 100 * (isNum(r.p) ? r.p : 0) / max));
  var c = r.color ? (color.parse(r.color) ? color.team(r.color) : r.color) : 'var(--signal)';
  var mk = isNum(r.market) ? '<i class="qk-chance-mk" style="left:' + Math.min(100, 100 * r.market / max).toFixed(1) + '%"></i>' : '';
  var aria = r.label + ': our chance ' + fmt.pct(r.p) + (isNum(r.market) ? ', market ' + fmt.pct(r.market) : '');
  var tag = r.href ? 'a' : 'div';
  return '<' + tag + ' class="qk-chance"' + (r.href ? ' href="' + esc(r.href) + '"' : '') + '>' +
    '<span class="qk-chance-lab">' + (r.mark ? QK.teamMark(r.mark, 'sm') : '') + '<span>' + esc(r.label) + (r.sub ? ' <small>' + esc(r.sub) + '</small>' : '') + '</span></span>' +
    '<span class="qk-chance-track" role="img" aria-label="' + esc(aria) + '"><span class="qk-chance-fill" style="width:' + w.toFixed(1) + '%;--cc:' + c + '"></span>' + mk + '</span>' +
    '<span class="qk-chance-v">' + fmt.pct(r.p) + '</span></' + tag + '>';
};
QK.chances = function (rows, o) {
  o = o || {};
  var rs = (rows || []).filter(function (r) { return r && isNum(r.p); });
  if (o.sort !== false) rs.sort(function (a, b) { return b.p - a.p; });
  if (o.limit) rs = rs.slice(0, o.limit);
  var mx = o.max;
  if (!isNum(mx)) { var m = Math.max.apply(null, rs.map(function (r) { return Math.max(r.p || 0, isNum(r.market) ? r.market : 0); }).concat([0.01])); mx = m > 0.6 ? 1 : Math.min(1, Math.ceil(m * 10 + 0.4) / 10); }
  var anyM = rs.some(function (r) { return isNum(r.market); });
  return '<div class="qk-chances">' + rs.map(function (r) { return QK.chanceBar(r, { max: mx }); }).join('') +
    (o.key === false ? '' : '<div class="qk-chances-key"><span><i class="bar"' + (rs.some(function (r) { return !!r.color; }) ? ' style="background:var(--ink-3)"' : '') + '></i>' + esc(o.oursName || 'Our chance') + '</span>' + (anyM ? '<span><i class="tick"></i>' + esc(o.marketName || 'Market (reference)') + '</span>' : '') + (mx < 1 ? '<span>Scale 0–' + fmt.pct(mx) + '</span>' : '') + '</div>') + '</div>';
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
  return '<' + tag + ' class="qk-stat' + (k.cls ? ' ' + esc(k.cls) : '') + '"' + (k.href ? ' href="' + esc(k.href) + '"' : '') + '>' +
    '<div class="qk-stat-label">' + lab + (isNum(k.pctl) ? QK.pctlChip(k.pctl) : '') + '</div>' +
    '<div class="qk-stat-v' + (k.signal ? ' signal' : '') + (k.text ? ' text' : '') + '">' + v + (k.unit && !empty ? '<span class="u">' + esc(k.unit) + '</span>' : '') + '</div>' +
    (dl || sub ? '<div class="qk-stat-sub">' + dl + (sub ? '<span>' + sub + '</span>' : '') + '</div>' : '') + spark + '</' + tag + '>';
};
QK.stats = function (list) {
  return '<div class="qk-stats">' + (list || []).filter(Boolean).map(function (x) { return typeof x === 'string' ? x : QK.statTile(x); }).join('') + '</div>';
};

/* ─────────────────────────────────────── player card header */
/* QK.playerHeader({ name, number, pos, team: { name, abbr, colour, href }, kicker, meta: [[label, value] | html],
 * stats: [{ label, value, sub }], tags: [html], split: false (keep the name on one line) }) */
QK.playerHeader = function (o) {
  o = o || {};
  var t = o.team || {};
  var tc = t.colour && color.parse(t.colour) ? color.team(t.colour) : (o.colour || 'var(--signal)');
  var nm = String(o.name || '');
  var sp = o.split === false ? -1 : nm.indexOf(' ');
  var name = sp > 0 ? '<small>' + esc(nm.slice(0, sp)) + '</small>' + esc(nm.slice(sp + 1)) : esc(nm);
  var kick = [o.pos ? esc(o.pos) : '', t.name ? '<span class="qk-row" style="gap:6px;flex-wrap:nowrap">' + QK.teamMark(t, 'sm') + (t.href ? '<a href="' + esc(t.href) + '">' + esc(t.name) + '</a>' : esc(t.name)) + '</span>' : '', o.kicker ? esc(o.kicker) : ''].filter(Boolean).join('<span aria-hidden="true">·</span>');
  var meta = (o.meta || []).filter(Boolean).map(function (m) { return Array.isArray(m) ? '<span>' + esc(m[0]) + ' <b>' + esc(m[1]) + '</b></span>' : '<span>' + m + '</span>'; }).join('');
  var stats = (o.stats || []).filter(Boolean).map(function (s) {
    return '<div class="qk-ph-stat"><div class="v">' + esc(s.value === undefined || s.value === null ? '—' : s.value) + '</div><div class="l">' + esc(s.label) + '</div>' + (s.sub ? '<div class="s">' + esc(s.sub) + '</div>' : '') + '</div>';
  }).join('');
  return '<section class="qk-ph" style="--tc:' + esc(tc) + '">' + (isNum(o.number) || /^\d+$/.test(String(o.number || '')) ? '<div class="qk-ph-num" aria-hidden="true">' + esc(o.number) + '</div>' : '') +
    '<div style="min-width:0"><div class="qk-ph-kicker">' + kick + '</div><h1 class="qk-ph-name">' + name + '</h1>' +
    (meta ? '<div class="qk-ph-meta">' + meta + '</div>' : '') + ((o.tags || []).length ? '<div class="qk-ph-tags">' + o.tags.join('') + '</div>' : '') + '</div>' +
    (stats ? '<div class="qk-ph-stats">' + stats + '</div>' : '') + '</section>';
};

/* ─────────────────────────────────────── percentile card (Savant style) */
/* QK.pctCard({ title, peer: 'NHL forwards', sample: '7 GP · 117 min at 5v5', groups: [{ label, rows: [{ label, pctl,
 * value, tip, early }] }], note, foot, right (HTML in the head), id, cls }). The peer group and sample are always
 * shown; a row marked early (below the sample where the metric settles) gets a dashed knob and a footnote. */
QK.pctCard = function (o) {
  o = o || {};
  var early = false;
  var groups = (o.groups || []).map(function (g) {
    var rows = (g.rows || []).filter(function (r) { return r && isNum(r.pctl); });
    rows.forEach(function (r) { if (r.early) early = true; });
    return rows.length ? '<div class="qk-pgrp">' + (g.label ? '<div class="qk-pgrp-h">' + esc(g.label) + '</div>' : '') + QK.pctlBars(rows) + '</div>' : '';
  }).join('');
  var head = '<div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(o.title || 'Percentile rankings') + '</div>' +
    '<div class="qk-pcard-peer">' + (o.peer ? QK.tag('Peers: ' + o.peer, 'signal') : '') + (o.sample ? '<span>' + esc(o.sample) + '</span>' : '') + '</div></div>' + (o.right || '') + '</div>';
  var body = groups ? '<div class="qk-pscale" aria-hidden="true"><span>Poor</span><i></i><span>Great</span></div>' + groups +
    (early ? '<div class="qk-pnote">A dashed knob and a trailing dot mark a metric still short of the sample where it settles down: read it as early.</div>' : '') +
    (o.note ? '<div class="qk-pnote">' + esc(o.note) + '</div>' : '')
    : QK.empty(o.emptyTitle || 'Not enough data yet', o.emptyText || 'Percentiles appear once the sample floors are met.');
  return '<section class="qk-card qk-pcard' + (o.cls ? ' ' + esc(o.cls) : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' + head +
    '<div class="qk-card-body">' + body + '</div>' + (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};

/* ─────────────────────────────────────── leaderboard */
/* QK.leaderboard(el, spec): QK.table with column types —
 *   { type: 'entity', key, sub: 'key', mark: fn(row) -> team, href: fn(row) }   name, team mark, sub-line (pinned)
 *   { type: 'pctl', key, pctl: 'pct_key', fmt, d }                                value on a percentile heat cell
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
        return isNum(p) ? '<span class="qk-pcell" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '" title="' + esc(QK.ordinal(p)) + ' percentile">' + t + '</span>' : t;
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
var CMP_FALLBACK = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-3)'];
QK.compareView = function (o) {
  o = o || {};
  var E = (o.entities || []).slice(0, 3), n = E.length, delta = o.delta !== false && n === 2;
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
          '<span class="p"' + (isNum(p) ? ' title="' + esc(QK.ordinal(p)) + ' percentile"' : '') + '>' + (isNum(p) ? Math.round(p) : '') + '</span></div>';
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
  var short = function (e) { return e.abbr || String(e.name || '').split(' ').slice(-1)[0]; };
  var head = '<div class="qk-cmp-head"><div class="qk-cmp-dh" style="text-align:left">' + esc(o.metricLabel || 'Metric · value · percentile') + '</div>' + E.map(function (e, i) {
    var nm = '<b>' + esc(e.name) + '</b>';
    return '<div class="qk-cmp-ent" style="--ec:' + cols[i] + '">' + (e.href ? '<a class="qk-cmp-a" href="' + esc(e.href) + '">' + nm + '</a>' : nm) + '<small>' + esc(e.sub || '') + '</small>' +
      (total ? '<span class="wins">Better on ' + wins[i] + ' of ' + total + '</span>' : '') + '</div>';
  }).join('') + (delta ? '<div class="qk-cmp-dh" title="' + esc(E[0].name) + ' minus ' + esc(E[1].name) + '">Δ ' + esc(short(E[0])) + '</div>' : '') + '</div>';
  return '<div class="qk-cmp' + (delta ? '' : ' nodelta') + '" style="--n:' + n + '">' + head + (body || QK.empty('Nothing to compare', 'These players share no metrics with values this season.')) + '</div>';
};

/* ─────────────────────────────────────── matchup bar (tale of the tape) */
/* QK.matchupBar({ left: team, right: team, rows: [{ label, a, b, fmt, better: 'high' | 'low', tip }], colors: [l, r] }) */
QK.matchupBar = function (o) {
  o = o || {};
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

root.QK = QK;
})(window);
