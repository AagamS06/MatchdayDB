"""Original synthetic performance profiles using a dated, real-name demo roster.

Club associations are a 2024/2025 illustration. All metrics, valuations and
tactical descriptions are simulated, not measurements of these real players.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, UTC

from database import Database
from errors import MatchdayError
from models import Fixture, Player, PlayerStats, Team, name_key, utc_now

SEED_VERSION = "matchday-demo-v1"
SEED_SEASON = "2024/2025"
TEAMS = [
    (1, "Manchester City", "Man City", "PL"),
    (2, "Arsenal", "Arsenal", "PL"),
    (3, "Liverpool", "Liverpool", "PL"),
    (4, "Chelsea", "Chelsea", "PL"),
    (5, "Manchester United", "Man United", "PL"),
    (6, "Newcastle United", "Newcastle", "PL"),
    (7, "Tottenham Hotspur", "Spurs", "PL"),
    (8, "Aston Villa", "Villa", "PL"),
    (9, "Real Madrid", "Real Madrid", "PD"),
    (10, "Barcelona", "Barcelona", "PD"),
    (11, "Atlético Madrid", "Atlético", "PD"),
    (12, "Bayern Munich", "Bayern", "BL1"),
    (13, "Bayer Leverkusen", "Leverkusen", "BL1"),
    (14, "Paris Saint-Germain", "PSG", "FL1"),
    (15, "Inter Milan", "Inter", "SA"),
    (16, "AC Milan", "Milan", "SA"),
    (17, "Atalanta", "Atalanta", "SA"),
    (18, "Sporting CP", "Sporting", "PPL"),
    (19, "Real Sociedad", "Sociedad", "PD"),
    (20, "RB Leipzig", "Leipzig", "BL1"),
]

# Names, roles, nationalities, club snapshot IDs, birth dates, and original demo bios.
ROSTER = [
    (
        "Alisson Becker",
        "GK",
        "Brazil",
        3,
        "1992-10-02",
        "Sweeper keeper who claims crosses and distributes calmly through the first press.",
    ),
    (
        "Ederson",
        "GK",
        "Brazil",
        1,
        "1993-08-17",
        "Proactive goalkeeper with adventurous positioning and accurate long distribution.",
    ),
    (
        "David Raya",
        "GK",
        "Spain",
        2,
        "1995-09-15",
        "Compact goalkeeper who supports short buildup and commands aerial deliveries.",
    ),
    (
        "Thibaut Courtois",
        "GK",
        "Belgium",
        9,
        "1992-05-11",
        "Penalty-area goalkeeper emphasizing reach, shot stopping and secure handling.",
    ),
    (
        "Gianluigi Donnarumma",
        "GK",
        "Italy",
        14,
        "1999-02-25",
        "Tall shot stopper who protects the goal and intervenes decisively on crosses.",
    ),
    (
        "Mike Maignan",
        "GK",
        "France",
        16,
        "1995-07-03",
        "Sweeper keeper who organizes a high defensive line and initiates fast distribution.",
    ),
    (
        "William Saliba",
        "CB",
        "France",
        2,
        "2001-03-24",
        "Composed centre-back who defends space, recovers in transition and progresses possession under pressure.",
    ),
    (
        "Gabriel Magalhães",
        "CB",
        "Brazil",
        2,
        "1997-12-19",
        "Left-sided centre-back who attacks aerial duels and steps forward to disrupt receiving forwards.",
    ),
    (
        "Virgil van Dijk",
        "CB",
        "Netherlands",
        3,
        "1991-07-08",
        "Aerially commanding centre-back who controls defensive space and switches play from deep.",
    ),
    (
        "Rúben Dias",
        "CB",
        "Portugal",
        1,
        "1997-05-14",
        "Organizing centre-back who protects the box and circulates possession securely.",
    ),
    (
        "Alessandro Bastoni",
        "CB",
        "Italy",
        15,
        "1999-04-13",
        "Left-sided ball-playing defender who carries into midfield and delivers progressive passes.",
    ),
    (
        "Antonio Rüdiger",
        "CB",
        "Germany",
        9,
        "1993-03-03",
        "Aggressive centre-back who closes forwards quickly and covers wide transition spaces.",
    ),
    (
        "Ronald Araújo",
        "CB",
        "Uruguay",
        10,
        "1999-03-07",
        "Powerful recovery defender who competes in isolation and challenges aerial balls.",
    ),
    (
        "Joško Gvardiol",
        "CB",
        "Croatia",
        1,
        "2002-01-23",
        "Left-footed defender who carries through pressure and steps into advanced buildup lanes.",
    ),
    (
        "Trent Alexander-Arnold",
        "RB",
        "England",
        3,
        "1998-10-07",
        "Creative right-back who inverts into midfield and plays diagonal line-breaking passes.",
    ),
    (
        "Achraf Hakimi",
        "RB",
        "Morocco",
        14,
        "1998-11-04",
        "Attacking right-back who overlaps at speed and arrives in the final third.",
    ),
    (
        "Dani Carvajal",
        "RB",
        "Spain",
        9,
        "1992-01-11",
        "Combative right-back who combines on the flank and tracks runners into the box.",
    ),
    (
        "Pedro Porro",
        "RB",
        "Spain",
        7,
        "1999-09-13",
        "Forward-thinking full-back who delivers crosses and passes into the half-space.",
    ),
    (
        "Alphonso Davies",
        "LB",
        "Canada",
        12,
        "2000-11-02",
        "Explosive overlapping full-back who carries the ball long distances and recovers quickly.",
    ),
    (
        "Theo Hernández",
        "LB",
        "France",
        16,
        "1997-10-06",
        "Attacking left-back who drives through open space and creates chances with carries.",
    ),
    (
        "Nuno Mendes",
        "LB",
        "Portugal",
        14,
        "2002-06-19",
        "Dynamic left-back who beats the first defender and covers the flank in transition.",
    ),
    (
        "Federico Dimarco",
        "LB",
        "Italy",
        15,
        "1997-11-10",
        "Creative wing-back who provides width and accurate early deliveries into the area.",
    ),
    (
        "Rodri",
        "DM",
        "Spain",
        1,
        "1996-06-22",
        "Press-resistant deep-lying playmaker who controls tempo, breaks transition lines with progressive passes and protects central space.",
    ),
    (
        "Declan Rice",
        "DM",
        "England",
        2,
        "1999-01-14",
        "Defensive midfielder who wins duels, carries through midfield and covers attacking teammates.",
    ),
    (
        "Martín Zubimendi",
        "DM",
        "Spain",
        19,
        "1999-02-02",
        "Press-resistant holding playmaker who receives between opponents and progresses with short combinations.",
    ),
    (
        "Aurélien Tchouaméni",
        "DM",
        "France",
        9,
        "2000-01-27",
        "Screening midfielder who closes central lanes, wins aerial duels and distributes from deep.",
    ),
    (
        "Joshua Kimmich",
        "DM",
        "Germany",
        12,
        "1995-02-08",
        "Deep-lying organizer who controls buildup with line-breaking passes and quick switches.",
    ),
    (
        "João Palhinha",
        "DM",
        "Portugal",
        12,
        "1995-07-09",
        "Ball-winning defensive midfielder who contests tackles and shields the back line.",
    ),
    (
        "Manuel Ugarte",
        "DM",
        "Uruguay",
        5,
        "2001-04-11",
        "Intense midfield ball winner who presses receivers and recovers loose possession.",
    ),
    (
        "Moisés Caicedo",
        "DM",
        "Ecuador",
        4,
        "2001-11-02",
        "Mobile holding midfielder who receives under pressure, tackles and connects transitions.",
    ),
    (
        "Federico Valverde",
        "CM",
        "Uruguay",
        9,
        "1998-07-22",
        "Box-to-box midfielder with powerful carries, recovery runs and energetic counterpressing.",
    ),
    (
        "Nicolò Barella",
        "CM",
        "Italy",
        15,
        "1997-02-07",
        "Box-to-box midfielder who presses aggressively and creates through quick combinations.",
    ),
    (
        "Frenkie de Jong",
        "CM",
        "Netherlands",
        10,
        "1997-05-12",
        "Press-resistant central midfielder who escapes pressure with carries and controls possession.",
    ),
    (
        "Pedri",
        "CM",
        "Spain",
        10,
        "2002-11-25",
        "Technical central midfielder who receives on the half-turn and finds passes between lines.",
    ),
    (
        "Vitinha",
        "CM",
        "Portugal",
        14,
        "2000-02-13",
        "Press-resistant playmaker who dictates rhythm and links midfield with precise short passing.",
    ),
    (
        "Bruno Guimarães",
        "CM",
        "Brazil",
        6,
        "1997-11-16",
        "Combative central playmaker who protects possession and advances play through midfield.",
    ),
    (
        "Alexis Mac Allister",
        "CM",
        "Argentina",
        3,
        "1998-12-24",
        "Balanced midfielder who presses intelligently and links buildup with progressive passing.",
    ),
    (
        "Ryan Gravenberch",
        "CM",
        "Netherlands",
        3,
        "2002-05-16",
        "Tall central midfielder who turns away from pressure and carries through transition lines.",
    ),
    (
        "Jude Bellingham",
        "AM",
        "England",
        9,
        "2003-06-29",
        "Attacking box-to-box midfielder who carries forward and arrives late in the penalty area.",
    ),
    (
        "Martin Ødegaard",
        "AM",
        "Norway",
        2,
        "1998-12-17",
        "Left-footed attacking playmaker who creates in the right half-space and leads the press.",
    ),
    (
        "Kevin De Bruyne",
        "AM",
        "Belgium",
        1,
        "1991-06-28",
        "Direct creative midfielder who plays through balls, crosses early and attacks transition space.",
    ),
    (
        "Florian Wirtz",
        "AM",
        "Germany",
        13,
        "2003-05-03",
        "Creative attacking midfielder who turns between lines and combines around the penalty area.",
    ),
    (
        "Jamal Musiala",
        "AM",
        "Germany",
        12,
        "2003-02-26",
        "Elusive attacking midfielder who dribbles through tight spaces and carries into the box.",
    ),
    (
        "Cole Palmer",
        "AM",
        "England",
        4,
        "2002-05-06",
        "Left-footed creator who drifts into the right half-space and combines chance creation with shooting.",
    ),
    (
        "Bukayo Saka",
        "RW",
        "England",
        2,
        "2001-09-05",
        "Left-footed inverted right winger who isolates defenders, cuts inside and creates from the half-space.",
    ),
    (
        "Mohamed Salah",
        "RW",
        "Egypt",
        3,
        "1992-06-15",
        "Inverted right winger who attacks the box with diagonal runs and finishes on his left foot.",
    ),
    (
        "Lamine Yamal",
        "RW",
        "Spain",
        10,
        "2007-07-13",
        "Creative left-footed right winger who beats defenders and delivers passes from wide positions.",
    ),
    (
        "Michael Olise",
        "RW",
        "France",
        12,
        "2001-12-12",
        "Inverted right winger who slows defenders, cuts inside and supplies precise final passes.",
    ),
    (
        "Ousmane Dembélé",
        "RW",
        "France",
        14,
        "1997-05-15",
        "Two-footed wide attacker who accelerates past defenders and creates unpredictable combinations.",
    ),
    (
        "Vinícius Júnior",
        "LW",
        "Brazil",
        9,
        "2000-07-12",
        "Explosive left winger who attacks space, beats opponents in isolation and carries into the area.",
    ),
    (
        "Rafael Leão",
        "LW",
        "Portugal",
        16,
        "1999-06-10",
        "Powerful left winger who drives into space and creates chances from long carries.",
    ),
    (
        "Luis Díaz",
        "LW",
        "Colombia",
        3,
        "1997-01-13",
        "Energetic left winger who counterpresses, dribbles inside and attacks the back post.",
    ),
    (
        "Khvicha Kvaratskhelia",
        "LW",
        "Georgia",
        14,
        "2001-02-12",
        "Creative left winger who changes direction in isolation and combines near the penalty area.",
    ),
    (
        "Raphinha",
        "LW",
        "Brazil",
        10,
        "1996-12-14",
        "Hard-running wide forward who presses high and attacks the box with diagonal movements.",
    ),
    (
        "Erling Haaland",
        "ST",
        "Norway",
        1,
        "2000-07-21",
        "Powerful penalty-box striker who stretches the back line and finishes high-value chances.",
    ),
    (
        "Harry Kane",
        "ST",
        "England",
        12,
        "1993-07-28",
        "Complete centre-forward who drops to link play and combines passing with reliable box finishing.",
    ),
    (
        "Kylian Mbappé",
        "ST",
        "France",
        9,
        "1998-12-20",
        "Explosive forward who attacks channels, carries in transition and finishes inside the area.",
    ),
    (
        "Lautaro Martínez",
        "ST",
        "Argentina",
        15,
        "1997-08-22",
        "Mobile striker who presses defenders and connects short combinations before attacking the box.",
    ),
    (
        "Alexander Isak",
        "ST",
        "Sweden",
        6,
        "1999-09-21",
        "Technical striker who carries through the channels and combines movement with composed finishing.",
    ),
    (
        "Viktor Gyökeres",
        "ST",
        "Sweden",
        18,
        "1998-06-04",
        "Physical channel-running striker who drives at defenders and leads transitions with powerful carries.",
    ),
]

# Goals, assists, xG, xA, carries, progressive passes, tackles per 90, pass accuracy.
ARCHETYPES = {
    "GK": (0.0, 0.01, 0.0, 0.01, 0.1, 3.0, 0.05, 77),
    "CB": (0.05, 0.02, 0.05, 0.03, 1.0, 4.0, 1.4, 91),
    "LB": (0.05, 0.17, 0.07, 0.17, 2.8, 4.5, 1.8, 83),
    "RB": (0.05, 0.19, 0.06, 0.2, 2.4, 5.8, 1.7, 84),
    "DM": (0.07, 0.08, 0.08, 0.1, 1.9, 7.5, 2.1, 91),
    "CM": (0.12, 0.18, 0.13, 0.2, 3.1, 6.6, 1.5, 89),
    "AM": (0.28, 0.29, 0.3, 0.32, 4.1, 6.1, 0.8, 84),
    "LW": (0.38, 0.22, 0.4, 0.24, 5.4, 3.7, 0.7, 81),
    "RW": (0.4, 0.25, 0.42, 0.28, 5.0, 4.2, 0.8, 82),
    "ST": (0.65, 0.13, 0.68, 0.13, 2.1, 2.0, 0.4, 77),
}


def seed_database(database: Database) -> dict[str, object]:
    if database.source != "demo":
        raise MatchdayError("SOURCE_MISMATCH", "Synthetic records cannot enter an API database.", 409)
    if database.season != SEED_SEASON:
        raise MatchdayError("DEMO_SEASON", f"The bundled demonstration uses {SEED_SEASON}.", 422)
    with database.transaction() as connection:
        for team_id, name, short, league in TEAMS:
            database.upsert_team(
                connection, Team(team_id=team_id, name=name, short_name=short, league=league)
            )
        for player_id, (name, position, nationality, team_id, born, bio) in enumerate(ROSTER, start=1):
            rng = random.Random(f"{SEED_VERSION}:{player_id}")
            minutes = rng.randint(1500, 3100)
            values = ARCHETYPES[position]
            factors = [rng.uniform(0.72, 1.28) for _ in range(7)]
            totals = [values[i] * factors[i] * minutes / 90 for i in range(7)]
            player = Player(
                player_id=player_id,
                name=name,
                position=position,
                nationality=nationality,
                team_id=team_id,
                date_of_birth=born,
                tactical_bio=bio,
                market_value=rng.randrange(15, 121) * 1_000_000,
            )
            database.upsert_player(connection, player)
            database.upsert_stats(
                connection,
                PlayerStats(
                    player_id=player_id,
                    season=SEED_SEASON,
                    minutes_played=minutes,
                    matches_played=min(38, math.ceil(minutes / 82)),
                    goals=round(totals[0]),
                    assists=round(totals[1]),
                    xG=round(totals[2], 2),
                    xA=round(totals[3], 2),
                    progressive_carries=round(totals[4]),
                    progressive_passes=round(totals[5]),
                    tackles_won=round(totals[6]),
                    pass_accuracy=round(min(97, values[7] + rng.uniform(-3, 3)), 1),
                ),
            )
            for alias in {name, name.split()[-1]}:
                connection.execute(
                    "INSERT OR IGNORE INTO player_aliases(player_id,alias_key) VALUES (?,?)",
                    (player_id, name_key(alias)),
                )
        connection.execute(
            "INSERT INTO competitions(competition_id,code,name,updated_at) VALUES (1,'PL','Premier League',?) ON CONFLICT(competition_id) DO UPDATE SET updated_at=excluded.updated_at",
            (utc_now(),),
        )
        for match_id, home, away, day in ((1, 2, 1, 24), (2, 3, 4, 25), (3, 6, 7, 25)):
            database.upsert_fixture(
                connection,
                Fixture(
                    match_id=match_id,
                    competition_id=1,
                    season=SEED_SEASON,
                    home_team_id=home,
                    away_team_id=away,
                    kickoff=datetime(2025, 5, day, 15, tzinfo=UTC),
                    status="FINISHED",
                    home_score=2,
                    away_score=1,
                ),
            )
        database.set_meta(connection, "seed_version", SEED_VERSION)
        database.set_meta(connection, "reference_date", "2025-06-01")
    return {"source": "demo", "players": len(ROSTER), "teams": len(TEAMS), "seed_version": SEED_VERSION}
