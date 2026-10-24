"""把 mvp_data.json 嵌入 app_src.html，產生根目錄的 index.html。"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(HERE, 'app_src.html'), encoding='utf-8').read()
d = open(os.path.join(HERE, 'mvp_data.json'), encoding='utf-8').read()
assert '</' not in d
open(os.path.join(HERE, '..', 'index.html'), 'w', encoding='utf-8').write(s.replace('__DATA__', d))
print('wrote index.html')
