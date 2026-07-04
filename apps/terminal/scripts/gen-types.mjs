// Generate src/api/types.gen.ts from the committed OpenAPI snapshot (src/api/openapi.json).
//
// Monorepo: the snapshot is refreshed from the backend (same repo) — run FROM THE REPO ROOT:
//   python -c "import json;from leviathan.graphrag.server import app;print(json.dumps(app.openapi(),indent=2))" \
//     > apps/terminal/src/api/openapi.json
// then `npm --prefix apps/terminal run gen:types`. Committing the snapshot lets the frontend build without
// importing the Python app, and any backend response-shape change becomes a TS compile error here.
import { readFileSync, writeFileSync } from 'node:fs';
import openapiTS, { astToString } from 'openapi-typescript';

const IN = new URL('../src/api/openapi.json', import.meta.url);
const OUT = new URL('../src/api/types.gen.ts', import.meta.url);

const schema = JSON.parse(readFileSync(IN, 'utf8'));
const ast = await openapiTS(schema);
const banner = '/* AUTO-GENERATED from src/api/openapi.json — do not edit. Run `npm run gen:types`. */\n';
writeFileSync(OUT, banner + astToString(ast));
console.log('wrote src/api/types.gen.ts');
