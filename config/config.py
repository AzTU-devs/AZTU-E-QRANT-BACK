import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Rüblük hesabat fayllarının saxlanıldığı qovluq (yalnız 4-cü rüb üçün)
    UPLOAD_FOLDER = os.getenv(
        'UPLOAD_FOLDER',
        os.path.join(os.path.dirname(basedir), 'uploads')
    )
    REPORT_FILES_FOLDER = os.path.join(UPLOAD_FOLDER, 'report_files')

    # İcazə verilən fayl tipləri (sənəd və pdf)
    ALLOWED_REPORT_EXTENSIONS = {'pdf', 'doc', 'docx'}

    # Hər faylın maksimum ölçüsü: 25 MB
    MAX_REPORT_FILE_SIZE = 25 * 1024 * 1024