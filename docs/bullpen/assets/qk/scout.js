/* The Quant — the Scouting Room and team-comparison kit (round 8, 28 Oct 2026). Spec: STYLE_GUIDE.md §5 ("Scouting
 * Room"); how a site switches: MIGRATION_V4.md ("Round 8"). Load after quant.js and quant-charts.js:
 *   <script src="assets/qk/scout.js" defer></script>
 * A page that does not load it is unaffected. Pilot: The Quant Bullpen (bp-scout.js: #/<L>/scout, bp-teams.js:
 * #/<L>/teams). The nav switch lives in quant.js: QK.sections(sport, { scout: true }) turns "Players" into
 * "Scouting Room" (#/scout) and hides "Lab".
 *
 * Builders return HTML strings unless noted "(renders)". Older-browser rule: no optional chaining, no nullish coalescing.
 *
 *   QK.pctRank(sorted, v)                  percentile 0-100 of v among ascending values (mid-rank of ties)
 *   QK.csv(cols, rows) / QK.download(name, text, type)    CSV text (RFC 4180, a BOM for spreadsheets) and a file download
 *   QK.board(el, spec) (renders)           the Board: column-set chips, "Add a metric", a percentile table with a sticky
 *        name column, paging (top N, "Show all"), sortable heads, pin buttons and "Download CSV" of what is on screen.
 *        spec: { id, sets: [{ key, label, groups: [{ label, ids }] }], set, meta(id) -> { label, tip, ours: { name, about }
 *        | null, lower, style, fmt(v) }, addable: '<optgroup>' HTML (or [{ value, label }]), added: [ids],
 *        lead: [{ key, label, tip, fmt(row) -> text, val(row) -> number }], rows: [{ id, name, sub, mark: { abbr, colour },
 *        href }], val(row, id) -> number | null, peers: rows the percentiles are taken over (default rows),
 *        ranked(row, id) -> false keeps a cell uncoloured (a metric not ranked for that row), sort: { key, dir }, page (50),
 *        all, hl(row) -> bool, pin: { has(id), toggle(row), label }, onPick(row) (a click on a name; modified clicks follow
 *        the link), onState({ set, added, sort, all }), csv: file name, noun ('players'), note (HTML under the table),
 *        unit (the noun of the sort line) } -> { draw(), state(), setRows(rows, peers) }
 *   QK.heatGrid(el, spec) (renders)        the team heat grid: the same spec (sets are the phase groups), every row shown,
 *        each cell filled on the percentile scale with the value (or the percentile, "Values | Percentiles"), sticky
 *        club column, rows linked (row.href), CSV. -> the same handle
 *   QK.powerBars(rows, o)                  the power board: ranked rows, each a bar split into parts around zero (o.parts:
 *        [{ key, label, color }]; row.parts: { key: v }) with the total as a volt tick and big number, the record line,
 *        cells ({ label, html }), form squares (the last o.formN, default 10) and quiet chances. rows: [{ rank, name,
 *        abbr, colour, href, sub, value, text, parts, cells, form, chances: [{ label, p | text }] }]; o: { max, groups:
 *        [{ label, rows }] (instead of rows), unit, valueLabel, formLabel, formN, key: false }
 *   QK.leaderCard(o)                       a small multiple: o.title (+ o.ours tag, o.tip), the top five as bars, the
 *        bottom three ("where useful"), and a slot for QKC.strip (o.stripId). Items: { id, name, sub, href, text, w (bar
 *        0-100), mark: { abbr, colour } }; o.count ('of 213'), o.foot (HTML)
 *   QKC.strip(el, spec) (renders)          the distribution strip: every value of the group as a dot on one axis (a
 *        beeswarm in bins), coloured on the percentile scale, the median as a dashed line and the highlighted players
 *        ringed and named. spec: { values: [{ v, name, id, href, hl }], xName (axis title), fmt, lower (better to the
 *        right: the axis flips), median, onClick(point), label }
 *   QK.drawer.open({ html, label, onClose, cls }) -> the inner element (renders) · close() · isOpen() · body()
 *        a right-hand panel (a bottom sheet on phones) with a close button, Esc and a backdrop; one at a time
 *   QK.profile(o)                          the drawer's profile: o: { kicker, name, sub, team: { abbr, colour, alt },
 *        stats: [{ label, value, pctl }], peer, groups: [{ label, rows (QK.pctlBars rows) }], similar: { label, items:
 *        [{ name, href, sub, id }] }, links: [{ label, href, primary }], actions (HTML), note }
 *   QK.tray(o) (renders)                   the compare tray, fixed at the foot of the page: o: { max (4), ids, item(id) ->
 *        { name, sub, colour }, body(ids) -> HTML (QK.trayCompare), href(ids) -> the full Compare page | null,
 *        hrefLabel, onChange(ids), label } -> { add, remove, toggle, has, ids, open, close, clear, refresh, destroy }
 *   QK.trayCompare(o)                      2-4 entities side by side on percentile bars: o: { entities: [{ name, sub,
 *        colour, href }], groups: [{ label, rows: [{ label, tip, ours, cells: [{ text, pctl }] }] }], note }
 *   QK.strengths(o)                        a club card: o: { name, abbr, colour, href, sub, best: [{ label, pctl, text }],
 *        worst: [...] } (three each)
 *   QK.scoutBar(items, o)                  the one control bar: items [{ label, html, cls }] as labelled fields */
(function (root) {
'use strict';

var QK = root.QK;
if (!QK) return;
var esc = QK.esc, isNum = QK.isNum;

/* ─────────────────────────────────────── percentiles, CSV */
QK.pctRank = function (sorted, v) {
  if (!sorted || !sorted.length || !isNum(v)) return null;
  var lo = 0, hi = sorted.length;
  while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; }
  var up = lo;
  while (up < sorted.length && sorted[up] === v) up++;
  return 100 * ((lo + up) / 2) / sorted.length;
};
function csvCell(x) {
  var s = x === undefined || x === null ? '' : String(x);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
QK.csv = function (cols, rows) {
  return [cols.map(csvCell).join(',')].concat((rows || []).map(function (r) { return r.map(csvCell).join(','); })).join('\r\n') + '\r\n';
};
QK.download = function (name, text, type) {
  try {
    var blob = new Blob([type && type !== 'text/csv' ? '' : '﻿', text], { type: (type || 'text/csv') + ';charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name || 'download.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    return true;
  } catch (e) { return false; }
};
function plain(html) { return String(html === undefined || html === null ? '' : html).replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").trim(); }

/* ─────────────────────────────────────── the Board and the heat grid */
function setIds(set) {
  var out = [];
  ((set && set.groups) || []).forEach(function (g) { (g.ids || []).forEach(function (id) { if (out.indexOf(id) < 0) out.push(id); }); });
  return out;
}
function boardCore(el, spec, grid) {
  if (typeof el === 'string') el = document.querySelector(el);
  if (!el) return null;
  var S = spec, pre = S.id || (grid ? 'qk-hg' : 'qk-bd');
  var st = { set: S.set || ((S.sets || [])[0] || {}).key, added: (S.added || []).slice(), sort: S.sort || null, all: !!S.all, show: S.show || 'value' };
  var rows = S.rows || [], peers = S.peers || null;
  var meta = function (id) { var m = S.meta ? S.meta(id) : null; return m || { label: id }; };
  var val = function (r, id) { var v = S.val ? S.val(r, id) : (r.vals || {})[id]; return isNum(v) ? v : null; };
  function curSet() { return (S.sets || []).filter(function (x) { return x.key === st.set; })[0] || (S.sets || [])[0] || { key: '', groups: [] }; }
  function columns() {
    var set = curSet(), groups = (set.groups || []).map(function (g) { return { label: g.label || '', ids: (g.ids || []).slice() }; });
    var have = setIds(set), extra = st.added.filter(function (id) { return have.indexOf(id) < 0; });
    if (extra.length) groups.push({ label: 'Added', ids: extra, added: true });
    return groups.filter(function (g) { return g.ids.length; });
  }
  function pctFns(ids) {
    var P = peers || rows, out = {};
    ids.forEach(function (id) {
      var m = meta(id);
      var srt = P.filter(function (r) { return !S.ranked || S.ranked(r, id) !== false; }).map(function (r) { return val(r, id); }).filter(isNum).sort(function (a, b) { return a - b; });
      out[id] = function (r) {
        var v = val(r, id);
        if (!isNum(v) || srt.length < 3 || (S.ranked && S.ranked(r, id) === false)) return null;
        var p = QK.pctRank(srt, v);
        return m.lower ? 100 - p : p;
      };
    });
    return out;
  }
  function fmtv(id, v) { var m = meta(id); return !isNum(v) ? '—' : (m.fmt ? m.fmt(v) : QK.fmt.num(v, Math.abs(v) < 10 && v % 1 ? 2 : 0)); }
  function sortVal(r, key) {
    var ld = (S.lead || []).filter(function (c) { return c.key === key; })[0];
    if (key === 'name') return r.name;
    if (ld) return ld.val ? ld.val(r) : null;
    return val(r, key);
  }
  function sorted(list) {
    if (!st.sort || !st.sort.key) return list.slice();
    var k = st.sort.key, d = st.sort.dir === 'asc' ? 1 : -1;
    return list.map(function (r, i) { return { r: r, v: sortVal(r, k), i: i }; }).sort(function (a, b) {
      var x = a.v, y = b.v;
      if (x === y) return a.i - b.i;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * d;
    }).map(function (o) { return o.r; });
  }
  function headLabel(id) {
    var m = meta(id);
    return '<span' + (m.tip ? ' data-tip="' + esc(m.tip) + '"' : '') + '>' + esc(m.short || m.label) + (m.lower ? ' ↓' : '') + '</span>' +
      (m.ours ? QK.ours({ short: true, model: m.ours.name, about: m.ours.about }) : '');
  }
  function sortLabel() {
    if (!st.sort || !st.sort.key) return '';
    var k = st.sort.key, ld = (S.lead || []).filter(function (c) { return c.key === k; })[0];
    var lab = k === 'name' ? 'name' : ld ? ld.label : meta(k).label;
    return ' · sorted by ' + esc(lab) + (st.sort.dir === 'asc' ? ' (lowest first)' : ' (highest first)');
  }
  var shown = [], shownCols = [];
  function draw() {
    var groups = columns(), ids = [];
    groups.forEach(function (g) { g.ids.forEach(function (id) { if (ids.indexOf(id) < 0) ids.push(id); }); });
    var P = pctFns(ids);
    var list = sorted(rows), total = list.length, page = S.page || 50;
    shown = grid || st.all ? list : list.slice(0, page);
    shownCols = ids;
    var lead = S.lead || [];
    var chips = (S.sets || []).map(function (x) {
      return '<button type="button" class="qk-chip" data-set="' + esc(x.key) + '" aria-pressed="' + (x.key === st.set ? 'true' : 'false') + '">' + esc(x.label) + '</button>';
    }).join('');
    var addOpts = typeof S.addable === 'string' ? S.addable : (S.addable || []).map(function (o) { return '<option value="' + esc(o.value) + '">' + esc(o.label) + '</option>'; }).join('');
    var bar = '<div class="qk-bd-bar"><div class="qk-bd-sets"><span class="qk-within-l">' + esc(S.setsLabel || 'Columns') + '</span><div class="qk-chips scroll" role="group" aria-label="Column sets">' + chips + '</div></div>' +
      '<div class="qk-bd-tools">' + (addOpts ? '<label class="qk-bd-add"><span class="qk-within-l">Add a metric</span><select class="qk-select" id="' + esc(pre) + '-add"><option value="">Any metric…</option>' + addOpts + '</select></label>' : '') +
      (grid ? '<div class="qk-seg" id="' + esc(pre) + '-show" role="group" aria-label="Cells show"><button type="button" data-value="value" aria-pressed="' + (st.show === 'value') + '">Values</button><button type="button" data-value="pct" aria-pressed="' + (st.show === 'pct') + '">Percentiles</button></div>' : '') +
      '<button type="button" class="qk-btn sm" data-act="csv">Download CSV</button></div></div>';
    var added = st.added.length ? '<div class="qk-bd-added"><span class="qk-within-l">Added</span>' + st.added.map(function (id) {
      return '<button type="button" class="qk-chip" data-rm="' + esc(id) + '" aria-label="Remove ' + esc(meta(id).label) + '">' + esc(meta(id).label) + ' <span aria-hidden="true">×</span></button>';
    }).join('') + '<button type="button" class="qk-chip" data-rm="*">Clear</button></div>' : '';
    var noun = S.noun || 'rows';
    var metaLine = '<div class="qk-bd-meta">' + (grid || shown.length === total ? esc(total + ' ' + noun) : 'Top ' + shown.length + ' of ' + total + ' ' + esc(noun)) + sortLabel() + '</div>';
    var hasGroups = groups.length > 1 || (groups[0] && groups[0].label);
    var aria = function (k) { return st.sort && st.sort.key === k ? (st.sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'; };
    var th = function (k, html, cls) { return '<th scope="col" class="' + (cls || 'num') + '" aria-sort="' + aria(k) + '" data-k="' + esc(k) + '"><button type="button">' + html + '</button></th>'; };
    var thead = (hasGroups ? '<tr class="qk-bd-grp"><th class="sticky-col" scope="colgroup"></th>' + (lead.length ? '<th colspan="' + lead.length + '"></th>' : '') +
      groups.map(function (g) { return '<th scope="colgroup" colspan="' + g.ids.length + '"><span>' + esc(g.label) + '</span></th>'; }).join('') + '</tr>' : '') +
      '<tr>' + th('name', esc(S.nameLabel || 'Name'), 'sticky-col') + lead.map(function (c) { return th(c.key, c.tip ? '<span data-tip="' + esc(c.tip) + '">' + esc(c.label) + '</span>' : esc(c.label)); }).join('') +
      groups.map(function (g, gi) { return g.ids.map(function (id, j) { return th(id, headLabel(id), 'num' + (j === 0 && gi > 0 ? ' gs' : '')); }).join(''); }).join('') + '</tr>';
    var tbody = shown.map(function (r, i) {
      var pin = S.pin ? '<button type="button" class="qk-pin" data-pin="' + esc(r.id) + '" aria-pressed="' + (S.pin.has(r.id) ? 'true' : 'false') + '" title="' + esc(S.pin.label || 'Pin to the compare tray') + '" aria-label="' + esc((S.pin.label || 'Pin to the compare tray') + ': ' + r.name) + '">' + (S.pin.has(r.id) ? '✓' : '+') + '</button>' : '';
      var mark = r.mark ? QK.teamMark(r.mark, 'sm') : '';
      var name = '<div class="qk-bd-in"><span class="qk-bd-rk num">' + (i + 1) + '</span>' + mark + '<span class="qk-bd-nm"><a class="qk-bd-a" href="' + esc(r.href || '#') + '"' + (S.onPick ? ' data-pick="' + esc(r.id) + '"' : '') + '>' + esc(r.name) + '</a>' +
        (r.sub ? '<small>' + esc(r.sub) + '</small>' : '') + '</span>' + pin + '</div>';
      var cells = lead.map(function (c) { return '<td class="num qk-bd-lead">' + esc(c.fmt ? c.fmt(r) : '') + '</td>'; }).join('');
      groups.forEach(function (g, gi) {
        g.ids.forEach(function (id, j) {
          var v = val(r, id), p = P[id](r), m = meta(id), t = fmtv(id, v), gs = j === 0 && gi > 0 ? ' gs' : '';
          if (!isNum(p)) { cells += '<td class="num qk-bd-c' + gs + '">' + esc(t) + '</td>'; return; }
          var tip = QK.ordinal(Math.round(p)) + ' percentile' + (m.style ? ' (style: neither better nor worse)' : '');
          var bg = m.style ? 'var(--s-3)' : QK.pctColor(p), ink = m.style ? 'var(--ink-1)' : QK.pctInk(p);
          if (grid) cells += '<td class="num qk-hg-c' + gs + '" style="background:' + bg + ';color:' + ink + '" title="' + esc(m.label + ': ' + t + ', ' + tip) + '">' + esc(st.show === 'pct' ? String(Math.round(p)) : t) + '</td>';
          else cells += '<td class="num qk-bd-c' + gs + '"><span class="qk-pcell" style="background:' + bg + ';color:' + ink + '" title="' + esc(tip) + '">' + esc(t) + '</span></td>';
        });
      });
      return '<tr' + (S.hl && S.hl(r) ? ' class="hl"' : '') + (grid && r.href ? ' data-href="' + esc(r.href) + '"' : '') + '><th scope="row" class="sticky-col qk-bd-name">' + name + '</th>' + cells + '</tr>';
    }).join('');
    var table = '<div class="qk-table-wrap qk-bd-wrap"' + (S.maxHeight ? ' style="--table-max:' + S.maxHeight + 'px"' : '') + '><table class="qk-table dense ' + (grid ? 'qk-hg-t' : 'qk-bd-t') + '">' +
      (S.caption ? '<caption class="qk-sr">' + esc(S.caption) + '</caption>' : '') + '<thead>' + thead + '</thead><tbody>' +
      (tbody || '<tr><td colspan="' + (1 + lead.length + ids.length) + '">' + QK.empty('No rows', S.empty || 'Nothing matches the current filters.') + '</td></tr>') + '</tbody></table></div>';
    var foot = '<div class="qk-bd-foot">' + (!grid && total > (S.page || 50) ? '<button type="button" class="qk-btn sm" data-act="all">' + (st.all ? 'Show the top ' + (S.page || 50) : 'Show all ' + total) + '</button>' : '') +
      (S.note ? '<div class="qk-bd-note">' + S.note + '</div>' : '') + '</div>';
    el.innerHTML = '<div class="qk-bd' + (grid ? ' qk-hg' : '') + '">' + bar + added + metaLine + table + foot + '</div>';
    wire();
    if (S.onState) S.onState({ set: st.set, added: st.added.slice(), sort: st.sort, all: st.all, show: st.show });
  }
  function wire() {
    QK.$$('[data-set]', el).forEach(function (b) { b.addEventListener('click', function () { st.set = b.getAttribute('data-set'); draw(); }); });
    QK.$$('[data-rm]', el).forEach(function (b) {
      b.addEventListener('click', function () { var id = b.getAttribute('data-rm'); st.added = id === '*' ? [] : st.added.filter(function (x) { return x !== id; }); draw(); });
    });
    var add = document.getElementById(pre + '-add');
    if (add) add.addEventListener('change', function () {
      var id = add.value;
      if (id && st.added.indexOf(id) < 0) st.added.push(id);
      if (id) st.sort = { key: id, dir: meta(id).lower ? 'asc' : 'desc' };
      draw();
    });
    var show = document.getElementById(pre + '-show');
    if (show) QK.seg(show, function (v) { st.show = v === 'pct' ? 'pct' : 'value'; draw(); });
    QK.$$('th[aria-sort] button', el).forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.parentNode.getAttribute('data-k');
        var low = k !== 'name' && !!meta(k).lower && !(S.lead || []).some(function (c) { return c.key === k; });
        var first = k === 'name' ? 'asc' : low ? 'asc' : 'desc';
        st.sort = st.sort && st.sort.key === k ? { key: k, dir: st.sort.dir === 'asc' ? 'desc' : 'asc' } : { key: k, dir: first };
        draw();
        var nb = el.querySelector('th[data-k="' + k + '"] button'); if (nb) nb.focus();
      });
    });
    QK.$$('[data-act="all"]', el).forEach(function (b) { b.addEventListener('click', function () { st.all = !st.all; draw(); }); });
    QK.$$('[data-act="csv"]', el).forEach(function (b) { b.addEventListener('click', function () { QK.download(S.csv || 'table.csv', csvText()); }); });
    QK.$$('[data-pin]', el).forEach(function (b) {
      b.addEventListener('click', function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        var id = b.getAttribute('data-pin'), r = rows.filter(function (x) { return String(x.id) === id; })[0];
        if (r && S.pin) { S.pin.toggle(r); var on = S.pin.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; }
      });
    });
    if (S.onPick) QK.$$('[data-pick]', el).forEach(function (a) {
      a.addEventListener('click', function (ev) {
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
        var id = a.getAttribute('data-pick'), r = rows.filter(function (x) { return String(x.id) === id; })[0];
        if (r) { ev.preventDefault(); S.onPick(r); }
      });
    });
    if (grid) QK.$$('tr[data-href]', el).forEach(function (tr) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function (ev) { if (ev.target.closest('a, button, input, select')) return; root.location.href = tr.getAttribute('data-href'); });
    });
    if (QK.tooltips) QK.tooltips();
  }
  /* exactly what is on screen: the rows shown (the top N, or all), the columns shown, the values as written */
  function csvText() {
    var lead = S.lead || [];
    var cols = ['Rank', S.nameLabel || 'Name', S.subLabel || 'Detail'].concat(lead.map(function (c) { return c.label; })).concat(shownCols.map(function (id) { return meta(id).label; }));
    var P = grid && st.show === 'pct' ? pctFns(shownCols) : null;
    var out = shown.map(function (r, i) {
      return [i + 1, r.name, r.sub || ''].concat(lead.map(function (c) { return c.fmt ? plain(c.fmt(r)) : ''; })).concat(shownCols.map(function (id) {
        if (P) { var p = P[id](r); return isNum(p) ? Math.round(p) : ''; }
        var v = val(r, id); return isNum(v) ? plain(fmtv(id, v)) : '';
      }));
    });
    return QK.csv(cols, out);
  }
  draw();
  return {
    draw: draw,
    state: function () { return { set: st.set, added: st.added.slice(), sort: st.sort, all: st.all, show: st.show }; },
    setRows: function (r, p) { rows = r || []; peers = p || null; draw(); },
    csv: csvText
  };
}
QK.board = function (el, spec) { return boardCore(el, spec, false); };
QK.heatGrid = function (el, spec) { return boardCore(el, spec, true); };

/* ─────────────────────────────────────── the power board */
QK.powerBars = function (rows, o) {
  o = o || {};
  var groups = o.groups || [{ label: '', rows: rows || [] }];
  var parts = o.parts || [];
  var all = [];
  groups.forEach(function (g) { (g.rows || []).forEach(function (r) { all.push(r); }); });
  var ext = function (r) {
    var pos = 0, neg = 0;
    parts.forEach(function (p) { var v = (r.parts || {})[p.key]; if (isNum(v)) { if (v > 0) pos += v; else neg += v; } });
    return Math.max(Math.abs(pos), Math.abs(neg), Math.abs(isNum(r.value) ? r.value : 0));
  };
  var max = isNum(o.max) && o.max > 0 ? o.max : Math.max.apply(null, all.map(ext).concat([0.5])) * 1.05;
  var pctX = function (v) { return 50 + 50 * Math.max(-1, Math.min(1, v / max)); };
  function bar(r) {
    var segs = '', posAt = 0, negAt = 0, aria = [];
    parts.forEach(function (p) {
      var v = (r.parts || {})[p.key];
      if (!isNum(v)) return;
      aria.push(p.label + ' ' + QK.fmt.signed(v, 2));
      var a, b;
      if (v >= 0) { a = pctX(posAt); posAt += v; b = pctX(posAt); }
      else { b = pctX(negAt); negAt += v; a = pctX(negAt); }
      segs += '<i style="left:' + a.toFixed(2) + '%;width:' + Math.max(0.4, b - a).toFixed(2) + '%;background:' + p.color + '" title="' + esc(p.label + ': ' + QK.fmt.signed(v, 2)) + '"></i>';
    });
    var tick = isNum(r.value) ? '<b class="qk-pw-tick" style="left:' + pctX(r.value).toFixed(2) + '%"></b>' : '';
    return '<div class="qk-pw-bar" role="img" aria-label="' + esc((o.valueLabel || 'Rating') + ' ' + (r.text || '') + (aria.length ? ': ' + aria.join(', ') : '')) + '"><span class="qk-pw-zero"></span>' + segs + tick + '</div>';
  }
  var key = o.key === false ? '' : '<div class="qk-pw-key">' + parts.map(function (p) { return '<span><i style="background:' + p.color + '"></i>' + esc(p.label) + '</span>'; }).join('') +
    '<span><b class="qk-pw-tick k"></b>' + esc(o.valueLabel || 'Rating') + (o.unit ? ' (' + esc(o.unit) + ')' : '') + '</span>' +
    '<span class="qk-pw-scale">Grey line = 0 · bar ends at ' + esc(QK.fmt.signed(-max, 1)) + ' and ' + esc(QK.fmt.signed(max, 1)) + '</span></div>';
  var body = groups.map(function (g) {
    var rs = (g.rows || []);
    if (!rs.length) return '';
    return (g.label ? '<div class="qk-pw-grp">' + esc(g.label) + '</div>' : '') + rs.map(function (r) {
      var nm = '<span class="qk-pw-nm' + QK.longName(r.name, 20) + '">' + esc(r.name) + '</span>';
      var team = (r.href ? '<a class="qk-pw-team" href="' + esc(r.href) + '">' : '<span class="qk-pw-team">') + QK.teamMark({ abbr: r.abbr, colour: r.colour, name: r.name }, 'sm') +
        '<span class="qk-pw-who">' + nm + (r.sub ? '<small>' + esc(r.sub) + '</small>' : '') + '</span>' + (r.href ? '</a>' : '</span>');
      var cells = (r.cells || []).map(function (c) { return '<span class="qk-pw-cell"><small>' + esc(c.label) + '</small>' + (c.html !== undefined ? c.html : esc(c.text)) + '</span>'; }).join('');
      var form = r.form ? '<span class="qk-pw-cell"><small>' + esc(o.formLabel || 'Last 10') + '</small>' + QK.formDots(r.form, o.formN || 10) + '</span>' : '';
      var ch = (r.chances || []).filter(function (c) { return isNum(c.p) || c.text; }).map(function (c) { return '<span class="qk-pw-ch">' + esc(c.label) + ' <b>' + esc(c.text || QK.fmt.pct(c.p)) + '</b></span>'; }).join('');
      return '<div class="qk-pw-row" role="listitem"><span class="qk-pw-rk qk-outline num" aria-hidden="true">' + esc(r.rank) + '</span>' + team +
        '<div class="qk-pw-mid">' + bar(r) + '</div><span class="qk-pw-v num">' + esc(r.text || '') + '</span>' +
        '<div class="qk-pw-cells">' + cells + form + (ch ? '<span class="qk-pw-chs">' + ch + '</span>' : '') + '</div></div>';
    }).join('');
  }).join('');
  return '<div class="qk-pw">' + key + '<div role="list">' + body + '</div></div>';
};

/* ─────────────────────────────────────── a leader small multiple */
QK.leaderCard = function (o) {
  o = o || {};
  function list(items, cls, start) {
    return '<ol class="qk-lc-list' + (cls ? ' ' + cls : '') + '"' + (start ? ' start="' + start + '"' : '') + '>' + (items || []).map(function (it, i) {
      var w = isNum(it.w) ? Math.max(3, Math.min(100, it.w)) : 0;
      return '<li><span class="qk-lc-rk num">' + esc(it.rank || (start ? start + i : i + 1)) + '</span>' + (it.mark ? QK.teamMark(it.mark, 'sm') : '') +
        '<span class="qk-lc-nm"><a href="' + esc(it.href || '#') + '"' + (it.id !== undefined ? ' data-pick="' + esc(it.id) + '"' : '') + '>' + esc(it.name) + '</a>' + (it.sub ? '<small>' + esc(it.sub) + '</small>' : '') + '</span>' +
        '<span class="qk-lc-bar" aria-hidden="true"><i style="width:' + w.toFixed(1) + '%;background:' + (isNum(it.pctl) ? QK.pctColor(it.pctl) : 'var(--signal)') + '"></i></span>' +
        '<span class="qk-lc-v num">' + esc(it.text) + '</span></li>';
    }).join('') + '</ol>';
  }
  var title = '<div class="qk-lc-t"><span' + (o.tip ? ' data-tip="' + esc(o.tip) + '" tabindex="0"' : '') + '>' + esc(o.title) + '</span>' + (o.ours ? QK.ours({ short: true, model: o.ours.name, about: o.ours.about }) : '') + '</div>';
  return '<section class="qk-card qk-lc"><div class="qk-lc-h">' + (o.kicker ? '<div class="qk-kicker">' + esc(o.kicker) + '</div>' : '') + title +
    (o.count ? '<div class="qk-lc-c">' + esc(o.count) + (o.lower ? ' · lower is better' : '') + '</div>' : '') + '</div>' +
    '<div class="qk-lc-b">' + list(o.top, '', 0) + (o.bottom && o.bottom.length ? '<div class="qk-lc-sub">' + esc(o.bottomLabel || 'At the bottom') + '</div>' + list(o.bottom, 'low', o.bottomStart || 0) : '') +
    (o.stripId ? '<div id="' + esc(o.stripId) + '" class="qk-chart qk-lc-strip" style="--h:' + (o.stripH || 104) + 'px"></div>' : '') + '</div>' +
    (o.foot ? '<div class="qk-lc-f">' + o.foot + '</div>' : '') + '</section>';
};

/* ─────────────────────────────────────── the distribution strip (QKC) */
function stripChart(el, s) {
  var QKC = root.QKC;
  if (!QKC) return null;
  var pts = (s.values || []).filter(function (p) { return p && isNum(p.v); });
  var srt = pts.map(function (p) { return p.v; }).sort(function (a, b) { return a - b; });
  var med = isNum(s.median) ? s.median : (srt.length ? (srt.length % 2 ? srt[(srt.length - 1) / 2] : (srt[srt.length / 2 - 1] + srt[srt.length / 2]) / 2) : null);
  var lo = srt.length ? srt[0] : 0, hi = srt.length ? srt[srt.length - 1] : 1, span = (hi - lo) || 1;
  /* a beeswarm in bins: 48 bins across, each point stacked out from the middle (0, +1, -1, +2 ...) */
  var bins = {}, maxK = 1;
  var order = pts.map(function (p, i) { return i; }).sort(function (a, b) { return pts[a].v - pts[b].v; });
  var ys = [];
  order.forEach(function (i) {
    var b = Math.round(47 * (pts[i].v - lo) / span), k = bins[b] || 0;
    bins[b] = k + 1;
    var y = k === 0 ? 0 : (k % 2 ? 1 : -1) * Math.ceil(k / 2);
    ys[i] = y;
    if (Math.abs(y) > maxK) maxK = Math.abs(y);
  });
  var f = s.fmt || function (v) { return QK.fmt.num(v, 2); };
  return QKC.mount(el, function (T) {
    var data = pts.map(function (p, i) {
      var pc = QK.pctRank(srt, p.v);
      if (s.lower) pc = 100 - pc;
      return { value: [p.v, ys[i] / (maxK + 0.5)], name: p.name, href: p.href, id: p.id, pc: pc,
        symbolSize: p.hl ? 13 : 6,
        itemStyle: { color: QK.pctHex(pc), opacity: p.hl ? 1 : 0.8, borderColor: p.hl ? T.ink1 : 'transparent', borderWidth: p.hl ? 2 : 0 },
        label: p.hl ? { show: true, formatter: QK.surname(p.name || ''), position: 'top', distance: 4, color: T.ink1, fontFamily: T.fontCond, fontWeight: 700, fontSize: 12 } : { show: false } };
    });
    var xa = QKC.axis(T, { type: 'value', scale: true, fmt: f, inverse: !!s.lower, line: true, split: false });
    QKC.nameAxis(xa, (s.xName || 'Value') + (s.lower ? ' (better to the right)' : ''), 'bottom');
    var ya = { type: 'value', show: false, min: -1.15, max: 1.15 };
    return {
      grid: { left: 10, right: 14, top: 20, bottom: 30, containLabel: true },
      xAxis: xa, yAxis: ya,
      tooltip: QKC.tooltip(T, { formatter: function (p) { if (p.componentType !== 'series') return ''; var d = data[p.dataIndex]; return '<div style="font-weight:700">' + esc(d.name || '') + '</div>' + QKC.tipRow(p.color, s.xName || 'Value', f(d.value[0])) + QKC.tipRow(p.color, 'Percentile', QK.ordinal(Math.round(d.pc))); } }),
      series: [{
        type: 'scatter', data: data, z: 3,
        emphasis: { scale: 1.5 },
        markLine: isNum(med) ? { silent: true, symbol: 'none', animation: false, lineStyle: { color: T.ink2, type: [4, 3], width: 1.2 },
          label: Object.assign(QKC.annot(T, { fontSize: 11.5 }), { show: true, formatter: 'Median ' + f(med), position: 'end', distance: 2 }), data: [{ xAxis: med }] } : undefined
      }]
    };
  }, { label: s.label || ('Distribution of ' + (s.xName || 'the metric')), onClick: s.onClick ? function (p) { if (p.componentType === 'series' && p.data) s.onClick(p.data); } : undefined });
}
if (root.QKC) root.QKC.strip = stripChart;
QK.strip = stripChart;

/* ─────────────────────────────────────── the profile drawer */
var DR = { bg: null, el: null, inner: null, onClose: null, last: null };
function drawerKey(ev) { if (ev.key === 'Escape' && DR.el) QK.drawer.close(); }
QK.drawer = {
  open: function (o) {
    o = o || {};
    if (!DR.el) {
      DR.bg = document.createElement('div'); DR.bg.className = 'qk-drawer-bg';
      DR.el = document.createElement('aside'); DR.el.className = 'qk-drawer'; DR.el.setAttribute('role', 'dialog'); DR.el.setAttribute('aria-modal', 'true');
      DR.el.innerHTML = '<button type="button" class="qk-drawer-x" aria-label="Close the profile">×</button><div class="qk-drawer-in"></div>';
      document.body.appendChild(DR.bg); document.body.appendChild(DR.el);
      DR.bg.addEventListener('click', function () { QK.drawer.close(); });
      DR.el.querySelector('.qk-drawer-x').addEventListener('click', function () { QK.drawer.close(); });
      document.addEventListener('keydown', drawerKey);
      DR.last = document.activeElement;
    } else if (DR.onClose && DR.onClose !== o.onClose) { /* replacing the content: the old owner is not told */ }
    DR.onClose = o.onClose || null;
    DR.el.className = 'qk-drawer' + (o.cls ? ' ' + o.cls : '');
    DR.el.setAttribute('aria-label', o.label || 'Profile');
    DR.inner = DR.el.querySelector('.qk-drawer-in');
    DR.inner.innerHTML = o.html || '';
    DR.inner.scrollTop = 0;
    document.documentElement.classList.add('qk-drawer-on');
    requestAnimationFrame(function () { if (DR.el) { DR.el.classList.add('on'); DR.bg.classList.add('on'); var x = DR.el.querySelector('.qk-drawer-x'); if (x) x.focus({ preventScroll: true }); } });
    if (QK.tooltips) QK.tooltips();
    return DR.inner;
  },
  close: function (silent) {
    if (!DR.el) return;
    var cb = DR.onClose;
    document.removeEventListener('keydown', drawerKey);
    DR.el.remove(); DR.bg.remove();
    document.documentElement.classList.remove('qk-drawer-on');
    var last = DR.last;
    DR.el = DR.bg = DR.inner = DR.onClose = DR.last = null;
    if (last && last.focus && last.isConnected) { try { last.focus({ preventScroll: true }); } catch (e) { /* gone */ } }
    if (cb && !silent) cb();
  },
  isOpen: function () { return !!DR.el; },
  body: function () { return DR.inner; }
};
QK.profile = function (o) {
  o = o || {};
  var t = o.team || {};
  var blk = QK.color.block(t.colour && QK.color.parse(t.colour) ? t.colour : null);
  var head = '<header class="qk-pf-h" style="--tb:' + esc(blk.bg) + (blk.edge ? ';--te:' + esc(blk.edge) : '') + '">' +
    (o.kicker ? '<span class="qk-pf-k">' + esc(o.kicker) + '</span>' : '') +
    '<h2 class="qk-pf-nm' + QK.longName(o.name, 18) + '">' + (o.href ? '<a href="' + esc(o.href) + '">' + esc(o.name) + '</a>' : esc(o.name)) + '</h2>' +
    (o.sub ? '<div class="qk-pf-sub">' + esc(o.sub) + '</div>' : '') + '</header>';
  var stats = (o.stats || []).length ? '<div class="qk-pf-nums">' + o.stats.map(function (s) {
    return '<div><b class="num">' + esc(s.value) + '</b><span' + (s.tip ? ' data-tip="' + esc(s.tip) + '"' : '') + '>' + esc(s.label) + '</span>' + (isNum(s.pctl) ? QK.pctlChip(s.pctl) : '') + '</div>';
  }).join('') + '</div>' : '';
  var acts = (o.actions || '') + (o.links || []).map(function (l) { return '<a class="qk-btn sm' + (l.primary ? ' primary' : '') + '" href="' + esc(l.href) + '">' + esc(l.label) + '</a>'; }).join('');
  var groups = (o.groups || []).filter(function (g) { return g && (g.rows || []).some(function (r) { return r && isNum(r.pctl); }); });
  var early = groups.some(function (g) { return g.rows.some(function (r) { return r && r.early; }); });
  var pct = groups.length ? '<div class="qk-pf-pct">' + (o.peer ? '<div class="qk-pcard-peer">' + QK.tag('Peers: ' + o.peer, 'signal') + '</div>' : '') +
    groups.map(function (g) { return '<div class="qk-pgrp"><div class="qk-pgrp-h">' + esc(g.label) + '</div>' + QK.pctlBars(g.rows) + '</div>'; }).join('') + QK.pctKey({}) +
    (early ? '<div class="qk-pnote">A dashed box marks a metric still short of the sample where it settles down: read it as early.</div>' : '') + '</div>'
    : QK.empty('No percentiles yet', o.emptyText || 'This player is short of the sample floor for the group on screen.');
  var sim = o.similar && o.similar.items && o.similar.items.length ? '<div class="qk-pf-sim"><div class="qk-pgrp-h">' + esc(o.similar.label || 'Most like') + '</div><div class="qk-chips">' +
    o.similar.items.map(function (x) { return '<a class="qk-chip" href="' + esc(x.href) + '"' + (x.id !== undefined ? ' data-pick="' + esc(x.id) + '"' : '') + (x.sub ? ' title="' + esc(x.sub) + '"' : '') + '>' + esc(x.name) + '</a>'; }).join('') + '</div></div>' : '';
  return '<div class="qk-pf">' + head + stats + (acts ? '<div class="qk-pf-acts">' + acts + '</div>' : '') + pct + sim + (o.note ? '<p class="qk-pnote">' + o.note + '</p>' : '') + '</div>';
};

/* ─────────────────────────────────────── the compare tray */
QK.tray = function (o) {
  o = o || {};
  var max = o.max || 4, ids = (o.ids || []).map(String).slice(0, max), open = false, el = null;
  function item(id) { return (o.item && o.item(id)) || { name: id }; }
  function changed() { if (o.onChange) o.onChange(ids.slice()); paint(); }
  function paint() {
    if (!ids.length) { if (el) { el.remove(); el = null; } document.documentElement.classList.remove('qk-tray-on'); document.documentElement.style.removeProperty('--qk-tray-h'); open = false; return; }
    if (!el) { el = document.createElement('section'); el.className = 'qk-tray'; el.setAttribute('aria-label', o.label || 'Compare tray'); document.body.appendChild(el); }
    document.documentElement.classList.add('qk-tray-on');
    var href = o.href ? o.href(ids) : null;
    var chips = ids.map(function (id) {
      var it = item(id), c = it.colour && QK.color.parse(it.colour) ? QK.color.team(it.colour) : 'var(--signal)';
      return '<span class="qk-tray-chip" style="--tc:' + esc(c) + '"><b>' + esc(it.short || QK.surname(it.name) || it.name) + '</b>' + (it.sub ? '<small>' + esc(it.sub) + '</small>' : '') +
        '<button type="button" data-rm="' + esc(id) + '" aria-label="Remove ' + esc(it.name) + ' from the tray">×</button></span>';
    }).join('');
    var body = open && ids.length >= 2 && o.body ? '<div class="qk-tray-panel" role="region" aria-label="Side by side">' + o.body(ids.slice()) + '</div>'
      : open ? '<div class="qk-tray-panel"><p class="qk-pnote">Pin one more player to compare side by side.</p></div>' : '';
    el.innerHTML = body + '<div class="qk-tray-bar"><span class="qk-tray-l">' + esc(o.label || 'Compare tray') + ' <b class="num">' + ids.length + '/' + max + '</b></span>' +
      '<div class="qk-tray-chips">' + chips + '</div><div class="qk-tray-acts">' +
      '<button type="button" class="qk-btn sm' + (open ? ' solid' : ' primary') + '" data-act="open" aria-expanded="' + open + '">' + (open ? 'Hide' : 'Side by side') + '</button>' +
      (href && ids.length >= 2 ? '<a class="qk-btn sm" href="' + esc(href) + '">' + esc(o.hrefLabel || 'Full compare') + '</a>' : '') +
      '<button type="button" class="qk-btn sm" data-act="clear">Clear</button></div></div>';
    QK.$$('[data-rm]', el).forEach(function (b) { b.addEventListener('click', function () { api.remove(b.getAttribute('data-rm')); }); });
    var ob = el.querySelector('[data-act="open"]'); if (ob) ob.addEventListener('click', function () { open = !open; paint(); });
    var cb = el.querySelector('[data-act="clear"]'); if (cb) cb.addEventListener('click', function () { api.clear(); });
    /* a site's fixed first-visit notice (.fv-notice) sits above the tray, never over it */
    document.documentElement.style.setProperty('--qk-tray-h', el.offsetHeight + 'px');
    if (o.onPaint) o.onPaint(el, open);
    if (QK.tooltips) QK.tooltips();
  }
  var api = {
    add: function (id) { id = String(id); if (ids.indexOf(id) >= 0) return false; if (ids.length >= max) ids.shift(); ids.push(id); changed(); return true; },
    remove: function (id) { id = String(id); ids = ids.filter(function (x) { return x !== id; }); changed(); },
    toggle: function (id) { id = String(id); if (ids.indexOf(id) >= 0) api.remove(id); else api.add(id); return ids.indexOf(id) >= 0; },
    has: function (id) { return ids.indexOf(String(id)) >= 0; },
    ids: function () { return ids.slice(); },
    open: function () { open = true; paint(); },
    close: function () { open = false; paint(); },
    clear: function () { ids = []; changed(); },
    refresh: function () { paint(); },
    el: function () { return el; },
    destroy: function () { if (el) el.remove(); el = null; document.documentElement.classList.remove('qk-tray-on'); document.documentElement.style.removeProperty('--qk-tray-h'); }
  };
  paint();
  return api;
};
QK.trayCompare = function (o) {
  o = o || {};
  var E = (o.entities || []).slice(0, 4), n = E.length;
  var head = '<div class="qk-tc-r qk-tc-head"><span class="qk-tc-lab"></span>' + E.map(function (e) {
    var b = QK.color.block(e.colour && QK.color.parse(e.colour) ? e.colour : null);
    var nm = '<b class="' + QK.longName(e.short || e.name, 14).trim() + '">' + esc(e.short || e.name) + '</b>';
    return '<span class="qk-tc-ent" style="--tb:' + esc(b.bg) + (b.edge ? ';--te:' + esc(b.edge) : '') + '">' + (e.href ? '<a href="' + esc(e.href) + '">' + nm + '</a>' : nm) + '<small>' + esc(e.sub || '') + '</small></span>';
  }).join('') + '</div>';
  var body = (o.groups || []).map(function (g) {
    var rs = (g.rows || []).filter(function (r) { return r && (r.cells || []).some(function (c) { return c && (isNum(c.pctl) || (c.text && c.text !== '—')); }); });
    if (!rs.length) return '';
    return '<div class="qk-tc-g">' + esc(g.label) + '</div>' + rs.map(function (r) {
      var best = -1, bv = null;
      (r.cells || []).forEach(function (c, i) { if (c && isNum(c.pctl) && (bv === null || c.pctl > bv)) { bv = c.pctl; best = i; } });
      return '<div class="qk-tc-r"><span class="qk-tc-lab"' + (r.tip ? ' data-tip="' + esc(r.tip) + '" tabindex="0"' : '') + '>' + esc(r.label) + (r.ours ? QK.ours({ short: true, model: r.ours.name, about: r.ours.about }) : '') + '</span>' +
        E.map(function (e, i) {
          var c = (r.cells || [])[i] || {}, p = c.pctl;
          return '<span class="qk-tc-c' + (i === best ? ' best' : '') + '"' + (isNum(p) ? ' title="' + esc(QK.ordinal(Math.round(p)) + ' percentile') + '"' : '') + '><span class="qk-tc-bar" aria-hidden="true"><i style="width:' + (isNum(p) ? Math.max(3, p) : 0) + '%;background:' + (isNum(p) ? QK.pctColor(p) : 'transparent') + '"></i></span>' +
            (isNum(p) ? '<span class="qk-pbox num" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '">' + Math.round(p) + '</span>' : '<span class="qk-pbox num empty">–</span>') +
            '<span class="qk-tc-v num">' + esc(c.text === undefined ? '—' : c.text) + '</span></span>';
        }).join('') + '</div>';
    }).join('');
  }).join('');
  return '<div class="qk-tc" style="--n:' + n + '">' + head + (body || QK.empty('Nothing to compare', 'These players share no metrics with values.')) + (o.note ? '<p class="qk-pnote">' + o.note + '</p>' : '') + '</div>';
};

/* ─────────────────────────────────────── strengths and weaknesses */
QK.strengths = function (o) {
  o = o || {};
  var chip = function (x) {
    return '<li' + (x.tip ? ' data-tip="' + esc(x.tip) + '" tabindex="0"' : '') + '><span class="qk-pbox num" style="background:' + QK.pctColor(x.pctl) + ';color:' + QK.pctInk(x.pctl) + '">' + Math.round(x.pctl) + '</span><span class="l">' + esc(x.label) + '</span><span class="v num">' + esc(x.text || '') + '</span></li>';
  };
  var nm = (o.href ? '<a href="' + esc(o.href) + '">' : '') + esc(o.name) + (o.href ? '</a>' : '');
  return '<article class="qk-sw"><header>' + QK.teamMark({ abbr: o.abbr, colour: o.colour, name: o.name }, 'sm') + '<span class="qk-sw-nm"><b class="' + QK.longName(o.name, 18).trim() + '">' + nm + '</b>' + (o.sub ? '<small>' + esc(o.sub) + '</small>' : '') + '</span></header>' +
    '<div class="qk-sw-h up">' + esc(o.bestLabel || 'Best at') + '</div><ul>' + (o.best || []).map(chip).join('') + '</ul>' +
    '<div class="qk-sw-h dn">' + esc(o.worstLabel || 'Weakest at') + '</div><ul>' + (o.worst || []).map(chip).join('') + '</ul></article>';
};

/* ─────────────────────────────────────── the control bar */
QK.scoutBar = function (items, o) {
  o = o || {};
  return '<div class="qk-sbar' + (o.cls ? ' ' + esc(o.cls) : '') + '">' + (items || []).filter(Boolean).map(function (it) {
    return '<label class="qk-sbar-f' + (it.cls ? ' ' + esc(it.cls) : '') + '"><span class="qk-within-l">' + esc(it.label) + '</span>' + it.html + '</label>';
  }).join('') + '</div>';
};

})(window);
