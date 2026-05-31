import os
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum, JSON, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///database.db')

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), unique=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # 'student', 'alumni', 'recruiter', 'admin'
    student_id = Column(String(100), nullable=True)
    academic_data_pending = Column(Boolean, default=False)
    academic_data_last_attempt = Column(DateTime, nullable=True)
    academic_data_retry_count = Column(Integer, default=0)
    academic_data_raw = Column(Text, nullable=True)
    profile_picture = Column(String(255), default='default-avatar.png')
    reset_token = Column(String(255), nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    companies = relationship('Company', back_populates='owner')
    sent_messages = relationship('Message', back_populates='sender', foreign_keys='Message.sender_id')
    received_messages = relationship('Message', back_populates='receiver', foreign_keys='Message.receiver_id')


class Company(Base):
    __tablename__ = 'companies'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    website_url = Column(String(500))
    linkedin_url = Column(String(500))
    logo_url = Column(String(500))
    industry = Column(String(255))
    location = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship('User', back_populates='companies')


class ChatSession(Base):
    __tablename__ = 'chat_sessions'
    id = Column(Integer, primary_key=True)
    user1_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    user2_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(Enum('pending', 'accepted', 'blocked', name='chat_status'), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

    user1 = relationship('User', foreign_keys=[user1_id])
    user2 = relationship('User', foreign_keys=[user2_id])
    messages = relationship('Message', back_populates='session')


class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship('ChatSession', back_populates='messages')
    sender = relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')


class AdminForward(Base):
    __tablename__ = 'admin_forwarded_chats'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    admin_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    original_question = Column(Text, nullable=False)
    status = Column(Enum('pending', 'resolved', name='admin_forward_status'), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    user = relationship('User', foreign_keys=[user_id])
    admin = relationship('User', foreign_keys=[admin_id])


def init_models():
    """Create tables for the configured database."""
    Base.metadata.create_all(bind=engine)


if __name__ == '__main__':
    init_models()
