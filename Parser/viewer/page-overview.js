/* Corpus page (index.html): one table of bugs x agents, built from the user's uploads
 * (uploads.js), all analysed with the one table file of tables.html. It opens with the
 * example dataset (TV.uploads.seed: 25 bugs, 3 agents, 3 runs) and grows with every dataset
 * folder or log the user uploads; when every bug was deleted it offers the example again.
 *
 * Trajectories tab: search (a bug id matches that bug exactly; any other text, a bug name or
 * a file name), an Agent filter and an External validation filter, the legend (phases, the
 * agent's self-validation and the benchmark's external validation kept apart) and the table. A row is a bug, a column an agent, both in the order they were
 * first uploaded, so a new bug is added at the bottom and a new agent at the right. A cell
 * shows one run's strips (run 1, else its first run) and a dot per run (TV.uploads.layout: an
 * upload is the cell's next run, or replaces a run the user chose to replace); a dot opens its
 * run. Rows have checkboxes: the selected bugs' uploads can be deleted. Statistics tab:
 * view-stats.js over the same trajectories, by agent. data/overview.js gives only the
 * vocabularies (the legend's words). */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var D = window.TRAJ_OVERVIEW;
  TV.vocab = (D && D.vocab) || {};
  var RUN = 1;
  var RS = TV.ruleset.get(), RKEY = TV.ruleset.key(RS);
  TV.watchRules(RKEY);

  /* ---------------------------------------------------------------- data */
  var UP = [];                       // upload records, each with .sum (TV.uploads.summary)
  var COLS = [];                     // the table's agents, in the order they were first uploaded
  var ROWS = [];                     // one per bug, in the order it was first uploaded: {bug, label, noBug, ups, first, cells: {agent: cell}, agents, pass, nTotal, fails, disagree}
  var BYBUG = {};
  var LAY = null;                    // TV.uploads.layout
  var maxN = 1;
  var loaded = false;                // the uploads have been read
  /* a cell: its runs (number -> {pass, rec}), the run its strips show and that run's summary */
  function cellOf(c) {
    var runs = Object.keys(c.runs).map(Number).sort(function (x, y) { return x - y; });
    var shown = c.runs[RUN] ? RUN : runs[0], x = c.runs[shown];
    return { agent: c.agent, runs: runs, at: c.runs, shown: shown, sum: x.rec.sum, pass: x.pass, rec: x.rec };
  }
  function prep() {
    LAY = TV.uploads.layout(null, UP);
    var byAdded = UP.slice().sort(function (a, b) { return String(a.added).localeCompare(String(b.added)); });
    COLS = [];
    BYBUG = {};
    ROWS = [];
    byAdded.forEach(function (r, k) {
      var at = LAY.at[r.id];
      if (!at) return;
      if (COLS.indexOf(at.agent) < 0) COLS.push(at.agent);
      var row = BYBUG[at.bug];
      if (!row) {
        var noBug = at.bug.charAt(0) === '~';
        row = BYBUG[at.bug] = { bug: at.bug, label: noBug ? r.name : TV.bugName(at.bug), noBug: noBug, ups: [], first: k, cells: {} };
        ROWS.push(row);
      }
      row.ups.push(r);
    });
    Object.keys(LAY.cells).forEach(function (k) {
      var c = LAY.cells[k], row = BYBUG[c.bug];
      if (row) row.cells[c.agent] = cellOf(c);
    });
    maxN = 1;
    ROWS.forEach(function (row) {
      row.pass = {};
      row.nTotal = 0;
      row.fails = 0;
      row.agents = COLS.filter(function (a) { return row.cells[a]; });
      row.agents.forEach(function (a) {
        var c = row.cells[a];
        row.pass[a] = c.pass;
        maxN = Math.max(maxN, c.sum.n_actions || 0);
        row.nTotal += c.sum.n_actions || 0;
        c.runs.forEach(function (r) { if (c.at[r].pass === false) row.fails++; });
      });
      var known = row.agents.map(function (a) { return row.pass[a]; }).filter(function (x) { return x != null; });
      row.disagree = known.some(function (x) { return x !== known[0]; });
    });
  }
  /* where an upload opens: its bug's runs side by side when there are several, else itself */
  function upHref(rec) {
    var at = LAY && LAY.at[rec.id], row = at && BYBUG[at.bug];
    return row && !row.noBug && row.ups.length > 1 ? 'analyze.html#b=' + encodeURIComponent(row.bug) + '&m=' + encodeURIComponent(rec.id) : 'analyze.html#u=' + encodeURIComponent(rec.id);
  }
  function runHref(row, a, r) { return upHref(row.cells[a].at[r].rec); }

  /* ---------------------------------------------------------------- state */
  var S = { tab: 'list', q: '', ag: '', oc: '', sort: 'added' };
  var SEL = {};
  (function readHash() {
    var h = TV.readHash();
    if (h.tab === 'stats') S.tab = 'stats';
    if (h.q) S.q = h.q;
    if (h.ag) S.ag = h.ag;
    if (/^(pass|fail|mixed)$/.test(h.oc || '')) S.oc = h.oc;
    if (/^(bug|actions|failures)$/.test(h.sort || '')) S.sort = h.sort;
  })();
  function saveHash() {
    TV.writeHash({ tab: S.tab === 'list' ? '' : S.tab, q: S.q, ag: S.ag, oc: S.oc,
      sort: S.sort === 'added' ? '' : S.sort, theme: TV.readHash().theme });
  }

  /* ---------------------------------------------------------------- header + status */
  document.title = 'Corpus Overview · Inceptor trace exploration dashboard';
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }
  function rulesLine(extra) {
    return '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span>' + (extra ? '<span class="rs-x">' + extra + '</span>' : '') +
      '<a class="rs-edit" href="tables.html">Customize the rules</a>';
  }

  /* ---------------------------------------------------------------- filters */
  function rowMatchesQuery(row) {
    return TV.queryMatch(S.q, row.noBug ? null : row.bug, [row.label].concat(row.ups.map(function (r) { return r.name; })));
  }
  function ocOf(row, oc) {
    if (!oc) return true;
    if (oc === 'mixed') {
      if (!S.ag) return row.disagree;
      var c = row.cells[S.ag], v = c ? c.runs.map(function (r) { return c.at[r].pass; }).filter(function (x) { return x != null; }) : [];
      return v.some(function (x) { return x !== v[0]; });
    }
    var want = oc === 'pass', ags = S.ag ? [S.ag] : row.agents;
    return ags.length > 0 && ags.every(function (a) { return row.pass[a] === want; });
  }
  function bugRows(oc) {
    return ROWS.filter(function (row) { return (!S.ag || row.cells[S.ag]) && rowMatchesQuery(row) && ocOf(row, oc); });
  }
  var OC_TIP = {
    all: { '': 'every bug', pass: 'external validation: every agent passed (run 1, or its first run)', fail: 'external validation: every agent failed (run 1, or its first run)', mixed: 'external validation: some agents passed and some failed' },
    one: { '': 'every bug', pass: 'external validation: {a} passed in the run its strips show', fail: 'external validation: {a} failed in the run its strips show', mixed: 'external validation: {a} passed in some runs and failed in others' }
  };
  function renderFilters() {
    if (S.ag && COLS.indexOf(S.ag) < 0 && loaded) S.ag = '';
    $('#agentSeg').innerHTML = [''].concat(COLS).map(function (a) {
      var n = ROWS.filter(function (row) { return row.cells[a]; }).length;
      var tip = a ? a + ': its column only; ' + TV.plural(n, 'bug') : 'all agents side by side';
      return '<button type="button" data-ag="' + esc(a) + '" aria-pressed="' + (S.ag === a) + '" data-tip="' + esc(tip) + '">' + (a ? TV.agentHTML(a) : 'All') + '</button>';
    }).join('');
    $('#ocSeg').innerHTML = [['', 'All'], ['pass', TV.extBox(true) + 'Passed'], ['fail', TV.extBox(false) + 'Failed'], ['mixed', 'Mixed']].map(function (x) {
      var n = bugRows(x[0]).length;
      var tip = (S.ag ? OC_TIP.one : OC_TIP.all)[x[0]].replace('{a}', S.ag);
      return '<button type="button" data-oc="' + x[0] + '" aria-pressed="' + (S.oc === x[0]) + '" data-tip="' + esc(tip) + '">' + x[1] + ' <span class="cnt">' + n + '</span></button>';
    }).join('');
    $('#q').value = S.q;
    $('#sort').value = S.sort;
  }

  /* ---------------------------------------------------------------- legend */
  function renderLegend() {
    var sample = function (cls, fill) {
      return '<span class="lg-sample ' + cls + '" aria-hidden="true">' + fill.map(function (f) { return '<i style="background:' + f + '"></i>'; }).join('') + '</span>';
    };
    $('#legend').innerHTML = '<h2 class="lg-title">Legend</h2>' +
      '<div class="lg-row"><span class="lg-k">' + sample('tall', TV.PHASE_ORDER.map(TV.phaseVar)) + '<b>Phase</b><span class="muted">upper strip</span></span>' +
        '<span class="lg-v">' + TV.phaseLegend() + '</span></div>' +
      '<div class="lg-row"><span class="lg-k">' + sample('thin', TV.OUTCOMES.map(TV.outcomeVar)) + '<b>Validation outcome</b><span class="muted">lower strip · self-validation by the agent</span></span>' +
        '<span class="lg-v">' + TV.outcomeLegend() + '</span></div>' +
      (function (r) { return '<div class="lg-row"><span class="lg-k"><b>' + r[0] + '</b><span class="muted">' + r[1] + '</span></span><span class="lg-v">' + r[2] + '</span></div>'; })(TV.externalLegendRow(true));
  }

  /* ---------------------------------------------------------------- the table */
  function stripCell(s, max) {
    return '<span class="track">' + TV.stripsHTML(s.strip, s.sub_strip, s.n_actions, max * 1.04) +
      '<span class="an" data-tip="' + esc(TV.plural(s.n_actions, 'step')) + '">' + s.n_actions + '</span></span>';
  }
  /* the external validation of each run (a green, red or grey box), each a link to its run */
  function runMarksHTML(row, c) {
    var desc = c.runs.map(function (r) { var x = c.at[r]; return 'run ' + r + ' (' + x.rec.name + '): ' + TV.EXTERNAL_WORD[TV.oc(x.pass)]; }).join('\n');
    return '<span class="rdots" data-tip="' + esc(c.agent + ' · external validation\n' + desc) + '">' + c.runs.map(function (r) {
      var x = c.at[r];
      return '<a class="xbox ' + TV.oc(x.pass) + '" href="' + runHref(row, c.agent, r) + '" aria-label="' + esc(c.agent + ' run ' + r + ': external validation ' + TV.EXTERNAL_WORD[TV.oc(x.pass)]) + '"></a>';
    }).join('') + '</span>';
  }
  function cellHTML(row, a, single) {
    var c = row.cells[a];
    var lbl = '<span class="alabel">' + TV.agentHTML(a) + '</span>';
    if (!c) return '<span class="acell blank" data-agent="' + esc(a) + '" role="cell">' + lbl + '</span>';
    return '<span class="acell" data-agent="' + esc(a) + '" data-run="' + c.shown + '" role="cell">' + lbl +
      stripCell(c.sum, single ? Math.max.apply(null, ROWS.map(function (x) { return x.cells[a] ? x.cells[a].sum.n_actions || 0 : 0; })) : maxN) +
      runMarksHTML(row, c) + '</span>';
  }
  function bugCell(row) {
    var href = row.noBug || row.ups.length === 1 ? 'analyze.html#u=' + encodeURIComponent(row.ups[0].id) : 'analyze.html#b=' + encodeURIComponent(row.bug);
    return '<a class="bid' + (row.noBug ? ' nobug' : '') + '" role="cell" href="' + href + '" title="' + esc(row.noBug ? row.label + ': no bug id in the log' : row.label) + '">' + esc(row.label) + '</a>';
  }
  function renderBugs() {
    var single = !!S.ag, cols = single ? [S.ag] : COLS;
    var rows = bugRows(S.oc);
    var nOf = function (row) { return single ? ((row.cells[S.ag] || {}).sum || {}).n_actions || 0 : row.nTotal; };
    var failsOf = function (row) { var c = row.cells[S.ag]; return single ? (c ? c.runs.filter(function (r) { return c.at[r].pass === false; }).length : 0) : row.fails; };
    var byBug = function (x, y) { return (x.noBug ? 1 : 0) - (y.noBug ? 1 : 0) || TV.bugSort(x.bug, y.bug); };
    if (S.sort === 'bug') rows.sort(byBug);
    else if (S.sort === 'actions') rows.sort(function (x, y) { return nOf(y) - nOf(x) || x.first - y.first; });
    else if (S.sort === 'failures') rows.sort(function (x, y) { return failsOf(y) - failsOf(x) || x.first - y.first; });
    var nsel = Object.keys(SEL).length;
    $('#bugActs').innerHTML = nsel ? '<span class="muted small">' + nsel + ' selected</span><button class="btn small danger" type="button" data-act="delete" title="Delete the selected bugs\' uploads from this browser">Delete</button>' +
      '<button class="btn ghost small" type="button" data-act="clear">Clear</button>' : '';
    var el = $('#bugs');
    el.style.setProperty('--nag', Math.max(1, cols.length));
    el.classList.toggle('single', single);
    var all = rows.length && rows.every(function (row) { return SEL[row.bug]; });
    var h = '<div class="brow head" role="row"><span class="sel"><input type="checkbox" data-selall="bugs"' + (all ? ' checked' : '') + ' aria-label="Select every bug shown"></span>' +
      '<span role="columnheader">Bug</span>' +
      cols.map(function (a) { return '<span role="columnheader">' + TV.agentHTML(a) + '</span>'; }).join('') + '</div>';
    rows.forEach(function (row) {
      h += '<div class="brow" role="row" data-bug="' + esc(row.bug) + '">' +
        '<span class="sel"><input type="checkbox" data-sel="bugs" value="' + esc(row.bug) + '"' + (SEL[row.bug] ? ' checked' : '') + ' aria-label="Select ' + esc(row.label) + '"></span>' +
        bugCell(row) +
        cols.map(function (a) { return cellHTML(row, a, single); }).join('') + '</div>';
    });
    if (!rows.length) h += '<div class="empty">No bug matches. <button class="btn" type="button" data-reset>Show all</button></div>';
    el.innerHTML = h;
  }
  /* nothing uploaded yet: the page invites a folder */
  var EMPTY = '<div class="card welcome"><h2>No trajectories yet</h2>' +
    '<p>Upload a dataset folder to see its bugs, agents and runs here. A folder is read as <code>&lt;dataset&gt;/&lt;bug&gt;/&lt;agent&gt;/run1/&lt;log&gt;</code>, with an optional CSV of outcomes (bug, agent, outcome); log files can be uploaded too.</p>' +
    '<a class="btn primary" href="upload.html"><span aria-hidden="true">&#8679;</span> Upload a dataset</a> ' +
    '<button class="btn" type="button" data-act="seed" title="25 bugs, each repaired by Claude Code, Codex and Qwen Code in 3 runs">Load the example dataset</button></div>';

  /* ---------------------------------------------------------------- render */
  var statsDirty = true;
  function render() {
    var none = loaded && !ROWS.length;
    $('#tab-list').classList.toggle('isempty', none);
    $('#emptyState').innerHTML = none ? EMPTY : '';
    renderFilters();
    renderBugs();
    $('#tab-list').classList.remove('pending');
    statsDirty = true;
    if (S.tab === 'stats') renderStats();
    saveHash();
  }
  function renderStats() {
    if (!statsDirty || !TV.views.stats) return;
    statsDirty = false;
    if (!ROWS.length) { $('#tab-stats').innerHTML = loaded ? EMPTY : ''; return; }
    var groups = COLS.map(function (a) {
      return { key: a, agent: a, trajs: UP.filter(function (r) { return LAY.at[r.id] && LAY.at[r.id].agent === a; }).map(function (r) { return r.sum; }) };
    });
    var runs = [];
    ROWS.forEach(function (row) { row.agents.forEach(function (a) { row.cells[a].runs.forEach(function (r) { if (runs.indexOf(r) < 0) runs.push(r); }); }); });
    runs.sort(function (x, y) { return x - y; });
    TV.overview = { agents: COLS, runs: runs, rows: ROWS, groups: groups, href: runHref };
    try { TV.views.stats.render($('#tab-stats')); }
    catch (err) { $('#tab-stats').innerHTML = '<p class="note">Statistics error: ' + esc(err && err.message) + '</p>'; if (window.console) console.error(err); }
  }

  /* ---------------------------------------------------------------- events */
  $('#agentSeg').addEventListener('click', function (e) {
    var b = e.target.closest('[data-ag]');
    if (b) { S.ag = b.dataset.ag; render(); }
  });
  $('#ocSeg').addEventListener('click', function (e) {
    var b = e.target.closest('[data-oc]');
    if (b) { S.oc = b.dataset.oc; render(); }
  });
  $('#q').addEventListener('input', function (e) { S.q = e.target.value.trim(); render(); });
  $('#sort').addEventListener('change', function (e) { S.sort = e.target.value; render(); });

  $('#bugs').addEventListener('change', function (e) {
    var box = e.target.closest('input[type="checkbox"]');
    if (!box) return;
    if (box.dataset.selall) $$('input[data-sel="bugs"]').forEach(function (x) { if (box.checked) SEL[x.value] = 1; else delete SEL[x.value]; });
    else if (box.checked) SEL[box.value] = 1; else delete SEL[box.value];
    renderBugs();
  });
  /* a click on a row opens it (a cell: the run its strips show), unless it was on a checkbox or a link of its own */
  $('#bugs').addEventListener('click', function (e) {
    if (e.target.closest('[data-reset]')) { S.q = ''; S.oc = ''; S.ag = ''; render(); return; }
    if (e.target.closest('.sel, a')) return;
    var el = e.target.closest('.brow[data-bug]');
    var row = el && BYBUG[el.dataset.bug];
    if (!row) return;
    var cell = e.target.closest('.acell[data-run]');
    if (cell) { location.href = runHref(row, cell.dataset.agent, +cell.dataset.run); return; }
    var link = el.querySelector('a.bid');
    if (link) location.href = link.getAttribute('href');
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.dataset.act === 'clear') { SEL = {}; renderBugs(); return; }
    if (b.dataset.act === 'seed') { loadExample(b); return; }
    if (b.dataset.act !== 'delete') return;
    var bugs = Object.keys(SEL), ids = [];
    bugs.forEach(function (k) { (BYBUG[k] ? BYBUG[k].ups : []).forEach(function (r) { ids.push(r.id); }); });
    if (!ids.length || !window.confirm('Delete ' + TV.plural(bugs.length, 'bug') + ' (' + TV.plural(ids.length, 'run') + ') from this browser? This cannot be undone.')) return;
    TV.uploads.remove(ids).then(function () {
      UP = UP.filter(function (r) { return ids.indexOf(r.id) < 0; });
      SEL = {};
      prep();
      render();
    });
  });

  /* ---------------------------------------------------------------- tabs, keys */
  function setTab(tab, quiet) {
    S.tab = tab;
    $$('.tabs [data-tab]').forEach(function (b) { b.setAttribute('aria-selected', b.dataset.tab === tab ? 'true' : 'false'); });
    $('#tab-list').hidden = tab !== 'list';
    $('#tab-stats').hidden = tab !== 'stats';
    if (tab === 'stats' && !quiet) renderStats();
    saveHash();
  }
  $$('.tabs [data-tab]').forEach(function (b) { b.addEventListener('click', function () { setTab(b.dataset.tab); }); });
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea' || e.metaKey || e.ctrlKey || e.altKey) {
      if (e.key === 'Escape' && tag === 'input') e.target.blur();
      return;
    }
    if (e.key === '/') { e.preventDefault(); setTab('list'); $('#q').focus(); }
    else if (e.key === '1') setTab('list');
    else if (e.key === '2') setTab('stats');
    else if (e.key === 'Escape') $('#help').hidden = true;
    else if (e.key === '?') $('#help').hidden = !$('#help').hidden;
  });

  /* ---------------------------------------------------------------- the rules: uploads analysed with other tables are analysed again */
  function refreshUploads() {
    var stale = UP.filter(function (r) { return r.rulesKey !== RKEY; });
    if (!stale.length || !TV.engine.usable()) return Promise.resolve(false);
    return TV.uploads.refresh(UP, RS, function (done, total) {
      status('busy', rulesLine('analysing the trajectories again… ' + done + ' / ' + total));
    }).then(function (res) {
      UP.forEach(function (r) { r.sum = TV.uploads.summary(r); });
      prep();
      if (res.failed.length) status('warn', rulesLine(res.failed.length + ' trajectories could not be analysed with these tables: ' + esc(res.failed[0].error)));
      else status(TV.ruleset.isDefault(RS) ? '' : 'ok', TV.ruleset.isDefault(RS) ? '' : rulesLine('applied'));
      return true;
    }, function (err) {
      status('warn', rulesLine('the trajectories could not be analysed again (' + esc(err.message) + ')'));
      return false;
    });
  }

  /* the example dataset again (every bug was deleted) */
  function loadExample(btn) {
    btn.disabled = true;
    status('busy', 'Loading the example dataset…');
    TV.uploads.seed(true).then(function () { return TV.uploads.list(); }).then(function (recs) {
      UP = recs.filter(function (r) { return r && r.result && r.result.trajectory; });
      UP.forEach(function (r) { r.sum = TV.uploads.summary(r); });
      prep();
      status('', '');
      render();
      return refreshUploads();
    }).then(function (changed) { if (changed) render(); }, function (err) {
      btn.disabled = false;
      status('warn', 'The example dataset could not be loaded (' + esc((err && err.message) || err) + ').');
    });
  }

  /* one render, once the uploads are known; again when they were analysed with other tables */
  renderLegend();
  if (!TV.ruleset.isDefault(RS)) status('', rulesLine(''));
  TV.uploads.list().then(function (recs) {
    UP = recs.filter(function (r) { return r && r.result && r.result.trajectory; });
    UP.forEach(function (r) { r.sum = TV.uploads.summary(r); });
    loaded = true;
    prep();
    setTab(S.tab, true);
    render();
    return refreshUploads();
  }).then(function (changed) { if (changed) render(); });
})();
