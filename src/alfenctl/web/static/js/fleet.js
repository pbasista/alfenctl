/* The Fleet: every charging station this server can see, one tile each.
 *
 * The page is about one station at a time, and until now the only way to
 * say which was a dialog behind a button in the header -- which is fine for
 * changing station and no good at all for the question people actually
 * arrive with, which is "what have I got".  Somebody with four chargers on
 * a site had nowhere to see four chargers.
 *
 * "Fleet" rather than "Network": a charging *network* is the operator's
 * back office, which is a different tab, and a tab named for it here would
 * send people to the wrong one twice.  It is the same view jkctl calls the
 * Bank, drawn out of the same tiles, and clicking one is how this page
 * changes what it is about.
 */

import { Badge, Empty } from '/core/js/ui.js';
import { html } from '/core/vendor/preact-htm.module.js';

/* Everything the server knows about, configured first: a station named in
 * the config file is one somebody chose, and one mDNS found is one that
 * happened to be plugged in.  A station in both lists is the configured
 * one, which carries the credentials.
 */
export function fleetOf(stations) {
  if (!stations) return [];
  const configured = stations.configured || [];
  const discovered = (stations.discovered || []).filter(
    (d) => !configured.some((c) => c.host === d.host || c.name === d.name)
  );
  return [...configured, ...discovered];
}

/* Whether this tile is the station the rest of the page is about.  The link
 * carries whatever the station was set by -- a name from the config file or
 * an address typed in by hand -- so both are worth comparing.
 *
 * Exported because clicking a tile opens that station's dashboard, and the
 * station this page is already on must not be set again on the way there:
 * one of these tiles can be the synthetic one for a station typed into the
 * picker, which has a name and no address, and setting it a second time is
 * a refusal ("no address for that station") in front of somebody who asked
 * for nothing but to see it. */
export function isCurrent(station, current) {
  if (!current) return false;
  return current === station.name || current === station.host;
}

function Tile({ station, current, onPick }) {
  const here = isCurrent(station, current);
  return html`<button
    class=${`tile${here ? ' selected' : ''}`}
    onClick=${() => onPick(station)}
  >
    <div class="tile-head">
      <span class="id">${station.name || station.host}</span>
      <span class="spacer"></span>
      ${here ? html`<${Badge} tone="good">this page<//>` : null}
    </div>
    <div class="stats">
      <div class="stat">
        <span class="k">address</span>
        <span class="v">${station.host || '—'}${station.port ? `:${station.port}` : ''}</span>
      </div>
      <div class="stat">
        <span class="k">known from</span>
        <span class="v">${station.source || 'config'}</span>
      </div>
    </div>
  </button>`;
}

export function Fleet({ stations, current, busy, onPick, onRescan, onAdd }) {
  const known = fleetOf(stations);
  /* The station this page is on always has a tile, whether or not mDNS
   * found it and whether or not it is in the config file -- an address
   * typed into the picker is neither, and a Fleet that says "0 stations"
   * while the header names one is a Fleet nobody believes twice. */
  const all =
    current && !known.some((station) => isCurrent(station, current))
      ? [{ name: current, host: '', source: 'this session' }, ...known]
      : known;
  return html`<div>
    <div class="toolbar spaced">
      <span class="muted">
        ${stations === null && all.length === 0
          ? 'Looking for chargers on this network...'
          : `${all.length} station${all.length === 1 ? '' : 's'} this server can see`}
      </span>
      <span class="spacer"></span>
      <button class="btn" disabled=${busy} onClick=${onAdd}>Add by address</button>
      <button class="btn" disabled=${busy} onClick=${onRescan}>Look again</button>
    </div>
    ${all.length === 0
      ? html`<${Empty}>
          None found by mDNS and none in your config file. A charger that is not
          announcing itself can still be reached by address.
        <//>`
      : html`<div class="tiles">
          ${all.map(
            (station) => html`<${Tile}
              key=${`${station.name}-${station.host}`}
              station=${station}
              current=${current}
              onPick=${onPick}
            />`
          )}
        </div>`}
  </div>`;
}
