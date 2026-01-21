from datetime import datetime

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
from app.models.prediction_item import PredictionItem as PredictionItemModel
from app.models.user import User
from app.models.user_badge import UserBadge
from app.schemas.user import (
    AccuracyPoint,
    AccuracyTrend,
    BadgeCollection,
    BadgeItem,
    EpisodePredictions,
    NicknameUpdate,
    PrimaryBadgeUpdate,
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

    primary_badge = None
    if current_user.primary_badge_id:
        primary_badge = (
            db.query(BadgeMaster)
            .filter(BadgeMaster.id == current_user.primary_badge_id)
            .first()
        )

    return UserSummary(
        nickname=current_user.nickname,
        points=current_user.points,
        accuracy_rate=accuracy,
        participated_episodes=int(participated_episodes or 0),
        primary_badge_id=current_user.primary_badge_id,
        primary_badge_name=primary_badge.name if primary_badge else None,
        primary_badge_icon_url=primary_badge.icon_url if primary_badge else None,
    )


def _award_badges(db: Session, user: User) -> None:
    badge_names = [
        "연프 촉",
        "편집 읽는 사람",
        "역배 전문가",
        "분석왕",
        "초심자",
        "열정팬",
    ]
    badge_rows = (
        db.query(BadgeMaster)
        .filter(BadgeMaster.name.in_(badge_names))
        .all()
    )
    badge_by_name = {badge.name: badge for badge in badge_rows}
    if not badge_by_name:
        return

    existing_badges = {
        row.badge_id
        for row in db.query(UserBadge.badge_id)
        .filter(UserBadge.user_id == user.id)
        .all()
    }

    def add_badge(name: str) -> None:
        badge = badge_by_name.get(name)
        if not badge or badge.id in existing_badges:
            return
        db.add(UserBadge(user_id=user.id, badge_id=badge.id, earned_at=datetime.utcnow()))
        existing_badges.add(badge.id)

    has_prediction = (
        db.query(Prediction.id)
        .filter(Prediction.user_id == user.id)
        .first()
        is not None
    )
    if has_prediction:
        add_badge("초심자")

    season_couple_correct = (
        db.query(func.count(Prediction.id))
        .filter(
            Prediction.user_id == user.id,
            Prediction.prediction_type == "season_final_couple",
            Prediction.is_correct.is_(True),
        )
        .scalar()
    )
    if int(season_couple_correct or 0) >= 3:
        add_badge("연프 촉")

    special_items = (
        db.query(PredictionItemModel.id, PredictionItemModel.episode_id)
        .filter(
            PredictionItemModel.scope == "episode",
            PredictionItemModel.is_special.is_(True),
        )
        .all()
    )
    if special_items:
        special_by_episode: dict[int, list[int]] = {}
        for item_id, episode_id in special_items:
            if episode_id is None:
                continue
            special_by_episode.setdefault(int(episode_id), []).append(int(item_id))
        episode_ids = sorted(special_by_episode.keys())
        if episode_ids:
            episode_numbers = {
                row.id: row.episode_number
                for row in db.query(Episode.id, Episode.episode_number)
                .filter(Episode.id.in_(episode_ids))
                .all()
            }
            episode_ok: dict[int, bool] = {}
            for ep_id, item_ids in special_by_episode.items():
                rows = (
                    db.query(Prediction)
                    .filter(
                        Prediction.user_id == user.id,
                        Prediction.prediction_item_id.in_(item_ids),
                    )
                    .all()
                )
                if len(rows) != len(item_ids):
                    episode_ok[ep_id] = False
                    continue
                episode_ok[ep_id] = all(row.is_correct is True for row in rows)

            streak = 0
            last_ep_num = None
            for ep_id in episode_ids:
                ep_num = episode_numbers.get(ep_id)
                if ep_num is None:
                    continue
                if episode_ok.get(ep_id) is True:
                    if last_ep_num is None or ep_num == last_ep_num + 1:
                        streak += 1
                    else:
                        streak = 1
                    last_ep_num = ep_num
                else:
                    streak = 0
                    last_ep_num = ep_num
                if streak >= 5:
                    add_badge("편집 읽는 사람")
                    break

    total_counts = dict(
        db.query(Prediction.prediction_item_id, func.count(Prediction.id))
        .group_by(Prediction.prediction_item_id)
        .all()
    )
    value_counts = (
        db.query(
            Prediction.prediction_item_id,
            Prediction.selected_value,
            func.count(Prediction.id),
        )
        .group_by(Prediction.prediction_item_id, Prediction.selected_value)
        .all()
    )
    ratio_map: dict[tuple[int, str], float] = {}
    for item_id, selected_value, count in value_counts:
        if item_id is None:
            continue
        total = total_counts.get(item_id, 0)
        if total:
            ratio_map[(int(item_id), str(selected_value))] = count / total

    rare_correct = 0
    user_correct = (
        db.query(Prediction.prediction_item_id, Prediction.selected_value)
        .filter(Prediction.user_id == user.id, Prediction.is_correct.is_(True))
        .all()
    )
    for item_id, selected_value in user_correct:
        if item_id is None:
            continue
        ratio = ratio_map.get((int(item_id), str(selected_value)))
        if ratio is not None and ratio < 0.2:
            rare_correct += 1
    if rare_correct >= 3:
        add_badge("역배 전문가")

    analysis_items = (
        db.query(PredictionItemModel.id)
        .filter(PredictionItemModel.category.in_(["job_guess", "age_guess"]))
        .all()
    )
    analysis_item_ids = [int(row.id) for row in analysis_items]
    if analysis_item_ids:
        analysis_rows = (
            db.query(Prediction)
            .filter(
                Prediction.user_id == user.id,
                Prediction.prediction_item_id.in_(analysis_item_ids),
            )
            .all()
        )
        if len(analysis_rows) == len(analysis_item_ids) and all(
            row.is_correct is True for row in analysis_rows
        ):
            add_badge("분석왕")

    episode_item_ids = (
        db.query(PredictionItemModel.episode_id)
        .filter(PredictionItemModel.scope == "episode")
        .distinct()
        .all()
    )
    episode_ids = [int(row.episode_id) for row in episode_item_ids if row.episode_id]
    if episode_ids:
        user_episode_ids = (
            db.query(Prediction.episode_id)
            .filter(
                Prediction.user_id == user.id,
                Prediction.episode_id.in_(episode_ids),
            )
            .distinct()
            .all()
        )
        user_episode_set = {int(row.episode_id) for row in user_episode_ids if row.episode_id}
        if len(user_episode_set) == len(set(episode_ids)):
            add_badge("열정팬")

    db.commit()


@router.put("/users/me/nickname", response_model=UserSummary)
def update_nickname(
    payload: NicknameUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserSummary:
    current_user.nickname = payload.nickname
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

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

    primary_badge = None
    if current_user.primary_badge_id:
        primary_badge = (
            db.query(BadgeMaster)
            .filter(BadgeMaster.id == current_user.primary_badge_id)
            .first()
        )

    return UserSummary(
        nickname=current_user.nickname,
        points=current_user.points,
        accuracy_rate=accuracy,
        participated_episodes=int(participated_episodes or 0),
        primary_badge_id=current_user.primary_badge_id,
        primary_badge_name=primary_badge.name if primary_badge else None,
        primary_badge_icon_url=primary_badge.icon_url if primary_badge else None,
    )


@router.put("/users/me/primary-badge", response_model=UserSummary)
def update_primary_badge(
    payload: PrimaryBadgeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserSummary:
    owned = (
        db.query(UserBadge)
        .filter(
            UserBadge.user_id == current_user.id,
            UserBadge.badge_id == payload.badge_id,
        )
        .first()
    )
    if not owned:
        raise HTTPException(status_code=400, detail="Badge not owned")

    current_user.primary_badge_id = payload.badge_id
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

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

    primary_badge = (
        db.query(BadgeMaster)
        .filter(BadgeMaster.id == current_user.primary_badge_id)
        .first()
    )

    return UserSummary(
        nickname=current_user.nickname,
        points=current_user.points,
        accuracy_rate=accuracy,
        participated_episodes=int(participated_episodes or 0),
        primary_badge_id=current_user.primary_badge_id,
        primary_badge_name=primary_badge.name if primary_badge else None,
        primary_badge_icon_url=primary_badge.icon_url if primary_badge else None,
    )


@router.get("/users/me/badges", response_model=BadgeCollection)
def read_badges(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BadgeCollection:
    _award_badges(db, current_user)
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
            Prediction.prediction_item_id,
            Prediction.prediction_type,
            PredictionItemModel.question_text,
            PredictionItemModel.category,
            Prediction.target_participant_id,
            Prediction.selected_value,
            Prediction.betting_points,
            Prediction.is_correct,
            case(
                (Prediction.is_correct.is_(True), Prediction.betting_points),
                else_=0,
            ).label("earned_points"),
        )
        .outerjoin(
            PredictionItemModel,
            Prediction.prediction_item_id == PredictionItemModel.id,
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
                prediction_item_id=row.prediction_item_id,
                prediction_type=row.prediction_type,
                question_text=row.question_text,
                category=row.category,
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
