"""Experimenter commands typed in the brain terminal (``/next``, ``/goto CHAT`` ...).

Each one becomes the same ``WozCommand`` the WoZ panel would send (reason ``other``, note
"typed in the brain terminal"), so it goes through the same validation and logging.
Handy for development and as a backup when the panel is not available.
"""

from __future__ import annotations

from pipi_brain.protocol import WozCommand

NOTE = "typed in the brain terminal"

HELP = """\
Experimenter commands (same as the WoZ panel):
  /start            start the session        /next          next phase
  /goto PHASE       jump to a phase          /extend SEC    add focus time
  /out  /in         force migration          /say LINE_ID   speak a fixed line
  /text WORDS       speak custom text        /game GAME     start a game
  /endgame          end the current game     /robot fake|real  swap robot body
  /eyes STATE       set eyes                 /motion NAME   play a motion
  /pause  /resume   freeze / continue        /stop          EMERGENCY STOP
  /end              end the session          /help          this text"""

_SIMPLE = {
    "/start": "start_session",
    "/next": "next_phase",
    "/out": "trigger_migration_out",
    "/in": "trigger_migration_in",
    "/endgame": "end_game",
    "/pause": "pause",
    "/resume": "resume",
    "/stop": "emergency_stop",
    "/end": "end_session",
    "/quit": "end_session",
}
# command -> (WoZ command, argument name, argument is a number)
_WITH_ARG = {
    "/goto": ("goto_phase", "phase", False),
    "/extend": ("extend_focus", "seconds", True),
    "/say": ("say", "line_id", False),
    "/text": ("say_text", "text", False),
    "/game": ("start_game", "game", False),
    "/robot": ("switch_robot_body", "body", False),
    "/eyes": ("set_eyes", "state", False),
    "/motion": ("play_motion", "name", False),
}


def parse_terminal_command(line: str) -> WozCommand | str:
    """A WozCommand, or a text to print (help or an error)."""
    word, _, rest = line.strip().partition(" ")
    word = word.lower()
    rest = rest.strip()
    if word in ("/help", "/?"):
        return HELP
    if word in _SIMPLE:
        return WozCommand(command=_SIMPLE[word], reason="other", note=NOTE)  # type: ignore[arg-type]
    if word in _WITH_ARG:
        command, arg_name, numeric = _WITH_ARG[word]
        if not rest:
            return f"{word} needs a value (see /help)"
        value: str | float = rest
        if numeric:
            try:
                value = float(rest)
            except ValueError:
                return f"{word}: '{rest}' is not a number"
        elif arg_name == "phase":
            value = rest.upper()
        return WozCommand(
            command=command,  # type: ignore[arg-type]
            args={arg_name: value},
            reason="other",
            note=NOTE,
        )
    return f"unknown command {word} (type /help)"
