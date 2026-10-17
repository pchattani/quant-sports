/* The Quant Footballer — one page per person and one page per club.
 *
 *   #/player/<pid>   every appearance of one person: club, cups, continental and
 *                    international, filtered by ?scope=club|intl, ?c=<slug>, ?e=<era>
 *   #/club/<tid>     one club or national team across competitions and seasons, with
 *                    its current squad, filtered by ?c=<slug> and ?e=<era>
 *
 * Reads data/people/<pid>.json and data/clubs/<tid>.json (UNIFIED_PAYLOADS.md §2-3).
 * When those are missing it falls back to what the older payloads hold
 * (season_index.json, careers/<pid>.json, the competition's own files), so the
 * pages degrade rather than fail. With a live competition selected the page adds
 * that competition's season dossier (percentiles, analytics, shot map) from
 * pages.js, rendered with the competition's payloads. */
(function (FH) {
'use strict';

const { INDEX, C, PALETTE, esc, num, pct, signed, fmtMetric, fmtDate, crest, statTile, tableHTML, setHTML, sortableIn, wireRowLinks,
        probBar, resultClass, statusChip, plot, layout, loadSite, ensureComp, withComp, clubHref, personHref, rowsOf, currentSeason } = FH;

const KIND_LABEL = { league: 'League', domestic_cup: 'National cup', super_cup: 'Super cup', continental_club: 'Continental', international: 'International' };
const KIND_ORDER = { league: 0, continental_club: 1, domestic_cup: 2, super_cup: 3, international: 4 };
const KIND_COLOR = { league: C.blue, continental_club: C.purple, domestic_cup: C.teal, super_cup: C.yellow, international: C.green };
const POS_LABEL = { G: 'Goalkeeper', D: 'Defender', M: 'Midfielder', F: 'Forward' };
const POS_GROUP = { G: 'Goalkeepers', D: 'Defenders', M: 'Midfielders', F: 'Forwards' };

function compOf(slug) { return INDEX.competitions.find(c => c.slug === slug) || null; }
function kindOf(slug) {
  const c = compOf(slug);
  if (!c) return 'league';
  if (c.kind_u) return c.kind_u;
  if (c.kind !== 'cup') return 'league';
  return { domestic: 'domestic_cup', super: 'super_cup', international: 'international' }[c.family] || 'continental_club';
}
function scopeOf(slug) { return kindOf(slug) === 'international' ? 'international' : 'club'; }
function compName(slug, names) { const c = compOf(slug); return c ? c.name : ((names || {})[slug] || {}).name || slug || '—'; }
function compShort(slug, names) { const c = compOf(slug); return c ? (c.short_name || c.name) : compName(slug, names); }
function has(v) { return v !== undefined && v !== null && !(typeof v === 'number' && isNaN(v)); }
function sum(rows, k) { return rows.reduce((s, r) => s + (has(r[k]) ? Number(r[k]) : 0), 0); }
function wavg(rows, k, w) { let a = 0, b = 0; rows.forEach(r => { if (has(r[k]) && r[k] > 0 && (r[w] || 0) > 0) { a += r[k] * r[w]; b += r[w]; } }); return b ? a / b : null; }
function ordinal(n) { const v = n % 100; return n + (v >= 11 && v <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th'); }
function initialsOf(name) { return String(name || '?').split(' ').filter(Boolean).map(w => w[0]).join('').slice(0, 2).toUpperCase(); }
function kindChip(kind) { return '<span class="chip kind-chip kind-' + esc(kind || '') + '">' + esc(KIND_LABEL[kind] || kind || '') + '</span>'; }
function posBadge(p) { return p ? '<span class="pos-badge pos-' + esc(p) + '">' + esc(p) + '</span>' : ''; }
function crestOf(name, tid, size) { return crest(name, tid ? 'assets/crests/' + tid + '.png' : null, size); }
function clubA(name, tid, slug) {
  if (!name) return '<span class="muted-inline">—</span>';
  return tid ? '<a class="team-link" href="' + esc(clubHref(tid, slug)) + '">' + crestOf(name, tid) + esc(name) + '</a>' : crestOf(name, null) + esc(name);
}
/* "2025/26" sorts after "2025": compare on the first year, split seasons last. */
function eraKey(e) { const m = /(\d{4})(?:\/(\d{2,4}))?/.exec(String(e || '')); return m ? Number(m[1]) + (m[2] ? 0.5 : 0) : -1; }
/* An era for a row that has none, from its season label. */
function eraOfSeason(s) {
  const t = String(s || '');
  let m = /(\d\d)\/(\d\d)/.exec(t);
  if (m) return '20' + m[1] + '/' + m[2];
  m = /(19|20)\d\d/.exec(t);
  return m ? m[0] : t;
}
/* The season key of a date in a player's frame: a split season turns on 1 August for international
   football (a June or July tournament closes the season), a calendar season is the year. */
const NEUTRAL = { 'club-world-cup': 1, 'intercontinental-cup': 1 };
function frameEra(frame, date) {
  const d = String(date || '');
  if (d.length < 7) return null;
  const y = Number(d.slice(0, 4)), m = Number(d.slice(5, 7));
  if (frame !== 'split') return String(y);
  const s = m >= 8 ? y : y - 1;
  return s + '/' + String((s + 1) % 100).padStart(2, '0');
}
/* A match has its own page in the live edition or within the last year (build_site_all.has_match_page);
   older appearances (a past season backfilled for its totals) are in the log without a link. */
const PAGE_CUTOFF = new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10);
function hasMatchPage(r) {
  const c = compOf(r.comp);
  return (c && String(currentSeason(c).sid) === String(r.sid)) || String(r.date || '') >= PAGE_CUTOFF;
}
function moneyShort(v, cur) {
  const n = Number(v) || 0, sym = !cur || cur === 'EUR' ? '€' : cur + ' ';
  return n >= 1e6 ? sym + (Math.round(n / 1e5) / 10) + 'm' : n >= 1e3 ? sym + Math.round(n / 1e3) + 'k' : sym + n;
}
/* A season x competition row's data coverage, for the Source column. */
function coverageChip(r) {
  if (r.coverage === 'partial' || r.coverage === 'none') {
    const c = r.cov || [];
    const why = r.gap === 'backfill' ? 'the missing matches are being backfilled' : r.gap === 'unavailable' ? 'Sofascore has no line-ups for the missing matches' : 'the missing ties are outside what the site fetches';
    return ' <span class="chip warn" title="Line-ups for ' + (c[0] || 0) + ' of the team\'s ' + (c[1] || 0) + ' matches: ' + why + '. The figures are a lower bound.">partial' + (c.length ? ' ' + c[0] + '/' + c[1] : '') + '</span>';
  }
  if (r.coverage === 'totals' && r.source !== 'archive') return ' <span class="chip" title="Sofascore\'s season totals: our line-ups cover only part of this season' + (r.lineups ? ' (' + r.lineups.min + ' minutes in them)' : '') + '">season totals</span>';
  return '';
}
function seasonHref(slug, sid) {
  const c = compOf(slug);
  if (!c) return null;
  return String(sid) === currentSeason(c).sid || !has(sid) ? '#/' + slug + '/' : '#/' + slug + '/p-table?s=' + encodeURIComponent(sid);
}

// ── shared: the filter bar ────────────────────────────────────────────────

/* Filters live in the query string; changing one rewrites it without a reload. */
function setQuery(base, q) {
  const target = '#/' + base + FH.queryString(q);
  if (location.hash !== target) history.replaceState(null, '', target);
  FH.STATE.query = q;
}

function filterBar(id, q, opts) {
  const o = opts || {};
  const chip = (val, label, n) => '<button type="button" class="fam-btn' + ((q.scope || '') === val ? ' active' : '') + '" data-scope="' + val + '">' + esc(label) + (n !== undefined ? ' <span>' + n + '</span>' : '') + '</button>';
  let h = '<div class="card filter-card"><div class="controls filter-bar" id="' + id + '">';
  if (o.scopes) h += '<div class="scope-chips">' + chip('', 'All', o.counts.all) + chip('club', 'Club only', o.counts.club) + chip('intl', 'International only', o.counts.intl) + '</div>';
  h += '<label>Competition <select class="team-select" data-f="c"><option value="">All competitions</option>' +
    o.comps.map(c => '<option value="' + esc(c.slug) + '"' + (q.c === c.slug ? ' selected' : '') + '>' + esc(c.name) + '</option>').join('') + '</select></label>';
  h += '<label>Season <select class="team-select" data-f="e"><option value="">Every season</option>' +
    o.eras.map(e => '<option value="' + esc(e) + '"' + (q.e === e ? ' selected' : '') + '>' + esc(e) + '</option>').join('') + '</select></label>';
  if (q.c || q.e || q.scope) h += '<button type="button" class="btn-ghost" data-reset="1">Clear filters</button>';
  h += '<span class="filter-note muted-inline">' + (o.note || '') + '</span></div></div>';
  return h;
}

function wireFilterBar(id, q, onChange) {
  const bar = document.getElementById(id);
  if (!bar) return;
  bar.querySelectorAll('[data-scope]').forEach(b => b.addEventListener('click', () => onChange(Object.assign({}, q, { scope: b.dataset.scope || undefined }))));
  bar.querySelectorAll('select[data-f]').forEach(s => s.addEventListener('change', () => { const n = Object.assign({}, q); n[s.dataset.f] = s.value || undefined; onChange(n); }));
  const r = bar.querySelector('[data-reset]');
  if (r) r.addEventListener('click', () => onChange({}));
}

// ══ person ═══════════════════════════════════════════════════════════════

let PERSON_TOKEN = 0;

/* data/people/<pid>.json, or a person assembled from season_index.json and the career archive. */
function loadPerson(pid) {
  return loadSite('people/' + pid + '.json').then(doc => {
    if (doc && doc.id) return Object.assign({ unified: true }, doc);
    return Promise.all([loadSite('season_index.json'), FH.fetchJSON('data/careers/' + pid + '.json', null)]).then(([si, car]) => {
      const row = (((si || {}).players || {})[pid]) || null;
      if (!row && !car) return null;
      const det = (car || {}).details || {};
      const seasons = ((row || {}).rows || []).map(r => {
        const c = compOf(r.comp) || {};
        const cs = currentSeason(c);
        return { comp: r.comp, kind: kindOf(r.comp), scope: scopeOf(r.comp), sid: cs.sid, season: cs.season, era: cs.era || eraOfSeason(cs.season),
                 team: r.t, source: 'live', apps: r.apps, min: r.min, g: r.g, a: r.a, xg: r.xg, xa: r.xa, rt: r.rt, sh: r.sh, kp: r.kp, yc: r.y, rc: r.r, pos: r.pos };
      });
      const archive = ((car || {}).seasons || []).map(s => {
        const slug = (INDEX.competitions.find(c => c.name.toLowerCase() === String(s.tournament || '').toLowerCase()) || {}).slug || null;
        return { comp: slug, tournament: s.tournament, kind: slug ? kindOf(slug) : (/world cup|euro|copa am|nations|qualif|friendl/i.test(s.tournament || '') ? 'international' : 'league'),
                 scope: slug ? scopeOf(slug) : (/world cup|euro|copa am|nations|qualif|friendl/i.test(s.tournament || '') ? 'international' : 'club'),
                 season: s.year, era: eraOfSeason(s.year), team: s.team, tid: s.tid, apps: s.apps, min: s.minutes, g: s.goals, a: s.assists, xg: s.xg, xa: s.xa, rt: s.rating, source: 'archive' };
      }).filter(a => !seasons.some(s => s.comp && s.comp === a.comp && s.era === a.era));
      const club = seasons.filter(s => s.scope === 'club').sort((a, b) => (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || (b.min || 0) - (a.min || 0))[0];
      const nt = seasons.find(s => s.scope === 'international');
      return {
        unified: false, id: pid, name: (row || {}).n || det.name, pos: det.position || (seasons[0] || {}).pos, nat: det.country, height: det.height, shirt: det.shirt, foot: det.foot,
        dob: det.dob ? new Date(det.dob * 1000).toISOString().slice(0, 10) : null,
        current_club: club ? { name: club.team, source: 'appearances' } : (det.team ? { name: det.team, tid: det.team_id, source: 'profile' } : null),
        national_team: nt ? { name: nt.team } : null, seasons: seasons, archive: archive, apps: [], apps_fields: []
      };
    });
  });
}

function ageOf(doc) {
  if (has(doc.age)) return doc.age;
  if (!doc.dob) return null;
  const d = new Date(doc.dob + 'T12:00:00Z');
  return isNaN(d.getTime()) ? null : Math.floor((Date.now() - d.getTime()) / (365.25 * 86400000));
}

function renderPerson(param) {
  const pid = String(param || '').split('/')[0];
  const pane = document.getElementById('tab-page');
  const token = ++PERSON_TOKEN;
  pane.innerHTML = '<div class="muted">Loading…</div>';
  loadPerson(pid).then(doc => {
    if (token !== PERSON_TOKEN) return;
    if (!doc) { pane.innerHTML = '<div class="card"><div class="muted">No player with id ' + esc(pid) + ' in the stores or the archive.</div></div>'; return; }
    drawPerson(pane, doc, token);
  }).catch(err => { pane.innerHTML = '<div class="error-banner">Could not load this player: ' + esc(err.message) + '</div>'; });
}

function personRows(doc) {
  const names = doc.comps || {};
  const seasons = (doc.seasons || []).map(s => Object.assign({}, s, {
    kind: s.kind || kindOf(s.comp), scope: s.scope || scopeOf(s.comp), era: s.era || eraOfSeason(s.season), cname: compName(s.comp, names) }));
  // Archive rows may carry the long names (minutes, goals, assists, rating): read either.
  const pick = (r, a, b) => has(r[a]) ? r[a] : r[b];
  const archive = (doc.archive || []).map(s => Object.assign({}, s, {
    min: pick(s, 'min', 'minutes'), g: pick(s, 'g', 'goals'), a: pick(s, 'a', 'assists'), rt: pick(s, 'rt', 'rating'),
    kind: s.kind || (s.comp ? kindOf(s.comp) : 'league'), scope: s.scope || (s.comp ? scopeOf(s.comp) : 'club'), era: s.era || eraOfSeason(s.season),
    cname: s.comp ? compName(s.comp, names) : (s.tournament || '—'), source: 'archive' }));
  const eraBy = {};
  seasons.forEach(s => { eraBy[s.comp + '|' + s.sid] = s.era; });
  const f = doc.apps_fields || [];
  const apps = (doc.apps || []).map(r => {
    const o = {};
    f.forEach((k, i) => { o[k] = r[i]; });
    o.scope = ((names[o.comp] || {}).scope) || scopeOf(o.comp);
    o.kind = ((names[o.comp] || {}).kind) || kindOf(o.comp);
    // International football (and the world club cups) count in the player's own frame by date, as the
    // build does (UNIFIED_PAYLOADS.md 13): a club edition's appearances in that edition's season.
    o.era = ((o.scope === 'international' || NEUTRAL[o.comp]) && doc.frame ? frameEra(doc.frame, o.date) : null) ||
      eraBy[o.comp + '|' + o.sid] || eraOfSeason(o.date ? (Number(o.date.slice(5, 7)) >= 7 ? o.date.slice(0, 4) + '/' + (Number(o.date.slice(0, 4)) + 1) : o.date.slice(0, 4)) : '');
    return o;
  });
  return { seasons: seasons, archive: archive, apps: apps };
}

function matchQ(q) {
  return r => (!q.scope || r.scope === (q.scope === 'intl' ? 'international' : 'club')) && (!q.c || r.comp === q.c) && (!q.e || r.era === q.e);
}

function drawPerson(pane, doc, token) {
  const R = personRows(doc);
  const all = R.seasons.concat(R.archive);
  const q = Object.assign({}, FH.STATE.query || {});
  // A competition filter for a competition he never played in is dropped rather than showing nothing.
  if (q.c && !all.some(r => r.comp === q.c)) delete q.c;
  const age = ageOf(doc);
  const cc = doc.current_club || null, nt = doc.national_team || null;
  const teamTid = (name, scope) => { const t = Object.keys(doc.teams || {}).find(k => doc.teams[k].name === name && (scope === undefined || !!doc.teams[k].national === (scope === 'international'))); return t || null; };
  const sub = [];
  if (cc && cc.name) sub.push(clubA(cc.name, cc.tid || teamTid(cc.name, 'club')) + (cc.source === 'appearances' ? ' <span class="muted-inline" title="From his latest club appearance, not a squad list">(latest club appearance)</span>' : cc.source === 'profile' ? ' <span class="muted-inline">(profile)</span>' : ''));
  else sub.push('<span class="muted-inline">No current club on record</span>');
  if (nt && nt.name) sub.push(clubA(nt.name, nt.tid || teamTid(nt.name, 'international')) + ' <span class="chip nt-chip">national team</span>');
  const chips = [];
  if (doc.pos) chips.push('<span class="chip pos-' + esc(doc.pos) + '">' + esc(POS_LABEL[doc.pos] || doc.pos) + '</span>');
  if (age) chips.push('<span class="chip">' + age + ' years</span>');
  if (doc.height) chips.push('<span class="chip">' + doc.height + ' cm</span>');
  if (doc.nat) chips.push('<span class="chip">' + esc(doc.nat) + '</span>');
  if (doc.shirt) chips.push('<span class="chip">#' + esc(doc.shirt) + '</span>');
  if (doc.foot) chips.push('<span class="chip">' + esc(doc.foot) + ' foot</span>');
  if (doc.mv) chips.push('<span class="chip" title="Sofascore\'s market value, reference only">' + esc(moneyShort(doc.mv, doc.mvc)) + '</span>');
  if (doc.until) chips.push('<span class="chip" title="Contract end, Sofascore">contract to ' + esc(String(doc.until).slice(0, 7)) + '</span>');
  if (cc && cc.as_of) chips.push('<span class="chip" title="Squad source: ' + esc(cc.source || '') + '">club as of ' + esc(fmtDate(cc.as_of, true)) + '</span>');
  if (!doc.unified) chips.push('<span class="chip warn" title="data/people/' + esc(doc.id) + '.json is not built yet">this season and the archive only</span>');

  const compsSeen = {};
  all.forEach(r => { if (r.comp && !compsSeen[r.comp]) compsSeen[r.comp] = { slug: r.comp, name: r.cname, kind: r.kind }; });
  const comps = Object.keys(compsSeen).map(k => compsSeen[k]).sort((a, b) => (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || a.name.localeCompare(b.name));
  const eras = Array.from(new Set(all.map(r => r.era).filter(Boolean))).sort((a, b) => eraKey(b) - eraKey(a));
  const counts = { all: all.length, club: all.filter(r => r.scope === 'club').length, intl: all.filter(r => r.scope === 'international').length };

  pane.innerHTML = FH.pageHeader('<span class="ph-initials">' + esc(initialsOf(doc.name)) + '</span>', esc(doc.name || 'Player ' + doc.id), sub.join(' · '), chips.join('')) +
    '<div id="person-filter"></div><div id="person-body"></div>';
  const draw = nq => {
    Object.keys(nq).forEach(k => { if (!nq[k]) delete nq[k]; });
    setQuery('player/' + doc.id, nq);
    setHTML('person-filter', filterBar('pf-bar', nq, { scopes: true, counts: counts, comps: comps, eras: eras,
      note: (doc.apps || []).length ? (doc.apps.length + ' matches in the stores' + (R.archive.length ? ' · older seasons from the archive (season totals)' : '')) : (R.archive.length ? 'Older seasons from the archive (season totals)' : '') }));
    wireFilterBar('pf-bar', nq, draw);
    drawPersonBody(doc, R, nq, token);
  };
  draw(q);
}

function drawPersonBody(doc, R, q, token) {
  const keep = matchQ(q);
  const rows = R.seasons.filter(keep), arch = R.archive.filter(keep), apps = R.apps.filter(keep);
  const both = rows.concat(arch);
  const names = doc.comps || {};
  const mins = sum(both, 'min'), g = sum(both, 'g'), a = sum(both, 'a');
  const xg = sum(both.filter(r => has(r.xg)), 'xg'), xa = sum(both.filter(r => has(r.xa)), 'xa');
  const rt = wavg(both, 'rt', 'min');
  const starts = sum(rows.filter(r => has(r.starts)), 'starts');
  const nEras = new Set(both.map(r => r.era)).size;
  const label = q.c ? compName(q.c, names) : q.scope === 'club' ? 'club football' : q.scope === 'intl' ? 'international football' : 'all competitions';
  let html = '<div class="kpi-grid six">' +
    statTile('Seasons', nEras, label + (q.e ? ', ' + esc(q.e) : '')) +
    statTile('Appearances', sum(both, 'apps') + (starts ? ' <span class="kpi-dim">(' + starts + ' st)</span>' : ''), mins.toLocaleString('en-US') + ' minutes') +
    statTile('Goals', g, xg ? 'xG ' + num(xg, 1) : '') + statTile('Assists', a, xa ? 'xA ' + num(xa, 1) : '') +
    statTile('G+A per 90', mins ? num((g + a) * 90 / mins, 2) : '—', mins ? num(g * 90 / mins, 2) + ' goals per 90' : '') +
    statTile('Rating', rt ? num(rt, 2) : '—', 'minutes-weighted') + '</div>';

  html += '<div class="grid-2"><div class="card"><div class="card-header">Goals and assists by season <span class="card-sub">Every competition in the filter, stacked by kind.</span></div><div id="pn-ga" style="height:320px"></div></div>' +
    '<div class="card"><div class="card-header">Minutes by season <span class="card-sub">Where the minutes came from: league, cups, continental, international.</span></div><div id="pn-min" style="height:320px"></div></div></div>';
  const dossierOn = !!(q.c && R.seasons.some(s => s.comp === q.c && s.source === 'live') && compOf(q.c) && compOf(q.c).ok && (!q.e || R.seasons.some(s => s.comp === q.c && s.source === 'live' && s.era === q.e)));
  // With a live competition selected, its dossier below carries the match-by-match charts and the full log.
  if (apps.length >= 3 && !dossierOn) html += '<div class="grid-2"><div class="card"><div class="card-header">Match by match <span class="card-sub">Rating per appearance (dots, coloured by kind) and the five-match rolling mean.</span></div><div id="pn-rt" style="height:300px"></div></div>' +
    '<div class="card"><div class="card-header">Goals against xG <span class="card-sub">Cumulative, oldest to newest, across the appearances in the filter.</span></div><div id="pn-xg" style="height:300px"></div></div></div>';

  // Year by year: every competition in the filter summed per season (the competitions below add up to it).
  html += '<div class="card"><div class="card-header">Season by season <span class="card-sub">All competitions in the filter, one row per season' + (doc.frame === 'calendar' ? ' (calendar years, as his club football runs)' : ' (July to June; international matches fall in the season they are played in)') + '.</span></div><div id="pn-years"></div></div>';
  // Career by season.
  const crow = both.slice().sort((x, y) => eraKey(y.era) - eraKey(x.era) || (KIND_ORDER[x.kind] - KIND_ORDER[y.kind]) || (y.min || 0) - (x.min || 0));
  html += '<div class="card"><div class="card-header">Career by season <span class="card-sub">One row per competition, season and team. Store rows carry xG; archive rows are Sofascore\'s season totals; "partial" rows are lower bounds.</span></div><div id="pn-career"></div></div>';
  html += '<div class="card"><div class="card-header">By competition <span class="card-sub">Every season in the filter, summed per competition.</span></div><div id="pn-split"></div></div>';
  html += '<div id="pn-dossier"></div>';
  if (!dossierOn) html += '<div class="card"><div class="card-header">Match log <span class="card-sub" id="pn-log-sub"></span></div><div id="pn-log"></div></div>';

  const best = R.seasons.filter(s => s.source === 'live' && compOf(s.comp)).sort((x, y) => (y.min || 0) - (x.min || 0))[0];
  const cmpComp = q.c && R.seasons.some(s => s.comp === q.c && s.source === 'live') ? q.c : (best ? best.comp : null);
  const pos = doc.pos === 'G' ? 'G' : (doc.pos || 'M');
  html += '<div class="card"><div class="muted">' + (cmpComp ? '<a href="#/compare/players/' + esc(cmpComp) + ':' + esc(doc.id) + '">Compare this player →</a> &nbsp;·&nbsp; <a href="#/lab/' + esc(cmpComp) + '/' + esc(pos) + '">Player lab →</a> &nbsp;·&nbsp; ' : '') +
    '<a href="#/leaders">Global leaders →</a> &nbsp;·&nbsp; <a href="#/value?q=' + encodeURIComponent(doc.name || '') + '">Player value →</a> &nbsp;·&nbsp; <a href="#/transfer?p=' + esc(doc.id) + '">Transfer simulator →</a> &nbsp;·&nbsp; <a href="#/glossary">Glossary →</a></div></div>';
  setHTML('person-body', html);

  // Tables.
  setHTML('pn-career', crow.length ? tableHTML([
    { label: 'Season' }, { label: 'Competition' }, { label: 'Team' }, { label: 'Apps', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' },
    { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }, { label: 'G+A/90', align: 'right' }, { label: 'Rating', align: 'right' }, { label: 'Source', align: 'center' }
  ], crow.map(r => {
    const href = r.comp && r.source !== 'archive' ? seasonHref(r.comp, r.sid) : (r.comp && r.sid ? seasonHref(r.comp, r.sid) : null);
    return { cells: [
      { v: eraKey(r.era) + (r.season ? 0 : 0), html: esc(r.season || r.era || '—') },
      { v: r.cname, html: (href ? '<a href="' + esc(href) + '">' + esc(r.cname) + '</a>' : esc(r.cname)) + ' ' + kindChip(r.kind) },
      { v: r.team || '', html: clubA(r.team, r.tid, r.comp) },
      { v: r.apps || 0, align: 'right' }, { v: r.min || 0, align: 'right' }, { v: r.g || 0, align: 'right' }, { v: r.a || 0, align: 'right' },
      { v: has(r.xg) ? r.xg : -1, html: has(r.xg) ? num(r.xg, 2) : '—', align: 'right' }, { v: has(r.xa) ? r.xa : -1, html: has(r.xa) ? num(r.xa, 2) : '—', align: 'right' },
      { v: r.min ? ((r.g || 0) + (r.a || 0)) * 90 / r.min : 0, html: r.min ? num(((r.g || 0) + (r.a || 0)) * 90 / r.min, 2) : '—', align: 'right' },
      { v: r.rt || 0, html: r.rt ? num(r.rt, 2) : '—', align: 'right' },
      { v: r.source, html: '<span class="chip' + (r.source === 'archive' ? '' : ' st-live') + '">' + esc(r.source === 'live' ? 'current edition' : r.source || '') + '</span>' + coverageChip(r), align: 'center' }
    ] };
  }), { sticky: true }) : '<div class="muted">No appearance matches the filter.</div>');
  sortableIn('pn-career');

  const years = {};
  both.forEach(r => {
    if (!r.era) return;
    const y = years[r.era] || (years[r.era] = { era: r.era, rows: [], club: 0, intl: 0, partial: false });
    y.rows.push(r);
    if (r.scope === 'international') y.intl += r.min || 0; else y.club += r.min || 0;
    if (r.coverage === 'partial' || r.coverage === 'none') y.partial = true;
  });
  const yrows = Object.keys(years).map(k => years[k]).sort((x, y) => eraKey(y.era) - eraKey(x.era));
  setHTML('pn-years', yrows.length ? tableHTML([
    { label: 'Season' }, { label: 'Competitions', align: 'right' }, { label: 'Apps', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' },
    { label: 'G+A/90', align: 'right' }, { label: 'Rating', align: 'right' }, { label: 'Club min', align: 'right' }, { label: 'Intl min', align: 'right' }, { label: 'Data', align: 'center' }
  ], yrows.map(y => {
    const m = sum(y.rows, 'min'), gg = sum(y.rows, 'g'), aa = sum(y.rows, 'a'), rr = wavg(y.rows, 'rt', 'min');
    return { cells: [
      { v: eraKey(y.era), html: '<strong>' + esc(y.era) + '</strong>' }, { v: y.rows.length, align: 'right' }, { v: sum(y.rows, 'apps'), align: 'right' },
      { v: m, align: 'right' }, { v: gg, align: 'right' }, { v: aa, align: 'right' },
      { v: m ? (gg + aa) * 90 / m : 0, html: m ? num((gg + aa) * 90 / m, 2) : '—', align: 'right' },
      { v: rr || 0, html: rr ? num(rr, 2) : '—', align: 'right' }, { v: y.club, align: 'right' }, { v: y.intl, html: y.intl ? String(y.intl) : '—', align: 'right' },
      { v: y.partial ? 0 : 1, html: y.partial ? '<span class="chip warn" title="At least one competition this season is a lower bound (line-ups missing)">partial</span>' : '<span class="chip">complete</span>', align: 'center' }
    ] };
  }), { compact: true }) : '<div class="muted">No season in the filter.</div>');
  sortableIn('pn-years');

  const byComp = {};
  both.forEach(r => { const k = r.comp || r.cname; (byComp[k] = byComp[k] || { comp: r.comp, cname: r.cname, kind: r.kind, rows: [] }).rows.push(r); });
  const splits = Object.keys(byComp).map(k => byComp[k]).sort((x, y) => (KIND_ORDER[x.kind] - KIND_ORDER[y.kind]) || sum(y.rows, 'min') - sum(x.rows, 'min'));
  setHTML('pn-split', splits.length ? tableHTML([
    { label: 'Competition' }, { label: 'Kind' }, { label: 'Seasons', align: 'right' }, { label: 'Apps', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'G', align: 'right' },
    { label: 'A', align: 'right' }, { label: 'G+A/90', align: 'right' }, { label: 'Rating', align: 'right' }, { label: '', sortable: false }
  ], splits.map(s => {
    const m = sum(s.rows, 'min'), gg = sum(s.rows, 'g'), aa = sum(s.rows, 'a');
    return { cells: [
      { v: s.cname, html: '<strong>' + esc(s.cname) + '</strong>' }, { v: s.kind, html: kindChip(s.kind) }, { v: new Set(s.rows.map(r => r.era)).size, align: 'right' },
      { v: sum(s.rows, 'apps'), align: 'right' }, { v: m, align: 'right' }, { v: gg, align: 'right' }, { v: aa, align: 'right' },
      { v: m ? (gg + aa) * 90 / m : 0, html: m ? num((gg + aa) * 90 / m, 2) : '—', align: 'right' },
      { v: wavg(s.rows, 'rt', 'min') || 0, html: wavg(s.rows, 'rt', 'min') ? num(wavg(s.rows, 'rt', 'min'), 2) : '—', align: 'right' },
      { v: '', html: s.comp ? '<a href="#" class="filter-to" data-c="' + esc(s.comp) + '">only this →</a>' : '' }
    ] };
  })) : '<div class="muted">Nothing to split.</div>');
  sortableIn('pn-split');
  document.querySelectorAll('#pn-split .filter-to').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const nq = Object.assign({}, q, { c: a.dataset.c });
    setQuery('player/' + doc.id, nq);
    drawPerson(document.getElementById('tab-page'), doc, token);
    window.scrollTo(0, 0);
  }));

  // Match log.
  setHTML('pn-log-sub', apps.length ? apps.length + ' appearances in the stores, newest first' + (apps.length > 60 ? ' (the latest 60 shown)' : '') : '');
  setHTML('pn-log', apps.length ? tableHTML([
    { label: 'Date' }, { label: 'Competition' }, { label: 'For' }, { label: 'Opponent' }, { label: 'H/A', align: 'center' }, { label: 'Result', align: 'center' },
    { label: 'Min', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }, { label: 'Rating', align: 'right' }
  ], apps.slice(0, 60).map(r => {
    const team = ((doc.teams || {})[String(r.tid)] || {}).name || '';
    const res = String(r.res || '');
    const wl = res.charAt(0);
    return { _href: r.gid && hasMatchPage(r) ? FH.matchHref(r.gid, r.comp) : null, cells: [
      { v: r.date || '', html: esc(fmtDate(r.date, true)) }, { v: compShort(r.comp, names), html: esc(compShort(r.comp, names)) },
      { v: team, html: clubA(team, r.tid, r.comp) }, { v: r.opp || '', html: clubA(r.opp, r.opp_tid, r.comp) }, { v: r.home ? 'H' : 'A', align: 'center' },
      { v: res, html: '<span class="res-' + esc(wl) + '">' + esc(res) + '</span>', align: 'center' },
      { v: r.min || 0, html: (r.min || 0) + (r.start ? '' : ' <span class="sub-mark" title="substitute">S</span>'), align: 'right' },
      { v: r.g || 0, align: 'right' }, { v: r.a || 0, align: 'right' },
      { v: has(r.xg) ? r.xg : -1, html: has(r.xg) ? num(r.xg, 2) : '—', align: 'right' }, { v: has(r.xa) ? r.xa : -1, html: has(r.xa) ? num(r.xa, 2) : '—', align: 'right' },
      { v: has(r.rt) ? r.rt : 0, html: has(r.rt) ? num(r.rt, 2) : '—', align: 'right' }
    ] };
  }), { sticky: true }) : '<div class="muted">' + (doc.unified ? 'No appearance in the match stores for this filter.' : 'The match log arrives with the unified player payload; the competition dossier below carries this season\'s log.') + '</div>');
  wireRowLinks('pn-log');
  sortableIn('pn-log');

  personCharts(both, apps);

  // The competition's dossier for this season, when a live competition is selected.
  const live = q.c ? R.seasons.find(s => s.comp === q.c && s.source === 'live') : null;
  const c = q.c ? compOf(q.c) : null;
  if (live && c && c.ok && (!q.e || q.e === live.era)) {
    setHTML('pn-dossier', '<div class="dossier-head"><h3>' + esc(c.name) + ' ' + esc(currentSeason(c).season || '') + '</h3><span class="muted-inline">Percentiles against positional peers in this competition, the shot map and the full match log.</span> <a href="#/' + esc(c.slug) + '/players">' + esc(c.short_name || c.name) + ' players →</a></div><div id="pn-dossier-body"><div class="muted">Loading…</div></div>');
    ensureComp(c.slug, ['players_live', 'teams']).then(() => {
      if (token !== PERSON_TOKEN || !document.getElementById('pn-dossier-body')) return;
      withComp(c.slug, () => FH.renderPlayerDossier(document.getElementById('pn-dossier-body'), doc.id, { tiles: false }));
    });
  }
}

function personCharts(rows, apps) {
  const eras = Array.from(new Set(rows.map(r => r.era).filter(Boolean))).sort((a, b) => eraKey(a) - eraKey(b));
  if (!eras.length) { setHTML('pn-ga', '<div class="muted">No season in the filter.</div>'); setHTML('pn-min', ''); return; }
  const kinds = Object.keys(KIND_ORDER).filter(k => rows.some(r => r.kind === k));
  const legend = { showlegend: true, legend: { orientation: 'h', y: 1.14, font: { color: C.text2 } } };
  const per = (k, key) => eras.map(e => sum(rows.filter(r => r.era === e && r.kind === k), key));
  plot('pn-ga', kinds.map(k => ({ type: 'bar', name: KIND_LABEL[k] + ' G+A', x: eras, y: eras.map(e => sum(rows.filter(r => r.era === e && r.kind === k), 'g') + sum(rows.filter(r => r.era === e && r.kind === k), 'a')),
    marker: { color: KIND_COLOR[k] }, customdata: eras.map(e => sum(rows.filter(r => r.era === e && r.kind === k), 'g') + ' G, ' + sum(rows.filter(r => r.era === e && r.kind === k), 'a') + ' A'),
    hovertemplate: '%{x} · ' + KIND_LABEL[k] + ': %{customdata}<extra></extra>' })),
    layout(Object.assign({ barmode: 'stack', bargap: 0.4, margin: { l: 40, r: 15, t: 30, b: 60 }, xaxis: { type: 'category', tickangle: -30 }, yaxis: { title: 'Goals + assists', rangemode: 'tozero' } }, legend)));
  plot('pn-min', kinds.map(k => ({ type: 'bar', name: KIND_LABEL[k], x: eras, y: per(k, 'min'), marker: { color: KIND_COLOR[k] }, hovertemplate: '%{x} · ' + KIND_LABEL[k] + ': %{y} min<extra></extra>' })),
    layout(Object.assign({ barmode: 'stack', bargap: 0.4, margin: { l: 50, r: 15, t: 30, b: 60 }, xaxis: { type: 'category', tickangle: -30 }, yaxis: { title: 'Minutes', rangemode: 'tozero' } }, legend)));
  if (apps.length < 3) return;
  const chron = apps.slice().reverse();
  const xs = chron.map((r, i) => i + 1);
  const rated = chron.map(r => has(r.rt) ? r.rt : null);
  const roll = rated.map((_, k) => { const w = rated.slice(Math.max(0, k - 4), k + 1).filter(v => v !== null); return w.length ? w.reduce((s, v) => s + v, 0) / w.length : null; });
  plot('pn-rt', [
    { type: 'scatter', mode: 'markers', name: 'Rating', x: xs, y: rated, marker: { size: 7, color: chron.map(r => KIND_COLOR[r.kind] || C.text3) },
      text: chron.map(r => fmtDate(r.date, true) + ' · ' + compShort(r.comp) + ' · ' + (r.home ? 'v ' : '@ ') + (r.opp || '') + ' ' + (r.res || '')), hovertemplate: '%{text}<br>rating %{y:.2f}<extra></extra>' },
    { type: 'scatter', mode: 'lines', name: 'Rolling 5', x: xs, y: roll, line: { color: C.text2, width: 2 }, hoverinfo: 'skip' }
  ], layout({ margin: { l: 40, r: 15, t: 10, b: 35 }, xaxis: { title: 'Appearance' }, yaxis: { range: [4.5, 10] } }));
  let cg = 0, cx = 0;
  const hasXg = chron.some(r => has(r.xg));
  plot('pn-xg', [
    { type: 'scatter', mode: 'lines', name: 'Goals', x: xs, y: chron.map(r => (cg += r.g || 0)), line: { color: C.green, width: 2 } }
  ].concat(hasXg ? [{ type: 'scatter', mode: 'lines', name: 'xG', x: xs, y: chron.map(r => (cx += r.xg || 0)), line: { color: C.blue, width: 2, dash: 'dot' } }] : []),
    layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 40, r: 15, t: 30, b: 35 }, xaxis: { title: 'Appearance' }, yaxis: { rangemode: 'tozero' } }));
}

// ══ club ═════════════════════════════════════════════════════════════════

let CLUB_TOKEN = 0;

/* The club's name in a competition, from that competition's teams.json. */
function nameIn(slug, tid) {
  const teams = (((FH.CACHE[slug] || {}).data || {}).teams || {}).teams || {};
  return Object.keys(teams).find(n => String(teams[n].team_id) === String(tid)) || null;
}

/* data/clubs/<tid>.json, or a club assembled from one competition's own payloads. */
function loadClub(tid, q) {
  return loadSite('clubs/' + tid + '.json').then(doc => {
    if (doc && doc.id !== undefined) return Object.assign({ unified: true }, doc);
    return loadSite('clubs_index.json').then(ci => {
      const row = rowsOf(ci).find(r => String(r.id) === String(tid)) || null;
      const slugs = (q.c ? [q.c] : []).concat(row ? (row.comps || []) : []).filter((s, i, a) => compOf(s) && a.indexOf(s) === i);
      if (!slugs.length) return null;
      return Promise.all(slugs.map(s => ensureComp(s, ['teams', 'table', 'fixtures', 'players_live']).then(() => s))).then(list => {
        const names = {};
        list.forEach(s => { const n = nameIn(s, tid); if (n) names[s] = n; });
        const comps = Object.keys(names);
        if (!comps.length) return null;
        const first = comps[0];
        const national = kindOf(first) === 'international';
        const seasons = [], matches = [], squad = {};
        comps.forEach(s => {
          const d = FH.CACHE[s].data, n = names[s], c = compOf(s), cs = currentSeason(c);
          const t = d.table || {};
          let tr = (t.standings || t.overall || []).find(r => r.team === n);
          if (!tr && t.conferences) Object.keys(t.conferences).forEach(gk => { tr = tr || (t.conferences[gk] || []).find(r => r.team === n); });
          seasons.push(Object.assign({ comp: s, kind: kindOf(s), scope: scopeOf(s), sid: cs.sid, season: cs.season, era: cs.era || eraOfSeason(cs.season), source: 'live' },
            tr ? { pos: tr.pos, played: tr.played, w: tr.w, d: tr.d, l: tr.l, gf: tr.gf, ga: tr.ga, pts: tr.pts } : {}));
          ((d.fixtures || {}).matches || []).filter(f => f.home === n || f.away === n).forEach(f => {
            const h = f.home === n;
            const opp = h ? f.away : f.home;
            const ot = ((d.teams || {}).teams || {})[opp] || {};
            matches.push({ id: f.id, comp: s, sid: cs.sid, date: f.date, home: h ? 1 : 0, opp: opp, opp_tid: ot.team_id, status: f.status, gf: h ? f.hs : f.as, ga: h ? f.as : f.hs,
              xg: f.xg ? (h ? f.xg : [f.xg[1], f.xg[0]]) : null, detail: f.detail, model: f.model ? { h: f.model.h, d: f.model.d, a: f.model.a } : null });
          });
          ((d.players_live || {}).players || []).filter(p => p.team === n).forEach(p => {
            const e = squad[p.player_id] || (squad[p.player_id] = { id: p.player_id, name: p.name, pos: p.position, shirt: p.shirt, nat: p.country, age: p.age, height: p.height, min: 0, apps: 0, g: 0, a: 0, rt: p.rating });
            e.min += p.minutes || 0; e.apps += p.matches || 0; e.g += p.goals || 0; e.a += p.assists || 0;
          });
        });
        matches.sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')));
        return { unified: false, id: Number(tid), name: (row || {}).name || names[first], national: national, crest: 'assets/crests/' + tid + '.png', home: (row || {}).home || null,
          names: names, seasons: seasons, matches: matches,
          squad: { source: 'appearances', players: Object.keys(squad).map(k => squad[k]).sort((x, y) => y.min - x.min) } };
      });
    });
  });
}

function renderClub(param) {
  const tid = String(param || '').split('/')[0];
  const pane = document.getElementById('tab-page');
  const token = ++CLUB_TOKEN;
  const q = Object.assign({}, FH.STATE.query || {});
  pane.innerHTML = '<div class="muted">Loading…</div>';
  Promise.all([loadClub(tid, q), loadSite('people_index.json')]).then(([doc, pi]) => {
    if (token !== CLUB_TOKEN) return;
    if (!doc) { pane.innerHTML = '<div class="card"><div class="muted">No club or national team with id ' + esc(tid) + ' in the stores.</div></div>'; return; }
    const people = {};
    rowsOf(pi).forEach(p => { people[String(p.id)] = p; });
    drawClub(pane, doc, people, token);
  }).catch(err => { pane.innerHTML = '<div class="error-banner">Could not load this club: ' + esc(err.message) + '</div>'; });
}

function drawClub(pane, doc, people, token) {
  const seasons = (doc.seasons || []).map(s => Object.assign({}, s, { kind: s.kind || kindOf(s.comp), era: s.era || eraOfSeason(s.season), cname: compName(s.comp) }));
  const matches = (doc.matches || []).map(m => {
    const s = seasons.find(x => x.comp === m.comp && String(x.sid) === String(m.sid));
    return Object.assign({}, m, { kind: kindOf(m.comp), era: s ? s.era : eraOfSeason(String(m.date || '').slice(0, 4)) });
  });
  const q = Object.assign({}, FH.STATE.query || {});
  delete q.scope;
  if (q.c && !seasons.some(s => s.comp === q.c) && !matches.some(m => m.comp === q.c)) delete q.c;
  const home = doc.home ? compOf(doc.home) : null;
  const sub = [];
  if (doc.national) sub.push('<span class="chip nt-chip">national team</span>');
  if (home) sub.push('<a href="#/' + esc(home.slug) + '/">' + esc(home.name) + '</a>');
  if (doc.country) sub.push(esc(doc.country));
  const chips = [];
  if (doc.pool && doc.pool.rank) chips.push('<a class="chip" href="#/clubs" title="Rank on the pooled cross-league scale">pool #' + doc.pool.rank + (has(doc.pool.strength) ? ' · ' + num(doc.pool.strength, 2) + ' PPG' : has(doc.pool.rating) ? ' · ' + num(doc.pool.rating, 2) : '') + '</a>');
  Array.from(new Set(seasons.filter(s => s.source === 'live').map(s => s.comp))).forEach(s => { const c = compOf(s); if (c) chips.push('<a class="chip" href="#/' + esc(s) + '/">' + esc(c.short_name || c.name) + '</a>'); });
  if (!doc.unified) chips.push('<span class="chip warn" title="data/clubs/' + esc(doc.id) + '.json is not built yet">this season only</span>');
  const compsSeen = {};
  seasons.concat(matches).forEach(r => { if (r.comp && !compsSeen[r.comp]) compsSeen[r.comp] = { slug: r.comp, name: compName(r.comp), kind: kindOf(r.comp) }; });
  const comps = Object.keys(compsSeen).map(k => compsSeen[k]).sort((a, b) => (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || a.name.localeCompare(b.name));
  const eras = Array.from(new Set(seasons.map(s => s.era).concat(matches.map(m => m.era)).filter(Boolean))).sort((a, b) => eraKey(b) - eraKey(a));
  pane.innerHTML = FH.pageHeader(crest(doc.name, doc.crest || 'assets/crests/' + doc.id + '.png', 'xl'), esc(doc.name), sub.join(' · '), chips.join('')) +
    '<div id="club-filter"></div><div id="club-body"></div>';
  const draw = nq => {
    Object.keys(nq).forEach(k => { if (!nq[k]) delete nq[k]; });
    setQuery('club/' + doc.id, nq);
    setHTML('club-filter', filterBar('cf-bar', nq, { scopes: false, comps: comps, eras: eras, note: matches.length + ' matches in the stores' }));
    wireFilterBar('cf-bar', nq, draw);
    drawClubBody(doc, seasons, matches, people, nq, token);
  };
  draw(q);
}

function drawClubBody(doc, seasons, matchesAll, people, q, token) {
  const keep = r => (!q.c || r.comp === q.c) && (!q.e || r.era === q.e);
  const ss = seasons.filter(keep);
  const ms = matchesAll.filter(keep);
  const done = ms.filter(m => m.status === 'finished' && has(m.gf) && has(m.ga));
  const w = done.filter(m => m.gf > m.ga).length, dr = done.filter(m => m.gf === m.ga).length, l = done.length - w - dr;
  const gf = sum(done, 'gf'), ga = sum(done, 'ga');
  const withXg = done.filter(m => m.xg);
  const xgf = withXg.reduce((s, m) => s + (m.xg[0] || 0), 0), xga = withXg.reduce((s, m) => s + (m.xg[1] || 0), 0);
  let html = '<div class="kpi-grid six">' +
    statTile('Played', done.length, ms.length - done.length ? (ms.length - done.length) + ' to play' : '') +
    statTile('Record', w + '-' + dr + '-' + l, done.length ? pct(w / done.length, 0) + ' won' : '') +
    statTile('Goals', gf + ' – ' + ga, done.length ? num(gf / done.length, 2) + ' – ' + num(ga / done.length, 2) + ' per match' : '') +
    statTile('xG', withXg.length ? num(xgf / withXg.length, 2) + ' – ' + num(xga / withXg.length, 2) : '—', withXg.length ? 'per match, ' + withXg.length + ' with xG' : 'no xG in the filter') +
    statTile('Points per game', done.length ? num((3 * w + dr) / done.length, 2) : '—', 'every match in the filter') +
    statTile('Clean sheets', done.filter(m => m.ga === 0).length, done.length ? pct(done.filter(m => m.ga === 0).length / done.length, 0) : '') + '</div>';

  // Strengths and needs (value.js): league clubs only; a club without a value file shows nothing.
  html += '<div id="cl-needs"></div><div id="cl-dossier"></div>';
  html += '<div class="card"><div class="card-header">Year by year <span class="card-sub">Every competition in the filter summed per season: the rows below add up to these.</span></div><div id="cl-years"></div></div>';
  html += '<div class="card"><div class="card-header">Season by season <span class="card-sub">Finishing position, record and the model\'s strength where it was fitted.</span></div><div id="cl-seasons"></div></div>' +
    '<div class="card"><div class="card-header">' + (doc.national ? 'Latest call-up' : 'Current squad') + ' <span class="card-sub" id="cl-squad-sub"></span></div><div id="cl-squad"></div></div>';
  html += '<div class="grid-2"><div class="card"><div class="card-header">Points per game by season <span class="card-sub">Matches in the stores, by competition.</span></div><div id="cl-ppg" style="height:300px"></div></div>' +
    '<div class="card"><div class="card-header">xG difference by match <span class="card-sub">Oldest to newest; colour by kind of competition.</span></div><div id="cl-xgd" style="height:300px"></div></div></div>';
  html += '<div class="card"><div class="card-header">Matches <span class="card-sub">Every competition in the filter; results with xG, fixtures with the model\'s line.</span></div><div id="cl-matches"></div></div>';
  const homeName = (doc.names || {})[doc.home] || doc.name;
  const cmpSlug = q.c && (doc.names || {})[q.c] ? q.c : doc.home;
  html += '<div class="card"><div class="muted">' + (cmpSlug ? '<a href="#/compare/clubs/' + esc(cmpSlug) + ':' + esc(FH.slugify((doc.names || {})[cmpSlug] || homeName)) + '">Compare this ' + (doc.national ? 'team' : 'club') + ' →</a> &nbsp;·&nbsp; ' : '') +
    '<a href="' + (doc.national ? '#/nations' : '#/clubs') + '">' + (doc.national ? 'National teams' : 'Clubs across leagues') + ' →</a></div></div>';
  setHTML('club-body', html);

  // Seasons table.
  const srows = ss.slice().sort((x, y) => eraKey(y.era) - eraKey(x.era) || (KIND_ORDER[x.kind] - KIND_ORDER[y.kind]));
  setHTML('cl-seasons', srows.length ? tableHTML([
    { label: 'Season' }, { label: 'Competition' }, { label: 'Finish', align: 'right', title: 'League or group position, or how far it went' }, { label: 'P', align: 'right' }, { label: 'W-D-L', align: 'right', sortable: false },
    { label: 'GD', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Model', align: 'right', title: 'Attack / defence from the fit, current seasons only' }
  ], srows.map(s0 => {
    // Archive rows can carry zeros for what the archive does not know (played, W-D-L, goals): show them as unknown.
    const s = (!s0.played && s0.source !== 'live') ? Object.assign({}, s0, { played: null, w: null, d: null, l: null, gf: null, ga: null }) : s0;
    const href = seasonHref(s.comp, s.sid);
    // A cup's points are its group or league phase's; its record counts every round. Points sit beside
    // the record only where the two agree (a league, a qualifying group), otherwise they go with the
    // table position in "Finish".
    const isLeague = s.kind === 'league';
    const agrees = has(s.pts) && has(s.w) && s.pts === 3 * s.w + s.d;
    const inPhase = !s.stage || ['league', 'group', 'qualifying'].indexOf(s.stage) >= 0;
    const stage = s.stage && !inPhase ? (FH.ROUND_LABELS[s.stage] || s.stage) : '';
    const grp = s.group ? String(s.group).replace(/^.*,\s*/, '') : '';
    let finish;
    if (isLeague) {
      finish = has(s.pos) ? ordinal(s.pos) + (grp ? ' · ' + grp : '') : '';
      if (stage) finish = (finish ? finish + ' · ' : '') + stage;
      else if (s.pos === 1 && !grp && s.source !== 'live') finish += ' · champions';
    } else {
      // Friendlies have no standing; a continental cup's single table is its league phase.
      const table = has(s.pos) && s.comp !== 'friendlies' ? ordinal(s.pos) + (grp ? ' in ' + (/^[A-Z]\d?$/.test(grp) ? 'group ' + grp : grp) : (s.kind === 'continental_club' ? ' in the league phase' : '')) +
        (has(s.pts) && !agrees ? ', ' + s.pts + ' pts' : '') : '';
      finish = [stage, table].filter(Boolean).join(' · ');
      if (!finish && s.stage === 'qualifying') finish = 'Qualifying';
    }
    finish = finish || '—';
    const showPts = has(s.pts) && (isLeague || agrees) && s.comp !== 'friendlies';
    return { _href: href, cells: [
      { v: eraKey(s.era), html: esc(s.season || s.era || '') + (s.source === 'live' ? ' <span class="chip st-live">now</span>' : '') },
      { v: s.cname, html: esc(s.cname) + ' ' + kindChip(s.kind) + (s.group ? ' <span class="muted-inline">' + esc(String(s.group).replace(/^.*,\s*/, '')) + '</span>' : '') },
      { v: s.stage === 'winner' ? 0 : has(s.pos) ? s.pos : 99, html: s.stage === 'winner' ? '<strong>' + esc(finish) + '</strong>' : esc(finish), align: 'right' },
      { v: s.played || 0, html: has(s.played) ? s.played : '—', align: 'right' },
      { v: '', html: has(s.w) ? s.w + '-' + s.d + '-' + s.l : '—', align: 'right' },
      { v: has(s.gf) ? s.gf - s.ga : 0, html: has(s.gf) && has(s.ga) ? signed(s.gf - s.ga, 0) : '—', align: 'right' },
      { v: showPts ? s.pts : -1, html: showPts ? '<strong>' + s.pts + '</strong>' : '—', align: 'right' },
      { v: s.rating && has(s.rating.elo) ? s.rating.elo : 0, html: s.rating ? signed(s.rating.attack, 2) + ' / ' + signed(s.rating.defence, 2) : '—', align: 'right' }
    ] };
  }), { compact: true }) : '<div class="muted">No season matches the filter.</div>');
  sortableIn('cl-seasons');
  wireRowLinks('cl-seasons');

  // Year by year from the same rows (a row without a record, an archive table, leaves its season "partial").
  const yb = {};
  ss.forEach(s => {
    if (!s.era) return;
    const y = yb[s.era] || (yb[s.era] = { era: s.era, comps: 0, played: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0, partial: false, won: [] });
    y.comps += 1;
    if (!has(s.w) || (!s.played && s.source !== 'live')) { if (s.played) y.partial = true; return; }
    ['played', 'w', 'd', 'l', 'gf', 'ga'].forEach(k => { y[k] += Number(s[k]) || 0; });
    if (s.stage === 'winner') y.won.push(compShort(s.comp));
    if (s.coverage === 'partial' || s.coverage === 'none') y.lineups = true;
  });
  const ylist = Object.keys(yb).map(k => yb[k]).sort((x, y) => eraKey(y.era) - eraKey(x.era));
  setHTML('cl-years', ylist.length ? tableHTML([
    { label: 'Season' }, { label: 'Competitions', align: 'right' }, { label: 'P', align: 'right' }, { label: 'W-D-L', align: 'right', sortable: false },
    { label: 'GF', align: 'right' }, { label: 'GA', align: 'right' }, { label: 'PPG', align: 'right' }, { label: 'Won' }, { label: 'Data', align: 'center' }
  ], ylist.map(y => ({ cells: [
    { v: eraKey(y.era), html: '<strong>' + esc(y.era) + '</strong>' }, { v: y.comps, align: 'right' }, { v: y.played, align: 'right' },
    { v: '', html: y.played ? y.w + '-' + y.d + '-' + y.l : '—', align: 'right' }, { v: y.gf, align: 'right' }, { v: y.ga, align: 'right' },
    { v: y.played ? (3 * y.w + y.d) / y.played : 0, html: y.played ? num((3 * y.w + y.d) / y.played, 2) : '—', align: 'right' },
    { v: y.won.join(', '), html: esc(y.won.join(', ')) },
    { v: y.partial ? 0 : 1, html: y.partial ? '<span class="chip warn" title="An archive table without a record is not in the sums">partial</span>' : y.lineups ? '<span class="chip" title="Results complete; some matches lack player line-ups">results</span>' : '<span class="chip">complete</span>', align: 'center' }
  ] })), { compact: true }) : '<div class="muted">No season matches the filter.</div>');
  sortableIn('cl-years');

  // Squad: the current roster, never filtered by season (it is today's squad).
  const sq = (doc.squad || {}).players || [];
  const src = (doc.squad || {}).source;
  setHTML('cl-squad-sub', sq.length ? sq.length + ' players · ' + (src === 'roster' ? 'Sofascore\'s current squad list' : doc.national ? 'who played in its latest international window' : 'from appearances (no squad list fetched yet)') +
    ((doc.squad || {}).as_of ? ', as of ' + esc(fmtDate(doc.squad.as_of, true)) : '') : '');
  const flag = p => {
    const ix = people[String(p.id)] || {};
    if (doc.national) return ix.club_tid ? clubA(ix.club, ix.club_tid) : (ix.club ? esc(ix.club) : '');
    return ix.nt_tid ? '<a class="chip nt-chip" href="' + esc(clubHref(ix.nt_tid)) + '" title="Plays for ' + esc(ix.nt) + '">' + esc(ix.nt) + '</a>' : '';
  };
  setHTML('cl-squad', sq.length ? ['G', 'D', 'M', 'F', '?'].map(pos => {
    const g = sq.filter(p => (p.pos || '?') === pos || (pos === '?' && ['G', 'D', 'M', 'F'].indexOf(p.pos) < 0));
    if (!g.length) return '';
    return '<div class="squad-pos-head">' + esc(POS_GROUP[pos] || 'Position not recorded') + ' · ' + g.length + '</div>' + tableHTML([
      { label: '#', align: 'right' }, { label: 'Player' }, { label: 'Age', align: 'right' }, { label: 'Nat', align: 'center' }, { label: doc.national ? 'Club' : 'International' },
      { label: 'Apps', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'Rating', align: 'right' },
      { label: 'Value', align: 'right', title: 'Sofascore market value, reference only' }, { label: 'Contract', align: 'right', title: 'Contract end, Sofascore' }
    ], g.map(p => ({ cells: [
      { v: Number(p.shirt) || 999, html: p.shirt && !doc.national ? esc(p.shirt) : '', align: 'right' },
      { v: p.name, html: '<a class="player-link" href="' + esc(personHref(p.id)) + '">' + esc(p.name) + '</a> ' + posBadge(p.pos) +
        (src !== 'roster' && !doc.national && !p.apps ? ' <span class="muted-inline" title="Listed from his latest club appearance; no appearance for the club this season">not played this season</span>' : '') },
      { v: p.age || 0, html: p.age || '—', align: 'right' }, { v: p.nat || '', html: esc(p.nat || ''), align: 'center' }, { v: '', html: flag(p) },
      { v: p.apps || 0, align: 'right' }, { v: p.min || 0, align: 'right' }, { v: p.g || 0, align: 'right' }, { v: p.a || 0, align: 'right' },
      { v: p.rt || 0, html: has(p.rt) && p.rt ? num(p.rt, 2) : '—', align: 'right' },
      { v: p.mv || 0, html: p.mv ? esc(moneyShort(p.mv, p.mvc)) : '—', align: 'right' },
      { v: p.until || '', html: p.until ? esc(String(p.until).slice(0, 7)) : '—', align: 'right' }
    ] })), { compact: true });
  }).join('') : '<div class="muted">No squad on record yet.</div>');
  document.querySelectorAll('#cl-squad table').forEach(t => FH.makeSortable(t));

  // Matches.
  const isNext = m => m.status === 'scheduled' || m.status === 'live';
  const upcoming = ms.filter(isNext).sort((x, y) => String(x.date || '').localeCompare(String(y.date || '')));
  const NEXT = 6;
  const ordered = upcoming.slice(0, NEXT).concat(ms.filter(m => !isNext(m)));
  const hidden = Math.max(0, upcoming.length - NEXT);
  setHTML('cl-matches', ms.length ? (hidden ? '<div class="muted-inline pad">The next ' + NEXT + ' fixtures, then the results, newest first; ' + hidden + ' later fixtures are on each competition\'s Fixtures tab.</div>' : '') + tableHTML([
    { label: 'Date' }, { label: 'Competition' }, { label: 'Opponent' }, { label: 'H/A', align: 'center' }, { label: 'Result', align: 'center' }, { label: 'xG', align: 'center', sortable: false },
    { label: 'Model', align: 'center', sortable: false }, { label: '', sortable: false }
  ], ordered.slice(0, 120).map(m => {
    const fin = m.status === 'finished';
    const href = m.detail ? FH.matchHref(m.id, m.comp) : null;
    return { _href: href, cells: [
      { v: m.date || '', html: esc(fmtDate(m.date, true)) }, { v: compShort(m.comp), html: '<a href="' + esc(seasonHref(m.comp, m.sid) || '#/') + '">' + esc(compShort(m.comp)) + '</a>' },
      { v: m.opp || '', html: clubA(m.opp, m.opp_tid, m.comp) }, { v: m.home ? 'H' : 'A', align: 'center' },
      { v: fin ? m.gf - m.ga : -99, html: fin ? '<span class="' + resultClass(m.gf, m.ga) + '">' + m.gf + ' – ' + m.ga + '</span>' : statusChip(m), align: 'center' },
      { v: '', html: m.xg ? '<span class="xg-line">' + num(m.xg[0], 2) + ' – ' + num(m.xg[1], 2) + '</span>' : '', align: 'center' },
      { v: '', html: isNext(m) && m.model ? probBar(m.model, { small: true }) : '', align: 'center' },   // the fixture's home / draw / away
      { v: '', html: href ? '<a href="' + esc(href) + '">Analysis →</a>' : '' }
    ] };
  }), { sticky: true }) : '<div class="muted">No match matches the filter.</div>');
  wireRowLinks('cl-matches');
  sortableIn('cl-matches');

  clubCharts(seasons.filter(keep), done);
  if (!doc.national && FH.renderClubNeeds) FH.renderClubNeeds(document.getElementById('cl-needs'), doc.id);

  // The competition dossier: the model, analytics and players in a live competition.
  const c = q.c ? compOf(q.c) : null;
  const live = c ? seasons.find(s => s.comp === c.slug && s.source === 'live') : null;
  if (c && c.ok && live && (!q.e || q.e === live.era)) {
    setHTML('cl-dossier', '<div class="dossier-head"><h3>' + esc(c.name) + ' ' + esc(currentSeason(c).season || '') + '</h3><span class="muted-inline">The model, the season profile and the analytics in this competition.</span> <a href="#/' + esc(c.slug) + '/">' + esc(c.short_name || c.name) + ' →</a></div><div id="cl-dossier-body"><div class="muted">Loading…</div></div>');
    ensureComp(c.slug, (FH.PAGE_NEEDS || {}).team || ['teams']).then(() => {
      if (token !== CLUB_TOKEN || !document.getElementById('cl-dossier-body')) return;
      const n = (doc.names || {})[c.slug] || nameIn(c.slug, doc.id) || doc.name;
      withComp(c.slug, () => FH.renderClubDossier(document.getElementById('cl-dossier-body'), n));
    });
  }
}

function clubCharts(ss, done) {
  const groups = {};
  done.forEach(m => { const k = m.era + '|' + m.comp; (groups[k] = groups[k] || { era: m.era, comp: m.comp, kind: m.kind, rows: [] }).rows.push(m); });
  const eras = Array.from(new Set(done.map(m => m.era))).sort((a, b) => eraKey(a) - eraKey(b));
  const compsList = Array.from(new Set(done.map(m => m.comp)));
  if (eras.length) {
    plot('cl-ppg', compsList.map((s, i) => ({ type: 'bar', name: compShort(s), x: eras, y: eras.map(e => { const g = groups[e + '|' + s]; return g ? g.rows.reduce((t, m) => t + (m.gf > m.ga ? 3 : m.gf === m.ga ? 1 : 0), 0) / g.rows.length : null; }),
      marker: { color: PALETTE[i % PALETTE.length] }, customdata: eras.map(e => { const g = groups[e + '|' + s]; return g ? g.rows.length + ' matches' : ''; }),
      hovertemplate: '%{x} · ' + compShort(s) + ': %{y:.2f} PPG (%{customdata})<extra></extra>' })),
      layout({ barmode: 'group', showlegend: true, legend: { orientation: 'h', y: 1.16, font: { color: C.text2 } }, margin: { l: 40, r: 15, t: 30, b: 40 }, xaxis: { type: 'category' }, yaxis: { range: [0, 3.05], title: 'Points per game' } }));
  } else setHTML('cl-ppg', '<div class="muted">No finished match in the filter.</div>');
  const xs = done.filter(m => m.xg).slice().reverse();
  if (xs.length >= 2) {
    plot('cl-xgd', [{ type: 'bar', x: xs.map((m, i) => i + 1), y: xs.map(m => m.xg[0] - m.xg[1]), marker: { color: xs.map(m => KIND_COLOR[m.kind] || C.text3) },
      text: xs.map(m => fmtDate(m.date, true) + ' · ' + compShort(m.comp) + ' · ' + (m.home ? 'v ' : '@ ') + m.opp + ' ' + m.gf + '-' + m.ga), textposition: 'none',
      hovertemplate: '%{text}<br>xG difference %{y:+.2f}<extra></extra>' }],
      layout({ margin: { l: 40, r: 15, t: 10, b: 35 }, xaxis: { title: 'Match' }, yaxis: { title: 'xG for − against', zeroline: true } }));
  } else setHTML('cl-xgd', '<div class="muted">Not enough matches with xG in the filter.</div>');
}

Object.assign(FH.GLOBAL_PAGES, { person: renderPerson, club: renderClub });
})(window.FH);
