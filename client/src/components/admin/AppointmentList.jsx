import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Video, Check, X, FileText, Send, Loader2, Calendar as CalendarIcon, Phone, MessageSquare, Clock } from 'lucide-react';
import api from '../../services/api';
import { onSocketEvent } from '../../services/socket';
import { PRICING } from '../../config/site';
import toast from 'react-hot-toast';

const FILTERS = [
  { key: 'today', label: 'Today' },
  { key: 'upcoming', label: 'Upcoming' },
  { key: 'completed', label: 'Completed' },
  { key: 'cancelled', label: 'Cancelled' },
  { key: 'all', label: 'All' },
];

// Map UI filter -> API status value (DB statuses are capitalised)
const FILTER_TO_STATUS = {
  today: 'today',
  upcoming: 'upcoming',
  completed: 'Completed',
  cancelled: 'Cancelled',
};

const to12h = (t) => {
  if (!t) return '';
  const [h, m] = t.substring(0, 5).split(':');
  const hour = parseInt(h, 10);
  return `${hour % 12 || 12}:${m} ${hour >= 12 ? 'PM' : 'AM'}`;
};

const AppointmentList = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const filterParam = searchParams.get('filter') || 'upcoming';

  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null); // stores appointment ID being acted upon

  // Note modal state
  const [noteModal, setNoteModal] = useState({ isOpen: false, text: '', apptId: null, clientId: null });

  const fetchAppointments = React.useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      const status = FILTER_TO_STATUS[filterParam];
      if (status) params.status = status;

      const res = await api.get('/admin/appointments', { params });
      setAppointments(res.data.appointments);
    } catch (error) {
      console.error(error);
      toast.error('Failed to load appointments');
    } finally {
      setLoading(false);
    }
  }, [filterParam]);

  useEffect(() => {
    fetchAppointments();
    // Listen for real-time updates
    return onSocketEvent('availability_changed', fetchAppointments);
  }, [fetchAppointments]);

  const handleFilterChange = (filter) => {
    setSearchParams({ filter });
  };

  const handleFollowup = async (id, type) => {
    setActionLoading(`${id}-${type}`);
    try {
      if (type === 'yes') {
        await api.post(`/admin/appointments/${id}/followup`);
        toast.success('Follow-up recommended. Booking link sent to the client.');
      } else {
        await api.post(`/admin/appointments/${id}/complete`);
        toast.success('Treatment marked complete. Client archived.');
      }
      fetchAppointments();
    } catch (error) {
      console.error(error);
      toast.error(error.response?.data?.error || 'Action failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleStatusChange = async (id, newStatus) => {
    if (!window.confirm(`Are you sure you want to change this appointment status to ${newStatus}?`)) return;
    setActionLoading(`${id}-status`);
    try {
      await api.patch(`/admin/appointments/${id}/status`, { status: newStatus });
      toast.success(`Appointment marked as ${newStatus}`);
      fetchAppointments();
    } catch (error) {
      console.error(error);
      toast.error(error.response?.data?.error || 'Failed to change status');
    } finally {
      setActionLoading(null);
    }
  };

  const saveNote = async () => {
    if (!noteModal.text.trim()) return;
    try {
      await api.post('/admin/notes', {
        content: noteModal.text,
        appointmentId: noteModal.apptId,
        clientId: noteModal.clientId
      });
      toast.success('Note saved successfully');
      setNoteModal({ isOpen: false, text: '', apptId: null, clientId: null });
    } catch (error) {
      console.error(error);
      toast.error('Failed to save note');
    }
  };

  const getStatusBadge = (status) => {
    const styles = {
      Booked: 'bg-sky-100 text-sky-700',
      Completed: 'bg-emerald-100 text-emerald-700',
      Cancelled: 'bg-red-100 text-red-700',
      pending_payment: 'bg-amber-100 text-amber-700',
    };
    const label = status === 'pending_payment' ? 'Pending Payment' : status;
    return (
      <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${styles[status] || 'bg-slate-100 text-slate-700'}`}>
        {label}
      </span>
    );
  };

  return (
    <div className="animate-fade-in space-y-6">

      {/* Header & Tabs */}
      <div className="bg-white p-4 sm:p-5 rounded-2xl shadow-sm border border-slate-100">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-slate-800">Appointments</h2>
            <p className="text-sm text-slate-500">{appointments.length} {filterParam === 'all' ? 'total' : filterParam} appointment{appointments.length === 1 ? '' : 's'}</p>
          </div>
          <div className="flex overflow-x-auto hide-scrollbar gap-1.5 bg-slate-100 p-1 rounded-xl">
            {FILTERS.map(tab => (
              <button
                key={tab.key}
                onClick={() => handleFilterChange(tab.key)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap
                  ${filterParam === tab.key
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                  }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Appointment List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-teal-500 w-8 h-8" />
        </div>
      ) : appointments.length === 0 ? (
        <div className="bg-white p-12 rounded-2xl border border-slate-100 text-center text-slate-500 shadow-sm">
          <CalendarIcon className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-lg font-medium">No appointments found</p>
          <p className="text-sm">Try changing the filter</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {appointments.map((appt) => (
            <div key={appt.id} className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden hover:shadow-md transition-all flex flex-col">

              {/* Card Header */}
              <div className="p-4 border-b border-slate-100 flex justify-between items-start bg-slate-50/60">
                <div className="min-w-0">
                  <h3 className="font-bold text-slate-800 text-lg truncate">{appt.full_name}</h3>
                  <p className="text-xs text-slate-500">
                    {appt.age} yrs{appt.gender ? ` • ${appt.gender.replace(/_/g, ' ')}` : ''} • #{appt.id}
                  </p>
                </div>
                {getStatusBadge(appt.status)}
              </div>

              {/* Card Body */}
              <div className="p-4 space-y-3.5 flex-grow">
                <div className="flex items-center gap-3 text-sm text-slate-600">
                  <div className="w-9 h-9 rounded-lg bg-teal-50 text-teal-600 flex items-center justify-center shrink-0">
                    <CalendarIcon size={16} />
                  </div>
                  <div>
                    <p className="font-semibold text-slate-800">{new Date(appt.appointment_date).toLocaleDateString('en-IN', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}</p>
                    <p className="text-xs flex items-center gap-1"><Clock size={12} /> {to12h(appt.start_time)} – {to12h(appt.end_time)} IST</p>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-sm text-slate-600">
                  <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                    <Phone size={16} />
                  </div>
                  <div className="min-w-0">
                    <p>+91 {appt.mobile}</p>
                    <p className="text-xs truncate">{appt.email}</p>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-sm text-slate-600">
                  <div className="w-9 h-9 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center shrink-0">
                    <span className="font-bold text-base">₹</span>
                  </div>
                  <div>
                    <p className="font-medium">
                      {appt.consultation_type || 'Consultation'}
                      {appt.payment_amount ? ` · ₹${Number(appt.payment_amount).toLocaleString('en-IN')}` : ''}
                    </p>
                    <p className="text-xs">
                      Payment: <span className={appt.payment_status === 'completed' ? 'text-emerald-600 font-medium' : ''}>{appt.payment_status || 'N/A'}</span>
                      {appt.follow_up_count !== undefined && ` · Follow-ups ${appt.follow_up_count}/${PRICING.maxFollowUps}`}
                    </p>
                  </div>
                </div>

                {appt.problem_description && (
                  <div className="bg-slate-50 p-3 rounded-xl border border-slate-100">
                    <p className="text-[10px] font-semibold text-slate-500 mb-1 uppercase tracking-wider">Concern</p>
                    <p className="text-sm text-slate-700 line-clamp-2" title={appt.problem_description}>
                      {appt.problem_description}
                    </p>
                  </div>
                )}
              </div>

              {/* Card Actions */}
              <div className="p-4 border-t border-slate-100 bg-slate-50/60 mt-auto">
                {appt.status === 'Booked' && (
                  <div className="flex flex-col gap-2">
                    <div className="flex gap-2">
                      {appt.meet_join_url ? (
                        <div className="flex flex-col gap-2 flex-grow">
                          <a
                            href={appt.meet_join_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center justify-center gap-2 px-3 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-700 transition-colors"
                          >
                            <Video size={16} />
                            Join Google Meet
                          </a>
                          <a
                            href={`/translate/${appt.id}?role=counselor&meetUrl=${encodeURIComponent(appt.meet_join_url)}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center justify-center gap-2 px-3 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors"
                          >
                            <MessageSquare size={16} />
                            Translation Room
                          </a>
                        </div>
                      ) : (
                        <button disabled className="flex-1 bg-slate-200 text-slate-500 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 cursor-not-allowed">
                          <Video size={16} /> No Meet Link
                        </button>
                      )}
                      <button
                        onClick={() => setNoteModal({ isOpen: true, text: '', apptId: appt.id, clientId: appt.client_id })}
                        className="p-2 border border-slate-200 bg-white hover:bg-slate-50 rounded-lg text-slate-600 transition-colors self-start"
                        title="Add Note"
                      >
                        <FileText size={18} />
                      </button>
                    </div>
                    <div className="flex gap-2 mt-1">
                      <button
                        onClick={() => handleStatusChange(appt.id, 'Completed')}
                        disabled={actionLoading === `${appt.id}-status`}
                        className="flex-1 text-emerald-700 border border-emerald-200 bg-white hover:bg-emerald-50 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
                      >
                        Complete Session
                      </button>
                      <button
                        onClick={() => handleStatusChange(appt.id, 'Cancelled')}
                        disabled={actionLoading === `${appt.id}-status`}
                        className="flex-1 text-red-600 border border-red-200 bg-white hover:bg-red-50 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {appt.status === 'Cancelled' && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleStatusChange(appt.id, 'Booked')}
                      disabled={actionLoading === `${appt.id}-status`}
                      className="flex-1 text-teal-700 border border-teal-200 bg-white hover:bg-teal-50 py-1.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                    >
                      Restore Booking
                    </button>
                  </div>
                )}

                {appt.status === 'pending_payment' && (
                  <p className="text-xs text-amber-700 text-center py-1.5 bg-amber-50 rounded-lg border border-amber-200">
                    Awaiting payment — slot is released automatically after 15 minutes.
                  </p>
                )}

                {appt.status === 'Completed' && appt.requires_followup === null && (
                  <div>
                    {(appt.follow_up_count || 0) >= PRICING.maxFollowUps ? (
                      <p className="text-xs font-semibold text-amber-700 text-center py-2 bg-amber-50 rounded-lg border border-amber-200">
                        Maximum follow-up sessions reached for this client.
                      </p>
                    ) : (
                      <>
                        <p className="text-xs font-semibold text-slate-600 mb-2 text-center">Recommend a follow-up session?</p>
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleFollowup(appt.id, 'yes')}
                            disabled={actionLoading === `${appt.id}-yes`}
                            className="flex-1 border border-emerald-500 text-emerald-700 bg-white hover:bg-emerald-50 py-1.5 rounded-lg text-sm font-medium flex items-center justify-center gap-1 transition-colors disabled:opacity-50"
                          >
                            {actionLoading === `${appt.id}-yes` ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                            Yes
                          </button>
                          <button
                            onClick={() => handleFollowup(appt.id, 'no')}
                            disabled={actionLoading === `${appt.id}-no`}
                            className="flex-1 border border-red-400 text-red-600 bg-white hover:bg-red-50 py-1.5 rounded-lg text-sm font-medium flex items-center justify-center gap-1 transition-colors disabled:opacity-50"
                          >
                            {actionLoading === `${appt.id}-no` ? <Loader2 size={16} className="animate-spin" /> : <X size={16} />}
                            No
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}

                {appt.status === 'Completed' && appt.requires_followup !== null && (
                  <div className="text-center text-sm font-medium">
                    {appt.requires_followup ? (
                      <span className="text-emerald-700 flex items-center justify-center gap-1"><Send size={14}/> Follow-up {appt.follow_up_count}/{PRICING.maxFollowUps} recommended</span>
                    ) : (
                      <span className="text-slate-500 flex items-center justify-center gap-1"><Check size={14}/> Treatment complete</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Note Modal */}
      {noteModal.isOpen && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl w-full max-w-md overflow-hidden shadow-2xl">
            <div className="p-4 border-b border-slate-100 flex justify-between items-center">
              <h3 className="font-bold text-lg">Add Counselor Note</h3>
              <button onClick={() => setNoteModal({ isOpen: false, text: '', apptId: null, clientId: null })} className="text-slate-400 hover:text-slate-600">
                <X size={20} />
              </button>
            </div>
            <div className="p-4">
              <textarea
                value={noteModal.text}
                onChange={(e) => setNoteModal({...noteModal, text: e.target.value})}
                placeholder="Enter confidential notes for this session..."
                className="w-full h-32 border border-slate-300 rounded-lg p-3 resize-none focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none"
              ></textarea>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  onClick={() => setNoteModal({ isOpen: false, text: '', apptId: null, clientId: null })}
                  className="px-4 py-2 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={saveNote}
                  className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 transition-colors shadow-sm"
                >
                  Save Note
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default AppointmentList;
