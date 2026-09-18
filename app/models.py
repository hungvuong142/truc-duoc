"""SQLAlchemy ORM models: staff, duty_weights, holidays, assignments."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Float,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Staff(Base):
    __tablename__ = "staff"

    bmo_id: Mapped[str] = mapped_column(String, primary_key=True)
    ho_va_ten: Mapped[str] = mapped_column(String, nullable=False)
    tuoi: Mapped[int | None] = mapped_column(Integer)
    gioi_tinh: Mapped[str | None] = mapped_column(String)
    trinh_do: Mapped[str | None] = mapped_column(String)
    vi_tri: Mapped[str] = mapped_column(String, nullable=False)
    so_dien_thoai: Mapped[str | None] = mapped_column(String)
    mang_thai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sinh_de: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ghi_chu: Mapped[str | None] = mapped_column(String)
    ninh_binh_base: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="staff")


class NinhBinhAssignment(Base):
    """One row = this staff member is assigned to the Ninh Binh base for
    this (year, month). `Staff.ninh_binh_base` is a derived snapshot of
    this table for the current month -- see repository.sync_ninh_binh_base."""

    __tablename__ = "ninh_binh_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.bmo_id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("staff_id", "year", "month", name="uq_ninh_binh_assignment"),
    )


class DutyWeight(Base):
    __tablename__ = "duty_weights"

    duty_code: Mapped[int] = mapped_column(Integer, primary_key=True)
    duty_type: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String)
    duty_weight: Mapped[float | None] = mapped_column(Float)
    multiplier: Mapped[float | None] = mapped_column(Float)


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("is_recurring", "month", "day", "year", name="uq_holiday_date"),
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    duty_date: Mapped[date] = mapped_column(Date, nullable=False)
    base: Mapped[str] = mapped_column(String, nullable=False)
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.bmo_id"), nullable=False)
    is_half_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    staff: Mapped["Staff"] = relationship(back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("duty_date", "base", "staff_id", name="uq_assignment_slot"),
    )
