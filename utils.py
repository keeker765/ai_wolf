import json


def print_json(data:dict):
    print(json.dumps(data, indent=4, ensure_ascii=False))