"""Check a ComfyUI workflow's Treza nodes against the pack's real node classes.

python tests/check_comfyui.py <a checkout of treza-labs/treza-comfyui> <workflow.json>

For each Treza node: the class exists in NODE_CLASS_MAPPINGS, the widget values line up
with the class's widget inputs (seed is followed by control_after_generate), combo values
are offered, numbers are in range, and every link joins matching types.
"""

import json
import sys

sys.path.insert(0, sys.argv[1])
from treza_nodes.nodes import NODE_CLASS_MAPPINGS  # noqa: E402

WIDGET_TYPES = {"STRING", "INT", "FLOAT", "BOOLEAN"}
wf = json.load(open(sys.argv[2]))
problems = []
nodes = {n["id"]: n for n in wf["nodes"]}

for n in wf["nodes"]:
    if not n["type"].startswith("Treza"):
        continue
    cls = NODE_CLASS_MAPPINGS.get(n["type"])
    if not cls:
        problems.append(f"{n['type']}: not a node in the pack")
        continue
    spec = cls.INPUT_TYPES()
    widgets, sockets = [], []
    for group in ("required", "optional"):
        for name, (kind, *rest) in spec.get(group, {}).items():
            opts = rest[0] if rest else {}
            if isinstance(kind, list) or kind in WIDGET_TYPES:
                widgets.append((name, kind, opts))
                if name == "seed":
                    widgets.append(("control_after_generate", ["fixed", "increment", "decrement", "randomize"], {}))
            else:
                sockets.append((name, kind))
    values = n.get("widgets_values", [])
    if len(values) != len(widgets):
        problems.append(f"{n['type']}: {len(values)} widget values for {len(widgets)} widgets {[w[0] for w in widgets]}")
    for (name, kind, opts), value in zip(widgets, values):
        if isinstance(kind, list) and value not in kind:
            problems.append(f"{n['type']}.{name}: {value!r} not in {kind}")
        if kind in ("INT", "FLOAT"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"{n['type']}.{name}: {value!r} is not a number")
            elif not opts.get("min", value) <= value <= opts.get("max", value):
                problems.append(f"{n['type']}.{name}: {value} outside {opts.get('min')}..{opts.get('max')}")
        if kind == "BOOLEAN" and not isinstance(value, bool):
            problems.append(f"{n['type']}.{name}: {value!r} is not true/false")
    named = n.get("widgets_values_named")
    if named and list(named) != [w[0] for w in widgets]:
        problems.append(f"{n['type']}: widgets_values_named keys {list(named)} differ from {[w[0] for w in widgets]}")
    input_names = {i["name"]: i for i in n.get("inputs", [])}
    for name, kind in sockets:
        if name not in input_names or input_names[name]["type"] != kind:
            problems.append(f"{n['type']}: socket input {name} ({kind}) missing or typed {input_names.get(name, {}).get('type')}")
    outs = [(o["name"], o["type"]) for o in n.get("outputs", [])]
    if outs != list(zip(cls.RETURN_NAMES, cls.RETURN_TYPES)):
        problems.append(f"{n['type']}: outputs {outs} differ from {list(zip(cls.RETURN_NAMES, cls.RETURN_TYPES))}")
    print(f"{n['type']}: {len(widgets)} widgets, {len(sockets)} sockets, {len(outs)} outputs checked")

for link_id, src, src_slot, dst, dst_slot, kind in wf["links"]:
    out = nodes[src]["outputs"][src_slot]
    inp = nodes[dst]["inputs"][dst_slot]
    if out["type"] != kind or inp["type"] != kind:
        problems.append(f"link {link_id}: {out['type']} -> {inp['type']} as {kind}")
    if link_id not in (out.get("links") or []) or inp.get("link") != link_id:
        problems.append(f"link {link_id}: not recorded on both ends")

print("\n".join(problems) if problems else "no problems")
sys.exit(1 if problems else 0)
