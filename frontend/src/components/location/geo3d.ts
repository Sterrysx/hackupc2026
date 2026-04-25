import * as THREE from "three";
import type { Feature, MultiPolygon } from "geojson";

/**
 * Geometry helpers for the 3D location-selector globe.
 *
 *   • latLonToVec3 — standard spherical → cartesian (Y up).
 *   • buildContinentLineGeometry — coastlines as line segments on the sphere,
 *     subdivided so straight GeoJSON edges follow the curvature, and SORTED
 *     BY MIDPOINT LONGITUDE so a setDrawRange-driven reveal paints L→R.
 *   • buildGraticuleGeometry — global lat/lon grid for engraving feel.
 *   • buildContinentHatchGeometry — scanline hatch (horizontal + vertical)
 *     CLIPPED to continent polygons via per-polygon parity. Gives every
 *     landmass an interlaced texture without a custom shader.
 *   • buildContinentFillGeometry — solid filled landmasses with per-vertex
 *     colours that paint a latitude-driven gradient. Triangulates each
 *     polygon (with holes) via THREE.ShapeUtils, subdivides the triangles
 *     so they follow the sphere's curvature, then projects every vertex to
 *     the surface. The result is a single non-indexed BufferGeometry the
 *     globe renders below the hatch + outline layers.
 */

const SUBDIVISIONS = 4;
const HATCH_SUBSAMPLE_DEG = 1;

export function latLonToVec3(lat: number, lon: number, radius: number): THREE.Vector3 {
  const phi = ((90 - lat) * Math.PI) / 180;
  const theta = ((lon + 180) * Math.PI) / 180;
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  );
}

export interface ContinentLineResult {
  geometry: THREE.BufferGeometry;
  segmentCount: number;
}

export function buildContinentLineGeometry(
  land: Feature<MultiPolygon>,
  radius: number,
): ContinentLineResult {
  type Seg = {
    ax: number; ay: number; az: number;
    bx: number; by: number; bz: number;
    midLon: number;
  };
  const segs: Seg[] = [];

  for (const polygon of land.geometry.coordinates) {
    for (const ring of polygon) {
      for (let i = 0; i < ring.length - 1; i++) {
        const [lon1, lat1] = ring[i];
        const [lon2, lat2] = ring[i + 1];
        for (let k = 0; k < SUBDIVISIONS; k++) {
          const t1 = k / SUBDIVISIONS;
          const t2 = (k + 1) / SUBDIVISIONS;
          const lonA = lon1 + (lon2 - lon1) * t1;
          const latA = lat1 + (lat2 - lat1) * t1;
          const lonB = lon1 + (lon2 - lon1) * t2;
          const latB = lat1 + (lat2 - lat1) * t2;
          const a = latLonToVec3(latA, lonA, radius);
          const b = latLonToVec3(latB, lonB, radius);
          segs.push({
            ax: a.x, ay: a.y, az: a.z,
            bx: b.x, by: b.y, bz: b.z,
            midLon: (lonA + lonB) / 2,
          });
        }
      }
    }
  }

  segs.sort((a, b) => a.midLon - b.midLon);

  const positions = new Float32Array(segs.length * 6);
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    const o = i * 6;
    positions[o] = s.ax; positions[o + 1] = s.ay; positions[o + 2] = s.az;
    positions[o + 3] = s.bx; positions[o + 4] = s.by; positions[o + 5] = s.bz;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  return { geometry, segmentCount: segs.length };
}

export function buildGraticuleGeometry(radius: number, stepDeg: number): THREE.BufferGeometry {
  const verts: number[] = [];
  const SAMPLES = 96;

  // Parallels (latitude rings) — skip the polar caps to avoid degenerate rings.
  for (let lat = -75; lat <= 75; lat += stepDeg) {
    for (let i = 0; i < SAMPLES; i++) {
      const lon1 = -180 + (i * 360) / SAMPLES;
      const lon2 = -180 + ((i + 1) * 360) / SAMPLES;
      const a = latLonToVec3(lat, lon1, radius);
      const b = latLonToVec3(lat, lon2, radius);
      verts.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }
  // Meridians (full half-circles from south pole to north pole).
  for (let lon = -180; lon < 180; lon += stepDeg) {
    for (let i = 0; i < SAMPLES; i++) {
      const lat1 = -90 + (i * 180) / SAMPLES;
      const lat2 = -90 + ((i + 1) * 180) / SAMPLES;
      const a = latLonToVec3(lat1, lon, radius);
      const b = latLonToVec3(lat2, lon, radius);
      verts.push(a.x, a.y, a.z, b.x, b.y, b.z);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(verts), 3));
  return geometry;
}

export function buildContinentHatchGeometry(
  land: Feature<MultiPolygon>,
  radius: number,
  latStepDeg: number,
  lonStepDeg: number,
): THREE.BufferGeometry {
  const verts: number[] = [];

  // ── Horizontal hatch — parallels clipped to land per polygon ─────────── //
  for (let lat = -78; lat <= 78; lat += latStepDeg) {
    for (const polygon of land.geometry.coordinates) {
      const crossings: number[] = [];
      for (const ring of polygon) {
        for (let i = 0; i < ring.length - 1; i++) {
          const [lon1, lat1] = ring[i];
          const [lon2, lat2] = ring[i + 1];
          if ((lat1 - lat) * (lat2 - lat) < 0) {
            const t = (lat - lat1) / (lat2 - lat1);
            crossings.push(lon1 + t * (lon2 - lon1));
          }
        }
      }
      crossings.sort((a, b) => a - b);
      for (let p = 0; p + 1 < crossings.length; p += 2) {
        const lonStart = crossings[p];
        const lonEnd = crossings[p + 1];
        if (lonEnd - lonStart < 0.5) continue;
        const steps = Math.max(2, Math.ceil((lonEnd - lonStart) / HATCH_SUBSAMPLE_DEG));
        for (let s = 0; s < steps; s++) {
          const t1 = s / steps;
          const t2 = (s + 1) / steps;
          const lonA = lonStart + (lonEnd - lonStart) * t1;
          const lonB = lonStart + (lonEnd - lonStart) * t2;
          const a = latLonToVec3(lat, lonA, radius);
          const b = latLonToVec3(lat, lonB, radius);
          verts.push(a.x, a.y, a.z, b.x, b.y, b.z);
        }
      }
    }
  }

  // ── Vertical hatch — meridians clipped to land per polygon ───────────── //
  for (let lon = -180; lon <= 180; lon += lonStepDeg) {
    for (const polygon of land.geometry.coordinates) {
      const crossings: number[] = [];
      for (const ring of polygon) {
        for (let i = 0; i < ring.length - 1; i++) {
          const [lon1, lat1] = ring[i];
          const [lon2, lat2] = ring[i + 1];
          if ((lon1 - lon) * (lon2 - lon) < 0) {
            const t = (lon - lon1) / (lon2 - lon1);
            crossings.push(lat1 + t * (lat2 - lat1));
          }
        }
      }
      crossings.sort((a, b) => a - b);
      for (let p = 0; p + 1 < crossings.length; p += 2) {
        const latStart = crossings[p];
        const latEnd = crossings[p + 1];
        if (latEnd - latStart < 0.5) continue;
        const steps = Math.max(2, Math.ceil((latEnd - latStart) / HATCH_SUBSAMPLE_DEG));
        for (let s = 0; s < steps; s++) {
          const t1 = s / steps;
          const t2 = (s + 1) / steps;
          const latA = latStart + (latEnd - latStart) * t1;
          const latB = latStart + (latEnd - latStart) * t2;
          const a = latLonToVec3(latA, lon, radius);
          const b = latLonToVec3(latB, lon, radius);
          verts.push(a.x, a.y, a.z, b.x, b.y, b.z);
        }
      }
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(verts), 3));
  return geometry;
}

// ── Continent fill ──────────────────────────────────────────────────────── //

/** Maximum edge length (in degrees of arc on the lon/lat plane) before we
 *  subdivide a triangle. Triangles with longer edges look visibly flat
 *  against the sphere; 4° matches the hatch density and reads as smooth. */
const FILL_MAX_EDGE_DEG = 4;

export interface ContinentFillOptions {
  /** RGB triple for the equatorial pole of the gradient. */
  equatorColor: [number, number, number];
  /** RGB triple for the high-latitude pole of the gradient. */
  poleColor: [number, number, number];
}

/**
 * Build a single filled, vertex-coloured BufferGeometry covering every land
 * polygon. Colour is interpolated from `equatorColor` at lat=0 to
 * `poleColor` at |lat|=90 with a smoothstep so the transition reads as a
 * gradient rather than a hard band.
 */
export function buildContinentFillGeometry(
  land: Feature<MultiPolygon>,
  radius: number,
  opts: ContinentFillOptions,
): THREE.BufferGeometry {
  const positions: number[] = [];
  const colors: number[] = [];

  for (const polygon of land.geometry.coordinates) {
    if (polygon.length === 0) continue;
    const outer = polygon[0].map(([lon, lat]) => new THREE.Vector2(lon, lat));
    const holes = polygon
      .slice(1)
      .map((ring) => ring.map(([lon, lat]) => new THREE.Vector2(lon, lat)));

    // Drop the duplicated closing vertex some GeoJSON rings carry — leaving
    // it in confuses the ear-clipper into producing slivers.
    if (outer.length > 1 && outer[0].equals(outer[outer.length - 1])) {
      outer.pop();
    }
    for (const hole of holes) {
      if (hole.length > 1 && hole[0].equals(hole[hole.length - 1])) {
        hole.pop();
      }
    }
    if (outer.length < 3) continue;

    const triangles = THREE.ShapeUtils.triangulateShape(outer, holes);
    if (triangles.length === 0) continue;

    // ShapeUtils returns triangle index triples into the merged
    // (outer + ...holes) array — re-merge so the index lookup is consistent.
    const merged: THREE.Vector2[] = outer.slice();
    for (const hole of holes) merged.push(...hole);

    for (const tri of triangles) {
      const [i, j, k] = tri;
      emitSubdividedTriangle(
        merged[i], merged[j], merged[k],
        radius, opts, positions, colors,
      );
    }
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
  geom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colors), 3));
  return geom;
}

/**
 * Recursively split a triangle in lon/lat space until every edge is shorter
 * than `FILL_MAX_EDGE_DEG`, then project each vertex to the sphere and emit
 * positions + per-vertex colours.
 */
function emitSubdividedTriangle(
  a: THREE.Vector2, b: THREE.Vector2, c: THREE.Vector2,
  radius: number,
  opts: ContinentFillOptions,
  positions: number[],
  colors: number[],
): void {
  const edgeAB = a.distanceTo(b);
  const edgeBC = b.distanceTo(c);
  const edgeCA = c.distanceTo(a);
  const maxEdge = Math.max(edgeAB, edgeBC, edgeCA);

  if (maxEdge <= FILL_MAX_EDGE_DEG) {
    pushVertex(a, radius, opts, positions, colors);
    pushVertex(b, radius, opts, positions, colors);
    pushVertex(c, radius, opts, positions, colors);
    return;
  }

  // Subdivide on the longest edge so the children stay roughly equilateral.
  if (edgeAB === maxEdge) {
    const m = midpoint(a, b);
    emitSubdividedTriangle(a, m, c, radius, opts, positions, colors);
    emitSubdividedTriangle(m, b, c, radius, opts, positions, colors);
  } else if (edgeBC === maxEdge) {
    const m = midpoint(b, c);
    emitSubdividedTriangle(a, b, m, radius, opts, positions, colors);
    emitSubdividedTriangle(a, m, c, radius, opts, positions, colors);
  } else {
    const m = midpoint(c, a);
    emitSubdividedTriangle(a, b, m, radius, opts, positions, colors);
    emitSubdividedTriangle(m, b, c, radius, opts, positions, colors);
  }
}

function midpoint(p: THREE.Vector2, q: THREE.Vector2): THREE.Vector2 {
  return new THREE.Vector2((p.x + q.x) / 2, (p.y + q.y) / 2);
}

function pushVertex(
  p: THREE.Vector2,
  radius: number,
  opts: ContinentFillOptions,
  positions: number[],
  colors: number[],
): void {
  // p.x is longitude, p.y is latitude.
  const v = latLonToVec3(p.y, p.x, radius);
  positions.push(v.x, v.y, v.z);
  // Latitude-driven gradient: equator → equatorColor, |lat|=90 → poleColor.
  // Smoothstep so the band reads as a gradient instead of a hard transition.
  const t = Math.min(1, Math.abs(p.y) / 90);
  const ts = t * t * (3 - 2 * t);
  const r = opts.equatorColor[0] + (opts.poleColor[0] - opts.equatorColor[0]) * ts;
  const g = opts.equatorColor[1] + (opts.poleColor[1] - opts.equatorColor[1]) * ts;
  const b = opts.equatorColor[2] + (opts.poleColor[2] - opts.equatorColor[2]) * ts;
  colors.push(r, g, b);
}
