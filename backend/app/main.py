from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    admin_l3_rerun as admin_l3_rerun_router,
)
from app.api.routers import (
    admin_negative_area as admin_negative_area_router,
)
from app.api.routers import (
    admin_rules as admin_rules_router,
)
from app.api.routers import (
    mrp_catalogue as mrp_catalogue_router,
)
from app.api.routers import (
    auth as auth_router,
)
from app.api.routers import (
    cam_discrepancies as cam_discrepancies_router,
)
from app.api.routers import (
    cases as cases_router,
)
from app.api.routers import (
    dedupe_snapshots as dedupe_snapshots_router,
)
from app.api.routers import (
    health,
)
from app.api.routers import (
    incomplete_autorun as incomplete_autorun_router,
)
from app.api.routers import (
    notifications as notifications_router,
)
from app.api.routers import (
    users as users_router,
)
from app.api.routers import (
    verification as verification_router,
)
from app.config import get_settings
from app.startup import init_aws_resources


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    # await init_aws_resources()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PFL Credit AI", version="0.2.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(cases_router.router)
    app.include_router(cam_discrepancies_router.router)
    app.include_router(dedupe_snapshots_router.router)
    app.include_router(verification_router.router)
    app.include_router(verification_router.md_router)
    app.include_router(notifications_router.router)
    app.include_router(admin_rules_router.router)
    app.include_router(admin_l3_rerun_router.router)
    app.include_router(admin_negative_area_router.router)
    app.include_router(mrp_catalogue_router.router)
    app.include_router(incomplete_autorun_router.case_router)
    app.include_router(incomplete_autorun_router.admin_router)
    return app


app = create_app()


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "pfl-credit-ai", "status": "ok"}
