/* The Backoffice tab: how the charger talks to its central system.
 *
 * The OCPP connection settings (URLs, protocol, heartbeat, timeouts,
 * proxy) and the write-only secrets the property API cannot carry -- the
 * authorization key, the proxy password, TLS certificates.
 */

import { offerWriter, useDraft } from '/core/js/drafts.js';
import { EnumRow, NumRow, panelWait, putPanel, TextRow, ToggleRow, usePanel } from '/core/js/panels.js';
import { Card, Caveats, Help, Row } from '/core/js/ui.js';
import { html, } from '/core/vendor/preact-htm.module.js';


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
function useOcpp({ onLoad, scope }) {
  /* Every hook first, and unconditionally -- see the note in
   * js/charging.js on what an early return does to hook order. */
  const panel = usePanel('ocpp', onLoad);
  const [doc] = panel;
  const draft = useDraft(scope);
  const live = doc?.ocpp || {};
  return {
    panel,
    doc,
    draft,
    live,
    opts: live.options || {},
    get: (key) => draft.get(key, live[key]),
    set: (key) => (value) => draft.set(key, value),
  };
}

/* Each card is its own draft, sent to the one endpoint. */
function offerOcpp(scope, title, { busy, readOnly, onWrite }) {
  offerWriter(scope, { title, busy, disabled: readOnly, write: onWrite });
}

/* Where the backoffice is, and what the charger is to it. */
function Connection({ readOnly, busy, onLoad, onWrite }) {
  const { panel, draft, live, opts, get, set } = useOcpp({ onLoad, scope: 'ocpp:connection' });

  const waiting = panelWait(panel, { title: 'OCPP connection', what: 'Reading the backoffice...' });
  if (waiting !== undefined) return waiting;

  offerOcpp('ocpp:connection', 'OCPP connection', { busy, readOnly, onWrite });
  return html`<${Card} title="OCPP connection" draft=${draft}>
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
      hint="the name the last applied preset left behind; it labels the connection rather than deciding it"
    />
    <${EnumRow}
      pending=${draft.has('connectMethod')}
      k="Connect method"
      readOnly=${readOnly}
      value=${get('connectMethod')}
      table=${opts.connectMethod}
      onChange=${set('connectMethod')}
      disabled=${busy}
      includeBlank
    />
    <${EnumRow}
      pending=${draft.has('protocol')}
      k="OCPP version"
      readOnly=${readOnly}
      value=${get('protocol')}
      table=${Object.fromEntries((opts.protocol || []).map((p) => [p, p]))}
      kind="text"
      onChange=${set('protocol')}
      disabled=${busy}
      includeBlank
    />
    <${TextRow}
      pending=${draft.has('wiredUrl')}
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
      pending=${draft.has('wiredPath')}
      k="Wired path"
      value=${get('wiredPath')}
      live=${live.wiredPath}
      placeholder="/ocpp"
      width="220px"
      onChange=${set('wiredPath')}
      disabled=${busy}
    />`}
    <${TextRow}
      pending=${draft.has('mobileUrl')}
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
      pending=${draft.has('mobilePath')}
      k="Mobile path"
      value=${get('mobilePath')}
      live=${live.mobilePath}
      width="220px"
      onChange=${set('mobilePath')}
      disabled=${busy}
    />`}
    <${EnumRow}
      pending=${draft.has('securityProfile')}
      k="Security profile"
      readOnly=${readOnly}
      value=${get('securityProfile')}
      table=${opts.securityProfile}
      onChange=${set('securityProfile')}
      disabled=${busy}
      includeBlank
    />
    <${TextRow}
      pending=${draft.has('cpoName')}
      k="CPO name"
      readOnly=${readOnly}
      value=${get('cpoName')}
      live=${live.cpoName}
      onChange=${set('cpoName')}
      disabled=${busy}
      hint="the name the charger checks the certificate against"
    />
    <${Caveats}
      items=${(live.warnings || []).map((w) => ({ short: w, detail: w }))}
    />
  <//>`;
}

/* How often the charger talks, and how hard it tries when it cannot. */
function Timing({ readOnly, busy, onLoad, onWrite }) {
  const { panel, draft, live, opts, get, set } = useOcpp({ onLoad, scope: 'ocpp:timing' });

  /* The connection card reports the *failure* for all three of them -- one
   * endpoint saying it three times is one endpoint shouting -- but each
   * card waits for itself.  Rendering nothing while the read is in flight
   * is what put one skeleton on this tab where four cards were coming, and
   * moved everything below them when they landed. */
  const waiting = panelWait(panel, {
    title: 'Timing and retries',
    what: 'Reading the backoffice...',
    quiet: true,
  });
  if (waiting !== undefined) return waiting;

  offerOcpp('ocpp:timing', 'Timing and retries', { busy, readOnly, onWrite });
  return html`<${Card} title="Timing and retries" draft=${draft}>
    <${NumRow}
      pending=${draft.has('heartbeatS')}
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
      pending=${draft.has('pingPongS')}
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
      pending=${draft.has('meterIntervalS')}
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
      pending=${draft.has('txAttempts')}
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
      pending=${draft.has('txRetryS')}
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
      pending=${draft.has('statusMode')}
      k="Status notification"
      readOnly=${readOnly}
      value=${get('statusMode')}
      table=${opts.statusMode}
      onChange=${set('statusMode')}
      disabled=${busy}
      includeBlank
    />
  <//>`;
}

/* What the charger sends unprompted, and what it sends it through. */
function Notices({ readOnly, busy, onLoad, onWrite }) {
  const { panel, draft, live, get, set } = useOcpp({ onLoad, scope: 'ocpp:notices' });

  const waiting = panelWait(panel, {
    title: 'Notices and proxy',
    what: 'Reading the backoffice...',
    quiet: true,
  });
  if (waiting !== undefined) return waiting;

  offerOcpp('ocpp:notices', 'Notices and proxy', { busy, readOnly, onWrite });
  return html`<${Card} title="Notices and proxy" draft=${draft}>
    <${ToggleRow}
      pending=${draft.has('sendStationStatus')}
      k="Send station status"
      value=${get('sendStationStatus')}
      onChange=${set('sendStationStatus')}
      disabled=${readOnly || busy}
    />
    <${ToggleRow}
      pending=${draft.has('infoNotifications')}
      k="Informational notices"
      value=${get('infoNotifications')}
      onChange=${set('infoNotifications')}
      disabled=${readOnly || busy}
    />
    <${ToggleRow}
      pending=${draft.has('proxyEnabled')}
      k="Proxy"
      value=${get('proxyEnabled')}
      onChange=${set('proxyEnabled')}
      disabled=${readOnly || busy}
    />
    <${TextRow}
      pending=${draft.has('proxyAddress')}
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
      pending=${draft.has('proxyUser')}
      k="Proxy user"
      readOnly=${readOnly}
      value=${get('proxyUser')}
      live=${live.proxyUser}
      onChange=${set('proxyUser')}
      disabled=${busy}
    />
  <//>`;
}

function Secrets({ readOnly, busy, api, toast }) {
  const panel = usePanel('secrets', () => api.get('/secrets'));
  const [doc] = panel;
  const waiting = panelWait(panel, { title: 'Secrets', what: 'Reading the secrets...' });
  if (waiting !== undefined) return waiting;

  const secrets = doc.secrets || [];
  return html`<${Card} title="Secrets" width="full" immediate=${!readOnly}>
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
