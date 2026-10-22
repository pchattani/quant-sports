/* The Quant Gridiron — the Model section's text pages: Methodology (#/methodology[/<sec>]), Glossary
 * (#/glossary[/<key> | g:<group>]) and the Disclaimer (#/disclaimer). Calibration lives in calibration.js.
 * The text is GI.METHOD (method-text.js); old links inside it are rewritten through GI.fixLinks.
 * Reads glossary.json. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
function slug(s) { return String(s || 'group').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

GI.route('methodology', function (el, params) {
  const M = GI.METHOD || {};
  const tmp = document.createElement('div');
  tmp.innerHTML = GI.fixLinks(M.HTML || '');
  const secs = Array.prototype.slice.call(tmp.querySelectorAll('section[id]')).map(s => {
    const h2 = s.querySelector('h2');
    const title = h2 ? h2.textContent : s.id;
    if (h2) h2.parentNode.removeChild(h2);
    return { id: s.id.replace(/^m-/, ''), title: title, html: s.innerHTML };
  });
  el.innerHTML = GI.pageHead('Model', 'Methodology', 'Where the data comes from, how every model works, and where it is wrong. Every constant is the one in the code on 1 October 2026; each section names its source file under <code>oddsmarkets/nfl/</code>.') + GI.sectionNav('model', 'methodology') +
    '<div class="gi-doc"><nav class="qk-card gi-toc" aria-label="Sections"><b>Contents</b><ol>' + secs.map(s => '<li><a href="#/methodology/' + esc(s.id) + '" data-target="method-' + esc(s.id) + '">' + esc(s.title) + '</a></li>').join('') + '</ol></nav>' +
    '<div class="gi-doc-body">' + secs.map((s, i) => '<section class="qk-card gi-prose" id="method-' + esc(s.id) + '"><div class="qk-card-body"><h2><span class="gi-num" style="color:var(--signal)">' + (i + 1) + '</span> ' + esc(s.title) + '</h2>' + s.html + '</div></section>').join('') + '</div></div>';
  el.querySelectorAll('.gi-toc a[data-target]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const t = document.getElementById(a.dataset.target);
    if (t) t.scrollIntoView({ block: 'start' });
    GI.setHashQuiet(a.getAttribute('href'));
  }));
  const want = params.sec || '';
  if (want) { const t = document.getElementById('method-' + String(want).replace(/^m-/, '')); if (t) setTimeout(() => t.scrollIntoView({ block: 'start' }), 30); }
});

GI.route('glossary', function (el, params) {
  const key = params.id || (params.query || {}).k || '';
  return GI.load('glossary.json').then(g => {
    if (!el.isConnected) return;
    const M = GI.METHOD || {};
    const groups = GI.ok(g) ? (g.groups || []) : [];
    const MT = (M.MODEL_TERMS || []).map(x => [x[0], x[1].slice()]);
    ((g || {}).model || []).forEach(t => { let grp = MT.find(x => x[0] === (t.group || 'Models')); if (!grp) { grp = [t.group || 'Models', []]; MT.push(grp); } if (!grp[1].some(y => y[1] === t.label)) grp[1].push([t.key + '_model', t.label, t.desc]); });
    const used = {};
    const entry = (e, isModel) => {
      let id = e.key;
      if (used[e.key]) { id = e.key + '-' + used[e.key]; used[e.key]++; } else used[e.key] = 1;
      const tags = [];
      if (isModel) tags.push('model term');
      else {
        if (e.lower) tags.push('lower is better');
        if (e.scope && e.scope !== 'all') tags.push(e.scope === 'style' ? 'tendency' : String(e.scope));
        if (isNum(e.stabilises_at)) tags.push('stabilises ~' + GI.int(e.stabilises_at) + ' ' + (e.unit || 'plays'));
      }
      return '<div class="gi-gl-e" id="gl-' + esc(id) + '" data-q="' + esc(GI.fold([e.label, e.key, e.desc, e.group, e.scope].join(' '))) + '" data-scope="' + (isModel ? 'model' : 'metric') + '"><dt><a href="#/glossary/' + encodeURIComponent(e.key) + '">' + esc(e.label || e.key) + '</a> <code>' + esc(e.key) + '</code>' +
        tags.map(t => '<span class="qk-badge">' + esc(t) + '</span>').join('') + '</dt><dd>' + (e.desc ? esc(GI.copyText(GI.cleanDesc(e.desc))) : '<span class="qk-muted">No definition yet.</span>') + '</dd></div>';
    };
    const cards = groups.map(x => ({ name: x.name, sl: slug(x.name), html: (x.entries || []).map(e => entry(e, false)).join(''), n: (x.entries || []).length }))
      .concat(MT.map(x => ({ name: 'Terms: ' + x[0], sl: 'model-' + slug(x[0]), html: x[1].map(t => entry({ key: t[0], label: t[1], desc: t[2] }, true)).join(''), n: x[1].length })));
    const stab = [];
    groups.forEach(x => (x.entries || []).forEach(e => { if (isNum(e.stabilises_at) && !stab.some(r => r.key === e.key)) stab.push(Object.assign({ _g: x.name }, e)); }));
    stab.sort((a, b) => a.stabilises_at - b.stabilises_at);
    const N = (g || {}).notices || {};
    el.innerHTML = GI.pageHead('Model', 'Glossary', 'Every metric the site computes for players and teams, with the sample at which it stabilises, and the terms the pages use.') + GI.sectionNav('model', 'glossary') +
      '<div class="gi-toolbar">' + GI.field('Filter', '<input id="gl-search" class="qk-input" type="search" placeholder="Filter the glossary…">') + GI.field('Show', GI.select('gl-kind', [['', 'Metrics and terms'], ['metric', 'Catalogue metrics'], ['model', 'Terms and models']], '', 'Show')) + '<span class="qk-sub" id="gl-count"></span></div>' +
      '<div class="qk-chips scroll gi-gl-index" style="margin-top:10px">' + cards.map(c => '<a class="qk-chip" href="#/glossary/g:' + esc(c.sl) + '" data-group="' + esc(c.sl) + '">' + esc(c.name) + ' <span class="n">' + c.n + '</span></a>').join('') + '</div>' +
      (stab.length ? GI.card('Stabilisation points', 'the sample at which a metric is 70% signal: with r(n) = n/(n + k), n₀.₇ = 7k/3; the catalogue shrinks each value by (n·x + k·mean)/(n + k)', GI.chartBox('gl-stab', Math.max(300, Math.min(stab.length, 30) * 20 + 40), 'Stabilisation points'), { cls: 'gi-mt' }) : '') +
      cards.map(c => '<section class="qk-card gi-gl-group gi-mt" data-group="' + esc(c.sl) + '" id="glg-' + esc(c.sl) + '"><div class="qk-card-head"><div class="gi-card-titles"><h3 class="qk-card-title">' + esc(c.name) + '</h3><div class="qk-card-sub">' + c.n + '</div></div></div><div class="qk-card-body"><dl class="gi-gl-list">' + c.html + '</dl></div></section>').join('') +
      '<div id="gl-none" hidden>' + QK.empty('Nothing matches', 'Try a shorter word.') + '</div>' +
      GI.card('Data credits', '', '<div class="gi-prose"><p>' + esc(N.nflverse || M.NFLVERSE || '') + '</p><p>' + esc(N.ftn || M.FTN || '') + '</p><p>' + esc(N.ngs || M.NGS || '') + '</p></div>', { cls: 'gi-mt' });
    if (stab.length) {
      const top = stab.slice(0, 30);
      GI.ch.bar('gl-stab', { cats: top.map(e => e.label + ' (' + (e.unit || 'plays') + ')'), series: [{ name: 'Stabilises at', data: top.map(e => Math.round(e.stabilises_at)) }], horizontal: true, labels: true, fmt: v => GI.int(v), labelWidth: 200, hrefs: top.map(e => '#/glossary/' + encodeURIComponent(e.key)) });
    }
    const input = el.querySelector('#gl-search'), kind = el.querySelector('#gl-kind'), count = el.querySelector('#gl-count');
    const entries = Array.prototype.slice.call(el.querySelectorAll('.gi-gl-e')), groupsEl = Array.prototype.slice.call(el.querySelectorAll('.gi-gl-group'));
    const filter = () => {
      const needle = GI.fold(input.value.trim()), kd = kind.value;
      let shown = 0;
      entries.forEach(e => { const hit = (!needle || needle.split(/\s+/).every(w => e.dataset.q.indexOf(w) >= 0)) && (!kd || e.dataset.scope === kd); e.hidden = !hit; if (hit) shown++; });
      groupsEl.forEach(c => { c.hidden = !c.querySelector('.gi-gl-e:not([hidden])'); });
      el.querySelector('#gl-none').hidden = !!shown;
      count.textContent = needle || kd ? shown + ' of ' + entries.length + ' entries' : entries.length + ' entries';
    };
    input.addEventListener('input', filter);
    kind.addEventListener('change', filter);
    filter();
    el.querySelectorAll('.gi-gl-index a').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); const t = el.querySelector('#glg-' + a.dataset.group); if (t) { t.hidden = false; t.scrollIntoView({ block: 'start' }); } GI.setHashQuiet(a.getAttribute('href')); }));
    if (key) {
      if (key.indexOf('g:') === 0) { const t = el.querySelector('#glg-' + key.slice(2).replace(/[^a-z0-9-]/g, '')); if (t) setTimeout(() => t.scrollIntoView({ block: 'start' }), 30); }
      else {
        const e = document.getElementById('gl-' + key);
        if (e) { e.classList.add('gi-hit'); setTimeout(() => e.scrollIntoView({ block: 'center' }), 60); }
        else { input.value = key.replace(/_/g, ' '); filter(); }
      }
    }
  });
});

GI.route('disclaimer', function (el) {
  const t = document.getElementById('disclaimer-template');
  el.innerHTML = GI.pageHead('Model', 'Disclaimer and terms', '') + GI.sectionNav('model', 'disclaimer') + GI.card('', '', '<div class="gi-prose">' + (t ? t.innerHTML : '') + '</div>');
});

})(window.GI);
