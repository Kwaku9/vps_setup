---
name: add-poi
description: Add a point of interest to the WorldView dashboard globe. Geocodes the location, queries OSM for building data, computes camera parameters, and appends to poi.ts.
argument-hint: "Place Name" [lat lon | near City]
allowed-tools: Read, Edit, Bash, WebFetch, AskUserQuestion, Glob, Grep
---

# /add-poi — Interactive POI Creator

Add a point of interest to the WorldView geospatial dashboard globe.

**Target file**: `/workspace/vscode-projects/geospatial-dashboard/src/globe/poi.ts`

## Usage

```
/add-poi "Place Name"
/add-poi "Place Name" lat lon
/add-poi "Place Name" near Paris
```

## Instructions

You are adding a new POI entry to `/workspace/vscode-projects/geospatial-dashboard/src/globe/poi.ts`. Follow these steps precisely.

### Step 1: Parse Arguments

Extract from the skill argument:
- **Name**: the quoted place name (required)
- **Coordinates**: if `lat lon` numbers are provided, use them directly. If `near <city>` is given, geocode the city first then geocode the place name near that location. If neither, geocode the place name.

### Step 2: Geocode (if coordinates not provided)

Query Nominatim for coordinates:

```bash
curl -s "https://nominatim.openstreetmap.org/search?q=PLACE_NAME&format=json&limit=1" -H "User-Agent: WorldView-POI-Skill"
```

Extract `lat` and `lon` from the first result. If no results, ask the user for coordinates.

### Step 3: Ask for Group

Ask the user which group this POI belongs to:
- **CITIES** — city-level overview (default pitch -35, default height 5000)
- **LANDMARKS** — specific building or feature (default pitch -40, default height 2000)

### Step 4: Query Overpass for Building Data

Search for building geometry near the geocoded point:

```bash
curl -s "https://overpass-api.de/api/interpreter" --data-urlencode "data=[out:json][timeout:10];(way[\"name\"~\"PLACE_NAME\"][\"building\"](around:500,LAT,LON);relation[\"name\"~\"PLACE_NAME\"][\"building\"](around:500,LAT,LON););out body;" -H "User-Agent: WorldView-POI-Skill"
```

If results are found:
- Look for `height` or `building:height` tag → parse as number (meters)
- Use building centroid if available to refine coordinates

If no building data is found, that's fine — proceed with geocoded coordinates and defaults.

### Step 5: Compute Camera Parameters

- **height**: If building height found: `max(buildingHeight * 3, 500)`. Otherwise: 2000 for LANDMARKS, 5000 for CITIES
- **heading**: 30 (slight angle for visual interest)
- **pitch**: -35 for CITIES, -40 for LANDMARKS
- **longitude**: from geocode/building centroid (this goes BEFORE latitude in the poi() call)
- **latitude**: from geocode/building centroid

### Step 6: Find Next Free Keyboard Key

Read `/workspace/vscode-projects/geospatial-dashboard/src/globe/poi.ts` and collect all `.key` values currently in use. Also treat these as reserved and unavailable:
- `1`, `2`, `3`, `4` (vision modes)
- `b` (bloom toggle)
- `c` (CCTV layer)
- `v` (traffic layer)
- `g` (WiGLE layer)
- `h` (help overlay)
- `x` (reset view)
- `z` (zoom)

From the remaining lowercase letters `a-z`, pick the first unused one alphabetically.

### Step 7: Write to poi.ts

Read `/workspace/vscode-projects/geospatial-dashboard/src/globe/poi.ts`. Find the correct insertion point:
- For **CITIES**: insert a new line after the last `poi(...)` line in the `// Cities` section (before the blank line separating cities from landmarks)
- For **LANDMARKS**: insert a new line after the last `poi(...)` line in the `// Landmarks` section (before the `];` closing bracket)

Append a line matching the existing format exactly. Use appropriate spacing/alignment:

```typescript
  poi("Place Name", "KEY", LON, LAT, HEIGHT, HEADING, PITCH, "GROUP"),
```

Important formatting rules:
- 2-space indent
- Longitude before latitude (the poi() function takes lon, lat order)
- Numbers with no unnecessary decimals (use up to 4 decimal places for coordinates)
- The group string must be `"CITIES"` or `"LANDMARKS"`

### Step 8: Confirm

Report to the user:
- Name and assigned keyboard key
- Coordinates (lat, lon)
- Camera: height, heading, pitch
- Group
- Building height if found from Overpass
- Note that Vite HMR will auto-reload — press the assigned key to fly there
