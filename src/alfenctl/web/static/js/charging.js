/* The Charging tab: how the station shares its supply.
 *
 * Load balancing and solar charging (the vendor app's Load balancing
 * panel), the OCPP charging profiles the charger enforces locally, the
 * per-socket direct-start override, and Smart Charging Network
 * membership.  The same modules the CLI drives, over the same one
 * connection, edited as cards with one Apply each.
 */


import { offerWriter, useDraft } from '/core/js/drafts.js';
import { EnumRow, NumRow, panelWait, putPanel, TextRow, ToggleRow, usePanel } from '/core/js/panels.js';
import { Card, Caveats, caller, Row, useConfirm } from '/core/js/ui.js';
import { html, useState } from '/core/vendor/preact-htm.module.js';

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
function useBalancing({ onLoad, scope }) {
  /* Every hook first, and unconditionally.  Preact matches hooks up by the
   * order they are called in, so a `useDraft` sitting below an early
   * return belongs to a different slot on the render that has a document
   * than on the render that did not -- which is a card that quietly wears
   * another card's state the moment its read lands. */
  const panel = usePanel('lb', onLoad);
  const [doc] = panel;
  const draft = useDraft(scope);
  const live = doc?.loadbalancing || {};
  return {
    panel,
    doc,
    draft,
    live,
    opts: live.options || {},
    bounds: live.bounds || {},
    get: (key) => draft.get(key, live[key]),
    set: (key) => (value) => draft.set(key, value),
  };
}

/* The toast belongs to whoever does the writing, and that is `onWrite` --
 * saying it here as well is how one Apply used to raise two identical
 * notices. */
function offerBalancing(scope, title, { busy, readOnly, onWrite }) {
  offerWriter(scope, { title, busy, disabled: readOnly, write: onWrite });
}

function Balancing({ readOnly, busy, onLoad, onWrite }) {
  const { panel, draft, live, opts, get, set } = useBalancing({
    onLoad,
    scope: 'lb:balancing',
  });

  const waiting = panelWait(panel, { title: 'Load balancing', what: 'Reading load balancing...' });
  if (waiting !== undefined) return waiting;

  offerBalancing('lb:balancing', 'Load balancing', { busy, readOnly, onWrite });
  return html`<${Card} title="Load balancing" draft=${draft}>

    <${ToggleRow}
      pending=${draft.has('static')}
      k="Static balancing"
      value=${get('static')}
      onChange=${set('static')}
      disabled=${readOnly || busy}
      label="cap against the feed"
      hint="cap the station when the meter says the supply behind it is loaded"
    />
    <${ToggleRow}
      pending=${draft.has('active')}
      k="Active balancing"
      value=${get('active')}
      onChange=${set('active')}
      disabled=${readOnly || busy}
      label="follow the meter"
      hint="hold the station to whatever the meter is measuring, moment by moment"
    />
    <${EnumRow}
      pending=${draft.has('protocol')}
      k="Meter protocol"
      readOnly=${readOnly}
      value=${get('protocol')}
      table=${opts.protocol}
      onChange=${set('protocol')}
      disabled=${busy}
      includeBlank
    />
    <${EnumRow}
      pending=${draft.has('dataSource')}
      k="Data source"
      readOnly=${readOnly}
      value=${get('dataSource')}
      table=${opts.dataSource}
      onChange=${set('dataSource')}
      disabled=${busy}
      includeBlank
    />
    <${EnumRow}
      pending=${draft.has('measurementIncludesEv')}
      k="Measurement"
      readOnly=${readOnly}
      value=${get('measurementIncludesEv')}
      table=${opts.measurementIncludesEv}
      kind="boolean"
      onChange=${set('measurementIncludesEv')}
      disabled=${busy}
      hint="whether the meter's reading already has the car in it"
    />
    <${Caveats}
      items=${(live.warnings || []).map((w) => ({ short: w, detail: w }))}
    />
  <//>`;
}

/* What the station is held to once it is balancing: the ceiling, the
 * floor it falls back to, and how it is allowed to use its phases. */
function Limits({ readOnly, busy, onLoad, onWrite }) {
  const { panel, draft, live, bounds, get, set } = useBalancing({ onLoad, scope: 'lb:limits' });

  /* The card above reports the *failure* for both of them -- one endpoint
   * saying it twice is one endpoint shouting -- but not the wait.  A card
   * that renders nothing while a read is in flight is a card the grid does
   * not know is coming: three panels behind one read put up one skeleton
   * and then landed as three, and every card below them jumped a row.  A
   * skeleton is a card's way of saying it will be here. */
  const waiting = panelWait(panel, {
    title: 'Current limits and phases',
    what: 'Reading load balancing...',
    quiet: true,
  });
  if (waiting !== undefined) return waiting;

  offerBalancing('lb:limits', 'Current limits and phases', { busy, readOnly, onWrite });
  return html`<${Card} title="Current limits and phases" draft=${draft}>
    <${NumRow}
      pending=${draft.has('maxMeterCurrentA')}
      k="Max meter current"
      readOnly=${readOnly}
      value=${get('maxMeterCurrentA')}
      live=${live.maxMeterCurrentA}
      min=${bounds.maxMeterCurrentA?.min}
      max=${bounds.maxMeterCurrentA?.max}
      unit="A"
      onChange=${set('maxMeterCurrentA')}
      disabled=${busy}
    />
    <${NumRow}
      pending=${draft.has('safeCurrentA')}
      k="Safe current"
      readOnly=${readOnly}
      value=${get('safeCurrentA')}
      live=${live.safeCurrentA}
      min=${bounds.safeCurrentA?.min}
      max=${bounds.safeCurrentA?.max}
      unit="A"
      onChange=${set('safeCurrentA')}
      disabled=${busy}
      hint="what the station falls back to when nothing is managing it"
    />
    <${NumRow}
      pending=${draft.has('maxImbalanceA')}
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
      pending=${draft.has('phaseRotation')}
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
      pending=${draft.has('phaseSwitching')}
      k="Phase switching"
      value=${get('phaseSwitching')}
      onChange=${set('phaseSwitching')}
      disabled=${readOnly || busy}
      label="allow one or three"
      hint="let the station switch between single-phase and multiphase charging"
    />
    <${EnumRow}
      pending=${draft.has('maxAllowedPhases')}
      k="Max allowed phases"
      readOnly=${readOnly}
      value=${get('maxAllowedPhases')}
      table=${{ 1: '1', 3: '3' }}
      onChange=${set('maxAllowedPhases')}
      disabled=${busy}
      includeBlank
    />
  <//>`;
}

/* Solar is the same document as the balancing card above it -- one read of
 * `/lb` answers both, which is why they share the panel store's `lb` key
 * rather than each fetching it.  Two reads of one endpoint over the one
 * charger connection was two waits for one answer, and two copies of it
 * that could disagree. */
function Solar({ readOnly, busy, onLoad, onWrite }) {
  const panel = usePanel('lb', onLoad);
  const [doc] = panel;
  const draft = useDraft('lb:solar');

  const waiting = panelWait(panel, {
    title: 'Solar charging',
    what: 'Reading solar charging...',
  });
  if (waiting !== undefined) return waiting;

  const live = doc.loadbalancing || {};
  if (live.solarMode === null || live.solarMode === undefined) return null;
  const opts = live.options || {};
  const bounds = live.bounds || {};
  const get = (key) => draft.get(key, live[key]);

  const set = (key) => (value) => draft.set(key, value);

  offerBalancing('lb:solar', 'Solar charging', { busy, readOnly, onWrite });

  return html`<${Card} title="Solar charging" draft=${draft}>
    <${EnumRow}
      pending=${draft.has('solarMode')}
      k="Mode"
      readOnly=${readOnly}
      value=${get('solarMode')}
      table=${opts.solarMode}
      onChange=${set('solarMode')}
      disabled=${busy}
      includeBlank
    />
    <${NumRow}
      pending=${draft.has('solarGreenShare')}
      k="Green share"
      readOnly=${readOnly}
      value=${get('solarGreenShare')}
      live=${live.solarGreenShare}
      min=${bounds.solarGreenShare?.min}
      max=${bounds.solarGreenShare?.max}
      unit="%"
      onChange=${set('solarGreenShare')}
      disabled=${busy}
      hint="how much of the available surplus the car may take"
    />
    <${NumRow}
      pending=${draft.has('solarComfortW')}
      k="Comfort level"
      readOnly=${readOnly}
      value=${get('solarComfortW')}
      live=${live.solarComfortW}
      min=${bounds.solarComfortW?.min}
      max=${bounds.solarComfortW?.max}
      step="50"
      unit="W"
      onChange=${set('solarComfortW')}
      disabled=${busy}
      hint="the minimum the charger always allows in comfort mode"
    />
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
  const panel = usePanel('profiles', onLoad);
  const [doc] = panel;
  const confirm = useConfirm();

  const waiting = panelWait(panel, { title: 'Charging profiles', what: 'Reading charging profiles...' });
  if (waiting !== undefined) return waiting;

if (doc.supported === false) {
    return html`<${Card} title="Charging profiles">
      <div class="empty">This charger's firmware does not support charging profiles.</div>
    <//>`;
  }
  const profiles = doc.profiles || [];
  /* Six columns when there are profiles, one sentence when there are not
   * -- and none is the ordinary state of a charger nobody has sent a
   * profile to, so the card is not a row wide by default. */
  return html`<${Card}
    title="Charging profiles"
    width=${profiles.length ? 'full' : undefined}
    immediate=${!readOnly}
  >

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
                        confirm.ask({
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
    html`<div class="actions">
      <button
        class="btn"
        disabled=${busy}
        onClick=${() =>
          confirm.ask({
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
          confirm.ask({
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
    ${confirm.node}
  <//>`;
}

function DirectStart({ readOnly, busy, onLoad, onWrite }) {
  const panel = usePanel('direct-start', onLoad);
  const [doc] = panel;
  const draft = useDraft('direct-start');

  const waiting = panelWait(panel, { title: 'Direct start', what: 'Reading direct start...' });
  if (waiting !== undefined) return waiting;

  const live = doc.directStart || {};
  const overrides = live.overrides || {};
  if (!Object.keys(overrides).length && live.randomDelayS === null) return null;

  const numbers = Object.keys(overrides).sort();

  const get = (n) => draft.get(`socket${n}`, overrides[n]);
  const delay = draft.get('randomDelayS', live.randomDelayS);

  /* The charger takes every socket at once, so the write is the whole
   * card as it stands, not only what was changed in it. */
  offerWriter('direct-start', {
    title: 'Direct start',
    busy,
    disabled: readOnly,
    write: () =>
      onWrite({
        sockets: numbers.map(Number),
        direct: numbers.map((n) => Boolean(get(n))),
        randomDelayS: delay,
      }),
  });

  return html`<${Card} title="Direct start" draft=${draft}>
    <p class="note">
      Let a socket charge despite an installed profile. With no profile
      installed, this changes nothing.
    </p>
    <div class="rows">
      ${numbers.map(
        (n) => html`<${ToggleRow}
          pending=${draft.has(`socket${n}`)}
          key=${n}
          k=${`Socket ${n}`}
          value=${get(n)}
          onChange=${(v) => draft.set(`socket${n}`, v)}
          disabled=${readOnly || busy}
          label=${get(n) ? 'direct start' : 'follow the profile'}
        />`
      )}
      <${NumRow}
        pending=${draft.has('randomDelayS')}
        k="Random delay"
        readOnly=${readOnly}
        value=${delay}
        live=${live.randomDelayS}
        min="0"
        max=${live.maxDelayS}
        unit="s"
        onChange=${(v) => draft.set('randomDelayS', v)}
        disabled=${busy}
        title=${`below ${live.compliantDelayS} s the station is no longer compliant with the UK regulation`}
      />
    </div>
  <//>`;
}

/* --- Smart Charging Network --------------------------------------------------- */

function Scn({ readOnly, busy, onLoad, onAction }) {
  const panel = usePanel('scn', onLoad);
  const [doc] = panel;

  const confirm = useConfirm();
  const [name, setName] = useState('');
  const waiting = panelWait(panel, { title: 'Smart Charging Network', what: 'Reading SCN membership...' });
  if (waiting !== undefined) return waiting;

const scn = doc.scn || {};
  const members = scn.peers || [];

  return html`<${Card} title="Smart Charging Network" immediate=${!readOnly}>
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
        ? html`<div class="actions">
            <button
              class="btn"
              disabled=${busy}
              onClick=${() =>
                confirm.ask({
                  title: `Leave '${scn.name}'?`,
                  body: 'The other members keep their settings; this station charges on its own again.',
                  confirmLabel: 'Leave',
                  run: () => onAction({ action: 'leave' }),
                })}
            >
              Leave the network
            </button>
          </div>`
        : html`<div class="actions">
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
                confirm.ask({
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
                confirm.ask({
                  title: `Join '${name.trim()}'?`,
                  body: 'The other members on the LAN are found and told. The charger reboots to apply it.',
                  confirmLabel: 'Join',
                  run: () => onAction({ action: 'join', name: name.trim() }),
                })}
            >
              Join
            </button>
          </div>`)}
    ${confirm.node}
  <//>`;
}

export function Charging({ api, readOnly, busy, toast }) {
  const call = caller(toast);
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
    call(() => api.post('/profiles', { action: 'install-uk' }), (doc) => doc.message || 'Profile installed.');
  const clearProfile = (id) =>
    call(() => api.post('/profiles', { action: 'clear', id }), (doc) => doc.message || 'Profile cleared.');
  const writeDirectStart = (payload) =>
    call(() => api.post('/direct-start', payload), 'Profile override written.', { raise: true });
  const scnAction = (payload) =>
    call(() => api.post('/scn', payload), (doc) => doc.message || 'Done.');

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
