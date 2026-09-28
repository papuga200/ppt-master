# elkjs (vendored)

- Package: [elkjs](https://github.com/kieler/elkjs) 0.12.0, the Eclipse Layout Kernel (ELK) compiled to JavaScript.
- File kept: `elk.bundled.js` (the self-contained build, unmodified), with the package's `package.json` and `LICENSE.md`.
- Licence: elkjs is dual-licensed `EPL-2.0 OR GPL-3.0-or-later`. PPT Master uses and redistributes it under the
  **Eclipse Public License 2.0** (full text in `LICENSE.md`). Source code: https://github.com/kieler/elkjs and
  https://github.com/eclipse/elk.
- Used by: `scripts/diagram_layout.py` (through `scripts/diagram_layout_elk.js`, run with Node.js). Nothing else loads it.
- Updating: `npm install elkjs@<version>` in a scratch folder, copy `lib/elk.bundled.js`, `LICENSE.md` and `package.json`
  here, update this notice, and run `tests/test_diagram_layout.py`.
