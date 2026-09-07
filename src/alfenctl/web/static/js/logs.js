/* The charger's event log, with an optional follow.
 *
 * The charger has no streaming endpoint: following means re-reading its
 * newest page and dropping what we have already shown, which the server
 * does on the live-refresh beat.  If the charger logged faster than we
 * polled, the server says so rather than letting the gap pass silently.
 *
 * This used to be a radio button inside a "History" tab, which is a poor
 * place for the one thing that answers "why did it stop at three in the
 * morning".  It is a tab, and it can now page backwards as far as the
 * charger's buffer goes rather than showing only the newest page.
 */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { Progress, Select } from './ui.js';

const KINDS = ['', 'ERROR', 'WARNING', 'INFO', 'USER', 'CHARGING'];

/* How far back the "read further back" control offers to go, in the
 * spellings `logs.parse_since` already takes from `alfenctl logs --since`. */
const SPANS = [
  { value: '', title: 'the newest page' },
  { value: 'today', title: 'since midnight' },
  { value: '24h', title: 'the last 24 hours' },
  { value: '7d', title: 'the last 7 days' },
  { value: 'all', title: 'everything the charger kept' },
];

/* How many lines are drawn at once.
 *
 * The page holds far more than this (see MAX_LOG_LINES in app.js) -- a
 * week of a busy charger is tens of thousands -- and drawing them all is
 * seconds of layout for lines nobody scrolls to.  So the newest of them
 * are drawn and the count below says how many there are, which is the
 * honest version of what this used to do silently.
 */
const DRAWN = 2000;

export function Logs({ lines, follow, onFollow, onReload, onSince, busy, loading, link }) {
  const [kind, setKind] = useState('');
  const [needle, setNeedle] = useState('');
  const [span, setSpan] = useState('');
  const [stick, setStick] = useState(true);
  const box = useRef(null);

  useEffect(() => {
    if (stick && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines, stick]);

  const wanted = needle.trim().toLowerCase();
  const matching = (lines || []).filter(
    (line) =>
      (!kind || line.kind === kind) &&
      (!wanted || (line.text || '').toLowerCase().includes(wanted))
  );
  const shown = matching.slice(-DRAWN);

  const save = () => {
    const text = matching
      .map((line) => `${(line.time || '').replace('T', ' ')} ${line.kind || ''} ${line.text}`)
      .join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([`${text}\n`], { type: 'text/plain' }));
    a.download = 'charger.log';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return html`<div>
    <div class="toolbar">
      <button class="btn" disabled=${busy || loading} onClick=${onReload}>
        ${loading ? 'Reading...' : 'Read the newest page'}
      </button>
      <${Select}
        value=${span}
        disabled=${loading}
        onChange=${(event) => {
          const asked = event.target.value;
          setSpan(asked);
          if (asked) onSince(asked);
        }}
        entries=${SPANS}
      />
      <label class="toggle">
        <input type="checkbox" checked=${follow} onChange=${(e) => onFollow(e.target.checked)} />
        follow
      </label>
      <${Select}
        value=${kind}
        onChange=${(e) => setKind(e.target.value)}
        entries=${KINDS.map((name) => ({ value: name, title: name || 'every kind' }))}
      />
      <input
        type="search"
        placeholder="find in these lines"
        class="grow"
        value=${needle}
        onInput=${(e) => setNeedle(e.target.value)}
      />
      <label class="toggle">
        <input type="checkbox" checked=${stick} onChange=${(e) => setStick(e.target.checked)} />
        stick to the end
      </label>
      <button class="btn ghost" disabled=${!matching.length} onClick=${save}>Save</button>
      <span class="spacer"></span>
      <span class="muted small">
        ${matching.length > shown.length
          ? `newest ${shown.length} of ${matching.length} lines`
          : `${matching.length} lines`}
      </span>
    </div>

    <${Progress} link=${link} what="Reading the event log" />

    <div class="logs" ref=${box}>
      ${shown.length === 0
        ? html`<div class="empty">
            ${(lines || []).length === 0
              ? 'No log lines yet.'
              : 'Nothing in the log matches.'}
          </div>`
        : shown.map(
            (line, index) => html`<div class=${`logline ${line.kind || ''}`} key=${line.id ?? index}>
              <span class="ts">${(line.time || '').replace('T', ' ').slice(0, 19) || ''}</span>
              <span class="msg">${line.text}</span>
            </div>`
          )}
    </div>
  </div>`;
}

export function logGapNote() {
  return {
    id: null,
    time: null,
    kind: 'gap-note',
    text: '... lines were logged faster than we could read them ...',
  };
}
