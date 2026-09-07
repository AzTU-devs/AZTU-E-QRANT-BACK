from extentions.db import db

class Project(db.Model):
    __tablename__ = 'project'
    # A user may own one project PER competition (not one globally), so the
    # uniqueness is composite rather than a global UNIQUE on fin_kod.
    __table_args__ = (
        db.UniqueConstraint('fin_kod', 'competition_id', name='uq_project_fin_competition'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_code = db.Column(db.Integer, unique=True, nullable=False)
    fin_kod = db.Column(db.String, nullable=False)
    project_name = db.Column(db.Text)
    project_purpose = db.Column(db.Text)
    project_annotation = db.Column(db.Text)
    project_key_words = db.Column(db.Text)
    project_scientific_idea = db.Column(db.Text)
    project_structure = db.Column(db.Text)
    team_characterization = db.Column(db.Text)
    project_monitoring = db.Column(db.Text)
    project_assessment = db.Column(db.Text)
    project_requirements = db.Column(db.Text)
    project_deadline = db.Column(db.DateTime)
    approved = db.Column(db.Integer, default=0)
    collaborator_limit = db.Column(db.Integer, nullable=False, default=7)
    max_smeta_amount = db.Column(db.Integer, nullable=False, default=50000)
    expert = db.Column(db.Text, default=None)
    priotet = db.Column(db.Text)
    submitted = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime)
    winner = db.Column(db.Boolean, default=False)
    winner_at = db.Column(db.DateTime)
    # An admin can send a submitted proposal back for corrections. The note is
    # what the lead is meant to act on, so it is kept after the resubmission
    # too — `submitted` is what says whether anything is outstanding.
    revision_note = db.Column(db.Text)
    returned_at = db.Column(db.DateTime)
    returned_by = db.Column(db.String(100))  # fin_kod of the admin
    competition_id = db.Column(db.Integer)  # FK-by-convention -> competitions.id
    # Projects of PREVIOUS competitions (the archive) are read-only by default.
    # An admin flips this flag to hand the project back to its owner for edits.
    edit_unlocked = db.Column(db.Boolean, default=False)
    edit_unlocked_at = db.Column(db.DateTime)
    edit_unlocked_by = db.Column(db.String(100))  # fin_kod of the admin

    def project_detail(self):
        return {
            'id': self.id,
            'project_code': self.project_code,
            'fin_kod': self.fin_kod,
            'project_name': self.project_name,
            'project_purpose': self.project_purpose,
            'project_annotation': self.project_annotation,
            'project_key_words': self.project_key_words,
            'project_scientific_idea': self.project_scientific_idea,
            'project_structure': self.project_structure,
            'team_characterization': self.team_characterization,
            'project_monitoring': self.project_monitoring,
            'project_assessment': self.project_assessment,
            'project_requirements': self.project_requirements,
            'project_deadline': self.project_deadline,
            'approved': self.approved,
            'collaborator_limit': self.collaborator_limit,
            'max_smeta_amount': self.max_smeta_amount,
            'expert': self.expert,
            'priotet': self.priotet,
            'submitted': self.submitted,
            'submitted_at': self.submitted_at,
            'winner': bool(self.winner),
            'winner_at': self.winner_at,
            'revision_note': self.revision_note,
            'returned_at': self.returned_at,
            'returned_by': self.returned_by,
            # True while the lead still has corrections to make: sent back and
            # not handed in again since.
            'needs_revision': bool(self.returned_at) and not bool(self.submitted),
            'competition_id': self.competition_id,
            'edit_unlocked': bool(self.edit_unlocked),
            'edit_unlocked_at': self.edit_unlocked_at,
            'edit_unlocked_by': self.edit_unlocked_by
        }