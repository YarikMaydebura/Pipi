"""games.yaml and motions.yaml: loading, validation and the startup checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from pipi_brain.bodies.alpha_mini_moves import load_moves
from pipi_brain.config import ConfigError, LoadedConfig, load_config
from pipi_brain.games.config import GamesConfig, load_games_config
from pipi_brain.games.motions import BODIES, load_motions
from pipi_brain.games.setup import build_registry, check_motions, check_session, load_game_setup

from .conftest import CONFIG_DIR

# The clips the fake robot's model has (agreed with the web side), plus its two aliases.
FAKE_ROBOT_CLIPS = {
    "act_bird",
    "act_boxer",
    "act_swimmer",
    "act_dancer",
    "act_robot",
    "act_sleeping",
    "act_superhero",
    "act_drummer",
    "duel_ready",
    "duel_draw",
    "duel_hit",
    "duel_win",
    # staring + arm RPS (procedural on the fake robot, web/src/fake-robot/gameMotions.ts)
    "stare_ready",
    "stare_lose",
    "rps_shake",
    "rps_rock",
    "rps_paper",
    "rps_scissors",
    "sad",
    "shrug",
    "bow",
    "idle",
    "talk",
    "listen",
    "think",
    "happy",
    "nod",
    "shake_head",
    "signature_wave",
    "celebrate",
    "dance",
    "wake_up",
    "sleep",
}
FAKE_ROBOT_ALIASES = {"wave", "excited"}


def games_yaml() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / "games.yaml").read_text(encoding="utf-8"))


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "games.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_games_yaml_loads_with_the_documented_values() -> None:
    config = load_games_config(CONFIG_DIR / "games.yaml")
    assert config.good_sport is True
    assert config.crocodile.rounds_for("study") == 2 and config.crocodile.rounds_for("dev") == 2
    assert config.crocodile.rounds_for("demo") > 2
    assert config.crocodile.round_timeout_s == 30
    assert (config.crocodile.hint_after_wrong, config.crocodile.max_wrong_guesses) == (2, 3)
    duel = config.quick_draw
    assert duel.rounds == 3 and duel.wins_needed == 2
    assert duel.delay_range_s == (2, 5) and duel.robot_reaction_ms == (450, 900)
    assert duel.robot_win_chance == 0.3 and duel.bang_threshold_db == -20
    words = {word.word: word for word in config.crocodile.words}
    assert words["bird"].spoken == "a bird" and words["sleeping"].spoken == "someone sleeping"


def test_every_crocodile_word_has_a_motion_the_fake_robot_can_play() -> None:
    config = load_games_config(CONFIG_DIR / "games.yaml")
    motions = load_motions(CONFIG_DIR / "motions.yaml")
    for word in config.crocodile.words:
        assert motions.resolve(word.motion, "fake_robot") == word.motion


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["crocodile"]["words"].append(dict(d["crocodile"]["words"][0])), "unique"),
        (lambda d: d["quick_draw"].update(rounds=2), "odd"),
        (lambda d: d["quick_draw"].update(delay_range_s=[5, 2]), "delay_range_s"),
        (lambda d: d["quick_draw"].update(robot_win_chance=1.5), "robot_win_chance"),
        (lambda d: d["quick_draw"].update(bang_threshold_db=3), "bang_threshold_db"),
        (lambda d: d["crocodile"].update(words=[]), "words"),
        (lambda d: d["crocodile"].update(hint_after_wrong=9), "hint_after_wrong"),
        (lambda d: d.update(typo_key=1), "typo_key"),
        (lambda d: d["crocodile"]["words"][0].update(motion="Act Bird"), "motion"),
    ],
)
def test_invalid_games_yaml_is_rejected(tmp_path: Path, change: Any, message: str) -> None:
    data = games_yaml()
    change(data)
    with pytest.raises(ConfigError, match=message):
        load_games_config(write(tmp_path, data))


def test_motion_library_sends_names_as_they_are_to_the_web_bodies() -> None:
    motions = load_motions(CONFIG_DIR / "motions.yaml")
    sent = {motions.resolve(name, "fake_robot") for name in motions.names} - {None}
    assert sent <= FAKE_ROBOT_CLIPS | FAKE_ROBOT_ALIASES, sent - FAKE_ROBOT_CLIPS
    for name in motions.names:
        for body in ("fake_robot", "desktop_pet"):
            assert motions.resolve(name, body) in (name, None)  # as-is, never renamed
    for name in ("act_bird", "duel_ready", "duel_hit", "duel_win", "celebrate", "bow", "idle"):
        assert motions.resolve(name, "fake_robot") == name
    for name in ("celebrate", "bow", "wave", "nod", "idle"):
        assert motions.resolve(name, "desktop_pet") == name
    # the pet has no acting / duel clips (it would answer "unknown motion")
    assert motions.resolve("act_bird", "desktop_pet") is None
    assert motions.resolve("duel_ready", "desktop_pet") is None
    assert motions.supports("fake_robot") and motions.supports("desktop_pet")
    assert motions.supports("fake_robot", "crocodile")
    assert not motions.supports("desktop_pet", "crocodile")


def test_alpha_mini_mapping_points_only_at_verified_moves() -> None:
    motions = load_motions(CONFIG_DIR / "motions.yaml")
    moves = load_moves(CONFIG_DIR / "alpha_mini.yaml")  # rejects unverified joints/behaviors
    used = {motions.resolve(name, "alpha_mini") for name in motions.names} - {None}
    assert used and moves.missing(name for name in used if name is not None) == []
    # Crocodile on the real robot: only the words its verified moves can act.
    acting = {name for name in motions.names if name.startswith("act_")}
    playable = {n for n in acting if motions.resolve(n, "alpha_mini") is not None}
    assert playable == {"act_sleeping", "act_robot", "act_dancer"}
    assert motions.supports("alpha_mini", "crocodile")
    # Needs an unverified joint (head yaw / arms): stays null until tested in the lab.
    for name in ("shake_head", "shrug", "act_bird", "act_boxer", "duel_ready"):
        assert motions.resolve(name, "alpha_mini") is None
    assert motions.resolve("act_bird", "unknown_body") is None
    assert motions.resolve("moonwalk", "fake_robot") is None
    assert set(BODIES) == {"fake_robot", "desktop_pet", "alpha_mini"}


def test_canonical_motion_names_of_the_design_are_all_present() -> None:
    motions = load_motions(CONFIG_DIR / "motions.yaml")
    canonical = {
        "social": "wave signature_wave nod shake_head think excited celebrate sad shrug bow",
        "social2": "wake_up sleep",
        "crocodile": "act_bird act_boxer act_swimmer act_dancer act_robot act_sleeping",
        "crocodile2": "act_superhero act_drummer",
        "duel": "duel_ready duel_draw duel_hit duel_win",
        "rps": "rps_shake rps_rock rps_paper rps_scissors",
        "staring": "stare_ready stare_lose",
    }
    names = [name for group in canonical.values() for name in group.split()]
    assert len(names) == 30 and motions.unknown(names) == []


def test_bad_motions_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "motions.yaml"
    path.write_text("motions:\n  wave: {group: social, robot_x: wave}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="wave"):
        load_motions(path)
    path.write_text("nothing: here\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="motions"):
        load_motions(path)


def test_startup_check_catches_a_motion_that_is_not_in_the_library(tmp_path: Path) -> None:
    data = games_yaml()
    data["crocodile"]["words"][0]["motion"] = "act_unicorn"
    registry = build_registry(GamesConfig.model_validate(data))
    with pytest.raises(ConfigError, match="crocodile_robot: act_unicorn"):
        check_motions(registry, load_motions(CONFIG_DIR / "motions.yaml"))


def test_setup_registers_only_the_built_games(dev_config: LoadedConfig) -> None:
    setup = load_game_setup(dev_config.app.games)
    assert [game.id for game in setup.registry.registered] == [
        "crocodile_robot",
        "quick_draw",
        "staring",
        "rps_arms",
    ]
    for unbuilt in ("crocodile_human",):
        assert setup.registry.info(unbuilt) is not None  # known ...
        assert setup.registry.implementation(unbuilt) is None  # ... but not built
    check_session(setup, dev_config.app.session)
    bad = dev_config.app.session.model_copy(update={"default_game": "crocodile_human"})
    with pytest.raises(ConfigError, match="default_game"):
        check_session(setup, bad)
    bad = dev_config.app.session.model_copy(update={"first_game": "chess"})
    with pytest.raises(ConfigError, match="first_game"):
        check_session(setup, bad)


@pytest.mark.parametrize(
    ("mode", "first"), [("dev", "crocodile_robot"), ("study", "crocodile_robot"), ("demo", None)]
)
def test_game_files_and_first_game_per_mode(mode: str, first: str | None) -> None:
    app = load_config(CONFIG_DIR / f"{mode}.yaml").app
    assert app.games.games_file == CONFIG_DIR / "games.yaml"
    assert app.games.motions_file == CONFIG_DIR / "motions.yaml"
    assert app.session.first_game == first
    assert app.bodies.stop_timeout_s == 1
    check_session(load_game_setup(app.games), app.session)


def test_dev_break_is_long_enough_for_the_real_games() -> None:
    """Chat (30 s) + 2 Crocodile rounds (up to 30 s each) + menu + a best-of-3 duel."""
    dev = load_config(CONFIG_DIR / "dev.yaml").app
    games = load_games_config(dev.games.games_file)
    crocodile = games.crocodile.rounds_for("dev") * games.crocodile.round_timeout_s
    duel = games.quick_draw.rounds * (
        games.quick_draw.delay_range_s[1] + games.quick_draw.give_up_s
    )
    worst_case = dev.session.chat_max_s + crocodile + dev.session.game_menu_s + duel
    assert dev.timers.break_max_s is not None and dev.timers.break_max_s >= worst_case
