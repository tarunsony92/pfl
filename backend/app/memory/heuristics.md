# PFL Finance — Phase 1 Credit Heuristics (M5 stub, static)
# Managed by: Credit Head. Updated via M7 feedback distillation.
# Format: ## Heuristic: <name> blocks.

---

## Heuristic: CIBIL_BELOW_700_AUTO_REJECT

Any applicant or co-applicant with a CIBIL score below 700 is an automatic
hard-reject. No exceptions. If score is 0 (no credit history), treat as
CIBIL = 650 and apply the same rejection rule.

**Severity:** HARD_REJECT
**Applies to:** Step 1 (Policy Gates)

---

## Heuristic: HIGH_FOIR_ESCALATE

When FOIR (Fixed Obligation to Income Ratio) is between 40% and 50%, the
case should be flagged for enhanced review. Loan amount should be reduced to
bring FOIR under 40% before recommending approval. If FOIR exceeds 50%, the
case must be rejected unless co-applicant income materially reduces the ratio.

**Severity:** SOFT_WARNING (40-50%), HARD_REJECT (>50%)
**Applies to:** Step 8 (Reconciliation)

---

## Heuristic: ADDRESS_MISMATCH_INVESTIGATION

When fewer than 4 of 6 address sources match, the discrepancy must be
investigated. Common reasons: recent relocation, rural addresses without
pincodes, and PAN having an old employer address. A mismatch between GPS
coordinates and stated address is the most serious indicator of fabrication.

**Severity:** HARD_REJECT (match_count < 4)
**Applies to:** Step 5 (Address Verification)

---

## Heuristic: STOCK_VALUE_SANITY_CHECK

For kirana/retail businesses, stock value should be approximately 3–6 months
of turnover. If stated stock significantly exceeds this range, probe further.
Items priced far above market MRP suggest either double-counting or fictitious
inventory. A stock-to-loan ratio below 1.0 is a hard reject.

**Severity:** HARD_REJECT (ratio < 1.0), SOFT_WARNING (ratio 1.0–1.5)
**Applies to:** Step 7 (Stock Quantification)

---

## Heuristic: BANK_BOUNCE_PATTERN

More than 3 EMI/cheque bounces in the 6-month statement period is a strong
negative signal. Even if ABB is above the proposed EMI, recurring bounces
suggest cash-flow volatility. Escalate to CEO if bounce count > 3.

**Severity:** ESCALATE_TO_CEO (bounce_count > 3)
**Applies to:** Step 2 (Banking Check)

---

## Heuristic: BUSINESS_DISTANCE_LIMIT

Businesses located more than 25 km from the branch are outside the serviceable
area. GPS distance should be used when available; otherwise use stated address
to compute an approximate crow-fly distance. Urban branches in dense areas
should apply a 15 km soft-warning threshold.

**Severity:** HARD_REJECT (> 25 km)
**Applies to:** Step 6 (Business Premises)

---

## Heuristic: INCOME_BANK_VARIANCE

If the declared monthly income in the Auto CAM is more than 15% higher than
the Average Bank Balance / 3, there is a material discrepancy that must be
explained. Round-number deposits on the 1st or 15th of the month (suggesting
cash infusion) should be flagged.

**Severity:** HARD_REJECT (variance > 15%), SOFT_WARNING (10–15%)
**Applies to:** Step 8 (Reconciliation)

---

## NPA Patterns

The following patterns are associated with cases that became NPAs in the
historical portfolio. Step 11 should elevate risk assessment when multiple
patterns co-occur.

1. **Cash-infusion borrowers**: Round deposits of exactly the proposed EMI
   amount appearing in bank statement just before PD visit.
2. **Thin bureau file**: CIBIL score of exactly 700 (minimum threshold) with
   only 1–2 credit accounts and no repayment history beyond 12 months.
3. **Sole-trader businesses < 2 years old**: Higher default rate than
   established businesses. Require additional income proof.
4. **Multi-lender indebtedness**: Equifax showing 3+ active loans suggests
   the applicant is cycling debt. Scrutinize FOIR carefully.
5. **Address-income inconsistency**: Claimed high income but residential
   address is a shared room or chawl. Cross-check with electricity bill.

---
