import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X, ArrowRight } from 'lucide-react';
import Logo from './Logo';

const NAV_LINKS = [
  { name: 'Home', hash: '' },
  { name: 'Services', hash: '#services' },
  { name: 'About', hash: '#about' },
  { name: 'Pricing', hash: '#pricing' },
  { name: 'FAQ', hash: '#faq' },
];

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();
  const onHome = location.pathname === '/';

  const closeMenu = () => setIsOpen(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Close the mobile menu on route change
  useEffect(() => { setIsOpen(false); }, [location.pathname, location.hash]);

  const isActive = (link) => {
    if (!onHome) return false;
    if (!link.hash) return !location.hash;
    return location.hash === link.hash;
  };

  const renderLink = (link, mobile = false) => {
    const base = mobile
      ? 'block px-4 py-3 rounded-xl text-base font-medium transition-colors'
      : 'text-sm font-medium transition-colors';
    const state = isActive(link)
      ? (mobile ? 'bg-teal-50 text-teal-700' : 'text-teal-700')
      : (mobile ? 'text-slate-700 hover:bg-slate-50' : 'text-slate-600 hover:text-teal-700');

    // On the home page a plain anchor gives native smooth scrolling; elsewhere
    // we route to "/" first so the anchor actually exists.
    return onHome ? (
      <a key={link.name} href={link.hash || '#top'} className={`${base} ${state}`} onClick={closeMenu}>
        {link.name}
      </a>
    ) : (
      <Link key={link.name} to={`/${link.hash}`} className={`${base} ${state}`} onClick={closeMenu}>
        {link.name}
      </Link>
    );
  };

  return (
    <nav
      id="top"
      className={`sticky top-0 z-50 transition-all duration-300 ${
        scrolled ? 'bg-white/85 backdrop-blur-lg shadow-[0_1px_0_0_rgb(15_23_42/0.06)]' : 'bg-transparent'
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-[4.5rem]">
          <Logo onClick={closeMenu} />

          {/* Desktop Menu */}
          <div className="hidden md:flex items-center gap-8">
            {NAV_LINKS.map((link) => renderLink(link))}
          </div>

          <div className="hidden md:flex items-center gap-3">
            <Link to="/booking" className="btn-primary text-sm py-2.5 px-5 group" onClick={closeMenu}>
              Book a Session
              <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>

          {/* Mobile menu button */}
          <div className="flex items-center md:hidden">
            <button
              onClick={() => setIsOpen(!isOpen)}
              aria-expanded={isOpen}
              aria-label="Toggle navigation"
              className="inline-flex items-center justify-center p-2 rounded-xl text-slate-600 hover:text-slate-900 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors"
            >
              {isOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      {isOpen && (
        <div className="md:hidden animate-fade-in bg-white border-t border-slate-100 shadow-lg">
          <div className="px-3 pt-3 pb-4 space-y-1">
            {NAV_LINKS.map((link) => renderLink(link, true))}
            <div className="pt-3">
              <Link to="/booking" className="btn-primary w-full" onClick={closeMenu}>
                Book a Session <ArrowRight size={16} />
              </Link>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
