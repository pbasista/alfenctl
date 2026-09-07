/* The dashboard: what the station is and what it is doing right now.
 *
 * Two of these cards write as well as read.  They edit a draft and send it
 * on Apply rather than on every keystroke: there is one connection to the
 * charger, a car may be drawing current through it, and a half-typed "1" on
 * the way to "16" is a real number the station would act on.
 */

import { html, useRef, useState } from '../vendor/preact-htm.module.js';
import { Apply, EnumRow, NumRow, ToggleRow, useDraft } from './panels.js';
import { PowerChart, usePowerHistory } from './powerchart.js';

import { Card, Caveats, DASH, fmt, Help, Row } from './ui.js';

const CHARGING_WORDS = ['charging', 'ev connected', 'nfc'];
const BIG_DRIFT_S = 60;

/* The currents an installation is actually wired for -- 1-phase 16 A, a
 * 3-phase 11 kW box, a 22 kW one -- as tick marks under every slider, so
 * the ordinary answers are one drag away and land exactly.  Only the ones
 * a given slider can actually reach are offered: a tick outside the track
 * is a stop the drag never lands on. */
const COMMON_AMPS = [6, 8, 10, 13, 16, 20, 25, 32, 40, 50, 63];

/* What the sliders will not go past, if the charger says nothing else.
 * The floor is Mode 3's: the pilot cannot offer a car less than 6 A, so a
 * limit below it does not charge slowly, it does not charge (the backend's
 * `controls.MIN_CHARGE_CURRENT_A` says the same, and sends the real number
 * as `minChargeCurrentA`). */
const FALLBACK_MIN_A = 6;
const FALLBACK_MAX_A = 64;

function socketClass(state) {
  const text = (state || '').toLowerCase();
  if (CHARGING_WORDS.some((word) => text.includes(word))) return 'socket charging';
  if (text.includes('available')) return 'socket available';
  return 'socket';
}

/* `useDraft` and `Apply` -- a card's fields edited together and sent once
 * -- live in panels.js.  They were written here first and then copied
 * there when the panel tabs wanted them, which left two of each: the same
 * contract in two files, free to drift apart. */

function number(value) {

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/* Where every current slider in the Sockets card starts and stops, and what
 * each is showing, from one reading and one draft.
 *
 * The old sliders ran the property's whole range -- often 1 to 64 A -- which
 * is two things that are not true at once.  Nothing charges below 6 A: Mode
 * 3 offers the car a current as a duty cycle on the pilot and IEC 61851
 * defines nothing under that, which is why one of the charger's own states
 * is "charging power off low maxcurrent".  And nothing draws more than the
 * limit above it: the installation's caps the station, the station's caps
 * each socket.
 *
 * The socket ceiling follows the station's *draft*, not its reading, so
 * pulling the station down takes the sockets with it as you drag rather than
 * leaving them at a number that stopped meaning anything.  Anything the
 * ceiling moved is returned as `moved`, because a value the card is showing
 * is a value Apply has to write.
 *
 * A charger already set below the floor is not argued with -- its slider
 * opens down to wherever it is, so what is displayed is what is set. The
 * card's caveats are what say that such a socket will not charge.
 */
function currentBounds(live, limits, draft) {
  const floor = live.minChargeCurrentA ?? FALLBACK_MIN_A;
  const ceiling = live.maxCurrentA ?? FALLBACK_MAX_A;
  const installation = live.installationMaxCurrentA;
  const has = (amps) => amps !== null && amps !== undefined;
  /* A slider always reaches the number the charger is actually holding,
   * whichever side of the honest range that number falls.  A limit set to
   * 4 A, or a socket left above the station's, is a real setting on a real
   * charger and a control that could not show it would be lying about the
   * reading; the card's caveats are what say such a setting is a mistake. */
  const bottom = (amps) => (has(amps) ? Math.min(floor, Math.floor(amps)) : floor);
  const top = (limit, amps) => Math.max(Math.floor(limit), has(amps) ? amps : 0);

  const stationLive = live.stationMaxCurrentA;
  const stationMax = top(Math.min(ceiling, installation ?? ceiling), stationLive);
  const stationMin = Math.min(bottom(stationLive), stationMax);
  const stationValue = has(stationLive)
    ? clamp(
        Number('station' in draft ? draft.station : stationLive),
        stationMin,
        stationMax
      )
    : null;

  /* The sockets' ceiling is the station's *draft*, so dragging the station
   * down takes them with it as you watch.  Until it is dragged there is no
   * draft to enforce, and each socket keeps the room its own reading needs
   * -- the difference between "you just lowered this" and "this was already
   * set high", which are not the same thing and must not look alike. */
  const dragging = 'station' in draft;
  const sockets = new Map();
  for (const [number, amps] of limits) {
    if (!has(amps)) continue;
    const key = `socket${number}`;
    const limit = Math.min(stationMax, stationValue ?? stationMax);
    const min = bottom(amps);
    const max = Math.max(min, dragging ? Math.floor(limit) : top(limit, amps));
    const value = clamp(Number(key in draft ? draft[key] : amps), min, max);
    sockets.set(number, { min, max, value, live: amps, moved: value !== amps });
  }
  return {
    station: { min: stationMin, max: stationMax, value: stationValue, live: stationLive },
    sockets,
  };
}

/* The id of the tick list for one range, and the list itself.  One per
 * distinct range on the page: the ticks a station slider offers are not the
 * ticks a socket limited to half of it can reach. */
function ticksId(min, max) {
  return `alfen-amps-${min}-${max}`;
}

/* The tick list re-renders on every link beat with the sliders, and each
 * rewrite of an option's value attribute drops any provisional selection
 * a browser had made in its amp-picker popup -- the same failure the
 * category select had (see Select in ui.js), on the one other element
 * whose options this page rebuilds.  The range decides the whole list, so
 * an unchanged range hands the differ back the vnode it already rendered
 * and the beat never reaches the options. */
function AmpsTicks({ min, max }) {
  const prev = useRef(null);
  if (!prev.current || prev.current.min !== min || prev.current.max !== max) {
    prev.current = { min, max, vnode: html`<datalist id=${ticksId(min, max)}>
      ${COMMON_AMPS.filter((amps) => amps >= min && amps <= max).map(
        (amps) => html`<option value=${amps} key=${amps}></option>`
      )}
    </datalist>` };
  }
  return prev.current.vnode;
}

/* A current, as a slider.  Amps are a physical quantity with a small range
 * and a handful of sane answers, so dragging beats typing -- and the number
 * beside it turns amber while it is still only a draft.
 *
 * The range is the honest one rather than the one the property will accept.
 * A charger takes 0-63 A on any of these and the slider used to offer all
 * of it, which is two lies in one control: nothing charges below 6 A, and
 * nothing draws more than the limit above it -- the station's for a socket,
 * the installation's for the station.  Both ends move as those change, so
 * the ends are written under the track where they can be seen to move. */
function Amps({ value, live, min, max, onInput }) {
  const pending = Number(value) !== Number(live);
  return html`<span class="set">
    <input
      type="range"
      min=${min}
      max=${max}
      step="1"
      list=${ticksId(min, max)}
      value=${value}
      aria-label="maximum current, amps"
      onInput=${(event) => onInput(Number(event.target.value))}
    />
    <span class=${`val${pending ? ' pending' : ''}`}>${fmt(Number(value), 1)} A</span>
    <span class="bounds"><span>${fmt(min, 0)} A</span><span>${fmt(max, 0)} A</span></span>
  </span>`;
}

/* What one word of state is worth being loud about.
 *
 * The charger's own vocabulary decides: anything with "error" in it is
 * wrong, anything charging or switched on is live, "available" is settled
 * and well.  Everything else is a fact rather than a signal and stays in
 * the neutral badge, which is most of them.
 */
function tone(text) {
  const words = (text || '').toLowerCase();
  if (words.includes('error') || words.includes('fault')) return ' bad';
  if (words.includes('charging') || words.includes(' on') || words === 'on') return ' warn';
  if (words.includes('available')) return ' good';
  return '';
}

/* One piece of socket state: what it is, and what it is set to.
 *
 * These used to be a line of prose -- "relay main off, bypass off" -- which
 * reads as a sentence about the socket rather than as three switches with
 * positions.  A badge each says which words are the state.
 */
function Stat({ k, v, title }) {
  return html`<span class=${`stat${tone(title || v)}`} title=${title || ''}>
    <span class="k">${k}</span><span class="v">${v}</span>
  </span>`;
}

/* The control pilot, as its IEC 61851 letter with the whole phrase behind
 * it: "B2" is what an installer reads for, and "(vehicle connected, ready)"
 * is what makes it mean something the first time. */
function Pilot({ state }) {
  if (!state) return null;
  return html`<${Stat} k="pilot" v=${state.split(' ')[0]} title=${state} />`;
}

/* The relay block, one badge per contactor.  `status.POWER_STATES` writes
 * these as "main on, bypass off" -- two switches in one string -- so the
 * comma is the split. */
function Relay({ state }) {
  if (!state) return null;
  const parts = state.split(', ').map((part) => part.trim()).filter(Boolean);
  const named = parts.every((part) => part.includes(' '));
  if (!named) return html`<${Stat} k="relay" v=${state} />`;
  return parts.map((part) => {
    const at = part.lastIndexOf(' ');
    return html`<${Stat}
      key=${part}
      k=${part.slice(0, at)}
      v=${part.slice(at + 1)}
      title=${part}
    />`;
  });
}

/* Sockets: what each one is doing and what it is allowed to draw.
 *
 * These were two cards until the limits looked homeless on their own -- a
 * socket's maximum current is a property of that socket, so it lives in the
 * socket's own tile.  The station's own maximum then had nowhere to be but
 * a row under the tiles, where its slider started and stopped at different
 * places than theirs: two controls of the same kind, half a tile's padding
 * out of line, which is what an unfinished page looks like.  So the station
 * gets a tile too -- the same shape, the same limit row, its read-only
 * numbers where a socket keeps its state -- and every track on the card
 * shares one pair of edges.
 */
function Sockets({ status, controls, sockets, setup, onApply, readOnly, busy }) {
  const edits = useDraft();
  const live = controls || {};
  const reported = status?.sockets || [];
  /* How many sockets are on the wall.  A single-socket station still
   * answers for the second one -- its firmware builds the whole object
   * dictionary either way, and its own boot log says so -- which put a
   * phantom socket, with a slider, on the dashboard of a station that has
   * one.  So the count decides, not the reply.  The backend trims its own
   * view the same way; this is the belt to that pair of braces, and covers
   * a status reading taken before the count had arrived. */
  const count = sockets || live.socketCount || 0;
  const real = (n) => !count || n <= count;
  const limits = new Map(
    (live.sockets || []).filter((s) => real(s.number)).map((s) => [s.number, s.maxCurrentA])
  );
  const numbers = [...new Set([...reported.map((s) => s.number), ...limits.keys()])]
    .filter(real)
    .sort((a, b) => a - b);
  const safe = status?.activeSafeCurrentA;
  const editable = !readOnly;
  const { station, sockets: socketBounds } = currentBounds(live, limits, edits.draft);

  /* What the station is, as opposed to what it is set to: the two limits
   * above its own, which are read-only here.  They sit where a socket keeps
   * its state, so the tile below them is the same tile.  The balancing mode
   * is the same kind of fact -- it decides whether these numbers are being
   * managed at all -- so it joins them, as a word rather than amps. */
  const stationFacts = [
    ['installation', live.installationMaxCurrentA, (a) => `${fmt(a, 1)} A`],
    ['safe', safe, (a) => `${fmt(a, 1)} A`],
    setup?.loadBalancing ? ['balancing', setup.loadBalancing, (w) => w] : null,
    setup?.smartCharging ? ['smart charging', 'on', (w) => w] : null,
  ]
    .filter(Boolean)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v, render]) => ({ k, v: render(v) }));

  if (!numbers.length && station.value === null) {
    return html`<${Card} title="Sockets"><div class="empty">No socket state reported.</div><//>`;
  }

  /* Everything the card is showing goes in the write, not everything that
   * was dragged: a socket the station limit pushed down is on screen at its
   * new number and has to be on the charger at it too. */
  const send = () => {
    const payload = {};
    if (station.value !== null && station.value !== station.live) {
      payload.stationMaxCurrentA = number(station.value);
    }
    const changed = numbers
      .filter((n) => socketBounds.get(n)?.moved)
      .map((n) => ({ number: n, maxCurrentA: number(socketBounds.get(n).value) }));
    if (changed.length) payload.sockets = changed;
    if (!Object.keys(payload).length) {
      edits.clear();
      return;
    }
    onApply(payload).then(edits.clear, () => {});
  };

  /* One current, in the row every tile on this card keeps it in. */
  const limitRow = (bound, onInput) => {
    if (!bound || bound.value === null) return null;
    return html`<div class="limit">
      <span class="lab">max current</span>
      ${editable
        ? html`<${Amps}
            value=${bound.value}
            live=${bound.live}
            min=${bound.min}
            max=${bound.max}
            onInput=${onInput}
          />`
        : html`<span class="val">${fmt(bound.live, 1)} A</span>`}
    </div>`;
  };

  /* One tick list per range in use, rendered once and pointed at by id. */
  const ranges = new Map();
  if (editable) {
    for (const bound of [station, ...socketBounds.values()]) {
      if (bound.value === null) continue;
      ranges.set(ticksId(bound.min, bound.max), [bound.min, bound.max]);
    }
  }

  return html`<${Card} title="Sockets">
    ${[...ranges].map(([id, [lo, hi]]) => html`<${AmpsTicks} key=${id} min=${lo} max=${hi} />`)}
    <div class="sockets">
      ${numbers.map((n) => {
        const socket = reported.find((s) => s.number === n) || { number: n };
        return html`<div class=${socketClass(socket.state)} key=${n}>
          <div class="head">
            <span class="state">${socket.state || 'unknown'}</span>
            <span class="badge">socket ${n}</span>
          </div>
          ${socket.state &&
          html`<div class="sub">
            <${Pilot} state=${socket.mode3} />
            <${Relay} state=${socket.power} />
            ${socket.led && html`<${Stat} k="led" v=${socket.led} />`}
          </div>`}
          ${limitRow(socketBounds.get(n), (v) => edits.set(`socket${n}`, v))}
        </div>`;
      })}

      ${(station.value !== null || stationFacts.length > 0) &&
      html`<div class="socket station">
        <div class="head">
          <span class="spacer"></span>
          <span class="badge">station</span>
        </div>
        ${stationFacts.length > 0 &&
        html`<div class="sub">
          ${stationFacts.map(
            (fact) => html`<${Stat} key=${fact.k} k=${fact.k} v=${fact.v} />`
          )}
        </div>`}
        ${limitRow(station, (v) => edits.set('station', v))}
      </div>`}
    </div>

    <${Caveats} items=${live.warnings} />
    ${editable && html`<${Apply} edits=${edits} busy=${busy} onApply=${send} />`}
  <//>`;
}

/* Which of the three phases the station is actually using.
 *
 * A station whose `mainMaxAllowedPhases` is 1 charges on one phase, and
 * the other two tiles are then a pair of zeroes that look like a fault
 * rather than like a setting.  So they are drawn dimmed, and the card
 * says which setting did it -- a tile that is empty because nothing is
 * happening and a tile that is empty because the station was told to use
 * one phase are not the same thing, and must not look alike.
 *
 * `null` when nothing has said: the load balancing document is read once
 * per station, and until it lands no phase is greyed out on a guess.
 */
function phaseUse(allowed) {
  if (allowed !== 1 && allowed !== 3) return null;
  return allowed;
}

function Power({ status, station, activity, live, allowedPhases }) {
  const samples = usePowerHistory(status, station);
  const power = status ? status.activePowerW : null;
  const kw = power === null || power === undefined ? null : power / 1000;
  const volts = status?.voltagesV || [];
  const amps = status?.currentsA || [];
  /* Read, not worked out: volts times amps is apparent power, and the
   * difference between that and this is the power factor.  The meter
   * answers for it per phase (2221_13..15), so the card asks. */
  const watts = status?.powersW || [];
  const inUse = phaseUse(allowedPhases);
  /* The meter's own lifetime totals, when the charger keeps them: kW says
   * what is happening now, and this says what has happened -- which is the
   * number a session is measured against.  A charger that does not answer
   * for the register gets no row rather than a row of nothing, and the
   * consumed row waits until there is something to consume: it counts energy
   * going the other way, so on a station that cannot do that it is zero for
   * ever and says nothing. */
  const delivered = status?.energyDeliveredKWh;
  const totals = [];
  if (delivered !== null && delivered !== undefined) {
    totals.push(['Energy delivered', delivered]);
  }
  if (status?.energyConsumedKWh) {
    totals.push(['Energy consumed', status.energyConsumedKWh]);
  }
  return html`<${Card}
    title="Live meter"
    actions=${inUse === 1 && html`<span class="badge">single phase</span>`}
  >
    <div class=${`metric${kw ? '' : ' calm'}`}>
      <span class="metric-value">${kw === null ? DASH : fmt(kw, 2)}</span>
      <span class="metric-unit">kW</span>
    </div>
    <${PowerChart} samples=${samples} activity=${activity} live=${live} />
    ${(volts.length || amps.length || watts.length) &&
    html`<div class="phases">
      ${[0, 1, 2].map((i) => {
        const unused = inUse === 1 && i > 0;
        return html`<div class=${`phase${unused ? ' unused' : ''}`} key=${i}>
          <div class="p">
            L${i + 1}${unused && html`<span class="off" title="the station is set to charge on one phase"> off</span>`}
          </div>
          <div class="n">${fmt(volts[i], 1)}<span class="metric-unit"> V</span></div>
          <div class="n">${fmt(amps[i], 1)}<span class="metric-unit"> A</span></div>
          <div class="n">
            ${watts[i] === null || watts[i] === undefined ? DASH : fmt(watts[i] / 1000, 2)}<span
              class="metric-unit"
            >
              kW</span
            >
          </div>
        </div>`;
      })}
    </div>`}
    ${totals.length > 0 &&
    html`<div class="rows spaced">
      ${totals.map(
        ([label, value]) => html`<${Row} key=${label} k=${label} v=${`${fmt(value, 1)} kWh`} />`
      )}
    </div>`}
  <//>`;
}

/* The ends of the temperature track, if the charger says nothing else. */
const FALLBACK_ALARM_MIN_C = -40;
const FALLBACK_ALARM_MAX_C = 100;

/* Where the temperature card's track starts and stops, and where the two
 * limits sit on it.
 *
 * The same rule the currents follow: the track always reaches the numbers
 * the charger is actually holding, whichever side of the sensible range
 * they fall, because a control that could not show a setting would be lying
 * about it.  And the two ends do not cross -- dragging one into the other
 * pushes it along, which is why a limit nobody touched can still be part of
 * the write.
 */
function alarmBounds(live, now, draft) {
  const has = (value) => value !== null && value !== undefined;
  const lowLive = live.temperatureAlarmLowC;
  const highLive = live.temperatureAlarmHighC;
  const known = [lowLive, highLive, now].filter(has);
  const min = Math.min(
    live.minAlarmTemperatureC ?? FALLBACK_ALARM_MIN_C,
    ...known.map((value) => Math.floor(value))
  );
  const max = Math.max(
    live.maxAlarmTemperatureC ?? FALLBACK_ALARM_MAX_C,
    ...known.map((value) => Math.ceil(value))
  );
  let low = has(lowLive)
    ? clamp(Number('low' in draft ? draft.low : lowLive), min, max)
    : null;
  let high = has(highLive)
    ? clamp(Number('high' in draft ? draft.high : highLive), min, max)
    : null;
  if (low !== null && high !== null && low >= high) {
    if ('low' in draft) high = Math.min(max, low + 1);
    else low = Math.max(min, high - 1);
  }
  return { min, max, low, high, lowLive, highLive };
}

/* One temperature, as a slider, in the shape the currents use. */
function Degrees({ value, live, min, max, label, onInput }) {
  const pending = Number(value) !== Number(live);
  return html`<span class="set">
    <input
      type="range"
      min=${min}
      max=${max}
      step="1"
      value=${value}
      aria-label=${label}
      onInput=${(event) => onInput(Number(event.target.value))}
    />
    <span class=${`val${pending ? ' pending' : ''}`}>${fmt(Number(value), 0)} °C</span>
  </span>`;
}

/* Temperature, the display and the LEDs: the station's own conditions.
 *
 * Two cards until the temperature one had nothing in it but a reading and
 * two sliders -- a card and a half of content spread over two cards, in a
 * grid where a card is as tall as the tallest in its row.  They belong
 * together in any case: both are the station itself rather than what it is
 * charging, and both are settings somebody comes back to -- the alarm band
 * with the seasons, the brightness the first evening it is too bright.
 *
 * The reading and its two limits still lead, because they only mean
 * anything against each other (42 C is fine under a 60 C alarm and a fault
 * under a 40 C one) and the band is what says which.  Not every station has
 * a screen -- an Eve Single S-line has LEDs and nothing else -- so the card
 * says which it is rather than offering a brightness slider that quietly
 * means something narrower than it looks: the setting is `sysIntensity`,
 * which drives the LEDs as well, so it stays either way.
 *
 * One draft and one Apply for the lot, like every other card here: they
 * write to the same endpoint, and a card that is edited as a whole is the
 * rule this page is built on.
 */
function Conditions({ status, controls, display, setup, onApply, readOnly, busy }) {
  const edits = useDraft();
  const live = controls || {};

  const now = status?.temperatureC ?? null;
  const { min, max, low, high, lowLive, highLive } = alarmBounds(live, now, edits.draft);
  const hasTemperature = now !== null || low !== null || high !== null;
  const bandEditable = !readOnly && (low !== null || high !== null);
  const at = (value) => clamp(((value - min) / (max - min)) * 100, 0, 100);
  const cold = now !== null && low !== null && now < low;
  const hot = now !== null && high !== null && now > high;

  const level = edits.get('intensity', live.intensity);
  const auto = edits.get('autoDim', live.autoDim);
  // `undefined` is "the charger was not asked", which is not "no".
  const noScreen = display?.present === false;
  const hasIntensity = live.intensity !== null && live.intensity !== undefined;
  const hasAutoDim = live.autoDim !== null && live.autoDim !== undefined;
  const language = setup?.language;
  const hasDisplay = hasIntensity || hasAutoDim || Boolean(language);
  /* The on-screen price is a display setting, not a tariff -- nothing on
   * the charger bills anybody -- so it lives here, under what the screen
   * shows, rather than in a card of its own. */
  const money = (value) =>
    value === null || value === undefined
      ? null
      : `${Number(value).toFixed(2)}${setup?.priceCurrency ? ` ${setup.priceCurrency}` : ''}`;
  const priceRows = [
    ['Start price', money(setup?.priceStart)],
    ['Price per kWh', money(setup?.pricePerKwh)],
    ['Price per minute', money(setup?.pricePerMinute)],
  ].filter(([, v]) => v !== null);

  const badge = noScreen && html`<span class="badge warn">no display</span>`;
  const title = 'Temperature, display and LEDs';
  /* A station that reports a temperature and nothing else settable has the
   * headline and the band and no rows at all, and an empty row list is a
   * gap where a reader looks for a field. */
  const rows =
    low !== null ||
    high !== null ||
    hasIntensity ||
    hasAutoDim ||
    Boolean(language) ||
    (display?.present && display.width) ||
    priceRows.length > 0;

  if (!hasTemperature && !hasDisplay) {
    return html`<${Card} title=${title} actions=${badge}>
      <div class="empty">
        This charger reports neither a temperature nor a brightness setting.
      </div>
    <//>`;
  }

  const send = () => {
    const payload = {};
    if (low !== null && low !== lowLive) payload.temperatureAlarmLowC = low;
    if (high !== null && high !== highLive) payload.temperatureAlarmHighC = high;
    if ('intensity' in edits.draft) payload.intensity = number(edits.draft.intensity);
    if ('autoDim' in edits.draft) payload.autoDim = Boolean(edits.draft.autoDim);
    if (!Object.keys(payload).length) {
      edits.clear();
      return;
    }
    onApply(payload).then(edits.clear, () => {});
  };

  return html`<${Card} title=${title} actions=${badge}>
    ${noScreen &&
    html`<p class="note">
      This station has no display: there is nowhere to put a logo, and the
      brightness below reaches its LEDs.
    </p>`}

    ${hasTemperature &&
    html`<div class=${`metric${cold || hot ? '' : ' calm'}`}>
      <span class="metric-value">${now === null ? DASH : fmt(now, 1)}</span>
      <span class="metric-unit">°C</span>
      ${(cold || hot) &&
      html`<span class="badge warn" style="margin-left:auto">
        ${hot ? 'above the high alarm' : 'below the low alarm'}
      </span>`}
    </div>

    <div class="tempband">
      <div class="track">
        ${low !== null &&
        high !== null &&
        html`<span
          class="ok"
          style=${`left:${at(low)}%;right:${100 - at(high)}%`}
          title=${`no alarm between ${fmt(low, 0)} and ${fmt(high, 0)} °C`}
        ></span>`}
        ${now !== null &&
        html`<span
          class=${`now${cold || hot ? ' bad' : ''}`}
          style=${`left:${at(now)}%`}
          title=${`${fmt(now, 1)} °C now`}
        ></span>`}
      </div>
      <div class="ends"><span>${fmt(min, 0)} °C</span><span>${fmt(max, 0)} °C</span></div>
    </div>`}

    ${rows &&
    html`<div class="rows spaced">
      ${low !== null &&
      html`<${Row}
        k="Alarm below"
        v=${bandEditable
          ? html`<${Degrees}
              value=${low}
              live=${lowLive}
              min=${min}
              max=${max}
              label="low temperature alarm, degrees Celsius"
              onInput=${(v) => edits.set('low', v)}
            />`
          : `${fmt(lowLive, 0)} °C`}
      />`}
      ${high !== null &&
      html`<${Row}
        k="Alarm above"
        v=${bandEditable
          ? html`<${Degrees}
              value=${high}
              live=${highLive}
              min=${min}
              max=${max}
              label="high temperature alarm, degrees Celsius"
              onInput=${(v) => edits.set('high', v)}
            />`
          : `${fmt(highLive, 0)} °C`}
      />`}
      ${hasIntensity &&
      html`<${Row}
        k="Brightness"
        title="one setting for the screen and the LEDs both"
        v=${readOnly
          ? `${level}%`
          : html`<span class="set">
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value=${level}
                aria-label="display and LED brightness, percent"
                onInput=${(e) => edits.set('intensity', e.target.value)}
              />
              <span class=${`val${Number(level) !== Number(live.intensity) ? ' pending' : ''}`}>
                ${level}%
              </span>
            </span>`}
      />`}
      ${hasAutoDim &&
      html`<${ToggleRow}
        k="Auto dim"
        value=${auto}
        onChange=${(v) => edits.set('autoDim', v)}
        disabled=${readOnly}
        label="when idle"
        title="dim the display and the LEDs when nothing is happening at the station"
      />`}
      ${language &&
      html`<${Row}
        k="Language"
        v=${language}
        title="the language the charger's own display speaks"
      />`}
      ${display?.present &&
      display.width &&
      html`<${Row} k="Logo area" v=${`${display.width} × ${display.height}`} />`}
      ${priceRows.map(
        ([k, v]) => html`<${Row}
          key=${k}
          k=${k}
          v=${v}
          title="what the screen shows a session costing -- the charger bills nobody"
        />`
      )}
    </div>`}
    ${!readOnly && html`<${Apply} edits=${edits} busy=${busy} onApply=${send} />`}
  <//>`;
}

function Identity({ info, hardware, setup, clock, onSync, readOnly, busy }) {
  /* The clock lives here: the identity is the station's "who and since
   * when", and a clock nobody set is part of that -- its drift badge is
   * what says a station was never given the time of day. */
  const drifted =
    clock && clock.driftSeconds !== null && Math.abs(clock.driftSeconds) > BIG_DRIFT_S;
  const plain = (stamp) => (stamp || '').replace('T', ' ');
  return html`<${Card}
    title="Station"
    actions=${!readOnly &&
    clock &&
    html`<button class="btn small" disabled=${busy} onClick=${onSync}>Sync clock</button>`}
  >
    <div class="rows">
      <${Row} k="Object ID" v=${info?.objectId} data=${true} />
      <${Row} k="Identity" v=${info?.identity} data=${true} />
      <${Row} k="Model" v=${info?.model} data=${true} />
      <${Row} k="Firmware" v=${info?.firmware} data=${true} />
      <${Row} k="Sockets" v=${info?.sockets} />
      <${Row} k="Uptime" v=${setup?.uptime} title="time since the last reboot" />
      ${clock &&
      html`<${Row} k="Local time" v=${plain(clock.local)} data=${true} title=${`time zone ${clock.zone || 'unknown'}`} />
      <${Row}
        k="Clock difference"
        v=${html`<span class=${drifted ? 'badge warn' : ''}>${clock.drift}</span>`}
        title="the charger keeps UTC and derives local time from a stored offset"
      />`}
      ${setup?.latitude !== null &&
      setup?.latitude !== undefined &&
      setup?.longitude !== null &&
      setup?.longitude !== undefined &&
      html`<${Row}
        k="Position"
        v=${`${fmt(setup.latitude, 5)}, ${fmt(setup.longitude, 5)}`}
        title="the position the station was given at installation"
      />`}
      ${(hardware || []).map((item) => html`<${Row} key=${item.label} k=${item.label} v=${item.value} />`)}
    </div>
  <//>`;
}

/* The charger keeps UTC and displays local time derived from a stored
 * offset; both are shown in the Station card, next to the drift badge. */

/* The device-unique id, when the charger said anything with it.
 *
 * It is what a vendor derives a key from, so it earns a row on a station
 * that reports one -- and a real NG910 reports zeros, which is a row that
 * says nothing.  Anything that is not padding, dots and zeros counts. */
function realUniqueId(value) {
  const text = String(value ?? '').trim();
  return text && /[^0.\-\s]/.test(text) ? text : null;
}

function License({ license, onInstall, readOnly, busy }) {
  const [key, setKey] = useState('');
  const [open, setOpen] = useState(false);
  if (license && license.supported === false) {
    return html`<${Card} title="License">
      <div class="empty">This firmware does not use license keys.</div>
    <//>`;
  }
  /* Every feature the model can have, installed or not: a chip list of what
   * a station holds says nothing about what is left of its licence, which is
   * most of why anyone opens this card. */
  const features = license?.features || [];
  const unlocked = features.filter((feature) => feature.on).length;
  const uniqueId = realUniqueId(license?.uniqueId);
  return html`<${Card}
    title="License"
    actions=${!readOnly && html`<button class="btn small" onClick=${() => setOpen(!open)}>${open ? 'Cancel' : 'Install a key'}</button>`}
  >
    <div class="rows">
      ${uniqueId && html`<${Row} k="Unique ID" v=${uniqueId} data=${true} />`}
      <${Row} k="Key" v=${license?.key} data=${true} />
      ${features.length > 0 &&
      html`<${Row} k="Features" v=${`${unlocked} of ${features.length} unlocked`} />`}
    </div>
    <div class="chips spaced">
      ${features.length
        ? features.map(
            (feature) => html`<span
              class=${`chip ${feature.on ? 'on' : 'off'}`}
              key=${feature.name}
              title=${feature.on ? 'installed' : 'not in this license'}
            >
              ${feature.name}
            </span>`
          )
        : html`<span class="muted">This charger reports no feature list.</span>`}
    </div>
    ${open &&
    html`<div class="card-foot">
      <input
        type="text"
        class="grow"
        placeholder="0011.2233.4455.6677.8899.AABB"
        value=${key}
        onInput=${(e) => setKey(e.target.value)}
      />
      <button
        class="btn primary"
        disabled=${busy || !key.trim()}
        onClick=${() => {
          onInstall(key.trim());
          setKey('');
          setOpen(false);
        }}
      >
        Install
      </button>
    </div>`}
  <//>`;
}

/* The health verdict: what the doctor would say, asked for on demand.
 *
 * A full pass takes seconds (it reads every panel), so it is not run on
 * page load; the card offers it, and holds the findings once it has.  It
 * used to be a bare button above the grid, which is the one thing on the
 * page that was not a card and looked it.
 */
function Doctor({ onDoctor, busy }) {
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);
  const run = async () => {
    setRunning(true);
    try {
      const doc = await onDoctor();
      setReport(doc.doctor);
    } finally {
      setRunning(false);
    }
  };

  const { counts = {}, findings = [] } = report || {};
  const worst = !report
    ? null
    : counts.error
      ? 'error'
      : counts.warning
        ? 'warning'
        : findings.length
          ? 'note'
          : 'clean';
  const badge = report
    ? html`<span class=${`badge ${worst === 'error' ? 'bad' : worst === 'warning' ? 'warn' : 'good'}`}>
        ${worst === 'clean'
          ? 'nothing to report'
          : `${counts.error || 0} error, ${counts.warning || 0} warning, ${counts.note || 0} note`}
      </span>`
    : null;

  return html`<${Card} title="Health" actions=${badge}>
    ${!report
      ? html`<div class="empty">
          One pass over every panel, with the same findings the terminal
          prints. It takes a few seconds.
        </div>`
      : findings.length === 0
        ? html`<div class="empty">Nothing to report -- this charger looks well.</div>`
        : html`<div class="rows">
            ${findings.map(
              (f, i) => html`<${Row}
                key=${i}
                k=${f.area}
                title=${f.fix || ''}
                v=${html`<span
                  class=${`badge ${f.severity === 'error' ? 'bad' : f.severity === 'warning' ? 'warn' : ''}`}
                >
                  ${f.detail}
                </span>`}
              />`
            )}
          </div>`}
    <div class="card-foot">
      <button class="btn" disabled=${busy || running} onClick=${run}>
        ${running ? 'Checking...' : report ? 'Check again' : 'Run the check'}
      </button>
    </div>
  <//>`;
}

/* Load balancing, and the three settings worth changing from here.
 *
 * This was a card of five read-only rows and a sentence saying the
 * controls were on another tab -- which is a strange thing for a dashboard
 * to say about the answer to "why is it only drawing 6 A", since that
 * answer is usually "because one of these is set to what it is set to".
 * So the two switches that decide whether the station is being managed at
 * all, and the two currents that decide what it falls back to, are
 * editable here.  The rest -- the meter protocol, the phases, solar -- is
 * still a tab away, because it is configuration rather than a decision
 * anyone makes while looking at a charging car.
 *
 * It writes to the same endpoint the Charging tab does, and hands the
 * reply to the panel store, so the full editor already agrees with this
 * card by the time anybody opens it.
 */
/* The load balancing mode: one setting made of two register bits.
 *
 * The charger keeps them in one byte (`STATIC_BIT` and `ACTIVE_BIT` in
 * loadbalancing.py) and the vendor's app offers them as two checkboxes,
 * which is what this card offered too -- with the mode those two add up to
 * printed above them as a read-only word.  So the one row that says what
 * the station is doing was the one row that could not be changed, and the
 * thing anybody opens this card for -- "stop managing it", "manage it
 * against the meter" -- was a puzzle in two parts with its answer written
 * out beside it.
 *
 * The four combinations are four options.  The Charging tab still has the
 * two switches for anyone who wants to think in bits; here it is the one
 * question the dashboard is being asked.
 */
const MODES = {
  off: { title: 'off -- not managed', bits: { static: false, active: false } },
  static: { title: 'static -- cap against the feed', bits: { static: true, active: false } },
  active: { title: 'active -- follow the meter', bits: { static: false, active: true } },
  both: { title: 'static + active', bits: { static: true, active: true } },
};

const MODE_TITLES = Object.fromEntries(
  Object.entries(MODES).map(([key, mode]) => [key, mode.title])
);

/* Which of the four a reading is.  `null` for either bit is a charger that
 * has not answered for the register, and is not "off": it falls through to
 * no option at all, so the select shows the blank rather than claiming the
 * station is unmanaged. */
function modeKey(isStatic, isActive) {
  if (isStatic === null || isStatic === undefined) return null;
  if (isActive === null || isActive === undefined) return null;
  return isStatic ? (isActive ? 'both' : 'static') : isActive ? 'active' : 'off';
}

function BalancingSummary({ lb, onWrite, readOnly, busy }) {
  const edits = useDraft();
  if (!lb) return null;
  const get = (key) => edits.get(key, lb[key]);
  const bounds = lb.bounds || {};
  const editable = !readOnly && Boolean(onWrite);
  const mode = edits.get('mode', modeKey(lb.static, lb.active));

  const send = () => {
    const { mode: picked, ...payload } = edits.draft;
    /* The blank option is "the charger has not said", which is not a mode
     * anybody can be put into: picking it writes nothing. */
    if (MODES[picked]) Object.assign(payload, MODES[picked].bits);
    if (!Object.keys(payload).length) {
      edits.clear();
      return;
    }
    onWrite(payload).then(edits.clear, () => {});
  };

  return html`<${Card} title="Load balancing">
    <${Help} summary="The mode and the currents; the rest is on the Charging tab.">
      The phases, the meter's data source and solar charging stay in the
      full editor there: those are configuration rather than a decision
      anybody makes while looking at a charging car. This card was a
      sentence saying so, printed under its last field.
    <//>
    <div class="rows">
      <${EnumRow}
        k="Mode"
        readOnly=${!editable}
        value=${mode}
        table=${MODE_TITLES}
        kind="text"
        onChange=${(v) => edits.set('mode', v)}
        disabled=${busy}
        includeBlank
        title="whether the station is managed at all, and against what"
      />
      <${NumRow}
        k="Safe current"
        readOnly=${!editable}
        value=${get('safeCurrentA')}
        live=${lb.safeCurrentA}
        min=${bounds.minSafeCurrentA}
        max=${bounds.maxSafeCurrentA}
        unit="A"
        onChange=${(v) => edits.set('safeCurrentA', v)}
        disabled=${busy}
        title="what the station falls back to when nothing is managing it"
      />
      ${lb.maxMeterCurrentA !== null &&
      lb.maxMeterCurrentA !== undefined &&
      html`<${NumRow}
        k="Max meter current"
        readOnly=${!editable}
        value=${get('maxMeterCurrentA')}
        live=${lb.maxMeterCurrentA}
        min=${bounds.minMeterCurrentA}
        max=${bounds.maxMeterCurrentA}
        unit="A"
        onChange=${(v) => edits.set('maxMeterCurrentA', v)}
        disabled=${busy}
        title="what the supply behind the station can carry"
      />`}
      ${lb.protocol !== null &&
      lb.protocol !== undefined &&
      html`<${EnumRow}
        k="Meter protocol"
        readOnly=${!editable}
        value=${get('protocol')}
        table=${lb.options?.protocols}
        onChange=${(v) => edits.set('protocol', v)}
        disabled=${busy}
        includeBlank
        title="which meter the station listens to, and over what"
      />`}
      ${lb.solarMode !== null &&
      lb.solarMode !== undefined &&
      lb.solarMode !== 0 &&
      html`<${Row} k="Solar" v=${lb.options?.solarModes?.[lb.solarMode]} />`}
    </div>
    <${Caveats}
      items=${(lb.warnings || []).map((w) => ({ short: w, detail: w }))}
    />
    ${editable && html`<${Apply} edits=${edits} busy=${busy} onApply=${send} />`}
  <//>`;
}

export function Dashboard({
  data,
  status,
  station,
  activity,
  liveUpdates,
  onSync,
  onLicense,
  onControls,
  onBalancing,
  onReload,
  onDoctor,
  readOnly,
  busy,
}) {
  if (!data) {
    return html`<div class="empty">
      Nothing read yet.
      <div class="actions-row centred">
        <button class="btn primary" onClick=${onReload} disabled=${busy}>Read the charger</button>
      </div>
    </div>`;
  }
  const live = status || data.status;
  return html`<div>
    <div class="grid">
      <${Sockets}
        status=${live}
        controls=${data.controls}
        sockets=${data.info?.sockets}
        setup=${data.setup}
        onApply=${onControls}
        readOnly=${readOnly}
        busy=${busy}
      />
      <${Power}
        status=${live}
        station=${station}
        activity=${activity}
        live=${liveUpdates}
        allowedPhases=${data.loadbalancing?.maxAllowedPhases}
      />
      <${Conditions}
        status=${live}
        controls=${data.controls}
        display=${data.display}
        setup=${data.setup}
        onApply=${onControls}
        readOnly=${readOnly}
        busy=${busy}
      />
      <${BalancingSummary}
        lb=${data.loadbalancing}
        onWrite=${onBalancing}
        readOnly=${readOnly}
        busy=${busy}
      />
      <${Identity}
        info=${data.info}
        hardware=${data.hardware}
        setup=${data.setup}
        clock=${data.clock}
        onSync=${onSync}
        readOnly=${readOnly}
        busy=${busy}
      />
      <${License} license=${data.license} onInstall=${onLicense} readOnly=${readOnly} busy=${busy} />
      <${Doctor} onDoctor=${onDoctor} busy=${busy} />
    </div>
  </div>`;
}
