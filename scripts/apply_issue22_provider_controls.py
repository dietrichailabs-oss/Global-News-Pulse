"""One-time, exact-source integration; never run against integrated files."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path

EXPECTED = {
    "global_pulse/controller.py": "9dbfdc5fcc5996a6048a8e71ef44b2c702f02dd9",
    "global_pulse/ui.py": "e16a258d050ffad90a6cc2a89e85be48a6c39dd6",
}


def replace_method(text, class_name, method, replacement):
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    matches = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method]
    if len(matches) != 1:
        raise SystemExit(f"Expected one {class_name}.{method}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    return "".join(lines[:node.lineno - 1]) + replacement.rstrip() + "\n" + "".join(lines[node.end_lineno:])


def main():
    sources = {}
    for name, expected in EXPECTED.items():
        raw = Path(name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != expected:
            raise SystemExit(f"Exact baseline refused: {name}; do not reapply on integrated files")
        sources[name] = raw.decode("utf-8")
    controller = replace_method(sources["global_pulse/controller.py"], "Controller", "_apply_sources", '''    def _apply_sources(self):
        from .source_availability import enabled_ids
        enabled = enabled_ids(self.catalog, self.get_setting("enabled_sources", None))
        self.scheduler.set_sources([dict(source, enabled=source["id"] in enabled)
                                    for source in self.catalog])

    def set_source_enabled(self, source_id, enabled):
        """Explicit provider-ID action; never starts monitoring or bypasses due times."""
        from .source_availability import capability
        if self._closed:
            raise RuntimeError("Controller is closed")
        if type(enabled) is not bool or not isinstance(source_id, str):
            raise ValueError("A provider identity and boolean state are required")
        source = next((s for s in self.catalog if s["id"] == source_id), None)
        if source is None:
            raise ValueError("Provider is no longer configured")
        if enabled and not capability(source)[0]:
            raise ValueError("This provider has no eligible configured collector")
        preference = self.get_setting("enabled_sources", None)
        requested = ({s["id"] for s in self.catalog if s.get("enabled")}
                     if preference is None else set(preference) if isinstance(preference, list) else set())
        if enabled:
            requested.add(source_id)
        else:
            requested.discard(source_id)
        self.set_setting("enabled_sources", sorted(requested))
        return enabled
''')
    ui = sources["global_pulse/ui.py"]
    for method, target in (("_build_sources", "build_sources"), ("_populate_sources", "populate_sources"),
                           ("_source_selected", "source_selected"), ("_populate_source_preferences", "populate_preferences")):
        ui = replace_method(ui, "MainWindow", method,
            f"    def {method}(self):\n        from .provider_actions import {target}\n        return {target}(self)\n")
    old = 'if check.isChecked() and check.isEnabled():enabled.append(source_id)'
    new = 'if isinstance(check,QCheckBox) and check.isChecked() and check.isEnabled():enabled.append(source_id)'
    if ui.count(old) != 1:
        raise SystemExit("Exact Settings collection loop not found")
    ui = ui.replace(old, new)
    # Validate all replacements before writing either file.
    for text in (controller, ui):
        ast.parse(text)
    for name, text in (("global_pulse/controller.py", controller), ("global_pulse/ui.py", ui)):
        Path(name).write_bytes(text.encode("utf-8"))
        print("GP_PROVIDER_CONTROL_INTEGRATED", name)


if __name__ == "__main__":
    main()
