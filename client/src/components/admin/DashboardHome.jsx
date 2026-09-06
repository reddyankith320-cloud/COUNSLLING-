import React, { useState, useEffect } from 'react';
import { Users, Calendar as CalendarIcon, CheckCircle, IndianRupee, TrendingUp, Clock } from 'lucide-react';
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
import toast from 'react-hot-toast';
import { Link } from 'react-router-dom';

// Register ChartJS components
ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const DashboardHome = () => {
  const [stats, setStats] = useState(null);
  const [earningsData, setEarningsData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        const [statsRes, earningsRes] = await Promise.all([
          api.get('/admin/dashboard'),
          api.get('/admin/earnings?period=monthly')
        ]);
        
        setStats(statsRes.data.stats);
        
        // Format chart data
        const earnings = earningsRes.data.earnings.reverse(); // Chronological order
        setEarningsData({
          labels: earnings.map(e => e.period),
          datasets: [
            {
              label: 'Earnings (₹)',
              data: earnings.map(e => e.total),
              backgroundColor: 'rgba(14, 165, 233, 0.8)',
              borderRadius: 4,
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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="w-12 h-12 border-4 border-slate-200 border-t-sky-500 rounded-full animate-spin"></div>
      </div>
    );
  }

  const statCards = [
    { 
      title: "Today's Appointments", 
      value: stats?.todayAppointments || 0, 
      icon: <Clock className="text-amber-500" size={24} />,
      bg: "bg-amber-100",
      link: "/admin/dashboard/appointments?filter=today"
    },
    { 
      title: "Upcoming Appointments", 
      value: stats?.upcomingAppointments || 0, 
      icon: <CalendarIcon className="text-sky-500" size={24} />,
      bg: "bg-sky-100",
      link: "/admin/dashboard/appointments?filter=upcoming"
    },
    { 
      title: "Completed Sessions", 
      value: stats?.completedAppointments || 0, 
      icon: <CheckCircle className="text-green-500" size={24} />,
      bg: "bg-green-100",
      link: "/admin/dashboard/appointments?filter=completed"
    },
    { 
      title: "Total Clients", 
      value: stats?.totalClients || 0, 
      icon: <Users className="text-indigo-500" size={24} />,
      bg: "bg-indigo-100",
      link: "/admin/dashboard/clients"
    },
  ];

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-slate-800">Welcome Back, Counselor</h2>
        <p className="text-slate-500">Here's what's happening with your practice today.</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {statCards.map((card, idx) => (
          <Link key={idx} to={card.link} className="bg-white rounded-xl p-6 shadow-sm border border-slate-100 hover:shadow-md transition-shadow group">
            <div className="flex justify-between items-start mb-4">
              <div className={`w-12 h-12 rounded-lg ${card.bg} flex items-center justify-center`}>
                {card.icon}
              </div>
            </div>
            <div>
              <h3 className="text-3xl font-bold text-slate-800 mb-1">{card.value}</h3>
              <p className="text-sm font-medium text-slate-500 group-hover:text-sky-600 transition-colors">{card.title}</p>
            </div>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Earnings Chart */}
        <div className="lg:col-span-2 bg-white p-6 rounded-xl shadow-sm border border-slate-100">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4 border-b border-slate-100 pb-6">
            <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <TrendingUp className="text-sky-500" size={20} />
              Revenue Overview
            </h3>
            
            <div className="flex flex-wrap gap-4 sm:gap-8">
              <div className="text-right">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">Initial</p>
                <p className="text-lg font-bold text-slate-700 flex items-center justify-end">
                  <IndianRupee size={16} />
                  {stats?.initialEarnings?.toLocaleString('en-IN') || 0}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">Follow-up</p>
                <p className="text-lg font-bold text-slate-700 flex items-center justify-end">
                  <IndianRupee size={16} />
                  {stats?.followupEarnings?.toLocaleString('en-IN') || 0}
                </p>
              </div>
              <div className="text-right pl-4 sm:border-l border-slate-200">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">Total</p>
                <p className="text-xl font-extrabold text-green-600 flex items-center justify-end">
                  <IndianRupee size={18} />
                  {stats?.totalEarnings?.toLocaleString('en-IN') || 0}
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
                  plugins: { legend: { display: false } },
                  scales: { y: { beginAtZero: true } }
                }} 
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 border-2 border-dashed border-slate-200 rounded-lg">
                <IndianRupee size={48} className="mb-2 opacity-30" />
                <p>No earnings data available yet</p>
              </div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-100">
          <h3 className="text-lg font-bold text-slate-800 mb-6">Quick Actions</h3>
          <div className="space-y-4">
            <Link to="/admin/dashboard/slots" className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 hover:border-sky-300 hover:bg-sky-50 transition-colors group">
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-sky-600">
                <CalendarIcon size={20} />
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-sky-700">Manage Slots</p>
                <p className="text-xs text-slate-500">Update working hours & holidays</p>
              </div>
            </Link>
            
            <Link to="/admin/dashboard/appointments?filter=today" className="flex items-center gap-4 p-4 rounded-lg border border-slate-200 hover:border-amber-300 hover:bg-amber-50 transition-colors group">
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-amber-600">
                <Clock size={20} />
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-amber-700">Today's Sessions</p>
                <p className="text-xs text-slate-500">View and join today's meetings</p>
              </div>
            </Link>

            <button 
              onClick={() => {
                toast.success('Report generation started. This feature will be implemented in the export phase.');
              }}
              className="w-full flex items-center gap-4 p-4 rounded-lg border border-slate-200 hover:border-green-300 hover:bg-green-50 transition-colors group text-left"
            >
              <div className="w-10 h-10 rounded-full bg-slate-100 group-hover:bg-white flex items-center justify-center text-green-600">
                <CheckCircle size={20} />
              </div>
              <div>
                <p className="font-semibold text-slate-800 group-hover:text-green-700">Export Report</p>
                <p className="text-xs text-slate-500">Download appointments as Excel/PDF</p>
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardHome;
