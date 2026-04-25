# Claude Code Prompt — Location Selector Landing Page

> Copy and paste everything below the horizontal rule directly into Claude Code.

---

You are building the location selection landing page for an industrial digital twin application simulating a HP Metal Jet S100 metal 3D printer. This is the first screen users see when they open the app.

## Tech stack

- Vite project. Read the existing codebase first and identify the framework in use (React, Vue, etc.)
- Match exactly the aesthetic, component patterns, folder structure, fonts, and CSS variables already used in the frontend
- You can use D3.js for the map — install it if it is not already present. If there is already a mapping library in the project, use that instead
- Do not introduce any new UI component library unless one is already being used in the project

## Page purpose

The user must select one of 10 world cities as the physical location of the printer. This choice determines environmental conditions (temperature, humidity, atmospheric pressure) that affect component degradation throughout the 5-year simulation. This page has no other function — it is purely a location picker that hands off a city object to the rest of the app.

## Visual style

- Minimalist, clean, premium — Apple product page aesthetic
- Black and white palette: white background, black UI elements, dark grey accents
- Leave CSS variables for primary accent color (currently black) so it can be easily rebranded later
- Thin lines, generous whitespace, sharp typography
- No gradients. No drop shadows except one subtle box-shadow on the modal card
- Font: use whatever is already defined in the project. If none is defined, use Inter (import from Google Fonts)
- All colors defined as CSS variables at the top of the stylesheet:
  ```
  --color-bg: #ffffff
  --color-fg: #000000
  --color-fg-muted: #6b6b6b
  --color-border: #000000
  --color-ocean: #f0f0f0
  --color-land: #ffffff
  --color-land-stroke: #000000
  ```

## Intro animation

Plays once on page load. A sessionStorage flag (`location_page_animated`) prevents it from replaying if the user navigates back.

1. Blank white canvas for 200ms
2. Coastline SVG paths stroke-draw progressively left to right using `stroke-dashoffset` animation — like a pen drawing the world. Duration: 2.5s, ease-in-out
3. As soon as the map finishes drawing, city markers appear one by one: fade in + scale from 0.5 to 1. Staggered 80ms apart
4. After all markers are visible, the page title and subtitle fade in upward (translateY 12px → 0, opacity 0 → 1, 400ms)
5. If the sessionStorage flag is already set, skip straight to the final state with no animation

## Map

- Full-screen SVG world map using Natural Earth or Robinson projection
- Ocean background: `--color-ocean` (#f0f0f0)
- Land fill: `--color-land` (#ffffff)
- Coastline stroke: `--color-land-stroke` (#000000), stroke-width 0.4px
- The map must be pannable (click and drag with smooth inertia) and zoomable (scroll wheel)
- Min zoom: full world visible on screen. Max zoom: 4×
- No country labels, no graticule, no legend — only the 10 city markers and their name labels

## City markers

Coordinates:

| City | Lat | Lon |
|---|---|---|
| Singapore | 1.29 | 103.85 |
| Dubai | 25.20 | 55.27 |
| Mumbai | 19.08 | 72.88 |
| Shanghai | 31.23 | 121.47 |
| Barcelona | 41.39 | 2.16 |
| London | 51.51 | -0.13 |
| Moscow | 55.75 | 37.62 |
| Chicago | 41.88 | -87.63 |
| Houston | 29.76 | -95.37 |
| Mexico City | 19.43 | -99.13 |

Marker states:

- **Default:** filled black circle, radius 4px. City name label in 10px small-caps, positioned to avoid coastline overlap (offset manually per city if needed)
- **Hover:** circle radius grows to 7px. Label becomes bold. Single pulse ring animation (one ring expands and fades out — does not loop)
- **Selected (after confirm):** circle becomes a 12px ring (stroke only, no fill) with a 3px dot in the center — crosshair/target style. Label stays bold
- Cursor: pointer on hover over any marker

## City info popup

Appears instantly when user clicks a marker. Centered on screen, not anchored to the marker position.

Structure:
```
┌─────────────────────────────────┐
│  CITY NAME                      │
│  Country · Region               │
├─────────────────────────────────┤
│  Avg Temperature    Humidity    │
│  17.5 °C            62 %        │
│                                 │
│  Altitude           Pressure    │
│  12 m               1012 hPa    │
├─────────────────────────────────┤
│  [Cancel]    [Confirm location →]│
└─────────────────────────────────┘
```

Styling:
- White background, 1px solid `--color-border`, border-radius 4px max
- Width: 360px fixed
- City name: 24px bold uppercase
- Country: 13px, `--color-fg-muted`
- Metric labels: 11px small-caps, `--color-fg-muted`
- Metric values: 22px, bold, `--color-fg`
- Cancel button: ghost (1px black border, white fill, black text)
- Confirm button: solid (black fill, white text)
- Both buttons same width, side by side, full width of footer
- Clicking outside the modal or pressing Escape triggers Cancel
- Open: instant (no animation). Close: 150ms opacity fade

## City data (hardcode as a const array)

```js
const CITIES = [
  { id: "singapore",   name: "Singapore",   country: "Singapore",     lat: 1.29,   lon: 103.85, avgTemp: 27.0, avgHumidity: 84, altitude: 15,   pressure: 1011 },
  { id: "dubai",       name: "Dubai",       country: "UAE",           lat: 25.20,  lon: 55.27,  avgTemp: 28.5, avgHumidity: 55, altitude: 5,    pressure: 1013 },
  { id: "mumbai",      name: "Mumbai",      country: "India",         lat: 19.08,  lon: 72.88,  avgTemp: 27.2, avgHumidity: 72, altitude: 14,   pressure: 1012 },
  { id: "shanghai",    name: "Shanghai",    country: "China",         lat: 31.23,  lon: 121.47, avgTemp: 16.7, avgHumidity: 72, altitude: 4,    pressure: 1013 },
  { id: "barcelona",   name: "Barcelona",   country: "Spain",         lat: 41.39,  lon: 2.16,   avgTemp: 17.5, avgHumidity: 62, altitude: 12,   pressure: 1012 },
  { id: "london",      name: "London",      country: "United Kingdom", lat: 51.51,  lon: -0.13,  avgTemp: 11.3, avgHumidity: 76, altitude: 11,   pressure: 1012 },
  { id: "moscow",      name: "Moscow",      country: "Russia",        lat: 55.75,  lon: 37.62,  avgTemp: 5.8,  avgHumidity: 75, altitude: 156,  pressure: 997  },
  { id: "chicago",     name: "Chicago",     country: "USA",           lat: 41.88,  lon: -87.63, avgTemp: 10.3, avgHumidity: 68, altitude: 181,  pressure: 995  },
  { id: "houston",     name: "Houston",     country: "USA",           lat: 29.76,  lon: -95.37, avgTemp: 20.8, avgHumidity: 74, altitude: 15,   pressure: 1011 },
  { id: "mexico_city", name: "Mexico City", country: "Mexico",        lat: 19.43,  lon: -99.13, avgTemp: 16.0, avgHumidity: 57, altitude: 2240, pressure: 780  },
]
```

Place this array at the very top of the component file. It is the single source of truth for all city data.

## Page chrome (UI outside the map)

- **Top-left corner:** app identifier — `HP METAL JET S100 · DIGITAL TWIN` in 11px small-caps, `--color-fg-muted`, with a thin 1px left border accent (8px tall, `--color-fg`) as a visual prefix. Fixed position, does not move with map pan/zoom
- **Top-right corner:** instruction — `Select a location to begin` in 12px, `--color-fg-muted`. Fades out after a city is confirmed
- **Bottom bar:** fixed to bottom of viewport, full width, 1px top border, white background. Hidden by default. Slides up from below (translateY 100% → 0, 300ms ease-out) after the user confirms a city for the first time. Contains:
  - Left: `SELECTED LOCATION` label (10px small-caps, muted) + confirmed city name (16px bold) below it
  - Right: `Launch simulation →` button (solid black)
  - The bottom bar stays visible and updates if the user selects a different city afterward

## Behavior flow

```
Page loads
  → Intro animation plays (or skips if already seen)
  → Map is interactive

User clicks city marker
  → Popup opens with that city's data
  → User clicks Cancel or presses Escape
      → Popup closes, nothing changes
  → User clicks Confirm
      → Popup closes
      → Marker switches to Selected state
      → Bottom bar slides up showing selected city
      → onCitySelected(cityObject) callback is called

User clicks a different marker while bottom bar is visible
  → New popup opens
  → If confirmed: previous marker reverts to Default, new marker becomes Selected,
    bottom bar updates, onCitySelected fires again with new city

User clicks Launch simulation →
  → Calls onLaunchSimulation(cityObject)
  → Routing to main app is handled externally by the team
```

## Callbacks / props

Export the component with these props (adapt to framework conventions):

```
onCitySelected(city)      // fires every time a city is confirmed via popup
onLaunchSimulation(city)  // fires when Launch simulation button is clicked
```

For now, both can default to `console.log`. The team will wire routing externally.

## Code quality requirements

- Single file component if the framework supports it (Vue SFC or React file with co-located styles)
- All city data in the `CITIES` const at the top — never scattered elsewhere
- All colors via CSS variables — never hardcoded hex values inside component logic
- All magic numbers (marker radius, animation durations, zoom limits) as named constants at the top of the file
- Comments:
  - File header block explaining the component's role, props, and how city data flows to the rest of the app
  - One comment per major section (animation, map setup, marker logic, popup, bottom bar)
- Desktop only for now: minimum supported width 1280px. No responsive breakpoints needed
- Do not add any analytics, tracking, or external API calls
- The component must work offline — all map data bundled locally (use topojson world atlas or equivalent)
