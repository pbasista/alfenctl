/* The charger connection, as one control in the header.
 *
 * This is the one widget on the page that is about a charger rather than
 * about a device in general: it wears the states `web/session.py` names,
 * it counts the browsers watching the same station, and it keeps the
 * history of what the link has done.  Everything else the header draws --
 * the live switch, the offline notice, the toasts -- is shared, and comes
 * from /core/js/ui.js.
 */

import { Watching } from '/core/js/shell.js';
import { Chev, span, usePopover } from '/core/js/ui.js';
import { html } from '/core/vendor/preact-htm.module.js';

/* What the link is doing, in the words the pill wears.
 *
 * Split out from the pill itself because two things show it: the pill in
 * the header, and the menu that opens under it, which repeats the state as
 * its own heading. */
function linkFace(link) {
  const state = link?.state || 'released';
  const labels = {
    released: 'released',
    opening: 'connecting',
    idle: 'connected, idle',
    busy: 'busy',
    error: 'error',
  };
  const percent =
    link && link.progress !== null && link.progress !== undefined
      ? ` ${Math.round(link.progress * 100)}%`
      : '';
  const detail =
    state === 'busy' || state === 'opening'
      ? (link.op || '') + percent
      : state === 'error'
        ? link.error
        : state === 'idle' && link.releaseIn !== null && link.releaseIn !== undefined
          ? `releases in ${Math.ceil(link.releaseIn)}s`
          : state === 'released'
            ? 'charger is free'
            : '';
  return { state, label: labels[state] || state, detail };
}

/* One finished operation, in the words the history uses for it. */
function said(item) {
  return `${item.op}${item.detail ? ` -- ${item.detail}` : ''}`;
}

/* The connection, as one control.
 *
 * This used to be a pill in the header and a bar under the tabs holding
 * four more things -- the live toggle, connect, release, and who else was
 * watching -- which is a whole row of chrome spent on controls nobody
 * touches twice an hour, sitting above the content they were there to look
 * at.  The pill was already the one place that says what the connection is
 * doing, so it is the place the rest belongs: it opens, and everything
 * about the link is in the one menu -- including the history of what the
 * link has done, which is longer than a bar could ever have shown.
 *
 * A refresh nobody asked for still shows on the face of it -- this is the
 * one place that says what the connection is doing -- but wearing the
 * colours of a link at rest; see the `.pill.busy.quiet` rule.
 */
export function ConnectionPill({
  link,
  activity,
  offline,
  onConnect,
  onRelease,
  onWatchers,
}) {
  const menu = usePopover();
  const { state, label, detail } = linkFace(link);
  const calm = link?.quiet ? ' quiet' : '';
  const clients = link?.clients || 1;
  const items = activity || [];
  const now = Date.now() / 1000;

  return html`<div class=${`anchor conn${menu.open ? ' open' : ''}`} ref=${menu.box}>
    <button
      type="button"
      ref=${menu.trigger}
      class=${`pill ${offline ? 'gone' : state}${calm}`}
      title=${detail}
      aria-expanded=${menu.open}
      aria-haspopup="dialog"
      aria-label=${`the charger connection: ${offline ? 'the server is not answering' : label}`}
      onClick=${menu.toggle}
    >
      <span class="dot"></span>
      <span class="label">${offline ? 'server unreachable' : label}</span>
      ${!offline && detail && html`<span class="pill-op">${detail}</span>`}
      ${!offline &&
      link &&
      link.queued > 0 &&
      html`<span class="queued">${link.queued} waiting</span>`}
      <${Chev} down />
    </button>

    ${menu.open &&
    html`<div class="menu conn-menu" role="dialog" aria-label="The charger connection">
      <div class="conn-head">
        <span class="what">${label}</span>
        ${detail && html`<span class="muted">${detail}</span>`}
      </div>

      <div class="conn-live muted">
        ${link?.live
          ? `Live updates on -- reading every ${link?.pollInterval || 3}s.`
          : 'Live updates paused.'}
        ${' '}Switched beside this pill.
      </div>

      <div class="actions">
        <button
          class="btn small"
          disabled=${offline || link?.state === 'released'}
          onClick=${() => {
            menu.close();
            onRelease();
          }}
        >
          Release
        </button>
        <button
          class="btn small"
          disabled=${offline || (link?.state !== 'released' && link?.state !== 'error')}
          onClick=${() => {
            menu.close();
            onConnect();
          }}
        >
          Connect
        </button>
        <span class="spacer"></span>
        <!-- The list opens over the menu and leaves it open: the menu is
             where it was asked for, and closing the list goes back to it. -->
        <${Watching} clients=${clients} onOpen=${onWatchers} />
      </div>

      <div class="conn-past">
        <div class="past-head">
          <!-- "What the connection has done" -- a sentence where the two
               lines under it want a label.  The list says what it holds;
               the heading only has to name it. -->
          <span>Activity</span>
          <span class="muted">${items.length} in this session</span>
        </div>
        ${items.length === 0
          ? html`<div class="muted">Nothing yet.</div>`
          : html`<div class="past-list">
              ${items.map(
                (item) => html`<div
                  class=${`deed${item.ok ? '' : ' bad'}`}
                  key=${`${item.at}-${item.op}`}
                >
                  <span class="op" title=${said(item)}>${said(item)}</span>
                  <span class="when">${span(Math.max(0, now - item.at))} ago</span>
                  <span class="ms">${span(item.seconds)}</span>
                </div>`
              )}
            </div>`}
      </div>
    </div>`}
  </div>`;
}
