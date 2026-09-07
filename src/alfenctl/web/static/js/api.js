/* Talking to the alfenctl server: fetch helpers and the event stream.
 *
 * Every write carries the X-Alfen-UI header -- the server refuses POSTs
 * without it, which is what keeps another origin from driving this one
 * through the session cookie.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json', 'X-Alfen-UI': '1' };

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/* Told when a request could not reach the server at all.
 *
 * A refused connection is not a failed operation: it means the program
 * behind this page has gone, and every control on it is about to lie.  The
 * event stream notices too, but only on its own schedule -- a click is
 * often the first thing that finds out, so it says so here rather than
 * raising a toast about "Failed to fetch" and leaving the page looking
 * healthy.  See `useServerLink` in app.js.
 */
const unreachable = new Set();

export function onUnreachable(fn) {
  unreachable.add(fn);
  return () => unreachable.delete(fn);
}

/* True when `fetch` rejected rather than answering: a TypeError, which is
 * the one thing the fetch API throws for "the request never happened".
 * An aborted navigation looks the same and is harmless -- the page is on
 * its way out either way. */
function networkFailure(err) {
  return err instanceof TypeError;
}

async function send(request) {
  try {
    return await request;
  } catch (err) {
    if (!networkFailure(err)) throw err;
    for (const fn of [...unreachable]) fn();
    throw new ApiError('the alfenctl server is not answering', 0);
  }
}

async function unwrap(response) {
  const text = await response.text();
  let doc = null;
  try {
    doc = text ? JSON.parse(text) : null;
  } catch {
    doc = null;
  }
  if (!response.ok) {
    throw new ApiError(doc?.error || text || response.statusText, response.status);
  }
  return doc;
}

export async function get(path, params) {
  const query = params ? `?${new URLSearchParams(params).toString()}` : '';
  return unwrap(await send(fetch(`/api${path}${query}`, { headers: { 'X-Alfen-UI': '1' } })));
}

export async function post(path, body) {
  return unwrap(
    await send(
      fetch(`/api${path}`, {
        method: 'POST',
        headers: JSON_HEADERS,
        body: JSON.stringify(body || {}),
      })
    )
  );
}

export async function upload(path, file, params) {
  const query = new URLSearchParams({ filename: file.name, ...(params || {}) });
  return unwrap(
    await send(
      fetch(`/api${path}?${query.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream', 'X-Alfen-UI': '1' },
        body: file,
      })
    )
  );
}


/* The event stream. One connection for the whole page: the server
 * multiplexes by event name, and browsers only allow a handful of
 * connections per origin anyway. */
export function subscribe(handlers) {
  let source = null;
  let retry = null;

  const open = () => {
    source = new EventSource('/api/events');
    for (const [name, fn] of Object.entries(handlers)) {
      if (name === 'onopen' || name === 'onerror') continue;
      source.addEventListener(name, (event) => {
        try {
          fn(JSON.parse(event.data));
        } catch (err) {
          console.error('bad event payload', name, err);
        }
      });
    }
    source.onopen = () => handlers.onopen?.();
    source.onerror = () => {
      handlers.onerror?.();
      // EventSource reconnects on its own, but not after the server has
      // gone away for good; a slow explicit retry covers a restart.
      if (source.readyState === EventSource.CLOSED && !retry) {
        retry = setTimeout(() => {
          retry = null;
          open();
        }, 3000);
      }
    };
  };

  open();
  return () => {
    if (retry) clearTimeout(retry);
    if (source) source.close();
  };
}
