import yaml
import json
import os

for root, subFolders, files in os.walk('.'):
    # print root, subFolders, files
    for filename in files:
        if filename[-5:] == '.json':
            dataMap = json.loads(open(os.path.join(root, filename), 'r').read())
            yamlStr = yaml.safe_dump(dataMap, open(os.path.join(root, '%s.yaml' % filename[:-5]), 'w'))
