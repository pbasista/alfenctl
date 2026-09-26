/* Backup, restore, and the presets Alfen publishes.
 *
 * The export is a plain download link (the server streams the file); a
 * restore is uploaded, diffed against the live charger, shown as the same
 * preview the CLI prints, and only written when you say so.  A preset is
 * applied as a job, because the backoffice ones upload through the
 * firmware channel and reboot.
 */

import { download } from '/core/js/api.js';
import { usePanel } from '/core/js/panels.js';
import { Card, caller, Dialog, Help, Progress, Select, useConfirm } from '/core/js/ui.js';
import { html, useState } from '/core/vendor/preact-htm.module.js';

const FORMATS = [
  { value: 'json', title: "JSON (alfenctl's own)" },
  { value: 'xml', title: "XML (the Windows app's settings)" },
  { value: 'exml', title: 'encrypted XML' },
];

function ExportCard({ busy, toast, link }) {
  const [format, setFormat] = useState('json');
  const [writableOnly, setWritableOnly] = useState(false);
  const [loading, setLoading] = useState(false);

  /* The saving itself is `download` in /core/js/api.js -- the fetch, the
   * filename off the reply's own `Content-Disposition`, the blob and the
   * click.  This had written all four out, and so had the other program's
   * settings export; the one thing that is this card's is which backup to
   * ask for. */
  const save = async () => {
    setLoading(true);
    try {
      await download('/api/backup', {
        params: { format, writableOnly: writableOnly ? '1' : '' },
        fallback: `charger.${format}`,
      });
      toast.ok('Backup downloaded.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  };

  return html`<${Card} title="Backup">
    <${Help} summary="Reads every property on the charger and writes it to a file.">
      A JSON backup is the one this program restores, with the card beside
      this. The two XML shapes are what the vendor's Windows app reads and
      writes, for moving a configuration between the two programs.
    <//>
    <div class="actions">
      <${Select}
        value=${format}
        onChange=${setFormat}
        entries=${FORMATS}
        disabled=${loading || busy}
      />
      <label class="toggle">
        <input
          type="checkbox"
          checked=${writableOnly}
          disabled=${busy}
          onChange=${(e) => setWritableOnly(e.target.checked)}
        />
        writable only
      </label>
      <button class="btn primary" disabled=${loading || busy} onClick=${save}>
        ${loading ? 'Reading every property...' : 'Download'}
      </button>
    </div>
    <${Progress} link=${link} what="Reading every property" />
  <//>`;
}

function RestoreCard({ readOnly, busy, api, toast }) {
  const [preview, setPreview] = useState(null);
  const [file, setFile] = useState(null);
  const [working, setWorking] = useState(false);

  const upload = async (theFile, apply) => {
    setWorking(true);
    try {
      const doc = await api.upload('/restore', theFile, apply ? { apply: '1' } : {});
      if (apply) {
        toast.ok(`Applied ${doc.applied} change(s).`);
        setPreview(null);
        setFile(null);
      } else {
        setFile(theFile);
        setPreview(doc);
      }
    } catch (err) {
      toast.error(err.message);
    } finally {
      setWorking(false);
    }
  };

  return html`<${Card} title="Restore">
    <${Help} summary="An uploaded backup is diffed against the charger before anything is written.">
      The difference is shown as a table, and nothing is sent until you say
      so. Properties that identify the device -- serial, identity, MAC, IP,
      licence -- are skipped, because writing another charger's into this
      one is how a station stops being itself.
    <//>
    <div class="actions">
      <input
        type="file"
        accept=".json,.xml,.exml,application/json,application/xml"
        disabled=${readOnly || busy || working}
        onChange=${(e) => {
          const chosen = e.target.files?.[0];
          if (chosen) upload(chosen, false);
          e.target.value = '';
        }}
      />
      ${working && html`<span class="muted">working...</span>`}
    </div>
    ${preview &&
    html`<${Dialog}
      title=${`Apply ${preview.changes.length} change(s)?`}
      onClose=${() => setPreview(null)}
    >
      <div class="table-wrap" style="max-height:300px">
        <table>
          <thead>
            <tr>
              <th>Property</th>
              <th>From</th>
              <th>To</th>
            </tr>
          </thead>
          <tbody>
            ${preview.changes.map(
              (c) => html`<tr key=${c.id}>
                <td class="data">${c.id} ${c.title || c.name || ''}</td>
                <td>${String(c.from)}</td>
                <td>${String(c.to)}</td>
              </tr>`
            )}
          </tbody>
        </table>
      </div>
      ${preview.skippedBound?.length > 0 &&
      html`<p class="note">
        ${preview.skippedBound.length} device-bound propert${preview.skippedBound.length === 1
          ? 'y was'
          : 'ies were'}
        skipped (serial, identity, MAC, IP, licence).
      </p>`}
      ${preview.skippedReadOnly?.length > 0 &&
      html`<p class="note">
        ${preview.skippedReadOnly.length} propert${preview.skippedReadOnly.length === 1
          ? 'y the charger will not take was'
          : 'ies the charger will not take were'}
        skipped (read-only).
      </p>`}
      ${preview.invalid?.length > 0 &&
      html`<p class="note">
        ${preview.invalid.map((bad) => `${bad.id}: ${bad.error}`).join('; ')}
      </p>`}
      ${preview.errors?.length > 0 && html`<p class="note">${preview.errors.join('; ')}</p>`}
      <div class="actions">
        <button
          class="btn primary"
          disabled=${busy || working}
          onClick=${() => upload(file, true)}
        >
          Apply
        </button>
        <button class="btn ghost" onClick=${() => setPreview(null)}>Cancel</button>
      </div>
    <//>`}
  <//>`;
}

/* What one preset holds, before anything is written.
 *
 * Applying one used to be the only way to find out what was in it, which
 * for something that clears the current backoffice settings and reboots
 * the station is the wrong way round.  The server downloads the same file
 * the apply would and says what it would do; a backoffice preset is a
 * signed blob nothing can read, so what it says there is its size and what
 * applying it costs, which is still more than nothing.
 */
function PresetPreview({ preset, doc, error, onClose, onApply, canApply }) {
  const entries = doc?.entries || [];
  return html`<${Dialog} title=${preset.label} onClose=${onClose} width=${720}>
    <p class="note flush">${preset.kind}${doc?.bytes ? ` -- ${doc.bytes} bytes` : ''}</p>
    ${error
      ? html`<div class="empty">${error}</div>`
      : !doc
        ? html`<div class="empty">Fetching the preset...</div>`
        : doc.note
          ? html`<p class="note">${doc.note}</p>`
          : entries.length === 0
            ? html`<div class="empty">This preset sets nothing.</div>`
            : html`<div class="table-wrap" style="max-height:min(52vh,420px)">
                <table>
                  <thead>
                    <tr>
                      ${doc.kind === 'meter-map'
                        ? html`<th>Measurand</th>
                            <th>Register</th>
                            <th>Type</th>
                            <th>Scale</th>`
                        : html`<th>Property</th>
                            <th>Sets it to</th>`}
                    </tr>
                  </thead>
                  <tbody>
                    ${doc.kind === 'meter-map'
                      ? entries.map(
                          (e) => html`<tr key=${`${e.measurand}-${e.register}`}>
                            <td>${e.measurand}</td>
                            <td class="data">${e.register}</td>
                            <td>${e.dataType}</td>
                            <td>${e.factor}</td>
                          </tr>`
                        )
                      : entries.map(
                          (e) => html`<tr key=${e.id}>
                            <td>
                              ${e.title || e.name
                                ? html`<div class="prop-name">${e.title || e.name}</div>`
                                : null}
                              <div class="prop-title data">
                                ${[e.name && e.name !== e.title ? e.name : '', e.id]
                                  .filter(Boolean)
                                  .join('  ·  ')}
                              </div>
                            </td>
                            <td class="val data">${e.value || html`<span class="muted">(empty)</span>`}</td>
                          </tr>`
                        )}
                  </tbody>
                </table>
              </div>`}
    ${canApply &&
    html`<div class="actions">
      <button class="btn primary" onClick=${onApply}>Apply this preset</button>
      <button class="btn ghost" onClick=${onClose}>Close</button>
    </div>`}
  <//>`;
}

function PresetsCard({ readOnly, busy, api, toast }) {
  const call = caller(toast);
  const [doc, loading, error, read] = usePanel('presets', () => api.get('/presets'));
  const [search, setSearch] = useState('');
  const confirm = useConfirm();
  /* Which preset is open, what came back for it, and what went wrong --
   * three pieces of one thing, so one state rather than three that can
   * disagree about which preset they belong to. */
  const [showing, setShowing] = useState(null);

  if (doc === null && !error) {
    return html`<div class="empty">Reading presets...</div>`;
  }

  const presets = (doc?.presets || []).filter(
    (p) =>
      !search.trim() ||
      p.label.toLowerCase().includes(search.trim().toLowerCase()) ||
      p.name.toLowerCase().includes(search.trim().toLowerCase())
  );
  const shown = presets.filter((p) => !p.isBackoffice || search.trim());

  const apply = (preset) =>
    confirm.ask({
      title: `Apply ${preset.label}?`,
      body: preset.isBackoffice
        ? 'This clears the current backoffice settings, uploads the preset, and needs a reboot afterwards.'
        : "The preset's settings are written to the charger.",
      confirmLabel: 'Apply',
      danger: preset.isBackoffice,
      run: () =>
        call(() => api.post('/preset', { name: preset.label }), 'Preset job started.'),
    });

  /* Open the preview, then fill it in.  The dialog goes up on the click
   * rather than after the download, because fetching a preset off Alfen's
   * FTP takes a second or two and a button that does nothing for a second
   * is a button people press twice. */
  const show = (preset) => {
    setShowing({ preset, doc: null, error: '' });
    api
      .get('/preset', { name: preset.label })
      .then((got) => setShowing((open) => (open?.preset === preset ? { ...open, doc: got } : open)))
      .catch((err) =>
        setShowing((open) => (open?.preset === preset ? { ...open, error: err.message } : open))
      );
  };

  /* The row, not two tracks of it.  A preset list is a table of four
   * columns over a search box, and a card two tracks wide ends the row for
   * every card after it -- so it was costing the grid a row either way.
   * Taking the whole row spends that deliberately, and gives the labels --
   * which are long, and are what you search by -- the width to be read. */
  return html`<${Card} title="Presets" width="full">
    <${Help} summary="What Alfen publishes beside its firmware.">
      Property settings, Modbus meter maps, and a preset per backoffice
      operator. A backoffice preset is a signed blob: applying it clears
      the current operator's settings, uploads through the firmware
      channel, and needs a reboot afterwards.
    <//>
    <div class="actions">
      <input
        type="search"
        placeholder=${`search ${doc?.backofficeCount || 0} backoffice presets too`}
        class="grow"
        value=${search}
        onInput=${(e) => setSearch(e.target.value)}
      />
      <button class="btn ghost" disabled=${loading || busy} onClick=${read}>
        ${loading ? 'Reading...' : 'Refresh'}
      </button>
    </div>
    ${error
      ? html`<div class="empty">${error}</div>`
      : shown.length === 0
        ? html`<div class="empty">No presets match.</div>`
        : html`<div class="table-wrap spaced">
            <table>
              <thead>
                <tr>
                  <th>Preset</th>
                  <th>Kind</th>
                  <th>Published</th>
                  <th class="right"></th>
                </tr>
              </thead>
              <tbody>
                ${shown.slice(0, 100).map(
                  (p) => html`<tr key=${p.name}>
                    <td class="data">${p.label}</td>
                    <td>${p.kind}</td>
                    <td>${p.modified || '—'}</td>
                    <td class="right">
                      <button class="btn small ghost" onClick=${() => show(p)}>show</button>
                      ${!readOnly &&
                      html`<button class="btn small" disabled=${busy} onClick=${() => apply(p)}>
                        apply
                      </button>`}
                    </td>
                  </tr>`
                )}
              </tbody>
            </table>
            ${shown.length > 100 &&
            html`<p class="note">...and ${shown.length - 100} more; narrow the search.</p>`}
          </div>`}
    ${showing &&
    html`<${PresetPreview}
      preset=${showing.preset}
      doc=${showing.doc}
      error=${showing.error}
      canApply=${!readOnly}
      onClose=${() => setShowing(null)}
      onApply=${() => {
        const preset = showing.preset;
        setShowing(null);
        apply(preset);
      }}
    />`}
    ${confirm.node}
  <//>`;
}

export function BackupBar({ api, readOnly, busy, toast, link }) {
  return html`<div class="grid spaced">
    <${ExportCard} busy=${busy} toast=${toast} link=${link} />
    ${!readOnly &&
    html`<${RestoreCard} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />`}
    <${PresetsCard} readOnly=${readOnly} busy=${busy} api=${api} toast=${toast} />
  </div>`;
}
