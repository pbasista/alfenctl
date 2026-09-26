/* The Access tab: who may start a session, and who may log in.
 *
 * The authorization settings (the vendor app's Authorization panel), the
 * RFID whitelist the charger consults when no backoffice can answer, the
 * master tag that always authorises, and the passwords and app PIN.
 */

import { offerWriter, useDraft } from '/core/js/drafts.js';
import { EnumRow, Loading, PanelError, panelWait, TextRow, ToggleRow, usePanel } from '/core/js/panels.js';
import { Card, Caveats, Dialog, Help, Row, useConfirm } from '/core/js/ui.js';
import { html, useState } from '/core/vendor/preact-htm.module.js';


/* --- authorization ------------------------------------------------------------ */

function Authorization({ readOnly, busy, onLoad, onWrite }) {
  const panel = usePanel('auth', onLoad);
  const [doc] = panel;
  const draft = useDraft('auth');

  const waiting = panelWait(panel, { title: 'Authorization', what: 'Reading authorization...' });
  if (waiting !== undefined) return waiting;

const live = doc.authorization || {};
  const opts = live.options || {};
  const get = (key) => draft.get(key, live[key]);

  const set = (key) => (value) => draft.set(key, value);

  offerWriter('auth', { title: 'Authorization', busy, disabled: readOnly, write: onWrite });

  return html`<${Card} title="Authorization" draft=${draft}>
    <${EnumRow}
      pending=${draft.has('mode')}
      k="Mode"
      readOnly=${readOnly}
      value=${get('mode')}
      table=${opts.mode}
      onChange=${set('mode')}
      disabled=${busy}
      includeBlank
    />
    <${TextRow}
      pending=${draft.has('plugAndChargeId')}
      k="Plug & charge id"
      readOnly=${readOnly}
      value=${get('plugAndChargeId')}
      live=${live.plugAndChargeId}
      onChange=${set('plugAndChargeId')}
      disabled=${busy}
    />
    <${ToggleRow}
      pending=${draft.has('whitelistEnabled')}
      k="Whitelist"
      value=${get('whitelistEnabled')}
      onChange=${set('whitelistEnabled')}
      disabled=${readOnly || busy}
      label="consult the local tag list"
    />
    <${ToggleRow}
      pending=${draft.has('localListEnabled')}
      k="OCPP local list"
      value=${get('localListEnabled')}
      onChange=${set('localListEnabled')}
      disabled=${readOnly || busy}
      label="consult the backoffice's list"
    />
    <${EnumRow}
      pending=${draft.has('offlineAction')}
      k="Offline action"
      readOnly=${readOnly}
      value=${get('offlineAction')}
      table=${opts.offlineAction}
      onChange=${set('offlineAction')}
      disabled=${busy}
      includeBlank
      hint="what to do when the backoffice cannot be reached"
    />
    <${EnumRow}
      pending=${draft.has('onlineAction')}
      k="Online action"
      readOnly=${readOnly}
      value=${get('onlineAction')}
      table=${opts.onlineAction}
      onChange=${set('onlineAction')}
      disabled=${busy}
      includeBlank
    />
    <${ToggleRow}
      pending=${draft.has('restartAfterOutage')}
      k="Restart after outage"
      value=${get('restartAfterOutage')}
      onChange=${set('restartAfterOutage')}
      disabled=${readOnly || busy}
    />
    <${ToggleRow}
      pending=${draft.has('remoteTxRequests')}
      k="Remote start requests"
      value=${get('remoteTxRequests')}
      onChange=${set('remoteTxRequests')}
      disabled=${readOnly || busy}
    />
    <${ToggleRow}
      pending=${draft.has('stopOnInvalidTag')}
      k="Stop on invalid tag"
      value=${get('stopOnInvalidTag')}
      onChange=${set('stopOnInvalidTag')}
      disabled=${readOnly || busy}
    />
    <${Caveats}
      items=${(live.warnings || []).map((w) => ({ short: w, detail: w }))}
    />
  <//>`;
}

/* --- the whitelist and the master tag ----------------------------------------- */

function Tags({ readOnly, busy, api, toast }) {
  const [doc, loading, error, read] = usePanel('tags', () => api.get('/tags'));
  const confirm = useConfirm();
  const [adding, setAdding] = useState(null);
  const tags = doc?.tags ?? null;

  if (tags === null && !error) {
    return html`<${Loading} loading=${loading} what="Reading the whitelist..." title="RFID whitelist" />`;
  }

  const act = (payload, ok) =>
    api
      .post('/tags', payload)
      .then((doc) => {
        setTags(doc.tags);
        toast.ok(ok);
      })
      .catch((err) => toast.error(err.message));

  /* A tag is an identifier, a word about it, and one button -- which is
   * the shape `.entry` already draws for the browsers watching and for
   * Alfen's releases.  It was a four-column table, and a four-column
   * table is why this card claimed two tracks of the grid; a card two
   * tracks wide ends the row for everything after it.  As a list it is a
   * card like any other, and the tag -- the part anyone reads -- gets the
   * whole width instead of a quarter of it. */
  const expiry = (tag) =>
    tag.expires === '1970-01-01' ? 'never expires' : tag.expires ? `expires ${tag.expires}` : null;

  return html`<${Card}
    title="RFID whitelist"
    immediate=${!readOnly}
    actions=${tags && html`<span class="badge">${tags.length} tag(s)</span>`}
  >

    ${error
      ? html`<${PanelError} error=${error} loading=${loading} onRetry=${read} />`
      : tags === null
        ? html`<${Loading} loading=${loading} what="Reading the whitelist..." title="RFID whitelist" />`
        : tags.length === 0
          ? html`<div class="empty">
              No tags on the whitelist. The charger consults it when no backoffice
              can answer.
            </div>`
          : html`<div class="scroller">
              ${tags.map(
                (t) => html`<div class="entry" key=${t.tag}>
                  <div class="head">
                    <span class="name data">${t.tag}</span>
                    ${!readOnly &&
                    html`<span class="act">
                      <button
                        class="btn small ghost"
                        disabled=${busy}
                        onClick=${() =>
                          confirm.ask({
                            title: `Remove ${t.tag}?`,
                            body: 'The tag no longer authorises a session.',
                            confirmLabel: 'Remove',
                            run: () => act({ action: 'remove', tags: [t.tag] }, 'Tag removed.'),
                          })}
                      >
                        remove
                      </button>
                    </span>`}
                  </div>
                  <div class="meta">
                    ${[t.statusLabel, expiry(t)].filter(Boolean).join(' -- ')}
                  </div>
                </div>`
              )}
            </div>`}
    ${!readOnly &&
    html`<div class="actions">
      <button
        class="btn"
        disabled=${busy || loading}
        onClick=${() =>
          setAdding({
            tag: '',
            expires: '',
          })}
      >
        Add a tag
      </button>
      <button
        class="btn"
        disabled=${busy}
        onClick=${() =>
          confirm.ask({
            title: 'Enrol the next tag presented?',
            body: 'Hold the card to the charger\'s reader now; it will be added.',
            confirmLabel: 'Start learning',
            run: () => act({ action: 'learn' }, 'Learning: hold a card to the reader.'),
          })}
      >
        Learn next tag
      </button>
      ${tags?.length > 0 &&
      html`<button
        class="btn danger"
        disabled=${busy}
        onClick=${() =>
          confirm.ask({
            title: 'Remove every tag?',
            body: 'The whole whitelist is emptied. This cannot be undone.',
            confirmLabel: 'Clear',
            danger: true,
            run: () => act({ action: 'clear' }, 'Whitelist cleared.'),
          })}
      >
        Clear all
      </button>`}
    </div>`}
    ${adding &&
    /* This used to be its own hand-rolled backdrop, on a class no
     * stylesheet ever defined -- so it rendered as an unstyled block
     * pushed into the middle of the card rather than as a dialog.  It is
     * the page's own dialog now, which is also the one that closes on
     * Escape and on a click outside. */
    html`<${Dialog} title="Add a tag" onClose=${() => setAdding(null)} width=${420}>
      <div class="field">
        <span class="lab">Tag id</span>
        <input
          type="text"
          value=${adding.tag}
          onInput=${(e) => setAdding({ ...adding, tag: e.target.value })}
        />
      </div>
      <div class="field">
        <span class="lab">Expires -- YYYY-MM-DD, or empty for never</span>
        <input
          type="text"
          placeholder="never"
          value=${adding.expires}
          onInput=${(e) => setAdding({ ...adding, expires: e.target.value })}
        />
      </div>
      <div class="actions">
        <button
          class="btn primary"
          disabled=${!adding.tag.trim()}
          onClick=${() => {
            const { tag, expires } = adding;
            setAdding(null);
            act(
              { action: 'add', tags: [tag.trim()], expires: expires.trim() || null },
              'Tag added.'
            );
          }}
        >
          Add
        </button>
      </div>
    <//>`}

    ${confirm.node}
  <//>`;
}

function MasterTag({ readOnly, busy, api, toast }) {
  const panel = usePanel('master-tag', () => api.get('/master-tag'));
  const [doc] = panel;
  const [tag, setTag] = useState('');

  const waiting = panelWait(panel, { title: 'Master tag', what: 'Reading the master tag...' });
  if (waiting !== undefined) return waiting;

  const mt = doc.masterTag || {};
  if (mt.supported === false) {
    return html`<${Card} title="Master tag">
      <div class="empty">This charger does not support a master tag.</div>
    <//>`;
  }
  return html`<${Card} title="Master tag" immediate=${!readOnly}>
    <p class="note">One tag that always authorises, whatever the whitelist says.</p>

    <div class="rows">
      <${Row} k="Enabled" v=${mt.enabled ? 'yes' : 'no'} />
      <${Row} k="Tag" v=${mt.tag || '—'} data=${true} />
    </div>
    ${!readOnly &&
    html`<div class="actions">
      <input
        type="text"
        placeholder="tag id"
        style="width:160px"
        value=${tag}
        onInput=${(e) => setTag(e.target.value)}
      />
      <button
        class="btn"
        disabled=${busy || !tag.trim()}
        onClick=${() =>
          api
            .post('/master-tag', { tag: tag.trim() })
            .then(() => {
              toast.ok('Master tag set.');
              read();
              setTag('');
            })
            .catch((err) => toast.error(err.message))}
      >
        Set
      </button>
      ${mt.tag &&
      html`<button
        class="btn ghost"
        disabled=${busy}
        onClick=${() =>
          api
            .post('/master-tag', { tag: '' })
            .then(() => {
              toast.ok('Master tag cleared.');
              read();
            })
            .catch((err) => toast.error(err.message))}
      >
        Clear
      </button>`}
    </div>`}
  <//>`;
}

/* --- passwords and the app PIN -------------------------------------------------- */

function Passwords({ readOnly, busy, api, toast }) {
  const [pw, setPw] = useState('');
  const [hours, setHours] = useState('24');
  const [pin, setPin] = useState('');
  const [code, setCode] = useState('');

  const call = (body, ok) =>
    api
      .post('/password', body)
      .then((doc) => {
        toast.ok(doc.message || ok);
        setPw('');
        setPin('');
        setCode('');
      })
      .catch((err) => toast.error(err.message));

  /* A read-only server says so where the controls would have been.  This
   * used to return nothing at all, so the card was simply absent and the
   * page looked as though this charger had no passwords to set. */
  if (readOnly) {
    return html`<${Card} title="Passwords" actions=${html`<span class="badge">read-only</span>`}>
      <div class="empty">This server cannot change the charger's passwords.</div>
    <//>`;
  }

  return html`<${Card} title="Passwords" immediate>
    <${Help} summary="Firmware 5.0 and later wants a unique per-charger password.">
      Update alfen.toml after changing one, so the next login can use it. A
      temporary password reverts on its own after the hours you name; the
      recovery code is the one printed on the charger itself.
    <//>
    <div class="field">
      <span class="lab">New login password</span>
      <div class="actions">
        <input
          type="text"
          style="width:180px"
          value=${pw}
          disabled=${busy}
          onInput=${(e) => setPw(e.target.value)}
        />
        <button
          class="btn"
          disabled=${busy || !pw}
          onClick=${() => call({ action: 'set', password: pw }, 'Password changed.')}
        >
          Set
        </button>
        <button
          class="btn ghost"
          disabled=${busy || !pw}
          title="a password that reverts after the hours you name"
          onClick=${() =>
            call(
              { action: 'temporary', password: pw, hours: Number(hours) || 24 },
              'Temporary password set.'
            )}
        >
          Set temporary
        </button>
        <input
          type="number"
          style="width:80px"
          min="1"
          max="72"
          value=${hours}
          title="hours until a temporary password reverts"
          onInput=${(e) => setHours(e.target.value)}
        />
      </div>
    </div>
    <div class="field">
      <span class="lab">Recovery -- the code printed on the charger</span>
      <div class="actions">
        <input
          type="text"
          style="width:180px"
          value=${code}
          disabled=${busy}
          onInput=${(e) => setCode(e.target.value)}
        />
        <button
          class="btn ghost"
          disabled=${busy || !code.trim()}
          onClick=${() => call({ action: 'recover', code: code.trim() }, 'Password reset.')}
        >
          Reset to default
        </button>
      </div>
    </div>
    <div class="field">
      <span class="lab">Eve Connect app PIN -- 4 to 6 digits</span>
      <div class="actions">
        <input
          type="text"
          style="width:120px"
          value=${pin}
          disabled=${busy}
          onInput=${(e) => setPin(e.target.value)}
        />
        <button
          class="btn"
          disabled=${busy || !pin.trim()}
          onClick=${() => call({ action: 'pin', pin: pin.trim() }, 'PIN set.')}
        >
          Set PIN
        </button>
        <button
          class="btn ghost"
          disabled=${busy}
          onClick=${() => call({ action: 'pin', pin: '' }, 'App access enabled without a PIN.')}
        >
          No PIN
        </button>
        <button
          class="btn ghost"
          disabled=${busy}
          onClick=${() => call({ action: 'pin' }, 'App access disabled.')}
        >
          Disable app access
        </button>
      </div>
    </div>
  <//>`;
}

export function Access({ api, readOnly, busy, toast }) {
  const writeAuthorization = (payload) =>
    api
      .post('/auth', payload)
      .then(() => toast.ok('Authorization written.'))
      .catch((err) => {
        toast.error(err.message);
        throw err;
      });
  return html`<div class="grid">
    <${Authorization}
      readOnly=${readOnly}
      busy=${busy}
      onLoad=${() => api.get('/auth')}
      onWrite=${writeAuthorization}
    />
    <${Tags} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
    <${MasterTag} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
    <${Passwords} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
  </div>`;
}
