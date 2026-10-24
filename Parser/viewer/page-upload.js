/* Upload page (upload.html): add logs, as a dataset folder or as files.
 *
 * A folder follows <dataset>/<bug>/<agent>/run<n>/<files> (TV.uploads.scan): the folders say
 * which bug, agent and run each trajectory is, so nothing is asked but what is already there.
 * An optional CSV anywhere in it gives the outcomes (bug, agent, outcome; TV.uploads.
 * readOutcomes). The page lists the runs found, and a run that is already on the Corpus
 * Overview (the same bug, agent and run, or the same file uploaded before) waits for the user's choice:
 * replace that run, or add this one as the cell's next run. Only then are the runs analysed;
 * in each run folder the first file the engine reads is the trajectory (TV.uploads.addRun).
 *
 * Files cannot say how they are related, so the user says it:
 *   Separate                  each upload stands alone (analyze.html#u=<id>), as before
 *   One bug, several agents   a comparison group of kind 'agents': the agents side by side
 *   One agent, several runs   a comparison group of kind 'runs': one agent's runs, numbered
 * Files are analysed (and kept) as soon as they are added, so the page can show what each is
 * (agent, model, bug named in the log, actions) and check the choice: one agent only for
 * 'runs', distinct run numbers, one bug for the whole group. A file whose run is already in
 * the table waits for the same choice as a folder's. Saving writes the group and the run in
 * the table (slot) onto each member's record (uploads.js), analyses again the members whose
 * bug id changed, and opens the group (analyze.html#g=<id>, with the Fingerprint tab).
 * upload.html#g=<id> edits an existing group; files can be added to it. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$;
  var D = window.TRAJ_OVERVIEW;
  if (D && D.vocab) TV.vocab = D.vocab;
  var ITEMS = [];            // files: [{rec, isNew, run, outcome, clash, choice}]
  var REMOVED = [];          // members taken out of an edited group
  var KIND = 'none', touched = false, GID = null;
  var FOLDER = null;         // a folder: {name, scan, csvs: [names used], items: [{run, outcome, clash, choice, slot}]}
  var EXISTING = [];         // the uploads already kept (but the ones on this page)

  function busy(text) { $('#busy').hidden = !text; $('#busyText').textContent = text || ''; }
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }
  function agentOf(r) { return TV.uploads.agent(r); }
  function bugOf(r) { return TV.uploads.bug(r); }
  function uniq(xs) { return xs.filter(function (x, k) { return x && xs.indexOf(x) === k; }); }
  function typedBug() { return TV.bugKey($('#gBug').value); }
  function noEngine() {
    status('warn', 'Uploading needs the analysis engine. Open the <a href="https://inceptor-tool.vercel.app/">hosted dashboard</a> or run <code>python3 -m atif.cli serve</code>.');
  }
  /* the uploads kept, without the ones this page holds */
  function loadExisting() {
    return TV.uploads.list().then(function (xs) {
      var mine = ITEMS.map(function (it) { return it.rec.id; });
      EXISTING = xs.filter(function (r) { return r && r.result && r.result.trajectory && mine.indexOf(r.id) < 0; });
    });
  }

  /* ---------------------------------------------------------------- already there? */
  /* the choice for a run that is already in the table, and the run each choice gives */
  function choiceHTML(it, key) {
    if (!it.clash) return '<span class="muted">–</span>';
    var c = it.clash, what = c.same ? 'The same file is already uploaded' + (c.bug ? ' (' + TV.bugName(c.bug) + ' · ' + c.agent + ' · run ' + c.run + ')' : '') :
      'Run ' + c.run + ' of ' + TV.bugName(c.bug) + ' · ' + c.agent + ' is already uploaded (' + (c.rec ? c.rec.name : '') + ')';
    return '<span class="clash"><span class="clash-w" data-tip="' + esc(what) + '">already there</span><span class="seg small" role="group" aria-label="' + esc(what) + '">' +
      '<button type="button" data-choice="replace" data-k="' + key + '" aria-pressed="' + (it.choice === 'replace') + '" data-tip="' + esc((c.same ? 'delete the earlier upload and keep this one' : 'this one takes run ' + c.run) + '') + '">Replace</button>' +
      '<button type="button" data-choice="add" data-k="' + key + '" aria-pressed="' + (it.choice === 'add') + '" data-tip="keep both: this one becomes the next run">Add as run ' + (it.addRun || 'n+1') + '</button></span></span>';
  }
  /* where each item goes: no clash or 'replace', its own run; 'add', after the cell's last
   * run (counting the runs placed before it). items: [{bug, agent, run, clash, choice}] */
  function placeAll(items) {
    var L = TV.uploads.layout(null, EXISTING), occ = {};
    function runsOf(bug, agent) {
      var k = bug + '\u0001' + agent;
      if (!occ[k]) {
        occ[k] = {};
        var c = L.cells[k];
        if (c) Object.keys(c.runs).forEach(function (r) { occ[k][r] = 1; });
      }
      return occ[k];
    }
    items.forEach(function (it) {
      it.slot = null;
      var c = it.clash;
      if (c && c.same && it.choice === 'replace' && c.bug === it.bug && c.agent === it.agent) {
        it.slot = c.run;                                  // the same file again: it takes the earlier upload's run
        runsOf(it.bug, it.agent)[c.run] = 1;
      } else if (!c || it.choice !== 'add') {
        it.slot = it.run;
        if (it.bug && it.agent && it.run) runsOf(it.bug, it.agent)[it.run] = 1;
      }
    });
    items.forEach(function (it) {
      if (!it.clash) return;
      var o = runsOf(it.bug || it.clash.bug, it.agent || it.clash.agent), n = 0;
      Object.keys(o).forEach(function (r) { n = Math.max(n, +r); });
      it.addRun = n + 1;
      if (it.choice === 'add') { it.slot = n + 1; o[n + 1] = 1; }
    });
  }
  function undecided(items) { return items.filter(function (it) { return it.clash && !it.choice; }).length; }

  /* ================================================================ a folder */
  function readFolder(files) {
    if (ITEMS.length) { status('warn', 'Save or discard the files below before adding a folder.'); return; }
    status('', '');
    var sc = TV.uploads.scan(files);
    if (!sc.runs.length) {
      status('warn', '<b>No run folders found.</b> A folder is read as <code>&lt;dataset&gt;/&lt;bug&gt;/&lt;agent&gt;/run1/&lt;log&gt;</code>, with <code>run2</code>, <code>run3</code>… beside <code>run1</code>' +
        (sc.ignored.length ? ' (' + TV.plural(sc.ignored.length, 'file') + ' skipped, e.g. ' + esc(sc.ignored.slice(0, 2).join(', ')) + ')' : '') + '.');
      return;
    }
    busy('Reading the folder…');
    var name = sc.dataset || (sc.runs[0].path.split('/')[0]) || 'folder';
    Promise.all([loadExisting()].concat(sc.csvs.map(function (f) {
      return f.text().then(function (t) { return { name: f.name, rows: TV.uploads.readOutcomes(t) }; }, function () { return { name: f.name, rows: null }; });
    }))).then(function (res) {
      var tables = res.slice(1), rows = [];
      tables.forEach(function (x) { if (x.rows) rows = rows.concat(x.rows); });
      FOLDER = { name: name, scan: sc, csvs: tables.filter(function (x) { return x.rows; }).map(function (x) { return x.name; }),
        badCsvs: tables.filter(function (x) { return !x.rows; }).map(function (x) { return x.name; }),
        items: sc.runs.map(function (r) {
          return { src: r, bug: r.bug, agent: r.agent, run: r.run, outcome: TV.uploads.outcomeOf(rows, r.bug, r.agent, r.run), clash: null, choice: '' };
        }) };
      return findSameFiles(FOLDER.items);
    }).then(function () {
      busy('');
      folderClashes();
      renderFolder();
    }, function (err) { busy(''); status('warn', 'The folder could not be read: ' + esc(err.message)); });
  }
  /* a file of the same size as one kept is read and compared (a hash) */
  function findSameFiles(items) {
    var sizes = {};
    EXISTING.forEach(function (r) { if (r.hash) sizes[r.size] = 1; });
    return items.reduce(function (p, it) {
      return p.then(function () {
        var f = it.src.files.filter(function (x) { return sizes[x.size]; })[0];
        if (!f) return;
        return f.text().then(function (t) { it.hash = TV.uploads.hash(t); });
      });
    }, Promise.resolve());
  }
  function folderClashes() {
    var L = TV.uploads.layout(null, EXISTING);
    FOLDER.items.forEach(function (it) {
      it.clash = TV.uploads.clash(L, EXISTING, { bug: it.bug, agent: it.agent, run: it.run, hash: it.hash });
      if (!it.clash) it.choice = '';
    });
    placeAll(FOLDER.items);
  }
  function renderFolder() {
    $('#fcfg').hidden = !FOLDER;
    $('#drop').classList.toggle('compact', !!(FOLDER || ITEMS.length));
    if (!FOLDER) return;
    var F = FOLDER, items = F.items;
    var bugs = uniq(items.map(function (it) { return it.bug || '?'; })), ags = uniq(items.map(function (it) { return it.agent || '?'; }));
    var nOut = items.filter(function (it) { return it.outcome != null; }).length, nClash = items.filter(function (it) { return it.clash; }).length;
    $('#fHead').innerHTML = '<h2><span class="fold-i" aria-hidden="true">&#128193;</span>' + esc(F.name) + '</h2><span class="muted">' +
      [TV.plural(bugs.length, 'bug'), TV.plural(ags.length, 'agent'), TV.plural(items.length, 'run')].join(' · ') + '</span>';
    var notes = [];
    notes.push(F.csvs.length ? 'Outcomes from <b>' + esc(F.csvs.join(', ')) + '</b>: ' + nOut + ' of ' + items.length + ' runs.' :
      'No outcome file: the external validation of the runs shows as unknown until you set it. A CSV with the columns <code>bug</code>, <code>agent</code> and <code>outcome</code> (pass / fail: the benchmark\'s verdict on the final patch) gives it.');
    if (F.badCsvs.length) notes.push(esc(F.badCsvs.join(', ')) + ': no <code>bug</code> and <code>outcome</code> columns, so not read.');
    if (F.scan.ignored.length) notes.push('<span data-tip="' + esc(F.scan.ignored.slice(0, 12).join('\n') + (F.scan.ignored.length > 12 ? '\n…' : '')) + '">' + TV.plural(F.scan.ignored.length, 'file') + ' outside run folders skipped.</span>');
    if (items.some(function (it) { return !it.bug || !it.agent; })) notes.push('Where a bug or agent folder is missing, the log names it.');
    $('#fNotes').innerHTML = notes.map(function (n) { return '<p>' + n + '</p>'; }).join('');
    var h = '<div class="ufrow head frun" role="row"><span>Bug</span><span>Agent</span><span>Run</span><span>Files</span><span>External validation</span><span>' +
      (nClash ? 'Already there <span class="bulk"><button type="button" class="linkbtn" data-all="replace">replace all</button> · <button type="button" class="linkbtn" data-all="add">add all</button></span>' : '') + '</span></div>';
    items.forEach(function (it, k) {
      var fs = it.src.files;
      h += '<div class="ufrow frun' + (it.clash ? ' hasclash' : '') + '" role="row">' +
        '<span class="mono">' + (it.bug ? esc(TV.bugName(it.bug)) : '<span class="muted">from the log</span>') + '</span>' +
        '<span>' + (it.agent ? TV.agentHTML(it.agent) : '<span class="muted">from the log</span>') + '</span>' +
        '<span class="num">' + it.run + (it.slot && it.slot !== it.run ? ' <span class="muted small">→ ' + it.slot + '</span>' : '') + '</span>' +
        '<span class="uf-name" data-tip="' + esc(fs.map(function (f) { return f.name + ' · ' + TV.uploads.sizeLabel(f.size); }).join('\n')) + '"><b>' + esc(fs[0].name) + '</b>' +
          (fs.length > 1 ? '<span class="muted small">+' + (fs.length - 1) + ' more; the first the engine reads is the trajectory</span>' : '') + '</span>' +
        '<span>' + TV.markHTML(it.outcome, it.outcome == null ? 'no outcome in the CSV' : 'from the CSV') + '</span>' +
        '<span>' + choiceHTML(it, k) + '</span></div>';
    });
    $('#fTable').innerHTML = h;
    var left = undecided(items);
    $('#fMsg').innerHTML = left ? '<span class="bad">' + TV.plural(left, 'run') + ' already in the table: choose Replace or Add for each.</span>' : '';
    $('#fSave').disabled = !!left;
    $('#fSave').textContent = 'Add ' + TV.plural(items.length, 'run') + ' to the table';
  }
  $('#fTable').addEventListener('click', function (e) {
    var b = e.target.closest('[data-choice]'), all = e.target.closest('[data-all]');
    if (b) FOLDER.items[+b.dataset.k].choice = b.dataset.choice;
    else if (all) FOLDER.items.forEach(function (it) { if (it.clash) it.choice = all.dataset.all; });
    else return;
    placeAll(FOLDER.items);
    renderFolder();
  });
  $('#fDiscard').addEventListener('click', function () { FOLDER = null; renderFolder(); status('', ''); });
  $('#fSave').addEventListener('click', function () {
    if (!FOLDER || undecided(FOLDER.items)) return;
    if (!TV.engine.usable()) { noEngine(); return; }
    var F = FOLDER, rs = TV.ruleset.get(), failed = [], added = 0, n = F.items.length;
    busy('Loading the analysis engine…');
    TV.engine.start().then(function () {
      return F.items.reduce(function (p, it, k) {
        return p.then(function () {
          busy('Analysing ' + (k + 1) + ' of ' + n + ': ' + [it.bug ? TV.bugName(it.bug) : '', it.agent, 'run ' + it.run].filter(Boolean).join(' · ') + '…');
          return TV.uploads.addRun(it.src, rs, { bug: it.bug || null, agent: it.agent || null, slot: it.slot, outcome: it.outcome, dataset: F.name }).then(function () {
            added++;
            if (it.clash && it.choice === 'replace' && it.clash.rec) return TV.uploads.remove([it.clash.rec.id]);
          }, function (err) {
            if (!err || !err.answered) throw err;           // the engine stopped: give up
            failed.push({ name: it.src.path, error: err.message });
          });
        });
      }, Promise.resolve());
    }).then(function () {
      busy('');
      if (!failed.length) { location.href = 'index.html'; return; }
      FOLDER = null;
      renderFolder();
      status('warn', '<b>' + added + ' of ' + TV.plural(n, 'run') + ' added; ' + failed.length + ' could not be read.</b> ' +
        failed.slice(0, 8).map(function (f) { return esc(f.name) + ': ' + esc(f.error); }).join(' · ') + (failed.length > 8 ? ' · …' : '') +
        ' <a href="index.html">Open the Corpus Overview</a>');
    }, function (err) {
      busy('');
      status('warn', 'The analysis engine could not start: ' + esc((err && err.message) || err) + (added ? '. ' + added + ' runs were added.' : ''));
    });
  });

  /* ================================================================ files */
  /* ---------------------------------------------------------------- what the files look like */
  function guessKind() {
    if (ITEMS.length < 2) return 'none';
    var ags = uniq(ITEMS.map(function (it) { return agentOf(it.rec); }));
    if (ags.length === 1) return 'runs';
    return ags.length === ITEMS.length ? 'agents' : 'none';
  }
  function defaultName() {
    var bug = typedBug() || uniq(ITEMS.map(function (it) { return bugOf(it.rec); }))[0];
    var head = bug ? TV.bugName(bug) : 'Comparison';
    return head + ' · ' + (KIND === 'runs' ? agentOf(ITEMS[0].rec) + ', ' + ITEMS.length + ' runs' : ITEMS.length + ' agents');
  }
  /* each file's run already in the table, under the current choice */
  function fileClashes() {
    var L = TV.uploads.layout(null, EXISTING), group = KIND !== 'none';
    ITEMS.forEach(function (it) {
      var r = it.rec, bug = (group && typedBug()) || bugOf(r), run = KIND === 'runs' ? it.run : null;
      if (KIND !== 'runs' && r.slot) run = r.slot;
      it.bug = bug; it.agent = agentOf(r);
      var c = TV.uploads.clash(L, EXISTING, { bug: bug, agent: it.agent, run: run, hash: r.hash, id: r.id });
      if (!c) it.choice = '';
      it.clash = c;
    });
    var xs = ITEMS.map(function (it) { return { bug: it.bug, agent: it.agent, run: KIND === 'runs' ? it.run : it.rec.slot || null, clash: it.clash, choice: it.choice, item: it }; });
    placeAll(xs);
    xs.forEach(function (x) { x.item.slot = x.slot; x.item.addRun = x.addRun; });
  }
  /* {errors, notes} of the current choice */
  function check() {
    var errors = [], notes = [];
    fileClashes();
    var left = undecided(ITEMS);
    if (left) errors.push(TV.plural(left, 'file') + ' already in the table: choose Replace or Add for each.');
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
    var bugs = uniq(ITEMS.map(function (it) { return String(bugOf(it.rec)); }));
    if (!typedBug() && bugs.length > 1) errors.push('The logs name different bugs (' + bugs.map(TV.bugName).join(', ') + '). Type the bug they all repair.');
    else if (typedBug() && bugs.some(function (b) { return b !== typedBug(); })) notes.push('All files will be read as ' + TV.bugName(typedBug()) + '.');
    return { errors: errors, notes: notes };
  }

  /* ---------------------------------------------------------------- render */
  function outcomeSeg(it, k) {
    var cur = it.outcome === true ? 'pass' : it.outcome === false ? 'fail' : '';
    return '<span class="seg small" role="group" aria-label="External validation">' + [['', '?'], ['pass', 'passed'], ['fail', 'failed']].map(function (o) {
      return '<button type="button" data-oc="' + o[0] + '" data-k="' + k + '" aria-pressed="' + (cur === o[0]) + '"' + (o[0] ? '' : ' title="unknown"') + '>' + o[1] + '</button>';
    }).join('') + '</span>';
  }
  function render() {
    $('#cfg').hidden = !ITEMS.length;
    $('#drop').classList.toggle('compact', !!(FOLDER || ITEMS.length));
    if (!ITEMS.length) return;
    var group = KIND !== 'none', c = check(), clashCol = ITEMS.some(function (it) { return it.clash; });
    $('#kinds').hidden = ITEMS.length < 2 && !GID;
    document.querySelectorAll('#kinds input').forEach(function (r) { r.checked = r.value === KIND; r.closest('.relopt').classList.toggle('on', r.checked); });
    $('#grpFields').hidden = !group;
    $('#gName').placeholder = defaultName();
    var cls = (KIND === 'runs' ? ' runs' : '') + (clashCol ? ' clashes' : '');
    var h = '<div class="ufrow head' + cls + '" role="row"><span>File</span><span>Agent</span><span>Bug in log</span><span>Actions</span>' + (KIND === 'runs' ? '<span>Run</span>' : '') +
      '<span>External validation</span>' + (clashCol ? '<span>Already there</span>' : '') + '<span></span></div>';
    ITEMS.forEach(function (it, k) {
      var r = it.rec, t = (r.result || {}).trajectory || {}, model = TV.uploads.model(r), bug = bugOf(r);
      h += '<div class="ufrow' + cls + '" role="row">' +
        '<span class="uf-name"><b>' + esc(r.name) + '</b><span class="muted small">' + esc(TV.uploads.formatLabel(((r.result || {}).source || {}).format)) + ' · ' + TV.uploads.sizeLabel(r.size || 0) + '</span></span>' +
        '<span>' + TV.agentHTML(agentOf(r)) + (model ? '<span class="muted small mono uf-model">' + esc(model) + '</span>' : '') + '</span>' +
        '<span>' + (bug ? esc(TV.bugName(bug)) : '<span class="muted">–</span>') + '</span>' +
        '<span class="num">' + (t.n_actions || 0) + '</span>' +
        (KIND === 'runs' ? '<span><input class="uf-run" type="number" min="1" step="1" value="' + esc(it.run) + '" data-run="' + k + '" aria-label="Run number of ' + esc(r.name) + '"></span>' : '') +
        '<span>' + outcomeSeg(it, k) + '</span>' +
        (clashCol ? '<span>' + choiceHTML(it, k) + '</span>' : '') +
        '<span><button type="button" class="btn ghost icon small" data-rm="' + k + '" title="Remove" aria-label="Remove ' + esc(r.name) + '">✕</button></span></div>';
    });
    $('#files').innerHTML = h;
    validate(c);
  }
  function validate(c) {
    c = c || check();
    $('#msg').innerHTML = c.errors.map(function (e) { return '<span class="bad">' + esc(e) + '</span>'; }).concat(c.notes.map(function (n) { return '<span>' + esc(n) + '</span>'; })).join('');
    var save = $('#save');
    save.disabled = !!c.errors.length;
    save.textContent = KIND !== 'none' ? 'Save and compare' : ITEMS.length === 1 ? 'Open' : 'Save';
    $('#discard').textContent = GID ? 'Cancel' : 'Discard';
  }

  /* ---------------------------------------------------------------- adding files */
  function addFiles(files) {
    if (!files || !files.length) return;
    if (FOLDER) { status('warn', 'Add or discard the folder below before adding files.'); return; }
    if (!TV.engine.usable()) { noEngine(); return; }
    status('', '');
    TV.addUploads(files, busy, function (added, failed) {
      added.forEach(function (rec) {
        var used = ITEMS.map(function (it) { return it.run; }), n = 1;
        while (used.indexOf(n) >= 0) n++;
        ITEMS.push({ rec: rec, isNew: true, run: n, outcome: null, clash: null, choice: '' });
      });
      if (!touched) KIND = guessKind();
      if (!$('#gBug').value) { var bugs = uniq(ITEMS.map(function (it) { return String(bugOf(it.rec)); })); if (bugs.length === 1) $('#gBug').value = bugs[0]; }
      if (failed.length) status('warn', '<b>' + TV.plural(failed.length, 'file') + ' could not be read.</b> ' + failed.map(function (f) { return esc(f.name) + ': ' + esc(f.error); }).join(' · '));
      render();
    }, { bug: KIND !== 'none' ? typedBug() || null : null });
  }
  var picker = $('#file'), folderPicker = $('#folderIn');
  $('#pick').addEventListener('click', function () { picker.click(); });
  $('#pickDir').addEventListener('click', function () { folderPicker.click(); });
  picker.addEventListener('change', function () { addFiles(picker.files); picker.value = ''; });
  folderPicker.addEventListener('change', function () {
    var fs = Array.prototype.slice.call(folderPicker.files || []);
    fs.forEach(function (f) { f.relPath = f.webkitRelativePath || f.name; });
    folderPicker.value = '';
    readFolder(fs);
  });

  /* a drop: files, or a folder (read through its entries, with their paths) */
  function walk(entry) {
    if (entry.isFile) return new Promise(function (resolve) {
      entry.file(function (f) { f.relPath = entry.fullPath.replace(/^\/+/, ''); resolve([f]); }, function () { resolve([]); });
    });
    var reader = entry.createReader(), all = [];
    return new Promise(function (resolve) {
      (function more() {
        reader.readEntries(function (xs) {
          if (!xs.length) { Promise.all(all.map(walk)).then(function (ls) { resolve([].concat.apply([], ls)); }); return; }
          all = all.concat(Array.prototype.slice.call(xs));
          more();
        }, function () { resolve([]); });
      })();
    });
  }
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
      if (k !== 'drop' || !e.dataTransfer) return;
      var entries = Array.prototype.map.call(e.dataTransfer.items || [], function (it) { return it.webkitGetAsEntry ? it.webkitGetAsEntry() : null; }).filter(Boolean);
      if (entries.some(function (x) { return x.isDirectory; })) {
        e.preventDefault();
        busy('Reading the folder…');
        Promise.all(entries.map(walk)).then(function (ls) { busy(''); readFolder([].concat.apply([], ls)); });
        return;
      }
      if (e.dataTransfer.files && e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files); }
    });
  });

  /* ---------------------------------------------------------------- editing the choice */
  $('#kinds').addEventListener('change', function (e) {
    if (!e.target.name) return;
    KIND = e.target.value;
    touched = true;
    render();
  });
  $('#gBug').addEventListener('input', function () { $('#gName').placeholder = defaultName(); render(); });
  $('#files').addEventListener('change', function (e) {
    var k = e.target.dataset.run;
    if (k == null) return;
    ITEMS[+k].run = +e.target.value;
    render();
  });
  $('#files').addEventListener('click', function (e) {
    var oc = e.target.closest('[data-oc]');
    if (oc) {
      ITEMS[+oc.dataset.k].outcome = oc.dataset.oc === 'pass' ? true : oc.dataset.oc === 'fail' ? false : null;
      render();
      return;
    }
    var ch = e.target.closest('[data-choice]');
    if (ch) { ITEMS[+ch.dataset.k].choice = ch.dataset.choice; render(); return; }
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
    var replaced = ITEMS.filter(function (it) { return it.clash && it.choice === 'replace' && it.clash.rec; }).map(function (it) { return it.clash.rec.id; });
    busy('Saving…');
    var steps = ITEMS.map(function (it) {
      return function () {
        var r = it.rec;
        r.outcome = it.outcome;
        if (r.result && r.result.trajectory) r.result.trajectory.outcome = { pass: it.outcome, by_run: { 1: it.outcome } };
        if (meta) r.group = meta; else delete r.group;
        if (KIND === 'runs') r.run = it.run; else delete r.run;
        /* its run in the table: the one given, or after the cell's last run */
        var slot = it.slot;
        if (!slot && it.bug) {
          var L = TV.uploads.layout(null, EXISTING.concat(ITEMS.map(function (x) { return x.rec; }).filter(function (x) { return x.slot && x !== r; })));
          slot = TV.uploads.nextRun(L, it.bug, it.agent);
        }
        if (slot) r.slot = slot; else delete r.slot;
        if (group && bug && String(r.bug || '') !== bug) {
          r.bug = bug;
          busy('Analysing ' + r.name + ' as ' + TV.bugName(bug) + '…');
          return TV.uploads.reanalyze(r);
        }
        return TV.uploads.save(r);
      };
    }).concat(REMOVED.map(function (r) { return function () { delete r.group; delete r.run; return TV.uploads.save(r); }; }))
      .concat([function () { return TV.uploads.remove(replaced); }]);
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
      ITEMS = g.members.map(function (r) { return { rec: r, isNew: false, run: r.run || 1, outcome: r.outcome == null ? null : r.outcome, clash: null, choice: '' }; });
      $('#gBug').value = uniq(g.members.map(function (r) { return String(bugOf(r)); })).length === 1 ? bugOf(g.members[0]) : '';
      $('#gName').value = g.name || '';
      $('#upTitle').textContent = 'Edit comparison';
      document.title = 'Edit comparison · Inceptor';
      return loadExisting().then(render);
    });
  } else loadExisting();
  if (!TV.engine.usable()) noEngine();
})();
