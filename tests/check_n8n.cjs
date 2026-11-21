// Checks every Treza node in an n8n workflow against the built node's own description:
// each parameter must be a property shown for that resource, operation and node version,
// and option values must be ones the property offers.
// node tests/check_n8n.cjs <a built checkout of treza-labs/n8n-nodes-treza> <workflow.json>
const path = require('path');
const fs = require('fs');
const [dir, file] = process.argv.slice(2);
const { Treza } = require(path.join(dir, 'dist/nodes/Treza/Treza.node.js'));
const description = new Treza().description;
const pkg = require(path.join(dir, 'package.json'));
const wf = JSON.parse(fs.readFileSync(file, 'utf8'));
const type = `${pkg.name}.${description.name}`;
let problems = 0;

function shown(prop, params, version) {
  const show = prop.displayOptions && prop.displayOptions.show;
  if (!show) return true;
  return Object.entries(show).every(([key, wanted]) => {
    if (key === '@version') {
      return wanted.some((w) => (typeof w === 'number' ? w === version : w && w._cnd && w._cnd.gte !== undefined ? version >= w._cnd.gte : false));
    }
    const value = key in params ? params[key] : (description.properties.find((p) => p.name === key && shown(p, params, version)) || {}).default;
    return wanted.includes(value);
  });
}

for (const node of wf.nodes.filter((n) => n.type.startsWith(pkg.name))) {
  if (node.type !== type) { console.log(`${node.name}: unknown type ${node.type} (expected ${type})`); problems++; continue; }
  const versions = Array.isArray(description.version) ? description.version : [description.version];
  if (!versions.includes(node.typeVersion)) { console.log(`${node.name}: typeVersion ${node.typeVersion} not in ${versions}`); problems++; }
  for (const [key, value] of Object.entries(node.parameters)) {
    const props = description.properties.filter((p) => p.name === key && shown(p, node.parameters, node.typeVersion));
    if (props.length === 0) { console.log(`${node.name}: "${key}" is not a parameter shown for this operation`); problems++; continue; }
    const prop = props[0];
    if (prop.type === 'options' && !String(value).startsWith('=') && !prop.options.some((o) => o.value === value)) {
      console.log(`${node.name}: "${key}" = ${JSON.stringify(value)} is not one of ${prop.options.map((o) => o.value)}`); problems++;
    }
    if (prop.type === 'collection' && value && typeof value === 'object') {
      for (const sub of Object.keys(value)) {
        if (!prop.options.some((o) => o.name === sub)) { console.log(`${node.name}: "${key}.${sub}" is not an option of ${key}`); problems++; }
      }
    }
    if (prop.type === 'number' && typeof value !== 'number' && !String(value).startsWith('=')) { console.log(`${node.name}: "${key}" should be a number`); problems++; }
  }
  const required = description.properties.filter((p) => p.required && shown(p, node.parameters, node.typeVersion) && !(p.name in node.parameters) && (p.default === '' || p.default === undefined));
  for (const p of required) { console.log(`${node.name}: required "${p.name}" is missing`); problems++; }
  console.log(`${node.name}: checked ${Object.keys(node.parameters).length} parameters against ${type} v${node.typeVersion}`);
}
const names = new Set(wf.nodes.map((n) => n.name));
for (const [from, out] of Object.entries(wf.connections)) {
  if (!names.has(from)) { console.log(`connection from unknown node ${from}`); problems++; }
  for (const branch of out.main) for (const c of branch) if (!names.has(c.node)) { console.log(`connection to unknown node ${c.node}`); problems++; }
}
console.log(problems ? `${problems} problem(s)` : 'no problems');
process.exit(problems ? 1 : 0);
