/* The Connectivity tab: where the charger is, and how it got there.
 *
 * Called Connectivity rather than Network because "network" is already a
 * word about charging stations -- the charging network an operator runs
 * them on, which is what the Backoffice tab is about.  A tab named for it
 * that turns out to hold interface addresses and a Wi-Fi scan is a tab that
 * sends people to the wrong place twice.
 *
 * The interface addresses (read-only, the way the CLI prints them), the
 * Wi-Fi radio's scan and join, the live smart-meter wiring test, and the
 * custom Modbus register map for a meter the charger does not know.
 */

import { Loading, PanelCard, PanelError, panelWait, usePanel } from '/core/js/panels.js';
import { Card, caller, Row } from '/core/js/ui.js';
import { html, useState } from '/core/vendor/preact-htm.module.js';

function WifiScan({ readOnly, busy, api, toast }) {
  const call = caller(toast);
  const [doc, setDoc] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');
  const [psk, setPsk] = useState('');
  const [joining, setJoining] = useState(null);
  const [enableFirst, setEnableFirst] = useState(true);

  const scan = async () => {
    setScanning(true);
    setError('');
    try {
      setDoc(await api.get('/wifi/scan', enableFirst ? { enable: '1' } : {}));
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  };

  const join = (net) =>
    api
      .post('/wifi', {
        action: 'connect',
        ssid: net.ssid,
        psk: psk || null,
        security: net.security,
      })
      .then(() => toast.ok(`Asked to join ${net.ssid}.`))
      .catch((err) => toast.error(err.message))
      .finally(() => setJoining(null));

  const nets = doc?.networks || [];
  return html`<${Card} title="Wi-Fi">
    <div class="actions">
      <button class="btn" disabled=${scanning || busy} onClick=${scan}>
        ${scanning ? 'Scanning...' : 'Scan for networks'}
      </button>
      <label class="toggle" title="a scan with the radio off finds nothing; this switches it on first">
        <input
          type="checkbox"
          checked=${enableFirst}
          disabled=${readOnly || busy}
          onChange=${(e) => setEnableFirst(e.target.checked)}
        />
        switch the radio on first
      </label>
    </div>
    ${error && html`<p class="card-note bad">${error}</p>`}
    ${doc?.note && html`<p class="note">${doc.note}</p>`}
    ${nets.length > 0 &&
    /* A network is a name, a line about it, and one button, which is the
     * shape `.entry` already draws for Alfen's releases -- and the
     * passphrase, when it is asked for, has the width of the entry rather
     * than of a table cell.  As a three-column table this card had to
     * claim two tracks of the grid, and a card two tracks wide ends the
     * row for every card after it. */
    html`<div class="scroller spaced">
      ${nets.map(
        (n) => html`<div class="entry" key=${n.ssid}>
          <div class="head">
            <span class="name data">${n.ssid}</span>
            ${!readOnly &&
            html`<span class="act">
              <button
                class="btn small"
                disabled=${busy || !n.supported || joining === n.ssid}
                title=${n.supported ? '' : 'the charger cannot join this security mode'}
                onClick=${() => {
                  setJoining(n.ssid);
                  setPsk('');
                }}
              >
                join
              </button>
            </span>`}
          </div>
          <div class="meta muted">
            ${n.securityLabel} -- ${n.signal} (${n.signalDbm} dBm)
          </div>
          ${joining === n.ssid &&
          html`<div class="actions">
            <input
              type="password"
              placeholder="passphrase"
              class="grow"
              value=${psk}
              onInput=${(e) => setPsk(e.target.value)}
            />
            <button class="btn small primary" disabled=${busy} onClick=${() => join(n)}>
              join
            </button>
            <button class="btn small ghost" onClick=${() => setJoining(null)}>cancel</button>
          </div>`}
        </div>`
      )}
    </div>`}
    ${!readOnly &&
    html`<div class="actions">
      <button
        class="btn ghost"
        disabled=${busy}
        onClick=${() =>
          call(() => api.post('/wifi', { action: 'enable' }), 'Wi-Fi radio enabled.')}
      >
        Enable radio
      </button>
      <button
        class="btn ghost"
        disabled=${busy}
        onClick=${() =>
          call(() => api.post('/wifi', { action: 'disconnect' }), 'Wi-Fi radio switched off.')}
      >
        Switch radio off
      </button>
    </div>`}
  <//>`;
}

function MeterTest({ busy, api }) {
  const [doc, loading, error, read] = usePanel('meter-test', () => api.get('/meter-test'));

  if (doc === null && !error) {
    return html`<${Loading} loading=${loading} what="Reading the meter test..." title="Smart-meter test" />`;
  }

  const readings = doc?.readings || [];
  return html`<${Card}
    title="Smart-meter test"
    actions=${html`<button class="btn small ghost" disabled=${busy} onClick=${read}>
      refresh
    </button>`}
  >
    ${error
      ? html`<${PanelError} error=${error} loading=${loading} onRetry=${read} />`
      : readings.length === 0
        ? html`<div class="empty">
            No live meter readings. The charger reports them once the
            <code>meter4</code> category has been read -- open the Properties
            tab and read it first.
          </div>`
        : html`<div class="rows">
            ${readings.map(
              (m) => html`<${Row}
                key=${m.label}
                k=${m.label}
                v=${m.value === null ? '—' : `${m.value} ${m.unit}`}
              />`
            )}
          </div>`}
  <//>`;
}

function MeterMap({ readOnly, busy, api, toast }) {
  const panel = usePanel('meter-map', () => api.get('/meter-map'));
  const [doc] = panel;
  const waiting = panelWait(panel, { title: 'Custom meter map', what: 'Reading the meter map...' });
  if (waiting !== undefined) return waiting;

const map = doc.meterMap || {};
  const entries = map.entries || [];
  return html`<${Card}
    title="Custom meter map"
    immediate=${!readOnly}
    actions=${entries.length > 0 && html`<span class="badge">${entries.length} of ${map.capacity}</span>`}
    width="full"
  >
    ${entries.length === 0
      ? html`<div class="empty">
          No custom register map is installed; the charger is reading a meter
          it knows, or none at all.
        </div>`
      : html`<div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Measurand</th>
                <th>Register</th>
                <th>Type</th>
                <th>Scale</th>
              </tr>
            </thead>
            <tbody>
              ${entries.map(
                (e, i) => html`<tr key=${i}>
                  <td>${e.measurand}</td>
                  <td class="data">${e.register}</td>
                  <td>${e.dataType}</td>
                  <td>${e.factor}</td>
                </tr>`
              )}
            </tbody>
          </table>
        </div>`}
    ${!readOnly &&
    html`<div class="actions">
      <input
        type="file"
        accept=".json,application/json"
        disabled=${busy}
        onChange=${(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          api
            .upload('/meter-map', file)
            .then(() => {
              toast.ok('Register map written. Check it with the meter test.');
              read();
            })
            .catch((err) => toast.error(err.message));
          e.target.value = '';
        }}
      />
      <span class="note">one of Alfen's register-map JSON files</span>
    </div>`}
  <//>`;
}

export function Connectivity({ api, readOnly, busy, toast }) {
  const [netDoc, netLoading, netError, netRead] = usePanel('connectivity', () =>
    api.get('/connectivity')
  );
  return html`<div class="grid">
    ${netError
      ? html`<${PanelError} error=${netError} loading=${netLoading} onRetry=${netRead} title="Interfaces" />`
      : netDoc
        ? html`<${PanelCard}
            title="Interfaces"
            rows=${netDoc.connectivity?.rows}
            note="Where the charger is reachable."
            more="Read only, and as the CLI reports it: these are the addresses the
              charger answers with. The Wi-Fi radio is joined from the card beside this
              one, and a wired address is set on the charger itself."
          />`
        : html`<${Loading} loading=${netLoading} what="Reading the interfaces..." title="Interfaces" />`}
    <${WifiScan} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
    <${MeterTest} busy=${busy} api=${api} />
    <${MeterMap} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
  </div>`;
}
