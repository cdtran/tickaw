"""Notebooks organize questions; each cell pins an independent dataset snapshot."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notebook(Base):
    __tablename__ = "notebooks"
    __table_args__ = (CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="title_length"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotebookCell(Base):
    __tablename__ = "notebook_cells"
    __table_args__ = (
        CheckConstraint("length(btrim(question)) BETWEEN 1 AND 4000", name="question_length"),
        CheckConstraint("status IN ('SAVED')", name="status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notebook_id: Mapped[UUID] = mapped_column(ForeignKey("notebooks.id", ondelete="RESTRICT"), index=True)
    dataset_version_id: Mapped[UUID] = mapped_column(ForeignKey("dataset_versions.id", ondelete="RESTRICT"), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'SAVED'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
