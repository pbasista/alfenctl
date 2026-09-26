/* Which charger this page is about: everything mDNS answered plus
 * everything the config file names, and an address typed in by hand for the
 * ones neither knows.
 *
 * The other dialog about who is on the other end -- who else has this page
 * open -- was here too, and is `Watchers` in /core/js/shell.js now: the
 * server that answers it is the shared one, and the other program had the
 * endpoint and nothing that asked it.
 */

import { Picker } from '/core/js/ui.js';
import { html, useEffect, useState } from '/core/vendor/preact-htm.module.js';

import * as api from './api.js';
import { fleetOf } from './fleet.js';

/* Which charger this page is about.
 *
 * The list is `Picker` from the shared package -- the same dialog, in the
 * same shape, as the one jkctl opens to choose a board, because "which of
 * the devices on the other end is this page about" is one question and had
 * been answered by two different widgets.  What is this program's is what
 * goes under the list: a charger that neither mDNS nor the config file
 * knows can still be reached by address, with credentials, and that is a
 * form no bus-scanning program has any use for.
 */
export function StationPicker({ onPick, onClose, toast }) {
  const [stations, setStations] = useState(null);
  const [host, setHost] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    api
      .get('/stations')
      .then(setStations)
      .catch((err) => {
        toast.error(err.message);
        setStations({ configured: [], discovered: [] });
      });
  }, []);

  /* The two lines every device on either page is named by: what this one
   * is called, and what it is.  A station that has only ever been named in
   * a config file has an address and nothing else, and says so rather than
   * repeating its own address on both lines. */
  const entries = fleetOf(stations).map((station) => ({
    key: `${station.name}-${station.host}`,
    label: station.name || station.host,
    detail: station.name ? station.host || '' : 'not connected to yet',
    aside: station.source,
    station,
  }));

  const connect = () =>
    onPick({
      host: host.trim(),
      username: username || undefined,
      password: password || undefined,
    });

  return html`<${Picker}
    title="Choose a station"
    onClose=${onClose}
    looking=${stations === null}
    entries=${entries}
    empty="None found by mDNS and none in your config file. Enter an address below."
    onPick=${(entry) =>
      onPick({
        name: entry.station.name,
        host: entry.station.host,
        port: entry.station.port,
      })}
  >
    <div class="field spaced">
      <span class="lab">or an address directly</span>
      <div class="actions">
        <label class="grow">
          <span class="sr-only">address</span>
          <input
            type="text"
            placeholder="192.168.1.42"
            value=${host}
            onInput=${(e) => setHost(e.target.value)}
          />
        </label>
        <label class="grow narrow">
          <span class="sr-only">user name</span>
          <input
            type="text"
            placeholder="user"
            value=${username}
            onInput=${(e) => setUsername(e.target.value)}
          />
        </label>
        <label class="grow narrow">
          <span class="sr-only">password</span>
          <input
            type="password"
            placeholder="password"
            value=${password}
            onInput=${(e) => setPassword(e.target.value)}
          />
        </label>
        <button class="btn primary" disabled=${!host.trim()} onClick=${connect}>Connect</button>
      </div>
    </div>
  <//>`;
}
