from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore


class HeaderSessionMiddleware:
    """
    Keeps users authenticated both in normal browsers and inside cross-origin
    iframe previews where third-party cookies are blocked.

    Supports authentication via:
      1. ``X-Session-Token: <session_key>``
      2. ``Authorization: Bearer <session_key>``
      3. ``?auth_token=<session_key>`` (GET requests only)

    The URL parameter is deliberately restricted to safe methods so a shared
    link can never be used to trigger a state change on someone else's behalf.
    """

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = (
            request.headers.get("X-Session-Token")
            or request.META.get("HTTP_X_SESSION_TOKEN")
            or ""
        )
        if not token and "Authorization" in request.headers:
            auth = request.headers["Authorization"].strip()
            if auth.startswith("Bearer "):
                token = auth[7:].strip()
        if not token and request.method in self.SAFE_METHODS:
            token = request.GET.get("auth_token", "").strip()

        # If the user is not yet authenticated via cookie, authenticate via token.
        if token and len(token) <= 64 and (not hasattr(request, "user") or not request.user.is_authenticated):
            try:
                session = SessionStore(session_key=token)
                user_id = session.get(SESSION_KEY)
                backend = session.get(BACKEND_SESSION_KEY)
                if user_id:
                    User = get_user_model()
                    user = User.objects.filter(pk=user_id, is_active=True).first()
                    if user:
                        user.backend = backend or "django.contrib.auth.backends.ModelBackend"
                        request.user = user
                        request.session = session
            except Exception:
                pass

        response = self.get_response(request)

        # Behind an HTTPS proxy, make the cookies usable from the preview iframe.
        is_https = request.is_secure() or request.headers.get("x-forwarded-proto") == "https"
        if is_https:
            for cookie_name in ("sessionid", "csrftoken"):
                if cookie_name in response.cookies:
                    response.cookies[cookie_name]["samesite"] = "None"
                    response.cookies[cookie_name]["secure"] = True

        return response
