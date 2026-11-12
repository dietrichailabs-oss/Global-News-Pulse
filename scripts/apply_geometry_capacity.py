"""One exact, bounded geometry-capacity change; all other validation stays."""
import ast
from pathlib import Path
import subprocess
BASE='af18cc23d413a80eb33fad1a8f29f69c5a329a79'
path=Path('global_pulse/map_evidence.py')
raw=subprocess.check_output(['git','show',BASE+':'+path.as_posix()])
if path.read_bytes().replace(b'\r\n',b'\n')!=raw:raise RuntimeError('Geometry capacity baseline mismatch')
text=raw.decode('utf-8')
old='MAX_AREA_POINTS = 8192\n'
if text.count(old)!=1:raise RuntimeError('Geometry capacity anchor mismatch')
new=text.replace(old,'MAX_AREA_POINTS = 16384  # Supports the observed 10,094-point NWS area; still bounded.\n',1)
# Assert this is solely one constant assignment, not a validation bypass.
a,b=ast.parse(text),ast.parse(new)
for tree in (a,b):
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MAX_AREA_POINTS' for t in n.targets))
    node.value=ast.Constant(value=0)
if ast.dump(a)!=ast.dump(b):raise RuntimeError('Unexpected non-capacity geometry change')
path.write_text(new,encoding='utf-8',newline='\n')
print('GP_GEOMETRY_CAPACITY_16384_ONLY_OTHER_VALIDATION_UNCHANGED')
