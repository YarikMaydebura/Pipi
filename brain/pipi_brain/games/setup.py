"""Everything the session needs for games, loaded and checked once at startup.

``load_game_setup`` reads ``games.yaml`` and ``motions.yaml``, builds the registry with the
games that are really built (M4: ``crocodile_robot`` and ``quick_draw``) and checks that every
motion a game uses exists in the motion library. A problem raises ``ConfigError`` before the
session starts, never in the middle of a game.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipi_brain.config import ConfigError, GamesFilesConfig, SessionConfig
from pipi_brain.games.config import GamesConfig, load_games_config
from pipi_brain.games.crocodile import CrocodileRobot
from pipi_brain.games.motions import MotionLibrary, load_motions
from pipi_brain.games.quick_draw import QuickDraw
from pipi_brain.games.registry import GameRegistry
from pipi_brain.games.rps import RockPaperScissors
from pipi_brain.games.staring import Staring


@dataclass(frozen=True)
class GameSetup:
    config: GamesConfig
    motions: MotionLibrary
    registry: GameRegistry


def build_registry(config: GamesConfig) -> GameRegistry:
    """A fresh registry (games keep per-session state, e.g. the words already acted)."""
    registry = GameRegistry()
    registry.register(CrocodileRobot(config.crocodile))
    registry.register(QuickDraw(config.quick_draw))
    registry.register(Staring(config.staring))
    registry.register(RockPaperScissors(config.rps_arms))
    # M6: crocodile_human (stretch goal) is registered here once it is built.
    return registry


def check_motions(registry: GameRegistry, motions: MotionLibrary) -> None:
    """Every motion a registered game uses must be a canonical name in motions.yaml."""
    problems = [
        f"{game.id}: {', '.join(unknown)}"
        for game in registry.registered
        if (unknown := motions.unknown(game.motions()))
    ]
    if problems:
        raise ConfigError(
            "Motions used by games but missing from motions.yaml -> " + "; ".join(problems)
        )


def check_session(setup: GameSetup, session: SessionConfig) -> None:
    """``session.default_game`` / ``first_game`` must name games that are built."""
    for key, game_id in (
        ("default_game", session.default_game),
        ("first_game", session.first_game),
    ):
        if game_id is not None and setup.registry.implementation(game_id) is None:
            built = ", ".join(game.id for game in setup.registry.registered)
            raise ConfigError(f"session.{key} is {game_id!r}, but only these are built: {built}")


def load_game_setup(files: GamesFilesConfig) -> GameSetup:
    """Read games.yaml + motions.yaml and build the registry. Raises ConfigError."""
    config = load_games_config(files.games_file)
    motions = load_motions(files.motions_file)
    registry = build_registry(config)
    check_motions(registry, motions)
    return GameSetup(config, motions, registry)
