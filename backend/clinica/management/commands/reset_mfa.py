from django.core.management.base import BaseCommand, CommandError

from clinica.models import User


class Command(BaseCommand):
    help = "Reinicia el segundo factor de un usuario (p. ej. si perdió el teléfono): en su próximo ingreso vuelve a enrolarse."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, username, **options):
        # vaciar el secreto obliga a re-enrolar; no es una contraseña fija
        if not User.objects.filter(username=username).update(mfa_secret="", mfa_enabled=False, mfa_last_step=0):  # nosec B106
            raise CommandError(f"No existe el usuario {username}")
        self.stdout.write(f"MFA de {username} reiniciado; se enrolará de nuevo al ingresar.")
