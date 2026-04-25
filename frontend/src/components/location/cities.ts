/**
 * Cities — single source of truth for the 10 candidate physical locations
 * for the HP Metal Jet S100 simulation.
 *
 *   • Coordinates and climate hardcoded per the design brief; values feed the
 *     5-year degradation simulation downstream.
 *   • Shared by LocationSelectorPage, WorldMap, and the Zustand store so the
 *     City type stays consistent end-to-end.
 */

export interface City {
  id: string;
  name: string;
  country: string;
  lat: number;
  lon: number;
  /** Annual mean temperature, °C. */
  avgTemp: number;
  /** Annual mean relative humidity, %. */
  avgHumidity: number;
  /** Elevation above sea level, m. */
  altitude: number;
  /** Mean atmospheric pressure, hPa. */
  pressure: number;
}

export const CITIES: City[] = [
  { id: "singapore",   name: "Singapore",   country: "Singapore",      lat: 1.29,  lon: 103.85, avgTemp: 27.0, avgHumidity: 84, altitude: 15,   pressure: 1011 },
  { id: "dubai",       name: "Dubai",       country: "UAE",            lat: 25.20, lon: 55.27,  avgTemp: 28.5, avgHumidity: 55, altitude: 5,    pressure: 1013 },
  { id: "mumbai",      name: "Mumbai",      country: "India",          lat: 19.08, lon: 72.88,  avgTemp: 27.2, avgHumidity: 72, altitude: 14,   pressure: 1012 },
  { id: "shanghai",    name: "Shanghai",    country: "China",          lat: 31.23, lon: 121.47, avgTemp: 16.7, avgHumidity: 72, altitude: 4,    pressure: 1013 },
  { id: "barcelona",   name: "Barcelona",   country: "Spain",          lat: 41.39, lon: 2.16,   avgTemp: 17.5, avgHumidity: 62, altitude: 12,   pressure: 1012 },
  { id: "london",      name: "London",      country: "United Kingdom", lat: 51.51, lon: -0.13,  avgTemp: 11.3, avgHumidity: 76, altitude: 11,   pressure: 1012 },
  { id: "moscow",      name: "Moscow",      country: "Russia",         lat: 55.75, lon: 37.62,  avgTemp: 5.8,  avgHumidity: 75, altitude: 156,  pressure: 997  },
  { id: "chicago",     name: "Chicago",     country: "USA",            lat: 41.88, lon: -87.63, avgTemp: 10.3, avgHumidity: 68, altitude: 181,  pressure: 995  },
  { id: "houston",     name: "Houston",     country: "USA",            lat: 29.76, lon: -95.37, avgTemp: 20.8, avgHumidity: 74, altitude: 15,   pressure: 1011 },
  { id: "mexico_city", name: "Mexico City", country: "Mexico",         lat: 19.43, lon: -99.13, avgTemp: 16.0, avgHumidity: 57, altitude: 2240, pressure: 780  },
];
