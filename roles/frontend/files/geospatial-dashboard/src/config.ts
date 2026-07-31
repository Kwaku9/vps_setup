export const config = {
  googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? '',
  cesiumIonToken: import.meta.env.VITE_CESIUM_ION_TOKEN ?? '',
  firmsMapKey: import.meta.env.VITE_FIRMS_MAP_KEY ?? '',
  // OpenSky / ADS-B keys removed: nothing in the client used them, and quota
  // credentials must not ship to browsers. Flights come via /api/planes.
} as const;
