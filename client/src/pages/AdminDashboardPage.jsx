import React, { useState } from 'react';
import { useNavigate, Routes, Route, Link, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, Users, Settings, LogOut, 
  Menu, CalendarDays, MessageSquare
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

// Placeholders for subcomponents (will be replaced by actual components)
const DashboardHome = React.lazy(() => import('../components/admin/DashboardHome'));
const AppointmentList = React.lazy(() => import('../components/admin/AppointmentList'));
const ClientList = React.lazy(() => import('../components/admin/ClientList'));
const SlotManager = React.lazy(() => import('../components/admin/SlotManager'));
const Transcripts = React.lazy(() => import('../components/admin/Transcripts'));

const AdminDashboardPage = () => {
  const { admin, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  
  const handleLogout = async () => {
    await logout();
    navigate('/admin/login');
  };

  const navItems = [
    { name: 'Dashboard', path: '/admin/dashboard', icon: <LayoutDashboard size={20} /> },
    { name: 'Appointments', path: '/admin/dashboard/appointments', icon: <CalendarDays size={20} /> },
    { name: 'Clients', path: '/admin/dashboard/clients', icon: <Users size={20} /> },
    { name: 'Slot Management', path: '/admin/dashboard/slots', icon: <Settings size={20} /> },
    { name: 'Transcripts', path: '/admin/dashboard/transcripts', icon: <MessageSquare size={20} /> },
  ];

  const SidebarContent = () => (
    <>
      <div className="h-16 flex items-center px-6 border-b border-slate-700/50">
        <div className="w-8 h-8 bg-sky-500 rounded-lg flex items-center justify-center mr-3">
          <span className="text-white font-bold text-sm">AS</span>
        </div>
        <div className="flex flex-col">
          <span className="font-bold text-sm text-white leading-tight">Adulla Sridevi Reddy</span>
          <span className="text-[9px] text-slate-400 font-medium">Master of Social Work (MSW) - Postgraduate Degree · Admin Panel</span>
        </div>
      </div>
      
      <div className="p-4">
        <div className="mb-6 px-2">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Logged in as</p>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center text-slate-300 font-bold">
              {admin?.name?.charAt(0) || 'A'}
            </div>
            <div>
              <p className="text-sm font-medium text-white">{admin?.name}</p>
              <p className="text-xs text-slate-400 truncate max-w-[150px]">{admin?.email}</p>
            </div>
          </div>
        </div>

        <nav className="space-y-1">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path || 
                             (item.path !== '/admin/dashboard' && location.pathname.startsWith(item.path));
            return (
              <Link
                key={item.name}
                to={item.path}
                onClick={() => setSidebarOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
                  ${isActive 
                    ? 'bg-sky-500/10 text-sky-400 border border-sky-500/20' 
                    : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                  }`}
              >
                {item.icon}
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="mt-auto p-4 border-t border-slate-700/50">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2.5 w-full rounded-lg text-sm font-medium text-red-400 hover:bg-red-500/10 transition-colors"
        >
          <LogOut size={20} />
          Logout
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-slate-100 flex">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div 
          className="fixed inset-0 z-20 bg-slate-900/50 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`fixed inset-y-0 left-0 z-30 w-64 bg-slate-900 flex flex-col transition-transform duration-300 ease-in-out lg:translate-x-0 lg:static lg:inset-auto ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <SidebarContent />
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Header */}
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-4 sm:px-6 z-10 shadow-sm">
          <div className="flex items-center">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2 rounded-md text-slate-500 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500 mr-2"
            >
              <Menu size={24} />
            </button>
            <h1 className="text-xl font-bold text-slate-800 truncate hidden sm:block">
              {navItems.find(i => location.pathname === i.path || (i.path !== '/admin/dashboard' && location.pathname.startsWith(i.path)))?.name || 'Dashboard'}
            </h1>
          </div>
          
          <div className="flex items-center gap-4">
            <a href="/" target="_blank" className="text-sm text-sky-600 hover:underline font-medium">View Site</a>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto p-4 sm:p-6 lg:p-8 bg-slate-50">
          <React.Suspense fallback={
            <div className="flex items-center justify-center h-full">
              <div className="w-12 h-12 border-4 border-slate-200 border-t-sky-500 rounded-full animate-spin"></div>
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
