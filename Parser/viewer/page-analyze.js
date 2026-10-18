/* An uploaded trajectory (analyze.html#u=<id>), next to the corpus, or a comparison of uploads
 * (analyze.html#g=<group>&m=<member>, set up on upload.html). Uploading itself is upload.html;
 * analyze.html with nothing named goes to the corpus page.
 *
 *   analyze.html#g=<id>   a comparison group (uploads.js groups): a bar with its members (one
 *                         bug's agents, or one agent's runs), the selected member shown as
 *                         below, and the Fingerprint tab with every member side by side.
 *
 *   analyze.html#u=<id>   one upload (uploads.js): its file bar (bug id, harness outcome,
 *                         previous / next, delete), its unrecognised steps with a suggested
 *                         lookup-table row for each (review.js), how it compares with the corpus
 *                         (the same agent's run-1 trajectories, and the same bug's runs when it
 *                         names a corpus bug), then the bug page's Trajectory and Timeline views.
 *
 * Every upload is analysed with the one table file of tables.html (TV.ruleset); one analysed
 * with other rules is analysed again when opened. The corpus side of the comparison is
 * data/overview.js, re-run under the same rules when they are not the default ones
 * (TV.corpus). This file gives the views the shell they expect: TV.traj, TV.exp, TV.state,
 * TV.setCursor, the playhead and the details panel. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc, $ = TV.$, $$ = TV.$$;
  var VIEWS = ['trajectory', 'timeline', 'fingerprint'];
  var S = TV.state = { t: null, i: 0, view: 'trajectory', level: 'categories', fp: 'agents', timeMode: false,
    expanded: {}, playing: false, speed: 4, panel: false };
  var D = window.TRAJ_OVERVIEW && window.TRAJ_OVERVIEW.schema === 'trajview-overview/3' ? window.TRAJ_OVERVIEW : null;
  var RS = TV.ruleset.get(), RKEY = TV.ruleset.key(RS);
  TV.watchRules(RKEY);
  var REC = null;                  // the open upload
  var CUR = null;                  // its prepared trajectory
  var LIST = [];                   // every upload, newest first
  var CORPUS = null;               // D under the rules (null until known; D itself for the default rules)
  var GROUP = null;                // the open comparison: {g (uploads.js group), byKey: {upload id: trajectory}}
  if (D) TV.vocab = D.vocab || {};

  function busy(text) { $('#busy').hidden = !text; if (text) $('#busyText').textContent = text; }
  function status(kind, html) {
    var el = $('#status');
    el.hidden = !html;
    el.className = 'status' + (kind ? ' ' + kind : '');
    el.innerHTML = html || '';
  }

  /* ---------------------------------------------------------------- routing */
  function route() {
    var q = TV.readHash();
    stopPlay();
    if (VIEWS.indexOf(q.v) >= 0) S.view = q.v;
    if (q.g) openGroup(q.g, q.m);
    else if (q.u) { GROUP = null; openUpload(q.u); }
    else location.replace('index.html');            // uploading is upload.html
  }
  function saveHash() {
    if (GROUP) TV.writeHash({ g: GROUP.g.id, m: REC && REC.id, v: S.view === 'trajectory' ? '' : S.view, theme: TV.readHash().theme });
  }
  window.addEventListener('hashchange', route);
  TV.steps.source = function (t) { return REC && t._src === REC.id ? TV.uploads.atif(REC) : null; };

  /* ---------------------------------------------------------------- a comparison group */
  function openGroup(gid, mid) {
    $('#err').hidden = true;
    $('#trajScreen').hidden = false;
    TV.uploads.list().then(function (xs) {
      LIST = xs;
      var g = TV.uploads.groups(xs).filter(function (x) { return x.id === gid; })[0];
      if (!g) {
        $('#trajScreen').hidden = true;
        $('#err').innerHTML = '<b>No comparison ' + esc(gid) + ' in this browser.</b> <a href="index.html">Back to the corpus</a>';
        $('#err').hidden = false;
        return;
      }
      var stale = TV.engine.usable() ? g.members.filter(function (r) { return r.rulesKey !== RKEY; }) : [];
      return stale.reduce(function (p, r, k) {
        return p.then(function () {
          busy('Applying the tables to ' + r.name + (stale.length > 1 ? ' (' + (k + 1) + ' of ' + stale.length + ')' : '') + '…');
          return TV.uploads.reanalyze(r, RS).catch(function () { /* shown as it was analysed */ });
        });
      }, Promise.resolve()).then(function () {
        busy('');
        GROUP = { g: g, byKey: {} };
        g.members.forEach(function (r) { GROUP.byKey[r.id] = prepUpload(r); });
        groupData();
        $('#fpTab').hidden = false;
        show(g.members.filter(function (r) { return r.id === mid; })[0] || g.members[0], true);
      });
    });
  }
  /* the members as the Fingerprint view reads them (TV.bugData.group) */
  function groupData() {
    var g = GROUP.g;
    TV.bugData = { agents: [], runs: [], byKey: GROUP.byKey, trajs: g.members.map(function (r) { return GROUP.byKey[r.id]; }),
      group: { kind: g.kind, rows: g.members.map(function (r) { return { key: r.id, t: GROUP.byKey[r.id], label: TV.uploads.memberLabel(r, g.members) }; }) } };
  }
  function renderGroupBar() {
    var el = $('#grpbar');
    el.hidden = !GROUP;
    if (!GROUP) return;
    var g = GROUP.g;
    el.innerHTML = '<h1>' + esc(g.name || 'Comparison') + '</h1><span class="gk">' + esc(TV.uploads.KINDS[g.kind] || '') + '</span><div class="gmembers" role="group" aria-label="Members">' +
      TV.bugData.group.rows.map(function (x) {
        var t = x.t, a = t.agent, extra = g.kind === 'agents' && x.label !== a ? ' <span class="muted small">' + esc(x.label.slice(a.length + 3)) + '</span>' : '';
        return '<button type="button" class="gmem" data-mem="' + esc(x.key) + '" aria-pressed="' + (REC && x.key === REC.id) + '">' +
          (g.kind === 'runs' ? '<b>' + esc(x.label) + '</b>' : TV.agentHTML(a, extra)) + TV.markHTML(t.outcome.pass) + '<span class="n">' + t.n + '</span></button>';
      }).join('') + '</div><a class="btn small" href="upload.html#g=' + encodeURIComponent(g.id) + '">Edit</a>';
  }
  $('#grpbar').addEventListener('click', function (e) {
    var b = e.target.closest('[data-mem]');
    if (b) TV.select(b.dataset.mem);
  });

  /* ---------------------------------------------------------------- one upload */
  function openUpload(id) {
    $('#err').hidden = true;
    $('#trajScreen').hidden = false;
    TV.uploads.list().then(function (xs) {
      LIST = xs;
      var rec = xs.filter(function (r) { return r.id === id; })[0];
      if (!rec) {
        $('#trajScreen').hidden = true;
        $('#err').innerHTML = '<b>No upload ' + esc(id) + ' in this browser.</b> Uploads are kept per browser; it may have been deleted. <a href="index.html">Back to the corpus</a>';
        $('#err').hidden = false;
        return;
      }
      if (rec.rulesKey === RKEY) { show(rec, true); return; }
      if (!TV.engine.usable()) { show(rec, true); status('warn', 'This upload was analysed with other rules; analysing it again needs the analysis engine.'); return; }
      busy('Applying the tables to ' + rec.name + '…');
      TV.uploads.reanalyze(rec, RS).then(function (r) { busy(''); show(r, true); }, function (err) {
        busy('');
        show(rec, true);
        status('warn', 'Could not apply the current tables (' + esc(err.message) + '); this shows the tables it was analysed with.');
      });
    });
  }
  /* an upload's trajectory, prepared (TV.prepTraj), keyed by the upload's id; in a 'runs'
   * group its run is the run number given on upload.html */
  function prepUpload(rec) {
    var res = rec.result, t = TV.prepTraj(res.trajectory);
    t._src = rec.id;
    if (rec.group && rec.group.kind === 'runs') t.run = rec.run || 1;
    t.key = rec.id;
    var byIndex = {};
    t.actions.forEach(function (a) { a.rules = []; byIndex[a.i] = a; });
    ((res.rules || {}).optional || []).concat((res.rules || {}).custom || []).forEach(function (r) {
      (r.matched || []).forEach(function (i) { if (byIndex[i]) byIndex[i].rules.push({ id: r.id, sentence: r.sentence }); });
    });
    return t;
  }
  function show(rec, fresh) {
    REC = rec;
    var res = rec.result, t = prepUpload(rec), src = res.source || {}, swe = TV.uploads.project(rec) === 'swebench';
    if (res.vocab) TV.vocab = res.vocab;
    if (GROUP && GROUP.byKey[rec.id]) { GROUP.byKey[rec.id] = t; groupData(); }
    renderGroupBar();
    $('.fb-nav').hidden = $('#delUp').hidden = !!GROUP;
    var keepI = !fresh && CUR ? S.i : 0;
    CUR = t;
    S.t = t.key;
    if (fresh) S.expanded = {};
    S.i = keepI ? TV.clamp(keepI, 1, t.n) : 0;
    if (!S.i) S.panel = false;
    document.title = rec.name + ' · TrajecTiers';
    document.body.classList.add('has-result', 'docked');
    $('#fname').textContent = rec.name;
    $('#fmeta').innerHTML = TV.agentHTML(src.agent || t.agent) + (src.model ? '<span class="model mono">' + esc(src.model) + '</span>' : '') +
      '<span class="muted">' + esc(TV.uploads.formatLabel(src.format)) + ' · ' + TV.uploads.sizeLabel(rec.size || 0) + '</span>' +
      (swe ? '<span class="yours swe" data-tip="' + esc('a SWE-bench run' + (src.repo_root ? ': the repository is ' + src.repo_root : '') + '. It is analysed with Python conventions and kept apart from the Android corpus.') + '">SWE-bench</span>' : '') +
      (src.bug ? '<span class="muted">' + esc(TV.uploads.bugLabel(src.bug, swe ? 'swebench' : 'android')) + (src.bug_inferred ? ' (found in the log)' : '') + '</span>' : '');
    $('#bugLbl').textContent = swe ? 'Instance' : 'Bug';
    $('#bugFld').title = swe ? 'The SWE-bench instance id; it only names the run' : 'The bug-<id> checkout the log works in; paths are read relative to it';
    $('#bug').style.width = swe ? '190px' : '';
    $('#bug').inputMode = swe ? 'text' : 'numeric';
    $('#bug').value = rec.bug || '';
    $('#bug').placeholder = src.bug || 'id';
    $$('#outcomeSeg button').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.oc === (rec.outcome === true ? 'pass' : rec.outcome === false ? 'fail' : '') ? 'true' : 'false');
    });
    var k = LIST.map(function (r) { return r.id; }).indexOf(rec.id);
    $('#prevUp').disabled = k <= 0;
    $('#nextUp').disabled = k < 0 || k >= LIST.length - 1;
    $('#prevUp').title = k > 0 ? 'Newer: ' + LIST[k - 1].name + ' ( [ )' : 'No newer upload';
    $('#nextUp').title = k >= 0 && k < LIST.length - 1 ? 'Older: ' + LIST[k + 1].name + ' ( ] )' : 'No older upload';
    $('#notes').innerHTML = (res.warnings || []).map(function (w) { return '<p class="note">' + esc(w) + '</p>'; }).join('');
    renderReview(res);
    var changed = ((res.rules || {}).optional || []).concat((res.rules || {}).custom || []).reduce(function (s, r) { return s + (r.matched || []).length; }, 0);
    if (!$('#status').classList.contains('warn')) {               // only your own rows are worth a line
      status('', TV.ruleset.isDefault(RS) ? '' : '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span><span class="rs-x">they changed ' + TV.plural(changed, 'action') + ' here</span><a class="rs-edit" href="tables.html">Edit the tables</a>');
    }
    renderCompare();
    syncPanel();
    setView(S.view, true);
    updateCursorUI();
    measureSticky();
    saveHash();
  }
  /* unrecognised steps: a suggested row each; adding rows analyses the upload again */
  function renderReview(res) {
    var el = $('#unrec');
    el.innerHTML = TV.review.html(res.unrecognized, { goto: true });
    var card = el.querySelector('.unrec');
    if (!card) return;
    TV.review.bind(card, res.unrecognized, function (rs, rows) {
      RS = rs;
      RKEY = TV.ruleset.key(RS);
      TV.rulesShown(RKEY);
      CORPUS = null; cmpPromise = null;                       // the corpus side, under the new rows too
      busy('Analysing ' + REC.name + ' with ' + TV.plural(rows.length, 'new row') + '…');
      TV.uploads.reanalyze(REC, RS).then(function (r) {
        busy('');
        if (GROUP) { route(); return; }                          // the other members get the rows too
        show(r, false);
        status('ok', '<span class="rs-name">' + esc(TV.ruleset.label(RS)) + '</span><span class="rs-x">added ' + TV.plural(rows.length, 'row') +
          '; your other uploads and the corpus get them when you open them</span><a class="rs-edit" href="tables.html">See the tables</a>');
      }, function (err) { busy(''); status('warn', 'The rows were added, but this upload could not be analysed again: ' + esc(err.message)); });
    });
  }

  /* bug id and harness outcome */
  var bugTimer = 0;
  $('#bug').addEventListener('input', function () {
    clearTimeout(bugTimer);
    var v = this.value.replace(/^bug-/, '').trim();
    bugTimer = setTimeout(function () {
      if (!REC || (REC.bug || '') === v) return;
      REC.bug = v || null;
      busy('Analysing with bug-' + (v || '?') + '…');
      TV.uploads.reanalyze(REC, RS).then(function (r) { busy(''); show(r, false); }, function (err) { busy(''); status('warn', 'Could not analyse it again: ' + esc(err.message)); });
    }, 700);
  });
  $('#outcomeSeg').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-oc]');
    if (!b || !REC) return;
    TV.uploads.setOutcome(REC, b.dataset.oc === 'pass' ? true : b.dataset.oc === 'fail' ? false : null).then(function (r) { show(r, false); });
  });
  function step(d) {
    if (GROUP) {                                      // within the comparison
      var ms = GROUP.g.members, j = ms.indexOf(REC) + d;
      if (ms[j]) TV.select(ms[j].id);
      return;
    }
    var k = LIST.map(function (r) { return r.id; }).indexOf(REC && REC.id);
    var next = LIST[k + d];
    if (next) location.hash = 'u=' + encodeURIComponent(next.id);
  }
  $('#prevUp').addEventListener('click', function () { step(-1); });
  $('#nextUp').addEventListener('click', function () { step(1); });
  $('#delUp').addEventListener('click', function () {
    if (!REC || !window.confirm('Delete ' + REC.name + ' from this browser? This cannot be undone.')) return;
    TV.uploads.remove([REC.id]).then(function () { location.href = 'index.html'; });
  });

  /* ---------------------------------------------------------------- with the corpus */
  function corpusReady() {
    if (!D) return Promise.resolve(null);
    if (TV.ruleset.isDefault(RS)) return Promise.resolve(D);
    var copy = JSON.parse(JSON.stringify(D));
    return TV.corpus.cached(D, RS).then(function (hit) {
      if (hit) return TV.corpus.apply(copy, hit);
      if (!TV.engine.usable()) return null;
      return TV.corpus.overview(D, RS, function (done, total) {
        var el = $('#cmpWait');
        if (el) el.textContent = 'Applying your table rows to the corpus… ' + done + ' / ' + total + ' bugs';
      }).then(function (res) { return TV.corpus.apply(copy, res); });
    });
  }
  var cmpPromise = null;
  function renderCompare() {
    var el = $('#compare'), t = CUR;
    if (!D) { el.innerHTML = ''; return; }
    if (t.project === 'swebench') {
      el.innerHTML = '<div class="card cmp"><div class="cmp-h"><h2>This trajectory and the corpus</h2></div><p class="note">This is a SWE-bench run on a Python repository' +
        (((REC.result || {}).source || {}).repo_root ? ' (<code>' + esc(REC.result.source.repo_root) + '</code>)' : '') +
        ', so it is not compared with the corpus of Android app repairs. Its paths are read relative to the repository, and Python\'s test conventions apply (<code>tests/</code>, <code>test_*.py</code>, pytest and unittest results, and the scripts the agent writes at the repository root to reproduce the issue).</p></div>';
      return;
    }
    if (!CORPUS) {
      el.innerHTML = '<div class="card cmp"><p class="muted" id="cmpWait">Loading the corpus under ' + esc(TV.ruleset.label(RS).toLowerCase()) + '…</p></div>';
      if (!cmpPromise) cmpPromise = corpusReady().then(function (c) {
        CORPUS = c || 'none';
        if (CUR) renderCompare();
      }, function (err) {
        CORPUS = 'none';
        el.innerHTML = '<div class="card cmp"><p class="note">The corpus could not be analysed with your table rows (' + esc(err.message) + '), so there is no comparison.</p></div>';
      });
      return;
    }
    if (CORPUS === 'none') { el.innerHTML = '<div class="card cmp"><p class="note">Comparing with the corpus under your table rows needs the analysis engine.</p></div>'; return; }
    var C = CORPUS, agents = C.agents || TV.AGENT_ORDER, same = agents.indexOf(t.agent) >= 0;
    var pool = [];
    C.bugs.forEach(function (b) { (same ? [t.agent] : agents).forEach(function (a) { if (b.agents[a]) pool.push(b.agents[a]); }); });
    var who = same ? t.agent + '\'s ' + pool.length + ' corpus runs' : 'all ' + pool.length + ' corpus runs';
    /* a tile: this run's value, the corpus median, and where the value falls among the runs */
    function tile(label, value, xs, fmt, tip) {
      var a = xs.filter(function (x) { return x != null && !isNaN(x); }), med = TV.median(a), cmp = '';
      if (med != null) {
        cmp = 'corpus median ' + fmt(med);
        if (value != null) {
          var lo = a.filter(function (x) { return x < value; }).length / a.length, hi = a.filter(function (x) { return x > value; }).length / a.length;
          cmp += lo >= 0.5 ? ' · above ' + Math.round(100 * lo) + '% of runs' : hi >= 0.5 ? ' · below ' + Math.round(100 * hi) + '% of runs' : ' · typical';
        }
      }
      return '<div class="tile"' + (tip ? ' data-tip="' + esc(tip) + '"' : '') + '><span>' + label + '</span><b>' + (value == null ? '–' : fmt(value)) + '</b>' +
        (cmp ? '<span class="tc">' + cmp + '</span>' : '') + '</div>';
    }
    var id = function (x) { return String(Math.round(x)); };
    var dur = t.stats.duration_s != null ? t.stats.duration_s : t.stats.reported_duration_s;
    var failedAtt = t.attempts.filter(function (a) { return a.outcome === 'failed'; }).length;
    var h = '<div class="card cmp"><div class="cmp-h"><h2>This trajectory and the corpus</h2><span class="muted small">compared with ' + esc(who) + ' (run 1) · ' + esc(TV.ruleset.label(RS)) + '</span></div>';
    h += '<div class="tiles">' +
      tile('Actions', t.n, pool.map(function (x) { return x.n_actions; }), id, TV.plural(t.n_steps || 0, 'agent step') + ' (LLM turns)') +
      tile('Phase spans', t.phases.length, pool.map(function (x) { return x.stats.n_phases; }), id, 'stretches of one phase; a phase may come back') +
      tile('Repair attempts', t.attempts.length, pool.map(function (x) { return x.stats.n_attempts; }), id, 'edits of app code, each checked by the first build or test after it' + (failedAtt ? '; ' + failedAtt + ' failed here' : '')) +
      tile('First fix', t.anchor, pool.map(function (x) { return x.stats.anchor; }), function (x) { return '#' + Math.round(x); }, t.anchor ? 'the first edit of a source file' : 'this log never edits a source file') +
      (dur != null ? tile('Duration', dur, pool.map(function (x) { return x.stats.duration_s != null ? x.stats.duration_s : x.stats.reported_duration_s; }), TV.fmtDur) : '') +
      '</div>';
    /* phase shares: this run against the pooled corpus runs */
    function shares(list) {
      var tot = {}, n = 0;
      list.forEach(function (x) { TV.PHASE_ORDER.forEach(function (p) { var k = (x.metrics || {})[p + '_actions'] || 0; tot[p] = (tot[p] || 0) + k; n += k; }); });
      return { tot: tot, n: n };
    }
    function bar(sh, label) {
      return '<div class="ps-l">' + label + '</div><div class="bar100">' + (sh.n ? TV.PHASE_ORDER.filter(function (p) { return sh.tot[p]; }).map(function (p) {
        var share = sh.tot[p] / sh.n;
        return '<i style="flex:' + sh.tot[p] + ' 1 0;background:' + TV.phaseVar(p) + ';color:' + TV.phaseTextVar(p) + '" data-tip="' + esc(p + ': ' + sh.tot[p] + ' actions (' + TV.pct(share) + ')') + '">' + (share >= 0.08 ? TV.pct(share) : '') + '</i>';
      }).join('') : '<i class="none"></i>') + '</div>';
    }
    h += '<div class="cmp-cols"><div><h3>Where the actions go</h3><div class="pshare">' + bar(shares([t]), '<b>This run</b>') + bar(shares(pool), same ? TV.agentHTML(t.agent) + '<span class="muted small">corpus, ' + pool.length + ' runs</span>' : '<b>Corpus</b><span class="muted small">all ' + pool.length + ' runs</span>') + '</div>' +
      '<div class="legend lg-inline">' + TV.phaseLegend() + '</div></div>';
    /* phase outcomes: this run's counts against the corpus shares, phase by phase (a phase whose
     * checks changed counts each of its outcomes) */
    var mine = {};
    t.subs.forEach(function (s) { var r = mine[s.p.phase] || (mine[s.p.phase] = {}); r[s.outcome] = (r[s.outcome] || 0) + 1; });
    h += '<div><h3>Phase outcomes</h3><div class="ocmp">';
    TV.PHASE_ORDER.filter(function (p) { return mine[p]; }).forEach(function (p) {
      var c = {}, n = 0;
      pool.forEach(function (x) { var row = ((x.subphases || {}).by_phase || {})[p] || {}; Object.keys(row).forEach(function (o) { c[o] = (c[o] || 0) + row[o]; n += row[o]; }); });
      h += '<span class="bl">' + TV.phaseChip(p) + '</span><span class="oc-mine">' + TV.OUTCOMES.filter(function (o) { return mine[p][o]; }).map(function (o) {
        return '<span class="ocount o-' + o + '" data-tip="' + esc(mine[p][o] + ' here · ' + TV.outcomeDef(p, o)) + '"><b aria-hidden="true">' + TV.OUTCOME_GLYPH[o] + '</b>' + mine[p][o] + '</span>';
      }).join('') + '</span><span class="bar100 mini" data-tip="the outcomes of this phase in the corpus runs">' + (n ? TV.OUTCOMES.filter(function (o) { return c[o]; }).map(function (o) {
        return '<i class="o-' + o + '" style="flex:' + c[o] + ' 1 0" data-tip="' + esc('corpus: ' + c[o] + ' ' + o + ' (' + TV.pct(c[o] / n) + ')') + '">' + (c[o] / n >= 0.25 ? TV.pct(c[o] / n) : '') + '</i>';
      }).join('') : '<i class="none"></i>') + '</span>';
    });
    h += '</div><div class="legend lg-inline"><span class="muted small">this run (counts) · corpus (shares)</span>' + TV.outcomeLegend() + '</div></div></div>';
    /* the same bug in the corpus */
    var bug = t.bug && C.bugs.filter(function (b) { return String(b.bug) === String(t.bug); })[0];
    if (bug) {
      h += '<div class="samebug"><h3>bug-' + esc(bug.bug) + ' in the corpus <span class="muted small">run ' + (C.run || 1) + (bug.app ? ' · ' + esc(bug.app) : '') + '</span></h3>';
      var maxN = Math.max(t.n, Math.max.apply(null, agents.map(function (a) { return (bug.agents[a] || {}).n_actions || 0; })));
      h += '<div class="sb-row"><span class="sb-a"><b>This run</b></span>' + TV.markHTML(t.outcome.pass) + '<span class="track">' + TV.stripsHTML(t.strip, t.subStrip, t.n, maxN) + '<span class="an">' + t.n + '</span></span></div>';
      agents.forEach(function (a) {
        var x = bug.agents[a];
        if (!x) return;
        h += '<a class="sb-row" href="bug.html#bug=' + encodeURIComponent(bug.bug) + '&t=' + a + '-r' + (C.run || 1) + '"><span class="sb-a">' + TV.agentHTML(a) + '</span>' + TV.markHTML(x.pass) +
          '<span class="track">' + TV.stripsHTML(x.strip, x.sub_strip, x.n_actions, maxN) + '<span class="an">' + x.n_actions + '</span></span></a>';
      });
      h += '<a class="btn small" href="bug.html#bug=' + encodeURIComponent(bug.bug) + '">Open bug-' + esc(bug.bug) + ' (3 agents × 3 runs)</a></div>';
    }
    el.innerHTML = h + '</div>';
  }

  /* ---------------------------------------------------------------- the views' shell */
  TV.traj = function () { return CUR; };
  TV.applyLevel = function (t, level) { S.expanded[t.id] = TV.levelExpansion(t, level); };
  TV.exp = function (t) {
    t = t || CUR;
    return S.expanded[t.id] || (S.expanded[t.id] = TV.levelExpansion(t, S.level));
  };
  TV.setCursor = function (i, opts) {
    opts = opts || {};
    var t = CUR;
    if (!t || !t.n) return;
    S.i = TV.clamp(Math.round(i), 1, t.n);
    if (!opts.playing) S.panel = true;
    var v = TV.views[S.view];
    if (v && v.onCursor) { try { v.onCursor(S.i, opts); } catch (err) { if (window.console) console.error(err); } }
    syncPanel();
    updateCursorUI();
  };
  /* a comparison's member (the Fingerprint view and the group bar select one) */
  TV.select = function (key, opts) {
    if (!GROUP || !GROUP.byKey[key]) return;
    var rec = GROUP.g.members.filter(function (r) { return r.id === key; })[0];
    if (!rec) return;
    stopPlay();
    if (rec !== REC) show(rec, true);
    if (opts && opts.i) TV.setCursor(opts.i);
  };
  function setView(v, force) {
    if (VIEWS.indexOf(v) < 0 || (v === 'fingerprint' && !GROUP)) v = 'trajectory';
    var changed = v !== S.view;
    S.view = v;
    $$('.tabs [data-view]').forEach(function (b) { b.setAttribute('aria-selected', b.dataset.view === v ? 'true' : 'false'); });
    if (changed || force) render();
    saveHash();
  }
  function tabCtl() {
    var h = '';
    if (S.view === 'fingerprint') {
      h = '';
    } else if (S.view === 'trajectory') {
      h = TV.levelCtlHTML(S.level);
    } else if (CUR.hasTs) {
      h = '<span class="seg small" role="group" aria-label="x axis"><button type="button" data-x="index" aria-pressed="' + !S.timeMode + '">action #</button>' +
        '<button type="button" data-x="time" aria-pressed="' + S.timeMode + '">wall-clock</button></span>';
    } else h = '<span class="muted small">x = action # (no timestamps in this log)</span>';
    $('#tabCtl').innerHTML = h;
  }
  $('#tabCtl').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.level) { S.level = b.dataset.level; TV.applyLevel(CUR, S.level); render(); }
    else if (b.dataset.x) { S.timeMode = b.dataset.x === 'time'; render(); }
  });
  function render() {
    if (!CUR) return;
    tabCtl();
    var el = $('#view'), v = TV.views[S.view];
    TV.tip.hide();
    try {
      v.render(el);
      if (v.onCursor && S.i) v.onCursor(S.i, { initial: true, noscroll: true });
    } catch (err) {
      el.innerHTML = '<p class="note">View error: ' + esc(err && err.message) + '</p>';
      if (window.console) console.error(err);
    }
  }
  TV.render = render;
  $$('.tabs [data-view]').forEach(function (b) { b.addEventListener('click', function () { setView(b.dataset.view); }); });
  var resizeTimer = 0;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { measureSticky(); if (!RO) relayout(); }, 120);
  });
  /* the view follows its own width: a ResizeObserver redraws it in the frame where the width
   * changed (the details panel opened or closed, the window resized), so no frame with the old
   * layout is ever painted (a delayed redraw made the view flicker) */
  var viewW = 0, RO = window.ResizeObserver;
  if (RO) {
    new RO(function (entries) {
      var w = Math.round(entries[0].contentRect.width);
      if (!w || w === viewW) return;
      var first = !viewW;
      viewW = w;
      if (!first) relayout();
    }).observe(widthProbe($('#view')));
  }
  /* a zero-height box as wide as the view: its size never follows the view's content, so a
   * redraw cannot notify the observer again */
  function widthProbe(view) {
    var probe = document.createElement('div');
    probe.className = 'wprobe';
    probe.setAttribute('aria-hidden', 'true');
    view.parentNode.insertBefore(probe, view);
    return probe;
  }
  function relayout() {
    if (!CUR) return;
    var v = TV.views[S.view];
    if (v && v.relayout) v.relayout(); else render();
  }
  function measureSticky() {
    document.documentElement.style.setProperty('--hdr-h', ($('header.top').offsetHeight || 0) + 'px');
    document.documentElement.style.setProperty('--ph-h', ($('#playhead').offsetHeight || 0) + 'px');
  }

  /* ---------------------------------------------------------------- playhead */
  var play = 0;
  var ICON_PLAY = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.4v9.2l7.6-4.6z" fill="currentColor"/></svg>';
  var ICON_PAUSE = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="2.2" y="1.5" width="2.8" height="9" rx="0.7" fill="currentColor"/><rect x="7" y="1.5" width="2.8" height="9" rx="0.7" fill="currentColor"/></svg>';
  function playBtn() {
    var b = $('#playBtn');
    b.innerHTML = S.playing ? ICON_PAUSE : ICON_PLAY;
    b.setAttribute('aria-label', S.playing ? 'Pause' : 'Play');
    document.body.classList.toggle('playing', S.playing);
  }
  function stopPlay() {
    if (play) clearInterval(play);
    play = 0;
    if (S.playing) { S.playing = false; playBtn(); }
  }
  function startPlay() {
    if (!CUR || !CUR.n) return;
    S.playing = true;
    playBtn();
    TV.setCursor(!S.i || S.i >= CUR.n ? 1 : S.i, { playing: true });
    schedule();
  }
  function schedule() {
    if (play) clearInterval(play);
    play = setInterval(function () {
      if (!CUR || S.i >= CUR.n) { stopPlay(); return; }
      TV.setCursor(S.i + 1, { playing: true });
    }, 1000 / S.speed);
  }
  function togglePlay() { if (S.playing) stopPlay(); else startPlay(); }
  $('#playBtn').addEventListener('click', togglePlay);
  $('#playBtn').innerHTML = ICON_PLAY;
  $('#stepBack').addEventListener('click', function () { TV.setCursor((S.i || 2) - 1); });
  $('#stepFwd').addEventListener('click', function () { TV.setCursor((S.i || 0) + 1); });
  $('#cursor').addEventListener('input', function (e) { TV.setCursor(+e.target.value, { from: 'slider' }); });
  $('#speed').addEventListener('change', function (e) { S.speed = +e.target.value || 4; if (S.playing) schedule(); });
  function updateCursorUI() {
    var t = CUR;
    if (!t) return;
    var a = S.i ? t.actions[S.i - 1] : null, c = $('#cursor');
    c.max = Math.max(1, t.n);
    c.value = S.i || 1;
    c.disabled = !t.n;
    $('#stepBack').disabled = !t.n || S.i <= 1;
    $('#stepFwd').disabled = !t.n || S.i >= t.n;
    $('#playBtn').disabled = !t.n;
    $('#cursorLabel').innerHTML = a ? '<b>#' + a.i + '</b><span class="muted">/' + t.n + '</span> <span class="cl-mid">' + esc(a.category) + '</span>' +
        (a.verdict !== 'none' ? ' <span class="vg v-' + a.verdict + '">' + TV.VERDICT_GLYPH[a.verdict] + '</span>' : '') +
        (a.sub ? ' <span class="opill mini o-' + a.sub.outcome + '" data-tip="' + esc(a.sub.p.phase + ' outcome: ' + TV.outcomeDef(a.sub.p.phase, a.sub.outcome)) + '"><b aria-hidden="true">' + TV.OUTCOME_GLYPH[a.sub.outcome] + '</b><span class="ell">' + esc(a.sub.p.phase) + '</span></span>' : '')
      : '<b>#–</b><span class="muted">/' + t.n + ' · press ▶ or j</span>';
  }

  /* ---------------------------------------------------------------- details panel */
  function syncPanel() {
    var want = !!(CUR && S.i && S.panel);
    var was = document.body.classList.contains('panel-open');
    document.body.classList.toggle('panel-open', want);
    if (want) renderPanel(); else emptyPanel();
    if (want !== was && !RO) setTimeout(relayout, 180);                   // no ResizeObserver: redraw after the slide
  }
  /* no action picked: the docked column says how to fill it */
  function emptyPanel() {
    $('#dtI').textContent = '#–';
    $('#dtOf').textContent = '';
    $('#dtPrev').disabled = $('#dtNext').disabled = true;
    $('#dtBody').innerHTML = '<p class="dt-empty">Click an action, or press <kbd>j</kbd>.</p>';
  }
  function closePanel() { S.panel = false; syncPanel(); }
  TV.closePanel = closePanel;
  function renderPanel() {
    var t = CUR, a = t.actions[S.i - 1];
    if (!a) return;
    $('#dtI').textContent = '#' + a.i;
    $('#dtOf').textContent = 'of ' + t.n + ' · ' + t.agent;
    $('#dtPrev').disabled = a.i <= 1;
    $('#dtNext').disabled = a.i >= t.n;
    $('#dtBody').innerHTML = TV.detailsActsHTML(a) + TV.actionDetailsHTML(t, a);
    if (TV.steps) TV.steps.fill($('#dtBody'), t, a);
    $('#dtBody').scrollTop = 0;
  }
  $('#dtPrev').addEventListener('click', function () { TV.setCursor(S.i - 1); });
  $('#dtNext').addEventListener('click', function () { TV.setCursor(S.i + 1); });
  $('#dtClose').addEventListener('click', closePanel);

  /* ---------------------------------------------------------------- keyboard */
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if ((tag === 'input' && e.target.type !== 'range') || tag === 'select' || tag === 'textarea' || e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key;
    if (k === 'Escape') { if (!$('#help').hidden) $('#help').hidden = true; else closePanel(); return; }
    if (k === '?') { $('#help').hidden = !$('#help').hidden; return; }
    if (!CUR) return;
    if (k === 'j') { TV.setCursor((S.i || 0) + 1); e.preventDefault(); }
    else if (k === 'k') { TV.setCursor((S.i || 2) - 1); e.preventDefault(); }
    else if (k === ' ' && tag !== 'button') { togglePlay(); e.preventDefault(); }
    else if (k === '1' || k === '2' || (k === '3' && GROUP)) setView(VIEWS[+k - 1]);
    else if (k === '[') step(-1);
    else if (k === ']') step(1);
  });

  setTimeout(function () { document.body.classList.remove('preload'); }, 400);
  route();
})();
