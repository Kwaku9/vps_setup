import "cesium/Build/Cesium/Widgets/widgets.css";
import { Cartesian3 } from "cesium";
import { installOrchestrator } from "@/net/orchestrator";
import { createViewer } from "@/globe/viewer";
import { CameraController } from "@/globe/camera";
import { getPOIByKey } from "@/globe/poi";
import { ShaderManager, VisionMode } from "@/shaders/postprocess";
import { EffectsManager } from "@/shaders/effects";
import { LayerManager, LayerName } from "@/layers/layer-manager";
import { ControlsPanel } from "@/ui/controls-panel";
import { EntityInfoPanel } from "@/ui/entity-info";
import { HUDOverlay } from "@/ui/hud-overlay";
import { LocationsBar } from "@/ui/locations-bar";
import { ParametersPanel } from "@/ui/parameters-panel";
import { RightSidebar } from "@/ui/right-sidebar";
import { HUDDock } from "@/ui/hud-dock";
import { worldAudio } from "@/audio/engine";

// Cinematic hide-all: fade every HUD panel out for a clean globe.
function installCinematicStyles(): void {
  const style = document.createElement("style");
  style.textContent = `
    .wv-hud-panel { transition: opacity 300ms ease; }
    body.wv-cinematic .wv-hud-panel { opacity: 0 !important; pointer-events: none !important; }
    @media (prefers-reduced-motion: reduce) { .wv-hud-panel { transition: none; } }
  `;
  document.head.appendChild(style);
}

async function init() {
  // Must precede every layer: wraps window.fetch with per-upstream rate
  // budgets, coalescing, backoff, and circuit breakers.
  installOrchestrator();
  installCinematicStyles();
  worldAudio.installAutoArm();

  const viewer = await createViewer("cesiumContainer");
  const camera = new CameraController(viewer);
  const shaders = new ShaderManager(viewer.scene);
  const effects = new EffectsManager(viewer.scene);
  const layers = new LayerManager(viewer);
  const controls = new ControlsPanel();
  const entityInfo = new EntityInfoPanel(viewer);
  const hud = new HUDOverlay(viewer);
  const locationsBar = new LocationsBar(camera);
  const params = new ParametersPanel(viewer.scene);
  const rightSidebar = new RightSidebar(shaders, layers, controls);
  const hudDock = new HUDDock(layers);
  hudDock.setOnHideAll((hidden) => {
    document.body.classList.toggle("wv-cinematic", hidden);
  });

  // Wire up controls panel
  controls.setOnModeChange((mode: VisionMode) => {
    shaders.setMode(mode);
    controls.updateActiveMode(mode);
  });

  controls.setOnLayerToggle((name: string) => {
    layers.toggleLayer(name as LayerName);
    controls.updateLayers(layers.getStatus());
  });

  let bloomOn = false;
  controls.setOnBloomToggle(() => {
    bloomOn = effects.toggleBloom();
    controls.updateBloom(bloomOn);
  });

  controls.updateActiveMode("normal");

  // Keyboard bindings
  document.addEventListener("keydown", (e) => {
    if ((e.target as HTMLElement).tagName === "INPUT") return;

    const key = e.key.toLowerCase();

    // Vision modes: 1-4
    const modeMap: Record<string, VisionMode> = {
      "1": "normal",
      "2": "crt",
      "3": "nvg",
      "4": "flir",
    };
    if (modeMap[key]) {
      shaders.setMode(modeMap[key]);
      controls.updateActiveMode(modeMap[key]);
      return;
    }

    // Cinematic hide-all HUD
    if (key === "`") {
      hudDock.toggleHideAll();
      return;
    }

    // Country borders overlay
    if (key === "8") {
      layers.toggleLayer("borders");
      controls.updateLayers(layers.getStatus());
      worldAudio.layerToggle();
      return;
    }

    // POI keys
    const poi = getPOIByKey(key);
    if (poi) {
      camera.flyTo(poi.target);
      worldAudio.flyTo();
      return;
    }

    // Layer toggles
    if (key === "b") {
      bloomOn = effects.toggleBloom();
      controls.updateBloom(bloomOn);
      return;
    }

    if (key === "c") {
      layers.toggleLayer("cctv");
      controls.updateLayers(layers.getStatus());
      return;
    }

    if (key === "v") {
      layers.toggleLayer("traffic");
      controls.updateLayers(layers.getStatus());
      return;
    }

    if (key === "g") {
      layers.toggleLayer("wigle");
      controls.updateLayers(layers.getStatus());
      return;
    }

    if (key === "x") {
      layers.toggleLayer("firms");
      controls.updateLayers(layers.getStatus());
      return;
    }

    if (key === "z") {
      layers.toggleLayer("acled");
      controls.updateLayers(layers.getStatus());
      return;
    }

    if (key === "9") {
      layers.toggleLayer("threats");
      controls.updateLayers(layers.getStatus());
      return;
    }
if (key === "6") {
      layers.toggleLayer("maritime");
      controls.updateLayers(layers.getStatus());
      return;
    }

    if (key === "a") {
      layers.toggleLayer("artemis");
      controls.updateLayers(layers.getStatus());
      return;
    }

    // Panel toggles
    if (key === "[") {
      controls.toggle();
      return;
    }

    if (key === "]") {
      rightSidebar.toggle();
      return;
    }

    if (key === "\\") {
      params.toggle();
      return;
    }

    if (key === "/") {
      e.preventDefault(); // Prevent browser quick-find
      locationsBar.toggle();
      return;
    }

    if (key === "h") {
      hud.toggle();
      return;
    }
  });

  // Load all data layers
  await layers.loadAll();
  controls.updateLayers(layers.getStatus());

  // Wire camera-awareness for traffic, wigle, and firms
  let cameraDebounce: number | null = null;
  viewer.camera.changed.addEventListener(() => {
    if (cameraDebounce !== null) clearTimeout(cameraDebounce);
    cameraDebounce = window.setTimeout(() => {
      layers.traffic.onCameraMove();
      layers.wigle.onCameraMove();
      layers.firms.onCameraMove();
      layers.earthquakes.onCameraMove();
    }, 2000);
  });

  // Periodically refresh layer counts
  setInterval(() => {
    controls.updateLayers(layers.getStatus());
  }, 10000);

  // Earth rotation — one full revolution every 20 minutes
  const EARTH_ROTATION_RATE = (2 * Math.PI) / 1200;
  let earthRotationEnabled = true; // user toggle (Spacebar)
  let earthRotationActive = true;  // auto-pause during interaction
  let lastRotateTime = Date.now();

  // Pause rotation when user interacts, resume after 3s idle
  let rotateIdleTimer: number | null = null;
  const pauseEarthRotation = () => {
    earthRotationActive = false;
    if (rotateIdleTimer !== null) clearTimeout(rotateIdleTimer);
    rotateIdleTimer = window.setTimeout(() => {
      earthRotationActive = true;
      lastRotateTime = Date.now();
    }, 3000);
  };

  viewer.scene.canvas.addEventListener("pointerdown", pauseEarthRotation);
  viewer.scene.canvas.addEventListener("wheel", pauseEarthRotation);

  // Spacebar toggles rotation on/off
  document.addEventListener("keydown", (e) => {
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    if (e.key === " ") {
      e.preventDefault();
      earthRotationEnabled = !earthRotationEnabled;
      lastRotateTime = Date.now();
      console.log("Earth rotation: " + (earthRotationEnabled ? "ON" : "PAUSED"));
    }
  });

  viewer.clock.onTick.addEventListener(() => {
    if (!earthRotationEnabled || !earthRotationActive) {
      lastRotateTime = Date.now();
      return;
    }
    const now = Date.now();
    const dt = (now - lastRotateTime) / 1000;
    lastRotateTime = now;
    if (dt > 1) return; // skip large gaps (tab hidden, etc.)
    viewer.camera.rotate(Cartesian3.UNIT_Z, -EARTH_ROTATION_RATE * dt);
  });

  // --- URL parameter handling (Grafana deep-link integration) ---
  applyURLParams(camera, layers);

  console.log("WorldView initialized");
}

/** Country ISO-3166 → [lat, lon, viewHeight] centroids for fly-to on ?country= */
const COUNTRY_CENTROIDS: Record<string, [number, number, number]> = {
  CN: [35.86,  104.19, 4_500_000],
  RU: [61.52,  105.32, 7_000_000],
  US: [37.09,  -95.71, 5_500_000],
  DE: [51.17,   10.45, 1_200_000],
  NL: [52.13,    5.29,   600_000],
  FR: [46.23,    2.21, 1_500_000],
  GB: [55.38,   -3.44, 1_000_000],
  BR: [-14.24, -51.93, 5_000_000],
  IN: [20.59,   78.96, 4_000_000],
  KR: [35.91,  127.77,   700_000],
  JP: [36.20,  138.25,   900_000],
  SG: [ 1.35,  103.82,   300_000],
  UA: [48.38,   31.17, 1_000_000],
  IR: [32.43,   53.69, 1_500_000],
  VN: [14.06,  108.28, 1_200_000],
  HK: [22.40,  114.11,   200_000],
  TW: [23.70,  120.96,   400_000],
  CA: [56.13, -106.35, 5_000_000],
  AU: [-25.27,  133.78, 5_000_000],
  ID: [-0.79,  113.92, 3_000_000],
  RO: [45.94,   24.97,   800_000],
  PL: [51.92,   19.14,   800_000],
  CZ: [49.82,   15.47,   500_000],
  TR: [38.96,   35.24, 1_500_000],
  PK: [30.38,   69.35, 2_000_000],
  TH: [15.87,  100.99, 1_200_000],
};

function applyURLParams(camera: CameraController, layers: LayerManager): void {
  const params = new URLSearchParams(window.location.search);

  const country = params.get("country")?.toUpperCase() ?? null;
  const lat = parseFloat(params.get("lat") ?? "");
  const lon = parseFloat(params.get("lon") ?? "");
  const height = parseFloat(params.get("height") ?? "");

  // Country filter — show only threats from this country + fly to attacker
  if (country) {
    layers.threats.setCountryFilter(country);
    layers.threats.setVisible(true);

    // When arriving from Grafana cyber map, show only relevant layers
    layers.satellites.setVisible(true);
    layers.weather.setVisible(true);
    layers.flights.setVisible(true);
    layers.military.setVisible(false);
    layers.earthquakes.setVisible(false);
    layers.cctv.setVisible(false);
    layers.traffic.setVisible(false);
    layers.wigle.setVisible(false);
    layers.firms.setVisible(false);
    layers.acled.setVisible(false);

    // Try to fly to the most recent attacker's actual location
    const latest = layers.threats.getLatestForCountry(country);
    if (latest) {
      camera.flyTo({
        longitude: latest.longitude,
        latitude: latest.latitude,
        height: 500_000,
        pitch: -35,
      });
      console.log(
        `WorldView: flying to latest ${country} threat — ${latest.ip} at [${latest.latitude.toFixed(2)}, ${latest.longitude.toFixed(2)}]`
      );
    } else {
      const centroid = COUNTRY_CENTROIDS[country];
      if (centroid) {
        camera.flyTo({ longitude: centroid[1], latitude: centroid[0], height: centroid[2] });
      } else if (!isNaN(lat) && !isNaN(lon)) {
        camera.flyTo({ longitude: lon, latitude: lat, height: isNaN(height) ? 2_000_000 : height });
      }
      console.log(`WorldView: filtering threats to country=${country} (centroid fallback)`);
    }
    return;
  }

  // Explicit lat/lon/height fly-to (without country filter)
  if (!isNaN(lat) && !isNaN(lon)) {
    camera.flyTo({ longitude: lon, latitude: lat, height: isNaN(height) ? 2_000_000 : height });
  }
}

init().catch((e) => console.error("WorldView init failed:", e));
