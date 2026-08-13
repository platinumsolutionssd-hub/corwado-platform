# CORWADO Access Matrix — role × data-class (Phase 1 identity)

**Status: DRAFT for John's sign-off. Nothing implements until this is signed.**
This is the written contract the RLS/app-layer code in Phase 1 must implement — it
comes *before* any code. It extends the deployed tenancy model (RLS + `app.current_org`
/ `app.platform_admin`, see `SECURITY_resolver.md`) with the new **consultant** role.

## The boundary principle (unchanged, restated)

One org's tenant data is invisible to another org, enforced at the database by
Row-Level Security keyed on `organization_id = current_setting('app.current_org')`.
App-layer stamping is defence-in-depth, never the primary control. Every rule below
is *narrower or equal to* what RLS already enforces; the matrix never widens access
beyond the tenant boundary except where a role is cross-org **by explicit design**
(landlord bypass; consultant by per-org grant).

## Roles (grounded in the deployed mechanics)

| Role | What it is | Mechanism today |
|---|---|---|
| **Landlord** | Platform admin / vendor superadmin (Platinum Solutions). Cross-org by design. | `get_current_platform_admin`; token `typ=platform_admin`; sets `app.platform_admin='on'` → **full RLS bypass**. Never sets `org_id`. |
| **Staff** | An org's dashboard users + Telegram operators. Belong to exactly one org. | `get_current_staff`; token `typ=staff`; sets `app.current_org` only → RLS-confined to that org. `staff_account` + `authorized_operator`, both org-scoped. |
| **Consultant** | External advisor (agronomy / EUDR compliance) serving **many** orgs, each by that org's explicit, revocable grant. **NEW — not yet built.** | To be designed this phase. Cross-org, but per-org-scoped and read-mostly — NOT a landlord bypass. |
| **Static visitor** | Marketing / demo view over **canned sample data**. Mode 2A. | Never touches Postgres. No org, no auth. Isolation by construction. |
| **Live visitor** | DB-free live agri-venture / FarmLab tool on ad-hoc input. Mode 2B. | Runs live GEE analysis on the visitor's own input; **writes nothing** to the tenant DB. No org, no auth. |

## Data classes (grounded to tables)

| Data class | Tables (schema.sql) |
|---|---|
| **Org registry data** | `cooperative`, `buyer`, `buyer_posting`, `agro_dealer`, `radio_station`, `radio_broadcast_slot`, `price_board_entry`, `aggregation_event/contribution`, `message_dispatch`, `organization` |
| **Parcels / geometry** | `parcel`, `parcel_draw_token`, `land_steward`, `season_planting` |
| **Compliance outputs / deforestation reports** | FarmTrace outputs (validator + deforestation). **No table yet** — the registry (2.3) will store these; today they are computed, ephemeral artifacts. |
| **Financial / BoQ** | `input_requirement`, `input_financing_record` |
| **Operator identity (PII)** | `authorized_operator`, `staff_account`, `land_steward` contact fields, `inbound_message` (phone/handle) |

## The matrix

Legend: **RW** read+write · **R** read · **R×** read cross-org · **—** no access ·
**R (grant)** read only where the org has granted this consultant · **(ephemeral)**
computes but persists nothing to the tenant DB.

| Data class | Landlord | Staff (own org) | Consultant (granted org) | Static visitor | Live visitor |
|---|---|---|---|---|---|
| **Org registry data** | RW× (platform mgmt) | RW | R (grant) | — (canned sample only) | — |
| **Parcels / geometry** | R× (support) | RW | R (grant) | — | (ephemeral) |
| **Compliance outputs / deforestation reports** | R× | RW | **R (grant)** — the consultant's primary purpose | — | (ephemeral) |
| **Financial / BoQ** | R× (support) | RW *(edit staff-only, always)* | **— never** | — | — |
| **Operator identity (PII)** | R× (support) | R *(manage = org-admin, see decision 3)* | **— never** | — | — |

### Cell rationale (the non-obvious ones)

- **Consultant never sees Financial/BoQ or Operator PII.** Least privilege: an advisor
  reviewing land/compliance has no need for who-financed-what or operators' phone
  numbers. This also keeps the consultant clear of the BoQ firewall (BoQ is
  record-keeping, never a creditworthiness signal — a consultant reading it invites
  exactly the inference the firewall forbids).
- **Consultant's home is Compliance outputs + Parcels.** That is the whole reason the
  role exists — an EUDR/agronomy advisor reads a client org's plots and their
  deforestation/validator reports, and nothing else.
- **Staff BoQ is RW but edit-only-by-staff** regardless of how the farmer record was
  created (carried from PROJECT_STATE §6 — this boundary does not move).
- **Live visitor "(ephemeral)"**: it can run the live deforestation/diagnostic tool on
  its own drawn geometry and see a result, but that computation touches no org's
  stored parcels or reports. It is outside the tenant system entirely.

## Consultant mechanics (the locked decisions, made concrete)

1. **Request → approve → revoke.** A consultant *requests* access to an org; the org
   *approves*; the grant is *revocable* by the org at any time. A revoked grant
   removes all access immediately (no cached tokens outliving it — grant state checked
   per request, not baked into a long-lived JWT).
2. **One consultant, many orgs.** A single consultant principal holds N independent
   per-org grants. Access to org A is scoped to org A's data only — the consultant is
   never cross-org *in aggregate*; they are the union of individually-granted single-org
   views. Mechanically this is **NOT** `app.platform_admin` (that would leak all orgs);
   it is a per-request `app.current_org` set to the *granted* org after checking an
   active grant row exists — the same RLS path staff use, gated by a grant table.
3. **John's dual role = a separate client-org record.** John-as-landlord (platform
   superadmin) and John-as-consultant (advising a client org) are **distinct
   principals with distinct tokens**. His consultant access to any client org goes
   through the ordinary request→approve→revoke grant — it must NOT ride on his landlord
   bypass. This is the one place the two token types must be provably non-crossing.

Proposed new state (for the RLS design that follows sign-off): a
`consultant_account` identity table (org-independent) + a `consultant_grant`
(`consultant_id`, `organization_id`, `status`, `granted_at`, `revoked_at`) join,
with a `get_current_consultant` dep that sets `app.current_org` to the grant's org
only after verifying an `active` grant — never `app.platform_admin`.

## Open decisions — resolve these when you sign

1. **Consultant grant scope: fixed bundle vs org-configurable.** The matrix proposes a
   *fixed* least-privilege bundle (parcels + compliance + registry read; never BoQ/PII).
   Alternative: let the granting org choose, per grant, which data classes to share.
   **My recommendation: fixed bundle for v1** — simpler to reason about and audit; add
   per-class opt-in later only if a real org asks. Financial/BoQ and Operator PII stay
   *never*, regardless, in either option.
2. **Landlord: mechanism vs policy.** The landlord is full RLS bypass — mechanically it
   is RW on every table in every org. The matrix's "R× (support)" for tenant
   operational data is a *policy* intent, **not RLS-enforceable** (bypass is
   all-or-nothing). Options: (a) accept full-bypass landlord for platform management and
   constrain write-behaviour app-layer/procedurally; (b) add a separate read-only
   support-admin token type for cross-org read without write. **My recommendation: (a)
   for now**, documented plainly, revisit if a support team beyond you ever exists.
3. **Is there an org-admin among staff?** "The org approves" a consultant grant — *which*
   staff member? And who manages operators / sees the org's own settings? Today all
   staff look equal, and *self-onboarding* is **landlord**-approved (per the tenancy
   record), not org-approved. Consultant grants being **org**-approved implies an
   **org-admin staff sub-role**. **Decision needed:** introduce an org-admin staff flag
   (approves consultant grants, manages operators), or route consultant-grant approval
   through the landlord like onboarding? **My recommendation: introduce an org-admin
   flag** — consultant access is the org's call to make, not the platform's, and it
   keeps the landlord out of per-org trust decisions.
4. **Grant durability / audit.** Should grants expire automatically (e.g. 12-month
   review) or persist until revoked? For a lender-grade audit trail I lean toward
   *persist-until-revoked + a logged review date*, but flag it for your call.

---
*Once signed, the RLS/app-layer implementation (consultant_account, consultant_grant,
get_current_consultant, and the org-admin flag if decision 3 lands that way) is the
next gated stage. This document is the contract that stage implements.*
