"""
main.py  —  AVL Maroc PFE  |  Vehicle Teleoperation HMI
Entry point.  Run from the project root:
    python main.py
"""

import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Vehicle Command HMI")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()