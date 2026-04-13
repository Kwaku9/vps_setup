export interface CCTVCamera {
  id: string;
  name: string;
  lat: number;
  lon: number;
  snapshotUrl: string;
  streamUrl?: string;
  city: string;
  direction: string;
}

/**
 * Fetch cameras from all available sources.
 * Sources: NYC DOT, Caltrans (LA/SoCal), Florida 511, TxDOT (5 districts),
 *          Illinois/Chicago (ArcGIS), DC (DDOT), Georgia 511
 */
export async function fetchCameras(): Promise<CCTVCamera[]> {
  const results = await Promise.allSettled([
    fetchNYC(),
    fetchCaltrans(),
    fetchFlorida(),
    fetchTexas(),
    fetchChicago(),
    fetchDC(),
    fetchGeorgia(),
  ]);

  const all: CCTVCamera[] = [];
  for (const r of results) {
    if (r.status === "fulfilled") all.push(...r.value);
    else console.warn("CCTV source failed:", r.reason);
  }

  console.log(`CCTV: loaded ${all.length} cameras from ${results.filter(r => r.status === 'fulfilled').length}/${results.length} sources`);
  return all;
}

export function getSnapshotUrl(camera: CCTVCamera): string {
  if (camera.city === "NYC") {
    return camera.snapshotUrl + "?t=" + Date.now();
  }
  return camera.snapshotUrl;
}

// ── NYC DOT Traffic Cameras ─────────────────────────────

async function fetchNYC(): Promise<CCTVCamera[]> {
  const resp = await fetch("/api/cctv/api/cameras");
  if (!resp.ok) throw new Error("NYC CCTV API " + resp.status);

  const data: any[] = await resp.json();

  return data
    .filter((c: any) => c.latitude && c.longitude && c.id)
    .map((c: any) => ({
      id: "nyc-" + c.id,
      name: c.name || "NYC Camera",
      lat: c.latitude,
      lon: c.longitude,
      snapshotUrl: "/api/cctv/api/cameras/" + c.id + "/image",
      city: "NYC",
      direction: c.direction || "",
    }));
}

// ── Caltrans CCTV (District 7 = LA/SoCal, ~470 cameras) ──

async function fetchCaltrans(): Promise<CCTVCamera[]> {
  const resp = await fetch("/api/caltrans/d7/cctv/cctvStatusD07.json");
  if (!resp.ok) throw new Error("Caltrans API " + resp.status);

  const json = await resp.json();
  const entries: any[] = json.data || [];

  return entries
    .filter((e: any) => {
      const loc = e.cctv?.location;
      return loc?.latitude && loc?.longitude && e.cctv?.inService === "true";
    })
    .map((e: any) => {
      const cam = e.cctv;
      const loc = cam.location;
      const img = cam.imageData?.static?.currentImageURL || "";
      const stream = cam.imageData?.streamingVideoURL || "";
      return {
        id: "ca-" + cam.index,
        name: loc.locationName || "Caltrans Camera",
        lat: parseFloat(loc.latitude),
        lon: parseFloat(loc.longitude),
        snapshotUrl: img,
        streamUrl: stream || undefined,
        city: "Los Angeles",
        direction: loc.direction || "",
      };
    });
}

// ── Florida 511 (statewide, ~4600 cameras) ──────────────

async function fetchFlorida(): Promise<CCTVCamera[]> {
  const resp = await fetch("/api/fl511/map/mapIcons/Cameras");
  if (!resp.ok) throw new Error("FL511 API " + resp.status);

  const json = await resp.json();
  const entries: any[] = json.item2 || [];

  return entries
    .filter(
      (c: any) =>
        c.location &&
        c.location.length === 2 &&
        c.location[0] !== 0 &&
        c.location[1] !== 0
    )
    .map((c: any) => ({
      id: "fl-" + c.itemId,
      name: c.title || "FL Camera",
      lat: c.location[0],
      lon: c.location[1],
      snapshotUrl: "/api/fl511/map/Cctv/" + c.itemId,
      city: "FL",
      direction: "",
    }));
}

// ── TxDOT (Texas, 5 major districts) ────────────────────

async function fetchTexas(): Promise<CCTVCamera[]> {
  const districts: [string, string][] = [
    ["HOU", "Houston"],
    ["DAL", "Dallas"],
    ["AUS", "Austin"],
    ["SAT", "San Antonio"],
    ["FTW", "Fort Worth"],
  ];

  const results = await Promise.allSettled(
    districts.map(async ([code, cityName]) => {
      const resp = await fetch(
        `/api/txdot/DistrictIts/GetCctvStatusListByDistrict?districtCode=${code}`
      );
      if (!resp.ok) throw new Error(`TxDOT ${code}: ${resp.status}`);
      const json = await resp.json();
      const roadways: Record<string, any[]> = json.roadwayCctvStatuses || {};
      const cams: CCTVCamera[] = [];

      for (const camList of Object.values(roadways)) {
        for (const c of camList) {
          if (c.latitude && c.longitude) {
            cams.push({
              id: `tx-${code}-${c.icd_Id || c.name}`,
              name: c.name || "TxDOT Camera",
              lat: c.latitude,
              lon: c.longitude,
              snapshotUrl: "",
              city: cityName,
              direction: c.dirDescription || "",
            });
          }
        }
      }
      return cams;
    })
  );

  const cameras: CCTVCamera[] = [];
  for (const r of results) {
    if (r.status === "fulfilled") cameras.push(...r.value);
    else console.warn("TxDOT district failed:", r.reason);
  }
  return cameras;
}

// ── Illinois / Chicago (ArcGIS FeatureServer) ────────────

async function fetchChicago(): Promise<CCTVCamera[]> {
  const resp = await fetch(
    "/api/ilcams/aIrBD8yn1TDTEXoz/arcgis/rest/services/TrafficCamerasTM_Public/FeatureServer/0/query" +
    "?where=1%3D1&outFields=*&f=json&resultRecordCount=5000"
  );
  if (!resp.ok) throw new Error("IL CCTV API " + resp.status);

  const json = await resp.json();
  const features: any[] = json.features || [];

  return features
    .filter((f: any) => f.attributes?.x && f.attributes?.y)
    .map((f: any) => ({
      id: "il-" + f.attributes.OBJECTID,
      name: f.attributes.CameraLocation || "IL Camera",
      lat: f.attributes.y,
      lon: f.attributes.x,
      snapshotUrl: f.attributes.SnapShot || "",
      city: "Illinois",
      direction: f.attributes.CameraDirection || "",
    }));
}

// ── Washington DC (DDOT, location-only) ──────────────────

async function fetchDC(): Promise<CCTVCamera[]> {
  const resp = await fetch(
    "/api/dccams/dcgis/rest/services/DCGIS_DATA/Transportation_Sensors_WebMercator/MapServer/93/query" +
    "?where=1%3D1&outFields=*&outSR=4326&f=geojson"
  );
  if (!resp.ok) throw new Error("DC CCTV API " + resp.status);

  const json = await resp.json();
  const features: any[] = json.features || [];

  return features
    .filter(
      (f: any) =>
        f.geometry?.coordinates?.length === 2 &&
        f.geometry.coordinates[0] !== 0
    )
    .map((f: any) => ({
      id: "dc-" + f.properties.OBJECTID,
      name: `DC Camera ${f.properties.FACILITYID || f.properties.CAMERAID || ""}`,
      lat: f.geometry.coordinates[1],
      lon: f.geometry.coordinates[0],
      snapshotUrl: "",
      city: "DC",
      direction: "",
    }));
}

// ── Georgia 511 (statewide, ~3800 cameras) ───────────────

async function fetchGeorgia(): Promise<CCTVCamera[]> {
  const resp = await fetch("/api/ga511/map/mapIcons/Cameras");
  if (!resp.ok) throw new Error("GA511 API " + resp.status);

  const json = await resp.json();
  const entries: any[] = json.item2 || [];

  return entries
    .filter(
      (c: any) =>
        c.location &&
        c.location.length === 2 &&
        c.location[0] !== 0 &&
        c.location[1] !== 0
    )
    .map((c: any) => ({
      id: "ga-" + c.itemId,
      name: c.title || "GA Camera",
      lat: c.location[0],
      lon: c.location[1],
      snapshotUrl: "/api/ga511/map/Cctv/" + c.itemId,
      city: "GA",
      direction: "",
    }));
}
