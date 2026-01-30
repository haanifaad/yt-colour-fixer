import sys
from pathlib import Path
from PySide6 import QtCore, QtWidgets

from yt_colour_fixer.pipeline import VideoPipeline


class PipelineWorker(QtCore.QObject):
    progress = QtCore.Signal(str, float)
    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, input_path: Path, output_dir: Path):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir

    @QtCore.Slot()
    def run(self) -> None:
        try:
            pipeline = VideoPipeline(self.input_path, self.output_dir, self._on_progress)
            result = pipeline.run()
            self.finished.emit(str(result))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _on_progress(self, message: str, value: float) -> None:
        self.progress.emit(message, value)


class MainWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YT Colour Fixer")
        self.setMinimumWidth(520)

        self.input_edit = QtWidgets.QLineEdit()
        self.output_edit = QtWidgets.QLineEdit()
        self.browse_input_button = QtWidgets.QPushButton("Browse Input")
        self.browse_output_button = QtWidgets.QPushButton("Browse Output")
        self.start_button = QtWidgets.QPushButton("Start Processing")
        self.progress_bar = QtWidgets.QProgressBar()
        self.status_label = QtWidgets.QLabel("Idle")
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)

        form_layout = QtWidgets.QFormLayout()
        form_layout.addRow("Input file", self._wrap_row(self.input_edit, self.browse_input_button))
        form_layout.addRow("Output folder", self._wrap_row(self.output_edit, self.browse_output_button))

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self.start_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.log_box)

        self.browse_input_button.clicked.connect(self._browse_input)
        self.browse_output_button.clicked.connect(self._browse_output)
        self.start_button.clicked.connect(self._start_processing)

        self.thread: QtCore.QThread | None = None
        self.worker: PipelineWorker | None = None

    def _wrap_row(self, line_edit: QtWidgets.QLineEdit, button: QtWidgets.QPushButton) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return container

    def _browse_input(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Input",
            str(Path.home()),
            "Video or ZIP (*.mp4 *.mov *.mkv *.zip)",
        )
        if path:
            self.input_edit.setText(path)

    def _browse_output(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output", str(Path.home()))
        if path:
            self.output_edit.setText(path)

    def _start_processing(self) -> None:
        input_path = Path(self.input_edit.text())
        output_dir = Path(self.output_edit.text())
        if not input_path.exists():
            QtWidgets.QMessageBox.warning(self, "Missing Input", "Please select a valid input file.")
            return
        if not output_dir.exists():
            QtWidgets.QMessageBox.warning(self, "Missing Output", "Please select a valid output directory.")
            return

        self.progress_bar.setValue(0)
        self.status_label.setText("Starting...")
        self.log_box.clear()
        self.start_button.setEnabled(False)

        self.thread = QtCore.QThread()
        self.worker = PipelineWorker(input_path, output_dir)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(self._finish_success)
        self.worker.failed.connect(self._finish_failure)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_thread)

        self.thread.start()

    @QtCore.Slot(str, float)
    def _update_progress(self, message: str, value: float) -> None:
        self.status_label.setText(message)
        self.progress_bar.setValue(int(value * 100))
        self.log_box.appendPlainText(f"{message} ({value:.2f})")

    @QtCore.Slot(str)
    def _finish_success(self, output_path: str) -> None:
        self.status_label.setText("Complete")
        self.progress_bar.setValue(100)
        self.log_box.appendPlainText(f"Output saved: {output_path}")
        QtWidgets.QMessageBox.information(self, "Done", f"Output saved: {output_path}")
        self.start_button.setEnabled(True)

    @QtCore.Slot(str)
    def _finish_failure(self, error: str) -> None:
        self.status_label.setText("Failed")
        self.log_box.appendPlainText(f"Error: {error}")
        QtWidgets.QMessageBox.critical(self, "Error", error)
        self.start_button.setEnabled(True)

    def _cleanup_thread(self) -> None:
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
