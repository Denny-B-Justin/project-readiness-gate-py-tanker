"""Toast notifications, shown top-centre by the shell's notification container.

Send one from a Python callback, for example
``set_props(TOASTS_ID, {"sendNotifications": [toast("success", "Draft saved")]})``
or by returning ``[toast(...)]`` to ``Output(TOASTS_ID, "sendNotifications")``.

``TOAST_KINDS`` is the one definition of how each kind looks: the class that
tints the card (``assets/brand.css``) and the icon beside the message. The
browser-side toast helper in ``assets/store.js`` declares the same table, and
a test keeps the two identical.
"""

from __future__ import annotations

from typing import Any, Final, Literal, TypedDict

from pcn_clone.app.icons import IconName, icon

TOASTS_ID: Final = "toasts"
"""Id of the ``dmc.NotificationContainer`` in the shell layout."""

ToastKind = Literal["success", "error", "warning", "info"]


class ToastStyle(TypedDict):
    """How one kind of toast is drawn."""

    className: str
    icon: IconName


TOAST_KINDS: Final[dict[ToastKind, ToastStyle]] = {
    "success": {"className": "toast-success", "icon": "circle-check"},
    "error": {"className": "toast-error", "icon": "octagon-x"},
    "warning": {"className": "toast-warning", "icon": "alert-triangle"},
    "info": {"className": "toast-info", "icon": "info"},
}


def toast(
    kind: ToastKind, message: str, description: str | None = None
) -> dict[str, Any]:
    """Return a ``sendNotifications`` entry for a ``kind`` toast.

    ``message`` is the headline; ``description``, when given, is a quieter
    second line under it. Toasts close themselves after four seconds.
    """
    style = TOAST_KINDS[kind]
    entry: dict[str, Any] = {
        "action": "show",
        "className": style["className"],
        "icon": icon(style["icon"]),
        "message": message,
    }
    if description is not None:
        entry["title"] = message
        entry["message"] = description
    return entry
