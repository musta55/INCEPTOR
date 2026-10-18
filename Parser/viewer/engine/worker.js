/* The viewer's analysis engine when no local server answers (the hosted viewer): the atif
 * package itself, run by Pyodide (CPython in WebAssembly) in this worker, so the page stays
 * responsive and an uploaded log never leaves the browser. atif.zip is written by
 * `python3 -m atif.cli engine`.
 * A module worker (new Worker(url, {type: 'module'})): Pyodide 314 refuses classic workers.
 *
 *   in:  {id, op: 'rules'}                 -> upload.rules_info()
 *        {id, op: 'analyze', body: {...}}  -> upload.request(body)          (one uploaded log)
 *        {id, op: 'corpus', body: {rules, summary, urls: [...]}}
 *                                          -> upload.corpus_request(...)    (corpus packs, fetched
 *                                             and gunzipped here: data/atif/run<k>/bug-<id>.json.gz)
 *   out: {id, json: '<result>'} or {id, error: message, boot: true when the engine never loaded} */
var PYODIDE = 'https://cdn.jsdelivr.net/npm/pyodide@314.0.7/';
var booted = false;

var ready = (async function () {
  var mod = await import(PYODIDE + 'pyodide.mjs');
  var py = await mod.loadPyodide({ indexURL: PYODIDE });
  var zip = await fetch('atif.zip', { cache: 'no-cache' });
  if (!zip.ok) throw new Error('engine/atif.zip: HTTP ' + zip.status);
  py.unpackArchive(await zip.arrayBuffer(), 'zip', { extractDir: '/engine' });
  py.runPython('import sys, json\nsys.path.insert(0, "/engine")\nfrom atif import upload');
  booted = true;
  return py;
})();

/* one corpus pack as JSON text; a host may already have undone the gzip (Content-Encoding) */
async function packText(url) {
  var r = await fetch(url);
  if (!r.ok) throw new Error(url.split('/').slice(-3).join('/') + ': HTTP ' + r.status + ' (run python3 -m atif.cli view --all)');
  var buf = new Uint8Array(await r.arrayBuffer());
  if (buf[0] !== 0x1f || buf[1] !== 0x8b) return new TextDecoder().decode(buf);
  var stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

function call(py, code, body) {
  py.globals.set('REQUEST', body);
  try {
    return py.runPython('json.dumps(' + code + '(json.loads(REQUEST)), ensure_ascii=False, default=str)');
  } finally {
    py.globals.delete('REQUEST');
  }
}

self.onmessage = async function (e) {
  var msg = e.data, py;
  try {
    py = await ready;
  } catch (err) {
    self.postMessage({ id: msg.id, error: String((err && err.message) || err), boot: true });
    return;
  }
  var out;
  try {
    if (msg.op === 'rules') {
      out = py.runPython('json.dumps(upload.rules_info(), ensure_ascii=False, default=str)');
    } else if (msg.op === 'corpus') {
      var b = msg.body || {}, texts;
      try {
        texts = await Promise.all((b.urls || []).map(packText));
      } catch (err) {                        // a missing pack: the page's to explain, not a crash
        self.postMessage({ id: msg.id, json: JSON.stringify({ error: String((err && err.message) || err) }) });
        return;
      }
      out = call(py, 'upload.corpus_request', '{"rules":' + JSON.stringify(b.rules || null) + ',"summary":' + (b.summary ? 'true' : 'false') +
        ',"packs":[' + texts.join(',') + ']}');
    } else {
      out = call(py, 'upload.request', JSON.stringify(msg.body));
    }
    self.postMessage({ id: msg.id, json: out });
  } catch (err) {                          // a fault of the analysis: the Python traceback's last line
    var text = String((err && err.message) || err).trim().split('\n');
    self.postMessage({ id: msg.id, error: 'the analysis failed: ' + text[text.length - 1], boot: !booted });
  }
};
