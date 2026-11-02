/* pcnReviews: the browser-side review store, the reviewer's half of
 * localStorage (the project half is pcnStore in store.js, whose `storage`
 * helpers this builds on).
 *
 * Key spaces, each versioned by `schemaVersion` (2):
 *   pcn:reviews        the index: one entry per session with its progress
 *                      counts, re-derived from the payload on every write
 *   pcn:review:<id>    one full review record per session
 *
 * The record is self-contained: the submission and its serialized field
 * text, the dimension definitions and the MCA matrix are frozen into it at
 * Submit, so a review renders from its own record whatever the live content
 * says later. Per item (a dimension, or an MCA criterion) it holds
 *   {status: "pending", generation}
 *   {status: "error", generation, errorMessage, error: {kind, code}}
 *   {status: "ok", generation, finding, disposition?}       (dimensions)
 *   {status: "ok", generation, scoreFinding, disposition?}  (criteria)
 * Errors are `retryable` (RETRYABLE_CODES: a retry may succeed) or
 * `terminal` (TERMINAL_CODES: it cannot); the two code sets are disjoint.
 *
 * Everything read back is untrusted and every read and write validates the
 * whole record: field-level strictness (unknown keys reject) plus the
 * cross-record invariants: definition ids unique and in agreement with the
 * state keys; the submission targets the record's template; the field
 * snapshot and the submission name the same fields in the same order; each
 * finding is keyed by its item id and carries the record's model; every
 * citation, the AI's and the reviewer's, resolves to the field snapshot;
 * every score is on the frozen scale and a `not_evidenced` basis carries the
 * scale minimum. A record that fails is unreadable: reported, never shown
 * half-empty, and never migrated across schema versions.
 *
 * API (`window.pcnReviews`):
 *   createReview(input) -> record
 *     input: {projectId, projectTitle, templateId, templateLabel,
 *     templateVersion, sourceProjectTemplateVersion, assessmentSetId,
 *     assessmentSetVersion, model, assessmentInputDigest, dimensionDefs,
 *     fields, submission, mca?: {setId, setVersion, matrix}}. The store
 *     stamps the id, timestamps, every item `{status: "pending",
 *     generation: 0}` and an empty `reviewerSummary`.
 *   listReviews() -> {entries, unreadable}
 *     entries: index entries derived from each readable payload, most
 *     recently edited first; unreadable: [{id?, reason}], listed, never
 *     dropped.
 *   getReview(id) -> {status: "ok", review} | {status: "missing"}
 *     | {status: "unreadable", message}
 *   writeItem(reviewId, kind, itemId, expectedGeneration, next)
 *     -> {applied: true, review} | {applied: false, reason: "stale" |
 *     "missing" | "unreadable"}
 *     Compare-and-swap on one item (`kind` "dimension" or "criterion"):
 *     re-reads the record and writes `next` (a full item state carrying its
 *     own generation) only while the stored generation equals
 *     `expectedGeneration`. Launches and decisions write at
 *     `expectedGeneration + 1`, so a superseded write is reported, never
 *     applied.
 *   writeResult(reviewId, kind, itemId, generation, next) -> as writeItem;
 *     the completion of a launch: written only while the item is still
 *     `pending` at `generation` (the launch's), so nothing overwrites a
 *     result or a decision already stored.
 *   launchItem(reviewId, kind, itemId, currentGeneration) -> as writeItem;
 *     writes `{status: "pending", generation: currentGeneration + 1}`.
 *   saveSummary(reviewId, text) -> record (re-reads, patches only
 *     `reviewerSummary`).
 *   deleteReview(id): removes the payload first, then the index entry, so
 *     a late write finds nothing to resurrect.
 *   items(record) -> [{kind, id, label, state}] in record order
 *     (dimensions by definition, then criteria by matrix).
 *   itemState(record, kind, itemId), isRetryableErrorState(state)
 *   checkRecord(value) -> {ok: true, record} | {ok: false, issues}
 * Failures throw: `ReviewInvariantError` when a write would break the
 * record's invariants (an application defect), `pcnStore.StoreError` when
 * the browser refuses the write (a device problem), plain `Error` when the
 * index or the payload to replace cannot be read, or the record to update
 * is gone. A failed write changes nothing.
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const REVIEW_SCHEMA_VERSION = 2;
  const INDEX_KEY = "pcn:reviews";
  const reviewKey = (reviewId) => `pcn:review:${reviewId}`;

  const RETRYABLE_CODES = ["provider_error", "transport_error", "storage_error"];
  const TERMINAL_CODES = [
    "invalid_request",
    "unknown_template",
    "unknown_assessment_set",
    "unknown_dimension",
    "unknown_mca_set",
    "unknown_mca_criterion",
    "template_version_mismatch",
    "assessment_set_version_mismatch",
    "mca_set_version_mismatch",
    "model_mismatch",
    "input_digest_mismatch",
    "inconsistent_submission",
    "invalid_result",
  ];
  const KINDS = ["dimension", "criterion"];
  const VERDICTS = ["fail", "notClear", "pass"];
  const QUOTE_MAX_LENGTH = 300;
  const JUSTIFICATION_MAX_LENGTH = 600;
  const MAX_CITATIONS = 3;

  const UNREADABLE_VERSION =
    "This review was saved by a different version of the app and cannot be opened.";
  const UNREADABLE_CORRUPT = "This review's stored data is corrupt and cannot be opened.";
  const UNREADABLE_MISSING = "This review's stored data is missing.";
  const UNREADABLE_INDEX = "The review index could not be read.";

  const store = () => window.pcnStore;
  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  const clone = (value) => JSON.parse(JSON.stringify(value));

  /** A write that would break the record's own invariants: an application
   *  defect, distinct from the browser refusing a write. */
  class ReviewInvariantError extends Error {
    constructor(message) {
      super(message);
      this.name = "ReviewInvariantError";
    }
  }

  // --- Validation -----------------------------------------------------------
  //
  // Each check takes (value, path, issues) and appends {path, message} for
  // every problem; a value is valid exactly when it appends nothing.

  function fail(issues, path, message) {
    issues.push({ path: path.slice(), message });
  }

  const str = (min) => (value, path, issues) => {
    if (typeof value !== "string") fail(issues, path, "Expected a string.");
    else if (value.length < min) fail(issues, path, `Expected at least ${min} character(s).`);
  };
  const anyString = str(0);
  const nonEmpty = str(1);

  const nonBlank = (label) => (value, path, issues) => {
    if (typeof value !== "string") fail(issues, path, "Expected a string.");
    else if (value.trim().length === 0) fail(issues, path, `${label} must not be blank.`);
  };

  const bounded = (label, max) => (value, path, issues) => {
    if (typeof value !== "string" || value.length < 1) {
      fail(issues, path, "Expected a non-empty string.");
    } else if (value.length > max) {
      fail(issues, path, `Expected at most ${max} characters.`);
    } else if (value.trim().length === 0) {
      fail(issues, path, `${label} must not be blank.`);
    }
  };
  const quote = bounded("Quote", QUOTE_MAX_LENGTH);
  const justification = bounded("Justification", JUSTIFICATION_MAX_LENGTH);

  const integer = (min) => (value, path, issues) => {
    if (!Number.isInteger(value) || value < min) {
      fail(issues, path, `Expected an integer of at least ${min}.`);
    }
  };
  const generation = integer(0);

  const boolean = (value, path, issues) => {
    if (typeof value !== "boolean") fail(issues, path, "Expected a boolean.");
  };

  const oneOf = (allowed) => (value, path, issues) => {
    if (!allowed.includes(value)) fail(issues, path, `Expected one of ${allowed.join(", ")}.`);
  };

  const literal = (expected) => (value, path, issues) => {
    if (value !== expected) fail(issues, path, `Expected ${JSON.stringify(expected)}.`);
  };

  const arrayOf = (item, min, max) => (value, path, issues) => {
    if (!Array.isArray(value)) {
      fail(issues, path, "Expected an array.");
      return;
    }
    if (min !== undefined && value.length < min) {
      fail(issues, path, `Expected at least ${min} item(s).`);
    }
    if (max !== undefined && value.length > max) {
      fail(issues, path, `Expected at most ${max} item(s).`);
    }
    value.forEach((entry, index) => item(entry, path.concat(index), issues));
  };

  const recordOf = (item) => (value, path, issues) => {
    if (!isPlainObject(value)) {
      fail(issues, path, "Expected an object.");
      return;
    }
    for (const [key, entry] of Object.entries(value)) item(entry, path.concat(key), issues);
  };

  /** A strict object: every `required` key present, `optional` keys
   *  allowed, nothing else. */
  const object = (required, optional) => (value, path, issues) => {
    if (!isPlainObject(value)) {
      fail(issues, path, "Expected an object.");
      return;
    }
    const extra = optional || {};
    for (const key of Object.keys(value)) {
      if (!hasOwn(required, key) && !hasOwn(extra, key)) {
        fail(issues, path.concat(key), `Unrecognized key "${key}".`);
      }
    }
    for (const [key, check] of Object.entries(required)) {
      if (!hasOwn(value, key)) fail(issues, path.concat(key), "Required.");
      else check(value[key], path.concat(key), issues);
    }
    for (const [key, check] of Object.entries(extra)) {
      if (hasOwn(value, key)) check(value[key], path.concat(key), issues);
    }
  };

  /** A union discriminated by `key`: `branches` maps each value of the
   *  discriminator to the check of its branch. */
  const union = (key, branches) => (value, path, issues) => {
    if (!isPlainObject(value) || !hasOwn(branches, value[key])) {
      fail(issues, path.concat(key), `Expected ${key} to be one of ${Object.keys(branches).join(", ")}.`);
      return;
    }
    branches[value[key]](value, path, issues);
  };

  const passes = (check, value) => {
    const issues = [];
    check(value, [], issues);
    return issues.length === 0;
  };

  // The submission's answer values: one of the shapes a field answer takes.
  const stringRecord = recordOf(anyString);
  const nestedStringRecord = recordOf(stringRecord);
  const ANSWER_SHAPES = [
    anyString,
    stringRecord,
    arrayOf(stringRecord),
    object({
      options: arrayOf(stringRecord),
      selection: object({ optionId: anyString, justification: anyString }),
    }),
    object({ componentCosts: nestedStringRecord, narratives: stringRecord }),
    object({ rows: nestedStringRecord, narratives: stringRecord }, { applicability: stringRecord }),
    object({ rows: nestedStringRecord }),
    object({ values: stringRecord, narratives: stringRecord }),
  ];
  const answerValue = (value, path, issues) => {
    if (!ANSWER_SHAPES.some((shape) => passes(shape, value))) {
      fail(issues, path, "The answer does not match any field answer shape.");
    }
  };

  const submission = object({
    templateId: nonEmpty,
    answers: arrayOf(object({ sectionId: nonEmpty, fieldId: nonEmpty, answer: answerValue }), 1),
  });

  const verdictDescriptors = object({ fail: nonEmpty, notClear: nonEmpty, pass: nonEmpty });
  const dimensionDef = object({
    id: nonEmpty,
    label: nonEmpty,
    description: nonEmpty,
    guidance: nonEmpty,
    verdicts: verdictDescriptors,
  });
  const snapshotField = object({
    sectionId: nonEmpty,
    sectionLabel: nonEmpty,
    fieldId: nonEmpty,
    fieldLabel: nonEmpty,
    serializedText: nonEmpty,
  });

  const verifiedRef = object({ sectionId: nonEmpty, fieldId: nonEmpty, quote, verified: boolean });
  const finding = object({
    dimensionId: nonEmpty,
    model: nonEmpty,
    verdict: oneOf(VERDICTS),
    reasoning: anyString,
    evidence: arrayOf(verifiedRef),
    questions: arrayOf(anyString),
  });
  const scoreFinding = object({
    criterionId: nonEmpty,
    model: nonEmpty,
    score: integer(1),
    justification,
    basis: union("kind", {
      documented: object({
        kind: literal("documented"),
        evidence: arrayOf(verifiedRef, 1, MAX_CITATIONS),
      }),
      not_evidenced: object({ kind: literal("not_evidenced") }),
    }),
  });

  const reviewerRef = object(
    { sectionId: nonEmpty, fieldId: nonEmpty },
    { quote: anyString, note: anyString },
  );
  const disposition = union("kind", {
    accepted: object({ kind: literal("accepted") }, { note: anyString }),
    edited: object(
      {
        kind: literal("edited"),
        finalVerdict: oneOf(VERDICTS),
        finalText: nonBlank("An edited finding's text"),
        evidence: arrayOf(reviewerRef),
      },
      { note: anyString },
    ),
    dismissed: object({ kind: literal("dismissed") }, { note: anyString }),
  });
  const criterionDisposition = union("kind", {
    accepted: object({ kind: literal("accepted") }, { note: anyString }),
    adjusted: object({
      kind: literal("adjusted"),
      finalScore: integer(1),
      rationale: nonBlank("An adjusted score's rationale"),
      basis: union("kind", {
        documented: object({ kind: literal("documented"), evidence: arrayOf(reviewerRef, 1) }),
        not_evidenced: object({ kind: literal("not_evidenced") }),
      }),
    }),
  });

  const runError = union("kind", {
    retryable: object({ kind: literal("retryable"), code: oneOf(RETRYABLE_CODES) }),
    terminal: object({ kind: literal("terminal"), code: oneOf(TERMINAL_CODES) }),
  });

  const itemStateOf = (resultKey, resultCheck, dispositionCheck) =>
    union("status", {
      pending: object({ status: literal("pending"), generation }),
      error: object({
        status: literal("error"),
        generation,
        errorMessage: nonEmpty,
        error: runError,
      }),
      ok: object(
        { status: literal("ok"), generation, [resultKey]: resultCheck },
        { disposition: dispositionCheck },
      ),
    });
  const dimensionState = itemStateOf("finding", finding, disposition);
  const criterionState = itemStateOf("scoreFinding", scoreFinding, criterionDisposition);

  const finitePercent = (value, path, issues) => {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100) {
      fail(issues, path, "Expected a finite number from 0 to 100.");
    }
  };
  const matrixShape = object({
    scale: arrayOf(object({ value: integer(1), label: nonEmpty, meaning: nonEmpty }), 2),
    bands: arrayOf(object({ id: nonEmpty, label: nonEmpty, minPercentOfMaximum: finitePercent }), 1),
    criteria: arrayOf(
      object({
        id: nonEmpty,
        label: nonEmpty,
        weight: integer(1),
        description: nonEmpty,
        descriptors: recordOf(nonEmpty),
      }),
      1,
    ),
  });

  /** The matrix's own invariants: a contiguous 1..N scale, unique criteria
   *  weighing 100 in all with a descriptor per scale value, and unique
   *  bands whose thresholds strictly descend to exactly 0. */
  function matrix(value, path, issues) {
    const before = issues.length;
    matrixShape(value, path, issues);
    if (issues.length > before) return;
    value.scale.forEach((entry, index) => {
      if (entry.value !== index + 1) {
        fail(
          issues,
          path.concat("scale", index, "value"),
          "Scale values must be a contiguous ascending run starting at 1; " +
            `position ${index} has value ${entry.value}.`,
        );
      }
    });
    const scaleKeys = new Set(value.scale.map((entry) => String(entry.value)));
    const seenCriteria = new Set();
    let weightSum = 0;
    value.criteria.forEach((criterion, index) => {
      if (seenCriteria.has(criterion.id)) {
        fail(issues, path.concat("criteria", index, "id"), `Duplicate criterion id "${criterion.id}".`);
      }
      seenCriteria.add(criterion.id);
      weightSum += criterion.weight;
      const descriptorKeys = new Set(Object.keys(criterion.descriptors));
      for (const key of scaleKeys) {
        if (!descriptorKeys.has(key)) {
          fail(
            issues,
            path.concat("criteria", index, "descriptors"),
            `Criterion "${criterion.id}" has no descriptor for scale value ${key}.`,
          );
        }
      }
      for (const key of descriptorKeys) {
        if (!scaleKeys.has(key)) {
          fail(
            issues,
            path.concat("criteria", index, "descriptors"),
            `Criterion "${criterion.id}" has a descriptor for "${key}", which is not a scale value.`,
          );
        }
      }
    });
    if (weightSum !== 100) {
      fail(issues, path.concat("criteria"), `Criterion weights must sum to exactly 100; they sum to ${weightSum}.`);
    }
    const seenBands = new Set();
    value.bands.forEach((band, index) => {
      if (seenBands.has(band.id)) {
        fail(issues, path.concat("bands", index, "id"), `Duplicate band id "${band.id}".`);
      }
      seenBands.add(band.id);
      const previous = value.bands[index - 1];
      if (previous && band.minPercentOfMaximum >= previous.minPercentOfMaximum) {
        fail(
          issues,
          path.concat("bands", index, "minPercentOfMaximum"),
          "Band thresholds must be strictly descending; " +
            `"${band.id}" (${band.minPercentOfMaximum}) does not descend from ` +
            `"${previous.id}" (${previous.minPercentOfMaximum}).`,
        );
      }
    });
    const last = value.bands[value.bands.length - 1];
    if (last.minPercentOfMaximum !== 0) {
      fail(
        issues,
        path.concat("bands", value.bands.length - 1, "minPercentOfMaximum"),
        "The final band's threshold must be exactly 0 so every percent-of-maximum " +
          `resolves to a band; "${last.id}" has ${last.minPercentOfMaximum}.`,
      );
    }
  }

  const recordShape = object(
    {
      schemaVersion: literal(REVIEW_SCHEMA_VERSION),
      id: nonEmpty,
      createdISO: nonEmpty,
      editedISO: nonEmpty,
      projectId: nonEmpty,
      projectTitle: nonEmpty,
      templateId: nonEmpty,
      templateLabel: nonEmpty,
      templateVersion: nonEmpty,
      sourceProjectTemplateVersion: nonEmpty,
      assessmentSetId: nonEmpty,
      assessmentSetVersion: nonEmpty,
      model: nonEmpty,
      assessmentInputDigest: nonEmpty,
      dimensionDefs: arrayOf(dimensionDef, 1),
      fields: arrayOf(snapshotField, 1),
      submission,
      dimensions: recordOf(dimensionState),
      reviewerSummary: anyString,
    },
    {
      mca: object({
        setId: nonEmpty,
        setVersion: nonEmpty,
        matrix,
        criteria: recordOf(criterionState),
      }),
    },
  );

  /** The invariants across the record's parts, on a record whose shape is
   *  already valid. */
  function crossRecord(record, issues) {
    const defIds = new Set();
    for (const def of record.dimensionDefs) {
      if (defIds.has(def.id)) fail(issues, ["dimensionDefs"], `Duplicate dimension id "${def.id}".`);
      defIds.add(def.id);
    }
    for (const key of Object.keys(record.dimensions)) {
      if (!defIds.has(key)) {
        fail(issues, ["dimensions"], `Dimension state "${key}" has no matching definition.`);
      }
    }
    for (const id of defIds) {
      if (!hasOwn(record.dimensions, id)) {
        fail(issues, ["dimensions"], `Dimension "${id}" has no state entry.`);
      }
    }

    if (record.submission.templateId !== record.templateId) {
      fail(
        issues,
        ["submission", "templateId"],
        `Submission targets template "${record.submission.templateId}", ` +
          `but the record pins "${record.templateId}".`,
      );
    }

    const fieldRefs = new Set();
    for (const field of record.fields) {
      const ref = `${field.sectionId}/${field.fieldId}`;
      if (fieldRefs.has(ref)) fail(issues, ["fields"], `Duplicate field snapshot ref "${ref}".`);
      fieldRefs.add(ref);
    }
    const answers = record.submission.answers;
    if (record.fields.length !== answers.length) {
      fail(
        issues,
        ["fields"],
        `Field snapshot has ${record.fields.length} entries but the ` +
          `submission has ${answers.length} answers.`,
      );
    } else {
      answers.forEach((answer, index) => {
        const field = record.fields[index];
        if (answer.sectionId !== field.sectionId || answer.fieldId !== field.fieldId) {
          fail(
            issues,
            ["fields", index],
            `Field snapshot ref "${field.sectionId}/${field.fieldId}" does not agree ` +
              `with submission answer "${answer.sectionId}/${answer.fieldId}" at position ${index}.`,
          );
        }
      });
    }
    const cites = (ref) => fieldRefs.has(`${ref.sectionId}/${ref.fieldId}`);

    for (const [key, state] of Object.entries(record.dimensions)) {
      if (state.status !== "ok") continue;
      const path = ["dimensions", key];
      if (state.finding.dimensionId !== key) {
        fail(issues, path, `Finding for "${key}" carries dimensionId "${state.finding.dimensionId}".`);
      }
      if (state.finding.model !== record.model) {
        fail(
          issues,
          path,
          `Finding for "${key}" was produced by model "${state.finding.model}", ` +
            `but the record pins "${record.model}".`,
        );
      }
      for (const ref of state.finding.evidence) {
        if (!cites(ref)) {
          fail(
            issues,
            path,
            `Finding for "${key}" cites "${ref.sectionId}/${ref.fieldId}", ` +
              "which is not in the record's field snapshot.",
          );
        }
      }
      if (state.disposition && state.disposition.kind === "edited") {
        for (const ref of state.disposition.evidence) {
          if (!cites(ref)) {
            fail(
              issues,
              path,
              `Edited disposition for "${key}" cites "${ref.sectionId}/${ref.fieldId}", ` +
                "which is not in the record's field snapshot.",
            );
          }
        }
      }
    }

    if (!record.mca) return;
    const mca = record.mca;
    const matrixIds = new Set(mca.matrix.criteria.map((criterion) => criterion.id));
    for (const key of Object.keys(mca.criteria)) {
      if (!matrixIds.has(key)) {
        fail(issues, ["mca", "criteria"], `Criterion state "${key}" is not in the frozen matrix.`);
      }
    }
    for (const id of matrixIds) {
      if (!hasOwn(mca.criteria, id)) {
        fail(issues, ["mca", "criteria"], `Criterion "${id}" has no state entry.`);
      }
    }
    const scaleValues = new Set(mca.matrix.scale.map((entry) => entry.value));
    const scaleMinimum = mca.matrix.scale[0].value;
    for (const [key, state] of Object.entries(mca.criteria)) {
      if (state.status !== "ok") continue;
      const path = ["mca", "criteria", key];
      const scored = state.scoreFinding;
      if (scored.criterionId !== key) {
        fail(issues, path, `Score finding for "${key}" carries criterionId "${scored.criterionId}".`);
      }
      if (scored.model !== record.model) {
        fail(
          issues,
          path,
          `Score finding for "${key}" was produced by model "${scored.model}", ` +
            `but the record pins "${record.model}".`,
        );
      }
      if (!scaleValues.has(scored.score)) {
        fail(issues, path, `Score ${scored.score} for "${key}" is not a value on the frozen matrix's scale.`);
      }
      if (scored.basis.kind === "not_evidenced" && scored.score !== scaleMinimum) {
        fail(
          issues,
          path,
          `Score finding for "${key}" pairs a not_evidenced basis with score ${scored.score}; ` +
            `absence can only score the scale minimum (${scaleMinimum}).`,
        );
      }
      if (scored.basis.kind === "documented") {
        for (const ref of scored.basis.evidence) {
          if (!cites(ref)) {
            fail(
              issues,
              path,
              `Score finding for "${key}" cites "${ref.sectionId}/${ref.fieldId}", ` +
                "which is not in the record's field snapshot.",
            );
          }
        }
      }
      const adjusted = state.disposition && state.disposition.kind === "adjusted" ? state.disposition : null;
      if (!adjusted) continue;
      if (!scaleValues.has(adjusted.finalScore)) {
        fail(
          issues,
          path,
          `Adjusted score ${adjusted.finalScore} for "${key}" is not a value on the frozen matrix's scale.`,
        );
      }
      if (adjusted.basis.kind === "not_evidenced" && adjusted.finalScore !== scaleMinimum) {
        fail(
          issues,
          path,
          `Adjusted score for "${key}" pairs a not_evidenced basis with score ${adjusted.finalScore}; ` +
            "a non-minimum score must cite the submission.",
        );
      }
      if (adjusted.basis.kind === "documented") {
        for (const ref of adjusted.basis.evidence) {
          if (!cites(ref)) {
            fail(
              issues,
              path,
              `Adjusted disposition for "${key}" cites "${ref.sectionId}/${ref.fieldId}", ` +
                "which is not in the record's field snapshot.",
            );
          }
        }
      }
    }
  }

  /** The whole record check: shape, then (on a well-shaped record) the
   *  cross-record invariants. */
  function checkRecord(value) {
    const issues = [];
    recordShape(value, [], issues);
    if (issues.length === 0) crossRecord(value, issues);
    return issues.length === 0 ? { ok: true, record: value } : { ok: false, issues };
  }

  const indexEntry = object(
    {
      schemaVersion: literal(REVIEW_SCHEMA_VERSION),
      id: nonEmpty,
      createdISO: nonEmpty,
      editedISO: nonEmpty,
      projectTitle: nonEmpty,
      templateId: nonEmpty,
      templateLabel: nonEmpty,
      dimensionsTotal: integer(1),
      dimensionsOk: generation,
      dimensionsError: generation,
    },
    { criteriaTotal: integer(1), criteriaOk: generation, criteriaError: generation },
  );

  /** The record, or a ReviewInvariantError naming every violation. */
  function validateRecord(record) {
    const result = checkRecord(record);
    if (!result.ok) {
      throw new ReviewInvariantError(
        "Review record violates its invariants: " +
          result.issues.map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`).join("; "),
      );
    }
    return record;
  }

  // --- Items ----------------------------------------------------------------

  function requireKind(kind) {
    if (!KINDS.includes(kind)) throw new TypeError(`Unknown review item kind "${kind}".`);
  }

  /** The stored state of one item, or undefined. */
  function itemState(record, kind, itemId) {
    requireKind(kind);
    const states = kind === "dimension" ? record.dimensions : record.mca && record.mca.criteria;
    return states && hasOwn(states, itemId) ? states[itemId] : undefined;
  }

  /** `record` with one item's state replaced. */
  function withItemState(record, kind, itemId, next) {
    if (kind === "dimension") {
      return Object.assign({}, record, {
        dimensions: Object.assign({}, record.dimensions, { [itemId]: next }),
      });
    }
    return Object.assign({}, record, {
      mca: Object.assign({}, record.mca, {
        criteria: Object.assign({}, record.mca.criteria, { [itemId]: next }),
      }),
    });
  }

  /** Every item of a record in its frozen order: dimensions by definition,
   *  then criteria by matrix. */
  function items(record) {
    const list = record.dimensionDefs.map((def) => ({
      kind: "dimension",
      id: def.id,
      label: def.label,
      state: record.dimensions[def.id],
    }));
    if (record.mca) {
      for (const criterion of record.mca.matrix.criteria) {
        list.push({
          kind: "criterion",
          id: criterion.id,
          label: criterion.label,
          state: record.mca.criteria[criterion.id],
        });
      }
    }
    return list;
  }

  /** True when an item failed in a way a retry can fix. */
  const isRetryableErrorState = (state) =>
    !!state && state.status === "error" && state.error.kind === "retryable";

  // --- Index ----------------------------------------------------------------

  function editedTime(entry) {
    const parsed = Date.parse(entry.editedISO);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  /** The record's index entry: the one writer of the progress counts. */
  function indexEntryOf(record) {
    const states = Object.values(record.dimensions);
    const entry = {
      schemaVersion: REVIEW_SCHEMA_VERSION,
      id: record.id,
      createdISO: record.createdISO,
      editedISO: record.editedISO,
      projectTitle: record.projectTitle,
      templateId: record.templateId,
      templateLabel: record.templateLabel,
      dimensionsTotal: states.length,
      dimensionsOk: states.filter((state) => state.status === "ok").length,
      dimensionsError: states.filter((state) => state.status === "error").length,
    };
    if (record.mca) {
      const criteria = Object.values(record.mca.criteria);
      entry.criteriaTotal = criteria.length;
      entry.criteriaOk = criteria.filter((state) => state.status === "ok").length;
      entry.criteriaError = criteria.filter((state) => state.status === "error").length;
    }
    return entry;
  }

  function bestEffortId(raw) {
    return isPlainObject(raw) && typeof raw.id === "string" && raw.id.length > 0 ? raw.id : undefined;
  }

  /** Why a stored shape is unreadable: another app version, or corruption. */
  function unreadableReason(raw) {
    return isPlainObject(raw) && raw.schemaVersion !== REVIEW_SCHEMA_VERSION
      ? UNREADABLE_VERSION
      : UNREADABLE_CORRUPT;
  }

  /** The raw index: {status: "absent"} on a fresh device, {status:
   *  "unreadable"} when storage refuses or holds something else, otherwise
   *  {status: "ok", entries} with the entries as stored. */
  function readRawIndex() {
    const text = store().storage.readText(INDEX_KEY);
    if (text === undefined) return { status: "unreadable" };
    if (text === null) return { status: "absent" };
    try {
      const parsed = JSON.parse(text);
      return Array.isArray(parsed) ? { status: "ok", entries: parsed } : { status: "unreadable" };
    } catch (_error) {
      return { status: "unreadable" };
    }
  }

  /** One validated payload: ok, missing or unreadable. */
  function readRecord(reviewId) {
    const text = store().storage.readText(reviewKey(reviewId));
    if (text === undefined || text === null) return { status: "missing" };
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (_error) {
      return { status: "unreadable", message: unreadableReason(undefined) };
    }
    const result = checkRecord(parsed);
    return result.ok
      ? { status: "ok", review: result.record }
      : { status: "unreadable", message: unreadableReason(parsed) };
  }

  /** Write the payload, then upsert its index entry (other entries kept
   *  verbatim, unreadable ones included). An unreadable index, or a payload
   *  that cannot be read to be put back, refuses the write before anything
   *  changes; if the index write fails, the payload is put back as it was
   *  and the failure rethrown, so a throw means nothing changed. */
  function writeRecord(record) {
    const index = readRawIndex();
    if (index.status === "unreadable") {
      throw new Error(
        "The review index could not be read; refusing to write so the stored sessions are not made inconsistent.",
      );
    }
    const key = reviewKey(record.id);
    const previous = store().storage.readText(key);
    if (previous === undefined) {
      throw new Error("The stored review could not be read; refusing to write over it.");
    }
    store().storage.writeJSON(key, record);
    try {
      const entries = index.status === "ok" ? index.entries.slice() : [];
      const entry = indexEntryOf(record);
      const at = entries.findIndex((existing) => bestEffortId(existing) === record.id);
      if (at === -1) entries.push(entry);
      else entries[at] = entry;
      store().storage.writeJSON(INDEX_KEY, entries);
    } catch (error) {
      try {
        if (previous === null) store().storage.removeStrict(key);
        else store().storage.writeJSON(key, JSON.parse(previous));
      } catch (_rollbackError) {
        // The payload keeps the new value; readers derive the listing from
        // payloads, so what the reviewer sees stays honest.
      }
      throw error;
    }
  }

  // --- Store operations -----------------------------------------------------

  function listReviews() {
    const index = readRawIndex();
    if (index.status === "absent") return { entries: [], unreadable: [] };
    if (index.status === "unreadable") {
      return { entries: [], unreadable: [{ reason: UNREADABLE_INDEX }] };
    }
    const entries = [];
    const unreadable = [];
    for (const raw of index.entries) {
      if (!passes(indexEntry, raw)) {
        const id = bestEffortId(raw);
        unreadable.push(id ? { id, reason: unreadableReason(raw) } : { reason: unreadableReason(raw) });
        continue;
      }
      const payload = readRecord(raw.id);
      if (payload.status === "ok") {
        entries.push(indexEntryOf(payload.review));
      } else {
        unreadable.push({
          id: raw.id,
          reason: payload.status === "unreadable" ? payload.message : UNREADABLE_MISSING,
        });
      }
    }
    entries.sort((a, b) => editedTime(b) - editedTime(a));
    return { entries, unreadable };
  }

  const getReview = (id) => readRecord(id);

  function createReview(input) {
    const source = isPlainObject(input) ? clone(input) : {};
    const timestamp = store().nowISO();
    const assembled = {
      schemaVersion: REVIEW_SCHEMA_VERSION,
      id: store().newId(),
      createdISO: timestamp,
      editedISO: timestamp,
      projectId: source.projectId,
      projectTitle: source.projectTitle,
      templateId: source.templateId,
      templateLabel: source.templateLabel,
      templateVersion: source.templateVersion,
      sourceProjectTemplateVersion: source.sourceProjectTemplateVersion,
      assessmentSetId: source.assessmentSetId,
      assessmentSetVersion: source.assessmentSetVersion,
      model: source.model,
      assessmentInputDigest: source.assessmentInputDigest,
      dimensionDefs: source.dimensionDefs,
      fields: source.fields,
      submission: source.submission,
      dimensions: {},
    };
    for (const def of Array.isArray(source.dimensionDefs) ? source.dimensionDefs : []) {
      if (isPlainObject(def)) assembled.dimensions[def.id] = { status: "pending", generation: 0 };
    }
    if (source.mca !== undefined) {
      const mca = isPlainObject(source.mca) ? source.mca : {};
      const criteria = {};
      const listed = isPlainObject(mca.matrix) && Array.isArray(mca.matrix.criteria) ? mca.matrix.criteria : [];
      for (const criterion of listed) {
        if (isPlainObject(criterion)) criteria[criterion.id] = { status: "pending", generation: 0 };
      }
      assembled.mca = { setId: mca.setId, setVersion: mca.setVersion, matrix: mca.matrix, criteria };
    }
    assembled.reviewerSummary = "";
    const record = validateRecord(assembled);
    writeRecord(record);
    return record;
  }

  /** The one compare-and-swap: re-read the record and write `next` over
   *  one item while `current(state)` holds for its stored state. */
  function swapItem(reviewId, kind, itemId, current, next) {
    requireKind(kind);
    const found = readRecord(reviewId);
    if (found.status === "missing") return { applied: false, reason: "missing" };
    if (found.status === "unreadable") return { applied: false, reason: "unreadable" };
    const state = itemState(found.review, kind, itemId);
    if (!state) throw new Error(`Review "${reviewId}" has no ${kind} "${itemId}".`);
    if (!current(state)) return { applied: false, reason: "stale" };
    const updated = withItemState(found.review, kind, itemId, clone(next));
    updated.editedISO = store().nowISO();
    const validated = validateRecord(updated);
    writeRecord(validated);
    return { applied: true, review: validated };
  }

  const writeItem = (reviewId, kind, itemId, expectedGeneration, next) =>
    swapItem(reviewId, kind, itemId, (state) => state.generation === expectedGeneration, next);

  const writeResult = (reviewId, kind, itemId, generation, next) =>
    swapItem(
      reviewId,
      kind,
      itemId,
      (state) => state.status === "pending" && state.generation === generation,
      next,
    );

  const launchItem = (reviewId, kind, itemId, currentGeneration) =>
    writeItem(reviewId, kind, itemId, currentGeneration, {
      status: "pending",
      generation: currentGeneration + 1,
    });

  function saveSummary(reviewId, text) {
    const current = readRecord(reviewId);
    if (current.status !== "ok") {
      throw new Error(`Cannot update review "${reviewId}" (${current.status}).`);
    }
    const updated = Object.assign({}, current.review, {
      reviewerSummary: text,
      editedISO: store().nowISO(),
    });
    const validated = validateRecord(updated);
    writeRecord(validated);
    return validated;
  }

  function deleteReview(id) {
    store().storage.removeStrict(reviewKey(id));
    const index = readRawIndex();
    if (index.status === "ok") {
      store().storage.writeJSON(
        INDEX_KEY,
        index.entries.filter((entry) => bestEffortId(entry) !== id),
      );
    }
  }

  window.pcnReviews = {
    REVIEW_SCHEMA_VERSION,
    INDEX_KEY,
    reviewKey,
    RETRYABLE_CODES,
    TERMINAL_CODES,
    KINDS,
    ReviewInvariantError,
    checkRecord,
    createReview,
    listReviews,
    getReview,
    writeItem,
    writeResult,
    launchItem,
    saveSummary,
    deleteReview,
    items,
    itemState,
    isRetryableErrorState,
  };
})();
