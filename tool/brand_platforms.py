"""Apply FloraMW names, permissions and raster icon to generated runners.
Requires Pillow: python3 -m pip install pillow
Run after flutter create from the project root.
"""
from pathlib import Path
from PIL import Image
import json
root=Path(__file__).resolve().parents[1]
icon=Image.open(root/'assets/icon.png').convert('RGB')
manifest=root/'android/app/src/main/AndroidManifest.xml'
if manifest.exists():
 text=manifest.read_text().replace('android:label="floramw"','android:label="FloraMW"')
 manifest.write_text(text)
 for density,size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
  folder=root/f'android/app/src/main/res/mipmap-{density}'
  folder.mkdir(parents=True,exist_ok=True)
  icon.resize((size,size),Image.Resampling.LANCZOS).save(folder/'ic_launcher.png')
 for folder in ['drawable','drawable-v21']:
  p=root/f'android/app/src/main/res/{folder}/launch_background.xml'
  p.parent.mkdir(parents=True,exist_ok=True)
  p.write_text('<?xml version="1.0" encoding="utf-8"?><layer-list xmlns:android="http://schemas.android.com/apk/res/android"><item><shape android:shape="rectangle"><solid android:color="#244c3c"/></shape></item><item android:gravity="center" android:drawable="@mipmap/ic_launcher"/></layer-list>')
plist=root/'ios/Runner/Info.plist'
if plist.exists():
 import plistlib
 data=plistlib.loads(plist.read_bytes())
 data['CFBundleDisplayName']='FloraMW'
 data['CFBundleName']='FloraMW'
 data['NSCameraUsageDescription']='FloraMW uses your camera to photograph plants when you choose to.'
 data['NSPhotoLibraryUsageDescription']='FloraMW lets you select a plant photograph from your library.'
 plist.write_bytes(plistlib.dumps(data,sort_keys=False))
 icons=root/'ios/Runner/Assets.xcassets/AppIcon.appiconset'
 contents=icons/'Contents.json'
 if contents.exists():
  spec=json.loads(contents.read_text())
  for n,entry in enumerate(spec['images']):
   size=int(float(entry['size'].split('x')[0])*float(entry['scale'].rstrip('x')))
   name=f'FloraMW-{n}-{size}.png'
   icon.resize((size,size),Image.Resampling.LANCZOS).save(icons/name)
   entry['filename']=name
  contents.write_text(json.dumps(spec,indent=2)+'\n')
print('Applied available Android/iOS branding and permissions.')
launch=root/'ios/Runner/Assets.xcassets/LaunchImage.imageset'
if launch.exists():
 for filename,size in [('LaunchImage.png',160),('LaunchImage@2x.png',320),('LaunchImage@3x.png',480)]:
  icon.resize((size,size),Image.Resampling.LANCZOS).save(launch/filename)
 story=root/'ios/Runner/Base.lproj/LaunchScreen.storyboard'
 if story.exists():
  text=story.read_text()
  import re
  text=re.sub(r'<color key="backgroundColor"[^>]*/>', '<color key="backgroundColor" red="0.141" green="0.298" blue="0.235" alpha="1" colorSpace="custom" customColorSpace="sRGB"/>',text)
  story.write_text(text)
