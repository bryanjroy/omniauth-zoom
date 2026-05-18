"""SQLAlchemy models and session management."""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import enum
import config

engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class PermitStatus(str, enum.Enum):
    NEEDED = "needed"
    DRAFTED = "drafted"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    venue = Column(String, default=config.EVENT_VENUE)
    status = Column(String, default="planned")  # planned, confirmed, cancelled, completed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    permits = relationship("Permit", back_populates="event")
    staff_assignments = relationship("StaffAssignment", back_populates="event")
    vendor_bookings = relationship("VendorBooking", back_populates="event")
    expenses = relationship("Expense", back_populates="event")


class Permit(Base):
    __tablename__ = "permits"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"))
    permit_type = Column(String, nullable=False)  # venue, alcohol, amusement, special_event
    status = Column(SAEnum(PermitStatus), default=PermitStatus.NEEDED)
    submitted_date = Column(DateTime)
    approved_date = Column(DateTime)
    expiry_date = Column(DateTime)
    reference_number = Column(String)
    fee_paid = Column(Float, default=0.0)
    notes = Column(Text)
    contact_name = Column(String)
    contact_email = Column(String)
    contact_phone = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="permits")


class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)   # bartender, event_staff, bounce_house_operator
    email = Column(String)
    phone = Column(String)
    tips_certified = Column(Boolean, default=False)
    hourly_rate = Column(Float)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    assignments = relationship("StaffAssignment", back_populates="staff")


class StaffAssignment(Base):
    __tablename__ = "staff_assignments"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"))
    staff_id = Column(Integer, ForeignKey("staff.id"))
    role = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    confirmed = Column(Boolean, default=False)
    hours_worked = Column(Float)
    amount_paid = Column(Float)

    event = relationship("Event", back_populates="staff_assignments")
    staff = relationship("Staff", back_populates="assignments")


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String)   # bounce_house, catering, photography, etc.
    contact_name = Column(String)
    email = Column(String)
    phone = Column(String)
    website = Column(String)
    base_rate = Column(Float)
    notes = Column(Text)
    rating = Column(Float)
    is_preferred = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    bookings = relationship("VendorBooking", back_populates="vendor")


class VendorBooking(Base):
    __tablename__ = "vendor_bookings"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"))
    vendor_id = Column(Integer, ForeignKey("vendors.id"))
    service_description = Column(Text)
    quoted_price = Column(Float)
    final_price = Column(Float)
    deposit_paid = Column(Float, default=0.0)
    confirmed = Column(Boolean, default=False)
    confirmation_number = Column(String)
    notes = Column(Text)

    event = relationship("Event", back_populates="vendor_bookings")
    vendor = relationship("Vendor", back_populates="bookings")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    category = Column(String)
    description = Column(String)
    amount = Column(Float)
    paid_date = Column(DateTime)
    receipt_path = Column(String)
    notes = Column(Text)

    event = relationship("Event", back_populates="expenses")


class EmailLog(Base):
    __tablename__ = "email_log"

    id = Column(Integer, primary_key=True)
    direction = Column(String)   # inbound / outbound
    from_addr = Column(String)
    to_addr = Column(String)
    subject = Column(String)
    body_preview = Column(Text)
    gmail_message_id = Column(String)
    thread_id = Column(String)
    agent_handled = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
