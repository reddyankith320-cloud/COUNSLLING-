import React from 'react';
import { useLocation, Link, Navigate } from 'react-router-dom';
import { CheckCircle, Calendar, Clock, Video, Download, Copy, Printer, MessageSquare, Mail, ExternalLink } from 'lucide-react';
import toast from 'react-hot-toast';
import { COUNSELOR, PRICING } from '../config/site';

// Build an RFC 5545 calendar file for the booked slot (IST -> UTC).
const buildICS = (appointment) => {
  const { isoDate, startTime = '18:00', endTime = '19:00', meetLink, id } = appointment;
  if (!isoDate) return null;

  const toUTCStamp = (date, time) => {
    const d = new Date(`${date}T${time}:00+05:30`);
    return d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  };

  const escape = (s = '') => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');

  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Find My Peace//Counseling Booking//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:fmp-appointment-${id}@findmypeace`,
    `DTSTAMP:${toUTCStamp(isoDate, startTime)}`,
    `DTSTART:${toUTCStamp(isoDate, startTime)}`,
    `DTEND:${toUTCStamp(isoDate, endTime)}`,
    `SUMMARY:${escape(`Counseling Session with ${COUNSELOR.name}`)}`,
    `DESCRIPTION:${escape(`Google Meet link: ${meetLink || 'sent by email'}\nPlease join 5 minutes early.`)}`,
    `LOCATION:${escape(meetLink || 'Google Meet')}`,
    ...(meetLink ? [`URL:${meetLink}`] : []),
    'BEGIN:VALARM',
    'TRIGGER:-PT30M',
    'ACTION:DISPLAY',
    'DESCRIPTION:Counseling session starts in 30 minutes',
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ].join('\r\n');
};

const ConfirmationPage = () => {
  const location = useLocation();
  const { appointment, clientName } = location.state || {};

  // Protect route if no state
  if (!appointment) {
    return <Navigate to="/" replace />;
  }

  const copyToClipboard = async (text, type) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${type} copied to clipboard!`);
    } catch {
      toast.error('Could not copy. Please copy the link manually.');
    }
  };

  const downloadICS = () => {
    const ics = buildICS(appointment);
    if (!ics) {
      toast.error('Calendar file unavailable for this booking.');
      return;
    }
    const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', 'find-my-peace-session.ics');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-sand-50 py-12 px-4 sm:px-6 lg:px-8 print:bg-white print:py-4">
      <div className="max-w-2xl mx-auto animate-fade-in">

        {/* Success Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-emerald-100 rounded-full mb-6 relative print:hidden">
            <div className="absolute inset-0 bg-emerald-400 rounded-full animate-ping opacity-20"></div>
            <CheckCircle className="text-emerald-600 w-10 h-10" />
          </div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold text-slate-900 mb-3">You're booked, {clientName}.</h1>
          <p className="text-slate-600 text-lg">
            Your {appointment.consultationType ? appointment.consultationType.toLowerCase().replace(' fee', '') : ''} session with {COUNSELOR.name} is confirmed.
          </p>
        </div>

        {/* Details Card */}
        <div className="bg-white rounded-3xl shadow-soft border border-slate-100 overflow-hidden mb-8">
          <div className="bg-gradient-to-r from-teal-600 to-teal-500 p-6 text-white">
            <p className="text-teal-100 text-xs font-semibold uppercase tracking-wider mb-1">Session details</p>
            <h2 className="font-display text-2xl font-semibold">Booking #{appointment.id}</h2>
          </div>

          <div className="p-6 md:p-8 space-y-6">
            <div className="grid sm:grid-cols-2 gap-6">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-2xl bg-teal-50 flex items-center justify-center flex-shrink-0 text-teal-600">
                  <Calendar size={22} />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-1">Date</p>
                  <p className="font-semibold text-slate-900">{appointment.date}</p>
                </div>
              </div>

              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-2xl bg-teal-50 flex items-center justify-center flex-shrink-0 text-teal-600">
                  <Clock size={22} />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-1">Time</p>
                  <p className="font-semibold text-slate-900">{appointment.time}</p>
                  <p className="text-xs text-slate-500">{PRICING.sessionMinutes} minute session</p>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-100 pt-6">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-2xl bg-indigo-50 flex items-center justify-center flex-shrink-0 text-indigo-600">
                  <Video size={22} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-500 mb-2">Google Meet link</p>
                  {appointment.meetLink ? (
                    <>
                      <div className="flex flex-col sm:flex-row gap-2">
                        <a
                          href={appointment.meetLink}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-3 bg-teal-600 text-white rounded-xl font-semibold hover:bg-teal-700 transition-colors print:hidden"
                        >
                          <ExternalLink size={18} /> Open Google Meet
                        </a>
                        <button
                          onClick={() => copyToClipboard(appointment.meetLink, 'Meet link')}
                          className="inline-flex items-center justify-center gap-2 px-4 py-3 bg-white text-slate-700 rounded-xl font-medium hover:bg-slate-50 border border-slate-200 transition-colors print:hidden"
                        >
                          <Copy size={18} /> Copy
                        </button>
                      </div>
                      <p className="mt-2 text-xs text-slate-500 break-all font-mono">{appointment.meetLink}</p>
                    </>
                  ) : (
                    <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl p-3">
                      Your meeting link is being generated and will be sent to your email and WhatsApp shortly.
                    </p>
                  )}

                  {appointment.meetLink && (
                    <a
                      href={`/translate/${appointment.id}?role=client&meetUrl=${encodeURIComponent(appointment.meetLink)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 w-full px-4 py-3 bg-indigo-50 text-indigo-700 border border-indigo-100 rounded-xl font-medium flex items-center justify-center gap-2 hover:bg-indigo-100 transition-colors print:hidden"
                    >
                      <MessageSquare size={18} />
                      Join Live Translation Room (optional)
                    </a>
                  )}
                </div>
              </div>
            </div>

            <div className="bg-slate-50 rounded-2xl p-4 flex items-start gap-3 text-sm text-slate-600">
              <Mail size={18} className="text-teal-600 flex-shrink-0 mt-0.5" />
              <p>We've sent these details to your email and mobile number via SMS and WhatsApp. Please join 5 minutes before your scheduled time.</p>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center print:hidden">
          <button
            onClick={downloadICS}
            className="btn-primary flex items-center justify-center gap-2"
          >
            <Download size={18} />
            Add to Calendar
          </button>

          <button
            onClick={() => window.print()}
            className="btn-outline flex items-center justify-center gap-2"
          >
            <Printer size={18} />
            Save / Print
          </button>
        </div>

        <div className="mt-8 text-center print:hidden">
          <Link to="/" className="text-teal-700 font-medium hover:underline">
            Return to Home
          </Link>
        </div>

      </div>
    </div>
  );
};

export default ConfirmationPage;
