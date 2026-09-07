/* Small shared pieces: the link indicator, fields, dialogs, toasts. */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';

export const DASH = '—';

/* How long the link has to stay busy before the page treats it as busy.
 *
 * The live refresh holds the connection for as long as a charger takes to
 * answer, several times a minute.  Reacting to that on the beat meant every
 * button on the page went grey and came back every few seconds, which reads
 * as a fault rather than as a refresh.  Work nobody asked for is filtered
 * out by `link.quiet` before it gets here; this is for the rest -- a write
 * that lands in 150 ms should not flicker the page on its way past either.
 */
const BUSY_SETTLE_MS = 400;

export function fmt(value, digits = 1) {
  if (value === null || value === undefined || value === '') return DASH;
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(digits);
  }
  return String(value);
}

/* True once `busy` has held for BUSY_SETTLE_MS, false the moment it drops.
 *
 * Slow one way and immediate the other, deliberately: a control should come
 * back the instant it can be used, and go away only when there is really
 * something to wait for.  Nothing is lost by letting a click through in the
 * meantime -- the server queues every request behind the one connection
 * anyway, and answers it when its turn comes.
 */
export function useSteadyBusy(busy, delay = BUSY_SETTLE_MS) {
  const [steady, setSteady] = useState(false);
  useEffect(() => {
    if (!busy) {
      setSteady(false);
      return undefined;
    }
    const timer = setTimeout(() => setSteady(true), delay);
    return () => clearTimeout(timer);
  }, [busy, delay]);
  return steady;
}

/* A span of time in the largest unit that still says something useful.
 * It measures both how long an operation took (milliseconds, usually) and
 * how long ago it happened (an hour, by the end of a session), so it runs
 * from milliseconds to hours. */
export function ago(seconds) {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

/* `data` marks a value that is read character by character -- an id, a
 * licence key, a timestamp.  Those get fixed-width digits, and the whole
 * value on hover, since a long one wraps rather than being cut off. */
export function Row({ k, v, title, data }) {
  const plain = typeof v === 'string' || typeof v === 'number' ? String(v) : '';
  return html`<div class="row2">
    <div class="k">${k}</div>
    <div class=${`v${data ? ' data' : ''}`} title=${title || plain}>
      ${v === null || v === undefined || v === '' ? html`<span class="muted">${DASH}</span>` : v}
    </div>
  </div>`;
}

/* A setting that is legal but will not do what it looks like -- a socket
 * limit above the station's, sockets that add up past it.  The card has one
 * line for it and the explanation takes three, so the short form is what
 * shows: the whole of it is the hover title, and clicking opens it in place
 * for anyone without a mouse to hover with.
 *
 * The chevron is what says it opens.  It read "why?" -- a word small enough
 * and faint enough to be taken for part of the sentence, which then went
 * away once the line was open, leaving nothing to press to close it again.
 * See `.chev` in app.css. */
export function Caveats({ items }) {
  if (!items?.length) return null;
  return html`<div class="caveats">
    ${items.map(
      (item) => html`<details class="why" key=${item.short || item}>
        <summary title=${item.detail || item}>
          <span class="mark">!</span>
          <span class="short">${item.short || item}</span>
          <span class="chev" aria-hidden="true">▸</span>
        </summary>
        <p>${item.detail || item}</p>
      </details>`
    )}
  </div>`;
}

/* A panel.
 *
 * `width` is one of three, not a spans-everything boolean: the default is
 * one column of the grid, `wide` is two, and `full` is the row.  The
 * boolean it replaced was on eleven cards, which is what made a page of
 * them read as a stack of banners rather than a grid -- so `full` is now
 * for the things that genuinely are a row wide (a table, the log, a list
 * of releases) and `wide` for a form of two columns.  Everything else is
 * one column, and roughly square. */
/* One line about a card, with the rest of what there is to say folded
 * behind it.
 *
 * Half the cards on this page opened with three or four sentences of
 * explanation, which is a paragraph of prose above two controls: it pushes
 * the controls down, it wraps to a different number of lines in every
 * card, and the cards in a row then end at four different heights.  The
 * summary is the one line worth reading every time; the paragraph is
 * worth reading once, so it opens.
 */
export function Help({ summary, children }) {
  if (!children) return html`<p class="note">${summary}</p>`;
  return html`<details class="help">
    <summary>
      <span class="chev" aria-hidden="true">▸</span>
      <span class="short">${summary}</span>
    </summary>
    <p>${children}</p>
  </details>`;
}

export function Card({ title, children, width, actions }) {

  return html`<section class=${`card${width ? ` ${width}` : ''}`}>

    ${title &&
    html`<h2>
      <span>${title}</span><span class="spacer"></span>${actions}
    </h2>`}
    ${children}
  </section>`;
}

/* A popover that belongs to the pointer and the keyboard both: a click
 * anywhere else, or Escape, puts it away.  Returns the open flag, a
 * toggle, the ref to hang on whatever counts as "inside", and the ref for
 * the button that opens it.
 *
 * Closing gives the keyboard back.  Escape used to leave focus on a
 * button that no longer existed, which drops it at the top of the
 * document: the menu is dismissed and the next Tab starts the page over.
 * So the trigger is remembered and refocused, and only when the popover
 * itself had the focus -- closing because a click landed somewhere else
 * must not pull the keyboard away from wherever that click went. */
function usePopover() {

  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const trigger = useRef(null);

  const close = () => {
    if (box.current?.contains(document.activeElement)) trigger.current?.focus();
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return undefined;
    const elsewhere = (event) => {
      if (!box.current?.contains(event.target)) setOpen(false);
    };
    const key = (event) => {
      if (event.key !== 'Escape') return;
      if (box.current?.contains(document.activeElement)) trigger.current?.focus();
      setOpen(false);
    };
    document.addEventListener('mousedown', elsewhere);
    window.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('mousedown', elsewhere);
      window.removeEventListener('keydown', key);
    };
  }, [open]);

  return {
    open,
    box,
    trigger,
    toggle: () => (open ? close() : setOpen(true)),
    close,
  };
}

/* What the link is doing, in the words the pill wears.
 *
 * Split out from the pill itself because two things show it: the pill in
 * the header, and the menu that opens under it, which repeats the state as
 * its own heading. */
function linkFace(link) {
  const state = link?.state || 'released';
  const labels = {
    released: 'released',
    connecting: 'connecting',
    idle: 'connected, idle',
    busy: 'busy',
    error: 'error',
  };
  const percent =
    link && link.progress !== null && link.progress !== undefined
      ? ` ${Math.round(link.progress * 100)}%`
      : '';
  const detail =
    state === 'busy' || state === 'connecting'
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

  return html`<div class=${`conn${menu.open ? ' open' : ''}`} ref=${menu.box}>
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
      <span class="caret" aria-hidden="true">▾</span>
    </button>

    ${menu.open &&
    html`<div class="conn-menu" role="dialog" aria-label="The charger connection">
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

      <div class="actions-row">
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
        <button
          class="btn small ghost"
          onClick=${() => {
            menu.close();
            onWatchers();
          }}
        >
          ${clients} ${clients === 1 ? 'browser' : 'browsers'} watching
        </button>
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
                  class=${`row${item.ok ? '' : ' bad'}`}
                  key=${`${item.at}-${item.op}`}
                >
                  <span class="op" title=${said(item)}>${said(item)}</span>
                  <span class="when">${ago(Math.max(0, now - item.at))} ago</span>
                  <span class="ms">${ago(item.seconds)}</span>
                </div>`
              )}
            </div>`}
      </div>
    </div>`}
  </div>`;
}

/* Live updates, as one switch in the header.
 *
 * This lived in the pill's menu, with Connect, Release and the watcher
 * count, on the reasoning that those are controls nobody touches twice an
 * hour.  That is true of the other three and was never true of this one:
 * it decides whether every number on the page is a reading or a memory,
 * and it is the thing people reach for the moment a charger starts doing
 * something.  It costs one click here and cost two there.
 *
 * A mode rather than an action, so `aria-pressed` rather than a label
 * that changes.  The state is in the shape as well as the colour -- the
 * line is flat when the page is not reading and beats when it is -- so it
 * survives a screen that has no colour to read.
 *
 * It was three arcs rising from a dot, which is the signal-strength mark
 * every phone and laptop draws for a radio: on a page about a charger on
 * a network, beside a Wi-Fi tab, a switch wearing that icon reads as
 * "the link is good", which is a different claim entirely and one this
 * button does not make.  A pulse says what this actually is -- something
 * being read over and over -- and belongs to no other meaning here.
 */
export function LiveToggle({ link, offline, onLive }) {
  const live = Boolean(link?.live);
  const every = link?.pollInterval || 3;
  const title = offline
    ? 'Live updates need the alfenctl server.'
    : live
      ? `Live updates on -- reading the charger every ${every}s. Click to pause.`
      : 'Live updates paused. Click to resume.';
  return html`<button
    type="button"
    class=${`btn small ghost icon live${live ? ' on' : ''}`}
    title=${title}
    aria-label=${title}
    aria-pressed=${live}
    disabled=${offline}
    onClick=${() => onLive(!live)}
  >
    <svg
      viewBox="0 0 16 16"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path class="flat" d="M1.6 8h12.8" />
      <path class="beat" d="M1.6 8h2.6l1.7-4.2L8.9 12.4l1.4-4.4h2.7" />
    </svg>
  </button>`;
}

/* The alfenctl server has gone, and every control on the page is about to
 * lie about a charger it can no longer reach.
 *
 * The page cannot fix that and does not pretend to.  It says which of the
 * two things went -- the server on this machine, not the charger on the
 * wall -- keeps trying, and offers the one thing a person can do about it.
 * Nothing here is dismissible: a banner you can wave away is a banner that
 * stops being true quietly.
 *
 * It sits *in* the header rather than under it.  As its own bar it was a
 * block that appeared and disappeared with the server, and every blip
 * pushed the tabs and the whole page down and back -- movement caused by
 * the one message on the page that is not about the charger.  The header
 * is a flex row with a spacer in it, which on any laptop is hundreds of
 * pixels of slack, and its height is set by the two-line station name, so
 * one line of small text costs nothing.  The pill beside it already reads
 * "server unreachable"; this is the sentence that says which server and
 * what to do.
 *
 * The sentence yields space rather than taking it, and below the narrow
 * breakpoint it goes entirely -- so the announcement is carried by a
 * visually-hidden copy that is always there in full, and the visible text
 * is plain.  Eliding text for the eye must not elide it for a reader.
 */
export function OfflineNotice({ state, onRetry }) {
  if (state !== 'offline' && state !== 'reconnecting') return null;
  const gone = state === 'offline';
  const said = gone
    ? 'The alfenctl server is not answering. Nothing on this page is live.'
    : 'Lost the alfenctl server -- trying to get it back...';
  return html`<div class=${`offline-note${gone ? ' gone' : ''}`}>
    <span class="sr-only" role="alert">${said}</span>
    <span class="dot" aria-hidden="true"></span>
    <span class="what" aria-hidden="true">${said}</span>
    <button class="btn small" onClick=${onRetry}>Try now</button>
  </div>`;
}

/* Something is being read from the charger, and it is taking a while.
 *
 * A read that pages the charger -- the event log, the transaction
 * database, every property for a backup -- holds the one connection for
 * seconds at a time, and the page had nothing to show for it but the
 * pill's "busy", which is also what a 150 ms write looks like.  So the
 * panel that asked draws a bar while its own read is running, with
 * whatever the worker can say about how far it has got.
 *
 * `what` is the beginning of the operation's name, as the worker publishes
 * it (see the `ctx.worker.run` calls in web/api.py): a panel shows the bar
 * for its own read and not for someone else's write going past.  A panel
 * whose read has more than one name -- Properties reads one category or
 * all of them, and the worker says which -- passes an array, so that no
 * panel has to widen its prefix until it matches everybody else's reads
 * too.  `tools/frontlint.py` (C004) checks every name here against the
 * operations web/api.py actually publishes.
 */
export function Progress({ link, what }) {
  const names = what === undefined ? [] : Array.isArray(what) ? what : [what];
  const op = link?.op || '';
  const running =
    link &&
    (link.state === 'busy' || link.state === 'connecting') &&
    !link.quiet &&
    (names.length === 0 || names.some((name) => op.startsWith(name)));
  if (!running) return null;
  const known = link.progress !== null && link.progress !== undefined;
  return html`<div class="reading" role="status">
    <div class="what">
      <span>${link.op || 'Reading the charger'}</span>
      <span class="muted">${link.note || (known ? `${Math.round(link.progress * 100)}%` : '')}</span>
    </div>
    <div class=${`bar${known ? '' : ' unknown'}`}>
      <span style=${known ? `width:${Math.round(link.progress * 100)}%` : ''}></span>
    </div>
  </div>`;
}

export function Confirm({ title, body, confirmLabel, danger, onConfirm, onCancel }) {

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);
  return html`<div class="backdrop" onClick=${(e) => e.target === e.currentTarget && onCancel()}>
    <div class="modal" role="dialog" aria-modal="true">
      <h3>${title}</h3>
      <p>${body}</p>
      <div class="buttons">
        <button class="btn ghost" onClick=${onCancel}>Cancel</button>
        <button class=${`btn ${danger ? 'danger' : 'primary'}`} onClick=${onConfirm}>
          ${confirmLabel || 'Confirm'}
        </button>
      </div>
    </div>
  </div>`;
}

/* A dialog with no decision in it: a title, some content, one way out. */
export function Dialog({ title, children, onClose, width }) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return html`<div class="backdrop" onClick=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="modal" style=${`width:min(${width || 520}px,100%)`} role="dialog" aria-modal="true">
      <h3>${title}</h3>
      ${children}
      <div class="buttons"><button class="btn" onClick=${onClose}>Close</button></div>
    </div>
  </div>`;
}

/* Every notice the page raises, and the one place a screen reader is told
 * about them.  `polite` rather than `assertive`: these report what just
 * happened, and none of them is worth cutting somebody off mid-sentence. */
export function Toasts({ toasts, dismiss }) {
  return html`<div class="toasts" role="status" aria-live="polite">

    ${toasts.map(
      (toast) => html`<div class=${`toast ${toast.kind}`} key=${toast.id}>
        <span>${toast.text}</span>
        <button class="x" title="dismiss" aria-label="dismiss" onClick=${() => dismiss(toast.id)}>
          ×
        </button>

      </div>`
    )}
  </div>`;
}

/* Toast list plus the helpers views use to add to it. */
export function useToasts() {
  const [toasts, setToasts] = useState([]);
  const dismiss = (id) => setToasts((list) => list.filter((t) => t.id !== id));
  const push = (kind, text, linger = 6000) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((list) => [...list, { id, kind, text: String(text) }]);
    if (linger) setTimeout(() => dismiss(id), linger);
  };
  return {
    toasts,
    dismiss,
    ok: (text) => push('ok', text),
    info: (text) => push('info', text),
    error: (text) => push('error', text, 12000),
  };
}

/* A select that does not re-render when nothing about it changed.
 *
 * The page re-renders on every link beat -- once a second while a station
 * is connected -- and each one rebuilt the option vnodes, so the differ
 * rewrote every option's value on the way past.  That is a mutation of the
 * very list a browser's open dropdown is showing, so the popup rebuilt
 * under the pointer and the highlight moved with it: the category
 * dropdown jumped to a different option from time to time, and only while
 * a station was connected, which is the only time the page re-renders on a
 * beat.  Handing the differ back the same vnode it already rendered
 * short-circuits the diff before it reaches the DOM, and the open popup
 * keeps its hover.
 *
 * `entries` is compared by value rather than identity on purpose: callers
 * build it inline, and a stable identity is exactly what a plain array
 * built on render does not have.
 */
export function Select({ value, onChange, entries, disabled }) {
  const prev = useRef(null);
  if (
    !prev.current ||
    value !== prev.current.value ||
    disabled !== prev.current.disabled ||
    !sameEntries(prev.current.entries, entries)
  ) {
    prev.current = {
      value,
      disabled,
      entries,
      /* The change handler in here may go stale while value and entries
       * hold; that is harmless, since every caller's closes over a state
       * setter, which is the same function for the life of the page. */
      /* The whole of what is selected, on hover.  A `<select>` is capped
       * at the width of the column it sits in (see `select` in app.css),
       * so the longest options -- "ask the backoffice, then fall back to
       * the list", "unsecured with basic authentication" -- are cut with
       * an ellipsis, and the pointer is how the rest of one is read. */
      vnode: html`<select
        value=${value}
        onChange=${onChange}
        disabled=${disabled}
        title=${entries.find((e) => e.value === value)?.title || ''}
      >
        ${entries.map((e) => html`<option value=${e.value} key=${e.value}>${e.title}</option>`)}
      </select>`,
    };
  }
  return prev.current.vnode;
}

function sameEntries(a, b) {
  return (
    a.length === b.length &&
    a.every((entry, i) => entry.value === b[i].value && entry.title === b[i].title)
  );
}
