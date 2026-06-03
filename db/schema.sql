PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- TABELE

CREATE TABLE tournament (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'SETUP'
                CHECK (state IN ('SETUP','GROUP','KO','FINISHED')),
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE team (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id  INTEGER NOT NULL,
    name           TEXT    NOT NULL,
    group_name     TEXT    CHECK (group_name IN ('A','B')),
    UNIQUE (tournament_id, name),
    FOREIGN KEY (tournament_id) REFERENCES tournament(id) ON DELETE CASCADE
);

CREATE TABLE player (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id  INTEGER NOT NULL,
    name     TEXT    NOT NULL,
    FOREIGN KEY (team_id) REFERENCES team(id) ON DELETE CASCADE
);

CREATE TABLE match (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id  INTEGER NOT NULL,
    stage          TEXT    NOT NULL
                   CHECK (stage IN (
                       'GROUP',
                       'SF_TOP','FINAL_TOP','THIRD_PLACE',
                       'SF_MID','FINAL_MID','SEVENTH_PLACE',
                       'SF_BOT','FINAL_BOT','ELEVENTH_PLACE'
                   )),
    group_name     TEXT    CHECK (group_name IN ('A','B')),
    home_team_id   INTEGER,
    away_team_id   INTEGER,
    home_score     INTEGER CHECK (home_score >= 0),
    away_score     INTEGER CHECK (away_score >= 0),
    winner_pen     INTEGER CHECK (winner_pen IN (NULL, 0, 1)),
                            -- 0 = home wygrał karne, 1 = away wygrał karne
    played         INTEGER NOT NULL DEFAULT 0 CHECK (played IN (0,1)),

    CHECK (home_team_id IS NULL OR away_team_id IS NULL OR home_team_id != away_team_id),
    CHECK ( (stage = 'GROUP' AND group_name IS NOT NULL)
         OR (stage <> 'GROUP' AND group_name IS NULL) ),
    CHECK ( (played = 0 AND home_score IS NULL AND away_score IS NULL)
         OR (played = 1 AND home_score IS NOT NULL AND away_score IS NOT NULL) ),
    CHECK ( winner_pen IS NULL
         OR (stage <> 'GROUP' AND played = 1 AND home_score = away_score) ),

    FOREIGN KEY (tournament_id) REFERENCES tournament(id) ON DELETE CASCADE,
    FOREIGN KEY (home_team_id)  REFERENCES team(id)       ON DELETE SET NULL,
    FOREIGN KEY (away_team_id)  REFERENCES team(id)       ON DELETE SET NULL
);

CREATE TABLE goal (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   INTEGER NOT NULL,
    scorer_id  INTEGER NOT NULL,
    FOREIGN KEY (match_id)  REFERENCES match(id)  ON DELETE CASCADE,
    FOREIGN KEY (scorer_id) REFERENCES player(id) ON DELETE CASCADE
);

CREATE TABLE transfer (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id   INTEGER  NOT NULL,
    player_id       INTEGER  NOT NULL,
    from_team_id    INTEGER  NOT NULL,
    to_team_id      INTEGER  NOT NULL,
    transferred_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (from_team_id <> to_team_id),
    FOREIGN KEY (tournament_id) REFERENCES tournament(id) ON DELETE CASCADE,
    FOREIGN KEY (player_id)     REFERENCES player(id)     ON DELETE CASCADE,
    FOREIGN KEY (from_team_id)  REFERENCES team(id)       ON DELETE CASCADE,
    FOREIGN KEY (to_team_id)    REFERENCES team(id)       ON DELETE CASCADE
);

-- INDEKSY

CREATE INDEX idx_match_tournament_stage ON match(tournament_id, stage);
CREATE INDEX idx_goal_match              ON goal(match_id);
CREATE INDEX idx_goal_scorer             ON goal(scorer_id);
CREATE INDEX idx_player_team             ON player(team_id);
CREATE INDEX idx_transfer_tournament_pl  ON transfer(tournament_id, player_id);

-- TRIGGERY

-- 1. Limit składu drużyny: max 10 zawodników.
CREATE TRIGGER trg_player_squad_limit
BEFORE INSERT ON player
FOR EACH ROW
WHEN (SELECT COUNT(*) FROM player WHERE team_id = NEW.team_id) >= 10
BEGIN
    SELECT RAISE(ABORT, 'Drużyna ma już 10 zawodników (limit składu).');
END;

-- 2. Audyt transferu: po UPDATE team_id w player loguj do `transfer`.
CREATE TRIGGER trg_transfer_audit
AFTER UPDATE OF team_id ON player
FOR EACH ROW
WHEN OLD.team_id <> NEW.team_id
BEGIN
    INSERT INTO transfer (tournament_id, player_id, from_team_id, to_team_id)
    VALUES (
        (SELECT tournament_id FROM team WHERE id = NEW.team_id),
        NEW.id,
        OLD.team_id,
        NEW.team_id
    );
END;

-- 3. Blokada transferu po starcie fazy KO.
CREATE TRIGGER trg_transfer_window
BEFORE UPDATE OF team_id ON player
FOR EACH ROW
WHEN OLD.team_id <> NEW.team_id
 AND (SELECT t.state
        FROM team tm JOIN tournament t ON t.id = tm.tournament_id
       WHERE tm.id = OLD.team_id) IN ('KO','FINISHED')
BEGIN
    SELECT RAISE(ABORT, 'Transfery zablokowane po starcie fazy pucharowej.');
END;

-- 4. Walidacja bramki: strzelec musi grać w jednej z drużyn meczu.
CREATE TRIGGER trg_goal_scorer_valid
BEFORE INSERT ON goal
FOR EACH ROW
WHEN (SELECT p.team_id FROM player p WHERE p.id = NEW.scorer_id)
     NOT IN (
        SELECT m.home_team_id FROM match m WHERE m.id = NEW.match_id
        UNION
        SELECT m.away_team_id FROM match m WHERE m.id = NEW.match_id
     )
BEGIN
    SELECT RAISE(ABORT, 'Strzelec nie należy do żadnej z drużyn tego meczu.');
END;

-- 5. Drużyny meczu muszą należeć do tego samego turnieju co mecz.
CREATE TRIGGER trg_match_teams_same_tournament_ins
BEFORE INSERT ON match
FOR EACH ROW
WHEN (NEW.home_team_id IS NOT NULL
       AND (SELECT tournament_id FROM team WHERE id = NEW.home_team_id) <> NEW.tournament_id)
  OR (NEW.away_team_id IS NOT NULL
       AND (SELECT tournament_id FROM team WHERE id = NEW.away_team_id) <> NEW.tournament_id)
BEGIN
    SELECT RAISE(ABORT, 'Drużyny meczu muszą być z tego samego turnieju co mecz.');
END;

CREATE TRIGGER trg_match_teams_same_tournament_upd
BEFORE UPDATE OF home_team_id, away_team_id ON match
FOR EACH ROW
WHEN (NEW.home_team_id IS NOT NULL
       AND (SELECT tournament_id FROM team WHERE id = NEW.home_team_id) <> NEW.tournament_id)
  OR (NEW.away_team_id IS NOT NULL
       AND (SELECT tournament_id FROM team WHERE id = NEW.away_team_id) <> NEW.tournament_id)
BEGIN
    SELECT RAISE(ABORT, 'Drużyny meczu muszą być z tego samego turnieju co mecz.');
END;

-- WIDOKI

-- Tabela grupy: W/D/L, bramki strzelone/stracone, bilans, punkty.
CREATE VIEW v_group_table AS
WITH per_team AS (
    SELECT t.tournament_id, t.group_name, t.id AS team_id, t.name AS team_name,
           CASE WHEN m.home_team_id = t.id THEN m.home_score ELSE m.away_score END AS gf,
           CASE WHEN m.home_team_id = t.id THEN m.away_score ELSE m.home_score END AS ga
      FROM team t
      JOIN match m ON m.tournament_id = t.tournament_id
                  AND m.stage = 'GROUP'
                  AND m.played = 1
                  AND (m.home_team_id = t.id OR m.away_team_id = t.id)
     WHERE t.group_name IS NOT NULL
)
SELECT tournament_id,
       group_name,
       team_id,
       team_name,
       COUNT(*)                                                AS played,
       SUM(CASE WHEN gf > ga THEN 1 ELSE 0 END)                AS wins,
       SUM(CASE WHEN gf = ga THEN 1 ELSE 0 END)                AS draws,
       SUM(CASE WHEN gf < ga THEN 1 ELSE 0 END)                AS losses,
       COALESCE(SUM(gf), 0)                                    AS goals_for,
       COALESCE(SUM(ga), 0)                                    AS goals_against,
       COALESCE(SUM(gf - ga), 0)                               AS goal_diff,
       SUM(CASE WHEN gf > ga THEN 3 WHEN gf = ga THEN 1 ELSE 0 END) AS points
  FROM per_team
 GROUP BY tournament_id, group_name, team_id, team_name;

-- Klasyfikacja strzelców (per turniej).
CREATE VIEW v_top_scorers AS
SELECT m.tournament_id,
       p.id   AS player_id,
       p.name AS player_name,
       t.id   AS team_id,
       t.name AS team_name,
       COUNT(*) AS goals
  FROM goal g
  JOIN match  m ON m.id = g.match_id
  JOIN player p ON p.id = g.scorer_id
  JOIN team   t ON t.id = p.team_id
 GROUP BY m.tournament_id, p.id, p.name, t.id, t.name;

-- Terminarz: mecze z nazwami drużyn zamiast ID.
CREATE VIEW v_match_schedule AS
SELECT m.id            AS match_id,
       m.tournament_id,
       m.stage,
       m.group_name,
       m.home_team_id,
       ht.name         AS home_team_name,
       m.away_team_id,
       at.name         AS away_team_name,
       m.home_score,
       m.away_score,
       m.winner_pen,
       m.played
  FROM match m
  LEFT JOIN team ht ON ht.id = m.home_team_id
  LEFT JOIN team at ON at.id = m.away_team_id;

-- Historia transferów z nazwami.
CREATE VIEW v_transfer_history AS
SELECT tr.id              AS transfer_id,
       tr.tournament_id,
       tr.transferred_at,
       p.id               AS player_id,
       p.name             AS player_name,
       tr.from_team_id,
       tf.name            AS from_team_name,
       tr.to_team_id,
       tt.name            AS to_team_name
  FROM transfer tr
  JOIN player p  ON p.id  = tr.player_id
  JOIN team   tf ON tf.id = tr.from_team_id
  JOIN team   tt ON tt.id = tr.to_team_id;