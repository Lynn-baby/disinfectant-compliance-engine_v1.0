#!/usr/bin/env node

import LlamaCloud from "@llamaindex/llama-cloud";
import { readFile, writeFile, mkdir } from "fs/promises";
import { basename, join, extname, resolve } from "path";
import { statSync, readdirSync } from "fs";

const SUPPORTED_EXTS = new Set([".pdf", ".docx", ".pptx", ".xlsx"]);
const DEFAULT_OUT = "parsed_docs";

function usage(): never {
  console.error(
    "Usage: LLAMA_CLOUD_API_KEY=<key> npx tsx parse.ts <file|dir> [...] [--out <dir>] [-o <dir>]"
  );
  console.error("  Supported: .pdf .docx .pptx .xlsx");
  console.error("  --out, -o   Output directory (default: ./parsed_docs)");
  process.exit(1);
}

function parseArgs(argv: string[]): { files: string[]; outDir: string } {
  const positional: string[] = [];
  let outDir = "";

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--out" || arg === "-o") {
      outDir = argv[++i] ?? "";
      if (!outDir) usage();
    } else {
      positional.push(arg);
    }
  }

  if (positional.length === 0) usage();

  const files: string[] = [];
  for (const p of positional) {
    const resolved = resolve(p);
    const s = statSync(resolved);
    if (s.isDirectory()) {
      for (const entry of readdirSync(resolved)) {
        if (SUPPORTED_EXTS.has(extname(entry).toLowerCase())) {
          files.push(resolve(resolved, entry));
        }
      }
    } else {
      const ext = extname(resolved).toLowerCase();
      if (!SUPPORTED_EXTS.has(ext)) {
        console.warn(`Skipping unsupported format (${ext}): ${p}`);
        continue;
      }
      files.push(resolved);
    }
  }

  if (files.length === 0) {
    console.error("No supported files found (.pdf .docx .pptx .xlsx).");
    process.exit(1);
  }

  return { files, outDir: outDir ? resolve(outDir) : "" };
}

async function parseDoc(filePath: string, outDir: string, apiKey: string): Promise<void> {
  const client = new LlamaCloud({ apiKey });
  const ext = extname(filePath);
  const fileName = basename(filePath, ext);
  console.log(`\n[1/3] Reading: ${fileName} (${ext})`);

  const buffer = await readFile(filePath);
  const file = new File([buffer], basename(filePath));

  console.log(`[2/3] Uploading & parsing (agentic tier)...`);
  const fileObj = await client.files.create({ file, purpose: "parse" });
  const result = await client.parsing.parse({
    tier: "agentic",
    version: "latest",
    file_id: fileObj.id,
    output_options: {
      markdown: {
        tables: { output_tables_as_markdown: true },
      },
    },
    expand: ["markdown_full"],
  });

  const markdown = result.markdown_full ?? "";
  if (!markdown) {
    console.error(`  WARNING: No markdown output for ${fileName}`);
    return;
  }

  await mkdir(outDir, { recursive: true });
  const outPath = join(outDir, `${fileName}.md`);
  await writeFile(outPath, markdown, "utf-8");
  console.log(`[3/3] Saved: ${outPath} (${markdown.length.toLocaleString()} chars)`);
}

async function main() {
  const apiKey = process.env["LLAMA_CLOUD_API_KEY"];
  if (!apiKey) {
    console.error("ERROR: LLAMA_CLOUD_API_KEY is not set.");
    console.error("Usage: LLAMA_CLOUD_API_KEY=<key> npx tsx parse.ts <file|dir> [...] [--out <dir>]");
    process.exit(1);
  }

  const argv = process.argv.slice(2);
  const { files, outDir } = parseArgs(argv);

  const outputDir = outDir || join(resolve("."), DEFAULT_OUT);
  console.log(`Output: ${outputDir}`);
  console.log(`Files: ${files.length} document(s)`);

  for (const filePath of files) {
    try {
      await parseDoc(filePath, outputDir, apiKey);
    } catch (err) {
      console.error(`FAILED: ${filePath}`);
      console.error(err);
    }
  }

  console.log(`\nDone. ${files.length} file(s) → ${outputDir}`);
}

main();
