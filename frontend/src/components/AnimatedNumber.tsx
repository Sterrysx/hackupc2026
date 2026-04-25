/**
 * AnimatedNumber — interpolates a numeric value with an ease-out curve and
 * writes the formatted result directly to the DOM via ref. No React
 * re-renders during the animation; framer-motion drives the tween in JS.
 *
 * Why imperative DOM updates?
 *   If we set the value via React children, every prop change would briefly
 *   render the *final* value before the animation kicked in (one-frame snap),
 *   and we'd re-render the whole component subtree on every animation frame.
 *   Writing textContent in a motion-value subscription gives us a smooth
 *   ticker with zero re-renders.
 */

import { useEffect, useLayoutEffect, useRef } from "react";
import { animate, useMotionValue } from "framer-motion";

interface AnimatedNumberProps {
  value: number;
  /** Custom formatter — default rounds to integer. */
  format?: (v: number) => string;
  /** Animation duration in seconds — keep short so consecutive ticks stay legible. */
  duration?: number;
  className?: string;
  style?: React.CSSProperties;
}

const DEFAULT_FORMAT = (v: number) => Math.round(v).toString();

export function AnimatedNumber({
  value,
  format = DEFAULT_FORMAT,
  duration = 0.5,
  className,
  style,
}: AnimatedNumberProps) {
  const motion = useMotionValue(value);
  const ref = useRef<HTMLSpanElement>(null);
  const formatRef = useRef(format);
  formatRef.current = format;

  // Initial sync — runs synchronously after mount, before paint.
  useLayoutEffect(() => {
    if (ref.current) ref.current.textContent = formatRef.current(motion.get());
  }, [motion]);

  // Subscribe to motion value changes; write to DOM on each tick.
  useEffect(() => {
    return motion.on("change", (v: number) => {
      if (ref.current) ref.current.textContent = formatRef.current(v);
    });
  }, [motion]);

  // Animate to new target whenever `value` changes.
  useEffect(() => {
    const controls = animate(motion, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [value, duration, motion]);

  return <span ref={ref} className={className} style={style} />;
}
