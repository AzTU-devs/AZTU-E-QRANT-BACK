"""Re-sanitise existing announcement HTML with the current bleach allow-list.

Announcements authored before the sanitizer was applied may hold unsafe HTML.
This re-runs `AnnouncementController.sanitize_html` over every stored
announcement. Dry-run by default; pass --apply to write.

    venv/bin/python -m scripts.resanitize_announcements [--apply]
"""
import sys

from scripts._bootstrap import app_context
from extentions.db import db
from models.announcementModel import Announcement
from controllers.AnnouncementController import sanitize_html


def main(apply_changes):
    changed = 0
    with app_context():
        for a in Announcement.query.all():
            cleaned = sanitize_html(a.content or '')
            if cleaned != (a.content or ''):
                changed += 1
                print(f"[{'APPLY' if apply_changes else 'DRY'}] announcement id={a.id} would change "
                      f"({len(a.content or '')} -> {len(cleaned)} chars)")
                if apply_changes:
                    a.content = cleaned
        if apply_changes and changed:
            db.session.commit()
    print(f"{changed} announcement(s) {'updated' if apply_changes else 'need cleaning'}.")


if __name__ == '__main__':
    main('--apply' in sys.argv[1:])
