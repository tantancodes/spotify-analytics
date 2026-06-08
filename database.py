import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Load keys out of our hidden .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Create the master engine that manages our cloud connection pool
engine = create_engine(DATABASE_URL)

# Create a sessionmaker which opens temporary channels to execute SQL queries
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# The base class that our SQL tables will inherit to map Python code to Neon rows
Base = declarative_base()

def get_db():
    """Context manager to safely open and close database sessions per API request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()