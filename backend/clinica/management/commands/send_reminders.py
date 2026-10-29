from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from clinica.models import Appointment
from clinica.notify import notify


class Command(BaseCommand):
    help = "Envía recordatorios de 48h y 24h de las citas próximas (RF-11). Idempotente: correrlo cada hora."

    def handle(self, *args, **options):
        now = timezone.now()
        sent = 0
        upcoming = Appointment.objects.filter(start__gt=now, start__lte=now + timedelta(hours=48), status__in=["programado", "confirmado"])
        for a in upcoming.select_related("patient", "clinic"):
            left = a.start - now
            if left > timedelta(hours=24):
                sent += notify(a, "recordatorio_48h")
            else:
                sent += notify(a, "recordatorio_24h")
        self.stdout.write(f"Recordatorios enviados: {sent}")
