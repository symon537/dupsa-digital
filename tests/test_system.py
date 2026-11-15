"""Automated tests for the Malkia Konnect attendance system.  Run:  python manage.py test tests -v 2"""
import json
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.attendance import analytics
from apps.attendance.models import AttendanceEvent, AttendanceRecord
from apps.attendance.services import haversine_m
from apps.audit.models import AuditLog
from apps.branches.models import Branch, OfficeQRCode
from apps.core.models import CompanySettings
from apps.departments.models import Department, Position
from apps.employees.models import EmployeeProfile
from apps.leaves.models import LeaveApplication, LeaveType

PW = "Str0ng!Pass#1"
LAT, LON = Decimal("-6.781000"), Decimal("39.229000")


def make_user(username, role=Role.EMPLOYEE, **kw):
    u = User.objects.create(username=username, role=role, first_name=kw.pop("first_name", username.title()), last_name="Test", email=f"{username}@x.com", **kw)
    u.set_password(PW)
    u.save()
    return u


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cache.clear()
        CompanySettings.get()
        cls.branch = Branch.objects.create(name="Sinza HQ", code="SNZ", latitude=LAT, longitude=LON, radius_m=100)
        cls.other = Branch.objects.create(name="Mbezi", code="MBZ", latitude=Decimal("-6.72"), longitude=Decimal("39.215"), radius_m=100)
        cls.qr = cls.branch.ensure_qr()
        cls.other_qr = cls.other.ensure_qr()
        cls.dept = Department.objects.create(name="Sales", code="SAL")
        cls.admin = make_user("admin", Role.SUPER_ADMIN, is_staff=True, is_superuser=True)
        cls.hr = make_user("hr", Role.HR_MANAGER)
        cls.director = make_user("director", Role.DIRECTOR)
        cls.bm = make_user("bm", Role.BRANCH_MANAGER)
        cls.branch.manager = cls.bm
        cls.branch.save()
        cls.emp_user = make_user("amina", first_name="Amina")
        cls.emp = EmployeeProfile.objects.create(user=cls.emp_user, branch=cls.branch, department=cls.dept, employment_date=date(2025, 1, 1), gender="F")
        cls.emp2_user = make_user("daniel", first_name="Daniel")
        cls.emp2 = EmployeeProfile.objects.create(user=cls.emp2_user, branch=cls.other, employment_date=date(2025, 1, 1), gender="M")
        for n, d, g in [("Annual leave", 28, ""), ("Sick leave", 63, ""), ("Maternity leave", 84, "F")]:
            LeaveType.objects.create(name=n, days_per_year=d, gender_restriction=g)

    def setUp(self):
        cache.clear()

    def login(self, user):
        self.client.logout()
        self.assertTrue(self.client.login(username=user.username, password=PW))

    def clock(self, action, token=None, lat=-6.781, lon=39.229, acc=10):
        body = {"token": token or self.qr.token}
        if lat is not None:
            body.update(latitude=lat, longitude=lon, accuracy=acc)
        return self.client.post(reverse(f"api_clock_{action}"), json.dumps(body), content_type="application/json")


class LoginTests(Base):
    def test_login_page_matches_reference(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertEqual(r.status_code, 200)
        for text in ["Staff Attendance System", "Malkia Konnect Shop", "Username / Email", "Remember me", "Forgot password?", "Sign In", "People", "Productivity", "login-photo"]:
            self.assertContains(r, text)
        self.assertNotContains(r, "collincewarioba@gmail.com")  # developer e-mail must not appear on login

    def test_login_photo_can_be_disabled(self):
        s = CompanySettings.get(); s.login_background_enabled = False; s.save()
        self.assertNotContains(self.client.get(reverse("accounts:login")), "login-photo")

    def test_login_by_username_and_email(self):
        for ident in ("hr", "hr@x.com"):
            self.client.logout()
            r = self.client.post(reverse("accounts:login"), {"username": ident, "password": PW})
            self.assertRedirects(r, reverse("core:home"), fetch_redirect_response=False)

    def test_bad_password_and_lockout(self):
        for _ in range(5):
            r = self.client.post(reverse("accounts:login"), {"username": "hr", "password": "wrong"})
            self.assertContains(r, "Incorrect")
        r = self.client.post(reverse("accounts:login"), {"username": "hr", "password": PW})
        self.assertEqual(r.status_code, 429)
        self.assertTrue(AuditLog.objects.filter(action="auth.locked_out").exists())

    def test_employee_redirected_to_mobile(self):
        self.login(self.emp_user)
        self.assertRedirects(self.client.get(reverse("core:home")), reverse("my:home"))

    def test_login_required(self):
        for name in ["core:home", "employees:list", "my:home", "reports:index"]:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login/", r["Location"])


class PermissionTests(Base):
    def test_employee_blocked_from_management(self):
        self.login(self.emp_user)
        for name in ["employees:list", "attendance:list", "branches:list", "reports:index", "audit:list", "accounts:user_list", "core:settings", "shifts:list"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_role_matrix(self):
        cases = {
            "hr": {"audit:list": 200, "accounts:user_list": 403, "core:settings": 403, "employees:create": 200},
            "director": {"audit:list": 403, "employees:create": 403, "reports:index": 200, "branches:qr_list": 403},
            "bm": {"employees:list": 200, "employees:create": 403, "branches:qr_list": 200, "audit:list": 403},
            "admin": {"audit:list": 200, "accounts:user_list": 200, "core:settings": 200, "core:about": 200},
        }
        users = {"hr": self.hr, "director": self.director, "bm": self.bm, "admin": self.admin}
        for key, expectations in cases.items():
            self.login(users[key])
            for name, code in expectations.items():
                self.assertEqual(self.client.get(reverse(name)).status_code, code, f"{key} -> {name}")

    def test_branch_manager_sees_only_own_branch(self):
        self.login(self.bm)
        html = self.client.get(reverse("employees:list")).content.decode()
        self.assertIn("Amina", html)
        self.assertNotIn("Daniel", html)

    def test_dashboard_api_forbidden_for_employee(self):
        self.login(self.emp_user)
        self.assertEqual(self.client.get(reverse("api_dashboard_charts")).status_code, 403)

    def test_post_only_actions_reject_get(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("branches:toggle", args=[self.branch.pk])).status_code, 405)


class AttendanceFlowTests(Base):
    def test_haversine(self):
        self.assertAlmostEqual(haversine_m(-6.781, 39.229, -6.781, 39.229), 0, places=1)
        self.assertAlmostEqual(haversine_m(-6.781, 39.229, -6.782, 39.229), 111.2, delta=1)

    def test_full_clock_cycle(self):
        self.login(self.emp_user)
        r = self.clock("in")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ok"])
        rec = AttendanceRecord.objects.get(employee=self.emp, date=timezone.localdate())
        self.assertIsNotNone(rec.clock_in)
        self.assertEqual(rec.branch, self.branch)
        r = self.clock("out")
        self.assertEqual(r.status_code, 200, r.content)
        rec.refresh_from_db()
        self.assertIsNotNone(rec.clock_out)
        self.assertTrue(AuditLog.objects.filter(action="attendance.clock_in").exists())
        self.assertGreaterEqual(AttendanceEvent.objects.filter(success=True).count(), 2)

    def test_duplicate_clock_in_blocked(self):
        self.login(self.emp_user)
        self.clock("in")
        r = self.clock("in")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "duplicate_clock_in")
        self.assertEqual(AttendanceRecord.objects.filter(employee=self.emp).count(), 1)

    def test_clock_out_without_clock_in_blocked(self):
        self.login(self.emp_user)
        r = self.clock("out")
        self.assertEqual(r.json()["code"], "no_active_clock_in")

    def test_duplicate_clock_out_blocked(self):
        self.login(self.emp_user)
        self.clock("in"); self.clock("out")
        self.assertEqual(self.clock("out").json()["code"], "duplicate_clock_out")

    def test_outside_radius_rejected_and_logged(self):
        self.login(self.emp_user)
        r = self.clock("in", lat=-6.80, lon=39.25)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "outside_radius")
        ev = AttendanceEvent.objects.filter(success=False).latest("id")
        self.assertTrue(ev.suspicious)
        self.assertGreater(ev.distance_m, 1000)
        self.assertFalse(AttendanceRecord.objects.filter(employee=self.emp).exists())

    def test_missing_gps_rejected_when_enforced(self):
        self.login(self.emp_user)
        self.assertEqual(self.clock("in", lat=None).json()["code"], "permission_required")

    def test_poor_gps_accuracy_rejected(self):
        self.login(self.emp_user)
        self.assertFalse(self.clock("in", acc=5000).json()["ok"])

    def test_gps_enforcement_can_be_disabled(self):
        s = CompanySettings.get(); s.enforce_gps = False; s.save()
        self.login(self.emp_user)
        self.assertTrue(self.clock("in", lat=None).json()["ok"])

    def test_invalid_and_tampered_qr(self):
        self.login(self.emp_user)
        self.assertEqual(self.clock("in", token="garbage").json()["code"], "qr_invalid")
        self.assertEqual(self.clock("in", token=self.qr.token[:-3] + "abc").json()["code"], "qr_invalid")
        self.assertTrue(AttendanceEvent.objects.filter(suspicious=True).exists())

    def test_expired_and_rotated_qr(self):
        self.login(self.emp_user)
        old = self.qr.token
        OfficeQRCode.issue(self.branch, user=self.admin)
        self.assertEqual(self.clock("in", token=old).json()["code"], "qr_revoked")
        new = self.branch.active_qr
        new.expires_at = timezone.now() - timedelta(days=1); new.save()
        self.assertEqual(self.clock("in", token=new.token).json()["code"], "qr_expired")

    def test_other_branch_not_allowed_unless_granted(self):
        self.login(self.emp_user)
        r = self.clock("in", token=self.other_qr.token, lat=-6.72, lon=39.215)
        self.assertEqual(r.status_code, 403)
        self.emp.allowed_branches.add(self.other)
        self.assertTrue(self.clock("in", token=self.other_qr.token, lat=-6.72, lon=39.215).json()["ok"])

    def test_inactive_employee_cannot_clock(self):
        self.emp.status = "terminated"; self.emp.save()
        self.login(self.emp_user)
        self.assertEqual(self.clock("in").json()["code"], "inactive")

    def test_non_employee_has_no_profile(self):
        self.login(self.hr)
        self.assertEqual(self.clock("in").status_code, 403)

    def test_anonymous_api_rejected(self):
        self.assertIn(self.clock("in").status_code, (401, 403))

    def test_today_endpoint_and_qr_check(self):
        self.login(self.emp_user)
        self.clock("in")
        j = self.client.get(reverse("api_today")).json()
        self.assertTrue(j["clocked_in"])
        c = self.client.post(reverse("api_qr_check"), json.dumps({"token": self.qr.token}), content_type="application/json").json()
        self.assertTrue(c["ok"]); self.assertEqual(c["branch"], "Sinza HQ"); self.assertTrue(c["allowed"])

    def test_late_status_calculation(self):
        from datetime import datetime, time
        from apps.attendance.services import CLOCK_IN, process_clock
        d = timezone.localdate()
        while d.weekday() > 4:
            d -= timedelta(days=1)
        late = timezone.make_aware(datetime.combine(d, time(9, 0)))
        res = process_clock(self.emp_user, CLOCK_IN, self.qr.token, -6.781, 39.229, 10, now=late)
        self.assertEqual(res["record"].status, "late")
        self.assertGreater(res["record"].late_minutes, 0)


class PageSmokeTests(Base):
    def test_every_management_page_renders(self):
        self.login(self.admin)
        urls = [reverse(n) for n in [
            "core:home", "core:about", "core:settings", "core:holidays", "employees:list", "employees:create", "branches:list", "branches:create",
            "branches:qr_list", "departments:index", "shifts:list", "shifts:create", "shifts:assign", "attendance:list", "attendance:corrections",
            "leaves:list", "leaves:calendar", "leaves:types", "reports:index", "notifications:list", "notifications:announce", "audit:list",
            "accounts:user_list", "accounts:user_create", "accounts:change_password", "my:home" ]]
        urls += [reverse("employees:detail", args=[self.emp.pk]), reverse("employees:edit", args=[self.emp.pk]), reverse("branches:edit", args=[self.branch.pk]),
                 reverse("branches:qr_poster", args=[self.branch.pk]), reverse("accounts:user_edit", args=[self.hr.pk])]
        for u in urls:
            r = self.client.get(u)
            self.assertIn(r.status_code, (200, 302), u)
            if u != reverse("my:home"):
                self.assertEqual(r.status_code, 200, u)

    def test_mobile_pages_render(self):
        self.login(self.emp_user)
        for n in ["my:home", "my:records", "my:requests", "my:profile", "my:notifications"]:
            r = self.client.get(reverse(n))
            self.assertEqual(r.status_code, 200, n)
        r = self.client.get(reverse("my:scan") + "?t=" + self.qr.token)
        self.assertContains(r, "Confirm attendance")
        self.assertContains(self.client.get(reverse("my:home")), "Scan Office QR Code")

    def test_qr_png_and_poster(self):
        self.login(self.admin)
        r = self.client.get(reverse("branches:qr_image", args=[self.branch.pk]))
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertTrue(r.content.startswith(b"\x89PNG"))
        self.assertContains(self.client.get(reverse("branches:qr_poster", args=[self.branch.pk])), "Scan to Clock In")

    def test_password_reset_pages(self):
        for n in ["accounts:password_reset", "accounts:password_reset_done", "accounts:password_reset_complete"]:
            self.assertEqual(self.client.get(reverse(n)).status_code, 200)

    def test_custom_404(self):
        self.login(self.admin)
        self.assertEqual(self.client.get("/does-not-exist/").status_code, 404)


class DashboardTests(Base):
    def test_stats_are_database_driven(self):
        self.login(self.emp_user); self.clock("in")
        s = analytics.dashboard_stats(self.admin)
        self.assertEqual(s["total_employees"], 2)
        self.assertEqual(s["present"], 1)
        self.assertEqual(s["clocked_in"], 1)
        self.assertEqual(s["branches"], 2)
        j = self.client.get(reverse("api_dashboard_charts"))
        self.assertEqual(j.status_code, 403)  # employee
        self.login(self.hr)
        j = self.client.get(reverse("api_dashboard_charts")).json()
        self.assertEqual(j["stats"]["present"], 1)
        self.assertEqual(len(j["charts"]["trend7"]["labels"]), 7)
        self.assertEqual(sum(1 for b in j["charts"]["by_branch"] if b["present"]), 1)

    def test_dashboard_renders_for_each_staff_role(self):
        for u, title in [(self.admin, "HR Admin Dashboard"), (self.hr, "HR Admin Dashboard"), (self.director, "Director Dashboard"), (self.bm, "Branch Manager Dashboard")]:
            self.login(u)
            self.assertContains(self.client.get(reverse("core:home")), title)


class EmployeeManagementTests(Base):
    def post_employee(self, **extra):
        data = {"first_name": "Grace", "last_name": "Mushi", "gender": "F", "branch": self.branch.pk, "employment_date": "2026-01-05",
                "status": "active", "department": self.dept.pk, "phone": "0712345678"}
        data.update(extra)
        return self.client.post(reverse("employees:create"), data)

    def test_create_employee_generates_number_and_password(self):
        self.login(self.hr)
        r = self.post_employee()
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        p = EmployeeProfile.objects.get(user__first_name="Grace")
        self.assertTrue(p.employee_number)
        self.assertEqual(p.user.role, Role.EMPLOYEE)
        self.assertTrue(p.user.has_usable_password())
        self.assertTrue(AuditLog.objects.filter(action="employee.created").exists())

    def test_invalid_phone_rejected(self):
        self.login(self.hr)
        self.assertEqual(self.post_employee(phone="abc").status_code, 200)

    def test_deactivate_and_reactivate(self):
        self.login(self.hr)
        self.client.post(reverse("employees:toggle", args=[self.emp.pk]))
        self.emp.refresh_from_db(); self.emp.user.refresh_from_db()
        self.assertFalse(self.emp.user.is_active)
        self.client.post(reverse("employees:toggle", args=[self.emp.pk]))
        self.emp.user.refresh_from_db()
        self.assertTrue(self.emp.user.is_active)

    def test_search_and_exports(self):
        self.login(self.hr)
        self.assertContains(self.client.get(reverse("employees:list") + "?q=amina"), "Amina")
        r = self.client.get(reverse("employees:list") + "?export=csv")
        self.assertIn("Employee No", r.content.decode())
        r = self.client.get(reverse("employees:list") + "?export=xlsx")
        from openpyxl import load_workbook
        self.assertEqual(load_workbook(BytesIO(r.content)).active.max_row, 3)


class BranchAndSettingsTests(Base):
    def test_create_branch_issues_qr(self):
        self.login(self.hr)
        r = self.client.post(reverse("branches:create"), {"name": "Kimara", "code": "kmr", "latitude": "-6.779", "longitude": "39.18", "radius_m": 100, "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        b = Branch.objects.get(name="Kimara")
        self.assertEqual(b.code, "KMR")
        self.assertIsNotNone(b.active_qr)

    def test_rotate_qr(self):
        self.login(self.hr)
        old = self.branch.active_qr.token
        self.client.post(reverse("branches:qr_rotate", args=[self.branch.pk]))
        self.assertNotEqual(self.branch.active_qr.token, old)
        self.assertTrue(AuditLog.objects.filter(action="qr.rotated").exists())

    def test_holiday_blocks_absence_count_and_duplicates(self):
        self.login(self.hr)
        self.client.post(reverse("core:holidays"), {"date": "2026-12-09", "name": "Independence Day"})
        r = self.client.post(reverse("core:holidays"), {"date": "2026-12-09", "name": "Again"})
        self.assertContains(r, "already exists")

    def test_department_and_position_creation(self):
        self.login(self.hr)
        self.client.post(reverse("departments:index"), {"d-name": "Stores", "d-code": "sto", "d-is_active": "on", "save_department": "1"})
        self.assertTrue(Department.objects.filter(code="STO").exists())
        d = Department.objects.get(code="STO")
        self.client.post(reverse("departments:index"), {"p-name": "Store Keeper", "p-department": d.pk, "p-is_active": "on", "save_position": "1"})
        self.assertTrue(Position.objects.filter(name="Store Keeper").exists())

    def test_shift_create_and_assign(self):
        self.login(self.hr)
        r = self.client.post(reverse("shifts:create"), {"name": "Early", "start_time": "07:00", "end_time": "16:00", "break_minutes": 60, "grace_minutes": 10, "days": ["0", "1", "2", "3", "4"], "is_active": "on"})
        self.assertEqual(r.status_code, 302, r.context["form"].errors if r.context else "")
        from apps.shifts.models import WorkShift, get_shift_for
        s = WorkShift.objects.get(name="Early")
        r = self.client.post(reverse("shifts:assign"), {"shift": s.pk, "employees": [self.emp.pk], "start_date": timezone.localdate().isoformat()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(get_shift_for(self.emp, timezone.localdate()), s)

    def test_settings_update(self):
        self.login(self.admin)
        r = self.client.post(reverse("core:settings"), {"company_name": "Malkia Konnect", "max_gps_accuracy_m": 80, "overtime_threshold_minutes": 15,
                                                         "qr_validity_days": 30, "working_days_list": ["0", "1", "2"], "enforce_gps": "on", "login_background_enabled": "on"})
        self.assertEqual(r.status_code, 302, r.context["form"].errors if r.context else "")
        self.assertEqual(CompanySettings.get().working_days, "0,1,2")


class LeaveTests(Base):
    def apply(self, type_name="Annual leave", days=3):
        lt = LeaveType.objects.get(name=type_name)
        start = timezone.localdate() + timedelta(days=7)
        while start.weekday() != 0:
            start += timedelta(days=1)
        return self.client.post(reverse("my:requests"), {"l-leave_type": lt.pk, "l-start_date": start.isoformat(), "l-end_date": (start + timedelta(days=days - 1)).isoformat(), "l-reason": "Family", "submit_leave": "1"})

    def test_apply_approve_balance_and_notification(self):
        self.login(self.emp_user)
        r = self.apply()
        self.assertEqual(r.status_code, 302, r.context["leave_form"].errors if r.context else "")
        app = LeaveApplication.objects.get(employee=self.emp)
        self.assertEqual(app.status, "pending")
        self.login(self.hr)
        self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "approve", "note": "ok"})
        app.refresh_from_db()
        self.assertEqual(app.status, "approved")
        self.login(self.emp_user)
        self.assertTrue(self.emp_user.notifications.filter(category="leave").exists())
        self.assertContains(self.client.get(reverse("notifications:list")), "Leave")

    def test_overlap_rejected(self):
        self.login(self.emp_user)
        self.apply(); r = self.apply()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(LeaveApplication.objects.count(), 1)

    def test_gender_restricted_type_blocked(self):
        self.login(self.emp2_user)
        self.apply("Maternity leave")
        self.assertEqual(LeaveApplication.objects.count(), 0)

    def test_reject_and_cancel(self):
        self.login(self.emp_user); self.apply()
        app = LeaveApplication.objects.get()
        self.login(self.bm)
        self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "reject"})
        app.refresh_from_db(); self.assertEqual(app.status, "rejected")
        self.login(self.emp_user); self.apply()
        app2 = LeaveApplication.objects.exclude(pk=app.pk).get()
        self.client.post(reverse("my:leave_cancel", args=[app2.pk]))
        app2.refresh_from_db(); self.assertEqual(app2.status, "cancelled")

    def test_director_cannot_approve(self):
        self.login(self.emp_user); self.apply()
        app = LeaveApplication.objects.get()
        self.login(self.director)
        self.assertEqual(self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "approve"}).status_code, 403)

    def test_approved_leave_prevents_clock_in(self):
        self.login(self.emp_user)
        today = timezone.localdate()
        LeaveApplication.objects.create(employee=self.emp, leave_type=LeaveType.objects.first(), start_date=today, end_date=today, days=1, status="approved")
        self.assertEqual(self.clock("in").json()["code"], "on_leave")

    def test_calendar_shows_approved(self):
        today = timezone.localdate()
        LeaveApplication.objects.create(employee=self.emp, leave_type=LeaveType.objects.first(), start_date=today, end_date=today, days=1, status="approved")
        self.login(self.hr)
        self.assertContains(self.client.get(reverse("leaves:calendar")), "Amina Test")


class CorrectionTests(Base):
    def test_request_and_approve_correction(self):
        self.login(self.emp_user)
        d = timezone.localdate() - timedelta(days=1)
        r = self.client.post(reverse("my:requests"), {"c-date": d.isoformat(), "c-requested_clock_in": "08:00", "c-requested_clock_out": "17:00", "c-reason": "Forgot to scan", "submit_correction": "1"})
        self.assertEqual(r.status_code, 302, r.context["corr_form"].errors if r.context else "")
        from apps.attendance.models import AttendanceCorrection
        c = AttendanceCorrection.objects.get()
        self.login(self.hr)
        self.client.post(reverse("attendance:correction_review", args=[c.pk]), {"decision": "approve"})
        rec = AttendanceRecord.objects.get(employee=self.emp, date=d)
        self.assertTrue(rec.corrected)
        self.assertEqual(timezone.localtime(rec.clock_in).strftime("%H:%M"), "08:00")


class ReportTests(Base):
    def setUp(self):
        super().setUp()
        self.login(self.emp_user); self.clock("in"); self.clock("out")
        self.login(self.hr)

    def q(self, t, **kw):
        p = {"type": t, "date_from": timezone.localdate().isoformat(), "date_to": timezone.localdate().isoformat()}
        p.update(kw)
        return reverse("reports:index") + "?" + "&".join(f"{k}={v}" for k, v in p.items())

    def test_all_report_types_render(self):
        from apps.reports.builders import REPORT_TYPES
        for t, _ in REPORT_TYPES:
            extra = {"employee": self.emp.pk} if t == "employee" else {}
            r = self.client.get(self.q(t, **extra))
            self.assertEqual(r.status_code, 200, t)
            self.assertNotContains(r, "Traceback")
            self.assertTrue(r.context["report"], t)

    def test_exports(self):
        r = self.client.get(self.q("daily") + "&format=csv")
        self.assertIn("Amina", r.content.decode())
        r = self.client.get(self.q("daily") + "&format=xlsx")
        from openpyxl import load_workbook
        self.assertGreaterEqual(load_workbook(BytesIO(r.content)).active.max_row, 2)
        r = self.client.get(self.q("monthly") + "&format=pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertTrue(AuditLog.objects.filter(action="report.exported").exists())

    def test_employee_report_requires_employee(self):
        self.assertContains(self.client.get(self.q("employee")), "Select an employee")

    def test_branch_manager_report_scoped(self):
        self.login(self.bm)
        r = self.client.get(self.q("daily"))
        self.assertContains(r, "Amina"); self.assertNotContains(r, "Daniel")


class NotificationAndUserTests(Base):
    def test_announcement_reaches_employees(self):
        self.login(self.hr)
        self.client.post(reverse("notifications:announce"), {"title": "Staff meeting", "message": "Friday 10am"})
        self.assertTrue(self.emp_user.notifications.filter(title="Staff meeting").exists())
        self.login(self.emp_user)
        self.assertContains(self.client.get(reverse("my:notifications")), "Staff meeting")
        n = self.emp_user.notifications.first()
        self.client.post(reverse("notifications:read", args=[n.pk]))
        n.refresh_from_db(); self.assertTrue(n.is_read)

    def test_employee_cannot_announce(self):
        self.login(self.emp_user)
        self.assertEqual(self.client.get(reverse("notifications:announce")).status_code, 403)

    def test_user_management_and_self_protection(self):
        self.login(self.admin)
        r = self.client.post(reverse("accounts:user_create"), {"username": "newhr", "first_name": "N", "last_name": "H", "email": "n@x.com", "role": "hr_manager", "is_active": "on", "password": "Another#Pass9"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(User.objects.get(username="newhr").role, Role.HR_MANAGER)
        self.client.post(reverse("accounts:user_toggle", args=[self.admin.pk]))
        self.admin.refresh_from_db(); self.assertTrue(self.admin.is_active)

    def test_change_password(self):
        self.login(self.emp_user)
        r = self.client.post(reverse("accounts:change_password"), {"old_password": PW, "new_password1": "BrandNew#Pass77", "new_password2": "BrandNew#Pass77"})
        self.assertEqual(r.status_code, 302)
        self.emp_user.refresh_from_db(); self.assertTrue(self.emp_user.check_password("BrandNew#Pass77"))

    def test_password_reset_email_sent(self):
        from django.core import mail
        self.client.post(reverse("accounts:password_reset"), {"email": "hr@x.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset", mail.outbox[0].body.lower())

    def test_audit_log_records_login(self):
        self.client.post(reverse("accounts:login"), {"username": "hr", "password": PW})
        self.assertTrue(AuditLog.objects.filter(action__startswith="auth.").exists())
