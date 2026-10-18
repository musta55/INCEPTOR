/* TrajecTiers dashboard - the analysis engine, and the corpus under the user's rules.
 *
 * TV.engine   the Python package atif, reached through one of two engines with the same calls:
 *             the local server (python3 -m atif.cli serve: /api/rules, /api/analyze, /api/corpus)
 *             when the page is on a loopback host and it answers, else the package itself run by
 *             Pyodide in a worker (engine/worker.js), which is how the hosted viewer works.
 *               rules()           the lookup tables (built-in and ready-made rows) and the vocabularies
 *               analyze(body)     one uploaded log (atif.upload.request)
 *               corpus(body)      corpus packs re-run under a rule set (atif.upload.corpus_request)
 *             A rejection with .answered is the engine's own answer (a log or a rule to fix);
 *             any other means the engine cannot run here (file://, offline).
 * TV.corpus   the corpus under the current rule set: run-1 summaries of every bug (overview,
 *             statistics, comparisons) or one bug's full trajectories (bug page), re-run from
 *             data/atif/run<k>/bug-<id>.json.gz; the summaries are cached in IndexedDB per
 *             rule set, so a rule set is applied to the corpus once.
 * TV.idb      a small IndexedDB store (uploads, their texts, that cache); every call rejects
 *             where the browser keeps nothing (private windows, some file:// pages).
 * TV.steps    one action's step as the log recorded it (ATIF): the full thought and result,
 *             and the raw JSON, for the details panel. The corpus's come from its packs, an
 *             upload's from the ATIF kept beside it (TV.steps.source, set by the Analyze page).
 *             A page opened from a file cannot fetch the packs: the panel keeps the export's
 *             300-character texts and says why. */
(function () {
  'use strict';
  var TV = window.TV;

  /* ---------------------------------------------------------------- IndexedDB */
  var STORES = ['uploads', 'texts', 'cache'], dbp = null;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error('this browser keeps no data for the page')); return; }
      var req;
      try { req = indexedDB.open('trajectiers', 1); } catch (e) { reject(e); return; }
      req.onupgradeneeded = function () {
        STORES.forEach(function (s) { if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s); });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error('IndexedDB is not available')); };
    });
    dbp.catch(function () { dbp = null; });
    return dbp;
  }
  function tx(store, mode, fn) {
    return db().then(function (d) {
      return new Promise(function (resolve, reject) {
        var t = d.transaction(store, mode), req = fn(t.objectStore(store));
        t.oncomplete = function () { resolve(req ? req.result : undefined); };
        t.onerror = t.onabort = function () { reject(t.error || new Error('IndexedDB: the write failed')); };
      });
    });
  }
  TV.idb = {
    get: function (store, key) { return tx(store, 'readonly', function (s) { return s.get(key); }); },
    put: function (store, key, value) { return tx(store, 'readwrite', function (s) { s.put(value, key); }); },
    del: function (store, key) { return tx(store, 'readwrite', function (s) { s.delete(key); }); },
    all: function (store) { return tx(store, 'readonly', function (s) { return s.getAll(); }); },
    keys: function (store) { return tx(store, 'readonly', function (s) { return s.getAllKeys(); }); }
  };

  /* ---------------------------------------------------------------- engines */
  function answered(msg) { return Object.assign(new Error(msg), { answered: true }); }
  function api(path, body) {
    return fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok || j.error) throw answered(j.error || ('HTTP ' + r.status));
          return j;
        }, function () { throw new Error('no TrajecTiers server here (HTTP ' + r.status + ')'); });   // e.g. a static host
      });
  }
  var SERVER = {
    rules: function () { return api('/api/rules'); },
    analyze: function (body) { return api('/api/analyze', body); },
    corpus: function (body) { return api('/api/corpus', body); }
  };
  function browserEngine() {
    var worker = new Worker('engine/worker.js', { type: 'module' }), calls = {}, next = 0;
    function settle(m) {
      var c = calls[m.id];
      if (!c) return;
      delete calls[m.id];
      if (m.error) { c.reject(m.boot ? new Error(m.error) : answered(m.error)); return; }
      var j = JSON.parse(m.json);
      if (j.error) c.reject(answered(j.error)); else c.resolve(j);
    }
    worker.onmessage = function (e) { settle(e.data); };
    worker.onerror = function (e) {                                // the worker itself failed
      Object.keys(calls).forEach(function (id) { settle({ id: +id, error: e.message || 'the engine failed to start', boot: true }); });
    };
    function call(op, body) {
      return new Promise(function (resolve, reject) {
        var id = ++next;
        calls[id] = { resolve: resolve, reject: reject };
        worker.postMessage({ id: id, op: op, body: body });
      });
    }
    return {
      rules: function () { return call('rules'); },
      analyze: function (body) { return call('analyze', body); },
      corpus: function (body) {
        return call('corpus', { rules: body.rules, summary: body.summary,
          urls: body.paths.map(function (p) { return new URL(p, location.href).href; }) });
      }
    };
  }
  var ENGINE = null, starting = null;
  TV.engine = {
    info: null,
    kind: null,                      // 'server' | 'browser' once started
    usable: function () { return location.protocol !== 'file:' && typeof Worker !== 'undefined'; },
    start: function () {
      if (starting) return starting;
      if (!TV.engine.usable()) return Promise.reject(new Error('a page opened from a file (file://) cannot run the analysis engine'));
      var local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);   // where `serve` may run
      starting = (local ? SERVER.rules() : Promise.reject()).then(function (info) {
        ENGINE = SERVER; TV.engine.kind = 'server'; return info;
      }, function () {
        ENGINE = browserEngine(); TV.engine.kind = 'browser'; return ENGINE.rules();
      }).then(function (info) { TV.engine.info = info; return info; });
      starting.catch(function () { starting = null; });
      return starting;
    },
    analyze: function (body) { return TV.engine.start().then(function () { return ENGINE.analyze(body); }); },
    corpus: function (body) { return TV.engine.start().then(function () { return ENGINE.corpus(body); }); }
  };

  /* ---------------------------------------------------------------- the corpus under the rules */
  var BATCH = 5;                     // packs per engine call (progress steps)
  var KEEP = 4;                      // rule sets whose corpus summaries stay cached
  function packPath(run, bug) { return 'data/atif/run' + run + '/bug-' + encodeURIComponent(bug) + '.json.gz'; }
  function cacheKey(D, rs) {
    return 'ov|' + TV.ruleset.key(rs) + '|' + (D.generated_by || '') + '|' + (D.config || '') + '|run' + (D.run || 1) + '|' + D.bugs.length;
  }
  function prune(keep) {
    TV.idb.keys('cache').then(function (keys) {
      var ov = keys.filter(function (k) { return String(k).indexOf('ov|') === 0 && k !== keep; });
      return Promise.all(ov.slice(0, Math.max(0, ov.length - (KEEP - 1))).map(function (k) { return TV.idb.del('cache', k); }));
    }).catch(function () { /* nothing kept anyway */ });
  }
  TV.corpus = {
    packPath: packPath,
    /* the cached run-1 summaries of D under rs, or null (no computing) */
    cached: function (D, rs) {
      return TV.idb.get('cache', cacheKey(D, rs)).then(function (x) { return x || null; }, function () { return null; });
    },
    /* run-1 summaries of every bug of D (window.TRAJ_OVERVIEW) under rs:
     * {key, vocab, bugs: {bug: {agent: summary}}, hits: {rule id: {actions, trajectories}}};
     * onProgress(done, total) after each batch of packs */
    overview: function (D, rs, onProgress) {
      var key = cacheKey(D, rs);
      return TV.corpus.cached(D, rs).then(function (hit) {
        if (hit) return hit;
        var bugs = D.bugs.map(function (b) { return String(b.bug); }), out = { key: key, vocab: null, bugs: {}, hits: {} }, done = 0;
        var batches = [];
        for (var i = 0; i < bugs.length; i += BATCH) batches.push(bugs.slice(i, i + BATCH));
        if (onProgress) onProgress(0, bugs.length);
        return batches.reduce(function (p, batch) {
          return p.then(function () {
            return TV.engine.corpus({ rules: rs, summary: true, paths: batch.map(function (b) { return packPath(D.run || 1, b); }) }).then(function (res) {
              out.vocab = res.vocab;
              res.packs.forEach(function (pk) {
                out.bugs[pk.bug] = pk.views;
                Object.keys(pk.views).forEach(function (a) {
                  var h = pk.views[a].rule_hits || {};
                  Object.keys(h).forEach(function (id) {
                    var x = out.hits[id] || (out.hits[id] = { actions: 0, trajectories: 0 });
                    x.actions += h[id]; x.trajectories++;
                  });
                });
              });
              done += batch.length;
              if (onProgress) onProgress(done, bugs.length);
            });
          });
        }, Promise.resolve()).then(function () {
          TV.idb.put('cache', key, out).then(function () { prune(key); }, function () { /* not kept */ });
          return out;
        });
      });
    },
    /* put the summaries of res (TV.corpus.overview) into D in place; the outcomes stay */
    apply: function (D, res) {
      D.bugs.forEach(function (b) {
        var mine = res.bugs[String(b.bug)] || {};
        Object.keys(b.agents || {}).forEach(function (a) {
          var s = mine[a], old = b.agents[a];
          if (!s) return;
          s.pass = old.pass;
          s.by_run = old.by_run;
          b.agents[a] = s;
        });
      });
      if (res.vocab) D.vocab = res.vocab;
      return D;
    },
    /* one bug's trajectories (d = window.TRAJ_BUG) re-run under rs, in d's order, with d's
     * outcomes and app name; resolves to d itself, changed in place */
    bug: function (d, rs) {
      var runs = (d.runs || [1, 2, 3]);
      return TV.engine.corpus({ rules: rs, summary: false, paths: runs.map(function (r) { return packPath(r, d.bug); }) }).then(function (res) {
        var by = {};
        res.packs.forEach(function (pk) { Object.keys(pk.views).forEach(function (a) { by[a + '-r' + pk.run] = pk.views[a]; }); });
        d.trajectories = d.trajectories.map(function (t) {
          var n = by[t.agent + '-r' + t.run];
          if (!n) return t;
          n.outcome = t.outcome;
          n.app = t.app;
          return n;
        });
        if (res.vocab) d.vocab = res.vocab;
        return d;
      });
    }
  };

  /* ---------------------------------------------------------------- one step, as recorded */
  var PACKS = {}, ATIF = {}, RAW_OPEN = false;
  function gunzipText(buf) {
    if (buf[0] !== 0x1f || buf[1] !== 0x8b) return Promise.resolve(new TextDecoder().decode(buf));   // a host undid the gzip
    if (typeof DecompressionStream === 'undefined') return Promise.reject(new Error('this browser cannot unpack the corpus files'));
    return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  }
  function pack(run, bug) {
    var path = packPath(run, bug);
    if (!PACKS[path]) {
      PACKS[path] = location.protocol === 'file:' ? Promise.reject(new Error('a page opened from a file (file://) cannot read the corpus files')) :
        fetch(path).then(function (r) {
          if (!r.ok) throw new Error(path + ': HTTP ' + r.status);
          return r.arrayBuffer();
        }).then(function (b) { return gunzipText(new Uint8Array(b)); }).then(JSON.parse);
      PACKS[path].catch(function () { delete PACKS[path]; });
    }
    return PACKS[path];
  }
  /* the trajectory with this scope: the main one, or a sub-agent's (subagent_trajectories) */
  function scoped(traj, scope) {
    if (!scope || scope === 'main') return traj;
    var subs = traj.subagent_trajectories || [];
    for (var k = 0; k < subs.length; k++) {
      if (subs[k].trajectory_id === scope) return subs[k];
      var deeper = scoped(subs[k], scope);
      if (deeper !== subs[k] && deeper) return deeper;
    }
    return null;
  }
  function textOf(x) {                       // a message or result: text, or ATIF content parts
    if (x == null) return '';
    if (typeof x === 'string') return x;
    if (Array.isArray(x)) return x.map(function (p) { return p && p.type === 'text' ? String(p.text || '') : p && p.type ? '[' + p.type + ']' : JSON.stringify(p); }).join('\n');
    return JSON.stringify(x, null, 2);
  }
  TV.steps = {
    /* a page's own ATIF for a trajectory (uploads), or null: the corpus pack */
    source: null,
    atif: function (t) {
      var key = String(t._src || t.id || t.key);
      if (!ATIF[key]) {
        ATIF[key] = TV.steps.source && TV.steps.source(t) || pack(t.run, t.bug).then(function (pk) {
          var x = (pk.trajectories || {})[t.agent];
          if (!x) throw new Error('the corpus file has no ' + t.agent + ' trajectory');
          return x;
        });
        ATIF[key].catch(function () { delete ATIF[key]; });
      }
      return ATIF[key];
    },
    /* {step, call, result, calls, thought, text} of action a of t */
    of: function (t, a) {
      return TV.steps.atif(t).then(function (traj) {
        var tr = scoped(traj, a.scope);
        var step = tr && (tr.steps || []).filter(function (x) { return String(x.step_id) === String(a.step); })[0];
        if (!step) throw new Error('step ' + a.step + ' is not in the log');
        var calls = step.tool_calls || [], results = (step.observation || {}).results || [];
        var k = calls.map(function (c) { return c.tool_call_id; }).indexOf(a.call_id);
        var call = calls[k] || null;
        var result = results.filter(function (r) { return r.source_call_id && r.source_call_id === a.call_id; })[0] ||
          (k >= 0 && !results.some(function (r) { return r.source_call_id; }) ? results[k] : null) || null;
        return { step: step, call: call, result: result, calls: calls.length,
          thought: textOf(step.reasoning_content) || textOf(step.message), text: result ? textOf(result.content) : '' };
      });
    },
    /* fill the details panel el (TV.actionDetailsHTML of a) with the full texts and the raw JSON */
    fill: function (el, t, a) {
      var tag = (t._src || t.id || t.key) + ':' + a.i;
      el.setAttribute('data-for', tag);
      var raw = el.querySelector('.dt-raw'), btn = el.querySelector('[data-raw]');
      function note(which, html) { var n = el.querySelector('[data-full-note="' + which + '"]'); if (n) n.innerHTML = html; }
      var clipped = (a.thought || '').length >= 295 || (a.result || '').length >= 295;
      if (clipped) { note('result', ' · <span class="spin small" aria-hidden="true"></span> loading the full text'); }
      var got = TV.steps.of(t, a);
      got.then(function (x) {
        if (el.getAttribute('data-for') !== tag) return;
        note('thought', ''); note('result', '');
        var th = el.querySelector('[data-full="thought"]'), rs = el.querySelector('[data-full="result"]');
        if (th && x.thought) th.textContent = x.thought;
        if (rs) {
          rs.innerHTML = x.text ? markLines(x.text, a.evidence_line) : '<span class="muted">(empty)</span>';
          var m = rs.querySelector('mark');
          if (m) rs.scrollTop = Math.max(0, m.offsetTop - rs.clientHeight / 2);
        }
        if (clipped) note('result', ' · full text');
      }, function (err) {
        if (el.getAttribute('data-for') !== tag) return;
        if (clipped) note('result', ' · first 300 characters <span class="muted" data-tip="' + TV.esc('The full text could not be loaded: ' + err.message + '. Open the hosted dashboard, or run python3 -m atif.cli serve from the Parser directory.') + '">(why?)</span>');
      });
      function showRaw() {
        raw.hidden = !RAW_OPEN;
        if (btn) btn.setAttribute('aria-pressed', String(RAW_OPEN));
        if (!RAW_OPEN) return;
        raw.innerHTML = '<div class="dt-k">Raw JSON <span class="muted small">the step as the log recorded it (ATIF)</span></div><p class="muted small"><span class="spin small" aria-hidden="true"></span> loading…</p>';
        got.then(function (x) {
          if (el.getAttribute('data-for') !== tag) return;
          var step = Object.assign({}, x.step);
          if (x.calls > 1) {                  // this action's call only, and its result
            step.tool_calls = x.call ? [x.call] : [];
            step.observation = Object.assign({}, step.observation, { results: x.result ? [x.result] : [] });
          }
          var json = JSON.stringify(step, null, 2);
          raw.innerHTML = '<div class="dt-k">Raw JSON <span class="muted small">' + (x.calls > 1 ? '1 of the step\'s ' + x.calls + ' tool calls' : 'the step as the log recorded it (ATIF)') +
            (a.scope && a.scope !== 'main' ? ' · a sub-agent\'s step' : '') + '</span><button type="button" class="btn ghost small" data-copy-raw>Copy</button></div>' +
            '<pre class="dt-code dt-json">' + TV.esc(json) + '</pre>';
          var copy = raw.querySelector('[data-copy-raw]');
          copy.addEventListener('click', function () {
            (navigator.clipboard ? navigator.clipboard.writeText(json) : Promise.reject()).then(function () { copy.textContent = 'Copied'; }, function () { copy.textContent = 'Select and copy'; });
          });
        }, function (err) {
          if (el.getAttribute('data-for') !== tag) return;
          raw.innerHTML = '<div class="dt-k">Raw JSON</div><p class="note">The raw step could not be loaded: ' + TV.esc(err.message) + '. Open the <a href="https://trajectiers.vercel.app/">hosted dashboard</a>, or run <code>python3 -m atif.cli serve</code> from the Parser directory.</p>';
        });
      }
      if (btn) btn.addEventListener('click', function () { RAW_OPEN = !RAW_OPEN; showRaw(); if (RAW_OPEN) raw.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); });
      if (RAW_OPEN) showRaw();
    }
  };
  /* the text with the line(s) of the verdict's evidence marked ("a … b": two lines) */
  function markLines(text, line) {
    var parts = line ? String(line).split(' … ') : [], spans = [];
    parts.forEach(function (p) {
      var at = text.lastIndexOf(p.slice(0, 120));
      if (at >= 0 && p) spans.push([at, at + p.length]);
    });
    spans.sort(function (x, y) { return x[0] - y[0]; });
    var out = '', pos = 0;
    spans.forEach(function (sp) {
      if (sp[0] < pos) return;
      out += TV.esc(text.slice(pos, sp[0])) + '<mark class="evm">' + TV.esc(text.slice(sp[0], sp[1])) + '</mark>';
      pos = sp[1];
    });
    return out + TV.esc(text.slice(pos));
  }
})();
