# Security boundary — session-less inbound org resolver (migration 004)

## The problem it solves
Inbound Telegram/WhatsApp messages arrive with no logged-in staff, hence no
`app.current_org`. To scope them under RLS we must first resolve the sender's
chat_id/phone to an organization — but the identity tables
(`authorized_operator`, `land_steward`) are `FORCE`-RLS, so a no-context
session cannot read them. The resolver needs a narrow, **context-free read**
of exactly those two tables, returning only `(organization_id, org_status)`.

002's answer was a `BYPASSRLS` role owning `SECURITY DEFINER` functions.
Creating a `BYPASSRLS` role requires `SUPERUSER`; Render's owner
(`corwado_platform_user`) is `NOSUPERUSER`, so 002 cannot be deployed. 004
delivers the same read window without any superuser-only object.

## Chosen mechanism — role-scoped permissive policy (refined Mechanism A)
- `corwado_resolver`: a plain `NOLOGIN`, **NON-`BYPASSRLS`** role (a `CREATEROLE`
  owner can create it).
- The two resolver functions are `SECURITY DEFINER`, **owned by
  `corwado_resolver`**, so they execute as that role.
- A permissive policy `resolver_read FOR SELECT TO corwado_resolver
  USING (true)` on `authorized_operator` and `land_steward`. `FORCE` RLS stays
  on every table.
- `corwado_app` receives `EXECUTE` on the two functions (PUBLIC execute is
  revoked) and nothing else.

Because `resolver_read` is scoped `TO corwado_resolver`, it applies only while
code runs as that role — i.e. only inside the two functions. Every other role,
including `corwado_app`, sees only the ordinary `tenant_isolation` policy.

## The required comparison: compromised `corwado_app` vs. the BYPASSRLS design
Under **both** designs a compromised `corwado_app` connection can:
- EXECUTE `resolve_chat_org` / `resolve_phone_org` for arbitrary keys, learning
  `(org_id, status)` for a supplied chat_id/phone. Identical signatures and
  bodies in both designs.

Under **neither** design can it:
- Read rows from `authorized_operator` or `land_steward` beyond its own org.
  BYPASSRLS: `corwado_app` has no bypass and no policy granting cross-tenant
  read. 004: `resolver_read` is `TO corwado_resolver`, which `corwado_app` is
  not — it gets only `tenant_isolation`.

**Verdict: `corwado_app` can do nothing more under 004 than under the BYPASSRLS
design.** The one residual capability — an EXECUTE-holder can probe "does key X
belong to org Y?" — is identical in both and is the intended, minimal contract
of the functions (they return a single org id + status, nothing else).

## Why NOT the GUC-keyed variant of Mechanism A
A permissive policy keyed on `current_setting('app.resolver_mode', true) = 'on'`
(not role-scoped) is **weaker than BYPASSRLS**, and the weakness is *not* fixable
by session-variable hygiene:
- Custom GUCs like `app.resolver_mode` are settable by **any** role, including
  `corwado_app`. A compromised `corwado_app` could run
  `SET app.resolver_mode='on'; SELECT * FROM land_steward;` and dump every
  tenant — something the BYPASSRLS design never permitted.
- Making the functions set the GUC transaction-locally (`set_config(...,true)`,
  or a function-local `SET` clause that auto-resets even on exception) closes
  the **leakage** problem (the setting cannot outlive the function/transaction)
  but does **not** close this **self-activation** problem: nothing stops
  `corwado_app` from setting the GUC itself.
- Once the policy has to be role-scoped (`TO corwado_resolver`) to be safe, the
  GUC is redundant — role-scoping alone is the boundary. So 004 uses role
  scoping and **no GUC**, removing the pooled-connection leakage surface
  entirely. This is why the session-variable "non-negotiable" is satisfied by
  elimination rather than by hygiene.

## Why NOT Mechanism B (drop FORCE on the two lookup tables)
Dropping `FORCE` on `authorized_operator`/`land_steward` makes the table
**owner** RLS-exempt on them. Honest cost: any code running as the owner gets
unrestricted cross-tenant read on the two most identity-sensitive tables in the
system. The deployed app **currently connects as the owner**, so B would make
the entire live application bypass isolation on exactly those tables. Even after
the app is moved to `corwado_app` (Stage 5), the owner credential — still used
for migrations/admin — would retain blanket read. 004 keeps `FORCE` everywhere
and confines the cross-tenant read to one `NOLOGIN` role reachable only through
two functions that each return a single org id. **B is retained only as a
fallback** if Stage 3 shows a `CREATEROLE`/`NOSUPERUSER` owner cannot own
functions with `corwado_resolver`.

## Stage-5 connection role and cutover ordering

**1. Which role does the deployed app connect as under 004? → `corwado_app`.**
Not the owner. Two reasons, both intrinsic to this design:
- *Isolation:* `corwado_app` is `NOSUPERUSER`/`NOBYPASSRLS` and owns nothing, so
  it is fully subject to `tenant_isolation` on every table. The owner role
  (`corwado_platform_user`) has table/schema DDL power and is the one role
  whose exemption we would ever have to reason about; keeping it out of the
  request path is the whole point of a restricted app role.
- *Mechanics:* 004 revokes EXECUTE on the resolvers from PUBLIC and grants it
  **only to `corwado_app`**. The owner therefore cannot even call
  `resolve_chat_org`/`resolve_phone_org`. An app connecting as the owner would
  fail the inbound seam outright. So `corwado_app` is not merely preferred — it
  is the only role the new code can connect as and still function.

**2. Does the OLD deployed code work if we just point `DATABASE_URL` at
`corwado_app`? → No. It must be one cutover event with the new-code deploy.**
The currently-deployed pre-multi-tenancy code sets no `app.current_org`. As
`corwado_app` (RLS-subject, non-owner) with no context it gets exactly what it
gets today as the owner: **0 rows on every read, WITH CHECK failure on every
write.** There is no safe intermediate state — flipping `DATABASE_URL` alone
just moves the breakage sideways. Both changes have to land in the same deploy:
the new code (which sets context via auth + the resolver) **and** the
`corwado_app` connection string, together.

**Exact Stage-5 ordering (unambiguous for the dashboard step).** By Stage 5 the
migrations (004, 003) are already applied to prod (Stage 4). Then:
1. Auto-Deploy stays **OFF** (so nothing ships mid-configuration).
2. Claude: `git push origin master` — new code + the 004 file reach GitHub, undeployed.
3. John, in the Render dashboard, sets **both** env vars and saves:
   `JWT_SECRET=<value>` and `DATABASE_URL=<corwado_app internal connection string>`.
4. John triggers **Manual Deploy → "Deploy latest commit"** (the just-pushed new code).
   Because the env vars are already set, the new code boots with `JWT_SECRET`
   present **and** connecting as `corwado_app` — both changes live in one deploy.

Do **not** rely on the env-var save alone to ship the new code: with Auto-Deploy
off it would redeploy the *old* commit as `corwado_app`, which is still broken.
The explicit "Deploy latest commit" after the env vars are set is what makes it a
single, correct cutover. (Test-only data + ~no live users, so the brief window is
a non-event — correctness of ordering matters, not speed.)

## Inbound write path, end to end (Fork A)
`inbound_message`/`parcel_draw_token` are relaxed to RLS-exempt + nullable
`organization_id`. Flow: message arrives → `corwado_app` calls `resolve_chat_org`
→ gets `org_id` → sets `app.current_org` → the `inbound_message` insert succeeds
(no NOT NULL bar, org stamped when known, NULL when the sender is unrecognised).
This is what fixes the write-path break Stage 1 confirmed.

## What Stage 3 must prove (as the Render-equivalent NOSUPERUSER owner)
1. A `CREATEROLE`/`NOSUPERUSER` owner can: `CREATE ROLE corwado_resolver`
   (plain), `ALTER FUNCTION … OWNER TO corwado_resolver`, `CREATE POLICY … TO
   corwado_resolver`, and manage the EXECUTE grants — **all without superuser**.
2. Functionally: the resolver returns the right org for a known chat_id; an
   `inbound_message` insert then succeeds under that org context; and a second
   org's context still cannot read the first's rows.

If step 1 fails at `ALTER … OWNER` or the grant (a role-membership limitation),
fall back to Mechanism B with the cost stated above.
