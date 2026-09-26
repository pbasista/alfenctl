/* Talking to the alfenctl server.
 *
 * The transport is shared -- the UI header, the two kinds of failure, the
 * event stream and its slow retry all live in /core/js/api.js, which knows
 * nothing about this program beyond the name it says when the server stops
 * answering.  What is alfenctl's own is the shape the page calls it in:
 * every endpoint under `/api`, a second positional argument that is the
 * query, and an upload that takes a `File` and sends its name along.
 */

import * as core from '/core/js/api.js';

core.configure({ name: 'alfenctl' });

export const onUnreachable = core.onUnreachable;

export function get(path, params) {
  return core.get(`/api${path}`, { params });
}

export function post(path, body) {
  return core.post(`/api${path}`, body || {});
}

/* A file, as bytes with its name in the query -- the server writes the
 * upload out under that name, and a body of octets has nowhere else to
 * carry it. */
export function upload(path, file, params) {
  return core.upload(`/api${path}`, file, {
    params: { filename: file.name, ...(params || {}) },
  });
}

/* The page's one event stream. */
export function subscribe(handlers) {
  return core.subscribe('/api/events', handlers);
}
