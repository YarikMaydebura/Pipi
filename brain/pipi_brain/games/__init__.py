"""Games (docs/GAMES.md). Built in M4: ``crocodile_robot`` and ``quick_draw``.

- ``base.py``: the contracts (``Game``, ``GameContext``, ``RoundResult``)
- ``runner.py``: rules -> rounds -> "again / stop / another game" -> logs and memory
- ``registry.py``: known / built / available games + the keyword fallback map
- ``intent.py``: the voice game menu (LLM intent JSON, keyword fallback)
- ``config.py`` / ``motions.py`` / ``setup.py``: games.yaml, motions.yaml, startup checks
- ``crocodile.py``, ``quick_draw.py``: one module per game
"""
