// Runs ELK (elkjs, vendored under vendor/elkjs, EPL-2.0) on ELK JSON graphs: one graph or an array of graphs on stdin,
// the laid-out graph (or array, in the same order) on stdout. Called by diagram_layout.py; not meant to be run by hand.
'use strict';
const path = require('path');
const ELK = require(path.join(__dirname, 'vendor', 'elkjs', 'elk.bundled.js'));

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  let payload;
  try {
    payload = JSON.parse(input);
  } catch (error) {
    process.stderr.write('diagram_layout_elk: the input is not JSON: ' + error.message + '\n');
    process.exit(2);
  }
  const elk = new ELK();
  const graphs = Array.isArray(payload) ? payload : [payload];
  // a graph ELK cannot lay out (an option it rejects for this graph) must not sink the others: it comes back as null
  Promise.allSettled(graphs.map(graph => elk.layout(graph))).then(settled => {
    const results = settled.map(item => (item.status === 'fulfilled' ? item.value : null));
    if (!Array.isArray(payload) && results[0] === null) {
      const reason = settled[0].reason;
      process.stderr.write('diagram_layout_elk: ELK failed: ' + ((reason && reason.message) || reason) + '\n');
      process.exit(3);
    }
    process.stdout.write(JSON.stringify(Array.isArray(payload) ? results : results[0]));
  });
});
