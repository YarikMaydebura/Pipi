"""``config/games.yaml``: every tunable value of the games (docs/GAMES.md §6), validated.

Unknown keys and impossible values are errors, so a typo stops the brain at startup instead
of surprising us in the middle of a session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pipi_brain.config import ConfigError, read_yaml

Range = tuple[float, float]
Name = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_range(name: str, value: Range) -> None:
    low, high = value
    if low < 0 or high < low:
        raise ValueError(f"{name} must be [min, max] with 0 <= min <= max, got {list(value)}")


class CrocodileWord(_Strict):
    word: str = Field(min_length=1, max_length=40)
    motion: Name  # a name from motions.yaml
    synonyms: tuple[str, ...] = ()  # also correct
    close: tuple[str, ...] = ()  # nearly right: encouraging nod
    say: str | None = None  # how Pipi names it; default "a <word>"

    @property
    def spoken(self) -> str:
        if self.say:
            return self.say
        article = "an" if self.word[:1].lower() in "aeiou" else "a"
        return f"{article} {self.word}"


class CrocodileConfig(_Strict):
    rounds_study: int = Field(ge=1, le=10)
    rounds_demo: int = Field(ge=1, le=10)
    round_timeout_s: float = Field(gt=0)
    hint_after_wrong: int = Field(ge=1)
    max_wrong_guesses: int = Field(ge=1)
    repeat_motion_every_s: float = Field(gt=0)
    reaction_pause_s: float = Field(ge=0)
    llm_picks_word: bool
    keyword_shortcut: bool
    words: tuple[CrocodileWord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> CrocodileConfig:
        names = [word.word.casefold() for word in self.words]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"crocodile words must be unique; twice: {', '.join(duplicates)}")
        if self.hint_after_wrong > self.max_wrong_guesses:
            raise ValueError("hint_after_wrong must not be larger than max_wrong_guesses")
        return self

    def rounds_for(self, mode: str) -> int:
        return self.rounds_demo if mode == "demo" else self.rounds_study


class QuickDrawConfig(_Strict):
    rounds: int = Field(ge=1, le=9)
    delay_range_s: Range
    robot_reaction_ms: Range
    robot_win_chance: float = Field(ge=0, le=1)
    give_up_s: float = Field(gt=0)
    bang_threshold_db: float = Field(lt=0, ge=-100)
    go_blank_ms: float = Field(default=300, ge=0, le=2000)
    noise_window_ms: float = Field(ge=0)
    slow_motion_robot_ms: Range
    slow_motion_give_up_s: float = Field(gt=0)
    bang_words: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ranges(self) -> QuickDrawConfig:
        _check_range("delay_range_s", self.delay_range_s)
        _check_range("robot_reaction_ms", self.robot_reaction_ms)
        _check_range("slow_motion_robot_ms", self.slow_motion_robot_ms)
        if self.rounds % 2 == 0:
            raise ValueError("quick_draw.rounds must be odd (best of 3, 5, ...)")
        return self

    @property
    def wins_needed(self) -> int:
        return self.rounds // 2 + 1


# --- M6 games: validated so games.yaml stays correct, not used by any code yet ----------------


class CrocodileHumanConfig(_Strict):
    categories: tuple[str, ...] = Field(min_length=1)
    burst_frames: int = Field(ge=1, le=12)
    burst_interval_ms: int = Field(ge=50)


class StaringConfig(_Strict):
    robot_loses_after_s: Range
    min_fps_for_detect: float = Field(gt=0)


class RpsArmsConfig(_Strict):
    rounds: int = Field(ge=1, le=9)
    mode: Literal["camera", "voice"]


class GamesConfig(_Strict):
    good_sport: bool
    between_rounds_s: float = Field(ge=0, le=30)
    llm_timeout_s: float = Field(gt=0)
    llm_retries: int = Field(ge=0, le=3)
    crocodile: CrocodileConfig
    quick_draw: QuickDrawConfig
    crocodile_human: CrocodileHumanConfig
    staring: StaringConfig
    rps_arms: RpsArmsConfig


def load_games_config(path: Path) -> GamesConfig:
    """Read and validate games.yaml. Raises ConfigError with a readable message."""
    try:
        return GamesConfig.model_validate(read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"Invalid games config in {path}:\n{exc}") from exc
