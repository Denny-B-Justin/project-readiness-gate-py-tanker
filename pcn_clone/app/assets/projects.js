/* Projects pages: the clientside callbacks (`dash_clientside.pcnProjects`),
 * toasts raised from the browser, whole-row navigation in the Projects table
 * and the tag entry's keyboard handling. Every storage call goes through
 * `window.pcnStore` (store.js).
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const store = () => window.pcnStore;
  const noUpdate = () => window.dash_clientside.no_update;
  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const errorText = (error) => (error && error.message ? error.message : undefined);

  // --- Toasts ---------------------------------------------------------------

  // Toast kinds as JSON, identical to TOAST_KINDS in pcn_clone.app.notify.
  const TOAST_KINDS = {"success": {"className": "toast-success", "icon": "circle-check"}, "error": {"className": "toast-error", "icon": "octagon-x"}, "warning": {"className": "toast-warning", "icon": "alert-triangle"}, "info": {"className": "toast-info", "icon": "info"}};

  /** A `sendNotifications` entry shaped exactly as `notify.toast` builds it:
   *  `message` is the headline; a description, when given, becomes the body
   *  under it. */
  function toast(kind, message, description) {
    const style = TOAST_KINDS[kind];
    const entry = {
      action: "show",
      className: style.className,
      icon: {
        type: "Span",
        namespace: "dash_html_components",
        props: {
          className: "icon",
          style: { "--icon-size": "16px" },
          "data-icon": style.icon,
          "aria-hidden": "true",
        },
      },
      message,
    };
    if (description) {
      entry.title = message;
      entry.message = description;
    }
    return entry;
  }

  /** Show a toast in the shell's notification container. */
  function notify(kind, message, description) {
    const setProps = window.dash_clientside && window.dash_clientside.set_props;
    if (typeof setProps === "function") {
      setProps("toasts", { sendNotifications: [toast(kind, message, description)] });
    }
  }

  // --- Callback context and focus -------------------------------------------

  /** The inputs that fired the running callback with a truthy value (real
   *  events, not re-renders), as {id, prop}; a pattern id is parsed into
   *  its dict. */
  function firedInputs() {
    const context = window.dash_clientside.callback_context;
    return ((context && context.triggered) || [])
      .filter((entry) => entry.value)
      .map((entry) => {
        const dot = entry.prop_id.lastIndexOf(".");
        const rawId = entry.prop_id.slice(0, dot);
        let id = rawId;
        try {
          id = JSON.parse(rawId);
        } catch (_error) {
          id = rawId;
        }
        return { id, prop: entry.prop_id.slice(dot + 1) };
      });
  }

  /** The id of the first input that fired the running callback, or null. */
  function triggeredId() {
    const fired = firedInputs();
    return fired.length ? fired[0].id : null;
  }

  /** Focus `elementId` once `ready()` holds, checking once per frame for at
   *  most `maxFrames` frames. */
  function focusWhen(ready, elementId, maxFrames) {
    let frame = 0;
    const tick = () => {
      const element = document.getElementById(elementId);
      if (element && ready()) {
        element.focus();
        if (document.activeElement === element) return;
      }
      frame += 1;
      if (frame < maxFrames) window.requestAnimationFrame(tick);
    };
    window.requestAnimationFrame(tick);
  }

  /** Give `elementId` the focus when its dialog opens. The dialog's focus
   *  trap moves focus to its close button shortly after mounting, so for up
   *  to `maxFrames` frames focus is taken back from the page, the opener or
   *  that close button; once it rests anywhere else in the dialog the user
   *  put it there, and it is left alone. */
  function focusOnOpen(elementId, maxFrames) {
    let frame = 0;
    let held = 0;
    const tick = () => {
      const element = document.getElementById(elementId);
      const dialog = element && element.closest(".mantine-Modal-content");
      const active = document.activeElement;
      if (dialog) {
        if (active === element) {
          held += 1;
          if (held >= 3) return;
        } else if (
          !active ||
          active === document.body ||
          !dialog.contains(active) ||
          active.matches(".mantine-Modal-close")
        ) {
          held = 0;
          element.focus();
        } else {
          return;
        }
      }
      frame += 1;
      if (frame < maxFrames) window.requestAnimationFrame(tick);
    };
    window.requestAnimationFrame(tick);
  }

  /** Remove `new=1` from the address bar, keeping other parameters and the
   *  hash, so a reload does not reopen the create dialog. */
  function dropNewParam() {
    const url = new URL(window.location.href);
    if (url.searchParams.get("new") !== "1") return;
    url.searchParams.delete("new");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  }

  // --- Document listeners ---------------------------------------------------

  // A `tr.row-link[data-href]` inside a `[data-nav]` container opens its href
  // through that container's dcc.Location (named by `data-nav`). The href is
  // a relative query URL; the Location gets it resolved against the current
  // address, since it compares a new href with `window.location.href`. Clicks
  // on the row's own controls (its title link, the delete button) and clicks
  // that end a text selection are left alone; modifier clicks open a new tab.
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    const target = event.target instanceof Element ? event.target : null;
    const row = target && target.closest("tr.row-link[data-href]");
    if (!row || target.closest("a, button, input, label, [role='button']")) return;
    const selection = window.getSelection();
    if (selection && selection.toString()) return;
    const href = row.getAttribute("data-href");
    if (event.metaKey || event.ctrlKey || event.shiftKey) {
      window.open(href, "_blank", "noopener");
      return;
    }
    const nav = row.closest("[data-nav]");
    const setProps = window.dash_clientside && window.dash_clientside.set_props;
    if (nav && typeof setProps === "function") {
      setProps(nav.getAttribute("data-nav"), {
        href: new URL(href, window.location.href).href,
      });
    } else {
      const link = row.querySelector("a[href]");
      if (link) link.click();
    }
  });

  // In a tag entry box, Backspace on an empty input removes the last tag.
  document.addEventListener("keydown", (event) => {
    const input = event.target;
    if (event.key !== "Backspace" || !(input instanceof HTMLInputElement)) return;
    if (!input.matches(".tag-entry input") || input.value) return;
    const box = input.closest(".tag-entry");
    const removers = box ? box.querySelectorAll(".tag-entry-remove") : [];
    if (removers.length) removers[removers.length - 1].click();
  });

  /** Add a typed tag unless it is blank or already present (case-blind). */
  function addTag(tags, raw) {
    const value = String(raw || "").trim().replace(/,$/, "").trim();
    if (!value || tags.some((tag) => tag.toLowerCase() === value.toLowerCase())) return tags;
    return tags.concat([value]);
  }

  /** A project's page as an absolute URL on the current address: the same
   *  path with `?page=project&project_id=<id>` (see pcn_clone.app.routing). */
  function projectHref(project) {
    const url = new URL(window.location.href);
    url.search = new URLSearchParams({ page: "project", project_id: project.id }).toString();
    url.hash = "";
    return url.href;
  }

  let lastClonedNonce = null;
  let leavingAfterCreate = false;

  // --- Clientside callbacks -------------------------------------------------

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.pcnProjects = {
    /** The index for the Projects table (only the fields a row shows), with
     *  the browser's clock and zone so dates render as this browser sees
     *  them. */
    readIndex: function () {
      let timeZone = null;
      try {
        timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || null;
      } catch (_error) {
        timeZone = null;
      }
      const projects = store().listProjects().map((record) => {
        const row = { id: record.id, title: record.title, editedISO: record.editedISO };
        if (record.tags) row.tags = record.tags;
        return row;
      });
      return { projects, now: store().nowISO(), timeZone };
    },

    /** A click on the active column flips its direction; a click on another
     *  column sorts by it ascending. */
    toggleSort: function (_name, _updated, sort) {
      const source = triggeredId();
      if (source === null) return noUpdate();
      const col = source === "projects-sort-name" ? "name" : "updated";
      const current = isPlainObject(sort) ? sort : { col: "updated", dir: "desc" };
      if (current.col === col) return { col, dir: current.dir === "desc" ? "asc" : "desc" };
      return { col, dir: "asc" };
    },

    /** Create button state: disabled until the title has text. */
    createDisabled: function (title) {
      return !(typeof title === "string" && title.trim().length > 0);
    },

    /** Tag entry: Enter, a trailing comma or leaving the box adds the typed
     *  tag; a suggestion click adds that tag; a chip's remove button drops
     *  it. Dash can deliver several of these in one call (leaving the box by
     *  clicking a suggestion), so every input that fired is applied, the
     *  typed tag first. Returns [tags, input value]. */
    editTags: function (value, _submit, _blur, _suggest, _remove, tags) {
      const current = Array.isArray(tags) ? tags : [];
      const typed = typeof value === "string" ? value : "";
      const fired = firedInputs();
      const commit =
        typed.endsWith(",") ||
        fired.some((input) => input.prop === "n_submit" || input.prop === "n_blur");
      let next = commit ? addTag(current, typed) : current;
      for (const input of fired) {
        if (!isPlainObject(input.id)) continue;
        if (input.id.type === "projects-tag-suggest") next = addTag(next, input.id.tag);
        if (input.id.type === "projects-tag-remove") {
          next = next.filter((tag) => tag !== input.id.tag);
        }
      }
      return [next === current ? noUpdate() : next, commit && typed ? "" : noUpdate()];
    },

    /** On open: drop `?new=1` and focus the title. On close: clear whichever
     *  fields hold something, unless the dialog closed because a create is
     *  leaving the page. Returns [title, tags, tag input]. */
    resetCreate: function (opened, title, tags, tagInput) {
      if (opened) {
        leavingAfterCreate = false;
        dropNewParam();
        focusOnOpen("projects-new-title", 45);
        return [noUpdate(), noUpdate(), noUpdate()];
      }
      if (leavingAfterCreate) {
        leavingAfterCreate = false;
        return [noUpdate(), noUpdate(), noUpdate()];
      }
      return [
        title ? "" : noUpdate(),
        Array.isArray(tags) && tags.length ? [] : noUpdate(),
        tagInput ? "" : noUpdate(),
      ];
    },

    /** Open or close a dialog from its trigger buttons: an id ending in
     *  "-cancel" or "-close" closes it, any other trigger opens it. */
    toggleDialog: function () {
      const source = triggeredId();
      if (source === null) return noUpdate();
      const id = typeof source === "string" ? source : JSON.stringify(source);
      return !/-(cancel|close)$/.test(id);
    },

    /** Create the project and open it. Returns [nav href, dialog opened]. */
    createProject: function (clicks, title, tags, meta) {
      const trimmed = typeof title === "string" ? title.trim() : "";
      if (!clicks || !trimmed) return [noUpdate(), noUpdate()];
      try {
        const input = Object.assign({}, meta, {
          title: trimmed,
          tags: Array.isArray(tags) ? tags : [],
        });
        const project = store().createProject(input);
        leavingAfterCreate = true;
        return [projectHref(project), false];
      } catch (error) {
        notify("error", "Couldn’t create the Concept Note", errorText(error));
        return [noUpdate(), noUpdate()];
      }
    },

    /** Clone the default whose values Python delivered (once per payload),
     *  then open it. Returns [nav href, dialog opened]. */
    cloneDefault: function (payload) {
      if (!isPlainObject(payload) || payload.nonce === lastClonedNonce) {
        return [noUpdate(), noUpdate()];
      }
      lastClonedNonce = payload.nonce;
      try {
        if (!payload.ok) {
          throw new Error(payload.errorMessage || "The selected default could not be loaded.");
        }
        const project = store().cloneDefaultProject(payload.meta, payload.values);
        return [projectHref(project), false];
      } catch (error) {
        notify("error", "Couldn’t create a project from this default", errorText(error));
        return [noUpdate(), noUpdate()];
      }
    },

    /** Open the delete confirmation for the clicked row, naming the project
     *  from the index. Returns [target, dialog opened, dialog title]. */
    askDelete: function (_clicks, index) {
      const source = triggeredId();
      const projects = isPlainObject(index) && Array.isArray(index.projects) ? index.projects : [];
      const project = isPlainObject(source) ? projects.find((p) => p.id === source.id) : null;
      if (!project) return [noUpdate(), noUpdate(), noUpdate()];
      return [{ id: project.id, title: project.title }, true, `Delete “${project.title}”?`];
    },

    /** Delete the confirmed project, refresh the list and, once the row and
     *  the dialog are gone, put focus on the New Concept Note button.
     *  Returns [refresh counter, dialog opened]. */
    deleteProject: function (clicks, target, refresh) {
      if (!clicks || !isPlainObject(target)) return [noUpdate(), noUpdate()];
      try {
        store().deleteProject(target.id);
        notify("success", `“${target.title}” deleted`);
        const rowButton = JSON.stringify({ id: target.id, type: "projects-delete" });
        focusWhen(
          () => !document.getElementById(rowButton) && !document.querySelector(".pj-dialog-delete"),
          "projects-new-open",
          240,
        );
      } catch (error) {
        notify("error", `Couldn’t delete “${target.title}”`, errorText(error));
      }
      return [(refresh || 0) + 1, false];
    },
  };
})();
