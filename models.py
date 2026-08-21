from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, ARRAY
from sqlalchemy.orm import relationship
from database import Base

class UserModel(Base):
    __tablename__ = "users"

    spotify_id = Column(String, primary_key=True, index=True)
    display_name = Column(String, nullable=True)
    access_token = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    session_token = Column(String, unique=True, nullable=True, index=True)


class ArtistModel(Base):
    __tablename__ = "artists"

    artist_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    genres = Column(ARRAY(String), nullable=True)


class TrackModel(Base):
    __tablename__ = "tracks"

    track_id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    artist_id = Column(String, ForeignKey("artists.artist_id"), nullable=True)
    danceability = Column(Float, nullable=True)
    energy = Column(Float, nullable=True)
    valence = Column(Float, nullable=True)
    tempo = Column(Float, nullable=True)

    artist = relationship("ArtistModel")


class ListeningHistoryModel(Base):
    __tablename__ = "listening_history"

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    spotify_id = Column(String, ForeignKey("users.spotify_id"), nullable=False)
    track_id = Column(String, ForeignKey("tracks.track_id"), nullable=False)
    played_at = Column(DateTime(timezone=True), nullable=True)