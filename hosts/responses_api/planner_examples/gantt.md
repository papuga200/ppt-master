#### Slide 07 - 26-week delivery plan

- **Role**: timeline
- **Author tier**: frontier
- **Layout**: content
- **Audience move**: See nine concurrent workstreams, the sequence of all three unit slices, the assurance work that overlaps build, and the decisions Meridian controls.
- **Story link**: proves P02's delivery claim and dates P03–P06; P08 names the accountable roles; P09 ties invoices to five accepted outcomes.
- **Relationships**: Prove, Repeat and Assure and adopt overlap on one 26-week ruler; nine workstream lanes carry labelled bars; unit onboarding is staggered Anchor then Pattern then Challenger; milestones and decision gates sit at their actual week; Ask Meridian runs inside the core plan but ends before UAT/go-live; Trust Gate evidence feeds the week-23 cutover decision.
- **Title**: Nine overlapping workstreams reach production in week 24 and handover in week 26, with Meridian decisions at every material gate
- **Core message**: The plan proves a thin slice before scaling, makes reuse and complexity visible, and reserves weeks 18–23 for hardening, parallel evidence and cutover readiness.
- **Hierarchy**: 1 the phase band and week ruler; 2 the nine lanes with named bars; 3 mint decision diamonds; 4 deep-green milestone triangles; 5 dependency arrows; 6 the acceptance strip.
- **Content**:
    eyebrow: `26-WEEK DELIVERY PLAN`
    ruler: `W1` through `W26`, labelled every two weeks; calendar note `end July 2026 kick-off → end January 2027 completion`
    phase band 1: `PROVE · W1–W10`
    phase band 2: `REPEAT · W5–W18`
    phase band 3: `ASSURE AND ADOPT · W11–W26`
    lane 1: `Mobilisation and discovery` — `charter, stakeholders, current reports, readiness and acceptance approach · W1–W3`
    lane 2: `Architecture, security and environments` — `NFRs, platform / capacity, security design, environments, CI/CD and connectivity · W1–W6` · `production hardening and access review · W18–W23`
    lane 3: `Data ingestion and platform` — `common framework · W2–W7` · `Anchor feeds and model · W3–W10` · `Pattern feeds and model · W5–W14` · `Challenger feeds and model · W7–W18` · `metadata, monitoring and performance tuning · W18–W23`
    lane 4: `Metric definition and governance` — `metric inventory, ownership, AMC workflow, mappings and approvals · W2–W9` · `change support · W10–W24`
    lane 5: `Trust Gate` — `controls, reconciliations, exceptions and evidence pack · W3–W10` · `extend across Pattern and Challenger · W8–W18` · `parallel-run evidence · W19–W23`
    lane 6: `Reporting and dashboards` — `persona journeys and wireframes · W4–W8` · `semantic model and three products · W7–W18` · `UAT refinement and performance · W19–W23`
    lane 7: `Ask Meridian pilot` — `design and security review · W11–W13` · `glossary grounding, interface and benchmark set · W13–W17` · `testing, user trial and recommendation · W17–W21`
    lane 8: `Testing, deployment and adoption` — `test strategy and data · W8–W12` · `system and integration testing · W12–W18` · `UAT by unit and parallel run · W18–W23` · `training, cutover, hypercare and handover · W21–W26`
    lane 9: `Project management and governance` — `weekly delivery workshops, RAID, dependency / decision logs, scope and financial control · W1–W26` · `monthly steering and quality reviews · W1–W26`
    marker W1: `▲ W1 Mobilised — charter, integrated plan, RAID and governance calendar agreed`
    marker W2: `◆ W2 Pilot units selected — scored choice, source owners and access plan approved`
    marker W4: `◆ W4 Solution and commercial assumptions gate — architecture, security, capacity, caps and NFR backlog approved`
    marker W6: `◆ W6 AMC priority baseline and report wireframes approved`
    marker W10: `◆ W10 Anchor vertical slice — source-to-report slice, Trust Gate evidence and Power BI view demonstrated`
    marker W14: `▲ W14 Pattern unit beta — repeatable onboarding pattern demonstrated; deviations logged`
    marker W18: `◆ W18 Three-unit integrated beta — common model, Group beta and rollout-kit draft approved`
    marker W21: `◆ W21 Ask Meridian evaluation — stop / refine / progress recommendation`
    marker W23: `◆ W23 UAT and go-live gate — no open Severity 1 or 2 defect; critical controls pass or carry authorised exception; training, cutover and support ready`
    marker W24: `▲ W24 Production go-live — scheduled pipelines and three report products released to authorised users`
    marker W26: `▲ W26 Handover and completion — hypercare exit, runbooks, AMC ownership, evidence pack, rollout kit and closure accepted`
    dependency labels: `W4 platform gate → environment build` · `Anchor slice → reusable Pattern mapping` · `three-unit beta → UAT / parallel run` · `Trust Gate evidence → W23 cutover decision` · `W21 pilot result has no dependency into core go-live`
    source line: `Source: Tessellate proposed 26-week delivery plan; dates align to Meridian's end-July 2026 kick-off and end-January 2027 completion.`
- **Fill**: left rail x=54..294; phase ruler x=300..1226, y=146..196; nine lanes y=202..574 at ~41 px each; marker labels sit on their week positions, with compact top/bottom callouts to avoid collisions; acceptance strip y=586..652; source at the foot. Every bar carries its own label inside or fully beside it.
- **Visual scaffold**:
    ```
    ┌ header                                     26-WEEK DELIVERY PLAN ┐
    │ title (two lines)                                                │
    │ workstream rail    │ PROVE ─────│ REPEAT ─────│ ASSURE & ADOPT ───│
    │                    │ W1 2 4 6 8 10 12 14 16 18 20 22 24 26       │
    │ Mobilise/discover  │ ▬ charter + readiness                       │
    │ Architecture/sec.  │ ▬▬▬ design/env                 ▬ hardening   │
    │ Data/platform      │  ▬framework▬▬ Anchor▬▬ Pattern▬▬ Challenger │
    │ Metric governance  │  ▬ inventory/AMC ▬ change support           │
    │ Trust Gate         │   ▬ controls ▬ extend      ▬ parallel evidence│
    │ Reporting          │    ▬ design ▬▬▬ build       ▬ refine         │
    │ Ask Meridian       │              ▬design ▬build ▬trial ◆W21      │
    │ Test/deploy/adopt  │        ▬strategy ▬test ▬UAT/parallel ▬handover│
    │ PM/governance      │ ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬ │
    │ ▲W1 ◆W2 ◆W4 ◆W6 ◆W10 ▲W14 ◆W18 ◆W21 ◆W23 ▲W24 ▲W26             │
    │ acceptance evidence strip                                        │
    │ source                                                footer/folio│
    └───────────────────────────────────────────────────────────────────┘
    ```
- **Avoid**: a four-step roadmap; anonymous bars; gates placed in a legend rather than at their week; a lane for milestones; equal bar lengths; dependency lines without endpoints; allowing Ask Meridian to sit on the core go-live critical path.
- **Reference**: lib.a725b71f.p14 — borrow: "activity rows down a left rail, a shared time ruler and deliverable markers at their dates" — never: "portrait page ratio or micro-text"; second reference lib.d9052387.p2 — borrow: "phase bands above swimlanes and review gates on one common calendar" — never: "colours, quarter wording or template labels".
- **Editor notes**: bar positions are determined by the stated week ranges. Keep every milestone and gate name at its marker. Do not use a content legend to carry dates or acceptance text.
- Data class: client dates + proposed delivery plan/gates.
