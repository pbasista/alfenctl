/* What the charger has been drawing, for as long as this page has been
 * watching it.
 *
 * The station keeps no history a browser can ask for -- its own registers
 * say what is happening now and what has happened in total, and nothing in
 * between -- so this is the page's own memory: every live-refresh reading
 * of the active power, kept in the tab, thrown away when the station
 * changes.  It answers the one question a number on its own cannot: you
 * moved a slider, and did anything happen?
 *
 * Which is why the writes are marked on it.  The activity list already
 * knows when the connection was used to write something (see
 * `rememberActivity` in app.js), so each one is a tick under the line, and
 * the effect of a change sits next to the change.
 */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { acrossPlot, clockTime, Hovered, useHover } from './chart.js';
import { fmt } from './ui.js';

/* How much is kept: at the default three-second beat this is about half an
 * hour, which is the span over which a charging session's settings get
 * fiddled with.  Older samples fall off the front. */
const KEEP = 720;

/* The narrowest window the chart will draw.  Without it the first three
 * samples would be stretched across the whole width, and a line whose
 * shape changes because more of it arrived is a line that lies twice. */
const MIN_SPAN_S = 180;

/* Where the samples are kept between reloads.  Per station, and in the
 * session rather than in local storage: this is what *this* look at the
 * charger has seen, and it should not still be there next week. */
const KEY = 'alfenctl-power';

function stored(station) {
  try {
    const held = JSON.parse(sessionStorage.getItem(`${KEY}:${station}`) || '[]');
    return Array.isArray(held) ? held.slice(-KEEP) : [];
  } catch {
    /* No session storage, or something else wrote nonsense into it.  The
     * chart starts empty, which is what it does on a fresh tab anyway. */
    return [];
  }
}

function keep(station, samples) {
  try {
    sessionStorage.setItem(`${KEY}:${station}`, JSON.stringify(samples));
  } catch {
    /* Private windows, a full quota: the chart still works, it just
     * forgets across a reload. */
  }
}

/* The samples this page has taken, growing on every reading the charger
 * sends and starting over when the station changes. */
export function usePowerHistory(status, station) {
  const [samples, setSamples] = useState(() => stored(station || ''));
  const last = useRef(null);
  const where = useRef(station || '');

  useEffect(() => {
    if (where.current === (station || '')) return;
    where.current = station || '';
    last.current = null;
    setSamples(stored(station || ''));
  }, [station]);

  useEffect(() => {
    /* One sample per reading, not one per render: the page redraws on
     * every link beat, and most of those carry no new status at all. */
    if (!status || status === last.current) return;
    last.current = status;
    const watts = status.activePowerW;
    if (watts === null || watts === undefined) return;
    setSamples((held) => {
      const next = [...held, { t: Math.round(Date.now() / 1000), w: watts }].slice(-KEEP);
      keep(where.current, next);
      return next;
    });
  }, [status]);

  return samples;
}

/* Where a write happened, in the window the chart is showing.  Only
 * writes: a read is the page looking, and marking those would put a tick
 * every three seconds. */
function marks(activity, from, to) {
  return (activity || [])
    .filter((item) => item.ok && /^(Writing|Setting|Installing|Erasing)/.test(item.op || ''))
    .filter((item) => item.at >= from && item.at <= to)
    .map((item) => ({ at: item.at, op: item.op }));
}

const W = 600;
const H = 120;
const PAD = 6;

/* The sample nearest a moment, which is what the pointer is really asking
 * for.  A chart of one reading every three seconds has gaps in it -- a
 * paused refresh, a charger that took a while to answer -- and a cursor
 * that interpolated across one would be inventing a measurement.  This
 * names a reading that was actually taken. */
function nearest(samples, when) {
  let best = samples[0];
  for (const sample of samples) {
    if (Math.abs(sample.t - when) < Math.abs(best.t - when)) best = sample;
  }
  return best;
}

export function PowerChart({ samples, activity, live }) {
  /* Every hook first, and unconditionally: the empty chart below returns
   * before the drawing does, and a hook behind an early return belongs to
   * a different slot on the render that has samples. */
  const hover = useHover();
  if (!samples || samples.length < 2) {
    return html`<div class="chart empty-chart">
      ${live === false
        ? 'Live updates are off, so nothing is being recorded here.'
        : 'Watching -- the line fills in as the charger reports.'}
    </div>`;
  }

  const now = samples[samples.length - 1].t;
  const span = Math.max(MIN_SPAN_S, now - samples[0].t);
  const from = now - span;
  const peak = Math.max(...samples.map((s) => s.w), 0);
  /* A ceiling that does not twitch: rounding it up to a whole kW means the
   * line's height means something between one look and the next, instead
   * of rescaling every time the car takes another 40 W. */
  const ceiling = Math.max(1000, Math.ceil(peak / 1000) * 1000);

  const x = (t) => PAD + ((t - from) / span) * (W - 2 * PAD);
  const y = (w) => H - PAD - (w / ceiling) * (H - 2 * PAD);

  const shown = samples.filter((s) => s.t >= from);
  const line = shown.map((s) => `${x(s.t).toFixed(1)},${y(s.w).toFixed(1)}`).join(' ');
  const area = `${PAD},${H - PAD} ${line} ${x(now).toFixed(1)},${H - PAD}`;
  const ticks = marks(activity, from, now);

  /* What the pointer is over, if it is over anything: the reading nearest
   * the moment under it, placed by where that reading actually is rather
   * than by where the pointer is.  `acrossPlot` is what makes the moment
   * under it the right one -- the line starts a pad in from the box the
   * pointer is measured against. */
  const across = acrossPlot(hover.at, PAD, W);
  const under = across === null ? null : nearest(shown, from + across * span);

  /* The plot is its own box so that the pointer's fraction across it is a
   * fraction across the SVG, and so the cursor and the label -- which are
   * HTML, because nothing drawn inside a stretched SVG keeps its shape --
   * can be positioned in percentages of exactly the same rectangle.  The
   * scale under it is not part of that rectangle. */
  return html`<div class="chart">
    <div class="plot" ref=${hover.box} ...${hover.on}>
    <svg viewBox=${`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
         aria-label=${`charging power over the last ${Math.round(span / 60)} minutes, peaking at ${fmt(peak / 1000, 1)} kilowatts`}>
      <polygon class="area" points=${area} />
      <polyline class="line" points=${line} vector-effect="non-scaling-stroke" />
      ${ticks.map(
        (tick) => html`<line
          class="mark"
          key=${tick.at}
          x1=${x(tick.at)}
          x2=${x(tick.at)}
          y1=${PAD}
          y2=${H - PAD}
          vector-effect="non-scaling-stroke"
        ><title>${tick.op}</title></line>`
      )}
    </svg>
    ${under &&
    html`<${Hovered}
      x=${x(under.t) / W}
      y=${y(under.w) / H}
      heading=${clockTime(under.t)}
      lines=${[`${fmt(under.w / 1000, 2)} kW`]}
    />`}
    </div>
    <div class="ends">
      <span>${Math.round(span / 60)} min ago</span>
      ${ticks.length > 0 &&
      html`<span class="key"><i></i>${ticks.length} setting${ticks.length === 1 ? '' : 's'} written</span>`}
      <span>${fmt(ceiling / 1000, 0)} kW full scale</span>
    </div>
  </div>`;
}
