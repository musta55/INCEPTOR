/* Overview > Statistics: per-agent comparisons for the overview run (run 1) plus the 3-run
 * pass picture. Forms: a pass matrix (bug x run squares), 100%-stacked phase shares, subphase
 * outcomes per phase (one 100% bar per phase and agent), and "tables of bars" (one row per
 * category, one column per agent, a common scale), so agents need no colour of their own:
 * bars are neutral, or wear the outcome colour they encode. Counts come from the phase
 * taxonomy's metrics (atif/phase.py), which leave polls out. */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;
  var norm = false;

  function ctx() { return TV.overview; }
  function trajs(a) { return ctx().data.bugs.map(function (b) { return b.agents[a]; }).filter(Boolean); }

  /* ------------------------------------------------------------------ pass matrix + table */
  function passPanel() {
    var C = ctx(), D = C.data, AG = C.agents, RUNS = C.runs, nb = D.bugs.length;
    var h = '<section class="card panel wide"><h3>Outcome across runs</h3>' +
      '<p class="desc">Harness outcome of every bug in runs ' + RUNS.join(', ') + ' (columns = bugs by id, rows = runs). Filled = pass, ring = fail. Hover a square for the bug; click to open it.</p>';
    h += '<div class="pm-wrap"><div class="pm">';
    AG.forEach(function (a) {
      h += '<div>' + TV.agentHTML(a) + '</div><div class="pm-grid" style="--nb:' + nb + '" role="img" aria-label="' + esc(a) + ' pass matrix">';
      RUNS.forEach(function (r) {
        h += '<span class="pm-r">r' + r + '</span>';
        D.bugs.forEach(function (b) {
          var v = b.byRun[a][r];
          h += '<a class="' + TV.oc(v) + '" href="bug.html#bug=' + encodeURIComponent(b.bug) + '&t=' + a + '-r' + r + '" data-tip="' +
            esc('bug-' + b.bug + ' · ' + a + ' · run ' + r + ': ' + TV.oc(v)) + '"></a>';
        });
      });
      h += '</div>';
    });
    h += '</div>';
    h += '<div class="tscroll"><table class="ptab"><thead><tr><th>Agent</th>' + RUNS.map(function (r) { return '<th>Run ' + r + '</th>'; }).join('') +
      '<th data-tip="bugs that pass in every run">All runs pass</th><th data-tip="bugs that fail in every run">No run passes</th>' +
      '<th data-tip="bugs that pass in some runs and fail in others">Runs disagree</th></tr></thead><tbody>';
    AG.forEach(function (a) {
      var all = 0, none = 0, mixed = 0;
      D.bugs.forEach(function (b) {
        var v = RUNS.map(function (r) { return b.byRun[a][r]; }).filter(function (x) { return x != null; });
        if (!v.length) return;
        if (v.every(function (x) { return x; })) all++;
        else if (v.every(function (x) { return !x; })) none++;
        else mixed++;
      });
      h += '<tr><td>' + TV.agentHTML(a) + '</td>' + RUNS.map(function (r) {
        var known = D.bugs.filter(function (b) { return b.byRun[a][r] != null; }).length;
        var p = D.bugs.filter(function (b) { return b.byRun[a][r] === true; }).length;
        return '<td>' + p + '<span class="muted">/' + known + '</span></td>';
      }).join('') + '<td>' + all + '</td><td>' + none + '</td><td>' + mixed + '</td></tr>';
    });
    return h + '</tbody></table></div></div></section>';
  }

  /* ------------------------------------------------------------------ phase shares */
  function phasePanel() {
    var C = ctx(), AG = C.agents;
    var h = '<section class="card panel"><h3>Where the actions go</h3><p class="desc">Share of run-' + C.run +
      ' tool actions in each phase, all bugs pooled (polls left out, as in the metrics).</p><div class="legend" style="margin-bottom:12px">' + TV.phaseLegend() + '</div><div class="pshare">';
    AG.forEach(function (a) {
      var tot = {}, n = 0;
      trajs(a).forEach(function (t) {
        TV.PHASE_ORDER.forEach(function (p) { var k = (t.metrics || {})[p + '_actions'] || 0; tot[p] = (tot[p] || 0) + k; n += k; });
      });
      h += '<div>' + TV.agentHTML(a) + '<div class="muted small">' + n + ' actions</div></div><div class="bar100">';
      TV.PHASE_ORDER.forEach(function (p) {
        var v = tot[p] || 0;
        if (!v) return;
        var share = v / n;
        h += '<i style="flex:' + v + ' 1 0;background:' + TV.phaseVar(p) + ';color:' + TV.phaseTextVar(p) + '" data-tip="' +
          esc(a + ' · ' + p + ': ' + v + ' actions (' + TV.pct(share) + ')') + '">' + (share >= 0.07 ? TV.pct(share) : '') + '</i>';
      });
      h += '</div>';
    });
    return h + '</div></section>';
  }

  /* ------------------------------------------------------------------ subphase outcomes per phase */
  function outcomePanel() {
    var C = ctx(), AG = C.agents;
    var h = '<section class="card panel"><h3>Subphase outcomes per phase</h3><p class="desc">Run-' + C.run +
      ' subphases of each phase by outcome; one bar per agent, 100% = that agent\'s subphases in the phase (the count is at the right). Hover a piece for the codebook\'s meaning.</p>' +
      '<div class="legend" style="margin-bottom:12px">' + TV.outcomeLegend() + '</div>' +
      '<div class="phout" style="--nag:' + AG.length + '"><span></span>' + AG.map(function (a) { return '<span class="bh">' + TV.agentHTML(a) + '</span>'; }).join('');
    TV.PHASE_ORDER.forEach(function (p) {
      h += '<span class="bl">' + TV.phaseChip(p) + '</span>';
      AG.forEach(function (a) {
        var c = {}, n = 0;
        trajs(a).forEach(function (t) {
          var row = ((t.subphases || {}).by_phase || {})[p] || {};
          Object.keys(row).forEach(function (o) { c[o] = (c[o] || 0) + row[o]; n += row[o]; });
        });
        h += '<span class="bc"><span class="bar100 mini">' + (n ? TV.OUTCOMES.filter(function (o) { return c[o]; }).map(function (o) {
          var share = c[o] / n;
          return '<i class="o-' + o + '" style="flex:' + c[o] + ' 1 0" data-tip="' + esc(a + ' · ' + p + ' · ' + c[o] + ' ' + o + ' (' + TV.pct(share) + ') · ' + TV.outcomeDef(p, o)) + '">' +
            (share >= 0.22 ? TV.pct(share) : '') + '</i>';
        }).join('') : '<i class="none"></i>') + '</span><span class="bv">' + n + '</span></span>';
      });
    });
    return h + '</div></section>';
  }

  /* ------------------------------------------------------------------ table of bars */
  function barTable(title, desc, rows, valueOf, opts) {
    opts = opts || {};
    var AG = ctx().agents, per = {}, max = 0;
    AG.forEach(function (a) { per[a] = trajs(a); });
    var data = rows.map(function (r) {
      var o = { key: r, v: {} };
      AG.forEach(function (a) {
        var tot = TV.sum(per[a].map(function (t) { return valueOf(t, r); }));
        o.v[a] = opts.share ? tot : (norm ? (per[a].length ? tot / per[a].length : 0) : tot);
        max = Math.max(max, o.v[a]);
      });
      return o;
    }).filter(function (o) { return opts.keepZero || AG.some(function (a) { return o.v[a] > 0; }); });
    function fmt(v, a) {
      if (opts.share) return String(v);
      return norm ? (v ? v.toFixed(2) : '0') : String(v);
    }
    var h = '<section class="card panel' + (opts.wide ? ' wide' : '') + '"><h3>' + esc(title) + '</h3><p class="desc">' + desc + '</p>';
    if (!data.length) return h + '<p class="muted">Nothing to show.</p></section>';
    h += '<div class="btab" style="--nag:' + AG.length + '"><span class="bh"></span>' + AG.map(function (a) { return '<span class="bh">' + TV.agentHTML(a) + '</span>'; }).join('');
    data.forEach(function (o) {
      var lab = opts.label ? opts.label(o.key) : esc(TV.humanize(o.key));
      h += '<span class="bl"' + (opts.tip ? ' data-tip="' + esc(opts.tip(o.key)) + '"' : ' title="' + esc(TV.humanize(o.key)) + '"') + '>' + lab + '</span>';
      AG.forEach(function (a) {
        var v = o.v[a], w = max ? 100 * v / max : 0;
        var tip = a + ' · ' + TV.humanize(o.key) + ': ' + fmt(v, a) + (opts.share ? ' of ' + per[a].length + ' trajectories' : norm ? ' per trajectory' : '') +
          (opts.tipExtra ? opts.tipExtra(o.key, a, per[a]) : '');
        h += '<span class="bc" data-tip="' + esc(tip) + '"><span class="bt"><span class="bb' + (v > 0 ? '' : ' zero') + '" style="width:calc((100% - 40px) * ' + (w / 100).toFixed(4) + ')' +
          (opts.color ? ';background:' + opts.color(o.key) : '') + '"></span><span class="bv">' + fmt(v, a) + '</span></span></span>';
      });
    });
    return h + '</div></section>';
  }

  /* the last Repair subphase of a trajectory, as one category */
  var FINAL = [
    ['succeeded_test', '✓ succeeded · test', 'the last Repair subphase succeeded on a test run'],
    ['succeeded_build', '✓ succeeded · build', 'the last Repair subphase succeeded on a build only: it compiles, no test judged it'],
    ['failed', '✗ failed', 'the last Repair subphase failed: tests fail, or the change does not compile'],
    ['blocked', '⊘ blocked', 'the environment stopped the run that judges the last attempt'],
    ['unchecked', '○ unchecked', 'the final change was never run'],
    ['none', 'no repair', 'the trajectory has no Repair phase (no edit of app source)']
  ];
  function finalOf(t) {
    var m = t.metrics || {}, o = m.final_repair_outcome;
    if (!o) return 'none';
    return o === 'succeeded' ? 'succeeded_' + (m.final_repair_evidence === 'test' ? 'test' : 'build') : o;
  }
  var PROCESS = [
    ['n_attempts', 'attempts', 'repair attempts: app-source edits up to the run that judges them (G4)'],
    ['n_failed_attempts', 'failed attempts', 'attempts whose judging run failed'],
    ['n_blocked_attempts', 'blocked attempts', 'attempts whose judging run the environment stopped'],
    ['repair_cycles', 'repair spans', 'Repair phase spans; a lookup of two or more rows inside an attempt splits them (G7)'],
    ['reentries', 'phase re-entries', 'times a phase starts again after another phase'],
    ['tool_errors', 'tool errors', 'lookups, edits and other non-run calls that failed'],
    ['reverts', 'reverts', 'actions that undo changes (git checkout / restore / stash / reset)'],
    ['self_reviews', 'self-reviews', 'git diff, or reading back its own changed files']
  ];
  function metric(t, k) {
    var v = (t.metrics || {})[k];
    if (v && typeof v === 'object') return TV.sum(Object.keys(v).map(function (x) { return v[x]; }));
    return typeof v === 'number' ? v : 0;
  }

  function render(el) {
    var C = ctx(), RUN = C.run;
    var per = norm ? 'per trajectory' : 'total';
    var h = '<div class="stat-ctl"><span class="muted">Run ' + RUN + ' of the ' + esc(C.data.config || 'original') + ' configuration · ' +
      C.agents.map(function (a) { return trajs(a).length; }).reduce(function (s, x) { return s + x; }, 0) + ' trajectories</span>' +
      '<span class="seg small" role="group" aria-label="Counts"><button type="button" data-norm="0" aria-pressed="' + !norm + '">Totals</button>' +
      '<button type="button" data-norm="1" aria-pressed="' + norm + '">Per trajectory</button></span></div>';
    h += '<div class="statgrid">';
    h += passPanel();
    h += phasePanel();
    h += outcomePanel();
    h += barTable('Final repair check', 'Trajectories (of each agent\'s ' + trajs(C.agents[0]).length + ') by the outcome and evidence of their last Repair subphase; the tooltip gives how many of them the harness passes.',
      FINAL.map(function (x) { return x[0]; }),
      function (t, r) { return finalOf(t) === r ? 1 : 0; },
      { share: true, keepZero: true,
        color: function (r) { return 'var(--o-' + (r === 'none' ? 'unchecked' : r.split('_')[0]) + ')'; },
        label: function (r) { return esc(FINAL.filter(function (x) { return x[0] === r; })[0][1]); },
        tip: function (r) { return FINAL.filter(function (x) { return x[0] === r; })[0][2]; },
        tipExtra: function (r, a, ts) {
          var mine = ts.filter(function (t) { return finalOf(t) === r; });
          return mine.length ? '; harness passes ' + mine.filter(function (t) { return t.pass === true; }).length + ' of them' : '';
        } });
    h += barTable('Process badges', 'Trajectories (of each agent\'s ' + trajs(C.agents[0]).length + ') where the badge holds.', TV.BADGES.map(function (b) { return b.key; }),
      function (t, r) { var b = TV.BADGES.filter(function (x) { return x.key === r; })[0]; return b.test(t.badges || {}, t.pass) ? 1 : 0; },
      { share: true, keepZero: true,
        label: function (r) { return esc(TV.BADGES.filter(function (x) { return x.key === r; })[0].label); },
        tip: function (r) { return TV.BADGES.filter(function (x) { return x.key === r; })[0].def; } });
    h += barTable('Subphase flags', 'Subphases that carry each flag (' + per + ').', TV.FLAGS,
      function (t, r) { return metric(t, r + '_subphases'); },
      { keepZero: true, label: function (r) { return esc(TV.flagLabel(r)); }, tip: function (r) { return TV.flagDef(r); } });
    h += barTable('Attempts and process', 'Repair attempts and other process measures of the phase taxonomy (' + per + ').', PROCESS.map(function (x) { return x[0]; }),
      function (t, r) { return metric(t, r); },
      { keepZero: true,
        label: function (r) { return esc(PROCESS.filter(function (x) { return x[0] === r; })[0][1]); },
        tip: function (r) { return PROCESS.filter(function (x) { return x[0] === r; })[0][2]; } });
    h += '</div>';
    el.innerHTML = h;
    el.querySelectorAll('[data-norm]').forEach(function (b) {
      b.addEventListener('click', function () { norm = b.dataset.norm === '1'; render(el); });
    });
  }

  TV.views.stats = { render: render };
})();
