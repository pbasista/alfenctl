/* What the two plots on this page have in common: where the pointer is
 * over one, and the reading that follows it.
 *
 * Both charts draw an SVG stretched to the card's width
 * (`preserveAspectRatio: none`), which is what lets them be laid out in
 * CSS and keep their stroke weights -- and which also means nothing drawn
 * inside them keeps its shape.  A circle marking the hovered sample would
 * come out an ellipse, and a differently-shaped ellipse in every card.  So
 * everything that has to stay round or stay thin is HTML positioned over
 * the plot in percentages, and the SVG holds only what is allowed to
 * stretch: the line and the area under it.
 */

import { html, useRef, useState } from '../vendor/preact-htm.module.js';

/* How far from either edge the floating label is allowed to be centred.
 * Past this it stops following the pointer and leans in, so a reading
 * taken at the very start or end of a plot is still inside the card. */
const TIP_EDGE = 0.14;

/* Where the pointer is across a plot, as a fraction of its width.
 *
 * `null` when it is not over one at all, which is most of the time and is
 * what tells every caller to draw none of this.  Touch counts as a
 * pointer: a finger dragged along the line reads it the same way, which
 * on a phone is the only way to read it at all.
 */
export function useHover() {
  const [at, setAt] = useState(null);
  const box = useRef(null);

  const track = (event) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;
    const point = event.touches?.[0] || event;
    const x = point.clientX - rect.left;
    setAt(Math.min(1, Math.max(0, x / rect.width)));
  };

  return {
    at,
    box,
    /* Spread onto whatever element owns the plot's width. */
    on: {
      onMouseMove: track,
      onMouseLeave: () => setAt(null),
      onTouchStart: track,
      onTouchMove: track,
      onTouchEnd: () => setAt(null),
      onTouchCancel: () => setAt(null),
    },
  };
}

/* Where the pointer is across the *drawing*, rather than across the box
 * that holds it.
 *
 * Both charts inset what they draw by a few units at each end, and both
 * then asked `useHover` -- which measures the whole box -- which sample the
 * pointer was over.  So the pointer's 0 was the box's left edge while the
 * first sample sat a pad in from it, and the two disagreed by a pad's
 * worth all the way across: at the left of the chart the marker was to the
 * right of the cursor, at the right of it the marker was to the left, and
 * in the middle they met.  This is the same fraction measured against the
 * region the samples are actually in.
 *
 * Clamped, because the pad itself is outside that region and a pointer in
 * it is still pointing at the nearest end.
 */
export function acrossPlot(at, pad, width) {
  if (at === null || at === undefined) return null;
  const inner = width - 2 * pad;
  if (inner <= 0) return null;
  return Math.min(1, Math.max(0, (at * width - pad) / inner));
}

/* The rule under the pointer, and the reading it is pointing at.
 *
 * `at` is where the pointer is; `x` is where the *sample* is, which is not
 * the same thing -- the rule snaps to the reading it is naming, or the
 * chart would claim a value at a moment nothing was measured.  `y`, when a
 * caller has one, puts a dot on the line itself.
 *
 * `rule` is for a chart that already shows what the pointer is on.  A line
 * has nothing to mark the moment with, so it gets the vertical rule; a bar
 * chart lights up the bar itself, and a rule down the middle of a lit bar
 * is a second answer to a question already answered -- one that, on a wide
 * bar, sits half a bar away from the cursor and reads as a mistake.
 */
export function Hovered({ x, y, heading, lines, rule = true }) {
  const lean = Math.min(1 - TIP_EDGE, Math.max(TIP_EDGE, x));
  return html`<div class="hover" aria-hidden="true">
    ${rule && html`<span class="rule" style=${`left:${(x * 100).toFixed(2)}%`}></span>`}
    ${y !== null &&
    y !== undefined &&
    html`<span
      class="spot"
      style=${`left:${(x * 100).toFixed(2)}%;top:${(y * 100).toFixed(2)}%`}
    ></span>`}
    <span class="tip" style=${`left:${(lean * 100).toFixed(2)}%`}>
      <span class="when">${heading}</span>
      ${lines.map((line) => html`<span class="what" key=${line}>${line}</span>`)}
    </span>
  </div>`;
}

/* A clock time, in the reader's own zone: a chart of the last half hour is
 * read against the wall, not against an ISO stamp. */
export function clockTime(seconds) {
  return new Date(seconds * 1000).toLocaleTimeString();
}
