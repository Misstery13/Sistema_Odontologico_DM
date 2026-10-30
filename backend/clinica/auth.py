from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import User

STAFF = {"recepcion", "odontologo", "asistente"}

# RBAC (RNF-05): recurso -> (roles que leen, roles que escriben). Menor privilegio: admin no ve datos clínicos.
PERMISSIONS = {
    "patients": (STAFF, {"recepcion", "odontologo"}),
    "odontogram": (STAFF, {"odontologo"}),
    "treatments": (STAFF | {"auditor"}, {"odontologo"}),
    "notes": ({"odontologo", "asistente"}, {"odontologo", "asistente"}),
    "appointments": (STAFF, STAFF),
    "chairs": (STAFF | {"admin"}, {"admin"}),
    "dentists": (STAFF | {"auditor", "admin"}, set()),
    "audit": ({"admin", "auditor"}, set()),
    "perio": ({"odontologo", "asistente"}, {"odontologo"}),
    "prescriptions": ({"odontologo", "asistente"}, {"odontologo"}),
    "consents": ({"odontologo", "asistente"}, {"odontologo", "asistente"}),
    "consent_templates": ({"odontologo", "asistente", "admin"}, {"admin"}),
    "catalog": (STAFF | {"auditor", "admin"}, {"admin"}),
    "supplies": ({"asistente", "odontologo", "auditor", "admin"}, {"asistente", "admin"}),
    "budgets": (STAFF, {"odontologo"}),
    "budget_decision": (set(), {"recepcion", "odontologo"}),  # registra la aprobación del paciente
    "commissions": ({"auditor", "admin"}, {"auditor", "admin"}),
    "reports": ({"auditor", "admin"}, set()),
    "users": ({"admin"}, {"admin"}),
    "vitals": ({"odontologo", "asistente"}, {"odontologo", "asistente"}),
    "attachments": ({"odontologo", "asistente"}, {"odontologo", "asistente"}),
}


class ExpiringTokenAuthentication(TokenAuthentication):
    """Token que caduca tras SESSION_IDLE_MINUTES sin actividad."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        now = timezone.now()
        if user.last_activity and now - user.last_activity > timedelta(minutes=settings.SESSION_IDLE_MINUTES):
            token.delete()
            raise AuthenticationFailed("Sesión cerrada por inactividad")
        if not user.last_activity or now - user.last_activity > timedelta(seconds=30):  # evita un UPDATE por request
            User.objects.filter(pk=user.pk).update(last_activity=now)
        return user, token


class RolePermission(BasePermission):
    """La vista declara `resource` (y opcionalmente `action_resources` por acción)."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated or request.tenant is None:
            return False
        if request.user.must_change_password:
            raise PermissionDenied("Debes cambiar tu contraseña temporal antes de continuar")
        resource = getattr(view, "action_resources", {}).get(getattr(view, "action", None), view.resource)
        read, write = PERMISSIONS[resource]
        return request.user.role in (read if request.method in SAFE_METHODS else write)
