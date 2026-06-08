"""Synonym mapping model.

Replaces: kb-web server.py synonym_map handling
"""

from sqlalchemy import Column, String, Text
from app.models.database import Base


class Synonym(Base):
    __tablename__ = "synonyms"

    word = Column(String, primary_key=True)
    synonyms_json = Column(Text, default="[]")  # JSON array of synonym strings
