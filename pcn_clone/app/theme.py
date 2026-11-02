"""The Mantine theme: brand palette, type, radii, shadows and overlay defaults.

Mantine components (modals, menus, popovers, toasts, form inputs) read this
theme; plain ``html`` elements are styled by ``assets/brand.css``. The two
agree on every value: the ``brand`` scale runs from blue-tint through the
brand blues, with blue-600 as the primary shade and blue-700 as its hover.
"""

from __future__ import annotations

from typing import Any, Final

SCRIM_COLOR: Final = "#16223a"
"""Ink-navy base of the modal scrim, laid at 34% opacity."""

BRAND_THEME: Final[dict[str, Any]] = {
    "primaryColor": "brand",
    "primaryShade": 7,
    "colors": {
        "brand": [
            "#eef0f8",  # blue-tint
            "#dfe3f3",  # blue-tint-2
            "#ccd2ea",  # blue-border
            "#aab3d9",
            "#8793c6",
            "#6673b5",
            "#4a56a4",  # blue-500
            "#374291",  # blue-600, the primary shade
            "#2c3576",  # blue-700, the hover shade
            "#232a5e",
        ],
    },
    "black": "#14223b",
    "white": "#ffffff",
    "fontFamily": "Inter, Roboto, Arial, system-ui, sans-serif",
    "fontFamilyMonospace": (
        "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
    ),
    "headings": {
        "fontFamily": "'Fira Sans', 'Trebuchet MS', system-ui, sans-serif",
        "fontWeight": "700",
    },
    "defaultRadius": "md",
    "radius": {"sm": "8px", "md": "10px", "lg": "14px", "xl": "16px"},
    "shadows": {
        "sm": "0 1px 2px rgba(22, 34, 58, 0.05), 0 1px 1px rgba(22, 34, 58, 0.04)",
        "md": (
            "0 8px 24px -8px rgba(22, 34, 58, 0.16),"
            " 0 2px 8px -2px rgba(22, 34, 58, 0.08)"
        ),
        "lg": (
            "0 24px 60px -16px rgba(22, 34, 58, 0.3),"
            " 0 8px 24px -8px rgba(22, 34, 58, 0.14)"
        ),
    },
    "cursorType": "pointer",
    "components": {
        "Modal": {
            "defaultProps": {
                "centered": True,
                "size": 452,
                "radius": "xl",
                "shadow": "lg",
                "overlayProps": {
                    "color": SCRIM_COLOR,
                    "backgroundOpacity": 0.34,
                    "blur": 1.5,
                },
                "transitionProps": {"transition": "pop", "duration": 150},
                "closeButtonProps": {"aria-label": "Close"},
            },
        },
        "Menu": {
            "defaultProps": {
                "position": "bottom-start",
                "offset": 4,
                "width": "target",
                "radius": "lg",
                "shadow": "md",
            },
        },
        "Popover": {
            "defaultProps": {"offset": 8, "width": 288, "radius": "lg", "shadow": "md"},
        },
        "Notification": {
            "defaultProps": {"radius": "lg", "withCloseButton": False},
        },
    },
}
"""Theme for ``dmc.MantineProvider``; pair it with ``forceColorScheme="light"``."""
