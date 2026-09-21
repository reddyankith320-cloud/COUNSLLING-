// Date helpers that are always evaluated in the counselor's timezone (IST),
// regardless of where the server is hosted. `toISOString()` is UTC and gives
// the wrong calendar day after 5:30 PM IST, so never use it for "today".

const TZ = 'Asia/Kolkata';

/**
 * Current date/time parts in IST.
 * @returns {{ date: string, time: string }} e.g. { date: '2026-09-20', time: '18:05' }
 */
function nowIST() {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date());

  const get = (type) => parts.find(p => p.type === type).value;
  const hour = get('hour') === '24' ? '00' : get('hour');

  return {
    date: `${get('year')}-${get('month')}-${get('day')}`,
    time: `${hour}:${get('minute')}`,
  };
}

/** Today's calendar date in IST as YYYY-MM-DD. */
function todayIST() {
  return nowIST().date;
}

/** Format a JS Date (or pg DATE value) as YYYY-MM-DD in IST. */
function toDateString(d) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(d));
  const get = (type) => parts.find(p => p.type === type).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** '18:00' -> '6:00 PM' */
function to12Hour(time) {
  const [h, m] = time.split(':');
  let hour = parseInt(h, 10);
  const ampm = hour >= 12 ? 'PM' : 'AM';
  hour = hour % 12 || 12;
  return `${hour}:${m} ${ampm}`;
}

module.exports = { TZ, nowIST, todayIST, toDateString, to12Hour };
