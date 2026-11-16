from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.districts import router as districts_router
from app.api.v1.observations import router as observations_router
from app.api.v1.reports import router as reports_router
from app.api.v1.flowers import router as flowers_router
from app.api.v1.plants import router as plants_router
from app.api.v1.identifications import router as identifications_router
from app.api.v1.identification_history import router as identification_history_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(districts_router)
api_router.include_router(observations_router)
api_router.include_router(reports_router)
api_router.include_router(flowers_router)
api_router.include_router(plants_router)
api_router.include_router(identifications_router)
api_router.include_router(identification_history_router)
