/* Being told the page was raised, when you are not looking at the page.
 *
 * Raising a tab from inside it is mostly wishful: `window.focus()` is a
 * silent no-op in Firefox outside a user gesture, and a tab whose title
 * changed is not highlighted, coloured or animated by anything -- the flash
 * is only readable when the strip is short enough to show more than
 * "alfenct...".  A notification is the one signal that leaves the browser
 * altogether, and a click on it *is* a user gesture, so its handler is
 * allowed the `focus()` the event itself is not.
 *
 * It has to be asked for, from a click of your own.  Firefox takes
 * `Notification.requestPermission()` only from a user gesture, and a page
 * that asks the moment it loads is the reason for that rule; a refusal is
 * also remembered by the browser for good.  So nothing here happens until
 * the bell in the header is pressed, and the answer is kept per browser,
 * next to the theme.
 */

import { html, useState } from '../vendor/preact-htm.module.js';

const WANT_KEY = 'alfenctl-notify';

/* Long enough to find on another screen, short enough not to pile up. */
const NOTE_MS = 20000;

/* One tag for everything this page sends, so a second `alfenctl ui`
 * replaces the note the first one left rather than stacking under it. */
const NOTE_TAG = 'alfenctl-focus';

/* Notifications are for secure contexts: this page opened on the machine
 * serving it, or served over https.  Shared over plain http to someone
 * else's machine (`alfenctl ui --listen`), Firefox and Chrome take the
 * question away rather than answer it, and the bell has nothing to offer. */
function supported() {
  return (
    typeof Notification !== 'undefined' &&
    typeof Notification.requestPermission === 'function' &&
    window.isSecureContext !== false
  );
}

function permission() {
  return supported() ? Notification.permission : 'unsupported';
}

function wanted() {
  return localStorage.getItem(WANT_KEY) === '1';
}

/* Show one, and let a click on it do the thing the page may not do itself. */
function show(title, body) {
  try {
    const note = new Notification(title, { body, tag: NOTE_TAG, renotify: true });
    note.onclick = () => {
      /* A click is a user gesture, so this focus() is honoured where the
       * one the focus event tries is quietly dropped. */
      window.focus();
      note.close();
    };
    setTimeout(() => note.close(), NOTE_MS);
    return true;
  } catch {
    /* Android's Chrome sends notifications only through a service worker,
     * which this page has none of.  Nothing to do but leave it to the
     * toast, which the tab shows either way. */
    return false;
  }
}

/* The bell's state and the two things it can do, plus the call the event
 * stream makes when the server says a second `alfenctl ui` wanted this tab.
 *
 * `state` is one of `unsupported` (no notifications in this browser, or not
 * offered on this page), `off`, `on`, or `blocked` -- refused once, which
 * only the browser's own site permissions can undo.
 */
export function useTabAlerts() {
  const [state, setState] = useState(() => {
    const answer = permission();
    if (answer === 'unsupported') return 'unsupported';
    if (answer === 'denied') return 'blocked';
    return answer === 'granted' && wanted() ? 'on' : 'off';
  });

  /* Call this from a click and from nothing else; the browser will not take
   * the question any other way.  Returns what it answered. */
  const enable = async () => {
    let answer;
    try {
      answer = permission() === 'granted' ? 'granted' : await Notification.requestPermission();
    } catch {
      answer = 'unsupported'; /* offered, then refused to be asked */
    }
    if (answer === 'unsupported') {
      setState('unsupported');
      return answer;
    }
    if (answer !== 'granted') {
      setState(answer === 'denied' ? 'blocked' : 'off');
      return answer;
    }
    localStorage.setItem(WANT_KEY, '1');
    setState('on');
    /* One right away: it proves the whole path works, at the moment the
     * question is still in mind, rather than a week later. */
    return show('alfenctl ui', 'Notifications are on. This is what one looks like.')
      ? 'granted'
      : 'unsupported';
  };

  const disable = () => {
    localStorage.removeItem(WANT_KEY);
    setState('off');
  };

  /* Read the wish and the permission afresh rather than closing over
   * `state`: this is called from the event stream's handler, wired up on
   * the first render and remembering nothing since. */
  const notify = () => {
    if (!wanted() || permission() !== 'granted') return false;
    /* You are looking straight at the tab: the toast has already said it. */
    if (document.hasFocus()) return false;
    return show(
      'alfenctl ui was started again',
      'This is the tab it meant -- click here to come back to it.'
    );
  };

  return { state, enable, disable, notify };
}

const BELL_TITLES = {
  off: 'notify me when alfenctl raises this tab',
  on: 'notifications are on -- click to turn them off',
  blocked: 'this browser has blocked notifications for this page',
};

/* The one control, in the header beside the theme: on, off, or blocked and
 * not ours to unblock. */
export function Bell({ alerts, toast }) {
  const state = alerts.state;
  if (state === 'unsupported') return null;
  const click = async () => {
    if (state === 'on') {
      alerts.disable();
      toast.info('Notifications off.');
      return;
    }
    if (state === 'blocked') {
      toast.error(
        'This browser has blocked notifications for this page. Allow them in its site permissions to turn them on.'
      );
      return;
    }
    const answer = await alerts.enable();
    if (answer === 'granted') {
      toast.ok('Notifications on: alfenctl will say when this is the tab it meant.');
    } else if (answer === 'denied') {
      toast.error(
        'Notifications blocked. Only this browser can undo that, in its site permissions.'
      );
    } else if (answer === 'unsupported') {
      toast.error('This browser allows notifications but would not send one.');
    } else {
      toast.info('The browser was not answered, so nothing changed.');
    }
  };
  return html`<button
    class="btn small ghost icon"
    title=${BELL_TITLES[state]}
    aria-label=${BELL_TITLES[state]}
    aria-pressed=${state === 'on'}
    onClick=${click}
  >
    <span aria-hidden="true">${state === 'on' ? '🔔' : '🔕'}</span>
  </button>`;
}
