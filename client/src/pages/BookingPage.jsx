import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar as CalendarIcon, Clock, User, FileText, ChevronRight, ChevronLeft, CheckCircle2, Shield, Lock, Video } from "lucide-react";
import DatePicker from "react-datepicker";
import toast from "react-hot-toast";
import api from "../services/api";
import { onSocketEvent } from "../services/socket";
import { COUNSELOR, PRICING } from "../config/site";

const toYMD = (dateObj) => {
  const year = dateObj.getFullYear();
  const month = String(dateObj.getMonth() + 1).padStart(2, "0");
  const day = String(dateObj.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const STEPS = [
  { num: 1, title: "Your details", icon: User },
  { num: 2, title: "Questionnaire", icon: FileText },
  { num: 3, title: "Pick a slot", icon: CalendarIcon },
  { num: 4, title: "Review", icon: CheckCircle2 },
];

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

  // Fetch unavailable dates (this month + next)
  const fetchDates = useCallback(async () => {
    setFetchingDates(true);
    try {
      const today = new Date();
      const year = today.getFullYear();
      const month = today.getMonth() + 1;
      const nextMonth = month === 12 ? 1 : month + 1;
      const nextYear = month === 12 ? year + 1 : year;

      const [r1, r2] = await Promise.all([
        api.get(`/slots/unavailable`, { params: { year, month } }),
        api.get(`/slots/unavailable`, { params: { year: nextYear, month: nextMonth } }),
      ]);

      setUnavailableDates([...r1.data.allUnavailable, ...r2.data.allUnavailable]);
    } catch (error) {
      console.error(error);
      toast.error("Failed to fetch calendar availability");
      setUnavailableDates([]);
    } finally {
      setFetchingDates(false);
    }
  }, []);

  useEffect(() => {
    fetchDates();
    return onSocketEvent("availability_changed", fetchDates);
  }, [fetchDates]);

  // Fetch available slots when a date is selected (and refresh on live updates)
  const fetchSlots = useCallback(async (dateObj) => {
    setFetchingSlots(true);
    try {
      const res = await api.get(`/slots/available-slots`, { params: { date: toYMD(dateObj) } });
      setAvailableSlots(res.data.slots);
    } catch (err) {
      console.error(err);
      toast.error("Failed to load time slots");
    } finally {
      setFetchingSlots(false);
    }
  }, []);

  useEffect(() => {
    if (!formData.appointmentDate) {
      setAvailableSlots([]);
      return;
    }
    fetchSlots(formData.appointmentDate);
    return onSocketEvent("availability_changed", () => fetchSlots(formData.appointmentDate));
  }, [formData.appointmentDate, fetchSlots]);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: "" }));
    }
  };

  const validateStep1 = () => {
    const newErrors = {};
    if (!formData.fullName.trim()) newErrors.fullName = "Full name is required";
    else if (formData.fullName.trim().length < 2) newErrors.fullName = "Please enter your full name";
    if (!formData.age) newErrors.age = "Age is required";
    else if (isNaN(formData.age) || formData.age < 1 || formData.age > 120) newErrors.age = "Enter a valid age";
    if (!formData.mobile.trim()) newErrors.mobile = "Mobile number is required";
    else if (!/^[6-9]\d{9}$/.test(formData.mobile)) newErrors.mobile = "Enter a valid 10-digit Indian mobile number";
    if (!formData.email.trim()) newErrors.email = "Email is required";
    else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = "Enter a valid email address";

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep2 = () => {
    const newErrors = {};
    if (!formData.problemDescription.trim()) newErrors.problemDescription = "Please describe what brings you here";
    else if (formData.problemDescription.trim().length < 10) newErrors.problemDescription = "Please write at least 10 characters";

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

    if (isValid) {
      setStep(prev => prev + 1);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const prevStep = () => {
    setStep(prev => prev - 1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleSubmit = async () => {
    if (!validateStep3()) return;

    setLoading(true);
    try {
      const payload = {
        fullName: formData.fullName.trim(),
        age: parseInt(formData.age, 10),
        gender: formData.gender,
        mobile: formData.mobile.trim(),
        email: formData.email.trim(),
        problemDescription: formData.problemDescription.trim(),
        appointmentDate: toYMD(formData.appointmentDate),
        startTime: formData.appointmentTime.startTime,
        endTime: formData.appointmentTime.endTime,
      };

      const response = await api.post("/bookings", payload);

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

      if (status === 409) {
        // Slot was taken while the user was filling the form — refresh and send them back
        toast.error(errMsg, { duration: 6000 });
        setFormData(prev => ({ ...prev, appointmentTime: null }));
        if (formData.appointmentDate) fetchSlots(formData.appointmentDate);
        setStep(3);
        return;
      }

      toast.error(errMsg);

      if (error.response?.data?.details) {
        const backendErrors = {};
        error.response.data.details.forEach(err => {
          backendErrors[err.field] = err.message;
        });
        setErrors(backendErrors);
        if (backendErrors.fullName || backendErrors.age || backendErrors.mobile || backendErrors.email) setStep(1);
        else if (backendErrors.problemDescription) setStep(2);
      }
    } finally {
      setLoading(false);
    }
  };

  const fieldClass = (name) => `input-field ${errors[name] ? "input-error" : ""}`;

  return (
    <div className="min-h-screen bg-sand-50 py-10 sm:py-14 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-10">
          <span className="eyebrow">Book a session</span>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold text-slate-900 mt-3">Schedule your counseling session</h1>
          <div className="mt-5 inline-flex items-center gap-3 bg-white border border-slate-200 rounded-2xl px-5 py-3 shadow-sm">
            <div className="w-10 h-10 bg-teal-600 rounded-xl flex items-center justify-center text-white font-display font-semibold">
              {COUNSELOR.initials}
            </div>
            <div className="text-left">
              <p className="font-semibold text-slate-800 text-sm">{COUNSELOR.name}</p>
              <p className="text-xs text-slate-500">{COUNSELOR.qualification} &middot; {COUNSELOR.experience} experience</p>
            </div>
          </div>
        </div>

        {maxFollowupReached && (
          <div className="mb-8 p-5 bg-amber-50 border border-amber-200 rounded-2xl text-amber-900">
            <div className="flex items-start gap-3">
              <Shield className="text-amber-600 flex-shrink-0 mt-0.5" size={22} />
              <div>
                <p className="font-bold text-base">Maximum follow-up sessions reached.</p>
                <p className="text-sm mt-1">
                  The maximum of {PRICING.maxFollowUps} follow-up sessions has been completed. Please contact the counselor for further assistance.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Stepper */}
        <div className="mb-8">
          <div className="flex justify-between items-start relative">
            <div className="absolute left-[12%] right-[12%] top-6 h-0.5 bg-slate-200 z-0"></div>
            <div
              className="absolute left-[12%] top-6 h-0.5 bg-teal-500 z-0 transition-all duration-500"
              style={{ width: `${((step - 1) / (STEPS.length - 1)) * 76}%` }}
            ></div>

            {STEPS.map(({ num, title, icon: Icon }) => {
              const done = step > num;
              const active = step === num;
              return (
                <div key={num} className="relative z-10 flex flex-col items-center w-1/4">
                  <div className={`w-12 h-12 rounded-full flex items-center justify-center border-2 transition-all duration-300 ${
                    done ? "bg-teal-600 border-teal-600 text-white" :
                    active ? "bg-white border-teal-600 text-teal-700 shadow-glow" :
                    "bg-white border-slate-200 text-slate-400"
                  }`}>
                    {done ? <CheckCircle2 size={20} /> : <Icon size={20} />}
                  </div>
                  <span className={`mt-2 text-[11px] sm:text-xs font-semibold text-center ${active || done ? "text-teal-700" : "text-slate-400"}`}>{title}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card p-6 sm:p-8 shadow-soft">

          {step === 1 && (
            <div className="space-y-6 animate-fade-in">
              <div>
                <h2 className="font-display text-2xl font-semibold text-slate-900">Your details</h2>
                <p className="text-sm text-slate-500 mt-1">We'll use these to send your meeting link and confirmation.</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label htmlFor="fullName" className="block text-sm font-medium text-slate-700 mb-2">Full name <span className="text-red-500">*</span></label>
                  <input
                    id="fullName"
                    type="text"
                    name="fullName"
                    autoComplete="name"
                    value={formData.fullName}
                    onChange={handleInputChange}
                    className={fieldClass("fullName")}
                    placeholder="Enter your full name"
                  />
                  {errors.fullName && <p className="mt-1.5 text-sm text-red-500">{errors.fullName}</p>}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="age" className="block text-sm font-medium text-slate-700 mb-2">Age <span className="text-red-500">*</span></label>
                    <input
                      id="age"
                      type="number"
                      name="age"
                      inputMode="numeric"
                      value={formData.age}
                      onChange={handleInputChange}
                      className={fieldClass("age")}
                      placeholder="e.g. 25"
                      min="1" max="120"
                    />
                    {errors.age && <p className="mt-1.5 text-sm text-red-500">{errors.age}</p>}
                  </div>
                  <div>
                    <label htmlFor="gender" className="block text-sm font-medium text-slate-700 mb-2">Gender</label>
                    <select
                      id="gender"
                      name="gender"
                      value={formData.gender}
                      onChange={handleInputChange}
                      className="input-field"
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
                  <label htmlFor="mobile" className="block text-sm font-medium text-slate-700 mb-2">Mobile number <span className="text-red-500">*</span></label>
                  <div className="relative">
                    <span className="absolute inset-y-0 left-0 flex items-center pl-4 text-slate-500 font-medium text-sm border-r border-slate-200 pr-3 my-2.5">+91</span>
                    <input
                      id="mobile"
                      type="tel"
                      name="mobile"
                      inputMode="numeric"
                      autoComplete="tel-national"
                      value={formData.mobile}
                      onChange={(e) => handleInputChange({ target: { name: "mobile", value: e.target.value.replace(/\D/g, "").slice(0, 10) } })}
                      className={`${fieldClass("mobile")} pl-16`}
                      placeholder="9876543210"
                      maxLength="10"
                    />
                  </div>
                  {errors.mobile && <p className="mt-1.5 text-sm text-red-500">{errors.mobile}</p>}
                </div>

                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-2">Email address <span className="text-red-500">*</span></label>
                  <input
                    id="email"
                    type="email"
                    name="email"
                    autoComplete="email"
                    value={formData.email}
                    onChange={handleInputChange}
                    className={fieldClass("email")}
                    placeholder="your.email@example.com"
                  />
                  {errors.email && <p className="mt-1.5 text-sm text-red-500">{errors.email}</p>}
                </div>
              </div>

              <p className="text-xs text-slate-500 flex items-center gap-1.5"><Lock size={12} /> Returning client? Use the same mobile number and email so your follow-up pricing is applied automatically.</p>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-6 animate-fade-in">
              <div>
                <h2 className="font-display text-2xl font-semibold text-slate-900">Pre-counseling questionnaire</h2>
                <p className="text-sm text-slate-500 mt-1">This helps your counselor prepare for your session.</p>
              </div>

              <div className="bg-teal-50 border border-teal-100 rounded-2xl p-4 flex gap-3">
                <Shield className="text-teal-600 flex-shrink-0 mt-0.5" size={18} />
                <p className="text-sm text-teal-900 leading-relaxed">
                  Please briefly describe what brings you to counseling today. Your response is <strong className="font-semibold">completely confidential</strong> and will only be seen by your counselor.
                </p>
              </div>

              <div>
                <label htmlFor="problemDescription" className="block text-sm font-medium text-slate-700 mb-2">
                  What challenges or issues would you like to discuss? <span className="text-red-500">*</span>
                </label>
                <textarea
                  id="problemDescription"
                  name="problemDescription"
                  value={formData.problemDescription}
                  onChange={handleInputChange}
                  rows="6"
                  maxLength="5000"
                  className={`${fieldClass("problemDescription")} resize-none leading-relaxed`}
                  placeholder="Share your current feelings, challenges, or what you hope to achieve through counseling..."
                ></textarea>
                <div className="flex justify-between items-center mt-2">
                  {errors.problemDescription ? (
                    <p className="text-sm text-red-500">{errors.problemDescription}</p>
                  ) : (
                    <p className="text-sm text-slate-500">Take your time — there are no wrong answers.</p>
                  )}
                  <p className={`text-xs tabular-nums ${formData.problemDescription.trim().length < 10 ? "text-amber-600" : "text-slate-400"}`}>
                    {formData.problemDescription.length} / 5000
                  </p>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-6 animate-fade-in">
              <div>
                <h2 className="font-display text-2xl font-semibold text-slate-900">Pick a date and time</h2>
                <p className="text-sm text-slate-500 mt-1">Sessions are {PRICING.sessionMinutes} minutes, in the evening (IST).</p>
              </div>

              <div className="grid md:grid-cols-2 gap-6">
                {/* Calendar Selection */}
                <div>
                  <p className="text-sm font-medium text-slate-700 mb-3 flex items-center gap-2">
                    <CalendarIcon size={16} className="text-teal-600" />
                    Available dates
                  </p>
                  <div className="bg-white p-3 rounded-2xl border border-slate-200 flex justify-center">
                    {fetchingDates ? (
                      <div className="h-72 flex flex-col items-center justify-center text-slate-400">
                        <div className="w-8 h-8 border-4 border-teal-100 border-t-teal-500 rounded-full animate-spin mb-4"></div>
                        <p className="text-sm">Loading calendar...</p>
                      </div>
                    ) : (
                      <DatePicker
                        selected={formData.appointmentDate}
                        onChange={(date) => {
                          setFormData(prev => ({ ...prev, appointmentDate: date, appointmentTime: null }));
                          if (errors.appointmentDate) setErrors(prev => ({ ...prev, appointmentDate: "" }));
                        }}
                        minDate={new Date()}
                        excludeDates={unavailableDates.map(d => new Date(`${d}T00:00:00`))}
                        inline
                      />
                    )}
                  </div>
                  {errors.appointmentDate && <p className="mt-2 text-sm text-red-500 text-center">{errors.appointmentDate}</p>}
                </div>

                {/* Time Slot Selection */}
                <div>
                  <p className="text-sm font-medium text-slate-700 mb-3 flex items-center gap-2">
                    <Clock size={16} className="text-teal-600" />
                    Available time slots
                  </p>

                  <div className="bg-white p-3 rounded-2xl border border-slate-200 min-h-[300px] flex flex-col">
                    {!formData.appointmentDate ? (
                      <div className="flex-1 flex flex-col items-center justify-center text-center text-slate-400 space-y-3 px-4">
                        <CalendarIcon size={32} className="opacity-40" />
                        <p className="text-sm">Select a date first to see available time slots.</p>
                      </div>
                    ) : fetchingSlots ? (
                      <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
                        <div className="w-8 h-8 border-4 border-teal-100 border-t-teal-500 rounded-full animate-spin mb-4"></div>
                        <p className="text-sm">Loading slots...</p>
                      </div>
                    ) : availableSlots.length === 0 || availableSlots.every(s => !s.available) ? (
                      <div className="flex-1 flex flex-col items-center justify-center text-center text-slate-500 space-y-2 px-4">
                        <p className="font-medium">No slots available on this date.</p>
                        <p className="text-sm text-slate-400">Please choose another day.</p>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-2.5">
                        <p className="text-xs text-slate-500 px-1">
                          {formData.appointmentDate.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
                        </p>
                        {availableSlots.map((slot) => {
                          const isSelected = formData.appointmentTime?.startTime === slot.startTime;
                          return (
                            <button
                              key={slot.startTime}
                              type="button"
                              disabled={!slot.available}
                              onClick={() => {
                                setFormData(prev => ({ ...prev, appointmentTime: slot }));
                                if (errors.appointmentTime) setErrors(prev => ({ ...prev, appointmentTime: "" }));
                              }}
                              className={`w-full py-3.5 px-4 rounded-xl border-2 flex justify-between items-center transition-all
                                ${!slot.available ? "bg-slate-50 border-slate-100 text-slate-400 cursor-not-allowed" :
                                  isSelected ? "bg-teal-50 border-teal-600 text-teal-800 shadow-sm" :
                                  "bg-white border-slate-200 text-slate-700 hover:border-teal-300 hover:bg-teal-50/40"}`}
                            >
                              <span className={`font-semibold ${!slot.available ? "line-through" : ""}`}>{slot.display}</span>
                              {isSelected && <CheckCircle2 className="text-teal-600" size={20} />}
                              {!slot.available && <span className="text-[11px] font-medium bg-slate-200 text-slate-600 px-2 py-0.5 rounded-md">Unavailable</span>}
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
              <div>
                <h2 className="font-display text-2xl font-semibold text-slate-900">Review and pay</h2>
                <p className="text-sm text-slate-500 mt-1">Please check your details before proceeding to payment.</p>
              </div>

              <div className="bg-sand-50 rounded-2xl p-5 sm:p-6 border border-sand-200">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-y-6 gap-x-8">
                  <div>
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Client details</h3>
                    <dl className="space-y-2 text-sm">
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Name</dt><dd className="text-slate-800 font-medium">{formData.fullName}</dd></div>
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Age / Gender</dt><dd className="text-slate-800 font-medium">{formData.age} / {formData.gender ? formData.gender.replace(/_/g, " ") : "Not specified"}</dd></div>
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Mobile</dt><dd className="text-slate-800 font-medium">+91 {formData.mobile}</dd></div>
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Email</dt><dd className="text-slate-800 font-medium break-all">{formData.email}</dd></div>
                    </dl>
                  </div>

                  <div>
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Session</h3>
                    <dl className="space-y-2 text-sm">
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Date</dt><dd className="text-slate-800 font-medium">{formData.appointmentDate?.toLocaleDateString("en-IN", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</dd></div>
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Time</dt><dd className="text-slate-800 font-medium">{formData.appointmentTime?.display} IST</dd></div>
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Mode</dt><dd className="text-slate-800 font-medium flex items-center gap-1.5"><Video size={14} className="text-teal-600" /> Online (Google Meet)</dd></div>
                      <div className="flex gap-3"><dt className="w-24 text-slate-500 shrink-0">Counselor</dt><dd className="text-slate-800 font-medium">{COUNSELOR.name}</dd></div>
                    </dl>
                  </div>
                </div>
              </div>

              <div className="bg-teal-50 border border-teal-100 rounded-2xl p-4 flex gap-3 text-sm text-teal-900">
                <Shield className="flex-shrink-0 text-teal-600 mt-0.5" size={18} />
                <p>
                  The exact fee — <strong>Registration (₹{PRICING.registrationFee})</strong> for first-time clients or <strong>Follow-up (₹{PRICING.followUpFee})</strong> for returning clients — is shown on the next screen before you pay. Payment is processed securely by Razorpay; your booking is confirmed only after successful payment.
                </p>
              </div>
            </div>
          )}

          {/* Navigation Buttons */}
          <div className="mt-8 flex justify-between items-center border-t border-slate-100 pt-6">
            {step > 1 ? (
              <button
                type="button"
                onClick={prevStep}
                disabled={loading}
                className="btn-ghost"
              >
                <ChevronLeft size={18} /> Back
              </button>
            ) : <div></div>}

            {step < STEPS.length ? (
              <button
                type="button"
                onClick={nextStep}
                className="btn-primary px-6"
              >
                Continue <ChevronRight size={18} />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={loading}
                className="btn-primary px-7"
              >
                {loading ? (
                  <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div> Processing...</>
                ) : (
                  <>Proceed to Payment <ChevronRight size={18} /></>
                )}
              </button>
            )}
          </div>
        </div>

        <p className="text-center text-xs text-slate-500 mt-6 flex items-center justify-center gap-1.5">
          <Lock size={12} /> Your information is encrypted and never shared.
        </p>
      </div>
    </div>
  );
};

export default BookingPage;
