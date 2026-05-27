"""Django Ninja root API — mounts each app's router under /api/v1/."""

from ninja import NinjaAPI

from apps.academics.api import router as academics_router
from apps.academics.teacher_api import router as teacher_classes_router
from apps.accounts.api import router as accounts_router
from apps.accounts.parent_api import profile_router as parent_profile_router
from apps.accounts.parent_api import router as parent_accounts_router
from apps.accounts.teacher_api import profile_router as teacher_profile_router
from apps.accounts.teacher_api import router as teacher_accounts_router
from apps.attendance.api import router as attendance_router
from apps.attendance.parent_api import router as parent_attendance_router
from apps.attendance.teacher_api import router as teacher_attendance_router
from apps.core.exceptions import register_exception_handlers
from apps.exams.api import router as exams_router
from apps.exams.parent_api import router as parent_marks_router
from apps.exams.teacher_api import router as teacher_tests_router
from apps.fees.api import router as fees_router
from apps.fees.parent_api import router as parent_fees_router
from apps.people.api import router as people_router
from apps.people.parent_api import router as parent_feed_router
from apps.people.teacher_api import router as teacher_students_router
from apps.schools.api import router as schools_router

api = NinjaAPI(
    title="Skooly API",
    version="1.0.0",
    description="Skooly — school management platform API (admin / skooly-stride).",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

api.add_router("/auth/", accounts_router)
api.add_router("/schools/", schools_router)
api.add_router("/", people_router)
api.add_router("/", academics_router)
api.add_router("/", attendance_router)
api.add_router("/", exams_router)
api.add_router("/", fees_router)

register_exception_handlers(api)


# ---------------------------------------------------------------------------
# Teacher API (skooly-guru) — mounted at /api/v1/teacher/.
#
# A separate NinjaAPI instance so teacher routes never collide with the admin
# routes above (same paths, different shapes). Every teacher router locks to
# TeacherJWTAuth, so only teacher tokens can reach it. Routers are registered
# here as each teacher sub-phase lands.
# ---------------------------------------------------------------------------
teacher_api = NinjaAPI(
    title="Skooly Teacher API",
    version="teacher-1.0.0",
    description="Skooly — teacher mobile app (skooly-guru) API.",
    urls_namespace="teacher",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

teacher_api.add_router("/auth/", teacher_accounts_router)
teacher_api.add_router("/", teacher_profile_router)
teacher_api.add_router("/", teacher_classes_router)
teacher_api.add_router("/", teacher_students_router)
teacher_api.add_router("/", teacher_attendance_router)
teacher_api.add_router("/", teacher_tests_router)

register_exception_handlers(teacher_api)


# ---------------------------------------------------------------------------
# Parent API (skooly-parent) — mounted at /api/v1/parent/.
#
# A third NinjaAPI instance, same rationale as the teacher one: every router
# locks to ParentJWTAuth so only parent tokens reach it, and child-scoped
# endpoints resolve the Student through the authenticated parent's links.
# ---------------------------------------------------------------------------
parent_api = NinjaAPI(
    title="Skooly Parent API",
    version="parent-1.0.0",
    description="Skooly — parent mobile app (skooly-parent) API.",
    urls_namespace="parent",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

parent_api.add_router("/auth/", parent_accounts_router)
parent_api.add_router("/", parent_profile_router)
parent_api.add_router("/", parent_feed_router)
parent_api.add_router("/", parent_attendance_router)
parent_api.add_router("/", parent_marks_router)
parent_api.add_router("/", parent_fees_router)

register_exception_handlers(parent_api)
