# Menedżer Turnieju

Aplikacja desktopowa do prowadzenia turnieju piłkarskiego dla **12 drużyn**: od
rejestracji drużyn i zawodników, przez losowanie grup i fazę grupową
(system każdy z każdym), aż po trzy równoległe drabinki pucharowe wyłaniające
końcową klasyfikację miejsc 1–12.

**Najważniejsze funkcje:**

- drużyny i zawodnicy (składy 5–10 osób), transfery z historią do startu fazy pucharowej;
- losowanie grup i terminarz z naprzemiennym przydziałem gospodarza (najwyżej dwa mecze
  z rzędu u siebie lub na wyjeździe);
- termin (data i godzina) każdego meczu ustawiany z kalendarza;
- wyniki ze strzelcami, tabele grup, klasyfikacja strzelców z miejscami ex aequo;
- faza pucharowa z rzutami karnymi — pełny przebieg serii, który **nie** wlicza się
  do klasyfikacji strzelców;
- **grafiki PNG na Facebooka**: kolejka (wyniki + tabele), kolejka jednej grupy,
  faza pucharowa, klasyfikacja strzelców;
- eksport i import turnieju do pliku `.json` (kopia zapasowa / przeniesienie na inny komputer);
- jasny i ciemny motyw (zapamiętywany między uruchomieniami).

Dalsza część dokumentacji koncentruje się na warstwie technicznej — przede wszystkim
na modelu danych i sposobie realizacji operacji w bazie danych.

---

## Pobranie gotowego programu (Windows)

Gotowa wersja nie wymaga instalacji Pythona:

1. Pobierz `Menedzer-Turnieju-vX.Y.zip` z zakładki
   [Releases](https://github.com/migrabos/tournament-management-app/releases).
2. Rozpakuj do zwykłego folderu (np. `Dokumenty\Menedżer Turnieju`) — **nie** do
   `C:\Program Files`, bo program zapisuje dane obok siebie.
3. Uruchom `Menedżer Turnieju.exe`.

Szczegóły (gdzie są dane, aktualizacja, rozwiązywanie problemów) są w pliku
[`INSTRUKCJA.txt`](INSTRUKCJA.txt) dołączonym do paczki.
Wymagania: Windows 10 lub 11 (64-bit).

---

## 1. Wykorzystywane technologie

| Warstwa | Technologia |
|---|---|
| Język | **Python 3.10+** |
| Baza danych | **SQLite 3** |
| GUI i grafiki | **PySide6** (Qt for Python), rysowanie grafik przez `QPainter` |
| Testy | **unittest** (biblioteka standardowa) |
| Paczka `.exe` | **PyInstaller** (tryb folderu) |

---

## 2. Model / schemat bazy danych

![Schemat bazy danych](docs/schema.png)

*Diagram jest generowany automatycznie z `db/schema.sql` — po zmianie schematu
wystarczy uruchomić `python -m tools.schema_diagram`.*

Baza składa się z **7 tabel**, **5 widoków** i **8 triggerów**. Poniżej opis encji.

### 2.1. Tabela `tournament`

*Opis: Turniej i jego stan w postaci automatu skończonego `SETUP → GROUP → KO → FINISHED`. Stan steruje tym, jakie operacje są dozwolone (np. losowanie i usuwanie zawodników tylko w `SETUP`, transfery tylko przed `KO`).*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator turnieju (PK) |
| name | TEXT | Nazwa turnieju (NOT NULL) |
| state | TEXT | Stan turnieju: `SETUP`/`GROUP`/`KO`/`FINISHED` (NOT NULL, DEFAULT `SETUP`, CHECK) |
| created_at | DATETIME | Data utworzenia (NOT NULL, DEFAULT `CURRENT_TIMESTAMP`) |

### 2.2. Tabela `team`

*Opis: Drużyna należąca do turnieju. Para `(tournament_id, name)` jest unikalna.*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator drużyny (PK) |
| tournament_id | INTEGER | Turniej drużyny (NOT NULL, FK → tournament.id, ON DELETE CASCADE) |
| name | TEXT | Nazwa drużyny (NOT NULL) |
| group_name | TEXT | Grupa `A`/`B`; `NULL` do czasu losowania (CHECK) |

### 2.3. Tabela `player`

*Opis: Zawodnik przypisany do drużyny. Zmiana `team_id` oznacza transfer (obsługiwany triggerami).*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator zawodnika (PK) |
| team_id | INTEGER | Drużyna zawodnika (NOT NULL, FK → team.id, ON DELETE CASCADE) |
| name | TEXT | Imię i nazwisko zawodnika (NOT NULL) |

### 2.4. Tabela `match`

*Opis: Pojedynczy mecz. Pole `stage` rozróżnia fazę grupową od 9 etapów pucharowych w trzech drabinkach (TOP/MID/BOT: półfinał, finał, mecz o miejsce).*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator meczu (PK) |
| tournament_id | INTEGER | Turniej meczu (NOT NULL, FK → tournament.id, ON DELETE CASCADE) |
| stage | TEXT | Etap: `GROUP` lub etap KO, np. `SF_TOP`/`FINAL_TOP`/`THIRD_PLACE` (NOT NULL, CHECK) |
| group_name | TEXT | Grupa `A`/`B` dla meczu grupowego; `NULL` dla KO (CHECK) |
| round | INTEGER | Numer kolejki fazy grupowej; `NULL` dla meczów KO |
| home_team_id | INTEGER | Gospodarz (FK → team.id, ON DELETE SET NULL) |
| away_team_id | INTEGER | Gość (FK → team.id, ON DELETE SET NULL) |
| home_score | INTEGER | Bramki gospodarza (CHECK ≥ 0) |
| away_score | INTEGER | Bramki gościa (CHECK ≥ 0) |
| winner_pen | INTEGER | Rozstrzygnięcie po karnych: 0 = gospodarz, 1 = gość, `NULL` = bez karnych (CHECK) |
| played | INTEGER | Czy rozegrany: 0/1 (NOT NULL, DEFAULT 0, CHECK) |
| scheduled_at | TEXT | Termin meczu `RRRR-MM-DD GG:MM` ustawiany ręcznie; `NULL` = nieustalony |

### 2.5. Tabela `goal`

*Opis: Pojedyncza bramka z gry — powiązanie meczu ze strzelcem. Liczba rekordów meczu musi zgadzać się z sumą wyniku (walidowane w warstwie serwisu).*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator bramki (PK) |
| match_id | INTEGER | Mecz, w którym padła (NOT NULL, FK → match.id, ON DELETE CASCADE) |
| scorer_id | INTEGER | Strzelec (NOT NULL, FK → player.id, ON DELETE CASCADE) |

### 2.6. Tabela `penalty_kick`

*Opis: Pojedynczy strzał w serii rzutów karnych po remisie w meczu pucharowym. Celowo osobna tabela, a nie rodzaj bramki w `goal` — dzięki temu karne z definicji nie trafiają do klasyfikacji strzelców ani statystyk bramek.*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator strzału (PK) |
| match_id | INTEGER | Mecz (NOT NULL, FK → match.id, ON DELETE CASCADE) |
| kick_no | INTEGER | Kolejność strzału w serii (NOT NULL, CHECK ≥ 1, `UNIQUE (match_id, kick_no)`) |
| player_id | INTEGER | Wykonawca (NOT NULL, FK → player.id, ON DELETE CASCADE) |
| scored | INTEGER | 1 = gol, 0 = pudło/obrona (NOT NULL, CHECK) |

### 2.7. Tabela `transfer`

*Opis: Dziennik audytu transferów. Nie jest wypełniany ręcznie — wiersze wstawia automatycznie trigger po zmianie `team_id` zawodnika.*

| Kolumna | Typ | Opis |
|---|---|---|
| id | INTEGER | Identyfikator transferu (PK) |
| tournament_id | INTEGER | Turniej transferu (NOT NULL, FK → tournament.id, ON DELETE CASCADE) |
| player_id | INTEGER | Przeniesiony zawodnik (NOT NULL, FK → player.id, ON DELETE CASCADE) |
| from_team_id | INTEGER | Drużyna źródłowa (NOT NULL, FK → team.id, ON DELETE CASCADE) |
| to_team_id | INTEGER | Drużyna docelowa (NOT NULL, FK → team.id, ON DELETE CASCADE) |
| transferred_at | DATETIME | Data transferu (NOT NULL, DEFAULT `CURRENT_TIMESTAMP`) |

### Reguły integralności wymuszane w bazie

Model celowo przenosi **reguły biznesowe do schematu**, aby były nienaruszalne
niezależnie od tego, która część kodu modyfikuje dane:

- **Więzy `CHECK`** — spójność pojedynczego wiersza, np.:
  - mecz grupowy musi mieć grupę, mecz KO nie może jej mieć;
  - mecz „rozegrany” (`played=1`) musi mieć oba wyniki, „nierozegrany” — żadnego;
  - karne (`winner_pen`) dozwolone tylko dla remisu w fazie pucharowej;
  - drużyna nie może grać sama ze sobą; wyniki nieujemne.
- **Klucze obce z `ON DELETE`** — kaskady (`CASCADE`) i odpięcia (`SET NULL`)
  utrzymują spójność referencyjną przy usuwaniu turnieju/drużyny.
- **`UNIQUE`** — brak zdublowanych nazw drużyn w turnieju (`tournament_id, name`)
  i numerów strzałów w serii karnych (`match_id, kick_no`).

### Triggery (logika w bazie)

| Trigger | Moment | Reguła |
|---|---|---|
| `trg_player_squad_limit` | BEFORE INSERT player | Limit składu: maks. 10 zawodników w drużynie. |
| `trg_transfer_audit` | AFTER UPDATE player.team_id | Automatyczny wpis do dziennika `transfer`. |
| `trg_transfer_window` | BEFORE UPDATE player.team_id | Blokada transferów po starcie fazy KO. |
| `trg_transfer_min_squad` | BEFORE UPDATE player.team_id | Drużyna źródłowa nie może spaść poniżej 5 zawodników. |
| `trg_goal_scorer_valid` | BEFORE INSERT goal | Strzelec musi grać w jednej z drużyn meczu. |
| `trg_penalty_kick_valid` | BEFORE INSERT penalty_kick | Strzał tylko w meczu rozstrzygniętym karnymi; wykonawca z jednej z drużyn meczu. |
| `trg_match_teams_same_tournament_*` | BEFORE INSERT/UPDATE match | Obie drużyny meczu muszą należeć do tego samego turnieju. |

### Widoki (warstwa odczytu)

| Widok | Zawartość |
|---|---|
| `v_group_table` | Tabela grupy: rozegrane, W/R/P, bramki strzelone/stracone, bilans, punkty. |
| `v_scorers` | Klasyfikacja strzelców per turniej (bramki z gry, bez rzutów karnych w serii). |
| `v_shootout_score` | Wynik serii rzutów karnych meczu (gole gospodarza i gościa). |
| `v_match_schedule` | Terminarz z nazwami drużyn, terminem i wynikiem serii karnych. |
| `v_transfer_history` | Historia transferów z nazwami zawodnika i drużyn. |

---

## 3. Realizacja operacji w bazie danych

### 3.1. Połączenie i konfiguracja (`db/init.py`)

Każde połączenie konfiguruje dwa istotne PRAGMA:

```python
conn.execute("PRAGMA foreign_keys = ON")    # SQLite domyślnie nie egzekwuje kluczy obcych
conn.execute("PRAGMA journal_mode = WAL")    # Write-Ahead Logging
```

- **`foreign_keys = ON`** — SQLite dla zgodności wstecznej domyślnie nie wymusza
  kluczy obcych; włączamy egzekwowanie jawnie przy każdym połączeniu.
- **`journal_mode = WAL`** — tryb Write-Ahead Logging pozwala czytać bazę w
  trakcie zapisu (czytelnicy nie blokują pisarza i odwrotnie), co poprawia
  współbieżność GUI ↔ operacje zapisu.

Ustawiono też `row_factory = sqlite3.Row`, dzięki czemu wiersze są dostępne
jak słowniki (`row["points"]`) — czytelniej niż indeksy pozycyjne.

### 3.2. Bezpieczeństwo zapytań

Wszystkie zapytania używają parametrów `?` zamiast sklejania stringów —
**ochrona przed SQL injection** i poprawna obsługa typów:

```python
conn.execute("INSERT INTO team (tournament_id, name) VALUES (?, ?)",
             (tournament_id, name))
```

### 3.3. Transakcje atomowe (`app/services/`)

Operacje wieloetapowe są opakowane w jawne transakcje `BEGIN IMMEDIATE … COMMIT`
z `rollback()` na wyjątku. Wzorzec:

```python
conn = get_connection()
try:
    conn.execute("BEGIN IMMEDIATE")
    ...                  # wiele instrukcji
    conn.commit()
except Exception:
    conn.rollback()      # albo wszystko, albo nic
    raise
finally:
    conn.close()
```

Przykłady operacji atomowych:
- **Losowanie grup** (`draw.py`) — wyczyszczenie grup, przydział 6+6 drużyn i
  zmiana stanu turnieju to jedna transakcja.
- **Generowanie terminarza** (`schedule.py`) — wszystkie mecze round-robin obu
  grup wstawiane w jednej transakcji.
- **Zapis wyniku meczu** (`match_result.py`) — wynik, wszyscy strzelcy oraz
  (w fazie pucharowej) cała seria rzutów karnych zapisywane razem. Zwycięzca po
  karnych jest wyliczany z przebiegu serii i sprawdzany przed zapisem; edycja
  wyniku usuwa i wstawia strzelców oraz serię od nowa.
- **Zatwierdzenie fazy grupowej** (`confirm_group_stage`) — sprawdzenie kompletu
  wyników, rozstawienie trzech drabinek KO (`seed_brackets`) i zmiana stanu na
  `KO` w jednej transakcji. Od tej chwili wyniki grup są zablokowane.
- **Import turnieju** (`backup.py`) — cały turniej z pliku `.json` (drużyny,
  zawodnicy, mecze, bramki, karne, transfery) wstawiany jako nowy turniej w jednej
  transakcji; przy błędzie w bazie nie zostaje nic.

### 3.4. Kontrola współbieżności

Transfer zawodnika to **zasób limitowany**:
do drużyny z jednym wolnym miejscem (limit składu = 10) dwóch użytkowników
może próbować przenieść zawodnika jednocześnie. Dokładnie jeden może wygrać.

Zastosowano dwie nakładające się techniki (`transfer.py`):

1. **`BEGIN IMMEDIATE`** — od razu bierze blokadę zapisu na bazie, więc druga
   transakcja czeka (lub dostaje `database is locked`).
2. **Warunkowy UPDATE (compare-and-set)** — kluczowy mechanizm:

```python
rows_updated = conn.execute(
    "UPDATE player SET team_id = ? WHERE id = ? AND team_id = ?",
    (to_team_id, player_id, from_team_id)
).rowcount

if rows_updated == 0:
    raise ValueError("Zawodnik został właśnie przeniesiony — spróbuj ponownie.")
```

Warunek `AND team_id = from_team_id` sprawia, że jeśli inna transakcja zdążyła
przenieść zawodnika, `UPDATE` dotknie **0 wierszy** i operacja jest odrzucana —
decyzja podejmowana jest na podstawie aktualnego stanu rekordu.

3. **Mechanizm retry** (`with_retry`) — przy `sqlite3.OperationalError:
   database is locked` operacja jest ponawiana z rosnącym opóźnieniem
   (backoff), co pozwala obsłużyć przejściowe kolizje blokad WAL.

Poprawność potwierdza test `test_two_users_compete_for_last_squad_slot`.

### 3.5. Logika w bazie zamiast w aplikacji

Przeniesiono część reguł do bazy (triggery + widoki), zamiast
implementować je w Pythonie:

- **Audyt transferów** realizuje trigger `trg_transfer_audit` — warstwa serwisu
  wykonuje sam `UPDATE player`, a wpis historii powstaje automatycznie. Dzięki
  temu **każda** zmiana drużyny zawodnika jest zarejestrowana, niezależnie od
  ścieżki kodu.
- **Walidacje** (limit/minimum składu, okno transferowe, poprawność strzelca
  i wykonawcy karnego) są w triggerach — stanowią ostateczną linię obrony nawet
  gdyby walidacja aplikacyjna została pominięta. Warstwa serwisu sprawdza je też
  wcześniej, by zwrócić czytelny komunikat błędu.
- **Usuwanie zawodników** jest dozwolone tylko w stanie `SETUP` (`player_dao`):
  później kaskada usunęłaby jego bramki, a wyniki meczów zostałyby — strzelcy
  przestaliby zgadzać się z wynikami.

### 3.6. Raporty agregujące (`app/reports/`)

Raporty to złożone zapytania **z całą logiką po stronie SQL** — Python tylko
mapuje wynik na listę słowników. Wykorzystane konstrukcje:

- **`JOIN`** wielu tabel (np. `goal` → `match` → `player` → `team`).
- **`GROUP BY` + funkcje agregujące** (`COUNT`, `SUM`, `AVG`, `ROUND`).
- **Wyrażenia warunkowe** `CASE WHEN` do liczenia punktów i bilansu.
- **CTE (`WITH …`)** — np. `team_stats` buduje pomocniczy zbiór „gier” drużyny
  (raz jako gospodarz, raz jako gość), a `group_table_after_round` liczy tabelę
  grupy tylko z meczów do wskazanej kolejki (na grafikę kolejki).
- **Funkcja okna `RANK() OVER`** — miejsca ex aequo w klasyfikacji strzelców
  (równa liczba goli = to samo miejsce: 1, 1, 3, …).
- **Widoki** jako gotowe, reużywalne źródła (`v_group_table`, `v_scorers` …),
  z sortowaniem wg regulaminu: punkty → różnica bramek → bramki strzelone.

### 3.7. Algorytmika wspierana bazą

- **Algorytm Bergera** (`schedule.py`) generuje kolejki systemu „każdy z każdym”
  dla 6 drużyn (rotacja stolika). Gospodarz dobierany jest naprzemiennie — każda
  drużyna gra 2 lub 3 razy u siebie i najwyżej dwa mecze z rzędu u siebie lub na
  wyjeździe. Wynik trafia do tabeli `match`.
- **Propagacja drabinki KO** (`bracket.py`) — po wpisaniu wyniku półfinału
  zwycięzca (także po karnych) trafia do finału, a przegrany do meczu o miejsce;
  klasyfikacja po grupie pobierana jest z widoku `v_group_table`.

### 3.8. Grafiki do publikacji (`app/ui/graphics.py`)

Grafiki PNG są rysowane przez `QPainter` na podstawie widoków i raportów
(terminarz, `group_table_after_round`, klasyfikacja strzelców). Mają stały styl
niezależny od motywu aplikacji, a dłuższy bok obrazu ma zawsze **2048 px** —
to limit, do którego Facebook zmniejsza zdjęcia, więc nie są ponownie skalowane
i tekst pozostaje ostry. Pliki zapisują się do `exports/grafiki/<turniej>/`.

---

## 4. Uruchomienie ze źródeł

### Wymagania
- Python **3.10 lub nowszy**
- System: Windows / Linux / macOS (grafiki korzystają z czcionki Segoe UI —
  na innych systemach Qt podstawi zbliżoną)

### Instalacja i start

```bash
# 1. (zalecane) wirtualne środowisko
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 2. instalacja zależności (GUI)
pip install -r requirements.txt

# 3. uruchomienie aplikacji
python main.py
```

Przy pierwszym uruchomieniu `main.py` automatycznie tworzy bazę
`db/tournament.db` ze schematu `db/schema.sql` (jeśli plik jeszcze nie istnieje).
Po zmianie schematu istniejącą bazę trzeba utworzyć od nowa — dane można
wcześniej wyeksportować do `.json` i zaimportować z powrotem.

### Ręczna inicjalizacja bazy (opcjonalnie)

```bash
python -m db.init
```

### Uruchomienie testów

```bash
python -m unittest discover -s tests
```

### Budowanie paczki `.exe`

```bash
pip install pyinstaller
python -m PyInstaller "Menedżer Turnieju.spec" --noconfirm
```

Wynik trafia do `dist/Menedżer Turnieju/` (program, folder `_internal` z
bibliotekami oraz `INSTRUKCJA.txt`, `LICENSE`, `THIRD-PARTY-NOTICES.txt`).
Ten folder pakuje się do ZIP i dołącza do wydania na GitHubie.

---

## 5. Licencja

Projekt jest udostępniony na licencji **MIT** — zob. [`LICENSE`](LICENSE).

Aplikacja korzysta z **Qt for Python (PySide6)** na licencji **LGPL-3.0**;
informacje o bibliotekach zewnętrznych: [`THIRD-PARTY-NOTICES.txt`](THIRD-PARTY-NOTICES.txt).

**Autorzy:** Michał Graboś, Kacper Drożyński
