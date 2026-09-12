from extentions.db import db
from datetime import datetime

# The scoring sheet an expert fills in for a project. The weights are fixed by
# the competition rules and add up to 100; `key` is what the stored breakdown
# is indexed by, so renaming a title later does not orphan existing scores.
CRITERIA = [
    {'key': 'scientific_relevance', 'number': 1, 'max_score': 15,
     'title': 'Layihənin elmi aktuallığı, elmi yeniliyi və problemin əsaslandırılması'},
    {'key': 'methodology', 'number': 2, 'max_score': 15,
     'title': 'Məqsəd və vəzifələrin aydınlığı, tədqiqat metodologiyasının elmi əsaslandırılması'},
    {'key': 'expected_results', 'number': 3, 'max_score': 15,
     'title': 'Gözlənilən nəticələrin elmi səviyyəsi, elmi və praktiki əhəmiyyəti'},
    {'key': 'priority_alignment', 'number': 4, 'max_score': 10,
     'title': 'Layihənin müsabiqənin prioritet istiqamətlərinə uyğunluğu'},
    {'key': 'team_capacity', 'number': 5, 'max_score': 15,
     'title': 'Layihə rəhbəri və komandanın elmi potensialı, kvalifikasiyası və müvafiq tədqiqat təcrübəsi'},
    {'key': 'infrastructure', 'number': 6, 'max_score': 5,
     'title': 'Layihənin icrası üçün mövcud maddi-texniki baza və resursların yetərliliyi'},
    {'key': 'budget_justification', 'number': 7, 'max_score': 10,
     'title': 'Büdcənin əsaslandırılması, xərclərin məqsədəuyğunluğu və maliyyə səmərəliliyi'},
    {'key': 'innovation_potential', 'number': 8, 'max_score': 5,
     'title': 'Nəticələrin tətbiqi, innovasiya, patentləşdirmə və kommersiyalaşdırma potensialı'},
    {'key': 'strategic_fit', 'number': 9, 'max_score': 5,
     'title': 'Layihənin AzTU-nun strateji inkişaf məqsədlərinə uyğunluğu'},
    {'key': 'international', 'number': 10, 'max_score': 5,
     'title': 'Beynəlxalq əməkdaşlıq və nəticələrin beynəlxalq elmi görünürlük potensialı'},
]

CRITERIA_BY_KEY = {c['key']: c for c in CRITERIA}

# The sheet totals 100 by construction; derived rather than written down twice.
MAX_TOTAL = sum(c['max_score'] for c in CRITERIA)
MIN_SCORE = 0


def parse_criteria(raw):
    """Normalise a submitted scoring sheet into {key: {score, note}}.

    Accepts either a mapping keyed by criterion, or a list of objects carrying
    a `key`. Returns `(criteria, error)`; `error` names the first problem found
    so the expert is told which row is wrong rather than just "invalid".
    """
    if raw is None:
        return None, 'Qiymətləndirmə meyarları tələb olunur.'

    if isinstance(raw, list):
        raw = {item.get('key'): item for item in raw if isinstance(item, dict)}

    if not isinstance(raw, dict):
        return None, 'Qiymətləndirmə meyarları düzgün formatda deyil.'

    parsed = {}
    for definition in CRITERIA:
        key = definition['key']
        entry = raw.get(key)

        if entry is None:
            return None, f"{definition['number']}. meyar üzrə bal verilməyib."

        # A bare number is accepted as the score, with no note.
        if not isinstance(entry, dict):
            entry = {'score': entry}

        value = entry.get('score')
        if value is None or value == '':
            return None, f"{definition['number']}. meyar üzrə bal verilməyib."

        try:
            score = int(value)
        except (TypeError, ValueError):
            return None, f"{definition['number']}. meyar üzrə bal rəqəm olmalıdır."

        if not MIN_SCORE <= score <= definition['max_score']:
            return None, (f"{definition['number']}. meyar üzrə bal {MIN_SCORE} ilə "
                          f"{definition['max_score']} arasında olmalıdır.")

        parsed[key] = {
            'score': score,
            'note': (str(entry.get('note') or '').strip() or None),
        }

    return parsed, None


def total_of(criteria):
    """The sheet's total. Always derived — never taken from the client."""
    if not criteria:
        return 0
    return sum(int((criteria.get(c['key']) or {}).get('score') or 0) for c in CRITERIA)


class Assessment(db.Model):
    __tablename__ = 'assessment'
    # One verdict per expert per project — scoring again edits the same row
    # rather than stacking up duplicates.
    __table_args__ = (
        db.UniqueConstraint('project_code', 'expert', name='uq_assessment_project_expert'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.Integer, nullable=False)
    expert = db.Column(db.String, nullable=False)   # the expert's e-mail
    # The TOTAL out of 100, computed from `criteria`. Kept as a column so
    # listing and sorting projects by score needs no JSON arithmetic.
    assessment = db.Column(db.Integer)
    # {key: {score, note}} — the per-criterion breakdown behind the total.
    criteria = db.Column(db.JSON)
    note = db.Column(db.String)                     # the closing overall note
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def breakdown(self):
        """The sheet as an ordered list, ready to render as a table."""
        stored = self.criteria or {}
        rows = []
        for definition in CRITERIA:
            entry = stored.get(definition['key']) or {}
            rows.append({
                **definition,
                'score': entry.get('score'),
                'note': entry.get('note'),
            })
        return rows

    def serialize(self):
        return {
            'id': self.id,
            'project_code': self.project_code,
            'expert': self.expert,
            'assessment': self.assessment,
            'total': self.assessment,
            'max_total': MAX_TOTAL,
            'criteria': self.breakdown(),
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
