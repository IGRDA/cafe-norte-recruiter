// @vitest-environment node
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { generate, OUT } from "./generate";

it("contracts.ts is generated from the current schema", async () => {
  expect(readFileSync(OUT, "utf8"), "run `make export-schema`").toBe(await generate());
});
