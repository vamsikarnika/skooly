"""Django Ninja root API — mounts each app's router under /api/v1/."""

from ninja import NinjaAPI

from apps.academics.api import router as academics_router
from apps.accounts.api import router as accounts_router
from apps.attendance.api import router as attendance_router
from apps.core.exceptions import register_exception_handlers
from apps.exams.api import router as exams_router
from apps.fees.api import router as fees_router
from apps.people.api import router as people_router
from apps.schools.api import router as schools_router

api = NinjaAPI(
    title="Skooly API",
    version="1.0.0",
    description="Skooly — school management platform API.",
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
