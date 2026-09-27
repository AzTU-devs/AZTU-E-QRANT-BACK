"""Report (do not modify) projects whose max_smeta_amount / collaborator_limit
differ from their competition's values — i.e. rows a lead may have edited before
those fields were locked (finding B-H1).

    venv/bin/python -m scripts.report_project_cap_overrides
"""
from scripts._bootstrap import app_context
from models.projectModel import Project
from models.competitionModel import Competition


def main():
    with app_context():
        competitions = {c.id: c for c in Competition.query.all()}
        overrides = 0
        for project in Project.query.all():
            comp = competitions.get(project.competition_id)
            if not comp:
                continue
            if project.max_smeta_amount != comp.max_smeta_amount or \
               project.collaborator_limit != comp.collaborator_limit:
                overrides += 1
                print(f"project {project.project_code} (competition {comp.code}): "
                      f"max_smeta_amount={project.max_smeta_amount} (comp {comp.max_smeta_amount}), "
                      f"collaborator_limit={project.collaborator_limit} (comp {comp.collaborator_limit})")
        print(f"\n{overrides} project(s) differ from their competition's caps. "
              f"Review before overwriting — some may be legitimate per-project adjustments.")


if __name__ == '__main__':
    main()
