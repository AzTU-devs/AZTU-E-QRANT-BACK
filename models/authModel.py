from extentions.db import db
from werkzeug.security import generate_password_hash, check_password_hash

class Auth(db.Model):
    __tablename__ = 'auth'
    
    id = db.Column(db.Integer, primary_key=True)
    fin_kod = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    user_type = db.Column(db.Integer, nullable=False)
    # 0 = teacher, 1 = phd, 2 = master
    # academic_role = db.Column(db.Integer)
    # 1 = collaborator, 0 = owner, 2 = super admin
    project_role = db.Column(db.Integer)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False)
    approved_at = db.Column(db.DateTime)
    blocked = db.Column(db.Integer, nullable=False, default=0)
    blocked_at = db.Column(db.DateTime)
    unblocked_at = db.Column(db.DateTime)
    otp_verificated = db.Column(db.Boolean, default=False)


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<Auth {self.fin_kod}>'
    

    def auth_details(self): 
        return {
            'fin_kod' : self.fin_kod,
            'user_type': self.user_type,
            # 'academic_role': self.academic_role,
            'project_role': self.project_role
        }