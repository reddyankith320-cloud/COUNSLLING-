import React from 'react';
import { Link } from 'react-router-dom';
import { Shield, Video, Heart, CheckCircle2, ArrowRight, UserCircle, Activity } from 'lucide-react';

const HomePage = () => {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-br from-sky-50 via-white to-sky-100 pt-16 pb-24 lg:pt-24 lg:pb-32">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMzAiIGN5PSIzMCIgcj0iMiIgZmlsbD0iIzBlYTVlOSIgZmlsbC1vcGFjaXR5PSIwLjA1Ii8+PC9zdmc+')] opacity-50 z-0"></div>
        
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
          <div className="flex flex-col lg:flex-row items-center gap-12 lg:gap-8">
            <div className="w-full lg:w-1/2 text-center lg:text-left animate-fade-in">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-sky-100 text-sky-700 font-medium text-sm mb-6">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                </span>
                Online Sessions Available
              </div>
              <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold text-slate-900 tracking-tight leading-tight mb-6">
                Find peace of mind with <span className="text-transparent bg-clip-text bg-gradient-to-r from-sky-500 to-green-500">Find My Peace</span>
              </h1>
              <p className="text-lg md:text-xl text-slate-600 mb-8 max-w-2xl mx-auto lg:mx-0 leading-relaxed">
                Professional, compassionate counseling — guiding you towards a brighter tomorrow.
              </p>
              <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start">
                <Link to="/booking" className="btn-primary text-lg px-8 py-4 flex items-center justify-center gap-2 group">
                  Book a Session
                  <ArrowRight size={20} className="group-hover:translate-x-1 transition-transform" />
                </Link>
                <a href="#about" className="btn-outline text-lg px-8 py-4 flex items-center justify-center">
                  Learn More
                </a>
              </div>
              
              <div className="mt-10 flex items-center justify-center lg:justify-start gap-4 text-sm text-slate-500 font-medium">
                <div className="flex -space-x-2">
                  {[1, 2, 3, 4].map(i => (
                    <div key={i} className="w-8 h-8 rounded-full bg-slate-200 border-2 border-white flex items-center justify-center overflow-hidden">
                      <UserCircle size={32} className="text-slate-400" />
                    </div>
                  ))}
                </div>
                <p>Trusted by 500+ clients</p>
              </div>
            </div>
            
            <div className="w-full lg:w-1/2">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-tr from-sky-200 to-green-100 rounded-[2rem] transform rotate-3 scale-105 blur-lg opacity-60"></div>
                <div className="relative bg-white p-2 rounded-[2rem] shadow-2xl border border-white/50">
                  <div className="aspect-[4/3] rounded-[1.5rem] overflow-hidden bg-slate-100 relative">
                    {/* Counselor Profile */}
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400">
                      <UserCircle size={120} strokeWidth={1} />
                      <p className="mt-4 font-semibold text-slate-600">Adulla Sridevi Reddy</p>
                      <p className="text-xs text-slate-400">Master of Social Work (MSW) - Postgraduate Degree · 20+ Years of Professional Counseling Experience</p>
                    </div>
                  </div>
                  
                  {/* Floating badge */}
                  <div className="absolute -bottom-6 -left-6 bg-white p-4 rounded-xl shadow-xl border border-slate-100 flex items-center gap-4 animate-bounce" style={{ animationDuration: '3s' }}>
                    <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center text-green-600">
                      <Shield size={24} />
                    </div>
                    <div>
                      <p className="font-bold text-slate-800">100% Secure</p>
                      <p className="text-xs text-slate-500">Confidential Sessions</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Services Section */}
      <section id="services" className="py-20 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-3xl mx-auto mb-16">
            <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">How we can help you</h2>
            <p className="text-lg text-slate-600">We offer specialized counseling services tailored to your unique needs and challenges.</p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {[
              { title: 'Individual Counseling', icon: <UserCircle className="w-8 h-8 text-sky-500" />, desc: 'Personalized support for anxiety, depression, stress, and personal growth.' },
              { title: 'Relationship Counseling', icon: <Heart className="w-8 h-8 text-rose-500" />, desc: 'Navigate conflicts, improve communication, and strengthen bonds with loved ones.' },
              { title: 'Career Guidance', icon: <CheckCircle2 className="w-8 h-8 text-green-500" />, desc: 'Clarity and direction for professional development and work-related stress.' },
              { title: 'HIV/AIDS & STI Counseling', icon: <Activity className="w-8 h-8 text-purple-500" />, desc: 'Confidential counseling for individuals seeking guidance on HIV and sexually transmitted infections (STIs). Services include prevention education, emotional support, coping with diagnosis, treatment adherence, relationship guidance, stigma management, and referrals to appropriate healthcare services when required.' }
            ].map((service, idx) => (
              <div key={idx} className="card p-8 hover:shadow-md transition-shadow group">
                <div className="w-16 h-16 rounded-2xl bg-slate-50 flex items-center justify-center mb-6 group-hover:bg-sky-50 transition-colors">
                  {service.icon}
                </div>
                <h3 className="text-xl font-bold text-slate-900 mb-3">{service.title}</h3>
                <p className="text-slate-600 leading-relaxed">{service.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* About Section */}
      <section id="about" className="py-20 bg-slate-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col lg:flex-row items-center gap-12">
            <div className="w-full lg:w-1/2 order-2 lg:order-1">
              <div className="grid grid-cols-2 gap-4">
                <div className="card p-6 text-center">
                  <div className="text-3xl font-bold text-sky-500 mb-2">20+</div>
                  <div className="text-sm font-medium text-slate-600">Years of Professional Counseling Experience</div>
                </div>
                <div className="card p-6 text-center">
                  <div className="text-3xl font-bold text-green-500 mb-2">MSW</div>
                  <div className="text-sm font-medium text-slate-600">Master of Social Work (MSW) - Postgraduate Degree</div>
                </div>
                <div className="card p-6 text-center col-span-2 bg-gradient-to-r from-sky-500 to-sky-600 text-white">
                  <div className="text-2xl font-bold mb-1">Native Telugu Speaker</div>
                  <div className="text-sm text-sky-100">Deep cultural understanding</div>
                </div>
              </div>
            </div>
            
            <div className="w-full lg:w-1/2 order-1 lg:order-2">
              <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-6">About Your Counselor</h2>
              <h3 className="text-xl font-semibold text-sky-600 mb-4">Adulla Sridevi Reddy</h3>
              <p className="text-sm text-slate-500 mb-4 font-medium">Master of Social Work (MSW) - Postgraduate Degree · 20+ Years of Professional Counseling Experience</p>
              <p className="text-slate-600 mb-6 leading-relaxed">
                Adulla Sridevi Reddy is a dedicated counseling professional with a Master of Social Work (MSW) - Postgraduate Degree and over 20 years of experience helping individuals and families navigate emotional, personal, and social challenges.
              </p>
              <p className="text-slate-600 mb-8 leading-relaxed">
                She provides compassionate, confidential, and client-centered counseling services, offering guidance in a supportive and respectful environment.
              </p>
              <ul className="space-y-4">
                {['Empathy and Active Listening', 'Evidence-based Therapy Approaches', 'Strict Confidentiality', 'Culturally Sensitive Practice'].map((item, idx) => (
                  <li key={idx} className="flex items-center gap-3">
                    <CheckCircle2 className="text-green-500 flex-shrink-0" size={20} />
                    <span className="text-slate-700 font-medium">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing/Booking CTA */}
      <section className="py-24 bg-white relative overflow-hidden">
        <div className="absolute top-0 right-0 -mt-20 -mr-20 w-80 h-80 bg-green-50 rounded-full blur-3xl opacity-50"></div>
        <div className="absolute bottom-0 left-0 -mb-20 -ml-20 w-80 h-80 bg-sky-50 rounded-full blur-3xl opacity-50"></div>
        
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 text-center">
          <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-6">Ready to start your journey?</h2>
          <p className="text-xl text-slate-600 mb-10 max-w-2xl mx-auto">
            Take the first step towards better mental health today. All sessions are conducted securely via Google Meet.
          </p>
          
          <div className="bg-white border-2 border-sky-100 shadow-xl rounded-2xl p-8 max-w-lg mx-auto mb-10 relative">
            <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-gradient-to-r from-sky-500 to-sky-600 text-white px-6 py-1 rounded-full text-sm font-bold uppercase tracking-wider shadow-md whitespace-nowrap">
              Consultation Fees
            </div>
            
            <div className="flex flex-col w-full mb-6 pt-6 gap-6">
              
              {/* Registration Fee Block */}
              <div className="flex flex-col items-center">
                <span className="text-xl text-slate-500 font-medium mb-1">Registration Fee</span>
                <span className="text-4xl font-extrabold text-slate-900 mb-4">₹7</span>
                <p className="text-sm text-slate-600 text-center leading-relaxed">
                  One-time registration fee for your first counseling session, including assessment, case evaluation, and a personalized counseling plan.
                </p>
              </div>

              <div className="w-full border-t border-slate-100 my-2"></div>

              {/* Follow-up Fee Block */}
              <div className="flex flex-col items-center">
                <span className="text-xl text-slate-500 font-medium mb-1">Follow-up Session</span>
                <span className="text-3xl font-bold text-slate-700 mb-2">₹499</span>
                <span className="text-sm font-medium text-amber-600 bg-amber-50 px-4 py-1.5 rounded-full mb-3">Up to 3 follow-up sessions only.</span>
                <p className="text-sm text-slate-600 text-center leading-relaxed">
                  ₹499 per follow-up session (Maximum of 3 follow-up sessions per registration).
                </p>
              </div>

            </div>
            
            <ul className="space-y-4 text-left mb-8 mt-4 pt-4 border-t border-slate-100">
              <li className="flex items-center gap-3">
                <Video className="text-sky-500" size={20} />
                <span className="text-slate-700">1-on-1 Video call (Google Meet)</span>
              </li>
              <li className="flex items-center gap-3">
                <Shield className="text-sky-500" size={20} />
                <span className="text-slate-700">100% Private & Confidential</span>
              </li>
            </ul>
            
            <Link to="/booking" className="btn-primary w-full block py-4 text-lg text-center shadow-lg shadow-sky-500/30">
              Book Your Session Now
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
};

export default HomePage;
