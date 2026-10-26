"""Connection status, not an inferred guarantee of AI or network stability."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QPushButton


class StabilityIndicator(QDialog):
    def __init__(self, restore):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(225, 42)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.setToolTip('Restaurar o Jarvis. A cor mostra o estado da conexão, não garante disponibilidade dos modelos.')
        self.button.clicked.connect(restore)
        layout.addWidget(self.button)
        self.set_status('connecting')

    def set_status(self, state):
        label, color = {
            'connected': ('● JARVIS · Conectado', '#00d687'),
            'connecting': ('● JARVIS · Conectando', '#ffca50'),
            'reconnecting': ('● JARVIS · Reconectando', '#ffca50'),
            'disconnected': ('● JARVIS · Desconectado', '#ff6666'),
        }.get(state, ('● JARVIS · Sem estado', '#aaaaaa'))
        self.button.setText(label)
        self.button.setStyleSheet(f'background:#001018;color:{color};border:1px solid {color};padding:8px;border-radius:6px;')

    def place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 12, screen.bottom() - self.height() - 12)
