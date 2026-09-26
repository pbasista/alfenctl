/* What the charger has been drawing -- and how warm it has been getting --
 * for as long as this page has been watching it.
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
 *
 * The drawing itself is `Series` in /core/js/chart.js, which is where it
 * went when the same chart in the other program turned out to have been
 * drawing in colours that no longer existed.  What is left here is what is
 * genuinely this program's: where the samples come from, and that they are
 * watts stored and kilowatts read.
 *
 * The temperature rides on the same picture rather than taking a card of
 * its own.  On its own it is a flat line that moves a degree an hour, which
 * is a whole card saying nothing; beside the power it answers the question
 * it is actually there for, which is whether an hour at eleven kilowatts is
 * costing the station anything.  Its own scale and its own colour, named by
 * the key under the plot -- see `also` in the shared chart.
 */

import { Series } from '/core/js/chart.js';
import { html, useEffect, useRef, useState } from '/core/vendor/preact-htm.module.js';

/* How much is kept: at the default three-second beat this is about half an
 * hour, which is the span over which a charging session's settings get
 * fiddled with.  Older samples fall off the front. */
const KEEP = 720;

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
    /* The temperature rides along with the power rather than being kept
     * separately: they are read in the same status document, on the same
     * beat, and two arrays that were meant to be sampled together drift
     * apart the first time one of the two registers goes quiet. */
    const celsius = status.temperatureC;
    setSamples((held) => {
      const taken = { t: Math.round(Date.now() / 1000), w: watts };
      if (typeof celsius === 'number') taken.c = celsius;
      const next = [...held, taken].slice(-KEEP);
      keep(where.current, next);
      return next;
    });
  }, [status]);

  return samples;
}

/* Where a write happened, in the window the chart is showing.  Only
 * writes: a read is the page looking, and marking those would put a tick
 * every three seconds. */
function marks(activity) {
  return (activity || [])
    .filter((item) => item.ok && /^(Writing|Setting|Installing|Erasing)/.test(item.op || ''))
    .map((item) => ({ at: item.at, what: item.op }));
}

export function PowerChart({ samples, activity, live }) {
  return html`<${Series}
    samples=${(samples || []).map((s) => ({ t: s.t, v: s.w / 1000 }))}
    marks=${marks(activity)}
    unit="kW"
    digits=${2}
    step=${1}
    floor=${1}
    label="power"
    also=${{
      samples: (samples || [])
        .filter((s) => typeof s.c === 'number')
        .map((s) => ({ t: s.t, v: s.c })),
      unit: '°C',
      digits: 1,
      step: 2,
      label: 'temperature',
    }}
    what="charging power"
    empty=${live === false
      ? 'Live updates are off, so nothing is being recorded here.'
      : 'Watching — the line fills in as the charger reports.'}
  />`;
}
