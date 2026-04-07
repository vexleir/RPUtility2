import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const staticDir = path.join(repoRoot, "app", "web", "static");

function listJsFiles(dir) {
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
    .map((entry) => path.join(dir, entry.name))
    .sort();
}

const files = listJsFiles(staticDir);
if (!files.length) {
  console.log("No frontend JavaScript files found.");
  process.exit(0);
}

let failed = false;

for (const file of files) {
  const rel = path.relative(repoRoot, file);
  try {
    const source = readFileSync(file, "utf8");
    new vm.Script(source, { filename: file });
    console.log(`OK  ${rel}`);
  } catch (error) {
    failed = true;
    console.error(`FAIL ${rel}`);
    process.stderr.write(`${error}\n`);
  }
}

if (failed) {
  process.exit(1);
}

console.log(`Validated ${files.length} frontend JavaScript files.`);
