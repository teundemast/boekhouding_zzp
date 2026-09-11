# Contributing

This is one person's bookkeeping program, open-sourced because it may be useful to
another Dutch freelancer. It is not a product and there is no roadmap I am committed to.
Issues and pull requests are welcome, with that in mind.

The README is in Dutch because its readers are. Code, comments, and commit messages are
in English; the user interface, the PDFs, and the docs are in Dutch.

## Running it

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.run
```

Python 3.12 or newer. Everything is pinned in `requirements.txt`.

Your administration lives outside the repository, by default in
`~/Documents/boekhouding-data`. Set `BOEKHOUDING_DATA` to point the tests or a scratch
install somewhere else.

## What a change has to respect

These are the rules the program is built on. A change that breaks one of them is a bug,
even if the tests pass:

- **Money is integer cents.** No floats anywhere near an amount. `money.round_half_up`
  refuses a float on purpose.
- **Invoice numbers are sequential and gap-free**, assigned only on finalisation.
- **A finalised invoice is immutable**, and its stored PDF is never regenerated.
- **Nothing is hard-deleted.** Records get `deleted_at`; the Belastingdienst wants seven
  years of history.
- **A filed quarter does not change silently.** Later documents dated inside it surface as
  corrections.
- **No personal data in the code.** Business details, clients, and rates live in the
  database, so that a fresh install starts empty. Test fixtures use made-up companies.
- **Tax rates and thresholds go in `app/taxyears.py`** with the year attached, never
  inline in a calculation. A year nobody has checked against the Belastingdienst stays
  `verified=False`, which makes the program call its output an estimate.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

A change to the BTW or income tax logic needs a test that states the rule in figures.
`tests/test_vat_return.py` reads as the specification of what this program believes about
Dutch VAT, scenario by scenario; add to it rather than around it. If you are fixing a
miscalculation, please include the numbers you checked it against and where they came
from (a Belastingdienst page, or an invoice you verified by hand).

## Bugs

For anything that touches a figure, the useful report is: what you entered, what the
program showed, what you expected, and why &mdash; ideally with the rule or source that
says so. Never paste a real invoice, a BTW number, or an IBAN into an issue; make up
numbers that show the same problem.
