from extentions.db import db
from datetime import datetime


class ProjectFile(db.Model):
    """Arbitrary files attached to a project during creation (unlimited count)."""
    __tablename__ = 'project_files'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_code = db.Column(db.Integer, nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    content_type = db.Column(db.String(120))
    file_size = db.Column(db.BigInteger)
    uploaded_by = db.Column(db.String(100))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def serialize(self):
        content_type = self.content_type or ''
        return {
            'id': self.id,
            'project_code': self.project_code,
            'original_filename': self.original_filename,
            'content_type': self.content_type,
            'file_size': self.file_size,
            'is_image': content_type.startswith('image/'),
            'url': f"/api/project/files/{self.id}/download",
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }
