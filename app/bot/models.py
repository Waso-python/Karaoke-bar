from sqlalchemy import Column, Integer, String, Boolean, create_engine, BigInteger, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    display_name = Column(String)
    table_number = Column(String, nullable=True)
    is_registered = Column(Boolean, default=False)
    language_code = Column(String, nullable=True)
    registered_at = Column(DateTime, nullable=True)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    song_id = Column(Integer)
    song_title = Column(String)
    song_artist = Column(String)
    has_backing = Column(Boolean)
    status = Column(String, default="pending")  # pending, completed, cancelled
    ordered_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Связь с пользователем
    user = relationship("User", backref="orders")

    def to_dict(self):
        return {
            "id": self.id,
            "song_id": self.song_id,
            "song_title": self.song_title,
            "song_artist": self.song_artist,
            "has_backing": self.has_backing,
            "status": self.status,
            "ordered_at": self.ordered_at,
            "completed_at": self.completed_at
        }


def init_db():
    # Создаем новую БД, если она еще не существует
    engine = create_engine("sqlite:///karaoke_bot.db")
    Base.metadata.create_all(engine)
    return engine


# Инициализируем БД
engine = init_db()
Session = sessionmaker(bind=engine)
