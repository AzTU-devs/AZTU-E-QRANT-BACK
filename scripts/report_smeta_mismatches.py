"""Report (do not modify) projects whose stored smeta aggregate differs from the
recomputed line-item totals, or that contain negative amounts.

    venv/bin/python -m scripts.report_smeta_mismatches
"""
from scripts._bootstrap import app_context
from models.projectModel import Project
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.rentModel import Rent
from models.smetaModels.salaryModel import Salary
from models.smetaModels.subjectModel import SubjectOfPurchase
from models.smetaModels.other_expensesModel import other_exp_model
from models.smetaModels.servicesTableModel import ServicesOfPurchase


def _sum(rows, attr):
    return sum(getattr(r, attr) or 0 for r in rows)


def main():
    with app_context():
        mismatches = 0
        negatives = 0
        for project in Project.query.all():
            code = project.project_code
            expected = {
                'total_equipment': _sum(SubjectOfPurchase.query.filter_by(project_code=code).all(), 'total_amount'),
                'total_services': _sum(ServicesOfPurchase.query.filter_by(project_code=code).all(), 'total_amount'),
                'total_rent': _sum(Rent.query.filter_by(project_code=code).all(), 'total_amount'),
                'other_expenses': _sum(other_exp_model.query.filter_by(project_code=code).all(), 'total_amount'),
                'total_salary': _sum(Salary.query.filter_by(project_code=code).all(), 'total_salary'),
            }
            smeta = Smeta.query.filter(Smeta.project_code.in_([code, str(code)])).first()
            stored = {k: (getattr(smeta, k) or 0) for k in expected} if smeta else {k: 0 for k in expected}
            diffs = {k: (stored[k], expected[k]) for k in expected if stored[k] != expected[k]}
            if diffs:
                mismatches += 1
                print(f"project {code}: aggregate != line items -> "
                      + ", ".join(f"{k} stored={s} computed={e}" for k, (s, e) in diffs.items()))

            # Negative line amounts anywhere.
            for model, attr in ((Rent, 'total_amount'), (SubjectOfPurchase, 'total_amount'),
                                (ServicesOfPurchase, 'total_amount'), (other_exp_model, 'total_amount'),
                                (Salary, 'total_salary')):
                for row in model.query.filter_by(project_code=code).all():
                    if (getattr(row, attr) or 0) < 0:
                        negatives += 1
                        print(f"project {code}: NEGATIVE {model.__tablename__}.{attr}={getattr(row, attr)} (id={row.id})")

        print(f"\n{mismatches} project(s) with aggregate/line-item mismatch; {negatives} negative amount(s).")


if __name__ == '__main__':
    main()
