"""``?page=projects``: the proposer's Concept Notes, most recently edited
first.

The project index lives in the browser (``assets/store.js``). A clientside
callback reads the fields a row shows into the ``projects-index`` memory
store on load and after every mutation (each one bumps ``projects-refresh``);
Python renders the table from that copy. Sorting, tag entry, creating,
cloning and deleting run clientside (``assets/projects.js``); the only other
server call loads the default project's values. ``?page=projects&new=1``
opens the create dialog on load.
"""

from __future__ import annotations

import uuid
from typing import Any

import dash_mantine_components as dmc
from dash import (
    ALL,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    ctx,
    dcc,
    html,
)
from dash.development.base_component import Component
from dash.exceptions import PreventUpdate

from pcn_clone.app.a11y import aria
from pcn_clone.app.icons import icon
from pcn_clone.app.projects_data import (
    default_project_meta,
    default_project_values,
    format_date,
    parse_iso,
    relative_days,
    resolve_timezone,
    template_badge,
    template_meta,
)
from pcn_clone.app.routing import page_url
from pcn_clone.content import load_default_project, load_template

LEDE = "Every Concept Note you’ve started, most recently edited first."  # noqa: RUF001

SUGGESTED_TAGS = [
    "Water & Sanitation",
    "Health",
    "Transport",
    "Energy",
    "Education",
    "Climate Adaptation",
    "Urban",
    "Rural",
]

DEFAULT_SORT = {"col": "updated", "dir": "desc"}
"""The table's initial order: Updated, newest first."""

DEFAULTS_LIST_CLASS = "pj-defaults-list"

CLOSE_BUTTON = {"aria-label": "Close"}
"""Props for a dialog's close button."""


# --- Layout pieces -----------------------------------------------------------


def new_button(button_id: str) -> html.Button:
    """A compact "New Concept Note" button that opens the create dialog."""
    return html.Button(
        [icon("plus", 14, weight="bold"), "New Concept Note"],
        id=button_id,
        type="button",
        className="btn btn-primary btn-sm pj-new-btn",
    )


def toolbar() -> html.Div:
    """The count label and the Defaults / New Concept Note actions."""
    return html.Div(
        className="pj-toolbar",
        children=[
            html.Div(
                className="section-label pj-count",
                children=[
                    html.Span("Your Concept Notes"),
                    html.Span("0", id="projects-count", className="count-badge"),
                ],
            ),
            html.Div(
                className="pj-actions",
                children=[
                    html.Button(
                        [icon("layers", 14), "Defaults"],
                        id="projects-defaults-open",
                        type="button",
                        className="btn btn-secondary btn-sm",
                    ),
                    new_button("projects-new-open"),
                ],
            ),
        ],
    )


def sort_header(label: str, col: str, extra_class: str = "") -> html.Th:
    """A sortable column header: a button that sorts by the column, with
    ``aria-sort`` on the header cell and an arrow showing the direction."""
    return html.Th(
        id=f"projects-sort-{col}-th",
        scope="col",
        className=f"sortable {extra_class}".rstrip(),
        **aria(sort="none"),
        children=html.Button(
            [
                label,
                html.Span(
                    "↕",
                    id=f"projects-sort-{col}-arrow",
                    className="sort-arrow",
                    **aria(hidden="true"),
                ),
            ],
            id=f"projects-sort-{col}",
            n_clicks=0,
            type="button",
            className="sort-btn",
        ),
    )


def table() -> html.Div:
    """The Concept Note table; rows are rendered from the index."""
    table_attributes: dict[str, Any] = {"data-nav": "projects-nav"}
    return html.Div(
        id="projects-table-wrap",
        className="table-card",
        hidden=True,
        children=html.Table(
            className="data-table",
            **table_attributes,
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("No", scope="col", className="col-no"),
                            sort_header("Concept Note", "name"),
                            sort_header("Updated", "updated", "pj-col-updated"),
                            html.Th("Action", scope="col", className="col-action"),
                        ]
                    )
                ),
                html.Tbody(id="projects-rows"),
            ],
        ),
    )


def empty_state() -> html.Div:
    """The first-run panel shown when the browser holds no projects."""
    return html.Div(
        id="projects-empty",
        className="empty-state",
        hidden=True,
        children=[
            html.Span(icon("layers", 26), className="empty-state-icon"),
            html.P("No Concept Notes yet", className="empty-state-title"),
            html.P(
                "Start a new Concept Note to draft a proposal and get structured "
                "feedback before it goes for review.",
                className="empty-state-text",
            ),
            html.Div(new_button("projects-empty-new"), className="empty-state-actions"),
        ],
    )


def dialog_lede(lede: str, lede_id: str) -> html.P:
    """A dialog's one-line description, the first thing in its body."""
    return html.P(lede, id=lede_id, className="pj-dialog-lede")


def dialog_foot(*buttons: html.Button) -> html.Div:
    """The right-aligned action row on a faint surface."""
    return html.Div(className="pj-dialog-foot", children=list(buttons))


def tag_entry() -> list[Component]:
    """The tag box (chips plus a free-text input) and its suggestion row."""
    return [
        html.Div(
            className="tag-entry",
            children=[
                html.Div(id="projects-new-tag-chips", className="tag-entry-chips"),
                dcc.Input(
                    id="projects-new-tag-input",
                    type="text",
                    value="",
                    placeholder="Type a tag and press Enter…",
                    autoComplete="off",
                    className="tag-entry-input",
                ),
            ],
        ),
        html.Div(
            id="projects-new-suggestions",
            className="tag-entry-suggestions",
            children=[
                html.Span("Suggested", className="tag-entry-suggest-label"),
                *[
                    html.Button(
                        [icon("plus", 11, weight="bold"), tag],
                        id={"type": "projects-tag-suggest", "tag": tag},
                        type="button",
                        className="tag-entry-suggest",
                    )
                    for tag in SUGGESTED_TAGS
                ],
            ],
        ),
    ]


def create_dialog(opened: bool) -> dmc.Modal:
    """The "New Concept Note" dialog: a title, the template, and tags."""
    template = load_template()
    return dmc.Modal(
        id="projects-new-modal",
        opened=opened,
        size=560,
        radius=18,
        title="New Concept Note",
        closeButtonProps=CLOSE_BUTTON,
        classNames={
            "content": "pj-dialog pj-dialog-new",
            "header": "pj-dialog-header",
            "title": "pj-dialog-title",
            "body": "pj-dialog-body",
        },
        children=[
            dialog_lede(
                "Name it and choose a template to start from.", "projects-new-lede"
            ),
            html.Div(
                className="pj-dialog-section",
                children=[
                    html.Label(
                        "Concept Note title",
                        htmlFor="projects-new-title",
                        className="pj-field-label",
                    ),
                    dcc.Input(
                        id="projects-new-title",
                        type="text",
                        value="",
                        placeholder="e.g. Rural Health Clinic Expansion",
                        autoComplete="off",
                    ),
                    html.Div("Template", className="pj-field-label pj-field-gap"),
                    html.Div(
                        className="pj-template-panel",
                        children=[
                            html.Div(template.label, className="pj-template-name"),
                            html.P(
                                template.description or "",
                                className="pj-template-desc",
                            ),
                        ],
                    ),
                    html.Label(
                        "Tags",
                        htmlFor="projects-new-tag-input",
                        className="pj-field-label pj-field-gap",
                    ),
                    html.P(
                        "Tag this note so it’s easy to find and group later.",  # noqa: RUF001
                        className="pj-field-hint",
                    ),
                    *tag_entry(),
                ],
            ),
            dialog_foot(
                html.Button(
                    "Cancel",
                    id="projects-new-cancel",
                    type="button",
                    className="btn btn-secondary btn-md",
                ),
                html.Button(
                    [icon("plus", 15), "Create Concept Note"],
                    id="projects-new-create",
                    type="button",
                    disabled=True,
                    className="btn btn-primary btn-md",
                ),
            ),
        ],
    )


def default_card() -> html.Button:
    """The card for the default project; clicking it clones the default."""
    project = load_default_project()
    return html.Button(
        id={"type": "projects-default-card", "id": project.id},
        type="button",
        className="pj-default-card",
        children=[
            html.Span(icon("doc-check", 17), className="pj-default-icon"),
            html.Span(
                className="pj-default-text",
                children=[
                    html.Span(
                        className="pj-default-headline",
                        children=[
                            html.Span(project.title, className="pj-default-title"),
                            html.Span(
                                template_badge(),
                                className="pill pill-tint pj-default-badge",
                            ),
                        ],
                    ),
                    html.Span(project.description, className="pj-default-blurb"),
                ],
            ),
            html.Span(
                className="pj-default-end",
                children=[
                    icon("chevron-right", 15),
                    html.Span(className="spinner pj-default-spinner"),
                ],
            ),
        ],
    )


def defaults_dialog() -> dmc.Modal:
    """The "Browse defaults" dialog listing the institution's examples."""
    return dmc.Modal(
        id="projects-defaults-modal",
        opened=False,
        size=560,
        radius=18,
        title="Browse defaults",
        closeButtonProps=CLOSE_BUTTON,
        classNames={
            "content": "pj-dialog pj-dialog-defaults",
            "header": "pj-dialog-header",
            "title": "pj-dialog-title",
            "body": "pj-dialog-body",
        },
        children=[
            dialog_lede(
                "Start from a pre-filled example instead of a blank Concept Note.",
                "projects-defaults-lede",
            ),
            html.Fieldset(
                default_card(),
                id="projects-defaults-list",
                className=DEFAULTS_LIST_CLASS,
                disabled=False,
                **aria(busy="false", label="Defaults"),
            ),
            dialog_foot(
                html.Button(
                    "Cancel",
                    id="projects-defaults-cancel",
                    type="button",
                    className="btn btn-secondary btn-md",
                ),
            ),
        ],
    )


def delete_dialog() -> dmc.Modal:
    """The delete confirmation. Overlay clicks do not dismiss it; Cancel,
    Delete and Escape do."""
    return dmc.Modal(
        id="projects-delete-modal",
        opened=False,
        size=420,
        withCloseButton=False,
        closeOnClickOutside=False,
        title="Delete this Concept Note?",
        classNames={
            "content": "pj-dialog pj-dialog-delete",
            "header": "pj-dialog-header pj-alert-header",
            "title": "pj-alert-title",
            "body": "pj-dialog-body",
        },
        children=[
            html.P(
                "This permanently removes the Concept Note and its draft. "
                "This can’t be undone.",  # noqa: RUF001
                className="pj-alert-text",
            ),
            dialog_foot(
                html.Button(
                    "Cancel",
                    id="projects-delete-cancel",
                    type="button",
                    className="btn btn-secondary btn-md",
                ),
                html.Button(
                    "Delete",
                    id="projects-delete-confirm",
                    type="button",
                    className="btn btn-destructive btn-md",
                ),
            ),
        ],
    )


def layout(new: str | None = None) -> Component:
    """The Projects page. ``new=1`` opens the create dialog on load."""
    return html.Div(
        className="page",
        children=[
            dcc.Location(id="projects-nav", refresh="callback-nav"),
            dcc.Store(id="projects-index", storage_type="memory"),
            dcc.Store(id="projects-refresh", storage_type="memory", data=0),
            dcc.Store(
                id="projects-template-meta",
                storage_type="memory",
                data=dict(template_meta()),
            ),
            dcc.Store(id="projects-sort", storage_type="memory", data=DEFAULT_SORT),
            dcc.Store(id="projects-new-tags", storage_type="memory", data=[]),
            dcc.Store(id="projects-delete-target", storage_type="memory"),
            dcc.Store(id="projects-default-payload", storage_type="memory"),
            html.Div(
                className="page-head",
                children=[
                    html.H1("Projects", className="page-title"),
                    html.P(LEDE, className="page-lede"),
                ],
            ),
            toolbar(),
            table(),
            empty_state(),
            create_dialog(opened=new == "1"),
            defaults_dialog(),
            delete_dialog(),
        ],
    )


# --- Rendering ---------------------------------------------------------------


def project_row(project: dict[str, Any], number: int, index: dict[str, Any]) -> html.Tr:
    """One table row. The whole row opens the project; the trash button
    asks to delete it."""
    project_id = str(project["id"])
    title = str(project["title"])
    href = page_url("project", project_id=project_id)
    zone = resolve_timezone(index.get("timeZone"))
    edited = project.get("editedISO")
    row_attributes: dict[str, Any] = {"data-href": href}
    return html.Tr(
        className="row-link",
        **row_attributes,
        children=[
            html.Td(str(number), className="col-no"),
            html.Td(
                html.Div(
                    className="pj-name",
                    children=[
                        dcc.Link(title, href=href, className="cell-title"),
                        *[
                            html.Span(tag, className="pill pill-tint pill-sm pj-tag")
                            for tag in project.get("tags") or []
                        ],
                    ],
                )
            ),
            html.Td(
                [
                    html.Span(format_date(edited, zone), className="cell-strong"),
                    html.Span(
                        relative_days(edited, parse_iso(index.get("now"))),
                        className="cell-sub",
                    ),
                ]
            ),
            html.Td(
                html.Button(
                    icon("trash"),
                    id={"type": "projects-delete", "id": project_id},
                    type="button",
                    className="icon-btn icon-btn-ghost",
                    **aria(label=f"Delete {title}"),
                ),
                className="col-action",
            ),
        ],
    )


def sorted_projects(
    projects: list[dict[str, Any]], sort: dict[str, str]
) -> list[dict[str, Any]]:
    """The projects in table order: by lower-cased title or by ``editedISO``,
    ascending or descending, ties keeping their stored order."""
    col = sort.get("col", "updated")

    def key(project: dict[str, Any]) -> str:
        if col == "name":
            return str(project.get("title", "")).lower()
        return str(project.get("editedISO", ""))

    return sorted(projects, key=key, reverse=sort.get("dir") == "desc")


def header_state(
    sort: dict[str, str], col: str, extra_class: str = ""
) -> tuple[str, str, str]:
    """A sortable header's class, ``aria-sort`` value and arrow for the
    current sort."""
    base = f"sortable {extra_class}".rstrip()
    if sort.get("col") != col:
        return base, "none", "↕"
    if sort.get("dir") == "asc":
        return f"{base} active", "ascending", "↑"
    return f"{base} active", "descending", "↓"


@callback(
    Output("projects-rows", "children"),
    Output("projects-count", "children"),
    Output("projects-table-wrap", "hidden"),
    Output("projects-empty", "hidden"),
    Output("projects-sort-name-th", "className"),
    Output("projects-sort-name-th", "aria-sort"),
    Output("projects-sort-name-arrow", "children"),
    Output("projects-sort-updated-th", "className"),
    Output("projects-sort-updated-th", "aria-sort"),
    Output("projects-sort-updated-arrow", "children"),
    Input("projects-index", "data"),
    Input("projects-sort", "data"),
)
def render_table(
    index: dict[str, Any] | None, sort: dict[str, str] | None
) -> tuple[Any, ...]:
    """The rows, count and visibility for the current index and sort. Until
    the index has been read, neither the table nor the empty state shows."""
    sort = sort or DEFAULT_SORT
    headers = (
        *header_state(sort, "name"),
        *header_state(sort, "updated", "pj-col-updated"),
    )
    if not index:
        return ([], "0", True, True, *headers)
    projects = sorted_projects(list(index.get("projects") or []), sort)
    rows = [project_row(p, n, index) for n, p in enumerate(projects, start=1)]
    return (rows, str(len(rows)), not rows, bool(rows), *headers)


clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="toggleSort"),
    Output("projects-sort", "data"),
    Input("projects-sort-name", "n_clicks"),
    Input("projects-sort-updated", "n_clicks"),
    State("projects-sort", "data"),
    prevent_initial_call=True,
)


# --- Tag entry ---------------------------------------------------------------


@callback(
    Output("projects-new-tag-chips", "children"),
    Output({"type": "projects-tag-suggest", "tag": ALL}, "hidden"),
    Output("projects-new-suggestions", "hidden"),
    Output("projects-new-tag-input", "placeholder"),
    Input("projects-new-tags", "data"),
    prevent_initial_call=True,
)
def render_tags(tags: list[str] | None) -> tuple[Any, ...]:
    """The tag chips, with used suggestions hidden. The layout already shows
    the empty state, so this runs only when the tags change."""
    chosen = list(tags or [])
    chips = [
        html.Span(
            className="tag-entry-chip",
            children=[
                tag,
                html.Button(
                    icon("close", 11, weight="bold"),
                    id={"type": "projects-tag-remove", "tag": tag},
                    type="button",
                    className="tag-entry-remove",
                    **aria(label=f"Remove {tag}"),
                ),
            ],
        )
        for tag in chosen
    ]
    suggestions = [output["id"]["tag"] for output in ctx.outputs_list[1]]
    hidden = [tag in chosen for tag in suggestions]
    placeholder = "Add another…" if chosen else "Type a tag and press Enter…"
    return chips, hidden, all(hidden), placeholder


clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="editTags"),
    Output("projects-new-tags", "data"),
    Output("projects-new-tag-input", "value"),
    Input("projects-new-tag-input", "value"),
    Input("projects-new-tag-input", "n_submit"),
    Input("projects-new-tag-input", "n_blur"),
    Input({"type": "projects-tag-suggest", "tag": ALL}, "n_clicks"),
    Input({"type": "projects-tag-remove", "tag": ALL}, "n_clicks"),
    State("projects-new-tags", "data"),
    prevent_initial_call=True,
)


# --- Store reads and dialogs -------------------------------------------------

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="readIndex"),
    Output("projects-index", "data"),
    Input("projects-refresh", "data"),
)

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="toggleDialog"),
    Output("projects-new-modal", "opened"),
    Input("projects-new-open", "n_clicks"),
    Input("projects-empty-new", "n_clicks"),
    Input("projects-new-cancel", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="toggleDialog"),
    Output("projects-defaults-modal", "opened"),
    Input("projects-defaults-open", "n_clicks"),
    Input("projects-defaults-cancel", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="toggleDialog"),
    Output("projects-delete-modal", "opened", allow_duplicate=True),
    Input("projects-delete-cancel", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="resetCreate"),
    Output("projects-new-title", "value"),
    Output("projects-new-tags", "data", allow_duplicate=True),
    Output("projects-new-tag-input", "value", allow_duplicate=True),
    Input("projects-new-modal", "opened"),
    State("projects-new-title", "value"),
    State("projects-new-tags", "data"),
    State("projects-new-tag-input", "value"),
    prevent_initial_call="initial_duplicate",
)

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="createDisabled"),
    Output("projects-new-create", "disabled"),
    Input("projects-new-title", "value"),
)

clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="createProject"),
    Output("projects-nav", "href"),
    Output("projects-new-modal", "opened", allow_duplicate=True),
    Input("projects-new-create", "n_clicks"),
    State("projects-new-title", "value"),
    State("projects-new-tags", "data"),
    State("projects-template-meta", "data"),
    prevent_initial_call=True,
)


# --- Defaults ----------------------------------------------------------------


@callback(
    Output("projects-default-payload", "data"),
    Input({"type": "projects-default-card", "id": ALL}, "n_clicks"),
    prevent_initial_call=True,
    running=[
        (Output("projects-defaults-list", "disabled"), True, False),
        (
            Output("projects-defaults-list", "className"),
            f"{DEFAULTS_LIST_CLASS} is-busy",
            DEFAULTS_LIST_CLASS,
        ),
        (Output("projects-defaults-list", "aria-busy"), "true", "false"),
        (Output("projects-defaults-cancel", "disabled"), True, False),
        (Output("projects-defaults-modal", "closeOnEscape"), False, True),
        (Output("projects-defaults-modal", "closeOnClickOutside"), False, True),
        (
            Output("projects-defaults-modal", "closeButtonProps"),
            {**CLOSE_BUTTON, "disabled": True},
            CLOSE_BUTTON,
        ),
    ],
)
async def load_default(clicks: list[int | None]) -> dict[str, Any]:
    """The selected default's record metadata and draft values, for the
    browser to clone. An unknown id yields ``ok: False`` with a message.
    While it runs the dialog is locked: the cards and Cancel are disabled and
    neither Escape, the overlay nor the close button dismisses it."""
    selected = ctx.triggered_id
    if not isinstance(selected, dict) or not any(clicks):
        raise PreventUpdate
    nonce = uuid.uuid4().hex
    if selected.get("id") != load_default_project().id:
        return {
            "ok": False,
            "errorMessage": "The selected default could not be loaded.",
            "nonce": nonce,
        }
    return {
        "ok": True,
        "defaultId": selected["id"],
        "meta": default_project_meta(),
        "values": default_project_values(),
        "nonce": nonce,
    }


clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="cloneDefault"),
    Output("projects-nav", "href", allow_duplicate=True),
    Output("projects-defaults-modal", "opened", allow_duplicate=True),
    Input("projects-default-payload", "data"),
    prevent_initial_call=True,
)


# --- Delete ------------------------------------------------------------------


clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="askDelete"),
    Output("projects-delete-target", "data"),
    Output("projects-delete-modal", "opened"),
    Output("projects-delete-modal", "title"),
    Input({"type": "projects-delete", "id": ALL}, "n_clicks"),
    State("projects-index", "data"),
    prevent_initial_call=True,
)


clientside_callback(
    ClientsideFunction(namespace="pcnProjects", function_name="deleteProject"),
    Output("projects-refresh", "data"),
    Output("projects-delete-modal", "opened", allow_duplicate=True),
    Input("projects-delete-confirm", "n_clicks"),
    State("projects-delete-target", "data"),
    State("projects-refresh", "data"),
    prevent_initial_call=True,
)
