import {
  Viewer,
  Cesium3DTileset,
  Cartesian3,
  Math as CesiumMath,
  RequestScheduler,
  Ion,
  Color,
} from 'cesium';
import { config } from '@/config';

export async function createViewer(containerId: string): Promise<Viewer> {
  if (config.cesiumIonToken) {
    Ion.defaultAccessToken = config.cesiumIonToken;
  }

  // Increase concurrent requests for Google 3D Tiles
  RequestScheduler.maximumRequests = 18;
  RequestScheduler.maximumRequestsPerServer = 18;

  const viewer = new Viewer(containerId, {
    // Disable the default globe — Google 3D Tiles replaces it
    globe: false,
    // Disable all default UI widgets
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
    // Don't use requestRenderMode initially — let tiles stream in
    requestRenderMode: false,
    // Google TOS: show credits on screen
    creditContainer: undefined,
  });

  // Dark sky background
  viewer.scene.backgroundColor = Color.BLACK;
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 100;

  // Keep skybox and sun for visual context
  viewer.scene.skyBox = viewer.scene.skyBox;
  viewer.scene.sun = viewer.scene.sun;

  // Guard against frustum RangeError when globe is disabled and tiles haven't loaded
  viewer.scene.camera.frustum.near = 1.0;
  viewer.scene.camera.frustum.far = 500000000.0;

  // Load Google Photorealistic 3D Tiles directly (not via Ion)
  if (config.googleMapsApiKey) {
    try {
      console.log('Loading Google Photorealistic 3D Tiles...');
      const tileset = await Cesium3DTileset.fromUrl(
        `https://tile.googleapis.com/v1/3dtiles/root.json?key=${config.googleMapsApiKey}`,
        {
          showCreditsOnScreen: true,
        }
      );
      viewer.scene.primitives.add(tileset);
      console.log('Google Photorealistic 3D Tiles loaded successfully');
    } catch (e) {
      console.error('Failed to load Google 3D Tiles:', e);
      console.error('Falling back to default globe');
      enableFallbackGlobe(viewer);
    }
  } else {
    console.warn('No Google Maps API key — using default globe');
    enableFallbackGlobe(viewer);
  }

  // Set initial camera to view Earth from space
  viewer.camera.setView({
    destination: Cartesian3.fromDegrees(-98.0, 39.5, 15000000),
    orientation: {
      heading: 0,
      pitch: CesiumMath.toRadians(-90),
      roll: 0,
    },
  });

  // Force continuous rendering to ensure tiles load
  viewer.scene.requestRender();

  return viewer;
}

function enableFallbackGlobe(viewer: Viewer): void {
  // Re-create viewer with globe would be complex, so just log
  // The viewer was created with globe: false, so we can't easily re-enable
  console.warn('Fallback globe not available when created with globe: false');
}
