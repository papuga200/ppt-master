#### Slide 03 - Source-to-decision architecture

- **Role**: architecture
- **Author tier**: frontier
- **Layout**: content
- **Audience move**: See one connected technical path, inside Meridian's tenancy, where data, controls, definitions, reporting and AI share the same governed spine.
- **Story link**: proves P02's trust claim; P04 explains ownership and user experiences on this spine; P05 expands only the Ask Meridian branch.
- **Relationships**: structured sources enter through source contracts and pipelines; Bronze, Silver and Gold are sequential; a Trust Gate applies at each transition and can quarantine or block; AMC-approved calculations enter the certified semantic model; three report products and Ask Meridian consume that model; lineage, security and environment separation span the architecture; all processing remains in Meridian's approved tenancy and region.
- **Title**: One certified semantic model carries every source batch through Trust Gate and AMC to three secured decision products
- **Core message**: Fabric and Power BI provide the shortest integrated path for the six-month timetable; trust comes from publication gates, versioned metrics and lineage rather than from the platform name.
- **Hierarchy**: 1 the left-to-right source-to-decision spine; 2 Trust Gate as three mint checkpoints; 3 AMC as the governing band over Gold and the semantic model; 4 the three report products; 5 the Ask Meridian dashed pilot branch; 6 the tenancy and cross-cutting rails.
- **Content**:
    eyebrow: `MAPH ARCHITECTURE`
    scope frame label: `MERIDIAN MICROSOFT CLOUD TENANCY · APPROVED REGION · SEPARATE DEVELOPMENT / TEST / PRODUCTION WORKSPACES`
    sources heading: `STRUCTURED SOURCES — UP TO 12 FEEDS / THREE BUSINESS UNITS (PROPOSED CAP)`
    source patterns: `database extract` · `file / SFTP` · `REST API`
    source contract: `owner · schema · grain · keys · extraction time · expected volume · permitted values · control totals · personal-data classification`
    ingest node: `Fabric Data Factory pipelines` / `scheduled daily ingestion · immutable batch ID · source, business unit and extraction timestamp`
    bronze node: `OneLake Bronze — source-aligned` / `raw extract retained unchanged within policy · file hash · record count · financial / volume control totals`
    trust gate 1: `TRUST GATE 1` / `schema · completeness · duplicate · timeliness · source totals` / `pass / warn / quarantine`
    silver node: `OneLake Silver — conformed` / `date · business unit · agency hierarchy · pseudonymous agent key · policy / case · product · channel`
    trust gate 2: `TRUST GATE 2` / `referential integrity · uniqueness · allowed values · cross-field rules · source-to-conformed reconciliation`
    gold node: `Fabric Warehouse Gold — agency performance` / `reusable facts and dimensions · business unit · period · source batch · calculation version · metric version`
    trust gate 3: `TRUST GATE 3` / `Gold-to-Silver and source-anchor reconciliation` / `critical failure blocks publication; authorised non-critical exception stays visible`
    AMC band: `Agency Metric Catalogue (AMC) — only Approved, effective-dated definitions calculate Gold measures`
    semantic node: `Certified Power BI semantic model` / `one measure definition · Microsoft Entra ID groups · row-level and object-level security`
    product 1: `BU Performance Cockpit` / `secured self-service and authorised drill-through for each unit`
    product 2: `Group Performance Lens` / `consolidated comparison with caveats and labelled local extensions`
    product 3: `Data Trust Console` / `freshness · quality · reconciliation · exceptions · release evidence · lineage`
    pilot branch: `Ask Meridian — contained pilot` / `constrained query against the certified model; no Bronze or Silver access`
    lineage rail: `MAPH metadata propagates source batch → transformation → calculation version → metric version → report result`
    security rail: `client-managed identities · least privilege · pseudonymisation · encryption · logging · private endpoints where approved · no client data used to train third-party models`
    design-choice strip: `Daily batch plus controlled month-end rerun` · `one conformed model with BU mappings` · `critical controls prevent publication` · `effective-dated metrics preserve history`
    rationale: `Why Fabric + Power BI: follows Meridian's Power BI preference, reduces integration seams and supports a repeatable onboarding pattern. Azure modular services remain a contingency only if Fabric licensing, region or security approval fails at the week-4 gate.`
    source line: `Source: Meridian RFP; Tessellate solution design and standing security position. Platform approval, capacity and feed count are commercial assumptions to confirm by week 4.`
- **Fill**: sources x=54..210; tenancy frame x=226..1226 and y=146..594; architecture spine inside the frame from x=246..1198, y=198..430; report products stack at right; cross-cutting AMC, lineage and security rails y=448..568; design-choice/rationale strip y=604..660.
- **Visual scaffold**:
    ```
    ┌ header                                             MAPH ARCHITECTURE ┐
    │ title (two lines)                                                     │
    │ STRUCTURED       ┌╌ MERIDIAN TENANCY · APPROVED REGION · DEV/TEST/PROD ╌┐
    │ SOURCES          │ ingest ▶ Bronze ◆TG1 ▶ Silver ◆TG2 ▶ Gold ◆TG3      │
    │ database ───────▶│                                      ▲ AMC band      │
    │ file/SFTP ──────▶│                         certified semantic model ─┬─ BU Cockpit
    │ REST API ───────▶│                                                   ├─ Group Lens
    │ source contract  │                                                   ├─ Trust Console
    │                  │                                                   └╌ Ask Meridian
    │                  │ lineage rail: batch → transform → calc → metric → result
    │                  │ security rail: identity · RLS/OLS · encryption · logging
    │                  └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
    │ design choices + Fabric/Power BI rationale strip                     │
    │ source                                                   footer/folio│
    └──────────────────────────────────────────────────────────────────────┘
    ```
- **Avoid**: a generic layered stack with no control flow; separate marts for each business unit; Trust Gate as one box beside the platform; Ask Meridian connected to raw data; a public-model endpoint; decorative vendor logos.
- **Reference**: lib.293842e0.p10 — borrow: "a left decision rail tied to a layered architecture and cross-cutting governance bands" — never: "brand, wording, decorative particle field"; second reference lib.e2e8e4b1.p42 — borrow: "a whole-system map in named zones with explicit interfaces and an operating rail" — never: "vendor logos or unreadable micro-density".
- **Editor notes**: do not imply Fabric licensing, approved region or private connectivity are confirmed; the week-4 gate confirms them. Keep every flow endpoint attached to a named node.
- Data class: client fact + firm capability + proposed architecture/scope/commercial assumption.
