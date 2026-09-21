import React, { useState, useEffect, useCallback } from 'react';
import { Calendar as CalendarIcon, Lock, Trash2, Plus, Loader2, Clock } from 'lucide-react';
import DatePicker from 'react-datepicker';
import { format } from 'date-fns';
import api from '../../services/api';
import toast from 'react-hot-toast';

// pg returns DATE columns as midnight-UTC timestamps; take the date part only
// so it doesn't shift a day in browsers ahead of UTC.
const parseDate = (d) => new Date(`${String(d).slice(0, 10)}T00:00:00`);
const fmtDate = (d) => format(parseDate(d), 'EEE, dd MMM yyyy');
const to12h = (t) => {
  if (!t) return '';
  const [h, m] = String(t).substring(0, 5).split(':');
  const hour = parseInt(h, 10);
  return `${hour % 12 || 12}:${m} ${hour >= 12 ? 'PM' : 'AM'}`;
};

const Panel = ({ icon: Icon, tone, title, subtitle, children }) => (
  <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 flex flex-col">
    <div className="flex items-center gap-3 mb-6">
      <div className={`w-10 h-10 rounded-xl ${tone} flex items-center justify-center shrink-0`}>
        <Icon size={20} />
      </div>
      <div>
        <h3 className="text-lg font-bold text-slate-800">{title}</h3>
        <p className="text-sm text-slate-500">{subtitle}</p>
      </div>
    </div>
    {children}
  </div>
);

const ListRow = ({ primary, secondary, onRemove, title }) => (
  <div className="flex justify-between items-center p-3 border border-slate-100 bg-white hover:bg-slate-50 rounded-xl transition-colors">
    <div className="min-w-0">
      <p className="font-medium text-slate-800 text-sm">{primary}</p>
      {secondary && <p className="text-xs text-slate-500 truncate">{secondary}</p>}
    </div>
    <button
      onClick={onRemove}
      className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"
      title={title}
    >
      <Trash2 size={16} />
    </button>
  </div>
);

const SlotManager = () => {
  const [holidays, setHolidays] = useState([]);
  const [blockedDates, setBlockedDates] = useState([]);
  const [blockedSlots, setBlockedSlots] = useState([]);
  const [timeSlots, setTimeSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null);

  // Forms state
  const [holidayDate, setHolidayDate] = useState(null);
  const [holidayReason, setHolidayReason] = useState('');
  const [blockDate, setBlockDate] = useState(null);
  const [blockReason, setBlockReason] = useState('');
  const [slotDate, setSlotDate] = useState(null);
  const [slotTime, setSlotTime] = useState('');
  const [slotReason, setSlotReason] = useState('');

  const fetchData = useCallback(async () => {
    try {
      const [blockedRes, holRes, slotsRes, timesRes] = await Promise.all([
        api.get('/slots/blocked'),
        api.get('/slots/holidays'),
        api.get('/slots/blocked-slots'),
        api.get('/slots/time-slots'),
      ]);
      setBlockedDates(blockedRes.data.blockedDates || []);
      setHolidays(holRes.data.holidays || []);
      setBlockedSlots(slotsRes.data.blockedSlots || []);
      setTimeSlots(timesRes.data.timeSlots || []);
    } catch (error) {
      console.error(error);
      toast.error('Failed to load availability settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const run = async (key, fn, successMsg) => {
    setSaving(key);
    try {
      await fn();
      toast.success(successMsg);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Something went wrong');
    } finally {
      setSaving(null);
    }
  };

  const handleAddHoliday = (e) => {
    e.preventDefault();
    if (!holidayDate) return toast.error('Please select a date');
    run('holiday', async () => {
      await api.post('/slots/holidays', { date: format(holidayDate, 'yyyy-MM-dd'), reason: holidayReason });
      setHolidayDate(null);
      setHolidayReason('');
    }, 'Holiday added');
  };

  const handleRemoveHoliday = (id) => {
    if (!window.confirm('Remove this holiday?')) return;
    run(`holiday-${id}`, () => api.delete(`/slots/holidays/${id}`), 'Holiday removed');
  };

  const handleBlockDate = (e) => {
    e.preventDefault();
    if (!blockDate) return toast.error('Please select a date');
    run('block', async () => {
      await api.post('/slots/block', { date: format(blockDate, 'yyyy-MM-dd'), reason: blockReason });
      setBlockDate(null);
      setBlockReason('');
    }, 'Date blocked');
  };

  const handleUnblockDate = (dateStr) => {
    if (!window.confirm('Unblock this date?')) return;
    run(`unblock-${dateStr}`, () => api.post('/slots/unblock', { date: dateStr }), 'Date unblocked');
  };

  const handleBlockSlot = (e) => {
    e.preventDefault();
    if (!slotDate) return toast.error('Please select a date');
    if (!slotTime) return toast.error('Please select a time slot');
    run('slot', async () => {
      await api.post('/slots/block-slot', { date: format(slotDate, 'yyyy-MM-dd'), startTime: slotTime, reason: slotReason });
      setSlotDate(null);
      setSlotTime('');
      setSlotReason('');
    }, 'Time slot blocked');
  };

  const handleUnblockSlot = (id) => {
    if (!window.confirm('Unblock this time slot?')) return;
    run(`unslot-${id}`, () => api.delete(`/slots/unblock-slot/${id}`), 'Time slot unblocked');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin text-teal-500 w-10 h-10" />
      </div>
    );
  }

  const inputCls = "w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/60 focus:border-teal-500";

  return (
    <div className="animate-fade-in space-y-6 max-w-7xl mx-auto">
      <div className="mb-2">
        <h2 className="text-2xl font-bold text-slate-800">Availability</h2>
        <p className="text-slate-500">Block out whole days, single time slots, or add holidays. Clients see changes instantly.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Block a single time slot */}
        <Panel icon={Clock} tone="bg-teal-100 text-teal-700" title="Block a Time Slot" subtitle="Keep the rest of the day open.">
          <form onSubmit={handleBlockSlot} className="space-y-3 mb-6 bg-sand-50 p-4 rounded-xl border border-sand-200">
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Date *</label>
              <DatePicker selected={slotDate} onChange={setSlotDate} minDate={new Date()} className={inputCls} placeholderText="Select date" dateFormat="dd MMM yyyy" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Time slot *</label>
              <select value={slotTime} onChange={(e) => setSlotTime(e.target.value)} className={inputCls}>
                <option value="">Select slot</option>
                {timeSlots.map(s => <option key={s.startTime} value={s.startTime}>{s.display}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Reason (optional)</label>
              <input type="text" value={slotReason} onChange={(e) => setSlotReason(e.target.value)} className={inputCls} placeholder="e.g. Personal appointment" />
            </div>
            <button type="submit" disabled={saving === 'slot'} className="w-full py-2.5 bg-teal-600 text-white hover:bg-teal-700 rounded-xl text-sm font-semibold transition-colors flex justify-center items-center gap-2 disabled:opacity-60">
              {saving === 'slot' ? <Loader2 size={16} className="animate-spin" /> : <Lock size={16} />} Block Slot
            </button>
          </form>

          <h4 className="font-semibold text-slate-700 mb-3 text-sm">Upcoming blocked slots</h4>
          <div className="flex-1 overflow-y-auto max-h-[280px] pr-1 space-y-2">
            {blockedSlots.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6 bg-sand-50 rounded-xl border border-dashed border-sand-200">No blocked time slots.</p>
            ) : blockedSlots.map((s) => (
              <ListRow
                key={s.id}
                primary={`${fmtDate(s.date)} · ${to12h(s.start_time)}`}
                secondary={s.reason}
                onRemove={() => handleUnblockSlot(s.id)}
                title="Unblock slot"
              />
            ))}
          </div>
        </Panel>

        {/* Block Specific Date */}
        <Panel icon={Lock} tone="bg-orange-100 text-orange-600" title="Block a Full Day" subtitle="Make an entire date unavailable.">
          <form onSubmit={handleBlockDate} className="space-y-3 mb-6 bg-sand-50 p-4 rounded-xl border border-sand-200">
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Date *</label>
              <DatePicker selected={blockDate} onChange={setBlockDate} minDate={new Date()} className={inputCls} placeholderText="Select date" dateFormat="dd MMM yyyy" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Reason (optional)</label>
              <input type="text" value={blockReason} onChange={(e) => setBlockReason(e.target.value)} className={inputCls} placeholder="e.g. Personal leave" />
            </div>
            <button type="submit" disabled={saving === 'block'} className="w-full py-2.5 bg-orange-50 text-orange-700 hover:bg-orange-100 rounded-xl text-sm font-semibold transition-colors flex justify-center items-center gap-2 border border-orange-200 disabled:opacity-60">
              {saving === 'block' ? <Loader2 size={16} className="animate-spin" /> : <Lock size={16} />} Block Date
            </button>
          </form>

          <h4 className="font-semibold text-slate-700 mb-3 text-sm">Blocked dates</h4>
          <div className="flex-1 overflow-y-auto max-h-[280px] pr-1 space-y-2">
            {blockedDates.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6 bg-sand-50 rounded-xl border border-dashed border-sand-200">No blocked dates.</p>
            ) : blockedDates.map((block) => (
              <ListRow
                key={block.id}
                primary={fmtDate(block.date)}
                secondary={block.reason}
                onRemove={() => handleUnblockDate(String(block.date).slice(0, 10))}
                title="Unblock date"
              />
            ))}
          </div>
        </Panel>

        {/* Holidays */}
        <Panel icon={CalendarIcon} tone="bg-emerald-100 text-emerald-600" title="Holidays" subtitle="Festivals and public holidays.">
          <form onSubmit={handleAddHoliday} className="space-y-3 mb-6 bg-sand-50 p-4 rounded-xl border border-sand-200">
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Date *</label>
              <DatePicker selected={holidayDate} onChange={setHolidayDate} className={inputCls} placeholderText="Select date" dateFormat="dd MMM yyyy" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Holiday name *</label>
              <input type="text" value={holidayReason} onChange={(e) => setHolidayReason(e.target.value)} className={inputCls} placeholder="e.g. Diwali" required />
            </div>
            <button type="submit" disabled={saving === 'holiday'} className="w-full py-2.5 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 rounded-xl text-sm font-semibold transition-colors flex justify-center items-center gap-2 border border-emerald-200 disabled:opacity-60">
              {saving === 'holiday' ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} Add Holiday
            </button>
          </form>

          <h4 className="font-semibold text-slate-700 mb-3 text-sm">Holidays</h4>
          <div className="flex-1 overflow-y-auto max-h-[280px] pr-1 space-y-2">
            {holidays.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6 bg-sand-50 rounded-xl border border-dashed border-sand-200">No holidays added.</p>
            ) : holidays.map((holiday) => (
              <ListRow
                key={holiday.id}
                primary={fmtDate(holiday.date)}
                secondary={holiday.reason}
                onRemove={() => handleRemoveHoliday(holiday.id)}
                title="Remove holiday"
              />
            ))}
          </div>
        </Panel>

      </div>
    </div>
  );
};

export default SlotManager;
