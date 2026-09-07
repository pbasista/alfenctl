/* The Backoffice tab: how the charger talks to its central system.
 *
 * The OCPP connection settings (URLs, protocol, heartbeat, timeouts,
 * proxy) and the write-only secrets the property API cannot carry -- the
 * authorization key, the proxy password, TLS certificates.
 */

import { html, } from '../vendor/preact-htm.module.js';
import {
  Apply,
  EnumRow,
  Loading,
  NumRow,
  PanelError,
  putPanel,
  TextRow,
  ToggleRow,
  useDraft,
  usePanel,
} from './panels.js';
import { Card, Caveats, Help, Row } from './ui.js';


/* One read of `/ocpp` behind three cards.
 *
 * These were twenty fields in one card, in two columns, spanning two
 * tracks of the grid to hold them -- and a card that spans two tracks
 * ends the row for everything after it.  They divide cleanly by the
 * question being asked: where the backoffice is, how often the charger
 * talks to it, and what it says unprompted.  The pattern is the one
 * `Solar` established on the charging tab: the same panel key, so there
 * is still one read and one document, and a draft and an Apply each.
 */
function useOcpp({ onLoad }) {
  /* Every hook first, and unconditionally -- see the note in
   * js/charging.js on what an early return does to hook order. */
  const [doc, loading, error, read] = usePanel('ocpp', onLoad);
  const edits = useDraft();
  const live = doc?.ocpp || {};
  return {
    doc,
    loading,
    error,
    read,
    edits,
    live,
    opts: live.options || {},
    get: (key) => edits.get(key, live[key]),
    set: (key) => (value) => edits.set(key, value),
  };
}

function sendOcpp(edits, onWrite) {
  return () => {
    onWrite({ ...edits.draft }).catch(() => {});
    edits.clear();
  };
}

/* Where the backoffice is, and what the charger is to it. */
function Connection({ readOnly, busy, onLoad, onWrite }) {
  const { doc, loading, error, read, edits, live, opts, get, set } = useOcpp({ onLoad });

  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="OCPP connection" />`;
  if (!doc) return html`<${Loading} loading=${loading} what="Reading the backoffice..." title="OCPP connection" />`;

  return html`<${Card} title="OCPP connection">
    <${Help} summary="An operator is chosen by applying its preset, not from this card.">
      The rows below are the connection itself -- the URL the charger dials
      and what it says on the way in -- and setting them by hand is one of
      the two ways to point a station at a CSMS. The other is Alfen's own
      list of operators, on the ${' '}
      <a href="#properties">Properties tab</a>, under <em>Presets</em>: an
      operator's preset is a signed blob that carries the whole
      configuration, so applying one clears what the last operator left,
      uploads through the firmware channel and needs a reboot. That is more
      than a register write, which is why it is not a dropdown here.
    <//>
    <${Row}
      k="Back office"
      v=${live.backofficeName || '—'}
      data=${true}
      title="the name the last applied preset left behind; it labels the connection rather than deciding it"
    />
    <${EnumRow}
      k="Connect method"
      readOnly=${readOnly}
      value=${get('connectMethod')}
      table=${opts.connectMethods}
      onChange=${set('connectMethod')}
      disabled=${busy}
      includeBlank
    />
    <${EnumRow}
      k="OCPP version"
      readOnly=${readOnly}
      value=${get('protocol')}
      table=${Object.fromEntries((opts.protocols || []).map((p) => [p, p]))}
      kind="text"
      onChange=${set('protocol')}
      disabled=${busy}
      includeBlank
    />
    <${TextRow}
      k="Wired URL"
      readOnly=${readOnly}
      value=${readOnly
        ? [get('wiredUrl'), get('wiredPath')].filter(Boolean).join('/')
        : get('wiredUrl')}
      live=${live.wiredUrl}
      placeholder="ws://csms.example.com:80"
      width="220px"
      onChange=${set('wiredUrl')}
      disabled=${busy}
    />
    ${!readOnly &&
    html`<${TextRow}
      k="Wired path"
      value=${get('wiredPath')}
      live=${live.wiredPath}
      placeholder="/ocpp"
      width="220px"
      onChange=${set('wiredPath')}
      disabled=${busy}
    />`}
    <${TextRow}
      k="Mobile URL"
      readOnly=${readOnly}
      value=${readOnly
        ? [get('mobileUrl'), get('mobilePath')].filter(Boolean).join('/')
        : get('mobileUrl')}
      live=${live.mobileUrl}
      width="220px"
      onChange=${set('mobileUrl')}
      disabled=${busy}
    />
    ${!readOnly &&
    html`<${TextRow}
      k="Mobile path"
      value=${get('mobilePath')}
      live=${live.mobilePath}
      width="220px"
      onChange=${set('mobilePath')}
      disabled=${busy}
    />`}
    <${EnumRow}
      k="Security profile"
      readOnly=${readOnly}
      value=${get('securityProfile')}
      table=${opts.securityProfiles}
      onChange=${set('securityProfile')}
      disabled=${busy}
      includeBlank
    />
    <${TextRow}
      k="CPO name"
      readOnly=${readOnly}
      value=${get('cpoName')}
      live=${live.cpoName}
      onChange=${set('cpoName')}
      disabled=${busy}
      title="the name the charger checks the certificate against"
    />
    <${Caveats}
      items=${(live.warnings || []).map((w) => ({ short: w, detail: w }))}
    />
    ${!readOnly &&
    html`<${Apply} edits=${edits} busy=${busy} onApply=${sendOcpp(edits, onWrite)} />`}
  <//>`;
}

/* How often the charger talks, and how hard it tries when it cannot. */
function Timing({ readOnly, busy, onLoad, onWrite }) {
  const { doc, loading, error, edits, live, opts, get, set } = useOcpp({ onLoad });

  /* The connection card reports the *failure* for all three of them -- one
   * endpoint saying it three times is one endpoint shouting -- but each
   * card waits for itself.  Rendering nothing while the read is in flight
   * is what put one skeleton on this tab where four cards were coming, and
   * moved everything below them when they landed. */
  if (error) return null;
  if (!doc) {
    return html`<${Loading}
      loading=${loading}
      what="Reading the backoffice..."
      title="Timing and retries"
    />`;
  }

  return html`<${Card} title="Timing and retries">
    <${NumRow}
      k="Heartbeat"
      readOnly=${readOnly}
      value=${get('heartbeatS')}
      live=${live.heartbeatS}
      min="0"
      unit="s"
      onChange=${set('heartbeatS')}
      disabled=${busy}
      title=${live.heartbeatActualS && live.heartbeatActualS !== live.heartbeatS
        ? `the backoffice settled on ${live.heartbeatActualS} s`
        : ''}
    />
    <${NumRow}
      k="Ping/pong"
      readOnly=${readOnly}
      value=${get('pingPongS')}
      live=${live.pingPongS}
      min="0"
      unit="s"
      onChange=${set('pingPongS')}
      disabled=${busy}
    />
    <${NumRow}
      k="Meter interval"
      readOnly=${readOnly}
      value=${get('meterIntervalS')}
      live=${live.meterIntervalS}
      min="0"
      unit="s"
      onChange=${set('meterIntervalS')}
      disabled=${busy}
    />
    <${NumRow}
      k="Message attempts"
      readOnly=${readOnly}
      value=${get('txAttempts')}
      live=${live.txAttempts}
      min="0"
      unit="tries"
      onChange=${set('txAttempts')}
      disabled=${busy}
    />
    <${NumRow}
      k="Retry interval"
      readOnly=${readOnly}
      value=${get('txRetryS')}
      live=${live.txRetryS}
      min="0"
      unit="s"
      onChange=${set('txRetryS')}
      disabled=${busy}
    />
    <${EnumRow}
      k="Status notification"
      readOnly=${readOnly}
      value=${get('statusMode')}
      table=${opts.statusModes}
      onChange=${set('statusMode')}
      disabled=${busy}
      includeBlank
    />
    ${!readOnly &&
    html`<${Apply} edits=${edits} busy=${busy} onApply=${sendOcpp(edits, onWrite)} />`}
  <//>`;
}

/* What the charger sends unprompted, and what it sends it through. */
function Notices({ readOnly, busy, onLoad, onWrite }) {
  const { doc, loading, error, edits, live, get, set } = useOcpp({ onLoad });

  if (error) return null;
  if (!doc) {
    return html`<${Loading}
      loading=${loading}
      what="Reading the backoffice..."
      title="Notices and proxy"
    />`;
  }

  return html`<${Card} title="Notices and proxy">
    <${ToggleRow}
      k="Send station status"
      value=${get('sendStationStatus')}
      onChange=${set('sendStationStatus')}
      disabled=${readOnly || busy}
    />
    <${ToggleRow}
      k="Informational notices"
      value=${get('infoNotifications')}
      onChange=${set('infoNotifications')}
      disabled=${readOnly || busy}
    />
    <${ToggleRow}
      k="Proxy"
      value=${get('proxyEnabled')}
      onChange=${set('proxyEnabled')}
      disabled=${readOnly || busy}
    />
    <${TextRow}
      k="Proxy address"
      readOnly=${readOnly}
      value=${get('proxyAddress')}
      live=${live.proxyAddress}
      placeholder="host:port"
      width="180px"
      onChange=${set('proxyAddress')}
      disabled=${busy}
    />
    <${TextRow}
      k="Proxy user"
      readOnly=${readOnly}
      value=${get('proxyUser')}
      live=${live.proxyUser}
      onChange=${set('proxyUser')}
      disabled=${busy}
    />
    ${!readOnly &&
    html`<${Apply} edits=${edits} busy=${busy} onApply=${sendOcpp(edits, onWrite)} />`}
  <//>`;
}

function Secrets({ readOnly, busy, api, toast }) {
  const [doc, loading, error, read] = usePanel('secrets', () => api.get('/secrets'));
  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="Secrets" />`;
  if (!doc) {
    return html`<${Loading} loading=${loading} what="Reading the secrets..." title="Secrets" />`;
  }
  const secrets = doc.secrets || [];
  return html`<${Card} title="Secrets" width="full">
    <${Help} summary="Write-only: installing one replaces whatever was there.">
      The charger never reads these back, so there is nothing to compare
      against and nothing to show you afterwards. Each applies on the next
      restart. An item marked * is typed from the vendor app's own table,
      but the app never sends it, so it is untested against a live charger.
    <//>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>What it is</th>
            <th>Takes</th>
            ${!readOnly && html`<th class="right"></th>`}
          </tr>
        </thead>
        <tbody>
          ${secrets.map(
            (s) => html`<tr key=${s.name}>
              <td class="data">${s.name}</td>
              <td>
                ${s.summary}${s.verified ? '' : ' *'}
              </td>
              <td>${s.takesFile ? 'FILE' : 'VALUE'}</td>
              ${!readOnly &&
              html`<td class="right">
                <label
                  class="btn small ghost"
                  style="cursor:${busy ? 'wait' : 'pointer'}"
                  title=${s.takesFile
                    ? 'a PEM file'
                    : 'a value; the charger never reads it back'}
                >
                  ${busy ? 'busy' : 'install'}
                  <input
                    type="file"
                    style="display:none"
                    disabled=${busy}
                    onChange=${(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      api
                        .upload('/secret', file, { name: s.name })
                        .then((r) => toast.ok(r.message || 'Installed.'))
                        .catch((err) => toast.error(err.message));
                      e.target.value = '';
                    }}
                  />
                </label>
              </td>`}
            </tr>`
          )}
        </tbody>
      </table>
    </div>
  <//>`;

}

export function Backoffice({ api, readOnly, busy, toast }) {
  const writeConnection = (payload) =>
    api
      .post('/ocpp', payload)
      .then((doc) => {
        toast.ok('Backoffice settings written.');
        /* The reply is the charger's new answer, and three cards are
         * reading one document: an Apply on any of them moves the other
         * two without reading the charger again. */
        if (doc?.ocpp) putPanel('ocpp', doc);
        return doc;
      })
      .catch((err) => {
        toast.error(err.message);
        throw err;
      });
  const load = () => api.get('/ocpp');
  const parts = { readOnly, busy, onLoad: load, onWrite: writeConnection };
  return html`<div class="grid">
    <${Connection} ...${parts} />
    <${Timing} ...${parts} />
    <${Notices} ...${parts} />
    <${Secrets} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
  </div>`;
}
