from extentions.db import db
from datetime import datetime
import base64

class User(db.Model):
    __tablename__ = 'User'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text)
    surname = db.Column(db.Text)
    father_name = db.Column(db.Text)
    fin_kod = db.Column(db.Text, unique=True, nullable=False)
    image = db.Column(db.LargeBinary)
    born_place = db.Column(db.Text)
    living_location = db.Column(db.Text)
    home_phone = db.Column(db.Text, unique=True)
    personal_mobile_number = db.Column(db.Text, unique=True)
    personal_email = db.Column(db.Text, unique=True)
    citizenship = db.Column(db.Text)
    personal_id_number = db.Column(db.Text)
    sex = db.Column(db.Text)
    work_place = db.Column(db.Text)
    department = db.Column(db.Text)
    duty = db.Column(db.Text)
    main_education = db.Column(db.Text)
    additonal_education = db.Column(db.Text)
    scientific_degree = db.Column(db.Text)
    scientific_date = db.Column(db.DateTime)
    scientific_name = db.Column(db.Text)
    scientific_name_date = db.Column(db.DateTime)
    work_location = db.Column(db.Text)
    work_phone = db.Column(db.Text, unique=True)
    work_email = db.Column(db.Text, unique=True)
    profile_completed = db.Column(db.Integer, nullable=False)
    born_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime)
    institution_code = db.Column(db.String)
    cv_original_filename = db.Column(db.String)
    cv_stored_filename = db.Column(db.String)

    def user_details(self):
        return {
            "id": self.id,
            "name": self.name,
            "surname": self.surname,
            "father_name": self.father_name,
            "fin_kod": self.fin_kod,
            "image": base64.b64encode(bytes(self.image)).decode('utf-8') if self.image else None,
            "born_place": self.born_place,
            "living_location": self.living_location,
            "home_phone": self.home_phone,
            "personal_mobile_number": self.personal_mobile_number,
            "personal_email": self.personal_email,
            "citizenship": self.citizenship,  
            "personal_id_number": self.personal_id_number,
            "sex": self.sex,
            "work_place": self.work_place,
            "department": self.department,
            "duty": self.duty,
            "main_education": self.main_education,
            "additonal_education": self.additonal_education,
            "scientific_degree": self.scientific_degree,
            "scientific_date": self.scientific_date,
            "scientific_name": self.scientific_name,
            "scientific_name_date": self.scientific_name_date,
            "work_location": self.work_location,
            "work_phone": self.work_phone,
            "work_email": self.work_email,
            "profile_completed": self.profile_completed,
            "born_date": self.born_date,
            "institution_code": self.institution_code,
            "cv_original_filename": self.cv_original_filename,
            "has_cv": bool(self.cv_stored_filename)
        }
    
    def get_user_image(self):
        return {
            "image": base64.b64encode(bytes(self.image)).decode('utf-8') if self.image else None
        }