/* Lookup tables page (tables.html): what the built-in tables hold, the user's own rows on top
 * of them, and the steps of the user's uploads that no table recognizes.
 *
 * Three sections, one per table of the Final lookup tables (atif/lookup.py): action lookup
 * (categories from shell commands and native tools, and the shell runners), target files,
 * phase lookup (rows 1-15 and the general rule). Each shows the user's rows, a form to add one,
 * and the built-in contents word for word (vocab.lookup of data/overview.js, else the
 * engine's) in a collapsed block whose rows have "Change…", which starts a row of the user's
 * from them.
 * The rows are the one set of the viewer
 * (TV.ruleset, localStorage), which every page applies to every trajectory; new rows go last,
 * and the last matching row wins. Where the engine can run, each change re-runs the corpus
 * (TV.corpus.overview, cached per set of rows; each row shows how many corpus steps of run 1
 * it matched) and the uploads, whose unrecognised steps (review.js) are listed at the top.
 * #draft=<row> (from "+ Row from this action" on a step) fills a form; #back=<page> is where
 * the close button returns; #unrec scrolls to the review. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var D = window.TRAJ_OVERVIEW && window.TRAJ_OVERVIEW.bugs ? window.TRAJ_OVERVIEW : null;
  var L = null, RS = TV.ruleset.get(), HITS = null, HITS_KEY = null, seq = 0;
  var UPLOADS = [];
  var hq = TV.readHash(), SAME = 'previous step\'s phase';
  if (D) TV.vocab = D.vocab || {};
  TV.watchRules(TV.ruleset.key(RS));

  /* ---------------------------------------------------------------- where to go back */
  var back = /^(index|bug|analyze)\.html(#.*)?$/.test(hq.back || '') ? hq.back : null;
  if (!back && document.referrer) {
    try {
      var ref = new URL(document.referrer);
      if (ref.origin === location.origin && !/(rules|tables)\.html$/.test(ref.pathname)) back = ref.pathname.split('/').pop() + ref.hash;
    } catch (e) { /* no referrer */ }
  }
  if (back) $('#closeRules').href = back;
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (e.key !== 'Escape' || tag === 'input' || tag === 'select' || !$('#help').hidden || $$('.lt-add').some(function (f) { return !f.hidden; })) return;
    location.href = $('#closeRules').getAttribute('href');
  });

  /* ---------------------------------------------------------------- the tables' contents */
  function start() {
    var v = D && D.vocab;
    if (v && v.lookup) return Promise.resolve({ lookup: v.lookup });
    return TV.engine.start().then(function (info) {
      TV.vocab = Object.assign({}, TV.vocab, { lookup: info.lookup });
      return { lookup: info.lookup };
    });
  }

  /* ---------------------------------------------------------------- applying */
  function applied(html, cls) {
    var el = $('#rsApplied');
    el.className = 'rs-applied' + (cls ? ' ' + cls : '');
    el.innerHTML = html;
  }
  var timer = 0;
  function changed() {
    RS = TV.ruleset.save(RS);
    TV.rulesShown(TV.ruleset.key(RS));
    render();
    clearTimeout(timer);
    timer = setTimeout(apply, 600);
  }
  /* the corpus (for the hit counts) and the uploads (for their unrecognised steps) under RS */
  function apply() {
    var my = ++seq, key = TV.ruleset.key(RS);
    if (!TV.engine.usable()) {
      if (!TV.ruleset.isDefault(RS)) applied('saved in this browser; they apply on the hosted site or with <code>python3 -m atif.cli serve</code>', 'warn');
      return;
    }
    var corpus = TV.ruleset.isDefault(RS) || !D ? Promise.resolve(null) : TV.corpus.overview(D, RS, function (done, total) {
      if (my === seq) applied('<span class="spin small" aria-hidden="true"></span>applying to the corpus… ' + done + ' / ' + total, 'busy');
    });
    corpus.then(function (res) {
      if (my !== seq) return;
      HITS = res ? res.hits : null; HITS_KEY = key;
      render();
      var stale = UPLOADS.filter(function (r) { return r.rulesKey !== key; });
      if (!stale.length) return;
      return TV.uploads.refresh(UPLOADS, RS, function (done, total) {
        if (my === seq) applied('<span class="spin small" aria-hidden="true"></span>analysing your uploads again… ' + done + ' / ' + total, 'busy');
      });
    }).then(function () {
      if (my !== seq) return;
      applied(TV.ruleset.isDefault(RS) ? '' : 'applied to the corpus' + (UPLOADS.length ? ' and your uploads' : ''), TV.ruleset.isDefault(RS) ? '' : 'ok');
      renderReview();
    }, function (err) {
      if (my !== seq) return;
      applied(err.answered ? 'not applied: ' + esc(err.message) : 'saved; could not apply them here (' + esc(err.message) + ')', err.answered ? 'bad' : 'warn');
    });
  }

  /* ---------------------------------------------------------------- the user's rows */
  function hits(id) {
    if (!HITS || HITS_KEY !== TV.ruleset.key(RS)) return '';
    var x = HITS[id];
    return x ? '<span class="hits" data-tip="steps of the corpus (run 1) this row matched">' + TV.plural(x.actions, 'step') + '</span>' : '<span class="hits none" data-tip="no step of the corpus (run 1) matches it; it may match your uploads">no corpus match</span>';
  }
  function mineHTML(kinds) {
    var rows = RS.custom.filter(function (r) { return kinds.indexOf(r.kind) >= 0; });
    if (!rows.length) return '';
    return '<ul class="lt-rows">' + rows.map(function (r) {
      return '<li class="lt-row' + (r.enabled === false ? ' off' : '') + '"><span class="lt-yours">yours</span><span class="lt-sent">' + esc(TV.ruleSentence(r)) +
        (r.regex ? ' <span class="muted small">(pattern)</span>' : '') + '</span>' + hits(r.id) +
        '<button type="button" class="btn ghost icon small" data-del="' + esc(r.id) + '" title="Delete this row" aria-label="Delete this row">✕</button></li>';
    }).join('') + '</ul>';
  }

  /* ---------------------------------------------------------------- the built-in tables */
  function phaseCell(v) {
    if (/^\(previous/.test(v || '')) return '<span class="lt-same" data-tip="' + esc(L.same) + '">' + SAME + '</span>';
    return TV.PHASE_ORDER.indexOf(v) >= 0 ? TV.phaseChip(v) : esc(v);
  }
  function changeBtn(table, value, label) {
    return '<button type="button" class="btn ghost small lt-change" data-change="' + table + '" data-value="' + esc(value) + '" data-label="' + esc(label) + '" title="Start a row of yours from this one">Change…</button>';
  }
  /* a cell of the table, its entries split at ";" and "," into code chips, word for word */
  function entriesHTML(cell) {
    if (!cell) return '<span class="muted">–</span>';
    return cell.split(/;\s*/).map(function (group) {
      return group.split(/,\s*(?![^(]*\))/).map(function (x) { return '<code>' + esc(x.trim()) + '</code>'; }).join(' ');
    }).join('<span class="lt-semi">;</span> ');
  }
  function renderBuiltIn() {
    $('#ltVersion').textContent = L.version || 'Final lookup table';
    $('#ltDate').textContent = L.version_date ? '· ' + L.version_date : '';
    $('#actSum').textContent = '· ' + L.actions.length + ' categories, with the shell commands and the native tools that give each';
    $('#actBody').innerHTML = L.actions.map(function (a) {
      return '<tr><td><span class="midchip" data-tip="' + esc(a.type + ': ' + a.does) + '">' + esc(a.type) + '</span><div class="muted small">' + esc(a.does) + '</div></td>' +
        '<td class="lt-prog">' + entriesHTML(a.shell) + '</td><td class="lt-tools">' + entriesHTML(a.native) + '</td>' +
        '<td>' + changeBtn('act', a.type, a.type) + '</td></tr>';
    }).join('');
    $('#compound').textContent = L.compound || '';
    $('#beyond').innerHTML = L.actions.filter(function (a) { return (a.other_agents || []).length; }).map(function (a) {
      return '<b>' + esc(a.type) + '</b> ' + a.other_agents.map(function (n) { return '<code>' + esc(n) + '</code>'; }).join(' ');
    }).join(' · ') + '. Any other tool is <b>other</b>.';
    $('#roleSum').textContent = '· ' + L.targets.length + ' targets, checked in this order';
    $('#roleBody').innerHTML = L.targets.map(function (r) {
      return '<tr><td><b>' + esc(r.name) + '</b></td><td>' + esc(r.files) + '</td><td>' + changeBtn('role', r.target, r.name) + '</td></tr>';
    }).join('');
    $('#roleNote').textContent = L.targets_swebench || '';
    $('#phaseSum').textContent = '· ' + L.phases.length + ' rows; the first that matches the step decides';
    $('#phaseBody').innerHTML = L.phases.map(function (p) {
      var value = TV.PHASE_ORDER.indexOf(p.phase) >= 0 ? p.phase : 'follow';
      return '<tr><td class="lt-n">' + p.n + '</td><td>' + phaseCell(p.phase) + '</td><td>' + esc(p.categories) + '</td><td>' + esc(p.target) + '</td><td>' + esc(p.position) + '</td>' +
        '<td>' + changeBtn('phase', value, 'row ' + p.n + ': ' + p.categories + (p.target !== 'any' ? ' on a ' + p.target : '')) + '</td></tr>';
    }).join('');
    $('#sameNote').innerHTML = '<b>General rule</b>: ' + esc(L.general) + ' <b>' + SAME + '</b>: ' + esc(L.same) + '.';
  }

  /* ---------------------------------------------------------------- unrecognised steps of the uploads */
  function renderReview() {
    var key = TV.ruleset.key(RS), fresh = UPLOADS.filter(function (r) { return r.rulesKey === key; });
    var rep = TV.review.merge(fresh), el = $('#unrec');
    el.innerHTML = TV.review.html(rep, {
      where: function (g) {
        return '<div class="muted">in ' + g.uploads.slice(0, 3).map(function (r) { return '<a href="analyze.html#u=' + encodeURIComponent(r.id) + '">' + esc(r.name) + '</a>'; }).join(', ') +
          (g.uploads.length > 3 ? ' and ' + (g.uploads.length - 3) + ' more' : '') + '</div>';
      }
    });
    var card = el.querySelector('.unrec');
    if (card) {
      card.querySelector('.ur-intro').insertAdjacentHTML('afterbegin', 'From your uploads. ');
      TV.review.bind(card, rep, function (rs) { RS = rs; changed(); });
    }
    if (hq.unrec != null || location.hash === '#unrec') { hq.unrec = null; setTimeout(function () { (card || el).scrollIntoView({ block: 'start' }); }, 60); }
  }

  /* ---------------------------------------------------------------- render */
  function render() {
    if (!L) return;
    var n = RS.custom.length;
    $('#rsName').textContent = n ? TV.plural(n, 'row') : 'none';
    $('#resetAll').hidden = !n;
    $('#actMine').innerHTML = mineHTML(['category', 'shell_tool']);
    $('#roleMine').innerHTML = mineHTML(['file_role']);
    $('#phaseMine').innerHTML = mineHTML(['phase']);
  }
  function fillSelects() {
    var does = {};
    L.actions.forEach(function (a) { does[a.type] = a.does; });
    $('#actForm [name=value]').innerHTML = L.actions.map(function (a) { return '<option value="' + esc(a.type) + '">' + esc(a.type) + ' · ' + esc(a.does) + '</option>'; }).join('');
    $('#phaseForm [name=value]').innerHTML = TV.PHASE_ORDER.map(function (p) { return '<option value="' + p + '">' + p + '</option>'; }).join('') +
      '<option value="follow">' + SAME + '</option>';
    $('#roleForm [name=value]').innerHTML = L.targets.map(function (r) { return '<option value="' + esc(r.target) + '">' + esc(r.name) + '</option>'; }).join('');
  }

  /* ---------------------------------------------------------------- forms */
  function nextId() {
    var used = {};
    RS.custom.forEach(function (r) { used[r.id] = 1; });
    for (var n = 1; ; n++) if (!used['R' + n]) return 'R' + n;
  }
  var KIND_OF = { actForm: 'category', shellForm: 'shell_tool', roleForm: 'file_role', phaseForm: 'phase' };
  function howWord(form) {
    var f = form.field && form.field.value, el = form.querySelector('.lt-how-l');
    if (!form.field) return;
    if (el) el.textContent = f === 'program' ? 'Program name (with its first argument, if any)' : f === 'tool' ? 'Text the tool name contains' : 'Text the command contains';
    form.match.placeholder = f === 'program' ? (form.id === 'phaseForm' ? 'adb' : 'cargo test') : f === 'tool' ? (form.id === 'phaseForm' ? 'update_plan' : 'list_dir') :
      form.id === 'phaseForm' ? 'update_plan' : './gradlew lint';
    preview(form);
  }
  /* the row the form would add, in the same words as the rows above */
  function formRow(form) {
    var kind = KIND_OF[form.id];
    return { kind: kind, field: kind === 'file_role' ? 'path' : kind === 'shell_tool' ? 'tool' : form.field.value,
      match: form.match.value.trim(), regex: false, value: form.value.value.trim(), enabled: true };
  }
  function preview(form) {
    var r = formRow(form), el = form.querySelector('.lt-preview');
    el.innerHTML = r.match ? '<span class="muted small">The row will read:</span> ' + esc(TV.ruleSentence(r)) : '<span class="muted small">Type the ' +
      (r.kind === 'shell_tool' ? 'tool\'s name' : r.kind === 'file_role' ? 'text to look for in file paths' : 'text to look for') + ' above.</span>';
  }
  function openForm(form, focus) {
    $$('.lt-add').forEach(function (f) { if (f !== form) f.hidden = true; });
    form.hidden = false;
    preview(form);
    if (focus !== false) setTimeout(function () { form.match.focus(); }, 30);
  }
  function closeForm(form) {
    form.hidden = true;
    form.match.value = '';
    form.querySelector('.rf-err').textContent = '';
    form.querySelector('.lt-hint').hidden = true;
  }
  function onAdd(form, kind) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var m = form.match.value.trim(), err = form.querySelector('.rf-err'), val = form.value.value.trim();
      if (!m) { err.textContent = kind === 'shell_tool' ? 'Type the tool\'s name.' : 'Type the text to look for.'; form.match.focus(); return; }
      if (kind === 'shell_tool' && !/^[A-Za-z_][\w.-]*$/.test(val)) { err.textContent = 'Type the argument that holds the command, such as command or cmd.'; form.value.focus(); return; }
      err.textContent = '';
      RS.custom.push({ id: nextId(), kind: kind, field: kind === 'file_role' ? 'path' : kind === 'shell_tool' ? 'tool' : form.field.value,
        match: m, regex: false, value: val, enabled: true });
      closeForm(form);
      changed();
    });
    form.addEventListener('input', function () { form.querySelector('.rf-err').textContent = ''; preview(form); });
    form.addEventListener('change', function () { preview(form); });
    form.querySelector('[data-cancel]').addEventListener('click', function () { closeForm(form); });
    form.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); closeForm(form); } });
    if (form.field) { form.field.addEventListener('change', function () { howWord(form); }); howWord(form); }
  }
  onAdd($('#actForm'), 'category');
  onAdd($('#shellForm'), 'shell_tool');
  onAdd($('#roleForm'), 'file_role');
  onAdd($('#phaseForm'), 'phase');
  document.addEventListener('click', function (e) {
    var del = e.target.closest('[data-del]');
    if (del) {
      var id = del.dataset.del;
      RS.custom = RS.custom.filter(function (r) { return r.id !== id; });
      changed();
      return;
    }
    var op = e.target.closest('[data-open]');
    if (op) { openForm($('#' + op.dataset.open)); return; }
    var ch = e.target.closest('[data-change]');
    if (ch) {
      var form = { act: $('#actForm'), role: $('#roleForm'), phase: $('#phaseForm') }[ch.dataset.change];
      form.value.value = ch.dataset.value;
      var hint = form.querySelector('.lt-hint');
      hint.innerHTML = 'Changing <b>' + esc(ch.dataset.label) + '</b>: type the ' + (ch.dataset.change === 'role' ? 'path' : 'command, tool or program') + ' and pick the new value.';
      openForm(form, false);
      hint.hidden = false;
      form.scrollIntoView({ block: 'center', behavior: 'smooth' });
      setTimeout(function () { form.match.focus(); }, 250);
    }
  });
  $('#resetAll').addEventListener('click', function () {
    if (!window.confirm('Remove all your rows?')) return;
    RS = TV.ruleset.clean(null);
    changed();
  });

  /* ---------------------------------------------------------------- start */
  start().then(function (info) {
    L = info.lookup;
    renderBuiltIn();
    fillSelects();
    if (hq.draft) {                                   // "+ Row from this action" on a step
      try {
        var d = JSON.parse(hq.draft), form = d.kind === 'category' ? $('#actForm') : d.kind === 'file_role' ? $('#roleForm') : $('#phaseForm');
        form.match.value = String(d.match || '');
        if (form.field && d.field && /^(target|tool|program)$/.test(d.field)) { form.field.value = d.field; howWord(form); }
        if (d.value) form.value.value = d.value;
        openForm(form, false);
        TV.writeHash({ back: back || '' });
        setTimeout(function () { form.scrollIntoView({ block: 'center', behavior: 'smooth' }); form.match.focus(); form.match.select(); }, 120);
      } catch (e) { /* a broken link: empty forms */ }
    }
    render();
    return TV.uploads.list().then(function (xs) {
      UPLOADS = xs.filter(function (r) { return r && r.result && r.result.trajectory; });
      renderReview();
      apply();
    });
  }).catch(function (err) {
    if (L) return;
    $('#app').innerHTML = '<div class="card nodata"><h2>The lookup tables could not be loaded</h2><p>(' + esc(err && err.message) + ')</p><p>Generate the data from the Parser directory: <code>python3 -m atif.cli view --all</code></p></div>';
  });
})();
