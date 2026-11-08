"""Standard-library-only frontend resource checks."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
credits=json.loads((root/'assets/photo_credits.json').read_text())
assert set(credits)=={'hibiscus','periwinkle','marigold','frangipani'}
for key,record in credits.items():
    data=(root/record['asset']).read_bytes()
    assert data[:2]==b'\xff\xd8' and len(data)>10000,key
    assert record['photographer'] and record['source'].startswith('https://')
    assert 'creativecommons.org/licenses/' in record['license_url']
packs=json.loads((root/'assets/translations.json').read_text())
assert set(packs)=={'en','ny','yao','tum','swk','lon','tog'}
for code,pack in packs.items():
    assert isinstance(pack['strings'],dict)
    assert code=='en' or pack['status']=='native-review-required'
    for key,value in pack['strings'].items():
        assert isinstance(key,str) and isinstance(value,str) and value.strip()
for source in (root/'lib').rglob('*.dart'):
    for target in re.findall(r"import '([^']+)';",source.read_text()):
        if not target.startswith(('dart:','package:')): assert (source.parent/target).is_file()
ET.parse(root/'android/app/src/main/AndroidManifest.xml')
import plistlib
plist=plistlib.loads((root/'ios/Runner/Info.plist').read_bytes())
assert plist['CFBundleDisplayName']=='FloraMW'
assert plist['NSCameraUsageDescription'] and plist['NSPhotoLibraryUsageDescription']
print('PASS photographs, licences, translation resources, source imports and native metadata')
