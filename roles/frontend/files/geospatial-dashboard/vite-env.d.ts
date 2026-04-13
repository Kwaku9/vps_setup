/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GOOGLE_MAPS_API_KEY: string;
  readonly VITE_CESIUM_ION_TOKEN: string;
  readonly VITE_OPENSKY_USERNAME: string;
  readonly VITE_OPENSKY_PASSWORD: string;
  readonly VITE_ADSB_API_KEY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.glsl?raw' {
  const value: string;
  export default value;
}
