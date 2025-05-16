# main.py
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QLabel, QVBoxLayout
from runAiBot import run_bot

class LinkedInApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LinkedIn Bot")
        self.setGeometry(100, 100, 300, 200)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        self.label = QLabel("Click to start automation")
        self.button = QPushButton("Run Bot")
        self.button.clicked.connect(run_bot)
        layout.addWidget(self.label)
        layout.addWidget(self.button)
        self.setLayout(layout)

app = QApplication(sys.argv)
window = LinkedInApp()
window.show()
sys.exit(app.exec_())