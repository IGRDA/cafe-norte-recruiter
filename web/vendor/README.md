# Vendored scripts

Pinned third-party browser code, fetched once by hand and committed. No package manager, no
build step (D02). Update by re-running the fetch, checking the hash, and recording both.

| File | Package | Version | sha256 | Fetched from |
| --- | --- | --- | --- | --- |
| `daily-js.esm.js` | `@daily-co/daily-js` (`dist/daily-iframe-esm.js`) | 0.94.0 | `399b87d9528b75c62f00d532b3f794c99e303c92d0b2f3ef2c845cd18a1a6615` | `https://unpkg.com/@daily-co/daily-js@0.94.0/dist/daily-iframe-esm.js` |

```bash
curl -sL https://unpkg.com/@daily-co/daily-js@0.94.0/dist/daily-iframe-esm.js -o web/vendor/daily-js.esm.js
shasum -a 256 web/vendor/daily-js.esm.js
```
