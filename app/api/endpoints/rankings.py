from fastapi import APIRouter, Depends
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.api.endpoints.users import get_current_user
from app.db.session import get_db
from app.models.badge import BadgeMaster
from app.models.user import User
from app.schemas.ranking import RankingEntry, RankingOverview

router = APIRouter()


@router.get("/rankings", response_model=RankingOverview)
def read_rankings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RankingOverview:
    rank_subq = (
        db.query(
            User.id.label("user_id"),
            func.rank().over(order_by=User.points.desc()).label("rank"),
        )
        .filter(User.id != 1)
        .subquery()
    )

    leaders_rows = (
        db.query(
            User.id,
            User.nickname,
            User.points,
            rank_subq.c.rank,
            BadgeMaster.icon_url,
            BadgeMaster.name,
        )
        .join(rank_subq, rank_subq.c.user_id == User.id)
        .outerjoin(BadgeMaster, BadgeMaster.id == User.primary_badge_id)
        .order_by(rank_subq.c.rank.asc(), User.id.asc())
        .limit(20)
        .all()
    )

    leaders = [
        RankingEntry(
            user_id=row.id,
            nickname=row.nickname,
            points=row.points,
            rank=int(row.rank),
            primary_badge_icon_url=row.icon_url,
            primary_badge_name=row.name,
        )
        for row in leaders_rows
    ]

    me_row = (
        db.query(
            User.id,
            User.nickname,
            User.points,
            rank_subq.c.rank,
            BadgeMaster.icon_url,
            BadgeMaster.name,
        )
        .join(rank_subq, rank_subq.c.user_id == User.id)
        .outerjoin(BadgeMaster, BadgeMaster.id == User.primary_badge_id)
        .filter(User.id == current_user.id)
        .first()
    )

    me_entry = None
    if me_row:
        me_entry = RankingEntry(
            user_id=me_row.id,
            nickname=me_row.nickname,
            points=me_row.points,
            rank=int(me_row.rank),
            primary_badge_icon_url=me_row.icon_url,
            primary_badge_name=me_row.name,
        )

    return RankingOverview(me=me_entry, leaders=leaders)
