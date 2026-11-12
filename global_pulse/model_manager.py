"""Explicit, cancellable per-language downloads using the owned worker."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QMessageBox


class ModelManager(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller=controller
        # One reusable dialog per controller; closing hides it. This avoids a
        # queued deletion racing controller/Qt shutdown while downloads signal.
        self.setWindowTitle("Manage offline translation models")
        self.resize(620,300)
        layout=QVBoxLayout(self)
        note=QLabel("Available does not mean installed. Choose Download for each language.\n"
                    "Downloads require consent; translations stay local. Close leaves queued work running; Exit Completely cancels it.")
        note.setWordWrap(True);layout.addWidget(note)
        self.rows={}
        self.remove_buttons={}
        for code,item in controller.translator.catalog.items():
            row=QHBoxLayout();name=QLabel(f"{item['name']} → English\n{item['size_bytes']/1_000_000:.1f} MB")
            status=QLabel();status.setWordWrap(True)
            progress=QProgressBar();progress.setRange(0,100);progress.setVisible(False)
            download=QPushButton("Download");download.setAccessibleName(f"Download {item['name']} model")
            cancel=QPushButton("Cancel");cancel.setEnabled(False)
            remove=QPushButton("Remove local model");remove.setEnabled(False)
            download.clicked.connect(lambda checked=False,c=code:controller.download_translation_model(c,self))
            cancel.clicked.connect(lambda checked=False,c=code:controller.cancel_model_download(c))
            remove.clicked.connect(lambda checked=False,c=code:self.remove_model(c))
            row.addWidget(name);row.addWidget(status,1);row.addWidget(progress);row.addWidget(download);row.addWidget(cancel);row.addWidget(remove)
            layout.addLayout(row);self.rows[code]=(status,progress,download,cancel);self.remove_buttons[code]=remove
        close=QPushButton("Close");close.clicked.connect(self.close);layout.addWidget(close)
        controller.model_download_changed.connect(self.update_status)
        controller.model_download_progress.connect(self.update_progress)
        self.refresh()

    def refresh(self):
        for code in self.rows:
            text=("Queued / downloading" if code in self.controller._model_jobs.values() else
                  "Installed" if self.controller.translator.installed(code) else "Available — not installed")
            self.update_status(code,text)

    def update_status(self,code,text):
        if code not in self.rows:return
        status,progress,download,cancel=self.rows[code]
        remove=self.remove_buttons[code]
        busy=code in self.controller._model_jobs.values()
        installed=self.controller.translator.installed(code)
        status.setText(text)
        download.setText("Installed" if installed else "Retry" if "fail" in text.lower() else "Download")
        download.setEnabled(not busy and not installed);cancel.setEnabled(busy);remove.setEnabled(installed and not busy)
        progress.setVisible(busy)
        if busy:progress.setRange(0,0)

    def update_progress(self,code,received,total):
        if code not in self.rows:return
        status,progress,_,_=self.rows[code]
        progress.setRange(0,100);progress.setValue(int(received*100/max(1,total)))
        status.setText(f"Downloading {received/1_000_000:.1f} / {total/1_000_000:.1f} MB")


    def remove_model(self, code):
        item=self.controller.translator.catalog.get(code,{})
        if not self.controller.translator.installed(code):
            self.refresh();return
        answer=QMessageBox.question(
            self,
            "Remove local translation model?",
            f"Remove the installed {item.get('name',code)} → English model from this computer?\n\n"
            "This removes only that reviewed local model. Event history and separately exported files are unchanged.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            removed=self.controller.remove_translation_model(code)
            self.update_status(code,"Removed from this computer" if removed else "Model is busy or already absent")
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,"Model could not be removed",str(exc))
        self.refresh()
