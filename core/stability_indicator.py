"""Compact connection, stop and microphone controls."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton


class StabilityIndicator(QDialog):
    def __init__(self, restore, interrupt=None, toggle_mic=None, muted=False):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(286, 92)
        self.setStyleSheet('QDialog {background:#17212e;border:1px solid #344458;border-radius:10px;} QPushButton {font:10pt "Segoe UI";padding:6px;border-radius:5px;background:#243447;color:#edf3fa;} QPushButton:hover {background:#334a61;}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(5)
        self.button = QPushButton()
        self.button.setToolTip('Restaurar o Jarvis; o estado refere-se à conexão.')
        self.button.clicked.connect(restore)
        layout.addWidget(self.button)
        row = QHBoxLayout()
        self.stop_button = QPushButton('Parar tarefa')
        self.stop_button.setToolTip('Interromper ações e fala do Jarvis')
        self.stop_button.clicked.connect(interrupt or (lambda: None))
        row.addWidget(self.stop_button)
        self.mic_button = QPushButton()
        self.mic_button.clicked.connect(toggle_mic or (lambda: None))
        row.addWidget(self.mic_button)
        layout.addLayout(row)
        self.set_muted(muted)
        self.set_status('connecting')

    def set_muted(self, muted):
        self.mic_button.setText('Ligar microfone' if muted else 'Desligar microfone')
        self.mic_button.setToolTip('O microfone está desligado' if muted else 'O microfone está ligado')

    def set_status(self, state):
        label, color = {
            'connected': ('● JARVIS · Conectado', '#70dfa9'),
            'connecting': ('● JARVIS · Conectando', '#edc779'),
            'reconnecting': ('● JARVIS · Reconectando', '#edc779'),
            'disconnected': ('● JARVIS · Desconectado', '#ff939c'),
        }.get(state, ('● JARVIS · Sem estado', '#b6c4d5'))
        self.button.setText(label)
        self.button.setStyleSheet(f'color:{color};border:0px;text-align:left;')

    def place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 12, screen.bottom() - self.height() - 12)
