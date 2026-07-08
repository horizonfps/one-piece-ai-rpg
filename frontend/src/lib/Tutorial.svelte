<script>
  import { onMount } from 'svelte'
  import { getPlayerGuide } from './api.js'
  import { t, getLocale } from './i18n.svelte.js'

  // Renders the player guide markdown served by the backend.
  // Minimal renderer for the subset the guide uses: headings, one-level lists, fences, bold, inline code.
  let { onback } = $props()

  let blocks = $state([])
  let error = $state(null)

  function inline(text) {
    // Bold and inline code become spans; the rest is plain text.
    const spans = []
    const re = /\*\*([^*]+)\*\*|`([^`]+)`/g
    let last = 0
    let m
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) spans.push({ t: text.slice(last, m.index) })
      if (m[1] !== undefined) spans.push({ t: m[1], b: true })
      else spans.push({ t: m[2], c: true })
      last = m.index + m[0].length
    }
    if (last < text.length) spans.push({ t: text.slice(last) })
    return spans
  }

  function parse(md) {
    const out = []
    let para = []
    let list = null
    let code = null

    const flushPara = () => {
      if (para.length) out.push({ kind: 'p', spans: inline(para.join(' ')) })
      para = []
    }
    const flushList = () => {
      if (list) out.push(list)
      list = null
    }

    for (const rawLine of md.split('\n')) {
      const line = rawLine.replace(/\s+$/, '')
      if (code) {
        if (line.trim() === '```') {
          out.push({ kind: 'code', text: code.lines.join('\n') })
          code = null
        } else code.lines.push(rawLine)
        continue
      }
      if (line.trim().startsWith('```')) {
        flushPara(); flushList()
        code = { lines: [] }
        continue
      }
      const h = line.match(/^(#{1,4})\s+(.*)$/)
      if (h) {
        flushPara(); flushList()
        out.push({ kind: 'h', level: h[1].length, spans: inline(h[2]) })
        continue
      }
      const li = line.match(/^(\s*)-\s+(.*)$/)
      if (li) {
        flushPara()
        if (!list) list = { kind: 'list', items: [] }
        const item = { text: li[2], sub: [] }
        if (li[1].length > 0 && list.items.length) list.items[list.items.length - 1].sub.push(item)
        else list.items.push(item)
        continue
      }
      if (line.trim() === '') {
        flushPara(); flushList()
        continue
      }
      if (list) {
        // Wrapped continuation of the previous item.
        const items = list.items
        const lastTop = items[items.length - 1]
        const target = lastTop.sub.length ? lastTop.sub[lastTop.sub.length - 1] : lastTop
        target.text += ' ' + line.trim()
        continue
      }
      para.push(line.trim())
    }
    flushPara(); flushList()
    if (code) out.push({ kind: 'code', text: code.lines.join('\n') })
    return out
  }

  onMount(async () => {
    try {
      const g = await getPlayerGuide(getLocale())
      blocks = parse(g.markdown ?? '')
    } catch (e) {
      error = String(e)
    }
  })
</script>

{#snippet spans(list)}
  {#each list as s}
    {#if s.b}<strong>{s.t}</strong>{:else if s.c}<code>{s.t}</code>{:else}{s.t}{/if}
  {/each}
{/snippet}

<main>
  <header>
    <p class="kicker">One Piece RPG</p>
    <h1>{t('tutorial.title')}</h1>
  </header>

  <section class="panel guide">
    <div class="panel-head">
      <h2>{t('tutorial.guide')}</h2>
      <button class="ghost" onclick={onback}>{t('common.back')}</button>
    </div>

    {#if error}
      <p class="err">{t('tutorial.load_error', { msg: error })}</p>
    {:else}
      {#each blocks as blk, i (i)}
        {#if blk.kind === 'h'}
          {#if blk.level <= 1}
            <h2 class="g-h1">{@render spans(blk.spans)}</h2>
          {:else if blk.level === 2}
            <h3 class="g-h2">{@render spans(blk.spans)}</h3>
          {:else}
            <h4 class="g-h3">{@render spans(blk.spans)}</h4>
          {/if}
        {:else if blk.kind === 'p'}
          <p class="g-p">{@render spans(blk.spans)}</p>
        {:else if blk.kind === 'code'}
          <pre class="g-code">{blk.text}</pre>
        {:else if blk.kind === 'list'}
          <ul class="g-list">
            {#each blk.items as item}
              <li>
                {@render spans(inline(item.text))}
                {#if item.sub.length}
                  <ul>
                    {#each item.sub as sub}
                      <li>{@render spans(inline(sub.text))}</li>
                    {/each}
                  </ul>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      {/each}
    {/if}
  </section>
</main>

<style>
  .guide {
    max-width: 720px;
  }
  .g-h1 {
    margin: 1.6rem 0 0.5rem;
    font-size: 1.15rem;
  }
  .g-h2 {
    margin: 1.4rem 0 0.4rem;
    font-size: 0.98rem;
  }
  .g-h3 {
    margin: 1.1rem 0 0.3rem;
    font-size: 0.88rem;
    color: var(--ink-dim);
  }
  .g-p {
    margin: 0.45rem 0;
    font-size: 0.88rem;
    line-height: 1.65;
  }
  .g-list {
    margin: 0.45rem 0;
    padding-left: 1.2rem;
    display: grid;
    gap: 0.35rem;
    font-size: 0.88rem;
    line-height: 1.6;
  }
  .g-list ul {
    margin-top: 0.35rem;
    padding-left: 1.1rem;
    display: grid;
    gap: 0.3rem;
    list-style: circle;
  }
  .g-code {
    margin: 0.6rem 0;
    padding: 0.6rem 0.8rem;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--bg-raised);
    font-size: 0.78rem;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
  }
  code {
    padding: 0.05rem 0.3rem;
    border-radius: 4px;
    background: var(--bg-raised);
    border: 1px solid var(--line);
    font-size: 0.82em;
  }
  .err {
    color: var(--down, #c66);
    font-size: 0.85rem;
  }
</style>
