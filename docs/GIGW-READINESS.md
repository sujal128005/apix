# GIGW 3.0 readiness

**Assessed 12 September 2026.**

GIGW 3.0 carries **88 mandatory checkpoints** across four domains — Quality (25),
Accessibility (50, adopted from WCAG 2.1 Level AA), Cybersecurity (3 core areas
under CERT-In advisories), and Lifecycle Management (10 policies). Certification
is by STQC as a **Certified Quality Website**, with cybersecurity established
through a **"safe to host"** certificate from a CERT-In or STQC empanelled
auditor.

*Verify the current edition against `guidelines.india.gov.in` before an audit is
scheduled. This assessment was written from the published summary of GIGW 3.0,
not from the certification checklist itself.*

---

## The division that matters

Most of GIGW is **not a software problem**, and reading it as one is the fastest
way to arrive at an audit unprepared.

| Domain | Ours | The ministry's |
|---|---|---|
| Quality | Responsive layout, navigation, load time, consistent presentation | Content policy, information architecture sign-off, uniform branding |
| Accessibility | WCAG 2.1 AA in markup, colour, keyboard and structure | Accessible content authoring, the accessibility statement |
| Cybersecurity | Secure coding, headers, dependency hygiene, audit remediation | Commissioning the CERT-In audit, hosting, the security policy |
| Lifecycle | Versioning, deprecation, change process | **All ten policies**, the Website Quality Manual, the Web Information Manager |

**A Web Information Manager must be designated** — typically at Joint Secretary
level — and the **Website Quality Manual** must exist with its policy templates
completed. Neither can be produced by a development team. Both gate
certification.

---

## Accessibility — what is done and tested

50 of the 88 checkpoints, and the part most amenable to automated testing.
`tests/unit/test_accessibility.py` runs on every commit.

| Criterion | Status |
|---|---|
| 1.4.3 Contrast (minimum), 4.5:1 | **Measured for every text/background pair** from the stylesheet tokens, so a colour tweak below threshold fails CI |
| 1.4.11 Non-text contrast, 3:1 | Saffron accent measured at 4.76:1 |
| 1.4.4 Resize text to 200% | Working control; whole page scales from one custom property. **No fixed-px font size survives** — asserted |
| 1.4.1 Use of colour | Every status tag carries text as well as colour |
| 2.4.1 Bypass blocks | Skip link on every page, hidden until focused, with a real target |
| 2.4.2 Page titled | Unique, descriptive titles — distinctness asserted |
| 2.4.7 Focus visible | Focus ring never removed; asserted |
| 3.1.1 Language of page | `lang="en"` on every page |
| 1.1.1 Non-text content | No images at all; asserted, so adding one without alt text fails |
| 1.3.1 Info and relationships | Semantic landmarks, `aria-label` on navigation, `aria-current` on the active page |
| 4.1.2 Name, role, value | Text-size controls carry `role`, `aria-label`, `aria-pressed` |

**Two defects this testing found and fixed:**

- Caption text measured **4.31:1** against the alternate panel background, below
  the 4.5 threshold. The token was darkened to `#666e77`, which clears 4.5 on
  every background it appears on.
- Chart axis labels were fixed at **10px and 11px**, so they ignored the text
  sizer entirely — leaving charts unreadable for precisely the user who had just
  enlarged the text. Now relative.

**What automated testing cannot establish:** screen-reader behaviour, cognitive
load, reading order with assistive technology, or the many criteria requiring
human judgement. An audit is still required; these tests only stop easy
regressions reaching it.

---

## Cybersecurity — before the CERT-In audit

In place: security headers on every response including static assets, CSP
permitting no remote origin, CORS as an allow-list never `*`, rate limiting,
parameterised queries throughout, least-privilege database roles with UPDATE and
DELETE revoked on append-only tables, no credentials in source, TLS verification
never disabled (ADR-016), and errors that never return a stack trace.

Still needed, and not ours to do: the CERT-In empanelled audit itself,
penetration testing, remediation, and the "safe to host" certificate.

**Expect findings.** A first audit that returns nothing usually means the audit
was shallow. Budget for a remediation cycle.

---

## Quality — open items

- **Mobile-first.** The layout is responsive and laptop-first. GIGW 3.0
  emphasises mobile-first; this needs testing on real devices, not emulation.
- **Load time** at production data volume, from an Indian network rather than
  localhost.
- **India Portal integration**, and any DigiLocker or single-sign-on requirement
  — a ministry architecture decision.

---

## Honest position

The application-layer work is done and tested. **Certification is not close**,
and not because of the software: it waits on a designated Web Information
Manager, a completed Website Quality Manual, ten lifecycle policies, an STQC
engagement and a CERT-In audit — all of which are ministry acts with their own
timelines.

Raise those early. They are slower than anything left in the code.
