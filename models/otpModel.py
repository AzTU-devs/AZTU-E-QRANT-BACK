import hashlib
import hmac

from extentions.db import db


class Otp(db.Model):
    __tablename__ = 'otp'

    id = db.Column(db.Integer, primary_key=True)
    # Legacy plaintext column, kept nullable for old rows. New codes are NOT
    # stored here — only their SHA-256 goes in `otp_hash` (finding B-L4).
    otp = db.Column(db.Integer, nullable=True)
    otp_hash = db.Column(db.String(64))
    fin_kod = db.Column(db.String, nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)

    @staticmethod
    def hash_code(code):
        return hashlib.sha256(str(code).encode('utf-8')).hexdigest()

    def set_code(self, code):
        """Store only the hash of the one-time code, never the code itself."""
        self.otp_hash = self.hash_code(code)

    def matches(self, code):
        """Constant-time comparison against the stored hash."""
        if not self.otp_hash:
            return False
        return hmac.compare_digest(self.otp_hash, self.hash_code(code))
