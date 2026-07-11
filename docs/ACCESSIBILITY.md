# Accessibility Design Commitments

Written to close a real gap: the original technical proposal named
gender, literacy, and voice-access as inclusion priorities, but did not
make specific commitments for persons with disabilities — even though
the ToR names this explicitly. This document is the concrete answer,
meant to sit alongside the user/administrator manuals promised in
ToR Phase 6.

## Farmer-facing channels

The platform already routes each farmer to their own preferred channel
(`land_steward.preferred_channel`), and every dispatched message is
tagged with a `content_format` matched to that channel:

| Channel | Content format | Who this serves |
|---|---|---|
| IVR | Audio script (spoken) | Farmers who cannot read, including visual impairment |
| Radio | Audio script (spoken) | Farmers with no phone, or with hearing but not literacy |
| SMS / USSD | Short text | Farmers with basic phones and functional literacy |
| WhatsApp | Pictorial + short text | Farmers with smartphones, mixed literacy |

`land_steward.has_disability` and `disability_notes` (free text, e.g.
"visual impairment — prefers IVR") let a Digital Champion record
relevant context at registration, without requiring a formal diagnosis
or category — CORWADO staff can filter by this flag
(`GET /api/stewards?has_disability=true`) to check outreach is actually
reaching this group, not just assume it is.

**Commitment for Days 12-14 (dashboard build):** the registration form
must let a Digital Champion set `preferred_channel=ivr` and
`has_disability=true` together in one flow, not as a buried option —
accessibility needs to be as easy to record as a phone number.

## CORWADO staff-facing dashboard

These are commitments for the React dashboard build (Days 12-14), not
yet implemented — recorded here so they don't get silently dropped once
we're focused on visual polish:

- **Keyboard navigation**: every action reachable via keyboard alone, no
  mouse-only interactions.
- **Screen-reader compatibility**: semantic HTML, ARIA labels on icons
  and status indicators (the channel badges, severity icons, etc. in
  the Day 1 demo currently rely on icon + color alone — this needs
  text alternatives before it's a real deliverable, not just a demo).
- **Contrast**: WCAG AA minimum (4.5:1 for body text) — the demo's sand
  background / charcoal text pairing was chosen to meet this, needs
  verification once real content replaces demo copy.
- **No color-only signaling**: severity/status shown with icon + label,
  not color alone (partially true in the Day 1 demo — needs a pass).
- **Reduced motion respected**: no animation that can't be disabled.

## What's still open

- Exact WCAG conformance level (AA vs AAA) — worth confirming with
  CORWADO during Phase 2 needs assessment rather than assuming, since
  it affects build time.
- Sign language or captioned video for any training video content —
  not yet scoped; flag during needs assessment if CORWADO's Digital
  Champions cascade will include deaf trainees.
- This document itself should be reviewed against CORWADO's own
  safeguarding/inclusion policy (ToR Section 8.1.6) once shared —
  we don't have that document yet.
