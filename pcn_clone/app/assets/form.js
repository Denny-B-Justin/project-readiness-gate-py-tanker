/* pcnForm: the proposer workspace in the browser (see pcn_clone/app/form).
 *
 * The browser owns a project's answers. On mount the saved draft
 * (pcnStore.loadDraft) is laid over every field's blank default and returned
 * into the `form-values` store; once the workspace is in the page its native
 * controls are created (input slots), list and worksheet rows drawn, and the
 * values written into the controls. Only then is the workspace hydrated:
 * before that nothing is saved. Every edit updates the values, mirrors them
 * into `form-values`, refreshes the live figures, and autosaves 500 ms after
 * the last edit; a pending save is written at once when the page is hidden
 * or left, or the app navigates elsewhere. Only answers are saved;
 * evaluation feedback lives in memory.
 *
 * Everything shared with the server comes from the `pf-config` store: the
 * component ids, the text both sides show, the verdict labels and pills, and
 * per field its kind, default, where its readiness is decided and the facts
 * its live figures need.
 *
 * Readiness: a text, textarea or group field is ready when its answer is
 * complete, decided here as the proposer types. For the other kinds the
 * server decides: an edit marks the field's readiness as owed, and 400 ms
 * after the last edit every owed answer is sent in one request; until the
 * answer for the latest edit arrives, Evaluate stays disabled and a click on
 * it is ignored.
 *
 * Evaluation: a click on an enabled Evaluate button writes the answer (and a
 * worksheet's context) to the field's request store, which starts the server
 * callback, and keeps the answer's signature. The response carries the
 * request's `n`; one for an earlier request is ignored. The verdict is stale
 * once the field's current signature differs from the kept one (a late
 * result is kept and shown stale). An answer the server finds not ready is
 * refused unsent, and the field keeps its earlier feedback.
 *
 * Chrome: the scroll-spy picks the section under the sticky chrome for the
 * jump menu, `--scroll-progress` drives the bar's progress fill, and the
 * back-to-top button appears past one viewport. A jump moves the focus to the
 * section's heading once the menu has closed.
 *
 * Dash renders the structure and owns its components' props: this script
 * changes them only through `dash_clientside.set_props`. It writes to the
 * DOM directly only for what Dash does not track: the native controls'
 * values and disabled states, the rows and inputs it creates, the text of
 * computed cells, its `data-pf-*` state attributes, and the description
 * Mantine gives each dialog (removed, so a dialog is not described by its
 * whole body). Dash never re-renders an ancestor of a control; should a slot
 * lose its input anyway, the input is created again with its value.
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const AUTOSAVE_DELAY_MS = 500;
  const READINESS_DELAY_MS = 400;
  /** How long a finished request may take to deliver its response before
   *  the field is marked failed (the request itself failed). */
  const RESPONSE_GRACE_MS = 1500;
  const MOUNT_POLL_MS = 20;
  const MOUNT_TIMEOUT_MS = 15000;
  /** How long a jump waits for the menu to hand the focus back to its
   *  trigger before moving it to the section's heading anyway. */
  const MENU_FOCUS_WAIT_MS = 400;
  const SAVE_FAILED = "Your draft couldn’t be saved — check your browser’s storage settings.";
  const REEVALUATE_LABEL = "Re-evaluate";
  const EVALUATING_LABEL = "Evaluating…";
  const NOTES_TITLE = "Review notes (AI)";
  /** Month inputs where the browser has no month picker take typed YYYY-MM. */
  const MONTH_PLACEHOLDER = "YYYY-MM";
  const MONTH_PATTERN = "\\d{4}-(0[1-9]|1[0-2])";
  const TALLY_TONE = { pass: "pass", notClear: "nc", fail: "fail" };

  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const clone = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
  const isNonBlank = (value) => typeof value === "string" && value.trim() !== "";
  const numbers = () => window.pcnNumbers;
  const store = () => window.pcnStore;
  const dash = () => window.dash_clientside;
  const prefersReducedMotion = () =>
    !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  /** The mounted workspace, or null. */
  let form = null;

  const ids = () => form.config.ids;
  const messages = () => form.config.messages;

  /** `template` with each `{name}` replaced by `values[name]`. */
  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, (match, name) => (hasOwn(values, name) ? String(values[name]) : match));
  }

  // --- Dash components ------------------------------------------------------

  /** An html component as Dash's layout JSON. */
  function node(type, props, children) {
    const allProps = Object.assign({}, props);
    if (children !== undefined) allProps.children = children;
    return { type, namespace: "dash_html_components", props: allProps };
  }

  /** A brand icon (icons.icon in Python). */
  function iconNode(name, size, bold) {
    const props = {
      className: "icon",
      style: { "--icon-size": `${size}px` },
      "data-icon": name,
      "aria-hidden": "true",
    };
    if (bold) props["data-weight"] = "bold";
    return node("Span", props);
  }

  function spinnerNode(size) {
    return node("Span", {
      className: "spinner",
      style: { "--spinner-size": `${size}px` },
      "aria-hidden": "true",
    });
  }

  /** A verdict pill (verdicts.verdict_pill in Python). */
  function verdictNode(verdict, small) {
    const style = form.config.verdicts[verdict] || { label: String(verdict), pill: "pill-muted" };
    return node("Span", { className: `pill ${style.pill}${small ? " pill-sm" : ""} pf-verdict` }, [
      node("Span", { className: "pill-dot", "aria-hidden": "true" }),
      style.label,
    ]);
  }

  function setProps(id, props) {
    const api = dash();
    if (api && typeof api.set_props === "function") api.set_props(id, props);
  }

  /** set_props, skipped when `props` equal what was last sent under `key`. */
  function setPropsOnce(key, id, props) {
    const serial = JSON.stringify(props);
    if (form.sent[key] === serial) return;
    form.sent[key] = serial;
    setProps(id, props);
  }

  const fieldKey = (type, fieldId) => ({ type, field: fieldId });

  /** The inputs that fired the running clientside callback: [{id, prop, value}]. */
  function triggered() {
    const context = dash().callback_context;
    return ((context && context.triggered) || []).map((entry) => {
      const dot = entry.prop_id.lastIndexOf(".");
      let id = entry.prop_id.slice(0, dot);
      try {
        id = JSON.parse(id);
      } catch (_error) {
        // A plain string id.
      }
      return { id, prop: entry.prop_id.slice(dot + 1), value: entry.value };
    });
  }

  // --- Values ---------------------------------------------------------------

  /** Keep string cells; numbers and booleans become their text, the rest
   *  is dropped (the coercion pcn_clone.core applies to untrusted cells). */
  function stringRecord(value) {
    const out = {};
    if (!isPlainObject(value)) return out;
    for (const [key, cell] of Object.entries(value)) {
      if (typeof cell === "string") out[key] = cell;
      else if (typeof cell === "number" && Number.isFinite(cell)) out[key] = String(cell);
      else if (typeof cell === "boolean") out[key] = String(cell);
    }
    return out;
  }

  function nestedRecord(value) {
    const out = {};
    if (!isPlainObject(value)) return out;
    for (const [key, record] of Object.entries(value)) {
      if (isPlainObject(record)) out[key] = stringRecord(record);
    }
    return out;
  }

  /** A list item with a durable `_rowId` (one is minted if missing). */
  function withRowId(item) {
    const record = stringRecord(item);
    if (record._rowId) return record;
    const rest = Object.assign({}, record);
    delete rest._rowId;
    return Object.assign({ _rowId: store().newId() }, rest);
  }

  /** A restored answer in its field's stored shape; anything unusable
   *  falls back to the blank default. */
  function normalize(field, value) {
    switch (field.kind) {
      case "group":
        return Object.assign(clone(field.default), stringRecord(value));
      case "list":
        return Array.isArray(value) ? value.filter(isPlainObject).map(withRowId) : [];
      case "worksheet":
        if (!isPlainObject(value)) return clone(field.default);
        return {
          componentCosts: nestedRecord(value.componentCosts),
          narratives: stringRecord(value.narratives),
        };
      case "scenario_comparison": {
        if (!isPlainObject(value)) return clone(field.default);
        const out = {};
        if (hasOwn(value, "applicability")) out.applicability = stringRecord(value.applicability);
        out.rows = nestedRecord(value.rows);
        out.narratives = stringRecord(value.narratives);
        return out;
      }
      case "static_table":
        return isPlainObject(value) ? { rows: nestedRecord(value.rows) } : clone(field.default);
      default:
        return typeof value === "string" ? value : clone(field.default);
    }
  }

  function blankItem(field) {
    const item = { _rowId: store().newId() };
    for (const control of field.controls) item[control.id] = "";
    return item;
  }

  /** The value at `path` in a field's answer; a list path is [rowId, control]. */
  function readPath(fieldId, path) {
    const field = form.config.fields[fieldId];
    let current = form.values[fieldId];
    if (field.kind === "list") {
      const item = (current || []).find((entry) => entry._rowId === path[0]);
      return item ? item[path[1]] : undefined;
    }
    for (const key of path) {
      if (!isPlainObject(current)) return undefined;
      current = current[key];
    }
    return current;
  }

  function writePath(fieldId, path, value) {
    const field = form.config.fields[fieldId];
    if (path.length === 0) {
      form.values[fieldId] = value;
      return;
    }
    if (field.kind === "list") {
      const item = form.values[fieldId].find((entry) => entry._rowId === path[0]);
      if (item) item[path[1]] = value;
      return;
    }
    if (!isPlainObject(form.values[fieldId])) form.values[fieldId] = clone(field.default);
    let current = form.values[fieldId];
    for (const key of path.slice(0, -1)) {
      if (!isPlainObject(current[key])) current[key] = {};
      current = current[key];
    }
    current[path[path.length - 1]] = value;
  }

  // --- Signatures -----------------------------------------------------------

  /** A worksheet's context: its row-source list answer. Null otherwise. */
  function contextFor(fieldId) {
    const field = form.config.fields[fieldId];
    if (field.kind !== "worksheet") return null;
    const source = field.rowSource;
    return [{ sectionId: source.sectionId, fieldId: source.fieldId, answer: form.values[source.fieldId] }];
  }

  /** The fingerprint a verdict is graded against (the rule
   *  pcn_clone/app/form/signature.py states in Python). */
  function signatureOf(field, answer, context) {
    if (field.kind === "worksheet") return JSON.stringify({ answer, context });
    if (field.kind === "list" || field.kind === "scenario_comparison" || field.kind === "static_table") {
      return JSON.stringify(answer === undefined ? null : answer);
    }
    if (typeof answer === "string") return answer;
    if (field.kind === "group" && isPlainObject(answer)) {
      return field.controls.map((control) => `${control.label}: ${answer[control.id] ?? ""}`).join("\n");
    }
    return "";
  }

  function signature(fieldId) {
    return signatureOf(form.config.fields[fieldId], form.values[fieldId], contextFor(fieldId));
  }

  // --- Controls -------------------------------------------------------------

  function pathOf(element) {
    try {
      const path = JSON.parse(element.getAttribute("data-pf-path"));
      return Array.isArray(path) ? path : null;
    } catch (_error) {
      return null;
    }
  }

  /** Create the native input a slot declares. A month input the browser
   *  cannot show as a month picker asks for typed YYYY-MM instead. */
  function createInput(slot) {
    let attributes;
    try {
      attributes = JSON.parse(slot.getAttribute("data-pf-input"));
    } catch (_error) {
      return null;
    }
    const input = document.createElement("input");
    for (const [name, value] of Object.entries(attributes)) {
      if (name === "class") input.className = value;
      else input.setAttribute(name, value);
    }
    if (attributes.type === "month" && input.type !== "month") {
      input.setAttribute("placeholder", MONTH_PLACEHOLDER);
      input.setAttribute("pattern", MONTH_PATTERN);
      input.setAttribute("inputmode", "numeric");
    }
    slot.appendChild(input);
    return input;
  }

  /** Create the input of each empty slot under `scope` and return them;
   *  slots in a row prototype are left for its copies. */
  function materialize(scope) {
    const created = [];
    for (const slot of scope.querySelectorAll(".pf-slot[data-pf-input]")) {
      if (slot.firstElementChild || slot.closest("[data-pf-prototype]")) continue;
      const input = createInput(slot);
      if (input) created.push(input);
    }
    return created;
  }

  function setControlValue(control, value) {
    const text = typeof value === "string" ? value : "";
    if (control.value !== text) control.value = text;
  }

  /** Write the stored values into every bound control under `scope`. */
  function applyValues(scope) {
    for (const control of scope.querySelectorAll("[data-pf-field][data-pf-path]")) {
      const fieldId = control.getAttribute("data-pf-field");
      const path = pathOf(control);
      if (path && form.config.fields[fieldId]) setControlValue(control, readPath(fieldId, path));
    }
  }

  /** A fresh copy of a container's row prototype with its inputs created. */
  function instantiate(container) {
    const row = container.querySelector("[data-pf-prototype] tr").cloneNode(true);
    materialize(row);
    return row;
  }

  /** Put `rows` into `tbody` in order, moving only what is out of place (a
   *  moved element would lose focus), and drop the rest. */
  function placeRows(tbody, rows) {
    rows.forEach((row, index) => {
      if (tbody.children[index] !== row) tbody.insertBefore(row, tbody.children[index] || null);
    });
    while (tbody.children.length > rows.length) tbody.lastElementChild.remove();
  }

  function bindRowControls(row, fieldId, pathFor, values) {
    for (const control of row.querySelectorAll("[data-pf-control]")) {
      const controlId = control.getAttribute("data-pf-control");
      control.setAttribute("data-pf-field", fieldId);
      control.setAttribute("data-pf-path", JSON.stringify(pathFor(controlId)));
      setControlValue(control, values[controlId]);
    }
  }

  /** Give back the input of any slot that lost it, with its value and
   *  disabled state. */
  function restoreSlots() {
    const restored = materialize(form.root);
    if (!restored.length) return;
    const fieldIds = new Set();
    for (const input of restored) {
      applyValues(input.parentElement);
      const fieldId = input.getAttribute("data-pf-field");
      if (fieldId && form.config.fields[fieldId]) fieldIds.add(fieldId);
    }
    for (const fieldId of fieldIds) refreshFigures(fieldId);
  }

  // --- Lists ----------------------------------------------------------------

  function listContainer(fieldId) {
    return form.root.querySelector(`[data-pf-list="${CSS.escape(fieldId)}"]`);
  }

  /** Draw a list field's rows from its items, keyed by `_rowId`. */
  function renderList(fieldId) {
    const container = listContainer(fieldId);
    const tbody = container.querySelector("tbody[data-pf-rows]");
    const existing = new Map();
    for (const row of tbody.children) existing.set(row.getAttribute("data-pf-row-id"), row);
    const rows = form.values[fieldId].map((item, index) => {
      let row = existing.get(item._rowId);
      existing.delete(item._rowId);
      if (!row) {
        row = instantiate(container);
        row.setAttribute("data-pf-row-id", item._rowId);
        bindRowControls(row, fieldId, (controlId) => [item._rowId, controlId], item);
      }
      const number = index + 1;
      for (const control of row.querySelectorAll("[data-pf-control]")) {
        control.setAttribute("aria-label", `${control.getAttribute("data-pf-label")} for Item ${number}`);
      }
      const remove = row.querySelector("[data-pf-remove]");
      remove.setAttribute("data-pf-remove", item._rowId);
      remove.setAttribute("aria-label", `Remove item ${number}`);
      return row;
    });
    placeRows(tbody, rows);
    container.setAttribute("data-pf-empty", rows.length ? "false" : "true");
  }

  function addItem(fieldId) {
    const field = form.config.fields[fieldId];
    const item = blankItem(field);
    form.values[fieldId].push(item);
    renderList(fieldId);
    changed(fieldId);
    const row = listContainer(fieldId).querySelector(`tr[data-pf-row-id="${CSS.escape(item._rowId)}"]`);
    const first = row && row.querySelector("[data-pf-control]");
    if (first) first.focus();
  }

  function removeItem(fieldId, rowId) {
    form.values[fieldId] = form.values[fieldId].filter((item) => item._rowId !== rowId);
    renderList(fieldId);
    changed(fieldId);
    const add = listContainer(fieldId).querySelector("[data-pf-add]");
    if (add) add.focus();
  }

  // --- Worksheet ------------------------------------------------------------

  function worksheetContainer(fieldId) {
    return form.root.querySelector(`[data-pf-worksheet="${CSS.escape(fieldId)}"]`);
  }

  /** The worksheet's rows from its source list (pcn_clone.core.worksheet
   *  derive_worksheet_rows). */
  function deriveRows(field) {
    const source = field.rowSource;
    const items = form.values[source.fieldId];
    return (Array.isArray(items) ? items : []).filter(isPlainObject).map((item) => {
      const text = (key) => (typeof item[key] === "string" ? item[key] : "");
      const match = /^(\d{4})/.exec(text(source.startDateControlId).trim());
      const startYear = match ? Number(match[1]) : null;
      return {
        rowId: text("_rowId"),
        label: text(source.labelControlId).trim(),
        startYear,
        hasStartDate: startYear !== null,
      };
    });
  }

  function costsOf(fieldId) {
    const answer = form.values[fieldId];
    return isPlainObject(answer) && isPlainObject(answer.componentCosts) ? answer.componentCosts : {};
  }

  function rowTotal(field, rowValues) {
    const values = isPlainObject(rowValues) ? rowValues : {};
    return field.sum.reduce((total, controlId) => total + numbers().toAmount(values[controlId]), 0);
  }

  /** Draw the worksheet's rows from the source list, then its figures. */
  function renderWorksheet(fieldId) {
    const field = form.config.fields[fieldId];
    const container = worksheetContainer(fieldId);
    const tbody = container.querySelector("tbody[data-pf-rows]");
    const derived = deriveRows(field);
    const costs = costsOf(fieldId);
    const existing = new Map();
    for (const row of tbody.children) existing.set(row.getAttribute("data-pf-row-id"), row);
    const rows = derived.map((spec) => {
      let row = existing.get(spec.rowId);
      existing.delete(spec.rowId);
      if (!row) {
        row = instantiate(container);
        row.setAttribute("data-pf-row-id", spec.rowId);
        bindRowControls(
          row,
          fieldId,
          (controlId) => ["componentCosts", spec.rowId, controlId],
          isPlainObject(costs[spec.rowId]) ? costs[spec.rowId] : {},
        );
      }
      const label = spec.label || "(unnamed item)";
      row.querySelector(".pf-ws-row-label").textContent = label;
      row.querySelector(".pf-ws-row-years").textContent = spec.hasStartDate
        ? `years ${spec.startYear}–${spec.startYear + field.requiredSpan - 1}`
        : "";
      row.setAttribute("data-pf-start", spec.hasStartDate ? "set" : "missing");
      for (const control of row.querySelectorAll("[data-pf-control]")) {
        control.disabled = !spec.hasStartDate;
        control.setAttribute("aria-label", `${control.getAttribute("data-pf-label")} for ${label}`);
      }
      return row;
    });
    placeRows(tbody, rows);
    container.setAttribute("data-pf-empty", rows.length ? "false" : "true");
    updateWorksheetFigures(fieldId, derived);
  }

  /** Row totals, the category summary and its total row
   *  (pcn_clone.core.worksheet compute_row_total and
   *  compute_category_summary). Rows without a start date count nowhere. */
  function updateWorksheetFigures(fieldId, derived) {
    const field = form.config.fields[fieldId];
    const container = worksheetContainer(fieldId);
    const rows = derived || deriveRows(field);
    const costs = costsOf(fieldId);
    const format = numbers().formatAmount;
    for (const row of container.querySelectorAll("tbody[data-pf-rows] > tr")) {
      const spec = rows.find((candidate) => candidate.rowId === row.getAttribute("data-pf-row-id"));
      row.querySelector("[data-pf-total]").textContent =
        spec && spec.hasStartDate ? format(rowTotal(field, costs[spec.rowId])) : "—";
    }
    const figures = {};
    const totals = { perColumn: {}, total: 0 };
    for (const column of field.sum) totals.perColumn[column] = 0;
    for (const option of field.categories) {
      const perColumn = {};
      for (const column of field.sum) perColumn[column] = 0;
      let total = 0;
      for (const row of rows) {
        if (!row.hasStartDate) continue;
        const values = isPlainObject(costs[row.rowId]) ? costs[row.rowId] : {};
        if ((values[field.groupBy] ?? "") !== option.value) continue;
        for (const column of field.sum) perColumn[column] += numbers().toAmount(values[column]);
        total += rowTotal(field, values);
      }
      totals.total += total;
      figures[option.value] = { perColumn, total };
    }
    for (const column of field.sum) {
      totals.perColumn[column] = field.categories.reduce(
        (sum, option) => sum + figures[option.value].perColumn[column],
        0,
      );
    }
    figures[""] = totals;
    for (const cell of container.querySelectorAll("[data-pf-sum]")) {
      const [category, column] = cell.getAttribute("data-pf-sum").split("|");
      const entry = figures[category];
      if (!entry) continue;
      cell.textContent = format(column ? entry.perColumn[column] : entry.total);
    }
  }

  // --- Scenario comparison --------------------------------------------------

  /** Gate the entered cells and compute the derived ones
   *  (pcn_clone.core.scenario is_applicable and compute_computed_cell). */
  function updateScenario(fieldId) {
    const field = form.config.fields[fieldId];
    const container = form.root.querySelector(`[data-pf-scenario="${CSS.escape(fieldId)}"]`);
    const answer = isPlainObject(form.values[fieldId]) ? form.values[fieldId] : {};
    const rows = isPlainObject(answer.rows) ? answer.rows : {};
    const applicability = isPlainObject(answer.applicability) ? answer.applicability : {};
    const applicable = !field.gate || applicability[field.gate.id] === field.gate.activeValue;
    for (const control of container.querySelectorAll("[data-pf-path]")) {
      const path = pathOf(control);
      if (path && path[0] === "rows") control.disabled = !applicable;
    }
    const cellValue = (rowId, columnId) => (isPlainObject(rows[rowId]) ? rows[rowId][columnId] : undefined);
    for (const cell of container.querySelectorAll("[data-pf-computed]")) {
      const [rowId, columnId] = cell.getAttribute("data-pf-computed").split("|");
      const computed = field.computedRows.find((row) => row.id === rowId);
      let text = "—";
      if (applicable && computed) {
        const left = numbers().parseScenarioAmount(cellValue(computed.subtract[0], columnId));
        const right = numbers().parseScenarioAmount(cellValue(computed.subtract[1], columnId));
        if (left.present && left.ok && right.present && right.ok) {
          text = numbers().formatAmount(left.value - right.value);
        }
      }
      cell.textContent = text;
    }
  }

  // --- Static table ---------------------------------------------------------

  /** Make the cells of rows whose gate column holds the inert value inert:
   *  disabled, selects showing "n/a"; the gate cell and comment textareas
   *  stay editable. */
  function updateStatic(fieldId) {
    const field = form.config.fields[fieldId];
    const container = form.root.querySelector(`[data-pf-static="${CSS.escape(fieldId)}"]`);
    const answer = isPlainObject(form.values[fieldId]) ? form.values[fieldId] : {};
    const rows = isPlainObject(answer.rows) ? answer.rows : {};
    const types = {};
    for (const column of field.columns) types[column.id] = column.type;
    for (const control of container.querySelectorAll("[data-pf-path]")) {
      const path = pathOf(control);
      if (!path || path[0] !== "rows") continue;
      const [, rowId, columnId] = path;
      const gate = field.gateColumn;
      const inert = !!gate && isPlainObject(rows[rowId]) && rows[rowId][gate] === field.inertValue;
      const cellInert = inert && columnId !== gate && types[columnId] !== "textarea";
      control.disabled = cellInert;
      if (control.tagName === "SELECT" && control.options.length) {
        control.options[0].textContent = cellInert ? "n/a" : "—";
      }
    }
  }

  /** Recompute the live figures that depend on a field. */
  function refreshFigures(fieldId) {
    const kind = form.config.fields[fieldId].kind;
    if (kind === "worksheet") updateWorksheetFigures(fieldId);
    else if (kind === "scenario_comparison") updateScenario(fieldId);
    else if (kind === "static_table") updateStatic(fieldId);
    for (const dependent of form.dependents[fieldId] || []) renderWorksheet(dependent);
  }

  // --- Edits ----------------------------------------------------------------

  function onEdit(event) {
    const control = event.target;
    if (!form || !form.hydrated || !(control instanceof Element)) return;
    const fieldId = control.getAttribute("data-pf-field");
    const path = fieldId && pathOf(control);
    if (!path || !form.config.fields[fieldId]) return;
    if (readPath(fieldId, path) === control.value) return;
    writePath(fieldId, path, control.value);
    changed(fieldId);
  }

  /** After a field's answer changed: mirror, autosave, figures, readiness
   *  and feedback state, for the field and the worksheets drawn from it. */
  function changed(fieldId) {
    mirror();
    scheduleSave();
    refreshFigures(fieldId);
    for (const id of [fieldId, ...(form.dependents[fieldId] || [])]) {
      updateReadiness(id, READINESS_DELAY_MS);
      renderField(id);
    }
  }

  function mirror() {
    setProps(ids().formValues, { data: Object.assign({}, form.values) });
  }

  // --- Autosave -------------------------------------------------------------

  function scheduleSave() {
    if (!form || !form.hydrated) return;
    if (form.saveTimer !== null) clearTimeout(form.saveTimer);
    form.saveTimer = setTimeout(save, AUTOSAVE_DELAY_MS);
  }

  /** Write the draft and bump the project's edited time. */
  function save() {
    form.saveTimer = null;
    try {
      store().saveDraft(form.project.id, form.values);
      store().updateProject(form.project.id, {});
      form.lastSaved = new Date();
      form.saveFailed = false;
    } catch (_error) {
      form.saveFailed = true;
    }
    renderAutosave();
  }

  /** Write a pending save now. */
  function flushSave() {
    if (form && form.saveTimer !== null) {
      clearTimeout(form.saveTimer);
      save();
    }
  }

  function renderAutosave() {
    if (form.saveFailed) {
      setPropsOnce("autosave", ids().autosave, { children: SAVE_FAILED, className: "pf-autosave is-failed" });
      return;
    }
    const label = form.lastSaved
      ? `Last saved at ${form.lastSaved.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`
      : messages().autosaveIdle;
    setPropsOnce("autosave", ids().autosave, { children: label, className: "pf-autosave" });
  }

  // --- Readiness ------------------------------------------------------------

  /** Whether a text, textarea or group answer is complete: non-blank text,
   *  every group control non-blank (pcn_clone.core.fields
   *  is_field_answer_complete). */
  function isComplete(field, value) {
    if (field.kind === "group") {
      return isPlainObject(value) && field.controls.every((control) => isNonBlank(value[control.id]));
    }
    return isNonBlank(value);
  }

  /** A field's answer changed: decide its readiness now, or owe the
   *  server's answer and ask for it after `delay` ms. */
  function updateReadiness(fieldId, delay) {
    const field = form.config.fields[fieldId];
    if (field.readiness === "local") {
      form.readiness[fieldId] = { ready: isComplete(field, form.values[fieldId]), pending: false };
      return;
    }
    form.readinessOwed[fieldId] = (form.readinessOwed[fieldId] || 0) + 1;
    form.readiness[fieldId] = { ready: false, pending: true };
    clearTimeout(form.readinessTimer);
    form.readinessTimer = setTimeout(requestReadiness, delay);
  }

  /** Send every owed answer, each with the number of its latest edit. */
  function requestReadiness() {
    if (!form) return;
    form.readinessTimer = null;
    const request = {};
    for (const [fieldId, n] of Object.entries(form.readinessOwed)) {
      if (!form.readiness[fieldId].pending) continue;
      request[fieldId] = { answer: clone(form.values[fieldId]), context: clone(contextFor(fieldId)), n };
    }
    if (Object.keys(request).length) setProps(ids().readinessRequest, { data: request });
  }

  /** The server's readiness answers; one for an earlier edit is ignored. */
  function readinessArrived(answers) {
    if (!isPlainObject(answers)) return;
    for (const [fieldId, answer] of Object.entries(answers)) {
      if (!form.config.fields[fieldId] || !isPlainObject(answer)) continue;
      if (answer.n !== form.readinessOwed[fieldId]) continue;
      form.readiness[fieldId] = { ready: answer.ready === true, pending: false };
      renderField(fieldId);
    }
  }

  // --- Evaluation -----------------------------------------------------------

  function isEvaluating(fieldId) {
    const state = form.states[fieldId];
    return (state && state.status === "evaluating") || form.running[fieldId] === true;
  }

  /** Whether a click on the field's Evaluate button starts an evaluation:
   *  its latest answer is known to be ready and none is running. */
  function canEvaluate(fieldId) {
    const readiness = form.readiness[fieldId];
    return !!readiness && readiness.ready && !readiness.pending && !isEvaluating(fieldId);
  }

  /** Start an evaluation: send the answer (and context) and keep the
   *  signature of exactly what was sent. */
  function beginEvaluation(fieldId) {
    const field = form.config.fields[fieldId];
    const n = (form.evaluationsSent[fieldId] || 0) + 1;
    form.evaluationsSent[fieldId] = n;
    const answer = clone(form.values[fieldId]);
    const context = clone(contextFor(fieldId));
    form.pending[fieldId] = {
      n,
      signature: signatureOf(field, answer, context),
      previous: form.states[fieldId] || null,
    };
    form.states[fieldId] = { status: "evaluating" };
    clearTimeout(form.graceTimers[fieldId]);
    setProps(fieldKey(ids().evaluateRequest, fieldId), { data: { answer, context, n } });
    renderField(fieldId);
  }

  /** The response to the field's latest evaluation request. */
  function finishEvaluation(fieldId, response) {
    const pending = form.pending[fieldId];
    if (!pending || !isPlainObject(response) || response.n !== pending.n) return;
    delete form.pending[fieldId];
    clearTimeout(form.graceTimers[fieldId]);
    if (response.notReady === true) {
      if (pending.previous) form.states[fieldId] = pending.previous;
      else delete form.states[fieldId];
      updateReadiness(fieldId, 0);
    } else if (response.ok && isPlainObject(response.result)) {
      form.states[fieldId] = { status: "graded", result: response.result, signature: pending.signature };
    } else {
      form.states[fieldId] = {
        status: "failed",
        errorMessage: response.errorMessage || messages().transportFailure,
      };
    }
    renderField(fieldId);
  }

  /** The running flag the evaluate callback raises and lowers. When it
   *  drops without a response arriving, the request failed in transit. */
  function runningChanged(fieldId, running) {
    form.running[fieldId] = running;
    delete form.sent[`button:${fieldId}`];
    clearTimeout(form.graceTimers[fieldId]);
    const pending = form.pending[fieldId];
    if (!running && pending) {
      form.graceTimers[fieldId] = setTimeout(() => {
        if (!form || form.pending[fieldId] !== pending) return;
        delete form.pending[fieldId];
        form.states[fieldId] = { status: "failed", errorMessage: messages().transportFailure };
        renderField(fieldId);
      }, RESPONSE_GRACE_MS);
    }
    renderField(fieldId);
  }

  /** A field's footer and Evaluate button, and its section's tally. The
   *  footer's live region holds the state only; the button keeps its action
   *  as its accessible name while it shows "Evaluating…", so the state is
   *  announced once. */
  function renderField(fieldId) {
    if (!form || !form.hydrated) return;
    const field = form.config.fields[fieldId];
    const state = form.states[fieldId] || { status: "idle" };
    const evaluating = isEvaluating(fieldId);
    const graded = !evaluating && state.status === "graded";
    const failed = !evaluating && state.status === "failed";
    const stale = graded && signature(fieldId) !== state.signature;
    const pending = form.pending[fieldId];
    const regrade = graded || (evaluating && !!pending && !!pending.previous && pending.previous.status === "graded");

    const status = [];
    if (evaluating) {
      status.push(node("Span", { className: "pf-evaluating" }, [spinnerNode(14), EVALUATING_LABEL]));
    }
    if (graded) {
      status.push(
        node("Button", { type: "button", className: "pf-notes-button", "data-pf-notes": fieldId }, [
          verdictNode(state.result.verdict, true),
          node(
            "Span",
            { className: stale ? "pf-notes-label is-stale" : "pf-notes-label" },
            stale ? "Out of date · view notes" : "View review notes",
          ),
          node("Span", { className: "pf-notes-chevron" }, [iconNode("chevron-right", 14, true)]),
        ]),
      );
      if (stale) {
        status.push(
          node("Span", { className: "pf-badge is-stale" }, [
            iconNode("alert-triangle", 13, true),
            "Feedback out of date",
          ]),
        );
      }
    }
    if (failed) {
      status.push(
        node("Span", { role: "alert", className: "pf-badge is-failed" }, [
          iconNode("alert-triangle", 13, true),
          `Evaluation failed — ${state.errorMessage}`,
        ]),
      );
    }
    setPropsOnce(`status:${fieldId}`, fieldKey(ids().status, fieldId), { children: status });

    const action = regrade ? REEVALUATE_LABEL : messages().evaluate;
    setPropsOnce(`button:${fieldId}`, fieldKey(ids().evaluate, fieldId), {
      children: evaluating ? [EVALUATING_LABEL] : [iconNode("sparkle", 15), action],
      className: `btn btn-md ${!graded || stale ? "btn-primary" : "btn-secondary"}`,
      disabled: evaluating || !canEvaluate(fieldId),
      "aria-label": fill(messages().fieldAction, { action, number: field.number, title: field.title }),
    });
    renderTally(field.sectionId);
  }

  /** A section's counts by state: verdicts in rubric order, then
   *  evaluating, failed and not evaluated; zero counts are left out. */
  function renderTally(sectionId) {
    const section = form.config.sections.find((candidate) => candidate.id === sectionId);
    const verdicts = Object.keys(form.config.verdicts);
    const counts = { evaluating: 0, failed: 0, idle: 0 };
    for (const verdict of verdicts) counts[verdict] = 0;
    for (const fieldId of section.fieldIds) {
      const state = form.states[fieldId];
      if (isEvaluating(fieldId)) counts.evaluating += 1;
      else if (!state || state.status === "idle") counts.idle += 1;
      else if (state.status === "failed") counts.failed += 1;
      else if (hasOwn(counts, state.result.verdict)) counts[state.result.verdict] += 1;
    }
    const items = [];
    for (const verdict of verdicts) {
      if (!counts[verdict]) continue;
      items.push(
        node("Span", { className: `pf-tally-item is-${TALLY_TONE[verdict]}` }, [
          node("Span", { className: "pf-tally-dot", "aria-hidden": "true" }),
          `${counts[verdict]} ${form.config.verdicts[verdict].label}`,
        ]),
      );
    }
    if (counts.evaluating) {
      items.push(
        node("Span", { className: "pf-tally-item is-evaluating" }, [
          spinnerNode(12),
          `${counts.evaluating} evaluating`,
        ]),
      );
    }
    if (counts.failed) {
      items.push(
        node("Span", { className: "pf-tally-item is-failed" }, [
          iconNode("alert-triangle", 12, true),
          `${counts.failed} failed`,
        ]),
      );
    }
    if (counts.idle) {
      items.push(
        node("Span", { className: "pf-tally-item is-idle" }, [
          node("Span", { className: "pf-tally-dot", "aria-hidden": "true" }),
          `${counts.idle} not evaluated`,
        ]),
      );
    }
    setPropsOnce(`tally:${sectionId}`, { type: ids().tally, section: sectionId }, { children: items });
  }

  /** Open the shared review-notes dialog on a graded field's feedback. Its
   *  heading is laid out as the field dialogs' (dialogs.dialog_heading in
   *  Python), the verdict beside it. */
  function openNotes(fieldId) {
    const state = form.states[fieldId];
    if (!state || state.status !== "graded") return;
    const field = form.config.fields[fieldId];
    const result = state.result;
    const stale = signature(fieldId) !== state.signature;
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions : [];
    const title = [
      node("Span", { className: "pf-dialog-icon is-blue" }, iconNode("sparkle", 16)),
      node("Span", { className: "pf-dialog-names" }, [
        node("Span", { className: "pf-dialog-title" }, NOTES_TITLE),
        node("Span", { className: "pf-dialog-field" }, [
          node("Span", { className: "pf-dialog-number" }, [
            field.number,
            node("Span", { className: "sr-only" }, " — "),
          ]),
          field.title,
        ]),
      ]),
      verdictNode(result.verdict, true),
    ];
    const body = [];
    if (stale) {
      body.push(
        node("Div", { role: "status", className: "pf-notes-stale" }, [
          iconNode("alert-triangle", 14, true),
          "Feedback is out of date — the answer has changed since it was evaluated. " +
            "Re-evaluate the field to refresh it.",
        ]),
      );
    }
    body.push(
      node("Section", { className: "pf-notes-section" }, [
        node("H3", { className: "pf-notes-heading" }, "Reasoning"),
        node("P", { className: "pf-dialog-prose" }, String(result.reasoning || "")),
      ]),
    );
    if (suggestions.length) {
      body.push(
        node("Section", { className: "pf-notes-section" }, [
          node("H3", { className: "pf-notes-heading" }, "Suggestions"),
          node(
            "Ol",
            { className: "pf-notes-suggestions" },
            suggestions.map((suggestion) => node("Li", {}, String(suggestion))),
          ),
        ]),
      );
    } else {
      body.push(node("P", { className: "pf-notes-none" }, "No suggestions — the answer meets the standard."));
    }
    setProps(ids().notesDialog, { title, children: body, opened: true });
  }

  /** Dialogs are named by their heading only: drop the description Mantine
   *  points at the whole body. */
  function undescribeDialogs() {
    for (const dialog of document.querySelectorAll(".pf-dialog[aria-describedby]")) {
      dialog.removeAttribute("aria-describedby");
    }
  }

  // --- Chrome: scroll-spy, progress, jump, back to top -----------------------

  function sectionAnchor(sectionId) {
    return document.getElementById(ids().anchorPrefix + sectionId);
  }

  /** The height of the sticky chrome (suite header and context bar). */
  function chromeOffset() {
    let total = 0;
    for (const element of document.querySelectorAll("[data-sticky-chrome]")) {
      total += element.getBoundingClientRect().height;
    }
    return total;
  }

  function onScroll() {
    if (!form || form.scrollFrame) return;
    form.scrollFrame = window.requestAnimationFrame(() => {
      if (!form) return;
      form.scrollFrame = 0;
      updateScroll();
    });
  }

  function updateScroll() {
    const line = chromeOffset() + 24;
    let current = form.config.sections[0].id;
    for (const section of form.config.sections) {
      const anchor = sectionAnchor(section.id);
      if (anchor && anchor.getBoundingClientRect().top <= line) current = section.id;
    }
    if (current !== form.activeSection) {
      form.activeSection = current;
      renderJump();
    }
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    document.documentElement.style.setProperty("--scroll-progress", `${progress * 100}%`);
    const visible = window.scrollY > window.innerHeight;
    if (visible !== form.backToTopVisible) {
      form.backToTopVisible = visible;
      setProps(ids().backToTop, {
        className: visible ? "pf-back-to-top is-visible" : "pf-back-to-top",
        tabIndex: visible ? "0" : "-1",
        "aria-hidden": visible ? null : "true",
      });
    }
  }

  /** The jump menu's trigger and ticked row for the section in view. */
  function renderJump() {
    const active = form.config.sections.find((section) => section.id === form.activeSection);
    setProps(ids().jumpNumber, { children: active.number });
    setProps(ids().jumpTitle, { children: active.title });
    setProps(ids().jumpTrigger, {
      "aria-label": fill(messages().jumpCurrent, { number: active.number, title: active.title }),
    });
    for (const section of form.config.sections) {
      const on = section.id === active.id;
      setProps(
        { type: ids().jumpItem, section: section.id },
        {
          className: on ? "pf-jump-item is-active" : "pf-jump-item",
          rightSection: on ? iconNode("check", 15, true) : null,
        },
      );
    }
  }

  /** Scroll so the section's top sits just below the sticky chrome. */
  function jumpTo(sectionId) {
    const anchor = sectionAnchor(sectionId);
    if (!anchor) return;
    const top = window.scrollY + anchor.getBoundingClientRect().top - chromeOffset() - 18;
    window.scrollTo({ top: Math.max(0, top), behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  /** Move the focus to the section's heading once the closing jump menu
   *  has handed it back to its trigger (or after MENU_FOCUS_WAIT_MS). */
  function focusSectionAfterMenu(sectionId) {
    const anchor = sectionAnchor(sectionId);
    const heading = anchor && anchor.querySelector("h2[tabindex]");
    if (!heading) return;
    if (form.stopJumpFocus) form.stopJumpFocus();
    const trigger = document.getElementById(ids().jumpTrigger);
    const focusHeading = () => {
      stop();
      heading.focus({ preventScroll: true });
    };
    const onFocusIn = (event) => {
      if (event.target === trigger) focusHeading();
    };
    const timer = setTimeout(focusHeading, MENU_FOCUS_WAIT_MS);
    function stop() {
      clearTimeout(timer);
      document.removeEventListener("focusin", onFocusIn, true);
      if (form && form.stopJumpFocus === stop) form.stopJumpFocus = null;
    }
    document.addEventListener("focusin", onFocusIn, true);
    form.stopJumpFocus = stop;
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  // --- Listeners ------------------------------------------------------------

  /** Clicks inside the workspace: list add/remove, review notes, back to top. */
  function onClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!form || !form.hydrated || !target) return;
    const add = target.closest("[data-pf-add]");
    if (add) {
      addItem(add.getAttribute("data-pf-add"));
      return;
    }
    const remove = target.closest("[data-pf-remove]");
    const list = remove && remove.closest("[data-pf-list]");
    if (remove && list && remove.getAttribute("data-pf-remove")) {
      removeItem(list.getAttribute("data-pf-list"), remove.getAttribute("data-pf-remove"));
      return;
    }
    const notes = target.closest("[data-pf-notes]");
    if (notes) {
      openNotes(notes.getAttribute("data-pf-notes"));
      return;
    }
    if (target.closest(`#${CSS.escape(ids().backToTop)}`)) scrollToTop();
  }

  /** Document clicks, seen before anything else handles them: an Evaluate
   *  click starts the evaluation, or is swallowed while the field is not
   *  known to be ready (the button's disabled state can trail an edit by a
   *  render); a jump-menu row (rendered outside the workspace, in the menu's
   *  portal) scrolls to its section. */
  function onCaptureClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!form || !form.hydrated || !target) return;
    const button = target.closest("[data-pf-evaluate]");
    if (button && form.root.contains(button)) {
      const fieldId = button.getAttribute("data-pf-evaluate");
      if (form.config.fields[fieldId] && !button.disabled && canEvaluate(fieldId)) {
        beginEvaluation(fieldId);
      } else {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
      return;
    }
    const item = target.closest("[data-pf-jump]");
    if (item) {
      const sectionId = item.getAttribute("data-pf-jump");
      focusSectionAfterMenu(sectionId);
      window.requestAnimationFrame(() => jumpTo(sectionId));
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === "hidden") flushSave();
  }

  /** Body changes: leaving the page (Dash navigation removes the
   *  workspace), dialogs opening, or a slot that lost its input. */
  function onMutation() {
    if (!form || !form.root) return;
    if (!form.root.isConnected) {
      teardown();
      return;
    }
    undescribeDialogs();
    restoreSlots();
  }

  function listen(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    form.listeners.push(() => target.removeEventListener(type, handler, options));
  }

  // --- Lifecycle ------------------------------------------------------------

  /** Build the workspace once its elements are in the page. */
  function bind(state) {
    const root = document.getElementById(state.config.ids.root);
    state.root = root;
    materialize(root);
    for (const [fieldId, field] of Object.entries(state.config.fields)) {
      if (field.kind === "list") renderList(fieldId);
    }
    for (const [fieldId, field] of Object.entries(state.config.fields)) {
      if (field.kind === "worksheet") renderWorksheet(fieldId);
      else if (field.kind === "scenario_comparison") updateScenario(fieldId);
      else if (field.kind === "static_table") updateStatic(fieldId);
    }
    applyValues(root);
    listen(root, "input", onEdit);
    listen(root, "change", onEdit);
    listen(root, "click", onClick);
    listen(document, "click", onCaptureClick, true);
    listen(document, "visibilitychange", onVisibilityChange);
    listen(window, "pagehide", flushSave);
    // In-app navigation (dcc.Link, back and forward) leaves the page.
    listen(window, "_dashprivate_pushstate", flushSave);
    listen(window, "popstate", flushSave);
    listen(window, "scroll", onScroll, { passive: true });
    listen(window, "resize", onScroll);
    state.observer = new MutationObserver(onMutation);
    state.observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-describedby"],
    });
    state.hydrated = true;
    root.setAttribute("data-pf-ready", "true");
    renderAutosave();
    for (const fieldId of Object.keys(state.config.fields)) updateReadiness(fieldId, 0);
    for (const fieldId of Object.keys(state.config.fields)) renderField(fieldId);
    undescribeDialogs();
    updateScroll();
  }

  /** Call `bind` once the workspace's root is in the page. */
  function whenRendered(state) {
    const started = Date.now();
    const poll = () => {
      if (form !== state) return;
      if (document.getElementById(state.config.ids.root)) {
        bind(state);
      } else if (Date.now() - started < MOUNT_TIMEOUT_MS) {
        setTimeout(poll, MOUNT_POLL_MS);
      }
    };
    poll();
  }

  function teardown() {
    const state = form;
    flushSave();
    for (const stop of state.listeners) stop();
    if (state.observer) state.observer.disconnect();
    if (state.scrollFrame) window.cancelAnimationFrame(state.scrollFrame);
    if (state.stopJumpFocus) state.stopJumpFocus();
    clearTimeout(state.readinessTimer);
    for (const timer of Object.values(state.graceTimers)) clearTimeout(timer);
    document.documentElement.style.removeProperty("--scroll-progress");
    form = null;
  }

  /** Restore the project's draft over the blank defaults; the result is the
   *  `form-values` store's first value. */
  function mount(config, project) {
    if (!isPlainObject(config) || !isPlainObject(project) || typeof project.id !== "string") {
      return dash().no_update;
    }
    if (form) teardown();
    let draft = null;
    try {
      draft = store().loadDraft(project.id);
    } catch (_error) {
      draft = null;
    }
    const values = {};
    for (const [fieldId, field] of Object.entries(config.fields)) {
      values[fieldId] = draft && hasOwn(draft, fieldId) ? normalize(field, draft[fieldId]) : clone(field.default);
    }
    if (draft) {
      for (const [key, value] of Object.entries(draft)) if (!hasOwn(values, key)) values[key] = value;
    }
    const dependents = {};
    for (const [fieldId, field] of Object.entries(config.fields)) {
      if (field.kind !== "worksheet") continue;
      (dependents[field.rowSource.fieldId] = dependents[field.rowSource.fieldId] || []).push(fieldId);
    }
    form = {
      config,
      project,
      values,
      dependents,
      root: null,
      hydrated: false,
      observer: null,
      listeners: [],
      sent: {},
      saveTimer: null,
      lastSaved: null,
      saveFailed: false,
      readiness: {},
      readinessOwed: {},
      readinessTimer: null,
      states: {},
      pending: {},
      evaluationsSent: {},
      running: {},
      graceTimers: {},
      activeSection: config.sections[0].id,
      backToTopVisible: false,
      scrollFrame: 0,
      stopJumpFocus: null,
    };
    whenRendered(form);
    return values;
  }

  // --- Entry points ---------------------------------------------------------

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.pcnForm = {
    mount,

    /** Open a field dialog from its header pill. */
    openDialog: function (clicks) {
      return clicks ? true : dash().no_update;
    },

    /** A field's evaluation response or running flag changed. */
    evaluationChanged: function () {
      if (!form || !form.hydrated) return;
      for (const { id, value } of triggered()) {
        if (!isPlainObject(id) || !form.config.fields[id.field]) continue;
        if (id.type === ids().evaluation) finishEvaluation(id.field, value);
        else if (id.type === ids().evaluating) runningChanged(id.field, value === true);
      }
    },

    /** The server's readiness answers arrived. */
    readinessChanged: function (answers) {
      if (form && form.hydrated) readinessArrived(answers);
    },
  };

  /** The open workspace, read by the submission step and the tests (each
   *  returns null while no workspace is open):
   *  - `hydrated()`: true once the draft is in the controls and edits are
   *    saved; read the answers only after that;
   *  - `snapshot()`: a deep copy of the current answers, the flat
   *    `{field id: answer}` map in stored shapes (`form-values` holds the
   *    same);
   *  - `signature(fieldId)`: the field's current answer signature;
   *  - `state(fieldId)`: a copy of the field's feedback state (`status`
   *    idle, evaluating, graded or failed, with the result or message). */
  window.pcnForm = {
    hydrated: () => !!(form && form.hydrated),
    snapshot: () => (form ? clone(form.values) : null),
    signature: (fieldId) => (form && form.config.fields[fieldId] ? signature(fieldId) : null),
    state: (fieldId) => (form ? clone(form.states[fieldId] || { status: "idle" }) : null),
  };
})();
