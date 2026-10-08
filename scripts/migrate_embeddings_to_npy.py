# -*- coding: utf-8 -*-
"""把 embeddings.json 转成 embeddings.npy（float32 二进制，快10倍）"""
import json, os, numpy as np

src = 'data/embeddings.json'
dst = 'data/embeddings.npy'

print('读 JSON...')
d = json.load(open(src, encoding='utf-8'))
print('条数:', len(d))

# 按 index 排序，排成矩阵
keys = sorted(d.keys(), key=int)
n = len(keys)
dim = len(d[keys[0]])
mat = np.zeros((n, dim), dtype=np.float32)
for k in keys:
    mat[int(k)] = d[k]

np.save(dst, mat)
sz_json = os.path.getsize(src) / 1024 / 1024
sz_npy = os.path.getsize(dst) / 1024 / 1024
print(f'JSON: {sz_json:.1f} MB → NPY: {sz_npy:.1f} MB')
print('完成')
