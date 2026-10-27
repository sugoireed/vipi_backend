# vipi_app_backend — Vipi! platform API, admin & ops dashboard

Django 5 + Django REST Framework. Three jobs:

1. **Translation proxy** — the app sends a short WAV, the server checks the user's pass (or free daily quota),
   calls Gemini with the server's key and logs latency/usage. Audio is never stored.
2. **Passes & payments** — day / week / trip passes, device purchase, business seats; M-Pesa STK push
   (Safaricom Daraja) with callback, card/cash confirmation by staff.
3. **Rental fleet** — kiosks (JKIA, Mombasa, partner hotels…), Pods & Talk Cases by serial, reservations,
   hand-over, returns with late fees, deposits, lost kits, device history.

Staff use **/dashboard/** (styled like the app: dark header, rounded sheet, white cards; purple primary,
orange accent) and **/admin/** for raw data.

## Run it on your Mac

```bash
cd vipi_app_backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add GEMINI_API_KEY (and M-Pesa sandbox keys when you have them)
python manage.py migrate
python manage.py seed_demo --activity --admin "you@example.com:choose-a-password"
python manage.py runserver 0.0.0.0:8000
```

- Dashboard: http://localhost:8000/dashboard/ (log in with the admin you just created)
- Admin: http://localhost:8000/admin/
- API health: http://localhost:8000/api/v1/health/

`seed_demo` without `--activity` only creates plans, kiosks and the fleet (safe for production).
With `--activity` it adds 140 fake travellers and 45 days of payments, rentals and translations so the
dashboard has something to show. Start from an empty `db.sqlite3` before going live.

Tests: `python manage.py test tests`

## Connect the Flutter app

The app now has **Settings → Vipi! account**:

- Server URL: Android emulator → `http://10.0.2.2:8000`; real phone on the same Wi-Fi →
  `http://<your Mac's IP>:8000` (System Settings → Wi-Fi → Details). Add that IP to `ALLOWED_HOSTS` in `.env`.
- Create an account / sign in. From then on live translations go through the server: no Gemini key on
  the phone, the pass is checked, and every translation appears on the dashboard.
- Buy a pass: M-Pesa STK push. Without Daraja keys, use **Dev: simulate paid** (only works when `DEBUG=true`).

## API (v1)

| Method | Path | Auth | What |
| --- | --- | --- | --- |
| GET | `/api/v1/health/` | – | Engine + M-Pesa configured? |
| POST | `/api/v1/auth/register/` | – | `{email, password, name, phone, country}` → `{token, me}` |
| POST | `/api/v1/auth/login/` | – | `{email, password}` → `{token, me}` |
| GET/PATCH | `/api/v1/me/` | token | Profile, active pass, free translations left today |
| GET | `/api/v1/plans/` | – | Active plans with KES/USD prices |
| POST | `/api/v1/purchase/` | token | `{plan, method: mpesa\|card, phone}` → payment (STK push sent) |
| GET | `/api/v1/payments/<ref>/` | token | Poll payment status |
| POST | `/api/v1/payments/<ref>/simulate-paid/` | token | DEBUG only |
| POST | `/api/v1/payments/mpesa/callback?k=<secret>` | Daraja | STK result; marks paid + grants pass |
| GET | `/api/v1/passes/` | token | My passes |
| GET | `/api/v1/kiosks/` | – | Pickup points + kits available |
| GET/POST | `/api/v1/rentals/` | token | My rentals / reserve a kit `{kiosk, plan, days, reserved_for, flight, method, phone}` |
| GET | `/api/v1/esim/bundles/` | – | Kenya eSIM data bundles |
| GET/POST | `/api/v1/esim/orders/` | token | My eSIMs / buy a bundle `{bundle, method: mpesa\|card, phone}` |
| GET | `/api/v1/esim/orders/<ref>/` | token | Status, install links (iOS/Android), data left |
| GET | `/api/v1/esim/orders/<ref>/qr.png` | token | QR code to install from another screen |
| POST | `/api/v1/translate/` | token | multipart `audio` (WAV ≤ 30 s), `direction` to_en\|to_sw, `glossary` JSON, `earbuds`, `client` |

Auth header: `Authorization: Token <token>`. No pass and free quota used → **402** with `code: "no_pass"`.

## eSIM data bundles

Bundles are plans of kind `esim_data` with an `EsimBundle` (GB, days, provider package id). When the payment
succeeds, the backend orders the eSIM from the provider (3 attempts; then the order shows as failed on
**Dashboard → Payments** for a retry or refund) and returns one-tap install links
(`esimsetup.apple.com` for iOS 17.4+, `esimsetup.android.com` for Android 10+), the LPA code and a QR image.

- `ESIM_PROVIDER=sandbox` (default): fake eSIMs for testing — nothing installs on a real phone.
- `ESIM_PROVIDER=airalo`: Airalo Partner API. Add `AIRALO_CLIENT_ID/SECRET`, set each bundle's
  `provider_package_id` in admin, and check field names against Airalo's docs once you have partner access.
- Provisioning runs inside the payment callback for now; move it to a background worker as volume grows.

## Business rules (edit in admin or `.env`)

- Free tier: `FREE_DAILY_TRANSLATIONS` (default 10/day). Any active pass = unlimited.
- New passes stack after the current one. Per-day plans multiply by the number of days.
- Kit rentals: deposit held on hand-over, released on time, captured if late/damaged/lost.
  Late days are charged at the plan's daily rate. Returned devices go to *charging* until staff mark them ready.
- Prices (seeded): Day KES 390 · Week 1,950 · Trip 3,250 · Kit 1,040/day or 5,850/week + 5,000 deposit ·
  Pods 12,900 · Business seat 1,950/month.

## Deploy (Laravel Forge / any Ubuntu VPS)

1. Create a site, point it at the repo, Python 3.12+, add a PostgreSQL database.
2. `.env`: `DEBUG=false`, long `SECRET_KEY`, `ALLOWED_HOSTS=api.yourdomain`, `CSRF_TRUSTED_ORIGINS=https://api.yourdomain`,
   `DATABASE_URL=postgres://…`, `GEMINI_API_KEY`, M-Pesa production keys and `MPESA_CALLBACK_URL=https://api.yourdomain/api/v1/payments/mpesa/callback`.
3. Deploy script: `pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput`
4. Daemon: `gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60`; Nginx proxies to it, HTTPS on.
5. `python manage.py seed_demo` (no `--activity`) and `python manage.py createsuperuser`.

## Layout

```
config/            settings (env-driven), urls, api_urls
apps/accounts/     Profile, Organisation (B2B), register/login/me API
apps/billing/      Plan, Payment, Pass, M-Pesa Daraja client, purchase/callback API, seed_demo command
apps/fleet/        Kiosk, Device, Rental (check_out / check_in / mark_lost), DeviceEvent, kiosks/rentals API
apps/translate/    TranslationLog, Gemini engine, quota rules, /translate API
apps/dashboard/    staff dashboard views + templates
static/vipi/       dashboard.css, Chart.js 4.4.1 (vendored), logo
templates/admin/   branded Django admin
tests/             API, payments, rentals and dashboard tests
```
