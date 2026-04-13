export const config = {
  googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? '',
  cesiumIonToken: import.meta.env.VITE_CESIUM_ION_TOKEN ?? '',
  openSky: {
    username: import.meta.env.VITE_OPENSKY_USERNAME ?? '',
    password: import.meta.env.VITE_OPENSKY_PASSWORD ?? '',
  },
  adsbApiKey: import.meta.env.VITE_ADSB_API_KEY ?? '',
  firmsMapKey: import.meta.env.VITE_FIRMS_MAP_KEY ?? '',
} as const;
