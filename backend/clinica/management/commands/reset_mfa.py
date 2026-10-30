from django.core.management.base import BaseCommand, CommandError

from clinica.models import User


class Command(BaseCommand):
    help = "Reinicia el segundo factor de un usuario (p. ej. si perdió el teléfono): en su próximo ingreso vuelve a enrolarse."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, username, **options):
        if not User.objects.filter(username=username).update(mfa_secret="", mfa_enabled=False, mfa_last_step=0):
            raise CommandError(f"No existe el usuario {username}")
        self.stdout.write(f"MFA de {username} reiniciado; se enrolará de nuevo al ingresar.")
