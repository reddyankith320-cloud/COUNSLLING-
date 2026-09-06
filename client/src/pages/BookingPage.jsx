import React, { useState, useEffect } from "react";
import { io } from "socket.io-client";
const socket = io(import.meta.env.VITE_SOCKET_URL || `${window.location.protocol}//${window.location.host}`);
import { useNavigate } from "react-router-dom";
import { Calendar as CalendarIcon, Clock, User, FileText, ChevronRight, ChevronLeft, CheckCircle2, Shield } from "lucide-react";
import DatePicker from "react-datepicker";
import "react-datepicker/dist/react-datepicker.css";
import toast from "react-hot-toast";
import api from "../services/api";

const BookingPage = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [unavailableDates, setUnavailableDates] = useState([]);
  const [fetchingDates, setFetchingDates] = useState(false);
  const [availableSlots, setAvailableSlots] = useState([]);
  const [fetchingSlots, setFetchingSlots] = useState(false);
  const [maxFollowupReached, setMaxFollowupReached] = useState(false);
  
  // Form State
  const [formData, setFormData] = useState({
    fullName: "",
    age: "",
    gender: "",
    mobile: "",
    email: "",
    problemDescription: "",
    appointmentDate: null,
    appointmentTime: null // { startTime, endTime, display }
  });

  const [errors, setErrors] = useState({});

  // Fetch unavailable dates on load
  const fetchDates = async () => {
    setFetchingDates(true);
    try {
      const today = new Date();
      const year = today.getFullYear();
      const month = today.getMonth() + 1;
      
      const response1 = await api.get(`/slots/unavailable?year=${year}&month=${month}`);
      
      const nextMonth = month === 12 ? 1 : month + 1;
      const nextYear = month === 12 ? year + 1 : year;
      const response2 = await api.get(`/slots/unavailable?year=${nextYear}&month=${nextMonth}`);
      
      const allUnavailable = [
        ...response1.data.booked, ...response1.data.blocked,
        ...response2.data.booked, ...response2.data.blocked
      ];
      
      setUnavailableDates(allUnavailable.map(d => new Date(d).toDateString()));
    } catch (error) {
      console.error(error);
      toast.error("Failed to fetch calendar availability");
      setUnavailableDates([]);
    } finally {
      setFetchingDates(false);
    }
  };

  useEffect(() => {
    fetchDates();
    socket.on("availability_changed", fetchDates);
    return () => socket.off("availability_changed", fetchDates);
  }, []);

  // Fetch available slots when a date is selected
  useEffect(() => {
    if (!formData.appointmentDate) {
      setAvailableSlots([]);
      return;
    }
    const fetchSlots = async () => {
      setFetchingSlots(true);
      try {
        const dateObj = formData.appointmentDate;
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, "0");
        const day = String(dateObj.getDate()).padStart(2, "0");
        const formattedDate = `${year}-${month}-${day}`;

        const res = await api.get(`/slots/available-slots?date=${formattedDate}`);
        setAvailableSlots(res.data.slots);
      } catch (err) {
        console.error(err);
        toast.error("Failed to load time slots");
      } finally {
        setFetchingSlots(false);
      }
    };
    fetchSlots();
  }, [formData.appointmentDate]);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: "" }));
    }
  };

  const validateStep1 = () => {
    const newErrors = {};
    if (!formData.fullName.trim()) newErrors.fullName = "Full Name is required";
    if (!formData.age) newErrors.age = "Age is required";
    else if (isNaN(formData.age) || formData.age < 1 || formData.age > 120) newErrors.age = "Valid age is required";
    if (!formData.mobile.trim()) newErrors.mobile = "Mobile Number is required";
    else if (!/^[6-9]\d{9}$/.test(formData.mobile)) newErrors.mobile = "Invalid Indian mobile number";
    if (!formData.email.trim()) newErrors.email = "Email is required";
    else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = "Invalid email format";
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep2 = () => {
    const newErrors = {};
    if (!formData.problemDescription.trim()) newErrors.problemDescription = "Please describe your problem briefly";
    else if (formData.problemDescription.length < 10) newErrors.problemDescription = "Description must be at least 10 characters";
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep3 = () => {
    const newErrors = {};
    if (!formData.appointmentDate) newErrors.appointmentDate = "Please select a date";
    if (!formData.appointmentTime) newErrors.appointmentTime = "Please select a time slot";
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const nextStep = () => {
    let isValid = false;
    if (step === 1) isValid = validateStep1();
    if (step === 2) isValid = validateStep2();
    if (step === 3) isValid = validateStep3();
    
    if (isValid) setStep(prev => prev + 1);
  };

  const prevStep = () => setStep(prev => prev - 1);

  const handleSubmit = async () => {
    if (!validateStep3()) return;
    
    setLoading(true);
    try {
      const dateObj = formData.appointmentDate;
      const year = dateObj.getFullYear();
      const month = String(dateObj.getMonth() + 1).padStart(2, "0");
      const day = String(dateObj.getDate()).padStart(2, "0");
      
      const payload = {
        ...formData,
        appointmentDate: `${year}-${month}-${day}`,
        startTime: formData.appointmentTime.startTime,
        endTime: formData.appointmentTime.endTime,
        age: parseInt(formData.age)
      };

      const response = await api.post("/bookings", payload);
      
      toast.success("Booking initiated!");
      
      navigate("/payment", { 
        state: { 
          paymentDetails: response.data.payment,
          bookingDetails: response.data.booking,
          clientName: formData.fullName,
          email: formData.email,
          mobile: formData.mobile
        }
      });
    } catch (error) {
      const status  = error.response?.status;
      const errMsg  = error.response?.data?.error || "Failed to create booking";

      if (status === 403 && errMsg.toLowerCase().includes("maximum follow-up")) {
        setMaxFollowupReached(true);
        toast.error("Maximum follow-up sessions reached.", { duration: 6000 });
        return;
      }

      toast.error(errMsg);
      
      if (error.response?.data?.details) {
        const backendErrors = {};
        error.response.data.details.forEach(err => {
          backendErrors[err.field] = err.message;
        });
        setErrors(backendErrors);
      }
    } finally {
      setLoading(false);
    }
  };

  const steps = [
    { num: 1, title: "Personal Details", icon: <User size={20} /> },
    { num: 2, title: "Questionnaire", icon: <FileText size={20} /> },
    { num: 3, title: "Select Slot", icon: <CalendarIcon size={20} /> },
    { num: 4, title: "Review", icon: <CheckCircle2 size={20} /> }
  ];

  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold text-slate-900">Book a Counseling Session</h1>
          <p className="mt-2 text-slate-600">Schedule your appointment with Adulla Sridevi Reddy</p>
          <div className="mt-4 inline-flex items-center gap-3 bg-white border border-slate-200 rounded-xl px-5 py-3 shadow-sm">
            <div className="w-10 h-10 bg-sky-100 rounded-full flex items-center justify-center">
              <User className="text-sky-600" size={20} />
            </div>
            <div className="text-left">
              <p className="font-semibold text-slate-800 text-sm">Adulla Sridevi Reddy</p>
              <p className="text-xs text-slate-500">Master of Social Work (MSW) - Postgraduate Degree &middot; 20+ Years of Professional Counseling Experience</p>
            </div>
          </div>
        </div>

        {maxFollowupReached && (
          <div className="mb-8 p-5 bg-amber-50 border border-amber-200 rounded-xl text-amber-900">
            <div className="flex items-start gap-3">
              <Shield className="text-amber-600 flex-shrink-0 mt-0.5" size={22} />
              <div>
                <p className="font-bold text-base">Maximum follow-up sessions reached.</p>
                <p className="text-sm mt-1">
                  Maximum of 3 follow-up sessions has been completed. Please contact the counselor for further assistance if required.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Stepper */}
        <div className="mb-10">
          <div className="flex justify-between items-center relative">
            <div className="absolute left-0 top-1/2 transform -translate-y-1/2 w-full h-1 bg-slate-200 z-0 hidden sm:block"></div>
            <div className="absolute left-0 top-1/2 transform -translate-y-1/2 h-1 bg-sky-500 z-0 transition-all duration-300 hidden sm:block" style={{ width: `${((step - 1) / (steps.length - 1)) * 100}%` }}></div>
            
            {steps.map((s) => (
              <div key={s.num} className="relative z-10 flex flex-col items-center">
                <div className={`w-12 h-12 rounded-full flex items-center justify-center border-4 transition-colors duration-300 ${step >= s.num ? "bg-sky-500 border-sky-100 text-white" : "bg-white border-slate-200 text-slate-400"}`}>
                  {s.icon}
                </div>
                <span className={`mt-2 text-xs font-medium hidden sm:block ${step >= s.num ? "text-sky-600" : "text-slate-400"}`}>{s.title}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-6 md:p-8 animate-fade-in shadow-lg shadow-slate-200/50">
          
          {step === 1 && (
            <div className="space-y-6 animate-fade-in">
              <h2 className="text-2xl font-bold text-slate-800 mb-6 border-b pb-2">Personal Details</h2>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Full Name *</label>
                  <input
                    type="text"
                    name="fullName"
                    value={formData.fullName}
                    onChange={handleInputChange}
                    className={`input-field ${errors.fullName ? "border-red-500 ring-1 ring-red-500" : ""}`}
                    placeholder="Enter your full name"
                  />
                  {errors.fullName && <p className="mt-1 text-sm text-red-500">{errors.fullName}</p>}
                </div>
                
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Age *</label>
                    <input
                      type="number"
                      name="age"
                      value={formData.age}
                      onChange={handleInputChange}
                      className={`input-field ${errors.age ? "border-red-500 ring-1 ring-red-500" : ""}`}
                      placeholder="e.g. 25"
                      min="1" max="120"
                    />
                    {errors.age && <p className="mt-1 text-sm text-red-500">{errors.age}</p>}
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Gender</label>
                    <select
                      name="gender"
                      value={formData.gender}
                      onChange={handleInputChange}
                      className="input-field bg-white"
                    >
                      <option value="">Select</option>
                      <option value="male">Male</option>
                      <option value="female">Female</option>
                      <option value="other">Other</option>
                      <option value="prefer_not_to_say">Prefer not to say</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Mobile Number *</label>
                  <div className="relative">
                    <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">+91</span>
                    <input
                      type="tel"
                      name="mobile"
                      value={formData.mobile}
                      onChange={handleInputChange}
                      className={`input-field pl-10 ${errors.mobile ? "border-red-500 ring-1 ring-red-500" : ""}`}
                      placeholder="9876543210"
                      maxLength="10"
                    />
                  </div>
                  {errors.mobile && <p className="mt-1 text-sm text-red-500">{errors.mobile}</p>}
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Email Address *</label>
                  <input
                    type="email"
                    name="email"
                    value={formData.email}
                    onChange={handleInputChange}
                    className={`input-field ${errors.email ? "border-red-500 ring-1 ring-red-500" : ""}`}
                    placeholder="your.email@example.com"
                  />
                  {errors.email && <p className="mt-1 text-sm text-red-500">{errors.email}</p>}
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-6 animate-fade-in">
              <h2 className="text-2xl font-bold text-slate-800 mb-6 border-b pb-2">Pre-Counseling Questionnaire</h2>
              
              <div className="bg-sky-50 border border-sky-100 rounded-xl p-4 mb-6">
                <p className="text-sm text-sky-800 leading-relaxed">
                  To help us serve you better, please briefly describe what brings you to counseling today.
                  Your response is <strong className="font-semibold">completely confidential</strong> and will only be seen by your counselor.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  What challenges or issues would you like to discuss? *
                </label>
                <div className="relative">
                  <textarea
                    name="problemDescription"
                    value={formData.problemDescription}
                    onChange={handleInputChange}
                    rows="5"
                    className={`input-field resize-none ${errors.problemDescription ? "border-red-500 ring-1 ring-red-500" : ""}`}
                    placeholder="Please provide a brief description of your current feelings, challenges, or what you hope to achieve through counseling..."
                  ></textarea>
                </div>
                <div className="flex justify-between items-center mt-2">
                  {errors.problemDescription ? (
                    <p className="text-sm text-red-500">{errors.problemDescription}</p>
                  ) : (
                    <p className="text-sm text-slate-500">This helps the counselor prepare for your session.</p>
                  )}
                  <p className={`text-xs ${formData.problemDescription.length < 10 ? "text-red-400" : "text-slate-400"}`}>
                    {formData.problemDescription.length} chars (min 10)
                  </p>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-6 animate-fade-in">
              <h2 className="text-2xl font-bold text-slate-800 mb-6 border-b pb-2">Select Preferred Date & Time</h2>
              
              <div className="grid md:grid-cols-2 gap-8">
                {/* Calendar Selection */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-3 flex items-center gap-2">
                    <CalendarIcon size={18} className="text-sky-500" />
                    Available Dates
                  </label>
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 shadow-sm flex justify-center">
                    {fetchingDates ? (
                      <div className="h-64 flex flex-col items-center justify-center text-slate-400">
                        <div className="w-8 h-8 border-4 border-sky-200 border-t-sky-500 rounded-full animate-spin mb-4"></div>
                        <p>Loading calendar...</p>
                      </div>
                    ) : (
                      <DatePicker
                        selected={formData.appointmentDate}
                        onChange={(date) => {
                          setFormData(prev => ({ ...prev, appointmentDate: date, appointmentTime: null }));
                          if (errors.appointmentDate) setErrors(prev => ({ ...prev, appointmentDate: "" }));
                        }}
                        minDate={new Date()}
                        excludeDates={unavailableDates.map(d => new Date(d))}
                        inline
                        calendarClassName="shadow-none border-0 font-sans custom-calendar"
                      />
                    )}
                  </div>
                  {errors.appointmentDate && <p className="mt-2 text-sm text-red-500 text-center">{errors.appointmentDate}</p>}
                </div>

                {/* Time Slot Selection */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-3 flex items-center gap-2">
                    <Clock size={18} className="text-sky-500" />
                    Available Time Slots
                  </label>
                  
                  <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm min-h-[300px]">
                    {!formData.appointmentDate ? (
                      <div className="h-full flex flex-col items-center justify-center text-center text-slate-400 space-y-3">
                        <CalendarIcon size={32} className="opacity-50" />
                        <p>Please select a date first to view available time slots.</p>
                      </div>
                    ) : fetchingSlots ? (
                      <div className="h-full flex flex-col items-center justify-center text-slate-400">
                        <div className="w-8 h-8 border-4 border-sky-200 border-t-sky-500 rounded-full animate-spin mb-4"></div>
                        <p>Loading slots...</p>
                      </div>
                    ) : availableSlots.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 space-y-3">
                        <p>No slots available for this date.</p>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-3">
                        {availableSlots.map((slot, idx) => {
                          const isSelected = formData.appointmentTime?.startTime === slot.startTime;
                          return (
                            <button
                              key={idx}
                              disabled={!slot.available}
                              onClick={() => {
                                setFormData(prev => ({ ...prev, appointmentTime: slot }));
                                if (errors.appointmentTime) setErrors(prev => ({ ...prev, appointmentTime: "" }));
                              }}
                              className={`
                                w-full py-4 px-4 rounded-xl border flex justify-between items-center transition-all
                                ${!slot.available ? "bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed opacity-70" : 
                                  isSelected ? "bg-sky-50 border-sky-500 text-sky-700 ring-1 ring-sky-500 shadow-sm" : 
                                  "bg-white border-slate-200 text-slate-700 hover:border-sky-300 hover:shadow-sm"}
                              `}
                            >
                              <span className="font-medium text-lg tracking-wide">{slot.display}</span>
                              {isSelected && <CheckCircle2 className="text-sky-500" size={20} />}
                              {!slot.available && <span className="text-xs bg-slate-200 px-2 py-1 rounded-md">Booked</span>}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  {errors.appointmentTime && <p className="mt-2 text-sm text-red-500 text-center">{errors.appointmentTime}</p>}
                </div>
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-6 animate-fade-in">
              <h2 className="text-2xl font-bold text-slate-800 mb-6 border-b pb-2">Review & Pay</h2>
              
              <div className="bg-slate-50 rounded-xl p-6 border border-slate-200">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-y-6 gap-x-8">
                  <div>
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Client Details</h3>
                    <div className="space-y-2">
                      <p className="text-slate-800"><span className="font-medium text-slate-600 w-24 inline-block">Name:</span> {formData.fullName}</p>
                      <p className="text-slate-800"><span className="font-medium text-slate-600 w-24 inline-block">Age/Gender:</span> {formData.age} / {formData.gender || "Not specified"}</p>
                      <p className="text-slate-800"><span className="font-medium text-slate-600 w-24 inline-block">Mobile:</span> +91 {formData.mobile}</p>
                      <p className="text-slate-800"><span className="font-medium text-slate-600 w-24 inline-block">Email:</span> {formData.email}</p>
                    </div>
                  </div>
                  
                  <div>
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Appointment Info</h3>
                    <div className="space-y-2">
                      <p className="text-slate-800">
                        <span className="font-medium text-slate-600 w-24 inline-block">Date:</span> 
                        {formData.appointmentDate?.toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
                      </p>
                      <p className="text-slate-800">
                        <span className="font-medium text-slate-600 w-24 inline-block">Time:</span> 
                        {formData.appointmentTime?.display}
                      </p>
                      <p className="text-slate-800">
                        <span className="font-medium text-slate-600 w-24 inline-block">Mode:</span> 
                        Online (Google Meet)
                      </p>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="bg-sky-50 border border-sky-100 rounded-xl p-4 flex gap-3 text-sm text-sky-800">
                <Shield className="flex-shrink-0 text-sky-500" size={20} />
                <p>Payment of the <strong>Registration Fee (₹7)</strong> or <strong>Follow-up Fee (₹499)</strong> is required before confirming the appointment. By clicking "Proceed to Payment", you agree to our Terms of Service and Privacy Policy. Your payment will be processed securely via Razorpay.</p>
              </div>
            </div>
          )}

          {/* Navigation Buttons */}
          <div className="mt-8 flex justify-between items-center border-t pt-6">
            {step > 1 ? (
              <button 
                onClick={prevStep}
                disabled={loading}
                className="btn-secondary flex items-center gap-2 text-slate-600 px-5"
              >
                <ChevronLeft size={18} /> Back
              </button>
            ) : <div></div>}

            {step < steps.length ? (
              <button 
                onClick={nextStep}
                className="btn-primary flex items-center gap-2 px-6"
              >
                Next Step <ChevronRight size={18} />
              </button>
            ) : (
              <button 
                onClick={handleSubmit}
                disabled={loading}
                className="btn-primary flex items-center gap-2 px-8 shadow-md"
              >
                {loading ? (
                  <span className="flex items-center gap-2"><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div> Processing...</span>
                ) : (
                  <span className="flex items-center gap-2">Proceed to Payment <ChevronRight size={18} /></span>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default BookingPage;
