/* pcnReview: review sessions in the browser (see pcn_clone/app/review).
 *
 * Submit: the button is enabled once the proposer's workspace is hydrated
 * (a draft never restored leaves it disabled, with the reason as its
 * description); a click snapshots the answers into the request store, the
 * server returns the intake snapshot, and the review is created from it
 * (every item pending at generation 0) and opened. No snapshot within the
 * configured time gives up, and a snapshot arriving after that is ignored.
 *
 * The run talks to the server over two lists in the app shell: the outbox,
 * which this script rewrites whole with the run requests the server has not
 * yet acknowledged, and the inbox, to which the server only appends and
 * which this script reads past a cursor. Dash may
 * fold several writes to one store into a single callback run; reading the
 * whole list loses none of them.
 *
 * Mounting a review page reads the record and launches every pending item
 * not already in flight in this page session (a revisited page waits for
 * the run in flight instead of launching again; a reload starts with none
 * in flight, so pending items restart). Launching moves the item to pending
 * at the next generation in the stored record (`pcnReviews.launchItem`) and
 * queues the request. Each result is merged with `pcnReviews.writeResult`:
 * only into an item still pending at the launch's generation, so a late or
 * repeated result never overwrites a result or a decision; it is dropped
 * and announced. When a result cannot be stored, the stored record is
 * re-read before anything else is written, and an item is never left
 * pending on screen after a failure: a failure that cannot be stored either
 * is shown until the next reload restarts the item. A run that ends with
 * items unanswered, or whose messages (heartbeats included) stop for
 * `staleHeartbeats` heartbeat intervals because its connection closed,
 * settles those items as a retryable transport error.
 *
 * Every change to a review dispatches `pcn:review-changed` on window with
 * {reviewId}; the open review page's stores are refreshed (see
 * pcn_clone/app/review/__init__.py for the contract) and an open
 * Assessment list re-reads its sessions.
 *
 * Ids, messages, toast styles and timings come from the configuration in
 * the shell's config store; the store itself is `window.pcnReviews`
 * (review-store.js).
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const HYDRATION_POLL_MS = 50;
  const HYDRATION_TIMEOUT_MS = 15000;

  const reviews = () => window.pcnReviews;
  const store = () => window.pcnStore;
  const dash = () => window.dash_clientside;
  const noUpdate = () => window.dash_clientside.no_update;
  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const isNonEmptyString = (value) => typeof value === "string" && value.length > 0;
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const errorText = (error) => (error && error.message ? error.message : undefined);
  const itemKey = (kind, id) => `${kind}/${id}`;

  /** The configuration (the shell's config store), kept from the first
   *  callback that reads it. */
  let config = null;
  const useConfig = (value) => {
    if (isPlainObject(value)) config = value;
    return config;
  };
  const ids = () => config.ids;
  const messages = () => config.messages;

  /** Items launched in this page session and not yet settled:
   *  reviewId -> Map(itemKey -> generation). */
  const inFlight = new Map();
  /** Run requests not yet settled: nonce -> {reviewId, open: Map(itemKey ->
   *  generation), sentAt, lastSeen}. */
  const launches = new Map();
  /** The requests the server has not acknowledged, as the outbox holds them. */
  let outbox = [];
  /** How much of the inbox has been read. */
  let inboxCursor = 0;
  let sweepTimer = null;
  /** Failures shown but not stored: reviewId -> Map(itemKey -> state). */
  const overlays = new Map();
  /** The review page in view, {reviewId}, or null. Only it is published
   *  to: Dash refuses to set props on components outside the layout. */
  let mounted = null;
  /** True while the Assessment list is in view. */
  let listOpen = false;
  let listTick = 0;
  /** The mounted review's summary editor: {reviewId, text, stored, pending,
   *  timer, lastSavedISO, saveFailed}. */
  let summary = null;
  /** The Submit request waiting for its snapshot: {nonce, timer}, or null. */
  let submitting = null;
  const handledSnapshots = new Set();

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, (match, name) =>
      hasOwn(values, name) ? String(values[name]) : match,
    );
  }

  const countSentence = (pair, n) => fill(pair[n === 1 ? 0 : 1], { n });

  /** A review's page as an absolute URL on the current address: the same
   *  path with `?page=review&review_id=<id>` (see pcn_clone.app.routing). */
  function reviewHref(reviewId) {
    const url = new URL(window.location.href);
    url.search = new URLSearchParams({ page: "review", review_id: reviewId }).toString();
    url.hash = "";
    return url.href;
  }

  function setProps(id, props) {
    const set = dash() && dash().set_props;
    if (typeof set === "function") set(id, props);
  }

  // --- Toasts ---------------------------------------------------------------

  /** A toast shaped as `pcn_clone.app.notify.toast` builds it. */
  function notify(kind, message, description) {
    if (!config) return;
    const style = config.toastKinds[kind];
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
    setProps(ids().toasts, { sendNotifications: [entry] });
  }

  /** A notice about one review: on its page as is, elsewhere headed with
   *  the review's title. */
  function notifyAbout(reviewId, kind, text, detail) {
    if (mounted && mounted.reviewId === reviewId) {
      notify(kind, text, detail);
      return;
    }
    const current = reviews().getReview(reviewId);
    const title = current.status === "ok" ? current.review.projectTitle : reviewId;
    notify(kind, fill(messages().inReview, { title }), detail ? `${text} ${detail}` : text);
  }

  /** The inputs that fired the running callback with a value. */
  function firedId() {
    const context = dash().callback_context;
    const entry = ((context && context.triggered) || []).find((candidate) => candidate.value);
    if (!entry) return null;
    const rawId = entry.prop_id.slice(0, entry.prop_id.lastIndexOf("."));
    try {
      return JSON.parse(rawId);
    } catch (_error) {
      return rawId;
    }
  }

  // --- Session registries ---------------------------------------------------

  function flying(reviewId) {
    let map = inFlight.get(reviewId);
    if (!map) {
      map = new Map();
      inFlight.set(reviewId, map);
    }
    return map;
  }

  /** Take an item out of flight, unless a newer launch replaced it. */
  function settle(reviewId, kind, itemId, generation) {
    const map = inFlight.get(reviewId);
    if (!map) return;
    if (map.get(itemKey(kind, itemId)) === generation) map.delete(itemKey(kind, itemId));
    if (map.size === 0) inFlight.delete(reviewId);
  }

  function setOverlay(reviewId, kind, itemId, state) {
    let map = overlays.get(reviewId);
    if (!map) {
      map = new Map();
      overlays.set(reviewId, map);
    }
    map.set(itemKey(kind, itemId), state);
  }

  function clearOverlay(reviewId, kind, itemId) {
    const map = overlays.get(reviewId);
    if (map) map.delete(itemKey(kind, itemId));
  }

  function readItem(reviewId, kind, itemId) {
    const current = reviews().getReview(reviewId);
    return current.status === "ok" ? reviews().itemState(current.review, kind, itemId) : undefined;
  }

  function labelOf(reviewId, kind, itemId) {
    const current = reviews().getReview(reviewId);
    if (current.status !== "ok") return itemId;
    const item = reviews().items(current.review).find((entry) => entry.kind === kind && entry.id === itemId);
    return item ? item.label : itemId;
  }

  // --- Completion and status ------------------------------------------------

  function tally(states) {
    const result = { pending: 0, retryable: 0, movedOn: 0, invalidResult: 0, undecided: 0 };
    for (const state of states) {
      if (state.status === "pending") result.pending += 1;
      else if (state.status === "ok") result.undecided += state.disposition === undefined ? 1 : 0;
      else if (state.error.kind === "retryable") result.retryable += 1;
      else if (state.error.code === "invalid_result") result.invalidResult += 1;
      else result.movedOn += 1;
    }
    return result;
  }

  /** Whether the review is complete and, in fixed order, what blocks it.
   *  `summaryInput` is {text, persisted, saveFailed}. */
  function completion(record, summaryInput) {
    const sentences = messages().reasons;
    const list = reviews().items(record);
    const dims = tally(list.filter((item) => item.kind === "dimension").map((item) => item.state));
    const crits = tally(list.filter((item) => item.kind === "criterion").map((item) => item.state));
    const slots = [
      [dims.pending, sentences.dimensionsPending],
      [crits.pending, sentences.criteriaPending],
      [dims.retryable, sentences.dimensionsRetryable],
      [crits.retryable, sentences.criteriaRetryable],
      [dims.movedOn, sentences.dimensionsMovedOn],
      [crits.movedOn, sentences.criteriaMovedOn],
      [dims.invalidResult, sentences.dimensionsInvalid],
      [crits.invalidResult, sentences.criteriaInvalid],
      [dims.undecided, sentences.dimensionsUndecided],
      [crits.undecided, sentences.criteriaUndecided],
    ];
    const reasons = slots.filter(([n]) => n > 0).map(([n, pair]) => countSentence(pair, n));
    if (summaryInput.text.trim().length === 0) reasons.push(sentences.summaryBlank);
    else if (!summaryInput.persisted) {
      reasons.push(summaryInput.saveFailed ? sentences.summarySaveFailed : sentences.summarySaving);
    }
    return { ready: reasons.length === 0, reasons };
  }

  /** The context bar's line: drafting progress while anything is pending,
   *  otherwise the first blocking reason or the ready line. */
  function status(record, summaryInput) {
    const states = reviews().items(record).map((item) => item.state);
    const pending = states.filter((state) => state.status === "pending").length;
    if (pending > 0) {
      return fill(messages().drafting, { total: states.length, returned: states.length - pending });
    }
    return completion(record, summaryInput).reasons[0] || messages().ready;
  }

  // --- Publishing -----------------------------------------------------------

  function summaryInputFor(reviewId, record) {
    if (summary && summary.reviewId === reviewId) {
      return {
        text: summary.text,
        persisted: summary.text === summary.stored,
        saveFailed: summary.saveFailed,
      };
    }
    return { text: record.reviewerSummary, persisted: true, saveFailed: false };
  }

  /** The record as the page shows it: unstored failures over their items
   *  and the summary as typed. */
  function viewOf(reviewId, stored) {
    const record = clone(stored);
    const map = overlays.get(reviewId);
    for (const [key, state] of map ? map.entries() : []) {
      const slash = key.indexOf("/");
      const kind = key.slice(0, slash);
      const itemId = key.slice(slash + 1);
      const states = kind === "dimension" ? record.dimensions : record.mca && record.mca.criteria;
      if (states && hasOwn(states, itemId) && states[itemId].status === "pending") states[itemId] = state;
    }
    if (summary && summary.reviewId === reviewId) record.reviewerSummary = summary.text;
    return record;
  }

  function sessionState(reviewId) {
    const current = reviews().getReview(reviewId);
    if (current.status !== "ok") return null;
    const record = viewOf(reviewId, current.review);
    const input = summaryInputFor(reviewId, record);
    const done = completion(record, input);
    return {
      record,
      summary: {
        reviewId,
        persisted: input.persisted,
        saveFailed: input.saveFailed,
        lastSavedISO: summary && summary.reviewId === reviewId ? summary.lastSavedISO : null,
      },
      completion: {
        ready: done.ready,
        reasons: done.reasons,
        status: status(record, input),
        drafting: reviews()
          .items(record)
          .some((item) => item.state.status === "pending"),
      },
    };
  }

  /** Set the stores derived from the record. */
  function publishDerived(state) {
    setProps(ids().summary, { data: state.summary });
    setProps(ids().completion, { data: state.completion });
    setProps(ids().status, { children: state.completion.status, title: state.completion.status });
  }

  function announce(reviewId) {
    setTimeout(() => window.dispatchEvent(new CustomEvent("pcn:review-changed", { detail: { reviewId } })));
  }

  /** A review changed: refresh its page if it is in view and the list if
   *  that is, then announce it. */
  function changed(reviewId) {
    if (mounted && mounted.reviewId === reviewId) {
      const state = sessionState(reviewId);
      if (state) {
        setProps(ids().record, { data: state.record });
        publishDerived(state);
      }
    }
    if (listOpen) setProps(ids().listRefresh, { data: (listTick += 1) });
    announce(reviewId);
  }

  // --- Launching ------------------------------------------------------------

  /** The error state for a write that failed: an invariant violation is an
   *  application defect (terminal), anything else a device failure a retry
   *  may fix. */
  function persistFailureState(generation, error, storageMessage) {
    return error instanceof reviews().ReviewInvariantError
      ? {
          status: "error",
          generation,
          errorMessage: messages().invalidResult,
          error: { kind: "terminal", code: "invalid_result" },
        }
      : {
          status: "error",
          generation,
          errorMessage: storageMessage || messages().resultNotSaved,
          error: { kind: "retryable", code: "storage_error" },
        };
  }

  function announceDropped(reviewId, kind, label, reason) {
    const text =
      reason === "stale"
        ? fill(messages().superseded[kind], { label })
        : fill(messages().arrivedLate[kind], { label, state: messages().sessionState[reason] });
    notifyAbout(reviewId, "info", text);
  }

  /** Move one item to pending at the next generation, unless this session
   *  already has it in flight. Returns {kind, id, generation} when it is
   *  launched, otherwise null (a failure is shown on the item). */
  function startItem(reviewId, item, currentGeneration) {
    if (flying(reviewId).has(itemKey(item.kind, item.id))) return null;
    let written;
    try {
      written = reviews().launchItem(reviewId, item.kind, item.id, currentGeneration);
    } catch (error) {
      notifyAbout(
        reviewId,
        "error",
        fill(messages().saveResultFailed[item.kind], { label: item.label }),
        errorText(error),
      );
      let base = currentGeneration;
      try {
        const stored = readItem(reviewId, item.kind, item.id);
        if (stored) base = stored.generation;
      } catch (_readError) {
        // Keep the generation the launch was based on.
      }
      setOverlay(
        reviewId,
        item.kind,
        item.id,
        persistFailureState(base, error, messages().startFailure[item.kind]),
      );
      return null;
    }
    if (!written.applied) {
      announceDropped(reviewId, item.kind, item.label, written.reason);
      return null;
    }
    clearOverlay(reviewId, item.kind, item.id);
    flying(reviewId).set(itemKey(item.kind, item.id), currentGeneration + 1);
    return { kind: item.kind, id: item.id, generation: currentGeneration + 1 };
  }

  /** The pins every request of this record carries. */
  function requestOf(record) {
    const request = {
      templateId: record.templateId,
      templateVersion: record.templateVersion,
      assessmentSetId: record.assessmentSetId,
      assessmentSetVersion: record.assessmentSetVersion,
      model: record.model,
      assessmentInputDigest: record.assessmentInputDigest,
      submission: record.submission,
    };
    if (record.mca) {
      request.mcaSetId = record.mca.setId;
      request.mcaSetVersion = record.mca.setVersion;
    }
    return request;
  }

  /** Queue one run request for `items` (already pending at their
   *  generations) and write the outbox. */
  function launch(record, items) {
    const nonce = store().newId();
    launches.set(nonce, {
      reviewId: record.id,
      open: new Map(items.map((item) => [itemKey(item.kind, item.id), item.generation])),
      sentAt: Date.now(),
      lastSeen: null,
    });
    outbox = outbox.concat([{ reviewId: record.id, nonce, items, request: requestOf(record) }]);
    setProps(ids().launch, { data: outbox });
    if (sweepTimer === null) sweepTimer = setInterval(sweep, config.heartbeatMs);
  }

  // --- Merging --------------------------------------------------------------

  function isRunError(value) {
    if (!isPlainObject(value) || Object.keys(value).length !== 2) return false;
    if (value.kind === "retryable") return reviews().RETRYABLE_CODES.includes(value.code);
    return value.kind === "terminal" && reviews().TERMINAL_CODES.includes(value.code);
  }

  function transportState(kind, generation) {
    return {
      status: "error",
      generation,
      errorMessage: messages().transportFailure[kind],
      error: { kind: "retryable", code: "transport_error" },
    };
  }

  /** The item state a delivered response stands for; an unrecognisable
   *  response is a transport failure. */
  function stateFromResponse(kind, generation, response) {
    if (isPlainObject(response) && response.ok === true && isPlainObject(response.finding)) {
      const state = { status: "ok", generation };
      state[kind === "dimension" ? "finding" : "scoreFinding"] = response.finding;
      return state;
    }
    if (
      isPlainObject(response) &&
      response.ok === false &&
      isNonEmptyString(response.errorMessage) &&
      isRunError(response.error)
    ) {
      return { status: "error", generation, errorMessage: response.errorMessage, error: response.error };
    }
    return transportState(kind, generation);
  }

  /** Store an item's completion into its launch's pending generation. */
  function persistCompletion(reviewId, kind, itemId, generation, next) {
    const label = labelOf(reviewId, kind, itemId);
    let written;
    try {
      written = reviews().writeResult(reviewId, kind, itemId, generation, next);
    } catch (error) {
      notifyAbout(reviewId, "error", fill(messages().saveResultFailed[kind], { label }), errorText(error));
      let stored;
      try {
        stored = readItem(reviewId, kind, itemId);
      } catch (_readError) {
        stored = undefined;
      }
      if (stored && stored.generation === generation && stored.status === next.status) {
        try {
          reviews().writeItem(reviewId, kind, itemId, generation, stored);
        } catch (_repairError) {
          // The listing derives its entries from payloads.
        }
        clearOverlay(reviewId, kind, itemId);
        changed(reviewId);
        return;
      }
      const fallback = persistFailureState(generation, error);
      try {
        written = reviews().writeResult(reviewId, kind, itemId, generation, fallback);
      } catch (_fallbackError) {
        written = undefined;
      }
      if (written === undefined) setOverlay(reviewId, kind, itemId, fallback);
      else if (!written.applied) announceDropped(reviewId, kind, label, written.reason);
      else clearOverlay(reviewId, kind, itemId);
      changed(reviewId);
      return;
    }
    if (written.applied) clearOverlay(reviewId, kind, itemId);
    else announceDropped(reviewId, kind, label, written.reason);
    changed(reviewId);
  }

  /** Settle the items a run left unanswered as transport failures and
   *  forget the run. */
  function finish(nonce) {
    const run = launches.get(nonce);
    launches.delete(nonce);
    outbox = outbox.filter((request) => request.nonce !== nonce);
    if (launches.size === 0 && sweepTimer !== null) {
      clearInterval(sweepTimer);
      sweepTimer = null;
    }
    if (!run) return;
    for (const [key, generation] of run.open) {
      const slash = key.indexOf("/");
      const kind = key.slice(0, slash);
      const itemId = key.slice(slash + 1);
      settle(run.reviewId, kind, itemId, generation);
      persistCompletion(run.reviewId, kind, itemId, generation, transportState(kind, generation));
    }
  }

  /** Fail the runs that have gone silent: no message for `staleHeartbeats`
   *  heartbeat intervals means their connection is gone. */
  function sweep() {
    const limit = config.staleHeartbeats * config.heartbeatMs;
    const now = Date.now();
    for (const [nonce, run] of Array.from(launches)) {
      if (now - (run.lastSeen === null ? run.sentAt : run.lastSeen) > limit) finish(nonce);
    }
  }

  function receiveResult(message) {
    const { reviewId, kind, itemId, generation } = message;
    if (!reviews().KINDS.includes(kind) || !isNonEmptyString(itemId) || !Number.isInteger(generation)) return;
    const run = launches.get(message.nonce);
    if (run && run.open.get(itemKey(kind, itemId)) === generation) run.open.delete(itemKey(kind, itemId));
    settle(reviewId, kind, itemId, generation);
    persistCompletion(reviewId, kind, itemId, generation, stateFromResponse(kind, generation, message.response));
  }

  function receiveOne(message) {
    if (!isPlainObject(message) || !isNonEmptyString(message.reviewId) || !isNonEmptyString(message.nonce)) {
      return;
    }
    const run = launches.get(message.nonce);
    if (run) run.lastSeen = Date.now();
    if (message.type === "started") outbox = outbox.filter((request) => request.nonce !== message.nonce);
    else if (message.type === "result") receiveResult(message);
    else if (message.type === "done") finish(message.nonce);
  }

  // --- The reviewer summary -------------------------------------------------

  function summaryFingerprint() {
    if (!summary) return "";
    return [summary.text.trim().length === 0, summary.text === summary.stored, summary.saveFailed].join();
  }

  function performSave() {
    if (!summary) return;
    summary.timer = null;
    const text = summary.pending;
    if (text === null) return;
    summary.pending = null;
    try {
      reviews().saveSummary(summary.reviewId, text);
      summary.stored = text;
      summary.lastSavedISO = store().nowISO();
      summary.saveFailed = false;
    } catch (_error) {
      summary.saveFailed = true;
    }
    changed(summary.reviewId);
  }

  /** Save a pending summary now. */
  function flushSummary() {
    if (summary && summary.timer !== null) {
      clearTimeout(summary.timer);
      performSave();
    }
  }

  /** The summary as typed; saved after the configured delay. */
  function changeSummary(reviewId, text) {
    if (!summary || summary.reviewId !== reviewId || !config) return;
    const before = summaryFingerprint();
    summary.text = String(text);
    summary.pending = summary.text;
    if (summary.timer !== null) clearTimeout(summary.timer);
    summary.timer = setTimeout(performSave, config.summarySaveDelayMs);
    if (summaryFingerprint() !== before) changed(reviewId);
  }

  function summaryState(reviewId) {
    if (!summary || summary.reviewId !== reviewId) return null;
    return {
      reviewId,
      text: summary.text,
      persisted: summary.text === summary.stored,
      saveFailed: summary.saveFailed,
      lastSavedISO: summary.lastSavedISO,
    };
  }

  /** Navigating in the app leaves the page: save the summary now and stop
   *  publishing, as the page's stores are leaving the layout. */
  function leavePage() {
    flushSummary();
    mounted = null;
    listOpen = false;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushSummary();
  });
  window.addEventListener("pagehide", flushSummary);
  window.addEventListener("_dashprivate_pushstate", leavePage);
  window.addEventListener("popstate", leavePage);

  // --- Decisions and retries ------------------------------------------------

  /** Record (or, with null, clear) the reviewer's decision on an ok item at
   *  `generation`; true when the decision is stored. */
  function decide(reviewId, kind, itemId, generation, disposition) {
    const label = labelOf(reviewId, kind, itemId);
    const current = reviews().getReview(reviewId);
    if (current.status !== "ok") {
      notify("info", fill(messages().decisionNotSaved, { label, state: messages().sessionState[current.status] }));
      return false;
    }
    const stored = reviews().itemState(current.review, kind, itemId);
    if (!stored || stored.status !== "ok" || stored.generation !== generation) {
      notify("info", fill(messages().decisionMovedOn, { label }));
      changed(reviewId);
      return false;
    }
    const resultKey = kind === "dimension" ? "finding" : "scoreFinding";
    const next = { status: "ok", generation: generation + 1, [resultKey]: stored[resultKey] };
    if (disposition) next.disposition = disposition;
    let written;
    try {
      written = reviews().writeItem(reviewId, kind, itemId, generation, next);
    } catch (error) {
      try {
        const after = readItem(reviewId, kind, itemId);
        if (after && after.generation === generation + 1) {
          changed(reviewId);
          return true;
        }
      } catch (_readError) {
        // Fall through to the failure.
      }
      notify(
        "error",
        fill(messages().decisionSaveFailed, { label }),
        error instanceof reviews().ReviewInvariantError ? messages().decisionInvalid : messages().decisionStorage,
      );
      return false;
    }
    if (written.applied) {
      changed(reviewId);
      return true;
    }
    notify(
      "info",
      written.reason === "stale"
        ? fill(messages().decisionMovedOn, { label })
        : fill(messages().decisionNotSaved, { label, state: messages().sessionState[written.reason] }),
    );
    if (written.reason === "stale") changed(reviewId);
    return false;
  }

  /** Launch one item again after a retryable error; true when launched. */
  function retry(reviewId, kind, itemId) {
    const current = reviews().getReview(reviewId);
    if (current.status !== "ok" || !config) return false;
    const record = current.review;
    const item = reviews().items(record).find((entry) => entry.kind === kind && entry.id === itemId);
    if (!item) return false;
    const map = overlays.get(reviewId);
    const shown = (map && map.get(itemKey(kind, itemId))) || item.state;
    if (!reviews().isRetryableErrorState(shown)) return false;
    const launched = startItem(reviewId, item, shown.generation);
    if (launched) launch(record, [launched]);
    changed(reviewId);
    return !!launched;
  }

  /** True when the review has no run unsettled and no summary waiting to be
   *  saved. */
  function idle(reviewId) {
    const running = Array.from(launches.values()).some((run) => run.reviewId === reviewId);
    const saving = !!summary && summary.reviewId === reviewId && summary.timer !== null;
    return !running && !saving;
  }

  // --- Submit ---------------------------------------------------------------

  /** Give up on a Submit whose snapshot never came: ignore it if it comes
   *  later, and enable the button again. */
  function abandonSubmit(nonce) {
    if (!submitting || submitting.nonce !== nonce) return;
    submitting = null;
    handledSnapshots.add(nonce);
    notify("error", messages().submitFailed, messages().submitNoAnswer);
    if (document.getElementById(ids().submit)) {
      setProps(ids().submit, { "aria-disabled": null, "aria-busy": "false" });
    }
  }

  // --- The gate -------------------------------------------------------------

  /** "MM.DD.YYYY, HH:MM" in this browser's time; an em dash if unparseable. */
  function formatDateTime(iso) {
    const time = Date.parse(iso);
    if (Number.isNaN(time)) return "—";
    const date = new Date(time);
    const pad = (n) => String(n).padStart(2, "0");
    return (
      `${pad(date.getMonth() + 1)}.${pad(date.getDate())}.${date.getFullYear()}, ` +
      `${pad(date.getHours())}:${pad(date.getMinutes())}`
    );
  }

  /** The review gate's lookup: the record's identity and provenance, an
   *  unreadable answer, or null. */
  window.pcnGate.lookups.review = (id) => {
    const result = reviews().getReview(id);
    if (result.status === "missing") return null;
    if (result.status === "unreadable") return window.pcnGate.unreadable(result.message);
    const record = result.review;
    const projection = {
      id: record.id,
      projectTitle: record.projectTitle,
      templateId: record.templateId,
      templateLabel: record.templateLabel,
      templateVersion: record.templateVersion,
      sourceProjectTemplateVersion: record.sourceProjectTemplateVersion,
      assessmentSetId: record.assessmentSetId,
      assessmentSetVersion: record.assessmentSetVersion,
      model: record.model,
      submitted: formatDateTime(record.createdISO),
    };
    if (record.mca) {
      projection.mcaSetId = record.mca.setId;
      projection.mcaSetVersion = record.mca.setVersion;
    }
    return projection;
  };

  // --- Clientside callbacks -------------------------------------------------

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.pcnReview = {
    /** Open the session for the review page in view: launch its pending
     *  items, publish its state and return its record. */
    mount: function (session, configValue) {
      if (!useConfig(configValue) || !isPlainObject(session) || !isNonEmptyString(session.reviewId)) {
        return noUpdate();
      }
      const reviewId = session.reviewId;
      if (summary && summary.reviewId !== reviewId) flushSummary();
      mounted = { reviewId };
      const current = reviews().getReview(reviewId);
      if (current.status !== "ok") return noUpdate();
      const record = current.review;
      if (!summary || summary.reviewId !== reviewId) {
        summary = {
          reviewId,
          text: record.reviewerSummary,
          stored: record.reviewerSummary,
          pending: null,
          timer: null,
          lastSavedISO: null,
          saveFailed: false,
        };
      }
      const launched = [];
      for (const item of reviews().items(record)) {
        if (item.state.status !== "pending") continue;
        const started = startItem(reviewId, item, item.state.generation);
        if (started) launched.push(started);
      }
      if (launched.length) launch(record, launched);
      const state = sessionState(reviewId);
      if (!state) return noUpdate();
      publishDerived(state);
      announce(reviewId);
      return state.record;
    },

    /** Read the inbox past the cursor. */
    receive: function (messagesList, configValue) {
      if (!useConfig(configValue) || !Array.isArray(messagesList)) return;
      if (messagesList.length < inboxCursor) inboxCursor = 0;
      const fresh = messagesList.slice(inboxCursor);
      inboxCursor = messagesList.length;
      for (const message of fresh) receiveOne(message);
    },

    /** The project crumb closes the open component. */
    backToHub: function (clicks) {
      return clicks ? null : noUpdate();
    },

    /** The breadcrumb for the open component, or the hub. Returns [title
     *  hidden, back hidden, tail hidden, tail text]. */
    crumbs: function (part) {
      const open = isPlainObject(part);
      return [open, !open, !open, open ? String(part.title || "") : ""];
    },

    /** Submit becomes usable once the workspace is hydrated; if it never
     *  is, the button's description and the autosave line say why. Returns
     *  [aria-disabled, hint, autosave line]. */
    enableSubmit: function (project, configValue) {
      if (submitting) clearTimeout(submitting.timer);
      submitting = null;
      if (!useConfig(configValue) || !isPlainObject(project)) return [noUpdate(), noUpdate(), noUpdate()];
      return new Promise((resolve) => {
        const started = Date.now();
        const poll = () => {
          if (window.pcnForm && window.pcnForm.hydrated()) resolve([null, "", noUpdate()]);
          else if (Date.now() - started < HYDRATION_TIMEOUT_MS) setTimeout(poll, HYDRATION_POLL_MS);
          else resolve(["true", messages().draftNotRestored, messages().draftNotRestored]);
        };
        poll();
      });
    },

    /** A Submit click: snapshot the answers and the project now. Returns
     *  [request, aria-disabled, aria-busy]. */
    startSubmit: function (clicks, project, configValue) {
      const unchanged = [noUpdate(), noUpdate(), noUpdate()];
      if (!useConfig(configValue) || !clicks || submitting || !isPlainObject(project)) return unchanged;
      if (!window.pcnForm || !window.pcnForm.hydrated()) return unchanged;
      const stored = store().getProject(project.id);
      if (!stored) {
        notify("error", messages().submitFailed, messages().projectGone);
        return unchanged;
      }
      const nonce = store().newId();
      submitting = { nonce, timer: setTimeout(() => abandonSubmit(nonce), config.submitTimeoutMs) };
      return [
        {
          nonce,
          projectId: stored.id,
          projectTitle: stored.title,
          sourceProjectTemplateVersion: stored.templateVersion,
          values: window.pcnForm.snapshot(),
        },
        "true",
        "true",
      ];
    },

    /** The intake snapshot arrived: create the review and open it. Returns
     *  [nav href, aria-disabled, aria-busy]. */
    finishSubmit: function (snapshot, request, configValue) {
      const unchanged = [noUpdate(), noUpdate(), noUpdate()];
      if (!useConfig(configValue) || !isPlainObject(snapshot) || !isPlainObject(request)) return unchanged;
      if (snapshot.nonce !== request.nonce || handledSnapshots.has(snapshot.nonce)) return unchanged;
      handledSnapshots.add(snapshot.nonce);
      if (submitting && submitting.nonce === snapshot.nonce) clearTimeout(submitting.timer);
      try {
        if (!snapshot.ok) throw new Error(snapshot.errorMessage);
        const intake = snapshot.intake;
        const record = reviews().createReview({
          projectId: request.projectId,
          projectTitle: request.projectTitle,
          templateId: intake.templateId,
          templateLabel: intake.templateLabel,
          templateVersion: intake.templateVersion,
          sourceProjectTemplateVersion: request.sourceProjectTemplateVersion,
          assessmentSetId: intake.assessmentSetId,
          assessmentSetVersion: intake.assessmentSetVersion,
          model: intake.model,
          assessmentInputDigest: intake.assessmentInputDigest,
          dimensionDefs: intake.dimensionDefs,
          fields: intake.fields,
          submission: intake.submission,
          mca: { setId: intake.mcaSetId, setVersion: intake.mcaSetVersion, matrix: intake.matrix },
        });
        return [reviewHref(record.id), noUpdate(), noUpdate()];
      } catch (error) {
        submitting = null;
        notify("error", messages().submitFailed, errorText(error));
        return [noUpdate(), null, "false"];
      }
    },

    /** The reviews list, with the browser's zone for its dates. */
    readList: function () {
      listOpen = true;
      let timeZone = null;
      try {
        timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || null;
      } catch (_error) {
        timeZone = null;
      }
      const listing = reviews().listReviews();
      return { entries: listing.entries, unreadable: listing.unreadable, timeZone };
    },

    /** Cancel closes the delete confirmation. */
    closeDialog: function (clicks) {
      return clicks ? false : noUpdate();
    },

    /** Ask to delete the clicked session. Returns [target, dialog opened]. */
    askDelete: function (_clicks, listing) {
      const source = firedId();
      if (!isPlainObject(source) || !isPlainObject(listing)) return [noUpdate(), noUpdate()];
      const rows = [].concat(listing.entries || [], listing.unreadable || []);
      const row = rows.find((candidate) => isPlainObject(candidate) && candidate.id === source.id);
      return row ? [{ id: row.id }, true] : [noUpdate(), noUpdate()];
    },

    /** Delete the confirmed session and refresh the list. Returns [refresh
     *  tick, dialog opened]. */
    deleteReview: function (clicks, target, configValue) {
      if (!useConfig(configValue) || !clicks || !isPlainObject(target)) return [noUpdate(), noUpdate()];
      try {
        reviews().deleteReview(target.id);
        notify("success", messages().deleted);
      } catch (error) {
        notify("error", messages().deleteFailed, errorText(error));
      }
      return [(listTick += 1), false];
    },
  };

  window.pcnReview = {
    decide,
    retry,
    changeSummary,
    flushSummary,
    summaryState,
    idle,
    completion: (record, summaryInput) => completion(record, summaryInput),
    status: (record, summaryInput) => status(record, summaryInput),
    record: () => {
      if (!mounted) return null;
      const state = sessionState(mounted.reviewId);
      return state ? state.record : null;
    },
  };
})();
