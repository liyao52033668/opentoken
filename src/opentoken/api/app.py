from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from opentoken.api.auth import maybe_require_api_key
from opentoken.api.routes.chat import router as chat_router
from opentoken.api.routes.embeddings import router as embeddings_router
from opentoken.api.routes.files import router as files_router
from opentoken.api.routes.health import router as health_router
from opentoken.api.routes.models import router as models_router
from opentoken.api.routes.responses import router as responses_router
from opentoken.api.routes.uploads import router as uploads_router


def create_app() -> FastAPI:
    app = FastAPI(title="OpenToken")

    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        rejection = maybe_require_api_key(request)
        if rejection is not None:
            return rejection
        return await call_next(request)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": str(exc),
                    "type": "internal_server_error",
                }
            },
        )

    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(files_router)
    app.include_router(uploads_router)
    app.include_router(embeddings_router)
    app.include_router(chat_router)
    app.include_router(responses_router)
    return app
