import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X } from 'lucide-react';

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();

  const toggleMenu = () => setIsOpen(!isOpen);
  const closeMenu = () => setIsOpen(false);

  const navLinks = [
    { name: 'Home', path: '/' },
    { name: 'Services', path: '/#services' },
    { name: 'About', path: '/#about' },
  ];

  return (
    <nav className="bg-white/80 backdrop-blur-md sticky top-0 z-50 border-b border-slate-100 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex items-center">
            <Link to="/" className="flex-shrink-0 flex items-center gap-2" onClick={closeMenu}>
              <div className="w-8 h-8 bg-sky-500 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-base">FMP</span>
              </div>
              <div className="flex flex-col">
                <span className="font-bold text-lg text-slate-800 tracking-tight leading-tight">Find My Peace</span>
                <span className="text-[10px] text-slate-500 font-medium leading-tight hidden sm:block">Professional Counseling Services · 20+ Years of Experience</span>
              </div>
            </Link>
          </div>

          {/* Desktop Menu */}
          <div className="hidden md:flex items-center space-x-8">
            {navLinks.map((link) => (
              <a
                key={link.name}
                href={link.path.startsWith('/#') && location.pathname === '/' ? link.path.substring(1) : link.path}
                className="text-slate-600 hover:text-sky-500 font-medium transition-colors"
                onClick={closeMenu}
              >
                {link.name}
              </a>
            ))}
            <Link to="/booking" className="btn-primary" onClick={closeMenu}>
              Book a Session
            </Link>
          </div>

          {/* Mobile menu button */}
          <div className="flex items-center md:hidden">
            <button
              onClick={toggleMenu}
              className="inline-flex items-center justify-center p-2 rounded-md text-slate-500 hover:text-slate-700 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-sky-500 transition-colors"
            >
              <span className="sr-only">Open main menu</span>
              {isOpen ? <X className="block h-6 w-6" /> : <Menu className="block h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      {isOpen && (
        <div className="md:hidden animate-fade-in bg-white border-b border-slate-100">
          <div className="px-2 pt-2 pb-3 space-y-1 sm:px-3">
            {navLinks.map((link) => (
              <a
                key={link.name}
                href={link.path.startsWith('/#') && location.pathname === '/' ? link.path.substring(1) : link.path}
                className="block px-3 py-2 rounded-md text-base font-medium text-slate-700 hover:text-sky-500 hover:bg-slate-50"
                onClick={closeMenu}
              >
                {link.name}
              </a>
            ))}
            <div className="px-3 py-2 mt-4">
              <Link to="/booking" className="w-full text-center block btn-primary" onClick={closeMenu}>
                Book a Session
              </Link>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
