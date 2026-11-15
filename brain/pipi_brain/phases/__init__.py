"""The session state machine (docs/INTERACTION_FLOW.md), M3.

- ``controller.py``: ``SessionController`` runs the phases and is the ``WozBackend``
- one module per phase: ``setup``, ``persona_pick``, ``greeting``, ``focus``, ``migration``
  (MIGRATE_OUT / MIGRATE_IN), ``robot_wake``, ``chat``, ``games`` (M3 placeholders),
  ``goodbye`` (ROBOT_GOODBYE / RETURN)
- shared helpers: ``context`` (what a phase may use), ``voice`` (speaking), ``conversation``
  (listening + LLM turns), ``timers`` / ``clock`` (pause, countdowns, safe points), ``flow``
  (phase order), ``woz_commands`` / ``woz_actions`` (WoZ commands), ``inputs`` /
  ``terminal_commands`` (microphone, typed lines, ``/commands``)

Nothing is imported here on purpose (keeps imports cheap and free of cycles).
"""
