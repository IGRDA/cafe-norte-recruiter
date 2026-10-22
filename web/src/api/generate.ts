// `npm run types`: contracts.ts from contracts.schema.json, which `make export-schema` writes from
// the Pydantic models. contracts.test.ts fails when the committed file is stale.
import { readFileSync, writeFileSync } from "node:fs";
import { compile, type JSONSchema } from "json-schema-to-typescript";

const DIR = new URL(".", import.meta.url);
const BANNER = "/* Generated from contracts.schema.json by `npm run types` (after `make export-schema`). Do not edit. */";

export function generate(): Promise<string> {
  const schema = JSON.parse(readFileSync(new URL("contracts.schema.json", DIR), "utf8")) as JSONSchema;
  return compile(schema, "BrowserContracts", {
    bannerComment: BANNER,
    additionalProperties: false,
  });
}

export const OUT = new URL("contracts.ts", DIR);

if (import.meta.main) {
  writeFileSync(OUT, await generate());
}
