Upload this folder's CONTENTS to your web host:

- index.html
- static/
  - app.css
  - app.js
  - logo.png

Important:
- If you only upload index.html, you'll get NO CSS. You must upload the static/ folder too.
- The app needs backend API routes (/api/*). If your host is "static only", the UI will load but uploads/background removal will NOT work.

If your frontend is on a different domain than the backend (example: frontend=https://rbg.aucto.ch and backend=Railway),
you MUST enable CORS on the Railway backend:

- In Railway → your backend service → Variables, set:
  CORS_ORIGINS=https://rbg.aucto.ch,https://www.rbg.aucto.ch

Then redeploy/restart the Railway service.

