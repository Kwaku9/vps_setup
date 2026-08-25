import {
  Viewer,
  Cesium3DTileset,
  Cartesian3,
  Math as CesiumMath,
  RequestScheduler,
  Ion,
  Color,
  TileMapServiceImageryProvider,
  buildModuleUrl,
} from 'cesium';
import { config } from '@/config';

// ── Tile quality presets ────────────────────────────────────────────────────
// SSE ↑ = blockier but far fewer tile requests/RAM; cacheBytes governs how
// much revisiting costs. MED is the default balance for a 2-core VPS-served
// client; HIGH is for beefy clients on fast links.
export type TileQuality = 'low' | 'med' | 'high';

const TILE_PRESETS: Record<TileQuality, { sse: number; cacheBytes: number }> = {
  low:  { sse: 28, cacheBytes: 256 * 1024 * 1024 },
  med:  { sse: 16, cacheBytes: 512 * 1024 * 1024 },
  high: { sse: 8,  cacheBytes: 1024 * 1024 * 1024 },
};

let googleTileset: Cesium3DTileset | null = null;
let fallbackActive = false;

export function setTileQuality(q: TileQuality): void {
  if (!googleTileset) return;
  const p = TILE_PRESETS[q];
  googleTileset.maximumScreenSpaceError = p.sse;
  googleTileset.cacheBytes = p.cacheBytes;
}

export function isFallbackGlobeActive(): boolean {
  return fallbackActive;
}

export async function createViewer(containerId: string): Promise<Viewer> {
  if (config.cesiumIonToken) {
    Ion.defaultAccessToken = config.cesiumIonToken;
  }

  // Concurrent tile request budget (Cesium's own scheduler — API traffic is
  // governed separately by src/net/orchestrator.ts).
  RequestScheduler.maximumRequests = 18;
  RequestScheduler.maximumRequestsPerServer = 18;

  const viewer = new Viewer(containerId, {
    // Globe stays constructed as the fallback surface; it is hidden once the
    // Google tileset streams in (the old build had globe:false and rendered a
    // black void when Google failed).
    baseLayer: false,
    animation: false,
    baseLayerPicker: false,
    fullscreenButton: false,
    geocoder: false,
    homeButton: false,
    infoBox: false,
    sceneModePicker: false,
    selectionIndicator: false,
    timeline: false,
    navigationHelpButton: false,
    requestRenderMode: false,
    creditContainer: undefined,
  });

  // Offline Natural Earth II base imagery — guaranteed fallback, no keys.
  try {
    const naturalEarth = await TileMapServiceImageryProvider.fromUrl(
      buildModuleUrl('Assets/Textures/NaturalEarthII')
    );
    viewer.imageryLayers.addImageryProvider(naturalEarth);
  } catch (e) {
    console.warn('Offline base imagery unavailable:', e);
  }

  viewer.scene.backgroundColor = Color.BLACK;
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 100;

  // Guard against frustum RangeError before tiles have loaded
  viewer.scene.camera.frustum.near = 1.0;
  viewer.scene.camera.frustum.far = 500000000.0;

  if (config.googleMapsApiKey) {
    try {
      console.log('Loading Google Photorealistic 3D Tiles...');
      const preset = TILE_PRESETS.med;
      const tileset = await Cesium3DTileset.fromUrl(
        `https://tile.googleapis.com/v1/3dtiles/root.json?key=${config.googleMapsApiKey}`,
        {
          showCreditsOnScreen: true,
          maximumScreenSpaceError: preset.sse,
          cacheBytes: preset.cacheBytes,
          maximumCacheOverflowBytes: 128 * 1024 * 1024,
          // Skip intermediate LODs on deep zooms — fewer requests, faster focus.
          skipLevelOfDetail: true,
          skipScreenSpaceErrorFactor: 16,
          skipLevels: 1,
          // Relax detail at the horizon and screen edges.
          dynamicScreenSpaceError: true,
          dynamicScreenSpaceErrorDensity: 2.0e-4,
          dynamicScreenSpaceErrorFactor: 24.0,
          foveatedScreenSpaceError: true,
          // Don't burn quota while the tab is hidden.
          preloadWhenHidden: false,
        }
      );
      viewer.scene.primitives.add(tileset);
      googleTileset = tileset;
      // Google surface replaces the fallback globe.
      viewer.scene.globe.show = false;
      console.log('Google Photorealistic 3D Tiles loaded successfully');
    } catch (e) {
      console.error('Failed to load Google 3D Tiles — using fallback globe:', e);
      fallbackActive = true;
    }
  } else {
    console.warn('No Google Maps API key — using fallback globe');
    fallbackActive = true;
  }

  viewer.camera.setView({
    destination: Cartesian3.fromDegrees(-98.0, 39.5, 15000000),
    orientation: {
      heading: 0,
      pitch: CesiumMath.toRadians(-90),
      roll: 0,
    },
  });

  viewer.scene.requestRender();

  return viewer;
}
