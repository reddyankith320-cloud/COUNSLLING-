import React, { useState, useEffect, useCallback } from 'react';
import { Search, Loader2, Users, ChevronRight, Archive, UserCircle } from 'lucide-react';
import { format } from 'date-fns';
import api from '../../services/api';
import toast from 'react-hot-toast';

const ClientList = () => {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [selectedClient, setSelectedClient] = useState(null); // For details view

  const fetchClients = useCallback(async (search = '') => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/clients?search=${search}&archived=${showArchived}`);
      setClients(res.data.clients);
    } catch (error) {
      console.error(error);
      toast.error('Failed to load clients');
    } finally {
      setLoading(false);
    }
  }, [showArchived]);

  useEffect(() => {
    // Debounce search
    const delayDebounceFn = setTimeout(() => {
      fetchClients(searchTerm);
    }, 500);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm, fetchClients]);

  const viewClientDetails = async (id) => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/clients/${id}`);
      setSelectedClient(res.data);
    } catch (error) {
      console.error(error);
      toast.error('Failed to load client details');
    } finally {
      setLoading(false);
    }
  };

  // If a client is selected, show details view
  if (selectedClient) {
    const { client, appointments, notes } = selectedClient;
    return (
      <div className="animate-fade-in space-y-6 max-w-4xl mx-auto">
        <button 
          onClick={() => setSelectedClient(null)}
          className="text-slate-500 hover:text-slate-800 flex items-center gap-1 font-medium transition-colors"
        >
          &larr; Back to Client List
        </button>

        {/* Client Header Profile */}
        <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-100 flex flex-col sm:flex-row items-center sm:items-start gap-6">
          <div className="w-24 h-24 bg-slate-100 rounded-full flex items-center justify-center text-slate-400">
            <UserCircle size={64} strokeWidth={1} />
          </div>
          <div className="flex-1 text-center sm:text-left">
            <div className="flex items-center justify-center sm:justify-start gap-3 mb-2">
              <h2 className="text-2xl font-bold text-slate-900">{client.full_name}</h2>
              {client.is_archived && (
                <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider flex items-center gap-1">
                  <Archive size={12} /> Archived
                </span>
              )}
            </div>
            <p className="text-slate-600">{client.age} years old • {client.gender || 'Not specified'}</p>
            
            <div className="flex flex-col sm:flex-row gap-4 sm:gap-8 mt-4 pt-4 border-t border-slate-100">
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Contact</p>
                <p className="text-sm font-medium text-slate-800">{client.mobile}</p>
                <p className="text-sm text-slate-500">{client.email}</p>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Since</p>
                <p className="text-sm font-medium text-slate-800">
                  {format(new Date(client.created_at), 'MMM dd, yyyy')}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* History */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-100 p-6">
            <h3 className="font-bold text-slate-800 text-lg mb-4">Session History</h3>
            {appointments.length === 0 ? (
              <p className="text-slate-500 text-sm text-center py-8">No sessions found.</p>
            ) : (
              <div className="space-y-4 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                {appointments.map(appt => (
                  <div key={appt.id} className="p-3 border border-slate-100 rounded-lg bg-slate-50">
                    <div className="flex justify-between items-start mb-2">
                      <p className="font-semibold text-slate-800 text-sm">
                        {format(new Date(appt.appointment_date), 'MMM dd, yyyy')}
                      </p>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full uppercase font-bold
                        ${appt.status === 'completed' ? 'bg-green-100 text-green-700' : 
                          appt.status === 'cancelled' ? 'bg-red-100 text-red-700' : 
                          'bg-sky-100 text-sky-700'}`}
                      >
                        {appt.status}
                      </span>
                    </div>
                    {appt.problem_description && (
                      <p className="text-xs text-slate-600 line-clamp-2 mt-1">
                        "{appt.problem_description}"
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Counselor Notes */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-100 p-6">
            <h3 className="font-bold text-slate-800 text-lg mb-4">Confidential Notes</h3>
            {notes.length === 0 ? (
              <p className="text-slate-500 text-sm text-center py-8">No notes added yet.</p>
            ) : (
              <div className="space-y-4 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                {notes.map(note => (
                  <div key={note.id} className="p-4 border-l-4 border-amber-400 bg-amber-50 rounded-r-lg">
                    <p className="text-xs text-amber-700 font-semibold mb-2">
                      {format(new Date(note.created_at), 'MMM dd, yyyy - hh:mm a')}
                    </p>
                    <p className="text-sm text-slate-800 whitespace-pre-wrap">{note.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // List View
  return (
    <div className="animate-fade-in space-y-6">
      <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-100 flex flex-col sm:flex-row justify-between items-center gap-4">
        <h2 className="text-xl font-bold text-slate-800">Client Directory</h2>
        
        <div className="flex w-full sm:w-auto items-center gap-4">
          <div className="relative w-full sm:w-64">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
              <Search size={16} />
            </div>
            <input
              type="text"
              placeholder="Search clients..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>
          
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer whitespace-nowrap">
            <input 
              type="checkbox" 
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="rounded text-sky-500 focus:ring-sky-500"
            />
            Show Archived
          </label>
        </div>
      </div>

      {loading && clients.length === 0 ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-sky-500 w-8 h-8" />
        </div>
      ) : clients.length === 0 ? (
        <div className="bg-white p-12 rounded-xl border border-slate-100 text-center text-slate-500 shadow-sm">
          <Users className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-lg font-medium">No clients found</p>
          <p className="text-sm">Try adjusting your search criteria</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider border-b border-slate-200">
                  <th className="p-4 font-semibold">Client Name</th>
                  <th className="p-4 font-semibold hidden md:table-cell">Contact</th>
                  <th className="p-4 font-semibold text-center">Sessions</th>
                  <th className="p-4 font-semibold hidden sm:table-cell">Joined Date</th>
                  <th className="p-4 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm">
                {clients.map((client) => (
                  <tr key={client.id} className="hover:bg-slate-50 transition-colors">
                    <td className="p-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-sky-100 text-sky-600 flex items-center justify-center font-bold flex-shrink-0">
                          {client.full_name.charAt(0)}
                        </div>
                        <div>
                          <p className="font-semibold text-slate-800 flex items-center gap-2">
                            {client.full_name}
                            {client.is_archived && <span className="text-[10px] bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded uppercase font-bold">Archived</span>}
                          </p>
                          <p className="text-xs text-slate-500 md:hidden mt-0.5">{client.mobile}</p>
                        </div>
                      </div>
                    </td>
                    <td className="p-4 hidden md:table-cell">
                      <p className="text-slate-800">{client.mobile}</p>
                      <p className="text-xs text-slate-500">{client.email}</p>
                    </td>
                    <td className="p-4 text-center">
                      <span className="inline-block px-2 py-1 bg-slate-100 text-slate-700 rounded-md font-semibold text-xs">
                        {client.completed_sessions} / {client.total_sessions}
                      </span>
                    </td>
                    <td className="p-4 hidden sm:table-cell text-slate-500">
                      {format(new Date(client.created_at), 'MMM dd, yyyy')}
                    </td>
                    <td className="p-4 text-right">
                      <button 
                        onClick={() => viewClientDetails(client.id)}
                        className="inline-flex items-center gap-1 text-sky-600 font-medium hover:text-sky-800 transition-colors bg-sky-50 hover:bg-sky-100 px-3 py-1.5 rounded-lg"
                      >
                        View <ChevronRight size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default ClientList;
