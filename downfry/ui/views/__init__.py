from .home_view import HomeView
from .queue_view import QueueView
from .history_view import HistoryView
from .settings_view import SettingsView
from .library_view import LibraryView

try:
    from .player_view import PlayerView
except ImportError:
    PlayerView = None

__all__ = [
    "HomeView",
    "QueueView",
    "HistoryView",
    "SettingsView",
    "LibraryView",
    "PlayerView",
]

