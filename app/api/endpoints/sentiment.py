from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.sentiment import ParticipantSummary, SentimentEvent, SentimentOverview, SentimentPoint

router = APIRouter()


def _build_condition(
    female_id: Optional[int],
    male_id: Optional[int],
    target_id: Optional[int],
) -> tuple[str, dict]:
    if target_id and (female_id or male_id):
        raise HTTPException(status_code=400, detail="target_id와 female_id/male_id는 동시에 사용할 수 없습니다.")
    if target_id:
        return (
            "target_participant_id = :target_id AND female_id IS NULL AND male_id IS NULL",
            {"target_id": target_id},
        )
    if female_id is None or male_id is None:
        raise HTTPException(status_code=400, detail="커플 분석에는 female_id와 male_id가 모두 필요합니다.")
    return (
        "female_id = :female_id AND male_id = :male_id AND target_participant_id IS NULL",
        {"female_id": female_id, "male_id": male_id},
    )


def _fetch_overview(
    db: Session,
    condition: str,
    params: dict,
    history_limit: int,
):
    latest_row = db.execute(
        text(
            "SELECT support_rate, delta_5m, captured_at "
            "FROM sentiment_snapshots "
            f"WHERE {condition} "
            "ORDER BY captured_at DESC LIMIT 1"
        ),
        params,
    ).fetchone()

    history_rows = db.execute(
        text(
            "SELECT captured_at, support_rate "
            "FROM sentiment_snapshots "
            f"WHERE {condition} "
            "ORDER BY captured_at DESC LIMIT :limit"
        ),
        {**params, "limit": history_limit},
    ).fetchall()

    summary_row = db.execute(
        text(
            "SELECT summary_text "
            "FROM sentiment_summaries "
            f"WHERE {condition} "
            "ORDER BY generated_at DESC LIMIT 1"
        ),
        params,
    ).fetchone()

    event_row = db.execute(
        text(
            "SELECT event_type, delta, start_at, end_at "
            "FROM sentiment_events "
            f"WHERE {condition} "
            "ORDER BY end_at DESC LIMIT 1"
        ),
        params,
    ).fetchone()

    return latest_row, history_rows, summary_row, event_row


@router.get("/sentiment/participants", response_model=List[ParticipantSummary])
def read_sentiment_participants(db: Session = Depends(get_db)) -> List[ParticipantSummary]:
    rows = db.execute(
        text("SELECT id, name, gender, image_url FROM participants ORDER BY id ASC")
    ).fetchall()
    return [
        ParticipantSummary(
            id=row.id,
            name=row.name,
            gender=row.gender,
            image_url=row.image_url,
        )
        for row in rows
    ]


@router.get("/sentiment/overview", response_model=SentimentOverview)
def read_sentiment_overview(
    female_id: Optional[int] = Query(default=None),
    male_id: Optional[int] = Query(default=None),
    target_id: Optional[int] = Query(default=None),
    history_limit: int = Query(default=12, ge=2, le=120),
    db: Session = Depends(get_db),
) -> SentimentOverview:
    condition, params = _build_condition(female_id, male_id, target_id)
    resolved_female_id = female_id
    resolved_male_id = male_id
    resolved_target_id = target_id

    latest_row, history_rows, summary_row, event_row = _fetch_overview(
        db, condition, params, history_limit
    )

    if not history_rows:
        if target_id:
            fallback_row = db.execute(
                text(
                    "SELECT target_participant_id "
                    "FROM sentiment_snapshots "
                    "WHERE target_participant_id IS NOT NULL "
                    "ORDER BY captured_at DESC LIMIT 1"
                )
            ).fetchone()
            if fallback_row:
                resolved_target_id = fallback_row.target_participant_id
                condition, params = _build_condition(None, None, resolved_target_id)
        else:
            fallback_row = db.execute(
                text(
                    "SELECT female_id, male_id "
                    "FROM sentiment_snapshots "
                    "WHERE female_id IS NOT NULL "
                    "AND male_id IS NOT NULL "
                    "AND target_participant_id IS NULL "
                    "ORDER BY captured_at DESC LIMIT 1"
                )
            ).fetchone()
            if fallback_row:
                resolved_female_id = fallback_row.female_id
                resolved_male_id = fallback_row.male_id
                condition, params = _build_condition(
                    resolved_female_id, resolved_male_id, None
                )

        if resolved_female_id or resolved_target_id:
            latest_row, history_rows, summary_row, event_row = _fetch_overview(
                db, condition, params, history_limit
            )

    history = [
        SentimentPoint(captured_at=row.captured_at, support_rate=row.support_rate)
        for row in reversed(history_rows)
    ]

    return SentimentOverview(
        female_id=resolved_female_id,
        male_id=resolved_male_id,
        target_id=resolved_target_id,
        support_rate=latest_row.support_rate if latest_row else 0,
        delta_5m=latest_row.delta_5m if latest_row else 0,
        history=history,
        summary=summary_row.summary_text if summary_row else None,
        event=(
            SentimentEvent(
                event_type=event_row.event_type,
                delta=event_row.delta,
                start_at=event_row.start_at,
                end_at=event_row.end_at,
            )
            if event_row
            else None
        ),
    )
