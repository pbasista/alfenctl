/* The Charging tab: how the station shares its supply.
 *
 * Load balancing and solar charging (the vendor app's Load balancing
 * panel), the OCPP charging profiles the charger enforces locally, the
 * per-socket direct-start override, and Smart Charging Network
 * membership.  The same modules the CLI drives, over the same one
 * connection, edited as cards with one Apply each.
 */

import { html, useState } from '../vendor/preact-htm.module.js';
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

import { Card, Caveats, Confirm, Row } from './ui.js';

/* --- load balancing and solar ------------------------------------------------ */

/* One read of `/lb` behind two cards, in the pattern `Solar` below already
 * uses: the same panel key, a draft and an Apply of its own each, and the
 * charger's reply put back for both by `onLbWrite`.
 *
 * They were one card of eleven fields forced into two columns, and a card
 * two tracks wide ends the row for everything after it.  They are two
 * questions in any case: whether the station balances at all and against
 * what it measures, then the numbers it is held to when it does.
 */
function useBalancing({ onLoad }) {
  /* Every hook first, and unconditionally.  Preact matches hooks up by the
   * order they are called in, so a `useDraft` sitting below an early
   * return belongs to a different slot on the render that has a document
   * than on the render that did not -- which is a card that quietly wears
   * another card's state the moment its read lands. */
  const [doc, loading, error, read] = usePanel('lb', onLoad);
  const edits = useDraft();
  const live = doc?.loadbalancing || {};
  return {
    doc,
    loading,
    error,
    read,
    edits,
    live,
    opts: live.options || {},
    bounds: live.bounds || {},
    get: (key) => edits.get(key, live[key]),
    set: (key) => (value) => edits.set(key, value),
  };
}

/* The toast belongs to whoever does the writing, and that is `onWrite` --
 * saying it here as well is how one Apply used to raise two identical
 * notices.  An empty draft is an Apply nobody made a change for. */
function sendBalancing(edits, onWrite) {
  return () => {
    const payload = { ...edits.draft };
    if (!Object.keys(payload).length) {
      edits.clear();
      return;
    }
    onWrite(payload).catch(() => {});
    edits.clear();
  };
}

function Balancing({ readOnly, busy, onLoad, onWrite }) {
  const { doc, loading, error, read, edits, live, opts, get, set } = useBalancing({
    onLoad,
  });

  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="Load balancing" />`;
  if (!doc) return html`<${Loading} loading=${loading} what="Reading load balancing..." title="Load balancing" />`;

  return html`<${Card} title="Load balancing">

    <${ToggleRow}
      k="Static balancing"
      value=${get('static')}
      onChange=${set('static')}
      disabled=${readOnly || busy}
      label="cap against the feed"
      title="cap the station when the meter says the supply behind it is loaded"
    />
    <${ToggleRow}
      k="Active balancing"
      value=${get('active')}
      onChange=${set('active')}
      disabled=${readOnly || busy}
      label="follow the meter"
      title="hold the station to whatever the meter is measuring, moment by moment"
    />
    <${EnumRow}
      k="Meter protocol"
      readOnly=${readOnly}
      value=${get('protocol')}
      table=${opts.protocols}
      onChange=${set('protocol')}
      disabled=${busy}
      includeBlank
    />
    <${EnumRow}
      k="Data source"
      readOnly=${readOnly}
      value=${get('dataSource')}
      table=${opts.dataSources}
      onChange=${set('dataSource')}
      disabled=${busy}
      includeBlank
    />
    <${EnumRow}
      k="Measurement"
      readOnly=${readOnly}
      value=${get('measurementIncludesEv')}
      table=${opts.measurementSources}
      kind="boolean"
      onChange=${set('measurementIncludesEv')}
      disabled=${busy}
      title="whether the meter's reading already has the car in it"
    />
    <${Caveats}
      items=${(live.warnings || []).map((w) => ({ short: w, detail: w }))}
    />
    ${!readOnly &&
    html`<${Apply} edits=${edits} busy=${busy} onApply=${sendBalancing(edits, onWrite)} />`}
  <//>`;
}

/* What the station is held to once it is balancing: the ceiling, the
 * floor it falls back to, and how it is allowed to use its phases. */
function Limits({ readOnly, busy, onLoad, onWrite }) {
  const { doc, loading, error, edits, live, bounds, get, set } = useBalancing({ onLoad });

  /* The card above reports the *failure* for both of them -- one endpoint
   * saying it twice is one endpoint shouting -- but not the wait.  A card
   * that renders nothing while a read is in flight is a card the grid does
   * not know is coming: three panels behind one read put up one skeleton
   * and then landed as three, and every card below them jumped a row.  A
   * skeleton is a card's way of saying it will be here. */
  if (error) return null;
  if (!doc) {
    return html`<${Loading}
      loading=${loading}
      what="Reading load balancing..."
      title="Current limits and phases"
    />`;
  }

  return html`<${Card} title="Current limits and phases">
    <${NumRow}
      k="Max meter current"
      readOnly=${readOnly}
      value=${get('maxMeterCurrentA')}
      live=${live.maxMeterCurrentA}
      min=${bounds.minMeterCurrentA}
      max=${bounds.maxMeterCurrentA}
      unit="A"
      onChange=${set('maxMeterCurrentA')}
      disabled=${busy}
    />
    <${NumRow}
      k="Safe current"
      readOnly=${readOnly}
      value=${get('safeCurrentA')}
      live=${live.safeCurrentA}
      min=${bounds.minSafeCurrentA}
      max=${bounds.maxSafeCurrentA}
      unit="A"
      onChange=${set('safeCurrentA')}
      disabled=${busy}
      title="what the station falls back to when nothing is managing it"
    />
    <${NumRow}
      k="Max imbalance"
      readOnly=${readOnly}
      value=${get('maxImbalanceA')}
      live=${live.maxImbalanceA}
      min="0"
      unit="A"
      onChange=${set('maxImbalanceA')}
      disabled=${busy}
    />
    <${TextRow}
      k="Phase rotation"
      readOnly=${readOnly}
      value=${get('phaseRotation')}
      live=${live.phaseRotation}
      placeholder="L1L2L3"
      width="110px"
      onChange=${set('phaseRotation')}
      disabled=${busy}
    />
    <${ToggleRow}
      k="Phase switching"
      value=${get('phaseSwitching')}
      onChange=${set('phaseSwitching')}
      disabled=${readOnly || busy}
      label="allow one or three"
      title="let the station switch between single-phase and multiphase charging"
    />
    <${EnumRow}
      k="Max allowed phases"
      readOnly=${readOnly}
      value=${get('maxAllowedPhases')}
      table=${{ 1: '1', 3: '3' }}
      onChange=${set('maxAllowedPhases')}
      disabled=${busy}
      includeBlank
    />
    ${!readOnly &&
    html`<${Apply} edits=${edits} busy=${busy} onApply=${sendBalancing(edits, onWrite)} />`}
  <//>`;
}

/* Solar is the same document as the balancing card above it -- one read of
 * `/lb` answers both, which is why they share the panel store's `lb` key
 * rather than each fetching it.  Two reads of one endpoint over the one
 * charger connection was two waits for one answer, and two copies of it
 * that could disagree. */
function Solar({ readOnly, busy, onLoad, onWrite }) {
  const [doc, loading, error, read] = usePanel('lb', onLoad);
  const edits = useDraft();

  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="Solar charging" />`;
  if (!doc) {
    return html`<${Loading}
      loading=${loading}
      what="Reading solar charging..."
      title="Solar charging"
    />`;
  }
  const live = doc.loadbalancing || {};
  if (live.solarMode === null || live.solarMode === undefined) return null;
  const opts = live.options || {};
  const bounds = live.bounds || {};
  const get = (key) => edits.get(key, live[key]);

  const set = (key) => (value) => edits.set(key, value);

  const send = () => {
    const payload = { ...edits.draft };
    onWrite(payload).catch(() => {});
    edits.clear();
  };

  return html`<${Card} title="Solar charging">
    <${EnumRow}
      k="Mode"
      readOnly=${readOnly}
      value=${get('solarMode')}
      table=${opts.solarModes}
      onChange=${set('solarMode')}
      disabled=${busy}
      includeBlank
    />
    <${NumRow}
      k="Green share"
      readOnly=${readOnly}
      value=${get('solarGreenShare')}
      live=${live.solarGreenShare}
      min=${bounds.minGreenShare}
      max=${bounds.maxGreenShare}
      unit="%"
      onChange=${set('solarGreenShare')}
      disabled=${busy}
      title="how much of the available surplus the car may take"
    />
    <${NumRow}
      k="Comfort level"
      readOnly=${readOnly}
      value=${get('solarComfortW')}
      live=${live.solarComfortW}
      min=${bounds.minComfortW}
      max=${bounds.maxComfortW}
      step="50"
      unit="W"
      onChange=${set('solarComfortW')}
      disabled=${busy}
      title="the minimum the charger always allows in comfort mode"
    />
    ${!readOnly && html`<${Apply} edits=${edits} busy=${busy} onApply=${send} />`}
  <//>`;
}

/* --- charging profiles and the direct-start override -------------------------- */

function hhmm(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  return d > 0 ? `+${d}d ${time}` : time;
}

function Profiles({ readOnly, busy, onLoad, onInstallUk, onClear }) {
  const [doc, loading, error, read] = usePanel('profiles', onLoad);
  const [confirm, setConfirm] = useState(null);

  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="Charging profiles" />`;
  if (!doc) return html`<${Loading} loading=${loading} what="Reading charging profiles..." title="Charging profiles" />`;

  if (doc.supported === false) {
    return html`<${Card} title="Charging profiles">
      <div class="empty">This charger's firmware does not support charging profiles.</div>
    <//>`;
  }
  const profiles = doc.profiles || [];
  /* Six columns when there are profiles, one sentence when there are not
   * -- and none is the ordinary state of a charger nobody has sent a
   * profile to, so the card is not a row wide by default. */
  return html`<${Card} title="Charging profiles" width=${profiles.length ? 'full' : undefined}>

    ${profiles.length === 0
      ? html`<div class="empty">
          No charging profiles installed. The charger enforces any that are,
          whether or not a backoffice is watching.
        </div>`
      : html`<div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Profile</th>
                <th>Connector</th>
                <th>Kind</th>
                <th>Purpose</th>
                <th>Schedule</th>
                ${!readOnly && html`<th class="right"></th>`}
              </tr>
            </thead>
            <tbody>
              ${profiles.map(
                (p) => html`<tr key=${p.id}>
                  <td class="data">${p.id}${p.isUkDefault ? ' (UK default)' : ''}</td>
                  <td>${p.connectorId}</td>
                  <td>${p.kind}</td>
                  <td>${p.purpose}</td>
                  <td>
                    ${(p.periods || [])
                      .map((per) => `${hhmm(per.startS)} → ${per.limitA} ${p.rateUnit}`)
                      .join(', ')}
                  </td>
                  ${!readOnly &&
                  html`<td class="right">
                    <button
                      class="btn small"
                      disabled=${busy}
                      onClick=${() =>
                        setConfirm({
                          title: `Clear profile ${p.id}?`,
                          body: 'The charger stops enforcing this schedule.',
                          confirmLabel: 'Clear',
                          run: () => onClear(p.id),
                        })}
                    >
                      clear
                    </button>
                  </td>`}
                </tr>`
              )}
            </tbody>
          </table>
        </div>`}
    ${!readOnly &&
    html`<div class="actions-row">
      <button
        class="btn"
        disabled=${busy}
        onClick=${() =>
          setConfirm({
            title: 'Install the UK Smart Charging default?',
            body: 'Charging is blocked 08:00-11:00 and 16:00-22:00 on weekdays, allowed the rest of the time.',
            confirmLabel: 'Install',
            run: onInstallUk,
          })}
      >
        Install UK default
      </button>
      ${profiles.length > 0 &&
      html`<button
        class="btn ghost"
        disabled=${busy}
        onClick=${() =>
          setConfirm({
            title: 'Clear every profile?',
            body: 'The charger stops enforcing any local schedule.',
            confirmLabel: 'Clear all',
            danger: true,
            run: () => onClear('all'),
          })}
      >
        Clear all
      </button>`}
    </div>`}
    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  <//>`;
}

function DirectStart({ readOnly, busy, onLoad, onWrite }) {
  const [doc, loading, error, read] = usePanel('direct-start', onLoad);
  const edits = useDraft();

  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="Direct start" />`;
  if (!doc) {
    return html`<${Loading} loading=${loading} what="Reading direct start..." title="Direct start" />`;
  }
  const live = doc.directStart || {};
  const overrides = live.overrides || {};
  if (!Object.keys(overrides).length && live.randomDelayS === null) return null;

  const numbers = Object.keys(overrides).sort();

  const get = (n) => edits.get(`socket${n}`, overrides[n]);
  const delay = edits.get('randomDelayS', live.randomDelayS);

  const send = () => {
    const payload = {
      sockets: numbers.map(Number),
      direct: numbers.map((n) => Boolean(get(n))),
      randomDelayS: delay,
    };
    onWrite(payload).catch(() => {});
    edits.clear();
  };

  return html`<${Card} title="Direct start">
    <p class="note">
      Let a socket charge despite an installed profile. With no profile
      installed, this changes nothing.
    </p>
    <div class="rows">
      ${numbers.map(
        (n) => html`<${ToggleRow}
          key=${n}
          k=${`Socket ${n}`}
          value=${get(n)}
          onChange=${(v) => edits.set(`socket${n}`, v)}
          disabled=${readOnly || busy}
          label=${get(n) ? 'direct start' : 'follow the profile'}
        />`
      )}
      <${NumRow}
        k="Random delay"
        readOnly=${readOnly}
        value=${delay}
        live=${live.randomDelayS}
        min="0"
        max=${live.maxDelayS}
        unit="s"
        onChange=${(v) => edits.set('randomDelayS', v)}
        disabled=${busy}
        title=${`below ${live.compliantDelayS} s the station is no longer compliant with the UK regulation`}
      />
    </div>
    ${!readOnly && html`<${Apply} edits=${edits} busy=${busy} onApply=${send} />`}
  <//>`;
}

/* --- Smart Charging Network --------------------------------------------------- */

function Scn({ readOnly, busy, onLoad, onAction }) {
  const [doc, loading, error, read] = usePanel('scn', onLoad);

  const [confirm, setConfirm] = useState(null);
  const [name, setName] = useState('');
  if (error) return html`<${PanelError} error=${error} loading=${loading} onRetry=${read} title="Smart Charging Network" />`;
  if (!doc) return html`<${Loading} loading=${loading} what="Reading SCN membership..." title="Smart Charging Network" />`;

  const scn = doc.scn || {};
  const members = scn.peers || [];

  return html`<${Card} title="Smart Charging Network">
    ${scn.inNetwork
      ? html`<div class="rows">
          <${Row} k="Network" v=${scn.name} data=${true} />
          <${Row} k="This station" v=${`socket ${scn.socketId}`} />
          <${Row} k="Sockets in the group" v=${scn.socketCount} />
          <${Row} k="Alternating" v=${`every ${scn.alternatingPeriodS} s`} />
          <${Row} k="Group current" v=${`${scn.totalCurrentA} A`} />
          <${Row} k="Socket safe current" v=${`${scn.socketSafeCurrentA} A`} />
          <${Row} k="Group safe current" v=${`${scn.totalSafeCurrentA} A`} />
          ${members.length > 0 &&
          html`<${Row}
            k="Other members"
            v=${members.map((p) => `${p.objectId} (socket ${p.socketId})`).join(', ')}
          />`}
        </div>`
      : html`<div class="empty">
          This station is not a member of a Smart Charging Network -- a group
          of chargers that share one grid connection's current budget and
          take turns charging when the budget is tight.
        </div>`}
    ${!readOnly &&
      (scn.inNetwork
        ? html`<div class="actions-row">
            <button
              class="btn"
              disabled=${busy}
              onClick=${() =>
                setConfirm({
                  title: `Leave '${scn.name}'?`,
                  body: 'The other members keep their settings; this station charges on its own again.',
                  confirmLabel: 'Leave',
                  run: () => onAction({ action: 'leave' }),
                })}
            >
              Leave the network
            </button>
          </div>`
        : html`<div class="actions-row">
            <input
              type="text"
              placeholder="network name (max 7 chars)"
              style="width:200px"
              maxLength="7"
              value=${name}
              onInput=${(e) => setName(e.target.value)}
            />
            <button
              class="btn"
              disabled=${busy || !name.trim()}
              onClick=${() =>
                setConfirm({
                  title: `Create '${name.trim()}'?`,
                  body: 'This station becomes the network\'s only member. The charger reboots to apply it.',
                  confirmLabel: 'Create',
                  run: () => onAction({ action: 'create', name: name.trim() }),
                })}
            >
              Create
            </button>
            <button
              class="btn"
              disabled=${busy || !name.trim()}
              onClick=${() =>
                setConfirm({
                  title: `Join '${name.trim()}'?`,
                  body: 'The other members on the LAN are found and told. The charger reboots to apply it.',
                  confirmLabel: 'Join',
                  run: () => onAction({ action: 'join', name: name.trim() }),
                })}
            >
              Join
            </button>
          </div>`)}
    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  <//>`;
}

export function Charging({ api, readOnly, busy, toast }) {
  const onLbLoad = () => api.get('/lb');
  const onLbWrite = (payload) =>
    api
      .post('/lb', payload)
      .then((doc) => {
        toast.ok('Load balancing written.');
        /* The reply is the charger's new answer, so the store takes it:
         * the solar card beside this one, and the summary on the
         * dashboard, both move without reading the charger again. */
        if (doc?.loadbalancing) putPanel('lb', doc);
        return doc;
      })
      .catch((err) => {
        toast.error(err.message);
        throw err;
      });

  const onProfilesLoad = () => api.get('/profiles');
  const onDirectLoad = () => api.get('/direct-start');
  const onScnLoad = () => api.get('/scn');
  const installUk = () =>
    api
      .post('/profiles', { action: 'install-uk' })
      .then((doc) => toast.ok(doc.message || 'Profile installed.'))
      .catch((err) => toast.error(err.message));
  const clearProfile = (id) =>
    api
      .post('/profiles', { action: 'clear', id })
      .then((doc) => toast.ok(doc.message || 'Profile cleared.'))
      .catch((err) => toast.error(err.message));
  const writeDirectStart = (payload) =>
    api
      .post('/direct-start', payload)
      .then(() => toast.ok('Profile override written.'))
      .catch((err) => toast.error(err.message));
  const scnAction = (payload) =>
    api
      .post('/scn', payload)
      .then((doc) => toast.ok(doc.message || 'Done.'))
      .catch((err) => toast.error(err.message));

  return html`<div class="grid">
    <${Balancing} readOnly=${readOnly} busy=${busy} onLoad=${onLbLoad} onWrite=${onLbWrite} />
    <${Limits} readOnly=${readOnly} busy=${busy} onLoad=${onLbLoad} onWrite=${onLbWrite} />
    <${Solar} readOnly=${readOnly} busy=${busy} onLoad=${onLbLoad} onWrite=${onLbWrite} />

    <${Scn}
      readOnly=${readOnly}
      busy=${busy}
      onLoad=${onScnLoad}
      onAction=${scnAction}
    />
    <${Profiles}
      readOnly=${readOnly}
      busy=${busy}
      onLoad=${onProfilesLoad}
      onInstallUk=${installUk}
      onClear=${clearProfile}
    />
    <${DirectStart}
      readOnly=${readOnly}

      busy=${busy}
      onLoad=${onDirectLoad}
      onWrite=${writeDirectStart}
    />
  </div>`;
}
