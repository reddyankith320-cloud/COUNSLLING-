import React from 'react';
import { Link } from 'react-router-dom';

/** Brand mark: a simple lotus/leaf on a teal tile. */
export const LogoMark = ({ size = 36, className = '' }) => (
  <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
    <rect width="64" height="64" rx="16" fill="#0d9488" />
    <g fill="none" stroke="#ffffff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M32 46c-9-3-14-9-14-17 0-6 3-11 7-13 3 2 5 6 5 10" />
      <path d="M32 46c9-3 14-9 14-17 0-6-3-11-7-13-3 2-5 6-5 10" />
      <path d="M32 46V22" />
      <path d="M32 22c0-4 2-7 5-9" />
    </g>
    <circle cx="32" cy="14" r="2.6" fill="#fbbf24" />
  </svg>
);

/**
 * Logo with wordmark. `tone="light"` for dark backgrounds.
 */
const Logo = ({ tone = 'dark', tagline = true, to = '/', onClick, size = 36 }) => {
  const nameColor = tone === 'light' ? 'text-white' : 'text-slate-900';
  const tagColor = tone === 'light' ? 'text-slate-400' : 'text-slate-500';

  return (
    <Link to={to} onClick={onClick} className="flex items-center gap-2.5 shrink-0" aria-label="Find My Peace – Home">
      <LogoMark size={size} />
      <span className="flex flex-col leading-none">
        <span className={`font-display font-semibold text-[1.15rem] tracking-tight ${nameColor}`}>Find My Peace</span>
        {tagline && (
          <span className={`text-[10px] font-medium tracking-wide mt-1 ${tagColor} hidden sm:block`}>
            Professional Counseling · 20+ Years
          </span>
        )}
      </span>
    </Link>
  );
};

export default Logo;
