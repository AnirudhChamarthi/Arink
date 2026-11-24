// Copies the contract's generated example payloads into src/mocks/fixtures so that mock mode and the
// tests run without the backend. Run after the contract is regenerated: `npm run sync:fixtures`.
import { cpSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../riskbot/contract/generated");
const dest = resolve(here, "../src/mocks");

for (const sub of ["fixtures", "schema"]) {
  const to = join(dest, sub);
  rmSync(to, { recursive: true, force: true });
  mkdirSync(to, { recursive: true });
  const files = readdirSync(join(src, sub)).filter((f) => f.endsWith(".json"));
  for (const f of files) cpSync(join(src, sub, f), join(to, f));
  console.log(`synced ${files.length} ${sub} files -> ${to}`);
}
