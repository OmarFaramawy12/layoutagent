import json

data = {"shapes": [{"type": "rect", "w": 10, "h": 5}]}
with open("sample.json", "w") as f:
    json.dump(data, f, indent=2)
print("wrote sample.json")
