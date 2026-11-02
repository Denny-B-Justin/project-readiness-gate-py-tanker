/* pcnReviewUi: the assessor workspace in the browser (see
 * pcn_clone/app/review/workspace).
 *
 * The review session (review.js) publishes the open record, the summary's
 * save state and the completion into its stores; this script turns them
 * into the workspace. When a record arrives whose frozen structure is not
 * in the page's `rv-ws-shape` store, its structure (dimension definitions
 * and the MCA matrix) goes there and the server draws the views and the
 * card frames. From then on each change publishes a progress snapshot to
 * `rv-ws-progress`: the states, the completion, and every card whose drawn
 * state is stale (each card's top carries the key of the state it shows)
 * with the fields it cites; the server redraws those card regions, the
 * component regions and the memo panel. A component's cards are drawn from
 * the first time its view opens, so the hub stays light while the drafts
 * stream in. Results land card by card and a decision redraws its card,
 * never the page.
 *
 * The script owns what the reviewer types and the workspace's local state:
 * the open view (published to the session's `rv-part` store, which shows
 * it and scrolls to the top), the summary (handed to
 * pcnReview.changeSummary, which saves it), decision notes (saved on blur),
 * and the in-place editors. An opened editor's form is asked for through
 * `rv-ws-editing` and drawn once; the script keeps its draft and writes it
 * through pcnReview.decide on Save, recording a save that changes nothing
 * as an acceptance. A closed editor's form is cleared.
 *
 * A decision is written at the item's stored generation (the session's
 * record, which a write updates at once). While it is being written the
 * card's buttons are aria-disabled and what they are asked to do is queued,
 * then replayed once the write settles, stored or not: a click that ends a
 * note's edit, saving the note on blur, still acts. A stored decision moves
 * the focus to its redrawn footer.
 *
 * Every snapshot and editor request names all that is stale, so one that
 * Dash drops for a newer one loses nothing, and an unchanged one is not
 * sent again. The script listens to the workspace's root only.
 *
 * Dash renders the cards and owns their components' props: this script
 * changes Dash components only through `dash_clientside.set_props`. It
 * writes to the DOM directly only for what Dash does not track: the
 * native inputs it creates in the slots, the values and checked and
 * disabled states of the editors' and notes' controls, the editors'
 * citation rows (copied from their prototype), the editors' filled-in text,
 * the buttons' aria-disabled while a decision saves, and its `data-rv-*`
 * state attributes. No callback redraws an ancestor of any of them while it
 * is in use.
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const clone = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
  const isBlank = (value) => typeof value !== "string" || value.trim() === "";
  const dash = () => window.dash_clientside;

  /** The workspace; null until the configuration arrives. */
  let ws = null;

  const ids = () => ws.config.ids;
  const messages = () => ws.config.messages;
  const session = () => window[ws.config.api];

  /** `template` with each `{name}` replaced by `values[name]`. */
  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, (match, name) => (hasOwn(values, name) ? String(values[name]) : match));
  }

  function setProps(id, props) {
    const api = dash();
    if (api && typeof api.set_props === "function") api.set_props(id, props);
  }

  /** set_props, skipped when `props` equal what was last sent under `key`. */
  function setPropsOnce(key, id, props) {
    const serial = JSON.stringify(props);
    if (ws.sent[key] === serial) return;
    ws.sent[key] = serial;
    setProps(id, props);
  }

  /** A short stable hash of `text` (FNV-1a, 32 bits). */
  function hash(text) {
    let value = 0x811c9dc5;
    for (let index = 0; index < text.length; index += 1) {
      value ^= text.charCodeAt(index);
      value = Math.imul(value, 0x01000193) >>> 0;
    }
    return value.toString(16).padStart(8, "0");
  }

  // --- The record -----------------------------------------------------------

  /** An item's state in `record`; pending when the record holds none. */
  function stateIn(record, kind, item) {
    const states =
      kind === "dimension" ? record.dimensions : record.mca ? record.mca.criteria : null;
    const state = states && states[item];
    return isPlainObject(state) ? state : { status: "pending", generation: 0 };
  }

  /** An item's state as published, the one the cards show. */
  const itemState = (kind, item) => stateIn(ws.record, kind, item);

  /** An item's state as stored right now, to act on: a decision updates the
   *  session's record at once, before the published one follows. */
  function liveState(kind, item) {
    let record = null;
    try {
      record = session().record();
    } catch (_error) {
      record = null;
    }
    const current = isPlainObject(record) && record.id === ws.record.id ? record : ws.record;
    return stateIn(current, kind, item);
  }

  const keyOf = (state) => JSON.stringify(state);
  const dispositionOf = (state) =>
    state.status === "ok" && isPlainObject(state.disposition) ? state.disposition : null;

  function snapshotField(ref) {
    return (ws.record.fields || []).find(
      (field) => field.sectionId === ref.sectionId && field.fieldId === ref.fieldId,
    );
  }

  function locationOf(ref) {
    const field = snapshotField(ref);
    return field
      ? fill(messages().location, { section: field.sectionLabel, field: field.fieldLabel })
      : fill(messages().locationMissing, { ref: `${ref.sectionId}/${ref.fieldId}` });
  }

  /** Every citation an item's state shows: the draft's and the reviewer's. */
  function citedRefs(state) {
    const refs = [];
    const add = (list) => {
      if (Array.isArray(list)) for (const ref of list) if (isPlainObject(ref)) refs.push(ref);
    };
    if (isPlainObject(state.finding)) add(state.finding.evidence);
    if (isPlainObject(state.scoreFinding) && isPlainObject(state.scoreFinding.basis)) {
      add(state.scoreFinding.basis.evidence);
    }
    const disposition = dispositionOf(state);
    if (disposition) {
      add(disposition.evidence);
      if (isPlainObject(disposition.basis)) add(disposition.basis.evidence);
    }
    return refs;
  }

  /** The record's frozen structure, keyed by the review and its content. */
  function shapeOf(record) {
    const shape = {
      reviewId: record.id,
      dimensionDefs: (record.dimensionDefs || []).map(({ id, label, description }) => ({
        id,
        label,
        description,
      })),
      mca: record.mca ? { matrix: record.mca.matrix } : null,
    };
    shape.key = `${record.id}:${hash(JSON.stringify(shape))}`;
    return shape;
  }

  const anyPending = (record) =>
    [
      ...Object.values(record.dimensions || {}),
      ...Object.values((record.mca && record.mca.criteria) || {}),
    ].some((state) => !isPlainObject(state) || state.status === "pending");

  // --- The adjustment draft -------------------------------------------------
  // A not-evidenced basis pairs only with the scale-minimum score: raising
  // the score off the floor falls back to documented, and "not evidenced" is
  // refused off the floor.

  const adjust = {
    initialAdjustDraft(scoreFinding, initial) {
      if (initial) {
        return {
          score: initial.finalScore,
          rationale: initial.rationale,
          basisKind: initial.basis.kind,
          evidence: initial.basis.kind === "documented" ? initial.basis.evidence.map((ref) => ({ ...ref })) : [],
        };
      }
      const basis = scoreFinding.basis;
      return {
        score: scoreFinding.score,
        rationale: "",
        basisKind: basis.kind,
        evidence:
          basis.kind === "documented"
            ? basis.evidence.map(({ sectionId, fieldId, quote }) => ({ sectionId, fieldId, quote }))
            : [],
      };
    },
    withScore(draft, score, scaleMinimum) {
      return {
        ...draft,
        score,
        basisKind: score !== scaleMinimum && draft.basisKind === "not_evidenced" ? "documented" : draft.basisKind,
      };
    },
    withBasisKind(draft, basisKind, scaleMinimum) {
      if (basisKind === "not_evidenced" && draft.score !== scaleMinimum) return draft;
      return { ...draft, basisKind };
    },
    adjustDraftIssues(draft) {
      return {
        rationaleMissing: draft.rationale.trim().length === 0,
        evidenceMissing: draft.basisKind === "documented" && draft.evidence.length === 0,
      };
    },
    canSaveAdjustDraft(draft) {
      const issues = adjust.adjustDraftIssues(draft);
      return !issues.rationaleMissing && !issues.evidenceMissing;
    },
    toAdjustedDisposition(draft) {
      if (!adjust.canSaveAdjustDraft(draft)) {
        throw new Error("An incomplete adjustment cannot become a disposition.");
      }
      return {
        kind: "adjusted",
        finalScore: draft.score,
        rationale: draft.rationale,
        basis:
          draft.basisKind === "not_evidenced"
            ? { kind: "not_evidenced" }
            : { kind: "documented", evidence: draft.evidence.map(curatedRef) },
      };
    },
  };

  /** A curated citation with its blank quote and note left out. */
  function curatedRef({ sectionId, fieldId, quote, note }) {
    const ref = { sectionId, fieldId };
    if (quote) ref.quote = quote;
    if (note) ref.note = note;
    return ref;
  }

  // --- Cards ----------------------------------------------------------------

  const cardItem = (card) => ({
    kind: card.getAttribute("data-rv-kind"),
    item: card.getAttribute("data-rv-card"),
  });
  const cardKey = (card) => `${card.getAttribute("data-rv-kind")}:${card.getAttribute("data-rv-card")}`;

  /** The key of the state a card's top shows, or null before its first draw. */
  function drawnKey(card) {
    const top = card.querySelector(".rv-item-top > [data-rv-key]");
    return top ? top.getAttribute("data-rv-key") : null;
  }

  /** Whether the decision note shows: the item is decided (a score only by
   *  acceptance) and its decision carries a note or one is being added. */
  function noteShows(kind, state, key) {
    const disposition = dispositionOf(state);
    if (!disposition) return false;
    if (kind === "criterion" && disposition.kind !== "accepted") return false;
    return !!ws.notes[key] || !isBlank(disposition.note);
  }

  /** Bring a card's local state in line with its item: the note area, the
   *  note's text when the decision changed, an editor whose item is no
   *  longer drafted, and the focus a decision moves once its redraw lands. */
  function applyCard(card, kind, item, state) {
    const key = cardKey(card);
    const stateKey = keyOf(state);
    const disposition = dispositionOf(state);
    if (!disposition) ws.notes[key] = false;
    card.toggleAttribute("data-rv-note-open", noteShows(kind, state, key));
    const note = card.querySelector("[data-rv-note]");
    if (note && card.getAttribute("data-rv-note-for") !== stateKey && document.activeElement !== note) {
      note.value = disposition && typeof disposition.note === "string" ? disposition.note : "";
      card.setAttribute("data-rv-note-for", stateKey);
    }
    if (ws.editors[key] && state.status !== "ok") closeEditor(card);
    const focus = ws.focusNext[key];
    if (focus && state.generation >= focus.generation && drawnKey(card) === stateKey) {
      delete ws.focusNext[key];
      const active = document.activeElement;
      const target = card.querySelector(`.rv-item-foot [data-rv-action="${focus.action}"]`);
      if (target && (!active || active === document.body || card.contains(active))) {
        target.focus({ preventScroll: true });
      }
    }
  }

  /** Mark a card as saving a decision: its decision buttons say so to
   *  assistive tech and queue what they are asked to do. */
  function setSaving(card, saving) {
    card.toggleAttribute("data-rv-saving", saving);
    for (const button of card.querySelectorAll(".rv-card-view .btn")) {
      if (saving) button.setAttribute("aria-disabled", "true");
      else button.removeAttribute("aria-disabled");
    }
  }

  /** Record a decision on a card's item at its stored generation (null
   *  clears it); resolves true once stored. While the write is in flight the
   *  card's decisions queue; when it settles, stored or not, the card is
   *  usable again, the last queued decision is replayed, and on success the
   *  focus moves to the `focusOn` control of the redrawn footer. */
  function decide(card, disposition, focusOn) {
    const key = cardKey(card);
    const { kind, item } = cardItem(card);
    const state = liveState(kind, item);
    if (state.status !== "ok") return Promise.resolve(false);
    setSaving(card, true);
    let result;
    try {
      result = session().decide(ws.record.id, kind, item, state.generation, disposition);
    } catch (_error) {
      result = false;
    }
    return Promise.resolve(result)
      .then(
        (stored) => stored === true,
        () => false,
      )
      .then((stored) => {
        setSaving(card, false);
        if (stored && focusOn) ws.focusNext[key] = { action: focusOn, generation: state.generation + 1 };
        const queued = ws.queued[key];
        delete ws.queued[key];
        if (queued) act(card, queued);
        schedule();
        return stored;
      });
  }

  /** Save a decision note on blur; a blank note is removed. */
  function saveNote(card, value) {
    const { kind, item } = cardItem(card);
    const disposition = dispositionOf(liveState(kind, item));
    if (!disposition) return;
    const note = isBlank(value) ? undefined : value;
    if (note === disposition.note) return;
    const next = { ...disposition };
    if (note === undefined) delete next.note;
    else next.note = note;
    decide(card, next);
  }

  // --- Editors --------------------------------------------------------------

  const editorOf = (card) => ws.editors[cardKey(card)];

  /** An edit that changed nothing endorses the draft. */
  function isUnchangedEdit(payload, finding) {
    if (
      payload.finalVerdict !== finding.verdict ||
      payload.finalText !== finding.reasoning ||
      payload.evidence.length !== finding.evidence.length
    ) {
      return false;
    }
    return payload.evidence.every((ref, index) => {
      const base = finding.evidence[index];
      return (
        ref.sectionId === base.sectionId &&
        ref.fieldId === base.fieldId &&
        (ref.quote === undefined ? "" : ref.quote) === base.quote &&
        ref.note === undefined
      );
    });
  }

  function openEditor(card) {
    const { kind, item } = cardItem(card);
    const state = liveState(kind, item);
    if (state.status !== "ok") return;
    const disposition = dispositionOf(state);
    let editor;
    if (kind === "dimension") {
      const edited = disposition && disposition.kind === "edited" ? disposition : null;
      editor = {
        base: state.finding,
        initialNote: edited ? edited.note : undefined,
        draft: {
          verdict: edited ? edited.finalVerdict : state.finding.verdict,
          text: edited ? edited.finalText : state.finding.reasoning,
          evidence: edited
            ? clone(edited.evidence)
            : state.finding.evidence.map(({ sectionId, fieldId, quote }) => ({ sectionId, fieldId, quote })),
        },
      };
    } else {
      const adjusted = disposition && disposition.kind === "adjusted" ? disposition : null;
      editor = {
        base: state.scoreFinding,
        existingNote: disposition && disposition.kind === "accepted" ? disposition.note : undefined,
        scaleMinimum: ws.record.mca.matrix.scale[0].value,
        draft: adjust.initialAdjustDraft(state.scoreFinding, adjusted),
      };
    }
    Object.assign(editor, { kind, item, card, state, element: null, saving: false });
    ws.editors[cardKey(card)] = editor;
    card.setAttribute("data-rv-editing", "");
    schedule();
  }

  /** The editor's form has been drawn: create its inputs, put the draft
   *  into them and move the focus there. */
  function bindEditor(editor, element) {
    editor.element = element;
    materialize(element);
    writeEditor(editor);
    const first = element.querySelector("input[type=radio]:checked") || element.querySelector("textarea");
    if (first) first.focus({ preventScroll: true });
  }

  function closeEditor(card) {
    const key = cardKey(card);
    if (ws.editors[key] && ws.editors[key].element) ws.clearing[key] = true;
    delete ws.editors[key];
    card.removeAttribute("data-rv-editing");
    schedule();
  }

  function checkRadio(element, choice, value) {
    for (const radio of element.querySelectorAll(`[data-rv-choice="${choice}"] input[type=radio]`)) {
      radio.checked = radio.value === String(value);
    }
  }

  function fillText(element, name, text) {
    for (const target of element.querySelectorAll(`[data-rv-fill="${name}"]`)) target.textContent = text;
  }

  /** Put an opening draft into the editor's controls. */
  function writeEditor(editor) {
    const { element, draft } = editor;
    if (editor.kind === "dimension") {
      checkRadio(element, "verdict", draft.verdict);
      element.querySelector('[data-rv-field="text"]').value = draft.text;
    } else {
      const ai = editor.base.score;
      for (const option of element.querySelectorAll("[data-rv-value]")) {
        option.toggleAttribute("data-rv-ai", option.getAttribute("data-rv-value") === String(ai));
      }
      fillText(element, "ai-score", String(ai));
      fillText(element, "ai-justification", editor.base.justification);
      element.querySelector('[data-rv-field="rationale"]').value = draft.rationale;
    }
    setAdding(editor, false);
    drawRows(editor);
    refreshEditor(editor);
  }

  /** The editor's derived state: what shows, what is checked, what blocks
   *  saving. */
  function refreshEditor(editor) {
    const { element, draft } = editor;
    const count = draft.evidence.length;
    if (editor.kind === "dimension") {
      fillText(element, "citations", fill(count === 1 ? messages().citationsOne : messages().citationsMany, { count }));
      const missing = isBlank(draft.text);
      element.querySelector('[data-rv-error="text"]').hidden = !missing;
      element.querySelector('[data-rv-action="save-edit"]').disabled = missing || editor.saving;
      return;
    }
    const changed = draft.score !== editor.base.score;
    const issues = adjust.adjustDraftIssues(draft);
    element.setAttribute("data-rv-changed", changed ? "true" : "false");
    element.setAttribute("data-rv-basis", draft.basisKind);
    checkRadio(element, "score", draft.score);
    checkRadio(element, "basis", draft.basisKind);
    const silence = element.querySelector('[data-rv-choice="basis"] input[value="not_evidenced"]');
    if (silence) silence.disabled = draft.score !== editor.scaleMinimum;
    fillText(element, "score", String(draft.score));
    element.querySelector('[data-rv-error="rationale"]').hidden = !(changed && issues.rationaleMissing);
    const canSave = !changed || adjust.canSaveAdjustDraft(draft);
    element.querySelector('[data-rv-action="save-score"]').disabled = !canSave || editor.saving;
  }

  /** Draw the kept citations from the editor's row prototype. */
  function drawRows(editor) {
    const element = editor.element;
    const list = element.querySelector("[data-rv-list]");
    const prototype = element.querySelector("[data-rv-prototype] li");
    const rows = editor.draft.evidence.map((ref, index) => {
      const row = prototype.cloneNode(true);
      row.setAttribute("data-rv-row", String(index));
      const part = (name) => row.querySelector(`[data-rv-fill="${name}"]`);
      part("location").textContent = locationOf(ref);
      part("quote").textContent = ref.quote ? fill(messages().curatedQuote, { quote: ref.quote }) : "";
      part("quote").hidden = !ref.quote;
      part("note").textContent = ref.note ? fill(messages().curatedNote, { note: ref.note }) : "";
      part("note").hidden = !ref.note;
      return row;
    });
    list.replaceChildren(...rows);
    element.querySelector("[data-rv-empty]").hidden = rows.length > 0;
  }

  function setAdding(editor, adding) {
    const form = editor.element.querySelector("[data-rv-add-form]");
    const opener = editor.element.querySelector('[data-rv-action="open-add"]');
    form.hidden = !adding;
    opener.hidden = adding;
    if (!adding) {
      const select = form.querySelector("select");
      if (select) select.selectedIndex = 0;
      for (const control of form.querySelectorAll("textarea, input")) control.value = "";
    } else {
      const select = form.querySelector("select");
      if (select) select.focus();
    }
  }

  function addCitation(editor) {
    const form = editor.element.querySelector("[data-rv-add-form]");
    const field = (ws.record.fields || [])[Number(form.querySelector("select").value)];
    if (!field) return;
    const quote = form.querySelector("textarea").value.trim();
    const note = form.querySelector("input").value.trim();
    editor.draft = {
      ...editor.draft,
      evidence: [...editor.draft.evidence, curatedRef({ sectionId: field.sectionId, fieldId: field.fieldId, quote, note })],
    };
    setAdding(editor, false);
    drawRows(editor);
    refreshEditor(editor);
    editor.element.querySelector('[data-rv-action="open-add"]').focus();
  }

  function removeCitation(editor, index) {
    editor.draft = { ...editor.draft, evidence: editor.draft.evidence.filter((_ref, at) => at !== index) };
    drawRows(editor);
    refreshEditor(editor);
    const rows = editor.element.querySelectorAll("[data-rv-list] [data-rv-action]");
    const next = rows[Math.min(index, rows.length - 1)] || editor.element.querySelector('[data-rv-action="open-add"]');
    if (next) next.focus();
  }

  function setEditorSaving(editor, saving) {
    editor.saving = saving;
    editor.element.querySelector("fieldset").disabled = saving;
    const save = editor.element.querySelector('[data-rv-action^="save-"]');
    save.textContent = saving ? messages().saving : editor.kind === "dimension" ? messages().saveEdit : messages().saveScore;
    refreshEditor(editor);
  }

  /** Save an editor's draft: a finding as edited (or accepted when nothing
   *  changed), a score as adjusted (or accepted, any rationale kept as the
   *  decision's note, when the score is unchanged). Only a stored decision
   *  closes the editor. */
  function saveEditor(editor) {
    const draft = editor.draft;
    let next;
    if (editor.kind === "dimension") {
      if (isBlank(draft.text)) return;
      const payload = {
        kind: "edited",
        finalVerdict: draft.verdict,
        finalText: draft.text,
        evidence: draft.evidence.map(curatedRef),
      };
      if (editor.initialNote !== undefined) payload.note = editor.initialNote;
      next = isUnchangedEdit(payload, editor.base) ? { kind: "accepted" } : payload;
      if (next.kind === "accepted" && payload.note !== undefined) next.note = payload.note;
    } else if (draft.score === editor.base.score) {
      const note = isBlank(draft.rationale) ? editor.existingNote : draft.rationale;
      next = note === undefined ? { kind: "accepted" } : { kind: "accepted", note };
    } else {
      if (!adjust.canSaveAdjustDraft(draft)) return;
      next = adjust.toAdjustedDisposition(draft);
    }
    setEditorSaving(editor, true);
    decide(editor.card, next, "change").then((stored) => {
      setEditorSaving(editor, false);
      if (stored) closeEditor(editor.card);
    });
  }

  /** An editor control changed: update the draft. */
  function onEditorInput(target) {
    const card = target.closest("[data-rv-card]");
    const editor = card && editorOf(card);
    if (!editor || !editor.element || !editor.element.contains(target)) return;
    const choice = target.closest("[data-rv-choice]");
    const draft = editor.draft;
    if (choice && target.type === "radio" && target.checked) {
      const kind = choice.getAttribute("data-rv-choice");
      if (kind === "verdict") editor.draft = { ...draft, verdict: target.value };
      else if (kind === "score") editor.draft = adjust.withScore(draft, Number(target.value), editor.scaleMinimum);
      else if (kind === "basis") editor.draft = adjust.withBasisKind(draft, target.value, editor.scaleMinimum);
    } else if (target.getAttribute("data-rv-field") === "text") {
      editor.draft = { ...draft, text: target.value };
    } else if (target.getAttribute("data-rv-field") === "rationale") {
      editor.draft = { ...draft, rationale: target.value };
    } else {
      return;
    }
    refreshEditor(editor);
  }

  // --- Actions --------------------------------------------------------------

  /** Actions on a card's decision, queued while one is being saved. */
  const DECISIONS = new Set(["accept", "dismiss", "change", "edit", "add-note", "retry"]);

  function act(card, action, button) {
    const key = cardKey(card);
    const { kind, item } = cardItem(card);
    if (DECISIONS.has(action) && card.hasAttribute("data-rv-saving")) {
      ws.queued[key] = action;
      return;
    }
    const editor = editorOf(card);
    switch (action) {
      case "accept":
        decide(card, { kind: "accepted" }, "change");
        break;
      case "dismiss":
        decide(card, { kind: "dismissed" }, "change");
        break;
      case "change":
        ws.notes[key] = false;
        decide(card, null, "accept");
        break;
      case "retry":
        session().retry(ws.record.id, kind, item);
        break;
      case "add-note": {
        ws.notes[key] = true;
        applyCard(card, kind, item, itemState(kind, item));
        const note = card.querySelector("[data-rv-note]");
        if (note) note.focus();
        break;
      }
      case "edit":
        openEditor(card);
        break;
      case "cancel-edit":
        closeEditor(card);
        card.querySelector('.rv-item-foot [data-rv-action="edit"]')?.focus();
        break;
      case "save-edit":
      case "save-score":
        if (editor && editor.element && !editor.saving) saveEditor(editor);
        break;
      case "open-add":
        if (editor && editor.element) setAdding(editor, true);
        break;
      case "cancel-add":
        if (editor && editor.element) {
          setAdding(editor, false);
          editor.element.querySelector('[data-rv-action="open-add"]').focus();
        }
        break;
      case "add-citation":
        if (editor && editor.element) addCitation(editor);
        break;
      case "remove-citation": {
        const row = button.closest("[data-rv-row]");
        if (editor && editor.element && row) removeCitation(editor, Number(row.getAttribute("data-rv-row")));
        break;
      }
      default:
        break;
    }
  }

  // --- Views ----------------------------------------------------------------

  function openView(view) {
    setProps(ids().view, { data: { key: view, title: ws.config.views[view] } });
  }

  function closeView() {
    setProps(ids().view, { data: null });
  }

  /** Show the opened component's view (or the hub). A component's cards
   *  are drawn from the first time its view opens. */
  function applyView(root) {
    const open = isPlainObject(ws.view) && hasOwn(ws.config.views, ws.view.key) ? ws.view.key : "";
    root.setAttribute("data-rv-showing", open);
    if (open && !ws.seen.has(open)) {
      ws.seen.add(open);
      schedule();
    }
    return open;
  }

  // --- Summary --------------------------------------------------------------

  function renderAutosave() {
    const summary = isPlainObject(ws.summary) ? ws.summary : {};
    let text = messages().autosaveIdle;
    let className = "rv-autosave";
    if (summary.saveFailed) {
      text = messages().autosaveFailed;
      className = "rv-autosave is-failed";
    } else if (summary.lastSavedISO) {
      const time = new Date(summary.lastSavedISO);
      if (!Number.isNaN(time.getTime())) {
        text = fill(messages().autosaveSaved, {
          time: time.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
        });
      }
    }
    setPropsOnce("autosave", ids().autosave, { children: text, className });
  }

  // --- Sync -----------------------------------------------------------------

  /** Create the native input each empty slot under `scope` declares. */
  function materialize(scope) {
    for (const slot of scope.querySelectorAll(".rv-slot[data-rv-input]")) {
      if (slot.firstElementChild) continue;
      let attributes;
      try {
        attributes = JSON.parse(slot.getAttribute("data-rv-input"));
      } catch (_error) {
        continue;
      }
      const input = document.createElement("input");
      for (const [name, value] of Object.entries(attributes)) {
        if (name === "class") input.className = value;
        else input.setAttribute(name, value);
      }
      slot.appendChild(input);
    }
  }

  /** A newly drawn structure: create its inputs, restore the summary, and
   *  start the cards' bookkeeping afresh. */
  function bind(body) {
    ws.body = body;
    ws.sent = {};
    ws.editors = {};
    ws.clearing = {};
    ws.notes = {};
    ws.queued = {};
    ws.focusNext = {};
    ws.seen = new Set();
    materialize(body);
    const summary = document.getElementById(ids().summary);
    if (summary) summary.value = typeof ws.record.reviewerSummary === "string" ? ws.record.reviewerSummary : "";
  }

  function schedule() {
    if (!ws || ws.frame) return;
    ws.frame = window.requestAnimationFrame(sync);
  }

  /** Bring the drawn workspace in line with the session: views, the memo
   *  panel's variant and save line, each card's local state, and a progress
   *  snapshot naming every card whose drawn state is stale. */
  function sync() {
    ws.frame = 0;
    const record = ws.record;
    const root = document.getElementById(ids().root);
    if (!root) unwatch();
    if (!record || !root) return;
    watch(root);
    const body = root.querySelector("[data-rv-shape]");
    if (!body || body.getAttribute("data-rv-shape") !== ws.shapeKey) return;
    if (ws.body !== body) bind(body);
    applyView(root);
    root.toggleAttribute("data-rv-drafting", anyPending(record));
    renderAutosave();

    const render = { dimension: {}, criterion: {} };
    const cited = new Map();
    const editing = { draw: [], clear: [] };
    for (const card of body.querySelectorAll("[data-rv-card]")) {
      const { kind, item } = cardItem(card);
      const state = itemState(kind, item);
      applyCard(card, kind, item, state);
      syncEditor(card, kind, item, editing);
      if (!ws.seen.has(ws.config.viewOfKind[kind])) continue;
      const key = keyOf(state);
      if (drawnKey(card) === key) continue;
      render[kind][item] = key;
      for (const ref of citedRefs(state)) {
        const field = snapshotField(ref);
        if (field) cited.set(`${field.sectionId}/${field.fieldId}`, field);
      }
    }
    const completion = isPlainObject(ws.completion) ? ws.completion : null;
    const progress = {
      dimensionDefs: (record.dimensionDefs || []).map(({ id, label, description }) => ({ id, label, description })),
      dimensions: record.dimensions,
      mca: record.mca ? { matrix: record.mca.matrix, criteria: record.mca.criteria } : null,
      memo: completion ? { ready: completion.ready === true, reasons: completion.reasons || [] } : null,
      summary: ws.seen.has("scores"),
      render,
    };
    const serial = JSON.stringify(progress);
    if (ws.sent.progress !== serial) {
      ws.sent.progress = serial;
      setProps(ids().progress, { data: { ...progress, fields: [...cited.values()] } });
    }
    requestEditors(editing);
  }

  /** Bring a card's editor slot in line with its editor: bind a drawn form,
   *  or note in `editing` that one is to be drawn or cleared. A closed
   *  editor's form is cleared before the editor is drawn again. */
  function syncEditor(card, kind, item, editing) {
    const key = cardKey(card);
    const editor = ws.editors[key];
    const drawn = card.querySelector(".rv-card-edit-slot > [data-rv-editor]");
    if (!drawn) delete ws.clearing[key];
    if (drawn && (!editor || ws.clearing[key])) {
      editing.clear.push({ kind, item });
      return;
    }
    if (!editor) return;
    if (editor.element && !editor.element.isConnected) editor.element = null;
    if (!drawn) {
      const entry = { kind, item };
      if (kind === "dimension") {
        entry.definition = (ws.record.dimensionDefs || []).find((d) => d.id === item);
      } else {
        entry.criterion = ws.record.mca.matrix.criteria.find((c) => c.id === item);
        entry.state = editor.state;
      }
      editing.draw.push(entry);
    } else if (!editor.element) {
      bindEditor(editor, drawn);
    }
  }

  /** Ask for the editors to draw and clear, with the field snapshot their
   *  pickers offer (and the text of the fields a score's draft cites). Every
   *  request names all of them, so one Dash drops for a newer one loses
   *  nothing. */
  function requestEditors(editing) {
    const cites = new Set();
    for (const entry of editing.draw) {
      if (entry.state) for (const ref of citedRefs(entry.state)) cites.add(`${ref.sectionId}/${ref.fieldId}`);
    }
    const fields = (ws.record.fields || []).map((field) => {
      const { sectionId, fieldId, sectionLabel, fieldLabel, serializedText } = field;
      const entry = { sectionId, fieldId, sectionLabel, fieldLabel };
      if (cites.has(`${sectionId}/${fieldId}`)) entry.serializedText = serializedText;
      return entry;
    });
    const request = {
      draw: editing.draw,
      clear: editing.clear,
      scale: ws.record.mca ? ws.record.mca.matrix.scale : [],
      fields,
    };
    const serial = JSON.stringify(request);
    if (ws.sent.editing === serial) return;
    ws.sent.editing = serial;
    if (editing.draw.length || editing.clear.length) setProps(ids().editing, { data: request });
  }

  // --- Listeners ------------------------------------------------------------

  const inWorkspace = (target) => !!(ws && ws.body && target instanceof Element && ws.body.contains(target));

  function onClick(event) {
    const target = event.target;
    if (!inWorkspace(target)) return;
    const open = target.closest("[data-rv-open]");
    if (open) {
      openView(open.getAttribute("data-rv-open"));
      return;
    }
    if (target.closest("[data-rv-close]")) {
      closeView();
      return;
    }
    const button = target.closest("[data-rv-action]");
    const card = button && button.closest("[data-rv-card]");
    if (card && !button.disabled) act(card, button.getAttribute("data-rv-action"), button);
  }

  function onInput(event) {
    const target = event.target;
    if (!inWorkspace(target)) return;
    if (target.id === ids().summary) {
      session().changeSummary(ws.record.id, target.value);
      return;
    }
    onEditorInput(target);
  }

  function onFocusOut(event) {
    const target = event.target;
    if (!inWorkspace(target) || !target.hasAttribute("data-rv-note")) return;
    const card = target.closest("[data-rv-card]");
    if (card) saveNote(card, target.value);
  }

  const LISTENERS = [
    ["click", onClick],
    ["input", onInput],
    ["change", onInput],
    ["focusout", onFocusOut],
  ];

  /** Listen to the workspace root, and redraw what is stale whenever its
   *  content changes; a root left behind by navigation is released. */
  function watch(root) {
    if (ws.root === root) return;
    unwatch();
    ws.root = root;
    for (const [type, handler] of LISTENERS) root.addEventListener(type, handler);
    ws.observer = new MutationObserver(schedule);
    ws.observer.observe(root, { childList: true, subtree: true });
  }

  function unwatch() {
    if (!ws.root) return;
    for (const [type, handler] of LISTENERS) ws.root.removeEventListener(type, handler);
    ws.observer.disconnect();
    ws.root = null;
    ws.observer = null;
    ws.body = null;
  }

  /** In-app navigation may have taken the workspace off the page. */
  function onNavigate() {
    setTimeout(() => {
      if (ws.root && !ws.root.isConnected) unwatch();
    });
  }

  function start(config) {
    ws = {
      config,
      record: null,
      summary: null,
      completion: null,
      view: null,
      shapeKey: null,
      root: null,
      observer: null,
      body: null,
      frame: 0,
      sent: {},
      editors: {},
      clearing: {},
      notes: {},
      queued: {},
      focusNext: {},
      seen: new Set(),
    };
    window.addEventListener("_dashprivate_pushstate", onNavigate);
    window.addEventListener("popstate", onNavigate);
  }

  // --- Entry points ---------------------------------------------------------

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.pcnReviewUi = {
    /** The session's record, summary state or completion changed: publish
     *  the record's structure unless this page's shape store holds it. */
    sessionChanged: function (record, summary, completion, config, published) {
      if (!isPlainObject(config)) return dash().no_update;
      if (!ws) start(config);
      ws.summary = summary;
      ws.completion = completion;
      ws.record = isPlainObject(record) ? record : null;
      schedule();
      if (!ws.record) return dash().no_update;
      const shape = shapeOf(ws.record);
      ws.shapeKey = shape.key;
      return isPlainObject(published) && published.key === shape.key ? dash().no_update : shape;
    },

    /** The open view changed: show it (or the hub) and land at its top. */
    viewChanged: function (view, config) {
      if (!isPlainObject(config)) return;
      if (!ws) start(config);
      const previous = isPlainObject(ws.view) ? ws.view.key : "";
      ws.view = view;
      const root = document.getElementById(ids().root);
      if (!root) return;
      const open = applyView(root);
      if (open === previous) return;
      window.scrollTo({ top: 0 });
      const focus = open
        ? root.querySelector(`.rv-view-${open} [data-rv-close]`)
        : root.querySelector(`[data-rv-open="${previous}"]`);
      if (focus) focus.focus({ preventScroll: true });
    },
  };

  /** Hooks for the browser tests, present only on a page opened with
   *  `window.pcnTestHooks` set: `adjust` holds the adjustment draft's
   *  transitions, `editor(kind, item)` a copy of an open editor's draft (or
   *  null). */
  if (window.pcnTestHooks === true) {
    window.pcnReviewUi = {
      adjust,
      editor: (kind, item) => {
        const editor = ws && ws.editors[`${kind}:${item}`];
        return editor ? clone(editor.draft) : null;
      },
    };
  }
})();
