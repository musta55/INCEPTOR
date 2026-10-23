/* Corpus page > Statistics: the trajectories of the Trajectories tab (every uploaded run),
 * compared agent by agent. Panels: one card per agent (external pass rate and median steps),
 * the external validation across runs (pass matrix + table), where the actions go
 * (100%-stacked phase shares), and the agent's self-validation (one 100% bar per agent). Bars are neutral or wear the
 * phase / outcome colour they encode; agents are told apart by name, never by colour. Counts
 * come from the phase taxonomy's metrics (atif/phase.py), which leave polls out. Context:
 * TV.overview (page-overview.js): agents, runs, rows (the table's bugs), groups (an agent's
 * runs) and href(row, agent, run). */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;

  function ctx() { return TV.overview; }
  function groupHTML(g) { return '<span class="gname">' + TV.agentHTML(g.agent) + '</span>'; }
  function fmt1(x) { return x == null ? '–' : (Math.round(x * 10) / 10).toString(); }
  function passAt(row, a, r) { var c = row.cells[a], x = c && c.at[r]; return x ? x.pass : undefined; }

  /* ------------------------------------------------------------------ one card per agent */
  function cards() {
    var C = ctx();
    return '<section class="scards">' + C.groups.map(function (g) {
      var ts = g.trajs, known = ts.filter(function (t) { return t.pass != null; }), pass = known.filter(function (t) { return t.pass === true; }).length;
      var model = ts.map(function (t) { return t.model; }).filter(Boolean)[0] || '';
      var nb = C.rows.filter(function (row) { return row.cells[g.agent]; }).length;
      var line = TV.plural(ts.length, 'run') + ' of ' + TV.plural(nb, 'bug');
      return '<article class="card scard">' +
        '<div class="sc-h">' + groupHTML(g) + '<span class="model" title="model">' + esc(model) + '</span></div>' +
        '<div class="hero" data-tip="' + esc(TV.EXTERNAL_DEF) + '"><b>' + (known.length ? pass + '<small>/' + known.length + '</small>' : '–') + '</b><span>' +
          (known.length ? 'runs pass external validation · ' + TV.pct(pass / known.length) : 'no external validation set') + '</span></div>' +
        '<div class="sc-l">' + esc(line) + '</div>' +
        '<div class="sc-k"><span><b>' + fmt1(TV.median(ts.map(function (t) { return t.n_actions; }))) + '</b> median steps per trajectory</span></div>' +
        '</article>';
    }).join('') + '</section>';
  }

  /* ------------------------------------------------------------------ pass matrix + table */
  function passPanel() {
    var C = ctx(), AG = C.agents, RUNS = C.runs, bugs = C.rows, nb = bugs.length;
    var h = '<section class="card panel wide"><h3 data-tip="' + esc(TV.EXTERNAL_DEF) + '">External validation across runs</h3>' +
      '<p class="desc">Runs ' + RUNS.join(', ') + ' · green = passed, red = failed · click to open.</p>';
    h += '<div class="pm-wrap"><div class="pm">';
    AG.forEach(function (a) {
      h += '<div>' + TV.agentHTML(a) + '</div><div class="pm-grid" style="--nb:' + nb + '" role="img" aria-label="' + esc(a) + ' pass matrix">';
      RUNS.forEach(function (r) {
        h += '<span class="pm-r">r' + r + '</span>';
        bugs.forEach(function (b) {
          var v = passAt(b, a, r), tip = b.label + ' · ' + a + ' · run ' + r + ': ';
          h += v === undefined ? '<span class="nil" data-tip="' + esc(tip + 'no run') + '"></span>' :
            '<a class="' + TV.oc(v) + '" href="' + C.href(b, a, r) + '" data-tip="' + esc(tip + 'external validation ' + TV.EXTERNAL_WORD[TV.oc(v)]) + '"></a>';
        });
      });
      h += '</div>';
    });
    h += '</div>';
    h += '<div class="tscroll"><table class="ptab"><thead><tr><th rowspan="2">Agent</th>' +
      '<th class="grp" colspan="' + (RUNS.length + 3) + '" data-tip="' + esc(TV.EXTERNAL_DEF) + '">External validation</th></tr><tr>' +
      RUNS.map(function (r) { return '<th data-tip="bugs that pass in run ' + r + '">Run ' + r + '</th>'; }).join('') +
      '<th data-tip="bugs that pass in every run">All pass</th><th data-tip="bugs that fail in every run">None pass</th>' +
      '<th data-tip="bugs that pass in some runs and fail in others">Runs disagree</th></tr></thead><tbody>';
    AG.forEach(function (a) {
      var all = 0, none = 0, mixed = 0;
      bugs.forEach(function (b) {
        var v = RUNS.map(function (r) { return passAt(b, a, r); }).filter(function (x) { return x != null; });
        if (!v.length) return;
        if (v.every(function (x) { return x; })) all++;
        else if (v.every(function (x) { return !x; })) none++;
        else mixed++;
      });
      h += '<tr><td>' + TV.agentHTML(a) + '</td>' + RUNS.map(function (r) {
        var known = bugs.filter(function (b) { return passAt(b, a, r) != null; }).length;
        var p = bugs.filter(function (b) { return passAt(b, a, r) === true; }).length;
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
          esc(g.agent + ' · ' + p + ': ' + v + ' actions (' + TV.pct(share) + ')') + '">' + (share >= 0.07 ? TV.pct(share) : '') + '</i>';
      });
      h += '</div>';
    });
    return h + '</div></section>';
  }

  /* ------------------------------------------------------------------ phase outcomes */
  function outcomePanel() {
    var C = ctx(), G = C.groups;
    var h = '<section class="card panel' + (G.length > 3 ? ' wide' : '') + '"><h3>Self-validation outcomes</h3><p class="desc">How the Validation phase ended, judged by the agent\'s own builds, compilations and tests (count at the right).</p>' +
      '<div class="legend lg-inline">' + TV.outcomeLegend() + '</div>' +
      '<div class="phout" style="--nag:' + G.length + '"><span></span>' + G.map(function (g) { return '<span class="bh">' + groupHTML(g) + '</span>'; }).join('');
    TV.VERDICT_PHASES.forEach(function (p) {
      h += '<span class="bl">' + TV.phaseChip(p) + '</span>';
      G.forEach(function (g) {
        var c = {}, n = 0;
        g.trajs.forEach(function (t) {
          var row = ((t.subphases || {}).by_phase || {})[p] || {};
          Object.keys(row).forEach(function (k) { var o = TV.outcomeOf(k); c[o] = (c[o] || 0) + row[k]; n += row[k]; });
        });
        h += '<span class="bc"><span class="bar100 mini">' + (n ? TV.OUTCOMES.filter(function (o) { return c[o]; }).map(function (o) {
          var share = c[o] / n;
          return '<i class="o-' + o + '" style="flex:' + c[o] + ' 1 0" data-tip="' + esc(g.agent + ' · ' + p + ' · ' + c[o] + ' ' + o + ' (' + TV.pct(share) + ') · ' + TV.outcomeDef(p, o)) + '">' +
            (share >= 0.22 ? TV.pct(share) : '') + '</i>';
        }).join('') : '<i class="none"></i>') + '</span><span class="bv">' + n + '</span></span>';
      });
    });
    return h + '</div></section>';
  }

  function render(el) {
    var h = cards();
    h += '<div class="statgrid">' + passPanel() + phasePanel() + outcomePanel() + '</div>';
    el.innerHTML = h;
  }

  TV.views.stats = { render: render };
})();
