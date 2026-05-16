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
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.academics.models import (
    Class,
    Section,
    StudentEnrollment,
    Subject,
    SubjectClassMapping,
    TeacherAssignment,
)
from apps.accounts.models import User
from apps.core.context import use_school
from apps.people.models import Gender, Relation, Student, StudentStatus, Teacher
from apps.schools.models import AcademicYear, Board, School

SCHOOL_NAME = "Vidya Bharati High School"
SCHOOL_PHONE = "+919876543210"
ADMIN_PASSWORD = "demo1234"

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

                total_students = 0
                for cls_name, sections in classes_map.items():
                    for sec in sections:
                        count = rng.randint(STUDENTS_PER_SECTION - 3, STUDENTS_PER_SECTION + 3)
                        self._seed_section_students(
                            rng, school, year, sec, count, cls_name
                        )
                        total_students += count
                self.stdout.write(self.style.SUCCESS(f"  ✓ students: {total_students}"))

        self.stdout.write(self.style.SUCCESS("Demo seed complete."))

    # --- Helpers ----------------------------------------------------------------

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
