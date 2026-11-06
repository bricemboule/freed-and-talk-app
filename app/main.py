"""Point d'entrée de l'API : configuration, routes et gestion des erreurs."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import get_settings
from app.modules.auth.api.routes import router as auth_router, users_router
from app.modules.psychologists.routes import router as profiles_router
from app.modules.appointments.routes import router as appointments_router
from app.modules.communication.routes import router as communication_router
from app.modules.content.routes import router as content_router
from app.modules.reviews.routes import router as reviews_router
from app.modules.search.routes import router as search_router
from app.modules.administration.routes import router as administration_router
from app.modules.payments.routes import router as payments_router


# Charger les paramètres définis dans .env ou leurs valeurs par défaut.
settings = get_settings()

app = FastAPI(
    title="FREE & TALK API",
    version="1.0.0",
)

# Autoriser le navigateur à appeler l'API depuis les sites configurés.
allowed_origins = [origin.strip() for origin in settings.cors_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Les routes métier sont définies dans le module d'authentification.
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(profiles_router)
app.include_router(appointments_router)
app.include_router(communication_router)
app.include_router(content_router)
app.include_router(reviews_router)
app.include_router(search_router)
app.include_router(administration_router)
app.include_router(payments_router)


@app.exception_handler(RequestValidationError)
async def validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Identifier les champs invalides sans exposer les données reçues."""
    messages = {
        "missing": "Champ obligatoire.",
        "string_too_short": "Texte trop court.",
        "string_too_long": "Texte trop long.",
        "string_type": "Une chaîne de caractères est attendue.",
        "string_pattern_mismatch": "Format invalide.",
        "json_invalid": "Le corps de la requête doit être un JSON valide.",
    }
    details = []
    for error in exc.errors():
        location = error.get("loc", ())
        field = ".".join(str(part) for part in location)
        message = messages.get(error["type"], "Valeur invalide.")
        if location == ("body", "phone"):
            message = "Utilisez le format international, par exemple +237600000000, ou null."
        elif location == ("body", "email") and error["type"] != "missing":
            message = "Adresse email invalide."
        if error["type"] in ("string_too_short", "string_too_long"):
            bounds = error.get("ctx", {})
            if "min_length" in bounds:
                message = f"Au moins {bounds['min_length']} caractères requis."
            elif "max_length" in bounds:
                message = f"Au maximum {bounds['max_length']} caractères autorisés."
        details.append({"field": field, "code": error["type"], "message": message})

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Données invalides",
                "details": details,
            }
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Confirmer que l'API répond, sans vérifier la base de données."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """Rediriger la page d'accueil vers la documentation interactive Swagger."""
    return RedirectResponse("/docs")
