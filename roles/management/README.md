# OPS mobile dashboard

The mobile app is served at `/m/`. The classic dashboard remains at `/`.

Services cards group live containers by resolved Podman pod name. Each shape
represents one container; circles are VPS containers, squares are host services,
and diamonds are remote endpoints. Cards show total CPU and actual RAM usage.
The upper ring tracks the highest container CPU percentage and the lower ring
tracks the highest RAM usage/limit percentage, so one busy member isn't hidden
by a pod average. CPU values can exceed 100% when using multiple cores; only
the visual arc is capped. Green is below 60%, amber starts at 60%, red at 85%.
The Problems filter includes red resource pressure as well as service failures.

Movement grows with each container's load; card positions remain fixed. Motion
can be turned off, respects reduced-motion settings, and pauses offscreen and
when the page is hidden. Missing or older-than-90-second scrape data stays gray.
Host services and remote endpoints retain status but don't claim VPS load data.

The Sessions bridge, native reply composer, and browser-local Kokoro/Whisper
controls are documented in [OPS-SESSIONS.md](../../OPS-SESSIONS.md).

Deploy with the `ops-dashboard` Ansible tag. The 2026-10-08 isolated Services
release is `.ops-services-release-20261008` on the VPS; its previous image is
`localhost/ops-dashboard:pre-services-20261008`. Merge the feature PR before
future source deployments. Verification covered 88 backend tests, mobile browser
layouts at 320/390px, resource filters, stale values and motion controls, plus
live production checks of Sessions and 57 VPS containers.
