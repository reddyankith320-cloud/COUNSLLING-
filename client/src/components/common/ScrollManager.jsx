import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * SPA navigations don't scroll like full page loads do. This restores the
 * expected behaviour: jump to the top on a new route, or to the `#hash`
 * target once the page has rendered.
 */
const ScrollManager = () => {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (hash) {
      const id = hash.slice(1);
      // Wait a frame so the target section exists after a route change
      const raf = requestAnimationFrame(() => {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      return () => cancelAnimationFrame(raf);
    }
    window.scrollTo(0, 0);
  }, [pathname, hash]);

  return null;
};

export default ScrollManager;
