"""Idempotent seed for a realistic Andhra Pradesh demo school.

Usage:
    uv run python manage.py seed_demo            # creates school if missing
    uv run python manage.py seed_demo --reset    # wipes the demo school first

The seeded school admin can log in with:
    phone: +919876543210
    password: demo1234
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
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
from apps.accounts.models import User
from apps.attendance.models import Attendance, AttendanceStatus
from apps.communications.models import (
    Announcement,
    AnnouncementCategory,
    Notification,
    NotificationType,
)
from apps.core.context import use_school
from apps.exams.models import (
    MCQOption,
    Question,
    QuestionType,
    ReportCard,
    ReportCardTerm,
    SubmissionAnswer,
    SubmissionStatus,
    Test,
    TestMode,
    TestScore,
    TestSubmission,
    TestType,
)
from apps.fees import services as fees_services
from apps.fees.models import (
    FeeStructure,
    PaymentMode,
    StudentFee,
    StudentFeeComponent,
)
from apps.people.models import Gender, Relation, Student, StudentStatus, Teacher
from apps.schools.models import AcademicYear, Board, School

SCHOOL_NAME = "Vidya Bharati High School"
SCHOOL_PHONE = "+919876543210"
ADMIN_PASSWORD = "demo1234"

# Login-capable demo teacher for the skooly-guru app (the admin phone above is
# taken, so the teacher uses a distinct number). Linked to the first seeded
# teacher profile, which has assignments so a subject resolves.
TEACHER_PHONE = "+919876500001"
TEACHER_PASSWORD = "demo1234"

# Login-capable demo parent for the skooly-parent app. Phone-only (no
# password seeded) — the parent goes through signup-on-first-use on the
# login screen. Real OTP delivery deferred (ClickUp 86d39qahj).
PARENT_PHONE = "+919876512345"
PARENT_NAME = "Suresh Reddy"

# --- Realistic name pools (AP/Telugu / pan-Indian) -----------------------------

BOY_FIRST_NAMES = [
    "Arjun", "Karthik", "Sai", "Rohit", "Aditya", "Vihaan", "Ishaan", "Krishna",
    "Aravind", "Charan", "Hemanth", "Mahesh", "Naveen", "Pranav", "Rahul",
    "Sandeep", "Surya", "Tarun", "Varun", "Yashwanth", "Anirudh", "Bhargav",
    "Chaitanya", "Dheeraj", "Eshwar", "Gopal", "Harish", "Jaswanth", "Kiran",
    "Lokesh", "Manoj", "Nikhil", "Pavan", "Raghu", "Sasank", "Teja", "Uday",
    "Vamsi", "Yuvraj", "Akhil", "Bharath", "Chandra", "Deepak", "Eswar",
    "Ganesh", "Hari", "Jagadish", "Kalyan", "Lakshman", "Mohan",
]

GIRL_FIRST_NAMES = [
    "Ananya", "Aishwarya", "Bhavana", "Chitra", "Divya", "Geetha", "Harika",
    "Indu", "Jyothi", "Kavya", "Lavanya", "Madhuri", "Nandini", "Padmaja",
    "Priya", "Rashmi", "Sahithi", "Tanvi", "Uma", "Vasundhara", "Yamini",
    "Aaradhya", "Bhavya", "Charita", "Deepika", "Esha", "Gayatri", "Hema",
    "Janaki", "Keerthi", "Lasya", "Manasa", "Navya", "Pavani", "Radhika",
    "Sanjana", "Tejaswini", "Usha", "Vandana", "Yashoda", "Akshara", "Bindu",
    "Chandana", "Disha", "Eshanya", "Gowri", "Hamsini", "Jhansi",
]

SURNAMES = [
    "Reddy", "Naidu", "Rao", "Sharma", "Verma", "Iyer", "Patel", "Choudary",
    "Goud", "Yadav", "Krishna", "Murthy", "Babu", "Chowdary", "Devarakonda",
    "Gunturu", "Kalyan", "Mallikarjuna", "Nagarjuna", "Pasupuleti",
    "Ramachandran", "Subramaniam", "Tirupati", "Venkatesh", "Vasanth",
    "Ananth", "Bharadwaj", "Chinta", "Deshpande", "Gowda",
]

CITIES = [
    "Visakhapatnam", "Vijayawada", "Guntur", "Tirupati", "Nellore", "Kurnool",
    "Rajahmundry", "Kakinada", "Anantapur", "Eluru",
]
STREETS = [
    "MG Road", "Main Road", "Gandhi Nagar", "Krishna Lane", "Temple Street",
    "School Road", "Market Road", "Railway Station Road", "RTC Complex",
]

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

TEACHER_QUALS = [
    "M.Sc., B.Ed.", "M.A., B.Ed.", "B.Tech, B.Ed.", "M.Sc. Physics, B.Ed.",
    "M.A. English, B.Ed.", "M.Sc. Maths, B.Ed.", "M.A. Telugu, B.Ed.",
    "M.Com., B.Ed.", "M.Sc. Chemistry, B.Ed.", "M.Sc. Biology, B.Ed.",
]

SUBJECTS = [
    ("Telugu", "TEL"),
    ("Hindi", "HIN"),
    ("English", "ENG"),
    ("Mathematics", "MAT"),
    ("General Science", "SCI"),
    ("Physical Science", "PSC"),
    ("Biological Science", "BIO"),
    ("Social Studies", "SOC"),
    ("Computer Science", "CS"),
]

CLASS_LEVELS = [
    ("Class 1", 1), ("Class 2", 2), ("Class 3", 3), ("Class 4", 4),
    ("Class 5", 5), ("Class 6", 6), ("Class 7", 7), ("Class 8", 8),
    ("Class 9", 9), ("Class 10", 10),
]

SECTIONS_PER_CLASS = {
    "Class 1": ["A", "B"], "Class 2": ["A", "B"], "Class 3": ["A", "B"],
    "Class 4": ["A", "B"], "Class 5": ["A", "B"],
    "Class 6": ["A", "B", "C"], "Class 7": ["A", "B", "C"],
    "Class 8": ["A", "B", "C"], "Class 9": ["A", "B", "C"],
    "Class 10": ["A", "B"],
}

STUDENTS_PER_SECTION = 28  # average; varies +/-3
TEACHER_COUNT = 18


class Command(BaseCommand):
    help = "Seed the database with a realistic Andhra Pradesh demo school."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--reset", action="store_true", help="Wipe the demo school first.")
        parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")

    def handle(self, *args: Any, **opts: Any) -> None:
        rng = random.Random(opts["seed"])

        existing = User.objects.filter(phone=SCHOOL_PHONE).first()
        if existing and not opts["reset"]:
            self.stdout.write(self.style.WARNING(
                f"Demo school already seeded (admin {SCHOOL_PHONE}). Use --reset to recreate."
            ))
            return

        with transaction.atomic():
            if opts["reset"] and existing:
                self.stdout.write("Wiping existing demo school…")
                school = existing.school
                if school:
                    School.all_tenants.filter(id=school.id).delete()
                existing.delete()

            school, _admin, _tokens = self._seed_school()
            self.stdout.write(self.style.SUCCESS(f"  ✓ school: {school.name} (id={school.id})"))
            self.stdout.write(self.style.SUCCESS(f"  ✓ admin login: {SCHOOL_PHONE} / {ADMIN_PASSWORD}"))

            with use_school(school):
                year = school.current_academic_year
                assert year is not None
                subjects = self._seed_subjects(school)
                self.stdout.write(self.style.SUCCESS(f"  ✓ subjects: {len(subjects)}"))

                teachers = self._seed_teachers(rng, school)
                self.stdout.write(self.style.SUCCESS(f"  ✓ teachers: {len(teachers)}"))

                classes_map = self._seed_classes(school, year, subjects)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ classes: {len(classes_map)}  ({sum(len(v) for v in classes_map.values())} sections)"
                ))

                self._seed_assignments(rng, school, year, classes_map, subjects, teachers)

                self._seed_teacher_login(school, teachers)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ teacher login: {TEACHER_PHONE} / {TEACHER_PASSWORD}"
                ))

                total_students = 0
                for cls_name, sections in classes_map.items():
                    for sec in sections:
                        count = rng.randint(STUDENTS_PER_SECTION - 3, STUDENTS_PER_SECTION + 3)
                        self._seed_section_students(
                            rng, school, year, sec, count, cls_name
                        )
                        total_students += count
                self.stdout.write(self.style.SUCCESS(f"  ✓ students: {total_students}"))

                marks_total = self._seed_attendance(rng, school)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ attendance: {marks_total:,} marks across ~60 school days"
                ))

                tests_total, scores_total = self._seed_tests(rng, school, teachers)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ tests: {tests_total} published tests with {scores_total:,} scores"
                ))

                fee_stats = self._seed_fees(rng, school)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ fees: {fee_stats['structures']} structures, "
                    f"{fee_stats['student_fees']:,} student fees, "
                    f"{fee_stats['payments']:,} payments"
                ))

                children = self._seed_parent(school, classes_map)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ parent login: {PARENT_PHONE} (set password on first login) → "
                    f"{', '.join(c.full_name for c in children)}"
                ))

                ann_count = self._seed_announcements(school, classes_map)
                self.stdout.write(self.style.SUCCESS(f"  ✓ announcements: {ann_count}"))

                tt_count = self._seed_timetable(school, classes_map)
                self.stdout.write(self.style.SUCCESS(f"  ✓ timetable periods: {tt_count}"))

                rc_count = self._seed_report_cards(school, children, year)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ report cards: {rc_count} published"
                ))

                ot_count, sub_count = self._seed_online_tests(
                    school, children, teachers
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ online tests: {ot_count} published, "
                    f"{sub_count} pre-submitted attempts"
                ))

        self.stdout.write(self.style.SUCCESS("Demo seed complete."))

    # --- Helpers ----------------------------------------------------------------

    def _seed_parent(
        self, school: School, classes_map: dict[str, list[Section]]
    ) -> list[Student]:
        """Create the demo parent (Suresh Reddy) and link two real students,
        renamed Aarav/Ananya Reddy so the parent-app demo reads naturally."""
        from apps.people.models import Parent, ParentStudent

        def adopt(cls_name: str, first_name: str) -> Student | None:
            for sec in classes_map.get(cls_name, []):
                enr = (
                    StudentEnrollment.objects.filter(section=sec, status="active")
                    .select_related("student")
                    .order_by("id")
                    .first()
                )
                if enr is None:
                    continue
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
                    "parent1_relation", "parent1_whatsapp", "primary_whatsapp_phone",
                    "updated_at",
                ])
                return st
            return None

        children = [c for c in (adopt("Class 8", "Aarav"), adopt("Class 5", "Ananya")) if c]
        # NOTE: deliberately no User row here. The parent goes through the
        # first-use signup flow on the login screen (set their own password).
        parent = Parent.objects.create(
            school=school,
            name=PARENT_NAME,
            phone=PARENT_PHONE,
            email="suresh.reddy@example.com",
        )
        for child in children:
            ParentStudent.objects.create(
                school=school, parent=parent, student=child, relation=Relation.FATHER
            )
            self._seed_notifications(school, child)
        return children

    @staticmethod
    def _seed_online_tests(
        school: School, children: list[Student], teachers: list[Teacher],
    ) -> tuple[int, int]:
        """Seed two online tests per demo child's section:
          - A pending Math practice quiz with 5 MCQs (no submission yet)
          - A completed Science review quiz with 5 MCQs (pre-submitted)
        Returns (test count, pre-submitted submission count).
        """
        from apps.academics.models import Subject

        # Same two tests per child's section — picked by name so the demo
        # parent sees both a pending and a completed test on the list. Each
        # questions_data entry is either:
        #   (text, [(option, is_correct), ...])  — MCQ
        #   (text, "correct text")              — short-answer
        def make_quiz(
            section, subject_name: str, name: str, available_until,
            questions_data: list,
        ) -> Test:
            subject = Subject.objects.filter(
                school=school, name=subject_name
            ).first() or Subject.objects.filter(school=school).first()
            teacher = section.class_teacher or (teachers[0] if teachers else None)
            test = Test.objects.create(
                school=school, section=section, subject=subject, name=name,
                test_type=TestType.OTHER, mode=TestMode.ONLINE,
                test_date=timezone.now().date(),
                available_from=timezone.now() - timezone.timedelta(days=1),
                available_until=available_until,
                duration_min=20,
                max_marks=sum(1 for _ in questions_data),  # 1 mark per question
                created_by=teacher,
                published_at=timezone.now(),
            )
            for idx, (q_text, payload) in enumerate(questions_data):
                if isinstance(payload, str):
                    # Short-answer question — no MCQOption rows, correct text
                    # lives on the Question itself for case-insensitive
                    # equality at grade time.
                    Question.objects.create(
                        school=school, test=test,
                        question_type=QuestionType.SHORT_ANSWER,
                        text=q_text, marks=1, display_order=idx, topic=subject_name,
                        correct_answer=payload,
                    )
                else:
                    q = Question.objects.create(
                        school=school, test=test,
                        question_type=QuestionType.MCQ,
                        text=q_text, marks=1, display_order=idx, topic=subject_name,
                    )
                    for o_idx, (o_text, is_correct) in enumerate(payload):
                        MCQOption.objects.create(
                            question=q, text=o_text, is_correct=is_correct,
                            display_order=o_idx,
                        )
            return test

        math_questions = [
            ("What is 7 x 8?",
             [("54", False), ("56", True), ("64", False), ("48", False)]),
            ("Which is a prime number?",
             [("9", False), ("21", False), ("11", True), ("15", False)]),
            ("What is 144 / 12?",
             [("11", False), ("12", True), ("14", False), ("10", False)]),
            ("Round 47.6 to the nearest whole.",
             [("47", False), ("48", True), ("47.5", False), ("50", False)]),
            # Short-answer: case-insensitive equality at grade time.
            ("Name the smallest prime number.", "2"),
        ]
        sci_questions = [
            ("Which gas do plants absorb during photosynthesis?",
             [("Oxygen", False), ("Carbon dioxide", True), ("Nitrogen", False), ("Hydrogen", False)]),
            ("How many planets in our solar system?",
             [("7", False), ("8", True), ("9", False), ("10", False)]),
            ("Water freezes at?",
             [("0°C", True), ("4°C", False), ("32°C", False), ("100°C", False)]),
            ("Which is NOT a force?",
             [("Gravity", False), ("Friction", False), ("Magnetism", False), ("Distance", True)]),
            # Short-answer.
            ("Tallest mountain on Earth?", "Mount Everest"),
        ]

        deadline = timezone.now() + timezone.timedelta(days=7)
        tests_created = 0
        submissions_created = 0

        for child in children:
            enroll = child.enrollments.filter(status="active").select_related("section").first()
            if enroll is None:
                continue
            section = enroll.section

            # 1. Pending Math quiz — no submission.
            make_quiz(section, "Mathematics", "Practice Quiz — Numbers", deadline, math_questions)
            tests_created += 1

            # 2. Completed Science quiz — pre-submit with a mixed result so
            # the demo parent can immediately tap into the result screen.
            sci_test = make_quiz(section, "Science", "Revision Quiz — General Knowledge",
                                 deadline, sci_questions)
            tests_created += 1

            submission = TestSubmission.objects.create(
                school=school, test=sci_test, student=child,
                status=SubmissionStatus.SUBMITTED,
                submitted_at=timezone.now() - timezone.timedelta(hours=2),
                max_marks=sci_test.max_marks or 0,
            )
            total = 0
            for idx, q in enumerate(sci_test.questions.all().order_by("display_order")):
                if q.question_type == QuestionType.SHORT_ANSWER:
                    # Wrong text for the short-answer at the end so the demo
                    # result shows a 4/5 mixed score including an "incorrect"
                    # short-answer review row.
                    SubmissionAnswer.objects.create(
                        school=school, submission=submission, question=q,
                        text_answer="Kanchenjunga",
                        is_correct=False, marks_awarded=0,
                    )
                    continue
                options = list(q.options.all().order_by("display_order"))
                # First 4 MCQs answered correctly.
                pick = next(o for o in options if o.is_correct) if idx < 4 else options[0]
                is_correct = bool(pick.is_correct)
                marks = q.marks if is_correct else 0
                total += marks
                SubmissionAnswer.objects.create(
                    school=school, submission=submission, question=q,
                    selected_option=pick, is_correct=is_correct, marks_awarded=marks,
                )
            submission.total_marks = total
            submission.save(update_fields=["total_marks", "updated_at"])
            # Mirror to TestScore so the existing teacher report endpoint
            # also sees this online attempt.
            TestScore.objects.update_or_create(
                test=sci_test, student=child,
                defaults={
                    "school": school, "marks_obtained": total, "is_absent": False,
                },
            )
            submissions_created += 1

        return tests_created, submissions_created

    @staticmethod
    def _seed_report_cards(
        school: School, children: list[Student], year: AcademicYear
    ) -> int:
        """Seed Term 1 + Term 2 report cards (both published) for each demo child."""

        def grade(pct: float) -> str:
            if pct >= 91:
                return "A1"
            if pct >= 81:
                return "A2"
            if pct >= 71:
                return "B1"
            if pct >= 61:
                return "B2"
            if pct >= 51:
                return "C1"
            if pct >= 41:
                return "C2"
            if pct >= 33:
                return "D"
            return "E"

        # Class 8 subjects (Aarav) vs Class 5 subjects (Ananya) — keep distinct
        # marks so the two children's cards don't look identical in the demo.
        class_8_subjects = [
            ("Mathematics",    [68, 74]),  # [term1_marks, term2_marks]
            ("Science",        [72, 76]),
            ("Social Studies", [78, 82]),
            ("English",        [81, 85]),
            ("Hindi",          [65, 70]),
            ("Computer Sci.",  [85, 88]),
        ]
        class_5_subjects = [
            ("Mathematics",    [88, 85]),
            ("Science",        [82, 79]),
            ("Social Studies", [76, 80]),
            ("English",        [90, 92]),
            ("Hindi",          [84, 88]),
        ]

        term_meta = [
            (ReportCardTerm.TERM_1, "Term 1", date(2025, 10, 31)),
            (ReportCardTerm.TERM_2, "Term 2", date(2026, 2, 28)),
        ]
        remark_options = [
            "A focused student with steady improvement this term. Keep up the good effort.",
            "Shows consistent application and active class participation. Encouraged to keep aiming higher.",
        ]
        principal_remark = "Maintains a positive attitude and sets a good example for peers."

        rows: list[ReportCard] = []
        for child in children:
            # Class-aware subject set + section size for rank denom.
            enroll = child.enrollments.filter(status="active").first()
            section = enroll.section if enroll else None
            total_students = (
                StudentEnrollment.objects.filter(section=section, status="active").count()
                if section else 30
            )
            is_upper = bool(enroll and enroll.section.class_obj.display_order >= 6)
            subjects = class_8_subjects if is_upper else class_5_subjects

            for term_idx, (term_value, term_label, issue_date) in enumerate(term_meta):
                subj_payload = []
                total_marks = 0
                for name, marks_pair in subjects:
                    m = marks_pair[term_idx]
                    subj_payload.append({
                        "name": name, "maxMarks": 100, "marks": m, "grade": grade(m),
                    })
                    total_marks += m
                overall_pct = round(total_marks / len(subjects))

                snapshot = {
                    "term": term_label,
                    "academicYear": year.label,
                    "issueDate": issue_date.isoformat(),
                    "subjects": subj_payload,
                    "attendancePct": 92 if term_idx == 1 else 87,
                    "teacherRemark": remark_options[term_idx],
                    "principalRemark": principal_remark if term_idx == 1 else None,
                    "overallGrade": grade(overall_pct),
                    "overallPct": overall_pct,
                    "rank": 9 if term_idx == 1 else 7,
                    "totalStudents": total_students,
                }
                rows.append(ReportCard(
                    school=school, student=child, academic_year=year, term=term_value,
                    published_at=timezone.now(),
                    data_snapshot=snapshot,
                ))
        ReportCard.objects.bulk_create(rows)
        return len(rows)

    @staticmethod
    def _seed_timetable(school: School, classes_map: dict[str, list[Section]]) -> int:
        """Seed a weekly timetable for every section. Higher classes (6-10) get
        8 periods Mon-Fri + 5 on Sat; lower classes (1-5) get 7 + 5. Lunch /
        recess gaps are inferred client-side from the time gaps."""

        # Period slots per day. Slot tuples are (period_number, start, end).
        weekday_high = [
            (1, time(8, 0), time(8, 45)),
            (2, time(8, 45), time(9, 30)),
            (3, time(9, 30), time(10, 15)),
            (4, time(10, 30), time(11, 15)),
            (5, time(11, 15), time(12, 0)),
            (6, time(12, 45), time(13, 30)),
            (7, time(13, 30), time(14, 15)),
            (8, time(14, 15), time(15, 0)),
        ]
        weekday_low = [
            (1, time(8, 30), time(9, 15)),
            (2, time(9, 15), time(10, 0)),
            (3, time(10, 0), time(10, 45)),
            (4, time(11, 0), time(11, 45)),
            (5, time(11, 45), time(12, 30)),
            (6, time(13, 0), time(13, 45)),
            (7, time(13, 45), time(14, 30)),
        ]
        sat_high = weekday_high[:5]
        sat_low = weekday_low[:5]
        weekdays = [DayOfWeek.MON, DayOfWeek.TUE, DayOfWeek.WED, DayOfWeek.THU, DayOfWeek.FRI]

        rows: list[TimetablePeriod] = []
        for cls_name, sections in classes_map.items():
            level = next(o for n, o in CLASS_LEVELS if n == cls_name)
            cls_subjects = list(
                Subject.objects.filter(class_mappings__class_obj__name=cls_name).order_by("id")
            )
            if not cls_subjects:
                continue
            weekday_slots = weekday_high if level >= 6 else weekday_low
            sat_slots = sat_high if level >= 6 else sat_low

            for section in sections:
                assignments = {
                    a.subject_id: a.teacher
                    for a in TeacherAssignment.objects.filter(section=section).select_related("teacher")
                }
                for day in weekdays:
                    for idx, (pnum, start, end) in enumerate(weekday_slots):
                        # Rotate subjects per day so every day looks varied.
                        subj = cls_subjects[(idx + day.value * 3) % len(cls_subjects)]
                        rows.append(TimetablePeriod(
                            school=school, section=section, day_of_week=day,
                            period_number=pnum, subject=subj,
                            teacher=assignments.get(subj.id),
                            start_time=start, end_time=end,
                        ))
                for idx, (pnum, start, end) in enumerate(sat_slots):
                    subj = cls_subjects[idx % len(cls_subjects)]
                    rows.append(TimetablePeriod(
                        school=school, section=section, day_of_week=DayOfWeek.SAT,
                        period_number=pnum, subject=subj,
                        teacher=assignments.get(subj.id),
                        start_time=start, end_time=end,
                    ))
        TimetablePeriod.objects.bulk_create(rows, batch_size=2000)
        return len(rows)

    @staticmethod
    def _seed_announcements(school: School, classes_map: dict[str, list[Section]]) -> int:
        # Class 8 + Class 8-A so the demo Aarav sees class/section-targeted ones.
        sections_c8 = classes_map.get("Class 8", [])
        cls_8 = sections_c8[0].class_obj if sections_c8 else None
        sec_8a = sections_c8[0] if sections_c8 else None
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
             "Class 8 selection round next Wednesday during period 3.",
             date(2026, 5, 22), AnnouncementCategory.CLASS, cls_8, None, False),
            ("Class 8-A field trip permission",
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

    @staticmethod
    def _seed_notifications(school: School, child: Student) -> None:
        fn = child.first_name
        # Today's attendance notice expires end of day so it doesn't accumulate
        # day over day — the parent only ever sees the current status.
        eod = timezone.now().replace(hour=23, minute=59, second=59, microsecond=0)
        rows = [
            (NotificationType.ATTENDANCE, f"{fn} is in school",
             "Marked present this morning.", "/attendance", False, eod),
            (NotificationType.FEE, "Fee overdue: Transport",
             "Transport Fee was due. Please clear at the school office.", "/fees", False, None),
            (NotificationType.TEST, "New online test assigned",
             "A practice quiz is now available.", "/more/online-tests", True, None),
            (NotificationType.MARKS, "Test results published",
             f"{fn}'s latest test marks are out.", "/marks", True, None),
            (NotificationType.ANNOUNCEMENT, "Parent-Teacher Meeting",
             "Scheduled this Saturday, 10 AM to 1 PM.", "/more/announcements", True, None),
        ]
        Notification.objects.bulk_create([
            Notification(
                school=school, student=child, type=t, title=title, body=body,
                link_to=link, is_read=is_read, expires_at=expires_at,
            )
            for (t, title, body, link, is_read, expires_at) in rows
        ])

    def _seed_school(self) -> tuple[School, User, dict]:
        from apps.accounts import services as auth_services

        user, school, tokens = auth_services.signup_school(
            school_name=SCHOOL_NAME,
            board=Board.AP_STATE,
            address="Gandhi Nagar, Vijayawada, Andhra Pradesh 520003",
            academic_year_label="2025-26",
            academic_year_start=date(2025, 6, 1),
            academic_year_end=date(2026, 4, 30),
            admin_first_name="Lakshmi",
            admin_last_name="Narayana",
            admin_phone=SCHOOL_PHONE,
            admin_email="principal@vidyabharati.school",
            admin_password=ADMIN_PASSWORD,
        )
        school.whatsapp_number = "+918000000000"
        school.primary_color = "#1f4e79"
        school.save(update_fields=["whatsapp_number", "primary_color"])
        return school, user, tokens

    def _seed_subjects(self, school: School) -> dict[str, Subject]:
        subjects = {}
        for name, code in SUBJECTS:
            subj, _ = Subject.objects.get_or_create(
                school=school, name=name, defaults={"code": code}
            )
            subjects[name] = subj
        return subjects

    def _seed_teachers(self, rng: random.Random, school: School) -> list[Teacher]:
        teachers: list[Teacher] = []
        for i in range(TEACHER_COUNT):
            is_female = i % 2 == 0
            first = rng.choice(GIRL_FIRST_NAMES if is_female else BOY_FIRST_NAMES)
            last = rng.choice(SURNAMES)
            phone = f"+9197{rng.randint(10000000, 99999999):08d}"
            teacher = Teacher.objects.create(
                school=school,
                first_name=first,
                last_name=last,
                phone=phone,
                email=f"{first.lower()}.{last.lower()}@vidyabharati.school",
                qualification=rng.choice(TEACHER_QUALS),
                joining_date=date(2020 + (i % 5), rng.randint(1, 12), rng.randint(1, 28)),
                status="active",
                photo_url=f"https://api.dicebear.com/9.x/initials/svg?seed={first}+{last}",
            )
            teachers.append(teacher)
        return teachers

    def _seed_teacher_login(self, school: School, teachers: list[Teacher]) -> None:
        """Create a login-capable User for the first teacher so the skooly-guru
        app has a real account to authenticate against."""
        teacher = teachers[0]
        user, _created = User.objects.get_or_create(
            phone=TEACHER_PHONE,
            defaults={
                "school": school,
                "role": "teacher",
                "first_name": teacher.first_name,
                "last_name": teacher.last_name,
                "email": teacher.email,
            },
        )
        user.set_password(TEACHER_PASSWORD)
        user.save()
        teacher.user = user
        teacher.save(update_fields=["user"])

    def _seed_classes(
        self,
        school: School,
        year: AcademicYear,
        subjects: dict[str, Subject],
    ) -> dict[str, list[Section]]:
        result: dict[str, list[Section]] = {}
        for cls_name, order in CLASS_LEVELS:
            cls = Class.objects.create(
                school=school,
                academic_year=year,
                name=cls_name,
                display_order=order,
            )
            # Subject mapping: primary classes get fewer subjects.
            applicable = self._subjects_for_class(order, subjects)
            for subj in applicable:
                SubjectClassMapping.objects.create(school=school, subject=subj, class_obj=cls)

            sections = []
            for sec_name in SECTIONS_PER_CLASS[cls_name]:
                section = Section.objects.create(
                    school=school,
                    class_obj=cls,
                    name=sec_name,
                    room_number=f"{order}{sec_name}",
                    capacity=40,
                )
                sections.append(section)
            result[cls_name] = sections
        return result

    @staticmethod
    def _subjects_for_class(level: int, subjects: dict[str, Subject]) -> list[Subject]:
        if level <= 5:
            keys = ["Telugu", "English", "Mathematics", "General Science", "Social Studies"]
        elif level <= 7:
            keys = ["Telugu", "Hindi", "English", "Mathematics", "General Science", "Social Studies"]
        else:
            keys = [
                "Telugu", "Hindi", "English", "Mathematics",
                "Physical Science", "Biological Science", "Social Studies", "Computer Science",
            ]
        return [subjects[k] for k in keys if k in subjects]

    def _seed_assignments(
        self,
        rng: random.Random,
        school: School,
        year: AcademicYear,
        classes_map: dict[str, list[Section]],
        subjects: dict[str, Subject],
        teachers: list[Teacher],
    ) -> None:
        # Each section gets a class teacher; each subject taught to that section
        # is assigned a teacher round-robin from the pool.
        for cls_name, sections in classes_map.items():
            order = next(o for n, o in CLASS_LEVELS if n == cls_name)
            applicable = self._subjects_for_class(order, subjects)
            for section in sections:
                section.class_teacher = rng.choice(teachers)
                section.save(update_fields=["class_teacher"])
                for subj in applicable:
                    teacher = rng.choice(teachers)
                    TeacherAssignment.objects.get_or_create(
                        school=school,
                        teacher=teacher,
                        subject=subj,
                        section=section,
                        academic_year=year,
                    )

    def _seed_section_students(
        self,
        rng: random.Random,
        school: School,
        year: AcademicYear,
        section: Section,
        count: int,
        cls_name: str,
    ) -> None:
        cls_order = next(o for n, o in CLASS_LEVELS if n == cls_name)
        base_age = cls_order + 5  # Class 1 ~6yo, Class 10 ~15yo
        for i in range(count):
            is_female = rng.random() < 0.48
            first = rng.choice(GIRL_FIRST_NAMES if is_female else BOY_FIRST_NAMES)
            last = rng.choice(SURNAMES)
            father_first = rng.choice(BOY_FIRST_NAMES)
            mother_first = rng.choice(GIRL_FIRST_NAMES)

            today = date(2026, 5, 17)
            dob_year = today.year - base_age - rng.randint(0, 1)
            dob = date(dob_year, rng.randint(1, 12), rng.randint(1, 28))
            admission_year = today.year - (cls_order - 1)

            adm = f"VB{admission_year}{section.class_obj.display_order:02d}{section.id:02d}{i + 1:03d}"
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
                    f"{rng.choice(CITIES)}, AP"
                ),
                photo_url=f"https://api.dicebear.com/9.x/avataaars/svg?seed={first}+{last}+{i}",
                admission_date=date(admission_year, 6, rng.randint(1, 20)),
                status=StudentStatus.ACTIVE,
                parent1_name=f"{father_first} {last}",
                parent1_phone=f"+9198{rng.randint(10000000, 99999999):08d}",
                parent1_relation=Relation.FATHER,
                parent1_whatsapp=True,
                parent2_name=f"{mother_first} {last}",
                parent2_phone=f"+9197{rng.randint(10000000, 99999999):08d}",
                parent2_relation=Relation.MOTHER,
                parent2_whatsapp=rng.random() < 0.4,
                primary_whatsapp_phone=f"+9198{rng.randint(10000000, 99999999):08d}",
            )
            StudentEnrollment.objects.create(
                school=school,
                student=student,
                section=section,
                academic_year=year,
                roll_number=f"{i + 1:02d}",
                enrollment_date=date(admission_year, 6, 15),
                status="active",
            )

    def _seed_attendance(self, rng: random.Random, school: School) -> int:
        """Generate ~60 school days of attendance (Mon-Sat) ending yesterday.

        Per-student baseline attendance rate is sampled from a distribution
        skewed high (mean ~93%) so most kids are mostly present, with a
        handful of regular absentees for realism.
        """
        today = timezone.now().date()
        # Last 90 calendar days; we'll skip Sundays giving ~78 marking days.
        # Cap at 60 days actually marked to keep volume manageable.
        candidate_days: list[date] = []
        d = today - timedelta(days=1)
        while len(candidate_days) < 60 and d > today - timedelta(days=120):
            if d.weekday() != 6:  # 6 = Sunday
                candidate_days.append(d)
            d -= timedelta(days=1)
        candidate_days.reverse()

        # Pre-compute (section, [(student, base_rate, marked_by_teacher)]).
        sections = list(
            Section.objects.filter(school=school).select_related("class_teacher")
        )
        per_section: dict[int, list[tuple[Student, float, Teacher | None]]] = {}
        for section in sections:
            students = list(
                Student.objects.filter(
                    school=school,
                    enrollments__section=section,
                    enrollments__status="active",
                ).distinct()
            )
            roster = [
                (
                    s,
                    # base attendance rate: mean ~0.93, min ~0.70
                    max(0.70, min(0.99, rng.gauss(0.93, 0.05))),
                    section.class_teacher,
                )
                for s in students
            ]
            per_section[section.id] = roster

        rows: list[Attendance] = []
        for day in candidate_days:
            for section in sections:
                for student, base_rate, teacher in per_section[section.id]:
                    r = rng.random()
                    if r < base_rate:
                        # Most are present; small chance of late
                        status = (
                            AttendanceStatus.LATE
                            if rng.random() < 0.04
                            else AttendanceStatus.PRESENT
                        )
                    else:
                        # Absent group; small chance of half-day instead
                        status = (
                            AttendanceStatus.HALF_DAY
                            if rng.random() < 0.15
                            else AttendanceStatus.ABSENT
                        )
                    marked_dt = timezone.make_aware(
                        datetime.combine(day, time(9, rng.randint(0, 30)))
                    )
                    rows.append(
                        Attendance(
                            school=school,
                            student=student,
                            section=section,
                            date=day,
                            status=status,
                            marked_by=teacher,
                            marked_at=marked_dt,
                            notes="",
                        )
                    )

        Attendance.objects.bulk_create(rows, batch_size=2000)

        # bulk_create skips auto_now_add, so set marked_at explicitly via UPDATE.
        # (We already pass marked_at above; the auto_now_add is harmless for bulk_create.)
        return len(rows)

    def _seed_tests(
        self, rng: random.Random, school: School, teachers: list[Teacher]
    ) -> tuple[int, int]:
        """For each (section, subject) generate ~3 published tests over the last
        90 days. Per-student score is sampled from a normal distribution skewed
        toward 60-80% of max marks; ~5% absent rate. Some students consistently
        do better or worse so subject averages look realistic across tests."""
        from decimal import Decimal

        from apps.academics.models import (
            Section as SectionModel,
        )
        from apps.academics.models import (
            SubjectClassMapping as Mapping,
        )

        today = timezone.now().date()

        # Cache: section_id -> list of (student, ability) where ability in [-0.2, +0.2]
        # is a per-student offset on the score distribution mean.
        section_rosters: dict[int, list[tuple[Student, float]]] = {}
        sections = SectionModel.objects.filter(school=school).select_related("class_obj")
        for section in sections:
            students = list(
                Student.objects.filter(
                    school=school,
                    enrollments__section=section,
                    enrollments__status="active",
                ).distinct()
            )
            section_rosters[section.id] = [
                (s, rng.gauss(0.0, 0.08)) for s in students
            ]

        test_count = 0
        score_count = 0
        score_rows: list[TestScore] = []

        # Distribution of test types and their characteristics.
        plans = [
            (TestType.FA1, "FA1 · Unit Test", 50, 70),
            (TestType.FA2, "FA2 · Unit Test", 50, 50),
            (TestType.SA1, "SA1 · Term Exam", 100, 30),
        ]

        for section in sections:
            roster = section_rosters[section.id]
            if not roster:
                continue
            subjects_for_class = [
                m.subject
                for m in Mapping.objects.filter(
                    school=school, class_obj=section.class_obj
                ).select_related("subject")
            ]
            if not subjects_for_class:
                continue

            for subject in subjects_for_class:
                for test_type, name_suffix, max_marks, days_ago in plans:
                    test_date = today - timedelta(days=days_ago + rng.randint(-3, 3))
                    published_at = timezone.make_aware(
                        datetime.combine(
                            test_date + timedelta(days=rng.randint(1, 4)),
                            time(16, rng.randint(0, 45)),
                        )
                    )
                    test = Test.objects.create(
                        school=school,
                        section=section,
                        subject=subject,
                        name=f"{subject.name} {name_suffix}",
                        test_type=test_type,
                        test_date=test_date,
                        max_marks=max_marks,
                        created_by=section.class_teacher or rng.choice(teachers),
                        published_at=published_at,
                    )
                    test_count += 1

                    for student, ability in roster:
                        if rng.random() < 0.05:
                            score_rows.append(
                                TestScore(
                                    school=school,
                                    test=test,
                                    student=student,
                                    marks_obtained=None,
                                    is_absent=True,
                                )
                            )
                            score_count += 1
                            continue
                        # Mean 0.72 (~72%) + per-student ability offset, sd 0.12,
                        # clamped to [0.25, 1.0] of max_marks.
                        pct = max(0.25, min(1.0, rng.gauss(0.72 + ability, 0.12)))
                        marks = round(Decimal(pct * max_marks), 2)
                        score_rows.append(
                            TestScore(
                                school=school,
                                test=test,
                                student=student,
                                marks_obtained=marks,
                                is_absent=False,
                            )
                        )
                        score_count += 1

        TestScore.objects.bulk_create(score_rows, batch_size=2000)
        return test_count, score_count

    def _seed_fees(self, rng: random.Random, school: School) -> dict[str, int]:
        """Create one fee structure per class for the current academic year,
        apply to every student, then generate a realistic payment distribution:
        ~35% fully paid, ~25% partial, ~30% pending, ~10% overdue.

        Skips PDF receipt generation in seed (WeasyPrint is slow at volume;
        admins can regenerate on demand). receipt_pdf_url stays empty.
        """
        year = school.current_academic_year
        assert year is not None

        # Fee structures per grade level (paise). AP State Board realistic
        # ranges: ~₹15k for primary, ~₹35-50k for high school.
        class_fee_plans = {
            # class_order: (structure_name, [(component_name, paise, due_offset_days, optional?)])
            1: ("Class 1 Annual Fees", [
                ("Tuition", 12_00_000, 0, False),
                ("Books & Stationery", 2_50_000, 30, False),
                ("Transport", 8_00_000, 0, True),
            ]),
            2: ("Class 2 Annual Fees", [
                ("Tuition", 13_00_000, 0, False),
                ("Books & Stationery", 2_50_000, 30, False),
                ("Transport", 8_00_000, 0, True),
            ]),
            3: ("Class 3 Annual Fees", [
                ("Tuition", 14_00_000, 0, False),
                ("Books & Stationery", 3_00_000, 30, False),
                ("Transport", 9_00_000, 0, True),
            ]),
            4: ("Class 4 Annual Fees", [
                ("Tuition", 15_00_000, 0, False),
                ("Books & Stationery", 3_00_000, 30, False),
                ("Transport", 9_00_000, 0, True),
            ]),
            5: ("Class 5 Annual Fees", [
                ("Tuition", 16_00_000, 0, False),
                ("Books & Stationery", 3_50_000, 30, False),
                ("Transport", 9_00_000, 0, True),
            ]),
            6: ("Class 6 Annual Fees", [
                ("Tuition", 28_00_000, 0, False),
                ("Books & Stationery", 4_00_000, 30, False),
                ("Lab Fee", 2_00_000, 60, False),
                ("Computer Fee", 1_50_000, 60, False),
                ("Transport", 12_00_000, 0, True),
            ]),
            7: ("Class 7 Annual Fees", [
                ("Tuition", 30_00_000, 0, False),
                ("Books & Stationery", 4_00_000, 30, False),
                ("Lab Fee", 2_00_000, 60, False),
                ("Computer Fee", 1_50_000, 60, False),
                ("Transport", 12_00_000, 0, True),
            ]),
            8: ("Class 8 Annual Fees", [
                ("Tuition", 35_00_000, 0, False),
                ("Books & Stationery", 4_50_000, 30, False),
                ("Lab Fee", 2_50_000, 60, False),
                ("Computer Fee", 1_50_000, 60, False),
                ("Transport", 12_00_000, 0, True),
            ]),
            9: ("Class 9 Annual Fees", [
                ("Tuition", 42_00_000, 0, False),
                ("Books & Stationery", 5_00_000, 30, False),
                ("Lab Fee", 3_00_000, 60, False),
                ("Computer Fee", 2_00_000, 60, False),
                ("Transport", 12_00_000, 0, True),
            ]),
            10: ("Class 10 Annual Fees", [
                ("Tuition", 48_00_000, 0, False),
                ("Books & Stationery", 5_00_000, 30, False),
                ("Lab Fee", 3_00_000, 60, False),
                ("Computer Fee", 2_00_000, 60, False),
                ("Board Exam Fee", 1_50_000, 90, False),
                ("Transport", 12_00_000, 0, True),
            ]),
        }

        # Term-start date for due-date calculations.
        term_start = year.start_date

        structures: list[FeeStructure] = []
        for cls in Class.objects.filter(school=school, academic_year=year).order_by("display_order"):
            plan = class_fee_plans.get(cls.display_order)
            if plan is None:
                continue
            structure_name, components_plan = plan
            components_payload = [
                {
                    "name": name,
                    "amount_paise": amount,
                    "due_date": term_start + timedelta(days=offset),
                    "is_optional": optional,
                    "display_order": idx,
                }
                for idx, (name, amount, offset, optional) in enumerate(components_plan)
            ]
            structure = fees_services.create_structure(
                school=school,
                actor_id=None,  # type: ignore[arg-type]
                academic_year_id=year.id,
                class_id=cls.id,
                name=structure_name,
                components=components_payload,
            )
            structures.append(structure)
            fees_services.apply_structure_to_class(
                school=school, actor_id=None, structure_id=structure.id  # type: ignore[arg-type]
            )

        # Generate payments. For each StudentFee, roll a die:
        #   35% → pay in full (one lump or split)
        #   25% → pay partial (one payment covering 30-70% of final)
        #   30% → no payments (pending)
        #   10% → no payments AND we'll let the natural recompute mark overdue
        # We don't generate PDFs in seed — too slow at this volume. Admins
        # can regenerate later on demand.
        admin_user = User.objects.filter(school=school, role="admin").first()
        payment_modes = [PaymentMode.CASH, PaymentMode.CHEQUE, PaymentMode.BANK_TRANSFER, PaymentMode.ONLINE]
        payments_made = 0
        today = timezone.now().date()

        student_fees = list(
            StudentFee.objects.filter(school=school).select_related("fee_structure")
        )
        rng.shuffle(student_fees)

        for sf in student_fees:
            roll = rng.random()
            if roll < 0.10:
                continue  # will become overdue once recompute runs
            if roll < 0.40:
                continue  # pending, due date not yet passed

            applicable_components = list(
                StudentFeeComponent.objects.filter(
                    school=school, student_fee=sf, is_applicable=True
                ).select_related("fee_component")
            )
            if not applicable_components:
                continue

            full_payment = roll >= 0.75  # 25% partial, 35% full
            paid_on = today - timedelta(days=rng.randint(5, 90))

            if full_payment:
                allocations = [
                    {"component_id": c.id, "amount_paise": c.applied_paise}
                    for c in applicable_components
                ]
            else:
                # Partial: pay between 30% and 70% of final, spread across
                # the first 1-2 components.
                target_total = int(sf.final_paise * rng.uniform(0.3, 0.7))
                allocations = []
                remaining = target_total
                for c in applicable_components:
                    if remaining <= 0:
                        break
                    take = min(remaining, c.applied_paise)
                    if take <= 0:
                        continue
                    allocations.append({"component_id": c.id, "amount_paise": take})
                    remaining -= take
                if not allocations:
                    continue

            fees_services.record_payment(
                school=school,
                actor_id=admin_user.id if admin_user else None,  # type: ignore[arg-type]
                student_fee_id=sf.id,
                paid_on=paid_on,
                payment_mode=rng.choice(payment_modes),
                reference_number=f"REF{rng.randint(10000, 99999)}",
                notes="",
                allocations=allocations,
            )
            payments_made += 1

        # Final pass: recompute statuses so overdue catches any structures
        # whose components passed their due_date.
        fees_services.recompute_overdue_all(school=school)

        return {
            "structures": len(structures),
            "student_fees": StudentFee.objects.filter(school=school).count(),
            "payments": payments_made,
        }
