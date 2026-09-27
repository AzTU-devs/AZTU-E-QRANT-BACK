import logging
from datetime import datetime

from flask import Blueprint, request, render_template, current_app, g

from extentions.db import db
from config.limiter import limiter
from utils.email_util import send_email
from utils.jwt_required import token_required
from utils.email_validation import (
    validate_expert_email, new_verification_token, new_one_time_password,
)
from models.authModel import Auth
from utils.identity import email_taken
from utils.pdf_safety import rl_text
from models.userModel import User
from models.expertModel import Expert, EXPERT_ROLE
from models.projectModel import Project
from models.assessmentModel import (
    Assessment, CRITERIA, MAX_TOTAL, parse_criteria, total_of,
)
from exceptions.exception import (
    handle_specific_not_found, handle_success, handle_global_exception, handle_creation,
)

logger = logging.getLogger(__name__)

expert_bp = Blueprint('expert', __name__)


# ---------------------------------------------------------------- helpers ----

def frontend_url():
    """Where the browser-facing app lives, for links we put in e-mails."""
    return current_app.config.get('FRONTEND_URL', 'http://e-grant.aztu.edu.az').rstrip('/')


def caller_email():
    """An expert's identity IS their e-mail — it is their `Auth.fin_kod`."""
    return (g.user.get('fin_kod') or '').strip().lower()


def expert_project_or_error(project_code):
    """The project, if the calling expert is the one assigned to it."""
    try:
        project_code = int(project_code)
    except (TypeError, ValueError):
        return None, ({'error': 'project_code must be a number.', 'status': 400}, 400)

    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return None, ({'error': 'Project not found.', 'status': 404}, 404)

    # Admins may look at anything; an expert only at what they were given.
    if g.user.get('role') != 2:
        assigned = (project.expert or '').strip().lower()
        if assigned != caller_email():
            return None, ({'error': 'This project is not assigned to you.', 'status': 403}, 403)

    return project, None


def send_verification_email(expert):
    """Issue a fresh token and mail the confirmation link. Returns True on send."""
    expert.verification_token = new_verification_token()
    expert.verification_sent_at = datetime.utcnow()

    link = f"{frontend_url()}/expert-verify/{expert.verification_token}"
    html = render_template(
        'email/expert_verify_template.html', expert=expert, verification_link=link
    )
    return send_email('E-poçt ünvanının təsdiqi', expert.email, html)


def upsert_expert_account(expert):
    """Give the expert a login carrying a fresh one-time password.

    The account IS an `Auth` row keyed by the e-mail address, so an expert
    signs in through the same form as everyone else — the identifier field
    simply holds an address instead of a FIN. Returns the plaintext password,
    which is only ever shown in the e-mail.
    """
    one_time_password = new_one_time_password()

    account = Auth.query.filter_by(fin_kod=expert.email).first()
    if not account:
        account = Auth(
            fin_kod=expert.email,
            user_type=EXPERT_ROLE,
            project_role=EXPERT_ROLE,
            approved=True,
            created_at=datetime.utcnow(),
            approved_at=datetime.utcnow(),
            blocked=0,
        )
        db.session.add(account)

    account.set_password(one_time_password)
    account.must_change_password = True
    account.approved = True
    account.blocked = 0
    account.project_role = EXPERT_ROLE
    return one_time_password


# ------------------------------------------------------------- admin: CRUD ---

@expert_bp.route("/api/create-expert", methods=['POST'])
@limiter.limit("60 per minute")
@token_required([2])
def create_expert():
    try:
        data = request.get_json() or {}

        required_fields = ['email', 'name', 'surname', 'father_name', 'personal_id_serial_number']
        missing = [f for f in required_fields if not (data.get(f) or '').strip()]
        if missing:
            return {'error': f"Bu sahələr tələb olunur: {', '.join(missing)}", 'status': 400}, 400

        # The address has to work — everything the expert ever receives goes there.
        email, error = validate_expert_email(data['email'])
        if error:
            return {'error': error, 'status': 400}, 400

        if Expert.query.filter_by(email=email).first():
            return {'error': 'Bu e-poçt ünvanı ilə ekspert artıq mövcuddur.', 'status': 409}, 409

        # Everyone signs in by e-mail, so an expert's address must not already
        # sign a staff member in (or the two accounts would collide).
        if email_taken(email):
            return {'error': 'Bu e-poçt ünvanı artıq başqa hesabda istifadə olunur.', 'status': 409}, 409

        serial = data['personal_id_serial_number'].strip()
        if Expert.query.filter_by(personal_id_serial_number=serial).first():
            return {'error': 'Bu şəxsiyyət vəsiqəsi ilə ekspert artıq mövcuddur.', 'status': 409}, 409

        expert = Expert(
            email=email,
            name=data['name'].strip(),
            surname=data['surname'].strip(),
            father_name=data['father_name'].strip(),
            personal_id_serial_number=serial,
            work_place=(data.get('work_place') or None),
            duty=(data.get('duty') or None),
            scientific_degree=(data.get('scientific_degree') or None),
            phone_number=(data.get('phone_number') or None),
            email_verified=False,
            created_at=datetime.utcnow(),
        )
        db.session.add(expert)
        db.session.flush()

        # Sending is the real proof the address works, so it happens before the
        # commit and its outcome is reported rather than swallowed.
        sent = send_verification_email(expert)
        db.session.commit()

        payload = expert.serialize()
        payload['verification_email_sent'] = bool(sent)

        if not sent:
            return {
                'status': 201,
                'data': payload,
                'message': 'Ekspert yaradıldı, lakin təsdiq e-poçtu göndərilə bilmədi. '
                           'Ünvanı yoxlayıb yenidən göndərin.',
                'success_code': 'CREATED_WITHOUT_EMAIL',
            }, 201

        return handle_success(payload, 'Ekspert yaradıldı. Təsdiq linki e-poçt ünvanına göndərildi.')

    except Exception as e:
        db.session.rollback()
        logger.exception('create_expert failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/experts/<int:expert_id>/resend-verification", methods=['POST'])
@limiter.limit("60 per minute")
@token_required([2])
def resend_verification(expert_id):
    try:
        expert = Expert.query.get(expert_id)
        if not expert:
            return {'error': 'Ekspert tapılmadı.', 'status': 404}, 404
        if expert.email_verified:
            return {'error': 'Bu ekspertin e-poçtu artıq təsdiqlənib.', 'status': 409}, 409

        sent = send_verification_email(expert)
        db.session.commit()

        if not sent:
            return {'error': 'Təsdiq e-poçtu göndərilə bilmədi.', 'status': 502}, 502
        return handle_success(expert.serialize(), 'Təsdiq linki yenidən göndərildi.')

    except Exception as e:
        db.session.rollback()
        logger.exception('resend_verification failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/expert/verify/<string:token>", methods=['POST', 'GET'])
@limiter.limit("60 per minute")
def verify_expert_email(token):
    """Public: the link in the confirmation e-mail lands here.

    No token check beyond the secret itself — whoever holds it demonstrably
    received the mail, which is the whole point of the exercise.
    """
    try:
        expert = Expert.query.filter_by(verification_token=token).first()
        if not expert:
            return {'error': 'Təsdiq linki etibarsızdır və ya artıq istifadə olunub.', 'status': 404}, 404

        if not expert.email_verified:
            expert.email_verified = True
            expert.email_verified_at = datetime.utcnow()
            expert.verification_token = None
            db.session.commit()

        return handle_success(
            {'email': expert.email, 'name': expert.full_name(), 'email_verified': True},
            'E-poçt ünvanı təsdiqləndi.'
        )

    except Exception as e:
        db.session.rollback()
        logger.exception('verify_expert_email failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/experts", methods=['GET'])
@limiter.limit("60 per minute")
@token_required([2])
def get_experts():
    try:
        query = Expert.query
        # The assignment dropdown asks for verified only: an unverified address
        # cannot receive the one-time password, so assigning would be a dead end.
        if (request.args.get('verified_only') or '').lower() in ('1', 'true', 'yes'):
            query = query.filter(Expert.email_verified.is_(True))

        experts = query.order_by(Expert.surname.asc(), Expert.name.asc()).all()
        return handle_success([e.serialize() for e in experts], 'Experts fetched successfully.')

    except Exception as e:
        logger.exception('get_experts failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/experts/<int:expert_id>", methods=['DELETE'])
@limiter.limit("60 per minute")
@token_required([2])
def delete_expert(expert_id):
    try:
        expert = Expert.query.get(expert_id)
        if not expert:
            return {'error': 'Ekspert tapılmadı.', 'status': 404}, 404

        assigned = Project.query.filter_by(expert=expert.email).count()
        if assigned:
            return {
                'error': f'Bu ekspert {assigned} layihəyə təyin olunub. Əvvəlcə təyinatı ləğv edin.',
                'status': 409
            }, 409

        account = Auth.query.filter_by(fin_kod=expert.email).first()
        if account and account.project_role == EXPERT_ROLE:
            db.session.delete(account)

        db.session.delete(expert)
        db.session.commit()
        return handle_success({'id': expert_id}, 'Ekspert silindi.')

    except Exception as e:
        db.session.rollback()
        logger.exception('delete_expert failed')
        return handle_global_exception(str(e))


# -------------------------------------------------------- admin: assignment ---

@expert_bp.route("/api/set-expert", methods=['POST'])
@limiter.limit("60 per minute")
@token_required([2])
def set_expert():
    try:
        data = request.get_json() or {}
        for field in ('email', 'project_code'):
            if not data.get(field):
                return {'error': f'{field} field is required.', 'status': 400}, 400

        email = (data['email'] or '').strip().lower()

        # `project_code` is an INTEGER column; the old lookup stringified it and
        # then dereferenced the result without checking, so a miss was a 500.
        try:
            project_code = int(data['project_code'])
        except (TypeError, ValueError):
            return {'error': 'project_code must be a number.', 'status': 400}, 400

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return {'error': 'Layihə tapılmadı.', 'status': 404}, 404

        expert = Expert.query.filter_by(email=email).first()
        if not expert:
            return {'error': 'Ekspert tapılmadı.', 'status': 404}, 404

        if not expert.email_verified:
            return {
                'error': 'Ekspertin e-poçt ünvanı təsdiqlənməyib. '
                         'Təyinat məktubu göndərilə bilməz.',
                'status': 409
            }, 409

        if not project.submitted:
            return {'status': 409, 'error': 'Layihə hələ təqdim edilməyib.',
                    'message': 'Project not submitted.'}, 409

        project.expert = expert.email

        # A fresh one-time password every time the expert is appointed, so an
        # old mail cannot be replayed to get in.
        one_time_password = upsert_expert_account(expert)

        lead = User.query.filter_by(fin_kod=project.fin_kod).first()
        html = render_template(
            'email/set_expert_template.html',
            expert=expert,
            project=project,
            lead_name=f"{lead.name or ''} {lead.surname or ''}".strip() if lead else None,
            login_email=expert.email,
            one_time_password=one_time_password,
            login_url=f"{frontend_url()}/signin",
        )
        sent = send_email('Ekspert Təyinatı', expert.email, html)

        if not sent:
            # Nothing is committed, so the appointment did not silently happen
            # while the expert was never told about it.
            db.session.rollback()
            return {
                'error': 'Ekspertə məktub göndərilə bilmədi. Təyinat edilmədi.',
                'status': 502
            }, 502

        db.session.commit()

        return handle_success(
            {
                'project_code': project.project_code,
                'expert': expert.serialize(),
                'credentials_emailed': True,
            },
            'Ekspert təyin edildi və məlumatlar e-poçt ilə göndərildi.'
        )

    except Exception as e:
        db.session.rollback()
        logger.exception('set_expert failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/unset-expert", methods=['POST'])
@limiter.limit("60 per minute")
@token_required([2])
def unset_expert():
    try:
        data = request.get_json() or {}
        try:
            project_code = int(data.get('project_code'))
        except (TypeError, ValueError):
            return {'error': 'project_code must be a number.', 'status': 400}, 400

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return {'error': 'Layihə tapılmadı.', 'status': 404}, 404

        project.expert = None
        db.session.commit()
        return handle_success({'project_code': project_code}, 'Ekspert təyinatı ləğv edildi.')

    except Exception as e:
        db.session.rollback()
        logger.exception('unset_expert failed')
        return handle_global_exception(str(e))


# ------------------------------------------------------------ expert: work ---

@expert_bp.route("/api/expert/my-projects", methods=['GET'])
@limiter.limit("300 per minute")
@token_required([EXPERT_ROLE])
def expert_projects():
    """Every project this expert has been appointed to, with their own verdict."""
    try:
        email = caller_email()
        expert = Expert.query.filter_by(email=email).first()

        projects = Project.query.filter_by(expert=email).all()
        scored = {
            a.project_code: a
            for a in Assessment.query.filter_by(expert=email).all()
        }

        items = []
        for project in projects:
            lead = User.query.filter_by(fin_kod=project.fin_kod).first()
            assessment = scored.get(project.project_code)
            items.append({
                'project_code': project.project_code,
                'project_name': project.project_name,
                'project_annotation': project.project_annotation,
                'submitted': bool(project.submitted),
                'submitted_at': project.submitted_at.isoformat() if project.submitted_at else None,
                'lead_name': f"{lead.name or ''} {lead.surname or ''}".strip() if lead else None,
                'assessment': assessment.serialize() if assessment else None,
                'max_total': MAX_TOTAL,
            })

        return handle_success({
            'expert': expert.serialize() if expert else {'email': email},
            'projects': items,
            # The sheet is served with the work so the client renders the rows
            # from one source of truth instead of duplicating the weights.
            'criteria': CRITERIA,
            'max_total': MAX_TOTAL,
        }, 'Assigned projects fetched successfully.')

    except Exception as e:
        logger.exception('expert_projects failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/expert/assessment/<int:project_code>", methods=['GET'])
@limiter.limit("300 per minute")
@token_required([2, EXPERT_ROLE])
def get_assessment(project_code):
    """The verdicts on one project. An expert sees only their own."""
    try:
        project, error = expert_project_or_error(project_code)
        if error:
            return error

        query = Assessment.query.filter_by(project_code=project.project_code)
        if g.user.get('role') != 2:
            query = query.filter_by(expert=caller_email())

        return handle_success(
            [a.serialize() for a in query.all()], 'Assessment fetched successfully.'
        )

    except Exception as e:
        logger.exception('get_assessment failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/assessment/criteria", methods=['GET'])
@limiter.limit("300 per minute")
@token_required([2, EXPERT_ROLE])
def assessment_criteria():
    """The scoring sheet: the criteria, their weights and the total."""
    return handle_success({'criteria': CRITERIA, 'max_total': MAX_TOTAL},
                          'Criteria fetched successfully.')


@expert_bp.route("/api/expert/assessment", methods=['POST'])
@limiter.limit("120 per minute")
@token_required([EXPERT_ROLE])
def save_assessment():
    """Record or revise this expert's scoring sheet for a project.

    The total is always recomputed from the per-criterion scores — it is never
    taken from the client, so it cannot disagree with the breakdown behind it.
    """
    try:
        data = request.get_json() or {}

        project, error = expert_project_or_error(data.get('project_code'))
        if error:
            return error

        criteria, error_message = parse_criteria(data.get('criteria'))
        if error_message:
            return {'error': error_message, 'status': 400}, 400

        score = total_of(criteria)

        email = caller_email()
        assessment = Assessment.query.filter_by(
            project_code=project.project_code, expert=email
        ).first()

        if not assessment:
            assessment = Assessment(
                project_code=project.project_code, expert=email,
                created_at=datetime.utcnow(),
            )
            db.session.add(assessment)

        assessment.criteria = criteria
        assessment.assessment = score
        assessment.note = (data.get('note') or '').strip() or None
        assessment.updated_at = datetime.utcnow()
        db.session.commit()

        return handle_success(assessment.serialize(), 'Qiymətləndirmə yadda saxlanıldı.')

    except Exception as e:
        db.session.rollback()
        logger.exception('save_assessment failed')
        return handle_global_exception(str(e))


@expert_bp.route("/api/project/<int:project_code>/assessments", methods=['GET'])
@limiter.limit("300 per minute")
@token_required([2])
def project_assessments(project_code):
    """Admin view: every expert verdict on a project, with the expert named."""
    try:
        rows = Assessment.query.filter_by(project_code=project_code).all()
        experts = {e.email: e for e in Expert.query.all()}

        items = []
        for row in rows:
            expert = experts.get(row.expert)
            item = row.serialize()
            item['expert_name'] = expert.full_name() if expert else row.expert
            item['expert_degree'] = expert.scientific_degree if expert else None
            items.append(item)

        scored = [i['assessment'] for i in items if i['assessment'] is not None]
        return handle_success({
            'assessments': items,
            'criteria': CRITERIA,
            'max_total': MAX_TOTAL,
            'expert_count': len(items),
            # What the admin actually compares projects on when several experts
            # have scored the same one.
            'average_total': round(sum(scored) / len(scored), 2) if scored else None,
        }, 'Assessments fetched successfully.')

    except Exception as e:
        logger.exception('project_assessments failed')
        return handle_global_exception(str(e))

# ------------------------------------------------------ admin: PDF export ---

from io import BytesIO
from flask import make_response
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

PDF_FONT = 'NotoSans'


def _register_pdf_font():
    """Azerbaijani needs a Unicode face; Helvetica would drop the diacritics."""
    try:
        pdfmetrics.getFont(PDF_FONT)
    except Exception:
        pdfmetrics.registerFont(
            TTFont(PDF_FONT, './utils/noto_sans/static/NotoSans-Regular.ttf')
        )


@expert_bp.route("/api/project/<int:project_code>/assessments/pdf", methods=['GET'])
@limiter.limit("10 per minute")
@token_required([2])
def project_assessments_pdf(project_code):
    """Admin-only: every expert's scoring sheet for one project, as a PDF."""
    try:
        _register_pdf_font()

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return {'error': 'Layihə tapılmadı.', 'status': 404}, 404

        rows = Assessment.query.filter_by(project_code=project_code).all()
        experts = {e.email: e for e in Expert.query.all()}
        lead = User.query.filter_by(fin_kod=project.fin_kod).first()

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('T', parent=styles['Title'], fontName=PDF_FONT,
                                     fontSize=15, alignment=1, spaceAfter=10)
        head_style = ParagraphStyle('H', parent=styles['Heading2'], fontName=PDF_FONT,
                                    fontSize=12, spaceBefore=12, spaceAfter=6)
        body_style = ParagraphStyle('B', parent=styles['Normal'], fontName=PDF_FONT,
                                    fontSize=9, leading=12)
        cell_style = ParagraphStyle('C', parent=body_style, fontSize=8, leading=10)
        cell_bold = ParagraphStyle('CB', parent=cell_style, fontSize=8, leading=10)

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                leftMargin=28, rightMargin=28, topMargin=32, bottomMargin=28)
        elements = [
            Paragraph('Ekspert Qiymətləndirmə Hesabatı', title_style),
            Paragraph(f"<b>Layihə:</b> {rl_text(project.project_name or 'Adsız layihə')}", body_style),
            Paragraph(f"<b>Layihə kodu:</b> {project.project_code}", body_style),
        ]
        if lead:
            elements.append(Paragraph(
                rl_text(f"Layihə rəhbəri: {(lead.name or '')} {(lead.surname or '')}".strip()),
                body_style))

        if not rows:
            elements.append(Spacer(1, 16))
            elements.append(Paragraph('Bu layihə üzrə qiymətləndirmə yoxdur.', body_style))
        else:
            scored = [r.assessment for r in rows if r.assessment is not None]
            if scored:
                elements.append(Paragraph(
                    f"<b>Ekspert sayı:</b> {len(rows)} &nbsp;&nbsp; "
                    f"<b>Orta bal:</b> {round(sum(scored) / len(scored), 2)} / {MAX_TOTAL}",
                    body_style))

            for assessment in rows:
                expert = experts.get(assessment.expert)
                name = expert.full_name() if expert else assessment.expert
                elements.append(Paragraph(rl_text(f'Ekspert: {name}'), head_style))
                elements.append(Paragraph(f'<b>E-poçt:</b> {rl_text(assessment.expert)}', body_style))

                data = [[
                    Paragraph('№', cell_bold),
                    Paragraph('Qiymətləndirmə meyarı', cell_bold),
                    Paragraph('Maks. bal', cell_bold),
                    Paragraph('Ekspert balı', cell_bold),
                    Paragraph('Qeyd', cell_bold),
                ]]
                for row in assessment.breakdown():
                    data.append([
                        Paragraph(str(row['number']), cell_style),
                        Paragraph(rl_text(row['title']), cell_style),
                        Paragraph(str(row['max_score']), cell_style),
                        Paragraph('' if row['score'] is None else str(row['score']), cell_style),
                        Paragraph(rl_text(row['note']) if row['note'] else '', cell_style),
                    ])
                data.append([
                    Paragraph('', cell_bold),
                    Paragraph('YEKUN BAL', cell_bold),
                    Paragraph(str(MAX_TOTAL), cell_bold),
                    Paragraph(f"{assessment.assessment if assessment.assessment is not None else 0}", cell_bold),
                    Paragraph('', cell_bold),
                ])

                widths = [doc.width * w for w in (0.05, 0.42, 0.10, 0.10, 0.33)]
                table = Table(data, colWidths=widths, repeatRows=1)
                table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTNAME', (0, 0), (-1, -1), PDF_FONT),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                    ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
                ]))
                elements.append(Spacer(1, 6))
                elements.append(table)

                if assessment.note:
                    elements.append(Spacer(1, 6))
                    elements.append(Paragraph(f'<b>Ümumi rəy:</b> {rl_text(assessment.note)}', body_style))
                elements.append(Spacer(1, 10))

        doc.build(elements)
        buffer.seek(0)

        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = (
            f'attachment; filename=assessments_{project_code}.pdf'
        )
        return response

    except Exception as e:
        logger.exception('project_assessments_pdf failed')
        return handle_global_exception(str(e))
