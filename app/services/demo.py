"""
Przykładowy turniej do przetestowania aplikacji.

Tworzy 12 drużyn (losowo wybrane kluby Ekstraklasy z ich zawodnikami),
losuje grupy, generuje terminarz i rozgrywa część fazy grupowej (domyślnie 3 z 5 kolejek). Użytkownik od razu widzi
wypełnione tabele i może sam wpisać resztę wyników.

Wszystko idzie przez istniejące DAO i serwisy, więc obowiązują te same
reguły i triggery co przy ręcznym zakładaniu turnieju.
"""
import random

from app.dao import tournament_dao, team_dao, player_dao
from app.services import draw, schedule, match_result

DEMO_NAME = "Przykładowy turniej"

# Kluby i zawodnicy Ekstraklasy, sezon 2026/27 (składy z jesieni 2026).
# Do turnieju losowanych jest 12 klubów; każdy gra 8 zawodnikami.
SQUADS = {
    "Cracovia": ["Ajdin Hasić", "Filip Marchwiński", "Kacper Śmiglewski", "Mauro Perković",
                 "Lasse Nordås", "Dominik Piła", "Mateusz Skoczylas", "Mateusz Klich"],
    "GKS Katowice": ["Arkadiusz Jędrych", "Maciej Kikolski", "Aleksander Paluszek",
                     "Marcel Wędrychowski", "Adrian Błąd", "Rafał Strączek",
                     "Jakub Kokosiński", "Marcin Wasielewski"],
    "Górnik Zabrze": ["Erik Janža", "Rafał Janicki", "Paweł Bochniewicz", "Kacper Urbański",
                      "Michał Synoś", "Jarosław Kubicki", "Michał Rakoczy", "Ksawery Semik"],
    "Jagiellonia Białystok": ["Taras Romanczuk", "Jesús Imaz", "Dušan Stojinović",
                              "Dimitris Rallis", "Jeremy Agbonifo", "Kamil Jóźwiak",
                              "Zachary Zalewski", "Ousmane Sow"],
    "Korona Kielce": ["Mariusz Stępiński", "Nono", "Dawid Błanik", "Stjepan Davidović",
                      "Martin Remacle", "Xavier Dziekoński", "Patrik Hellebrand", "Ondřej Lingr"],
    "Lech Poznań": ["Mikael Ishak", "Radosław Murawski", "Patrik Wålemark", "Ali Gholizadeh",
                    "Yannick Agnero", "Robert Gumny", "Luis Palma", "Mateusz Skrzypczak"],
    "Legia Warszawa": ["Ivan Brkić", "Paweł Wszołek", "Artur Jędrzejczyk", "Kamil Piątkowski",
                       "Rafał Augustyniak", "Damian Szymański", "Bartosz Kapustka",
                       "Wojciech Urbański"],
    "Motor Lublin": ["Karol Czubak", "Ivo Rodrigues", "Rony Lopes", "Bartosz Bereszyński",
                     "Kamil Lukoszek", "Tin Plavotić", "Mateusz Łęgowski", "Borys Mołdach"],
    "Piast Gliwice": ["Jakub Czerwiński", "Marcel Mendes-Dudziński", "Jakub Łabojko",
                      "Oskar Leśniak", "Jorge Félix", "Levis Pitan", "Oliwier Maziarz",
                      "Maciek Kucharski"],
    "Pogoń Szczecin": ["Kamil Grosicki", "Kellyn Acosta", "Rajmund Molnár", "Filip Čuić",
                       "Benjamin Mendy", "Jean-Pierre Nsame", "Paul Mukairu", "Antoni Fojut"],
    "Radomiak Radom": ["Rafał Wolski", "Kryspin Szcześniak", "Cezary Wołowiec", "Adam Żabicki",
                       "Mikołaj Molendowski", "Bartłomiej Gradecki", "Szymon Kilianek",
                       "Filip Koperski"],
    "Raków Częstochowa": ["Fran Tudor", "Stratos Svarnas", "Mahir Emreli", "Nils Zätterström",
                          "Dieudonné Debohi", "Ádin Molnár", "Bogdan Racovițan", "Tomasz Pieńko"],
    "Śląsk Wrocław": ["Michał Szromnik", "Hubert Śliczniak", "Jan Jurčec", "Damian Warchoł",
                      "Michał Mokrzycki", "Piotr Samiec-Talar", "Patryk Sokołowski",
                      "Przemysław Banaszak"],
    "Widzew Łódź": ["Juljan Shehu", "Bartłomiej Drągowski", "Karol Świderski",
                    "Mariusz Fornalczyk", "Przemysław Wiśniewski", "Sebastian Bergier",
                    "Emil Kornvig", "Giannis Papanikolaou"],
    "Wieczysta Kraków": ["Mikkel Maigaard", "Efthymis Koulouris", "Lucas Piazon",
                         "Lisandro Semedo", "Nikola Čavlina", "Mateusz Wieteska",
                         "Antoni Mikułko", "Bartosz Białek"],
    "Wisła Kraków": ["Alan Uryga", "Ángel Rodado", "Marc Carbó", "Frederico Duarte",
                     "Julián Lelieveld", "Patryk Letkiewicz", "Kacper Duda", "James Igbekeme"],
    "Wisła Płock": ["Łukasz Sekulski", "Rafał Leszczyński", "Krystian Pomorski", "Olaf Kobacki",
                    "Said Hamulić", "Dani Pacheco", "Deni Jurić", "Sidnei Tavares"],
    "Zagłębie Lubin": ["Damian Dąbrowski", "Arkadiusz Woźniak", "Filip Szymczak",
                       "Dominik Hładun", "Jasmin Burić", "Josip Ćorluka", "Michalis Kosidis",
                       "Kamil Nowogoński"],
}
TEAMS_IN_TOURNAMENT = 12

# Rozkład liczby bramek jednej drużyny w meczu (0 i 1 najczęściej).
GOAL_WEIGHTS = [28, 32, 22, 12, 6]  # 0, 1, 2, 3, 4


def _unique_name() -> str:
    """'Przykładowy turniej', a jeśli już jest — 'Przykładowy turniej (2)' itd."""
    existing = {t["name"] for t in tournament_dao.list_tournaments()}
    if DEMO_NAME not in existing:
        return DEMO_NAME
    n = 2
    while f"{DEMO_NAME} ({n})" in existing:
        n += 1
    return f"{DEMO_NAME} ({n})"


def create_demo_tournament(rounds_played: int = 3, seed: int | None = None) -> int:
    """
    Tworzy przykładowy turniej i zwraca jego id.
    rounds_played: ile kolejek fazy grupowej rozegrać (0-5).
    seed: ziarno losowania wyników (dla powtarzalności, np. w testach).
    """
    rng = random.Random(seed)

    tid = tournament_dao.create_tournament(_unique_name())

    teams = sorted(rng.sample(list(SQUADS), TEAMS_IN_TOURNAMENT))
    players: dict[int, list[int]] = {}
    for team_name in teams:
        team_id = team_dao.add_team(tid, team_name)
        players[team_id] = [player_dao.add_player(team_id, name) for name in SQUADS[team_name]]

    draw.draw_groups(tid)
    schedule.generate_group_schedule(tid)

    for fx in schedule.get_schedule(tid):
        if fx["stage"] != "GROUP" or fx["round"] > rounds_played:
            continue
        home_goals = rng.choices(range(len(GOAL_WEIGHTS)), GOAL_WEIGHTS)[0]
        away_goals = rng.choices(range(len(GOAL_WEIGHTS)), GOAL_WEIGHTS)[0]
        scorers = (
            [rng.choice(players[fx["home_team_id"]]) for _ in range(home_goals)]
            + [rng.choice(players[fx["away_team_id"]]) for _ in range(away_goals)]
        )
        match_result.save_match_result(fx["match_id"], home_goals, away_goals, scorers)

    return tid