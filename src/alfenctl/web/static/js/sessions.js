/* The Sessions tab: what the charger has actually delivered.
 *
 * Read from the charger's own transaction database, which is paged in
 * whole -- there is no way to ask it for less -- so one read answers every
 * question this tab can be asked.  The server groups it every way this tab
 * offers on the way past (see `get_transactions` in web/api.py), which is
 * what lets the grouping change without touching the charger again.
 *
 * It opens on the monthly summary, as `alfenctl transactions --summary`
 * does: "how much did this cost me in March" is the question people have,
 * and a list of four hundred rows is not the answer to it.  A month opens
 * in place to the sessions behind it, and the flat list is still one click
 * away for anyone who wants to read the lot.
 */

import { html, useState } from '../vendor/preact-htm.module.js';
import { acrossPlot, Hovered, useHover } from './chart.js';
import { Loading, PanelError, usePanel } from './panels.js';
import { Card, Progress, Select } from './ui.js';

const VIEWS = [
  { value: 'day', title: 'by day' },
  { value: 'month', title: 'by month' },
  { value: 'socket', title: 'by socket' },
  { value: 'tag', title: 'by tag' },
  { value: '', title: 'every session' },
];

const GROUP_HEAD = { day: 'Day', month: 'Month', socket: 'Socket', tag: 'Tag' };

function duration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

function stamp(text) {
  return (text || '').replace('T', ' ');
}

/* A CSV field, quoted where it has to be.  A tag or a stop reason with a
 * comma in it used to split into two columns in whatever opened the file,
 * silently, one row at a time. */
function csvField(value) {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function download(rows) {
  const header = 'socket,id,start,stop,duration_s,energy_kwh,tag,reason';
  const lines = rows.map((s) =>
    [s.socket, s.id, stamp(s.start), stamp(s.stop), s.durationS, s.energyKwh, s.tag, s.reason]
      .map(csvField)
      .join(',')
  );
  const blob = new Blob([`${[header, ...lines].join('\n')}\n`], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'charging-sessions.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

/* Which sessions a summary row was built from.
 *
 * The server groups the rows and sends the totals; opening one has to find
 * its sessions again on this side, by the same rule the grouping used.
 * They are kept next to each other here so they cannot drift apart from
 * `GROUPINGS` in `transactions.py`. */
const BELONGS = {
  day: (session, key) => (session.start || '').slice(0, 10) === key,
  month: (session, key) => (session.start || '').slice(0, 7) === key,
  socket: (session, key) => `socket ${session.socket}` === key,
  tag: (session, key) => (session.tag || '') === key,
};

/* The energy column, with the row's share of the biggest one drawn behind
 * it.  A year of months is twelve numbers to compare by eye; the bar is
 * what makes the tall one obvious without reading any of them. */
function Energy({ kwh, of }) {
  const share = of > 0 ? Math.max(0, Math.min(1, (kwh || 0) / of)) : 0;
  return html`<span class="meter">
    <span class="fill" style=${`width:${(share * 100).toFixed(1)}%`}></span>
    <span class="figure">${kwh} kWh</span>
  </span>`;
}

/* --- how much, and when ------------------------------------------------------
 *
 * Every app that reads an Alfen's transaction database shows the sessions
 * as a list, and a list of four hundred rows does not answer "are we using
 * more of it than we were".  The database has the answer -- it is a
 * timestamp and a number of kWh per session -- so this is one bar per
 * period across whatever span the sessions cover, which is a shape rather
 * than a table.
 *
 * The periods with no session are drawn as well, as gaps: a chart that
 * only plotted the days something happened would space a fortnight's
 * holiday exactly like a fortnight of daily charging.
 *
 * Which period it is, is whichever the table below is grouped by.  It was
 * always a day, whatever the tab was showing -- so the view this tab opens
 * on, twelve months of totals, sat under a chart of four hundred daily
 * bars most of which were the days nobody charged: a floor of nothing with
 * a scatter of spikes over it, at one or two pixels a bar, which is not a
 * shape anybody can read and is not what the table underneath it said.
 * Grouped by month, twelve bars answer the question twelve rows are
 * asking.  The groupings that are not periods at all -- by socket, by tag
 * -- keep the daily chart: their table is not a history, and the history
 * is still worth having above it.
 */

const CHART_W = 720;
const CHART_H = 150;
const CHART_PAD = 8;
const DAY_MS = 86400000;

/* What one bar of the chart covers, for each grouping that is a stretch of
 * time.  `of` is the key a session falls in -- the same slice `BELONGS`
 * groups the table by -- and `next` is the key after a given one, which is
 * what fills in the periods nothing happened in.
 *
 * A month is stepped through by its number rather than by adding days: the
 * months are not the same length, and a fixed step would drift.  A day is
 * stepped from noon UTC rather than midnight, because midnight plus 24
 * hours lands on the previous day in any zone west of UTC once a browser
 * has turned the stamp back into local time -- so a chart could grow a
 * duplicate day and lose another.  From the middle of a day, a 24-hour
 * step is the next day everywhere. */
const PERIODS = {
  day: {
    of: (session) => (session.start || '').slice(0, 10),
    next: (day) => new Date(Date.parse(`${day}T12:00:00Z`) + DAY_MS).toISOString().slice(0, 10),
    short: (day) => day.slice(5).replace('-', '/'),
    looks: /^\d{4}-\d{2}-\d{2}$/,
    noun: 'day',
  },
  month: {
    of: (session) => (session.start || '').slice(0, 7),
    next: (month) => {
      const [year, index] = month.split('-').map(Number);
      return index === 12 ? `${year + 1}-01` : `${year}-${String(index + 1).padStart(2, '0')}`;
    },
    short: (month) => month,
    looks: /^\d{4}-\d{2}$/,
    noun: 'month',
  },
};

/* Which period a view is charted in.  The two that are periods chart
 * themselves; everything else -- by socket, by tag, the flat list -- is a
 * table about something other than time, and gets the daily history. */
function periodFor(view) {
  return PERIODS[view] || PERIODS.day;
}

/* One entry per period from the first session to the last, in order, with
 * the energy delivered in each.  A gap is a real period with a real zero.
 *
 * The run is capped: a database whose oldest session is years back would
 * otherwise be asked for a bar per day over all of it, and a loop that
 * builds one is a loop nobody is watching.  And it is only walked at all
 * when every key really is a date -- a session whose stamp the charger
 * truncated slices to something `next` cannot step from, and stepping from
 * it is how a filler loop becomes an endless one.  Those are drawn as the
 * periods they are, with no gaps filled in. */
const MAX_BARS = 3000;

function totalsBy(period, sessions) {
  const totals = new Map();
  for (const session of sessions) {
    const key = period.of(session);
    if (!key) continue;
    totals.set(key, (totals.get(key) || 0) + (Number(session.energyKwh) || 0));
  }
  if (totals.size === 0) return [];
  const bar = (key) => ({ key, kwh: Number((totals.get(key) || 0).toFixed(3)) });
  const keys = [...totals.keys()].sort();
  if (!keys.every((key) => period.looks.test(key))) return keys.map(bar);
  const last = keys[keys.length - 1];
  const out = [];
  for (let key = keys[0]; out.length < MAX_BARS; key = period.next(key)) {
    out.push(bar(key));
    if (key === last) break;
  }
  return out;
}

function EnergyChart({ sessions, view }) {
  const hover = useHover();
  const period = periodFor(view);
  const bars = totalsBy(period, sessions);
  if (bars.length < 2) return null;

  const peak = Math.max(...bars.map((d) => d.kwh), 0);
  /* A ceiling in whole kWh, so the bars mean the same height between one
   * look at this tab and the next. */
  const ceiling = Math.max(1, Math.ceil(peak));
  const plot = CHART_W - 2 * CHART_PAD;
  const slot = plot / bars.length;
  /* A bar with a little air either side, and never thinner than a hair:
   * a year of bars in one card is about two viewBox units each. */
  const width = Math.max(1, slot * 0.72);

  /* Which bar the pointer is over: the bars are a row of equal slots, so
   * the fraction across them is the index straight away -- across *them*,
   * which is not across the box the pointer is measured in.  See
   * `acrossPlot`. */
  const across = acrossPlot(hover.at, CHART_PAD, CHART_W);
  const at = across === null ? -1 : Math.min(bars.length - 1, Math.floor(across * bars.length));
  const under = at < 0 ? null : bars[at];
  const total = bars.reduce((n, d) => n + d.kwh, 0);
  const busiest = bars.reduce((best, d) => (d.kwh > best.kwh ? d : best), bars[0]);

  return html`<div class="grid spaced">
    <${Card}
      title=${`Energy delivered, by ${period.noun}`}
      width="full"
      actions=${html`<span class="badge">
        ${bars.length} ${period.noun}s -- ${total.toFixed(1)} kWh
      </span>`}
    >
      <div class="chart">
        <div class="plot" ref=${hover.box} ...${hover.on}>
          <svg
            viewBox=${`0 0 ${CHART_W} ${CHART_H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label=${`energy delivered in each of ${bars.length} ${period.noun}s, ${total.toFixed(1)} kilowatt-hours in all, the most in one ${period.noun} being ${busiest.kwh} in ${busiest.key}`}
          >
            ${bars.map((d, i) => {
              const height = (d.kwh / ceiling) * (CHART_H - 2 * CHART_PAD);
              return html`<rect
                class=${`col${at === i ? ' under' : ''}`}
                key=${d.key}
                x=${CHART_PAD + i * slot + (slot - width) / 2}
                y=${CHART_H - CHART_PAD - height}
                width=${width}
                height=${Math.max(0, height)}
              />`;
            })}
            <line
              class="axis"
              x1=${CHART_PAD}
              x2=${CHART_W - CHART_PAD}
              y1=${CHART_H - CHART_PAD}
              y2=${CHART_H - CHART_PAD}
              vector-effect="non-scaling-stroke"
            />
          </svg>
          ${under &&
          html`<${Hovered}
            x=${(CHART_PAD + (at + 0.5) * slot) / CHART_W}
            y=${null}
            rule=${false}
            heading=${under.key}
            lines=${[`${under.kwh} kWh`]}
          />`}
        </div>
        <div class="ends">
          <span>${period.short(bars[0].key)}</span>
          <span>${ceiling} kWh full scale</span>
          <span>${period.short(bars[bars.length - 1].key)}</span>
        </div>
      </div>
    <//>
  </div>`;
}

function SessionTable({ rows, dense }) {
  if (!rows.length) return html`<div class="empty">No sessions here.</div>`;
  return html`<div class=${`table-wrap${dense ? ' inset' : ''}`}>
    <table>
      <thead>
        <tr>
          <th>Socket</th>
          <th>Started</th>
          <th>Stopped</th>
          <th>Duration</th>
          <th class="right">Energy</th>
          <th>Tag</th>
          <th>Stopped by</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(
          (s, i) => html`<tr key=${`${s.socket}-${s.start}-${i}`}>
            <td>${s.socket ?? '—'}</td>
            <td class="data">${stamp(s.start) || '—'}</td>
            <td class="data">${stamp(s.stop) || (s.complete === false ? '(running)' : '—')}</td>
            <td>${duration(s.durationS)}</td>
            <td class="val num right">${s.energyKwh ?? '—'} kWh</td>
            <td class="data">${s.tag || '—'}</td>
            <td>${s.reason || '—'}</td>
          </tr>`
        )}
      </tbody>
    </table>
  </div>`;
}

function Summary({ view, groups, total, sessions }) {
  const [open, setOpen] = useState(null);
  if (!groups?.length) return html`<div class="empty">Nothing to group.</div>`;
  const biggest = Math.max(...groups.map((r) => Number(r.energyKwh) || 0), 0);
  const belongs = BELONGS[view];
  return html`<div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>${GROUP_HEAD[view]}</th>
          <th class="right">Sessions</th>
          <th class="right">Energy</th>
          <th class="right">Time</th>
          <th class="right">kWh/session</th>
        </tr>
      </thead>
      <tbody>
        ${groups.flatMap((r) => {
          const showing = open === r.key;
          const rows = [
            html`<tr
              key=${r.key}
              class=${`openable${showing ? ' open' : ''}`}
              tabIndex="0"
              title="the sessions behind this row"
              onClick=${() => setOpen(showing ? null : r.key)}
              onKeyDown=${(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                setOpen(showing ? null : r.key);
              }}
            >
              <td class="data">
                <span class="twist" aria-hidden="true">${showing ? '▾' : '▸'}</span>${r.key}
              </td>
              <td class="val num right">${r.sessions}</td>
              <td class="val num right"><${Energy} kwh=${r.energyKwh} of=${biggest} /></td>
              <td class="val num right">${duration(r.durationS)}</td>
              <td class="val num right">${r.averageKwh ?? '—'}</td>
            </tr>`,
          ];
          if (showing) {
            rows.push(html`<tr key=${`${r.key}-open`} class="opened">
              <td colspan="5">
                <${SessionTable}
                  dense=${true}
                  rows=${sessions.filter((s) => belongs(s, r.key))}
                />
              </td>
            </tr>`);
          }
          return rows;
        })}
        <tr class="total">
          <td>total</td>
          <td class="val num right">${total.sessions}</td>
          <td class="val num right">${total.energyKwh} kWh</td>
          <td class="val num right">${duration(total.durationS)}</td>
          <td class="val num right">${total.averageKwh ?? '—'}</td>
        </tr>
      </tbody>
    </table>
  </div>`;
}

export function Sessions({ api, busy, link }) {
  const [doc, loading, error, read] = usePanel('transactions', () => api.get('/transactions'));
  const [view, setView] = useState('month');
  const [socket, setSocket] = useState('');

  /* Titled, so both of these render as a card rather than a loose div:
   * the tab keeps the shape it will have once the read lands, instead of
   * changing from a bare block into a toolbar and a table. */
  if (error)
    return html`<${PanelError}
      error=${error}
      loading=${loading}
      onRetry=${read}
      title="Charging sessions"
    />`;
  if (!doc) {
    return html`<div>
      <${Progress} link=${link} what="Reading charging sessions" />
      <${Loading} loading=${loading} what="Reading charging sessions..." title="Charging sessions" />
    </div>`;
  }

  const all = doc.sessions || [];
  const sessions = all.filter((s) => !socket || String(s.socket) === socket);
  const sockets = [...new Set(all.map((s) => s.socket).filter(Boolean))].sort();
  /* A socket filter changes what the summary is a summary *of*, and the
   * server grouped the lot -- so with one picked, the grouping is redone
   * here over what is left rather than showing totals for sessions that
   * are not on screen. */
  const groups = socket
    ? regroup(view, sessions)
    : doc.summaries?.[view] || doc.summary || [];

  const total = socket ? sum(sessions) : doc.total;

  return html`<div>
    <div class="toolbar">
      <${Select}
        value=${view}
        onChange=${(e) => setView(e.target.value)}
        entries=${VIEWS}
      />
      <${Select}
        value=${socket}
        onChange=${(e) => setSocket(e.target.value)}
        entries=${[
          { value: '', title: 'every socket' },
          ...sockets.map((n) => ({ value: String(n), title: `socket ${n}` })),
        ]}
      />
      <button class="btn ghost" disabled=${busy || loading} onClick=${read}>
        ${loading ? 'Reading...' : 'Read again'}
      </button>
      <button class="btn ghost" disabled=${!sessions.length} onClick=${() => download(sessions)}>
        Download CSV
      </button>
      <span class="spacer"></span>
      <span class="muted small">
        ${sessions.length} session(s)${doc.truncated ? ' -- database cap reached' : ''}
      </span>
    </div>

    <${Progress} link=${link} what="Reading charging sessions" />

    ${doc.truncated &&
    html`<p class="card-note">
      The read stopped at the page cap; sessions older than these may be missing.
    </p>`}

    ${sessions.length === 0
      ? html`<div class="empty">No charging sessions in the database.</div>`
      : html`<${EnergyChart} sessions=${sessions} view=${view} />
          ${view === ''
            ? html`<${SessionTable} rows=${sessions} />`
            : html`<${Summary}
                view=${view}
                groups=${groups}
                total=${total}
                sessions=${sessions}
              />`}`}
  </div>`;
}

/* The same grouping the server does, for the one case it cannot: a socket
 * filter applied after the fact.  Keys match `transactions.by_*`. */
function regroup(view, sessions) {
  const key = {
    day: (s) => (s.start || '').slice(0, 10) || '(unknown)',
    month: (s) => (s.start || '').slice(0, 7) || '(unknown)',
    socket: (s) => (s.socket === null || s.socket === undefined ? '(unknown)' : `socket ${s.socket}`),
    tag: (s) => s.tag || '(unknown)',
  }[view];
  const out = new Map();
  for (const session of sessions) {
    const name = key(session);
    out.set(name, [...(out.get(name) || []), session]);
  }
  return [...out.keys()].sort().map((name) => ({ key: name, ...sum(out.get(name)) }));
}

function sum(rows) {
  const energy = rows.reduce((n, s) => n + (Number(s.energyKwh) || 0), 0);
  const seconds = rows.reduce((n, s) => n + (Number(s.durationS) || 0), 0);
  return {
    key: 'total',
    sessions: rows.length,
    energyKwh: Number(energy.toFixed(3)),
    durationS: seconds,
    averageKwh: rows.length ? Number((energy / rows.length).toFixed(3)) : null,
  };
}
