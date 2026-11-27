# Council Transcript — Prior Authorization API Project Plan

**Timestamp:** 2026-11-25T04:01:09Z  
**Topic:** Review of Prior Auth API take-home project plan (Oxbridge Health / Roman Gavrilov)

---

## Original question

Review this plan [Prior Authorization API — Project Plan] … use the council review

---

## Framed question

Review this Prior Authorization API project plan for a senior SWE take-home ($180–200K role, Oxbridge Health / Roman Gavrilov). The candidate must ship a durable Python + PostgreSQL prior-auth backend that a teammate would inherit, then defend every line in a 45-minute live walkthrough. AI use is allowed but must be owned.

**Stakes:** Weak architecture or overbuilding risks failing the take-home or looking junior in the live session. Underbuilding risks missing compliance/audit/visibility rules that reviewers explicitly care about.

**Question:** Pressure-test this plan. Where will it fail a senior take-home or the live walkthrough? What should be cut, tightened, or added before coding starts?

---

## Anonymization mapping (peer review)

| Letter | Advisor |
|--------|---------|
| A | The Expansionist |
| B | The Executor |
| C | The Contrarian |
| D | The First Principles Thinker |
| E | The Outsider |

---

## Advisor responses

### The Contrarian (Response C)

The plan fails by optimizing for architecture theater over inheritance clarity.

Layers + routers-by-actor + outbox stub + Idempotency-Key + Testcontainers looks senior on paper and junior under interrogation. In 45 minutes they will ask *why* each piece exists. If you cannot defend Idempotency-Key and outbox as *required by the brief*, you look like you shipped a portfolio, not a teammate-ready service. Cut both until a reviewer cites a partner retry story. Same for “phases 0–6”: the blocker “need private repo URL” is process cosplay—code can start locally; repo is not a dependency.

**Fatal domain hole: status model is too thin for the review rules.** `submitted|in_review|decided` collapses claim, per-procedure decide, and whole-request final into mush. Live walkthrough will ask: can two reviewers race a claim? What if procedures disagree? Is the request “decided” only when *final*? Without explicit `claimed_by` / claim lease / `finalized_at` / actor on the approval path, you violate “never approved without actor” the moment someone sets status via a side door. IntakeRejection-with-no-row is clever until Support asks “find failed submissions”—then you have no durable failure record. Failed intake must be a queryable entity (or append-only rejection log), not a 400 body.

**Hard `units>30` reject is a product landmine.** Brief says “almost always typo,” not “always illegal.” Reviewers may want soft-fail / flag for ops. Locking it as hard reject without a README assumption you can defend in one sentence will get you boxed.

**What’s missing before coding:** one sequence diagram of submit→claim→per-proc→finalize→audit; exact redaction matrix per role; Support query path for failures; concurrent-claim test as *non-negotiable*, not one of ten. Everything else is cuttable fat.

### The First Principles Thinker (Response D)

You're optimizing for a neat layered service. The real problem is: can a stranger trust and defend a durable prior-auth state machine under audit pressure in 45 minutes?

Strip the plan. What must exist?

1. **Truth of the request** — one entity whose status transitions are explicit, irreversible where required, and never “approved” without an actor.
2. **Truth of why** — append-only audit that answers who/when/what for every mutation a support eng or auditor will ask about.
3. **Truth of what each actor may see** — redaction as a hard boundary, not a serializer nicety.
4. **Truth of intake** — failed submissions findable without polluting the claim queue.

Everything else is costume.

**Where this plan fails seniors**

- **Status model is too thin.** `submitted|in_review|decided` hides claim, per-procedure decisions, and finalization. Live walkthrough will ask: “Two reviewers race—who wins? Can you finalize with one procedure undecided? What if intake fails after partial write?” If you can’t draw the transition graph on a whiteboard, you’ve underbuilt the product and overbuilt the folders.
- **IntakeRejection as “no request row”** is the wrong question. Support needs “find failed submissions.” That is a durable artifact with correlation id, payload snapshot, field errors, actor, timestamp—not a void. Don’t invent a parallel domain; make failed intake a first-class record outside the reviewable queue.
- **Layers/routers-by-actor/outbox/idempotency** are resume padding. Partners build from OpenAPI. Reviewers grade: correctness of rules, audit completeness, race on claim, redaction. Cut outbox stub, cut optional Idempotency-Key unless you can defend exactly one retry case in 30 seconds.
- **“Defaults locked” without the invariant list** is cargo cult. The walkthrough defense is: *invariants → transitions → who may trigger them → what is audited.* Reorder the plan around that, then pick FastAPI.

**Before coding:** write a one-page state machine + audit matrix + visibility matrix. If a phase doesn’t force one of those three to be true, cut it.

### The Expansionist (Response A)

The upside this plan leaves on the table is **inheritance theater done right**. Seniors don’t win with “I shipped FastAPI + Alembic.” They win when a stranger can extend the system without asking you. Treat that as the product.

**Expand before you code:** make **audit + partner contract** the hero path, not a side layer. Reviewers explicitly care about who/when, failed submissions, and OpenAPI-only partners. A first-class `GET /support/failed-submissions`, typed error codes that map 1:1 to OpenAPI examples, and an append-only audit stream that can answer “show me everything that touched request X” will look 2× more senior than another status enum.

**Undervalued wins:**
- **Claim race + COI** as the live demo spine — walk the concurrent claim test, then the reviewer-who-treats-patient reject. That’s the “I thought about production” moment.
- **Actor-shaped OpenAPI** (member vs office vs reviewer vs ops) so redaction isn’t a filter bolted on later — it’s the contract. Partners inherit clarity; you inherit a walkthrough narrative.
- **Idempotency-Key** kept, not optional fluff: “retry after timeout doesn’t double-submit” is exactly the durable-backend story they want.

**Grow into, don’t grow past:** wire the outbox stub so a one-line “notify office” and a workload count query are 20 minutes of polish, not a rewrite. Same for an auditor role as a read-only consumer of audit — they said auditors are next; showing the seam is free senior signal.

**Cut nothing that proves durability; cut anything that doesn’t narrate.** Extra domain layers without a story burn time. Extra wishlist without the outbox hook wastes the expansion path.

If this lands, the walkthrough isn’t “here’s my CRUD.” It’s “here’s how a teammate, a partner, and compliance all inherit the same source of truth.”

### The Outsider (Response E)

Your plan reads like it was written for people who already do prior auth. A teammate inheriting this—or a reviewer who isn’t deep in healthcare ops—will hit fog immediately.

**Where it fails the walkthrough**
You’ll say “IntakeRejection separate from request” and “submitted|in_review|decided” like those are obvious. They’re not. In 45 minutes someone will ask: *If intake fails, where do support people look? Is that a request or not?* If the answer lives only in your head, you look junior. Same for “units>30 almost always typo”—you locked “hard reject,” but the README must say *why* in one sentence a non-clinician gets. “Conflict of interest” and “claim queue” need plain definitions in the API docs, not just code names.

**Cut before coding**
- Outbox stub / wishlist notify / workload counts: dead weight you can’t defend as “senior” if core audit/redaction is thin. Cut until Phase 5 has spare time.
- Optional Idempotency-Key: either required with a clear contract or gone. Half-optional features read as incomplete.
- Router-by-actor sprawl: three actors × many routes looks impressive; one resource API with role checks is easier to inherit and explain.

**Tighten**
- One page of “words a new hire needs”: request vs rejection, who sees what, what “final” means, what “approved without actor” forbids.
- Seed data story: fake patients/providers/reviewers must make COI and redaction *demonstrable* in one curl script. If demos need tribal knowledge, the plan failed.
- Audit: say *what* is logged per step in English, not “AuditEvent append-only.”

**Add**
- Explicit “support finds failed submissions” path in the API surface (query/filter), not an afterthought.
- Live-session script: 5 commands that prove submit → reject fields → claim race → COI block → member redaction. If you can’t show it without opening an IDE, architecture overbuilt the wrong thing.

Ship the boring, readable system. Domain jargon without a glossary is the real senior-fail risk.

### The Executor (Response B)

**Monday-morning verdict:** The plan is shippable. The private-repo blocker is real—get that URL first or you’re stuck pushing nothing. Everything else can start today without it: local init, compose, Alembic, first failing tests.

**What will fail the walkthrough**
- Status machine with no transition table you can draw from memory. Reviewers ask “what if claim then second claim?” You need one claim race test and a one-line rule: `UPDATE … WHERE status='submitted' AND claimed_by IS NULL`.
- IntakeRejection as a separate path is fine—own the API contract Monday: same error shape, exact field keys, no request id. If the OpenAPI isn’t written before code, partners/docs story dies in the room.
- Outbox stub is dead weight. Cut it. Wishlist = “not built; would be…” in README. Don’t defend empty tables.
- Ten tests is enough only if they map to grading: units>30, past DOS, inactive coverage, COI, redaction, claim race, audit actor on approve, failed-submission lookup. Drop aesthetic coverage.

**Cut before coding**
- Router-per-actor sprawl → one router package, auth dependency picks role. Faster to build, easier to defend.
- “Phases 0–6” theater → three merges: submit+audit, review+claim, member+redaction+README.
- Optional Idempotency-Key unless OpenAPI requires it—defer.

**Add Monday AM (in order)**
1. Repo + compose + empty Alembic revision that creates `requests`, `procedures`, `audit_events`, seed master data.
2. OpenAPI stub with submit/claim/decide/member endpoints and error schema.
3. One red pytest for submit reject (units>30) → implement until green.
4. Hard-code `America/New_York` in one `clock.py`—don’t bury it.

Ship the thin vertical slice that a teammate can run with `docker compose up` and `pytest`. Anything you can’t demo in 45 minutes from that README is overbuild.

---

## Peer reviews

### Reviewer 1
1. Strongest: D — real bar, four truths, right pre-code artifacts.  
2. Biggest blind spot: A — keeps outbox/idempotency/actor OpenAPI sprawl; never pressure-tests thin status or units>30.  
3. All missed: OpenAPI/grader contract risk; PHI in audit payloads; explicit 6–8 hour time-box.

### Reviewer 2
1. Strongest: D — durable state under audit; clean cut rule.  
2. Biggest blind spot: A — resume padding; skips status collapse and units landmine.  
3. All missed: DB-enforced invariants; timed walkthrough recovery; auth/PHI first-class.

### Reviewer 3
1. Strongest: D — four non-negotiables + hard cut rule.  
2. Biggest blind spot: A — expands polish without fixing thin status / non-durable intake.  
3. All missed: schema/transaction invariants; hour budget for cut/keep.

### Reviewer 4
1. Strongest: D — stranger-defend bar + pre-code filter.  
2. Biggest blind spot: A — expands while missing fatal status collapse.  
3. All missed: hour budget; auth→redaction binding; README as async grader; check whether OpenAPI/idempotency required by prompt.

### Reviewer 5
1. Strongest: D — grading axis + three artifacts.  
2. Biggest blind spot: B — ship-first underweights partner/idempotency story; risks mushy status.  
3. All missed: time-budget demo plan; auth threat model; clock/TZ test strategy; private-repo submission checklist.

---

## Chairman synthesis

See council-report HTML and the verdict below.

### Where the Council Agrees
- Core stack (FastAPI + Postgres + Alembic + JWT + docker compose) is fine; don’t re-litigate it.
- Thin status enum without explicit claim/finalize/actor fields is the highest-risk domain gap.
- Failed intake must be queryable for Support — not only a 422 body.
- Cut outbox / wishlist until MVP is solid; Idempotency-Key is defer-or-commit, not half-optional.
- Before coding: state machine + audit matrix + visibility/redaction matrix; claim race is non-negotiable.
- Live walkthrough needs a short curl/demo script a stranger can follow.

### Where the Council Clashes
- Expansionist wants Idempotency-Key, actor-shaped OpenAPI, outbox seam, auditor stub as senior signal; Contrarian/First Principles/Outsider/Executor call most of that resume padding.
- Executor treats private-repo as real blocker for submission; Contrarian says start coding locally now.
- Contrarian flags hard units>30 as product landmine; plan’s hard reject is fine if README defends it in one sentence (majority lean: keep hard reject + document).

### Blind Spots the Council Caught
- DB constraints must enforce “decided ⇒ decided_by NOT NULL” and atomic claim — tests alone aren’t enough.
- Audit payloads can leak PHI into member-visible paths if not designed carefully.
- Need an hour budget / fail-closed list for what ships if time runs short.
- README is the async grader before the live session — glossary + decisions matter as much as code.
- Auth threat model for fake JWT is thin in the plan (role escalation, forged claims).

### The Recommendation
Keep the plan’s MVP spine and boring stack. Reorder around three artifacts before scaffolding folders: (1) transition graph with claim + whole-request finalize + actor invariants, (2) audit + support lookup for failed intake as durable records, (3) per-role visibility matrix with member redaction. Cut outbox/wishlist and defer Idempotency-Key. Prefer one resource API + RBAC over router-per-actor theater unless you can narrate “auditors next” in 20 seconds. Collapse phases to three vertical slices. Encode invariants in schema + same-transaction audit.

### The One Thing to Do First
Write a one-page **state machine + audit matrix + visibility matrix** (including how Support finds a failed submission by correlation id) and put it in the README Decisions section — then create the private template repo and scaffold against that page only.
