/* Overview page (index.html): one run (run 1) of every bug x agent, from data/overview.js
 * (window.TRAJ_OVERVIEW, schema trajview-overview/3). Agent cards, the Bugs list (filters, sort,
 * search) and the Statistics tab (view-stats.js). A bug row opens bug.html#bug=<id>. Each
 * agent cell draws the phase strip and, under it, the subphase-outcome strip (sub_strip). */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var D = window.TRAJ_OVERVIEW;
  if (!D || !D.bugs || !D.bugs.length || D.schema !== 'trajview-overview/3') {
    $('#app').hidden = true;
    $('#nodata').hidden = false;
    if (D && D.schema) $('#nodataWhy').textContent = 'The file holds schema ' + D.schema + '; this viewer draws phases and subphases (trajview-overview/3). Regenerate it from the Parser directory:';
    return;
  }
  TV.vocab = D.vocab || {};

  /* ---------------------------------------------------------------- data */
  var AG = (D.agents || TV.AGENT_ORDER).slice();
  var RUNS = (D.runs || [1, 2, 3]).slice();
  var RUN = D.run || 1;
  var maxN = 1;
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
    b.allPass = known.length === AG.length && known.every(function (x) { return x === true; });
    b.anyFail = known.some(function (x) { return x === false; });
    b.disagree = known.some(function (x) { return x !== known[0]; });
    b.flaky = AG.some(function (a) {
      var v = RUNS.map(function (r) { return b.byRun[a][r]; }).filter(function (x) { return x != null; });
      return v.some(function (x) { return x !== v[0]; });
    });
    b.search = ('bug-' + b.bug + ' ' + (b.app || '')).toLowerCase();
  });
  D.bugs.sort(function (x, y) { return TV.bugSort(x.bug, y.bug); });
  TV.overview = { data: D, agents: AG, runs: RUNS, run: RUN, maxN: maxN };

  /* ---------------------------------------------------------------- state */
  var FILTERS = [
    { k: 'all', l: 'All', d: 'every bug', f: function () { return true; } },
    { k: 'allpass', l: 'All pass', d: 'every agent passes in run ' + RUN, f: function (b) { return b.allPass; } },
    { k: 'anyfail', l: 'Any fail', d: 'at least one agent fails in run ' + RUN, f: function (b) { return b.anyFail; } },
    { k: 'disagree', l: 'Agents disagree', d: 'some agents pass and some fail in run ' + RUN, f: function (b) { return b.disagree; } },
    { k: 'flaky', l: 'Runs disagree', d: 'some agent passes in one run and fails in another (runs ' + RUNS.join(', ') + ')', f: function (b) { return b.flaky; } }
  ];
  var S = { tab: 'bugs', q: '', f: 'all', ag: '', sort: 'bug' };
  var hq = TV.readHash();
  if (hq.tab === 'stats') S.tab = 'stats';
  if (hq.q) S.q = hq.q;
  if (FILTERS.some(function (x) { return x.k === hq.f; })) S.f = hq.f;
  if (/^\w+:(pass|fail)$/.test(hq.ag || '') && AG.indexOf(hq.ag.split(':')[0]) >= 0) S.ag = hq.ag;
  if (/^(bug|actions|failures)$/.test(hq.sort || '')) S.sort = hq.sort;
  function saveHash() {
    TV.writeHash({ tab: S.tab === 'bugs' ? '' : S.tab, q: S.q, f: S.f === 'all' ? '' : S.f, ag: S.ag,
      sort: S.sort === 'bug' ? '' : S.sort, theme: TV.readHash().theme });
  }

  /* ---------------------------------------------------------------- header + cards */
  var nb = D.bugs.length;
  $('#subtitle').textContent = (D.config || 'original') + ' configuration · run ' + RUN + ' · ' + nb + ' bugs × ' + AG.length + ' agents';
  document.title = 'TrajecTiers · ' + (D.config || 'original');
  $('#foot').textContent = (D.generated_by || '') + ' · schema ' + (D.schema || '?') + ' · outcomes from ' + (D.outcome_source || '?') +
    ' (the harness built the patched app and ran the bug test)';

  function fmtNum(x) { return x == null ? '–' : (Math.round(x * 10) / 10).toString(); }
  function cards() {
    return AG.map(function (a) {
      var ts = D.bugs.map(function (b) { return b.agents[a]; }).filter(Boolean);
      var known = D.bugs.filter(function (b) { return b.pass[a] != null; });
      var pass = known.filter(function (b) { return b.pass[a] === true; }).length;
      var allRuns = 0, allKnown = 0, all3 = 0;
      D.bugs.forEach(function (b) {
        var v = RUNS.map(function (r) { return b.byRun[a][r]; });
        v.forEach(function (x) { if (x != null) { allKnown++; if (x) allRuns++; } });
        if (v.every(function (x) { return x === true; })) all3++;
      });
      var perBug = nb ? allRuns / nb : 0;
      return '<article class="card acard">' +
        '<div class="acard-h">' + TV.agentHTML(a) + '<span class="model" title="model">' + esc((D.models || {})[a] || '') + '</span></div>' +
        '<div class="hero"><b>' + pass + '<small>/' + known.length + '</small></b><span>pass in run ' + RUN + ' · ' + TV.pct(known.length ? pass / known.length : null) + '</span></div>' +
        '<div class="runs" data-tip="' + esc('Pass count over runs ' + RUNS.join(', ') + ': ' + allRuns + ' of ' + allKnown + ' trajectories') + '">' +
          'Runs ' + RUNS[0] + '–' + RUNS[RUNS.length - 1] + ': <b>' + allRuns + '/' + allKnown + '</b> · ' + perBug.toFixed(1) + ' of ' + RUNS.length + ' runs pass per bug · all ' + RUNS.length + ' pass on ' + all3 + ' bugs</div>' +
        '<div class="kv">' +
          '<div><b>' + fmtNum(TV.median(ts.map(function (t) { return t.n_actions; }))) + '</b><span>median actions</span></div>' +
          '<div data-tip="phase spans per trajectory (a phase that recurs counts once per stretch)"><b>' + fmtNum(TV.median(ts.map(function (t) { return t.stats.n_phases; }))) + '</b><span>median phase spans</span></div>' +
          '<div data-tip="' + esc('repair attempts in run ' + RUN + ' (rule G4: app-source edits up to the run that judges them), and how many failed') + '"><b>' + TV.sum(ts.map(function (t) { return t.stats.n_attempts; })) +
            '<small class="muted"> / ' + TV.sum(ts.map(function (t) { return (t.metrics || {}).n_failed_attempts || 0; })) + ' ✗</small></b><span>attempts / failed</span></div>' +
          '<div data-tip="' + esc('subphases whose check the environment stopped (outcome blocked), run ' + RUN) + '"><b>' + TV.sum(ts.map(function (t) { return (t.metrics || {}).blocked_subphases || 0; })) + '</b><span>blocked subphases</span></div>' +
        '</div></article>';
    }).join('');
  }
  $('#cards').innerHTML = cards();

  /* ---------------------------------------------------------------- bugs list */
  function agentOptions() {
    var h = '<option value="">any</option>';
    AG.forEach(function (a) {
      h += '<option value="' + a + ':pass">' + esc(a) + ' passes</option><option value="' + a + ':fail">' + esc(a) + ' fails</option>';
    });
    $('#agentFilter').innerHTML = h;
  }
  agentOptions();

  function matches(b, f) {
    if (f && !f.f(b)) return false;
    if (S.ag) {
      var p = S.ag.split(':');
      if (b.pass[p[0]] !== (p[1] === 'pass')) return false;
    }
    if (S.q) {
      var q = S.q.toLowerCase().replace(/^bug-?/, '');
      if (b.search.indexOf(q) < 0 && b.search.indexOf(S.q.toLowerCase()) < 0) return false;
    }
    return true;
  }
  function renderFilters() {
    $('#filters').innerHTML = FILTERS.map(function (f) {
      var n = D.bugs.filter(function (b) { return matches(b, f); }).length;
      return '<button class="chip" type="button" data-f="' + f.k + '" aria-pressed="' + (S.f === f.k) + '" data-tip="' + esc(f.d) + '">' +
        esc(f.l) + ' <span class="cnt">' + n + '</span></button>';
    }).join('');
  }
  function cellHTML(b, a) {
    var t = b.agents[a];
    var lbl = '<span class="alabel">' + TV.agentHTML(a) + '</span>';
    if (!t) {
      return '<span class="acell none" data-agent="' + a + '" role="cell">' + lbl + TV.markHTML(b.pass[a]) + '<span class="track">not converted</span>' + TV.runDots(b.byRun[a], RUNS, null, a) + '</span>';
    }
    return '<span class="acell" data-agent="' + a + '" role="cell">' + lbl +
      TV.markHTML(t.pass, a + ' · run ' + RUN + ': ' + TV.oc(t.pass)) +
      '<span class="track">' + TV.stripsHTML(t.strip, t.sub_strip, t.n_actions, maxN * 1.08) +
      '<span class="an" data-tip="' + esc(t.n_actions + ' actions · ' + t.stats.n_phases + ' phase spans · ' + t.stats.n_subphases + ' subphases · ' + TV.plural(t.stats.n_attempts, 'attempt')) + '">' + t.n_actions + '</span></span>' +
      TV.runDots(b.byRun[a], RUNS, null, a) + '</span>';
  }
  function renderBugs() {
    var f = FILTERS.filter(function (x) { return x.k === S.f; })[0];
    var rows = D.bugs.filter(function (b) { return matches(b, f); });
    if (S.sort === 'actions') rows.sort(function (x, y) { return y.nTotal - x.nTotal || TV.bugSort(x.bug, y.bug); });
    else if (S.sort === 'failures') rows.sort(function (x, y) { return y.fails - x.fails || TV.bugSort(x.bug, y.bug); });
    var h = '<div class="brow head" role="row"><span role="columnheader">Bug</span><span role="columnheader">App</span>' +
      AG.map(function (a) { return '<span role="columnheader">' + TV.agentHTML(a) + '</span>'; }).join('') + '</div>';
    rows.forEach(function (b) {
      h += '<a class="brow" role="row" href="bug.html#bug=' + encodeURIComponent(b.bug) + '" data-bug="' + esc(b.bug) + '"' +
        (b.page === false ? ' title="bug page not exported yet"' : '') + '>' +
        '<span class="bid" role="cell">bug-' + esc(b.bug) + '</span>' +
        '<span class="bapp" role="cell" title="' + esc(b.app || '') + '">' + esc(b.app || '–') + '</span>' +
        AG.map(function (a) { return cellHTML(b, a); }).join('') + '</a>';
    });
    if (!rows.length) h += '<div class="empty">No bug matches. <button class="btn" type="button" data-reset>Show all</button></div>';
    var el = $('#bugs');
    el.style.setProperty('--nag', AG.length);
    el.innerHTML = h;
  }
  function renderLegend() {
    var subs = {};
    D.bugs.forEach(function (b) { AG.forEach(function (a) { var t = b.agents[a]; (t && t.sub_strip || []).forEach(function (p) { subs[p[0]] = 1; }); }); });
    $('#bugLegend').innerHTML = '<span class="lg-t">Phase</span>' + TV.phaseLegend() +
      (Object.keys(subs).length ? '<span class="lg-t">Subphase outcome</span><span class="lgm muted">(thin strip)</span>' + TV.outcomeLegend(subs) : '') +
      '<span class="lg-t">Outcome</span><span class="lgm">' + TV.markHTML(true) + 'pass</span><span class="lgm">' + TV.markHTML(false) + 'fail</span>' +
      '<span class="lgm muted">(run ' + RUN + ')</span>' +
      '<span class="lg-t">Runs ' + RUNS.join('·') + '</span><span class="lgm"><i class="rdot pass"></i>pass</span><span class="lgm"><i class="rdot fail"></i>fail</span>' +
      '<span class="lgm muted">strip length = actions</span>';
  }
  function render() {
    $('#q').value = S.q;
    $('#agentFilter').value = S.ag;
    $('#sort').value = S.sort;
    renderFilters();
    renderBugs();
    saveHash();
  }

  $('#filters').addEventListener('click', function (e) {
    var c = e.target.closest('[data-f]');
    if (c) { S.f = c.dataset.f; render(); }
  });
  $('#q').addEventListener('input', function (e) { S.q = e.target.value.trim(); render(); });
  $('#agentFilter').addEventListener('change', function (e) { S.ag = e.target.value; render(); });
  $('#sort').addEventListener('change', function (e) { S.sort = e.target.value; render(); });
  $('#bugs').addEventListener('click', function (e) {
    if (e.target.closest('[data-reset]')) { e.preventDefault(); S.q = ''; S.f = 'all'; S.ag = ''; render(); return; }
    var cell = e.target.closest('.acell[data-agent]'), row = e.target.closest('a.brow');
    if (cell && row && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
      e.preventDefault();
      location.href = 'bug.html#bug=' + encodeURIComponent(row.dataset.bug) + '&t=' + cell.dataset.agent + '-r' + RUN;
    }
  });

  /* ---------------------------------------------------------------- tabs */
  var statsDone = false;
  function setTab(tab) {
    S.tab = tab;
    $$('.tabs [data-tab]').forEach(function (b) { b.setAttribute('aria-selected', b.dataset.tab === tab ? 'true' : 'false'); });
    $('#tab-bugs').hidden = tab !== 'bugs';
    $('#tab-stats').hidden = tab !== 'stats';
    if (tab === 'stats' && !statsDone && TV.views.stats) {
      statsDone = true;
      try { TV.views.stats.render($('#tab-stats')); }
      catch (err) { $('#tab-stats').innerHTML = '<p class="note">Statistics error: ' + esc(err && err.message) + '</p>'; if (window.console) console.error(err); }
    }
    saveHash();
  }
  $$('.tabs [data-tab]').forEach(function (b) { b.addEventListener('click', function () { setTab(b.dataset.tab); }); });

  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea' || e.metaKey || e.ctrlKey || e.altKey) {
      if (e.key === 'Escape' && tag === 'input') e.target.blur();
      return;
    }
    if (e.key === '/') { e.preventDefault(); setTab('bugs'); $('#q').focus(); }
    else if (e.key === '1') setTab('bugs');
    else if (e.key === '2') setTab('stats');
    else if (e.key === 'Escape') $('#help').hidden = true;
    else if (e.key === '?') $('#help').hidden = !$('#help').hidden;
  });

  renderLegend();
  render();
  setTab(S.tab);
})();
