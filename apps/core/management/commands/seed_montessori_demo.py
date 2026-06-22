"""Idempotent seed for a large 'Montessori Demo School' presentation demo.

Differs from ``seed_demo`` (Vidya Bharati) in scale and structure:
  * 10 classes (Grade 1-10), exactly 2 sections each  -> 20 sections
  * Core 6 subjects for every class
  * 40 students per section                            -> 800 students
  * 100 teachers, specialised by subject
  * Every (section, subject) assigned to a teacher, and a weekly timetable
    built so **no teacher is ever double-booked** at the same day+period.

The rich, generic data (attendance, tests/marks, fees, online tests,
notifications) is reused from ``seed_demo`` so every app screen looks
populated. Report cards / announcements / the demo parent are seeded here
against this school's Grade naming + Core-6 subjects.

Usage:
    uv run python manage.py seed_montessori_demo          # create if missing
    uv run python manage.py seed_montessori_demo --reset  # wipe + recreate

Logins (all on this demo school):
    admin   : +919900000000 / demo1234
    teacher : +919900000001 / demo1234
    parent  : +919900012345 / skooly123
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (
    Class,
    DayOfWeek,
    Section,
    StudentEnrollment,
    Subject,
    SubjectClassMapping,
    TeacherAssignment,
    TimetablePeriod,
)
from apps.accounts.models import Role, User
from apps.communications.models import Announcement, AnnouncementCategory
from apps.core.context import use_school
from apps.core.management.commands.seed_demo import (
    BLOOD_GROUPS,
    BOY_FIRST_NAMES,
    CITIES,
    GIRL_FIRST_NAMES,
    STREETS,
    SURNAMES,
    TEACHER_QUALS,
)
from apps.core.management.commands.seed_demo import Command as DemoCommand
from apps.exams.models import (
    ExamName,
    ReportCard,
    ReportCardTerm,
    Test,
    TestMode,
    TestScore,
    TestType,
)
from apps.people.models import (
    Gender,
    Parent,
    ParentStudent,
    Relation,
    Student,
    StudentStatus,
    Teacher,
)
from apps.schools.models import Board, School

SCHOOL_NAME = "Montessori Demo School"
SCHOOL_PHONE = "+919900000000"
ADMIN_PASSWORD = "demo1234"

TEACHER_PHONE = "+919900000001"
TEACHER_PASSWORD = "demo1234"

PARENT_PHONE = "+919900012345"
PARENT_NAME = "Suresh Reddy"
PARENT_PASSWORD = "skooly123"

# Core 6 subjects (AP State Board) — taught in every class.
SUBJECTS = [
    ("Telugu", "TEL"),
    ("Hindi", "HIN"),
    ("English", "ENG"),
    ("Mathematics", "MAT"),
    ("Science", "SCI"),
    ("Social Studies", "SOC"),
]

# Grade 1..10, display_order matches the grade number.
CLASS_LEVELS = [(f"Grade {i}", i) for i in range(1, 11)]
SECTION_NAMES = ["A", "B"]

STUDENTS_PER_SECTION = 40
TEACHER_COUNT = 100

# Weekly period slots. Grades 6-10 get 8 periods Mon-Fri; 1-5 get 7. Saturday
# is a half day (first 5). Lunch/recess are the time gaps between periods.
WEEKDAY_HIGH = [
    (1, time(8, 0), time(8, 45)),
    (2, time(8, 45), time(9, 30)),
    (3, time(9, 30), time(10, 15)),
    (4, time(10, 30), time(11, 15)),
    (5, time(11, 15), time(12, 0)),
    (6, time(12, 45), time(13, 30)),
    (7, time(13, 30), time(14, 15)),
    (8, time(14, 15), time(15, 0)),
]
WEEKDAY_LOW = [
    (1, time(8, 30), time(9, 15)),
    (2, time(9, 15), time(10, 0)),
    (3, time(10, 0), time(10, 45)),
    (4, time(11, 0), time(11, 45)),
    (5, time(11, 45), time(12, 30)),
    (6, time(13, 0), time(13, 45)),
    (7, time(13, 45), time(14, 30)),
]
WEEKDAYS = [DayOfWeek.MON, DayOfWeek.TUE, DayOfWeek.WED, DayOfWeek.THU, DayOfWeek.FRI]

# "Common tests" the strength radar reads: exams every section of a grade
# writes under the same name. Each entry is (exam label, is_series,
# [(test name, max marks, date), ...]). The radar groups by (exam, name,
# subject) and averages each student's percentile across all of them.
COMMON_EXAMS: list[tuple[str, bool, list[tuple[str, int, date]]]] = [
    ("Quarterly Exam", False, [("Quarterly Exam", 100, date(2025, 8, 28))]),
    ("Half-Yearly Exam", False, [("Half-Yearly Exam", 100, date(2025, 11, 21))]),
    ("Weekly Test", True, [
        ("Weekly Test 1", 25, date(2026, 1, 16)),
        ("Weekly Test 2", 25, date(2026, 2, 13)),
    ]),
]

# Hand-picked subject aptitude (target %) for the demo parent's children, so
# their radar tells a clear story (STEM-leaning Aarav, language-leaning Ananya).
# Every other student gets a randomised but self-consistent shape.
CHILD_PROFILES: dict[str, dict[str, int]] = {
    "Aarav": {
        "Mathematics": 92, "Science": 88, "Social Studies": 71,
        "English": 63, "Hindi": 57, "Telugu": 74,
    },
    "Ananya": {
        "Mathematics": 61, "Science": 73, "Social Studies": 83,
        "English": 93, "Hindi": 86, "Telugu": 90,
    },
}


class Command(BaseCommand):
    help = "Seed a large Montessori demo school (no teacher timetable clashes)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--reset", action="store_true", help="Wipe the demo school first.")
        parser.add_argument("--seed", type=int, default=7, help="Random seed for reproducibility.")
        parser.add_argument(
            "--name", default=SCHOOL_NAME,
            help=f'School name to brand the demo (default: "{SCHOOL_NAME}").',
        )
        parser.add_argument(
            "--logo", default="",
            help="Optional logo image URL to set on the school (else set it later in the admin portal).",
        )
        parser.add_argument(
            "--exams-only", action="store_true",
            help="Backfill exam-named common tests onto the existing demo (feeds the "
                 "strength radar) without recreating the school. Idempotent.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        rng = random.Random(opts["seed"])

        if opts["exams_only"]:
            self._backfill_common_exams(rng)
            return

        existing = User.objects.filter(phone=SCHOOL_PHONE).first()
        if existing and not opts["reset"]:
            self.stdout.write(self.style.WARNING(
                f"Montessori demo already seeded (admin {SCHOOL_PHONE}). Use --reset to recreate."
            ))
            return

        # Reused rich-data helpers live on the seed_demo Command; route their
        # (rare) stdout through ours.
        demo = DemoCommand()
        demo.stdout = self.stdout
        demo.style = self.style

        with transaction.atomic():
            if opts["reset"] and existing:
                self.stdout.write("Wiping existing Montessori demo school…")
                school = existing.school
                if school:
                    School.all_tenants.filter(id=school.id).delete()
                existing.delete()

            school = self._seed_school(name=opts["name"], logo_url=opts["logo"])
            self.stdout.write(self.style.SUCCESS(f"  ✓ school: {school.name} (id={school.id})"))
            self.stdout.write(self.style.SUCCESS(f"  ✓ admin login: {SCHOOL_PHONE} / {ADMIN_PASSWORD}"))

            with use_school(school):
                year = school.current_academic_year
                assert year is not None

                subjects = self._seed_subjects(school)
                self.stdout.write(self.style.SUCCESS(f"  ✓ subjects: {len(subjects)} (Core 6)"))

                teachers, pool_by_subject = self._seed_teachers(rng, school, subjects)
                self.stdout.write(self.style.SUCCESS(f"  ✓ teachers: {len(teachers)}"))

                sections = self._seed_classes_sections(school, year, subjects)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ classes: {len(CLASS_LEVELS)}  ({len(sections)} sections)"
                ))

                self._seed_assignments(school, year, sections, subjects, pool_by_subject)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ assignments: {TeacherAssignment.objects.filter(school=school).count()}"
                ))

                self._seed_teacher_login(school, teachers)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ teacher login: {TEACHER_PHONE} / {TEACHER_PASSWORD}"
                ))

                total = 0
                for section in sections:
                    self._seed_section_students(rng, school, year, section, STUDENTS_PER_SECTION)
                    total += STUDENTS_PER_SECTION
                self.stdout.write(self.style.SUCCESS(f"  ✓ students: {total}"))

                tt_count, max_load = self._seed_timetable_no_clash(school, sections, subjects)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ timetable periods: {tt_count} (no teacher clashes; "
                    f"max teacher load {max_load} periods/week)"
                ))

                # --- reused generic rich data (covers last ~2 months) -----------
                marks_total = demo._seed_attendance(rng, school)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ attendance: {marks_total:,} marks across ~60 school days (all sections)"
                ))

                tests_total, scores_total = demo._seed_tests(rng, school, teachers)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ tests: {tests_total} published with {scores_total:,} scores"
                ))

                fee_stats = demo._seed_fees(rng, school)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ fees: {fee_stats['structures']} structures, "
                    f"{fee_stats['student_fees']:,} student fees, {fee_stats['payments']:,} payments"
                ))

                # --- demo parent + report cards + announcements (this school) ---
                children = self._seed_parent(school)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ parent login: {PARENT_PHONE} / {PARENT_PASSWORD} → "
                    f"{', '.join(c.full_name for c in children)}"
                ))

                ce_tests, ce_scores = self._seed_common_exams(
                    rng, school, year, sections, subjects, children
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ common exams: {ce_tests} published across all sections "
                    f"({ce_scores:,} scores) — feeds the strength radar"
                ))

                rc_count = self._seed_report_cards(school, children, year)
                self.stdout.write(self.style.SUCCESS(f"  ✓ report cards: {rc_count} published"))

                ann_count = self._seed_announcements(school, sections)
                self.stdout.write(self.style.SUCCESS(f"  ✓ announcements: {ann_count}"))

                ot_count, sub_count = DemoCommand._seed_online_tests(school, children, teachers)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ online tests: {ot_count} published, {sub_count} pre-submitted"
                ))

        self.stdout.write(self.style.SUCCESS("Montessori demo seed complete."))

    # --- structure ------------------------------------------------------------

    def _seed_school(self, *, name: str, logo_url: str) -> School:
        from apps.accounts import services as auth_services

        _user, school, _tokens = auth_services.signup_school(
            school_name=name,
            board=Board.AP_STATE,
            address="Alampur, Jogulamba Gadwal, Telangana 509152",
            academic_year_label="2025-26",
            academic_year_start=date(2025, 6, 1),
            academic_year_end=date(2026, 4, 30),
            admin_first_name="Padmaja",
            admin_last_name="Rao",
            admin_phone=SCHOOL_PHONE,
            admin_email="principal@demo.school",
            admin_password=ADMIN_PASSWORD,
        )
        school.whatsapp_number = "+918000000001"
        school.primary_color = "#7c3aed"
        fields = ["whatsapp_number", "primary_color"]
        if logo_url:
            school.logo_url = logo_url
            fields.append("logo_url")
        school.save(update_fields=fields)
        return school

    def _seed_subjects(self, school: School) -> list[Subject]:
        subjects = []
        for name, code in SUBJECTS:
            subj, _ = Subject.objects.get_or_create(
                school=school, name=name, defaults={"code": code}
            )
            subjects.append(subj)
        return subjects

    def _seed_teachers(
        self, rng: random.Random, school: School, subjects: list[Subject]
    ) -> tuple[list[Teacher], dict[int, list[Teacher]]]:
        """Create TEACHER_COUNT teachers, each specialised in one subject
        (round-robin), and return both the flat list and the per-subject pool."""
        teachers: list[Teacher] = []
        pool: dict[int, list[Teacher]] = {s.id: [] for s in subjects}
        for i in range(TEACHER_COUNT):
            is_female = i % 2 == 0
            first = rng.choice(GIRL_FIRST_NAMES if is_female else BOY_FIRST_NAMES)
            last = rng.choice(SURNAMES)
            phone = f"+9196{rng.randint(10000000, 99999999):08d}"
            teacher = Teacher.objects.create(
                school=school,
                first_name=first,
                last_name=last,
                phone=phone,
                email=f"{first.lower()}.{last.lower()}{i}@montessoridemo.school",
                qualification=rng.choice(TEACHER_QUALS),
                joining_date=date(2018 + (i % 7), rng.randint(1, 12), rng.randint(1, 28)),
                status="active",
                photo_url=f"https://api.dicebear.com/9.x/initials/svg?seed={first}+{last}",
            )
            teachers.append(teacher)
            pool[subjects[i % len(subjects)].id].append(teacher)
        return teachers, pool

    def _seed_teacher_login(self, school: School, teachers: list[Teacher]) -> None:
        teacher = teachers[0]
        user, _ = User.objects.get_or_create(
            phone=TEACHER_PHONE,
            defaults={
                "school": school,
                "role": Role.TEACHER,
                "first_name": teacher.first_name,
                "last_name": teacher.last_name,
                "email": teacher.email,
            },
        )
        user.set_password(TEACHER_PASSWORD)
        user.save()
        teacher.user = user
        teacher.save(update_fields=["user"])

    def _seed_classes_sections(
        self, school: School, year: Any, subjects: list[Subject]
    ) -> list[Section]:
        sections: list[Section] = []
        for cls_name, order in CLASS_LEVELS:
            cls = Class.objects.create(
                school=school, academic_year=year, name=cls_name, display_order=order
            )
            # Every class gets all Core-6 subjects.
            for subj in subjects:
                SubjectClassMapping.objects.create(school=school, subject=subj, class_obj=cls)
            for sec_name in SECTION_NAMES:
                section = Section.objects.create(
                    school=school, class_obj=cls, name=sec_name,
                    room_number=f"{order}{sec_name}", capacity=STUDENTS_PER_SECTION,
                )
                sections.append(section)
        return sections

    def _seed_assignments(
        self,
        school: School,
        year: Any,
        sections: list[Section],
        subjects: list[Subject],
        pool_by_subject: dict[int, list[Teacher]],
    ) -> None:
        """Assign every (section, subject) to a teacher from that subject's pool,
        picking the least-loaded teacher so the load stays balanced. Each
        section's 6 subjects therefore map to 6 distinct teachers."""
        load: dict[int, int] = defaultdict(int)
        for section in sections:
            first_teacher: Teacher | None = None
            for subj in subjects:
                cand = min(pool_by_subject[subj.id], key=lambda t: load[t.id])
                TeacherAssignment.objects.get_or_create(
                    school=school, teacher=cand, subject=subj,
                    section=section, academic_year=year,
                )
                load[cand.id] += 1
                if first_teacher is None:
                    first_teacher = cand
            # Class teacher = the section's first-subject teacher.
            section.class_teacher = first_teacher
            section.save(update_fields=["class_teacher"])

    def _seed_timetable_no_clash(
        self, school: School, sections: list[Section], subjects: list[Subject]
    ) -> tuple[int, int]:
        """Build each section's weekly timetable, guaranteeing that no teacher is
        booked in two sections at the same (day, period). Greedy: at each slot,
        pick the least-scheduled subject whose teacher is currently free."""
        # (day, period_number) -> set of teacher ids already booked there.
        busy: dict[tuple[int, int], set[int]] = defaultdict(set)
        rows: list[TimetablePeriod] = []
        teacher_load: dict[int, int] = defaultdict(int)

        for section in sections:
            order = section.class_obj.display_order
            weekday_slots = WEEKDAY_HIGH if order >= 6 else WEEKDAY_LOW
            sat_slots = weekday_slots[:5]
            # (subject, teacher) pairs for this section — distinct teachers.
            pairs = [
                (a.subject, a.teacher)
                for a in TeacherAssignment.objects.filter(section=section)
                .select_related("subject", "teacher")
                .order_by("subject_id")
            ]
            subj_count: dict[int, int] = {s.id: 0 for s, _ in pairs}
            last_subject_id: int | None = None

            day_plan = [(day, weekday_slots) for day in WEEKDAYS]
            day_plan.append((DayOfWeek.SAT, sat_slots))

            for day, slots in day_plan:
                for pnum, start, end in slots:
                    key = (int(day), pnum)
                    free = [(s, t) for (s, t) in pairs if t is None or t.id not in busy[key]]
                    if not free:
                        # No teacher available — leave it a free period.
                        rows.append(TimetablePeriod(
                            school=school, section=section, day_of_week=day,
                            period_number=pnum, subject=None, teacher=None,
                            start_time=start, end_time=end,
                        ))
                        continue
                    # Prefer least-scheduled subject; break ties avoiding a repeat.
                    free.sort(key=lambda st: (subj_count[st[0].id], st[0].id == last_subject_id))
                    subj, teacher = free[0]
                    if teacher is not None:
                        busy[key].add(teacher.id)
                        teacher_load[teacher.id] += 1
                    subj_count[subj.id] += 1
                    last_subject_id = subj.id
                    rows.append(TimetablePeriod(
                        school=school, section=section, day_of_week=day,
                        period_number=pnum, subject=subj, teacher=teacher,
                        start_time=start, end_time=end,
                    ))

        # Hard guarantee: assert no teacher is double-booked at any slot.
        by_slot: dict[tuple[int, int], list[int]] = defaultdict(list)
        for r in rows:
            if r.teacher_id is not None:
                by_slot[(r.day_of_week, r.period_number)].append(r.teacher_id)
        clashes = {k: v for k, v in by_slot.items() if len(v) != len(set(v))}
        assert not clashes, f"Teacher double-booked at slots: {list(clashes)[:5]}"

        TimetablePeriod.objects.bulk_create(rows, batch_size=2000)
        max_load = max(teacher_load.values()) if teacher_load else 0
        return len(rows), max_load

    def _seed_section_students(
        self, rng: random.Random, school: School, year: Any, section: Section, count: int
    ) -> None:
        order = section.class_obj.display_order
        base_age = order + 5
        for i in range(count):
            is_female = rng.random() < 0.48
            first = rng.choice(GIRL_FIRST_NAMES if is_female else BOY_FIRST_NAMES)
            last = rng.choice(SURNAMES)
            father_first = rng.choice(BOY_FIRST_NAMES)
            mother_first = rng.choice(GIRL_FIRST_NAMES)

            today = date(2026, 5, 17)
            dob = date(today.year - base_age - rng.randint(0, 1), rng.randint(1, 12), rng.randint(1, 28))
            admission_year = today.year - (order - 1)
            adm = f"MD{admission_year}{order:02d}{section.id:02d}{i + 1:03d}"

            student = Student.objects.create(
                school=school,
                admission_number=adm,
                first_name=first,
                last_name=last,
                dob=dob,
                gender=Gender.FEMALE if is_female else Gender.MALE,
                blood_group=rng.choice(BLOOD_GROUPS),
                address=(
                    f"{rng.randint(1, 99)}-{rng.randint(1, 99)}, {rng.choice(STREETS)}, "
                    f"{rng.choice(CITIES)}, TS"
                ),
                photo_url=f"https://api.dicebear.com/9.x/avataaars/svg?seed={first}+{last}+{i}",
                admission_date=date(admission_year, 6, rng.randint(1, 20)),
                status=StudentStatus.ACTIVE,
                parent1_name=f"{father_first} {last}",
                parent1_phone=f"+9195{rng.randint(10000000, 99999999):08d}",
                parent1_relation=Relation.FATHER,
                parent1_whatsapp=True,
                parent2_name=f"{mother_first} {last}",
                parent2_phone=f"+9194{rng.randint(10000000, 99999999):08d}",
                parent2_relation=Relation.MOTHER,
                parent2_whatsapp=rng.random() < 0.4,
                primary_whatsapp_phone=f"+9195{rng.randint(10000000, 99999999):08d}",
            )
            StudentEnrollment.objects.create(
                school=school, student=student, section=section, academic_year=year,
                roll_number=f"{i + 1:02d}", enrollment_date=date(admission_year, 6, 15),
                status="active",
            )

    # --- common exams (strength radar) ----------------------------------------

    def _backfill_common_exams(self, rng: random.Random) -> None:
        """Add exam-named common tests to an already-seeded demo school, without
        recreating it — used to light up the strength radar on an existing
        (e.g. prod) demo. No-op if the exams are already present."""
        existing = User.objects.filter(phone=SCHOOL_PHONE).first()
        school = existing.school if existing else None
        if school is None:
            self.stdout.write(self.style.ERROR(
                "No Montessori demo school found — run the full seed first."
            ))
            return
        with transaction.atomic(), use_school(school):
            year = school.current_academic_year
            sections = list(
                Section.objects.filter(school=school, class_obj__academic_year=year)
                .select_related("class_obj")
            )
            subjects = list(Subject.objects.filter(school=school))
            children = list(
                Student.objects.filter(parent_links__parent__phone=PARENT_PHONE).distinct()
            )
            tests, scores = self._seed_common_exams(rng, school, year, sections, subjects, children)
            if tests == 0:
                self.stdout.write(self.style.WARNING(
                    "Common exams already present — nothing to backfill."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ common exams backfilled: {tests} tests, {scores:,} scores"
                ))

    def _seed_common_exams(
        self,
        rng: random.Random,
        school: School,
        year: Any,
        sections: list[Section],
        subjects: list[Subject],
        children: list[Student],
    ) -> tuple[int, int]:
        """Publish, in every section of every grade, the same set of exams under
        a shared exam name — the "common tests" the strength radar reads. Each
        student's marks are driven by a stable per-subject aptitude (hand-picked
        for the demo children, randomised for everyone else) so percentiles
        spread into a meaningful radar. Idempotent: a no-op once the common
        tests exist, and coexists with any exam names the admin already made."""
        # Key idempotency on the real signal — the common tests themselves — not
        # on ExamName rows (the admin may have created some by hand via the UI).
        if Test.objects.filter(
            school=school, exam_name__isnull=False, published_at__isnull=False
        ).exists():
            return 0, 0

        # Reuse an existing exam name (case-insensitive) or create one, so we
        # never collide with an admin-defined label.
        by_lower = {e.label.lower(): e for e in ExamName.objects.filter(school=school)}
        next_order = max((e.display_order for e in by_lower.values()), default=0)
        exam_name_by_label: dict[str, ExamName] = {}
        for label, is_series, _insts in COMMON_EXAMS:
            existing = by_lower.get(label.lower())
            if existing is None:
                next_order += 1
                existing = ExamName.objects.create(
                    school=school, label=label, is_series=is_series, display_order=next_order
                )
            exam_name_by_label[label] = existing
        child_profiles = {
            c.id: CHILD_PROFILES[c.first_name]
            for c in children
            if c.first_name in CHILD_PROFILES
        }
        target_cache: dict[tuple[int, int], int] = {}
        tests_made = scores_made = 0

        for section in sections:
            enrolls = list(
                StudentEnrollment.objects.filter(section=section, status="active")
                .select_related("student")
            )
            teacher_by_subject = {
                a.subject_id: a.teacher
                for a in TeacherAssignment.objects.filter(section=section)
            }
            for subj in subjects:
                teacher = teacher_by_subject.get(subj.id)
                for label, _is_series, instances in COMMON_EXAMS:
                    for tname, max_marks, tdate in instances:
                        test = Test.objects.create(
                            school=school, section=section, subject=subj,
                            name=tname, test_type=TestType.OTHER, mode=TestMode.OFFLINE,
                            test_date=tdate, max_marks=max_marks, duration_min=0,
                            created_by=teacher, exam_name=exam_name_by_label[label],
                            published_at=timezone.now(),
                        )
                        tests_made += 1
                        batch: list[TestScore] = []
                        for enr in enrolls:
                            student = enr.student
                            if rng.random() < 0.03:  # the odd absentee
                                batch.append(TestScore(
                                    school=school, test=test, student=student,
                                    marks_obtained=None, is_absent=True,
                                ))
                                continue
                            target = self._subject_target(
                                rng, target_cache, student, subj, child_profiles
                            )
                            pct = min(99, max(12, target + rng.randint(-7, 7)))
                            batch.append(TestScore(
                                school=school, test=test, student=student,
                                marks_obtained=round(max_marks * pct / 100),
                                is_absent=False,
                            ))
                        TestScore.objects.bulk_create(batch, batch_size=2000)
                        scores_made += len(batch)
        return tests_made, scores_made

    @staticmethod
    def _subject_target(
        rng: random.Random,
        cache: dict[tuple[int, int], int],
        student: Student,
        subject: Subject,
        child_profiles: dict[int, dict[str, int]],
    ) -> int:
        """A student's stable target % in a subject. Demo children follow their
        hand-picked profile; everyone else gets a latent ability (cached under
        key 0) plus a fixed per-subject offset, so their standing is consistent
        across the term's exams while still varying by subject."""
        key = (student.id, subject.id)
        if key in cache:
            return cache[key]
        profile = child_profiles.get(student.id)
        if profile and subject.name in profile:
            value = profile[subject.name]
        else:
            ability_key = (student.id, 0)
            if ability_key not in cache:
                cache[ability_key] = rng.randint(45, 90)
            value = min(96, max(20, cache[ability_key] + rng.randint(-12, 12)))
        cache[key] = value
        return value

    # --- demo parent / report cards / announcements ---------------------------

    def _seed_parent(self, school: School) -> list[Student]:
        """Adopt one Grade 8 + one Grade 5 student as the demo parent's children."""

        def adopt(grade_name: str, first_name: str) -> Student | None:
            enr = (
                StudentEnrollment.objects.filter(
                    section__class_obj__name=grade_name, status="active"
                )
                .select_related("student")
                .order_by("id")
                .first()
            )
            if enr is None:
                return None
            st = enr.student
            st.first_name = first_name
            st.last_name = "Reddy"
            st.parent1_name = PARENT_NAME
            st.parent1_phone = PARENT_PHONE
            st.parent1_relation = Relation.FATHER
            st.parent1_whatsapp = True
            st.primary_whatsapp_phone = PARENT_PHONE
            st.save(update_fields=[
                "first_name", "last_name", "parent1_name", "parent1_phone",
                "parent1_relation", "parent1_whatsapp", "primary_whatsapp_phone", "updated_at",
            ])
            return st

        children = [c for c in (adopt("Grade 8", "Aarav"), adopt("Grade 5", "Ananya")) if c]

        first, _, last = PARENT_NAME.partition(" ")
        user = User(
            phone=PARENT_PHONE, role=Role.PARENT, school=school,
            first_name=first, last_name=last,
            email="suresh.reddy@example.com", is_active=True,
        )
        user.set_password(PARENT_PASSWORD)
        user.save()
        parent = Parent.objects.create(
            school=school, user=user, name=PARENT_NAME,
            phone=PARENT_PHONE, email="suresh.reddy@example.com",
        )
        for child in children:
            ParentStudent.objects.create(
                school=school, parent=parent, student=child, relation=Relation.FATHER
            )
            DemoCommand._seed_notifications(school, child)
        return children

    @staticmethod
    def _seed_report_cards(school: School, children: list[Student], year: Any) -> int:
        """Term 1 + Term 2 report cards (published) using Core-6 subjects."""

        def grade(pct: float) -> str:
            for cutoff, g in [(91, "A1"), (81, "A2"), (71, "B1"), (61, "B2"),
                              (51, "C1"), (41, "C2"), (33, "D")]:
                if pct >= cutoff:
                    return g
            return "E"

        # [term1, term2] marks per Core-6 subject; distinct per child.
        subjects_upper = [
            ("Mathematics", [68, 74]), ("Science", [72, 76]),
            ("Social Studies", [78, 82]), ("English", [81, 85]),
            ("Hindi", [65, 70]), ("Telugu", [79, 83]),
        ]
        subjects_lower = [
            ("Mathematics", [88, 85]), ("Science", [82, 79]),
            ("Social Studies", [76, 80]), ("English", [90, 92]),
            ("Hindi", [84, 88]), ("Telugu", [86, 90]),
        ]
        term_meta = [
            (ReportCardTerm.TERM_1, "Term 1", date(2025, 10, 31)),
            (ReportCardTerm.TERM_2, "Term 2", date(2026, 2, 28)),
        ]
        remarks = [
            "A focused student with steady improvement this term. Keep it up.",
            "Consistent application and active class participation. Encouraged to aim higher.",
        ]
        principal_remark = "Maintains a positive attitude and sets a good example for peers."

        rows: list[ReportCard] = []
        for child in children:
            enroll = child.enrollments.filter(status="active").first()
            section = enroll.section if enroll else None
            total_students = (
                StudentEnrollment.objects.filter(section=section, status="active").count()
                if section else 40
            )
            is_upper = bool(enroll and enroll.section.class_obj.display_order >= 6)
            subjects = subjects_upper if is_upper else subjects_lower

            for term_idx, (term_value, term_label, issue_date) in enumerate(term_meta):
                subj_payload = []
                total_marks = 0
                for name, pair in subjects:
                    m = pair[term_idx]
                    subj_payload.append({"name": name, "maxMarks": 100, "marks": m, "grade": grade(m)})
                    total_marks += m
                overall_pct = round(total_marks / len(subjects))
                rows.append(ReportCard(
                    school=school, student=child, academic_year=year, term=term_value,
                    published_at=timezone.now(),
                    data_snapshot={
                        "term": term_label,
                        "academicYear": year.label,
                        "issueDate": issue_date.isoformat(),
                        "subjects": subj_payload,
                        "attendancePct": 92 if term_idx == 1 else 87,
                        "teacherRemark": remarks[term_idx],
                        "principalRemark": principal_remark if term_idx == 1 else None,
                        "overallGrade": grade(overall_pct),
                        "overallPct": overall_pct,
                        "rank": 9 if term_idx == 1 else 7,
                        "totalStudents": total_students,
                    },
                ))
        ReportCard.objects.bulk_create(rows)
        return len(rows)

    @staticmethod
    def _seed_announcements(school: School, sections: list[Section]) -> int:
        grade_8 = next((s for s in sections if s.class_obj.name == "Grade 8"), None)
        cls_8 = grade_8.class_obj if grade_8 else None
        sec_8a = grade_8 if grade_8 else None
        rows = [
            ("Parent-Teacher Meeting",
             "Scheduled this Saturday from 10 AM to 1 PM. Please meet your class teacher first.",
             date(2026, 5, 25), AnnouncementCategory.SCHOOL, None, None, False),
            ("School closed — Eid",
             "School will remain closed on 17 May for Eid al-Adha.",
             date(2026, 5, 17), AnnouncementCategory.HOLIDAY, None, None, True),
            ("Annual Sports Day",
             "Annual Sports Day on 30 May at the school grounds, 9 AM onwards.",
             date(2026, 5, 30), AnnouncementCategory.SCHOOL, None, None, False),
            ("Math Olympiad selection",
             "Grade 8 selection round next Wednesday during period 3.",
             date(2026, 5, 22), AnnouncementCategory.CLASS, cls_8, None, False),
            ("Grade 8-A field trip permission",
             "Permission slips for the museum visit are due Friday.",
             date(2026, 5, 20), AnnouncementCategory.CLASS, None, sec_8a, True),
        ]
        Announcement.objects.bulk_create([
            Announcement(
                school=school, title=t, body=b, date=d, category=c,
                target_class=tc, target_section=ts, is_read=ir,
            )
            for (t, b, d, c, tc, ts, ir) in rows
        ])
        return len(rows)
