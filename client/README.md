# Find My Peace – Client

React 19 + Vite + Tailwind CSS v4 frontend for the Find My Peace counseling platform.

## Scripts

```bash
npm run dev      # start dev server on http://localhost:5173 (proxies /api and /socket.io to :5000)
npm run build    # production build into dist/
npm run preview  # preview the production build
npm run lint     # oxlint
```

## Environment

Copy `.env.example` to `.env`:

| Variable | Purpose |
| --- | --- |
| `VITE_RAZORPAY_KEY_ID` | Razorpay **public** key id (never the secret) |
| `VITE_API_BASE_URL` | API origin, e.g. `https://api.example.com`. Leave empty in dev to use the Vite proxy. |
| `VITE_SOCKET_URL` | Socket.io origin (defaults to `VITE_API_BASE_URL`) |

## Structure

- `src/pages` – route-level pages (home, booking, payment, confirmation, admin)
- `src/components/common` – navbar, footer, logo, loader
- `src/components/admin` – dashboard panels
- `src/services` – axios instance (`api.js`) and shared socket (`socket.js`)
- `src/config/site.js` – counselor details, pricing copy, contact info (edit here, not in pages)
