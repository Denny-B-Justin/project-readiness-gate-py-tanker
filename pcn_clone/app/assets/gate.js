/* pcnGate: the client-side check behind gated pages (see pcn_clone/app/gate.py).
 *
 * A gated page sends a request {type, id, expect, fields}. `check` looks the
 * record up with the lookup registered for `type`, requires every `expect`
 * field to match, and answers {status: "ok", record} with only the requested
 * `fields`, or {status: "not_found"}. A lookup that finds a record it cannot
 * read returns `pcnGate.unreadable(message)`, answered as {status:
 * "unreadable", message}. Lookups live in `pcnGate.lookups`; a page gated on
 * another record type registers its own there.
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const isPlainObject = (value) =>
    typeof value === "object" && value !== null && !Array.isArray(value);

  /** Lookups by record type: each takes an id and returns the record, null,
   *  or an `unreadable(message)` answer. */
  const lookups = {
    project: (id) => window.pcnStore.getProject(id),
  };

  /** A lookup's answer for a record that exists but cannot be read. */
  class Unreadable {
    constructor(message) {
      this.message = message;
    }
  }
  const unreadable = (message) => new Unreadable(message);

  /** The gate's answer for one request. */
  function check(request) {
    if (!isPlainObject(request)) return { status: "not_found" };
    const lookup = lookups[request.type];
    const id = request.id;
    const record = typeof lookup === "function" && typeof id === "string" && id ? lookup(id) : null;
    if (record instanceof Unreadable) return { status: "unreadable", message: record.message };
    const expect = isPlainObject(request.expect) ? request.expect : {};
    if (!record || Object.keys(expect).some((key) => record[key] !== expect[key])) {
      return { status: "not_found" };
    }
    const picked = {};
    for (const field of Array.isArray(request.fields) ? request.fields : []) {
      if (Object.prototype.hasOwnProperty.call(record, field)) picked[field] = record[field];
    }
    return { status: "ok", record: picked };
  }

  window.pcnGate = { lookups, check, unreadable };

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.pcnGate = { check };
})();
