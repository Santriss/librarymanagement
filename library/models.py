from django.db import models
from django.contrib.auth.models import User
from datetime import datetime, timedelta, date


# ─── Límite de préstamos por tipo de estudiante ───────────────────────────────
BOOK_LIMIT = {
    'pregrado': 3,
    'posgrado': 5,
    'prueba':   1,
}

# ─── Umbral de multa acumulada para bloqueo automático ───────────────────────
FINE_BLOCK_THRESHOLD = 50   # en pesos/dólares


def calculate_fine(issue_date):
    """
    Calcula la multa escalonada según días de retraso (vence a los 15 días).
    Retorna: (overdue_days, fine_total, is_suspended)
      - Días 1-5:   $5/día
      - Días 6-15:  $10/día
      - Días >15:   $20/día  +  suspensión 30 días
    """
    days_since_issue = (date.today() - issue_date).days
    overdue_days = max(0, days_since_issue - 15)

    if overdue_days == 0:
        return 0, 0, False

    fine = 0
    suspended = False

    if overdue_days <= 5:
        fine = overdue_days * 5
    elif overdue_days <= 15:
        fine = (5 * 5) + ((overdue_days - 5) * 10)
    else:
        fine = (5 * 5) + (10 * 10) + ((overdue_days - 15) * 20)
        suspended = True

    return overdue_days, fine, suspended


class StudentExtra(models.Model):
    STUDENT_TYPE_CHOICES = [
        ('pregrado', 'Pregrado'),
        ('posgrado', 'Posgrado'),
        ('prueba',   'Prueba Académica'),
    ]
    user            = models.OneToOneField(User, on_delete=models.CASCADE)
    enrollment      = models.CharField(max_length=40)
    branch          = models.CharField(max_length=40)
    student_type    = models.CharField(max_length=20, choices=STUDENT_TYPE_CHOICES,
                                       default='pregrado')
    suspended_until = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.user.first_name + '[' + str(self.enrollment) + ']'

    @property
    def get_name(self):
        return self.user.first_name

    @property
    def getuserid(self):
        return self.user.id

    @property
    def book_limit(self):
        return BOOK_LIMIT.get(self.student_type, 3)

    @property
    def is_suspended(self):
        if self.suspended_until and self.suspended_until >= date.today():
            return True
        return False


class Book(models.Model):
    catchoice = [
        ('education',     'Education'),
        ('entertainment', 'Entertainment'),
        ('comics',        'Comics'),
        ('biography',     'Biographie'),
        ('history',       'History'),
    ]
    name     = models.CharField(max_length=30)
    isbn     = models.PositiveIntegerField()
    author   = models.CharField(max_length=40)
    category = models.CharField(max_length=30, choices=catchoice, default='education')

    def __str__(self):
        return str(self.name) + '[' + str(self.isbn) + ']'


def get_expiry():
    return datetime.today() + timedelta(days=15)


class IssuedBook(models.Model):
    enrollment  = models.CharField(max_length=30)
    isbn        = models.CharField(max_length=30)
    issuedate   = models.DateField(auto_now=True)
    expirydate  = models.DateField(default=get_expiry)
    statuschoice = [
        ('Issued',   'Issued'),
        ('Returned', 'Returned'),
    ]
    status = models.CharField(max_length=20, choices=statuschoice, default='Issued')

    def __str__(self):
        return self.enrollment
