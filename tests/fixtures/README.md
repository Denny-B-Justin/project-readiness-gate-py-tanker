# Golden fixtures

The JSON files here are the frozen contract the core and AI layers are
tested against: the serialized Concept Note and its digest, validation and
calculation results for a range of answers, and the exact prompts and JSON
schemas sent to the model. They cover template `pcn_global` 1.5.0 and the
default project `upper_valley_district_road` 1.0.0.

Nothing in this repository generates them, and they are not meant to be
edited: a change to a fixture is a change to the contract. The serializer,
the prompts and the schemas must reproduce them byte for byte.
`tests/helpers.py` loads them, and a missing file fails the run at
collection time.

| File | Pins |
| --- | --- |
| `serialized_default.json`, `serialized_blank.json` | canonical answers, the 19 serialized fields and the `aiv1-` digest |
| `prepare_cases.json` | 77 per-field validation and serialization cases |
| `number_cases.json` | amount parsing and formatting |
| `worksheet_calc.json` | the 4.1 cost worksheet derived from the 3.2 scope list |
| `scenario_calc.json` | the 4.2 and 4.3 scenario tables |
| `mca_cases.json` | weighted MCA summaries and bands |
| `quote_cases.json` | evidence-quote normalisation and verification |
| `content_check.json` | versions, field order, scale, bands and weights of the content |
| `prompts/field_prompts.json` | the system and user prompt for each of the 19 fields |
| `prompts/assessment_prompts.json`, `prompts/mca_prompts.json` | the prompts for the 5 dimensions and the 4 criteria |
| `prompts/schemas.json` | the three strict JSON schemas, their wire formats and the shared constants |

## Encoding

- An expected error is `{"error": "<message>"}`. Messages are exact, except
  that a non-string input in `number_cases.json` is recorded with an
  engine-specific message and means only "raises".
- JSON cannot carry `-0`, `NaN` or `Infinity`. Negative zero is recorded as
  `0`; no value is `NaN` or `Infinity`.
- Strings are raw UTF-8. Invisible characters such as NBSP, U+FEFF and
  U+2028 appear literally, never as `\u` escapes.

## Serialized submissions

`serialized_default.json` and `serialized_blank.json` share one shape:

```
{
  "templateId": "pcn_global",
  "canonicalAnswers": [{"sectionId", "fieldId", "answer"}, ...],
  "fields": [{"sectionId", "sectionLabel", "fieldId", "fieldLabel", "serializedText"}, ...],
  "document": null,
  "digest": "aiv1-<sha256 hex>"
}
```

- `canonicalAnswers` has exactly one entry per template field, in template
  order. Unanswered fields carry the blank value of their kind: `""` for
  text and textarea, `{}` for group, `[]` for list,
  `{"componentCosts": {}, "narratives": {}}` for worksheet,
  `{"rows": {}, "narratives": {}}` for scenario comparison and
  `{"rows": {}}` for static table.
- `fields` are the 19 serialized fields. Labels are
  `"<section.number>. <section.title>"` and `"<field.number> <field.title>"`.
  A structurally blank answer (`null`, whitespace only, or a container whose
  values are all blank ignoring `_rowId`) renders `No answer provided.`.
  Otherwise the per-field preparer runs with the whole canonical answer list
  as context: valid text renders as is, whitespace-only text renders
  `No answer provided.`, and an invalid answer renders
  `This answer is structurally invalid and could not be rendered:` followed
  by one `- <message>` line per issue.
- `document` is `null`: there is no standalone document string. The document
  is built inline in the assessment and MCA user prompts (see
  `prompts/assessment_prompts.json`): `## <sectionLabel> (sectionId: <id>)`
  once each time the section changes, then each field as
  `### <fieldLabel> (sectionId: <s>, fieldId: <f>)\n"""\n<serializedText>\n"""`,
  with parts joined by `"\n\n"`.
- `digest` is `"aiv1-" + sha256_hex(utf8(json))`, where `json` is the compact
  array of `[fieldId, serializedText]` pairs with no spaces and non-ASCII
  characters unescaped, as `json.dumps(pairs, ensure_ascii=False,
  separators=(",", ":"))` produces.
- The blank submission is a single empty `project_title` answer, the minimum
  a submission may hold. Canonicalization fills the other 18 fields and every
  field renders `No answer provided.`.

## prepare_cases.json

77 cases of `{name, sectionId, fieldId, kind, answer, context, result, raw,
submissionSerializedText}`.

- `result` is `{ok, serializedText, issues}` from the per-field dispatcher
  that both the evaluate request and the submission use: `serializedText` is
  set and `issues` is empty when `ok`; otherwise `serializedText` is `null`
  and `issues` lists the messages.
- `kind` is the field's input type, or `"textarea"` for the nine fields that
  declare no input.
- `raw` is the dedicated validator's own structured result for list,
  worksheet, scenario and static-table fields, with issues keyed by item,
  row, column, narrative or applicability id; an ok worksheet also carries
  its derived rows and grand total. It is `null` for text, textarea and
  group, which serialize directly and never fail.
- `submissionSerializedText` is what the submission serializer renders for
  the field when the case answer replaces the default project's. For a
  worksheet case the 3.2 list is replaced by the case's context entry, or by
  `[]` when `context` is `null`.
- `answer` is the stored answer value as a draft or submission holds it.
  Text, textarea and group answers reach the evaluate request already
  serialized to a string, which the dispatcher returns unchanged; one case
  covers that.
- `context` is used only by the 4.1 worksheet and holds the 3.2 list as
  `[{"sectionId": "project_description_and_impact", "fieldId":
  "scope_of_the_project", "answer": <list>}]`. It is `null` otherwise.
- Blank text, textarea and group answers are `ok` (group 1.3 serializes to
  `"Project Start Date: \nEstimated Project Completion Date: "`); the
  no-answer marker exists only at the submission layer. Blank list,
  worksheet, scenario and static-table answers are not `ok`.
- Coverage: every field's default answer; a blank answer of every kind and
  whitespace-only text; group with one control blank, one key absent, and
  the pre-serialized string; list 3.2 items with and without `_rowId` and a
  non-array answer; list 5.1 invalid select values, the likelihood × impact
  ≥ 4 rule at its boundary with blank and present measures, and forged
  numeric and null cells; worksheet 4.1 with a missing start date, negative,
  non-numeric and missing amounts, a missing narrative and category, decimal
  and exponent amounts, a stale cost key, no context, and duplicate and
  missing source row ids; scenario 4.2 with missing and absent cells,
  negative and invalid values and a missing narrative; scenario 4.3 with the
  gate `"no"`, unanswered, invalid, `"yes"` with a missing row, and `" yes "`
  (validation trims it, applicability does not); static 6.1 and 6.2 with
  required `"no"`, a missing required column, an invalid status, and comment
  normalisation.

## number_cases.json

`parseAmount`, `formatAmount`, `parseScenarioAmount`, `formatScenarioAmount`
and `toAmount`, each a list of `{input, result}`.

`parseAmount` (worksheet) returns `{ok: true, value}` or `{ok: false, reason:
"not_a_number" | "negative"}`. `parseScenarioAmount` returns
`{present: false}`, `{present: true, ok: true, value}` or `{present: true,
ok: false, reason}`. `toAmount` is the parsed value, or 0 when not ok.

- Input is trimmed first. Blank gives `{ok: true, value: 0}` from
  `parseAmount` (blank is zero) and `{present: false}` from
  `parseScenarioAmount` (blank is absent). `null` counts as blank.
- Parsing follows JavaScript `Number()` semantics, then a finiteness check,
  then `< 0` is `negative`. Python's `float()` differs, so the parser is
  explicit. Accepted: `"1e3"`, `"0x10"`, `"0b101"`, `"0o17"`, `"+5"`,
  `".5"`, `"5."`, `"00012"`, `"1e-7"`, `"1e21"`, and surrounding whitespace
  including NBSP and U+FEFF. `not_a_number`: `"1,000"`, `"1_000"`,
  `"1 000"`, `"abc"`, `"NaN"`, `"Infinity"`, `"-Infinity"`, `"1e400"`,
  `"-0x10"` (signed hex), and Arabic-Indic digits. `"-0"` is accepted as
  zero. `"-5"` is `negative`.
- A non-string input is recorded as an error and must raise.
- Formatting rounds to two decimals with halves toward +∞
  (`floor(x * 100 + 0.5) / 100`, not banker's rounding), prints an
  integer-valued result without decimals and any other with exactly two, and
  inserts thousands separators. Pinned consequences: `12.345` → `12.35`,
  `1.005` → `1`, `2.675` → `2.68`, `0.125` → `0.13`, `-0.125` → `-0.12`,
  `-2.5` → `-2.50`, `-0.005` → `0` (never `-0`), `999.995` → `1,000`,
  `1e20` → `100,000,000,000,000,000,000`, and `1e21` →
  `999,999,999,999,999,900,000` (the integer part prints the shortest
  round-trip digits padded with zeros, not the exact binary value).

## worksheet_calc.json

The default project's 4.1 worksheet against its 3.2 list: `rows` (per source
row: `rowId`, `component`, `cost_category`, the raw `amounts` as entered with
`""` for an absent key, `rowTotal`, `amountValues`, `startDate`,
`startYear`, `hasStartDate` and `sourceItem`), `countedRowIds`,
`grandTotal`, `categorySummary` (`{columns, rows, grandTotal}`),
`yearLabels` (`null`), `requiredCostControlIds`, `derivedRows` and
`variants`.

- A row is counted if and only if its start date has a leading 4-digit year;
  category validity is not part of the rule.
- Year labels are not stored: the required cost control at index `i` is
  labelled `startYear + i` (for example `Year 1 (2026)`), and the optional
  `subsequent_years` gets no year label.
- `variants` are `{name, sourceAnswer, worksheetAnswer, derivedRows,
  rowTotals, countedRowIds, grandTotal, categorySummary}`: a cleared and an
  unparseable start date (costs not counted), an uncategorised row (in
  `grandTotal` but not in `categorySummary.grandTotal`), invalid amounts
  summing as zero, decimal amounts (`1234.867`), a stale component key, and
  no source rows.

## scenario_calc.json

`defaults` holds, for `operating_costs` (4.2) and `revenues` (4.3), the
default answer, `applicable`, and the `computedRows` (`{rowId, label,
subtract, cells: {columnId: {present, value}}}`). `computedCellCases` and
`isApplicableCases` pin the rules:

- A computed cell is `left − right`, present only when both cells are
  non-blank, finite and non-negative; otherwise it is `{present: false,
  value: null}`. The difference itself may be negative, and floats are plain
  IEEE arithmetic (`0.3 − 0.1 = 0.19999999999999998`).
- 4.2 is always applicable. 4.3 is applicable only when
  `answer.applicability.revenue_expected` is exactly `"yes"`: no trim, case
  sensitive.

## mca_cases.json

`[{name, scores: {criterionId: number}, result}]`, where `result` is the
summary `{rows: [{criterionId, label, weight, score, weightedPoints}],
totalWeightedPoints, maxWeightedPoints, percentOfMaximum, band: {id, label,
minPercentOfMaximum}}` or `{"error": msg}`. Weights are 30/30/20/20 on a
1 to 5 scale, so the maximum is 500.

- `percentOfMaximum = (totalWeightedPoints / maxWeightedPoints) * 100` at
  full precision, in that order: 290 points give `57.99999999999999`, while
  400 and 300 give exactly `80` and `60`.
- `band` is the first band whose threshold the percentage meets: high at 80,
  medium at 60, low at 0.
- Errors: a missing or unknown criterion, and scores of 0, 6 and 2.5.

## quote_cases.json

`normalize` cases (`{name, input, output}`) and `verify` cases (`{name,
quote, fieldText, verified}`).

- Normalisation is NFC, then every run of whitespace collapsed to one space,
  then a trim. The whitespace class is JavaScript's `\s`, which differs from
  Python's: U+FEFF is whitespace here but not in Python, and U+0085 and
  U+001C–U+001F are whitespace in Python but not here; U+200B and U+180E are
  in neither. The same class governs every trim in the validators and
  parsers.
- NFC composes (`e` + U+0301 → `é`, U+212B → `Å`) and does not apply
  compatibility folding (`ﬁ` and `①` are unchanged).
- Verification is a case-sensitive substring test of the normalised quote in
  the normalised field text; an empty or whitespace-only quote is `false`.
  Five cases use real serialized text from `serialized_default.json`.

## prompts/

- `field_prompts.json`: `{fieldId: {system, user, sectionId}}` for all 19
  fields with the default project's answers. `system` is the base prompt
  followed by `"\n\nTemplate-specific guidance (how to communicate; does not
  override the rubric or the required output):\n"` and the trimmed template
  guidance. `user` holds the field number and title, the guidance, the
  criteria label (`Quality rubric` when there is none) with the Fail / Not
  Clear / Pass descriptors, and `## Proposer's answer\n"""\n<answer or "(no
  answer provided)">\n"""`.
- `assessment_prompts.json`: `{dimensionId: {system, user}}` for the 5
  dimensions. `mca_prompts.json`: `{criterionId: {system, user}}` for the 4
  criteria. Both embed the default submission. The MCA wrapper says "does not
  override the **descriptors** or the required output" where the assessment
  wrapper says "rubric".
- `schemas.json`: the three strict schemas (`fieldEvaluation`,
  `assessmentFinding`, `mcaScoreFinding`), their `formatNames`
  (`field_evaluation`, `assessment_finding`, `mca_score_finding`), the full
  wire formats under `textFormats` (`{type: "json_schema", name, strict:
  true, schema}`), the shared `constants`, and `protocolParts`, the inputs
  of the `arv1-` and `mrv1-` revision hashes. The schemas are draft-07 and
  reuse repeated sub-schemas by `$ref` into a top-level `definitions` block;
  reproduce that exactly when hashing or comparing. The citation list is an
  `anyOf` with one branch per section, each with `sectionId` as a `const`
  and `fieldId` as an `enum`. The MCA `basis` is an `anyOf` of `documented`
  (integer score 1 to 5, 1 to 3 evidence items) and `not_evidenced` (score
  `const` 1).

### Constants

| Constant | Value |
| --- | --- |
| quote maximum length (assessment and MCA) | 300, and non-blank after trimming |
| MCA justification maximum length | 600, non-blank |
| MCA citations per documented score | 1 to 3 |
| verdicts | `fail`, `notClear`, `pass`, shown as Inadequate, Concerns, Adequate |
| MCA basis kinds | `documented`, `not_evidenced` |
| no-answer marker | `No answer provided.` |
| invalid marker | `This answer is structurally invalid and could not be rendered:` then `\n- <message>` per issue |
| prefixes | `aiv1-` input digest, `arv1-` assessor revision, `mrv1-` MCA revision |
| row id key | `_rowId` |
| inert static-table value | `no` |

Inner markers that appear inside serialized text: `(no answer provided)` for
a blank narrative, `(not provided)`, `(invalid)` and `(not computable)` for
scenario cells, `(unnamed component)`, `(none selected)`, `(no components
listed)` and `(no start date in section 3.2 — costs not entered)` for the
worksheet, `—` for a blank static-table cell and `n/a` for an inert one, and
`The proposer indicated this is not applicable; no scenario figures are
expected for this field.` for a scenario gated off.

## content_check.json

Versions (`templateVersion` 1.5.0, `criteriaVersion` 1.4.0,
`assessmentVersion` 0.3.0, `mcaVersion` 0.1.0); the ids of the template,
criteria, assessment and MCA sets and the default project; `sections`;
`fieldOrder` (`{sectionId, fieldId, kind, declaredInputType, number, title}`,
with `kind` `"textarea"` where no input is declared); the five
`dimensionIds`; the four `criterionIds`; the `scale` (`min`, `max`,
`entries`); the `bands`; the `weights`; the `assessorRevision` and
`mcaRevision` hashes; and `defaultInputDigest`.
