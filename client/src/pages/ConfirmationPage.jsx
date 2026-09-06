import React from 'react';
import { useLocation, Link, Navigate } from 'react-router-dom';
import { CheckCircle, Calendar, Clock, Video, Download, Copy, Share2, MessageSquare } from 'lucide-react';
import toast from 'react-hot-toast';
import { format } from 'date-fns';

const ConfirmationPage = () => {
  const location = useLocation();
  const { appointment, clientName } = location.state || {};

  // Protect route if no state
  if (!appointment) {
    return <Navigate to="/" replace />;
  }

  const copyToClipboard = (text, type) => {
    navigator.clipboard.writeText(text);
    toast.success(`${type} copied to clipboard!`);
  };

  const generateICS = () => {
    const formatCalendarDate = (dateString) => {
      return format(new Date(dateString), 'yyyyMMdd');
    };

    const icsContent = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      'BEGIN:VEVENT',
      `DATE:${formatCalendarDate(appointment.date)}T123000Z`,
      `DTSTART:${formatCalendarDate(appointment.date)}T123000Z`,
      `DTEND:${formatCalendarDate(appointment.date)}T133000Z`,
      'SUMMARY:Counseling Session - Find My Peace',
      `DESCRIPTION:Google Meet Link: ${appointment.meetLink}`,
      `LOCATION:${appointment.meetLink}`,
      'END:VEVENT',
      'END:VCALENDAR'
    ].join('\n');

    const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' });
    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.setAttribute('download', 'counseling_session.ics');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-2xl mx-auto animate-fade-in">
        
        {/* Success Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-green-100 rounded-full mb-6 relative">
            <div className="absolute inset-0 bg-green-500 rounded-full animate-ping opacity-20"></div>
            <CheckCircle className="text-green-500 w-10 h-10" />
          </div>
          <h1 className="text-3xl font-bold text-slate-900 mb-2">Booking Confirmed!</h1>
          <p className="text-slate-600 text-lg">Thank you, {clientName}. Your counseling session has been booked with Find My Peace.</p>
        </div>

        {/* Details Card */}
        <div className="bg-white rounded-2xl shadow-lg border border-slate-100 overflow-hidden mb-8">
          <div className="bg-sky-50 p-6 border-b border-sky-100">
            <h2 className="font-semibold text-sky-900 text-lg flex items-center gap-2">
              Session Details
            </h2>
          </div>
          
          <div className="p-6 md:p-8 space-y-6">
            <div className="flex flex-col md:flex-row gap-6 md:gap-12">
              <div className="flex-1 flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-slate-50 flex items-center justify-center flex-shrink-0 text-sky-500">
                  <Calendar size={24} />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-1">Date</p>
                  <p className="font-semibold text-slate-900">{format(new Date(appointment.date), 'PPP')}</p>
                </div>
              </div>
              
              <div className="flex-1 flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-slate-50 flex items-center justify-center flex-shrink-0 text-sky-500">
                  <Clock size={24} />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-1">Time</p>
                  <p className="font-semibold text-slate-900">{appointment.time || '6:00 PM - 7:00 PM (IST)'}</p>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-100 pt-6 mt-2">
              <div className="flex items-start gap-4 mb-4">
                <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center flex-shrink-0 text-blue-600">
                  <Video size={24} />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-slate-500 mb-1">Google Meet Link</p>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <a 
                      href={appointment.meetLink} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="text-blue-600 font-medium hover:underline truncate max-w-[200px] sm:max-w-full"
                    >
                      {appointment.meetLink}
                    </a>
                    <button 
                      onClick={() => copyToClipboard(appointment.meetLink, 'Meet link')}
                      className="p-3 bg-white text-indigo-600 rounded-xl font-medium hover:bg-indigo-50 border border-indigo-100 transition-colors shadow-sm"
                      title="Copy Link"
                    >
                      <Copy size={20} />
                    </button>
                  </div>
                  
                  {/* Translation Room Button */}
                  <a 
                    href={`/translate/${appointment.id}?role=client&meetUrl=${encodeURIComponent(appointment.meetLink)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-4 w-full p-3 bg-white text-indigo-600 border border-indigo-200 rounded-xl font-medium flex items-center justify-center gap-2 hover:bg-indigo-50 transition-colors shadow-sm"
                  >
                    <MessageSquare size={20} />
                    Join Live Translation Room
                  </a>
                </div>
              </div>
              
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 ml-16 bg-slate-50 p-4 rounded-lg">
                <div>
                  <p className="text-xs text-slate-500 mb-1">Meeting ID</p>
                  <p className="font-mono text-sm font-medium">{appointment.meetingId}</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <button 
            onClick={generateICS}
            className="btn-primary flex items-center justify-center gap-2"
          >
            <Download size={18} />
            Add to Calendar
          </button>
          
          <button 
            onClick={() => window.print()}
            className="btn-outline flex items-center justify-center gap-2 bg-white"
          >
            <Share2 size={18} />
            Save / Print
          </button>
        </div>
        
        <p className="text-center text-sm text-slate-500 mt-8">
          We've also sent these details to your email and mobile number via SMS/WhatsApp.
        </p>

        <div className="mt-8 text-center">
          <Link to="/" className="text-sky-600 font-medium hover:underline">
            Return to Home
          </Link>
        </div>

      </div>
    </div>
  );
};

export default ConfirmationPage;
