#!/usr/bin/env python
# -*- coding: utf-8 -*-
with open('metadata_source.json', 'r') as f:
    contents = f.readlines()

# versions start
v_start = 0
v_stop = 0

for i in range(len(contents)):
    ln = contents[i]
    if "\"version\"" in ln:
        v_stop = i
    if "\"versions\"" in ln:
        v_start = i

# remove from v_start+1 do v_stop-1
index = range(v_start+1, v_stop-1)
new_contents = [element for i, element in enumerate(contents) if i not in index]

with open('metadata.json', 'w') as f:
    f.writelines(new_contents)
