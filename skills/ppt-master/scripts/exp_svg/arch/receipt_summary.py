#!/usr/bin/env python3
"""Lossless findings view of a retained receipt; never changes readiness or geometry.

See scripts/docs/experimental-authoring-tools.md for tool contracts.
Usage: python receipt_summary.py --help
Examples: use current measured JSON; no slide is written.
Dependencies: standard library and Pillow through architecture evaluation.
"""
from __future__ import annotations

import argparse, json, hashlib
from pathlib import Path
import sys
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from console_encoding import configure_utf8_stdio  # noqa: E402


def compact(d: dict, ids: tuple = ()) -> dict:
    result={k:d.get(k) for k in ('tool','version','status','input_sha256','scene_sha256','elapsed_s','capacity_fit','ready','delivery_state','coverage','blocking_constraints','warnings','residual_constraints','unsatisfied_constraints') if k in d}
    r=d.get('result',d.get('geometry',{}))
    result['geometry_counts']={k:len(r.get(k,{})) for k in ('boxes','objects','label_boxes','routes','buses')}
    result['spacing_scale']=r.get('spacing_scale')
    selected=set(ids)
    for f in d.get('blocking_constraints',[]):
        if f.get('id'): selected.add(f['id'])
        for key in ('with','zones','by'):
            selected.update(x for x in f.get(key,[]) if isinstance(x,str))
    result['selected_geometry']={k:{i:v for i,v in r.get(k,{}).items() if i in selected or any(i.startswith(s+':') for s in selected)} for k in ('boxes','label_boxes','routes')}
    result['scope']='All original findings/readiness/coverage retained. Geometry only for finding-related or requested IDs. Full authoritative receipt remains available; this view proves neither aesthetics nor native export.'
    return result

def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    ap=argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--in',dest='source',type=Path,required=True); ap.add_argument('--out',type=Path); ap.add_argument('--ids',nargs='*',default=[]); a=ap.parse_args(argv)
    raw=a.source.read_bytes(); d=json.loads(raw.decode('utf-8-sig')); c=compact(d,a.ids); c['full_receipt_sha256']=hashlib.sha256(raw).hexdigest()
    text=json.dumps(c,indent=2,ensure_ascii=True)
    if a.out:
        assert a.out.resolve()!=a.source.resolve()
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text,encoding='utf-8')
        print(json.dumps({'view':str(a.out),'bytes':len(text.encode('utf-8')),'ready':c.get('ready'),'blockers':len(c.get('blocking_constraints',[])),'warnings':len(c.get('warnings',[])),'full_receipt_sha256':c['full_receipt_sha256']}))
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
