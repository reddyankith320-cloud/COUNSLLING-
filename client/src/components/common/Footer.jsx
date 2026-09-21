import React from 'react';
import { Link } from 'react-router-dom';
import { Phone, Mail, MapPin, Clock, ShieldCheck } from 'lucide-react';
import Logo from './Logo';
import { CONTACT, SESSION_TIMES } from '../../config/site';

const Footer = () => {
  return (
    <footer className="bg-slate-950 text-slate-300 pt-16 pb-8 relative overflow-hidden">
      <div className="absolute -top-32 -right-32 w-96 h-96 rounded-full bg-teal-500/10 blur-3xl pointer-events-none" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-10 mb-12">

          <div className="md:col-span-5">
            <Logo tone="light" />
            <p className="text-slate-400 text-sm leading-relaxed mt-5 max-w-md">
              Find My Peace provides compassionate, confidential, and client-centered counseling —
              offering guidance in a supportive and respectful environment, in Telugu and English.
            </p>
            <div className="mt-6 inline-flex items-center gap-2 text-xs font-medium text-teal-300 bg-teal-500/10 border border-teal-500/20 px-3 py-1.5 rounded-full">
              <ShieldCheck size={14} /> 100% private & confidential sessions
            </div>
          </div>

          <div className="md:col-span-2">
            <h3 className="text-white font-semibold text-sm uppercase tracking-wider mb-4">Explore</h3>
            <ul className="space-y-3 text-sm">
              <li><Link to="/" className="text-slate-400 hover:text-teal-300 transition-colors">Home</Link></li>
              <li><Link to="/#services" className="text-slate-400 hover:text-teal-300 transition-colors">Services</Link></li>
              <li><Link to="/#about" className="text-slate-400 hover:text-teal-300 transition-colors">About</Link></li>
              <li><Link to="/#pricing" className="text-slate-400 hover:text-teal-300 transition-colors">Pricing</Link></li>
              <li><Link to="/#faq" className="text-slate-400 hover:text-teal-300 transition-colors">FAQ</Link></li>
              <li><Link to="/booking" className="text-slate-400 hover:text-teal-300 transition-colors">Book a Session</Link></li>
            </ul>
          </div>

          <div className="md:col-span-2">
            <h3 className="text-white font-semibold text-sm uppercase tracking-wider mb-4">Services</h3>
            <ul className="space-y-3 text-sm text-slate-400">
              <li>Individual Counseling</li>
              <li>Relationship Counseling</li>
              <li>Career Guidance</li>
              <li>HIV/AIDS & STI Counseling</li>
              <li>Stress & Anxiety Support</li>
            </ul>
          </div>

          <div className="md:col-span-3">
            <h3 className="text-white font-semibold text-sm uppercase tracking-wider mb-4">Contact</h3>
            <ul className="space-y-3.5 text-sm">
              <li className="flex items-start gap-3">
                <Phone size={16} className="text-teal-400 mt-0.5 flex-shrink-0" />
                <a href={`tel:${CONTACT.phone.replace(/\s/g, '')}`} className="text-slate-400 hover:text-teal-300 transition-colors">{CONTACT.phone}</a>
              </li>
              <li className="flex items-start gap-3">
                <Mail size={16} className="text-teal-400 mt-0.5 flex-shrink-0" />
                <a href={`mailto:${CONTACT.email}`} className="text-slate-400 hover:text-teal-300 transition-colors">{CONTACT.email}</a>
              </li>
              <li className="flex items-start gap-3">
                <Clock size={16} className="text-teal-400 mt-0.5 flex-shrink-0" />
                <span className="text-slate-400">Sessions daily, {SESSION_TIMES}</span>
              </li>
              <li className="flex items-start gap-3">
                <MapPin size={16} className="text-teal-400 mt-0.5 flex-shrink-0" />
                <span className="text-slate-400">{CONTACT.location}<br />(Online sessions via Google Meet)</span>
              </li>
            </ul>
          </div>
        </div>

        <div className="border-t border-slate-800 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-slate-500 text-sm">
            © {new Date().getFullYear()} Find My Peace. All rights reserved.
          </p>
          <div className="flex items-center gap-6 text-sm text-slate-500">
            <Link to="/admin/login" className="hover:text-slate-300 transition-colors">Counselor Login</Link>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
