#!/usr/bin/env node
// skillopt-claude — scaffold a self-evolving CLAUDE.md into a project.
//
//   npx skillopt-claude [init] [targetDir] [--force]
//
// Copies the template payload into targetDir (default: cwd). Existing files are
// skipped unless --force. The template's `gitignore` is restored to `.gitignore`
// (npm renames dotfiles on publish, so it ships without the dot).

import { readdir, mkdir, copyFile, access, stat } from "node:fs/promises";
import { constants } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const TEMPLATE = join(HERE, "..", "template");

// files whose template name differs from the scaffolded name
const RENAME = { gitignore: ".gitignore" };

function parseArgs(argv) {
  const args = argv.slice(2).filter((a) => a !== "init"); // "init" is an optional verb
  const force = args.includes("--force");
  const target = args.find((a) => !a.startsWith("-")) ?? ".";
  return { force, target };
}

async function exists(p) {
  try {
    await access(p, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function copyTree(srcDir, destDir, { force }, report) {
  await mkdir(destDir, { recursive: true });
  for (const entry of await readdir(srcDir, { withFileTypes: true })) {
    const src = join(srcDir, entry.name);
    const name = RENAME[entry.name] ?? entry.name;
    const dest = join(destDir, name);
    if (entry.isDirectory()) {
      await copyTree(src, dest, { force }, report);
    } else {
      if ((await exists(dest)) && !force) {
        report.skipped.push(dest);
        continue;
      }
      await mkdir(dirname(dest), { recursive: true });
      await copyFile(src, dest);
      report.written.push(dest);
    }
  }
}

async function main() {
  const { force, target } = parseArgs(process.argv);

  if (!(await exists(TEMPLATE))) {
    console.error(`skillopt-claude: template payload missing at ${TEMPLATE}`);
    process.exit(1);
  }

  const targetDir = target;
  const report = { written: [], skipped: [] };
  await copyTree(TEMPLATE, targetDir, { force }, report);

  const rel = (p) => relative(process.cwd(), p) || ".";
  console.log(`\n  skillopt-claude → ${rel(targetDir)}\n`);
  for (const f of report.written) console.log(`  + ${rel(f)}`);
  for (const f of report.skipped) console.log(`  · skip (exists) ${rel(f)}`);
  if (report.skipped.length && !force) {
    console.log(`\n  ${report.skipped.length} file(s) skipped. Re-run with --force to overwrite.`);
  }

  console.log(`
  Next steps:
    1. Edit the "Core" section of CLAUDE.md with your project's real instructions.
    2. Install the loop's deps:   uv sync
    3. Set your key:              export ANTHROPIC_API_KEY=...
    4. Try it:                    uv run scripts/evolve.py status

  The Stop hook in .claude/settings.json evolves CLAUDE.md after each session.
  Docs: README.md, AGENTS.md, docs/DESIGN.md
`);
}

main().catch((err) => {
  console.error(`skillopt-claude: ${err.message}`);
  process.exit(1);
});
