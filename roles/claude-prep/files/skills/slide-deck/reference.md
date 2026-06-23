# slide-deck — reference

Design system, conventions, the live-graph config, and the gotchas. Worked
example: `vps_setup/local/etl/graph-etl-deck.html`.

## Design system (CSS vars in template.html)

| var | meaning | use for |
|-----|---------|---------|
| `--src`  #3b82f6 blue  | source / inputs   | the "from" side, input tables |
| `--dst`  #22c55e green | target / output   | the "to" side, the thing produced |
| `--accent` #f59e0b amber | highlight        | shared/derived nodes, the payoff number |
| `--bad`  #ef4444 red   | failure           | failure-mode slides |

Helper classes: `.src .dst .amber .bad .muted` (text colors), `.pill` (tag),
`.cols` (equal columns), `.grid5` + `.stat`/`.big-num`/`.lbl` (number grid),
`.kbd` (key cap). `section.center` centers a slide.

## Slide-writing rules

- **One idea per slide.** If a slide needs two diagrams, it's two slides.
- **Terse.** Phrases, not paragraphs. The detail goes in `<aside class="notes">`.
- **Every slide gets speaker notes** — they're also the source for the narration doc.
- **Accurate.** Node labels, rel names, endpoints, model ids, numbers all come
  from source. Label anything not-yet-built as "planned" on the slide itself.
- **Standard arc** (drop what doesn't apply, don't pad):
  Title → One-liner → Where it fits → Core concept → Inputs → Architecture/Model
  → How it runs → Key mechanism → Spotlight (why bother) → Failure modes →
  Numbers → Live graph → Recap.

## Animated flow diagrams (PREFER over Mermaid for traffic/request flows)

Mermaid renders static, dated-looking boxes. For anything that shows *flow / traffic /
a request moving through hops*, use the template's animated `.flow` component instead:
glass node cards joined by connector links with a **glowing packet that travels in the
flow direction** + a directional arrowhead + a flowing-gradient pulse. Palette-agnostic
(`color-mix(var(--src)…)`), responsive (stacks vertically on phones), respects
`prefers-reduced-motion`. Keep Mermaid only for **static structure** (data models, ER,
class/graph shapes) where there's no direction to animate.

```html
<div class="flow">
  <div class="node src">You<small>browser</small></div>   <!-- .src/.dst/.hi/.bad tint the border+glow -->
  <div class="link"></div>                                  <!-- animated forward packet → -->
  <div class="node hi">Service</div>                        <!-- .hi = focal node -->
  <div class="link lbl"><span class="cap">label</span></div><!-- captioned link -->
  <div class="node dst">Sink</div>
</div>
```

- `.flow.vert` → vertical stack (use when >5 nodes so they don't cramp; arrows point down).
- `.link.back` → return packet (flows the other way, `--dst` colored).
- `.bilink` wrapping two `<span class="link">` + `<span class="link back">` → a **two-way**
  connector (forward + return tracks). Use this for bidirectional media (e.g. WebRTC) —
  do NOT fake a return row with `visibility:hidden` placeholder nodes (reads as missing boxes).
- **Node text sizing:** default `.72em` (desktop) bumps to `1.05em` + 60–84% width on mobile.
  Keep main label short (1–3 words); put detail in `<small>`. Verify ≤6 nodes fit one row at
  1280px, else go `.flow.vert`.

## Mermaid conventions (static structure only)

- Use `<pre class="mermaid">…</pre>`. The template renders them **lazily per
  slide** (reveal hides off-screen slides, so init-on-load renders them at 0px
  width and they break). Do not switch to `startOnLoad:true`.
- Highlight the focal node: `classDef me fill:#064e3b,stroke:#22c55e,...; class X me;`
- Two-tone data models: blue `classDef` for 1:1 nodes, amber for shared/derived.
- Keep labels short; long edge labels wrap badly.

## Live graph config (Enhancement 1)

`window.DECK_GRAPH` at the top of the deck:

```js
window.DECK_GRAPH = {
  enabled: true,
  serverUrl: "bolt://localhost:7687",
  serverUser: "neo4j",
  serverPassword: "…",                 // localhost-presentation only; don't commit remote creds
  initialCypher: "MATCH (n)-[r]->(m) RETURN n,r,m LIMIT 75",
  caption: "Live from bolt://localhost:7687",
  labels: { Session:{label:'title'}, File:{label:'path'} },  // node prop to show
  relationships: { HAS_SESSION:{}, TOUCHES_FILE:{} }
};
```

- neovis.js connects over Bolt-via-WebSocket from the browser — Neo4j must be
  reachable from where the deck is *viewed*. Renders only when its slide is shown.
- If Bolt is unreachable the slide shows a fallback message; the deck still opens.
  So a deck is safe to ship/screenshot offline — set real creds only when
  presenting next to a running Neo4j.
- `--no-graph`: set `enabled:false` and delete the live-graph `<section>`.

**Styling (baked into the template's neovis IIFE — config-free).** The `labels.<L>.label`
prop is the *caption*, and neovis renders its FULL value, so a long property (a memory
summary, a message body) becomes a giant unreadable node label. The template wraps each
label with NeoVis advanced config that **truncates the caption to ~32 chars** and moves the
full text to a **hover tooltip** (dark-glassy `.vis-tooltip`). It also applies a per-node
**purple-glow theme** (so neovis doesn't fall back to vis.js default light-blue), a tuned
`forceAtlas2Based` physics with `stabilization.fit` + an on-`completed` `network.fit()` so
even **edge-less / disconnected nodes cluster and stay in view** (don't get flung
off-canvas), and a **styled empty-state** ("Graph is empty…") when zero nodes return. `#viz`
is 520px tall, centered, max-width 1000px. None of this needs per-deck config — just set
`DECK_GRAPH`. (Distilled from the bruce-deck `:BruceMemory` graph, whose disconnected
paragraph-captioned nodes exposed all of the above.)

## Verify + export (Enhancement 2)

- **Verify (mandatory before "done"):** `bash assets/verify.sh <deck.html>` prints
  a URL + server PID. Then Playwright `browser_navigate` to `…#/0,#/1,…`,
  `browser_take_screenshot` each, and `browser_console_messages level=error`.
  Look for: blank slides, content overflow, a `pre.mermaid` still showing raw
  text (render failed), missing diagrams. Kill the server **by PID** when done.
- **Export:** `bash assets/export.sh <deck.html>` → `<deck>.pdf` + `slides/*.png`
  (decktape; falls back to headless-Chrome `?print-pdf`).

## NotebookLM narration companion

Write `<name>-narration.md`: a plain-language walkthrough assembled from the
speaker notes (one short section per slide, no jargon without a gloss). The user
uploads it to NotebookLM for an audio/video overview + Q&A. Keep it standalone —
it should read correctly without seeing the slides.

## Mobile / responsive (built into the template)

reveal.js fit-scales the fixed `width×height` canvas to the viewport, so on a phone a
1280-wide canvas scales to ~0.3× and **all text shrinks**, regardless of `font-size`.
The template fixes this by using a **narrower, taller canvas on mobile** (720×1000 vs
1280×760) so the fit-scale is ~0.55× → text renders far bigger. Detected once at init:
`const _mobile = matchMedia('(max-width:760px)').matches`. Paired `@media (max-width:760px)`
rules stack `.cols` vertically, drop `.grid5` to 2 columns, shrink tables, and wrap long
`pre code` lines (`white-space:pre-wrap`). Tall Mermaid is capped (`svg{max-height:560px}`).
Verify at 390×844 — LR mermaids with many nodes still cramp; prefer ≤5 nodes or split.

## Enhancement 3: voiceovers (Voicebox "Him-Mentor")

Per-slide narration spoken in the cloned **Qwen "Him-Mentor"** voice, played on slide change.

- **Source of truth = the speaker notes.** `assets/gen-voiceovers.py <deck.html>` parses each
  top-level `<section>`'s `<aside class="notes">`, strips HTML, and POSTs to the Voicebox
  server, writing `<deck-dir>/voiceovers/slide-<i>.wav` (i = reveal horizontal index).
- **API:** `POST http://localhost:17493/generate/stream` → returns a WAV (24 kHz mono).
  Body: `{profile_id, text, engine:"qwen", model_size:"0.6B", language:"en", normalize:true}`.
  Him-Mentor profile id `7f5a70c8-4ec9-4be1-9a38-cc15568f03f1` (override `--profile`).
- **Playback:** the template's `#vo-bar` toggle + `window.playVO(indexh)` on `slidechanged`.
  First toggle click is the user gesture that unlocks autoplay. Missing files are ignored,
  so the deck works with or without generated audio.
- **Voicebox must be running** (`cd voicebox && podman-compose up -d`) — and it uses the GPU.
  On a 6 GB card already running kokoro/whisper (push-to-talk), starting Voicebox can contend;
  generate when the GPU is free, then it's static WAVs (no Voicebox needed to present).
- Remove the `#vo-bar` div + the VO `<script>` + `window.DECK_VO` if a deck has no narration.

## Background music (scored bed under the narration)

The same `#vo-bar` toggle also runs a looping music bed, driven by `window.DECK_BG` and the
`#bg-audio` element (both already in the template; the playback IIFE is shared verbatim with
every deck). Levels and fade DIRECTION are fixed rules — don't change them per deck:

- **`base: 0.15`** — bed sits at **15%** under the voice while a voiceover is playing.
- **`swell: 0.25`** — bed rises to **25%** when that slide's voiceover **ends** (fills silence).
- **On slide change** the bed **dips out** (`FADE_OUT 350ms`), then **fades back to base** as the
  next slide starts (`FADE_IN 900ms`); the swell fade is `1400ms`.
- **`tracks: […]`** = a per-slide arc (ONE entry per slide; index clamps past the end). When the
  next slide's track **differs** it **crossfades** (dip → swap → recover); when it's the **same**
  track it stays continuous (dip + recover, no reload). Omit `tracks` and set **`src`** for a
  single bed across the whole deck.
- Track files live in **`bg/`** next to the deck (mp3). Source library: `~/Music/bg_music/`
  (the_glass_lobby, salt_air_after_dark, modular_intent, wood-paneled_afternoon, Clearance_Confirmed).
  Copy the ones you map into the deck's `bg/`; on decks.aicortex.cloud they're shared at `/opt/compose/decks/bg/`.
- Remove `window.DECK_BG` + the `#bg-audio` element to disable music (voiceovers still work).

## Pronunciation fixes (TTS lexicon in gen-voiceovers.py)

Qwen3-TTS mispronounces brand/jargon words (e.g. it says "LiveKit" with a short-i). Fixes live in
**`apply_pronunciations(text)`** in `assets/gen-voiceovers.py`, applied to the narration **right before
synthesis** — so the on-screen speaker notes and `narration.md` stay clean/readable while the audio says it
right. Do NOT hand-respell words inside the deck's `<aside class="notes">`; add them to the map instead.

- **Add a fix:** append one `re.sub(...)` line to `apply_pronunciations()`. Use `flags=re.I` and `\b…\b`
  word boundaries; for acronyms spell with spaces ("V P S") so TTS reads letters; preserve caps/plurals with a
  small replacement function when needed (see `_widget`, `_gemini`, `_pg`). Keep the readable spelling in the
  notes — the map does the translation.
- **Current lexicon** (2026-06-23): LiveKit→LyveKit (also `livekit-agent`), widget→wid-git, gemini→geminye,
  litellm→"light LLM", Live Avatar/LiveAvatar→"Lyve Avatar", `vision_io.py`→"vizion I O dot pie", vps→"V P S",
  Postgres→"Post-gress".
- **Re-record only what changed** — don't regenerate the whole deck:
  - Find affected slides by **map-diff** (`apply_pronunciations(notes) != notes`), not raw keyword grep
    (the map is case-sensitive/word-specific; grep over-reports).
  - `python3 gen-voiceovers.py <deck.html> --only 1,2,5 --out-dir vo-<slug>` regenerates just those slide
    indices into the deck's namespaced voiceover dir.
- **Redeploy = audio only.** Pronunciation is baked into the WAVs, so `scp` the changed `vo-<slug>/*.wav` to
  `/opt/compose/decks/<vo-slug>/` — **no deck-HTML/index redeploy needed** (see [[decks-aicortex-cloud]]).
- The map is shared by every deck the generator runs on, so one fix corrects the word across all decks; batch
  multiple new words before re-recording to save GPU passes.

## timeline.aicortex.cloud aesthetic (the DEFAULT — baked into template.html)

This is the house style and `assets/template.html` already ships with it — you do NOT need to
add it, and you must NOT replace it with a neutral/stock theme. It's documented here so you can
keep hand-written slides consistent. The dark glassmorphic purple-blue palette (source:
`journey-tracker/timeline.html`, gold-reference deck `livekit-agent/bruce-deck.html`):

```css
--src:#7b93ff; --dst:#9b6fd0; --accent:#a78bfa; --bad:#ef6a6a;       /* purple-blue accents */
/* body bg */ linear-gradient(135deg,#0a0a14 0%,#1a1030 50%,#0a0a14 100%)
/* glass card */ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.10);
                 border-radius:16px; backdrop-filter:blur(20px); box-shadow:0 8px 32px rgba(0,0,0,.4);
/* gradient heading */ background:linear-gradient(135deg,#fff,#c7d2fe 40%,#a78bfa 72%,#fff);
                       -webkit-background-clip:text; color:transparent;
/* ambient glow */ radial-gradient blobs in --glow rgba(123,147,255,.45)
font: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif
```
Signature motifs: frosted glass cards, gradient (light-on-dark) headings, soft accent glows,
pulsing dots. Set Mermaid `themeVariables` to match (`primaryColor:#2a1a4a, lineColor:#7b93ff`).
Worked example: `livekit-agent/bruce-deck.html`.

## Gotchas (learned the hard way)

- **`file://` is blocked in Playwright** → always serve over http (verify.sh).
- **`pkill -f '<port/pattern>'` self-kills** when run as an inline `bash -c`,
  because the pattern is in the shell's own argv (exit 144, no output). Kill the
  server by PID instead.
- **highlight.js CDN build has no `cypher` grammar** → don't set
  `class="language-cypher"` (logs a warning + no highlight). Leave the `<code>`
  language unset for Cypher, or use `language-sql` for partial highlighting.
- **Mermaid in reveal** must render lazily per slide (see above).
- **Mermaid `classDef` names can't be reserved words.** Naming a class `graph`
  (or `flowchart`, `end`, `subgraph`, `class`) → "Syntax error in text". Use safe
  names like `gdb`, `svc`, `me`. Symptom: the slide shows a red mermaid error box.
- **Verify after editing serves a cached copy.** python http.server + browser cache
  can re-serve the old HTML (you'll see a stale slide count). Append a cache-buster
  query (`?v=2`) to the URL when re-verifying edits.
- **Favicon 404** in console is harmless; ignore it.
