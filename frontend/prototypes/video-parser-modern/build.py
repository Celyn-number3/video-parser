from pathlib import Path
import base64
root=Path(__file__).resolve().parent
image=(root/'coast-preview.jpg').read_bytes()
data='data:image/jpeg;base64,'+base64.b64encode(image).decode()
html=(root/'index.template.html').read_text(encoding='utf-8').replace('__STYLES__',(root/'styles.css').read_text(encoding='utf-8')).replace('__SCRIPT__',(root/'app.js').read_text(encoding='utf-8')).replace('__IMAGE__',data)
(root/'index.html').write_text(html,encoding='utf-8',newline='')
print('Self-contained HTML:',len(html.encode()),'bytes; embedded image:',len(image))
