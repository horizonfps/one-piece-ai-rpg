// Sonda o tile-set do onepieceworldmap.com pra descobrir, por zoom, quais índices
// existem e o tamanho médio — antes de baixar tudo. NÃO escreve nada em disco.
const BASE = 'https://onepieceworldmap.com/Blueworld'
const MAX_ZOOM = 7
const MAP_EXTENT = 50000
const TILE_SIZE = 512
const MIN_RES = Math.pow(2, MAX_ZOOM) * 2.0 // 256

const tilesPerSide = (z) => Math.ceil((MAP_EXTENT * Math.pow(2, z)) / MIN_RES / TILE_SIZE)

async function head(z, x, y) {
  const url = `${BASE}/${z}/${x}/${y}.png`
  try {
    const res = await fetch(url)
    const len = res.ok ? (await res.arrayBuffer()).byteLength : 0
    return { ok: res.ok, status: res.status, len }
  } catch (e) {
    return { ok: false, status: 'ERR ' + e.message, len: 0 }
  }
}

for (let z = 1; z <= MAX_ZOOM; z++) {
  const n = tilesPerSide(z)
  const mid = Math.floor(n / 2)
  const probes = [
    [0, 0], [mid, mid], [n - 1, n - 1], [n - 1, 0], [0, n - 1],
  ]
  const results = await Promise.all(probes.map(([x, y]) => head(z, x, y).then((r) => ({ x, y, ...r }))))
  const found = results.filter((r) => r.ok)
  const avg = found.length ? Math.round(found.reduce((a, r) => a + r.len, 0) / found.length) : 0
  console.log(
    `z=${z} side=${n} (${n * n} tiles)  amostras=${results.map((r) => `${r.x},${r.y}:${r.ok ? r.len : r.status}`).join('  ')}  avg=${avg}B`,
  )
}
