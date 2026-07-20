from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Booking, ChatSession, Memory, Message, User, utcnow

HISTORY_WINDOW = 12

ACTIVE_BOOKING_STATES = ("COLLECTING", "PRESENTING", "CONFIRMING")


class BookingRepo:
    def __init__(self, db: Session):
        self.db = db

    def active_for_user(self, user_id: str) -> Booking | None:
        stmt = (
            select(Booking)
            .where(Booking.user_id == user_id, Booking.status.in_(ACTIVE_BOOKING_STATES))
            .order_by(Booking.updated_at.desc())
        )
        return self.db.scalars(stmt).first()

    def create(self, user_id: str) -> Booking:
        booking = Booking(user_id=user_id, status="COLLECTING", slots={})
        self.db.add(booking)
        self.db.commit()
        return booking

    def save(self, booking: Booking) -> None:
        booking.updated_at = utcnow()
        self.db.commit()

    def list_for_user(self, user_id: str) -> list[Booking]:
        stmt = (
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.updated_at.desc())
        )
        return list(self.db.scalars(stmt).all())


class MemoryRepo:
    def __init__(self, db: Session):
        self.db = db

    def list_for_user(self, user_id: str) -> list[Memory]:
        stmt = select(Memory).where(Memory.user_id == user_id).order_by(Memory.key)
        return list(self.db.scalars(stmt).all())

    def upsert(self, user_id: str, category: str, key: str, value: str) -> Memory:
        stmt = select(Memory).where(Memory.user_id == user_id, Memory.key == key)
        memory = self.db.scalars(stmt).first()
        if memory is None:
            memory = Memory(user_id=user_id, category=category, key=key, value=value)
            self.db.add(memory)
        else:  # conflict resolution: newest wins
            memory.category = category
            memory.value = value
            memory.updated_at = utcnow()
        self.db.commit()
        return memory

    def delete(self, user_id: str, key: str) -> bool:
        stmt = select(Memory).where(Memory.user_id == user_id, Memory.key == key)
        memory = self.db.scalars(stmt).first()
        if memory is None:
            return False
        self.db.delete(memory)
        self.db.commit()
        return True

    def delete_all(self, user_id: str) -> int:
        memories = self.list_for_user(user_id)
        for memory in memories:
            self.db.delete(memory)
        self.db.commit()
        return len(memories)


class ConversationRepo:
    def __init__(self, db: Session):
        self.db = db

    def touch_user(self, user_id: str) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            self.db.add(user)
        else:
            user.last_seen_at = utcnow()
        self.db.commit()
        return user

    def get_or_create_session(self, session_id: str, user_id: str) -> ChatSession:
        session = self.db.get(ChatSession, session_id)
        if session is None:
            session = ChatSession(id=session_id, user_id=user_id)
            self.db.add(session)
            self.db.commit()
        return session

    def add_message(self, session_id: str, role: str, content: str) -> Message:
        msg = Message(session_id=session_id, role=role, content=content)
        self.db.add(msg)
        self.db.commit()
        return msg

    def recent_messages(self, session_id: str, limit: int = HISTORY_WINDOW) -> list[Message]:
        """Last `limit` messages of the session, oldest first."""
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        return list(reversed(self.db.scalars(stmt).all()))
