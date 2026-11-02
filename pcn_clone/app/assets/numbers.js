/* pcnNumbers: amount parsing and formatting for the live form figures.
 *
 * The same rules as pcn_clone.core.numbers, so a total shown while typing
 * equals the one the server serializes:
 *   - an entered amount is read with Number() after trimming; blank is zero
 *     in the worksheet and absent in a scenario comparison; anything not
 *     finite is rejected as "not_a_number", anything below zero as
 *     "negative";
 *   - formatAmount rounds half up at the cent (Math.round(value * 100) /
 *     100), prints integers bare and everything else with two decimals, and
 *     groups thousands with commas.
 *
 * Plain ES2020, no build step. Dash serves it from /assets/.
 */
(function () {
  "use strict";

  const entered = (raw) => (typeof raw === "string" ? raw.trim() : "");

  function parseNonBlank(text) {
    const value = Number(text);
    if (!Number.isFinite(value)) return { ok: false, reason: "not_a_number" };
    if (value < 0) return { ok: false, reason: "negative" };
    return { ok: true, value };
  }

  /** A worksheet amount: blank is a valid zero. */
  function parseAmount(raw) {
    const text = entered(raw);
    return text === "" ? { ok: true, value: 0 } : parseNonBlank(text);
  }

  /** A scenario amount: blank is absent ({present: false}), not zero. */
  function parseScenarioAmount(raw) {
    const text = entered(raw);
    if (text === "") return { present: false };
    return Object.assign({ present: true }, parseNonBlank(text));
  }

  /** An amount for summation; blank or rejected entries count as zero. */
  function toAmount(raw) {
    const parsed = parseAmount(raw);
    return parsed.ok ? parsed.value : 0;
  }

  /** "1,234,567.89": integers bare, otherwise two decimals, half up. */
  function formatAmount(value) {
    const rounded = Math.round(value * 100) / 100;
    const fixed = Number.isInteger(rounded) ? String(Math.trunc(rounded)) : rounded.toFixed(2);
    const negative = fixed.startsWith("-");
    const unsigned = negative ? fixed.slice(1) : fixed;
    const [intPart, decPart] = unsigned.split(".");
    const grouped = (intPart || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return `${negative ? "-" : ""}${grouped}${decPart ? `.${decPart}` : ""}`;
  }

  window.pcnNumbers = { parseAmount, parseScenarioAmount, toAmount, formatAmount };
})();
