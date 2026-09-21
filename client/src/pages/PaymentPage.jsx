import React, { useState } from "react";
import { useLocation, useNavigate, Navigate, Link } from "react-router-dom";
import { Shield, AlertCircle, RefreshCw, CreditCard, Smartphone, Building2, CheckCircle, Lock, Calendar, Clock } from "lucide-react";
import toast from "react-hot-toast";
import api from "../services/api";
import { COUNSELOR } from "../config/site";

const PaymentPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [paymentFailed, setPaymentFailed] = useState(false);

  const { paymentDetails, bookingDetails, clientName, email, mobile } = location.state || {};

  // Guard: redirect if accessed directly without booking state
  if (!paymentDetails || !bookingDetails) {
    return <Navigate to="/booking" replace />;
  }

  const { orderId, amount, currency, key } = paymentDetails;
  const consultationType = bookingDetails.consultationType || "Consultation";
  const isFollowUp = /follow/i.test(consultationType);

  const prettyDate = bookingDetails.date
    ? new Date(`${bookingDetails.date}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "long", year: "numeric" })
    : null;

  const handlePayment = () => {
    setLoading(true);
    setPaymentFailed(false);

    const options = {
      key: key || import.meta.env.VITE_RAZORPAY_KEY_ID,
      amount: amount * 100, // paise
      currency: currency || "INR",
      name: "Find My Peace",
      description: consultationType + " – Counseling Session",
      order_id: orderId,
      prefill: {
        name: clientName,
        email: email,
        contact: mobile,
      },
      notes: {
        appointmentId: bookingDetails.appointmentId,
      },
      theme: {
        color: "#0d9488",
      },
      modal: {
        ondismiss: () => {
          setLoading(false);
          setPaymentFailed(true);
          toast.error("Payment cancelled. Your slot is held for 15 minutes.");
        },
      },
      handler: async (response) => {
        try {
          toast.loading("Verifying payment...", { id: "pay-verify" });

          const verifyRes = await api.post("/payments/verify", {
            razorpay_order_id:   response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature:  response.razorpay_signature,
            appointmentId:       bookingDetails.appointmentId,
          });

          toast.success("Payment successful!", { id: "pay-verify" });

          navigate("/confirmation", {
            state: {
              appointment: verifyRes.data.appointment,
              clientName: clientName || "Client",
            },
            replace: true,
          });
        } catch (error) {
          console.error("Payment verification error:", error);
          toast.error(error.response?.data?.error || "Payment verification failed. Please contact support.", { id: "pay-verify", duration: 8000 });
          setPaymentFailed(true);
          setLoading(false);
        }
      },
    };

    if (typeof window.Razorpay === "undefined") {
      toast.error("Payment gateway failed to load. Please refresh the page.");
      setLoading(false);
      return;
    }

    const rzp = new window.Razorpay(options);
    rzp.on("payment.failed", (response) => {
      console.error("Payment failed:", response.error);
      toast.error("Payment failed: " + (response.error?.description || "Please try again."));
      setPaymentFailed(true);
      setLoading(false);
    });
    rzp.open();
  };

  const paymentMethods = [
    { icon: <Smartphone size={16} />, label: "UPI (GPay, PhonePe, BHIM, Paytm)" },
    { icon: <CreditCard size={16} />, label: "Debit & Credit Cards" },
    { icon: <Building2 size={16} />, label: "Net Banking" },
  ];

  return (
    <div className="min-h-screen bg-sand-50 py-12 px-4 sm:px-6 lg:px-8 flex flex-col items-center justify-center">
      <div className="max-w-md w-full animate-fade-in">

        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-teal-100 rounded-2xl mb-4">
            <Lock className="text-teal-700" size={28} />
          </div>
          <h1 className="font-display text-3xl font-semibold text-slate-900">Complete your payment</h1>
          <p className="mt-2 text-slate-600">
            Almost there, {clientName?.split(" ")[0] || "there"} — your slot is reserved for 15 minutes.
          </p>
        </div>

        <div className="bg-white rounded-3xl shadow-soft border border-slate-100 overflow-hidden">
          {/* Amount Header */}
          <div className="bg-gradient-to-br from-slate-900 via-slate-900 to-teal-900 p-7 text-white text-center relative overflow-hidden">
            <div className="absolute -top-10 -right-10 w-40 h-40 rounded-full bg-teal-500/20 blur-2xl" />
            <p className="text-teal-200 text-xs font-bold uppercase tracking-[0.18em] mb-2 relative">{consultationType}</p>
            <h2 className="font-display text-5xl font-semibold flex justify-center items-start relative">
              <span className="text-2xl mt-1.5 mr-1 font-sans font-medium">₹</span>
              {Number(amount).toLocaleString("en-IN")}
            </h2>
            <p className="text-slate-400 text-xs mt-2 relative">
              {isFollowUp ? "Follow-up counseling session" : "One-time registration · includes first session"}
            </p>
          </div>

          <div className="p-6">
            <h3 className="font-semibold text-slate-800 mb-4">Order summary</h3>

            <div className="space-y-3 mb-6 text-sm">
              {prettyDate && (
                <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                  <span className="text-slate-500 flex items-center gap-2"><Calendar size={14} /> Date</span>
                  <span className="font-medium text-slate-800">{prettyDate}</span>
                </div>
              )}
              {bookingDetails.display && (
                <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                  <span className="text-slate-500 flex items-center gap-2"><Clock size={14} /> Time</span>
                  <span className="font-medium text-slate-800">{bookingDetails.display} IST</span>
                </div>
              )}
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">Counselor</span>
                <span className="font-medium text-slate-800">{COUNSELOR.name}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Booking ID</span>
                <span className="font-mono text-xs text-slate-600">#{bookingDetails.appointmentId}</span>
              </div>
            </div>

            {paymentFailed && (
              <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-xl flex gap-3 text-red-800 text-sm">
                <AlertCircle className="flex-shrink-0 text-red-500" size={20} />
                <p>Payment failed or was cancelled. No money has been deducted — please try again.</p>
              </div>
            )}

            <button
              onClick={handlePayment}
              disabled={loading}
              className="w-full btn-primary text-base py-4"
              id="pay-now-btn"
            >
              {loading ? (
                <>
                  <RefreshCw className="animate-spin" size={20} />
                  Opening secure checkout...
                </>
              ) : (
                <>
                  <Shield size={20} />
                  Pay ₹{Number(amount).toLocaleString("en-IN")} securely
                </>
              )}
            </button>

            {/* Accepted payment methods */}
            <div className="mt-5 p-4 bg-sand-50 rounded-2xl border border-sand-200">
              <p className="text-xs text-slate-500 font-semibold mb-2.5 text-center uppercase tracking-wider">Accepted payment methods</p>
              <div className="space-y-1.5">
                {paymentMethods.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm text-slate-700">
                    <CheckCircle size={14} className="text-teal-600 flex-shrink-0" />
                    {m.label}
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 text-center text-xs text-slate-500 flex items-center justify-center gap-1.5">
              <Lock size={12} />
              Secured by Razorpay · 256-bit SSL encrypted
            </div>
          </div>
        </div>

        <p className="text-center text-sm text-slate-500 mt-6">
          Changed your mind? <Link to="/booking" className="text-teal-700 font-medium hover:underline">Edit your booking</Link>
        </p>

      </div>
    </div>
  );
};

export default PaymentPage;
