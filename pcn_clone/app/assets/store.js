/* pcnStore: the browser-side project store.
 *
 * The browser owns localStorage; Python never reads or writes it. Pages reach
 * the store through `window.pcnStore` (directly or from the clientside
 * callbacks in projects.js and gate.js), so key names, record shapes and
 * validation live here only. `pcnStore.storage` exposes the low-level read,
 * write and failure semantics for any other key space.
 *
 * Key spaces, each versioned by a `schemaVersion` field:
 *   pcn:projects               the project index: an array of records
 *   pcn:project:<id>:answers   one draft per project: {schemaVersion, values}
 * The review sessions' key spaces belong to review-store.js (`pcnReviews`),
 * which builds on `storage`.
 *
 * Everything read back is untrusted. Each index entry is validated on its own;
 * a corrupt entry is quarantined (left out of every result and dropped on the
 * next index write) so one bad record never takes down the list. Reads degrade
 * to empty when storage is unavailable. Writes never fail silently: they throw
 * a `StoreError` and announce it as a `pcn:store-error` window event.
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  /** Version of the on-disk project record; any other value is quarantined. */
  const PROJECT_SCHEMA_VERSION = 1;
  /** Version of the draft wrapper; any other value reads as no draft. */
  const DRAFT_SCHEMA_VERSION = 1;

  const INDEX_KEY = "pcn:projects";
  const draftKey = (projectId) => `pcn:project:${projectId}:answers`;

  // --- Shape checks ---------------------------------------------------------

  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const isNonEmptyString = (value) => typeof value === "string" && value.length > 0;
  const isStringArray = (value) =>
    Array.isArray(value) && value.every((item) => typeof item === "string");

  /** The project record, field by field, in stored key order. The record is
   *  strict: a missing required field, a wrong type or an unknown key rejects
   *  the whole entry. */
  const RECORD_FIELDS = {
    schemaVersion: (value) => value === PROJECT_SCHEMA_VERSION,
    id: isNonEmptyString,
    title: isNonEmptyString,
    templateId: isNonEmptyString,
    templateVersion: isNonEmptyString,
    criteriaSetId: isNonEmptyString,
    criteriaVersion: isNonEmptyString,
    tags: isStringArray,
    createdISO: isNonEmptyString,
    editedISO: isNonEmptyString,
  };
  const OPTIONAL_FIELDS = new Set(["tags"]);

  /** A copy of `entry` in canonical key order when it is a valid current
   *  record, otherwise null. */
  function parseRecord(entry) {
    if (!isPlainObject(entry)) return null;
    for (const key of Object.keys(entry)) {
      if (!hasOwn(RECORD_FIELDS, key)) return null;
    }
    const record = {};
    for (const [key, isValid] of Object.entries(RECORD_FIELDS)) {
      if (!hasOwn(entry, key)) {
        if (OPTIONAL_FIELDS.has(key)) continue;
        return null;
      }
      if (!isValid(entry[key])) return null;
      record[key] = Array.isArray(entry[key]) ? entry[key].slice() : entry[key];
    }
    return record;
  }

  /** A restored draft is plausible when it is a non-array object: a flat
   *  field-id to answer map whose per-field values are heterogeneous. */
  const isPlausibleDraft = isPlainObject;

  /** Sort key for "most recently edited first"; an unparseable timestamp
   *  sorts as the oldest instead of throwing or jumping to the top. */
  function editedTime(record) {
    const parsed = Date.parse(record.editedISO);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  // --- Ids and clock --------------------------------------------------------

  const nowISO = () => new Date().toISOString();

  /** A v4 UUID. `crypto.randomUUID` exists only in secure contexts (https or
   *  localhost), so a plain-http deployment builds one from random bytes. */
  function newId() {
    const cryptoApi = window.crypto;
    if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
      try {
        return cryptoApi.randomUUID();
      } catch (_error) {
        // Fall through to the byte-built id.
      }
    }
    const bytes = new Uint8Array(16);
    if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
      cryptoApi.getRandomValues(bytes);
    } else {
      for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  // --- Storage access and failure reporting ---------------------------------

  /** A failed write. `kind` is "quota" (storage full), "unavailable"
   *  (storage disabled or blocked) or "write" (any other refusal); `cause`
   *  holds the browser's original error. */
  class StoreError extends Error {
    constructor(kind, message, cause) {
      super(message);
      this.name = "StoreError";
      this.kind = kind;
      this.cause = cause;
    }
  }

  function isQuotaError(error) {
    return (
      typeof DOMException !== "undefined" &&
      error instanceof DOMException &&
      (error.name === "QuotaExceededError" ||
        error.name === "NS_ERROR_DOM_QUOTA_REACHED" ||
        error.code === 22 ||
        error.code === 1014)
    );
  }

  /** Announce a failed write to any listener (an autosave line, a banner). */
  function reportError(error, key) {
    try {
      window.dispatchEvent(
        new CustomEvent("pcn:store-error", {
          detail: { kind: error.kind, message: error.message, key },
        }),
      );
    } catch (_ignored) {
      // Reporting must never mask the failure itself.
    }
  }

  /** localStorage, or undefined when the browser blocks access to it. */
  function getStorage() {
    try {
      return window.localStorage || undefined;
    } catch (_error) {
      return undefined;
    }
  }

  /** The parsed JSON at `key`, or undefined when absent, unreadable or not
   *  JSON. Reads never throw. */
  function readJSON(key) {
    const storage = getStorage();
    if (!storage) return undefined;
    let raw;
    try {
      raw = storage.getItem(key);
    } catch (_error) {
      return undefined;
    }
    if (raw === null) return undefined;
    try {
      return JSON.parse(raw);
    } catch (_error) {
      return undefined;
    }
  }

  /** Store `value` as JSON at `key`. Throws (and reports) a StoreError when
   *  the browser refuses the write. */
  function writeJSON(key, value) {
    const storage = getStorage();
    if (!storage) {
      const error = new StoreError(
        "unavailable",
        "Browser storage is unavailable, so nothing can be saved on this device.",
      );
      reportError(error, key);
      throw error;
    }
    try {
      storage.setItem(key, JSON.stringify(value));
    } catch (cause) {
      const error = isQuotaError(cause)
        ? new StoreError(
            "quota",
            "Browser storage is full. Delete a Concept Note you no longer need and try again.",
            cause,
          )
        : new StoreError(
            "write",
            `Browser storage refused the change${cause && cause.message ? `: ${cause.message}` : "."}`,
            cause,
          );
      reportError(error, key);
      throw error;
    }
  }

  /** Remove `key`; best-effort, a failed removal is not worth surfacing. */
  function remove(key) {
    const storage = getStorage();
    if (!storage) return;
    try {
      storage.removeItem(key);
    } catch (_error) {
      // Best-effort cleanup.
    }
  }

  /** The raw text at `key`: a string, null when absent, or undefined when
   *  storage is unavailable or refuses the read. Reads never throw. */
  function readText(key) {
    const storage = getStorage();
    if (!storage) return undefined;
    try {
      return storage.getItem(key);
    } catch (_error) {
      return undefined;
    }
  }

  /** Remove `key`. Throws (and reports) a StoreError when the browser
   *  refuses, for removals that must not fail silently. */
  function removeStrict(key) {
    const storage = getStorage();
    if (!storage) {
      const error = new StoreError(
        "unavailable",
        "Browser storage is unavailable, so nothing can be changed on this device.",
      );
      reportError(error, key);
      throw error;
    }
    try {
      storage.removeItem(key);
    } catch (cause) {
      const error = new StoreError(
        "write",
        `Browser storage refused the change${cause && cause.message ? `: ${cause.message}` : "."}`,
        cause,
      );
      reportError(error, key);
      throw error;
    }
  }

  // --- Project index --------------------------------------------------------

  /** The valid records in the index; corrupt entries are left out. A
   *  missing or wholly unreadable index reads as empty. */
  function readIndex() {
    const parsed = readJSON(INDEX_KEY);
    if (!Array.isArray(parsed)) return [];
    return parsed.map(parseRecord).filter((record) => record !== null);
  }

  const writeIndex = (records) => writeJSON(INDEX_KEY, records);

  function requireString(name, value) {
    if (!isNonEmptyString(value)) {
      throw new TypeError(`A project needs a non-empty ${name}.`);
    }
    return value;
  }

  function requireTags(value) {
    if (!isStringArray(value)) throw new TypeError("Project tags must be a list of strings.");
    return value.slice();
  }

  /** Every valid project, most recently edited first. */
  function listProjects() {
    return readIndex().sort((a, b) => editedTime(b) - editedTime(a));
  }

  /** The project with this id, or null. */
  function getProject(id) {
    return readIndex().find((record) => record.id === id) || null;
  }

  /** Create and store a project from {title, templateId, templateVersion,
   *  criteriaSetId, criteriaVersion, tags?}; the store stamps the id, schema
   *  version and timestamps. An empty tag list is not stored. Returns the
   *  new record. */
  function createProject(input) {
    const source = isPlainObject(input) ? input : {};
    const tags = source.tags === undefined || source.tags === null ? [] : requireTags(source.tags);
    const timestamp = nowISO();
    const record = {
      schemaVersion: PROJECT_SCHEMA_VERSION,
      id: newId(),
      title: requireString("title", source.title),
      templateId: requireString("templateId", source.templateId),
      templateVersion: requireString("templateVersion", source.templateVersion),
      criteriaSetId: requireString("criteriaSetId", source.criteriaSetId),
      criteriaVersion: requireString("criteriaVersion", source.criteriaVersion),
    };
    if (tags.length > 0) record.tags = tags;
    record.createdISO = timestamp;
    record.editedISO = timestamp;
    const records = readIndex();
    records.push(record);
    writeIndex(records);
    return record;
  }

  /** Apply {title?, tags?} to a project and re-stamp `editedISO`; a bare
   *  `updateProject(id)` is the "touch" that bumps recency after a draft
   *  save. Throws for an unknown id. Returns the updated record. */
  function updateProject(id, patch) {
    const changes = isPlainObject(patch) ? patch : {};
    const records = readIndex();
    const index = records.findIndex((record) => record.id === id);
    if (index === -1) throw new Error(`Cannot update unknown project "${id}".`);
    const updated = Object.assign({}, records[index]);
    if (changes.title !== undefined) updated.title = requireString("title", changes.title);
    if (changes.tags !== undefined) updated.tags = requireTags(changes.tags);
    updated.editedISO = nowISO();
    records[index] = updated;
    writeIndex(records);
    return updated;
  }

  /** Remove a project and its draft, so a deleted project leaves nothing
   *  behind. */
  function deleteProject(id) {
    writeIndex(readIndex().filter((record) => record.id !== id));
    remove(draftKey(id));
  }

  // --- Drafts ---------------------------------------------------------------

  /** A project's saved answers (a flat field-id to answer map), or null when
   *  there is none or the stored blob is not a current, plausible draft. */
  function loadDraft(projectId) {
    const parsed = readJSON(draftKey(projectId));
    if (!isPlainObject(parsed) || parsed.schemaVersion !== DRAFT_SCHEMA_VERSION) return null;
    return isPlausibleDraft(parsed.values) ? parsed.values : null;
  }

  /** Save a project's answers. Throws a StoreError when storage refuses. */
  function saveDraft(projectId, values) {
    if (!isPlausibleDraft(values)) throw new TypeError("A draft must be a field-id to answer map.");
    writeJSON(draftKey(projectId), { schemaVersion: DRAFT_SCHEMA_VERSION, values });
  }

  /** Forget a project's saved answers. */
  function clearDraft(projectId) {
    remove(draftKey(projectId));
  }

  // --- Defaults -------------------------------------------------------------

  /** Create an ordinary, editable project from a default: the record from
   *  `meta` (the createProject input) and its draft from `values`. If the
   *  draft write fails the record is removed again, so a half-cloned project
   *  never appears, and the original failure is rethrown. */
  function cloneDefaultProject(meta, values) {
    const project = createProject(meta);
    try {
      saveDraft(project.id, values);
    } catch (error) {
      try {
        deleteProject(project.id);
      } catch (_cleanupError) {
        // Keep the original failure: it says why cloning failed.
      }
      throw error;
    }
    return project;
  }

  window.pcnStore = Object.assign(window.pcnStore || {}, {
    PROJECT_SCHEMA_VERSION,
    DRAFT_SCHEMA_VERSION,
    INDEX_KEY,
    draftKey,
    StoreError,
    listProjects,
    getProject,
    createProject,
    updateProject,
    deleteProject,
    loadDraft,
    saveDraft,
    clearDraft,
    cloneDefaultProject,
    newId,
    nowISO,
    /** Low-level storage with the store's read and failure semantics. */
    storage: {
      readJSON,
      readText,
      writeJSON,
      remove,
      removeStrict,
      isPlainObject,
      isNonEmptyString,
    },
  });
})();
