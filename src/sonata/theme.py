from PySide6.QtGui import QColor, QPalette


def apply_theme(app, dark: bool):
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        "Window": "#25282d" if dark else "#f1f2f4",
        "WindowText": "#e7e9ed" if dark else "#20242a",
        "Base": "#1d2024" if dark else "#ffffff",
        "AlternateBase": "#25292f" if dark else "#f4f6f8",
        "Text": "#e7e9ed" if dark else "#20242a",
        "Button": "#30343b" if dark else "#e7e9ec",
        "ButtonText": "#e7e9ed" if dark else "#20242a",
        "Highlight": "#2364a0" if dark else "#cce4f7",
        "HighlightedText": "#ffffff" if dark else "#163957",
        "ToolTipBase": "#30343b" if dark else "#fffde9",
        "ToolTipText": "#e7e9ed" if dark else "#20242a",
        "PlaceholderText": "#9ba4b1" if dark else "#6c7580",
    }
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#7d8490"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#7d8490"))
    app.setPalette(palette)
    border = "#454b55" if dark else "#b8bec7"
    header = "#30343b" if dark else "#e9edf2"
    base = "#1d2024" if dark else "#ffffff"
    hover = "#3a4655" if dark else "#deecf7"
    app.setStyleSheet(f"""
        QToolBar {{ spacing: 3px; padding: 3px; border-bottom: 1px solid {border}; }}
        QToolButton {{ padding: 4px 7px; border-radius: 1px; }}
        QToolButton:hover {{ background: {hover}; }}
        QPushButton {{ padding: 4px 12px; border: 1px solid {border}; background: {header}; border-radius: 1px; min-height: 20px; }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: {border}; }}
        QLineEdit, QComboBox, QSpinBox {{ min-height: 23px; padding: 1px 4px; border: 1px solid {border}; border-radius: 1px; }}
        QLineEdit:focus {{ border-color: #4186bd; }}
        QHeaderView::section {{ background: {header}; padding: 5px 7px; border: 0; border-right: 1px solid {border}; border-bottom: 1px solid {border}; }}
        QTabBar::tab {{ padding: 6px 20px; border: 1px solid {border}; background: {header}; margin-right: 2px; border-radius: 0; }}
        QTabBar::tab:selected {{ background: {base}; border-bottom-color: {base}; }}
        QTableView {{ gridline-color: {border}; border: 1px solid {border}; }}
        QStatusBar {{ border-top: 1px solid {border}; }}
        QGroupBox {{ margin-top: 7px; padding-top: 6px; }}
    """)
