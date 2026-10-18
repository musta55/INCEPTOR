/* Upload page (upload.html): add logs, then say how they are related.
 *
 *   Separate                  each upload stands alone (analyze.html#u=<id>), as before
 *   One bug, several agents   a comparison group of kind 'agents': the agents side by side
 *   One agent, several runs   a comparison group of kind 'runs': one agent's runs, numbered
 *
 * Files are analysed (and kept) as soon as they are added, so the page can show what each is
 * (agent, model, bug named in the log, actions) and check the choice: one agent only for
 * 'runs', distinct run numbers, one bug for the whole group, no SWE-bench run beside an
 * Android one. Saving writes the group onto each member's record (uploads.js), analyses again
 * the members whose bug id changed, and opens the group (analyze.html#g=<id>, with the
 * Fingerprint tab). upload.html#g=<id> edits an existing group; files can be added to it. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$;
  var D = window.TRAJ_OVERVIEW;
  if (D && D.vocab) TV.vocab = D.vocab;
  var ITEMS = [];            // [{rec, isNew, run, outcome}]
  var REMOVED = [];          // members taken out of an edited group
  var KIND = 'none', touched = false, GID = null;

  function busy(text) { $('#busy').hidden = !text; $('#busyText').textContent = text || ''; }
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }
  function agentOf(r) { return TV.uploads.agent(r); }
  function bugOf(r) { var res = r.result || {}; return r.bug || (res.source || {}).bug || (res.trajectory || {}).bug || ''; }
  function uniq(xs) { return xs.filter(function (x, k) { return x && xs.indexOf(x) === k; }); }
  function typedBug() { return $('#gBug').value.trim().replace(/^bug-/, ''); }

  /* ---------------------------------------------------------------- what the files look like */
  function guessKind() {
    if (ITEMS.length < 2) return 'none';
    var ags = uniq(ITEMS.map(function (it) { return agentOf(it.rec); }));
    if (ags.length === 1) return 'runs';
    return ags.length === ITEMS.length ? 'agents' : 'none';
  }
  function defaultName() {
    var bug = typedBug() || uniq(ITEMS.map(function (it) { return bugOf(it.rec); }))[0];
    var head = bug ? (TV.uploads.project(ITEMS[0].rec) === 'swebench' ? bug : 'bug-' + bug) : 'Comparison';
    return head + ' · ' + (KIND === 'runs' ? agentOf(ITEMS[0].rec) + ', ' + ITEMS.length + ' runs' : ITEMS.length + ' agents');
  }
  /* {errors, notes} of the current choice */
  function check() {
    var errors = [], notes = [];
    if (KIND === 'none') return { errors: errors, notes: notes };
    if (ITEMS.length < 2) errors.push('Add at least two files to compare.');
    var ags = uniq(ITEMS.map(function (it) { return agentOf(it.rec); }));
    if (KIND === 'runs' && ags.length > 1) errors.push('These come from different agents (' + ags.join(', ') + '). Pick “One bug, several agents”, or remove files.');
    if (KIND === 'runs') {
      var nums = ITEMS.map(function (it) { return it.run; });
      if (nums.some(function (n) { return !(n >= 1 && n === Math.round(n)); }) || uniq(nums.map(String)).length < nums.length) errors.push('Give each file its own run number.');
    }
    if (KIND === 'agents') {
      var twice = ags.filter(function (a) { return ITEMS.filter(function (it) { return agentOf(it.rec) === a; }).length > 1; });
      if (twice.length) notes.push(twice.join(', ') + ' appears more than once; the model or the file name tells them apart.');
    }
    if (uniq(ITEMS.map(function (it) { return TV.uploads.project(it.rec); })).length > 1) errors.push('A SWE-bench run cannot be compared with an Android one.');
    var bugs = uniq(ITEMS.map(function (it) { return String(bugOf(it.rec)); }));
    if (!typedBug() && bugs.length > 1) errors.push('The logs name different bugs (' + bugs.join(', ') + '). Type the bug they all repair.');
    else if (typedBug() && bugs.some(function (b) { return b !== typedBug(); })) notes.push('All files will be read as bug-' + typedBug() + '.');
    return { errors: errors, notes: notes };
  }

  /* ---------------------------------------------------------------- render */
  function outcomeSeg(it, k) {
    var cur = it.outcome === true ? 'pass' : it.outcome === false ? 'fail' : '';
    return '<span class="seg small" role="group" aria-label="Harness outcome">' + [['', '?'], ['pass', 'pass'], ['fail', 'fail']].map(function (o) {
      return '<button type="button" data-oc="' + o[0] + '" data-k="' + k + '" aria-pressed="' + (cur === o[0]) + '"' + (o[0] ? '' : ' title="unknown"') + '>' + o[1] + '</button>';
    }).join('') + '</span>';
  }
  function render() {
    $('#cfg').hidden = !ITEMS.length;
    if (!ITEMS.length) return;
    var group = KIND !== 'none';
    $('#kinds').hidden = ITEMS.length < 2 && !GID;
    document.querySelectorAll('#kinds input').forEach(function (r) { r.checked = r.value === KIND; r.closest('.relopt').classList.toggle('on', r.checked); });
    $('#grpFields').hidden = !group;
    $('#gName').placeholder = defaultName();
    var h = '<div class="ufrow head' + (KIND === 'runs' ? ' runs' : '') + '" role="row"><span>File</span><span>Agent</span><span>Bug in log</span><span>Actions</span>' + (KIND === 'runs' ? '<span>Run</span>' : '') +
      '<span>Outcome</span><span></span></div>';
    ITEMS.forEach(function (it, k) {
      var r = it.rec, t = (r.result || {}).trajectory || {}, model = TV.uploads.model(r), bug = bugOf(r);
      h += '<div class="ufrow' + (KIND === 'runs' ? ' runs' : '') + '" role="row">' +
        '<span class="uf-name"><b>' + esc(r.name) + '</b><span class="muted small">' + esc(TV.uploads.formatLabel(((r.result || {}).source || {}).format)) + ' · ' + TV.uploads.sizeLabel(r.size || 0) + '</span></span>' +
        '<span>' + TV.agentHTML(agentOf(r)) + (model ? '<span class="muted small mono uf-model">' + esc(model) + '</span>' : '') + '</span>' +
        '<span>' + (bug ? esc(TV.uploads.bugLabel(bug, TV.uploads.project(r))) : '<span class="muted">–</span>') + '</span>' +
        '<span class="num">' + (t.n_actions || 0) + '</span>' +
        (KIND === 'runs' ? '<span><input class="uf-run" type="number" min="1" step="1" value="' + esc(it.run) + '" data-run="' + k + '" aria-label="Run number of ' + esc(r.name) + '"></span>' : '') +
        '<span>' + outcomeSeg(it, k) + '</span>' +
        '<span><button type="button" class="btn ghost icon small" data-rm="' + k + '" title="Remove" aria-label="Remove ' + esc(r.name) + '">✕</button></span></div>';
    });
    $('#files').innerHTML = h;
    validate();
  }
  function validate() {
    var c = check();
    $('#msg').innerHTML = c.errors.map(function (e) { return '<span class="bad">' + esc(e) + '</span>'; }).concat(c.notes.map(function (n) { return '<span>' + esc(n) + '</span>'; })).join('');
    var save = $('#save');
    save.disabled = !!c.errors.length;
    save.textContent = KIND !== 'none' ? 'Save and compare' : ITEMS.length === 1 ? 'Open' : 'Save';
    $('#discard').textContent = GID ? 'Cancel' : 'Discard';
  }

  /* ---------------------------------------------------------------- adding files */
  function addFiles(files) {
    if (!files || !files.length) return;
    if (!TV.engine.usable()) { status('warn', 'Uploading needs the analysis engine. Open the <a href="https://trajectiers.vercel.app/">hosted dashboard</a> or run <code>python3 -m atif.cli serve</code>.'); return; }
    status('', '');
    TV.addUploads(files, busy, function (added, failed) {
      added.forEach(function (rec) {
        var used = ITEMS.map(function (it) { return it.run; }), n = 1;
        while (used.indexOf(n) >= 0) n++;
        ITEMS.push({ rec: rec, isNew: true, run: n, outcome: null });
      });
      if (!touched) KIND = guessKind();
      if (!$('#gBug').value) { var bugs = uniq(ITEMS.map(function (it) { return String(bugOf(it.rec)); })); if (bugs.length === 1) $('#gBug').value = bugs[0]; }
      if (failed.length) status('warn', '<b>' + TV.plural(failed.length, 'file') + ' could not be read.</b> ' + failed.map(function (f) { return esc(f.name) + ': ' + esc(f.error); }).join(' · '));
      render();
    }, { bug: KIND !== 'none' ? typedBug() || null : null });
  }
  var picker = $('#file');
  $('#pick').addEventListener('click', function () { picker.click(); });
  picker.addEventListener('change', function () { addFiles(picker.files); picker.value = ''; });
  ['dragenter', 'dragover'].forEach(function (k) {
    document.addEventListener(k, function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return;
      e.preventDefault();
      $('#drop').classList.add('over');
    });
  });
  ['dragleave', 'drop'].forEach(function (k) {
    document.addEventListener(k, function (e) {
      if (k === 'dragleave' && e.relatedTarget) return;
      $('#drop').classList.remove('over');
      if (k === 'drop' && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files); }
    });
  });

  /* ---------------------------------------------------------------- editing the choice */
  $('#kinds').addEventListener('change', function (e) {
    if (!e.target.name) return;
    KIND = e.target.value;
    touched = true;
    render();
  });
  $('#gBug').addEventListener('input', function () { $('#gName').placeholder = defaultName(); validate(); });
  $('#files').addEventListener('input', function (e) {
    var k = e.target.dataset.run;
    if (k == null) return;
    ITEMS[+k].run = +e.target.value;
    validate();
  });
  $('#files').addEventListener('click', function (e) {
    var oc = e.target.closest('[data-oc]');
    if (oc) {
      ITEMS[+oc.dataset.k].outcome = oc.dataset.oc === 'pass' ? true : oc.dataset.oc === 'fail' ? false : null;
      render();
      return;
    }
    var rm = e.target.closest('[data-rm]');
    if (!rm) return;
    var it = ITEMS.splice(+rm.dataset.rm, 1)[0];
    if (it.isNew) TV.uploads.remove([it.rec.id]);
    else REMOVED.push(it.rec);
    if (!touched) KIND = guessKind();
    render();
  });

  /* ---------------------------------------------------------------- save, discard */
  $('#save').addEventListener('click', function () {
    if (check().errors.length) return;
    var group = KIND !== 'none', bug = typedBug() || null;
    var gid = group ? GID || 'g' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5) : null;
    var meta = group ? { id: gid, kind: KIND, name: $('#gName').value.trim() || defaultName() } : null;
    busy('Saving…');
    var steps = ITEMS.map(function (it) {
      return function () {
        var r = it.rec;
        r.outcome = it.outcome;
        if (r.result && r.result.trajectory) r.result.trajectory.outcome = { pass: it.outcome, by_run: { 1: it.outcome } };
        if (meta) r.group = meta; else delete r.group;
        if (KIND === 'runs') r.run = it.run; else delete r.run;
        if (group && bug && String(r.bug || '') !== bug) {
          r.bug = bug;
          busy('Analysing ' + r.name + ' as bug-' + bug + '…');
          return TV.uploads.reanalyze(r);
        }
        return TV.uploads.save(r);
      };
    }).concat(REMOVED.map(function (r) { return function () { delete r.group; delete r.run; return TV.uploads.save(r); }; }));
    steps.reduce(function (p, f) { return p.then(f); }, Promise.resolve()).then(function () {
      busy('');
      location.href = group ? 'analyze.html#g=' + encodeURIComponent(gid) : ITEMS.length === 1 ? 'analyze.html#u=' + encodeURIComponent(ITEMS[0].rec.id) : 'index.html';
    }, function (err) { busy(''); status('warn', 'Could not save: ' + esc(err.message)); });
  });
  $('#discard').addEventListener('click', function () {
    var fresh = ITEMS.filter(function (it) { return it.isNew; }).map(function (it) { return it.rec.id; });
    if (fresh.length && !window.confirm('Delete the ' + TV.plural(fresh.length, 'file') + ' added here?')) return;
    TV.uploads.remove(fresh).then(function () { location.href = GID ? 'analyze.html#g=' + encodeURIComponent(GID) : 'index.html'; });
  });

  /* ---------------------------------------------------------------- start: a new upload, or upload.html#g=<id> */
  var gq = TV.readHash().g;
  if (gq) {
    TV.uploads.list().then(function (xs) {
      var g = TV.uploads.groups(xs).filter(function (x) { return x.id === gq; })[0];
      if (!g) { status('warn', 'No comparison ' + esc(gq) + ' in this browser.'); return; }
      GID = g.id; KIND = g.kind; touched = true;
      ITEMS = g.members.map(function (r) { return { rec: r, isNew: false, run: r.run || 1, outcome: r.outcome == null ? null : r.outcome }; });
      $('#gBug').value = uniq(g.members.map(function (r) { return String(bugOf(r)); })).length === 1 ? bugOf(g.members[0]) : '';
      $('#gName').value = g.name || '';
      $('#upTitle').textContent = 'Edit comparison';
      document.title = 'Edit comparison · TrajecTiers';
      render();
    });
  }
  if (!TV.engine.usable()) status('warn', 'Uploading needs the analysis engine. Open the <a href="https://trajectiers.vercel.app/">hosted dashboard</a> or run <code>python3 -m atif.cli serve</code>.');
})();
