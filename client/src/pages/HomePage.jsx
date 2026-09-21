import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Shield, Video, Heart, CheckCircle2, ArrowRight, UserCircle, Activity, Briefcase,
  CalendarCheck, CreditCard, Clock, Languages, Sparkles, Quote, Lock, ChevronDown
} from 'lucide-react';
import { COUNSELOR, PRICING, SESSION_TIMES } from '../config/site';

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: (i = 0) => ({ opacity: 1, y: 0, transition: { duration: 0.6, delay: i * 0.1, ease: [0.22, 1, 0.36, 1] } }),
};

const Reveal = ({ children, delay = 0, className = '' }) => (
  <motion.div
    className={className}
    variants={fadeUp}
    initial="hidden"
    whileInView="show"
    viewport={{ once: true, margin: '-60px' }}
    custom={delay}
  >
    {children}
  </motion.div>
);

const SERVICES = [
  {
    title: 'Individual Counseling',
    icon: UserCircle,
    color: 'bg-teal-50 text-teal-600',
    desc: 'Personalised support for anxiety, depression, stress, low mood, and personal growth.',
  },
  {
    title: 'Relationship Counseling',
    icon: Heart,
    color: 'bg-rose-50 text-rose-500',
    desc: 'Navigate conflict, rebuild communication, and strengthen bonds with the people you love.',
  },
  {
    title: 'Career Guidance',
    icon: Briefcase,
    color: 'bg-amber-50 text-amber-600',
    desc: 'Clarity and direction for professional decisions, burnout, and work-related stress.',
  },
  {
    title: 'HIV/AIDS & STI Counseling',
    icon: Activity,
    color: 'bg-violet-50 text-violet-600',
    desc: 'Confidential guidance on prevention, coping with a diagnosis, treatment adherence, stigma, relationships, and referrals to healthcare services.',
  },
];

const STEPS = [
  { icon: CalendarCheck, title: 'Choose a slot', desc: `Pick an evening slot that suits you (${SESSION_TIMES}) and tell us briefly what brings you here.` },
  { icon: CreditCard, title: 'Pay securely', desc: 'Complete payment via UPI, card, or net banking through Razorpay. No hidden charges.' },
  { icon: Video, title: 'Join on Google Meet', desc: 'Your private meeting link arrives instantly by email, SMS, and WhatsApp.' },
];

const FAQS = [
  {
    q: 'How long is a session?',
    a: `Each session is ${PRICING.sessionMinutes} minutes, one-on-one with ${COUNSELOR.name} over Google Meet.`,
  },
  {
    q: 'What does the registration fee cover?',
    a: `The one-time ₹${PRICING.registrationFee} registration fee covers your first session, including assessment, case evaluation, and a personalised counseling plan. Follow-up sessions are ₹${PRICING.followUpFee} each (up to ${PRICING.maxFollowUps} per registration).`,
  },
  {
    q: 'Is everything I share confidential?',
    a: 'Yes. Sessions are strictly private and confidential. Your pre-session notes are seen only by your counselor, and nothing is shared with anyone else.',
  },
  {
    q: 'Which languages are sessions available in?',
    a: 'Sessions are available in Telugu and English. A live translation room is also available if you and the counselor speak different languages.',
  },
  {
    q: 'What if I need to reschedule?',
    a: 'Please contact us using the details in the footer as early as possible and we will help you find another slot.',
  },
];

const HomePage = () => {
  return (
    <div className="flex flex-col">

      {/* ============================ HERO ============================ */}
      <section className="relative overflow-hidden -mt-[4.5rem] pt-[4.5rem]">
        {/* Backdrop */}
        <div className="absolute inset-0 bg-gradient-to-b from-teal-50/80 via-sand-50 to-sand-50" />
        <div className="absolute inset-0 bg-dots opacity-70 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_70%)]" />
        <div className="absolute -top-40 -right-40 w-[34rem] h-[34rem] rounded-full bg-teal-200/40 blur-3xl" />
        <div className="absolute top-1/2 -left-40 w-[26rem] h-[26rem] rounded-full bg-amber-100/60 blur-3xl" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative pt-14 pb-20 lg:pt-24 lg:pb-32">
          <div className="grid lg:grid-cols-12 gap-12 lg:gap-8 items-center">

            {/* Copy */}
            <div className="lg:col-span-7 text-center lg:text-left">
              <motion.div variants={fadeUp} initial="hidden" animate="show" custom={0}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/80 border border-teal-100 text-teal-800 font-medium text-sm mb-7 shadow-sm">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-teal-500"></span>
                </span>
                Online sessions available · Telugu & English
              </motion.div>

              <motion.h1 variants={fadeUp} initial="hidden" animate="show" custom={1}
                className="font-display text-[2.6rem] leading-[1.08] sm:text-5xl lg:text-[3.9rem] font-semibold text-slate-900 mb-6">
                A calmer mind begins with{' '}
                <span className="relative inline-block">
                  <span className="relative z-10 text-teal-700">one conversation.</span>
                  <span className="absolute left-0 right-0 bottom-1 h-3 bg-amber-200/70 -rotate-1 rounded-sm" aria-hidden="true" />
                </span>
              </motion.h1>

              <motion.p variants={fadeUp} initial="hidden" animate="show" custom={2}
                className="text-lg md:text-xl text-slate-600 mb-9 max-w-2xl mx-auto lg:mx-0 leading-relaxed">
                Professional, compassionate counseling with {COUNSELOR.name} — {COUNSELOR.experience.toLowerCase()} of helping individuals and families find clarity, confidence, and peace.
              </motion.p>

              <motion.div variants={fadeUp} initial="hidden" animate="show" custom={3}
                className="flex flex-col sm:flex-row gap-3 justify-center lg:justify-start">
                <Link to="/booking" className="btn-primary text-base px-7 py-3.5 group">
                  Book a Session
                  <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" />
                </Link>
                <a href="#how" className="btn-ghost text-base px-6 py-3.5 bg-white/70 border border-slate-200">
                  How it works
                </a>
              </motion.div>

              <motion.div variants={fadeUp} initial="hidden" animate="show" custom={4}
                className="mt-11 grid grid-cols-3 gap-4 max-w-md mx-auto lg:mx-0">
                {[
                  { v: '20+', l: 'Years experience' },
                  { v: 'MSW', l: 'Postgraduate degree' },
                  { v: '500+', l: 'Clients supported' },
                ].map((s) => (
                  <div key={s.l} className="text-center lg:text-left">
                    <div className="font-display text-2xl sm:text-3xl font-semibold text-slate-900">{s.v}</div>
                    <div className="text-xs sm:text-sm text-slate-500 font-medium">{s.l}</div>
                  </div>
                ))}
              </motion.div>
            </div>

            {/* Counselor card */}
            <div className="lg:col-span-5">
              <motion.div
                initial={{ opacity: 0, scale: 0.96, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.7, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
                className="relative max-w-md mx-auto"
              >
                <div className="absolute -inset-3 bg-gradient-to-tr from-teal-300/50 via-transparent to-amber-200/60 rounded-[2.2rem] blur-xl" />

                <div className="relative bg-white rounded-[2rem] shadow-soft border border-white/70 p-3">
                  <div className="rounded-[1.5rem] bg-gradient-to-br from-teal-600 via-teal-700 to-slate-900 p-8 text-white relative overflow-hidden">
                    <div className="absolute -top-10 -right-10 w-40 h-40 rounded-full bg-white/10" />
                    <div className="absolute -bottom-16 -left-10 w-48 h-48 rounded-full bg-white/5" />

                    <div className="relative">
                      <div className="w-24 h-24 rounded-2xl bg-white/15 backdrop-blur border border-white/20 flex items-center justify-center mb-6">
                        <span className="font-display text-4xl font-semibold tracking-tight">{COUNSELOR.initials}</span>
                      </div>
                      <p className="text-teal-100 text-xs font-bold uppercase tracking-[0.18em] mb-2">Your counselor</p>
                      <h2 className="font-display text-2xl font-semibold mb-1">{COUNSELOR.name}</h2>
                      <p className="text-teal-100/90 text-sm leading-relaxed">
                        {COUNSELOR.qualificationLong}
                      </p>

                      <div className="mt-6 flex flex-wrap gap-2">
                        {['Empathetic', 'Evidence-based', 'Culturally sensitive'].map((t) => (
                          <span key={t} className="text-xs font-medium bg-white/10 border border-white/15 px-2.5 py-1 rounded-full">{t}</span>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 divide-x divide-slate-100 py-4">
                    {[
                      { icon: Clock, l: 'Evening slots', s: '6–9 PM IST' },
                      { icon: Video, l: 'Google Meet', s: '1-on-1 video' },
                      { icon: Languages, l: 'Languages', s: 'Telugu · English' },
                    ].map(({ icon: Icon, l, s }) => (
                      <div key={l} className="px-3 text-center">
                        <Icon size={18} className="mx-auto text-teal-600 mb-1.5" />
                        <p className="text-xs font-semibold text-slate-800">{l}</p>
                        <p className="text-[11px] text-slate-500">{s}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Floating badge (sits over the dark card corner so it never covers text) */}
                <div className="absolute -top-5 -right-2 sm:-right-6 bg-white px-4 py-3 rounded-2xl shadow-soft border border-slate-100 flex items-center gap-3 animate-float">
                  <div className="w-10 h-10 bg-emerald-100 rounded-full flex items-center justify-center text-emerald-600">
                    <Shield size={20} />
                  </div>
                  <div>
                    <p className="font-bold text-slate-800 text-sm leading-tight">100% Confidential</p>
                    <p className="text-[11px] text-slate-500">Private & secure sessions</p>
                  </div>
                </div>
              </motion.div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================ HOW IT WORKS ============================ */}
      <section id="how" className="py-20 bg-white border-y border-slate-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <Reveal className="text-center max-w-2xl mx-auto mb-14">
            <span className="eyebrow">Simple & quick</span>
            <h2 className="section-title mt-3">Book in three easy steps</h2>
          </Reveal>

          <div className="grid md:grid-cols-3 gap-6 lg:gap-8 relative">
            <div className="hidden md:block absolute top-9 left-[16%] right-[16%] h-px bg-gradient-to-r from-transparent via-teal-200 to-transparent" />
            {STEPS.map(({ icon: Icon, title, desc }, i) => (
              <Reveal key={title} delay={i} className="relative text-center px-4">
                <div className="relative mx-auto w-[4.5rem] h-[4.5rem] rounded-2xl bg-teal-50 border border-teal-100 flex items-center justify-center text-teal-600 mb-5">
                  <Icon size={28} />
                  <span className="absolute -top-2 -right-2 w-7 h-7 rounded-full bg-slate-900 text-white text-xs font-bold flex items-center justify-center">{i + 1}</span>
                </div>
                <h3 className="font-display text-xl font-semibold text-slate-900 mb-2">{title}</h3>
                <p className="text-slate-600 leading-relaxed">{desc}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ============================ SERVICES ============================ */}
      <section id="services" className="py-20 lg:py-24 bg-sand-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <Reveal className="text-center max-w-3xl mx-auto mb-14">
            <span className="eyebrow">Services</span>
            <h2 className="section-title mt-3 mb-4">How we can help you</h2>
            <p className="text-lg text-slate-600">Specialised counseling tailored to your unique needs and challenges — in a safe, judgement-free space.</p>
          </Reveal>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 lg:gap-6">
            {SERVICES.map(({ title, icon: Icon, color, desc }, i) => (
              <Reveal key={title} delay={i}>
                <div className="card h-full p-7 lg:p-8 hover:shadow-soft hover:-translate-y-1 transition-all duration-300 group">
                  <div className="flex items-start gap-5">
                    <div className={`w-14 h-14 rounded-2xl ${color} flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform`}>
                      <Icon size={26} />
                    </div>
                    <div>
                      <h3 className="font-display text-xl font-semibold text-slate-900 mb-2">{title}</h3>
                      <p className="text-slate-600 leading-relaxed">{desc}</p>
                    </div>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ============================ ABOUT ============================ */}
      <section id="about" className="py-20 lg:py-24 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            <Reveal>
              <div className="relative">
                <div className="absolute -inset-4 bg-gradient-to-br from-teal-100 to-amber-50 rounded-[2rem] -rotate-2" />
                <div className="relative bg-sand-50 rounded-[1.75rem] border border-sand-200 p-8 lg:p-10">
                  <Quote className="text-teal-300 mb-4" size={36} />
                  <p className="font-display text-xl lg:text-2xl text-slate-800 leading-relaxed mb-6">
                    "Every person deserves a space where they can speak freely, feel heard, and be guided with respect — in their own language."
                  </p>
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-full bg-teal-600 text-white flex items-center justify-center font-display font-semibold">{COUNSELOR.initials}</div>
                    <div>
                      <p className="font-semibold text-slate-900">{COUNSELOR.name}</p>
                      <p className="text-xs text-slate-500">{COUNSELOR.qualification} · {COUNSELOR.experience}</p>
                    </div>
                  </div>
                </div>

                <div className="relative grid grid-cols-2 gap-4 mt-8">
                  <div className="card p-5 text-center">
                    <div className="font-display text-3xl font-semibold text-teal-700 mb-1">20+</div>
                    <div className="text-sm font-medium text-slate-600">Years of professional counseling</div>
                  </div>
                  <div className="card p-5 text-center">
                    <div className="font-display text-3xl font-semibold text-amber-600 mb-1">MSW</div>
                    <div className="text-sm font-medium text-slate-600">Master of Social Work</div>
                  </div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={1}>
              <span className="eyebrow">About your counselor</span>
              <h2 className="section-title mt-3 mb-6">{COUNSELOR.name}</h2>
              <p className="text-slate-600 mb-5 leading-relaxed text-lg">
                A dedicated counseling professional with a {COUNSELOR.qualificationLong} and over 20 years of experience helping individuals and families navigate emotional, personal, and social challenges.
              </p>
              <p className="text-slate-600 mb-8 leading-relaxed">
                She provides compassionate, confidential, and client-centered counseling — offering guidance in a supportive and respectful environment, with deep cultural understanding as a native Telugu speaker.
              </p>
              <ul className="grid sm:grid-cols-2 gap-3">
                {['Empathy & active listening', 'Evidence-based approaches', 'Strict confidentiality', 'Culturally sensitive practice'].map((item) => (
                  <li key={item} className="flex items-center gap-3 bg-sand-50 border border-sand-200 rounded-xl px-4 py-3">
                    <CheckCircle2 className="text-teal-600 flex-shrink-0" size={18} />
                    <span className="text-slate-700 font-medium text-sm">{item}</span>
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ============================ PRICING ============================ */}
      <section id="pricing" className="py-20 lg:py-24 bg-slate-950 relative overflow-hidden">
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[50rem] h-[50rem] rounded-full bg-teal-500/10 blur-3xl" />
        <div className="absolute inset-0 bg-dots opacity-20" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
          <Reveal className="text-center max-w-2xl mx-auto mb-12">
            <span className="eyebrow text-teal-300">Transparent pricing</span>
            <h2 className="section-title text-white mt-3 mb-4">Ready to start your journey?</h2>
            <p className="text-lg text-slate-400">Take the first step towards better mental health today. No subscriptions, no hidden fees.</p>
          </Reveal>

          <div className="grid md:grid-cols-2 gap-6 max-w-4xl mx-auto">
            <Reveal>
              <div className="relative bg-white rounded-3xl p-8 lg:p-9 h-full shadow-soft">
                <div className="absolute -top-3 left-8 bg-teal-600 text-white text-xs font-bold uppercase tracking-wider px-3 py-1 rounded-full shadow">Start here</div>
                <p className="text-sm font-semibold text-slate-500 mb-2">Registration Fee</p>
                <div className="flex items-baseline gap-1 mb-4">
                  <span className="font-display text-5xl font-semibold text-slate-900">₹{PRICING.registrationFee}</span>
                  <span className="text-slate-500 text-sm">one-time</span>
                </div>
                <p className="text-slate-600 text-sm leading-relaxed mb-6">
                  Covers your first counseling session, including assessment, case evaluation, and a personalised counseling plan.
                </p>
                <ul className="space-y-3 mb-8 text-sm">
                  {[`${PRICING.sessionMinutes}-minute 1-on-1 video session`, 'Google Meet link sent instantly', 'Email, SMS & WhatsApp confirmation'].map((f) => (
                    <li key={f} className="flex items-center gap-2.5 text-slate-700"><CheckCircle2 size={16} className="text-teal-600 shrink-0" />{f}</li>
                  ))}
                </ul>
                <Link to="/booking" className="btn-primary w-full py-3.5 text-base">
                  Book Your First Session <ArrowRight size={18} />
                </Link>
              </div>
            </Reveal>

            <Reveal delay={1}>
              <div className="bg-white/5 backdrop-blur border border-white/10 rounded-3xl p-8 lg:p-9 h-full text-white">
                <p className="text-sm font-semibold text-slate-400 mb-2">Follow-up Session</p>
                <div className="flex items-baseline gap-1 mb-4">
                  <span className="font-display text-5xl font-semibold">₹{PRICING.followUpFee}</span>
                  <span className="text-slate-400 text-sm">per session</span>
                </div>
                <p className="text-slate-300 text-sm leading-relaxed mb-6">
                  Continue your progress with follow-up sessions, recommended by your counselor after the first meeting.
                </p>
                <ul className="space-y-3 mb-8 text-sm">
                  {[`Up to ${PRICING.maxFollowUps} follow-ups per registration`, 'Same counselor, same care', 'Book any available evening slot'].map((f) => (
                    <li key={f} className="flex items-center gap-2.5 text-slate-200"><CheckCircle2 size={16} className="text-teal-400 shrink-0" />{f}</li>
                  ))}
                </ul>
                <div className="flex items-center gap-2 text-xs text-amber-300 bg-amber-400/10 border border-amber-400/20 rounded-xl px-3 py-2.5">
                  <Sparkles size={14} /> Automatically applied when you book again with the same details.
                </div>
              </div>
            </Reveal>
          </div>

          <Reveal className="mt-10 flex flex-wrap justify-center gap-x-8 gap-y-3 text-sm text-slate-400">
            <span className="flex items-center gap-2"><Lock size={15} className="text-teal-400" /> Secured by Razorpay</span>
            <span className="flex items-center gap-2"><Shield size={15} className="text-teal-400" /> 100% private & confidential</span>
            <span className="flex items-center gap-2"><Video size={15} className="text-teal-400" /> Google Meet video sessions</span>
          </Reveal>
        </div>
      </section>

      {/* ============================ FAQ ============================ */}
      <section id="faq" className="py-20 lg:py-24 bg-sand-50">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <Reveal className="text-center mb-12">
            <span className="eyebrow">FAQ</span>
            <h2 className="section-title mt-3">Common questions</h2>
          </Reveal>

          <div className="space-y-3">
            {FAQS.map(({ q, a }, i) => (
              <Reveal key={q} delay={i * 0.5}>
                <details className="group card px-6 py-1 open:shadow-soft transition-shadow">
                  <summary className="flex items-center justify-between gap-4 py-4 cursor-pointer list-none font-semibold text-slate-900 [&::-webkit-details-marker]:hidden">
                    {q}
                    <ChevronDown size={18} className="text-slate-400 shrink-0 transition-transform group-open:rotate-180" />
                  </summary>
                  <p className="pb-5 text-slate-600 leading-relaxed">{a}</p>
                </details>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ============================ FINAL CTA ============================ */}
      <section className="py-16 bg-white border-t border-slate-100">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <Reveal>
            <div className="relative overflow-hidden rounded-3xl bg-gradient-to-r from-teal-600 to-teal-500 text-white p-8 sm:p-12 text-center shadow-glow">
              <div className="absolute -top-16 -right-16 w-56 h-56 rounded-full bg-white/10" />
              <div className="absolute -bottom-20 -left-10 w-64 h-64 rounded-full bg-white/10" />
              <h2 className="font-display text-3xl sm:text-4xl font-semibold mb-3 relative">You don't have to face it alone.</h2>
              <p className="text-teal-50 text-lg mb-8 relative max-w-xl mx-auto">Evening slots are available every day. Book a confidential session and take the first step today.</p>
              <Link to="/booking" className="relative inline-flex items-center gap-2 bg-white text-teal-700 font-semibold px-7 py-3.5 rounded-xl hover:bg-teal-50 transition-colors shadow-lg">
                Book a Session <ArrowRight size={18} />
              </Link>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
};

export default HomePage;
