/* Corpus page > Statistics: the trajectories of the Trajectories tab (the corpus bugs not
 * removed from view, run 1, plus the user's uploads), compared group by group. A group is
 * one corpus agent, or the uploads of one agent ("yours"). Panels: one card per group (pass
 * rate and size), the corpus outcome across runs (pass matrix + table), where the actions
 * go (100%-stacked phase shares), and the outcomes of each phase (one 100% bar per
 * phase and group). Bars are neutral or wear the phase / outcome colour they encode; groups
 * are told apart by name, never by colour. Counts come from the phase taxonomy's metrics
 * (atif/phase.py), which leave polls out. Context: TV.overview (page-overview.js). */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;

  function ctx() { return TV.overview; }
  function groupHTML(g) {
    return '<span class="gname">' + TV.agentHTML(g.agent) + (g.corpus ? '' : '<span class="yours" data-tip="your uploads of this agent">yours</span>') +
      (g.swebench ? '<span class="yours swe" data-tip="SWE-bench runs on Python repositories, kept apart from the Android ones">SWE-bench</span>' : '') + '</span>';
  }
  function fmt1(x) { return x == null ? '–' : (Math.round(x * 10) / 10).toString(); }

  /* ------------------------------------------------------------------ one card per group */
  function cards() {
    var C = ctx(), D = C.data, RUNS = C.runs;
    return '<section class="scards">' + C.groups.map(function (g) {
      var ts = g.trajs, known = ts.filter(function (t) { return t.pass != null; }), pass = known.filter(function (t) { return t.pass === true; }).length;
      var model = g.corpus ? (D.models || {})[g.agent] : (ts.map(function (t) { return t.model; }).filter(Boolean)[0] || '');
      var line;
      if (g.corpus) {
        var all = 0, n = 0;
        C.bugs.forEach(function (b) { RUNS.forEach(function (r) { var v = b.byRun[g.agent][r]; if (v != null) { n++; if (v) all++; } }); });
        line = 'runs ' + RUNS[0] + '–' + RUNS[RUNS.length - 1] + ': ' + all + ' / ' + n + ' pass';
      } else line = TV.plural(ts.length, 'trajectory', 'trajectories') + (known.length < ts.length ? ' · ' + (ts.length - known.length) + ' without an outcome' : '');
      return '<article class="card scard">' +
        '<div class="sc-h">' + groupHTML(g) + '<span class="model" title="model">' + esc(model || '') + '</span></div>' +
        '<div class="hero"><b>' + (known.length ? pass + '<small>/' + known.length + '</small>' : '–') + '</b><span>' +
          (known.length ? 'pass' + (g.corpus ? ' in run ' + C.run : '') + ' · ' + TV.pct(pass / known.length) : 'no outcome set') + '</span></div>' +
        '<div class="sc-l">' + esc(line) + '</div>' +
        '<div class="sc-k"><span><b>' + fmt1(TV.median(ts.map(function (t) { return t.n_actions; }))) + '</b> median actions</span>' +
          '<span><b>' + fmt1(TV.median(ts.map(function (t) { return t.stats.n_phases; }))) + '</b> median phase spans</span></div>' +
        '</article>';
    }).join('') + '</section>';
  }

  /* ------------------------------------------------------------------ pass matrix + table (corpus) */
  function passPanel() {
    var C = ctx(), AG = C.agents, RUNS = C.runs, bugs = C.bugs, nb = bugs.length;
    var h = '<section class="card panel wide"><h3>Corpus outcome across runs</h3>' +
      '<p class="desc">Runs ' + RUNS.join(', ') + ' · filled = pass, ring = fail · click to open.</p>';
    h += '<div class="pm-wrap"><div class="pm">';
    AG.forEach(function (a) {
      h += '<div>' + TV.agentHTML(a) + '</div><div class="pm-grid" style="--nb:' + nb + '" role="img" aria-label="' + esc(a) + ' pass matrix">';
      RUNS.forEach(function (r) {
        h += '<span class="pm-r">r' + r + '</span>';
        bugs.forEach(function (b) {
          var v = b.byRun[a][r];
          h += '<a class="' + TV.oc(v) + '" href="bug.html#bug=' + encodeURIComponent(b.bug) + '&t=' + a + '-r' + r + '" data-tip="' +
            esc('bug-' + b.bug + ' · ' + a + ' · run ' + r + ': ' + TV.oc(v)) + '"></a>';
        });
      });
      h += '</div>';
    });
    h += '</div>';
    h += '<div class="tscroll"><table class="ptab"><thead><tr><th>Agent</th>' + RUNS.map(function (r) { return '<th>Run ' + r + '</th>'; }).join('') +
      '<th data-tip="bugs that pass in every run">All pass</th><th data-tip="bugs that fail in every run">None pass</th>' +
      '<th data-tip="bugs that pass in some runs and fail in others">Runs disagree</th></tr></thead><tbody>';
    AG.forEach(function (a) {
      var all = 0, none = 0, mixed = 0;
      bugs.forEach(function (b) {
        var v = RUNS.map(function (r) { return b.byRun[a][r]; }).filter(function (x) { return x != null; });
        if (!v.length) return;
        if (v.every(function (x) { return x; })) all++;
        else if (v.every(function (x) { return !x; })) none++;
        else mixed++;
      });
      h += '<tr><td>' + TV.agentHTML(a) + '</td>' + RUNS.map(function (r) {
        var known = bugs.filter(function (b) { return b.byRun[a][r] != null; }).length;
        var p = bugs.filter(function (b) { return b.byRun[a][r] === true; }).length;
        return '<td>' + p + '<span class="muted">/' + known + '</span></td>';
      }).join('') + '<td>' + all + '</td><td>' + none + '</td><td>' + mixed + '</td></tr>';
    });
    return h + '</tbody></table></div></div></section>';
  }

  /* ------------------------------------------------------------------ phase shares */
  function phasePanel() {
    var C = ctx();
    var h = '<section class="card panel' + (C.groups.length > 3 ? ' wide' : '') + '"><h3>Where the actions go</h3><p class="desc">Share of actions per phase.</p>' +
      '<div class="legend lg-inline">' + TV.phaseLegend() + '</div><div class="pshare">';
    C.groups.forEach(function (g) {
      var tot = {}, n = 0;
      g.trajs.forEach(function (t) {
        TV.PHASE_ORDER.forEach(function (p) { var k = (t.metrics || {})[p + '_actions'] || 0; tot[p] = (tot[p] || 0) + k; n += k; });
      });
      h += '<div class="ps-l">' + groupHTML(g) + '<span class="muted small">' + TV.plural(g.trajs.length, 'run') + ' · ' + n + ' actions</span></div><div class="bar100">';
      if (!n) h += '<i class="none"></i>';
      TV.PHASE_ORDER.forEach(function (p) {
        var v = tot[p] || 0;
        if (!v) return;
        var share = v / n;
        h += '<i style="flex:' + v + ' 1 0;background:' + TV.phaseVar(p) + ';color:' + TV.phaseTextVar(p) + '" data-tip="' +
          esc(g.agent + (g.corpus ? '' : ' (yours)') + ' · ' + p + ': ' + v + ' actions (' + TV.pct(share) + ')') + '">' + (share >= 0.07 ? TV.pct(share) : '') + '</i>';
      });
      h += '</div>';
    });
    return h + '</div></section>';
  }

  /* ------------------------------------------------------------------ phase outcomes */
  function outcomePanel() {
    var C = ctx(), G = C.groups;
    var h = '<section class="card panel' + (G.length > 3 ? ' wide' : '') + '"><h3>Phase outcomes</h3><p class="desc">How each phase ended (count at the right).</p>' +
      '<div class="legend lg-inline">' + TV.outcomeLegend() + '</div>' +
      '<div class="phout" style="--nag:' + G.length + '"><span></span>' + G.map(function (g) { return '<span class="bh">' + groupHTML(g) + '</span>'; }).join('');
    TV.PHASE_ORDER.forEach(function (p) {
      h += '<span class="bl">' + TV.phaseChip(p) + '</span>';
      G.forEach(function (g) {
        var c = {}, n = 0;
        g.trajs.forEach(function (t) {
          var row = ((t.subphases || {}).by_phase || {})[p] || {};
          Object.keys(row).forEach(function (o) { c[o] = (c[o] || 0) + row[o]; n += row[o]; });
        });
        h += '<span class="bc"><span class="bar100 mini">' + (n ? TV.OUTCOMES.filter(function (o) { return c[o]; }).map(function (o) {
          var share = c[o] / n;
          return '<i class="o-' + o + '" style="flex:' + c[o] + ' 1 0" data-tip="' + esc(g.agent + (g.corpus ? '' : ' (yours)') + ' · ' + p + ' · ' + c[o] + ' ' + o + ' (' + TV.pct(share) + ') · ' + TV.outcomeDef(p, o)) + '">' +
            (share >= 0.22 ? TV.pct(share) : '') + '</i>';
        }).join('') : '<i class="none"></i>') + '</span><span class="bv">' + n + '</span></span>';
      });
    });
    return h + '</div></section>';
  }

  function render(el) {
    var C = ctx(), ups = C.groups.filter(function (g) { return !g.corpus; });
    var nUp = ups.reduce(function (s, g) { return s + g.trajs.length; }, 0);
    var h = '<p class="stat-head muted">Run ' + C.run + ' of the ' + esc(C.data.config || 'original') + ' configuration: ' + C.bugs.length + ' bugs' +
      (C.hidden ? ' (' + C.hidden + ' removed from view)' : '') + ' × ' + C.agents.length + ' agents' + (nUp ? ', and ' + TV.plural(nUp, 'upload') : '') +
      (C.computing ? ' · updating…' : '') + '</p>';
    h += cards();
    h += '<div class="statgrid">' + passPanel() + phasePanel() + outcomePanel() + '</div>';
    el.innerHTML = h;
  }

  TV.views.stats = { render: render };
})();
