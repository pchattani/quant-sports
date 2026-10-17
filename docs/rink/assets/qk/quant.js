/* The Quant — shared UI kit (v1). Framework-free; one global, QK.
 * Older-browser rule shared with the sites: no optional chaining, no nullish coalescing.
 *
 *   QK.SPORTS / QK.sport(key)          the seven sites: names, URLs, accents, icons
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
 *   QK.fmt.*                           numbers, percents, odds, local times */
(function (root) {
'use strict';

var QK = root.QK || {};
QK.version = '1.1.0';

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
  empty: '<svg viewBox="0 0 36 36" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="5" y="8" width="26" height="20" rx="3"/><path d="M5 14h26M11 20h8M11 24h5"/></svg>',
  arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 8h10M9 4l4 4-4 4"/></svg>'
};
QK.ICON = ICON;

/* ─────────────────────────────────────── sports registry + IA */
var PUB = 'https://pchattani.github.io/';
QK.HOME_URL = PUB + 'the-quant/';
QK.SPORTS = [
  { key: 'football',   label: 'Football',   site: 'The Quant Footballer', repo: 'the-quant-footballer', folder: 'site',     leagues: 'Europe, the Americas, Asia, Africa · 69 competitions' },
  { key: 'nfl',        label: 'NFL',        site: 'The Quant Gridiron',   repo: 'the-quant-gridiron',   folder: 'gridiron', leagues: 'NFL' },
  { key: 'basketball', label: 'Basketball', site: 'The Quant Hardwood',   repo: 'the-quant-hardwood',   folder: 'hardwood', leagues: 'NBA · WNBA' },
  { key: 'baseball',   label: 'Baseball',   site: 'The Quant Bullpen',    repo: 'the-quant-bullpen',    folder: 'bullpen',  leagues: 'MLB · Triple-A' },
  { key: 'hockey',     label: 'Hockey',     site: 'The Quant Rink',       repo: 'the-quant-rink',       folder: 'rink',     leagues: 'NHL' },
  { key: 'f1',         label: 'F1',         site: 'The Quant Paddock',    repo: 'the-quant-paddock',    folder: 'paddock',  leagues: 'Formula 1 · 1950 to today' },
  { key: 'tennis',     label: 'Tennis',     site: 'The Quant Ace',        repo: 'the-quant-ace',        folder: 'ace',      leagues: 'ATP · WTA' }
];
QK.SPORTS.forEach(function (s) { s.url = PUB + s.repo + '/'; s.data = s.url + 'data/'; s.accent = 'var(--a-' + s.key + ')'; });
QK.sport = function (key) { for (var i = 0; i < QK.SPORTS.length; i++) if (QK.SPORTS[i].key === key) return QK.SPORTS[i]; return null; };
/* Local preview: when a page is served from docs/ (http://127.0.0.1:<port>/home/...), link sibling folders. */
QK.localBase = function () {
  var l = root.location || {};
  return /^(localhost|127\.0\.0\.1)$/.test(l.hostname || '') || l.protocol === 'file:';
};
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
  baseball: { fixtures: 'Games' }, basketball: { fixtures: 'Games' }, hockey: { fixtures: 'Games' }, nfl: { fixtures: 'Games' }
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
};

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
 *                rows, sort: { key, dir: 'desc' }, rank: true, dense: true, maxHeight: 480, onRow(row) })
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
      return '<tr>' + (spec.rank ? '<td class="rank num">' + (i + 1) + '</td>' : '') + cols.map(function (c) { return cell(c, r); }).join('') + '</tr>';
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
  return '<span class="qk-pctl" data-band="' + band + '" title="' + Math.round(p) + 'th percentile">' + Math.round(p) + '</span>';
};
/* Savant-style percentile bars: rows [{label, pctl, value}] */
QK.pctlBars = function (rows) {
  function col(p) { return p >= 50 ? color.mix(cssVar('--div-mid') || '#383835', cssVar('--div-pos'), Math.min(1, (p - 50) / 45 + 0.25)) : color.mix(cssVar('--div-mid') || '#383835', cssVar('--div-neg'), Math.min(1, (50 - p) / 45 + 0.25)); }
  return '<div class="qk-pbars">' + rows.map(function (r) {
    var p = Math.max(0, Math.min(100, r.pctl)), c = col(p);
    return '<div class="qk-pbar"><span class="qk-pbar-label" title="' + esc(r.label) + '">' + esc(r.label) + '</span>' +
      '<span class="qk-pbar-track" role="img" aria-label="' + esc(r.label) + ': ' + Math.round(p) + 'th percentile"><span class="qk-pbar-fill" style="width:' + p + '%;background:' + c + '"></span>' +
      '<span class="qk-pbar-knob" style="left:' + p + '%;background:' + c + ';color:' + color.ink(c) + '">' + Math.round(p) + '</span></span>' +
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
 * that clears 3:1 on the card, else the model blue (left) and market orange (right). */
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
  if (side === 'right' && c && o && color.contrast(c, o) < 1.6) c = null;
  return c || (raw ? null : (side === 'left' ? 'var(--c-1)' : 'var(--c-2)'));
};
/* Model-v-market strip on a 0-100% track: blue dot = model, orange dot = market. */
QK.mvm = function (model, market, label) {
  if (!isNum(model) || !isNum(market)) return '';
  var a = Math.min(model, market) * 100, b = Math.max(model, market) * 100;
  return '<div class="qk-mvm" role="img" aria-label="' + esc(label || '') + ' model ' + fmt.pct(model) + ', market ' + fmt.pct(market) + '">' +
    '<span>' + esc(label || 'Model v mkt') + '</span><span class="qk-mvm-track"><span class="qk-mvm-link" style="left:' + a + '%;width:' + (b - a) + '%"></span>' +
    '<span class="qk-mvm-dot k" style="left:' + market * 100 + '%"></span><span class="qk-mvm-dot m" style="left:' + model * 100 + '%"></span></span>' +
    '<span class="qk-mvm-val"><b style="color:var(--c-model)">' + Math.round(model * 100) + '</b> v <b style="color:var(--c-market)">' + Math.round(market * 100) + '</b></span></div>';
};

/* ─────────────────────────────────────── game card + ticker item */
/* Game shape (home.json and every site's adapters):
 * { sport, league, id, start, status: pre|live|final, home:{name,abbr,colour,logo}, away:{…}, hs, as,
 *   p_home, p_draw, p_away, market_home, note, clock, period, href } */
QK.statusBadge = function (g) {
  if (g.status === 'live') return '<span class="qk-badge live">Live' + (g.period ? ' · ' + esc(QK.periodLabel(g)) : '') + '</span>';
  if (g.status === 'final') return '<span class="qk-badge final">Final' + (g.note === 'OT' ? '/OT' : '') + '</span>';
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
      '<span class="p" title="Model win probability">' + (isNum(p) && !fin ? fmt.pct(p) : '') + '</span>' +
      '<span class="sc">' + (fin || live ? (isNum(sc) ? sc : '–') : '') + '</span></div>';
  }
  var foot = '';
  if (!fin && isNum(g.p_home)) foot = QK.probBar(pA, g.p_draw, g.p_home, g.away, g.home);
  /* pre-game only: a live market has moved with the score, the pre-game model has not */
  var pre = g.status === 'pre';
  var mk = pre && isNum(g.market_home) && isNum(g.p_home) ? QK.mvm(g.p_home, g.market_home, 'Model v mkt') : '';
  var xg = g.xg && isNum(g.xg[0]) ? '<span class="num">xG ' + g.xg[0].toFixed(1) + '–' + g.xg[1].toFixed(1) + '</span>' : '';
  var edge = isNum(g.market_home) && isNum(g.p_home) && pre && Math.abs(g.p_home - g.market_home) >= 0.08 ? '<span class="qk-badge edge" data-tip="Model and market disagree by ' + Math.round(Math.abs(g.p_home - g.market_home) * 100) + ' points on the home side">Edge ' + fmt.pp(g.p_home - g.market_home) + '</span>' : '';
  var tag = g.href ? 'a' : 'div';
  return '<' + tag + (g.href ? ' href="' + esc(g.href) + '"' : '') + ' class="qk-match' + (live ? ' is-live' : '') + '" style="--sa:' + (s.accent || 'var(--accent)') + '">' +
    '<div class="qk-match-top"><span class="lg">' + (opts.sport !== false ? '<span class="qk-sportpill">' + esc(s.label || g.sport) + '</span> · ' : '') + esc(g.league || '') + (g.note && g.note !== 'OT' ? ' · ' + esc(g.note) : '') + '</span>' + QK.statusBadge(g) + '</div>' +
    '<div class="qk-match-teams">' + row(g.away, as, pA, hw > 0) + row(g.home, hs, g.p_home, hw < 0) + '</div>' +
    (foot || mk || xg || edge ? '<div class="qk-stack" style="--g:6px">' + foot + (mk ? '<div style="margin-top:6px">' + mk + '</div>' : '') + '</div>' : '') +
    (xg || edge ? '<div class="qk-match-foot">' + (xg || '<span></span>') + edge + '</div>' : '') +
    '</' + tag + '>';
};
/* 'Today 18:30' → '18:30'; another day → 'Sat 18:30' */
QK.whenShort = function (iso) {
  var r = fmt.relDay(iso);
  if (r === 'Today') return fmt.time(iso);
  var d = new Date(iso);
  return (isNaN(d) ? '' : d.toLocaleDateString(undefined, { weekday: 'short' })) + ' ' + fmt.time(iso);
};
QK.tick = function (g) {
  var fin = g.status === 'final', live = g.status === 'live';
  var s = QK.sport(g.sport) || {};
  function r(t, sc, lost) { return '<div class="qk-tick-row' + (fin && lost ? ' lost' : '') + '"><span class="qk-truncate">' + esc(t.abbr || t.name) + '</span><span class="s">' + (fin || live ? (isNum(sc) ? sc : '–') : (isNum(t._p) ? fmt.pct(t._p) : '')) + '</span></div>'; }
  var hw = isNum(g.hs) && isNum(g.as) ? (g.hs > g.as ? 1 : g.hs < g.as ? -1 : 0) : 0;
  var a = Object.assign({}, g.away, { _p: isNum(g.p_away) ? g.p_away : (isNum(g.p_home) && !isNum(g.p_draw) ? 1 - g.p_home : null) });
  var hm = Object.assign({}, g.home, { _p: g.p_home });
  return '<a class="qk-tick" href="' + esc(g.href || '#') + '" style="--sa:' + (s.accent || '') + '"><div class="qk-tick-top"><span class="qk-sportpill">' + esc(s.label || '') + '</span><span class="st' + (live ? ' live' : '') + '">' +
    (live ? '● ' + esc(QK.periodLabel(g) || 'Live') : fin ? 'Final' : esc(QK.whenShort(g.start))) + '</span></div>' + r(a, g.as, hw > 0) + r(hm, g.hs, hw < 0) + '</a>';
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

root.QK = QK;
})(window);
