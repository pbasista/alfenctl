/* The things you do to a charger, and the jobs some of them become.
 *
 * Firmware and logo uploads hold the one connection for a minute or more,
 * so they answer straight away with a job and report their progress on the
 * event stream -- which is also why the link indicator can show a
 * percentage while they run.
 */

import { html, useState } from '../vendor/preact-htm.module.js';
import { ago, Card, Confirm, Dialog, Help } from './ui.js';

const BYTES_PER_MB = 1048576;

function FileAction({ title, note, accept, label, disabled, onSend, extra }) {
  const [file, setFile] = useState(null);
  return html`<${Card} title=${title}>
    <p class="note">${note}</p>
    <div class="actions-row">
      <input
        type="file"
        accept=${accept}
        onChange=${(e) => setFile(e.target.files[0] || null)}
        class=${`grow${file ? ' chosen' : ''}`}
      />
      ${extra}
      <button
        class="btn primary"
        disabled=${disabled || !file}
        onClick=${() => {
          onSend(file);
          setFile(null);
        }}
      >
        ${label}
      </button>
    </div>
  <//>`;
}

function Jobs({ jobs }) {
  if (!jobs?.length) return null;
  return html`<${Card} title="Jobs" width="wide">
    ${jobs
      .slice()
      .reverse()
      .map(
        (job) => html`<div class=${`job ${job.state}`} key=${job.id}>
          <div class="head">
            <strong>${job.name}</strong>
            <span class=${`badge ${job.state === 'done' ? 'good' : job.state === 'failed' ? 'bad' : 'warn'}`}>
              ${job.state}
            </span>
          </div>
          ${job.message && html`<div class="msg">${job.message}</div>`}
          ${job.error && html`<div class="err">${job.error}</div>`}
          <div class="bar">
            <span style=${`width:${Math.round((job.progress || 0) * 100)}%`}></span>
          </div>
          <div class="msg" style="display:flex;gap:12px">
            <span>${Math.round((job.progress || 0) * 100)}%</span>
            <span>${ago(job.elapsed || 0)}</span>
            ${job.result?.warnings?.map((w) => html`<span class="badge warn" key=${w}>${w}</span>`)}
          </div>
        </div>`
      )}
  <//>`;
}

/* What Alfen publishes for this station, and the file on your disk -- one
 * card, because they end in the same place.  The list is the app's own
 * dialog with its filter kept: an image whose product code does not cover
 * this model, or that needs a stepping-stone release first, is shown but
 * cannot be started from here.  `alfenctl firmware` can still be told to
 * install it, deliberately, from a terminal. */
function Firmware({ onList, onInstallFile, onInstallRelease, disabled }) {
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [all, setAll] = useState(false);
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [confirm, setConfirm] = useState(null);

  const load = async (includeAll) => {
    setLoading(true);
    setError('');
    try {
      setListing(await onList(includeAll));
    } catch (err) {
      setError(err.message);
      setListing(null);
    } finally {
      setLoading(false);
    }
  };

  const releases = listing?.releases || [];
  const best = releases.find((r) => !r.blocked && r.notes.includes('upgrade'));

  return html`<${Card} title="Firmware">
    <${Help} summary="An image is checked against this model and version before anything is sent.">
      Then it is uploaded and installed, which takes several minutes and
      ends in a reboot. An image whose product code does not cover this
      model, or that needs a stepping-stone release first, is listed but
      cannot be started from here.
    <//>

    <div class="toolbar">
      <button class="btn primary" disabled=${loading} onClick=${() => load(all)}>
        ${loading ? 'Asking Alfen...' : listing ? 'Refresh the list' : "List what Alfen publishes"}
      </button>
      <label class="toggle">
        <input
          type="checkbox"
          checked=${all}
          onChange=${(e) => {
            setAll(e.target.checked);
            if (listing) load(e.target.checked);
          }}
        />
        include other models
      </label>
      <span class="spacer"></span>
      ${listing &&
      html`<span class="note flush">
        ${releases.length} for ${listing.model || listing.family} on ${listing.source}
      </span>`}
    </div>

    ${error && html`<div class="card-note">${error}</div>`}

    ${listing &&
    (releases.length === 0
      ? html`<div class="empty">
          Nothing published for this model. Turn on "include other models" to see the rest.
        </div>`
      : html`<div class="scroller">
          ${releases.map(
            (release) => html`<div
              class=${`entry${release === best ? ' best' : ''}${release.blocked ? ' blocked' : ''}`}
              key=${release.name}
            >
              <div class="head">
                <span class="name data">${release.name}</span>
                ${release === best && html`<span class="badge good">next release</span>`}
                <span class="act">
                  <button
                    class="btn small"
                    disabled=${disabled || release.blocked}
                    title=${release.blocked ? release.warnings.join('; ') : ''}
                    onClick=${() =>
                      setConfirm({
                        title: `Install ${release.name}?`,
                        body:
                          `It is downloaded from ${listing.source}, checked, uploaded and ` +
                          'installed. The charger reboots and is offline for several minutes.',
                        confirmLabel: 'Download and install',
                        danger: true,
                        run: () => onInstallRelease(release.name),
                      })}
                  >
                    Install
                  </button>
                </span>
              </div>
              <div class="meta reason">${release.summary || 'nothing to note'}</div>
              <div class="meta muted">
                ${[
                  release.modified?.slice(0, 10),
                  release.size && `${(release.size / BYTES_PER_MB).toFixed(1)} MB`,
                  release.isBundle && 'zip bundle',
                ]
                  .filter(Boolean)
                  .join(', ')}
              </div>
            </div>`
          )}
        </div>`)}

    <div class="card-foot">
      <input
        type="file"
        accept=".fwi,.fwu,.bin"
        onChange=${(e) => setFile(e.target.files[0] || null)}
        class=${`grow${file ? ' chosen' : ''}`}
      />
      <button
        class="btn"
        disabled=${disabled || !file}
        onClick=${() =>
          setConfirm({
            title: `Install ${file.name}?`,
            body: `${file.name} is checked, uploaded and installed. The charger reboots and is offline for several minutes.`,
            confirmLabel: 'Upload and install',
            danger: true,
            run: () => {
              onInstallFile(file);
              setFile(null);
            },
          })}
      >
        Install
      </button>
    </div>

    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  <//>`;
}

export function Actions({
  jobs,
  display,
  onReboot,
  onTimeSync,
  onLogo,
  onFirmware,
  onFirmwareList,
  onFirmwareRelease,
  onTilt,
  onConsole,
  onConsoleList,
  onErase,
  readOnly,
  busy,
  toast,
}) {
  const [confirm, setConfirm] = useState(null);
  /* A station with no screen accepts the transfer and shows it nowhere, so
   * the button is not offered -- which is what the vendor's own dialog does.
   * `undefined` is "not read yet" rather than "no". */
  const noScreen = display?.present === false;

  if (readOnly) {
    return html`<div class="grid">
      <${Card} title="Actions">
        <div class="empty">
          This server is running read-only, so nothing here could change the
          charger. Start <code>alfenctl ui</code> without --read-only to use it.
        </div>
      <//>
    </div>`;
  }

  return html`<div class="grid">
    <${Card} title="Restart">
      <${Help} summary="Restarts the charger.">
        A car that is charging stops, and the station is unreachable for a
        minute or two while it comes back.
      <//>
      <button
        class="btn danger"
        disabled=${busy}
        onClick=${() =>
          setConfirm({
            title: 'Restart the charger?',
            body: 'Any charging session stops and the station goes offline for a minute or two.',
            confirmLabel: 'Restart',
            danger: true,
            run: onReboot,
          })}
      >
        Restart the charger
      </button>
    <//>

    <${Card} title="Clock">
      <${Help} summary="Sets the charger's clock from this computer.">
        Worth doing before any upload: a firmware image's signature is
        checked against the charger's own idea of the date.
      <//>
      <button class="btn" disabled=${busy} onClick=${onTimeSync}>Sync the clock</button>
    <//>

    <${FileAction}
      title="Splash logo"
      note=${noScreen
        ? 'This station has no display, so there is nowhere to show a logo. ' +
          'alfenctl logo --force sends one from a terminal anyway, which is ' +
          'the only way to find out what a charger really does with it.'
        : "A PNG or JPEG, converted and packaged for this charger's display. " +
          'Needs the Personalized display feature.'}
      accept="image/*"
      label="Upload logo"
      disabled=${busy || noScreen}
      onSend=${onLogo}
    />

    <${Firmware}
      disabled=${busy}
      onList=${onFirmwareList}
      onInstallFile=${onFirmware}
      onInstallRelease=${onFirmwareRelease}
    />

    <${Tilt} onCalibrate=${onTilt} busy=${busy} />

    <${Erase} onErase=${onErase} busy=${busy} />

    <${Jobs} jobs=${jobs} />

    <${Console} onSend=${onConsole} onList=${onConsoleList} busy=${busy} toast=${toast} />

    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  </div>`;
}

/* --- maintenance: tilt, console, erase -------------------------------------------------- */

function Tilt({ onCalibrate, busy }) {
  const [confirm, setConfirm] = useState(null);
  return html`<${Card} title="Tilt sensor">
    <${Help} summary="Stores where the charger stands right now as upright.">
      A pedestal charger reports being knocked over by comparing itself
      against three stored setpoints. Only worth doing once it is installed
      and standing as it is going to stand.
    <//>
    <button
      class="btn"
      disabled=${busy}
      onClick=${() =>
        setConfirm({
          title: 'Calibrate the tilt sensor?',
          body: "The charger's current position becomes its definition of level.",
          confirmLabel: 'Calibrate',
          run: onCalibrate,
        })}
    >
      Calibrate
    </button>
    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  <//>`;
}

function Console({ onSend, onList, busy, toast }) {
  const [command, setCommand] = useState('');
  /* The table, and the sentence saying why two thirds of it is blank.
   * Both come from the server, which takes them from the CLI's own table
   * -- the same words in the terminal and here, rather than the same
   * words twice in two languages. */
  const [commands, setCommands] = useState(null);
  const [note, setNote] = useState('');
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(null);
  /* The table of known commands opens over the page rather than inside
   * the card.  In the card it was twenty-two rows of three columns
   * appearing under two controls, so the card became a row wide -- and a
   * card that claims the row ends it for every card after it, which
   * rearranged the whole tab on the way to answering "what can I type
   * here". */
  return html`<${Card} title="Console">
    <${Help} summary="The charger's own command console -- it validates nothing.">
      The vendor app's Command Window, in other words. A wrong command can
      disrupt charging or the configuration, and nothing here will stop
      you: prefer the buttons elsewhere on this page where there are any.
    <//>
    <div class="actions-row">
      <input
        type="text"
        placeholder="console command"
        class="grow"
        value=${command}
        disabled=${busy}
        onInput=${(e) => setCommand(e.target.value)}
      />
      <button
        class="btn"
        disabled=${busy || !command.trim()}
        onClick=${() =>
          setConfirm({
            title: `Send '${command.trim()}'?`,
            body: 'The console accepts anything and validates nothing.',
            confirmLabel: 'Send',
            run: () => onSend(command.trim()),
          })}
      >
        Send
      </button>
      <button
        class="btn ghost icon"
        disabled=${busy}
        aria-haspopup="dialog"
        aria-expanded=${open}
        title="What commands does this console take?"
        aria-label="the commands this console is known to take"
        onClick=${() => {
          if (commands) {
            setOpen(!open);
            return;
          }
          onList()
            .then((doc) => {
              setCommands(doc.commands || []);
              setNote(doc.note || '');
              setOpen(true);
            })
            .catch((err) => toast.error(err.message));
        }}
      >
        ?
      </button>
    </div>
    ${open &&
    commands &&
    html`<${Dialog}
      title="What this console is known to take"
      width=${760}
      onClose=${() => setOpen(false)}
    >
      ${note && html`<p class="note flush">${note}</p>`}
      <div class="table-wrap" style="max-height:min(56vh,460px)">
        <table>
          <thead>
            <tr>
              <th>What it does</th>
              <th>Console command</th>
              <th>alfenctl</th>
            </tr>
          </thead>
          <tbody>
            ${commands.map(
              (c) => html`<tr key=${c.command + c.what}>
                <td>${c.what}</td>
                <td class="data">${c.command || html`<span class="muted">unknown</span>`}</td>
                <td>${c.alfenctl || html`<span class="muted">—</span>`}</td>
              </tr>`
            )}
          </tbody>
        </table>
      </div>
    <//>`}
    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  <//>`;
}

function Erase({ onErase, busy }) {
  const [confirm, setConfirm] = useState(null);
  /* The target the API takes, what it is called in a sentence, and what
   * goes when it is erased. */
  const targets = [
    ['settings', 'the settings', 'factory defaults (you may lose contact with the charger)'],
    ['personal-data', 'the personal data', 'RFID tags, transactions and logs'],
    ['transactions', 'the transactions', 'the transaction database'],
  ];
  return html`<${Card} title="Erase">
    <${Help} summary="None of these can be undone.">
      Erasing the settings returns the charger to factory defaults --
      including its network settings, which is how you lose contact with a
      charger you can no longer find.
    <//>
    <!-- One to a row rather than three across.  Three "Erase ..." labels
         do not fit a card's width, so they wrapped to two lines of
         different lengths -- three buttons of the same kind, at three
         different left edges.  Stacked, they are a list of three things
         that can be erased, which is what they are. -->
    <div class="stack buttons-col">
    ${targets.map(([target, named, what]) => html`<button
      key=${target}
      class="btn danger"
      disabled=${busy}
      onClick=${() =>
        setConfirm({
          title: `Erase ${named}?`,
          body: `This erases ${what}.  It cannot be undone.`,
          confirmLabel: `Erase ${named}`,
          danger: true,
          run: () => onErase(target),
        })}
    >
      Erase ${named}
    </button>`)}
    </div>
    ${confirm &&
    html`<${Confirm}
      ...${confirm}
      onCancel=${() => setConfirm(null)}
      onConfirm=${() => {
        const run = confirm.run;
        setConfirm(null);
        run();
      }}
    />`}
  <//>`;
}
