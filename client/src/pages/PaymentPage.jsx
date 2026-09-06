import React, { useEffect, useState } from "react";
import { useLocation, useNavigate, Navigate } from "react-router-dom";
import { Shield, AlertCircle, RefreshCw, CreditCard, Smartphone, Building2, CheckCircle } from "lucide-react";
import toast from "react-hot-toast";
import api from "../services/api";

const PaymentPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [paymentFailed, setPaymentFailed] = useState(false);

  const { paymentDetails, bookingDetails, clientName, email, mobile } = location.state || {};

  // Guard: redirect if accessed directly without booking state
  if (!paymentDetails || !bookingDetails) {
    return <Navigate to="/" replace />;
  }

  const { orderId, amount, currency, key } = paymentDetails;
  const consultationType = bookingDetails.consultationType || "Consultation";

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
        color: "#0ea5e9",
      },
      modal: {
        ondismiss: () => {
          setLoading(false);
          setPaymentFailed(true);
          toast.error("Payment cancelled. Your slot is still reserved for a few minutes.");
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
          toast.error("Payment verification failed. Please contact support.", { id: "pay-verify" });
          setPaymentFailed(true);
          setLoading(false);
        }
      },
    };

    if (typeof window.Razorpay === "undefined") {
      toast.error("Razorpay is not loaded. Please refresh the page.");
      setLoading(false);
      return;
    }

    const rzp = new window.Razorpay(options);
    rzp.on("payment.failed", (response) => {
      console.error("Payment failed:", response.error);
      toast.error("Payment failed: " + response.error.description);
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
    <div className="min-h-screen bg-slate-50 py-12 px-4 sm:px-6 lg:px-8 flex flex-col items-center justify-center">
      <div className="max-w-md w-full">

        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-sky-100 rounded-full mb-4">
            <Shield className="text-sky-600" size={32} />
          </div>
          <h1 className="text-3xl font-bold text-slate-900">Complete Payment</h1>
          <p className="mt-2 text-slate-600">
            You are almost there! Complete your payment to confirm your booking.
          </p>
        </div>

        <div className="bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
          {/* Amount Header */}
          <div className="bg-gradient-to-br from-slate-900 to-slate-700 p-6 text-white text-center">
            <p className="text-slate-400 text-sm mb-1">{consultationType}</p>
            <h2 className="text-5xl font-extrabold flex justify-center items-start">
              <span className="text-2xl mt-1 mr-1">₹</span>
              {amount}
            </h2>
            <p className="text-slate-400 text-xs mt-2">Counseling Session Fee</p>
          </div>

          <div className="p-6">
            <h3 className="font-bold text-slate-800 mb-4">Order Summary</h3>

            <div className="space-y-3 mb-6">
              <div className="flex justify-between pb-3 border-b border-slate-100">
                <span className="text-slate-500">Service</span>
                <span className="font-medium text-slate-800">Find My Peace – Counseling Session</span>
              </div>
              <div className="flex justify-between pb-3 border-b border-slate-100">
                <span className="text-slate-500">Type</span>
                <span className="font-medium text-slate-800">{consultationType}</span>
              </div>
              {bookingDetails?.date && (
                <div className="flex justify-between pb-3 border-b border-slate-100">
                  <span className="text-slate-500">Date</span>
                  <span className="font-medium text-slate-800">{bookingDetails.date}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-500">Counselor</span>
                <span className="font-medium text-slate-800">Adulla Sridevi Reddy</span>
              </div>
            </div>

            {paymentFailed && (
              <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-lg flex gap-3 text-red-800 text-sm">
                <AlertCircle className="flex-shrink-0 text-red-500" size={20} />
                <p>Payment failed or was cancelled. Please try again.</p>
              </div>
            )}

            <button
              onClick={handlePayment}
              disabled={loading}
              className="w-full btn-primary text-lg py-4 flex justify-center items-center gap-2 shadow-lg shadow-sky-500/30"
              id="pay-now-btn"
            >
              {loading ? (
                <>
                  <RefreshCw className="animate-spin" size={20} />
                  Opening Razorpay...
                </>
              ) : (
                <>
                  <Shield size={20} />
                  Pay ₹{amount} Securely
                </>
              )}
            </button>

            {/* Accepted payment methods */}
            <div className="mt-5 p-3 bg-slate-50 rounded-xl">
              <p className="text-xs text-slate-500 font-semibold mb-2 text-center">Accepted Payment Methods</p>
              <div className="space-y-1">
                {paymentMethods.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
                    <CheckCircle size={12} className="text-green-500 flex-shrink-0" />
                    {m.label}
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 text-center text-xs text-slate-500 flex items-center justify-center gap-1">
              <Shield size={12} />
              Secured by Razorpay. 256-bit SSL encrypted.
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};

export default PaymentPage;
