from sqlalchemy.orm import sessionmaker
from shared.database.engine import engine

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)