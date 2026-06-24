---
name: slide-deck
description: Build a self-contained reveal.js technical presentation explaining a system or pipeline — Mermaid architecture diagrams, an optional LIVE Neo4j graph embed (neovis.js), mobile-responsive layout, optional per-slide voiceovers in a cloned Voicebox voice, speaker notes, a NotebookLM-ready narration companion, Playwright self-verification, and one-command PDF export. Use when the user asks to "make a presentation/deck/slides" about how some code, pipeline, service, or architecture works.
argument-hint: <topic or path to the system> [--no-graph] [--voiceover] [--export]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, mcp__playwright__browser_navigate, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_press_key, mcp__playwright__browser_console_messages
---

# slide-deck — Technical presentations that explain a system

Produce a single self-contained `<name>-deck.html` (reveal.js, CDN-loaded, no build
step) that explains a system "simply but accurately": what it does, where it fits,
its data/architecture model, how it runs, how it fails, and the numbers. Diagrams
are **animated CSS flow components** (`.flow`) for any traffic / request / pipeline flow —
**Mermaid only** for a genuinely static class/ER diagram; an optional slide renders a
**live** Neo4j graph. The template ships in the timeline house style (see Aesthetic below) —
do not downgrade it to a stock/neutral theme.

**Gold reference: `livekit-agent/bruce-deck.html`** — copy its look and feel. (The skill was
originally distilled from `vps_setup/local/etl/graph-etl-deck.html`; both are now in the house style.)

## When to use

- "Make a presentation / deck / slides explaining <system>"
- "Illustrate what <pipeline/service/component> does"
- Especially anything that touches a **Neo4j graph** (the live-graph slide shines)

## The enhancements over a hand-rolled deck

1. **Live Neo4j graph slide (neovis.js).** Instead of a static diagram placeholder,
   one slide renders the *actual* graph straight from Bolt — configurable Cypher,
   styled nodes/edges, with a graceful offline fallback so the deck still opens with
   zero dependencies. Driven by a single `window.DECK_GRAPH` config block.
2. **Self-verifying + exportable build.** The deck is never declared "done" on faith:
   serve it locally, drive it with Playwright, screenshot **every** slide to catch
   broken Mermaid / overflow / empty slides, then `export.sh` turns it into a PDF
   (and per-slide PNGs) via decktape. A NotebookLM-ready `<name>-narration.md` is
   generated from the speaker notes so the same content becomes an audio/video
   overview.
3. **Mobile-responsive + cloned-voice voiceovers.** The template ships mobile-readable
   (narrower canvas on phones so text scales up — see reference.md "Mobile / responsive").
   And `assets/gen-voiceovers.py` turns each slide's speaker notes into per-slide audio
   in a cloned **Voicebox** voice (default Qwen "Him-Mentor"), played on slide change via
   the `#vo-bar` toggle. The same toggle runs a **scored background-music bed** (`window.DECK_BG`):
   loops at 15% under the voice, swells to 25% when the voiceover ends, dips on slide change,
   crossfades on per-slide track changes (tracks in `bg/`). See reference.md → "Background music".
   Optional — strip `DECK_BG`/`#bg-audio` (and the VO bits) for a silent deck.

Aesthetic (DEFAULT — not optional): `assets/template.html` **ships in the
timeline.aicortex.cloud house style** — dark glassmorphic purple-blue palette
(`--src#7b93ff`/`--dst#9b6fd0`/`--accent#a78bfa`), gradient headings, ambient glow,
animated `.flow` diagrams, themed live-graph, and the voiceover bar. Just fill the stubs;
**don't swap the palette back to a neutral/stock theme**. A new deck must come out looking
like `livekit-agent/bruce-deck.html`. Palette + conventions: reference.md →
"timeline.aicortex.cloud aesthetic".

## Golden rule: accurate, not invented

Decks explain real systems. **Read the actual code first** and cite it. Numbers,
node labels, relationship names, endpoints, model ids — pull them from source, not
memory. If something is planned-but-not-built, label it "planned" on the slide.
When the architecture is unclear from code, ask the user 2-3 targeted questions
rather than guess (an Explore subagent is a good way to map an unfamiliar system).

## Workflow

1. **Gather ground truth.** Read the relevant code / configs. For an unfamiliar or
   large system, dispatch an `Explore` subagent to map it (request-flow hops, data
   model, "implemented vs planned", and file:line refs). Collect the real numbers.
2. **Copy the template.** `cp assets/template.html <dest>/<name>-deck.html`. Pick a
   destination next to the system it documents.
3. **Fill the slides.** Replace the `<!-- FILL: -->` stubs. Keep the slide arc:
   Title → One-liner → Where it fits (**animated `.flow`**) → Core concept → Source/Inputs
   → Architecture/Data model (Mermaid for static structure) → How it runs → Key mechanism
   (code snippet) → Spotlight (the "why bother") → Wiring/Deploy → Failure modes →
   The numbers → Live graph → Recap. Drop slides that don't apply; don't pad.
   Slide-writing rules in `reference.md` (terse, one idea per slide, every slide
   gets a `<aside class="notes">`).
4. **Configure the live graph.** Edit the `window.DECK_GRAPH` block (Bolt URI, creds,
   `initialCypher`, label/caption styling). If the system has no graph, pass
   `--no-graph` and delete that slide.
5. **Verify (mandatory).** `bash assets/verify.sh <name>-deck.html` starts a local
   server and tells you the URL; then with Playwright `browser_navigate` to each
   `#/<n>` and `browser_take_screenshot`, and `browser_console_messages level=error`
   to catch render failures. Fix anything that's blank, overflowing, or where a
   Mermaid block stayed as raw text. **Also screenshot a few content-heavy slides at a
   mobile viewport (390×844)** to confirm text is readable and columns/code/tables fit.
   (See reference.md for the Mermaid-in-reveal, `file://`-blocked, and pkill-self-match gotchas.)
6. **Generate the narration companion.** Write `<name>-narration.md` — a plain-language
   walkthrough built from the speaker notes, structured for NotebookLM ingestion.
7. **Voiceovers (if --voiceover or asked).** `python3 assets/gen-voiceovers.py <name>-deck.html`
   synthesizes each slide's notes into `voiceovers/slide-<i>.wav` via Voicebox (default
   Qwen "Him-Mentor"). Needs the Voicebox server up (and the GPU free — see reference.md
   "Enhancement 3"). The deck plays them via the `#vo-bar` toggle; missing files are ignored.
   - **Pronunciation fixes:** mispronounced brand/jargon words are corrected in
     `apply_pronunciations()` in gen-voiceovers.py (a TTS lexicon applied before synthesis —
     keeps the notes readable). When the user reports a bad word, add a `re.sub` line there
     (don't respell the notes), then **re-record only affected slides**: find them by map-diff,
     run `--only <indices> --out-dir vo-<slug>`, and `scp` just the changed `vo-<slug>/*.wav`
     (no deck-HTML redeploy — the fix is in the audio). See reference.md "Pronunciation fixes".
8. **Export (if --export or asked).** `bash assets/export.sh <name>-deck.html` →
   `<name>-deck.pdf` + `slides/` PNGs (needs `npx decktape`, falls back to the
   reveal `?print-pdf` + headless-Chrome path documented in export.sh).
9. **Report.** Give the file path, how to view (`S` notes, `F` fullscreen), the
   companion artifacts, the voiceover + export commands.

## Files

- `assets/template.html` — the reusable reveal.js skeleton: design-system CSS,
  the **animated flow-diagram component** (`.flow`/`.node`/`.link` with moving
  packets — preferred over Mermaid for traffic/request flows), lazy per-slide
  Mermaid rendering (for static structure/data-models), mobile-responsive canvas,
  optional voiceover bar, the neovis.js live-graph slide + fallback, slide stubs.
- `assets/verify.sh` — serve the deck on a free port for Playwright verification.
- `assets/export.sh` — deck → PDF + per-slide PNGs.
- `assets/gen-voiceovers.py` — slide notes → per-slide WAVs via Voicebox (Him-Mentor). Has a
  TTS pronunciation lexicon (`apply_pronunciations()`) + `--only <indices>` / `--out-dir vo-<slug>`
  for targeted re-records.
- `reference.md` — design system (colors, slide patterns), the animated-flow + Mermaid
  conventions, mobile/voiceover/aesthetic notes, the live-graph schema, and gotchas.
