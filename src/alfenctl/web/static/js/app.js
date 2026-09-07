/* The alfenctl web UI.
 *
 * One page, one event stream, one charger connection somewhere behind the
 * server.  Everything the backend learns -- the link state, a status
 * refresh, a job's progress -- arrives as an event and lands in the state
 * here, so two browsers watching the same station stay in step with each
 * other without either of them polling.
 */

import { html, render, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { Access } from './access.js';
import { Actions } from './actions.js';
import * as api from './api.js';
import { Backoffice } from './backoffice.js';
import { Charging } from './charging.js';
import { Dashboard } from './dashboard.js';
import { Logs, logGapNote } from './logs.js';
import { Network } from './network.js';
import { Bell, useTabAlerts } from './notify.js';
import { putPanel, resetPanels } from './panels.js';

import { EMPTY_PROPERTIES, Properties } from './properties.js';
import { Sessions } from './sessions.js';
import {
  ago,
  ConnectionPill,
  Dialog,
  LiveToggle,
  OfflineNotice,
  Toasts,
  useSteadyBusy,
  useToasts,
} from './ui.js';

/* The tabs, in the order someone works down them: what the charger is
 * doing, then what it is set to do, then what it has done, then the two
 * catalogues, then the things you do to it.
 *
 * The log used to be a radio button inside a "History" tab, two clicks
 * from anywhere and invisible until you found it -- which for the one
 * thing that answers "why did it stop charging at 3am" is the wrong place
 * entirely.  It is a tab, beside the sessions it explains. */
const TABS = [
  ['dashboard', 'Dashboard'],
  ['charging', 'Charging'],
  ['sessions', 'Sessions'],
  ['logs', 'Logs'],
  ['access', 'Access'],
  ['network', 'Network'],
  ['backoffice', 'Backoffice'],
  ['properties', 'Properties'],
  ['actions', 'Actions'],
];


/* Where an explicit theme choice is kept, and the key that used to hold it.
 *
 * The old one was written on every load, so every browser that ever opened
 * this page has "dark" stored in it and would never see the system default
 * this version starts from.  A new key retires that; the old one is dropped
 * on the way past. */
const THEME_KEY = 'alfenctl-theme-mode';
const OLD_THEME_KEY = 'alfenctl-theme';

/* system first: a station checked from a laptop in a bright office and one
 * checked from a phone in a dark garage want different pages, and the
 * machine already knows which. */
const THEMES = ['system', 'light', 'dark'];

/* What all three theme marks share: the live switch's box, its stroke
 * weight and its cap -- so the header's icons are one set. */
const THEME_SVG = {
  viewBox: '0 0 16 16',
  width: 15,
  height: 15,
  fill: 'none',
  stroke: 'currentColor',
  'stroke-width': 1.5,
  'stroke-linecap': 'round',
  'stroke-linejoin': 'round',
  'aria-hidden': 'true',
  focusable: 'false',
};

/* The three theme marks, drawn rather than typed.
 *
 * They were the characters U+25D0, U+2600 and U+263E, and a font decides
 * how big a character is: the sun came with its own generous side
 * bearings, the moon was set at cap height beside it, and the half-filled
 * circle standing for "follow the system" was drawn smaller than either.
 * Three buttons of one size holding three marks of three sizes, in a
 * header whose other icon -- the live switch -- is a 15px drawing.  These
 * are that drawing's siblings, at one optical size, with no font in the
 * decision.
 *
 * The system mark is a disc half filled: the two themes in one circle,
 * which says "whichever of them the machine is on" without introducing a
 * third idea for it. */
const THEME_ICON = {
  system: html`<svg ...${THEME_SVG}>
    <circle cx="8" cy="8" r="5.6" />
    <path d="M8 2.4a5.6 5.6 0 0 0 0 11.2z" fill="currentColor" stroke="none" />
  </svg>`,
  light: html`<svg ...${THEME_SVG}>
    <circle cx="8" cy="8" r="3.4" />
    <path
      d="M8 1.1v1.7M8 13.2v1.7M1.1 8h1.7M13.2 8h1.7M3.15 3.15l1.2 1.2M11.65 11.65l1.2 1.2M12.85 3.15l-1.2 1.2M4.35 11.65l-1.2 1.2"
    />
  </svg>`,
  dark: html`<svg ...${THEME_SVG}>
    <path d="M13.4 9.6A5.9 5.9 0 0 1 6.4 2.6a5.9 5.9 0 1 0 7 7z" />
  </svg>`,
};

const LIGHT_QUERY = '(prefers-color-scheme: light)';

/* How many log lines the page holds.
 *
 * A "since 7d" read on a busy charger brings tens of thousands; this is
 * what is kept in memory, and the log tab draws the newest slice of it
 * (see DRAWN in logs.js) while saying how many there are. */
const MAX_LOG_LINES = 40000;


/* How many finished operations the ticker's popover can look back over.
 *
 * The server remembers a dozen, which is all the link event needs to carry
 * several times a second; the page keeps every one it has ever been told
 * about, so an afternoon of work is still there to scroll through. */
const MAX_ACTIVITY = 400;

/* Which operation this is: the instant it finished, which no two share. */
const activityKey = (item) => `${item.at}-${item.op}`;

/* Fold the link event's handful of recent operations into what the page has
 * already seen.  Both lists are newest first, and the ones already known
 * are dropped rather than repeated. */
function rememberActivity(known, arriving) {
  if (!arriving?.length) return known;
  const seen = new Set(known.map(activityKey));
  const fresh = arriving.filter((item) => !seen.has(activityKey(item)));
  return fresh.length === 0 ? known : [...fresh, ...known].slice(0, MAX_ACTIVITY);
}

const TITLE_FLASHES = 6;
const TITLE_FLASH_MS = 700;

/* Someone started `alfenctl ui` again while this tab was already open.  No
 * browser lets a program outside it switch to a tab, so the tab does the
 * switching: it asks for focus -- which some browsers grant and some quietly
 * ignore -- and flashes its own title either way, which is the one signal a
 * background tab can always make.  Neither is worth much in Firefox, which
 * is why `notify.js` offers the notification that is. */
function comeForward() {
  try {
    window.focus();
  } catch {
    /* refused: the title flash below is the fallback, and is what there is */
  }
  const original = document.title;
  let left = TITLE_FLASHES;
  const timer = setInterval(() => {
    document.title = document.title === original ? 'alfenctl is here' : original;
    left -= 1;
    if (left <= 0) {
      clearInterval(timer);
      document.title = original;
    }
  }, TITLE_FLASH_MS);
}

/* The page's theme: the system's, unless this browser has said otherwise.
 *
 * Resolved here rather than in the stylesheet.  `app.css` is dark on `:root`
 * and light behind `[data-theme="light"]`, so answering
 * `prefers-color-scheme` in CSS as well would mean keeping the whole light
 * palette written twice; this stamps the attribute the sheet already reads.
 * The page does not run without JavaScript anyway -- there is a `<noscript>`
 * on it saying so.
 */
function useTheme() {
  const [mode, setMode] = useState(() => {
    const stored = localStorage.getItem(THEME_KEY);
    return THEMES.includes(stored) ? stored : 'system';
  });

  useEffect(() => localStorage.removeItem(OLD_THEME_KEY), []);

  useEffect(() => {
    const media = window.matchMedia(LIGHT_QUERY);
    const stamp = () => {
      document.documentElement.dataset.theme =
        mode === 'system' ? (media.matches ? 'light' : 'dark') : mode;
    };
    stamp();
    if (mode !== 'system') return undefined;
    // Only while following the system is there anything to follow.
    media.addEventListener('change', stamp);
    return () => media.removeEventListener('change', stamp);
  }, [mode]);

  const next = THEMES[(THEMES.indexOf(mode) + 1) % THEMES.length];
  return {
    mode,
    next,
    /* A choice is remembered; the resolved theme is not.  Writing it back on
     * every load is what left every browser pinned to the old default. */
    cycle: () => {
      setMode(next);
      localStorage.setItem(THEME_KEY, next);
    },
  };
}

/* Which tab the address bar is asking for.
 *
 * The tab is in the URL so a reload comes back where you were, and so a
 * link to "the logs on this charger" is a link somebody can send. */
function tabFromHash() {
  const asked = (window.location.hash || '').replace(/^#/, '');
  return TABS.some(([id]) => id === asked) ? asked : TABS[0][0];
}

/* How long a dropped event stream may spend trying before the page calls
 * the server gone.
 *
 * EventSource reconnects on its own within a few seconds, so a server
 * being restarted -- `alfenctl ui` stopped and started again -- comes back
 * inside this and the page never says anything.  Longer than this is a
 * server that is not coming back by itself, which is worth a banner. */
const SERVER_GRACE_MS = 6000;

/* Whether the program behind this page is still there.
 *
 * `connecting` until the stream first opens, then `online`; `reconnecting`
 * the moment anything fails to reach the server, and `offline` if it is
 * still failing when the grace runs out.  A failed fetch counts as well as
 * a dropped stream: a click is often what finds out first, and a page that
 * only listened to the stream would keep taking orders for a charger it
 * cannot reach.
 */
function useServerLink() {
  const [state, setState] = useState('connecting');
  const timer = useRef(null);

  const clear = () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const lost = () => {
    setState((was) => (was === 'offline' ? was : 'reconnecting'));
    if (timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      setState('offline');
    }, SERVER_GRACE_MS);
  };

  const found = () => {
    clear();
    setState('online');
  };

  useEffect(() => api.onUnreachable(lost), []);
  useEffect(() => clear, []);

  return { state, lost, found, offline: state === 'offline' };
}

function StationPicker({ onPick, onClose, toast }) {

  const [stations, setStations] = useState(null);
  const [host, setHost] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    api
      .get('/stations')
      .then(setStations)
      .catch((err) => {
        toast.error(err.message);
        setStations({ configured: [], discovered: [] });
      });
  }, []);

  const all = stations
    ? [...stations.configured, ...stations.discovered.filter(
        (d) => !stations.configured.some((c) => c.host === d.host || c.name === d.name)
      )]
    : [];

  return html`<div class="backdrop" onClick=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="modal" style="width:min(560px,100%)">
      <h3>Choose a station</h3>
      ${stations === null
        ? html`<p>Looking for chargers on this network...</p>`
        : all.length === 0
          ? html`<p>None found by mDNS and none in your config file. Enter an address below.</p>`
          : html`<div class="scroller stack">
              ${all.map(
                (station) => html`<button
                  class="btn pick"
                  key=${station.name + station.host}
                  onClick=${() => onPick({ name: station.name, host: station.host, port: station.port })}
                >
                  <strong>${station.name}</strong>
                  <span class="muted"> ${station.host || ''} · ${station.source}</span>
                </button>`
              )}
            </div>`}
      <div class="field">
        <span class="lab">or an address directly</span>
        <div class="actions-row">
          <input type="text" placeholder="192.168.1.42" class="grow" value=${host} onInput=${(e) => setHost(e.target.value)} />
          <input type="text" placeholder="user" class="grow narrow" value=${username} onInput=${(e) => setUsername(e.target.value)} />
          <input type="password" placeholder="password" class="grow narrow" value=${password} onInput=${(e) => setPassword(e.target.value)} />
        </div>
      </div>
      <div class="buttons">
        <button class="btn ghost" onClick=${onClose}>Cancel</button>
        <button
          class="btn primary"
          disabled=${!host.trim()}
          onClick=${() => onPick({ host: host.trim(), username: username || undefined, password: password || undefined })}
        >
          Connect
        </button>
      </div>
    </div>
  </div>`;
}

/* Who else has this page open.  The link pill counts them because they all
 * share one charger connection; this says which they are, so "someone is
 * holding the station" has a face -- the tab on the next desk, or the phone
 * in the garage. */
function Watchers({ me, onClose, toast }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api
      .get('/clients')
      .then((doc) => setRows(doc.clients))
      .catch((err) => {
        toast.error(err.message);
        setRows([]);
      });
  }, []);

  const now = Date.now() / 1000;
  return html`<${Dialog} title="Browsers watching" onClose=${onClose} width=${560}>
    ${rows === null
      ? html`<p class="note flush">Asking the server...</p>`
      : rows.length === 0
        ? html`<div class="empty">No open event streams.</div>`
        : html`<div class="scroller">
            ${rows.map(
              (row) => html`<div class=${`entry${row.id === me ? ' you' : ''}`} key=${row.id}>
                <div class="head">
                  <span class="name">${row.label}</span>
                  ${row.id === me && html`<span class="badge good">this browser</span>`}
                  <span class="act name data">${row.address}${row.port ? `:${row.port}` : ''}</span>
                </div>
                <div class="meta" title=${row.agent}>
                  watching for ${ago(Math.max(0, now - (row.since || now)))}
                </div>
              </div>`
            )}
          </div>`}
  <//>`;
}

function App() {
  const [state, setState] = useState(null);
  const [link, setLink] = useState({ state: 'released' });
  const [info, setInfo] = useState(null);
  const [status, setStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [activity, setActivity] = useState([]);
  const [propertyView, setPropertyView] = useState(EMPTY_PROPERTIES);
  const [logLines, setLogLines] = useState([]);
  const [logLoading, setLogLoading] = useState(false);
  const [tab, setTab] = useState(tabFromHash);
  /* Which tabs have been opened.  A tab is built the first time it is
   * asked for and then stays built, hidden rather than thrown away: what
   * it read is still there, and so is the half-typed value in it and where
   * the log was scrolled to.  Switching away and back used to unmount the
   * lot and re-read a charger that had not changed. */
  const [seen, setSeen] = useState(() => new Set([tabFromHash()]));
  const [picking, setPicking] = useState(false);
  const [watching, setWatching] = useState(false);
  const [me, setMe] = useState(null);
  const theme = useTheme();
  const toast = useToasts();
  const alerts = useTabAlerts();
  const server = useServerLink();
  const loadedFor = useRef(null);
  const everOpened = useRef(false);

  const readOnly = state ? state.readOnly : false;

  /* What "busy" means to a control on the page, which is not what it means
   * to the link.  The live refresh takes the connection every few seconds
   * and every button on the page used to grey out and come back with it --
   * a page that blinked at you and told you nothing, since a click during a
   * refresh is queued behind it and runs perfectly well.  So the refresh is
   * excluded (`quiet`, set by the worker for the tasks nobody asked for),
   * and what is left has to last long enough to be worth showing. */
  const busy = useSteadyBusy(
    (link.state === 'busy' || link.state === 'connecting') && !link.quiet
  );

  /* Read the world afresh: what the server holds, and what it knows about
   * the charger.  Called on the first load and again whenever the stream
   * comes back, because a server that was restarted has forgotten
   * everything this page was told before it went. */
  const resync = async () => {
    try {
      const doc = await api.get('/state');
      setState(doc);
      setLink(doc.link);
      setActivity((known) => rememberActivity(known, doc.link?.activity));
      setInfo(doc.info);
      setJobs(doc.jobs || []);
      server.found();
      return doc;
    } catch (err) {
      toast.error(err.message);
      return null;
    }
  };

  /* One stream for the whole page. */
  useEffect(() => {
    const stop = api.subscribe({
      hello: (doc) => setMe(doc.clientId),
      focus: () => {
        comeForward();
        alerts.notify();
        toast.info('alfenctl ui was started again -- this is the tab it meant.');
      },
      link: (doc) => {
        setLink(doc);
        setActivity((known) => rememberActivity(known, doc.activity));
      },
      info: (doc) => setInfo(doc?.objectId ? doc : null),
      status: setStatus,
      job: (job) =>
        setJobs((list) => {
          const next = list.filter((j) => j.id !== job.id);
          next.push(job);
          if (job.state === 'done') toast.ok(`${job.name}: ${job.message || 'done'}`);
          if (job.state === 'failed') toast.error(`${job.name}: ${job.error}`);
          return next;
        }),
      log: (doc) =>
        setLogLines((lines) => {
          const added = doc.missed ? [logGapNote(), ...doc.lines] : doc.lines;
          return [...lines, ...added].slice(-MAX_LOG_LINES);
        }),
      properties: () => {},
      onopen: () => {
        server.found();
        /* The first open is the page loading, which is already reading
         * `/state` below.  Every one after it is the server coming back
         * from somewhere, and what this page holds is then a description
         * of a program that no longer exists. */
        if (everOpened.current) {
          resync().then((doc) => doc && loadedFor.current && reload());
        }
        everOpened.current = true;
      },
      onerror: () => server.lost(),
    });
    resync();
    /* Whatever the address bar asked for is being shown already; this is
     * what makes opening `#logs` directly read the log, rather than
     * landing on an empty one until you click the tab you are on. */
    show(tabFromHash());
    return stop;
  }, []);


  /* Follow the tab in the address bar, so Back and a pasted link work. */
  useEffect(() => {
    const follow = () => show(tabFromHash());
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, []);


  /* Read the dashboard once per station, not on every re-render. */
  const reload = async () => {
    try {
      setDashboard(await api.get('/dashboard'));
    } catch (err) {
      toast.error(err.message);
    }
  };
  useEffect(() => {
    const station = link.station || '';
    if (!station || loadedFor.current === station) return;
    loadedFor.current = station;
    reload();
  }, [link.station]);

  const call = async (fn, okMessage) => {
    try {
      const result = await fn();
      if (okMessage) toast.ok(typeof okMessage === 'function' ? okMessage(result) : okMessage);
      return result;
    } catch (err) {
      toast.error(err.message);
      throw err;
    }
  };

  /* The dashboard's balancing card and the Charging tab's full editor
   * write the same settings to the same endpoint, so the reply goes into
   * the panel store and both of them move at once. */
  const writeBalancing = async (payload) => {
    const doc = await call(() => api.post('/lb', payload), 'Load balancing written.');
    if (doc?.loadbalancing) putPanel('lb', doc);
    reload();
    return doc;
  };

  const setLive = (enabled) => call(() => api.post('/live', { enabled }));

  const setFollow = async (on) => {
    await call(() => api.post('/live', { logs: on, enabled: on ? true : undefined }));
    setState((s) => (s ? { ...s, followLogs: on } : s));
  };

  const loadLogs = async (since) => {
    setLogLoading(true);
    try {
      const doc = await api.get('/logs', since ? { since } : {});
      setLogLines(doc.lines.slice(-MAX_LOG_LINES));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLogLoading(false);
    }
  };
  const loadLogsSince = (since) => loadLogs(since);


  const pick = async (station) => {
    setPicking(false);
    setDashboard(null);
    setStatus(null);
    setPropertyView(EMPTY_PROPERTIES);  // another charger, another catalog
    resetPanels();                      // ... and another set of panel answers
    setLogLines([]);
    loadedFor.current = null;
    await call(() => api.post('/station', station), `Station set to ${station.name || station.host}.`);
    reload();
  };

  /* Show a tab: build it if this is its first time, and put it in the
   * address bar so a reload comes back to it. */
  const show = (id) => {
    setTab(id);
    setSeen((known) => (known.has(id) ? known : new Set([...known, id])));
    if (window.location.hash.replace(/^#/, '') !== id) {
      window.history.replaceState(null, '', `#${id}`);
    }
  };

  /* The log is read the first time it is looked at, and not before: it is
   * a charger round trip, and until a station has been chosen there is
   * nothing to ask.  Which is why this waits for the station rather than
   * firing from `show` -- opening the page straight at `#logs` used to
   * mean showing the tab before there was anything to put in it. */
  useEffect(() => {
    if (tab !== 'logs' || !link.station) return;
    if (logLines.length === 0 && !logLoading) loadLogs();
  }, [tab, link.station]);


  /* Arrow keys walk the tab strip, as a tablist is expected to. */
  const onTabKey = (event, index) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    const at =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? TABS.length - 1
          : step
            ? (index + step + TABS.length) % TABS.length
            : null;
    if (at === null) return;
    event.preventDefault();
    show(TABS[at][0]);
    document.getElementById(`tab-${TABS[at][0]}`)?.focus();
  };


  const reboot = () => call(() => api.post('/actions/reboot'), (r) => r.message);
  const syncClock = () => call(() => api.post('/actions/time-sync'), 'Charger clock set.');
  const uploadLogo = (file) =>
    call(() => api.upload('/actions/logo', file), 'Logo upload started.');
  const uploadFirmware = (file) =>
    call(() => api.upload('/actions/firmware', file), 'Firmware upload started.');
  const listFirmware = (all) =>
    api.get('/firmware/available', all ? { all: '1' } : {});
  const installRelease = (name) =>
    call(() => api.post('/actions/firmware-release', { name }), `Installing ${name}.`);
  const sendConsole = (command) =>
    call(() => api.post('/console', { command }), (r) => r.message);
  const listConsole = () => api.get('/console');
  const calibrateTilt = () => call(() => api.post('/tilt'), (r) => r.message);
  const eraseTarget = (target) =>
    call(() => api.post('/erase', { target }), (r) => r.message);

  /* One tab's content.  Called once per tab, the first time it is opened;
   * what it returns then stays mounted behind `hidden`. */
  const panel = (id) => {
    if (id === 'dashboard') {
      return html`<${Dashboard}
        data=${dashboard}
        status=${status}
        station=${link.station}
        activity=${activity}
        liveUpdates=${link.live}
        readOnly=${readOnly}
        busy=${busy}
        onReload=${reload}

        onDoctor=${() => api.get('/doctor')}
        onSync=${() =>
          call(() => api.post('/actions/time-sync'), 'Charger clock set from this computer.').then(reload)}
        onLicense=${(key) =>
          call(() => api.post('/actions/license', { key }), (r) => r.message).then(reload)}
        onControls=${(changes) =>
          call(() => api.post('/actions/controls', changes), 'Charger settings written.').then(
            reload
          )}
        onBalancing=${writeBalancing}
      />`;

    }
    if (id === 'properties') {
      return html`<${Properties}
        state=${propertyView}
        onState=${setPropertyView}
        readOnly=${readOnly}
        busy=${busy}
        toast=${toast}
        api=${api}
        onCategories=${() => api.get('/categories').then((doc) => doc.categories)}
        onLoad=${(category) =>
          api.get('/properties', category ? { category } : {}).then((doc) => doc.properties)}
        onWrite=${(writes) => api.post('/properties', { writes }).then((doc) => doc.properties)}
        link=${link}
      />`;

    }
    if (id === 'charging') {
      return html`<${Charging} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`;
    }
    if (id === 'access') {
      return html`<${Access} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`;
    }
    if (id === 'network') {
      return html`<${Network} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`;
    }
    if (id === 'backoffice') {
      return html`<${Backoffice} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`;
    }
    if (id === 'sessions') {
      return html`<${Sessions} api=${api} busy=${busy} link=${link} />`;

    }
    if (id === 'logs') {
      return html`<${Logs}
        lines=${logLines}
        follow=${state.followLogs}
        busy=${busy}
        loading=${logLoading}
        onFollow=${setFollow}
        onReload=${() => loadLogs()}
        onSince=${loadLogsSince}

        link=${link}
      />`;
    }

    return html`<${Actions}
      jobs=${jobs}

      display=${dashboard?.display}
      readOnly=${readOnly}
      busy=${busy}
      onReboot=${reboot}
      onTimeSync=${syncClock}
      onLogo=${uploadLogo}
      onFirmware=${uploadFirmware}
      onFirmwareList=${listFirmware}
      onFirmwareRelease=${installRelease}
      onTilt=${calibrateTilt}
      onConsole=${sendConsole}
      onConsoleList=${listConsole}
      onErase=${eraseTarget}
      toast=${toast}
    />`;
  };

  /* Every tab that has been opened, all of them mounted, all but one of
   * them hidden.  `hidden` rather than a swap: a tab that is thrown away
   * takes its reading, its draft and its scroll position with it, and
   * putting it back costs the charger another round trip for an answer
   * nothing has changed. */
  const panes = () => {
    if (!state) return html`<div class="empty">Connecting to the alfenctl server...</div>`;
    if (!state.hasTarget && !link.station) {
      return html`<div class="empty">
        No station selected yet.
        <div class="actions-row centred">
          <button class="btn primary" onClick=${() => setPicking(true)}>Choose a station</button>
        </div>
      </div>`;
    }
    return TABS.filter(([id]) => seen.has(id)).map(
      ([id]) => html`<div
        class="pane"
        key=${id}
        id=${`pane-${id}`}
        role="tabpanel"
        aria-labelledby=${`tab-${id}`}
        hidden=${tab !== id}
      >
        ${panel(id)}
      </div>`
    );
  };

  return html`<div class="app">

    <header class=${`top${server.state === 'offline' ? ' gone' : server.state === 'reconnecting' ? ' lost' : ''}`}>
      <div class="brand">
        <a
          class="home"
          href="https://github.com/pbasista/alfenctl"
          target="_blank"
          rel="noreferrer"
          title="alfenctl on GitHub"
        >
          <span class="bolt">⚡</span><span class="name">alfenctl</span>
        </a>
        ${state?.version
          ? html`<a
              class="ver"
              href="https://github.com/pbasista/alfenctl/releases"
              target="_blank"
              rel="noreferrer"
              title="release notes"
            >${state.version}</a>`
          : null}
      </div>
      <div class="station-id">
        <span class="primary">${(info && (info.identity || info.objectId)) || link.station || 'no station'}</span>
        <span class="secondary">
          ${info ? `${info.model || ''} ${info.firmware || ''}`.trim() : 'not connected'}
        </span>
      </div>
      <button class="btn small ghost" onClick=${() => setPicking(true)}>change</button>
      <span class="spacer"></span>
      <${OfflineNotice} state=${server.state} onRetry=${resync} />
      ${readOnly && html`<span class="badge">read-only</span>`}
      <${ConnectionPill}
        link=${link}
        activity=${activity}
        offline=${server.offline}
        onConnect=${() => call(() => api.post('/link', { action: 'connect' }))}
        onRelease=${() =>
          call(() => api.post('/link', { action: 'release' }), 'Connection released.')}
        onWatchers=${() => setWatching(true)}
      />
      <!-- After the pill, not before it.  The pill is the one thing in
           this header whose width is decided by what it has to say --
           "busy", "connected, idle", "server unreachable" -- and
           everything to the left of it slides every time that changes,
           because the header packs these against its right edge.  A
           switch that walks away from the pointer while the link is
           working is a switch you miss.  The pill holds a minimum width
           of its own now as well, so most of those changes move
           nothing at all. -->
      <${LiveToggle} link=${link} offline=${server.offline} onLive=${setLive} />
      <${Bell} alerts=${alerts} toast=${toast} />

      <button
        class="btn small ghost icon"
        title=${`theme: ${theme.mode} -- click for ${theme.next}`}
        aria-label=${`theme: ${theme.mode}`}
        onClick=${theme.cycle}
      >
        ${THEME_ICON[theme.mode]}
      </button>
    </header>

    <div class="body">

      <nav class="tabs" role="tablist" aria-label="What to look at">
        ${TABS.map(
          ([id, label], index) => html`<button
            key=${id}
            id=${`tab-${id}`}
            role="tab"
            type="button"
            aria-selected=${tab === id}
            aria-controls=${`pane-${id}`}
            tabIndex=${tab === id ? 0 : -1}
            onKeyDown=${(event) => onTabKey(event, index)}
            onClick=${() => show(id)}
          >
            ${label}
          </button>`
        )}
      </nav>
      <main>${panes()}</main>


      <footer class="license">
        <!-- The EU flag, drawn inline to the official geometry (same as
             Wikimedia's own SVG of it): 12 upright five-pointed gold stars
             each with a circumscribed radius of 1/18 of the flag height
             (30 of 540), on a circle of radius 1/3 of the flag height
             (180, same as Wikimedia's own SVG of the flag), on a 3:2 flag of the official blue.  The viewBox is
             810x540, so the whole rectangle is the flag.  The frame and
             halo are set in CSS so they follow the theme. -->
        <svg class="eu-flag" viewBox="0 0 810 540" width="30" height="20" aria-hidden="true">
          <defs>
            <path id="eu-star" fill="#ffcc00" d="M0.00,-33.33L7.48,-10.30L31.70,-10.30L12.11,3.93L19.59,26.97L0.00,12.73L-19.59,26.97L-12.11,3.93L-31.70,-10.30L-7.48,-10.30Z" />
          </defs>
          <rect x="0" y="0" width="810" height="540" fill="#003399" />
          <use href="#eu-star" x="405" y="90" />
          <use href="#eu-star" x="495" y="114.1" />
          <use href="#eu-star" x="560.9" y="180" />
          <use href="#eu-star" x="585" y="270" />
          <use href="#eu-star" x="560.9" y="360" />
          <use href="#eu-star" x="495" y="425.9" />
          <use href="#eu-star" x="405" y="450" />
          <use href="#eu-star" x="315" y="425.9" />
          <use href="#eu-star" x="249.1" y="360" />
          <use href="#eu-star" x="225" y="270" />
          <use href="#eu-star" x="249.1" y="180" />
          <use href="#eu-star" x="315" y="114.1" />
        </svg>
        <a
          href="https://github.com/pbasista/alfenctl/blob/main/LICENSE"
          target="_blank"
          rel="noreferrer"
          title="The licence this copy of alfenctl is under"
        >
          Licensed under the EUPL-1.2
        </a>
      </footer>
    </div>

    ${picking && html`<${StationPicker} onPick=${pick} onClose=${() => setPicking(false)} toast=${toast} />`}
    ${watching && html`<${Watchers} me=${me} onClose=${() => setWatching(false)} toast=${toast} />`}
    <${Toasts} toasts=${toast.toasts} dismiss=${toast.dismiss} />
  </div>`;
}

render(html`<${App} />`, document.getElementById('root'));
