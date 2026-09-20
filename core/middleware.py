from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore


class HeaderSessionMiddleware:
    """
    Ensures users stay authenticated both in normal browser environments and
    inside cross-origin iframe previews where third-party cookies are blocked.
    Supports authentication via:
      1. X-Session-Token HTTP header
      2. Authorization: Bearer <session_key> header
      3. ?auth_token=<session_key> URL query parameter
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = (
            request.headers.get("X-Session-Token")
            or request.GET.get("auth_token")
            or request.META.get("HTTP_X_SESSION_TOKEN")
        )
        if not token and "Authorization" in request.headers:
            auth = request.headers["Authorization"].strip()
            if auth.startswith("Bearer "):
                token = auth[7:].strip()

        # If user is not yet authenticated via cookie, authenticate via token
        if token and (not hasattr(request, "user") or not request.user.is_authenticated):
            try:
                session = SessionStore(session_key=token)
                user_id = session.get(SESSION_KEY)
                backend = session.get(BACKEND_SESSION_KEY)
                if user_id:
                    User = get_user_model()
                    user = User.objects.filter(pk=user_id).first()
                    if user:
                        user.backend = backend or "django.contrib.auth.backends.ModelBackend"
                        request.user = user
                        request.session = session
            except Exception:
                pass

        response = self.get_response(request)

        # Over HTTPS or reverse proxies, ensure SameSite=None and Secure on cookies
        is_https = request.is_secure() or request.headers.get("x-forwarded-proto") == "https"
        if is_https:
            for cookie_name in ("sessionid", "csrftoken"):
                if cookie_name in response.cookies:
                    response.cookies[cookie_name]["samesite"] = "None"
                    response.cookies[cookie_name]["secure"] = True

        return response
