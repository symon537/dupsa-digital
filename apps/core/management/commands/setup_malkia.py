"""Create the essential data (settings, leave types, default shift, super admin) and optional demo data.

    python manage.py setup_malkia --admin-password "YourStrongPass1"
    python manage.py setup_malkia --demo            # adds example branches/staff/attendance for testing
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.attendance.models import AttendanceRecord
from apps.branches.models import Branch
from apps.core.models import CompanySettings
from apps.departments.models import Department, Position
from apps.employees.models import EmployeeProfile
from apps.leaves.models import LeaveType
from apps.shifts.models import WorkShift

LEAVE_TYPES = [
    ("Annual leave", 28, True, False, ""), ("Sick leave", 63, True, True, ""), ("Maternity leave", 84, True, True, "F"),
    ("Paternity leave", 3, True, False, "M"), ("Compassionate leave", 4, True, False, ""), ("Unpaid leave", 0, False, False, ""),
]
# Example branches only (coordinates are approximate placeholders - HR must set the real GPS values).
DEMO_BRANCHES = [("Sinza (HQ)", "SNZ", -6.7810, 39.2290), ("Mbezi Beach", "MBZ", -6.7200, 39.2150),
                 ("Ubungo", "UBG", -6.7950, 39.2200), ("Kimara", "KMR", -6.7790, 39.1800)]
NAMES = [("Amina", "Juma", "F"), ("Daniel", "Maro", "M"), ("Neema", "Hassan", "F"), ("Peter", "Lameck", "M"),
         ("Grace", "Mushi", "F"), ("Joseph", "Mwakyusa", "M"), ("Rehema", "Salim", "F"), ("Baraka", "Komba", "M")]


class Command(BaseCommand):
    help = "Create essential data and (optionally) demo data."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--admin-password", default=None)
        parser.add_argument("--demo", action="store_true", help="Create example branches, staff and attendance history.")
        parser.add_argument("--demo-password", default="Malkia@2026")

    def handle(self, *args, **o):
        CompanySettings.get()
        for name, days, paid, doc, gender in LEAVE_TYPES:
            LeaveType.objects.get_or_create(name=name, defaults=dict(days_per_year=days, is_paid=paid, requires_document=doc, gender_restriction=gender))
        WorkShift.objects.get_or_create(name="Standard shift", defaults=dict(start_time=time(8, 0), end_time=time(17, 0), break_minutes=60, grace_minutes=15))
        if o["admin_password"]:
            u, created = User.objects.get_or_create(username=o["admin_username"], defaults=dict(role=Role.SUPER_ADMIN, first_name="System", last_name="Admin", is_staff=True, is_superuser=True))
            u.role, u.is_staff, u.is_superuser = Role.SUPER_ADMIN, True, True
            u.set_password(o["admin_password"]); u.save()
            self.stdout.write(self.style.SUCCESS(f"Super administrator '{u.username}' {'created' if created else 'updated'}."))
        elif not User.objects.filter(role=Role.SUPER_ADMIN).exists() and not o["demo"]:
            raise CommandError("No super administrator exists. Re-run with --admin-password.")
        if o["demo"]:
            self.demo(o["demo_password"], o["admin_username"])
        self.stdout.write(self.style.SUCCESS("Setup complete."))

    def demo(self, pw, admin_username):
        if not User.objects.filter(role=Role.SUPER_ADMIN).exists():
            u = User.objects.create(username=admin_username, role=Role.SUPER_ADMIN, first_name="System", last_name="Admin", is_staff=True, is_superuser=True)
            u.set_password(pw); u.save()
        depts = {n: Department.objects.get_or_create(name=n, defaults={"code": c})[0] for n, c in [("Sales", "SAL"), ("Customer Care", "CUS"), ("Stores", "STO")]}
        for n, d in [("Sales Assistant", "Sales"), ("Cashier", "Sales"), ("Store Keeper", "Stores"), ("Customer Care Officer", "Customer Care")]:
            Position.objects.get_or_create(name=n, department=depts[d])
        branches = [Branch.objects.get_or_create(code=c, defaults=dict(name=n, latitude=Decimal(str(la)), longitude=Decimal(str(lo)), radius_m=100, address=f"{n}, Dar es Salaam"))[0] for n, c, la, lo in DEMO_BRANCHES]
        for b in branches:
            b.ensure_qr()

        def mkuser(username, role, first, last):
            u, _ = User.objects.get_or_create(username=username, defaults=dict(role=role, first_name=first, last_name=last, email=f"{username}@example.com"))
            u.set_password(pw); u.save()
            return u

        mkuser("hr", Role.HR_MANAGER, "Halima", "HR")
        mkuser("director", Role.DIRECTOR, "Malkia", "Director")
        bm = mkuser("manager", Role.BRANCH_MANAGER, "Brian", "Manager")
        branches[0].manager = bm; branches[0].save()
        positions = list(Position.objects.all())
        rnd = random.Random(7)
        profiles = []
        for i, (f, l, g) in enumerate(NAMES):
            u = mkuser(f"{f.lower()}.{l.lower()}", Role.EMPLOYEE, f, l)
            branch = branches[i % len(branches)]
            p = getattr(u, "employee_profile", None) or EmployeeProfile.objects.create(
                user=u, gender=g, phone=f"07{rnd.randint(10000000, 99999999)}", branch=branch, department=depts["Sales"],
                position=rnd.choice(positions), employment_date=date(2025, 1, 6))
            profiles.append(p)
        # make the branch manager an employee at Sinza too so he can clock in
        if not hasattr(bm, "employee_profile"):
            EmployeeProfile.objects.create(user=bm, gender="M", branch=branches[0], department=depts["Sales"], employment_date=date(2024, 6, 1))
        # 14 days of history (weekdays/Saturdays)
        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        for back in range(1, 15):
            d = today - timedelta(days=back)
            if d.weekday() == 6:
                continue
            for p in profiles:
                if rnd.random() < 0.1:
                    continue
                late = rnd.random() < 0.18
                ci = datetime.combine(d, time(8, rnd.randint(20, 45) if late else rnd.randint(0, 12)))
                co = datetime.combine(d, time(17, rnd.randint(0, 40)))
                worked = int((co - ci).total_seconds() // 60) - 60
                AttendanceRecord.objects.get_or_create(employee=p, date=d, defaults=dict(
                    branch=p.branch, shift_name="Standard shift", clock_in=timezone.make_aware(ci, tz), clock_out=timezone.make_aware(co, tz),
                    status="late" if late else "present", late_minutes=max(0, ci.minute - 15) if late else 0, break_minutes=60, worked_minutes=worked))
        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Demo users (password: {pw}): hr, director, manager, amina.juma, daniel.maro ..."))
