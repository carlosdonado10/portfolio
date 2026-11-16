import { readFileSync } from "node:fs"
import { gzipSync } from "node:zlib"

const LIMIT = 8 * 1024
const file = new URL("../dist/notify.js", import.meta.url)
const size = gzipSync(readFileSync(file)).length
console.log(`dist/notify.js gzip: ${size} bytes (limit ${LIMIT})`)
if (size > LIMIT) {
  console.error("notify.js exceeds the gzip size budget")
  process.exit(1)
}
