#!/usr/bin/env python3
"""Test script to check camera detection API."""

import requests
import json

try:
    response = requests.get('http://localhost:8000/api/west/camera/status')
    data = response.json()
    print('Camera Status:')
    print('  camera_ok:', data.get('camera_ok'))
    print('  last_frame_ts:', data.get('last_frame_ts'))
    print('  detections:', len(data.get('detections', [])), 'found')
    
    detections = data.get('detections', [])
    if detections:
        print('\nDetections (first 5):')
        for d in detections[:5]:
            print('  -', d.get('cls_raw'), '->', d.get('cls_mapped'), 'conf=' + str(round(d.get('conf', 0), 2)))
        if len(detections) > 5:
            print('  ... and', len(detections) - 5, 'more')
            
        # Aggregate by mapped class
        counts = {}
        for d in detections:
            cls = d.get('cls_mapped', 'unknown')
            counts[cls] = counts.get(cls, 0) + 1
        
        print('\nAggregated counts:')
        for cls, count in sorted(counts.items()):
            print('  ', cls + ':', count)
    else:
        print('\nNo detections yet.')
        
except Exception as e:
    print('Error:', e)
    import traceback
    traceback.print_exc()
