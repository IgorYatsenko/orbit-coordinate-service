from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.sqlalchemy.base import SQLAlchemyBase


class Satellite(SQLAlchemyBase):
    __tablename__ = "satellites"
    __table_args__ = (
        CheckConstraint("norad_id BETWEEN 1 AND 999999999", name="norad_id_range"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    norad_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    international_designator: Mapped[str | None] = mapped_column(String(32))
    launch_date: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
