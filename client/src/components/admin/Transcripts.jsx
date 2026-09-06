import React, { useState, useEffect } from 'react';
import { Search, Trash2, Download, ToggleLeft, ToggleRight, Loader2, MessageSquare, AlertCircle } from 'lucide-react';
import api from '../../services/api';
import toast from 'react-hot-toast';
import { jsPDF } from 'jspdf';

const Transcripts = () => {
  const [appointments, setAppointments] = useState([]);
  const [selectedAppt, setSelectedAppt] = useState('');
  const [transcripts, setTranscripts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [storeTranscripts, setStoreTranscripts] = useState(true);

  useEffect(() => {
    fetchAppointments();
    fetchSettings();
  }, []);

  useEffect(() => {
    if (selectedAppt) {
      fetchTranscripts(selectedAppt);
    } else {
      setTranscripts([]);
    }
  }, [selectedAppt]);

  const fetchAppointments = async () => {
    try {
      const res = await api.get('/admin/appointments');
      // Only show appointments that have been booked or completed
      setAppointments(res.data.filter(a => a.status === 'Booked' || a.status === 'Completed'));
    } catch (error) {
      console.error(error);
      toast.error('Failed to load appointments');
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await api.get('/admin/settings');
      if (res.data.settings.store_transcripts) {
        setStoreTranscripts(res.data.settings.store_transcripts === 'true');
      }
    } catch (error) {
      console.error('Failed to fetch settings:', error);
    }
  };

  const toggleStorage = async () => {
    const newValue = !storeTranscripts;
    setStoreTranscripts(newValue);
    try {
      await api.put('/admin/settings/store_transcripts', { value: newValue.toString() });
      toast.success(newValue ? 'Transcript storage enabled' : 'Transcript storage disabled');
    } catch (error) {
      console.error(error);
      setStoreTranscripts(!newValue);
      toast.error('Failed to update setting');
    }
  };

  const fetchTranscripts = async (apptId) => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/transcripts/${apptId}`);
      setTranscripts(res.data.transcripts);
    } catch (error) {
      console.error(error);
      toast.error('Failed to fetch transcripts');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedAppt) return;
    if (!window.confirm('Are you sure you want to delete all transcripts for this appointment? This cannot be undone.')) return;
    
    try {
      await api.delete(`/admin/transcripts/${selectedAppt}`);
      setTranscripts([]);
      toast.success('Transcripts deleted');
    } catch (error) {
      console.error(error);
      toast.error('Failed to delete transcripts');
    }
  };

  const downloadPDF = () => {
    if (transcripts.length === 0) return;
    
    const doc = new jsPDF();
    const appt = appointments.find(a => a.id.toString() === selectedAppt);
    
    doc.setFontSize(18);
    doc.text(`Translation Transcript - Appointment #${selectedAppt}`, 14, 22);
    
    doc.setFontSize(11);
    doc.text(`Client: ${appt?.full_name || 'Unknown'}`, 14, 30);
    doc.text(`Date: ${new Date().toLocaleDateString()}`, 14, 36);
    
    let yPos = 45;
    
    transcripts.forEach((t) => {
      // Check page break
      if (yPos > 270) {
        doc.addPage();
        yPos = 20;
      }
      
      doc.setFontSize(10);
      doc.setTextColor(100);
      doc.text(`[${new Date(t.timestamp).toLocaleTimeString()}] ${t.speaker.toUpperCase()} (${t.detected_language} -> ${t.target_language}):`, 14, yPos);
      
      yPos += 5;
      doc.setTextColor(0);
      
      // Handle text wrapping
      const origLines = doc.splitTextToSize(`Original: ${t.original_text}`, 180);
      doc.text(origLines, 14, yPos);
      yPos += (origLines.length * 5);
      
      const transLines = doc.splitTextToSize(`Translated: ${t.translated_text}`, 180);
      doc.text(transLines, 14, yPos);
      yPos += (transLines.length * 5) + 5;
    });
    
    doc.save(`Transcript_Appt_${selectedAppt}.pdf`);
  };

  const filteredTranscripts = transcripts.filter(t => 
    t.original_text.toLowerCase().includes(searchTerm.toLowerCase()) ||
    t.translated_text.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <MessageSquare className="text-sky-500" />
            Transcripts
          </h2>
          <p className="text-slate-500 mt-1">Manage and export translated meeting transcripts</p>
        </div>

        <div className="flex items-center gap-3 bg-white p-3 rounded-xl border border-slate-200 shadow-sm">
          <span className="text-sm font-medium text-slate-700">Store Transcripts</span>
          <button 
            onClick={toggleStorage}
            className={`text-2xl ${storeTranscripts ? 'text-emerald-500' : 'text-slate-400'}`}
          >
            {storeTranscripts ? <ToggleRight /> : <ToggleLeft />}
          </button>
        </div>
      </div>

      {!storeTranscripts && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 p-4 rounded-xl flex items-start gap-3">
          <AlertCircle className="shrink-0 mt-0.5 text-amber-600" size={20} />
          <div>
            <h4 className="font-semibold text-amber-900">Transcript Storage Disabled</h4>
            <p className="text-sm mt-1">Live translations will still work during meetings, but no text will be saved to the database. You will not be able to view or download transcripts for new meetings.</p>
          </div>
        </div>
      )}

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="p-4 border-b border-slate-200 flex flex-col sm:flex-row gap-4 bg-slate-50">
          
          <div className="flex-1">
            <label className="block text-sm font-medium text-slate-700 mb-1">Select Appointment</label>
            <select 
              value={selectedAppt}
              onChange={(e) => setSelectedAppt(e.target.value)}
              className="w-full border-slate-300 rounded-lg shadow-sm focus:border-sky-500 focus:ring-sky-500"
            >
              <option value="">-- Choose an appointment --</option>
              {appointments.map(a => (
                <option key={a.id} value={a.id}>
                  #{a.id} - {a.full_name} ({new Date(a.appointment_date).toLocaleDateString()})
                </option>
              ))}
            </select>
          </div>

          <div className="flex-1 relative">
            <label className="block text-sm font-medium text-slate-700 mb-1">Search Transcripts</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
              <input 
                type="text" 
                placeholder="Search keywords..." 
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                disabled={!selectedAppt || transcripts.length === 0}
                className="w-full pl-10 border-slate-300 rounded-lg shadow-sm focus:border-sky-500 focus:ring-sky-500 disabled:bg-slate-100 disabled:text-slate-400"
              />
            </div>
          </div>
          
          <div className="flex items-end gap-2">
            <button 
              onClick={downloadPDF}
              disabled={transcripts.length === 0}
              className="px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <Download size={18} /> Export PDF
            </button>
            <button 
              onClick={handleDelete}
              disabled={transcripts.length === 0}
              className="px-4 py-2 bg-red-50 text-red-600 rounded-lg hover:bg-red-100 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 border border-red-200"
            >
              <Trash2 size={18} /> Delete All
            </button>
          </div>
        </div>

        <div className="p-0">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400">
              <Loader2 className="animate-spin mb-4" size={32} />
              <p>Loading transcripts...</p>
            </div>
          ) : !selectedAppt ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400 bg-slate-50/50">
              <MessageSquare size={48} className="mb-4 opacity-20" />
              <p>Select an appointment to view its transcript</p>
            </div>
          ) : transcripts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400 bg-slate-50/50">
              <p>No transcripts found for this appointment.</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100 max-h-[600px] overflow-y-auto">
              {filteredTranscripts.map((t) => (
                <div key={t.id} className="p-4 hover:bg-slate-50 transition-colors">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${
                      t.speaker === 'counselor' ? 'bg-indigo-100 text-indigo-700' : 'bg-emerald-100 text-emerald-700'
                    }`}>
                      {t.speaker}
                    </span>
                    <span className="text-xs text-slate-400">
                      {new Date(t.timestamp).toLocaleTimeString()}
                    </span>
                    <span className="text-xs text-slate-400 ml-auto border border-slate-200 px-2 py-0.5 rounded">
                      {t.detected_language} → {t.target_language}
                    </span>
                  </div>
                  
                  <div className="pl-2 border-l-2 border-slate-200 ml-2 space-y-2">
                    <p className="text-sm text-slate-500">
                      {t.original_text}
                    </p>
                    <p className="text-base text-slate-800 font-medium">
                      {t.translated_text}
                    </p>
                  </div>
                </div>
              ))}
              
              {filteredTranscripts.length === 0 && searchTerm && (
                <div className="text-center py-12 text-slate-500">
                  No matches found for "{searchTerm}"
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Transcripts;
