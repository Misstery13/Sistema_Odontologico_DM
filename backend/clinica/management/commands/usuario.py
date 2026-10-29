import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from clinica.models import ROLES, Clinic, User


class Command(BaseCommand):
    help = "Crea un usuario de una clínica con su rol, o le cambia la contraseña si ya existe. La contraseña se pide por teclado."

    def add_arguments(self, parser):
        parser.add_argument("clinica", help="Nombre exacto de la clínica")
        parser.add_argument("username")
        parser.add_argument("rol", choices=[r for r, _ in ROLES])
        parser.add_argument("--nombre", default="")
        parser.add_argument("--apellido", default="")

    def handle(self, clinica, username, rol, nombre, apellido, **options):
        clinic = Clinic.objects.filter(name=clinica).first()
        if not clinic:
            raise CommandError(f"No existe la clínica «{clinica}»; créala con `manage.py nueva_clinica`")
        user = User(username=username, clinic=clinic, role=rol, first_name=nombre, last_name=apellido)
        existing = User.objects.filter(username=username).first()
        if existing and existing.clinic_id != clinic.pk:
            raise CommandError("Ese usuario pertenece a otra clínica")
        user = existing or user
        user.role, user.clinic = rol, clinic
        password = getpass.getpass("Contraseña: ")
        if password != getpass.getpass("Repite la contraseña: "):
            raise CommandError("Las contraseñas no coinciden")
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        user.set_password(password)
        user.save()
        self.stdout.write(f"Usuario {username} ({rol}) {'actualizado' if existing else 'creado'} en «{clinic.name}».")
