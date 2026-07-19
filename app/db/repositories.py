from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatSession, Message, User, utcnow

HISTORY_WINDOW = 12


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
