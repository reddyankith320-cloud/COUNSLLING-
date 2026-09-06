import React from 'react';

const Loader = ({ fullScreen = false }) => {
  const content = (
    <div className="flex flex-col items-center justify-center">
      <div className="relative w-16 h-16">
        <div className="absolute top-0 left-0 w-full h-full border-4 border-sky-100 rounded-full"></div>
        <div className="absolute top-0 left-0 w-full h-full border-4 border-sky-500 rounded-full border-t-transparent animate-spin"></div>
      </div>
      <p className="mt-4 text-slate-500 font-medium animate-pulse">Loading...</p>
    </div>
  );

  if (fullScreen) {
    return (
      <div className="fixed inset-0 bg-slate-50/80 backdrop-blur-sm z-50 flex items-center justify-center">
        {content}
      </div>
    );
  }

  return <div className="p-8 flex justify-center">{content}</div>;
};

export default Loader;
