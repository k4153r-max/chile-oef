from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from chile_oef import __version__
from chile_oef.app.api.routes import router
from chile_oef.app.settings import get_settings

settings = get_settings()
app = FastAPI(
    title="CHILE-OEF",
    version=__version__,
    description=(
        "Experimental probabilistic earthquake-occurrence forecasting research platform. "
        "Not an official alert or deterministic prediction service."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)
