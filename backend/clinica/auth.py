from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
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
    "dentists": (STAFF, set()),
    "audit": ({"admin", "auditor"}, set()),
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
        resource = getattr(view, "action_resources", {}).get(getattr(view, "action", None), view.resource)
        read, write = PERMISSIONS[resource]
        return request.user.role in (read if request.method in SAFE_METHODS else write)
