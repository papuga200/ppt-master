// Routes orthogonal connectors around fixed obstacles with libavoid (adaptagrams, LGPL-2.1-or-later) through the
// libavoid-js WebAssembly build. Called by route_connections.py --engine libavoid; not meant to be run by hand.
// The package is NOT vendored in the fork: its directory comes from argv[2] (PPT_MASTER_LIBAVOID_JS).
// stdin:  {"shapes": [{"id", "x", "y", "w", "h"}],
//          "conns": [{"id", "src": {"shape", "pins": [{"dx", "dy", "dir"}]}, "dst": {...}}],   dir: N | E | S | W
//          (several pins on one end share a class id: libavoid picks the cheapest)
//          "params": {"shapeBufferDistance": 10, "idealNudgingDistance": 8, "segmentPenalty": 60, "crossingPenalty": 200}}
// stdout: {"routes": {"<conn id>": [[x, y], ...]}}
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const pkg = process.argv[2];
if (!pkg) {
  process.stderr.write('libavoid_runner: pass the libavoid-js package directory as the first argument\n');
  process.exit(2);
}
const { AvoidLib } = await import(pathToFileURL(path.join(pkg, 'dist', 'index-node.mjs')).href);

let input = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) input += chunk;
const req = JSON.parse(input);

await AvoidLib.load();
const A = AvoidLib.getInstance();
const router = new A.Router(A.RouterFlag.OrthogonalRouting.value);
const params = { shapeBufferDistance: 10, idealNudgingDistance: 8, segmentPenalty: 60, crossingPenalty: 200,
  fixedSharedPathPenalty: 0, ...(req.params || {}) };
for (const [name, value] of Object.entries(params)) {
  if (A.RoutingParameter[name] !== undefined) router.setRoutingParameter(A.RoutingParameter[name], value);
}
router.setRoutingOption(A.RoutingOption.nudgeOrthogonalSegmentsConnectedToShapes, true);
router.setRoutingOption(A.RoutingOption.nudgeOrthogonalTouchingColinearSegments, true);
router.setRoutingOption(A.RoutingOption.penaliseOrthogonalSharedPathsAtConnEnds, true);

const DIRS = { N: 1, S: 2, W: 4, E: 8 };  // libavoid ConnDirUp, ConnDirDown, ConnDirLeft, ConnDirRight
const shapes = {};
for (const s of req.shapes) {
  shapes[s.id] = new A.ShapeRef(router, new A.Rectangle(new A.Point(s.x, s.y), new A.Point(s.x + s.w, s.y + s.h)));
}
const conns = {};
let pinClass = 1;
for (const c of req.conns) {
  const ends = [];
  for (const end of [c.src, c.dst]) {
    const shape = shapes[end.shape];
    if (!shape) throw new Error(`connector ${c.id} names unknown shape ${end.shape}`);
    const klass = pinClass++;
    for (const pin of end.pins) {
      const made = new A.ShapeConnectionPin(shape, klass, pin.dx, pin.dy, false, 0, DIRS[pin.dir] || 15);
      if (pin.cost) made.setConnectionCost(pin.cost);
    }
    ends.push(new A.ConnEnd(shape, klass));
  }
  const conn = new A.ConnRef(router, ends[0], ends[1]);
  conn.setHateCrossings(true);
  conns[c.id] = conn;
}
router.processTransaction();
const routes = {};
for (const [id, conn] of Object.entries(conns)) {
  const line = conn.displayRoute();
  const pts = [];
  for (let i = 0; i < line.size(); i++) {
    const p = line.at(i);
    pts.push([p.x, p.y]);
  }
  routes[id] = pts;
}
process.stdout.write(JSON.stringify({ routes }));
