# Build prompt: boekhoudsysteem voor een Nederlandse ZZP'er

Build me a self-hosted bookkeeping application for a single Dutch freelancer (ZZP'er,
eenmanszaak, IB-ondernemer). It is used by one person only — me. There are no other
users, no tenants, no roles, no billing plans. Optimise for correctness, durability of
my data, and low maintenance. Do not optimise for scale, and do not add features I did
not ask for.

## Who this is for

I am a data science freelancer in the Netherlands, registered as an eenmanszaak. The
following details must be configurable in one settings screen and used on all invoices.
They belong in the database, never as defaults in the code: a copy of this application
handed to someone else must start empty, so that nobody can accidentally invoice with
another person's IBAN or BTW number.

- Company name
- Address, postcode, city
- Phone
- Email
- BTW-id
- IBAN
- KvK number

I file BTW-aangifte once per quarter and do my inkomstenbelasting once per year. Most
of my revenue comes from a handful of Dutch B.V. clients, invoiced monthly, sometimes
with several project lines per invoice.

## Core scope

### 1. Invoicing (facturen)

- Create, edit, and finalise sales invoices. Draft invoices are freely editable;
  finalised invoices are immutable — corrections happen via a credit note
  (creditfactuur) that references the original.
- Sequential, gap-free invoice numbering per calendar year. My current format is
  `F00006` (prefix + zero-padded counter). Make the prefix and padding configurable,
  but never allow a gap or a reused number — this is a legal requirement.
- Per-invoice fields: invoice date, invoice number, client, client reference
  ("Uw kenmerk", free text — I use things like `FEB`), payment terms in days
  (default 14), and optional notes.
- Line items with: aantal (quantity, may be fractional hours), code (short project
  code, e.g. `ADSD`, `NOVA`), omschrijving (multi-line description), unit price or
  line total, and BTW rate.
- BTW rates: 21% (hoog), 9% (laag), 0%, vrijgesteld, verlegd (reverse charge, domestic),
  and intracommunautaire levering (EU B2B, 0% with the client's VAT number shown and
  the text "btw verlegd" on the invoice). Group the totals per rate on the invoice
  footer, the way `Btw hoog 21% (€ 1.638,00)  € 343,98` reads on my current invoices.
- Round per line to two decimals, then sum; totals must reconcile exactly. Use integer
  cents internally — never floats for money.
- Generate a PDF that matches the layout of my existing invoices: my details top-right,
  client address block top-left, "FACTUUR" heading, a metadata block (Datum,
  Factuurnummer, Klantnummer, Uw kenmerk), the line-item table, the totals block, and
  the payment sentence at the bottom:
  "Gelieve deze factuur binnen 14 dagen onder vermelding van het factuurnummer te
  betalen."
- Every finalised invoice's PDF is stored on disk and never regenerated from changed
  data — the PDF I sent is the record.
- Verify the invoice carries everything the Belastingdienst requires: my full name and
  address, my BTW-id, my KvK number, the client's name and address, invoice date,
  sequential number, description and quantity of services, the date the service was
  delivered (or period), the amount ex BTW per rate, the BTW rate and amount, and the
  total.
- Duplicate an existing invoice as the starting point for the next one — this is my
  most common action, since I bill the same clients monthly with similar lines.
- Recurring invoice templates: define a client, a set of lines, and a monthly cadence,
  then have the system prepare next month's invoice as a **draft** for me to check and
  finalise. Never send anything automatically.
- Optionally email the invoice as a PDF attachment via SMTP, with the SMTP settings in
  config. If this is more trouble than it is worth, "download the PDF" is fine.
- Invoice template configuration: my logo, accent colour, and the standard footer text,
  in settings rather than hard-coded in the template.
- Language per client: a Dutch and an English version of the invoice template, chosen by
  the client's country or an explicit setting. Foreign clients get the English one.
- Currency: invoice in a foreign currency where needed, showing the EUR equivalent and
  the exchange rate used on the invoice date, because the BTW and the bookkeeping must be
  in EUR. Store both the original amount and the EUR amount.
- Partial payments: an invoice can be partly paid, so track the paid amount and the
  remaining balance rather than a boolean paid/unpaid flag.
- Optionally render an EPC/SEPA payment QR code on the invoice (IBAN, amount, invoice
  number as the reference) so clients can scan it in their banking app. This is a purely
  local, offline computation — no payment provider integration, no iDEAL, no incasso.

### 2. Quotes (offertes)

Draft a quote with the same line-item structure and PDF layout as an invoice, but headed
"OFFERTE", with a validity date ("geldig tot") instead of payment terms, and its own
number sequence (e.g. `O00001`). Statuses: concept, verzonden, geaccepteerd, afgewezen,
verlopen. Converting an accepted quote into a draft invoice — carrying over the lines —
is the whole point of this feature, so make that one click. Quotes never touch the BTW
figures; only invoices do.

### 3. Time tracking (urenregistratie)

My invoices are hour-based: the aantal column on my current invoices is hours per project
code (41, 23, 22). So this is not a side feature — it feeds invoicing directly.

- Log time entries: date, client, project code, hours (fractional), description, and a
  billable/non-billable flag.
- Projects belong to a client and carry the code and description that end up on the
  invoice line (e.g. `NOVA` — "Data science diensten verricht voor Nova, exploratie en
  transformatie van data") plus an hourly rate.
- Generate a draft invoice from unbilled hours for a chosen client and period: one line
  per project, with the summed hours as aantal and the project's rate applied. Mark those
  entries as invoiced and link them to the invoice, so nothing is ever billed twice.
- Weekly and monthly views, and a per-project total of hours and revenue.
- Non-billable hours still count towards the urencriterium, so all logged hours — billable
  or not — feed the 1.225-uur total in the annual overview. Acquisition, administration,
  and training are business hours too.

### 4. Clients (klanten)

Name, address, country, contact person, email, BTW number (validated by format, and
optionally checked against VIES for EU clients), klantnummer, default payment terms,
and default BTW treatment. Soft-delete only — a client referenced by an invoice can
never be hard-deleted.

### 5. Expenses (kosten / inkoopfacturen)

- Record purchase invoices and receipts: date, supplier, description, amount ex BTW,
  BTW amount, BTW rate, and category.
- Attach the source document (PDF or image); store it on disk alongside the record.
- Flag deductible BTW (voorbelasting) separately from the cost itself, since some
  costs have partially or non-deductible BTW.
- Handle the cases a ZZP'er actually hits: BTW verlegd on domestic subcontracting,
  intracommunautaire verwerving (EU purchases — self-assess BTW and deduct it in the
  same return), imports from outside the EU, and purchases with no BTW at all.
- A private-use percentage per expense (e.g. a phone that is 70% business), affecting
  both the deductible BTW and the deductible cost.
- Categories mapped to a simple, fixed chart of accounts suitable for an eenmanszaak.
  Do not build a general ledger with journal entries — that is more machinery than I
  need. A categorised list of income and expenses is enough, as long as the quarterly
  and annual figures come out right.
- Categories should cover the deduction rules that actually differ: representatie/
  relatiegeschenken and zakelijke etentjes (partially deductible), werkruimte thuis,
  telefoon en internet, vakliteratuur en opleidingen, software-abonnementen,
  verzekeringen, and reiskosten. Where the deductible percentage differs from 100%,
  encode it on the category with the year attached, and show me both the paid amount and
  the deductible amount.
- Recurring expenses (monthly subscriptions, insurance) can be defined once and prepared
  as draft entries each period, the same way recurring invoices work.
- **Document inbox**: drop a PDF or photo into a watched folder, or forward it to a
  configured mailbox, and it appears as an unprocessed document waiting to be booked. The
  point is that receipts never pile up outside the system.
- Optional and clearly separated: OCR/"scan & herken" to pre-fill supplier, date, amount,
  and BTW from the document. Only do this with a local, offline library, and always
  present the extracted values as a suggestion I confirm. If no good offline option
  exists, skip it and say so rather than introducing a cloud dependency — manual entry of
  a handful of receipts per month is genuinely fine.

### 6. Assets and depreciation (investeringen en afschrijvingen)

Assets over the investment threshold (currently €450 ex BTW) are capitalised rather
than expensed. Straight-line depreciation over a configurable term (5 years default,
minimum residual value), with the yearly depreciation charge appearing automatically in
the annual figures. Track the kleinschaligheidsinvesteringsaftrek (KIA) threshold and
tell me when a year's total investments qualify.

### 7. Quarterly BTW return (btw-aangifte)

This is the feature that has to be right. For a chosen quarter, produce the exact
figures for each rubriek of the Belastingdienst's aangifte omzetbelasting:

- 1a — leveringen/diensten belast met hoog tarief (omzet + btw)
- 1b — leveringen/diensten belast met laag tarief
- 1c — leveringen/diensten belast met overige tarieven behalve 0%
- 1d — privégebruik
- 1e — leveringen/diensten belast met 0% of niet bij u belast
- 2a — leveringen/diensten waarbij de heffing naar u is verlegd
- 3a — leveringen naar landen buiten de EU (uitvoer)
- 3b — leveringen naar/diensten in landen binnen de EU
- 3c — installatie/afstandsverkopen binnen de EU
- 4a — leveringen/diensten uit landen buiten de EU
- 4b — leveringen/diensten uit landen binnen de EU
- 5a — verschuldigde omzetbelasting (total)
- 5b — voorbelasting
- Saldo te betalen or terug te vragen

Rules that must hold:

- The figures follow the factuurstelsel (invoice date determines the period), which is
  the default for an eenmanszaak. If you support kasstelsel, make it an explicit setting
  and be consistent everywhere.
- Reverse-charge and intracommunautaire purchases appear both as verschuldigde btw
  (2a/4a/4b) and as voorbelasting (5b), netting to zero when fully deductible.
- Once I mark a quarter as filed, lock it: any later document dated inside that quarter
  must be flagged as a correction rather than silently changing a filed figure. Show
  those corrections so I can include them in a suppletie or in the next return if under
  the €1.000 threshold.
- Show a drill-down from every rubriek to the individual invoices and expenses that make
  it up. When the Belastingdienst asks, I need to point at the documents.
- Also produce the ICP-opgaaf (opgaaf intracommunautaire prestaties) per quarter: per EU
  client VAT number, the total of goods and services supplied.
- I do not need to file electronically. Showing me the numbers to type into the
  Belastingdienst portal, plus an exportable PDF/CSV of the underlying detail, is exactly
  right.
- Support the **kleineondernemersregeling (KOR)** as a setting, even though I am unlikely
  to use it: when enabled from a given date, sales are exempt, voorbelasting is not
  deductible, and the return changes accordingly. Track annual turnover against the
  €20.000 threshold and warn me if I approach it. Also flag the reverse: BTW previously
  deducted on assets may need to be revised (herziening) on entering the KOR.
- **Oninbare vorderingen**: when an invoice is still unpaid one year after the due date,
  the BTW on it can be reclaimed. Surface these automatically as a to-do in the quarter
  they become eligible, with the amount to enter, and handle the correction if the client
  pays later after all.
- A pre-filing checklist before I mark a quarter as filed: unprocessed documents in the
  inbox, draft invoices still open inside the period, bank transactions not yet matched,
  and expenses missing an attachment. I would rather be told about a forgotten receipt
  than discover it after filing.
- Show the previous four quarters next to the current one, so an obviously wrong figure
  stands out before I submit it.

### 8. Annual figures for the inkomstenbelasting

An annual overview I can hand to (or type into) my aangifte inkomstenbelasting:

- Omzet ex btw, total costs by category, and the resulting winst uit onderneming
- Depreciation for the year, per asset
- Balance sheet items I actually have: debiteuren (unpaid invoices at year-end),
  crediteuren, bank balance, assets at book value
- Zakelijke kilometers with the fixed rate per kilometer (configurable — currently
  €0,23) for a private car used for business
- A checklist of the ondernemersaftrek items with the current-year amounts as configurable
  values, not hard-coded: urencriterium (1.225 uur), zelfstandigenaftrek,
  startersaftrek, meewerkaftrek, and the MKB-winstvrijstelling percentage. Compute the
  indicative belastbare winst after these, clearly labelled as an estimate, not tax advice.
- A urencriterium report built from the time tracking in section 3: total hours for the
  year against 1.225, broken down per month and per project, exportable as the
  substantiation the Belastingdienst may ask for.
- A **tax reservation** view: given the year-to-date profit, an indicative amount I should
  be setting aside for the inkomstenbelasting and the Zvw-bijdrage, and how that compares
  to what I have actually paid in voorlopige aanslag instalments. This is the number I
  most want to know mid-year, and getting it wrong is what hurts in April.
- Compare each year against the previous one — omzet, costs per category, and profit — so
  the trend is visible without exporting anything.

### 9. Bank reconciliation

Import bank transactions from a CSV or MT940 export (Rabobank, in my case — make the
CSV column mapping configurable rather than hard-coding one bank's format). Match
payments against open invoices, primarily on amount and the invoice number appearing in
the description. Suggest matches, but require me to confirm; never auto-match silently.
Mark invoices paid on the transaction's value date, supporting partial payments and a
single transaction settling several invoices. Show me an aging overview of what is still
outstanding, and let me generate a herinnering/aanmaning PDF for overdue invoices, with
escalating standard texts (vriendelijke herinnering, aanmaning, laatste aanmaning) that I
can edit.

Bank transactions that are not invoice payments must also be classifiable: expenses paid
directly from the account, privéopnames and privéstortingen (which are not costs or
revenue and must not touch the profit), tax payments to the Belastingdienst, and
transfers. Every transaction should end up either matched, categorised, or explicitly
marked as ignored — nothing silently unaccounted for.

**Opening balances**: I have been trading since 2023, so let me set a start date for the
system with opening balances — bank balance, outstanding debiteuren, existing assets with
their book value and remaining depreciation term — rather than forcing me to re-enter
years of history. A generic CSV importer for historic invoices and expenses would be a
welcome bonus.

### 10. Dashboard

One screen I see on opening the application: revenue this quarter and this year, unpaid
invoices with the total outstanding and anything overdue, the current quarter's provisional
BTW balance, the tax reservation figure, hours logged this year against 1.225, and
anything waiting for me (unprocessed documents, unmatched transactions, draft invoices).
Numbers and short lists, not decoration. If you add a chart, make it one chart of monthly
revenue and nothing more.

## Explicitly out of scope

I have looked at the commercial Dutch packages and deliberately do not want most of what
they offer. Do not build: a double-entry grootboek with journal entries, multi-user
accounts or an accountant login, ledenadministratie, voorraadbeheer, salarisadministratie,
automatische incasso or SEPA-betaalbestanden, iDEAL or payment-provider integrations,
PSD2/automatic bank feeds (CSV and MT940 import is enough), a mobile app, an API for
third parties, or a general integrations framework. If a feature only makes sense for a
company with employees, customers of its own, or an external accountant, it is not for me.

The one mobile concession worth making: the document inbox should be reachable from a
phone browser on my local network so I can photograph a receipt. That is a page, not an app.

## Non-functional requirements

- **Money**: integer cents everywhere, with an explicit rounding policy at each boundary.
  No floating point in any calculation that touches an amount.
- **Locale**: Dutch number formatting in the UI and on PDFs (`€ 1.638,00` — comma as the
  decimal separator, dot as the thousands separator), dates as `dd-mm-yyyy`, Dutch UI
  labels. Code, comments, and commit messages in English.
- **Data retention**: the Belastingdienst requires 7 years of records. Nothing is ever
  hard-deleted; everything is soft-deleted with an audit trail of what changed, when, and
  from what to what. Attached source documents are stored immutably on disk.
- **Backups**: a one-command backup that produces a single archive of the database plus
  all attachments and generated PDFs, and a documented, tested restore path. Also a full
  export to plain CSV/JSON so I am never locked into this application — that export is a
  first-class feature, not an afterthought.
- **Deployment**: runs locally on my own machine (Windows), started with one command. A
  single-file SQLite database is ideal. No cloud services, no external dependencies at
  runtime, no account system, no telemetry. If you add authentication at all, a single
  password is the maximum.
- **Tech stack**: pick a boring, well-supported one and justify it in one paragraph
  before you start. A Python backend (FastAPI or Django) with SQLite and server-rendered
  pages, or a TypeScript equivalent, both fit. Prefer fewer dependencies and a stack that
  will still run in five years without maintenance over anything fashionable.

## Testing

The tax calculations are the part that must not be wrong, so:

- Unit tests for every BTW scenario: 21%, 9%, 0%, vrijgesteld, verlegd,
  intracommunautair (both directions), import, private-use percentages, and credit notes.
- Tests that a full quarter of realistic documents produces the correct figure in every
  rubriek, including the netting of reverse-charge entries.
- Tests for rounding: many small lines must sum to the invoice total exactly, and a
  quarter's invoices must sum to the rubriek total exactly.
- Tests that invoice numbering never produces a gap or a duplicate, including under
  concurrent or interrupted creation.
- Tests that a finalised invoice cannot be mutated and that a filed quarter cannot be
  silently altered.
- At least one end-to-end test: create clients, invoice a quarter, book expenses, run the
  BTW return, mark it filed, then add a late document and see it surface as a correction.

## Working agreement

- Start with a short plan: the data model, the tech stack choice, and the order you will
  build in. Wait for my go-ahead before writing code.
- Build in vertical slices that each work end to end, in this order: clients and
  invoicing, then expenses, then the quarterly BTW return, then time tracking and
  invoicing from hours, then bank reconciliation, then the annual overview, then quotes
  and the dashboard. I would rather have four solid features than eight half-finished
  ones — stop and check in after each slice.
- Where a Dutch tax rule is ambiguous or has changed recently, say so explicitly and put
  the rate or threshold in a configuration file with the year attached, rather than
  guessing and burying it in the code.
- Label anything that estimates my income tax clearly as an indication, not advice. The
  BTW figures should be exact; the IB figures are a starting point for my aangifte.
