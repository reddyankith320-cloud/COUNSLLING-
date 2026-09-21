import React, { useState, useEffect } from 'react';
import { Users, Calendar as CalendarIcon, CheckCircle, IndianRupee, TrendingUp, Clock, Download, Loader2, XCircle } from 'lucide-react';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import api from '../../services/api';
import { exportAppointmentsExcel } from '../../utils/exportReport';
import { useAuth } from '../../context/AuthContext';
import toast from 'react-hot-toast';
import { Link } from 'react-router-dom';

// Register ChartJS components
ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const formatPeriod = (p) => {
  // 'YYYY-MM' -> 'Sep 2026', 'YYYY-MM-DD' -> '20 Sep'
  if (/^\d{4}-\d{2}$/.test(p)) {
    const [y, m] = p.split('-');
    return new Date(y, m - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(p)) {
    return new Date(p).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  }
  return p;
};

const DashboardHome = () => {
  const { admin } = useAuth();
  const [stats, setStats] = useState(null);
  const [earningsData, setEarningsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        const [statsRes, earningsRes] = await Promise.all([
          api.get('/admin/dashboard'),
          api.get('/admin/earnings?period=monthly')
        ]);

        setStats(statsRes.data.stats);

        // Format chart data
        const earnings = [...earningsRes.data.earnings].reverse(); // Chronological order
        setEarningsData({
          labels: earnings.map(e => formatPeriod(e.period)),
          datasets: [
            {
              label: 'Registration (₹)',
              data: earnings.map(e => Number(e.initial_total)),
              backgroundColor: 'rgba(13, 148, 136, 0.85)',
              borderRadius: 6,
              stack: 'earnings',
            },
            {
              label: 'Follow-up (₹)',
              data: earnings.map(e => Number(e.followup_total)),
              backgroundColor: 'rgba(245, 158, 11, 0.85)',
              borderRadius: 6,
              stack: 'earnings',
            },
          ],
        });
      } catch (error) {
        console.error(error);
        toast.error('Failed to load dashboard data');
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

  const handleExport = async () => {
    setExporting(true);
    try {
      const count = await exportAppointmentsExcel();
      toast.success(count ? `Exported ${count} appointments to Excel` : 'No appointments to export yet');
    } catch (error) {
      console.error(error);
      toast.error('Export failed. Please try again.');
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="w-12 h-12 border-4 border-slate-200 border-t-teal-500 rounded-full animate-spin"></div>
      </div>
    );
  }

  const statCards = [
    {
      title: "Today's Sessions",
      value: stats?.todayAppointments || 0,
      icon: <Clock size={22} />,
      color: "bg-amber-100 text-amber-600",
      link: "/admin/dashboard/appointments?filter=today"
    },
    {
      title: "Upcoming Sessions",
      value: stats?.upcomingAppointments || 0,
      icon: <CalendarIcon size={22} />,
      color: "bg-teal-100 text-teal-600",
      link: "/admin/dashboard/appointments?filter=upcoming"
    },
    {
      title: "Completed Sessions",
      value: stats?.completedAppointments || 0,
      icon: <CheckCircle size={22} />,
      color: "bg-emerald-100 text-emerald-600",
      link: "/admin/dashboard/appointments?filter=completed"
    },
    {
      title: "Cancelled",
      value: stats?.cancelledAppointments || 0,
      icon: <XCircle size={22} />,
      color: "bg-rose-100 text-rose-600",
      link: "/admin/dashboard/appointments?filter=cancelled"
    },
    {
      title: "Active Clients",
      value: stats?.totalClients || 0,
      icon: <Users size={22} />,
      color: "bg-indigo-100 text-indigo-600",
      link: "/admin/dashboard/clients"
    },
  ];

  const firstName = admin?.name?.split(' ')[0] || 'Counselor';
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';

  return (
    <div className="animate-fade-in">
      <div className="mb-8 flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-800">{greeting}, {firstName}</h2>
          <p className="text-slate-500">Here's what's happening with your practice today.</p>
        </div>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm font-semibold text-slate-700 hover:bg-slate-50 hover:border-slate-300 transition-colors shadow-sm disabled:opacity-60"
        >
          {exporting ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
          Export to Excel
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4 mb-8">
        {statCards.map((card, idx) => (
          <Link key={idx} to={card.link} className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100 hover:shadow-md hover:-translate-y-0.5 transition-all group">
            <div className={`w-11 h-11 rounded-xl ${card.color} flex items-center justify-center mb-4`}>
              {card.icon}
            </div>
            <h3 className="text-3xl font-bold text-slate-800 mb-0.5 tabular-nums">{card.value}</h3>
            <p className="text-sm font-medium text-slate-500 group-hover:text-teal-700 transition-colors">{card.title}</p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Earnings Chart */}
        <div className="lg:col-span-2 bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4 border-b border-slate-100 pb-6">
            <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <TrendingUp className="text-teal-500" size={20} />
              Revenue Overview
            </h3>

            <div className="flex flex-wrap gap-4 sm:gap-8">
              <div className="text-right">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">Registration</p>
                <p className="text-lg font-bold text-slate-700 flex items-center justify-end tabular-nums">
                  <IndianRupee size={16} />
                  {(stats?.initialEarnings || 0).toLocaleString('en-IN')}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">Follow-up</p>
                <p className="text-lg font-bold text-slate-700 flex items-center justify-end tabular-nums">
                  <IndianRupee size={16} />
                  {(stats?.followupEarnings || 0).toLocaleString('en-IN')}
                </p>
              </div>
              <div className="text-right pl-4 sm:border-l border-slate-200">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">Total</p>
                <p className="text-xl font-extrabold text-emerald-600 flex items-center justify-end tabular-nums">
                  <IndianRupee size={18} />
                  {(stats?.totalEarnings || 0).toLocaleString('en-IN')}
                </p>
              </div>
            </div>
          </div>

          <div className="h-[300px] w-full">
            {earningsData && earningsData.labels.length > 0 ? (
              <Bar
                data={earningsData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: {
                    legend: { display: true, position: 'bottom', labels: { usePointStyle: true, boxWidth: 8 } },
                    tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label.replace(' (₹)', '')}: ₹${Number(ctx.raw).toLocaleString('en-IN')}` } },
                  },
                  scales: {
                    x: { stacked: true, grid: { display: false } },
                    y: { stacked: true, beginAtZero: true, ticks: { callback: (v) => `₹${Number(v).toLocaleString('en-IN')}` }, grid: { color: 'rgba(148,163,184,0.15)' } },
                  },
                }}
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 border-2 border-dashed border-slate-200 rounded-xl">
                <IndianRupee size={48} className="mb-2 opacity-30" />
                <p>No earnings data available yet</p>
              </div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
          <h3 className="text-lg font-bold text-slate-800 mb-6">Quick Actions</h3>
          <div className="space-y-3">
            <Link to="/admin/dashboard/appointments?filter=today" className="flex items-center gap-4 p-4 rounded-xl border border-slate-200 hover:border-amber-300 hover:bg-amber-50 transition-colors group">
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-amber-600">
                <Clock size={20} />
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-amber-700">Today's Sessions</p>
                <p className="text-xs text-slate-500">View and join today's meetings</p>
              </div>
            </Link>

            <Link to="/admin/dashboard/slots" className="flex items-center gap-4 p-4 rounded-xl border border-slate-200 hover:border-teal-300 hover:bg-teal-50 transition-colors group">
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-teal-600">
                <CalendarIcon size={20} />
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-teal-700">Manage Availability</p>
                <p className="text-xs text-slate-500">Block dates, slots & holidays</p>
              </div>
            </Link>

            <Link to="/admin/dashboard/clients" className="flex items-center gap-4 p-4 rounded-xl border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50 transition-colors group">
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-indigo-600">
                <Users size={20} />
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-indigo-700">Client Directory</p>
                <p className="text-xs text-slate-500">History, notes & contact details</p>
              </div>
            </Link>

            <button
              onClick={handleExport}
              disabled={exporting}
              className="w-full flex items-center gap-4 p-4 rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50 transition-colors group text-left disabled:opacity-60"
            >
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-emerald-600">
                {exporting ? <Loader2 size={20} className="animate-spin" /> : <Download size={20} />}
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-emerald-700">Export Report</p>
                <p className="text-xs text-slate-500">Download all appointments as Excel</p>
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardHome;
