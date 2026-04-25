import { useMemo } from "react";

interface SparklineProps {
  values: number[];
  predictedValues?: number[];
  width?: number;
  height?: number;
  color?: string;
  predictedColor?: string;
  fill?: boolean;
}

/**
 * Hand-rolled sparkline (pure SVG) — Recharts is overkill for tiny tile charts.
 * Renders the recent history of healthIndex with an optional dashed projection.
 */
export function Sparkline({
  values,
  predictedValues,
  width = 220,
  height = 36,
  color = "oklch(0.85 0.13 215)",
  predictedColor = "oklch(0.85 0.13 215 / 0.55)",
  fill = true,
}: SparklineProps) {
  const path = useMemo(() => buildPath(values, width, height), [values, width, height]);
  const predPath = useMemo(
    () => (predictedValues ? buildPath(predictedValues, width, height) : null),
    [predictedValues, width, height],
  );
  const areaPath = useMemo(() => (fill ? buildArea(values, width, height) : null), [values, width, height, fill]);

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block">
      {areaPath && (
        <>
          <defs>
            <linearGradient id="sparkfill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.32" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill="url(#sparkfill)" />
        </>
      )}
      {predPath && (
        <path
          d={predPath}
          fill="none"
          stroke={predictedColor}
          strokeWidth={1.5}
          strokeDasharray="3 3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      <path d={path} fill="none" stroke={color} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function buildPath(values: number[], w: number, h: number): string {
  if (values.length === 0) return "";
  const min = 0;
  const max = 1;
  const step = w / Math.max(1, values.length - 1);
  return values
    .map((v, i) => {
      const x = i * step;
      const y = h - ((v - min) / (max - min)) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function buildArea(values: number[], w: number, h: number): string {
  const stroke = buildPath(values, w, h);
  if (!stroke) return "";
  return `${stroke} L${w} ${h} L0 ${h} Z`;
}
