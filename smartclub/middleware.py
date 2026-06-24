from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class CanonicalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        canonical_host = getattr(settings, "CANONICAL_HOST", "")
        if canonical_host and not self._is_exempt_path(request.path_info):
            current_host = request.get_host().split(":", 1)[0].lower()
            if current_host != canonical_host.lower():
                return HttpResponsePermanentRedirect(
                    f"https://{canonical_host}{request.get_full_path()}"
                )

        return self.get_response(request)

    def _is_exempt_path(self, path):
        exempt_paths = getattr(settings, "CANONICAL_HOST_EXEMPT_PATHS", ())
        return any(path == exempt_path or path.startswith(exempt_path) for exempt_path in exempt_paths)
