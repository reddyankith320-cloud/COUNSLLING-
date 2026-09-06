import React from 'react';
import { Link } from 'react-router-dom';
import { Phone, Mail, MapPin } from 'lucide-react';

const Footer = () => {
  return (
    <footer className="bg-slate-900 text-slate-300 pt-16 pb-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12">
          
          <div className="md:col-span-1">
            <Link to="/" className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 bg-sky-500 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-base">FMP</span>
              </div>
              <div className="flex flex-col">
                <span className="font-bold text-xl text-white tracking-tight leading-tight">Find My Peace</span>
                <span className="text-[10px] text-slate-400 font-medium">Professional Counseling Services · 20+ Years of Experience</span>
              </div>
            </Link>
            <p className="text-slate-400 text-sm leading-relaxed mb-6">
              Find My Peace provides compassionate, confidential, and client-centered counseling services, offering guidance in a supportive and respectful environment.
            </p>
            <div className="flex space-x-4">
              <a href="#" className="text-slate-400 hover:text-sky-400 transition-colors">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"></path></svg>
              </a>
              <a href="#" className="text-slate-400 hover:text-sky-400 transition-colors">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 4s-.7 2.1-2 3.4c1.6 10-9.4 17.3-18 11.6 2.2.1 4.4-.6 6-2C3 15.5.5 9.6 3 5c2.2 2.6 5.6 4.1 9 4-.9-4.2 4-6.6 7-3.8 1.1 0 3-1.2 3-1.2z"></path></svg>
              </a>
              <a href="#" className="text-slate-400 hover:text-sky-400 transition-colors">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>
              </a>
            </div>
          </div>

          <div>
            <h3 className="text-white font-semibold text-lg mb-4">Quick Links</h3>
            <ul className="space-y-3">
              <li><Link to="/" className="text-slate-400 hover:text-sky-400 transition-colors">Home</Link></li>
              <li><a href="#about" className="text-slate-400 hover:text-sky-400 transition-colors">About</a></li>
              <li><a href="#services" className="text-slate-400 hover:text-sky-400 transition-colors">Services</a></li>
              <li><Link to="/booking" className="text-slate-400 hover:text-sky-400 transition-colors">Book a Session</Link></li>
            </ul>
          </div>

          <div>
            <h3 className="text-white font-semibold text-lg mb-4">Services</h3>
            <ul className="space-y-3 text-slate-400">
              <li>Individual Counseling</li>
              <li>Relationship Counseling</li>
              <li>Career Guidance</li>
              <li>Anxiety & Depression</li>
              <li>Stress Management</li>
            </ul>
          </div>

          <div>
            <h3 className="text-white font-semibold text-lg mb-4">Contact Us</h3>
            <ul className="space-y-4">
              <li className="flex items-start gap-3">
                <Phone size={18} className="text-sky-500 mt-1 flex-shrink-0" />
                <span className="text-slate-400">+91 98765 43210</span>
              </li>
              <li className="flex items-start gap-3">
                <Mail size={18} className="text-sky-500 mt-1 flex-shrink-0" />
                <span className="text-slate-400">hello@findmypeace.in</span>
              </li>
              <li className="flex items-start gap-3">
                <MapPin size={18} className="text-sky-500 mt-1 flex-shrink-0" />
                <span className="text-slate-400">Hyderabad, Telangana<br />(Online Sessions Available)</span>
              </li>
            </ul>
          </div>
        </div>
        
        <div className="border-t border-slate-800 pt-8 flex flex-col md:flex-row justify-between items-center">
          <p className="text-slate-500 text-sm mb-4 md:mb-0">
            © {new Date().getFullYear()} Find My Peace. All rights reserved.
          </p>
          <div className="flex space-x-6 text-sm text-slate-500">
            <Link to="/admin/login" className="hover:text-slate-300 transition-colors">Admin Login</Link>
            <a href="#" className="hover:text-slate-300 transition-colors">Privacy Policy</a>
            <a href="#" className="hover:text-slate-300 transition-colors">Terms of Service</a>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
