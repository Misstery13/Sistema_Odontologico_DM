from rest_framework.authtoken.models import Token


class TenantMiddleware:
    """Resuelve la clínica (tenant) del usuario a partir del token y la deja en request.tenant."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        key = request.headers.get("Authorization", "").removeprefix("Token ").strip()
        if key:
            token = Token.objects.select_related("user").filter(key=key, user__is_active=True).first()
            if token:
                request.tenant = token.user.clinic_id
        return self.get_response(request)
