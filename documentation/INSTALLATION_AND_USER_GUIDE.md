# Malkia Konnect Smart Attendance Management System

Django 5 + MySQL 8 + Bootstrap 5 + Chart.js. Staff clock in/out by scanning a branch QR code on their phone; GPS is verified on the server.
Developer: Warioba Collince.

## 1. Install on Windows 11 (VS Code + WampServer)

1. Install **Python 3.12** (tick *Add python.exe to PATH*), **VS Code**, **Git**, and **WampServer** (start it; the icon must be green).
2. Open phpMyAdmin (`http://localhost/phpmyadmin`) and create a database named `malkia_attendance` with collation `utf8mb4_unicode_ci`.
3. Open this folder in VS Code, then *Terminal > New Terminal* and run:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
   If `mysqlclient` fails to install, delete that line from `requirements.txt`, run `pip install pymysql`, and continue (the project switches to PyMySQL automatically).
4. Edit `.env`: set `SECRET_KEY` to a long random text, `DB_USER=root` and `DB_PASSWORD=` (WampServer default is an empty password).
5. Create the tables and the first administrator:

```bat
python manage.py migrate
python manage.py setup_malkia --admin-username admin --admin-password "ChooseAStrongPassword1"
python manage.py runserver
```
6. Open `http://127.0.0.1:8000/` and sign in.

Try it with sample data: `python manage.py setup_malkia --demo` (demo users `hr`, `director`, `manager`, `amina.juma`... password `Malkia@2026`). **Never use demo data in production.**

## 2. First-time configuration (as admin)
1. **Branches > Add branch**: enter the real name, address and GPS coordinates (Google Maps: right-click the shop entrance, copy latitude/longitude). Set the radius (default 100 m). The example branches (Mbezi Beach, Ubungo, Kimara) are placeholders - create only the real ones.
2. **Departments**, **Positions**, **Shifts & Schedules** (a default 08:00-17:00 shift exists).
3. **Settings**: GPS enforcement, QR validity, working days, login background; **Settings > Public holidays**.
4. **Employees > Add employee**: a username and one-time temporary password are shown after saving.
5. **QR Code Management**: print each branch poster and display it at the entrance. Rotate the code whenever you want to replace it.

## 3. Testing on a phone
Phone cameras and GPS only work on **HTTPS** (or `localhost`). For tests, run `cloudflared tunnel --url http://127.0.0.1:8000` (or ngrok), add the HTTPS address to `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `SITE_URL` in `.env`, and re-print the QR (the QR contains `SITE_URL`).

## 4. Automated tests
`python manage.py test tests -v 2` (63 tests: login/lockout, permissions, QR + GPS rules, duplicates, leave, corrections, reports, exports, dashboards).

## 5. User guide (short)
- **Employee**: open the site on the phone, sign in, tap *Clock In*, allow location, scan the office QR. Same for *Clock Out*. Use *Requests* for leave and missed-scan corrections. If the camera fails, use *paste the code*, or scan the poster with the phone's normal camera and open the link.
- **Branch manager**: dashboard, own-branch staff, leave/correction approval, branch reports, QR poster.
- **HR manager**: everything about employees, shifts, leave, branches, announcements, audit logs and reports.
- **Director**: read-only company-wide dashboard and reports.
- **Super admin**: also users, roles, settings.

## 6. Deployment (Ubuntu VPS, HTTPS)
```bash
sudo apt install python3-venv nginx mysql-server libmysqlclient-dev pkg-config build-essential
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
# .env: DEBUG=False, SECRET_KEY=<random>, ALLOWED_HOSTS=attendance.example.com, SITE_URL=https://attendance.example.com,
#       CSRF_TRUSTED_ORIGINS=https://attendance.example.com, SECURE_SSL=True, DB_* for MySQL
python manage.py migrate && python manage.py collectstatic --noinput
python manage.py setup_malkia --admin-password "..."
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3   # run under systemd
```
Nginx proxies to Gunicorn and serves `/media/`; get the certificate with `sudo certbot --nginx -d attendance.example.com`. Schedule a nightly `mysqldump` of the database and a copy of `media/` to off-server storage.

## 7. Security notes
Passwords hashed (PBKDF2), CSRF on all forms, 5-failure login lockout (15 min), role checks on the server for every view and API, signed + expiring + rotatable QR tokens, server-side GPS distance check, all rejected/suspicious attempts logged, audit log of key actions, HTTPS/HSTS/secure cookies when `SECURE_SSL=True`.
GPS can be spoofed by determined users; the QR + GPS + audit trail make cheating hard and visible, not impossible.

## 8. Layout
`config/` settings and URLs | `apps/` accounts, employees, departments, branches, shifts, attendance, leaves, reports, notifications, audit, core | `templates/` | `static/` | `tests/` | `documentation/`
