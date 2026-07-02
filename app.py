import os
from flask import Flask
from flask_cors import CORS
from flasgger import Swagger
from sqlalchemy import inspect, text
from dotenv import load_dotenv
from config.config import Config
from config.limiter import limiter
from extentions.db import migrate, db
from controllers.AuthController import auth_bp
from controllers.AnnouncementController import announcement_bp
from controllers.UserController import user_bp
from controllers.lockController import lock_bp
from controllers.ExpertController import expert_bp
from controllers.PriotetController import priotet_bp
from controllers.ProjectController import project_offer
from controllers.PublicController import public_bp
from controllers.InstitutionController import institution_bp
from controllers.CollaboratorController import collaborator_bp
from controllers.smetaControllers.rentController import rent_bp
from controllers.smetaControllers.smetaCotroller import smeta_bp
from controllers.smetaControllers.salaryController import salary_bp
from controllers.ProjectActivitiesController import project_activity
from controllers.ReportController import report_bp
from controllers.smetaControllers.subjectController import subject_bp
from controllers.smetaControllers.other_expensesController import other_exp
from controllers.smetaControllers.servicesTableController import services_bp

def ensure_schema():
    """Idempotently add columns that `db.create_all()` cannot add to existing
    tables. `create_all` only creates missing tables; it never ALTERs an
    existing one, so new columns on the `project` table are added here."""
    inspector = inspect(db.engine)
    if 'project' not in inspector.get_table_names():
        return

    existing_columns = {col['name'] for col in inspector.get_columns('project')}
    statements = []
    if 'winner' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN winner BOOLEAN DEFAULT FALSE")
    if 'winner_at' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN winner_at TIMESTAMP")

    if statements:
        with db.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))


def main_app():
    load_dotenv()
    app = Flask(__name__)
    template = {
        "swagger": "2.0",
        "info": {
            "title": "E-Grant API",
            "description": "API documentation for E-Grant project",
            "version": "1.0"
        },
        "schemes": ["http", "https"]
    }

    swagger = Swagger(app, template=template)
    limiter.init_app(app)
    app.config.from_object(Config)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.getenv('SQLALCHEMY_TRACK_MODIFICATIONS', 'False').lower() == 'true'
    
    CORS(
    	app,
    	# origins=["http://e-grant.aztu.edu.az", "http://10.0.26.35"],
    	origins="*",
    	supports_credentials=True,
    	allow_headers=["Content-Type", "Authorization", "Content-Disposition"],
    	methods=["GET", "POST", "PUT", "PATCH", "OPTIONS", "DELETE"]
	)

    db.init_app(app)
    migrate.init_app(app, db)
    
    with app.app_context():
        db.create_all()
        ensure_schema()

    app.register_blueprint(auth_bp)
    app.register_blueprint(announcement_bp)
    app.register_blueprint(lock_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(rent_bp)
    app.register_blueprint(smeta_bp)
    app.register_blueprint(salary_bp)
    app.register_blueprint(other_exp)
    app.register_blueprint(expert_bp)
    app.register_blueprint(subject_bp)
    app.register_blueprint(priotet_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(project_offer)
    app.register_blueprint(public_bp)
    app.register_blueprint(institution_bp)
    app.register_blueprint(collaborator_bp)
    app.register_blueprint(project_activity)
    app.register_blueprint(report_bp)

    return app

if __name__ == '__main__':
    app = main_app()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)