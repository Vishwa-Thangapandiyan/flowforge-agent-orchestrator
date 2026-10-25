#!/usr/bin/env node
// `npx flowforge-map …` (D49): the same words as the `flowforge` command, with no Python.
"use strict";
require("../lib/launcher").main().then((code) => process.exit(code), (err) => {
  process.stderr.write(`flowforge-map: ${err && err.message ? err.message : err}\n`);
  process.exit(1);
});
