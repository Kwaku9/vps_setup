# Trajectory Learning — interactive presentation

32 slides about the pipeline’s purpose, capture and curation, PostgreSQL/Neo4j
institutional memory, Gemma/Qwen training, evaluation, release, and current status.

## Published gallery

- Slides: https://decks.aicortex.cloud/trajectory-learning/
- Reading edition: https://decks.aicortex.cloud/trajectory-learning/read.html
- Offline PDF: https://decks.aicortex.cloud/trajectory-learning/trajectory-learning-guide.pdf

Hosted on the VPS under `/opt/compose/decks/trajectory-learning/`, using the existing
`decks-nginx` container and Cloudflare Access protection. Sign in normally if prompted.
The laptop and Tailscale are not needed to read this deployment.

On iPhone, swipe or use the arrows. The display icon opens presenter notes. Fullscreen
has a separate **Exit full screen** button at the top right, with a minimum 48px touch
target and safe-area positioning. Standard and WebKit fullscreen events are handled;
if native fullscreen is unavailable, in-page expansion retains the same exit control.

The reading edition uses plain HTML with all 32 sections and full speaker explanations.
It works with JavaScript disabled. The 33-page PDF includes a cover and all sections;
open it and choose **Share → Save to Files** for offline reading.

## Build / source

- `build_deck.py`: authored slide content, composition, wrapper, and public export.
- `build_reader.py`: script-free reading page generated from `slides.json`.
- `assets/deck-ui.js`: explicit fullscreen exit, WebKit handling, and fallback.
- `make_pdf.mjs`: print the reading edition to the offline PDF.
- `speaker-notes.md`: full narrative and implementation source references.

Run `python3 build_deck.py`, then `node make_pdf.mjs`. The browser helpers use the
workstation’s installed Chromium and Puppeteer paths; adapt these on another machine.
Only `public/` is published; no private session logs, credentials, or pipeline state.

`npm run dev` opens the HyperFrames presenter. `npm run check` validates the composition.
The CLI pin is now 0.8.134; bundled player assets remain the previously verified 0.8.106.
A single MP4 render does not capture all scene compositions; use the live deck or PDF.

## Validation (2026-10-05)

- Framework lint/runtime/layout/contrast check passed.
- All 32 slides checked at desktop and iPhone dimensions; navigation and mask toggle pass.
- Native fullscreen enter/exit by touch, denied-API fallback, and Escape exit pass.
- Reading edition checked at 390×844 with JavaScript disabled; no horizontal overflow.
- PDF generated: 33 pages; includes the complete explanatory narrative.
- Tests use Chromium mobile emulation, not a physical iPhone or Safari.

`browser-check.mjs` and `fullscreen-check.mjs` accept `DECK_URL` for deployment testing.
Reports/screenshots are in `checks/`, excluded from the published directory.
Implementation claims describe commit 74e0d75 and its October 2 validation evidence;
no GPU training or production model-quality improvement is claimed.

## Deployment notes

The gallery index was updated additively; its Ansible source is
`roles/decks/files/index.html`. The previous live index is backed up on the VPS at
`/opt/backups/decks/index-before-trajectory-learning-20261005.html`.

The original workstation preview was served privately over Tailscale on port
8447 while the laptop was online. To disable only that route:
`tailscale serve --https=8447 off`.
