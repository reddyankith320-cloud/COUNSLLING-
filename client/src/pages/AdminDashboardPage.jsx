import React, { useState } from 'react';
import { useNavigate, Routes, Route, Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Users, LogOut,
  Menu, CalendarDays, MessageSquare, CalendarOff, ExternalLink, X
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { LogoMark } from '../components/common/Logo';
import { COUNSELOR } from '../config/site';

const DashboardHome = React.lazy(() => import('../components/admin/DashboardHome'));
const AppointmentList = React.lazy(() => import('../components/admin/AppointmentList'));
const ClientList = React.lazy(() => import('../components/admin/ClientList'));
const SlotManager = React.lazy(() => import('../components/admin/SlotManager'));
const Transcripts = React.lazy(() => import('../components/admin/Transcripts'));

const NAV_ITEMS = [
  { name: 'Dashboard', path: '/admin/dashboard', icon: LayoutDashboard },
  { name: 'Appointments', path: '/admin/dashboard/appointments', icon: CalendarDays },
  { name: 'Clients', path: '/admin/dashboard/clients', icon: Users },
  { name: 'Availability', path: '/admin/dashboard/slots', icon: CalendarOff },
  { name: 'Transcripts', path: '/admin/dashboard/transcripts', icon: MessageSquare },
];

const isItemActive = (item, pathname) =>
  pathname === item.path || (item.path !== '/admin/dashboard' && pathname.startsWith(item.path));

// Defined outside the page so it isn't re-created (and remounted) on every render
const Sidebar = ({ admin, pathname, onNavigate, onLogout, onClose }) => (
  <>
    <div className="h-[4.5rem] flex items-center justify-between px-5 border-b border-white/5">
      <div className="flex items-center gap-3">
        <LogoMark size={36} />
        <div className="flex flex-col leading-none">
          <span className="font-display font-semibold text-white">Find My Peace</span>
          <span className="text-[10px] text-slate-500 font-medium mt-1 uppercase tracking-wider">Counselor panel</span>
        </div>
      </div>
      <button onClick={onClose} className="lg:hidden text-slate-400 hover:text-white p-1" aria-label="Close menu">
        <X size={20} />
      </button>
    </div>

    <div className="p-4 flex-1 overflow-y-auto">
      <div className="mb-6 p-3 rounded-xl bg-white/[0.04] border border-white/5 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-teal-600 flex items-center justify-center text-white font-display font-semibold shrink-0">
          {admin?.name?.charAt(0) || COUNSELOR.initials.charAt(0)}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white truncate">{admin?.name}</p>
          <p className="text-xs text-slate-400 truncate">{admin?.email}</p>
        </div>
      </div>

      <nav className="space-y-1">
        {NAV_ITEMS.map((item) => {
          const active = isItemActive(item, pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              to={item.path}
              onClick={onNavigate}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors
                ${active
                  ? 'bg-teal-500/15 text-teal-300 border border-teal-500/20'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white border border-transparent'
                }`}
            >
              <Icon size={19} />
              {item.name}
            </Link>
          );
        })}
      </nav>
    </div>

    <div className="p-4 border-t border-white/5 space-y-1">
      <a
        href="/"
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:bg-white/5 hover:text-white transition-colors"
      >
        <ExternalLink size={19} />
        View website
      </a>
      <button
        onClick={onLogout}
        className="flex items-center gap-3 px-3 py-2.5 w-full rounded-xl text-sm font-medium text-red-400 hover:bg-red-500/10 transition-colors"
      >
        <LogOut size={19} />
        Logout
      </button>
    </div>
  </>
);

const AdminDashboardPage = () => {
  const { admin, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/admin/login');
  };

  const currentTitle = NAV_ITEMS.find(i => isItemActive(i, location.pathname))?.name || 'Dashboard';

  return (
    <div className="min-h-screen bg-sand-50 flex">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-slate-900/60 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`fixed inset-y-0 left-0 z-30 w-72 bg-slate-950 flex flex-col transition-transform duration-300 ease-in-out lg:translate-x-0 lg:static lg:inset-auto ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <Sidebar
          admin={admin}
          pathname={location.pathname}
          onNavigate={() => setSidebarOpen(false)}
          onClose={() => setSidebarOpen(false)}
          onLogout={handleLogout}
        />
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        <header className="h-[4.5rem] bg-white/80 backdrop-blur border-b border-slate-200 flex items-center justify-between px-4 sm:px-6 lg:px-8 sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2 rounded-xl text-slate-500 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              aria-label="Open menu"
            >
              <Menu size={22} />
            </button>
            <h1 className="font-display text-xl font-semibold text-slate-800 truncate">{currentTitle}</h1>
          </div>

          <div className="text-sm text-slate-500 hidden sm:block">
            {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 p-4 sm:p-6 lg:p-8">
          <React.Suspense fallback={
            <div className="flex items-center justify-center h-[50vh]">
              <div className="w-12 h-12 border-4 border-slate-200 border-t-teal-500 rounded-full animate-spin"></div>
            </div>
          }>
            <Routes>
              <Route path="/" element={<DashboardHome />} />
              <Route path="/appointments/*" element={<AppointmentList />} />
              <Route path="/clients/*" element={<ClientList />} />
              <Route path="/slots" element={<SlotManager />} />
              <Route path="/transcripts" element={<Transcripts />} />
            </Routes>
          </React.Suspense>
        </main>
      </div>
    </div>
  );
};

export default AdminDashboardPage;
