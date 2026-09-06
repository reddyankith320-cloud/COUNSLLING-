import React, { useState, useEffect } from 'react';
import { Calendar as CalendarIcon, Lock, Trash2, Plus, Loader2 } from 'lucide-react';
import DatePicker from 'react-datepicker';
import "react-datepicker/dist/react-datepicker.css";
import { format } from 'date-fns';
import api from '../../services/api';
import toast from 'react-hot-toast';

const SlotManager = () => {
  const [holidays, setHolidays] = useState([]);
  const [blockedDates, setBlockedDates] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Forms state
  const [holidayDate, setHolidayDate] = useState(null);
  const [holidayReason, setHolidayReason] = useState('');
  const [blockDate, setBlockDate] = useState(null);
  const [blockReason, setBlockReason] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const [blockedRes, holRes] = await Promise.all([
        api.get('/slots/blocked'),
        api.get('/slots/holidays')
      ]);
      setBlockedDates(blockedRes.data.blockedDates || []);
      setHolidays(holRes.data.holidays || []);
    } catch (error) {
      console.error(error);
      toast.error('Failed to load date configurations');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleAddHoliday = async (e) => {
    e.preventDefault();
    if (!holidayDate) return toast.error('Please select a date');
    
    const formattedDate = format(holidayDate, 'yyyy-MM-dd');
    
    try {
      await api.post('/slots/holidays', { date: formattedDate, reason: holidayReason });
      toast.success('Holiday added successfully');
      setHolidayDate(null);
      setHolidayReason('');
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to add holiday');
    }
  };

  const handleRemoveHoliday = async (id) => {
    if (!window.confirm('Are you sure you want to remove this holiday?')) return;
    try {
      await api.delete(`/slots/holidays/${id}`);
      toast.success('Holiday removed');
      fetchData();
    } catch (error) {
      console.error(error);
      toast.error('Failed to remove holiday');
    }
  };

  const handleBlockDate = async (e) => {
    e.preventDefault();
    if (!blockDate) {
      return toast.error('Please select a date');
    }
    
    const formattedDate = format(blockDate, 'yyyy-MM-dd');
    
    try {
      await api.post('/slots/block', {
        date: formattedDate,
        reason: blockReason
      });
      toast.success('Date blocked successfully');
      setBlockDate(null);
      setBlockReason('');
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to block date');
    }
  };

  const handleUnblockDate = async (dateStr) => {
    if (!window.confirm('Are you sure you want to unblock this date?')) return;
    try {
      await api.post('/slots/unblock', { date: dateStr });
      toast.success('Date unblocked successfully');
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to unblock date');
    }
  };

  if (loading && holidays.length === 0 && blockedDates.length === 0) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin text-sky-500 w-10 h-10" />
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-6 max-w-6xl mx-auto">
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-slate-800">Date Management</h2>
        <p className="text-slate-500">Configure your availability by blocking out specific dates and holidays.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Block Specific Date */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-100 p-6 flex flex-col">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-orange-100 text-orange-600 flex items-center justify-center shrink-0">
              <Lock size={20} />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-800">Block Specific Date</h3>
              <p className="text-sm text-slate-500">Make an entire date unavailable for booking.</p>
            </div>
          </div>
          
          <form onSubmit={handleBlockDate} className="space-y-4 mb-8 bg-slate-50 p-4 rounded-xl border border-slate-100">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Date *</label>
                <div className="bg-white border rounded-lg">
                  <DatePicker
                    selected={blockDate}
                    onChange={setBlockDate}
                    minDate={new Date()}
                    className="w-full px-3 py-2 border-0 rounded-lg focus:ring-0 text-sm"
                    placeholderText="Select Date"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Reason (Optional)</label>
                <input
                  type="text"
                  value={blockReason}
                  onChange={(e) => setBlockReason(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:border-sky-500 focus:ring-sky-500"
                  placeholder="e.g. Personal Leave"
                />
              </div>
            </div>
            
            <button 
              type="submit"
              className="w-full py-2 bg-orange-50 text-orange-600 hover:bg-orange-100 rounded-lg text-sm font-semibold transition-colors flex justify-center items-center gap-2 border border-orange-200"
            >
              <Lock size={16} /> Block Date
            </button>
          </form>

          <h4 className="font-semibold text-slate-700 mb-3">Currently Blocked Dates</h4>
          <div className="flex-1 overflow-y-auto max-h-[300px] pr-2 custom-scrollbar space-y-2">
            {blockedDates.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6 bg-slate-50 rounded-lg">No manually blocked dates.</p>
            ) : (
              blockedDates.map((block, idx) => (
                <div key={idx} className="flex justify-between items-center p-3 border border-slate-100 bg-white hover:bg-slate-50 rounded-lg transition-colors">
                  <div>
                    <p className="font-medium text-slate-800 text-sm">
                      {format(new Date(block.date), 'MMM dd, yyyy (EEEE)')}
                    </p>
                    {block.reason && <p className="text-xs text-slate-500">Reason: {block.reason}</p>}
                  </div>
                  <button 
                    onClick={() => handleUnblockDate(format(new Date(block.date), 'yyyy-MM-dd'))}
                    className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                    title="Unblock Date"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Holidays */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-100 p-6 flex flex-col">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-emerald-100 text-emerald-600 flex items-center justify-center shrink-0">
              <CalendarIcon size={20} />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-800">Public Holidays</h3>
              <p className="text-sm text-slate-500">Dates that are globally blocked out.</p>
            </div>
          </div>
          
          <form onSubmit={handleAddHoliday} className="space-y-4 mb-8 bg-slate-50 p-4 rounded-xl border border-slate-100">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Holiday Date *</label>
                <div className="bg-white border rounded-lg">
                  <DatePicker
                    selected={holidayDate}
                    onChange={setHolidayDate}
                    className="w-full px-3 py-2 border-0 rounded-lg focus:ring-0 text-sm"
                    placeholderText="Select Date"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Holiday Name</label>
                <input
                  type="text"
                  value={holidayReason}
                  onChange={(e) => setHolidayReason(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:border-sky-500 focus:ring-sky-500"
                  placeholder="e.g. Diwali"
                  required
                />
              </div>
            </div>
            
            <button 
              type="submit"
              className="w-full py-2 bg-emerald-50 text-emerald-600 hover:bg-emerald-100 rounded-lg text-sm font-semibold transition-colors flex justify-center items-center gap-2 border border-emerald-200"
            >
              <Plus size={16} /> Add Holiday
            </button>
          </form>

          <h4 className="font-semibold text-slate-700 mb-3">Upcoming Holidays</h4>
          <div className="flex-1 overflow-y-auto max-h-[300px] pr-2 custom-scrollbar space-y-2">
            {holidays.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6 bg-slate-50 rounded-lg border border-dashed border-slate-200">No holidays added.</p>
            ) : (
              holidays.map((holiday) => (
                <div key={holiday.id} className="flex justify-between items-center p-3 border border-slate-100 bg-white hover:bg-slate-50 rounded-lg transition-colors">
                  <div>
                    <p className="font-medium text-slate-800 text-sm">
                      {format(new Date(holiday.date), 'MMM dd, yyyy (EEEE)')}
                    </p>
                    <p className="text-xs text-slate-500">{holiday.reason}</p>
                  </div>
                  <button 
                    onClick={() => handleRemoveHoliday(holiday.id)}
                    className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                    title="Remove Holiday"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

      </div>
    </div>
  );
};

export default SlotManager;
