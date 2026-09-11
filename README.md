# Boekhouding

Een boekhoudprogramma voor één Nederlandse ZZP'er, dat lokaal op mijn eigen machine
draait. Geen cloud, geen accounts, geen abonnement. Facturen maken, kosten boeken, elk
kwartaal de btw-aangifte, en aan het eind van het jaar de cijfers voor de
inkomstenbelasting.

Dit is persoonlijke software, opensource gemaakt omdat iemand anders er misschien wat aan
heeft. Het rekent met **Nederlandse** belastingregels en is gebouwd rond hoe één
eenmanszaak werkt; daarbuiten heb je er niets aan. Er is geen support en geen garantie,
zie [Licentie en aansprakelijkheid](#licentie-en-aansprakelijkheid). Fork hem gerust.

## Starten

Dubbelklik **`Boekhouding.cmd`**. De browser gaat open op <http://127.0.0.1:8777>.

De eerste keer duurt dat een minuut of twee: het programma installeert dan zichzelf.
Heb je nog geen Python, dan legt de starter uit hoe je dat installeert. Daarna kom je op
het instellingenscherm, waar je je eigen bedrijfsgegevens invult &mdash; die staan
bewust niet in de code, zodat niemand per ongeluk met andermans IBAN of btw-nummer
factureert. Zolang bedrijfsnaam, adres, btw-nummer, KvK en IBAN ontbreken kun je wel
alles klaarzetten, maar geen factuur definitief maken.

Zolang dat zwarte venster open staat, draait het programma. Sluit je het venster, dan
sluit je de boekhouding af. Je hoeft het dus niet permanent te laten draaien: start het
wanneer je facturen maakt of de aangifte doet, en sluit het daarna weer.

Vanaf de opdrachtregel kan ook:

```powershell
.\start.ps1
```

De eerste keer maakt dit een virtuele omgeving aan en installeert het de afhankelijkheden.

Wil je vanaf je telefoon een bonnetje kunnen fotograferen:

```powershell
.\start.ps1 --lan
```

Let op: met `--lan` is de boekhouding bereikbaar voor alles op hetzelfde netwerk, zonder
wachtwoord. Doe dat op je eigen netwerk thuis, niet op de wifi van een hotel of een
klant.

## Waar staan mijn gegevens

Alles staat buiten deze map, standaard in `C:\Users\<jij>\Boekhouding`:

```
Boekhouding/
  boekhouding.sqlite3   de administratie
  facturen/2026/        de verstuurde pdf's, precies zoals ze verstuurd zijn
  documenten/2026/03/   bonnen en inkoopfacturen
  inbox/                hier gedropte bestanden verschijnen als "nog te boeken"
  backups/
```

Die map staat bewust *niet* in `Documents`: dat is de map die OneDrive aanbiedt om te
back-uppen, en een sqlite-database die onder je handen gesynchroniseerd wordt is een
database die op een dag stuk is. In `AppData` hoort het ook niet, want je facturen en
bonnen zijn jouw documenten &mdash; die moet je over zeven jaar nog kunnen vinden en naar
een usb-stick kunnen slepen, niet opgraven uit een verborgen map.

Stond je administratie al in `Documents/boekhouding-data`, dan blijft het programma die
gebruiken: een update laat je nooit naar een leeg boekhoudingetje kijken. Verhuizen mag,
en het programma zegt het er ook bij als hij hem daar nog vindt: sluit het programma en
verplaats de map naar `Boekhouding` in je gebruikersmap.

Een andere locatie, bijvoorbeeld een tweede schijf: zet `BOEKHOUDING_DATA` voordat je
start.

### Aan iemand anders geven

```powershell
.\.venv\Scripts\python.exe -m tools.maak_zip
```

Maakt een zip naast de projectmap: de code en de licentie, zonder git-historie, zonder
virtuele omgeving en zonder administratie. Voor het inpakken controleert het script of er geen
btw-nummers, IBANs, e-mailadressen of telefoonnummers in de code staan, en weigert het
anders. De ontvanger pakt uit en dubbelklikt `Boekhouding.cmd`.

### Back-up

```powershell
.\.venv\Scripts\python.exe -m tools.backup            # één zip met alles
.\.venv\Scripts\python.exe -m tools.backup --export   # plus alles als losse CSV
.\.venv\Scripts\python.exe -m tools.backup --restore <zip> <lege map>
```

De CSV-export staat er zodat dit programma mijn administratie nooit kan gijzelen: die
bestanden zijn over zeven jaar nog leesbaar, met of zonder deze code. De restore is
getest (`tests/test_backup.py`), niet alleen geschreven.

## Eerste keer inrichten

1. **Instellingen** &rarr; controleer bedrijfsgegevens, btw-nummer, KvK en IBAN.
2. Vul bij **Laatst gebruikte nummer** het laatste factuurnummer in dat je buiten dit
   systeem al hebt verstuurd (bijvoorbeeld `6` als je laatste factuur F00006 was). De
   reeks loopt dan door en de teller kan daarna alleen nog omhoog.
3. **Klanten** &rarr; klant aanmaken, met per klant een of meer **projecten**. De
   projectcode komt in de kolom *Code* op de factuur en groepeert je uren.

## Hoe ik het gebruik

**Maandelijks factureren.** Uren boeken onder *Uren*, dan *Factuur uit uren* voor een
klant en een periode: één regel per project met de opgetelde uren. Nakijken, eventueel
regels bijplakken, dan *Definitief maken*. Dat kent het nummer toe, schrijft de pdf weg
en zet de factuur op slot. Nog sneller voor een vaste klant: een eerdere factuur openen
en *Dupliceren*.

**Kosten.** Bonnetje in de `inbox`-map (of direct uploaden bij het boeken). Kosten boeken
met de juiste btw-behandeling &mdash; binnenlands, verlegd, EU-verwerving of invoer. Bij
een aanschaf boven de investeringsgrens vraagt het programma of je hem wilt activeren en
afschrijven.

**Elk kwartaal.** *Btw-aangifte* &rarr; kwartaal kiezen. Je krijgt elke rubriek (1a t/m
5b) met het bedrag dat in het portaal van de Belastingdienst moet &mdash; in **hele
euro's**, afgerond in je eigen voordeel zoals de Belastingdienst toestaat (te betalen naar
beneden, voorbelasting naar boven), met het exacte bedrag tot op de cent ernaast. 5a en
het saldo zijn de som van de *afgeronde* regels, zodat het formulier op zichzelf klopt.
Verder een controlelijst met wat er nog open staat, en per rubriek een doorklik naar de
facturen en bonnen die het bedrag vormen. Overtypen in het portaal, daarna hier
*Markeer als ingediend*. Vanaf dat
moment is het kwartaal vergrendeld: een latere factuur of bon met een datum in die
periode verschijnt als **correctie**, met het advies of het een suppletie moet zijn of in
de volgende aangifte mag.

Heb je EU-klanten, dan staat de **ICP-opgaaf** eronder; die dien je apart in.

## Wat het programma bewaakt

- **Factuurnummers zijn doorlopend en zonder gaten.** Het nummer wordt pas toegekend bij
  *definitief maken*, in dezelfde transactie, met een uniciteitsconstraint als vangnet.
  Een weggegooid concept verbruikt geen nummer.
- **Een definitieve factuur is onveranderlijk.** Corrigeren gaat via een creditfactuur.
  De pdf die verstuurd is, wordt nooit opnieuw gegenereerd.
- **Bedragen zijn hele centen.** Nergens een float. `round_half_up` weigert zelfs een
  float, omdat zo'n waarde betekent dat er ergens `/` staat waar `Decimal` hoort.
- **Btw wordt per tarief over de opgetelde grondslag berekend**, niet per regel. Daarom
  klopt het totalenblok op de factuur tot op de cent.
- **Niets wordt echt verwijderd.** Alles krijgt `deleted_at`; de Belastingdienst wil zeven
  jaar historie.
- **Een ingediend kwartaal verandert niet stilletjes.** De cijfers zoals ingediend worden
  bewaard, en elk verschil daarna is zichtbaar als correctie.

## Belastingcijfers

Tarieven, drempels en aftrekposten staan in [`app/taxyears.py`](app/taxyears.py), met het
jaar erbij, nooit los in de code. Elk jaar in januari controleren bij de Belastingdienst
en `verified=True` zetten. Zolang dat niet gebeurd is, noemt het programma alles wat
ermee berekend wordt een schatting. **2026 is geverifieerd** tegen de bronnen die in dat
bestand bij naam genoemd staan; de eerdere jaren nog niet.

### Wat er te reserveren valt

Het dashboard rekent de hele keten door in
[`app/services/income_tax.py`](app/services/income_tax.py), op basis van de verwachte
jaarwinst (want de schijven en heffingskortingen zijn jaarbedragen):

```
winst uit onderneming
  - zelfstandigenaftrek        alleen bij het urencriterium van 1.225 uur
  - startersaftrek             optioneel
= winst na ondernemersaftrek
  - MKB-winstvrijstelling      12,7% in 2026
= belastbare winst
  -> box 1 in schijven         35,75% / 37,56% / 49,50%
  - algemene heffingskorting   max 3.115, afbouw 6,398% vanaf 29.736
  - arbeidskorting             opbouw in 3 fases tot 5.685, daarna afbouw
= inkomstenbelasting           nooit onder nul
  + Zvw-bijdrage               4,85% over de belastbare winst, tot 79.409
```

Bij €40.000 winst komt dat op ongeveer €5.445 (13,6%), niet op de 35% die een vuistregel
zou zeggen. De volledige berekening staat regel voor regel op het dashboard, zodat je hem
kunt narekenen in plaats van moeten geloven.

**Wat er níét in zit**, en waarom het een schatting blijft: ander inkomen, een fiscale
partner, hypotheekrente, lijfrente of giften, box 2 en box 3, en de tariefsaanpassing
boven de hoogste schijf. Heffingskortingen worden als niet-uitbetaalbaar behandeld.

**De btw-bedragen zijn exact. De inkomstenbelastingcijfers zijn een indicatie om mee te
beginnen, geen belastingadvies.**

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

166 tests. De belangrijkste zitten in
[`tests/test_vat_return.py`](tests/test_vat_return.py): die lezen als de specificatie van
wat dit programma over de Nederlandse btw gelooft, scenario voor scenario. Verder
[`tests/test_money.py`](tests/test_money.py) voor afronding,
[`tests/test_invoices.py`](tests/test_invoices.py) voor nummering en onveranderlijkheid,
en [`tests/test_end_to_end.py`](tests/test_end_to_end.py) voor een heel kwartaal door de
webinterface heen. De fixtures rekenen met verzonnen bedrijven:
[`tests/test_no_personal_data.py`](tests/test_no_personal_data.py) faalt als er ergens een
btw-nummer, IBAN, e-mailadres of telefoonnummer in de code belandt.

## Opbouw

```
app/
  money.py        centen, Nederlandse notatie, afronding
  vat.py          btw-behandelingen en hun rubriek in de aangifte
  taxyears.py     tarieven en drempels per jaar
  models.py       het datamodel
  services/       invoices.py, expenses.py, vat_return.py  <- hier zit de logica
  pdf/            de factuur-pdf
  web/            FastAPI-routes en Jinja-templates
tools/            run.py, backup.py, maak_zip.py
```

Er is bewust **geen grootboek met journaalposten**: voor een eenmanszaak is een
gecategoriseerde lijst van inkomsten en uitgaven genoeg, zolang de kwartaal- en
jaarcijfers kloppen.

## Nog niet gebouwd

Bankafschriften importeren en afletteren, het jaaroverzicht voor de IB, offertes,
terugkerende facturen, en de betaal-QR op de factuur. Het datamodel houdt er al rekening
mee; de schermen ontbreken nog.

## Hoe dit gebouwd is

[`PROMPT.md`](PROMPT.md) is de opdracht waarmee dit programma gebouwd is: wat het moet
kunnen, welke belastingregels er gelden, en wat er expliciet níét in moet. Dat bestand
staat er bewust nog in. Het leest als de specificatie, het legt uit waarom sommige dingen
zo zijn, en een deel ervan is nog niet gebouwd &mdash; zie *Nog niet gebouwd*.

## Licentie en aansprakelijkheid

MIT, zie [`LICENSE`](LICENSE). Doe ermee wat je wilt.

Wel dit: het is boekhoudsoftware die één persoon voor zichzelf geschreven heeft, en de
MIT-licentie zegt niet voor niets *without warranty of any kind*. Je blijft zelf
verantwoordelijk voor je eigen aangifte. De btw-bedragen zijn exact bedoeld en getest,
maar controleer ze de eerste keer met de hand tegen je eigen facturen. De
inkomstenbelastingcijfers zijn een indicatie om mee te beginnen, geen belastingadvies.
Tarieven en drempels veranderen elk jaar: kijk in [`app/taxyears.py`](app/taxyears.py) of
het jaar dat jij gebruikt op `verified=True` staat.
