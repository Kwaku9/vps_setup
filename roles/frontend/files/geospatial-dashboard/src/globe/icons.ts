// Aircraft, ship and satellite marker icons.
//
// Aircraft silhouettes (BODIES) and the type-aware classifier are ported
// verbatim from God's Eye View (github.com/bilawalsidhu/gods-eye-view,
// src/data/aircraftIcons.js and src/data/aircraftClass.js), which adapt
// skylight (github.com/cpaczek/skylight). Both are MIT:
//
//   Copyright (c) 2026 Bilawal Sidhu
//   Copyright (c) skylight contributors
//
//   Permission is hereby granted, free of charge, to any person obtaining a
//   copy of this software and associated documentation files (the
//   "Software"), to deal in the Software without restriction, including
//   without limitation the rights to use, copy, modify, merge, publish,
//   distribute, sublicense, and/or sell copies of the Software, and to permit
//   persons to whom the Software is furnished to do so, subject to the
//   following conditions: The above copyright notice and this permission
//   notice shall be included in all copies or substantial portions of the
//   Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
//
// Vessel and satellite silhouettes, their classifiers, and the north-aligned
// orientation helper are WorldView's own; satellite class colours follow
// God's Eye View.
//
// Glyphs are WHITE, nose/bow up (-Y). Colour comes from billboard.color, so
// one cached image per shape serves every tint.

import { Cartesian3, Cartesian4, Transforms, Matrix4 } from "cesium";

export type AircraftClass =
  | "airliner" | "widebody" | "quadjet" | "turboprop" | "light"
  | "glider" | "helicopter" | "fastjet" | "bizjet" | "uav"
  // WorldView additions: types distinct enough to recognise from above.
  | "b747" | "a380";

const VIEW = 96;
const C = VIEW / 2; // 48 — glyph centre

// Hairline dark edge (scaled for the 96 box: ~1.5u ≈ the old 0.5u at 32).
const STROKE =
  'stroke="rgba(0,0,0,0.32)" stroke-width="1.4" stroke-linejoin="round"';
// Heavier edge for the chart-symbol ("bold") glyphs adopted 2026-08-15.
const STROKE_BOLD =
  'stroke="rgba(0,0,0,0.38)" stroke-width="2" stroke-linejoin="round"';
// Softer white for translucent detail (prop discs, rotor disc) — still white so
// the tint multiplies cleanly; only the alpha differs.
const DISC = 'fill="white" fill-opacity="0.5"';

// Each body is drawn in a centred coordinate frame (origin 0,0 = glyph centre),
// nose toward -Y. Numbers are in the 96-unit space (half-extent up to ~45).
// Upstream also carries an unlisted easter-egg body (tr3b), so string keys.
const BODIES: Record<string, string> = {
  // ── WorldView: Boeing 747. From above the giveaway is the upper deck: the
  //    forward third of the fuselage is wider than the rest, then necks in
  //    behind the wing root. Four pods, deep sweep, big tailplane.
  b747: `
    <path d="M0,-46 C 8,-44 10.5,-37 10.5,-29 L 10.5,-19
             C 10.5,-16 8.2,-14 8.2,-11
             L 46,13 L 46,21 L 8.2,11.5
             L 7.6,22 L 21,32 L 21,38 L 0,33 L -21,38 L -21,32 L -7.6,22
             L -8.2,11.5 L -46,21 L -46,13 L -8.2,-11
             C -8.2,-14 -10.5,-16 -10.5,-19
             L -10.5,-29 C -10.5,-37 -8,-44 0,-46 Z" fill="white" ${STROKE_BOLD}/>
    <rect x="-32" y="9.5" width="6.5" height="12" rx="2" fill="white"/>
    <rect x="-18.5" y="4" width="6.5" height="12" rx="2" fill="white"/>
    <rect x="12" y="4" width="6.5" height="12" rx="2" fill="white"/>
    <rect x="25.5" y="9.5" width="6.5" height="12" rx="2" fill="white"/>`,

  // ── WorldView: Airbus A380. Fattest fuselage of any airliner (full-length
  //    double deck), a vast, LESS-swept wing with wingtip fences, four pods.
  a380: `
    <path d="M0,-44 C 9,-42 11.5,-35 11.5,-26 L 11.5,-9
             L 46,6 L 47,7 L 47,15 L 45,15 L 11.5,10
             L 10.5,23 L 22,31 L 22,37 L 0,33 L -22,37 L -22,31 L -10.5,23
             L -11.5,10 L -45,15 L -47,15 L -47,7 L -46,6 L -11.5,-9
             L -11.5,-26 C -11.5,-35 -9,-42 0,-44 Z" fill="white" ${STROKE_BOLD}/>
    <rect x="-33" y="4" width="7" height="12" rx="2" fill="white"/>
    <rect x="-20" y="0" width="7" height="12" rx="2" fill="white"/>
    <rect x="13" y="0" width="7" height="12" rx="2" fill="white"/>
    <rect x="26" y="4" width="7" height="12" rx="2" fill="white"/>`,

  // ── Airliner: slender swept-wing narrow-body, two underwing engine pods,
  //    swept tailplane. The canonical jet; everything else reads against it.
  airliner: `
    <path d="M0,-42 C 3.8,-40 4.6,-34 4.6,-26 L 4.6,-14
             L 32,4 L 34,6 L 34,10 L 31.4,9.2 L 4.6,2.4
             L 4.2,20
             L 14,28 L 14,32 L 0,28.6 L -14,32 L -14,28 L -4.2,20
             L -4.6,2.4 L -31.4,9.2 L -34,10 L -34,6 L -32,4 L -4.6,-14
             L -4.6,-26 C -4.6,-34 -3.8,-40 0,-42 Z" fill="white" ${STROKE}/>
    <path d="M-15.5,-1.5 l3,7.6 4,-1.4 -1.5,-8.4 Z" fill="white"/>
    <path d="M15.5,-1.5 l-3,7.6 -4,-1.4 1.5,-8.4 Z" fill="white"/>
    <path d="M-1.6,33.5 L 1.6,33.5 L 1.6,40 L -1.6,40 Z" fill="white"/>`,

  // ── Widebody: same swept jet but noticeably BIGGER span + fatter fuselage,
  //    twin engines set further out. Reads as a heavier airliner.
  widebody: `
    <path d="M0,-45 C 5.6,-43 6.8,-36 6.8,-27 L 6.8,-12
             L 38,9 L 41.5,12.4 L 41.5,16.6 L 37.6,15 L 6.8,6
             L 6.3,21
             L 17,30 L 17,34.6 L 0,30.4 L -17,34.6 L -17,30 L -6.3,21
             L -6.8,6 L -37.6,15 L -41.5,16.6 L -41.5,12.4 L -38,9 L -6.8,-12
             L -6.8,-27 C -6.8,-36 -5.6,-43 0,-45 Z" fill="white" ${STROKE}/>
    <path d="M-19,2 l3.6,9 4.8,-1.7 -1.8,-10 Z" fill="white"/>
    <path d="M19,2 l-3.6,9 -4.8,-1.7 1.8,-10 Z" fill="white"/>
    <path d="M-2,35.5 L 2,35.5 L 2,42.5 L -2,42.5 Z" fill="white"/>`,

  // ── Quadjet: the widest swept jet, with FOUR bold underwing engine pods (two
  //    per wing) that hang well below the trailing edge — the wing reads as a
  //    4-lumped bar even when the individual pods blur together at ~20px.
  quadjet: `
    <path d="M0,-45 C 7,-42 9,-34 9,-25 L 9,-11
             L 46,12 L 46,21 L 9,11.5
             L 8.4,21 L 20,31 L 20,37.5 L 0,32 L -20,37.5 L -20,31 L -8.4,21
             L -9,11.5 L -46,21 L -46,12 L -9,-11
             L -9,-25 C -9,-34 -7,-42 0,-45 Z" fill="white" ${STROKE_BOLD}/>
    <rect x="-31" y="9" width="7" height="12" rx="2" fill="white"/>
    <rect x="-17" y="4.5" width="7" height="12" rx="2" fill="white"/>
    <rect x="10" y="4.5" width="7" height="12" rx="2" fill="white"/>
    <rect x="24" y="9" width="7" height="12" rx="2" fill="white"/>`,

  // ── Turboprop: bold STRAIGHT (unswept) wings — thicker chord than a jet — two
  //    fat nacelles that jut ahead of the leading edge, each capped by a solid
  //    prop disc. Reads as "straight wing with two lumps + discs" at ~20px.
  turboprop: `
    <path d="M0,-40 C 3.4,-38.5 4.2,-33 4.2,-26 L 4.2,-18
             L 36,-15.5 L 36,-7.5 L 4.2,-8
             L 3.8,22
             L 13,27.5 L 13,31.5 L 0,28.6 L -13,31.5 L -13,27.5 L -3.8,22
             L -4.2,-8 L -36,-7.5 L -36,-15.5 L -4.2,-18
             L -4.2,-26 C -4.2,-33 -3.4,-38.5 0,-40 Z" fill="white" ${STROKE}/>
    <circle cx="-17.5" cy="-16.5" r="7.5" fill="white" fill-opacity="0.5"/>
    <circle cx="17.5" cy="-16.5" r="7.5" fill="white" fill-opacity="0.5"/>
    <path d="M-19.5,-19 h4 v5 h-4 Z" fill="white"/>
    <path d="M15.5,-19 h4 v5 h-4 Z" fill="white"/>
    <path d="M-1.7,31.5 L 1.7,31.5 L 1.7,38.5 L -1.7,38.5 Z" fill="white"/>`,

  // ── Light GA: small and CHUNKY — short, DEEP-chord straight wings and a fat
  //    stubby fuselage make it read as a solid little block (not a thin cross),
  //    with a bold nose prop disc. The short deep wing is the anti-glider cue.
  light: `
    <path d="M0,-27
             C 4,-25 5.2,-20 5.2,-13
             L 5.2,-9
             L 27,-9 L 27,6 L 5.2,6
             L 5.2,16
             L 11.5,23 L 11.5,27 L 0,23.5 L -11.5,27 L -11.5,23 L -5.2,16
             L -5.2,6
             L -27,6 L -27,-9 L -5.2,-9
             L -5.2,-13
             C -5.2,-20 -4,-25 0,-27 Z" fill="white" ${STROKE}/>
    <ellipse cx="0" cy="-29" rx="12" ry="3.8" ${DISC}/>`,

  // ── Glider: VERY long, high-aspect TAPERED wings (fat root → thin tips) on a
  //    slim fuselage with a T-tail. The extreme span is the whole identity — it
  //    reads as "the wide skinny one" against light's short stubby wings.
  glider: `
    <path d="M0,-35 C 2.4,-33 3,-29 3,-25 L 3,-14
             L 45,-10.5 L 45,-3.5 L 2.9,-6
             L 2.2,32 L -2.2,32 L -2.9,-6
             L -45,-3.5 L -45,-10.5 L -3,-14
             L -3,-25 C -3,-29 -2.4,-33 0,-35 Z" fill="white" ${STROKE_BOLD}/>
    <rect x="-10.5" y="32.5" width="21" height="5" rx="1.5" fill="white" ${STROKE_BOLD}/>`,

  // ── Helicopter: a SOLID translucent main-rotor disc (survives downscale as an
  //    obvious circle, unlike a thin ring) with a bold two-blade cross, a
  //    teardrop cabin, a tail boom, and a tail rotor. Unmistakable "disc on top"
  //    silhouette that never reads as a fixed-wing.
  helicopter: `
    <circle cx="0" cy="-6" r="31" fill="white" fill-opacity="0.22"/>
    <g transform="rotate(45 0 -6)">
      <rect x="-30.5" y="-8.2" width="61" height="4.4" rx="2.2" fill="white" fill-opacity="0.9"/>
      <rect x="-30.5" y="-8.2" width="61" height="4.4" rx="2.2" fill="white" fill-opacity="0.9" transform="rotate(90 0 -6)"/>
    </g>
    <path d="M0,-22 C 8,-20 10.5,-13 10.5,-6 C 10.5,2 7.5,7 0,8.5
             C -7.5,7 -10.5,2 -10.5,-6 C -10.5,-13 -8,-20 0,-22 Z" fill="white" ${STROKE}/>
    <path d="M-2.6,8 L 2.6,8 L 1.8,32 L -1.8,32 Z" fill="white" ${STROKE}/>
    <path d="M-8,27 L 8,27 L 8,30.6 L -8,30.6 Z" fill="white"/>
    <circle cx="5.6" cy="35" r="6" fill="white" fill-opacity="0.6"/>
    <circle cx="5.6" cy="35" r="2.1" fill="white"/>`,

  // ── Fast jet: sharp delta/cropped-delta with a pointed nose, LERX root
  //    blend, and twin tail fins. Aggressive, all-wing.
  fastjet: `
    <path d="M0,-43
             L 3.5,-30
             C 4,-24 4.6,-16 5,-8
             L 27,20 L 27,26 L 6,16
             L 8,30 L 8,34 L 3,31
             L 3,38 L 6.5,42 L 6.5,44 L 0,41.5
             L -6.5,44 L -6.5,42 L -3,38
             L -3,31 L -8,34 L -8,30 L -6,16
             L -27,26 L -27,20 L -5,-8
             C -4.6,-16 -4,-24 -3.5,-30 Z" fill="white" ${STROKE}/>`,
  // 2026-08-15 Hangar additions: two NEW classes shipped with the real-model
  // fleet (CLASS_MODEL_REAL). Same contract as the set above: 96×96 nose-up,
  // white fill, hairline stroke, tint-safe.
  // Business jet — slender fuselage, modest swept wing, aft engines, T-tail.
  bizjet: `
    <path d="M0,-42
             L 2.6,-36 L 3.4,-26 L 3.4,-8
             L 27,8 L 27,13 L 3.6,6
             L 3.6,16
             L 8,18 L 8,26 L 3.8,25
             L 3.2,30 L 15,34 L 15,38 L 2.4,36
             L 0,40
             L -2.4,36 L -15,38 L -15,34 L -3.2,30
             L -3.8,25 L -8,26 L -8,18 L -3.6,16
             L -3.6,6 L -27,13 L -27,8 L -3.4,-8
             L -3.4,-26 L -2.6,-36 Z" fill="white" ${STROKE}/>`,
  // ── TR-3B (hidden 9th kind, Easter egg — NOT a classifyAircraft() output).
  //    The canonical black-triangle silhouette: a dark isosceles delta with a
  //    light at each corner and a dimmer one at the centre. Reached only by
  //    explicit user conversion (see tr3bRegistry.js), never by classification.
  //
  //    DELIBERATE BREAK from the white-fill contract above: this glyph is a
  //    SHADOW, so it carries its own near-black fill. The billboard tint still
  //    multiplies (white fleet / cyan tracked / amber military), which darkens
  //    rather than lightens — the triangle stays a silhouette in every layer,
  //    and the corner lights pick the tint up as their hue.
  tr3b: `
    <path d="M0,-38 L 40,30 L -40,30 Z"
          fill="#0d1014" stroke="rgba(158,184,210,0.34)" stroke-width="1.6"
          stroke-linejoin="round"/>
    <circle cx="0" cy="-24" r="8.5" fill="#c9dcf0" fill-opacity="0.13"/>
    <circle cx="-28" cy="21" r="8.5" fill="#c9dcf0" fill-opacity="0.13"/>
    <circle cx="28" cy="21" r="8.5" fill="#c9dcf0" fill-opacity="0.13"/>
    <circle cx="0" cy="-24" r="4.6" fill="#dceaf8" fill-opacity="0.52"/>
    <circle cx="-28" cy="21" r="4.6" fill="#dceaf8" fill-opacity="0.52"/>
    <circle cx="28" cy="21" r="4.6" fill="#dceaf8" fill-opacity="0.52"/>
    <circle cx="0" cy="6" r="3.4" fill="#dceaf8" fill-opacity="0.26"/>`,

  // ── TR-3B, thermal-reactive variant. Same cold airframe, but the three
  //    corner emitters + the centre one render HOT: near-white cores inside a
  //    baked radial glow, so the FLIR/NVG luminance mapping (and any bloom)
  //    lights them up while the hull stays cold. Selected by the layers
  //    whenever their `irBoost` style param is on (surveillance/thermal/nvg).
  tr3bHot: `
    <defs>
      <radialGradient id="tr3bGlow">
        <stop offset="0%" stop-color="#ffffff" stop-opacity="0.92"/>
        <stop offset="32%" stop-color="#f2f9ff" stop-opacity="0.44"/>
        <stop offset="100%" stop-color="#dcefff" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <path d="M0,-38 L 40,30 L -40,30 Z"
          fill="#0b0e12" stroke="rgba(126,148,172,0.3)" stroke-width="1.6"
          stroke-linejoin="round"/>
    <circle cx="0" cy="-24" r="15" fill="url(#tr3bGlow)"/>
    <circle cx="-28" cy="21" r="15" fill="url(#tr3bGlow)"/>
    <circle cx="28" cy="21" r="15" fill="url(#tr3bGlow)"/>
    <circle cx="0" cy="6" r="10" fill="url(#tr3bGlow)"/>
    <circle cx="0" cy="-24" r="5.2" fill="#ffffff"/>
    <circle cx="-28" cy="21" r="5.2" fill="#ffffff"/>
    <circle cx="28" cy="21" r="5.2" fill="#ffffff"/>
    <circle cx="0" cy="6" r="3.6" fill="#ffffff" fill-opacity="0.82"/>`,

  // Large UAV (Reaper-class) — bulbous sensor nose, very long slender
  // straight wings, slim tail boom, canted V-tail.
  uav: `
    <path d="M0,-40
             C 3.6,-40 4.6,-35 4.4,-30
             L 2.4,-12
             L 43,-7 L 43,-2.5 L 2.3,0
             L 2.1,24
             L 13,32 L 13,36 L 1.6,30
             L 0,38
             L -1.6,30 L -13,36 L -13,32 L -2.1,24
             L -2.3,0 L -43,-2.5 L -43,-7 L -2.4,-12
             L -4.4,-30 C -4.6,-35 -3.6,-40 0,-40 Z" fill="white" ${STROKE}/>`,
};

const ICON_PX = 64;
const iconCache = new Map<string, string>();

function svgUri(svg: string): string {
  return "data:image/svg+xml;base64," + btoa(svg);
}

/** White nose-up silhouette for an aircraft class. */
export function aircraftIcon(kind: AircraftClass): string {
  const k = BODIES[kind] ? kind : "airliner";
  let uri = iconCache.get(k);
  if (!uri) {
    uri = svgUri(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON_PX}" height="${ICON_PX}" viewBox="0 0 ${VIEW} ${VIEW}"><g transform="translate(${C},${C})">${BODIES[k]}</g></svg>`
    );
    iconCache.set(k, uri);
  }
  return uri;
}

// ── Vessels ────────────────────────────────────────────────────────────────
// Top-down hulls, bow up (-Y), in a 64-unit box centred on 0,0. Each kind has
// its own planform so it reads by SHAPE at ~20px, not only by colour.

export type VesselKind =
  | "container" | "tanker" | "passenger" | "fishing" | "tug" | "sailing"
  | "yacht" | "military" | "hsc" | "patrol" | "dredger" | "other";

const HULL = 'fill="white" stroke="rgba(0,0,0,0.5)" stroke-width="1.6" stroke-linejoin="round"';
const DECK = 'fill="none" stroke="rgba(0,0,0,0.45)" stroke-width="1.4"';
const DECK_FILL = 'fill="rgba(0,0,0,0.28)"';

const VESSELS: Record<VesselKind, string> = {
  // Long, slab-sided hull, sharp bow, square stern; a grid of container
  // bays and the bridge block right aft.
  container: `
    <path d="M0,-30 C 5,-24 7,-18 7,-12 L 7,28 L -7,28 L -7,-12 C -7,-18 -5,-24 0,-30 Z" ${HULL}/>
    <path d="M-5,-14 H5 M-5,-7 H5 M-5,0 H5 M-5,7 H5 M-5,14 H5 M0,-17 V17" ${DECK}/>
    <rect x="-6" y="19" width="12" height="5" ${DECK_FILL}/>`,
  // Long hull with a ROUNDED bow, the central pipe run down the deck and the
  // superstructure aft.
  tanker: `
    <path d="M0,-29 C 6,-28 8,-22 8,-14 L 8,28 L -8,28 L -8,-14 C -8,-22 -6,-28 0,-29 Z" ${HULL}/>
    <path d="M0,-22 V17 M-4,-12 H4 M-4,-2 H4 M-4,8 H4" ${DECK}/>
    <rect x="-6.5" y="19" width="13" height="6" ${DECK_FILL}/>`,
  // Broad, full hull rounded at both ends; stacked deck outline and a funnel.
  passenger: `
    <path d="M0,-29 C 7,-27 9,-19 9,-10 L 9,22 C 9,27 6,29 0,29 C -6,29 -9,27 -9,22 L -9,-10 C -9,-19 -7,-27 0,-29 Z" ${HULL}/>
    <path d="M-6,-14 C -6,-20 6,-20 6,-14 L 6,22 L -6,22 Z" ${DECK}/>
    <ellipse cx="0" cy="8" rx="2.6" ry="3.6" ${DECK_FILL}/>`,
  // Short beamy hull, wheelhouse forward, outrigger booms swung out.
  fishing: `
    <path d="M0,-17 C 5,-14 6,-8 6,-2 L 6,15 L -6,15 L -6,-2 C -6,-8 -5,-14 0,-17 Z" ${HULL}/>
    <rect x="-4" y="-8" width="8" height="6" ${DECK_FILL}/>
    <path d="M-6,3 L -19,-5 M6,3 L 19,-5" fill="none" stroke="white" stroke-width="1.8"/>`,
  // Stubby, almost oval hull with a fat fender band and the house forward.
  tug: `
    <path d="M0,-15 C 8,-14 10,-6 10,1 C 10,10 7,15 0,15 C -7,15 -10,10 -10,1 C -10,-6 -8,-14 0,-15 Z" ${HULL}/>
    <path d="M0,-12 C 6,-11 8,-5 8,1 C 8,8 6,12 0,12 C -6,12 -8,8 -8,1 C -8,-5 -6,-11 0,-12 Z" ${DECK}/>
    <rect x="-4" y="-8" width="8" height="7" ${DECK_FILL}/>`,
  // Slim hull; the mainsail and boom drawn as a triangle off the mast.
  sailing: `
    <path d="M0,-22 C 4,-17 5,-9 5,0 C 5,10 4,16 2.5,18 L -2.5,18 C -4,16 -5,10 -5,0 C -5,-9 -4,-17 0,-22 Z" ${HULL}/>
    <circle cx="0" cy="-5" r="1.6" ${DECK_FILL}/>
    <path d="M0,-5 L 9,13 L 0,13 Z" fill="white" fill-opacity="0.75" stroke="rgba(0,0,0,0.4)" stroke-width="1"/>`,
  // Sleek motor yacht: fine entry, flat transom, long cabin top.
  yacht: `
    <path d="M0,-22 C 5,-16 6,-8 6,0 L 6,18 L -6,18 L -6,0 C -6,-8 -5,-16 0,-22 Z" ${HULL}/>
    <path d="M-3.5,-8 C -3.5,-12 3.5,-12 3.5,-8 L 3.5,10 L -3.5,10 Z" ${DECK_FILL}/>`,
  // Angular warship: knife bow, faceted sides, stepped superstructure, a gun
  // mount forward and a helideck aft.
  military: `
    <path d="M0,-31 L 5,-18 L 7,-4 L 7,22 L 5,28 L -5,28 L -7,22 L -7,-4 L -5,-18 Z" ${HULL}/>
    <circle cx="0" cy="-17" r="2.2" ${DECK_FILL}/>
    <path d="M0,-17 V-23" stroke="rgba(0,0,0,0.5)" stroke-width="1.4"/>
    <path d="M-4,-8 L 4,-8 L 4,12 L -4,12 Z" ${DECK_FILL}/>
    <rect x="-5" y="17" width="10" height="8" ${DECK}/>`,
  // High-speed craft: twin catamaran hulls joined by a deck.
  hsc: `
    <path d="M-7,-20 C -4,-16 -3.5,-10 -3.5,-4 L -3.5,20 L -10,20 L -10,-4 C -10,-10 -9.5,-16 -7,-20 Z" ${HULL}/>
    <path d="M7,-20 C 9.5,-16 10,-10 10,-4 L 10,20 L 3.5,20 L 3.5,-4 C 3.5,-10 4,-16 7,-20 Z" ${HULL}/>
    <rect x="-8" y="-4" width="16" height="16" rx="2" fill="white" stroke="rgba(0,0,0,0.5)" stroke-width="1.4"/>`,
  // Patrol / pilot / SAR / police boat: compact planing hull with a
  // diagonal service stripe.
  patrol: `
    <path d="M0,-19 C 5,-14 6,-7 6,0 L 6,15 L -6,15 L -6,0 C -6,-7 -5,-14 0,-19 Z" ${HULL}/>
    <path d="M-6,4 L 6,-4 M-6,8 L 6,0" stroke="rgba(0,0,0,0.5)" stroke-width="1.6"/>
    <rect x="-3.5" y="-10" width="7" height="6" ${DECK_FILL}/>`,
  // Dredger: boxy hull with the drag arm along one side.
  dredger: `
    <path d="M-7,-22 L 7,-22 L 8,-18 L 8,22 L -8,22 L -8,-18 Z" ${HULL}/>
    <rect x="-5" y="-16" width="10" height="20" ${DECK}/>
    <path d="M9,-14 L 13,10" stroke="white" stroke-width="2.2"/>`,
  // Generic hull for unknown types.
  other: `
    <path d="M0,-22 C 5,-17 6,-9 6,-2 L 6,18 L -6,18 L -6,-2 C -6,-9 -5,-17 0,-22 Z" ${HULL}/>`,
};

/** Vessel kind from the AIS ship-type code (ITU-R M.1371), falling back to
 *  the relay's coarse category when the code is not available. */
export function classifyVessel(shipType: number | null | undefined, category = ""): VesselKind {
  const t = typeof shipType === "number" ? shipType : NaN;
  if (Number.isFinite(t) && t > 0) {
    if (t === 30) return "fishing";
    if (t === 31 || t === 32 || t === 52) return "tug";
    if (t === 33) return "dredger";
    if (t === 35) return "military";
    if (t === 36) return "sailing";
    if (t === 37) return "yacht";
    if (t === 50 || t === 51 || t === 53 || t === 55 || t === 58) return "patrol";
    if (t >= 40 && t <= 49) return "hsc";
    if (t >= 60 && t <= 69) return "passenger";
    if (t >= 70 && t <= 79) return "container";
    if (t >= 80 && t <= 89) return "tanker";
    return "other";
  }
  const byCategory: Record<string, VesselKind> = {
    cargo: "container", tanker: "tanker", passenger: "passenger",
    fishing: "fishing", military: "military", hsc: "hsc",
    special: "patrol",
  };
  return byCategory[category] ?? "other";
}

/** White bow-up silhouette for a vessel kind. */
export function vesselIcon(kind: VesselKind): string {
  const key = `vessel:${kind}`;
  let uri = iconCache.get(key);
  if (!uri) {
    uri = svgUri(
      `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="-32 -32 64 64">${VESSELS[kind] ?? VESSELS.other}</svg>`
    );
    iconCache.set(key, uri);
  }
  return uri;
}

/** On-screen size for a hull: bigger ships draw bigger, within reason. */
export function vesselPixelSize(lengthM: number): number {
  if (!lengthM || lengthM <= 0) return 18;
  return Math.round(Math.min(30, Math.max(14, 12 + lengthM / 15)));
}

// ── Satellites ─────────────────────────────────────────────────────────────
// Symmetric, so never rotated. Each family has its real-world layout.

export type SatelliteKind = "station" | "nav" | "starlink" | "weather" | "generic";

const PANEL = 'fill="white" fill-opacity="0.85" stroke="rgba(0,0,0,0.45)" stroke-width="1"';
const BUS = 'fill="white" stroke="rgba(0,0,0,0.5)" stroke-width="1"';
const CELL = 'stroke="rgba(0,0,0,0.3)" stroke-width="0.8" fill="none"';

const SATELLITES: Record<SatelliteKind, string> = {
  // ISS / Tiangong: long main truss carrying four pairs of big solar arrays,
  // with the pressurised modules stacked across the middle.
  station: `
    <rect x="-23" y="-1" width="46" height="2" ${BUS}/>
    <rect x="-22" y="-12" width="5" height="10" ${PANEL}/><rect x="-22" y="2" width="5" height="10" ${PANEL}/>
    <rect x="-15" y="-12" width="5" height="10" ${PANEL}/><rect x="-15" y="2" width="5" height="10" ${PANEL}/>
    <rect x="10" y="-12" width="5" height="10" ${PANEL}/><rect x="10" y="2" width="5" height="10" ${PANEL}/>
    <rect x="17" y="-12" width="5" height="10" ${PANEL}/><rect x="17" y="2" width="5" height="10" ${PANEL}/>
    <rect x="-3" y="-14" width="6" height="28" rx="2" ${BUS}/>
    <rect x="-8" y="-3" width="16" height="6" rx="2" ${BUS}/>`,
  // GPS / Galileo: box bus, two long panel wings, antenna face.
  nav: `
    <rect x="-22" y="-4" width="15" height="8" ${PANEL}/>
    <rect x="7" y="-4" width="15" height="8" ${PANEL}/>
    <path d="M-17,-4 V4 M-12,-4 V4 M12,-4 V4 M17,-4 V4" ${CELL}/>
    <path d="M-7,0 H-4 M4,0 H7" stroke="white" stroke-width="1.6"/>
    <rect x="-4" y="-6" width="8" height="12" rx="1" ${BUS}/>
    <circle cx="0" cy="-8" r="2" ${BUS}/>`,
  // Starlink: flat-panel bus with ONE long array to the side.
  starlink: `
    <rect x="-14" y="-5" width="10" height="10" rx="1" ${BUS}/>
    <path d="M-4,0 H-1" stroke="white" stroke-width="1.6"/>
    <rect x="-1" y="-4" width="23" height="8" ${PANEL}/>
    <path d="M5,-4 V4 M11,-4 V4 M17,-4 V4" ${CELL}/>`,
  // Weather satellite: bus, a single wing, and the round imager/dish.
  weather: `
    <rect x="-20" y="-4" width="13" height="8" ${PANEL}/>
    <path d="M-7,0 H-5" stroke="white" stroke-width="1.6"/>
    <rect x="-5" y="-6" width="10" height="12" rx="1" ${BUS}/>
    <circle cx="11" cy="0" r="5.5" ${BUS}/>
    <circle cx="11" cy="0" r="2.2" fill="rgba(0,0,0,0.3)"/>`,
  // Everything else: compact bus, two short wings.
  generic: `
    <rect x="-17" y="-4" width="11" height="8" ${PANEL}/>
    <rect x="6" y="-4" width="11" height="8" ${PANEL}/>
    <path d="M-6,0 H-4 M4,0 H6" stroke="white" stroke-width="1.6"/>
    <rect x="-4" y="-5" width="8" height="10" rx="1" ${BUS}/>`,
};

/** Satellite family from its CelesTrak group (and the station NORAD ids). */
export function classifySatellite(group: string, noradId: string): SatelliteKind {
  if (noradId === "25544" || noradId === "48274") return "station"; // ISS, Tiangong
  if (group === "gps-ops" || group === "galileo") return "nav";
  if (group === "starlink") return "starlink";
  if (group === "weather") return "weather";
  return "generic";
}

/** Class colours after God's Eye View's satellite classes (station warm
 *  white, navigation cyan, comms constellation dim slate, catch-all
 *  blue-grey); weather gets its own green so it stays separable. */
export const SATELLITE_COLORS: Record<SatelliteKind, string> = {
  station: "#fff6e5",
  nav: "#4fd8ff",
  starlink: "#6f88a3",
  weather: "#7fe0b0",
  generic: "#9fb3c4",
};

export function satelliteIcon(kind: SatelliteKind): string {
  const key = `sat:${kind}`;
  let uri = iconCache.get(key);
  if (!uri) {
    uri = svgUri(
      `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="-24 -24 48 48">${SATELLITES[kind]}</svg>`
    );
    iconCache.set(key, uri);
  }
  return uri;
}

const scratchEnu = new Matrix4();
const scratchCol = new Cartesian4();

/** Local north at a position, for billboard.alignedAxis. With it, an icon's
 *  up edge points true north from ANY camera angle (including locked orbits),
 *  so rotation = -heading points it along its course. The old
 *  alignedAxis = UNIT_Z (Earth's spin axis) only matches north near the
 *  equator in a top-down view; at oblique angles and higher latitudes it
 *  skewed headings. */
export function northAxis(position: Cartesian3, result = new Cartesian3()): Cartesian3 {
  Transforms.eastNorthUpToFixedFrame(position, undefined, scratchEnu);
  Matrix4.getColumn(scratchEnu, 1, scratchCol);
  return Cartesian3.fromElements(scratchCol.x, scratchCol.y, scratchCol.z, result);
}

// ── Type-aware classification ─────────────────────────────────────────────

const HELI = new Set([
  'EC20',
  'EC25',
  'EC30',
  'EC35',
  'EC45',
  'EC55',
  'AS50',
  'AS55',
  'AS65',
  'AS32',
  'A109',
  'A119',
  'A139',
  'A169',
  'A189',
  'B06',
  'B06T',
  'B407',
  'B412',
  'B427',
  'B429',
  'B430',
  'B505',
  'S76',
  'S92',
  'S61',
  'S64',
  'H60',
  'H500',
  'MD52',
  'MD60',
  'R22',
  'R44',
  'R66',
  'EXEC',
  'EXPL',
  'GAZL',
  'LYNX',
  'NH90',
  'PUMA',
  'SCAV',
  'UH1',
  'B105',
  'B212',
  'B214',
  'B222',
  'AC',
  'H47',
  'H64',
]);
const QUAD = new Set([
  'B741',
  'B742',
  'B743',
  'B744',
  'B748',
  'B74S',
  'B74R',
  'B74D',
  'A388',
  'A342',
  'A343',
  'A345',
  'A346',
  'A124',
  'C5M',
  'A225',
  'IL96',
  'B52',
  'A140',
]);
const WIDE = new Set([
  'A306',
  'A30B',
  'A310',
  'A332',
  'A333',
  'A338',
  'A339',
  'A359',
  'A35K',
  'B762',
  'B763',
  'B764',
  'B772',
  'B77L',
  'B773',
  'B77W',
  'B778',
  'B779',
  'B788',
  'B789',
  'B78X',
  'MD11',
  'IL86',
  'DC10',
  'L101',
  'A337',
  'B767',
  'B777',
  'B787',
  'C17',
  'K35R', // military heavies that read as widebodies
]);
const TPROP = new Set([
  'DH8A',
  'DH8B',
  'DH8C',
  'DH8D',
  'AT43',
  'AT44',
  'AT45',
  'AT46',
  'AT72',
  'AT73',
  'AT75',
  'AT76',
  'SF34',
  'SB20',
  'SW3',
  'SW4',
  'E110',
  'E120',
  'C208',
  'C212',
  'C408',
  'PC12',
  'B190',
  'BE20',
  'B350',
  'B300',
  'JS31',
  'JS32',
  'JS41',
  'D228',
  'D328',
  'F50',
  'F27',
  'ATP',
  'TBM7',
  'TBM8',
  'TBM9',
  'TBM0',
  'PC6',
  'C441',
  'C425',
  'DHC6',
  'DHC7',
  'C130',
  'AN12',
  'AN26',
  'AN32',
  'SH36',
  'CVLT',
  'SAAB',
  'A400',
]);
const GLIDER = new Set([
  'DISC',
  'DUOD',
  'VENT',
  'NIMB',
  'NIM3',
  'NIM4',
  'JANS',
  'ARCE',
  'DG40',
  'DG80',
  'DG1T',
  'DG30',
  'DG50',
  'LS3',
  'LS4',
  'LS6',
  'LS7',
  'LS8',
  'STD3',
  'G103',
  'G102',
  'G104',
  'PW5',
  'PW6',
  'L13',
  'L23',
  'L33',
  'PIK',
  'PEGA',
  'KEST',
  'TWIN',
  'AS33',
  'ASW',
  'ASG',
  'ASK',
  'VENS',
  'GLID',
  'MOSQ',
  'DIMO',
]);
const LIGHT = new Set([
  'C150',
  'C152',
  'C162',
  'C172',
  'C72R',
  'C175',
  'C177',
  'C180',
  'C182',
  'C185',
  'C188',
  'C206',
  'C207',
  'C210',
  'C310',
  'C337',
  'SR20',
  'SR22',
  'S22T',
  'PA18',
  'PA24',
  'PA28',
  'P28A',
  'P28B',
  'P28R',
  'PA32',
  'P32R',
  'PA34',
  'PA38',
  'PA44',
  'PA46',
  'DA20',
  'DA40',
  'DA42',
  'DA62',
  'BE33',
  'BE35',
  'BE36',
  'BE58',
  'BE76',
  'BE19',
  'BE23',
  'BE24',
  'M20P',
  'M20T',
  'AA1',
  'AA5',
  'GLAS',
  'COL4',
  'RV4',
  'RV6',
  'RV7',
  'RV8',
  'RV9',
  'RV10',
  'RV14',
  'GA8',
  'G115',
  'BL8',
  'CH7',
]);
// GEV addition (2026-08-15 Hangar fleet): business jets — distinct class so the
// Citation II GLB + a slimmer glyph read apart from airliners.
const BIZJET = new Set([
  'C500',
  'C501',
  'C510',
  'C525',
  'C25A',
  'C25B',
  'C25C',
  'C25M',
  'C550',
  'C551',
  'C560',
  'C56X',
  'C650',
  'C680',
  'C68A',
  'C700',
  'C750',
  'CL30',
  'CL35',
  'CL60',
  'GLF2',
  'GLF3',
  'GLF4',
  'GLF5',
  'GLF6',
  'GA5C',
  'GA6C',
  'G150',
  'G280',
  'GL5T',
  'GL7T',
  'GLEX',
  'LJ23',
  'LJ24',
  'LJ25',
  'LJ31',
  'LJ35',
  'LJ40',
  'LJ45',
  'LJ55',
  'LJ60',
  'LJ70',
  'LJ75',
  'FA10',
  'FA20',
  'FA50',
  'FA7X',
  'FA8X',
  'F900',
  'F2TH',
  'H25A',
  'H25B',
  'H25C',
  'HDJT',
  'E50P',
  'E55P',
  'E545',
  'E550',
  'PC24',
  'PRM1',
  'BE40',
  'ASTR',
  'WW24',
  'SF50', // Cirrus Vision Jet — a JET (was mis-set in LIGHT before the bizjet class existed)
]);
// GEV addition (2026-08-15 Hangar fleet): large UAVs — ICAO designators seen on
// ADS-B/adsb.lol for Predator/Reaper/Global Hawk-class airframes.
const UAV = new Set([
  'Q1',
  'Q4',
  'Q9',
  'MQ1',
  'MQ4',
  'MQ9',
  'RQ4',
  'TB2',
  'SHDW',
  'HERN',
]);
// GEV addition: fast jets, for the military layer's adsb.lol `t` codes.
const FASTJET = new Set([
  'F16',
  'F15',
  'F18',
  'FA18',
  'F14',
  'F22',
  'F35',
  'F4',
  'F5',
  'A10',
  'AV8B',
  'TYPH',
  'EUFI',
  'RFAL',
  'RAFL',
  'GRIP',
  'JAS39',
  'TOR',
  'MIR2',
  'M2000',
  'SU27',
  'SU30',
  'SU33',
  'SU34',
  'SU35',
  'SU57',
  'MG29',
  'MIG29',
  'MG31',
  'J20',
  'T38',
  'HAWK',
  'L39',
  'M346',
  'T7A',
]);

/** OpenSky extended-states integer category → class. */
const OPENSKY_CATEGORY: Record<number, AircraftClass> = {
  2: 'light', // Light (< 15 500 lbs)
  3: 'airliner', // Small
  4: 'airliner', // Large
  5: 'airliner', // High-vortex large (B757)
  6: 'widebody', // Heavy
  7: 'fastjet', // High performance (>5g, >400 kt)
  8: 'helicopter', // Rotorcraft
  9: 'glider',
};

/** ADS-B emitter-category string → class. */
const EMITTER_CATEGORY: Record<string, AircraftClass> = {
  A1: 'light',
  A2: 'light',
  A3: 'airliner',
  A4: 'airliner',
  A5: 'widebody',
  A6: 'fastjet',
  A7: 'helicopter',
  B1: 'glider',
};

export function classifyAircraft({ typeCode, category }: { typeCode?: string; category?: number | string | null } = {}): AircraftClass {
  const code = String(typeCode || '')
    .trim()
    .toUpperCase();
  if (code) {
    if (code.startsWith('B74')) return 'b747';
    if (code === 'A388') return 'a380';
    if (FASTJET.has(code)) return 'fastjet';
    if (UAV.has(code)) return 'uav';
    if (HELI.has(code)) return 'helicopter';
    if (QUAD.has(code)) return 'quadjet';
    if (WIDE.has(code)) return 'widebody';
    if (TPROP.has(code)) return 'turboprop';
    if (GLIDER.has(code)) return 'glider';
    if (BIZJET.has(code)) return 'bizjet';
    if (LIGHT.has(code)) return 'light';
    return 'airliner'; // known type code, not in a special set → default jet
  }
  if (typeof category === 'number' && Number.isFinite(category) && OPENSKY_CATEGORY[category])
    return OPENSKY_CATEGORY[category];
  const cat = String(category || '')
    .trim()
    .toUpperCase();
  if (EMITTER_CATEGORY[cat]) return EMITTER_CATEGORY[cat];
  return 'airliner';
}
