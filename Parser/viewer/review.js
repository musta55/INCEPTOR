/* TrajecTiers dashboard - the review of unrecognised steps (atif/diagnose.py), on an upload's
 * page (analyze.html#u=<id>) and on the Lookup tables page (every upload's, merged).
 *
 * A step is unrecognised when its tool, or a program of its shell command, is in no lookup
 * table: it counts as other and takes the phase of the step before it. Each
 * group (one tool or program) comes with a suggested row from fixed name rules; the user picks
 * what it does and adds the row to their lookup tables (TV.ruleset), and the pages analyse
 * everything again with it.
 *
 *   TV.review.html(report, opts)   the card; report = {n_actions, n_unrecognized, n_follow,
 *                                  groups}; opts.where(group) -> HTML after the examples,
 *                                  opts.goto: examples are #links that move the cursor
 *   TV.review.bind(el, onAdded)    its buttons; onAdded(rs, rows) after rows were saved
 *   TV.review.merge(records)       the reports of several uploads as one (tables page) */
(function () {
  'use strict';
  var TV = window.TV, esc = TV.esc;

  function choices(g) {
    var lookup = ((TV.vocab || {}).lookup || {}).actions || [], does = {};
    lookup.forEach(function (x) { does[x.type] = x.does; });
    var sug = g.suggest && g.suggest.row, pick = sug ? (sug.kind === 'shell_tool' ? 'shell:' + sug.value : sug.value) : '';
    var opts = ['<option value=""' + (pick ? '' : ' selected') + '>what does it do?</option>'];
    if (g.kind === 'tool') {
      var arg = sug && sug.kind === 'shell_tool' ? sug.value : 'command';
      opts.push('<option value="shell:' + esc(arg) + '"' + (pick === 'shell:' + arg ? ' selected' : '') + '>runs shell commands (“' + esc(arg) + '”)</option>');
    }
    (TV.vocab.categories || TV.CATEGORIES).forEach(function (c) {
      opts.push('<option value="' + c + '"' + (pick === c ? ' selected' : '') + '>' + c + (does[c] ? ' · ' + esc(does[c]) : '') + '</option>');
    });
    return opts.join('');
  }
  function gkey(g) { return g.kind + '|' + g.key; }

  TV.review = {
    /* the row a choice makes: "shell:<arg>" a shell tool, else an action type */
    row: function (g, choice) {
      if (!choice) return null;
      if (choice.indexOf('shell:') === 0) return { kind: 'shell_tool', field: 'tool', match: g.key, value: choice.slice(6), regex: false, enabled: true };
      return { kind: 'category', field: g.kind === 'program' ? 'program' : 'tool', match: g.key, value: choice, regex: false, enabled: true };
    },
    /* add rows to the user's tables (new ids, after their other rows: later rows win) */
    addRows: function (rows) {
      var rs = TV.ruleset.get(), used = {};
      rs.custom.forEach(function (r) { used[r.id] = 1; });
      rows.forEach(function (r) {
        for (var n = 1; used['R' + n]; n++) { /* next free id */ }
        r.id = 'R' + n;
        used[r.id] = 1;
        rs.custom.push(r);
      });
      return TV.ruleset.save(rs);
    },
    html: function (rep, opts) {
      opts = opts || {};
      var groups = (rep && rep.groups) || [];
      if (!groups.length) return '';
      var nsug = groups.filter(function (g) { return g.suggest; }).length;
      var h = '<section class="card unrec" aria-labelledby="urH"><div class="ur-h"><h2 id="urH">Unrecognized steps <span class="cnt">' +
        (rep.n_actions ? rep.n_unrecognized + ' of ' + rep.n_actions + ' steps' : TV.plural(rep.n_unrecognized, 'step')) + '</span></h2>' +
        (nsug > 1 ? '<button type="button" class="btn small primary" data-ur-all>Add the ' + nsug + ' suggested rows</button>' : '') + '</div>' +
        '<p class="muted small ur-intro">No lookup row matches these, so they count as <b>other</b>. Add a row for each (suggestions come from the tool\'s name; check them).</p><div class="ur-list">';
      groups.forEach(function (g) {
        var ex = (g.examples || []).map(function (x) {
          return (opts.goto ? '<button type="button" class="lnk" data-goto="' + x.i + '">#' + x.i + '</button>' : '<span class="muted">#' + x.i + '</span>') + ' <code>' + esc(x.text || '') + '</code>';
        }).join('<br>');
        h += '<div class="ur-row" data-ur="' + esc(gkey(g)) + '">' +
          '<div class="ur-what"><span class="ur-kind">' + (g.kind === 'tool' ? 'tool' : 'program') + '</span><code class="ur-key">' + esc(g.key) + '</code>' +
          '<span class="muted small">' + TV.plural(g.n, 'step') + ' · now <span class="midchip">' + esc(g.category) + '</span></span></div>' +
          '<div class="ur-ex small">' + ex + (opts.where ? opts.where(g) : '') + '</div>' +
          '<div class="ur-act"><select aria-label="' + esc('What ' + g.key + ' does') + '">' + choices(g) + '</select>' +
          '<button type="button" class="btn small" data-ur-add>Add row</button>' +
          (g.suggest ? '<span class="ur-why muted small">suggested: ' + esc(g.suggest.why) + '</span>' : '<span class="ur-why muted small">no suggestion: pick one</span>') + '</div></div>';
      });
      return h + '</div></section>';
    },
    bind: function (el, rep, onAdded) {
      var byKey = {};
      ((rep && rep.groups) || []).forEach(function (g) { byKey[gkey(g)] = g; });
      el.addEventListener('click', function (e) {
        var one = e.target.closest('[data-ur-add]'), all = e.target.closest('[data-ur-all]'), rows = [];
        if (!one && !all) return;
        (one ? [one.closest('[data-ur]')] : TV.$$('[data-ur]', el)).forEach(function (row) {
          var g = byKey[row.getAttribute('data-ur')], choice = row.querySelector('select').value;
          if (!g) return;
          if (!choice && one) { row.querySelector('select').focus(); row.classList.add('need'); return; }
          var r = TV.review.row(g, all && !choice ? null : choice);
          if (r) rows.push(r);
        });
        if (!rows.length) return;
        TV.$$('button', el).forEach(function (b) { b.disabled = true; });
        onAdded(TV.review.addRows(rows), rows);
      });
      el.addEventListener('change', function (e) { var r = e.target.closest('[data-ur]'); if (r) r.classList.remove('need'); });
    },
    /* the reports of several upload records as one: groups merged by tool or program, with the
     * uploads they come from (g.uploads) */
    merge: function (records) {
      var out = { n_actions: 0, n_unrecognized: 0, n_follow: 0, groups: [] }, by = {};
      records.forEach(function (rec) {
        var rep = (rec.result || {}).unrecognized;
        if (!rep) return;
        out.n_actions += rep.n_actions || 0;
        out.n_unrecognized += rep.n_unrecognized || 0;
        out.n_follow += rep.n_follow || 0;
        (rep.groups || []).forEach(function (g) {
          var k = gkey(g), m = by[k];
          if (!m) {
            m = by[k] = Object.assign({}, g, { examples: [], uploads: [], n: 0, n_follow: 0 });
            out.groups.push(m);
          }
          m.n += g.n;
          m.n_follow += g.n_follow || 0;
          m.uploads.push(rec);
          (g.examples || []).forEach(function (x) { if (m.examples.length < 3) m.examples.push(x); });
        });
      });
      out.groups.sort(function (x, y) { return (x.kind !== 'tool') - (y.kind !== 'tool') || y.n - x.n || String(x.key).localeCompare(y.key); });
      return out;
    }
  };
})();
