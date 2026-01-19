from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.badge import BadgeMaster
from app.models.chat import Chat
from app.models.user import User
from app.api.endpoints.users import get_current_user
from app.schemas.chat import ChatHistory, ChatMessage

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict) -> None:
        for connection in list(self.active_connections):
            await connection.send_json(message)


manager = ConnectionManager()


def _get_user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/chats", response_model=ChatHistory)
def read_chat_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
) -> ChatHistory:
    return ChatHistory(messages=_fetch_chat_messages(db, limit))


def _fetch_chat_messages(db: Session, limit: int) -> List[ChatMessage]:
    rows = (
        db.query(
            Chat.id,
            Chat.user_id,
            Chat.content,
            Chat.created_at,
            User.nickname,
            BadgeMaster.icon_url,
            BadgeMaster.name,
        )
        .join(User, User.id == Chat.user_id)
        .outerjoin(BadgeMaster, BadgeMaster.id == User.primary_badge_id)
        .order_by(Chat.created_at.desc())
        .limit(limit)
        .all()
    )

    messages = [
        ChatMessage(
            id=row.id,
            user_id=row.user_id,
            nickname=row.nickname,
            content=row.content,
            created_at=row.created_at,
            primary_badge_icon_url=row.icon_url,
            primary_badge_name=row.name,
        )
        for row in rows
    ]
    messages.reverse()
    return messages


@router.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = next(get_db())
    try:
        user = _get_user_from_token(db, token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)

    badge = None
    if user.primary_badge_id:
        badge = (
            db.query(BadgeMaster)
            .filter(BadgeMaster.id == user.primary_badge_id)
            .first()
        )

    try:
        while True:
            data = await websocket.receive_json()
            content = data.get("content")
            if not content:
                continue

            chat = Chat(user_id=user.id, content=content, created_at=datetime.utcnow())
            db.add(chat)
            db.commit()
            db.refresh(chat)

            payload = ChatMessage(
                id=chat.id,
                user_id=user.id,
                nickname=user.nickname,
                content=chat.content,
                created_at=chat.created_at,
                primary_badge_icon_url=badge.icon_url if badge else None,
                primary_badge_name=badge.name if badge else None,
            )
            await manager.broadcast(payload.model_dump(mode="json"))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        db.close()
