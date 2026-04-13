/**
 * Artemis 2 trajectory data from JPL Horizons API.
 * Horizons ID: -1024 (Integrity Orion EM-2)
 * Moon ID: 301
 *
 * Returns J2000 ecliptic XYZ vectors (km, Earth-centered).
 * We convert ecliptic → equatorial → geographic for globe rendering.
 *
 * Launch: 2026-Apr-01 22:24 UTC from LC-39B, Kennedy Space Center
 * Trajectory data available from T+3h24m18s (post-ICPS separation)
 */

export interface TrajectoryPoint {
  epoch: Date;
  lat: number;   // geographic latitude (degrees)
  lon: number;   // geographic longitude (degrees)
  alt: number;   // altitude above Earth surface (meters)
  range: number; // distance from Earth center (km)
  vx: number;    // velocity X (km/s)
  vy: number;    // velocity Y (km/s)
  vz: number;    // velocity Z (km/s)
  speed: number; // total speed (km/s)
}

export interface ArtemisData {
  spacecraft: TrajectoryPoint[];
  moon: TrajectoryPoint[];
  missionPhase: string;
}

const OBLIQUITY_RAD = 23.4393 * (Math.PI / 180); // J2000 obliquity of ecliptic
const COS_OBL = Math.cos(OBLIQUITY_RAD);
const SIN_OBL = Math.sin(OBLIQUITY_RAD);
const EARTH_RADIUS_KM = 6371.0;

// Launch: April 1, 2026 at 22:24 UTC from Kennedy Space Center
export const LAUNCH_TIME = "2026-04-01T22:24:00Z";
// Trajectory data starts ~T+3h24m after launch (post-ICPS separation).
// NASA updates the nav solution frequently, shifting the exact start time.
// We try multiple start times to stay resilient.
const SC_START_CANDIDATES = [
  "2026-04-02T01:49",  // earliest possible (original nav solution)
  "2026-04-02T02:00",  // safe fallback after nav update
  "2026-04-02T02:30",  // wider margin
  "2026-04-02T03:00",  // even wider
];
export const TRAJECTORY_END = "2026-04-10T23:50";

// Kennedy Space Center pad LC-39B
export const KSC_LAT = 28.6083;
export const KSC_LON = -80.6041;

// Mission timeline (hours after launch)
export const MISSION_EVENTS = {
  launch: 0,
  solarArrayDeploy: 0.333,    // T+0:20
  perigeeRaise: 0.817,        // T+0:49
  apogeeRaise: 1.799,         // T+1:47:57
  icpsSeparation: 3.405,      // T+3:24:18 — trajectory data starts here
  orionSepBurn: 4.833,        // T+4:50
  // Lunar flyby is ~day 4
  lunarFlyby: 96,
  lunarFlybyEnd: 100,
  reentry: 216,               // ~day 9
  splashdown: 240,            // ~day 10
};

function eclipticToEquatorial(x: number, y: number, z: number): [number, number, number] {
  const xEq = x;
  const yEq = y * COS_OBL - z * SIN_OBL;
  const zEq = y * SIN_OBL + z * COS_OBL;
  return [xEq, yEq, zEq];
}

function gmst(date: Date): number {
  const jd = date.getTime() / 86400000 + 2440587.5;
  const t = (jd - 2451545.0) / 36525.0;
  let gmstDeg = 280.46061837 + 360.98564736629 * (jd - 2451545.0) +
    0.000387933 * t * t - t * t * t / 38710000.0;
  gmstDeg = ((gmstDeg % 360) + 360) % 360;
  return gmstDeg * (Math.PI / 180);
}

function cartesianToGeographic(
  xKm: number, yKm: number, zKm: number, date: Date
): { lat: number; lon: number; alt: number; range: number } {
  const [xEq, yEq, zEq] = eclipticToEquatorial(xKm, yKm, zKm);

  const range = Math.sqrt(xEq * xEq + yEq * yEq + zEq * zEq);
  const lat = Math.asin(zEq / range) * (180 / Math.PI);

  const theta = gmst(date);
  let lon = Math.atan2(yEq, xEq) - theta;
  lon = ((lon * (180 / Math.PI)) % 360 + 540) % 360 - 180;

  const alt = (range - EARTH_RADIUS_KM) * 1000; // meters

  return { lat, lon, alt, range };
}

function parseHorizonsVectors(resultText: string): TrajectoryPoint[] {
  const points: TrajectoryPoint[] = [];

  const soeIdx = resultText.indexOf("$$SOE");
  const eoeIdx = resultText.indexOf("$$EOE");
  if (soeIdx < 0 || eoeIdx < 0) return points;

  const dataBlock = resultText.substring(soeIdx + 5, eoeIdx).trim();
  const lines = dataBlock.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);

  // Horizons VECTORS format (each timestep is 3 lines):
  // Line 1: JDTDB = A.D. YYYY-Mon-DD HH:MM:SS.SSSS TDB
  // Line 2: X = ... Y = ... Z = ...
  // Line 3: VX= ... VY= ... VZ= ...
  let currentEpoch: Date | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Parse epoch from the date line: "2461132.575694445 = A.D. 2026-Apr-02 01:49:00.0000 TDB"
    const dateMatch = line.match(/A\.D\.\s+(\d{4})-(\w{3})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
    if (dateMatch) {
      const months: Record<string, number> = {
        Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
        Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11
      };
      currentEpoch = new Date(Date.UTC(
        parseInt(dateMatch[1]),
        months[dateMatch[2]] ?? 0,
        parseInt(dateMatch[3]),
        parseInt(dateMatch[4]),
        parseInt(dateMatch[5]),
        parseInt(dateMatch[6])
      ));
      continue;
    }

    // Position line
    if ((line.startsWith("X =") || line.startsWith(" X =")) && currentEpoch) {
      const posMatch = line.match(
        /X\s*=\s*([+-]?\d+\.\d+E[+-]?\d+)\s+Y\s*=\s*([+-]?\d+\.\d+E[+-]?\d+)\s+Z\s*=\s*([+-]?\d+\.\d+E[+-]?\d+)/
      );
      if (!posMatch) continue;

      const x = parseFloat(posMatch[1]);
      const y = parseFloat(posMatch[2]);
      const z = parseFloat(posMatch[3]);

      // Next line has velocity
      let vx = 0, vy = 0, vz = 0;
      if (i + 1 < lines.length) {
        const velLine = lines[i + 1];
        const velMatch = velLine.match(
          /VX\s*=\s*([+-]?\d+\.\d+E[+-]?\d+)\s+VY\s*=\s*([+-]?\d+\.\d+E[+-]?\d+)\s+VZ\s*=\s*([+-]?\d+\.\d+E[+-]?\d+)/
        );
        if (velMatch) {
          vx = parseFloat(velMatch[1]);
          vy = parseFloat(velMatch[2]);
          vz = parseFloat(velMatch[3]);
        }
      }

      const geo = cartesianToGeographic(x, y, z, currentEpoch);
      const speed = Math.sqrt(vx * vx + vy * vy + vz * vz);

      points.push({
        epoch: currentEpoch,
        lat: geo.lat,
        lon: geo.lon,
        alt: geo.alt,
        range: geo.range,
        vx, vy, vz,
        speed,
      });

      currentEpoch = null;
    }
  }

  return points;
}

async function fetchHorizonsTrajectory(
  command: string,
  startTime: string,
  stopTime: string,
  stepSize: string
): Promise<string> {
  const params = new URLSearchParams({
    format: "json",
    COMMAND: `'${command}'`,
    MAKE_EPHEM: "YES",
    EPHEM_TYPE: "VECTORS",
    CENTER: "'500@399'",
    START_TIME: `'${startTime}'`,
    STOP_TIME: `'${stopTime}'`,
    STEP_SIZE: `'${stepSize}'`,
    VEC_TABLE: "'2'",
    REF_PLANE: "'ECLIPTIC'",
    REF_SYSTEM: "'J2000'",
    OUT_UNITS: "'KM-S'",
    CSV_FORMAT: "'NO'",
  });

  const response = await fetch("/api/horizons?" + params.toString());
  if (!response.ok) throw new Error("Horizons API error: " + response.status);

  const data = await response.json();
  return data.result || "";
}

export function getMissionPhase(now: Date): string {
  const launch = new Date(LAUNCH_TIME);
  const hoursElapsed = (now.getTime() - launch.getTime()) / 3600000;

  if (hoursElapsed < 0) return "PRE-LAUNCH";
  if (hoursElapsed < MISSION_EVENTS.solarArrayDeploy) return "LIFTOFF";
  if (hoursElapsed < MISSION_EVENTS.perigeeRaise) return "EARTH ORBIT";
  if (hoursElapsed < MISSION_EVENTS.apogeeRaise) return "PERIGEE RAISE";
  if (hoursElapsed < MISSION_EVENTS.icpsSeparation) return "APOGEE RAISE";
  if (hoursElapsed < MISSION_EVENTS.orionSepBurn) return "ICPS SEPARATION";
  if (hoursElapsed < MISSION_EVENTS.lunarFlyby) return "TRANS-LUNAR COAST";
  if (hoursElapsed < MISSION_EVENTS.lunarFlybyEnd) return "LUNAR FLYBY";
  if (hoursElapsed < MISSION_EVENTS.reentry) return "TRANS-EARTH COAST";
  if (hoursElapsed < MISSION_EVENTS.splashdown) return "RE-ENTRY";
  return "POST-MISSION";
}

export function getHoursAfterLaunch(now: Date): number {
  return (now.getTime() - new Date(LAUNCH_TIME).getTime()) / 3600000;
}

export async function fetchArtemisTrajectory(): Promise<ArtemisData> {
  const now = new Date();
  const stepMinutes = 10;

  // Moon trajectory — always uses the first candidate (Moon data available for full range)
  const moonStart = SC_START_CANDIDATES[0];

  // Spacecraft trajectory — try each start time until one returns data.
  // NASA frequently updates the nav solution, shifting the earliest available epoch.
  let spacecraft: TrajectoryPoint[] = [];
  for (const startCandidate of SC_START_CANDIDATES) {
    const scResult = await fetchHorizonsTrajectory(
      "-1024", startCandidate, TRAJECTORY_END, `${stepMinutes}m`
    );
    spacecraft = parseHorizonsVectors(scResult);
    if (spacecraft.length > 0) {
      console.log(`Horizons SC: start=${startCandidate} → ${spacecraft.length} points`);
      break;
    }
    console.log(`Horizons SC: start=${startCandidate} → no data, trying next`);
  }

  // Moon in parallel is fine — its ephemeris covers a wide range
  const moonResult = await fetchHorizonsTrajectory(
    "301", moonStart, TRAJECTORY_END, `${stepMinutes}m`
  );
  const moon = parseHorizonsVectors(moonResult);

  console.log(
    `Horizons: ${spacecraft.length} SC points, ${moon.length} Moon points`
  );

  if (spacecraft.length > 0) {
    const first = spacecraft[0];
    console.log(
      `  First SC point: ${first.epoch.toISOString()} alt=${(first.alt / 1000).toFixed(0)} km, range=${first.range.toFixed(0)} km`
    );
  }

  return {
    spacecraft,
    moon,
    missionPhase: getMissionPhase(now),
  };
}

/** Interpolate between two trajectory points for smooth position */
export function interpolatePosition(points: TrajectoryPoint[], time: Date): TrajectoryPoint | null {
  if (points.length === 0) return null;

  const t = time.getTime();

  // Before first point — return first
  if (t <= points[0].epoch.getTime()) return points[0];
  // After last point — return last
  if (t >= points[points.length - 1].epoch.getTime()) return points[points.length - 1];

  // Binary search for bracketing interval
  let lo = 0, hi = points.length - 1;
  while (lo < hi - 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid].epoch.getTime() <= t) lo = mid;
    else hi = mid;
  }

  const prev = points[lo];
  const next = points[hi];
  const dt = next.epoch.getTime() - prev.epoch.getTime();
  if (dt === 0) return prev;

  const frac = (t - prev.epoch.getTime()) / dt;

  return {
    epoch: time,
    lat: prev.lat + (next.lat - prev.lat) * frac,
    lon: prev.lon + (next.lon - prev.lon) * frac,
    alt: prev.alt + (next.alt - prev.alt) * frac,
    range: prev.range + (next.range - prev.range) * frac,
    vx: prev.vx + (next.vx - prev.vx) * frac,
    vy: prev.vy + (next.vy - prev.vy) * frac,
    vz: prev.vz + (next.vz - prev.vz) * frac,
    speed: prev.speed + (next.speed - prev.speed) * frac,
  };
}
