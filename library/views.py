from django.shortcuts import redirect, render
from django.http import HttpResponseRedirect
from . import forms, models
from django.contrib.auth.models import Group
from django.contrib import auth
from django.contrib.auth.decorators import login_required, user_passes_test
from datetime import datetime, timedelta, date
from django.core.mail import send_mail
from librarymanagement.settings import EMAIL_HOST_USER


# ─── Helpers ─────────────────────────────────────────────────────────────────

def home_view(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect('afterlogin')
    return render(request, 'library/index.html')

def studentclick_view(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect('afterlogin')
    return render(request, 'library/studentclick.html')

def adminclick_view(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect('afterlogin')
    return render(request, 'library/adminclick.html')

def is_admin(user):
    return user.is_superuser or user.is_staff

def is_student(user):
    return user.groups.filter(name='STUDENT').exists()


# ─── Sign-up ─────────────────────────────────────────────────────────────────

def studentsignup_view(request):
    form1 = forms.StudentUserForm()
    form2 = forms.StudentExtraForm()
    mydict = {'form1': form1, 'form2': form2}
    if request.method == 'POST':
        form1 = forms.StudentUserForm(request.POST)
        form2 = forms.StudentExtraForm(request.POST)
        if form1.is_valid() and form2.is_valid():
            user = form1.save()
            user.set_password(user.password)
            user.save()
            f2 = form2.save(commit=False)
            f2.user = user
            f2.save()
            my_student_group = Group.objects.get_or_create(name='STUDENT')
            my_student_group[0].user_set.add(user)
        return HttpResponseRedirect('studentlogin')
    return render(request, 'library/studentsignup.html', context=mydict)


# ─── After-login router ───────────────────────────────────────────────────────

def afterlogin_view(request):
    if is_admin(request.user):
        return render(request, 'library/adminafterlogin.html')
    elif is_student(request.user):
        return render(request, 'library/studentafterlogin.html')


# ─── Admin: books ─────────────────────────────────────────────────────────────

@login_required(login_url='adminlogin')
@user_passes_test(is_admin)
def addbook_view(request):
    form = forms.BookForm()
    if request.method == 'POST':
        form = forms.BookForm(request.POST)
        if form.is_valid():
            form.save()
            return render(request, 'library/bookadded.html')
    return render(request, 'library/addbook.html', {'form': form})

@login_required(login_url='adminlogin')
@user_passes_test(is_admin)
def viewbook_view(request):
    books = models.Book.objects.all()
    return render(request, 'library/viewbook.html', {'books': books})


# ─── Utilidad: estado de bloqueo del estudiante ──────────────────────────────

def _check_student_block(student):
    """
    Revisa si el estudiante debe ser bloqueado para nuevos préstamos.
    Devuelve (bloqueado:bool, razon:str)
    """
    # 1) Suspensión por retraso grave (>15 días)
    if student.is_suspended:
        return True, f"Cuenta suspendida hasta {student.suspended_until}."

    active_books = models.IssuedBook.objects.filter(
        enrollment=student.enrollment, status='Issued'
    )

    total_fine = 0
    for ib in active_books:
        overdue_days, fine, suspended = models.calculate_fine(ib.issuedate)

        # Si este libro acaba de generar suspensión, guardarla
        if suspended and not student.is_suspended:
            student.suspended_until = date.today() + timedelta(days=30)
            student.save()
            return True, (
                f"Cuenta suspendida 30 días (hasta {student.suspended_until}) "
                f"por retraso superior a 15 días."
            )

        # Retraso mayor a 7 días bloquea inmediatamente
        if overdue_days > 7:
            return True, (
                f"Tiene un libro con {overdue_days} días de retraso (máximo 7 permitido)."
            )

        total_fine += fine

    # Multa acumulada supera el umbral
    if total_fine > models.FINE_BLOCK_THRESHOLD:
        return True, (
            f"Multa acumulada de ${total_fine} supera el límite de "
            f"${models.FINE_BLOCK_THRESHOLD}."
        )

    return False, ""


# ─── Admin: issue book ───────────────────────────────────────────────────────

@login_required(login_url='adminlogin')
@user_passes_test(is_admin)
def issuebook_view(request):
    form = forms.IssuedBookForm()
    context = {'form': form}

    if request.method == 'POST':
        form = forms.IssuedBookForm(request.POST)
        context['form'] = form
        if form.is_valid():
            enrollment = request.POST.get('enrollment2')
            isbn       = request.POST.get('isbn2')

            try:
                student = models.StudentExtra.objects.get(enrollment=enrollment)
            except models.StudentExtra.DoesNotExist:
                context['error'] = "Estudiante no encontrado."
                return render(request, 'library/issuebook.html', context)

            # ── Verificar bloqueo ───────────────────────────────────────────
            blocked, reason = _check_student_block(student)
            if blocked:
                context['error'] = f"Préstamo bloqueado: {reason}"
                return render(request, 'library/issuebook.html', context)

            # ── Verificar límite de libros según tipo ───────────────────────
            active_count = models.IssuedBook.objects.filter(
                enrollment=enrollment, status='Issued'
            ).count()

            if active_count >= student.book_limit:
                context['error'] = (
                    f"El estudiante ({student.get_student_type_display()}) ya tiene "
                    f"{active_count}/{student.book_limit} libros prestados."
                )
                return render(request, 'library/issuebook.html', context)

            # ── Todo OK, registrar préstamo ─────────────────────────────────
            obj = models.IssuedBook(enrollment=enrollment, isbn=isbn)
            obj.save()
            return render(request, 'library/bookissued.html')

    return render(request, 'library/issuebook.html', context)


# ─── Admin: view issued books ────────────────────────────────────────────────

@login_required(login_url='adminlogin')
@user_passes_test(is_admin)
def viewissuedbook_view(request):
    issuedbooks = models.IssuedBook.objects.all()
    li = []
    for ib in issuedbooks:
        issdate = ib.issuedate.strftime('%d-%m-%Y')
        expdate = ib.expirydate.strftime('%d-%m-%Y')

        overdue_days, fine, suspended = models.calculate_fine(ib.issuedate)

        # Auto-aplicar suspensión si corresponde
        if suspended and ib.status == 'Issued':
            try:
                st = models.StudentExtra.objects.get(enrollment=ib.enrollment)
                if not st.is_suspended:
                    st.suspended_until = date.today() + timedelta(days=30)
                    st.save()
            except models.StudentExtra.DoesNotExist:
                pass

        fine_label = f"${fine}"
        if suspended:
            fine_label += " ⚠ SUSPENSIÓN"

        books    = list(models.Book.objects.filter(isbn=ib.isbn))
        students = list(models.StudentExtra.objects.filter(enrollment=ib.enrollment))
        for i, book in enumerate(books):
            s = students[i] if i < len(students) else None
            name       = s.get_name   if s else '—'
            enrollment = s.enrollment if s else ib.enrollment
            t = (name, enrollment, book.name, book.author,
                 issdate, expdate, fine_label, ib.status)
            li.append(t)

    return render(request, 'library/viewissuedbook.html', {'li': li})


@login_required(login_url='adminlogin')
@user_passes_test(is_admin)
def viewstudent_view(request):
    students = models.StudentExtra.objects.all()
    return render(request, 'library/viewstudent.html', {'students': students})


# ─── Student: view own issued books ─────────────────────────────────────────

@login_required(login_url='studentlogin')
def viewissuedbookbystudent(request):
    student    = models.StudentExtra.objects.filter(user_id=request.user.id)
    issuedbook = models.IssuedBook.objects.filter(enrollment=student[0].enrollment)

    li1 = []
    li2 = []
    for ib in issuedbook:
        books = models.Book.objects.filter(isbn=ib.isbn)
        for book in books:
            t = (request.user, student[0].enrollment, student[0].branch,
                 book.name, book.author)
            li1.append(t)

        issdate = ib.issuedate.strftime('%d-%m-%Y')
        expdate = ib.expirydate.strftime('%d-%m-%Y')

        overdue_days, fine, suspended = models.calculate_fine(ib.issuedate)

        fine_label = f"${fine}"
        if suspended:
            fine_label += " ⚠ CUENTA SUSPENDIDA"
        elif overdue_days > 7:
            fine_label += " ⚠ PRÉSTAMOS BLOQUEADOS"

        t = (issdate, expdate, fine_label, ib.status, ib.id)
        li2.append(t)

    return render(request, 'library/viewissuedbookbystudent.html',
                  {'li1': li1, 'li2': li2})


def returnbook(request, id):
    issued_book = models.IssuedBook.objects.get(pk=id)
    issued_book.status = 'Returned'
    issued_book.save()
    return redirect('viewissuedbookbystudent')


def aboutus_view(request):
    return render(request, 'library/aboutus.html')


def contactus_view(request):
    sub = forms.ContactusForm()
    if request.method == 'POST':
        sub = forms.ContactusForm(request.POST)
        if sub.is_valid():
            email   = sub.cleaned_data['Email']
            name    = sub.cleaned_data['Name']
            message = sub.cleaned_data['Message']
            send_mail(
                str(name) + ' || ' + str(email), message,
                EMAIL_HOST_USER, ['wapka1503@gmail.com'], fail_silently=False
            )
            return render(request, 'library/contactussuccess.html')
    return render(request, 'library/contactus.html', {'form': sub})
