// Pré-bundle dos tiles do onepieceworldmap.com (FASE 9 / phase-07-map.md).
// Baixa o tile-set Blueworld pra `public/tiles/Blueworld/{z}/{x}/{y}.png` — servido
// localmente pelo Vite (dev) e pelo FastAPI (prod), zero internet em runtime.
//
// Uso:  node scripts/fetch-tiles.mjs [maxZoom]   (default 6; passe 7 pra incluir o
// zoom nativo máximo, +~96MB). Pula 404 (bordas de oceano fora do tile-set).
// Idempotente: pula tiles já baixados (re-rodar completa o que faltou).
import { mkdir, writeFile, stat } from 'node:fs/promises'
import { join } from 'node:path'

const BASE = 'https://onepieceworldmap.com/Blueworld'
const OUT = join(process.cwd(), 'public', 'tiles', 'Blueworld')
// O mundo Blueworld é RETANGULAR (mais largo que alto): a Grand Line corre na
// horizontal. A 1ª versão deste script assumiu um quadrado de 50000 e sub-baixou a
// metade leste — onde East Blue (e Foosha) ficam: coords de ilha com lng até ~64620.
// Medido na fonte (z6): conteúdo em x=0..35, y=0..23. EXTENT_X cobre a largura real;
// EXTENT_Y mantém a altura. A CRS do Map.svelte não muda (mapeamento de X sem offset).
const EXTENT_X = 73728 // 36 tiles em z6 (x=0..35); cobre o leste de East Blue
const EXTENT_Y = 50000 // 25 tiles em z6 (y=0..24); altura do mundo
const TILE_SIZE = 512
const MIN_RES = Math.pow(2, 7) * 2.0 // 256 (mapMaxZoom=7, mapMaxResolution=2.0)
const CONCURRENCY = 8
const MAX_ZOOM = Number(process.argv[2] || 6)

const tilesIn = (extent, z) => Math.ceil((extent * Math.pow(2, z)) / MIN_RES / TILE_SIZE)

async function exists(p) {
  try { await stat(p); return true } catch { return false }
}

async function fetchTile(z, x, y) {
  const dest = join(OUT, String(z), String(x), `${y}.png`)
  if (await exists(dest)) return { status: 'skip', bytes: 0 }
  let res
  try {
    res = await fetch(`${BASE}/${z}/${x}/${y}.png`)
  } catch (e) {
    return { status: 'err', bytes: 0, msg: e.message }
  }
  if (res.status === 404) return { status: 404, bytes: 0 }
  if (!res.ok) return { status: res.status, bytes: 0 }
  const buf = Buffer.from(await res.arrayBuffer())
  await mkdir(join(OUT, String(z), String(x)), { recursive: true })
  await writeFile(dest, buf)
  return { status: 200, bytes: buf.length }
}

// monta a fila de todos os (z,x,y) — grade retangular (nx × ny). Tiles fora do
// conteúdo (oceano) voltam 404 e são pulados.
const queue = []
for (let z = 1; z <= MAX_ZOOM; z++) {
  const nx = tilesIn(EXTENT_X, z)
  const ny = tilesIn(EXTENT_Y, z)
  for (let x = 0; x < nx; x++) for (let y = 0; y < ny; y++) queue.push({ z, x, y })
}

console.log(`Baixando ${queue.length} tiles (z1..${MAX_ZOOM}) com ${CONCURRENCY} conexões → ${OUT}`)

let i = 0, ok = 0, skip = 0, miss = 0, err = 0, bytes = 0
async function worker() {
  while (i < queue.length) {
    const t = queue[i++]
    const r = await fetchTile(t.z, t.x, t.y)
    if (r.status === 200) { ok++; bytes += r.bytes }
    else if (r.status === 'skip') skip++
    else if (r.status === 404) miss++
    else { err++; if (err <= 10) console.error(`ERR ${t.z}/${t.x}/${t.y}: ${r.status} ${r.msg || ''}`) }
    const done = ok + skip + miss + err
    if (done % 200 === 0 || done === queue.length) {
      console.log(`${done}/${queue.length}  ok=${ok} skip=${skip} 404=${miss} err=${err}  ${(bytes / 1e6).toFixed(1)}MB`)
    }
  }
}
await Promise.all(Array.from({ length: CONCURRENCY }, worker))
console.log(`\nDONE  baixados=${ok} já-tinha=${skip} 404=${miss} erros=${err}  total novo=${(bytes / 1e6).toFixed(1)}MB`)
