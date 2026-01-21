from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.endpoints.users import get_current_user
from app.db.session import get_db
from app.models.episode import Episode
from app.models.participant import Participant
from app.models.prediction import Prediction
from app.models.prediction_item import PredictionItem
from app.models.user import User
from app.schemas.prediction import (
    AdminEpisodeResultsSubmit,
    AdminSeasonCouplesSubmit,
    AdminSeasonFinalSubmit,
    EpisodePredictionsSubmit,
    PredictionAnswer,
    PredictionsOverview,
    SeasonCouplePair,
    SeasonCouplesSubmit,
    SeasonFinalVoteSubmit,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _next_episode(db: Session) -> Episode | None:
    now = _utcnow()
    return (
        db.query(Episode)
        .filter(Episode.start_time > now)
        .order_by(Episode.start_time.asc())
        .first()
    )


def _season_start_open(db: Session) -> bool:
    now = _utcnow()
    ep1 = db.query(Episode).filter(Episode.id == 1).first()
    if not ep1:
        return False
    ep2 = db.query(Episode).filter(Episode.id == 2).first()
    return now >= ep1.start_time and (ep2 is None or now < ep2.start_time)


def _season_episode_id(db: Session, fallback_id: int | None) -> int:
    ep1 = db.query(Episode).filter(Episode.id == 1).first()
    if ep1:
        return ep1.id
    if fallback_id:
        return fallback_id
    return 1


def _ensure_admin(current_user: User) -> None:
    if current_user.id != 1:
        raise HTTPException(status_code=403, detail="Admin only")


def _apply_prediction_result(
    db: Session,
    prediction: Prediction,
    is_correct: bool,
    points: int,
) -> None:
    earned = points if is_correct else 0
    delta = earned - int(prediction.earned_points or 0)
    prediction.is_correct = is_correct
    prediction.earned_points = earned
    if delta:
        user = db.query(User).filter(User.id == prediction.user_id).first()
        if user:
            user.points = int(user.points or 0) + delta
            db.add(user)
    db.add(prediction)


def _season_final_vote_open(db: Session) -> bool:
    items = (
        db.query(PredictionItem)
        .filter(
            PredictionItem.scope == "season",
            PredictionItem.category.in_(["final_zero_vote", "season_popular_one"]),
        )
        .all()
    )
    return len(items) > 0


def _season_item_id(db: Session, category: str) -> int:
    item = (
        db.query(PredictionItem)
        .filter(
            PredictionItem.scope == "season",
            PredictionItem.category == category,
        )
        .order_by(PredictionItem.id.asc())
        .first()
    )
    if not item:
        raise HTTPException(
            status_code=400,
            detail=f"Missing season prediction item: {category}",
        )
    return item.id


@router.get("/predictions/overview", response_model=PredictionsOverview)
def get_predictions_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PredictionsOverview:
    next_episode = _next_episode(db)
    season_start_open = _season_start_open(db)
    season_final_vote_open = _season_final_vote_open(db)

    participants = db.query(Participant).order_by(Participant.id.asc()).all()

    season_episode_id = _season_episode_id(db, next_episode.id if next_episode else None)
    season_predictions = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.prediction_type == "season_final_couple",
            Prediction.episode_id == season_episode_id,
        )
        .all()
    )
    season_couples: list[SeasonCouplePair] = []
    for prediction in season_predictions:
        try:
            female_id, male_id = prediction.selected_value.split(":")
            season_couples.append(
                SeasonCouplePair(
                    female_id=int(female_id),
                    male_id=int(male_id),
                )
            )
        except ValueError:
            continue

    season_couples_locked = len(season_couples) > 0

    episode_items = []
    if next_episode:
        episode_items = (
            db.query(PredictionItem)
            .filter(
                PredictionItem.scope == "episode",
                PredictionItem.episode_id == next_episode.id,
            )
            .order_by(PredictionItem.id.asc())
            .all()
        )
    episode_answers = []
    if next_episode:
        episode_answers = [
            PredictionAnswer(
                prediction_item_id=row.prediction_item_id,
                selected_value=row.selected_value,
                target_participant_id=row.target_participant_id,
            )
            for row in db.query(Prediction)
            .filter(
                Prediction.user_id == current_user.id,
                Prediction.episode_id == next_episode.id,
            )
            .all()
        ]
    episode_predictions_locked = False
    if next_episode:
        episode_predictions_locked = (
            db.query(Prediction)
            .filter(
                Prediction.user_id == current_user.id,
                Prediction.episode_id == next_episode.id,
            )
            .first()
            is not None
        )

    final_zero_vote = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.prediction_type == "season_final_zero",
        )
        .first()
    )
    popular_one = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.prediction_type == "season_popular_one",
        )
        .first()
    )

    return PredictionsOverview(
        next_episode=next_episode,
        is_admin=current_user.id == 1,
        season_start_open=season_start_open,
        season_final_vote_open=season_final_vote_open,
        season_couples_locked=season_couples_locked,
        season_couples=season_couples,
        episode_predictions_locked=episode_predictions_locked,
        participants=participants,
        episode_items=episode_items,
        episode_answers=episode_answers,
        season_final_zero_vote=int(final_zero_vote.selected_value)
        if final_zero_vote
        else None,
        season_popular_one=int(popular_one.selected_value) if popular_one else None,
    )


@router.post("/predictions/season-couples", status_code=status.HTTP_201_CREATED)
def submit_season_couples(
    payload: SeasonCouplesSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not _season_start_open(db):
        raise HTTPException(status_code=403, detail="Season start prediction is closed")

    next_episode = _next_episode(db)
    season_episode_id = _season_episode_id(db, next_episode.id if next_episode else None)
    season_item_id = _season_item_id(db, "season_final_couple")

    existing = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.prediction_type == "season_final_couple",
            Prediction.episode_id == season_episode_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Season couples already submitted")

    participants = {
        participant.id: participant for participant in db.query(Participant).all()
    }
    used_ids: set[int] = set()

    for pair in payload.pairs:
        female = participants.get(pair.female_id)
        male = participants.get(pair.male_id)
        if not female or not male:
            raise HTTPException(status_code=400, detail="Invalid participant in pair")
        if female.gender == male.gender:
            raise HTTPException(status_code=400, detail="Pair must be different genders")
        if pair.female_id in used_ids or pair.male_id in used_ids:
            raise HTTPException(status_code=400, detail="Duplicate participant in pairs")
        used_ids.add(pair.female_id)
        used_ids.add(pair.male_id)

        db.add(
            Prediction(
                user_id=current_user.id,
                episode_id=season_episode_id,
                prediction_item_id=season_item_id,
                prediction_type="season_final_couple",
                target_participant_id=pair.male_id,
                selected_value=f"{pair.female_id}:{pair.male_id}",
            )
        )

    db.commit()
    return {"status": "ok"}


@router.post("/predictions/season-final", status_code=status.HTTP_201_CREATED)
def submit_season_final_votes(
    payload: SeasonFinalVoteSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not _season_final_vote_open(db):
        raise HTTPException(status_code=403, detail="Final vote is closed")

    if payload.final_zero_vote_participant_id is None or payload.season_popular_participant_id is None:
        raise HTTPException(status_code=400, detail="Both votes are required")

    participants = {
        participant.id: participant for participant in db.query(Participant).all()
    }
    if payload.final_zero_vote_participant_id not in participants:
        raise HTTPException(status_code=400, detail="Invalid zero-vote participant")
    if payload.season_popular_participant_id not in participants:
        raise HTTPException(status_code=400, detail="Invalid popular participant")

    existing_zero = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.prediction_type == "season_final_zero",
        )
        .first()
    )
    existing_popular = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.prediction_type == "season_popular_one",
        )
        .first()
    )
    if existing_zero or existing_popular:
        raise HTTPException(status_code=409, detail="Final votes already submitted")

    season_episode_id = _season_episode_id(db, None)
    final_zero_item_id = _season_item_id(db, "final_zero_vote")
    popular_one_item_id = _season_item_id(db, "season_popular_one")

    db.add(
        Prediction(
            user_id=current_user.id,
            episode_id=season_episode_id,
            prediction_item_id=final_zero_item_id,
            prediction_type="season_final_zero",
            target_participant_id=payload.final_zero_vote_participant_id,
            selected_value=str(payload.final_zero_vote_participant_id),
        )
    )
    db.add(
        Prediction(
            user_id=current_user.id,
            episode_id=season_episode_id,
            prediction_item_id=popular_one_item_id,
            prediction_type="season_popular_one",
            target_participant_id=payload.season_popular_participant_id,
            selected_value=str(payload.season_popular_participant_id),
        )
    )
    db.commit()
    return {"status": "ok"}


@router.post("/predictions/episode", status_code=status.HTTP_201_CREATED)
def submit_episode_predictions(
    payload: EpisodePredictionsSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    items = (
        db.query(PredictionItem)
        .filter(
            PredictionItem.id.in_([answer.prediction_item_id for answer in payload.answers]),
            PredictionItem.scope == "episode",
            PredictionItem.episode_id == payload.episode_id,
        )
        .all()
    )
    found_ids = {item.id for item in items}
    if found_ids != {answer.prediction_item_id for answer in payload.answers}:
        raise HTTPException(status_code=400, detail="Invalid prediction items")

    existing = (
        db.query(Prediction)
        .filter(
            Prediction.user_id == current_user.id,
            Prediction.episode_id == payload.episode_id,
            Prediction.prediction_item_id.in_([a.prediction_item_id for a in payload.answers]),
        )
        .all()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Predictions already submitted")

    for answer in payload.answers:
        db.add(
            Prediction(
                user_id=current_user.id,
                episode_id=payload.episode_id,
                prediction_item_id=answer.prediction_item_id,
                prediction_type="episode_prediction",
                target_participant_id=answer.target_participant_id,
                selected_value=answer.selected_value,
            )
        )
    db.commit()
    return {"status": "ok"}


@router.post("/predictions/admin/season-couples", status_code=status.HTTP_201_CREATED)
def submit_admin_season_couples(
    payload: AdminSeasonCouplesSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_admin(current_user)
    season_episode_id = _season_episode_id(db, None)
    correct_pairs = {f"{pair.female_id}:{pair.male_id}" for pair in payload.pairs}
    episode = db.query(Episode).filter(Episode.id == season_episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    data = dict(episode.result_data or {})
    data["season_final_couple"] = list(correct_pairs)
    episode.result_data = data
    db.add(episode)

    predictions = (
        db.query(Prediction)
        .filter(
            Prediction.prediction_type == "season_final_couple",
            Prediction.episode_id == season_episode_id,
        )
        .all()
    )
    for prediction in predictions:
        _apply_prediction_result(
            db,
            prediction,
            prediction.selected_value in correct_pairs,
            100,
        )
    db.commit()
    return {"status": "ok"}


@router.post("/predictions/admin/season-final", status_code=status.HTTP_201_CREATED)
def submit_admin_season_final(
    payload: AdminSeasonFinalSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_admin(current_user)
    season_episode_id = _season_episode_id(db, None)
    episode = db.query(Episode).filter(Episode.id == season_episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    data = dict(episode.result_data or {})
    if payload.final_zero_vote_participant_id is not None:
        data["season_final_zero"] = str(payload.final_zero_vote_participant_id)
    if payload.season_popular_participant_id is not None:
        data["season_popular_one"] = str(payload.season_popular_participant_id)
    episode.result_data = data
    db.add(episode)

    if payload.final_zero_vote_participant_id is not None:
        predictions = (
            db.query(Prediction)
            .filter(Prediction.prediction_type == "season_final_zero")
            .all()
        )
        for prediction in predictions:
            _apply_prediction_result(
                db,
                prediction,
                prediction.selected_value == str(payload.final_zero_vote_participant_id),
                50,
            )
    if payload.season_popular_participant_id is not None:
        predictions = (
            db.query(Prediction)
            .filter(Prediction.prediction_type == "season_popular_one")
            .all()
        )
        for prediction in predictions:
            _apply_prediction_result(
                db,
                prediction,
                prediction.selected_value == str(payload.season_popular_participant_id),
                50,
            )

    db.commit()
    return {"status": "ok"}


@router.post("/predictions/admin/episode", status_code=status.HTTP_201_CREATED)
def submit_admin_episode_results(
    payload: AdminEpisodeResultsSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_admin(current_user)
    items = (
        db.query(PredictionItem)
        .filter(
            PredictionItem.id.in_([answer.prediction_item_id for answer in payload.answers]),
            PredictionItem.scope == "episode",
            PredictionItem.episode_id == payload.episode_id,
        )
        .all()
    )
    item_by_id = {item.id: item for item in items}
    if len(item_by_id) != len({answer.prediction_item_id for answer in payload.answers}):
        raise HTTPException(status_code=400, detail="Invalid prediction items")

    episode = db.query(Episode).filter(Episode.id == payload.episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    data = dict(episode.result_data or {})

    message_pairs: List[str] = []
    like_up_value: Optional[str] = None
    like_down_value: Optional[str] = None
    special_values: Dict[str, str] = {}

    for answer in payload.answers:
        item = item_by_id.get(answer.prediction_item_id)
        if not item:
            continue
        if item.category == "message_target":
            message_pairs.append(answer.selected_value)
        elif item.category == "like_up":
            like_up_value = answer.selected_value
        elif item.category == "like_down":
            like_down_value = answer.selected_value
        elif item.is_special:
            special_values[str(answer.prediction_item_id)] = answer.selected_value

    if message_pairs:
        data["message_target"] = message_pairs
    if like_up_value is not None:
        data["like_up"] = like_up_value
    if like_down_value is not None:
        data["like_down"] = like_down_value
    if special_values:
        data["special"] = special_values

    episode.result_data = data
    db.add(episode)

    if message_pairs:
        message_item_ids = [
            item.id for item in item_by_id.values() if item.category == "message_target"
        ]
        predictions = (
            db.query(Prediction)
            .filter(
                Prediction.prediction_item_id.in_(message_item_ids),
                Prediction.episode_id == payload.episode_id,
            )
            .all()
        )
        correct_pairs = set(message_pairs)
        for prediction in predictions:
            _apply_prediction_result(
                db,
                prediction,
                prediction.selected_value in correct_pairs,
                10,
            )

    if like_up_value is not None:
        like_up_items = [item.id for item in item_by_id.values() if item.category == "like_up"]
        predictions = (
            db.query(Prediction)
            .filter(
                Prediction.prediction_item_id.in_(like_up_items),
                Prediction.episode_id == payload.episode_id,
            )
            .all()
        )
        for prediction in predictions:
            _apply_prediction_result(
                db,
                prediction,
                prediction.selected_value == like_up_value,
                20,
            )

    if like_down_value is not None:
        like_down_items = [
            item.id for item in item_by_id.values() if item.category == "like_down"
        ]
        predictions = (
            db.query(Prediction)
            .filter(
                Prediction.prediction_item_id.in_(like_down_items),
                Prediction.episode_id == payload.episode_id,
            )
            .all()
        )
        for prediction in predictions:
            _apply_prediction_result(
                db,
                prediction,
                prediction.selected_value == like_down_value,
                20,
            )

    if special_values:
        special_item_ids = [
            item.id for item in item_by_id.values() if item.is_special
        ]
        predictions = (
            db.query(Prediction)
            .filter(
                Prediction.prediction_item_id.in_(special_item_ids),
                Prediction.episode_id == payload.episode_id,
            )
            .all()
        )
        for prediction in predictions:
            correct = special_values.get(str(prediction.prediction_item_id))
            _apply_prediction_result(
                db,
                prediction,
                prediction.selected_value == correct,
                int(prediction.betting_points or 0),
            )

    db.commit()
    return {"status": "ok"}
