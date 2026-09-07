/* The property browser and editor.
 *
 * The server sends each property already merged with the EDS catalog, so a
 * row knows its own title, unit, type and -- for an enumerated one -- its
 * options.  That is what lets this be a real editor rather than a grid of
 * numbers: an enum gets a dropdown of names, everything else gets an input,
 * and read-only rows are simply not editable.
 *
 * What a row leads with is the catalog's words for the property -- "Maximum
 * Station Current", not `sysMaxStationCurrent` and certainly not `2062_0`.
 * The table used to lead with the parameter name, which for two properties
 * in three is the id again, so a page of it said nothing about what any of
 * it was.  Where the catalog does describe a property the title is the
 * heading, the parameter name and id are underneath it for the id-shaped
 * questions, and an enumerated value is shown as the word the catalog gives
 * it with the stored number beside it.  Where it does not -- the vendor's
 * own EDS covers about a third of what a charger answers with -- the row
 * carries a "purpose unknown" badge instead of a name nobody has.
 */

import { html, useEffect, useMemo, useState } from '../vendor/preact-htm.module.js';
import { BackupBar } from './backup.js';
import { Card, DASH, Progress, Select } from './ui.js';


/* What a row says when neither the vendor's catalog nor this program's own
 * glossary has a name for the property: the register's purpose is unknown
 * to every source, said as a badge on the row rather than a dash whose
 * sentence only appears on hover.  The count above the table says it once
 * more, and the "described only" checkbox hides these rows. */
const UNDESCRIBED = "purpose unknown";

/* How long a freshly-read row stays marked.  Long enough to find with the
 * eye, short enough that a second read is obviously a second read. */
const FLASH_MS = 4000;

function Editor({ prop, onSave, onCancel, busy }) {
  const [value, setValue] = useState(prop.value === null ? '' : String(prop.value));
  const save = () => onSave(prop.id, value);
  const onKey = (event) => {
    if (event.key === 'Enter') save();
    if (event.key === 'Escape') onCancel();
  };
  return html`<div class="actions-row">
    ${prop.options?.length
      ? html`<${Select}
          value=${value}
          onChange=${(e) => setValue(e.target.value)}
          onKeyDown=${onKey}
          entries=${prop.options.map((option) => ({
            value: String(option.value),
            title: `${option.title || option.value} (${option.value})`,
          }))}
        />`
      : html`<input
          type="text"
          autofocus
          value=${value}
          maxlength=${prop.length || undefined}
          onInput=${(e) => setValue(e.target.value)}
          onKeyDown=${onKey}
        />`}
    <button class="btn small primary" disabled=${busy} onClick=${save}>Save</button>
    <button class="btn small ghost" onClick=${onCancel}>Cancel</button>
  </div>`;
}

/* Is this value read as a quantity or as a word?  Numbers line up on their
 * right-hand edge with the numbers above and below them; text does not. */
function isNumeric(prop) {
  return typeof prop.value === 'number' && !prop.options?.length;
}

/* One property, said in the order a reader wants it: what it is, then what
 * it is called, then what it is called by the protocol.
 *
 * Editing one opens a second row under it rather than replacing the value
 * in place.  A table's columns are as wide as their widest cell, and an
 * editor is a dropdown and two buttons where a reading is "16" -- so
 * clicking Edit on one row widened the value column for the whole table
 * and shoved four hundred other rows sideways, then shoved them back on
 * Cancel.  Underneath, in a cell that spans every column, the editor
 * belongs to no column and changes none of them; and the value it is
 * replacing stays on screen above it, which is what you are changing it
 * from.  It is the shape the sessions table already opens a summary row
 * with. */
function PropRow({ prop, busy, readOnly, editing, fresh, onEdit, onSave, onCancel }) {
  const heading = prop.title || (prop.known ? prop.name : '');
  const under = [prop.known && prop.name !== heading ? prop.name : '', prop.id]
    .filter(Boolean)
    .join('  ·  ');
  return html`<tr class=${`${fresh ? 'arrived' : ''}${editing ? ' editing' : ''}`}>
    <td class="name">
      ${heading
        ? html`<div class="prop-name">${heading}</div>`
        : html`<span
            class="badge warn"
            title="not in the vendor's catalog, its apps, or this program"
            aria-label=${UNDESCRIBED}
          >
            ${UNDESCRIBED}
          </span>`}
      <div class="prop-title data">${under}</div>
      ${prop.category && html`<span class="badge cat">${prop.category}</span>`}
    </td>
    <td class=${`val${isNumeric(prop) ? ' num' : ''}`}>
      <span>${prop.display || DASH}</span>
      ${prop.unit && html`<span class="muted"> ${prop.unit}</span>`}
      ${prop.meaning && html`<div class="prop-title">${prop.meaning}</div>`}
    </td>
    <td class="type muted">${prop.type}</td>
    <td class="right">
      ${prop.writable
        ? !readOnly &&
          !editing &&
          html`<button class="btn small ghost" onClick=${onEdit}>Edit</button>`
        : html`<span class="badge ro">ro</span>`}
    </td>
  </tr>
  ${editing &&
  html`<tr class="editor">
    <td colspan="4">
      <${Editor} prop=${prop} busy=${busy} onSave=${onSave} onCancel=${onCancel} />
    </td>
  </tr>`}`;
}

/* The state that outlives the tab.
 *
 * Everything here used to be this component's own, which meant switching to
 * the log and back threw away the rows the charger had just been read for
 * and asked it for its category list again -- a second of reflow, and a
 * hold of the one connection, to arrive back where you already were.  It
 * lives in `App` now and arrives as `state`; only what is true while the
 * tab is on screen -- which row is being edited, whether a read is in
 * flight -- is still local.  `app.js` clears it when the station changes.
 */
export const EMPTY_PROPERTIES = {
  categories: [],
  properties: null,
  category: 'generic',
  filter: '',
  writableOnly: false,
  namedOnly: false,
};

export function Properties({
  state,
  onState,
  onLoad,
  onWrite,
  onCategories,
  readOnly,
  busy,
  toast,
  api,
  link,
}) {

  const { categories, properties, category, filter, writableOnly, namedOnly } = state;
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(false);
  /* Which rows the last read brought in.  Local rather than in `state`:
   * it is true for four seconds and about this visit, not about the
   * station. */
  const [arrived, setArrived] = useState(null);
  const patch = (fields) => onState((current) => ({ ...current, ...fields }));

  useEffect(() => {
    if (!arrived) return undefined;
    const timer = setTimeout(() => setArrived(null), FLASH_MS);
    return () => clearTimeout(timer);
  }, [arrived]);

  /* Once per station, not once per visit: the list only changes when the
   * charger does, and `app.js` empties it when one is picked. */
  useEffect(() => {
    if (categories.length) return undefined;
    let alive = true;
    onCategories()
      .then((names) => alive && patch({ categories: names }))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [categories.length]);

  const load = async (which) => {
    setLoading(true);
    setEditing(null);
    try {
      const rows = await onLoad(which === 'all' ? '' : which);
      /* A read refreshes what it covers; it does not clear the rest.
       * Reading a second category used to throw the first one's rows
       * away, so comparing two categories meant reading them over and
       * over.  A row read again replaces its old value; what this read
       * did not mention, an earlier read did. */
      onState((current) => {
        const known = current.properties || [];
        const seen = new Set(rows.map((row) => row.id));
        /* What this read found goes to the top, in the order the charger
         * answered, and what an earlier read found stays underneath it.
         * Appending put a hundred fresh rows below whatever was already
         * there, so the answer to "did that do anything" was somewhere off
         * the bottom of the page.  Rows this read covers again are
         * replaced by their new values rather than kept twice. */
        return {
          ...current,
          properties: [...rows, ...known.filter((p) => !seen.has(p.id))],
        };
      });
      /* Freshly read, for as long as it takes to notice.  See `.arrived`
       * in app.css: the rows fade from the highlight rather than blinking,
       * and a screen that has asked for less motion gets none. */
      setArrived(new Set(rows.map((row) => row.id)));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  };

  const save = async (id, value) => {
    try {
      const updated = await onWrite([{ id, value }]);
      onState((current) => ({
        ...current,
        properties: (current.properties || []).map(
          (p) => updated.find((u) => u.id === p.id) || p
        ),
      }));
      setEditing(null);
      toast.ok(`${id} written.`);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (properties || []).filter((p) => {
      if (writableOnly && !p.writable) return false;
      if (namedOnly && !p.known) return false;
      if (!needle) return true;
      return (
        p.id.toLowerCase().includes(needle) ||
        p.name.toLowerCase().includes(needle) ||
        (p.title || '').toLowerCase().includes(needle) ||
        (p.meaning || '').toLowerCase().includes(needle) ||
        String(p.value ?? '').toLowerCase().includes(needle)
      );
    });
  }, [properties, filter, writableOnly, namedOnly]);

  const unnamed = (properties || []).filter((p) => !p.known).length;

  return html`<div>
    <div class="toolbar">
      <${Select}
        value=${category}
        onChange=${(e) => patch({ category: e.target.value })}
        entries=${[
          { value: 'all', title: 'every category (slow)' },
          /* The chosen category stands in the list until the real one
           * arrives, so the select is never a lie about what it holds. */
          ...(categories.length === 0 ? [{ value: category, title: category }] : []),
          ...categories.map((name) => ({ value: name, title: name })),
        ]}
      />
      <button class="btn primary" disabled=${loading || busy} onClick=${() => load(category)}>
        ${loading ? 'Reading...' : 'Read'}
      </button>
      <input
        type="search"
        placeholder="filter by name, meaning, id or value"
        class="grow"
        value=${filter}
        onInput=${(e) => patch({ filter: e.target.value })}
      />
      <label class="toggle">
        <input type="checkbox" checked=${writableOnly} onChange=${(e) => patch({ writableOnly: e.target.checked })} />
        writable only
      </label>
      <label class="toggle" title="hide the properties of unknown purpose">
        <input type="checkbox" checked=${namedOnly} onChange=${(e) => patch({ namedOnly: e.target.checked })} />
        described only
      </label>
    </div>

    <${Progress} link=${link} what=${['Reading all properties', 'Reading properties']} />

    <!-- Nothing read yet, or nothing matching: a card either way.  Loose
         in the tab, an empty state is a line of grey text above three real
         cards, so the backup card below it reads as the important thing on
         a tab whose whole point is the list that is not there yet.  A card
         that says so is the list, empty. -->
    ${properties === null
      ? html`<${Card} title="Properties">
          <div class="empty">
            Nothing read from this charger yet -- pick a category above and
            read it.<br />
            <span class="note">
              "every category" walks the whole charger and takes a few seconds -- the link
              indicator shows it working.
            </span>
          </div>
        <//>`
      : shown.length === 0
        ? html`<${Card} title="Properties">
            <div class="empty">
              Nothing matches. ${properties.length} propert${properties.length === 1
                ? 'y is'
                : 'ies are'}
              ${' '}read; the filters above are hiding all of them.
            </div>
          <//>`
        : html`<div>
            <div class="muted small count">
              ${shown.length} of ${properties.length} properties${unnamed
                ? ` -- ${unnamed} of them of unknown purpose`
                : ''}
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Property</th>
                    <th>Value</th>
                    <th class="type">Type</th>
                    <th class="right"></th>
                  </tr>
                </thead>
                <tbody>
                  ${shown.map(
                    (prop) => html`<${PropRow}
                      key=${prop.id}
                      prop=${prop}
                      busy=${busy}
                      readOnly=${readOnly}
                      editing=${editing === prop.id}
                      fresh=${Boolean(arrived?.has(prop.id))}
                      onEdit=${() => setEditing(prop.id)}
                      onSave=${save}
                      onCancel=${() => setEditing(null)}
                    />`
                  )}
                </tbody>
              </table>
            </div>
          </div>`}
    <${BackupBar} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} link=${link} />

  </div>`;
}
