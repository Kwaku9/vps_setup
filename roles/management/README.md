# OPS mobile dashboard

Services uses the approved two-column phone layout: each pod card has CPU and
RAM arcs, one shape per container, a load label, total usage, and a running
count. Selecting the card reveals the containers and existing role-gated
Start/Stop controls. Shapes move more at higher load; motion can be disabled
and respects reduced-motion settings. Missing or old readings stay gray.

This layout was restored from `eedeab3` / `4cc3235` onto current main after a
source-based deployment reverted to the older text-only tiles. The current
pod-name discovery fix (`58a9f82`) is retained, including real pod membership
for managed services. The restoration does not revert the application to the
old feature branch or replace Sessions, Inventory, authentication, or actions.

The resource API includes actual `memory_usage_mb` and `metrics_at` from the
source scrape. Rings show the busiest container's percentage; card values
show totals. Thresholds are 60% (amber) and 85% (red). High resource pressure
also appears in the Problems filter.

Build and check `files/ops-dashboard/frontend-svelte` with `npm ci`,
`npm run check`, `npm test`, and `npm run build`. For the browser regression,
start `npm exec vite preview -- --port 5187`, then run
`CHROME_BIN=/usr/bin/google-chrome npm run test:browser:services`.
The browser test uses fixture data and submits no container actions. It covers
the reference seven-container card, grouping, filters, motion, stale readings,
and 320/390/640px layouts. The backend suite includes the newer pod-grouping
tests as well as resource-field and missing-metric regressions.

Deploy the management role with the `ops-dashboard` tag from source containing
this restoration. The isolated 2026-11-06 release uses the current production
image as its base; rollback is retained as
`localhost/ops-dashboard:pre-layout-20261106` on the VPS. Its release directory
is `.ops-layout-release-20261106` under the VPS workspace.
