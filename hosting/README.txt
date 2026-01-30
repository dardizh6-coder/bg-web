Upload this folder's CONTENTS to your web host:

- index.html
- static/
  - app.css
  - app.js
  - logo.png

Important:
- If you only upload index.html, you'll get NO CSS. You must upload the static/ folder too.
- The app needs backend API routes (/api/*). If your host is "static only", the UI will load but uploads/background removal will NOT work.

If your frontend is on a different domain than the backend (example: frontend on another host, backend at zhaku.eu),
you MUST enable CORS on the backend:

- In your backend env (Railway / server), set:
  CORS_ORIGINS=https://zhaku.eu,https://www.zhaku.eu

Then redeploy/restart the Railway service.

