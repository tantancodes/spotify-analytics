from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import engine, Base, get_db

app = FastAPI(title="Spotify Listening Intelligence Engine API")

@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    """Baseline operational diagnostic route verifying service and cloud database status."""
    try:
        # Run a raw, ultra-lightweight query to test the Neon cloud connection
        db.execute(text("SELECT 1"))
        return {
            "status": "operational",
            "database_connected": True,
            "engine": "PostgreSQL (Neon Cloud)"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Database connection failed: {str(e)}"
        )