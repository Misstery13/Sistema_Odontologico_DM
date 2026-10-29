import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification

log = logging.getLogger("notificaciones")


def send(channel, recipient, text):
    # ponytail: adaptador simulado (solo log); conectar aquí Meta Cloud API (WhatsApp) / Twilio (SMS/email)
    log.info("[%s simulado] a %s: %s", channel, recipient, text)


def notify(appointment, kind):
    """Envía y registra un mensaje de la cita; devuelve False si ya se envió o no hay contacto."""
    p = appointment.patient
    channel, recipient = ("whatsapp", p.phone) if p.phone else ("email", p.email)
    if not recipient:
        return False
    when = timezone.localtime(appointment.start).strftime("%d/%m/%Y %H:%M")
    text = {
        "confirmacion": f"Hola {p.first_name}, tu cita en {appointment.clinic} quedó agendada para el {when}.",
        "recordatorio_48h": f"Hola {p.first_name}, te recordamos tu cita en {appointment.clinic} el {when} (en 2 días).",
        "recordatorio_24h": f"Hola {p.first_name}, te esperamos mañana {when} en {appointment.clinic}.",
    }[kind]
    try:
        with transaction.atomic():  # savepoint: un duplicado no rompe la transacción de la petición
            Notification.objects.create(clinic=appointment.clinic, appointment=appointment, kind=kind, channel=channel, recipient=recipient, message=text)
    except IntegrityError:
        return False
    send(channel, recipient, text)
    return True
