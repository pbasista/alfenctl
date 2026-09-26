/* The alfenctl web UI.
 *
 * One page, one event stream, one charger connection somewhere behind the
 * server.  Everything the backend learns -- the link state, a status
 * refresh, a job's progress -- arrives as an event and lands in the state
 * here, so two browsers watching the same station stay in step with each
 * other without either of them polling.
 */

import { configure as configureApi } from '/core/js/api.js';
import { DraftDialog, PageApply, resetDrafts } from '/core/js/drafts.js';
import { Bell, configure as configureNotify, useTabAlerts } from '/core/js/notify.js';
import { putPanel, resetPanels } from '/core/js/panels.js';
import {
  Brand,
  configure as configureShell,
  DeviceId,
  Glyph,
  Header,
  License,
  Pane,
  ThemeToggle,
  useFavicon,
  useServerLink,
  useTabs,
  useTheme,
  Watchers,
} from '/core/js/shell.js';
import {
  caller,
  LiveToggle,
  OfflineNotice,
  Toasts,
  useSteadyBusy,
  useToasts,
} from '/core/js/ui.js';
import { html, render, useEffect, useRef, useState } from '/core/vendor/preact-htm.module.js';

import { Access } from './access.js';
import { Actions } from './actions.js';
import * as api from './api.js';
import { Backoffice } from './backoffice.js';
import { Charging } from './charging.js';
import { ConnectionPill } from './conn.js';
import { Connectivity } from './connectivity.js';
import { Dashboard } from './dashboard.js';
import { Fleet, isCurrent } from './fleet.js';
import { Logs, logGapNote } from './logs.js';
import { EMPTY_PROPERTIES, Properties } from './properties.js';
import { Sessions } from './sessions.js';
import { StationPicker } from './stations.js';

/* What this program calls itself, to the three shared modules that write a
 * sentence or keep a key with the name in it.
 *
 * Where it lives on the web, where its releases are and where its licence
 * is used to be three more constants here.  They are `[project.urls]` in
 * `pyproject.toml` now, and the shared `Brand` and `License` read them off
 * `GET /api/about` -- so a repository that moves is one line in one file.
 */
const NAME = 'alfenctl';

configureApi({ name: NAME });
configureNotify({ name: NAME });
configureShell({ name: NAME });

/* --- the mark ------------------------------------------------------------
 *
 * The bolt.  It was the character U+26A1 in the header and a differently
 * drawn bolt percent-encoded into index.html for the tab -- so the two
 * places this program's mark appears were an emoji whose shape, weight and
 * colour belonged to whichever platform was drawing it, and a hand-encoded
 * SVG nobody was ever going to edit twice.  The header's is the one that
 * was right, so this is that bolt, drawn rather than typed: the same shape
 * at any size, in this program's own amber, and something a browser will
 * actually put in a tab.
 *
 * Worn in both places by `Glyph` and `useFavicon`; `currentColor` is the
 * header's text there and `--tab-mark` in the tab.
 */
const MARK = {
  viewBox: '0 0 16 16',
  shapes: [
    [
      'path',
      {
        d: 'M9.9 1.4 3.9 9.2h3.3l-1.1 5.4 6-7.8H8.8z',
        fill: 'currentColor',
      },
    ],
  ],
};

/* The tabs, in the order someone works down them: what the charger is
 * doing, then what it is set to do, then what it has done, then the two
 * catalogues, then the things you do to it.
 *
 * The log used to be a radio button inside a "History" tab, two clicks
 * from anywhere and invisible until you found it -- which for the one
 * thing that answers "why did it stop charging at 3am" is the wrong place
 * entirely.  It is a tab, beside the sessions it explains.
 *
 * The Fleet is first, and so is the landing tab, because "which station is
 * this page about" is the question that comes before every other one on the
 * page -- and because the page had no answer to "what have I got" at all,
 * only a dialog behind a button for changing station.  It is the same view,
 * out of the same tiles, as jkctl's Bank.
 *
 * "Connectivity" was "Network", which on a page about charging stations is
 * the operator's charging network -- the thing the Backoffice tab is about.
 * A tab called Network that holds interface addresses and a Wi-Fi scan
 * sends people to the wrong one twice. */
const TABS = [
  ['fleet', 'Fleet'],
  ['dashboard', 'Dashboard'],
  ['charging', 'Charging'],
  ['sessions', 'Sessions'],
  ['logs', 'Logs'],
  ['access', 'Access'],
  ['connectivity', 'Connectivity'],
  ['backoffice', 'Backoffice'],
  ['properties', 'Properties'],
  ['actions', 'Actions'],
];


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

/* Everything the Actions tab can ask the charger to do.
 *
 * Sixteen one-line closures over `call`, which is sixteen lines in the
 * middle of `App` that say nothing except which endpoint goes with which
 * prop.  As a table they are readable as a table: the whole of what that
 * tab can do, in one place, beside the words it says when it works.
 *
 * `(r) => r.message` is the server's own sentence -- "rebooting", "erased
 * 412 transactions" -- which is better than anything this page could write
 * for it, and the only thing that knows how many.
 */
function useCommands(call) {
  return {
    onReboot: () => call(() => api.post('/actions/reboot'), (r) => r.message),
    onTimeSync: () => call(() => api.post('/actions/time-sync'), 'Charger clock set.'),
    onLogo: (file) => call(() => api.upload('/actions/logo', file), 'Logo upload started.'),
    onFirmware: (file) =>
      call(() => api.upload('/actions/firmware', file), 'Firmware upload started.'),
    onFirmwareList: (all) => api.get('/firmware/available', all ? { all: '1' } : {}),
    onFirmwareRelease: (name) =>
      call(() => api.post('/actions/firmware-release', { name }), `Installing ${name}.`),
    onTilt: () => call(() => api.post('/tilt'), (r) => r.message),
    onConsole: (command) => call(() => api.post('/console', { command }), (r) => r.message),
    onConsoleList: () => api.get('/console'),
    /* Not through `call`: the panel shows the reply and the failure in its
     * own card, beside the command that caused them, rather than in a
     * toast that has scrolled away by the time the result is read. */
    onDiagnosticSend: (payload) => api.post('/diag', payload),
    onDiagnosticResult: () => api.get('/diag'),
    onErase: (target) => call(() => api.post('/erase', { target }), (r) => r.message),
  };
}

function App() {
  useFavicon(MARK);
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
  const nav = useTabs(TABS);
  const { tab } = nav;
  /* Which tabs have been opened.  A tab is built the first time it is
   * asked for and then stays built, hidden rather than thrown away: what
   * it read is still there, and so is the half-typed value in it and where
   * the log was scrolled to.  Switching away and back used to unmount the
   * lot and re-read a charger that had not changed. */
  const [seen, setSeen] = useState(() => new Set([tab]));
  useEffect(() => {
    setSeen((known) => (known.has(tab) ? known : new Set([...known, tab])));
  }, [tab]);
  const [picking, setPicking] = useState(false);
  const [watching, setWatching] = useState(false);
  /* Every station this server can see, for the Fleet tab.  Read when that
   * tab is first opened rather than on load: it is an mDNS sweep, and a
   * page opened straight at `#logs` has no use for it. */
  const [fleet, setFleet] = useState(null);
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
    (link.state === 'busy' || link.state === 'opening') && !link.quiet
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
    return stop;
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

  const call = caller(toast);
  const commands = useCommands(call);

  /* A manufacturer sign-in that came back through the loopback lands on this
   * page with ?code&state in the address (see cloud.loopback_redirect on the
   * server).  Finish it once, on load: hand the whole address to the server,
   * which matches it to the sign-in it started and caches the token, then
   * scrub the query so a reload does not resubmit a code that is already
   * spent.  Nothing is pasted; the redirect did it. */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.get('state') || !(params.get('code') || params.get('error'))) return;
    const redirected = window.location.href;
    window.history.replaceState(null, '', window.location.pathname + window.location.hash);
    call(
      () => api.post('/cloud/login', { action: 'finish', redirected }),
      (r) => (r.account ? `Signed in to Alfen as ${r.account}.` : 'Signed in to Alfen.')
    ).then((r) => r && resync());
  }, []);

  /* The dashboard's balancing card and the Charging tab's full editor
   * write the same settings to the same endpoint, so the reply goes into
   * the panel store and both of them move at once. */
  const writeBalancing = async (payload) => {
    const doc = await call(() => api.post('/lb', payload), 'Load balancing written.', {
      raise: true,
    });
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


  const lookForStations = async () => {
    try {
      setFleet(await api.get('/stations'));
    } catch (err) {
      toast.error(err.message);
      setFleet({ configured: [], discovered: [] });
    }
  };

  const pick = async (station) => {
    setPicking(false);
    setDashboard(null);
    setStatus(null);
    setPropertyView(EMPTY_PROPERTIES);  // another charger, another catalog
    resetPanels();                      // ... and another set of panel answers
    resetDrafts();                      // ... and nothing changed on it yet
    setLogLines([]);
    loadedFor.current = null;
    const doc = await call(
      () => api.post('/station', station),
      `Station set to ${station.name || station.host}.`
    );
    /* The reply carries the new link, and it is taken rather than waited
     * for.  The stream sends the same document a moment later, and in that
     * moment the page still believes no station is chosen -- which is the
     * one state that replaces the whole body with "No station selected
     * yet", so a tile clicked on the Fleet flashed that prompt on its way
     * to the dashboard. */
    if (doc?.link) setLink(doc.link);
    reload();
    return doc;
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

  /* The same, for the Fleet: an mDNS sweep is worth doing when somebody
   * asks what there is, and not before. */
  useEffect(() => {
    if (tab === 'fleet' && fleet === null) lookForStations();
  }, [tab]);


  /* One tab's content, by name.  Built once per tab, the first time it is
   * opened; what it returns then stays mounted behind `hidden`.
   *
   * A table rather than the chain of `if (id === ...)` this was: nine
   * branches returning nine templates, in which the two long ones buried
   * the seven that are one line, and a tab added to `TABS` without a
   * branch here fell through to whichever one the chain happened to end
   * on.  A key that is not here now renders nothing, loudly.
   */
  const panels = {
    /* Choosing a station on the Fleet opens it, the way clicking a board on
     * the other program's Bank opens that board.  A tile is not a setting:
     * somebody clicking one has picked the charger they want to look at,
     * and leaving them on a grid of tiles with one of them newly outlined
     * makes them go and find the tab themselves.  Only when the server took
     * it -- a station that could not be set leaves the page where it is,
     * beside the list another can be chosen from. */
    fleet: () => html`<${Fleet}
      stations=${fleet}
      current=${link.station}
      busy=${busy}
      onPick=${async (station) => {
        if (isCurrent(station, link.station)) {
          nav.show('dashboard');
          return;
        }
        const doc = await pick({ name: station.name, host: station.host, port: station.port });
        if (doc) nav.show('dashboard');
      }}
      onRescan=${() => {
        setFleet(null);
        lookForStations();
      }}
      onAdd=${() => setPicking(true)}
    />`,

    dashboard: () => html`<${Dashboard}
      data=${dashboard}
      status=${status}
      station=${link.station}
      activity=${activity}
      liveUpdates=${link.live}
      readOnly=${readOnly}
      busy=${busy}
      onReload=${reload}
      onDoctor=${() => call(() => api.get('/doctor'))}
      onSync=${() =>
        call(
          () => api.post('/actions/time-sync'),
          'Charger clock set from this computer.'
        ).then(reload)}
      onLicense=${(key) =>
        call(() => api.post('/actions/license', { key }), (r) => r.message).then(reload)}
      cloudSignedIn=${!!state?.cloudSignedIn}
      onCloudSignInStart=${() =>
        api.post('/cloud/login', { action: 'start', origin: window.location.origin })}
      onCloudSignInFinish=${(redirected) =>
        call(
          () => api.post('/cloud/login', { action: 'finish', redirected }),
          (r) => (r.account ? `Signed in to Alfen as ${r.account}.` : 'Signed in to Alfen.')
        ).then((r) => {
          if (r) resync();
          return r;
        })}
      onCloudSignOut=${() =>
        call(
          () => api.post('/cloud/login', { action: 'logout' }),
          'Signed out of Alfen.'
        ).then((r) => {
          if (r) resync();
          return r;
        })}
      onCloudLookup=${(token) =>
        call(
          () => api.post('/cloud', token ? { token } : {}),
          'Fetched from the manufacturer.'
        )}
      onControls=${(changes) =>
        call(() => api.post('/actions/controls', changes), 'Charger settings written.', {
          raise: true,
        }).then(reload)}
      onBalancing=${writeBalancing}
    />`,

    charging: () => html`<${Charging} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`,

    sessions: () => html`<${Sessions} api=${api} busy=${busy} link=${link} />`,

    logs: () => html`<${Logs}
      lines=${logLines}
      follow=${state.followLogs}
      busy=${busy}
      loading=${logLoading}
      onFollow=${setFollow}
      onReload=${() => loadLogs()}
      onSince=${loadLogsSince}
      link=${link}
    />`,

    access: () => html`<${Access} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`,

    connectivity: () =>
      html`<${Connectivity} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`,

    backoffice: () =>
      html`<${Backoffice} api=${api} readOnly=${readOnly} busy=${busy} toast=${toast} />`,

    properties: () => html`<${Properties}
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
    />`,

    actions: () => html`<${Actions}
      key=${link.station}
      jobs=${jobs}
      display=${dashboard?.display}
      readOnly=${readOnly}
      busy=${busy}
      ...${commands}
      toast=${toast}
    />`,
  };

  /* Every tab that has been opened, all of them mounted, all but one of
   * them hidden.  `hidden` rather than a swap: a tab that is thrown away
   * takes its reading, its draft and its scroll position with it, and
   * putting it back costs the charger another round trip for an answer
   * nothing has changed. */
  const panes = () => {
    if (!state) return html`<div class="empty">Connecting to the ${NAME} server...</div>`;
    /* Nothing chosen yet.  The Fleet tab is the answer to that, so the
     * page says which tab rather than growing a second way to choose --
     * a page that offers the same choice in two places is a page where
     * neither of them is where you look for it. */
    if (!state.hasTarget && !link.station && tab !== 'fleet') {
      return html`<div class="empty">
        No station selected yet.
        <div class="actions centred">
          <button class="btn primary" onClick=${() => nav.show('fleet')}>Choose a station</button>
        </div>
      </div>`;
    }
    return TABS.filter(([id]) => seen.has(id)).map(
      ([id]) => html`<${Pane} key=${id} id=${id} shown=${tab === id}>${panels[id]?.()}<//>`
    );
  };

  return html`<div class="app">

    <${Header} state=${server.state} nav=${nav} label="What to look at">
      <${Brand}><${Glyph} mark=${MARK} /><//>
      <!-- The station's name is itself the way to change station.  What
           opened the list used to be a "change" button beside the name,
           which is a second control for an action about the thing next to
           it -- and the name is what somebody reads to realise they are
           looking at the wrong charger. -->
      <${DeviceId}
        primary=${(info && (info.identity || info.objectId)) || link.station || 'no station'}
        secondary=${info ? `${info.model || ''} ${info.firmware || ''}`.trim() : 'not connected'}
        onPick=${() => setPicking(true)}
        title="Which charging station"
      />
      <span class="spacer"></span>
      <!-- Every edit not sent yet, on whichever tab and card it was made,
           where it can always be seen and sent or dropped all at once.
           Each card also applies or discards its own from its title. -->
      <${PageApply} />
      <${OfflineNotice} state=${server.state} onRetry=${resync} program=${NAME} />
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
      <${LiveToggle}
        link=${link}
        offline=${server.offline}
        onLive=${setLive}
        program=${NAME}
      />
      <${Bell} alerts=${alerts} toast=${toast} />

      <${ThemeToggle} theme=${theme} />
    <//>

    <div class="body">
      <main>${panes()}</main>
      <${License} />
    </div>

    ${picking && html`<${StationPicker} onPick=${pick} onClose=${() => setPicking(false)} toast=${toast} />`}
    ${watching && html`<${Watchers} me=${me} onClose=${() => setWatching(false)} toast=${toast} />`}
    <${DraftDialog} />
    <${Toasts} toasts=${toast.toasts} dismiss=${toast.dismiss} />
  </div>`;
}

render(html`<${App} />`, document.getElementById('root'));
