"""Removing a project, or a person, together with everything hanging off it.

Nothing in this schema uses database-level foreign keys — rows are tied to each
other by `project_code` and `fin_kod` alone — so a delete that only removes the
parent row leaves the children behind for ever. Worse, an orphaned
`collaborators` row keeps occupying its owner's competition slot, silently
barring them from joining anything else.

Both helpers stage their work on the session and leave the commit to the
caller, so a request that touches several of them either lands whole or not at
all.
"""

import os
import logging

from flask import current_app

from extentions.db import db
from models.authModel import Auth
from models.otpModel import Otp
from models.userModel import User
from models.projectModel import Project
from models.messageModel import MessageThread
from models.reportModel import QuarterlyReport
from models.assessmentModel import Assessment
from models.projectFileModel import ProjectFile
from models.notificationModel import Notification
from models.collaboratorModel import Collaborator
from models.projectActivities import ProjectActivities
from models.roleChangeRequestModel import RoleChangeRequest
from models.smetaModels.rentModel import Rent
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.salaryModel import Salary
from models.smetaModels.subjectModel import SubjectOfPurchase
from models.smetaModels.other_expensesModel import other_exp_model
from models.smetaModels.servicesTableModel import ServicesOfPurchase

logger = logging.getLogger(__name__)

# Everything addressed by `project_code`. `Smeta` is stored with a stringified
# code in places, which is why it is looked up separately below.
PROJECT_SCOPED_MODELS = (
    Collaborator,
    ProjectActivities,
    ProjectFile,
    Assessment,
    Salary,
    Rent,
    SubjectOfPurchase,
    ServicesOfPurchase,
    other_exp_model,
)


def _remove_file(folder_key, stored_filename):
    """Delete an uploaded file from disk. Never fatal: a missing file must not
    block the database rows that point at it from going away."""
    if not stored_filename:
        return
    try:
        folder = current_app.config.get(folder_key)
        if not folder:
            return
        path = os.path.join(folder, stored_filename)
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        logger.exception("Could not remove the stored file %s", stored_filename)


def delete_project_cascade(project_code):
    """Stage the removal of one project and everything attached to it.

    Returns a {label: count} summary of what went, for the caller to report.
    """
    project_code = int(project_code)
    removed = {}

    for model in PROJECT_SCOPED_MODELS:
        rows = model.query.filter_by(project_code=project_code).all()
        if model is ProjectFile:
            for row in rows:
                _remove_file('PROJECT_FILES_FOLDER', row.stored_filename)
        for row in rows:
            db.session.delete(row)
        if rows:
            removed[model.__tablename__] = len(rows)

    # Quarterly reports own their files through a real FK cascade, but the
    # uploads on disk are ours to clean up.
    reports = QuarterlyReport.query.filter_by(project_code=project_code).all()
    for report in reports:
        for report_file in report.files:
            _remove_file('REPORT_FILES_FOLDER', report_file.stored_filename)
        db.session.delete(report)
    if reports:
        removed['quarterly_reports'] = len(reports)

    # `Smeta.project_code` is an INTEGER, but parts of the smeta code write it
    # through a string; match both so no aggregate row is left behind.
    smetas = Smeta.query.filter(
        Smeta.project_code.in_([project_code, str(project_code)])
    ).all()
    for smeta in smetas:
        db.session.delete(smeta)
    if smetas:
        removed['smeta'] = len(smetas)

    project = Project.query.filter_by(project_code=project_code).first()
    if project:
        db.session.delete(project)
        removed['project'] = 1

    return removed


def delete_user_cascade(fin_kod):
    """Stage the removal of one person: their account, profile, every project
    they lead, and every trace of them on other people's projects.

    Returns a {label: count} summary of what went.
    """
    removed = {}

    # Projects they lead go first, taking their teams and budgets with them.
    owned = Project.query.filter_by(fin_kod=fin_kod).all()
    for project in owned:
        for label, count in delete_project_cascade(project.project_code).items():
            removed[label] = removed.get(label, 0) + count

    # Their seat on OTHER people's teams, and the budget lines that go with it.
    for model in (Collaborator, Salary):
        rows = model.query.filter_by(fin_kod=fin_kod).all()
        for row in rows:
            db.session.delete(row)
        if rows:
            removed[model.__tablename__] = removed.get(model.__tablename__, 0) + len(rows)

    # Conversations with the admins, attachments included (FK cascade covers
    # the message rows; the uploads on disk do not cascade).
    threads = MessageThread.query.filter_by(user_fin_kod=fin_kod).all()
    for thread in threads:
        for message in thread.messages:
            for attachment in message.attachments:
                _remove_file('MESSAGE_FILES_FOLDER', attachment.stored_filename)
        db.session.delete(thread)
    if threads:
        removed['message_threads'] = len(threads)

    for model, column in (
        (Notification, 'recipient_fin_kod'),
        (RoleChangeRequest, 'fin_kod'),
        (Otp, 'fin_kod'),
    ):
        rows = model.query.filter_by(**{column: fin_kod}).all()
        for row in rows:
            db.session.delete(row)
        if rows:
            removed[model.__tablename__] = len(rows)

    # The profile last of all — its CV upload is the final file on disk.
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if user:
        _remove_file('CV_FILES_FOLDER', user.cv_stored_filename)
        db.session.delete(user)
        removed['profile'] = 1

    account = Auth.query.filter_by(fin_kod=fin_kod).first()
    if account:
        db.session.delete(account)
        removed['auth'] = 1

    return removed
