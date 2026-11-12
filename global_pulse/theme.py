"""Global Pulse's restrained, high-contrast workstation palette."""

BG = "#0d0e10"
PANEL = "#151619"
RAISED = "#202125"
BORDER = "#35363b"
TEXT = "#e9edf5"
MUTED = "#929caf"
PURPLE = "#a78bfa"
SEVERITY = {"critical": "#fb6674", "high": "#f5a65c", "moderate": "#e3cc68",
            "informational": "#63b3ed", "unassessed": "#8c95a8"}

STYLE = """
QWidget { background: #0d0e10; color: #e9edf5; font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 12px; }
QMainWindow { background: #0d0e10; }
QFrame#Panel { background: #151619; border: 1px solid #35363b; border-radius: 6px; }
QFrame#Panel QWidget { background: transparent; }
QFrame#MediaTile { border: 1px solid #35363b; background: #121315; border-radius: 4px; }
QFrame#MapControls { background: #151619; border: 1px solid #3b3c40; border-radius: 3px; }
QFrame#TitleBar { background: #131416; border-bottom: 1px solid #35363b; }
QLabel#Brand { font-size: 18px; font-weight: 700; letter-spacing: 2px; color: #f2efff; }
QLabel#Eyebrow { font-size: 10px; font-weight: 600; letter-spacing: 1px; color: #929caf; }
QLabel#Muted { color: #929caf; }
QLabel#SectionTitle { color: #b5bfcf; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
QLabel#Count { background: #29223d; color: #c8b8f9; border-radius: 9px; padding: 2px 7px; font-weight: 600; }
QLabel#DemoBanner { background: #46361a; color: #f4d383; padding: 6px 14px; border-bottom: 1px solid #876c32; }
QLabel#LiveBadge { color: #7fdbb2; background: #173029; border: 1px solid #284d40; border-radius: 9px; padding: 3px 9px; font-size: 10px; font-weight: 600; }
QPushButton, QToolButton { background: #202125; border: 1px solid #35363b; border-radius: 4px; padding: 4px 7px; color: #c9d1df; }
QPushButton:hover, QToolButton:hover { background: #272c3c; border-color: #726495; color: white; }
QPushButton:pressed, QToolButton:pressed { background: #332b48; }
QPushButton:checked, QToolButton:checked { background: #302742; border-color: #7055a3; color: #ddd0ff; }
QPushButton:disabled, QToolButton:disabled { color: #616b7f; background: #121620; }
QPushButton#Primary { background: #7853bd; color: white; border-color: #9872d6; font-weight: 600; }
QToolButton#WindowControl { border: none; background: transparent; border-radius: 0; font-size: 17px; padding: 8px 14px; }
QToolButton#WindowClose:hover { background: #ad3c50; color: white; }
QLineEdit, QComboBox, QSpinBox, QTimeEdit, QPlainTextEdit, QTextEdit { background: #101113; border: 1px solid #30384b; border-radius: 4px; padding: 4px 6px; selection-background-color: #695096; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #a78bfa; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #202125; border: 1px solid #424b62; selection-background-color: #44335f; padding: 3px; }
QListWidget, QTreeWidget, QTableWidget { background: #151619; border: none; outline: none; alternate-background-color: #151a24; selection-background-color: #29243d; selection-color: white; }
QListWidget::item { border-bottom: 1px solid #222837; padding: 9px 10px; }
QListWidget::item:selected { background: #29243d; border-left: 3px solid #a78bfa; }
QListWidget::item:hover { background: #1c2230; }
QTreeWidget::item, QTableWidget::item { padding: 6px 7px; border: none; }
QHeaderView::section { background: #171c27; color: #9eabc0; border: none; border-bottom: 1px solid #333b4c; padding: 8px 7px; font-size: 10px; font-weight: 600; }
QTextBrowser { background: transparent; border: none; padding: 3px; selection-background-color: #695096; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #3a4255; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; }
QScrollBar::handle:horizontal { background: #3a4255; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #0d0e10; }
QSplitter::handle:hover { background: #53446f; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #8e9bb1; padding: 9px 14px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #d8c9ff; border-bottom: 2px solid #a78bfa; }
QTabBar::tab:hover { background: #202125; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid #657087; border-radius: 3px; background: #131925; }
QCheckBox::indicator:checked { background: #9271cf; border-color: #c2a5fb; }
QSlider::groove:horizontal { height: 3px; background: #33394a; }
QSlider::sub-page:horizontal { background: #9676d3; }
QSlider::handle:horizontal { background: #c8b4ee; width: 11px; height: 11px; margin: -4px 0; border-radius: 5px; }
QGroupBox { border: 1px solid #35363b; border-radius: 5px; margin-top: 15px; padding-top: 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #bdb2d6; }
QMenu { background: #181e2a; border: 1px solid #46506b; padding: 5px; }
QMenu::item { padding: 7px 20px; }
QMenu::item:selected { background: #3a2c51; }
QToolTip { color: #e9edf5; background: #222b3b; border: 1px solid #526079; padding: 6px; }
QStatusBar { background: #101113; color: #8793a8; border-top: 1px solid #262e3e; font-size: 10px; }
"""
