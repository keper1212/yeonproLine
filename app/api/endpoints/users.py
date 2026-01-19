from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.badge import BadgeMaster
from app.models.episode import Episode
from app.models.prediction import Prediction
from app.models.user import User
from app.models.user_badge import UserBadge
from app.schemas.user import (
    AccuracyPoint,
    AccuracyTrend,
    BadgeCollection,
    BadgeItem,
    EpisodePredictions,
    PredictionHistory,
    PredictionItem,
    UserSummary,
)

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/users/me", response_model=UserSummary)
def read_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserSummary:
    scored_counts = (
        db.query(
            func.coalesce(
                func.sum(
                    case((Prediction.is_correct.is_(True), 1), else_=0)
                ),
                0,
            ).label("correct"),
            func.coalesce(
                func.sum(
                    case((Prediction.is_correct.isnot(None), 1), else_=0)
                ),
                0,
            ).label("total"),
        )
        .filter(Prediction.user_id == current_user.id)
        .one()
    )
    participated_episodes = (
        db.query(func.count(func.distinct(Prediction.episode_id)))
        .filter(Prediction.user_id == current_user.id)
        .scalar()
    )

    total = int(scored_counts.total or 0)
    correct = int(scored_counts.correct or 0)
    accuracy = round((correct / total) * 100, 2) if total else 0.0

    return UserSummary(
        nickname=current_user.nickname,
        points=current_user.points,
        accuracy_rate=accuracy,
        participated_episodes=int(participated_episodes or 0),
    )


@router.get("/users/me/badges", response_model=BadgeCollection)
def read_badges(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BadgeCollection:
    rows = (
        db.query(BadgeMaster, UserBadge.earned_at)
        .outerjoin(
            UserBadge,
            (UserBadge.badge_id == BadgeMaster.id)
            & (UserBadge.user_id == current_user.id),
        )
        .order_by(BadgeMaster.id)
        .all()
    )

    return BadgeCollection(
        badges=[
            BadgeItem(
                id=badge.id,
                name=badge.name,
                description=badge.description,
                icon_url=badge.icon_url,
                is_owned=earned_at is not None,
                earned_at=earned_at,
            )
            for badge, earned_at in rows
        ]
    )


@router.get("/users/me/stats/accuracy", response_model=AccuracyTrend)
def read_accuracy_trend(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccuracyTrend:
    rows = (
        db.query(
            Episode.id.label("episode_id"),
            func.coalesce(
                func.sum(
                    case((Prediction.is_correct.is_(True), 1), else_=0)
                ),
                0,
            ).label("correct"),
            func.coalesce(
                func.sum(
                    case((Prediction.is_correct.isnot(None), 1), else_=0)
                ),
                0,
            ).label("total"),
        )
        .join(Prediction, Prediction.episode_id == Episode.id)
        .filter(Prediction.user_id == current_user.id)
        .group_by(Episode.id)
        .order_by(Episode.id)
        .all()
    )

    points = []
    for row in rows:
        total = int(row.total or 0)
        correct = int(row.correct or 0)
        accuracy = round((correct / total) * 100, 2) if total else 0.0
        points.append(
            AccuracyPoint(
                episode_id=row.episode_id,
                accuracy_rate=accuracy,
                correct_predictions=correct,
                total_predictions=total,
            )
        )

    return AccuracyTrend(points=points)


@router.get("/users/me/predictions", response_model=PredictionHistory)
def read_prediction_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PredictionHistory:
    rows = (
        db.query(
            Prediction.id,
            Prediction.episode_id,
            Prediction.prediction_type,
            Prediction.target_participant_id,
            Prediction.selected_value,
            Prediction.betting_points,
            Prediction.is_correct,
            case(
                (Prediction.is_correct.is_(True), Prediction.betting_points),
                else_=0,
            ).label("earned_points"),
        )
        .filter(Prediction.user_id == current_user.id)
        .order_by(Prediction.episode_id, Prediction.id)
        .all()
    )

    episodes_map = {}
    for row in rows:
        if row.episode_id not in episodes_map:
            episodes_map[row.episode_id] = []
        episodes_map[row.episode_id].append(
            PredictionItem(
                id=row.id,
                prediction_type=row.prediction_type,
                target_participant_id=row.target_participant_id,
                selected_value=row.selected_value,
                betting_points=row.betting_points,
                is_correct=row.is_correct,
                earned_points=int(row.earned_points or 0),
            )
        )

    episodes = [
        EpisodePredictions(episode_id=episode_id, predictions=predictions)
        for episode_id, predictions in episodes_map.items()
    ]

    return PredictionHistory(episodes=episodes)
