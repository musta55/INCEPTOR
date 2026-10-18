/* Corpus page (index.html): the corpus overview (run 1 of every bug x agent, from
 * data/overview.js, schema trajview-overview/3) and the user's uploads (uploads.js), all
 * analysed with the one table file of tables.html.
 *
 * Trajectories tab: search (a bug id matches that bug exactly), an Agent filter and an
 * Outcome filter, the legend (phases and phase outcomes kept apart), the uploads table
 * and the corpus table. Rows have checkboxes: corpus bugs can be removed from view (kept in
 * localStorage 'tv-hidden', restorable), uploads deleted. Statistics tab: view-stats.js
 * over the same trajectories: the corpus agents, then the uploads grouped by agent.
 *
 * Under rules other than the default ones, the corpus summaries are re-run from the corpus
 * packs (TV.corpus, cached per rule set) and stale uploads are analysed again. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var D = window.TRAJ_OVERVIEW;
  if (!D || !D.bugs || !D.bugs.length || D.schema !== 'trajview-overview/3') {
    $('#app').hidden = true;
    $('#nodata').hidden = false;
    if (D && D.schema) $('#nodataWhy').textContent = 'The file holds schema ' + D.schema + '; this dashboard reads phases and their outcomes (trajview-overview/3). Regenerate it from the Parser directory:';
    return;
  }
  TV.vocab = D.vocab || {};
  var AG = (D.agents || TV.AGENT_ORDER).slice();
  var RUNS = (D.runs || [1, 2, 3]).slice();
  var RUN = D.run || 1;
  var RS = TV.ruleset.get(), RKEY = TV.ruleset.key(RS);
  TV.watchRules(RKEY);

  /* ---------------------------------------------------------------- removed bugs */
  var HIDE_KEY = 'tv-hidden';
  var hidden = (function () {
    try { var x = JSON.parse(localStorage.getItem(HIDE_KEY) || '[]'); return Array.isArray(x) ? x.map(String) : []; } catch (e) { return []; }
  })();
  function saveHidden() { try { localStorage.setItem(HIDE_KEY, JSON.stringify(hidden)); } catch (e) { /* this visit only */ } }
  function isHidden(b) { return hidden.indexOf(String(b.bug)) >= 0; }

  /* ---------------------------------------------------------------- data */
  var UP = [];                       // upload records, each with .sum (TV.uploads.summary)
  var maxN = 1, maxUp = 1;
  var computing = false;             // corpus summaries are being re-run under the rules
  function prep() {
    maxN = 1;
    D.bugs.forEach(function (b) {
      b.byRun = b.by_run || {};
      b.agents = b.agents || {};
      b.pass = {};
      b.nTotal = 0;
      b.fails = 0;
      AG.forEach(function (a) {
        var t = b.agents[a];
        var br = b.byRun[a] || (t && t.by_run) || {};
        b.byRun[a] = br;
        b.pass[a] = t && t.pass != null ? t.pass : br[RUN];
        if (t) { maxN = Math.max(maxN, t.n_actions || 0); b.nTotal += t.n_actions || 0; }
        RUNS.forEach(function (r) { if (br[r] === false) b.fails++; });
      });
      var known = AG.map(function (a) { return b.pass[a]; }).filter(function (x) { return x != null; });
      b.disagree = known.some(function (x) { return x !== known[0]; });
    });
    maxUp = 1;
    UP.forEach(function (r) { maxUp = Math.max(maxUp, r.sum.n_actions || 0); });
  }
  function upAgents() {
    var seen = {};
    UP.forEach(function (r) { seen[r.sum.agent] = 1; });
    return Object.keys(seen).sort(function (x, y) {
      var i = AG.indexOf(x), j = AG.indexOf(y);
      return (i < 0 ? 99 : i) - (j < 0 ? 99 : j) || x.localeCompare(y);
    });
  }
  function allAgents() { return AG.concat(upAgents().filter(function (a) { return AG.indexOf(a) < 0; })); }
  D.bugs.sort(function (x, y) { return TV.bugSort(x.bug, y.bug); });
  prep();

  /* ---------------------------------------------------------------- state */
  var S = { tab: 'list', q: '', ag: '', oc: '', sort: 'bug' };
  var SEL = { bugs: {}, ups: {} };
  (function readHash() {
    var h = TV.readHash();
    if (h.tab === 'stats') S.tab = 'stats';
    if (h.q) S.q = h.q;
    var old = /^(\w+):(pass|fail)$/.exec(h.ag || '');        // links of the earlier filter
    if (old) { S.ag = old[1]; S.oc = old[2]; } else if (h.ag) S.ag = h.ag;
    if (/^(pass|fail|mixed)$/.test(h.oc || '')) S.oc = h.oc;
    else if (h.f === 'allpass') S.oc = 'pass';
    else if (h.f === 'disagree') S.oc = 'mixed';
    if (/^(bug|actions|failures)$/.test(h.sort || '')) S.sort = h.sort;
  })();
  function saveHash() {
    TV.writeHash({ tab: S.tab === 'list' ? '' : S.tab, q: S.q, ag: S.ag, oc: S.oc,
      sort: S.sort === 'bug' ? '' : S.sort, theme: TV.readHash().theme });
  }

  /* ---------------------------------------------------------------- header + status */
  function subtitle() {
    var shown = D.bugs.filter(function (b) { return !isHidden(b); }).length;
    $('#subtitle').innerHTML = esc((D.config || 'original') + ' configuration') + ' · ' + shown + (hidden.length ? ' of ' + D.bugs.length : '') +
      ' Android bugs × ' + AG.length + ' agents · run ' + RUN + ' shown, runs ' + RUNS[0] + '–' + RUNS[RUNS.length - 1] + ' as dots';
  }
  document.title = 'Corpus · TrajecTiers trace exploration dashboard';
  $('#foot').textContent = (D.generated_by || '') + ' · schema ' + (D.schema || '?') + ' · outcomes from ' + (D.outcome_source || '?') +
    ' (the harness built the patched app and ran the bug test)';
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }
  function rulesLine(extra) {
    return '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span>' + (extra ? '<span class="rs-x">' + extra + '</span>' : '') +
      '<a class="rs-edit" href="tables.html">Edit the tables</a>';
  }

  /* ---------------------------------------------------------------- filters */
  function bugMatchesQuery(b) { return TV.queryMatch(S.q, b.bug, [b.app]); }
  function ocOf(b, oc) {
    if (!oc) return true;
    if (S.ag && AG.indexOf(S.ag) < 0) return false;          // an agent only the uploads have
    if (oc === 'mixed') {
      if (!S.ag) return b.disagree;
      var v = RUNS.map(function (r) { return b.byRun[S.ag][r]; }).filter(function (x) { return x != null; });
      return v.some(function (x) { return x !== v[0]; });
    }
    var want = oc === 'pass';
    return (S.ag ? [S.ag] : AG).every(function (a) { return b.pass[a] === want; });
  }
  function bugRows(oc) {
    return D.bugs.filter(function (b) { return !isHidden(b) && bugMatchesQuery(b) && ocOf(b, oc); });
  }
  function upMatches(r, oc) {
    var s = r.sum;
    if (S.ag && s.agent !== S.ag) return false;
    if (oc === 'mixed') return false;
    if (oc && s.pass !== (oc === 'pass')) return false;
    return TV.queryMatch(S.q, s.bug, [r.name, s.agent, s.model, (r.result.trajectory || {}).app]);
  }
  var OC_TIP = {
    all: { '': 'every bug', pass: 'every agent passes in run ' + RUN, fail: 'every agent fails in run ' + RUN, mixed: 'some agents pass and some fail in run ' + RUN },
    one: { '': 'every bug', pass: '{a} passes in run ' + RUN, fail: '{a} fails in run ' + RUN, mixed: '{a} passes in some of runs ' + RUNS.join(', ') + ' and fails in others' }
  };
  function renderFilters() {
    var ags = allAgents();
    $('#agentSeg').innerHTML = [''].concat(ags).map(function (a) {
      var tip = a ? (AG.indexOf(a) >= 0 ? a + ': its column only; ' + D.bugs.filter(function (b) { return b.pass[a] === true; }).length + ' of ' + D.bugs.length + ' bugs pass in run ' + RUN : a + ': your uploads only') : 'all agents side by side';
      return '<button type="button" data-ag="' + esc(a) + '" aria-pressed="' + (S.ag === a) + '" data-tip="' + esc(tip) + '">' + (a ? TV.agentHTML(a) : 'All') + '</button>';
    }).join('');
    $('#ocSeg').innerHTML = [['', 'All'], ['pass', '✓ Pass'], ['fail', '✗ Fail'], ['mixed', 'Mixed']].map(function (x) {
      var n = bugRows(x[0]).length + UP.filter(function (r) { return upMatches(r, x[0]); }).length;
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
    $('#legend').innerHTML =
      '<div class="lg-row"><span class="lg-k">' + sample('tall', TV.PHASE_ORDER.slice(0, 4).map(TV.phaseVar)) + '<b>Phase</b><span class="muted">upper strip</span></span>' +
        '<span class="lg-v">' + TV.phaseLegend() + '</span></div>' +
      '<div class="lg-row"><span class="lg-k">' + sample('thin', TV.OUTCOMES.map(function (o) { return 'var(--o-' + o + ')'; })) + '<b>Phase outcome</b><span class="muted">lower strip</span></span>' +
        '<span class="lg-v">' + TV.outcomeLegend() + '</span></div>' +
      '<div class="lg-row"><span class="lg-k"><b>Harness outcome</b></span><span class="lg-v">' +
        '<span class="lgm">' + TV.markHTML(true) + 'pass</span><span class="lgm">' + TV.markHTML(false) + 'fail</span><span class="lgm muted">run ' + RUN + '</span>' +
        '<span class="lgm sep"><i class="rdot pass"></i><i class="rdot fail"></i> runs ' + RUNS.join('·') + '</span>' +
        '<span class="lgm muted">strip length = number of actions</span></span></div>';
  }

  /* ---------------------------------------------------------------- uploads table */
  function relDate(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return '';
    var d = (Date.now() - t) / 1000;
    if (d < 90) return 'just now';
    if (d < 3600) return Math.round(d / 60) + ' min ago';
    if (d < 86400) return Math.round(d / 3600) + ' h ago';
    return new Date(t).toLocaleDateString();
  }
  function stripCell(s, max) {
    return '<span class="track">' + TV.stripsHTML(s.strip, s.sub_strip, s.n_actions, max * 1.04) +
      '<span class="an" data-tip="' + esc(s.n_actions + ' actions · ' + s.stats.n_phases + ' phase spans') + '">' + s.n_actions + '</span></span>';
  }
  /* "12 unrecognized": steps whose tool or program no lookup table knows (atif/diagnose.py) */
  function unrecTag(r) {
    var u = (r.result || {}).unrecognized;
    if (!u || !u.n_unrecognized) return '';
    return ' · <span class="unrec-tag" data-tip="' + esc(TV.plural(u.n_unrecognized, 'step') + ' of ' + u.n_actions + ' match nothing in the lookup tables (' +
      u.groups.slice(0, 4).map(function (g) { return g.key; }).join(', ') + (u.groups.length > 4 ? ', …' : '') + '). Open the upload to add rows for them.') + '">' + u.n_unrecognized + ' unrecognized</span>';
  }
  function knownBug(id) { return id && D.bugs.some(function (b) { return String(b.bug) === String(id); }); }
  function renderUploads() {
    var rows = UP.filter(function (r) { return upMatches(r, S.oc); });
    if (S.sort === 'actions') rows = rows.slice().sort(function (x, y) { return y.sum.n_actions - x.sum.n_actions; });
    $('#upCount').textContent = UP.length ? (rows.length < UP.length ? rows.length + ' of ' + UP.length : UP.length) : '';
    var nsel = Object.keys(SEL.ups).length;
    $('#upActs').innerHTML = (nsel ? '<span class="muted small">' + nsel + ' selected</span><button class="btn small danger" type="button" data-act="delete">Delete</button>' +
      '<button class="btn ghost small" type="button" data-act="clear-ups">Clear</button>' : '') +
      (UP.length ? '<button class="btn small" type="button" data-upload>+ Upload</button>' : '');
    var el = $('#upList');
    if (!UP.length) {
      el.className = 'upempty';
      el.innerHTML = '<div><b>Your own trajectories</b> <span class="muted">· one, or several to compare</span></div>' +
        '<button class="btn" type="button" data-upload>Upload…</button>';
      return;
    }
    el.className = 'card ups';
    var groups = TV.uploads.groups(UP);
    var gl = groups.length ? '<div class="ugroups"><span class="muted small">Comparisons</span>' + groups.map(function (g) {
      return '<a href="analyze.html#g=' + encodeURIComponent(g.id) + '" data-tip="' + esc(TV.uploads.KINDS[g.kind] + ': ' + g.members.map(function (r) { return TV.uploads.memberLabel(r, g.members); }).join(', ')) + '">⇄ ' + esc(g.name || 'comparison') + '</a>';
    }).join('') + '</div>' : '';
    if (!rows.length) { el.innerHTML = gl + '<div class="empty">No upload matches the filters.</div>'; return; }
    var all = rows.every(function (r) { return SEL.ups[r.id]; });
    var h = '<div class="urow head" role="row"><span class="sel"><input type="checkbox" data-selall="ups"' + (all ? ' checked' : '') + ' aria-label="Select every upload shown"></span>' +
      '<span>Trajectory</span><span>Agent</span><span>Bug</span><span>Outcome</span><span>Phases and their outcomes</span><span>Added</span></div>';
    rows.forEach(function (r) {
      var s = r.sum, src = r.result.source || {}, bug = s.bug || src.bug, swe = s.project === 'swebench';
      h += '<div class="urow' + (r.rulesKey !== RKEY ? ' stale' : '') + '" role="row" data-id="' + esc(r.id) + '">' +
        '<span class="sel"><input type="checkbox" data-sel="ups" value="' + esc(r.id) + '"' + (SEL.ups[r.id] ? ' checked' : '') + ' aria-label="Select ' + esc(r.name) + '"></span>' +
        '<a class="uname" href="analyze.html#u=' + encodeURIComponent(r.id) + '"><b>' + esc(r.name) + '</b><span class="muted small">' + esc(TV.uploads.formatLabel(src.format)) + ' · ' + TV.uploads.sizeLabel(r.size || 0) +
          unrecTag(r) + (r.group ? ' · <span class="ugrp">⇄ ' + esc(r.group.name || 'comparison') + '</span>' : '') + '</span></a>' +
        '<span class="uag"' + (s.model ? ' data-tip="' + esc(s.model) + '"' : '') + '>' + TV.agentHTML(s.agent || '?') + '</span>' +
        '<span class="ubug">' + (swe ? '<span class="yours swe" data-tip="' + esc((bug ? bug + ' · ' : '') + 'a SWE-bench run, kept apart from the Android corpus') + '">SWE-bench</span>' :
          bug ? (knownBug(bug) ? '<a href="bug.html#bug=' + encodeURIComponent(bug) + '" data-tip="open this bug in the corpus">bug-' + esc(bug) + '</a>' : 'bug-' + esc(bug)) : '<span class="muted">–</span>') + '</span>' +
        '<span class="uoc">' + TV.markHTML(s.pass, s.pass == null ? 'no harness outcome given (set it on the trajectory page)' : 'harness outcome you set') + '</span>' +
        stripCell(s, maxUp) +
        '<span class="udate muted small" title="' + esc(r.added) + '">' + esc(relDate(r.added)) + '</span></div>';
    });
    el.innerHTML = gl + h;
  }

  /* ---------------------------------------------------------------- corpus table */
  function cellHTML(b, a, single) {
    var t = b.agents[a];
    var lbl = '<span class="alabel">' + TV.agentHTML(a) + '</span>';
    if (!t) return '<span class="acell none" data-agent="' + a + '" role="cell">' + lbl + TV.markHTML(b.pass[a]) + '<span class="track">not converted</span>' + TV.runDots(b.byRun[a], RUNS, null, a) + '</span>';
    return '<span class="acell" data-agent="' + a + '" role="cell">' + lbl +
      TV.markHTML(t.pass, a + ' · run ' + RUN + ': ' + TV.oc(t.pass)) +
      stripCell(t, single ? Math.max.apply(null, D.bugs.map(function (x) { return (x.agents[a] || {}).n_actions || 0; })) : maxN) +
      TV.runDots(b.byRun[a], RUNS, null, a) + '</span>';
  }
  function renderBugs() {
    var single = S.ag && AG.indexOf(S.ag) >= 0, cols = S.ag ? (single ? [S.ag] : []) : AG;
    var rows = bugRows(S.oc);
    var nOf = function (b) { return single ? ((b.agents[S.ag] || {}).n_actions || 0) : b.nTotal; };
    var failsOf = function (b) { return single ? RUNS.filter(function (r) { return b.byRun[S.ag][r] === false; }).length : b.fails; };
    if (S.sort === 'actions') rows.sort(function (x, y) { return nOf(y) - nOf(x) || TV.bugSort(x.bug, y.bug); });
    else if (S.sort === 'failures') rows.sort(function (x, y) { return failsOf(y) - failsOf(x) || TV.bugSort(x.bug, y.bug); });
    $('#bugCount').textContent = rows.length + ' of ' + D.bugs.length;
    var nsel = Object.keys(SEL.bugs).length;
    $('#bugActs').innerHTML = (nsel ? '<span class="muted small">' + nsel + ' selected</span><button class="btn small" type="button" data-act="hide" title="Remove the selected bugs from this page and its statistics (in this browser; Restore brings them back)">Remove from view</button>' +
      '<button class="btn ghost small" type="button" data-act="clear-bugs">Clear</button>' : '') +
      (hidden.length ? '<button class="btn ghost small" type="button" data-act="restore" data-tip="' + esc('removed: ' + hidden.map(function (x) { return 'bug-' + x; }).join(', ')) + '">' + hidden.length + ' removed · Restore</button>' : '');
    var el = $('#bugs');
    el.style.setProperty('--nag', Math.max(1, cols.length));
    el.classList.toggle('single', !!single);
    el.classList.toggle('computing', computing);
    if (S.ag && !single) {
      el.innerHTML = '<div class="empty">The corpus has no ' + esc(S.ag) + ' trajectories; its uploads are listed above.</div>';
      return;
    }
    var all = rows.length && rows.every(function (b) { return SEL.bugs[b.bug]; });
    var h = '<div class="brow head" role="row"><span class="sel"><input type="checkbox" data-selall="bugs"' + (all ? ' checked' : '') + ' aria-label="Select every bug shown"></span>' +
      '<span role="columnheader">Bug</span><span role="columnheader">App</span>' +
      cols.map(function (a) { return '<span role="columnheader">' + TV.agentHTML(a) + '</span>'; }).join('') + '</div>';
    rows.forEach(function (b) {
      h += '<div class="brow" role="row" data-bug="' + esc(b.bug) + '"' + (b.page === false ? ' title="bug page not exported yet"' : '') + '>' +
        '<span class="sel"><input type="checkbox" data-sel="bugs" value="' + esc(b.bug) + '"' + (SEL.bugs[b.bug] ? ' checked' : '') + ' aria-label="Select bug-' + esc(b.bug) + '"></span>' +
        '<a class="bid" role="cell" href="bug.html#bug=' + encodeURIComponent(b.bug) + '">bug-' + esc(b.bug) + '</a>' +
        '<span class="bapp" role="cell" title="' + esc(b.app || '') + '">' + esc(b.app || '–') + '</span>' +
        cols.map(function (a) { return cellHTML(b, a, single); }).join('') + '</div>';
    });
    if (!rows.length) h += '<div class="empty">No bug matches. <button class="btn" type="button" data-reset>Show all</button></div>';
    el.innerHTML = h;
  }

  /* ---------------------------------------------------------------- render */
  var statsDirty = true;
  function render() {
    subtitle();
    renderFilters();
    renderUploads();
    renderBugs();
    $('#tab-list').classList.remove('pending');
    statsDirty = true;
    if (S.tab === 'stats') renderStats();
    saveHash();
  }
  function renderStats() {
    if (!statsDirty || !TV.views.stats) return;
    statsDirty = false;
    var bugs = D.bugs.filter(function (b) { return !isHidden(b); });
    var groups = AG.map(function (a) {
      return { key: a, agent: a, corpus: true, trajs: bugs.map(function (b) { return b.agents[a]; }).filter(Boolean) };
    });
    /* uploads: one group per agent, and SWE-bench runs apart from the Android ones */
    upAgents().forEach(function (a) {
      ['android', 'swebench'].forEach(function (p) {
        var ts = UP.filter(function (r) { return r.sum.agent === a && r.sum.project === p; }).map(function (r) { return r.sum; });
        if (ts.length) groups.push({ key: 'up:' + a + (p === 'swebench' ? ':swe' : ''), agent: a, corpus: false, swebench: p === 'swebench', trajs: ts });
      });
    });
    TV.overview = { data: D, agents: AG, runs: RUNS, run: RUN, bugs: bugs, hidden: hidden.length, groups: groups, rules: TV.ruleset.label(RS), computing: computing };
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

  function onSelect(e) {
    var box = e.target.closest('input[type="checkbox"]');
    if (!box) return false;
    var which = box.dataset.sel || box.dataset.selall, set = SEL[which];
    if (box.dataset.selall) {
      $$('input[data-sel="' + which + '"]').forEach(function (x) { if (box.checked) set[x.value] = 1; else delete set[x.value]; });
    } else if (box.checked) set[box.value] = 1; else delete set[box.value];
    if (which === 'bugs') renderBugs(); else renderUploads();
    return true;
  }
  $('#bugs').addEventListener('change', onSelect);
  $('#upList').addEventListener('change', onSelect);
  /* a click on a row opens it, unless it was on a checkbox or a link of its own */
  $('#bugs').addEventListener('click', function (e) {
    if (e.target.closest('[data-reset]')) { S.q = ''; S.oc = ''; S.ag = ''; render(); return; }
    if (e.target.closest('.sel, a')) return;
    var row = e.target.closest('.brow[data-bug]');
    if (!row) return;
    var cell = e.target.closest('.acell[data-agent]');
    location.href = 'bug.html#bug=' + encodeURIComponent(row.dataset.bug) + (cell ? '&t=' + cell.dataset.agent + '-r' + RUN : '');
  });
  $('#upList').addEventListener('click', function (e) {
    if (e.target.closest('.sel, a, button')) return;
    var row = e.target.closest('.urow[data-id]');
    if (row) location.href = 'analyze.html#u=' + encodeURIComponent(row.dataset.id);
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b) return;
    var act = b.dataset.act;
    if (act === 'hide') {
      Object.keys(SEL.bugs).forEach(function (id) { if (hidden.indexOf(id) < 0) hidden.push(id); });
      SEL.bugs = {};
      saveHidden();
      render();
    } else if (act === 'restore') { hidden = []; saveHidden(); render(); }
    else if (act === 'clear-bugs') { SEL.bugs = {}; renderBugs(); }
    else if (act === 'clear-ups') { SEL.ups = {}; renderUploads(); }
    else if (act === 'delete') {
      var ids = Object.keys(SEL.ups);
      if (!ids.length || !window.confirm('Delete ' + TV.plural(ids.length, 'upload') + ' from this browser? This cannot be undone.')) return;
      TV.uploads.remove(ids).then(function () {
        UP = UP.filter(function (r) { return ids.indexOf(r.id) < 0; });
        SEL.ups = {};
        prep();
        render();
      });
    }
  });

  /* uploading (and setting up a comparison) is upload.html */
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-upload]')) location.href = 'upload.html';
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

  /* ---------------------------------------------------------------- the rules: corpus + uploads */
  /* both resolve to true when the corpus or the uploads changed (the lists then render again) */
  function applyCorpusRules() {
    if (TV.ruleset.isDefault(RS)) return Promise.resolve(false);
    return TV.corpus.cached(D, RS).then(function (hit) {
      if (hit) { TV.corpus.apply(D, hit); TV.vocab = D.vocab; prep(); status('ok', rulesLine('applied to the corpus')); return true; }
      if (!TV.engine.usable()) {
        status('warn', rulesLine('needs the analysis engine; showing the <b>built-in tables</b>'));
        return false;
      }
      computing = true;
      render();
      return TV.corpus.overview(D, RS, function (done, total) {
        status('busy', rulesLine('applying them to the corpus… ' + done + ' / ' + total + ' bugs'));
      }).then(function (res) {
        TV.corpus.apply(D, res);
        TV.vocab = D.vocab;
        computing = false;
        prep();
        status('ok', rulesLine('applied to the corpus'));
        return true;
      }, function (err) {
        computing = false;
        status('warn', rulesLine('not applied (' + esc(err.message) + '); showing the <b>built-in tables</b>'));
        return true;
      });
    });
  }
  function refreshUploads() {
    var stale = UP.filter(function (r) { return r.rulesKey !== RKEY; });
    if (!stale.length || !TV.engine.usable()) return Promise.resolve(false);
    return TV.uploads.refresh(UP, RS, function (done, total) {
      status('busy', rulesLine('analysing your uploads again… ' + done + ' / ' + total));
    }).then(function (res) {
      UP.forEach(function (r) { r.sum = TV.uploads.summary(r); });
      prep();
      if (res.failed.length) status('warn', rulesLine(res.failed.length + ' upload(s) could not be analysed with these tables: ' + esc(res.failed[0].error)));
      else status(TV.ruleset.isDefault(RS) ? '' : 'ok', TV.ruleset.isDefault(RS) ? '' : rulesLine('applied to the corpus and your uploads'));
      return true;
    }, function (err) {
      status('warn', rulesLine('your uploads could not be analysed again (' + esc(err.message) + ')'));
      return false;
    });
  }

  /* one render, once the uploads are known (so the corpus table does not jump down when they
   * arrive); again only when the user's rows changed the corpus or the uploads */
  renderLegend();
  subtitle();
  renderFilters();
  if (!TV.ruleset.isDefault(RS)) status('', rulesLine(''));
  TV.uploads.list().then(function (recs) {
    UP = recs.filter(function (r) { return r && r.result && r.result.trajectory; });
    UP.forEach(function (r) { r.sum = TV.uploads.summary(r); });
    prep();
    setTab(S.tab, true);
    render();
    return applyCorpusRules();
  }).then(function (changed) { if (changed) render(); return refreshUploads(); }).then(function (changed) { if (changed) render(); });
})();
