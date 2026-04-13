import { CameraTarget } from "./camera";

export interface POI {
  name: string;
  target: CameraTarget;
  key: string;
  group: "CITIES" | "LANDMARKS";
}

function poi(
  name: string,
  key: string,
  lon: number,
  lat: number,
  height: number,
  heading = 0,
  pitch = -35,
  group: "CITIES" | "LANDMARKS" = "LANDMARKS"
): POI {
  return {
    name,
    key,
    group,
    target: { longitude: lon, latitude: lat, height, heading, pitch },
  };
}

export const POI_LIST: POI[] = [
  // ── Cities ─────────────────────────────────────────────
  poi("New York",     "n", -73.9857, 40.7580,  5000, 30,  -30, "CITIES"),
  poi("Los Angeles",  "0", -118.2437, 34.0522, 5000, 15,  -30, "CITIES"),
  poi("Miami",        "-", -80.1918, 25.7617,  5000, 20,  -30, "CITIES"),
  poi("London",       "l",  -0.1276, 51.5074,  5000,  0,  -30, "CITIES"),
  poi("Tokyo",        "k", 139.6917, 35.6895,  5000, 15,  -30, "CITIES"),
  poi("Moscow",       "m",  37.6176, 55.7520,  5000,  0,  -30, "CITIES"),
  poi("Beijing",      "j", 116.3912, 39.9042,  5000,  0,  -30, "CITIES"),
  poi("Sydney",       "y", 151.2093,-33.8688,  5000, 20,  -30, "CITIES"),
  poi("Dubai",        "d",  55.2708, 25.2048,  3000, 30,  -25, "CITIES"),

  // ── Puerto Rico ────────────────────────────────────────
  // El Morro — camera north of the fort over the Atlantic, looking south at PR
  poi("El Morro Fort","s", -66.1244, 18.4755,   600, 180, -25, "CITIES"),
  // Old San Juan — low flyover of the colonial district
  poi("Old San Juan", "o", -66.1175, 18.4663,   800, 30,  -25, "CITIES"),
  // Playa Azul — hovering above the beach in Luquillo, looking at shore
  poi("Playa Azul",   "u", -65.7185, 18.3845,   700, 200, -28, "CITIES"),
  // Las Tetas de Cayey — twin mountain peaks
  poi("Cayey Peaks",  "a", -66.1280, 18.0850,  2500,  0,  -30, "CITIES"),
  // Rincon — camera over western ocean looking east at coast + beach
  poi("Rincon",       "i", -67.2680, 18.3408,  1500, 90,  -20, "CITIES"),
  // Fajardo — eastern coast
  poi("Fajardo",      "f", -65.6525, 18.3358,  2000, 10,  -30, "CITIES"),
  // Ponce — camera south over Caribbean looking north at shoreline + city
  poi("Ponce",        "p", -66.6141, 17.9980,  2500,  0,  -20, "CITIES"),

  // ── Landmarks ──────────────────────────────────────────
  poi("Pentagon",     "q", -77.0558, 38.8719,  1500, 30, -40, "LANDMARKS"),
  poi("Kremlin",      "w",  37.6176, 55.7520,  1200, 15, -35, "LANDMARKS"),
  poi("White House",  "e", -77.0365, 38.8977,   800,  0, -30, "LANDMARKS"),
  poi("Area 51",      "r",-115.8111, 37.2350, 15000,  0, -45, "LANDMARKS"),
  // Times Square — low angle looking SSE down Broadway at the billboards
  poi("Times Square", "t", -73.9850, 40.7593,   250, 168, -12, "LANDMARKS"),
  poi("Strait of Hormuz", "5", 56.2028, 26.4494, 5000, 30, -35, "LANDMARKS"),
];

export function getPOIByKey(key: string): POI | undefined {
  return POI_LIST.find((p) => p.key === key.toLowerCase());
}
