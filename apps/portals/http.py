from django.http import HttpResponse

#: The only file types any route serves a stored file as, and the extension each is named
#: with: what a portal accepts and a browser's own viewer draws.
SERVED_TYPES = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
#: The other way round: a stored file's type, from the extension it is named with.
TYPE_BY_EXTENSION = {extension: content_type for content_type, extension in SERVED_TYPES.items()}


def inert_response(body: bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(body, content_type=content_type)
    # Every route that serves a stored file sends all three (spec §6, "Upload safety"): a file
    # is saved, never rendered; its type is never guessed; and if anything renders it
    # anyway, it runs no script and loads nothing.
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    # A student's file is never left in a shared or browser cache.
    response["Cache-Control"] = "no-store"
    return response


#: A browser's own viewer may draw the file and load nothing else; no page may frame it.
_INLINE_CSP = "default-src 'none'; img-src 'self'; object-src 'self'; frame-ancestors 'none'"


def inline_response(body: bytes, content_type: str) -> HttpResponse:
    """A stored file shown in the browser to a counsellor or staff member, never saved by it.
    Not `inert_response`: Chromium will not render a PDF inside a `sandbox`ed document."""
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    response["Content-Security-Policy"] = _INLINE_CSP
    return response
