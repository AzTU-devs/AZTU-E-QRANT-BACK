"""Authoritative, server-side budget (smeta) totals.

The `Smeta` row is an aggregate of the line-item tables. Historically every
controller trusted the client's `total_*`/`total_amount` and adjusted the
aggregate incrementally, so a lead could send a small total and slip an
over-budget proposal past the cap (finding B-H1).

The rule now: line totals are computed here from price/quantity/duration, and
the aggregate is RECOMPUTED from the line items after every change — the client
never gets to state a total. Only the two non-line-item aggregates the UI
derives itself (tax and social-fund contributions) are set directly, and even
those are validated and gated to an allow-list.
"""

from extentions.db import db
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.rentModel import Rent
from models.smetaModels.salaryModel import Salary
from models.smetaModels.subjectModel import SubjectOfPurchase
from models.smetaModels.other_expensesModel import other_exp_model
from models.smetaModels.servicesTableModel import ServicesOfPurchase

# The only aggregate columns a client may set directly (via /api/update-smeta-field
# or /api/edit-smeta): the tax total and the social-fund contribution. Everything
# else is derived from line items and must never be hand-written.
DIRECT_SMETA_FIELDS = ('total_fee', 'defense_fund')


def line_total(unit_price, quantity, duration=1):
    """A line's total from its parts. Callers validate the inputs first."""
    return (unit_price or 0) * (quantity or 0) * (duration if duration is not None else 1)


def _sum(rows, attr):
    return sum(getattr(r, attr) or 0 for r in rows)


def get_or_create_smeta(project_code):
    """The aggregate row for a project, matching both the int and legacy-str
    spellings of `project_code`, creating it if absent."""
    code = int(project_code)
    smeta = Smeta.query.filter(Smeta.project_code.in_([code, str(code)])).first()
    if not smeta:
        smeta = Smeta(project_code=code)
        db.session.add(smeta)
    return smeta


def recompute_project_smeta(project_code):
    """Rebuild the five line-item category totals on the aggregate row from the
    line items themselves. Leaves `total_fee`/`defense_fund` untouched. Staged
    on the session; the caller commits. Returns the aggregate row."""
    code = int(project_code)
    smeta = get_or_create_smeta(code)
    smeta.total_equipment = _sum(SubjectOfPurchase.query.filter_by(project_code=code).all(), 'total_amount')
    smeta.total_services = _sum(ServicesOfPurchase.query.filter_by(project_code=code).all(), 'total_amount')
    smeta.total_rent = _sum(Rent.query.filter_by(project_code=code).all(), 'total_amount')
    smeta.other_expenses = _sum(other_exp_model.query.filter_by(project_code=code).all(), 'total_amount')
    smeta.total_salary = _sum(Salary.query.filter_by(project_code=code).all(), 'total_salary')
    return smeta


def project_grand_total(project_code):
    """The authoritative grand total = the five recomputed category totals plus
    the tax and social-fund aggregates. This is what the submission cap check
    compares against — never the stored aggregate the client could have moved."""
    smeta = recompute_project_smeta(project_code)
    return sum([
        smeta.total_salary or 0,
        smeta.total_equipment or 0,
        smeta.total_services or 0,
        smeta.total_rent or 0,
        smeta.other_expenses or 0,
        smeta.total_fee or 0,
        smeta.defense_fund or 0,
    ])
