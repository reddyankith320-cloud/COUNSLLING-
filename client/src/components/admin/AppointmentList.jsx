import React, { useState, useEffect } from 'react';
import { io } from 'socket.io-client';
const socket = io(import.meta.env.VITE_SOCKET_URL || `${window.location.protocol}//${window.location.host}`);
import { useSearchParams } from 'react-router-dom';
import { Video, Check, X, FileText, Send, Loader2, Calendar as CalendarIcon, Phone, MessageSquare } from 'lucide-react';
import api from '../../services/api';
import toast from 'react-hot-toast';

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
      let endpoint = '/admin/appointments';
      if (filterParam === 'today') endpoint += '?status=today';
      else if (filterParam === 'upcoming') endpoint += '?status=upcoming';
      else if (filterParam === 'completed') endpoint += '?status=completed';
      
      const res = await api.get(endpoint);
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
    socket.on('availability_changed', () => {
      fetchAppointments();
    });
    return () => {
      socket.off('availability_changed');
    };
  }, [fetchAppointments]);

  const handleFilterChange = (filter) => {
    setSearchParams({ filter });
  };

  const handleFollowup = async (id, type) => {
    setActionLoading(`${id}-${type}`);
    try {
      if (type === 'yes') {
        await api.post(`/admin/appointments/${id}/followup`);
        toast.success('Follow-up initiated. Payment link sent to client.');
        // Optionally show payment link in a modal
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
      toast.error('Failed to change status');
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
    switch (status) {
      case 'Booked': return <span className="px-2 py-1 bg-sky-100 text-sky-700 rounded-full text-xs font-semibold">Booked</span>;
      case 'Completed': return <span className="px-2 py-1 bg-green-100 text-green-700 rounded-full text-xs font-semibold">Completed</span>;
      case 'Cancelled': return <span className="px-2 py-1 bg-red-100 text-red-700 rounded-full text-xs font-semibold">Cancelled</span>;
      case 'pending_payment': return <span className="px-2 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-semibold">Pending Payment</span>;
      default: return <span className="px-2 py-1 bg-slate-100 text-slate-700 rounded-full text-xs font-semibold">{status}</span>;
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      
      {/* Header & Tabs */}
      <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-100">
        <h2 className="text-xl font-bold text-slate-800 mb-4">Appointments</h2>
        <div className="flex overflow-x-auto hide-scrollbar space-x-2">
          {['today', 'upcoming', 'completed', 'all'].map(tab => (
            <button
              key={tab}
              onClick={() => handleFilterChange(tab)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap
                ${filterParam === tab 
                  ? 'bg-slate-900 text-white' 
                  : 'bg-slate-50 text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Appointment List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-sky-500 w-8 h-8" />
        </div>
      ) : appointments.length === 0 ? (
        <div className="bg-white p-12 rounded-xl border border-slate-100 text-center text-slate-500 shadow-sm">
          <CalendarIcon className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-lg font-medium">No appointments found</p>
          <p className="text-sm">Try changing the filter</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {appointments.map((appt) => (
            <div key={appt.id} className="bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden hover:shadow-md transition-all flex flex-col">
              
              {/* Card Header */}
              <div className="p-4 border-b border-slate-100 flex justify-between items-start bg-slate-50/50">
                <div>
                  <h3 className="font-bold text-slate-800 text-lg">{appt.full_name}</h3>
                  <p className="text-xs text-slate-500">{appt.age} yrs • {appt.gender}</p>
                </div>
                {getStatusBadge(appt.status)}
              </div>

              {/* Card Body */}
              <div className="p-4 space-y-4 flex-grow">
                <div className="flex items-center gap-3 text-sm text-slate-600">
                  <div className="w-8 h-8 rounded-lg bg-sky-50 text-sky-600 flex items-center justify-center shrink-0">
                    <CalendarIcon size={16} />
                  </div>
                  <div>
                    <p className="font-semibold text-slate-800">{new Date(appt.appointment_date).toLocaleDateString('en-IN', { month: 'short', day: 'numeric', year: 'numeric' })}</p>
                    <p className="text-xs">
                      {appt.start_time
                        ? `${appt.start_time?.substring(0, 5)} - ${appt.end_time?.substring(0, 5)}`
                        : '6:00 PM - 7:00 PM'}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-sm text-slate-600">
                  <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                    <Phone size={16} />
                  </div>
                  <div>
                    <p>{appt.mobile}</p>
                    <p className="text-xs truncate max-w-[200px]">{appt.email}</p>
                  </div>
                </div>

                {appt.follow_up_count !== undefined && (
                  <div className="flex items-center gap-3 text-sm text-slate-600">
                    <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center shrink-0">
                      <FileText size={16} />
                    </div>
                    <div>
                      <p className="font-medium">{appt.follow_up_count}/3 Follow-ups</p>
                    </div>
                  </div>
                )}
                
                <div className="flex items-center gap-3 text-sm text-slate-600">
                  <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center shrink-0">
                    <span className="font-bold text-lg">₹</span>
                  </div>
                  <div>
                    <p className="font-medium">{appt.consultation_type || 'Consultation'}</p>
                    <p className="text-xs">Payment: {appt.payment_status || 'N/A'}</p>
                  </div>
                </div>

                {appt.problem_description && (
                  <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 mt-2">
                    <p className="text-xs font-semibold text-slate-500 mb-1 uppercase tracking-wider">Problem</p>
                    <p className="text-sm text-slate-700 line-clamp-2" title={appt.problem_description}>
                      {appt.problem_description}
                    </p>
                  </div>
                )}
              </div>

              {/* Card Actions */}
              <div className="p-4 border-t border-slate-100 bg-slate-50/50 mt-auto">
                {appt.status === 'Booked' && (
                  <div className="flex flex-col gap-2">
                    <div className="flex gap-2">
                      {appt.meet_join_url ? (
                        <div className="flex flex-col gap-2 flex-grow">
                          <a 
                            href={appt.meet_join_url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="flex items-center gap-2 px-3 py-2 bg-indigo-50 text-indigo-700 rounded-lg text-sm font-medium hover:bg-indigo-100 transition-colors"
                          >
                            <Video size={16} />
                            Google Meet
                          </a>
                          <a 
                            href={`/translate/${appt.id}?role=counselor&meetUrl=${encodeURIComponent(appt.meet_join_url)}`} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="flex items-center gap-2 px-3 py-2 bg-emerald-50 text-emerald-700 rounded-lg text-sm font-medium hover:bg-emerald-100 transition-colors"
                          >
                            <MessageSquare size={16} />
                            Translate Room
                          </a>
                        </div>
                      ) : (
                        <button disabled className="flex-1 bg-slate-200 text-slate-500 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 cursor-not-allowed">
                          <Video size={16} /> No Link
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
                        className="flex-1 text-emerald-600 border border-emerald-200 hover:bg-emerald-50 py-1.5 rounded-lg text-xs font-medium transition-colors"
                      >
                        Complete Session
                      </button>
                      <button 
                        onClick={() => handleStatusChange(appt.id, 'Cancelled')}
                        disabled={actionLoading === `${appt.id}-status`}
                        className="flex-1 text-red-500 border border-red-200 hover:bg-red-50 py-1.5 rounded-lg text-xs font-medium transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                    <div className="flex gap-2 mt-1">
                      <button 
                        onClick={() => {
                          const newTime = window.prompt("Enter new Date and Time (e.g. 2026-08-10 19:00):");
                          if (newTime) {
                             // Basic prompt for reschedule. Real app would have a date picker modal.
                             alert("Please use the client app to re-book, or we will add a modal here soon.");
                          }
                        }}
                        className="flex-1 text-sky-600 border border-sky-200 hover:bg-sky-50 py-1.5 rounded-lg text-xs font-medium transition-colors"
                      >
                        Reschedule
                      </button>
                      <button 
                        onClick={() => handleStatusChange(appt.id, 'Blocked')}
                        disabled={actionLoading === `${appt.id}-status`}
                        className="flex-1 text-slate-600 border border-slate-300 hover:bg-slate-100 py-1.5 rounded-lg text-xs font-medium transition-colors"
                      >
                        Block Slot
                      </button>
                    </div>
                  </div>
                )}

                {appt.status === 'Cancelled' && (
                  <div className="flex gap-2">
                    <button 
                      onClick={() => handleStatusChange(appt.id, 'Booked')}
                      disabled={actionLoading === `${appt.id}-status`}
                      className="flex-1 text-sky-600 border border-sky-200 hover:bg-sky-50 py-1.5 rounded-lg text-sm font-medium transition-colors"
                    >
                      Reopen Slot
                    </button>
                  </div>
                )}

                {appt.status === 'Completed' && appt.requires_followup === null && (
                  <div>
                    {(appt.follow_up_count || 0) >= 3 ? (
                      <p className="text-xs font-semibold text-amber-600 text-center py-2 bg-amber-50 rounded-lg border border-amber-200">
                        This client has reached the maximum number of follow-up sessions.
                      </p>
                    ) : (
                      <>
                        <p className="text-xs font-semibold text-slate-600 mb-2 text-center">Require Follow-up Session?</p>
                        <div className="flex gap-2">
                          <button 
                            onClick={() => handleFollowup(appt.id, 'yes')}
                            disabled={actionLoading === `${appt.id}-yes`}
                            className="flex-1 border border-green-500 text-green-600 hover:bg-green-50 py-1.5 rounded-lg text-sm font-medium flex items-center justify-center gap-1 transition-colors disabled:opacity-50"
                          >
                            {actionLoading === `${appt.id}-yes` ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                            Yes
                          </button>
                          <button 
                            onClick={() => handleFollowup(appt.id, 'no')}
                            disabled={actionLoading === `${appt.id}-no`}
                            className="flex-1 border border-red-500 text-red-600 hover:bg-red-50 py-1.5 rounded-lg text-sm font-medium flex items-center justify-center gap-1 transition-colors disabled:opacity-50"
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
                      <span className="text-green-600 flex items-center justify-center gap-1"><Send size={14}/> Follow-up {appt.follow_up_count}/3 sent</span>
                    ) : (
                      <span className="text-slate-500 flex items-center justify-center gap-1"><Check size={14}/> Treatment Complete</span>
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
                className="w-full h-32 border border-slate-300 rounded-lg p-3 resize-none focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none"
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
                  className="px-4 py-2 bg-sky-500 text-white rounded-lg hover:bg-sky-600 transition-colors shadow-sm"
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
