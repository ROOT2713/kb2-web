"""Document repository — CRUD operations for document metadata."""

from typing import Optional, List, Dict
from sqlalchemy.orm import Session

from app.models.document import Document


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, doc: Document) -> Document:
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def get(self, doc_id: str) -> Optional[Document]:
        return self.db.query(Document).filter(Document.doc_id == doc_id).first()

    def get_by_hash(self, content_hash: str) -> Optional[Document]:
        return self.db.query(Document).filter(Document.content_hash == content_hash).first()

    def list_all(self, bank: str = "all") -> List[Document]:
        q = self.db.query(Document)
        if bank != "all":
            q = q.filter(Document.bank == bank)
        return q.order_by(Document.created_at.desc()).all()

    def update(self, doc_id: str, **kwargs) -> Optional[Document]:
        doc = self.get(doc_id)
        if doc:
            for k, v in kwargs.items():
                if hasattr(doc, k) and v is not None:
                    setattr(doc, k, v)
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def delete(self, doc_id: str) -> bool:
        doc = self.get(doc_id)
        if doc:
            self.db.delete(doc)
            self.db.commit()
            return True
        return False
