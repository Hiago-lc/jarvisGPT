"""Read-only desktop mirror; input always targets the real desktop."""
import platform
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QCursor, QPainter, QColor
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout


class DesktopMonitor(QDialog):
    def __init__(self, stop, back):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('JARVIS — desktop ao vivo')
        self.setStyleSheet('QDialog {background:#001018;color:#00d9ee;} QLabel {color:#c6f7ff;} QPushButton {padding:8px;background:#003541;color:white;}')
        self.resize(390, 360)
        self.running = False
        self.returned = False
        self.excluded = False
        self._stop = stop
        self._back = back
        layout = QVBoxLayout(self)
        self.status = QLabel('Desktop ao vivo — somente visualização')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.picture = QLabel('Preparando prévia…')
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(240, 135)
        layout.addWidget(self.picture, 1)
        self.detail = QLabel('O Jarvis controla o desktop real. Esta imagem não recebe cliques.')
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        row = QHBoxLayout()
        self.stop_button = QPushButton('PARAR')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)
        button = QPushButton('Voltar ao Jarvis')
        button.clicked.connect(self.back)
        row.addWidget(button)
        layout.addLayout(row)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 12, screen.top() + 24)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self._exclude_from_capture()

    def _exclude_from_capture(self):
        if platform.system() != 'Windows':
            return
        try:
            import ctypes
            from ctypes import wintypes
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user.SetWindowDisplayAffinity.restype = wintypes.BOOL
            self.excluded = bool(user.SetWindowDisplayAffinity(int(self.winId()), 0x11))
        except Exception:
            self.excluded = False

    def refresh(self):
        if not self.isVisible():
            return
        if not self.excluded:
            self.picture.setText('Prévia indisponível: o sistema não permitiu excluir\no painel da captura para evitar imagem recursiva.\nA automação continua com o painel recolhido nas entradas.')
            return
        screen = QApplication.primaryScreen()
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            self.picture.setText('Captura indisponível neste momento.')
            return
        # Root-window captures usually omit the hardware cursor.
        painter = QPainter(pixmap)
        painter.setPen(QColor('#00ff88'))
        painter.setBrush(QColor('#00ff88'))
        cursor = QCursor.pos() - screen.geometry().topLeft()
        painter.drawEllipse(QPointF(cursor), 5, 5)
        painter.end()
        self.picture.setPixmap(pixmap.scaled(self.picture.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def begin(self, goal):
        self.returned = False
        self.running = True
        self.stop_button.setEnabled(True)
        self.status.setText('Executando: ' + goal[:240])

    def finish(self, steps):
        self.running = False
        self.stop_button.setEnabled(False)
        self.status.setText(f'Execução encerrada após {steps} entradas. O resultado está no chat do Jarvis.')

    def stop(self):
        self._stop()
        self.status.setText('Interrupção solicitada. Aguardando a etapa atual retornar…')

    def back(self):
        self.returned = True
        if self.running:
            self.stop()
        self._back()
        self.hide()

    def closeEvent(self, event):
        self.returned = True
        if self.running:
            self._stop()
        self._back()
        event.accept()
