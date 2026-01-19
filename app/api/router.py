from fastapi import APIRouter

from app.api.endpoints import auth, chat, predictions, rankings, users

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(users.router, tags=["users"])
api_router.include_router(predictions.router, tags=["predictions"])
api_router.include_router(rankings.router, tags=["rankings"])
api_router.include_router(chat.router, tags=["chat"])
