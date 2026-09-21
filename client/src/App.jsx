import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider, useAuth } from './context/AuthContext';

// Pages
import HomePage from './pages/HomePage';
import BookingPage from './pages/BookingPage';
import PaymentPage from './pages/PaymentPage';
import ConfirmationPage from './pages/ConfirmationPage';
import AdminLoginPage from './pages/AdminLoginPage';
import AdminDashboardPage from './pages/AdminDashboardPage';
import TranslationRoom from './pages/TranslationRoom';

// Common
import Navbar from './components/common/Navbar';
import Footer from './components/common/Footer';
import Loader from './components/common/Loader';
import ScrollManager from './components/common/ScrollManager';

// Protected Route Wrapper
const ProtectedRoute = ({ children }) => {
  const { admin, loading } = useAuth();

  if (loading) {
    return <Loader fullScreen />;
  }

  if (!admin) {
    return <Navigate to="/admin/login" replace />;
  }

  return children;
};

// Layout for client pages (with Navbar and Footer)
const ClientLayout = ({ children }) => (
  <div className="min-h-screen flex flex-col">
    <Navbar />
    <main className="flex-grow">
      {children}
    </main>
    <Footer />
  </div>
);

function App() {
  return (
    <AuthProvider>
      <Router>
        <ScrollManager />
        <Toaster
          position="top-center"
          toastOptions={{
            duration: 4000,
            style: { borderRadius: '12px', background: '#0f172a', color: '#fff', fontSize: '14px' },
            success: { iconTheme: { primary: '#14b8a6', secondary: '#fff' } },
          }}
        />
        <Routes>
          {/* Client Routes */}
          <Route path="/" element={<ClientLayout><HomePage /></ClientLayout>} />
          <Route path="/booking" element={<ClientLayout><BookingPage /></ClientLayout>} />
          <Route path="/payment" element={<ClientLayout><PaymentPage /></ClientLayout>} />
          <Route path="/confirmation" element={<ClientLayout><ConfirmationPage /></ClientLayout>} />

          {/* Live translation room (opened from the confirmation page / admin) */}
          <Route path="/translate/:appointmentId" element={<TranslationRoom />} />

          {/* Admin Routes */}
          <Route path="/admin/login" element={<AdminLoginPage />} />
          <Route
            path="/admin/dashboard/*"
            element={
              <ProtectedRoute>
                <AdminDashboardPage />
              </ProtectedRoute>
            }
          />
          <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />

          {/* Fallback route */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;
