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
