from django.http import HttpRequest


def staff_unread(request: HttpRequest) -> dict[str, int]:
    """Unread student messages, for the badge on the staff Inbox link (staff only)."""
    membership = getattr(request, "membership", None)
    if getattr(membership, "role", None) != "PLATFORM_ADMIN":
        return {"staff_unread": 0}
    from .views import unread_messages

    return {"staff_unread": unread_messages().count()}
