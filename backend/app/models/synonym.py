"""Synonym mapping model.

Replaces: kb-web server.py synonym_map handling

v1 schema: id (INTEGER PK AUTOINCREMENT), term, expansion, category
"""

from sqlalchemy import Column, String, Integer
from app.models.database import Base


class Synonym(Base):
    __tablename__ = "synonym_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    term = Column(String, nullable=False)
    expansion = Column(String, nullable=False)
    category = Column(String, default="")
