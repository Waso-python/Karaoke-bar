from sqlalchemy import Column, Integer, String, Boolean, create_engine, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

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


def init_db():
    # Удаляем старую БД если она существует
    if os.path.exists("karaoke_bot.db"):
        os.remove("karaoke_bot.db")

    # Создаем новую БД
    engine = create_engine("sqlite:///karaoke_bot.db")
    Base.metadata.create_all(engine)
    return engine


# Инициализируем БД
engine = init_db()
Session = sessionmaker(bind=engine)
